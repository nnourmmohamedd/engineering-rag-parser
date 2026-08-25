"""Ground-truth dataset loader tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engineering_rag.services.retriever.evaluation.dataset import dataset_hash, load_evaluation_dataset


def _case(case_id: str = "c1", **overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "case_id": case_id,
        "query": "a query",
        "query_type": "exact_term",
        "source_document": "doc.pdf",
        "relevant_chunk_ids": ["chunk_1"],
    }
    base.update(overrides)
    return base


class TestLoadEvaluationDataset:
    def test_missing_file_raises_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_evaluation_dataset(tmp_path / "missing.jsonl")

    def test_empty_file_raises_value_error(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.jsonl"
        path.write_text("", encoding="utf-8")
        with pytest.raises(ValueError, match="empty"):
            load_evaluation_dataset(path)

    def test_invalid_json_line_raises_with_line_number(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.jsonl"
        path.write_text('{"case_id": "c1"\n', encoding="utf-8")
        with pytest.raises(ValueError, match="invalid JSON"):
            load_evaluation_dataset(path)

    def test_schema_violation_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "bad_schema.jsonl"
        path.write_text(json.dumps(_case(query_type="not_a_type")) + "\n", encoding="utf-8")
        with pytest.raises(ValueError, match="invalid evaluation case"):
            load_evaluation_dataset(path)

    def test_duplicate_case_id_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "dupes.jsonl"
        lines = [json.dumps(_case("c1")), json.dumps(_case("c1"))]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with pytest.raises(ValueError, match="duplicate case_id"):
            load_evaluation_dataset(path)

    def test_valid_dataset_loads_all_cases(self, tmp_path: Path) -> None:
        path = tmp_path / "good.jsonl"
        lines = [json.dumps(_case("c1")), json.dumps(_case("c2"))]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        cases = load_evaluation_dataset(path)
        assert [c.case_id for c in cases] == ["c1", "c2"]

    def test_blank_lines_are_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "blanks.jsonl"
        path.write_text(f"\n{json.dumps(_case('c1'))}\n\n", encoding="utf-8")
        cases = load_evaluation_dataset(path)
        assert len(cases) == 1


class TestDatasetHash:
    def test_stable_for_same_content(self, tmp_path: Path) -> None:
        path = tmp_path / "d.jsonl"
        path.write_text(json.dumps(_case()) + "\n", encoding="utf-8")
        assert dataset_hash(path) == dataset_hash(path)

    def test_changes_with_content(self, tmp_path: Path) -> None:
        path1 = tmp_path / "d1.jsonl"
        path2 = tmp_path / "d2.jsonl"
        path1.write_text(json.dumps(_case("c1")) + "\n", encoding="utf-8")
        path2.write_text(json.dumps(_case("c2")) + "\n", encoding="utf-8")
        assert dataset_hash(path1) != dataset_hash(path2)

    def test_real_shipped_dataset_loads(self) -> None:
        real_path = Path("data/eval/retrieval_ground_truth.jsonl")
        cases = load_evaluation_dataset(real_path)
        assert len(cases) >= 15
        assert any(c.is_unanswerable for c in cases)
        assert any(len(c.relevant_chunk_ids) > 1 for c in cases)
