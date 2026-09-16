# M0b — Execution/Governance Foundation: readiness for maintainer sign-off

Baseline: `6fd8093bab8a9c54fed9b618eced14ba86d20ee2` (P13, independent maintainer **HARD PASS**).

**Status: READY_FOR_MAINTAINER_SIGNOFF.** All ten M0b requirements are READY against their exact
§26 pass conditions. `docs/milestones.yaml` still records M0b as `IN_PROGRESS` and is deliberately
not edited — sign-off is the maintainer's act, not this session's.

M0b exit gate: *event replay + transition/authority tests + ACL/budget/trace contracts pass;
testable without a DomainPack.* The suite is green with no backend at all (712 passed / 342
skipped), and no test imports `lab_brain.domains.*` — `tests/toy_authority.py` is a fixture in
`tests/`, which is what "testable without a DomainPack" means.

---

## What was missing, and it was one thing

Every component M0b needs existed and was governed. What did not exist was a **caller that walked
the path end to end**. The consequence was precise and had been recorded honestly for three
slices: §26's EPI-004 row says the ReviewItem is ***auto*-created**, and nothing auto-created one.
`core/escalation.py` built the objects; a human test invoked it.

`core/episode.py` is that caller. It decides nothing: `TransitionPolicy.evaluate` stays pure
because `v3.3-a12` requires a stored Decision to re-derive from its own snapshot, so every impure
thing the flow needs happens in the episode instead — joining `authority_class` off the supporting
attestations, loading conflicts, reading history — and the resolved values are what go into the
snapshot.

---

## Readiness matrix

### SYS-001 — core scientific state path

| | |
|---|---|
| **§26 pass condition** | static/conformance test rejects bypass from cognition directly to EpistemicState update or support arrays on Attestation/Hypothesis |
| **Implementation** | `src/lab_brain/core/episode.py` (the path); `src/lab_brain/core/repositories/evidence.py` (the Attestation → RelationJudgment leg); `src/lab_brain/core/belief.py` (event → projection) |
| **Test** | `tests/unit/test_core_architecture_invariants.py` (static half); `tests/e2e/test_episode_cognition_path_postgres.py` (17 tests, dynamic half) |
| **PostgreSQL** | Yes. The bypasses are *attempted* against the real schema rather than assumed impossible: no writable belief-status column anywhere, no projection table, `AuthorizedRevision` unconstructable, an LLM verdict with nowhere to go |
| **Known limitations** | `Hypothesis` (§8.1) does not exist as an entity until EPI-001 in M3. The clause's "Hypothesis" half is discharged against `HypothesisView` — the only hypothesis-shaped object in core and the one `evaluate` reads — which carries no support array. `stakes` is a parameter for the same reason |
| **Verdict** | **READY** |

### SEC-002 — Actor/ACL, project-scoped artifact access

| | |
|---|---|
| **§26 pass condition** | unauthorized actor refused by ACL/egress gate; a new unclassified artifact defaults restricted; same bytes may carry different labels in two projects; holding in A grants nothing in B; an inactive actor is BLOCKed even with correct membership and clearance; an unresolved actor is BLOCKed. All with negative fixtures |
| **Implementation** | `src/lab_brain/core/access.py`; `src/lab_brain/core/models/access.py`; migration `002a` |
| **Test** | `tests/security/test_project_scoped_access.py` (22 tests); `tests/integration/test_artifact_occurrence_postgres.py` |
| **PostgreSQL** | Yes, for the occurrence table and the classification constraint |
| **Known limitations** | "Defaults restricted" is implemented as *unrepresentable* rather than defaulted: `artifact_occurrences.sensitivity_label` is NOT NULL **with no default**, so an unclassified presence cannot be written at all. Asserted by `test_an_occurrence_requires_a_classification`, whose docstring records that a default of "unrestricted" would make every such insert a silent grant. Stricter than the clause, and worth the maintainer confirming that reading |
| **Verdict** | **READY** |

### COST-001 — BudgetGate, CostLedger, supervisor approval path

