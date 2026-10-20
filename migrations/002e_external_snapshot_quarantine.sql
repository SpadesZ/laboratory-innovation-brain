-- 002e_external_snapshot_quarantine.sql
--
-- M5 / GH-002, upgrade safety. `002d` checks every NEW snapshot against the access scope it names;
-- it does not look at rows written before it, and some of those were written under the model the
-- review found vulnerable -- a project's request served by another project's connector, stored
-- under that other project's policy, with no scope recorded anywhere. Such a row cannot be told
-- apart from a legitimate one by looking at it, so it may not go on being trusted by default.
--
-- FAIL CLOSED ON UPGRADE. Every snapshot that exists when this migration runs is checked by the
-- SAME rule `002d` applies to new writes, against the scopes recorded by then:
--
--     no scope named, PUBLIC material         coherent (no authorization was involved)
--     no scope named, private material        PRIVATE_WITHOUT_SCOPE
--     a scope named that was never recorded   SCOPE_NOT_RECORDED   (every pre-`002d` GitHub row)
--     a scope of another project / provider   SCOPE_OF_ANOTHER_PROJECT
--     private material off the allowlist      NOT_ON_ALLOWLIST
--
-- and every row that is not provably coherent is QUARANTINED: recorded in
-- `external_snapshot_quarantine` with its reason. The snapshot row itself is untouched -- it is
-- provenance, append-only, and what was read stays re-readable -- but it no longer counts:
--
--     cache       a quarantined snapshot is never served as a cache hit; a fresh read under the
--                 project's own scope supersedes it (the cache key admits one TRUSTED row)
--     admission   no attestation may be admitted from it (`attestations`)
--     use         an attestation already admitted from it cannot be cited by a new relation, a new
--                 evidence bundle or a new belief event
--     replay      `external_quarantined_attestations` is the §6.18 selection: the attestations to
--                 quarantine when replaying belief events, so events they triggered before the
--                 upgrade are skipped rather than silently kept
--
-- Quarantine is append-only and any writer may add to it (quarantining more is the fail-safe
-- direction); nothing releases a row. A project re-establishes trust by reading again under its own
-- scope, which is a new snapshot with its own provenance.
--
-- The cache key moves from a UNIQUE constraint to a trigger, because "one TRUSTED snapshot per
-- (project, provider, pinned locator)" depends on the quarantine table, which a unique index cannot
-- read. The trigger serialises same-key inserts with a transaction-scoped advisory lock, so two
-- concurrent writers cannot both pass the check.

CREATE TABLE IF NOT EXISTS external_snapshot_quarantine (
    snapshot_id     TEXT PRIMARY KEY REFERENCES external_snapshots (snapshot_id),
    project_id      TEXT NOT NULL REFERENCES projects (project_id),
    reason_code     TEXT NOT NULL CHECK (reason_code IN (
                        'PRIVATE_WITHOUT_SCOPE', 'SCOPE_NOT_RECORDED', 'SCOPE_OF_ANOTHER_PROJECT',
                        'NOT_ON_ALLOWLIST', 'QUARANTINED_BY_OPERATOR')),
    quarantined_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS external_snapshot_quarantine_project_idx
    ON external_snapshot_quarantine (project_id);

CREATE OR REPLACE FUNCTION external_snapshot_quarantine_in_project() RETURNS TRIGGER AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM external_snapshots s
         WHERE s.snapshot_id = NEW.snapshot_id AND s.project_id = NEW.project_id
    ) THEN
        RAISE EXCEPTION
            'quarantine of % names project %, which is not the snapshot''s project',
            NEW.snapshot_id, NEW.project_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS external_snapshot_quarantine_in_project_trg ON external_snapshot_quarantine;
CREATE TRIGGER external_snapshot_quarantine_in_project_trg
    BEFORE INSERT ON external_snapshot_quarantine
    FOR EACH ROW EXECUTE FUNCTION external_snapshot_quarantine_in_project();

DROP TRIGGER IF EXISTS external_snapshot_quarantine_is_append_only_trg
    ON external_snapshot_quarantine;
CREATE TRIGGER external_snapshot_quarantine_is_append_only_trg
    BEFORE UPDATE OR DELETE ON external_snapshot_quarantine
    FOR EACH ROW EXECUTE FUNCTION external_provenance_is_append_only();

-- The rule `002d` enforces on new writes, as a function of a row: NULL when the row's project and
-- access scope are provably coherent, else the reason they are not.
CREATE OR REPLACE FUNCTION external_snapshot_scope_problem(
    p_project_id TEXT,
    p_provider TEXT,
    p_visibility TEXT,
    p_access_policy_ref TEXT,
    p_repository_identity TEXT
) RETURNS TEXT AS $$
DECLARE
    v_scope external_access_scopes%ROWTYPE;
BEGIN
    IF p_access_policy_ref IS NULL THEN
        RETURN CASE WHEN p_visibility = 'PUBLIC' THEN NULL ELSE 'PRIVATE_WITHOUT_SCOPE' END;
    END IF;
    SELECT * INTO v_scope FROM external_access_scopes WHERE policy_ref = p_access_policy_ref;
    IF NOT FOUND THEN
        RETURN 'SCOPE_NOT_RECORDED';
    END IF;
    IF v_scope.project_id <> p_project_id OR v_scope.provider <> p_provider THEN
        RETURN 'SCOPE_OF_ANOTHER_PROJECT';
    END IF;
    IF p_visibility <> 'PUBLIC' AND NOT (
        p_repository_identity IS NOT NULL
        AND split_part(p_repository_identity, ' ', 2) = ANY (v_scope.private_allowlist)
    ) THEN
        RETURN 'NOT_ON_ALLOWLIST';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE;

