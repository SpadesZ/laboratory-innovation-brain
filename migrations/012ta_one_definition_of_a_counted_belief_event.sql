-- 012ta_one_definition_of_a_counted_belief_event.sql
--
-- G0 trust boundaries, round 5 (docs/audit/g0-boundary-round5-2026-11-21/REPORT.md).
--
-- THE GAP. `012t` let the schema owner quarantine a belief event, or a transition policy, so the
-- row "decides nothing"; `002e` stores the external snapshots whose attestations no longer count
-- (the §6.18 selection, `external_quarantined_attestations`). Only the Python projection
-- (`BeliefEpisode.project`) read the first, and nothing read the second. Every other reader of a
-- belief history read the raw rows, so a withdrawn row still decided something, or still blocked
-- what the owner meant to release (reproduced, evidence/reproduction_before.log):
--   Q1 `cwg_state` (the SQL confirmation rule, `012p`): a quarantined promotion read SUPPORTED;
--   Q2 `011l`'s root-cause check: the same promotion counted as the cause's current state;
--   Q3 the `011z` time bound: a quarantined forged event dated a month ahead refused every honest
--      transition of its subject until that date;
--   Q4 the `011z` gate recorded a transition under a quarantined policy, which the projection then
--      skipped;
--   Q5 EPI-001 (`012n`): a quarantined admission still counted as a competing hypothesis;
--   Q6 an event triggered by an attestation of a quarantined external snapshot still counted.
-- And one of the same shape for independence:
--   Q7 the `011z` gate bounded a WORK count by its own notion of an evidence line (every current
--      relation of the subject; an attestation no stored run stands behind counted as a line),
--      while the product counts the lines of the decision's admitted relations and counts such an
--      attestation as unknown (`VerificationLoop._independence`, `core.warrant.evidence_line`).
--
-- THE RULE: ONE DEFINITION, IN SQL, READ BY BOTH SIDES.
--   * `belief_event_exclusions` names every stored event that may not count, and why:
--     OWNER_QUARANTINED (the event, or the policy it was recorded under, `012t`) or
--     QUARANTINED_TRIGGER (one of its triggering attestations is in the stored §6.18 selection).
--   * `belief_replay(project, target)` is the structural half of `core.belief.replay`: the events in
--     (occurred_at, event_id) order -- event ids compared byte-wise (COLLATE "C"), as Python
--     compares str -- skipping an excluded event and, in cascade, every event whose from_state
--     the running state no longer is (PREDECESSOR_MISSING). `belief_counted_state` is its result.
--   * Python reads the same rows: `SqlBeliefEventStore.withheld` / `trigger_quarantined` (the
--     projection's skips) and `counted_history` (what EPI-001's revision gate and the root-cause
--     trace read). The PostgreSQL suite enumerates histories and holds `belief_replay` equal to
--     `replay` (tests/e2e/test_g0_counted_history_differential_postgres.py).
--   * Every SQL reader of "the current state" or "an admitted hypothesis" reads `belief_replay`:
--     `cwg_state`, `011l`, `012o`'s warrant check, `012n`'s competing-set count; the `011z` gate's
--     time bound ignores excluded events and its policy check refuses a quarantined policy.
--   * `belief_evidence_lines(project, attestation_ids)` is the product's independence count: the
--     distinct (capability, backend, sorted inputs, parameters) of the stored runs behind the
--     attestations; an attestation with no stored run is unknown and counts nothing. The gate
--     bounds a WORK count by it over the decision's own (already checked) admitted relations.
--
-- WHAT STAYS PYTHON-ONLY, STATED. SQL cannot re-derive a decision (`TransitionPolicy.evaluate`),
-- so Python additionally refuses a whole history with an unverifiable event: Python can only
-- refuse MORE than SQL counts, never count what SQL excludes. A caller-supplied §6.18 selection
-- (`quarantined_attestation_ids`, e.g. by extractor version) is transient and Python-only; it too
-- can only skip more.
--
-- WHAT IS UNCHANGED. No row is changed or removed. Function signatures are unchanged; bodies are
-- replaced (CREATE OR REPLACE), each differing from its previous version only where marked
-- "012ta".

