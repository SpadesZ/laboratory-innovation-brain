-- 003g_measurement_provenance_in_sql.sql
--
-- G0 round 6, residual T-1r (docs/audit/g0-boundary-round6-2026-11-24/REPORT.md).
--
-- THE GAP. `003f` gave the Python relation reader a measurement-provenance rule (an unsigned or
-- unverifiable measurement of an (instrument, capability) the owner enrolled a key for is not
-- support), and left the SQL readers of the same evidence without it, because PostgreSQL cannot
-- verify an Ed25519 signature. So SQL counted what Python refused (reproduced,
-- tests/e2e/test_g0_boundary_round6_postgres.py, evidence/reproduction_before.log):
--   T1 the projection refuses a history whose promotion counted such a measurement; `cwg_state`
--      read SUPPORTED;
--   T2 `cwg_evidence` (the SQL confirmation rule's support) listed the SUPPORTS;
--   T3 the `011z` gate accepted a decision snapshot counting it;
--   T4 `011l` accepted the cause as SUPPORTED;
--   T5 the strict mode was an environment variable of the services' own process, invisible to SQL
--      and changeable by whoever controls that process.
--
-- THE RULE, IN SQL, READ BY BOTH SIDES.
--   * `measurement_provenance_modes`: the owner's append-only setting, `enrolled` (no row: the
--     default) or `strict`; `measurement_provenance_mode()` is the latest. Python reads it from
--     here; the environment variable may only state the same mode (a disagreement is a
--     configuration error, never a weaker reading).
--   * `measurement_verifications`: the owner-run verifier's verdict on each relayed signature
--     (`lab-brain admin verify-measurements`, `security.measurement_provenance.verify_pending`),
--     owner only, append-only, one per run, bound to the signature it judged. SQL cannot check the
--     signature; it can check that the owner's verifier did, and re-check the structural parts
--     (the key, its scope, revocation before arrival).
--   * `measurement_run_status(run)`: VERIFIED, NOT_REQUIRED (no signature, `enrolled` mode, no key
--     ever enrolled for the pair), UNSIGNED, PENDING_VERIFICATION (signed, not yet verified), the
--     verifier's failure verdict, or a structural failure. Only VERIFIED and NOT_REQUIRED count.
--     Python's `MeasurementProvenance.run` gives the same answer: its own VERIFIED additionally
--     needs this one's, and an unsigned run is judged by the same mode and enrolment.
--   * `measurement_support_problem(project, attestations)`: why a SUPPORTS resting on these
--     attestations is not support, or NULL (an attestation with no run is not a measurement).
--
-- THE READERS. `cwg_evidence` leaves out a SUPPORTS that does not count (T2). `belief_replay`
-- refuses a history in which a counted (not owner-quarantined) event's decision counted such a
-- SUPPORTS, as `core.belief.verified_history` refuses it in Python (SUPPORT_UNVERIFIED): every
-- event reads HISTORY_REFUSED and nothing counts -- so `cwg_state`, `011l`, `012o` and `012n`,
-- which read `belief_replay`, follow (T1, T4). The `011z` gate refuses a snapshot counting one
-- (T3): `belief_snapshot_problem` is the 005f check followed by this one.
--
-- WHAT STAYS OPEN, STATED. The owner is the trust root: a VERIFIED verdict the owner wrote by hand
-- for a signature that does not verify is counted by SQL and refused by Python (Python re-verifies
-- the signature). Signing cannot show a lying sensor, a compromised runner host or a stolen key,
-- nor that the observation value extracted from the signed bytes is faithful.

CREATE TABLE measurement_provenance_modes (
    seq         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    mode        TEXT NOT NULL CHECK (mode IN ('enrolled', 'strict')),
    reason      TEXT NOT NULL CHECK (length(btrim(reason)) >= 10),
    actor_id    TEXT NOT NULL REFERENCES actors (actor_id),
    decided_at  TIMESTAMPTZ NOT NULL,
    recorded_by TEXT NOT NULL
);

