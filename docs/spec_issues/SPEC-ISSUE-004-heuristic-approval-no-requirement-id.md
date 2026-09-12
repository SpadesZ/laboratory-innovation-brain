# SPEC-ISSUE-004: Heuristic approval governance has no dedicated Requirement ID

Severity: GATE
Status: OPEN
Blocks gate: M7
Raised: 2026-09-12
Raised by: M0a Spec Coverage Audit (§23.5 (2))
Affected: P16, §6.11, §6.15, §17.7, §17.11, §22 "Tacit Knowledge Governance"

## The unregistered MUST

§6.11:

> Heuristic Miner 的輸出**不是**直接入庫的 active rule，而是 `CandidateHeuristic`，必須引用來源、
> 保留原句 locator，並等待人類 approval（P16）。

§6.15:

> 只從授權來源產生，不得自行升級。

§22 lists this as an acceptance criterion. §17.7 and §17.11 define `Heuristic` and
`CandidateHeuristic` with `approval_status` fields, so the spec clearly intends enforcement.

None of the 53 Requirement IDs covers it. There is no `HEU-xxx` namespace, and no existing
requirement's pass condition mentions heuristic approval.

## Why it matters

This is the tacit-knowledge equivalent of EVI-003. An unapproved mined rule that silently becomes an
active lab rule is a machine inference promoted to lab doctrine — the same contamination P3 forbids
for evidence, arriving through the heuristic path instead. A future reader of a diagnosis would see
"the lab's rule says check the contact first" with no way to tell whether a human ever agreed.

## Why it is not blocking now

The Heuristic Miner is M7 (`Operational Lab Brain`, DEFERRED). Nothing in M0a–M4 mines or applies
heuristics, so no code can violate this today. Recorded as `Blocks gate: M7` so it must be settled
before that milestone rather than after.

## Options for the maintainer

1. **Add a dedicated requirement** (e.g. `HEU-001` / `T-HEU-001`): a candidate heuristic MUST carry
   source artifact IDs and locators, MUST start at `PENDING_REVIEW`, and MUST NOT become active
   without a recorded human approval carrying `approved_by_actor_id`. Moves the invariant to 54 ↔ 54.
2. **Extend `SEC-002`** (actor/approval/ACL) to name heuristic promotion as an approval-gated action.
   Preserves 53 ↔ 53; makes one requirement carry an extra idea.
3. **Declare DEFERRED** in §23.6 with a review date, on the grounds that M7 is outside the v3.3
   delivery scope.

Option 1 is recommended: §22 already treats this as an acceptance criterion, and §0.3 warns that a
Requirement with no Test will never be implemented — here there is not even a Requirement.

## Resolution checklist

- [ ] Maintainer picks option 1, 2 or 3
- [ ] If option 1: §25.3, §26 and the invariant count updated; `docs/milestones.yaml` allocates it
- [ ] `docs/normative_statements.yaml` gains entries for §6.11 and §6.15
- [ ] This issue closed
