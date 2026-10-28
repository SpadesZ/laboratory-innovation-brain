"""The spend ceiling at the transport: what is reserved, when, and what a reservation ends as.

Every test talks to a real local HTTP endpoint through the real `OpenAICompatibleClient`; the guard
is an in-memory stand-in that records what the transport asked of it (the PostgreSQL guard, and the
atomicity of its reservations, are in `tests/e2e/test_g0_spend_ledger_postgres.py`). The endpoints
are on 127.0.0.1 -- this machine -- so the stand-in says `meter_this_machine`, exactly as an Owner
metering a local proxy would; one test shows the same client is NOT metered without it.

    before       a reservation precedes the request; a refused reservation sends nothing
    size         the reserved body is the bytes the endpoint received; `max_tokens` is what it
                 received; an image is counted
    endings      usage -> settle; no usage, an HTTP error, a timeout -> retain at the worst case
    two          the schema fallback is two reservations
    every path   capability probes are reserved; the model list (GET, no body) is not
    required     a remote request with no guard, when required, is refused unsent
"""

from __future__ import annotations

import json
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

import pytest

from lab_brain.evaluation.live_budget import LiveBudgetMissing, spend_from_env
from lab_brain.llm_runtime import spend
from lab_brain.llm_runtime.capabilities import Capability
from lab_brain.llm_runtime.probes import PROBE_ORDER, run_probe
from lab_brain.llm_runtime.provider import (
    OpenAICompatibleClient,
    ProviderError,
    ProviderFailure,
)
from lab_brain.llm_runtime.spend import Reservation, SpendRefused, SpendRequest
from tests.fake_llm_provider import FakeProvider
from tests.transport_endpoints import Endpoint

KEY = "sk-test-spend-guard-0123456789abcdefABCDEF"


@dataclass
class Recorder:
    meter_this_machine: bool = True
    refuse: str | None = None
    reserved: list[SpendRequest] = field(default_factory=list)
    settled: list[tuple[str, Mapping[str, int] | None]] = field(default_factory=list)
    retained: list[tuple[str, str]] = field(default_factory=list)

    def reserve(self, request: SpendRequest) -> Reservation:
        if self.refuse is not None:
            raise SpendRefused(self.refuse)
        self.reserved.append(request)
        return Reservation(request.call_id, "test", Decimal("0.01"))

    def settle(self, reservation: Reservation, usage: Mapping[str, int] | None) -> str:
        self.settled.append((reservation.call_id, usage))
        return "SETTLED"

    def retain(self, reservation: Reservation, reason: str) -> None:
        self.retained.append((reservation.call_id, reason))


@pytest.fixture(autouse=True)
def _no_ambient_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "LAB_BRAIN_LLM_SPEND_BUDGET",
        "LAB_BRAIN_LLM_SPEND_REQUIRED",
        "LAB_BRAIN_LLM_MAX_OUTPUT_TOKENS",
    ):
        monkeypatch.delenv(name, raising=False)
    spend.install(None)


@pytest.fixture
def endpoint():
    started = Endpoint().start()
    yield started
    started.stop()


def test_the_worst_case_is_the_stated_formula():
    bound, cost = spend.worst_case_cost(
        body_bytes=10_000,
        image_count=1,
        max_output_tokens=16_384,
        input_per_mtok=Decimal("1.25"),
        output_per_mtok=Decimal("10"),
        safety_multiplier=Decimal("1.5"),
        image_allowance_tokens=4096,
        request_overhead_tokens=1024,
    )
    assert bound == 15_000 + 4096 + 1024
    assert cost == (Decimal(20_120) * Decimal("1.25") + Decimal(16_384) * 10) / 1_000_000
    with pytest.raises(ValueError):
        spend.worst_case_cost(
            body_bytes=1,
            image_count=0,
            max_output_tokens=0,
            input_per_mtok=Decimal(1),
            output_per_mtok=Decimal(1),
        )
    with pytest.raises(ValueError):
        spend.worst_case_cost(
            body_bytes=1,
            image_count=0,
            max_output_tokens=1,
            input_per_mtok=Decimal(1),
            output_per_mtok=Decimal(1),
            safety_multiplier=Decimal("0.9"),
        )


def test_a_reservation_names_the_bytes_and_max_tokens_the_endpoint_received(endpoint):
    guard = Recorder()
    client = OpenAICompatibleClient(
        endpoint.origin + "/v1", KEY, spend=guard, max_output_tokens=777
    )
    client.chat("m", "a research prompt éé", image_png=b"\x89PNG fake")
    (seen,) = endpoint.seen
    (asked,) = guard.reserved
    assert asked.body_bytes == len(seen.body)
    assert asked.max_output_tokens == json.loads(seen.body)["max_tokens"] == 777
    assert asked.image_count == 1 and asked.model == "m"
    assert asked.endpoint_host == f"127.0.0.1:{endpoint.port}"
    assert asked.call_id.startswith("llmcall:")
    # The endpoint's reply has no usage: the worst case stays charged.
    assert guard.settled == [] and [c for c, _ in guard.retained] == [asked.call_id]


