"""The prediction effects are defined for the model that declares them, and the definitions are true.

A deployed route proposed the right mechanism, declared its discriminating forecast as PREDICTS, and
the check observed exactly that outcome: the PREDICTS relation was recorded and no transition
followed -- correctly, since only SUPPORTS is support -- and the model had been given the four effect
names and no meaning. Now (prompt 5.0.0, rc-4.0.0, probe-6.0.0) the meanings are stated, from one
source, and held true:

    meanings       every prediction effect has exactly one meaning, and the prompt renders each one
    the claim      "SUPPORTS is the only support, CONTRADICTS the only refutation" is a fact of this
                   product: every TransitionPolicy it constructs requires only those two, and a
                   policy that raises belief requires SUPPORTS, one that lowers it CONTRADICTS
    no promotion   a PREDICTS forecast is admitted as PREDICTS and instantiates PREDICTS -- nothing
                   turns it into support
    support        is never required: a falsification-only certificate is admitted, and passes the
                   qualification suite
    coherence      one outcome of an observable takes one effect within a hypothesis; a certificate
                   that gives it two is refused, at admission and in qualification
    qualification  the locks the deployment holds, made under the typed-falsifier semantics, are no
                   longer current

The same distinction through PostgreSQL and the web workspace -- a PREDICTS observation recorded and
moving nothing, a SUPPORTS one promoting through a governed decision, falsifiers alone confirming
nothing -- is `tests/e2e/test_web_prediction_effects_postgres.py`.
"""

from __future__ import annotations

import ast
import json
import pathlib
from typing import Any

import pytest

import lab_brain
import lab_brain.llm_runtime.registry as registry_module
from lab_brain.cognition.roles import HYPOTHESIS_ENGINE, RoleOutputRefused, parse_hypothesis_engine
from lab_brain.core.models.belief_event import BeliefState
from lab_brain.core.models.enums import RelationType
from lab_brain.core.models.prediction import (
    PREDICTION_EFFECT_MEANINGS,
    PREDICTION_EFFECT_TYPES,
    OutcomeSpace,
)
from lab_brain.domains.silicon_photonics.authority_policy import transition_policies
from lab_brain.domains.silicon_photonics.vertical import (
    diagnosis_targets,
    vertical_transition_policies,
)
from lab_brain.llm_runtime.contracts import HYPOTHESIS_CONTRACT, RESPONSE_CONTRACT_VERSION
from lab_brain.llm_runtime.probes import (
    HYPOTHESIS_SUITE,
    PROBE_VERSION,
    QUALIFICATION_DIGEST,
    hypothesis_suite,
)
from lab_brain.llm_runtime.registry import ConnectionRow, lock_fingerprint
from lab_brain.research.service import ADMISSION_POLICY

#: `QUALIFICATION_DIGEST` under the typed falsifier (probe-5.0.0, prompt 4.0.0, rc-3.0.0): the
#: semantics every lock the deployment holds was made under.
TYPED_FALSIFIER_DIGEST = "43ce474f374e950b910721dffc563cf0f79ccdeebf67a717857e6bae2bb3b44e"
_MARKER = "\n\nCONTEXT:\n"
SUPPORT_OR_REFUTATION = {RelationType.SUPPORTS, RelationType.CONTRADICTS}

#: A domain that is not silicon photonics: the rules are generic.
_SPACE = OutcomeSpace(
    outcome_space_id="os:toy.reading",
    version="1.0.0",
    domain="toy",
    action_type="MEASUREMENT",
    outcomes=("HIGH", "NOMINAL", "LOW"),
)
BINDINGS = {"bench.reading": _SPACE}


def _p(key: str, outcome: str, effect: str) -> dict[str, str]:
    return {
        "key": key,
        "observable_ref": "bench.reading",
        "outcome_space_id": _SPACE.outcome_space_id,
        "outcome_space_version": _SPACE.version,
        "expected_outcome": outcome,
        "relation_effect": effect,
    }


def _reply(predictions: list[dict[str, str]], falsifiers: list[str], n: int = 2) -> str:
    return json.dumps(
        {
            "hypotheses": [
                {
                    "key": f"h{i}",
                    "statement": f"mechanism {i} explains the reading",
                    "mechanism": f"m{i}",
                    "assumptions": [],
                    "falsifier": "the reading is otherwise",
                    "falsifier_prediction_keys": falsifiers,
                    "confounders": [],
                    "minimal_test_ref": "bench.reading",
                    "predictions": predictions,
                }
                for i in range(n)
            ],
            "position": {"mechanism_view": "m0", "uncertainties": []},
        }
    )


# -- the meanings ---------------------------------------------------------------------------------


