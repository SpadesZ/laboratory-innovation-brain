"""`012f` against writers that do not go through the workspace, and the operator's commands.

Two authorities, held by the database:

    deployment LLM administration   only a current administrator -- an unrevoked grant to an active
                                    HUMAN actor -- creates a connection, locks a model, binds a
                                    slot, creates or activates a runtime. Membership grants none.
    project egress authorization    only an active member of THAT project holding LLM_EGRESS may
                                    declare its egress: labels within their clearance, never in
                                    Private Mode, only ENABLED EXTERNAL connections, versions in
                                    order, append-only.

And `LLMSettings` -- the workspace's operation behind each settings step -- refuses a non-administrator
at every step, including those whose rows name no actor for the database to check. And
`lab-brain admin ...`, the operator's way of making those grants: explicit, idempotent, and refusing
what the system would not understand.
"""

from __future__ import annotations

import io

import psycopg
import pytest

from lab_brain.core.models.inference import LogicalSlot
from lab_brain.interfaces import cli
from lab_brain.llm_runtime.runtime import LLMSettings, SettingsRefused
from lab_brain.llm_runtime.secrets import SecretStore
from tests.postgres_fixtures import database_url

pytestmark = pytest.mark.postgres

T0 = "2026-09-28T00:00:00Z"


class _Refused:
    def __init__(self, fragment: str) -> None:
        self.fragment = fragment

    def __enter__(self) -> None:
        return None

    def __exit__(self, kind, value, tb) -> bool:  # type: ignore[no-untyped-def]
        assert kind is not None, f"not refused: expected {self.fragment!r}"
        assert issubclass(kind, psycopg.Error), value
        assert self.fragment in str(value), str(value)
        return True


def _grant(db, actor: str = "act:test") -> None:  # type: ignore[no-untyped-def]
    db.execute(
        "INSERT INTO llm_administrators (actor_id, granted_at, granted_through)"
        " VALUES (%s, now(), 'OPERATOR_CLI')",
        (actor,),
    )


def _actor(db, actor: str, kind: str = "HUMAN") -> None:  # type: ignore[no-untyped-def]
    db.execute(
        "INSERT INTO actors (actor_id, actor_type, display_name) VALUES (%s, %s, %s)",
        (actor, kind, actor),
    )


def _connection(  # type: ignore[no-untyped-def]
    db,
    cid: str = "llc:ext",
    *,
    reach: str = "EXTERNAL",
    url: str = "https://api.example/v1",
    by: str = "act:test",
) -> None:
    db.execute(
        "INSERT INTO llm_connections (connection_id, name, provider_kind, base_url, reach,"
        " lifecycle, created_by, created_at, updated_at)"
        " VALUES (%s, %s, 'OPENAI_COMPATIBLE', %s, %s, 'ENABLED', %s, %s, %s)",
        (cid, cid.split(":")[1], url, reach, by, T0, T0),
    )


def _member(  # type: ignore[no-untyped-def]
    db,
    actor: str,
    project: str = "prj:test",
    *,
    clearance=("PUBLIC", "INTERNAL"),
    scopes=("LLM_EGRESS",),
) -> None:
    db.execute(
        "INSERT INTO project_memberships (actor_id, project_id, role, sensitivity_clearance,"
        " approval_scopes, active) VALUES (%s, %s, 'RESEARCHER', %s, %s, TRUE)",
        (actor, project, list(clearance), list(scopes)),
    )


def _declare(  # type: ignore[no-untyped-def]
    db,
    version: int,
    connections,
    labels,
    *,
    by: str = "act:test",
    project: str = "prj:test",
    pid: str | None = None,
) -> None:
    db.execute(
        "INSERT INTO project_llm_egress_policies (policy_id, project_id, version,"
        " approved_connection_ids, permitted_labels, declared_by_actor_id, declared_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            pid or f"lep:{project}:{version}",
            project,
            version,
            list(connections),
            list(labels),
            by,
            T0,
        ),
    )


# -- deployment LLM administration -------------------------------------------------------------


