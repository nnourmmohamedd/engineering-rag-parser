# Third-party licenses

Every entry was **read from the installed distribution metadata** in this
project's `.venv` (`importlib.metadata`), not copied from documentation or
recalled from memory. Regenerate with:

```bash
python -c "from importlib.metadata import metadata,version; \
[print(p, version(p), (metadata(p).get('License-Expression') or metadata(p).get('License'))) \
 for p in ['docling','pypdf','pdfminer.six','pypdfium2','Pillow','torch']]"
```

Verified on 2026-08-24 against Python 3.13.9 / Windows 11.

---

## Policy

This parser is intended for **corporate engineering use**, so the default
runtime path is restricted to permissive licenses (MIT / BSD / Apache-2.0 /
MIT-CMU). Two consequences:

1. **No copyleft in the runtime path.** Nothing below is GPL, LGPL or AGPL.
2. **`PyMuPDF` / `fitz` is deliberately excluded.** It is **AGPL-3.0**. It is
   the most convenient library for PDF page rendering and image extraction, and
   it is used by many comparable projects — this one uses `pypdfium2`
   (BSD-3-Clause + Apache-2.0) instead, at some cost in convenience. See
   [ADR-003](TASKS.md#adr-003--preflight-baseline-must-not-use-docling-and-must-avoid-agpl).
   A test (`tests/unit/test_package_hygiene.py::test_no_agpl_dependency_in_runtime`)
   fails the build if `fitz`/`pymupdf` is ever imported anywhere in `src/`.

---

## Runtime dependencies (installed by default)

| Package | Version | License | Purpose in this project | Source |
|---|---|---|---|---|
| `docling` | 2.121.0 | MIT | PDF conversion pipeline, layout + table structure models | https://github.com/docling-project/docling |
| `docling-core` | 2.92.0 | MIT | `DoclingDocument` model, JSON/Markdown serializers | https://github.com/docling-project |
| `docling-ibm-models` | 3.14.0 | MIT | Layout (Heron) and TableFormer model code | https://github.com/docling-project/docling-ibm-models |
| `docling-parse` | 7.15.0 | MIT | Low-level PDF text/geometry backend | https://github.com/docling-project/docling-parse |
| `pypdf` | 6.16.2 | BSD-3-Clause | **Preflight**: metadata, encryption, outline, fonts, annotations, attachments | https://github.com/py-pdf/pypdf |
| `pdfminer.six` | 20260107 | MIT | **Preflight**: independent per-page text + line geometry baseline | https://github.com/pdfminer/pdfminer.six |
| `pypdfium2` | 5.13.0 | BSD-3-Clause + Apache-2.0 (PDFium) | **Preflight**: page geometry, raster image objects, local page rendering for visual review | https://github.com/pypdfium2-team/pypdfium2 |
| `Pillow` | 12.3.0 | MIT-CMU | Image handling and PNG asset writing | https://python-pillow.org |
| `pydantic` | 2.13.4 | MIT | Validated configuration, domain models, reports | https://github.com/pydantic/pydantic |
| `PyYAML` | 6.0.3 | MIT | Config profile loading (`configs/*.yaml`) | https://pyyaml.org/ |
| `typer` | 0.26.8 | MIT | `engrag-parse` CLI | https://github.com/fastapi/typer |
| `rich` | 15.0.0 | MIT | Terminal tables, structured log rendering | https://github.com/Textualize/rich |

### Transitively required by Docling

| Package | Version | License | Why present | Source |
|---|---|---|---|---|
| `torch` | 2.13.0+**cpu** | Apache-2.0 (with LLVM exception for bundled parts) | Inference for the layout + TableFormer models. Installed from the **CPU wheel index** per [ADR-002](TASKS.md#adr-002--cpu-only-pytorch-is-the-default-accelerator-path) | https://pytorch.org |
| `torchvision` | 0.28.0+cpu | BSD-3-Clause | Image transforms used by the vision models | https://github.com/pytorch/vision |
| `numpy` | 2.5.2 | BSD-3-Clause (with 0BSD/MIT/Zlib bundled components) | Array maths under torch/Docling | https://numpy.org |
| `transformers` | 5.15.1 | Apache-2.0 | Model loading for Docling's enrichment stages | https://github.com/huggingface/transformers |
| `huggingface-hub` | 1.28.0 | Apache-2.0 | Model-weight download and local cache resolution | https://github.com/huggingface/huggingface_hub |
| `cryptography` | 50.0.0 | Apache-2.0 OR BSD-3-Clause | Encrypted-PDF support inside `pypdf` | https://github.com/pyca/cryptography |
| `sympy` | 1.14.0 | BSD-3-Clause | torch dependency | https://sympy.org |
| `networkx` | 3.6.1 | BSD-3-Clause | torch dependency | https://networkx.org |
| `filelock` | 3.32.3 | MIT | Model cache locking | https://github.com/tox-dev/py-filelock |

---

## Development dependencies (not shipped at runtime)

| Package | Version | License | Purpose | Source |
|---|---|---|---|---|
| `pytest` | 9.1.1 | MIT | Test runner | https://docs.pytest.org |
| `pytest-cov` | 7.1.0 | MIT | Coverage reporting | https://github.com/pytest-dev/pytest-cov |
| `ruff` | 0.16.4 | MIT | Lint + format | https://docs.astral.sh/ruff |
| `mypy` | 2.3.1 | MIT | Static type checking | https://www.mypy-lang.org/ |
| `reportlab` | 5.0.1 | BSD-3-Clause | Generates the synthetic fixture PDFs at test time, so no binary test blobs are committed | https://www.reportlab.com/ |
| `ipykernel` | 7.3.0 | BSD-3-Clause | Jupyter kernel for the exploration notebook | https://github.com/ipython/ipykernel |

---

## Optional extras (opt-in, not installed by default)

| Extra | Package | License | Notes |
|---|---|---|---|
| `[ocr]` | `easyocr` | Apache-2.0 | Only for genuinely scanned documents. Downloads ~100 MB of detection/recognition weights on first use. **Not installed in the verified environment** — the acceptance document is digitally generated and needs no OCR. |
| `[vlm]` | `transformers`, `accelerate` | Apache-2.0 | Optional local picture description. Disabled by default ([ADR-005](TASKS.md#adr-005--no-vlm-picture-description-in-the-default-path)). |

---

## Model artifacts

Model **weights** are downloaded at first run and carry their own licenses,
separate from the code licenses above.

| Model | Used for | License | Size (approx.) |
|---|---|---|---|
| `docling-project/docling-layout-heron` | Page layout / region detection | MIT (per model card) | ~200 MB |
| TableFormer (`docling-ibm-models`) | Table structure recovery | MIT (per model card) | ~140 MB |
| `HuggingFaceTB/SmolVLM-256M-Instruct` | Optional picture description | Apache-2.0 | ~500 MB — **not downloaded**, VLM disabled by default |
| EasyOCR detection/recognition | Optional OCR | Apache-2.0 | ~100 MB — **not downloaded**, OCR disabled by default |

Weights land in the standard Hugging Face cache unless `docling.artifacts_path`
is set. Verify the current model card before redistributing weights: a model
card can change license between releases, and only the code licenses above were
machine-verified here.

---

## This project

`engineering-rag-parser` is **MIT** licensed (see `pyproject.toml`).

The supplied `Instrumentation-and-Control-Engineering.pdf` is **not** covered by
that license, is treated as confidential, and is excluded from version control
by `.gitignore` along with every artifact derived from it.
