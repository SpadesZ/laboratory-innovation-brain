"""One definition of a belief event that counts: the database's `belief_replay` (`005f`) and the
product's projection (`BeliefEpisode.project` -> `core.belief.replay`) are held equal by enumeration.

A stored history with a cascade in it (a later move that counts only once an earlier one is gone)
and one event triggered by external evidence; then every combination of the exclusions the
database stores -- the owner's quarantine of each event and of each transition policy (`012t`),
and the quarantine of the external snapshot behind the trigger (`002e`) -- 2**9 = 512 cases, each
inside a transaction that is rolled back. For each case:

    * SQL `belief_replay` counts exactly the events the projection applies, and skips each other
      event for the same reason;
    * `belief_counted_state` and `cwg_state` (the SQL confirmation rule) equal the projection's
      current state;
    * `SqlBeliefEventStore.counted_history` (what EPI-001's revision gate and the root-cause trace
      read) is the projection's applied events, in order;
    * the in-memory store's `counted_history` over the counted events is itself.

And the independence count: `belief_evidence_lines` (the gate's bound) equals the product's own
count (`VerificationLoop._independence`) for every subset of the stored attestations of a run, an
attestation of another run, and run-less ones.

Engineering evidence only. G0 is NOT PASSED.
"""

from __future__ import annotations

import datetime as dt
import itertools
import types
from typing import Any

import psycopg
import pytest

from lab_brain.core.belief import SkipReason
from lab_brain.core.episode import BeliefEpisode
from lab_brain.core.models import TransitionPolicy
from lab_brain.core.repositories import SqlBeliefEventStore, SqlTransitionPolicyStore
from lab_brain.core.repositories.belief_events import (
    SqlBeliefTransitionDecisionStore,
    counted_events,
)
from lab_brain.core.repositories.conflicts import SqlConflictStore
from tests.e2e.round5_fixtures import external_attestation
from tests.e2e.test_belief_replay_postgres import (
    ADMIT,
    GENESIS,
    HYP,
    PROJECT,
    PROMOTE,
    T0,
    _authorize,
    _genesis,
)
from tests.e2e.test_belief_replay_postgres import world as world
from tests.e2e.test_g0_screening_independence_postgres import guarded as guarded
from tests.e2e.test_g0_screening_independence_postgres import standin as standin
from tests.e2e.test_research_episode_postgres import PROJECT as RESEARCH_PROJECT

pytestmark = pytest.mark.postgres

ACTOR = "act:test"

#: After the genesis bre:0 (ACTIVE at T0 - 1h): bre:1 challenges, bre:2 promotes (triggered by the
#: external attestation), bre:3 challenges from ACTIVE again -- it counts only once bre:1 or bre:2
#: no longer does (the cascade) -- and bre:4 promotes after it.


def _append(
    db: Any, event_id: str, policy: TransitionPolicy, at: dt.datetime, trigger: str
) -> None:
    """A decision the policy really ALLOWs (recorded as before the gate), and its event, written
    by the owner with the 005d append: the history's shape, not the gate, is under test."""
    decision = _authorize(db, policy, f"dec:{event_id.split(':')[1]}")
    db.execute(
        "SELECT belief_revision_event_append(%s, %s, 'HYPOTHESIS', %s, %s, %s, %s, %s, %s, %s,"
        " %s, NULL, NULL, %s, 'trc:diff', %s)",
        (
            event_id,
            PROJECT,
            HYP,
            policy.from_state.value,
            policy.candidate_to_state.value,
            [trigger],
            [],
            policy.policy_id,
            policy.version,
            ACTOR,
            at,
            decision.decision_id,
        ),
    )


def _projection_reader(db: Any) -> BeliefEpisode:
    """The product's read path over the SQL stores (no relation re-check: the decisions here rest
    on contract-fixture relations, and the evidence check is R-1's, not this suite's)."""
    nothing = types.SimpleNamespace()
    return BeliefEpisode(
        policies=SqlTransitionPolicyStore(db),
        decisions=SqlBeliefTransitionDecisionStore(db),
        events=SqlBeliefEventStore(db),
        relations=nothing,  # type: ignore[arg-type]
        authority_classes=nothing,  # type: ignore[arg-type]
        conflicts=SqlConflictStore(db),
        reviews=nothing,  # type: ignore[arg-type]
        ids=nothing,  # type: ignore[arg-type]
    )


