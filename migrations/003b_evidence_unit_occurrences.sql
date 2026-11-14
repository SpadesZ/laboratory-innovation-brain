-- 003b_evidence_unit_occurrences.sql
--
-- `v3.3-a18`: SPEC-ISSUE-014 and SPEC-ISSUE-015, ADR-0012. A forward migration; 003a is applied
-- and is not edited.
--
-- TWO DEFECTS, both reproduced against this schema before it was changed.
--
-- (1) `evidence_units` had `evidence_unit_id` as PRIMARY KEY *and* a `project_id` column, while
--     the identity is derived from (artifact_id, structural_path, content_digest) and is
--     project-independent. The same document in two projects therefore collided on the second
--     insert -- and the visible symptom (a UniqueViolation) is not the real one: the first
--     project to ingest a document owned its evidence, and the second got a readable artifact
--     with no evidence at all. Same shape as R-7, one layer down.
--
-- (2) 003a's rule-1 trigger fires only when a unit DECLARES a bound condition, so a raw writer
--     skipped it by declaring nothing. A severed result with `bound_condition_texts` omitted was
--     a fully conformant canonical evidence unit whose interpreting condition existed nowhere.
--
-- WHAT THIS MIGRATION DOES NOT DO: teach PostgreSQL to read scientific prose. Per `v3.3-a13`'s
-- ruling on belief transitions, duplicating the segmenter in SQL would make semantic truth two
-- definitions that drift. The digest below is a byte operation. The judgement half lives in the
-- admission path, which re-runs the recorded segmenter over the artifact's own bytes.

-- ---------------------------------------------------------------------------
-- 1. The segmentation witness (storage-checkable half of SPEC-ISSUE-015)
-- ---------------------------------------------------------------------------

ALTER TABLE evidence_units ADD COLUMN IF NOT EXISTS segmentation_witness TEXT;

-- Must reproduce `lab_brain.core.models.identifiers.segmentation_witness_for` exactly. The
-- length-prefixed encoding is what stops two adjacent fields impersonating one longer field, and
-- `length()` on text counts characters in both languages, so the two agree.
--
-- `tests/integration/test_evidence_units_postgres.py` cross-checks SQL against Python on every
-- run rather than trusting this comment: two implementations of one digest is exactly the drift
-- this repository keeps writing down, and the only honest mitigation is a test that compares them.
CREATE OR REPLACE FUNCTION evidence_unit_expected_witness(
    p_artifact_id TEXT,
    p_structural_path TEXT,
    p_body TEXT,
    p_inherited_context TEXT[],
    p_bound_condition_texts TEXT[],
    p_parser_id TEXT,
    p_parser_version TEXT,
    p_segmenter_id TEXT,
    p_segmenter_version TEXT
) RETURNS TEXT AS $$
DECLARE
    inherited_blob TEXT;
    bound_blob TEXT;
    payload TEXT;
BEGIN
    SELECT coalesce(string_agg(length(v) || ':' || v, '' ORDER BY ord), '')
      INTO inherited_blob
      FROM unnest(coalesce(p_inherited_context, '{}')) WITH ORDINALITY AS t(v, ord);

    SELECT coalesce(string_agg(length(v) || ':' || v, '' ORDER BY ord), '')
      INTO bound_blob
      FROM unnest(coalesce(p_bound_condition_texts, '{}')) WITH ORDINALITY AS t(v, ord);

    payload :=
        length(p_artifact_id)       || ':' || p_artifact_id       ||
        length(p_structural_path)   || ':' || p_structural_path   ||
        length(p_body)              || ':' || p_body              ||
        length(inherited_blob)      || ':' || inherited_blob      ||
        length(bound_blob)          || ':' || bound_blob          ||
        length(p_parser_id)         || ':' || p_parser_id         ||
        length(p_parser_version)    || ':' || p_parser_version    ||
        length(p_segmenter_id)      || ':' || p_segmenter_id      ||
        length(p_segmenter_version) || ':' || p_segmenter_version;

    RETURN 'sha256:' || encode(sha256(convert_to(payload, 'UTF8')), 'hex');
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Backfill. This computes a digest over fields that are already present; it invents no
-- provenance and asserts nothing about whether those rows came from a real segmenter. That
-- question is the admission path's, and backfilling here does not answer it either way -- a
-- forged row gets a consistent witness and is still refused by re-derivation. Stated plainly
-- because "the migration made the bad rows pass" would otherwise be a fair reading.
UPDATE evidence_units
   SET segmentation_witness = evidence_unit_expected_witness(
           artifact_id, structural_path, body, inherited_context, bound_condition_texts,
           parser_id, parser_version, segmenter_id, segmenter_version)
 WHERE segmentation_witness IS NULL;

ALTER TABLE evidence_units ALTER COLUMN segmentation_witness SET NOT NULL;

ALTER TABLE evidence_units DROP CONSTRAINT IF EXISTS evidence_unit_witness_is_wellformed;
ALTER TABLE evidence_units ADD CONSTRAINT evidence_unit_witness_is_wellformed
    CHECK (segmentation_witness ~ '^sha256:[0-9a-f]{64}$');

CREATE OR REPLACE FUNCTION evidence_unit_witness_binds_contents()
RETURNS TRIGGER AS $$
DECLARE
    expected TEXT;
