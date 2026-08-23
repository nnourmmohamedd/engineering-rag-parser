# Validation methodology

## The claim this framework can and cannot make

It **can** say: *these specific measurements, taken against an independent
baseline, show this much text survived, these figures are represented, these
items could not be machine-read, and these pages need a human.*

It **cannot** say: *the extraction is 100% accurate.* No general-purpose PDF
parser can. The framework is built so that the difference between those two
statements is visible in the output rather than hidden by it.

## Design principles

### 1. The baseline must be independent

Preflight measures the source with **pypdf + pdfminer.six + pypdfium2**. Docling
never contributes to the baseline. A validator that compares Docling's output to
Docling's own reading of the file measures self-consistency, not correctness,
and will report ~100% on a document it has mangled.

### 2. One number is not evidence

A single character ratio is easy to satisfy and easy to be fooled by:

- Header/footer removal and reading-order repair change it in both directions.
- An image-heavy page scores 1.00 while conveying nothing, because *both sides
  agree there is little text*.
- A page can keep 97% of its characters and lose every instrument tag.

So each page carries `char_coverage`, `token_jaccard`, `token_recall`,
`critical_token_recall`, relocation lists, missing spans, duplicated spans, and
figure counts — and low scores are surfaced per page, never averaged away.

### 3. Comparisons must be like-for-like

The canonical body deliberately excludes page headers and footers. Comparing it
against a native baseline that still contains `www.example.com  Page 16 of 27`
reports the page's own page number as lost content — and fails every page in the
document.

**This was a real defect during development.** The first full run produced
critical-token failures on 24 of 27 pages, all of them the footer's page number.
The fix (`strip_furniture()`) removes proven furniture from *both* sides, and
records `furniture_chars_excluded` per page so the exclusion is auditable rather
than invisible.

### 4. Relocation is not loss

Docling attributes a paragraph crossing a page break to the page where it
**starts**. That is correct reading-order repair. A naive per-page comparison
reports it as loss on the following page.

**This was the second real defect.** Pages 18 and 23 appeared to have lost whole
paragraphs — including `AVEVA`, `E&I`, `I-CAD`. Checking the document as a whole
showed every one of those tokens present, attributed to pages 17 and 22 where
the paragraphs begin.

The framework therefore runs two different checks:

| Check | Scope | Severity | Question |
|---|---|---|---|
| `critical_token_recall` | page, ±1 neighbour | **WARNING** | Is this token on the page I expected? |
| `document_text_completeness` | whole document | **CRITICAL gate** | Is this token anywhere at all? |

Only the second can fail a run. Page-local attribution is a provenance nuance;
document-level absence is a defect.

### 5. Thresholds are policy, and must be visible

Every threshold lives in `ValidationThresholds` with a docstring, is written
into `run_manifest.json`, and is echoed in each check's `threshold` field. A
reviewing engineer can see and challenge them without reading the checkers.

Text-quality thresholds engage only where there is enough text to judge
(`source_chars >= sparse_text_char_threshold`, default 200). Below that, the page
is governed by visual review — that is how a page of pure diagram avoids being
scored on the two words in its caption.

### 6. Visual content is never signed off by a number

A page is flagged for review when it carries **any** non-repeated image, is
sparse, or is empty. Flagging is driven by **presence, not area**.

**This mattered concretely.** With the 25%-of-page area threshold, pages 13, 16,
22 and 27 fell below the line — each holding a real engineering diagram. Under a
purely area-based rule those four would have passed unreviewed. Presence-based
flagging catches all 15.

## What each check proves

### File and page integrity

| Check | Gate | Proves | Does **not** prove |
|---|---|---|---|
| `source_unmodified` | ● | Input SHA-256 identical after the run | — |
| `expected_page_count` | ● | Parsed page count equals source | Page *content* is right |
| `page_count_match` | ● | Every source page appears in coverage | — |
| `page_numbering_monotonic` | ● | No duplicated or reordered pages | — |
| `page_provenance_coverage` | ● | Every page has at least one item with `prov` | The page is *complete* |
| `conversion_status` | ● | Docling returned `SUCCESS`, not `PARTIAL_SUCCESS` | — |

### Text coverage

| Check | Gate | Proves | Does **not** prove |
|---|---|---|---|
| `document_text_completeness` | ● | No number, unit or acronym absent document-wide | It landed on the right page |
| `critical_token_recall` | — | Page-local token attribution | — |
| `page_text_coverage` | — | Text-bearing pages retain their volume | Semantics survived |
| `no_duplicated_spans` | — | No span repeats — the signature of OCR merged over embedded text | — |

**Critical tokens** are extracted from *raw* text before any lossy folding:
numbers, unit-bearing quantities (`4-20 mA`, `100 kPa`), and acronyms/instrument
tags (`P&ID`, `FT-101`, `ISA-5.1`). Case is preserved — `PID` and `pid` are
different claims in an instrumentation document. Mixing the aggressive
comparison normaliser into token extraction is precisely how a validator reports
99% coverage while dropping every tag, so the two are separate functions and the
split is enforced by unit tests.

