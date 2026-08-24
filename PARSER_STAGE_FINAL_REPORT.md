# Parser Stage Final Report

**Report date:** 2026-08-24
**Scope:** finish, harden, test and document the existing PDF-parsing milestone
in `engineering-rag-parser`, against the findings of `PROJECT_COMPLETION_AUDIT.md`
(2026-08-24). No chunking, embeddings, vector store, retrieval, reranking or
chatbot code was added — that remains explicitly out of scope for this pass.

---

## 1. Executive verdict

**`PARSER MILESTONE COMPLETE WITH DOCUMENT-LEVEL WARNINGS`**

All six previously-undocumented defects the audit found (D-1…D-6) are fixed
and covered by regression tests. Every "required work still incomplete" item
the audit could reasonably resolve without a large new heavy dependency
(lockfile, CI, coverage measurement) is now in place. The remaining warnings
are properties of the *source document* (three raster table bodies with no
text layer, fifteen diagrams whose internal semantics no automated check in
this project can verify) — not implementation defects. `PASS_WITH_WARNINGS`
is the correct, intentional final status of the acceptance run, not a
near-miss.

**Software completion and document semantic certainty are different claims.**
This report can state, with reproducible evidence, that the software:
parses all 27 pages, preserves every substantive figure, detects and flags
every table it cannot machine-read, produces portable and reloadable
artifacts, and passes its full test/lint/type suite. It cannot state, and
does not claim, that the content of the three unrecovered tables or the
internal labels/connections of the fifteen preserved diagrams have been
verified by a human. Those are explicitly listed as outstanding human-review
items (§13).

## 2. Final completion percentage

| Dimension | Percentage | Basis |
|---|---:|---|
| **Parser milestone (this repository's declared scope)** | **100%** (updated by §18–20's OCR verification pass) | All 7 defects (D-1…D-7) fixed with regression tests; lockfile, CI and coverage measurement added; `scanned`/OCR path now proven end to end against a genuine image-only PDF (§18), with 100% critical-token recall; clean installation independently verified (§20); original 27-page acceptance document re-verified with no regression (§18.11). Still true: only one OS and one primary acceptance document have been verified; GPU and multi-Python-version execution remain configured but unexercised (§11, §14 A-7). |
| **Full future RAG chatbot** | **~18%** (unchanged) | Parsing is one of roughly six stages (parse → chunk → embed → store → retrieve/rerank → serve). No chunking, embedding, vector store, retrieval, reranking or chat interface exists anywhere in this repository, by design — this pass intentionally did not start that work. |

Neither number is inflated. Where evidence was inconclusive (cold-cache CI
coverage, multi-Python execution), this report says so explicitly in §7/§14
rather than assuming success.

## 3. Environment

| Item | Value |
|---|---|
| OS | Windows 11 Home Single Language, `Windows-11-10.0.26200-SP0`, AMD64 |
| Python | 3.13.9 (CPython) |
| Docling | 2.121.0 |
| docling-core | 2.92.0 |
| docling-ibm-models | 3.14.0 |
| docling-parse | 7.15.0 |
| torch | 2.13.0+cpu (`torch.cuda.is_available() == False`) |
| CPU/GPU | 11th Gen Intel Core i7-1165G7 (4 physical / 8 logical cores); NVIDIA MX450 2 GB detected but unused (CPU-only wheel by design, ADR-002) |
| Active OCR backend | **None installed** (`easyocr` not present); `scanned` profile is implemented but unexercised end-to-end — see §12 |
| pydantic | 2.13.4 · typer 0.26.8 · rich 15.0.0 |
| pytest 9.1.1 · pytest-cov 7.1.0 · ruff 0.16.4 · mypy 2.3.1 | dev tooling now fully installed, including `jupyter 1.1.1`, `nbformat 5.11.1`, `nbclient 0.11.0`, `build 1.5.0` (previously missing — this was audit finding D-1) |

## 4. Architecture (unchanged from the audit)

```text
PDF
→ input safety checks (preflight.py — pypdf/pdfminer.six/pypdfium2, no Docling)
→ profile selection (pipeline_factory.choose_profile, evidence-based + audited reason)
→ Docling conversion (pipeline_factory.build_converter, parser.convert_pdf)
→ DoclingDocument
→ canonical JSON (parser.save_document_json — now with portable URIs, D-3)
→ Markdown / assets (exporters.py — now flags picture-backed labelled tables, D-5)
→ independent validation (validation/* — now includes json_portable_paths, D-5's gate extension)
→ immutable run directory (artifacts.py)
→ reports and human-review artifacts (validation/report.py, validation/visual.py)
```

No module boundary changed. All Docling imports remain confined to
`pipeline_factory.py` and `parser.py` (still enforced by
`test_docling_imports_are_confined`).

## 5. Changes made

