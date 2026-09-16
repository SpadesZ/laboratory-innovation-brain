"""EPI-006: conflicts are first-class typed records, and a blocking one prevents ALLOW.

    §17.19.3  Conflict 是 `blocking_conflict_policy`、`unresolved_conflicts[]` 與
              `ReviewItem(CONFLICT)` 共用的唯一物件。衝突不得只以字串或散落旗標表示。
    §25.3     Conflicts MUST be first-class typed Conflict records with a declared conflict_type
              and blocking flag. `blocking_conflict_policy` MUST resolve against conflict_type;
              a blocking Conflict MUST prevent ALLOW; closing a Conflict MUST record a resolution
              event.

WHAT THIS SLICE CHANGED, AND WHY THE OLD ARRANGEMENT WAS THE PROBLEM. `HypothesisView` used to
carry `blocking_conflict_ids` -- opaque ids the *caller* had already judged to be blocking --
while `TransitionPolicy.blocking_conflict_policy` listed `conflict_type` values that nothing
compared against. The policy therefore honoured whatever it was handed: a caller that forgot to
populate the ids got an ALLOW, and a caller that populated them with the wrong thing got a block.
That is the arrangement §17.19.3 rules out. The policy now matches its declared types against
typed records and decides for itself.

The vocabulary is closed on purpose. A free-text conflict type cannot be matched against a policy,
and an LLM-authored one would put the decision back where AGT-016 forbids it -- a model deciding
what counts as blocking is a model deciding belief.
"""

from __future__ import annotations

import datetime as dt

import pytest

from lab_brain.core.models import (
    BeliefState,
    HypothesisView,
    TransitionOutcome,
    TransitionReason,
)
from lab_brain.core.models.conflict import (
    UNRESOLVED_CONFLICT_STATUSES,
    Conflict,
    ConflictResolutionStatus,
    ConflictType,
)
from lab_brain.core.repositories.conflicts import ConflictStoreError, InMemoryConflictStore
from tests.contract.test_transition_policy import conflict, hypothesis, policy, run

pytestmark = [pytest.mark.requirement("EPI-006"), pytest.mark.spec_test("T-EPI-006")]

T0 = dt.datetime(2026, 9, 16, 9, 0, tzinfo=dt.UTC)
PROJECT = "prj:photonics"
HYP = "hyp:rs-contact-resistance"


# --------------------------------------------------------------------------------------------
# The contract. §17.19.3's declared fields and vocabularies.
# --------------------------------------------------------------------------------------------


def test_the_conflict_carries_every_field_17_19_3_declares():
    """By name. A declared field the model lacks is a fact the record cannot hold."""
    for field in (
        "conflict_id",
        "project_id",
        "episode_id",
        "trace_id",
        "conflict_type",
        "subject_refs",
        "blocking",
        "detected_at",
        "detected_by_actor_or_slot",
        "supporting_refs",
        "review_id",
        "resolution_status",
        "resolved_at",
        "resolution_event_id",
    ):
        assert field in Conflict.model_fields, field


def test_the_conflict_type_vocabulary_is_the_declared_seven():
    """Closed, and exactly §17.19.3's list.

    Asserted as a set equality rather than a membership check: an *extra* member is as much a
    divergence as a missing one, and an extra one would be a conflict type no policy in the spec
    can declare as blocking.
    """
    assert {kind.value for kind in ConflictType} == {
        "PROVENANCE_CONFLICT",
        "CONDITION_CONFLICT",
        "VALIDITY_CONFLICT",
        "AUTHORITY_CONFLICT",
        "SIM_TO_REAL_CONFLICT",
        "SOURCE_RETRACTION_CONFLICT",
        "INDEPENDENCE_UNRESOLVED",
    }


def test_the_resolution_status_vocabulary_is_the_declared_five():
    assert {status.value for status in ConflictResolutionStatus} == {
        "OPEN",
        "UNDER_REVIEW",
        "RESOLVED",
        "ACCEPTED_AS_OPEN_QUESTION",
        "EXPIRED",
    }


def test_a_conflict_is_not_free_text():
    """§17.19.3: 衝突不得只以字串或散落旗標表示."""
    with pytest.raises(ValueError, match="conflict_type"):
        conflict(conflict_type="a measurement disagreed with a simulation")


