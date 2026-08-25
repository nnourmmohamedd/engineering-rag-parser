"""Production embedding-service implementation: ``BAAI/bge-base-en-v1.5`` via sentence-transformers.

Uses the normal Hugging Face cache (no custom caching layer). Never commits
weights to the repository: nothing here writes model files into the repo
tree, and ``.gitignore`` already excludes local cache directories a
developer might point ``HF_HOME`` at.
"""

from __future__ import annotations

import logging
import os
import time

from .config import EmbedderConfig
from .errors import EmptyQueryError, ModelLoadError, VectorValidationError
from .interface import EmbeddingService
from .models import EmbeddingBatchStats, EmbeddingRecord, ModelInfo
from .validation import validate_vector

__all__ = ["BGEEmbeddingService"]

logger = logging.getLogger(__name__)

_INSTALL_HINT = (
    "The 'sentence-transformers' package (and network access to Hugging Face Hub on first use, "
    "or a pre-populated local cache with offline=true) is required. Install it with "
    'pip install -e ".[indexing]".'
)


class BGEEmbeddingService(EmbeddingService):
    """Loads ``SentenceTransformer(config.model_name)`` once and reuses it for every call."""

    def __init__(self, config: EmbedderConfig) -> None:
        self._config = config
        if config.offline:
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ModelLoadError(_INSTALL_HINT) from exc

        device = _resolve_device(config.device)
        logger.info("Loading embedding model %s on device=%s", config.model_name, device)
        try:
            self._model = SentenceTransformer(
                config.model_name,
                revision=config.model_revision,
                trust_remote_code=config.trust_remote_code,
                device=device,
            )
        except Exception as exc:  # noqa: BLE001 - surface a clean, actionable message
            hint = (
                " HF_HUB_OFFLINE is set but the model is not cached locally."
                if config.offline
                else " If this is a network error, retry online once, or cache the model and set offline=true."
            )
            raise ModelLoadError(
                f"Could not load embedding model {config.model_name!r}.{hint} {_INSTALL_HINT}"
            ) from exc

        self._model.eval()
        self._device = device
        self._resolved_revision = _resolve_revision(config.model_name, config.model_revision)
        if hasattr(self._model, "get_embedding_dimension"):
            dimension = self._model.get_embedding_dimension()
        else:  # pragma: no cover - back-compat with sentence-transformers < 6.0
            dimension = self._model.get_sentence_embedding_dimension()
        self._dimension = int(dimension or config.expected_dimension)
        self._max_seq_length = int(getattr(self._model, "max_seq_length", config.maximum_sequence_length))
        self._tokenizer_name = config.model_name

        if self._dimension != config.expected_dimension:
            raise ModelLoadError(
                f"Model {config.model_name!r} produces {self._dimension}-d vectors, "
                f"but expected_dimension={config.expected_dimension} in configuration."
            )

    def model_info(self) -> ModelInfo:
        return ModelInfo(
            model_name=self._config.model_name,
            resolved_revision=self._resolved_revision,
            dimension=self._dimension,
            max_seq_length=self._max_seq_length,
            device=self._device,
            tokenizer_name=self._tokenizer_name,
            normalize_embeddings=self._config.normalize_embeddings,
        )

    def embed_passages(
        self, chunk_ids: list[str], texts: list[str]
    ) -> tuple[list[EmbeddingRecord], EmbeddingBatchStats]:
        if len(chunk_ids) != len(texts):
            raise ValueError(f"chunk_ids ({len(chunk_ids)}) and texts ({len(texts)}) length mismatch")
        if not texts:
            return [], EmbeddingBatchStats(
                input_count=0, batch_size=self._config.batch_size, duration_s=0.0, vectors_per_second=0.0
            )

        prefixed = [self._config.document_prefix + t for t in texts]

        started = time.perf_counter()
        try:
            import torch

            with torch.no_grad():
                vectors = self._model.encode(
                    prefixed,
                    batch_size=self._config.batch_size,
                    normalize_embeddings=self._config.normalize_embeddings,
                    convert_to_numpy=True,
                    show_progress_bar=False,
                )
        except Exception as exc:  # noqa: BLE001
            raise VectorValidationError(f"Batch embedding failed for {len(texts)} passage(s): {exc}") from exc
        duration = time.perf_counter() - started

        records: list[EmbeddingRecord] = []
        for cid, vec in zip(chunk_ids, vectors, strict=True):
            vec_list = [float(x) for x in vec]
            validate_vector(
                vec_list,
                chunk_id=cid,
                expected_dimension=self._dimension,
                normalize_expected=self._config.normalize_embeddings,
            )
            records.append(EmbeddingRecord(chunk_id=cid, vector=vec_list))

        stats = EmbeddingBatchStats(
            input_count=len(texts),
            batch_size=self._config.batch_size,
            duration_s=round(duration, 4),
            vectors_per_second=round(len(texts) / duration, 2) if duration > 0 else 0.0,
        )
        logger.info(
            "Embedded %d passage(s) in %.2fs (%.1f vec/s)",
            stats.input_count,
            stats.duration_s,
            stats.vectors_per_second,
        )
        return records, stats

    def embed_query(self, text: str) -> list[float]:
        if not text or not text.strip():
            raise EmptyQueryError("Query text must not be empty or whitespace-only")

        prefixed = self._config.query_prefix + text
        try:
            import torch

            with torch.no_grad():
                vector = self._model.encode(
                    [prefixed],
                    normalize_embeddings=self._config.normalize_embeddings,
                    convert_to_numpy=True,
                    show_progress_bar=False,
                )[0]
        except Exception as exc:  # noqa: BLE001
            raise VectorValidationError(f"Query embedding failed: {exc}") from exc

        vec_list = [float(x) for x in vector]
        validate_vector(
            vec_list,
            chunk_id=None,
            expected_dimension=self._dimension,
            normalize_expected=self._config.normalize_embeddings,
        )
        return vec_list

    def health_check(self) -> None:
        vector = self.embed_query("health check smoke test")
        validate_vector(
            vector,
            chunk_id=None,
            expected_dimension=self._dimension,
            normalize_expected=self._config.normalize_embeddings,
        )


def _resolve_device(requested: str) -> str:
    if requested != "auto":
        return requested
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
    except ImportError:  # pragma: no cover - torch always present via sentence-transformers
        pass
    return "cpu"


def _resolve_revision(model_name: str, pinned_revision: str | None) -> str | None:
    """Best-effort: read the resolved commit hash from the local HF cache. Never fails the run."""
    if pinned_revision is not None:
        return pinned_revision
    try:
        from huggingface_hub import HfApi

        return HfApi().model_info(model_name).sha
    except Exception:  # noqa: BLE001 - best-effort only, e.g. offline/no network
        try:
            from huggingface_hub import scan_cache_dir

            cache = scan_cache_dir()
            for repo in cache.repos:
                if repo.repo_id == model_name:
                    for revision in repo.revisions:
                        return revision.commit_hash
        except Exception:  # noqa: BLE001
            return None
    return None
