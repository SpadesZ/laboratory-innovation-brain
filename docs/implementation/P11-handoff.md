# P11 — contract holes, conflict persistence, authority review loop

Baseline: `6bf1d3b430518a7b3289178f345cb679049d2cdf` (P10, **CONDITIONAL FAIL**, targeted rework).
Phase 0's scope fix and `v3.3-a13` were PASS / LOCKED and are untouched.

| Phase | SHA | Content |
|---|---|---|
| A-fix / B-fix | `037ad167f14e573d314fc57393874cd991c3b121` | four contract holes |
| C | `8a7df062cc9340bcd93c9478e888c67a7e722105` | EPI-006 PostgreSQL persistence (`011a`) |
| D | `debcb01c9ca420e6b64436a49cd872cf7fd43095` | EPI-004 ↔ ReviewItem loop (`011b`) |

---

## Phase A-fix / B-fix — four holes, two of them mine specifically

### 1. Transitivity, declined and rationalised

The P10 version of `partial_order_violations` did not check transitivity, and argued in its own
docstring that "a partial order may legitimately contain INCOMPARABLE pairs that break naive
chains." That is true, and it was beside the point: the fix is to require transitivity
**conditionally**. `A>B, B>C, C>A` passed and is not an order under any reading. The audit was
right to call it a rationalisation for not doing the harder thing.

The rule now: if `a` dominates `b` and `b` dominates `c`, then `a` must dominate `c`, strictly
unless both steps were EQUIVALENT. A chain requirement arises only when both antecedent
comparisons are STRONGER or EQUIVALENT, so an INCOMPARABLE pair generates none of its own — which
is what keeps genuine partial orders legal, and is the distinction the earlier version failed to
make rather than a reason to skip the check. EQUIVALENT is transitive in its own right, or a
comparator could treat equivalence as "close enough" pairwise and produce a three-way set no
threshold evaluates consistently.

Four adversarial comparators, each failing exactly one law, all of which passed before: the cycle;
the chain that does not compose (`A>B, B>C`, `A` INCOMPARABLE `C`); inconsistent equivalence; and
a mixed chain that comes back EQUIVALENT. A fifth is the **control** — `A>B` with `C` unrankable
against both — because without it a check that simply demanded every pair rank would satisfy the
other four while forbidding exactly what §10.5.1 permits.

### 2. `compare` and `meets` could diverge

§10.5.1 declares `meets` alongside `compare`, so per the maintainer ruling it is kept and a
conformance law added rather than deleted. Nothing tied the two together, and a DomainPack whose
`meets` returned True where `compare` said WEAKER would produce an **ALLOW on insufficient
authority** — `evaluate` tests INCOMPARABLE via `compare` and then asks `meets` for the threshold,
so a divergence is a silent promotion, not an untidiness. The law: `meets(required, candidate)` is
true exactly when `compare(candidate, required)` is STRONGER or EQUIVALENT. Both directions are
tested, including the under-permissive one.

### 3. Conformance was not enforced anywhere

`AuthorityPolicy` gained `authority_classes`, declared by the DomainPack because core cannot
enumerate a domain's vocabulary, and `AuthorityPolicyRegistry.register` now verifies §10.5.1's laws
over exactly that set. An empty declaration is refused rather than treated as nothing to check,
since it would pass every law trivially. A conformance suite a DomainPack is merely *encouraged*
to run is a suite the DomainPack under deadline does not run.

### 4. A comment claimed a guard that did not exist

`transition.py` carried a docstring saying `blocking_conflict_policy_is_known_vocabulary()` existed
to catch typos. **It did not exist anywhere in the repo.** That is the worst failure mode in this
codebase — a comment asserting a guard nobody wrote, which stops the next reader looking — and the
consequence was fail-open: `evaluate` matches on `ConflictType.value`, so `"SIM_TO_REAL_CONFLIC"`
matched nothing and the policy silently declared **no** blocking types, surfacing as an unexpected
ALLOW long after the typo. The validation is now real, runs at construction, names the unknown
value and lists the known ones. It immediately caught a placeholder in this project's own
determinism test, which declared `blocking_conflict_policy=("X",)`.

### 5. Terminal conflict states unblocked with no event

The closure obligation was written over one enum member while `blocks_transitions` treated three
statuses as closing, so a blocking conflict could be unblocked by setting its status to `EXPIRED`
with no event and no timestamp — exactly *只改 enum 就解除 block*. The rule is now stated over the
**consequence** and derived from `UNRESOLVED_CONFLICT_STATUSES`, so there is one definition of
"still blocking" and an eighth status cannot quietly create a fourth unblocking state with no
closure requirement. Parametrized over all three, in both directions.

