"""Retrieval-readiness evaluation (Phase 14): does each engineering term or
statement land in a coherent, individually retrievable chunk?

This is a **deterministic, automated lexical check** — it verifies a search
term appears in some chunk's `retrieval_text`, and records how many distinct
chunks it is split across. It is explicitly **not** a relevance judgement and
is not a substitute for human semantic review: no embeddings, no ranking, no
model-based scoring is used here. Results are written to
`docs/chunker/_generated/retrieval_readiness_report.json` for
`docs/chunker/MENTOR_EXPLANATION.md` / `HYBRID_BASELINE_COMPARISON.md` to
reference; the split between "automated lexical check" (this file) and
"human semantic review" (still PENDING, never fabricated) is stated
explicitly wherever these results are cited.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engineering_rag.pipelines.chunking_pipeline import run_chunking_pipeline
from engineering_rag.services.chunker import load_config
from engineering_rag.services.chunker.models import ContentType

from ...conftest import requires_chunker_tokenizer

pytestmark = [pytest.mark.slow, pytest.mark.integration, requires_chunker_tokenizer]

ENGINEERING_RUN = Path("data/output/parser/Instrumentation-and-Control-Engineering/20260824T124235Z-01e4d6fa")

# (label, search phrase, expected content_type family, category)
CASES: list[tuple[str, str, ContentType | None, str]] = [
    ("definition_ci", "C&I", None, "definition/acronym"),
    ("definition_hazop", "HAZOP", None, "definition/acronym"),
    ("standard_reference", "ISA-84", None, "section-specific fact"),
    ("standard_reference_pid", "P&ID", None, "section-specific fact"),
    ("table_1_label", "Table 1", ContentType.TABLE, "table"),
    ("table_2_label", "Table 2", ContentType.TABLE, "table"),
    ("multi_paragraph_topic", "Instrumentation Design Engineering", None, "multi-paragraph explanation"),
    ("figure_presence", "", ContentType.FIGURE, "diagram/caption"),
]


@pytest.fixture(scope="module")
def chunks(tmp_path_factory: pytest.TempPathFactory):
    if not (ENGINEERING_RUN / "docling" / "document.json").is_file():
        pytest.skip(f"Parser run not present at {ENGINEERING_RUN}")
    config = load_config("configs/chunker_production.yaml")
    result = run_chunking_pipeline(ENGINEERING_RUN, config, tmp_path_factory.mktemp("retrieval_eval"))
    return result.chunks


def _evaluate(chunks: list, label: str, phrase: str, expected_type: ContentType | None) -> dict:
    if phrase:
        matches = [c for c in chunks if phrase.lower() in c.retrieval_text.lower()]
    else:
        matches = [c for c in chunks if expected_type is not None and c.content_type is expected_type]
    return {
        "case": label,
        "phrase": phrase or None,
        "expected_content_type": expected_type.value if expected_type else None,
        "matching_chunk_ids": [c.chunk_id for c in matches],
        "matching_chunk_count": len(matches),
        "found": bool(matches),
        "sufficient_local_context": any(len(c.text.split()) >= 5 for c in matches) if matches else False,
        "human_review_required": True,  # lexical match only; never claims semantic relevance
    }


class TestRetrievalReadiness:
    @pytest.mark.parametrize("label,phrase,expected_type,category", CASES)
    def test_term_is_findable_in_a_coherent_chunk(
        self, chunks, label, phrase, expected_type, category
    ) -> None:
        evaluation = _evaluate(chunks, label, phrase, expected_type)
        assert evaluation["found"], (
            f"{label} ({category}): {phrase!r} not found in any chunk's retrieval_text"
        )
        assert evaluation["sufficient_local_context"], f"{label}: matched chunk(s) too short to carry context"

    def test_writes_evidence_report(self, chunks, tmp_path_factory: pytest.TempPathFactory) -> None:
        report = {
            "document": "Instrumentation-and-Control-Engineering.pdf",
            "methodology": "automated lexical substring match against retrieval_text — NOT a semantic "
            "relevance judgement; human semantic review is separately tracked and not fabricated here",
            "cases": [
                _evaluate(chunks, label, phrase, expected_type) for label, phrase, expected_type, _ in CASES
            ],
        }
        out_dir = Path("docs/chunker/_generated")
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "retrieval_readiness_report.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        assert all(c["found"] for c in report["cases"])
