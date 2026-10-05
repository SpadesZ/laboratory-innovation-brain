"""The ROLE_HYPOTHESIS conformance suite, without a backend.

A model passed a one-space probe and then, given the vertical's several outcome spaces in real
research, bound a prediction to a space it named itself from the evidence (`os:sp.cj_per_mm`); the
parser refused it (VER-004). The parser was right; the qualification was too trivial for the
contract it certified. Proven here:

    no longer current   the single-space qualification's digest -- and the route the deployment
                        locked under it -- are not the ones in force
    multi-space         passes only when every prediction is bound to a declared (id, version) pair
                        and expects an outcome that space admits; using every space is not required
    invented space      a plausible id made from a quantity the evidence names is FAILED
    undeclared outcome  a declared space with an outcome it does not admit is FAILED
    synthetic only      the case carries no silicon-photonics identifier and no project evidence
    minimum N           still enforced, by each case, on its own
    semantics           the suite, its cases, the prompt and the contract are in the digest that
                        makes earlier locks stale

Readiness, the runtime boundary, re-locking and history are proven in
`tests/integration/test_hypothesis_conformance_postgres.py` and
`tests/e2e/test_web_hypothesis_conformance_postgres.py`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from pathlib import Path

import lab_brain.llm_runtime.registry as registry_module
from lab_brain.cognition.roles import HYPOTHESIS_ENGINE
from lab_brain.domains.silicon_photonics.product import mechanism_catalog
from lab_brain.llm_runtime.capabilities import Capability
from lab_brain.llm_runtime.contracts import (
    CONTRACT_DIGEST,
    HYPOTHESIS_CONTRACT,
    RESPONSE_CONTRACT_VERSION,
)
from lab_brain.llm_runtime.probes import (
    HYPOTHESIS_SUITE,
    PROBE_VERSION,
    QUALIFICATION_DIGEST,
    TEMPTING_QUANTITIES,
    ProbeOutcome,
    hypothesis_suite,
    multi_space_probe,
    qualification_digest,
    run_probe,
)
from lab_brain.llm_runtime.provider import ChatReply, ProviderError, ProviderFailure
from lab_brain.llm_runtime.registry import ConnectionRow, lock_fingerprint

#: `QUALIFICATION_DIGEST` as it was under the single-space probe (`probe-2.0.0`, prompt 2.0.0).
SINGLE_SPACE_DIGEST = "50c6da1f8af4006637fe72ed7498c41099002a8069acefb9f0ca4e44337e8c00"

_MARKER = "\n\nCONTEXT:\n"
Binding = tuple[str, str, str]  # outcome_space_id, outcome_space_version, expected_outcome
LEVEL = ("os:probe.bench_level", "1.0.0", "ABOVE_REFERENCE")
WARMUP = ("os:probe.warmup_trend", "2.0.0", "RISES_THEN_HOLDS")
PLATE = ("os:probe.plate_position", "1.0.0", "EDGE_HIGHER")
REPEAT = ("os:probe.repeatability", "1.0.0", "REPEATABLE")


def _context(prompt: str) -> dict[str, object]:
    value = json.loads(prompt.split(_MARKER, 1)[1])
    assert isinstance(value, dict)
    return value


def _answer(count: int, bindings: Sequence[Binding]) -> str:
    """`count` distinct certificates; certificate n predicts over bindings[n % len(bindings)]."""
    return json.dumps(
        {
            "hypotheses": [
                {
                    "key": f"h{n}",
                    "statement": f"mechanism {n} explains the reading.",
                    "mechanism": f"mechanism {n}",
                    "assumptions": ["the reading is representative"],
                    "falsifier": f"a check that rules out mechanism {n}",
                    "confounders": ["placement"],
                    "minimal_test_ref": "repeat the measurement",
                    "predictions": [
                        {
                            "observable_ref": "channel A reading",
                            "outcome_space_id": bindings[n % len(bindings)][0],
                            "outcome_space_version": bindings[n % len(bindings)][1],
                            "expected_outcome": bindings[n % len(bindings)][2],
                            "relation_effect": "SUPPORTS",
                        }
                    ],
                }
                for n in range(count)
            ],
            "position": {"mechanism_view": "mechanism 0", "uncertainties": []},
        }
    )


def _valid(prompt: str, count: int) -> str:
    """A valid answer to either case: every prediction over a space the context declares."""
    spaces = _context(prompt)["outcome_spaces"]
    assert isinstance(spaces, list)
    return _answer(
        count,
        [(s["outcome_space_id"], s["outcome_space_version"], s["outcomes"][0]) for s in spaces],
    )


class _Model:
    """Answers each case with `answer(case, prompt)`, after `latency[case]` ms; records the calls."""

    def __init__(
        self,
        answer: Callable[[str, str], str],
        latency: dict[str, int] | None = None,
        fail_on: str | None = None,
    ) -> None:
        self.answer = answer
        self.latency = latency or {}
        self.fail_on = fail_on
        self.cases: list[str] = []

    def chat(self, model: str, prompt: str, **_: object) -> ChatReply:
        case = "multi-space" if "os:probe.bench_level" in prompt else "contextual-minimum"
        self.cases.append(case)
        if case == self.fail_on:
            raise ProviderError(ProviderFailure.TIMEOUT, "no answer within 9 s")
        return ChatReply(text=self.answer(case, prompt), latency_ms=self.latency.get(case, 7))


def _suite(model: _Model, minimum: int = 5):  # type: ignore[no-untyped-def]
    return run_probe(model, "m", Capability.ROLE_HYPOTHESIS, hypothesis_minimum=minimum)  # type: ignore[arg-type]


def test_the_single_space_qualification_is_no_longer_current(monkeypatch):
    assert QUALIFICATION_DIGEST != SINGLE_SPACE_DIGEST
    assert PROBE_VERSION == "probe-3.0.0"
    assert [name for name, _ in hypothesis_suite(5)] == ["contextual-minimum", "multi-space"]
    # The route the LOCAL deployment locked qwen2.5:7b under the single-space probe, recomputed
    # from its public parts: it is that route under the old semantics, and not under the current.
    ollama = ConnectionRow(
        "llc:x",
        "ollama",
        "OPENAI_COMPATIBLE",
        "http://host.docker.internal:11434/v1",
        "LOCAL",
        None,
        None,
        "ENABLED",
        "act:x",
        None,  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
    )
    caps = [
        "CHAT",
        "ROLE_CRITIQUE",
        "ROLE_HYPOTHESIS",
        "ROLE_QUERY",
        "ROLE_SPECIALIST",
        "STRUCTURED_JSON",
    ]
    one_space = {"ROLE_HYPOTHESIS": {"minimum_hypotheses": 5}}
    assert lock_fingerprint(ollama, "qwen2.5:7b", caps, one_space) != "lk:09d58ebac3b9b558"
    monkeypatch.setattr(registry_module, "QUALIFICATION_DIGEST", SINGLE_SPACE_DIGEST)
    assert lock_fingerprint(ollama, "qwen2.5:7b", caps, one_space) == "lk:09d58ebac3b9b558"


def test_the_multi_space_case_passes_only_declared_pairs_and_legal_outcomes():
    case = multi_space_probe(5)
    assert case.judge(_answer(5, [LEVEL, WARMUP, PLATE, REPEAT])) is None
    assert case.judge(_answer(5, [PLATE])) is None, "using every declared space is not required"
    # The pair is copied, not assumed: the warm-up space is declared at 2.0.0 only.
    wrong_version = case.judge(_answer(5, [LEVEL, ("os:probe.warmup_trend", "1.0.0", "STEADY")]))
    assert "os:probe.warmup_trend@1.0.0, which the engine was not shown" in str(wrong_version)
    # A space the contextual case declares is not declared here.
    other_case = case.judge(_answer(5, [("os:probe.level", "1.0.0", "HIGH")]))
    assert "was not shown" in str(other_case)


def test_an_invented_outcome_space_is_failed():
    for quantity in TEMPTING_QUANTITIES:
        invented = (f"os:probe.{quantity}", "1.0.0", "HIGH")
        model = _Model(
            lambda case, prompt, invented=invented: (
                _answer(5, [LEVEL, invented]) if case == "multi-space" else _valid(prompt, 5)
            )
        )
        result = _suite(model)
        assert result.outcome is ProbeOutcome.FAILED, quantity
        assert result.detail.startswith("multi-space: the typed role parser refused it")
        assert f"{invented[0]}@1.0.0, which the engine was not shown" in result.detail
        assert "VER-004" in result.detail
        assert model.cases == ["contextual-minimum", "multi-space"]


def test_a_declared_space_with_an_undeclared_outcome_is_failed():
    model = _Model(
        lambda case, prompt: (
            _answer(5, [PLATE, ("os:probe.bench_level", "1.0.0", "HIGH")])
            if case == "multi-space"
            else _valid(prompt, 5)
        )
    )
    result = _suite(model)
    assert result.outcome is ProbeOutcome.FAILED
    assert result.detail.startswith("multi-space:")
    assert "expects 'HIGH', which os:probe.bench_level@1.0.0 does not admit" in result.detail


def test_the_multi_space_case_carries_nothing_of_a_domain_or_project():
    prompt = multi_space_probe(5).prompt
    context = _context(prompt)
    evidence = context["evidence"]
    declared = context["outcome_spaces"]
    assert isinstance(evidence, list) and isinstance(declared, list)
    assert all(str(e["attestation_id"]).startswith("att:probe-m") for e in evidence)
    assert str(context["question"]).startswith("PROBE:")
    # Several spaces, one not at 1.0.0; quantities the evidence names that no space is.
    assert len(declared) >= 3 and {s["outcome_space_version"] for s in declared} != {"1.0.0"}
    texts = " ".join(str(e["text"]) for e in evidence)
    ids = {str(s["outcome_space_id"]) for s in declared}
    for quantity in TEMPTING_QUANTITIES:
        assert quantity in texts and not any(quantity in i for i in ids)
    # Nothing of the silicon-photonics pack: no identifier, no space, no mechanism, no fixture text.
    pack = Path(__file__).parents[2] / "src" / "lab_brain" / "domains" / "silicon_photonics"
    sp_ids = {
        m
        for f in pack.glob("*.py")
        for m in re.findall(r"(?:os|cap):sp\.\w+", f.read_text("utf-8"))
    }
    assert sp_ids, "the pack declares identifiers to compare against"
    lowered = prompt.lower()
    for forbidden in (*sp_ids, "os:sp.", "cap:sp.", "silicon", "photonic"):
        assert forbidden.lower() not in lowered, forbidden
    for mechanism in mechanism_catalog().mechanisms:
        assert mechanism.mechanism.lower() not in lowered, mechanism.mechanism
    assert not re.search(r"\b(?:Rs|Cj)\b", prompt)
    fixture = Path(__file__).parents[2] / "fixtures" / "evidence" / "rs_anomaly_report.md"
    for line in fixture.read_text("utf-8").splitlines():
        if len(line.strip()) > 20:
            assert line.strip().lower() not in lowered


def test_the_contextual_minimum_is_enforced_by_each_case_on_its_own():
    # Bindings right, one certificate short: the first case fails, and the second is not asked.
    short = _Model(lambda case, prompt: _valid(prompt, 4))
    result = _suite(short)
    assert result.outcome is ProbeOutcome.FAILED
    assert result.detail.startswith("contextual-minimum:")
    assert "expected at least 5 hypotheses, got 4" in result.detail
    assert short.cases == ["contextual-minimum"]
    # Five over one space, four over several: the multi-space case enforces N too.
    uneven = _Model(lambda case, prompt: _valid(prompt, 5 if case == "contextual-minimum" else 4))
    result = _suite(uneven)
    assert result.detail.startswith("multi-space:") and "got 4" in result.detail
    # Four is enough where four is asked.
    assert _suite(_Model(lambda case, prompt: _valid(prompt, 4)), minimum=4).outcome is (
        ProbeOutcome.PASSED
    )


def test_the_suite_records_what_it_ran_and_its_slowest_call():
    model = _Model(
        lambda case, prompt: _valid(prompt, 5),
        latency={"contextual-minimum": 7, "multi-space": 40},
    )
    result = _suite(model)
    assert result.outcome is ProbeOutcome.PASSED
    assert dict(result.parameters) == {
        "minimum_hypotheses": 5,
        "suite": HYPOTHESIS_SUITE,
        "cases": ["contextual-minimum", "multi-space"],
    }
    assert result.latency_ms == 40, "each call must fit the deadline: the slowest is recorded"
    assert str(result.response_digest).startswith("sha256:")
    # A case that cannot be asked is an ERROR, named, with the suite still recorded.
    error = _suite(_Model(lambda case, prompt: _valid(prompt, 5), fail_on="multi-space"))
    assert error.outcome is ProbeOutcome.ERROR
    assert error.detail.startswith("multi-space: TIMEOUT")
    assert error.parameters["suite"] == HYPOTHESIS_SUITE


def test_the_suite_the_prompt_and_the_contract_are_the_semantics_locks_are_made_under():
    template = HYPOTHESIS_ENGINE.prompt.template
    assert HYPOTHESIS_ENGINE.prompt.prompt_version == "2.1.0"
    assert "copy its outcome_space_id and outcome_space_version exactly" in template
    assert "expected_outcome verbatim from that same space's outcomes" in template
    assert "Never invent or infer an outcome space from the evidence" in template
    assert RESPONSE_CONTRACT_VERSION == "rc-1.1.0"
    assert "Never make up an outcome space or derive one from a quantity" in HYPOTHESIS_CONTRACT
    base = {
        "probe_version": PROBE_VERSION,
        "contracts": CONTRACT_DIGEST,
        "probes": {
            "ROLE_HYPOTHESIS": {"suite": HYPOTHESIS_SUITE, "cases": {"multi-space": ["p", "c"]}}
        },
        "prompts": {"prm:hypothesis-engine": ["2.1.0", template]},
    }
    digest = qualification_digest(**base)  # type: ignore[arg-type]
    for changed in (
        {"probes": {"ROLE_HYPOTHESIS": {"suite": "hypothesis-conformance@1.0.1", "cases": {}}}},
        {
            "probes": {
                "ROLE_HYPOTHESIS": {"suite": HYPOTHESIS_SUITE, "cases": {"multi-space": ["q", "c"]}}
            }
        },
        {"prompts": {"prm:hypothesis-engine": ["2.1.0", template + " "]}},
        {"contracts": "another contract digest"},
    ):
        assert qualification_digest(**{**base, **changed}) != digest, changed  # type: ignore[arg-type]
