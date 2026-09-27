-- 011k_verification_plans.sql
--
-- M4 / VER-001, VER-005. §9.6's SelectionPolicy and §17.14.1's VerificationPlan, durable.
--
-- A SELECTION POLICY VERSION IS IMMUTABLE. VER-005's "identical input + identical policy version
-- MUST return an identical ranked plan" can only be checked against a version that cannot change
-- underneath the plans ranked under it, so a (policy_id, version) row refuses UPDATE and DELETE.
--
-- A PLAN IS APPEND-ONLY, AND ITS CHOICE IS ITS OWN RANKING'S FIRST SUFFICIENT ACTION. VER-001 --
-- "若較便宜 evidence 已足夠，不得無理由升級到 simulator" -- is what the planner's ranking encodes, and a
-- plan whose `chosen_action_id` is not the first action in `ranked_action_ids` whose sufficiency
-- result says `sufficient` is a plan that escalated past a cheaper sufficient action without
-- saying why. `VerificationPlan`'s model refuses it; this trigger refuses it for every writer of
-- SQL, together with the structural half: the ranking is a permutation of the candidates, every
-- candidate has exactly one sufficiency result, the Pareto front is a subset of the candidates,
-- the rationale reference is the plan's own, and the recorded decision agrees with the choice
-- (ACT names one; EXISTING_EVIDENCE_DECIDES and NO_SUFFICIENT_ACTION name none, and the second
-- only when no candidate is sufficient).
--
-- Re-planning after a result is a NEW plan. The old one stays as the record of what was decided
-- with what was known then.

CREATE TABLE IF NOT EXISTS selection_policies (
    policy_id               TEXT NOT NULL CHECK (btrim(policy_id) <> ''),
    version                 TEXT NOT NULL CHECK (btrim(version) <> ''),
    pareto_dimensions       TEXT[] NOT NULL,
    lexicographic_fallback  TEXT[] NOT NULL,
    tie_break_rule          TEXT NOT NULL CHECK (tie_break_rule IN ('CAPABILITY_ID')),
    effective_from          TIMESTAMPTZ NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (policy_id, version),
    -- §9.6: after Pareto filtering candidates are rarely unique; a policy with fewer than two
    -- Pareto dimensions is not a Pareto filter, and one with no fallback cannot break the tie.
    CONSTRAINT selection_policies_filter_and_fallback CHECK (
        cardinality(pareto_dimensions) >= 2 AND cardinality(lexicographic_fallback) >= 1
    ),
    -- Only §9.4's CostVector dimensions may be ordered: no "normalized_cost" (VER-003).
    CONSTRAINT selection_policies_order_cost_dimensions CHECK (
        pareto_dimensions <@ ARRAY[
            'wall_clock_s', 'human_minutes', 'money_estimate', 'compute_units', 'token_count',
            'license_seat_s', 'earliest_available_at', 'irreversible', 'dependency_risk'
        ]::TEXT[]
        AND lexicographic_fallback <@ ARRAY[
            'wall_clock_s', 'human_minutes', 'money_estimate', 'compute_units', 'token_count',
            'license_seat_s', 'earliest_available_at', 'irreversible', 'dependency_risk'
        ]::TEXT[]
    )
);

CREATE FUNCTION selection_policies_are_immutable() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        'selection policy %@% is immutable (VER-005): a changed ordering is a new version, or '
        'the plans ranked under this one could no longer be reproduced',
        OLD.policy_id, OLD.version;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER selection_policies_are_immutable_trg
    BEFORE UPDATE OR DELETE ON selection_policies
    FOR EACH ROW EXECUTE FUNCTION selection_policies_are_immutable();

CREATE TABLE IF NOT EXISTS verification_plans (
    plan_id                   TEXT PRIMARY KEY,
    project_id                TEXT NOT NULL REFERENCES projects (project_id),
    episode_id                TEXT NOT NULL REFERENCES research_episodes (episode_id),
    candidate_action_ids      TEXT[] NOT NULL,
    ranked_action_ids         TEXT[] NOT NULL,
    sufficiency_results       JSONB NOT NULL,
    pareto_front_ids          TEXT[] NOT NULL,
    selection_policy_id       TEXT NOT NULL,
    selection_policy_version  TEXT NOT NULL,
    chosen_action_id          TEXT,
    rationale_ref             TEXT NOT NULL,
    rationale                 JSONB NOT NULL,
    created_at                TIMESTAMPTZ NOT NULL,

    FOREIGN KEY (selection_policy_id, selection_policy_version)
        REFERENCES selection_policies (policy_id, version),
    CONSTRAINT verification_plans_rationale_is_its_own CHECK (
        rationale_ref = plan_id || '#rationale'
    ),
    CONSTRAINT verification_plans_sufficiency_is_an_object CHECK (
        jsonb_typeof(sufficiency_results) = 'object'
    ),
    CONSTRAINT verification_plans_decision_is_known CHECK (
        rationale ->> 'decision' IN ('ACT', 'EXISTING_EVIDENCE_DECIDES', 'NO_SUFFICIENT_ACTION')
    )
);

