-- 002c_external_snapshots.sql
--
-- M5 / GH-001, GH-002, GH-003 (§6.16, §17.21). External material as provenance: the pinned
-- snapshot a citation rests on, the lifecycle of external records, and GH-003's rule that
-- technical material is never promoted -- held here for every writer of SQL.
--
-- In Appendix A's 002 slot (artifacts / source works) because a snapshot is the provenance of an
-- EXTERNAL_CONNECTOR artifact and the manifestation of a SourceWork.
--
-- EXTERNAL_SNAPSHOTS. One row per (project, provider, pinned locator) -- the cache key: the pinned
-- locator names an immutable version, so a second retrieval of it is a cache hit, never a second
-- copy. For every writer:
--
--   the kept artifact   exists, came from an external connector (source_origin), and is present
--                       in the snapshot's project (ADR-0010); when the whole content was kept, the
--                       artifact's hash IS the recorded content hash
--   GitHub provenance   (§22) a code file or release is pinned to a 40-hex commit that its
--                       canonical locator names, and carries its repository identity
--   GH-003              repository / code_file / release are TECHNICAL_ARTIFACT, nothing higher
--   GH-002              private or authenticated material is never labelled PUBLIC
--   append-only         a moved branch is a new snapshot; the old one stays re-readable (§6.16)
--
-- EXTERNAL_SOURCE_EVENTS. Discovery, snapshot, cache hit, admission, drift, SOURCE_UNAVAILABLE,
-- refused access, connector errors. A refused access stores a digest of the locator and no locator:
-- a private repository's name is private context (GH-002). No event detail may carry a query, text,
-- content, token or credential. Append-only.
--
-- ATTESTATIONS (GH-003, additive guard). An attestation citing a TECHNICAL_ARTIFACT source work, or
-- citing an external snapshot's artifact directly, is REPORTED -- another party's material is never
-- MEASURED, SIMULATED or OBSERVED by this lab. An attestation naming the snapshot it was read
-- from is in that snapshot's project and claims no deeper §6.4 enrichment stage than the snapshot
-- kept. SOURCE_WORKS: a software repository is never PEER_REVIEWED or internal evidence.

CREATE TABLE IF NOT EXISTS external_snapshots (
    snapshot_id          TEXT PRIMARY KEY,
    project_id           TEXT NOT NULL REFERENCES projects (project_id),
    provider             TEXT NOT NULL CHECK (btrim(provider) <> ''),
    source_type          TEXT NOT NULL CHECK (btrim(source_type) <> ''),
    requested_locator    TEXT NOT NULL CHECK (btrim(requested_locator) <> ''),
    canonical_locator    TEXT NOT NULL CHECK (btrim(canonical_locator) <> ''),
    requested_ref        TEXT,
    resolved_ref         TEXT NOT NULL CHECK (btrim(resolved_ref) <> ''),
    repository_identity  TEXT,
    content_hash         TEXT NOT NULL CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    artifact_id          TEXT NOT NULL REFERENCES artifacts (artifact_id),
    retention            TEXT NOT NULL CHECK (retention IN ('FULL_CONTENT', 'EXCERPT', 'METADATA_ONLY')),
    retention_rule       TEXT NOT NULL CHECK (btrim(retention_rule) <> ''),
    visibility           TEXT NOT NULL CHECK (visibility IN ('PUBLIC', 'AUTHENTICATED', 'PRIVATE')),
    -- §6.5: only the classes an external source can carry. The lab's own runs and measurements
    -- are internal by definition; an expert heuristic enters by human approval (P16).
    trust_class          TEXT NOT NULL
        CHECK (trust_class IN ('PEER_REVIEWED', 'PREPRINT', 'PATENT', 'TECHNICAL_ARTIFACT', 'WEB')),
    sensitivity          TEXT NOT NULL
        CHECK (sensitivity IN ('RESTRICTED_NDA', 'CONFIDENTIAL_LAB', 'INTERNAL', 'PUBLIC')),
    license_class        TEXT NOT NULL
        CHECK (license_class IN ('PERMISSIVE', 'COPYLEFT', 'PROPRIETARY', 'UNKNOWN')),
    license_identifier   TEXT,
    rights_status        TEXT,
    access_policy_ref    TEXT,
    retrieved_at         TIMESTAMPTZ NOT NULL,
    created_at           TIMESTAMPTZ NOT NULL,

    CONSTRAINT external_snapshots_cache_key UNIQUE (project_id, provider, canonical_locator),
    CONSTRAINT external_snapshots_commit_pinned CHECK (
        source_type NOT IN ('code_file', 'release')
        OR (resolved_ref ~ '^[0-9a-f]{40}$'
            AND strpos(canonical_locator, resolved_ref) > 0
            AND repository_identity IS NOT NULL AND btrim(repository_identity) <> '')
    ),
    CONSTRAINT external_snapshots_technical_is_technical CHECK (
        source_type NOT IN ('repository', 'code_file', 'release')
        OR trust_class = 'TECHNICAL_ARTIFACT'
    ),
    CONSTRAINT external_snapshots_private_is_not_public CHECK (
        visibility = 'PUBLIC' OR sensitivity <> 'PUBLIC'
    )
);

