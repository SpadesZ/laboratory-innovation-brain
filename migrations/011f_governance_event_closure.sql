-- 011f — GovernanceEvent, and a closure reference that can say which kind (`v3.3-a15`)
--
-- Forward-only. `005a`–`005d` and `011a`–`011e` are applied and their files are not touched; this
-- migration evolves the schema they created, which is the only way the ruling can be honoured.
--
-- THE RULING THIS IMPLEMENTS. SPEC-ISSUE-012 asked what event an automatically expired ReviewItem
-- may cite, and the answer was that none existed. `v3.3-a14` routes every closure through
-- `ReviewResolution`'s event, `011c` made that a `belief_revision_events` reference, and §17.13
-- gives a `BeliefRevisionEvent` exactly one meaning: a hypothesis's belief state changed. **An
-- unanswered timeout is not a transition.** Every construction was probed and every one was
-- illegal:
--
--   no-op TransitionPolicy(ACTIVE -> ACTIVE)   unrepresentable, `005b` CHECK from <> to
--   non-genesis citing the admission policy    refused by `005c`
--   ACTIVE -> INCONCLUSIVE, policy honours
--     the blocking conflict                    NEED_HUMAN_REVIEW, no ALLOW, no event -- circular
--   same, policy ignores the conflict          ALLOW with no required relations: a scheduler
--                                              declaring a hypothesis INCONCLUSIVE on nothing
--   genesis for a fabricated hypothesis id     accepted, and what the M0b fixture was doing
--
-- `v3.3-a15` adopts Reading B: a `GovernanceEvent` for state changes that are governance rather
-- than science, and a closure reference that says which kind it is.
--
-- WHY THE VOCABULARY IS ONE VALUE. `event_type` admits `REVIEW_EXPIRY` and nothing else. A generic
-- audit-event type would be a second way to close anything -- exactly the hole this amendment
-- exists to avoid rather than open. A new kind is a spec amendment, which is the point.
--
-- WHY TWO TYPED COLUMNS RATHER THAN ONE POLYMORPHIC ONE. SQL has no polymorphic foreign key, and
-- the composite `(event_id, project_id)` references are what make a cross-project closure
-- *unrepresentable* instead of merely wrong -- the guarantee `005c` and `011a` were built for. So
-- each kind keeps its own nullable column with its own composite FK, a CHECK says exactly one is
-- set and agrees with the declared kind, and the canonical `resolution_event_id` is **generated**
-- from them so the pair can never disagree with itself.

-- ---------------------------------------------------------------------------------------------
-- 1. Refuse to evolve a database that cannot be reconciled
-- ---------------------------------------------------------------------------------------------
--
-- Same shape as `011b`, `011d` and `011e`, and for the same reason: `declared_by_actor_id` becomes
-- required on a queue policy, and there is no correct value to invent for a policy somebody
-- already declared. Inventing one would manufacture the authority record this migration exists to
-- require.

DO $$
DECLARE
    v_policies INTEGER;
BEGIN
    SELECT count(*) INTO v_policies FROM review_queue_policies;
    IF v_policies > 0 THEN
        RAISE EXCEPTION
            'refusing to require declared_by_actor_id: this database already holds % review queue '
            'policies declared before the field existed. §17.19.1 as amended by v3.3-a15 makes the '
            'policy author the standing authority for automatic expiry, and it must not be '
            'inferred -- least of all from the service account that runs the sweep. Re-create the '
            'database from empty, or attribute each policy by hand first',
            v_policies;
    END IF;
END;
$$;

-- ---------------------------------------------------------------------------------------------
-- 2. The GovernanceEvent
-- ---------------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS governance_events (
    event_id            TEXT PRIMARY KEY,
    project_id          TEXT NOT NULL REFERENCES projects (project_id),

    -- CLOSED, AND CLOSED AT ONE VALUE. See the header: a permissive vocabulary here would make
    -- this table a general-purpose way to close a Conflict without moving a belief.
    event_type          TEXT NOT NULL CHECK (event_type IN ('REVIEW_EXPIRY')),
    subject_type        TEXT NOT NULL CHECK (subject_type IN ('REVIEW_ITEM')),
    subject_id          TEXT NOT NULL,

    -- The conflict this expiry closed, when there was one. Nullable because a review that gates
    -- nothing can still expire, and recording a conflict it did not close would be a lie.
    related_conflict_id TEXT,

    -- The standing policy that authorised this, and **which version of it**. Not the currently
    -- active one: an expiry re-interpreted under a policy the reviewer never saw is not the
    -- deadline they were given.
    policy_id           TEXT NOT NULL,
    policy_version      TEXT NOT NULL,

    -- TWO ACTORS, AND THEY ANSWER DIFFERENT QUESTIONS. `declared_by_actor_id` is who decided that
    -- items of this stakes lapse after this long; `actor_id` is who or what executed this
    -- particular sweep. Collapsing them would let a service account look like the author of a
    -- governance decision it only carried out.
    declared_by_actor_id TEXT REFERENCES actors (actor_id),
    actor_id            TEXT NOT NULL REFERENCES actors (actor_id),

    reason_code         TEXT NOT NULL,
    rationale           TEXT,

    occurred_at         TIMESTAMPTZ NOT NULL,
    trace_id            TEXT NOT NULL,
    episode_id          TEXT,

    CONSTRAINT governance_events_policy_in_project
        FOREIGN KEY (policy_id, policy_version, project_id)
        REFERENCES review_queue_policies (policy_id, version, project_id),

    CONSTRAINT governance_events_review_in_project
        FOREIGN KEY (subject_id, project_id) REFERENCES review_items (review_id, project_id),

    CONSTRAINT governance_events_conflict_in_project
        FOREIGN KEY (related_conflict_id, project_id)
        REFERENCES conflicts (conflict_id, project_id),

    -- Lets a resolution and a conflict reference this event *with* its project, which is what
    -- makes a cross-project closure unrepresentable rather than merely rejected.
    CONSTRAINT governance_events_id_project_unique UNIQUE (event_id, project_id)
);

