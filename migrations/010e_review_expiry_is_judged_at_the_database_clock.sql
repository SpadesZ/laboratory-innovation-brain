-- 010e_review_expiry_is_judged_at_the_database_clock.sql
--
-- G0 round 5, Q8 (docs/audit/g0-boundary-round5-2026-11-21/REPORT.md): time sources.
--
-- THE GAP. `review_expire` (`011f`) refuses an expiry whose `p_now` is before the review's
-- declared deadline, and `p_now` is the caller's value. The product's sweep passes its own clock;
-- any writer of SQL could pass next week, and the review is expired days early: a REVIEW_EXPIRY
-- governance event in the declaring person's name, the review terminal, its conflict closed as
-- ACCEPTED_AS_OPEN_QUESTION -- "a way to clear an inconvenient review", in `011f`'s own words.
-- Reproduced: tests/integration/test_g0_review_expiry_clock_postgres.py.
--
-- THE RULE. The same bound the belief gate puts on a writer's time (`011z`): a REVIEW_EXPIRY
-- governance event is not dated more than `belief_write_skew()` after the database clock. A
-- trigger on the event `review_expire` writes first, so the function itself (and the checks
-- `011f` and later migrations attach to it) is unchanged, and every writer is bound, not only the
-- function's callers.

CREATE FUNCTION governance_review_expiry_is_not_in_the_future() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.event_type = 'REVIEW_EXPIRY'
       AND NEW.occurred_at > clock_timestamp() + belief_write_skew() THEN
        RAISE EXCEPTION
            'review expiry %: dated %, after the database clock (%) by more than %; a review '
            'expires when its deadline has passed by the database''s clock, not the caller''s '
            '(010e)', NEW.event_id, NEW.occurred_at, clock_timestamp(), belief_write_skew()
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public;

CREATE TRIGGER governance_review_expiry_is_not_in_the_future
    BEFORE INSERT ON governance_events
    FOR EACH ROW EXECUTE FUNCTION governance_review_expiry_is_not_in_the_future();
