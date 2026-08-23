# Claude Code Master Prompt — Engineering-Grade Docling PDF Parser

You are the principal Python/ML platform engineer responsible for building a production-quality, local-first document parsing module for an Engineering-Grade RAG system. Work autonomously inside the current empty project folder. Do not stop after creating a demo notebook or a single script. Investigate, design, implement, run, test, inspect the real outputs, fix defects, and leave a reproducible repository that another engineer can clone and operate.

## Mission

Build a reliable PDF ingestion and parsing package centered on Docling. It must take a complex engineering PDF, preserve its structure and source provenance, produce a valid DoclingDocument JSON file, and export a clean, useful Markdown document with referenced image assets. It must also generate objective validation evidence showing what was captured, what may have been missed, and which pages/items require human review.

This parser is the upstream foundation of a later RAG pipeline involving structure-aware chunking, embeddings, vector search, and cross-encoder reranking. Do not implement the vector database, chatbot, or reranker now. Design the parser outputs and metadata so those later stages can consume them without reparsing the PDF.

The supplied test document is named:

`Instrumentation-and-Control-Engineering.pdf`

Locate it in the current folder or its immediate subdirectories. Copy it, without changing its bytes, to `data/input/Instrumentation-and-Control-Engineering.pdf` if necessary. Never commit this PDF or generated document content to Git.

## Non-negotiable engineering principle

Do not claim “100% accuracy” merely because conversion succeeds or the Markdown looks readable. No general-purpose PDF parser or OCR system can guarantee perfect recovery of every visual and semantic relationship. The required outcome is instead:

- high-fidelity, deterministic, auditable extraction;
- preservation of original evidence, page numbers, bounding boxes/provenance, tables, pictures, and reading order wherever Docling supplies them;
- independent page-level coverage checks;
- explicit `PASS`, `PASS_WITH_WARNINGS`, or `FAIL` status;
- no silent loss: uncertain or unsupported content must be retained as an asset and flagged for review;
- honest documentation of residual limitations.

If any critical requirement cannot be completed, continue with all safe work that can be completed, record the exact blocker and evidence, and do not fabricate success.

## Known characteristics of the acceptance PDF

Use these as validation clues, not as hardcoded extraction results:

- 27 A4 pages, digitally generated and text-searchable rather than a scanned-only PDF.
- A table of contents, six numbered main sections, a conclusion, dense paragraphs, nested numbered/bulleted lists, many engineering acronyms, and repeated headers/footers.
- Repeated visual furniture includes a branded top banner/logo, watermark, website text, and `Page N of 27` footers. Detect/classify these so they do not pollute the canonical body Markdown, while retaining their existence in the audit data.
- Important visual content includes conceptual/FEED/detailed-design process flows, procurement and commissioning flows, a P&ID-style process/control graphic, control-system architecture, an instrumentation layout, a pressure hook-up drawing, a loop wiring diagram, a QA/interdisciplinary workflow, and tables.
- The document visibly contains tables labelled Table 1, Table 2, and Table 3. Verify their titles, locations, cell recovery, and reading order from the actual PDF. Do not assume the numbering is in physical page order.
- Some pages are image-heavy. A native text extraction baseline may contain little text on those pages even though important information is visible. Such pages must not be marked complete based only on text counts.

## Working rules

1. Begin with read-only environment and document inspection. Record Python, OS, CPU/GPU availability, available package managers, PDF metadata, page count, text density per page, and image count/coverage per page.
2. Read the current official Docling documentation and inspect the actual installed Docling API. Do not copy obsolete snippets. Record the installed versions and pin/lock them.
3. Use only free/open-source local dependencies. No paid API and no cloud upload. The default path must work offline after packages/model artifacts have been downloaded.
4. Because this is intended for corporate engineering use, prefer permissive dependencies. Create `THIRD_PARTY_LICENSES.md` with package, version, license, purpose, and source URL. Do not add an AGPL dependency to the default runtime path unless explicitly approved. Verify licenses rather than guessing.
5. Treat the PDF as potentially confidential and untrusted: do not upload it, execute embedded content, follow external links, or log its full text. Add sane file-size/page/time/resource limits and safe output-path handling.
6. Use Git with small, logical commits if Git is available, but do not push or deploy anything.
7. Maintain `TASKS.md`: planned work, current status, decisions, validation findings, and remaining risks. Update it throughout the job.

