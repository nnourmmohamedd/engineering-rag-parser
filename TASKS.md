# TASKS.md — Engineering-Grade Docling PDF Parser

Living work log: plan, status, decisions, validation findings, residual risks.
All timestamps UTC. Status legend: `TODO` / `WIP` / `DONE` / `BLOCKED` / `DEFERRED`.

**Project status: COMPLETE.** Final acceptance run `PASS_WITH_WARNINGS`,
19/19 gates, 201 tests passing. See
[`docs/FINAL_IMPLEMENTATION_REPORT.md`](docs/FINAL_IMPLEMENTATION_REPORT.md).

---

## 0. Environment evidence (recorded 2026-08-23, read-only inspection)

| Item | Observed value |
|---|---|
| OS | Microsoft Windows 11 Home Single Language, 10.0.26200 |
| CPU | 11th Gen Intel Core i7-1165G7 @ 2.80 GHz — 4 physical / 8 logical |
| RAM | 16,930,299,904 bytes (~15.8 GiB) |
| GPU | NVIDIA GeForce MX450 (**2048 MiB VRAM**), driver 581.83, CUDA 13.0; plus Intel Iris Xe |
| Python available | 3.13.9 (default), 3.10.11. **No 3.12 present.** |
| Package managers | pip 26.2.1; `uv` **not installed** |
| Git | 2.51.0.windows.1 — local repo, no remote |
| Source PDF | 5,378,401 bytes, header `%PDF-1.4`, 27 pages |
| Source SHA-256 | `01e4d6fa3a2e884f83fad507d08b228aa40f814dc0f3c44e6c9db315f73c3b1a` |

Copied byte-identically to `data/input/` (SHA-256 re-verified after copy). Original untouched.

---

## 1. Architecture decisions (ADR-style)

### ADR-001 — Python 3.13.9 as the project interpreter
**Context.** The brief suggests 3.12 *"unless environment evidence supports a better choice."* 3.12 is not installed; only 3.13.9 and 3.10.11 are.
**Decision.** Use **3.13.9** — the machine default, with `cp313` wheels available for Docling and torch.
**Consequence.** `requires-python = ">=3.10,<3.14"` so the package still installs on 3.10–3.12, but all executed evidence comes from 3.13.9.
**Status.** DONE.

### ADR-002 — CPU-only PyTorch is the default accelerator path
**Context.** A CUDA GPU exists but the MX450 exposes only **2048 MiB** VRAM. Docling's layout + TableFormer models would thrash or OOM, and a CUDA OOM mid-conversion yields a *partial* document — the worst failure mode for an auditable parser.
**Decision.** Install `torch`/`torchvision` from the **CPU wheel index**; `AcceleratorDevice.CPU` in every shipped profile. GPU reachable via config, never implicit.
**Consequence.** ~8.7 s/page, deterministic and memory-safe. `torch.cuda.is_available() == False` in the verified environment.
**Status.** DONE — `torch-2.13.0+cpu`.

### ADR-003 — Preflight baseline must not use Docling, and must avoid AGPL
**Context.** Validation must be independent; comparing Docling to Docling proves nothing. Separately, corporate use makes copyleft in the runtime unacceptable.
**Decision.** Permissive-only baseline: `pypdf` (BSD-3), `pdfminer.six` (MIT), `pypdfium2` (BSD-3 + Apache-2.0), `Pillow` (MIT-CMU). **`PyMuPDF`/`fitz` rejected — AGPL-3.0**, despite being the most convenient library for the job.
**Consequence.** A test fails the build if `fitz`/`pymupdf` is ever imported in `src/`.
**Status.** DONE — verified in `THIRD_PARTY_LICENSES.md` from installed metadata.

### ADR-004 — Installable package + CLI (not a notebook, not a service)
**Decision.** `src/` layout, `engrag-parse` console script, pure-function core with injected config. The notebook is a *client*.
**Consequence.** A future FastAPI/worker adapter wraps `run_pipeline()` without touching parsing code. Comparison in `docs/productionization_options.md`.
**Status.** DONE — enforced by `test_package_hygiene.py`.

