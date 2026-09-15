"""EPI-003: every belief change is an append-only event, and the event is replayable.

    §6.18    信念轉移採 append-only `BeliefRevisionEvent`。任何 manual correction 也必須形成
             event，不可直接 UPDATE current belief row（EPI-003 / AGT-009）。
    §17.13   BeliefRevisionEvent { event_id, project_id, target_type, target_id, from_state?,
             to_state, triggering_attestation_ids[], triggering_relation_ids[], policy_id,
             policy_version, actor_id?, inference_provenance_id?,
             rationale_artifact_or_record_ref?, occurred_at, trace_id }
    §8.2     DRAFT -> ADMITTED -> ACTIVE -> {SUPPORTED | CHALLENGED | CONTRADICTED | INCONCLUSIVE}
                                      \\-> EVOLVED / SUPERSEDED

Written before the implementation. Every negative case below is a record that would make the
history unreplayable while looking complete -- which is the only failure mode that matters here,
because an event stream nobody can re-derive is not an audit trail, it is a log.

`project_id` and `policy_id` are present by amendment `v3.3-a11` (SPEC-ISSUE-010). Without the
first, "replay this project's belief history" is not expressible; without the second, an event
says it was authorised at version 1.2.0 without saying by which policy.
"""

from __future__ import annotations

import datetime as dt

import pytest

from lab_brain.core.models import (
    BELIEF_TERMINAL_STATES,
    BeliefRevisionEvent,
    BeliefState,
    BeliefTargetType,
    new_id,
)

pytestmark = [pytest.mark.requirement("EPI-003"), pytest.mark.spec_test("T-EPI-003")]

T0 = dt.datetime(2026, 9, 15, 10, 0, tzinfo=dt.UTC)
PROJECT = "prj:photonics"
TARGET = "hyp:rs-contact-resistance"
TRACE = "trc:episode-1"


def event(**overrides: object) -> BeliefRevisionEvent:
    defaults: dict[str, object] = {
        "event_id": "bre:1",
        "project_id": PROJECT,
        "target_type": BeliefTargetType.HYPOTHESIS,
        "target_id": TARGET,
        "from_state": BeliefState.ACTIVE,
        "to_state": BeliefState.SUPPORTED,
        "triggering_relation_ids": ("rel:1",),
        "policy_id": "pol:hypothesis-default",
        "policy_version": "1.0.0",
        "occurred_at": T0,
        "trace_id": TRACE,
    }
    defaults.update(overrides)
    return BeliefRevisionEvent(**defaults)  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------------
# The declared contract.
# --------------------------------------------------------------------------------------------


def test_the_event_carries_every_field_17_13_declares():
    """By name. A declared field the model lacks is a fact the replay cannot recover."""
    for field in (
        "event_id",
        "project_id",
        "target_type",
        "target_id",
        "from_state",
        "to_state",
        "triggering_attestation_ids",
        "triggering_relation_ids",
        "policy_id",
        "policy_version",
        "actor_id",
        "inference_provenance_id",
        "rationale_artifact_or_record_ref",
        "occurred_at",
        "trace_id",
    ):
        assert field in BeliefRevisionEvent.model_fields, f"§17.13 declares {field}"


def test_the_state_vocabulary_is_exactly_the_8_2_lifecycle():
    """§8.2's diagram is the normative list.

    §8.2.1's prose says an LLM may not turn ACTIVE into "SUPPORTED/REJECTED", but there is no
    REJECTED state in §8.2 -- its negative terminal is CONTRADICTED. Read as shorthand rather than
    a ninth state; recorded in SPEC-ISSUE-010 so nobody has to re-derive that.
    """
    assert {member.value for member in BeliefState} == {
        "DRAFT",
        "ADMITTED",
        "ACTIVE",
        "SUPPORTED",
        "CHALLENGED",
        "CONTRADICTED",
        "INCONCLUSIVE",
        "EVOLVED",
        "SUPERSEDED",
    }
    assert "REJECTED" not in {member.value for member in BeliefState}


def test_the_event_is_frozen_and_forbids_unknown_fields():
    """Append-only starts in memory: correcting a record writes a new one (P2)."""
    assert BeliefRevisionEvent.model_config.get("frozen") is True
    assert BeliefRevisionEvent.model_config.get("extra") == "forbid"
    with pytest.raises(Exception):  # noqa: B017 - pydantic's type here is not the property
        event(unexpected_field="x")


def test_an_event_id_is_its_own_kind():
    assert new_id("belief_revision_event").startswith("bre:")