-- ---------------------------------------------------------------------------------------------
-- 1. The one definition
-- ---------------------------------------------------------------------------------------------

CREATE VIEW belief_event_exclusions AS
SELECT e.event_id,
       e.project_id,
       e.target_id,
       CASE WHEN EXISTS (
                SELECT 1 FROM owner_quarantines q
                 WHERE (q.subject_kind = 'BELIEF_EVENT' AND q.subject_id = e.event_id)
                    OR (q.subject_kind = 'TRANSITION_POLICY' AND q.subject_id = e.policy_id
                        AND q.subject_version = e.policy_version))
            THEN 'OWNER_QUARANTINED'
            ELSE 'QUARANTINED_TRIGGER' END AS reason
  FROM belief_revision_events e
 WHERE EXISTS (
           SELECT 1 FROM owner_quarantines q
            WHERE (q.subject_kind = 'BELIEF_EVENT' AND q.subject_id = e.event_id)
               OR (q.subject_kind = 'TRANSITION_POLICY' AND q.subject_id = e.policy_id
                   AND q.subject_version = e.policy_version))
    OR EXISTS (
           SELECT 1 FROM belief_revision_event_attestations ea
             JOIN external_quarantined_attestations x
               ON x.attestation_id = ea.attestation_id AND x.project_id = e.project_id
            WHERE ea.event_id = e.event_id);

COMMENT ON VIEW belief_event_exclusions IS
    'G0 round 5 (012ta): every stored belief event that may not count, and why -- '
    'OWNER_QUARANTINED (012t: the event or its policy) or QUARANTINED_TRIGGER (002e: a triggering '
    'attestation of a quarantined external snapshot). The one definition both the SQL readers and '
    'the Python projection read.';

CREATE FUNCTION belief_replay(p_project TEXT, p_target TEXT)
RETURNS TABLE (
    event_id    TEXT,
    occurred_at TIMESTAMPTZ,
    from_state  TEXT,
    to_state    TEXT,
    counted     BOOLEAN,
    skip_reason TEXT
) AS $$
#variable_conflict use_column
DECLARE
    v_state TEXT;
    v_row   RECORD;
BEGIN
    FOR v_row IN
        SELECT e.event_id AS id, e.occurred_at AS at, e.from_state AS f, e.to_state AS t,
               x.reason AS excluded
          FROM belief_revision_events e
          LEFT JOIN belief_event_exclusions x ON x.event_id = e.event_id
         WHERE e.project_id = p_project AND e.target_id = p_target
         ORDER BY e.occurred_at, e.event_id COLLATE "C"
    LOOP
        event_id := v_row.id;
        occurred_at := v_row.at;
        from_state := v_row.f;
        to_state := v_row.t;
        IF v_row.excluded IS NOT NULL THEN
            counted := FALSE;
            skip_reason := v_row.excluded;
        ELSIF v_row.f IS DISTINCT FROM v_state THEN
            counted := FALSE;
            skip_reason := 'PREDECESSOR_MISSING';
        ELSE
            counted := TRUE;
            skip_reason := NULL;
            v_state := v_row.t;
        END IF;
        RETURN NEXT;
    END LOOP;
END;
$$ LANGUAGE plpgsql STABLE SET search_path = pg_catalog, public;

COMMENT ON FUNCTION belief_replay(TEXT, TEXT) IS
    'G0 round 5 (012ta): the structural half of core.belief.replay over the stored history -- each '
    'event in (occurred_at, event_id COLLATE "C") order, counted or skipped (OWNER_QUARANTINED, '
    'QUARANTINED_TRIGGER, PREDECESSOR_MISSING). Held equal to Python replay by the PostgreSQL suite.';

-- The current state the replay reaches (NULL: no counted event).
CREATE FUNCTION belief_counted_state(p_project TEXT, p_target TEXT)
RETURNS TEXT AS $$
    SELECT r.to_state FROM belief_replay(p_project, p_target) r
     WHERE r.counted
     ORDER BY r.occurred_at DESC, r.event_id COLLATE "C" DESC
     LIMIT 1
$$ LANGUAGE sql STABLE SET search_path = pg_catalog, public;

