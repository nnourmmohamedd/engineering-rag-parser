"""Top-level retrieval configuration: embedding + chroma + search + evaluation + logging.

Mirrors ``pipelines/indexing_config.py``'s conventions exactly: composes the
already-existing, independently-owned ``EmbedderConfig`` and ``ChromaConfig``
with retrieval-specific sections owned by ``services/retriever``. Every field
is validated at parse time, before any model is loaded or any database is
touched.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict

from engineering_rag.databases.chroma.config import ChromaConfig
from engineering_rag.services.embedder.config import EmbedderConfig
from engineering_rag.services.retriever.config import RetrievalEvaluationConfig, RetrievalSearchConfig

__all__ = ["RetrievalConfig", "load_retrieval_config"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RetrievalLoggingConfig(_Frozen):
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


class RetrievalConfig(_Frozen):
    """Composed, hashable configuration for retrieval search and evaluation runs."""

    profile: Literal["production"] = "production"

    embedding: EmbedderConfig = EmbedderConfig()
    chroma: ChromaConfig = ChromaConfig()
    search: RetrievalSearchConfig = RetrievalSearchConfig()
    evaluation: RetrievalEvaluationConfig = RetrievalEvaluationConfig()
    logging: RetrievalLoggingConfig = RetrievalLoggingConfig()

    def effective_dict(self) -> dict[str, Any]:
        return json.loads(self.model_dump_json())

    def config_hash(self) -> str:
        payload = json.dumps(self.effective_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_retrieval_config(path: Path | str | None = None, **overrides: Any) -> RetrievalConfig:
    """Load a full ``configs/retrieval_*.yaml`` profile, applying top-level overrides.

    Raises:
        FileNotFoundError: if an explicit path does not exist.
        ValueError: if the YAML does not describe a mapping.
        pydantic.ValidationError: if the effective configuration is invalid.
    """
    data: dict[str, Any] = {}
    if path is not None:
        cfg_path = Path(path)
        if not cfg_path.is_file():
            raise FileNotFoundError(f"Config file not found: {cfg_path}")
        loaded = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError(
                f"Config file must contain a YAML mapping, got {type(loaded).__name__}: {cfg_path}"
            )
        data = loaded
    data.update({k: v for k, v in overrides.items() if v is not None})
    return RetrievalConfig.model_validate(data)
