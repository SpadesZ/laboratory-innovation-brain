"""Durable screening plans, readings and the hypotheses proposed after them (`012y`).

Append-only, project-scoped, read back through the models. `012y` holds the invariants for every
writer of SQL: a reading belongs to a check its plan selected, an executed reading names its Run and
Observations, one executed reading per evidence line per episode, and -- the guard -- no SUPPORTS
relation to a conditioned hypothesis from the look that prompted it, from anything older than it,
or from a deterministic repeat of that look.
"""

from __future__ import annotations

import json
from typing import Any

from lab_brain.core.models.cost import CostVector
from lab_brain.core.models.screening import (
    ConditionedHypothesis,
    ScreeningCandidate,
    ScreeningObservation,
    ScreeningPlan,
    ScreeningReading,
    ScreeningStatus,
    inputs_key,
)
from lab_brain.core.repositories.budget import SqlConnection
from lab_brain.core.repositories.protocols import RepositoryError


class ScreeningStoreError(RepositoryError):
    """A screening write violated an invariant."""


class InMemoryScreeningStore:
    """The same contract in memory, for tests that need no database."""

    def __init__(self) -> None:
        self.plans: dict[str, ScreeningPlan] = {}
        self.observations: dict[str, ScreeningObservation] = {}
        self.conditioned: dict[tuple[str, str], ConditionedHypothesis] = {}

    def add_plan(self, plan: ScreeningPlan) -> ScreeningPlan:
        if plan.plan_id in self.plans:
            raise ScreeningStoreError(f"screening plan {plan.plan_id} is append-only")
        self.plans[plan.plan_id] = plan
        return plan

    def add_observation(self, observation: ScreeningObservation) -> ScreeningObservation:
        plan = self.plans.get(observation.plan_id)
        if plan is None or observation.capability_id not in {
            c.capability_id for c in plan.selected
        }:
            raise ScreeningStoreError(
                f"screening observation {observation.screening_observation_id} is not a check its "
                "plan selected"
            )
        if observation.status is ScreeningStatus.EXECUTED and any(
            o.evidence_line == observation.evidence_line
            and o.episode_id == observation.episode_id
            and o.status is ScreeningStatus.EXECUTED
            for o in self.observations.values()
        ):
            raise ScreeningStoreError("one executed reading per evidence line per episode")
        self.observations[observation.screening_observation_id] = observation
        return observation

    def add_conditioned(self, record: ConditionedHypothesis) -> ConditionedHypothesis:
        key = (record.project_id, record.hypothesis_id)
        if key in self.conditioned:
            raise ScreeningStoreError(f"conditioned hypothesis {record.hypothesis_id} is recorded")
        self.conditioned[key] = record
        return record

    def screened_keys(self, project_id: str, episode_id: str) -> frozenset[str]:
        return frozenset(
            inputs_key(o.capability_id, self.plans[o.plan_id].input_artifacts)
            for o in self.observations.values()
            if o.project_id == project_id
            and o.episode_id == episode_id
            and o.status is ScreeningStatus.EXECUTED
        )


