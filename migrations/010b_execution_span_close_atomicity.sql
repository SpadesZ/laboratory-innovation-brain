-- 010b_execution_span_close_atomicity.sql
--
-- OPS-003 / §17.19.1. Two observability-integrity defects found by audit of P6 (`ddcea712`).
--
-- 010a is applied and is NOT edited: the checksum ledger exists to refuse that (AGT-004). This
-- migration alters the schema forward.
--
-- ============================================================================================
-- DEFECT 1: a span's terminal status and its cost refs could be permanently split.
-- ============================================================================================
--
-- `SqlSpanRepository.close()` issued the status UPDATE and then one INSERT per cost ref. Under the
-- autocommit connection those stores require, each statement commits on its own, so:
--
--     close(span, SUCCEEDED, [cost:valid, cost:missing])
--       1. span -> SUCCEEDED        committed
--       2. cost:valid link          committed
--       3. cost:missing             FK violation, raises
--     result: span SUCCEEDED, cost refs partial, and the close-once trigger refuses any retry.
--
-- Reproduced against the live schema before this fix, not reasoned about. The two facts OPS-003
-- exists to make reliable -- status and cost refs -- were exactly the pair that could diverge, and
-- permanently, because the span can never be closed again.
--
-- THE FIX IS ONE STATEMENT. `execution_span_close` does the whole close, so under autocommit the
-- statement's own atomicity covers it: any invalid cost ref aborts the statement and the span stays
-- RUNNING with no links. This is deliberately not "wrap it in a transaction in Python" -- these
-- stores refuse a non-autocommit connection precisely because they must not commit a connection
-- they do not own (see `require_durable_connection`), so the atomic unit has to be the statement.
--
-- Cost refs are validated BEFORE the UPDATE as well, so the ordinary failure writes nothing at all
-- rather than relying on rollback. The FK stays as the backstop.
CREATE OR REPLACE FUNCTION execution_span_close(
    p_span_id        TEXT,
    p_status         TEXT,
    p_end_time       TIMESTAMPTZ,
    p_metadata       JSONB,
    p_cost_entry_ids TEXT[]
) RETURNS BOOLEAN AS $$
DECLARE
    v_missing TEXT;
    v_refs    TEXT[] := COALESCE(p_cost_entry_ids, ARRAY[]::TEXT[]);
BEGIN
    IF p_status = 'RUNNING' THEN
        RAISE EXCEPTION
            'execution_span_close: % cannot be closed to RUNNING; closing records how an '
            'interval ended', p_span_id;
    END IF;

    SELECT ref INTO v_missing
      FROM unnest(v_refs) AS ref
     WHERE NOT EXISTS (SELECT 1 FROM cost_entries WHERE cost_entry_id = ref)
     LIMIT 1;

    IF v_missing IS NOT NULL THEN
        RAISE EXCEPTION
            'execution_span_close: cost entry % does not exist, so span % stays RUNNING with no '
            'links. A span whose status is committed and whose cost refs are not is the one '
            'failure OPS-003 must not have', v_missing, p_span_id;
    END IF;

    UPDATE execution_spans
       SET status   = p_status,
           end_time = p_end_time,
           metadata = COALESCE(p_metadata, metadata)
     WHERE span_id = p_span_id
       AND status  = 'RUNNING';

    -- Not an exception: losing a concurrent close is an ordinary outcome, and the row lock the
    -- UPDATE took means the loser re-evaluates `status = 'RUNNING'` against the committed row and
    -- matches nothing. Exactly one caller gets TRUE.
    IF NOT FOUND THEN
        RETURN FALSE;
    END IF;

    INSERT INTO execution_span_cost_entries (span_id, cost_entry_id)
    SELECT p_span_id, ref FROM unnest(v_refs) AS ref
    ON CONFLICT DO NOTHING;

    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;


-- ============================================================================================
-- DEFECT 2: a parent span was not required to be in the same trace.
-- ============================================================================================
--
-- 010a's FK was `parent_span_id REFERENCES execution_spans (span_id)` -- parent must exist, and
-- nothing about which trace it belongs to. So this was accepted:
--
--     parent P, trace_id = A
--     child  C, trace_id = B, parent_span_id = P
--
-- and `trace('B')` then returned only C. Reconstruction found C's parent absent from the trace and
-- treated C as a root, so a corrupt cross-trace edge was silently laundered into a plausible tree.
-- A reconstruction that repairs its own input is worse than one that fails: the output looks like
-- evidence.
--
-- The composite FK makes it unrepresentable. `span_id` is already the primary key, so the UNIQUE
-- below adds no uniqueness -- it exists because a composite foreign key needs a matching unique
-- constraint to point at. Stated rather than left looking redundant.
ALTER TABLE execution_spans
    ADD CONSTRAINT execution_spans_span_is_unique_within_its_trace UNIQUE (span_id, trace_id);

-- Dropped by its exact auto-generated name rather than with IF EXISTS. If 010a ever produced a
-- different name, this migration must fail loudly instead of quietly leaving the weak FK in place,
-- which would restore the defect while reporting success.
ALTER TABLE execution_spans
    DROP CONSTRAINT execution_spans_parent_span_id_fkey;

-- MATCH SIMPLE (the default) skips the check when any referencing column is NULL, so a root span
-- with no parent is still allowed -- `trace_id` is NOT NULL, so `parent_span_id IS NULL` is the
-- only way that happens, which is exactly the intended case.
ALTER TABLE execution_spans
    ADD CONSTRAINT execution_spans_parent_is_in_the_same_trace
        FOREIGN KEY (parent_span_id, trace_id)
        REFERENCES execution_spans (span_id, trace_id);
