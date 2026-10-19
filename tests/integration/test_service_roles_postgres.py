"""The services' database roles, as the container deployment's `init` creates them.

`deployment/docker/service_roles.py` runs as the migrator before `lab-brain admin db-roles`: it
creates (or resets) the role `web` and `local-models` connect as, with the password from the
services' own secret volume, and the auditors' role without a login. Against the real server,
with throwaway role names (roles are cluster-wide), dropped afterwards:

1. the roles hold none of the attributes that could step past or undo `db-roles`, even when one
   existed with them;
2. the password is stored as a SCRAM-SHA-256 verifier the server accepts: the services' role logs
   in with it, and the auditors' role cannot log in;
3. a second run changes nothing, and a different password is set;
4. `db-roles` then accepts both roles, as `init` runs it next.
"""

from __future__ import annotations

import importlib.util
import io
import secrets
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from lab_brain.interfaces import cli
from tests.postgres_fixtures import database_url

pytestmark = pytest.mark.postgres

ROOT = Path(__file__).resolve().parents[2]


def _service_roles() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "service_roles", ROOT / "deployment" / "docker" / "service_roles.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _connect_as(role: str, password: str) -> Any:
    params = {**conninfo_to_dict(database_url()), "user": role, "password": password}
    return psycopg.connect(**params, autocommit=True, connect_timeout=5)


@pytest.fixture
def names(db: Any) -> Iterator[tuple[str, str]]:
    suffix = secrets.token_hex(4)
    app, reader = f"lbt_svc_app_{suffix}", f"lbt_svc_reader_{suffix}"
    try:
        yield app, reader
    finally:
        for role in (app, reader):
            if db.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone():
                db.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
                db.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


def _attributes(db: Any, role: str) -> tuple[Any, ...]:
    return tuple(
        db.execute(
            "SELECT rolsuper, rolcreaterole, rolcreatedb, rolreplication, rolbypassrls,"
            " rolcanlogin, has_parameter_privilege(oid, 'session_replication_role', 'SET')"
            " FROM pg_roles WHERE rolname = %s",
            (role,),
        ).fetchone()
    )


def test_the_services_role_logs_in_with_its_file_and_holds_no_escape(db, names):
    app, reader = names
    roles = _service_roles()
    password = secrets.token_hex(24)
    # A role left with an attribute that could undo the grants is reset, not trusted.
    db.execute(sql.SQL("CREATE ROLE {} CREATEDB").format(sql.Identifier(app)))
    lines = roles.ensure_roles(db, password, app_role=app, reader_role=reader)
    assert lines[0].startswith(f"database role {app}: updated (login;")
    assert lines[1].startswith(f"database role {reader}: created (no login;")
    assert _attributes(db, app) == (False, False, False, False, False, True, False)
    assert _attributes(db, reader) == (False, False, False, False, False, False, False)
    (stored,) = db.execute(
        "SELECT rolpassword FROM pg_authid WHERE rolname = %s", (app,)
    ).fetchone()
    assert stored.startswith("SCRAM-SHA-256$4096:") and roles.verifies(stored, password)
    with _connect_as(app, password) as as_app:
        assert as_app.execute("SELECT current_user").fetchone() == (app,)
    with pytest.raises(psycopg.OperationalError):
        _connect_as(app, secrets.token_hex(24)).close()
    # No password and no login: refused either way, whatever the server checks first.
    with pytest.raises(
        psycopg.OperationalError, match=r"password authentication failed|not permitted to log in"
    ):
        _connect_as(reader, password).close()


def test_a_second_start_changes_nothing_and_a_new_password_is_set(db, names):
    app, reader = names
    roles = _service_roles()
    first = secrets.token_hex(24)
    assert [
        line.split(":")[1].split()[0]
        for line in roles.ensure_roles(db, first, app_role=app, reader_role=reader)
    ] == ["created", "created"]
    (before,) = db.execute(
        "SELECT rolpassword FROM pg_authid WHERE rolname = %s", (app,)
    ).fetchone()
    again = roles.ensure_roles(db, first, app_role=app, reader_role=reader)
    assert [line.split(":")[1].split()[0] for line in again] == ["unchanged", "unchanged"]
    assert db.execute(
        "SELECT rolpassword FROM pg_authid WHERE rolname = %s", (app,)
    ).fetchone() == (before,), "the stored verifier is not re-salted on every start"
    second = secrets.token_hex(24)
    assert roles.ensure_roles(db, second, app_role=app, reader_role=reader)[0].startswith(
        f"database role {app}: updated"
    )
    with _connect_as(app, second) as as_app:
        assert as_app.execute("SELECT 1").fetchone() == (1,)
    with pytest.raises(ValueError, match=r"generated by make_secret.py"):
        roles.ensure_roles(db, "short", app_role=app, reader_role=reader)


def test_db_roles_accepts_the_roles_init_creates(db, names):
    app, reader = names
    _service_roles().ensure_roles(db, secrets.token_hex(24), app_role=app, reader_role=reader)
    out = io.StringIO()
    code = cli.main(
        ["admin", "db-roles", "--app-role", app, "--reader-role", reader],
        out=out,
        env={"LAB_BRAIN_DATABASE_URL": database_url()},
        connect=lambda s: psycopg.connect(s.dsn, autocommit=True),
    )
    assert code == 0, out.getvalue()
    assert f"database role {app}: reads and writes rows" in out.getvalue()
