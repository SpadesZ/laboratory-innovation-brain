"""Exploratory screening, offline: the selection policy, the records, the review's parser, the
grounding-relevance rule, overlap reporting, the Critic's reserve and the structure summary.

    selection    only observables no rival discriminates on; only declared, cheap, local, available
                 checks with a workflow and their inputs; ordered by cost then id; cut by count and
                 by stage budget; a reading already taken is not taken again; the device is not an
                 input at all
    records      a reading's finding follows from outcome vs reference; an executed reading names
                 its Run; nothing unexecuted observed anything
    review       every abnormal reading answered once; a rival must say what that reading means,
                 cite shown evidence that shares words with it, and may not respond to a normal
                 reading or cite the reading as evidence
    debate       a screening stage runs after the coverage review and before the Critic, its rival
                 is conditioned on the reading and critiqued; a normal-only stage asks nothing
    reserve      an optional call that would leave the Critic short is withheld and recorded, and
                 the Critic still runs
    structure    design fields only, with pointers and units; an answer-like field is refused
"""

from __future__ import annotations

import datetime as dt
import inspect
import json
from collections.abc import Mapping, Sequence
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Any

import pytest

from lab_brain.cognition.aliases import AliasTable
from lab_brain.cognition.overlap import overlapping_pairs
from lab_brain.cognition.roles import (
    RoleOutputRefused,
    content_terms,
    parse_coverage_review,
    parse_screening_review,
)
from lab_brain.core.models.capability import Availability
from lab_brain.core.models.cost import CostVector
from lab_brain.core.models.hypothesis_set import HypothesisCertificate
from lab_brain.core.models.screening import (
    CandidateDisposition,
    ConditionedHypothesis,
    ScreeningObservation,
    ScreeningPlan,
    ScreeningPolicy,
    ScreeningReading,
    ScreeningStatus,
    inputs_key,
)
from lab_brain.domains.silicon_photonics import vertical as sp
from lab_brain.domains.silicon_photonics.diagnosis import DesignError, DeviceProject
from lab_brain.domains.silicon_photonics.product import product_vertical
from lab_brain.domains.silicon_photonics.structure import screening_norms, structure_summary
from lab_brain.domains.silicon_photonics.tools import INPUT_DEVICE_PROJECT
from lab_brain.research.structure import StructureEntry, StructureSummary
from lab_brain.verification.screening import (
    RESEARCH_SCREENING_POLICY,
    ScreeningOutcome,
    select_screening,
)
from tests.debate_fixtures import evidence_items, load_fixture
from tests.unit.test_g0_reliability import (
    _context,
    _coverage,
    _engine_without_connectivity,
    _scientist,
    _world,
)

NOW = dt.datetime(2026, 10, 27, 9, 0, tzinfo=dt.UTC)
ART = "art:" + "a" * 64


def _vertical() -> Any:
    return product_vertical(outputs=None, jobs=None, broker=None, now=lambda: NOW)


def _bindings(vertical: Any) -> Mapping[str, Any]:
    return vertical.registry.registries.disagreement_metrics.observable_bindings(vertical.domain)


def _plan(
    certificates: Sequence[HypothesisCertificate] = (),
    *,
    policy: ScreeningPolicy = RESEARCH_SCREENING_POLICY,
    already: frozenset[str] = frozenset(),
    vertical: Any = None,
) -> ScreeningPlan:
    vertical = vertical or _vertical()
    regs = vertical.registry.registries
    return select_screening(
        plan_id="spl:1",
        project_id="prj:1",
        episode_id="epi:1",
        trace_id="trc:1",
        actor_id="act:1",
        hypothesis_set_id="hst:1",
        certificates=certificates,
        bindings=_bindings(vertical),
        capabilities=regs.capabilities,
        workflows=regs.workflows,
        norms=vertical.screening_norms,
        available_inputs=frozenset({INPUT_DEVICE_PROJECT}),
        input_artifacts=(ART,),
        already_screened=already,
        policy=policy,
        now=NOW,
    )