-- The upgrade itself: every existing row that cannot be proven coherent is quarantined.
INSERT INTO external_snapshot_quarantine (snapshot_id, project_id, reason_code)
SELECT s.snapshot_id, s.project_id, p.problem
  FROM external_snapshots s
 CROSS JOIN LATERAL (
        SELECT external_snapshot_scope_problem(
                   s.project_id, s.provider, s.visibility, s.access_policy_ref,
                   s.repository_identity) AS problem
       ) p
 WHERE p.problem IS NOT NULL
ON CONFLICT (snapshot_id) DO NOTHING;

-- One TRUSTED snapshot per cache key. A quarantined row no longer holds its key.
ALTER TABLE external_snapshots DROP CONSTRAINT IF EXISTS external_snapshots_cache_key;
CREATE INDEX IF NOT EXISTS external_snapshots_cache_key_idx
    ON external_snapshots (project_id, provider, canonical_locator);

CREATE OR REPLACE FUNCTION external_snapshots_one_trusted_per_key() RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(
        hashtextextended(NEW.project_id || chr(31) || NEW.provider || chr(31)
                         || NEW.canonical_locator, 0)
    );
    IF EXISTS (
        SELECT 1 FROM external_snapshots s
         WHERE s.project_id = NEW.project_id
           AND s.provider = NEW.provider
           AND s.canonical_locator = NEW.canonical_locator
           AND NOT EXISTS (
               SELECT 1 FROM external_snapshot_quarantine q WHERE q.snapshot_id = s.snapshot_id
           )
    ) THEN
        RAISE EXCEPTION
            '% is already snapshotted in project % by a trusted row; a pinned version is kept '
            'once (cache key)', NEW.canonical_locator, NEW.project_id
            USING ERRCODE = 'unique_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS external_snapshots_one_trusted_per_key_trg ON external_snapshots;
CREATE TRIGGER external_snapshots_one_trusted_per_key_trg
    BEFORE INSERT ON external_snapshots
    FOR EACH ROW EXECUTE FUNCTION external_snapshots_one_trusted_per_key();

-- The §6.18 selection, and what the use guards below read.
CREATE OR REPLACE VIEW external_quarantined_attestations AS
SELECT a.attestation_id, a.project_id, q.snapshot_id, q.reason_code
  FROM attestations a
  JOIN external_snapshot_quarantine q ON q.snapshot_id = a.method ->> 'snapshot_id';

CREATE OR REPLACE FUNCTION external_attestation_is_quarantined(p_attestation_id TEXT)
RETURNS BOOLEAN AS $$
    SELECT EXISTS (
        SELECT 1 FROM external_quarantined_attestations WHERE attestation_id = p_attestation_id
    );
$$ LANGUAGE sql STABLE;

-- Admission: nothing is admitted from a quarantined snapshot.
CREATE OR REPLACE FUNCTION attestations_not_from_quarantined_snapshot() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.method ? 'snapshot_id' AND EXISTS (
        SELECT 1 FROM external_snapshot_quarantine q
         WHERE q.snapshot_id = NEW.method ->> 'snapshot_id'
    ) THEN
        RAISE EXCEPTION
            'attestation % cites external snapshot %, which is quarantined: its project and '
            'access scope could not be proven coherent (GH-002)',
            NEW.attestation_id, NEW.method ->> 'snapshot_id';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS attestations_not_from_quarantined_snapshot_trg ON attestations;
CREATE TRIGGER attestations_not_from_quarantined_snapshot_trg
    BEFORE INSERT ON attestations
    FOR EACH ROW EXECUTE FUNCTION attestations_not_from_quarantined_snapshot();

-- Use: an attestation admitted from a snapshot quarantined later cannot be cited anew.
CREATE OR REPLACE FUNCTION external_quarantine_blocks_citation() RETURNS TRIGGER AS $$
DECLARE
    v_cited TEXT[];
    v_id TEXT;
BEGIN
    IF TG_TABLE_NAME = 'relation_judgments' THEN
        v_cited := NEW.supporting_attestation_ids || ARRAY[NEW.from_entity_id, NEW.to_entity_id];
    ELSE
        v_cited := ARRAY[NEW.attestation_id];
    END IF;
    FOREACH v_id IN ARRAY v_cited LOOP
        IF external_attestation_is_quarantined(v_id) THEN
            RAISE EXCEPTION
                '% cites attestation %, which was admitted from a quarantined external snapshot '
                '(GH-002 upgrade); it is not trusted evidence', TG_TABLE_NAME, v_id;
        END IF;
    END LOOP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS relation_judgments_not_quarantined_trg ON relation_judgments;
CREATE TRIGGER relation_judgments_not_quarantined_trg
    BEFORE INSERT ON relation_judgments
    FOR EACH ROW EXECUTE FUNCTION external_quarantine_blocks_citation();

DROP TRIGGER IF EXISTS evidence_bundle_members_not_quarantined_trg ON evidence_bundle_members;
CREATE TRIGGER evidence_bundle_members_not_quarantined_trg
    BEFORE INSERT ON evidence_bundle_members
    FOR EACH ROW EXECUTE FUNCTION external_quarantine_blocks_citation();

DROP TRIGGER IF EXISTS belief_revision_event_attestations_not_quarantined_trg
    ON belief_revision_event_attestations;
CREATE TRIGGER belief_revision_event_attestations_not_quarantined_trg
    BEFORE INSERT ON belief_revision_event_attestations
    FOR EACH ROW EXECUTE FUNCTION external_quarantine_blocks_citation();
