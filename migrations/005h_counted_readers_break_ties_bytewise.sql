-- 005h_counted_readers_break_ties_bytewise.sql
--
-- G0 round 6, residual C-1 (docs/audit/g0-boundary-round6-2026-11-24/REPORT.md).
--
-- THE GAP. Three SQL readers on the confirmation path pick ONE row by a text ordering whose ties
-- are broken by the database's collation, while Python orders the same strings by code point:
--   * `cwg_bound_class` -- the declared class a hypothesis binds to (`ORDER BY set_ref, class_id
--     LIMIT 1`): it decides a hypothesis's member key, so which rivals compete and whether a
--     support is DOMAIN-warranted;
--   * `confirmation_rule_breaches` -- the candidate's own declaration whose refuting outcomes are
--     checked (`ORDER BY set_ref LIMIT 1`);
--   * `failure_analyses_confirmation_holds_the_rule` -- the class name a confirmed cause must be
--     recorded as (`ORDER BY set_ref LIMIT 1`).
-- On a database whose default collation is not C (an ICU or glibc locale), two active
-- declaration sets whose refs differ only in case or punctuation sort differently from Python
-- (e.g. 'B-set' before 'a-set' byte-wise, after it in en-US), so SQL could bind another class than
-- the product. The suite's databases are C.UTF-8, which is why nothing failed.
--
-- THE FIX. The same bodies, with the tie-breaks byte-wise (COLLATE "C"), as `005f` did for the
-- belief readers. Nothing else differs from `012p`.

CREATE OR REPLACE FUNCTION cwg_bound_class(p_project TEXT, p_hypothesis TEXT)
RETURNS TABLE (set_ref TEXT, class_id TEXT) AS $$
    SELECT d.set_ref, d.class_id
      FROM hypotheses h
      JOIN diagnostic_declarations d ON d.active AND d.mechanism = h.mechanism
     WHERE h.project_id = p_project AND h.hypothesis_id = p_hypothesis
       AND cwg_binds(p_project, p_hypothesis, d.observable_ref, d.outcome_space_id,
                     d.outcome_space_version, d.supports_outcome, d.refutes_outcomes)
     ORDER BY d.set_ref COLLATE "C", d.class_id COLLATE "C"
     LIMIT 1
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION confirmation_rule_breaches(
    p_project   TEXT,
    p_episode   TEXT,
    p_candidate TEXT
) RETURNS TEXT[] AS $$
DECLARE
    v_set        TEXT;
    v_breaches   TEXT[] := '{}';
    v_members    TEXT[];
    v_states     JSONB := '{}'::jsonb;
    v_keys       JSONB := '{}'::jsonb;
    v_h          TEXT;
    v_supported  TEXT[];
    v_family     TEXT[];
    v_rivals     TEXT[];
    v_excluded   TEXT[];
    v_refuted    TEXT[];
    v_candidate  TEXT;
    v_key        TEXT;
    v_support    TEXT[];
    v_observed   TEXT[];
    v_found      TEXT[];
    v_own        RECORD;
    v_row        RECORD;
