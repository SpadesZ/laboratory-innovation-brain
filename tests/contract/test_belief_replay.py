"""EPI-003: replay re-derives the state, and a quarantine changes it without editing history.

    §6.18  發現某 extractor_version 有系統性錯誤
             -> quarantine 該版本產生的所有 Attestation
             -> replay BeliefRevisionEvent, 略過被隔離的 triggering attestation
             -> 得到可驗證的新 EpistemicStateProjection
             -> 不得靠手改 current status

Split from `test_belief_transition.py` (which owns EPI-005) because §26 maps one requirement to one
test id, and a module carrying both pairs makes the traceability matrix check form cross products
it cannot map -- `(EPI-003, T-EPI-005)` is not a pair the spec declares. One requirement per module
keeps the matrix honest.

Every replay case below is a way a contamination rollback could look complete and leave a belief
standing that its evidence no longer supports.
"""

from __future__ import annotations

import datetime as dt

import pytest

from lab_brain.core.belief import (
    PROJECTION_VERSION,
    BeliefScopeError,
    SkipReason,
    VerifiedBeliefRevision,
    quarantined_by_extractor_version,
    replay,
)
from lab_brain.core.models import BeliefRevisionEvent, BeliefState, BeliefTargetType
from tests.conftest_fixtures import forged_verification

pytestmark = [pytest.mark.requirement("EPI-003"), pytest.mark.spec_test("T-EPI-003")]

T0 = dt.datetime(2026, 9, 15, 12, 0, tzinfo=dt.UTC)
PROJECT = "prj:photonics"
HYP = "hyp:rs-contact-resistance"
TRACE = "trc:episode-1"


def event(**overrides: object) -> BeliefRevisionEvent:
    defaults: dict[str, object] = {
        "event_id": "bre:1",
        "project_id": PROJECT,
        "target_type": BeliefTargetType.HYPOTHESIS,
        "target_id": HYP,
        "from_state": BeliefState.ACTIVE,
        "to_state": BeliefState.SUPPORTED,
        "triggering_attestation_ids": ("att:1",),
        "policy_id": "pol:hypothesis-default",
        "policy_version": "1.0.0",
        "authorization_decision_id": "dec:1",
        "occurred_at": T0,
        "trace_id": TRACE,
    }
    defaults.update(overrides)
    # Genesis carries no authorization and non-genesis requires one (`v3.3-a12`). Mirrored here so
    # a case that only wanted to set `from_state=None` does not have to know about the field; the
    # rule itself is tested directly rather than through this default.
    if defaults.get("from_state") is None:
        defaults["authorization_decision_id"] = None
    return BeliefRevisionEvent(**defaults)  # type: ignore[arg-type]


def _attested(extractor_id: str, extractor_version: str):
    """An Attestation from a named extractor at a named version.

    Built through the shared fixture's provenance so `extractor_version` and
    `extraction_provenance.extractor_version` agree -- Attestation refuses them out of step, which
    is the M0a invariant that makes this quarantine query meaningful in the first place.
    """
    from tests.conftest_fixtures import make_attestation, make_extraction_provenance

    return make_attestation(
        extraction_provenance=make_extraction_provenance(
            extractor_id=extractor_id, extractor_version=extractor_version
        )
    )


def verified(*events: BeliefRevisionEvent) -> tuple[VerifiedBeliefRevision, ...]:
    """Wrap events as verified revisions without verifying them.

    This module tests the *fold*: ordering, quarantine skipping, cascade, project scoping. None of
    that is about authorization, and standing up a decision store for each case would test the read
    gate a dozen more times and the reducer less clearly. Verification has its own module.
    """
    return tuple(forged_verification(event) for event in events)


# --------------------------------------------------------------------------------------------
# The minimal deterministic reducer.
# --------------------------------------------------------------------------------------------


def test_an_empty_history_projects_to_no_state():
    """Distinct from DRAFT, which an event had to produce."""
    projection = replay(PROJECT, HYP, ())
    assert projection.is_empty
    assert projection.current_state is None
    assert projection.last_event_id is None


