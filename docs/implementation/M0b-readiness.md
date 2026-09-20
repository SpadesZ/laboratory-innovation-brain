# M0b — Execution/Governance Foundation: readiness for maintainer sign-off

Baseline: `6fd8093bab8a9c54fed9b618eced14ba86d20ee2` (P13, independent maintainer **HARD PASS**).
Revised after the M0b sign-off audit returned **CONDITIONAL FAIL** on
`37c33fce96364daacc8121bf88937001536bcea5` with two P1 closure gaps.

Revised again after the maintainer ruled on SPEC-ISSUE-012 (adopt Reading B, `v3.3-a15`).

Revised a third time after independent maintainer review of `v3.3-a15` passed its design and
returned one remaining P0 at the database persistence boundary, closed here by `v3.3-a16` and
migration `011g` — see "`v3.3-a16`: the closure-proof substitution" below.

**Status: READY_FOR_MAINTAINER_SIGNOFF — all ten requirements READY.**
[SPEC-ISSUE-012](../spec_issues/SPEC-ISSUE-012-review-expiry-has-no-authorable-closure-event.md)
is **RESOLVED**; no GATE issue is open against M0b.

`docs/milestones.yaml` still records M0b as `IN_PROGRESS` and is deliberately not edited — sign-off
is the maintainer's act, not this session's.

---

## Audit response — what changed since `37c33fc`

### P1-A — OPS-002 expiry liveness: **escalated, ruled on, then implemented**

The audit was right that the seam existed with no production caller. Adding the caller was four
lines, and the instruction to first determine *who may author the expiry closure event* is what
stopped it. The determination came back negative, the gate was raised, and the maintainer ruled:
adopt Reading B with a narrow `GovernanceEvent`. `v3.3-a15`, migration `011f` and
`lab_brain.core.review_expiry.ReviewExpiryProcessor` implement that ruling — see
"`v3.3-a15`: what the ruling changed" below.

The evidence that produced the gate is kept here because it is what makes the shape of the fix
legible.

The chain is rigid and every link is locked: an expired item must leave PENDING → terminal
ReviewItem → `decision_ref` → durable `ReviewResolution` → `belief_revision_event_id` **NOT NULL**
(`011c`) → `Conflict.resolution_event_id` FK to `belief_revision_events` (`011a`). So an automatic
expiry must author a **`BeliefRevisionEvent`**, and §17.13 gives that object exactly one meaning:
a hypothesis's belief state changed. **An unanswered timeout is not a transition.**

Probed against the real schema rather than argued:

| Construction | Result |
|---|---|
| No-op `TransitionPolicy(ACTIVE → ACTIVE)` to cite | **unrepresentable** — `005b` `CHECK (from_state <> candidate_to_state)` |
| Non-genesis event citing the admission policy | refused by `005c` |
| Real transition `ACTIVE → INCONCLUSIVE`, policy honouring the conflict | `NEED_HUMAN_REVIEW` → no ALLOW → no event → **circular** |
| Real transition, policy ignoring the conflict | `ALLOW` with *no required relation types* — a scheduler declaring a hypothesis INCONCLUSIVE on no evidence |
| Genesis event for a fabricated hypothesis id | accepted — **and this is what the M0b fixture does** |

The last row is the finding that settled it. The old OPS-002 tests passed because their
closure-event helper wrote a genesis event for `f"hyp:{event_id}"` — a hypothesis that does not
exist — to satisfy the foreign key. **That helper is now deleted, not adapted**, and
`test_the_expiry_writes_no_belief_revision_event_and_leaves_the_projection_alone` counts the belief
log to prove nothing invents a subject any more.

### `v3.3-a15`: what the ruling changed

`GovernanceEvent` under §17.19.1 — *a governance/operational state change that does NOT itself
alter scientific belief*. It may not be accepted as `BeliefRevisionEvent` evidence, may not appear
in a belief replay, and may not mutate `EpistemicStateProjection`; a scheduler may not author a
belief revision at all.

Three bounds are what keep the fix narrow, and each is enforced rather than asserted:

- **One event type.** `REVIEW_EXPIRY` and nothing else. A generic audit-event vocabulary would be a
  second way to close any Conflict without moving a belief. Opening the CHECK goes red.
- **One permitted combination.** `GOVERNANCE` requires `outcome = EXPIRED`; a human resolution
  (APPROVED | CORRECTED | REJECTED) may not close against one, and a conflict with no review may
  not close against one at all. Both go red when removed.
