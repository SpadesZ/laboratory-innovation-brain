-- 011e — the ReviewQueue has capacity, stakes and an SLA/expiry policy (OPS-002)
--
-- Forward-only. `011a`–`011d` are applied and are not touched.
--
--     §14.4  Human ReviewQueue 必須有 stakes、created_at、SLA/expiry policy 與 queue capacity，
--            避免所有 uncertain item 永久卡在 PENDING。
--     §26    T-OPS-002 ... a ReviewItem without `stakes` or without an SLA/expiry policy is
--            refused at creation, and an item past its expiry leaves PENDING via the declared
--            policy rather than parking there indefinitely.
--
-- WHAT `011b` LEFT OPEN, AND IT SAID SO AT THE TIME. `011b` shipped `review_items` as a "minimum
-- schema" for EPI-004 and stated in its own header that ReviewQueue depth and human-review
-- Capability availability did not exist. `stakes` was NOT NULL but could be `''`; `due_at` and
-- `expires_at` were nullable and nothing set them. So every review created by
-- `authority_conflict_escalate` had no expiry at all -- which is the exact state §14.4 exists to
-- forbid: an item that can park in PENDING forever, and a queue that cannot tell a planner how
-- long the wait is.
--
-- THE POLICY IS VERSIONED AND STORED, NOT A CONSTANT. Two reasons, and the second is the one that
-- matters. First, §14.4's SLA is a governance decision a lab makes, and a number compiled into
-- core would be core deciding how long a professor may take. Second, an item's expiry has to stay
-- explicable *after* the policy changes: a review that expired under a 48-hour rule must not look
-- wrong because the lab later moved to 72. So the review records which policy version priced it,
-- the same way an event records the `TransitionPolicy` version that authorised it (`v3.3-a11`).
--
-- WHAT IS NOT IN SQL, AS ALWAYS. Capacity does not refuse an escalation. §26 says depth and
-- capacity change *availability*, and a full queue that refused to accept a blocking conflict's
-- review would leave the conflict OPEN with nobody assigned -- still blocking, and now invisible
-- to the queue that is supposed to report the backlog. The database records the numbers; whether
-- human review is available is `HumanReviewCapability`'s answer, in Python, where the planner
-- reads it.

-- ---------------------------------------------------------------------------------------------
-- 1. The declared queue policy
-- ---------------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS review_queue_policies (
    policy_id               TEXT NOT NULL,
    version                 TEXT NOT NULL,
    project_id              TEXT NOT NULL REFERENCES projects (project_id),

    -- §14.4's "queue capacity". How many outstanding items this queue can hold before human
    -- review reports itself unavailable. Zero is legal and means exactly what it says: this
    -- project is not accepting human review right now. Distinguishing it from "no limit" is the
    -- same lesson `v3.3-a10` recorded for budget caps -- absent and zero are two different facts,
    -- so there is no NULL here and "no limit" is not expressible by omission.
    capacity                INTEGER NOT NULL CHECK (capacity >= 0),

    -- §14.4's SLA and expiry, in minutes from `created_at`. Defaults apply to any stakes value the
    -- per-stakes maps do not mention, so a queue can never receive an item it has no deadline for.
    default_sla_minutes     INTEGER NOT NULL CHECK (default_sla_minutes > 0),
    default_expiry_minutes  INTEGER NOT NULL CHECK (default_expiry_minutes > 0),

    -- stakes -> minutes. JSONB rather than columns because `stakes` is domain-supplied free text
    -- (§17.19.1 does not enumerate it) and core must not fix a vocabulary it does not own.
    sla_minutes_by_stakes    JSONB NOT NULL DEFAULT '{}'::jsonb,
    expiry_minutes_by_stakes JSONB NOT NULL DEFAULT '{}'::jsonb,

    --: Minutes of reviewer attention this queue can supply per day. Feeds
    --: `HumanReviewCapability.earliest_available_at` (§14.4.1) -- the planner needs the professor's
    --: time priced, not assumed free.
    reviewer_minutes_per_day INTEGER NOT NULL DEFAULT 0 CHECK (reviewer_minutes_per_day >= 0),

    effective_from          TIMESTAMPTZ NOT NULL,
    active                  BOOLEAN NOT NULL DEFAULT TRUE,

    PRIMARY KEY (policy_id, version),

    -- Expiry must not precede the SLA. A queue whose items expire before they are late would
    -- close every review unanswered while reporting no breaches at all.
    CONSTRAINT review_queue_policies_expiry_after_sla
        CHECK (default_expiry_minutes >= default_sla_minutes),

    CONSTRAINT review_queue_policies_id_project_unique UNIQUE (policy_id, version, project_id)
);

COMMENT ON TABLE review_queue_policies IS
    'OPS-002 / §14.4. Capacity, SLA and expiry for one project''s human ReviewQueue. Versioned so '
    'an item that expired under an older rule stays explicable after the lab changes the rule.';

