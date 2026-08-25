"""Vector validation gate tests: dimension, NaN/Inf, zero, norm tolerance."""

from __future__ import annotations

import math

import pytest

from engineering_rag.services.embedder.errors import VectorValidationError
from engineering_rag.services.embedder.validation import validate_vector


def _unit_vector(dim: int = 768) -> list[float]:
    return [1.0] + [0.0] * (dim - 1)


class TestValidateVector:
    def test_valid_normalized_vector_passes(self) -> None:
        validate_vector(_unit_vector(), chunk_id="c1", expected_dimension=768, normalize_expected=True)

    def test_wrong_dimension_rejected(self) -> None:
        with pytest.raises(VectorValidationError, match="768-d"):
            validate_vector([0.1] * 10, chunk_id="c1", expected_dimension=768, normalize_expected=False)

    def test_nan_rejected(self) -> None:
        v = _unit_vector()
        v[5] = math.nan
        with pytest.raises(VectorValidationError, match="NaN or Inf"):
            validate_vector(v, chunk_id="c1", expected_dimension=768, normalize_expected=False)

    def test_inf_rejected(self) -> None:
        v = _unit_vector()
        v[5] = math.inf
        with pytest.raises(VectorValidationError, match="NaN or Inf"):
            validate_vector(v, chunk_id="c1", expected_dimension=768, normalize_expected=False)

    def test_all_zero_rejected(self) -> None:
        with pytest.raises(VectorValidationError, match="all-zero"):
            validate_vector([0.0] * 768, chunk_id="c1", expected_dimension=768, normalize_expected=False)

    def test_norm_outside_tolerance_rejected(self) -> None:
        v = [2.0] + [0.0] * 767  # norm == 2.0
        with pytest.raises(VectorValidationError, match="L2 norm"):
            validate_vector(
                v, chunk_id="c1", expected_dimension=768, normalize_expected=True, norm_tolerance=1e-3
            )

    def test_norm_within_tolerance_accepted(self) -> None:
        v = [1.0005] + [0.0] * 767
        validate_vector(
            v, chunk_id="c1", expected_dimension=768, normalize_expected=True, norm_tolerance=1e-3
        )

    def test_error_message_names_chunk_id(self) -> None:
        with pytest.raises(VectorValidationError, match="my_chunk"):
            validate_vector([0.0] * 5, chunk_id="my_chunk", expected_dimension=768, normalize_expected=False)

    def test_query_label_used_when_chunk_id_none(self) -> None:
        with pytest.raises(VectorValidationError, match=r"<query>"):
            validate_vector([0.0] * 5, chunk_id=None, expected_dimension=768, normalize_expected=False)