BEGIN
    SELECT h.hypothesis_set_id INTO v_set FROM hypotheses h
     WHERE h.project_id = p_project AND h.hypothesis_id = p_candidate;
    IF NOT FOUND OR NOT EXISTS (
        SELECT 1 FROM hypothesis_sets s
         WHERE s.set_id = v_set AND s.project_id = p_project AND s.episode_id = p_episode
    ) THEN
        RETURN ARRAY[format('%s is not a member of a hypothesis set of %s', p_candidate,
                            p_episode)];
    END IF;
    SELECT array_agg(h.hypothesis_id ORDER BY h.hypothesis_id COLLATE "C") INTO v_members
      FROM hypotheses h WHERE h.hypothesis_set_id = v_set AND h.project_id = p_project;
    FOREACH v_h IN ARRAY v_members LOOP
        v_states := v_states || jsonb_build_object(v_h, cwg_state(p_project, v_h));
        v_keys := v_keys || jsonb_build_object(v_h, cwg_member_key(p_project, v_h));
    END LOOP;

    SELECT coalesce(array_agg(m ORDER BY m COLLATE "C"), '{}') INTO v_supported
      FROM unnest(v_members) m WHERE v_states ->> m = 'SUPPORTED';
    IF cardinality(v_supported) = 0 THEN
        RETURN ARRAY[format('no member of %s is SUPPORTED', v_set)];
    END IF;
    IF (SELECT count(DISTINCT v_keys ->> s) FROM unnest(v_supported) s) > 1 THEN
        RETURN ARRAY[format('%s are SUPPORTED as different mechanisms: competing support',
                            array_to_string(v_supported, ', '))];
    END IF;
    v_candidate := v_supported[1];
    v_key := v_keys ->> v_candidate;
    IF p_candidate <> v_candidate THEN
        v_breaches := v_breaches || format('the rule''s candidate is %s, not %s', v_candidate,
                                           p_candidate);
    END IF;
    SELECT array_agg(m ORDER BY m) INTO v_family
      FROM unnest(v_members) m WHERE v_keys ->> m = v_key;
    SELECT coalesce(array_agg(m ORDER BY m), '{}') INTO v_rivals
      FROM unnest(v_members) m WHERE NOT (m = ANY (v_family));

    SELECT coalesce(array_agg(m ORDER BY m), '{}') INTO v_refuted
      FROM unnest(v_members) m
     WHERE EXISTS (SELECT 1 FROM cwg_evidence(p_project, m) e
                    WHERE e.relation_type = 'CONTRADICTS' AND e.warrant IN ('DOMAIN', 'REVIEW'));
    SELECT coalesce(array_agg(m ORDER BY m), '{}') INTO v_excluded
      FROM unnest(v_refuted) m WHERE v_states ->> m = 'CONTRADICTED';

    -- The candidate's own class holds a warranted refutation.
    SELECT array_agg(m ORDER BY m) INTO v_found FROM unnest(v_family) m WHERE m = ANY (v_refuted);
    IF cardinality(v_found) > 0 THEN
        v_breaches := v_breaches || format('%s -- the candidate''s own class -- hold a warranted '
                                           'refutation', array_to_string(v_found, ', '));
    END IF;

    -- Warranted support, and the observations it rests on.
    SELECT coalesce(array_agg(DISTINCT e.relation_id), '{}'),
           coalesce(array_agg(DISTINCT e.from_entity_id), '{}')
      INTO v_support, v_observed
      FROM unnest(v_family) m
     CROSS JOIN LATERAL cwg_evidence(p_project, m) e
     WHERE v_states ->> m = 'SUPPORTED' AND e.relation_type = 'SUPPORTS'
       AND e.warrant IN ('DOMAIN', 'REVIEW');
    IF cardinality(v_support) = 0 THEN
        v_breaches := v_breaches || format('%s is SUPPORTED on support nobody accountable '
                                           'warranted', v_candidate);
    END IF;

    -- Every outcome the episode observed: its runs' attestations, and what each admitted relation
    -- of a member records. Another declared class's signature among them, or an outcome the
    -- candidate's own class cannot produce, is evidence against a unique confirmation.
    FOR v_row IN
        WITH observed AS (
            SELECT o.observation_id, o.metric_or_event AS observable,
                   left(a.method ->> 'outcome_space',
                        length(a.method ->> 'outcome_space')
                        - strpos(reverse(a.method ->> 'outcome_space'), '@')) AS space_id,
                   right(a.method ->> 'outcome_space',
                         strpos(reverse(a.method ->> 'outcome_space'), '@') - 1) AS space_version,
                   a.method ->> 'outcome' AS outcome
              FROM attestations a
              JOIN observations o ON o.observation_id = a.observation_id
              JOIN runs r ON r.run_id = o.run_id
              JOIN jobs j ON j.job_id = r.job_id
             WHERE a.project_id = p_project AND j.episode_id = p_episode
               AND strpos(coalesce(a.method ->> 'outcome_space', ''), '@') > 0
               AND a.method ->> 'outcome' IS NOT NULL
            UNION
            SELECT r.from_entity_id, l.observable, l.space_id, l.space_version, l.outcome
              FROM unnest(v_members) m
              JOIN relation_judgments r
                ON r.project_id = p_project AND r.to_entity_id = m AND r.valid_to IS NULL
               AND r.relation_type IN ('SUPPORTS', 'CONTRADICTS', 'TESTS', 'PREDICTS')
             CROSS JOIN LATERAL cwg_observed_link(r) l
             WHERE l.outcome IS NOT NULL
        )
        SELECT DISTINCT ob.observation_id, ob.outcome, d.class_id, d.mechanism
          FROM observed ob
          JOIN diagnostic_declarations d
            ON d.active
           AND (d.observable_ref, d.outcome_space_id, d.outcome_space_version, d.supports_outcome)
               = (ob.observable, ob.space_id, ob.space_version, ob.outcome)
         WHERE 'class:' || d.class_id IS DISTINCT FROM v_key
         ORDER BY ob.observation_id, d.class_id
    LOOP
        v_breaches := v_breaches || format('%s: the observed %s is the declared signature of '
                                           '''%s'', another mechanism than %s''s', v_row.observation_id,
                                           v_row.outcome, v_row.mechanism, v_candidate);
    END LOOP;
    IF v_key LIKE 'class:%' THEN
        SELECT * INTO v_own FROM diagnostic_declarations
         WHERE active AND class_id = substr(v_key, 7)
         ORDER BY set_ref COLLATE "C" LIMIT 1;
        IF FOUND THEN
            FOR v_row IN
                WITH observed AS (
                    SELECT o.observation_id, o.metric_or_event AS observable,
                           a.method ->> 'outcome_space' AS space, a.method ->> 'outcome' AS outcome
                      FROM attestations a
                      JOIN observations o ON o.observation_id = a.observation_id
                      JOIN runs r ON r.run_id = o.run_id
                      JOIN jobs j ON j.job_id = r.job_id
                     WHERE a.project_id = p_project AND j.episode_id = p_episode
                    UNION
                    SELECT r.from_entity_id, l.observable, l.space_id || '@' || l.space_version,
                           l.outcome
                      FROM unnest(v_members) m
                      JOIN relation_judgments r
                        ON r.project_id = p_project AND r.to_entity_id = m
                       AND r.valid_to IS NULL
                       AND r.relation_type IN ('SUPPORTS', 'CONTRADICTS', 'TESTS', 'PREDICTS')
                     CROSS JOIN LATERAL cwg_observed_link(r) l
                     WHERE l.outcome IS NOT NULL
                )
                SELECT DISTINCT observation_id, outcome FROM observed
                 WHERE observable = v_own.observable_ref
                   AND space = v_own.outcome_space_id || '@' || v_own.outcome_space_version
                   AND outcome = ANY (v_own.refutes_outcomes)
                 ORDER BY observation_id, outcome
            LOOP
                v_breaches := v_breaches || format('%s: the observed %s is an outcome the declared '
                                                   'class ''%s'' cannot produce',
                                                   v_row.observation_id, v_row.outcome,
                                                   v_own.mechanism);
            END LOOP;
        END IF;
    END IF;

    -- A rival affirming the observation the support rests on, unless a warranted refutation
    -- excluded it. Invalidated affirmations count.
    SELECT array_agg(DISTINCT r.to_entity_id ORDER BY r.to_entity_id) INTO v_found
      FROM relation_judgments r
     WHERE r.project_id = p_project AND r.from_entity_id = ANY (v_observed)
       AND r.relation_type IN ('SUPPORTS', 'PREDICTS')
       AND r.to_entity_id = ANY (v_rivals) AND NOT (r.to_entity_id = ANY (v_excluded));
    IF cardinality(v_found) > 0 THEN
        v_breaches := v_breaches || format('%s affirm the observation supporting %s and nothing '
                                           'warranted excludes them', array_to_string(v_found, ', '),
                                           v_candidate);
    END IF;

    -- An unsettled relation a person's answer could turn against the conclusion.
    SELECT array_agg(e.relation_id ORDER BY e.relation_id) INTO v_found
      FROM (
          SELECT e.relation_id FROM unnest(v_rivals) m
           CROSS JOIN LATERAL cwg_evidence(p_project, m) e
           WHERE NOT (m = ANY (v_excluded)) AND e.relation_type = 'SUPPORTS'
             AND e.warrant IS NULL
          UNION
          SELECT e.relation_id FROM unnest(v_family) m
           CROSS JOIN LATERAL cwg_evidence(p_project, m) e
           WHERE e.relation_type = 'CONTRADICTS' AND e.warrant IS NULL
      ) e;
    IF cardinality(v_found) > 0 THEN
        v_breaches := v_breaches || format('a person''s answer on %s could change whether %s is '
                                           'the cause', array_to_string(v_found, ', '), v_candidate);
    END IF;

    -- A rival whose warranted support only an open blocking conflict holds back.
    SELECT array_agg(m ORDER BY m) INTO v_found
      FROM unnest(v_rivals) m
     WHERE NOT (m = ANY (v_excluded)) AND v_states ->> m IS DISTINCT FROM 'SUPPORTED'
       AND EXISTS (SELECT 1 FROM cwg_evidence(p_project, m) e
                    WHERE e.relation_type = 'SUPPORTS' AND e.warrant IN ('DOMAIN', 'REVIEW'))
       AND EXISTS (SELECT 1 FROM conflicts c
                    WHERE c.project_id = p_project AND m = ANY (c.subject_refs) AND c.blocking
                      AND c.resolution_status IN ('OPEN', 'UNDER_REVIEW'));
    IF cardinality(v_found) > 0 THEN
        v_breaches := v_breaches || format('%s hold warranted support blocked only by an open '
                                           'conflict review', array_to_string(v_found, ', '));
    END IF;
    RETURN v_breaches;
END;
$$ LANGUAGE plpgsql STABLE;

CREATE OR REPLACE FUNCTION failure_analyses_confirmation_holds_the_rule()
RETURNS TRIGGER AS $$
DECLARE
    v_breaches TEXT[];
    v_missing  TEXT[];
    v_key      TEXT;
    v_class    TEXT;
    v_ref      TEXT;
BEGIN
    IF NEW.resolution_status <> 'CONFIRMED' THEN
        RETURN NEW;
    END IF;
    v_breaches := confirmation_rule_breaches(NEW.project_id, NEW.episode_id,
                                             NEW.confirmed_root_cause);
    IF cardinality(v_breaches) > 0 THEN
        RAISE EXCEPTION
            'failure analysis % confirms %, but the confirmation rule does not hold: %',
            NEW.failure_analysis_id, NEW.confirmed_root_cause,
            array_to_string(v_breaches, '; ');
    END IF;
    SELECT coalesce(array_agg(h.hypothesis_id ORDER BY h.hypothesis_id), '{}') INTO v_missing
      FROM hypotheses h
      JOIN hypotheses c ON c.hypothesis_set_id = h.hypothesis_set_id
     WHERE c.hypothesis_id = NEW.confirmed_root_cause AND c.project_id = NEW.project_id
       AND NOT (h.hypothesis_id = ANY (NEW.candidate_causes));
    IF cardinality(v_missing) > 0 THEN
        RAISE EXCEPTION 'failure analysis % omits rivals % from its candidate causes; a '
            'confirmation is relative to every member of its set', NEW.failure_analysis_id,
            v_missing;
    END IF;
    FOREACH v_ref IN ARRAY NEW.warrant_refs LOOP
        IF NOT EXISTS (
            SELECT 1 FROM cwg_evidence(NEW.project_id, NEW.confirmed_root_cause) e
             WHERE e.relation_type = 'SUPPORTS' AND e.warrant IN ('DOMAIN', 'REVIEW')
               AND e.ref = v_ref
        ) THEN
            RAISE EXCEPTION 'failure analysis % cites %, which is not a current warrant of %''s '
                'support', NEW.failure_analysis_id, v_ref, NEW.confirmed_root_cause;
        END IF;
    END LOOP;
    v_key := cwg_member_key(NEW.project_id, NEW.confirmed_root_cause);
    IF v_key LIKE 'class:%' THEN
        SELECT mechanism INTO v_class FROM diagnostic_declarations
         WHERE active AND class_id = substr(v_key, 7) ORDER BY set_ref COLLATE "C" LIMIT 1;
        IF FOUND AND NEW.failure_class IS DISTINCT FROM v_class THEN
            RAISE EXCEPTION 'failure analysis % records % as ''%''; a member of the declared '
                'class ''%'' is recorded as that class', NEW.failure_analysis_id,
                NEW.confirmed_root_cause, NEW.failure_class, v_class;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