CREATE TABLE measurement_verifications (
    run_id      TEXT PRIMARY KEY REFERENCES measurement_signatures (run_id),
    verdict     TEXT NOT NULL CHECK (verdict IN (
                    'VERIFIED', 'UNKNOWN_KEY', 'KEY_REVOKED', 'OUT_OF_SCOPE', 'NONCE_MISMATCH',
                    'DIGEST_MISMATCH', 'TIME_MISMATCH', 'BAD_SIGNATURE')),
    -- The signature judged, copied from `measurement_signatures` by the guard.
    key_id      TEXT NOT NULL,
    signature   TEXT NOT NULL,
    detail      TEXT NOT NULL,
    verifier    TEXT NOT NULL CHECK (btrim(verifier) <> ''),
    actor_id    TEXT NOT NULL REFERENCES actors (actor_id),
    verified_at TIMESTAMPTZ NOT NULL,
    recorded_by TEXT NOT NULL
);

COMMENT ON TABLE measurement_verifications IS
    'G0 round 6 (003g): the owner-run verifier''s verdict on a relayed measurement signature. Owner '
    'only, append-only, one per run; the SQL readers count a signed measurement only on VERIFIED.';

CREATE FUNCTION measurement_provenance_is_the_owners() RETURNS TRIGGER AS $$
DECLARE
    v_owner OID;
    v_sig   measurement_signatures%ROWTYPE;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION '% is append-only: % refused; a later decision is a new row (003g)',
            TG_TABLE_NAME, TG_OP
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    SELECT relowner INTO v_owner FROM pg_class WHERE oid = TG_RELID;
    IF NOT pg_has_role(current_user, v_owner, 'MEMBER') THEN
        RAISE EXCEPTION
            '%: the measurement-provenance mode and the verifier''s verdicts are the schema '
            'owner''s, not %''s; a verdict or a mode the services could write would let them count '
            'their own measurements (003g)', TG_TABLE_NAME, current_user
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF TG_TABLE_NAME = 'measurement_verifications' THEN
        SELECT * INTO v_sig FROM measurement_signatures WHERE run_id = NEW.run_id;
        NEW.key_id := v_sig.key_id;
        NEW.signature := v_sig.signature;
        NEW.verified_at := clock_timestamp();
    ELSE
        NEW.decided_at := clock_timestamp();
    END IF;
    NEW.recorded_by := session_user;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public;

CREATE TRIGGER measurement_provenance_modes_are_the_owners
    BEFORE INSERT OR UPDATE OR DELETE ON measurement_provenance_modes
    FOR EACH ROW EXECUTE FUNCTION measurement_provenance_is_the_owners();
CREATE TRIGGER measurement_verifications_are_the_owners
    BEFORE INSERT OR UPDATE OR DELETE ON measurement_verifications
    FOR EACH ROW EXECUTE FUNCTION measurement_provenance_is_the_owners();

-- The owner's current mode; `enrolled` until the owner records another.
CREATE FUNCTION measurement_provenance_mode() RETURNS TEXT AS $$
    SELECT coalesce(
        (SELECT mode FROM measurement_provenance_modes ORDER BY seq DESC LIMIT 1), 'enrolled')
$$ LANGUAGE sql STABLE SET search_path = pg_catalog, public;

-- `MeasurementProvenance.run`, as far as SQL can judge it (the signature itself: the verdict).
CREATE FUNCTION measurement_run_status(p_run_id TEXT) RETURNS TEXT AS $$
DECLARE
    v_run     runs%ROWTYPE;
    v_sig     measurement_signatures%ROWTYPE;
    v_ver     measurement_verifications%ROWTYPE;
    v_key     measurement_signing_keys%ROWTYPE;
    v_revoked TIMESTAMPTZ;
BEGIN
    SELECT * INTO v_run FROM runs WHERE run_id = p_run_id;
    IF NOT FOUND THEN
        RETURN 'NO_RUN';
    END IF;
    SELECT * INTO v_sig FROM measurement_signatures WHERE run_id = p_run_id;
    IF NOT FOUND THEN
        IF measurement_provenance_mode() = 'strict' OR EXISTS (
            SELECT 1 FROM measurement_signing_keys k
             WHERE k.instrument_id = v_run.backend_id AND v_run.capability_id = ANY (k.capability_ids)
        ) THEN
            RETURN 'UNSIGNED';
        END IF;
        RETURN 'NOT_REQUIRED';
    END IF;
    IF v_sig.job_id IS DISTINCT FROM v_run.job_id OR NOT EXISTS (
        SELECT 1 FROM measurement_nonces n WHERE n.nonce = v_sig.nonce AND n.job_id = v_run.job_id
    ) THEN
        RETURN 'NONCE_MISMATCH';
    END IF;
    SELECT * INTO v_key FROM measurement_signing_keys WHERE key_id = v_sig.key_id;
    IF NOT FOUND THEN
        RETURN 'UNKNOWN_KEY';
    END IF;
    SELECT revoked_at INTO v_revoked FROM measurement_signing_key_revocations
     WHERE key_id = v_sig.key_id;
    IF v_revoked IS NOT NULL AND v_revoked <= v_sig.recorded_at THEN
        RETURN 'KEY_REVOKED';
    END IF;
    IF v_key.instrument_id <> v_run.backend_id
       OR NOT (v_run.capability_id = ANY (v_key.capability_ids)) THEN
        RETURN 'OUT_OF_SCOPE';
    END IF;
    SELECT * INTO v_ver FROM measurement_verifications WHERE run_id = p_run_id;
    IF NOT FOUND THEN
        RETURN 'PENDING_VERIFICATION';
    END IF;
    IF v_ver.key_id IS DISTINCT FROM v_sig.key_id
       OR v_ver.signature IS DISTINCT FROM v_sig.signature THEN
        RETURN 'BAD_SIGNATURE';
    END IF;
    RETURN v_ver.verdict;
