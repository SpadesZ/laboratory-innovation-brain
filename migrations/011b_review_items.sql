-- 011b — ReviewItem minimum schema, and the conflict's link to it (EPI-004)
--
-- §26's M0b row lists "ReviewItem minimum schema" alongside migrations 005–007 and 010–011, so
-- this belongs here rather than in M1. Forward-only; nothing applied is touched.
--
-- THIS IS A SHARED FOUNDATION, NOT UX-005. §17.19.1's `ReviewItem` is also the object UX-005
-- requires for NEEDS_REVIEW, and T-UX-005's pass condition is about ReviewQueue *depth* and
-- measurable human-review Capability availability -- neither of which exists yet. What lands here
-- is only what T-EPI-004 needs: an INCOMPARABLE authority comparison must auto-create a
-- `ReviewItem(subject_type=AUTHORITY_CONFLICT)` whose `subject_id` is a conflict_id, and a belief
-- must stay blocked until that review resolves. Claiming UX-005 on this basis would be claiming a
-- requirement whose test nothing here runs.
--
-- WHY `subject_id` IS NOT A FOREIGN KEY. §17.19.1 lets a ReviewItem review several kinds of
-- subject -- §17.19.3 says `ReviewItem(subject_type=CONFLICT | AUTHORITY_CONFLICT).subject_id` is
-- a conflict_id, and other subject types point elsewhere. A single foreign key cannot express a
-- reference whose target table depends on a sibling column, so the AUTHORITY_CONFLICT case is
-- checked by trigger instead: for that subject_type the subject must be a conflict in the same
-- project. Stated here rather than left as an apparent omission.

CREATE TABLE IF NOT EXISTS review_items (
    review_id                 TEXT PRIMARY KEY,
    project_id                TEXT NOT NULL REFERENCES projects (project_id),

    -- Only the two conflict subject types are usable yet. The CHECK is narrow on purpose: the
    -- other §17.19.1 subject types arrive with the requirements that need them, and a permissive
    -- CHECK now would let a row in that no code path reviews.
    subject_type              TEXT NOT NULL CHECK (subject_type IN ('CONFLICT', 'AUTHORITY_CONFLICT')),
    subject_id                TEXT NOT NULL,

    stakes                    TEXT NOT NULL,
    reason                    TEXT NOT NULL,

    status                    TEXT NOT NULL DEFAULT 'QUEUED' CHECK (status IN (
                                  'QUEUED', 'ASSIGNED', 'APPROVED',
                                  'CORRECTED', 'REJECTED', 'EXPIRED')),

    episode_id                TEXT,
    trace_id                  TEXT NOT NULL,
    required_authority        TEXT,
    required_role             TEXT,
    assigned_actor_id         TEXT REFERENCES actors (actor_id),
    decision_ref              TEXT,
    estimated_human_minutes   INTEGER NOT NULL DEFAULT 0
                                  CHECK (estimated_human_minutes >= 0),

    created_at                TIMESTAMPTZ NOT NULL,
    due_at                    TIMESTAMPTZ,
    expires_at                TIMESTAMPTZ,

    -- Lets a conflict reference its review *with* its project.
    CONSTRAINT review_items_id_project_unique UNIQUE (review_id, project_id)
);

COMMENT ON TABLE review_items IS
    'EPI-004 / §17.19.1, minimum schema only. Shared foundation with UX-005 -- UX-005 additionally '
    'requires ReviewQueue depth and human-review Capability availability, which do not exist yet, '
    'so this does NOT discharge it.';

COMMENT ON COLUMN review_items.subject_id IS
    'For AUTHORITY_CONFLICT and CONFLICT this is a conflict_id, enforced by trigger rather than a '
    'foreign key: §17.19.1 allows several subject types and no single FK can express a reference '
    'whose target depends on subject_type.';

CREATE INDEX IF NOT EXISTS review_items_queue_idx
    ON review_items (project_id, status, created_at, review_id);