| File | Purpose | Behaviour changed |
|---|---|---|
| `pyproject.toml` | D-1 fix | `dev` is now declared under `[project.optional-dependencies]` **in addition to** `[dependency-groups]`, so `pip install -e ".[dev]"` (the documented command) actually works on any pip version. Added `nbformat`, `nbclient`, `build` to the dev set (Phase 2 requirement). |
| `src/engineering_rag_parser/pipeline_factory.py` | D-2 fix | Added `_describe_suboption()`; `describe_effective_options()` now re-serialises `table_structure_options`/`ocr_options`/`picture_description_options` from the live objects by concrete class, instead of the `{}` produced by dumping through the parent's abstract-base-typed field. |
| `src/engineering_rag_parser/parser.py` | D-3 and D-6 fixes | `save_document_json()` now post-processes and re-validates the JSON to rewrite Windows backslash path separators in `"uri"` values to `/`. `build_inventory()` now classifies list items via `ListItem.enumerated` (the field Docling's own Markdown serializer consults) instead of guessing from the `marker` string. |
| `src/engineering_rag_parser/domain.py` | D-5 support | Added `PictureFinding.represents_table_label`. |
| `src/engineering_rag_parser/exporters.py` | D-5 fix | Added `flag_table_only_pictures()`; `export_markdown()` now injects the same "Unrecovered table" warning block for a labelled table detected only as a picture region (Table 3's case) as it already did for zero-cell table regions. |
| `src/engineering_rag_parser/pipeline.py` | D-5 wiring | Calls `flag_table_only_pictures()` between `find_table_labels()` and `export_markdown()`. |
| `src/engineering_rag_parser/validation/structure.py` | D-5 fix | `unrecovered_content_preserved` (the no-silent-loss gate) now also covers picture-represented labelled tables, not only zero-cell table regions. |
| `src/engineering_rag_parser/validation/markdown.py` | D-3 gate | Added the `json_portable_paths` CRITICAL gate checking for backslash separators in any `"uri"` value in `document.json`. |
| `src/engineering_rag_parser/cli.py` | New defect found and fixed during this pass | `_force_utf8_streams()` reconfigures stdout/stderr to UTF-8 before any Rich `Console` is constructed. Without it, `validate --strict` (and any command printing an arrow/warning glyph) crashed with an unhandled `UnicodeEncodeError` on a Windows console running a legacy non-UTF-8 codepage — reproduced live during this pass, not hypothetical. |
| `docs/_generated/gen_param_guide.py` | D-2 fix, applied to generated docs | Uses the same subclass-aware dump so `docs/docling_parameter_guide.md` no longer shows `table_structure_options: {}`. |
| `docs/docling_parameter_guide.md` | Regenerated | Reflects the D-2 fix. |
| `docs/limitations.md` | Documentation | Added §13 (defect disposition table) and §14 (explicit `scanned`/OCR experimental status). |
| `README.md` | Documentation | Added the reproducible-installation (lockfile) section, updated the test/coverage commands, added CI and report references. |
| `requirements.lock` | New (A-1) | Exact `pip freeze` dependency closure of the verified environment, with a documented decision record, regeneration and verification commands. |
| `.github/workflows/ci.yml` | New (A-2) | Format/lint/type/fast-test/coverage/build/notebook-validation on synthetic fixtures only, on a small 2-version Python matrix, running on Linux (a deliberate cross-platform check against D-3-class regressions). |
| `tests/unit/test_inventory.py` | New | Deterministic unit tests for D-6 against a directly-constructed `DoclingDocument` (no model weights needed). |
| `tests/unit/test_cli.py` | New | 21 CLI tests: `--version`/`--help`, exit codes 0/2, `inspect`/`validate`/`show`/`run`, and the UTF-8 stream regression. |
| `tests/unit/test_exporters_and_preflight.py` | Extended | Unit tests for `flag_table_only_pictures` (D-5) and `_portabalize_json_uris` (D-3). |
| `tests/unit/test_validation.py` | Extended | Unit tests for the `json_portable_paths` gate and the extended `unrecovered_content_preserved` gate (both table-region and picture-region loss sources). |
| `tests/integration/test_pipeline_integration.py` | Extended | `describe_effective_options` regression tests for D-2; a real-conversion regression test for D-3's portable URIs. |

## 6. Audit findings

| Finding | Previous status | Verification evidence | Fix | Tests | Final status |
|---|---|---|---|---|---|
| D-1 (install command broken) | HIGH — confirmed via wheel metadata (`Provides-Extra: ['ocr','vlm']`, no `dev`) | Re-verified: `pip show` on the rebuilt wheel now lists `Provides-Extra: dev` with `pytest`/`jupyter`/etc. under it | `dev` extra added to `[project.optional-dependencies]` | Wheel-metadata inspection (manual, §7); `jupyter`/`nbformat`/`nbclient`/`build` now installed and used by the notebook/coverage/build steps | **FIXED** |
| D-2 (`table_structure_options: {}`) | Medium — confirmed via manifest inspection | Re-verified: `describe_effective_options()` now returns `{"type": "TableStructureOptions", "do_cell_matching": true, "mode": "accurate"}`; confirmed in the new final run's `run_manifest.json` | `_describe_suboption()` re-dumps by concrete class | `test_table_structure_options_records_concrete_fields`, `test_ocr_options_records_concrete_fields_when_enabled` | **FIXED** |
| D-3 (Windows backslashes in JSON URIs) | Medium — confirmed, 141/141 URIs affected on the prior run | Re-verified: 0 backslash-URIs in the new run's `docling/document.json` (was 141 previously) | Post-process + re-validate in `save_document_json()`; new `json_portable_paths` gate | `test_normalizes_windows_separator` + 3 more unit tests; `test_json_image_uris_use_portable_separators` (real conversion); `test_backslash_uri_fails_the_gate` + 2 more gate tests | **FIXED** |
| D-4 (final report named the older of two equivalent runs) | Low | N/A — a fresh final run was produced for this pass and is named unambiguously (§8) | Superseded by a new run | — | **RESOLVED (superseded)** |
| D-5 (Table 3 not covered by the no-silent-loss gate) | Medium | Re-verified: `unrecovered_content_preserved` now reports "All 3 unrecovered table region(s)" (was 2) on the new run; Table 3's warning block confirmed present in `markdown/document.md` at the correct position | `flag_table_only_pictures()` + gate extension in `validation/structure.py` | `TestFlagTableOnlyPictures` (4 tests), `TestTableChecksPictureBackedTable` (4 tests) | **FIXED** |
| D-6 (list type inventory disagreed with Markdown, 41 ordered vs 31 rendered bullets) | Low | Re-verified against the real document: `ordered_list_items=10`, `unordered_list_items=31` on the new run — now matches the Markdown's 10 `N.` + 31 `-` markers exactly | `build_inventory()` uses `ListItem.enumerated` | `TestListTypeClassification` (5 tests) against a directly-constructed `DoclingDocument` | **FIXED** |
| CLI Unicode crash (found during this pass, not in the original audit) | — | Reproduced live: `validate --strict` raised an unhandled `UnicodeEncodeError` from Rich on a legacy-codepage Windows console; confirmed exit code was an accidental crash code, not the intended strict-mode escalation | `_force_utf8_streams()` in `cli.py` | `TestForceUtf8Streams` (3 tests) | **FIXED** |
| A-1 (no lockfile) | Medium | — | `requirements.lock` (pip-freeze closure, documented decision not to adopt `uv` — see the file's header) | — | **ADDED** |
| A-2 (no CI) | Low (optional in the brief) | — | `.github/workflows/ci.yml` | Workflow YAML validated with `yaml.safe_load` | **ADDED** |
| A-3/A-4 (`scanned`/OCR unexercised) | Medium | Unchanged: `easyocr` deliberately not installed | Documented explicitly as experimental (`docs/limitations.md` §14); not claimed fixed | — | **NOT ATTEMPTED THIS PASS — see §12** |
| A-5 (no coverage measurement) | Low | — | Measured: 84% (warm model cache) / 58% (cold, as CI will see it) on the fast suite | — | **MEASURED** |
| A-6 (no third-party Markdown linter) | Low | — | Not added this pass (time-boxed; the 9 bespoke structural Markdown checks were judged to cover the same ground with more document-specific precision) | — | **NOT ADDRESSED — acceptable residual gap** |
| A-7 (3.10–3.12 never executed) | Medium | — | CI matrix runs 3.11 and 3.13 (bookends of Docling's tested range and this project's dev version); 3.10/3.12 still asserted only by `requires-python`, not executed | — | **PARTIALLY ADDRESSED** |

## 7. Tests and quality

All commands below were re-executed in this pass's final state, in the
existing `.venv` (Python 3.13.9).

| Check | Command | Result |
|---|---|---|
| Fast tests | `pytest -m "not slow"` | **212 passed, 33 deselected** (up from 168; +44 new/extended regression tests) |
| Slow acceptance tests | `pytest -m slow -p no:cacheprovider` | **33 passed, 212 deselected**, ~72s |
| Coverage (warm model cache) | `pytest -m "not slow" --cov=engineering_rag_parser --cov-report=term-missing` | **84%** overall (`domain.py`/`config.py`/`normalization.py` ≥97%; `cli.py` 85%, up from 0% — no CLI test existed before this pass; `exporters.py` 73% is the largest remaining gap, mostly rare/exceptional branches) |
| Coverage (cold, as CI will actually see it) | same, with `ENGRAG_SKIP_DOCLING=1` (simulates no cached model weights) | **58%** — `requires_docling_models`-gated tests self-skip rather than downloading model weights on every CI job |
| Formatting | `ruff format --check .` | **PASS** — 44 files already formatted |
| Linting | `ruff check .` | **PASS** — all checks passed |
| Type checking | `mypy src` | **PASS** — Success: no issues found in 17 source files |
| Package build | `python -m build --wheel` | **PASS** — `engineering_rag_parser-1.0.0-py3-none-any.whl` built; `Provides-Extra: dev` confirmed present |
| Notebook validation | `nbformat.validate(...)` | **PASS** — valid nbformat 4.5, 31 cells |
| CI configuration | `yaml.safe_load('.github/workflows/ci.yml')` | **PASS** — parses; not executed on a real GitHub runner in this pass (no push made) |

**Total tests: 245** (212 fast + 33 slow), up from the audit's 201.

## 8. Acceptance PDF

| Field | Value |
|---|---|
| Source filename | `Instrumentation-and-Control-Engineering.pdf` |
| SHA-256 | `01e4d6fa3a2e884f83fad507d08b228aa40f814dc0f3c44e6c9db315f73c3b1a` |
| File size | 5,378,401 bytes |
| Page count | 27 |
| **New final run ID** | **`20260824T073915Z-01e4d6fa`** |
| Run directory | `artifacts/Instrumentation-and-Control-Engineering/20260824T073915Z-01e4d6fa/` |
| Profile | `high_fidelity` (explicit) |
| Config hash | `83adcde3902fd35087a0215a044d1d79dd0f4e13d64e7dedd66c6770a2f44671` (same as the audit's run — no config change) |
| Status | `PASS_WITH_WARNINGS` |
| Timings | preflight 1.85s · conversion 66.39s · JSON serialize 4.89s · export 15.21s · validation 0.23s (total ≈88.5s — faster than the audit's 269s run, likely a warmer model/OS cache) |
| Items total / with provenance | 367 / 367 (100%) |
| Text characters (parsed) | consistent with the audit (document-level critical-token recall 100%, word-type recall 100%) |
| Tables (Docling regions) | 2, both `asset_only`, 0 cells each; Table 3 (picture-represented) makes 3 labelled tables total |
| Pictures (Docling regions) | 114; 13 substantive pictures + 2 asset_only tables = 15 substantive assets; 101 decorative repeats excluded |
| List items | 41 total — **10 ordered, 31 unordered** (D-6: now matches the Markdown's rendering exactly) |
| Generated artifacts | 209 files, each SHA-256-hashed in `run_manifest.json` |

## 9. Validation gates

37 checks ran (up from 36 — `json_portable_paths` is new). **0 failed gates.**
Non-`PASS` results are reported as `WARN`, not summarised as `PASS`:

| Check | Gate | Result |
|---|:---:|---|
| page_count_match | ● | PASS |
| page_numbering_monotonic | ● | PASS |
| page_provenance_coverage | ● | PASS |
| critical_token_recall | | **WARN** — pages [1, 2] below threshold (TOC numbering, documented limitation #4) |
| page_text_coverage | | **WARN** — pages [18, 23] below threshold (cross-page relocation, documented limitation #6) |
| no_duplicated_spans | | PASS |
| document_text_completeness | ● | PASS — 100% critical-token recall, 100% word-type recall |
| headings_present | ● | PASS |
| heading_hierarchy_consistent | | PASS |
| toc_sections_recovered | | PASS — 28/28 (100%) |
| captions_attached | | PASS |
| substantive_figures_represented | ● | PASS — all 15 pages |
| decorative_assets_separated | | PASS |
| labelled_tables_located | ● | PASS — all 3 tables located and individually reported |
| table_cells_recovered | | **WARN** — 2/2 detected table regions recovered 0 cells (source property, not a defect) |
| unrecovered_content_preserved | ● | **PASS — now covers all 3 unrecovered tables, including Table 3 (D-5 fix)** |
| table_cell_density | | PASS |
| no_single_cell_tables | | PASS |
| visual_review_coverage | ● | PASS — 17 review artifacts for 15 flagged pages |
| visual_content_not_text_verified | | PASS (an honesty check, not an accuracy claim) |
| markdown_encoding | ● | PASS |
| markdown_non_empty | ● | PASS |
| markdown_image_links | ● | PASS — 15/15 resolve, 0 broken |
| markdown_no_base64 | ● | PASS |
| markdown_no_absolute_paths | | PASS |
| markdown_character_hygiene | | PASS |
| markdown_no_placeholders | ● | PASS |
| markdown_heading_structure | | **WARN** — 1 level jump (cosmetic, documented limitation #2) |
| markdown_table_consistency | | PASS |
| markdown_semantic_retention | | PASS — 101% (76 Markdown headings vs 75 in the DoclingDocument) |
| json_parseable | ● | PASS |
| json_reloads_into_model | ● | PASS |
| **json_portable_paths** | ● | **PASS — new gate (D-3), 0 backslash URIs** |
| json_roundtrip_stable | | PASS |
| source_unmodified | ● | PASS |
| conversion_status | ● | PASS |
| expected_page_count | ● | PASS |

`validate --strict` on this run correctly returns **exit code 1**, escalating
the 4 warnings above — this is the intended, tested behaviour of strict mode,
not a failure of the parser.

## 10. Tables

| | Table 1 | Table 2 | Table 3 |
|---|---|---|---|
| Page (caption) | 16 | 25 | 23 |
| Caption | "C&I Deliverables by Project Phase and Issuance Status" | "Critical Interdisciplinary Data Exchange for C&I Engineering" | "The Purpose and Necessity of C&I Installation Drawings" |
| Representation | Docling `TableItem`, 0 cells | Docling `TableItem`, 0 cells (body on page 26) | Docling `PictureItem` (no table region at all) |
| Cell count | 0 | 0 | 0 (never a candidate — no table region) |
| Asset path | `assets/pictures/page016-table000.png` | `assets/pictures/page026-table001.png` | `assets/pictures/page023-picture096.png` |
| Searchable / machine-readable | **No** | **No** | **No** |
| Covered by the no-silent-loss gate | Yes (always was) | Yes (always was) | **Yes — as of this pass (D-5)** |
| Review status | Pending human transcription | Pending human transcription | Pending human transcription |

All three are explicit `CRITICAL`-severity findings, all three carry an
asset and an in-place Markdown warning, and all three are listed under
`human_review_items`. None of the three is presented as, or mistaken for,
recovered structured data anywhere in the artifacts.

## 11. Engineering figures

- **15 substantive figures preserved**, on pages 4, 6, 8, 9, 11, 13, 14, 18,
  20, 21, 22, 27 (12 pictures) plus the 3 table-body pages counted separately
  in §10.
- **Internal semantics NOT verified.** No automated check in this project — or
  any prior audit of it — confirms that P&ID symbols, tag numbers, signal
  lines or diagram relationships were recovered. Only 1 of 15 has a caption
  at all (Table 3's).
- **17 review artifacts** (`validation/review/*.html`) exist for the 15
  figure-bearing pages plus pages 1–2 (TOC warnings). **No evidence exists
  that a human has opened any of them** — this report does not claim
  otherwise. See §13.

## 12. OCR/scanned status

- **Not installed:** `easyocr` (the `[ocr]` extra) remains uninstalled in
  this environment — a deliberate choice, unchanged from the audit, because
  the acceptance document has a clean native text layer and does not need it,
  and the dependency is a ~100 MB download unjustified for this milestone.
- **Scanned-PDF testing did NOT pass in this pass, because it was not
  attempted.** This is stated plainly rather than left ambiguous: OCR
  **option construction** is unit-tested (`test_scanned_enables_full_page_ocr`,
  still passing), but no actual OCR **conversion** has ever been executed
  against any document, real or synthetic, in this repository's history.
- **What remains experimental:** the `scanned` profile and the `auto`
  profile's routing decision to it. Both are implemented and documented as
  such in `docs/limitations.md` §14 — not claimed as proven.
- If a genuinely scanned document needs processing: `pip install -e ".[ocr]"`,
  then `engrag-parse run --profile scanned --input <scan>.pdf`. The CLI will
  either succeed with a visible `ocr_engine`/`ocr_score` recorded in the
  manifest, or fail loudly (exit 3, exception message on stderr) — it will
  not silently claim success. This loud-failure behaviour was verified this
  pass as part of fixing the CLI's Unicode-crash defect (§6), which touched
  the same error-reporting path.

## 13. Human-review status

- **Review artifacts generated:** 17 HTML cards, unchanged in mechanism from
  the audit, now regenerated fresh for the new run.
- **Review pages:** 1, 2, 4, 6, 8, 9, 11, 13, 14, 16, 18, 20, 21, 22, 23, 26,
  27.
- **Human engineering sign-off: has NOT occurred.** This report is produced
  by an AI assistant and explicitly cannot provide engineering sign-off on
  P&ID symbols, tag numbers, signal-line connectivity, or the correctness of
  the three unrecovered tables' transcription. Completion of the *software
  workflow* — generating the review artifacts, gating on their presence, and
  listing every item under `human_review_items` — is verified and complete.
  A qualified human reviewing the 17 cards and the 3 table images is a
  separate, outstanding step.

## 14. Remaining limitations

**Fixed software defects (this pass):** D-1 through D-6, plus the CLI
Unicode-crash defect found during verification (§6).

**Accepted document warnings (source properties, not defects):**
`critical_token_recall` (pages 1–2, TOC numbering), `page_text_coverage`
(pages 18/23, cross-page paragraph relocation — content is `relocated`, not
lost), `table_cells_recovered` (Tables 1–2's raster bodies),
`markdown_heading_structure` (1 cosmetic heading-level jump). All four are
explained in `docs/limitations.md` and reproduced with evidence in §9 above.

**Human-review requirements:** the 3 unrecovered tables and the 15
substantive figures — see §10–13. Not resolvable by any change to this
codebase; they require either the tables' authoring source, manual
transcription, a targeted OCR pass, or human visual confirmation of the
diagrams.

**Future enhancements (out of scope, unchanged from the audit):**
structure-aware chunking from `document.json`, embeddings, vector storage,
retrieval, reranking, a chat interface, targeted OCR for the 3 tables, a
diagram-understanding stage, and a container image. None of this was started,
per the master prompt's explicit instruction not to.

**Genuinely not attempted this pass, stated plainly:** running the `scanned`
profile against a real OCR conversion (§12); executing the fast test suite on
Python 3.10/3.12 locally (CI now covers 3.11/3.13; §6 A-7); adding a
third-party Markdown linter (A-6, judged lower-value than the existing 9
bespoke structural checks given the time budget); actually pushing and
observing a GitHub Actions run (no `git push` was performed — see §17).

## 15. RAG readiness

**Yes, ready for structure-aware chunking**, using
**`docling/document.json`** as the canonical input — unchanged conclusion
from the audit, now with two additional guarantees this pass adds:

1. Its image URIs are portable (D-3): a chunking pipeline running on Linux
   in production will not silently fail to resolve a Windows-authored path.
2. Its `table_structure_options` and OCR configuration are now accurately
   recorded in the accompanying `run_manifest.json` (D-2), so a chunking
   pipeline choosing how to treat a given run's tables can trust the
   manifest rather than needing to re-derive the effective configuration.

**Flattened Markdown alone should not be the only chunking source** because:
it drops per-item bounding boxes and the element tree Markdown serialization
discards; it cannot distinguish an `asset_only` table from body text without
regex-matching the warning blockquote this project injects; and — as of this
pass — the picture-represented Table 3 case (D-5) demonstrates that even a
*labelled* table can arrive as an ordinary picture reference with no special
markup unless the exporter explicitly injects one, which is exactly the kind
of representation-specific knowledge that belongs in code operating on the
structured JSON, not in a markdown-parsing heuristic.

## 16. Final commands

```powershell
# Installation (flexible ranges)
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision
python -m pip install -e ".[dev]"

# Installation (exact lock)
python -m pip install -r requirements.lock
python -m pip install -e . --no-deps

# Notebook
python -m ipykernel install --user --name engineering-rag-parser --display-name "Python (engineering-rag-parser)"
# then open notebooks/01_docling_exploration.ipynb in VS Code, select that kernel

# CLI
.\.venv\Scripts\engrag-parse.exe inspect  --input "data\input\Instrumentation-and-Control-Engineering.pdf"
.\.venv\Scripts\engrag-parse.exe run      --input "data\input\Instrumentation-and-Control-Engineering.pdf" --profile high_fidelity
.\.venv\Scripts\engrag-parse.exe show     --run "artifacts\Instrumentation-and-Control-Engineering\20260824T073915Z-01e4d6fa"
.\.venv\Scripts\engrag-parse.exe validate --run "artifacts\Instrumentation-and-Control-Engineering\20260824T073915Z-01e4d6fa"
.\.venv\Scripts\engrag-parse.exe validate --run "artifacts\Instrumentation-and-Control-Engineering\20260824T073915Z-01e4d6fa" --strict

# Tests / quality
.\.venv\Scripts\python.exe -m pytest -m "not slow"
.\.venv\Scripts\python.exe -m pytest -m slow -p no:cacheprovider
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\mypy.exe src
.\.venv\Scripts\python.exe -m pytest -m "not slow" --cov=engineering_rag_parser --cov-report=term-missing --cov-report=html
.\.venv\Scripts\python.exe -m build --wheel
```

## 17. Git status (at the end of the first pass, commit `768d410`)

| | |
|---|---|
| Branch | `master` |
| Committed as | `768d410` — "Fix D-1..D-6 audit defects, add CLI tests, lockfile, and CI" |
| Remote | `https://github.com/nnourmmohamedd/engineering-rag-parser.git` (added and pushed in a prior session) |

This pass's own commit/push status (OCR verification changes) is recorded in §21.

---

## 18. OCR/scanned-path verification pass (2026-08-24, second pass)

This section supersedes §12's "not attempted" status. The `scanned`/OCR path
has now been run end to end, independently validated, and is covered by
regression tests — not merely unit-tested for option construction.

### 18.1 Source PDF (independent inspection, no Docling)

| Field | Value |
|---|---|
| File | `data/input/ocr/scanned_docling_test_source.pdf` |
| SHA-256 | `9f8584370b06588304f48665edecc65e74890bc89063e8b070ae3f6a70ff8dc4` |
| Size | 51,191 bytes |
| Pages | 2, A4 (595.28 × 841.89 pt), PDF 1.7, not encrypted |
| Producer | WeasyPrint 62.3 |
| Native text | 1,834 chars / 258 words (pypdf); 1,851 chars (pdfminer.six per-page sum) |
| Page 1 | 1,741 chars — dense: multi-column layout, margin callout, headings, a data table, checkboxes, math notation, form fields, a code block |
| Page 2 | 110 chars — nearly blank (single footer line), confirmed intentional, not an extraction failure |
| Images (pypdf) | 0 — text/vector rendered, not a scan (confirms it is native-text ground truth, not proof of OCR) |
| Ground-truth manifest | `artifacts/ocr_validation/ground_truth_manifest.json` (built by `scripts/ocr/build_ground_truth.py`, using only pypdf + pdfminer.six — never Docling); gitignored (derived document content), regenerate on demand |
| Critical-token set | 31 tokens in `scripts/ocr/critical_tokens.json` (title, DOC-REF, table model/metric values, status labels, form fields, code identifiers, math section heading, a proper name) |

### 18.2 Genuine image-only derivative (proof, not assertion)

| Field | Value |
|---|---|
| File | `data/input/ocr/scanned_docling_test_image_only.pdf` (gitignored) |
| Generator | `scripts/ocr/make_image_only_pdf.py` — renders every source page via `pypdfium2` at 400 DPI, rebuilds each page as a new PDF containing only that raster (via `reportlab`), no native text layer, no hidden OCR text |
| SHA-256 | `57f84fd5b7d2e03db2fd6bbdb3877c7f3ed3201e28a1ef7b137e4445b733432a` |
| Size | 1,420,000 bytes |
| Pages | 2 (preserved), A4 dimensions preserved, page order preserved, near-blank page 2 preserved as a real page |
| **Image-only proof** | `pdfminer.six` extracts **0** characters; each page carries exactly **1** raster image (pypdf); file opens and every page renders via `pypdfium2` |
| Regression coverage | `tests/unit/test_ocr_image_only_pdf.py` (10 tests, synthetic fixture, no confidential PDF needed) |
| DPI note | 300 DPI initially used; raised to **400 DPI** after diagnosing one OCR misread (§18.6) — this is now the recommended minimum for small text |

### 18.3 OCR dependency and engine selection

| Item | Value |
|---|---|
| Chosen engine | **RapidOCR** (`rapidocr-onnxruntime` 1.2.3), onnxruntime backend |
| License | Apache-2.0 |
| Local/offline | Yes — detection (`PP-OCRv6_det_small`), classification (`ch_ppocr_mobile_v2.0_cls_mobile`) and recognition (`PP-OCRv6_rec_small`) ONNX models ship **inside the pip wheel**; no runtime network call |
| Install size | ~26 MB wheel (rapidocr-onnxruntime + onnxruntime + protobuf + flatbuffers) |
| Python 3.13 / Windows | Verified working in this environment |
| Linux CI | Same pure-Python/onnxruntime stack; no OS-specific step required |
| Docling selection | `docling.ocr_engine: rapidocr` → `RapidOcrOptions` (already implemented in `pipeline_factory._OCR_ENGINES`, unchanged code) |
| Install command | `pip install -e ".[ocr]"` |
| Why not EasyOCR (the originally-shipped default) | EasyOCR (`easyocr` 1.7.2, also installed and confirmed importable) downloads ~100 MB of weights from `github.com/JaidedAI/EasyOCR/releases` on first use. That host was **unreachable from the verification environment**: `urllib`, `requests` and `curl` all failed with TLS-level connection resets against `github.com` (confirmed across 4+ retries with backoff), while `pypi.org`, `huggingface.co` and GitHub's own CDN subdomain (`objects.githubusercontent.com`) all succeeded — a targeted external network restriction, not a code defect. EasyOCR remains fully supported (`ocr_engine: easyocr`, `pip install -e ".[ocr-easyocr]"`) for environments where that host is reachable, and is still exercised by existing unit tests for option construction. |

### 18.4 Profile selection (Phase 4)

| Input | `auto` decision | Evidence |
|---|---|---|
| Native-text source | `default` | "Uniform digital text (917 chars/page) with no substantive figures" |
| Image-only derivative | `scanned` | "2/2 pages carry little or no extractable text (0 chars/page): the document behaves as image-only, so OCR is required" |

`choose_profile()` correctly distinguishes the two files from preflight evidence alone (no Docling
involved in the decision). Regression coverage: `tests/integration/test_ocr_conversion.py::TestImageOnlyDetection`.

### 18.5 Real OCR conversion runs

| Run | Profile | Run ID | Status | Exit |
|---|---|---|---|---|
| Explicit scanned | `scanned` | `20260824T100730Z-57f84fd5` | **PASS** | 0 |
| Automatic | `auto` (routed to `scanned`) | `20260824T100804Z-57f84fd5` | **PASS** | 0 |

Both runs are byte-for-byte equivalent in content (auto correctly resolves to the same effective
`scanned` configuration). Manifest confirms: `do_ocr=true`, `ocr_options.type=RapidOcrOptions`,
`ocr_options.backend=onnxruntime`, `ocr_options.mode=full_page`, `ocr_score=0.9856`. Conversion runtime
~16s (no model download at runtime). Full artifact tree produced: source manifest, canonical JSON,
Markdown, page/picture assets, validation report, run manifest, logs.

### 18.6 OCR validation against the independent ground truth

Computed by `scripts/ocr/validate_ocr_run.py`, using the same normalization primitives
(`normalize_for_compare`, `token_recall`, `critical_tokens`) the rest of the validation framework uses —
not a bespoke OCR-only methodology.

| Metric | Value |
|---|---|
| Page count | 2/2 match |
| Page order | Preserved |
| Blank/near-blank page 2 | Preserved with provenance, not dropped |
| Character recall (normalized) | 146% (Markdown includes both a Markdown-table and an HTML-table rendering of the recovered data table — an intentional dual-representation, not duplication/loss) |
| Word-type recall | 96.86% |
| **Critical-token recall** | **100% (31/31)** |
| Heading recovery | All 5 section headings + title recovered |
| Multi-column reading order | Usable — left/right column content not interleaved |
| Margin callout | Recovered as its own heading, correctly separated from body text |
| Table caption/header/row recovery | Recovered as both a Markdown pipe table and an HTML table (4 rows × 5 cols, all values correct) |
| Checkbox/status recovery | `- [x] OCR Images`, `- [ ] Extract Formulae as LaTeX` correctly recovered |
| Form-label recovery | Inspection ID, Chunking Strategy, Vector Store all recovered |
| Code-block recovery | All 4 lines of the Python snippet recovered verbatim |
| Math recovery | Recovered as plain text (`f(x) = ∫0 ∞ e−x² dx = √π/2`) — normalized comparison, not exact LaTeX equality (not required) |
| JSON reload | `DoclingDocument.load_from_json` succeeds |
| Markdown | Non-empty, portable, no absolute paths |
| Asset links | Resolve |
| Provenance | Retained per page |
| Disclosed limitation | At 300 DPI, one proper name was misread ("El-Sayed" → "E1-Sayed", an l/1 glyph confusion — a textbook OCR ambiguity). Diagnosed, and resolved by raising render DPI to 400; not papered over by relaxing the critical-token threshold. |

### 18.7 Software defect found and fixed during OCR verification (D-7)

| ID | Defect | Root cause | Fix | Tests |
|---|---|---|---|---|
| D-7 | `labelled_tables_located` (CRITICAL gate) failed on any document with **zero** `Table N:` captions in its native text, even though nothing was actually unaccounted for | `passed = bool(located) and not unaccounted` required at least one label to exist, which is only true for documents shaped like the acceptance PDF | `validation/structure.py`: `passed = not unaccounted` — an empty `located` dict is not a failure, only a genuinely unaccounted label is | `tests/unit/test_validation.py::TestLabelledTablesLocatedNoLabelsInSource` (2 new tests); re-verified the acceptance PDF's 3 real tables are still located correctly (§11 below) |

### 18.8 Failure-mode tests (Phase 8)

`tests/unit/test_ocr_failure_modes.py` (5 tests): missing OCR dependency, OCR engine initialization
failure, and OCR conversion failure all produce **exit code 3** with a readable message, never a
fabricated `PASS`, in both text and `--json` output modes; no `run_manifest.json` is ever left claiming
`PASS`/`PASS_WITH_WARNINGS` after a failed conversion.

### 18.9 Test suite growth

| Area | New tests |
|---|---|
| Image-only PDF generation utility | 10 (`tests/unit/test_ocr_image_only_pdf.py`) |
| Real OCR conversion (integration, synthetic fixture, self-skips without `rapidocr`/model weights) | 9 (`tests/integration/test_ocr_conversion.py`) |
| OCR failure modes | 5 (`tests/unit/test_ocr_failure_modes.py`) |
| D-7 gate regression | 2 (`tests/unit/test_validation.py`) |
| **New total** | **271 tests** (229 fast + 42 slow), up from 245 |

### 18.10 Full quality suite (re-run after all OCR changes)

| Check | Result |
|---|---|
| Fast tests | **229 passed, 0 failed** |
| Slow tests | **42 passed, 0 failed** (includes the real OCR conversion + full 27-page acceptance suite) |
| Coverage (warm cache) | **84%** |
| `ruff format --check .` | PASS (51 files) |
| `ruff check .` | PASS |
| `mypy src` | PASS — no issues in 17 source files |
| `python -m build --wheel` | PASS — `Provides-Extra: dev, ocr, ocr-easyocr, vlm` |
| Notebook | Valid nbformat 4.5, 31 cells |

### 18.11 Main acceptance PDF re-run (no regression)

| Field | Value |
|---|---|
| New run ID | `20260824T103000Z-01e4d6fa` |
| Status | `PASS_WITH_WARNINGS` (unchanged) |
| Gates | 37 checks, **0 failed** (unchanged) |
| Warnings | Same 4 legitimate document-level warnings as before: `critical_token_recall`, `page_text_coverage`, `table_cells_recovered`, `markdown_heading_structure` |
| All 3 tables still located | Yes — `labelled_tables_located` and `unrecovered_content_preserved` both PASS, confirming D-7's fix did not affect a document that genuinely has labelled tables |
| `validate --strict` | Exit code 1 (warnings correctly escalated) — unchanged, intended behaviour |

### 18.12 OCR acceptance criteria (Phase 7) — all satisfied

Image-only status independently proven; OCR demonstrably activated (`do_ocr=true`, `ocr_score=0.9856`
in the manifest); every source page represented in order; the blank-looking page preserved and
classified; OCR engine/settings recorded; JSON parses and reloads; Markdown non-empty and portable;
asset links resolve; provenance retained; **100% of critical identity tokens recovered**; multi-column
reading order usable; the one OCR limitation found is disclosed, not hidden; all automated tests pass.

---

## 19. Updated completion status

| Dimension | Status |
|---|---|
| **Parser software milestone** | **100%** — all prior defects (D-1…D-7) fixed with regression tests; OCR/scanned path proven end to end; clean installation verified (§20); full test/lint/type/build suite passes; original 27-page acceptance document re-verified with no regression |
| Controlled OCR benchmark | **PASS** (100% critical-token recall; one disclosed, resolved glyph-level limitation) |
| Original engineering PDF | `PASS_WITH_WARNINGS` (4 legitimate, unchanged document-level warnings) |
| Human engineering semantic review | **PENDING** — unchanged; the 3 unrecovered tables and 15 diagrams on the acceptance document still require human sign-off; this is a document-review requirement, not a software gap |
| Full future RAG chatbot | **~18%** (unchanged; parsing is one of six stages; no chunking/embedding/retrieval code exists, by design) |

---

## 20. Clean-installation proof

A temporary `.venv-clean` (outside the permanent `.venv`) was created, used, and removed after
verification; `.venv` was never touched.

```powershell
py -3.13 -m venv .venv-clean
.venv-clean\Scripts\python.exe -m pip install --upgrade pip
.venv-clean\Scripts\python.exe -m pip install -e ".[dev,ocr]"
```

| Check | Result |
|---|---|
| `engrag-parse --version` | `engrag-parse 1.0.0` |
| `engrag-parse --help` | Renders all 4 subcommands |
| `pytest -m "not slow"` | **229 passed, 0 failed** |
| `ruff format --check .` | PASS (51 files) |
| `ruff check .` | PASS |
| `mypy src` | PASS — no issues in 17 source files |
| `python -m build --wheel` | PASS |
| OCR smoke test (`run --profile scanned` on the real image-only benchmark) | **PASS**, exit 0, 0 failed gates, 24.3s (RapidOCR — no model download needed) |

`.venv-clean` was deleted after verification; `.venv` (the permanent environment) was not modified.

---

## 21. Service-architecture restructure (2026-08-24, third pass)

This section records a structural migration, not a parsing-behaviour change.
Everything in §1–20 above describes the parser as it existed under the flat
`src/engineering_rag_parser/` package (module names like `pipeline_factory.py`,
`parser.py`, `domain.py` in §5–6/§18 are historical evidence of that state and
are retained unedited for traceability — they were correct descriptions of the
code at the time each defect was found and fixed).

The parser was then restructured, at the mentor's requirement, into a
service-oriented layout under `src/engineering_rag/`:
`services/parser/` (the complete parser, moved and — where two responsibilities
shared one file — split, never rewritten), `pipelines/parsing_pipeline.py`
(thin orchestration), `api/cli.py` (the CLI), `utils/{paths,hashing,logging}.py`
(new shared helpers, including centralized `logging`), and empty, documented
boundary packages for the next milestones (`services/chunker/`, `clients/`,
`databases/`, `prompts/`).

**No parsing behaviour changed.** The OCR benchmark and the original
27-page engineering PDF were both re-run through the new architecture and
paths (`data/output/parser/`, replacing `artifacts/` as the default) and
produced the same status, the same gate results, and the same 100%
document-level critical-token recall as §8–11 and §18 above. Full evidence —
migration mapping, test results (now 246 fast + 42 slow = 288, up from 271;
the increase is new `utils/`-module tests and new architecture-boundary
tests, not lost coverage), coverage, ruff, mypy, wheel inspection, a second
clean-install run against the new package, the two acceptance re-runs, and
the Git/CI outcome — is in
[`RESTRUCTURE_COMPLETION_REPORT.md`](RESTRUCTURE_COMPLETION_REPORT.md), the
authoritative report for this pass.

| Dimension | Status |
|---|---|
| Parser software functionality | **100%** (unchanged from §19 — verified with no regression under the new architecture) |
| Parser architecture restructuring | **PASS** — PR #1 merged into `master` (`8376a93`); both GitHub Actions jobs (Python 3.11, Python 3.13) green. See `RESTRUCTURE_COMPLETION_REPORT.md` for full evidence |
| Controlled OCR benchmark | **PASS** (unchanged, re-verified through the new paths) |
| Original engineering PDF | `PASS_WITH_WARNINGS` (unchanged, re-verified through the new paths) |
| Human engineering semantic review | **PENDING** — unchanged; not affected by a structural refactor |
| Full future RAG chatbot | **~18%** (unchanged; chunking, embeddings, retrieval, reranking, generation remain unimplemented) |
| Chunking milestone | **NOT STARTED** — `services/chunker/` is a documented empty scaffold only |

---

*This report was produced by re-executing every command it cites, on the
final code state, in this repository's own `.venv` (and, for §21, a second
temporary `.venv-clean`). It supersedes the completion percentages and defect
list in `PROJECT_COMPLETION_AUDIT.md`, which remains the evidence baseline
the first pass was scoped against and is retained for traceability. §18–20
record the second, OCR-focused verification pass; §1–17 record the first;
§21 records the third, architecture-restructure pass — see
`RESTRUCTURE_COMPLETION_REPORT.md` for its full evidence.*
