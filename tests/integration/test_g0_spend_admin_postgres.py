"""Who may change the money: the Owner's spend administration against the services' role.

Against the real server, connecting AS the least-privilege roles a deployment uses -- never as
the test superuser, which every rule here would let through. Each test creates throwaway roles
(roles are cluster-wide) exactly as the container deployment does (`service_roles.ensure_roles`
and then `grant_database_roles`, i.e. `lab-brain admin db-roles`), and drops them afterwards:

    app      the services' login role: reserves, settles, retains and reads -- nothing else
    owner    a login role the operator made a member of `lab_brain_spend_admin` (migration 011t)

    app refused     raise a ceiling, close an open circuit, create a budget, declare or alter a
                    price, write the ledger, forge the writer flag (even with table privileges a
                    deployment granted by mistake), call any administration function, SET ROLE to
                    the administration role, TRUNCATE, disable triggers, replication role
    owner allowed   create a budget, declare a price, change a ceiling, close a circuit, declare
                    an endpoint free and revoke it
    bounded         concurrent reservations by the app, each on its own connection, never pass
                    the ceiling
    local proxy     a loopback endpoint is metered by a configured ceiling unless the Owner
                    declared it free; undeclared, an unpriced local request is refused unsent
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import secrets
import threading
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, replace
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from lab_brain.evaluation.live_budget import (
    LiveBudgetMissing,
    install_live_spend_guard,
    install_local_free_guard,
    spend_from_env,
)
from lab_brain.interfaces.deployment import OperatorRefused, grant_database_roles
from lab_brain.llm_runtime import spend
from lab_brain.llm_runtime.provider import OpenAICompatibleClient, ProviderError
from lab_brain.llm_runtime.spend import PostgresSpendGuard, SpendRequest
from tests.fake_llm_provider import FakeProvider
from tests.postgres_fixtures import database_url

pytestmark = pytest.mark.postgres

ROOT = Path(__file__).resolve().parents[2]
ADMIN = "lab_brain_spend_admin"
KEY = "sk-test-spend-admin-0123456789abcdefABCDEF"
DAY = dt.date(2026, 10, 28)


def _service_roles() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "service_roles", ROOT / "deployment" / "docker" / "service_roles.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class Roles:
    app: str
    reader: str
    owner: str
    password: str

    def dsn(self, role: str) -> str:
        params = {**conninfo_to_dict(database_url()), "user": role, "password": self.password}
        return psycopg.conninfo.make_conninfo(**params)

    def connect(self, role: str) -> Any:
        return psycopg.connect(self.dsn(role), autocommit=True, connect_timeout=5)


def _drop(su: Any, role: str) -> None:
    if su.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone():
        su.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role)))
        su.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


@pytest.fixture
def su(postgres_connection: Any) -> Any:
    """The migrator (a superuser here): sets the scene, never the subject of a boundary test."""
    return postgres_connection


@pytest.fixture
def roles(su: Any) -> Iterator[Roles]:
    suffix = secrets.token_hex(4)
    made = Roles(
        f"lbt_sp_app_{suffix}", f"lbt_sp_rd_{suffix}", f"lbt_sp_own_{suffix}", secrets.token_hex(24)
    )
    try:
        _service_roles().ensure_roles(su, made.password, app_role=made.app, reader_role=made.reader)
        grant_database_roles(su, app_role=made.app, reader_role=made.reader)
        su.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION"
                " NOBYPASSRLS PASSWORD {}"
            ).format(sql.Identifier(made.owner), sql.Literal(made.password))
        )
        if su.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (ADMIN,)).fetchone():
            su.execute(
                sql.SQL("GRANT {} TO {}").format(sql.Identifier(ADMIN), sql.Identifier(made.owner))
            )
        yield made
    finally:
        for role in (made.app, made.reader, made.owner):
            _drop(su, role)


def _budget(su: Any, ceiling: str = "10") -> str:
    budget = f"test-adm-{uuid.uuid4().hex[:12]}"
    spend.declare_budget(su, budget, currency="USD", ceiling=Decimal(ceiling), actor_id="act:owner")
    return budget


def _price(c: Any, budget: str, host: str = "api.example.test", model: str = "m") -> None:
    spend.declare_price(
        c,
        budget,
        endpoint_host=host,
        model=model,
        currency="USD",
        input_per_mtok=Decimal("2.5"),
        output_per_mtok=Decimal("15"),
        source="test fixture price, not a real provider's",
        source_date=DAY,
        actor_id="act:owner",
    )


def _state(su: Any, budget: str) -> spend.BudgetState:
    state = spend.budget_state(su, budget)
    assert state is not None
    return state


def _ledger_count(su: Any, budget: str) -> int:
    row = su.execute(
        "SELECT count(*) FROM llm_spend_ledger WHERE budget_id = %s", (budget,)
    ).fetchone()
    return int(row[0])


def _open_circuit(su: Any, budget: str) -> None:
    """An overrun, by the superuser: reported usage past the reservation opens the circuit."""
    call = spend.new_call_id()
    su.execute(
        "SELECT llm_spend_reserve(%s, %s, 'api.example.test', 'm', 100, 0, 10)", (budget, call)
    )
    assert su.execute("SELECT llm_spend_settle(%s, 50, 5000, 5050)", (call,)).fetchone() == (
        "OVERRUN",
    )
    assert _state(su, budget).circuit_open


Denied = (psycopg.errors.InsufficientPrivilege,)


# -- the services' role cannot change the money ----------------------------------------------------


def test_the_app_cannot_raise_its_own_ceiling(su, roles):
    budget = _budget(su, "1")
    with roles.connect(roles.app) as app, pytest.raises(Denied):
        spend.set_ceiling(app, budget, Decimal("1000000"), actor_id="act:app", reason="more")
    assert _state(su, budget).ceiling == Decimal(1)


def test_the_app_cannot_close_an_open_circuit(su, roles):
    budget = _budget(su, "1")
    _price(su, budget)
    _open_circuit(su, budget)
    charged = _state(su, budget).charged
    with roles.connect(roles.app) as app, pytest.raises(Denied):
        spend.set_ceiling(
            app, budget, charged + 1, actor_id="act:app", reason="x", close_circuit=True
        )
    assert _state(su, budget).circuit_open


def test_the_app_cannot_create_a_budget(su, roles):
    budget = f"test-adm-{uuid.uuid4().hex[:12]}"
    with roles.connect(roles.app) as app:
        with pytest.raises(Denied):
            spend.declare_budget(
                app, budget, currency="USD", ceiling=Decimal(5), actor_id="act:app"
            )
        with pytest.raises(Denied):
            app.execute(
                "INSERT INTO llm_spend_budgets (budget_id, currency, ceiling, declared_by)"
                " VALUES (%s, 'USD', 5, 'act:app')",
                (budget,),
            )
    assert spend.budget_state(su, budget) is None


def test_the_app_cannot_declare_or_alter_a_price(su, roles):
    budget = _budget(su)
    _price(su, budget)
    with roles.connect(roles.app) as app:
        with pytest.raises(Denied):
            _price(app, budget, model="cheap")
        with pytest.raises(Denied):
            app.execute(
                "INSERT INTO llm_spend_prices (budget_id, currency, endpoint_host, model,"
                " input_per_mtok, output_per_mtok, source, source_date, declared_by)"
                " VALUES (%s, 'USD', 'api.example.test', 'm', 0, 0, 'x', %s, 'act:app')",
                (budget, DAY),
            )
        for statement in (
            "UPDATE llm_spend_prices SET output_per_mtok = 0 WHERE budget_id = %s",
            "DELETE FROM llm_spend_prices WHERE budget_id = %s",
        ):
            with pytest.raises(Denied):
                app.execute(statement, (budget,))
    rows = su.execute(
        "SELECT model, output_per_mtok FROM llm_spend_prices WHERE budget_id = %s", (budget,)
    ).fetchall()
    assert rows == [("m", Decimal("15.00000000"))]


def test_a_forged_writer_flag_writes_nothing(su, roles):
    budget = _budget(su, "1")
    _price(su, budget)
    call = spend.new_call_id()
    su.execute(
        "SELECT llm_spend_reserve(%s, %s, 'api.example.test', 'm', 100, 0, 10)", (budget, call)
    )
    before = _state(su, budget)
    forged = (
        ("UPDATE llm_spend_budgets SET charged = 0, ceiling = 999 WHERE budget_id = %s", (budget,)),
        ("DELETE FROM llm_spend_ledger WHERE budget_id = %s", (budget,)),
        ("UPDATE llm_spend_ledger SET amount = 0 WHERE budget_id = %s", (budget,)),
        (
            "INSERT INTO llm_spend_ledger (budget_id, kind, actor_id, reason, charged_after,"
            " ceiling_after) VALUES (%s, 'CEILING', 'act:app', 'forged', 0, 999)",
            (budget,),
        ),
    )
    with roles.connect(roles.app) as app:
        for statement, args in forged:
            with app.transaction():
                app.execute("SELECT set_config('lab_brain.llm_spend_writer', 'on', TRUE)")
                with pytest.raises(Denied), app.transaction():
                    app.execute(statement, args)
    after = _state(su, budget)
    assert (after.charged, after.ceiling) == (before.charged, before.ceiling)
    assert _ledger_count(su, budget) == 1


def test_the_flag_is_not_enough_even_where_table_writes_were_granted_by_mistake(su, roles):
    """Defence in depth: a deployment that granted the app row writes on the spend tables (say,
    by a hand-written GRANT ... ON ALL TABLES after `db-roles`) still cannot write them -- the
    triggers accept a write only from inside the migrator's functions, not from a flag."""
    budget = _budget(su, "1")
    _price(su, budget)
    tables = sql.SQL(", ").join(
        sql.Identifier(t) for t in ("llm_spend_budgets", "llm_spend_prices", "llm_spend_ledger")
    )
    su.execute(
        sql.SQL("GRANT INSERT, UPDATE, DELETE ON {} TO {}").format(
            tables, sql.Identifier(roles.app)
        )
    )
    su.execute(
        sql.SQL("GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO {}").format(
            sql.Identifier(roles.app)
        )
    )
    try:
        with roles.connect(roles.app) as app:
            for statement in (
                "UPDATE llm_spend_budgets SET ceiling = 999 WHERE budget_id = %s",
                "INSERT INTO llm_spend_ledger (budget_id, kind, actor_id, reason, charged_after,"
                " ceiling_after) VALUES (%s, 'CEILING', 'act:app', 'forged', 0, 999)",
                "INSERT INTO llm_spend_prices (budget_id, currency, endpoint_host, model,"
                " input_per_mtok, output_per_mtok, source, source_date, declared_by)"
                " VALUES (%s, 'USD', 'api.example.test', 'm', 0, 0, 'x', '2026-10-28', 'a')",
            ):
                with pytest.raises(psycopg.errors.RaiseException), app.transaction():
                    app.execute("SELECT set_config('lab_brain.llm_spend_writer', 'on', TRUE)")
                    app.execute(statement, (budget,))
    finally:
        grant_database_roles(su, app_role=roles.app, reader_role=roles.reader)
    assert _state(su, budget).ceiling == Decimal(1)


