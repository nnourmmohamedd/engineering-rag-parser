"""Internal working representation used while a document moves through the
chunking pipeline, before final ordering/IDs are assigned.

Not part of the public output contract — see :mod:`.models` for that.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import ContentType, ProvenanceRecord, SplitMethod, TableFragmentMeta

__all__ = ["WorkingChunk"]


@dataclass
class WorkingChunk:
    """A chunk mid-pipeline: content is final, but its position/ID are not.

    ``parent_chunk_key`` and ``merged_from_keys`` hold *provisional* chunk IDs
    (computed from a pre-split/pre-merge position, see
    :mod:`.linking`) — deterministic lineage markers, not necessarily IDs of
    rows that appear in the final ``chunks.jsonl``.
    """

    text: str
    content_type: ContentType
    heading_path: list[str] = field(default_factory=list)
    section_title: str | None = None
    captions: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    page_numbers: list[int] = field(default_factory=list)
    provenance: list[ProvenanceRecord] = field(default_factory=list)
    source_element_refs: list[str] = field(default_factory=list)

    split_method: SplitMethod = SplitMethod.HIERARCHICAL
    was_recursively_split: bool = False
    overlap_tokens_before: int = 0

    parent_chunk_key: str | None = None
    merged_from_keys: list[str] | None = None

    table_metadata: TableFragmentMeta | None = None
    figure_asset_path: str | None = None
    figure_page_no: int | None = None

    is_atomic_overflow: bool = False
    warnings: list[str] = field(default_factory=list)
    parser_warnings: list[str] = field(default_factory=list)

    token_count: int = 0

    def retrieval_text(self, *, include_heading_context: bool) -> str:
        """Build ``retrieval_text``: ``text`` optionally prefixed with real context.

        Never invents facts — only prepends the heading path / section title /
        captions that already exist on this chunk.
        """
        if not include_heading_context:
            return self.text
        prefix_parts: list[str] = []
        if self.heading_path:
            prefix_parts.append(" > ".join(self.heading_path))
        if self.captions:
            prefix_parts.append(" | ".join(self.captions))
        if not prefix_parts:
            return self.text
        return f"{' :: '.join(prefix_parts)}\n{self.text}"
