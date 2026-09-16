-- 011a — §17.19.3 Conflict, enforced by the database (EPI-006)
--
-- The `011` slot is Appendix A's `011_predictions_conflicts.sql`; the `a` suffix takes the
-- conflict half and leaves Prediction to a later migration, the same convention 005a–005d used.
-- Forward-only: nothing already applied is touched.
--
-- WHY THIS EXISTS WHEN THE MODEL ALREADY ENFORCES ALL OF IT. Because that is the sentence this
-- project has had to learn four times. `BeliefRevisionEvent` was model-validated and raw SQL
-- wrote an unauthorised one (P7). `005c` closed the inconsistent forgeries and raw SQL still
-- wrote an unauthorised event with no Decision (P8). The read path trusted the write path and a
-- semantically forged Decision reached a projection (P9). A Python-only guard holds for callers
-- who go through Python, and a migration, a support script or a future service writes SQL.
--
-- WHAT THE DATABASE CANNOT DO, STATED SO NOBODY LOOKS FOR IT. It cannot decide whether a given
-- `conflict_type` *should* be blocking -- that is `blocking`, supplied by the domain -- and it
-- cannot evaluate `TransitionPolicy.blocking_conflict_policy`, because §8.2.1 lives in Python and
-- duplicating it in SQL would make semantic truth two definitions that drift (`v3.3-a13`). What
-- it enforces is everything that makes those decisions trustworthy: the vocabulary is closed, a
-- conflict names a subject, a closure carries the event that closed it, an open conflict cannot
-- look half-closed, the scientific identity cannot be edited, and nothing can be deleted.

-- ---------------------------------------------------------------------------------------------
-- 1. The record
-- ---------------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS conflicts (
    conflict_id                TEXT PRIMARY KEY,
    project_id                 TEXT NOT NULL REFERENCES projects (project_id),

    -- §17.19.3's seven. Closed, because `blocking_conflict_policy` matches against it and an
    -- unknown value would match nothing -- a fail-open typo, which is exactly the hole the P10
    -- audit found on the Python side.
    conflict_type              TEXT NOT NULL CHECK (conflict_type IN (
                                   'PROVENANCE_CONFLICT',
                                   'CONDITION_CONFLICT',
                                   'VALIDITY_CONFLICT',
                                   'AUTHORITY_CONFLICT',
                                   'SIM_TO_REAL_CONFLICT',
                                   'SOURCE_RETRACTION_CONFLICT',
                                   'INDEPENDENCE_UNRESOLVED')),

    -- §17.19.3's five.
    resolution_status          TEXT NOT NULL DEFAULT 'OPEN' CHECK (resolution_status IN (
                                   'OPEN',
                                   'UNDER_REVIEW',
                                   'RESOLVED',
                                   'ACCEPTED_AS_OPEN_QUESTION',
                                   'EXPIRED')),

    -- Consumed by `TransitionPolicy.blocking_conflict_policy`. The domain decides the value; the
    -- database only insists there is one.
    blocking                   BOOLEAN NOT NULL,

    -- A conflict about nothing cannot appear in any hypothesis's `unresolved_conflicts`.
    subject_refs               TEXT[] NOT NULL CHECK (cardinality(subject_refs) >= 1),
    supporting_refs            TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],

    detected_at                TIMESTAMPTZ NOT NULL,
    detected_by_actor_or_slot  TEXT NOT NULL,
    trace_id                   TEXT NOT NULL,
    episode_id                 TEXT,

    -- The ReviewItem this was escalated to. The foreign key arrives with the review_items table;
    -- until then this is an unchecked reference and the column comment says so rather than
    -- leaving a reader to assume it resolves.
    review_id                  TEXT,

    resolved_at                TIMESTAMPTZ,
    resolution_event_id        TEXT,

    -- THE INVARIANT THE P10 AUDIT FOUND MISSING IN PYTHON, AS ONE CHECK RATHER THAN THREE.
    -- Any status that stops a conflict blocking must carry the event that closed it. Written as
    -- an equality between two predicates so neither direction can be relaxed alone: a terminal
    -- status without a closure is refused, and an open one carrying closure details is refused
    -- too -- a reader checking `resolution_event_id` to decide whether something was dealt with
    -- would otherwise conclude it had been.
    CONSTRAINT conflicts_closure_matches_status CHECK (
        (resolution_status IN ('OPEN', 'UNDER_REVIEW'))
        = (resolved_at IS NULL AND resolution_event_id IS NULL)
    ),

    -- Composite, so a conflict cannot be closed by an event belonging to another project.
    -- `belief_revision_events` carries UNIQUE (event_id, project_id) from `005c`, which is what
    -- makes the cross-project reference unrepresentable rather than merely rejected.
    CONSTRAINT conflicts_resolution_event_in_project
        FOREIGN KEY (resolution_event_id, project_id)
        REFERENCES belief_revision_events (event_id, project_id),

    -- Lets other tables reference a conflict *with* its project, for the same reason.
    CONSTRAINT conflicts_id_project_unique UNIQUE (conflict_id, project_id)
);

COMMENT ON TABLE conflicts IS
    'EPI-006 / §17.19.3. The single object shared by blocking_conflict_policy, '
    'unresolved_conflicts[] and ReviewItem(CONFLICT). Append-only: closure is an UPDATE through '
    'conflict_close(), and DELETE is refused.';

COMMENT ON COLUMN conflicts.review_id IS
    'ReviewItem this conflict was escalated to. Not yet a foreign key -- the review_items table '
    'arrives with the EPI-004 ReviewItem integration -- so do not read this as a checked '
    'reference.';

