-- 003f_measurement_provenance.sql
--
-- G0 residual T-1 (High), prototype (docs/audit/g0-boundary-round5-2026-11-21/REPORT.md §T-1).
--
-- THE GAP. The services' role writes runs, observations and attestations -- the path every real
-- measurement takes -- so a stored row cannot tell a reading an instrument or a simulation runner
-- produced from one the services' process made up (reproduced: tests/e2e/
-- test_g0_measurement_provenance_postgres.py, a four-point-probe measurement that never happened is
-- admitted as support).
--
-- THE BOUNDARY. A measurement counts as provenance-verified only when a key the services' role
-- never holds signed it: the instrument's (or simulation runner's) Ed25519 key, enrolled here by
-- the schema owner. The runner signs a canonical statement binding
--     the run request (job id) and the run id, a nonce the database issued for that job,
--     the capability and the instrument (the run's backend id),
--     the digest of the raw output bytes, and the time of measurement
-- (`lab_brain.security.measurement_provenance.measurement_statement`). PostgreSQL cannot verify
-- an Ed25519 signature without an extension, so the readers verify it in Python and fail closed
-- (`MeasurementProvenance`); this migration records what they need, and makes the parts the
-- services must not choose the database's or the owner's:
--   * `measurement_signing_keys` / `measurement_signing_key_revocations`: owner only (the 012t
--     membership test), append-only, database clock and login role stamped. Enrolment names the
--     instrument and the capabilities a key may sign for, and a person who decided it.
--   * `measurement_nonces`: any writer may ask for a job's nonce, but the value and the time are
--     the database's (gen_random_uuid, clock_timestamp), one per job, append-only, and only while
--     the job has not finished -- so a statement cannot be signed before its request existed, nor
--     for a job that is already over.
--   * `measurement_signatures`: the runner's output, relayed by the services (who cannot forge
--     it): one per run, append-only, its nonce must be its job's, its run must be of that job, and
--     the database clock records when it arrived.
--
-- ENFORCEMENT IS PER INSTRUMENT AND CAPABILITY. Once the owner enrols a key for an
-- (instrument, capability), every measurement of that pair must carry a signature that verifies
-- (an unsigned one is labelled UNSIGNED and never counted as support); pairs with no enrolled key
-- are labelled NOT_REQUIRED and keep counting as before. A global strict switch is an Owner
-- decision, once runners exist for every backend.
--
-- WHAT SIGNING CANNOT PROVE. That the physical quantity is what the instrument reported (a lying
-- sensor, a mis-set probe); that the instrument host or the runner was not compromised (whoever
-- holds the key signs anything); that the key was not stolen; that the extraction from the signed
-- raw bytes to an observation value is faithful (the observation row is still the services'
-- write -- deterministic re-extraction from the signed bytes is the next step, designed only).
--
-- PRIVILEGES. Nothing here is granted or revoked: the guards refuse a non-owner whatever the
-- grants are. Revoking the services' row writes on the two key tables is the separate commit that
-- needs the Owner's approval.

CREATE TABLE measurement_signing_keys (
    key_id          TEXT PRIMARY KEY CHECK (key_id ~ '^rk:[0-9a-f]{32}$'),
    public_key      TEXT NOT NULL UNIQUE,
    -- The runs.backend_id this key signs for (one instrument or simulation runner).
    instrument_id   TEXT NOT NULL CHECK (btrim(instrument_id) <> ''),
    capability_ids  TEXT[] NOT NULL CHECK (cardinality(capability_ids) >= 1
                                           AND array_position(capability_ids, NULL) IS NULL),
    reason          TEXT NOT NULL CHECK (length(btrim(reason)) >= 10),
    actor_id        TEXT NOT NULL REFERENCES actors (actor_id),
    enrolled_at     TIMESTAMPTZ NOT NULL,
    recorded_by     TEXT NOT NULL
);

CREATE TABLE measurement_signing_key_revocations (
    key_id      TEXT PRIMARY KEY REFERENCES measurement_signing_keys (key_id),
    reason      TEXT NOT NULL CHECK (length(btrim(reason)) >= 10),
    actor_id    TEXT NOT NULL REFERENCES actors (actor_id),
    revoked_at  TIMESTAMPTZ NOT NULL,
    recorded_by TEXT NOT NULL
);

