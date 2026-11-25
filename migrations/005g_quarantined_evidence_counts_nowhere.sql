-- 005g_quarantined_evidence_counts_nowhere.sql
--
-- G0 round 6, Q-x (docs/audit/g0-boundary-round6-2026-11-24/REPORT.md).
--
-- THE GAP. `002e` says an attestation of a quarantined external snapshot counts nowhere: nothing
-- new may cite it, and `005f` skips an event it TRIGGERED. A relation that cited it before the
-- quarantine stayed current, and every reader kept admitting it: the product's relation reader
-- (`SqlRelationStore.admitted_for_subject`), the SQL confirmation rule (`cwg_evidence`), the
-- `011z` gate, and every promotion whose decision had COUNTED it (reproduced,
-- tests/e2e/test_g0_boundary_round6_postgres.py, evidence/reproduction_before_qx.log).
--
-- THE RULE, ROUTED THROUGH THE ONE DEFINITION (`005f`). An event is excluded as
-- QUARANTINED_TRIGGER when any attestation it rests on is in the stored §6.18 selection
-- (`external_quarantined_attestations`): one it was triggered by, or one behind a relation its
-- decision counted. Python reads the same view (`SqlBeliefEventStore.trigger_quarantined`). A
-- relation resting on such an attestation is not admitted by `cwg_evidence`, by Python's relation
-- reader (`quarantined_evidence_problem`, read by `SqlRelationStore`), nor counted by a new
-- decision (the `011z` snapshot check). The relation row is unchanged: quarantine decides what
-- counts, never what was recorded.

CREATE OR REPLACE FUNCTION quarantined_evidence_problem(p_project TEXT, p_attestation_ids TEXT[])
RETURNS TEXT AS $$
    SELECT format('%s is evidence of quarantined external snapshot %s (%s)', q.attestation_id,
                  q.snapshot_id, q.reason_code)
      FROM external_quarantined_attestations q
     WHERE q.project_id = p_project AND q.attestation_id = ANY (coalesce(p_attestation_ids, '{}'))
     ORDER BY q.attestation_id COLLATE "C"
     LIMIT 1
$$ LANGUAGE sql STABLE SET search_path = pg_catalog, public;

CREATE OR REPLACE VIEW belief_event_exclusions AS
SELECT e.event_id,
       e.project_id,
       e.target_id,
       CASE WHEN x.owner THEN 'OWNER_QUARANTINED' ELSE 'QUARANTINED_TRIGGER' END AS reason
  FROM belief_revision_events e
 CROSS JOIN LATERAL (
     SELECT EXISTS (
                SELECT 1 FROM owner_quarantines q
                 WHERE q.subject_kind = 'BELIEF_EVENT' AND q.subject_id = e.event_id
            ) OR EXISTS (
                SELECT 1 FROM owner_quarantines q
                 WHERE q.subject_kind = 'TRANSITION_POLICY' AND q.subject_id = e.policy_id
                   AND q.subject_version = e.policy_version
            ) AS owner,
            EXISTS (
                SELECT 1 FROM belief_revision_event_attestations ea
                  JOIN external_quarantined_attestations a
                    ON a.attestation_id = ea.attestation_id AND a.project_id = e.project_id
                 WHERE ea.event_id = e.event_id
            -- 005g: or an attestation behind a relation the event's decision counted.
            ) OR EXISTS (
                SELECT 1
                  FROM belief_transition_decisions d
                 CROSS JOIN LATERAL jsonb_array_elements(
                       coalesce(d.decision_input_snapshot::jsonb -> 'admitted_relations', '[]')) r
                 CROSS JOIN LATERAL jsonb_array_elements_text(
                       coalesce(r -> 'supporting_attestation_ids', '[]')) ref
                  JOIN external_quarantined_attestations a
                    ON a.attestation_id = ref AND a.project_id = e.project_id
                 WHERE d.decision_id = e.authorization_decision_id
            ) AS trigger_quarantined
 ) x
 WHERE x.owner OR x.trigger_quarantined;

COMMENT ON VIEW belief_event_exclusions IS
    'G0 round 5 (005f), round 6 (005g): every stored belief event that may not count, and why -- '
    'OWNER_QUARANTINED (012t: the event or its policy) or QUARANTINED_TRIGGER (002e: an '
    'attestation of a quarantined external snapshot that triggered it, or that stands behind a '
    'relation its decision counted). The one definition the SQL and Python readers read.';

-- `012p`'s admitted relations: 003g's measurement rule, and (005g) no relation resting on
-- quarantined external evidence.
CREATE OR REPLACE FUNCTION cwg_evidence(p_project TEXT, p_hypothesis TEXT)
RETURNS TABLE (
    relation_id TEXT, relation_type TEXT, from_entity_id TEXT,
    warrant TEXT, ref TEXT, identifies TEXT
) AS $$
    SELECT r.relation_id, r.relation_type, r.from_entity_id, w.warrant, w.ref, w.identifies
      FROM relation_judgments r
     CROSS JOIN LATERAL cwg_relation_warrant(r) w
     WHERE r.project_id = p_project AND r.to_entity_id = p_hypothesis AND r.valid_to IS NULL
       AND r.relation_type IN ('SUPPORTS', 'CONTRADICTS')
       AND (r.relation_type <> 'SUPPORTS'
            OR measurement_support_problem(r.project_id, r.supporting_attestation_ids) IS NULL)
       AND quarantined_evidence_problem(r.project_id, r.supporting_attestation_ids) IS NULL
$$ LANGUAGE sql STABLE;

-- The `011z` snapshot check: 005f's and 003g's, then (005g) no relation the snapshot counts may
-- rest on quarantined external evidence.
ALTER FUNCTION belief_snapshot_problem(TEXT, TEXT, JSONB)
    RENAME TO belief_snapshot_problem_003g;

CREATE FUNCTION belief_snapshot_problem(
    p_project_id TEXT, p_subject_id TEXT, p_snapshot JSONB
) RETURNS TEXT AS $$
DECLARE
    v_problem  TEXT := belief_snapshot_problem_003g(p_project_id, p_subject_id, p_snapshot);
    v_relation JSONB;
BEGIN
    IF v_problem IS NOT NULL THEN
        RETURN v_problem;
    END IF;
    FOR v_relation IN
        SELECT r FROM jsonb_array_elements(coalesce(p_snapshot -> 'admitted_relations', '[]')) r
    LOOP
        v_problem := quarantined_evidence_problem(p_project_id, ARRAY(
            SELECT jsonb_array_elements_text(
                coalesce(v_relation -> 'supporting_attestation_ids', '[]'))));
        IF v_problem IS NOT NULL THEN
            RETURN format('relation %s rests on quarantined evidence: %s',
                          v_relation ->> 'relation_id', v_problem);
        END IF;
    END LOOP;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE SET search_path = pg_catalog, public;
