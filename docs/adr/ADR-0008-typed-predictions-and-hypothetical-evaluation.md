# ADR-0008: Predictions are typed objects; sufficiency uses side-effect-free hypothetical evaluation

Status: Accepted
Date: 2026-09-12
Affected Requirements: VER-004, VER-006, EPI-005
Human Approval Required: Yes — P0 scientific semantics (granted via SAI 3.3 §17.5.1, §9.1)

## Context

"Is this experiment worth running?" reduces to "could its outcome change what we believe?".
Answering that requires evaluating a transition that has not happened yet.

If predictions are prose, the only way to evaluate them is to ask an LLM whether an outcome
would change the belief state. That routes the belief decision through the model and around
`TransitionPolicy` — the exact bypass EPI-005 exists to prevent, arriving through the
planner's back door instead of the front.

## Constraints

- VER-006: predictions MUST be typed `Prediction` objects bound to a declared `OutcomeSpace`
  version, carrying `RelationJudgmentTemplate` effects. Sufficiency MUST be computed via
  side-effect-free `TransitionPolicy.evaluate_hypothetical`. Planner and LLM MUST NOT invent
  hypothetical relations.
- §9.1: if no ACTIVE hypothesis declares a Prediction over `action.produces`, the action is
  NOT sufficient. Absence of a prediction is not evidence of discriminative power.
- VER-004: plausible outcomes must resolve to a concrete, versioned `OutcomeSpace`.

## Options Considered

1. **Prose predictions + LLM judgement of sufficiency** — flexible, and it makes the model
   the de facto transition authority.
2. **Typed predictions, sufficiency by actually applying relations then rolling back** — a
   transaction rollback still emits events and mutates projections in between. Any crash
   mid-window leaves fabricated belief history.
3. **Typed predictions + a pure `evaluate_hypothetical` that persists nothing.**

## Decision

Option 3.

`Prediction` binds `observable_ref`, `outcome_space_id` + version, `expected_outcome` (which
MUST be a member of the declared space), conditions, and
`relation_effect_if_observed[]: RelationJudgmentTemplate[]`.

`TransitionPolicy.evaluate_hypothetical(...)` takes hypothetical relations instantiated
*only* from declared Predictions and returns a `TransitionDecision`. It writes no
`RelationJudgment`, emits no `BeliefRevisionEvent`, and mutates no projection.

An action is sufficient iff some plausible outcome makes `evaluate_hypothetical` differ from
`evaluate`, or resolves a blocking `Conflict`.

## Consequences

- Positive: sufficiency is deterministic and testable. Identical inputs give identical
  decisions, so a plan can be defended after the fact.
- Positive: purity is directly assertable — `T-VER-006` checks that no relation rows, no
  events and no projection changes occurred.
- Positive: the planner cannot invent discriminative power that no hypothesis claimed.
- Negative: the debate stage must *materialise* `proposed_predictions[]` into typed
  Predictions before they count. A `Position` alone never makes an action sufficient
  (§17.14.1). This is real friction and it is the point.
- Negative: `OutcomeSpace` must be declared per action/hypothesis type before planning can
  run, which front-loads domain modelling work into M2.

## Migration / Rollback

`OutcomeSpace` and `Prediction` are versioned. Reverting to prose predictions would remove
the ability to compute sufficiency deterministically and is not planned.

## Tests / Evidence

- `T-VER-006`: out-of-space `expected_outcome` rejected at admission; `evaluate_hypothetical`
  persists nothing; an action with no bound Prediction over its `produces` is NOT sufficient;
  identical inputs return identical `TransitionDecision`.
- `T-VER-004`: outcomes outside the declared space, or excluded by constraints, are not
  plausible.