def _dispositions(plan: ScreeningPlan) -> dict[str, CandidateDisposition]:
    return {c.capability_id: c.disposition for c in plan.candidates}


# -- selection -------------------------------------------------------------------------------------


def test_with_no_rival_the_two_declared_readings_are_selected_cheapest_then_by_id():
    plan = _plan()
    assert [c.capability_id for c in plan.selected] == [
        sp.CAP_EXTRACTION_CONSISTENCY,
        sp.CAP_INSPECT_CONNECTIVITY,
    ]
    found = _dispositions(plan)
    # Everything else is considered and refused with the FIRST rule it fails.
    assert found[sp.CAP_MESH_SENSITIVITY] is CandidateDisposition.NOT_DECLARED_FOR_SCREENING
    assert found[sp.CAP_FOURPOINT_PROBE] is CandidateDisposition.NOT_DECLARED_FOR_SCREENING
    assert found[sp.CAP_FABRICATE_SPLIT] is CandidateDisposition.NOT_DECLARED_FOR_SCREENING
    assert all(c.detail for c in plan.candidates)
    assert plan.policy_id == "screening:research-run" and plan.policy_version == "1.0.0"


def test_an_observable_some_rival_discriminates_on_is_left_to_verification():
    world = _world(_scientist(_engine_without_connectivity))
    outcome = world.debate.run(world.request())
    plan = _plan(outcome.certificates)
    assert _dispositions(plan)[sp.CAP_EXTRACTION_CONSISTENCY] is (
        CandidateDisposition.ADDRESSED_BY_HYPOTHESIS
    )
    assert [c.capability_id for c in plan.selected] == [sp.CAP_INSPECT_CONNECTIVITY]
    assert sp.OBS_NORMALIZATION not in plan.unaddressed_observables


def test_the_count_and_the_stage_budget_cut_the_cheapest_first_list():
    one = ScreeningPolicy(
        policy_id="p", version="1", max_checks=1, max_wall_clock_s=60, max_check_wall_clock_s=10
    )
    assert _dispositions(_plan(policy=one))[sp.CAP_INSPECT_CONNECTIVITY] is (
        CandidateDisposition.OVER_MAX_CHECKS
    )
    tight = ScreeningPolicy(
        policy_id="p", version="1", max_checks=5, max_wall_clock_s=3, max_check_wall_clock_s=3
    )
    assert _dispositions(_plan(policy=tight))[sp.CAP_INSPECT_CONNECTIVITY] is (
        CandidateDisposition.OVER_STAGE_BUDGET
    )
    ceiling = ScreeningPolicy(
        policy_id="p", version="1", max_checks=5, max_wall_clock_s=3, max_check_wall_clock_s=1
    )
    assert not _plan(policy=ceiling).selected
    assert set(_dispositions(_plan(policy=ceiling)).values()) >= {
        CandidateDisposition.OVER_CHECK_CEILING
    }


def test_a_reading_already_taken_on_the_same_input_is_not_taken_again():
    taken = frozenset({inputs_key(sp.CAP_INSPECT_CONNECTIVITY, (ART,))})
    plan = _plan(already=taken)
    assert _dispositions(plan)[sp.CAP_INSPECT_CONNECTIVITY] is CandidateDisposition.ALREADY_SCREENED
    # Another input is another reading.
    assert inputs_key(sp.CAP_INSPECT_CONNECTIVITY, ("art:" + "b" * 64,)) not in taken


def test_an_unavailable_reader_is_never_screened():
    vertical = _vertical()
    vertical.registry.registries.capabilities.set_availability(
        sp.CAP_INSPECT_CONNECTIVITY, Availability.UNAVAILABLE
    )
    plan = _plan(vertical=vertical)
    assert _dispositions(plan)[sp.CAP_INSPECT_CONNECTIVITY] is CandidateDisposition.UNAVAILABLE
    vertical.registry.registries.capabilities.set_availability(
        sp.CAP_INSPECT_CONNECTIVITY, Availability.DEGRADED
    )
    assert not any(
        c.capability_id == sp.CAP_INSPECT_CONNECTIVITY for c in _plan(vertical=vertical).selected
    )