BEGIN
    expected := evidence_unit_expected_witness(
        NEW.artifact_id, NEW.structural_path, NEW.body, NEW.inherited_context,
        NEW.bound_condition_texts, NEW.parser_id, NEW.parser_version,
        NEW.segmenter_id, NEW.segmenter_version);

    IF NEW.segmentation_witness <> expected THEN
        RAISE EXCEPTION
            'evidence unit %: segmentation_witness does not bind its contents. The body, its '
            'bound conditions, its inherited context or its parser/segmenter identity was '
            'changed without re-deriving the witness (SAI 3.3 17.25, v3.3-a18).',
            NEW.evidence_unit_id
            USING ERRCODE = 'check_violation';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS evidence_unit_witness_binds ON evidence_units;
CREATE TRIGGER evidence_unit_witness_binds
    BEFORE INSERT OR UPDATE ON evidence_units
    FOR EACH ROW EXECUTE FUNCTION evidence_unit_witness_binds_contents();

-- ---------------------------------------------------------------------------
-- 2. Project-scoped presence (SPEC-ISSUE-014)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS evidence_unit_occurrences (
    evidence_unit_id    TEXT NOT NULL
                        REFERENCES evidence_units(evidence_unit_id) ON DELETE CASCADE,
    project_id          TEXT NOT NULL REFERENCES projects(project_id),
    -- Redundant against the unit, deliberately. Every presence check also has to ask "may this
    -- actor read the artifact this came from", and carrying it here makes that answerable from
    -- the occurrence alone -- rather than requiring the evidence to be loaded in order to decide
    -- whether the evidence may be read.
    artifact_id         TEXT NOT NULL REFERENCES artifacts(artifact_id),
    ingested_by_actor_id TEXT REFERENCES actors(actor_id),
    first_seen_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (evidence_unit_id, project_id)
);

-- Carry every existing unit into exactly one occurrence, in the project it used to name.
INSERT INTO evidence_unit_occurrences (evidence_unit_id, project_id, artifact_id)
SELECT evidence_unit_id, project_id, artifact_id
  FROM evidence_units
 WHERE project_id IS NOT NULL
    ON CONFLICT (evidence_unit_id, project_id) DO NOTHING;

-- The occurrence's artifact must be the unit's artifact. Cross-table, so it cannot be a CHECK.
-- Without it an occurrence could name a different artifact than the evidence it admits, and the
-- read gate -- which reads the artifact from the occurrence, by design -- would authorise against
-- the wrong bytes.
CREATE OR REPLACE FUNCTION evidence_unit_occurrence_artifact_matches()
RETURNS TRIGGER AS $$
DECLARE
    unit_artifact TEXT;
BEGIN
    SELECT artifact_id INTO unit_artifact
      FROM evidence_units
     WHERE evidence_unit_id = NEW.evidence_unit_id;

    IF unit_artifact IS NULL THEN
        RAISE EXCEPTION 'evidence unit % does not exist', NEW.evidence_unit_id
            USING ERRCODE = 'foreign_key_violation';
    END IF;

    IF unit_artifact <> NEW.artifact_id THEN
        RAISE EXCEPTION
            'occurrence of evidence unit % names artifact % but the unit came from %; the read '
            'gate resolves the artifact through the occurrence, so a mismatch would authorise '
            'against the wrong bytes (SEC-002)',
            NEW.evidence_unit_id, NEW.artifact_id, unit_artifact
            USING ERRCODE = 'check_violation';
    END IF;

    -- An occurrence of evidence in a project the artifact itself is not present in would make
    -- the evidence readable where its source is not (R-7, one layer down).
    IF NOT EXISTS (
        SELECT 1 FROM artifact_occurrences
         WHERE artifact_id = NEW.artifact_id AND project_id = NEW.project_id
    ) THEN
        RAISE EXCEPTION
            'artifact % has no occurrence in project %, so evidence extracted from it cannot be '
            'present there either (SEC-002, ADR-0010)',
            NEW.artifact_id, NEW.project_id
            USING ERRCODE = 'check_violation';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS evidence_unit_occurrence_artifact_matches_unit
    ON evidence_unit_occurrences;
CREATE TRIGGER evidence_unit_occurrence_artifact_matches_unit
    BEFORE INSERT OR UPDATE ON evidence_unit_occurrences
    FOR EACH ROW EXECUTE FUNCTION evidence_unit_occurrence_artifact_matches();

CREATE INDEX IF NOT EXISTS evidence_unit_occurrences_project_idx
    ON evidence_unit_occurrences (project_id, artifact_id);

-- ---------------------------------------------------------------------------
-- 3. Drop the project column, and the index that assumed it
-- ---------------------------------------------------------------------------
--
-- DROPPED, not made nullable -- the ADR-0010 reasoning verbatim: a column that still exists will
-- be read, and a stale project on the identity row is worse than none because it looks
-- authoritative. After this the old read is a hard error rather than a wrong answer.

DROP INDEX IF EXISTS evidence_units_project_path_key;
DROP INDEX IF EXISTS evidence_units_project_artifact_idx;

ALTER TABLE evidence_units DROP COLUMN IF EXISTS project_id;

-- The uniqueness that survives the split is global, not per project: one unit per
-- (artifact, structural path). That is now implied by the derived primary key -- two units with
-- the same artifact and path differ only if their bodies differ, which gives them different ids
-- -- so this index exists to make a re-segmentation attempt fail loudly rather than insert a
-- second boundary set alongside the first.
CREATE UNIQUE INDEX IF NOT EXISTS evidence_units_artifact_path_key
    ON evidence_units (artifact_id, structural_path);

CREATE INDEX IF NOT EXISTS evidence_units_artifact_idx
    ON evidence_units (artifact_id);
