"""The product's spend policy at the transport (011t): fail closed, and the Owner's free endpoints.

No database: the guards are in-memory stand-ins, or the PostgreSQL guard with its connection
replaced, and urllib's opener records what would have been sent. The real boundaries (who may
declare what) are in `tests/integration/test_g0_spend_admin_postgres.py`.

    remote       no guard, whatever the environment says: refused before anything is sent
    free         an endpoint the guard says the Owner declared free is sent unreserved; any other
                 model on it is reserved
    no budget    a guard with no ceiling refuses whatever is not declared free
    this machine a configured budget meters it; with no budget it is sent unmetered unless the
                 Owner sets LAB_BRAIN_LLM_SPEND_METER_LOCAL (the documented residual)
"""

from __future__ import annotations

import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import pytest

from lab_brain.evaluation.live_budget import LiveBudgetMissing, free_endpoints_from_env
from lab_brain.llm_runtime import spend
from lab_brain.llm_runtime.provider import OpenAICompatibleClient, ProviderError, ProviderFailure
from lab_brain.llm_runtime.spend import PostgresSpendGuard, Reservation, SpendRequest
from tests.transport_endpoints import Endpoint

KEY = "sk-test-spend-policy-0123456789abcdefABCDEF"
REMOTE = "https://models.provider.invalid/v1"


@dataclass
class Guard:
    free: set[tuple[str, str]] = field(default_factory=set)
    meter_this_machine: bool = True
    reserved: list[SpendRequest] = field(default_factory=list)

    def declared_free(self, endpoint_host: str, model: str) -> bool:
        return (endpoint_host, model) in self.free or (endpoint_host, "*") in self.free

    def reserve(self, request: SpendRequest) -> Reservation:
        self.reserved.append(request)
        return Reservation(request.call_id, "test", Decimal("0.01"))

    def settle(self, reservation: Reservation, usage: Mapping[str, int] | None) -> str:
        return "SETTLED"

    def retain(self, reservation: Reservation, reason: str) -> None:
        return None


class _Reply:
    def __enter__(self) -> _Reply:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self) -> bytes:
        return b'{"choices": [{"message": {"content": "ok"}}]}'


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []

    def record(self: object, request: urllib.request.Request, *a: object, **k: object) -> _Reply:
        seen.append(request.full_url)
        return _Reply()

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", record)
    return seen


