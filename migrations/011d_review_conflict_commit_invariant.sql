-- 011d — the `v3.3-a14` cross-table invariant moves to the COMMIT boundary
--
-- Forward-only. `011a`, `011b` and `011c` are applied and are not touched.
--
-- WHAT `011c` GOT RIGHT, AND WHAT IT MISSED. `011c` made `review_resolve_and_close_conflict` the
-- supported path and made `conflict_close` consult the linked review. Both are correct. But every
-- guard it added sits *inside a function*, and a function is something a writer can decline to
-- call. The P12 audit found both halves of `v3.3-a14`'s atomicity clause still reachable by raw
-- SQL:
--
--   P0-A  terminal ReviewItem + unresolved Conflict
--         `review_items_terminal_needs_a_decision` checks that a terminal review *has* a
--         `decision_ref`. It never looks at the conflict. So:
--             INSERT INTO review_resolutions (...valid...);
--             UPDATE review_items SET status='APPROVED', decision_ref='<resolution>' WHERE ...;
--         committed, with the linked conflict still OPEN / UNDER_REVIEW.
--
--   P0-B  outstanding ReviewItem + closed Conflict
--         `conflict_close` refuses while the review is outstanding, but `conflicts_only_close`
--         validates closure fields and immutability only. A direct UPDATE of `conflicts` skips
--         the function entirely and commits a closed conflict behind a QUEUED review.
--
-- §17.19.1 as amended forbids *both* states. A guard that holds for callers who go through the
-- function holds for callers who go through the function -- the same sentence `011a` opens with,
-- and the fifth time this project has had to write it down.
--
-- WHY A DEFERRED CONSTRAINT TRIGGER AND NOT A CHECK, AN FK, OR A BEFORE TRIGGER. The invariant
-- spans three tables, so no CHECK can see it and no foreign key can express it. A BEFORE trigger
-- cannot enforce it either, and this is the part worth being precise about: the one *valid*
-- operation necessarily passes through a forbidden intermediate state. Inside
-- `review_resolve_and_close_conflict` the review is terminalized before its conflict is closed, so
-- between those two statements the row pair reads exactly like P0-A. A trigger that fired per
-- statement would refuse the only correct way to do this.
--
-- The obligation is about what survives COMMIT, not about what any individual statement leaves
-- behind. `CREATE CONSTRAINT TRIGGER ... DEFERRABLE INITIALLY DEFERRED` says that and nothing
-- more: intermediate half-states inside one transaction are permitted, and a transaction that
-- still holds one when it tries to commit does not commit.
--
-- WHAT "LINKED" MEANS HERE, STATED BECAUSE THE ALTERNATIVE IS DEFENSIBLE AND IS NOT WHAT THE SPEC
-- SAYS. A pair is linked when `conflicts.review_id` names the review. That is the relation §8.2.1
-- creates ("link Conflict.review_id to that ReviewItem"), the one `v3.3-a14` means by "linked
-- Conflict", the one `conflict_close` consults, and the only one that is a checked, project-scoped,
-- write-once foreign key. §17.19.3's `ReviewItem.subject_id = conflict_id` is the other direction
-- of the same fact for the supported path, but it is not the gating relation: `subject_id` is
-- deliberately not a foreign key (`011b`), several reviews may name one conflict as subject after a
-- raw-SQL insert, and treating that as gating would let a stray queued row deadlock a conflict its
-- real reviewer had already resolved. Exactly one review gates a conflict, and `review_id` is it.
--
-- WHAT IS STILL NOT IN SQL, UNCHANGED FROM `011c`. No belief semantics. The database does not
-- evaluate a `TransitionPolicy`, does not decide whether a conflict should block, and does not
-- judge whether a human's answer was correct. Everything below is structural: that the records
-- referenced exist, belong to each other, belong to one project, and cannot come apart across a
-- commit (`v3.3-a13`).

