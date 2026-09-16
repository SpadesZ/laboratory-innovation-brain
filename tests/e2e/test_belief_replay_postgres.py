"""T-EPI-003: quarantine a triggering attestation, replay, and the projection changes.

    §26    EPI-003 | T-EPI-003 | e2e | 隔離 triggering attestation 後 replay，
           EpistemicState 投影改變且 history 保留。
    §6.18  ... -> replay BeliefRevisionEvent, 略過被隔離的 triggering attestation
           -> 得到可驗證的新 EpistemicStateProjection -> 不得靠手改 current status

The whole chain, through the real stores and the real database: a registered policy authorises two
transitions, the events are appended with real attestation references, the projection is replayed
out of PostgreSQL, one extractor version is quarantined, the projection is replayed again and
differs -- and the event log is byte-for-byte what it was.

The last clause is the one that distinguishes a rollback from a hand edit, so it is asserted rather
than assumed.

WHAT THIS USED TO SAY, AND WHY IT NO LONGER DOES. Until M0b closure this docstring recorded that
the module produced `BeliefProjection` -- a type with no `belief_level` and no
`unresolved_conflicts` -- and that §26's "EpistemicState 投影" was therefore only half met. EPI-004
and EPI-006 landed, the reducer now returns §17.13's `EpistemicStateProjection` with every field it
declares, and the note is kept in this form rather than deleted so the change is visible.

`belief_level` is present and always `None`. §17.13 marks it optional, §8.1 only *建議s* an ordinal
LOW/MEDIUM/HIGH and declares no thresholds, and "evidence quality dimensions" is a DomainPack
judgment -- so a level computed in core would be a scientific verdict in prose rather than in a
versioned policy (AGT-016). Recorded as a known limitation in `docs/implementation/M0b-readiness.md`
rather than papered over here.
"""

from __future__ import annotations

import datetime as dt

import pytest

from lab_brain.core.belief import (
    SkipReason,
    admit_hypothesis,
    authorize_transition,
    quarantined_by_extractor_version,
    record_transition,
    replay,
    verified_history,
)
from lab_brain.core.models import (
    BeliefState,
    HypothesisView,
    IndependenceSummary,
    RelationJudgment,
    RelationType,
    TransitionOutcome,
    TransitionPolicy,
)
from lab_brain.core.models.decision import BeliefTransitionDecision
from lab_brain.core.repositories import SqlBeliefEventStore, SqlTransitionPolicyStore
from lab_brain.core.repositories.belief_events import SqlBeliefTransitionDecisionStore
from tests.conftest_fixtures import make_artifact

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.requirement("EPI-003"),
    pytest.mark.spec_test("T-EPI-003"),
]

T0 = dt.datetime(2026, 9, 15, 13, 0, tzinfo=dt.UTC)
PROJECT = "prj:test"
HYP = "hyp:rs-contact-resistance"
TRACE = "trc:episode-rs"

#: §8's Hypothesis Admission policy: it backs a target's *first* event and nothing else.
#:
#: `is_admission=True` is what makes admission a separate path rather than a hole in the transition
#: gate -- `admit_hypothesis` requires it, `record_transition` refuses it, and migration 005c
#: enforces the pairing in the database. The full §8 certificate (mechanism, prediction, falsifier)
#: is `EPI-001` in M3; this records only the resulting state change.
GENESIS = TransitionPolicy(
    policy_id="pol:admission",
    version="1.0.0",
    from_state=BeliefState.DRAFT,
    candidate_to_state=BeliefState.ACTIVE,
    is_admission=True,
)
ADMIT = TransitionPolicy(
    policy_id="pol:challenge",
    version="1.0.0",
    from_state=BeliefState.ACTIVE,
    candidate_to_state=BeliefState.CHALLENGED,
    required_relation_types=(RelationType.CONTRADICTS,),
)
PROMOTE = TransitionPolicy(
    policy_id="pol:promote",
    version="1.0.0",
    from_state=BeliefState.CHALLENGED,
    candidate_to_state=BeliefState.SUPPORTED,
    required_relation_types=(RelationType.SUPPORTS,),
)


def _authorize(
    connection,  # type: ignore[no-untyped-def]
    policy: TransitionPolicy,
    decision_id: str,
) -> BeliefTransitionDecision:
    """A real §17.14.1 authorization, evaluated and then stored (`v3.3-a12`).

    It has to be a real one end to end: `record_transition` re-derives it, and the database
    requires the row to exist before the event may reference it. The relation below is built to
    satisfy whatever `required_relation_types` the policy declares, so the ALLOW is earned rather
    than asserted -- an `_allow()` helper that fabricated the verdict is exactly what this slice
    removed.
    """
    supporting = RelationJudgment(
        relation_id=f"rel:{decision_id.split(':')[-1]}",
        from_entity_id="att:clean",
        to_entity_id=HYP,
        relation_type=policy.required_relation_types[0],
        project_id=PROJECT,
        supporting_attestation_ids=("att:clean",),
    )
    decision = authorize_transition(
        decision_id=decision_id,
        policy=policy,
        hypothesis=HypothesisView(
            hypothesis_id=HYP, project_id=PROJECT, current_state=policy.from_state
        ),
        admitted_relations=(supporting,),
        independence_summary=IndependenceSummary(independent_count=2),
        candidate_to_state=policy.candidate_to_state,
        created_at=T0,
    )
    assert decision.result is TransitionOutcome.ALLOW, decision.evaluated.reason_code
    return SqlBeliefTransitionDecisionStore(connection).record(decision)