### ADR-005 — No VLM picture description in the default path
**Context.** Docling can attach machine-generated descriptions to pictures via a local VLM.
**Decision.** Off by default, behind an explicit flag. **A generated caption of a P&ID or loop wiring diagram is a hallucination risk on exactly the content an engineer most needs correct.**
**Consequence.** Every substantive picture is preserved as a referenced PNG with page + bbox provenance instead. Any VLM text, if enabled, is labelled machine-generated and never replaces the asset.
**Status.** DONE.

### ADR-006 — `heading_hierarchy` enabled, accepting TOC marker loss
**Context.** Discovered during validation: enabling it produces correct H1→H4 nesting, but TOC list items promoted to headings lose their leading `1.3`, `2.2`… markers. Disabling it preserves those markers but flattens all 76 headings to one level.
**Decision.** **Enable it.** The numbers are not lost from the document — every body heading retains its number, and document-level token recall is 100%. Correct nesting is materially more valuable for downstream section-aware chunking than numbering on a duplicate navigation block.
**Consequence.** Pages 1–2 show ~50% *page-local* critical-token recall; documented in `limitations.md` §4 and surfaced as a WARNING, never as loss.
**Status.** DONE.

### ADR-007 — Page-local attribution is a WARNING; only document-level loss is a gate
**Context.** Docling attributes a paragraph crossing a page break to the page where it *starts* — correct reading-order repair. A naive per-page comparison reported this as loss (pages 18, 23 appeared to lose `AVEVA`, `E&I`, `I-CAD`).
**Decision.** Two checks: `critical_token_recall` (page ±1 neighbour, **WARNING**) and `document_text_completeness` (whole document, **CRITICAL gate**).
**Consequence.** Relocation is reported as relocation. Only genuine absence can fail a run.
**Status.** DONE.

---

## 2. Work plan — all items complete

| # | Task | Status |
|---|---|---|
| 1 | Environment + PDF read-only inspection | DONE |
| 2 | Git init, project tree, `.gitignore` (PDF + artifacts excluded) | DONE |
| 3 | venv + pinned dependency install | DONE |
| 4 | Introspect the *installed* Docling API (no copied snippets) | DONE — snapshot in `docs/_generated/` |
| 5 | `config.py` + `domain.py` (Pydantic, profiles, thresholds) | DONE |
| 6 | `preflight.py` — independent source manifest | DONE |
| 7 | `pipeline_factory.py` — isolated Docling construction | DONE |
| 8 | `parser.py` — conversion, status handling, canonical JSON | DONE |
| 9 | `exporters.py` + `normalization.py` — Markdown + assets | DONE |
| 10 | `validation/` — coverage, structure, markdown, visual, report | DONE |
| 11 | `artifacts.py` + `cli.py` + `pipeline.py` | DONE |
| 12 | Notebook (thin educational client) | DONE — 31 cells, executes with 0 errors |
| 13 | Tests: unit, synthetic fixtures, integration, slow acceptance | DONE — 201 tests |
| 14 | Docs: README, architecture, parameter guide, validation methodology, productionization, limitations, licenses | DONE |
| 15 | Full run on the acceptance PDF | DONE — `PASS_WITH_WARNINGS` |
| 16 | Inspect all 27 pages; fix defects; rerun | DONE — see §3 |
| 17 | pytest / ruff / mypy / determinism | DONE — all green |
| 18 | `docs/FINAL_IMPLEMENTATION_REPORT.md` | DONE |

---

## 3. Validation findings — defects found by running against the real document

Each was found by inspecting real output, not by inspection of code.