COMMENT ON TABLE governance_events IS
    'v3.3-a15 / §17.19.1. A governance or operational state change that does NOT itself alter '
    'scientific belief. MUST NOT be accepted as BeliefRevisionEvent evidence, MUST NOT appear in a '
    'belief replay, and MUST NOT mutate EpistemicStateProjection. event_type is REVIEW_EXPIRY and '
    'nothing else -- a generic audit-event vocabulary would be a second way to close anything.';

CREATE INDEX IF NOT EXISTS governance_events_subject_idx
    ON governance_events (project_id, subject_id, occurred_at);

-- Append-only and immutable, like every other record that justifies a state change.

CREATE OR REPLACE FUNCTION governance_events_are_immutable()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        'governance_events are append-only: % of % is refused. This row is the authority a '
        'Conflict closed against; editing or removing it leaves a belief unblocked with no '
        'recoverable reason, which is the state §17.19.3 exists to prevent',
        TG_OP, COALESCE(OLD.event_id, NEW.event_id);
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS governance_events_immutable ON governance_events;
CREATE TRIGGER governance_events_immutable
    BEFORE UPDATE OR DELETE ON governance_events
    FOR EACH ROW EXECUTE FUNCTION governance_events_are_immutable();

-- ---------------------------------------------------------------------------------------------
-- 3. The queue policy records who declared it
-- ---------------------------------------------------------------------------------------------

ALTER TABLE review_queue_policies
    ADD COLUMN IF NOT EXISTS declared_by_actor_id TEXT REFERENCES actors (actor_id);
ALTER TABLE review_queue_policies
    ALTER COLUMN declared_by_actor_id SET NOT NULL;

COMMENT ON COLUMN review_queue_policies.declared_by_actor_id IS
    'v3.3-a15: the actor whose standing decision authorises automatic expiry under this policy. '
    'MUST NOT be inferred from the service account that executes the sweep -- the executor is '
    'recorded separately on the GovernanceEvent.';

-- ---------------------------------------------------------------------------------------------
-- 4. The resolution reference becomes a typed pair
-- ---------------------------------------------------------------------------------------------

ALTER TABLE review_resolutions
    ALTER COLUMN belief_revision_event_id DROP NOT NULL;

ALTER TABLE review_resolutions
    ADD COLUMN IF NOT EXISTS governance_event_id TEXT;
ALTER TABLE review_resolutions
    ADD COLUMN IF NOT EXISTS resolution_event_kind TEXT NOT NULL DEFAULT 'BELIEF_REVISION';
-- THE DEFAULT IS THE BACKFILL, AND IT STAYS. Every row that existed before this migration was a
-- BELIEF_REVISION closure by construction, because nothing else could be written -- so the DEFAULT
-- backfills them correctly.
--
-- Keeping it afterwards is the part worth justifying, because "a default nobody stated" is usually
-- how a wrong value gets in. Here it cannot: `review_resolutions_event_matches_kind` below ties the
-- kind to *which column is populated*. A row that supplies `governance_event_id` and lets the kind
-- default to BELIEF_REVISION is refused by that CHECK, not silently mislabelled. So the default can
-- only ever agree with what the row actually carries, and the generalisation stays backward
-- compatible for every caller that predates it.

ALTER TABLE review_resolutions
    DROP CONSTRAINT IF EXISTS review_resolutions_event_kind_known;
ALTER TABLE review_resolutions
    ADD CONSTRAINT review_resolutions_event_kind_known
    CHECK (resolution_event_kind IN ('BELIEF_REVISION', 'GOVERNANCE'));

ALTER TABLE review_resolutions
    DROP CONSTRAINT IF EXISTS review_resolutions_governance_event_in_project;