END;
$$ LANGUAGE plpgsql STABLE SET search_path = pg_catalog, public;

COMMENT ON FUNCTION measurement_run_status(TEXT) IS
    'G0 round 6 (003g): a run''s measurement provenance as SQL can judge it; VERIFIED and '
    'NOT_REQUIRED count. Held equal to MeasurementProvenance.run by the PostgreSQL suite.';

-- Why a SUPPORTS resting on these attestations is not support on measurement provenance, or NULL.
CREATE FUNCTION measurement_support_problem(p_project TEXT, p_attestation_ids TEXT[])
RETURNS TEXT AS $$
    SELECT format('%s: measurement provenance %s (run %s)', x.attestation_id, x.status, x.run_id)
      FROM (
          SELECT a.attestation_id, coalesce(a.run_id, o.run_id) AS run_id,
                 measurement_run_status(coalesce(a.run_id, o.run_id)) AS status
            FROM unnest(coalesce(p_attestation_ids, '{}')) ref (id)
            JOIN attestations a ON a.attestation_id = ref.id AND a.project_id = p_project
            LEFT JOIN observations o
              ON o.observation_id = a.observation_id AND o.project_id = a.project_id
           WHERE coalesce(a.run_id, o.run_id) IS NOT NULL
      ) x
     WHERE x.status NOT IN ('VERIFIED', 'NOT_REQUIRED')
     ORDER BY x.attestation_id COLLATE "C"
     LIMIT 1
$$ LANGUAGE sql STABLE SET search_path = pg_catalog, public;

-- ---------------------------------------------------------------------------------------------
-- The readers
-- ---------------------------------------------------------------------------------------------

-- `012p`'s list of admitted SUPPORTS/CONTRADICTS relations; 003g: a SUPPORTS that does not count
-- on measurement provenance is not admitted (`SqlRelationStore.admitted_for_subject`).
CREATE OR REPLACE FUNCTION cwg_evidence(p_project TEXT, p_hypothesis TEXT)
RETURNS TABLE (
    relation_id TEXT, relation_type TEXT, from_entity_id TEXT,
    warrant TEXT, ref TEXT, identifies TEXT
) AS $$
    SELECT r.relation_id, r.relation_type, r.from_entity_id, w.warrant, w.ref, w.identifies
      FROM relation_judgments r
     CROSS JOIN LATERAL cwg_relation_warrant(r) w
     WHERE r.project_id = p_project AND r.to_entity_id = p_hypothesis AND r.valid_to IS NULL
       AND r.relation_type IN ('SUPPORTS', 'CONTRADICTS')
       AND (r.relation_type <> 'SUPPORTS'
            OR measurement_support_problem(r.project_id, r.supporting_attestation_ids) IS NULL)
$$ LANGUAGE sql STABLE;