@pytest.fixture
def history(world: Any) -> tuple[Any, str]:
    db = world
    external = external_attestation(db, PROJECT)
    _genesis(SqlBeliefEventStore(db), db)
    _append(db, "bre:1", ADMIT, T0, "att:clean")
    _append(db, "bre:2", PROMOTE, T0 + dt.timedelta(hours=1), external)
    # An owner-registered rule for the branch the cascade can reach: ACTIVE -> CHALLENGED again.
    _append(db, "bre:3", ADMIT, T0 + dt.timedelta(hours=2), "att:clean")
    _append(db, "bre:4", PROMOTE, T0 + dt.timedelta(hours=3), "att:clean")
    return db, external


def _quarantine(db: Any, kind: str, subject: str, version: str = "") -> None:
    db.execute(
        "INSERT INTO owner_quarantines (subject_kind, subject_id, subject_version, reason,"
        " actor_id, quarantined_at, recorded_by) VALUES (%s, %s, %s, %s, %s, now(), '')",
        (kind, subject, version, "differential enumeration (G0 round 5)", ACTOR),
    )


EVENTS = ("bre:0", "bre:1", "bre:2", "bre:3", "bre:4")
POLICIES = tuple((p.policy_id, p.version) for p in (GENESIS, ADMIT, PROMOTE))

#: The history as built above, for the oracle: (event, policy, from, to); bre:2's trigger is the
#: external attestation.
SHAPE = (
    ("bre:0", GENESIS, None, "ACTIVE"),
    ("bre:1", ADMIT, "ACTIVE", "CHALLENGED"),
    ("bre:2", PROMOTE, "CHALLENGED", "SUPPORTED"),
    ("bre:3", ADMIT, "ACTIVE", "CHALLENGED"),
    ("bre:4", PROMOTE, "CHALLENGED", "SUPPORTED"),
)


def _oracle(bits: tuple[bool, ...]) -> tuple[tuple[str, ...], dict[str, str]]:
    """What the rule says, computed here from the toggles alone -- not from either reader -- so
    the enumeration checks the definition itself, not only that the two sides agree."""
    events_on = dict(zip(EVENTS, bits[: len(EVENTS)], strict=True))
    policies_on = dict(zip(POLICIES, bits[len(EVENTS) : -1], strict=True))
    snapshot_on = bits[-1]
    state: str | None = None
    applied: list[str] = []
    skipped: dict[str, str] = {}
    for event_id, policy, before, after in SHAPE:
        if events_on[event_id] or policies_on[(policy.policy_id, policy.version)]:
            skipped[event_id] = "OWNER_QUARANTINED"
        elif event_id == "bre:2" and snapshot_on:
            skipped[event_id] = "QUARANTINED_TRIGGER"
        elif before != state:
            skipped[event_id] = "PREDECESSOR_MISSING"
        else:
            applied.append(event_id)
            state = after
    return tuple(applied), skipped


def test_sql_belief_replay_equals_the_product_projection_for_every_exclusion(history):
    db, external = history
    ((snapshot,),) = db.execute(
        "SELECT method ->> 'snapshot_id' FROM attestations WHERE attestation_id = %s", (external,)
    ).fetchall()
    toggles = len(EVENTS) + len(POLICIES) + 1
    seen_states: set[str | None] = set()
    seen_reasons: set[str] = set()
    cases = 0
    for bits in itertools.product((False, True), repeat=toggles):
        with db.transaction() as tx:
            for on, event_id in zip(bits[: len(EVENTS)], EVENTS, strict=True):
                if on:
                    _quarantine(db, "BELIEF_EVENT", event_id)
            for on, (policy_id, version) in zip(bits[len(EVENTS) : -1], POLICIES, strict=True):
                if on:
                    _quarantine(db, "TRANSITION_POLICY", policy_id, version)
            if bits[-1]:
                db.execute(
                    "INSERT INTO external_snapshot_quarantine (snapshot_id, project_id,"
                    " reason_code) VALUES (%s, %s, 'QUARANTINED_BY_OPERATOR')",
                    (snapshot, PROJECT),
                )
            projection = _projection_reader(db).project(project_id=PROJECT, hypothesis_id=HYP)
            sql = db.execute(
                "SELECT event_id, counted, skip_reason FROM belief_replay(%s, %s)", (PROJECT, HYP)
            ).fetchall()
            counted = tuple(str(e) for e, ok, _ in sql if ok)
            skipped = {str(e): str(r) for e, ok, r in sql if not ok}
            python_skipped = {e: r.value for e, r in projection.skipped}
            assert (counted, skipped) == _oracle(bits), (bits, sql)
            assert counted == projection.applied, (bits, sql, projection)
            assert skipped == python_skipped, (bits, sql, projection)
            state = None if projection.current_state is None else projection.current_state.value
            ((counted_state, cwg),) = db.execute(
                "SELECT belief_counted_state(%s, %s), cwg_state(%s, %s)", (PROJECT, HYP) * 2
            ).fetchall()
            assert counted_state == cwg == state, (bits, counted_state, cwg, state)
            stored = SqlBeliefEventStore(db).counted_history(PROJECT, HYP)
            assert tuple(e.event_id for e in stored) == projection.applied, bits
            assert counted_events(stored) == stored, bits
            seen_states.add(state)
            seen_reasons.update(python_skipped.values())
            cases += 1
            raise psycopg.Rollback(tx)
    print(f"{cases} exclusion cases; states reached {sorted(map(str, seen_states))}")
    assert cases == 2**toggles == 512
    # The enumeration exercised every branch it claims to.
    assert {r.value for r in SkipReason} <= seen_reasons
    assert {None, "ACTIVE", "CHALLENGED", "SUPPORTED"} <= seen_states