| | |
|---|---|
| **§26 pass condition** | an over-budget model/tool call is blocked before any external side effect; the block is releasable by supervisor/human approval recorded as an event carrying `actor_id`; a retry without approval is still blocked; a permanent-refusal-only implementation must FAIL |
| **Implementation** | `src/lab_brain/core/budget.py`; `src/lab_brain/core/dispatch.py`; `src/lab_brain/core/repositories/budget.py`; migrations `007a`/`007b` |
| **Test** | `tests/contract/test_budget_gate.py` (45 tests); `tests/integration/test_cost_ledger_postgres.py` |
| **PostgreSQL** | Yes. The approval claim is durable and single-use, proven under two real concurrent sessions (`test_two_concurrent_sessions_claiming_one_approval_produce_one_winner`) |
| **Known limitations** | None against this pass condition. The approval path is real, not decorative: nine tests remove exactly one of the facts an approval needs (self-signing, inactive approver, non-human approver, no membership, no budget authority, wrong project/episode/action, expired) and each is refused separately |
| **Verdict** | **READY** |

### EPI-003 — every status change is an event; state rebuilds by replay

| | |
|---|---|
| **§26 pass condition** | quarantine a triggering attestation, replay, the EpistemicState projection changes and history is preserved |
| **Implementation** | `src/lab_brain/core/belief.py` — `replay`, `verified_history`, `quarantined_by_extractor_version`, and §17.13's `EpistemicStateProjection` |
| **Test** | `tests/e2e/test_belief_replay_postgres.py`; `tests/contract/test_belief_replay.py` |
| **PostgreSQL** | Yes. The projection is replayed out of the database, the quarantine is applied, the projection differs, and the event log is asserted byte-for-byte unchanged — which is the difference between a rollback and a hand edit |
| **Known limitations** | **`belief_level` is always `None`.** §17.13 marks it optional (`belief_level?`); §8.1 only *建議s* an ordinal LOW/MEDIUM/HIGH and declares no thresholds; "evidence quality dimensions" is a DomainPack judgment. Computing one in core would put a scientific verdict in prose rather than in a versioned policy (AGT-016). The field and its `BeliefLevel` enum exist so a later policy can populate it. **This is the one item a maintainer may reasonably want to argue about**, and it is stated rather than hidden |
| **Verdict** | **READY** |

### EPI-004 — INCOMPARABLE yields NEED_HUMAN_REVIEW + an auto-created ReviewItem

| | |
|---|---|
| **§26 pass condition** | authority fixtures cover stronger/weaker/equivalent/incomparable; a required INCOMPARABLE returns NEED_HUMAN_REVIEW, **auto-creates** ReviewItem(AUTHORITY_CONFLICT), and blocks belief promotion/rejection |
| **Implementation** | `src/lab_brain/core/authority.py`; `src/lab_brain/core/escalation.py`; `src/lab_brain/core/episode.py` (the caller); migrations `011b`–`011e` |
| **Test** | `tests/unit/test_authority_policy.py` (the four comparison results and the partial-order laws); `tests/e2e/test_authority_review_loop_postgres.py` — including `test_the_review_item_is_created_automatically_by_the_episode`, which calls **no** escalation function |
| **PostgreSQL** | Yes |
| **Known limitations** | None against this pass condition. The auto-creation clause was the P12/P13 blocker and is now discharged by a test under EPI-004's own marker — this was a real traceability gap found during this audit: the episode test proving auto-creation carried `SYS-001`, so EPI-004's marked tests did not include it |
| **Verdict** | **READY** |

### EPI-005 — versioned policy authorizes; LLM cannot mutate status

