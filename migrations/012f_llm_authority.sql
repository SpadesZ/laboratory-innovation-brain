-- Research workspace V2, closure. WHO may configure the deployment's language-model routes, and
-- WHO may let a project's evidence reach an external model -- two different authorities.
--
-- `012e` made the LLM runtime deployment-global and let any actor who was an active member of ANY
-- project administer it; the active runtime then declared ONE egress policy for EVERY project,
-- authored by whoever activated it, in RESEARCH mode whatever the project's own privacy mode was.
-- So a member of project A could configure an external route and thereby let project B's evidence
-- leave -- a permission nobody in project B granted (§14.2, §14.3, SEC-001). This migration splits
-- the two authorities and makes each fail closed:
--
--   deployment LLM administration   `llm_administrators`. Granted by the deployment's operator
--                                   (`lab-brain admin llm-admin`, run by whoever holds the database
--                                   credentials), to an active HUMAN actor; revoked, never deleted.
--                                   Every write that names its actor -- a connection created, a
--                                   model locked, a slot bound, a runtime created or activated --
--                                   must name a current administrator. Project membership grants
--                                   none of this.
--   project egress authorization    `project_llm_egress_policies`. A project's OWN declaration of
--                                   which external model connections may receive its evidence, and
--                                   under which labels -- versioned, append-only, authored by an
--                                   active HUMAN member of THAT project holding the LLM_EGRESS
--                                   approval scope (a named scope, as `BUDGET_OVERRUN` is), for
--                                   labels that member is cleared for, and never in Private Mode.
--                                   A global runtime supplies routes; only this row lets a
--                                   project's evidence use one. No row, no egress.
--
-- And LOCAL, which bypasses the egress gate because nothing leaves the machine, may now also be
-- declared of `host.docker.internal`: the Docker host a containerised workspace runs on (the
-- application accepts that name only when it is started as the container deployment).

CREATE TABLE IF NOT EXISTS llm_administrators (
    actor_id         TEXT NOT NULL REFERENCES actors (actor_id),
    granted_at       TIMESTAMPTZ NOT NULL,
    granted_through  TEXT NOT NULL CHECK (granted_through IN ('OPERATOR_CLI')),
    revoked_at       TIMESTAMPTZ,
    PRIMARY KEY (actor_id, granted_at),
    CONSTRAINT llm_administrators_revoked_after_granted
        CHECK (revoked_at IS NULL OR revoked_at >= granted_at)
);

CREATE UNIQUE INDEX IF NOT EXISTS llm_administrators_one_current
    ON llm_administrators (actor_id) WHERE revoked_at IS NULL;

-- A current administrator: an unrevoked grant, to an actor who is still active and HUMAN.
CREATE FUNCTION llm_is_administrator(p_actor TEXT) RETURNS BOOLEAN AS $$
    SELECT EXISTS (
        SELECT 1 FROM llm_administrators g JOIN actors a USING (actor_id)
         WHERE g.actor_id = p_actor AND g.revoked_at IS NULL
           AND a.active AND a.actor_type = 'HUMAN'
    )
$$ LANGUAGE sql STABLE;

CREATE FUNCTION llm_administrators_guard() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'an LLM administrator grant is revoked, never deleted';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NOT EXISTS (SELECT 1 FROM actors WHERE actor_id = NEW.actor_id AND active
                          AND actor_type = 'HUMAN') THEN
            RAISE EXCEPTION 'LLM administration is granted only to an active HUMAN actor, not %',
                NEW.actor_id;
        END IF;
        IF NEW.revoked_at IS NOT NULL THEN
            RAISE EXCEPTION 'a grant is recorded when it is made; revocation comes afterwards';
        END IF;
        RETURN NEW;
    END IF;
    IF (NEW.actor_id, NEW.granted_at, NEW.granted_through) IS DISTINCT FROM
       (OLD.actor_id, OLD.granted_at, OLD.granted_through) OR OLD.revoked_at IS NOT NULL
       OR NEW.revoked_at IS NULL THEN
        RAISE EXCEPTION 'an LLM administrator grant changes only by being revoked, once';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER llm_administrators_guard_trg BEFORE INSERT OR UPDATE OR DELETE ON llm_administrators
    FOR EACH ROW EXECUTE FUNCTION llm_administrators_guard();

