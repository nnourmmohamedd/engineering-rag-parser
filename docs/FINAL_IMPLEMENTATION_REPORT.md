# Final implementation report

**Document:** `Instrumentation-and-Control-Engineering.pdf`
**Final status: `PASS_WITH_WARNINGS`** — 19/19 acceptance gates passed, 4 warnings, 5 human-review items.
**Run:** `artifacts/Instrumentation-and-Control-Engineering/20260823T223107Z-01e4d6fa/`

Every number below was measured on that run. Nothing here is a template value or
an expectation.

---

## 1. Headline result

| | |
|---|---|
| Source | 27 pages, 5,378,401 bytes, PDF 1.4, not encrypted |
| Source SHA-256 | `01e4d6fa3a2e884f83fad507d08b228aa40f814dc0f3c44e6c9db315f73c3b1a` (unchanged after the run) |
| Conversion | `success` (not partial), 235.1 s wall |
| Pages parsed | **27 / 27**, all with provenance |
| Document-level critical-token recall | **100.0%** (77 of 76 source tokens present — parsed is a superset) |
| Document-level word-type recall | **100.0%** |
| Native vs parsed characters (furniture-stripped) | 32,637 → 32,506 (**99.6%**) |
| Figures | 15 substantive preserved as PNG assets; 54 decorative furniture instances excluded |
| Tables 1 / 2 / 3 | All located; **all three bodies are raster images — 0 cells recoverable** |
| Acceptance gates | **19 / 19 passed** |
| Warnings | 4 |
| Determinism | Byte-identical across same-code runs, timestamps excluded (§10) |

### The single most important finding

**All three labelled tables have raster-image bodies with no text layer.** Their
contents are *not machine-readable* and are not present in the Markdown as text.

This is not a parser defect — it is a property of the source document, verified
independently with pdfminer (page 16 contains no text at all between the footer
at y=38 and the caption at y=374). It is called out because **Docling's own
Markdown serializer drops zero-cell tables entirely**, leaving a caption
followed by silence. A parser that shipped that output would look flawless and
would have silently lost three tables.

---

## 2. Environment and versions

| Item | Value |
|---|---|
| OS | Windows 11 Home Single Language, 10.0.26200 |
| CPU | Intel Core i7-1165G7, 4 physical / 8 logical cores |
| RAM | ~15.8 GiB |
| GPU | NVIDIA GeForce MX450, **2048 MiB VRAM** — unused by choice (ADR-002) |
| Python | **3.13.9** CPython |
| Package manager | pip 26.2.1 (`uv` not installed) |

| Package | Version |
|---|---|
| `docling` | **2.121.0** |
| `docling-core` | **2.92.0** |
| `docling-ibm-models` | 3.14.0 |
| `docling-parse` | 7.15.0 |
| `torch` | **2.13.0+cpu** (`torch.cuda.is_available() == False`) |
| `torchvision` | 0.28.0+cpu |
| `pydantic` 2.13.4 · `pypdf` 6.16.2 · `pdfminer.six` 20260107 · `pypdfium2` 5.13.0 (PDFium 153.0.7999.0) · `Pillow` 12.3.0 | |
| `pytest` 9.1.1 · `ruff` 0.16.4 · `mypy` 2.3.1 | |

Full license inventory, read from installed metadata: [`../THIRD_PARTY_LICENSES.md`](../THIRD_PARTY_LICENSES.md).

---

## 3. Effective Docling configuration and why

Profile **`high_fidelity`**, config hash `83adcde3902fd350…`.
Machine-generated table: [`docling_parameter_guide.md`](docling_parameter_guide.md).

