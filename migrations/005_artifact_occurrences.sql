-- 005_artifact_occurrences.sql
--
-- Closes risk R-7: separate global content identity from project-scoped presence.
--
-- THE DEFECT. `artifacts.content_hash` carries a UNIQUE index, because content identity is the
-- point -- the same bytes are the same artifact everywhere. Migration 002 then put `project_id`
-- and `sensitivity_label` on that same row. Those are not properties of the bytes; they are
-- properties of a project's *copy* of the bytes, and there can be several.
--
-- The consequence is not a missing check, it is an unanswerable question. A foundry PDK document
-- classified RESTRICTED_NDA in project A and re-uploaded into project B is physically ONE ROW.
-- Content-hash duplicate detection hands B a reference to A's artifact, and every check reading
-- `artifact.sensitivity_label` consults A's answer about B's copy. Whichever project ingested the
-- bytes first owns the classification for everyone -- a genuine SEC-001 egress path built into the
-- schema rather than introduced by a bug.
--
-- THE SPLIT.
--   artifacts             global. These bytes, this hash, this lineage, these rights.
--   artifact_occurrences  per project. These bytes are present in THIS project, under THIS label,
--                         ingested by THIS actor at THIS time.
--
-- One artifact, N occurrences, N independent labels.

CREATE TABLE artifact_occurrences (
    artifact_id           TEXT NOT NULL REFERENCES artifacts (artifact_id),
    project_id            TEXT NOT NULL REFERENCES projects (project_id),

    -- NOT NULL with no default, exactly as it was on `artifacts`. P28 requires unclassified data
    -- to be treated as strictest, and a column that defaults to anything can be forgotten. The
    -- admission gate applies FAIL_CLOSED_SENSITIVITY explicitly (M1).
    sensitivity_label     TEXT NOT NULL
        CHECK (sensitivity_label IN ('RESTRICTED_NDA', 'CONFIDENTIAL_LAB', 'INTERNAL', 'PUBLIC')),

    ingested_by_actor_id  TEXT REFERENCES actors (actor_id),
    ingested_at           TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Identity is the PAIR. Neither half alone identifies an occurrence, which is precisely the
    -- distinction the old shape could not make.
    PRIMARY KEY (artifact_id, project_id)
);

CREATE INDEX artifact_occurrences_project_idx
    ON artifact_occurrences (project_id, ingested_at DESC);
CREATE INDEX artifact_occurrences_sensitivity_idx
    ON artifact_occurrences (project_id, sensitivity_label);

-- Backfill before dropping, so no classification is lost. Every existing artifact has exactly one
-- project and one label today; that becomes its single occurrence.
INSERT INTO artifact_occurrences (artifact_id, project_id, sensitivity_label,
                                  ingested_by_actor_id, ingested_at)
SELECT artifact_id, project_id, sensitivity_label, actor_id, created_at
FROM artifacts;

-- Now remove them from `artifacts`. Dropping rather than leaving them nullable: a column that
-- still exists will be read, and the whole point is that reading a project-scoped fact off the
-- global row is the bug. Making it impossible is the fix; making it discouraged is not.
DROP INDEX artifacts_project_idx;
DROP INDEX artifacts_sensitivity_idx;
ALTER TABLE artifacts DROP COLUMN project_id;
ALTER TABLE artifacts DROP COLUMN sensitivity_label;

-- ---------------------------------------------------------------------------------------------
-- Membership activation, so revocation does not require deleting the audit trail.
--
-- Migration 001 created project_memberships with a fail-closed `sensitivity_clearance TEXT[]
-- DEFAULT '{}'`, which stays. What was missing is a way to end a grant: without `active`, revoking
-- access means DELETE, and then "who could read this in March" has no answer.
-- ---------------------------------------------------------------------------------------------
ALTER TABLE project_memberships
    ADD COLUMN active BOOLEAN NOT NULL DEFAULT TRUE;

-- Clearance entries must be real labels. An unrecognised string in the array would be compared
-- against nothing and silently grant nothing -- fail-closed, but silently, and a typo in a grant
-- should be a loud error rather than an access denial nobody can explain.
ALTER TABLE project_memberships
    ADD CONSTRAINT project_memberships_clearance_labels_valid
    CHECK (sensitivity_clearance <@ ARRAY['RESTRICTED_NDA', 'CONFIDENTIAL_LAB',
                                          'INTERNAL', 'PUBLIC']::TEXT[]);
