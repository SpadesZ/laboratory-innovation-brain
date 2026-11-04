"""Evaluation of the safe arm (B3) beside the frozen arms, with the frozen tooling and scorers.

    B2   the frozen engine, `investigate` under `DISCOVERY` -- exactly the arm the 2026-11-02
         evidence recorded
    B3   `safe_investigate`: the same engine and protocol, then the adequacy gate

Everything that runs a world is the FROZEN evaluation tooling, unchanged: `held_out.run_held_out`
(blind laboratory, metered cost, truth-leak refusal, the force-fit scorer), `held_out.
run_full_catalog_control` (the family left in the catalog, scored by the benchmark's class rule)
and `curves.run_grid` (the existing world generator over a cap grid). This module only supplies
the B3 runner -- which records each run's assessment so abstentions can be broken down -- and
summarises. A version of the evaluator is therefore not needed: the frozen one scores both arms.

WHAT THE NUMBERS ARE. Engineering evidence on synthetic worlds written by the engine's author
lineage, with held-out families that were declared in the catalog the engine was developed
against. Not scientific validity, not an independent evaluation.
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from lab_brain.discovery.benchmark import ARMS, Arm, Scenario
from lab_brain.discovery.catalog import DiscoveryCatalog
from lab_brain.discovery.metrics import rate
from lab_brain.discovery.model import DiscoveryResult, to_jsonable
from lab_brain.discovery.protocol import DISCOVERY, DiscoveryProtocol
from lab_brain.discovery_eval import curves, held_out
from lab_brain.discovery_eval.blind import find_truth_leaks
from lab_brain.discovery_safety.gate import safe_investigate
from lab_brain.discovery_safety.model import (
    PROPOSAL_STAGE,
    PROPOSAL_STATUS,
    SAFETY,
    SafeRun,
    SafetyAssessment,
    SafetyProtocol,
)

B2: Arm = next(a for a in ARMS if a.arm_id == "B2")
SAFE_ARM_ID = "B3"
SAFE_ARM_LABEL = "LIB + Discovery + out-of-catalog safety gate (v1)"


@dataclass
class SafeArmRecorder:
    """An `Arm` runner for B3 that keeps every run's assessment, keyed by the scored digest."""

    safety: SafetyProtocol = SAFETY
    runs: dict[str, SafeRun] = field(default_factory=dict)

    def __call__(self, **kwargs: Any) -> DiscoveryResult:
        run = safe_investigate(safety=self.safety, **kwargs)
        self.runs[run.result.digest] = run
        return run.result

    def assessment(self, digest: str) -> SafetyAssessment:
        return self.runs[digest].assessment

    def arm(self, arm_id: str = SAFE_ARM_ID, label: str = SAFE_ARM_LABEL) -> Arm:
        return Arm(arm_id, label, DISCOVERY, self)


