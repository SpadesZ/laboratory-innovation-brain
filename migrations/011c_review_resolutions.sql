-- 011c — a review actually has to resolve before its conflict closes (`v3.3-a14`)
--
-- Forward-only. `011a` and `011b` are applied and are not touched.
--
-- WHAT WENT WRONG IN P11, BECAUSE IT EXPLAINS EVERY CONSTRAINT BELOW. The Phase D end-to-end test
-- claimed to exercise "review resolution closes the conflict" and did not: it pre-created a
-- `BeliefRevisionEvent` in its fixture, left the `ReviewItem` at `QUEUED`, and passed that
-- unrelated event to `conflict_close` as the closure proof. `conflict_close` never looked at the
-- review, so it worked. The test asserted a loop it never ran, and the handoff repeated the claim.
--
-- `v3.3-a14` settles what was unexecutable about it: §17.19.1's `decision_ref` had appeared once,
-- in a field list, with no prose saying what it points at or when it is required -- so "until the
-- review resolves" had no definition to enforce. It has one now, and this migration enforces it.
--
-- FOUR OBLIGATIONS, FOUR MECHANISMS:
--   1. a terminal review MUST carry `decision_ref`      -> trigger on `review_items`
--   2. an outstanding review keeps its conflict open     -> checked inside `conflict_close`
--   3. closure names *that* review's resolution event    -> checked inside `conflict_close`
--   4. no half-completed resolve-and-close               -> `review_resolve_and_close_conflict`
--
-- WHAT IS STILL NOT IN SQL. No belief semantics. The database does not evaluate a
-- `TransitionPolicy`, does not decide whether a conflict should block, and does not judge whether
-- a human's answer was correct. It enforces that the answer exists, that it belongs to this
-- review, and that the two records cannot come apart (`v3.3-a13`).

-- ---------------------------------------------------------------------------------------------
-- 1. The durable resolution record
-- ---------------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS review_resolutions (
    resolution_id           TEXT PRIMARY KEY,
    review_id               TEXT NOT NULL,
    project_id              TEXT NOT NULL REFERENCES projects (project_id),

    -- The terminal status this resolution put the review into. §17.19.1's four terminal values;
    -- the two outstanding ones are not resolutions and cannot appear here.
    outcome                 TEXT NOT NULL CHECK (outcome IN (
                                'APPROVED', 'CORRECTED', 'REJECTED', 'EXPIRED')),

    resolved_by_actor_id    TEXT NOT NULL REFERENCES actors (actor_id),
    resolved_at             TIMESTAMPTZ NOT NULL,

    -- Why. Free text on purpose: this is a human's reasoning, and the one field in this schema
    -- that should not be a closed vocabulary. It is not consulted by any gate.
    rationale               TEXT NOT NULL,

    -- REQUIRED, and the first draft of this migration had it nullable. A test written against
    -- that draft tried to close a conflict as ACCEPTED_AS_OPEN_QUESTION with no event, and
    -- `conflicts_only_close` refused -- correctly, because the P10 ruling is that *every* status
    -- which stops a conflict blocking must carry its closure event, with no exception unless the
    -- spec defines an alternative versioned closure event, and it does not. Unblocking a belief
    -- is itself a recordable act (§6.18), so "the reviewer decided to proceed with the
    -- disagreement on the record" needs an event just as much as "the reviewer settled it".
    belief_revision_event_id TEXT NOT NULL,

    -- One resolution per review. A second would mean two accounts of what the human decided, and
    -- whichever was read first would decide a belief.
    CONSTRAINT review_resolutions_one_per_review UNIQUE (review_id),

    -- Composite, so a resolution cannot belong to another project's review.
    CONSTRAINT review_resolutions_review_in_project
        FOREIGN KEY (review_id, project_id) REFERENCES review_items (review_id, project_id),

    -- Composite, so the produced event cannot belong to another project.
    CONSTRAINT review_resolutions_event_in_project
        FOREIGN KEY (belief_revision_event_id, project_id)
        REFERENCES belief_revision_events (event_id, project_id),

    CONSTRAINT review_resolutions_id_project_unique UNIQUE (resolution_id, project_id)
);

COMMENT ON TABLE review_resolutions IS
    'v3.3-a14: the durable record §17.19.1 decision_ref points at. A terminal ReviewItem must '
    'have one, and a linked Conflict may only close against the event this resolution produced.';

CREATE INDEX IF NOT EXISTS review_resolutions_review_idx
    ON review_resolutions (project_id, review_id);

