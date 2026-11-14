-- 012r_relation_invalidation.sql
--
-- A relation's invalidation is final, and its author survives it.
--
-- WHY. `012o` let an invalidation write `valid_to`, `invalidation_reason` and `actor_id`, and
-- checked only that the actor changed together with an invalidation. Two consequences, both
-- probed on a disposable database (data-organization audit 2026-10-15, F-02):
--   - a later UPDATE could set `valid_to` and `invalidation_reason` back to NULL, and a withdrawn
--     relation read as current again -- with nothing recording that it had ever been withdrawn;
--   - the invalidation overwrote `actor_id` with the person who withdrew it, so who originally
--     asserted the relation was lost. The gate's separation of duties reads exactly that column:
--     the actor who ran the episode that recorded a relation does not warrant it (`012o`, `012p`).
--
-- WHAT.
--   - `actor_id` is immutable: it names who recorded the relation, for its whole life;
--   - `invalidated_by_actor_id` records who withdrew it, written once, with the invalidation;
--   - an invalidation is one-way and written once: a closed relation is never reopened, re-dated,
--     given another reason or re-attributed.
--
-- HISTORY IS NOT REWRITTEN. A relation invalidated before this migration keeps its row as it is:
-- its `actor_id` is the invalidator, as `012o` wrote it, and its `invalidated_by_actor_id` is NULL.
-- Nothing is inferred for it, and like every closed relation it can no longer change.

ALTER TABLE relation_judgments
    ADD COLUMN IF NOT EXISTS invalidated_by_actor_id TEXT REFERENCES actors (actor_id);

ALTER TABLE relation_judgments
    DROP CONSTRAINT IF EXISTS relation_judgments_invalidator_only_when_closed;
ALTER TABLE relation_judgments
    ADD CONSTRAINT relation_judgments_invalidator_only_when_closed
    CHECK (invalidated_by_actor_id IS NULL OR valid_to IS NOT NULL);

COMMENT ON COLUMN relation_judgments.invalidated_by_actor_id IS
    'Who invalidated the relation (012r). Written once, with valid_to and invalidation_reason; '
    'actor_id keeps naming who recorded it. NULL on a current relation and on relations '
    'invalidated before 012r, whose actor_id is their invalidator.';

-- `012o`'s immutability rule, restated: the content as before, the author always, and the
-- invalidation once.
CREATE OR REPLACE FUNCTION relation_judgments_content_is_immutable()
RETURNS TRIGGER AS $$
BEGIN
    IF (NEW.relation_id, NEW.project_id, NEW.from_entity_id, NEW.to_entity_id, NEW.relation_type,
        NEW.attributes, NEW.supporting_attestation_ids, NEW.condition_match_ref,
        NEW.inference_provenance_id, NEW.valid_from, NEW.created_at)
       IS DISTINCT FROM
       (OLD.relation_id, OLD.project_id, OLD.from_entity_id, OLD.to_entity_id, OLD.relation_type,
        OLD.attributes, OLD.supporting_attestation_ids, OLD.condition_match_ref,
        OLD.inference_provenance_id, OLD.valid_from, OLD.created_at) THEN
        RAISE EXCEPTION
            'relation %''s content is immutable; only an invalidation may be recorded on it',
            OLD.relation_id;
    END IF;
    IF NEW.actor_id IS DISTINCT FROM OLD.actor_id THEN
        RAISE EXCEPTION
            'relation %''s author (actor_id %) is immutable; the actor who invalidates it is '
            'recorded in invalidated_by_actor_id (012r)', OLD.relation_id, OLD.actor_id;
    END IF;
    IF OLD.valid_to IS NOT NULL THEN
        IF (NEW.valid_to, NEW.invalidation_reason, NEW.invalidated_by_actor_id)
           IS DISTINCT FROM (OLD.valid_to, OLD.invalidation_reason, OLD.invalidated_by_actor_id)
        THEN
            RAISE EXCEPTION
                'relation % was invalidated at % (%); an invalidation is final: the relation is '
                'never reopened, re-dated, given another reason or re-attributed',
                OLD.relation_id, OLD.valid_to, OLD.invalidation_reason;
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.valid_to IS NOT NULL AND NEW.invalidated_by_actor_id IS NULL THEN
        RAISE EXCEPTION
            'relation %''s invalidation names who made it (invalidated_by_actor_id)',
            OLD.relation_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- A relation is never deleted: one that no longer holds is invalidated, and the record of what was
-- once held -- and withdrawn, by whom and why -- stays. (`TRUNCATE`, which fires no row trigger, is
-- not a service's privilege: `lab-brain admin db-roles`.)
CREATE OR REPLACE FUNCTION relation_judgments_are_never_deleted()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        'relation % is never deleted; a relation that no longer holds is invalidated '
        '(valid_to, invalidation_reason, invalidated_by_actor_id)', OLD.relation_id;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS relation_judgments_no_delete ON relation_judgments;
CREATE TRIGGER relation_judgments_no_delete
    BEFORE DELETE ON relation_judgments
    FOR EACH ROW EXECUTE FUNCTION relation_judgments_are_never_deleted();
