# ADR-0005: Cost is a vector, never a single scalar

Status: Accepted
Date: 2026-09-12
Affected Requirements: VER-003, VER-005, COST-001, OPS-002
Human Approval Required: No (records SAI 3.3 §9.4, §9.6)

## Context

Ranking verification actions needs a cost comparison. The convenient move is one
`normalized_cost` float. It is wrong in a specific, expensive way: a 6-week MPW shuttle and
a 6-week cluster job normalise to similar numbers, but one is irreversible and schedule-
coupled and the other can be cancelled at no cost.

Compressing the vector chooses the weights *before* seeing the decision, and hides that
choice inside a number nobody can audit.

## Constraints

- P25 Cost and waiting are first-class.
- VER-003: `CostVector` must express time / human effort / money / license / irreversibility;
  the planner may not rely on a single `normalized_cost`.
- §14.4.1 / OPS-002: human review is a **finite** capability whose availability comes from
  `ReviewQueue` capacity. The planner may not treat human attention as free and unlimited.

## Options Considered

1. **Single normalized scalar** — trivially sortable, silently mis-ranks irreversible actions.
2. **Scalar + hardcoded penalty for irreversible actions** — a magic constant standing in for
   a scientific judgement, and unauditable.
3. **Full `CostVector` + Pareto filtering + versioned deterministic `SelectionPolicy`.**

## Decision

Option 3. `CostVector` carries `wall_clock_s`, `human_minutes`, `money_estimate`,
`compute_units`, `license_seat_s`, `earliest_available_at`, `irreversible`, `dependency_risk`.

Ranking is: sufficiency (binary) → disagreement metric → Pareto dominance → versioned
`SelectionPolicy` lexicographic fallback.

The fallback exists because in 7-ish dimensions almost nothing is dominated, so Pareto alone
usually returns the whole candidate set. A named, versioned tie-break is how the same inputs
produce the same plan twice (VER-005) — the weights become reviewable data instead of an
implicit bias.

## Consequences

- Positive: "why this action and not that one" is answerable from the policy version.
- Positive: license seats and human minutes are schedulable resources, not afterthoughts.
- Negative: no single number to show in a UI. A vector plus the deciding dimension must be
  displayed instead.
- Negative: `SelectionPolicy` weights are a human decision, and a wrong one produces
  consistently wrong-but-reproducible plans. Preferred over inconsistently wrong.

## Migration / Rollback

`SelectionPolicy` is versioned data. Changing weights creates a new version; historical plans
keep referencing the version that produced them.

## Tests / Evidence

- `T-VER-003`: the vector expresses all required dimensions; no single-scalar dependency.
- `T-VER-005`: identical actions/state/policy yield identical ranking across runs.
- `T-OPS-002`: queue depth changes human-review availability and `earliest_available_at`.