| | |
|---|---|
| **§26 pass condition** | direct LLM status assignment rejected; admitted RelationJudgments + policy produce event and replayable projection; only `evaluate` exists (no `should_transition`); identical inputs + identical `policy_version` yield an identical decision under canonical serialization; **both** classes of forgery refused — storage-checkable at the database, semantic at the production read path, with an adversarial e2e in which raw SQL writes a semantically forged Decision, the database accepts it, the verifier refuses it and the projection is unchanged |
| **Implementation** | `src/lab_brain/core/models/transition.py`; `src/lab_brain/core/belief.py` (`authorize_transition`, `rederive_decision`, `record_transition`, `verify_stored_revision`); migrations `005a`–`005d` |
| **Test** | `tests/contract/test_transition_policy.py` (determinism across processes and hash seeds; canonical-operator-only scan); `tests/contract/test_belief_transition.py`; `tests/contract/test_belief_authorization_verification.py`; `tests/e2e/test_belief_authorization_verification_postgres.py` (the adversarial e2e); `tests/e2e/test_cognition_transition_vertical_postgres.py` (new) |
| **PostgreSQL** | Yes, for both forgery classes and for the vertical |
| **Known limitations** | None against this pass condition. The gap this session closed was narrower than the requirement: every pre-existing test built its `RelationJudgment` objects *in the test*, so nothing showed that **admitted** relations — rows in the database — reach the evaluator. The new vertical asserts the stored row *is* the object inside the snapshot, field by field, and reloads through fresh store objects |
| **Verdict** | **READY** |

### EPI-006 — first-class typed Conflict; blocking prevents ALLOW; closure records its event

| | |
|---|---|
| **§26 pass condition** | a blocking Conflict of a type listed in `blocking_conflict_policy` forces `outcome != ALLOW` and appears in `blocking_conflict_ids[]`; an AUTHORITY_CONFLICT from an INCOMPARABLE comparison creates a Conflict **linked to the auto-created ReviewItem**; resolving a Conflict without a `resolution_event_id` is rejected |
| **Implementation** | `src/lab_brain/core/models/conflict.py`; `src/lab_brain/core/repositories/conflicts.py`; migrations `011a`, `011c`, `011d` |
| **Test** | `tests/contract/test_conflict.py`; `tests/integration/test_conflicts_postgres.py` — including `test_an_incomparable_comparison_creates_a_linked_conflict_and_review`, which records no conflict; `tests/integration/test_review_conflict_commit_invariant_postgres.py` |
| **PostgreSQL** | Yes. `011d`'s commit-boundary invariant, the raw-SQL half-state refusals and the two real concurrency races are all P13's and are re-run unchanged |
| **Known limitations** | None against this pass condition. The same traceability gap as EPI-004 applied here and is closed the same way |
| **Verdict** | **READY** |

### VER-006 — typed Prediction bound to an OutcomeSpace version; side-effect-free hypothetical

| | |
|---|---|
| **§26 pass condition** | a Prediction with an out-of-space `expected_outcome` is rejected at admission; `evaluate_hypothetical` persists nothing (no relation rows, no BeliefRevisionEvent, projection unchanged); an action with no bound Prediction over its `produces` is reported NOT sufficient; identical inputs return an identical TransitionDecision |
| **Implementation** | `src/lab_brain/core/models/prediction.py` (`Prediction`, `OutcomeSpace`, `RelationJudgmentTemplate`, `bind`); `TransitionPolicy.evaluate_hypothetical`; `src/lab_brain/core/sufficiency.py` |
| **Test** | `tests/contract/test_prediction_sufficiency.py` (23 tests); `tests/e2e/test_hypothetical_evaluation_postgres.py` (5 tests) |
| **PostgreSQL** | Yes, for the "persists nothing" clause — counted before and after, three tables named individually, and the specific hypothetical `relation_id` asserted absent. §26 says contract/unit; a claim about persistence deserves rows to count |
| **Known limitations** | `evaluate_sufficiency` implements §9.1's first disjunct only, and **says so in its return value**: `SufficiencyResult.unevaluated_clauses` names the two it did not evaluate. (a) `plausible(y)` clauses 3–4 need a DomainPack `ValidationReport` and Capability feasibility — that is VER-004, allocated to M3. (b) "y resolves at least one blocking Conflict" is deferred *on principle*: deciding that an outcome resolves a conflict is what a reviewer does, and `v3.3-a14` made the resolution a durable human record precisely so nothing could infer it. Predictions are not persisted; that table is the other half of Appendix A's `011` slot and lands with the Verification Planner (M4). All three are declared in `UNBOUND` in `schema_drift.py` with reasons |
| **Verdict** | **READY** |

### OPS-002 — ReviewQueue capacity, SLA/expiry, human-review Capability