-- The product's independence count (`core.warrant.evidence_line` per run,
-- `VerificationLoop._independence` over them): distinct executions behind the attestations, an
-- attestation with no stored run counting nothing.
CREATE FUNCTION belief_evidence_lines(p_project TEXT, p_attestation_ids TEXT[])
RETURNS INTEGER AS $$
    SELECT count(DISTINCT ROW(u.capability_id, u.backend_id,
                              ARRAY(SELECT i FROM unnest(u.input_artifacts) i
                                     ORDER BY i COLLATE "C"),
                              u.input_parameters)::TEXT)::INTEGER
      FROM (SELECT DISTINCT unnest(p_attestation_ids) AS id) ref
      JOIN attestations a ON a.attestation_id = ref.id AND a.project_id = p_project
      LEFT JOIN observations o
        ON o.observation_id = a.observation_id AND o.project_id = p_project
      JOIN runs u ON u.run_id = coalesce(a.run_id, o.run_id)
$$ LANGUAGE sql STABLE SET search_path = pg_catalog, public;

-- ---------------------------------------------------------------------------------------------
-- 2. The SQL confirmation rule's state (`012p`)
-- ---------------------------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION cwg_state(p_project TEXT, p_hypothesis TEXT)
RETURNS TEXT AS $$
    -- 012ta: the counted state, not the latest raw event.
    SELECT belief_counted_state(p_project, p_hypothesis)
$$ LANGUAGE sql STABLE;

-- ---------------------------------------------------------------------------------------------
-- 3. The write gate (`011z`): (a) a quarantined policy, (g) the product's count, (h) the bound
-- ---------------------------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION belief_write_time_problem(
    p_project_id TEXT, p_target_id TEXT, p_at TIMESTAMPTZ, p_event BOOLEAN
) RETURNS TEXT AS $$
DECLARE
    v_latest TIMESTAMPTZ;
BEGIN
    IF p_at IS NULL OR p_at > clock_timestamp() + belief_write_skew() THEN
        RETURN format('it is dated %s, after the database clock (%s) by more than %s: a record is '
                      'not written in its own future', p_at, clock_timestamp(), belief_write_skew());
    END IF;
    IF p_event THEN
        -- 012ta: an excluded event counts nowhere, wherever it sorts; it bounds nothing.
        SELECT max(e.occurred_at) INTO v_latest FROM belief_revision_events e
         WHERE e.project_id = p_project_id AND e.target_id = p_target_id
           AND NOT EXISTS (SELECT 1 FROM belief_event_exclusions x WHERE x.event_id = e.event_id);
        IF v_latest IS NOT NULL AND p_at < v_latest THEN
            RETURN format('it is dated %s, before %s''s latest recorded event (%s): a new event '
                          'does not reorder the history it follows', p_at, p_target_id, v_latest);
        END IF;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE SET search_path = pg_catalog, public;

CREATE OR REPLACE FUNCTION belief_policy_problem(
    p_policy_id TEXT, p_version TEXT, p_admission BOOLEAN
) RETURNS TEXT AS $$
DECLARE
    v_admission BOOLEAN;
BEGIN
    SELECT is_admission INTO v_admission FROM transition_policies
     WHERE policy_id = p_policy_id AND version = p_version;
    IF NOT FOUND THEN
        RETURN format('%s@%s is not a registered policy', p_policy_id, p_version);
    END IF;
    IF v_admission IS DISTINCT FROM p_admission THEN
        RETURN format('%s@%s is %s admission policy', p_policy_id, p_version,
                      CASE WHEN v_admission THEN 'an' ELSE 'no' END);
    END IF;
    IF EXISTS (SELECT 1 FROM transition_policies
                WHERE supersedes = p_policy_id || '@' || p_version) THEN
        RETURN format('%s@%s is superseded; a new record is written under its successor',
                      p_policy_id, p_version);
    END IF;
    -- 012ta: every event under a quarantined policy is skipped; nothing new is recorded under it.
    IF EXISTS (SELECT 1 FROM owner_quarantines q
                WHERE q.subject_kind = 'TRANSITION_POLICY' AND q.subject_id = p_policy_id
                  AND q.subject_version = p_version) THEN
        RETURN format('%s@%s is quarantined by the owner (012t); nothing recorded under it counts',
                      p_policy_id, p_version);
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE SET search_path = pg_catalog, public;

