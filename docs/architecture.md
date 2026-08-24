# Architecture

## The problem this shape solves

A PDF parser is easy to build and hard to trust. The failure mode that matters
is not a crash — it is a run that exits `0`, produces readable Markdown, and has
quietly dropped a table, a diagram, or every instrument tag on one page. Nothing
downstream can detect that, because by then the PDF is gone and only the
Markdown remains.

So the architecture is organised around one question: **how would we know?**
That produces three structural commitments:

1. **An independent baseline.** Preflight measures the source with a completely
   separate library stack. If Docling were also the baseline, every coverage
   metric would be Docling agreeing with itself.
2. **A single Docling isolation layer.** All Docling construction and result
   handling lives in `services/parser/converter.py` (plus the sibling
   `exporters.py`, `inventory.py` and `validation/{structure,visual}.py`, each
   for their own narrow slice). Everything else speaks the project's own
   domain types.
3. **Validation as a product feature.** Checks carry severity, evidence,
   threshold and remediation, and the run has a terminal status with a non-zero
   exit code on failure.

## Data flow

```text
                      Instrumentation-and-Control-Engineering.pdf
                                        │
                    ┌───────────────────┴────────────────────┐
                    │                                        │
       (independent baseline)                        (Docling pipeline)
                    │                                        │
     preflight.inspect_source()                  profiles.choose_profile()
     pypdf · pdfminer.six · pypdfium2             converter.build_converter()
                    │                                        │
            SourceManifest ──────────┐              converter.convert_pdf()
            • per-page chars/words   │                       │
            • raster image bboxes    │              ConversionOutcome
            • repeated-image sigs    │              • status / partial / errors
            • furniture candidates   │              • confidence · timings
            • visual-review pages    │                       │
                    │                │              DoclingDocument
                    │                │                       │
                    │                │        ┌──────────────┼───────────────┐
                    │                │        │              │               │
                    │                │ converter.        exporters.     inventory.
                    │                │ save_document_    classify_      build_
                    │                │    json()         pictures()    inventory()
                    │                │        │          export_            │
                    │                │  docling/         assets()     DocumentInventory
                    │                │  document.json    export_            │
                    │                │                   markdown()         │
                    │                │                        │             │
                    │                └────────────┬───────────┘             │
                    │                             │                          │
                    └──────────────► validation/ ◄┴──────────────────────────┘
                                     source · structure · markdown · visual
                                                  │
                                          ValidationReport
                                     PASS / PASS_WITH_WARNINGS / FAIL
                                                  │
                                    artifacts.RunDirectory (immutable)
                                          + run_manifest.json
```

`services/parser/service.py::ParserService.run()` is the only place that
orders these steps — this is parser-domain behaviour, so it lives inside the
service, not the orchestration layer. `pipelines/parsing_pipeline.py` is a
thin wrapper the CLI (and any future adapter) calls, so a future FastAPI/worker
adapter reuses that same wrapper rather than duplicating sequencing logic.

## Module responsibilities

| Module | Owns | Deliberately does **not** |
|---|---|---|
| `services/parser/config.py` | Public YAML contract, profiles, thresholds, config hashing | Import Docling. Public keys stay stable across Docling upgrades |
| `services/parser/models.py` | Shared vocabulary: manifests, inventories, findings, report | Import Docling — a manifest written today must load after an upgrade |
| `services/parser/normalization.py` | Pure text primitives: folding, tokenising, span diffing | Touch the filesystem or any library — fully unit-testable |
| `services/parser/preflight.py` | Independent source manifest, page rendering | Use Docling for any measurement |
| `services/parser/profiles.py` | Deciding *which* profile to use, from preflight evidence | Construct any Docling object |
| `services/parser/converter.py` | **All** Docling option/converter construction, conversion, canonical JSON | Decide artifact layout |
| `services/parser/inventory.py` | Structural counting of a converted `DoclingDocument` | Run a conversion |
| `services/parser/exporters.py` | Picture classification, asset writing, Markdown post-processing | Invent content |
| `services/parser/artifacts.py` | Immutable run dirs, run manifest, JSONL log | Know what a "page" is |
| `services/parser/validation/*` | Checks with severity + evidence + threshold + remediation | Mutate artifacts |
| `services/parser/service.py` | `ParserService` — orders the steps above for one PDF | Parse anything itself |
| `pipelines/parsing_pipeline.py` | Thin orchestration wrapper | Contain parser-domain logic |
| `api/cli.py` | Presentation, logging configuration, exit codes | Contain logic worth testing separately |
| `utils/paths.py`, `utils/hashing.py`, `utils/logging.py` | Generic, service-agnostic helpers | Import from any service |

