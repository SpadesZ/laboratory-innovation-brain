-- 004a_evidence_bundles.sql
--
-- EvidenceBundle persistence (§17.14.1, EVI-006).
--
-- §22's Bundle Reproducibility criterion is "任一 LLM scientific output 可追到 canonical
-- EvidenceBundle hash，重建相同 ordered evidence set". Rebuilding requires the bundle to be stored:
-- a hash nobody can look up proves only that two hashes differ, never what either one contained.
--
-- The ordered attestation list is a separate table rather than an array column. The order is part
-- of bundle identity, and a child table with an explicit position lets the database enforce that
-- positions are contiguous from zero and that no attestation appears twice -- both of which an
-- array would leave to the application.
--
-- NUMBERING: 004a, not 005. Appendix A reserves 001-012 and 005 is
-- 005_epistemic_events_transition_policies.sql. The `a` suffix marks an addition beyond Appendix
-- A's index rather than a new canonical migration, the same convention as 008a.

CREATE TABLE evidence_bundles (
    bundle_id                 TEXT PRIMARY KEY,
    schema_version            INTEGER NOT NULL,

    research_intent           TEXT NOT NULL,
    -- Ordinal, not a probability: §8.1 rules out uncalibrated numbers in v1.
    stakes                    TEXT,

    query_text                TEXT NOT NULL,
    -- Stored so a bundle can be matched without carrying the query, which may itself be
    -- restricted (§14.3 forbids sending private identifiers outbound).
    query_hash                TEXT NOT NULL,

    source_policy_id          TEXT NOT NULL,
    source_policy_version     TEXT NOT NULL,

    condition_filter          JSONB NOT NULL DEFAULT '{}'::jsonb,
    condition_schema_versions JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_snapshot_refs      TEXT[] NOT NULL DEFAULT '{}',

    retrieval_trace_id        TEXT,
    project_id                TEXT NOT NULL REFERENCES projects (project_id),
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Derived in the application from the canonical (RFC 8785) serialization of the declared hash
    -- fields. The database cannot recompute it -- doing so would mean reimplementing JCS in
    -- plpgsql, and two implementations of a canonicalisation standard is exactly how the hashes
    -- start disagreeing. The format is constrained instead, and the repository verifies the value
    -- against a freshly computed one on read.
    canonical_hash            TEXT NOT NULL,

    CONSTRAINT evidence_bundles_hash_format
        CHECK (canonical_hash ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT evidence_bundles_query_hash_format
        CHECK (query_hash ~ '^sha256:[0-9a-f]{64}$')
);

-- Not unique: the same retrieval legitimately recurs, and each occurrence is its own bundle row
-- with its own id and timestamp. Indexed because looking a bundle up by hash is the primary access
-- path for provenance ("what did the model see when it said this?").
CREATE INDEX evidence_bundles_canonical_hash_idx ON evidence_bundles (canonical_hash);
CREATE INDEX evidence_bundles_project_idx ON evidence_bundles (project_id, created_at DESC);
CREATE INDEX evidence_bundles_intent_idx ON evidence_bundles (research_intent);

CREATE TABLE evidence_bundle_members (
    bundle_id      TEXT NOT NULL REFERENCES evidence_bundles (bundle_id) ON DELETE CASCADE,
    -- Zero-based rank. Part of bundle identity: two retrievals returning the same evidence in a
    -- different order are different bundles.
    position       INTEGER NOT NULL CHECK (position >= 0),
    attestation_id TEXT NOT NULL REFERENCES attestations (attestation_id),

    PRIMARY KEY (bundle_id, position),
    -- One attestation may not appear twice in one bundle: that would double-count it as evidence
    -- before EVI-004's independence resolution is ever reached.
    CONSTRAINT evidence_bundle_members_no_duplicates UNIQUE (bundle_id, attestation_id)
);

CREATE INDEX evidence_bundle_members_attestation_idx
    ON evidence_bundle_members (attestation_id);

-- Positions must be contiguous from zero. A gap would mean the stored order cannot be replayed,
-- so the bundle would no longer reconstruct the ordered evidence set §22 requires. Enforced as a
-- constraint trigger deferred to commit, since the rows arrive one INSERT at a time.
CREATE FUNCTION lab_brain_validate_bundle_positions() RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    member_count    INTEGER;
    max_position    INTEGER;
    target_bundle   TEXT;
BEGIN
    target_bundle := coalesce(NEW.bundle_id, OLD.bundle_id);

    SELECT count(*), coalesce(max(position), -1)
      INTO member_count, max_position
      FROM evidence_bundle_members
     WHERE bundle_id = target_bundle;

    -- An emptied bundle is legitimate: "we searched and found nothing" is a reproducible result.
    IF member_count = 0 THEN
        RETURN NULL;
    END IF;

    IF max_position <> member_count - 1 THEN
        RAISE EXCEPTION
            'evidence bundle % has % members but highest position %; positions must be '
            'contiguous from 0 or the ordered evidence set cannot be replayed (EVI-006)',
            target_bundle, member_count, max_position
            USING ERRCODE = 'check_violation';
    END IF;

    RETURN NULL;
END;
$$;

COMMENT ON FUNCTION lab_brain_validate_bundle_positions() IS
    'EVI-006: bundle member positions must be contiguous from 0 so the ordered evidence set is '
    'replayable. Deferred to commit because members are inserted one row at a time.';

CREATE CONSTRAINT TRIGGER evidence_bundle_members_positions_contiguous
    AFTER INSERT OR UPDATE OR DELETE ON evidence_bundle_members
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION lab_brain_validate_bundle_positions();
