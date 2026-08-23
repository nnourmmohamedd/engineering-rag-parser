"""Unit tests for configuration, safe paths, hashing and run manifests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from engineering_rag_parser.artifacts import (
    JsonlLogger,
    RunDirectory,
    UnsafePathError,
    environment_snapshot,
    safe_filename,
    sha256_file,
)
from engineering_rag_parser.config import ParserConfig, Profile, load_config


class TestParserConfig:
    def test_defaults_are_cpu_and_no_ocr(self) -> None:
        """Docling ships do_ocr=True; this project must override it for digital PDFs."""
        cfg = ParserConfig()
        assert cfg.docling.do_ocr is False
        assert cfg.docling.accelerator_device.value == "cpu"

    def test_config_hash_is_stable(self) -> None:
        assert ParserConfig().config_hash() == ParserConfig().config_hash()

    def test_config_hash_changes_with_content(self) -> None:
        a = ParserConfig()
        b = a.with_overrides(strict=True)
        assert a.config_hash() != b.config_hash()

    def test_config_is_frozen(self) -> None:
        cfg = ParserConfig()
        with pytest.raises(ValidationError):
            cfg.strict = True  # type: ignore[misc]

    def test_unknown_key_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ParserConfig.model_validate({"not_a_real_key": 1})

    def test_remote_services_cannot_be_enabled(self) -> None:
        """Local-only is a policy enforced by a validator, not merely a default."""
        with pytest.raises(ValidationError, match="never leave the machine"):
            ParserConfig.model_validate({"docling": {"enable_remote_services": True}})

    def test_threshold_ordering_is_validated(self) -> None:
        with pytest.raises(ValidationError, match="page_char_coverage_fail"):
            ParserConfig.model_validate(
                {"thresholds": {"page_char_coverage_warn": 0.5, "page_char_coverage_fail": 0.9}}
            )

    def test_effective_dict_is_json_serialisable(self) -> None:
        json.dumps(ParserConfig().effective_dict())

    def test_ocr_languages_accepts_list(self) -> None:
        cfg = ParserConfig.model_validate({"docling": {"ocr_languages": ["en", "de"]}})
        assert cfg.docling.ocr_languages == ("en", "de")


class TestLoadConfig:
    def test_none_path_yields_defaults(self) -> None:
        assert load_config(None).config_hash() == ParserConfig().config_hash()

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "nope.yaml")

    def test_non_mapping_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text("- just\n- a\n- list\n", encoding="utf-8")
        with pytest.raises(ValueError, match="YAML mapping"):
            load_config(path)

    def test_overrides_apply(self, tmp_path: Path) -> None:
        path = tmp_path / "c.yaml"
        path.write_text(yaml.safe_dump({"profile": "default"}), encoding="utf-8")
        assert load_config(path, profile=Profile.HIGH_FIDELITY).profile is Profile.HIGH_FIDELITY

    def test_none_overrides_are_ignored(self, tmp_path: Path) -> None:
        path = tmp_path / "c.yaml"
        path.write_text(yaml.safe_dump({"strict": True}), encoding="utf-8")
        assert load_config(path, strict=None).strict is True

    @pytest.mark.parametrize("name", ["default", "high_fidelity", "scanned", "auto"])
    def test_shipped_profiles_load(self, name: str) -> None:
        path = Path("configs") / f"{name}.yaml"
        if not path.is_file():
            pytest.skip(f"{path} not present")
        assert load_config(path).profile.value == name


class TestSafeFilename:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Table 1: Deliverables", "Table-1-Deliverables"),
            ("../../etc/passwd", "etc-passwd"),
            ("a/b\\c", "a-b-c"),
            ("", "item"),
            ("...", "item"),
        ],
    )
    def test_sanitises(self, raw: str, expected: str) -> None:
        assert safe_filename(raw) == expected

    def test_windows_reserved_names_are_escaped(self) -> None:
        assert safe_filename("CON") == "_CON"
        assert safe_filename("nul.txt") == "_nul.txt"

    def test_length_is_bounded(self) -> None:
        assert len(safe_filename("x" * 500)) <= 120


class TestRunDirectory:
    def test_creates_expected_subdirs(self, tmp_path: Path) -> None:
        run = RunDirectory.create(tmp_path / "artifacts", "doc", "a" * 64)
        for sub in RunDirectory.SUBDIRS:
            assert (run.root / sub).is_dir()

    def test_run_id_carries_timestamp_and_hash(self, tmp_path: Path) -> None:
        now = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        run = RunDirectory.create(tmp_path / "a", "doc", "abcdef12" + "0" * 56, now=now)
        assert run.root.name == "20260102T030405Z-abcdef12"

    def test_runs_are_immutable(self, tmp_path: Path) -> None:
        """A second run at the same instant must not silently overwrite the first."""
        now = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        RunDirectory.create(tmp_path / "a", "doc", "a" * 64, now=now)
        with pytest.raises(FileExistsError):
            RunDirectory.create(tmp_path / "a", "doc", "a" * 64, now=now)

    def test_quarantine_routes_elsewhere(self, tmp_path: Path) -> None:
        run = RunDirectory.create(tmp_path / "artifacts", "doc", "a" * 64, quarantine=True)
        assert "quarantine" in run.root.parts

    @pytest.mark.parametrize("escape", ["../evil.txt", "../../evil.txt", "sub/../../evil.txt"])
    def test_path_traversal_is_refused(self, tmp_path: Path, escape: str) -> None:
        run = RunDirectory.create(tmp_path / "a", "doc", "a" * 64)
        with pytest.raises(UnsafePathError):
            run.path_for(escape)

    def test_write_text_uses_lf_even_on_windows(self, tmp_path: Path) -> None:
        run = RunDirectory.create(tmp_path / "a", "doc", "a" * 64)
        path = run.write_text("markdown/x.md", "line one\r\nline two\rline three\n")
        raw = path.read_bytes()
        assert b"\r" not in raw
        assert raw == b"line one\nline two\nline three\n"

    def test_write_json_is_deterministic(self, tmp_path: Path) -> None:
        run = RunDirectory.create(tmp_path / "a", "doc", "a" * 64)
        p1 = run.write_json("validation/x.json", {"b": 2, "a": 1})
        first = p1.read_bytes()
        p2 = run.write_json("validation/x.json", {"a": 1, "b": 2})
        assert p2.read_bytes() == first

    def test_relative_uses_posix_separators(self, tmp_path: Path) -> None:
        run = RunDirectory.create(tmp_path / "a", "doc", "a" * 64)
        path = run.write_text("assets/pictures/x.md", "hi")
        assert run.relative(path) == "assets/pictures/x.md"

    def test_hash_artifacts_excludes_manifest(self, tmp_path: Path) -> None:
        run = RunDirectory.create(tmp_path / "a", "doc", "a" * 64)
        run.write_text("markdown/document.md", "content")
        run.write_json("run_manifest.json", {"x": 1})
        hashes = run.hash_artifacts()
        assert "markdown/document.md" in hashes
        assert "run_manifest.json" not in hashes


class TestHashingAndEnvironment:
    def test_sha256_matches_hashlib(self, tmp_path: Path) -> None:
        import hashlib

        path = tmp_path / "f.bin"
        payload = b"engineering" * 1000
        path.write_bytes(payload)
        assert sha256_file(path) == hashlib.sha256(payload).hexdigest()

    def test_environment_snapshot_excludes_identifying_data(self) -> None:
        """The manifest is shareable, so it must not carry hostname or user."""
        snap = environment_snapshot()
        blob = json.dumps(snap).lower()
        assert "python_version" in snap
        for leak in ("hostname", "username", "c:\\users", "/home/"):
            assert leak not in blob


class TestJsonlLogger:
    def test_appends_one_object_per_line(self, tmp_path: Path) -> None:
        log = JsonlLogger(tmp_path / "logs" / "run.jsonl")
        log.log("started", pages=27)
        log.log("finished", status="PASS")
        lines = (tmp_path / "logs" / "run.jsonl").read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["event"] == "started"
        assert json.loads(lines[1])["status"] == "PASS"

    def test_serialises_paths_and_datetimes(self, tmp_path: Path) -> None:
        log = JsonlLogger(tmp_path / "run.jsonl")
        log.log("e", path=Path("a/b"), when=datetime(2026, 1, 1, tzinfo=timezone.utc))
        record = json.loads((tmp_path / "run.jsonl").read_text(encoding="utf-8").strip())
        assert record["path"] == "a/b"
        assert record["when"].startswith("2026-01-01")