class SqlScreeningStore:
    """PostgreSQL implementation over `012y`."""

    def __init__(self, connection: SqlConnection) -> None:
        self._connection = connection

    def add_plan(self, plan: ScreeningPlan) -> ScreeningPlan:
        self._connection.execute(
            "INSERT INTO screening_plans (plan_id, project_id, episode_id, trace_id, actor_id,"
            " hypothesis_set_id, policy_id, policy_version, considered_hypothesis_ids,"
            " unaddressed_observables, input_artifacts, candidates, selected_capability_ids,"
            " created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)",
            (
                plan.plan_id,
                plan.project_id,
                plan.episode_id,
                plan.trace_id,
                plan.actor_id,
                plan.hypothesis_set_id,
                plan.policy_id,
                plan.policy_version,
                list(plan.considered_hypothesis_ids),
                list(plan.unaddressed_observables),
                list(plan.input_artifacts),
                json.dumps([c.model_dump(mode="json") for c in plan.candidates]),
                [c.capability_id for c in plan.selected],
                plan.created_at,
            ),
        )
        return plan

    def add_observation(self, observation: ScreeningObservation) -> ScreeningObservation:
        self._connection.execute(
            "INSERT INTO screening_observations (screening_observation_id, plan_id, project_id,"
            " episode_id, rank, capability_id, status, job_id, run_id, readings, observation_ids,"
            " estimated_cost, evidence_line, detail, recorded_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s, %s, %s)",
            (
                observation.screening_observation_id,
                observation.plan_id,
                observation.project_id,
                observation.episode_id,
                observation.rank,
                observation.capability_id,
                observation.status.value,
                observation.job_id,
                observation.run_id,
                json.dumps([r.model_dump(mode="json") for r in observation.readings]),
                [r.observation_id for r in observation.readings],
                json.dumps(observation.estimated_cost.model_dump(mode="json")),
                observation.evidence_line,
                observation.detail,
                observation.recorded_at,
            ),
        )
        return observation

    def add_conditioned(self, record: ConditionedHypothesis) -> ConditionedHypothesis:
        self._connection.execute(
            "INSERT INTO screening_conditioned_hypotheses (hypothesis_id, project_id, episode_id,"
            " plan_id, screening_observation_ids, inference_id, recorded_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                record.hypothesis_id,
                record.project_id,
                record.episode_id,
                record.plan_id,
                list(record.screening_observation_ids),
                record.inference_id,
                record.recorded_at,
            ),
        )
        return record

    def screened_keys(self, project_id: str, episode_id: str) -> frozenset[str]:
        rows = self._connection.execute(
            "SELECT s.capability_id, p.input_artifacts FROM screening_observations s"
            " JOIN screening_plans p ON p.plan_id = s.plan_id AND p.project_id = s.project_id"
            " WHERE s.project_id = %s AND s.episode_id = %s AND s.status = 'EXECUTED'",
            (project_id, episode_id),
        ).fetchall()
        found: list[Any] = list(rows)
        return frozenset(inputs_key(str(r[0]), list(r[1])) for r in found)

    def screened_capabilities(
        self, project_id: str, episode_id: str, input_artifacts: tuple[str, ...]
    ) -> frozenset[str]:
        """Capabilities whose reading of exactly these inputs this episode already took."""
        wanted = sorted(input_artifacts)
        rows = self._connection.execute(
            "SELECT s.capability_id, p.input_artifacts FROM screening_observations s"
            " JOIN screening_plans p ON p.plan_id = s.plan_id AND p.project_id = s.project_id"
            " WHERE s.project_id = %s AND s.episode_id = %s AND s.status = 'EXECUTED'",
            (project_id, episode_id),
        ).fetchall()
        found: list[Any] = list(rows)
        return frozenset(str(r[0]) for r in found if sorted(r[1]) == wanted)

    def plans_for_episode(self, project_id: str, episode_id: str) -> tuple[ScreeningPlan, ...]:
        rows = self._connection.execute(
            "SELECT plan_id, project_id, episode_id, trace_id, actor_id, hypothesis_set_id,"
            " policy_id, policy_version, considered_hypothesis_ids, unaddressed_observables,"
            " input_artifacts, candidates, created_at FROM screening_plans"
            " WHERE project_id = %s AND episode_id = %s ORDER BY created_at, plan_id",
            (project_id, episode_id),
        ).fetchall()
        return tuple(_plan(r) for r in rows)

    def observations_for_episode(
        self, project_id: str, episode_id: str
    ) -> tuple[ScreeningObservation, ...]:
        rows = self._connection.execute(
            "SELECT screening_observation_id, plan_id, project_id, episode_id, rank,"
            " capability_id, status, job_id, run_id, readings, estimated_cost, evidence_line,"
            " detail, recorded_at FROM screening_observations"
            " WHERE project_id = %s AND episode_id = %s ORDER BY recorded_at, plan_id, rank",
            (project_id, episode_id),
        ).fetchall()
        return tuple(_observation(r) for r in rows)

    def conditioned_for_episode(
        self, project_id: str, episode_id: str
    ) -> tuple[ConditionedHypothesis, ...]:
        rows = self._connection.execute(
            "SELECT hypothesis_id, project_id, episode_id, plan_id, screening_observation_ids,"
            " inference_id, recorded_at FROM screening_conditioned_hypotheses"
            " WHERE project_id = %s AND episode_id = %s ORDER BY recorded_at, hypothesis_id",
            (project_id, episode_id),
        ).fetchall()
        return tuple(_conditioned(r) for r in rows)


def _conditioned(r: Any) -> ConditionedHypothesis:
    return ConditionedHypothesis(
        hypothesis_id=r[0],
        project_id=r[1],
        episode_id=r[2],
        plan_id=r[3],
        screening_observation_ids=tuple(r[4]),
        inference_id=r[5],
        recorded_at=r[6],
    )


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _plan(r: Any) -> ScreeningPlan:
    return ScreeningPlan(
        plan_id=r[0],
        project_id=r[1],
        episode_id=r[2],
        trace_id=r[3],
        actor_id=r[4],
        hypothesis_set_id=r[5],
        policy_id=r[6],
        policy_version=r[7],
        considered_hypothesis_ids=tuple(r[8]),
        unaddressed_observables=tuple(r[9]),
        input_artifacts=tuple(r[10]),
        candidates=tuple(ScreeningCandidate.model_validate(c) for c in _json(r[11])),
        created_at=r[12],
    )


def _observation(r: Any) -> ScreeningObservation:
    return ScreeningObservation(
        screening_observation_id=r[0],
        plan_id=r[1],
        project_id=r[2],
        episode_id=r[3],
        rank=r[4],
        capability_id=r[5],
        status=ScreeningStatus(r[6]),
        job_id=r[7],
        run_id=r[8],
        readings=tuple(ScreeningReading.model_validate(x) for x in _json(r[9])),
        estimated_cost=CostVector.model_validate(_json(r[10])),
        evidence_line=r[11],
        detail=r[12],
        recorded_at=r[13],
    )


__all__ = ["InMemoryScreeningStore", "ScreeningStoreError", "SqlScreeningStore"]
