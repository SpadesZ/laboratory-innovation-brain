"""Durable SelectionPolicies and VerificationPlans (VER-001, VER-005; `011k`).

A plan is append-only: re-planning after a result is a NEW plan, and the old one stays as the record
of what was decided with what was known then. A policy version is immutable: VER-005's "identical
input + identical policy version -> identical plan" is only checkable if the version cannot change
underneath a stored plan. `011k` refuses, for any writer of SQL, a plan whose chosen action is not
the first sufficient action of its own ranking -- VER-001's invariant, held where the rows live.
"""

from __future__ import annotations

import json
from typing import Any, Protocol, cast, runtime_checkable

from lab_brain.core.models.verification import (
    PlanRationale,
    SelectionPolicy,
    SufficiencySummary,
    VerificationPlan,
)
from lab_brain.core.repositories.budget import SqlConnection
from lab_brain.core.repositories.protocols import RepositoryError


class VerificationPlanStoreError(RepositoryError):
    """A policy or plan write violated an invariant."""


@runtime_checkable
class VerificationPlanStore(Protocol):
    def add_policy(self, policy: SelectionPolicy) -> SelectionPolicy: ...

    def policy(self, policy_id: str, version: str) -> SelectionPolicy | None: ...

    def add_plan(self, plan: VerificationPlan) -> VerificationPlan: ...

    def get_plan(self, project_id: str, plan_id: str) -> VerificationPlan | None: ...

    def plans_for_episode(
        self, project_id: str, episode_id: str
    ) -> tuple[VerificationPlan, ...]: ...


class InMemoryVerificationPlanStore:
    def __init__(self) -> None:
        self._policies: dict[tuple[str, str], SelectionPolicy] = {}
        self._plans: dict[str, VerificationPlan] = {}

    def add_policy(self, policy: SelectionPolicy) -> SelectionPolicy:
        key = (policy.policy_id, policy.version)
        existing = self._policies.get(key)
        if existing is not None and existing != policy:
            raise VerificationPlanStoreError(
                f"selection policy {policy.ref} is immutable; a changed policy is a new version"
            )
        self._policies[key] = policy
        return policy

    def policy(self, policy_id: str, version: str) -> SelectionPolicy | None:
        return self._policies.get((policy_id, version))

    def add_plan(self, plan: VerificationPlan) -> VerificationPlan:
        if (plan.selection_policy_id, plan.selection_policy_version) not in self._policies:
            raise VerificationPlanStoreError(
                f"plan {plan.plan_id} was ranked under {plan.selection_policy_id}@"
                f"{plan.selection_policy_version}, which is not registered; an unregistered "
                "policy cannot be re-run, so the ranking could never be reproduced (VER-005)"
            )
        if plan.plan_id in self._plans:
            raise VerificationPlanStoreError(f"plan {plan.plan_id} is append-only")
        self._plans[plan.plan_id] = plan
        return plan

    def get_plan(self, project_id: str, plan_id: str) -> VerificationPlan | None:
        found = self._plans.get(plan_id)
        return found if found is not None and found.project_id == project_id else None

    def plans_for_episode(self, project_id: str, episode_id: str) -> tuple[VerificationPlan, ...]:
        return tuple(
            sorted(
                (
                    p
                    for p in self._plans.values()
                    if p.project_id == project_id and p.episode_id == episode_id
                ),
                key=lambda p: (p.created_at, p.plan_id),
            )
        )


_PLAN_COLUMNS = (
    "plan_id",
    "project_id",
    "episode_id",
    "candidate_action_ids",
    "ranked_action_ids",
    "sufficiency_results",
    "pareto_front_ids",
    "selection_policy_id",
    "selection_policy_version",
    "chosen_action_id",
    "rationale_ref",
    "rationale",
    "created_at",
)