A test (`tests/unit/test_architecture.py::TestPackageIsSelfContained::test_docling_imports_are_confined`)
fails the build if a Docling import appears outside the modules designed to
absorb that churn, and `TestServiceArchitectureBoundaries` enforces the
`api -> pipelines -> services -> utils` dependency direction. See
[`docs/architecture/service_architecture.md`](architecture/service_architecture.md)
for the full service-oriented picture, including the future `clients`,
`databases`, `prompts` and `services/chunker` boundaries.

## Three decisions worth explaining

### Why the baseline uses three libraries instead of one

Each answers a question the others cannot:

* `pypdf` — document structure: encryption, `/Title`, outline, fonts, annotations.
* `pdfminer.six` — text **with line geometry**. The geometry is essential:
  furniture detection requires that a line both repeats *and* sits in a
  header/footer band. Without position, any twice-occurring sentence looks like
  furniture.
* `pypdfium2` — raster image objects with bounding boxes, and page rendering.

The convenient single-library answer is PyMuPDF, which is AGPL and therefore
excluded (ADR-003).

### Why picture classification is cross-referenced, not thresholded

Docling's layout model reports **114 pictures** on the acceptance document.
Only 15 are real figures; the rest are fragments of the page banner it detects
separately on every page. An area threshold sorts most of these correctly and
silently discards the small ones — which on this document would have dropped
four genuine diagrams.

Instead, preflight already knows every raster image's exact bbox and which
`(bbox, pixel-size)` signatures repeat document-wide. A Docling picture region
is classified by **overlap with those known regions**. Area is only a fallback
for regions matching no source image at all, and it can only promote a region to
*substantive*, never demote one.

### Why page-local and document-level text checks are separate

Docling attributes a paragraph that crosses a page break to the page where it
**starts**. That is correct reading-order repair. A naive per-page comparison
reports it as loss on the following page.

So there are two checks with different severities:

* `critical_token_recall` (page-local, **WARNING**) — consults adjacent pages and
  reports tokens as *relocated* rather than *missing*.
* `document_text_completeness` (**CRITICAL gate**) — ignores page boundaries
  entirely and asks whether any high-information token is absent from the whole
  document.

Relocation is a provenance nuance; absence is a defect. Only the second can fail
a run.

## Artifact layout

```text
data/output/parser/<source_stem>/<UTC-timestamp>-<sha8>/
├── run_manifest.json                 source hash · config hash · profile + reason
│                                     · versions · timings · SHA-256 of every artifact
├── source/manifest.json              independent preflight inventory
├── docling/
│   ├── document.json                 canonical DoclingDocument (REFERENCED images)
│   └── assets/                       images referenced by relative URI
├── markdown/
│   ├── document.md                   canonical deliverable
│   ├── document.raw.md               untouched serializer output (audit)
│   └── document.with-furniture.md    body + furniture layers (shows what was excluded)
├── assets/pictures/*.png             substantive figures + unrecovered table regions
├── assets/pages/*.png                full page renders
├── validation/
│   ├── report.json  report.md  pages.csv
│   └── review/pageNNN.html           source render + bbox overlay
└── logs/run.jsonl
```

Runs are immutable: the directory is created with `exist_ok=False`, so a second
run never overwrites the first. Every write passes through
`RunDirectory.path_for()`, which resolves the candidate and refuses anything
landing outside the run root — the source PDF is untrusted, and a caption
derived from it must never steer a write into `~/.ssh`.

## Extension points

* **New output format** — add an exporter; nothing else changes.
* **New validation check** — return a `CheckResult`; the report aggregates and
  the status logic gates it automatically.
* **Docling upgrade** — edit `services/parser/converter.py`. Stored manifests
  and user YAML stay valid because the public config keys are independent.
* **Service deployment** — wrap `pipelines.parsing_pipeline.run_parsing_pipeline()`.
  See [productionization_options.md](productionization_options.md).
* **New capability (chunking, embedding, ...)** — add a sibling under
  `services/`, orchestrated by its own `pipelines/*_pipeline.py`. See
  [architecture/service_architecture.md](architecture/service_architecture.md#how-to-add-a-new-service).