| Option | Docling default | Selected | Why |
|---|---|---|---|
| `do_ocr` | **`True`** | **`False`** | The document is digitally generated and text-searchable (36,338 native chars). OCR over a good text layer duplicates and degrades it — `no_duplicated_spans` exists to catch exactly that failure, and it passes. |
| backend | `DoclingParseDocumentBackend` | same | Introspection showed `dlparse_v4` is a shim emitting `FutureWarning`, documented as removed in 2.74.0. The widely copied recipe is obsolete. |
| `table_structure_options.mode` | `accurate` | `accurate` | Table fidelity matters here. (It made no difference: the tables are images.) |
| `images_scale` | `1.0` | **`2.0`** | Below ~2.0 instrument tags inside a preserved diagram stop being legible. |
| `generate_page_images` / `generate_picture_images` | `False` | **`True`** | Required for referenced assets and the visual review cards. |
| `heading_hierarchy_options.enabled` | **`False`** | **`True`** | Produced correct H1→H4 nesting (76 headings, no level jumps). Cost: TOC list items lose their leading numbers — see §7. |
| `accelerator_options.device` | `auto` | **`cpu`** | The MX450 has 2 GiB VRAM. A CUDA OOM mid-conversion returns a *partial* document — the worst outcome for an auditable parser. |
| `do_picture_description` | `False` | `False` | ADR-005. A plausible-but-wrong caption on a P&ID is more dangerous than none. |
| `enable_remote_services` | `False` | `False` | Enforced by a config validator that rejects `True`, not merely defaulted. |
| `document_timeout` | `None` | `3600.0` | Bounded resource use for untrusted input. |

---

## 4. Runtime and resource observations

| Stage | Seconds | Note |
|---|---|---|
| Preflight | 3.0 | pypdf + pdfminer.six + pypdfium2 over 27 pages |
| **Docling conversion** | **235.2** | 8.7 s/page on 4 CPU cores; dominates the run |
| JSON serialization | 6.7 | Referenced image mode, 209 artifacts |
| Asset + Markdown export | 24.1 | 15 picture assets + 27 page renders at scale 2.0 |
| Validation | 0.4 | All checks including 17 review cards |
| **Total** | **~269 s (4.5 min)** | |

Peak memory stayed well within 16 GiB; no swapping observed. First run additionally
downloads ~340 MB of model weights.

Docling's own confidence report: `parse_score` **1.00**, `layout_score` **0.850**,
`mean_score` **0.925**, `low_score` **0.857**. `table_score` and `ocr_score` are
`NaN` — no cells were recovered and OCR did not run.

---

## 5. Source inventory (independent baseline — no Docling)

| Metric | Value |
|---|---|
| Pages | 27, all A4 (596 × 842 pt), rotation 0 |
| Characters / words | 36,338 / 4,494 |
| Fonts | 2 — `AAAAAA+ArialMT`, `BAAAAA+Arial-ItalicMT` |
| Outline (bookmarks) | 56 entries |
| Metadata | `Title: Instrumentation and Control Engineering`; `Producer: Skia/PDF m143 Google Docs Renderer` |
| Raster images | **69 total = 54 decorative + 15 substantive** |
| Sparse-text pages | 8, 11 |
| Image-heavy pages (≥25% area) | 4, 6, 8, 9, 11, 14, 18, 20, 21, 23, 26 |
| **Flagged for visual review** | **4, 6, 8, 9, 11, 13, 14, 16, 18, 20, 21, 22, 23, 26, 27** (15 pages) |
| Source anomalies | pypdf: "Multiple definitions in dictionary" ×28 (lenient writer; non-fatal) |

**Why 15 review pages and not 11.** Pages 13, 16, 22 and 27 carry a real diagram
but fall *below* the 25%-of-page area threshold (23.6%, 24.8%, 20.7%, 13.6%).
Flagging is therefore driven by **presence of a non-repeated image, not area** —
under a purely area-based rule those four diagrams would have passed unreviewed.

**Decorative vs substantive.** Two image signatures repeat on all 27 pages: a
512×512 watermark at bbox (185, 308, 411, 534) and a 1758×534 banner at
(20, 628, 549, 786). 27 × 2 = 54 decorative instances. The remaining 15 appear
exactly once each — those are the figures.

---

## 6. Parsed inventory (DoclingDocument)

| Item | Count |
|---|---|
| Pages | 27 |
| Items total / with provenance | 367 / **367 (100%)** |
| Section headers | 75 (levels: L1 ×11, L2 ×40, L3 ×24) |
| Titles | 0 — see §7 |
| Paragraphs | 108 |
| List items | 41 (all ordered) |
| Tables | 2 regions, **0 cells** |
| Pictures | 114 → 13 substantive + 101 decorative after classification |
| Captions | 1 |
| Formulas / code blocks | 0 / 0 |
| Furniture items | 26 (`page_footer`) |
| Characters | 35,413 |

