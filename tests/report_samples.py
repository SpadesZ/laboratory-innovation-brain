"""An `EpisodeReport` with EVERY field populated, each with a distinct value.

For tests that must show a surface drops nothing (the web renderer) or loses nothing (the stored
report codec). `inject` is appended to every text value, so the same report can carry hostile
markup into every field at once.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from collections.abc import Iterator
from typing import Any

from lab_brain.research.report import (
    ActionLine,
    BeliefLine,
    Conclusion,
    ContinuationSection,
    DebateSection,
    EpisodeReport,
    EvidenceLine,
    HypothesisLine,
    InputStatus,
    LiteratureLine,
    LiteratureSection,
    PendingAction,
    PlanLine,
    StageStatus,
)

T0 = dt.datetime(2026, 9, 28, 9, 0, tzinfo=dt.UTC)
T1 = dt.datetime(2026, 9, 28, 9, 5, 30, 125000, tzinfo=dt.UTC)


def full_report(inject: str = "") -> EpisodeReport:
    def t(value: str) -> str:
        return value + inject

    return EpisodeReport(
        episode_id=t("epi:full"),
        project_id=t("prj:full"),
        actor_id=t("act:full"),
        trace_id=t("trc:full"),
        goal=t("why is Rs high while Cj is normal"),
        domain=t("silicon_photonics"),
        started_at=T0,
        finished_at=T1,
        episode_state=t("SUSPENDED"),
        stages=(StageStatus(t("verification"), t("DONE"), t("2 plan(s), `cap:a` executed")),),
        inputs=(
            InputStatus(
                t("report.md"),
                t("document"),
                t("INTERNAL_MEASUREMENT"),
                t("art:doc"),
                t("READY"),
                job_id=t("job:ingest"),
                run_id=t("run:ingest"),
                evidence_units=7,
                statements=5,
                detail=t("all stages succeeded"),
            ),
        ),
        verification_input=t("device PS-504 (`art:device`)"),
        evidence=(
            EvidenceLine(
                t("att:1"),
                t("report.md"),
                t("unit 3"),
                t("INTERNAL_MEASUREMENT"),
                t("Rs is 12 ohm mm at -2 V"),
                t("internal document"),
            ),
        ),
        literature=LiteratureSection(
            provider=t("literature-corpus"),
            description=t("the local literature corpus file c.json"),
            query=t("series resistance contact"),
            egress_policy=t("egp:research-run@1.0.0"),
            discovered=4,
            consulted=(
                LiteratureLine(
                    t("Contact resistance in rib modulators"),
                    t("doi:10.1/x"),
                    t("PEER_REVIEWED"),
                    t("CC-BY-4.0"),
                    t("FULL_TEXT"),
                    t("RETRACTED"),
                    t("att:lit"),
                    t("retracted in 2025"),
                ),
            ),
            refusals=(t("doi:10.1/y was not licensed for retention"),),
        ),
        hypotheses=(
            HypothesisLine(
                t("hyp:1"),
                t("access contact discontinuity"),
                t("an access discontinuity dominates Rs"),
                t("every contact is tied"),
                t("cap:sp.inspect_contact_connectivity"),
                (t("sp.contact = OPEN SUPPORTS"),),
                t("CONTRADICTED"),
                (t("CONFOUNDER (MAJOR): probe contact"),),
            ),
        ),
        debate=DebateSection(
            debate_id=t("dbt:1"),
            reasoner=t("rules:sp.catalog@1.0.0"),
            rounds=2,
            stop_reason=t("NO_ESCALATION_TRIGGER"),
            positions=(t("ENGINE: contact"),),
            critic_evidence=11,
            inverted_evidence=3,
            alternatives_named=(t("mesh artifact"),),
            surviving=(t("mesh convergence artifact"),),
            contradicted=(t("dopant compensation"),),
            gate=t("advisory only"),
        ),
        belief=(
            BeliefLine(
                t("hyp:1"),
                t("access contact discontinuity"),
                t("CONTRADICTED"),
                (t("genesis -> ACTIVE (tp:a@1, `bre:1`)"),),
            ),
        ),
        plans=(
            PlanLine(
                t("vpl:1"),
                t("ACT"),
                t("cap:sp.fourpoint_probe"),
                t("cheapest sufficient"),
                (t("`cap:sp.fourpoint_probe` -- sufficient"),),
            ),
        ),
        completed=(
            ActionLine(
                t("cap:sp.extraction_consistency"),
                t("DESIGN_CHECK"),
                t("EXECUTED"),
                t("job:v1"),
                t("run:v1"),
                t("NormalizationBasisReader"),
                (t("sp.normalization = **AGREES** (RUN_DERIVED, rule r1)"),),
                output_artifacts=(t("art:out"),),
                detail=t("read the stored output"),
            ),
        ),
        pending=(
            PendingAction(
                t("cap:sp.mesh_sensitivity"),
                t("SIMULATION"),
                True,
                (t("mesh -> SUPPORTED if UNSTABLE"),),
                t("wall clock s 240"),
                t("no licensed simulator"),
                t("a Lumerical seat"),
            ),
        ),
        human_actions=(t("`cap:sp.fourpoint_probe` (MEASUREMENT) -- a person must act"),),
        conclusion=Conclusion(
            status=t("PROVISIONAL"),
            statement=t("not confirmed; 3 remain"),
            confirmed_hypothesis=t("hyp:none"),
            ruled_out=(t("contact (CONTRADICTED)"),),
            still_competing=(t("mesh (ACTIVE)"),),
            trace=(t("run `run:v1`"),),
        ),
        failure_analysis=t("`fan:1` -- OPEN"),
        heuristic_candidates=(t("`chr:1`: pattern -> check cap:a"),),
        next_steps=(t("Run `cap:sp.mesh_sensitivity` once a seat exists"),),
        provenance=(t("Episode `epi:full`; research run `rrn:full` (run 2 of this episode)."),),
        deployment=(t("Reasoner: rules"),),
        not_performed=(t("no simulation was run"),),
        notes=(t("a loop note"),),
        continuation=ContinuationSection(
            run_ordinal=2,
            resumed_from=t("SUSPENDED (awaiting simulator)"),
            reasoning=t("hypothesis set `hst:1` reused"),
            earlier_runs=(t("run 1 by act:full"),),
            earlier_checks=(t("`cap:a` -- job `job:v0`"),),
            superseded_jobs=(t("job `job:parked` superseded"),),
            recovered=(t("run 3 was INTERRUPTED"),),
        ),
    )


def leaves(value: Any) -> Iterator[Any]:
    """Every scalar a report carries, recursively."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        for f in dataclasses.fields(value):
            yield from leaves(getattr(value, f.name))
    elif isinstance(value, tuple):
        for v in value:
            yield from leaves(v)
    elif value is not None:
        yield value


__all__ = ["T0", "T1", "full_report", "leaves"]
