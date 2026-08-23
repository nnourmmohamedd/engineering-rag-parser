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
2. **A single Docling isolation layer.** All Docling construction lives in
   `pipeline_factory.py`; all Docling *result* handling lives in `parser.py`.
   Everything else speaks the project's own domain types.
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
        preflight.inspect_source()                pipeline_factory.build_converter()
        pypdf · pdfminer.six · pypdfium2                     │
                    │                             parser.convert_pdf()
            SourceManifest ──────────┐                       │
            • per-page chars/words   │              ConversionOutcome
            • raster image bboxes    │              • status / partial / errors
            • repeated-image sigs    │              • confidence · timings
            • furniture candidates   │                       │
            • visual-review pages    │              DoclingDocument
                    │                │                       │
                    │                │        ┌──────────────┼───────────────┐
                    │                │        │              │               │
                    │                │  save_document_   exporters.       parser.
                    │                │     json()        classify_       build_
                    │                │        │          pictures()     inventory()
                    │                │  docling/          export_            │
                    │                │  document.json     assets()     DocumentInventory
                    │                │                    export_            │
                    │                │                    markdown()        │
                    │                │                        │             │
                    │                └────────────┬───────────┘             │
                    │                             │                          │
                    └──────────────► validation/ ◄┴──────────────────────────┘
                                     coverage · structure · markdown · visual
                                                  │
                                          ValidationReport
                                     PASS / PASS_WITH_WARNINGS / FAIL
                                                  │
                                    artifacts.RunDirectory (immutable)
                                          + run_manifest.json
```

`pipeline.run_pipeline()` is the only place that orders these steps. It owns
sequencing and artifact placement and contains no parsing logic — which is what
makes a future FastAPI/worker adapter a thin wrapper rather than a rewrite.

## Module responsibilities

| Module | Owns | Deliberately does **not** |
|---|---|---|
| `config.py` | Public YAML contract, profiles, thresholds, config hashing | Import Docling. Public keys stay stable across Docling upgrades |
| `domain.py` | Shared vocabulary: manifests, inventories, findings, report | Import Docling — a manifest written today must load after an upgrade |
| `normalization.py` | Pure text primitives: folding, tokenising, span diffing | Touch the filesystem or any library — fully unit-testable |
| `preflight.py` | Independent source manifest, page rendering | Use Docling for any measurement |
| `pipeline_factory.py` | **All** Docling option/converter construction | Run a conversion |
| `parser.py` | Conversion, status/partial handling, canonical JSON, inventory | Decide artifact layout |
| `exporters.py` | Picture classification, asset writing, Markdown post-processing | Invent content |
| `artifacts.py` | Immutable run dirs, safe paths, hashing, run manifest, JSONL log | Know what a "page" is |
| `validation/*` | Checks with severity + evidence + threshold + remediation | Mutate artifacts |
| `pipeline.py` | Orchestration only | Parse anything itself |
| `cli.py` | Presentation and exit codes | Contain logic worth testing separately |

A test (`test_package_hygiene.py::test_docling_imports_are_confined`) fails the
build if a Docling import appears outside the modules designed to absorb that
churn.

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
artifacts/<source_stem>/<UTC-timestamp>-<sha8>/
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
* **Docling upgrade** — edit `pipeline_factory.py`. Stored manifests and user
  YAML stay valid because the public config keys are independent.
* **Service deployment** — wrap `run_pipeline()`. See
  [productionization_options.md](productionization_options.md).
