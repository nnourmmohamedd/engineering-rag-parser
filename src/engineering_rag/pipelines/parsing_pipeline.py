"""Orchestrates the parser service end to end: input validation → preflight →
profile decision → parser service → export → validation → artifact
packaging → final run status.

This is the single entry point a CLI, a notebook or a future FastAPI worker
all call. It owns *no* low-level PDF or Docling extraction logic — that
belongs entirely to :mod:`engineering_rag.services.parser`, which this module
depends on. See ``docs/architecture/service_architecture.md`` for the
enforced dependency direction.

``run_parsing_pipeline`` used to be ``pipeline.run_pipeline``. Its behaviour
is unchanged: it builds a :class:`~engineering_rag.services.parser.ParserRequest`
and delegates the entire preflight-through-manifest sequence to
:class:`~engineering_rag.services.parser.ParserService`, which now owns that
sequence directly (see ``services/parser/service.py``).
"""

from __future__ import annotations

from pathlib import Path

from engineering_rag.services.parser import ParserConfig, ParserRequest, ParserResult, ParserService
from engineering_rag.utils.paths import default_parser_output_root

__all__ = ["run_parsing_pipeline"]


def run_parsing_pipeline(
    pdf_path: Path | str,
    config: ParserConfig,
    output_root: Path | str | None = None,
) -> ParserResult:
    """Run the parsing pipeline and return the outcome.

    Args:
        pdf_path: source PDF to parse.
        config: effective parser configuration.
        output_root: base directory for run artifacts. Defaults to
            :func:`engineering_rag.utils.paths.default_parser_output_root`
            (``data/output/parser``) when omitted.

    Raises:
        PreflightError: if the input is inadmissible.
        ConversionFailedError: if Docling returns no usable document.
    """
    resolved_root: Path = Path(output_root) if output_root is not None else default_parser_output_root()
    request = ParserRequest(pdf_path=Path(pdf_path), config=config, output_root=resolved_root)
    return ParserService().run(request)
