"""G0 trust boundaries around belief transitions: R-2, R-3 and R-1 of the F2 closure report.

Every attack below is made through the deployment's real least-privilege services' role (created
by `deployment/docker/service_roles.py` and `grant_database_roles`, i.e. `lab-brain admin
db-roles`) and judged by the product's own readers:

R-2  `diagnostic_declaration_sets` is read by the database's confirmation rule (`012p`:
     `diagnostic_declarations.active`, `cwg_bound_class`, `cwg_relation_warrant`). A set the
     services' role registers (a) warrants a link nobody accountable warranted (DOMAIN), (b) adds
     another "declared signature" that blocks a confirmation the rule accepted, and (c) stops every
     later research run (`SqlDeclarationSetStore.ensure` refuses an undeclared set), permanently,
     because the table is append-only for every role.
R-3  a decision and event under a transition policy the installed code does not declare (a row
     registered before `011x`, or by any path past its trigger) were honoured by the projection.
R-1  a decision snapshot is the writer's record of what it read. For a hypothesis with no
     screening record nothing compared the relations, condition matches and authority classes it
     counted with the stored rows, so a services'-role writer could count a SUPPORTS that is not in
     the database, a condition match the database records as PARTIAL, or an authority class no
     stored attestation has.

Engineering evidence only. G0 is NOT PASSED.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import uuid
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest

from lab_brain.core.belief import UnverifiedBeliefRevision
from lab_brain.core.episode import BeliefEpisode
from lab_brain.core.models import BeliefState, RelationType, TransitionPolicy
from lab_brain.core.models.condition import ConditionMatchState
from lab_brain.core.models.relation import RelationJudgment
from lab_brain.core.models.transition import RelationEvidence, WarrantBasis
from lab_brain.core.repositories import SqlBeliefEventStore, SqlTransitionPolicyStore
from lab_brain.core.repositories.conditions import SqlConditionMatchStore
from lab_brain.core.repositories.evidence import SqlAttestationStore, SqlRelationStore
from lab_brain.core.repositories.warrants import SqlDeclarationSetStore, WarrantStoreError
from lab_brain.domains.silicon_photonics import vertical as sp
from lab_brain.domains.silicon_photonics.product import diagnostic_declaration_set
from lab_brain.research.confirmation import confirmation_verifier
from tests.debate_fixtures import PROJECT as CASE_PROJECT
from tests.e2e.test_causal_warrant_counterexample_postgres import CASE, NOVEL_MECHANISM, _renamed
from tests.e2e.test_g0_exploratory_screening_postgres import rows
from tests.e2e.test_g0_screening_independence_postgres import Guarded
from tests.e2e.test_g0_screening_independence_postgres import guarded as guarded
from tests.e2e.test_g0_screening_independence_postgres import standin as standin
from tests.e2e.test_g0_security_assurance_postgres import (
    AUTHORITY,
    _accepting,
    _episode,
    _product_relations,
)
from tests.e2e.test_research_episode_postgres import PROJECT
from tests.integration import test_g0_spend_admin_postgres as _roles
from tests.vertical_fixtures import case_by_id, load_fixture, run_case

pytestmark = pytest.mark.postgres

su = _roles.su
roles = _roles.roles

#: Reproductions committed before their fixes: strict, so a fix that lands without removing the
#: marker fails the suite (XPASS(strict)).
OPEN_R3 = pytest.mark.xfail(
    strict=True, reason="R-3 open: the projection honours undeclared policies"
)
OPEN_R1 = pytest.mark.xfail(
    strict=True, reason="R-1 open: snapshot evidence is not compared with the database"
)

#: The database's refusals that count: no privilege, or an owner-only guard.
REFUSALS = (psycopg.errors.InsufficientPrivilege, psycopg.errors.RaiseException)


def _try(write: Any) -> Exception | None:
    try:
        write()
    except psycopg.Error as exc:
        return exc
    return None


# =============================================================================================
# R-2: diagnostic declaration sets
# =============================================================================================


def _code_set() -> Any:
    return diagnostic_declaration_set()


def _insert_set(c: Any, set_id: str, declarations: list[dict[str, Any]]) -> None:
    c.execute(
        "INSERT INTO diagnostic_declaration_sets (set_id, version, domain, digest, declarations)"
        " VALUES (%s, '1', %s, %s, %s::jsonb)",
        (set_id, sp.DOMAIN, "sha256:" + uuid.uuid4().hex * 2, json.dumps(declarations)),
    )


def _breaches(db: Any, episode: str, cause: str) -> list[str]:
    return list(
        db.execute(
            "SELECT confirmation_rule_breaches(%s, %s, %s)", (CASE_PROJECT, episode, cause)
        ).fetchone()[0]
    )


def _sets(db: Any) -> list[tuple[str, str]]:
    return [
        (str(r[0]), str(r[1]))
        for r in db.execute(
            "SELECT set_id, version FROM diagnostic_declaration_sets ORDER BY 1, 2"
        ).fetchall()
    ]


def test_r2_the_services_role_cannot_register_a_set_that_blocks_a_confirmation(db, roles):
    """The catalog case confirms its cause on a DOMAIN warrant (the rule holds: no breach). As the
    services' role, register a set declaring the cause's own observed outcome as the signature of
    another mechanism: the SQL rule would then refuse that confirmation, and every later research
    run would be refused by the composition root's closed-set check."""
    fx = load_fixture()
    run = run_case(db, fx, case_by_id(fx, CASE))
    assert run.request is not None
    cause = run.result.confirmed_root_cause
    assert cause is not None
    episode = run.request.episode_id
    assert _breaches(db, episode, cause) == []
    ((observable, space, version, outcome),) = rows(
        db,
        "SELECT (l).observable, (l).space_id, (l).space_version, (l).outcome FROM ("
        " SELECT cwg_observed_link(r) AS l FROM relation_judgments r"
        " WHERE r.project_id = %s AND r.to_entity_id = %s AND r.relation_type = 'SUPPORTS'"
        " AND r.valid_to IS NULL) x WHERE (l).outcome IS NOT NULL LIMIT 1",
        CASE_PROJECT,
        cause,
    )
    rogue = [
        {
            "class_id": "g0_rogue_blocker",
            "mechanism": "g0 rogue blocking mechanism",
            "statement": "written by the services' role",
            "observable_ref": observable,
            "outcome_space_id": space,
            "outcome_space_version": version,
            "supports_outcome": outcome,
            "refutes_outcomes": ["G0_ROGUE_NEVER_OBSERVED"],
        }
    ]
    before = _sets(db)
    with roles.connect(roles.app) as app:
        refused = _try(lambda: _insert_set(app, "g0.rogue.blocker", rogue))
    after = _breaches(db, episode, cause)
    ensured: Exception | None = None
    try:
        SqlDeclarationSetStore(db).ensure((_code_set(),), _code_set().ref)
    except WarrantStoreError as exc:
        ensured = exc
    print(f"R-2 blocker: services role insert refused={refused!r}")
    print(f"R-2 blocker: SQL confirmation breaches for {cause} after: {after}")
    print(f"R-2 blocker: composition root's ensure() afterwards: {ensured!r}")
    assert refused is not None and isinstance(refused, REFUSALS), refused
    assert _sets(db) == before
    assert after == []
    assert ensured is None


