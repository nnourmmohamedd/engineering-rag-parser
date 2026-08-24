"""Orchestrates the chunker service: input validation → hierarchical chunking
→ type-aware refinement → merging → validation → artifact export.

Thin wrapper, mirroring :mod:`engineering_rag.pipelines.parsing_pipeline`:
``ChunkerService`` owns the actual sequence (chunker-domain behaviour); this
module is the stable entry point the CLI (and any future caller) uses.
"""

from __future__ import annotations

from pathlib import Path

from engineering_rag.services.chunker import ChunkerConfig, ChunkerRequest, ChunkerResult, ChunkerService

__all__ = ["run_chunking_pipeline"]


def run_chunking_pipeline(
    input_path: Path | str,
    config: ChunkerConfig,
    output_root: Path | str | None = None,
) -> ChunkerResult:
    """Run the chunking pipeline and return the outcome.

    Args:
        input_path: a ``document.json`` file, or a parser run directory
            containing ``docling/document.json``.
        config: effective chunker configuration.
        output_root: base directory for run artifacts. Defaults to
            ``config.output_root`` (``data/output/chunker``) when omitted.

    Raises:
        ChunkerInputError: if the input is inadmissible.
    """
    request = ChunkerRequest(
        input_path=Path(input_path),
        config=config,
        output_root=Path(output_root) if output_root is not None else None,
    )
    return ChunkerService().run(request)
