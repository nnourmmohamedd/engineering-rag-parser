"""Vector-shape validation shared by every embedding-service implementation.

Kept as pure functions (no numpy dependency exposed in the public interface
beyond what's needed internally) so a fake test embedder can reuse the exact
same checks the production BGE implementation uses.
"""

from __future__ import annotations

import math

from .errors import VectorValidationError

__all__ = ["validate_vector"]


def validate_vector(
    vector: list[float],
    *,
    chunk_id: str | None,
    expected_dimension: int,
    normalize_expected: bool,
    norm_tolerance: float = 1e-3,
) -> None:
    """Validate one embedding vector: dimension, finiteness, non-zero, norm.

    Raises:
        VectorValidationError: with an actionable message naming ``chunk_id``
            (or ``"<query>"`` when embedding a query) and what failed.
    """
    label = chunk_id or "<query>"
    if len(vector) != expected_dimension:
        raise VectorValidationError(f"{label}: expected a {expected_dimension}-d vector, got {len(vector)}-d")
    if not all(math.isfinite(v) for v in vector):
        raise VectorValidationError(f"{label}: vector contains NaN or Inf")
    if all(v == 0.0 for v in vector):
        raise VectorValidationError(f"{label}: vector is all-zero")
    if normalize_expected:
        norm = math.sqrt(sum(v * v for v in vector))
        if abs(norm - 1.0) > norm_tolerance:
            raise VectorValidationError(f"{label}: L2 norm {norm:.6f} is not within {norm_tolerance} of 1.0")
