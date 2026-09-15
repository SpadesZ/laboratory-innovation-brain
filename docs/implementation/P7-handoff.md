# P7 / M0b-4 — EPI-003 + EPI-005

Baseline: `4eb141f69c6fc27be094875d9ec6a32d487850dc` (P6, HARD PASS / LOCKED, CI `34935683559`).

Scope boundary, held: `EPI-003` and `EPI-005` only. No `EPI-004` (no ReviewItem creation, no
INCOMPARABLE auto-escalation flow), no `EPI-006` (no `Conflict` entity), no `SYS-001`, no
`EpistemicStateProjection`. Two migrations, both in Appendix A's reserved `005` slot.

A phase section is written **after** its commit exists, with the real SHA and real test counts.

| Phase | SHA | Scope |
|---|---|---|
| A | `9b0724fd9df777d5e0a66c9365b7e5bbe8c16cad` | event model, `005a`, drift binding |
| B | `67f3c5ab8cb8515f728ae393dd64bbc1af4f89d7` | `TransitionPolicy.evaluate`, `005b` |
| C | `ba107423d6dc87bc74ca14ba7b4edce281d7297e` | creation gate, replay reducer, e2e |

---

## SPEC-ISSUE-010 and amendment `v3.3-a11`

Raised in Phase A because the model could not be written honestly without a ruling. §17.13's
`BeliefRevisionEvent` declared neither `project_id` nor `policy_id`.

- **No project.** EPI-003 requires the state to be rebuildable by replay and SEC-002 scopes reads
  to a project — but with no project on the event, "this project's belief history" is not
  expressible. A replay could only be installation-wide, and "this event cites another project's
  evidence" was not a statement the schema could make, let alone refuse. R-7's shape exactly.
- **No policy id.** §8.2.1's `TransitionDecision` carries both `policy_id` and `policy_version`,
  and `TransitionPolicy` is keyed on `(policy_id, version)`. The event recorded only the version,
  and versions are per-policy — so EPI-005's "identical inputs + identical `policy_version` MUST
  return identical `TransitionDecision`" had no anchor.

Adding them without amending §17.13 would have been the ADR-0010 drift, refused for
`ExecutionSpan` in P6 for the same reason. No new requirement, no new normative statement,
59 ↔ 59, §17 outside the §6–§16 audit range.

Considered and **not** added, reasoned in the issue: `reason_code` (derivable by re-running
`evaluate`) and a Conflict reference (a blocking conflict *prevents* an event).

---

## What was built

**Phase A — the event log.** §8.2's lifecycle exactly, with no `REJECTED` (§8.2.1's prose says
"SUPPORTED/REJECTED"; §8.2's diagram, the normative one, has `CONTRADICTED`). Four validators, each
protecting replayability: it changed something, it left no terminal state, it cites its triggers,
no duplicate triggers.

Migration `005a`. Append-only in three places and it needs all three — frozen model, table triggers
refusing UPDATE/DELETE (including on the reference tables), and Phase C's gate. The triggering
arrays are **join tables**, not `TEXT[]`: §6.18's rollback *is* the query "which events were
triggered by an Attestation from extractor version X", so the references have to be joinable and
they have to resolve.

The append is one statement up front rather than after an audit: these tables are append-only in
*both* directions, so a half-written event could never be completed or removed — strictly worse
than the span defect `010b` had to fix.

**Phase B — the policy.** §8.2.1's signature exactly, and nothing else exists. Four outcomes, with
`NEED_HUMAN_REVIEW` carrying the three rules where the alternative is to invent a fact: INCOMPARABLE
authority (§10.5.1), an independence basis above WORK (§6.17), a blocking conflict (§23.4). §17.19's
UNKNOWN condition match escalates rather than resolving.

Migration `005b`: policy versions are durable and immutable, and an event's
`(policy_id, policy_version)` is now a foreign key into them — "the event names a policy version
nobody registered" became unrepresentable rather than a Python-side check.

