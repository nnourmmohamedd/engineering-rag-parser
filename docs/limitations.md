# Limitations

An honest account of what this parser does not guarantee. Everything here was
observed on the actual acceptance run, not anticipated in the abstract.

## The headline limitation

**No general-purpose PDF parser can guarantee recovery of every visual and
semantic relationship, and this one does not claim to.** A successful conversion
and readable Markdown are not evidence of accuracy. The status vocabulary
(`PASS` / `PASS_WITH_WARNINGS` / `FAIL`) describes *auditable extraction
quality*, not correctness of interpretation.

---

## 1. Three tables are not machine-readable — confirmed, not suspected

**Observed.** Tables 1, 2 and 3 all have **raster image bodies with no text
layer**. Verified independently with pdfminer: on page 16 there is no text
between y=38 (footer) and y=374 (the caption) — the entire table body region is
empty of text. The same holds for pages 23 and 26.

**Consequence.** TableFormer detects the regions but recovers **0 cells**. The
table contents cannot be searched, chunked or embedded.

**What the parser does instead.** Preserves each region as a PNG asset, emits an
explicit warning block in the Markdown at the table's exact reading-order
position, records a `CRITICAL`-severity finding per table, and lists each one
under "Human review required". A gate (`unrecovered_content_preserved`) fails
the run if any such region lacks either the asset or the warning.

**What it does not do.** It does not OCR them by default, and it does not guess
their contents. Docling's own Markdown serializer drops zero-cell tables
*entirely* — caption followed by silence — which is the silent loss this
parser exists to prevent.

**Recovery options**, in order of preference:
1. Obtain the tables from their authoring source.
2. Transcribe manually from `assets/pictures/page016-table000.png` and
   `assets/pictures/page026-table001.png`.
3. Run a targeted OCR pass and label the result **OCR-derived**, never merging
   it with native text.

## 2. Diagram semantics are unverified

15 engineering diagrams are preserved as referenced PNG assets with page and
bounding-box provenance: process flows, a P&ID-style control graphic,
control-system architecture, an instrumentation layout, a hook-up drawing, a
loop wiring diagram, and a QA/interdisciplinary workflow.

**No automated check in this project confirms that their labels, symbols or
connections were recovered.** Text metrics are irrelevant to them: a page of
pure diagram scores 1.00 on every text metric while conveying nothing.

The parser flags all 15 pages for visual review and generates an HTML card per
page with the source rendering and parsed bounding-box overlay. Whether the
diagram content is intact is a human judgement, and the report says so.

## 3. Machine-generated picture descriptions are disabled

Local VLM picture description is available (`picture_description.enabled`) but
**off by default** (ADR-005). On a P&ID or a loop wiring diagram, a plausible
but wrong caption is more dangerous than no caption: it reads as extracted fact.

If enabled, output is labelled a machine annotation, never replaces the picture
asset or its provenance, and is **not** evidence that diagram content was
recovered.

## 4. Table-of-contents entries lose their leading numbers

**Observed.** With `enable_heading_hierarchy: true`, TOC list items on pages 1–2
are promoted to headings and lose their leading `1.3`, `2.2`, … markers. This is
why pages 1 and 2 show ~50% page-local critical-token recall.

**Why it is accepted.** The numbers are not lost from the document — every real
body heading retains its number (`1.3 Project Lifecycle Phasing…` on page 5), and
`document_text_completeness` confirms 100% document-wide token recall. The TOC
is navigational furniture duplicating structure that exists elsewhere.

**The trade-off.** Disabling `enable_heading_hierarchy` preserves the TOC markers
but flattens all 76 headings to a single level, which is materially worse for
downstream section-aware chunking. Correct H1→H4 nesting was judged more
valuable than numbering on a duplicate navigation block.

## 5. The table of contents is serialized as headings

Pages 1–2 render as a block of headings duplicating the body structure. It is
faithful to the source but means the Markdown contains ~30 headings before the
document proper begins.

**Downstream implication.** Chunking should treat content before the first
`<!-- page: 3 -->` anchor as an index, not as body content.

## 6. Cross-page paragraphs are attributed to their starting page

Docling assembles a paragraph spanning a page break and gives it the provenance
of where it **starts** — correct reading-order repair, but it means a citation
to "page 23" may point to a paragraph whose text is visible at the top of page
23 while its `prov` says page 22.

Measured effect: pages 18 and 23 show 0.62/0.65 character coverage; pages 17 and
22 show 1.15/1.21. Content is conserved. The report labels these `relocated`
rather than `missing`, and the ±1-page detection window means content moved
further than one page is only caught by the document-level gate.

## 7. `document_timeout` produces a partial parse, not a clean failure

If Docling hits the timeout it may return `PARTIAL_SUCCESS`. The pipeline
detects this, marks the run `FAIL`, and quarantine routing exists in
`RunDirectory.create(quarantine=True)`. **This path has not been exercised on a
real timeout** — it is tested only by construction.

## 8. The independent baseline has its own failure modes

- pdfminer emits `(cid:NNN)` for glyphs without a Unicode mapping. These are
  stripped from both sides of every comparison — they are extractor artifacts,
  not content — but the stripping is a heuristic.
