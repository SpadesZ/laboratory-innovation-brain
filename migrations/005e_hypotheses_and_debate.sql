-- 005e_hypotheses_and_debate.sql
--
-- M3 / EPI-001, SRC-002, LLM-002. The Hypothesis certificate and the debate objects roles exchange.
--
-- NUMBERING. Extends Appendix A's `005` (epistemic events): a hypothesis is what every
-- BeliefRevisionEvent is about, and `005a`'s `target_id` has had no table to resolve to since P7
-- (risk R-12). Positions and CritiqueReports live here too because they are §7's inter-role
-- epistemic objects, and splitting them across slots would put a critique in a different migration
-- from the hypotheses it critiques. Predictions are Appendix A's `011` and land in `011i`.
--
-- WHAT IS DELIBERATELY NOT HERE: a status column. §8.1 lists `status_projection`, and four lines
-- later says status is rebuilt from BeliefRevisionEvent + TransitionPolicy. A stored status is the
-- bypass T-SYS-001 requires be rejected, so there is none -- the projection is derived.
--
-- WHAT THE DATABASE CHECKS, AND WHY IT IS THE STORAGE-CHECKABLE HALF (`v3.3-a13`'s split).
--   * a certificate is complete: statement, mechanism, falsifier, >=1 assumption, >=1 confounder,
--     a minimal test, and an author (an inference or an actor) -- §8's admission fields;
--   * a hypothesis belongs to exactly one competing set, in its episode and project;
--   * a Position's inference was produced from the bundle the Position names (the provenance's
--     bundle hash equals the bundle's canonical hash) -- otherwise "different EvidenceBundle", the
--     anti-groupthink source §7.2 names, is an assertion rather than a fact;
--   * a CritiqueReport's `differs_in` EQUALS the axes derivable from the two provenance rows, and is
--     non-empty -- §7.6's independence cannot be claimed, only exhibited;
--   * an inverted bundle is a different retrieval from the primary one (different canonical hash).
-- What it does NOT check is whether an objection is RIGHT. That is scientific judgment, and the
-- only thing that settles it is evidence through `TransitionPolicy` (§7.6).
--
-- APPEND-ONLY THROUGHOUT. A certificate is revised by EVOLVING it (a new hypothesis with
-- `parent_id`), a debate object is a record of what was said, and a debate record is a measurement.

-- ---------------------------------------------------------------------------------------------
-- 1. Competing sets
-- ---------------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS hypothesis_sets (
    set_id                       TEXT PRIMARY KEY,
    project_id                   TEXT NOT NULL REFERENCES projects (project_id),
    episode_id                   TEXT NOT NULL REFERENCES research_episodes (episode_id),
    question                     TEXT NOT NULL CHECK (btrim(question) <> ''),
    research_intent              TEXT NOT NULL CHECK (btrim(research_intent) <> ''),
    stakes                       TEXT NOT NULL CHECK (btrim(stakes) <> ''),
    root_cause                   BOOLEAN NOT NULL,
    source_policy_id             TEXT NOT NULL CHECK (btrim(source_policy_id) <> ''),
    source_policy_version        TEXT NOT NULL CHECK (btrim(source_policy_version) <> ''),
    -- SRC-002, frozen at creation against the policy in force (see `HypothesisSet`).
    inverted_retrieval_required  BOOLEAN NOT NULL,
    created_at                   TIMESTAMPTZ NOT NULL,

    UNIQUE (set_id, project_id)
);

CREATE INDEX IF NOT EXISTS hypothesis_sets_episode_idx ON hypothesis_sets (episode_id);

-- One function for "this row's episode is in this row's project", used by every table below that
-- names an episode. An episode spanning projects would make SEC-002 scope depend on which end of
-- the relation a reader started from -- `006b`'s reasoning for Jobs, applied to debate objects.
CREATE FUNCTION m3_episode_is_in_project() RETURNS TRIGGER AS $$
DECLARE
    v_project TEXT;
BEGIN
    SELECT project_id INTO v_project FROM research_episodes WHERE episode_id = NEW.episode_id;
    IF v_project IS DISTINCT FROM NEW.project_id THEN
        RAISE EXCEPTION
            '% row in project % names episode % of project %; an episode does not span projects',
            TG_TABLE_NAME, NEW.project_id, NEW.episode_id, v_project;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER hypothesis_sets_episode_in_project_trg BEFORE INSERT ON hypothesis_sets
    FOR EACH ROW EXECUTE FUNCTION m3_episode_is_in_project();

-- ---------------------------------------------------------------------------------------------
-- 2. The certificate (§8.1 / §17.5)
-- ---------------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS hypotheses (
    hypothesis_id            TEXT PRIMARY KEY,
    project_id               TEXT NOT NULL REFERENCES projects (project_id),
    hypothesis_set_id        TEXT NOT NULL,
    statement                TEXT NOT NULL CHECK (btrim(statement) <> ''),
    mechanism                TEXT NOT NULL CHECK (btrim(mechanism) <> ''),
    assumptions              TEXT[] NOT NULL,
    falsifier                TEXT NOT NULL CHECK (btrim(falsifier) <> ''),
    confounders              TEXT[] NOT NULL,
    minimal_test_ref         TEXT NOT NULL CHECK (btrim(minimal_test_ref) <> ''),
    parent_id                TEXT REFERENCES hypotheses (hypothesis_id),
    created_in_episode       TEXT NOT NULL REFERENCES research_episodes (episode_id),
    inference_provenance_id  TEXT REFERENCES inference_provenance (inference_id),
    authored_by_actor_id     TEXT REFERENCES actors (actor_id),
    created_at               TIMESTAMPTZ NOT NULL,

    FOREIGN KEY (hypothesis_set_id, project_id) REFERENCES hypothesis_sets (set_id, project_id),
    -- §8: 補齊 mechanism、prediction、falsifier、assumptions、confounders 與 minimum test. The
    -- prediction half is `011i`'s, because predictions reference this row.
    CONSTRAINT hypotheses_states_its_assumptions CHECK (cardinality(assumptions) >= 1),
    CONSTRAINT hypotheses_states_its_confounders CHECK (cardinality(confounders) >= 1),
    -- P23 / LLM-001: an LLM-proposed certificate names its inference; a human-authored one names
    -- its author (P12). A certificate that names neither was written by nobody.
    CONSTRAINT hypotheses_has_an_author CHECK (
        inference_provenance_id IS NOT NULL OR authored_by_actor_id IS NOT NULL
    ),
    CONSTRAINT hypotheses_not_own_parent CHECK (parent_id IS NULL OR parent_id <> hypothesis_id)
);

CREATE INDEX IF NOT EXISTS hypotheses_set_idx ON hypotheses (hypothesis_set_id);

CREATE FUNCTION hypotheses_belong_where_they_say() RETURNS TRIGGER AS $$
DECLARE
    v_set hypothesis_sets%ROWTYPE;
    v_provenance_project TEXT;
BEGIN
    SELECT * INTO v_set FROM hypothesis_sets WHERE set_id = NEW.hypothesis_set_id;
    IF v_set.episode_id <> NEW.created_in_episode THEN
        RAISE EXCEPTION
            'hypothesis % was created in episode % but its competing set % belongs to episode %; '
            'rivals answer one question in one episode (EPI-001)',
            NEW.hypothesis_id, NEW.created_in_episode, NEW.hypothesis_set_id, v_set.episode_id;
    END IF;
    IF NEW.inference_provenance_id IS NOT NULL THEN
        SELECT project_id INTO v_provenance_project
          FROM inference_provenance WHERE inference_id = NEW.inference_provenance_id;
        IF v_provenance_project <> NEW.project_id THEN
            RAISE EXCEPTION
                'hypothesis % in % cites inference % from project %; a certificate cannot be '
                'authored by another project''s model call (SEC-002)',
                NEW.hypothesis_id, NEW.project_id, NEW.inference_provenance_id,
                v_provenance_project;
        END IF;
    END IF;
    IF NEW.parent_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM hypotheses WHERE hypothesis_id = NEW.parent_id AND project_id = NEW.project_id
    ) THEN
        RAISE EXCEPTION 'hypothesis % evolves % from another project', NEW.hypothesis_id,
            NEW.parent_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER hypotheses_belong_where_they_say_trg
    BEFORE INSERT ON hypotheses
    FOR EACH ROW EXECUTE FUNCTION hypotheses_belong_where_they_say();