@pytest.fixture
def world(db):  # type: ignore[no-untyped-def]
    """Two registered policies and two attestations from different extractor versions.

    Real attestation rows, because a triggering reference is a foreign key and §6.18's rollback is
    the join from a contaminated extractor version to the events it triggered.
    """
    artifact = make_artifact(b"belief replay fixture")
    db.execute(
        "INSERT INTO artifacts (artifact_id, content_hash, uri, media_type, source_origin,"
        " lineage_id, lineage_revision) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            artifact.artifact_id,
            artifact.content_hash,
            artifact.uri,
            artifact.media_type,
            artifact.source_origin.value,
            artifact.lineage_id,
            artifact.lineage_revision,
        ),
    )
    db.execute("INSERT INTO claims (claim_id, normalized_proposition) VALUES ('clm:1', 'rs high')")
    db.execute(
        "INSERT INTO condition_schemas (domain, schema_id, version, json_schema,"
        " comparator_version) VALUES ('core', 'sch_test', '1.0.0',"
        ' \'{"type": "object", "properties": {}}\'::jsonb, \'1.0.0\')'
    )
    for attestation_id, extractor_version in (("att:clean", "2.0.0"), ("att:tainted", "1.0.0")):
        db.execute(
            "INSERT INTO attestations (attestation_id, claim_id, epistemic_type,"
            " source_artifact_id, locator, conditions, conditions_schema_version, project_id,"
            " extractor_version, extraction_provenance)"
            " VALUES (%s, 'clm:1', 'REPORTED', %s, 'p.1', '{}'::jsonb, 'core/sch_test@1.0.0',"
            " %s, %s, %s::jsonb)",
            (
                attestation_id,
                artifact.artifact_id,
                PROJECT,
                extractor_version,
                '{"extractor_id": "ext:cj", "extractor_version": "' + extractor_version + '"}',
            ),
        )
    policies = SqlTransitionPolicyStore(db)
    policies.register(GENESIS)
    policies.register(ADMIT)
    policies.register(PROMOTE)
    return db


def _genesis(store: SqlBeliefEventStore, connection) -> None:  # type: ignore[no-untyped-def]
    """Seed the hypothesis's first state through §8's admission gate.

    Goes through `admit_hypothesis`, not around the store: before P7-fix this had to be appended
    raw, because `record_transition` correctly refuses a target's first event and there was no
    other gate. That raw append was the audit's first finding.
    """
    store.append(
        admit_hypothesis(
            event_id="bre:0",
            policy=GENESIS,
            project_id=PROJECT,
            hypothesis_id=HYP,
            prior=replay(PROJECT, HYP, ()),
            occurred_at=T0 - dt.timedelta(hours=1),
            trace_id=TRACE,
            triggering_attestations=(_attestation(connection, "att:clean"),),
        )
    )


def _verified(connection, events):  # type: ignore[no-untyped-def]
    """The production read seam: stored events -> stores -> re-derived authorization -> replay.

    This is what the P8 audit found missing. Every `replay` below goes through it, so the e2e path
    exercises the same gate a production projector would rather than a shortcut only tests take.
    """
    return verified_history(
        project_id=PROJECT,
        target_id=HYP,
        events=events,
        decisions=SqlBeliefTransitionDecisionStore(connection),
        policies=SqlTransitionPolicyStore(connection),
    )


