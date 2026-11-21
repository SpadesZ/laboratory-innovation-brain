"""G0 trust boundaries, round 5: one definition of a belief event that counts.

Round 4 (`012t`) gave the schema owner a quarantine: a quarantined belief event, or every event
under a quarantined transition policy, "decides nothing". The product's Python projection
(`BeliefEpisode.project`) honours it. These tests ask whether every OTHER reader of the belief
history -- the SQL confirmation rule, the database's root-cause checks, the write gate, EPI-001's
competing-set count -- reads the same history the projection reads. Where they disagree, a row the
owner withdrew still decides something somewhere, or blocks something the owner meant to release.

Q1  `cwg_state` (the SQL confirmation rule, `012p`) reads the latest raw event, quarantined or not.
Q2  `011l`'s root-cause check (a CONFIRMED failure analysis needs a SUPPORTED cause) reads the
    latest raw event, quarantined or not.
Q3  the `011z` gate's time bound reads the subject's latest raw event: a quarantined forged event
    dated in the future still refuses every honest transition until that date.
Q4  the `011z` gate records a new transition under a quarantined policy, which the projection then
    skips: a write the database accepts and the product never counts.
Q5  EPI-001 (`011j`/`012n` and `HypothesisRevisionGate`) counts a quarantined admission as a
    competing hypothesis.
Q6  `002e`'s external-snapshot quarantine (the stored §6.18 selection) is read by no belief
    reader: the product projection keeps an event its quarantined attestation triggered.
Q7  the same shape for independence: the `011z` gate bounds a WORK count by its own definition of
    an evidence line (every current relation, a run-less attestation counting as a line), the
    product counts another (the admitted relations, a run-less attestation unknown), so the gate
    admits a count the product would never compute.

Every attack is made through the deployment's least-privilege services' role where the services
write, and as the schema owner where only the owner can (a quarantine, a row from before the
revocation). Engineering evidence only. G0 is NOT PASSED.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import pytest

from lab_brain.core.models import BeliefState, RelationType, TransitionPolicy
from lab_brain.core.models.enums import IndependenceBasis
from lab_brain.core.models.transition import IndependenceSummary
from lab_brain.core.repositories.evidence import SqlRelationStore
from tests.e2e.test_g0_boundary_round4_postgres import (
    _attempt,
    _events,
    _forger,
    _services_episode,
    _write,
)
from tests.e2e.test_g0_screening_independence_postgres import Guarded
from tests.e2e.test_g0_screening_independence_postgres import guarded as guarded
from tests.e2e.test_g0_screening_independence_postgres import standin as standin
from tests.e2e.test_g0_security_assurance_postgres import _accepting, _episode
from tests.e2e.test_g0_trust_boundaries_postgres import (
    SUPPORT_ONLY,
    _admin,
    _honest,
    _owner_registers,
    _read,
    _stored_support,
    _unscreened,
)
from tests.e2e.test_research_episode_postgres import PROJECT
from tests.integration import test_g0_spend_admin_postgres as _roles

pytestmark = pytest.mark.postgres

su = _roles.su
roles = _roles.roles


def _quarantine(g: Guarded, kind: str, ref: str, why: str) -> None:
    """The owner's quarantine through the operator command (`lab-brain admin quarantine`)."""
    status, out = _admin(g.db, "quarantine", kind, ref, "--reason", why, "--actor", g.actor)
    assert status == 0, out


