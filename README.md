# Engineering-Grade Docling PDF Parser

A local-first, auditable PDF ingestion package for engineering documents. It converts a PDF into a
validated `DoclingDocument` JSON, a clean referenced-asset Markdown document, and — the part that
matters most — **objective evidence about what was captured, what was not, and which pages a human
still has to look at.**

> **It does not claim 100% accuracy, and neither should you.** No general-purpose PDF parser or OCR
> engine can guarantee recovery of every visual and semantic relationship. What this package
> guarantees is that losses are *detected, reported and preserved as evidence* rather than passed
> off as success.

---

## Outcome on the supplied acceptance document

`Instrumentation-and-Control-Engineering.pdf` — 27 pages, 5,378,401 bytes,
SHA-256 `01e4d6fa…3b1a`.

| Result | Detail |
|---|---|
| **Status** | `PASS_WITH_WARNINGS` — **19/19 acceptance gates passed**, 4 warnings |
| Pages parsed | **27 / 27**, all with provenance |
| Text completeness | **100%** document-level critical-token recall and word-type recall vs an independent baseline; 32,637 → 32,506 chars (99.6%) after like-for-like furniture stripping |
| Figures | **15** substantive diagrams preserved as PNG assets; 54 decorative banner/watermark instances excluded from the body |
| **Tables 1, 2, 3** | **Located on pages 16, 25→26 and 23. All three bodies are raster images with no text layer — Docling recovered 0 cells. Contents are NOT machine-readable and are flagged for human transcription.** |
| Visual review | **17** side-by-side review cards under `validation/review/` |
| Determinism | Re-runs are **byte-identical** for every deliverable (timestamps excluded) |
| Tests | **271 passing** (229 fast + 42 slow, including the OCR/scanned path) |

Full measured results: [`docs/FINAL_IMPLEMENTATION_REPORT.md`](docs/FINAL_IMPLEMENTATION_REPORT.md).
OCR verification evidence, thresholds and metrics: [`PARSER_STAGE_FINAL_REPORT.md`](PARSER_STAGE_FINAL_REPORT.md).

The single most important finding is the table one, and it is the reason this package exists in this
shape: a parser that silently emitted the captions and dropped the table bodies would have looked
perfect.

---

## Outcome on the controlled OCR/scanned benchmark

The `scanned` profile has been run end to end against a genuine image-only PDF (proven independently:
zero extractable text, one raster image per page), not just unit-tested for option construction.

| Result | Detail |
|---|---|
| **Status** | `PASS` — both the explicit `scanned` profile and the `auto` profile (which correctly routes an image-only document to `scanned`) |
| OCR engine | **RapidOCR** (`rapidocr-onnxruntime`, Apache-2.0) — ships its ONNX models inside the pip wheel, so a scanned run needs no runtime network access |
| Critical-token recall | **100%** (31/31 hand-selected identity tokens: title, reference number, table values, status labels, form fields, code identifiers) |
| Word-type recall | 96.9% (normalized against an independent pdfminer.six/pypdf ground truth) |
| Page handling | Both pages represented in order; the nearly-blank second page preserved, not dropped |
| JSON / Markdown | Reloads into `DoclingDocument`; Markdown non-empty and portable |

Full methodology, ground-truth manifest, thresholds and the one disclosed OCR limitation (a glyph
misread resolved by raising render DPI) are in [`PARSER_STAGE_FINAL_REPORT.md`](PARSER_STAGE_FINAL_REPORT.md).
This benchmark proves the *software path* works; it is not a claim about OCR accuracy on arbitrary
real-world scans.

---

## What it does / does not do

**Does**

- Independent preflight inventory of the source (metadata, per-page text, images, fonts, outline,
  repeated furniture) built *without* Docling, so validation is not Docling checking itself.
- Docling conversion through a single isolated factory, with four profiles (`default`,
  `high_fidelity`, `scanned`, `auto`).
- Canonical `DoclingDocument` JSON via Docling's own serializer, with a reload + round-trip check.
- Deterministic Markdown with referenced image assets, page anchors for future RAG citation, and
  explicit markers where content could not be recovered.