def test_the_app_cannot_call_any_administration_function(su, roles):
    budget = _budget(su)
    calls = (
        ("SELECT llm_spend_set_ceiling(%s, 99, 'act:app', 'x', TRUE)", (budget,)),
        (
            "SELECT llm_spend_declare_budget(%s, 'USD', 99, 'act:app', 1, 4096, 1024)",
            (f"test-adm-{uuid.uuid4().hex[:12]}",),
        ),
        (
            "SELECT llm_spend_declare_price(%s, 'USD', 'api.example.test', 'm', 0, 0, 'x',"
            " '2026-10-28', 'act:app')",
            (budget,),
        ),
        ("SELECT llm_spend_declare_free('127.0.0.1:4000', '*', 'free', 'act:app')", ()),
        ("SELECT llm_spend_revoke_free('127.0.0.1:4000', '*', 'paid', 'act:app')", ()),
    )
    with roles.connect(roles.app) as app:
        for statement, args in calls:
            with pytest.raises(Denied):
                app.execute(statement, args)
    assert _state(su, budget).ceiling == Decimal(10)


def test_the_app_cannot_become_the_administration_role(su, roles):
    with roles.connect(roles.app) as app:
        with pytest.raises(Denied):
            app.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(ADMIN)))
        assert app.execute(
            "SELECT pg_has_role(session_user, %s, 'MEMBER')", (ADMIN,)
        ).fetchone() == (False,)


