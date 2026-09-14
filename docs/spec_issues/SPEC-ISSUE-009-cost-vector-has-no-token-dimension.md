# SPEC-ISSUE-009: COST-001 requires token accounting that `CostVector` cannot represent

Severity: GATE
Status: RESOLVED
Blocks gate: M0b
Raised: 2026-09-14
Raised by: P5 / M0b-2 implementation (COST-001)
Affected: §9.4, §17.17, §17.19.1, §25.3 `COST-001`, §26 `T-COST-001`

## The conflict

§25.3 states COST-001:

> 每次 LLM/tool action 前必須經 BudgetGate；CostLedger 至少記
> **wall-clock/tokens/money/license-seat** estimates。

§17.17 then defines what a ledger entry holds:

```
CostEntry {
  ...
  cost,                      # CostVector (9.4)
  ...
}
```

and §9.4 defines `CostVector` as exactly eight dimensions:

```
CostVector {
  wall_clock_s, human_minutes, money_estimate, compute_units,
  license_seat_s, earliest_available_at, irreversible, dependency_risk
}
```

Three of COST-001's four named minimum dimensions are there. **Tokens are not.** The ledger is
required to record a quantity the only type it may record has no slot for.

## Why it is not merely editorial

There are three ways to satisfy COST-001 against §9.4 as written, and all three are worse than
amending it:

1. **Record tokens in `compute_units`.** Two unrelated quantities share one integer, so
   "how many tokens did this episode burn" and "how much solver compute did it burn" become one
   number that answers neither. This is the same failure as R-7 — one slot holding two claims —
   and the same failure §9.4's own opening argument makes about `normalized_cost`: a dimension
   that has been merged into another is a dimension the planner cannot see.
2. **Put tokens somewhere outside `CostVector`.** Then §17.17's `cost` no longer holds the whole
   cost of an action, the budget gate caps a different set of dimensions from the ones the ledger
   records, and the two drift apart — which is the precise drift §17.17's own note says the
   `CostVector` reference exists to prevent.
3. **Read "tokens" as informative.** §25.3 is the normative requirement table and §0.2's keyword
   rules apply to it; `至少記` is a floor, not an example. An implementation that records no token
   count does not meet the stated floor, so this reading deletes an obligation rather than
   interpreting one.

Under AGT-015 an agent may not pick between these. The conflict is between two normative
contracts — §25.3's minimum dimensions and §9.4's closed dimension list — so it is escalated.

## Second defect found in the same area: caps of zero

§17.19.1 declares `Budget { ... hard_caps{}, soft_caps{} ... }` and does not say how an **absent**
cap differs from a cap of **zero**. Migration `007a_cost_ledger.sql` made nullable cap columns and
documented `NULL` as uncapped; `BudgetPolicy.cap_for()` in `lab_brain/core/budget.py` instead
treats a cap of `0` as uncapped, because `CostVector` defaults every dimension to zero and the
policy could not otherwise say "I constrain money only".

So the SQL and the Python currently disagree about what `0` means, and the disagreement is
dangerous in one direction only: a policy that means *no spend permitted in this dimension* is read
by the gate as *no limit in this dimension*. A deliberately frozen budget admits everything.

This is not the gate having a bug independently of the spec — the spec never stated the semantics,
so both readings were available. It is recorded here because the fix has to be a stated rule that
the model, the SQL and the gate are all checked against, not a patch in one of the three.

## Resolution

**Maintainer ruled on 2026-09-14 (amendment `v3.3-a10`).** Both defects are resolved in the
document, not worked around in the implementation:

1. **`token_count` is added to §9.4's `CostVector`** as a ninth dimension, and therefore flows into
   §17.17's `CostEntry.cost`, §17.17.1's `BudgetApproval.approved_overrun` and §17.19.1's budget
   caps without any of them being restated. It is a capped dimension: a token count that cannot be
   capped is accounting, not a budget. Tokens explicitly **may not** be folded into
   `compute_units`.
2. **§17.19.1 states the cap semantics**: an absent / `NULL` cap means *not capped in this
   dimension*; a cap of `0` means *zero permitted*, and the two are different facts. The Python
   model, the DDL and the gate are bound to that single reading.

**The Requirement ↔ Test invariant is unchanged at 59 ↔ 59, and no normative statement is added.**
COST-001 already obliged the ledger to record tokens — `cost.ledger.minimum_dimensions` is
registered at §17.17 and was already dischargeable in principle. This amendment makes that
obligation *representable*; it does not create it. Likewise the cap rule disambiguates the existing
`budget.gate.before_side_effect` obligation rather than adding one: a gate that cannot tell
"no cap" from "cap of zero" was never checking caps in the §17.17 sense.

No hard-obligation keyword is added to §6–§16, so the §23.5 (2) occurrence inventory is unchanged
(70 hard MUSTs over 72 classified occurrences).

## Superseded options considered

1. **Add `token_count` to `CostVector`** (chosen). Keeps one type for "what an action costs", so
   the ledger, the planner and the gate cannot disagree about what a cost consists of.
2. **Reuse `compute_units` for tokens.** Rejected: see defect 1 above.
3. **Add a `token_count` column to `CostEntry` outside the vector.** Rejected: the gate would then
   cap a different dimension set from the one the ledger records, and §17.17's stated reason for
   referencing §9.4 is exactly to prevent that.
4. **Declare tokens informative.** Rejected: it deletes a stated minimum from §25.3.

## Resolution checklist

- [x] Maintainer picks an option
- [x] §9.4 `CostVector` gains `token_count`
- [x] §17.19.1 states `NULL`/absent = uncapped, `0` = zero permitted
- [x] Version Notes gain the `v3.3-a10` row
- [ ] Implementation follows in P5-fix Phase B (model, DDL, gate, drift guard, negative tests)
- [x] This issue closed

The implementation box is deliberately still open at the Phase A commit. The document is closed —
the conflict has a ruling — and the code has not caught up yet. Ticking it early is how a checklist
becomes a claim nobody verified.