def test_r2_the_services_role_cannot_register_a_set_that_warrants_a_link(db, roles):
    """An uncatalogued account (the normalization rival renamed) is supported on its own check,
    but nobody accountable warranted the link: the SQL rule sees no warrant. As the services' role,
    register a set that declares that account a class with the observed signature: the SQL rule
    would read the link as DOMAIN-warranted."""
    fx = _renamed(
        NOVEL_MECHANISM,
        "The extraction divides by a length that includes the tapers, so Rs per length is high.",
    )
    run_case(db, fx, case_by_id(fx, CASE))
    ((novel,),) = rows(
        db,
        "SELECT hypothesis_id FROM hypotheses WHERE project_id = %s AND mechanism = %s",
        CASE_PROJECT,
        NOVEL_MECHANISM,
    )

    def warrants() -> list[tuple[str, str | None]]:
        return [
            (str(r[0]), None if r[1] is None else str(r[1]))
            for r in db.execute(
                "SELECT relation_id, warrant FROM cwg_evidence(%s, %s)"
                " WHERE relation_type = 'SUPPORTS' ORDER BY 1",
                (CASE_PROJECT, novel),
            ).fetchall()
        ]

    before = warrants()
    assert before and all(w is None for _, w in before), before
    declared = next(
        d
        for d in _code_set().model_dump(mode="json")["declarations"]
        if d["class_id"] == "normalization_error"
    )
    rogue = [{**declared, "class_id": "g0_rogue_taper", "mechanism": NOVEL_MECHANISM}]
    with roles.connect(roles.app) as app:
        refused = _try(lambda: _insert_set(app, "g0.rogue.warrant", rogue))
    after = warrants()
    print(f"R-2 warrant: services role insert refused={refused!r}")
    print(f"R-2 warrant: SQL warrant of {novel}'s support before={before} after={after}")
    assert refused is not None and isinstance(refused, REFUSALS), refused
    assert after == before


