-- 012s_project_scoped_provenance.sql
--
-- A scientific record cites only its own project's records.
--
-- WHY. Every scientific row carries a `project_id`, but the references BETWEEN rows were checked
-- only for existence, globally, or not at all. On a disposable database the data-organization
-- audit (2026-10-15, F-03) had all of these accepted:
--   - an attestation in project A citing an artifact present only in project B;
--   - a relation whose support list cites B's attestation, or one that does not exist;
--   - an evidence bundle in A with B's attestation as a member;
--   - an observation naming a run that does not exist, and one whose artifact has no occurrence
--     in its project;
-- and candidate heuristics checked their source artifacts only for existence, their source
-- episodes not at all. A relation's `inference_provenance_id` -- the record that an LLM produced
-- the judgment (AGT-010) -- is checked nowhere: the foreign key `004` defers to "M0b, with the
-- provenance table" was never added. "Which project does this result belong to?" rested on the
-- application.
--
-- WHAT. Checked for every writer, on insert -- and, where the row is mutable, on an update of the
-- reference -- each reference must resolve to a record of the SAME project:
--   observations           run_id (a run of the project), artifact_id (an occurrence in it)
--   attestations           observation_id, source_artifact_id (occurrence), run_id
--                          (its evidence_unit_id has been checked since `003c`)
--   relation_judgments     every supporting attestation, and the inference provenance
--   evidence_bundle_members the member attestation, against the bundle's project
--   candidate_heuristics   every source artifact (occurrence) and source episode
--
-- HISTORY IS NOT REWRITTEN. The rules bind new writes; rows already stored are not touched. The
-- view `provenance_scope_violations` lists any existing row that breaks them, read-only, so a
-- deployment can be checked before and after it applies this migration.

CREATE OR REPLACE FUNCTION scoped_artifact(p_project TEXT, p_artifact TEXT) RETURNS BOOLEAN AS $$
    SELECT p_artifact IS NULL OR EXISTS (
        SELECT 1 FROM artifact_occurrences o
         WHERE o.artifact_id = p_artifact AND o.project_id = p_project
    )
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION scoped_run(p_project TEXT, p_run TEXT) RETURNS BOOLEAN AS $$
    SELECT p_run IS NULL OR EXISTS (
        SELECT 1 FROM runs r WHERE r.run_id = p_run AND r.project_id = p_project
    )
$$ LANGUAGE sql STABLE;

CREATE OR REPLACE FUNCTION observations_cite_their_project() RETURNS TRIGGER AS $$
BEGIN
    IF NOT scoped_run(NEW.project_id, NEW.run_id) THEN
        RAISE EXCEPTION 'observation % names run %, which is not a run of %',
            NEW.observation_id, NEW.run_id, NEW.project_id;
    END IF;
    IF NOT scoped_artifact(NEW.project_id, NEW.artifact_id) THEN
        RAISE EXCEPTION 'observation % names artifact %, which has no occurrence in %',
            NEW.observation_id, NEW.artifact_id, NEW.project_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS observations_cite_their_project ON observations;
CREATE TRIGGER observations_cite_their_project
    BEFORE INSERT OR UPDATE OF run_id, artifact_id, project_id ON observations
    FOR EACH ROW EXECUTE FUNCTION observations_cite_their_project();

CREATE OR REPLACE FUNCTION attestations_cite_their_project() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.observation_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM observations o
         WHERE o.observation_id = NEW.observation_id AND o.project_id = NEW.project_id
    ) THEN
        RAISE EXCEPTION 'attestation % names observation %, which is not an observation of %',
            NEW.attestation_id, NEW.observation_id, NEW.project_id;
    END IF;
    IF NOT scoped_artifact(NEW.project_id, NEW.source_artifact_id) THEN
        RAISE EXCEPTION 'attestation % cites artifact %, which has no occurrence in %',
            NEW.attestation_id, NEW.source_artifact_id, NEW.project_id;
    END IF;
    IF NOT scoped_run(NEW.project_id, NEW.run_id) THEN
        RAISE EXCEPTION 'attestation % names run %, which is not a run of %',
            NEW.attestation_id, NEW.run_id, NEW.project_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS attestations_cite_their_project ON attestations;
CREATE TRIGGER attestations_cite_their_project
    BEFORE INSERT OR UPDATE OF observation_id, source_artifact_id, run_id, project_id
    ON attestations
    FOR EACH ROW EXECUTE FUNCTION attestations_cite_their_project();

CREATE OR REPLACE FUNCTION relation_judgments_cite_their_project() RETURNS TRIGGER AS $$
DECLARE
    v_missing TEXT[];
BEGIN
    SELECT coalesce(array_agg(s ORDER BY s), '{}') INTO v_missing
      FROM unnest(NEW.supporting_attestation_ids) s
     WHERE NOT EXISTS (
         SELECT 1 FROM attestations a
          WHERE a.attestation_id = s AND a.project_id = NEW.project_id
     );
    IF cardinality(v_missing) > 0 THEN
        RAISE EXCEPTION 'relation % rests on %, which are not attestations of %',
            NEW.relation_id, v_missing, NEW.project_id;
    END IF;
    IF NEW.inference_provenance_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM inference_provenance i
         WHERE i.inference_id = NEW.inference_provenance_id AND i.project_id = NEW.project_id
    ) THEN
        RAISE EXCEPTION 'relation % names inference %, which is not an inference of %',
            NEW.relation_id, NEW.inference_provenance_id, NEW.project_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS relation_judgments_cite_their_project ON relation_judgments;
CREATE TRIGGER relation_judgments_cite_their_project
    BEFORE INSERT ON relation_judgments
    FOR EACH ROW EXECUTE FUNCTION relation_judgments_cite_their_project();