def test_replay_folds_the_chain_in_time_order_not_insertion_order():
    events = [
        event(
            event_id="bre:2",
            from_state=BeliefState.ACTIVE,
            to_state=BeliefState.SUPPORTED,
            occurred_at=T0 + dt.timedelta(minutes=2),
        ),
        event(event_id="bre:1", from_state=None, to_state=BeliefState.ACTIVE),
    ]
    projection = replay(PROJECT, HYP, verified(*events))
    assert projection.applied == ("bre:1", "bre:2")
    assert projection.current_state is BeliefState.SUPPORTED
    assert projection.last_event_id == "bre:2"


def test_events_for_another_target_fail_loudly_rather_than_being_filtered():
    """This test previously asserted the opposite, and the opposite was wrong.

    `replay` used to filter on `target_id`, so a sequence containing another hypothesis's events
    quietly narrowed to the right ones. That reads like robustness and is the same mistake as
    filtering by project: the caller assembled a sequence it did not understand, and narrowing
    answers a question nobody asked while looking like success.
    """
    events = [
        event(event_id="bre:1", from_state=None, to_state=BeliefState.ACTIVE),
        event(
            event_id="bre:x",
            target_id="hyp:other",
            from_state=None,
            to_state=BeliefState.CONTRADICTED,
        ),
    ]
    with pytest.raises(BeliefScopeError, match="target"):
        replay(PROJECT, HYP, verified(*events))


def test_a_wrong_target_request_is_refused_rather_than_answered_as_empty():
    """The dangerous shape: every event is same-project and none is the requested target.

    Filtering returned an empty projection here, which is indistinguishable from "this hypothesis
    has no history yet" -- a confident wrong answer rather than an error. Same project throughout,
    so only the target is wrong and nothing else can account for the refusal.
    """
    events = [event(event_id="bre:1", from_state=None, to_state=BeliefState.ACTIVE)]

    with pytest.raises(BeliefScopeError, match="target"):
        replay(PROJECT, "hyp:not-this-one", verified(*events))


def test_a_wrong_project_request_is_refused_even_when_the_target_matches():
    """The other single-axis case, so neither guard can be carrying the other."""
    events = [event(event_id="bre:1", from_state=None, to_state=BeliefState.ACTIVE)]

    with pytest.raises(BeliefScopeError, match="project"):
        replay("prj:not-this-one", HYP, verified(*events))


def test_both_scope_problems_are_reported_together():
    """A caller who got both wrong should not have to fix one and re-run to find the other."""
    events = [
        event(event_id="bre:1", project_id="prj:other", target_id="hyp:other", from_state=None)
    ]

    with pytest.raises(BeliefScopeError) as caught:
        replay(PROJECT, HYP, verified(*events))
    assert "project" in str(caught.value) and "target" in str(caught.value)


# --------------------------------------------------------------------------------------------
# Scope is `(project_id, target_id)`. P7 audit finding 2.
# --------------------------------------------------------------------------------------------


def test_two_projects_may_use_the_same_target_id_without_their_histories_merging():
    """The collision the audit asked for, and the reason `v3.3-a11` added `project_id`.

    A hypothesis id is unique only within its project: since `011j` (M3, closing R-12) an event's
    `(project_id, target_id)` references a hypothesis admitted in that project, and two projects may
    admit the same id. So two projects reaching the same id is not a pathological case, and a replay
    keyed on the target alone would fold both histories together and return a state neither project
    is in.
    """
    mine = event(event_id="bre:mine", from_state=None, to_state=BeliefState.ACTIVE)
    theirs = event(
        event_id="bre:theirs",
        project_id="prj:other",
        from_state=None,
        to_state=BeliefState.CONTRADICTED,
    )

    assert replay(PROJECT, HYP, verified(mine)).current_state is BeliefState.ACTIVE
    assert replay("prj:other", HYP, verified(theirs)).current_state is BeliefState.CONTRADICTED


def test_mixed_project_input_fails_loudly_rather_than_being_filtered():
    """Filtering would return a plausible projection built from a query nobody meant to run.

    A caller handing this function two projects' events has already lost track of scope somewhere
    earlier; silently narrowing to the right ones hides that and answers the wrong question well.
    """
    events = [
        event(event_id="bre:mine", from_state=None, to_state=BeliefState.ACTIVE),
        event(
            event_id="bre:theirs",
            project_id="prj:other",
            from_state=None,
            to_state=BeliefState.CONTRADICTED,
        ),
    ]
    with pytest.raises(BeliefScopeError, match=r"project\(s\) prj:other"):
        replay(PROJECT, HYP, verified(*events))