**Eleven mutations, all red.** The first two restore exactly what P10 shipped.

---

## Phase C — EPI-006 persistence (`011a`)

Phase B left the contract enforced in the model and the in-memory store only, and said so. This is
the missing half, and it was not optional: the project has now found four separate places where
something wrote SQL instead of going through Python — an unauthorised belief event (P7), an event
with no Decision (P8), a semantically forged Decision reaching a projection (P9), and a
`model_copy` skipping a validator (`v3.3-a12`).

DB-enforced: project-scoped identity and reads; closed seven-value `conflict_type` and five-value
`resolution_status`; at least one subject ref; non-null `blocking`; and the closure invariant as an
**equality between two predicates**, so neither direction can be relaxed alone. `resolution_event_id`
is a composite FK into `belief_revision_events (event_id, project_id)` using `005c`'s UNIQUE, so a
conflict closed by another project's event is unrepresentable.

DELETE refused outright. UPDATE permitted for exactly one purpose — moving an unresolved conflict
to a terminal status with its closure event. Editing type, subjects, detection provenance, project
or `blocking` is refused; **`blocking = FALSE` is the one worth naming**, because it is the quietest
way to unblock a belief: the conflict stays OPEN and apparently untouched while the policy stops
seeing it. Re-resolving refused. OPEN ↔ UNDER_REVIEW stays legal and carries no closure, because
escalating is not resolving.

`conflict_close()` is one statement, scoped on both columns, conditioned on the row still being
unresolved — that condition is the concurrency guarantee: two callers racing cannot both succeed.

35 postgres tests, all negative except the round trips. One needed adjusting for a reason worth
recording: the unknown-status case originally passed no closure details, so the closure CHECK
refused the row before the vocabulary CHECK saw it — refused either way, but the test would have
passed with the vocabulary CHECK deleted.

---

## Phase D — EPI-004 ↔ ReviewItem (`011b`)

§8.2.1 states the flow and stops short of saying who performs it, which is why nothing did:
`evaluate` is pure (no clock, no I/O, no repository read), because `v3.3-a12` requires a stored
Decision to re-derive from its snapshot and a function that wrote rows could not be replayed. So
`evaluate` returns a `ReviewItemSpec` and `core/escalation.py` is the impure seam that acts on it.

The loop, end to end through the real stores:

    INCOMPARABLE -> NEED_HUMAN_REVIEW / AUTHORITY_INCOMPARABLE
      -> Conflict(AUTHORITY_CONFLICT, blocking=True)
      -> persisted ReviewItem(subject_type=AUTHORITY_CONFLICT, subject_id=conflict_id)
      -> conflict.review_id linked, in one statement
      -> unresolved conflict reaches the next HypothesisView
      -> promotion AND rejection stay blocked
      -> review resolution produces a belief revision event
      -> conflict closes against that event
      -> only then may the transition be reconsidered

Two of those are what a plausible implementation gets wrong. Raising the review reads as progress,
so the conflict moves to `UNDER_REVIEW` and **`UNDER_REVIEW` still blocks**. And *reconsidered* is
not *allowed*: after the closure the comparison is still INCOMPARABLE, so the decision escalates
again. Closing the conflict records that a human looked, not that the evidence became rankable. The
test then swaps in a comparator that genuinely ranks the evidence and asserts the same transition
passes — so the block really was the only thing in the way.

**One spec discrepancy, resolved rather than silently chosen.** §8.2.1 says the ReviewItem's
`subject_id` is the *hypothesis_id*; §17.19.3 says
`ReviewItem(CONFLICT | AUTHORITY_CONFLICT).subject_id` is a *conflict_id*. Both are normative and
they disagree. §17.19.3 is the more specific rule — it is the Conflict contract and the reason
`unresolved_conflicts[]` and `blocking_conflict_policy` share one object — so the review names the
conflict and the conflict names the hypothesis in `subject_refs`, leaving it one hop away, which is
the property §8.2.1 was after. Recorded in the module docstring for the maintainer to overrule if
that reading is wrong.

`011b` also turns `conflicts.review_id` into a checked composite FK, which `011a` had left
unchecked and said so. It immediately caught a Phase C test that raw-set `review_id = 'rvw:1'`.

**Shared foundation, not UX-005.** The same ReviewItem serves UX-005's NEEDS_REVIEW, but
T-UX-005's pass condition is ReviewQueue depth and measurably changed human-review Capability
availability, and neither exists. **UX-005 stays TODO.**

---

## Verification