-- Every configuration write that names its actor names a current administrator. The `012e`
-- guards are unchanged; these run beside them.
CREATE FUNCTION llm_requires_administrator() RETURNS TRIGGER AS $$
DECLARE
    v_actor TEXT;
BEGIN
    IF TG_TABLE_NAME = 'llm_connections' THEN
        v_actor := NEW.created_by;
    ELSIF TG_TABLE_NAME = 'llm_slot_bindings' THEN
        v_actor := NEW.bound_by;
    ELSIF TG_TABLE_NAME = 'llm_models' THEN
        IF NOT (NEW.lifecycle = 'LOCKED' AND OLD.lifecycle IS DISTINCT FROM 'LOCKED') THEN
            RETURN NEW;
        END IF;
        v_actor := NEW.locked_by;
    ELSIF TG_TABLE_NAME = 'llm_runtimes' THEN
        IF TG_OP = 'INSERT' THEN
            v_actor := NEW.created_by;
        ELSIF NEW.state = 'ACTIVE' AND OLD.state <> 'ACTIVE' THEN
            v_actor := NEW.activated_by;
        ELSE
            RETURN NEW;
        END IF;
    END IF;
    IF v_actor IS NULL OR NOT llm_is_administrator(v_actor) THEN
        RAISE EXCEPTION
            '% is not an LLM administrator of this deployment: the language-model routes are '
            'deployment configuration, and project membership does not grant it', v_actor;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER llm_connections_admin_trg BEFORE INSERT ON llm_connections
    FOR EACH ROW EXECUTE FUNCTION llm_requires_administrator();
CREATE TRIGGER llm_models_admin_trg BEFORE UPDATE ON llm_models
    FOR EACH ROW EXECUTE FUNCTION llm_requires_administrator();
CREATE TRIGGER llm_slot_bindings_admin_trg BEFORE INSERT OR UPDATE ON llm_slot_bindings
    FOR EACH ROW EXECUTE FUNCTION llm_requires_administrator();
CREATE TRIGGER llm_runtimes_admin_trg BEFORE INSERT OR UPDATE ON llm_runtimes
    FOR EACH ROW EXECUTE FUNCTION llm_requires_administrator();

-- FAIL CLOSED ON UPGRADE. A runtime activated under `012e` was activated by someone the old rule
-- let act as an administrator merely for being a member of some project -- exactly the authority
-- this migration withdraws. It is retired, not trusted: an administrator activates a runtime again
-- once one is granted.
UPDATE llm_runtimes SET state = 'RETIRED', retired_at = now() WHERE state = 'ACTIVE';

-- LOCAL may be declared of this machine: loopback, or the Docker host a container runs on.
ALTER TABLE llm_connections DROP CONSTRAINT llm_connections_local_is_loopback;
ALTER TABLE llm_connections ADD CONSTRAINT llm_connections_local_is_this_machine CHECK (
    reach <> 'LOCAL'
    OR base_url ~ '^https?://(127\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}|localhost|\[::1\]|host\.docker\.internal)(:[0-9]{1,5})?(/|$)'
);

CREATE TABLE IF NOT EXISTS project_llm_egress_policies (
    policy_id                TEXT PRIMARY KEY CHECK (policy_id LIKE 'lep:%'),
    project_id               TEXT NOT NULL REFERENCES projects (project_id),
    version                  INTEGER NOT NULL CHECK (version >= 1),
    -- EXTERNAL `llm_connections` this project's evidence may reach. Empty: none (a withdrawal).
    approved_connection_ids  TEXT[] NOT NULL DEFAULT '{}',
    -- Labels that may leave to them. RESTRICTED_NDA never: the gate refuses it under any policy.
    permitted_labels         TEXT[] NOT NULL DEFAULT '{}'
        CHECK (permitted_labels <@ ARRAY['PUBLIC', 'INTERNAL', 'CONFIDENTIAL_LAB']::TEXT[]),
    declared_by_actor_id     TEXT NOT NULL REFERENCES actors (actor_id),
    declared_at              TIMESTAMPTZ NOT NULL,
    UNIQUE (project_id, version),
    CONSTRAINT project_llm_egress_policies_whole CHECK (
        (cardinality(approved_connection_ids) = 0) = (cardinality(permitted_labels) = 0)
    )
);

