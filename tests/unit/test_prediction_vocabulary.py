"""A prediction's observable is a canonical identifier the DomainPack declares, without a backend.

The verification planner matches `Prediction.observable_ref` EXACTLY against what a Capability
produces. A model shown only outcome spaces wrote a space id where the observable belongs
(`os:sp.normalization_basis` for `sp.normalization_basis`); the prediction was admitted and nothing
could ever check it. Now a DomainPack declares its prediction vocabulary -- which observable is read
in which declared space (`DisagreementMetricRegistry.declare_observable`) -- the Hypothesis Engine is
shown it, and the parser admits a prediction only over a declared binding. Proven here:

    shown          the engine's context carries the domain's (observable, space, version, outcomes)
                   bindings, and no bare outcome-space list
    refused        a space id used as the observable (the smoke's failure); a valid observable with
                   another binding's space; a legal space with another observable; a wrong version;
                   an invented observable; an outcome the bound space does not admit
    unchanged      an accepted prediction reaches the typed Prediction exactly as declared, and the
                   planner finds the capability that produces it with no normalization at all
    unavailable    an observable only a simulation could check is still a valid prediction target
    other packs    another DomainPack supplies its own vocabulary through the same registry; nothing
                   in generic cognition or the LLM runtime names a silicon-photonics observable
    declarations   the registry refuses a binding to an undeclared space, a second space for one
                   observable, and an observable that is not a canonical identifier
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import lab_brain.llm_runtime.registry as registry_module
from lab_brain.cognition.roles import (
    HYPOTHESIS_ENGINE,
    RoleOutputRefused,
    binding_context,
    parse_hypothesis_engine,
)
from lab_brain.core.models.prediction import OutcomeSpace
from lab_brain.domains.registry import DomainPackRegistry
from lab_brain.domains.silicon_photonics import SiliconPhotonicsPack
from lab_brain.llm_runtime.probes import HYPOTHESIS_SUITE, PROBE_VERSION, hypothesis_suite
from lab_brain.llm_runtime.registry import ConnectionRow, lock_fingerprint
from lab_brain.verification.disagreement import DisagreementMetricError, DisagreementMetricRegistry
from lab_brain.verification.planner import VerificationPlanner
from tests.debate_fixtures import DOMAIN, build_world
from tests.integration.test_prediction_vocabulary_postgres import OUTCOME_SPACE_ONLY_DIGEST
from tests.toy_domain import TOY_DOMAIN, TOY_OBSERVABLE_METRIC, TOY_OUTCOME_SPACE, ToyDomainPack

_MARKER = "\n\nCONTEXT:\n"


def _sp_bindings() -> dict[str, OutcomeSpace]:
    registry = DomainPackRegistry()
    registry.install(
        SiliconPhotonicsPack(runner=lambda _r: None, conditions=registry.registries.conditions)  # type: ignore[arg-type,return-value]
    )
    return registry.registries.disagreement_metrics.observable_bindings(DOMAIN)


def _reply(*predictions: tuple[str, str, str, str]) -> str:
    """Two certificates, the first carrying `predictions` (observable, space, version, outcome),
    each SUPPORTS; both designate a typed falsifier over the connectivity binding."""

    def certificate(key: str, preds: tuple[tuple[str, str, str, str], ...]) -> dict[str, Any]:
        return {
            "key": key,
            "statement": f"{key} explains the reading.",
            "mechanism": f"mechanism {key}",
            "assumptions": ["the reading is representative"],
            "falsifier": f"a check that rules out {key}",
            "falsifier_prediction_keys": ["f"],
            "confounders": ["placement"],
            "minimal_test_ref": "inspect the layout",
            "predictions": [
                *(
                    {
                        "key": f"p{n}",
                        "observable_ref": o,
                        "outcome_space_id": s,
                        "outcome_space_version": v,
                        "expected_outcome": e,
                        "relation_effect": "SUPPORTS",
                    }
                    for n, (o, s, v, e) in enumerate(preds)
                ),
                {
                    "key": "f",
                    "observable_ref": "sp.contact_connectivity",
                    "outcome_space_id": "os:sp.contact_connectivity",
                    "outcome_space_version": "1.0.0",
                    "expected_outcome": "CONTINUOUS",
                    "relation_effect": "CONTRADICTS",
                },
            ],
        }

    valid = (("sp.contact_connectivity", "os:sp.contact_connectivity", "1.0.0", "DISCONTINUOUS"),)
    return json.dumps(
        {
            "hypotheses": [certificate("h1", predictions), certificate("h2", valid)],
            "position": {"mechanism_view": "h1", "uncertainties": []},
        }
    )


def test_the_engine_is_shown_the_domains_canonical_bindings():
    world = build_world()
    world.debate.run(world.request())
    prompt = next(
        p for p in world.scientist.prompts_seen if p.startswith(HYPOTHESIS_ENGINE.prompt.template)
    )
    context = json.loads(prompt.split(_MARKER, 1)[1])
    declared = world.registries.disagreement_metrics.observable_bindings(DOMAIN)
    assert context["prediction_bindings"] == binding_context(declared)
    assert "outcome_spaces" not in context, "no bare space list to copy an observable from"
    for entry in context["prediction_bindings"]:
        assert set(entry) == {
            "observable_ref",
            "outcome_space_id",
            "outcome_space_version",
            "outcomes",
            "action_type",
        }
        assert entry["observable_ref"] != entry["outcome_space_id"]
    assert {e["observable_ref"] for e in context["prediction_bindings"]} == set(declared)


@pytest.mark.parametrize(
    ("prediction", "refusal"),
    [
        (  # the smoke's failure: the space id written where the observable belongs
            ("os:sp.normalization_basis", "os:sp.normalization_basis", "1.0.0", "DISAGREES"),
            "observable 'os:sp.normalization_basis', which is not in the prediction vocabulary",
        ),
        (  # a valid observable with another binding's space
            ("sp.contact_connectivity", "os:sp.normalization_basis", "1.0.0", "DISAGREES"),
            "reads observable 'sp.contact_connectivity' in os:sp.normalization_basis@1.0.0; it is "
            "declared in os:sp.contact_connectivity@1.0.0",
        ),
        (  # a legal space with another observable
            ("sp.normalization_basis", "os:sp.contact_connectivity", "1.0.0", "DISCONTINUOUS"),
            "reads observable 'sp.normalization_basis' in os:sp.contact_connectivity@1.0.0",
        ),
        (  # the right observable and space id at a version never declared
            ("sp.contact_connectivity", "os:sp.contact_connectivity", "2.0.0", "DISCONTINUOUS"),
            "os:sp.contact_connectivity@2.0.0, which the engine was not shown",
        ),
        (  # an observable nobody declared
            ("sp.cj_per_mm", "os:sp.contact_connectivity", "1.0.0", "DISCONTINUOUS"),
            "observable 'sp.cj_per_mm', which is not in the prediction vocabulary",
        ),
        (  # a declared binding with an outcome its space does not admit
            ("sp.contact_connectivity", "os:sp.contact_connectivity", "1.0.0", "ELEVATED"),
            "expects 'ELEVATED', which os:sp.contact_connectivity@1.0.0 does not admit",
        ),
    ],
)
def test_a_prediction_outside_the_declared_bindings_is_refused(prediction, refusal):
    with pytest.raises(RoleOutputRefused, match=r"VER-004|does not admit") as refused:
        parse_hypothesis_engine(_reply(prediction), bindings=_sp_bindings(), minimum=2)
    assert refusal in str(refused.value)


def test_an_accepted_prediction_reaches_the_planner_exactly_as_declared():
    bindings = _sp_bindings()
    proposals, _ = parse_hypothesis_engine(
        _reply(("sp.normalization_basis", "os:sp.normalization_basis", "1.0.0", "DISAGREES")),
        bindings=bindings,
        minimum=2,
    )
    first = proposals[0].predictions[0]
    assert (first.observable_ref, first.outcome_space_id, first.outcome_space_version) == (
        "sp.normalization_basis",
        "os:sp.normalization_basis",
        "1.0.0",
    ), "unchanged"
    # Through a real debate: every typed Prediction is a declared binding, and the planner matches
    # it to what a capability produces -- the same string, nothing normalised or guessed.
    world = build_world()
    outcome = world.debate.run(world.request())
    declared = world.registries.disagreement_metrics.observable_bindings(DOMAIN)
    predictions = [p for c in outcome.certificates for p in c.predictions]
    assert predictions
    for p in predictions:
        space = declared[p.observable_ref]
        assert (p.outcome_space_id, p.outcome_space_version) == (
            space.outcome_space_id,
            space.version,
        )
    planner = VerificationPlanner(world.registries.capabilities)
    for observable in {p.observable_ref for p in predictions}:
        planned = planner.plan(goal=[observable], available=world.request().available_inputs)
        assert planned and all(observable in a.capability.produces for a in planned)
    assert outcome.ranking, "Stage C ranks the actions that would check them"


def test_every_declared_observable_is_produced_by_a_capability_even_one_nobody_can_run():
    world = build_world()
    declared = world.registries.disagreement_metrics.observable_bindings(DOMAIN)
    produced = {o: c for c in world.registries.capabilities for o in c.produces}
    assert set(declared) <= set(produced), "every prediction target names what a check reads"
    # The mesh observable is read only by a simulation; it stays a valid prediction target.
    assert "sp.mesh_stability" in declared
    assert produced["sp.mesh_stability"].action_type.value == "SIMULATION"
    proposals, _ = parse_hypothesis_engine(
        _reply(("sp.mesh_stability", "os:sp.mesh_stability", "1.0.0", "UNSTABLE")),
        bindings=declared,
        minimum=2,
    )
    assert proposals[0].predictions[0].observable_ref == "sp.mesh_stability"
    planned = VerificationPlanner(world.registries.capabilities).plan(
        goal=["sp.mesh_stability"], available=world.request().available_inputs
    )
    assert [a.capability_id for a in planned] == ["cap:sp.mesh_sensitivity"]


def test_another_domain_pack_supplies_its_own_vocabulary():
    registry = DomainPackRegistry()
    registry.install(ToyDomainPack())
    toy = registry.registries.disagreement_metrics.observable_bindings(TOY_DOMAIN)
    assert {o: s.outcome_space_id for o, s in toy.items()} == {
        TOY_OBSERVABLE_METRIC: TOY_OUTCOME_SPACE
    }
    reply = json.loads(_reply())
    for certificate in reply["hypotheses"]:
        certificate["predictions"] = [
            {
                "key": key,
                "observable_ref": TOY_OBSERVABLE_METRIC,
                "outcome_space_id": TOY_OUTCOME_SPACE,
                "outcome_space_version": "1.0.0",
                "expected_outcome": outcome,
                "relation_effect": effect,
            }
            for key, outcome, effect in (("p", "STIFF", "SUPPORTS"), ("f", "BROKEN", "CONTRADICTS"))
        ]
    proposals, _ = parse_hypothesis_engine(json.dumps(reply), bindings=toy, minimum=2)
    assert proposals[0].predictions[0].observable_ref == TOY_OBSERVABLE_METRIC
    sp_prediction = ("sp.contact_connectivity", "os:sp.contact_connectivity", "1.0.0", "STIFF")
    with pytest.raises(RoleOutputRefused, match="was not shown"):
        parse_hypothesis_engine(_reply(sp_prediction), bindings=toy, minimum=2)
    # Generic cognition and the LLM runtime name no silicon-photonics observable or space.
    src = Path(__file__).parents[2] / "src" / "lab_brain"
    for package in ("cognition", "llm_runtime"):
        for source in (src / package).glob("*.py"):
            text = source.read_text(encoding="utf-8")
            assert "os:sp." not in text and "sp.contact_connectivity" not in text, source


def test_the_registry_keeps_one_space_per_observable_and_only_declared_spaces():
    registry = DomainPackRegistry()
    registry.install(ToyDomainPack())
    metrics = registry.registries.disagreement_metrics
    assert metrics.declare_observable(TOY_OBSERVABLE_METRIC, TOY_OUTCOME_SPACE, "1.0.0")
    with pytest.raises(DisagreementMetricError, match="has not been declared"):
        metrics.declare_observable("toy.other", "os:toy.undeclared", "1.0.0")
    other = OutcomeSpace(
        outcome_space_id="os:toy.second",
        version="1.0.0",
        domain=TOY_DOMAIN,
        action_type="MEASUREMENT",
        outcomes=("A", "B"),
    )
    metrics.declare_space(other)
    with pytest.raises(DisagreementMetricError, match="already read in"):
        metrics.declare_observable(TOY_OBSERVABLE_METRIC, "os:toy.second", "1.0.0")
    for bad in ("", " toy.padded"):
        with pytest.raises(DisagreementMetricError, match="canonical"):
            metrics.declare_observable(bad, "os:toy.second", "1.0.0")
    assert DisagreementMetricRegistry().observable_bindings() == {}


def test_the_route_qualified_without_the_vocabulary_is_no_longer_current(monkeypatch):
    # The coder route the LOCAL deployment locked under the outcome-space-only contract, recomputed
    # from its public parts: that route under the previous semantics, not under the vocabulary's.
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
        "CODE",
        "ROLE_CRITIQUE",
        "ROLE_HYPOTHESIS",
        "ROLE_QUERY",
        "ROLE_SPECIALIST",
        "STRUCTURED_JSON",
    ]
    suite = {"minimum_hypotheses": 5, "suite": "hypothesis-conformance@1.0.0"}
    shown = {"ROLE_HYPOTHESIS": {**suite, "cases": ["contextual-minimum", "multi-space"]}}
    assert lock_fingerprint(ollama, "qwen2.5-coder:7b", caps, shown) != "lk:963d70828be54b8e"
    monkeypatch.setattr(registry_module, "QUALIFICATION_DIGEST", OUTCOME_SPACE_ONLY_DIGEST)
    assert lock_fingerprint(ollama, "qwen2.5-coder:7b", caps, shown) == "lk:963d70828be54b8e"
    assert (HYPOTHESIS_ENGINE.prompt.prompt_version, PROBE_VERSION) == ("4.0.0", "probe-5.0.0")
    assert HYPOTHESIS_SUITE == "hypothesis-conformance@3.0.0"


def test_the_qualification_suite_declares_observables_that_are_not_their_spaces():
    for name, case in hypothesis_suite(5):
        entries = json.loads(case.prompt.split(_MARKER, 1)[1])["prediction_bindings"]
        assert entries, name
        for entry in entries:
            space, observable = entry["outcome_space_id"], entry["observable_ref"]
            assert observable not in (space, space.removeprefix("os:")), (name, entry)
        # Copying each entry's space id into observable_ref is refused, case by case.
        copied = json.dumps(
            {
                "hypotheses": [
                    {
                        "key": f"h{n}",
                        "statement": "s",
                        "mechanism": f"m{n}",
                        "assumptions": ["a"],
                        "falsifier": "f",
                        "confounders": ["c"],
                        "minimal_test_ref": "t",
                        "falsifier_prediction_keys": ["p"],
                        "predictions": [
                            {
                                "key": "p",
                                "observable_ref": entries[0]["outcome_space_id"],
                                "outcome_space_id": entries[0]["outcome_space_id"],
                                "outcome_space_version": entries[0]["outcome_space_version"],
                                "expected_outcome": entries[0]["outcomes"][0],
                                "relation_effect": "SUPPORTS",
                            }
                        ],
                    }
                    for n in range(5)
                ],
                "position": {"mechanism_view": "m0", "uncertainties": []},
            }
        )
        assert "not in the prediction vocabulary" in str(case.judge(copied)), name
