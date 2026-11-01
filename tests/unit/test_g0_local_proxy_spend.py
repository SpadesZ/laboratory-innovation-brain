"""A model server on this machine is not presumed free (011v).

Before 011v a request to this machine went out unmetered whenever no spend ceiling was configured:
with no guard at all, and with a database but no budget. A LiteLLM-style proxy on localhost that
forwards to a paid provider was therefore an unmetered paid path -- the residual the Owner was
asked to accept (decision A3). These tests were written first and failed on 58c68be:

    no guard              a local request is refused unsent (was: sent, unmetered)
    database, no budget   the environment's guard meters this machine (was: not)
    wildcard              `*` never makes a model free, in Python as in SQL (was: every model)
    paid-proxy signals    a "free" endpoint that answers with a billing header or a cost in its
                          usage is reported, and the call is refused (was: accepted silently)

The Owner's exact (endpoint, model) free declaration stays the one exemption.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

import pytest

from lab_brain.evaluation.live_budget import LiveBudgetMissing, free_endpoints_from_env
from lab_brain.llm_runtime import spend
from lab_brain.llm_runtime.provider import OpenAICompatibleClient, ProviderError, ProviderFailure
from lab_brain.llm_runtime.spend import Reservation, SpendRequest
from tests.transport_endpoints import Endpoint

KEY = "sk-test-local-proxy-0123456789abcdefABCDEF"


@dataclass
class FreeGuard:
    """A guard whose Owner declared exactly `free` free; records reports and reservations."""

    free: set[tuple[str, str]] = field(default_factory=set)
    meter_this_machine: bool = True
    reported: list[tuple[str, str, tuple[str, ...]]] = field(default_factory=list)
    reserved: list[SpendRequest] = field(default_factory=list)

    def declared_free(self, endpoint_host: str, model: str) -> bool:
        return (endpoint_host, model) in self.free

    def report_paid_proxy(self, endpoint_host: str, model: str, signals: tuple[str, ...]) -> None:
        self.reported.append((endpoint_host, model, signals))
        self.free.discard((endpoint_host, model))

    def reserve(self, request: SpendRequest) -> Reservation:
        self.reserved.append(request)
        return Reservation(request.call_id, "b", Decimal("0.01"))

    def settle(self, reservation: Reservation, usage: Mapping[str, int] | None) -> str:
        return "SETTLED"

    def retain(self, reservation: Reservation, reason: str) -> None:
        return


@pytest.fixture(autouse=True)
def _no_ambient_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "LAB_BRAIN_LLM_SPEND_BUDGET",
        "LAB_BRAIN_LLM_SPEND_DSN",
        "LAB_BRAIN_DATABASE_URL",
        "LAB_BRAIN_LLM_SPEND_METER_LOCAL",
        "LAB_BRAIN_LLM_MAX_OUTPUT_TOKENS",
    ):
        monkeypatch.delenv(name, raising=False)
    spend.install(None)


@pytest.fixture
def endpoint():
    started = Endpoint().start()
    yield started
    started.stop()


def _chats(endpoint: Endpoint) -> int:
    return sum(1 for seen in endpoint.seen if seen.method == "POST")


def test_with_no_ceiling_configured_a_local_request_is_refused_unsent(endpoint):
    client = OpenAICompatibleClient(endpoint.origin + "/v1", KEY)
    with pytest.raises(ProviderError) as refused:
        client.chat("m", "a prompt a local proxy could forward to a paid provider")
    assert refused.value.failure is ProviderFailure.SPEND_REFUSED
    assert "free" in refused.value.detail
    assert _chats(endpoint) == 0


def test_the_model_list_of_a_local_server_still_needs_no_guard(endpoint):
    """A GET without a body carries no prompt and generates nothing (011r): still unmetered."""
    OpenAICompatibleClient(endpoint.origin + "/v1", KEY).list_models()
    assert [seen.method for seen in endpoint.seen] == ["GET"]


@pytest.mark.parametrize("switch", [None, "0", "false", "off", ""])
def test_a_database_without_a_budget_refuses_an_undeclared_local_request(
    endpoint, monkeypatch: pytest.MonkeyPatch, switch
):
    """The environment's guard (a database, no budget) meters this machine; the retired
    LAB_BRAIN_LLM_SPEND_METER_LOCAL switch cannot turn that off (was: sent unmetered)."""
    monkeypatch.setenv("LAB_BRAIN_LLM_SPEND_DSN", "postgresql://127.0.0.1:1/unreachable")
    if switch is not None:
        monkeypatch.setenv("LAB_BRAIN_LLM_SPEND_METER_LOCAL", switch)
    with pytest.raises(ProviderError) as refused:
        OpenAICompatibleClient(endpoint.origin + "/v1", KEY).chat("m", "hello")
    assert refused.value.failure is ProviderFailure.SPEND_REFUSED
    assert _chats(endpoint) == 0


def test_no_guard_has_a_way_to_exempt_this_machine_as_such(endpoint):
    """A guard object that says it does not meter this machine (the 011t attribute) is metered."""
    guard = FreeGuard(meter_this_machine=False)
    OpenAICompatibleClient(endpoint.origin + "/v1", KEY, spend=guard).chat("m", "hello")
    assert [r.model for r in guard.reserved] == ["m"]


def test_an_exact_free_declaration_lets_a_local_request_through_unreserved(endpoint):
    host = f"127.0.0.1:{endpoint.port}"
    guard = FreeGuard(free={(host, "m")})
    OpenAICompatibleClient(endpoint.origin + "/v1", KEY, spend=guard).chat("m", "hello")
    assert _chats(endpoint) == 1 and guard.reserved == [] and guard.reported == []


def test_another_model_at_a_free_endpoint_is_not_free(endpoint):
    host = f"127.0.0.1:{endpoint.port}"
    guard = FreeGuard(free={(host, "m")})
    OpenAICompatibleClient(endpoint.origin + "/v1", KEY, spend=guard).chat("gpt-paid", "hi")
    assert [r.model for r in guard.reserved] == ["gpt-paid"]


@pytest.mark.parametrize(
    ("headers", "extra", "signal"),
    [
        ({"x-litellm-response-cost": "0.0042"}, {}, "x-litellm-response-cost"),
        ({"openai-organization": "org-123"}, {}, "openai-organization"),
        ({"anthropic-ratelimit-tokens-limit": "80000"}, {}, "anthropic-ratelimit-tokens-limit"),
        ({}, {"usage": {"prompt_tokens": 3, "completion_tokens": 1, "cost": 0.0004}}, "usage.cost"),
        ({}, {"usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_cost": 1}}, "usage."),
    ],
)
def test_a_free_endpoint_that_answers_like_a_paid_proxy_is_reported_and_refused(
    headers, extra, signal
):
    endpoint = Endpoint(headers=headers, extra=extra).start()
    try:
        host = f"127.0.0.1:{endpoint.port}"
        guard = FreeGuard(free={(host, "m")})
        client = OpenAICompatibleClient(endpoint.origin + "/v1", KEY, spend=guard)
        with pytest.raises(ProviderError) as refused:
            client.chat("m", "hello")
        assert refused.value.failure is ProviderFailure.SPEND_REFUSED
        assert len(guard.reported) == 1
        reported_host, reported_model, signals = guard.reported[0]
        assert (reported_host, reported_model) == (host, "m")
        assert any(signal in s for s in signals)
        # The next request is no longer free: it is metered.
        client.chat("m", "again")
        assert [r.model for r in guard.reserved] == ["m"]
    finally:
        endpoint.stop()


def test_a_plain_local_model_server_raises_no_signal(endpoint):
    host = f"127.0.0.1:{endpoint.port}"
    guard = FreeGuard(free={(host, "m")})
    OpenAICompatibleClient(endpoint.origin + "/v1", KEY, spend=guard).chat("m", "hello")
    assert guard.reported == []


def test_the_signal_detector_names_what_it_saw():
    assert spend.paid_proxy_signals({}, {"usage": {"prompt_tokens": 1}}) == ()
    found = spend.paid_proxy_signals(
        {"X-LiteLLM-Response-Cost": "0.1", "Content-Type": "application/json"},
        {"usage": {"cost": 0.1}},
    )
    assert "header:x-litellm-response-cost" in found and "usage.cost" in found


def test_a_wildcard_free_endpoint_is_refused_by_the_evaluation_declaration():
    env = {"LAB_BRAIN_LIVE_FREE_ENDPOINTS": "127.0.0.1:11434 *", "LAB_BRAIN_LIVE_FREE_REASON": "x"}
    with pytest.raises(LiveBudgetMissing, match=r"\*"):
        free_endpoints_from_env(env)
