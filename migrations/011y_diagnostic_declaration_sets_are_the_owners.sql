-- 011y_diagnostic_declaration_sets_are_the_owners.sql
--
-- G0 trust boundaries, R-2 of the F2 closure (docs/audit/g0-trust-boundaries-2026-11-08/REPORT.md).
--
-- THE GAP. `012p` registers the DomainPack's diagnostic declarations in
-- `diagnostic_declaration_sets`, and the confirmation rule every writer is held to reads them
-- (`diagnostic_declarations.active`, `cwg_bound_class`, `cwg_relation_warrant`,
-- `confirmation_rule_breaches`). `lab-brain admin db-roles` granted INSERT on every table to the
-- services' role, so a services' writer could register a set of its own. Reproduced through the
-- real role (evidence/reproduction_before.log):
--   * a class declaring an uncatalogued account's observed outcome as its signature made the SQL
--     rule read that link as DOMAIN-warranted -- a warrant nobody accountable gave;
--   * a class declaring a confirmed cause's own observation as another mechanism's signature made
--     the SQL rule refuse that confirmation;
--   * any row the code does not declare makes `SqlDeclarationSetStore.ensure` refuse every later
--     research run, and because the table is append-only for every role (012p), the operator
--     cannot remove it: a permanent denial of service from one INSERT.
--
-- THE RULE. A declaration set is registered by the schema owner (the operator's migrator, or a role
-- that is a member of it) -- the boundary 011s draws for capability declarations and 011x for
-- transition policies, by the same test. `grant_database_roles` also revokes the privilege, so the
-- refusal is doubled. The product registers its sets through `lab-brain admin register-policies`
-- (run as the migrator at start); under the services' role a missing set refuses the run before
-- anything is written.
--
-- WHAT IS UNCHANGED. Rows already registered stay exactly as they are and stay readable; UPDATE and
-- DELETE stay refused for everyone (012p). Only INSERT changes, and only for non-owners.
CREATE FUNCTION diagnostic_declaration_sets_are_registered_by_the_owner() RETURNS TRIGGER AS $$
DECLARE
    v_owner OID;
BEGIN
    SELECT relowner INTO v_owner FROM pg_class WHERE oid = TG_RELID;
    IF NOT pg_has_role(current_user, v_owner, 'MEMBER') THEN
        RAISE EXCEPTION
            'declaration set %@%: a diagnostic declaration set is registered by the schema owner '
            '(the operator''s migrator, `lab-brain admin register-policies`), not by %; a set the '
            'services could write would decide what the confirmation rule counts as warranted (011y)',
            NEW.set_id, NEW.version, current_user
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public;

-- Named to fire before `diagnostic_declaration_sets_are_well_formed` (BEFORE triggers fire in name
-- order), so a non-owner is told who may write before being told what is malformed.
CREATE TRIGGER diagnostic_declaration_sets_a_registered_by_the_owner
    BEFORE INSERT ON diagnostic_declaration_sets
    FOR EACH ROW EXECUTE FUNCTION diagnostic_declaration_sets_are_registered_by_the_owner();