def _privileges(su: Any, role: str, table: str) -> dict[str, bool]:
    return {
        p: bool(
            su.execute("SELECT has_table_privilege(%s, %s, %s)", (role, table, p)).fetchone()[0]
        )
        for p in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
    }


def _declarations_closed(su: Any, role: str) -> None:
    assert _privileges(su, role, "diagnostic_declaration_sets") == {
        "SELECT": True,
        "INSERT": False,
        "UPDATE": False,
        "DELETE": False,
        "TRUNCATE": False,
        "REFERENCES": False,
        "TRIGGER": False,
    }
    ((enabled,),) = su.execute(
        "SELECT tgenabled FROM pg_trigger WHERE tgrelid = 'diagnostic_declaration_sets'::regclass"
        " AND tgname = 'diagnostic_declaration_sets_a_registered_by_the_owner'"
    ).fetchall()
    assert enabled == "O", "the owner-only guard must exist and be enabled"


def _well_formed() -> list[dict[str, Any]]:
    """A well-formed set body: the code's own declarations (registered here under another id)."""
    return list(_code_set().model_dump(mode="json")["declarations"])


def test_r2_the_guard_refuses_the_services_role_where_insert_was_granted_by_mistake(su, roles):
    """Layer two: with INSERT granted by hand, `011y` still refuses (by name); the next
    `db-roles` run revokes the grant again."""
    from lab_brain.interfaces.deployment import grant_database_roles

    _declarations_closed(su, roles.app)
    su.execute(f'GRANT INSERT ON diagnostic_declaration_sets TO "{roles.app}"')
    with roles.connect(roles.app) as app:
        refused = _try(lambda: _insert_set(app, "g0.mistaken.grant", _well_formed()))
    assert isinstance(refused, psycopg.errors.InsufficientPrivilege), refused
    assert "011y" in str(refused), refused
    assert ("g0.mistaken.grant", "1") not in _sets(su)
    grant_database_roles(su, app_role=roles.app, reader_role=roles.reader)
    _declarations_closed(su, roles.app)


def test_r2_the_services_role_cannot_change_erase_or_switch_off_the_guard(su, roles):
    with roles.connect(roles.app) as app:
        for statement in (
            "UPDATE diagnostic_declaration_sets SET digest = digest",
            "DELETE FROM diagnostic_declaration_sets",
            "TRUNCATE diagnostic_declaration_sets",
            "ALTER TABLE diagnostic_declaration_sets DISABLE TRIGGER"
            " diagnostic_declaration_sets_a_registered_by_the_owner",
            "ALTER TABLE diagnostic_declaration_sets DISABLE TRIGGER ALL",
            "DROP TRIGGER diagnostic_declaration_sets_a_registered_by_the_owner"
            " ON diagnostic_declaration_sets",
            "CREATE OR REPLACE FUNCTION diagnostic_declaration_sets_are_registered_by_the_owner()"
            " RETURNS TRIGGER AS $$ BEGIN RETURN NEW; END $$ LANGUAGE plpgsql",
            "DROP FUNCTION diagnostic_declaration_sets_are_registered_by_the_owner() CASCADE",
            "SET session_replication_role = replica",
            f'GRANT INSERT ON diagnostic_declaration_sets TO "{roles.app}"',
        ):
            refused = _try(lambda statement=statement: app.execute(statement))
            granted = _privileges(su, roles.app, "diagnostic_declaration_sets")["INSERT"]
            assert refused is not None or not granted, statement
    _declarations_closed(su, roles.app)


