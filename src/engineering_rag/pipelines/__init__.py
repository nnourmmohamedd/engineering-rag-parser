"""Orchestration layer: coordinates services, owns no low-level parsing logic.

Allowed dependency direction: ``api -> pipelines -> services -> utils``.
A pipeline module may depend on one or more services and on ``utils``; it
must never be imported *by* a service (that would be a cycle) and must never
construct a Docling object, read PDF bytes, or otherwise duplicate work a
service already owns.
"""

from __future__ import annotations
