"""`012e` against writers that do not go through the workspace.

Every rule the LLM settings rely on, held by the database: no credential in a reference, LOCAL only
on this machine, an endpoint that cannot be edited into another, the model lifecycle (discovered ->
tested -> locked, a lock that freezes exactly what the latest probes proved), append-only probes and
health, a slot that takes only a locked model proving what the slot needs, PRIVATE_LOCAL only on a
LOCAL connection, M3's minimum route and the Critic's fallback at activation, one active runtime,
frozen active bindings, and nothing an active runtime depends on unlocked or disabled under it.

These writers act as `act:test`, whom the operator granted LLM administration (`012f`); what a
writer who is NOT an administrator meets is `test_llm_authority_postgres`'s subject.
"""

from __future__ import annotations

import psycopg
import pytest

from lab_brain.core.models.inference import LogicalSlot
from lab_brain.llm_runtime.capabilities import BINDABLE_SLOTS, SLOT_REQUIREMENTS

pytestmark = pytest.mark.postgres

T0 = "2026-09-28T00:00:00Z"
ALL = [
    "CHAT",
    "STRUCTURED_JSON",
    "ROLE_QUERY",
    "ROLE_HYPOTHESIS",
    "ROLE_SPECIALIST",
    "ROLE_CRITIQUE",
]


@pytest.fixture(autouse=True)
def _administrator(db):  # type: ignore[no-untyped-def]
    db.execute(
        "INSERT INTO llm_administrators (actor_id, granted_at, granted_through)"
        " VALUES ('act:test', now(), 'OPERATOR_CLI')"
    )


def _connection(
    db, cid: str = "llc:ext", *, reach: str = "EXTERNAL", url: str = "https://api.example.com/v1"
) -> None:  # type: ignore[no-untyped-def]
    db.execute(
        "INSERT INTO llm_connections (connection_id, name, provider_kind, base_url, reach,"
        " secret_ref, secret_fingerprint, lifecycle, created_by, created_at, updated_at)"
        " VALUES (%s, %s, 'OPENAI_COMPATIBLE', %s, %s, 'env:KEY', '****abcd', 'ENABLED',"
        " 'act:test', %s, %s)",
        (cid, cid.split(":")[1], url, reach, T0, T0),
    )


def _model(
    db, mid: str, cid: str = "llc:ext", caps: list[str] | None = None, lock: bool = True
) -> None:  # type: ignore[no-untyped-def]
    db.execute(
        "INSERT INTO llm_models (model_profile_id, connection_id, model_name, source, created_at)"
        " VALUES (%s, %s, %s, 'FETCHED', %s)",
        (mid, cid, mid.split(":")[1], T0),
    )
    for n, cap in enumerate(ALL if caps is None else caps):
        db.execute(
            "INSERT INTO llm_capability_probes (probe_id, model_profile_id, capability, outcome,"
            " probe_version, probed_at) VALUES (%s, %s, %s, 'PASSED', 'probe-1', %s)",
            (f"lcp:{mid}-{n}", mid, cap, T0),
        )
    db.execute("UPDATE llm_models SET lifecycle = 'TESTED' WHERE model_profile_id = %s", (mid,))
    if lock:
        _lock(db, mid)


def _lock(db, mid: str) -> None:  # type: ignore[no-untyped-def]
    db.execute(
        "UPDATE llm_models SET lifecycle = 'LOCKED', locked_capabilities ="
        " llm_verified_capabilities(model_profile_id), lock_fingerprint = 'lk:0123456789abcdef',"
        " locked_at = %s, locked_by = 'act:test' WHERE model_profile_id = %s",
        (T0, mid),
    )


def _runtime(db, rid: str = "lrt:one") -> None:  # type: ignore[no-untyped-def]
    db.execute(
        "INSERT INTO llm_runtimes (runtime_id, name, created_by, created_at)"
        " VALUES (%s, %s, 'act:test', %s)",
        (rid, rid, T0),
    )


