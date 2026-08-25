"""Validated, hashable configuration owned by the retrieval domain.

Mirrors ``databases/chroma/config.py`` and ``services/embedder/config.py``:
frozen, ``extra="forbid"`` pydantic models validated at parse time. Composed
into the top-level profile by ``pipelines/retrieval_config.py`` alongside the
already-existing ``EmbedderConfig`` and ``ChromaConfig``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = ["RetrievalEvaluationConfig", "RetrievalSearchConfig"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RetrievalSearchConfig(_Frozen):
    """Operational limits and defaults for one ``search`` call."""

    default_top_k: int = Field(default=5, gt=0)
    maximum_top_k: int = Field(default=50, gt=0)
    allowed_metadata_filter_fields: list[str] = Field(
        default_factory=lambda: [
            "source_filename",
            "content_type",
            "document_id",
            "section_title",
            "chunk_run_id",
            "source_sha256",
        ],
        description="Chroma metadata fields a caller may filter on with an equality/scalar condition. "
        "JSON-encoded list fields (e.g. page_numbers, heading_path) are NOT supported as native list "
        "filters and are deliberately excluded — see docs/retrieval/ARCHITECTURE.md.",
    )
    query_max_length_chars: int = Field(default=2000, gt=0)
    timeout_s: float = Field(default=30.0, gt=0)
    log_level: str = "INFO"

    @model_validator(mode="after")
    def _validate(self) -> RetrievalSearchConfig:
        if self.default_top_k > self.maximum_top_k:
            raise ValueError(
                f"default_top_k ({self.default_top_k}) must not exceed maximum_top_k ({self.maximum_top_k})"
            )
        return self

    def effective_dict(self) -> dict[str, Any]:
        import json

        return json.loads(self.model_dump_json())


class RetrievalEvaluationConfig(_Frozen):
    """Configuration for the ``evaluate`` command."""

    dataset_path: str = Field(default="data/eval/retrieval_ground_truth.jsonl")
    k_values: list[int] = Field(default_factory=lambda: [1, 3, 5, 10])
    output_root: str = Field(default="data/output/retrieval")
    unanswerable_similarity_threshold: float = Field(
        default=0.55,
        gt=0,
        lt=1,
        description="Heuristic-only: an is_unanswerable case's top-1 similarity below this is judged "
        "'no good match found'. Not a validated relevance judgment — see docs/retrieval/EVALUATION.md.",
    )

    @model_validator(mode="after")
    def _validate(self) -> RetrievalEvaluationConfig:
        if not self.k_values:
            raise ValueError("k_values must not be empty")
        if any(k <= 0 for k in self.k_values):
            raise ValueError(f"every k in k_values must be > 0, got {self.k_values}")
        if sorted(set(self.k_values)) != sorted(self.k_values):
            raise ValueError(f"k_values must not contain duplicates: {self.k_values}")
        return self

    def effective_dict(self) -> dict[str, Any]:
        import json

        return json.loads(self.model_dump_json())