def test_a_conflict_must_name_at_least_one_subject():
    """A conflict about nothing cannot appear in any hypothesis's `unresolved_conflicts`."""
    with pytest.raises(ValueError, match="subject_refs"):
        conflict(subject_refs=())


# --------------------------------------------------------------------------------------------
# Blocking. T-EPI-006's first clause.
# --------------------------------------------------------------------------------------------


def test_a_blocking_conflict_of_a_declared_type_prevents_allow_and_is_named():
    """The pass condition: outcome != ALLOW *and* the id appears in `blocking_conflict_ids`.

    Both halves matter. A decision that blocked without naming the conflict would leave a caller
    unable to find out what to resolve.
    """
    decision = run(
        pol=policy(blocking_conflict_policy=("SIM_TO_REAL_CONFLICT",)),
        hyp=hypothesis(conflicts=(conflict(conflict_id="cfl:9"),)),
    )
    assert decision.outcome is not TransitionOutcome.ALLOW
    assert decision.reason_code is TransitionReason.BLOCKING_CONFLICT
    assert decision.blocking_conflict_ids == ("cfl:9",)


def test_matching_is_on_conflict_type_not_on_the_callers_selection():
    """The change this slice made, pinned directly.

    A conflict of a type the policy does *not* list is not blocking, however the caller feels
    about it. Under the old arrangement the caller's id list decided, so this case would have
    blocked.
    """
    decision = run(
        pol=policy(blocking_conflict_policy=("SIM_TO_REAL_CONFLICT",)),
        hyp=hypothesis(
            conflicts=(conflict(conflict_type=ConflictType.PROVENANCE_CONFLICT),),
        ),
    )
    assert decision.outcome is TransitionOutcome.ALLOW


def test_a_non_blocking_conflict_of_a_declared_type_does_not_block():
    """`blocking` is the domain's own flag, and the policy honours it.

    An unresolved non-blocking conflict is a recorded disagreement the domain has said does not
    gate belief. Treating every conflict as blocking would make the flag meaningless and freeze
    projects that had honestly written their disagreements down.
    """
    decision = run(
        pol=policy(blocking_conflict_policy=("SIM_TO_REAL_CONFLICT",)),
        hyp=hypothesis(conflicts=(conflict(blocking=False),)),
    )
    assert decision.outcome is TransitionOutcome.ALLOW


@pytest.mark.parametrize("status", sorted(UNRESOLVED_CONFLICT_STATUSES))
def test_an_unresolved_blocking_conflict_blocks(status):
    """`UNDER_REVIEW` blocks too, and that is the case worth being explicit about.

    A human looking at a conflict has not resolved it. Treating "someone is on it" as cleared is
    how a blocking conflict stops blocking exactly when it matters most.
    """
    decision = run(
        pol=policy(blocking_conflict_policy=("SIM_TO_REAL_CONFLICT",)),
        hyp=hypothesis(conflicts=(conflict(resolution_status=status),)),
    )
    assert decision.outcome is not TransitionOutcome.ALLOW


def test_a_resolved_blocking_conflict_no_longer_blocks():
    """Or a project would be frozen by its own history."""
    decision = run(
        pol=policy(blocking_conflict_policy=("SIM_TO_REAL_CONFLICT",)),
        hyp=hypothesis(
            conflicts=(
                conflict(
                    resolution_status=ConflictResolutionStatus.RESOLVED,
                    resolved_at=T0,
                    resolution_event_id="bre:resolution",
                ),
            )
        ),
    )
    assert decision.outcome is TransitionOutcome.ALLOW


def test_blocking_conflict_ids_are_sorted_and_deterministic():
    """§8.2.1's determinism reaches the conflict list too."""
    conflicts = (
        conflict(conflict_id="cfl:9"),
        conflict(conflict_id="cfl:1"),
        conflict(conflict_id="cfl:5"),
    )
    pol = policy(blocking_conflict_policy=("SIM_TO_REAL_CONFLICT",))

    first = run(pol=pol, hyp=hypothesis(conflicts=conflicts))
    second = run(pol=pol, hyp=hypothesis(conflicts=tuple(reversed(conflicts))))

    assert first.blocking_conflict_ids == ("cfl:1", "cfl:5", "cfl:9")
    assert first.blocking_conflict_ids == second.blocking_conflict_ids