def test_reported_usage_settles_and_missing_usage_retains():
    fake = FakeProvider(api_key=KEY).start()
    try:
        guard = Recorder()
        OpenAICompatibleClient(fake.base_url, KEY, spend=guard).chat(
            "fake-reasoner", "Reply with exactly one word: pong"
        )
    finally:
        fake.stop()
    ((call, usage),) = guard.settled
    assert call == guard.reserved[0].call_id
    assert usage is not None and usage["prompt_tokens"] >= 1 and "completion_tokens" in usage
    assert guard.retained == []
    assert spend.usage_tokens({"prompt_tokens": 3}) is None
    assert spend.usage_tokens({"prompt_tokens": 3, "completion_tokens": True}) is None
    assert spend.usage_tokens({"prompt_tokens": 3, "completion_tokens": 4}) == (3, 4, None)


def test_a_refused_reservation_sends_nothing(endpoint):
    guard = Recorder(refuse="no price is declared for model m")
    client = OpenAICompatibleClient(endpoint.origin + "/v1", KEY, spend=guard)
    with pytest.raises(ProviderError) as refused:
        client.chat("m", "EVIDENCE-0002")
    assert refused.value.failure is ProviderFailure.SPEND_REFUSED
    assert "no price" in refused.value.detail and "EVIDENCE-0002" not in str(refused.value)
    assert endpoint.seen == []


def test_this_machine_is_not_metered_unless_the_guard_says_so(endpoint):
    guard = Recorder(meter_this_machine=False)
    OpenAICompatibleClient(endpoint.origin + "/v1", KEY, spend=guard).chat("m", "local prompt")
    assert len(endpoint.seen) == 1 and guard.reserved == []


def test_a_timeout_keeps_the_worst_case():
    fake = FakeProvider(api_key=KEY, delay=lambda prompt, system: 3.0).start()
    try:
        guard = Recorder()
        client = OpenAICompatibleClient(fake.base_url, KEY, timeout=1.0, spend=guard)
        with pytest.raises(ProviderError) as failed:
            client.chat("fake-reasoner", "Reply with exactly one word: pong")
    finally:
        fake.stop()
    assert failed.value.failure is ProviderFailure.TIMEOUT
    assert len(fake.calls) == 1, "the provider received it -- and may bill it"
    ((call, reason),) = guard.retained
    assert call == guard.reserved[0].call_id and "TimeoutError" in reason
    assert guard.settled == []


def test_the_schema_fallback_reserves_twice():
    fake = FakeProvider(api_key=KEY, refuse_schema=True).start()
    try:
        guard = Recorder()
        OpenAICompatibleClient(fake.base_url, KEY, spend=guard).chat(
            "fake-reasoner",
            "Return exactly this JSON object",
            response_schema=("s", {"type": "object"}),
        )
    finally:
        fake.stop()
    assert len(fake.calls) == 2 and len(guard.reserved) == 2
    first, second = (r.call_id for r in guard.reserved)
    assert first != second
    assert [c for c, _ in guard.retained] == [first], "the refused one stays at its worst case"
    assert [c for c, _ in guard.settled] == [second]
    assert guard.reserved[0].body_bytes > guard.reserved[1].body_bytes, "schema, then none"


def test_every_capability_probe_request_is_reserved_and_the_model_list_is_not():
    fake = FakeProvider(api_key=KEY).start()
    try:
        guard = Recorder()
        client = OpenAICompatibleClient(fake.base_url, KEY, spend=guard)
        assert "fake-reasoner" in client.list_models()
        assert guard.reserved == [], "GET /models carries no body and generates nothing"
        for capability in PROBE_ORDER:
            run_probe(client, "fake-reasoner", capability)
    finally:
        fake.stop()
    assert len(fake.calls) >= len(PROBE_ORDER)
    assert len(guard.reserved) == len(fake.calls), "every request a probe sent was reserved first"
    assert {r.model for r in guard.reserved} == {"fake-reasoner"}


def test_a_probe_refused_by_the_ceiling_records_an_error_and_sends_nothing():
    fake = FakeProvider(api_key=KEY).start()
    try:
        client = OpenAICompatibleClient(fake.base_url, KEY, spend=Recorder(refuse="ceiling"))
        result = run_probe(client, "fake-reasoner", Capability.CHAT)
    finally:
        fake.stop()
    assert result.outcome.value == "ERROR" and "SPEND_REFUSED" in result.detail
    assert fake.calls == []


