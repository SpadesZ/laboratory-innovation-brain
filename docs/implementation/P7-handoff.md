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

---

# P7-fix — closing the three governance gaps

Baseline audited: `7acb2e45aac4a4863c72340cdef5d34e733c4cb4` (P7, **CONDITIONAL FAIL**). Scope was
the three findings and nothing else: `EPI-004`, `EPI-006` and M1 were not started, and M1's
Evidence-Aware Hierarchical Chunking is deliberately left for a later handoff.

## 1. Ungated belief write — closed as far as the spec allows, escalated for the rest

The audit was right and the finding was sharper than it first looked. `store.append(event)` took a
raw `BeliefRevisionEvent`, so `record_transition` was advisory: any caller could build an event
whose `policy_id` and `policy_version` named a real policy and persist it without a single ALLOW
ever being computed. Genesis made this worse — `from_state=None` was a general hole, so *any*
event could claim to be a beginning.

What changed:

- `append` accepts only an `AuthorizedRevision`, a frozen dataclass that refuses construction
  unless it carries a module-private sentinel. Only `record_transition` (on an §8.2.1 ALLOW) and
  `admit_hypothesis` can mint one, and each stamps `origin` as `TRANSITION` or `ADMISSION`.
- **Genesis is a separate admission path, not a bypass.** `admit_hypothesis` requires a policy
  marked `is_admission`, requires the prior projection to be empty *for that project and target*,
  and refuses evidence from another project. `record_transition` refuses an admission policy, and
  `admit_hypothesis` refuses a transition policy, so the two paths cannot borrow each other's
  authority.
- Migration `005c` re-checks the pairing **in the database**, because a Python gate is not a
  schema guarantee: a BEFORE INSERT trigger refuses any event whose recorded transition is not the
  one its cited policy governs, in both directions.

**What is still open, and why it was not invented.** The *consistent* forgery survives: an event
naming a real policy and recording exactly the transition that policy governs, for which no ALLOW
was ever evaluated. Closing it needs a persisted authorisation, and the spec cannot express one —
§17.13 gives the event no back-reference, §8.2.1's `TransitionDecision` has no identity and is
never stored. §17.14's `Decision` is a plausible home, but whether an event MUST be backed by one,
what `decision_type` / `result` vocabulary applies, and which Requirement ID owns §17.14 are all
unstated, and all three are normative. Choosing would be agent-invented semantics, so it is raised
as **SPEC-ISSUE-011** (GATE, blocks M0b) with four options and none implemented. Recorded as
**R-13**. The in-process capability is also not a security boundary and is not claimed as one — it
makes a bypass deliberate and visible in a diff, which is what it is for.

## 2. Project-scoped replay

`history` and `replay` now take `(project_id, target_id)`. The SQL store puts both columns in the
`WHERE` clause; mixed-project input raises `BeliefScopeError` rather than folding silently.
`BeliefProjection` records the project it belongs to, so a projection can no longer be compared
against a history it did not come from. The collision test the audit asked for is in place: two
projects using the same `target_id` keep separate histories and replay to different states.

## 3. Cross-project references fail closed in SQL

Not only in Python. `005c` adds `project_id` to both join tables and a composite foreign key to
`attestations (attestation_id, project_id)` and `relations (relation_id, project_id)`, so a
cross-project reference is unrepresentable rather than merely rejected. A `DO $$` guard in the
migration raises instead of back-filling if any existing row would need a project inferred.

The orphan hole is closed too: `belief_revision_events_cite_evidence` is a CONSTRAINT TRIGGER,
`DEFERRABLE INITIALLY DEFERRED`. That specific form is load-bearing. Under the autocommit
connections these stores require, a bare `INSERT` is its own transaction and commits with zero
references, while `belief_revision_event_append` writes the event and its references in one
statement. A non-deferred trigger would refuse both, because the event row necessarily exists
before its references do.

## Proving the guards are load-bearing

**Python guards — mutation, each asserted to have applied and to compile first:**

| mutation | result |
|---|---|
| capability check removed (gap 1) | 1 failed, 20 passed |
| admission/transition pairing removed (gap 1, genesis) | 1 failed, 20 passed |
| mixed-project replay check removed (gap 2) | 1 failed, 13 passed |
| all restored | 35 passed |

**SQL guards — proven additively rather than by dropping constraints.** A scratch database was
built with every migration up to `005b` — the exact schema the audit reviewed — and the three
writes the audit reported were attempted on it and on the full schema:

| attempt | up to `005b` | with `005c` |
|---|---|---|
| event records a transition its policy does not govern | ACCEPTED | REFUSED |
| genesis event backed by a transition policy | ACCEPTED | REFUSED |
| orphan event citing no evidence at all | ACCEPTED | REFUSED |

This is a stronger statement than a drop-and-restore: it reproduces the defect on the audited
schema instead of simulating it. A parametrized test also names each `005c` trigger and constraint
against `pg_trigger` / `pg_constraint`, so deleting one fails a test that says which object is
missing, rather than only failing a behavioural test that says something broke.

## Verification

All on a database created empty and migrated by `scripts/migrate.py`, so the schema under test is
the one the migrations produce and not an accumulated dev database:

- **Migrations**: 16 declared, 16 applied from empty; re-run reports `applied 16 / pending 0`.
- **Full suite, `postgres` profile**: **692 passed**, 0 failed, 44.9 s.
- **Backend-free** (`pytest` with no `LAB_BRAIN_TEST_*`): **521 passed, 171 skipped** — AGT-007
  holds, no PostgreSQL, licence or network needed.
- `ruff check src tests scripts`, `ruff format --check src tests scripts`, `mypy` (strict, 43
  files): clean.
- `scripts/check_requirement_coverage.py`: exit 0. No OPEN GATE spec issue blocks a DONE
  milestone — SPEC-ISSUE-011 names M0b, which is IN_PROGRESS, and M0b cannot be signed off while
  it is open. That is the intended consequence, not a gap in the gate.
- `scripts/update_status.py --check`: up to date.

## Operational note the maintainer needs

The **development** database `lab_brain` has a **superseded `005c`** applied and will report
checksum drift. An early `005c` was applied there before it was committed, and it was missing
`project_id` in `belief_revision_event_append`; editing the file to fix that would have falsified
the checksum ledger, so the file was corrected and a fresh database used instead. `005c` as
committed has only ever been applied from empty. Nothing in the repository is affected and no
applied migration was edited, but `lab_brain` should be dropped and re-created rather than
migrated forward. `lab_brain_p7fix` and `lab_brain_verify` are scratch databases from this work.

## Status

`EPI-003` and `EPI-005` stay **IN_PROGRESS**. R-13 is open against EPI-005's authorisation story,
`target_id` still has no foreign key (R-12, waiting on `EPI-001` in M3), and §26's T-EPI-003 also
names the projection that is `EPI-004`. Marking either DONE would be discharging part of a pass
condition.

Carried forward, not started: **SPEC-ISSUE-011** needs a maintainer ruling before M0b sign-off;
`EPI-004` / `EPI-006`; M1 Evidence-Aware Hierarchical Chunking.
