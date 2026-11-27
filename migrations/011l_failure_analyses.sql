-- 011l_failure_analyses.sql
--
-- M4 / EPI-002, VS-SP-001. §17.6's FailureAnalysis and §17.11's CandidateHeuristic, durable.
--
--   EPI-002    confirmed root cause 必須可以 trace 回 Run/Evidence/Artifact；LLM statement 不可作為證據。
--   T-EPI-002  confirmed root cause query 必須 trace 到 Relation/Attestation or Observation → Run →
--              Artifact；只有 LLM statement 的 fixture 不得確認 root cause。
--
-- `lab_brain.core.root_cause` walks the chain before a CONFIRMED analysis is built. This trigger
-- walks it again for every writer of SQL, because a support script that INSERTs a FailureAnalysis
-- naming whatever cause it likes is exactly the writer EPI-002 is about. For a CONFIRMED row:
--
--   the cause      is a hypothesis of the analysis's project (composite foreign key, `011j`'s
--                  identity), one of the analysis's candidate causes, and currently SUPPORTED:
--                  the latest event of its history (ordered as `SqlBeliefEventStore.history`
--                  orders it) moved it there
--   every cited    evidence id is an attestation of the project that is not INFERRED (a model's
--   attestation    statement, EVI-003) and not DISPUTED, that supports a current SUPPORTS relation
--                  to the cause which that SUPPORTED event was triggered by, and that reaches a
--                  Run -- directly or through its Observation -- of the same project which
--                  SUCCEEDED with output artifacts that all exist
--
-- Every candidate cause is a hypothesis of the project. An OPEN or INCONCLUSIVE analysis cites
-- no evidence (a CHECK, as in the model).
--
-- A CANDIDATE HEURISTIC IS DERIVED FROM CONFIRMED ANALYSES AND IS NEVER A RULE. `status` can only
-- be PENDING_REVIEW (HEU-001's approval is M7's governance and would arrive as its own record, not
-- as an UPDATE here); every failure it cites is a CONFIRMED analysis of its project; every source
-- artifact exists; and source artifacts and locators are present (HEU-001: MUST 保存).
--
-- Both tables are append-only.

CREATE TABLE IF NOT EXISTS failure_analyses (
    failure_analysis_id      TEXT PRIMARY KEY,
    project_id               TEXT NOT NULL REFERENCES projects (project_id),
    episode_id               TEXT NOT NULL REFERENCES research_episodes (episode_id),
    symptom                  TEXT NOT NULL CHECK (btrim(symptom) <> ''),
    expected_behavior        TEXT NOT NULL CHECK (btrim(expected_behavior) <> ''),
    observed_behavior        TEXT NOT NULL CHECK (btrim(observed_behavior) <> ''),
    candidate_causes         TEXT[] NOT NULL CHECK (cardinality(candidate_causes) >= 1),
    confirmed_root_cause     TEXT,
    root_cause_evidence_ids  TEXT[] NOT NULL DEFAULT '{}',
    failure_class            TEXT NOT NULL CHECK (btrim(failure_class) <> ''),
    fix                      TEXT,
    prevention_rule          TEXT,
    resolution_status        TEXT NOT NULL
        CHECK (resolution_status IN ('OPEN', 'CONFIRMED', 'INCONCLUSIVE')),
    created_at               TIMESTAMPTZ NOT NULL,

    FOREIGN KEY (project_id, confirmed_root_cause)
        REFERENCES hypotheses (project_id, hypothesis_id),
    CONSTRAINT failure_analyses_confirmed_names_its_cause CHECK (
        (resolution_status = 'CONFIRMED') = (confirmed_root_cause IS NOT NULL)
    ),
    CONSTRAINT failure_analyses_cause_was_a_candidate CHECK (
        confirmed_root_cause IS NULL OR confirmed_root_cause = ANY (candidate_causes)
    ),
    CONSTRAINT failure_analyses_evidence_iff_confirmed CHECK (
        (confirmed_root_cause IS NULL) = (cardinality(root_cause_evidence_ids) = 0)
    )
);

CREATE INDEX IF NOT EXISTS failure_analyses_project_idx
    ON failure_analyses (project_id, created_at);

CREATE TRIGGER failure_analyses_episode_in_project_trg BEFORE INSERT ON failure_analyses
    FOR EACH ROW EXECUTE FUNCTION m3_episode_is_in_project();

