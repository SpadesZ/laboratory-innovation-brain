-- 003a_evidence_units.sql
--
-- EVI-010 / §6.22 / §17.25 / ADR-0011. The canonical evidence body.
--
-- WHY 003a AND NOT 012. Appendix A reserves 012 for `ingestion_items_errors`, which is UX-001's
-- projection and a later slice. An EvidenceUnit is what an Attestation is made from, so it
-- extends 003 (claims/observations/attestations) by the same convention 002a and 004a follow.
-- Its retrieval counterpart extends 009 (vectors) and is a separate migration, because ADR-0011's
-- whole point is that the two have separate lifetimes -- including at the schema level, where
-- dropping every index row must be expressible without touching this table.
--
-- WHAT THIS TABLE MAY NOT GROW. An embedding column. §17.25 puts vectors on
-- `retrieval_representations`, and a nullable `embedding` here would make re-embedding an UPDATE
-- on scientific data. The schema-drift guard compares this DDL against §17.25's canonical block
-- and the Pydantic model on every CI run, so adding one fails rather than being noticed later.

CREATE TABLE IF NOT EXISTS evidence_units (
    -- Derived, never minted: 'evu:sha256:<hex>' over (artifact_id, structural_path,
    -- content_digest). The CHECK pins the shape; the derivation itself is enforced in the model,
    -- because recomputing a length-prefixed SHA-256 in SQL would be a second implementation of
    -- an identity rule and the two would drift (the reasoning v3.3-a13 applies to evaluate()).
    evidence_unit_id        TEXT PRIMARY KEY,
    project_id              TEXT NOT NULL REFERENCES projects(project_id),
    artifact_id             TEXT NOT NULL REFERENCES artifacts(artifact_id),
    source_work_id          TEXT REFERENCES source_works(source_work_id),

    unit_type               TEXT NOT NULL,
    structural_path         TEXT NOT NULL,
    locator                 JSONB NOT NULL,
    body                    TEXT NOT NULL,
    content_digest          TEXT NOT NULL,

    -- §6.22 rule 3(a)/4 fallback lineage. All three together or all three absent -- see the
    -- CHECK below. Partial lineage is the shape worth refusing: a sub-unit with a parent and no
    -- reason is indistinguishable from a token splitter that merely recorded a parent.
    parent_unit_id          TEXT,
    subdivision_index       INTEGER,
    subdivision_reason      TEXT,
    inherited_context       TEXT[] NOT NULL DEFAULT '{}',

    conditions              JSONB NOT NULL DEFAULT '{}'::jsonb,
    conditions_schema_version TEXT,
    -- §6.22 rule 1. The conditions this unit declares it cannot be read without. Enforced
    -- against `body || inherited_context` by the trigger below.
    bound_condition_texts   TEXT[] NOT NULL DEFAULT '{}',

    table_context           JSONB,
    figure_context          JSONB,

    -- §17.25's `provenance`, stored decomposed for the same reason §17.17's `cost` is: these are
    -- queried individually. §6.18's contamination rollback is the query "which units did
    -- segmenter version X cut", and a JSONB blob makes that a scan.
    parser_id               TEXT NOT NULL,
    parser_version          TEXT NOT NULL,
    segmenter_id            TEXT NOT NULL,
    segmenter_version       TEXT NOT NULL,
    segmented_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    token_limit             INTEGER,

    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT evidence_unit_id_is_derived
        CHECK (evidence_unit_id ~ '^evu:sha256:[0-9a-f]{64}$'),
    CONSTRAINT evidence_unit_digest_is_wellformed
        CHECK (content_digest ~ '^sha256:[0-9a-f]{64}$'),
    CONSTRAINT evidence_unit_type_is_known
        CHECK (unit_type IN ('SECTION', 'PROSE', 'TABLE', 'FIGURE', 'CODE', 'LOG')),
    CONSTRAINT evidence_unit_structural_path_not_blank
        CHECK (length(trim(structural_path)) > 0),

    -- Lineage is complete or absent. Never partial.
    CONSTRAINT evidence_unit_subdivision_is_all_or_nothing
        CHECK (
            (parent_unit_id IS NULL AND subdivision_index IS NULL AND subdivision_reason IS NULL)
         OR (parent_unit_id IS NOT NULL AND subdivision_index IS NOT NULL
             AND subdivision_reason IS NOT NULL)
        ),
    CONSTRAINT evidence_unit_subdivision_reason_is_known
        CHECK (subdivision_reason IS NULL
               OR subdivision_reason IN ('OVERSIZED_UNIT', 'BENCHMARK_BASELINE')),
    CONSTRAINT evidence_unit_is_not_its_own_parent
        CHECK (parent_unit_id IS NULL OR parent_unit_id <> evidence_unit_id),
    CONSTRAINT evidence_unit_inherits_only_from_a_parent
        CHECK (parent_unit_id IS NOT NULL OR cardinality(inherited_context) = 0),

    -- §6.22 rules 5 and 6, in both directions. A TABLE with no table_context has lost the
    -- headers and units its values need; a PROSE row carrying one means the segmenter
    -- mislabelled something, and the mislabel would propagate into retrieval.
    CONSTRAINT evidence_unit_table_context_matches_type
        CHECK ((unit_type = 'TABLE') = (table_context IS NOT NULL)),
    CONSTRAINT evidence_unit_figure_context_matches_type
        CHECK ((unit_type = 'FIGURE') = (figure_context IS NOT NULL))
);