def test_selection_cannot_read_the_device_and_is_the_same_for_every_device():
    """No parameter carries content: only artifact ids, input kinds, rivals and descriptors."""
    params = set(inspect.signature(select_screening).parameters)
    assert not params & {"device", "data", "content", "case", "truth", "expected", "label"}
    assert _plan().model_dump(exclude={"created_at"}) == _plan().model_dump(exclude={"created_at"})


def test_the_policy_bounds_are_checked():
    with pytest.raises(ValueError, match="per-check ceiling"):
        ScreeningPolicy(
            policy_id="p", version="1", max_checks=1, max_wall_clock_s=5, max_check_wall_clock_s=9
        )
    with pytest.raises(ValueError):
        ScreeningPolicy(
            policy_id="p", version="1", max_checks=9, max_wall_clock_s=5, max_check_wall_clock_s=1
        )


def test_the_screening_norms_are_the_same_reference_for_every_device():
    norms = screening_norms()
    assert set(norms) == {sp.CAP_INSPECT_CONNECTIVITY, sp.CAP_EXTRACTION_CONSISTENCY}
    assert norms[sp.CAP_INSPECT_CONNECTIVITY].reference_outcomes == {
        sp.OBS_CONNECTIVITY: "CONTINUOUS"
    }
    assert norms[sp.CAP_EXTRACTION_CONSISTENCY].reference_outcomes == {
        sp.OBS_NORMALIZATION: "AGREES"
    }


# -- records ---------------------------------------------------------------------------------------


def _reading(outcome: str, finding: str = "ABNORMAL") -> ScreeningReading:
    return ScreeningReading(
        observable_ref=sp.OBS_CONNECTIVITY,
        outcome_space_id=sp.SPACE_CONNECTIVITY,
        outcome_space_version="1.0.0",
        outcome=outcome,
        reference_outcome="CONTINUOUS",
        finding=finding,  # type: ignore[arg-type]
        observation_id="obs:1",
        attestation_id="att:1",
        method_ref="sp.rule.contact_connectivity@1.0.0",
    )


def test_a_readings_finding_follows_from_its_outcome_and_reference():
    assert _reading("DISCONTINUOUS").finding.value == "ABNORMAL"
    with pytest.raises(ValueError, match="is NORMAL, not ABNORMAL"):
        _reading("CONTINUOUS", "ABNORMAL")
    with pytest.raises(ValueError, match="is ABNORMAL, not NORMAL"):
        _reading("DISCONTINUOUS", "NORMAL")


def test_an_executed_reading_names_its_run_and_nothing_else_observed_anything():
    base = {
        "screening_observation_id": "sob:1",
        "plan_id": "spl:1",
        "project_id": "prj:1",
        "episode_id": "epi:1",
        "rank": 1,
        "capability_id": sp.CAP_INSPECT_CONNECTIVITY,
        "estimated_cost": CostVector(wall_clock_s=2),
        "recorded_at": NOW,
    }
    with pytest.raises(ValueError, match="without a Run"):
        ScreeningObservation(**base, status=ScreeningStatus.EXECUTED)
    with pytest.raises(ValueError, match="nothing executed"):
        ScreeningObservation(
            **base, status=ScreeningStatus.FAILED, readings=(_reading("DISCONTINUOUS"),)
        )
    ok = ScreeningObservation(
        **base,
        status=ScreeningStatus.EXECUTED,
        run_id="run:1",
        evidence_line="line",
        readings=(_reading("DISCONTINUOUS"),),
    )
    assert ok.abnormal == ok.readings


# -- the screening review's parser ---------------------------------------------------------------

_E = AliasTable("E").shown(["att:contact", "att:table"])
_O = AliasTable("O").shown(["obs:open", "obs:norm"])
_TEXTS = {
    "att:contact": "The measured behaviour is consistent with a contact-resistance contribution",
    "att:table": "| Bias | Cj | Rs | Split |",
}


