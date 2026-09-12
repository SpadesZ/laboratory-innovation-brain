# SPEC-ISSUE-006: P10 "No single scalar FoM" has no dedicated Requirement ID

Severity: GATE
Status: RESOLVED
Blocks gate: M4
Raised: 2026-09-12
Raised by: M0a Spec Coverage Audit (§23.5 (2))
Affected: P10, §10.4, §19, §22 "Verification"

## The unregistered MUST

§10.4:

> 不可只看單一 scalar FoM 判斷設計好壞。多目標 trade-off 必須被保留與呈現（P10）。

## Why VER-003 does not cover it

`VER-003` is about **cost**: "Verification cost 使用 CostVector；不可只存 normalized_cost 作唯一決策
依據." Its test checks that the planner does not depend on a single normalized cost scalar.

P10 is about **design quality** — the figure of merit of a device, not the cost of measuring it.
Different objects, different consumers: cost feeds Pareto filtering and `SelectionPolicy`; FoM feeds
hypothesis evaluation and design comparison. A system could hold a perfectly multi-dimensional
`CostVector` while ranking every candidate design by one scalar Q, and `T-VER-003` would pass.

§19 makes the intent explicit — the AutoPhotonicDesign row lists what is deliberately *not* adopted
as "單 scalar FoM keep/discard".

## Why it is not blocking now

No design evaluation exists before M4. Recorded as `Blocks gate: M4`.

## Resolution

**Maintainer ruled Option 1 on 2026-09-12 (amendment `v3.3-a2`).** `VER-007` / `T-VER-007` added:

> VER-007 — Candidate/design comparison MUST preserve and present multi-objective trade-offs. A
> single scalar figure of merit MUST NOT be the sole keep/discard criterion (P10).

Allocated to **M4**, where design comparison first exists. Registry entry added for §10.4, with a
note recording why this is not VER-003: that governs the *cost* of a verification action, this the
*quality* of a design, and a multi-dimensional `CostVector` can coexist with a scalar-ranked design
space while `T-VER-003` passes. Part of the 53 ↔ 53 to 57 ↔ 57 move.


## Superseded options considered

1. **Add a dedicated requirement** (e.g. `VER-007` / `T-VER-007`): candidate/design comparison MUST
   preserve and present multi-objective trade-offs; a single scalar FoM MUST NOT be the sole
   keep/discard criterion. Moves the invariant to 54 ↔ 54.
2. **Extend `VER-004`** (declared OutcomeSpace) to require that an OutcomeSpace over design quality
   be multi-dimensional or explicitly justify being scalar. Preserves 53 ↔ 53.
3. **Declare it advisory** with a DEFERRED rationale in §23.6 — acceptable only if the maintainer
   judges P10 unenforceable rather than merely unimplemented.

## Resolution checklist

- [ ] Maintainer picks option 1, 2 or 3
- [ ] Spec updated accordingly (and the invariant count, if option 1)
- [ ] `docs/normative_statements.yaml` gains an entry for §10.4
- [ ] This issue closed
