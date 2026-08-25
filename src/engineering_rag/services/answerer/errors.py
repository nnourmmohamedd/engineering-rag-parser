"""Typed exceptions raised by the answerer service."""

from __future__ import annotations

__all__ = ["AnswererError", "MalformedModelOutputError"]


class AnswererError(Exception):
    """Base class for every answerer-service failure."""


class MalformedModelOutputError(AnswererError):
    """Raised internally when the model's output cannot be parsed as the required JSON schema.

    Always caught inside :class:`~.service.GroundedAnswerService` and turned
    into a ``generation_failed`` :class:`~.models.AnswerResponse` (after the
    single allowed repair attempt, if configured) -- never propagated to the
    CLI as a raw exception.
    """