def _screen_reply(**changes: Any) -> dict[str, Any]:
    space = sp.SPACE_CONNECTIVITY
    rival = {
        "key": "v",
        "statement": "A contact via does not reach metal, so the contact path is cut.",
        "mechanism": "broken contact via",
        "assumptions": ["the drawing is the device"],
        "falsifier": "every contact is tied",
        "falsifier_prediction_keys": ["f"],
        "confounders": ["probe contact"],
        "minimal_test_ref": sp.CAP_INSPECT_CONNECTIVITY,
        "predictions": [
            {
                "key": "s",
                "observable_ref": sp.OBS_CONNECTIVITY,
                "outcome_space_id": space,
                "outcome_space_version": "1.0.0",
                "expected_outcome": "DISCONTINUOUS",
                "relation_effect": "SUPPORTS",
            },
            {
                "key": "f",
                "observable_ref": sp.OBS_CONNECTIVITY,
                "outcome_space_id": space,
                "outcome_space_version": "1.0.0",
                "expected_outcome": "CONTINUOUS",
                "relation_effect": "CONTRADICTS",
            },
        ],
        "responds_to": ["O1"],
        "grounding_evidence_ids": ["E1"],
    }
    rival.update(changes)
    return {"hypotheses": [rival], "declined": []}


def _screen(reply: dict[str, Any], abnormal: Mapping[str, str] | None = None) -> Any:
    return parse_screening_review(
        json.dumps(reply),
        bindings=_bindings(_vertical()),
        abnormal=abnormal if abnormal is not None else {"obs:open": sp.OBS_CONNECTIVITY},
        existing_mechanisms=["process contact resistance"],
        evidence_refs=_E,
        observation_refs=_O,
        shown_attestation_ids=["att:contact", "att:table"],
        evidence_texts=_TEXTS,
    )


def test_a_rival_accounting_for_an_abnormal_reading_is_read_with_its_grounds_and_overlap():
    draft = _screen(_screen_reply())
    assert draft.responds_to == {"v": ("obs:open",)}
    assert draft.grounding == {"v": ("att:contact",)}
    assert "contact" in draft.relevance["v"]["att:contact"]


def test_declining_the_abnormal_reading_is_a_complete_reply():
    draft = _screen({"hypotheses": [], "declined": [{"observation_ref": "O1", "reason": "no"}]})
    assert not draft.proposals and draft.declined[0].observation == "obs:open"


@pytest.mark.parametrize(
    ("reply", "why"),
    [
        (_screen_reply(grounding_evidence_ids=["E2"]), "none of which shares"),
        (_screen_reply(responds_to=["O2"]), "not under consideration"),
        (_screen_reply(responds_to=[]), "names no abnormal reading"),
        (_screen_reply(grounding_evidence_ids=["O1"]), "not under consideration"),
        (_screen_reply(grounding_evidence_ids=[]), "cites no evidence"),
        (_screen_reply(mechanism="process contact resistance"), "already under consideration"),
        ({"hypotheses": [], "declined": []}, "unanswered"),
    ],
)
def test_a_screening_reply_outside_its_contract_is_refused(reply, why):
    with pytest.raises(RoleOutputRefused, match=why):
        _screen(reply)


def test_a_rival_must_say_what_the_reading_it_answers_means():
    reply = _screen_reply()
    imp = ("sp.small_signal_impedance", "os:sp.rs_bias_response", "1.0.0")
    reply["hypotheses"][0]["predictions"] = [
        {
            "key": k,
            "observable_ref": imp[0],
            "outcome_space_id": imp[1],
            "outcome_space_version": imp[2],
            "expected_outcome": o,
            "relation_effect": e,
        }
        for k, o, e in (
            ("s", "RS_BIAS_INSENSITIVE", "SUPPORTS"),
            ("f", "RS_FALLS_WITH_REVERSE_BIAS", "CONTRADICTS"),
        )
    ]
    with pytest.raises(RoleOutputRefused, match="makes no SUPPORTS or CONTRADICTS prediction"):
        _screen(reply)


