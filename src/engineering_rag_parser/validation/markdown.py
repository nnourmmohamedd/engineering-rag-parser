"""Markdown and JSON quality assurance.

These checks operate on the *files that were actually written*, not on in-memory
objects. A validator that inspects the object graph can pass while the artifact
on disk is broken — wrong encoding, a dangling image link, a leftover
placeholder — and the artifact is what the next stage consumes.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from pathlib import Path
from typing import Any

from engineering_rag_parser.domain import CheckResult, DocumentInventory, Severity

__all__ = ["json_checks", "markdown_checks"]

logger = logging.getLogger(__name__)

_IMAGE_LINK_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<target>[^)]+)\)")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)
_TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)
#: Absolute Windows (C:\...) or POSIX (/home/...) paths must never appear.
_ABS_PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/])|(?:\]\(/[A-Za-z])")
_BASE64_RE = re.compile(r"data:image/[a-z]+;base64,", re.IGNORECASE)
#: Control characters that should never survive into a text artifact.
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
#: Common mojibake signatures from a latin-1/UTF-8 round trip.
_MOJIBAKE_RE = re.compile(r"(Ã[\x80-\xbf])|(â€[\x9c\x9d\x99\x93\x94])|(Â[\xa0-\xbf])|\ufffd")
_PLACEHOLDER_RE = re.compile(r"(?:TODO|FIXME|XXX|<unresolved>|\{\{[^}]*\}\}|@@[A-Z_]+@@|<!--ERP:)")


def markdown_checks(markdown_path: Path, run_root: Path, inventory: DocumentInventory) -> list[CheckResult]:
    """Validate the canonical Markdown artifact on disk."""
    checks: list[CheckResult] = []
    raw_bytes = markdown_path.read_bytes()

    # --- Encoding and line endings -------------------------------------------
    decode_error: str | None = None
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        decode_error = str(exc)
        text = raw_bytes.decode("utf-8", errors="replace")
    has_crlf = b"\r\n" in raw_bytes
    checks.append(
        CheckResult(
            check_id="markdown_encoding",
            title="Markdown is valid UTF-8 with LF line endings",
            passed=decode_error is None and not has_crlf,
            severity=Severity.CRITICAL,
            gate=True,
            summary="Valid UTF-8, LF endings."
            if decode_error is None and not has_crlf
            else f"utf8_error={decode_error}, crlf_present={has_crlf}",
            evidence={"bytes": len(raw_bytes), "crlf_present": has_crlf, "utf8_error": decode_error},
            threshold={"required": "UTF-8, no CRLF"},
            remediation="Write with newline='' and explicit LF so artifacts are byte-stable across OSes.",
        )
    )

    # --- Non-empty ------------------------------------------------------------
    checks.append(
        CheckResult(
            check_id="markdown_non_empty",
            title="Markdown is non-empty and substantial",
            passed=len(text.strip()) > 500,
            severity=Severity.CRITICAL,
            gate=True,
            summary=f"{len(text)} characters, {text.count(chr(10)) + 1} lines.",
            evidence={"characters": len(text), "lines": text.count("\n") + 1},
            threshold={"min_characters": 500},
            remediation="An almost-empty export means the serializer produced nothing usable.",
        )
    )

    # --- Image links resolve --------------------------------------------------
    links = list(_IMAGE_LINK_RE.finditer(text))
    broken: list[str] = []
    absolute: list[str] = []
    for match in links:
        target = match.group("target").strip()
        if target.startswith(("http://", "https://", "data:")):
            absolute.append(target[:80])
            continue
        if Path(target).is_absolute() or re.match(r"^[A-Za-z]:", target):
            absolute.append(target[:80])
            continue
        if not (run_root / target).is_file():
            broken.append(target)
    checks.append(
        CheckResult(
            check_id="markdown_image_links",
            title="Every referenced image exists and uses a portable relative path",
            passed=not broken and not absolute,
            severity=Severity.CRITICAL,
            gate=True,
            summary=f"{len(links)} image link(s); {len(broken)} broken, {len(absolute)} non-portable.",
            evidence={"total_links": len(links), "broken": broken[:10], "non_portable": absolute[:10]},
            threshold={"required": "all links relative and resolvable inside the run directory"},
            remediation="Re-run the export; assets must be written before the Markdown references them.",
        )
    )

    # --- No embedded base64 ---------------------------------------------------
    b64 = _BASE64_RE.findall(text)
    checks.append(
        CheckResult(
            check_id="markdown_no_base64",
            title="Markdown contains no base64-embedded images",
            passed=not b64,
            severity=Severity.CRITICAL,
            gate=True,
            summary="No embedded base64 payloads." if not b64 else f"{len(b64)} base64 payload(s) found.",
            evidence={"occurrences": len(b64)},
            threshold={"required": "zero"},
            remediation="Export with ImageRefMode.REFERENCED, not EMBEDDED.",
        )
    )

    # --- No absolute local paths ---------------------------------------------
    abs_hits = _ABS_PATH_RE.findall(text)
    checks.append(
        CheckResult(
            check_id="markdown_no_absolute_paths",
            title="Markdown leaks no machine-specific absolute paths",
            passed=not abs_hits,
            severity=Severity.WARNING,
            gate=False,
            summary="No absolute paths."
            if not abs_hits
            else f"{len(abs_hits)} absolute-path-like string(s).",
            evidence={"occurrences": len(abs_hits)},
            threshold={"required": "zero"},
            remediation="Absolute paths make the artifact non-portable and can leak directory structure.",
        )
    )

    # --- Control characters / mojibake ---------------------------------------
    controls = _CONTROL_RE.findall(text)
    mojibake = _MOJIBAKE_RE.findall(text)
    checks.append(
        CheckResult(
            check_id="markdown_character_hygiene",
            title="No control characters or mojibake",
            passed=not controls and not mojibake,
            severity=Severity.WARNING,
            gate=False,
            summary=f"{len(controls)} control character(s), {len(mojibake)} mojibake signature(s).",
            evidence={
                "control_chars": len(controls),
                "mojibake": len(mojibake),
                "sample": [unicodedata.name(c, repr(c)) for c in set(controls)][:5],
            },
            threshold={"required": "zero"},
            remediation="Mojibake indicates a mismatched encoding at extraction time.",
        )
    )

    # --- Unresolved placeholders ---------------------------------------------
    placeholders = _PLACEHOLDER_RE.findall(text)
    checks.append(
        CheckResult(
            check_id="markdown_no_placeholders",
            title="No unresolved placeholders or internal markers",
            passed=not placeholders,
            severity=Severity.CRITICAL,
            gate=True,
            summary="No leftover markers."
            if not placeholders
            else f"{len(placeholders)} placeholder(s) remain.",
            evidence={"samples": list(dict.fromkeys(placeholders))[:10]},
            threshold={"required": "zero"},
            remediation="An internal marker in the canonical output means a substitution step did not run.",
        )
    )

    # --- Heading hierarchy ----------------------------------------------------
    headings = [(len(m.group(1)), m.group(2)) for m in _HEADING_RE.finditer(text)]
    jumps = [
        {"from": headings[i - 1][0], "to": lvl, "heading": txt[:60]}
        for i, (lvl, txt) in enumerate(headings)
        if i > 0 and lvl > headings[i - 1][0] + 1
    ]
    h1_count = sum(1 for lvl, _ in headings if lvl == 1)
    checks.append(
        CheckResult(
            check_id="markdown_heading_structure",
            title="Markdown has one document title and a consistent heading hierarchy",
            passed=h1_count == 1 and not jumps,
            severity=Severity.WARNING,
            gate=False,
            summary=f"{h1_count} H1, {len(headings)} headings total, {len(jumps)} level jump(s).",
            evidence={"h1_count": h1_count, "total_headings": len(headings), "jumps": jumps[:8]},
            threshold={"required": "exactly one H1; no skipped levels"},
            remediation="Multiple H1s split the document for section-aware chunking.",
        )
    )

    # --- Table row consistency ------------------------------------------------
    inconsistent = _table_row_consistency(text)
    checks.append(
        CheckResult(
            check_id="markdown_table_consistency",
            title="Markdown tables have consistent column counts",
            passed=not inconsistent,
            severity=Severity.WARNING,
            gate=False,
            summary="All Markdown tables are rectangular."
            if not inconsistent
            else f"{len(inconsistent)} table(s) have ragged rows.",
            evidence={"tables": inconsistent[:5]},
            threshold={"rule": "every row in a pipe table has the same column count"},
            remediation="Ragged rows indicate a merged-cell table flattened into Markdown; use HTML instead.",
        )
    )

    # --- Semantic retention vs the document inventory -------------------------
    md_headings = len(headings)
    expected_headings = inventory.titles + inventory.section_headers
    retention = md_headings / expected_headings if expected_headings else 1.0
    checks.append(
        CheckResult(
            check_id="markdown_semantic_retention",
            title="Markdown retains the document's headings",
            passed=retention >= 0.9,
            severity=Severity.WARNING,
            gate=False,
            summary=f"{md_headings} Markdown headings vs {expected_headings} in the DoclingDocument "
            f"({retention:.0%} retained).",
            evidence={
                "markdown_headings": md_headings,
                "document_headings": expected_headings,
                "retention": round(retention, 4),
            },
            threshold={"min_retention": 0.9},
            remediation="Loss here means the Markdown serializer dropped structure the JSON still has; "
            "downstream chunking should consume the JSON.",
        )
    )

    return checks


def _table_row_consistency(text: str) -> list[dict[str, Any]]:
    """Find pipe tables whose rows disagree on column count."""
    problems: list[dict[str, Any]] = []
    block: list[str] = []
    start_line = 0
    for lineno, line in enumerate(text.split("\n"), start=1):
        if _TABLE_ROW_RE.match(line):
            if not block:
                start_line = lineno
            block.append(line)
            continue
        if block:
            problems.extend(_check_block(block, start_line))
            block = []
    if block:
        problems.extend(_check_block(block, start_line))
    return problems


def _check_block(block: list[str], start_line: int) -> list[dict[str, Any]]:
    """Validate one contiguous pipe-table block."""
    counts = [row.strip().strip("|").count("|") + 1 for row in block]
    if len(set(counts)) > 1:
        return [{"start_line": start_line, "rows": len(block), "column_counts": sorted(set(counts))}]
    return []


_URI_VALUE_RE = re.compile(r'"uri"\s*:\s*"((?:[^"\\]|\\.)*)"')


def _non_portable_uris(raw_text: str) -> list[str]:
    """URI values that contain a literal backslash and are not a remote URL.

    A backslash is a valid filename character on POSIX, so a Windows-style
    relative path (``assets\\image_….png``) silently fails to resolve there
    (audit finding D-3). Remote ``http(s)``/``data:`` URIs never contain one.
    """
    hits: list[str] = []
    for match in _URI_VALUE_RE.finditer(raw_text):
        value = match.group(1)
        if "\\\\" in value and not value.startswith(("http://", "https://", "data:")):
            hits.append(value)
    return hits


def json_checks(
    json_path: Path, reload_ok: bool, reload_error: str | None, roundtrip: dict[str, Any]
) -> list[CheckResult]:
    """Validate the serialised DoclingDocument artifact."""
    checks: list[CheckResult] = []

    raw_text = json_path.read_text(encoding="utf-8") if json_path.exists() else ""
    parse_error: str | None = None
    payload: Any = None
    try:
        payload = json.loads(raw_text)
    except Exception as exc:  # noqa: BLE001
        parse_error = str(exc)

    checks.append(
        CheckResult(
            check_id="json_parseable",
            title="document.json is valid, parseable JSON",
            passed=parse_error is None,
            severity=Severity.CRITICAL,
            gate=True,
            summary="Parsed successfully." if parse_error is None else f"Parse failed: {parse_error}",
            evidence={
                "bytes": json_path.stat().st_size if json_path.exists() else 0,
                "top_level_keys": sorted(payload)[:15] if isinstance(payload, dict) else None,
            },
            threshold={"required": "valid JSON"},
            remediation="Re-run the export; a truncated file usually means the process was interrupted.",
        )
    )

    checks.append(
        CheckResult(
            check_id="json_reloads_into_model",
            title="document.json reloads into the current DoclingDocument model",
            passed=reload_ok,
            severity=Severity.CRITICAL,
            gate=True,
            summary="Reloaded and validated against DoclingDocument."
            if reload_ok
            else f"Reload failed: {reload_error}",
            evidence={"error": reload_error},
            threshold={"required": "DoclingDocument.load_from_json succeeds"},
            remediation="A file that will not reload is not a usable handoff to the chunking stage.",
        )
    )

    non_portable = _non_portable_uris(raw_text) if parse_error is None else []
    checks.append(
        CheckResult(
            check_id="json_portable_paths",
            title="document.json image URIs use portable forward-slash separators",
            passed=not non_portable,
            severity=Severity.CRITICAL,
            gate=True,
            summary="All URI values are portable."
            if not non_portable
            else f"{len(non_portable)} URI value(s) contain a Windows backslash separator.",
            evidence={"count": len(non_portable), "sample": non_portable[:10]},
            threshold={"required": "no backslash in any relative URI value"},
            remediation="Backslashes are literal filename characters on POSIX; normalise to '/' after "
            "Docling's own serialiser writes the file.",
        )
    )

    checks.append(
        CheckResult(
            check_id="json_roundtrip_stable",
            title="Serialisation round-trip preserves the document inventory",
            passed=bool(roundtrip.get("identical", False)),
            severity=Severity.WARNING,
            gate=False,
            summary=roundtrip.get("summary", "Round-trip not performed."),
            evidence=roundtrip,
            threshold={"rule": "counts of texts/tables/pictures/pages must match after reload"},
            remediation="Material differences indicate the serializer is lossy for this document.",
        )
    )

    return checks