ALTER TABLE review_resolutions
    ADD CONSTRAINT review_resolutions_governance_event_in_project
    FOREIGN KEY (governance_event_id, project_id)
    REFERENCES governance_events (event_id, project_id);

-- EXACTLY ONE EVENT, AND IT AGREES WITH THE DECLARED KIND. Written as an equality between the kind
-- and which column is populated, so neither direction can drift: a GOVERNANCE resolution carrying
-- a belief event is refused, and so is a BELIEF_REVISION one carrying a governance event.
ALTER TABLE review_resolutions
    DROP CONSTRAINT IF EXISTS review_resolutions_event_matches_kind;
ALTER TABLE review_resolutions
    ADD CONSTRAINT review_resolutions_event_matches_kind
    CHECK (
        (resolution_event_kind = 'BELIEF_REVISION')
        = (belief_revision_event_id IS NOT NULL AND governance_event_id IS NULL)
        AND (resolution_event_kind = 'GOVERNANCE')
            = (governance_event_id IS NOT NULL AND belief_revision_event_id IS NULL)
    );

-- THE ONE COMBINATION `v3.3-a15` PERMITS. A human resolution may not close against a
-- GovernanceEvent: APPROVED, CORRECTED and REJECTED are decisions somebody made, and a governance
-- event records that nobody did.
ALTER TABLE review_resolutions
    DROP CONSTRAINT IF EXISTS review_resolutions_governance_only_expires;
ALTER TABLE review_resolutions
    ADD CONSTRAINT review_resolutions_governance_only_expires
    CHECK (resolution_event_kind <> 'GOVERNANCE' OR outcome = 'EXPIRED');

-- Generated, so the canonical reference cannot disagree with the typed columns it summarises.
ALTER TABLE review_resolutions
    ADD COLUMN IF NOT EXISTS resolution_event_id TEXT
    GENERATED ALWAYS AS (COALESCE(belief_revision_event_id, governance_event_id)) STORED;

COMMENT ON COLUMN review_resolutions.resolution_event_id IS
    'v3.3-a15: the canonical closure reference, generated from whichever typed column the kind '
    'names. Generated rather than stored so it can never disagree with resolution_event_kind.';

-- ---------------------------------------------------------------------------------------------
-- 5. The conflict's closure reference, the same way
-- ---------------------------------------------------------------------------------------------

ALTER TABLE conflicts
    ADD COLUMN IF NOT EXISTS governance_event_id TEXT;
ALTER TABLE conflicts
    ADD COLUMN IF NOT EXISTS resolution_event_kind TEXT;

ALTER TABLE conflicts
    DROP CONSTRAINT IF EXISTS conflicts_event_kind_known;
ALTER TABLE conflicts
    ADD CONSTRAINT conflicts_event_kind_known
    CHECK (resolution_event_kind IS NULL
           OR resolution_event_kind IN ('BELIEF_REVISION', 'GOVERNANCE'));

ALTER TABLE conflicts
    DROP CONSTRAINT IF EXISTS conflicts_governance_event_in_project;
ALTER TABLE conflicts
    ADD CONSTRAINT conflicts_governance_event_in_project
    FOREIGN KEY (governance_event_id, project_id)
    REFERENCES governance_events (event_id, project_id);

-- REPLACES `011a`'s `conflicts_closure_matches_status`, which predates the second kind and reads
-- `resolution_event_id IS NULL` as "not closed". A governance closure leaves that column NULL and
-- populates `governance_event_id`, so the original CHECK would refuse the one path this migration
-- exists to permit. The replacement keeps the same both-directions equality -- an open conflict
-- must not look half-closed, and a closed one must carry exactly one event of a declared kind.
ALTER TABLE conflicts
    DROP CONSTRAINT IF EXISTS conflicts_closure_matches_status;
ALTER TABLE conflicts
    ADD CONSTRAINT conflicts_closure_matches_status
    CHECK (
        (resolution_status IN ('OPEN', 'UNDER_REVIEW'))
        = (resolved_at IS NULL
           AND resolution_event_id IS NULL
           AND governance_event_id IS NULL
           AND resolution_event_kind IS NULL)
    );

ALTER TABLE conflicts
    DROP CONSTRAINT IF EXISTS conflicts_event_matches_kind;
ALTER TABLE conflicts
    ADD CONSTRAINT conflicts_event_matches_kind
    CHECK (
        resolution_event_kind IS NULL
        OR (
            (resolution_event_kind = 'BELIEF_REVISION')
            = (resolution_event_id IS NOT NULL AND governance_event_id IS NULL)
            AND (resolution_event_kind = 'GOVERNANCE')
                = (governance_event_id IS NOT NULL AND resolution_event_id IS NULL)
        )
    );

COMMENT ON COLUMN conflicts.resolution_event_kind IS
    'v3.3-a15: which kind of event closed this conflict. NULL while open. GOVERNANCE is permitted '
    'only for an EXPIRED ReviewResolution against a REVIEW_EXPIRY GovernanceEvent (§17.19.1).';