## Environment and developer experience

Create a local `.venv` and a reproducible Python project. Prefer `uv` if installed; otherwise use `python -m venv` and pip. Choose a stable Python version compatible with the current Docling release and its ML dependencies; Python 3.12 is a conservative default unless environment evidence supports a better choice. Add:

- `pyproject.toml` with package metadata, runtime/dev dependency groups, console script, tool configuration, and explicit supported Python range;
- a lockfile when supported by the chosen package manager;
- `.python-version` if useful;
- `.gitignore` covering `.venv`, model caches, `data/input`, generated artifacts, notebook checkpoints, logs, and secrets;
- `.env.example` containing configuration names only, never secrets;
- a VS Code workspace/settings recommendation selecting `${workspaceFolder}/.venv` and the local Jupyter kernel;
- `notebooks/01_docling_exploration.ipynb`, registered to the project kernel.

The notebook is an educational and diagnostic client of the package. It must not contain the production parsing implementation. It should demonstrate preflight inspection, the chosen Docling options, representative document elements, JSON/Markdown export, page-level metrics, and how to interpret the validation report.

Document exact setup commands for Windows PowerShell and Linux/macOS shells, with VS Code kernel-selection steps.

## Repository architecture

Use a clean `src` layout. Adapt names if justified, but keep responsibilities separated. A suitable target is:

```text
engineering-rag-parser/
├── pyproject.toml
├── README.md
├── TASKS.md
├── THIRD_PARTY_LICENSES.md
├── .gitignore
├── .env.example
├── configs/
│   ├── default.yaml
│   └── high_fidelity.yaml
├── data/
│   └── input/                       # ignored by Git
├── notebooks/
│   └── 01_docling_exploration.ipynb
├── docs/
│   ├── architecture.md
│   ├── docling_parameter_guide.md
│   ├── validation_methodology.md
│   ├── productionization_options.md
│   ├── limitations.md
│   └── FINAL_IMPLEMENTATION_REPORT.md
├── src/engineering_rag_parser/
│   ├── __init__.py
│   ├── cli.py
│   ├── config.py
│   ├── domain.py
│   ├── preflight.py
│   ├── pipeline_factory.py
│   ├── parser.py
│   ├── exporters.py
│   ├── normalization.py
│   ├── artifacts.py
│   └── validation/
│       ├── coverage.py
│       ├── structure.py
│       ├── markdown.py
│       ├── visual.py
│       └── report.py
└── tests/
    ├── unit/
    ├── integration/
    └── fixtures/                    # small synthetic/non-confidential fixtures
```

Production code must use type hints, docstrings where they add value, structured logging, pathlib, explicit exceptions, dependency injection/configuration, and no hidden global state. Use Pydantic/dataclasses for validated configuration and reports where appropriate.

## Preflight source inventory

Before Docling conversion, build an independent source manifest using permissively licensed PDF/text/image inspection libraries. Do not use Docling itself for all baseline measurements; validation must not merely compare Docling to itself.

Capture at least:

- SHA-256, byte size, MIME/type validation, filename, PDF version, encryption status, metadata, page count, and page dimensions/rotation;
- per-page native character/word/line counts and normalized text hashes;
- per-page image count, dimensions, bounding boxes or coverage when available;
- links, annotations, outlines/bookmarks, fonts, and embedded attachments when available;
- detection candidates for repeated headers, footers, logos, watermarks, and page numbers;
- sparse-text/image-heavy/empty-page flags;
- source tool and version details.

Save this as `source/manifest.json` inside the run artifact directory. Ensure any source text samples in logs/reports are short and redacted/configurable.

## Docling conversion strategy

Use `DocumentConverter`, PDF format options, and the standard PDF pipeline unless evidence justifies a different current Docling pipeline. Keep all Docling-specific construction inside `pipeline_factory.py` so API changes are isolated.

Implement configurable profiles, including at least:

- `default`: good CPU-safe behavior for ordinary digital PDFs;
- `high_fidelity`: accurate table structure and referenced pictures/page evidence, with higher resource usage;
- `scanned`: OCR-oriented profile for image-only documents;
- `auto`: runs preflight and chooses/adjusts a profile page-wise or document-wise with an auditable reason.