| # | Defect | Where | Resolution |
|---|---|---|---|
| 1 | `save_as_json(artifacts_dir=<absolute>)` doubled the path and crashed | `parser.py` | Docling joins a **relative** `artifacts_dir` onto the JSON's parent and writes relative URIs; an absolute path bakes in machine paths. Pass `Path("assets")`. |
| 2 | **Zero-cell tables vanish from Markdown entirely** — caption followed by silence | Docling serializer | Insert an explicit marker via `insert_text(sibling=…)` on a **deep copy**, so the warning lands at the exact reading-order position and the canonical JSON stays untouched. |
| 3 | `escape_html=True` corrupted engineering acronyms: `C&I` → `C&amp;I` (35×), `P&ID` → `P&amp;ID` (22×) | `exporters.py` | Disabled `escape_html` and `escape_underscores` (the latter would corrupt `FT_101`). |
| 4 | Coverage compared furniture-stripped Docling body against **unstripped** native text, reporting each page's own footer page number as loss — 24/27 pages failed | `validation/coverage.py` | `strip_furniture()` removes proven furniture from both sides; `furniture_chars_excluded` recorded per page. |
| 5 | Cross-page paragraph attribution reported as loss (pages 18, 23) | `validation/coverage.py` | ADR-007: page-local WARNING + document-level CRITICAL gate; `relocated_*` fields. |
| 6 | pdfminer `(cid:NNN)` glyph artifacts polluted the independent baseline, inventing a `127` token | `normalization.py` | Stripped from both sides of every comparison. |
| 7 | `NUMBER_RE` harvested fragments: `FT-101` also yielded `-101` and `101` | `normalization.py` | Negative lookbehind so tag internals are not re-tokenised. |
| 8 | Area-based review flagging missed 4 real diagrams (pages 13, 16, 22, 27 at 23.6%/24.8%/20.7%/13.6%) | `preflight.py` | Review driven by **presence** of a non-repeated image, not area. |
| 9 | ReportLab writes `/Title = "(anonymous)"`, promoted into an H1 | `exporters.py` | Placeholder-title guard. |
| 10 | Table 2's body region (page 26) reported as anonymous "table region 1" | `exporters.py` | Associate a caption at the foot of page N with a body region on page N+1. |
| 11 | Pages labelled `CRITICAL` while every gate passed | `validation/coverage.py` | Page-local token shortfall is a WARNING; the document-level gate is the authority. |
| 12 | `dlparse_v4` (the widely copied recipe) is a removed shim emitting `FutureWarning` | `config.py` | Not offered as a config value; `docling_parse` is the current backend. |

### Final measured results

- **27/27 pages** parsed, all with provenance. Source SHA-256 unchanged.
- **100%** document-level critical-token recall (77/76 — parsed is a superset) and **100%** word-type recall.
- 32,637 → 32,506 characters (**99.6%**) after like-for-like furniture stripping.
- **15/15** substantive figures represented and preserved; 54 decorative instances excluded.
- **3/3** labelled tables located from native text with individual outcomes.
- Markdown: 0 broken links, 0 base64, 0 absolute paths, 0 placeholders, 0 mojibake, 0 furniture leakage.
- **19/19** acceptance gates; 4 warnings; determinism verified byte-identical.

---

## 4. Residual risks and human-review items

### Requires human action

1. **Tables 1, 2, 3 are not machine-readable.** All three bodies are raster images with no text layer (verified independently with pdfminer). Preserved as PNG assets and flagged; contents need transcription or a targeted OCR pass.
2. **15 engineering diagrams are unverified.** Preserved with provenance and given review cards, but **no automated check confirms their labels, symbols or connections were recovered.**
3. **Pages 8 and 11** have zero native body characters — completeness cannot be judged from text.

### Accepted limitations

4. TOC entries on pages 1–2 lose their leading section numbers (ADR-006).
5. The TOC is serialized as headings, duplicating the body structure. Chunking should treat content before `<!-- page: 3 -->` as an index.
6. Cross-page relocation detection uses a ±1-page window; content moved further is caught only by the document-level gate.
7. One heading-level jump: `## A typical hook-up drawing specifies:` — a sentence Docling classified as a heading. Cosmetic.

### Untested paths (implemented, not exercised)

8. **GPU** (`accelerator_device: cuda`) — 2 GiB VRAM locally; CPU-only torch installed.
9. **OCR / `scanned` profile** — option construction is unit-tested; `easyocr` is not installed, so no OCR conversion has been run.
10. **VLM picture description** — implemented behind a flag, never executed.
11. **Quarantine path** for `PARTIAL_SUCCESS` — tested by construction, never by a real timeout.
12. **Python 3.10–3.12** — declared supported, not executed.

Full discussion: [`docs/limitations.md`](docs/limitations.md).

---

## 5. Deferred to the next milestone (explicitly out of scope)

Not implemented, by design: chunking, embeddings, vector database, retrieval,
cross-encoder reranking, chatbot. The metadata contract those stages consume is
specified in
[`docs/productionization_options.md`](docs/productionization_options.md#future-ingestion-contract)
and already present in every run's artifacts.