CREATE FUNCTION measurement_keys_are_the_owners() RETURNS TRIGGER AS $$
DECLARE
    v_owner OID;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION '% is append-only: % refused; a later decision is a new row (003f)',
            TG_TABLE_NAME, TG_OP
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    SELECT relowner INTO v_owner FROM pg_class WHERE oid = TG_RELID;
    IF NOT pg_has_role(current_user, v_owner, 'MEMBER') THEN
        RAISE EXCEPTION
            '%: a measurement signing key is enrolled or revoked by the schema owner, not by %; '
            'a key the services could enrol would let them sign their own measurements (003f)',
            TG_TABLE_NAME, current_user
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF TG_TABLE_NAME = 'measurement_signing_keys' THEN
        NEW.enrolled_at := clock_timestamp();
    ELSE
        NEW.revoked_at := clock_timestamp();
    END IF;
    NEW.recorded_by := session_user;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public;

CREATE TRIGGER measurement_signing_keys_are_the_owners
    BEFORE INSERT OR UPDATE OR DELETE ON measurement_signing_keys
    FOR EACH ROW EXECUTE FUNCTION measurement_keys_are_the_owners();
CREATE TRIGGER measurement_signing_key_revocations_are_the_owners
    BEFORE INSERT OR UPDATE OR DELETE ON measurement_signing_key_revocations
    FOR EACH ROW EXECUTE FUNCTION measurement_keys_are_the_owners();

CREATE TABLE measurement_nonces (
    nonce      TEXT PRIMARY KEY,
    job_id     TEXT NOT NULL UNIQUE REFERENCES jobs (job_id),
    issued_at  TIMESTAMPTZ NOT NULL,
    issued_by  TEXT NOT NULL
);

-- The value and the time are the database's; one per job; only for a job not yet finished.
CREATE FUNCTION measurement_nonces_are_the_databases() RETURNS TRIGGER AS $$
DECLARE
    v_state TEXT;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'measurement_nonces is append-only: % refused (003f)', TG_OP
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    SELECT state INTO v_state FROM jobs WHERE job_id = NEW.job_id;
    IF v_state IS NULL OR v_state NOT IN ('QUEUED', 'RUNNING') THEN
        RAISE EXCEPTION 'measurement nonce for job %: the job is %, and a nonce is issued only '
            'before its run is over (003f)', NEW.job_id, coalesce(v_state, 'not recorded');
    END IF;
    NEW.nonce := gen_random_uuid()::TEXT;
    NEW.issued_at := clock_timestamp();
    NEW.issued_by := session_user;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public;

CREATE TRIGGER measurement_nonces_are_the_databases
    BEFORE INSERT OR UPDATE OR DELETE ON measurement_nonces
    FOR EACH ROW EXECUTE FUNCTION measurement_nonces_are_the_databases();

CREATE TABLE measurement_signatures (
    run_id       TEXT PRIMARY KEY REFERENCES runs (run_id),
    job_id       TEXT NOT NULL REFERENCES jobs (job_id),
    nonce        TEXT NOT NULL REFERENCES measurement_nonces (nonce),
    key_id       TEXT NOT NULL,
    raw_digest   TEXT NOT NULL,
    measured_at  TIMESTAMPTZ NOT NULL,
    signature    TEXT NOT NULL,
    recorded_at  TIMESTAMPTZ NOT NULL,
    recorded_by  TEXT NOT NULL
);

COMMENT ON TABLE measurement_signatures IS
    'G0 T-1 (003f): the instrument or runner''s Ed25519 signature over a measurement statement '
    '(job, run, nonce, capability, instrument, raw digest, time). Relayed by the services, '
    'verified by the readers (lab_brain.security.measurement_provenance); SQL checks the shape.';

CREATE FUNCTION measurement_signatures_are_relayed_once() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'measurement_signatures is append-only: % refused (003f)', TG_OP
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM runs WHERE run_id = NEW.run_id AND job_id = NEW.job_id) THEN
        RAISE EXCEPTION 'measurement signature for run %: it is not the run of job %',
            NEW.run_id, NEW.job_id;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM measurement_nonces WHERE nonce = NEW.nonce
                    AND job_id = NEW.job_id) THEN
        RAISE EXCEPTION 'measurement signature for run %: nonce % was not issued for job %',
            NEW.run_id, NEW.nonce, NEW.job_id;
    END IF;
    NEW.recorded_at := clock_timestamp();
    NEW.recorded_by := session_user;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public;

CREATE TRIGGER measurement_signatures_are_relayed_once
    BEFORE INSERT OR UPDATE OR DELETE ON measurement_signatures
    FOR EACH ROW EXECUTE FUNCTION measurement_signatures_are_relayed_once();
