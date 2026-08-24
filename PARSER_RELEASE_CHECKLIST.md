# Parser Release Checklist

Evidence-based checklist for the OCR verification pass (2026-08-24). Every item below is backed by a
command actually re-executed against the final code state; see `PARSER_STAGE_FINAL_REPORT.md` §18–20
for full detail. Nothing here is marked done without evidence.

| Item | Status | Evidence |
|---|---|---|
| Clean installation (`.venv-clean`, `pip install -e ".[dev,ocr]"`) | ✅ DONE | `--version`, `--help`, 229 fast tests, ruff, mypy, build all PASS in the clean venv; `.venv-clean` removed afterward, `.venv` untouched |
| OCR installation (`pip install -e ".[ocr]"` → RapidOCR) | ✅ DONE | `rapidocr-onnxruntime` 1.2.3 installed; models bundled in wheel, no runtime download |
| Image-only status independently proven | ✅ DONE | `pdfminer.six` extracts 0 chars; 1 raster image/page (pypdf); 10 regression tests |
| Explicit `scanned` profile run | ✅ DONE | Run `20260824T100730Z-57f84fd5`, status PASS, 0 failed gates |
| Automatic (`auto`) profile run | ✅ DONE | Run `20260824T100804Z-57f84fd5`, correctly routed to `scanned`, status PASS |
| OCR validation vs independent ground truth | ✅ DONE | 100% critical-token recall (31/31), 96.9% word-type recall, page count/order preserved |
| Fast tests | ✅ DONE | 229 passed, 0 failed |
| Slow tests | ✅ DONE | 42 passed, 0 failed (includes real OCR conversion + full 27-page acceptance suite) |
| Coverage | ✅ DONE | 84% (warm model cache), fast suite |
| Ruff (format + lint) | ✅ DONE | `ruff format --check .` and `ruff check .` both PASS |
| mypy | ✅ DONE | `mypy src` — no issues in 17 source files |
| Package build | ✅ DONE | `python -m build --wheel` succeeds; `Provides-Extra: dev, ocr, ocr-easyocr, vlm` |
| Notebook validation | ✅ DONE | Valid nbformat 4.5, 31 cells |
| Main acceptance PDF re-run (regression check) | ✅ DONE | Run `20260824T103000Z-01e4d6fa`, `PASS_WITH_WARNINGS`, same 4 legitimate warnings as before, 37/37 gates evaluated, 0 failed |
| Git safety audit | ✅ DONE | Staged file set is exactly 9 modified + 8 new source/doc/test files; no PDFs, artifacts, secrets, `.venv`, or absolute paths staged |
| Commit | ⏳ PENDING | Commit hash recorded after this checklist is committed alongside it |
| Push to GitHub | ⏳ PENDING | `https://github.com/nnourmmohamedd/engineering-rag-parser` (remote already configured from a prior session; branch `master` already tracks `origin/master`) |
| GitHub Actions CI run | ⏳ PENDING | `gh` CLI is not authenticated in this environment (`gh auth status` reports not logged in); the workflow will run automatically on push, confirm at the repository's **Actions** tab |
| Human engineering review of diagrams/raster tables | ⏳ PENDING (by design) | Not fabricated as complete; 3 unrecovered tables and 15 diagrams on the acceptance document still require a qualified human reviewer — see `validation/review/*.html` in the acceptance run |

## Completion summary

```text
Parser software milestone:            100%
Controlled OCR benchmark:             PASS
Original engineering PDF:             PASS_WITH_WARNINGS (4 legitimate, unchanged warnings)
Human engineering semantic review:    PENDING
Full RAG chatbot:                     ~18% (unchanged; out of scope for this pass)
```