def test_only_the_matching_conflicts_are_named_in_the_decision():
    """A decision that listed unrelated conflicts would send a caller to resolve the wrong one."""
    decision = run(
        pol=policy(blocking_conflict_policy=("SIM_TO_REAL_CONFLICT",)),
        hyp=hypothesis(
            conflicts=(
                conflict(conflict_id="cfl:relevant"),
                conflict(
                    conflict_id="cfl:other",
                    conflict_type=ConflictType.PROVENANCE_CONFLICT,
                ),
            )
        ),
    )
    assert decision.blocking_conflict_ids == ("cfl:relevant",)


def test_a_policy_that_declares_no_blocking_types_is_not_blocked():
    """The field has to be meaningful in both directions, or it is decoration."""
    decision = run(hyp=hypothesis(conflicts=(conflict(),)))
    assert decision.outcome is TransitionOutcome.ALLOW


# --------------------------------------------------------------------------------------------
# AUTHORITY_CONFLICT. T-EPI-006's second clause, and the EPI-004 join.
# --------------------------------------------------------------------------------------------


def test_an_incomparable_comparison_forms_an_authority_conflict_linked_to_its_review():
    """§8.2.1's INCOMPARABLE flow, as a typed record rather than a special case.

    The decision escalates and describes the ReviewItem; this test builds the `Conflict` that
    escalation is about and links the two by `review_id`. §17.19.3 is explicit that
    `ReviewItem(subject_type=AUTHORITY_CONFLICT).subject_id` is a **conflict_id**, so the link has
    to exist in the record and not only in the decision.
    """
    from tests.toy_authority import ToyAuthorityPolicy

    decision = run(
        pol=policy(required_authority_rule="TIER_A"),
        hyp=hypothesis(admitted_authority_classes=("SIDEBAND",)),
        authority=ToyAuthorityPolicy(),
    )
    assert decision.outcome is TransitionOutcome.NEED_HUMAN_REVIEW
    assert decision.reason_code is TransitionReason.AUTHORITY_INCOMPARABLE
    spec = decision.review_item_spec
    assert spec is not None and spec.subject_type == "AUTHORITY_CONFLICT"

    authority_conflict = conflict(
        conflict_id="cfl:authority",
        conflict_type=ConflictType.AUTHORITY_CONFLICT,
        subject_refs=(HYP,),
        review_id="rvw:authority-1",
    )
    assert authority_conflict.conflict_type is ConflictType.AUTHORITY_CONFLICT
    assert authority_conflict.review_id == "rvw:authority-1"
    assert authority_conflict.blocks_transitions


def test_an_unresolved_authority_conflict_keeps_blocking_after_the_review_is_raised():
    """§8.2.1: "no BeliefRevisionEvent may promote/reject until the review resolves".

    Raising the review is not resolving it, so a conflict that has a `review_id` still blocks.
    Without this, escalation itself would clear the block.
    """
    decision = run(
        pol=policy(blocking_conflict_policy=("AUTHORITY_CONFLICT",)),
        hyp=hypothesis(
            conflicts=(
                conflict(
                    conflict_type=ConflictType.AUTHORITY_CONFLICT,
                    review_id="rvw:authority-1",
                    resolution_status=ConflictResolutionStatus.UNDER_REVIEW,
                ),
            )
        ),
    )
    assert decision.outcome is not TransitionOutcome.ALLOW
    assert decision.blocking_conflict_ids == ("cfl:1",)


# --------------------------------------------------------------------------------------------
# Closing one. T-EPI-006's third clause: "resolving without a resolution_event_id is rejected".
# --------------------------------------------------------------------------------------------


def test_a_resolved_conflict_without_a_resolution_event_is_rejected():
    """Refused at construction, so no code path can produce one -- including a support script."""
    with pytest.raises(ValueError, match="no resolution_event_id"):
        conflict(resolution_status=ConflictResolutionStatus.RESOLVED, resolved_at=T0)


def test_a_resolved_conflict_without_a_timestamp_is_rejected():
    """An as_of replay cannot place an untimed resolution."""
    with pytest.raises(ValueError, match="no resolved_at"):
        conflict(
            resolution_status=ConflictResolutionStatus.RESOLVED,
            resolution_event_id="bre:1",
        )


