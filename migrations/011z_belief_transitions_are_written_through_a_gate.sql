-- 011z_belief_transitions_are_written_through_a_gate.sql
--
-- G0 trust boundaries, T-2 (docs/audit/g0-trust-boundaries-2026-11-08/REPORT.md §4, §7;
-- docs/audit/g0-boundary-round4-2026-11-11/REPORT.md).
--
-- THE GAP. A belief decision (`005d`) and its event (`005a`-`005d`) are written by the services'
-- role, and the projection can only re-check what a snapshot CONTAINS (`G0 R-1`,
-- `SqlRelationStore.snapshot_problem`). Reproduced through the real services' role
-- (evidence/reproduction_before.log):
--   * a snapshot that leaves out a currently unresolved conflict of its subject re-derives to
--     ALLOW -- the conflicts a decision did not see are not in it to re-check, and by the time a
--     reader looks the conflict may have been closed;
--   * an independence count no stored evidence line supports (`IndependenceSummary` is the
--     writer's own number);
--   * a writer-chosen time: a promotion dated a month ahead sorts after every honest later move,
--     so a challenge recorded today no longer applies.
--
-- THE WRITE PATH. `belief_transition_record` is the migrator's SECURITY DEFINER function (fixed
-- search_path, EXECUTE revoked from PUBLIC; `grant_database_roles` grants it to the services'
-- role). It records one decision -- and, for an ALLOW, the event it authorises, through
-- `belief_revision_event_append` in the same statement -- after checking against the database at
-- that moment:
--   (a) the policy is registered, is a transition policy and is not superseded;
--   (b) for an ALLOW, the snapshot's view is of the decision's own subject and project;
--   (c) every relation in the snapshot is the stored relation, current, of that subject;
--   (d) every condition match is the stored match (id, state, fields, unknowns, tolerance);
--   (e) the authority classes are exactly those the stored attestations behind those relations
--       give;
--   (f) the conflicts are exactly the subject's currently unresolved ones (id, type, blocking,
--       status) -- nothing left out, nothing invented;
--   (g) a WORK independence count is no larger than the number of distinct evidence lines
--       (capability, backend, input artefacts, parameters) behind the subject's current relations,
--       an attestation with no stored run counting as at most one line;
--   (h) the writer's times are not in the future of the database clock (five minutes' skew), and
--       an event is not dated before the subject's latest recorded event, so it cannot reorder
--       the history; the database clock time and the session's role are recorded beside the
--       rows in `belief_write_records`.
-- `belief_admission_record` is the same gate for a genesis (admission) event: (a) for admission
-- policies, (h), and the record.
--
-- AN AMENDMENT TO THE PROPOSED DESIGN, STATED. The design (trust-boundaries report §4) had the
-- function stamp database-clock times onto the rows. The rows' own times decide replay order and
-- the decisions' re-derivation is keyed on them, so overwriting them would change every history's
-- meaning for every caller that supplies a time (each research run's clock, every fixture). The
-- function instead bounds the supplied time to [latest recorded event, database clock + skew]
-- -- which removes the reordering -- and records the database clock beside the row.
--
-- WHAT IT CANNOT DO. SQL cannot run `TransitionPolicy.evaluate`, so a decision whose snapshot does
-- not re-derive can still be recorded here; the projection refuses it (NOT_REDERIVABLE) and the
-- owner's quarantine (`012t`) is the remedy. Nor can it judge whether a stored observation is
-- genuine (T-1). Rows written before this migration, or by raw INSERT while the services' role
-- still holds row writes on the four tables, are only checked at read time: closing the raw path
-- is the separate REVOKE in `grant_database_roles`, which needs the Owner's approval.
--
-- WHAT IS UNCHANGED. No existing row, constraint, trigger or function is altered; the read-time
-- checks stay. The 005d append function keeps its signature.

CREATE TABLE belief_write_records (
    record_id    BIGSERIAL PRIMARY KEY,
    decision_id  TEXT UNIQUE REFERENCES belief_transition_decisions (decision_id),
    event_id     TEXT UNIQUE REFERENCES belief_revision_events (event_id),
    -- The database clock when the gate recorded the row(s), never a writer's value.
    recorded_at  TIMESTAMPTZ NOT NULL,
    -- The login role that called the gate (`session_user`: inside the definer function
    -- `current_user` is the migrator).
    recorded_by  TEXT NOT NULL,
    CONSTRAINT belief_write_records_name_a_row CHECK (decision_id IS NOT NULL OR event_id IS NOT NULL)
);

COMMENT ON TABLE belief_write_records IS
    'G0 T-2 (011z): every decision and event written through belief_transition_record or '
    'belief_admission_record, with the database clock and the calling login role. Written by '
    'those functions only (the owner); append-only.';

CREATE FUNCTION belief_write_records_are_the_gates() RETURNS TRIGGER AS $$
DECLARE
    v_owner OID;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'belief_write_records is append-only: % refused (011z)', TG_OP
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    SELECT relowner INTO v_owner FROM pg_class WHERE oid = TG_RELID;
    IF NOT pg_has_role(current_user, v_owner, 'MEMBER') THEN
        RAISE EXCEPTION
            'belief_write_records: written by the gate functions only (belief_transition_record, '
            'belief_admission_record), not by % (011z)', current_user
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    NEW.recorded_at := clock_timestamp();
    NEW.recorded_by := session_user;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public;

CREATE TRIGGER belief_write_records_are_the_gates
    BEFORE INSERT OR UPDATE OR DELETE ON belief_write_records
    FOR EACH ROW EXECUTE FUNCTION belief_write_records_are_the_gates();

-- The skew a writer's clock may run ahead of the database's.
CREATE FUNCTION belief_write_skew() RETURNS INTERVAL AS $$
    SELECT INTERVAL '5 minutes'
$$ LANGUAGE sql IMMUTABLE;

-- (h) for one write.
CREATE FUNCTION belief_write_time_problem(
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
        SELECT max(occurred_at) INTO v_latest FROM belief_revision_events
         WHERE project_id = p_project_id AND target_id = p_target_id;
        IF v_latest IS NOT NULL AND p_at < v_latest THEN
            RETURN format('it is dated %s, before %s''s latest recorded event (%s): a new event '
                          'does not reorder the history it follows', p_at, p_target_id, v_latest);
        END IF;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE SET search_path = pg_catalog, public;

-- (b)-(g): why an ALLOW's snapshot is not what the database holds now, or NULL.
CREATE FUNCTION belief_snapshot_problem(
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

    -- (g) a WORK independence count is bounded by the stored evidence lines.
    v_count := coalesce((p_snapshot -> 'independence_summary' ->> 'independent_count')::INTEGER, 0);
    IF v_count > 0 THEN
        IF coalesce(p_snapshot -> 'independence_summary' ->> 'basis', 'WORK') <> 'WORK' THEN
            RETURN format('it counts %s independent attestations under basis %s, which nothing '
                          'here can check', v_count,
                          p_snapshot -> 'independence_summary' ->> 'basis');
        END IF;
        -- A line per distinct execution (capability, backend, inputs, parameters), and at most
        -- one per attestation no stored run stands behind: its execution cannot be classified, so
        -- the bound is generous there (the product's own count gives it 0, EVI-004).
        SELECT count(DISTINCT CASE WHEN u.run_id IS NULL THEN ROW('attestation', a.attestation_id)::TEXT
                                   ELSE ROW(u.capability_id, u.backend_id,
                                            ARRAY(SELECT i FROM unnest(u.input_artifacts) i
                                                   ORDER BY i),
                                            u.input_parameters)::TEXT END)
          INTO v_lines
          FROM relation_judgments r
          CROSS JOIN LATERAL unnest(r.supporting_attestation_ids) ref
          JOIN attestations a ON a.attestation_id = ref AND a.project_id = p_project_id
          LEFT JOIN observations o ON o.observation_id = a.observation_id
          LEFT JOIN runs u ON u.run_id = coalesce(a.run_id, o.run_id)
         WHERE r.project_id = p_project_id AND r.to_entity_id = p_subject_id
           AND r.valid_to IS NULL;
        IF v_count > v_lines THEN
            RETURN format('it counts %s independent attestations; the stored evidence behind '
                          '%s''s current relations has %s distinct evidence line(s)', v_count,
                          p_subject_id, v_lines);
        END IF;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE SET search_path = pg_catalog, public;

-- (a) for one policy.
CREATE FUNCTION belief_policy_problem(
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
    RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE SET search_path = pg_catalog, public;

CREATE FUNCTION belief_transition_record(
    p_decision_id              TEXT,
    p_project_id               TEXT,
    p_subject_id               TEXT,
    p_decision_type            TEXT,
    p_result                   TEXT,
    p_policy_id                TEXT,
    p_policy_version           TEXT,
    p_from_state               TEXT,
    p_to_state                 TEXT,
    p_authority_policy_id      TEXT,
    p_authority_policy_version TEXT,
    p_snapshot                 TEXT,
    p_input_hash               TEXT,
    p_evaluated                TEXT,
    p_episode_id               TEXT,
    p_actor_id                 TEXT,
    p_created_at               TIMESTAMPTZ,
    -- The event an ALLOW authorises, or NULL (a decision on its own).
    p_event_id                 TEXT,
    p_target_type              TEXT,
    p_attestation_ids          TEXT[],
    p_relation_ids             TEXT[],
    p_event_actor_id           TEXT,
    p_inference_provenance_id  TEXT,
    p_rationale_ref            TEXT,
    p_occurred_at              TIMESTAMPTZ,
    p_trace_id                 TEXT
) RETURNS TIMESTAMPTZ AS $$
DECLARE
    v_problem TEXT;
    v_now     TIMESTAMPTZ := clock_timestamp();
BEGIN
    v_problem := belief_policy_problem(p_policy_id, p_policy_version, FALSE);
    IF v_problem IS NULL THEN
        v_problem := belief_write_time_problem(p_project_id, p_subject_id, p_created_at, FALSE);
    END IF;
    IF v_problem IS NULL AND p_result = 'ALLOW' THEN
        v_problem := belief_snapshot_problem(p_project_id, p_subject_id, p_snapshot::jsonb);
    END IF;
    IF v_problem IS NULL AND p_event_id IS NOT NULL THEN
        IF p_result <> 'ALLOW' THEN
            v_problem := format('decision %s is %s; only an ALLOW authorises an event',
                                p_decision_id, p_result);
        ELSE
            v_problem := belief_write_time_problem(p_project_id, p_subject_id, p_occurred_at, TRUE);
        END IF;
    END IF;
    IF v_problem IS NOT NULL THEN
        RAISE EXCEPTION 'belief_transition_record: decision % for % refused: % (011z, G0 T-2)',
            p_decision_id, p_subject_id, v_problem
            USING ERRCODE = 'check_violation';
    END IF;

    INSERT INTO belief_transition_decisions (
        decision_id, project_id, subject_id, decision_type, result, policy_id, policy_version,
        from_state, to_state, authority_policy_id, authority_policy_version,
        decision_input_snapshot, input_hash, evaluated_decision, episode_id, actor_id, created_at
    ) VALUES (
        p_decision_id, p_project_id, p_subject_id, p_decision_type, p_result, p_policy_id,
        p_policy_version, p_from_state, p_to_state, p_authority_policy_id,
        p_authority_policy_version, p_snapshot, p_input_hash, p_evaluated, p_episode_id,
        p_actor_id, p_created_at
    );
    IF p_event_id IS NOT NULL THEN
        PERFORM belief_revision_event_append(
            p_event_id, p_project_id, p_target_type, p_subject_id, p_from_state, p_to_state,
            p_attestation_ids, p_relation_ids, p_policy_id, p_policy_version, p_event_actor_id,
            p_inference_provenance_id, p_rationale_ref, p_occurred_at, p_trace_id, p_decision_id
        );
    END IF;
    INSERT INTO belief_write_records (decision_id, event_id, recorded_at, recorded_by)
    VALUES (p_decision_id, p_event_id, v_now, session_user);
    RETURN v_now;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public;

CREATE FUNCTION belief_admission_record(
    p_event_id                TEXT,
    p_project_id              TEXT,
    p_target_type             TEXT,
    p_target_id               TEXT,
    p_to_state                TEXT,
    p_attestation_ids         TEXT[],
    p_relation_ids            TEXT[],
    p_policy_id               TEXT,
    p_policy_version          TEXT,
    p_actor_id                TEXT,
    p_inference_provenance_id TEXT,
    p_rationale_ref           TEXT,
    p_occurred_at             TIMESTAMPTZ,
    p_trace_id                TEXT
) RETURNS TIMESTAMPTZ AS $$
DECLARE
    v_problem TEXT;
    v_now     TIMESTAMPTZ := clock_timestamp();
BEGIN
    v_problem := belief_policy_problem(p_policy_id, p_policy_version, TRUE);
    IF v_problem IS NULL THEN
        v_problem := belief_write_time_problem(p_project_id, p_target_id, p_occurred_at, TRUE);
    END IF;
    IF v_problem IS NOT NULL THEN
        RAISE EXCEPTION 'belief_admission_record: event % for % refused: % (011z, G0 T-2)',
            p_event_id, p_target_id, v_problem
            USING ERRCODE = 'check_violation';
    END IF;
    PERFORM belief_revision_event_append(
        p_event_id, p_project_id, p_target_type, p_target_id, NULL, p_to_state,
        p_attestation_ids, p_relation_ids, p_policy_id, p_policy_version, p_actor_id,
        p_inference_provenance_id, p_rationale_ref, p_occurred_at, p_trace_id, NULL
    );
    INSERT INTO belief_write_records (decision_id, event_id, recorded_at, recorded_by)
    VALUES (NULL, p_event_id, v_now, session_user);
    RETURN v_now;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public;

REVOKE ALL ON FUNCTION belief_transition_record(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT,
    TIMESTAMPTZ, TEXT, TEXT, TEXT[], TEXT[], TEXT, TEXT, TEXT, TIMESTAMPTZ, TEXT
) FROM PUBLIC;
REVOKE ALL ON FUNCTION belief_admission_record(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT[], TEXT[], TEXT, TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ, TEXT
) FROM PUBLIC;