CREATE INDEX IF NOT EXISTS external_snapshots_request_idx
    ON external_snapshots (project_id, provider, requested_locator);

CREATE FUNCTION external_snapshots_keep_what_they_say() RETURNS TRIGGER AS $$
DECLARE
    v_artifact artifacts%ROWTYPE;
BEGIN
    SELECT * INTO v_artifact FROM artifacts WHERE artifact_id = NEW.artifact_id;
    IF v_artifact.source_origin <> 'EXTERNAL_CONNECTOR' THEN
        RAISE EXCEPTION
            'snapshot % keeps artifact %, whose origin is %; a snapshot keeps what an external '
            'connector returned', NEW.snapshot_id, NEW.artifact_id, v_artifact.source_origin;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM artifact_occurrences o
         WHERE o.artifact_id = NEW.artifact_id AND o.project_id = NEW.project_id
    ) THEN
        RAISE EXCEPTION
            'snapshot % keeps artifact %, which is not present in project % (ADR-0010)',
            NEW.snapshot_id, NEW.artifact_id, NEW.project_id;
    END IF;
    IF NEW.retention = 'FULL_CONTENT' AND v_artifact.content_hash <> NEW.content_hash THEN
        RAISE EXCEPTION
            'snapshot % claims FULL_CONTENT retention of % but its artifact hashes to %; the '
            'kept bytes are not the bytes the provider returned', NEW.snapshot_id,
            NEW.content_hash, v_artifact.content_hash;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER external_snapshots_keep_what_they_say_trg
    BEFORE INSERT ON external_snapshots
    FOR EACH ROW EXECUTE FUNCTION external_snapshots_keep_what_they_say();

CREATE TABLE IF NOT EXISTS external_source_events (
    event_id        TEXT PRIMARY KEY,
    project_id      TEXT NOT NULL REFERENCES projects (project_id),
    provider        TEXT NOT NULL CHECK (btrim(provider) <> ''),
    kind            TEXT NOT NULL
        CHECK (kind IN ('DISCOVERED', 'SNAPSHOTTED', 'CACHE_HIT', 'ADMITTED', 'REF_DRIFT',
                        'SOURCE_UNAVAILABLE', 'ACCESS_REFUSED', 'CONNECTOR_ERROR')),
    locator_digest  TEXT NOT NULL CHECK (locator_digest ~ '^sha256:[0-9a-f]{64}$'),
    locator         TEXT,
    snapshot_id     TEXT REFERENCES external_snapshots (snapshot_id),
    actor_id        TEXT REFERENCES actors (actor_id),
    detail          JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at     TIMESTAMPTZ NOT NULL,

    CONSTRAINT external_source_events_refusal_has_no_locator CHECK (
        (kind = 'ACCESS_REFUSED') = (locator IS NULL)
    ),
    CONSTRAINT external_source_events_detail_carries_no_payload CHECK (
        jsonb_typeof(detail) = 'object'
        AND NOT (detail ?| ARRAY['query', 'text', 'content', 'token', 'credential'])
    )
);

CREATE INDEX IF NOT EXISTS external_source_events_project_idx
    ON external_source_events (project_id, occurred_at);

CREATE FUNCTION external_source_events_snapshot_in_project() RETURNS TRIGGER AS $$
DECLARE
    v_project TEXT;
BEGIN
    IF NEW.snapshot_id IS NULL THEN
        RETURN NEW;
    END IF;
    SELECT project_id INTO v_project FROM external_snapshots WHERE snapshot_id = NEW.snapshot_id;
    IF v_project IS DISTINCT FROM NEW.project_id THEN
        RAISE EXCEPTION 'event % in % names snapshot % of project %',
            NEW.event_id, NEW.project_id, NEW.snapshot_id, v_project;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER external_source_events_snapshot_in_project_trg
    BEFORE INSERT ON external_source_events
    FOR EACH ROW EXECUTE FUNCTION external_source_events_snapshot_in_project();

