# §9.2 disagreement compares affirmative forecasts, never falsifiers

Date: 2026-10-07
Scope: a P1 in verification ranking, reproduced after the typed falsifier. **Not a milestone.** No
Requirement or Test ID was added and no milestone status changed. Sufficiency, TransitionPolicy,
typed-falsifier admission, `evidence_from_run`/`comparable()`, cost vectors, SelectionPolicy,
BudgetGate, transport, credentials, locality and egress are unchanged.

## 1. The P1

`rank_by_disagreement` pooled every prediction's `expected_outcome` and took the maximum metric
distance between any two rivals' outcomes. A CONTRADICTS prediction is a hypothesis's predeclared
FALSIFYING outcome -- what would refute it, not what it expects -- and since every admitted
certificate must designate one, two rivals with identical signatures (HIGH -> SUPPORTS,
LOW -> CONTRADICTS) scored a positive disagreement by comparing one's HIGH with the other's LOW.
`LeastCostPlanner` reads `disagreement > 0` as `SelectionCandidate.discriminating`, which §9.2's
selection orders before Pareto and cost.

Reproduction (`repro_disagreement.py`, the same on `8c1d04b` and `cdcc267`):

| | before | after |
|---|---|---|
| identical signatures, falsifiers included | 1 | **0** |
| identical signatures, SUPPORTS only | 0 | 0 |
| SiPh planner, `cap:sp.charge_ac_sweep` (rivals identical over its observable) | 0.5, discriminating | **0, not discriminating** |
| SiPh planner, chosen action | `cap:sp.charge_ac_sweep` (SIMULATION) | **`cap:sp.extraction_consistency`** (the cheaper sufficient ANALYTICAL_RULE_CHECK) |

## 2. The semantics

**A forecast** (`is_affirmative_forecast`) is a prediction declaring SUPPORTS or PREDICTS and no
CONTRADICTS. CONTRADICTS -- alone or beside another effect -- is a falsifier; TESTS alone forecasts
nothing. Nothing is inferred from what a hypothesis does not declare.

**Per observable and OutcomeSpace version**, each rival's forecasts form the SET of outcomes it
affirms (duplicates collapse), and `forecast_disagreement` returns:

| case | disagreement |
|---|---|
| fewer than two rivals forecast | unknown (`None`) |
| every rival's set is identical | exactly 0 |
| every rival forecasts exactly one outcome | the DomainPack's declared metric, pairwise, the maximum over rivals -- as before |
| several outcomes and the sets differ | unknown: the domain declares a distance between outcomes, not between sets, and core invents none (no Cartesian maximum, average or set metric) |

With no metric declared for the space the disagreement stays unknown, as before. An observable with
predictions but no forecast (falsifiers only) is still listed in the ranking, with its disagreement
unknown. `RankedAction.predictions` records the forecasts the value was computed from.

**Sufficiency is untouched.** `assess_action` still reads every typed prediction, falsifiers
included: an action can be sufficient solely because an observed falsifier would change a
TransitionPolicy decision.

**One function, both callers.** Stage C of the debate and `LeastCostPlanner` both call
`rank_by_disagreement`, so the corrected semantics hold for both.

## 3. Tests

`tests/unit/test_forecast_disagreement.py`: which effects forecast; identical signatures 0 with or
without their falsifiers; opposing forecasts by the declared metric, falsifiers or not, PREDICTS
included; falsifiers or TESTS alone, a single forecasting rival and a mixed falsifier give no number;
identical multi-outcome sets 0 and unequal ones unknown; the planner reproduction no longer
discriminating and choosing the cheaper sufficient check; a falsifier alone still making an action
sufficient; a genuine disagreement still leading the order; Stage C and the planner reading the same
forecasts. Five mutation entries: falsifiers counted as forecasts, TESTS-only counted, a Cartesian
comparison of forecast sets, a number for unequal sets, a lost genuine disagreement.