-- ---------------------------------------------------------------------------------------------
-- 1. Refuse to enforce this over a database that already holds a forbidden pair
-- ---------------------------------------------------------------------------------------------
--
-- Same shape as `011b`'s guard before it added the review foreign key, and for the same reason:
-- a constraint added over data that violates it is a constraint that silently means less than it
-- says. There is no correct value to reconcile such a row against -- inventing a resolution would
-- manufacture the audit trail this migration exists to require -- so the migration stops and the
-- operator decides. The RAISE aborts the whole file, so nothing below is created either.

DO $$
DECLARE
    v_offending INTEGER;
BEGIN
    SELECT count(*) INTO v_offending
      FROM conflicts c
      JOIN review_items r
        ON r.review_id = c.review_id AND r.project_id = c.project_id
     WHERE (r.status IN ('QUEUED', 'ASSIGNED')
            AND c.resolution_status NOT IN ('OPEN', 'UNDER_REVIEW'))
        OR (r.status NOT IN ('QUEUED', 'ASSIGNED')
            AND c.resolution_status IN ('OPEN', 'UNDER_REVIEW'));

    IF v_offending > 0 THEN
        RAISE EXCEPTION
            'refusing to enforce the v3.3-a14 cross-table invariant: this database already holds '
            '% review/conflict pairs in a state §17.19.1 forbids, written before the constraint '
            'existed. Adding the triggers now would leave those rows permanently unreadable by '
            'their own rule while reporting the invariant as enforced. Re-create the database from '
            'empty, or adjudicate each pair by hand first',
            v_offending;
    END IF;
END;
$$;

