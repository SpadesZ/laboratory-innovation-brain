"""In-memory builders for M4's unit tests: the SiPh pack's registries and hand-made rivals.

No database. The planner is pure over descriptors, declared spaces, the registered outcome
validator and policies, so every VER-00x unit test can build its inputs here and run it twice.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Any

from lab_brain.core.models.belief_event import BeliefState
from lab_brain.core.models.condition import ConditionMatch, ConditionSchemaRef
from lab_brain.core.models.enums import ConditionMatchState, RelationType
from lab_brain.core.models.prediction import Prediction, RelationJudgmentTemplate
from lab_brain.core.models.transition import HypothesisView
from lab_brain.domains.registry import DomainPackRegistry
from lab_brain.domains.silicon_photonics import SiliconPhotonicsPack
from lab_brain.domains.silicon_photonics import vertical as sp
from lab_brain.domains.silicon_photonics.tools import INPUT_DEVICE_PROJECT
from lab_brain.verification.least_cost import LeastCostPlanner
from lab_brain.verification.sufficiency import HypothesisState, TransitionTarget

PROJECT = "prj:unit"
T0 = dt.datetime(2026, 9, 27, 9, 0, tzinfo=dt.UTC)
CONDITIONS = {"device_length_um": "500"}
AVAILABLE = frozenset({INPUT_DEVICE_PROJECT})

#: mechanism -> (observable, space, supporting outcome, contradicting outcome)
CHECKS: dict[str, tuple[str, str, str, str]] = {
    "contact": (sp.OBS_CONNECTIVITY, sp.SPACE_CONNECTIVITY, "DISCONTINUOUS", "CONTINUOUS"),
    "normalization": (sp.OBS_NORMALIZATION, sp.SPACE_NORMALIZATION, "DISAGREES", "AGREES"),
    "mesh": (sp.OBS_MESH, sp.SPACE_MESH, "UNSTABLE", "STABLE"),
    "dopant": (sp.OBS_CARRIER, sp.SPACE_CARRIER, "COMPENSATED", "NOMINAL"),
    "probe": (sp.OBS_PROBE, sp.SPACE_PROBE, "ELEVATED", "NOMINAL"),
}


def registries() -> Any:
    registry = DomainPackRegistry()
    registry.install(
        SiliconPhotonicsPack(
            runner=lambda _request: None,  # type: ignore[arg-type,return-value]
            conditions=registry.registries.conditions,
        )
    )
    return registry.registries


def predictions(mechanism: str, *, version: str = sp.SPACE_VERSION) -> tuple[Prediction, ...]:
    observable, space, supports, contradicts = CHECKS[mechanism]
    hypothesis_id = f"hyp:{mechanism}"
    return tuple(
        Prediction(
            prediction_id=f"prd:{mechanism}.{effect.value.lower()}",
            hypothesis_id=hypothesis_id,
            project_id=PROJECT,
            observable_ref=observable,
            outcome_space_id=space,
            outcome_space_version=version,
            expected_outcome=outcome,
            relation_effect_if_observed=(
                RelationJudgmentTemplate(relation_type=effect, to_entity_id=hypothesis_id),
            ),
        )
        for outcome, effect in (
            (supports, RelationType.SUPPORTS),
            (contradicts, RelationType.CONTRADICTS),
        )
    )


def rival(
    mechanism: str,
    *,
    state: BeliefState = BeliefState.ACTIVE,
    version: str = sp.SPACE_VERSION,
) -> HypothesisState:
    return HypothesisState(
        view=HypothesisView(
            hypothesis_id=f"hyp:{mechanism}",
            project_id=PROJECT,
            current_state=state,
            stakes="HIGH",
        ),
        admitted_relations=(),
        predictions=predictions(mechanism, version=version),
    )


def rivals(*mechanisms: str) -> tuple[HypothesisState, ...]:
    return tuple(rival(m) for m in (mechanisms or tuple(CHECKS)))


def targets() -> tuple[TransitionTarget, ...]:
    return tuple(
        TransitionTarget(policy=policy, to_state=to_state)
        for policy, to_state in sp.diagnosis_targets()
    )


def exact_match() -> ConditionMatch:
    return ConditionMatch(
        condition_match_id="cmt:unit",
        state=ConditionMatchState.EXACT,
        matched_fields=("device_length_um",),
        tolerance_policy_version="1.0.0",
        schema_ref=ConditionSchemaRef.parse(sp.DEVICE_SCHEMA_REF),
        created_at=T0,
    )


class Ids:
    def __init__(self) -> None:
        self._n = 0

    def __call__(self, kind: str) -> str:
        self._n += 1
        return f"{kind}:unit-{self._n:04d}"


def planner(regs: Any, *, case_memory: Any = None) -> LeastCostPlanner:
    return LeastCostPlanner(
        capabilities=regs.capabilities,
        metrics=regs.disagreement_metrics,
        validators=regs.validators,
        mint=Ids(),
        now=lambda: T0,
        case_memory=case_memory,
    )


def plan(
    regs: Any,
    states: Sequence[HypothesisState],
    *,
    exclude: frozenset[str] = frozenset(),
    case_memory: Any = None,
    symptom: str | None = None,
) -> Any:
    return planner(regs, case_memory=case_memory).plan(
        project_id=PROJECT,
        episode_id="epi:unit",
        hypotheses=states,
        targets=targets(),
        policy=sp.selection_policy(),
        authority_policy=sp.VerticalAuthorityPolicy(),
        available_inputs=AVAILABLE,
        conditions=CONDITIONS,
        symptom=symptom,
        exclude=exclude,
        projected_condition_match=exact_match(),
    )


__all__ = [
    "AVAILABLE",
    "CHECKS",
    "CONDITIONS",
    "PROJECT",
    "T0",
    "Ids",
    "exact_match",
    "plan",
    "planner",
    "predictions",
    "registries",
    "rival",
    "rivals",
    "targets",
]
