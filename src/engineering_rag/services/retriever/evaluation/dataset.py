"""Loader for the versioned, human-readable retrieval ground-truth dataset (JSONL).

Each line is one :class:`~engineering_rag.services.retriever.models.RetrievalEvaluationCase`.
Loading validates every case eagerly (pydantic) and computes a stable SHA-256
over the raw file content so every evaluation report can record exactly which
version of the dataset it ran against.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from engineering_rag.services.retriever.models import RetrievalEvaluationCase

__all__ = ["dataset_hash", "load_evaluation_dataset"]


def load_evaluation_dataset(path: Path | str) -> list[RetrievalEvaluationCase]:
    """Load and validate every case in a ground-truth JSONL file.

    Raises:
        FileNotFoundError: if ``path`` does not exist.
        ValueError: if the file is empty, a line is not valid JSON, a case
            fails schema validation, or ``case_id`` is not unique.
    """
    dataset_path = Path(path)
    if not dataset_path.is_file():
        raise FileNotFoundError(f"Evaluation dataset not found: {dataset_path}")

    lines = [line for line in dataset_path.read_text(encoding="utf-8").split("\n") if line.strip()]
    if not lines:
        raise ValueError(f"Evaluation dataset is empty: {dataset_path}")

    cases: list[RetrievalEvaluationCase] = []
    seen_ids: set[str] = set()
    for i, line in enumerate(lines, start=1):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{dataset_path}:{i}: invalid JSON: {exc}") from exc
        try:
            case = RetrievalEvaluationCase.model_validate(payload)
        except Exception as exc:  # noqa: BLE001 - re-raise as a clean, line-numbered ValueError
            raise ValueError(f"{dataset_path}:{i}: invalid evaluation case: {exc}") from exc
        if case.case_id in seen_ids:
            raise ValueError(f"{dataset_path}:{i}: duplicate case_id {case.case_id!r}")
        seen_ids.add(case.case_id)
        cases.append(case)

    return cases


def dataset_hash(path: Path | str) -> str:
    """Stable SHA-256 over the raw dataset file content."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
