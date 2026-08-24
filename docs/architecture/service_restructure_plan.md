# Service Restructure Plan

**Status:** implemented in this pass (this document is the plan that drove the
migration; see `docs/architecture/service_architecture.md` for the resulting
architecture and `RESTRUCTURE_COMPLETION_REPORT.md` for verification evidence).

Scope: restructure `engineering_rag_parser` into a service-oriented package
`engineering_rag` under `src/`, with `utils/services/prompts/pipelines/clients/
databases/api` top-level areas, per the mentor's architecture requirement.
**No parsing behaviour, validation gate, CLI option or output guarantee
changes.** No chunking, embeddings, retrieval, reranking, API server or
chatbot is implemented.

## 1. New package layout

```text
src/engineering_rag/
├── __init__.py            # __version__
├── api/                   # CLI boundary (Typer app); future HTTP lives here
├── clients/                # empty boundary + README (future embedding/LLM/reranker clients)
├── databases/               # empty boundary + README (future ChromaDB/metadata store)
├── prompts/                  # empty boundary + README (future retrieval/generation prompts)
├── pipelines/                 # orchestration only
├── services/
│   ├── parser/                 # the complete, working parser (moved from src/engineering_rag_parser)
│   │   └── validation/
│   └── chunker/                 # empty scaffold + documented future contract
└── utils/                        # generic, service-agnostic helpers
```

## 2. Complete old → new module mapping

| Old module | New module | Responsibility | Notes |
|---|---|---|---|
| `src/engineering_rag_parser/__init__.py` | `src/engineering_rag/__init__.py` | Package `__version__` | `PARSER_VERSION` re-exported from `services/parser/__init__.py` |
| `src/engineering_rag_parser/config.py` | `services/parser/config.py` | `ParserConfig` and all option models | Moved verbatim; docstring cross-references updated |
| `src/engineering_rag_parser/domain.py` | `services/parser/models.py` | Manifests, inventories, report models | Renamed `domain.py` → `models.py` per target tree; content unchanged |
| `src/engineering_rag_parser/normalization.py` | `services/parser/normalization.py` | Text normalisation/token primitives | Moved verbatim; parser-domain only (no other service consumes it yet) |
| `src/engineering_rag_parser/preflight.py` | `services/parser/preflight.py` | Independent (non-Docling) source inventory | `_sha256_file` now calls `utils.hashing.sha256_file` (dedup) |
| `src/engineering_rag_parser/pipeline_factory.py` | split: `services/parser/profiles.py` + `services/parser/converter.py` | Profile decision vs. Docling object construction were two responsibilities in one file | `choose_profile`/`resolve_profile_config`/`ProfileDecision` → `profiles.py`; `build_converter`/`build_pipeline_options`/`describe_effective_options`/`docling_versions` → `converter.py` |
| `src/engineering_rag_parser/parser.py` | split: `services/parser/converter.py` + `services/parser/inventory.py` | Conversion+JSON I/O vs. structural counting were two responsibilities | `convert_pdf`/`save_document_json`/`reload_document_json`/`page_texts` → `converter.py` (joins the Docling-converter-construction code above — both are "own the DoclingDocument lifecycle"); `build_inventory` → `inventory.py` |
| `src/engineering_rag_parser/exporters.py` | `services/parser/exporters.py` | Asset extraction, Markdown export | Moved; `safe_filename`/`sha256_file` imports repointed to `utils.paths`/`utils.hashing` |
| `src/engineering_rag_parser/artifacts.py` | `services/parser/artifacts.py` | Immutable run directories, run manifest, JSONL log | `safe_filename`/`UnsafePathError`/`sha256_file` extracted to `utils.paths`/`utils.hashing`; `RunDirectory`/`RunManifest`/`JsonlLogger` stay (parser-run-shaped, not yet reusable) |
| `src/engineering_rag_parser/pipeline.py` | `pipelines/parsing_pipeline.py` (thin) + `services/parser/service.py` (execution) | Orchestration vs. service execution | `run_pipeline()`'s body becomes `ParserService.run()`; `pipelines/parsing_pipeline.py` exposes `run_parsing_pipeline()`, which builds a `ParserRequest` and calls the service — identical execution order, now behind a service boundary |
| `src/engineering_rag_parser/cli.py` | `api/cli.py` | Typer app | Adds `--log-file`; default `--artifacts` now resolves to `data/output/parser`; wires `utils.logging.configure_logging()` at the app boundary instead of inline `logging.basicConfig` |
| `src/engineering_rag_parser/validation/__init__.py` | `services/parser/validation/__init__.py` | subpackage marker | `__all__` updated for the `source.py` rename |
| `src/engineering_rag_parser/validation/coverage.py` | `services/parser/validation/source.py` | Page coverage vs. independent source baseline | Renamed per target tree; content unchanged besides import paths |
| `src/engineering_rag_parser/validation/structure.py` | `services/parser/validation/structure.py` | Headings/TOC/table audits | Import paths only |
| `src/engineering_rag_parser/validation/markdown.py` | `services/parser/validation/markdown.py` | Markdown/JSON QA | Import paths only |
| `src/engineering_rag_parser/validation/visual.py` | `services/parser/validation/visual.py` | Review-card generation | Import paths only |
| `src/engineering_rag_parser/validation/report.py` | `services/parser/validation/report.py` | Report assembly, CSV, Markdown report | Import paths only |
| (new) | `services/parser/service.py` | `ParserService`, `ParserRequest`, `ParserResult` — public parser interface | New: thin class wrapping the exact sequence `pipeline.run_pipeline()` used to execute |
| (new) | `services/chunker/__init__.py` + `README.md` | Documented empty scaffold | No implementation |
| (new) | `utils/logging.py` | Centralised stdlib `logging` configuration | New: console + per-run file + optional JSONL handler, contextual filter |
| (new) | `utils/paths.py` | `safe_filename`, `UnsafePathError`, repo-root discovery, `data/input`+`data/output/{parser,chunker}` defaults | New; extracted from `artifacts.py` + new path-root logic |
| (new) | `utils/hashing.py` | `sha256_file` | Extracted (was duplicated in `preflight.py` and `artifacts.py`) |
| (new) | `api/README.md`, `clients/README.md`, `databases/README.md`, `prompts/README.md` | Boundary documentation | No executable code |