def _bind(db, slot: str, mid: str, rid: str = "lrt:one") -> None:  # type: ignore[no-untyped-def]
    db.execute(
        "INSERT INTO llm_slot_bindings (runtime_id, logical_slot, model_profile_id, bound_by,"
        " bound_at) VALUES (%s, %s, %s, 'act:test', %s)",
        (rid, slot, mid, T0),
    )


def _activate(db, rid: str = "lrt:one") -> None:  # type: ignore[no-untyped-def]
    db.execute(
        "UPDATE llm_runtimes SET state = 'ACTIVE', activated_by = 'act:test', activated_at = %s"
        " WHERE runtime_id = %s",
        (T0, rid),
    )


def _refused(match: str) -> pytest.RaisesContext[psycopg.Error]:
    return pytest.raises(psycopg.Error, match=match)


def test_a_connection_holds_a_reference_never_a_credential(db):
    with _refused("llm_connections_secret_ref_check"):
        db.execute(
            "INSERT INTO llm_connections (connection_id, name, provider_kind, base_url, reach,"
            " secret_ref, secret_fingerprint, created_by, created_at, updated_at) VALUES"
            " ('llc:x', 'x', 'OPENAI_COMPATIBLE', 'https://a.example/v1', 'EXTERNAL',"
            " 'sk-live-abcdefghijklmnopqrstuv', '****abcd', 'act:test', %s, %s)",
            (T0, T0),
        )
    with _refused("secret_has_fingerprint"):
        db.execute(
            "INSERT INTO llm_connections (connection_id, name, provider_kind, base_url, reach,"
            " secret_ref, created_by, created_at, updated_at) VALUES ('llc:x', 'x',"
            " 'OPENAI_COMPATIBLE', 'https://a.example/v1', 'EXTERNAL', 'env:KEY', 'act:test',"
            " %s, %s)",
            (T0, T0),
        )
    with _refused("base_url_check"):
        _connection(db, url="https://user:secret@api.example.com/v1")


def test_local_is_declared_only_of_this_machine_and_an_endpoint_is_its_identity(db):
    with _refused("local_is_this_machine"):
        _connection(db, "llc:lan", reach="LOCAL", url="http://10.1.2.3:8000/v1")
    _connection(db, "llc:here", reach="LOCAL", url="http://127.0.0.1:11434/v1")
    with _refused("endpoint is its identity"):
        db.execute("UPDATE llm_connections SET base_url = 'https://evil.example/v1'")
    with _refused("retired, never deleted"):
        db.execute("DELETE FROM llm_connections")


def test_the_model_lifecycle_and_what_a_lock_may_freeze(db):
    _connection(db)
    with _refused("discovered first"):
        db.execute(
            "INSERT INTO llm_models (model_profile_id, connection_id, model_name, source, lifecycle,"
            " created_at) VALUES ('llm:m', 'llc:ext', 'm', 'FETCHED', 'LOCKED', %s)",
            (T0,),
        )
    _model(db, "llm:m", caps=["CHAT", "STRUCTURED_JSON"], lock=False)
    with _refused("a lock freezes exactly the capabilities whose latest probe passed"):
        db.execute(
            "UPDATE llm_models SET lifecycle = 'LOCKED', locked_capabilities ="
            " ARRAY['CHAT', 'STRUCTURED_JSON', 'VISION'], lock_fingerprint = 'lk:0123456789abcdef',"
            " locked_at = %s, locked_by = 'act:test'",
            (T0,),
        )
    _model(db, "llm:mute", caps=["STRUCTURED_JSON"], lock=False)
    with _refused("has not passed the CHAT probe"):
        _lock(db, "llm:mute")
    _lock(db, "llm:m")
    with _refused("unlock it to test it again"):
        db.execute(
            "INSERT INTO llm_capability_probes (probe_id, model_profile_id, capability, outcome,"
            " probe_version, probed_at) VALUES ('lcp:late', 'llm:m', 'CHAT', 'PASSED', 'p', %s)",
            (T0,),
        )
    with _refused("append-only"):
        db.execute("DELETE FROM llm_capability_probes")
    with _refused("identity is immutable"):
        db.execute("UPDATE llm_models SET model_name = 'other' WHERE model_profile_id = 'llm:m'")


