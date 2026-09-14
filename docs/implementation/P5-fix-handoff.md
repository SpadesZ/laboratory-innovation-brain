# P5-fix — COST-001 correctness and approval security

Rolling handoff for the P5-fix slice. One section per phase, appended as each lands. The audited
baseline entering this slice is `a82939102ceaa24f4239af15d389158033f9eaf2` (P5 / M0b-2, CI run
`34769054039` green) — **not** yet PASSed by external audit, which is why this slice fixes it
rather than moving on to OPS-003.

Scope boundary: this slice touches COST-001 and the AGT-003 status guards only. `OPS-003`,
`EPI-003`/`EPI-005` and the rest of M0b stay untouched until P5-fix is PASSed.

A phase section is written **after** its commit exists, with the real SHA and the real test
counts. A pending phase says what it intends to do and nothing about what it achieved.

---

## Phase A — spec closure (DONE)

**SHA** `6c8e4718da9e8edde88856b4f8a14fe09071d899`

**Done**

- `SPEC-ISSUE-009` raised and ruled: COST-001 requires the ledger to record tokens; §9.4's
  `CostVector` — the only type §17.17 lets a ledger entry hold — had no token dimension.
- Amendment `v3.3-a10` (a): `token_count` added to §9.4 as a ninth, cappable dimension; explicitly
  not folded into `compute_units`.
- Amendment `v3.3-a10` (b): §17.19.1 now states cap semantics — absent/`NULL` = not capped,
  `0` = zero permitted — because the DDL and `BudgetPolicy.cap_for()` had opposite readings and
  the disagreement failed open.
- `docs/spec_issues/README.md` index corrected (six rows said OPEN for issues resolved two days
  earlier) and locked by `tests/spec/test_spec_issue_index.py`.
- `IMPLEMENTATION_STATUS.md`: amendments in force `a1…a10`, migration count 9 → 10, invariant
  history rows for a9 and a10, spec-issue table row 009.

**Tests** postgres profile 433 passed; backend-free 352 passed / 81 skipped; executed-coverage
gate ok on all four checks under `[postgres]`; ruff + ruff format + mypy strict clean;
`rebuild_obligation_inventory.py --check` 72 occurrences in sync; `update_status.py --check`
current.

**Invariants** Requirement ↔ Test **59 ↔ 59** unchanged. §23.5 (2) occurrence inventory unchanged
(70 hard MUSTs / 72 classified occurrences) — no hard-obligation keyword entered §6–§16.

**Open blockers carried into Phase B**

1. The spec declares `token_count`; the Pydantic `CostVector` does not have it. Nothing detects
   this: the drift guard binds §17 schemas only, and §9.4 is unbound.
2. `BudgetPolicy.cap_for()` still returns `None` for a cap of `0`, i.e. still reads a deliberately
   frozen budget as unlimited. The spec now forbids that reading; the code has not caught up.

**Next** Phase B.

---

## Phase B — BudgetGate correctness (DONE)

**SHA** `172e42b0752005954b9fc5040de3de6e44b6b95a`

**Done**

- `BudgetCaps` replaces `caps: CostVector` + the `capped` tuple on `BudgetPolicy`. Every dimension
  is `| None`, one-for-one with the nullable `cap_*` columns, so `None` (not capped) and `0` (zero
  permitted) are different values rather than one value with two meanings. `cap_for()` no longer
  guesses. Blocker 2 closed.
- `token_count` added to `CostVector` (additive in `plus()`), `CAPPED_DIMENSIONS`, `BudgetCaps`, and
  the three tables via migration `007b_cost_token_dimension.sql`. `007a` untouched — it is applied,
  and the checksum ledger exists to refuse edits to applied migrations.
- `cost_dimension_drift()`: §9.4's block, `CostVector`, `CAPPED_DIMENSIONS`, `BudgetCaps` and the
  `cost_entries` / `cap_*` / `overrun_*` columns are compared as one closed set, plus the rule that
  qualifiers are cappable nowhere. Blocker 1 closed structurally — §9.4 was the one canonical schema
  outside §17, which is why a10 could move the document with the suite still green.
- Zero-cap and token negative fixtures in `tests/contract/test_budget_gate.py` and
  `tests/integration/test_cost_ledger_postgres.py`.

**Adversarial checks that actually ran** Reinstating `return None if value == 0 else value` fails
four of the new tests, so they catch the real bug rather than describing it. Both drift directions
were proven to fire by doctoring the spec text and by removing a dimension from
`CAPPED_DIMENSIONS`.

**Tests** postgres profile 450 passed; backend-free 364 passed / 86 skipped; migrations applied then
idempotent (11 declared / 11 applied / 0 pending); executed-coverage gate ok on all four checks
under `[postgres]`; ruff + format + mypy strict clean; obligation inventory 72 in sync.

