-- 002b_prior_art_search.sql
--
-- M3 / SRC-003 / §17.20. PriorArtSearchRecord, and the novelty status that must cite one.
--
-- NUMBERING. Extends Appendix A's `002` (artifacts and source works): a prior-art search is a
-- record of which SOURCE WORKS a novelty claim was checked against, and `002`'s source-work
-- identity is what `deduped_work_count` counts. Applied after `006b` because a search belongs to a
-- ResearchEpisode, and after `003d` because it may cite the inference that planned its queries.
--
-- SRC-003 IN THE DATABASE, because a novelty status is exactly the kind of row a script writes:
--
--   * a novelty assessment names its search -- NOT NULL, foreign key;
--   * the search it names records sources, queries, a DATE RANGE and limitations. §17.20 marks
--     `date_range?` optional and SRC-003 lists it among what a cited record must hold, so the
--     column stays nullable and a NULL-dated search cannot be cited;
--   * a GLOBAL scope requires the search to have covered every trust class the assessment
--     declares as required for global novelty, the declared set must be non-empty and entirely
--     external, and the search must have searched at least one external source at all. So an
--     internal-only search cannot yield a GLOBAL status by any write path -- "internal novelty MUST
--     NOT 被當作 global novelty 呈現".
--
-- There is no `NOVEL` status: §7.1's 沒搜到不能宣告全球唯一. The strongest answer is
-- NOVELTY_CANDIDATE, meaning "no prior art found within this coverage".

