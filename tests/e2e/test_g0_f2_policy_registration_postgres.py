"""G0 finding F2: the services' role must not be able to register a transition policy.

THE ATTACK (`docs/audit/g0-security-assurance-2026-11-04/REPORT.md`, finding F2). Acting as the
deployment's least-privilege services' role -- created exactly as a deployment creates it
(`deployment/docker/service_roles.py`, then `lab-brain admin db-roles`, i.e.
`grant_database_roles`) -- a writer:

    1. registers an `ACTIVE -> SUPPORTED` transition policy that requires nothing;
    2. runs the product's own governed `BeliefEpisode` under it, which records an ALLOW decision
       and a belief event that re-derive from their own (empty) snapshot;
    3. leaves the honest, product-wired projection (`BeliefEpisode.project`, which feeds the loop's
       state, the confirmation re-check and the episode report's final state) to read SUPPORTED.

No forged support, no signature and no relation is needed: whoever holds the services' credentials
could make any hypothesis SUPPORTED. The R8 projection fix re-checks the SUPPORTS in a decision's
snapshot; an empty snapshot has nothing to re-check.

The first test asserts the SECURE behaviour: step 1 is refused by the database, and the honest
projection never reads SUPPORTED. It was committed first as a strict xfail on the unfixed code
(evidence: `docs/audit/g0-f2-closure-2026-11-04/evidence/`); the fix -- owner-only registration,
approved by the Owner on 2026-11-04 -- removed the marker:

    grant_database_roles  revokes INSERT, UPDATE, DELETE and TRUNCATE on `transition_policies`
                          from the services' role, on every run;
    011x                  a BEFORE INSERT guard: only a member of the table's owner registers a
                          policy, so a privilege granted by mistake does not reopen it;
    register-policies     the operator (the migrator) registers the declared policies at start;
                          the research service registers missing ones only as the owner and
                          otherwise refuses the run before writing anything.

The other tests: the guard holds where INSERT was granted by mistake; the services' role can
neither UPDATE, DELETE, TRUNCATE, nor drop, disable, replace or bypass the guard, nor grant itself
the privilege; repeated grants, the role helper and re-running the migrations leave it closed; a
temporary table shadowing `transition_policies` in the attacker's session does not help (the
decision's foreign key names the real table); an owner-registered policy still governs a
legitimate transition written by the services' role; registered policies stay readable and the
decisions citing them still re-derive; the operator's command and the service's own path. The
residual probe records the services' role's privileges on the trust-root tables.

Engineering evidence only. G0 is NOT PASSED.
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import psycopg
import pytest
from psycopg import sql

from lab_brain.core.models import BeliefState, TransitionPolicy
from lab_brain.core.repositories import SqlTransitionPolicyStore
from lab_brain.core.repositories.evidence import SqlAttestationStore, SqlRelationStore
from lab_brain.interfaces.deployment import grant_database_roles
from lab_brain.research.service import (
    ADMISSION_POLICY,
    PolicyRegistrationRefused,
    register_vertical_policies,
)
from lab_brain.verification import prospective
from tests.e2e.test_g0_screening_independence_postgres import Guarded
from tests.e2e.test_g0_screening_independence_postgres import guarded as guarded
from tests.e2e.test_g0_screening_independence_postgres import standin as standin
from tests.e2e.test_g0_security_assurance_postgres import (
    UNWARRANTED_PROMOTE,
    _accepting,
    _attempt,
    _episode,
    _measured_support,
    _product_relations,
    _promote,
)
from tests.e2e.test_research_episode_postgres import PROJECT
from tests.integration import test_g0_spend_admin_postgres as _roles
from tests.postgres_fixtures import database_url

pytestmark = pytest.mark.postgres

ROOT = Path(__file__).resolve().parents[2]

# The deployment's least-privilege roles, created and dropped per test (`lab-brain admin db-roles`).
su = _roles.su
roles = _roles.roles

#: The database's refusals that count: no privilege, or the owner-only guard. Anything else (a
#: duplicate key, say) is not the boundary and must not pass for it.
REFUSALS = (psycopg.errors.InsufficientPrivilege, psycopg.errors.RaiseException)


def empty_promote() -> TransitionPolicy:
    """What the services' role tries to register: a promotion that requires nothing at all
    (a fresh id per test, so a policy left by an earlier run is never mistaken for a refusal)."""
    return TransitionPolicy(
        policy_id=f"policy:g0-f2-services-written-{uuid.uuid4().hex[:12]}",
        version="1.0.0",
        from_state=BeliefState.ACTIVE,
        candidate_to_state=BeliefState.SUPPORTED,
    )


def _registered(c: Any, policy: TransitionPolicy) -> bool:
    return SqlTransitionPolicyStore(c).get(policy.policy_id, policy.version) is not None


def _attack(g: Guarded, app: Any, policy: TransitionPolicy) -> tuple[Exception | None, Any]:
    """The whole F2 chain as the services' role; the database's refusal, if any, and the
    honest product projection afterwards."""
    refused: Exception | None = None
    try:
        SqlTransitionPolicyStore(app).register(policy)
    except psycopg.Error as exc:  # the database's own refusal
        refused = exc
    print(f"F2: services role registering {policy.policy_id}: refused={refused!r}")
    if refused is None:
        written = _attempt(
            _episode(app, SqlRelationStore(app, support_verifier=_accepting), g.keys.trust),
            g,
            policy.policy_id,
            policy.version,
            # An event cites a trigger; any admitted attestation of the project will do (here the
            # screening measurement the hypothesis was conditioned on -- not a support).
            (SqlAttestationStore(app).get(PROJECT, g.attestation),),
        )
        print(
            f"F2: services-role transition {written.authorization.result}"
            f" event={None if written.event is None else written.event.event_id}"
            " snapshot relations="
            f"{list(written.authorization.decision_input_snapshot.admitted_relations)}"
        )
    honest = _episode(g.db, _product_relations(g), g.keys.trust)
    projection = honest.project(project_id=PROJECT, hypothesis_id=g.hypothesis)
    print(f"F2: honest product projection of {g.hypothesis} -> {projection.current_state}")
    return refused, projection


def test_the_services_role_cannot_register_a_policy_that_makes_a_hypothesis_supported(
    guarded, roles
):
    g = guarded
    before = _episode(g.db, _product_relations(g), g.keys.trust).project(
        project_id=PROJECT, hypothesis_id=g.hypothesis
    )
    assert before.current_state is not BeliefState.SUPPORTED
    policy = empty_promote()
    with roles.connect(roles.app) as app:
        refused, projection = _attack(g, app, policy)
    assert refused is not None, "the services' role registered a transition policy"
    assert isinstance(refused, REFUSALS), refused
    assert not _registered(g.db, policy)
    assert projection.current_state is not BeliefState.SUPPORTED
    assert projection.current_state is before.current_state


# -- the guard itself ---------------------------------------------------------------------------


def _as(c: Any, statement: Any, params: tuple[object, ...] = ()) -> Exception | None:
    """Run `statement` on `c`; the database's refusal, or None if it was accepted."""
    try:
        c.execute(statement, params)
    except psycopg.Error as exc:
        return exc
    return None


