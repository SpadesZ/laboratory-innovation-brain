-- 012z: a screening check refused by a fail-closed check is recorded as REFUSED.
--
-- WHY. `012y` knew four ways a selected check could end without a reading -- AWAITING_RESOURCE,
-- BUDGET_BLOCKED, FAILED, NOT_RUN. The V2 closure adds a fifth that is not a failure of the check:
-- immediately before a check's Job is submitted, and on every tool call it makes, the screening
-- executor re-reads what it is about to run and refuses anything that could reach outside the
-- machine, cost money, take a person or a licence seat, be irreversible, carry privacy constraints,
-- read another project's input, or drift from its plan (ADR-0015). Such a check observed nothing;
-- `screening_observations_unexecuted_observed_nothing` already holds for it.

ALTER TABLE screening_observations DROP CONSTRAINT IF EXISTS screening_observations_status_check;
ALTER TABLE screening_observations ADD CONSTRAINT screening_observations_status_check
    CHECK (status IN ('EXECUTED', 'AWAITING_RESOURCE', 'BUDGET_BLOCKED', 'FAILED', 'NOT_RUN',
                      'REFUSED'));
