"""Capability kinds are not the services' to write: proved as a NON-superuser role (`011s`).

The test database's user is a superuser, which no trigger binds. So this creates throwaway roles,
grants them exactly what `lab-brain admin db-roles` grants (`grant_database_roles`: the services'
role reads and writes rows of every table), connects AS the services' role and shows:

    1. it cannot register a capability declaration -- the trigger checks `current_user` against
       the table's owner, so the row privilege it holds does not open it;
    2. it cannot reclassify a declared capability in `capabilities`, nor delete or rewrite a
       declaration, nor TRUNCATE either table;
    3. `register_pack_declarations` under it registers the capability row and leaves the kind
       UNDECLARED (fail closed) instead of failing.

No grant change is needed for this: the boundary is the trigger, not the privilege.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from lab_brain.core.models.capability import ActionType
from lab_brain.core.repositories.conditions import SqlConditionSchemaStore
from lab_brain.domains.silicon_photonics import vertical as sp
from lab_brain.domains.silicon_photonics.plugin import PACK_VERSION
from lab_brain.interfaces.deployment import grant_database_roles
from lab_brain.storage.postgres.capabilities import (
    may_declare_capabilities,
    register_pack_declarations,
)
from tests.postgres_fixtures import database_url

pytestmark = pytest.mark.postgres


@pytest.fixture
def as_app(db: Any) -> Iterator[Any]:
    suffix = secrets.token_hex(4)
    app, reader = f"lbt_pro_app_{suffix}", f"lbt_pro_reader_{suffix}"
    password = secrets.token_hex(24)
    db.execute(
        sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
            sql.Identifier(app), sql.Literal(password)
        )
    )
    db.execute(sql.SQL("CREATE ROLE {}").format(sql.Identifier(reader)))
    connection = None
    try:
        grant_database_roles(db, app_role=app, reader_role=reader)
        SqlConditionSchemaStore(db).ensure(sp.device_schema_registration())
        # The pack's kinds, declared through the governed path by the owner.
        assert (
            register_pack_declarations(
                db,
                pack_id=sp.DOMAIN,
                pack_version=PACK_VERSION,
                capabilities=tuple((c, sp.specification_media_types(c)) for c in sp.capabilities()),
            )
            == ()
        )
        params = {**conninfo_to_dict(database_url()), "user": app, "password": password}
        connection = psycopg.connect(**params, autocommit=True, connect_timeout=5)
        assert connection.execute(
            "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
        ).fetchone() == (False,)
        yield connection
    finally:
        if connection is not None:
            connection.close()
        for role in (app, reader):
            db.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
            db.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


def test_the_services_role_cannot_register_a_kind(as_app):
    assert not may_declare_capabilities(as_app)
    with pytest.raises(psycopg.errors.RaiseException, match="registered by the schema owner"):
        as_app.execute(
            "INSERT INTO capabilities (capability_id, domain, version, action_type, backend_id,"
            " requires, produces, authority_class, estimate_cost_contract)"
            " VALUES ('cap:sp.lookup_as_probe', 'silicon_photonics', '1.0.0', 'MEASUREMENT',"
            " 'sp.lookup', '{}', ARRAY['sp.probe_contact_resistance'], 'MEAS_CALIBRATED',"
            " 'cost:sp.fourpoint_probe@1.0.0');"
            "INSERT INTO capability_declarations (capability_id, capability_version, pack_id,"
            " pack_version, action_type, declaration, declaration_hash, registered_by,"
            " registered_at) VALUES ('cap:sp.lookup_as_probe', '1.0.0', 'silicon_photonics',"
            " '1.0.0', 'MEASUREMENT', '{}', 'sha256:' || repeat('0', 64), 'x', now())"
        )


def test_the_services_role_cannot_reclassify_or_erase_a_declared_kind(as_app):
    with pytest.raises(psycopg.errors.RaiseException, match="declared by its domain pack"):
        as_app.execute(
            "UPDATE capabilities SET action_type = 'MEASUREMENT' WHERE capability_id = %s",
            (sp.CAP_INSPECT_CONNECTIVITY,),
        )
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        as_app.execute(
            "UPDATE capability_declarations SET action_type = 'MEASUREMENT'"
            " WHERE capability_id = %s",
            (sp.CAP_INSPECT_CONNECTIVITY,),
        )
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        as_app.execute(
            "DELETE FROM capability_declarations WHERE capability_id = %s",
            (sp.CAP_INSPECT_CONNECTIVITY,),
        )
    for table in ("capability_declarations", "capabilities"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            as_app.execute(sql.SQL("TRUNCATE {} CASCADE").format(sql.Identifier(table)))
    # Availability is state, not contract: the services may still change it.
    as_app.execute(
        "UPDATE capabilities SET availability = 'DEGRADED' WHERE capability_id = %s",
        (sp.CAP_INSPECT_CONNECTIVITY,),
    )


def test_registration_under_the_services_role_leaves_a_new_kind_undeclared(as_app):
    probe = next(c for c in sp.capabilities() if c.capability_id == sp.CAP_FOURPOINT_PROBE)
    disguised = probe.model_copy(
        update={
            "capability_id": "cap:sp.lookup_as_probe",
            "action_type": ActionType.MEASUREMENT,
            "backend_id": "sp.lookup",
        }
    )
    assert register_pack_declarations(
        as_app,
        pack_id=sp.DOMAIN,
        pack_version=PACK_VERSION,
        capabilities=((disguised, ()), (probe, ())),
    ) == ("cap:sp.lookup_as_probe",)
    assert as_app.execute(
        "SELECT count(*) FROM capability_declarations WHERE capability_id = %s",
        ("cap:sp.lookup_as_probe",),
    ).fetchone() == (0,)


def test_the_operator_command_refuses_the_services_role(as_app):
    """`lab-brain admin declare-capabilities` under the services' role: refused, nothing declared."""
    import io

    from lab_brain.interfaces.cli import main

    out = io.StringIO()
    code = main(
        ["admin", "declare-capabilities"],
        out=out,
        env={**_env(), "LAB_BRAIN_DATABASE_URL": "unused"},
        connect=lambda _settings: as_app,
    )
    assert code == 2 and "only the schema owner" in out.getvalue(), out.getvalue()


def test_the_operator_command_declares_every_kind_as_the_owner(db):
    import io

    from lab_brain.interfaces.cli import main

    out = io.StringIO()

    class _Kept:
        """The fixture's connection, which `main` must not close."""

        def __init__(self, inner: Any) -> None:
            self._inner = inner

        def close(self) -> None:
            pass

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

    code = main(
        ["admin", "declare-capabilities"],
        out=out,
        env={**_env(), "LAB_BRAIN_DATABASE_URL": database_url()},
        connect=lambda _settings: _Kept(db),
    )
    assert code == 0, out.getvalue()
    assert "UNDECLARED" not in out.getvalue()
    for capability in sp.capabilities():
        assert f"declared  {capability.capability_id}" in out.getvalue()


def _env() -> dict[str, str]:
    import os

    return {k: v for k, v in os.environ.items() if k.startswith("LAB_BRAIN_")}
