"""§9.2's disagreement is between the rivals' AFFIRMATIVE forecasts, never their falsifiers.

`rank_by_disagreement` pooled every prediction's expected outcome. Once every certificate had to
designate a CONTRADICTS falsifier, two rivals with identical signatures (HIGH -> SUPPORTS,
LOW -> CONTRADICTS) scored a positive disagreement, `SelectionCandidate.discriminating` flipped,
and the silicon-photonics planner chose a simulation over a cheaper sufficient analytical check.
Proven here:

    forecasts      SUPPORTS / PREDICTS forecast; CONTRADICTS (alone or mixed) and TESTS alone do not
    zero           identical signatures disagree by exactly 0, with or without their falsifiers
    positive       opposing forecasts disagree by the declared metric, falsifiers or not
    unknown        falsifiers or TESTS alone, or a single forecasting rival, give no number; unequal
                   multi-outcome forecast sets are unknown -- no invented set distance -- while
                   identical ones are 0
    sufficiency    still sees every prediction: a falsifier alone can make an action sufficient
    planner        the reproduction no longer prefers the AC sweep; genuine disagreement still leads
    Stage C        the debate's ranking and the planner read the same affirmative forecasts
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from lab_brain.cognition import debate as debate_module
from lab_brain.core.models.belief_event import BeliefState
from lab_brain.core.models.benchmark import DisagreementMetric
from lab_brain.core.models.enums import RelationType
from lab_brain.core.models.prediction import OutcomeSpace, Prediction, RelationJudgmentTemplate
from lab_brain.core.models.transition import HypothesisView
from lab_brain.domains.silicon_photonics import reasoning
from lab_brain.domains.silicon_photonics import vertical as sp
from lab_brain.domains.silicon_photonics.tools import CHARGE_AC_CAPABILITY
from lab_brain.verification import least_cost
from lab_brain.verification.disagreement import (
    DisagreementMetricRegistry,
    is_affirmative_forecast,
    rank_by_disagreement,
)
from lab_brain.verification.sufficiency import HypothesisState
from tests.debate_fixtures import build_world
from tests.vertical_units import PROJECT, plan, registries

S, C, P, T = (
    RelationType.SUPPORTS,
    RelationType.CONTRADICTS,
    RelationType.PREDICTS,
    RelationType.TESTS,
)
SPACE = "os:fx.level"
OBSERVABLE = "fx.level"
CAPABILITY = "cap:fx.read"


class _Rank:
    """|i - j| over HIGH, MID, LOW: a declared, ordered test metric."""

    ORDER = ("HIGH", "MID", "LOW")

    @property
    def declaration(self) -> DisagreementMetric:
        return DisagreementMetric(
            metric_id="dm:fx.rank",
            outcome_space_id=SPACE,
            outcome_space_version="1.0.0",
            implementation_ref="tests.unit.test_forecast_disagreement:_Rank",
            version="1.0.0",
        )

    def distance(self, a: str, b: str) -> Decimal:
        return Decimal(abs(self.ORDER.index(a) - self.ORDER.index(b)))


def _metrics() -> DisagreementMetricRegistry:
    metrics = DisagreementMetricRegistry()
    metrics.declare_space(
        OutcomeSpace(
            outcome_space_id=SPACE,
            version="1.0.0",
            domain="fx",
            action_type="MEASUREMENT",
            outcomes=_Rank.ORDER,
        )
    )
    metrics.register(_Rank())
    return metrics


def _p(hypothesis: str, outcome: str, *effects: RelationType, n: int = 0) -> Prediction:
    return Prediction(
        prediction_id=f"prd:{hypothesis}.{outcome}.{'-'.join(e.value for e in effects)}.{n}",
        hypothesis_id=f"hyp:{hypothesis}",
        project_id=PROJECT,
        observable_ref=OBSERVABLE,
        outcome_space_id=SPACE,
        outcome_space_version="1.0.0",
        expected_outcome=outcome,
        relation_effect_if_observed=tuple(
            RelationJudgmentTemplate(relation_type=e, to_entity_id=f"hyp:{hypothesis}")
            for e in effects
        ),
    )


def _score(*predictions: Prediction) -> Decimal | None:
    (ranked,) = rank_by_disagreement([(CAPABILITY, (OBSERVABLE,))], predictions, _metrics())
    return ranked.disagreement


# -- what a forecast is ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("effects", "forecast"),
    [
        ((S,), True),
        ((P,), True),
        ((S, T), True),
        ((C,), False),
        ((T,), False),
        ((C, S), False),
        ((C, P), False),
    ],
)
def test_a_forecast_is_supports_or_predicts_and_never_a_falsifier(effects, forecast):
    assert is_affirmative_forecast(_p("h", "HIGH", *effects)) is forecast


# -- the four cases --------------------------------------------------------------------------------


def test_identical_signatures_disagree_by_zero_with_or_without_their_falsifiers():
    identical = (_p("h1", "HIGH", S), _p("h1", "LOW", C), _p("h2", "HIGH", S), _p("h2", "LOW", C))
    assert _score(*identical) == Decimal(0)
    affirmative_only = tuple(p for p in identical if is_affirmative_forecast(p))
    assert _score(*affirmative_only) == Decimal(0), "the mandatory falsifiers change nothing"
    (ranked,) = rank_by_disagreement([(CAPABILITY, (OBSERVABLE,))], identical, _metrics())
    assert ranked.predictions == (("hyp:h1", "HIGH"), ("hyp:h2", "HIGH")), "forecasts only"
    assert ranked.metric_ref == "dm:fx.rank@1.0.0"


def test_opposing_forecasts_disagree_by_the_declared_metric_falsifiers_or_not():
    opposing = (_p("h1", "HIGH", S), _p("h2", "LOW", S))
    assert _score(*opposing) == Decimal(2)
    assert _score(*opposing, _p("h1", "LOW", C), _p("h2", "HIGH", C)) == Decimal(2)
    assert _score(_p("h1", "HIGH", P), _p("h2", "MID", S)) == Decimal(1), "PREDICTS forecasts"
    three = (_p("h1", "HIGH", S), _p("h2", "MID", S), _p("h3", "MID", S))
    assert _score(*three) == Decimal(1), "the maximum over rivals, as before"


def test_falsifiers_or_tests_alone_cannot_manufacture_a_disagreement():
    assert _score(_p("h1", "LOW", C), _p("h2", "HIGH", C)) is None
    assert _score(_p("h1", "HIGH", S), _p("h2", "LOW", C)) is None, "one rival forecasts"
    assert _score(_p("h1", "HIGH", S), _p("h2", "LOW", T)) is None
    assert _score(_p("h1", "HIGH", S), _p("h2", "LOW", C, S)) is None, "a mixed falsifier"


def test_identical_multi_outcome_sets_are_zero_and_unequal_ones_are_unknown():
    same = (
        _p("h1", "HIGH", S),
        _p("h1", "MID", S),
        _p("h1", "MID", P, n=1),  # a duplicate outcome collapses
        _p("h2", "MID", S),
        _p("h2", "HIGH", S),
    )
    assert _score(*same) == Decimal(0)
    unequal = (_p("h1", "HIGH", S), _p("h1", "MID", S), _p("h2", "MID", S), _p("h2", "LOW", S))
    assert _score(*unequal) is None, "no set distance is declared, so none is invented"
    subset = (_p("h1", "HIGH", S), _p("h2", "HIGH", S), _p("h2", "LOW", S))
    assert _score(*subset) is None


# -- the planner and Stage C -----------------------------------------------------------------------


def _sp(hypothesis: str, observable: str, space: str, outcome: str, effect: RelationType):  # type: ignore[no-untyped-def]
    return Prediction(
        prediction_id=f"prd:{hypothesis}.{observable}.{outcome}",
        hypothesis_id=f"hyp:{hypothesis}",
        project_id=PROJECT,
        observable_ref=observable,
        outcome_space_id=space,
        outcome_space_version="1.0.0",
        expected_outcome=outcome,
        relation_effect_if_observed=(
            RelationJudgmentTemplate(relation_type=effect, to_entity_id=f"hyp:{hypothesis}"),
        ),
    )


def _state(hypothesis: str, predictions: list[Prediction]) -> HypothesisState:
    return HypothesisState(
        view=HypothesisView(
            hypothesis_id=f"hyp:{hypothesis}",
            project_id=PROJECT,
            current_state=BeliefState.ACTIVE,
            stakes="HIGH",
        ),
        admitted_relations=(),
        predictions=tuple(predictions),
    )


IMPEDANCE = (reasoning.RS_RESPONSE_OBSERVABLE, reasoning.RS_RESPONSE_SPACE_ID)


def _reproduction(with_falsifiers: bool) -> tuple[HypothesisState, ...]:
    """The reproduction: both rivals declare the SAME signature over the AC sweep's observable;
    only h1 predicts over the cheap extraction check."""
    sweep = {
        h: [_sp(h, *IMPEDANCE, reasoning.RS_INSENSITIVE, S)]
        + ([_sp(h, *IMPEDANCE, reasoning.RS_RISES, C)] if with_falsifiers else [])
        for h in ("h1", "h2")
    }
    extraction = [
        _sp("h1", sp.OBS_NORMALIZATION, sp.SPACE_NORMALIZATION, "DISAGREES", S),
        _sp("h1", sp.OBS_NORMALIZATION, sp.SPACE_NORMALIZATION, "AGREES", C),
    ]
    return (_state("h1", sweep["h1"] + extraction), _state("h2", sweep["h2"]))


@pytest.mark.parametrize("with_falsifiers", [True, False])
def test_the_reproduction_no_longer_prefers_the_ac_sweep(with_falsifiers):
    regs = registries()
    states = _reproduction(with_falsifiers)
    sweep = regs.capabilities.resolve(CHARGE_AC_CAPABILITY)
    # The planner's `SelectionCandidate.discriminating` is `disagreement > 0` of exactly this value.
    disagreement, _ = least_cost._max_disagreement(
        sweep, [p for s in states for p in s.predictions], regs.disagreement_metrics
    )
    assert disagreement == Decimal(0), "identical forecasts do not discriminate"
    result = plan(regs, states).plan
    assert result.sufficiency_results[CHARGE_AC_CAPABILITY].disagreement == "0"
    assert result.sufficiency_results[CHARGE_AC_CAPABILITY].sufficient
    assert result.sufficiency_results[sp.CAP_EXTRACTION_CONSISTENCY].sufficient
    assert result.ranked_action_ids[0] == sp.CAP_EXTRACTION_CONSISTENCY
    assert result.chosen_action_id == sp.CAP_EXTRACTION_CONSISTENCY, "the cheaper sufficient check"


def test_sufficiency_still_reads_the_falsifier_alone():
    regs = registries()
    falsifier_only = _state(
        "contact", [_sp("contact", sp.OBS_CONNECTIVITY, sp.SPACE_CONNECTIVITY, "CONTINUOUS", C)]
    )
    result = plan(regs, (falsifier_only,)).plan
    summary = result.sufficiency_results[sp.CAP_INSPECT_CONNECTIVITY]
    assert summary.sufficient, "an observed falsifier would change a governed decision"
    assert ("hyp:contact", BeliefState.CONTRADICTED.value, "CONTINUOUS") in summary.discriminating
    assert summary.disagreement is None, "and it is no forecast to disagree with"
    assert result.chosen_action_id == sp.CAP_INSPECT_CONNECTIVITY


def test_a_genuine_disagreement_still_leads_the_order():
    regs = registries()
    states = tuple(
        _state(
            h,
            [
                _sp(h, sp.OBS_CONNECTIVITY, sp.SPACE_CONNECTIVITY, forecast, S),
                _sp(h, sp.OBS_CONNECTIVITY, sp.SPACE_CONNECTIVITY, falsifier, C),
                _sp(h, sp.OBS_NORMALIZATION, sp.SPACE_NORMALIZATION, "DISAGREES", S),
                _sp(h, sp.OBS_NORMALIZATION, sp.SPACE_NORMALIZATION, "AGREES", C),
            ],
        )
        for h, forecast, falsifier in (
            ("h1", "DISCONTINUOUS", "CONTINUOUS"),
            ("h2", "CONTINUOUS", "DISCONTINUOUS"),
        )
    )
    result = plan(regs, states).plan
    assert result.sufficiency_results[sp.CAP_INSPECT_CONNECTIVITY].disagreement == "1"
    assert result.sufficiency_results[sp.CAP_EXTRACTION_CONSISTENCY].disagreement == "0"
    assert result.ranked_action_ids.index(sp.CAP_INSPECT_CONNECTIVITY) < (
        result.ranked_action_ids.index(sp.CAP_EXTRACTION_CONSISTENCY)
    )
    assert result.chosen_action_id == sp.CAP_INSPECT_CONNECTIVITY


def test_stage_c_and_the_planner_read_the_same_affirmative_forecasts():
    assert debate_module.rank_by_disagreement is rank_by_disagreement
    assert least_cost.rank_by_disagreement is rank_by_disagreement
    world = build_world()
    outcome = world.debate.run(world.request())
    falsifiers = {
        (p.hypothesis_id, p.observable_ref, p.expected_outcome)
        for c in outcome.certificates
        for p in c.predictions
        if p.prediction_id in c.falsifier_prediction_ids
    }
    assert falsifiers and outcome.ranking
    for ranked in outcome.ranking:
        forecasts = {
            (p.hypothesis_id, p.expected_outcome)
            for c in outcome.certificates
            for p in c.predictions
            if p.observable_ref == ranked.observable_ref and is_affirmative_forecast(p)
        }
        assert set(ranked.predictions) <= forecasts, ranked
        assert not {(h, ranked.observable_ref, o) for h, o in ranked.predictions} & falsifiers
