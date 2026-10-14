"""Least-privilege database access (Causal Warrant Gate V1.1; the owner: no production superuser).

Every rule the gate puts in the database is a trigger or a constraint, and a superuser -- or a
table's owner -- can step past both. The V1.1 design record named that as the database's root of
trust. `lab-brain admin db-roles` grants the services' role row privileges only, so the rules bind
it. These tests create two throwaway login roles (random names and passwords, dropped afterwards),
grant them through the command, and show:

1. the product runs a whole diagnosis episode as the services' role, and the harness still finds
   the SQL and Python confirmation rules agreeing;
2. that role cannot step past what binds it: no `session_replication_role`, no `DISABLE TRIGGER`,
   no `DROP TRIGGER`, no `TRUNCATE` (which fires no row trigger), no new objects, no other role, no
   write to the migrations ledger, and the append-only records refuse its edits;
3. the auditors' role reads and writes nothing;
4. the command refuses a role that could undo what it grants, and grants nothing then.
"""

from __future__ import annotations

import io
import secrets
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from lab_brain.interfaces import cli
from lab_brain.verification.loop import StopReason
from tests.postgres_fixtures import database_url
from tests.vertical_fixtures import case_by_id, load_fixture, run_case

pytestmark = pytest.mark.postgres


def _main(*argv: str) -> tuple[int, str]:
    out = io.StringIO()
    code = cli.main(
        list(argv),
        out=out,
        env={"LAB_BRAIN_DATABASE_URL": database_url()},
        connect=lambda s: psycopg.connect(s.dsn, autocommit=True),
    )
    return code, out.getvalue()


def _connect_as(role: str, password: str) -> Any:
    params = {**conninfo_to_dict(database_url()), "user": role, "password": password}
    return psycopg.connect(**params, autocommit=True, connect_timeout=5)


def _refused(connection: Any, statement: str, error: type[Exception]) -> None:
    """`statement` is refused with `error`. Attempted inside a transaction that is always rolled
    back, so a regression that let it through still leaves the test database as it was."""
    with pytest.raises(error), connection.transaction(force_rollback=True):
        connection.execute(statement)


def _drop(connection: Any, *roles: str) -> None:
    for role in roles:
        if connection.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone():
            connection.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            connection.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


@pytest.fixture
def roles(db: Any) -> Iterator[tuple[str, str, str]]:
    """Two login roles with nothing granted yet: (services' role, auditors' role, password)."""
    suffix = secrets.token_hex(4)
    app, reader = f"lbt_app_{suffix}", f"lbt_reader_{suffix}"
    password = secrets.token_urlsafe(24)
    for role in (app, reader):
        db.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier(role), sql.Literal(password)
            )
        )
    try:
        yield app, reader, password
    finally:
        _drop(db, app, reader)


def test_the_product_runs_a_whole_episode_as_the_services_role(db, roles):  # type: ignore[no-untyped-def]
    app, reader, password = roles
    code, out = _main("admin", "db-roles", "--app-role", app, "--reader-role", reader)
    assert code == 0, out
    assert f"database role {app}: reads and writes rows" in out
    fx = load_fixture()
    with _connect_as(app, password) as as_app:
        assert as_app.execute(
            "SELECT current_user = %s AND NOT rolsuper FROM pg_roles WHERE rolname = current_user",
            (app,),
        ).fetchone() == (True,)
        # `run_case` runs the loop as `CheckedLoop`: after the run, SQL's rule and the loop's agree.
        run = run_case(as_app, fx, case_by_id(fx, "contact-open-via"))
    assert run.result.stop_reason is StopReason.CONFIRMED
    assert run.mechanism_of(run.result.confirmed_root_cause) == "contact_discontinuity"


#: What a writer holding the services' credential would try, to get past the database's rules.
_ESCAPES = (
    "SET session_replication_role = replica",
    "ALTER TABLE failure_analyses DISABLE TRIGGER ALL",
    "DROP TRIGGER failure_analyses_with_the_confirmation_rule_trg ON failure_analyses",
    "TRUNCATE warrant_reviewer_revocations",
    "TRUNCATE failure_analysis_flags",
    "CREATE TABLE lbt_scratch (x INT)",
    "CREATE FUNCTION lbt_scratch() RETURNS INT LANGUAGE sql AS 'SELECT 1'",
    "CREATE OR REPLACE FUNCTION cwg_state(p_project TEXT, p_hypothesis TEXT) RETURNS TEXT"
    " LANGUAGE sql AS 'SELECT NULL::TEXT'",
    "DELETE FROM schema_migrations",
    "INSERT INTO schema_migrations (filename, checksum, apply_index) VALUES ('x', 'x', 999)",
    "SET ROLE lab_brain",
    "GRANT pg_write_all_data TO CURRENT_USER",
)


