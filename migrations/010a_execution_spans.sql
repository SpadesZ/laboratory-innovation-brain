-- 010a_execution_spans.sql
--
-- OPS-003 / §12.5 / §17.19.1.
--
-- NUMBERING. Appendix A reserves 010 for `010_review_observability_benchmark_policies.sql` -- one
-- migration covering ReviewQueue (OPS-002), observability (OPS-003) and BenchmarkPolicy (§17.19.2).
-- Only the observability third is built here, so this takes the `010a` suffix rather than claiming
-- the whole slot; the review and benchmark halves land with their own requirements.
-- tests/spec/test_migration_numbering.py enforces that a bare-numbered migration's slug matches
-- Appendix A exactly, which is why claiming `010` would be wrong rather than merely premature.

-- One interval of execution within one trace.
--
-- NO FOREIGN KEY ON episode_id, job_id, model_call_id OR retrieval_id, and the absence is
-- deliberate rather than forgotten. Episodes and Jobs are Appendix A 005/006, neither of which is
-- built: an FK to a missing table is not a stricter schema, it is an unapplyable migration. They
-- are recorded as references now so the trace is complete when those tables arrive, and the
-- residual -- a span may name a job nobody can resolve -- is stated in IMPLEMENTATION_STATUS.md
-- rather than implied by a column that looks checked and is not.
CREATE TABLE execution_spans (
    span_id         TEXT PRIMARY KEY,
    trace_id        TEXT NOT NULL,
    -- Self-referential: a trace is a tree of spans. ON DELETE is absent because nothing deletes
    -- spans; observability that can be pruned by the thing being observed is not evidence.
    parent_span_id  TEXT REFERENCES execution_spans (span_id),

    span_type       TEXT NOT NULL CHECK (
        span_type IN ('EPISODE', 'RETRIEVAL', 'LLM_CALL', 'TOOL_CALL', 'JOB', 'RUN')
    ),
    episode_id      TEXT,
    actor_id        TEXT REFERENCES actors (actor_id),

    -- §17.19.1's `model_call_id?/job_id?/retrieval_id?` is one alternation, not three independent
    -- fields: a span describes at most one thing. Enforced, because a span with two subjects
    -- attributes its whole cost to both of them.
    model_call_id   TEXT,
    job_id          TEXT,
    retrieval_id    TEXT,

    start_time      TIMESTAMPTZ NOT NULL,
    end_time        TIMESTAMPTZ,
    status          TEXT NOT NULL CHECK (
        status IN ('RUNNING', 'SUCCEEDED', 'FAILED', 'BLOCKED')
    ),
    metadata        JSONB NOT NULL DEFAULT '{}'::jsonb,

    CONSTRAINT execution_spans_not_its_own_parent
        CHECK (parent_span_id IS NULL OR parent_span_id <> span_id),

    CONSTRAINT execution_spans_at_most_one_subject
        CHECK (
            (CASE WHEN model_call_id IS NULL THEN 0 ELSE 1 END)
          + (CASE WHEN job_id        IS NULL THEN 0 ELSE 1 END)
          + (CASE WHEN retrieval_id  IS NULL THEN 0 ELSE 1 END) <= 1
        ),

    -- The subject has to be the one the type declares. A JOB span holding a retrieval_id cannot be
    -- reassembled into the chain §12.5 describes.
    CONSTRAINT execution_spans_subject_matches_type
        CHECK (
            CASE span_type
                WHEN 'RETRIEVAL' THEN model_call_id IS NULL AND job_id IS NULL
                WHEN 'LLM_CALL'  THEN job_id IS NULL AND retrieval_id IS NULL
                WHEN 'JOB'       THEN model_call_id IS NULL AND retrieval_id IS NULL
                ELSE model_call_id IS NULL AND job_id IS NULL AND retrieval_id IS NULL
            END
        ),

    -- A finished interval with no end is indistinguishable from one still running, and duration is
    -- the point. The converse too: RUNNING with an end_time is a contradiction in the record.
    CONSTRAINT execution_spans_terminal_status_is_ended
        CHECK ((status = 'RUNNING') = (end_time IS NULL)),
    CONSTRAINT execution_spans_ends_after_it_starts
        CHECK (end_time IS NULL OR end_time >= start_time)
);

-- Reconstruction is always "give me this trace", so that is the index.
CREATE INDEX execution_spans_trace_idx ON execution_spans (trace_id, start_time);
CREATE INDEX execution_spans_parent_idx ON execution_spans (parent_span_id);
CREATE INDEX execution_spans_episode_idx ON execution_spans (episode_id);

-- OPS-003's "cost refs". §17.19.1 declares `cost_entry_ids[]`; stored as a join rather than an
-- array column so the reference is checked: an array of TEXT can name a ledger entry that does not
-- exist, and a cost ref that resolves to nothing is exactly the kind of evidence this requirement
-- is supposed to produce.
CREATE TABLE execution_span_cost_entries (
    span_id        TEXT NOT NULL REFERENCES execution_spans (span_id),
    cost_entry_id  TEXT NOT NULL REFERENCES cost_entries (cost_entry_id),
    PRIMARY KEY (span_id, cost_entry_id)
);

CREATE INDEX execution_span_cost_entries_cost_idx
    ON execution_span_cost_entries (cost_entry_id);

-- Spans are append-only in the same sense the cost ledger is, with one exception that is the whole
-- point of a span: it is opened RUNNING and closed once. So UPDATE is permitted only in that
-- direction -- never RUNNING again, never re-closing a closed span with a different answer, and
-- never rewriting when or what it was.
CREATE OR REPLACE FUNCTION execution_spans_close_once() RETURNS TRIGGER AS $$
BEGIN
    IF OLD.status <> 'RUNNING' THEN
        RAISE EXCEPTION
            'execution_span % is already %; a closed span is not re-decided (OPS-003)',
            OLD.span_id, OLD.status;
    END IF;
    IF NEW.span_id        <> OLD.span_id
    OR NEW.trace_id       <> OLD.trace_id
    OR NEW.span_type      <> OLD.span_type
    OR NEW.start_time     <> OLD.start_time
    OR COALESCE(NEW.parent_span_id, '') <> COALESCE(OLD.parent_span_id, '') THEN
        RAISE EXCEPTION
            'execution_span %: identity, trace, type, parent and start_time are immutable; '
            'closing a span records how it ended, not a different span (OPS-003)',
            OLD.span_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER execution_spans_close_once
    BEFORE UPDATE ON execution_spans
    FOR EACH ROW EXECUTE FUNCTION execution_spans_close_once();

CREATE OR REPLACE FUNCTION execution_spans_are_not_deletable() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        'execution_spans is append-only (OPS-003): deleting %s would remove the record of what '
        'was executed and what it cost', OLD.span_id;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER execution_spans_no_delete
    BEFORE DELETE ON execution_spans
    FOR EACH ROW EXECUTE FUNCTION execution_spans_are_not_deletable();