- **Two actors, recorded separately.** `ReviewQueuePolicy.declared_by_actor_id` is the standing
  authority; the event's `actor_id` is the executor. §17.19.1 forbids inferring the first from the
  second, so an executing SERVICE actor does not become a decision-maker.

The closure reference is generalised to the typed pair
`(resolution_event_kind, resolution_event_id)` on both `review_resolutions` and `conflicts`, with a
composite FK per kind — SQL has no polymorphic foreign key, and those composites are what make a
cross-project closure *unrepresentable* rather than merely wrong. The canonical id is a
`GENERATED ALWAYS AS` column so the pair cannot disagree with itself. `011d`'s commit-boundary
invariant was widened to compare the pair, not just the id.

`ReviewExpiryProcessor` is the production caller. It reads each item's **own** queue-policy
version rather than whichever policy is active — an expiry re-interpreted under a policy the
reviewer never saw is not the deadline they were given, and `review_expire` refuses a mismatch.
`now`, `actor_id` and the id source are parameters, so the sweep reads no clock and a retry
proposes the same primary keys. `ReviewQueue.expire` is **deleted**: it built the resolution
itself and so could produce an EXPIRED closure citing a belief revision, which is a second path
writing the wrong kind of event.

### `v3.3-a16`: the closure-proof substitution

Independent maintainer review passed `v3.3-a15`'s design and found one P0 left, at the database
persistence boundary. `011f` checks the typed pair from both sides — the Conflict and the
ReviewResolution must agree on `(resolution_event_kind, resolution_event_id)`. That proves the two
halves of a closure tell one story. **It does not prove the story is that review's**, because
nothing loaded the referenced `GovernanceEvent` to ask:

```
Review A, Conflict A, QueuePolicy P  ->  GovernanceEvent G   (entirely legitimate)

raw SQL then presents G as proof that review B expired:
    ReviewResolution B (EXPIRED, governance_event_id = G)
    Review B   -> EXPIRED
    Conflict B -> ACCEPTED_AS_OPEN_QUESTION, governance_event_id = G
```

