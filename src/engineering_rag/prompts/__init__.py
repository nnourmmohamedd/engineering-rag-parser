"""Prompt content for the project's LLM-facing stages.

Prompt text and structured-output schemas live under this package — never
inline in CLI or pipeline code — so a prompt/schema version bump is a
one-place change that automatically propagates into every consumer that
records it (run manifests, ``AnswerResponse``, logs, evaluation reports).
"""

from __future__ import annotations
