"""Generic, service-agnostic helpers shared across the whole application.

Nothing here may import from :mod:`engineering_rag.services`,
:mod:`engineering_rag.pipelines` or :mod:`engineering_rag.api` — this
package sits at the bottom of the dependency graph (``api -> pipelines ->
services -> utils``) so every other package can depend on it without risking
a cycle.
"""

from __future__ import annotations