Same project, same policy, a real `REVIEW_EXPIRY` event — and every check `011f` makes passes, so
it committed. A block lifted on an authority never granted for it. This is `v3.3-a14`'s closure
traceability clause ("an arbitrary event that merely belongs to the same project MUST NOT be
accepted as closure proof") reappearing one indirection further out.

Why no test caught it: every expiry test drove `ReviewExpiryProcessor`, which never asks for the
forbidden shape. The far end of the reference was exercised by the happy path and held by nothing —
the same finding as the five `v3.3-a15` mutations, at the one link they did not reach.

`v3.3-a16` states what "the same chain" means and `011g` makes the sentence executable, by
**extending `011d`/`011f`'s commit-boundary invariant rather than adding a second notion of closure
validity** — two independently maintainable definitions of "valid closure" disagree eventually, and
a writer then picks the one that says yes. Where `resolution_event_kind = GOVERNANCE`, the
referenced event must itself satisfy: `event_type = REVIEW_EXPIRY`, `subject_type = REVIEW_ITEM`,
the same `project_id` as the ReviewItem / ReviewResolution / linked Conflict, `subject_id` = that
review, `related_conflict_id` = that conflict and only that one, `policy_id` / `policy_version` =
the version the item was priced by, that `ReviewQueuePolicy` exists, `declared_by_actor_id` = that
policy's declarer, and `actor_id` = the resolution's `resolved_by_actor_id`.

Two narrower repairs ship with it:

- **`declared_by_actor_id` is required on a REVIEW_EXPIRY.** `v3.3-a15` made the queue policy's
  copy NOT NULL and left the event's optional, so for the only event type that exists a correct
  value always existed and "absent" stopped being an honest shape. Written as a CHECK keyed on
  `event_type` rather than a bare NOT NULL, so a second kind would have to state its own
  provenance rule instead of inheriting this one by accident.
- **An inactive executor fails closed.** An unknown executor already failed on the actors foreign
  key; `active = FALSE` did not, so a decommissioned service account could keep expiring reviews.
  Enforced as a `BEFORE INSERT` trigger and deliberately **not** in the deferred invariant: the
  question is whether the executor was active *when the sweep ran*, and re-asking it at every later
  commit would make deactivating a service account retroactively invalidate expiries that were
  legitimate when written. A test pins that distinction.

Nothing locked was redesigned. `GovernanceEvent` still admits `REVIEW_EXPIRY` and nothing else,
expiry still writes no `BeliefRevisionEvent` and leaves `EpistemicStateProjection` untouched,
`ACCEPTED_AS_OPEN_QUESTION` still closes the instance rather than the question, and no applied
migration was edited — `011g` is forward-only, like every one before it. No
scientific-authority or approval-scope system was added; the obligation is on the persistence path,
where `v3.3-a14` already put it.

### P1-B — SYS-001 exact conformance/traceability: **fixed**

Two things, both real.

**The static obligation was executing under no requirement.** §26 types T-SYS-001 `architecture`
and names "static/conformance test rejects … support arrays on Attestation/Hypothesis". Those
assertions lived in `tests/unit/test_core_architecture_invariants.py`, deliberately unmarked, while
the marked SYS-001 module was an e2e that performed none of them. They now live in
`tests/unit/test_sys001_static_conformance.py` under SYS-001/T-SYS-001 — one module, one pair, no
cross-product — and carry **no `postgres` marker**, because a static conformance check that needed
a database would be skipped by the very run that proves AGT-007.

**Hypothesis vs HypothesisView is resolved by building the model, not by asserting equivalence.**
`docs/milestones.yaml` moved SYS-001 to M0b precisely so "Hypothesis and EpistemicStateProjection
could both be tested", and the previous revision of this document contradicted it by calling
`Hypothesis` an M3 concern and using `HypothesisView` as a surrogate. The milestone record was
right: §8.1's certificate is a **data contract**, and what belongs to EPI-001/M3 is the *admission
gate* that judges its contents. `lab_brain.core.models.hypothesis.Hypothesis` is that certificate —
frozen, `extra="forbid"`, typed `prediction_ids` pointing at VER-006's `Prediction`, a required
falsifier, and no support arrays.

It **omits `status_projection` and `belief_level_projection`**, which §17.5 lists four lines above
"Status is rebuilt from BeliefRevisionEvent + TransitionPolicy". The second sentence wins: a stored,
writable status is exactly the bypass T-SYS-001 requires be rejected. Declared in `UNBOUND` with
that reason, and asserted — `FORBIDDEN_STATUS_FIELDS` is pinned exactly, and a mutation emptying it
goes red.

### P2 — both done

- **Stale documentation corrected.** `test_core_architecture_invariants.py`'s docstring claimed
  SYS-001 was unexercisable because "EpistemicState and Hypothesis … do not exist yet". Both exist;
  the docstring now records what it used to say and why it changed.
- **`earliest_available_at` can no longer report the past.** A full queue whose items are *all*
  breached returned `min(due_at)`, a moment already gone — a planner would have scheduled against a
  saturated queue on the strength of a date proving the opposite. §14.4.1 defines no formula, so the
  floor is a stated implementation rule: `max(now, projected)`. Two fixtures pin it, including the
  positive control that a full-but-unbreached queue still reports its real next slot.

M0b exit gate: *event replay + transition/authority tests + ACL/budget/trace contracts pass;
testable without a DomainPack.* The suite is green with no backend at all (722 passed / 391
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
| **Implementation** | `src/lab_brain/core/episode.py` (the path); `src/lab_brain/core/models/hypothesis.py` (§8.1 certificate); `src/lab_brain/core/repositories/evidence.py` (the Attestation → RelationJudgment leg); `src/lab_brain/core/belief.py` (event → projection) |
| **Test** | `tests/unit/test_sys001_static_conformance.py` (static half, **under SYS-001/T-SYS-001**, no backend); `tests/e2e/test_episode_cognition_path_postgres.py` (17 tests, dynamic half) |
| **PostgreSQL** | Dynamic half yes — the bypasses are *attempted* against the real schema rather than assumed impossible: no writable belief-status column anywhere, no projection table, `AuthorizedRevision` unconstructable, an LLM verdict with nowhere to go. Static half deliberately backend-free (§26 types it `architecture`) |
| **Known limitations** | §8's **Hypothesis Admission Gate** — judging whether a mechanism is a mechanism or a falsifier could falsify — is EPI-001 in M3. The certificate is held here; its contents are not judged. `Hypothesis` omits §17.5's `status_projection` / `belief_level_projection` by design (see the audit response above) and is listed in `UNBOUND` with that reason. `stakes` is an episode parameter until EPI-001 |
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
| **Implementation** | `src/lab_brain/core/models/conflict.py`; `src/lab_brain/core/repositories/conflicts.py`; migrations `011a`, `011c`, `011d`, `011f`, `011g` |
| **Test** | `tests/contract/test_conflict.py`; `tests/integration/test_conflicts_postgres.py` — including `test_an_incomparable_comparison_creates_a_linked_conflict_and_review`, which records no conflict; `tests/integration/test_review_conflict_commit_invariant_postgres.py`; `tests/integration/test_governance_event_chain_binding_postgres.py` (`v3.3-a16`) |
| **PostgreSQL** | Yes. `011d`'s commit-boundary invariant, the raw-SQL half-state refusals and the two real concurrency races are all P13's and are re-run unchanged. `v3.3-a16`'s chain binding is exercised by nine raw-SQL adversarial cases plus two positive controls |
| **Known limitations** | None against this pass condition. The same traceability gap as EPI-004 applied here and is closed the same way. "Resolving a Conflict without a `resolution_event_id` is rejected" now means *without the event this review's own resolution produced* — `v3.3-a16` closed the last shape in which an event of the right form but the wrong provenance was accepted |
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
| **Implementation (liveness)** | [SPEC-ISSUE-012](../spec_issues/SPEC-ISSUE-012-review-expiry-has-no-authorable-closure-event.md) is **RESOLVED**. `v3.3-a15` + migration `011f` supply the closure event an automatic expiry may author (`GovernanceEvent(REVIEW_EXPIRY)`); `v3.3-a16` + migration `011g` bind that event to the chain it closes. `src/lab_brain/core/review_expiry.py` — `ReviewExpiryProcessor` — is the **production caller**, and every liveness test drives it rather than the seam |
| **Test** | `tests/integration/test_review_expiry_postgres.py` (liveness through the production caller, including the executor guards); `tests/integration/test_governance_event_chain_binding_postgres.py` (`v3.3-a16`, under EPI-006); `tests/integration/test_review_queue_postgres.py` (creation-time refusals and the Capability) |
| **PostgreSQL** | Yes. The "refused at creation" clause is a trigger, tested by raw SQL for all four shapes: blank stakes, no policy, policy named but unpriced, expiry before due. The liveness clause is exercised end to end against the real schema, including two concurrent sessions producing exactly one expiry |
| **Known limitations** | None against this pass condition; **expiry liveness is discharged**. Capacity **does not** refuse an escalation, deliberately: §26 says depth and capacity change *availability*, and a full queue rejecting a blocking conflict's review would leave it OPEN with nobody assigned. `earliest_available_at` is a **lower bound** clamped to `now`, computed from the earliest outstanding `due_at`; there is no per-reviewer calendar, which §14.4.1's "actor schedule" would eventually want, and `reviewer_minutes_per_day` is stored but unconsumed until a planner exists |
| **Verdict** | **READY** — depth, capacity, `earliest_available_at`, stakes, the SLA/expiry policy at creation **and liveness** are all discharged |

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

`UX-005` stays `TODO` in M1 and is not one of the ten: `review_items`, `review_queue_policies` and
now `governance_events` are a shared foundation, and T-UX-005 additionally requires the
NEEDS_REVIEW *user experience*. `EPI-001` (§8's admission gate) stays M3.

Two requirements that a reader might expect to see promoted are deliberately absent:

- **UX-005** stays `TODO` in M1. `review_items` and now `review_queue_policies` are a shared
  foundation, and T-UX-005 additionally requires the NEEDS_REVIEW *user experience*. OPS-002 is the
  governance/backend capability contract; claiming UX-005 on this basis would claim a requirement
  whose test nothing runs.
- **EPI-001** (`Hypothesis` as an entity) is M3 and is why `stakes` is an episode parameter.

---

## Spec contradictions and AGT-015 gates discovered

**One, raised and now resolved: [SPEC-ISSUE-012](../spec_issues/SPEC-ISSUE-012-review-expiry-has-no-authorable-closure-event.md)** — an
automatically expired ReviewItem had no closure event anyone could author. Five readings with
different scientific outcomes, the probe evidence and the maintainer's ruling are in the issue.
Resolved by `v3.3-a15`, with `v3.3-a16` supplying the one clarification the implementation of that
ruling turned out to need. **No GATE issue is open against M0b.**

`v3.3-a16` is **not** a new contradiction and was not raised as one. §17.19.1 already required the
closure pair to hold "for the same review/conflict chain"; what it did not do was say what that
chain is, which left the sentence unexecutable in exactly the way `v3.3-a14` had left
`decision_ref`. Same shape of amendment, same resolution: no new obligation, no new Requirement or
Test ID, an existing one made uniquely enforceable.

The milestones.yaml-vs-readiness contradiction the audit flagged on `Hypothesis` was **not** a spec
ambiguity and is not escalated: the milestone record was right, the previous readiness text was
wrong, and the fix was to build the certificate (see P1-B above).

Three further places where the spec required a reading rather than a change, all resolved against
existing amendments and recorded in code:

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
| `ruff format --check` | clean, 122 files |
| `mypy` (strict) | clean, 58 source files |
| Backend-free suite | **722 passed / 391 skipped** (AGT-007) |
| Migrations from empty | **24** declared, 24 applied |
| Migration idempotency | `pending 0` on re-run |
| Full suite, `postgres` profile | **1113 passed**, 0 failed |
| Executed-coverage ratchet | exit 0 — 915 marked tests, 16 requirements with a passing test |
| `update_status.py --check` | up to date |
| Spec conformance / traceability | 149 passed, **59 ↔ 59** (`v3.3-a15` and `v3.3-a16` add no Requirement/Test ID) |
| Obligation inventory | 72 occurrences, in sync — neither amendment adds a §6–§16 hard-obligation keyword |
| Mutations, `v3.3-a16` guards | **13, all red** (11 SQL + 2 Python) — see below |

### The five `v3.3-a15` mutations that survived first

Every one of them was reached only through the production caller, which never asks for the
forbidden shape -- so the guard behind it was exercised by the happy path and held by nothing.
That is the P12 blank-rationale lesson in a new place, and it cost five tests:

- kind/column agreement (`011f` CHECK), raw SQL, both directions;
- `conflict_close`'s (kind, id) pair check, via a mid-transaction mismatch;
- `011d`'s commit-boundary pair check, generalised;
- `review_expire`'s deadline guard, reached directly rather than through the sweep;
- `declared_by_actor_id` NOT NULL on a queue policy.

### The thirteen `v3.3-a16` mutations, each held by its own negative test

Disabling any one of these turns the named tests red, and nothing else:

| guard | mechanism | test that holds it |
|---|---|---|
| `subject_id` = this review | `011g` invariant | the substitution case, and its isolated twin |
| `related_conflict_id` is a conflict this review gates | `011g` invariant | event names another review's conflict |
| `related_conflict_id` is *this* conflict | `011g` invariant | event claims it closed nothing |
| `policy_id` = the item's | `011g` invariant | event cites a different policy |
| `policy_version` = the item's | `011g` invariant | event cites a later version of the right policy |
| `declared_by_actor_id` = the policy's declarer | `011g` invariant | event restates a different author |
| `actor_id` = the resolution's resolver | `011g` invariant | two accounts of who ran the expiry |
| the executor is ACTIVE | `011g` trigger | inactive executor, via the sweep **and** via raw SQL |
| no cross-project event, resolution side | `011f` composite FK | parametrized, its own constraint name |
| no cross-project event, conflict side | `011f` composite FK | parametrized, its own constraint name |
| `declared_by_actor_id` present on a REVIEW_EXPIRY | `011g` CHECK | raw-SQL insert with none |
| the same rule in the model | validator | absent, and blank, separately |

Three further facts are **unrepresentable rather than checked**, and the migration says so instead
of shipping branches no test can reach: `event_type` and `subject_type` are CHECK-constrained to one
value each (folded into the invariant's lookup predicate so widening the vocabulary is a decision
somebody has to make there), and the event's project is held by the composite foreign keys above.
Each is proven by the mechanism that actually refuses it.

### The one `v3.3-a16` test that survived its own mutation

`test_an_event_from_another_project_cannot_be_cited_at_all` originally drove the whole four-
statement closure and matched on `governance_event_in_project` — a substring of **both**
`review_resolutions_governance_event_in_project` and `conflicts_governance_event_in_project`.
Relaxing either composite foreign key alone therefore left it green, because the other still
fired. It read as proof that both hold and was proof that one of them does. It is now
parametrized, attempting each half alone against its own constraint name, and relaxing either is
individually red. Found by the mutation run, not by review.

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

`011g` replaces `review_conflict_invariant_assert` a third time, so the same discipline applies:
every check `011d` and `011f` put in that function is carried across verbatim, and
`test_the_production_sweep_still_produces_a_chain_the_invariant_accepts` asserts that the supported
path still satisfies the tightened boundary — the failure mode a tightening like this actually has
is refusing the legitimate write, in a path nothing watches run.

No applied migration was edited. `005a`–`005d` and `011a`–`011f` are untouched.

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
`lab_brain_mut011e0`…`lab_brain_mut011e6`, and for `v3.3-a16`: `lab_brain_m0b`,
`lab_brain_m0bempty`, `lab_brain_mut`. P12's and P13's are listed in their own handoffs.