def _forge(g: Guarded, hypothesis: str, writer: Any, *, at: str = "now()") -> str:
    """An honest NEED_MORE_EVIDENCE decision copied by `writer` as an ALLOW, and the event
    ACTIVE -> SUPPORTED citing the copy, dated `at` (an SQL expression). The writer is the services'
    role while it holds row writes on the belief tables (before the Owner's revocation), the owner
    otherwise (a row from before it)."""
    from lab_brain.core.canonical_json import canonicalize

    policy = _owner_registers(g, SUPPORT_ONLY)
    honest = _attempt(
        _episode(g.db, SqlRelationStore(g.db, support_verifier=_accepting), g.keys.trust),
        g,
        hypothesis,
        policy,
    )
    assert honest.event is None and honest.authorization.result.value == "NEED_MORE_EVIDENCE"
    evaluated = honest.authorization.evaluated.model_dump(mode="json")
    evaluated["outcome"] = "ALLOW"
    forged = f"dec:r5-forged-{uuid.uuid4().hex[:8]}"
    event = f"bre:r5-forged-{uuid.uuid4().hex[:8]}"
    writer.execute(
        "INSERT INTO belief_transition_decisions (decision_id, project_id, subject_id,"
        " decision_type, result, policy_id, policy_version, from_state, to_state,"
        " authority_policy_id, authority_policy_version, decision_input_snapshot, input_hash,"
        " evaluated_decision, episode_id, actor_id, created_at)"
        " SELECT %s, project_id, subject_id, decision_type, 'ALLOW', policy_id, policy_version,"
        " from_state, to_state, authority_policy_id, authority_policy_version,"
        " decision_input_snapshot, input_hash, %s, episode_id, actor_id, created_at"
        " FROM belief_transition_decisions WHERE decision_id = %s",
        (forged, canonicalize(evaluated), honest.authorization.decision_id),
    )
    writer.execute(
        "SELECT belief_revision_event_append(%s, %s, 'HYPOTHESIS', %s, 'ACTIVE', 'SUPPORTED',"
        f" %s, %s, %s, %s, %s, NULL, NULL, {at}, 'trc:r5-forged', %s)",
        (
            event,
            PROJECT,
            hypothesis,
            [g.attestation],
            [],
            policy.policy_id,
            policy.version,
            g.actor,
            forged,
        ),
    )
    return event


def _forged_and_quarantined(g: Guarded, roles: Any, *, at: str = "now()") -> tuple[str, str]:
    """A hypothesis whose forged promotion the owner has quarantined: (hypothesis, event)."""
    hypothesis = _unscreened(g)
    with roles.connect(roles.app) as app:
        writer, _who = _forger(g, app)
        event = _forge(g, hypothesis, writer, at=at)
    _quarantine(g, "event", event, "forged authorization (G0 round 5)")
    return hypothesis, event


# =============================================================================================
# Q1, Q2: the SQL readers of "the current belief state"
# =============================================================================================


def test_q1_the_sql_confirmation_rule_reads_the_state_the_projection_reads(guarded, roles):
    g = guarded
    hypothesis, event = _forged_and_quarantined(g, roles)
    python = _read(_honest(g), hypothesis)
    ((sql,),) = g.db.execute("SELECT cwg_state(%s, %s)", (PROJECT, hypothesis)).fetchall()
    print(f"Q1 quarantined {event}: projection -> {python}; cwg_state -> {sql}")
    assert python == BeliefState.ACTIVE.value
    assert sql == python


def test_q2_a_root_cause_is_not_confirmed_on_a_quarantined_promotion(guarded, roles):
    """The services' role records a CONFIRMED failure analysis naming the hypothesis whose only
    promotion the owner quarantined. The database must refuse it because the cause is not
    SUPPORTED -- the reading every Python reader gives -- not for some later reason."""
    g = guarded
    hypothesis, _event = _forged_and_quarantined(g, roles)
    assert _read(_honest(g), hypothesis) == BeliefState.ACTIVE.value
    with roles.connect(roles.app) as app:
        _, refused = _write(
            lambda: app.execute(
                "INSERT INTO failure_analyses (failure_analysis_id, project_id, episode_id,"
                " symptom, expected_behavior, observed_behavior, candidate_causes,"
                " confirmed_root_cause, root_cause_evidence_ids, failure_class,"
                " resolution_status, created_at)"
                " VALUES (%s, %s, %s, 'loss high', 'low loss', 'high loss', %s, %s, %s,"
                " 'contact', 'CONFIRMED', now())",
                (
                    f"fa:r5-{uuid.uuid4().hex[:8]}",
                    PROJECT,
                    g.episode,
                    [hypothesis],
                    hypothesis,
                    [g.attestation],
                ),
            )
        )
    print(f"Q2 CONFIRMED on a quarantined promotion: {refused!r}")
    assert refused is not None
    assert "current belief state is ACTIVE" in str(refused), refused


# =============================================================================================
# Q3, Q4: the write gate
# =============================================================================================


def test_q3_a_quarantined_future_event_does_not_block_honest_transitions(guarded, roles):
    """A forged promotion dated 30 days ahead (a row from before the gate), quarantined by the
    owner. The projection ignores it; an honest promotion recorded now must go through."""
    g = guarded
    hypothesis, event = _forged_and_quarantined(g, roles, at="now() + interval '30 days'")
    assert _read(_honest(g), hypothesis) == BeliefState.ACTIVE.value
    with roles.connect(roles.app) as app:
        _stored_support(app, g, hypothesis)
        written, refused = _write(
            lambda: _attempt(_services_episode(app, g), g, hypothesis, SUPPORT_ONLY)
        )
    print(f"Q3 honest promotion after quarantining {event} (+30 days): refused={refused!r}")
    assert refused is None, refused
    assert written.event is not None
    assert _read(_honest(g), hypothesis) == BeliefState.SUPPORTED.value