def test_a_coverage_rival_must_cite_evidence_about_its_mechanism():
    reply = _screen_reply(grounding_evidence_ids=["E2"])
    reply["hypotheses"][0].pop("responds_to")
    with pytest.raises(RoleOutputRefused, match="none of which shares"):
        parse_coverage_review(
            json.dumps(reply),
            bindings=_bindings(_vertical()),
            unaddressed=[sp.OBS_CONNECTIVITY],
            existing_mechanisms=[],
            evidence_refs=_E,
            shown_attestation_ids=["att:contact", "att:table"],
            evidence_texts=_TEXTS,
        )


def test_content_terms_drop_function_words_and_fold_plurals():
    assert content_terms("The contacts of the via") == {"contact", "via"}
    assert "the" not in content_terms("the and of")


# -- the stage inside a debate -------------------------------------------------------------------


@dataclass
class FakeStage:
    """A `ScreeningHook` with readings decided by the test, never by a device."""

    outcomes: dict[str, str]
    #: The attestation each reading was admitted as; one the world knows, unless a test says not.
    attestation_id: str = ""
    conditioned: list[ConditionedHypothesis] = field(default_factory=list)
    screened: list[tuple[str, ...]] = field(default_factory=list)

    def screen(self, *, hypothesis_set_id: str, certificates: Any, bindings: Any) -> Any:
        self.screened.append(tuple(sorted(c.hypothesis_id for c in certificates)))
        plan = _plan(certificates)
        observations = []
        for c in plan.selected:
            (observable,) = c.observables
            reference = screening_norms()[c.capability_id].reference_outcomes[observable]
            outcome = self.outcomes.get(observable, reference)
            space, version = sp.space_for(observable) or ("", "")
            observations.append(
                ScreeningObservation(
                    screening_observation_id=f"sob:{c.rank}",
                    plan_id=plan.plan_id,
                    project_id="prj:1",
                    episode_id="epi:1",
                    rank=c.rank or 0,
                    capability_id=c.capability_id,
                    status=ScreeningStatus.EXECUTED,
                    run_id=f"run:{c.rank}",
                    evidence_line=f"line:{c.rank}",
                    estimated_cost=c.estimated_cost,
                    readings=(
                        ScreeningReading(
                            observable_ref=observable,
                            outcome_space_id=space,
                            outcome_space_version=version,
                            outcome=outcome,
                            reference_outcome=reference,
                            finding="NORMAL" if outcome == reference else "ABNORMAL",  # type: ignore[arg-type]
                            observation_id=f"obs:{c.rank}",
                            attestation_id=self.attestation_id or f"att:screen-{c.rank}",
                            method_ref="rule@1.0.0",
                        ),
                    ),
                    recorded_at=NOW,
                )
            )
        return ScreeningOutcome(plan=plan, observations=tuple(observations))

    def condition(self, **kwargs: Any) -> object:
        record = ConditionedHypothesis(
            project_id="prj:1", episode_id="epi:1", recorded_at=NOW, **kwargs
        )
        self.conditioned.append(record)
        return record

    def atomic(self) -> Any:
        return nullcontext()


def _screening_reply(ctx: dict[str, Any]) -> dict[str, Any]:
    (abnormal,) = [o for o in ctx["screening_observations"] if o["finding"] == "ABNORMAL"]
    reply = _screen_reply(responds_to=[abnormal["observation_ref"]])
    reply["hypotheses"][0]["grounding_evidence_ids"] = [
        e["attestation_id"] for e in ctx["evidence"] if "contact" in e["text"].lower()
    ][:1]
    return reply


def _screening_edit(material: str, ctx: dict[str, Any], _: int) -> str | None:
    if material.startswith("You are the Hypothesis Engine. Low-cost exploratory readings"):
        return json.dumps(_screening_reply(ctx))
    return None


