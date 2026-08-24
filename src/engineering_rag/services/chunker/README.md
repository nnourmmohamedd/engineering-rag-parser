# `services/chunker` — next milestone, not implemented

This package is an intentionally empty scaffold. No chunking logic exists
anywhere in this repository yet.

## Documented future contract

**Input:**

- validated `DoclingDocument` JSON (`data/output/parser/<document>/<run-id>/docling/document.json`);
- the source/run manifest (`run_manifest.json`);
- the validation report (`validation/report.json`);
- optional referenced visual assets (`assets/pictures/*.png`, `assets/pages/*.png`).

**Output** (`data/output/chunker/<document-name>/<run-id>/`):

- structure-aware chunks;
- chunk metadata;
- parent/child relationships;
- heading paths;
- page provenance;
- bounding-box provenance;
- asset references;
- validation severity carried over from the parser's findings;
- a chunk manifest.

## Why the parser's JSON, not its Markdown

`docling/document.json` is the canonical input for this milestone, not
`markdown/document.md`. The flattened Markdown drops per-item bounding boxes
and cannot reliably distinguish an `asset_only` table from body text without
regex-matching the warning blockquote the parser exporter injects. See
`docs/productionization_options.md#future-ingestion-contract` for the full
rationale, carried over unchanged from the parser milestone's own design
decisions.

## Expected shape when this milestone starts

Mirroring `services/parser/`: a `service.py` exposing `ChunkerService`,
`ChunkerRequest`, `ChunkerResult`; a `models.py` for chunk-domain types; a
`config.py` for chunking-specific configuration; and a
`pipelines/chunking_pipeline.py` orchestrating it, the same way
`pipelines/parsing_pipeline.py` orchestrates `services/parser`.