COMMENT ON COLUMN conflicts.blocking IS
    'Domain-supplied. The database does not decide which conflict types gate belief, and cannot '
    'evaluate blocking_conflict_policy: §8.2.1 is the single source of semantic truth (v3.3-a13).';

CREATE INDEX IF NOT EXISTS conflicts_project_status_idx
    ON conflicts (project_id, resolution_status, detected_at, conflict_id);

-- GIN over the subject array, because the query that matters is "every conflict naming this
-- hypothesis" and it is the one a transition gate runs.
CREATE INDEX IF NOT EXISTS conflicts_subject_refs_idx
    ON conflicts USING GIN (subject_refs);

-- ---------------------------------------------------------------------------------------------
-- 2. No DELETE, ever
-- ---------------------------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION conflicts_are_never_deleted()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        'conflicts are append-only: DELETE of % is refused. Removing a conflict erases the '
        'reason a belief was blocked, and a belief whose block has no recorded cause is '
        'indistinguishable from one that was never blocked (§17.19.3, EPI-006)',
        OLD.conflict_id;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS conflicts_no_delete ON conflicts;
CREATE TRIGGER conflicts_no_delete
    BEFORE DELETE ON conflicts
    FOR EACH ROW EXECUTE FUNCTION conflicts_are_never_deleted();

-- ---------------------------------------------------------------------------------------------
-- 3. The scientific identity is immutable; only a closure may be written
-- ---------------------------------------------------------------------------------------------
--
-- An UPDATE is permitted for exactly one purpose: moving an unresolved conflict to a terminal
-- status with its closure event. Everything else about the row is what the conflict *is*, and
-- editing it would rewrite the disagreement rather than resolve it.

CREATE OR REPLACE FUNCTION conflicts_only_close()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.conflict_id      IS DISTINCT FROM OLD.conflict_id
       OR NEW.project_id    IS DISTINCT FROM OLD.project_id
       OR NEW.conflict_type IS DISTINCT FROM OLD.conflict_type
       OR NEW.blocking      IS DISTINCT FROM OLD.blocking
       OR NEW.subject_refs  IS DISTINCT FROM OLD.subject_refs
       OR NEW.detected_at   IS DISTINCT FROM OLD.detected_at
       OR NEW.detected_by_actor_or_slot IS DISTINCT FROM OLD.detected_by_actor_or_slot
       OR NEW.trace_id      IS DISTINCT FROM OLD.trace_id THEN
        RAISE EXCEPTION
            'conflict %: identity, type, blocking flag, subjects and detection provenance are '
            'immutable. Editing them rewrites what the disagreement was rather than resolving '
            'it -- and flipping `blocking` to false is the quietest way to unblock a belief with '
            'no record that anything happened',
            OLD.conflict_id;
    END IF;

    IF OLD.resolution_status NOT IN ('OPEN', 'UNDER_REVIEW') THEN
        RAISE EXCEPTION
            'conflict % is already %, closed by %. Re-resolving would overwrite the event that '
            'justified the first close, leaving two incompatible accounts of why a belief became '
            'promotable again',
            OLD.conflict_id, OLD.resolution_status, OLD.resolution_event_id;
    END IF;

    -- Moving between the two unresolved statuses is legal and carries no closure: escalating to
    -- UNDER_REVIEW is not resolving, and a conflict under review still blocks.
    IF NEW.resolution_status IN ('OPEN', 'UNDER_REVIEW') THEN
        RETURN NEW;
    END IF;

    IF NEW.resolution_event_id IS NULL OR NEW.resolved_at IS NULL THEN
        -- The CHECK would also refuse this; the trigger says it in language an operator can act
        -- on, and BEFORE UPDATE runs first.
        RAISE EXCEPTION
            'conflict % cannot become % without a resolution_event_id and resolved_at. §25.3 '
            'EPI-006 requires closing a conflict to record the event that closed it; changing the '
            'status alone would unblock a belief with no recoverable reason',
            OLD.conflict_id, NEW.resolution_status;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS conflicts_only_close ON conflicts;
CREATE TRIGGER conflicts_only_close
    BEFORE UPDATE ON conflicts
    FOR EACH ROW EXECUTE FUNCTION conflicts_only_close();

-- ---------------------------------------------------------------------------------------------
-- 4. The atomic, event-linked close path
-- ---------------------------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION conflict_close(
    p_conflict_id          TEXT,
    p_project_id           TEXT,
    p_resolution_status    TEXT,
    p_resolution_event_id  TEXT,
    p_resolved_at          TIMESTAMPTZ
) RETURNS VOID AS $$
DECLARE
    v_updated INTEGER;
BEGIN
    IF p_resolution_status IN ('OPEN', 'UNDER_REVIEW') THEN
        RAISE EXCEPTION
            'conflict_close: % is not a closure. Moving a conflict to UNDER_REVIEW is a different '
            'operation and must not carry a resolution event', p_resolution_status;
    END IF;

    -- One statement, scoped on both columns, and conditioned on the row still being unresolved.
    -- That condition is the concurrency guarantee: two callers racing to close the same conflict
    -- cannot both succeed, because the second matches zero rows rather than overwriting the
    -- first's event.
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
            'conflict_close: % in % is absent or already closed. Reporting success here would '
            'tell a caller a block had lifted while it is still in place -- or lift one in a '
            'project the caller never named',
            p_conflict_id, p_project_id;
    END IF;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION conflict_close(TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ) IS
    'EPI-006: the only supported way to close a conflict. Project-scoped, conditioned on the row '
    'still being unresolved, and one statement -- so a race cannot produce two closures.';