**114 pictures vs 15 source images.** The layout model reports the page banner
as several separate picture regions on every page. Classification against the
preflight bounding boxes reduces these to 13 substantive figures; the other two
substantive regions (pages 16 and 26) were classified by Docling as *tables*, so
all 15 are accounted for.

---

## 7. Per-page validation — all 27 pages

`cov` = character coverage (parsed/native, furniture-stripped both sides).
`critR` = page-local critical-token recall. `fig` = substantive figures.

| Pg | Native | Parsed | cov | tokR | critR | fig | Severity | Review | Finding |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1524 | 1521 | 1.00 | 1.00 | **0.55** | 0 | WARNING | ✓ | TOC page — section numbers `1.3…4.2` live on the body headings instead (§7.1) |
| 2 | 1377 | 1341 | 0.97 | 0.97 | **0.47** | 0 | WARNING | ✓ | TOC page — same cause, numbers `4.3…6.4` |
| 3 | 1858 | 1858 | 1.00 | 1.00 | 1.00 | 0 | INFO | — | Clean |
| 4 | 1185 | 1173 | 0.99 | 0.97 | 1.00 | 1 | INFO | ✓ | Figure: project-lifecycle / phasing graphic |
| 5 | 2599 | 2590 | 1.00 | 1.00 | 1.00 | 0 | INFO | — | Clean |
| 6 | 657 | 653 | 0.99 | 1.00 | 1.00 | 1 | INFO | ✓ | Figure: conceptual design process flow (§2) |
| 7 | 1821 | 1817 | 1.00 | 1.00 | 1.00 | 0 | INFO | — | Clean |
| 8 | **0** | 0 | 1.00 | 1.00 | 1.00 | 1 | INFO | ✓ | **Sparse** — page is a FEED / feasibility-gate flow diagram; only text was the footer |
| 9 | 186 | 186 | 1.00 | 1.00 | 1.00 | 1 | INFO | ✓ | Figure: detailed-engineering design flow |
| 10 | 2265 | 2265 | 1.00 | 1.00 | 1.00 | 0 | INFO | — | Clean |
| 11 | **0** | 0 | 1.00 | 1.00 | 1.00 | 1 | INFO | ✓ | **Sparse** — procurement / installation / integration flow |
| 12 | 1386 | 1382 | 1.00 | 1.00 | 1.00 | 0 | INFO | — | Clean |
| 13 | 406 | 406 | 1.00 | 1.00 | 1.00 | 1 | INFO | ✓ | Figure (23.6% area — below the area threshold, caught by presence rule) |
| 14 | 791 | 791 | 1.00 | 1.00 | 1.00 | 1 | INFO | ✓ | Figure: **P&ID-style process/control graphic** (§3.1), largest at 56.4% |
| 15 | 1983 | 1973 | 0.99 | 1.00 | 1.00 | 0 | INFO | — | Clean |
| 16 | 1089 | 1081 | 0.99 | 1.00 | 1.00 | 1 | INFO | ✓ | **Table 1 body** — raster image, 0 cells, preserved as asset |
| 17 | 1988 | 2281 | **1.15** | 1.00 | 1.00 | 0 | INFO | — | Gains page 18's opening paragraph (cross-page merge) |
| 18 | 808 | 499 | **0.62** | 0.72 | 1.00 | 1 | WARNING | ✓ | 2 spans **relocated** to page 17; figure: control-system architecture |
| 19 | 1155 | 1155 | 1.00 | 1.00 | 1.00 | 0 | INFO | — | Clean |
| 20 | 811 | 811 | 1.00 | 1.00 | 1.00 | 1 | INFO | ✓ | Figure: **instrumentation location layout** (§5.1) |
| 21 | 774 | 768 | 0.99 | 1.00 | 1.00 | 1 | INFO | ✓ | Figure: **pressure hook-up drawing** (§5.2) |
| 22 | 1338 | 1620 | **1.21** | 1.00 | 1.00 | 1 | INFO | ✓ | Gains page 23's opening paragraph; figure: **loop wiring / cable block** |
| 23 | 798 | 516 | **0.65** | 0.65 | 1.00 | 1 | WARNING | ✓ | 2 spans **relocated** to page 22; **Table 3 body** detected as a picture |
| 24 | 2163 | 2161 | 1.00 | 1.00 | 1.00 | 0 | INFO | — | Clean |
| 25 | 1369 | 1361 | 0.99 | 1.00 | 1.00 | 0 | INFO | — | Carries the **Table 2 caption**; body is on page 26 |
| 26 | 1193 | 1193 | 1.00 | 1.00 | 1.00 | 1 | INFO | ✓ | **Table 2 body** — raster image, 0 cells, preserved as asset |
| 27 | 1089 | 1080 | 0.99 | 0.98 | 1.00 | 1 | INFO | ✓ | Figure: **QA / interdisciplinary workflow** (Conclusions) |

