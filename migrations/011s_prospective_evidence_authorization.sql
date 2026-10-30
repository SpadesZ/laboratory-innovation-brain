-- 011s: prospective support of a post-screening hypothesis needs evidence that is new in TIME, in
-- LINEAGE and in KIND, from a check someone accountable PRE-REGISTERED as a test of it.
--
-- NUMBERING. Applied after 011u (APPLY_ORDER is explicit); 012 suffixes are spent.
--
-- THE DEFECTS, DEMONSTRATED FIRST (tests/e2e/test_g0_prospective_evidence_postgres.py, on 011r with
-- 011p in force -- all eleven bases were ACCEPTED as SUPPORT of the post-screening rival):
--
--   unknown capture time  011p (f) skipped an artifact whose `captured_at` is NULL, so an uploaded
--                         measurement export with no capture time passed as new data
--   lineage               011p read no `derived_from_artifact_ids`: an output derived from a 2020
--                         measurement, an input derived (directly or transitively) from the
--                         screened output, a lineage cycle, an unbounded chain -- all passed
--   classification        the kind was read from `capabilities`, which the application role writes:
--                         a lookup inserted as a MEASUREMENT passed, a registered kind could be
--                         UPDATEd, and an ANALYTICAL_RULE_CHECK re-reading the very design file the
--                         screened reading read passed as "new evidence"
--   authorization         nothing asked whether anyone had pre-registered the check as a test of
--                         the hypothesis, so any later run of a passing kind could support it
--
-- THE CLOSURE.
--
--   capability_declarations   the kind of a capability, as its DomainPack's code declares it: the
--       pack id and version, the capability's contract version, the input media types the pack
--       reads as DESIGN SPECIFICATIONS, the canonical JSON the code produced and its SHA-256 (the
--       database recomputes the hash and checks the JSON against the `capabilities` row). Written
--       ONLY by the schema owner (the operator's migrator) -- the trigger checks `current_user`,
--       so a table privilege granted to the services' role does not open it -- and never changed.
--       A declared capability's contract in `capabilities` can no longer be UPDATEd by anyone.
--   verification_authorizations   a pre-registered test: which post-screening hypothesis, which of
--       its predictions, which declared capability (and declaration hash), by which accountable
--       person (an active HUMAN member of the project), why. Its time is the DATABASE's clock,
--       never the writer's, and must be after the hypothesis. Append-only.
--   verification_authorization_jobs   the one Job an authorization licenses, bound while the Job is
--       still QUEUED and has no Run -- so the authorization provably came before the execution.
--
-- For a hypothesis with a screening conditioning record, each basis observation of a SUPPORTS
-- relation (its source and the observation behind every cited attestation) must pass 011p's
-- rules (a)-(g) unchanged, and then (`prospective_basis_problem`):
--
--   (h) its capability is DECLARED (`capability_declarations`), agreeing with `capabilities`;
--   (i) its kind can produce new evidence about what it read:
--         EXISTING_EVIDENCE_LOOKUP, HISTORICAL_CASE_COMPARISON, HUMAN_EXPERT_REVIEW  never -- they
--             read or judge what exists;
--         ANALYTICAL_RULE_CHECK, NUMERICAL_SURROGATE  only of NEW EMPIRICAL inputs -- a deterministic
--             analysis of a design, or of anything that existed before the hypothesis, had its
--             outcome fixed (and readable) before the hypothesis was proposed;
--         SIMULATION  may read a declared design specification: it computes a consequence the
--             design does not state, after the hypothesis (still evidence about the DESIGNED device);
--         MEASUREMENT, FABRICATION  produce empirical data, whose capture time must be known;
--   (j) every EMPIRICAL artifact it reads or emits -- anything that is not a declared design
--       specification it reads, nor a computed RUN_OUTPUT of a computing kind -- has a KNOWN
--       capture time (NULL is refused: unknown is not new); no artifact it emits, and no empirical
--       artifact it reads, existed (row `created_at`) before the hypothesis;
--   (k) its LINEAGE -- `derived_from_artifact_ids` and `previous_artifact_id` of every input and
--       output, transitively, at most 16 links -- reaches no output of a screened run or of a run
--       that started before the hypothesis, no empirical data captured (or recorded) before it or of
--       unknown capture time, and no unrecorded artifact; a cycle or a deeper chain fails closed;
--   (l) its Job is bound to an authorization of THIS hypothesis, for THIS capability under the
--       declaration in force, naming the relation's prediction; the run started -- and an empirical
--       output was captured -- no earlier than the authorization.
--
-- PRESERVED. Relations other than SUPPORTS, and hypotheses formed before screening, are untouched:
-- retrospective evidence may still be recorded against a post-screening hypothesis as context
-- (CITES) and may still SUPPORT a pre-screening hypothesis. Stricter only: everything 011p refused
-- is refused with the same wording.
--
-- ENGINEERING, NOT SCIENCE. An accepted basis is a pre-registered, new, independent check as far
-- as the records show. It is not a physical confirmation, and the records are only as true as their
-- writers: a capture time, a media type or a lineage the writer omits or misstates is not detected.

-- -- capability declarations ----------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS capability_declarations (
    capability_id              TEXT PRIMARY KEY REFERENCES capabilities (capability_id),
    capability_version         TEXT NOT NULL CHECK (btrim(capability_version) <> ''),
    pack_id                    TEXT NOT NULL CHECK (btrim(pack_id) <> ''),
    pack_version               TEXT NOT NULL CHECK (btrim(pack_version) <> ''),
    action_type                TEXT NOT NULL,
    specification_media_types  TEXT[] NOT NULL DEFAULT '{}',
    declaration                TEXT NOT NULL,
    declaration_hash           TEXT NOT NULL CHECK (declaration_hash ~ '^sha256:[0-9a-f]{64}$'),
    registered_by              TEXT NOT NULL,
    registered_at              TIMESTAMPTZ NOT NULL
);

CREATE FUNCTION capability_declarations_are_the_packs() RETURNS TRIGGER AS $$
DECLARE
    v_owner OID;
    v_cap   capabilities%ROWTYPE;
    v_decl  JSONB;
BEGIN
    SELECT relowner INTO v_owner FROM pg_class WHERE oid = TG_RELID;
    IF NOT pg_has_role(current_user, v_owner, 'MEMBER') THEN
        RAISE EXCEPTION
            'capability %: a capability''s kind is declared by its domain pack and registered by '
            'the schema owner (the operator''s migrator), not by %; a kind the services could '
            'write would let a lookup call itself a measurement (011s)',
            NEW.capability_id, current_user;
    END IF;
    NEW.registered_by := current_user;
    NEW.registered_at := now();
    IF NEW.declaration_hash
       <> 'sha256:' || encode(sha256(convert_to(NEW.declaration, 'UTF8')), 'hex') THEN
        RAISE EXCEPTION 'capability %: the declaration hash is not the SHA-256 of the declaration',
            NEW.capability_id;
    END IF;
    v_decl := NEW.declaration::jsonb;
    SELECT * INTO v_cap FROM capabilities WHERE capability_id = NEW.capability_id;
    IF v_decl ->> 'pack_id' IS DISTINCT FROM NEW.pack_id
       OR v_decl ->> 'pack_version' IS DISTINCT FROM NEW.pack_version
       OR v_decl ->> 'version' IS DISTINCT FROM NEW.capability_version
       OR v_decl ->> 'action_type' IS DISTINCT FROM NEW.action_type
       OR v_decl -> 'specification_media_types' IS DISTINCT FROM
          to_jsonb(NEW.specification_media_types)
       OR (v_decl - 'pack_id' - 'pack_version' - 'specification_media_types') IS DISTINCT FROM
          jsonb_build_object(
              'capability_id', v_cap.capability_id, 'domain', v_cap.domain,
              'action_type', v_cap.action_type, 'backend_id', v_cap.backend_id,
              'requires', to_jsonb(v_cap.requires), 'produces', to_jsonb(v_cap.produces),
              'authority_class', v_cap.authority_class,
              'conditions_schema_version', v_cap.conditions_schema_version,
              'privacy_constraints', to_jsonb(v_cap.privacy_constraints),
              'license_constraints', to_jsonb(v_cap.license_constraints),
              'irreversible', v_cap.irreversible,
              'estimate_cost_contract', v_cap.estimate_cost_contract,
              'version', v_cap.version)
    THEN
        RAISE EXCEPTION
            'capability %: the declaration does not describe the registered capability (its '
            'kind, contract or pack fields differ); a declaration is the pack''s code, exactly',
            NEW.capability_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER capability_declarations_are_the_packs_trg BEFORE INSERT ON capability_declarations
    FOR EACH ROW EXECUTE FUNCTION capability_declarations_are_the_packs();

CREATE FUNCTION prospective_rows_are_append_only() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        '% is append-only: a declared kind, a pre-registered test and the job it licensed say '
        'what was decided before the evidence existed; rewriting one would hide that (011s)',
        TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER capability_declarations_are_append_only_trg
    BEFORE UPDATE OR DELETE ON capability_declarations
    FOR EACH ROW EXECUTE FUNCTION prospective_rows_are_append_only();

-- A declared capability's contract is the declaration's: no writer changes it in place.
CREATE FUNCTION capabilities_declared_contract_is_fixed() RETURNS TRIGGER AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM capability_declarations WHERE capability_id = OLD.capability_id)
       AND (NEW.capability_id, NEW.domain, NEW.action_type, NEW.backend_id, NEW.requires,
            NEW.produces, NEW.authority_class, NEW.conditions_schema_version,
            NEW.privacy_constraints, NEW.license_constraints, NEW.irreversible,
            NEW.estimate_cost_contract, NEW.version)
           IS DISTINCT FROM
           (OLD.capability_id, OLD.domain, OLD.action_type, OLD.backend_id, OLD.requires,
            OLD.produces, OLD.authority_class, OLD.conditions_schema_version,
            OLD.privacy_constraints, OLD.license_constraints, OLD.irreversible,
            OLD.estimate_cost_contract, OLD.version)
    THEN
        RAISE EXCEPTION
            'capability % is declared by its domain pack: its kind and contract cannot change in '
            'place; a changed capability is a new declared version (011s)', OLD.capability_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER capabilities_declared_contract_is_fixed_trg BEFORE UPDATE ON capabilities
    FOR EACH ROW EXECUTE FUNCTION capabilities_declared_contract_is_fixed();