-- Why the stored history of a subject is refused on measurement provenance, or NULL: the first
-- event (in replay order) the owner has not quarantined whose decision counted a SUPPORTS of the
-- subject that does not count now (`verified_history`'s SUPPORT_UNVERIFIED).
CREATE FUNCTION belief_history_problem(p_project TEXT, p_target TEXT) RETURNS TEXT AS $$
    SELECT format('event %s: its decision %s counts %s as SUPPORTS, which is not support now: %s',
                  e.event_id, d.decision_id, rel ->> 'relation_id', p.problem)
      FROM belief_revision_events e
      JOIN belief_transition_decisions d ON d.decision_id = e.authorization_decision_id
     CROSS JOIN LATERAL jsonb_array_elements(
           coalesce(d.decision_input_snapshot::jsonb -> 'admitted_relations', '[]')) rel
     CROSS JOIN LATERAL (
         SELECT measurement_support_problem(p_project, ARRAY(
                    SELECT jsonb_array_elements_text(
                        coalesce(rel -> 'supporting_attestation_ids', '[]')))) AS problem
     ) p
     WHERE e.project_id = p_project AND e.target_id = p_target
       AND rel ->> 'relation_type' = 'SUPPORTS'
       AND NOT EXISTS (SELECT 1 FROM belief_event_exclusions x
                        WHERE x.event_id = e.event_id AND x.reason = 'OWNER_QUARANTINED')
       AND p.problem IS NOT NULL
     ORDER BY e.occurred_at, e.event_id COLLATE "C"
     LIMIT 1
$$ LANGUAGE sql STABLE SET search_path = pg_catalog, public;

-- `005f`'s replay; 003g: a refused history counts nothing (every event HISTORY_REFUSED unless
-- excluded for its own reason), as Python's `verified_history` refuses it whole.
CREATE OR REPLACE FUNCTION belief_replay(p_project TEXT, p_target TEXT)
RETURNS TABLE (
    event_id    TEXT,
    occurred_at TIMESTAMPTZ,
    from_state  TEXT,
    to_state    TEXT,
    counted     BOOLEAN,
    skip_reason TEXT
) AS $$
#variable_conflict use_column
DECLARE
    v_state   TEXT;
    v_row     RECORD;
    v_refused BOOLEAN := belief_history_problem(p_project, p_target) IS NOT NULL;
BEGIN
    FOR v_row IN
        SELECT e.event_id AS id, e.occurred_at AS at, e.from_state AS f, e.to_state AS t,
               x.reason AS excluded
          FROM belief_revision_events e
          LEFT JOIN belief_event_exclusions x ON x.event_id = e.event_id
         WHERE e.project_id = p_project AND e.target_id = p_target
         ORDER BY e.occurred_at, e.event_id COLLATE "C"
    LOOP
        event_id := v_row.id;
        occurred_at := v_row.at;
        from_state := v_row.f;
        to_state := v_row.t;
        IF v_row.excluded IS NOT NULL THEN
            counted := FALSE;
            skip_reason := v_row.excluded;
        ELSIF v_refused THEN
            counted := FALSE;
            skip_reason := 'HISTORY_REFUSED';
        ELSIF v_row.f IS DISTINCT FROM v_state THEN
            counted := FALSE;
            skip_reason := 'PREDECESSOR_MISSING';
        ELSE
            counted := TRUE;
            skip_reason := NULL;
            v_state := v_row.t;
        END IF;
        RETURN NEXT;
    END LOOP;
END;
$$ LANGUAGE plpgsql STABLE SET search_path = pg_catalog, public;

-- The `011z` gate's snapshot check: `005f`'s, then (003g) no SUPPORTS the snapshot counts may
-- rest on a measurement whose provenance does not count.
ALTER FUNCTION belief_snapshot_problem(TEXT, TEXT, JSONB)
    RENAME TO belief_snapshot_problem_005f;

CREATE FUNCTION belief_snapshot_problem(
    p_project_id TEXT, p_subject_id TEXT, p_snapshot JSONB
) RETURNS TEXT AS $$
DECLARE
    v_problem  TEXT := belief_snapshot_problem_005f(p_project_id, p_subject_id, p_snapshot);
    v_relation JSONB;
BEGIN
    IF v_problem IS NOT NULL THEN
        RETURN v_problem;
    END IF;
    FOR v_relation IN
        SELECT r FROM jsonb_array_elements(coalesce(p_snapshot -> 'admitted_relations', '[]')) r
         WHERE r ->> 'relation_type' = 'SUPPORTS'
    LOOP
        v_problem := measurement_support_problem(p_project_id, ARRAY(
            SELECT jsonb_array_elements_text(
                coalesce(v_relation -> 'supporting_attestation_ids', '[]'))));
        IF v_problem IS NOT NULL THEN
            RETURN format('relation %s is not support now: %s', v_relation ->> 'relation_id',
                          v_problem);
        END IF;
    END LOOP;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE SET search_path = pg_catalog, public;
