-- 002_artifacts_sourceworks.sql
--
-- Artifacts (ART-001) and SourceWorks (EVI-004, EVI-008).
--
-- The central constraint is that artifact identity is content-derived, and the database says so
-- rather than trusting the application: `artifact_id = 'art:' || content_hash` is a CHECK. That
-- makes "same bytes, two ids" and "one id, two contents" both unrepresentable at rest, not just
-- discouraged in Python.

CREATE TABLE artifacts (
    artifact_id            TEXT PRIMARY KEY,
    content_hash           TEXT NOT NULL,
    media_type             TEXT NOT NULL,
    uri                    TEXT NOT NULL,

    -- Human-meaningful versioning, orthogonal to content addressing (§6.1). Every artifact is
    -- revision 1 of its own lineage unless it declares otherwise.
    lineage_id             TEXT NOT NULL,
    lineage_revision       INTEGER NOT NULL DEFAULT 1 CHECK (lineage_revision >= 1),
    previous_artifact_id   TEXT REFERENCES artifacts (artifact_id),

    source_origin          TEXT NOT NULL
        CHECK (source_origin IN ('UPLOAD', 'WATCHER_FILESYSTEM', 'WATCHER_GIT',
                                 'RUN_OUTPUT', 'EXTERNAL_CONNECTOR', 'DERIVED')),
    -- NOT NULL with no default: P28 requires unclassified data to be treated as strictest, and
    -- a column that defaults to anything can be forgotten. Classification is mandatory.
    sensitivity_label      TEXT NOT NULL
        CHECK (sensitivity_label IN ('RESTRICTED_NDA', 'CONFIDENTIAL_LAB',
                                     'INTERNAL', 'PUBLIC')),
    project_id             TEXT NOT NULL REFERENCES projects (project_id),

    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    captured_at            TIMESTAMPTZ,
    author_or_device       TEXT,
    actor_id               TEXT REFERENCES actors (actor_id),

    parser_version         TEXT,
    derived_from_artifact_ids TEXT[] NOT NULL DEFAULT '{}',

    rights_metadata        JSONB,
    -- SEC-003: parsing may only proceed once this is CLEAN or REDACTED.
    secret_scan_status     TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (secret_scan_status IN ('PENDING', 'CLEAN', 'QUARANTINED',
                                      'REDACTED', 'SCAN_FAILED')),
    metadata               JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- ART-001 enforced by the database, not only by the application.
    CONSTRAINT artifacts_id_is_content_addressed
        CHECK (artifact_id = 'art:' || content_hash),
    CONSTRAINT artifacts_content_hash_format
        CHECK (content_hash ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT artifacts_not_own_predecessor
        CHECK (previous_artifact_id IS NULL OR previous_artifact_id <> artifact_id),
    -- A revision above 1 must name what it supersedes, or the chain has an untraceable gap.
    CONSTRAINT artifacts_revision_chain_complete
        CHECK ((lineage_revision = 1 AND previous_artifact_id IS NULL)
               OR (lineage_revision > 1 AND previous_artifact_id IS NOT NULL))
);

-- content_hash is unique because it *is* the identity; a second row would mean two identities
-- for one set of bytes.
CREATE UNIQUE INDEX artifacts_content_hash_key ON artifacts (content_hash);
CREATE UNIQUE INDEX artifacts_lineage_revision_key ON artifacts (lineage_id, lineage_revision);
CREATE INDEX artifacts_project_idx ON artifacts (project_id, created_at DESC);
CREATE INDEX artifacts_sensitivity_idx ON artifacts (sensitivity_label);

CREATE TABLE source_works (
    source_work_id  TEXT PRIMARY KEY,
    work_type       TEXT NOT NULL
        CHECK (work_type IN ('JOURNAL_ARTICLE', 'PREPRINT', 'CONFERENCE_PAPER', 'THESIS',
                             'PATENT', 'TECHNICAL_REPORT', 'SOFTWARE_REPOSITORY',
                             'DATASET', 'WEB_PAGE', 'INTERNAL_DOCUMENT')),
    title           TEXT NOT NULL,
    authors         TEXT[] NOT NULL DEFAULT '{}',
    venue           TEXT,
    published_year  INTEGER CHECK (published_year BETWEEN 1600 AND 2200),
    canonical_locator TEXT,
    manifestation_artifact_ids TEXT[] NOT NULL DEFAULT '{}',
    trust_class     TEXT NOT NULL
        CHECK (trust_class IN ('INTERNAL_RUN', 'INTERNAL_MEASUREMENT', 'PEER_REVIEWED',
                               'PREPRINT', 'PATENT', 'TECHNICAL_ARTIFACT', 'WEB',
                               'EXPERT_HEURISTIC')),
    -- EVI-008: recorded even when the result is UNKNOWN. An absent check is indistinguishable
    -- from a passed one, which is how a retracted source ends up supporting a revision.
    retraction_check JSONB NOT NULL DEFAULT '{"status": "UNKNOWN"}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- External identifiers are a separate table, not an array: same-work resolution queries them
-- by (scheme, value), and a DOI must be unique across works or EVI-004 cannot collapse
-- manifestations reliably.
CREATE TABLE source_work_identifiers (
    source_work_id  TEXT NOT NULL REFERENCES source_works (source_work_id) ON DELETE CASCADE,
    scheme          TEXT NOT NULL,
    value           TEXT NOT NULL,
    PRIMARY KEY (source_work_id, scheme, value)
);

CREATE UNIQUE INDEX source_work_identifiers_unique ON source_work_identifiers (scheme, value);
