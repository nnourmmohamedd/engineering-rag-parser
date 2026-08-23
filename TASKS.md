# TASKS.md — Engineering-Grade Docling PDF Parser

Living work log: plan, status, decisions, validation findings, residual risks.
All timestamps UTC. Status legend: `TODO` / `WIP` / `DONE` / `BLOCKED`.

---

## 0. Environment evidence (recorded 2026-08-23, read-only inspection)

| Item | Observed value |
|---|---|
| OS | Microsoft Windows 11 Home Single Language, 10.0.26200 (Build 26200) |
| CPU | 11th Gen Intel Core i7-1165G7 @ 2.80 GHz — 4 physical cores / 8 logical |
| RAM | 16,930,299,904 bytes (~15.8 GiB) |
| GPU | NVIDIA GeForce MX450 (**2048 MiB VRAM**), driver 581.83, CUDA 13.0; plus Intel Iris Xe iGPU |
| Python available | 3.13.9 (default, `py -0p` marks `*`), 3.10.11. **No 3.12 present.** |
| Package managers | pip 26.2.1; `uv` **not installed** |
| Git | 2.51.0.windows.1 — available, repo initialised locally, no remote |
| Source PDF | `Instrumentation-and-Control-Engineering.pdf`, 5,378,401 bytes, header `%PDF-1.4` |
| Source SHA-256 | `01e4d6fa3a2e884f83fad507d08b228aa40f814dc0f3c44e6c9db315f73c3b1a` |

Copied byte-identically to `data/input/` (SHA-256 re-verified equal after copy). Original left untouched.

---

## 1. Architecture decisions (ADR-style)

### ADR-001 — Python 3.13.9 as the project interpreter
**Context.** The master prompt suggests 3.12 as a conservative default *"unless environment evidence supports a better choice."* 3.12 is not installed on this machine; only 3.13.9 and 3.10.11 are.
**Decision.** Use **3.13.9**. It is the machine default, current Docling and `torch` publish `cp313` Windows wheels, and 3.10 is near end of upstream bugfix support.
**Consequence.** `requires-python = ">=3.10,<3.14"` is declared so the package still installs on 3.10–3.12 for other engineers, but the pinned lock and all executed evidence come from 3.13.9.
**Status.** DONE — venv created at `.venv`, verified `Python 3.13.9`.

### ADR-002 — CPU-only PyTorch is the default accelerator path
**Context.** A CUDA GPU exists but the MX450 exposes only **2048 MiB** of VRAM. Docling's layout + TableFormer models plus any picture-description VLM would either OOM or thrash at that size, and a CUDA-OOM mid-conversion produces a *partial* document — the worst failure mode for an auditable parser.
**Decision.** Install `torch`/`torchvision` from the **CPU wheel index**. `AcceleratorDevice.CPU` is the default in every shipped profile. GPU stays reachable via config (`accelerator.device: cuda`/`auto`) but is never selected implicitly.
**Consequence.** Slower conversion, but deterministic and memory-safe on this hardware. Documented in the parameter guide and README troubleshooting.
**Status.** DONE — `torch-2.13.0+cpu`, `torchvision-0.28.0+cpu` installed.

### ADR-003 — Preflight baseline must not use Docling, and must avoid AGPL
**Context.** Validation must be independent: comparing Docling to Docling proves nothing. Separately, the runtime is intended for corporate engineering use, so copyleft in the default path is unacceptable.
**Decision.** Build the source manifest from a **permissive-only** stack:
`pypdf` (BSD-3-Clause), `pdfminer.six` (MIT), `pypdfium2` (BSD-3-Clause + Apache-2.0/PDFium), `Pillow` (MIT-CMU).
**Explicitly rejected: `PyMuPDF`/`fitz` — AGPL-3.0.** It is the most convenient library for this job and is deliberately not used anywhere, including tests and the notebook.
**Consequence.** Page rendering uses PDFium; text baseline uses pdfminer.six; structure/metadata uses pypdf. Recorded in `THIRD_PARTY_LICENSES.md`.
**Status.** TODO — pending install.

### ADR-004 — Installable package + CLI (not a notebook, not a service)
**Context.** Milestone is a reusable upstream parser for a later RAG pipeline.
**Decision.** `src/` layout, `engrag-parse` console script, pure-function core with injected config. The notebook is a *client* of the package and contains no parsing logic.
**Consequence.** A future FastAPI/worker adapter wraps `parser.parse_document()` without touching parsing code. Full comparison in `docs/productionization_options.md`.
**Status.** TODO.

### ADR-005 — No VLM picture description in the default path
**Context.** Docling can attach machine-generated descriptions to pictures via a local VLM (e.g. SmolVLM / Granite-Vision).
**Decision.** Off by default, exposed behind an explicit profile/flag. Hardware here (2 GiB VRAM, 4-core CPU) makes it slow and unreliable, and — more importantly — **a generated caption of a P&ID or loop wiring diagram is a hallucination risk on exactly the content an engineer most needs to be correct.**
**Consequence.** Every substantive picture is instead preserved as a referenced PNG asset with page + bounding-box provenance. Any VLM text, if ever enabled, is labelled machine-generated and never replaces the asset.
**Status.** TODO.

---

## 2. Work plan

| # | Task | Status |
|---|---|---|
| 1 | Environment + PDF read-only inspection | DONE |
| 2 | Git init, project tree, `.gitignore` (PDF + artifacts excluded) | DONE |
| 3 | venv + pinned dependency install | WIP |
| 4 | Introspect the *installed* Docling API (no copied snippets) | TODO |
| 5 | `config.py` + `domain.py` (Pydantic models, profiles, thresholds) | TODO |
| 6 | `preflight.py` — independent source manifest | TODO |
| 7 | `pipeline_factory.py` — isolated Docling construction | TODO |
| 8 | `parser.py` — conversion, status handling, canonical JSON | TODO |
| 9 | `exporters.py` + `normalization.py` — Markdown + assets | TODO |
| 10 | `validation/` — coverage, structure, markdown, visual, report | TODO |
| 11 | `artifacts.py` + `cli.py` | TODO |
| 12 | Notebook (thin educational client) | TODO |
| 13 | Tests: unit, synthetic fixtures, integration, slow acceptance | TODO |
| 14 | Docs: README, architecture, parameter guide, validation methodology, productionization, limitations, licenses | TODO |
| 15 | Full run on the acceptance PDF | TODO |
| 16 | Inspect all 27 pages; fix defects; rerun | TODO |
| 17 | pytest / ruff / mypy / determinism | TODO |
| 18 | `docs/FINAL_IMPLEMENTATION_REPORT.md` | TODO |

---

## 3. Validation findings

_(populated from real runs — see `docs/FINAL_IMPLEMENTATION_REPORT.md` for the authoritative record)_

## 4. Residual risks

_(populated as discovered)_
