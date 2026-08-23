# Productionization options

## The decision

**Installable Python package + CLI/batch runner.** Option 2 below.

The milestone needs a reusable, auditable upstream parser that a later RAG
pipeline consumes. It does not yet need concurrency, an API surface, or
infrastructure — and every piece of infrastructure added now is a piece that has
to be operated before it earns anything.

## Options compared

| Criterion | 1. Notebook / script | **2. Package + CLI** | 3. API service + workers | 4. Event-driven ingestion |
|---|---|---|---|---|
| **Reproducibility** | Poor — hidden cell-order state | **Strong** — pinned deps, config hash, immutable runs | Strong | Strong |
| **Maintainability** | Poor — untestable, untyped | **Strong** — typed, linted, 201 tests | Moderate — service + parser | Weaker — most moving parts |
| **Throughput** | One document, manually | Sequential; parallel by batching files | High — horizontal workers | Highest — autoscaling |
| **Isolation** | None | Process-level | Container per worker | Container + queue isolation |
| **Retries / idempotency** | Manual | Deterministic re-run; content-addressed runs | Queue-level retry | Native (DLQ, visibility timeout) |
| **Observability** | Cell output | JSONL log, run manifest, validation report | + metrics, tracing | + queue depth, per-stage SLOs |
| **Scaling** | None | Vertical | Horizontal | Elastic |
| **Deployment complexity** | Trivial | **Low** — `pip install` | Moderate — service, queue, orchestration | High — storage, queue, IaC, autoscaling |
| **Security** | Runs wherever the notebook runs | **Local-only; no network in default path** | Network surface, authn/authz | + bucket policies, IAM, encryption |
| **Cost** | ~0 | ~0 | Always-on compute | Pay-per-use + platform overhead |
| **Fit for engineering-doc RAG** | Prototype only | **Strong for batch corpus ingestion** | Good for on-demand upload | Good at large scale |

### 1. Notebook / script prototype

Fastest to a first result and genuinely useful for exploration. Rejected as the
deliverable: notebook state is invisible, cell order is not reproducible, and
nothing is testable. The notebook is retained as a *diagnostic client* of the
package, and a test fails the build if parsing logic reappears in it.

### 2. Installable package + CLI — **selected**

Concretely, for an engineering-document corpus:

- Documents arrive in batches (a project handover, a vendor package), not as a
  real-time stream. Batch throughput on 4 cores is adequate; the bottleneck is
  human review of flagged pages, not conversion.
- Reproducibility beats latency. `config_hash` + source SHA-256 + immutable run
  directories mean a result from six months ago can be re-derived and diffed.
- The confidential input never leaves the machine — no network surface at all.
- Boundaries are already service-shaped: `run_pipeline()` is a pure
  function of `(path, config, artifacts_base)`. A FastAPI handler or a Celery
  task is a wrapper, not a rewrite.

### 3. Internal API service + worker queue

The right next step *when* on-demand upload or multi-user access is needed. It
adds a service to operate, an auth story, and queue semantics — none of which
this milestone requires. Deferred deliberately.

### 4. Event-driven ingestion (object storage → queue → workers)

The right architecture at genuine scale (thousands of documents, elastic load).
It also puts confidential documents into shared storage, which needs a security
review this project has not had. Premature by a wide margin.

## Migration path

The boundary is already drawn, so growing into option 3 is additive:

```python
# Future FastAPI adapter — no parsing code changes.
@app.post("/parse")
async def parse(file: UploadFile, profile: str = "high_fidelity"):
    path = save_to_scratch(file)  # new
    config = load_config(f"configs/{profile}.yaml")  # existing
    result = run_pipeline(path, config, ARTIFACTS_ROOT)  # existing, untouched
    return {
        "status": result.status.value,
        "run_id": result.run_dir.name,
        "review_items": result.report.human_review_items,
    }
```

What would still need building: request auth, upload size limits at the edge
(the parser's own limits already exist), a job store, and artifact retention.
None of it touches `src/engineering_rag_parser/`.

## On Docker

Not provided. A Dockerfile here would be a *substitute* for local setup rather
than an addition to it — the venv path is documented, tested and works — and it
would need maintaining against a ~2.5 GB torch layer for no current consumer.
When option 3 arrives it becomes worthwhile, and should then be multi-stage,
non-root, with model weights baked into a cached layer so containers start
offline.

---

## Future ingestion contract

**Not implemented in this milestone.** No chunking, embeddings, vector store,
retrieval or reranking. This section specifies what the *next* stage consumes so
it never has to reparse the PDF.

Everything below already exists in the artifacts.

| Field | Source | Notes |
|---|---|---|
| `document_id` | `run_manifest.json → source.sha256` | Content-addressed. Same bytes ⇒ same id, across machines. |
| `source_filename` | `run_manifest.json → source.filename` | Display only; never an identity. |
| `block_id` | `document.json → item.self_ref` (e.g. `#/texts/42`) | Stable within a document version. |
| `block_type` | `item.label` | `section_header`, `text`, `list_item`, `table`, `picture`, `caption`, … |
| `heading_path` | Ancestor chain in the element tree | e.g. `["Section 4: …", "4.2 Input/Output (I/O) Lists"]`. Derive by walking `parent`. |
| `page_no` | `item.prov[0].page_no` | 1-based. |
| `bbox` | `item.prov[0].bbox` | `(l, b, r, t)`, `CoordOrigin.BOTTOMLEFT`. Enables click-to-source citation. |
| `charspan` | `item.prov[0].charspan` | Offsets within the item's text. |
| `text` | `item.text` | Original casing, acronyms and units preserved. |
| `table_repr` | `TableItem.data` → `export_to_markdown()` / `export_to_html()` | **Or `serialization: "asset_only"`** when cells were not recoverable. |
| `asset_ref` | `validation/report.json → pictures[].asset_path` | Relative POSIX path inside the run directory. |
| `content_layer` | `item.content_layer` | Skip `FURNITURE` when chunking body content. |
| `parser_version` | `run_manifest.json → parser_version` | Invalidate a cache when parsing semantics change. |
| `config_version` | `run_manifest.json → config_hash` | Same document + different config ⇒ different chunks. |
| `validation_status` | `validation/report.json → status` | **Do not index a `FAIL` run.** |
| `page_severity` | `report.json → page_coverage[].severity` | Down-weight or quarantine `CRITICAL` pages. |
| `needs_human_review` | `report.json → human_review_items` | Surface in retrieval results touching those pages. |

### Consume the JSON, not the Markdown

Structure-aware chunking should read `docling/document.json` directly. The
Markdown is a human deliverable; serializing to it **flattens away** the element
tree, per-item bounding boxes, content-layer labels and table cell structure —
exactly the metadata that makes citation and structure-aware chunking possible.
Round-tripping through Markdown discards it and cannot recover it.

### Three constraints the next stage must respect

1. **An `asset_only` table has no machine-readable content.** Do not embed its
   caption and present it as if the table were indexed. Either exclude it, or
   attach the asset and mark the chunk as requiring human reference.
2. **Figures carry no extracted semantics.** A picture asset is evidence, not
   text. If diagram content must be searchable, that is a separate, explicitly
   labelled OCR/VLM stage whose output is annotation — never conflated with
   extracted source text.
3. **A page's severity travels with its chunks.** A retrieval hit from a page
   flagged `CRITICAL` or `needs_visual_review` should say so, rather than
   presenting uncertain content with the same confidence as clean body text.