def test_the_gates_independence_bound_is_the_products_count(guarded):
    """`belief_evidence_lines` against `VerificationLoop._independence`, the product's count, for
    every subset of: the attestations of runs stored in the database, and run-less ones."""
    from lab_brain.core.models import RelationJudgment, RelationType
    from lab_brain.core.repositories.evidence import SqlAttestationStore
    from lab_brain.core.repositories.jobs import SqlJobStore
    from lab_brain.verification.loop import VerificationLoop

    db = guarded.db
    project = RESEARCH_PROJECT
    external = external_attestation(db, project)
    runs = [
        str(r[0])
        for r in db.execute(
            "SELECT a.attestation_id FROM attestations a"
            " LEFT JOIN observations o ON o.observation_id = a.observation_id"
            " JOIN runs u ON u.run_id = coalesce(a.run_id, o.run_id)"
            " WHERE a.project_id = %s ORDER BY a.attestation_id",
            (project,),
        ).fetchall()
    ]
    candidates = [*runs, external]
    attestations = SqlAttestationStore(db)

    class _Evidence:
        def attestation(self, project_id: str, attestation_id: str) -> Any:
            return attestations.get(project_id, attestation_id)

        def observation(self, project_id: str, observation_id: str) -> Any:
            from lab_brain.storage.postgres.verification_evidence import SqlEvidenceSink

            return SqlEvidenceSink(connection=db, outputs=None).observation(  # type: ignore[arg-type]
                project_id, observation_id
            )

    loop = types.SimpleNamespace(
        _d=types.SimpleNamespace(evidence=_Evidence(), jobs=SqlJobStore(db))
    )
    loop._supporting_attestations = lambda p, a: VerificationLoop._supporting_attestations(
        loop,  # type: ignore[arg-type]
        p,
        a,
    )
    checked = 0
    values: set[int] = set()
    for size in range(len(candidates) + 1):
        for subset in itertools.combinations(candidates, size):
            relation = (
                RelationJudgment(
                    relation_id="rel:diff",
                    from_entity_id=external,
                    to_entity_id="hyp:any",
                    relation_type=RelationType.SUPPORTS,
                    supporting_attestation_ids=subset,
                    project_id=project,
                )
                if subset
                else None
            )
            python = (
                0
                if relation is None
                else VerificationLoop._independence(loop, project, (relation,)).independent_count  # type: ignore[arg-type]
            )
            ((sql,),) = db.execute(
                "SELECT belief_evidence_lines(%s, %s)", (project, list(subset))
            ).fetchall()
            assert sql == python, (subset, sql, python)
            values.add(python)
            checked += 1
    print(
        f"independence: {checked} subsets of {len(candidates)} attestations ({len(runs)} with runs)"
    )
    assert checked == 2 ** len(candidates)
    assert len(runs) >= 2, "the enumeration needs attestations of stored runs"
    print(f"independence counts reached: {sorted(values)}")
    assert {0, 1, 2} <= values, "the enumeration must reach two distinct evidence lines"