CREATE INDEX IF NOT EXISTS verification_plans_episode_idx
    ON verification_plans (project_id, episode_id);

CREATE TRIGGER verification_plans_episode_in_project_trg BEFORE INSERT ON verification_plans
    FOR EACH ROW EXECUTE FUNCTION m3_episode_is_in_project();

CREATE FUNCTION verification_plans_choose_the_first_sufficient() RETURNS TRIGGER AS $$
DECLARE
    v_first_sufficient  TEXT;
    v_decision          TEXT := NEW.rationale ->> 'decision';
    v_keys              TEXT[];
BEGIN
    IF (SELECT coalesce(array_agg(x ORDER BY x), '{}') FROM unnest(NEW.ranked_action_ids) x)
       IS DISTINCT FROM
       (SELECT coalesce(array_agg(x ORDER BY x), '{}') FROM unnest(NEW.candidate_action_ids) x)
    THEN
        RAISE EXCEPTION
            'plan %: ranked_action_ids % is not a permutation of candidate_action_ids % (VER-005)',
            NEW.plan_id, NEW.ranked_action_ids, NEW.candidate_action_ids;
    END IF;

    SELECT coalesce(array_agg(k ORDER BY k), '{}') INTO v_keys
      FROM jsonb_object_keys(NEW.sufficiency_results) k;
    IF v_keys IS DISTINCT FROM
       (SELECT coalesce(array_agg(x ORDER BY x), '{}') FROM unnest(NEW.candidate_action_ids) x)
    THEN
        RAISE EXCEPTION
            'plan %: sufficiency results are keyed % but the candidates are %; every candidate '
            'has exactly one sufficiency result (§17.14.1)',
            NEW.plan_id, v_keys, NEW.candidate_action_ids;
    END IF;

    IF NOT (NEW.pareto_front_ids <@ NEW.candidate_action_ids) THEN
        RAISE EXCEPTION 'plan %: Pareto front % names a non-candidate',
            NEW.plan_id, NEW.pareto_front_ids;
    END IF;

    SELECT r.action_id INTO v_first_sufficient
      FROM unnest(NEW.ranked_action_ids) WITH ORDINALITY AS r(action_id, position)
     WHERE (NEW.sufficiency_results -> r.action_id ->> 'sufficient') = 'true'
     ORDER BY r.position
     LIMIT 1;

    IF v_decision = 'ACT' THEN
        IF NEW.chosen_action_id IS NULL
           OR NEW.chosen_action_id IS DISTINCT FROM v_first_sufficient THEN
            RAISE EXCEPTION
                'plan % chose % but the first sufficient action of its own ranking is %. '
                'VER-001: 若較便宜 evidence 已足夠，不得無理由升級 -- a plan may not pass over a '
                'cheaper sufficient action',
                NEW.plan_id, NEW.chosen_action_id, v_first_sufficient;
        END IF;
    ELSIF NEW.chosen_action_id IS NOT NULL THEN
        RAISE EXCEPTION 'plan % records decision % and still chooses %',
            NEW.plan_id, v_decision, NEW.chosen_action_id;
    ELSIF v_decision = 'NO_SUFFICIENT_ACTION' AND v_first_sufficient IS NOT NULL THEN
        RAISE EXCEPTION
            'plan % says no action is sufficient while % is sufficient; stopping is honest only '
            'when nothing could change a decision',
            NEW.plan_id, v_first_sufficient;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER verification_plans_choose_the_first_sufficient_trg
    BEFORE INSERT ON verification_plans
    FOR EACH ROW EXECUTE FUNCTION verification_plans_choose_the_first_sufficient();

CREATE FUNCTION verification_plans_are_append_only() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        'verification plan % is append-only; re-planning after a result is a new plan, and the '
        'old one stays as the record of what was decided with what was known then',
        OLD.plan_id;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER verification_plans_are_append_only_trg
    BEFORE UPDATE OR DELETE ON verification_plans
    FOR EACH ROW EXECUTE FUNCTION verification_plans_are_append_only();