def _decline_all(ctx: dict[str, Any]) -> dict[str, Any]:
    return {
        "hypotheses": [],
        "declined": [
            {"observable_ref": c["observable_ref"], "reason": "nothing points there"}
            for c in ctx["unaddressed_checks"]
        ],
    }


def _known_attestation() -> str:
    return evidence_items(load_fixture()["cases"][0])[0].attestation_id


def test_an_abnormal_reading_adds_one_conditioned_rival_that_the_critic_then_sees():
    scientist = _scientist(_engine_without_connectivity, _coverage(_decline_all), _screening_edit)
    world = _world(scientist, coverage_review=True, screening=True)
    stage = FakeStage({sp.OBS_CONNECTIVITY: "DISCONTINUOUS"}, _known_attestation())
    outcome = world.debate.run(world.request(screening=stage))
    screening = outcome.record.reliability["screening"]
    assert screening["status"] == "DONE" and screening["review"]["status"] == "DONE"
    (added,) = [c for c in outcome.certificates if c.hypothesis.mechanism == "broken contact via"]
    (record,) = stage.conditioned
    assert record.hypothesis_id == added.hypothesis_id
    assert record.screening_observation_ids == ("sob:1",)
    assert added.hypothesis_id in outcome.record.initial_hypothesis_ids
    # Screening ran once, over the rivals as the coverage review left them.
    assert len(stage.screened) == 1 and len(stage.screened[0]) == 2
    critic = [m for m in scientist.seen if m.startswith("You are the Adversarial Critic")]
    assert critic and "broken contact via" in {
        h["mechanism"] for h in _context(critic[0])["hypotheses"]
    }
    # The review saw the readings by alias, never a canonical observation id.
    (review,) = [m for m in scientist.seen if "screening_observations" in _context(m)]
    shown = _context(review)["screening_observations"]
    assert {o["observation_ref"] for o in shown} <= {"O1", "O2"}


def test_a_rival_admission_refuses_is_recorded_refused_and_conditions_nothing():
    """A reading the project never admitted cannot ground anything: admission refuses, and the
    refusal is the record -- no rival, no conditioning row."""
    scientist = _scientist(_engine_without_connectivity, _coverage(_decline_all), _screening_edit)
    world = _world(scientist, coverage_review=True, screening=True)
    stage = FakeStage({sp.OBS_CONNECTIVITY: "DISCONTINUOUS"})
    outcome = world.debate.run(world.request(screening=stage))
    review = outcome.record.reliability["screening"]["review"]
    assert not review["certified"] and "UNGROUNDED" in review["refused"][0]["detail"]
    assert not stage.conditioned and len(outcome.certificates) == 2


def test_a_normal_only_stage_asks_nothing_and_adds_nothing():
    scientist = _scientist(_engine_without_connectivity, _coverage(_decline_all), _screening_edit)
    world = _world(scientist, coverage_review=True, screening=True)
    stage = FakeStage({})
    outcome = world.debate.run(world.request(screening=stage))
    assert outcome.record.reliability["screening"]["review"]["status"] == "NOT_NEEDED"
    assert not [m for m in scientist.seen if "screening_observations" in _context(m)]
    assert not stage.conditioned and len(outcome.certificates) == 2


def test_a_failing_stage_is_recorded_and_the_debate_goes_on():
    class Broken(FakeStage):
        def screen(self, **kwargs: Any) -> Any:
            raise RuntimeError("reader crashed")

    scientist = _scientist(_engine_without_connectivity, _coverage(_decline_all))
    world = _world(scientist, coverage_review=True, screening=True)
    outcome = world.debate.run(world.request(screening=Broken({})))
    screening = outcome.record.reliability["screening"]
    assert screening["status"] == "FAILED" and "reader crashed" in screening["detail"]
    assert len(outcome.certificates) == 2


