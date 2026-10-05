"""Role qualification, without a backend: what the Hypothesis Engine is asked for, what its probe
demonstrates and records, and what makes a lock stale.

    the prompt          asks for CONTEXT.minimum_hypotheses -- never a number of its own -- so it
                        agrees with the context, the response contract and the parser
    the probe           runs at the N it is asked for, judges by the real parser at that N, and
                        records N with the result: the evidence says what was demonstrated
    the semantics       probe payloads, role prompt ids/versions/texts and response contracts form
                        one digest; changing any of them changes every lock fingerprint
    the requirement     is the research's (one per catalogued mechanism of its vertical), not a
                        number in the generic LLM runtime

Readiness, the runtime boundary and the database are proven in
`tests/integration/test_role_qualification_postgres.py` and
`tests/e2e/test_web_role_qualification_postgres.py`.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import lab_brain.llm_runtime as llm_runtime_package
import lab_brain.llm_runtime.probes as probes_module
from lab_brain.cognition.roles import ADVERSARIAL_CRITIC, HYPOTHESIS_ENGINE, QUERY_REWRITER
from lab_brain.domains.silicon_photonics.product import mechanism_catalog
from lab_brain.llm_runtime.capabilities import Capability
from lab_brain.llm_runtime.contracts import CONTRACT_DIGEST, HYPOTHESIS_CONTRACT
from lab_brain.llm_runtime.probes import (
    GENERIC_HYPOTHESIS_MINIMUM,
    PROBE_VERSION,
    PROBES,
    QUALIFICATION_DIGEST,
    ProbeOutcome,
    hypothesis_probe,
    qualification_digest,
    run_probe,
)
from lab_brain.llm_runtime.provider import ChatReply
from lab_brain.llm_runtime.registry import ConnectionRow, lock_fingerprint
from lab_brain.research.service import debate_minimum

MECHANISMS = (
    "contact oxidation",
    "self heating",
    "edge film thinning",
    "anneal silicide",
    "needle contact force",
    "surface moisture",
)


def _answer(count: int) -> str:
    """A well-formed Hypothesis Engine answer with `count` distinct certificates."""
    return json.dumps(
        {
            "hypotheses": [
                {
                    "key": f"h{n}",
                    "statement": f"{mechanism} explains the high reading.",
                    "mechanism": mechanism,
                    "assumptions": ["the reading is representative"],
                    "falsifier": f"a check that rules out {mechanism}",
                    "confounders": ["probe placement"],
                    "minimal_test_ref": "four point measurement",
                    "predictions": [
                        {
                            "observable_ref": "probe.resistance",
                            "outcome_space_id": "os:probe.level",
                            "outcome_space_version": "1.0.0",
                            "expected_outcome": "HIGH",
                            "relation_effect": "SUPPORTS",
                        }
                    ],
                }
                for n, mechanism in enumerate(MECHANISMS[:count], start=1)
            ],
            "position": {"mechanism_view": "contact oxidation", "uncertainties": []},
        }
    )


class _Model:
    """A model that answers the Hypothesis Engine with a fixed number of certificates."""

    def __init__(self, count: int) -> None:
        self.count = count
        self.prompts: list[str] = []

    def chat(self, model: str, prompt: str, **_: object) -> ChatReply:
        self.prompts.append(prompt)
        return ChatReply(text=_answer(self.count), latency_ms=7)


def test_the_prompt_asks_for_the_contexts_minimum_and_never_a_count_of_its_own():
    template = HYPOTHESIS_ENGINE.prompt.template
    assert "at least CONTEXT.minimum_hypotheses competing mechanisms -- never fewer" in template
    assert "two" not in template.lower() and not any(ch.isdigit() for ch in template)
    assert HYPOTHESIS_ENGINE.prompt.prompt_version == "2.0.0"
    # The response contract and the context agree with it; the parser stays the judge.
    assert "at least CONTEXT.minimum_hypotheses" in HYPOTHESIS_CONTRACT
    assert "minimum_hypotheses" in HYPOTHESIS_ENGINE.requires


def test_the_probe_runs_at_the_minimum_asked_for_and_records_it():
    for minimum in (2, 5):
        probe = hypothesis_probe(minimum)
        assert f'"minimum_hypotheses":{minimum}' in probe.prompt
        assert probe.judge(_answer(minimum)) is None
        assert "expected at least" in str(probe.judge(_answer(minimum - 1)))
    passed = run_probe(_Model(5), "m", Capability.ROLE_HYPOTHESIS, hypothesis_minimum=5)  # type: ignore[arg-type]
    assert passed.outcome is ProbeOutcome.PASSED
    assert dict(passed.parameters) == {"minimum_hypotheses": 5}
    # Two certificates pass at the generic floor and fail at five -- and each says which it was.
    two = _Model(2)
    at_two = run_probe(two, "m", Capability.ROLE_HYPOTHESIS, hypothesis_minimum=2)  # type: ignore[arg-type]
    at_five = run_probe(two, "m", Capability.ROLE_HYPOTHESIS, hypothesis_minimum=5)  # type: ignore[arg-type]
    assert at_two.outcome is ProbeOutcome.PASSED and at_two.parameters == {"minimum_hypotheses": 2}
    assert at_five.outcome is ProbeOutcome.FAILED and at_five.parameters == {
        "minimum_hypotheses": 5
    }
    assert "expected at least 5 hypotheses, got 2" in at_five.detail
    # Only synthetic material: the probe's evidence is the module's own, never a project's.
    assert all("att:probe-" in p for p in two.prompts)
    # Other capabilities have nothing to record; the generic floor is §7.4's 2.
    assert GENERIC_HYPOTHESIS_MINIMUM == 2
    assert PROBES[Capability.ROLE_HYPOTHESIS].prompt == hypothesis_probe(2).prompt
    for impossible in (1, 0, 51):
        with pytest.raises(ValueError):
            hypothesis_probe(impossible)


def test_the_qualification_semantics_are_one_digest_of_probes_prompts_and_contracts():
    base = {
        "probe_version": PROBE_VERSION,
        "contracts": CONTRACT_DIGEST,
        "probes": {"ROLE_HYPOTHESIS": ["payload", "contract"]},
        "prompts": {"prm:hypothesis-engine": ["2.0.0", "template"]},
    }
    digest = qualification_digest(**base)  # type: ignore[arg-type]
    assert digest == qualification_digest(**base)  # type: ignore[arg-type]
    for changed in (
        {"probe_version": "probe-9.9.9"},
        {"contracts": "another contract digest"},
        {"probes": {"ROLE_HYPOTHESIS": ["another payload", "contract"]}},
        {"prompts": {"prm:hypothesis-engine": ["2.0.1", "template"]}},
        {"prompts": {"prm:hypothesis-engine": ["2.0.0", "another template"]}},
    ):
        assert qualification_digest(**{**base, **changed}) != digest, changed  # type: ignore[arg-type]
    # The digest in force is over every probe and every role prompt the runtime serves.
    in_force = qualification_digest(
        probe_version=PROBE_VERSION,
        contracts=CONTRACT_DIGEST,
        probes={c.value: [p.prompt, p.system] for c, p in PROBES.items()},
        prompts={
            r.prompt.prompt_id: [r.prompt.prompt_version, r.prompt.template]
            for r in (QUERY_REWRITER, HYPOTHESIS_ENGINE, ADVERSARIAL_CRITIC)
        }
        | {"probe:specialist": ["-", probes_module._SPECIALIST_TEMPLATE]},
    )
    assert in_force == QUALIFICATION_DIGEST


def test_a_lock_fingerprint_names_what_was_demonstrated():
    connection = ConnectionRow(
        connection_id="llc:x",
        name="ollama",
        provider_kind="OPENAI_COMPATIBLE",
        base_url="http://127.0.0.1:11434/v1",
        reach="LOCAL",
        secret_ref=None,
        secret_fingerprint=None,
        lifecycle="ENABLED",
        created_by="act:x",
        created_at=None,  # type: ignore[arg-type]
        updated_at=None,  # type: ignore[arg-type]
    )
    caps = ["CHAT", "ROLE_HYPOTHESIS", "STRUCTURED_JSON"]

    def at(n: int) -> str:
        return lock_fingerprint(
            connection, "qwen2.5:7b", caps, {"ROLE_HYPOTHESIS": {"minimum_hypotheses": n}}
        )

    assert at(5) == at(5)
    assert at(2) != at(5), "evidence for 2 and evidence for 5 are different routes"
    assert lock_fingerprint(connection, "qwen2.5:7b", caps, {}) not in (at(2), at(5))


def test_the_requirement_is_the_verticals_and_the_generic_runtime_names_none():
    # The research asks for one competing hypothesis per mechanism its DomainPack catalogues.
    assert debate_minimum(SimpleNamespace(catalog=mechanism_catalog())) == len(  # type: ignore[arg-type]
        mechanism_catalog().mechanisms
    )
    three = SimpleNamespace(catalog=SimpleNamespace(mechanisms=("a", "b", "c")))
    assert debate_minimum(three) == 3  # type: ignore[arg-type]
    # The generic LLM runtime is given the number; nothing in it imports a domain.
    from pathlib import Path

    package = Path(llm_runtime_package.__file__).parent
    for source in package.glob("*.py"):
        text = source.read_text(encoding="utf-8")
        assert "lab_brain.domains" not in text, source.name
        assert "mechanism_catalog" not in text, source.name
