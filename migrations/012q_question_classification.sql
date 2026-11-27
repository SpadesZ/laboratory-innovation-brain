-- 012q_question_classification.sql
--
-- The research question's classification, recorded with every research run.
--
-- WHY. The question's sensitivity label lived only in the request that opened an episode. A
-- continuation that re-debated (`012k`) rebuilt its request without it and fell back to the
-- default INTERNAL, so a CONFIDENTIAL_LAB or RESTRICTED_NDA question could be reasoned over --
-- and, with an external model route, sent -- below its own classification. Nothing recorded which
-- classification a question was asked under (data-organization audit 2026-10-15, F-01).
--
-- WHAT. `research_runs.question_label` is the label every model-facing step of that run uses:
--   - required for every new run. There is no default: an undeclared question is refused, not
--     filed under a label nobody chose;
--   - a continuation carries the episode's recorded label unchanged, neither lowered nor raised.
--     Reclassifying a question is not something a continuation does;
--   - an episode opened before this migration has none recorded. Its next run declares one,
--     explicitly, and every run after that carries it;
--   - immutable once written.
--
-- HISTORY IS NOT REWRITTEN. Existing rows keep NULL, which reads as "not recorded"; no label is
-- inferred for them.

ALTER TABLE research_runs ADD COLUMN IF NOT EXISTS question_label TEXT;

ALTER TABLE research_runs DROP CONSTRAINT IF EXISTS research_runs_question_label_is_a_label;
ALTER TABLE research_runs ADD CONSTRAINT research_runs_question_label_is_a_label
    CHECK (question_label IS NULL
           OR question_label IN ('RESTRICTED_NDA', 'CONFIDENTIAL_LAB', 'INTERNAL', 'PUBLIC'));

COMMENT ON COLUMN research_runs.question_label IS
    'The classification of the research question this run reasoned under (012q). Required for '
    'every run written after 012q; a continuation carries the episode''s recorded label unchanged; '
    'NULL only on runs recorded before 012q.';

CREATE OR REPLACE FUNCTION research_runs_carry_the_question_label() RETURNS TRIGGER AS $$
DECLARE
    v_recorded TEXT;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF NEW.question_label IS DISTINCT FROM OLD.question_label THEN
            RAISE EXCEPTION
                'research run %''s question classification is recorded once (%); it is not '
                'changed afterwards', OLD.research_run_id,
                coalesce(OLD.question_label, 'not recorded');
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.question_label IS NULL THEN
        RAISE EXCEPTION
            'research run % declares no classification for its question; a question is '
            'classified explicitly, never filed under a default (012q)', NEW.research_run_id;
    END IF;
    SELECT question_label INTO v_recorded FROM research_runs
     WHERE episode_id = NEW.episode_id AND question_label IS NOT NULL
     ORDER BY ordinal DESC
     LIMIT 1;
    IF v_recorded IS NOT NULL AND v_recorded <> NEW.question_label THEN
        RAISE EXCEPTION
            'episode %''s question is classified %; research run % carries %, and a continuation '
            'keeps the question''s classification', NEW.episode_id, v_recorded,
            NEW.research_run_id, NEW.question_label;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS research_runs_carry_the_question_label_trg ON research_runs;
CREATE TRIGGER research_runs_carry_the_question_label_trg
    BEFORE INSERT OR UPDATE ON research_runs
    FOR EACH ROW EXECUTE FUNCTION research_runs_carry_the_question_label();