def test_only_a_current_administrator_configures_the_deployment_routes(db):
    # `act:test` is an active HUMAN member of nothing special -- and, above all, not granted.
    with _Refused("is not an LLM administrator"):
        _connection(db)
    _grant(db)
    _connection(db)
    db.execute(
        "INSERT INTO llm_models (model_profile_id, connection_id, model_name, source, created_at)"
        " VALUES ('llm:m', 'llc:ext', 'm', 'FETCHED', %s)",
        (T0,),
    )
    db.execute(
        "INSERT INTO llm_capability_probes (probe_id, model_profile_id, capability, outcome,"
        " probe_version, probed_at) SELECT 'lcp:' || c, 'llm:m', c, 'PASSED', 'p', %s FROM"
        " unnest(ARRAY['CHAT','STRUCTURED_JSON','ROLE_QUERY','ROLE_HYPOTHESIS','ROLE_SPECIALIST',"
        "'ROLE_CRITIQUE']) c",
        (T0,),
    )
    db.execute("UPDATE llm_models SET lifecycle = 'TESTED' WHERE model_profile_id = 'llm:m'")
    caps = [
        "CHAT",
        "ROLE_CRITIQUE",
        "ROLE_HYPOTHESIS",
        "ROLE_QUERY",
        "ROLE_SPECIALIST",
        "STRUCTURED_JSON",
    ]
    _actor(db, "act:member")
    _member(db, "act:member")
    lock = (
        "UPDATE llm_models SET lifecycle = 'LOCKED', locked_capabilities = %s,"
        " lock_fingerprint = 'lk:0123456789abcdef', locked_at = %s, locked_by = %s"
        " WHERE model_profile_id = 'llm:m'"
    )
    with _Refused("act:member is not an LLM administrator"):
        db.execute(lock, (caps, T0, "act:member"))
    db.execute(lock, (caps, T0, "act:test"))
    with _Refused("act:member is not an LLM administrator"):
        db.execute(
            "INSERT INTO llm_runtimes (runtime_id, name, created_by, created_at)"
            " VALUES ('lrt:x', 'x', 'act:member', %s)",
            (T0,),
        )
    db.execute(
        "INSERT INTO llm_runtimes (runtime_id, name, created_by, created_at)"
        " VALUES ('lrt:one', 'one', 'act:test', %s)",
        (T0,),
    )
    bind = (
        "INSERT INTO llm_slot_bindings (runtime_id, logical_slot, model_profile_id, bound_by,"
        " bound_at) VALUES ('lrt:one', %s, 'llm:m', %s, %s)"
    )
    with _Refused("act:member is not an LLM administrator"):
        db.execute(bind, ("REASONING_PRIMARY", "act:member", T0))
    db.execute(bind, ("REASONING_PRIMARY", "act:test", T0))
    db.execute(bind, ("FAST_UTILITY", "act:test", T0))
    activate = (
        "UPDATE llm_runtimes SET state = 'ACTIVE', activated_by = %s, activated_at = %s"
        " WHERE runtime_id = 'lrt:one'"
    )
    with _Refused("act:member is not an LLM administrator"):
        db.execute(activate, ("act:member", T0))
    # Revoked, the same actor is refused again.
    db.execute("UPDATE llm_administrators SET revoked_at = now() WHERE actor_id = 'act:test'")
    with _Refused("act:test is not an LLM administrator"):
        db.execute(activate, ("act:test", T0))
    _grant(db)
    db.execute(activate, ("act:test", T0))


def test_a_grant_goes_to_an_active_person_and_is_revoked_never_rewritten(db):
    _actor(db, "act:service", "SERVICE")
    with _Refused("only to an active HUMAN actor"):
        _grant(db, "act:service")
    _grant(db)
    with _Refused("llm_administrators_one_current"):
        _grant(db)
    with _Refused("revoked, never deleted"):
        db.execute("DELETE FROM llm_administrators")
    with _Refused("only by being revoked, once"):
        db.execute(
            "UPDATE llm_administrators SET granted_through = 'OPERATOR_CLI',"
            " granted_at = now() - interval '1 day'"
        )
    db.execute("UPDATE llm_administrators SET revoked_at = now()")
    with _Refused("only by being revoked, once"):
        db.execute("UPDATE llm_administrators SET revoked_at = now() + interval '1 hour'")
    # A deactivated person administers nothing, grant or no grant.
    _grant(db)
    assert db.execute("SELECT llm_is_administrator('act:test')").fetchone()[0] is True
    db.execute("UPDATE actors SET active = FALSE WHERE actor_id = 'act:test'")
    assert db.execute("SELECT llm_is_administrator('act:test')").fetchone()[0] is False


def test_local_names_this_machine_or_the_containers_docker_host_and_nothing_else(db):
    _grant(db)
    _connection(db, "llc:gw", reach="LOCAL", url="http://host.docker.internal:11434/v1")
    for url in (
        "http://10.0.0.5:11434/v1",
        "http://host.docker.internal.evil.test/v1",
        "http://evil.test/host.docker.internal/v1",
    ):
        with _Refused("local_is_this_machine"):
            _connection(db, "llc:no", reach="LOCAL", url=url)


# -- project egress authorization --------------------------------------------------------------


