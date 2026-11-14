"""G0 trust boundaries, round 4: T-2, T-3, R15 and R-4 of the trust-boundaries report.

Every attack is made through the deployment's real least-privilege services' role (created by
`deployment/docker/service_roles.py` and `grant_database_roles`, i.e. `lab-brain admin db-roles`)
and judged by the product's own readers (docs/audit/g0-trust-boundaries-2026-11-08/REPORT.md §7).

T-2  Belief decisions and events are written by the services' role, and the read-time checks
     (R-1) cannot see what a snapshot leaves out or what the writer chose:
       (a) a snapshot that omits a currently unresolved conflict of its subject;
       (b) an independence count no stored evidence line supports;
       (c) writer-supplied times: a transition dated in the future sorts after every honest later
           move, which then no longer applies;
       (d) one forged row makes the projection refuse the subject's whole history, and nothing but
           a superuser could remove it (denial of service).
T-3  A transition policy (before `011x`) or a diagnostic declaration set (before `011y`) written by
     the services' role blocks every research run or every projection of the subjects it touched,
     and the rows are append-only for every role.
R-4  `review_queue_policies` is writable by the services' role: it can declare a project's active
     queue -- the expiry a person's standing decision authorises -- in that person's name.

Engineering evidence only. G0 is NOT PASSED.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import psycopg
import pytest

from lab_brain.core.models import BeliefState, RelationType, TransitionPolicy
from lab_brain.core.models.conflict import Conflict, ConflictType
from lab_brain.core.models.enums import IndependenceBasis
from lab_brain.core.models.transition import IndependenceSummary
from lab_brain.core.repositories import SqlTransitionPolicyStore
from lab_brain.core.repositories.conflicts import SqlConflictStore
from lab_brain.core.repositories.evidence import SqlAttestationStore, SqlRelationStore
from lab_brain.core.repositories.warrants import SqlDeclarationSetStore, WarrantStoreError
from tests.e2e.test_g0_screening_independence_postgres import Guarded
from tests.e2e.test_g0_screening_independence_postgres import guarded as guarded
from tests.e2e.test_g0_screening_independence_postgres import standin as standin
from tests.e2e.test_g0_security_assurance_postgres import AUTHORITY, _accepting, _episode
from tests.e2e.test_g0_trust_boundaries_postgres import (
    REFUSALS,
    SUPPORT_ONLY,
    _admin,
    _code_set,
    _honest,
    _insert_set,
    _owner_registers,
    _product_reader,
    _RawDecisions,
    _read,
    _sets,
    _stored_support,
    _try,
    _unscreened,
    _well_formed,
    legacy_promote,
)
from tests.e2e.test_research_episode_postgres import PROJECT
from tests.integration import test_g0_spend_admin_postgres as _roles

pytestmark = pytest.mark.postgres

su = _roles.su
roles = _roles.roles

#: Owner-registered rules isolating one input each (registered as the owner: `011x`).
CONFLICT_GATED = TransitionPolicy(
    policy_id="policy:g0-r4-promote-unblocked",
    version="1.0.0",
    from_state=BeliefState.ACTIVE,
    candidate_to_state=BeliefState.SUPPORTED,
    required_relation_types=(RelationType.SUPPORTS,),
    blocking_conflict_policy=(ConflictType.SIM_TO_REAL_CONFLICT.value,),
)
INDEPENDENCE_GATED = TransitionPolicy(
    policy_id="policy:g0-r4-promote-independent",
    version="1.0.0",
    from_state=BeliefState.ACTIVE,
    candidate_to_state=BeliefState.SUPPORTED,
    required_relation_types=(RelationType.SUPPORTS,),
    min_independent_attestations=3,
    independence_basis=IndependenceBasis.WORK,
)
CHALLENGE = TransitionPolicy(
    policy_id="policy:g0-r4-challenge",
    version="1.0.0",
    from_state=BeliefState.SUPPORTED,
    candidate_to_state=BeliefState.CHALLENGED,
)

#: A refusal at write time: the database's (privilege, guard or the write function), or the
#: product's own refusal to record a transition it cannot stand behind.
WRITE_REFUSALS: tuple[type[BaseException], ...] = (psycopg.Error, RuntimeError)


def _attempt(
    episode: Any,
    g: Guarded,
    hypothesis: str,
    policy: TransitionPolicy,
    *,
    to: BeliefState = BeliefState.SUPPORTED,
    at: dt.datetime | None = None,
    independence: IndependenceSummary | None = None,
) -> Any:
    return episode.attempt_transition(
        project_id=PROJECT,
        hypothesis_id=hypothesis,
        policy_id=policy.policy_id,
        policy_version=policy.version,
        candidate_to_state=to,
        stakes="HIGH",
        occurred_at=at or dt.datetime.now(dt.UTC),
        trace_id=f"trc:r4-{uuid.uuid4().hex[:8]}",
        episode_id=g.episode,
        actor_id=g.actor,
        authority_policy_ref=(AUTHORITY.policy_id, AUTHORITY.policy_version),
        independence_summary=independence,
        triggering_attestations=(SqlAttestationStore(g.db).get(PROJECT, g.attestation),),
    )


def _services_episode(app: Any, g: Guarded) -> Any:
    """The product's episode wiring over the services' role (the product's own stores)."""
    return _episode(app, SqlRelationStore(app, support_verifier=_accepting), g.keys.trust)


def _write(attempt: Any) -> tuple[Any, BaseException | None]:
    try:
        return attempt(), None
    except WRITE_REFUSALS as exc:
        return None, exc


def _open_conflict(g: Guarded, hypothesis: str) -> Conflict:
    """An open conflict of the hypothesis, recorded through the product's conflict store."""
    conflict = Conflict(
        conflict_id=f"cfl:r4-{uuid.uuid4().hex[:10]}",
        project_id=PROJECT,
        conflict_type=ConflictType.SIM_TO_REAL_CONFLICT,
        subject_refs=(hypothesis,),
        blocking=True,
        detected_at=dt.datetime.now(dt.UTC),
        detected_by_actor_or_slot=g.actor,
        trace_id="trc:r4-conflict",
    )
    return SqlConflictStore(g.db).record(conflict)


class _NoConflicts:
    """A writer whose conflict source reports none (what the snapshot then records)."""

    def unresolved_for_subject(self, project_id: str, subject_ref: str) -> tuple[Conflict, ...]:
        return ()


def _events(g: Guarded, hypothesis: str) -> list[tuple[str, str, dt.datetime]]:
    return [
        (str(r[0]), str(r[1]), r[2])
        for r in g.db.execute(
            "SELECT event_id, to_state, occurred_at FROM belief_revision_events"
            " WHERE project_id = %s AND target_id = %s ORDER BY occurred_at, event_id",
            (PROJECT, hypothesis),
        ).fetchall()
    ]


# =============================================================================================
# T-2: what the services' role writes as a decision and an event
# =============================================================================================


def test_t2_a_snapshot_that_omits_an_open_conflict_is_refused_when_written(guarded, roles):
    """An open SIM_TO_REAL conflict blocks the promotion under CONFLICT_GATED. The services' role
    runs the product's episode with a conflict source that reports none: the snapshot records no
    conflict, re-derives to ALLOW, and nothing at read time can tell what was left out."""
    g = guarded
    hypothesis = _unscreened(g)
    policy = _owner_registers(g, CONFLICT_GATED)
    conflict = _open_conflict(g, hypothesis)
    with roles.connect(roles.app) as app:
        _stored_support(app, g, hypothesis)
        episode = _services_episode(app, g)
        episode._conflicts = _NoConflicts()  # type: ignore[attr-defined]
        written, refused = _write(lambda: _attempt(episode, g, hypothesis, policy))
    read = _read(_honest(g), hypothesis)
    print(f"T-2a omitted {conflict.conflict_id}: write refused={refused!r}")
    print(f"T-2a projection of {hypothesis} -> {read}")
    assert refused is not None, written
    assert read == BeliefState.ACTIVE.value


def test_t2_an_independence_count_no_stored_line_supports_is_refused_when_written(guarded, roles):
    g = guarded
    hypothesis = _unscreened(g)
    policy = _owner_registers(g, INDEPENDENCE_GATED)
    claimed = IndependenceSummary(basis=IndependenceBasis.WORK, independent_count=50)
    with roles.connect(roles.app) as app:
        _stored_support(app, g, hypothesis)
        written, refused = _write(
            lambda: _attempt(_services_episode(app, g), g, hypothesis, policy, independence=claimed)
        )
    read = _read(_honest(g), hypothesis)
    print(f"T-2b independent_count=50 claimed: write refused={refused!r}")
    print(f"T-2b projection of {hypothesis} -> {read}")
    assert refused is not None, written
    assert read == BeliefState.ACTIVE.value


def test_t2_a_future_dated_transition_is_refused_when_written(guarded, roles):
    """Dated a month ahead, a promotion sorts after every honest later move: a challenge recorded
    now no longer applies (its predecessor, SUPPORTED, is reached only after it in the order)."""
    g = guarded
    hypothesis = _unscreened(g)
    promote = _owner_registers(g, SUPPORT_ONLY)
    challenge = _owner_registers(g, CHALLENGE)
    later = dt.datetime.now(dt.UTC) + dt.timedelta(days=30)
    with roles.connect(roles.app) as app:
        _stored_support(app, g, hypothesis)
        written, refused = _write(
            lambda: _attempt(_services_episode(app, g), g, hypothesis, promote, at=later)
        )
        if written is not None:
            # The honest next move, now: a challenge (requires nothing but the SUPPORTED state).
            _attempt(_services_episode(app, g), g, hypothesis, challenge, to=BeliefState.CHALLENGED)
    read = _read(_honest(g), hypothesis)
    (now,) = g.db.execute("SELECT clock_timestamp()").fetchone()
    print(f"T-2c promotion dated {later.isoformat()}: write refused={refused!r}")
    print(f"T-2c stored history {[(e, s, t.isoformat()) for e, s, t in _events(g, hypothesis)]}")
    print(f"T-2c projection of {hypothesis} -> {read}")
    assert refused is not None, written
    assert all(t <= now for _, _, t in _events(g, hypothesis))
    assert read == BeliefState.ACTIVE.value


# -- the gate (`011z`): its other checks, its privileges and a positive control ---------------


def test_t2_the_gate_refuses_a_snapshot_whose_evidence_is_not_stored(guarded, roles):
    """Through the product's own store, the R-1 forgeries are refused when written, not only when
    read: a SUPPORTS that is not stored, an authority class no attestation has, a condition match
    the database records otherwise."""
    from lab_brain.core.models.condition import ConditionMatchState
    from lab_brain.core.models.relation import RelationJudgment
    from lab_brain.core.repositories.conditions import SqlConditionMatchStore
    from lab_brain.domains.silicon_photonics import vertical as sp
    from tests.e2e.test_g0_trust_boundaries_postgres import (
        AUTHORITY_GATED,
        CONDITION_GATED,
        _Classes,
        _inspection,
        _Relations,
    )

    g = guarded
    refusals: dict[str, str] = {}
    with roles.connect(roles.app) as app:
        hypothesis = _unscreened(g)
        observation, attestation = _inspection(g)
        phantom = RelationJudgment(
            relation_id=f"rel:r4-phantom-{uuid.uuid4().hex[:8]}",
            from_entity_id=observation,
            to_entity_id=hypothesis,
            relation_type=RelationType.SUPPORTS,
            supporting_attestation_ids=(attestation,),
            project_id=PROJECT,
        )
        episode = _services_episode(app, g)
        episode._relations = _Relations((phantom,))  # type: ignore[attr-defined]
        _, refused = _write(
            lambda: _attempt(episode, g, hypothesis, _owner_registers(g, SUPPORT_ONLY))
        )
        refusals["phantom relation"] = repr(refused)

        _stored_support(app, g, hypothesis)
        episode = _services_episode(app, g)
        episode._authority_classes = _Classes((sp.MEAS_CALIBRATED,))  # type: ignore[attr-defined]
        _, refused = _write(
            lambda: _attempt(episode, g, hypothesis, _owner_registers(g, AUTHORITY_GATED))
        )
        refusals["authority class"] = repr(refused)

        other = _unscreened_other(g, hypothesis)
        exact_id = str(
            g.db.execute("SELECT condition_match_id FROM condition_matches").fetchone()[0]
        )
        exact = SqlConditionMatchStore(g.db).get(exact_id)
        assert exact is not None
        partial = exact.model_copy(
            update={
                "condition_match_id": f"cmt:r4-{uuid.uuid4().hex[:10]}",
                "state": ConditionMatchState.PARTIAL,
            }
        )
        SqlConditionMatchStore(app).add(partial)
        _stored_support(app, g, other, condition_match=partial.condition_match_id)
        claimed = partial.model_copy(update={"state": ConditionMatchState.EXACT})
        conditioned = _owner_registers(g, CONDITION_GATED)
        _, refused = _write(
            lambda: _services_episode(app, g).attempt_transition(
                project_id=PROJECT,
                hypothesis_id=other,
                policy_id=conditioned.policy_id,
                policy_version=conditioned.version,
                candidate_to_state=BeliefState.SUPPORTED,
                stakes="HIGH",
                occurred_at=dt.datetime.now(dt.UTC),
                trace_id="trc:r4-cm",
                episode_id=g.episode,
                actor_id=g.actor,
                condition_matches=(claimed,),
                triggering_attestations=(SqlAttestationStore(g.db).get(PROJECT, g.attestation),),
            )
        )
        refusals["condition match"] = repr(refused)
    print(f"T-2 gate refusals: {refusals}")
    assert "is not the current relation stored" in refusals["phantom relation"]
    assert "authority classes" in refusals["authority class"]
    assert "is not the match stored" in refusals["condition match"]
    for h in (hypothesis, other):
        assert _read(_honest(g), h) == BeliefState.ACTIVE.value


def _unscreened_other(g: Guarded, hypothesis: str) -> str:
    ((other,),) = g.db.execute(
        "SELECT h.hypothesis_id FROM hypotheses h WHERE h.created_in_episode = %s"
        " AND h.hypothesis_id <> %s AND NOT EXISTS (SELECT 1 FROM screening_conditioned_hypotheses"
        "  s WHERE s.hypothesis_id = h.hypothesis_id) ORDER BY h.hypothesis_id LIMIT 1",
        (g.episode, hypothesis),
    ).fetchall()
    return str(other)


def test_t2_the_gate_refuses_an_event_dated_before_the_subjects_latest(guarded, roles):
    g = guarded
    hypothesis = _unscreened(g)
    policy = _owner_registers(g, SUPPORT_ONLY)
    ((latest,),) = g.db.execute(
        "SELECT max(occurred_at) FROM belief_revision_events WHERE target_id = %s", (hypothesis,)
    ).fetchall()
    with roles.connect(roles.app) as app:
        _stored_support(app, g, hypothesis)
        _, refused = _write(
            lambda: _attempt(
                _services_episode(app, g), g, hypothesis, policy, at=latest - dt.timedelta(days=1)
            )
        )
    print(f"T-2 backdated before {latest}: {refused!r}")
    assert refused is not None and "does not reorder the history" in str(refused), refused
    assert _read(_honest(g), hypothesis) == BeliefState.ACTIVE.value


def test_t2_an_honest_transition_goes_through_the_gate_and_is_recorded_with_the_clock(
    guarded, roles
):
    """Positive control: stored support, the true conflicts (none), the true classes; the
    services' role records decision and event in one call; the gate's record names the services'
    login role and the database clock; the projection reads SUPPORTED."""
    g = guarded
    hypothesis = _unscreened(g)
    policy = _owner_registers(g, SUPPORT_ONLY)
    with roles.connect(roles.app) as app:
        _stored_support(app, g, hypothesis)
        (before,) = g.db.execute("SELECT clock_timestamp()").fetchone()
        written = _attempt(_services_episode(app, g), g, hypothesis, policy)
    assert written.event is not None
    ((by, at, decision),) = g.db.execute(
        "SELECT recorded_by, recorded_at, decision_id FROM belief_write_records"
        " WHERE event_id = %s",
        (written.event.event_id,),
    ).fetchall()
    assert by == roles.app and at >= before
    assert decision == written.authorization.decision_id
    assert _read(_honest(g), hypothesis) == BeliefState.SUPPORTED.value


def _gates(su: Any) -> list[str]:
    return [
        str(r[0])
        for r in su.execute(
            "SELECT oid::regprocedure::text FROM pg_proc"
            " WHERE proname IN ('belief_transition_record', 'belief_admission_record')"
            " ORDER BY 1"
        ).fetchall()
    ]


def test_t2_the_gate_is_the_migrators_and_executable_by_the_services_only(su, roles):
    gates = _gates(su)
    assert len(gates) == 2, gates
    for gate in gates:
        definer, config, public = su.execute(
            "SELECT p.prosecdef, p.proconfig, has_function_privilege('public', p.oid, 'EXECUTE')"
            " FROM pg_proc p WHERE p.oid = %s::regprocedure",
            (gate,),
        ).fetchone()
        assert definer and any(c.startswith("search_path=") for c in config), (gate, config)
        assert not public, gate
        for role, may in ((roles.app, True), (roles.reader, False)):
            (allowed,) = su.execute(
                "SELECT has_function_privilege(%s, %s::regprocedure, 'EXECUTE')", (role, gate)
            ).fetchone()
            assert allowed is may, (gate, role)
    with roles.connect(roles.app) as app:
        for statement in (
            "INSERT INTO belief_write_records (decision_id, recorded_at, recorded_by)"
            " SELECT decision_id, now(), 'x' FROM belief_transition_decisions LIMIT 1",
            "UPDATE belief_write_records SET recorded_by = 'x'",
            "DELETE FROM belief_write_records",
            "TRUNCATE belief_write_records",
            "ALTER TABLE belief_write_records DISABLE TRIGGER ALL",
            "CREATE OR REPLACE FUNCTION belief_snapshot_problem(TEXT, TEXT, JSONB) RETURNS TEXT"
            " AS $$ SELECT NULL::TEXT $$ LANGUAGE sql",
            "DROP FUNCTION belief_transition_record CASCADE",
        ):
            refused = _try(lambda statement=statement: app.execute(statement))
            assert refused is not None, statement


class _RawEvents:
    """The services' role appending the event with the 005d function (no write gate)."""

    def __init__(self, c: Any) -> None:
        self._c = c

    def append(self, authorized: Any) -> Any:
        e = authorized.event
        self._c.execute(
            "SELECT belief_revision_event_append(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,"
            " %s, %s, %s, %s, %s)",
            (
                e.event_id,
                e.project_id,
                e.target_type.value,
                e.target_id,
                None if e.from_state is None else e.from_state.value,
                e.to_state.value,
                list(e.triggering_attestation_ids),
                list(e.triggering_relation_ids),
                e.policy_id,
                e.policy_version,
                e.actor_id,
                e.inference_provenance_id,
                e.rationale_artifact_or_record_ref,
                e.occurred_at,
                e.trace_id,
                e.authorization_decision_id,
            ),
        )
        return e

    def history(self, project_id: str, target_id: str) -> Any:
        from lab_brain.core.repositories import SqlBeliefEventStore

        return SqlBeliefEventStore(self._c).history(project_id, target_id)


@pytest.mark.xfail(
    strict=True,
    reason="T-2: the services' role holds row writes on the tables (Owner-gated REVOKE)",
)
def test_t2_raw_rows_written_by_the_services_role_are_refused(guarded, roles):
    """The same omission written with the services' role's own code (plain INSERT and the 005d
    append, which check nothing a snapshot leaves out). Closed only by revoking the row writes --
    the Owner's decision (REPORT §Owner decisions)."""
    g = guarded
    hypothesis = _unscreened(g)
    policy = _owner_registers(g, CONFLICT_GATED)
    _open_conflict(g, hypothesis)
    with roles.connect(roles.app) as app:
        _stored_support(app, g, hypothesis)
        episode = _services_episode(app, g)
        episode._conflicts = _NoConflicts()  # type: ignore[attr-defined]
        episode._decisions = _RawDecisions(app)  # type: ignore[attr-defined]
        episode._events = _RawEvents(app)  # type: ignore[attr-defined]
        written, refused = _write(lambda: _attempt(episode, g, hypothesis, policy))
    read = _read(_honest(g), hypothesis)
    print(f"T-2 raw rows: write refused={refused!r}; projection -> {read}")
    assert refused is not None and isinstance(refused, psycopg.errors.InsufficientPrivilege), (
        written,
        refused,
    )
    assert read == BeliefState.ACTIVE.value


def _forge_not_rederivable(g: Guarded, hypothesis: str, writer: Any) -> str:
    """A decision recorded honestly as NEED_MORE_EVIDENCE, copied by `writer` as an ALLOW (its
    snapshot unchanged, so the hash still binds it), and an event citing the copy."""
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
    forged = f"dec:r4-forged-{uuid.uuid4().hex[:8]}"
    event = f"bre:r4-forged-{uuid.uuid4().hex[:8]}"
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
        " %s, %s, %s, %s, %s, NULL, NULL, now(), 'trc:r4-forged', %s)",
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


def _forger(g: Guarded, app: Any) -> tuple[Any, str]:
    """The services' role while it still holds row writes on the decision table; the owner (a
    row written before the revocation) once it does not."""
    (holds,) = g.db.execute(
        "SELECT has_table_privilege(%s, 'belief_transition_decisions', 'INSERT')", (app.info.user,)
    ).fetchone()
    return (app, "services' role") if holds else (g.db, "owner (a row from before the revocation)")


def test_t2_one_forged_row_stops_denying_the_history_after_the_owners_quarantine(guarded, roles):
    """One forged decision makes the projection refuse the subject's WHOLE history
    (NOT_REDERIVABLE), and both rows are append-only for every role. The owner's quarantine of
    the event (recorded, never a deletion) must let the rest of the history read again.

    Read with the R8 projection as the security assurance pass wired it (`_honest`): the forged
    row cites an owner-registered rule the code does not declare, which the product's own reader
    refuses first (UNDECLARED_POLICY) -- the same denial, another reason."""
    g = guarded
    hypothesis = _unscreened(g)
    assert _read(_honest(g), hypothesis) == BeliefState.ACTIVE.value
    with roles.connect(roles.app) as app:
        writer, who = _forger(g, app)
        event = _forge_not_rederivable(g, hypothesis, writer)
    before = _read(_honest(g), hypothesis)
    print(f"T-2d forged event {event} written by the {who}: product projection -> {before}")
    assert before == "REFUSED:NOT_REDERIVABLE"
    deleted = _try(
        lambda: g.db.execute("DELETE FROM belief_revision_events WHERE event_id = %s", (event,))
    )
    print(f"T-2d the owner deleting the event: {deleted!r}")
    assert deleted is not None
    status, out = _admin(
        g.db,
        "quarantine",
        "event",
        event,
        "--reason",
        "forged authorization (G0 T-2d)",
        "--actor",
        g.actor,
    )
    print(f"T-2d quarantine: exit {status}: {out.strip()}")
    assert status == 0, out
    after = _read(_honest(g), hypothesis)
    print(f"T-2d product projection after the quarantine -> {after}")
    assert after == BeliefState.ACTIVE.value
    assert event in {e for e, _, _ in _events(g, hypothesis)}  # kept, not deleted
    projection = _honest(g).project(project_id=PROJECT, hypothesis_id=hypothesis)
    assert (event, "OWNER_QUARANTINED") in {(e, r.value) for e, r in projection.skipped}


# =============================================================================================
# T-3: rows written before 011x / 011y
# =============================================================================================


def test_t3_a_declaration_set_from_before_011y_stops_blocking_after_the_owners_quarantine(db):
    """A set the services' role could register before `011y` (inserted here as the owner) makes
    the composition root's check refuse every research run; the table is append-only for every
    role. The owner's quarantine must end the block and take it out of the SQL rule, while the row
    stays exactly as written."""
    code = _code_set()
    SqlDeclarationSetStore(db).ensure((code,), code.ref)
    _insert_set(db, "g0.r4.legacy", _well_formed())
    (written,) = db.execute(
        "SELECT row_to_json(s)::text FROM diagnostic_declaration_sets s WHERE set_id = %s",
        ("g0.r4.legacy",),
    ).fetchone()
    blocked: Exception | None = None
    try:
        SqlDeclarationSetStore(db).ensure((code,), code.ref)
    except WarrantStoreError as exc:
        blocked = exc
    print(f"T-3 set: ensure() with g0.r4.legacy@1 present -> {blocked!r}")
    assert blocked is not None
    deleted = _try(
        lambda: db.execute("DELETE FROM diagnostic_declaration_sets WHERE set_id = 'g0.r4.legacy'")
    )
    print(f"T-3 set: the owner deleting it -> {deleted!r}")
    assert deleted is not None
    actor = str(db.execute("SELECT actor_id FROM actors ORDER BY actor_id LIMIT 1").fetchone()[0])
    status, out = _admin(
        db,
        "quarantine",
        "declaration-set",
        "g0.r4.legacy@1",
        "--reason",
        "registered before 011y; nobody reviewed it as code",
        "--actor",
        actor,
    )
    print(f"T-3 set: quarantine: exit {status}: {out.strip()}")
    assert status == 0, out
    assert SqlDeclarationSetStore(db).ensure((code,), code.ref) == ()
    held = {str(r[0]) for r in db.execute("SELECT DISTINCT set_ref FROM diagnostic_declarations")}
    assert held == {code.ref}, held
    assert ("g0.r4.legacy", "1") in _sets(db)
    (kept,) = db.execute(
        "SELECT row_to_json(s)::text FROM diagnostic_declaration_sets s WHERE set_id = %s",
        ("g0.r4.legacy",),
    ).fetchone()
    assert kept == written


def test_t3_a_policy_from_before_011x_stops_denying_a_history_after_the_owners_quarantine(
    guarded, roles
):
    """The R-3 scenario: a transition under a policy row the code does not declare makes the
    product projection refuse the subject's history (UNDECLARED_POLICY), for good. Quarantined by
    the owner, the policy's events are skipped -- recorded as skipped -- and the rest reads."""
    from tests.e2e.test_g0_trust_boundaries_postgres import _attempt_on, _Unchecked, _writer

    g = guarded
    hypothesis = _unscreened(g)
    policy = _owner_registers(g, legacy_promote())
    with roles.connect(roles.app) as app:
        written = _attempt_on(
            _writer(
                app, g, relations=_Unchecked(SqlRelationStore(app, support_verifier=_accepting))
            ),
            g,
            hypothesis,
            policy,
        )
    assert written.event is not None
    before = _read(_product_reader(g), hypothesis)
    print(f"T-3 policy {policy.policy_id}: product projection -> {before}")
    assert before == "REFUSED:UNDECLARED_POLICY"
    status, out = _admin(
        g.db,
        "quarantine",
        "policy",
        f"{policy.policy_id}@{policy.version}",
        "--reason",
        "registered before 011x; not a policy the code declares",
        "--actor",
        g.actor,
    )
    print(f"T-3 policy: quarantine: exit {status}: {out.strip()}")
    assert status == 0, out
    after = _read(_product_reader(g), hypothesis)
    print(f"T-3 policy: product projection after the quarantine -> {after}")
    assert after == BeliefState.ACTIVE.value
    assert SqlTransitionPolicyStore(g.db).get(policy.policy_id, policy.version) == policy
    status, out = _admin(g.db, "register-policies")
    assert status == 0 and "quarantined" in out, out


# -- the quarantine (`012t`): owner only, append-only, never for the product's own rules -------


def test_t3_the_quarantine_is_the_owners_and_append_only(guarded, roles):
    g = guarded
    hypothesis = _unscreened(g)
    ((event,),) = g.db.execute(
        "SELECT event_id FROM belief_revision_events WHERE target_id = %s", (hypothesis,)
    ).fetchall()
    with roles.connect(roles.app) as app:
        inserted = _try(
            lambda: app.execute(
                "INSERT INTO owner_quarantines (subject_kind, subject_id, reason, actor_id,"
                " quarantined_at, recorded_by) VALUES ('BELIEF_EVENT', %s, 'the services hide it',"
                " %s, now(), 'x')",
                (event, g.actor),
            )
        )
        status, out = _admin(
            app,
            "quarantine",
            "event",
            event,
            "--reason",
            "the services hide it",
            "--actor",
            g.actor,
        )
    print(f"T-3 services' role quarantining {event}: {inserted!r}; command exit {status}: {out}")
    assert isinstance(inserted, REFUSALS), inserted
    assert status == 2 and "schema owner" in out, out
    assert _read(_honest(g), hypothesis) == BeliefState.ACTIVE.value
    status, out = _admin(
        g.db,
        "quarantine",
        "event",
        "bre:r4-no-such-event",
        "--reason",
        "a row that was never recorded",
        "--actor",
        g.actor,
    )
    assert status == 2 and "only a recorded row" in out, out
    status, out = _admin(
        g.db, "quarantine", "event", event, "--reason", "the owner's decision", "--actor", g.actor
    )
    assert status == 0, out
    for statement in (
        "UPDATE owner_quarantines SET reason = 'rewritten afterwards'",
        "DELETE FROM owner_quarantines",
    ):
        refused = _try(lambda statement=statement: g.db.execute(statement))
        assert refused is not None, statement
    assert _read(_honest(g), hypothesis) is not None


def test_t3_the_products_own_rules_are_not_quarantined(db):
    from lab_brain.research.service import ADMISSION_POLICY

    actor = str(db.execute("SELECT actor_id FROM actors ORDER BY 1 LIMIT 1").fetchone()[0])
    code = _code_set()
    SqlDeclarationSetStore(db).ensure((code,), code.ref)
    if (
        SqlTransitionPolicyStore(db).get(ADMISSION_POLICY.policy_id, ADMISSION_POLICY.version)
        is None
    ):
        SqlTransitionPolicyStore(db).register(ADMISSION_POLICY)
    for kind, ref in (
        ("policy", f"{ADMISSION_POLICY.policy_id}@{ADMISSION_POLICY.version}"),
        ("declaration-set", code.ref),
    ):
        status, out = _admin(
            db, "quarantine", kind, ref, "--reason", "switching governance off", "--actor", actor
        )
        assert status == 2 and "installed code declares" in out, (kind, out)
    assert db.execute("SELECT count(*) FROM owner_quarantines").fetchone()[0] == 0


# =============================================================================================
# R-4: review_queue_policies
# =============================================================================================


@pytest.mark.xfail(strict=True, reason="R-4 reproduction: the services' role declares queues")
def test_r4_the_services_role_cannot_declare_a_review_queue_in_a_persons_name(db, roles):
    """The active queue policy prices every review's expiry, and `review_expire` records that
    expiry as the declaring person's standing decision (`v3.3-a15`). As the services' role:
    deactivate the project's queue and declare one that expires every review after a minute, in
    a member's name."""
    project = str(db.execute("SELECT project_id FROM projects ORDER BY 1 LIMIT 1").fetchone()[0])
    person = str(db.execute("SELECT actor_id FROM actors ORDER BY 1 LIMIT 1").fetchone()[0])

    def active() -> list[tuple[Any, ...]]:
        return [
            tuple(r)
            for r in db.execute(
                "SELECT policy_id, version, default_expiry_minutes, declared_by_actor_id"
                " FROM review_queue_policies WHERE project_id = %s AND active",
                (project,),
            ).fetchall()
        ]

    before = active()
    with roles.connect(roles.app) as app:

        def declare() -> None:
            with app.transaction():
                app.execute(
                    "UPDATE review_queue_policies SET active = FALSE"
                    " WHERE project_id = %s AND active",
                    (project,),
                )
                app.execute(
                    "INSERT INTO review_queue_policies (policy_id, version, project_id, capacity,"
                    " default_sla_minutes, default_expiry_minutes, reviewer_minutes_per_day,"
                    " declared_by_actor_id, effective_from, active)"
                    " VALUES ('rqp:g0-r4', '1', %s, 0, 1, 1, 0, %s, now(), TRUE)",
                    (project, person),
                )

        refused = _try(declare)
    after = active()
    print(f"R-4: services' role declares a queue for {project} as {person}: refused={refused!r}")
    print(f"R-4: active queue before={before} after={after}")
    assert refused is not None and isinstance(refused, REFUSALS), refused
    assert after == before


__all__ = ["CHALLENGE", "CONFLICT_GATED", "INDEPENDENCE_GATED"]
