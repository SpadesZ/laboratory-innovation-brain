"""The Knowledge Inbox row, derived (UX-001, §17.22).

§17.22 states the whole design in one sentence:

    IngestionItem 是使用者在 Knowledge Inbox 看到的那一列。它是**投影，不是真相來源**：state 由
    Job / ExecutionSpan / Artifact / ReviewItem / Conflict 推導，不得由前端或人工直接指定。

So there is no settable ``state``. `IngestionItem` has no such field, `derive_state` is a pure
function of the authoritative records, and `test_state_is_not_a_writable_field` asserts the
absence structurally. A settable state is the bypass a UI reaches for first -- "mark it READY" --
and once it exists the projection and the records disagree with nothing detecting it.

THE PRECEDENCE IS ORDERED, AND THE ORDER IS THE REQUIREMENT.

    BLOCKED       if any StageResult failed with error_class = POLICY_BLOCK
    FAILED        if RAW_STORE failed, or all value-producing stages failed
    PARTIAL       if >=1 value-producing stage SUCCEEDED and >=1 FAILED
    NEEDS_REVIEW  if any open ReviewItem or blocking Conflict is attached
    DUPLICATE     if duplicate_of_artifact_id is set (identical bytes)
    PROCESSING    if any stage is PENDING or a Job is QUEUED/RUNNING/WAITING_RESOURCE
    READY         otherwise

Evaluated top to bottom, first match wins. Reordering any pair changes what a user is told:
BLOCKED above FAILED is why a policy refusal sends an approver rather than an engineer; PARTIAL
above NEEDS_REVIEW is why a half-extracted document reads as incomplete rather than as awaiting a
human who has nothing to look at yet.

THE TWO DUPLICATES ARE NOT THE SAME DUPLICATE, and §17.22 is emphatic:

    duplicate_of_artifact_id     identical bytes -> no new scientific value; safe to skip
    duplicate_of_source_work_id  same work, different bytes (preprint vs journal vs mirror)
                                 -> NOT a discardable duplicate. MUST still create
                                    SourceWork/Attestation so EVI-004 can resolve independence.
                                    Silently dropping it corrupts corroboration counting.

Only the first reaches DUPLICATE state. A same-work duplicate is READY, because it produced real
scientific value -- and `test_a_same_work_duplicate_is_ready_and_keeps_its_attestation` is the
one that would catch an implementation collapsing the two into one field.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from lab_brain.core.models.job import ACTIVE_JOB_STATES, Job
from lab_brain.ingestion.pipeline import IngestionStage, StageResult, StageStatus
from lab_brain.surface.errors import ErrorClass


class ItemState(StrEnum):
    """§17.22's state vocabulary, exactly. Derived, never assigned."""

    PROCESSING = "PROCESSING"
    READY = "READY"
    PARTIAL = "PARTIAL"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    DUPLICATE = "DUPLICATE"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


#: The precedence, as data. §17.22 numbers these and the order is normative, so it is written
#: once here and the derivation walks it -- rather than a chain of `if`s whose order a later edit
#: could change without anyone noticing the behaviour moved.
PRECEDENCE: tuple[ItemState, ...] = (
    ItemState.BLOCKED,
    ItemState.FAILED,
    ItemState.PARTIAL,
    ItemState.NEEDS_REVIEW,
    ItemState.DUPLICATE,
    ItemState.PROCESSING,
    ItemState.READY,
)

#: Stages that produce scientific value, for the FAILED and PARTIAL rules. SECRET_SCAN and
#: RAW_STORE are excluded on purpose: they are preconditions. A document whose scan and storage
#: succeeded and whose every parse failed has produced nothing, and calling that PARTIAL because
#: two stages "succeeded" would tell a user they got something.
VALUE_PRODUCING: frozenset[IngestionStage] = frozenset(
    {
        IngestionStage.PARSE_TEXT,
        IngestionStage.PARSE_TABLE,
        IngestionStage.PARSE_FIGURE,
        IngestionStage.SEGMENT,
    }
)


@dataclass(frozen=True)
class IngestionItem:
    """§17.22, minus ``state``.

    The omission is the requirement. Every other field is a reference to something authoritative;
    a `state` field would be the one piece of data with no source, which is precisely why a UI
    would write to it.
    """

    item_id: str
    project_id: str
    actor_id: str
    trace_id: str
    raw_artifact_id: str | None
    source_kind: str
    display_name: str
    submitted_at: dt.datetime
    stage_results: tuple[StageResult, ...] = ()
    duplicate_of_artifact_id: str | None = None
    duplicate_of_source_work_id: str | None = None
    review_ids: tuple[str, ...] = ()
    conflict_ids: tuple[str, ...] = ()
    error_ids: tuple[str, ...] = ()
    job_ids: tuple[str, ...] = ()
    last_updated_at: dt.datetime | None = None
    #: Set when a same-work duplicate produced its own SourceWork/Attestation. Carried so the
    #: EVI-004 obligation is observable on the row rather than only in another table.
    attestation_ids: tuple[str, ...] = ()


