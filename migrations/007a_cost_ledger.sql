-- 007a_cost_ledger.sql
--
-- NUMBERING. Appendix A reserves 007 for `007_capabilities_costs.sql` -- one migration covering
-- both Capabilities (VER-002, M2) and the cost ledger (COST-001, M0b). Only the cost half is built
-- here, so this takes the `007a` suffix rather than claiming the whole slot; the capabilities half
-- lands with VER-002 as its own extension. Neither over-claims, and
-- tests/spec/test_migration_numbering.py enforces that a bare-numbered migration's slug matches
-- Appendix A exactly.
--
-- COST-001 / §17.17 / §17.17.1, as amended by v3.3-a9.

-- A versioned set of caps. Versioned because an approval is granted against the caps in force at
-- the time: if they change afterwards, what was approved is no longer what would run, and the gate
-- must refuse rather than apply an old permission to new limits.
CREATE TABLE budget_policies (
    policy_id       TEXT NOT NULL,
    policy_version  TEXT NOT NULL,
    project_id      TEXT NOT NULL REFERENCES projects (project_id),

    -- Caps, per §9.4 dimension. NULL means "not capped in this dimension", which is deliberately
    -- distinct from 0 -- most policies constrain money and wall-clock and say nothing about human
    -- minutes, and reading silence as a cap of zero would block every call.
    cap_wall_clock_s    BIGINT CHECK (cap_wall_clock_s   >= 0),
    cap_human_minutes   BIGINT CHECK (cap_human_minutes  >= 0),
    cap_money_estimate  NUMERIC(18, 6) CHECK (cap_money_estimate >= 0),
    cap_compute_units   BIGINT CHECK (cap_compute_units  >= 0),
    cap_license_seat_s  BIGINT CHECK (cap_license_seat_s >= 0),

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (policy_id, policy_version)
);

CREATE INDEX budget_policies_project_idx ON budget_policies (project_id);

-- A supervisor's release of ONE overrun. Every column below is a scope the gate checks; an approval
-- that survives any of them is a standing permission nobody granted.
CREATE TABLE budget_approvals (
    approval_id         TEXT PRIMARY KEY,
    -- The approval is itself an attributable event (COST-001, v3.3-a6). Not nullable: an
    -- unattributable approval answers "who signed for this" with silence.
    approver_actor_id   TEXT NOT NULL REFERENCES actors (actor_id),

    project_id          TEXT NOT NULL REFERENCES projects (project_id),
    episode_id          TEXT NOT NULL,
    action_ref          TEXT NOT NULL,
    policy_id           TEXT NOT NULL,
    policy_version      TEXT NOT NULL,

    -- How much overrun was authorised, per dimension. An approval is for an amount.
    overrun_wall_clock_s   BIGINT NOT NULL DEFAULT 0 CHECK (overrun_wall_clock_s  >= 0),
    overrun_human_minutes  BIGINT NOT NULL DEFAULT 0 CHECK (overrun_human_minutes >= 0),
    overrun_money_estimate NUMERIC(18, 6) NOT NULL DEFAULT 0 CHECK (overrun_money_estimate >= 0),
    overrun_compute_units  BIGINT NOT NULL DEFAULT 0 CHECK (overrun_compute_units >= 0),
    overrun_license_seat_s BIGINT NOT NULL DEFAULT 0 CHECK (overrun_license_seat_s >= 0),

    granted_at          TIMESTAMPTZ NOT NULL,
    expires_at          TIMESTAMPTZ NOT NULL,
    -- Single use, recorded rather than inferred. Set when the approval releases a dispatch; the
    -- gate refuses an approval that already carries it.
    consumed_at         TIMESTAMPTZ,
    consumed_by_action  TEXT,

    FOREIGN KEY (policy_id, policy_version)
        REFERENCES budget_policies (policy_id, policy_version),

    -- An expiry that precedes the grant is not a window.
    CONSTRAINT budget_approvals_window_is_forward
        CHECK (expires_at > granted_at),
    -- If it was consumed, it was consumed by the action it was granted for. Nothing else may
    -- spend it.
    CONSTRAINT budget_approvals_consumed_by_its_own_action
        CHECK (consumed_by_action IS NULL OR consumed_by_action = action_ref),
    CONSTRAINT budget_approvals_consumption_is_complete
        CHECK ((consumed_at IS NULL) = (consumed_by_action IS NULL))
);

CREATE INDEX budget_approvals_scope_idx
    ON budget_approvals (project_id, episode_id, action_ref);

-- The ledger. Append-only in intent and in fact: entries are never updated, and an estimate and
-- its actual are two rows rather than one row edited. Overwriting the estimate would destroy the
-- evidence for why the call was admitted and hide systematic under-estimation.
CREATE TABLE cost_entries (
    cost_entry_id   TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES projects (project_id),
    episode_id      TEXT NOT NULL,
    -- Wider than actor_id on purpose: §7.3's LLM slots are not Actors, and a cost incurred by a
    -- slot still has to be attributable.
    actor_or_slot   TEXT NOT NULL,
    action_ref      TEXT NOT NULL,
    cost_kind       TEXT NOT NULL CHECK (cost_kind IN ('ESTIMATED', 'ACTUAL')),

    wall_clock_s          BIGINT NOT NULL DEFAULT 0 CHECK (wall_clock_s   >= 0),
    human_minutes         BIGINT NOT NULL DEFAULT 0 CHECK (human_minutes  >= 0),
    money_estimate        NUMERIC(18, 6) NOT NULL DEFAULT 0 CHECK (money_estimate >= 0),
    compute_units         BIGINT NOT NULL DEFAULT 0 CHECK (compute_units  >= 0),
    license_seat_s        BIGINT NOT NULL DEFAULT 0 CHECK (license_seat_s >= 0),
    earliest_available_at TIMESTAMPTZ,
    irreversible          BOOLEAN NOT NULL DEFAULT FALSE,
    dependency_risk       TEXT NOT NULL DEFAULT 'NONE'
        CHECK (dependency_risk IN ('NONE', 'LOW', 'MEDIUM', 'HIGH')),

    -- Present when the spend was released by a supervisor, so the ledger shows not only that the
    -- money went but that someone signed for it.
    approval_id     TEXT REFERENCES budget_approvals (approval_id),
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- One estimate and one actual per action, so "what did we think this would cost" has a single
    -- answer. A retry is a new action_ref, not a second estimate for the old one.
    CONSTRAINT cost_entries_one_per_action_and_kind UNIQUE (action_ref, cost_kind)
);

CREATE INDEX cost_entries_project_idx ON cost_entries (project_id, recorded_at DESC);
CREATE INDEX cost_entries_episode_idx ON cost_entries (episode_id, recorded_at DESC);

-- Append-only, enforced rather than documented. A ledger whose rows can be edited is a report.
CREATE OR REPLACE FUNCTION cost_entries_are_append_only() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        'cost_entries is append-only (COST-001): record a correcting entry instead of %ing %',
        lower(TG_OP), OLD.cost_entry_id;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER cost_entries_no_update
    BEFORE UPDATE ON cost_entries
    FOR EACH ROW EXECUTE FUNCTION cost_entries_are_append_only();

CREATE TRIGGER cost_entries_no_delete
    BEFORE DELETE ON cost_entries
    FOR EACH ROW EXECUTE FUNCTION cost_entries_are_append_only();