def test_r2_repeated_grants_and_migrations_do_not_reopen_it(su, roles):
    import subprocess
    import sys
    from pathlib import Path

    from lab_brain.interfaces.deployment import grant_database_roles

    root = Path(__file__).resolve().parents[2]
    grant_database_roles(su, app_role=roles.app, reader_role=roles.reader)
    grant_database_roles(su, app_role=roles.app, reader_role=roles.reader)
    subprocess.run([sys.executable, str(root / "scripts" / "migrate.py")], check=True)
    grant_database_roles(su, app_role=roles.app, reader_role=roles.reader)
    _declarations_closed(su, roles.app)
    reader = _privileges(su, roles.reader, "diagnostic_declaration_sets")
    assert reader["SELECT"] and not reader["INSERT"]


def test_r2_the_product_registers_its_sets_as_the_owner_and_reads_them_as_the_services(db, roles):
    """Positive control and history: on a database with no set, the services' role is refused
    before anything is written, naming the operator's command; the operator's command registers
    the code's set as the owner (idempotently); the services' and auditors' roles then read it and
    the composition root's check passes under the services' role without writing."""
    from lab_brain.core.repositories.warrants import DeclarationRegistrationRefused

    code = _code_set()
    db.execute("TRUNCATE diagnostic_declaration_sets")  # a fresh database, as the migrator
    with roles.connect(roles.app) as app:
        with pytest.raises(DeclarationRegistrationRefused, match="register-policies"):
            SqlDeclarationSetStore(app).ensure((code,), code.ref)
        assert _sets(db) == []
        status, out = _admin(app, "register-policies")
        assert status == 2 and "only the schema owner" in out, out
        assert _sets(db) == []
    status, out = _admin(db, "register-policies")
    assert status == 0, out
    assert f"registered  declaration set {code.ref}" in out, out
    status, out = _admin(db, "register-policies")
    assert status == 0 and f"present     declaration set {code.ref}" in out, out
    with roles.connect(roles.app) as app:
        assert SqlDeclarationSetStore(app).ensure((code,), code.ref) == ()
        held = app.execute("SELECT DISTINCT set_ref FROM diagnostic_declarations WHERE active")
        assert held.fetchall() == [(code.ref,)]
    reader = _privileges(db, roles.reader, "diagnostic_declaration_sets")
    assert reader["SELECT"] and not reader["INSERT"]