-- -- verification authorizations --------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS verification_authorizations (
    authorization_id  TEXT PRIMARY KEY CHECK (authorization_id ~ '^vauth:[A-Za-z0-9_.:\-]+$'),
    project_id        TEXT NOT NULL REFERENCES projects (project_id),
    episode_id        TEXT NOT NULL REFERENCES research_episodes (episode_id),
    hypothesis_id     TEXT NOT NULL,
    prediction_ids    TEXT[] NOT NULL CHECK (cardinality(prediction_ids) >= 1),
    capability_id     TEXT NOT NULL REFERENCES capability_declarations (capability_id),
    declaration_hash  TEXT NOT NULL,
    actor_id          TEXT NOT NULL REFERENCES actors (actor_id),
    rationale         TEXT NOT NULL CHECK (btrim(rationale) <> ''),
    created_at        TIMESTAMPTZ NOT NULL,

    FOREIGN KEY (project_id, hypothesis_id) REFERENCES hypotheses (project_id, hypothesis_id)
);

CREATE INDEX IF NOT EXISTS verification_authorizations_hypothesis_idx
    ON verification_authorizations (project_id, hypothesis_id);

CREATE FUNCTION verification_authorization_is_prospective() RETURNS TRIGGER AS $$
DECLARE
    v_hypothesis  hypotheses%ROWTYPE;
    v_declared    capability_declarations%ROWTYPE;
    v_missing     TEXT;
