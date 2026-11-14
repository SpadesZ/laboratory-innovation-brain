-- 002d_external_access_scopes.sql
--
-- M5 / GH-002. One project's external-access authorization serves that project and no other --
-- held here for every writer of SQL, not only for the snapshot service.
--
-- EXTERNAL_ACCESS_SCOPES. The authored, versioned access policy an adapter read under, as a
-- provider-neutral record: which project it belongs to, which provider, who declared it, and the
-- containers it lets that project read privately. The credential is never here. One `policy_ref`
-- is bound to one project, one provider and one allowlist forever: append-only, so a policy
-- version cannot be re-pointed at another project after material was read under it.
--
-- EXTERNAL_SNAPSHOTS (additive guard). A snapshot naming an access scope is in that scope's
-- project and from that scope's provider. Private or authenticated material names a scope, and its
-- repository is on that scope's allowlist. So project B cannot hold a snapshot read under project
-- A's policy, whichever code path wrote the row.
--
-- In Appendix A's 002 slot beside `002c`; applied after it, because the guard is a trigger on
-- `external_snapshots` and reuses `002c`'s append-only function. A trigger rather than a foreign
-- key, so snapshot rows written before this migration are not re-validated retroactively.

CREATE TABLE IF NOT EXISTS external_access_scopes (
    policy_ref            TEXT PRIMARY KEY CHECK (btrim(policy_ref) <> ''),
    project_id            TEXT NOT NULL REFERENCES projects (project_id),
    provider              TEXT NOT NULL CHECK (btrim(provider) <> ''),
    declared_by_actor_id  TEXT NOT NULL CHECK (btrim(declared_by_actor_id) <> ''),
    private_allowlist     TEXT[] NOT NULL DEFAULT '{}',
    recorded_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS external_access_scopes_project_idx
    ON external_access_scopes (project_id, provider);

DROP TRIGGER IF EXISTS external_access_scopes_are_append_only_trg ON external_access_scopes;
CREATE TRIGGER external_access_scopes_are_append_only_trg
    BEFORE UPDATE OR DELETE ON external_access_scopes
    FOR EACH ROW EXECUTE FUNCTION external_provenance_is_append_only();

CREATE OR REPLACE FUNCTION external_snapshots_read_under_own_scope() RETURNS TRIGGER AS $$
DECLARE
    v_scope external_access_scopes%ROWTYPE;
BEGIN
    IF NEW.access_policy_ref IS NULL THEN
        IF NEW.visibility <> 'PUBLIC' THEN
            RAISE EXCEPTION
                'snapshot % is % material with no access scope; private material is read only '
                'under its own project''s declared scope (GH-002)',
                NEW.snapshot_id, NEW.visibility;
        END IF;
        RETURN NEW;
    END IF;
    SELECT * INTO v_scope FROM external_access_scopes WHERE policy_ref = NEW.access_policy_ref;
    IF NOT FOUND THEN
        RAISE EXCEPTION
            'snapshot % names access scope %, which is not recorded (GH-002)',
            NEW.snapshot_id, NEW.access_policy_ref;
    END IF;
    IF v_scope.project_id <> NEW.project_id OR v_scope.provider <> NEW.provider THEN
        RAISE EXCEPTION
            'snapshot % in project % was read under access scope % of project % / %; one '
            'project''s authorization serves no other (GH-002)',
            NEW.snapshot_id, NEW.project_id, NEW.access_policy_ref, v_scope.project_id,
            v_scope.provider;
    END IF;
    IF NEW.visibility <> 'PUBLIC' AND NOT (
        NEW.repository_identity IS NOT NULL
        AND split_part(NEW.repository_identity, ' ', 2) = ANY (v_scope.private_allowlist)
    ) THEN
        RAISE EXCEPTION
            'snapshot % is % material whose repository is not on access scope %''s allowlist '
            '(GH-002)',
            NEW.snapshot_id, NEW.visibility, NEW.access_policy_ref;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS external_snapshots_read_under_own_scope_trg ON external_snapshots;
CREATE TRIGGER external_snapshots_read_under_own_scope_trg
    BEFORE INSERT ON external_snapshots
    FOR EACH ROW EXECUTE FUNCTION external_snapshots_read_under_own_scope();