-- `decision_ref` becomes a checked, project-scoped reference to the resolution.
ALTER TABLE review_items
    DROP CONSTRAINT IF EXISTS review_items_decision_ref_in_project;
ALTER TABLE review_items
    ADD CONSTRAINT review_items_decision_ref_in_project
    FOREIGN KEY (decision_ref, project_id)
    REFERENCES review_resolutions (resolution_id, project_id)
    -- Deferred: the resolution row and the review's `decision_ref` are written in the same
    -- statement and each references the other, so a non-deferrable constraint would refuse the
    -- only order they can legally be written in.
    DEFERRABLE INITIALLY DEFERRED;

COMMENT ON COLUMN review_items.decision_ref IS
    'v3.3-a14: the review_resolutions row recording how this review was resolved. Required for '
    'every terminal status, and a deferred foreign key because review and resolution reference '
    'each other within one statement.';

-- ---------------------------------------------------------------------------------------------
-- 2. A terminal review must carry its resolution
-- ---------------------------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION review_items_terminal_needs_a_decision()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.status IN ('QUEUED', 'ASSIGNED') THEN
        IF NEW.decision_ref IS NOT NULL THEN
            RAISE EXCEPTION
                'review % is % but carries decision_ref %. An outstanding review must not look '
                'answered -- a reader checking decision_ref would conclude a human had decided',
                NEW.review_id, NEW.status, NEW.decision_ref;
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.decision_ref IS NULL THEN
        RAISE EXCEPTION
            'review % cannot become % with no decision_ref. §17.19.1 as amended by v3.3-a14 '
            'requires a terminal review to record how it was resolved; without it the review is '
            'a human decision with no record of what was decided, and a conflict closed behind '
            'it would be unauditable',
            NEW.review_id, NEW.status;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS review_items_terminal_needs_a_decision ON review_items;
CREATE TRIGGER review_items_terminal_needs_a_decision
    BEFORE INSERT OR UPDATE ON review_items
    FOR EACH ROW EXECUTE FUNCTION review_items_terminal_needs_a_decision();

-- ---------------------------------------------------------------------------------------------
-- 3. `conflict_close` now consults the linked review
-- ---------------------------------------------------------------------------------------------
--
-- Replaces the `011a` body. The signature is unchanged, so every existing caller keeps working
-- and picks up the check -- which is the point: a caller that could opt out would.

