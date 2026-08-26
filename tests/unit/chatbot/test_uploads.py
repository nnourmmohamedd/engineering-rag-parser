"""Upload intake: validation, path safety, hashing and failure cleanup.

These are security tests as much as behaviour tests: the upload endpoint is
the one place a browser hands this application arbitrary bytes and an
arbitrary filename.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engineering_rag.chatbot.uploads import (
    PDF_SIGNATURE,
    StagedUpload,
    UploadLimits,
    UploadRejected,
    UploadRejectionCode,
    discard_staged_upload,
    iter_file_chunks,
    promote_staged_upload,
    stage_upload,
)

MINIMAL_PDF = PDF_SIGNATURE + b"1.4\n%%EOF\n"


def _stage(tmp_path: Path, data: bytes, *, filename: str = "report.pdf", **kwargs) -> StagedUpload:
    return stage_upload(
        [data],
        filename=filename,
        staging_dir=tmp_path / "staging",
        document_id=kwargs.pop("document_id", "doc123"),
        **kwargs,
    )


class TestAcceptsValidPdf:
    def test_valid_pdf_is_staged_with_correct_metadata(self, tmp_path: Path) -> None:
        staged = _stage(tmp_path, MINIMAL_PDF)
        assert staged.path.is_file()
        assert staged.byte_size == len(MINIMAL_PDF)
        assert staged.media_type == "application/pdf"
        assert staged.display_name == "report.pdf"

    def test_sha256_matches_the_bytes_written(self, tmp_path: Path) -> None:
        import hashlib

        staged = _stage(tmp_path, MINIMAL_PDF)
        assert staged.sha256 == hashlib.sha256(MINIMAL_PDF).hexdigest()
        assert staged.sha256 == hashlib.sha256(staged.path.read_bytes()).hexdigest()

    def test_identical_content_hashes_identically_for_duplicate_detection(self, tmp_path: Path) -> None:
        first = _stage(tmp_path, MINIMAL_PDF, document_id="a")
        second = _stage(tmp_path, MINIMAL_PDF, document_id="b", filename="other-name.pdf")
        assert first.sha256 == second.sha256

    def test_streaming_across_many_chunks_is_reassembled_correctly(self, tmp_path: Path) -> None:
        chunks = [MINIMAL_PDF[i : i + 3] for i in range(0, len(MINIMAL_PDF), 3)]
        staged = stage_upload(chunks, filename="a.pdf", staging_dir=tmp_path / "s", document_id="d1")
        assert staged.path.read_bytes() == MINIMAL_PDF

    def test_missing_content_type_is_tolerated(self, tmp_path: Path) -> None:
        assert _stage(tmp_path, MINIMAL_PDF, declared_media_type=None).byte_size > 0

    def test_octet_stream_is_tolerated(self, tmp_path: Path) -> None:
        # Browsers and curl often send this for a file input; the signature
        # check is what actually decides.
        assert _stage(tmp_path, MINIMAL_PDF, declared_media_type="application/octet-stream")

    def test_content_type_with_parameters_is_normalised(self, tmp_path: Path) -> None:
        assert _stage(tmp_path, MINIMAL_PDF, declared_media_type="application/pdf; charset=binary")


class TestRejectsUnsafeOrInvalidInput:
    def test_zero_byte_file_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(UploadRejected) as excinfo:
            _stage(tmp_path, b"")
        assert excinfo.value.code == UploadRejectionCode.EMPTY_FILE

    def test_non_pdf_content_is_rejected_even_with_a_pdf_extension(self, tmp_path: Path) -> None:
        """A lying extension must not get past the signature check."""
        with pytest.raises(UploadRejected) as excinfo:
            _stage(tmp_path, b"MZ\x90\x00 this is actually an executable")
        assert excinfo.value.code == UploadRejectionCode.NOT_A_PDF

    def test_non_pdf_content_with_a_lying_content_type_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(UploadRejected) as excinfo:
            _stage(tmp_path, b"<html>not a pdf</html>", declared_media_type="application/pdf")
        assert excinfo.value.code == UploadRejectionCode.NOT_A_PDF

    @pytest.mark.parametrize("name", ["notes.txt", "archive.zip", "script.exe", "image.png", "no-extension"])
    def test_unsupported_extensions_are_rejected(self, tmp_path: Path, name: str) -> None:
        with pytest.raises(UploadRejected) as excinfo:
            _stage(tmp_path, MINIMAL_PDF, filename=name)
        assert excinfo.value.code == UploadRejectionCode.UNSUPPORTED_EXTENSION

    def test_unsupported_declared_media_type_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(UploadRejected) as excinfo:
            _stage(tmp_path, MINIMAL_PDF, declared_media_type="text/html")
        assert excinfo.value.code == UploadRejectionCode.UNSUPPORTED_MEDIA_TYPE

    @pytest.mark.parametrize("name", ["", "   ", None])
    def test_missing_filename_is_rejected(self, tmp_path: Path, name: str | None) -> None:
        with pytest.raises(UploadRejected) as excinfo:
            _stage(tmp_path, MINIMAL_PDF, filename=name)
        assert excinfo.value.code == UploadRejectionCode.MISSING_FILENAME

    def test_oversized_upload_is_rejected_while_streaming(self, tmp_path: Path) -> None:
        with pytest.raises(UploadRejected) as excinfo:
            stage_upload(
                [MINIMAL_PDF, b"x" * 5000],
                filename="big.pdf",
                staging_dir=tmp_path / "s",
                document_id="d1",
                limits=UploadLimits(max_bytes=1000),
            )
        assert excinfo.value.code == UploadRejectionCode.TOO_LARGE

    def test_rejection_messages_never_leak_filesystem_paths(self, tmp_path: Path) -> None:
        with pytest.raises(UploadRejected) as excinfo:
            _stage(tmp_path, b"not a pdf at all")
        message = excinfo.value.message
        assert str(tmp_path) not in message
        assert "\\" not in message and "/" not in message


class TestPathSafety:
    """The client filename must never influence where bytes land."""

    @pytest.mark.parametrize(
        "hostile",
        [
            "../../../../etc/passwd.pdf",
            "..\\..\\..\\windows\\system32\\config.pdf",
            "/absolute/path/report.pdf",
            "C:\\Windows\\System32\\evil.pdf",
            "....//....//escape.pdf",
        ],
    )
    def test_traversal_attempts_stay_inside_the_staging_directory(self, tmp_path: Path, hostile: str) -> None:
        staging = tmp_path / "staging"
        staged = stage_upload([MINIMAL_PDF], filename=hostile, staging_dir=staging, document_id="doc123")
        resolved = staged.path.resolve()
        assert resolved.parent == staging.resolve()
        assert staged.path.name == "doc123.pdf"

    def test_stored_filename_is_sanitised_for_display_use(self, tmp_path: Path) -> None:
        staged = stage_upload(
            [MINIMAL_PDF],
            filename="../../weird name!@#.pdf",
            staging_dir=tmp_path / "s",
            document_id="d1",
        )
        assert "/" not in staged.stored_filename
        assert "\\" not in staged.stored_filename
        assert ".." not in staged.stored_filename

    def test_windows_reserved_device_name_is_defused(self, tmp_path: Path) -> None:
        staged = stage_upload([MINIMAL_PDF], filename="CON.pdf", staging_dir=tmp_path / "s", document_id="d1")
        assert staged.stored_filename.upper() != "CON.PDF"

    def test_original_name_is_preserved_verbatim_for_display(self, tmp_path: Path) -> None:
        """The UI must be able to show what the user actually uploaded."""
        staged = stage_upload(
            [MINIMAL_PDF], filename="Q3 Report (final).pdf", staging_dir=tmp_path / "s", document_id="d1"
        )
        assert staged.display_name == "Q3 Report (final).pdf"

    def test_path_is_named_by_document_id_not_user_input(self, tmp_path: Path) -> None:
        staged = stage_upload(
            [MINIMAL_PDF], filename="attacker-chosen.pdf", staging_dir=tmp_path / "s", document_id="server-id"
        )
        assert staged.path.name == "server-id.pdf"


class TestFailureCleanup:
    def test_rejected_upload_leaves_no_partial_file(self, tmp_path: Path) -> None:
        staging = tmp_path / "staging"
        with pytest.raises(UploadRejected):
            stage_upload([b"not a pdf"], filename="x.pdf", staging_dir=staging, document_id="d1")
        assert list(staging.iterdir()) == []

    def test_oversized_upload_leaves_no_partial_file(self, tmp_path: Path) -> None:
        staging = tmp_path / "staging"
        with pytest.raises(UploadRejected):
            stage_upload(
                [MINIMAL_PDF, b"x" * 10_000],
                filename="x.pdf",
                staging_dir=staging,
                document_id="d1",
                limits=UploadLimits(max_bytes=500),
            )
        assert list(staging.iterdir()) == []

    def test_a_producer_error_mid_stream_leaves_no_partial_file(self, tmp_path: Path) -> None:
        staging = tmp_path / "staging"

        def exploding():
            yield MINIMAL_PDF
            raise OSError("connection reset")

        with pytest.raises(OSError, match="connection reset"):
            stage_upload(exploding(), filename="x.pdf", staging_dir=staging, document_id="d1")
        assert list(staging.iterdir()) == []

    def test_discard_removes_the_staged_file_and_is_idempotent(self, tmp_path: Path) -> None:
        staged = _stage(tmp_path, MINIMAL_PDF)
        discard_staged_upload(staged)
        assert not staged.path.exists()
        discard_staged_upload(staged)  # must not raise


class TestPromotion:
    def test_promotion_moves_the_file_out_of_staging(self, tmp_path: Path) -> None:
        staged = _stage(tmp_path, MINIMAL_PDF)
        destination = promote_staged_upload(staged, tmp_path / "durable")

        assert destination.is_file()
        assert not staged.path.exists()
        assert destination.read_bytes() == MINIMAL_PDF


class TestLimits:
    @pytest.mark.parametrize("kwargs", [{"max_bytes": 0}, {"max_bytes": -1}, {"max_pages": 0}])
    def test_invalid_limits_are_rejected_at_construction(self, kwargs: dict) -> None:
        with pytest.raises(ValueError):
            UploadLimits(**kwargs)

    def test_defaults_are_conservative(self) -> None:
        limits = UploadLimits()
        assert limits.max_bytes == 100 * 1024 * 1024
        assert limits.max_pages == 2000


class TestFileChunkHelper:
    def test_round_trips_a_local_file(self, tmp_path: Path) -> None:
        source = tmp_path / "in.pdf"
        source.write_bytes(MINIMAL_PDF)
        staged = stage_upload(
            iter_file_chunks(source, chunk_size=4),
            filename="in.pdf",
            staging_dir=tmp_path / "s",
            document_id="d1",
        )
        assert staged.path.read_bytes() == MINIMAL_PDF
