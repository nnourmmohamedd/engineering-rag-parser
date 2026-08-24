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
| Commit | ✅ DONE | `b4248de` — "Verify OCR/scanned path end-to-end with RapidOCR, fix D-7 gate defect" |
| Push to GitHub | ❌ BLOCKED (confirmed external network restriction, not a code/auth problem) | `git push -u origin master` fails with `Recv failure: Connection was reset` against `https://github.com/nnourmmohamedd/engineering-rag-parser.git`. Diagnosed: TCP connects to `github.com:443` and `:22`, but the TLS/application-layer exchange resets — the same restriction that blocked EasyOCR's model download from `github.com` earlier in this session (§18.3). User confirmed this network blocks GitHub. **Action once off this network:** `git push -u origin master` (commit `b4248de` is already made locally and ready to push; nothing else to do). |
| GitHub Actions CI run | ⏳ PENDING (blocked on the push above) | Cannot run until the push succeeds. Once pushed, check `https://github.com/nnourmmohamedd/engineering-rag-parser/actions`. `gh` CLI is also not authenticated in this environment as a secondary blocker. |
| Human engineering review of diagrams/raster tables | ⏳ PENDING (by design) | Not fabricated as complete; 3 unrecovered tables and 15 diagrams on the acceptance document still require a qualified human reviewer — see `validation/review/*.html` in the acceptance run |

## Completion summary

```text
Parser software milestone:            100%
Controlled OCR benchmark:             PASS
Original engineering PDF:             PASS_WITH_WARNINGS (4 legitimate, unchanged warnings)
Human engineering semantic review:    PENDING
Full RAG chatbot:                     ~18% (unchanged; out of scope for this pass)
```
