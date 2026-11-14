-- 012_ingestion_items_errors.sql
--
-- UX-001 / UX-002 / UX-003 / §17.22 / §17.23. Appendix A's slot, taken with its exact slug.
--
-- THE RULE THIS SCHEMA HAS TO ENCODE, and it is the whole of §17.22's design:
--
--     IngestionItem 是使用者在 Knowledge Inbox 看到的那一列。它是**投影，不是真相來源**：state
--     由 Job / ExecutionSpan / Artifact / ReviewItem / Conflict 推導，不得由前端或人工直接指定。
--
-- So `ingestion_items` HAS NO `state` COLUMN. Not a state column with a trigger, not a state
-- column that a view overrides -- none. A column is a place to write, and the first thing a UI
-- does when a derivation is inconvenient is write to it; afterwards the projection and the
-- records disagree with nothing detecting the drift. `lab_brain.surface.ingestion_item.
-- derive_state` computes it from the authoritative rows on every read.
--
-- Same for `error_records`: §17.23 says outright that an ErrorRecord is
-- `Job.structured_error` + `ExecutionSpan`'s user-layer projection, 不是第二個真相來源. What is
-- stored here is the stable, project-scoped `error_id` a human quotes, plus the classification
-- that decides who acts -- never a second copy of the failure itself.
--
-- `technical_detail_ref` IS A POINTER. §17.24: technical detail may contain NDA filenames,
-- private repository paths and restricted prompt fragments, and expanding it requires an ACL
-- scope checked server-side. Inlining it here would put that material into the table a default
-- payload is built from, and `DiagnosticsService` would be redacting something it had already
-- handed over.

CREATE TABLE ingestion_items (
    item_id             TEXT PRIMARY KEY,
    project_id          TEXT NOT NULL REFERENCES projects (project_id),
    actor_id            TEXT NOT NULL REFERENCES actors (actor_id),
    trace_id            TEXT NOT NULL,

    -- §17.22: MUST exist before any parsing stage runs. Nullable because SEC-003 quarantines a
    -- file BEFORE raw storage, and such an item is real, visible and has no artifact -- it
    -- surfaces as BLOCKED, which is the state that exists precisely for it.
    raw_artifact_id     TEXT REFERENCES artifacts (artifact_id),

    source_kind         TEXT NOT NULL CHECK (source_kind IN ('UPLOAD', 'WATCHER', 'CONNECTOR')),
    display_name        TEXT NOT NULL,
    submitted_at        TIMESTAMPTZ NOT NULL,

    -- §17.22's two duplicate semantics, as two columns. NOT one column plus a kind flag: they
    -- co-occur (the same bytes of the same work arriving twice is both), and collapsing them
    -- would force a choice that discards what EVI-004's corroboration counter needs.
    --
    -- identical bytes  -> no new scientific value; safe to skip
    -- same work        -> NOT discardable. MUST still create SourceWork/Attestation, or
    --                     corroboration counting is silently wrong in the direction that makes
    --                     evidence look weaker than it is.
    duplicate_of_artifact_id    TEXT REFERENCES artifacts (artifact_id),
    duplicate_of_source_work_id TEXT REFERENCES source_works (source_work_id),

    last_updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT ingestion_items_not_its_own_duplicate
        CHECK (duplicate_of_artifact_id IS NULL OR duplicate_of_artifact_id <> raw_artifact_id)
);

CREATE INDEX ingestion_items_project_idx ON ingestion_items (project_id, submitted_at DESC);
CREATE INDEX ingestion_items_trace_idx   ON ingestion_items (trace_id);

-- §17.22's StageResult. One row per stage attempt, which is what makes PARTIAL representable:
-- the state derivation needs to see that one value-producing stage succeeded and another failed.
CREATE TABLE ingestion_stage_results (
    item_id         TEXT NOT NULL REFERENCES ingestion_items (item_id) ON DELETE CASCADE,
    stage           TEXT NOT NULL CHECK (
        stage IN (
            'SECRET_SCAN', 'RAW_STORE', 'PARSE_TEXT', 'PARSE_TABLE',
            'PARSE_FIGURE', 'CLAIM_EXTRACT', 'EMBED', 'INDEX', 'SEGMENT'
        )
    ),
    attempt         INTEGER NOT NULL DEFAULT 1 CHECK (attempt >= 1),
    status          TEXT NOT NULL CHECK (
        status IN ('SUCCEEDED', 'FAILED', 'SKIPPED', 'PENDING', 'DEGRADED')
    ),
    job_id          TEXT REFERENCES jobs (job_id),
    span_id         TEXT REFERENCES execution_spans (span_id),
    error_id        TEXT,
    reason_code     TEXT,
    error_class     TEXT CHECK (
        error_class IS NULL OR error_class IN (
            'USER_INPUT_ERROR', 'EXTRACTION_WARNING', 'POLICY_BLOCK',
            'EXTERNAL_SERVICE_ERROR', 'SYSTEM_ERROR'
        )
    ),
    output_refs     TEXT[] NOT NULL DEFAULT '{}',
    started_at      TIMESTAMPTZ NOT NULL,
    finished_at     TIMESTAMPTZ,

    PRIMARY KEY (item_id, stage, attempt),

    CONSTRAINT ingestion_stage_results_finished_after_started
        CHECK (finished_at IS NULL OR finished_at >= started_at),
    -- A failed stage must say WHY in a machine-readable way. UX-006 keys catalog text on
    -- `reason_code`, so a failure with none renders as the generic entry and the user is told
    -- nothing actionable -- which is the state §17.23's whole classification exists to avoid.
    CONSTRAINT ingestion_stage_results_failure_has_a_reason
        CHECK (status <> 'FAILED' OR reason_code IS NOT NULL)
);