CREATE OR REPLACE FUNCTION evidence_bundle_members_share_its_project() RETURNS TRIGGER AS $$
BEGIN
    -- A member or bundle that does not exist at all is the foreign keys' refusal.
    IF EXISTS (
        SELECT 1 FROM evidence_bundles b
          JOIN attestations a ON a.attestation_id = NEW.attestation_id
         WHERE b.bundle_id = NEW.bundle_id AND a.project_id <> b.project_id
    ) THEN
        RAISE EXCEPTION 'bundle % cannot hold attestation %: it is not an attestation of the '
            'bundle''s project', NEW.bundle_id, NEW.attestation_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS evidence_bundle_members_share_its_project ON evidence_bundle_members;
CREATE TRIGGER evidence_bundle_members_share_its_project
    BEFORE INSERT OR UPDATE ON evidence_bundle_members
    FOR EACH ROW EXECUTE FUNCTION evidence_bundle_members_share_its_project();

CREATE OR REPLACE FUNCTION candidate_heuristics_cite_their_project() RETURNS TRIGGER AS $$
DECLARE
    v_artifacts TEXT[];
    v_episodes  TEXT[];
BEGIN
    SELECT coalesce(array_agg(s ORDER BY s), '{}') INTO v_artifacts
      FROM unnest(NEW.source_artifact_ids) s
     WHERE NOT scoped_artifact(NEW.project_id, s);
    IF cardinality(v_artifacts) > 0 THEN
        RAISE EXCEPTION 'candidate % cites artifacts % with no occurrence in %',
            NEW.candidate_id, v_artifacts, NEW.project_id;
    END IF;
    SELECT coalesce(array_agg(s ORDER BY s), '{}') INTO v_episodes
      FROM unnest(NEW.source_episode_ids) s
     WHERE NOT EXISTS (
         SELECT 1 FROM research_episodes e WHERE e.episode_id = s AND e.project_id = NEW.project_id
     );
    IF cardinality(v_episodes) > 0 THEN
        RAISE EXCEPTION 'candidate % cites episodes % that are not episodes of %',
            NEW.candidate_id, v_episodes, NEW.project_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS candidate_heuristics_cite_their_project ON candidate_heuristics;
CREATE TRIGGER candidate_heuristics_cite_their_project
    BEFORE INSERT ON candidate_heuristics
    FOR EACH ROW EXECUTE FUNCTION candidate_heuristics_cite_their_project();

-- Read-only: every stored row that breaks a rule above, for checking a deployment's history.
CREATE OR REPLACE VIEW provenance_scope_violations AS
    SELECT 'observation' AS record_kind, o.observation_id AS record_id, o.project_id,
           'run' AS reference_kind, o.run_id AS reference
      FROM observations o WHERE NOT scoped_run(o.project_id, o.run_id)
    UNION ALL
    SELECT 'observation', o.observation_id, o.project_id, 'artifact', o.artifact_id
      FROM observations o WHERE NOT scoped_artifact(o.project_id, o.artifact_id)
    UNION ALL
    SELECT 'attestation', a.attestation_id, a.project_id, 'observation', a.observation_id
      FROM attestations a
     WHERE a.observation_id IS NOT NULL AND NOT EXISTS (
         SELECT 1 FROM observations o
          WHERE o.observation_id = a.observation_id AND o.project_id = a.project_id)
    UNION ALL
    SELECT 'attestation', a.attestation_id, a.project_id, 'artifact', a.source_artifact_id
      FROM attestations a WHERE NOT scoped_artifact(a.project_id, a.source_artifact_id)
    UNION ALL
    SELECT 'attestation', a.attestation_id, a.project_id, 'run', a.run_id
      FROM attestations a WHERE NOT scoped_run(a.project_id, a.run_id)
    UNION ALL
    SELECT 'relation', r.relation_id, r.project_id, 'supporting attestation', s
      FROM relation_judgments r, unnest(r.supporting_attestation_ids) s
     WHERE NOT EXISTS (
         SELECT 1 FROM attestations a WHERE a.attestation_id = s AND a.project_id = r.project_id)
    UNION ALL
    SELECT 'relation', r.relation_id, r.project_id, 'inference', r.inference_provenance_id
      FROM relation_judgments r
     WHERE r.inference_provenance_id IS NOT NULL AND NOT EXISTS (
         SELECT 1 FROM inference_provenance i
          WHERE i.inference_id = r.inference_provenance_id AND i.project_id = r.project_id)
    UNION ALL
    SELECT 'bundle member', m.bundle_id, b.project_id, 'attestation', m.attestation_id
      FROM evidence_bundle_members m
      JOIN evidence_bundles b ON b.bundle_id = m.bundle_id
      JOIN attestations a ON a.attestation_id = m.attestation_id
     WHERE a.project_id <> b.project_id
    UNION ALL
    SELECT 'candidate heuristic', c.candidate_id, c.project_id, 'artifact', s
      FROM candidate_heuristics c, unnest(c.source_artifact_ids) s
     WHERE NOT scoped_artifact(c.project_id, s)
    UNION ALL
    SELECT 'candidate heuristic', c.candidate_id, c.project_id, 'episode', s
      FROM candidate_heuristics c, unnest(c.source_episode_ids) s
     WHERE NOT EXISTS (
         SELECT 1 FROM research_episodes e WHERE e.episode_id = s AND e.project_id = c.project_id);

COMMENT ON VIEW provenance_scope_violations IS
    'Stored scientific rows citing a record outside their project, or a record that does not '
    'exist (012s). New writes are refused by triggers; this lists history, read-only.';
