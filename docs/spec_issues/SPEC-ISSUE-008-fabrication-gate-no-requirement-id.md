# SPEC-ISSUE-008: Fabrication human sign-off has no dedicated Requirement ID

Severity: EDITORIAL
Status: RESOLVED
Raised: 2026-09-12
Raised by: M0a Spec Coverage Audit (§23.5 (2))
Affected: §14.3, §9.3

## The unregistered MUST

§14.3, Governance Gates:

> **Fabrication gate**：版圖/製程送件必須由 human sign-off

§9.3 lists `fabrication` as a verification action type, characterised as "極高 + 高延遲 + 不可逆".

No Requirement ID covers it. `SEC-002` covers actor/approval/ACL generally and `COST-001` covers
budget gating; neither names fabrication sign-off, and `CostVector.irreversible` describes the cost
of the action without requiring anyone to authorise it.

## Why this is EDITORIAL rather than GATE

Fabrication is outside the entire v3.3 delivery scope. §26.1's milestones end at M8 and none of them
submits a tape-out; §9.3 lists the action type so the planner's cost model can *represent* it, not
because the system will perform one. There is no milestone at which an implementation could violate
this, so no `Blocks gate:` applies.

It is recorded because §23.5 requires every hard MUST in §6–§16 to be accounted for, and "out of
scope" is an accounting rather than an omission.

## Resolution

**Maintainer ruled Option 1 on 2026-09-12 (amendment `v3.3-a2`)** — no new requirement. The rule is
registered against **`SEC-002`**, which owns approval-gated actions, and marked DEFERRED with
`review_at: FIRST_FABRICATION_CAPABILITY`.

The reasoning is that fabrication is unenforceable rather than unenforced: §26.1's milestones end at
M8 and none submits a tape-out, so there is no milestone at which an implementation could violate
it. §9.3 lists `fabrication` as an action type so the planner's cost model can *represent* it, not
because the system will perform one.

The deferral carries a review trigger rather than a date, since the relevant event is the
registration of a fabrication Capability, not the passage of time. At that point it needs either its
own requirement or an explicit extension of `SEC-002`'s pass condition enumerating irreversible
actions. `T-SPEC-002` enforces that a DEFERRED entry carries a `review_at`, so the trigger cannot be
dropped silently.

This is the one finding of the five that did **not** move the invariant: 57 ↔ 57 counts the four new
requirements only.


## Superseded options considered

1. **Declare DEFERRED** in §23.6 with a review date tied to the first registration of a fabrication
   Capability. Recommended.
2. **Extend `SEC-002`** to enumerate irreversible actions requiring human sign-off, fabrication being
   the first member.
3. Add a dedicated requirement when fabrication enters scope.

## Resolution checklist

- [ ] Maintainer picks an option
- [ ] `docs/normative_statements.yaml` gains an entry for §14.3, with a DEFERRED rationale under
      option 1
- [ ] This issue closed