For this test PDF, native text should be primary. Do not force full-page OCR by default because it may duplicate or degrade clean embedded text. Apply OCR only where the installed Docling API supports it and preflight evidence shows it is needed. If page-wise OCR fallback is not safely supported, state that limitation and use a separate controlled fallback pass rather than merging duplicate text blindly.

Support and explain, using the exact names/types from the installed version, the relevant option families:

- allowed input formats and PDF backend/pipeline choice;
- `do_ocr`, OCR engine, language(s), full-page/bitmap behavior, thresholds, and auto mode;
- `do_table_structure` and table matching/cell mode such as fast versus accurate, if present;
- generation/retention of page images and picture images;
- image scale/resolution and its speed/memory/quality effect;
- code, formula, picture classification, and picture-description enrichments when available;
- local VLM picture-description options, prompts, confidence/area thresholds, and resource cost;
- accelerator/device selection, threads/batch sizes, CPU/GPU fallback, model artifact path, and offline mode;
- page range, maximum pages/file size, timeout/error behavior, and partial-conversion status;
- confidence scores and provenance fields exposed by the installed version.

Do not enable a large local VLM unconditionally. Provide it behind an optional feature flag/profile, detect hardware first, and document model download size, memory requirements, model license, expected latency, and limitations. The default must preserve every significant picture as a referenced asset with page/provenance information even when no VLM description is generated. Never invent the meaning of engineering symbols or diagrams.

Create `docs/docling_parameter_guide.md` as a practical table containing: public config key, actual Docling field/class, default, selected value, effect, quality/speed/memory trade-off, when to change it, and whether it was used for this PDF. Generate applicable portions from introspection/config schemas where possible so the guide does not drift.

Capture the full conversion result status, warnings, errors, timings, and Docling/Docling-core/model versions. Fail clearly if no document is returned. Preserve partial results only in a quarantined artifact path with `FAIL` status.

## Canonical artifacts

Each run must create an immutable directory such as `artifacts/<source_stem>/<timestamp>-<short_sha>/` containing:

```text
run_manifest.json
source/manifest.json
docling/document.json
markdown/document.md
assets/pictures/...
assets/pages/...                  # optional/audit profile
validation/report.json
validation/report.md
validation/pages.csv
validation/review/...
logs/run.jsonl
```

The run manifest must include source hash, configuration hash and effective configuration, UTC timestamp, environment/platform, package/model versions, chosen profile and reason, timings, artifact hashes, and final status. Avoid machine-specific absolute paths in portable outputs.

Export the DoclingDocument with Docling’s supported serializer, not a custom lossy reconstruction. Validate that the JSON can be parsed and reloaded into the current DoclingDocument model/API. If supported, perform a serialization round-trip comparison and report material differences.

## Professional Markdown export

Use Docling’s Markdown serializer as the source of truth, then apply only deterministic, separately tested post-processing that does not discard semantic content. Preserve the untouched serializer output as an audit artifact if normalization changes it.

The canonical `document.md` must have:

- valid UTF-8 and LF line endings;
- one clear document title and consistent heading hierarchy;
- paragraphs and nested lists in correct reading order;
- tables serialized as Markdown when they are rectangular and faithful; for complex/merged-cell tables, use a safe HTML table or preserve the table asset plus a structured warning rather than flattening or guessing;
- referenced image files using portable relative paths, with original captions when available;
- useful source-page anchors, such as unobtrusive HTML comments or stable block metadata, so future RAG citations can map to page/provenance without exposing noisy metadata in user-facing prose;
- removal of repeated header/footer/page-number furniture from body text only when supported by repeated-position/text evidence;
- preservation of technical acronyms, symbols, numbers, units, punctuation, list numbering, captions, and section numbering;
- no base64-embedded images in the canonical Markdown;
- no broken image links, absolute local paths, duplicated blocks, unresolved placeholders, or accidental notebook/debug output.

Do not replace diagrams with hallucinated prose. If an optional local VLM produces a description, label it as machine-generated annotation and retain the original picture/caption and provenance.

## Validation framework

Validation is a first-class product feature, not an afterthought. Compare the source inventory, DoclingDocument, exported JSON, Markdown, and rendered/source pages.