-- `011a`'s immutability trigger predates both columns, so a closed conflict could have its kind or
-- governance reference rewritten. Extended here rather than in `011a`.
CREATE OR REPLACE FUNCTION conflicts_only_close()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.conflict_id      IS DISTINCT FROM OLD.conflict_id
       OR NEW.project_id    IS DISTINCT FROM OLD.project_id
       OR NEW.conflict_type IS DISTINCT FROM OLD.conflict_type
       OR NEW.blocking      IS DISTINCT FROM OLD.blocking
       OR NEW.subject_refs  IS DISTINCT FROM OLD.subject_refs
       OR NEW.supporting_refs IS DISTINCT FROM OLD.supporting_refs
       OR NEW.episode_id    IS DISTINCT FROM OLD.episode_id
       OR NEW.trace_id      IS DISTINCT FROM OLD.trace_id
       OR NEW.detected_at   IS DISTINCT FROM OLD.detected_at
       OR NEW.detected_by_actor_or_slot IS DISTINCT FROM OLD.detected_by_actor_or_slot THEN
        RAISE EXCEPTION
            'conflict %: identity, type, blocking flag, subjects, supporting evidence, episode, '
            'trace and detection provenance are immutable. Editing them rewrites what the '
            'disagreement was rather than resolving it -- and flipping `blocking` to false is the '
            'quietest way to unblock a belief with no record that anything happened',
            OLD.conflict_id;
    END IF;

    IF OLD.review_id IS NOT NULL AND NEW.review_id IS DISTINCT FROM OLD.review_id THEN
        RAISE EXCEPTION
            'conflict % is already gated by review %; it cannot be re-pointed at %. The first '
            'review would stay in the queue gating nothing while the block it was raised for '
            'pointed somewhere else',
            OLD.conflict_id, OLD.review_id, NEW.review_id;
    END IF;

    IF OLD.resolution_status NOT IN ('OPEN', 'UNDER_REVIEW') THEN
        RAISE EXCEPTION
            'conflict % is already %, closed by % %. Re-resolving or reopening would overwrite the '
            'event that justified the first close, leaving two incompatible accounts of why a '
            'belief became promotable again',
            OLD.conflict_id, OLD.resolution_status,
            COALESCE(OLD.resolution_event_kind, 'an event'),
            COALESCE(OLD.resolution_event_id, OLD.governance_event_id);
    END IF;

    IF NEW.resolution_status IN ('OPEN', 'UNDER_REVIEW') THEN
        RETURN NEW;
    END IF;

    IF (NEW.resolution_event_id IS NULL AND NEW.governance_event_id IS NULL)
       OR NEW.resolved_at IS NULL
       OR NEW.resolution_event_kind IS NULL THEN
        RAISE EXCEPTION
            'conflict % cannot become % without a closure event, its kind and resolved_at. §25.3 '
            'EPI-006 requires closing a conflict to record the event that closed it; changing the '
            'status alone would unblock a belief with no recoverable reason',
            OLD.conflict_id, NEW.resolution_status;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------------------------------------
-- 6. `conflict_close` learns the kind
-- ---------------------------------------------------------------------------------------------
--
-- Replaces `011c`'s body. The signature gains one parameter with a default, so every existing
-- caller keeps working and keeps its meaning: an unqualified close is a BELIEF_REVISION close,
-- which is what all of them were.

CREATE OR REPLACE FUNCTION conflict_close(
    p_conflict_id          TEXT,
    p_project_id           TEXT,
    p_resolution_status    TEXT,
    p_resolution_event_id  TEXT,
    p_resolved_at          TIMESTAMPTZ,
    p_event_kind           TEXT DEFAULT 'BELIEF_REVISION'
) RETURNS VOID AS $$
DECLARE
    v_conflict   conflicts;
    v_review     review_items;
    v_resolution review_resolutions;
    v_updated    INTEGER;