-- ---------------------------------------------------------------------------------------------
-- 3. Position (§17.14.1)
-- ---------------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS positions (
    position_id              TEXT PRIMARY KEY,
    project_id               TEXT NOT NULL REFERENCES projects (project_id),
    role_id                  TEXT NOT NULL CHECK (btrim(role_id) <> ''),
    episode_id               TEXT NOT NULL REFERENCES research_episodes (episode_id),
    hypothesis_refs          TEXT[] NOT NULL DEFAULT '{}',
    mechanism_view           TEXT NOT NULL CHECK (btrim(mechanism_view) <> ''),
    supporting_relation_ids  TEXT[] NOT NULL DEFAULT '{}',
    uncertainties            TEXT[] NOT NULL DEFAULT '{}',
    proposed_predictions     JSONB NOT NULL DEFAULT '[]'::jsonb,
    confounders              TEXT[] NOT NULL DEFAULT '{}',
    bundle_id                TEXT NOT NULL REFERENCES evidence_bundles (bundle_id),
    inference_provenance_id  TEXT NOT NULL REFERENCES inference_provenance (inference_id),
    created_at               TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS positions_episode_idx ON positions (episode_id);

CREATE TRIGGER positions_episode_in_project_trg BEFORE INSERT ON positions
    FOR EACH ROW EXECUTE FUNCTION m3_episode_is_in_project();


CREATE FUNCTION positions_are_formed_from_their_bundle() RETURNS TRIGGER AS $$
DECLARE
    v_bundle_hash    TEXT;
    v_bundle_project TEXT;
    v_prov_hash      TEXT;
    v_prov_project   TEXT;
    v_missing        TEXT[];
BEGIN
    SELECT canonical_hash, project_id INTO v_bundle_hash, v_bundle_project
      FROM evidence_bundles WHERE bundle_id = NEW.bundle_id;
    SELECT evidence_bundle_hash, project_id INTO v_prov_hash, v_prov_project
      FROM inference_provenance WHERE inference_id = NEW.inference_provenance_id;
    IF v_bundle_project <> NEW.project_id OR v_prov_project <> NEW.project_id THEN
        RAISE EXCEPTION
            'position % in % names a bundle or an inference from another project (SEC-002)',
            NEW.position_id, NEW.project_id;
    END IF;
    IF v_prov_hash <> v_bundle_hash THEN
        RAISE EXCEPTION
            'position % names bundle % (hash %) but its inference % was produced from bundle hash '
            '%. §7.2''s anti-groupthink source is a DIFFERENT EvidenceBundle per position, which is '
            'only a fact if the bundle a position names is the one its model actually saw',
            NEW.position_id, NEW.bundle_id, v_bundle_hash, NEW.inference_provenance_id, v_prov_hash;
    END IF;
    SELECT array_agg(ref) INTO v_missing
      FROM unnest(NEW.hypothesis_refs) AS ref
     WHERE NOT EXISTS (
         SELECT 1 FROM hypotheses h WHERE h.hypothesis_id = ref AND h.project_id = NEW.project_id
     );
    IF v_missing IS NOT NULL THEN
        RAISE EXCEPTION 'position % references hypotheses % that do not exist in %',
            NEW.position_id, v_missing, NEW.project_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER positions_are_formed_from_their_bundle_trg
    BEFORE INSERT ON positions
    FOR EACH ROW EXECUTE FUNCTION positions_are_formed_from_their_bundle();

-- ---------------------------------------------------------------------------------------------
-- 4. CritiqueReport (§17.14.1), with §7.6's independence exhibited rather than claimed
-- ---------------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS critique_reports (
    critique_id              TEXT PRIMARY KEY,
    project_id               TEXT NOT NULL REFERENCES projects (project_id),
    episode_id               TEXT NOT NULL REFERENCES research_episodes (episode_id),
    target_ids               TEXT[] NOT NULL,
    objections               JSONB NOT NULL DEFAULT '[]'::jsonb,
    alternative_mechanisms   TEXT[] NOT NULL DEFAULT '{}',
    falsifier_challenges     JSONB NOT NULL DEFAULT '[]'::jsonb,
    blocking_conflicts       TEXT[] NOT NULL DEFAULT '{}',
    primary_bundle_id        TEXT NOT NULL REFERENCES evidence_bundles (bundle_id),
    inverted_bundle_id       TEXT REFERENCES evidence_bundles (bundle_id),
    original_inference_id    TEXT NOT NULL REFERENCES inference_provenance (inference_id),
    differs_in               TEXT[] NOT NULL,
    inference_provenance_id  TEXT NOT NULL REFERENCES inference_provenance (inference_id),
    created_at               TIMESTAMPTZ NOT NULL,

    CONSTRAINT critique_reports_names_a_target CHECK (cardinality(target_ids) >= 1),
    CONSTRAINT critique_reports_inverted_is_its_own_retrieval
        CHECK (inverted_bundle_id IS NULL OR inverted_bundle_id <> primary_bundle_id),
    CONSTRAINT critique_reports_axes_are_declared CHECK (
        differs_in <@ ARRAY['RETRIEVAL_BUNDLE', 'REASONING_POLICY', 'MODEL_ROUTE']::TEXT[]
    ),
    -- §7.6: 至少改變 retrieval bundle、reasoning policy 或 model route.
    CONSTRAINT critique_reports_is_independent CHECK (cardinality(differs_in) >= 1)
);

CREATE INDEX IF NOT EXISTS critique_reports_targets_idx ON critique_reports USING GIN (target_ids);

CREATE TRIGGER critique_reports_episode_in_project_trg BEFORE INSERT ON critique_reports
    FOR EACH ROW EXECUTE FUNCTION m3_episode_is_in_project();


CREATE FUNCTION critique_reports_exhibit_their_independence() RETURNS TRIGGER AS $$
DECLARE
    v_original  inference_provenance%ROWTYPE;
    v_critique  inference_provenance%ROWTYPE;
    v_axes      TEXT[] := ARRAY[]::TEXT[];
    v_primary   evidence_bundles%ROWTYPE;
    v_inverted  evidence_bundles%ROWTYPE;
    v_missing   TEXT[];
BEGIN
    SELECT * INTO v_original FROM inference_provenance WHERE inference_id = NEW.original_inference_id;
    SELECT * INTO v_critique FROM inference_provenance WHERE inference_id = NEW.inference_provenance_id;
    IF v_original.project_id <> NEW.project_id OR v_critique.project_id <> NEW.project_id THEN
        RAISE EXCEPTION 'critique % cites an inference from another project (SEC-002)',
            NEW.critique_id;
    END IF;
    IF NEW.original_inference_id = NEW.inference_provenance_id THEN
        RAISE EXCEPTION 'critique % names its own inference as the one it critiques',
            NEW.critique_id;
    END IF;

    -- The axes are DERIVED here from the two provenance rows, exactly as
    -- `InferenceProvenance.route_differs_from` derives them, and the row must state the same set.
    IF v_critique.evidence_bundle_hash <> v_original.evidence_bundle_hash THEN
        v_axes := array_append(v_axes, 'RETRIEVAL_BUNDLE');
    END IF;
    IF v_critique.source_policy_version IS DISTINCT FROM v_original.source_policy_version THEN
        v_axes := array_append(v_axes, 'REASONING_POLICY');
    END IF;
    IF (v_critique.model_id, v_critique.model_version, v_critique.logical_slot)
       IS DISTINCT FROM (v_original.model_id, v_original.model_version, v_original.logical_slot)
    THEN
        v_axes := array_append(v_axes, 'MODEL_ROUTE');
    END IF;
    IF NOT (NEW.differs_in @> v_axes AND v_axes @> NEW.differs_in) THEN
        RAISE EXCEPTION
            'critique % claims independence along % but its provenance differs from inference % '
            'along %. §7.6''s independence is exhibited by the two records, not asserted',
            NEW.critique_id, NEW.differs_in, NEW.original_inference_id, v_axes;
    END IF;

    SELECT * INTO v_primary FROM evidence_bundles WHERE bundle_id = NEW.primary_bundle_id;
    IF v_primary.project_id <> NEW.project_id THEN
        RAISE EXCEPTION 'critique % names a primary bundle from another project', NEW.critique_id;
    END IF;
    IF NEW.inverted_bundle_id IS NOT NULL THEN
        SELECT * INTO v_inverted FROM evidence_bundles WHERE bundle_id = NEW.inverted_bundle_id;
        IF v_inverted.project_id <> NEW.project_id THEN
            RAISE EXCEPTION 'critique % names an inverted bundle from another project',
                NEW.critique_id;
        END IF;
        IF v_inverted.canonical_hash = v_primary.canonical_hash THEN
            RAISE EXCEPTION
                'critique % presents bundle % as its inverted retrieval, but it is the same '
                'retrieval as primary bundle % (canonical hash %). §7.2: the Critic performs its '
                'OWN retrieval; a second row of the primary one is the groupthink it exists to break',
                NEW.critique_id, NEW.inverted_bundle_id, NEW.primary_bundle_id,
                v_primary.canonical_hash;
        END IF;
    END IF;

    SELECT array_agg(ref) INTO v_missing
      FROM unnest(NEW.target_ids) AS ref
     WHERE NOT EXISTS (
         SELECT 1 FROM hypotheses h WHERE h.hypothesis_id = ref AND h.project_id = NEW.project_id
     );
    IF v_missing IS NOT NULL THEN
        RAISE EXCEPTION 'critique % targets hypotheses % that do not exist in %',
            NEW.critique_id, v_missing, NEW.project_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER critique_reports_exhibit_their_independence_trg
    BEFORE INSERT ON critique_reports
    FOR EACH ROW EXECUTE FUNCTION critique_reports_exhibit_their_independence();

-- ---------------------------------------------------------------------------------------------
-- 5. Debate record (LLM-002: diversity / bundle-divergence / cost metrics are COLLECTED)
-- ---------------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS debate_records (
    debate_id                       TEXT PRIMARY KEY,
    project_id                      TEXT NOT NULL REFERENCES projects (project_id),
    episode_id                      TEXT NOT NULL REFERENCES research_episodes (episode_id),
    set_id                          TEXT NOT NULL,
    rounds                          INTEGER NOT NULL CHECK (rounds >= 1),
    max_rounds                      INTEGER NOT NULL CHECK (max_rounds >= 1),
    stop_reason                     TEXT NOT NULL CHECK (btrim(stop_reason) <> ''),
    escalation_triggers             TEXT[] NOT NULL DEFAULT '{}',
    position_ids                    TEXT[] NOT NULL DEFAULT '{}',
    critique_ids                    TEXT[] NOT NULL DEFAULT '{}',
    -- §15.4's metrics. NULL means NOT MEASURABLE (one position has no pairwise diversity), which is
    -- not the same fact as zero.
    position_diversity              NUMERIC CHECK (position_diversity BETWEEN 0 AND 1),
    critic_bundle_divergence        NUMERIC CHECK (critic_bundle_divergence BETWEEN 0 AND 1),
    critic_changed_final_set        BOOLEAN NOT NULL,
    initial_hypothesis_ids          TEXT[] NOT NULL,
    surviving_hypothesis_ids        TEXT[] NOT NULL,
    surviving_hypothesis_diversity  NUMERIC CHECK (surviving_hypothesis_diversity BETWEEN 0 AND 1),
    additional_evidence_items       INTEGER NOT NULL CHECK (additional_evidence_items >= 0),
    additional_token_count          BIGINT NOT NULL CHECK (additional_token_count >= 0),
    metric_versions                 JSONB NOT NULL,
    gate_evaluations                JSONB NOT NULL DEFAULT '[]'::jsonb,
    per_round                       JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at                      TIMESTAMPTZ NOT NULL,

    FOREIGN KEY (set_id, project_id) REFERENCES hypothesis_sets (set_id, project_id),
    -- §7.2: 簡單問題不得固定跑 8 rounds. The ceiling is a declared bound, never the target.
    CONSTRAINT debate_records_rounds_within_bound CHECK (rounds <= max_rounds)
);

CREATE TRIGGER debate_records_episode_in_project_trg BEFORE INSERT ON debate_records
    FOR EACH ROW EXECUTE FUNCTION m3_episode_is_in_project();

-- ---------------------------------------------------------------------------------------------
-- 6. Append-only
-- ---------------------------------------------------------------------------------------------

CREATE FUNCTION hypothesis_brain_rows_are_immutable() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        '% is append-only: a certificate is revised by evolving it into a new hypothesis, and a '
        'debate object or record is what was said and measured', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER hypothesis_sets_immutable_trg BEFORE UPDATE OR DELETE ON hypothesis_sets
    FOR EACH ROW EXECUTE FUNCTION hypothesis_brain_rows_are_immutable();
CREATE TRIGGER hypotheses_immutable_trg BEFORE UPDATE OR DELETE ON hypotheses
    FOR EACH ROW EXECUTE FUNCTION hypothesis_brain_rows_are_immutable();
CREATE TRIGGER positions_immutable_trg BEFORE UPDATE OR DELETE ON positions
    FOR EACH ROW EXECUTE FUNCTION hypothesis_brain_rows_are_immutable();
CREATE TRIGGER critique_reports_immutable_trg BEFORE UPDATE OR DELETE ON critique_reports
    FOR EACH ROW EXECUTE FUNCTION hypothesis_brain_rows_are_immutable();
CREATE TRIGGER debate_records_immutable_trg BEFORE UPDATE OR DELETE ON debate_records
    FOR EACH ROW EXECUTE FUNCTION hypothesis_brain_rows_are_immutable();
