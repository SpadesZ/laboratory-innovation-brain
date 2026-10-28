"""The cost-path audit's DEMONSTRATED gaps, each as the test that failed before the fix.

docs/audit/g0-evidence-auth-cost-closure-2026-10-28/cost-path-audit.md lists every path that can
send a billable request. Three of its gaps could be shown against the transport as it was, with no
network and no provider -- a local HTTP endpoint that records what it received:

    unbounded output   `chat()` sent no `max_tokens`: the provider decided how much to generate,
                       so no per-request worst case existed to cap money with
    no money check     a request to a remote endpoint was sent with no monetary ceiling and no
                       declared price -- there was no switch that could refuse it
    two per call       a provider that refuses `response_format` makes ONE logical call cost TWO
                       billed requests; any per-call meter undercounts it

Each is asserted here as the property the fixed transport has. The guard's own behaviour (worst
case, reservation, settlement, overrun) is in `test_g0_spend_guard.py`; the atomic PostgreSQL
ledger in `tests/e2e/test_g0_spend_ledger_postgres.py`.
"""

from __future__ import annotations

import json
import urllib.request

import pytest

from lab_brain.llm_runtime.provider import OpenAICompatibleClient, ProviderError
from tests.fake_llm_provider import FakeProvider
from tests.transport_endpoints import Endpoint

KEY = "sk-test-spend-gaps-0123456789abcdefABCDEF"


def test_gap_unbounded_output_every_chat_request_carries_max_tokens():
    endpoint = Endpoint().start()
    try:
        client = OpenAICompatibleClient(endpoint.origin + "/v1", KEY)
        client.chat("m", "Reply with exactly one word: pong")
        client.chat("m", "a research prompt", response_schema=("s", {"type": "object"}))
    finally:
        endpoint.stop()
    bodies = [json.loads(s.body) for s in endpoint.seen]
    assert len(bodies) == 2
    for body in bodies:
        assert isinstance(body.get("max_tokens"), int) and body["max_tokens"] >= 1, body


def test_gap_no_money_check_a_required_ceiling_refuses_a_remote_request_unsent(
    monkeypatch: pytest.MonkeyPatch,
):
    """With the guard REQUIRED and no ceiling configured, a request to a remote endpoint is
    refused before a connection is even opened -- the prompt never leaves the process."""
    monkeypatch.setenv("LAB_BRAIN_LLM_SPEND_REQUIRED", "1")
    monkeypatch.delenv("LAB_BRAIN_LLM_SPEND_BUDGET", raising=False)
    opened: list[str] = []

    def refuse_to_open(self: object, request: object, *args: object, **kw: object) -> object:
        opened.append(getattr(request, "full_url", str(request)))
        raise AssertionError("a connection was opened")

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", refuse_to_open)
    client = OpenAICompatibleClient("https://models.provider.invalid/v1", KEY)
    with pytest.raises(ProviderError) as refused:
        client.chat("m", "EVIDENCE-0001 a research prompt")
    assert refused.value.failure.value == "SPEND_REFUSED"
    assert "EVIDENCE-0001" not in str(refused.value) and KEY not in str(refused.value)
    assert opened == []


def test_gap_two_per_call_a_schema_refusal_is_two_billed_requests():
    """The fact the meter must follow: one `chat()` against a provider that refuses the schema
    reaches the provider twice. (That each of the two is reserved separately is asserted in
    `test_g0_spend_guard.py`.)"""
    fake = FakeProvider(api_key=KEY, refuse_schema=True).start()
    try:
        reply = OpenAICompatibleClient(fake.base_url, KEY).chat(
            "fake-reasoner",
            "Return exactly this JSON object",
            response_schema=("s", {"type": "object"}),
        )
    finally:
        fake.stop()
    assert reply.output_mode is not None and reply.output_mode.startswith("PROMPT_ONLY")
    assert len(fake.calls) == 2