CREATE OR REPLACE FUNCTION conflict_close(
    p_conflict_id          TEXT,
    p_project_id           TEXT,
    p_resolution_status    TEXT,
    p_resolution_event_id  TEXT,
    p_resolved_at          TIMESTAMPTZ
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

    SELECT * INTO v_conflict
      FROM conflicts
     WHERE conflict_id = p_conflict_id AND project_id = p_project_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'conflict_close: % in % does not exist. Reporting success would tell a caller a block '
            'had lifted while it is still in place -- or in a project it never named',
            p_conflict_id, p_project_id;
    END IF;

    -- THE OUTSTANDING REVIEW INVARIANT (`v3.3-a14`). Checked before anything is written.
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

        -- CLOSURE TRACEABILITY. The event must be the one *this* review's resolution produced,
        -- whatever terminal status the conflict is taking. Any other same-project event, and any
        -- other review's resolution event, is refused -- which is precisely the substitution
        -- P11's E2E made. Uniform across statuses on purpose: a per-status exemption is how the
        -- P10 audit's terminal-state hole appeared in the first place.
        IF p_resolution_event_id IS DISTINCT FROM v_resolution.belief_revision_event_id THEN
            RAISE EXCEPTION
                'conflict_close: conflict % would close as % against event %, but review %''s '
                'resolution produced event %. An event that merely belongs to the same project '
                'is not proof that this review resolved -- that substitution is the bug this '
                'check exists to refuse',
                p_conflict_id, p_resolution_status, p_resolution_event_id,
                v_review.review_id, v_resolution.belief_revision_event_id;
        END IF;
    END IF;

    UPDATE conflicts
       SET resolution_status   = p_resolution_status,
           resolution_event_id = p_resolution_event_id,
           resolved_at         = p_resolved_at
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

-- ---------------------------------------------------------------------------------------------
-- 4. Resolve and close, atomically
-- ---------------------------------------------------------------------------------------------
--
-- One statement, so neither half-state `v3.3-a14` names is observable: not "review terminal,
-- conflict open" and not "review outstanding, conflict closed". The `UPDATE ... WHERE
-- resolution_status IN ('OPEN','UNDER_REVIEW')` inside `conflict_close` is what makes the race
-- safe -- two callers cannot both match the row, so exactly one wins and the other raises.

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
        resolved_at, rationale, belief_revision_event_id
    ) VALUES (
        p_resolution_id, p_review_id, p_project_id, p_outcome, p_resolved_by_actor_id,
        p_resolved_at, p_rationale, p_event_id
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
        v_conflict_id, p_project_id, p_conflict_status, p_event_id, p_resolved_at
    );
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION review_resolve_and_close_conflict(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ
) IS
    'v3.3-a14: the supported path. Records the resolution, terminalizes the review and closes the '
    'linked conflict in one statement, so no half-completed state is observable.';

-- ---------------------------------------------------------------------------------------------
-- 5. Escalation is idempotent, and a review link is written once
-- ---------------------------------------------------------------------------------------------
--
-- `011b` accepted a conflict already `UNDER_REVIEW`, so a retried episode could insert a second
-- ReviewItem and overwrite `review_id` -- orphaning the first review, which would sit in the
-- queue gating nothing while the block it was raised for pointed elsewhere.

-- Dropped rather than replaced: the return type changes from VOID to TEXT, and
-- `CREATE OR REPLACE` cannot do that. Returning the review id is what makes a retried escalation
-- idempotent rather than merely harmless -- the caller gets the review that already exists.
DROP FUNCTION IF EXISTS authority_conflict_escalate(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ, TEXT, TEXT, INTEGER
);

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

    -- IDEMPOTENT. A retried episode gets the review that already exists, deterministically,
    -- rather than a second one. Returning it is better than raising: the retry is legitimate and
    -- the caller wants the review id, and a second row is the one outcome that must not happen.
    IF v_conflict.review_id IS NOT NULL THEN
        RETURN v_conflict.review_id;
    END IF;

    INSERT INTO review_items (
        review_id, project_id, subject_type, subject_id, stakes, reason, trace_id,
        created_at, required_authority, episode_id, estimated_human_minutes
    ) VALUES (
        p_review_id, p_project_id, 'AUTHORITY_CONFLICT', p_conflict_id, p_stakes, p_reason,
        p_trace_id, p_created_at, p_required_authority, p_episode_id,
        COALESCE(p_estimated_human_minutes, 0)
    );

    -- Conditioned on `review_id IS NULL`, which is what makes two concurrent escalations resolve
    -- to one winner rather than one overwriting the other.
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

-- ---------------------------------------------------------------------------------------------
-- 6. Immutability, completed
-- ---------------------------------------------------------------------------------------------
--
-- `011a` protected identity, type, blocking, subjects and detection provenance, and left
-- `supporting_refs` and `episode_id` editable. Both are scientific provenance: the first is the
-- evidence the conflict rests on and the second is the episode that found it, and rewriting
-- either changes what the disagreement was. `review_id` is protected too -- writable exactly
-- once, from NULL.

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

    -- Written once, from NULL. Replacing it orphans the review that was gating this conflict.
    IF OLD.review_id IS NOT NULL AND NEW.review_id IS DISTINCT FROM OLD.review_id THEN
        RAISE EXCEPTION
            'conflict % is already gated by review %; it cannot be re-pointed at %. The first '
            'review would stay in the queue gating nothing while the block it was raised for '
            'pointed somewhere else',
            OLD.conflict_id, OLD.review_id, NEW.review_id;
    END IF;

    IF OLD.resolution_status NOT IN ('OPEN', 'UNDER_REVIEW') THEN
        RAISE EXCEPTION
            'conflict % is already %, closed by %. Re-resolving or reopening would overwrite the '
            'event that justified the first close, leaving two incompatible accounts of why a '
            'belief became promotable again',
            OLD.conflict_id, OLD.resolution_status, OLD.resolution_event_id;
    END IF;

    IF NEW.resolution_status IN ('OPEN', 'UNDER_REVIEW') THEN
        RETURN NEW;
    END IF;

    IF NEW.resolution_event_id IS NULL OR NEW.resolved_at IS NULL THEN
        RAISE EXCEPTION
            'conflict % cannot become % without a resolution_event_id and resolved_at. §25.3 '
            'EPI-006 requires closing a conflict to record the event that closed it; changing the '
            'status alone would unblock a belief with no recoverable reason',
            OLD.conflict_id, NEW.resolution_status;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