def test_the_app_cannot_truncate_disable_triggers_or_replicate(su, roles):
    budget = _budget(su)
    with roles.connect(roles.app) as app:
        for table in ("llm_spend_budgets", "llm_spend_prices", "llm_spend_ledger"):
            with pytest.raises(Denied):
                app.execute(sql.SQL("TRUNCATE {} CASCADE").format(sql.Identifier(table)))
            with pytest.raises(Denied):
                app.execute(
                    sql.SQL("ALTER TABLE {} DISABLE TRIGGER ALL").format(sql.Identifier(table))
                )
        with pytest.raises(Denied):
            app.execute("SET session_replication_role = replica")
        with pytest.raises(Denied):
            app.execute(
                "CREATE OR REPLACE FUNCTION llm_spend_writer() RETURNS BOOLEAN"
                " LANGUAGE sql AS 'SELECT TRUE'"
            )
    assert spend.budget_state(su, budget) is not None


# -- what the app does do ---------------------------------------------------------------------------


def test_the_app_reserves_settles_retains_and_reads(su, roles):
    budget = _budget(su)
    _price(su, budget)
    guard = PostgresSpendGuard(roles.dsn(roles.app), budget)

    def request() -> SpendRequest:
        return SpendRequest(spend.new_call_id(), "api.example.test", "m", 1000, 0, 100)

    held = guard.reserve(request())
    assert guard.settle(held, {"prompt_tokens": 10, "completion_tokens": 5}) == "SETTLED"
    kept = guard.reserve(request())
    guard.retain(kept, "timeout")
    with roles.connect(roles.app) as app:
        assert spend.budget_state(app, budget) == _state(su, budget)
        kinds = [
            k
            for (k,) in app.execute(
                "SELECT kind FROM llm_spend_ledger WHERE budget_id = %s ORDER BY entry_id",
                (budget,),
            ).fetchall()
        ]
    assert kinds == ["RESERVATION", "SETTLEMENT", "RESERVATION", "RETAINED"]
    roles_seen = {
        r
        for (r,) in su.execute(
            "SELECT db_role FROM llm_spend_ledger WHERE budget_id = %s", (budget,)
        ).fetchall()
    }
    assert roles_seen == {roles.app}, "every row names the database role that wrote it"