def _world(db) -> None:  # type: ignore[no-untyped-def]
    _grant(db)
    _connection(db, "llc:ext")
    _connection(db, "llc:loc", reach="LOCAL", url="http://127.0.0.1:11434/v1")
    db.execute("UPDATE projects SET privacy_mode = 'RESEARCH' WHERE project_id = 'prj:test'")
    db.execute(
        "INSERT INTO projects (project_id, name, privacy_mode) VALUES"
        " ('prj:other', 'Other', 'RESEARCH')"
    )
    _member(db, "act:test")


def test_a_project_declares_its_own_egress_and_nobody_elses(db):
    _world(db)
    # An administrator of the deployment who is no member of prj:other declares nothing for it.
    with _Refused("may not declare the external-model egress of prj:other"):
        _declare(db, 1, ["llc:ext"], ["PUBLIC"], project="prj:other")
    # A member of prj:other without the LLM_EGRESS scope does not either.
    _actor(db, "act:b")
    _member(db, "act:b", "prj:other", scopes=())
    with _Refused("LLM_EGRESS approval scope"):
        _declare(db, 1, ["llc:ext"], ["PUBLIC"], by="act:b", project="prj:other")
    # With the scope, within their clearance.
    db.execute(
        "UPDATE project_memberships SET approval_scopes = ARRAY['LLM_EGRESS']"
        " WHERE actor_id = 'act:b'"
    )
    with _Refused("may authorize only labels they are cleared for"):
        _declare(db, 1, ["llc:ext"], ["CONFIDENTIAL_LAB"], by="act:b", project="prj:other")
    _declare(db, 1, ["llc:ext"], ["PUBLIC"], by="act:b", project="prj:other")
    # prj:test is untouched by prj:other's declaration.
    assert (
        db.execute(
            "SELECT count(*) FROM project_llm_egress_policies WHERE project_id = 'prj:test'"
        ).fetchone()[0]
        == 0
    )


def test_a_declaration_names_only_enabled_external_connections_in_a_non_private_project(db):
    _world(db)
    with _Refused("only ENABLED EXTERNAL model connections"):
        _declare(db, 1, ["llc:loc"], ["PUBLIC"])
    with _Refused("only ENABLED EXTERNAL model connections"):
        _declare(db, 1, ["llc:nothing"], ["PUBLIC"])
    with _Refused("approved at most once"):
        _declare(db, 1, ["llc:ext", "llc:ext"], ["PUBLIC"])
    with _Refused("egress_policies_whole"):
        _declare(db, 1, ["llc:ext"], [])
    # Even a member cleared for RESTRICTED_NDA cannot let it leave.
    db.execute(
        "UPDATE project_memberships SET sensitivity_clearance = ARRAY['PUBLIC', 'INTERNAL',"
        " 'RESTRICTED_NDA'] WHERE actor_id = 'act:test'"
    )
    with _Refused("permitted_labels_check"):
        _declare(db, 1, ["llc:ext"], ["RESTRICTED_NDA"])
    with _Refused("is not the next one"):
        _declare(db, 2, ["llc:ext"], ["PUBLIC"])
    db.execute("UPDATE projects SET privacy_mode = 'PRIVATE' WHERE project_id = 'prj:test'")
    with _Refused("Private Mode"):
        _declare(db, 1, ["llc:ext"], ["PUBLIC"])
    # A withdrawal is always possible, Private Mode or not.
    _declare(db, 1, [], [])
    db.execute("UPDATE projects SET privacy_mode = 'RESEARCH' WHERE project_id = 'prj:test'")
    _declare(db, 2, ["llc:ext"], ["PUBLIC", "INTERNAL"])
    with _Refused("append-only"):
        db.execute("UPDATE project_llm_egress_policies SET permitted_labels = ARRAY['PUBLIC']")
    with _Refused("append-only"):
        db.execute("DELETE FROM project_llm_egress_policies")