class SqlVerificationPlanStore:
    """PostgreSQL implementation over `011k`. Reads rebuild through the models."""

    def __init__(self, connection: SqlConnection) -> None:
        self._connection = connection

    def add_policy(self, policy: SelectionPolicy) -> SelectionPolicy:
        self._connection.execute(
            "INSERT INTO selection_policies (policy_id, version, pareto_dimensions,"
            " lexicographic_fallback, tie_break_rule, effective_from)"
            " VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (policy_id, version) DO NOTHING",
            (
                policy.policy_id,
                policy.version,
                [d.value for d in policy.pareto_dimensions],
                [d.value for d in policy.lexicographic_fallback],
                policy.tie_break_rule.value,
                policy.effective_from,
            ),
        )
        stored = self.policy(policy.policy_id, policy.version)
        if stored != policy:
            raise VerificationPlanStoreError(
                f"selection policy {policy.ref} is already recorded differently"
            )
        return policy

    def policy(self, policy_id: str, version: str) -> SelectionPolicy | None:
        row = self._connection.execute(
            "SELECT policy_id, version, pareto_dimensions, lexicographic_fallback,"
            " tie_break_rule, effective_from FROM selection_policies"
            " WHERE policy_id = %s AND version = %s",
            (policy_id, version),
        ).fetchone()
        if row is None:
            return None
        return SelectionPolicy.model_validate(
            {
                "policy_id": row[0],
                "version": row[1],
                "pareto_dimensions": tuple(cast("list[str]", row[2])),
                "lexicographic_fallback": tuple(cast("list[str]", row[3])),
                "tie_break_rule": row[4],
                "effective_from": row[5],
            }
        )

    def add_plan(self, plan: VerificationPlan) -> VerificationPlan:
        self._connection.execute(
            f"INSERT INTO verification_plans ({', '.join(_PLAN_COLUMNS)})"
            f" VALUES ({', '.join(['%s'] * len(_PLAN_COLUMNS))})",
            (
                plan.plan_id,
                plan.project_id,
                plan.episode_id,
                list(plan.candidate_action_ids),
                list(plan.ranked_action_ids),
                json.dumps(
                    {k: v.model_dump(mode="json") for k, v in plan.sufficiency_results.items()}
                ),
                list(plan.pareto_front_ids),
                plan.selection_policy_id,
                plan.selection_policy_version,
                plan.chosen_action_id,
                plan.rationale_ref,
                json.dumps(plan.rationale.model_dump(mode="json")),
                plan.created_at,
            ),
        )
        stored = self.get_plan(plan.project_id, plan.plan_id)
        if stored != plan:
            raise VerificationPlanStoreError(f"plan {plan.plan_id} did not round-trip")
        return plan

    def get_plan(self, project_id: str, plan_id: str) -> VerificationPlan | None:
        row = self._connection.execute(
            f"SELECT {', '.join(_PLAN_COLUMNS)} FROM verification_plans"
            " WHERE project_id = %s AND plan_id = %s",
            (project_id, plan_id),
        ).fetchone()
        return None if row is None else _plan_from_row(row)

    def plans_for_episode(self, project_id: str, episode_id: str) -> tuple[VerificationPlan, ...]:
        rows = self._connection.execute(
            f"SELECT {', '.join(_PLAN_COLUMNS)} FROM verification_plans"
            " WHERE project_id = %s AND episode_id = %s ORDER BY created_at, plan_id",
            (project_id, episode_id),
        ).fetchall()
        return tuple(_plan_from_row(row) for row in rows)


def _plan_from_row(row: tuple[Any, ...]) -> VerificationPlan:
    values = dict(zip(_PLAN_COLUMNS, row, strict=True))
    return VerificationPlan.model_validate(
        {
            **values,
            "candidate_action_ids": tuple(values["candidate_action_ids"]),
            "ranked_action_ids": tuple(values["ranked_action_ids"]),
            "pareto_front_ids": tuple(values["pareto_front_ids"]),
            "sufficiency_results": {
                k: SufficiencySummary.model_validate(v)
                for k, v in values["sufficiency_results"].items()
            },
            "rationale": PlanRationale.model_validate(values["rationale"]),
        }
    )


__all__ = [
    "InMemoryVerificationPlanStore",
    "SqlVerificationPlanStore",
    "VerificationPlanStore",
    "VerificationPlanStoreError",
]