BEGIN
    -- The database's clock: an authorization cannot be dated before it was made.
    NEW.created_at := now();
    SELECT * INTO v_hypothesis FROM hypotheses
     WHERE project_id = NEW.project_id AND hypothesis_id = NEW.hypothesis_id;
    IF NOT EXISTS (SELECT 1 FROM screening_conditioned_hypotheses
                    WHERE project_id = NEW.project_id AND hypothesis_id = NEW.hypothesis_id) THEN
        RAISE EXCEPTION
            'authorization %: % was not proposed after screening; a verification authorization '
            'pre-registers a test of a post-screening hypothesis (011s)',
            NEW.authorization_id, NEW.hypothesis_id;
    END IF;
    IF v_hypothesis.created_in_episode IS DISTINCT FROM NEW.episode_id THEN
        RAISE EXCEPTION 'authorization %: % is a hypothesis of episode %, not %',
            NEW.authorization_id, NEW.hypothesis_id, v_hypothesis.created_in_episode,
            NEW.episode_id;
    END IF;
    IF NOT (NEW.created_at > v_hypothesis.created_at) THEN
        RAISE EXCEPTION
            'authorization %: made at %, not after hypothesis % (%); a test is registered after '
            'the hypothesis it tests exists (011s)',
            NEW.authorization_id, NEW.created_at, NEW.hypothesis_id, v_hypothesis.created_at;
    END IF;
    SELECT * INTO v_declared FROM capability_declarations
     WHERE capability_id = NEW.capability_id;
    IF NEW.declaration_hash IS DISTINCT FROM v_declared.declaration_hash THEN
        RAISE EXCEPTION 'authorization %: % is declared as %, not %',
            NEW.authorization_id, NEW.capability_id, v_declared.declaration_hash,
            NEW.declaration_hash;
    END IF;
    IF v_declared.action_type IN ('EXISTING_EVIDENCE_LOOKUP', 'HISTORICAL_CASE_COMPARISON',
                                  'HUMAN_EXPERT_REVIEW') THEN
        RAISE EXCEPTION
            'authorization %: % is a %, which reads or judges existing evidence; it cannot be a '
            'prospective test (011s)', NEW.authorization_id, NEW.capability_id,
            v_declared.action_type;
    END IF;
    SELECT x INTO v_missing FROM unnest(NEW.prediction_ids) x
     WHERE NOT EXISTS (
        SELECT 1 FROM predictions p JOIN capabilities c ON c.capability_id = NEW.capability_id
         WHERE p.prediction_id = x AND p.project_id = NEW.project_id
           AND p.hypothesis_id = NEW.hypothesis_id
           AND p.observable_ref = ANY (c.produces))
     ORDER BY x LIMIT 1;
    IF v_missing IS NOT NULL THEN
        RAISE EXCEPTION
            'authorization %: % is not a prediction of % about an observable % produces',
            NEW.authorization_id, v_missing, NEW.hypothesis_id, NEW.capability_id;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM actors a JOIN project_memberships m ON m.actor_id = a.actor_id
         WHERE a.actor_id = NEW.actor_id AND a.actor_type = 'HUMAN' AND a.active
           AND m.project_id = NEW.project_id AND m.active)
    THEN
        RAISE EXCEPTION
            'authorization %: % is not an active person in project %; a test is pre-registered '
            'by someone accountable for it, never by a model or a service (011s)',
            NEW.authorization_id, NEW.actor_id, NEW.project_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER verification_authorization_is_prospective_trg
    BEFORE INSERT ON verification_authorizations
    FOR EACH ROW EXECUTE FUNCTION verification_authorization_is_prospective();