def _privileges(su: Any, role: str, table: str) -> dict[str, bool]:
    return {
        p: bool(
            su.execute("SELECT has_table_privilege(%s, %s, %s)", (role, table, p)).fetchone()[0]
        )
        for p in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
    }


def _closed(su: Any, role: str) -> None:
    assert _privileges(su, role, "transition_policies") == {
        "SELECT": True,
        "INSERT": False,
        "UPDATE": False,
        "DELETE": False,
        "TRUNCATE": False,
        "REFERENCES": False,
        "TRIGGER": False,
    }
    ((enabled,),) = su.execute(
        "SELECT tgenabled FROM pg_trigger WHERE tgrelid = 'transition_policies'::regclass"
        " AND tgname = 'transition_policies_registered_by_the_owner'"
    ).fetchall()
    assert enabled == "O", "the owner-only guard must exist and be enabled"


def _insert_sql(policy: TransitionPolicy) -> tuple[str, tuple[object, ...]]:
    return (
        "INSERT INTO transition_policies (policy_id, version, from_state, candidate_to_state)"
        " VALUES (%s, %s, %s, %s)",
        (policy.policy_id, policy.version, "ACTIVE", "SUPPORTED"),
    )


def test_the_guard_refuses_the_services_role_where_insert_was_granted_by_mistake(su, roles):
    """Defence in depth: with INSERT granted by hand, `011x`'s trigger still refuses the row, and
    the next `db-roles` run takes the privilege away again."""
    su.execute(
        sql.SQL("GRANT INSERT ON transition_policies TO {}").format(sql.Identifier(roles.app))
    )
    policy = empty_promote()
    with roles.connect(roles.app) as app:
        refused = _as(app, *_insert_sql(policy))
    assert isinstance(refused, psycopg.errors.InsufficientPrivilege), refused
    assert "registered by the schema owner" in str(refused) and "011x" in str(refused)
    assert not _registered(su, policy)
    grant_database_roles(su, app_role=roles.app, reader_role=roles.reader)
    _closed(su, roles.app)