BEGIN
    IF p_resolution_status IN ('OPEN', 'UNDER_REVIEW') THEN
        RAISE EXCEPTION
            'conflict_close: % is not a closure. Moving a conflict to UNDER_REVIEW is a different '
            'operation and must not carry a resolution event', p_resolution_status;
    END IF;

    IF p_event_kind NOT IN ('BELIEF_REVISION', 'GOVERNANCE') THEN
        RAISE EXCEPTION
            'conflict_close: % is not a closure event kind. §17.19.1 as amended by v3.3-a15 '
            'declares BELIEF_REVISION and GOVERNANCE, and an unknown kind would close a conflict '
            'against an event nothing can classify', p_event_kind;
    END IF;

    SELECT * INTO v_conflict
      FROM conflicts
     WHERE conflict_id = p_conflict_id AND project_id = p_project_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'conflict_close: % in % does not exist. Reporting success would tell a caller a block '
            'had lifted while it is still in place -- or in a project it never named',
            p_conflict_id, p_project_id;
    END IF;

    IF v_conflict.review_id IS NOT NULL THEN
        SELECT * INTO v_review
          FROM review_items
         WHERE review_id = v_conflict.review_id AND project_id = p_project_id;

        IF NOT FOUND THEN
            RAISE EXCEPTION
                'conflict_close: conflict % is linked to review %, which does not exist in %. A '
                'block whose review cannot be found must not be lifted on the assumption that it '
                'was handled',
                p_conflict_id, v_conflict.review_id, p_project_id;
        END IF;

        IF v_review.status IN ('QUEUED', 'ASSIGNED') THEN
            RAISE EXCEPTION
                'conflict_close: conflict % is linked to review %, which is still % -- a human '
                'has not answered. §8.2.1 blocks promotion and rejection until the review '
                'resolves, and ASSIGNED is somebody having picked the task up rather than '
                'somebody having decided',
                p_conflict_id, v_review.review_id, v_review.status;
        END IF;

        IF v_review.decision_ref IS NULL THEN
            RAISE EXCEPTION
                'conflict_close: review % is % but records no decision_ref, so there is nothing '
                'to trace this closure to',
                v_review.review_id, v_review.status;
        END IF;

        SELECT * INTO v_resolution
          FROM review_resolutions
         WHERE resolution_id = v_review.decision_ref AND project_id = p_project_id;

        IF NOT FOUND THEN
            RAISE EXCEPTION
                'conflict_close: review % names resolution %, which does not exist in %',
                v_review.review_id, v_review.decision_ref, p_project_id;
        END IF;

        -- THE PAIR MUST MATCH, BOTH HALVES. `v3.3-a15` makes the reference typed, so agreeing on
        -- the id is no longer enough: a conflict closed as GOVERNANCE against a resolution that
        -- recorded BELIEF_REVISION would describe the same row as two different kinds of act.
        IF p_event_kind IS DISTINCT FROM v_resolution.resolution_event_kind THEN
            RAISE EXCEPTION
                'conflict_close: conflict % would close as a % event, but review %''s resolution % '
                'recorded a % event. The Conflict and the ReviewResolution must reference the same '
                '(kind, id) pair (§17.19.3, v3.3-a15)',
                p_conflict_id, p_event_kind, v_review.review_id,
                v_resolution.resolution_id, v_resolution.resolution_event_kind;
        END IF;

        IF p_resolution_event_id IS DISTINCT FROM v_resolution.resolution_event_id THEN
            RAISE EXCEPTION
                'conflict_close: conflict % would close as % against event %, but review %''s '
                'resolution produced event %. An event that merely belongs to the same project '
                'is not proof that this review resolved -- that substitution is the bug this '
                'check exists to refuse',
                p_conflict_id, p_resolution_status, p_resolution_event_id,
                v_review.review_id, v_resolution.resolution_event_id;
        END IF;
    ELSIF p_event_kind = 'GOVERNANCE' THEN
        -- A governance closure is the product of a review expiring. A conflict with no review
        -- never had one to expire, so this would be a governance event closing a block nobody was
        -- ever assigned -- the general-purpose bypass the closed vocabulary exists to prevent.
        RAISE EXCEPTION
            'conflict_close: conflict % is linked to no review, so it cannot close against a '
            'GovernanceEvent. v3.3-a15 permits GOVERNANCE only as the product of a REVIEW_EXPIRY, '
            'and a conflict with no reviewer has no review to expire',
            p_conflict_id;
    END IF;

    UPDATE conflicts
       SET resolution_status     = p_resolution_status,
           resolution_event_kind = p_event_kind,
           resolution_event_id   = CASE WHEN p_event_kind = 'BELIEF_REVISION'
                                        THEN p_resolution_event_id END,
           governance_event_id   = CASE WHEN p_event_kind = 'GOVERNANCE'
                                        THEN p_resolution_event_id END,
           resolved_at           = p_resolved_at
     WHERE conflict_id = p_conflict_id
       AND project_id  = p_project_id
       AND resolution_status IN ('OPEN', 'UNDER_REVIEW');

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    IF v_updated = 0 THEN
        RAISE EXCEPTION
            'conflict_close: % in % is already closed. Exactly one caller may close a conflict, '
            'and the loser of a race must hear about it rather than believe it won',
            p_conflict_id, p_project_id;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- THE FIVE-ARGUMENT VERSION MUST GO, AND THIS IS NOT TIDYING. `CREATE OR REPLACE` cannot change a
-- signature, so the six-argument function above is a *new* function and `011c`'s five-argument one
-- still exists beside it. PostgreSQL then refuses every five-argument call as ambiguous -- both
-- overloads match, because the sixth parameter has a default. Dropping the old arity is what makes
-- the default mean "an unqualified close is a BELIEF_REVISION close" rather than "pick one".
DROP FUNCTION IF EXISTS conflict_close(TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ);