-- EXACTLY ONE ACTIVE POLICY PER PROJECT. Two would make "which deadline applies" depend on read
-- order, and an item priced by whichever was found first is an item with no declared deadline.
CREATE UNIQUE INDEX IF NOT EXISTS review_queue_policies_one_active_per_project
    ON review_queue_policies (project_id) WHERE active;

-- ---------------------------------------------------------------------------------------------
-- 2. A review records the policy that priced it, and carries real deadlines
-- ---------------------------------------------------------------------------------------------

ALTER TABLE review_items ADD COLUMN IF NOT EXISTS queue_policy_id      TEXT;
ALTER TABLE review_items ADD COLUMN IF NOT EXISTS queue_policy_version TEXT;

ALTER TABLE review_items
    DROP CONSTRAINT IF EXISTS review_items_queue_policy_in_project;
ALTER TABLE review_items
    ADD CONSTRAINT review_items_queue_policy_in_project
    FOREIGN KEY (queue_policy_id, queue_policy_version, project_id)
    REFERENCES review_queue_policies (policy_id, version, project_id);

COMMENT ON COLUMN review_items.queue_policy_version IS
    'OPS-002: the review_queue_policies version that computed this item''s due_at and expires_at. '
    'Recorded rather than re-derived, so an expiry stays explicable after the policy changes.';

-- Refuse the two states §14.4 forbids, on the way in.
--
-- A TRIGGER, NOT A CHECK, FOR ONE OF THE THREE. `stakes` being non-blank and the deadlines being
-- present are both expressible as CHECKs -- and a CHECK reports the constraint name, while §26's
-- pass condition is about a *reason* an operator can act on. The first thing someone does after
-- "violates check constraint review_items_stakes_not_blank" is come and read this file; the
-- message below saves the trip.

CREATE OR REPLACE FUNCTION review_items_have_stakes_and_a_deadline()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.stakes IS NULL OR btrim(NEW.stakes) = '' THEN
        RAISE EXCEPTION
            'review % has no stakes. §14.4 requires every queued item to carry them: stakes is '
            'what a reviewer prioritises by and what the SLA is priced from, and a blank one makes '
            'the item indistinguishable from the least urgent thing in the queue',
            NEW.review_id;
    END IF;

    IF NEW.queue_policy_id IS NULL OR NEW.queue_policy_version IS NULL THEN
        RAISE EXCEPTION
            'review % names no queue policy. §14.4 requires an SLA/expiry policy; without one the '
            'item has no deadline and can park in PENDING indefinitely, which is the state that '
            'requirement exists to forbid',
            NEW.review_id;
    END IF;

    IF NEW.due_at IS NULL OR NEW.expires_at IS NULL THEN
        RAISE EXCEPTION
            'review % is missing due_at or expires_at. Naming a policy is not the same as having '
            'been priced by it, and an item with no expiry never leaves the queue on its own',
            NEW.review_id;
    END IF;

    IF NEW.expires_at < NEW.due_at THEN
        RAISE EXCEPTION
            'review % expires at % before it is due at %. It would close unanswered while the '
            'queue reported no SLA breach at all',
            NEW.review_id, NEW.expires_at, NEW.due_at;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS review_items_have_stakes_and_a_deadline ON review_items;
CREATE TRIGGER review_items_have_stakes_and_a_deadline
    BEFORE INSERT ON review_items
    FOR EACH ROW EXECUTE FUNCTION review_items_have_stakes_and_a_deadline();

CREATE INDEX IF NOT EXISTS review_items_expiry_idx
    ON review_items (project_id, status, expires_at);

-- Refuse to enforce this over a database that already holds undeadlined items, for `011b`'s and
-- `011d`'s reason: a constraint added over data that violates it means less than it says, and
-- inventing deadlines for existing rows would manufacture the governance record it exists to
-- require.
DO $$
DECLARE
    v_undeadlined INTEGER;
BEGIN
    SELECT count(*) INTO v_undeadlined
      FROM review_items
     WHERE expires_at IS NULL OR due_at IS NULL OR queue_policy_id IS NULL;

    IF v_undeadlined > 0 THEN
        RAISE EXCEPTION
            'refusing to require an SLA/expiry policy: this database already holds % review items '
            'with no deadline, created before the policy existed. There is no correct value to '
            'reconcile them against -- a deadline invented now would be a governance record nobody '
            'made. Re-create the database from empty, or price each item by hand first',
            v_undeadlined;
    END IF;
END;
$$;