## 3. Public interfaces

* `engineering_rag.services.parser` exposes `ParserService`, `ParserRequest`,
  `ParserResult`, `PARSER_VERSION`, `ParserConfig`, `Profile`, `load_config`
  (config is still the documented YAML contract) and the exception types
  (`PreflightError`, `ConversionFailedError`). Internal modules
  (`converter`, `inventory`, `profiles`, `exporters`, `artifacts`,
  `preflight`, `normalization`, `validation.*`) remain importable for tests
  but are not part of the advertised surface.
* `engineering_rag.pipelines.parsing_pipeline.run_parsing_pipeline(...)` is
  the one orchestration entry point the CLI (and any future worker) calls.
* `engineering_rag.api.cli:app` is the Typer application; the console script
  becomes `engrag-parse = "engineering_rag.api.cli:app"`.

## 4. Dependency direction (enforced by an architecture test)

```
api → pipelines → services → utils
services → clients / databases   (boundary only, unused today)
```

Forbidden and tested for: `services → pipelines`, `services → api`,
`utils → services`, any circular import, and any Docling import outside
`services/parser/{converter.py, inventory.py, exporters.py,
validation/structure.py, validation/visual.py}`.

## 5. Affected imports / tests / non-source references

* **Tests** (`tests/unit/*.py`, `tests/integration/*.py`, `tests/conftest.py`):
  every `from engineering_rag_parser...` import rewritten to
  `from engineering_rag.services.parser...` / `engineering_rag.pipelines...` /
  `engineering_rag.api...`; test tree reorganised to mirror the service tree
  (`tests/unit/services/parser/`, `tests/unit/api/`, `tests/unit/utils/`,
  `tests/integration/services/parser/`, `tests/integration/pipelines/`).
* **Notebook** (`notebooks/01_docling_exploration.ipynb`): all
  `engineering_rag_parser` imports rewritten to `engineering_rag.*`.
* **Scripts** (`scripts/ocr/validate_ocr_run.py`): imports rewritten.
  `scripts/ocr/make_image_only_pdf.py` has no package import (uses only
  third-party libs) — unchanged.
* **Docs generation** (`docs/_generated/gen_param_guide.py`): imports
  rewritten to `engineering_rag.services.parser.{config,converter}`.
* **Documentation** (`README.md`, `docs/architecture.md`,
  `docs/docling_parameter_guide.md`, `docs/limitations.md`,
  `docs/validation_methodology.md`, `docs/productionization_options.md`,
  `PARSER_STAGE_FINAL_REPORT.md`, `PARSER_RELEASE_CHECKLIST.md`): package
  name and `artifacts/` output-root references updated to
  `engineering_rag` / `data/output/parser/`.
* **Packaging** (`pyproject.toml`): `[tool.hatch.build.targets.wheel].packages`
  → `["src/engineering_rag"]`; console script →
  `engineering_rag.api.cli:app`; `[tool.ruff.lint.isort].known-first-party`
  → `["engineering_rag"]`; `[tool.mypy].files` unchanged (`["src"]`);
  `[tool.coverage.run].source` → `["src/engineering_rag"]`.
* **CI** (`.github/workflows/ci.yml`): `--cov=engineering_rag_parser` →
  `--cov=engineering_rag`; wheel-content check unchanged (path-pattern based).
* **`.gitignore`**: `artifacts/`/`quarantine/` entries retained (back-compat
  for any pre-existing local runs) and `data/output/**` added; `data/input/**`
  already present.

## 6. Circular-dependency risks identified and avoided

* `validation/visual.py` imports `preflight.render_page_png` and
  `artifacts.RunDirectory` — both stay siblings inside `services/parser/`, no
  cycle.
* `pipelines/parsing_pipeline.py` must not be imported by anything under
  `services/` — verified by `test_architecture.py`.
* `utils/paths.py` and `utils/hashing.py` must not import anything from
  `services/` — verified by the same test; `services/parser/artifacts.py` and
  `preflight.py` import *from* `utils`, never the reverse.

## 7. Data directory migration

`data/input/` and `data/input/ocr/` already existed with the acceptance PDF
and OCR benchmark fixtures in place (pre-existing local state, confirmed
git-ignored). Default parser output root becomes `data/output/parser/`
(previously `artifacts/`); the CLI `--artifacts` option and
`run_pipeline`/`ParserService` `output_root` parameter still accept an
explicit override, so `show`/`validate` continue to work against any existing
`artifacts/<stem>/<run-id>/` directory supplied explicitly.

## 8. What is explicitly NOT done in this pass

Chunking implementation, embeddings, vector storage, retrieval, reranking, an
HTTP API server, and a chatbot — all remain out of scope, per the master
prompt.