### Structure coverage

| Check | Gate | Proves |
|---|---|---|
| `headings_present` | ● | A heading structure exists at all |
| `substantive_figures_represented` | ● | Every non-repeated source figure has a Docling region |
| `heading_hierarchy_consistent` | — | No skipped heading levels |
| `toc_sections_recovered` | — | Outline section *numbers* appear as headings |
| `captions_attached` | — | No caption orphaned from its object |
| `decorative_assets_separated` | — | Furniture distinguished from diagrams, with evidence |

`toc_sections_recovered` compares **numbering**, never extracted wording —
otherwise a whitespace or dash difference fails a check about structure.

### Tables

| Check | Gate | Proves |
|---|---|---|
| `labelled_tables_located` | ● | Every `Table N:` caption found in **native text** is reported with page, title and outcome |
| `unrecovered_content_preserved` | ● | Every zero-cell region has a written asset **and** a visible Markdown warning |
| `table_cells_recovered` | — | Detected regions yielded cells |
| `table_cell_density` | — | Recovered tables are not mostly empty |
| `no_single_cell_tables` | — | No callout box misread as a table |

The gate/warning split is deliberate. Zero cell recovery is a property of the
*source* — a table drawn as a raster image has no text to recover, and that is
not a parser defect. What is unacceptable is that such a table **disappears
quietly**. `unrecovered_content_preserved` therefore checks the artifacts
themselves: the asset file exists on disk and the warning text is present in the
Markdown.

Table labels are located from native PDF text rather than from
`document.tables`, because on the acceptance document Docling detects only two
table regions and classifies the third as a picture. Trusting `document.tables`
would have silently under-reported.

### Visual coverage

| Check | Gate | Proves | Does **not** prove |
|---|---|---|---|
| `visual_review_coverage` | ● | Every flagged page has a review artifact | Anyone looked at it |
| `visual_content_not_text_verified` | — (INFO) | States plainly that diagram content is unverified | — |

The second check always "passes" and exists to put the limitation in the report
rather than leave it implicit. **No automated check in this framework confirms
that a P&ID's labels, symbols or connections were recovered.**

### Markdown and JSON QA

Run against the **files on disk**, not in-memory objects — a validator that
inspects the object graph can pass while the artifact is broken.

| Check | Gate | Proves |
|---|---|---|
| `markdown_encoding` | ● | Valid UTF-8, LF endings |
| `markdown_non_empty` | ● | Substantial content |
| `markdown_image_links` | ● | Every link resolves and is relative |
| `markdown_no_base64` | ● | No embedded payloads |
| `markdown_no_placeholders` | ● | No internal marker survived substitution |
| `json_parseable` | ● | The JSON is valid |
| `json_reloads_into_model` | ● | It reloads into the current `DoclingDocument` |
| `json_roundtrip_stable` | — | Inventory identical after reload |
| `markdown_semantic_retention` | — | Markdown kept the JSON's headings |
| `markdown_table_consistency` | — | Pipe tables are rectangular |
| `markdown_character_hygiene` | — | No control characters or mojibake |

## Status derivation

```text
any CRITICAL check failed            -> FAIL                  (exit 1)
any WARNING check failed, strict     -> FAIL                  (exit 1)
any WARNING check failed, non-strict -> PASS_WITH_WARNINGS    (exit 0)
otherwise                            -> PASS                  (exit 0)
```

`INFO` checks never affect status.

`PASS_WITH_WARNINGS` is the *expected honest outcome* for a document containing
raster tables and engineering diagrams. Treating it as a lesser `PASS` misreads
it: it means every gate held and specific, listed items need a person.

## Determinism

Re-running the same input with the same config must produce byte-identical
artifacts, excluding legitimately varying fields: the run directory timestamp,
`generated_at_utc`, and `timings_s`. `config_hash` and the source SHA-256 must
match exactly. The comparison procedure is in
[`FINAL_IMPLEMENTATION_REPORT.md`](FINAL_IMPLEMENTATION_REPORT.md).

## Known blind spots

Stated plainly, because a methodology document that only lists strengths is
marketing:

1. **Diagram semantics are unverified.** Figures are preserved as assets with
   provenance. Whether a loop wiring diagram's connections survived is a human
   judgement.
2. **Reading order is checked structurally, not semantically.** Nothing verifies
   that two adjacent paragraphs belong together.
3. **The baseline has its own failure modes.** pdfminer emits `(cid:NNN)` for
   glyphs without a Unicode mapping; those are stripped from both sides, but a
   systematic mis-decode in the source would fool both tools identically.
4. **Furniture removal is evidence-based but not infallible.** A genuine body
   line appearing in the header band on more than half the pages would be
   removed. Every removal is logged in `furniture_removed`.
5. **Cross-page relocation uses a ±1-page window.** Content moved further than
   one page is reported as page-local missing and caught only by the
   document-level gate.