def test_the_projection_records_which_project_it_is_for():
    """A projection that does not say whose it is cannot be compared with another safely."""
    projection = replay(PROJECT, HYP, verified(event(from_state=None, to_state=BeliefState.ACTIVE)))
    assert projection.project_id == PROJECT
    assert projection.target_id == HYP


def test_replay_is_deterministic_for_events_in_the_same_microsecond():
    """Total order, so a projection is reproducible evidence rather than a coin toss."""
    events = [
        event(event_id="bre:b", from_state=BeliefState.ACTIVE, to_state=BeliefState.SUPPORTED),
        event(event_id="bre:a", from_state=None, to_state=BeliefState.ACTIVE),
    ]
    first = replay(PROJECT, HYP, verified(*events))
    second = replay(PROJECT, HYP, verified(*reversed(events)))
    assert first == second
    assert first.applied == ("bre:a", "bre:b")


def test_the_projection_carries_every_field_17_13_declares():
    """The inversion of a test that used to assert the opposite, and the inversion is the point.

    Until M0b closure this type was called `BeliefProjection` and this test asserted that
    `belief_level`, `unresolved_conflicts` and `projection_version` were **absent** -- because they
    needed EPI-004 and EPI-006, and a type carrying §17.13's name with two of its fields missing
    would have been read as finished. Those requirements landed, so the fields are real and the
    name is earned.

    `belief_level` is asserted to be None rather than merely present. §17.13 marks it optional,
    §8.1 only *建議s* an ordinal LOW/MEDIUM/HIGH and declares no thresholds, and "evidence quality
    dimensions" is a DomainPack judgment -- so core computing one would be a scientific verdict in
    core prose rather than in a versioned policy (AGT-016). Absent and explained beats invented.
    """
    projection = replay(PROJECT, HYP, verified(event(from_state=None, to_state=BeliefState.ACTIVE)))
    for declared in (
        "target_id",
        "current_state",
        "belief_level",
        "unresolved_conflicts",
        "last_event_id",
        "projection_version",
        "projected_at",
    ):
        assert hasattr(projection, declared), f"§17.13 declares {declared}"

    assert projection.belief_level is None, "core must not invent an ordinal belief level"
    assert projection.projection_version == PROJECTION_VERSION
    assert projection.unresolved_conflicts == ()


def test_unresolved_conflicts_are_supplied_and_deterministically_ordered():
    """§17.13: conflict_id references, not inline payloads -- and stable across two reads.

    Supplied rather than folded out of the events, because §17.19.3 conflicts are their own table
    with their own lifecycle and no fold over the belief log can know them. Sorted here because the
    caller gets them from a repository, and a projection whose conflict order depended on query
    planning would compare unequal to itself between two runs.
    """
    revisions = verified(event(from_state=None, to_state=BeliefState.ACTIVE))
    projection = replay(PROJECT, HYP, revisions, unresolved_conflicts=["cfl:b", "cfl:a", "cfl:b"])
    assert projection.unresolved_conflicts == ("cfl:a", "cfl:b")
    assert projection.has_unresolved_conflicts
    assert projection == replay(PROJECT, HYP, revisions, unresolved_conflicts=["cfl:b", "cfl:a"])


def test_the_projector_reads_no_clock():
    """`projected_at` is an argument. A projector that stamped `now()` would make two replays of
    one immutable history compare unequal, which is the whole claim EPI-003 makes."""
    revisions = verified(event(from_state=None, to_state=BeliefState.ACTIVE))
    assert replay(PROJECT, HYP, revisions).projected_at is None
    assert replay(PROJECT, HYP, revisions) == replay(PROJECT, HYP, revisions)

    stamped = replay(PROJECT, HYP, revisions, projected_at=T0)
    assert stamped.projected_at == T0
    assert stamped != replay(PROJECT, HYP, revisions)


# --------------------------------------------------------------------------------------------
# §6.18's contamination rollback.
# --------------------------------------------------------------------------------------------