**Summary: 23 INFO, 4 WARNING, 0 CRITICAL.** 17 pages received a visual review
card (the 15 flagged plus pages 1–2 for their warning).

### 7.1 Pages 1–2: why low `critR` is not loss

The TOC entries are list items; enabling `heading_hierarchy` promotes them to
headings and drops their leading `1.3`, `2.2`, … markers. Those numbers are
**not lost from the document** — every real body heading keeps its number
(`1.3 Project Lifecycle Phasing…` is on page 5), and the document-level gate
reports **100%** critical-token recall.

The alternative (disabling `heading_hierarchy`) preserves the TOC markers but
flattens all 76 headings to one level, which is materially worse for downstream
section-aware chunking. Documented in [`limitations.md`](limitations.md) §4.

### 7.2 Pages 18 / 23: relocation, not loss

Docling attributes a paragraph that crosses a page break to the page where it
**starts** — correct reading-order repair. Verified: `AVEVA`, `E&I`, `I-CAD` and
`AutoCAD Plant 3D` appear at the top of page 23 in the source but belong to a
paragraph beginning on page 22, and are attributed there. Pages 17 and 22 show
the mirror-image gain (1.15 / 1.21 coverage). Content is conserved; only page
attribution differs. The report labels these `relocated`.

---

## 8. Table findings — Tables 1, 2 and 3

Located from **native PDF text**, not from `document.tables` — Docling detected
only two table regions and classified the third as a picture, so trusting its
table list alone would have under-reported.

Note the numbering does **not** follow page order.

| Table | Caption page | Title | Docling outcome | Cells | Preserved as |
|---|---|---|---|---|---|
| **Table 1** | 16 | C&I Deliverables by Project Phase and Issuance Status | Table region on p16, `asset_only` | **0** | `assets/pictures/page016-table000.png` |
| **Table 2** | **25** | Critical Interdisciplinary Data Exchange for C&I Engineering | Table region on **p26** (caption at foot of p25, body overleaf), `asset_only` | **0** | `assets/pictures/page026-table001.png` |
| **Table 3** | **23** | The Purpose and Necessity of C&I Installation Drawings | **No table region** — classified as a *picture* | **0** | `assets/pictures/page023-picture096.png` |

**Root cause, verified independently.** All three table bodies are raster images
with no text layer. On page 16, pdfminer finds no text between the footer
(y=38.2) and the caption (y=374.6); the entire body region is empty of text.
TableFormer therefore has nothing to match and returns zero cells. Confirmed the
same way for pages 23 and 26.

**How each is handled in the canonical Markdown** — an explicit warning block at
the table's exact reading-order position, followed by the preserved asset:

> **⚠ Unrecovered table — Table 1** (page 16). Docling located this table region
> but recovered no cells, because the table body is a raster image with no text
> layer. The region is preserved below as an image asset. **Its contents are not
> machine-readable and require human review or a targeted OCR pass.**

The gate `unrecovered_content_preserved` verifies on the artifacts themselves
that each region has both a written asset file and a visible Markdown warning.
It passes for both table regions.

**What was NOT done:** no OCR, no guessing, no fabricated cells. The Markdown
does not contain these tables' contents and does not pretend to.