CREATE FUNCTION failure_analyses_trace_to_execution() RETURNS TRIGGER AS $$
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

    SELECT * INTO v_event FROM belief_revision_events e
     WHERE e.project_id = NEW.project_id AND e.target_id = NEW.confirmed_root_cause
     ORDER BY e.occurred_at DESC, e.event_id DESC
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
$$ LANGUAGE plpgsql;

CREATE TRIGGER failure_analyses_trace_to_execution_trg
    BEFORE INSERT ON failure_analyses
    FOR EACH ROW EXECUTE FUNCTION failure_analyses_trace_to_execution();

CREATE TABLE IF NOT EXISTS candidate_heuristics (
    candidate_id                   TEXT PRIMARY KEY,
    project_id                     TEXT NOT NULL REFERENCES projects (project_id),
    trigger_pattern                TEXT NOT NULL CHECK (btrim(trigger_pattern) <> ''),
    suggested_checks               TEXT[] NOT NULL CHECK (cardinality(suggested_checks) >= 1),
    rationale                      TEXT NOT NULL CHECK (btrim(rationale) <> ''),
    source_artifact_ids            TEXT[] NOT NULL CHECK (cardinality(source_artifact_ids) >= 1),
    source_locators                TEXT[] NOT NULL CHECK (cardinality(source_locators) >= 1),
    source_episode_ids             TEXT[] NOT NULL CHECK (cardinality(source_episode_ids) >= 1),
    miner_model_version            TEXT NOT NULL CHECK (btrim(miner_model_version) <> ''),
    status                         TEXT NOT NULL CHECK (status = 'PENDING_REVIEW'),
    proposed_scope                 JSONB NOT NULL DEFAULT '{}'::jsonb,
    conflicts_with_existing_rules  TEXT[] NOT NULL DEFAULT '{}',
    derived_from_failures          TEXT[] NOT NULL
        CHECK (cardinality(derived_from_failures) >= 1),
    created_at                     TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS candidate_heuristics_project_idx
    ON candidate_heuristics (project_id, created_at);

CREATE FUNCTION candidate_heuristics_rest_on_confirmed_failures() RETURNS TRIGGER AS $$
DECLARE
    v_failure   TEXT;
    v_missing   TEXT[];
BEGIN
    FOREACH v_failure IN ARRAY NEW.derived_from_failures LOOP
        IF NOT EXISTS (
            SELECT 1 FROM failure_analyses f
             WHERE f.failure_analysis_id = v_failure AND f.project_id = NEW.project_id
               AND f.resolution_status = 'CONFIRMED'
        ) THEN
            RAISE EXCEPTION
                'candidate heuristic % is derived from %, which is not a CONFIRMED failure '
                'analysis of %. A heuristic generalises confirmed findings, never open ones',
                NEW.candidate_id, v_failure, NEW.project_id;
        END IF;
    END LOOP;
    SELECT coalesce(array_agg(a ORDER BY a), '{}') INTO v_missing
      FROM unnest(NEW.source_artifact_ids) a
     WHERE NOT EXISTS (SELECT 1 FROM artifacts x WHERE x.artifact_id = a);
    IF cardinality(v_missing) > 0 THEN
        RAISE EXCEPTION 'candidate heuristic % cites source artifacts % that do not exist (HEU-001)',
            NEW.candidate_id, v_missing;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER candidate_heuristics_rest_on_confirmed_failures_trg
    BEFORE INSERT ON candidate_heuristics
    FOR EACH ROW EXECUTE FUNCTION candidate_heuristics_rest_on_confirmed_failures();

CREATE FUNCTION failure_memory_is_append_only() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        '% is append-only: a re-analysis is a new analysis, and approving a candidate is a '
        'separate governed record (HEU-001), never an edit', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER failure_analyses_are_append_only_trg
    BEFORE UPDATE OR DELETE ON failure_analyses
    FOR EACH ROW EXECUTE FUNCTION failure_memory_is_append_only();

CREATE TRIGGER candidate_heuristics_are_append_only_trg
    BEFORE UPDATE OR DELETE ON candidate_heuristics
    FOR EACH ROW EXECUTE FUNCTION failure_memory_is_append_only();