CREATE OR REPLACE FUNCTION belief_snapshot_problem(
    p_project_id TEXT, p_subject_id TEXT, p_snapshot JSONB
) RETURNS TEXT AS $$
DECLARE
    v_view      JSONB := p_snapshot -> 'hypothesis';
    v_relation  JSONB;
    v_match     JSONB;
    v_bad       TEXT;
    v_claimed   TEXT[];
    v_held      TEXT[];
    v_count     INTEGER;
    v_lines     INTEGER;
BEGIN
    IF v_view IS NULL OR v_view ->> 'project_id' IS DISTINCT FROM p_project_id
       OR v_view ->> 'hypothesis_id' IS DISTINCT FROM p_subject_id THEN
        RETURN format('its view is of %s in %s, not of %s in %s', v_view ->> 'hypothesis_id',
                      v_view ->> 'project_id', p_subject_id, p_project_id);
    END IF;

    -- (c) relations: stored, current, of this subject, same content.
    FOR v_relation IN
        SELECT r FROM jsonb_array_elements(coalesce(p_snapshot -> 'admitted_relations', '[]')) r
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM relation_judgments s
             WHERE s.relation_id = v_relation ->> 'relation_id'
               AND s.project_id = p_project_id
               AND s.to_entity_id = p_subject_id
               AND s.valid_to IS NULL
               AND v_relation ->> 'project_id' = p_project_id
               AND v_relation ->> 'to_entity_id' = p_subject_id
               AND s.from_entity_id = v_relation ->> 'from_entity_id'
               AND s.relation_type = v_relation ->> 'relation_type'
               AND s.attributes = coalesce(v_relation -> 'attributes', '{}'::jsonb)
               AND s.supporting_attestation_ids = ARRAY(
                       SELECT jsonb_array_elements_text(
                           coalesce(v_relation -> 'supporting_attestation_ids', '[]')))
               AND s.condition_match_ref IS NOT DISTINCT FROM v_relation ->> 'condition_match_ref'
        ) THEN
            RETURN format('relation %s is not the current relation stored for %s',
                          v_relation ->> 'relation_id', p_subject_id);
        END IF;
    END LOOP;

    -- (d) condition matches.
    FOR v_match IN
        SELECT m FROM jsonb_array_elements(coalesce(p_snapshot -> 'condition_matches', '[]')) m
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM condition_matches c
             WHERE c.condition_match_id = v_match ->> 'condition_match_id'
               AND c.state = v_match ->> 'state'
               AND c.tolerance_policy_version = v_match ->> 'tolerance_policy_version'
               AND coalesce(c.matched_fields, '{}') = ARRAY(
                       SELECT jsonb_array_elements_text(
                           coalesce(v_match -> 'matched_fields', '[]')))
               AND coalesce(c.unknowns, '{}') = ARRAY(
                       SELECT jsonb_array_elements_text(coalesce(v_match -> 'unknowns', '[]')))
        ) THEN
            RETURN format('condition match %s is not the match stored (%s in the decision)',
                          v_match ->> 'condition_match_id', v_match ->> 'state');
        END IF;
    END LOOP;

    -- (e) authority classes, recomputed from the stored attestations.
    v_claimed := ARRAY(
        SELECT DISTINCT x FROM jsonb_array_elements_text(
            coalesce(v_view -> 'admitted_authority_classes', '[]')) x ORDER BY 1);
    v_held := ARRAY(
        SELECT DISTINCT a.authority_class
          FROM jsonb_array_elements(coalesce(p_snapshot -> 'admitted_relations', '[]')) r
          CROSS JOIN LATERAL jsonb_array_elements_text(
              coalesce(r -> 'supporting_attestation_ids', '[]')) ref
          JOIN attestations a ON a.attestation_id = ref AND a.project_id = p_project_id
         WHERE a.authority_class IS NOT NULL
         ORDER BY 1);
    IF v_claimed IS DISTINCT FROM v_held THEN
        RETURN format('it states authority classes %s; the stored attestations behind its '
                      'relations give %s', v_claimed, v_held);
    END IF;

    -- (f) conflicts: exactly the currently unresolved ones (`SqlConflictStore.
    -- unresolved_for_subject`, `UNRESOLVED_CONFLICT_STATUSES`).
    SELECT string_agg(k, ', ' ORDER BY k) INTO v_bad FROM (
        (SELECT format('%s/%s/%s/%s', c ->> 'conflict_id', c ->> 'conflict_type',
                       c ->> 'blocking', c ->> 'resolution_status') AS k
           FROM jsonb_array_elements(coalesce(v_view -> 'conflicts', '[]')) c
         EXCEPT
         SELECT format('%s/%s/%s/%s', conflict_id, conflict_type, blocking::text, resolution_status)
           FROM conflicts
          WHERE project_id = p_project_id AND p_subject_id = ANY (subject_refs)
            AND resolution_status IN ('OPEN', 'UNDER_REVIEW'))
        UNION ALL
        (SELECT format('%s/%s/%s/%s', conflict_id, conflict_type, blocking::text,
                       resolution_status)
           FROM conflicts
          WHERE project_id = p_project_id AND p_subject_id = ANY (subject_refs)
            AND resolution_status IN ('OPEN', 'UNDER_REVIEW')
         EXCEPT
         SELECT format('%s/%s/%s/%s', c ->> 'conflict_id', c ->> 'conflict_type',
                       c ->> 'blocking', c ->> 'resolution_status')
           FROM jsonb_array_elements(coalesce(v_view -> 'conflicts', '[]')) c)
    ) d;
    IF v_bad IS NOT NULL THEN
        RETURN format('its conflicts are not %s''s currently unresolved conflicts (differing: %s)',
                      p_subject_id, v_bad);
    END IF;

    -- (g) a WORK independence count is bounded by the product's own count (012ta): the distinct
    -- executions behind the attestations of the decision's admitted relations -- which (c) has
    -- just held to the stored, current relations -- an attestation no stored run stands behind
    -- counting nothing (`belief_evidence_lines`, `VerificationLoop._independence`).
    v_count := coalesce((p_snapshot -> 'independence_summary' ->> 'independent_count')::INTEGER, 0);
    IF v_count > 0 THEN
        IF coalesce(p_snapshot -> 'independence_summary' ->> 'basis', 'WORK') <> 'WORK' THEN
            RETURN format('it counts %s independent attestations under basis %s, which nothing '
                          'here can check', v_count,
                          p_snapshot -> 'independence_summary' ->> 'basis');
        END IF;
        v_lines := belief_evidence_lines(p_project_id, ARRAY(
            SELECT ref
              FROM jsonb_array_elements(coalesce(p_snapshot -> 'admitted_relations', '[]')) r
             CROSS JOIN LATERAL jsonb_array_elements_text(
                 coalesce(r -> 'supporting_attestation_ids', '[]')) ref));
        IF v_count > v_lines THEN
            RETURN format('it counts %s independent attestations; the stored runs behind its '
                          'admitted relations make %s distinct evidence line(s) (an attestation '
                          'with no stored run is unknown and counts none)', v_count, v_lines);
        END IF;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE SET search_path = pg_catalog, public;

