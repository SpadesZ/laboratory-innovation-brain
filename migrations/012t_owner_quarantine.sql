-- 012t_owner_quarantine.sql
--
-- G0 trust boundaries, T-3 and T-2(d) (docs/audit/g0-boundary-round4-2026-11-11/REPORT.md).
--
-- THE GAP. Three kinds of row are append-only for every role and can stop the product for good:
--   * a diagnostic declaration set registered before `011y` that the code does not declare: the
--     composition root's closed-set check (`SqlDeclarationSetStore.ensure`) refuses every
--     research run, and the SQL confirmation rule reads it;
--   * a transition policy registered before `011x` that the code does not declare: the product
--     projection refuses the whole history of every subject with an event under it
--     (UNDECLARED_POLICY);
--   * one forged decision and event (written while the services' role held row writes, or past
--     the `011z` gate's reach -- SQL cannot re-derive): the projection refuses the subject's whole
--     history (NOT_REDERIVABLE).
-- Reproduced in evidence/reproduction_before.log: the owner's DELETE is refused (`012p`, `005a`),
-- so only a superuser disabling triggers could remove them -- and removing them would destroy the
-- evidence of what happened.
--
-- THE RULE. The schema owner (the operator's migrator) records a quarantine: which row, why, who
-- decided (an actor), and the database clock. Never a deletion, never an edit: the quarantined
-- row stays exactly as it was written, and so does the quarantine (append-only; no un-quarantine
-- -- a reversal is a decision this migration does not invent). Readers honour it:
--   * `diagnostic_declarations` (the view every SQL reader and `ensure()` reads) leaves a
--     quarantined set out, and a quarantined set no longer supersedes anything;
--   * the belief projection (`BeliefEpisode.project`, through `SqlBeliefEventStore.withheld`)
--     skips a quarantined event, and every event under a quarantined policy, recording each as
--     skipped (OWNER_QUARANTINED) -- the replay's own cascade then skips what depended on it.
-- Owner only, by the same test as `011s`/`011x`/`011y`: a quarantine the services could write
-- would let them hide any recorded belief change.
--
-- WHAT IS UNCHANGED. No existing row is changed or removed. The SQL confirmation rule's
-- `cwg_state` still reads raw events (T-4, unchanged).

CREATE TABLE owner_quarantines (
    quarantine_id   BIGSERIAL PRIMARY KEY,
    subject_kind    TEXT NOT NULL
                         CHECK (subject_kind IN ('TRANSITION_POLICY', 'DECLARATION_SET',
                                                 'BELIEF_EVENT')),
    subject_id      TEXT NOT NULL,
    -- The version of a policy or a declaration set; '' for an event, which has none.
    subject_version TEXT NOT NULL DEFAULT '',
    reason          TEXT NOT NULL CHECK (length(btrim(reason)) >= 10),
    actor_id        TEXT NOT NULL REFERENCES actors (actor_id),
    -- Stamped by the guard: the database clock and the login role, never a writer's values.
    quarantined_at  TIMESTAMPTZ NOT NULL,
    recorded_by     TEXT NOT NULL,
    CONSTRAINT owner_quarantines_once UNIQUE (subject_kind, subject_id, subject_version),
    CONSTRAINT owner_quarantines_event_has_no_version
        CHECK ((subject_kind = 'BELIEF_EVENT') = (subject_version = ''))
);

COMMENT ON TABLE owner_quarantines IS
    'G0 T-3/T-2 (012t): the schema owner''s record that a policy, declaration set or belief event '
    'no longer decides anything; the row it names is kept unchanged. Append-only, owner only.';

CREATE FUNCTION owner_quarantines_are_the_owners() RETURNS TRIGGER AS $$
DECLARE
    v_owner OID;
    v_found BOOLEAN;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'owner_quarantines is append-only: % refused; a quarantine is a record of '
            'a decision, and a later decision is a new row (012t)', TG_OP
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    SELECT relowner INTO v_owner FROM pg_class WHERE oid = TG_RELID;
    IF NOT pg_has_role(current_user, v_owner, 'MEMBER') THEN
        RAISE EXCEPTION
            'quarantine of % %: recorded by the schema owner (the operator''s migrator, '
            '`lab-brain admin quarantine`), not by %; a quarantine the services could write would '
            'let them hide any recorded belief change (012t)',
            NEW.subject_kind, NEW.subject_id, current_user
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF NEW.subject_kind = 'TRANSITION_POLICY' THEN
        v_found := EXISTS (SELECT 1 FROM transition_policies
                            WHERE policy_id = NEW.subject_id AND version = NEW.subject_version);
    ELSIF NEW.subject_kind = 'DECLARATION_SET' THEN
        v_found := EXISTS (SELECT 1 FROM diagnostic_declaration_sets
                            WHERE set_id = NEW.subject_id AND version = NEW.subject_version);
    ELSE
        v_found := EXISTS (SELECT 1 FROM belief_revision_events WHERE event_id = NEW.subject_id);
    END IF;
    IF NOT v_found THEN
        RAISE EXCEPTION 'quarantine: no % %@% is recorded; only a recorded row is quarantined',
            NEW.subject_kind, NEW.subject_id, NEW.subject_version;
    END IF;
    NEW.quarantined_at := clock_timestamp();
    NEW.recorded_by := session_user;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public;

CREATE TRIGGER owner_quarantines_are_the_owners
    BEFORE INSERT OR UPDATE OR DELETE ON owner_quarantines
    FOR EACH ROW EXECUTE FUNCTION owner_quarantines_are_the_owners();

-- The declarations the SQL rule and `ensure()` read: a quarantined set is not among them, and does
-- not supersede the set it named. Same columns, same order (`012p`).
CREATE OR REPLACE VIEW diagnostic_declarations AS
SELECT s.set_id,
       s.version,
       s.set_id || '@' || s.version                                   AS set_ref,
       d ->> 'class_id'                                               AS class_id,
       d ->> 'mechanism'                                              AS mechanism,
       d ->> 'statement'                                              AS statement,
       d ->> 'observable_ref'                                         AS observable_ref,
       d ->> 'outcome_space_id'                                       AS outcome_space_id,
       d ->> 'outcome_space_version'                                  AS outcome_space_version,
       d ->> 'supports_outcome'                                       AS supports_outcome,
       ARRAY(SELECT jsonb_array_elements_text(d -> 'refutes_outcomes')) AS refutes_outcomes,
       NOT EXISTS (
           SELECT 1 FROM diagnostic_declaration_sets x
            WHERE x.supersedes = s.set_id || '@' || s.version
              AND NOT EXISTS (
                  SELECT 1 FROM owner_quarantines q
                   WHERE q.subject_kind = 'DECLARATION_SET'
                     AND q.subject_id = x.set_id AND q.subject_version = x.version)
       )                                                              AS active
  FROM diagnostic_declaration_sets s
 CROSS JOIN LATERAL jsonb_array_elements(s.declarations) d
 WHERE NOT EXISTS (
     SELECT 1 FROM owner_quarantines q
      WHERE q.subject_kind = 'DECLARATION_SET'
        AND q.subject_id = s.set_id AND q.subject_version = s.version);