def _stage_classes(
    stage_results: Sequence[StageResult],
    error_class_for: dict[str, ErrorClass] | None,
) -> dict[str, ErrorClass]:
    """Map each failed stage's reason code to its class.

    Taken from a supplied mapping rather than inferred from the stage, because the same stage
    fails for different reasons: a parse can fail because the file is corrupt (USER_INPUT_ERROR)
    or because an ACL refused the source (POLICY_BLOCK), and those send different people.
    """
    if error_class_for is not None:
        return error_class_for
    derived: dict[str, ErrorClass] = {}
    for result in stage_results:
        if result.status is StageStatus.FAILED and result.error_class is not None:
            derived[result.reason_code or ""] = ErrorClass(result.error_class.value)
    return derived


def derive_state(
    item: IngestionItem,
    *,
    jobs: Sequence[Job] = (),
    open_review_ids: frozenset[str] = frozenset(),
    blocking_conflict_ids: frozenset[str] = frozenset(),
    error_class_for: dict[str, ErrorClass] | None = None,
) -> ItemState:
    """§17.22's derivation, evaluated in the documented order.

    Everything it reads is authoritative: stage results from the pipeline, jobs from the job
    store, open reviews from the ReviewQueue (OPS-002), blocking conflicts from the conflict
    store. Nothing is passed in as an opinion about what the state should be.
    """
    classes = _stage_classes(item.stage_results, error_class_for)
    failed = [r for r in item.stage_results if r.status is StageStatus.FAILED]

    # BLOCKED — a policy refusal. First, because it sends an approver rather than an engineer,
    # and because §17.22's ordering rule puts a secret-scan quarantine here rather than in FAILED.
    for result in failed:
        if classes.get(result.reason_code or "") is ErrorClass.POLICY_BLOCK:
            return ItemState.BLOCKED

    # FAILED — RAW_STORE failed, or every value-producing stage failed. The first disjunct is
    # UX-004's precondition: without durable bytes there is nothing to retry against.
    raw_store = next((r for r in item.stage_results if r.stage is IngestionStage.RAW_STORE), None)
    if raw_store is not None and raw_store.status is StageStatus.FAILED:
        return ItemState.FAILED

    value_results = [r for r in item.stage_results if r.stage in VALUE_PRODUCING]
    value_ok = [r for r in value_results if r.status is StageStatus.SUCCEEDED]
    value_bad = [r for r in value_results if r.status is StageStatus.FAILED]
    if value_results and not value_ok and value_bad:
        return ItemState.FAILED

    # PARTIAL — some value produced, some lost.
    if value_ok and value_bad:
        return ItemState.PARTIAL

    # NEEDS_REVIEW — a human owes this item something (UX-005 puts it in the ReviewQueue).
    if open_review_ids.intersection(item.review_ids):
        return ItemState.NEEDS_REVIEW
    if blocking_conflict_ids.intersection(item.conflict_ids):
        return ItemState.NEEDS_REVIEW

    # DUPLICATE — identical bytes ONLY. `duplicate_of_source_work_id` deliberately does not
    # appear: a same-work duplicate produced real scientific value and must not be presented as
    # something the user can discard.
    if item.duplicate_of_artifact_id is not None:
        return ItemState.DUPLICATE

    # PROCESSING — still moving.
    if any(r.status is StageStatus.PENDING for r in item.stage_results):
        return ItemState.PROCESSING
    if any(job.state in ACTIVE_JOB_STATES for job in jobs):
        return ItemState.PROCESSING

    return ItemState.READY


@dataclass
class DuplicateVerdict:
    """What kind of duplicate an incoming document is, if any (§17.22, EVI-004).

    Two fields rather than one enum with three members, because the two can co-occur: the same
    bytes of the same work arriving twice is both. Collapsing them would force a choice that
    loses information the corroboration counter needs.
    """

    identical_bytes_of: str | None = None
    same_work_as: str | None = None

    @property
    def is_discardable(self) -> bool:
        """Only identical bytes are safe to skip. §17.22 says so in as many words."""
        return self.identical_bytes_of is not None

    @property
    def must_still_attest(self) -> bool:
        """A same-work duplicate MUST still create SourceWork/Attestation.

        Silently dropping it corrupts corroboration counting: EVI-004 resolves independence at
        the *work* level, so a mirror that never became an Attestation is a citation the
        independence counter never sees -- and the count is then wrong in the direction that
        makes evidence look weaker than it is.
        """
        return self.same_work_as is not None and self.identical_bytes_of is None


def classify_duplicate(
    *,
    content_hash: str,
    source_work_id: str | None,
    known_artifact_by_hash: dict[str, str],
    known_artifacts_by_work: dict[str, tuple[str, ...]],
) -> DuplicateVerdict:
    """Decide which kind of duplicate an incoming document is.

    Pure, and reads two separate indexes: identity by content hash is ART-001's, identity by work
    is EVI-004's. Keeping them separate here is what makes the two verdicts independently
    representable.
    """
    identical = known_artifact_by_hash.get(content_hash)
    same_work = None
    if source_work_id is not None and known_artifacts_by_work.get(source_work_id):
        same_work = source_work_id
    return DuplicateVerdict(identical_bytes_of=identical, same_work_as=same_work)


__all__ = [
    "PRECEDENCE",
    "VALUE_PRODUCING",
    "DuplicateVerdict",
    "IngestionItem",
    "ItemState",
    "classify_duplicate",
    "derive_state",
]