def test_a_slot_takes_only_a_locked_model_that_proved_what_it_needs(db):
    _connection(db)
    _model(db, "llm:chat", caps=["CHAT"])
    _model(db, "llm:open", lock=False)
    _model(db, "llm:full")
    _runtime(db)
    with _refused("has not proven"):
        _bind(db, "REASONING_PRIMARY", "llm:chat")
    with _refused("only a LOCKED model"):
        _bind(db, "FAST_UTILITY", "llm:open")
    with _refused("PRIVATE_LOCAL is served only by a LOCAL model"):
        _bind(db, "PRIVATE_LOCAL", "llm:full")
    _bind(db, "REASONING_PRIMARY", "llm:full")


def test_activation_needs_the_minimum_route_and_a_critic_that_can_fall_back(db):
    _connection(db)
    _model(db, "llm:nocritic", caps=[c for c in ALL if c != "ROLE_CRITIQUE"])
    _model(db, "llm:full")
    _runtime(db)
    _bind(db, "REASONING_PRIMARY", "llm:nocritic")
    with _refused("lacks M3's minimum route"):
        _activate(db)
    _bind(db, "FAST_UTILITY", "llm:full")
    with _refused("has not proven ROLE_CRITIQUE"):
        _activate(db)
    _bind(db, "REASONING_ADVERSARIAL", "llm:full")
    _activate(db)
    with _refused("frozen"):
        _bind(db, "CODE", "llm:full")
    with _refused("cannot be unlocked"):
        db.execute(
            "UPDATE llm_models SET lifecycle = 'TESTED', locked_capabilities = NULL,"
            " lock_fingerprint = NULL, locked_at = NULL, locked_by = NULL"
            " WHERE model_profile_id = 'llm:full'"
        )
    with _refused("cannot be retired"):
        db.execute(
            "UPDATE llm_models SET lifecycle = 'RETIRED', locked_capabilities = NULL,"
            " lock_fingerprint = NULL, locked_at = NULL, locked_by = NULL"
            " WHERE model_profile_id = 'llm:full'"
        )
    with _refused("serves the active runtime"):
        db.execute("UPDATE llm_connections SET lifecycle = 'DISABLED'")
    _runtime(db, "lrt:two")
    _bind(db, "REASONING_PRIMARY", "llm:full", "lrt:two")
    _bind(db, "FAST_UTILITY", "llm:full", "lrt:two")
    with _refused("one_active"):
        _activate(db, "lrt:two")
    with _refused("cannot move ACTIVE -> DRAFT"):
        db.execute(
            "UPDATE llm_runtimes SET state = 'DRAFT', activated_at = NULL, activated_by = NULL WHERE runtime_id = 'lrt:one'"
        )


def test_health_is_append_only_and_restricted_evidence_never_leaves(db):
    _connection(db)
    db.execute(
        "INSERT INTO llm_connection_health (check_id, connection_id, outcome, checked_at)"
        " VALUES ('lch:1', 'llc:ext', 'REACHABLE', %s)",
        (T0,),
    )
    with _refused("append-only"):
        db.execute("UPDATE llm_connection_health SET outcome = 'UNREACHABLE'")
    with _refused("external_labels_check"):
        db.execute(
            "INSERT INTO llm_runtimes (runtime_id, name, external_labels, created_by, created_at)"
            " VALUES ('lrt:nda', 'nda', ARRAY['PUBLIC', 'RESTRICTED_NDA'], 'act:test', %s)",
            (T0,),
        )


def test_the_database_and_the_code_agree_on_what_each_slot_needs(db):
    for slot in BINDABLE_SLOTS:
        required = db.execute("SELECT llm_slot_requirements(%s)", (slot.value,)).fetchone()[0]
        assert set(required) == {c.value for c in SLOT_REQUIREMENTS[slot]}, slot
    assert (
        db.execute("SELECT llm_slot_requirements(%s)", (LogicalSlot.EMBEDDING.value,)).fetchone()[0]
        is None
    )