-- ---------------------------------------------------------------------------------------------
-- 7. The human path, unchanged in meaning
-- ---------------------------------------------------------------------------------------------
--
-- `review_resolve_and_close_conflict` keeps its signature and now writes the kind explicitly.
-- Every existing caller is a human resolution and stays BELIEF_REVISION.

CREATE OR REPLACE FUNCTION review_resolve_and_close_conflict(
    p_resolution_id         TEXT,
    p_review_id             TEXT,
    p_project_id            TEXT,
    p_outcome               TEXT,
    p_resolved_by_actor_id  TEXT,
    p_rationale             TEXT,
    p_event_id              TEXT,
    p_conflict_status       TEXT,
    p_resolved_at           TIMESTAMPTZ
) RETURNS VOID AS $$
DECLARE
    v_conflict_id TEXT;
BEGIN
    SELECT conflict_id INTO v_conflict_id
      FROM conflicts
     WHERE review_id = p_review_id AND project_id = p_project_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'review_resolve_and_close_conflict: no conflict in % is linked to review %. '
            'Resolving a review that gates nothing would record a decision with no effect, and '
            'the caller would have no way to notice',
            p_project_id, p_review_id;
    END IF;

    INSERT INTO review_resolutions (
        resolution_id, review_id, project_id, outcome, resolved_by_actor_id,
        resolved_at, rationale, belief_revision_event_id, resolution_event_kind
    ) VALUES (
        p_resolution_id, p_review_id, p_project_id, p_outcome, p_resolved_by_actor_id,
        p_resolved_at, p_rationale, p_event_id, 'BELIEF_REVISION'
    );

    UPDATE review_items
       SET status = p_outcome,
           decision_ref = p_resolution_id
     WHERE review_id = p_review_id
       AND project_id = p_project_id
       AND status IN ('QUEUED', 'ASSIGNED');

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'review_resolve_and_close_conflict: review % in % is not outstanding. A second '
            'resolution would overwrite the first human decision',
            p_review_id, p_project_id;
    END IF;

    PERFORM conflict_close(
        v_conflict_id, p_project_id, p_conflict_status, p_event_id, p_resolved_at,
        'BELIEF_REVISION'
    );
END;
$$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------------------------------------
-- 8. The expiry path, as one statement
-- ---------------------------------------------------------------------------------------------
--
-- Creates the GovernanceEvent, records the EXPIRED resolution, terminalizes the review and closes
-- the conflict -- all inside one function, for the reason `011c` gave: neither half-state
-- `v3.3-a14` forbids may be observable after a crash or under concurrency.
--
-- THE POLICY VERSION IS AN ARGUMENT AND IS CHECKED AGAINST THE ITEM. `v3.3-a15`: an expiry
-- re-interpreted under a policy the reviewer never saw is not the deadline they were given. The
-- caller must pass the version the item was priced by, and passing any other is refused here
-- rather than silently honoured.

CREATE OR REPLACE FUNCTION review_expire(
    p_resolution_id        TEXT,
    p_governance_event_id  TEXT,
    p_review_id            TEXT,
    p_project_id           TEXT,
    p_policy_id            TEXT,
    p_policy_version       TEXT,
    p_actor_id             TEXT,
    p_reason_code          TEXT,
    p_rationale            TEXT,
    p_now                  TIMESTAMPTZ,
    p_trace_id             TEXT
) RETURNS VOID AS $$
DECLARE
    v_review      review_items;
    v_conflict_id TEXT;
    v_declared_by TEXT;
