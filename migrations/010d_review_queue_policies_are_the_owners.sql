-- 010d_review_queue_policies_are_the_owners.sql
--
-- G0 trust boundaries, R-4 / T-5 (docs/audit/g0-boundary-round4-2026-11-11/REPORT.md).
--
-- THE GAP. `011e` stores a project's review-queue policy -- capacity, SLA and expiry -- and `011f`
-- made its `declared_by_actor_id` the person whose standing decision authorises automatic expiry:
-- `review_expire` copies it onto the REVIEW_EXPIRY GovernanceEvent, and the expiry closes the
-- review's conflict as ACCEPTED_AS_OPEN_QUESTION (`v3.3-a15`). The operator declares it
-- (`lab-brain admin review-queue`, run as the migrator, which checks the person is an active
-- member), but `lab-brain admin db-roles` granted INSERT, UPDATE and DELETE on every table to the
-- services' role. Reproduced through the real role (evidence/reproduction_before.log): it
-- deactivated the project's queue and declared one that expires every review after a minute, in a
-- member's name -- every later expiry then records a decision that person never made, and human
-- review stops being available. No path to SUPPORTED was found (an expired authority conflict is
-- re-raised by the next attempt); the harm is to the governance record and to availability.
--
-- THE RULE. A review-queue policy is written by the schema owner only (the operator's migrator, or
-- a role that is a member of it) -- the `011s`/`011x`/`011y` boundary, by the same test, for
-- INSERT, UPDATE (the operator's command deactivates the previous policy) and DELETE.
-- `grant_database_roles` revoking the privilege as well is a separate change for the Owner.
--
-- WHAT IS UNCHANGED. Every existing row, and every review priced by one, stays as it is; every role
-- still reads the table.
CREATE FUNCTION review_queue_policies_are_the_owners() RETURNS TRIGGER AS $$
DECLARE
    v_owner OID;
BEGIN
    SELECT relowner INTO v_owner FROM pg_class WHERE oid = TG_RELID;
    IF NOT pg_has_role(current_user, v_owner, 'MEMBER') THEN
        RAISE EXCEPTION
            'review queue policy %@%: declared by the schema owner (the operator''s migrator, '
            '`lab-brain admin review-queue`), not by %; a queue the services could declare would '
            'decide when reviews expire, in a person''s name (010d)',
            COALESCE(NEW.policy_id, OLD.policy_id), COALESCE(NEW.version, OLD.version),
            current_user
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public;

CREATE TRIGGER review_queue_policies_are_the_owners
    BEFORE INSERT OR UPDATE OR DELETE ON review_queue_policies
    FOR EACH ROW EXECUTE FUNCTION review_queue_policies_are_the_owners();