def test_the_services_role_cannot_change_erase_or_switch_off_the_guard(su, roles):
    """UPDATE, DELETE and TRUNCATE stay refused; and the services' role, which owns nothing,
    cannot drop, disable or replace the guard, turn triggers off, or grant itself the privilege."""
    app_ident = sql.Identifier(roles.app)
    attempts = {
        "update": "UPDATE transition_policies SET human_gate = human_gate",
        "delete": "DELETE FROM transition_policies",
        "truncate": "TRUNCATE transition_policies",
        "disable trigger": "ALTER TABLE transition_policies DISABLE TRIGGER"
        " transition_policies_registered_by_the_owner",
        "disable all triggers": "ALTER TABLE transition_policies DISABLE TRIGGER ALL",
        "drop trigger": "DROP TRIGGER transition_policies_registered_by_the_owner"
        " ON transition_policies",
        "replace function": "CREATE OR REPLACE FUNCTION"
        " transition_policies_are_registered_by_the_owner() RETURNS TRIGGER AS"
        " 'BEGIN RETURN NEW; END' LANGUAGE plpgsql",
        "drop function": "DROP FUNCTION transition_policies_are_registered_by_the_owner() CASCADE",
        "replication role": "SET session_replication_role = replica",
        "default privileges of the owner": sql.SQL(
            "ALTER DEFAULT PRIVILEGES FOR ROLE {} GRANT INSERT ON TABLES TO {}"
        ).format(
            sql.Identifier(
                su.execute(
                    "SELECT relowner::regrole::text FROM pg_class"
                    " WHERE oid = 'transition_policies'::regclass"
                ).fetchone()[0]
            ),
            app_ident,
        ),
        "own the table": sql.SQL("ALTER TABLE transition_policies OWNER TO {}").format(app_ident),
    }
    with roles.connect(roles.app) as app:
        accepted = [name for name, statement in attempts.items() if _as(app, statement) is None]
        # A GRANT by a role without the grant option is not an error: PostgreSQL warns that no
        # privileges were granted. What counts is the privilege afterwards.
        app.execute(sql.SQL("GRANT INSERT ON transition_policies TO {}").format(app_ident))
    assert accepted == [], f"the services' role was allowed to: {accepted}"
    _closed(su, roles.app)
    # Even with UPDATE and DELETE granted by mistake, `005b` keeps a registered version immutable.
    su.execute(sql.SQL("GRANT UPDATE, DELETE ON transition_policies TO {}").format(app_ident))
    with roles.connect(roles.app) as app:
        for statement in attempts["update"], attempts["delete"]:
            refused = _as(app, statement + " WHERE policy_id = %s", (ADMISSION_POLICY.policy_id,))
            assert isinstance(refused, psycopg.errors.RaiseException), refused
            assert "immutable" in str(refused)
    grant_database_roles(su, app_role=roles.app, reader_role=roles.reader)
    _closed(su, roles.app)


def test_repeated_grants_role_helpers_and_migrations_do_not_reopen_it(su, roles):
    """`db-roles` twice, the deployment's role helper again, the migrations again (nothing to
    apply), `db-roles` again: the services' role reads policies and registers none. The default
    privileges `db-roles` sets reach only tables created later -- never this one."""
    first = grant_database_roles(su, app_role=roles.app, reader_role=roles.reader)
    assert grant_database_roles(su, app_role=roles.app, reader_role=roles.reader) == first
    _closed(su, roles.app)
    _roles._service_roles().ensure_roles(
        su, roles.password, app_role=roles.app, reader_role=roles.reader
    )
    _closed(su, roles.app)
    migrated = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "migrate.py")],
        env={**os.environ, "LAB_BRAIN_DATABASE_URL": database_url()},
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert migrated.returncode == 0, migrated.stdout + migrated.stderr
    assert "up to date" in migrated.stdout
    _closed(su, roles.app)
    grant_database_roles(su, app_role=roles.app, reader_role=roles.reader)
    _closed(su, roles.app)
    # The table's own ACL, not a default privilege, decides: none names the services' role
    # with INSERT, and the reader reads.
    assert _privileges(su, roles.reader, "transition_policies")["INSERT"] is False
    assert _privileges(su, roles.reader, "transition_policies")["SELECT"] is True
    policy = empty_promote()
    with roles.connect(roles.app) as app:
        refused = _as(app, *_insert_sql(policy))
    assert isinstance(refused, psycopg.errors.InsufficientPrivilege), refused


