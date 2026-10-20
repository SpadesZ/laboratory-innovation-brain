-- 003d_inference_provenance.sql
--
-- LLM-001 / §17.14 / §7.6.
--
-- WHY THIS MIGRATION EXISTS AT ALL, stated plainly: the M1 exit gate says *all scientific LLM
-- calls persist bundle+provenance*, and the previous implementation built an
-- `InferenceProvenance` in memory and returned it. "Persist" was doing no work.
--
-- NUMBERING. Extends `003`, not `012`. §17.2's Attestation carries
-- `extraction_provenance.inference_provenance_id`, so this table is the resolution target for a
-- reference the claims/observations/attestations slot already declares -- and a suffixed
-- migration must extend a reserved Appendix A number (`test_a_suffixed_migration_extends_a_
-- number_that_exists`). Putting it under `012` would file the record of what a model said beside
-- the inbox rows that display failures.
--
-- ONE BUNDLE IDENTITY, NOT TWO. `evidence_bundle_hash` is EVI-006's canonical hash, stored as the
-- string it already is. There is deliberately no foreign key to `evidence_bundles`:
--
--   * §17.14.1 makes the hash the identity, and the same retrieval legitimately recurs as several
--     bundle rows with the same hash -- so an FK would have to pick one of them arbitrarily;
--   * an inference must stay checkable when its bundle row is unreachable. The hash is what lets
--     "was this the evidence" be answered from the provenance alone.
--
-- Recorded here rather than left implicit because "add an FK for integrity" is the obvious later
-- edit, and it would quietly replace a content identity with a row identity.

CREATE TABLE inference_provenance (
    inference_id            TEXT PRIMARY KEY,

    -- §17.14's fields, in its order.
    role                    TEXT NOT NULL,
    logical_slot            TEXT NOT NULL CHECK (
        logical_slot IN (
            'HYPOTHESIS', 'CRITIQUE', 'EXTRACTION', 'PLANNING',
            'SUMMARISATION', 'RELATION', 'EMBEDDING'
        )
    ),
    provider                TEXT,
    model_id                TEXT NOT NULL,
    model_version           TEXT NOT NULL,
    prompt_id               TEXT NOT NULL,
    prompt_version          TEXT NOT NULL,

    -- EVI-006's canonical hash. See the header for why this is not a foreign key.
    evidence_bundle_hash    TEXT NOT NULL,
    source_policy_version   TEXT,
    parameters              JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at              TIMESTAMPTZ NOT NULL,
    trace_id                TEXT NOT NULL,

    -- Not in §17.14, and the reason is stated rather than assumed. SEC-002 scopes every read by
    -- project membership, and an inference is read by UX-003's diagnostics and by the belief
    -- path; §17.14 reaches the project through `trace_id`, but a trace is not a scoped entity.
    -- Same argument `schema_drift.UNBOUND` records for Job and Run.
    project_id              TEXT NOT NULL REFERENCES projects (project_id),

    -- The scientific output itself. §17.14 describes the provenance of an object rather than the
    -- object, but M1's exit clause is about the CALL persisting, and provenance with no record of
    -- what it is the provenance *of* cannot answer "which answer did this model give". Stored as
    -- text because at M1 every scientific output is text; a typed object reference belongs with
    -- the slice that introduces typed outputs.
    output_text             TEXT NOT NULL,

    CONSTRAINT inference_provenance_bundle_hash_present
        CHECK (btrim(evidence_bundle_hash) <> ''),
    CONSTRAINT inference_provenance_model_present
        CHECK (btrim(model_id) <> '' AND btrim(model_version) <> ''),
    CONSTRAINT inference_provenance_prompt_present
        CHECK (btrim(prompt_id) <> '' AND btrim(prompt_version) <> '')
);

CREATE INDEX inference_provenance_project_idx ON inference_provenance (project_id, created_at DESC);
CREATE INDEX inference_provenance_trace_idx   ON inference_provenance (trace_id);
CREATE INDEX inference_provenance_bundle_idx  ON inference_provenance (evidence_bundle_hash);

-- APPEND-ONLY. §7.6 makes provenance the thing a belief transition's admissibility is judged
-- against, so a row that can be edited after the fact is a record that can be made to say the
-- inference came from a model it did not. The same reasoning `004b` applies to bundles and `011a`
-- to conflicts.
CREATE FUNCTION inference_provenance_is_append_only() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        'inference_provenance is append-only; % on % would let a stored inference be made to '
        'claim a model, prompt or evidence bundle it did not come from, and §7.6 judges belief '
        'admissibility against exactly that record',
        TG_OP, COALESCE(OLD.inference_id, NEW.inference_id);
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER inference_provenance_no_update
    BEFORE UPDATE OR DELETE ON inference_provenance
    FOR EACH ROW EXECUTE FUNCTION inference_provenance_is_append_only();

COMMENT ON TABLE inference_provenance IS
    'LLM-001 / §17.14. Every scientific LLM output, with the model, prompt and canonical '
    'EvidenceBundle hash that produced it. Append-only: §7.6 judges whether a stored inference '
    'may found a belief transition by reading this row.';