CREATE TABLE IF NOT EXISTS prior_art_search_records (
    search_id                   TEXT PRIMARY KEY,
    project_id                  TEXT NOT NULL REFERENCES projects (project_id),
    episode_id                  TEXT NOT NULL REFERENCES research_episodes (episode_id),
    intent                      TEXT NOT NULL CHECK (btrim(intent) <> ''),
    -- [{"provider_id": ..., "trust_classes": [...]}, ...]
    sources                     JSONB NOT NULL,
    queries                     TEXT[] NOT NULL,
    -- {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"} or NULL (§17.20's `date_range?`)
    date_range                  JSONB,
    retrieved_at                TIMESTAMPTZ NOT NULL,
    source_policy_version       TEXT NOT NULL CHECK (btrim(source_policy_version) <> ''),
    result_count                INTEGER NOT NULL CHECK (result_count >= 0),
    deduped_work_count          INTEGER NOT NULL CHECK (deduped_work_count >= 0),
    limitations                 TEXT[] NOT NULL,
    coverage_notes              TEXT NOT NULL,
    external_source_record_ids  TEXT[] NOT NULL DEFAULT '{}',
    inference_provenance_id     TEXT REFERENCES inference_provenance (inference_id),

    CONSTRAINT prior_art_has_sources CHECK (
        jsonb_typeof(sources) = 'array' AND jsonb_array_length(sources) >= 1
    ),
    CONSTRAINT prior_art_has_queries CHECK (cardinality(queries) >= 1),
    CONSTRAINT prior_art_has_limitations CHECK (cardinality(limitations) >= 1),
    CONSTRAINT prior_art_dedup_cannot_add CHECK (deduped_work_count <= result_count),
    -- One id per DISTINCT work: `result_count` is raw hits across queries, and the names are the
    -- deduplicated works, so it is the deduplicated count they must match.
    CONSTRAINT prior_art_counts_what_it_names
        CHECK (cardinality(external_source_record_ids) = deduped_work_count)
);

CREATE INDEX IF NOT EXISTS prior_art_episode_idx ON prior_art_search_records (episode_id);

CREATE TABLE IF NOT EXISTS novelty_assessments (
    assessment_id              TEXT PRIMARY KEY,
    project_id                 TEXT NOT NULL REFERENCES projects (project_id),
    episode_id                 TEXT NOT NULL REFERENCES research_episodes (episode_id),
    subject_id                 TEXT NOT NULL CHECK (btrim(subject_id) <> ''),
    search_id                  TEXT NOT NULL REFERENCES prior_art_search_records (search_id),
    -- `novelty_status`, not `status`: this is a claim about prior art, and a column called
    -- `status` beside the belief tables is the name T-EPI-005's structural probe reserves for
    -- lifecycles it has examined. Nothing about belief is representable in it.
    novelty_status             TEXT NOT NULL CHECK (
                                   novelty_status IN ('KNOWN', 'PARTIALLY_NOVEL', 'NOVELTY_CANDIDATE')),
    scope                      TEXT NOT NULL CHECK (scope IN ('INTERNAL', 'GLOBAL')),
    -- The trust classes the governing NOVELTY_AUDIT policy requires before a GLOBAL scope. Copied
    -- from the policy at assessment time, so the check below judges the row against the rule it
    -- was made under and a later policy cannot re-judge it.
    global_coverage_required   TEXT[] NOT NULL DEFAULT '{}',
    prior_art_matrix           JSONB NOT NULL DEFAULT '[]'::jsonb,
    inference_provenance_id    TEXT REFERENCES inference_provenance (inference_id),
    created_at                 TIMESTAMPTZ NOT NULL
);

CREATE FUNCTION novelty_rests_on_its_coverage() RETURNS TRIGGER AS $$
DECLARE
    v_search    prior_art_search_records%ROWTYPE;
    v_covered   TEXT[];
    v_internal  CONSTANT TEXT[] := ARRAY['INTERNAL_RUN', 'INTERNAL_MEASUREMENT', 'EXPERT_HEURISTIC'];
BEGIN
    SELECT * INTO v_search FROM prior_art_search_records WHERE search_id = NEW.search_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION
            'novelty assessment % cites search %, which does not exist. SRC-003: a novelty status '
            'with no coverage record MUST be refused', NEW.assessment_id, NEW.search_id;
    END IF;
    IF v_search.project_id <> NEW.project_id THEN
        RAISE EXCEPTION 'novelty assessment % in % cites search % of project %',
            NEW.assessment_id, NEW.project_id, NEW.search_id, v_search.project_id;
    END IF;
    IF v_search.date_range IS NULL THEN
        RAISE EXCEPTION
            'novelty assessment % cites search %, which records no date range. SRC-003: a novelty '
            'status must cite sources, queries, date range and limitations; a claim with no date '
            'bound is a claim about all time', NEW.assessment_id, NEW.search_id;
    END IF;

    SELECT array_agg(DISTINCT cls) INTO v_covered
      FROM jsonb_array_elements(v_search.sources) AS src,
           jsonb_array_elements_text(src -> 'trust_classes') AS cls;

    IF NEW.scope = 'GLOBAL' THEN
        IF cardinality(NEW.global_coverage_required) = 0
           OR NEW.global_coverage_required && v_internal THEN
            RAISE EXCEPTION
                'novelty assessment % claims GLOBAL scope under a coverage requirement % that is '
                'empty or includes internal classes; global novelty is judged against external '
                'prior art', NEW.assessment_id, NEW.global_coverage_required;
        END IF;
        IF v_covered <@ v_internal THEN
            RAISE EXCEPTION
                'novelty assessment % claims GLOBAL scope from search %, which searched only '
                'internal sources %. SRC-003: internal novelty MUST NOT be presented as global '
                'novelty', NEW.assessment_id, NEW.search_id, v_covered;
        END IF;
        IF NOT (v_covered @> NEW.global_coverage_required) THEN
            RAISE EXCEPTION
                'novelty assessment % claims GLOBAL scope, but search % covered % and the policy '
                'requires %; 沒搜到不能宣告全球唯一 -- an uncovered class is not an absent one',
                NEW.assessment_id, NEW.search_id, v_covered, NEW.global_coverage_required;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER novelty_rests_on_its_coverage_trg
    BEFORE INSERT ON novelty_assessments
    FOR EACH ROW EXECUTE FUNCTION novelty_rests_on_its_coverage();

CREATE TRIGGER prior_art_search_episode_in_project_trg BEFORE INSERT ON prior_art_search_records
    FOR EACH ROW EXECUTE FUNCTION m3_episode_is_in_project();
CREATE TRIGGER novelty_assessments_episode_in_project_trg BEFORE INSERT ON novelty_assessments
    FOR EACH ROW EXECUTE FUNCTION m3_episode_is_in_project();

CREATE FUNCTION prior_art_rows_are_immutable() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION '% is append-only: a search and the status it supported are records of what '
        'was checked, and editing either re-judges a novelty claim silently (SRC-003)',
        TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER prior_art_search_records_immutable_trg
    BEFORE UPDATE OR DELETE ON prior_art_search_records
    FOR EACH ROW EXECUTE FUNCTION prior_art_rows_are_immutable();
CREATE TRIGGER novelty_assessments_immutable_trg
    BEFORE UPDATE OR DELETE ON novelty_assessments
    FOR EACH ROW EXECUTE FUNCTION prior_art_rows_are_immutable();
