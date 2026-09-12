# SPEC-ISSUE-005: PriorArtSearchRecord / novelty coverage has no dedicated Requirement ID

Severity: GATE
Status: OPEN
Blocks gate: M3
Raised: 2026-09-12
Raised by: M0a Spec Coverage Audit (§23.5 (2))
Affected: §6.21, §7.5, §17.20, §22 "External Sources"

## The unregistered MUST

§6.21:

> `PriorArtSearchRecord`（§17.20）保存 novelty 判斷的搜尋覆蓋範圍。**沒有覆蓋率記錄的 novelty
> status 不可稽核。**

§7.5, the NOVELTY_AUDIT row:

> 保存 PriorArtSearchRecord；不得把 internal novelty 當成 global novelty

§17.20 defines the schema, including `limitations[]` and `coverage_notes`.

No Requirement ID covers it. `SRC-002` is closest — it mandates intent-switched policy and inverted
retrieval — but says nothing about recording search coverage. `GH-001..003` concern one provider
rather than novelty auditability.

## Why it matters

"This idea is novel" is a claim about the *absence* of prior art, and an absence claim is only as
good as the search behind it. Without a coverage record a novelty status cannot be distinguished
from "we did not look very hard" — the failure §6.21 calls unauditable. It also ages badly: a
novelty judgement from two databases reads identically to one from an exhaustive search once the
record is gone.

## Why it is not blocking now

The Novelty Auditor is one of the six core roles (M3); external adapters are M5. Nothing in M0a–M2
asserts novelty. Recorded as `Blocks gate: M3`, where the role first exists.

## Options for the maintainer

1. **Add a dedicated requirement** (e.g. `SRC-003` / `T-SRC-003`): a novelty status MUST reference a
   `PriorArtSearchRecord` recording sources, queries, date range and limitations; a novelty status
   with no coverage record MUST be rejected. Moves the invariant to 54 ↔ 54.
2. **Extend `SRC-002`**'s pass condition to require a persisted `PriorArtSearchRecord` for
   NOVELTY_AUDIT intent. Preserves 53 ↔ 53.
3. **Declare DEFERRED** to M5 with a review date.

Option 2 is arguably tidiest: `SRC-002` already owns intent-switched retrieval, and NOVELTY_AUDIT is
one of its intents.

## Resolution checklist

- [ ] Maintainer picks option 1, 2 or 3
- [ ] Spec updated accordingly (and the invariant count, if option 1)
- [ ] `docs/normative_statements.yaml` gains entries for §6.21 and §7.5
- [ ] This issue closed