- A validation framework producing per-check severity, evidence, thresholds and remediation, plus a
  `PASS` / `PASS_WITH_WARNINGS` / `FAIL` verdict and a non-zero exit code on failure.
- Per-page visual review cards (source render + parsed bounding-box overlay) for every page that
  text metrics cannot judge.

**Does not**

- No conversation memory, chatbot UI, or deployment/authentication surface. The answering backend
  (below) is a single-turn, question-in/answer-out API, not an agent.
- No cloud calls, no uploads, no telemetry. `enable_remote_services` is pinned to `False` by a
  validator that refuses to be overridden. LLM generation runs entirely through a **local** Ollama
  server — no cloud inference, no Ollama account, no paid API.
- No AI-generated descriptions of engineering diagrams by default. See
  [ADR-005](TASKS.md#adr-005--no-vlm-picture-description-in-the-default-path).
- No modification of the input file, ever (asserted by a gate).

## Beyond parsing: chunking, retrieval, and grounded answering

This repository has grown past the parser-only milestone described in most of this README. The
full pipeline today is:

```text
parse (this README)  ->  chunk  ->  embed + index (Chroma)  ->  retrieve (vector/BM25/hybrid/rerank)  ->  answer (local Ollama, grounded, cited)
```

| Stage | CLI | Docs |
|---|---|---|
| Structure-aware chunking | `engrag-chunk` | [`docs/chunker/`](docs/chunker/) |
| Embedding + ChromaDB indexing | `engrag-index` | [`docs/indexing/`](docs/indexing/) |
| Vector / hybrid (BM25 + RRF) / cross-encoder-reranked retrieval | `engrag-retrieve` | [`docs/retrieval/`](docs/retrieval/) |
| Grounded LLM answer generation (local `qwen3:8b` via Ollama, cited, refuses when evidence is insufficient) | `engrag-ask` | [`docs/answering/`](docs/answering/) |

The answering backend never reparses the PDF or duplicates retrieval logic — it calls the existing
`engrag-retrieve` pipeline, builds a token-budgeted, citable context, and validates every citation
deterministically before returning an answer. See
[`docs/answering/GROUNDED_ANSWERING_ARCHITECTURE.md`](docs/answering/GROUNDED_ANSWERING_ARCHITECTURE.md)
for the full flow and [`docs/answering/SECURITY_AND_GROUNDING.md`](docs/answering/SECURITY_AND_GROUNDING.md)
for the threat model (retrieved document text is treated as untrusted data, never as instructions).

---

## Architecture

The package is organised as services (`engineering_rag.services.*`), each with an isolated,
production-complete implementation, orchestrated by a thin pipeline layer and exposed through a
CLI — see [`docs/architecture/service_architecture.md`](docs/architecture/service_architecture.md)
for the full picture, including the future chunker/client/database/prompt boundaries.

```text
inspect_source()        services/parser/preflight.py    independent baseline (pypdf / pdfminer.six / pypdfium2)
        │
        ▼
choose_profile()        services/parser/profiles.py     evidence-based profile + audited reason
        │
        ▼
convert_pdf()           services/parser/converter.py    Docling conversion, status/partial handling
        │
        ├── save_document_json()                        canonical JSON (Docling serializer, REFERENCED images)
        │
        ├── export_assets() ──────────────► assets/pictures/*.png, assets/pages/*.png
        │   export_markdown()  services/parser/exporters.py  markdown/document.md
        │
        ▼
services/parser/validation/   source · structure · markdown · visual · report
        │
        ▼
RunDirectory            services/parser/artifacts.py    immutable run dir + run_manifest.json
```

`services/parser/service.py::ParserService` orders these steps; `pipelines/parsing_pipeline.py`
is the thin entry point the CLI (`api/cli.py`) and any future adapter call. All Docling imports
live in `services/parser/{converter,inventory,exporters}.py` and `services/parser/validation/
{structure,visual}.py`. `services/parser/config.py` exposes a stable public key set so a Docling
upgrade never invalidates a stored manifest or a user's YAML.

---

## Prerequisites

- Python 3.10–3.13 (developed and verified on **3.13.9**)
- ~4 GB disk for Docling's layout + TableFormer model weights (downloaded once, on first run)
- No GPU required. CPU-only is the shipped default.

---

## Setup

### Windows (PowerShell)

```powershell
git clone <repo> engineering-rag-parser
cd engineering-rag-parser

py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip

# CPU-only PyTorch first, so pip does not resolve a CUDA build you do not want.
python -m pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision

python -m pip install -e ".[dev]"
```

If activation is blocked: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`.

### Linux / macOS

```bash
git clone <repo> engineering-rag-parser
cd engineering-rag-parser

python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip

python -m pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision
python -m pip install -e ".[dev]"
```

### Optional extras

```bash
pip install -e ".[ocr]"   # RapidOCR (default engine) — only for genuinely scanned documents
pip install -e ".[ocr-easyocr]"  # EasyOCR alternative (set docling.ocr_engine: easyocr)
pip install -e ".[vlm]"   # local VLM picture description (off by default, see ADR-005)
pip install -e ".[chunking]"  # structure-aware chunking (engrag-chunk)
pip install -e ".[indexing]"  # BGE embeddings + ChromaDB (engrag-index, engrag-retrieve)
pip install -e ".[hybrid]"    # BM25 lexical index + RRF fusion (engrag-retrieve --mode hybrid*)
pip install -e ".[answering]" # local Ollama client + Qwen3 tokenizer for token budgeting (engrag-ask)

# Everything at once, matching CI:
pip install -e ".[dev,chunking,indexing,hybrid,answering]"
```

### Reproducible installation (lockfile)

`requirements.lock` captures the exact dependency closure verified in the
reference environment (see the header of the file for the full rationale and
regeneration commands):

```powershell
python -m pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision
python -m pip install -r requirements.lock
python -m pip install -e . --no-deps
```

The flexible-range install above (`pip install -e ".[dev]"`) is also fully
supported and is what CI uses; the lockfile is for byte-for-byte reproduction
of the verified environment when that matters more than picking up patch
releases.

### VS Code + Jupyter

1. **Ctrl+Shift+P → Python: Select Interpreter → `./.venv/Scripts/python.exe`**
   (`.vscode/settings.json` already points at it.)
2. Register the kernel:
   ```bash
   python -m ipykernel install --user --name engineering-rag-parser --display-name "Python (engineering-rag-parser)"
   ```
3. Open `notebooks/01_docling_exploration.ipynb` → **Select Kernel → Jupyter Kernel → Python (engineering-rag-parser)**.

The notebook is a *client* of the package. It contains no parsing logic; a test asserts this.

---

## Model artifacts and offline operation

The first run downloads Docling's layout and TableFormer weights from Hugging Face into the default
HF cache. After that, the default path is fully offline.

To pin models to a project-local directory and run air-gapped:

```bash
docling-tools models download -o ./models/docling
export ENGRAG_ARTIFACTS_PATH=./models/docling   # or set docling.artifacts_path in your YAML
export HF_HUB_OFFLINE=1
```

`.env.example` lists every supported variable. There are no secrets — this project contacts no
service.

---

## Run it

End-to-end on the supplied document:

```bash
engrag-parse run --input data/input/Instrumentation-and-Control-Engineering.pdf \
                 --config configs/high_fidelity.yaml
```

Other subcommands:

```bash
engrag-parse inspect  --input data/input/Instrumentation-and-Control-Engineering.pdf   # preflight only
engrag-parse run      --input ... --config configs/auto.yaml --json                    # machine-readable
engrag-parse validate --run data/output/parser/<stem>/<run-id> --strict                # re-gate in CI
engrag-parse show     --run data/output/parser/<stem>/<run-id>                         # summarise a run
engrag-parse --help
```

Exit codes: `0` pass (or pass-with-warnings), `1` validation FAIL, `2` input rejected by preflight,
`3` unexpected runtime failure.

### Chunking (structure-aware, hierarchical-first)

Chunk a completed parser run into retrieval-ready `chunks.jsonl`:

```bash
engrag-chunk run --input data/output/parser/<document>/<run-id> --profile configs/chunker_production.yaml
```

```bash
engrag-chunk inspect  --input data/output/chunker/<document>/<run-id>/chunks.jsonl   # counts, token stats
engrag-chunk validate --input data/output/chunker/<document>/<run-id> --strict       # re-gate in CI
engrag-chunk --help
```

No embeddings, vector database, retrieval or reranking is implemented by this
milestone — see [`docs/chunker/`](docs/chunker/) for the full architecture,
output schema, configuration reference, validation gates, the HybridChunker
baseline comparison, and the design rationale
(`docs/chunker/MENTOR_EXPLANATION.md`).

---

## Output tree

Each run creates an immutable directory `data/output/parser/<source_stem>/<UTC-timestamp>-<sha8>/`:

| Path | Meaning |
|---|---|
| `run_manifest.json` | Source hash, effective config + config hash, profile and **why**, versions, timings, SHA-256 of every artifact, final status |
| `source/manifest.json` | Independent preflight inventory (no Docling involved) |
| `docling/document.json` | Canonical `DoclingDocument`, Docling serializer, referenced images |
| `markdown/document.md` | **The canonical Markdown deliverable** |
| `markdown/document.raw.md` | Untouched serializer output, kept for audit diffing |
| `markdown/document.with-furniture.md` | Body + furniture layers, to show what was excluded |
| `assets/pictures/*.png` | Substantive figures and unrecovered table regions |
| `assets/pages/*.png` | Full page renders |
| `validation/report.md` | Human-readable validation report |
| `validation/report.json` | Machine-readable checks, evidence, thresholds |
| `validation/pages.csv` | Per-page metrics for spreadsheet review |
| `validation/review/pageNNN.html` | Side-by-side review card with bbox overlay |
| `logs/run.jsonl` | Structured event log, one JSON object per line |

Runs never overwrite each other (`mkdir(exist_ok=False)`), and every artifact write is path-checked
against the run root. `--artifacts` on `run` overrides the output root when needed (including writing
into a pre-existing `artifacts/` directory from before the service-architecture restructure); `validate`
and `show` accept any existing run directory via `--run`, wherever it lives.

---

## Profiles and tuning

| Profile | OCR | Tables | Scale | Use when |
|---|---|---|---|---|
| `default` | off | `fast` | 1.5 | Ordinary digital PDFs, throughput matters |
| `high_fidelity` | off | `accurate` | 2.0 | Table accuracy and readable figure assets matter |
| `scanned` | **on, full page** | `accurate` | 2.0 | Genuinely image-only documents |
| `auto` | decided | decided | decided | Let preflight choose and record the reason |

Common adjustments and their trade-offs are tabulated in
[`docs/docling_parameter_guide.md`](docs/docling_parameter_guide.md), generated from introspection of
the installed Docling so it cannot drift from reality.

> **Do not run `scanned` against a digital PDF.** Full-page OCR over an existing text layer
> duplicates and degrades it. The `no_duplicated_spans` check exists to catch exactly that.

---

## Interpreting the status

| Status | Meaning | Exit |
|---|---|---|
| `PASS` | Every acceptance gate passed, no warnings | 0 |
| `PASS_WITH_WARNINGS` | All gates passed; non-critical uncertainty remains. **Read `validation/report.md` → "Human review required".** | 0 |
| `FAIL` | At least one critical gate failed. Do not use the output. | 1 |

`--strict` escalates warnings to failure, for CI.

A status is a statement about *auditable extraction quality*, not accuracy. `PASS_WITH_WARNINGS`
with a flagged unrecovered table is a more honest and more useful result than a green tick.

---

## Tests, lint, types

```bash
pytest -m "not slow"                 # fast: unit + integration + hygiene + CLI (~30s-1min)
pytest -m slow                       # full acceptance run on the real PDF (~1-5 min)
pytest -m "not slow" --cov=engineering_rag --cov-report=term-missing         # with coverage

ruff check .                         # lint
ruff format --check .                # formatting
mypy src                             # types (17 modules, strict-ish)
python -m build --wheel              # package build
```

Exact results, commands and counts (including coverage) are recorded per run in
[`PARSER_STAGE_FINAL_REPORT.md`](PARSER_STAGE_FINAL_REPORT.md) rather than transcribed here, so this
file cannot drift out of date with the actual numbers.

The slow acceptance test skips itself with an explicit reason when the PDF is absent, so a fresh
clone still has a green suite. [`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs the fast
suite plus lint/type/build checks on every push, using only synthetic ReportLab-generated fixtures —
the supplied PDF and everything extracted from it are git-ignored and never uploaded or referenced by
CI.

---

## Troubleshooting

**First run is slow / appears to hang.** It is downloading model weights (hundreds of MB). Run with
`--log-level DEBUG`. Subsequent runs on this document take ~2–3 minutes on 4 CPU cores.

**`FutureWarning` about `DoclingParseV4DocumentBackend`.** You configured `backend: dlparse_v4`.
That shim is removed upstream; use `backend: docling_parse`.

**Out of memory.** Lower `docling.images_scale` (2.0 → 1.0), set `table_mode: fast`, reduce
`num_threads`. On GPU, note that Docling's models plus a VLM will not fit in 2 GB.

**CUDA errors or silent slowness.** The default is `accelerator_device: cpu` by design. Set
`cuda` only with ≥ 6 GB VRAM; a CUDA OOM mid-conversion yields a *partial* document, which is the
worst failure mode for an auditable parser.

**OCR engine not found.** `pip install -e ".[ocr]"` installs RapidOCR (default `ocr_engine`), whose
detection/classification/recognition ONNX models ship inside the wheel — no runtime download needed.
The EasyOCR alternative (`pip install -e ".[ocr-easyocr]"`, `ocr_engine: easyocr`) fetches ~100 MB of
weights from GitHub Releases on first use; verify that host is reachable before relying on it.

**Windows long paths.** Artifact paths nest several levels. Enable long paths:
`git config --system core.longpaths true` and set
`HKLM\SYSTEM\CurrentControlSet\Control\FileSystem\LongPathsEnabled = 1`.

**`UnicodeEncodeError` when piping output.** The Windows console defaults to a legacy code page.
Use `set PYTHONIOENCODING=utf-8` (or `$env:PYTHONIOENCODING="utf-8"`). Artifacts on disk are always
UTF-8 with LF regardless.

---

## Data privacy and licensing

- **The source PDF never leaves the machine.** No network calls in the default path;
  `enable_remote_services` is rejected by a config validator, not merely defaulted off.
- **Nothing document-derived is committed.** `.gitignore` excludes `data/input/`, `artifacts/`,
  `*.pdf` and `*.jsonl`.
- **Text in reports is redacted.** Samples are truncated to `text_sample_chars` (default 160); full
  page text is held in memory for validation and never written to an artifact.
- **Input is treated as untrusted**: magic-byte check, size/page/time limits, no execution of
  embedded content, no following of links, and every artifact write is path-checked against the run
  root.
- **Dependencies are permissive only** (MIT / BSD / Apache-2.0). **PyMuPDF is deliberately excluded
  as AGPL-3.0.** Full inventory with versions, licenses and source URLs:
  [`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md).
- This project is MIT licensed. Model weights carry their own licenses — see the parameter guide.

---

## Documentation

| Document | Contents |
|---|---|
| [`docs/answering/ANSWERING_COMPLETION_REPORT.md`](docs/answering/ANSWERING_COMPLETION_REPORT.md) | Evidence for the grounded-answering milestone: Ollama/model digest, tests, quality gates, real acceptance queries |
| [`docs/answering/GROUNDED_ANSWERING_ARCHITECTURE.md`](docs/answering/GROUNDED_ANSWERING_ARCHITECTURE.md) · [`COMMANDS.md`](docs/answering/COMMANDS.md) · [`EVALUATION.md`](docs/answering/EVALUATION.md) · [`OLLAMA_SETUP.md`](docs/answering/OLLAMA_SETUP.md) · [`SECURITY_AND_GROUNDING.md`](docs/answering/SECURITY_AND_GROUNDING.md) | Context building, token budgeting, prompts, citation validation, Ollama setup, threat model |
| [`docs/retrieval/HYBRID_RETRIEVAL_COMPLETION_REPORT.md`](docs/retrieval/HYBRID_RETRIEVAL_COMPLETION_REPORT.md) · [`RETRIEVAL_COMPLETION_REPORT.md`](docs/retrieval/RETRIEVAL_COMPLETION_REPORT.md) | Evidence for the vector + hybrid retrieval/reranking milestones |
| [`docs/retrieval/ARCHITECTURE.md`](docs/retrieval/ARCHITECTURE.md) · [`HYBRID_RETRIEVAL_ARCHITECTURE.md`](docs/retrieval/HYBRID_RETRIEVAL_ARCHITECTURE.md) · [`COMMANDS.md`](docs/retrieval/COMMANDS.md) · [`EVALUATION.md`](docs/retrieval/EVALUATION.md) | Retrieval pipeline, BM25/RRF/reranker design, commands, evaluation |
| [`docs/indexing/`](docs/indexing/) | Embedding + ChromaDB indexing pipeline documentation |
| [`docs/chunker/CHUNKER_COMPLETION_REPORT.md`](docs/chunker/CHUNKER_COMPLETION_REPORT.md) | Evidence for the chunking milestone: tests, quality gates, real-document acceptance runs, HybridChunker comparison |
| [`docs/chunker/ARCHITECTURE.md`](docs/chunker/ARCHITECTURE.md) · [`OUTPUT_SCHEMA.md`](docs/chunker/OUTPUT_SCHEMA.md) · [`CONFIGURATION.md`](docs/chunker/CONFIGURATION.md) · [`VALIDATION.md`](docs/chunker/VALIDATION.md) · [`MENTOR_EXPLANATION.md`](docs/chunker/MENTOR_EXPLANATION.md) | Chunker pipeline, output contract, config reference, validation gates, design rationale |
| [`RESTRUCTURE_COMPLETION_REPORT.md`](RESTRUCTURE_COMPLETION_REPORT.md) | Evidence for the service-architecture restructure: mapping, tests, quality gates, acceptance runs |
| [`docs/architecture/service_architecture.md`](docs/architecture/service_architecture.md) | The service-oriented architecture: every package, dependency direction, how to add a new service |
| [`docs/architecture/service_restructure_plan.md`](docs/architecture/service_restructure_plan.md) | The migration plan the restructure followed, with the complete old→new module mapping |
| [`PARSER_STAGE_FINAL_REPORT.md`](PARSER_STAGE_FINAL_REPORT.md) | Authoritative completion report for the parsing milestone: defect fixes, quality-gate results, OCR verification |
| [`PROJECT_COMPLETION_AUDIT.md`](PROJECT_COMPLETION_AUDIT.md) | The evidence-based audit the parsing-milestone hardening pass was scoped against |
| [`docs/FINAL_IMPLEMENTATION_REPORT.md`](docs/FINAL_IMPLEMENTATION_REPORT.md) | Measured results, all 27 pages, verified vs unresolved |
| [`docs/architecture.md`](docs/architecture.md) | Module responsibilities and data flow (parser service internals) |
| [`docs/docling_parameter_guide.md`](docs/docling_parameter_guide.md) | Every option: Docling field, default, chosen value, trade-off |
| [`docs/validation_methodology.md`](docs/validation_methodology.md) | What each check proves and, importantly, what it does not |
| [`docs/productionization_options.md`](docs/productionization_options.md) | Four deployment options compared; choice justified; ingestion contract |
| [`docs/limitations.md`](docs/limitations.md) | Honest residual limitations |
| [`TASKS.md`](TASKS.md) | Work log, ADRs, the 12 defects found by running against the real document, risks |

Reproduce the determinism check between two runs:

```bash
python docs/_generated/determinism_check.py data/output/parser/<stem>/<run-a> data/output/parser/<stem>/<run-b>
```

Regenerate the Docling parameter guide after an upgrade:

```bash
python docs/_generated/gen_param_guide.py
```
