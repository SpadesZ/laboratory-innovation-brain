-- 010c_outcome_spaces_benchmark_policies.sql
--
-- M3 / LLM-002, VER-004/VER-008 / §17.19.2. The benchmark half of Appendix A's `010` slot
-- (`010_review_observability_benchmark_policies.sql`), which `010a`'s header left for §17.19.2.
--
-- TWO TABLES, BOUND FIELD-FOR-FIELD. `schema_drift` binds both to §17.19.2's blocks, so a column
-- added here that the spec does not declare -- or a declared field left out -- fails CI.
--
-- WHY BENCHMARK POLICIES ARE ROWS. §15.4: 門檻由校準產生 ... hard gates 必須引用版本化的
-- BenchmarkPolicy，且校準證據可追溯。校準前不得任意 hard-code 門檻數字. A threshold that lives in
-- code has no calibration record by construction, and one that lives in a config file has one only
-- by convention. A row with NOT NULL `calibrated_at`, a positive `sample_size` and a non-empty
-- `calibration_artifact_refs` cannot be written without them -- so "calibrated before enforced" is
-- a property of the table, and a gate that can only be armed from a row inherits it.
--
-- VERSIONS ARE IMMUTABLE; `active` IS THE ONE THING THAT MOVES. Re-calibrating is a new version.
-- Editing a calibrated threshold in place would silently re-judge every decision already gated
-- against the old one, with nothing recording that the threshold changed. Deactivating a version is
-- a state change, not an edit, and at most one version per (domain, benchmark set, metric) is
-- active -- two active thresholds for one gate would make the gate's answer depend on which row a
-- reader found first.
--
-- OUTCOME SPACES ARE DECLARED, VERSIONED AND IMMUTABLE for VER-004's reason: "Planner MUST NOT
-- invent outcomes". A space that could be edited in place would let a prediction admitted against
-- one membership be evaluated against another, under the same version string.

-- ---------------------------------------------------------------------------------------------
-- 1. OutcomeSpace (§17.19.2)
-- ---------------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS outcome_spaces (
    outcome_space_id      TEXT NOT NULL,
    version               TEXT NOT NULL,
    domain                TEXT NOT NULL,
    action_type           TEXT NOT NULL,
    hypothesis_type       TEXT,
    schema_version        TEXT,
    outcomes              TEXT[] NOT NULL,
    order_or_metric_ref   TEXT,
    explicit_exclusions   TEXT[] NOT NULL DEFAULT '{}',
    validity_bounds       JSONB NOT NULL DEFAULT '{}'::jsonb,

    PRIMARY KEY (outcome_space_id, version),
    CONSTRAINT outcome_spaces_declares_something CHECK (cardinality(outcomes) >= 1),
    -- An exclusion naming a non-member is a rule about nothing (see `OutcomeSpace`).
    CONSTRAINT outcome_spaces_exclusions_are_members CHECK (explicit_exclusions <@ outcomes),
    CONSTRAINT outcome_spaces_identity_present CHECK (
        btrim(outcome_space_id) <> '' AND btrim(version) <> '' AND btrim(domain) <> ''
    )
);

CREATE FUNCTION outcome_spaces_are_immutable() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        'outcome space %@% is immutable; a changed membership is a new version. Editing it in '
        'place would evaluate predictions admitted under one membership against another (VER-004)',
        OLD.outcome_space_id, OLD.version;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER outcome_spaces_are_immutable_trg
    BEFORE UPDATE OR DELETE ON outcome_spaces
    FOR EACH ROW EXECUTE FUNCTION outcome_spaces_are_immutable();

-- ---------------------------------------------------------------------------------------------
-- 2. BenchmarkPolicy (§17.19.2)
-- ---------------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS benchmark_policies (
    policy_id                  TEXT NOT NULL,
    version                    TEXT NOT NULL,
    domain                     TEXT NOT NULL,
    benchmark_set_id           TEXT NOT NULL,
    metric_key                 TEXT NOT NULL,
    threshold                  NUMERIC NOT NULL,
    direction                  TEXT CHECK (direction IN ('AT_LEAST', 'AT_MOST')),
    calibrated_at              TIMESTAMPTZ NOT NULL,
    sample_size                INTEGER NOT NULL CHECK (sample_size >= 1),
    calibration_artifact_refs  TEXT[] NOT NULL,
    active                     BOOLEAN NOT NULL DEFAULT FALSE,

    PRIMARY KEY (policy_id, version),
    CONSTRAINT benchmark_policies_calibration_is_traceable
        CHECK (cardinality(calibration_artifact_refs) >= 1),
    CONSTRAINT benchmark_policies_identity_present CHECK (
        btrim(policy_id) <> '' AND btrim(version) <> '' AND btrim(domain) <> ''
        AND btrim(benchmark_set_id) <> '' AND btrim(metric_key) <> ''
    ),
    -- NaN is a NUMERIC value in PostgreSQL and compares equal to itself; a NaN threshold would
    -- pass or fail everything depending on the operator, which is a gate with no calibration.
    CONSTRAINT benchmark_policies_threshold_is_finite CHECK (threshold <> 'NaN'::numeric)
);

-- At most one active version per gate.
CREATE UNIQUE INDEX IF NOT EXISTS benchmark_policies_one_active
    ON benchmark_policies (domain, benchmark_set_id, metric_key)
    WHERE active;

CREATE FUNCTION benchmark_policies_versions_are_immutable() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION
            'benchmark policy %@% cannot be deleted; a gate decision that cited it would lose the '
            'threshold it was judged against (LLM-002)', OLD.policy_id, OLD.version;
    END IF;
    IF (NEW.policy_id, NEW.version, NEW.domain, NEW.benchmark_set_id, NEW.metric_key,
        NEW.threshold, NEW.direction, NEW.calibrated_at, NEW.sample_size,
        NEW.calibration_artifact_refs)
       IS DISTINCT FROM
       (OLD.policy_id, OLD.version, OLD.domain, OLD.benchmark_set_id, OLD.metric_key,
        OLD.threshold, OLD.direction, OLD.calibrated_at, OLD.sample_size,
        OLD.calibration_artifact_refs) THEN
        RAISE EXCEPTION
            'benchmark policy %@% is immutable except for `active`; a re-calibration is a new '
            'version. Editing a calibrated threshold in place re-judges every decision already '
            'gated against it, silently (LLM-002, §15.4)', OLD.policy_id, OLD.version;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER benchmark_policies_versions_are_immutable_trg
    BEFORE UPDATE OR DELETE ON benchmark_policies
    FOR EACH ROW EXECUTE FUNCTION benchmark_policies_versions_are_immutable();

COMMENT ON TABLE benchmark_policies IS
    'LLM-002 / §17.19.2. A hard gate threshold, with the benchmark that produced it. No row, no '
    'hard gate: calibration evidence is NOT NULL here, so an uncalibrated threshold is unstorable.';