QUARANTINED_RULE = TransitionPolicy(
    policy_id="policy:g0-r5-promote-withdrawn",
    version="1.0.0",
    from_state=BeliefState.ACTIVE,
    candidate_to_state=BeliefState.SUPPORTED,
    required_relation_types=(RelationType.SUPPORTS,),
)


def test_q4_the_gate_refuses_a_transition_under_a_quarantined_policy(guarded, roles):
    g = guarded
    hypothesis = _unscreened(g)
    policy = _owner_registers(g, QUARANTINED_RULE)
    _quarantine(g, "policy", f"{policy.policy_id}@{policy.version}", "withdrawn rule (G0 round 5)")
    with roles.connect(roles.app) as app:
        _stored_support(app, g, hypothesis)
        written, refused = _write(
            lambda: _attempt(_services_episode(app, g), g, hypothesis, policy)
        )
    recorded = [e for e in _events(g, hypothesis) if e[1] == BeliefState.SUPPORTED.value]
    print(f"Q4 under a quarantined policy: refused={refused!r}; recorded={recorded}")
    assert _read(_honest(g), hypothesis) == BeliefState.ACTIVE.value
    assert refused is not None and "quarantined" in str(refused), (written, refused)
    assert recorded == []


# =============================================================================================
# Q5: EPI-001's competing set
# =============================================================================================


def _rivals(g: Guarded, hypothesis: str) -> list[tuple[str, str]]:
    """(rival, its genesis event) for every other member of the hypothesis's set."""
    return [
        (str(r[0]), str(r[1]))
        for r in g.db.execute(
            "SELECT h.hypothesis_id, e.event_id FROM hypotheses h"
            " JOIN hypotheses me ON me.hypothesis_set_id = h.hypothesis_set_id"
            "  AND me.project_id = h.project_id"
            " JOIN belief_revision_events e ON e.project_id = h.project_id"
            "  AND e.target_id = h.hypothesis_id AND e.from_state IS NULL"
            " WHERE me.project_id = %s AND me.hypothesis_id = %s AND h.hypothesis_id <> %s"
            " ORDER BY h.hypothesis_id",
            (PROJECT, hypothesis, hypothesis),
        ).fetchall()
    ]


def test_q5_a_quarantined_admission_is_not_a_competing_hypothesis(guarded, roles):
    """Every rival's admission is withdrawn by the owner (forged straw men admitted to satisfy
    EPI-001). The projection reads each rival as never admitted; promoting the one remaining
    hypothesis of a root-cause set must be refused (至少維護 2 個 competing hypotheses)."""
    g = guarded
    hypothesis = _unscreened(g)
    rivals = _rivals(g, hypothesis)
    assert len(rivals) >= 1
    for _rival, genesis in rivals:
        _quarantine(g, "event", genesis, "straw-man admission (G0 round 5)")
    assert all(_read(_honest(g), rival) == "NONE" for rival, _ in rivals)
    policy = _owner_registers(g, SUPPORT_ONLY)
    with roles.connect(roles.app) as app:
        _stored_support(app, g, hypothesis)
        written, refused = _write(
            lambda: _attempt(_services_episode(app, g), g, hypothesis, policy)
        )
    print(f"Q5 promotion with every rival's admission quarantined: refused={refused!r}")
    assert refused is not None and "competing" in str(refused), (written, refused)
    assert _read(_honest(g), hypothesis) == BeliefState.ACTIVE.value


# =============================================================================================
# Q6: the stored §6.18 selection (external-snapshot quarantine, `002e`)
# =============================================================================================


def test_q6_an_event_triggered_by_quarantined_external_evidence_is_skipped(guarded, roles):
    """An event triggered by an attestation whose external snapshot was quarantined afterwards
    (`002e`): the stored selection names it, and the product projection must skip the event
    (QUARANTINED_TRIGGER), as the SQL readers must."""
    g = guarded
    hypothesis = _unscreened(g)
    attestation = _external_attestation(g)
    policy = _owner_registers(g, SUPPORT_ONLY)
    with roles.connect(roles.app) as app:
        _stored_support(app, g, hypothesis)
        written = g_attempt_with_trigger(app, g, hypothesis, policy, attestation)
    assert written.event is not None
    assert _read(_honest(g), hypothesis) == BeliefState.SUPPORTED.value
    _quarantine_snapshot_of(g, attestation)
    projection = _honest(g).project(project_id=PROJECT, hypothesis_id=hypothesis)
    ((sql,),) = g.db.execute("SELECT cwg_state(%s, %s)", (PROJECT, hypothesis)).fetchall()
    print(
        f"Q6 after quarantining the snapshot behind {attestation}: projection -> "
        f"{projection.current_state}; skipped {projection.skipped}; cwg_state -> {sql}"
    )
    assert (written.event.event_id, "QUARANTINED_TRIGGER") in {
        (e, r.value) for e, r in projection.skipped
    }
    assert projection.current_state is BeliefState.ACTIVE
    assert sql == BeliefState.ACTIVE.value