---

## 9. Substantive picture findings

15 figures preserved with page and bounding-box provenance. All 15 asset files
verified present, non-blank and linked from the Markdown.

| Page | Asset | Size (px) | Page area | Owning section |
|---|---|---|---|---|
| 4 | `page004-picture016.png` | 1009×567 | 28.5% | §1.2–1.3 Standards / lifecycle phasing |
| 6 | `page006-picture023.png` | 860×668 | 28.6% | §2 IDE Process Flow — **conceptual design flow** |
| 8 | `page008-picture034.png` | 826×897 | 36.9% | §2.2 **FEED / feasibility gate flow** |
| 9 | `page009-picture038.png` | 855×861 | 36.7% | §2.3 **detailed engineering design flow** |
| 11 | `page011-picture048.png` | 793×949 | 37.5% | §2.4 **procurement / installation / integration flow** |
| 13 | `page013-picture053.png` | 511×655 | 23.6% | §2.5 final documentation / commissioning |
| 14 | `page014-picture054.png` | 1058×1070 | 56.4% | §3.1 **P&ID-style process/control graphic** |
| 16 | `page016-table000.png` | 790×453 | — | **Table 1 body** |
| 18 | `page018-picture071.png` | 781×527 | 20.5% | §4.2–4.3 **control-system architecture** |
| 20 | `page020-picture080.png` | 1031×619 | 31.8% | §5.1 **instrument location layout (GA)** |
| 21 | `page021-picture086.png` | 696×584 | 20.2% | §5.2 **pressure hook-up drawing** |
| 22 | `page022-picture090.png` | 1097×378 | 20.7% | §5.3–5.4 **loop wiring / cable block diagram** |
| 23 | `page023-picture096.png` | 980×637 | 31.1% | §6 — **Table 3 body** (as picture) |
| 26 | `page026-table001.png` | 953×441 | — | **Table 2 body** |
| 27 | `page027-picture113.png` | 920×232 | 10.7% | Conclusions — **QA / interdisciplinary workflow** |

Every visual-content category named in the acceptance brief is accounted for:
conceptual/FEED/detailed-design flows, procurement and commissioning flows, a
P&ID-style graphic, control-system architecture, instrumentation layout, hook-up
drawing, loop wiring, and the QA/interdisciplinary workflow.

**No machine-generated descriptions were produced.** Picture description is
disabled (ADR-005). Nothing in this report claims the diagrams' labels, symbols
or connections were recovered — that requires human confirmation via the review
cards under `validation/review/`.

---

## 10. Markdown and JSON quality

| Property | Result |
|---|---|
| Size | 35,216 bytes, 480 lines |
| Encoding | valid UTF-8, **0 CRLF**, 0 lone CR |
| Headings | 1 × H1, 11 × H2, 40 × H3, 24 × H4 — no level jumps |
| Page anchors | **27** (`<!-- page: N -->`), monotonic |
| Image links | **15, all resolve**, all relative POSIX |
| Base64 payloads | **0** |
| Absolute paths | **0** |
| Internal markers left | **0** |
| Mojibake (U+FFFD) | **0** |
| Furniture leakage (`Page N of 27`, `instrunexus`) | **0 / 0** |
| Acronyms preserved | `C&I` ×36, `P&ID` ×22, `P&IDs` ×16, `ISA` ×13, `I/O` ×13, `HAZOP` ×10, `FEED` ×9, `UFR` ×8, `SIL` ×7, `DCS` ×5, `PLC` ×4, `LOPA` ×4, `MTO` ×4, `MCC` ×2, `AVEVA` ×1, `AutoCAD` ×1, `SLD` ×1, `4-20 mA` ×1 |
| Section numbering | Preserved on all body headings (`1.1`…`6.4`) |
| JSON | parses; **reloads into `DoclingDocument`**; round-trip inventory identical |

`escape_html=True` (the serializer default) was corrupting `C&I` into `C&amp;I`
and `P&ID` into `P&amp;ID` — 35 and 22 occurrences respectively. Disabled.

### Determinism

Two consecutive runs on identical code and input:

```text
file count            : 210 = 210, identical set
byte-identical        : 205 / 210
differ by timestamp   : logs/run.jsonl, source/manifest.json,
                        validation/report.json, validation/report.md
run_manifest.json     : differs only in generated_at_utc, run_id, timings_s, and the
                        embedded hashes of those same four timestamp-bearing files
config_hash           : identical (83adcde3902fd350…)
source SHA-256        : identical
status                : identical (PASS_WITH_WARNINGS)
```

**Every deliverable is byte-identical**, verified individually:

| Artifact | Identical |
|---|---|
| `markdown/document.md` | yes |
| `markdown/document.raw.md` | yes |
| `docling/document.json` | yes |
| `validation/pages.csv` | yes |
| `assets/pictures/*.png` (15) | yes |
| `assets/pages/*.png` (27) | yes |
| `validation/review/*.html` (17) | yes |

The only variation is in fields that carry a timestamp or a duration by
definition. Verified with `docs/_generated/determinism_check.py`.

---

## 11. Acceptance gates

| # | Gate | Check | Result |
|---|---|---|---|
| 1 | Unchanged 27-page source | `source_unmodified`, `expected_page_count` | **PASS** |
| 2 | Successful non-empty conversion | `conversion_status` | **PASS** (`success`) |
| 3 | JSON validates and reloads | `json_parseable`, `json_reloads_into_model` | **PASS** |
| 4 | Markdown non-empty, portable, no broken assets | `markdown_encoding`, `markdown_non_empty`, `markdown_image_links`, `markdown_no_base64`, `markdown_no_placeholders` | **PASS** |
| 5 | Every page has provenance | `page_provenance_coverage`, `page_count_match`, `page_numbering_monotonic` | **PASS** (27/27) |
| 6 | Sparse/image-heavy pages reviewed | `visual_review_coverage` | **PASS** (17 cards) |
| 7 | Furniture excluded, with evidence | `decorative_assets_separated` + `furniture_removed` | **PASS** |
| 8 | Tables 1–3 located and individually reported | `labelled_tables_located` | **PASS** |
| 9 | No critical numeric/acronym loss | `document_text_completeness` | **PASS** (100%) |
| 10 | No unexplained missing span/page/table/picture | `unrecovered_content_preserved`, `substantive_figures_represented` | **PASS** |
| 11 | Tests pass | 201 tests (168 fast + 33 acceptance) | **PASS** |
| 12 | Report lists actual metrics | this document | **PASS** |

**19 / 19 gate-marked checks passed.**

### The 4 warnings

| Warning | Meaning | Judgement |
|---|---|---|
| `table_cells_recovered` | 2 detected regions yielded 0 cells | Source property; preserved + flagged. Gate `unrecovered_content_preserved` passes |
| `critical_token_recall` | Pages 1–2 page-local shortfall | TOC numbering; 100% at document level (§7.1) |
| `page_text_coverage` | Pages 18, 23 below 80% | Cross-page relocation; content conserved (§7.2) |
| `markdown_heading_structure` | 1 heading-level jump | `## A typical hook-up drawing specifies:` — a sentence Docling classified as a heading. Cosmetic |

---

## 12. Quality checks — actual results

```text
ruff check .                 All checks passed!
ruff format --check .        31 files already formatted
mypy src                     Success: no issues found in 17 source files
pytest -m "not slow"         168 passed, 33 deselected
pytest -m slow               33 passed, 168 deselected  (real 27-page PDF)
notebook execution           31 cells, 0 errors (nbclient)
nbformat.validate            valid nbformat 4.5, outputs cleared
```

Test suite: **201 tests** — unit (normalisation, config, artifacts, safe paths,
validation logic, exporters, preflight), package hygiene (no Docling imports
outside the isolation layer, no AGPL, notebook is a thin client), integration
(real Docling conversion on synthetic fixtures), and the slow full-document
acceptance suite encoding the 12 gates.

---

## 13. Human review required

Reproduced verbatim from `validation/report.json`:

1. **Table 1 (page 16)** — body is a raster image; Docling recovered 0 cells.
   Transcribe manually or run the OCR profile before relying on its content.