**Open blockers carried into Phase C**

1. `BudgetApproval` is authenticated by nothing but the presence of an `actor_id` string. An
   inactive actor, a non-member, a SERVICE/AGENT_ROLE self-signature and an actor holding no budget
   authority all currently release an overrun.
2. `ONCE` is enforced only by the caller passing `consumed_approval_ids`. Two concurrent dispatches
   presenting the same approval both succeed.

**Known doc gap, not fixed here** `CHANGELOG.md` stops at M0a-2; P4, P5 and this slice are not in
it. Out of the stated scope of P5-fix and recorded rather than half-fixed.

**Next** Phase C.

## Phase C — approval security + atomic single-use (DONE)

**SHA** `df62c16360ff1b57c4a441fe483e6a3e31042a38`

**Done**

- `_unauthorised()` in the gate requires four independent facts of an approver: the record is the
  actor the approval names, the actor is active, the actor is `HUMAN`, and an active membership of
  *this* project carries the `BUDGET_OVERRUN` scope. Each is its own refusal with its own reason,
  ordered identity-first. Blocker 1 closed.
- `authorize_dispatch(request, claims)` is the dispatch entry point. `BudgetApprovalClaims` is a
  protocol with two implementations: `SqlBudgetApprovalClaims` (conditional
  `UPDATE ... WHERE consumed_at IS NULL ... RETURNING`) and `InMemoryBudgetApprovalClaims`
  (lock-guarded test-and-set). `claims=None` refuses any approval-dependent dispatch rather than
  falling back to the unenforced path. Blocker 2 closed.
- `evaluate_budget` stays pure and stays exported for replay; `consumed_approval_ids` is documented
  as a hint, not the enforcement.

**Deliberate non-rule** No separation-of-duties check between `request.actor_id` and the approver.
A researcher approving their own overrun is the §14.3 human decision; the self-signing case that
matters — a non-human actor — is refused by `actor_type`. Inventing the stronger rule would be the
agent legislating.

**Adversarial checks that actually ran** Bypassing `_unauthorised` fails 10 tests; dropping
`AND consumed_at IS NULL` fails 3 including the two-connection race; 8 threads on one in-memory
approval yield exactly 1 winner; 2 real psycopg connections through a barrier yield exactly 1 winner
and 1 consumed row. One earlier mutation silently failed to apply and reported green — the harness
now asserts the mutation landed first.

**Tests** postgres profile 474 passed; backend-free 382 passed / 92 skipped; executed-coverage gate
ok on all four checks; ruff + format + mypy strict clean.

**Open items carried into Phase D**

1. AGT-003: the manual header of `IMPLEMENTATION_STATUS.md` is still hand-typed. It went stale twice
   during this slice alone — amendments `a1…a8` while a9 was in force, and the migration count,
   which this slice has already had to bump by hand twice (9 → 10 → 11).
2. Risk register does not yet record that COST-001's gate, like SEC-002's read gate (R-7) and the
   critique gate (R-8), has **no live caller**. The rule is proven; its enforcement in a real
   dispatch path is not, because nothing dispatches until M1/M3.
3. `CHANGELOG.md` still stops at M0a-2.

**Next** Phase D.

## Phase D — governance / verification (DONE)

**SHA** `82fbbc38405a2c3f43c001ded117b84db6f426aa`

**Done**

- `spec-baseline` generated block in `IMPLEMENTATION_STATUS.md`: amendments in force (parsed from
  the Version Notes table) and migrations declared (counted from `migrations/`). Regenerated in
  `--requirements-only` mode, so the spec-conformance CI job checks it on every push.
- The "N migrations applied" claim is **removed, not generated**. It is a fact about a running
  database; a document cannot verify one, and generating a number labelled "applied" would have
  hidden the false claim behind a marker. A test refuses to let the phrase return.
- Cross-check re-derives the amendment span with a different parse from the generator's, scoped to
  the block — the first version searched the whole file and a staleness injection walked past it,
  because `v3.3-a10` also appears in the invariant-history table.
- R-10 recorded: the budget gate has no caller, the same shape as R-7 and R-8, with an explicit
  statement of which half *is* closed.
- `Next Recommended Task` rewritten to the real state.

**Adversarial checks that actually ran** Three drift injections — stale amendment span, stale
migration count, and the return of the "applied" claim — each caught. The amendment injection trips
two independent guards after the scoping fix.

**Full verification**