def test_every_prediction_effect_has_exactly_one_meaning_and_the_prompt_renders_each():
    assert set(PREDICTION_EFFECT_MEANINGS) == set(PREDICTION_EFFECT_TYPES)
    template = HYPOTHESIS_ENGINE.prompt.template
    for effect, meaning in PREDICTION_EFFECT_MEANINGS.items():
        assert f"{effect.value} means: {meaning}." in template, effect
    assert "Declare SUPPORTS only for an outcome that would discriminate" in template
    assert "give it falsifiers only -- never a SUPPORTS it has not earned" in template
    assert "never declare the same outcome of an observable with different" in template


def test_the_contract_says_which_effects_are_support_and_refutation_and_that_support_is_optional():
    assert RESPONSE_CONTRACT_VERSION == "rc-5.0.0"
    assert HYPOTHESIS_ENGINE.prompt.prompt_version == "5.0.0"
    assert (
        "SUPPORTS is the only effect counted as support and CONTRADICTS the only one counted as "
        "refutation; PREDICTS and TESTS are recorded and are neither" in HYPOTHESIS_CONTRACT
    )
    assert "A hypothesis need not have a SUPPORTS prediction" in HYPOTHESIS_CONTRACT
    assert (
        "the same outcome of the same observable takes one relation_effect" in HYPOTHESIS_CONTRACT
    )


# -- the claim is a fact of this product ----------------------------------------------------------


def test_every_policy_the_product_registers_reads_only_support_or_refutation():
    registered = [*transition_policies(), *vertical_transition_policies(), ADMISSION_POLICY]
    registered += [policy for policy, _ in diagnosis_targets()]
    for policy in registered:
        required = set(policy.required_relation_types)
        assert required <= SUPPORT_OR_REFUTATION, (policy.policy_id, required)
        if policy.candidate_to_state is BeliefState.SUPPORTED:
            assert RelationType.SUPPORTS in required, policy.policy_id
        if policy.candidate_to_state in (BeliefState.CONTRADICTED, BeliefState.CHALLENGED):
            assert RelationType.CONTRADICTS in required, policy.policy_id


def test_no_transition_policy_anywhere_in_the_source_requires_predicts_or_tests():
    """Every `TransitionPolicy(...)` the source constructs, found by reading it -- so a policy added
    later that made PREDICTS or TESTS move belief fails here, and the contract's words with it."""
    root = pathlib.Path(lab_brain.__file__).parent
    found = 0
    for path in sorted(root.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name != "TransitionPolicy":
                continue
            found += 1
            for keyword in node.keywords:
                if keyword.arg != "required_relation_types":
                    continue
                assert isinstance(keyword.value, ast.Tuple), (path, keyword.value.lineno)
                for element in keyword.value.elts:
                    assert isinstance(element, ast.Attribute), (path, element.lineno)
                    assert element.attr in {"SUPPORTS", "CONTRADICTS"}, (path, element.lineno)
    assert found >= 5


# -- the parser: no promotion, support optional, one outcome one effect ----------------------------


def test_a_predicts_forecast_stays_predicts():
    proposals, _ = parse_hypothesis_engine(
        _reply([_p("f", "HIGH", "PREDICTS"), _p("x", "LOW", "CONTRADICTS")], ["x"]),
        bindings=BINDINGS,
        minimum=2,
    )
    for proposal in proposals:
        effects = {p.expected_outcome: p.relation_effect for p in proposal.predictions}
        assert effects == {"HIGH": RelationType.PREDICTS, "LOW": RelationType.CONTRADICTS}


def test_a_falsification_only_certificate_is_admitted():
    proposals, _ = parse_hypothesis_engine(
        _reply([_p("x", "LOW", "CONTRADICTS"), _p("y", "NOMINAL", "CONTRADICTS")], ["x", "y"]),
        bindings=BINDINGS,
        minimum=2,
    )
    assert all(
        {p.relation_effect for p in proposal.predictions} == {RelationType.CONTRADICTS}
        for proposal in proposals
    )


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("SUPPORTS", "CONTRADICTS"),
        ("PREDICTS", "CONTRADICTS"),
        ("SUPPORTS", "PREDICTS"),
        ("TESTS", "SUPPORTS"),
    ],
)
def test_one_outcome_given_two_effects_is_refused(first: str, second: str):
    reply = _reply(
        [_p("a", "HIGH", first), _p("b", "HIGH", second), _p("x", "LOW", "CONTRADICTS")],
        ["x"] if second != "CONTRADICTS" else ["b"],
    )
    with pytest.raises(RoleOutputRefused, match="an outcome has one meaning for a hypothesis"):
        parse_hypothesis_engine(reply, bindings=BINDINGS, minimum=2)