def test_quarantine_then_replay_changes_the_projection_and_keeps_the_history(world):
    """The pass condition, end to end, read back out of PostgreSQL."""
    events = SqlBeliefEventStore(world)
    _genesis(events, world)

    # --- two policy-authorised revisions, appended through the gate ---
    first = record_transition(
        event_id="bre:1",
        authorization=_authorize(world, ADMIT, "dec:challenge"),
        policy=ADMIT,
        hypothesis=HypothesisView(
            hypothesis_id=HYP, project_id=PROJECT, current_state=BeliefState.ACTIVE
        ),
        candidate_to_state=BeliefState.CHALLENGED,
        prior=replay(PROJECT, HYP, _verified(world, events.history(PROJECT, HYP))),
        occurred_at=T0,
        trace_id=TRACE,
        triggering_attestations=(_attestation(world, "att:clean"),),
    )
    events.append(first)

    second = record_transition(
        event_id="bre:2",
        authorization=_authorize(world, PROMOTE, "dec:promote"),
        policy=PROMOTE,
        hypothesis=HypothesisView(
            hypothesis_id=HYP, project_id=PROJECT, current_state=BeliefState.CHALLENGED
        ),
        candidate_to_state=BeliefState.SUPPORTED,
        prior=replay(PROJECT, HYP, _verified(world, events.history(PROJECT, HYP))),
        occurred_at=T0 + dt.timedelta(hours=1),
        trace_id=TRACE,
        triggering_attestations=(_attestation(world, "att:tainted"),),
    )
    events.append(second)

    # --- the projection before anything is quarantined ---
    history = SqlBeliefEventStore(world).history(PROJECT, HYP)
    assert [event.event_id for event in history] == ["bre:0", "bre:1", "bre:2"]
    before = replay(PROJECT, HYP, _verified(world, history))
    assert before.current_state is BeliefState.SUPPORTED
    assert before.last_event_id == "bre:2"
    assert before.skipped == ()

    # --- §6.18 step 1: quarantine everything that extractor version produced ---
    quarantined = quarantined_by_extractor_version(
        [_attestation(world, "att:clean"), _attestation(world, "att:tainted")],
        {"ext:cj": "1.0.0"},
    )
    assert quarantined == {"att:tainted"}, "selection is on (extractor, version), not version alone"

    # --- §6.18 step 2: replay, skipping the quarantined triggers ---
    after = replay(PROJECT, HYP, _verified(world, history), quarantined_attestation_ids=quarantined)
    assert after.current_state is BeliefState.CHALLENGED, (
        "the promotion to SUPPORTED rested on evidence from the contaminated extractor version"
    )
    assert after.applied == ("bre:0", "bre:1")
    assert after.skipped == (("bre:2", SkipReason.QUARANTINED_TRIGGER),)

    # --- and the history is untouched. This is what makes it a rollback, not a hand edit ---
    unchanged = SqlBeliefEventStore(world).history(PROJECT, HYP)
    assert [event.event_id for event in unchanged] == ["bre:0", "bre:1", "bre:2"]
    assert unchanged == history, "replay must not have rewritten a single event"
    rows = world.execute(
        "SELECT to_state FROM belief_revision_events WHERE event_id = 'bre:2'"
    ).fetchone()
    assert rows[0] == "SUPPORTED", "the stored event still says what it always said"


def test_the_current_state_cannot_be_repaired_by_hand(world):
    """§6.18: 不得靠手改 current status.

    There is no current-status row to edit -- the state is a projection -- and the events the
    projection is derived from refuse UPDATE. Both halves asserted, because a system that stored
    the state would let the second half be true and the rule still be broken.
    """
    events = SqlBeliefEventStore(world)
    _genesis(events, world)
    events.append(
        record_transition(
            event_id="bre:1",
            authorization=_authorize(world, ADMIT, "dec:challenge"),
            policy=ADMIT,
            hypothesis=HypothesisView(
                hypothesis_id=HYP, project_id=PROJECT, current_state=BeliefState.ACTIVE
            ),
            candidate_to_state=BeliefState.CHALLENGED,
            prior=replay(PROJECT, HYP, _verified(world, events.history(PROJECT, HYP))),
            occurred_at=T0,
            trace_id=TRACE,
            triggering_attestations=(_attestation(world, "att:clean"),),
        )
    )

    stored = world.execute(
        "SELECT count(*) FROM information_schema.tables"
        " WHERE table_schema = 'public' AND table_name LIKE '%epistemic_state%'"
    ).fetchone()
    assert stored[0] == 0, "there is no stored current-state row to edit"

    import psycopg

    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        world.execute(
            "UPDATE belief_revision_events SET to_state = 'SUPPORTED' WHERE event_id = 'bre:1'"
        )


def _attestation(db, attestation_id: str):  # type: ignore[no-untyped-def]
    """Load an Attestation the way a caller would, so the fixture and the code agree on its shape."""
    from lab_brain.core.models import Attestation

    row = db.execute(
        "SELECT attestation_id, claim_id, epistemic_type, source_artifact_id, locator,"
        " conditions, conditions_schema_version, project_id, extractor_version,"
        " extraction_provenance FROM attestations WHERE attestation_id = %s",
        (attestation_id,),
    ).fetchone()
    assert row is not None, f"fixture did not create {attestation_id}"
    return Attestation.model_validate(
        {
            "attestation_id": row[0],
            "claim_id": row[1],
            "epistemic_type": row[2],
            "source_artifact_id": row[3],
            "locator": row[4],
            "conditions": row[5],
            "conditions_schema_version": row[6],
            "project_id": row[7],
            "extractor_version": row[8],
            "extraction_provenance": row[9],
        }
    )
