"""The monetary ceiling against real PostgreSQL (migration 011r) and real HTTP: fail closed.

Each test declares its own budget (a fresh id) and drives the real `OpenAICompatibleClient` through
the real `PostgresSpendGuard` against a local endpoint -- the repository's fake provider, or a
recording endpoint -- or, for a REMOTE host, against urllib's opener replaced by a local stand-in,
so no request ever leaves this machine. The fake provider is on 127.0.0.1, so the guard says
`meter_this_machine` (as an Owner metering a local proxy would); the live evaluation's guard does
not, and meters only remote hosts.

    refused unsent   no budget, no price, not enough left, an open circuit: the provider receives
                     nothing
    formula          the database's worst case is the stated formula; settlement is the reported
                     usage at the declared price
    concurrency      N threads, each on its own connection, never reserve past the ceiling
    endings          missing usage and a timeout keep the worst case; an overrun opens the circuit
                     and every later request is refused until the Owner closes it
    every path       probes are reserved (the span-based meter saw none of them); the schema
                     fallback is two reservations; the model list is not metered
    append-only      the ledger, the prices and the budget's money refuse direct writes
"""

from __future__ import annotations

import datetime as dt
import json
import threading
import urllib.request
import uuid
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from lab_brain.evaluation.live_budget import (
    LiveBudgetExhausted,
    LiveCap,
    check_spend_before_episode,
    install_live_spend_guard,
    spend_from_env,
    spent,
)
from lab_brain.llm_runtime import spend
from lab_brain.llm_runtime.capabilities import Capability
from lab_brain.llm_runtime.probes import run_probe
from lab_brain.llm_runtime.provider import OpenAICompatibleClient, ProviderError
from lab_brain.llm_runtime.spend import PostgresSpendGuard, SpendRefused, SpendRequest
from tests.fake_llm_provider import FakeProvider
from tests.postgres_fixtures import database_url
from tests.transport_endpoints import Endpoint

pytestmark = pytest.mark.postgres

KEY = "sk-test-spend-ledger-0123456789abcdefABCDEF"
PROMPT = "EVIDENCE-SPEND-77 pad P4 read 41 ohm"
IN, OUT = Decimal("2.5"), Decimal("15")


@pytest.fixture
def pg(postgres_connection: Any) -> Any:
    return postgres_connection


@pytest.fixture(autouse=True)
def _no_ambient_guard(monkeypatch: pytest.MonkeyPatch) -> Any:
    for name in ("LAB_BRAIN_LLM_SPEND_BUDGET", "LAB_BRAIN_LLM_SPEND_REQUIRED"):
        monkeypatch.delenv(name, raising=False)
    spend.install(None)
    yield
    spend.install(None)


def _budget(pg: Any, ceiling: str = "10", **options: Any) -> str:
    budget = f"test-{uuid.uuid4().hex[:16]}"
    spend.declare_budget(
        pg, budget, currency="USD", ceiling=Decimal(ceiling), actor_id="act:owner", **options
    )
    return budget


def _price(pg: Any, budget: str, host: str, model: str) -> None:
    spend.declare_price(
        pg,
        budget,
        endpoint_host=host,
        model=model,
        currency="USD",
        input_per_mtok=IN,
        output_per_mtok=OUT,
        source="test fixture price, not a real provider's",
        source_date=dt.date(2026, 10, 28),
        actor_id="act:owner",
    )


def _host(port: int) -> str:
    return f"127.0.0.1:{port}"


