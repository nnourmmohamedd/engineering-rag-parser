"""Typed exceptions raised by the grounding-validation service."""

from __future__ import annotations

__all__ = ["GroundingError"]


class GroundingError(Exception):
    """Base class for every grounding-validation failure."""