- A systematic mis-decode in the source (a broken embedded font) would fool
  pdfminer and Docling identically, and the comparison would report agreement.
- The baseline is single-column-oriented. On a genuinely multi-column document,
  pdfminer's reading order and Docling's would differ legitimately and coverage
  metrics would need reinterpreting. The acceptance document is single-column.

## 9. Furniture removal is evidence-based but not infallible

A line is removed only when it repeats in a header/footer band on ≥50% of pages.
A genuine body line meeting that description would be removed. Every removal is
recorded in `validation/report.json → furniture_removed` with its occurrence
count, and `markdown/document.with-furniture.md` retains the unstripped version.

## 10. Verified on one platform, one document

All measurements come from Windows 11 / Python 3.13.9 / CPU-only torch, on a
single 27-page document. `requires-python = ">=3.10,<3.14"` is declared and the
package is import-clean, but **3.10–3.12 have not been executed**. Behaviour on
scanned documents, multi-column layouts, rotated pages at scale, CJK text or
100+ page documents is untested beyond the synthetic fixtures.

## 11. GPU and OCR paths are configured but unexercised

- `accelerator_device: cuda` is implemented and never run: the local MX450 has
  2 GB VRAM and CPU-only torch is installed (`torch.cuda.is_available() == False`).
- The `scanned` profile and EasyOCR integration are implemented, and OCR option
  construction is unit-tested, but **no OCR conversion has been executed** —
  `easyocr` is not installed in the verified environment.

Both are documented as available, not as validated.

## 12. Determinism excludes timestamps by construction

Byte-identical re-runs are verified with the run timestamp, `generated_at_utc`
and `timings_s` excluded. Those fields vary by definition. Model inference is
deterministic on CPU for a fixed input; a GPU run may differ in low-order
floating-point detail and has not been checked.

## 13. Defects found by `PROJECT_COMPLETION_AUDIT.md` and their disposition

The audit (2026-08-24) found six previously undocumented defects (D-1…D-6),
none of which invalidated the parsing result. All six were fixed and are
covered by regression tests; see `PARSER_STAGE_FINAL_REPORT.md` for the full
evidence table.

| ID | Defect | Fix |
|---|---|---|
| D-1 | `pip install -e ".[dev]"` was broken (`dev` only existed as a PEP 735 dependency group, not an extra) | `dev` is now also declared under `[project.optional-dependencies]`; both installation paths work |
| D-2 | `run_manifest.json` recorded `table_structure_options: {}` even though the runtime object was fully configured | `describe_effective_options()` now re-serialises `table_structure_options`/`ocr_options`/`picture_description_options` from the live objects, by concrete class |
| D-3 | `docling/document.json` image URIs used Windows backslash separators, unresolvable on POSIX | `save_document_json()` post-processes and re-validates the file; a `json_portable_paths` gate now checks it on every run |
| D-4 | The final report named the older of two byte-identical final runs | Superseded: a new final run is produced and named unambiguously in `PARSER_STAGE_FINAL_REPORT.md` |
| D-5 | Table 3 (detected as a picture, not a table region) was not covered by the no-silent-loss gate | `flag_table_only_pictures()` marks such pictures; `unrecovered_content_preserved` now covers both table-region and picture-region unrecovered tables |
| D-6 | List-type inventory disagreed with the Markdown (41 "ordered" vs 31 rendered bullets) | `build_inventory()` now reads `ListItem.enumerated` — the same field the Markdown serializer consults — instead of guessing from the marker string |

## 14. `scanned` profile remains experimental in this environment

**Unchanged by this pass.** `easyocr` is a ~100 MB optional dependency
(`pip install -e ".[ocr]"`) that was deliberately not installed, to avoid an
unjustified heavy download for a milestone whose acceptance document does not
need OCR (it has a clean, complete native text layer). Consequently:

- OCR **option construction** is unit-tested (`test_scanned_enables_full_page_ocr`).
- An actual OCR **conversion** — the thing that would prove the `scanned`
  profile works, not just that it builds a valid options object — has never
  been executed in this repository.
- `choose_profile()`'s decision to route an image-only document to `scanned`
  is exercised only against a synthetic image-only fixture, not a real scan.

Treat `scanned`/OCR support as **implemented but unproven**, not as validated.
The CLI does not claim otherwise: it warns clearly when `do_ocr` is requested
but no OCR engine is importable in the environment, rather than silently
falling back or claiming success.

---

## What is genuinely solid

For balance, the claims that *are* backed by measurement on the final run:

- 27/27 pages parsed, all with provenance; source SHA-256 unchanged.
- 100% document-level critical-token recall and 100% word-type recall against
  the independent baseline.
- All 15 substantive figures represented and preserved as assets; 54 decorative
  furniture instances correctly excluded from the body.
- All 3 labelled tables located from native text, with page, title and outcome
  reported individually.
- Markdown: valid UTF-8/LF, 0 broken links, 0 base64, 0 absolute paths, 0
  placeholders, 0 furniture leakage.
- JSON reloads into the current `DoclingDocument` with an identical inventory.
- 19/19 acceptance gates pass.