def test_the_model_list_carries_no_body(endpoint):
    OpenAICompatibleClient(endpoint.origin + "/v1", KEY, spend=Recorder()).list_models()
    (seen,) = endpoint.seen
    assert seen.method == "GET" and seen.body == b""


def test_a_metered_request_without_max_tokens_or_body_is_impossible(endpoint):
    guard = Recorder()
    client = OpenAICompatibleClient(endpoint.origin + "/v1", KEY, spend=guard)
    for payload in ({"model": "m", "messages": []}, {"model": "m", "max_tokens": 0}):
        with pytest.raises(ProviderError) as refused:
            client._request("POST", "/chat/completions", payload)
        assert refused.value.failure is ProviderFailure.SPEND_REFUSED
    with pytest.raises(ProviderError):
        client._request("POST", "/chat/completions", None)
    with pytest.raises(ValueError):
        OpenAICompatibleClient(endpoint.origin + "/v1", KEY, max_output_tokens=0)
    assert endpoint.seen == [] and guard.reserved == []


def test_an_installed_guard_covers_clients_built_anywhere(endpoint):
    guard = Recorder()
    with spend.installed(guard):
        OpenAICompatibleClient(endpoint.origin + "/v1", KEY).chat("m", "prompt")
    assert len(guard.reserved) == 1
    OpenAICompatibleClient(endpoint.origin + "/v1", KEY).chat("m", "prompt")
    assert len(guard.reserved) == 1, "uninstalled again"


def test_a_named_budget_without_a_database_refuses(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LAB_BRAIN_LLM_SPEND_BUDGET", "nowhere")
    monkeypatch.setenv("LAB_BRAIN_DATABASE_URL", "")
    monkeypatch.delenv("LAB_BRAIN_LLM_SPEND_DSN", raising=False)
    opened: list[object] = []
    monkeypatch.setattr(
        urllib.request.OpenerDirector, "open", lambda *a, **k: opened.append(a) or None
    )
    client = OpenAICompatibleClient("https://models.provider.invalid/v1", KEY)
    with pytest.raises(ProviderError) as refused:
        client.chat("m", "prompt")
    assert refused.value.failure is ProviderFailure.SPEND_REFUSED and opened == []


def test_unrequired_and_unconfigured_the_product_keeps_its_behaviour(
    monkeypatch: pytest.MonkeyPatch,
):
    """The web runtime's default until the Owner decides (an Owner Gate): no ceiling configured,
    not required -- a remote request is sent, now with `max_tokens`."""
    sent: list[bytes] = []

    class Reply:
        def __enter__(self) -> Reply:
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"choices": [{"message": {"content": "ok"}}]}'

    def record(self: object, request: urllib.request.Request, *a: object, **k: object) -> Reply:
        sent.append(request.data or b"")
        return Reply()

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", record)
    OpenAICompatibleClient("https://models.provider.invalid/v1", KEY).chat("m", "prompt")
    assert len(sent) == 1 and json.loads(sent[0])["max_tokens"] == spend.DEFAULT_MAX_OUTPUT_TOKENS


def test_the_live_evaluation_requires_a_ceiling_and_prices_for_an_external_primary():
    assert spend_from_env(external=False, env={}) is None
    with pytest.raises(LiveBudgetMissing, match="LAB_BRAIN_LIVE_SPEND_CEILING"):
        spend_from_env(external=True, env={})
    env = {
        "LAB_BRAIN_LIVE_SPEND_CEILING": "25",
        "LAB_BRAIN_LIVE_SPEND_CURRENCY": "usd",
        "LAB_BRAIN_LIVE_PRICE_INPUT_PER_MTOK": "1.25",
        "LAB_BRAIN_LIVE_PRICE_OUTPUT_PER_MTOK": "10",
        "LAB_BRAIN_LIVE_PRICE_SOURCE": "provider pricing page",
        "LAB_BRAIN_LIVE_PRICE_DATE": "2026-10-28",
    }
    declared = spend_from_env(external=True, env=env)
    assert declared is not None and declared.currency == "USD"
    assert declared.ceiling == Decimal(25)
    with pytest.raises(LiveBudgetMissing):
        spend_from_env(external=True, env={**env, "LAB_BRAIN_LIVE_SPEND_MULTIPLIER": "0.5"})
    with pytest.raises(LiveBudgetMissing):
        spend_from_env(external=True, env={**env, "LAB_BRAIN_LIVE_PRICE_DATE": "soon"})