def test_every_settings_step_refuses_a_non_administrator_before_it_writes_or_sends(db):
    _grant(db)
    _connection(db)
    db.execute(
        "INSERT INTO llm_runtimes (runtime_id, name, created_by, created_at)"
        " VALUES ('lrt:one', 'one', 'act:test', %s)",
        (T0,),
    )
    db.execute(
        "INSERT INTO llm_models (model_profile_id, connection_id, model_name, source, created_at)"
        " VALUES ('llm:m', 'llc:ext', 'm', 'FETCHED', %s)",
        (T0,),
    )
    _actor(db, "act:member")
    _member(db, "act:member")

    def client(*_args: object) -> object:
        raise AssertionError("a refused step reached a provider")

    llm = LLMSettings(
        db,
        secrets=SecretStore(environ={}, credentials=None),
        actor_id="act:member",
        client=client,  # type: ignore[arg-type]
    )
    assert llm.is_administrator is False
    tables = (
        "llm_connections",
        "llm_connection_health",
        "llm_models",
        "llm_capability_probes",
        "llm_runtimes",
        "llm_slot_bindings",
    )

    def rows() -> list[object]:
        return [db.execute(f"SELECT row_to_json(x)::text FROM {t} x").fetchall() for t in tables]

    before = rows()
    steps = (
        lambda: llm.add_connection(
            name="x", base_url="https://a.example/v1", reach="EXTERNAL", secret_mode="none"
        ),
        lambda: llm.replace_secret("llc:ext", secret_mode="none"),
        lambda: llm.set_connection_lifecycle("llc:ext", "DISABLED"),
        lambda: llm.check_health("llc:ext"),
        lambda: llm.fetch_models("llc:ext"),
        lambda: llm.declare_model("llc:ext", "other"),
        lambda: llm.test_model("llm:m"),
        lambda: llm.lock("llm:m"),
        lambda: llm.unlock("llm:m"),
        lambda: llm.retire_model("llm:m"),
        lambda: llm.create_runtime("mine", ["PUBLIC"]),
        lambda: llm.bind("lrt:one", LogicalSlot.FAST_UTILITY, "llm:m"),
        lambda: llm.unbind("lrt:one", LogicalSlot.FAST_UTILITY),
        lambda: llm.readiness("lrt:one", live=True),
        lambda: llm.activate("lrt:one"),
        lambda: llm.retire_runtime("lrt:one"),
    )
    for step in steps:
        with pytest.raises(SettingsRefused, match="act:member is not an LLM administrator"):
            step()
    assert rows() == before
    # Reading what the deployment serves is not administration.
    assert llm.readiness("lrt:one").runtime.runtime_id == "lrt:one"


# -- the operator's commands ----------------------------------------------------------------------


def _admin(*argv: str) -> tuple[int, str]:
    out = io.StringIO()
    code = cli.main(
        ["admin", *argv],
        out=out,
        env={"LAB_BRAIN_DATABASE_URL": database_url()},
        connect=lambda s: psycopg.connect(s.dsn),
    )
    return code, out.getvalue()


def test_the_operator_sets_up_people_projects_memberships_and_administrators(db):
    assert _admin("actor", "act:ada", "--name", "Ada") == (0, "created actor act:ada (HUMAN)\n")
    assert _admin("actor", "act:ada", "--name", "Ada")[1] == "actor act:ada unchanged\n"
    code, said = _admin("project", "prj:lab", "--name", "Lab")
    assert code == 0 and "PRIVATE mode" in said
    assert (
        db.execute("SELECT privacy_mode FROM projects WHERE project_id = 'prj:lab'").fetchone()[0]
        == "PRIVATE"
    )
    code, said = _admin(
        "member", "prj:lab", "act:ada", "--clearance", "PUBLIC,INTERNAL", "--scope", "LLM_EGRESS"
    )
    assert code == 0 and "scopes LLM_EGRESS" in said
    row = db.execute(
        "SELECT sensitivity_clearance, approval_scopes, active FROM project_memberships"
        " WHERE actor_id = 'act:ada'"
    ).fetchone()
    assert (sorted(row[0]), row[1], row[2]) == (["INTERNAL", "PUBLIC"], ["LLM_EGRESS"], True)
    assert (
        "unchanged"
        in _admin(
            "member",
            "prj:lab",
            "act:ada",
            "--clearance",
            "INTERNAL,PUBLIC",
            "--scope",
            "LLM_EGRESS",
        )[1]
    )
    # Nothing the system would not understand is stored.
    code, said = _admin("member", "prj:lab", "act:ada", "--scope", "ADMIN")
    assert code == 2 and "unknown approval scope" in said
    code, said = _admin("member", "prj:lab", "act:ada", "--clearance", "SECRET")
    assert code == 2 and "unknown sensitivity label" in said
    # LLM administration: its own grant, to a person, revocable.
    assert _admin("llm-admin", "act:ada")[0] == 0
    assert "already administers" in _admin("llm-admin", "act:ada")[1]
    assert db.execute("SELECT llm_is_administrator('act:ada')").fetchone()[0] is True
    db.execute("INSERT INTO actors (actor_id, actor_type) VALUES ('act:bot', 'SERVICE')")
    code, said = _admin("llm-admin", "act:bot")
    assert code == 2 and "only to an active HUMAN actor" in said
    assert "no longer administers" in _admin("llm-admin", "act:ada", "--revoke")[1]
    assert db.execute("SELECT llm_is_administrator('act:ada')").fetchone()[0] is False
    code, said = _admin("show")
    assert code == 0 and "act:ada  HUMAN  Ada" in said and "prj:lab  PRIVATE  Lab" in said
    code, said = _admin("project", "prj:lab", "--name", "Lab", "--privacy-mode", "RESEARCH")
    assert code == 0 and "RESEARCH mode" in said
