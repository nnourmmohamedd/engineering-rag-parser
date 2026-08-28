"""Chatbot application configuration: paths, limits, worker and server settings.

Deliberately separate from the pipeline profiles (``configs/*.yaml``): those
describe *how a document is processed*, this describes *how the local
application runs*. The retrieval/answering profiles are still the single
source of truth for models, gates and token budgets -- nothing here overrides
them.

Every path is repository-relative and resolved lazily, matching
``utils/paths.py``'s convention, so importing this module never depends on
the working directory.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from engineering_rag.utils.paths import default_output_root

__all__ = ["ChatbotConfig", "ServerConfig", "StorageConfig", "WorkerConfig", "load_chatbot_config"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class StorageConfig(_Frozen):
    """Where the application's own durable state and uploaded files live."""

    root: Path = Field(
        default=Path("data/chatbot"),
        description="Base directory for the registry database, uploads and staging.",
    )
    max_upload_bytes: int = Field(default=100 * 1024 * 1024, gt=0)
    max_pages: int = Field(default=2000, gt=0)

    @property
    def database_path(self) -> Path:
        return self.root / "registry.sqlite3"

    @property
    def uploads_dir(self) -> Path:
        """Durable location for accepted source documents."""
        return self.root / "uploads"

    @property
    def staging_dir(self) -> Path:
        """Quarantine: files live here until validation succeeds."""
        return self.root / "staging"

    @property
    def backups_dir(self) -> Path:
        """Pre-mutation index copies, used to roll back a failed ingestion."""
        return self.root / "backups"


class WorkerConfig(_Frozen):
    """Bounded local ingestion worker.

    ``concurrency`` defaults to 1 on purpose: Docling conversion, BGE
    embedding and a local cross-encoder are all resource-heavy, and running
    two at once on a laptop makes both slower while risking index contention.
    """

    concurrency: int = Field(default=1, ge=1, le=4)
    poll_interval_s: float = Field(default=0.25, gt=0)


class ServerConfig(_Frozen):
    """HTTP server binding and CORS.

    Binds to loopback by default. This application ships no authentication,
    so exposing it beyond ``127.0.0.1`` without adding authentication and
    HTTPS in front would publish every indexed document -- see
    ``docs/chatbot/SECURITY.md``.
    """

    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8000, ge=1, le=65535)
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"],
        description="Exact allowed browser origins. Never '*' -- that would let any page call this API.",
    )

    @property
    def binds_to_loopback_only(self) -> bool:
        return self.host in {"127.0.0.1", "localhost", "::1"}


class ChatbotConfig(_Frozen):
    """Everything the local chatbot application needs to run."""

    storage: StorageConfig = StorageConfig()
    worker: WorkerConfig = WorkerConfig()
    server: ServerConfig = ServerConfig()

    answering_profile: Path = Field(default=Path("configs/answering_production.yaml"))
    retrieval_profile: Path = Field(default=Path("configs/retrieval_production.yaml"))
    chunker_profile: Path = Field(
        default=Path("configs/chunker_bge.yaml"),
        description=(
            "Must stay aligned with the indexing profile's embedding model: "
            "the chunker measures token counts with the tokenizer named here, "
            "and the indexer rejects any chunk run measured with a mismatched "
            "tokenizer before it ever reaches Chroma."
        ),
    )
    parser_output_root: Path = Field(default_factory=lambda: default_output_root() / "parser")
    chunker_output_root: Path = Field(default_factory=lambda: default_output_root() / "chunker")

    default_retrieval_mode: str = Field(
        default="vector",
        description="Matches the answering profile's production default; the UI may override per query.",
    )
    log_level: str = Field(default="INFO")


def load_chatbot_config() -> ChatbotConfig:
    """Build the configuration, applying ``ENGRAG_CHATBOT_*`` environment overrides.

    Environment variables exist so the dev/test/CI harness can redirect state
    to a temporary directory without editing files. Only non-secret operational
    settings are overridable; models and gates come from the pipeline profiles.
    """
    storage_kwargs: dict[str, Any] = {}
    if root := os.environ.get("ENGRAG_CHATBOT_DATA_ROOT"):
        storage_kwargs["root"] = Path(root)
    if raw_max := os.environ.get("ENGRAG_CHATBOT_MAX_UPLOAD_BYTES"):
        storage_kwargs["max_upload_bytes"] = int(raw_max)

    server_kwargs: dict[str, Any] = {}
    if host := os.environ.get("ENGRAG_CHATBOT_HOST"):
        server_kwargs["host"] = host
    if port := os.environ.get("ENGRAG_CHATBOT_PORT"):
        server_kwargs["port"] = int(port)
    if origins := os.environ.get("ENGRAG_CHATBOT_CORS_ORIGINS"):
        server_kwargs["cors_origins"] = [o.strip() for o in origins.split(",") if o.strip()]

    worker_kwargs: dict[str, Any] = {}
    if concurrency := os.environ.get("ENGRAG_CHATBOT_WORKER_CONCURRENCY"):
        worker_kwargs["concurrency"] = int(concurrency)

    top_level: dict[str, Any] = {}
    if profile := os.environ.get("ENGRAG_CHATBOT_ANSWERING_PROFILE"):
        top_level["answering_profile"] = Path(profile)
    if profile := os.environ.get("ENGRAG_CHATBOT_RETRIEVAL_PROFILE"):
        top_level["retrieval_profile"] = Path(profile)

    return ChatbotConfig(
        storage=StorageConfig(**storage_kwargs),
        worker=WorkerConfig(**worker_kwargs),
        server=ServerConfig(**server_kwargs),
        **top_level,
    )