-- ---------------------------------------------------------------------------------------------
-- 2. The invariant, as one function
-- ---------------------------------------------------------------------------------------------
--
-- Keyed on the review rather than the pair, because the review is the side that carries the
-- resolution: half of the obligation ("a terminal review names its own resolution, and the
-- outcome agrees with the status") is true or false without any conflict being involved, and the
-- other half is checked against every conflict the review gates.
--
-- IT RE-READS EVERY ROW. Nothing here trusts a trigger's NEW. A deferred trigger's NEW is the row
-- as it was when the event was queued, and by commit time the same transaction may have written it
-- again -- so a check against NEW would validate a value the database is not about to keep. The
-- identity arrives from the trigger; every value is read back at commit.

CREATE OR REPLACE FUNCTION review_conflict_invariant_assert(
    p_project_id TEXT,
    p_review_id  TEXT
) RETURNS VOID AS $$
DECLARE
    v_review      review_items;
    v_resolution  review_resolutions;
    v_conflict    conflicts;
    v_outstanding BOOLEAN;
BEGIN
    SELECT * INTO v_review
      FROM review_items
     WHERE review_id = p_review_id AND project_id = p_project_id;

    -- No review under this identity at commit. Nothing to check: a conflict still pointing at it
    -- is refused by `conflicts_review_in_project`, which owns that case and reports it better.
    IF NOT FOUND THEN
        RETURN;
    END IF;

    v_outstanding := v_review.status IN ('QUEUED', 'ASSIGNED');

    IF v_outstanding THEN
        -- Also enforced per-statement by `011c`'s BEFORE trigger. Repeated at the commit boundary
        -- because that trigger fires on `review_items` alone: nothing stops a transaction from
        -- reaching this state by writing the other two tables.
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

        -- Looked up on `resolution_id` alone, deliberately. Scoping the lookup by project would
        -- make the project check below vacuous -- a cross-project resolution would simply not be
        -- found, and the error would say "does not exist" about a row that does.
        SELECT * INTO v_resolution
          FROM review_resolutions
         WHERE resolution_id = v_review.decision_ref;

        IF NOT FOUND THEN
            RAISE EXCEPTION
                'review % is % and names resolution %, which does not exist. A terminal review '
                'whose decision_ref resolves to nothing is unauditable',
                v_review.review_id, v_review.status, v_review.decision_ref;
        END IF;

        -- THE RESOLUTION MUST BE *THIS* REVIEW'S. `review_items_decision_ref_in_project` requires
        -- only that the row exist in the same project, and `review_resolutions_one_per_review`
        -- says each resolution belongs to exactly one review -- so pointing at another review's
        -- resolution is representable, and it is another human's decision being reused as this
        -- one's justification.
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

        -- THE OUTCOME IS THE STATUS. `review_resolutions.outcome` and `review_items.status` are
        -- two recordings of one human decision, and a reader consulting either must get the same
        -- answer. A review APPROVED behind a resolution that says REJECTED is a record which
        -- contradicts itself, and whichever field a caller happened to read would decide a belief.
        IF v_resolution.outcome IS DISTINCT FROM v_review.status THEN
            RAISE EXCEPTION
                'review % is % but its resolution % records outcome %. These are two accounts of '
                'the same decision and must agree; whichever a reader consulted first would settle '
                'the belief',
                v_review.review_id, v_review.status,
                v_resolution.resolution_id, v_resolution.outcome;
        END IF;
    END IF;

    -- NOT SCOPED BY PROJECT IN THE WHERE, for the same reason the resolution lookup is not: a
    -- cross-project link must be *reported*, not filtered out of view. `conflicts_review_in_project`
    -- makes it unrepresentable; if that constraint were ever dropped this would still catch it.
    --
    -- A LOOP RATHER THAN A SINGLE ROW. `conflicts.review_id` is not unique, so two conflicts can
    -- name one review -- and `review_resolve_and_close_conflict`'s `SELECT ... INTO v_conflict_id`
    -- would then close whichever the planner returned first and leave the other open behind a
    -- terminal review. That is P0-A by another route, and checking every linked conflict closes it.
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
            -- THE OUTSTANDING REVIEW INVARIANT. This is P0-B: `conflict_close` refuses this, and
            -- a direct UPDATE of `conflicts` never reached `conflict_close`.
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
            -- THE OTHER HALF-STATE. This is P0-A: the review answered and the block never lifted,
            -- so the reviewer's work is done and the hypothesis is still gated, with nothing in
            -- the record saying why.
            IF v_conflict.resolution_status IN ('OPEN', 'UNDER_REVIEW') THEN
                RAISE EXCEPTION
                    'review % is % but conflict % is still %. v3.3-a14 forbids a terminal review '
                    'beside an unresolved conflict: the human has decided and the block is still '
                    'in place, which no later reader can distinguish from nobody having looked',
                    v_review.review_id, v_review.status,
                    v_conflict.conflict_id, v_conflict.resolution_status;
            END IF;

            -- CLOSURE TRACEABILITY, AT THE COMMIT BOUNDARY. `conflict_close` already refuses a
            -- substituted event; this is the same rule for a writer who did not call it.
            IF v_conflict.resolution_event_id IS DISTINCT FROM v_resolution.belief_revision_event_id
            THEN
                RAISE EXCEPTION
                    'conflict % closed as % against event %, but review %''s resolution % produced '
                    'event %. An event that merely belongs to the same project is not proof that '
                    'this review resolved',
                    v_conflict.conflict_id, v_conflict.resolution_status,
                    v_conflict.resolution_event_id, v_review.review_id,
                    v_resolution.resolution_id, v_resolution.belief_revision_event_id;
            END IF;
        END IF;
    END LOOP;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION review_conflict_invariant_assert(TEXT, TEXT) IS
    'v3.3-a14: the complete ReviewItem <-> Conflict cross-table invariant, evaluated against '
    'committed values. Called from deferred constraint triggers on all three tables, so no writer '
    'can reach a forbidden half-state by declining to call review_resolve_and_close_conflict().';

-- ---------------------------------------------------------------------------------------------
-- 3. Three deferred constraint triggers, one per table that can break the pair
-- ---------------------------------------------------------------------------------------------
--
-- All three are needed, because each table can reach a forbidden state while the other two are
-- untouched: `review_items` carries the status and `decision_ref` (P0-A), `conflicts` carries the
-- closure (P0-B), and `review_resolutions` carries the outcome and the event the closure must cite
-- -- editing a resolution after the fact rewrites what the human decided.
--
-- `CREATE CONSTRAINT TRIGGER` has no `OR REPLACE`, hence the DROP. Re-running this migration is
-- therefore idempotent, which the migration runner does not require but the empty-database rebuild
-- exercises.

CREATE OR REPLACE FUNCTION review_items_cross_table_invariant()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM review_conflict_invariant_assert(NEW.project_id, NEW.review_id);
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS review_items_cross_table_invariant ON review_items;
CREATE CONSTRAINT TRIGGER review_items_cross_table_invariant
    AFTER INSERT OR UPDATE ON review_items
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION review_items_cross_table_invariant();

CREATE OR REPLACE FUNCTION conflicts_cross_table_invariant()
RETURNS TRIGGER AS $$
BEGIN
    -- `NEW.review_id` IS SAFE HERE, WHICH IS NOT OBVIOUS AND IS WORTH THE PARAGRAPH. A deferred
    -- trigger's NEW is a snapshot, so reading a link out of it is normally a way to validate a
    -- value the database is not about to keep. The draft of this function re-read `review_id` from
    -- the table to avoid that -- and the mutation run showed the re-read made no observable
    -- difference, because the only case it protects against is unreachable:
    --
    --   * `conflicts_only_close` makes `review_id` writable exactly once, from NULL. So any
    --     statement that establishes the link is itself an UPDATE carrying the new value in NEW,
    --     and queues its own event.
    --   * The remaining gap would be "close an unlinked conflict, then link it later in the same
    --     transaction", where the closing statement's NEW.review_id is NULL. `conflicts_only_close`
    --     refuses the second half: once `resolution_status` is terminal the row admits no further
    --     UPDATE at all.
    --
    -- So a statement whose NEW.review_id is NULL cannot be the statement that made a linked pair
    -- inconsistent. Keeping the re-read would have meant shipping a branch no test can reach, which
    -- is the defect the P12 mutation run caught in the blank-rationale validator.
    --
    -- The re-read that *is* load-bearing lives in `review_conflict_invariant_assert`: it reads every
    -- row it judges, which is what makes deferring the check to COMMIT correct.
    IF NEW.review_id IS NOT NULL THEN
        PERFORM review_conflict_invariant_assert(NEW.project_id, NEW.review_id);
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS conflicts_cross_table_invariant ON conflicts;
CREATE CONSTRAINT TRIGGER conflicts_cross_table_invariant
    AFTER INSERT OR UPDATE ON conflicts
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION conflicts_cross_table_invariant();

CREATE OR REPLACE FUNCTION review_resolutions_cross_table_invariant()
RETURNS TRIGGER AS $$
BEGIN
    -- DELETE is covered because a resolution is the record a terminal review cites. Removing it
    -- leaves `decision_ref` pointing at nothing -- which the deferred foreign key also refuses,
    -- but the message here names the review and says why the row mattered.
    IF TG_OP = 'DELETE' THEN
        PERFORM review_conflict_invariant_assert(OLD.project_id, OLD.review_id);
        RETURN NULL;
    END IF;

    PERFORM review_conflict_invariant_assert(NEW.project_id, NEW.review_id);

    -- Re-pointing a resolution at a different review leaves the review it abandoned terminal with
    -- nothing behind it, so both sides are re-checked.
    IF TG_OP = 'UPDATE' AND (
           OLD.review_id IS DISTINCT FROM NEW.review_id
        OR OLD.project_id IS DISTINCT FROM NEW.project_id
    ) THEN
        PERFORM review_conflict_invariant_assert(OLD.project_id, OLD.review_id);
    END IF;

    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS review_resolutions_cross_table_invariant ON review_resolutions;
CREATE CONSTRAINT TRIGGER review_resolutions_cross_table_invariant
    AFTER INSERT OR UPDATE OR DELETE ON review_resolutions
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION review_resolutions_cross_table_invariant();