Implement at least these checks:

### File and page integrity

- source SHA-256 is stable and source file is never modified;
- expected page count equals parsed page/provenance coverage;
- page numbering is monotonic and no page is duplicated or silently omitted;
- conversion status/errors are captured;
- all output files are readable and hashes are recorded.

### Text coverage

- compare normalized native PDF text with Docling text page-by-page using multiple robust metrics, not one global character ratio;
- report source/parsed character and token/word counts, missing high-information spans, duplicated spans, and similarity/coverage scores;
- normalize whitespace, soft hyphens, ligatures, and line wrapping carefully, but preserve numbers, units, punctuation, and acronyms for critical-token checks;
- allow expected differences caused by header/footer removal and reading-order repair;
- define thresholds in config and explain them. Low-scoring pages must be flagged, never silently averaged away.

### Structure coverage

- inventory headings by level, paragraphs, ordered/unordered list items, tables, table cells, pictures, captions, formulas, code blocks, and provenance references;
- verify the TOC and numbered sections against headings without hardcoding the final extracted wording;
- detect heading-level jumps, orphan captions, empty tables, suspicious one-cell tables, and reading-order anomalies;
- specifically locate and audit Tables 1, 2, and 3 and report title, page, dimensions, empty-cell ratio, and serialization approach;
- distinguish repeated decorative assets from substantive diagrams.

### Visual and image coverage

- identify every image-heavy or sparse-text page from preflight;
- verify that important picture regions are represented in Docling or preserved as page/picture assets;
- create a review artifact per flagged page: source-page rendering plus parsed bounding-box overlay or a compact side-by-side/HTML equivalent, using only local tools;
- inspect every page of this 27-page acceptance document, not just the first page;
- machine-generated picture descriptions are supplemental and must not count as proof that all diagram labels/relationships were recovered.

### Markdown and JSON QA

- JSON schema/model validation and reload/round-trip test;
- Markdown parser/linter check where practical;
- image/link existence and portability;
- table row/column consistency;
- heading hierarchy, duplicate repeated furniture, mojibake/control characters, accidental binary/base64 content, and placeholder checks;
- compare semantic inventory before and after Markdown serialization to detect exporter loss;
- rerun determinism test with normalized timestamps/paths excluded from comparison.

Produce per-check severity, evidence, thresholds, and remediation. A single aggregate percentage is not sufficient.

## Acceptance gates for this PDF

The final run may be marked `PASS` only when all critical gates pass, including:

1. Source is recognized as the unchanged 27-page PDF.
2. Docling conversion returns a successful result with a non-empty DoclingDocument.
3. `docling/document.json` validates and reloads successfully.
4. `markdown/document.md` is non-empty, readable, portable, and has no broken referenced assets.
5. Every source page has provenance coverage or an explicit, justified review warning.
6. All sparse/image-heavy pages receive visual coverage review.
7. Repeated furniture does not pollute the canonical body, with evidence recorded for what was removed.
8. Tables 1, 2, and 3 are located and their extraction/serialization quality is individually reported.
9. No critical numeric/acronym sentinel loss is found in sampled high-information pages.
10. No critical missing/duplicate span, page, table, or substantive picture remains unexplained.
11. Unit, integration, and full-document acceptance tests pass.
12. The final report lists actual metrics and human-review items, not generic claims.

If a critical gate fails, status is `FAIL`. If critical gates pass but noncritical uncertainty remains, use `PASS_WITH_WARNINGS`. The CLI must return a non-zero exit code on `FAIL` and support a strict mode where warnings also fail CI.

## CLI

Provide a clear console command, for example `engrag-parse`, with subcommands similar to:

```bash
engrag-parse inspect  --input data/input/Instrumentation-and-Control-Engineering.pdf
engrag-parse parse    --input ... --config configs/high_fidelity.yaml
engrag-parse validate --run artifacts/... --strict
engrag-parse export   --run artifacts/... --format json --format markdown
engrag-parse run      --input ... --config configs/high_fidelity.yaml
```

Exact names may differ, but the end-to-end command must be simple, support `--help`, validate arguments, avoid overwriting prior runs, print the final artifact path and status, and expose machine-readable output for automation.

## Tests and quality controls

