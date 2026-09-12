-- 001_actors_projects.sql
--
-- Actors and projects. Created first because every other table references one or both:
-- §14.4 has no real governance without "who", and retrofitting actor_id foreign keys after
-- evidence exists means backfilling provenance that was never recorded.
--
-- M0a creates the tables and foreign keys only. Enforcement -- ACL checks, clearance
-- comparison, egress gating -- lands in M0b/P4 (SEC-002). The columns exist now so the
-- constraint direction is fixed before data arrives.

CREATE TABLE actors (
    actor_id      TEXT PRIMARY KEY,
    actor_type    TEXT NOT NULL
        CHECK (actor_type IN ('HUMAN', 'SERVICE', 'AGENT_ROLE')),
    display_name  TEXT,
    active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE projects (
    project_id    TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    -- §14.2 privacy mode. Default is the restrictive one: a project created without an
    -- explicit mode must not be the one that permits egress (P9, P28).
    privacy_mode  TEXT NOT NULL DEFAULT 'PRIVATE'
        CHECK (privacy_mode IN ('PRIVATE', 'RESEARCH', 'NOVELTY_AUDIT')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at   TIMESTAMPTZ
);

CREATE TABLE project_memberships (
    actor_id              TEXT NOT NULL REFERENCES actors (actor_id),
    project_id            TEXT NOT NULL REFERENCES projects (project_id),
    role                  TEXT NOT NULL,
    -- Sensitivity labels this actor may read (§14.1). An empty array means no clearance,
    -- which is the fail-closed default rather than "unrestricted".
    sensitivity_clearance TEXT[] NOT NULL DEFAULT '{}',
    approval_scopes       TEXT[] NOT NULL DEFAULT '{}',
    granted_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    granted_by_actor_id   TEXT REFERENCES actors (actor_id),
    PRIMARY KEY (actor_id, project_id)
);

CREATE INDEX project_memberships_project_idx ON project_memberships (project_id);
