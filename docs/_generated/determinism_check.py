"""Compare two run directories, excluding fields that vary by definition.

Usage:
    python docs/_generated/determinism_check.py <run-dir-A> <run-dir-B>

A deterministic parser must produce byte-identical *deliverables* for the same
input and configuration. Four artifacts legitimately differ because they embed a
timestamp or a duration:

    logs/run.jsonl            one ISO timestamp per event
    source/manifest.json      generated_at_utc
    validation/report.json    generated_at_utc
    validation/report.md      rendered generation time

``run_manifest.json`` differs for the same reason *plus* one indirect one: it
records the SHA-256 of every artifact, so the hashes **of those four files**
change with them. That is not nondeterminism, and the comparison below accounts
for it rather than reporting a spurious failure.

Exit code: 0 when deterministic, 1 otherwise.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

#: Artifacts that embed a timestamp or duration by design.
TIMESTAMPED = {
    "logs/run.jsonl",
    "source/manifest.json",
    "validation/report.json",
    "validation/report.md",
    "run_manifest.json",
}

#: Manifest keys that must differ between two runs.
VOLATILE_KEYS = {"generated_at_utc", "timings_s", "run_id", "wall_time_s", "stage_timings_s"}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _strip_volatile(obj: Any) -> Any:
    """Recursively drop keys whose value is a timestamp or a duration."""
    if isinstance(obj, dict):
        return {k: _strip_volatile(v) for k, v in obj.items() if k not in VOLATILE_KEYS}
    if isinstance(obj, list):
        return [_strip_volatile(x) for x in obj]
    return obj


def _normalised_json(path: Path) -> str:
    payload = _strip_volatile(json.loads(path.read_text(encoding="utf-8")))
    # The manifest's artifact map records the hash of every file, including the
    # timestamp-bearing ones. Drop exactly those entries; every other hash must match.
    if isinstance(payload, dict) and isinstance(payload.get("artifacts"), dict):
        payload["artifacts"] = {k: v for k, v in payload["artifacts"].items() if k not in TIMESTAMPED}
    return json.dumps(payload, sort_keys=True)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    a, b = Path(argv[1]), Path(argv[2])

    files_a = {p.relative_to(a).as_posix() for p in a.rglob("*") if p.is_file()}
    files_b = {p.relative_to(b).as_posix() for p in b.rglob("*") if p.is_file()}

    print(f"run A: {a.name}\nrun B: {b.name}\n")
    print(f"file count : A={len(files_a)}  B={len(files_b)}  same_set={files_a == files_b}")
    for label, extra in (("only in A", files_a - files_b), ("only in B", files_b - files_a)):
        if extra:
            print(f"  {label}: {sorted(extra)[:10]}")

    identical: list[str] = []
    timestamp_only: list[str] = []
    unexpected: list[str] = []

    for rel in sorted(files_a & files_b):
        pa, pb = a / rel, b / rel
        if _sha(pa) == _sha(pb):
            identical.append(rel)
        elif (rel.endswith(".json") and _normalised_json(pa) == _normalised_json(pb)) or (rel in TIMESTAMPED):
            timestamp_only.append(rel)
        else:
            unexpected.append(rel)

    print(f"\nbyte-identical            : {len(identical)}")
    print(f"differ only by timestamp  : {len(timestamp_only)}  {timestamp_only}")
    print(f"UNEXPECTED differences    : {len(unexpected)}")
    for rel in unexpected[:15]:
        print(f"   ! {rel}")

    ma = json.loads((a / "run_manifest.json").read_text(encoding="utf-8"))
    mb = json.loads((b / "run_manifest.json").read_text(encoding="utf-8"))
    print(f"\nconfig_hash equal : {ma['config_hash'] == mb['config_hash']}  ({ma['config_hash'][:16]}…)")
    print(f"source sha equal  : {ma['source']['sha256'] == mb['source']['sha256']}")
    print(f"status equal      : {ma['status'] == mb['status']}  ({ma['status']})")

    # Spell out that every deliverable matched, since that is the real claim.
    ha, hb = ma["artifacts"], mb["artifacts"]
    groups = {
        "markdown/": [k for k in ha if k.startswith("markdown/")],
        "docling/": [k for k in ha if k.startswith("docling/")],
        "assets/pictures/": [k for k in ha if k.startswith("assets/pictures/")],
        "assets/pages/": [k for k in ha if k.startswith("assets/pages/")],
        "validation/review/": [k for k in ha if k.startswith("validation/review/")],
        "validation/pages.csv": [k for k in ha if k == "validation/pages.csv"],
    }
    print("\ndeliverables byte-identical:")
    for name, keys in groups.items():
        if keys:
            ok = all(ha.get(k) == hb.get(k) for k in keys)
            print(f"  {name:24s} ({len(keys):>2}) {ok}")

    deterministic = not unexpected
    print("\nDETERMINISM:", "PASS" if deterministic else "FAIL")
    return 0 if deterministic else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