def test_an_open_conflict_may_not_carry_resolution_details():
    """A conflict that is still open must not look half-closed.

    A reader checking `resolution_event_id` to decide whether something was dealt with would
    conclude it had been.
    """
    with pytest.raises(ValueError, match="half-closed"):
        conflict(resolution_event_id="bre:1")


def test_the_store_refuses_to_resolve_without_an_event():
    """The same obligation at the store boundary, because the model is not the only writer."""
    store = InMemoryConflictStore()
    store.record(conflict())

    with pytest.raises(ConflictStoreError, match="no resolution_event_id"):
        store.resolve(
            project_id=PROJECT,
            conflict_id="cfl:1",
            resolution_event_id="",
            resolved_at=T0,
        )
    assert store.get(PROJECT, "cfl:1").is_unresolved  # type: ignore[union-attr]


def test_resolving_records_the_event_and_clears_the_block():
    store = InMemoryConflictStore()
    store.record(conflict())

    resolved = store.resolve(
        project_id=PROJECT,
        conflict_id="cfl:1",
        resolution_event_id="bre:resolution",
        resolved_at=T0,
    )
    assert resolved.resolution_status is ConflictResolutionStatus.RESOLVED
    assert resolved.resolution_event_id == "bre:resolution"
    assert not resolved.blocks_transitions
    assert store.get(PROJECT, "cfl:1") == resolved


def test_a_conflict_cannot_be_resolved_twice():
    """Re-resolving would overwrite the event that justified the first close."""
    store = InMemoryConflictStore()
    store.record(conflict())
    store.resolve(
        project_id=PROJECT,
        conflict_id="cfl:1",
        resolution_event_id="bre:first",
        resolved_at=T0,
    )

    with pytest.raises(ConflictStoreError, match="already RESOLVED"):
        store.resolve(
            project_id=PROJECT,
            conflict_id="cfl:1",
            resolution_event_id="bre:second",
            resolved_at=T0,
        )
    assert store.get(PROJECT, "cfl:1").resolution_event_id == "bre:first"  # type: ignore[union-attr]


def test_under_review_is_not_a_resolution():
    """Moving a conflict to review is a different operation and must not carry an event."""
    store = InMemoryConflictStore()
    store.record(conflict())

    with pytest.raises(ConflictStoreError, match="is not a resolution"):
        store.resolve(
            project_id=PROJECT,
            conflict_id="cfl:1",
            resolution_event_id="bre:1",
            resolved_at=T0,
            status=ConflictResolutionStatus.UNDER_REVIEW,
        )


def test_the_store_offers_no_way_to_delete_a_conflict():
    """Deleting one erases the reason a belief was blocked.

    Asserted against the class rather than trusted, for the same reason `BeliefEventStore` has no
    `delete`: the absence is the contract, and an absence nothing checks gets filled in later by
    someone who needed it once.
    """
    for forbidden in ("delete", "remove", "purge", "set_status", "update"):
        assert not hasattr(InMemoryConflictStore, forbidden), forbidden


# --------------------------------------------------------------------------------------------
# Project scope. SEC-002 applies to conflicts like every other read.
# --------------------------------------------------------------------------------------------


def test_conflicts_are_scoped_by_project():
    """Two projects may legitimately reference the same hypothesis id."""
    store = InMemoryConflictStore()
    store.record(conflict(conflict_id="cfl:mine"))
    store.record(conflict(conflict_id="cfl:theirs", project_id="prj:other"))

    assert [c.conflict_id for c in store.for_subject(PROJECT, HYP)] == ["cfl:mine"]
    assert [c.conflict_id for c in store.for_subject("prj:other", HYP)] == ["cfl:theirs"]


def test_a_conflict_in_another_project_cannot_be_resolved_through_this_one():
    """Fail closed rather than resolving the wrong record, or reporting success for neither."""
    store = InMemoryConflictStore()
    store.record(conflict(project_id="prj:other"))

    with pytest.raises(ConflictStoreError, match="does not exist"):
        store.resolve(
            project_id=PROJECT,
            conflict_id="cfl:1",
            resolution_event_id="bre:1",
            resolved_at=T0,
        )
    assert store.get("prj:other", "cfl:1").is_unresolved  # type: ignore[union-attr]