Use current stable tools such as pytest, Ruff, and a practical type checker, pinned through the project configuration. Add:

- unit tests for configuration, hashing, safe paths, normalization, furniture detection, metrics, report status, JSON/Markdown validation, and artifact manifests;
- small synthetic fixture PDFs covering headings, nested lists, tables, images/captions, repeated headers/footers, rotated pages, and an image-only page;
- integration tests for Docling conversion and export;
- a slow full-document acceptance test for the supplied PDF, skipped automatically only when the file/model artifacts are absent and with an explicit reason;
- tests ensuring the production package does not depend on notebook state;
- lint, format, and type-check commands;
- optional GitHub Actions CI using only synthetic fixtures. Never upload or commit the supplied proprietary/test PDF or its extracted content to CI.

Run all applicable checks yourself. Do not merely write tests. Record commands and results in the final report. Fix failures unless the failure is an honest documented environment limitation.

## Productionization research and selected approach

Create `docs/productionization_options.md` comparing at least:

1. notebook/script prototype;
2. installable Python package plus CLI/batch runner;
3. internal API service with worker queue;
4. event-driven ingestion service using object storage/queue/workers.

Compare reproducibility, maintainability, throughput, isolation, retries/idempotency, observability, scaling, deployment complexity, security, cost, and fit for an engineering-document RAG system.

Choose the installable package + CLI/batch runner for this milestone, with clean service boundaries that allow a future FastAPI/worker adapter. Explain why. Do not add infrastructure the task does not yet need, but optionally provide a minimal, multi-stage Dockerfile only if it is maintainable, non-root, cached correctly, and not used as a substitute for local setup.

Describe the future ingestion contract for chunking without implementing chunking: stable document ID/source hash, block ID, block type, heading path, page number, bounding box/provenance, text, table representation, asset reference, parser/config version, and validation status. Make clear that future structure-aware chunking should consume the DoclingDocument directly where possible rather than flattening everything to Markdown first.

## Documentation required

`README.md` must lead with the outcome and contain:

- what the system does and does not do;
- architecture overview;
- prerequisites;
- exact setup for `.venv`, VS Code, and Jupyter;
- model artifact/download/offline notes;
- exact end-to-end command for the supplied PDF;
- output tree and meaning of each artifact;
- config profiles and common tuning choices;
- validation status interpretation;
- test/lint/type-check commands;
- troubleshooting for first-run model downloads, memory, CPU/GPU, OCR, and Windows paths;
- data privacy and licensing notes.

`docs/FINAL_IMPLEMENTATION_REPORT.md` must state:

- actual environment and installed versions;
- exact effective Docling parameters and why they were chosen;
- measured runtime and resource observations;
- actual source and parsed inventories;
- actual page-level and structural validation results;
- explicit findings for all 27 pages, with concise grouping allowed for clean pages;
- table and substantive-picture findings;
- every warning/known limitation and recommended human review;
- exact reproduction commands;
- readiness assessment for the next chunking/vector-search stage.

## Execution order

Proceed autonomously in this order:

1. Inspect environment and PDF; write initial `TASKS.md` and architecture decision.
2. Initialize Git/project/venv and install pinned dependencies.
3. Implement source preflight and configuration.
4. Implement Docling pipeline, conversion result handling, and canonical serialization.
5. Implement deterministic Markdown/assets export.
6. Implement validation and visual audit artifacts.
7. Add notebook as a thin educational client.
8. Add tests, quality tooling, documentation, license inventory, and CI-safe fixtures.
9. Run the full pipeline on the supplied PDF.
10. Inspect every page and the final JSON/Markdown/assets/reports; fix defects and rerun.
11. Run tests/lint/type checks and determinism checks.
12. Complete the final implementation report and leave a concise terminal summary with the exact artifact paths, status, metrics, warnings, and next command.

## Definition of done

Do not stop at scaffolding. The work is done only when the repository is runnable from a fresh environment, the supplied PDF has actually been processed, the DoclingDocument JSON and professional referenced-asset Markdown exist, validation evidence has actually been generated and inspected, tests have actually been run, and the final report honestly distinguishes verified completeness from unresolved uncertainty.

When choosing between a visually prettier output and a more auditable lossless output, preserve information and provenance first. Human-readable polish is second, and all normalization must remain reproducible and testable.