2. **Table 2 (page 26)** — same.
3. **Confirm figure content on pages 4, 6, 8, 9, 11, 13, 14, 16, 18, 20, 21, 22,
   23, 26, 27** — 15 engineering diagrams are preserved as image assets, but no
   automated check verifies that their labels, symbols or connections were
   recovered.
4. **Page 8** — 0 native body characters; completeness cannot be judged from
   text. Review the page rendering.
5. **Page 11** — same.

Not listed above but worth a look: **Table 3 (page 23)**, which Docling
classified as a picture rather than a table. Its body is preserved as
`assets/pictures/page023-picture096.png` and is equally not machine-readable.

---

## 14. Reproduction

```bash
# 1. Environment (Windows PowerShell; see README for Linux/macOS)
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision
python -m pip install -e ".[dev]"

# 2. Place the source document (never committed)
#    data/input/Instrumentation-and-Control-Engineering.pdf
#    sha256 = 01e4d6fa3a2e884f83fad507d08b228aa40f814dc0f3c44e6c9db315f73c3b1a

# 3. Preflight only (fast, no Docling)
engrag-parse inspect --input data/input/Instrumentation-and-Control-Engineering.pdf

# 4. Full run — THE command that produced this report
engrag-parse run --input data/input/Instrumentation-and-Control-Engineering.pdf \
                 --config configs/high_fidelity.yaml

# 5. Re-gate an existing run (CI)
engrag-parse validate --run artifacts/Instrumentation-and-Control-Engineering/<run-id> --strict

# 6. Quality suite
ruff check . && ruff format --check . && mypy src
pytest -m "not slow"
pytest -m slow
```

Expected: exit code **0**, status **`PASS_WITH_WARNINGS`**, ~4.5 minutes after
model weights are cached.

---

## 15. Readiness for chunking / vector search

**Ready, with three explicit constraints.**

Available now in the artifacts, with no reparsing required:

| Contract field | Location |
|---|---|
| document id | `run_manifest.json → source.sha256` |
| block id / type / heading path | `docling/document.json` (`self_ref`, `label`, element tree) |
| page number + bbox + charspan | every item's `prov[]` |
| table representation | `TableItem.data`, or `serialization: "asset_only"` |
| asset reference | `assets/pictures/*.png` |
| parser + config version | `parser_version`, `config_hash` |
| validation status / page severity | `validation/report.json` |

Full specification: [`productionization_options.md`](productionization_options.md#future-ingestion-contract).

**Constraints the next stage must respect:**

1. **Consume `document.json`, not the Markdown.** Markdown serialization
   flattens away bounding boxes, the element tree and content-layer labels —
   exactly the metadata that makes citation and structure-aware chunking work.
2. **Three tables carry no indexable text.** Do not embed their captions and
   present the result as if the tables were indexed. Exclude them or attach the
   asset and mark the chunk as requiring human reference.
3. **Page severity must travel with its chunks.** A retrieval hit from a page
   flagged `WARNING` or `needs_visual_review` should say so rather than being
   presented with the same confidence as clean body text. Treat content before
   the `<!-- page: 3 -->` anchor as a table of contents, not body prose.

Not implemented in this milestone, by design: chunking, embeddings, vector
store, retrieval, reranking.

---

## 16. Honest completeness statement

**Verified by measurement:** 27/27 pages parsed with provenance; source
unmodified; 100% document-level critical-token and word-type recall against an
independent baseline; 15/15 substantive figures represented and preserved;
3/3 labelled tables located and individually reported; Markdown portable with
zero broken links, base64, absolute paths, placeholders or furniture leakage;
JSON reloads with an identical inventory; byte-identical re-runs; 19/19 gates.

**Not verified, and not claimed:** that the engineering diagrams' labels,
symbols and connections were recovered; the contents of Tables 1, 2 and 3;
behaviour on Python 3.10–3.12, on GPU, with OCR enabled, or on scanned,
multi-column or non-Latin documents.

The status is `PASS_WITH_WARNINGS` rather than `PASS`, and that is the correct
answer for this document. A `PASS` here would require ignoring three
unrecoverable tables — which is exactly the silent success this project was
built to make impossible.