def test_a_conflict_is_not_silently_re_recorded():
    """A detector overwriting one a human had put UNDER_REVIEW is a silent reopen."""
    store = InMemoryConflictStore()
    store.record(conflict(resolution_status=ConflictResolutionStatus.UNDER_REVIEW))

    with pytest.raises(ConflictStoreError, match="already exists"):
        store.record(conflict())
    assert (
        store.get(PROJECT, "cfl:1").resolution_status  # type: ignore[union-attr]
        is ConflictResolutionStatus.UNDER_REVIEW
    )


def test_subject_queries_are_deterministically_ordered():
    """The result feeds `evaluate`, whose determinism is only as good as its inputs'."""
    store = InMemoryConflictStore()
    for index in (3, 1, 2):
        store.record(
            conflict(conflict_id=f"cfl:{index}", detected_at=T0 + dt.timedelta(minutes=index))
        )

    assert [c.conflict_id for c in store.for_subject(PROJECT, HYP)] == [
        "cfl:1",
        "cfl:2",
        "cfl:3",
    ]


def test_the_unresolved_view_is_what_a_hypothesis_view_is_built_from():
    """The seam between the store and `evaluate`: resolved conflicts do not reach the policy.

    Built end to end rather than asserted on the store alone, because the failure that matters is
    a resolved conflict still blocking -- and that is only visible once the policy has run.
    """
    store = InMemoryConflictStore()
    store.record(conflict(conflict_id="cfl:open"))
    store.record(conflict(conflict_id="cfl:closed"))
    store.resolve(
        project_id=PROJECT,
        conflict_id="cfl:closed",
        resolution_event_id="bre:resolution",
        resolved_at=T0,
    )

    unresolved = store.unresolved_for_subject(PROJECT, HYP)
    assert [c.conflict_id for c in unresolved] == ["cfl:open"]

    decision = run(
        pol=policy(blocking_conflict_policy=("SIM_TO_REAL_CONFLICT",)),
        hyp=HypothesisView(
            hypothesis_id=HYP,
            project_id=PROJECT,
            current_state=BeliefState.ACTIVE,
            conflicts=unresolved,
        ),
    )
    assert decision.blocking_conflict_ids == ("cfl:open",)


# --------------------------------------------------------------------------------------------
# Terminal states. The P10 audit found the closure obligation applied to one status of three.
# --------------------------------------------------------------------------------------------

#: Every status that stops a conflict blocking. Derived from the module's own set rather than
#: listed, so an eighth status cannot be added without appearing here.
UNBLOCKING_STATUSES = tuple(
    sorted(
        status for status in ConflictResolutionStatus if status not in UNRESOLVED_CONFLICT_STATUSES
    )
)


def test_every_unblocking_status_is_covered_by_this_module():
    """The set under test is derived, not transcribed.

    A hand-written list of terminal statuses is how the hole appeared in the first place: the
    validator named `RESOLVED` while `blocks_transitions` treated three statuses as closing.
    """
    assert set(UNBLOCKING_STATUSES) == {
        ConflictResolutionStatus.RESOLVED,
        ConflictResolutionStatus.ACCEPTED_AS_OPEN_QUESTION,
        ConflictResolutionStatus.EXPIRED,
    }


@pytest.mark.parametrize("status", UNBLOCKING_STATUSES)
def test_no_unblocking_status_may_be_reached_without_a_closure_event(status):
    """The audit's finding, as a parametrized rule rather than a case per enum member.

    Before this, `EXPIRED` and `ACCEPTED_AS_OPEN_QUESTION` unblocked a conflict with no event and
    no timestamp -- exactly "只改 enum 就解除 block". Only `RESOLVED` was guarded, so the
    obligation was satisfied for the status people wrote tests about and absent for the two they
    did not.
    """
    with pytest.raises(ValueError, match="no resolution_event_id"):
        conflict(resolution_status=status)


@pytest.mark.parametrize("status", UNBLOCKING_STATUSES)
def test_no_unblocking_status_may_be_reached_without_a_timestamp(status):
    """An as_of replay cannot place an untimed closure, whichever status did the closing."""
    with pytest.raises(ValueError, match="no resolved_at"):
        conflict(resolution_status=status, resolution_event_id="bre:1")