-- ---------------------------------------------------------------------------------------------
-- A conflict review must name a conflict, in the same project
-- ---------------------------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION review_items_conflict_subject_exists()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.subject_type NOT IN ('CONFLICT', 'AUTHORITY_CONFLICT') THEN
        RETURN NEW;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM conflicts
         WHERE conflict_id = NEW.subject_id
           AND project_id  = NEW.project_id
    ) THEN
        RAISE EXCEPTION
            'review_items: % reviews % %, which is not a conflict in %. §17.19.3 makes '
            'ReviewItem(AUTHORITY_CONFLICT).subject_id a conflict_id, and a review pointing at '
            'nothing would sit in the queue forever describing a block nobody can find -- or '
            'point at another project''s conflict, which is why this is scoped on both',
            NEW.review_id, NEW.subject_type, NEW.subject_id, NEW.project_id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS review_items_conflict_subject_exists ON review_items;
CREATE TRIGGER review_items_conflict_subject_exists
    BEFORE INSERT OR UPDATE ON review_items
    FOR EACH ROW EXECUTE FUNCTION review_items_conflict_subject_exists();

-- ---------------------------------------------------------------------------------------------
-- The conflict's back-reference becomes a checked, project-scoped one
-- ---------------------------------------------------------------------------------------------
--
-- `011a` left `conflicts.review_id` unchecked and said so in its column comment, because the
-- table did not exist. It exists now, so the reference is real -- and composite, so a conflict
-- cannot be escalated to another project's review.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM conflicts WHERE review_id IS NOT NULL) THEN
        RAISE EXCEPTION
            'refusing to add the review foreign key: this database already holds conflicts with '
            'a review_id set, from when the column was unchecked. There is no correct value to '
            'reconcile them against -- inventing review rows would manufacture the audit trail '
            'this constraint exists to require. Re-create the database from empty instead';
    END IF;
END;
$$;

ALTER TABLE conflicts
    DROP CONSTRAINT IF EXISTS conflicts_review_in_project;
ALTER TABLE conflicts
    ADD CONSTRAINT conflicts_review_in_project
    FOREIGN KEY (review_id, project_id)
    REFERENCES review_items (review_id, project_id);

COMMENT ON COLUMN conflicts.review_id IS
    'The §17.19.1 ReviewItem this conflict was escalated to. Composite foreign key since 011b, so '
    'a cross-project escalation is unrepresentable.';

-- ---------------------------------------------------------------------------------------------
-- Escalation is one statement
-- ---------------------------------------------------------------------------------------------
--
-- The conflict and its review are one fact: a conflict escalated with no review is a block nobody
-- is working on, and a review whose conflict was never linked is a task that cannot clear the
-- block it exists for. The lesson 010b cost -- a span's status and its cost refs written
-- separately, and permanently divisible -- applies here for the same reason, and is worse here
-- because neither row can be deleted afterwards.

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
) RETURNS VOID AS $$
DECLARE
    v_updated INTEGER;
BEGIN
    INSERT INTO review_items (
        review_id, project_id, subject_type, subject_id, stakes, reason, trace_id,
        created_at, required_authority, episode_id, estimated_human_minutes
    ) VALUES (
        p_review_id, p_project_id, 'AUTHORITY_CONFLICT', p_conflict_id, p_stakes, p_reason,
        p_trace_id, p_created_at, p_required_authority, p_episode_id,
        COALESCE(p_estimated_human_minutes, 0)
    );

    -- The conflict must still be unresolved. Escalating a closed conflict would queue human work
    -- to lift a block that is already gone, and the reviewer would have no way to tell.
    UPDATE conflicts
       SET review_id = p_review_id,
           resolution_status = 'UNDER_REVIEW'
     WHERE conflict_id = p_conflict_id
       AND project_id  = p_project_id
       AND resolution_status IN ('OPEN', 'UNDER_REVIEW');

    GET DIAGNOSTICS v_updated = ROW_COUNT;
    IF v_updated = 0 THEN
        RAISE EXCEPTION
            'authority_conflict_escalate: conflict % in % is absent or already closed. Queueing a '
            'review for a lifted block gives a human a task with nothing behind it',
            p_conflict_id, p_project_id;
    END IF;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION authority_conflict_escalate(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ, TEXT, TEXT, INTEGER
) IS
    'EPI-004: create the ReviewItem for an AUTHORITY_CONFLICT and link it in one statement. The '
    'conflict moves to UNDER_REVIEW, which still blocks -- only its resolution event lifts it.';