def _external_attestation(g: Guarded) -> str:
    """An attestation of the episode's project admitted from an external snapshot (`002d`)."""
    from tests.e2e.round5_fixtures import external_attestation

    return external_attestation(g.db, PROJECT)


def _quarantine_snapshot_of(g: Guarded, attestation: str) -> None:
    from lab_brain.core.repositories.external_sources import SqlExternalSourceStore

    ((snapshot,),) = g.db.execute(
        "SELECT method ->> 'snapshot_id' FROM attestations WHERE attestation_id = %s",
        (attestation,),
    ).fetchall()
    SqlExternalSourceStore(g.db).quarantine(PROJECT, snapshot, "QUARANTINED_BY_OPERATOR")


def g_attempt_with_trigger(
    app: Any, g: Guarded, hypothesis: str, policy: TransitionPolicy, trigger: str
) -> Any:
    from lab_brain.core.repositories.evidence import SqlAttestationStore
    from tests.e2e.test_g0_security_assurance_postgres import AUTHORITY

    return _services_episode(app, g).attempt_transition(
        project_id=PROJECT,
        hypothesis_id=hypothesis,
        policy_id=policy.policy_id,
        policy_version=policy.version,
        candidate_to_state=BeliefState.SUPPORTED,
        stakes="HIGH",
        occurred_at=dt.datetime.now(dt.UTC),
        trace_id=f"trc:r5-{uuid.uuid4().hex[:8]}",
        episode_id=g.episode,
        actor_id=g.actor,
        authority_policy_ref=(AUTHORITY.policy_id, AUTHORITY.policy_version),
        triggering_attestations=(SqlAttestationStore(g.db).get(PROJECT, trigger),),
    )