| | |
|---|---|
| **§26 pass condition** | queue depth/capacity changes human-review capability availability and planner `earliest_available_at`; a ReviewItem without `stakes` or without an SLA/expiry policy is refused at creation; an item past its expiry leaves PENDING via the declared policy rather than parking there indefinitely |
| **Implementation** | migration `011e` (`review_queue_policies`, the deadline trigger, escalation re-priced); `src/lab_brain/core/review_queue.py` (`ReviewQueuePolicy`, `HumanReviewCapability`, `ReviewQueue`, `price_review`); `SqlReviewQueuePolicyStore` |
| **Test** | `tests/integration/test_review_queue_postgres.py` (22 tests) |
| **PostgreSQL** | Yes. The "refused at creation" clause is a trigger, tested by raw SQL for all four shapes: blank stakes, no policy, policy named but unpriced, expiry before due |
| **Known limitations** | Capacity **does not** refuse an escalation, and the asymmetry is deliberate: §26 says depth and capacity change *availability*. A full queue that rejected a blocking conflict's review would leave it OPEN with nobody assigned — still blocking the belief, and now invisible to the queue meant to report the backlog. `earliest_available_at` is computed from the earliest outstanding `due_at` and the declared default SLA; there is no per-reviewer calendar, which §14.4.1's "actor schedule" would eventually want. `reviewer_minutes_per_day` is declared and stored but not yet consumed by a planner — there is no planner in M0b |
| **Verdict** | **READY** |

### OPS-003 — execution trace linking episode → retrieval/LLM/job/run/artifact with costs

| | |
|---|---|
| **§26 pass condition** | one episode trace reconstructs retrieval → LLM → job → run → artifact and the associated cost entries |
| **Implementation** | `src/lab_brain/core/models/execution_span.py`; `src/lab_brain/core/repositories/observability.py`; migrations `010a`/`010b` |
| **Test** | `tests/e2e/test_episode_trace_postgres.py`; `tests/integration/test_execution_spans_postgres.py`; `tests/contract/test_execution_span.py`; `tests/contract/test_dispatch_seam.py` |
| **PostgreSQL** | Yes. Closing a span is atomic with its cost refs (`010b`), and a parent span must be in the same trace — a cross-trace edge would let a corrupt parent be laundered into a plausible tree |
| **Known limitations** | None against this pass condition |
| **Verdict** | **READY** |

---

## Requirements NOT ready

**None.** All ten are READY.

Two requirements that a reader might expect to see promoted are deliberately absent:

- **UX-005** stays `TODO` in M1. `review_items` and now `review_queue_policies` are a shared
  foundation, and T-UX-005 additionally requires the NEEDS_REVIEW *user experience*. OPS-002 is the
  governance/backend capability contract; claiming UX-005 on this basis would claim a requirement
  whose test nothing runs.
- **EPI-001** (`Hypothesis` as an entity) is M3 and is why `stakes` is an episode parameter.

---

## Spec contradictions and AGT-015 gates discovered

**None.** No spec amendment was needed and none was written. Three places where the spec required
a reading rather than a change, all resolved against existing amendments and recorded in code:

1. **`belief_level`** — §17.13 marks it optional and §8.1 only 建議s an ordinal scheme with no
   thresholds. Read as: the field exists and core does not populate it. Not escalated, because
   §17.13 already admits the absence.
2. **The comparator is named by the caller** — `TransitionPolicy` has no field pointing at an
   `AuthorityPolicy` and `AuthorityPolicy` carries no domain. §8.2.1 passes the comparator as an
   *argument* to `evaluate`, so choosing it is the caller's act. Inferring it from `policy.domain`
   would be core picking a DomainPack comparator on a hypothesis's behalf, which §10.5.1 forbids.
3. **Capacity vs. availability** — §14.4 requires a queue capacity and §26 says depth and capacity
   change availability. Neither says a full queue rejects work, and rejecting it would be
   fail-open in effect. Implemented as reporting, documented in `011e`'s header.

---

## Verification

Run in the mandated order, with the full PostgreSQL profile last so the outcome report the ratchet
reads is the one from the run that enabled the gate.

