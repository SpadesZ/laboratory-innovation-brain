-- 007b_cost_token_dimension.sql
--
-- COST-001 / §9.4 / §17.19.1, as amended by `v3.3-a10` (SPEC-ISSUE-009).
--
-- WHY THIS IS A NEW FILE AND NOT AN EDIT TO 007a. 007a has been applied. `scripts/migrate.py`
-- checksums applied migrations precisely so that editing one fails the run instead of letting two
-- environments diverge while both report themselves up to date (AGT-004). A new column is a new
-- migration; that rule has no exception for "it is only three lines".
--
-- WHAT CHANGED. §9.4's CostVector gained `token_count` as a ninth dimension. COST-001 requires the
-- ledger to record at least wall-clock/tokens/money/license-seat, and until a10 the type §17.17
-- says a ledger entry holds had no token slot at all. It is a cappable dimension, so it lands in
-- all three tables: what is spent (cost_entries), what may be spent (budget_policies) and what an
-- overrun was authorised for (budget_approvals).
--
-- Tokens are deliberately NOT folded into `compute_units`. Two different quantities in one integer
-- answers neither question, which is the same argument §9.4 makes against `normalized_cost`.

-- Spent. NOT NULL DEFAULT 0 like every other additive dimension: a partial estimate is still a
-- usable record, and an action that consumed no tokens should not have to say so.
ALTER TABLE cost_entries
    ADD COLUMN token_count BIGINT NOT NULL DEFAULT 0 CHECK (token_count >= 0);

-- Permitted. NULLABLE, and the nullability is the point (§17.19.1 cap semantics, `v3.3-a10`):
--
--     NULL  this policy does not constrain tokens
--     0     this policy permits zero tokens
--
-- Distinct values for distinct facts. The Python `BudgetCaps` mirrors this column-for-column;
-- before a10 it reused CostVector's zero defaults and had to read `0` as "uncapped", so a budget
-- frozen at zero admitted everything. tests/spec/test_schema_drift.py now compares the two.
ALTER TABLE budget_policies
    ADD COLUMN cap_token_count BIGINT CHECK (cap_token_count >= 0);

-- Authorised overrun. NOT NULL DEFAULT 0, unlike the cap above: an approval is an amount, so zero
-- headroom is the correct and only meaning of zero here. §17.19.1 excludes `approved_overrun` from
-- the cap rule for exactly this reason.
ALTER TABLE budget_approvals
    ADD COLUMN overrun_token_count BIGINT NOT NULL DEFAULT 0 CHECK (overrun_token_count >= 0);