def test_q5_the_products_competing_set_reader_leaves_out_quarantined_admissions(guarded, tmp_path):
    """The Python half of Q5: the `HypothesisRevisionGate` the research service wires into its
    reviser (`ResearchEpisodeService._brain`) counts as admitted exactly the rivals the
    projection reads as admitted."""
    from lab_brain.core.repositories import SqlBeliefEventStore
    from lab_brain.core.repositories.debate import SqlDebateStore
    from lab_brain.core.repositories.evidence import SqlAttestationStore
    from lab_brain.core.repositories.hypotheses import SqlHypothesisStore
    from lab_brain.research.service import ResearchEpisodeService
    from lab_brain.research.vertical import load_vertical_factory
    from lab_brain.storage.artifacts.local import LocalArtifactStore

    g = guarded
    hypothesis = _unscreened(g)
    rivals = _rivals(g, hypothesis)
    withdrawn = rivals[: len(rivals) // 2 + 1]
    for _rival, genesis in withdrawn:
        _quarantine(g, "event", genesis, "straw-man admission (G0 round 5)")
    service = ResearchEpisodeService(
        connection=g.db,
        artifact_store=LocalArtifactStore((tmp_path / "artifacts").resolve()),
        vertical_factory=load_vertical_factory("silicon_photonics"),
    )
    vertical, _outputs = service._vertical()
    brain, _ = service._brain(
        vertical,
        None,  # type: ignore[arg-type]
        SqlHypothesisStore(g.db),
        SqlBeliefEventStore(g.db),
        SqlDebateStore(g.db),
        SqlAttestationStore(g.db),
        None,  # type: ignore[arg-type]
    )
    counted = {r for r, _ in rivals if brain._gate._admitted(PROJECT, r)}
    projected = {r for r, _ in rivals if _read(_honest(g), r) != "NONE"}
    print(
        f"Q5 Python: revision gate counts {len(counted)} rivals; projection admits {len(projected)}"
    )
    assert projected == {r for r, _ in rivals} - {r for r, _ in withdrawn}
    assert counted == projected


# =============================================================================================
# Q7: independence -- the gate's count and the product's count are two definitions
# =============================================================================================

TWO_LINES = TransitionPolicy(
    policy_id="policy:g0-r5-promote-two-lines",
    version="1.0.0",
    from_state=BeliefState.ACTIVE,
    candidate_to_state=BeliefState.SUPPORTED,
    required_relation_types=(RelationType.SUPPORTS,),
    min_independent_attestations=2,
    independence_basis=IndependenceBasis.WORK,
)


def _support_with_a_runless_attestation(app: Any, g: Guarded, hypothesis: str) -> Any:
    """A stored SUPPORTS resting on the episode's inspection reading (one execution) and an
    attestation no stored run stands behind (an external literature reading)."""
    from lab_brain.core.models.relation import RelationJudgment
    from tests.e2e.test_g0_trust_boundaries_postgres import _inspection

    observation, inspection = _inspection(g)
    runless = _external_attestation(g)
    relation = RelationJudgment(
        relation_id=f"rel:r5-{uuid.uuid4().hex[:10]}",
        from_entity_id=observation,
        to_entity_id=hypothesis,
        relation_type=RelationType.SUPPORTS,
        supporting_attestation_ids=(inspection, runless),
        project_id=PROJECT,
    )
    SqlRelationStore(app).add(relation)
    return relation


def test_q7_the_gate_counts_independence_as_the_product_counts_it(guarded, roles):
    """The product's own count over this support is ONE line (the inspection run) and one
    unknown. The services' role claims two; the gate must refuse it."""
    g = guarded
    hypothesis = _unscreened(g)
    policy = _owner_registers(g, TWO_LINES)
    with roles.connect(roles.app) as app:
        _support_with_a_runless_attestation(app, g, hypothesis)
        written, refused = _write(
            lambda: _attempt(
                _services_episode(app, g),
                g,
                hypothesis,
                policy,
                independence=IndependenceSummary(basis=IndependenceBasis.WORK, independent_count=2),
            )
        )
    print(f"Q7 two lines claimed over one run and one run-less attestation: refused={refused!r}")
    assert refused is not None and "evidence line" in str(refused), (written, refused)
    assert _read(_honest(g), hypothesis) == BeliefState.ACTIVE.value


# =============================================================================================
# After the fix: the root-cause trace reads the history that counts (`counted_history`)
# =============================================================================================


def test_the_root_cause_trace_follows_the_promotion_that_counts(guarded, roles):
    """A forged promotion citing no relation, dated a minute ahead and quarantined by the owner,
    then an honest promotion.
    The trace the verification loop runs (`trace_root_cause` over the research service's
    `events.counted_history`) follows the honest event; over the raw rows it stopped at the forged
    one (NO_SUPPORTING_RELATION) although every reader of the state reads the honest one."""
    from lab_brain.core.repositories import SqlBeliefEventStore
    from lab_brain.core.repositories.jobs import SqlJobStore
    from lab_brain.core.root_cause import RootCauseRefused, trace_root_cause
    from lab_brain.storage.postgres.verification_evidence import SqlEvidenceSink

    g = guarded
    hypothesis = _unscreened(g)
    policy = _owner_registers(g, SUPPORT_ONLY)
    with roles.connect(roles.app) as app:
        writer, _who = _forger(g, app)
        forged = _forge(g, hypothesis, writer, at="now() + interval '1 minute'")
        _quarantine(g, "event", forged, "forged later promotion (G0 round 5)")
        _stored_support(app, g, hypothesis)
        honest = _attempt(_services_episode(app, g), g, hypothesis, policy)
    assert honest.event is not None
    assert _read(_honest(g), hypothesis) == BeliefState.SUPPORTED.value
    events = SqlBeliefEventStore(g.db)
    evidence = SqlEvidenceSink(connection=g.db, outputs=None)  # type: ignore[arg-type]

    def trace(history: Any) -> Any:
        try:
            return trace_root_cause(
                project_id=PROJECT,
                hypothesis_id=hypothesis,
                history=history,
                relation=evidence.relation,
                attestation=evidence.attestation,
                observation=evidence.observation,
                run=SqlJobStore(g.db).get_run,
                artifact_exists=evidence.artifact_exists,
            )
        except RootCauseRefused as refused:
            return refused

    raw, counted = trace(events.history), trace(events.counted_history)
    print(f"trace over raw rows -> {raw!r}; over counted history -> {counted!r}")
    assert isinstance(raw, RootCauseRefused) and forged in str(raw)
    assert not isinstance(counted, RootCauseRefused), counted
    assert counted.event_id == honest.event.event_id
    assert counted.links