def _ledger(pg: Any, budget: str) -> list[dict[str, Any]]:
    cursor = pg.execute(
        "SELECT * FROM llm_spend_ledger WHERE budget_id = %s ORDER BY entry_id", (budget,)
    )
    names = [c.name for c in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _state(pg: Any, budget: str) -> spend.BudgetState:
    state = spend.budget_state(pg, budget)
    assert state is not None
    return state


@pytest.fixture
def fake() -> Any:
    provider = FakeProvider(api_key=KEY).start()
    yield provider
    provider.stop()


def _client(provider: Any, budget: str, **options: Any) -> OpenAICompatibleClient:
    guard = PostgresSpendGuard(database_url(), budget, meter_this_machine=True)
    return OpenAICompatibleClient(provider.base_url, KEY, spend=guard, **options)


# -- refused before anything is sent ---------------------------------------------------------------


def test_no_budget_or_no_price_is_refused_before_send(pg, fake):
    with pytest.raises(ProviderError) as refused:
        _client(fake, "test-never-declared").chat("fake-reasoner", PROMPT)
    assert refused.value.failure.value == "SPEND_REFUSED" and "no spend budget" in str(
        refused.value
    )
    budget = _budget(pg)
    with pytest.raises(ProviderError) as refused:
        _client(fake, budget).chat("fake-reasoner", PROMPT)
    assert "no price is declared" in str(refused.value)
    _price(pg, budget, _host(fake.port), "fake-critic")  # another model's price does not count
    with pytest.raises(ProviderError):
        _client(fake, budget).chat("fake-reasoner", PROMPT)
    assert fake.calls == [], "the provider received nothing"
    assert _ledger(pg, budget) == [] and _state(pg, budget).charged == 0
    assert PROMPT not in str(refused.value) and KEY not in str(refused.value)


def test_a_request_that_could_pass_the_ceiling_is_refused_before_send(pg, fake):
    budget = _budget(pg, ceiling="0.01")  # 16384 output tokens at 15/M alone is 0.24576
    _price(pg, budget, _host(fake.port), "fake-reasoner")
    with pytest.raises(ProviderError) as refused:
        _client(fake, budget).chat("fake-reasoner", PROMPT)
    assert "may cost up to" in str(refused.value)
    assert fake.calls == []


# -- the formula, and settlement -------------------------------------------------------------------


def test_the_database_worst_case_is_the_formula_and_settlement_is_the_reported_usage(pg, fake):
    budget = _budget(
        pg,
        safety_multiplier=Decimal("1.5"),
        image_allowance_tokens=1000,
        request_overhead_tokens=100,
    )
    _price(pg, budget, _host(fake.port), "fake-reasoner")
    client = _client(fake, budget, max_output_tokens=500)
    client.chat("fake-reasoner", "Reply with exactly one word: pong", image_png=b"\x89PNG")
    reservation, settlement = _ledger(pg, budget)
    bound, worst = spend.worst_case_cost(
        body_bytes=reservation["body_bytes"],
        image_count=1,
        max_output_tokens=500,
        input_per_mtok=IN,
        output_per_mtok=OUT,
        safety_multiplier=Decimal("1.5"),
        image_allowance_tokens=1000,
        request_overhead_tokens=100,
    )
    assert reservation["kind"] == "RESERVATION" and reservation["image_count"] == 1
    assert reservation["input_bound_tokens"] == bound and reservation["worst_case"] == worst
    assert reservation["max_output_tokens"] == 500
    assert settlement["kind"] == "SETTLEMENT"
    prompt, completion = settlement["prompt_tokens"], settlement["completion_tokens"]
    actual = (prompt * IN + completion * OUT) * Decimal("0.000001")
    assert settlement["amount"] == actual and _state(pg, budget).charged == actual
    # Nothing of the prompt or the credential is in the ledger.
    text = json.dumps(_ledger(pg, budget), default=str)
    assert KEY not in text and "pong" not in text


def test_hidden_output_tokens_in_the_total_are_billed_as_output(pg):
    budget = _budget(pg)
    _price(pg, budget, "provider.test", "m")
    guard = PostgresSpendGuard(database_url(), budget)
    held = guard.reserve(SpendRequest(spend.new_call_id(), "provider.test", "m", 2000, 0, 4000))
    assert guard.settle(held, {"prompt_tokens": 100, "completion_tokens": 10,
                               "total_tokens": 1110}) == "SETTLED"  # fmt: skip
    charged = _state(pg, budget).charged
    assert charged == (100 * IN + 1010 * OUT) * Decimal("0.000001")


# -- concurrency -----------------------------------------------------------------------------------


def test_concurrent_reservations_never_pass_the_ceiling(pg):
    budget = _budget(pg, ceiling="1")
    _price(pg, budget, "provider.test", "m")
    request_cost = spend.worst_case_cost(
        body_bytes=10_000, image_count=0, max_output_tokens=10_000, input_per_mtok=IN,
        output_per_mtok=OUT,
    )[1]  # fmt: skip
    fits = int(Decimal(1) / request_cost)
    guard = PostgresSpendGuard(database_url(), budget)
    outcomes: list[str] = []
    reasons: list[str] = []
    gate = threading.Barrier(24)

    def race() -> None:
        gate.wait()
        for _ in range(3):
            try:
                guard.reserve(
                    SpendRequest(spend.new_call_id(), "provider.test", "m", 10_000, 0, 10_000)
                )
                outcomes.append("reserved")
            except SpendRefused as refused:
                outcomes.append("refused")
                reasons.append(str(refused))

    threads = [threading.Thread(target=race) for _ in range(24)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert outcomes.count("reserved") == fits < len(outcomes)
    # Every refusal is the ceiling's own, decided under the budget row's lock -- never the table's
    # CHECK firing as a backstop after two reservations both read the same charge.
    assert reasons and all("may cost up to" in r for r in reasons), sorted(set(reasons))[:3]
    state = _state(pg, budget)
    assert state.charged == fits * request_cost <= state.ceiling
    rows = _ledger(pg, budget)
    assert sum(r["worst_case"] for r in rows) == state.charged
    assert max(r["charged_after"] for r in rows) <= state.ceiling


# -- endings ---------------------------------------------------------------------------------------


def test_missing_usage_keeps_the_worst_case(pg):
    endpoint = Endpoint().start()  # answers without `usage`
    try:
        budget = _budget(pg)
        _price(pg, budget, _host(endpoint.port), "m")
        guard = PostgresSpendGuard(database_url(), budget, meter_this_machine=True)
        OpenAICompatibleClient(endpoint.origin + "/v1", KEY, spend=guard).chat("m", PROMPT)
    finally:
        endpoint.stop()
    reservation, ending = _ledger(pg, budget)
    assert ending["kind"] == "RETAINED" and ending["amount"] == reservation["worst_case"]
    assert _state(pg, budget).charged == reservation["worst_case"]


def test_a_timeout_keeps_the_worst_case(pg):
    slow = FakeProvider(api_key=KEY, delay=lambda prompt, system: 3.0).start()
    try:
        budget = _budget(pg)
        _price(pg, budget, _host(slow.port), "fake-reasoner")
        with pytest.raises(ProviderError) as failed:
            _client(slow, budget, timeout=1.0).chat("fake-reasoner", PROMPT)
    finally:
        slow.stop()
    assert failed.value.failure.value == "TIMEOUT"
    reservation, ending = _ledger(pg, budget)
    assert ending["kind"] == "RETAINED" and "TimeoutError" in ending["reason"]
    assert _state(pg, budget).charged == reservation["worst_case"]


def test_an_overrun_halts_every_further_call_until_the_owner_closes_it(pg):
    # The provider ignores max_tokens: five output tokens against a bound of two.
    chatty = FakeProvider(api_key=KEY, rewrite=lambda prompt, answer: "a b c d e").start()
    try:
        budget = _budget(pg)
        _price(pg, budget, _host(chatty.port), "fake-reasoner")
        client = _client(chatty, budget, max_output_tokens=2)
        client.chat("fake-reasoner", PROMPT)  # received, and paid for
        state = _state(pg, budget)
        assert state.circuit_open
        assert _ledger(pg, budget)[-1]["kind"] == "OVERRUN"
        with pytest.raises(ProviderError) as halted:
            client.chat("fake-reasoner", PROMPT)
        assert "halted after an overrun" in str(halted.value)
        assert len(chatty.calls) == 1, "nothing more was sent"
        with pytest.raises(LiveBudgetExhausted):
            check_spend_before_episode(pg, budget)
        with pytest.raises(psycopg.errors.CheckViolation):  # below what is charged
            spend.set_ceiling(
                pg, budget, state.charged / 2, actor_id="act:owner", reason="r", close_circuit=True
            )
        spend.set_ceiling(
            pg, budget, Decimal(10), actor_id="act:owner", reason="reviewed", close_circuit=True
        )
        _client(chatty, budget, max_output_tokens=50).chat("fake-reasoner", PROMPT)
        assert len(chatty.calls) == 2 and not _state(pg, budget).circuit_open
    finally:
        chatty.stop()


# -- every billable path ---------------------------------------------------------------------------


def test_the_schema_fallback_reserves_twice(pg):
    refusing = FakeProvider(api_key=KEY, refuse_schema=True).start()
    try:
        budget = _budget(pg)
        _price(pg, budget, _host(refusing.port), "fake-reasoner")
        _client(refusing, budget).chat(
            "fake-reasoner",
            "Return exactly this JSON object",
            response_schema=("s", {"type": "object"}),
        )
    finally:
        refusing.stop()
    kinds = [r["kind"] for r in _ledger(pg, budget)]
    assert kinds == ["RESERVATION", "RETAINED", "RESERVATION", "SETTLEMENT"]


def test_probes_are_reserved_though_the_span_meter_never_saw_them(pg, fake):
    """The demonstrated gap: qualification probes write no LLM_CALL span, so the evaluation's
    call/token meter counted none of them. The spend ledger counts every one."""
    budget = _budget(pg)
    _price(pg, budget, _host(fake.port), "fake-reasoner")
    with spend.installed(PostgresSpendGuard(database_url(), budget, meter_this_machine=True)):
        client = OpenAICompatibleClient(fake.base_url, KEY)  # built without a guard: installed
        client.list_models()
        for capability in (Capability.CHAT, Capability.STRUCTURED_JSON, Capability.VISION):
            run_probe(client, "fake-reasoner", capability)
    assert spent(pg, "fake-reasoner", LiveCap(max_calls=10, max_tokens=10)) == (0, 0)
    reservations = [r for r in _ledger(pg, budget) if r["kind"] == "RESERVATION"]
    assert len(reservations) == len(fake.calls) == 3, "the model list is not; each probe is"


def test_this_machine_is_not_charged_by_the_live_guard(pg, fake):
    budget = _budget(pg)
    _price(pg, budget, _host(fake.port), "fake-reasoner")
    guard = PostgresSpendGuard(database_url(), budget)  # meter_this_machine False
    OpenAICompatibleClient(fake.base_url, KEY, spend=guard).chat("fake-reasoner", PROMPT)
    assert len(fake.calls) == 1 and _ledger(pg, budget) == []


def test_the_live_evaluation_guard_meters_the_priced_remote_and_refuses_the_rest(
    pg, monkeypatch: pytest.MonkeyPatch
):
    """`install_live_spend_guard` as the live test calls it, with urllib's opener replaced by a
    local stand-in: no request leaves the machine."""
    budget = f"live-{uuid.uuid4().hex[:12]}"
    declared = spend_from_env(
        external=True,
        env={
            "LAB_BRAIN_LIVE_SPEND_BUDGET": budget,
            "LAB_BRAIN_LIVE_SPEND_CEILING": "5",
            "LAB_BRAIN_LIVE_SPEND_CURRENCY": "USD",
            "LAB_BRAIN_LIVE_PRICE_INPUT_PER_MTOK": "2.5",
            "LAB_BRAIN_LIVE_PRICE_OUTPUT_PER_MTOK": "15",
            "LAB_BRAIN_LIVE_PRICE_SOURCE": "test fixture price",
            "LAB_BRAIN_LIVE_PRICE_DATE": "2026-10-28",
        },
    )
    assert declared is not None
    sent: list[str] = []

    class Reply:
        def __enter__(self) -> Reply:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(
                {
                    "choices": [{"message": {"content": "ok"}}],
                    "usage": {"prompt_tokens": 20, "completion_tokens": 1, "total_tokens": 21},
                }
            ).encode()

    def opened(self: object, request: urllib.request.Request, *a: object, **k: object) -> Reply:
        sent.append(request.full_url)
        return Reply()

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", opened)
    install_live_spend_guard(
        database_url(), declared, endpoint_host="models.provider.test", model="primary",
        actor_id="act:owner",
    )  # fmt: skip
    try:
        OpenAICompatibleClient("https://models.provider.test/v1", KEY).chat("primary", PROMPT)
        for url, model in (
            ("https://models.provider.test/v1", "unpriced-critic"),
            ("https://elsewhere.provider.test/v1", "primary"),
        ):
            with pytest.raises(ProviderError):
                OpenAICompatibleClient(url, KEY).chat(model, PROMPT)
        # No guard at all, with the ceiling required by the deployment: refused unsent.
        spend.install(None)
        monkeypatch.setenv("LAB_BRAIN_LLM_SPEND_REQUIRED", "1")
        with pytest.raises(ProviderError) as unguarded:
            OpenAICompatibleClient("https://models.provider.test/v1", KEY).chat("primary", PROMPT)
        assert "no spend ceiling is configured" in str(unguarded.value)
    finally:
        spend.install(None)
    assert sent == ["https://models.provider.test/v1/chat/completions"]
    assert [r["kind"] for r in _ledger(pg, budget)] == ["RESERVATION", "SETTLEMENT"]
    check_spend_before_episode(pg, budget)


# -- append-only -----------------------------------------------------------------------------------


def test_the_ledger_prices_and_budget_money_refuse_direct_writes(pg, fake):
    budget = _budget(pg)
    _price(pg, budget, _host(fake.port), "fake-reasoner")
    _client(fake, budget).chat("fake-reasoner", "Reply with exactly one word: pong")
    refused = (
        "UPDATE llm_spend_ledger SET amount = 0 WHERE budget_id = %s",
        "DELETE FROM llm_spend_ledger WHERE budget_id = %s",
        "INSERT INTO llm_spend_ledger (budget_id, kind, charged_after, ceiling_after, actor_id,"
        " reason) VALUES (%s, 'CEILING', 0, 1, 'a', 'b')",
        "UPDATE llm_spend_budgets SET charged = 0 WHERE budget_id = %s",
        "UPDATE llm_spend_budgets SET ceiling = 1000 WHERE budget_id = %s",
        "UPDATE llm_spend_budgets SET safety_multiplier = 1 WHERE budget_id = %s",
        "DELETE FROM llm_spend_budgets WHERE budget_id = %s",
        "UPDATE llm_spend_prices SET output_per_mtok = 0 WHERE budget_id = %s",
        "DELETE FROM llm_spend_prices WHERE budget_id = %s",
    )
    before = _ledger(pg, budget)
    for sql in refused:
        with pytest.raises(psycopg.errors.RaiseException):
            pg.execute(sql, (budget,))
    with pytest.raises(psycopg.errors.RaiseException):  # a budget cannot start charged
        pg.execute(
            "INSERT INTO llm_spend_budgets (budget_id, currency, ceiling, charged, declared_by)"
            " VALUES ('test-precharged', 'USD', 1, 0.5, 'a')"
        )
    assert _ledger(pg, budget) == before


def test_the_database_refuses_a_reservation_without_max_tokens_or_a_size(pg):
    """The SQL function's own refusals, for a caller that is not this client."""
    budget = _budget(pg, ceiling="1")
    _price(pg, budget, "provider.test", "m")
    for body, images, max_output, why in (
        (10_000, 0, None, "no max_tokens"),
        (10_000, 0, 0, "no max_tokens"),
        (None, 0, 100, "size is not known"),
        (10_000, -1, 100, "size is not known"),
    ):
        with pytest.raises(Exception, match=why):
            pg.execute(
                "SELECT llm_spend_reserve(%s, %s, %s, %s, %s, %s, %s)",
                (budget, spend.new_call_id(), "provider.test", "m", body, images, max_output),
            )
    assert _state(pg, budget).charged == 0


def test_a_reservation_waits_for_an_open_one_and_reads_its_charge(pg):
    """Deterministic: B starts while A's reservation is uncommitted. Under the budget row's lock
    B waits, then reads A's charge and is refused by the ceiling itself. Without the lock B would
    read the old charge, decide it fits, and be stopped only by the table's CHECK."""
    import psycopg

    budget = _budget(pg, ceiling="1")
    _price(pg, budget, "provider.test", "m")
    body, out = 10_000, 10_000
    cost = spend.worst_case_cost(
        body_bytes=body, image_count=0, max_output_tokens=out, input_per_mtok=IN,
        output_per_mtok=OUT,
    )[1]  # fmt: skip
    # Leave room for exactly one more request after A's.
    fits = int(Decimal(1) / cost)
    for _ in range(fits - 1):
        PostgresSpendGuard(database_url(), budget).reserve(
            SpendRequest(spend.new_call_id(), "provider.test", "m", body, 0, out)
        )
    holder = psycopg.connect(database_url())  # A: an open transaction
    holder.execute(
        "SELECT llm_spend_reserve(%s, %s, %s, %s, %s, %s, %s)",
        (budget, spend.new_call_id(), "provider.test", "m", body, 0, out),
    )
    outcome: list[str] = []

    def second() -> None:
        try:
            PostgresSpendGuard(database_url(), budget).reserve(
                SpendRequest(spend.new_call_id(), "provider.test", "m", body, 0, out)
            )
            outcome.append("reserved")
        except SpendRefused as refused:
            outcome.append(str(refused))

    waiter = threading.Thread(target=second)
    waiter.start()
    waiter.join(timeout=2)
    assert waiter.is_alive(), "B must wait for A's reservation, not read past it"
    holder.commit()
    holder.close()
    waiter.join(timeout=30)
    assert len(outcome) == 1 and "may cost up to" in outcome[0], outcome
    assert _state(pg, budget).charged == fits * cost
