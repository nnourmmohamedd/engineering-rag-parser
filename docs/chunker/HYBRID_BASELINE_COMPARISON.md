# HybridChunker Baseline Comparison

**Purpose:** honest, reproducible evidence comparing this project's production
chunker (hierarchical-first, conditional recursive refinement) against
Docling's own `HybridChunker`, on the same real documents and the same
tokenizer. **The production strategy remains hierarchical + controlled
recursive splitting** — this comparison exists to document trade-offs, not to
justify replacing it.

Reproduce with:

```powershell
.\.venv\Scripts\python.exe scripts\chunker\compare_hybrid_baseline.py `
  --input "data\output\parser\Instrumentation-and-Control-Engineering\20260824T124235Z-01e4d6fa" `
  --output docs\chunker\_generated\engineering_pdf_baseline_comparison.json
```

Raw output for both documents: [`_generated/engineering_pdf_baseline_comparison.json`](_generated/engineering_pdf_baseline_comparison.json),
[`_generated/ocr_pdf_baseline_comparison.json`](_generated/ocr_pdf_baseline_comparison.json).

## Engineering PDF (27 pages, `01e4d6fa…`)

| Metric | Production (hierarchical + conditional recursive) | HybridChunker (baseline) |
|---|---:|---:|
| Total chunks | 117 | 76 |
| Content-type distribution | text 88, list 14, figure 13, table 2 | undifferentiated (76) |
| Token count — min / median / mean / p95 / max | 3 / 34 / 50.1 / 113 / 235 | 19 / 64.0 / 95.1 / 219 / 240 |
| Empty chunks | 0 | 0 |
| Oversized chunks, unflagged | 0 | 0 |
| Source elements represented | **185** | 170 |
| Heading-path preserved (fraction of chunks) | 86.3% | 98.7% |
| Duplicate-content chunks | 0 | 0 |
| Deterministic repeat run | ✅ yes | not evaluated (HybridChunker has no run-artifact identity to compare) |
| Processing time | 1.23 s | 0.22 s |

## OCR benchmark PDF (2 pages, `57f84fd5…`)

| Metric | Production | HybridChunker (baseline) |
|---|---:|---:|
| Total chunks | 9 | 8 |
| Content-type distribution | text 7, table 1, figure 1 | undifferentiated (8) |
| Token count — min / median / mean / p95 / max | 11 / 33 / 57.0 / 184 / 184 | 16 / 66.0 / 81.75 / 263 / **263** |
| Empty chunks | 0 | 0 |
| **Oversized chunks, unflagged** | **0** | **1** |
| Source elements represented | 24 | 23 |
| Heading-path preserved | 88.9% | 100% |
| Processing time | 1.18 s | 0.03 s |

## Findings

**Source-element representation.** Both documents show production
representing *more* source elements than HybridChunker (185 vs. 170; 24 vs.
23). The reason is structural, not a tuning difference: Docling's
`HierarchicalChunker` — which `HybridChunker` wraps internally — silently
drops any picture or table region that serializes to empty text (an
uncaptioned figure, or a raster table whose caption is plain nearby text
rather than a linked Docling caption item — exactly the acceptance
document's own Tables 1 and 2). `HybridChunker` inherits this gap unchanged.
Production's `type_handlers.figures`/`type_handlers.tables` explicitly
recover every such element from `doc.pictures`/`doc.tables` directly — see
`services/chunker/hierarchical.py`'s module docstring and
`MENTOR_EXPLANATION.md`.

**Unflagged overflow.** On the OCR document, `HybridChunker` produced one
chunk at 263 tokens against a configured `max_tokens=256` — 7 tokens over,
with no field marking it as such (Docling surfaces this only via a Python
`warnings.warn(...)` call, easy to miss in a batch job). Production's
`is_atomic_overflow` is a first-class, per-chunk output field: every
consumer of `chunks.jsonl` can filter or specially handle these chunks
without re-tokenizing to discover them. Production had zero unflagged
overflow chunks on both documents in this comparison.

**Content-type awareness.** `HybridChunker` produces text spans only — no
distinction between a table row-group, a list, code, or a figure. A
downstream chunking-aware reranker or a table-specific retrieval prompt has
nothing to key on. Production's `content_type` field, `table_metadata`
(fragment index/total, header-repeated), and `figure_asset_path` are
purpose-built for this.

**Chunk count and granularity.** Production produces more, smaller chunks
(mean 50 vs. 95 tokens on the engineering PDF). This follows from explicit
type-aware splitting (a table becomes N row-group chunks; a list becomes item
groups) rather than `HybridChunker`'s window-merging over raw doc-item
sequences. Neither granularity is objectively "better" — smaller chunks favor
precision (a query matches a narrower, more specific chunk) at some cost to
recall of multi-sentence context; this is a genuine trade-off documented
here, not a claim of superiority. `merge_small_chunks` (§ configuration) is
the tuning knob that trades chunk count for context size within production's
own strategy.

**Heading-path preservation** is slightly lower for production (86–89% vs.
99–100%) precisely because the recovered figures/tables (which the baseline
never emits at all) often have no Docling-linked heading context to inherit —
they carry their own caption/label instead. This is an honest trade-off:
those chunks exist and are searchable in production where they are entirely
absent from the baseline.

**Speed.** `HybridChunker` is 5–35x faster in this comparison — it does
strictly less work (no figure/table recovery, no per-type refinement, no
validation gate suite, no manifest/report generation). Both are fast in
absolute terms (well under 2 seconds) for documents of this size; this is not
a meaningful differentiator at this scale.

## Limitations of this comparison

- Two documents only (the two available real-document parser outputs in this
  repository). A larger, more diverse corpus would strengthen these
  conclusions but was out of scope for this pass.
- "Source elements represented" counts distinct `self_ref` values appearing
  in any output chunk; it is a coverage proxy, not a semantic-quality metric.
- No embedding or retrieval quality metric is computed here — see
  `docs/chunker/MENTOR_EXPLANATION.md` and the retrieval-readiness evaluation
  in `tests/integration/pipelines/test_retrieval_readiness.py` for that
  (lexical, not semantic) evidence instead.