# --------------------------------------------------------------------------------------------
# A transition has to be a transition. Each of these is an event that reads as a real revision
# and is not one.
# --------------------------------------------------------------------------------------------


def test_an_event_that_does_not_change_state_is_rejected():
    """A "revision" from ACTIVE to ACTIVE records nothing and replays as a no-op.

    Allowing it means the history can be padded with events that change nothing, which is how a
    projection's `last_event_id` stops meaning "the event that produced this state".
    """
    with pytest.raises(ValueError, match="does not change the state"):
        event(from_state=BeliefState.ACTIVE, to_state=BeliefState.ACTIVE)


def test_an_event_out_of_a_terminal_state_is_rejected():
    """EVOLVED and SUPERSEDED are exits from the lifecycle, not way-stations.

    §8.2 draws them as terminals. A transition out of one would mean a superseded hypothesis came
    back, and the replay would produce a state the lifecycle does not contain.
    """
    for terminal in sorted(BELIEF_TERMINAL_STATES):
        with pytest.raises(ValueError, match="terminal"):
            event(from_state=terminal, to_state=BeliefState.ACTIVE)


def test_the_first_event_for_a_target_may_omit_from_state():
    """`from_state?` is optional in §17.13: a target's first event has no predecessor."""
    assert event(from_state=None, to_state=BeliefState.DRAFT).from_state is None


def test_an_event_with_no_triggering_evidence_is_rejected():
    """§17.13 gives two triggering arrays, and an event citing neither cites nothing.

    Replay under quarantine (§6.18) works by skipping events whose triggering attestations were
    quarantined. An event with no triggers is unreachable by that mechanism -- it would survive
    every quarantine, which makes the contamination rollback silently incomplete.
    """
    with pytest.raises(ValueError, match="no triggering"):
        event(triggering_attestation_ids=(), triggering_relation_ids=())


def test_triggering_references_may_not_repeat():
    """A duplicated trigger double-counts the evidence that authorised a revision."""
    with pytest.raises(ValueError, match="twice"):
        event(triggering_relation_ids=("rel:1", "rel:1"))


def test_an_event_requires_a_policy_id_and_version():
    """`v3.3-a11`: a version without a policy identifies nothing.

    Versions are per-policy, so two policies at 1.0.0 are indistinguishable without the id, and an
    auditor holding the inputs cannot choose which policy to re-run.
    """
    for missing in ("policy_id", "policy_version"):
        with pytest.raises(Exception):  # noqa: B017 - absence is the property, not the type
            event(**{missing: None})


def test_an_event_requires_a_trace_id():
    """§12.5: `trace_id` threads the episode. A revision outside any trace cannot be explained."""
    with pytest.raises(Exception):  # noqa: B017
        event(trace_id=None)


def test_a_naive_occurred_at_is_rejected():
    """Replay orders events by time across processes; one naive timestamp makes that wrong."""
    with pytest.raises(ValueError, match="timezone-aware"):
        event(occurred_at=dt.datetime(2026, 9, 15, 10, 0))


def test_only_a_hypothesis_is_a_transition_target_for_now():
    """`target_type` exists because §17.13 declares it, with the one type §8.2 gives a lifecycle.

    A Claim's identity status (PROVISIONAL/RESOLVED/MERGED/DISPUTED) is governed by the merge path
    (P22), not by TransitionPolicy, and inventing a claim-transition vocabulary here would be
    building EPI-001's half of the model from an M0b slice.
    """
    assert {member.value for member in BeliefTargetType} == {"HYPOTHESIS"}


# --------------------------------------------------------------------------------------------
# Manual correction is still an event. §6.18 / AGT-009.
# --------------------------------------------------------------------------------------------


def test_a_manual_correction_is_representable_as_an_event():
    """§6.18: 任何 manual correction 也必須形成 event.

    So a human-attributed revision has to be constructible -- if the only way to record one were
    to edit the projection, the rule would be unfollowable rather than merely unenforced. The
    actor is recorded; the policy still authorises it.
    """
    corrected = event(
        actor_id="act:prof-lin",
        rationale_artifact_or_record_ref="art:sha256:...",
    )
    assert corrected.actor_id == "act:prof-lin"
    assert corrected.rationale_artifact_or_record_ref is not None


def test_the_event_exposes_no_mutation_helper():
    """There must be no supported way to turn one recorded revision into a different one.

    Pinned rather than assumed: a `with_state`/`apply`/`update` helper is exactly what someone
    adds when a projection looks wrong, and it would make the append-only rule advisory.
    """
    for forbidden in ("update", "apply", "with_state", "set_state", "mutate"):
        assert not hasattr(BeliefRevisionEvent, forbidden), forbidden
