-- 003c_attestation_evidence_unit.sql
--
-- `v3.3-a18`, §17.25's durable-reference clause. A forward migration.
--
-- §17.25 has always said "Attestation 引用 EvidenceUnit 時以 evidence_unit_id 記錄". M1-P1
-- implemented that as a parameter of the admission call, which satisfies the sentence and not the
-- requirement: persist the attestation, restart, reload it, and it can no longer say which passage
-- it read.
--
-- The locator does not close the gap. A document routinely has several evidence units at one
-- human-facing position -- which is exactly why `structural_path` is part of evidence identity and
-- the locator is not -- so "§3" narrows a citation to a section and not to the sentence that was
-- actually read.
--
-- NULLABLE, and that is not a weakening. §17.2's one-source rule is unchanged: an Attestation may
-- witness a Run or a SourceWork rather than a parsed document unit, and those have no evidence unit
-- to name. What the admission gate enforces is the conditional obligation -- an admission that
-- *cites* a unit must submit an attestation that *records* the same one -- which a NOT NULL column
-- could not express without forbidding the other two source kinds.

ALTER TABLE attestations
    ADD COLUMN IF NOT EXISTS evidence_unit_id TEXT
        REFERENCES evidence_units(evidence_unit_id);

-- Shape check rather than a bare FK, for the same reason `evidence_units` has one: a caller
-- passing a `rrp:` representation id or a raw `sha256:` digest here would be writing a reference
-- that resolves to nothing, and the FK alone reports that as "not found" long after the fact.
ALTER TABLE attestations DROP CONSTRAINT IF EXISTS attestation_evidence_unit_is_wellformed;
ALTER TABLE attestations ADD CONSTRAINT attestation_evidence_unit_is_wellformed
    CHECK (evidence_unit_id IS NULL OR evidence_unit_id ~ '^evu:sha256:[0-9a-f]{64}$');

-- The evidence an attestation cites must be present in the attestation's own project.
-- Cross-table, so it cannot be a CHECK. Without it an attestation in project B could cite
-- evidence only project A holds, and the citation would resolve -- the R-7 leak arriving through
-- the witness rather than through the read gate (SEC-002, §17.25.1).
CREATE OR REPLACE FUNCTION attestation_evidence_unit_is_present()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.evidence_unit_id IS NULL THEN
        RETURN NEW;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM evidence_unit_occurrences
         WHERE evidence_unit_id = NEW.evidence_unit_id
           AND project_id = NEW.project_id
    ) THEN
        RAISE EXCEPTION
            'attestation % cites evidence unit %, which has no occurrence in project %; '
            'presence in one project grants nothing in another (SEC-002, R-7, 17.25.1)',
            NEW.attestation_id, NEW.evidence_unit_id, NEW.project_id
            USING ERRCODE = 'check_violation';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS attestation_evidence_unit_present ON attestations;
CREATE TRIGGER attestation_evidence_unit_present
    BEFORE INSERT OR UPDATE ON attestations
    FOR EACH ROW EXECUTE FUNCTION attestation_evidence_unit_is_present();

-- "Which attestations read this passage" -- the query the durable reference exists to make
-- answerable, and the one a contamination review starts from when a segmenter version is
-- quarantined (§6.18).
CREATE INDEX IF NOT EXISTS attestations_evidence_unit_idx
    ON attestations (evidence_unit_id)
    WHERE evidence_unit_id IS NOT NULL;