@pytest.fixture(autouse=True)
def _no_ambient_policy(monkeypatch: pytest.MonkeyPatch) -> Any:
    for name in (
        "LAB_BRAIN_LLM_SPEND_BUDGET",
        "LAB_BRAIN_LLM_SPEND_REQUIRED",
        "LAB_BRAIN_LLM_SPEND_METER_LOCAL",
        "LAB_BRAIN_LLM_SPEND_DSN",
        "LAB_BRAIN_DATABASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    spend.install(None)
    yield
    spend.install(None)


@pytest.mark.parametrize("flag", [None, "0", "1"])
def test_a_remote_request_without_a_guard_is_refused_whatever_the_flag(
    flag: str | None, sent: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    if flag is not None:
        monkeypatch.setenv("LAB_BRAIN_LLM_SPEND_REQUIRED", flag)
    with pytest.raises(ProviderError) as refused:
        OpenAICompatibleClient(REMOTE, KEY).chat("m", "EVIDENCE-POLICY-1")
    assert refused.value.failure is ProviderFailure.SPEND_REFUSED and sent == []
    assert "EVIDENCE-POLICY-1" not in str(refused.value) and KEY not in str(refused.value)


def test_an_endpoint_the_owner_declared_free_is_sent_unreserved(sent: list[str]) -> None:
    guard = Guard(free={("models.provider.invalid", "free-model")})
    client = OpenAICompatibleClient(REMOTE, KEY, spend=guard)
    client.chat("free-model", "prompt")
    assert len(sent) == 1 and guard.reserved == []
    client.chat("paid-model", "prompt")
    assert len(sent) == 2 and [r.model for r in guard.reserved] == ["paid-model"]


def test_a_guard_with_no_budget_refuses_what_is_not_declared_free(sent: list[str]) -> None:
    asked: list[tuple[str, tuple[object, ...]]] = []

    class Row:
        def __init__(self, value: object) -> None:
            self._value = value

        def fetchone(self) -> tuple[object]:
            return (self._value,)

    class Connection:
        def execute(self, statement: str, args: tuple[object, ...]) -> Row:
            asked.append((statement, args))
            return Row(args == ("models.provider.invalid", "declared"))

        def close(self) -> None:
            return None

    guard = PostgresSpendGuard("postgresql://unused", None, connect=lambda dsn: Connection())
    client = OpenAICompatibleClient(REMOTE, KEY, spend=guard)
    client.chat("declared", "prompt")
    with pytest.raises(ProviderError) as refused:
        client.chat("undeclared", "prompt")
    assert refused.value.failure is ProviderFailure.SPEND_REFUSED
    assert "no spend ceiling is configured" in refused.value.detail
    assert len(sent) == 1
    assert all("llm_spend_endpoint_is_free" in statement for statement, _ in asked)


def test_which_guard_the_environment_gives() -> None:
    assert spend.resolve(None, env={}) is None
    with_budget = spend.resolve(
        None, env={"LAB_BRAIN_LLM_SPEND_BUDGET": "b", "LAB_BRAIN_DATABASE_URL": "postgresql://x"}
    )
    assert isinstance(with_budget, PostgresSpendGuard) and with_budget.meter_this_machine
    declarations = spend.resolve(None, env={"LAB_BRAIN_DATABASE_URL": "postgresql://x"})
    assert isinstance(declarations, PostgresSpendGuard) and declarations.budget_id is None
    assert not declarations.meter_this_machine
    strict = spend.resolve(
        None,
        env={"LAB_BRAIN_DATABASE_URL": "postgresql://x", "LAB_BRAIN_LLM_SPEND_METER_LOCAL": "1"},
    )
    assert strict is not None and strict.meter_this_machine
    assert spend.required({}) is True


def test_a_budget_meters_this_machine() -> None:
    endpoint = Endpoint().start()
    try:
        guard = Guard()
        OpenAICompatibleClient(endpoint.origin + "/v1", KEY, spend=guard).chat("m", "prompt")
        assert len(guard.reserved) == 1 and len(endpoint.seen) == 1
        guard.free.add((guard.reserved[0].endpoint_host, "*"))
        OpenAICompatibleClient(endpoint.origin + "/v1", KEY, spend=guard).chat("m", "prompt")
        assert len(guard.reserved) == 1 and len(endpoint.seen) == 2, "declared free"
    finally:
        endpoint.stop()


def test_with_no_ceiling_at_all_this_machine_is_the_documented_residual() -> None:
    """No budget, no database, no METER_LOCAL: a loopback request is sent unmetered. A local
    proxy to a paid provider would be too -- the residual spend-administration.md names; the
    Owner closes it by configuring a ceiling or LAB_BRAIN_LLM_SPEND_METER_LOCAL=1."""
    endpoint = Endpoint().start()
    try:
        OpenAICompatibleClient(endpoint.origin + "/v1", KEY).chat("m", "prompt")
        assert len(endpoint.seen) == 1
    finally:
        endpoint.stop()


def test_the_live_free_endpoints_are_parsed_and_need_a_reason() -> None:
    assert free_endpoints_from_env({}) == ((), "")
    free, reason = free_endpoints_from_env(
        {
            "LAB_BRAIN_LIVE_FREE_ENDPOINTS": "127.0.0.1:11434 qwen2.5:7b; LOCALHOST:8080 *",
            "LAB_BRAIN_LIVE_FREE_REASON": "Ollama on this machine",
        }
    )
    assert [(f.endpoint_host, f.model) for f in free] == [
        ("127.0.0.1:11434", "qwen2.5:7b"),
        ("localhost:8080", "*"),
    ]
    assert reason == "Ollama on this machine"
    with pytest.raises(LiveBudgetMissing, match="REASON"):
        free_endpoints_from_env({"LAB_BRAIN_LIVE_FREE_ENDPOINTS": "127.0.0.1:11434 *"})
    with pytest.raises(LiveBudgetMissing, match="host"):
        free_endpoints_from_env(
            {"LAB_BRAIN_LIVE_FREE_ENDPOINTS": "127.0.0.1:11434", "LAB_BRAIN_LIVE_FREE_REASON": "x"}
        )