BEGIN
    SELECT * INTO v_review
      FROM review_items
     WHERE review_id = p_review_id AND project_id = p_project_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'review_expire: review % does not exist in %', p_review_id, p_project_id;
    END IF;

    IF v_review.status NOT IN ('QUEUED', 'ASSIGNED') THEN
        RAISE EXCEPTION
            'review_expire: review % is %, so it has already left the queue. Expiring it again '
            'would overwrite the record of how it was actually resolved',
            p_review_id, v_review.status;
    END IF;

    -- THE DEADLINE IS WHAT MAKES AN EXPIRY LEGITIMATE. A sweep that could expire anything on
    -- request is a way to clear an inconvenient review.
    IF v_review.expires_at IS NULL OR v_review.expires_at > p_now THEN
        RAISE EXCEPTION
            'review_expire: review % expires at %, which is not before %. Expiring an item early '
            'is a way to clear an inconvenient review, and the declared deadline is the only thing '
            'that makes an expiry legitimate',
            p_review_id, v_review.expires_at, p_now;
    END IF;

    IF v_review.queue_policy_id IS DISTINCT FROM p_policy_id
       OR v_review.queue_policy_version IS DISTINCT FROM p_policy_version THEN
        RAISE EXCEPTION
            'review_expire: review % was priced by %@% but the expiry cites %@%. v3.3-a15 requires '
            'the version the item was priced by -- an expiry re-interpreted under a policy the '
            'reviewer never saw is not the deadline they were given',
            p_review_id, v_review.queue_policy_id, v_review.queue_policy_version,
            p_policy_id, p_policy_version;
    END IF;

    SELECT declared_by_actor_id INTO v_declared_by
      FROM review_queue_policies
     WHERE policy_id = p_policy_id AND version = p_policy_version AND project_id = p_project_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'review_expire: queue policy %@% does not exist in %',
            p_policy_id, p_policy_version, p_project_id;
    END IF;

    SELECT conflict_id INTO v_conflict_id
      FROM conflicts
     WHERE review_id = p_review_id AND project_id = p_project_id;

    INSERT INTO governance_events (
        event_id, project_id, event_type, subject_type, subject_id, related_conflict_id,
        policy_id, policy_version, declared_by_actor_id, actor_id, reason_code, rationale,
        occurred_at, trace_id, episode_id
    ) VALUES (
        p_governance_event_id, p_project_id, 'REVIEW_EXPIRY', 'REVIEW_ITEM', p_review_id,
        v_conflict_id, p_policy_id, p_policy_version, v_declared_by, p_actor_id,
        p_reason_code, p_rationale, p_now, p_trace_id, v_review.episode_id
    );

    INSERT INTO review_resolutions (
        resolution_id, review_id, project_id, outcome, resolved_by_actor_id,
        resolved_at, rationale, governance_event_id, resolution_event_kind
    ) VALUES (
        p_resolution_id, p_review_id, p_project_id, 'EXPIRED', p_actor_id,
        p_now, p_rationale, p_governance_event_id, 'GOVERNANCE'
    );

    UPDATE review_items
       SET status = 'EXPIRED',
           decision_ref = p_resolution_id
     WHERE review_id = p_review_id
       AND project_id = p_project_id
       AND status IN ('QUEUED', 'ASSIGNED');

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'review_expire: review % in % stopped being outstanding concurrently',
            p_review_id, p_project_id;
    END IF;

    IF v_conflict_id IS NOT NULL THEN
        -- ACCEPTED_AS_OPEN_QUESTION, and §17.19.3's honest status is the point. The authority
        -- question is exactly as open as it was; RESOLVED would claim an answer the timeout did
        -- not produce, and a later episode over the same INCOMPARABLE comparison must still
        -- escalate.
        PERFORM conflict_close(
            v_conflict_id, p_project_id, 'ACCEPTED_AS_OPEN_QUESTION',
            p_governance_event_id, p_now, 'GOVERNANCE'
        );
    END IF;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION review_expire(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ, TEXT
) IS
    'v3.3-a15 / OPS-002: the supported automatic expiry. Creates the REVIEW_EXPIRY GovernanceEvent, '
    'records the EXPIRED resolution, terminalizes the review and closes the linked conflict as '
    'ACCEPTED_AS_OPEN_QUESTION -- one statement, so no half-state is observable. Writes no '
    'BeliefRevisionEvent and leaves EpistemicStateProjection unchanged.';

-- ---------------------------------------------------------------------------------------------
-- 9. `011d`'s commit-boundary invariant learns the typed pair
-- ---------------------------------------------------------------------------------------------
--
-- Replaces the body only. Every check `011d` made is preserved; the closure-traceability comparison
-- becomes a comparison of (kind, id) rather than of a belief event id, because a conflict closed as
-- GOVERNANCE has no `resolution_event_id` at all and the old comparison would read that as a
-- substituted event.

CREATE OR REPLACE FUNCTION review_conflict_invariant_assert(
    p_project_id TEXT,
    p_review_id  TEXT
) RETURNS VOID AS $$
DECLARE
    v_review      review_items;
    v_resolution  review_resolutions;
    v_conflict    conflicts;
    v_outstanding BOOLEAN;
    v_conflict_event TEXT;