CREATE TRIGGER verification_authorizations_are_append_only_trg
    BEFORE UPDATE OR DELETE ON verification_authorizations
    FOR EACH ROW EXECUTE FUNCTION prospective_rows_are_append_only();

CREATE TABLE IF NOT EXISTS verification_authorization_jobs (
    -- One job per authorization: a pre-registered test is run once, not until it agrees.
    authorization_id  TEXT PRIMARY KEY REFERENCES verification_authorizations (authorization_id),
    job_id            TEXT NOT NULL UNIQUE REFERENCES jobs (job_id),
    bound_at          TIMESTAMPTZ NOT NULL
);

CREATE FUNCTION verification_job_is_bound_before_it_runs() RETURNS TRIGGER AS $$
DECLARE
    v_auth verification_authorizations%ROWTYPE;
    v_job  jobs%ROWTYPE;
BEGIN
    NEW.bound_at := now();
    SELECT * INTO v_auth FROM verification_authorizations
     WHERE authorization_id = NEW.authorization_id;
    SELECT * INTO v_job FROM jobs WHERE job_id = NEW.job_id;
    IF v_job.project_id IS DISTINCT FROM v_auth.project_id
       OR v_job.episode_id IS DISTINCT FROM v_auth.episode_id
       OR v_job.capability_id IS DISTINCT FROM v_auth.capability_id THEN
        RAISE EXCEPTION
            'authorization %: job % is not a % job of episode %',
            NEW.authorization_id, NEW.job_id, v_auth.capability_id, v_auth.episode_id;
    END IF;
    IF v_job.state <> 'QUEUED' OR v_job.result_run_id IS NOT NULL
       OR EXISTS (SELECT 1 FROM runs WHERE job_id = NEW.job_id) THEN
        RAISE EXCEPTION
            'authorization %: job % is already % -- an authorization is bound before its check '
            'runs, never after (011s)', NEW.authorization_id, NEW.job_id, v_job.state;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER verification_job_is_bound_before_it_runs_trg
    BEFORE INSERT ON verification_authorization_jobs
    FOR EACH ROW EXECUTE FUNCTION verification_job_is_bound_before_it_runs();

CREATE TRIGGER verification_authorization_jobs_are_append_only_trg
    BEFORE UPDATE OR DELETE ON verification_authorization_jobs
    FOR EACH ROW EXECUTE FUNCTION prospective_rows_are_append_only();

