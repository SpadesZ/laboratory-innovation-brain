-- 012x: a debate record says how it kept its model replies honest.
--
-- WHY. Live runs with a real model failed in two ways the record could not show: a reply wrapped
-- in a code fence, and a specialist that shortened a hypothesis id. Both were refused, correctly,
-- and nothing durable said how often replies were refused, repaired or retried, or which cheap
-- checks the hypotheses left unaddressed. `reliability` holds that, for each debate:
--
--   debate_policy     the versioned policy the debate ran under (attempts per role, coverage review)
--   reply_attempts    every role reply: accepted or refused (with the parser's reason), and any
--                     envelope repair made before parsing. The replies themselves stay verbatim in
--                     inference_provenance; this is the index of what happened to each
--   coverage_review   the low-cost executable checks no admitted hypothesis discriminated on, and
--                     for each: certified by a new grounded rival, or declined with a reason
--
-- A record written before this migration has '{}': it ran without any of it, which is the truth.
-- The table stays append-only (005e): the column is filled once, at insert.

ALTER TABLE debate_records ADD COLUMN IF NOT EXISTS reliability JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE debate_records DROP CONSTRAINT IF EXISTS debate_records_reliability_is_object;
ALTER TABLE debate_records ADD CONSTRAINT debate_records_reliability_is_object
    CHECK (jsonb_typeof(reliability) = 'object');
