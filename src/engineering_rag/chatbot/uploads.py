"""Secure upload intake: streaming to disk, validation, hashing, quarantine.

Everything a browser sends is untrusted. This module is the boundary that
turns an arbitrary multipart part into either a validated file in the staging
area or a typed rejection, and it deliberately does the checks in an order
that never costs more than it has to: cheap structural checks (extension,
declared type) before the file is read, then size while streaming, then a
real content-signature check, and only then a hash of the accepted bytes.

Threat notes:

- **Path traversal / device names**: the client filename is never used to
  build a path. It is reduced by ``utils.paths.safe_filename`` (which already
  handles ``..``, separators, and Windows reserved names like ``CON``) and the
  stored file is named by a server-generated document ID anyway. The original
  string survives only as *display* text.
- **Content-type lying**: a declared ``application/pdf`` is not trusted; the
  first bytes must actually be a ``%PDF-`` signature.
- **Zip bombs / oversized uploads**: the stream is aborted the moment it
  exceeds the configured limit, so a huge upload cannot fill the disk while
  being "validated" afterwards.
- **Partial writes**: a rejected or failed upload never remains in staging;
  the partial file is removed in a ``finally``.

Only PDF is accepted, because ``services/parser`` genuinely supports only
PDF. Advertising more would be a lie the ingestion pipeline could not honour.
"""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from engineering_rag.utils.paths import safe_filename

__all__ = [
    "ACCEPTED_EXTENSIONS",
    "ACCEPTED_MEDIA_TYPES",
    "PDF_SIGNATURE",
    "StagedUpload",
    "UploadLimits",
    "UploadRejected",
    "UploadRejectionCode",
    "stage_upload",
]

#: The parser service is PDF-only (`services/parser/preflight.py` is built on
#: pypdf/pdfminer/pypdfium2), so this is the complete accepted set.
ACCEPTED_EXTENSIONS: frozenset[str] = frozenset({".pdf"})
ACCEPTED_MEDIA_TYPES: frozenset[str] = frozenset({"application/pdf"})
PDF_SIGNATURE = b"%PDF-"


class UploadRejectionCode(str):
    """Stable machine-readable rejection codes (also used as API error codes)."""

    EMPTY_FILE = "UPLOAD_EMPTY_FILE"
    TOO_LARGE = "UPLOAD_TOO_LARGE"
    UNSUPPORTED_EXTENSION = "UPLOAD_UNSUPPORTED_EXTENSION"
    UNSUPPORTED_MEDIA_TYPE = "UPLOAD_UNSUPPORTED_MEDIA_TYPE"
    NOT_A_PDF = "UPLOAD_NOT_A_PDF"
    MISSING_FILENAME = "UPLOAD_MISSING_FILENAME"


class UploadRejected(Exception):
    """A rejected upload, carrying a stable code and a user-safe message.

    The message never contains a filesystem path or internal detail -- it is
    written to be shown directly in the UI.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class UploadLimits:
    """Configurable intake limits. Defaults are deliberately conservative for a laptop."""

    max_bytes: int = 100 * 1024 * 1024  # 100 MB
    max_pages: int = 2000

    def __post_init__(self) -> None:
        if self.max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if self.max_pages <= 0:
            raise ValueError("max_pages must be positive")


@dataclass(frozen=True)
class StagedUpload:
    """A validated file sitting in the staging area, not yet promoted to a document."""

    path: Path
    stored_filename: str
    display_name: str
    sha256: str
    byte_size: int
    media_type: str


def _validate_declared_shape(filename: str | None, declared_media_type: str | None) -> tuple[str, str]:
    """Cheap structural checks that need no file content at all."""
    if not filename or not filename.strip():
        raise UploadRejected(UploadRejectionCode.MISSING_FILENAME, "The upload is missing a filename.")

    display_name = filename.strip()
    suffix = Path(display_name).suffix.lower()
    if suffix not in ACCEPTED_EXTENSIONS:
        accepted = ", ".join(sorted(ACCEPTED_EXTENSIONS))
        raise UploadRejected(
            UploadRejectionCode.UNSUPPORTED_EXTENSION,
            f"Only {accepted} files are supported. This milestone's parser handles PDF only.",
        )

    # A missing content type is tolerated (some clients omit it); a *wrong*
    # one is not, because it signals a client that will mis-handle the reply.
    if declared_media_type:
        normalized = declared_media_type.split(";")[0].strip().lower()
        if normalized and normalized not in ACCEPTED_MEDIA_TYPES and normalized != "application/octet-stream":
            raise UploadRejected(
                UploadRejectionCode.UNSUPPORTED_MEDIA_TYPE,
                f"Unsupported content type {normalized!r}. Only application/pdf is accepted.",
            )
    return display_name, "application/pdf"


def stage_upload(
    chunks: Iterable[bytes],
    *,
    filename: str | None,
    staging_dir: Path,
    document_id: str,
    declared_media_type: str | None = None,
    limits: UploadLimits | None = None,
) -> StagedUpload:
    """Stream ``chunks`` into ``staging_dir`` and validate them, or raise :class:`UploadRejected`.

    The file is written under a server-generated name derived from
    ``document_id``; the client's filename never influences the path. On any
    rejection the partial file is deleted, so a failed upload leaves nothing
    behind.
    """
    effective_limits = limits or UploadLimits()
    display_name, media_type = _validate_declared_shape(filename, declared_media_type)

    staging_dir.mkdir(parents=True, exist_ok=True)
    # Server-generated name: safe by construction, not by sanitising input.
    target = staging_dir / f"{document_id}.pdf"

    digest = hashlib.sha256()
    total = 0
    head = b""
    wrote_anything = False

    try:
        with target.open("wb") as handle:
            for chunk in chunks:
                if not chunk:
                    continue
                total += len(chunk)
                if total > effective_limits.max_bytes:
                    raise UploadRejected(
                        UploadRejectionCode.TOO_LARGE,
                        f"The file exceeds the {effective_limits.max_bytes // (1024 * 1024)} MB "
                        "upload limit.",
                    )
                if len(head) < len(PDF_SIGNATURE):
                    head += chunk[: len(PDF_SIGNATURE) - len(head)]
                handle.write(chunk)
                digest.update(chunk)
                wrote_anything = True

        if not wrote_anything or total == 0:
            raise UploadRejected(UploadRejectionCode.EMPTY_FILE, "The file is empty (zero bytes).")

        # Signature check last among content checks: by now we know the file is
        # non-empty and within limits, so reading its first bytes is bounded.
        if not head.startswith(PDF_SIGNATURE):
            raise UploadRejected(
                UploadRejectionCode.NOT_A_PDF,
                "The file is not a valid PDF (its content does not start with a PDF signature).",
            )
    except Exception:
        target.unlink(missing_ok=True)
        raise

    return StagedUpload(
        path=target,
        stored_filename=safe_filename(display_name, fallback=f"{document_id}.pdf"),
        display_name=display_name,
        sha256=digest.hexdigest(),
        byte_size=total,
        media_type=media_type,
    )


def promote_staged_upload(staged: StagedUpload, destination_dir: Path) -> Path:
    """Move a validated staged file into its durable location, returning the new path."""
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / staged.path.name
    shutil.move(str(staged.path), str(destination))
    return destination


def discard_staged_upload(staged: StagedUpload) -> None:
    """Remove a staged file that will not be promoted. Safe to call twice."""
    staged.path.unlink(missing_ok=True)


def iter_file_chunks(path: Path, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
    """Yield a local file's bytes -- the same interface :func:`stage_upload` consumes."""
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk_size)
            if not block:
                return
            yield block