-- §6.22 rule 1, enforced in SQL rather than only in Python.
--
-- This is a CHECK-shaped rule that cannot be a CHECK: it compares one column against the
-- concatenation of two others element-wise, which PostgreSQL will not let a CHECK do portably
-- against an array. A trigger is the honest way to say it.
--
-- Note what it does NOT do: decide which conditions are bound. That judgement is the segmenter's
-- and lives in one place (`bind_condition_result_groups`). This only refuses a row that declares
-- a condition it does not contain -- the same division of labour v3.3-a13 fixed for belief
-- transitions, where SQL checks the binding and Python owns the semantics.
CREATE OR REPLACE FUNCTION evidence_unit_conditions_are_present()
RETURNS TRIGGER AS $$
DECLARE
    available TEXT;
    condition_text TEXT;
BEGIN
    IF cardinality(NEW.bound_condition_texts) = 0 THEN
        RETURN NEW;
    END IF;

    available := NEW.body || E'\n' || array_to_string(NEW.inherited_context, E'\n');

    FOREACH condition_text IN ARRAY NEW.bound_condition_texts LOOP
        IF position(condition_text IN available) = 0 THEN
            RAISE EXCEPTION
                'evidence unit % declares a condition it does not contain: %. The result has '
                'been separated from what makes it interpretable (SAI 3.3 6.22 rule 1, EVI-010). '
                'Nothing downstream can detect this, because no field is missing.',
                NEW.evidence_unit_id, left(condition_text, 120)
                USING ERRCODE = 'check_violation';
        END IF;
    END LOOP;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS evidence_unit_conditions_present ON evidence_units;
CREATE TRIGGER evidence_unit_conditions_present
    BEFORE INSERT OR UPDATE ON evidence_units
    FOR EACH ROW EXECUTE FUNCTION evidence_unit_conditions_are_present();

-- Retrieval and admission both go through project scope first (SEC-002). A unit is never read
-- without one, so the index leads with it.
CREATE INDEX IF NOT EXISTS evidence_units_project_artifact_idx
    ON evidence_units (project_id, artifact_id);

-- §6.18 contamination rollback: "which units did this segmenter version cut".
CREATE INDEX IF NOT EXISTS evidence_units_segmenter_version_idx
    ON evidence_units (segmenter_id, segmenter_version);

-- Fallback subdivisions of one parent, in order.
CREATE INDEX IF NOT EXISTS evidence_units_parent_idx
    ON evidence_units (parent_unit_id, subdivision_index)
    WHERE parent_unit_id IS NOT NULL;

-- One unit per (artifact, structural path) per project. The identity derivation already makes
-- two units with the same path and different bodies distinct ids; this stops the same path being
-- occupied twice within a project, which would mean a re-segmentation silently shadowed the old
-- boundaries instead of superseding them. Re-segmentation is a known limitation (ADR-0011) and
-- this constraint is what makes attempting it fail loudly rather than duplicate.
CREATE UNIQUE INDEX IF NOT EXISTS evidence_units_project_path_key
    ON evidence_units (project_id, artifact_id, structural_path);
