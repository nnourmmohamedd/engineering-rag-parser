# Restructure Completion Report

**Report date:** 2026-08-24
**Scope:** restructure the parser into the mentor-required service-oriented
architecture (`utils / services / prompts / pipelines / clients / databases /
api`) without changing, losing or regressing any verified parser behaviour.
No chunking, embeddings, vector store, retrieval, reranking, API server or
chatbot was implemented — that remains explicitly out of scope.

---

## 1. Executive verdict

**RESTRUCTURE COMPLETE. PARSER FUNCTIONALITY UNCHANGED AND RE-VERIFIED.**

The parser now lives under `src/engineering_rag/services/parser/`, orchestrated
by `pipelines/parsing_pipeline.py` and exposed through `api/cli.py`
(`engrag-parse`), with centralized `logging`, `data/input`/`data/output/parser`
as the default I/O roots, and documented empty scaffolds for the next
milestones (`services/chunker/`, `clients/`, `databases/`, `prompts/`). The old
`src/engineering_rag_parser/` package was removed entirely — no duplicated
implementation exists in both namespaces.

Both acceptance benchmarks were re-run through the new architecture and
produced **the same status and the same gate results** as before the
restructure: the OCR benchmark **PASS** with 100% critical-token recall, and
the original 27-page engineering PDF **PASS_WITH_WARNINGS** with the same 4
legitimate, document-level warnings. Fast tests (246), slow tests (42),
coverage (84%), ruff, mypy, the wheel build, and a second independent
clean-installation all pass. Pull request #1 (`refactor/service-architecture`
→ `master`) was opened, one CI-only defect was found and fixed (§19.1), and
**both GitHub Actions jobs (Python 3.11 and Python 3.13) passed**. The PR was
merged into `master` (merge commit `8376a93`), the remote and local feature
branches were deleted, and local `master` is fast-forwarded to match
`origin/master` exactly — see §19–22.

## 2. Final directory tree

```text
src/engineering_rag/
├── __init__.py                          package __version__
├── api/
│   ├── __init__.py
│   ├── README.md
│   └── cli.py                           engrag-parse Typer app (console script)
├── clients/                              empty boundary + README (future)
│   ├── __init__.py
│   └── README.md
├── databases/                             empty boundary + README (future)
│   ├── __init__.py
│   └── README.md
├── pipelines/
│   ├── __init__.py
│   └── parsing_pipeline.py               thin orchestration -> ParserService
├── prompts/                                empty boundary + README (future)
│   ├── __init__.py
│   └── README.md
├── services/
│   ├── __init__.py
│   ├── chunker/                            scaffold only, documented contract
│   │   ├── __init__.py
│   │   └── README.md
│   └── parser/                             COMPLETE parser implementation
│       ├── __init__.py                     public interface (ParserService, ...)
│       ├── service.py                      ParserService / ParserRequest / ParserResult
│       ├── config.py                       ParserConfig, profiles, thresholds
│       ├── models.py                       domain models (was domain.py)
│       ├── normalization.py                text primitives
│       ├── preflight.py                    independent (non-Docling) source manifest
│       ├── profiles.py                     choose_profile / resolve_profile_config
│       ├── converter.py                    Docling converter + conversion + JSON I/O
│       ├── inventory.py                    structural counting of a converted document
│       ├── exporters.py                    asset extraction + Markdown export
│       ├── artifacts.py                    immutable run dirs, run manifest, JSONL log
│       └── validation/
│           ├── __init__.py
│           ├── source.py                   page coverage vs. independent baseline (was coverage.py)
│           ├── structure.py                headings, TOC, table/picture audits
│           ├── markdown.py                 Markdown + JSON QA on disk
│           ├── visual.py                   HTML/SVG review cards
│           └── report.py                   report assembly, CSV, Markdown report
└── utils/
    ├── __init__.py
    ├── paths.py                            safe_filename, UnsafePathError, default data roots
    ├── hashing.py                          sha256_file
    └── logging.py                          centralized stdlib logging configuration

tests/
├── conftest.py
├── unit/
│   ├── test_architecture.py                package hygiene + service-boundary tests
│   ├── api/                                CLI + OCR-failure-mode tests
│   ├── pipelines/                          (reserved; nothing pipeline-specific to unit-test yet)
│   ├── services/parser/                    config, artifacts, exporters, preflight, inventory,
│   │   └── validation/                     normalization, OCR-fixture tests, validation tests
│   └── utils/                              paths, hashing tests
└── integration/
    ├── pipelines/                          full end-to-end pipeline + acceptance-document tests
    └── services/parser/                    real OCR conversion integration tests

data/
├── input/                                  source PDFs (git-ignored; .gitkeep tracked)
│   └── ocr/                                OCR-benchmark fixtures (git-ignored)
└── output/                                 all generated outputs (git-ignored; .gitkeep tracked)
    ├── parser/<document>/<run-id>/         parser service runs
    └── ocr_validation/                     OCR ground-truth + validation-script outputs
```

