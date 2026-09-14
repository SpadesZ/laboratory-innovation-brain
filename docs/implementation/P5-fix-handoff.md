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

## Phase B — BudgetGate correctness (PENDING)

Intended scope, not yet done:

- `cap_for()` must stop reading `0` as unlimited, which means `BudgetPolicy` needs a cap type that
  can express `NULL` separately from zero rather than reusing `CostVector`'s zero defaults.
- `token_count` through `CostVector`, `CAPPED_DIMENSIONS`, the DDL and the tests — as its own
  dimension, never inside `compute_units`.
- Bind §9.4 into the schema-drift guard so blocker 1 cannot reopen silently.
- Zero-cap negative fixtures in both the contract and the postgres suites.
- Cost stays multi-dimensional: no `total()`, no normalized scalar.

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