-- ---------------------------------------------------------------------------------------------
-- 4. The root-cause checks (`011l`, `012o`) and EPI-001's competing set (`012n`)
-- ---------------------------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION failure_analyses_trace_to_execution()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE
    v_cause           TEXT;
    v_event           belief_revision_events%ROWTYPE;
    v_evidence        TEXT;
    v_att             attestations%ROWTYPE;
    v_run_id          TEXT;
    v_run             runs%ROWTYPE;
    v_missing         TEXT[];
BEGIN
    FOREACH v_cause IN ARRAY NEW.candidate_causes LOOP
        IF NOT EXISTS (
            SELECT 1 FROM hypotheses h
             WHERE h.project_id = NEW.project_id AND h.hypothesis_id = v_cause
        ) THEN
            RAISE EXCEPTION
                'failure analysis % lists candidate cause %, which is not a hypothesis admitted in '
                'project % (§8, EPI-001)', NEW.failure_analysis_id, v_cause, NEW.project_id;
        END IF;
    END LOOP;

    IF NEW.resolution_status <> 'CONFIRMED' THEN
        RETURN NEW;
    END IF;

    -- 012ta: the cause's counted state -- the last event `belief_replay` counts -- not the latest
    -- raw event, which may be one the owner quarantined.
    SELECT e.* INTO v_event FROM belief_revision_events e
      JOIN belief_replay(NEW.project_id, NEW.confirmed_root_cause) r ON r.event_id = e.event_id
     WHERE r.counted
     ORDER BY e.occurred_at DESC, e.event_id COLLATE "C" DESC
     LIMIT 1;
    IF NOT FOUND OR v_event.to_state <> 'SUPPORTED' THEN
        RAISE EXCEPTION
            'failure analysis % confirms %, whose current belief state is %; only a SUPPORTED '
            'hypothesis can be a confirmed root cause (EPI-002)',
            NEW.failure_analysis_id, NEW.confirmed_root_cause,
            coalesce(v_event.to_state, 'no history');
    END IF;

    FOREACH v_evidence IN ARRAY NEW.root_cause_evidence_ids LOOP
        SELECT * INTO v_att FROM attestations a
         WHERE a.attestation_id = v_evidence AND a.project_id = NEW.project_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'failure analysis % cites %, which is not an attestation of %',
                NEW.failure_analysis_id, v_evidence, NEW.project_id;
        END IF;
        IF v_att.epistemic_type = 'INFERRED' OR v_att.verification_status = 'DISPUTED' THEN
            RAISE EXCEPTION
                'failure analysis % cites % (%, %). EPI-002: LLM statement 不可作為證據 -- a '
                'model''s reading or disputed evidence cannot confirm a root cause',
                NEW.failure_analysis_id, v_evidence, v_att.epistemic_type,
                v_att.verification_status;
        END IF;
        IF NOT EXISTS (
            SELECT 1
              FROM belief_revision_event_relations er
              JOIN relation_judgments r ON r.relation_id = er.relation_id
             WHERE er.event_id = v_event.event_id
               AND r.project_id = NEW.project_id
               AND r.to_entity_id = NEW.confirmed_root_cause
               AND r.relation_type = 'SUPPORTS'
               AND r.valid_to IS NULL
               AND v_evidence = ANY (r.supporting_attestation_ids)
        ) THEN
            RAISE EXCEPTION
                'failure analysis % cites %, which supports no current SUPPORTS relation to % '
                'among the relations event % was triggered by (§17.8: support is a relation)',
                NEW.failure_analysis_id, v_evidence, NEW.confirmed_root_cause, v_event.event_id;
        END IF;

        v_run_id := v_att.run_id;
        IF v_run_id IS NULL AND v_att.observation_id IS NOT NULL THEN
            SELECT o.run_id INTO v_run_id FROM observations o
             WHERE o.observation_id = v_att.observation_id AND o.project_id = NEW.project_id;
        END IF;
        IF v_run_id IS NULL THEN
            RAISE EXCEPTION
                'failure analysis % cites %, which is the output of no execution. T-EPI-002: '
                'the chain runs Attestation or Observation -> Run -> Artifact',
                NEW.failure_analysis_id, v_evidence;
        END IF;
        SELECT * INTO v_run FROM runs WHERE run_id = v_run_id;
        IF NOT FOUND OR v_run.project_id <> NEW.project_id OR v_run.status <> 'SUCCEEDED'
           OR cardinality(v_run.output_artifacts) = 0 THEN
            RAISE EXCEPTION
                'failure analysis % cites %, whose run % is missing, of another project, not '
                'SUCCEEDED, or produced no artifact (EPI-002, EVI-009)',
                NEW.failure_analysis_id, v_evidence, v_run_id;
        END IF;
        SELECT coalesce(array_agg(a ORDER BY a), '{}') INTO v_missing
          FROM unnest(v_run.output_artifacts) a
         WHERE NOT EXISTS (SELECT 1 FROM artifacts x WHERE x.artifact_id = a);
        IF cardinality(v_missing) > 0 THEN
            RAISE EXCEPTION
                'failure analysis % cites %, whose run % names output artifacts % that do not '
                'exist; a chain that ends at bytes nobody stored is not a trace',
                NEW.failure_analysis_id, v_evidence, v_run_id, v_missing;
        END IF;
    END LOOP;
    RETURN NEW;