# -- the attack, other ways round ---------------------------------------------------------------


def test_a_temporary_table_shadowing_the_policies_does_not_help(guarded, roles):
    """In its own session the services' role may create a temporary `transition_policies`, which
    unqualified reads in THAT session find first. The decision and event tables' foreign keys
    name the real table, so nothing under the shadow policy is stored, and the honest
    projection is unchanged."""
    g = guarded
    policy = empty_promote()
    with roles.connect(roles.app) as app:
        shadow = _as(
            app,
            "CREATE TEMPORARY TABLE transition_policies"
            " (LIKE public.transition_policies INCLUDING DEFAULTS)",
        )
        # PostgreSQL grants TEMP to PUBLIC by default, so the probe really runs here.
        assert shadow is None, shadow
        if shadow is None:
            app.execute(*_insert_sql(policy))
            assert _registered(app, policy), "the shadow is what this session reads"
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                _attempt(
                    _episode(app, SqlRelationStore(app, support_verifier=_accepting), g.keys.trust),
                    g,
                    policy.policy_id,
                    policy.version,
                    (SqlAttestationStore(app).get(PROJECT, g.attestation),),
                )
    assert not _registered(g.db, policy)
    projection = _episode(g.db, _product_relations(g), g.keys.trust).project(
        project_id=PROJECT, hypothesis_id=g.hypothesis
    )
    assert projection.current_state is not BeliefState.SUPPORTED


# -- authorized administration still works ------------------------------------------------------


def test_an_owner_registered_policy_still_governs_a_legitimate_transition(guarded, roles):
    """Positive control: the owner registers the policy (`_promote` does, as the schema owner);
    the services' role writes a signed, measured support and runs the governed transition
    through the product's own relation store and verifier; the honest projection reads
    SUPPORTED. Owner-only registration takes nothing from a legitimate flow."""
    g = guarded
    with roles.connect(roles.app) as app:
        relation = _measured_support(g, "f2-legitimate", g.authorize("f2-legitimate"), app)
        relations = SqlRelationStore(
            app, support_verifier=prospective.prospective_support_verifier(app, g.keys.trust)
        )
        written = _promote(g, app, relations, relation)
    assert _registered(g.db, UNWARRANTED_PROMOTE)
    assert written.event is not None
    assert relation in {
        r.relation_id for r in written.authorization.decision_input_snapshot.admitted_relations
    }
    projection = _episode(g.db, _product_relations(g), g.keys.trust).project(
        project_id=PROJECT, hypothesis_id=g.hypothesis
    )
    assert projection.current_state is BeliefState.SUPPORTED
    assert written.event.event_id in projection.applied


def test_registered_policies_stay_readable_and_their_decisions_still_re_derive(guarded, roles):
    """History: the product's policies were registered before this test (by the episode run as the
    owner), and one row is written as a pre-`011x` services' row would have been (triggers off,
    as only a superuser can). The services' and reader's roles read them; the hypothesis's stored
    history -- its admission under the registered admission policy -- still re-derives, read
    through the services' role."""
    g = guarded
    legacy = empty_promote()
    with g.db.transaction():
        g.db.execute("SET LOCAL session_replication_role = replica")
        g.db.execute(*_insert_sql(legacy))
    with roles.connect(roles.app) as app:
        for policy in (ADMISSION_POLICY, legacy):
            assert _registered(app, policy), policy.policy_id
        projection = _episode(
            app,
            SqlRelationStore(
                app, support_verifier=prospective.prospective_support_verifier(app, g.keys.trust)
            ),
            g.keys.trust,
        ).project(project_id=PROJECT, hypothesis_id=g.hypothesis)
    assert projection.current_state is BeliefState.ACTIVE
    assert projection.applied, "the admission event re-derived and was folded in"
    (cited,) = g.db.execute(
        "SELECT count(*) FROM belief_revision_events WHERE target_id = %s"
        " AND policy_id = %s AND policy_version = %s",
        (g.hypothesis, ADMISSION_POLICY.policy_id, ADMISSION_POLICY.version),
    ).fetchone()
    assert cited >= 1
    reader = _privileges(g.db, roles.reader, "transition_policies")
    assert reader["SELECT"] and not reader["INSERT"]