def test_an_optional_call_that_would_leave_the_critic_short_is_withheld_and_the_critic_runs():
    scientist = _scientist(_engine_without_connectivity, _coverage(_decline_all), _screening_edit)
    world = _world(scientist, coverage_review=True, screening=True, critic_reserve_tokens=1_000_000)
    stage = FakeStage({sp.OBS_CONNECTIVITY: "DISCONTINUOUS"})
    outcome = world.debate.run(world.request(screening=stage, tokens=1_000_000))
    reliability = outcome.record.reliability
    assert reliability["coverage_review"]["status"] == "RESERVED_FOR_CRITIC"
    assert reliability["screening"]["review"]["status"] == "RESERVED_FOR_CRITIC"
    assert reliability["withheld_for_critic"] == ["coverage review", "screening review"]
    assert outcome.critiques, "the Critic still ran"
    assert not stage.conditioned


def test_no_reserve_withholds_nothing():
    scientist = _scientist(_engine_without_connectivity, _coverage(_decline_all))
    world = _world(scientist, coverage_review=True)
    outcome = world.debate.run(world.request(tokens=1_000_000))
    assert outcome.record.reliability["withheld_for_critic"] == []


def test_identical_discriminating_claims_are_reported_never_merged():
    scientist = _scientist(_engine_without_connectivity)
    world = _world(scientist)
    outcome = world.debate.run(world.request())
    certificates = list(outcome.certificates)
    twin = certificates[0].model_copy(
        update={
            "hypothesis": certificates[0].hypothesis.model_copy(
                update={"hypothesis_id": "hyp:twin", "mechanism": "another name"}
            )
        }
    )
    pairs = overlapping_pairs([*certificates, twin])
    assert len(pairs) == 1 and "another name" in pairs[0]["mechanisms"]
    assert overlapping_pairs(certificates) == []
    assert outcome.record.reliability["overlap"] == []


# -- the device structure summary -----------------------------------------------------------------


def _device(**override: Any) -> bytes:
    nominal = {
        "format": "sp.device_project@1",
        "device_id": "PS-1",
        "drawn_length_um": "500",
        "contacts": [
            {"contact_id": "anode", "region": "p_plus", "via_to_metal": True, "overlap_nm": "400"},
            {
                "contact_id": "cathode",
                "region": "n_plus",
                "via_to_metal": False,
                "overlap_nm": "400",
            },
        ],
        "extraction_normalization_length_um": "500",
        "access_mesh_max_edge_nm": "5",
        "rib_doping_cm3": "5E17",
        "counterdoping_cm3": "0",
        "solver_converges": False,
    }
    return json.dumps({**nominal, **override}).encode()


def test_the_summary_is_design_fields_with_pointers_and_units_and_no_rule_outcome():
    summary = structure_summary(_device(), ART, "prj:1")
    paths = {e.path: e for e in summary.entries}
    assert paths["/contacts/1/via_to_metal"].value == "false"
    assert paths["/contacts/1/overlap_nm"].unit == "nm"
    assert paths["/drawn_length_um"].unit == "um"
    assert all(e.kind == "DESIGN_DECLARED" for e in summary.entries)
    shown = json.dumps(summary.as_context())
    for verdict in ("DISCONTINUOUS", "CONTINUOUS", "AGREES", "DISAGREES", 'solver_converges":'):
        assert verdict not in shown, verdict
    assert "/solver_converges" not in paths
    assert summary.as_context()["entries"][0]["ref"] == "S1"
    assert "not evidence" in str(summary.as_context()["note"])


def test_an_answer_like_field_is_refused_and_an_unknown_input_field_never_parses():
    with pytest.raises(ValueError, match="never carries an answer"):
        StructureSummary(
            summary_ref="x@1",
            project_id="prj:1",
            source_artifact_id=ART,
            entries=(StructureEntry(path="/root_cause", label="the root cause", value="open via"),),
            uncertainty="none",
        )
    with pytest.raises(DesignError, match="Extra inputs are not permitted"):
        DeviceProject.parse(_device(truth="contact_discontinuity"))
    with pytest.raises(DesignError):
        structure_summary(_device(expected={"stop": "CONFIRMED"}), ART, "prj:1")