def _count(values: Sequence[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return dict(sorted(out.items()))


def assessment_summary(assessments: Sequence[SafetyAssessment]) -> dict[str, Any]:
    """How the safe arm decided: decisions, reasons, confidence, what it left a person."""
    proposals = [a.proposal for a in assessments if a.proposal is not None]
    return {
        "n": len(assessments),
        "decisions": _count([a.decision.value for a in assessments]),
        "reasons": _count([a.reason.value if a.reason else "ENDORSED" for a in assessments]),
        "confidence": _count([a.confidence.value for a in assessments]),
        "engine_claimed": sum(1 for a in assessments if a.engine_claim),
        "engine_claim_withheld": sum(1 for a in assessments if a.engine_claim and not a.endorsed),
        "catalog_incomplete_detected": sum(1 for a in assessments if a.catalog_incomplete),
        "inadequacy_reproduced": sum(1 for a in assessments if a.inadequacy_reproduced),
        "proposals": len(proposals),
        "proposals_fitting_observed": sum(1 for p in proposals if p.fits_observed),
        "proposals_stage_1_only": all(
            p.stage == PROPOSAL_STAGE and p.status == PROPOSAL_STATUS for p in proposals
        ),
        "with_discriminating_request": sum(1 for a in assessments if a.requests),
        "with_reframed_question": sum(1 for a in assessments if a.reframed_question),
        "abstained_with_open_anomaly": sum(
            1 for a in assessments if not a.endorsed and a.anomalies
        ),
        "probe_units_mean": round(sum(a.spent_on_probes for a in assessments) / len(assessments), 4)
        if assessments
        else None,
    }


def held_out_evaluation(
    catalog: DiscoveryCatalog,
    worlds: Sequence[held_out.HeldOutWorld],
    *,
    budgets: Sequence[int],
    motivating_experiment: str,
    protocol: DiscoveryProtocol = DISCOVERY,
    safety: SafetyProtocol = SAFETY,
    baseline: Arm = B2,
) -> tuple[list[held_out.HeldOutRow], dict[str, Any]]:
    """B2 and B3 on held-out worlds at each budget, through the frozen `run_held_out`."""
    recorder = SafeArmRecorder(safety)
    arms = (baseline, recorder.arm())
    rows: list[held_out.HeldOutRow] = []
    for budget in budgets:
        rows.extend(
            held_out.run_held_out(
                catalog,
                worlds,
                arms=arms,
                budget=budget,
                motivating_experiment=motivating_experiment,
                protocol=protocol,
            )
        )
    by_world = {w.spec.world_id: w for w in worlds}
    per_budget: dict[str, Any] = {}
    for budget in budgets:
        safe = [r for r in rows if r.arm == SAFE_ARM_ID and r.budget == budget]
        for r in safe:
            leaks = find_truth_leaks(
                to_jsonable(recorder.assessment(r.digest)),
                held_out.truth_needles(catalog, by_world[r.world_id]),
            )
            if leaks:
                raise held_out.TruthLeak(f"an assessment names the truth: {leaks[:3]}")
        primary = [recorder.assessment(r.digest) for r in safe if not r.aliased]
        aliased = [recorder.assessment(r.digest) for r in safe if r.aliased]
        per_budget[str(budget)] = {
            "primary": assessment_summary(primary),
            "aliased": assessment_summary(aliased),
        }
    return rows, per_budget


def headline(rows: Sequence[held_out.HeldOutRow], arms: Sequence[str]) -> dict[str, Any]:
    """Force-fit, false null, correct (no claim), with-record per arm and budget; primary only."""
    out: dict[str, Any] = {}
    for budget in sorted({r.budget for r in rows}):
        at: dict[str, Any] = {}
        for arm in arms:
            p = [r for r in rows if r.budget == budget and r.arm == arm and not r.aliased]
            at[arm] = {
                "force_fit": rate([r.force_fit for r in p]),
                "false_null": rate([r.false_null for r in p]),
                "abstained_correctly": rate([r.correct for r in p]),
                "abstained_with_record": rate([r.with_record for r in p]),
                "realized_cost_mean": round(sum(r.spent for r in p) / len(p), 4) if p else None,
            }
        out[str(budget)] = at
    return out


def control_evaluation(
    catalog: DiscoveryCatalog,
    worlds: Sequence[held_out.HeldOutWorld],
    *,
    budgets: Sequence[int],
    motivating_experiment: str,
    protocol: DiscoveryProtocol = DISCOVERY,
    safety: SafetyProtocol = SAFETY,
) -> dict[str, Any]:
    """The positive control: the same worlds with the family LEFT IN the catalog (frozen
    `run_full_catalog_control`), B2 against B3, with B3's decisions broken down."""
    out: dict[str, Any] = {}
    for budget in budgets:
        recorder = SafeArmRecorder(safety)
        control = held_out.run_full_catalog_control(
            catalog,
            worlds,
            arms=(B2, recorder.arm()),
            budget=budget,
            motivating_experiment=motivating_experiment,
            protocol=protocol,
        )
        control["safe_arm_decisions"] = assessment_summary(
            [r.assessment for r in recorder.runs.values()]
        )
        out[str(budget)] = control
    return out


def curve_evaluation(
    scenario: Scenario, caps: Sequence[int], *, safety: SafetyProtocol = SAFETY
) -> tuple[list[curves.CapRow], dict[str, Any]]:
    """B2 and B3 over the cap grid on the existing world generator (frozen `curves.run_grid`)."""
    recorder = SafeArmRecorder(safety)
    rows = curves.run_grid(scenario, caps, (B2, recorder.arm()))
    summary: dict[str, Any] = {}
    kinds = sorted({r.kind for r in rows})
    for cap in caps:
        at: dict[str, Any] = {}
        for arm in (B2.arm_id, SAFE_ARM_ID):
            mine = [r for r in rows if r.cap == cap and r.arm == arm]
            at[arm] = {
                "correct": rate([r.correct for r in mine]),
                "false_discovery": rate([r.false_discovery for r in mine]),
                "claim_made": rate([r.claim_made for r in mine]),
                "realized_cost_mean": round(sum(r.spent for r in mine) / len(mine), 4),
                "per_kind": {
                    k: {
                        "n": sum(1 for r in mine if r.kind == k),
                        "correct": sum(1 for r in mine if r.kind == k and r.correct),
                        "false_discovery": sum(
                            1 for r in mine if r.kind == k and r.false_discovery
                        ),
                    }
                    for k in kinds
                },
            }
        safe = [r for r in rows if r.cap == cap and r.arm == SAFE_ARM_ID]
        at["safe_arm_decisions"] = assessment_summary([recorder.assessment(r.digest) for r in safe])
        summary[str(cap)] = at
    return rows, summary


def budget_monotonicity(rows: Sequence[held_out.HeldOutRow], arm: str) -> dict[str, Any]:
    """Per world: does a larger budget ever turn this arm's no-claim into a force-fit?"""
    budgets = sorted({r.budget for r in rows})
    index: Mapping[tuple[str, int], held_out.HeldOutRow] = {
        (r.world_id, r.budget): r for r in rows if r.arm == arm
    }
    worlds = sorted({r.world_id for r in rows if r.arm == arm and not r.aliased})
    escalations = [
        f"{w}: {a} -> {b}"
        for w in worlds
        for a, b in itertools.pairwise(budgets)
        if not index[(w, a)].force_fit and index[(w, b)].force_fit
    ]
    return {"budgets": budgets, "worlds": len(worlds), "force_fit_escalations": escalations}


__all__ = [
    "B2",
    "SAFE_ARM_ID",
    "SAFE_ARM_LABEL",
    "SafeArmRecorder",
    "assessment_summary",
    "budget_monotonicity",
    "control_evaluation",
    "curve_evaluation",
    "headline",
    "held_out_evaluation",
]