**Phase C — the gate and the reducer.** `record_transition` refuses five ways an event could claim
an authorisation it lacks. `replay` folds events in total order, skipping quarantined triggers,
fail-closed on partial quarantine and cascading on a skip. `BeliefProjection` is deliberately not
named `EpistemicStateProjection`.

---

## Three findings the checks produced, not review

**1. A determinism test that agreed with a nondeterministic implementation.** The Phase B mutation
— iterate the authority set unordered and report a member — **passed**
`test_the_decision_is_identical_in_a_fresh_process`. It used two hash seeds over a three-element
set, and those two seeds happened to produce the same iteration order for those three strings.
Measured afterwards: eight seeds over a three-element set give three distinct first elements. Now
eight seeds over six elements; the same mutation yields five distinct canonical decisions and fails.

**2. The genesis event is unreachable through the gate, and the gate is right.** A hypothesis with
no events has no state, and a `TransitionPolicy` always declares a `from_state`. My first e2e
assumed a hypothesis could start at `ACTIVE` with an empty history; the gate refused it. The first
state comes from §8's Hypothesis Admission Gate — `EPI-001`, M3. Recorded as **R-12**; the e2e seeds
its genesis event directly with that stated, and a test pins the refusal.

**3. The traceability matrix caught a marker error.** One module with two requirement markers and
two spec_test markers makes §26's check form cross products the spec does not declare —
`(EPI-003, T-EPI-005)` is not a pair. Split into one requirement per module.

Also: the `005b` policy foreign key immediately broke Phase A's fixtures, which cited an
unregistered policy. The fixtures were wrong and the constraint is what said so.

---

## Verification

| Check | Result |
|---|---|
| postgres profile | 669 passed |
| backend-free profile | 511 passed / 158 skipped |
| migration replay from empty | scratch DB, 0 → 15 applied, then 0 pending |
| full suite on the replayed DB | 669 passed |
| idempotency, dev DB | 15 declared / 15 applied / 0 pending |
| determinism mutation | 8 seeds, 5 distinct decisions → red |
| append-only | UPDATE/DELETE refused on events, references, policies |
| executed-coverage gate | 4/4 ok under `[postgres]` |
| obligation inventory | 72 in sync |
| `update_status.py --check` | current |
| ruff / ruff format / mypy strict | clean |

Requirement ↔ Test **59 ↔ 59** throughout. §23.5 (2) inventory unchanged.

---

## Status: both requirements stay IN_PROGRESS

**`EPI-003`** — T-EPI-003 names an "EpistemicState 投影". This produces `BeliefProjection`, the
minimal reducer; `belief_level` and `unresolved_conflicts` need `EPI-004` and `EPI-006`. The
quarantine-replay half of the pass condition runs end to end against PostgreSQL.

**`EPI-005`** — satisfied on the operator, the determinism and the event. Its
"LLM cannot directly mutate status" clause is enforced at the creation gate rather than against a
cognition path, because no cognition path exists yet.

## Unresolved, carried forward

1. **R-12** (new) — `target_id` has no foreign key (`Hypothesis` is M3), and the genesis event has
   no gate. Exactly one un-gated way into the event log remains, and M3 closes it.
2. **R-10** — unchanged: the budget gate's caller dispatches only mock actions.
3. **R-11** — unchanged: a span may name a Job or Run that has no row.
4. **R-7, R-8, R-9** — unchanged. `EPI-003` was R-9's blocker; the event infrastructure now exists,
   but reclassification history still needs an `artifact_occurrences` event, which was not in this
   slice's scope.
5. **Where authority classes enter `evaluate`** — §8.2.1 passes `admitted_relations`, but
   `authority_class` lives on `Attestation`. The caller resolves them onto `HypothesisView`, as
   §8.2.1 already does for `independence_summary`. A candidate spec clarification, not a blocker.
6. **`blocking_conflict_policy` type matching** — the policy honours conflict *ids* the caller
   supplies; matching them against §17.19.3's `conflict_type` vocabulary needs `EPI-006`.
7. **`CHANGELOG.md` still stops at M0a-2.** Unchanged since P5-fix.
