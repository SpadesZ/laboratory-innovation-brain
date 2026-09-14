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

## Phase C — approval security + atomic single-use (PENDING)

Intended scope, not yet done:

- `BudgetApproval` verified against an active HUMAN/supervisor actor with an active project
  membership and explicit budget approval authority, with every scope field matching. Inactive
  actor, non-member, service/agent self-signature, wrong project and absent authority all BLOCK.
- `ONCE` enforced by an atomic repository claim (conditional `UPDATE ... WHERE consumed_at IS NULL
  RETURNING`), not by the caller passing `consumed_approval_ids`. Two concurrent dispatches: one
  wins.
- A budget approval still releases the budget only — never SEC-002, never the §7.6 critique gate.

## Phase D — governance / verification (PENDING)

Intended scope, not yet done:

- AGT-003 recurrent blind spot: the manual header of `IMPLEMENTATION_STATUS.md` (amendments in
  force, migration count) must be covered by the freshness guard, not retyped.
- Amendment, migration-count and risk/status synchronisation.
- Full verification pass across both profiles.