-- §17.23's ErrorRecord.
CREATE TABLE error_records (
    -- ERR-YYYYMMDD-NNNN; stable and project-scoped, because it is what a human quotes.
    error_id            TEXT PRIMARY KEY,
    project_id          TEXT NOT NULL REFERENCES projects (project_id),
    trace_id            TEXT NOT NULL,
    job_id              TEXT REFERENCES jobs (job_id),
    span_id             TEXT REFERENCES execution_spans (span_id),
    item_id             TEXT REFERENCES ingestion_items (item_id),

    -- FROZEN vocabulary (§17.23's stability tier). A sixth member requires an ADR, because
    -- error_class decides who acts and every downstream retry branch reads it.
    error_class         TEXT NOT NULL CHECK (
        error_class IN (
            'USER_INPUT_ERROR', 'EXTRACTION_WARNING', 'POLICY_BLOCK',
            'EXTERNAL_SERVICE_ERROR', 'SYSTEM_ERROR'
        )
    ),
    -- GROWING vocabulary: free text at the column, constrained by UX-006's conformance test that
    -- every emitted code resolves in the catalog. A CHECK here would need editing for every new
    -- code, which §17.23 explicitly says M1 may add without an ADR.
    reason_code         TEXT NOT NULL,
    component           TEXT NOT NULL,
    occurred_at         TIMESTAMPTZ NOT NULL,

    attempt_count       INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts        INTEGER NOT NULL DEFAULT 1 CHECK (max_attempts >= 1),
    next_retry_at       TIMESTAMPTZ,

    -- A POINTER (§17.24). See the header.
    technical_detail_ref TEXT,
    resolved_at         TIMESTAMPTZ,
    resolution_note_ref TEXT,

    CONSTRAINT error_records_attempts_bounded CHECK (attempt_count <= max_attempts),

    -- §17.23: "exhausted retries transition the surface to FAILED with next_retry_at cleared".
    -- A stale timestamp on a dead item tells a user to wait for something that will never happen,
    -- so the schema refuses to hold that contradiction rather than relying on every writer.
    CONSTRAINT error_records_exhausted_has_no_next_retry
        CHECK (attempt_count < max_attempts OR next_retry_at IS NULL),

    -- §17.23: POLICY_BLOCK and USER_INPUT_ERROR MUST NOT be auto-retried. A scheduled retry on
    -- one of them is not a record of a decision -- it IS the retry loop the requirement forbids,
    -- and against an ACL it is indistinguishable from an attack.
    CONSTRAINT error_records_no_retry_scheduled_for_unretryable
        CHECK (
            error_class NOT IN ('POLICY_BLOCK', 'USER_INPUT_ERROR', 'EXTRACTION_WARNING')
            OR next_retry_at IS NULL
        )
);

CREATE INDEX error_records_project_idx ON error_records (project_id, occurred_at DESC);
CREATE INDEX error_records_item_idx    ON error_records (item_id) WHERE item_id IS NOT NULL;

-- `ingestion_stage_results.error_id` resolves, and to an error in the same project.
--
-- A deferred constraint trigger rather than a foreign key, because the stage result is written
-- during ingestion and its ErrorRecord is projected from the same failure -- either order is
-- legitimate within one transaction, and a plain FK would force one.
CREATE FUNCTION stage_error_must_resolve_in_project() RETURNS TRIGGER AS $$
DECLARE
    v_project TEXT;
    v_item_project TEXT;
BEGIN
    IF NEW.error_id IS NULL THEN
        RETURN NEW;
    END IF;
    SELECT project_id INTO v_project FROM error_records WHERE error_id = NEW.error_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION
            'stage %/% on item % names error % which does not exist; UX-003 lets a user quote '
            'that id, and one that resolves to nothing is a dead end at the moment somebody is '
            'already stuck', NEW.stage, NEW.attempt, NEW.item_id, NEW.error_id;
    END IF;
    SELECT project_id INTO v_item_project FROM ingestion_items WHERE item_id = NEW.item_id;
    IF v_item_project IS DISTINCT FROM v_project THEN
        RAISE EXCEPTION
            'item % is in project % but error % is in %; §17.24 scopes error lookup by project '
            'membership, and a cross-project reference is a way to reach one anyway',
            NEW.item_id, v_item_project, NEW.error_id, v_project;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER stage_error_must_resolve_in_project_trg
    AFTER INSERT OR UPDATE ON ingestion_stage_results
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION stage_error_must_resolve_in_project();

COMMENT ON TABLE ingestion_items IS
    'UX-001 / §17.22. The Knowledge Inbox row. NO `state` COLUMN: state is derived from Job / '
    'ExecutionSpan / Artifact / ReviewItem / Conflict on every read, and a column would be a '
    'place for a client to write when the derivation is inconvenient.';

COMMENT ON TABLE error_records IS
    'UX-002/UX-003 / §17.23. The user-layer projection of Job.structured_error + ExecutionSpan, '
    'not a second source of truth. `technical_detail_ref` is a pointer; expanding it is an '
    'authorization decision (§17.24).';