def test_quarantining_a_trigger_changes_the_projection_and_keeps_the_history():
    """T-EPI-003's pass condition, in one test.

    The projection changes; the events are untouched. That is the difference between a rollback and
    a hand edit -- §6.18's 不得靠手改 current status.
    """
    events = [
        event(
            event_id="bre:1",
            from_state=None,
            to_state=BeliefState.ACTIVE,
            triggering_attestation_ids=("att:clean",),
        ),
        event(
            event_id="bre:2",
            from_state=BeliefState.ACTIVE,
            to_state=BeliefState.SUPPORTED,
            triggering_attestation_ids=("att:contaminated",),
            occurred_at=T0 + dt.timedelta(minutes=1),
        ),
    ]

    before = replay(PROJECT, HYP, verified(*events))
    assert before.current_state is BeliefState.SUPPORTED

    after = replay(
        PROJECT, HYP, verified(*events), quarantined_attestation_ids={"att:contaminated"}
    )
    assert after.current_state is BeliefState.ACTIVE, "the promotion rested on quarantined evidence"
    assert after.applied == ("bre:1",)
    assert after.skipped == (("bre:2", SkipReason.QUARANTINED_TRIGGER),)
    assert len(events) == 2, "the event log itself is untouched"


def test_a_skip_cascades_to_events_whose_predecessor_is_gone():
    """Not cascading would apply a transition from a state the replay never reached."""
    events = [
        event(
            event_id="bre:1",
            from_state=None,
            to_state=BeliefState.ACTIVE,
            triggering_attestation_ids=("att:contaminated",),
        ),
        event(
            event_id="bre:2",
            from_state=BeliefState.ACTIVE,
            to_state=BeliefState.SUPPORTED,
            triggering_attestation_ids=("att:clean",),
            occurred_at=T0 + dt.timedelta(minutes=1),
        ),
    ]
    projection = replay(
        PROJECT, HYP, verified(*events), quarantined_attestation_ids={"att:contaminated"}
    )
    assert projection.is_empty
    assert dict(projection.skipped) == {
        "bre:1": SkipReason.QUARANTINED_TRIGGER,
        "bre:2": SkipReason.PREDECESSOR_MISSING,
    }


def test_an_event_with_any_quarantined_trigger_is_skipped_whole():
    """Fail-closed, and the choice is arguable enough to pin.

    The ALLOW was computed over the whole trigger set. This reducer cannot know it would still
    have been ALLOW over a subset -- re-deciding needs the policy inputs, which the event does not
    carry -- so keeping the event would preserve a belief whose authorisation may no longer hold.
    """
    events = [
        event(
            event_id="bre:1",
            from_state=None,
            to_state=BeliefState.ACTIVE,
            triggering_attestation_ids=("att:clean", "att:contaminated"),
        ),
    ]
    projection = replay(
        PROJECT, HYP, verified(*events), quarantined_attestation_ids={"att:contaminated"}
    )
    assert projection.is_empty
    assert projection.skipped == (("bre:1", SkipReason.QUARANTINED_TRIGGER),)


def test_quarantining_nothing_changes_nothing():
    events = [event(event_id="bre:1", from_state=None, to_state=BeliefState.ACTIVE)]
    assert replay(PROJECT, HYP, verified(*events)) == replay(
        PROJECT, HYP, verified(*events), quarantined_attestation_ids=set()
    )


# --------------------------------------------------------------------------------------------
# Selecting what to quarantine. §6.18's first step.
# --------------------------------------------------------------------------------------------


def test_quarantine_matches_on_extractor_and_version_not_version_alone():
    """ "1.0.0" is not a global identifier.

    Quarantining every extractor that happens to share a version string would discard evidence
    that was never contaminated -- a rollback that destroys good evidence is not a fix.
    """
    bad = _attested("ext:broken", "1.0.0")
    same_version = _attested("ext:fine", "1.0.0")
    same_extractor_newer = _attested("ext:broken", "2.0.0")

    quarantined = quarantined_by_extractor_version(
        [bad, same_version, same_extractor_newer], {"ext:broken": "1.0.0"}
    )
    assert quarantined == {bad.attestation_id}


def test_quarantining_no_versions_selects_nothing():
    attestation = _attested("ext:broken", "1.0.0")
    assert quarantined_by_extractor_version([attestation], None) == frozenset()
    assert quarantined_by_extractor_version([attestation], {}) == frozenset()
