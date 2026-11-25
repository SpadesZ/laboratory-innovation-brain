-- 002f_external_snapshot_quarantine_is_decided_by_the_owner.sql
--
-- G0 round 6, residual Q-r (docs/audit/g0-boundary-round6-2026-11-24/REPORT.md).
--
-- THE GAP. `002e` let any writer add an external-snapshot quarantine ("quarantining more is the
-- fail-safe direction"). Since `005f` (adopted by the Owner as the one definition of a counted
-- belief event) a stored snapshot quarantine excludes every belief event its attestations
-- triggered, so the services' role could demote any belief that rested on external evidence by
-- quarantining the snapshot behind it: fail-safe, but a denial of service on beliefs nobody
-- decided (reproduced, tests/e2e/test_g0_boundary_round6_postgres.py,
-- evidence/reproduction_before.log).
--
-- THE RULE. A new quarantine is the schema owner's decision (the `012t` membership test), and
-- records who decided it and why; the database stamps the time and the login role. Rows already
-- there (the `002e` upgrade's own) are kept as written. The direction is unchanged: quarantine is
-- append-only and irreversible, and a quarantined snapshot still counts nowhere. What changes is
-- only who may add one.
--
-- PRIVILEGES. Nothing is granted or revoked; the guard refuses a non-owner whatever the grants.

ALTER TABLE external_snapshot_quarantine
    ADD COLUMN decided_by_actor_id TEXT REFERENCES actors (actor_id),
    ADD COLUMN reason              TEXT,
    ADD COLUMN recorded_by         TEXT;

CREATE FUNCTION external_snapshot_quarantine_is_decided() RETURNS TRIGGER AS $$
DECLARE
    v_owner OID;
BEGIN
    SELECT relowner INTO v_owner FROM pg_class WHERE oid = TG_RELID;
    IF NOT pg_has_role(current_user, v_owner, 'MEMBER') THEN
        RAISE EXCEPTION
            'external snapshot %: a quarantine is the schema owner''s decision, not %''s; since '
            '005f it demotes every belief its evidence triggered (002f)', NEW.snapshot_id,
            current_user
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    IF NEW.decided_by_actor_id IS NULL OR length(btrim(coalesce(NEW.reason, ''))) < 10 THEN
        RAISE EXCEPTION
            'external snapshot %: a quarantine records the person who decided it and why, in at '
            'least ten characters (002f)', NEW.snapshot_id;
    END IF;
    NEW.quarantined_at := clock_timestamp();
    NEW.recorded_by := session_user;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public;

-- Named to fire after `002e`'s project check (BEFORE triggers run in name order).
CREATE TRIGGER external_snapshot_quarantine_is_decided_trg
    BEFORE INSERT ON external_snapshot_quarantine
    FOR EACH ROW EXECUTE FUNCTION external_snapshot_quarantine_is_decided();
