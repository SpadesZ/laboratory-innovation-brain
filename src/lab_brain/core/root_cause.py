"""EPI-002: a confirmed root cause traces to Run / Evidence / Artifact, and a model statement is not
evidence. Plus the failure memory and heuristic candidates VS-SP-001 ends with.

    EPI-002   confirmed root cause 必須可以 trace 回 Run/Evidence/Artifact；
              LLM statement 不可作為證據。
    T-EPI-002 confirmed root cause query 必須 trace 到 Relation/Attestation or Observation → Run →
              Artifact；只有 LLM statement 的 fixture 不得確認 root cause。
    §25.4     同類失敗形成可審核 heuristic candidate.

THE TRACE, LINK BY LINK, FROM THE BELIEF DOWNWARDS:

    hypothesis    in a ROOT-CAUSE competing set (EPI-001) and currently SUPPORTED -- the latest
                  event in its verified history
    relation      a SUPPORTS RelationJudgment among that event's triggering relations, landing on
                  this hypothesis (§17.8: the relation is the single source of truth for support)
    attestation   one of the relation's supporting attestations that `core.adjudication` admits:
                  not INFERRED (a model's statement, EVI-003) and not DISPUTED
    run           the attestation's `run_id` -- or its Observation's -- naming a durable Run of the
                  same project that SUCCEEDED
    artifact      every output artifact that Run declares, present in the artifact store

A cause is confirmed only when at least one complete chain exists. A chain that stops at a report
("the literature says"), at a model's reading ("the Critic concluded"), or at a Run whose outputs
are gone is not a confirmation, and the refusal says which link was missing. `011l` refuses the same
FailureAnalysis row for any writer of SQL.

WHY A RUN IS REQUIRED, NOT MERELY AN ARTIFACT. T-EPI-002 names the chain `... -> Run -> Artifact`.
A root cause is a claim about THIS episode's failing object, and the Run is the record that
something was executed against it -- by whom, with what inputs, under what validity. VS-SP-001
therefore executes every verification action, the local geometry inspection included, as a durable
Job with a Run (`verification.loop`), so the cheapest check can confirm a cause without breaking
the chain.

THE MINER IS DETERMINISTIC AND ITS OUTPUT IS A CANDIDATE. It groups CONFIRMED analyses by
(failure class, symptom) and proposes one CandidateHeuristic per group with at least
`MIN_SUPPORT` distinct episodes: the checks that confirmed them, the episodes and artifacts they
came from, and any existing candidate for the same trigger that suggests different checks. Status is
PENDING_REVIEW; approving it is HEU-001 (M7).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from lab_brain.core.adjudication import inadmissibility
from lab_brain.core.models.attestation import Attestation
from lab_brain.core.models.belief_event import BeliefRevisionEvent, BeliefState
from lab_brain.core.models.enums import RelationType
from lab_brain.core.models.failure import CandidateHeuristic, FailureAnalysis, ResolutionStatus
from lab_brain.core.models.hypothesis_set import HypothesisSet
from lab_brain.core.models.job import Run, RunStatus
from lab_brain.core.models.observation import Observation
from lab_brain.core.models.relation import RelationJudgment

MINER_VERSION = "failure-class-miner@1.0.0"
MIN_SUPPORT = 2


class RootCauseRefusal(StrEnum):
    NOT_A_ROOT_CAUSE_CANDIDATE = "NOT_A_ROOT_CAUSE_CANDIDATE"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    NO_SUPPORTING_RELATION = "NO_SUPPORTING_RELATION"
    ONLY_MODEL_STATEMENTS = "ONLY_MODEL_STATEMENTS"
    NO_EXECUTION_TRACE = "NO_EXECUTION_TRACE"


class RootCauseRefused(RuntimeError):
    def __init__(self, reason: RootCauseRefusal, detail: str) -> None:
        super().__init__(f"{reason.value}: {detail}")
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class TraceLink:
    relation_id: str
    attestation_id: str
    observation_id: str | None
    run_id: str
    capability_id: str
    artifact_ids: tuple[str, ...]


@dataclass(frozen=True)
class RootCauseTrace:
    project_id: str
    hypothesis_id: str
    event_id: str
    links: tuple[TraceLink, ...]
    #: (attestation_id, why it could not start a chain) for every supporting attestation left out.
    set_aside: tuple[tuple[str, str], ...] = ()

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        return tuple(sorted({link.attestation_id for link in self.links}))

    @property
    def run_ids(self) -> tuple[str, ...]:
        return tuple(sorted({link.run_id for link in self.links}))

    @property
    def artifact_ids(self) -> tuple[str, ...]:
        return tuple(sorted({a for link in self.links for a in link.artifact_ids}))

    @property
    def capability_ids(self) -> tuple[str, ...]:
        return tuple(sorted({link.capability_id for link in self.links}))


History = Callable[[str, str], Sequence[BeliefRevisionEvent]]
RelationLookup = Callable[[str, str], RelationJudgment | None]
AttestationLookup = Callable[[str, str], Attestation | None]
ObservationLookup = Callable[[str, str], Observation | None]
RunLookup = Callable[[str], Run | None]
ArtifactExists = Callable[[str], bool]


def trace_root_cause(
    *,
    project_id: str,
    hypothesis_id: str,
    history: History,
    relation: RelationLookup,
    attestation: AttestationLookup,
    observation: ObservationLookup,
    run: RunLookup,
    artifact_exists: ArtifactExists,
) -> RootCauseTrace:
    """Walk the SUPPORTED belief down to Runs and Artifacts, or refuse naming the missing link."""
    events = list(history(project_id, hypothesis_id))
    if not events or events[-1].to_state is not BeliefState.SUPPORTED:
        state = events[-1].to_state.value if events else "no history"
        raise RootCauseRefused(
            RootCauseRefusal.NOT_SUPPORTED,
            f"{hypothesis_id} is {state}; only a SUPPORTED hypothesis can be a confirmed "
            "root cause",
        )
    supported = events[-1]
    supporting = [
        found
        for relation_id in supported.triggering_relation_ids
        if (found := relation(project_id, relation_id)) is not None
        and found.relation_type is RelationType.SUPPORTS
        and found.to_entity_id == hypothesis_id
    ]
    if not supporting:
        raise RootCauseRefused(
            RootCauseRefusal.NO_SUPPORTING_RELATION,
            f"event {supported.event_id} moved {hypothesis_id} to SUPPORTED on no SUPPORTS "
            "relation landing on it; §17.8 makes the relation the single source of support",
        )
    links: list[TraceLink] = []
    set_aside: list[tuple[str, str]] = []
    admissible_seen = False
    for rel in sorted(supporting, key=lambda r: r.relation_id):
        for attestation_id in sorted(set(rel.supporting_attestation_ids)):
            witness = attestation(project_id, attestation_id)
            if witness is None or witness.project_id != project_id:
                set_aside.append((attestation_id, "does not resolve in this project"))
                continue
            excluded = inadmissibility(witness)
            if excluded is not None:
                set_aside.append((attestation_id, excluded))
                continue
            admissible_seen = True
            observation_id = witness.observation_id
            run_id = witness.run_id
            if run_id is None and observation_id is not None:
                obs = observation(project_id, observation_id)
                run_id = obs.run_id if obs is not None else None
            if run_id is None:
                set_aside.append(
                    (attestation_id, "is not the output of any execution (no Run in its chain)")
                )
                continue
            executed = run(run_id)
            if executed is None or executed.project_id != project_id:
                set_aside.append((attestation_id, f"names run {run_id}, which does not resolve"))
                continue
            if executed.status is not RunStatus.SUCCEEDED:
                set_aside.append((attestation_id, f"run {run_id} is {executed.status.value}"))
                continue
            missing = [a for a in executed.output_artifacts if not artifact_exists(a)]
            if not executed.output_artifacts or missing:
                set_aside.append(
                    (
                        attestation_id,
                        f"run {run_id} has no durable output artifact"
                        + (f" (missing {missing})" if missing else ""),
                    )
                )
                continue
            links.append(
                TraceLink(
                    relation_id=rel.relation_id,
                    attestation_id=attestation_id,
                    observation_id=observation_id,
                    run_id=run_id,
                    capability_id=executed.capability_id,
                    artifact_ids=tuple(sorted(executed.output_artifacts)),
                )
            )
    if not links:
        reason = (
            RootCauseRefusal.NO_EXECUTION_TRACE
            if admissible_seen
            else RootCauseRefusal.ONLY_MODEL_STATEMENTS
        )
        raise RootCauseRefused(
            reason,
            f"{hypothesis_id}'s support does not reach a Run and an Artifact: "
            + "; ".join(f"{a} {why}" for a, why in set_aside),
        )
    return RootCauseTrace(
        project_id=project_id,
        hypothesis_id=hypothesis_id,
        event_id=supported.event_id,
        links=tuple(links),
        set_aside=tuple(set_aside),
    )


def confirm_root_cause(
    *,
    hypothesis_set: HypothesisSet,
    hypothesis_id: str,
    candidate_causes: Sequence[str],
    trace: RootCauseTrace,
    failure_analysis_id: str,
    symptom: str,
    expected_behavior: str,
    observed_behavior: str,
    failure_class: str,
    fix: str | None = None,
    prevention_rule: str | None = None,
    created_at: dt.datetime,
) -> FailureAnalysis:
    """A CONFIRMED FailureAnalysis for a traced cause of a root-cause set -- or a refusal."""
    if not hypothesis_set.root_cause:
        raise RootCauseRefused(
            RootCauseRefusal.NOT_A_ROOT_CAUSE_CANDIDATE,
            f"set {hypothesis_set.set_id} is not a root-cause set; its members are not root causes",
        )
    if (trace.project_id, trace.hypothesis_id) != (hypothesis_set.project_id, hypothesis_id):
        raise RootCauseRefused(
            RootCauseRefusal.NO_EXECUTION_TRACE,
            f"the trace is for {trace.hypothesis_id} in {trace.project_id}, not {hypothesis_id}",
        )
    return FailureAnalysis(
        failure_analysis_id=failure_analysis_id,
        project_id=hypothesis_set.project_id,
        episode_id=hypothesis_set.episode_id,
        symptom=symptom,
        expected_behavior=expected_behavior,
        observed_behavior=observed_behavior,
        candidate_causes=tuple(sorted(set(candidate_causes))),
        confirmed_root_cause=hypothesis_id,
        root_cause_evidence_ids=trace.evidence_ids,
        failure_class=failure_class,
        fix=fix,
        prevention_rule=prevention_rule,
        resolution_status=ResolutionStatus.CONFIRMED,
        created_at=created_at,
    )


@dataclass(frozen=True)
class MinedEvidence:
    """What the miner may cite for one confirmed failure: its checks and its artifacts."""

    capability_ids: tuple[str, ...]
    artifact_ids: tuple[str, ...]
    run_ids: tuple[str, ...]


def mine_candidate_heuristics(
    failures: Sequence[FailureAnalysis],
    *,
    evidence_for: Mapping[str, MinedEvidence],
    existing: Sequence[CandidateHeuristic],
    mint: Callable[[str], str],
    now: Callable[[], dt.datetime],
    min_support: int = MIN_SUPPORT,
) -> tuple[CandidateHeuristic, ...]:
    """One PENDING_REVIEW candidate per recurring (failure class, symptom), deterministically."""
    groups: dict[tuple[str, str, str], list[FailureAnalysis]] = {}
    for failure in failures:
        if failure.resolution_status is not ResolutionStatus.CONFIRMED:
            continue
        key = (failure.project_id, failure.failure_class, " ".join(failure.symptom.lower().split()))
        groups.setdefault(key, []).append(failure)
    proposed: list[CandidateHeuristic] = []
    for (project_id, failure_class, symptom), members in sorted(groups.items()):
        episodes = sorted({f.episode_id for f in members})
        if len(episodes) < min_support:
            continue
        ids = tuple(sorted(f.failure_analysis_id for f in members))
        if any(set(c.derived_from_failures) == set(ids) for c in existing):
            continue  # already proposed from exactly this evidence
        checks = tuple(
            sorted({c for f in members for c in evidence_for[f.failure_analysis_id].capability_ids})
        )
        artifacts = tuple(
            sorted({a for f in members for a in evidence_for[f.failure_analysis_id].artifact_ids})
        )
        runs = tuple(
            sorted({r for f in members for r in evidence_for[f.failure_analysis_id].run_ids})
        )
        conflicts = tuple(
            sorted(
                c.candidate_id
                for c in existing
                if " ".join(c.trigger_pattern.lower().split()) == symptom
                and set(c.suggested_checks) != set(checks)
            )
        )
        proposed.append(
            CandidateHeuristic(
                candidate_id=mint("candidate_heuristic"),
                project_id=project_id,
                trigger_pattern=symptom,
                suggested_checks=checks,
                rationale=(
                    f"{len(ids)} confirmed failures of class {failure_class} across "
                    f"{len(episodes)} episodes were each confirmed by {', '.join(checks)}; when "
                    "this symptom recurs, try these checks before escalating"
                ),
                source_artifact_ids=artifacts,
                source_locators=tuple(f"run:{r}" for r in runs),
                source_episode_ids=tuple(episodes),
                miner_model_version=MINER_VERSION,
                proposed_scope={"failure_class": failure_class, "project_id": project_id},
                conflicts_with_existing_rules=conflicts,
                derived_from_failures=ids,
                created_at=now(),
            )
        )
    return tuple(proposed)


__all__ = [
    "MINER_VERSION",
    "MIN_SUPPORT",
    "MinedEvidence",
    "RootCauseRefusal",
    "RootCauseRefused",
    "RootCauseTrace",
    "TraceLink",
    "confirm_root_cause",
    "mine_candidate_heuristics",
    "trace_root_cause",
]