@pytest.mark.parametrize("status", UNBLOCKING_STATUSES)
def test_a_properly_closed_conflict_stops_blocking(status):
    """The rule has to be satisfiable in all three, or a project could never move past one."""
    closed = conflict(
        resolution_status=status,
        resolution_event_id="bre:closure",
        resolved_at=T0,
    )
    assert not closed.blocks_transitions
    assert not closed.is_unresolved


@pytest.mark.parametrize("status", sorted(UNRESOLVED_CONFLICT_STATUSES))
def test_no_unresolved_status_may_carry_closure_details(status):
    """The other direction: a conflict that still blocks must not look half-closed."""
    with pytest.raises(ValueError, match="closure details"):
        conflict(resolution_status=status, resolution_event_id="bre:1", resolved_at=T0)


@pytest.mark.parametrize("status", UNBLOCKING_STATUSES)
def test_the_store_closes_every_terminal_status_through_the_event_path(status):
    """`resolve` is the only way in, and it requires the event for all three."""
    store = InMemoryConflictStore()
    store.record(conflict())

    closed = store.resolve(
        project_id=PROJECT,
        conflict_id="cfl:1",
        resolution_event_id="bre:closure",
        resolved_at=T0,
        status=status,
    )
    assert closed.resolution_status is status
    assert not closed.blocks_transitions


@pytest.mark.parametrize("status", UNBLOCKING_STATUSES)
def test_an_expired_or_accepted_conflict_no_longer_blocks_a_transition(status):
    """End to end: the closure reaches `evaluate` and the block lifts.

    Asserted through the policy rather than on the model, because the failure that matters is a
    conflict that is closed in the record and still blocking -- or still blocking in the record
    and closed in the policy.
    """
    decision = run(
        pol=policy(blocking_conflict_policy=("SIM_TO_REAL_CONFLICT",)),
        hyp=hypothesis(
            conflicts=(
                conflict(
                    resolution_status=status,
                    resolution_event_id="bre:closure",
                    resolved_at=T0,
                ),
            )
        ),
    )
    assert decision.outcome is TransitionOutcome.ALLOW


# --------------------------------------------------------------------------------------------
# `blocking_conflict_policy` vocabulary. The comment claimed a guard that did not exist.
# --------------------------------------------------------------------------------------------


def test_an_unknown_blocking_conflict_type_is_refused_at_policy_construction():
    """The audit's second finding.

    `transition.py` carried a comment saying
    `blocking_conflict_policy_is_known_vocabulary()` existed to catch typos. It did not. The
    consequence was fail-open: `evaluate` matches on `ConflictType.value`, so
    `"SIM_TO_REAL_CONFLIC"` matched nothing and the policy silently declared no blocking types at
    all -- surfacing as an unexpected ALLOW long after the typo was written.
    """
    with pytest.raises(ValueError, match=r"not §17\.19\.3 conflict_type values"):
        policy(blocking_conflict_policy=("SIM_TO_REAL_CONFLIC",))


def test_the_refusal_names_the_unknown_value_and_the_known_ones():
    """A vocabulary error is only actionable if it says what was expected."""
    with pytest.raises(ValueError) as caught:
        policy(blocking_conflict_policy=("NOT_A_CONFLICT_TYPE",))
    message = str(caught.value)
    assert "NOT_A_CONFLICT_TYPE" in message
    assert "SIM_TO_REAL_CONFLICT" in message, "the known vocabulary has to be listed"


def test_one_bad_value_among_good_ones_is_still_refused():
    """A policy that was 'mostly right' would block some types and silently drop one."""
    with pytest.raises(ValueError, match="AUTHORITY_CONFLIC"):
        policy(
            blocking_conflict_policy=("SIM_TO_REAL_CONFLICT", "AUTHORITY_CONFLIC"),
        )


@pytest.mark.parametrize("kind", sorted(ConflictType))
def test_every_declared_conflict_type_is_accepted_as_a_blocking_policy(kind):
    """All seven, so the guard cannot be over-strict in a way no test would notice."""
    declared = policy(blocking_conflict_policy=(kind.value,))
    assert declared.blocking_conflict_policy == (kind.value,)


def test_an_empty_blocking_policy_remains_legal():
    """Declaring no blocking types is a real choice and must not be confused with a typo."""
    assert policy(blocking_conflict_policy=()).blocking_conflict_policy == ()
