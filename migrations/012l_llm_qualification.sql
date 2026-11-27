-- What a capability probe demanded, and every lock a model has had.
--
-- `012e` recorded a probe as capability and outcome: enough while every probe asked one fixed thing.
-- ROLE_HYPOTHESIS is now run at the minimum number of competing hypotheses the deployment's research
-- requires (`llm_runtime.probes`), so the evidence records what was demonstrated: `parameters`, e.g.
-- {"minimum_hypotheses": 5}. Rows written before carry none -- they demonstrate no minimum, and so
-- serve no requirement.
--
-- A model's row holds its CURRENT lock, and re-qualifying it (unlock, test, lock) replaces that.
-- Every lock is therefore also recorded here, append-only, the moment it is made -- and every lock
-- standing now, once -- so a re-qualified model's earlier route fingerprint stays on record beside
-- the InferenceProvenance that names it. Whether a lock is still CURRENT is not stored anywhere: it
-- is recomputed at use against the semantics in force (`llm_runtime.registry.lock_problem`).

ALTER TABLE llm_capability_probes
    ADD COLUMN IF NOT EXISTS parameters JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(parameters) = 'object');

CREATE TABLE IF NOT EXISTS llm_model_locks (
    model_profile_id     TEXT NOT NULL REFERENCES llm_models (model_profile_id),
    lock_fingerprint     TEXT NOT NULL CHECK (lock_fingerprint ~ '^lk:[0-9a-f]{16}$'),
    locked_capabilities  TEXT[] NOT NULL,
    locked_at            TIMESTAMPTZ NOT NULL,
    locked_by            TEXT REFERENCES actors (actor_id),
    PRIMARY KEY (model_profile_id, locked_at, lock_fingerprint)
);

INSERT INTO llm_model_locks
    (model_profile_id, lock_fingerprint, locked_capabilities, locked_at, locked_by)
SELECT model_profile_id, lock_fingerprint, locked_capabilities, locked_at, locked_by
  FROM llm_models
 WHERE lifecycle = 'LOCKED'
ON CONFLICT DO NOTHING;

CREATE FUNCTION llm_model_locks_guard() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'llm_model_locks is append-only: a lock a model had is history';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER llm_model_locks_guard_trg BEFORE UPDATE OR DELETE ON llm_model_locks
    FOR EACH ROW EXECUTE FUNCTION llm_model_locks_guard();

CREATE FUNCTION llm_models_record_lock() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.lifecycle = 'LOCKED' AND OLD.lifecycle IS DISTINCT FROM 'LOCKED' THEN
        INSERT INTO llm_model_locks
            (model_profile_id, lock_fingerprint, locked_capabilities, locked_at, locked_by)
        VALUES
            (NEW.model_profile_id, NEW.lock_fingerprint, NEW.locked_capabilities, NEW.locked_at,
             NEW.locked_by);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER llm_models_record_lock_trg AFTER UPDATE ON llm_models
    FOR EACH ROW EXECUTE FUNCTION llm_models_record_lock();

COMMENT ON COLUMN llm_capability_probes.parameters IS
    'What the probe demanded where that varies: ROLE_HYPOTHESIS records {"minimum_hypotheses": N}, '
    'the number of competing hypotheses it asked for and the parser required (012l).';
COMMENT ON TABLE llm_model_locks IS
    'Every lock a model has had, recorded when made; append-only. The model row holds the current '
    'lock; whether it is still current is recomputed at use (012l).';
