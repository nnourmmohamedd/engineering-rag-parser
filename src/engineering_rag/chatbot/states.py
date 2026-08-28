"""Explicit lifecycle vocabularies for documents and ingestion jobs.

Free-form status strings are the usual way this kind of registry rots: a
typo becomes a state nothing handles, and "is this document safe to search?"
turns into a scattered set of string comparisons. Everything here is an enum
with a single, centrally-defined transition table, and
:func:`assert_transition` is the only sanctioned way to move a job forward.

The most important invariant in this module is
:data:`RETRIEVABLE_DOCUMENT_STATES`: a document is exposed to retrieval only
when it is ``READY``. A partially-indexed, failed, interrupted or deleted
document must never reach a query, which is what
:func:`is_retrievable` exists to make unambiguous at every call site.
"""

from __future__ import annotations

from enum import Enum

__all__ = [
    "ACTIVE_JOB_STATES",
    "RETRIEVABLE_DOCUMENT_STATES",
    "TERMINAL_JOB_STATES",
    "DocumentStatus",
    "InvalidStateTransitionError",
    "JobStage",
    "JobState",
    "JobType",
    "assert_transition",
    "is_retrievable",
    "is_retryable_state",
]


class InvalidStateTransitionError(RuntimeError):
    """Raised when code attempts a job-state transition the lifecycle forbids."""


class JobType(str, Enum):
    """Why an ingestion job exists. Governs cleanup and activation semantics."""

    INGEST = "ingest"
    REPROCESS = "reprocess"
    DELETE = "delete"


class JobStage(str, Enum):
    """The pipeline stage a running job is currently executing.

    Distinct from :class:`JobState`: the *state* says whether the job is
    queued/running/failed, the *stage* says how far through the pipeline it
    got. Keeping them separate means a FAILED job still reports the stage
    that failed, which is what the UI and the retry path both need.
    """

    QUEUED = "QUEUED"
    VALIDATING = "VALIDATING"
    PARSING = "PARSING"
    PARSER_VALIDATION = "PARSER_VALIDATION"
    CHUNKING = "CHUNKING"
    CHUNK_VALIDATION = "CHUNK_VALIDATION"
    EMBEDDING = "EMBEDDING"
    VECTOR_INDEXING = "VECTOR_INDEXING"
    BM25_INDEXING = "BM25_INDEXING"
    INDEX_VALIDATION = "INDEX_VALIDATION"
    ACTIVATION = "ACTIVATION"
    CLEANUP = "CLEANUP"


#: Ordered pipeline stages, used to render progress and to compute a
#: monotonic completion fraction. ACTIVATION/CLEANUP are terminal-ish and
#: deliberately excluded from the progress denominator.
INGESTION_STAGE_ORDER: tuple[JobStage, ...] = (
    JobStage.QUEUED,
    JobStage.VALIDATING,
    JobStage.PARSING,
    JobStage.PARSER_VALIDATION,
    JobStage.CHUNKING,
    JobStage.CHUNK_VALIDATION,
    JobStage.EMBEDDING,
    JobStage.VECTOR_INDEXING,
    JobStage.BM25_INDEXING,
    JobStage.INDEX_VALIDATION,
    JobStage.ACTIVATION,
)


class JobState(str, Enum):
    """Whether a job is waiting, running, or finished -- and how it finished."""

    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    READY = "READY"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    #: Assigned by startup recovery to a job left mid-flight by a crash or
    #: restart. Never silently promoted to READY: its document stays
    #: unsearchable until a human explicitly retries.
    INTERRUPTED = "INTERRUPTED"


class DocumentStatus(str, Enum):
    """A document's lifecycle position. Only READY is searchable."""

    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"
    DELETING = "DELETING"
    DELETED = "DELETED"


#: The single source of truth for "may this document's chunks reach a query?".
#: Deliberately a one-element set rather than an inline ``== READY`` scattered
#: across call sites, so widening it is a visible, reviewable change.
RETRIEVABLE_DOCUMENT_STATES: frozenset[DocumentStatus] = frozenset({DocumentStatus.READY})

#: Job states that mean "no worker is or will be acting on this right now".
TERMINAL_JOB_STATES: frozenset[JobState] = frozenset(
    {JobState.READY, JobState.FAILED, JobState.CANCELLED, JobState.INTERRUPTED}
)

#: Job states a worker may still act on.
ACTIVE_JOB_STATES: frozenset[JobState] = frozenset({JobState.QUEUED, JobState.RUNNING})

#: States from which an explicit user-initiated retry is allowed.
_RETRYABLE: frozenset[JobState] = frozenset({JobState.FAILED, JobState.CANCELLED, JobState.INTERRUPTED})

#: Every legal job-state transition. Anything absent here is a bug, not a
#: state to be tolerated: `assert_transition` raises rather than warning.
_ALLOWED_JOB_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.QUEUED: frozenset({JobState.RUNNING, JobState.CANCELLED, JobState.INTERRUPTED}),
    JobState.RUNNING: frozenset({JobState.READY, JobState.FAILED, JobState.CANCELLED, JobState.INTERRUPTED}),
    # Retrying re-queues a finished job; a READY job is never re-queued in
    # place (a reprocess creates a new job instead), so READY is terminal.
    JobState.READY: frozenset(),
    JobState.FAILED: frozenset({JobState.QUEUED}),
    JobState.CANCELLED: frozenset({JobState.QUEUED}),
    JobState.INTERRUPTED: frozenset({JobState.QUEUED}),
}


def is_retrievable(status: DocumentStatus) -> bool:
    """Whether a document in ``status`` may have its chunks returned by a query."""
    return status in RETRIEVABLE_DOCUMENT_STATES


def is_retryable_state(state: JobState) -> bool:
    """Whether an explicit user-initiated retry is allowed from ``state``."""
    return state in _RETRYABLE


def assert_transition(current: JobState, target: JobState) -> None:
    """Raise :class:`InvalidStateTransitionError` unless ``current -> target`` is legal.

    Self-transitions are allowed (a heartbeat/progress update re-asserting the
    same state is not a lifecycle change), but every genuine move must appear
    in the transition table.
    """
    if current is target:
        return
    allowed = _ALLOWED_JOB_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        permitted = sorted(s.value for s in allowed) or ["<terminal>"]
        raise InvalidStateTransitionError(
            f"illegal job transition {current.value} -> {target.value}; "
            f"allowed from {current.value}: {permitted}"
        )


def stage_progress(stage: JobStage) -> float:
    """Monotonic 0.0-1.0 completion fraction for ``stage``.

    Reports real pipeline position, never a synthetic animated value: the UI
    is forbidden from inventing progress the backend has not reported.
    """
    try:
        index = INGESTION_STAGE_ORDER.index(stage)
    except ValueError:
        return 0.0
    return round(index / (len(INGESTION_STAGE_ORDER) - 1), 4)