CREATE FUNCTION project_llm_egress_policies_guard() RETURNS TRIGGER AS $$
DECLARE
    v_member  project_memberships%ROWTYPE;
    v_project projects%ROWTYPE;
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'a project''s egress policy is append-only: declare a new version';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM actors WHERE actor_id = NEW.declared_by_actor_id AND active
                      AND actor_type = 'HUMAN') THEN
        RAISE EXCEPTION 'a project''s egress policy is declared by an active HUMAN actor';
    END IF;
    SELECT * INTO v_member FROM project_memberships
     WHERE actor_id = NEW.declared_by_actor_id AND project_id = NEW.project_id AND active;
    IF NOT FOUND OR NOT ('LLM_EGRESS' = ANY (v_member.approval_scopes)) THEN
        RAISE EXCEPTION
            '% may not declare the external-model egress of %: that needs an active membership '
            'of that project holding the LLM_EGRESS approval scope',
            NEW.declared_by_actor_id, NEW.project_id;
    END IF;
    IF NOT (NEW.permitted_labels <@ v_member.sensitivity_clearance) THEN
        RAISE EXCEPTION '% may authorize only labels they are cleared for in % (%), not %',
            NEW.declared_by_actor_id, NEW.project_id, v_member.sensitivity_clearance,
            NEW.permitted_labels;
    END IF;
    IF NEW.version <> coalesce((SELECT max(version) FROM project_llm_egress_policies
                                 WHERE project_id = NEW.project_id), 0) + 1 THEN
        RAISE EXCEPTION 'project % egress policy version % is not the next one',
            NEW.project_id, NEW.version;
    END IF;
    IF cardinality(NEW.approved_connection_ids) > 0 THEN
        SELECT * INTO v_project FROM projects WHERE project_id = NEW.project_id;
        IF v_project.privacy_mode = 'PRIVATE' THEN
            RAISE EXCEPTION 'project % is in Private Mode: §14.2 allows no egress',
                NEW.project_id;
        END IF;
        IF v_project.archived_at IS NOT NULL THEN
            RAISE EXCEPTION 'project % is archived', NEW.project_id;
        END IF;
        IF cardinality(NEW.approved_connection_ids)
           <> (SELECT count(DISTINCT x) FROM unnest(NEW.approved_connection_ids) x) THEN
            RAISE EXCEPTION 'a connection is approved at most once';
        END IF;
        IF EXISTS (
            SELECT 1 FROM unnest(NEW.approved_connection_ids) x
             WHERE NOT EXISTS (SELECT 1 FROM llm_connections c
                                WHERE c.connection_id = x AND c.reach = 'EXTERNAL'
                                  AND c.lifecycle = 'ENABLED')
        ) THEN
            RAISE EXCEPTION
                'a project approves only ENABLED EXTERNAL model connections (a LOCAL one needs no '
                'egress approval)';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER project_llm_egress_policies_guard_trg
    BEFORE INSERT OR UPDATE OR DELETE ON project_llm_egress_policies
    FOR EACH ROW EXECUTE FUNCTION project_llm_egress_policies_guard();

COMMENT ON TABLE llm_administrators IS
    'Deployment-level LLM administration, granted by the operator to active HUMAN actors. Project '
    'membership grants none of it.';
COMMENT ON TABLE project_llm_egress_policies IS
    'A project''s own, versioned declaration of which EXTERNAL model connections may receive its '
    'evidence and under which labels. No row: no egress for that project, whatever is active.';
