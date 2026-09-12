-- 003_claims_observations_attestations.sql
--
-- The Claim / Observation / Attestation separation (§6.2, ADR-0003).
--
-- What the schema is shaped to prevent: one measurement cited by five papers reading as five
-- independent supports. Claim is proposition identity; Observation is an internal backend fact
-- wired to its Run or Artifact; Attestation is a named source's witness. Collapsing any two of
-- them systematically inflates corroboration (EVI-004).
--
-- Note the absence: no support_targets, no contradict_targets, no evidence_for. Support lives
-- only in relation_judgments (004). A parallel array here would be a second source of truth
-- that nothing keeps in step with the relation table (SYS-001).

CREATE TABLE claims (
    claim_id               TEXT PRIMARY KEY,
    normalized_proposition TEXT NOT NULL,
    domain                 TEXT,
    scope                  JSONB NOT NULL DEFAULT '{}'::jsonb,
    identity_status        TEXT NOT NULL DEFAULT 'PROVISIONAL'
        CHECK (identity_status IN ('PROVISIONAL', 'RESOLVED', 'MERGED', 'DISPUTED')),
    merged_into_claim_id   TEXT REFERENCES claims (claim_id),
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT claims_not_merged_into_self
        CHECK (merged_into_claim_id IS NULL OR merged_into_claim_id <> claim_id),
    -- A MERGED claim with no target silently drops every attestation pointing at it.
    CONSTRAINT claims_merge_target_required
        CHECK ((identity_status = 'MERGED') = (merged_into_claim_id IS NOT NULL))
);

CREATE INDEX claims_proposition_idx ON claims (normalized_proposition);
CREATE INDEX claims_domain_idx ON claims (domain) WHERE domain IS NOT NULL;

CREATE TABLE observations (
    observation_id            TEXT PRIMARY KEY,
    -- Exactly one origin. With neither, the value cannot be reproduced; with both, it is
    -- ambiguous which one to replay. run_id has no FK yet -- runs arrive in migration 006.
    run_id                    TEXT,
    artifact_id               TEXT REFERENCES artifacts (artifact_id),

    metric_or_event           TEXT NOT NULL,
    value_ref                 TEXT,
    value_numeric             DOUBLE PRECISION,
    value_text                TEXT,
    unit                      TEXT,

    conditions                JSONB NOT NULL DEFAULT '{}'::jsonb,
    conditions_schema_version TEXT NOT NULL REFERENCES condition_schemas (schema_ref),
    -- Extractor identity and version. Without it a number cannot be recomputed, and
    -- DOM-SP-002's shared-extractor guarantee is unverifiable.
    method_ref                TEXT NOT NULL,

    project_id                TEXT NOT NULL REFERENCES projects (project_id),
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT observations_exactly_one_origin
        CHECK ((run_id IS NOT NULL)::int + (artifact_id IS NOT NULL)::int = 1)
);

CREATE INDEX observations_run_idx ON observations (run_id) WHERE run_id IS NOT NULL;
CREATE INDEX observations_artifact_idx ON observations (artifact_id) WHERE artifact_id IS NOT NULL;
CREATE INDEX observations_metric_idx ON observations (metric_or_event);
CREATE INDEX observations_conditions_gin ON observations USING gin (conditions);

CREATE TABLE attestations (
    attestation_id            TEXT PRIMARY KEY,

    -- Exactly one subject: a proposition or a concrete observation. Which of the two it is
    -- determines how corroboration counts it.
    claim_id                  TEXT REFERENCES claims (claim_id),
    observation_id            TEXT REFERENCES observations (observation_id),

    -- P3 / EVI-003. INFERRED is stored, never derived from the source kind, so the admission
    -- gate has something concrete to refuse. It can never be promoted to a factual type.
    epistemic_type            TEXT NOT NULL
        CHECK (epistemic_type IN ('OBSERVED', 'SIMULATED', 'MEASURED',
                                  'REPORTED', 'DERIVED', 'INFERRED')),

    -- Exactly one source. "Which source said this" is the entire purpose of the row.
    source_artifact_id        TEXT REFERENCES artifacts (artifact_id),
    source_work_id            TEXT REFERENCES source_works (source_work_id),
    run_id                    TEXT,

    -- A claim without a locator cannot be re-checked by a human.
    locator                   TEXT NOT NULL,

    conditions                JSONB NOT NULL DEFAULT '{}'::jsonb,
    conditions_schema_version TEXT NOT NULL REFERENCES condition_schemas (schema_ref),
    -- Per-field status (§6.3, §17.9). UNKNOWN / NOT_REPORTED are what an extractor emits
    -- instead of guessing a plausible value (P14 / EVI-002).
    field_states              JSONB NOT NULL DEFAULT '{}'::jsonb,

    units                     TEXT,
    uncertainty               JSONB,
    method                    JSONB NOT NULL DEFAULT '{}'::jsonb,

    extraction_status         TEXT NOT NULL DEFAULT 'STAGE_A_METADATA'
        CHECK (extraction_status IN ('STAGE_A_METADATA', 'STAGE_B_STRUCTURED',
                                     'STAGE_C_DEEP', 'STAGE_D_HUMAN_VERIFIED')),
    verification_status       TEXT NOT NULL DEFAULT 'UNVERIFIED'
        CHECK (verification_status IN ('UNVERIFIED', 'MACHINE_CHECKED',
                                       'HUMAN_VERIFIED', 'DISPUTED')),
    -- Domain-supplied, compared by AuthorityPolicy (ADR-0007). No CHECK list: core must not
    -- know a domain's authority vocabulary, and must never order these values itself.
    authority_class           TEXT,

    project_id                TEXT NOT NULL REFERENCES projects (project_id),
    -- §6.18 contamination rollback selects by extractor version. Indexed for that reason.
    extractor_version         TEXT NOT NULL,
    extraction_provenance     JSONB NOT NULL,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT attestations_exactly_one_subject
        CHECK ((claim_id IS NOT NULL)::int + (observation_id IS NOT NULL)::int = 1),
    CONSTRAINT attestations_exactly_one_source
        CHECK ((source_artifact_id IS NOT NULL)::int
               + (source_work_id IS NOT NULL)::int
               + (run_id IS NOT NULL)::int = 1),
    -- Two places record the extractor version; disagreement would make quarantine-by-version
    -- miss rows.
    CONSTRAINT attestations_extractor_version_agrees
        CHECK (extraction_provenance ->> 'extractor_version' = extractor_version)
);

CREATE INDEX attestations_claim_idx ON attestations (claim_id) WHERE claim_id IS NOT NULL;
CREATE INDEX attestations_observation_idx ON attestations (observation_id)
    WHERE observation_id IS NOT NULL;
CREATE INDEX attestations_source_work_idx ON attestations (source_work_id)
    WHERE source_work_id IS NOT NULL;
CREATE INDEX attestations_epistemic_type_idx ON attestations (epistemic_type);
CREATE INDEX attestations_extractor_idx ON attestations
    ((extraction_provenance ->> 'extractor_id'), extractor_version);
CREATE INDEX attestations_conditions_gin ON attestations USING gin (conditions);