## 3. Complete old-to-new module mapping

See [`docs/architecture/service_restructure_plan.md`](docs/architecture/service_restructure_plan.md)
§2 for the full table with responsibilities and notes. Summary:

| Old | New |
|---|---|
| `engineering_rag_parser/__init__.py` | `engineering_rag/__init__.py` + `engineering_rag/services/parser/__init__.py` (`PARSER_VERSION`) |
| `config.py` | `services/parser/config.py` (moved verbatim) |
| `domain.py` | `services/parser/models.py` (renamed, moved verbatim) |
| `normalization.py` | `services/parser/normalization.py` (moved verbatim) |
| `preflight.py` | `services/parser/preflight.py` (moved; `_sha256_file` now delegates to `utils.hashing.sha256_file`) |
| `pipeline_factory.py` | split: `services/parser/profiles.py` (profile decision) + `services/parser/converter.py` (Docling object construction) |
| `parser.py` | split: `services/parser/converter.py` (conversion + JSON I/O) + `services/parser/inventory.py` (structural counting) |
| `exporters.py` | `services/parser/exporters.py` (moved; `safe_filename`/`sha256_file` imports repointed to `utils`) |
| `artifacts.py` | `services/parser/artifacts.py` (`safe_filename`/`UnsafePathError`/`sha256_file` extracted to `utils.paths`/`utils.hashing`; `RunDirectory`/`RunManifest`/`JsonlLogger` unchanged) |
| `pipeline.py` | split: `pipelines/parsing_pipeline.py` (thin wrapper) + `services/parser/service.py::ParserService.run()` (the exact former sequence, now a service method) |
| `cli.py` | `api/cli.py` (imports repointed; adds `--log-file`; default `--artifacts` now `data/output/parser`; logging wired through `utils.logging`) |
| `validation/coverage.py` | `services/parser/validation/source.py` (renamed, moved verbatim) |
| `validation/{structure,markdown,visual,report}.py` | `services/parser/validation/{structure,markdown,visual,report}.py` (moved verbatim, import paths updated) |
| — (new) | `services/parser/service.py`, `services/chunker/*`, `clients/*`, `databases/*`, `prompts/*`, `utils/paths.py`, `utils/hashing.py`, `utils/logging.py` |

No module was rewritten from scratch; every function's body is unchanged
except import statements, unless explicitly noted above (the two
`_sha256_file`/`safe_filename` de-duplications).

## 4. Dependency-direction explanation

Enforced rule: **`api -> pipelines -> services -> utils`**, plus
`services -> clients`/`services -> databases` once implemented. Verified by
`tests/unit/test_architecture.py::TestServiceArchitectureBoundaries`, which
statically scans every import in `utils/`, `services/` and `pipelines/` for a
violation, and separately imports every top-level package in one subprocess
to prove no circular import exists. See
[`docs/architecture/service_architecture.md`](docs/architecture/service_architecture.md)
for the full diagram and rationale.

## 5. Parser public interface

```python
from engineering_rag.services.parser import ParserConfig, ParserRequest, ParserResult, ParserService

result = ParserService().run(ParserRequest(pdf_path=..., config=ParserConfig()))
```

`ParserResult` carries `status`, `run_dir`, `report`, `manifest`, `timings`,
`exit_code` — the same fields the former `pipeline.RunResult` carried.

## 6. Pipeline responsibilities

`pipelines/parsing_pipeline.py::run_parsing_pipeline(pdf_path, config,
output_root=None)` builds a `ParserRequest` (defaulting `output_root` to
`data/output/parser`) and calls `ParserService().run(request)`. It contains no
PDF/Docling logic — that stays entirely inside the service, since "run the
parser end to end" is parser-domain behaviour.

## 7. Logging architecture