CREATE FUNCTION external_provenance_is_append_only() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        '% is append-only: external provenance is what was read and when; a later reading is a '
        'new row (§6.16)', TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER external_snapshots_are_append_only_trg
    BEFORE UPDATE OR DELETE ON external_snapshots
    FOR EACH ROW EXECUTE FUNCTION external_provenance_is_append_only();

CREATE TRIGGER external_source_events_are_append_only_trg
    BEFORE UPDATE OR DELETE ON external_source_events
    FOR EACH ROW EXECUTE FUNCTION external_provenance_is_append_only();

-- GH-003 on the evidence tables themselves -------------------------------------------------------

CREATE FUNCTION attestations_external_material_is_reported() RETURNS TRIGGER AS $$
DECLARE
    kept TEXT;
    kept_in TEXT;
BEGIN
    -- An attestation that names the snapshot it was read from (the admission path writes
    -- `method.snapshot_id`) must be in that snapshot's project, and may claim no deeper §6.4 stage
    -- than the snapshot kept: METADATA_ONLY -> A, EXCERPT -> B, FULL_CONTENT -> C. Stage D is a
    -- later human verification, never an admission's claim about itself.
    IF NEW.method ? 'snapshot_id' THEN
        SELECT s.retention, s.project_id INTO kept, kept_in
          FROM external_snapshots s WHERE s.snapshot_id = NEW.method->>'snapshot_id';
        IF FOUND THEN
            IF kept_in <> NEW.project_id THEN
                RAISE EXCEPTION
                    'attestation % in project % cites external snapshot % of project %',
                    NEW.attestation_id, NEW.project_id, NEW.method->>'snapshot_id', kept_in;
            END IF;
            IF NEW.extraction_status = 'STAGE_D_HUMAN_VERIFIED'
               OR (kept = 'METADATA_ONLY' AND NEW.extraction_status <> 'STAGE_A_METADATA')
               OR (kept = 'EXCERPT' AND NEW.extraction_status = 'STAGE_C_DEEP') THEN
                RAISE EXCEPTION
                    'attestation % claims % from external snapshot % that kept %; §6.4: a stage '
                    'is claimable only at a depth the kept material can be re-read',
                    NEW.attestation_id, NEW.extraction_status, NEW.method->>'snapshot_id', kept;
            END IF;
        END IF;
    END IF;
    IF NEW.epistemic_type = 'REPORTED' OR NEW.epistemic_type = 'INFERRED' THEN
        RETURN NEW;
    END IF;
    IF NEW.source_work_id IS NOT NULL AND EXISTS (
        SELECT 1 FROM source_works w
         WHERE w.source_work_id = NEW.source_work_id AND w.trust_class = 'TECHNICAL_ARTIFACT'
    ) THEN
        RAISE EXCEPTION
            'attestation % cites technical source work % as %. GH-003: technical/prior-art '
            'evidence is REPORTED, never promoted to measured or peer-reviewed evidence',
            NEW.attestation_id, NEW.source_work_id, NEW.epistemic_type;
    END IF;
    IF NEW.source_artifact_id IS NOT NULL AND EXISTS (
        SELECT 1 FROM external_snapshots s WHERE s.artifact_id = NEW.source_artifact_id
    ) THEN
        RAISE EXCEPTION
            'attestation % cites external snapshot artifact % as %; another party''s material '
            'is REPORTED by this lab, never %', NEW.attestation_id, NEW.source_artifact_id,
            NEW.epistemic_type, NEW.epistemic_type;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER attestations_external_material_is_reported_trg
    BEFORE INSERT ON attestations
    FOR EACH ROW EXECUTE FUNCTION attestations_external_material_is_reported();

CREATE FUNCTION source_works_repository_is_technical() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.work_type = 'SOFTWARE_REPOSITORY'
       AND NEW.trust_class IN ('PEER_REVIEWED', 'INTERNAL_RUN', 'INTERNAL_MEASUREMENT') THEN
        RAISE EXCEPTION
            'source work % is a software repository labelled %. GH-003: a repository is '
            'technical/prior-art material', NEW.source_work_id, NEW.trust_class;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER source_works_repository_is_technical_trg
    BEFORE INSERT OR UPDATE ON source_works
    FOR EACH ROW EXECUTE FUNCTION source_works_repository_is_technical();
