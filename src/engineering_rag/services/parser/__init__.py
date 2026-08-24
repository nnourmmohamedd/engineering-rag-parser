"""Public interface of the parser service.

Preferred surface: :class:`ParserService`, :class:`ParserRequest`,
:class:`ParserResult`, :class:`ParserConfig`, :class:`Profile`,
:func:`load_config`, :class:`PreflightError`, :class:`ConversionFailedError`,
:data:`PARSER_VERSION`. Internal modules (``converter``, ``inventory``,
``profiles``, ``exporters``, ``artifacts``, ``preflight``, ``normalization``,
``validation.*``) remain importable directly — tests exercise them
individually — but callers outside this package should prefer this module.
"""

from __future__ import annotations

from engineering_rag import __version__

__all__ = [
    "PARSER_VERSION",
    "ConversionFailedError",
    "ParserConfig",
    "ParserRequest",
    "ParserResult",
    "ParserService",
    "PreflightError",
    "Profile",
    "load_config",
]

#: Bumped whenever parsing/normalisation/validation semantics change in a way
#: that would alter artifacts for an identical input+config. Recorded in
#: every run manifest so downstream stages can detect stale artifacts.
PARSER_VERSION = __version__

from .config import ParserConfig, Profile, load_config  # noqa: E402
from .converter import ConversionFailedError  # noqa: E402
from .preflight import PreflightError  # noqa: E402
from .service import ParserRequest, ParserResult, ParserService  # noqa: E402