def test_the_services_role_cannot_step_past_the_rules_that_bind_it(db, roles):  # type: ignore[no-untyped-def]
    app, reader, password = roles
    assert _main("admin", "db-roles", "--app-role", app, "--reader-role", reader)[0] == 0
    fx = load_fixture()
    with _connect_as(app, password) as as_app:
        run_case(as_app, fx, case_by_id(fx, "contact-open-via"))
        for statement in _ESCAPES:
            _refused(as_app, statement, psycopg.errors.InsufficientPrivilege)
        # The append-only records refuse it as they refuse anyone: their triggers still fire.
        for statement in (
            "UPDATE failure_analyses SET failure_class = 'something else'",
            "DELETE FROM failure_analyses",
            "UPDATE belief_revision_events SET to_state = from_state",
            "DELETE FROM belief_revision_events",
            "DELETE FROM belief_transition_decisions",
            "DELETE FROM diagnostic_declaration_sets",
        ):
            _refused(as_app, statement, psycopg.errors.RaiseException)
    trigger_states = db.execute(
        "SELECT DISTINCT tgenabled FROM pg_trigger WHERE tgrelid = 'failure_analyses'::regclass"
        " AND NOT tgisinternal"
    ).fetchall()
    assert trigger_states == [("O",)], "every trigger on failure_analyses is still enabled"


def test_the_auditors_role_reads_and_writes_nothing(db, roles):  # type: ignore[no-untyped-def]
    app, reader, password = roles
    assert _main("admin", "db-roles", "--app-role", app, "--reader-role", reader)[0] == 0
    with _connect_as(reader, password) as as_reader:
        assert as_reader.execute("SELECT count(*) FROM actors").fetchone() == (1,)
        assert as_reader.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] > 0
        for statement in (
            "INSERT INTO actors (actor_id, actor_type, display_name) VALUES ('act:x', 'HUMAN', 'x')",
            "UPDATE projects SET name = 'renamed'",
            "DELETE FROM actors",
            "TRUNCATE actors",
        ):
            _refused(as_reader, statement, psycopg.errors.InsufficientPrivilege)


def test_db_roles_refuses_a_role_that_could_undo_what_it_grants(db, roles):  # type: ignore[no-untyped-def]
    app, reader, _ = roles
    owner = f"{app}_owner"
    db.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(owner)))
    try:
        db.execute(sql.SQL("CREATE TABLE {}.lbt_owned (x INT)").format(sql.Identifier("public")))
        db.execute(
            sql.SQL("ALTER TABLE public.lbt_owned OWNER TO {}").format(sql.Identifier(owner))
        )
        db.execute(sql.SQL("ALTER ROLE {} CREATEROLE").format(sql.Identifier(reader)))
        for argv, why in (
            (("--app-role", app, "--reader-role", reader), "can create roles"),
            (("--app-role", owner, "--reader-role", app), "owns, or acts as a role that owns"),
            (("--app-role", "lbt_nobody_here", "--reader-role", app), "does not exist"),
            (("--app-role", app, "--reader-role", app), "different roles"),
            (("--app-role", 'x"; DROP TABLE actors; --', "--reader-role", app), "plain lower-case"),
        ):
            code, out = _main("admin", "db-roles", *argv)
            assert code == 2 and why in out, (argv, out)
        db.execute(sql.SQL("ALTER ROLE {} NOCREATEROLE").format(sql.Identifier(reader)))
        db.execute(sql.SQL("GRANT {} TO {}").format(sql.Identifier(owner), sql.Identifier(app)))
        code, out = _main("admin", "db-roles", "--app-role", app, "--reader-role", reader)
        assert code == 2 and "acts as a role that owns" in out, out
        # Refused before anything was granted.
        assert db.execute(
            "SELECT has_table_privilege(%s, 'failure_analyses', 'INSERT')", (app,)
        ).fetchone() == (False,)
    finally:
        db.execute("DROP TABLE IF EXISTS public.lbt_owned")
        _drop(db, owner)
