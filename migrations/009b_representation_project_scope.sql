-- 009b_representation_project_scope.sql
--
-- `v3.3-a18` / ADR-0012, consequence of SPEC-ISSUE-014. A forward migration; 009a is applied and
-- is not edited.
--
-- 009a declared `UNIQUE (evidence_unit_id, index_id)` on the reasoning that two rows for one unit
-- in one index would mean a rebuild appended rather than replaced, and a search would rank the
-- same unit twice. That reasoning was correct while a unit belonged to exactly one project.
--
-- After the split it is wrong in a way that reintroduces the defect one layer up: the same
-- evidence is now legitimately present in several projects, each of which needs it in its own
-- retrieval scope, and the old constraint permits only the first. Project B would be unable to
-- index evidence it demonstrably holds -- which is SPEC-ISSUE-014's symptom moved from
-- `evidence_units` to `retrieval_representations`.
--
-- The invariant that was actually wanted is one representation per unit **per project** per
-- index, and it is stated that way now. `project_id` is already NOT NULL on this table and the
-- trigger added by 009a already refuses a representation whose project disagrees with its unit,
-- so widening the key adds no way to write a row that was previously refused.

DROP INDEX IF EXISTS retrieval_representations_unit_index_key;

CREATE UNIQUE INDEX IF NOT EXISTS retrieval_representations_unit_index_project_key
    ON retrieval_representations (evidence_unit_id, index_id, project_id);

-- 009a's trigger reads `evidence_units.project_id`, which 003b has now dropped. Replaced with the
-- occurrence lookup, which is the authority on presence (§17.25.1) -- and is strictly stronger:
-- it refuses a representation for a project the evidence is not present in, where the old version
-- could only compare against the single project the unit happened to name.
CREATE OR REPLACE FUNCTION retrieval_representation_project_matches_unit()
RETURNS TRIGGER AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM evidence_units WHERE evidence_unit_id = NEW.evidence_unit_id
    ) THEN
        RAISE EXCEPTION
            'retrieval representation % names evidence unit %, which does not exist',
            NEW.representation_id, NEW.evidence_unit_id
            USING ERRCODE = 'foreign_key_violation';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM evidence_unit_occurrences
         WHERE evidence_unit_id = NEW.evidence_unit_id
           AND project_id = NEW.project_id
    ) THEN
        RAISE EXCEPTION
            'evidence unit % has no occurrence in project %, so it cannot be indexed for '
            'retrieval there; presence in one project grants nothing in another '
            '(SEC-002, R-7, 17.25.1)',
            NEW.evidence_unit_id, NEW.project_id
            USING ERRCODE = 'check_violation';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
