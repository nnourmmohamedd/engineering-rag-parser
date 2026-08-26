"""Lifecycle vocabulary and transition-table behaviour."""

from __future__ import annotations

import pytest

from engineering_rag.chatbot.states import (
    ACTIVE_JOB_STATES,
    INGESTION_STAGE_ORDER,
    RETRIEVABLE_DOCUMENT_STATES,
    TERMINAL_JOB_STATES,
    DocumentStatus,
    InvalidStateTransitionError,
    JobStage,
    JobState,
    assert_transition,
    is_retrievable,
    is_retryable_state,
    stage_progress,
)


class TestRetrievability:
    def test_only_ready_documents_are_retrievable(self) -> None:
        assert frozenset({DocumentStatus.READY}) == RETRIEVABLE_DOCUMENT_STATES

    @pytest.mark.parametrize(
        "status",
        [
            DocumentStatus.UPLOADED,
            DocumentStatus.PROCESSING,
            DocumentStatus.FAILED,
            DocumentStatus.INTERRUPTED,
            DocumentStatus.DELETING,
            DocumentStatus.DELETED,
        ],
    )
    def test_every_non_ready_status_is_unsearchable(self, status: DocumentStatus) -> None:
        """A partially-indexed or removed document must never reach a query."""
        assert is_retrievable(status) is False

    def test_ready_is_searchable(self) -> None:
        assert is_retrievable(DocumentStatus.READY) is True


class TestJobTransitions:
    def test_happy_path_queued_to_ready(self) -> None:
        assert_transition(JobState.QUEUED, JobState.RUNNING)
        assert_transition(JobState.RUNNING, JobState.READY)

    def test_self_transition_is_allowed_for_progress_updates(self) -> None:
        assert_transition(JobState.RUNNING, JobState.RUNNING)

    @pytest.mark.parametrize("target", [JobState.FAILED, JobState.CANCELLED, JobState.INTERRUPTED])
    def test_running_may_end_in_any_failure_state(self, target: JobState) -> None:
        assert_transition(JobState.RUNNING, target)

    def test_queued_cannot_jump_straight_to_ready(self) -> None:
        """Skipping RUNNING would mean a document became searchable without processing."""
        with pytest.raises(InvalidStateTransitionError, match="illegal job transition"):
            assert_transition(JobState.QUEUED, JobState.READY)

    def test_ready_is_terminal(self) -> None:
        with pytest.raises(InvalidStateTransitionError):
            assert_transition(JobState.READY, JobState.QUEUED)

    @pytest.mark.parametrize("origin", [JobState.FAILED, JobState.CANCELLED, JobState.INTERRUPTED])
    def test_failed_states_may_be_requeued_by_an_explicit_retry(self, origin: JobState) -> None:
        assert_transition(origin, JobState.QUEUED)
        assert is_retryable_state(origin) is True

    def test_ready_is_not_retryable(self) -> None:
        assert is_retryable_state(JobState.READY) is False

    def test_interrupted_cannot_become_ready_without_reprocessing(self) -> None:
        """Recovery must never promote a half-finished job straight to success."""
        with pytest.raises(InvalidStateTransitionError):
            assert_transition(JobState.INTERRUPTED, JobState.READY)

    def test_active_and_terminal_states_are_disjoint_and_total(self) -> None:
        assert frozenset() == ACTIVE_JOB_STATES & TERMINAL_JOB_STATES
        assert set(JobState) == ACTIVE_JOB_STATES | TERMINAL_JOB_STATES


class TestStageProgress:
    def test_progress_is_monotonic_across_the_pipeline(self) -> None:
        values = [stage_progress(s) for s in INGESTION_STAGE_ORDER]
        assert values == sorted(values)

    def test_queued_is_zero_and_activation_is_one(self) -> None:
        assert stage_progress(JobStage.QUEUED) == 0.0
        assert stage_progress(JobStage.ACTIVATION) == 1.0

    def test_progress_stays_within_bounds(self) -> None:
        assert all(0.0 <= stage_progress(s) <= 1.0 for s in JobStage)

    def test_stage_outside_the_ingestion_order_is_zero_not_an_error(self) -> None:
        assert stage_progress(JobStage.CLEANUP) == 0.0