BEGIN
    SELECT * INTO v_review
      FROM review_items
     WHERE review_id = p_review_id AND project_id = p_project_id;

    IF NOT FOUND THEN
        RETURN;
    END IF;

    v_outstanding := v_review.status IN ('QUEUED', 'ASSIGNED');

    IF v_outstanding THEN
        IF v_review.decision_ref IS NOT NULL THEN
            RAISE EXCEPTION
                'review % is % but carries decision_ref %. An outstanding review must not look '
                'answered -- a reader checking decision_ref would conclude a human had decided',
                v_review.review_id, v_review.status, v_review.decision_ref;
        END IF;
    ELSE
        IF v_review.decision_ref IS NULL THEN
            RAISE EXCEPTION
                'review % is % with no decision_ref. §17.19.1 as amended by v3.3-a14 requires a '
                'terminal review to record how it was resolved; without it the review is a human '
                'decision with no record of what was decided',
                v_review.review_id, v_review.status;
        END IF;

        SELECT * INTO v_resolution
          FROM review_resolutions
         WHERE resolution_id = v_review.decision_ref;

        IF NOT FOUND THEN
            RAISE EXCEPTION
                'review % is % and names resolution %, which does not exist. A terminal review '
                'whose decision_ref resolves to nothing is unauditable',
                v_review.review_id, v_review.status, v_review.decision_ref;
        END IF;

        IF v_resolution.review_id IS DISTINCT FROM v_review.review_id THEN
            RAISE EXCEPTION
                'review % names resolution %, which resolved review % instead. A terminal review '
                'must cite the record of its own resolution; borrowing another review''s makes one '
                'human decision stand in for a second that never happened',
                v_review.review_id, v_resolution.resolution_id, v_resolution.review_id;
        END IF;

        IF v_resolution.project_id IS DISTINCT FROM v_review.project_id THEN
            RAISE EXCEPTION
                'review % in % names resolution % in %. A decision recorded in one project cannot '
                'resolve another project''s review (SEC-002)',
                v_review.review_id, v_review.project_id,
                v_resolution.resolution_id, v_resolution.project_id;
        END IF;

        IF v_resolution.outcome IS DISTINCT FROM v_review.status THEN
            RAISE EXCEPTION
                'review % is % but its resolution % records outcome %. These are two accounts of '
                'the same decision and must agree; whichever a reader consulted first would settle '
                'the belief',
                v_review.review_id, v_review.status,
                v_resolution.resolution_id, v_resolution.outcome;
        END IF;

        -- `v3.3-a15`: a GovernanceEvent closure is only ever the product of an expiry, and the
        -- CHECK on `review_resolutions` says so too. Repeated here because the CHECK guards one
        -- row and this guards the pair at commit.
        IF v_resolution.resolution_event_kind = 'GOVERNANCE'
           AND v_resolution.outcome <> 'EXPIRED' THEN
            RAISE EXCEPTION
                'resolution % closes review % as % against a GovernanceEvent. v3.3-a15 permits '
                'GOVERNANCE only for EXPIRED: APPROVED, CORRECTED and REJECTED are decisions '
                'somebody made, and a governance event records that nobody did',
                v_resolution.resolution_id, v_review.review_id, v_resolution.outcome;
        END IF;
    END IF;

    FOR v_conflict IN
        SELECT * FROM conflicts WHERE review_id = v_review.review_id
    LOOP
        IF v_conflict.project_id IS DISTINCT FROM v_review.project_id THEN
            RAISE EXCEPTION
                'conflict % in % is gated by review % in %. A review cannot gate another project''s '
                'conflict (SEC-002)',
                v_conflict.conflict_id, v_conflict.project_id,
                v_review.review_id, v_review.project_id;
        END IF;

        IF v_outstanding THEN
            IF v_conflict.resolution_status NOT IN ('OPEN', 'UNDER_REVIEW') THEN
                RAISE EXCEPTION
                    'conflict % is % while review % is still %. §17.19.1 as amended by v3.3-a14 '
                    'forbids an outstanding review beside a closed conflict -- ASSIGNED included, '
                    'since somebody having picked the task up is not somebody having answered. The '
                    'belief would be unblocked by a human decision nobody made',
                    v_conflict.conflict_id, v_conflict.resolution_status,
                    v_review.review_id, v_review.status;
            END IF;
        ELSE
            IF v_conflict.resolution_status IN ('OPEN', 'UNDER_REVIEW') THEN
                RAISE EXCEPTION
                    'review % is % but conflict % is still %. v3.3-a14 forbids a terminal review '
                    'beside an unresolved conflict: the human has decided and the block is still '
                    'in place, which no later reader can distinguish from nobody having looked',
                    v_review.review_id, v_review.status,
                    v_conflict.conflict_id, v_conflict.resolution_status;
            END IF;

            -- THE PAIR, BOTH HALVES (`v3.3-a15`). Agreeing on the id is no longer sufficient:
            -- the kind is part of what the closure claims happened.
            IF v_conflict.resolution_event_kind IS DISTINCT FROM v_resolution.resolution_event_kind
            THEN
                RAISE EXCEPTION
                    'conflict % closed against a % event but review %''s resolution % recorded a % '
                    'event. The Conflict and the ReviewResolution must reference the same '
                    '(kind, id) pair',
                    v_conflict.conflict_id, v_conflict.resolution_event_kind,
                    v_review.review_id, v_resolution.resolution_id,
                    v_resolution.resolution_event_kind;
            END IF;

            v_conflict_event := COALESCE(
                v_conflict.resolution_event_id, v_conflict.governance_event_id);

            IF v_conflict_event IS DISTINCT FROM v_resolution.resolution_event_id THEN
                RAISE EXCEPTION
                    'conflict % closed as % against event %, but review %''s resolution % produced '
                    'event %. An event that merely belongs to the same project is not proof that '
                    'this review resolved',
                    v_conflict.conflict_id, v_conflict.resolution_status, v_conflict_event,
                    v_review.review_id, v_resolution.resolution_id,
                    v_resolution.resolution_event_id;
            END IF;
        END IF;
    END LOOP;
END;
$$ LANGUAGE plpgsql;