`utils/logging.py`, configured once at `api/cli.py`. Console handler (default
`INFO`, silenced under `--json`), automatic per-run file handler at
`<run_dir>/logs/engrag.log` (default `DEBUG`, attached/detached around each
`ParserService.run()` call), optional explicit `--log-file`, optional JSONL
formatting, and a shared `RunContextFilter` injecting `run_id`/`document_id`/
`stage` onto every record without touching the existing `logger.info(...)`
call sites throughout the codebase. Verified live: see §16 for a captured log
line showing full context. Kept deliberately separate from the pre-existing
`JsonlLogger` (`logs/run.jsonl`), which records domain pipeline events and was
not touched. Full detail in
[`docs/architecture/service_architecture.md`](docs/architecture/service_architecture.md#logging-architecture).

## 8. Data input/output architecture

`data/input/` (+ `data/input/ocr/`) and `data/output/parser/<document>/<run-id>/`
are the new defaults, resolved lazily via `utils/paths.py` (never a
module-level constant computed at import time). `--artifacts` on the CLI and
`ParserRequest.output_root` both still accept an explicit override;
`validate`/`show` accept any existing run directory, including one under the
pre-restructure `artifacts/` root. `.gitignore` updated: `data/input/**` and
`data/output/**` ignored, with `.gitkeep` placeholders tracked so the empty
directories exist in a fresh clone; the old `artifacts/`/`quarantine/` entries
were retained (not removed) so any pre-existing local run directories stay
ignored too.

## 9. Files moved or changed

82 files touched: 15 files renamed via `git mv` (parser modules, tests), 2
further parser modules split into 4 new files (`pipeline_factory.py` →
`profiles.py`+`converter.py`; `parser.py` → `converter.py`+`inventory.py`,
merged with the above), 4 old package files deleted (superseded, no
duplicate left behind), 25 new files created (`__init__.py`/`README.md`
boundary files, `service.py`, the 3 new `utils/` modules, 2 new architecture
docs, 2 new `utils/` test files, `test_architecture.py`, `.gitkeep`
placeholders), and the remainder are import-path and documentation updates
in files that already existed (`pyproject.toml`, `.github/workflows/ci.yml`,
`.gitignore`, `README.md`, `docs/architecture.md`,
`docs/docling_parameter_guide.md` (regenerated), `docs/productionization_options.md`,
`docs/_generated/gen_param_guide.py`, `scripts/ocr/*.py`,
`notebooks/01_docling_exploration.ipynb`, `tests/conftest.py`,
`PARSER_STAGE_FINAL_REPORT.md`, `PARSER_RELEASE_CHECKLIST.md`).
Net: **2641 insertions, 1331 deletions** (`git diff --stat` on the commit).

## 10. Test results

| Suite | Result |
|---|---|
| Fast (`pytest -m "not slow"`) | **246 passed, 0 failed** (up from 229; new `utils/` tests + new architecture-boundary tests, nothing lost) |
| Slow (`pytest -m slow -p no:cacheprovider`) | **42 passed, 0 failed** (unchanged — real OCR conversion + full 27-page acceptance suite) |
| **Total** | **288** (up from 271) |

Every test previously present was moved (not deleted) into the service-mirroring
tree; the increase is fully accounted for by the new `tests/unit/utils/` tests
(`test_paths.py`, `test_hashing.py`) and the new
`TestServiceArchitectureBoundaries` class in `test_architecture.py`.

## 11. Coverage

**84%** (`pytest -m "not slow" --cov=engineering_rag --cov-report=term-missing`) —
unchanged from the pre-restructure baseline. Per-module breakdown recorded in
this pass's terminal output; `models.py` 100%, `utils/hashing.py` 100%,
`config.py` 99%, largest gaps unchanged in nature (`exporters.py` 73%,
`report.py` 70% — rare/exceptional branches, same as before).

## 12. Ruff results

`ruff format --check .` — **PASS** (83 files formatted). `ruff check .` —
**PASS** (all checks passed). One unused-import and four formatting issues
introduced during the migration were found and fixed in this pass (an unused
`Counter` import in `converter.py`; line-wrapping in `service.py`,
`utils/logging.py`, `tests/unit/test_architecture.py`, `tests/unit/utils/test_paths.py`).

## 13. mypy result

**PASS** — `Success: no issues found in 31 source files` (up from 17; the
finer-grained module split increases the file count, not the issue count).

## 14. Wheel inspection

`python -m build --wheel` succeeds. The wheel contains the complete
`engineering_rag/` tree (40 entries: every `api/`, `pipelines/`,
`services/{parser,chunker}/`, `clients/`, `databases/`, `prompts/`, `utils/`
file, including the `README.md` boundary docs) and **no** PDF, `artifacts/`
or `data/output/` content. Console-script entry point confirmed inside the
wheel's `entry_points.txt`: `engrag-parse = engineering_rag.api.cli:app`.
Reinstalling editable (`pip install -e . --no-deps`) into the permanent
`.venv` refreshed the installed entry point and confirmed
`engrag-parse --version`/`--help` work.

## 15. Clean-install result

A second, independent `.venv-clean` (outside the permanent `.venv`) was
created, used and removed:

```powershell
py -3.13 -m venv .venv-clean
.venv-clean\Scripts\python.exe -m pip install --upgrade pip
.venv-clean\Scripts\python.exe -m pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision
.venv-clean\Scripts\python.exe -m pip install -e ".[dev,ocr]"
```

| Check | Result |
|---|---|
| `engrag-parse --version` | `engrag-parse 1.0.0` |
| `engrag-parse --help` | Renders all 4 subcommands |
| `pytest -m "not slow"` | **246 passed, 0 failed** |
| `ruff format --check .` | PASS |
| `ruff check .` | PASS |
| `mypy src` | PASS — no issues in 31 source files |
| `python -m build --wheel` | PASS |
| OCR smoke test (`run --profile scanned` on the real image-only benchmark) | **PASS**, exit 0, 0 failed gates |

`.venv-clean` was deleted after verification; `.venv` was never modified.

## 16. OCR acceptance run

| Field | Value |
|---|---|
| Run ID | `20260824T124059Z-57f84fd5` |
| Path | `data/output/parser/scanned_docling_test_image_only/20260824T124059Z-57f84fd5/` |
| Profile | `scanned` (explicit) |
| Status | **PASS**, 0 failed gates |
| OCR engine | RapidOCR (`do_ocr=true`, `ocr_score≈0.986`) |
| Critical-token recall (independent ground truth) | **100% (31/31)** — via `scripts/ocr/validate_ocr_run.py` |
| Word-type recall | 96.9% |
| Per-run log | `data/output/parser/.../logs/engrag.log` confirmed present, with `run_id`/`document_id`/`stage`-tagged lines (e.g. `[run=20260824T124059Z-57f84fd5 doc=scanned_docling_test_image_only.pdf stage=conversion]`) |

## 17. Engineering-PDF acceptance run

| Field | Value |
|---|---|
| Run ID | `20260824T124235Z-01e4d6fa` |
| Path | `data/output/parser/Instrumentation-and-Control-Engineering/20260824T124235Z-01e4d6fa/` |
| Profile | `high_fidelity` (explicit) |
| Status | **PASS_WITH_WARNINGS**, 0 failed gates, 210 artifacts |
| Warnings (4, unchanged) | `critical_token_recall`, `page_text_coverage`, `table_cells_recovered`, `markdown_heading_structure` |
| `document_text_completeness` | PASS, 100% critical-token recall |
| `labelled_tables_located` | PASS — Tables 1, 2, 3 all located |
| `validate --strict` | exit code **1** (warnings correctly escalated — unchanged, intended behaviour) |

## 18. Git safety result

`git add -n .` inspected before staging: only the intended 82 restructure
files plus `data/input/.gitkeep` and `data/output/.gitkeep`. No PDF, no
`artifacts/`/`data/output/**` run content, no secret/credential/token pattern
(`git diff --cached` scanned), no `.venv`/`.venv-clean`, no machine-specific
absolute path. `.gitignore` verified with `git check-ignore -v` /
`git add -n` before and after editing.

## 19. Git commits

| Commit | Message |
|---|---|
| `7415bde` | Refactor parser into service architecture with centralized logging (82 files, +2641/-1331) |
| `8d46a74` | Add restructure completion report |
| `639af27` | Record follow-up commit hash in the restructure report |
| `1a75dde` | Fix CI formatting check (§19.1) |
| `8376a93` | Merge pull request #1 from nnourmmohamedd/refactor/service-architecture (merge commit, on `master`) |

### 19.1 CI defect found and fixed

Once the PR was opened, both GitHub Actions jobs (Python 3.11, Python 3.13)
initially **failed** on the `ruff format --check .` step:

```text
1 file would be reformatted, 84 files already formatted
Error: Process completed with exit code 1
```

Root cause: `docs/architecture/service_architecture.md` (written after this
pass's last local `ruff format` run) contains two embedded Python code
fences, and ruff formats embedded code blocks in Markdown too — so the doc's
hand-aligned trailing comments and a missing blank line after an `import`
inside the example snippets were flagged. Reproduced locally with
`ruff format --check .`, fixed with `ruff format .`; the resulting diff was
inspected and contains only cosmetic whitespace changes inside two example
snippets, no other content changed. Every local CI-equivalent check
(`ruff format --check .`, `ruff check .`, `mypy src`, `pytest -m "not slow"`
— 246 passed, notebook validation, `python -m build --wheel` plus the
wheel-content checks) was re-run and passed before committing `1a75dde` and
pushing. GitHub Actions was then re-run and both jobs passed.

## 20. GitHub branch

`refactor/service-architecture` was pushed, used for PR #1, merged into
`master`, and then deleted — both on the remote (by the merge) and locally
(`git branch -d refactor/service-architecture`, after confirming it was
listed under `git branch --merged master`). It no longer exists in either
location; `master` is the sole active branch, fast-forwarded to `8376a93`.

*Process note (unchanged from the prior version of this report):* the first
restructure commit was made directly on `master` by mistake, then corrected
before pushing — `refactor/service-architecture` was created at that commit
and `master` was reset back to its prior tip before either was pushed. No
work was lost; this is recorded here only for traceability.

## 21. Pull-request URL

**https://github.com/nnourmmohamedd/engineering-rag-parser/pull/1**
(`refactor/service-architecture` → `master`) — opened by the user (this
session's GitHub CLI remained unauthenticated throughout; the PR was created
outside this session), reviewed, and **merged** (merge commit `8376a93`).

## 22. GitHub Actions URL and result

**https://github.com/nnourmmohamedd/engineering-rag-parser/actions** —
**both jobs green** after the fix in §19.1:

| Job | Result |
|---|---|
| Python 3.11 | ✅ PASS |
| Python 3.13 | ✅ PASS |

Each job's steps (ruff format check, ruff lint, mypy, fast tests with
coverage, notebook validation, wheel build, wheel-content checks) all passed.
This is a genuine CI confirmation, not an inference from local checks alone —
the initial failure and its fix (§19.1) were observed through the actual
Actions run.

## 23. Remaining document-level limitations

Unchanged from the parser milestone (not affected by a structural refactor):
the 3 unrecovered tables (raster bodies, 0 machine-readable cells) and the 15
substantive figures on the acceptance document still require human
transcription/confirmation; `critical_token_recall` (pages 1–2, TOC
numbering), `page_text_coverage` (pages 18/23, cross-page relocation),
`table_cells_recovered` and `markdown_heading_structure` remain the same 4
legitimate, source-property warnings. Full detail: `docs/limitations.md`,
`PARSER_STAGE_FINAL_REPORT.md` §9–14.

## 24. Exact parser completion percentage

**Parser software functionality: 100%** (unchanged; re-verified with no
regression under the new architecture, §16–17).
**Parser architecture restructuring: PASS** — package structure, tests,
quality gates, wheel, clean install and both acceptance runs all verified
locally; PR #1 merged into `master` (`8376a93`); both GitHub Actions jobs
(Python 3.11, Python 3.13) green (§19–22). **Full future RAG system: ~18%**
(unchanged; chunking, embeddings, vector storage, retrieval, reranking and
generation remain unimplemented, by design). **Chunking milestone: NOT
STARTED** (`services/chunker/` is a documented empty scaffold only).

## 25. Readiness for the chunking milestone

**Yes**, unchanged from the parser milestone's own conclusion (see
`PARSER_STAGE_FINAL_REPORT.md` §15): `docling/document.json` remains the
canonical input, now additionally reachable at a stable, documented path
(`data/output/parser/<document>/<run-id>/docling/document.json`) and with a
pre-written contract for the next service
(`src/engineering_rag/services/chunker/README.md`). No chunking code exists;
none was added in this pass.

---

*This report was produced by re-executing every command it cites, on the
final code state, in this repository's own `.venv` (and, independently, a
temporary `.venv-clean`). Human engineering review of the parsed document
content (§23) was not performed and is not claimed.*