class _Kept:
    """A fixture's connection, which `main` must not close."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def close(self) -> None:
        pass

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _admin(connection: Any, *argv: str) -> tuple[int, str]:
    import io
    import os

    from lab_brain.interfaces.cli import main
    from tests.postgres_fixtures import database_url

    out = io.StringIO()
    env = {k: v for k, v in os.environ.items() if k.startswith("LAB_BRAIN_")}
    code = main(
        ["admin", *argv],
        out=out,
        env={**env, "LAB_BRAIN_DATABASE_URL": database_url()},
        connect=lambda _settings: _Kept(connection),
    )
    return code, out.getvalue()


# =============================================================================================
# Shared: an unscreened hypothesis, and a writer whose sources say what it wants
# =============================================================================================


def _unscreened(g: Guarded) -> str:
    """A hypothesis of the guarded episode that has NO screening conditioning record."""
    ((hypothesis,),) = rows(
        g.db,
        "SELECT h.hypothesis_id FROM hypotheses h WHERE h.created_in_episode = %s"
        " AND NOT EXISTS (SELECT 1 FROM screening_conditioned_hypotheses s"
        "  WHERE s.hypothesis_id = h.hypothesis_id)"
        " ORDER BY h.hypothesis_id LIMIT 1",
        g.episode,
    )
    return str(hypothesis)


def _owner_registers(g: Guarded, policy: TransitionPolicy) -> TransitionPolicy:
    """As the schema owner (a pre-`011x` row, or one any owner path registered)."""
    store = SqlTransitionPolicyStore(g.db)
    if store.get(policy.policy_id, policy.version) is None:
        store.register(policy)
    return policy


class _Relations:
    """A relation source that hands the episode exactly `relations` (what a writer chooses)."""

    def __init__(self, relations: tuple[RelationJudgment, ...]) -> None:
        self._relations = relations

    def admitted_for_subject(self, project_id: str, subject_id: str) -> Any:
        return self._relations


class _Classes:
    def __init__(self, classes: tuple[str, ...]) -> None:
        self._classes = classes

    def authority_classes_for(self, project_id: str, attestation_ids: Any) -> tuple[str, ...]:
        return self._classes


class _EventsCitingNoRelation:
    """The services' role writing the event itself: it cites the attestation, not the relation
    (a relation that is not stored cannot be referenced by the event's join table)."""

    def __init__(self, inner: SqlBeliefEventStore) -> None:
        self._inner = inner

    def append(self, authorized: Any) -> Any:
        event = authorized.event.model_copy(update={"triggering_relation_ids": ()})
        return self._inner.append(dataclasses.replace(authorized, event=event))

    def history(self, project_id: str, target_id: str) -> Any:
        return self._inner.history(project_id, target_id)


def _writer(
    app: Any,
    g: Guarded,
    *,
    relations: Any,
    classes: tuple[str, ...] | None = None,
    warrants: Any = None,
) -> Any:
    """`ResearchEpisodeService`'s episode wiring, over the services' role, with the writer's own
    sources: the product's code, run by whoever holds the services' credentials."""
    episode = _episode(app, relations, g.keys.trust)
    episode._events = _EventsCitingNoRelation(SqlBeliefEventStore(app))  # type: ignore[attr-defined]
    if classes is not None:
        episode._authority_classes = _Classes(classes)  # type: ignore[attr-defined]
    if warrants is not None:
        episode._warrants = warrants  # type: ignore[attr-defined]
    return episode


def _attempt_on(
    episode: Any,
    g: Guarded,
    hypothesis: str,
    policy: TransitionPolicy,
    *,
    condition_matches: tuple[Any, ...] = (),
    trigger: str | None = None,
) -> Any:
    return episode.attempt_transition(
        project_id=PROJECT,
        hypothesis_id=hypothesis,
        policy_id=policy.policy_id,
        policy_version=policy.version,
        candidate_to_state=BeliefState.SUPPORTED,
        stakes="HIGH",
        occurred_at=dt.datetime.now(dt.UTC),
        trace_id=f"trc:tb-{uuid.uuid4().hex[:8]}",
        episode_id=g.episode,
        actor_id=g.actor,
        authority_policy_ref=(AUTHORITY.policy_id, AUTHORITY.policy_version),
        condition_matches=condition_matches,
        # Admissible evidence for the event (SRC-002): the project's screening measurement.
        triggering_attestations=(SqlAttestationStore(g.db).get(PROJECT, trigger or g.attestation),),
    )


def _read(reader: Any, hypothesis: str) -> str:
    """What `reader` makes of the hypothesis: its state, or the typed reason it refused."""
    try:
        state = reader.project(project_id=PROJECT, hypothesis_id=hypothesis).current_state
    except UnverifiedBeliefRevision as refused:
        return f"REFUSED:{refused.reason.value}"
    return "NONE" if state is None else state.value


def _product_reader(g: Guarded) -> Any:
    """The belief projection the product's confirmation re-check decides from (R4), taken out of
    the verifier the product builds -- the product's own wiring, not rebuilt here."""
    reading = sp_product()
    verify = confirmation_verifier(
        g.db,
        trust=g.keys.trust,
        declaration_sets=reading.declaration_sets,
        active=reading.active_declarations,
        authority_policies=reading.authority_policies,
    )
    readers = [
        cell.cell_contents
        for cell in verify.__closure__ or ()
        if isinstance(cell.cell_contents, BeliefEpisode)
    ]
    assert len(readers) == 1, readers
    return readers[0]


def sp_product() -> Any:
    from lab_brain.domains.silicon_photonics.product import product_vertical

    return product_vertical(
        outputs=None, jobs=None, broker=None, now=lambda: dt.datetime.now(dt.UTC)
    )


# =============================================================================================
# R-3: decisions under a policy the installed code does not declare
# =============================================================================================


def legacy_promote() -> TransitionPolicy:
    """A promotion that requires nothing -- what the services' role could register before 011x."""
    return TransitionPolicy(
        policy_id=f"policy:g0-tb-legacy-{uuid.uuid4().hex[:10]}",
        version="1.0.0",
        from_state=BeliefState.ACTIVE,
        candidate_to_state=BeliefState.SUPPORTED,
    )


@OPEN_R3
def test_r3_the_projection_refuses_a_transition_under_an_undeclared_policy(guarded, roles):
    """The policy row predates `011x` (registered here by the owner, as the services' role could
    then); the services' role runs the product's episode under it; the product's projection must
    not read SUPPORTED, and must say why: UNDECLARED_POLICY."""
    g = guarded
    hypothesis = _unscreened(g)
    policy = _owner_registers(g, legacy_promote())
    with roles.connect(roles.app) as app:
        written = _attempt_on(
            _writer(app, g, relations=SqlRelationStore(app, support_verifier=_accepting)),
            g,
            hypothesis,
            policy,
        )
    print(f"R-3: services-role transition under {policy.policy_id}: event={written.event}")
    assert written.event is not None
    read = _read(_product_reader(g), hypothesis)
    print(f"R-3: product projection of {hypothesis} -> {read}")
    assert read == "REFUSED:UNDECLARED_POLICY", read


# =============================================================================================
# R-1: what a decision counted must be what the database holds
# =============================================================================================

#: Owner-registered promotions that do not require a diagnostic warrant, each isolating one
#: evidential item. (Under the product's 2.0.0 policies a SUPPORTS also needs a warrant, whose
#: record the warrant verifier re-checks against the stored relation; the condition match the
#: 2.0.0 policies read was not re-checked by anything.)
SUPPORT_ONLY = TransitionPolicy(
    policy_id="policy:g0-tb-promote-support",
    version="1.0.0",
    from_state=BeliefState.ACTIVE,
    candidate_to_state=BeliefState.SUPPORTED,
    required_relation_types=(RelationType.SUPPORTS,),
)
AUTHORITY_GATED = TransitionPolicy(
    policy_id="policy:g0-tb-promote-measured",
    version="1.0.0",
    from_state=BeliefState.ACTIVE,
    candidate_to_state=BeliefState.SUPPORTED,
    required_relation_types=(RelationType.SUPPORTS,),
    required_authority_rule=sp.MEAS_CALIBRATED,
)
CONDITION_GATED = TransitionPolicy(
    policy_id="policy:g0-tb-promote-conditions",
    version="1.0.0",
    from_state=BeliefState.ACTIVE,
    candidate_to_state=BeliefState.SUPPORTED,
    required_relation_types=(RelationType.SUPPORTS,),
    required_condition_match=(
        ConditionMatchState.EXACT,
        ConditionMatchState.COMPATIBLE,
    ),
)


def _inspection(g: Guarded) -> tuple[str, str]:
    """A stored design-inspection reading of the episode: (observation, attestation)."""
    ((observation, attestation),) = rows(
        g.db,
        "SELECT a.observation_id, a.attestation_id FROM attestations a"
        " JOIN observations o ON o.observation_id = a.observation_id"
        " JOIN runs r ON r.run_id = o.run_id JOIN jobs j ON j.job_id = r.job_id"
        " WHERE j.episode_id = %s AND a.authority_class = 'DESIGN_INSPECTION'"
        " ORDER BY a.attestation_id LIMIT 1",
        g.episode,
    )
    return str(observation), str(attestation)


def _stored_support(
    app: Any, g: Guarded, hypothesis: str, *, condition_match: str | None = None
) -> RelationJudgment:
    """As the services' role: a SUPPORTS of the unscreened hypothesis from a stored reading."""
    observation, attestation = _inspection(g)
    relation = RelationJudgment(
        relation_id=f"rel:tb-{uuid.uuid4().hex[:10]}",
        from_entity_id=observation,
        to_entity_id=hypothesis,
        relation_type=RelationType.SUPPORTS,
        supporting_attestation_ids=(attestation,),
        condition_match_ref=condition_match,
        project_id=PROJECT,
    )
    SqlRelationStore(app).add(relation)
    stored = SqlRelationStore(app).get(PROJECT, relation.relation_id)
    assert stored is not None
    return stored


def _honest(g: Guarded) -> Any:
    """The R8 projection as the security assurance pass wired it (the product's relation store
    and verifier), without a declared-policy list -- so these tests ask the evidence question on
    its own, and the product's reader (which also refuses the undeclared policy) separately."""
    return _episode(g.db, _product_relations(g), g.keys.trust)


@OPEN_R1
def test_r1_a_snapshot_support_that_is_not_stored_is_refused(guarded, roles):
    g = guarded
    hypothesis = _unscreened(g)
    observation, attestation = _inspection(g)
    phantom = RelationJudgment(
        relation_id=f"rel:tb-phantom-{uuid.uuid4().hex[:8]}",
        from_entity_id=observation,
        to_entity_id=hypothesis,
        relation_type=RelationType.SUPPORTS,
        supporting_attestation_ids=(attestation,),
        project_id=PROJECT,
    )
    policy = _owner_registers(g, SUPPORT_ONLY)
    with roles.connect(roles.app) as app:
        written = _attempt_on(
            _writer(app, g, relations=_Relations((phantom,)), warrants=_NoWarrants()),
            g,
            hypothesis,
            policy,
        )
    assert written.event is not None
    assert SqlRelationStore(g.db).get(PROJECT, phantom.relation_id) is None
    read = _read(_honest(g), hypothesis)
    print(f"R-1 phantom SUPPORTS {phantom.relation_id}: projection -> {read}")
    assert read == "REFUSED:EVIDENCE_UNVERIFIED", read
    assert _read(_product_reader(g), hypothesis).startswith("REFUSED:")


@OPEN_R1
def test_r1_a_snapshot_authority_class_no_attestation_has_is_refused(guarded, roles):
    g = guarded
    hypothesis = _unscreened(g)
    policy = _owner_registers(g, AUTHORITY_GATED)
    with roles.connect(roles.app) as app:
        support = _stored_support(app, g, hypothesis)
        written = _attempt_on(
            _writer(
                app,
                g,
                relations=SqlRelationStore(app, support_verifier=_accepting),
                classes=(sp.MEAS_CALIBRATED,),
            ),
            g,
            hypothesis,
            policy,
        )
    assert written.event is not None
    stored = SqlAttestationStore(g.db).authority_classes_for(
        PROJECT, list(support.supporting_attestation_ids)
    )
    read = _read(_honest(g), hypothesis)
    print(f"R-1 authority: stored classes {stored}, snapshot ('MEAS_CALIBRATED',) -> {read}")
    assert sp.MEAS_CALIBRATED not in stored
    assert read == "REFUSED:EVIDENCE_UNVERIFIED", read


@OPEN_R1
def test_r1_a_snapshot_condition_match_that_is_not_the_stored_one_is_refused(guarded, roles):
    g = guarded
    hypothesis = _unscreened(g)
    policy = _owner_registers(g, CONDITION_GATED)
    ((exact_id,),) = rows(g.db, "SELECT condition_match_id FROM condition_matches LIMIT 1")
    exact = SqlConditionMatchStore(g.db).get(str(exact_id))
    assert exact is not None and exact.state is ConditionMatchState.EXACT
    with roles.connect(roles.app) as app:
        partial = exact.model_copy(
            update={
                "condition_match_id": f"cmt:tb-{uuid.uuid4().hex[:10]}",
                "state": ConditionMatchState.PARTIAL,
            }
        )
        SqlConditionMatchStore(app).add(partial)
        _stored_support(app, g, hypothesis, condition_match=partial.condition_match_id)
        claimed = partial.model_copy(update={"state": ConditionMatchState.EXACT})
        written = _attempt_on(
            _writer(app, g, relations=SqlRelationStore(app, support_verifier=_accepting)),
            g,
            hypothesis,
            policy,
            condition_matches=(claimed,),
        )
    assert written.event is not None
    read = _read(_honest(g), hypothesis)
    print(f"R-1 condition match: stored PARTIAL, snapshot EXACT -> {read}")
    assert read == "REFUSED:EVIDENCE_UNVERIFIED", read


# -- controls and probes that were already closed ---------------------------------------------


class _NoWarrants:
    """A writer that resolves no warrant: its snapshot records no per-relation facts to re-check."""

    def resolve(self, project_id: str, hypothesis_id: str, relations: Any) -> Any:
        return SimpleNamespace(records=())

    def verify(self, *args: Any) -> None:
        return None


class _ForgedWarrants:
    """A writer's warrant source: every gated relation it is shown is "warranted by review"."""

    def __init__(self, line: str) -> None:
        self._line = line

    def resolve(self, project_id: str, hypothesis_id: str, relations: Any) -> Any:
        return SimpleNamespace(
            records=tuple(
                RelationEvidence(
                    relation_id=r.relation_id,
                    relation_type=r.relation_type,
                    prediction_id=r.attributes.get("prediction_id"),
                    authority_classes=(sp.MEAS_CALIBRATED,),
                    evidence_line=self._line,
                    warrant=WarrantBasis.REVIEW,
                    warrant_ref="dwg:tb-forged",
                )
                for r in relations
                if r.relation_type in (RelationType.SUPPORTS, RelationType.CONTRADICTS)
            )
        )

    def verify(self, *args: Any) -> None:
        return None


def test_r1_under_the_products_warranted_policy_a_phantom_support_was_already_refused(
    guarded, roles
):
    """Probe, not a regression: under the declared 2.0.0 promote policy the counted SUPPORTS needs
    a warrant record, and the warrant verifier re-checks that record's relation against the stored
    one. A phantom support with a forged warrant record was refused before this change
    (WARRANT_UNVERIFIED) and still is."""
    g = guarded
    hypothesis = _unscreened(g)
    observation, attestation = _inspection(g)
    ((exact_id,),) = rows(g.db, "SELECT condition_match_id FROM condition_matches LIMIT 1")
    exact = SqlConditionMatchStore(g.db).get(str(exact_id))
    phantom = RelationJudgment(
        relation_id=f"rel:tb-phantom-{uuid.uuid4().hex[:8]}",
        from_entity_id=observation,
        to_entity_id=hypothesis,
        relation_type=RelationType.SUPPORTS,
        supporting_attestation_ids=(attestation,),
        condition_match_ref=str(exact_id),
        project_id=PROJECT,
    )
    policy = SqlTransitionPolicyStore(g.db).get(
        sp.PROMOTE_MEASURED_POLICY_ID, sp.WARRANTED_VERTICAL_POLICY_VERSION
    )
    assert policy is not None
    with roles.connect(roles.app) as app:
        written = _attempt_on(
            _writer(
                app,
                g,
                relations=_Relations((phantom,)),
                warrants=_ForgedWarrants("line:tb-forged"),
            ),
            g,
            hypothesis,
            policy,
            condition_matches=(exact,),
            trigger=attestation,
        )
    assert written.event is not None
    read = _read(_honest(g), hypothesis)
    print(f"R-1 2.0.0 phantom with forged warrant record -> {read}")
    assert read == "REFUSED:WARRANT_UNVERIFIED", read
    assert _read(_product_reader(g), hypothesis) == "REFUSED:WARRANT_UNVERIFIED"


def test_r1_direct_event_rows_that_skip_the_episode_are_refused_by_the_database(guarded, roles):
    """Probe: an event written with no decision, or citing a decision that is not an ALLOW."""
    g = guarded
    hypothesis = _unscreened(g)

    def append(c: Any, decision: str | None) -> None:
        c.execute(
            "SELECT belief_revision_event_append(%s, %s, 'HYPOTHESIS', %s, 'ACTIVE', 'SUPPORTED',"
            " %s, %s, %s, %s, %s, NULL, NULL, now(), %s, %s)",
            (
                f"bre:tb-{uuid.uuid4().hex[:10]}",
                PROJECT,
                hypothesis,
                [g.attestation],
                [],
                sp.PROMOTE_MEASURED_POLICY_ID,
                sp.WARRANTED_VERTICAL_POLICY_VERSION,
                g.actor,
                "trc:tb",
                decision,
            ),
        )

    policy = SqlTransitionPolicyStore(g.db).get(
        sp.PROMOTE_MEASURED_POLICY_ID, sp.WARRANTED_VERTICAL_POLICY_VERSION
    )
    assert policy is not None
    with roles.connect(roles.app) as app:
        no_decision = _try(lambda: append(app, None))
        refused = _attempt_on(
            _writer(app, g, relations=SqlRelationStore(app, support_verifier=_accepting)),
            g,
            hypothesis,
            policy,
        )
        assert refused.event is None
        not_allow = _try(lambda: append(app, refused.authorization.decision_id))
    print(f"R-1 direct event, no decision: {no_decision!r}")
    print(f"R-1 direct event, {refused.authorization.result.value} decision: {not_allow!r}")
    assert no_decision is not None and not_allow is not None
    assert _read(_honest(g), hypothesis) == BeliefState.ACTIVE.value