| gate | result |
|---|---|
| Migrations from empty | **19** declared, 19 applied, `pending 0` on re-run |
| Full suite, `postgres` profile | **924 passed**, 0 failed |
| Backend-free | **678 passed / 246 skipped** (AGT-007) |
| `ruff check` / `ruff format --check` | clean |
| `mypy` (strict) | clean, 49 source files |
| Executed-coverage ratchet | exit 0 |
| `update_status.py --check` | up to date |
| Spec traceability | 59 ↔ 59 |
| Mutations | 11 (A-fix/B-fix), all red, restored green |

Covered by the above: authority transitivity adversarial + mutation; compare-vs-meets divergence
mutation; unknown conflict vocabulary mutation; all three terminal statuses' closure-event tests;
the postgres conflict raw-SQL negative battery; and the INCOMPARABLE → Conflict → ReviewItem →
still blocked → event-backed resolution e2e.

---

## Requirement status

Derived by `update_status.py` from milestone state plus marked tests — not hand-set.

| ID | Status | What is missing |
|---|---|---|
| `EPI-003` | IN_PROGRESS | §26's T-EPI-003 names `EpistemicStateProjection`; `BeliefProjection` has no `belief_level` or `unresolved_conflicts` |
| `EPI-004` | IN_PROGRESS | see below |
| `EPI-005` | IN_PROGRESS | cognition path: `evaluate` runs against hand-built `HypothesisView` / `RelationJudgment`; nothing derives those from admitted evidence |
| `EPI-006` | IN_PROGRESS | see below |
| `UX-005` | TODO | ReviewQueue depth and human-review Capability availability do not exist. Not claimed |
| `COST-001`, `OPS-003`, `SEC-002` | IN_PROGRESS | unchanged by this slice |

**Why EPI-004 and EPI-006 are still IN_PROGRESS, precisely.** The reason is shared and it is one
word in each §26 row: both say the ReviewItem is **auto**-created. Nothing calls the escalation
seam automatically. The vertical exists, is persisted, and is tested end to end — but it has to be
*invoked*, and the orchestration that would invoke it is `SYS-001`'s episode loop, which is TODO.
Marking either DONE would claim an automation that is one caller short.

Everything else in both rows is now satisfied: EPI-004's four comparison results, the INCOMPARABLE
escalation, the ReviewItem link and the promotion/rejection block; EPI-006's type-matched blocking,
`blocking_conflict_ids`, the AUTHORITY_CONFLICT → ReviewItem link, the closure-event requirement,
and the Postgres side of all of it.

---

## M1 Evidence-Aware Hierarchical Chunking — LOCKED HANDOFF, not implemented

No chunker and no embedding index was built in this slice. The six requirements, to be followed
when M1 opens and **not** to be replaced with LangChain-style fixed-token chunking:

1. **Minimum Evidence Boundary** — find the smallest complete evidence boundary that can
   independently support one claim or observation. Conditions and results must not be split apart.
2. **Structure-first** — section / subsection / paragraph / table / figure-caption / code-log block
   take priority over token counts.
3. **Table/figure context binding** — a table must retain header, unit and row context; a figure
   must be bound to its caption **and** the relevant surrounding text.
4. **Conditions + locator preserved** — a chunk must resolve back to an Artifact/SourceWork
   locator and retain conditions, units and method/provenance. **An embedding must never be the
   evidence itself.**
5. **Fixed-token only as fallback** — secondary subdivision or a token safety limit when an
   evidence unit is too large. Never the primary splitter.
6. **Retrieval benchmark** — a fixed scientific fixture comparing a fixed-token baseline against
   Evidence-Aware Hierarchical Chunking, measuring at minimum evidence-boundary completeness,
   correct locator recovery, condition retention, table/figure retrieval, and candidate
   recall/precision.

**Vectors do candidate retrieval only.** The final `EvidenceBundle` must still pass
condition/source/authority filtering. Treating a vector chunk as the evidence body would make the
epistemic record depend on an embedding model's version — precisely what EVI-005's
comparator-version binding exists to prevent elsewhere.

---

## Operational note

Dev database `lab_brain` still carries a superseded `005c` and needs dropping and re-creating
rather than migrating forward. No applied migration was edited. Scratch databases, all disposable:
`lab_brain_p11d`, `lab_brain_p11`, `lab_brain_p10`, `lab_brain_p9`, `lab_brain_a12`,
`lab_brain_a12b`, `lab_brain_a12final`, `lab_brain_pre005d`, `lab_brain_p7fix`,
`lab_brain_verify`, `lab_brain_pre005c`.