# -- the product's registration paths -----------------------------------------------------------


class _Kept:
    """A fixture's connection, which `main` must not close."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def close(self) -> None:
        pass

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k.startswith("LAB_BRAIN_")}


def _admin(connection: Any, *argv: str) -> tuple[int, str]:
    from lab_brain.interfaces.cli import main

    out = io.StringIO()
    code = main(
        ["admin", *argv],
        out=out,
        env={**_env(), "LAB_BRAIN_DATABASE_URL": database_url()},
        connect=lambda _settings: _Kept(connection),
    )
    return code, out.getvalue()


def test_the_operator_command_registers_the_declared_policies_as_the_owner(su):
    """Idempotent; and a registered row the product does not declare is listed for the
    operator's audit (here one written by the owner by hand), never touched."""
    hand_written = empty_promote()
    su.execute(*_insert_sql(hand_written))
    code, out = _admin(su, "register-policies")
    assert code == 0, out
    assert f"{ADMISSION_POLICY.policy_id}@{ADMISSION_POLICY.version}" in out
    assert f"undeclared  {hand_written.policy_id}@{hand_written.version}" in out
    assert _registered(su, hand_written)
    code_again, out_again = _admin(su, "register-policies")
    assert code_again == 0 and "registered " not in out_again, out_again


def test_the_service_path_refuses_a_missing_policy_under_the_services_role(su, roles):
    """`ResearchEpisodeService._register` calls `register_vertical_policies`: under the services'
    role a declared policy that is missing refuses the run before anything is written, naming the
    operator's command; under the owner it is registered. The operator's command under the
    services' role is refused the same way."""
    policy = empty_promote()
    vertical = cast(Any, SimpleNamespace(transition_policies=(policy,)))
    with roles.connect(roles.app) as app:
        with pytest.raises(PolicyRegistrationRefused, match="register-policies"):
            register_vertical_policies(app, vertical)
        assert not _registered(su, policy)
        assert register_vertical_policies(su, vertical) == (f"{policy.policy_id}@1.0.0",)
        assert register_vertical_policies(app, vertical) == ()  # all present: nothing to do
    assert _registered(su, policy)


def test_the_operator_command_refuses_the_services_role(su, roles, monkeypatch):
    """`lab-brain admin register-policies` under the services' role, with a declared policy
    missing: refused (exit 2), nothing registered."""
    from lab_brain.research import service

    policy = empty_promote()
    real = service.declared_policies
    monkeypatch.setattr(service, "declared_policies", lambda v: (*real(v), policy))
    with roles.connect(roles.app) as app:
        code, out = _admin(app, "register-policies")
    assert code == 2 and "only the schema owner" in out, out
    assert not _registered(su, policy)


# -- residual: what the services' role still writes ---------------------------------------------

#: Trust-root tables: rows a consequential reader decides from.
TRUST_ROOTS = (
    "transition_policies",
    "belief_transition_decisions",
    "belief_revision_events",
    "relation_judgments",
    "attestations",
    "verification_authorizations",
    "verification_authorizer_enrolments",
    "verification_authorizer_revocations",
    "warrant_reviewer_enrolments",
    "warrant_reviewer_revocations",
    "capability_declarations",
    "capabilities",
    "diagnostic_declaration_sets",
    "diagnostic_warrant_grants",
    "review_resolutions",
    "review_queue_policies",
    "schema_migrations",
    "llm_spend_budgets",
    "account_change_audit",
)


def test_residual_the_services_role_privileges_on_the_trust_roots(su, roles):
    """Recorded, not a fix: which trust-root tables the services' role still writes. The only
    change this pass makes is `transition_policies` (read-only); the rest is the A12 boundary
    the readers' own verification must hold (see the F2 closure report's residual risks)."""
    missing = [
        t
        for t in TRUST_ROOTS
        if su.execute("SELECT to_regclass(%s)", (f"public.{t}",)).fetchone()[0] is None
    ]
    assert missing == []
    matrix = {t: _privileges(su, roles.app, t) for t in TRUST_ROOTS}
    for table, privileges in matrix.items():
        granted = ",".join(p for p, held in privileges.items() if held) or "-"
        print(f"RESIDUAL: {roles.app} on {table}: {granted}")
    assert matrix["transition_policies"]["INSERT"] is False
    assert matrix["schema_migrations"]["INSERT"] is False
    assert all(not p["TRUNCATE"] for p in matrix.values())
