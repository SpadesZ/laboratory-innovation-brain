"""G0: what the transport asks for and reports, and what qualification now refuses.

schema      every role call carries its JSON schema as `response_format`; a provider that
            refuses the parameter (HTTP 400) is asked once more without it, and the reply says
            so -- any other failure is raised as it was
usage       the provider's own token counts come back with the reply, exactly as given
probes      ROLE_SPECIALIST / ROLE_CRITIQUE are asked with production-shaped ids, through
            research's own context builders, and judged with research's alias resolution: a
            reply that shortens a UUID, invents an alias or repeats one FAILS, as research
            would refuse it. A lock made under the short-id probes is stale.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from lab_brain.cognition.roles import (
    ADVERSARIAL_CRITIC,
    COVERAGE_REVIEW,
    HYPOTHESIS_ENGINE,
    QUERY_REWRITER,
)
from lab_brain.llm_runtime import contracts
from lab_brain.llm_runtime.capabilities import Capability
from lab_brain.llm_runtime.probes import (
    PROBES,
    QUALIFICATION_DIGEST,
    ProbeOutcome,
    coverage_probe,
    production_id,
    run_probe,
)
from lab_brain.llm_runtime.provider import (
    JSON_SCHEMA,
    PROMPT_ONLY,
    OpenAICompatibleClient,
    ProviderError,
)
from lab_brain.llm_runtime.runtime import RouteCompletion, _Route
from tests.fake_llm_provider import FakeProvider

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
#: `QUALIFICATION_DIGEST` under probe-6.0.0 (short synthetic ids), as `pre-lumerical-acceptance`
#: computed it: every lock made under it is now stale.
SHORT_ID_DIGEST = "e8b2be879673f2834981726d06c40879e0f748dc7ebd17e6404e2d2386ee03f1"


@pytest.fixture
def provider():  # type: ignore[no-untyped-def]
    p = FakeProvider().start()
    yield p
    p.stop()


def _client(p: FakeProvider) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(p.base_url, None, timeout=10, local_hosts=())


# -- schemas ----------------------------------------------------------------------------------


def test_every_contract_has_a_schema_in_the_plain_subset_every_provider_reads():
    assert set(contracts.SCHEMAS) == set(contracts.CONTRACTS)
    allowed = {"type", "properties", "required", "items", "enum"}

    def walk(node: Any) -> None:
        assert set(node) <= allowed, set(node) - allowed
        if node["type"] == "object":
            assert set(node["required"]) <= set(node["properties"])
            for child in node["properties"].values():
                walk(child)
        elif node["type"] == "array":
            walk(node["items"])
        else:
            assert node["type"] == "string"

    for schema in contracts.SCHEMAS.values():
        walk(schema)
    critique = contracts.SCHEMAS["ROLE_CRITIQUE"]["properties"]["objections"]["items"]
    assert "CONTRADICTS" not in critique["properties"]["kind"]["enum"], (
        "the live critic wrote a severity as its kind; the schema separates the two"
    )


def test_the_schema_and_contract_are_chosen_by_the_role_the_prompt_speaks_to():
    for template, key in (
        (QUERY_REWRITER.prompt.template, "ROLE_QUERY"),
        (HYPOTHESIS_ENGINE.prompt.template, "ROLE_HYPOTHESIS"),
        (ADVERSARIAL_CRITIC.prompt.template, "ROLE_CRITIQUE"),
        (COVERAGE_REVIEW.prompt.template, "ROLE_COVERAGE_REVIEW"),
    ):
        assert contracts.schema_for(template + "\n\nCONTEXT:\n{}") == (
            key.lower(),
            contracts.SCHEMAS[key],
        )
    assert contracts.schema_for(PROBES[Capability.ROLE_SPECIALIST].prompt)[0] == "role_specialist"  # type: ignore[index]
    assert contracts.schema_for("free text") is None


# -- the transport ----------------------------------------------------------------------------


def test_a_role_call_carries_its_schema_and_returns_the_providers_usage(provider):
    reply = _client(provider).chat(
        "fake-reasoner",
        "PROBE: anything",
        system="s",
        response_schema=("role_query", contracts.SCHEMAS["ROLE_QUERY"]),
    )
    (call,) = provider.calls
    assert call.response_format == {
        "type": "json_schema",
        "json_schema": {"name": "role_query", "schema": contracts.SCHEMAS["ROLE_QUERY"]},
    }
    assert reply.output_mode == JSON_SCHEMA
    assert reply.usage is not None and reply.usage["total_tokens"] == (
        reply.usage["prompt_tokens"] + reply.usage["completion_tokens"]
    )


def test_a_provider_that_refuses_the_schema_is_asked_once_without_it_and_the_reply_says_so(
    provider,
):
    provider.refuse_schema = True
    reply = _client(provider).chat(
        "fake-reasoner", "hello", response_schema=("role_query", contracts.SCHEMAS["ROLE_QUERY"])
    )
    assert [c.response_format is None for c in provider.calls] == [False, True]
    assert reply.output_mode is not None and reply.output_mode.startswith(PROMPT_ONLY)
    assert "HTTP 400" in reply.output_mode
    # Without a schema nothing is retried, and nothing is said about a mode.
    provider.calls.clear()
    plain = _client(provider).chat("fake-reasoner", "hello")
    assert len(provider.calls) == 1 and plain.output_mode is None


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (400, "API key not valid. Please pass a valid API key."),
        (400, "This model's maximum context length is 8192 tokens."),
        (500, "internal error while applying the schema"),
        (503, "overloaded"),
    ],
)
def test_any_other_failure_is_raised_as_before_and_not_retried(provider, status, message):
    """Only a 400/422 that names the structured-output parameter is retried without it: a bad
    key, an over-long prompt or a server error is raised after ONE call, as it always was."""
    provider.fail_with = (status, message)
    with pytest.raises(ProviderError, match=f"HTTP {status}"):
        _client(provider).chat("fake-reasoner", "hello", response_schema=("x", {"type": "object"}))
    assert len(provider.calls) == 1 and provider.calls[0].response_format is not None


def test_the_fallback_records_the_status_and_never_the_providers_words(provider):
    provider.fail_with = (422, "Invalid JSON payload: unknown field response_format.secret-ish")
    reply = _client(provider).chat(
        "fake-reasoner", "hello", response_schema=("x", {"type": "object"})
    )
    assert len(provider.calls) == 2 and provider.calls[1].response_format is None
    assert reply.output_mode == f"{PROMPT_ONLY}: HTTP 422 refused response_format"
    assert "secret-ish" not in str(reply.output_mode)


def test_the_route_hands_back_the_reply_its_usage_and_its_mode(provider):
    from lab_brain.cognition.llm import ModelSlot
    from lab_brain.core.models.inference import LogicalSlot

    route = RouteCompletion({LogicalSlot.FAST_UTILITY: _Route(_client(provider), "fake-reasoner")})
    material = QUERY_REWRITER.prompt.template + '\n\nCONTEXT:\n{"mode":"PRIMARY","question":"q"}'
    reply = route(material, ModelSlot(LogicalSlot.FAST_UTILITY, "fake-reasoner", "1"))
    assert json.loads(reply.text)["terms"]
    assert reply.output_mode == JSON_SCHEMA and reply.usage
    assert provider.calls[0].system == contracts.QUERY_CONTRACT


# -- qualification: production-shaped, and negative ---------------------------------------------


def test_the_specialist_and_critic_probes_are_built_as_research_builds_them():
    for capability in (Capability.ROLE_SPECIALIST, Capability.ROLE_CRITIQUE):
        context = json.loads(PROBES[capability].prompt.split("\n\nCONTEXT:\n", 1)[1])
        assert [h["hypothesis_id"] for h in context["hypotheses"]] == ["H1", "H2", "H3", "H4", "H5"]
        assert all(re.fullmatch(r"E[0-9]+", e["attestation_id"]) for e in context["evidence"])
        assert "hyp:" not in json.dumps(context) and "att:" not in json.dumps(context)
    assert UUID.search(production_id("hyp", "contact"))
    assert production_id("hyp", "contact") == production_id("hyp", "contact"), "fixed"


class _Canned:
    def __init__(self, text: str) -> None:
        self.text = text

    def chat(self, model: str, prompt: str, **_: Any) -> Any:
        from lab_brain.llm_runtime.provider import ChatReply

        return ChatReply(self.text, 1)


def _specialist(favoured: list[str]) -> str:
    return json.dumps({"mechanism_view": "contact oxidation", "favoured_hypothesis_ids": favoured})


@pytest.mark.parametrize(
    ("favoured", "outcome"),
    [
        (["H1", "H3"], ProbeOutcome.PASSED),
        ([production_id("hyp", "contact")], ProbeOutcome.PASSED),
        # What the live specialist did, against production-shaped ids: FAILED here, as research
        # refuses it. The short-id probe could not have shown this.
        ([production_id("hyp", "contact")[:12]], ProbeOutcome.FAILED),
        (["H6"], ProbeOutcome.FAILED),
        (["h1"], ProbeOutcome.FAILED),
        (["H2", "H2"], ProbeOutcome.FAILED),
        (["hyp:probe-contact"], ProbeOutcome.FAILED),
    ],
)
def test_the_specialist_probe_fails_what_research_would_refuse(favoured, outcome):
    result = run_probe(_Canned(_specialist(favoured)), "m", Capability.ROLE_SPECIALIST)  # type: ignore[arg-type]
    assert result.outcome is outcome, result.detail


@pytest.mark.parametrize(
    ("cited", "target", "outcome"),
    [
        (["E2"], "H1", ProbeOutcome.PASSED),
        (["E9"], "H1", ProbeOutcome.FAILED),
        ([production_id("att", "probe-2")[:12]], "H1", ProbeOutcome.FAILED),
        (["E2"], "H7", ProbeOutcome.FAILED),
    ],
)
def test_the_critique_probe_fails_what_research_would_refuse(cited, target, outcome):
    reply = json.dumps(
        {
            "objections": [
                {
                    "target_id": target,
                    "kind": "COUNTEREXAMPLE",
                    "severity": "CONTRADICTS",
                    "text": "the pads were measured after cleaning",
                    "evidence_attestation_ids": cited,
                }
            ],
            "alternative_mechanisms": [],
            "falsifier_challenges": [],
        }
    )
    result = run_probe(_Canned(reply), "m", Capability.ROLE_CRITIQUE)  # type: ignore[arg-type]
    assert result.outcome is outcome, result.detail


def test_the_coverage_case_accepts_a_grounded_answer_or_a_reasoned_decline_and_nothing_else():
    case = coverage_probe()
    decline = {
        "hypotheses": [],
        "declined": [
            {"observable_ref": "bench.repeat_spread", "reason": "E4 shows repeatable readings"}
        ],
    }
    assert case.judge(json.dumps(decline)) is None
    assert "unanswered" in str(case.judge(json.dumps({"hypotheses": [], "declined": []})))
    assert "not JSON" in str(case.judge("I would decline."))


def test_a_lock_made_under_the_short_id_probes_is_stale():
    assert QUALIFICATION_DIGEST != SHORT_ID_DIGEST