def test_concurrent_reservations_by_the_app_never_pass_the_ceiling(su, roles):
    # One request: input bound 100 + 1024 overhead = 1124 x 2.5/M, plus 1000 x 15/M = 0.01781.
    budget = _budget(su, "0.1")
    _price(su, budget)
    granted: list[Decimal] = []
    refused: list[str] = []
    lock = threading.Lock()
    start = threading.Barrier(16)

    def one() -> None:
        guard = PostgresSpendGuard(roles.dsn(roles.app), budget)
        start.wait()
        try:
            held = guard.reserve(
                SpendRequest(spend.new_call_id(), "api.example.test", "m", 100, 0, 1000)
            )
        except spend.SpendRefused as no:
            with lock:
                refused.append(str(no))
        else:
            with lock:
                granted.append(held.worst_case)

    threads = [threading.Thread(target=one) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(granted) == 5 and len(refused) == 11
    assert sum(granted) <= Decimal("0.1") and _state(su, budget).charged == sum(granted)


# -- the Owner's role does its job ----------------------------------------------------------------


def test_the_spend_administrator_declares_changes_and_closes(su, roles):
    budget = f"test-adm-{uuid.uuid4().hex[:12]}"
    with roles.connect(roles.owner) as owner:
        spend.declare_budget(
            owner, budget, currency="USD", ceiling=Decimal("1"), actor_id="act:owner"
        )
        _price(owner, budget)
        spend.set_ceiling(owner, budget, Decimal("2"), actor_id="act:owner", reason="raised")
    _open_circuit(su, budget)
    charged = _state(su, budget).charged
    with roles.connect(roles.owner) as owner:
        spend.set_ceiling(
            owner, budget, charged + 1, actor_id="act:owner", reason="reviewed", close_circuit=True
        )
    state = _state(su, budget)
    assert not state.circuit_open and state.ceiling == charged + 1
    assert su.execute(
        "SELECT db_role FROM llm_spend_budgets WHERE budget_id = %s", (budget,)
    ).fetchone() == (roles.owner,)


def test_db_roles_refuses_an_app_role_that_administers_spend(su, roles):
    su.execute(sql.SQL("GRANT {} TO {}").format(sql.Identifier(ADMIN), sql.Identifier(roles.app)))
    with pytest.raises(OperatorRefused, match="spend"):
        grant_database_roles(su, app_role=roles.app, reader_role=roles.reader)
    su.execute(
        sql.SQL("REVOKE {} FROM {}").format(sql.Identifier(ADMIN), sql.Identifier(roles.app))
    )
    first = grant_database_roles(su, app_role=roles.app, reader_role=roles.reader)
    assert grant_database_roles(su, app_role=roles.app, reader_role=roles.reader) == first


# -- a local proxy is metered unless the Owner declares it free ------------------------------------


@pytest.fixture
def fake() -> Iterator[FakeProvider]:
    provider = FakeProvider(api_key=KEY).start()
    yield provider
    provider.stop()


def test_a_local_proxy_is_metered_unless_the_owner_declares_it_free(su, roles, fake, monkeypatch):
    for name in ("LAB_BRAIN_LLM_SPEND_BUDGET", "LAB_BRAIN_LLM_SPEND_METER_LOCAL"):
        monkeypatch.delenv(name, raising=False)
    spend.install(None)
    host = f"127.0.0.1:{fake.port}"
    budget = _budget(su)  # a ceiling, and no price for anything on this machine
    guard = PostgresSpendGuard(roles.dsn(roles.app), budget)  # as the product's env guard is
    client = OpenAICompatibleClient(fake.base_url, KEY, spend=guard)
    with pytest.raises(ProviderError) as refused:
        client.chat("fake-reasoner", "a prompt for a local proxy")
    assert refused.value.failure.value == "SPEND_REFUSED" and fake.calls == []
    # The app cannot declare its own endpoint free.
    with roles.connect(roles.app) as app, pytest.raises(Denied):
        spend.declare_free_endpoint(app, host, "*", reason="it is free", actor_id="act:app")
    # The Owner can: genuinely free (a local model server, not a proxy), with a reason.
    with roles.connect(roles.owner) as owner:
        spend.declare_free_endpoint(
            owner, host, "fake-reasoner", reason="the test's fake provider", actor_id="act:owner"
        )
    client.chat("fake-reasoner", "a prompt for a free local model")
    assert len(fake.calls) == 1 and _ledger_count(su, budget) == 0
    with pytest.raises(ProviderError):
        client.chat("fake-critic", "another model on it is not declared")
    assert len(fake.calls) == 1
    with roles.connect(roles.owner) as owner:
        spend.revoke_free_endpoint(
            owner, host, "fake-reasoner", reason="it forwards now", actor_id="act:owner"
        )
    with pytest.raises(ProviderError):
        client.chat("fake-reasoner", "revoked: metered again")
    assert len(fake.calls) == 1


def test_the_live_evaluation_meters_an_undeclared_local_critic(su, roles, fake, monkeypatch):
    """The live guard as the live test installs it (an external primary priced), with a local
    critic: refused unsent until the Owner declares that endpoint free -- and the declaration made
    with the services' role is refused."""
    monkeypatch.delenv("LAB_BRAIN_LLM_SPEND_BUDGET", raising=False)
    host = f"127.0.0.1:{fake.port}"
    declared = spend_from_env(
        external=True,
        env={
            "LAB_BRAIN_LIVE_SPEND_BUDGET": f"live-{uuid.uuid4().hex[:12]}",
            "LAB_BRAIN_LIVE_SPEND_CEILING": "5",
            "LAB_BRAIN_LIVE_SPEND_CURRENCY": "USD",
            "LAB_BRAIN_LIVE_PRICE_INPUT_PER_MTOK": "2.5",
            "LAB_BRAIN_LIVE_PRICE_OUTPUT_PER_MTOK": "15",
            "LAB_BRAIN_LIVE_PRICE_SOURCE": "test fixture price",
            "LAB_BRAIN_LIVE_PRICE_DATE": "2026-10-28",
        },
    )
    assert declared is not None
    free = {
        "LAB_BRAIN_LIVE_FREE_ENDPOINTS": f"{host} fake-critic",
        "LAB_BRAIN_LIVE_FREE_REASON": "the test's fake provider, a model server on this machine",
    }
    with pytest.raises(Denied):  # the services' role cannot set up the evaluation's money
        install_live_spend_guard(
            roles.dsn(roles.app), declared, endpoint_host="models.provider.test",
            model="primary", actor_id="act:app", env=free,
        )  # fmt: skip
    try:
        install_live_spend_guard(
            database_url(), declared, endpoint_host="models.provider.test", model="primary",
            actor_id="act:owner", env={},
        )  # fmt: skip
        with pytest.raises(ProviderError) as refused:
            OpenAICompatibleClient(fake.base_url, KEY).chat("fake-critic", "local critic")
        assert refused.value.failure.value == "SPEND_REFUSED" and fake.calls == []
        spend.install(None)
        declared = replace(declared, budget_id=f"live-{uuid.uuid4().hex[:12]}")
        install_live_spend_guard(
            database_url(), declared, endpoint_host="models.provider.test", model="primary",
            actor_id="act:owner", env=free,
        )  # fmt: skip
        OpenAICompatibleClient(fake.base_url, KEY).chat("fake-critic", "local critic")
        assert len(fake.calls) == 1
        with pytest.raises(ProviderError):
            OpenAICompatibleClient(fake.base_url, KEY).chat("fake-reasoner", "not declared")
        assert len(fake.calls) == 1
    finally:
        spend.install(None)
        spend.revoke_free_endpoint(su, host, "fake-critic", reason="test over", actor_id="act:o")


def test_a_local_only_evaluation_needs_its_endpoints_declared_free(su, fake, monkeypatch):
    monkeypatch.delenv("LAB_BRAIN_LLM_SPEND_BUDGET", raising=False)
    with pytest.raises(LiveBudgetMissing, match="LAB_BRAIN_LIVE_FREE_ENDPOINTS"):
        install_local_free_guard(database_url(), actor_id="act:owner", env={})
    host = f"127.0.0.1:{fake.port}"
    try:
        install_local_free_guard(
            database_url(),
            actor_id="act:owner",
            env={
                "LAB_BRAIN_LIVE_FREE_ENDPOINTS": f"{host} *",
                "LAB_BRAIN_LIVE_FREE_REASON": "the test's fake provider",
            },
        )
        OpenAICompatibleClient(fake.base_url, KEY).chat("fake-reasoner", "free")
        assert len(fake.calls) == 1
        with pytest.raises(ProviderError) as refused:
            OpenAICompatibleClient("http://localhost:1/v1", KEY).chat("m", "undeclared proxy")
        assert "no spend ceiling is configured" in str(refused.value)
    finally:
        spend.install(None)
        spend.revoke_free_endpoint(su, host, "*", reason="test over", actor_id="act:o")
