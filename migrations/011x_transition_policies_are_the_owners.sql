-- 011x_transition_policies_are_the_owners.sql
--
-- G0 finding F2 (docs/audit/g0-security-assurance-2026-11-04/REPORT.md §5). Owner-only
-- TransitionPolicy registration, approved by the Owner on 2026-11-04 (option (a) of F2).
--
-- THE GAP. 005b made a policy version immutable (no UPDATE, no DELETE) but let any role holding
-- the INSERT privilege register a NEW one, and `lab-brain admin db-roles` granted INSERT on every
-- table to the services' role. A policy is the rule a belief transition is re-derived under: the
-- projection re-runs the decision against the policy the decision names. So a services'-role
-- writer could register `ACTIVE -> SUPPORTED` requiring nothing, record an ALLOW decision and an
-- event under it with an empty snapshot, and every honest reader would fold it in: there is no
-- support in the snapshot for the R8 re-check to refuse.
--
-- THE RULE. A transition policy is registered by the schema owner (the operator's migrator, or a
-- role that is a member of it) -- the same boundary 011s draws for capability declarations, by the
-- same test: `current_user` must be a member of the table's owner. The services' role owns
-- nothing (`grant_database_roles` refuses one that does), so the INSERT privilege alone no longer
-- opens the table; `grant_database_roles` revokes that privilege as well, so the refusal is
-- doubled (a privilege error first, this trigger if the privilege is ever granted by mistake).
--
-- WHY NOT A SECURITY DEFINER REGISTRATION FUNCTION. The only policies the product may register are
-- the ones its code declares (the admission policy and the installed vertical's). SQL cannot read
-- that code; a definer function callable by the services would need an allow-list the owner
-- maintains, which is the owner registering the policies with one more step. So the owner
-- registers them directly (`lab-brain admin register-policies`, run as the migrator at start) and
-- the services only read.
--
-- WHAT IS UNCHANGED. Rows already registered stay exactly as they are and stay readable by every
-- role that could read them; every decision and event citing them still re-derives. UPDATE and
-- DELETE stay refused for everyone (005b). Only INSERT changes, and only for non-owners.
CREATE FUNCTION transition_policies_are_registered_by_the_owner() RETURNS TRIGGER AS $$
DECLARE
    v_owner OID;
BEGIN
    SELECT relowner INTO v_owner FROM pg_class WHERE oid = TG_RELID;
    IF NOT pg_has_role(current_user, v_owner, 'MEMBER') THEN
        RAISE EXCEPTION
            'transition policy %@%: a policy is registered by the schema owner (the operator''s '
            'migrator, `lab-brain admin register-policies`), not by %; a policy the services '
            'could write would let them choose the rule their own transitions are judged by (011x)',
            NEW.policy_id, NEW.version, current_user
            USING ERRCODE = 'insufficient_privilege';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = pg_catalog, public;

CREATE TRIGGER transition_policies_registered_by_the_owner
    BEFORE INSERT ON transition_policies
    FOR EACH ROW EXECUTE FUNCTION transition_policies_are_registered_by_the_owner();
