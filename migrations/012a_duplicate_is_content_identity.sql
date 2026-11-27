-- 012a_duplicate_is_content_identity.sql
--
-- Repairs one CHECK in `012`. UX-001 / §17.22 / ART-001.
--
-- `012` shipped with:
--
--     CONSTRAINT ingestion_items_not_its_own_duplicate
--         CHECK (duplicate_of_artifact_id IS NULL OR duplicate_of_artifact_id <> raw_artifact_id)
--
-- which reads as an obvious sanity rule and is, under ART-001, unsatisfiable for the only case it
-- was meant to describe.
--
-- §17.22's `duplicate_of_artifact_id` means *identical bytes -- no new scientific value*. ART-001
-- makes `artifact_id = f(content bytes)`, total and injective. So the second arrival of identical
-- bytes computes the SAME artifact id as the first: there is no second artifact row to point at,
-- because content addressing is precisely the decision not to make one. The constraint therefore
-- forbade writing the correct value and permitted only wrong ones -- a pointer at some *other*
-- artifact, which would be a claim that two different documents are byte-identical.
--
-- The constraint was written against an implicit model where storage assigns ids and a duplicate
-- gets its own row. That model is not this one, and `002_artifacts_sourceworks.sql` has said so
-- since M0a. The rule that survives is not a column comparison at all:
--
--     an item is a duplicate when an EARLIER item in the same project already holds this
--     artifact
--
-- which is a statement about two items, not about one item's two columns, and is derived on read
-- from `ingestion_items` itself rather than asserted by a writer.
--
-- WHY THIS IS A NEW MIGRATION AND NOT AN EDIT TO 012. Forward-only, always: `012` is applied in
-- every environment that has run the suite since it landed, and editing an applied file makes the
-- checksum guard fire -- correctly, because a file that changed after being applied means two
-- databases claiming the same schema version have different schemas.
--
-- NOTHING ELSE IN 012 MOVES. The absent `state` column stays absent; `error_records`'
-- exhausted-retry and unretryable-class CHECKs are untouched; the deferred stage/error trigger is
-- untouched. This drops one constraint that could not be satisfied.

ALTER TABLE ingestion_items
    DROP CONSTRAINT IF EXISTS ingestion_items_not_its_own_duplicate;

COMMENT ON COLUMN ingestion_items.duplicate_of_artifact_id IS
    '§17.22: identical bytes, so no new scientific value. Under ART-001 this equals '
    '`raw_artifact_id` -- content addressing means the second arrival of the same bytes IS the '
    'same artifact. Set when an earlier item in this project already holds it; a duplicate is a '
    'relation between two ITEMS, which is why no column-level CHECK can express it.';