def test_different_outcomes_of_one_observable_take_different_effects():
    proposals, _ = parse_hypothesis_engine(
        _reply(
            [
                _p("s", "HIGH", "SUPPORTS"),
                _p("p", "NOMINAL", "PREDICTS"),
                _p("x", "LOW", "CONTRADICTS"),
            ],
            ["x"],
        ),
        bindings=BINDINGS,
        minimum=2,
    )
    assert len(proposals) == 2


# -- qualification ---------------------------------------------------------------------------------


def _suite_reply(entries: list[dict[str, Any]], shape: str) -> str:
    """Five certificates over the case's first binding, in one `shape`."""
    entry = entries[0]

    def p(key: str, outcome: str, effect: str) -> dict[str, str]:
        return {
            "key": key,
            "observable_ref": entry["observable_ref"],
            "outcome_space_id": entry["outcome_space_id"],
            "outcome_space_version": entry["outcome_space_version"],
            "expected_outcome": outcome,
            "relation_effect": effect,
        }

    first, last = entry["outcomes"][0], entry["outcomes"][-1]
    predictions, falsifiers = {
        "falsifiers-only": ([p("f", last, "CONTRADICTS")], ["f"]),
        "forecast-predicts": ([p("s", first, "PREDICTS"), p("f", last, "CONTRADICTS")], ["f"]),
        "incoherent": ([p("s", last, "SUPPORTS"), p("f", last, "CONTRADICTS")], ["f"]),
    }[shape]
    return json.dumps(
        {
            "hypotheses": [
                {
                    "key": f"h{n}",
                    "statement": f"mechanism {n}",
                    "mechanism": f"m{n}",
                    "assumptions": [],
                    "falsifier": "otherwise",
                    "falsifier_prediction_keys": falsifiers,
                    "confounders": [],
                    "minimal_test_ref": "a check",
                    "predictions": predictions,
                }
                for n in range(5)
            ],
            "position": {"mechanism_view": "m0", "uncertainties": []},
        }
    )


def test_the_suite_passes_falsifiers_alone_and_a_predicts_forecast_and_fails_an_incoherent_one():
    assert (PROBE_VERSION, HYPOTHESIS_SUITE) == ("probe-7.0.0", "hypothesis-conformance@5.0.0")
    for name, case in hypothesis_suite(5):
        if name == "coverage-review":  # its own contract; its certificates are checked alike
            continue
        entries = json.loads(case.prompt.split(_MARKER, 1)[1])["prediction_bindings"]
        assert case.judge(_suite_reply(entries, "falsifiers-only")) is None, name
        assert case.judge(_suite_reply(entries, "forecast-predicts")) is None, name
        failed = case.judge(_suite_reply(entries, "incoherent"))
        assert failed is not None and "one meaning for a hypothesis" in failed, (name, failed)
        assert case.system == HYPOTHESIS_CONTRACT and "SUPPORTS means:" in case.prompt


def test_the_locks_the_deployment_holds_are_no_longer_current(monkeypatch):
    assert QUALIFICATION_DIGEST != TYPED_FALSIFIER_DIGEST

    def connection(url: str, reach: str) -> ConnectionRow:
        return ConnectionRow(
            "llc:x",
            "x",
            "OPENAI_COMPATIBLE",
            url,
            reach,
            None,
            None,
            "ENABLED",
            "act:x",
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
        )

    ollama = connection("http://host.docker.internal:11434/v1", "LOCAL")
    gemini = connection("https://generativelanguage.googleapis.com/v1beta/openai", "EXTERNAL")
    shown = {
        "ROLE_HYPOTHESIS": {
            "cases": ["contextual-minimum", "multi-space"],
            "suite": "hypothesis-conformance@3.0.0",
            "minimum_hypotheses": 5,
        }
    }
    roles = ["CHAT", "ROLE_QUERY", "ROLE_SPECIALIST", "STRUCTURED_JSON"]
    locks = (
        (
            ollama,
            "qwen2.5-coder:7b",
            [*roles, "CODE", "ROLE_CRITIQUE", "ROLE_HYPOTHESIS"],
            shown,
            "lk:06d7d886bcb85a5a",
        ),
        (ollama, "qwen2.5:7b", [*roles, "ROLE_CRITIQUE"], {}, "lk:271a4fad2094aab1"),
        (
            gemini,
            "models/gemini-3.1-pro-preview",
            [*roles, "CODE", "ROLE_HYPOTHESIS", "VISION"],
            shown,
            "lk:665f375910cc4d84",
        ),
    )
    for conn, model, caps, qualification, fingerprint in locks:
        assert lock_fingerprint(conn, model, caps, qualification) != fingerprint
    monkeypatch.setattr(registry_module, "QUALIFICATION_DIGEST", TYPED_FALSIFIER_DIGEST)
    for conn, model, caps, qualification, fingerprint in locks:
        assert lock_fingerprint(conn, model, caps, qualification) == fingerprint
