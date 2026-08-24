"""Public interface of the chunker service.

Preferred surface: :class:`ChunkerService`, :class:`ChunkerRequest`,
:class:`ChunkerResult`, :class:`ChunkerConfig`, :func:`load_config`,
:class:`ChunkerInputError`, :data:`CHUNKER_VERSION`. Internal modules
(``hierarchical``, ``recursive``, ``type_handlers.*``, ``merging``,
``finalize``, ``validation``, ``loader``, ``tokenizer``, ``artifacts``)
remain importable directly — tests exercise them individually — but callers
outside this package should prefer this module.

Consumes the parser's canonical ``document.json`` output
(:mod:`engineering_rag.services.parser`) and never the reverse — this
package must not be imported by ``services/parser``.
"""

from __future__ import annotations

from engineering_rag import __version__

__all__ = [
    "CHUNKER_VERSION",
    "ChunkerConfig",
    "ChunkerInputError",
    "ChunkerRequest",
    "ChunkerResult",
    "ChunkerService",
    "load_config",
]

#: Bumped whenever chunking semantics change in a way that would alter
#: artifacts for identical input+config. Recorded in every chunk manifest.
CHUNKER_VERSION = __version__

from .config import ChunkerConfig, load_config  # noqa: E402
from .loader import ChunkerInputError  # noqa: E402
from .service import ChunkerRequest, ChunkerResult, ChunkerService  # noqa: E402