| gate | result |
|---|---|
| `ruff check src tests scripts` | clean |
| `ruff format --check` | clean, 116 files |
| `mypy` (strict) | clean, 55 source files |
| Backend-free suite | **712 passed / 342 skipped** (AGT-007) |
| Migrations from empty | **22** declared, 22 applied |
| Migration idempotency | `pending 0` on re-run |
| Full suite, `postgres` profile | **1054 passed**, 0 failed |
| Executed-coverage ratchet | exit 0 — 849 marked tests, 16 requirements with a passing test |
| `update_status.py --check` | up to date |
| Spec conformance / traceability | 149 passed, **59 ↔ 59** |
| Obligation inventory | 72 occurrences, in sync |
| Mutations | **7 SQL on `011e`, all red** (each guard deleted, the one-active-policy index downgraded to non-unique, and the idempotence check moved after the policy lookup) |

---

## Locked P13 contracts — re-asserted, not regressed

`011e` replaces `authority_conflict_escalate` a second time, so every locked property of `011c`'s
version is re-asserted by test rather than assumed:

- idempotent retry returns the existing review (`test_a_retried_escalation_is_still_idempotent_after_the_policy_landed`);
- the UPDATE is still conditioned on `review_id IS NULL`, and the real two-connection escalation
  race still yields exactly one winner with no orphan;
- a closed conflict is still refused; review and link are still one statement;
- `011d`'s commit-boundary invariant holds after an expiry sweep — the one path that terminalizes a
  review without a human deciding, and therefore the most likely place for the P12/P13 half-state
  to return (`test_the_expiry_leaves_no_forbidden_review_conflict_pair`).

No applied migration was edited. `005a`–`005d` and `011a`–`011d` are untouched.

---

## For the next session — M1 Research Memory + Evidence-Aware Hierarchical Chunking, LOCKED

No chunker and no embedding index exists, and none was built here. The seven requirements carry
forward verbatim and are **not** to be replaced with LangChain-style fixed-token chunking:

1. **Minimum evidence boundary** — the smallest complete boundary that can independently support
   one claim or observation. Conditions and results must not be split apart.
2. **Structure-first** — section / subsection / paragraph / table / figure-caption / code-log block
   take priority over token counts.
3. **Table/figure context binding** — a table retains header, unit and row context; a figure is
   bound to its caption **and** the relevant surrounding text.
4. **Conditions + locator + provenance** — a chunk resolves back to an Artifact/SourceWork locator
   and retains conditions, units and method/provenance.
5. **Fixed-token only as fallback** — secondary subdivision or a token safety limit when an
   evidence unit is too large. Never the primary splitter.
6. **Scientific retrieval benchmark vs a fixed-token baseline** — a fixed fixture measuring at
   minimum evidence-boundary completeness, correct locator recovery, condition retention,
   table/figure retrieval, and candidate recall/precision.
7. **Vectors do candidate retrieval only** — a vector chunk is **not** the evidence, and the final
   `EvidenceBundle` still passes condition/source/authority filtering. Treating a chunk as the
   evidence body would make the epistemic record depend on an embedding model's version, which is
   what EVI-005's comparator-version binding exists to prevent elsewhere.

### Open work the M1 session should know about

- **`UX-005`** needs the NEEDS_REVIEW user experience on top of OPS-002's queue.
- **`EPI-001`** (`Hypothesis` as an entity, §8's full admission certificate) is M3; until then
  `stakes` is supplied by the episode's caller.
- **`VER-004`** owns `plausible()`'s DomainPack half, which `evaluate_sufficiency` names as
  unevaluated.
- **Prediction persistence** is the other half of Appendix A's `011` slot.
- **`reviewer_minutes_per_day`** is stored and unconsumed until a planner exists.

---

## Operational note

Dev database `lab_brain` still carries a superseded `005c` and still needs dropping and re-creating
rather than migrating forward — `scripts/migrate.py` refuses it with a drift error, which is the
check working. No applied migration was edited in this session.

Scratch databases created here, all disposable: `lab_brain_p13`, `lab_brain_p13empty`,
`lab_brain_mut011e0`…`lab_brain_mut011e6`. P12's and P13's are listed in their own handoffs.