-- -- the facts, one function each (the guard and the evaluator's collector read the same rules) ---

-- Kinds that compute an outcome from their inputs, so a RUN_OUTPUT of theirs is computed, not data.
CREATE FUNCTION prospective_computing_kind(p_kind TEXT) RETURNS BOOLEAN AS $$
    SELECT p_kind IN ('ANALYTICAL_RULE_CHECK', 'NUMERICAL_SURROGATE', 'SIMULATION');
$$ LANGUAGE sql IMMUTABLE;

-- Is artifact `a` a declared design specification this run reads? (Never an output.)
CREATE FUNCTION prospective_is_specification(p_run runs, p_artifact artifacts) RETURNS BOOLEAN AS $$
    SELECT p_artifact.artifact_id = ANY (p_run.input_artifacts)
       AND p_artifact.source_origin IN ('UPLOAD', 'WATCHER_FILESYSTEM', 'WATCHER_GIT')
       AND EXISTS (SELECT 1 FROM capability_declarations d
                    WHERE d.capability_id = p_run.capability_id
                      AND p_artifact.media_type = ANY (d.specification_media_types));
$$ LANGUAGE sql STABLE;

-- Is artifact `a` empirical data for this run (neither a design it reads nor its computed output)?
CREATE FUNCTION prospective_is_empirical(p_run runs, p_artifact artifacts) RETURNS BOOLEAN AS $$
    SELECT NOT prospective_is_specification(p_run, p_artifact)
       AND NOT (p_artifact.artifact_id = ANY (p_run.output_artifacts)
                AND p_artifact.source_origin = 'RUN_OUTPUT'
                AND EXISTS (SELECT 1 FROM capability_declarations d
                             WHERE d.capability_id = p_run.capability_id
                               AND prospective_computing_kind(d.action_type)));
$$ LANGUAGE sql STABLE;

-- (h) declared, and agreeing with `capabilities`.            -> fact `unclassified_capability`
CREATE FUNCTION prospective_declaration_problem(p_run runs) RETURNS TEXT AS $$
DECLARE
    v_declared capability_declarations%ROWTYPE;
    v_kind     TEXT;
BEGIN
    SELECT * INTO v_declared FROM capability_declarations WHERE capability_id = p_run.capability_id;
    IF NOT FOUND THEN
        RETURN format('run %s is of capability %s, whose kind is not declared by a domain pack '
                      '(capability_declarations); a kind the services wrote is not a '
                      'classification (011s)', p_run.run_id, p_run.capability_id);
    END IF;
    SELECT action_type INTO v_kind FROM capabilities WHERE capability_id = p_run.capability_id;
    IF v_kind IS DISTINCT FROM v_declared.action_type THEN
        RETURN format('run %s: capability %s is registered as %s but declared as %s (011s)',
                      p_run.run_id, p_run.capability_id, v_kind, v_declared.action_type);
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE;

-- (i) a kind that can produce new evidence about what it read.  -> fact `retrospective_basis`
CREATE FUNCTION prospective_kind_problem(p_run runs, p_hypothesis_created TIMESTAMPTZ)
RETURNS TEXT AS $$
DECLARE
    v_kind     TEXT;
    v_artifact TEXT;
BEGIN
    SELECT action_type INTO v_kind FROM capability_declarations
     WHERE capability_id = p_run.capability_id;
    IF v_kind IS NULL THEN
        RETURN NULL;  -- undeclared: (h) refuses it
    END IF;
    IF v_kind IN ('EXISTING_EVIDENCE_LOOKUP', 'HISTORICAL_CASE_COMPARISON',
                  'HUMAN_EXPERT_REVIEW') THEN
        RETURN format('run %s is of capability %s, a %s: it reads existing evidence, which is '
                      'retrospective, not a prospective check (011p, 011s)',
                      p_run.run_id, p_run.capability_id, v_kind);
    END IF;
    IF v_kind IN ('ANALYTICAL_RULE_CHECK', 'NUMERICAL_SURROGATE') THEN
        SELECT a.artifact_id INTO v_artifact FROM artifacts a
         WHERE a.artifact_id = ANY (p_run.input_artifacts)
           AND (prospective_is_specification(p_run, a) OR a.created_at < p_hypothesis_created)
         ORDER BY a.artifact_id LIMIT 1;
        IF v_artifact IS NOT NULL OR cardinality(p_run.input_artifacts) = 0 THEN
            RETURN format('run %s is a %s of %s, which existed before the hypothesis (a design or '
                          'older data): a deterministic analysis of it had its outcome fixed '
                          'before the hypothesis, so it is not new evidence (011s)',
                          p_run.run_id, v_kind, coalesce(v_artifact, 'no new input'));
        END IF;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE;

-- (j) empirical data of known capture time, nothing that existed before. -> `unknown_capture_time`
--     (the NULL case) and `retrospective_basis` (the existed-before case)
CREATE FUNCTION prospective_capture_problem(p_run runs, p_hypothesis_created TIMESTAMPTZ)
RETURNS TEXT AS $$
DECLARE
    v_artifact TEXT;
BEGIN
    SELECT a.artifact_id INTO v_artifact FROM artifacts a
     WHERE a.artifact_id = ANY (p_run.input_artifacts || p_run.output_artifacts)
       AND a.captured_at IS NULL AND prospective_is_empirical(p_run, a)
     ORDER BY a.artifact_id LIMIT 1;
    IF v_artifact IS NOT NULL THEN
        RETURN format('run %s reads or emits %s, empirical data whose capture time is unknown: '
                      'unknown is not new, so it cannot be a prospective check (011s)',
                      p_run.run_id, v_artifact);
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE;

CREATE FUNCTION prospective_existence_problem(p_run runs, p_hypothesis_created TIMESTAMPTZ)
RETURNS TEXT AS $$
DECLARE
    v_artifact TEXT;
BEGIN
    SELECT a.artifact_id INTO v_artifact FROM artifacts a
     WHERE a.artifact_id = ANY (p_run.input_artifacts || p_run.output_artifacts)
       AND a.created_at < p_hypothesis_created
       AND (a.artifact_id = ANY (p_run.output_artifacts) OR prospective_is_empirical(p_run, a))
     ORDER BY a.artifact_id LIMIT 1;
    IF v_artifact IS NOT NULL THEN
        RETURN format('run %s reads or emits %s, which was recorded before the hypothesis was '
                      'proposed: retrospective evidence, not a prospective check (011s)',
                      p_run.run_id, v_artifact);
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE;

-- (k) lineage, transitively, bounded.                      -> fact `lineage_before_hypothesis`
--
-- Every ancestor of every input and output (`derived_from_artifact_ids`, `previous_artifact_id`),
-- with its depth; a link already on its path is a cycle, and the walk stops there and at depth 17.
CREATE FUNCTION prospective_lineage(p_run runs)
RETURNS TABLE (origin TEXT, artifact_id TEXT, depth INTEGER, cyclic BOOLEAN) AS $$
    WITH RECURSIVE walk (origin, artifact_id, depth, path, cyclic) AS (
        SELECT x, x, 0, ARRAY[x], FALSE
          FROM unnest(p_run.input_artifacts || p_run.output_artifacts) x
        UNION ALL
        SELECT w.origin, parent, w.depth + 1, w.path || parent, parent = ANY (w.path)
          FROM walk w
          JOIN artifacts a ON a.artifact_id = w.artifact_id
          CROSS JOIN LATERAL unnest(
              a.derived_from_artifact_ids
              || CASE WHEN a.previous_artifact_id IS NULL THEN '{}'::TEXT[]
                      ELSE ARRAY[a.previous_artifact_id] END) parent
         WHERE NOT w.cyclic AND w.depth < 17
    )
    SELECT origin, artifact_id, depth, cyclic FROM walk WHERE depth >= 1;
$$ LANGUAGE sql STABLE;

CREATE FUNCTION prospective_lineage_problem(
    p_conditioned screening_conditioned_hypotheses,
    p_run runs,
    p_hypothesis_created TIMESTAMPTZ
) RETURNS TEXT AS $$
DECLARE
    v_hit  RECORD;
BEGIN
    SELECT * INTO v_hit FROM prospective_lineage(p_run) l WHERE l.cyclic
     ORDER BY l.origin, l.depth LIMIT 1;
    IF FOUND THEN
        RETURN format('run %s: the lineage of %s is a cycle (through %s); a record that derives '
                      'from itself cannot show when its data came to be (011s)',
                      p_run.run_id, v_hit.origin, v_hit.artifact_id);
    END IF;
    SELECT * INTO v_hit FROM prospective_lineage(p_run) l WHERE l.depth > 16
     ORDER BY l.origin LIMIT 1;
    IF FOUND THEN
        RETURN format('run %s: the lineage of %s is deeper than 16 links; it is not walked '
                      'further, and what is not walked is not shown to be new (011s)',
                      p_run.run_id, v_hit.origin);
    END IF;
    SELECT l.* INTO v_hit FROM prospective_lineage(p_run) l
     WHERE NOT EXISTS (SELECT 1 FROM artifacts a WHERE a.artifact_id = l.artifact_id)
     ORDER BY l.origin, l.depth LIMIT 1;
    IF FOUND THEN
        RETURN format('run %s: the lineage of %s names %s, which is not recorded (011s)',
                      p_run.run_id, v_hit.origin, v_hit.artifact_id);
    END IF;
    SELECT l.origin, l.artifact_id, earlier.run_id AS run_id INTO v_hit
      FROM prospective_lineage(p_run) l
      JOIN runs earlier ON l.artifact_id = ANY (earlier.output_artifacts)
     WHERE earlier.run_id <> p_run.run_id
       AND (earlier.start_time < p_hypothesis_created
            OR EXISTS (SELECT 1 FROM screening_observations s
                        WHERE s.screening_observation_id
                              = ANY (p_conditioned.screening_observation_ids)
                          AND s.run_id = earlier.run_id))
     ORDER BY l.origin, l.depth LIMIT 1;
    IF FOUND THEN
        RETURN format('run %s: the lineage of %s reaches %s, an output of run %s, which ran '
                      'before the hypothesis was proposed or is the screened reading: derived from '
                      'evidence that already existed (011s)',
                      p_run.run_id, v_hit.origin, v_hit.artifact_id, v_hit.run_id);
    END IF;
    -- An ancestor that is data (not a declared design specification of this capability).
    SELECT l.origin, l.artifact_id, a.captured_at INTO v_hit
      FROM prospective_lineage(p_run) l JOIN artifacts a ON a.artifact_id = l.artifact_id
     WHERE NOT (a.source_origin IN ('UPLOAD', 'WATCHER_FILESYSTEM', 'WATCHER_GIT')
                AND EXISTS (SELECT 1 FROM capability_declarations d
                             WHERE d.capability_id = p_run.capability_id
                               AND a.media_type = ANY (d.specification_media_types)))
       AND (a.captured_at IS NULL OR a.captured_at < p_hypothesis_created
            OR a.created_at < p_hypothesis_created)
     ORDER BY l.origin, l.depth LIMIT 1;
    IF FOUND THEN
        RETURN format('run %s: the lineage of %s reaches %s, data %s: derived from evidence '
                      'that is not shown to be new (011s)',
                      p_run.run_id, v_hit.origin, v_hit.artifact_id,
                      CASE WHEN v_hit.captured_at IS NULL THEN 'of unknown capture time'
                           ELSE 'captured or recorded before the hypothesis' END);
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE;

-- (l) pre-registered for this hypothesis, capability and prediction. -> `unauthorized_verification`
CREATE FUNCTION prospective_authorization_problem(
    p_conditioned screening_conditioned_hypotheses,
    p_run runs,
    p_prediction_id TEXT,
    p_check_prediction BOOLEAN DEFAULT TRUE
) RETURNS TEXT AS $$
DECLARE
    v_auth    verification_authorizations%ROWTYPE;
    v_bound   TIMESTAMPTZ;
    v_hash    TEXT;
    v_kind    TEXT;
    v_early   TEXT;
BEGIN
    SELECT a.* INTO v_auth
      FROM verification_authorization_jobs b
      JOIN verification_authorizations a ON a.authorization_id = b.authorization_id
     WHERE b.job_id = p_run.job_id;
    IF NOT FOUND THEN
        RETURN format('run %s was not pre-registered: no verification authorization names its '
                      'job %s, so it is not an authorized test of %s, which was proposed after '
                      'screening (011s)', p_run.run_id, p_run.job_id, p_conditioned.hypothesis_id);
    END IF;
    SELECT bound_at INTO v_bound FROM verification_authorization_jobs WHERE job_id = p_run.job_id;
    IF v_auth.project_id <> p_conditioned.project_id
       OR v_auth.hypothesis_id <> p_conditioned.hypothesis_id THEN
        RETURN format('run %s was authorized (%s) as a test of %s, not of %s (011s)',
                      p_run.run_id, v_auth.authorization_id, v_auth.hypothesis_id,
                      p_conditioned.hypothesis_id);
    END IF;
    IF v_auth.capability_id <> p_run.capability_id THEN
        RETURN format('run %s is of %s; its authorization %s licensed %s (011s)',
                      p_run.run_id, p_run.capability_id, v_auth.authorization_id,
                      v_auth.capability_id);
    END IF;
    SELECT declaration_hash, action_type INTO v_hash, v_kind FROM capability_declarations
     WHERE capability_id = p_run.capability_id;
    IF v_hash IS DISTINCT FROM v_auth.declaration_hash THEN
        RETURN format('run %s: authorization %s was made under another declaration of %s (011s)',
                      p_run.run_id, v_auth.authorization_id, p_run.capability_id);
    END IF;
    IF p_check_prediction
       AND (p_prediction_id IS NULL OR NOT (p_prediction_id = ANY (v_auth.prediction_ids))) THEN
        RETURN format('run %s: authorization %s pre-registered predictions %s of %s, not %s; a '
                      'test supports only what it was registered to test (011s)',
                      p_run.run_id, v_auth.authorization_id, v_auth.prediction_ids,
                      p_conditioned.hypothesis_id, coalesce(p_prediction_id, 'an unnamed one'));
    END IF;
    IF p_run.start_time < v_auth.created_at OR p_run.created_at < v_bound THEN
        RETURN format('run %s started at %s, before its authorization %s was made (%s): a test '
                      'authorized after it began is not pre-registered (011s)',
                      p_run.run_id, p_run.start_time, v_auth.authorization_id, v_auth.created_at);
    END IF;
    IF v_kind IN ('MEASUREMENT', 'FABRICATION') THEN
        SELECT a.artifact_id INTO v_early FROM artifacts a
         WHERE a.artifact_id = ANY (p_run.output_artifacts)
           AND (a.captured_at IS NULL OR a.captured_at < v_auth.created_at)
         ORDER BY a.artifact_id LIMIT 1;
        IF v_early IS NOT NULL THEN
            RETURN format('run %s emits %s, whose data was captured before its authorization %s '
                          'was made (%s): not a pre-registered measurement (011s)',
                          p_run.run_id, v_early, v_auth.authorization_id, v_auth.created_at);
        END IF;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE;

-- -- the guard ----------------------------------------------------------------------------------

CREATE FUNCTION prospective_basis_problem(
    p_conditioned screening_conditioned_hypotheses,
    p_hypothesis_created TIMESTAMPTZ,
    p_observation_id TEXT,
    p_prediction_id TEXT,
    p_check_prediction BOOLEAN DEFAULT TRUE
) RETURNS TEXT AS $$
DECLARE
    v_problem TEXT;
    v_run     runs%ROWTYPE;
BEGIN
    -- 011p (a)-(g), unchanged, with the same wording. Its (h) is read from the declaration below.
    v_problem := screening_basis_problem(p_conditioned, p_hypothesis_created, p_observation_id);
    IF v_problem IS NOT NULL AND v_problem NOT LIKE '%not registered with a kind%'
       AND v_problem NOT LIKE '%reads existing evidence%' THEN
        RETURN v_problem;
    END IF;
    SELECT r.* INTO v_run FROM runs r JOIN observations o ON o.run_id = r.run_id
     WHERE o.observation_id = p_observation_id;
    v_problem := coalesce(
        prospective_declaration_problem(v_run),
        prospective_kind_problem(v_run, p_hypothesis_created),
        prospective_capture_problem(v_run, p_hypothesis_created),
        prospective_existence_problem(v_run, p_hypothesis_created),
        prospective_lineage_problem(p_conditioned, v_run, p_hypothesis_created),
        prospective_authorization_problem(p_conditioned, v_run, p_prediction_id,
                                          p_check_prediction));
    RETURN v_problem;
END;
$$ LANGUAGE plpgsql STABLE;

CREATE OR REPLACE FUNCTION relation_judgments_screening_guard() RETURNS TRIGGER AS $$
DECLARE
    v_conditioned  screening_conditioned_hypotheses%ROWTYPE;
    v_created      TIMESTAMPTZ;
    v_attestation  TEXT;
    v_cited        TEXT;
    v_problem      TEXT;
    v_prediction   TEXT;
BEGIN
    IF NEW.relation_type <> 'SUPPORTS' THEN
        RETURN NEW;
    END IF;
    SELECT * INTO v_conditioned FROM screening_conditioned_hypotheses
     WHERE project_id = NEW.project_id AND hypothesis_id = NEW.to_entity_id;
    IF NOT FOUND THEN
        RETURN NEW;
    END IF;
    SELECT created_at INTO v_created FROM hypotheses
     WHERE project_id = NEW.project_id AND hypothesis_id = NEW.to_entity_id;
    v_prediction := NEW.attributes ->> 'prediction_id';
    IF NOT EXISTS (SELECT 1 FROM observations WHERE observation_id = NEW.from_entity_id) THEN
        RAISE EXCEPTION
            'relation %: % is not an observation; only an observation can SUPPORT % , which was '
            'proposed after screening (011o)', NEW.relation_id, NEW.from_entity_id,
            NEW.to_entity_id;
    END IF;
    -- Everything the source and every cited observation rest on first; which prediction the
    -- relation claims is judged last, so a refusal names the deepest defect.
    v_problem := prospective_basis_problem(v_conditioned, v_created, NEW.from_entity_id,
                                           v_prediction, FALSE);
    IF v_problem IS NOT NULL THEN
        RAISE EXCEPTION 'relation %: %', NEW.relation_id, v_problem;
    END IF;
    FOREACH v_attestation IN ARRAY NEW.supporting_attestation_ids LOOP
        SELECT observation_id INTO v_cited FROM attestations WHERE attestation_id = v_attestation;
        IF v_cited IS NULL THEN
            RAISE EXCEPTION
                'relation %: it cites %, which attests no observation; only a prospective check '
                'can SUPPORT %, which was proposed after screening (011o)',
                NEW.relation_id, v_attestation, NEW.to_entity_id;
        END IF;
        v_problem := prospective_basis_problem(v_conditioned, v_created, v_cited, v_prediction,
                                               FALSE);
        IF v_problem IS NOT NULL THEN
            RAISE EXCEPTION 'relation %: it cites % of %: %',
                NEW.relation_id, v_attestation, v_cited, v_problem;
        END IF;
    END LOOP;
    -- (l), last: the relation names a prediction each basis run was pre-registered to test.
    SELECT p INTO v_problem FROM (
        SELECT prospective_authorization_problem(v_conditioned, r, v_prediction, TRUE) AS p
          FROM observations o JOIN runs r ON r.run_id = o.run_id
         WHERE o.observation_id = NEW.from_entity_id
            OR o.observation_id IN (SELECT a.observation_id FROM attestations a
                                     WHERE a.attestation_id = ANY (NEW.supporting_attestation_ids))
    ) x WHERE p IS NOT NULL LIMIT 1;
    IF v_problem IS NOT NULL THEN
        RAISE EXCEPTION 'relation %: %', NEW.relation_id, v_problem;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