END;
$function$;

CREATE OR REPLACE FUNCTION failure_analyses_confirmation_is_warranted()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE
    v_ref TEXT;
BEGIN
    IF NEW.resolution_status <> 'CONFIRMED' THEN
        RETURN NEW;
    END IF;
    IF cardinality(NEW.warrant_refs) = 0 THEN
        RAISE EXCEPTION
            'failure analysis % confirms % with no diagnostic warrant. A confirmed cause rests on '
            'support an accountable source warranted, not on a declared effect alone (012o)',
            NEW.failure_analysis_id, NEW.confirmed_root_cause;
    END IF;
    -- Each reference must be one the decision that moved the cause to SUPPORTED recorded for a
    -- SUPPORTS relation -- the snapshot the read path re-checks against the declarations and the
    -- grants. A reference shaped like a warrant but recorded nowhere is not one.
    FOREACH v_ref IN ARRAY NEW.warrant_refs LOOP
        IF NOT EXISTS (
            SELECT 1
              FROM belief_revision_events e
              JOIN belief_transition_decisions d
                ON d.decision_id = e.authorization_decision_id
             CROSS JOIN LATERAL jsonb_array_elements(
                   COALESCE(d.decision_input_snapshot::jsonb -> 'hypothesis' -> 'relation_evidence',
                            '[]'::jsonb)) AS r
             WHERE e.project_id = NEW.project_id
               AND e.target_id = NEW.confirmed_root_cause
               AND e.to_state = 'SUPPORTED'
               AND r ->> 'relation_type' = 'SUPPORTS'
               AND r ->> 'warrant_ref' = v_ref
               -- 012ta: a promotion that counts, not one the owner quarantined.
               AND EXISTS (SELECT 1 FROM belief_replay(NEW.project_id, NEW.confirmed_root_cause) c
                            WHERE c.counted AND c.event_id = e.event_id)
        ) THEN
            RAISE EXCEPTION
                'failure analysis % cites warrant %, which no decision promoting % recorded for '
                'its support', NEW.failure_analysis_id, v_ref, NEW.confirmed_root_cause;
        END IF;
    END LOOP;
    RETURN NEW;
