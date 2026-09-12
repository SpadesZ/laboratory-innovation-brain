-- 008_conditions.sql
--
-- Versioned condition schema registry (§6.19, EVI-005).
--
-- Applied before 003 despite the higher number: observations and attestations carry a foreign
-- key to a registered schema version, so the registry must exist first. The numbering follows
-- Appendix A's canonical list, which is an index rather than an application order.
--
-- The point of the foreign key is that EVI-005 becomes a storage guarantee. An attestation
-- referencing an unregistered condition schema version cannot be inserted, so unauditable
-- condition records cannot accumulate and be discovered later.

CREATE TABLE condition_schemas (
    domain             TEXT NOT NULL,
    schema_id          TEXT NOT NULL,
    version            TEXT NOT NULL,
    json_schema        JSONB NOT NULL,
    -- Separate from `version`: comparison rules can be corrected without the field set
    -- changing, and a ConditionMatch must stay attributable to the rules that produced it.
    comparator_version TEXT NOT NULL,
    registered_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (domain, schema_id, version),
    CONSTRAINT condition_schemas_version_is_semver
        CHECK (version ~ '^[0-9]+\.[0-9]+\.[0-9]+$'),
    CONSTRAINT condition_schemas_naming
        CHECK (domain ~ '^[a-z0-9_]+$' AND schema_id ~ '^[a-z0-9_]+$')
);

-- The qualified reference carried by every condition-aware record: domain/schema_id@version.
-- A generated column so the application and the database cannot disagree on the format.
ALTER TABLE condition_schemas
    ADD COLUMN schema_ref TEXT
    GENERATED ALWAYS AS (domain || '/' || schema_id || '@' || version) STORED;

CREATE UNIQUE INDEX condition_schemas_ref_key ON condition_schemas (schema_ref);

-- ConditionMatch results (§17.19). Persisted rather than recomputed because a belief transition
-- authorised under one comparator version must remain explainable after the comparator changes.
CREATE TABLE condition_matches (
    condition_match_id       TEXT PRIMARY KEY,
    state                    TEXT NOT NULL
        CHECK (state IN ('EXACT', 'COMPATIBLE', 'PARTIAL', 'INCOMPATIBLE', 'UNKNOWN')),
    matched_fields           TEXT[] NOT NULL DEFAULT '{}',
    mismatches               JSONB NOT NULL DEFAULT '[]'::jsonb,
    unknowns                 TEXT[] NOT NULL DEFAULT '{}',
    tolerance_policy_version TEXT NOT NULL,
    schema_ref               TEXT NOT NULL REFERENCES condition_schemas (schema_ref),
    rationale_ref            TEXT,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- The state must not contradict the findings recorded beside it; otherwise a gate reading
    -- only `state` would be misled by a comparator bug.
    CONSTRAINT condition_matches_exact_has_no_findings
        CHECK (state <> 'EXACT'
               OR (jsonb_array_length(mismatches) = 0 AND cardinality(unknowns) = 0)),
    CONSTRAINT condition_matches_incompatible_has_mismatch
        CHECK (state <> 'INCOMPATIBLE' OR jsonb_array_length(mismatches) > 0),
    CONSTRAINT condition_matches_unknown_has_unknowns
        CHECK (state <> 'UNKNOWN' OR cardinality(unknowns) > 0)
);

CREATE INDEX condition_matches_schema_idx ON condition_matches (schema_ref);