-- ---------------------------------------------------------------------------------------------
-- 3. Escalation prices the item from the declared policy
-- ---------------------------------------------------------------------------------------------
--
-- Replaces `011c`'s body. Signature unchanged apart from the two new outputs being computed rather
-- than passed, so no caller can opt out of being priced -- the same reason `011c` kept
-- `conflict_close`'s signature when it taught it to consult the review.
--
-- EVERY LOCKED PROPERTY OF `011c`'s VERSION IS PRESERVED, AND THIS IS THE PART TO CHECK IN REVIEW:
--   * idempotent -- an already-linked conflict returns its existing review id, unchanged;
--   * the UPDATE is still conditioned on `review_id IS NULL`, which is what makes two concurrent
--     escalations resolve to one winner rather than one overwriting the other (proven under real
--     concurrency in P13);
--   * a closed conflict is still refused;
--   * the review is still created and linked in one statement.
-- The only additions are the policy lookup and the two deadlines it computes.

CREATE OR REPLACE FUNCTION authority_conflict_escalate(
    p_review_id                TEXT,
    p_conflict_id              TEXT,
    p_project_id               TEXT,
    p_stakes                   TEXT,
    p_reason                   TEXT,
    p_trace_id                 TEXT,
    p_created_at               TIMESTAMPTZ,
    p_required_authority       TEXT,
    p_episode_id               TEXT,
    p_estimated_human_minutes  INTEGER
) RETURNS TEXT AS $$
DECLARE
    v_conflict conflicts;
    v_policy   review_queue_policies;
    v_sla      INTEGER;
    v_expiry   INTEGER;
BEGIN
    SELECT * INTO v_conflict
      FROM conflicts
     WHERE conflict_id = p_conflict_id AND project_id = p_project_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'authority_conflict_escalate: conflict % does not exist in %',
            p_conflict_id, p_project_id;
    END IF;

    IF v_conflict.resolution_status NOT IN ('OPEN', 'UNDER_REVIEW') THEN
        RAISE EXCEPTION
            'authority_conflict_escalate: conflict % is already %. Queueing a review for a block '
            'that has lifted gives a human a task with nothing behind it',
            p_conflict_id, v_conflict.resolution_status;
    END IF;

    -- IDEMPOTENT, and checked before the policy lookup on purpose: a retried episode must get the
    -- existing review even if the lab has since deactivated its queue policy. The first escalation
    -- was priced; the retry is not a second pricing.
    IF v_conflict.review_id IS NOT NULL THEN
        RETURN v_conflict.review_id;
    END IF;

    SELECT * INTO v_policy
      FROM review_queue_policies
     WHERE project_id = p_project_id AND active;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'authority_conflict_escalate: no active review queue policy for %. §14.4 requires an '
            'SLA/expiry policy before an item may be queued -- without one this review would have '
            'no deadline and could park in PENDING indefinitely',
            p_project_id;
    END IF;

    -- Per-stakes first, declared default second. There is no third fallback: a queue that priced
    -- an unknown stakes value by guessing would have a deadline nobody declared.
    v_sla := COALESCE(
        (v_policy.sla_minutes_by_stakes ->> p_stakes)::INTEGER, v_policy.default_sla_minutes);
    v_expiry := COALESCE(
        (v_policy.expiry_minutes_by_stakes ->> p_stakes)::INTEGER, v_policy.default_expiry_minutes);

    IF v_expiry < v_sla THEN
        RAISE EXCEPTION
            'review queue policy %@% prices stakes % to expire after % minutes but be due after '
            '%. The item would close unanswered while the queue reported no breach',
            v_policy.policy_id, v_policy.version, p_stakes, v_expiry, v_sla;
    END IF;

    INSERT INTO review_items (
        review_id, project_id, subject_type, subject_id, stakes, reason, trace_id,
        created_at, required_authority, episode_id, estimated_human_minutes,
        queue_policy_id, queue_policy_version, due_at, expires_at
    ) VALUES (
        p_review_id, p_project_id, 'AUTHORITY_CONFLICT', p_conflict_id, p_stakes, p_reason,
        p_trace_id, p_created_at, p_required_authority, p_episode_id,
        COALESCE(p_estimated_human_minutes, 0),
        v_policy.policy_id, v_policy.version,
        p_created_at + make_interval(mins => v_sla),
        p_created_at + make_interval(mins => v_expiry)
    );

    UPDATE conflicts
       SET review_id = p_review_id,
           resolution_status = 'UNDER_REVIEW'
     WHERE conflict_id = p_conflict_id
       AND project_id  = p_project_id
       AND review_id IS NULL
       AND resolution_status IN ('OPEN', 'UNDER_REVIEW');

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'authority_conflict_escalate: conflict % was linked to a review concurrently. '
            'Exactly one review gates a conflict, and the loser must not leave an orphan queued',
            p_conflict_id;
    END IF;

    RETURN p_review_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION authority_conflict_escalate(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ, TEXT, TEXT, INTEGER
) IS
    'EPI-004 + OPS-002: create the ReviewItem for an AUTHORITY_CONFLICT, price it from the '
    'project''s active review queue policy, and link it in one statement. Idempotent: a conflict '
    'already under review returns its existing review id.';