| Check | Result |
|---|---|
| postgres profile | 478 passed |
| backend-free profile | 386 passed / 92 skipped |
| migration replay from empty | scratch DB, 0 → 11 applied, then 0 pending |
| full suite on the replayed DB | 478 passed |
| idempotency, dev DB | 11 declared / 11 applied / 0 pending |
| executed-coverage gate | 4/4 ok under `[postgres]` |
| obligation inventory | 72 occurrences in sync |
| `update_status.py --check`, both modes | current |
| ruff / ruff format / mypy strict | clean |

**Invariants** Requirement ↔ Test **59 ↔ 59** unchanged across the whole slice. §23.5 (2) inventory
unchanged at 70 hard MUSTs / 72 classified occurrences.

---

## Phase E — durability of the approval claim (DONE)

Audit finding on `7420342f5f5da68343e5095ae877f60dfc34e552`, P1 blocker. Fixed before P6.

**The defect** `SqlBudgetApprovalClaims` accepted any object satisfying the connection protocol and
neither required autocommit nor committed. Handed psycopg's **default** `autocommit=False`
connection, the atomic UPDATE ran inside the caller's open transaction:

```
claim() -> True                     row updated, uncommitted
caller performs the side effect     the LLM call is made, the money is spent
transaction rolls back              for any reason, including an unrelated error
approval is unconsumed again        and claimable a second time
```

Atomicity was never the gap. The atomic `WHERE consumed_at IS NULL` guarantees one winner among
concurrent claimers; it says nothing about whether the winner's claim survives. The external effect
is not transactional and does not roll back with it, so one approval releases two actions —
§17.17.1's ONCE, violated by the configuration a caller gets by *not* thinking about it.

**The fix, smallest coherent** `SqlConnection` gains `autocommit: bool` as part of the contract.
`_require_durable()` refuses anything whose `autocommit` is not exactly `True`, at construction
**and** on every claim — `autocommit` is settable, so a store built on a durable connection is not
durable forever. Fail-closed on absence too: an object that cannot be *proven* to have autocommit
semantics is rejected, not assumed. Raises `NonDurableClaimStoreError` rather than returning
`False`, because a false claim is indistinguishable from ordinary contention and would turn a
wiring error into a retry loop that silently never succeeds.

**Explicitly not done: committing the caller's connection.** The store is handed someone else's
connection; calling `commit()` on it would durably commit whatever else that caller had in flight,
including work they intended to roll back. A component that silently commits its owner's
transaction is a worse bug than the one being fixed. It refuses instead.

**Tests added (5)**

- the hazard itself, executed: the same statement on a default psycopg connection reports success,
  a rollback follows, and the approval is unconsumed and claimable again
- a real `autocommit=False` connection is refused at construction
- a connection switched out of autocommit *after* construction is refused at claim, and writes
  nothing
- a claim that returned `True` is visible from a second session and survives a `rollback()`; the
  second session's re-claim returns `False`
- an object exposing only `execute` is refused (`autocommit=None`), so a mock or wrapper cannot
  reintroduce the defect behind a satisfied Protocol

Preserved unchanged: the 2-connection race (exactly one winner) and `claims=None` → BLOCK.

**Mutation** Making `_require_durable` return immediately fails 3 tests. The harness asserted the
mutation had landed before trusting the result.

**P2 cleanup in the same commit** SPEC-ISSUE-009's implementation checkbox ticked against Phase B's
SHA with what actually landed; R-3 corrected from "all eight spec issues" to nine.

**Verification** postgres 483 passed · backend-free 386 passed / 97 skipped · durability /
rollback / concurrency / claim-store targeted set 8 passed · migrations 11 declared / 11 applied /
0 pending · executed-coverage gate 4/4 under `[postgres]` · obligation inventory 72 in sync ·
`update_status.py --check` current · ruff + format + mypy strict clean.

---

## P5-fix complete — stop and await audit

Implementation stops here. The next slice (**P6 / M0b-3**, `OPS-003` first) does not start until
this returns PASS. Phase E was an audit finding on the Phase D SHA, not a self-directed
continuation; nothing beyond it has been started.

**Unresolved, carried forward**

1. **R-10 — no caller.** COST-001's gate is proven and unexercised in a live path. Closes with
   OPS-003/M1, which is why OPS-003 is next.
2. **R-7, R-8** — unchanged, same shape.
3. **R-9** — reclassification history still unrepresentable; waits on `EPI-003`.
4. **`CHANGELOG.md` stops at M0a-2.** P4, P5 and P5-fix are absent. Deliberately not fixed here:
   writing entries for other slices from the outside risks inventing history, and it is outside
   this slice's scope.
5. **`docs/spec_coverage_audit/M0a_hard_must_counts.yaml` records `spec_amendment: v3.3-a6`.**
   Informational only — nothing reads it — but it is a stale hand-typed field of exactly the kind
   Phase D just removed elsewhere. Left alone because changing the audit data file during a slice
   that does not re-adjudicate the audit would be worse.