END;
$function$;

CREATE OR REPLACE FUNCTION hypothesis_revisions_meet_m3_preconditions()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
DECLARE
    v_hyp       hypotheses%ROWTYPE;
    v_set       hypothesis_sets%ROWTYPE;
    v_admitted  INTEGER;
    v_unfit     TEXT;
BEGIN
    SELECT * INTO v_hyp FROM hypotheses
     WHERE hypothesis_id = NEW.target_id AND project_id = NEW.project_id;
    IF NOT FOUND THEN
        -- Said here, before the foreign key speaks, so the refusal names the rule.
        RAISE EXCEPTION
            'event % targets hypothesis % in %, which was never admitted there. R-12 / EPI-001: a '
            'belief event names a hypothesis admitted through §8''s gate (a certificate with its '
            'predictions), in the event''s own project', NEW.event_id, NEW.target_id,
            NEW.project_id;
    END IF;
    SELECT * INTO v_set FROM hypothesis_sets WHERE set_id = v_hyp.hypothesis_set_id;

    IF NEW.from_state IS NULL THEN
        IF NOT EXISTS (
            SELECT 1 FROM predictions p
             WHERE p.hypothesis_id = NEW.target_id AND p.project_id = NEW.project_id
        ) THEN
            RAISE EXCEPTION
                'hypothesis % cannot be admitted: its certificate has no typed Prediction. §8 '
                'admits a hypothesis only with mechanism, prediction, falsifier, assumptions, '
                'confounders and minimum test; without a prediction it is an idea (EPI-001)',
                NEW.target_id;
        END IF;
        IF cardinality(v_hyp.falsifier_prediction_ids) = 0 THEN
            RAISE EXCEPTION
                'hypothesis % cannot be admitted: its certificate has no typed falsifier. A '
                'falsifier in prose cannot be adjudicated; the certificate designates at least one '
                'of its own CONTRADICTS predictions (falsifier_prediction_ids)', NEW.target_id;
        END IF;
        SELECT string_agg(f.prediction_id, ', ' ORDER BY f.prediction_id) INTO v_unfit
          FROM unnest(v_hyp.falsifier_prediction_ids) AS f (prediction_id)
         WHERE NOT EXISTS (
            SELECT 1 FROM predictions p
             WHERE p.prediction_id = f.prediction_id
               AND p.hypothesis_id = NEW.target_id AND p.project_id = NEW.project_id
               AND NOT EXISTS (
                    SELECT 1 FROM jsonb_array_elements(p.relation_effect_if_observed) e
                     WHERE e ->> 'relation_type' IS DISTINCT FROM 'CONTRADICTS'
               )
         );
        IF v_unfit IS NOT NULL THEN
            RAISE EXCEPTION
                'hypothesis % cannot be admitted: its designated falsifier % is not a CONTRADICTS '
                'prediction of its own. A falsifier is one of the hypothesis''s typed predictions, '
                'declaring only CONTRADICTS on it', NEW.target_id, v_unfit;
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.to_state = 'SUPPORTED' AND v_set.root_cause THEN
        -- 012ta: an admission counts only if `belief_replay` counts it (a quarantined one does not).
        SELECT count(DISTINCT h.hypothesis_id) INTO v_admitted
          FROM hypotheses h
         WHERE h.hypothesis_set_id = v_set.set_id AND h.project_id = v_set.project_id
           AND EXISTS (SELECT 1 FROM belief_replay(h.project_id, h.hypothesis_id) r
                        WHERE r.counted AND r.from_state IS NULL);
        IF v_admitted < 2 THEN
            RAISE EXCEPTION
                'hypothesis % cannot become SUPPORTED: its root-cause set % has % admitted '
                'hypothesis. EPI-001: 至少維護 2 個 competing hypotheses；單一看似合理原因不得直接被'
                '升級成 confirmed root cause', NEW.target_id, v_set.set_id, v_admitted;
        END IF;
    END IF;

    -- §7.6's first trigger: a MAJOR REJECT (see the header) needs an independent critique path.
    IF NEW.to_state = 'CONTRADICTED'
       AND (v_set.root_cause OR v_set.inverted_retrieval_required)
       AND NOT EXISTS (
        SELECT 1 FROM critique_reports c
         WHERE NEW.target_id = ANY (c.target_ids)
           AND c.project_id = NEW.project_id
           AND cardinality(c.differs_in) >= 1
           AND c.created_at <= NEW.occurred_at
    ) THEN
        RAISE EXCEPTION
            'hypothesis % cannot be REJECTED (-> CONTRADICTED): no independent CritiqueReport '
            'targets it, and removing a rival from root-cause set % (stakes %) is a major REJECT. '
            '§7.6: 重大 REJECT 必須經 independent critique path (SRC-002)',
            NEW.target_id, v_set.set_id, v_set.stakes;
    END IF;

    IF v_set.inverted_retrieval_required AND NOT EXISTS (
        SELECT 1 FROM critique_reports c
         WHERE NEW.target_id = ANY (c.target_ids)
           AND c.project_id = NEW.project_id
           AND c.inverted_bundle_id IS NOT NULL
           AND cardinality(c.differs_in) >= 1
           AND c.created_at <= NEW.occurred_at
    ) THEN
        RAISE EXCEPTION
            'hypothesis % cannot enter BELIEF_REVISION: set % was debated at stakes % under %@%, '
            'which requires the Critic''s inverted retrieval, and no independent CritiqueReport '
            'with an inverted bundle targets it (SRC-002, §7.2)',
            NEW.target_id, v_set.set_id, v_set.stakes, v_set.source_policy_id,
            v_set.source_policy_version;
    END IF;
    RETURN NEW;
END;
$function$;
