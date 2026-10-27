"""G0 screening V2 closure, offline: production stays off, the screening review is qualified, and
every check is refused before execution on anything that could leave the machine or cost.

    default off      `ResearchFeatures()` and the web workspace screen nothing until enabled
    qualification    probe-8.0.0's `screening-review` case: research's own context builder, the
                     review's own contract and schema (rc-6.0.0), judged by its parser
    preflight        each fail-closed reason, read fresh at execution time: availability, action
                     type, licence, privacy, irreversibility, money, a person, a seat, the ceiling,
                     the declaration, a tool bound to a seat or to another capability, an input of
                     another project, a check the plan did not select
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest

from lab_brain.cognition.roles import SCREENING_REVIEW
from lab_brain.core.models.capability import Availability
from lab_brain.core.models.cost import CostVector
from lab_brain.domains.silicon_photonics import vertical as sp
from lab_brain.llm_runtime.contracts import (
    CONTRACTS,
    RESPONSE_CONTRACT_VERSION,
    SCHEMAS,
    SCREENING_CONTRACT,
    contract_for,
    schema_for,
)
from lab_brain.llm_runtime.probes import (
    HYPOTHESIS_SUITE,
    PROBE_VERSION,
    hypothesis_suite,
    screening_probe,
)
from lab_brain.research.service import ResearchFeatures
from lab_brain.verification.screening import RESEARCH_SCREENING_POLICY, preflight
from tests.unit.test_g0_exploratory_screening import ART, _plan, _vertical

MARKER = "\n\nCONTEXT:\n"


# -- production stays off ----------------------------------------------------------------------


def test_screening_is_off_unless_a_deployment_turns_it_on():
    assert ResearchFeatures().exploratory_screening is False
    assert ResearchFeatures().structure_context is False
    import inspect

    from lab_brain.interfaces.web.app import Workspace

    assert inspect.signature(Workspace).parameters["research_features"].default is None


# -- the screening review is qualified -----------------------------------------------------------


def _probe_context() -> dict[str, Any]:
    return dict(json.loads(screening_probe().prompt.split(MARKER, 1)[1]))


def _abnormal(ctx: dict[str, Any]) -> dict[str, Any]:
    (reading,) = [r for r in ctx["screening_observations"] if r["finding"] == "ABNORMAL"]
    return dict(reading)


def _rival(ctx: dict[str, Any], **changes: Any) -> str:
    reading = _abnormal(ctx)
    prediction = {
        "observable_ref": reading["observable_ref"],
        "outcome_space_id": reading["outcome_space_id"],
        "outcome_space_version": reading["outcome_space_version"],
    }
    evidence = ctx["evidence"][0]
    rival = {
        "key": "r",
        "statement": "Intermittent pad contact makes repeated resistor readings scatter.",
        "mechanism": "intermittent pad contact",
        "assumptions": ["the pads are worn"],
        "falsifier": "repeated readings agree",
        "falsifier_prediction_keys": ["f"],
        "confounders": ["meter noise"],
        "minimal_test_ref": reading["check"],
        "predictions": [
            {
                **prediction,
                "key": "s",
                "expected_outcome": "SCATTERED",
                "relation_effect": "SUPPORTS",
            },
            {
                **prediction,
                "key": "f",
                "expected_outcome": "REPEATABLE",
                "relation_effect": "CONTRADICTS",
            },
        ],
        "responds_to": [reading["observation_ref"]],
        "grounding_evidence_ids": [evidence["attestation_id"]],
    }
    rival.update(changes)
    return json.dumps({"hypotheses": [rival], "declined": []})


def test_the_suite_now_carries_the_screening_review_under_its_own_contract():
    assert PROBE_VERSION == "probe-8.0.0" and HYPOTHESIS_SUITE == "hypothesis-conformance@6.0.0"
    assert RESPONSE_CONTRACT_VERSION == "rc-6.0.0"
    names = [name for name, _ in hypothesis_suite(5)]
    assert names[-1] == "screening-review"
    probe = screening_probe()
    assert probe.prompt.startswith(SCREENING_REVIEW.prompt.template)
    assert probe.system == SCREENING_CONTRACT == CONTRACTS["ROLE_SCREENING_REVIEW"]
    # Research's screening call now carries the same contract and schema the probe qualified.
    assert contract_for(probe.prompt) == SCREENING_CONTRACT
    found = schema_for(probe.prompt)
    assert found is not None and found[0] == "role_screening_review"
    assert found[1] == SCHEMAS["ROLE_SCREENING_REVIEW"]
    ctx = _probe_context()
    assert {r["finding"] for r in ctx["screening_observations"]} == {"ABNORMAL", "NORMAL"}
    assert all(r["observation_ref"].startswith("O") for r in ctx["screening_observations"])
    assert "prj:" not in probe.prompt and "epi:" not in probe.prompt


def test_a_decline_and_a_grounded_rival_pass_the_screening_probe():
    ctx = _probe_context()
    judge = screening_probe().judge
    decline = {
        "hypotheses": [],
        "declined": [{"observation_ref": _abnormal(ctx)["observation_ref"], "reason": "no"}],
    }
    assert judge(json.dumps(decline)) is None
    assert judge(_rival(ctx)) is None, judge(_rival(ctx))


@pytest.mark.parametrize(
    ("change", "why"),
    [
        ("normal", "not under consideration"),
        ("unrelated_grounding", "none of which shares"),
        ("observation_as_evidence", "not under consideration"),
        ("no_answer", "unanswered"),
    ],
)
def test_a_screening_reply_outside_the_contract_fails_the_probe(change, why):
    ctx = _probe_context()
    judge = screening_probe().judge
    if change == "normal":
        (normal,) = [r for r in ctx["screening_observations"] if r["finding"] == "NORMAL"]
        reply = _rival(ctx, responds_to=[normal["observation_ref"]])
    elif change == "unrelated_grounding":
        # Evidence that shares no content word with the rival.
        # E5 (anneal, probe needles) shares no content word with the rival.
        unrelated = next(e["attestation_id"] for e in ctx["evidence"] if "annealed" in e["text"])
        reply = _rival(ctx, grounding_evidence_ids=[unrelated])
    elif change == "observation_as_evidence":
        reply = _rival(ctx, grounding_evidence_ids=[_abnormal(ctx)["observation_ref"]])
    else:
        reply = json.dumps({"hypotheses": [], "declined": []})
    failed = judge(reply)
    assert failed is not None and why in failed, failed


# -- fail closed before execution --------------------------------------------------------------


class _Registry:
    """The vertical's capability registry, with one capability's state or estimate overridden."""

    def __init__(self, inner: Any, *, estimate: CostVector | None = None, **fields: Any) -> None:
        self._inner = inner
        self._estimate = estimate
        self._fields = fields

    def get(self, capability_id: str) -> Any:
        found = self._inner.get(capability_id)
        if found is not None and capability_id == sp.CAP_INSPECT_CONNECTIVITY and self._fields:
            return found.model_copy(update=self._fields)
        return found

    def estimate(self, capability_id: str, params: Any) -> CostVector:
        if self._estimate is not None and capability_id == sp.CAP_INSPECT_CONNECTIVITY:
            return self._estimate
        cost: CostVector = self._inner.estimate(capability_id, params)
        return cost


class _Tools:
    def __init__(self, inner: Any, **override: Any) -> None:
        self._inner = inner
        self._override = override

    def descriptor(self, tool_id: str) -> Any:
        return self._inner.descriptor(tool_id).model_copy(update=self._override)


def _refusals(
    *,
    registry: Any = None,
    tools: Any = None,
    norms: Any = None,
    in_project: bool = True,
    capability_id: str = sp.CAP_INSPECT_CONNECTIVITY,
) -> list[str]:
    vertical = _vertical()
    regs = vertical.registry.registries
    plan = _plan(vertical=vertical)
    return preflight(
        capability_id=capability_id,
        plan=plan,
        capabilities=registry or regs.capabilities,
        workflows=regs.workflows,
        tools=tools or regs.tools,
        norms=vertical.screening_norms if norms is None else norms,
        policy=RESEARCH_SCREENING_POLICY,
        input_artifacts=(ART,),
        in_project=lambda _artifact, _project: in_project,
    )


def test_a_selected_local_free_check_passes_preflight():
    assert _refusals() == []


def _regs() -> Any:
    return _vertical().registry.registries


@pytest.mark.parametrize(
    ("make", "why"),
    [
        (
            lambda: {
                "registry": _Registry(_regs().capabilities, availability=Availability.DEGRADED)
            },
            "it is DEGRADED",
        ),
        (
            lambda: {"registry": _Registry(_regs().capabilities, privacy_constraints=("export",))},
            "privacy constraints",
        ),
        (lambda: {"registry": _Registry(_regs().capabilities, irreversible=True)}, "irreversible"),
        (
            lambda: {
                "registry": _Registry(
                    _regs().capabilities,
                    estimate=CostVector(wall_clock_s=2, money_estimate=Decimal("1")),
                )
            },
            "cost money",
        ),
        (
            lambda: {
                "registry": _Registry(
                    _regs().capabilities, estimate=CostVector(wall_clock_s=2, human_minutes=5)
                )
            },
            "a person",
        ),
        (
            lambda: {
                "registry": _Registry(
                    _regs().capabilities, estimate=CostVector(wall_clock_s=2, license_seat_s=2)
                )
            },
            "licence seat",
        ),
        (
            lambda: {
                "registry": _Registry(_regs().capabilities, estimate=CostVector(wall_clock_s=99))
            },
            "over the ceiling",
        ),
        (
            lambda: {"tools": _Tools(_regs().tools, resource_id="lumerical.seat")},
            "contends for resource",
        ),
        (
            lambda: {"tools": _Tools(_regs().tools, capability_id="cap:sp.charge_dc_sweep")},
            "executes another capability",
        ),
        (lambda: {"norms": {}}, "does not declare it a local reading"),
        (lambda: {"in_project": False}, "is not this project's"),
        (lambda: {"capability_id": sp.CAP_MESH_SENSITIVITY}, "its plan did not select it"),
    ],
)
def test_preflight_refuses_anything_that_could_leave_cost_or_drift(make, why):
    refusals = _refusals(**make())
    assert any(why in r for r in refusals), refusals
