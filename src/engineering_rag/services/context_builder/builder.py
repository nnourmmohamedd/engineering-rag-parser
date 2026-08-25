"""Deterministic context selection: ranked retrieval hits -> a budgeted, citable :class:`ContextPackage`.

Pure domain logic. Imports :class:`~engineering_rag.services.retriever.models.RetrievalResponse`
for its input type only -- never ``chromadb``, never ``clients.ollama``. A
concrete :class:`~.neighbor_provider.NeighborProvider` is injected by the
caller (``pipelines/answering_pipeline.py``); this module never constructs
one itself.

Stages, in order (see ``docs/answering/GROUNDED_ANSWERING_ARCHITECTURE.md``
for the full rationale): reject malformed candidates -> deduplicate by
chunk_id -> deduplicate by content hash -> apply per-document/per-section
diversity limits while budgeting tokens, in the caller's ranked order ->
optional same-document neighbor expansion filling only leftover budget ->
assign citation IDs only now, in final selection order -> render sanitized,
delimited evidence blocks.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from engineering_rag.prompts.answering import format_evidence_block
from engineering_rag.services.retriever import RetrievalHit, RetrievalResponse

from .config import ContextBuilderConfig
from .models import (
    CONTEXT_SCHEMA_VERSION,
    ContextPackage,
    ExcludedCandidate,
    NeighborChunk,
    SelectedSource,
    query_hash,
)
from .neighbor_provider import NeighborProvider
from .token_counter import TokenCounter

__all__ = ["ContextBuilder"]

logger = logging.getLogger(__name__)


class ContextBuilder:
    """Builds one :class:`ContextPackage` from one retrieval response. Stateless across calls."""

    def __init__(
        self,
        config: ContextBuilderConfig,
        token_counter: TokenCounter,
        neighbor_provider: NeighborProvider | None = None,
    ) -> None:
        self._config = config
        self._token_counter = token_counter
        self._neighbor_provider = neighbor_provider

    def build(
        self,
        *,
        query: str,
        retrieval_response: RetrievalResponse,
        reserved_output_tokens: int,
    ) -> ContextPackage:
        started = time.perf_counter()
        config = self._config
        warnings: list[str] = []
        excluded: list[ExcludedCandidate] = []
        hits = retrieval_response.hits

        # Stage 1: reject malformed / provenance-incomplete candidates.
        valid_hits = []
        for hit in hits:
            if not hit.chunk_id or not hit.retrieval_text or not hit.retrieval_text.strip():
                excluded.append(
                    ExcludedCandidate(
                        chunk_id=hit.chunk_id or "(missing-chunk-id)",
                        document_id=hit.document_id,
                        source_filename=hit.source_filename,
                        reason="malformed_provenance",
                        detail="missing chunk_id or empty retrieval_text",
                    )
                )
                continue
            valid_hits.append(hit)

        # Stage 2: deduplicate by chunk_id, preserving the caller's ranked order.
        seen_ids: set[str] = set()
        deduped_hits = []
        for hit in valid_hits:
            if hit.chunk_id in seen_ids:
                excluded.append(
                    ExcludedCandidate(
                        chunk_id=hit.chunk_id,
                        document_id=hit.document_id,
                        source_filename=hit.source_filename,
                        reason="duplicate_chunk_id",
                        detail="chunk_id already present at a higher or equal rank",
                    )
                )
                continue
            seen_ids.add(hit.chunk_id)
            deduped_hits.append(hit)

        # Stage 3: deduplicate by content hash (configurable).
        seen_hashes: set[str] = set()
        candidates = []
        for hit in deduped_hits:
            if config.deduplicate_content and hit.content_hash:
                if hit.content_hash in seen_hashes:
                    excluded.append(
                        ExcludedCandidate(
                            chunk_id=hit.chunk_id,
                            document_id=hit.document_id,
                            source_filename=hit.source_filename,
                            reason="duplicate_content_hash",
                            detail=f"content_hash already selected: {hit.content_hash[:12]}",
                        )
                    )
                    continue
                seen_hashes.add(hit.content_hash)
            candidates.append(hit)

        # Stage 4: diversity limits + token budgeting, in ranked order. Deterministic:
        # identical input + config always produces the identical selection.
        per_doc_counts: dict[str, int] = {}
        per_section_counts: dict[str, int] = {}
        selected: list[SelectedSource] = []
        used_tokens = 0

        for hit in candidates:
            if len(selected) >= config.max_sources:
                excluded.append(
                    _excl(hit, "max_sources_reached", f"max_sources={config.max_sources} already selected")
                )
                continue
            doc_key = hit.document_id or "(unknown-document)"
            if per_doc_counts.get(doc_key, 0) >= config.max_sources_per_document:
                excluded.append(
                    _excl(
                        hit,
                        "per_document_limit",
                        f"max_sources_per_document={config.max_sources_per_document} reached for {doc_key!r}",
                    )
                )
                continue
            section_key = f"{doc_key}::{hit.section_title or '(no-section)'}"
            if per_section_counts.get(section_key, 0) >= config.max_sources_per_section:
                excluded.append(
                    _excl(
                        hit,
                        "per_section_limit",
                        f"max_sources_per_section={config.max_sources_per_section} reached for {section_key!r}",
                    )
                )
                continue

            token_count = self._token_counter.count(hit.retrieval_text)
            if token_count > config.max_context_tokens:
                excluded.append(
                    _excl(
                        hit,
                        "chunk_exceeds_budget_alone",
                        f"{token_count} tokens alone exceeds max_context_tokens={config.max_context_tokens}; "
                        "no safe truncation fallback is implemented, so the whole chunk is excluded",
                    )
                )
                continue
            if used_tokens + token_count > config.max_context_tokens:
                excluded.append(
                    _excl(
                        hit,
                        "token_budget_exceeded",
                        f"would use {used_tokens + token_count} of {config.max_context_tokens} budget tokens",
                    )
                )
                continue

            selected.append(
                SelectedSource(
                    citation_id="",
                    chunk_id=hit.chunk_id,
                    chunk_index=hit.chunk_index,
                    document_id=hit.document_id,
                    retrieval_text=hit.retrieval_text,
                    source_filename=hit.source_filename,
                    page_numbers=list(hit.page_numbers),
                    section_title=hit.section_title,
                    heading_path=list(hit.heading_path),
                    content_type=hit.content_type,
                    source_sha256=hit.source_sha256,
                    content_hash=hit.content_hash,
                    previous_chunk_id=hit.previous_chunk_id,
                    next_chunk_id=hit.next_chunk_id,
                    vector_rank=hit.vector_rank,
                    bm25_rank=hit.bm25_rank,
                    rrf_rank=hit.rrf_rank,
                    reranker_rank=hit.reranker_rank,
                    retrieval_rank=hit.final_rank or hit.rank,
                    similarity_score=hit.similarity_score,
                    bm25_score=hit.bm25_score,
                    rrf_score=hit.rrf_score,
                    reranker_score=hit.reranker_score,
                    is_neighbor=False,
                    selection_order=len(selected) + 1,
                    token_count=token_count,
                    selection_reason="directly_retrieved",
                )
            )
            used_tokens += token_count
            per_doc_counts[doc_key] = per_doc_counts.get(doc_key, 0) + 1
            per_section_counts[section_key] = per_section_counts.get(section_key, 0) + 1

        # Stage 5: optional same-document neighbor expansion, lower priority than direct
        # hits -- runs only after every direct hit has already claimed its budget share,
        # and only ever fills genuinely leftover budget.
        if config.neighbor_expansion_enabled and self._neighbor_provider is not None:
            already_selected_ids = {s.chunk_id for s in selected}
            for direct in list(selected):
                chain = self._walk_chain(direct.previous_chunk_id, "previous", config.neighbor_window)
                chain += self._walk_chain(direct.next_chunk_id, "next", config.neighbor_window)
                for neighbor in chain:
                    if neighbor.chunk_id in already_selected_ids:
                        continue
                    if neighbor.document_id != direct.document_id:
                        warnings.append(
                            f"neighbor {neighbor.chunk_id!r} of {direct.chunk_id!r} skipped: "
                            "belongs to a different document"
                        )
                        continue
                    if len(selected) >= config.max_sources:
                        excluded.append(
                            ExcludedCandidate(
                                chunk_id=neighbor.chunk_id,
                                document_id=neighbor.document_id,
                                source_filename=neighbor.source_filename,
                                reason="max_sources_reached",
                                detail="neighbor expansion: max_sources already reached",
                            )
                        )
                        continue
                    token_count = self._token_counter.count(neighbor.retrieval_text)
                    if used_tokens + token_count > config.max_context_tokens:
                        excluded.append(
                            ExcludedCandidate(
                                chunk_id=neighbor.chunk_id,
                                document_id=neighbor.document_id,
                                source_filename=neighbor.source_filename,
                                reason="token_budget_exceeded",
                                detail="neighbor expansion: would exceed max_context_tokens",
                            )
                        )
                        continue

                    selected.append(
                        SelectedSource(
                            citation_id="",
                            chunk_id=neighbor.chunk_id,
                            chunk_index=neighbor.chunk_index,
                            document_id=neighbor.document_id,
                            retrieval_text=neighbor.retrieval_text,
                            source_filename=neighbor.source_filename,
                            page_numbers=list(neighbor.page_numbers),
                            section_title=neighbor.section_title,
                            heading_path=list(neighbor.heading_path),
                            content_type=neighbor.content_type,
                            source_sha256=neighbor.source_sha256,
                            content_hash=neighbor.content_hash,
                            previous_chunk_id=neighbor.previous_chunk_id,
                            next_chunk_id=neighbor.next_chunk_id,
                            is_neighbor=True,
                            selection_order=len(selected) + 1,
                            token_count=token_count,
                            selection_reason="neighbor_expansion",
                        )
                    )
                    used_tokens += token_count
                    already_selected_ids.add(neighbor.chunk_id)

        # Stage 6: assign citation IDs only now, in final selection order.
        final_sources = [
            source.model_copy(update={"citation_id": f"S{i}"}) for i, source in enumerate(selected, start=1)
        ]

        context_text = "\n\n".join(
            format_evidence_block(
                citation_id=s.citation_id,
                source_filename=s.source_filename,
                page_numbers=s.page_numbers,
                chunk_id=s.chunk_id,
                text=s.retrieval_text,
            )
            for s in final_sources
        )
        context_token_count = self._token_counter.count(context_text)
        if context_token_count > config.max_context_tokens:
            warnings.append(
                f"rendered context_text is {context_token_count} tokens, exceeding max_context_tokens="
                f"{config.max_context_tokens} by delimiter overhead; absorbed by safety_margin_tokens"
            )

        if not final_sources:
            warnings.append("no sources survived selection: the context package is empty")

        source_hashes = sorted({s.source_sha256 for s in final_sources if s.source_sha256})

        return ContextPackage(
            context_schema_version=CONTEXT_SCHEMA_VERSION,
            query=query,
            query_hash=query_hash(query),
            retrieval_mode=retrieval_response.retrieval_mode,
            selected_sources=final_sources,
            excluded_candidates=excluded,
            total_candidates_received=len(hits),
            total_sources_selected=len(final_sources),
            context_token_count=context_token_count,
            token_budget=config.max_context_tokens,
            reserved_output_tokens=reserved_output_tokens,
            prompt_overhead_tokens=config.reserved_system_tokens + config.safety_margin_tokens,
            context_text=context_text,
            source_hashes=source_hashes,
            tokenizer_description=self._token_counter.description,
            warnings=warnings,
            selection_duration_s=round(time.perf_counter() - started, 6),
            generated_at_utc=datetime.now(timezone.utc),
        )

    def _walk_chain(self, start_id: str | None, direction: str, window: int) -> list[NeighborChunk]:
        """Fetch up to ``window`` chunks starting at ``start_id``, nearest-first, same direction only."""
        assert self._neighbor_provider is not None  # noqa: S101 - only called when a provider is set
        chain: list[NeighborChunk] = []
        current_id = start_id
        for _ in range(window):
            if not current_id:
                break
            neighbor = self._neighbor_provider.get_chunk(current_id)
            if neighbor is None:
                break
            chain.append(neighbor)
            current_id = neighbor.previous_chunk_id if direction == "previous" else neighbor.next_chunk_id
        return chain


def _excl(hit: RetrievalHit, reason: str, detail: str) -> ExcludedCandidate:
    return ExcludedCandidate(
        chunk_id=hit.chunk_id,
        document_id=hit.document_id,
        source_filename=hit.source_filename,
        reason=reason,  # type: ignore[arg-type]
        detail=detail,
    )
