-- Research workspace V2. Configurable language-model routes for the research service.
--
-- §7.3's contract is CognitiveRole -> LogicalSlot -> ModelSlot: a role never names a model. The
-- role-to-slot table is code (`cognition.routing`) and stays read-only. What a deployment
-- configures is which model serves each LOGICAL SLOT. This migration records that configuration,
-- and holds the rules that make it trustworthy against every writer:
--
--   connection    an endpoint and a REFERENCE to its credential. No credential is ever stored here:
--                 `secret_ref` names where it lives (an environment variable, or the operating
--                 system's credential store) and `secret_fingerprint` shows which one it is
--                 (****abcd, a salted HMAC, never a fragment of the key). A connection's
--                 configuration state (`lifecycle`) is not its health: health is a separate,
--                 append-only log of checks, so "configured and enabled, but the endpoint is down
--                 today" is expressible.
--   model         discovered (fetched or declared) -> TESTED (capability probes recorded) -> LOCKED.
--                 Only probe-verified capabilities count; a lock freezes exactly the capabilities
--                 whose latest probe PASSED, and a fingerprint of the locked route that inference
--                 provenance records as the model version.
--   runtime       a named set of slot bindings. A model is bound to a slot only if it is LOCKED and
--                 its locked capabilities include everything that slot's roles need; PRIVATE_LOCAL
--                 only to a LOCAL connection. A runtime activates only with M3's minimum route
--                 (REASONING_PRIMARY, FAST_UTILITY; EMBEDDING is the built-in local embedder), and
--                 when REASONING_ADVERSARIAL is unbound only if the primary model can also serve
--                 the Critic it falls back to. One runtime is active at a time; an active runtime's
--                 bindings are frozen, and nothing it depends on can be unlocked, disabled or
--                 retired under it.

CREATE TABLE IF NOT EXISTS llm_secret_salt (
    singleton  BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    salt       TEXT NOT NULL CHECK (length(salt) >= 32)
);

CREATE TABLE IF NOT EXISTS llm_connections (
    connection_id       TEXT PRIMARY KEY CHECK (connection_id LIKE 'llc:%'),
    name                TEXT NOT NULL UNIQUE CHECK (name ~ '^[a-z0-9][a-z0-9._-]{0,47}$'),
    provider_kind       TEXT NOT NULL CHECK (provider_kind IN ('OPENAI_COMPATIBLE')),
    -- No credentials in the URL (no '@'), no query or fragment.
    base_url            TEXT NOT NULL CHECK (base_url ~ '^https?://[^[:space:]/?#@]+(/[^[:space:]?#@]*)?$'),
    reach               TEXT NOT NULL CHECK (reach IN ('LOCAL', 'EXTERNAL')),
    secret_ref          TEXT CHECK (
        secret_ref IS NULL
        OR secret_ref ~ '^(env:[A-Za-z_][A-Za-z0-9_]{0,127}|wincred:lab-brain/llm/[0-9a-f-]{36})$'
    ),
    secret_fingerprint  TEXT CHECK (secret_fingerprint IS NULL OR secret_fingerprint ~ '^\*{4}[0-9a-f]{4}$'),
    lifecycle           TEXT NOT NULL DEFAULT 'ENABLED'
        CHECK (lifecycle IN ('ENABLED', 'DISABLED', 'RETIRED')),
    created_by          TEXT NOT NULL REFERENCES actors (actor_id),
    created_at          TIMESTAMPTZ NOT NULL,
    updated_at          TIMESTAMPTZ NOT NULL,

    CONSTRAINT llm_connections_secret_has_fingerprint
        CHECK ((secret_ref IS NULL) = (secret_fingerprint IS NULL)),
    -- LOCAL is declared, and it may only be declared of this machine.
    CONSTRAINT llm_connections_local_is_loopback CHECK (
        reach <> 'LOCAL'
        OR base_url ~ '^https?://(127\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}|localhost|\[::1\])(:[0-9]{1,5})?(/|$)'
    )
);

CREATE TABLE IF NOT EXISTS llm_connection_health (
    check_id       TEXT PRIMARY KEY CHECK (check_id LIKE 'lch:%'),
    connection_id  TEXT NOT NULL REFERENCES llm_connections (connection_id),
    outcome        TEXT NOT NULL CHECK (
        outcome IN ('REACHABLE', 'AUTH_FAILED', 'UNREACHABLE', 'PROTOCOL_ERROR', 'SECRET_UNAVAILABLE')
    ),
    latency_ms     INTEGER CHECK (latency_ms IS NULL OR latency_ms >= 0),
    detail         TEXT NOT NULL DEFAULT '',
    checked_at     TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS llm_connection_health_latest_idx
    ON llm_connection_health (connection_id, checked_at DESC);

CREATE TABLE IF NOT EXISTS llm_models (
    model_profile_id     TEXT PRIMARY KEY CHECK (model_profile_id LIKE 'llm:%'),
    connection_id        TEXT NOT NULL REFERENCES llm_connections (connection_id),
    model_name           TEXT NOT NULL CHECK (btrim(model_name) <> '' AND length(model_name) <= 200),
    source               TEXT NOT NULL CHECK (source IN ('FETCHED', 'DECLARED')),
    lifecycle            TEXT NOT NULL DEFAULT 'DISCOVERED'
        CHECK (lifecycle IN ('DISCOVERED', 'TESTED', 'LOCKED', 'RETIRED')),
    locked_capabilities  TEXT[],
    lock_fingerprint     TEXT CHECK (lock_fingerprint IS NULL OR lock_fingerprint ~ '^lk:[0-9a-f]{16}$'),
    locked_at            TIMESTAMPTZ,
    locked_by            TEXT REFERENCES actors (actor_id),
    created_at           TIMESTAMPTZ NOT NULL,

    UNIQUE (connection_id, model_name),
    CONSTRAINT llm_models_locked_has_lock CHECK ((lifecycle = 'LOCKED') = (lock_fingerprint IS NOT NULL)),
    CONSTRAINT llm_models_lock_is_whole CHECK (
        (lock_fingerprint IS NULL)
        = (locked_capabilities IS NULL AND locked_at IS NULL AND locked_by IS NULL)
    )
);

CREATE TABLE IF NOT EXISTS llm_capability_probes (
    probe_id          TEXT PRIMARY KEY CHECK (probe_id LIKE 'lcp:%'),
    model_profile_id  TEXT NOT NULL REFERENCES llm_models (model_profile_id),
    capability        TEXT NOT NULL CHECK (capability IN (
        'CHAT', 'STRUCTURED_JSON', 'ROLE_QUERY', 'ROLE_HYPOTHESIS', 'ROLE_SPECIALIST',
        'ROLE_CRITIQUE', 'CODE', 'VISION'
    )),
    outcome           TEXT NOT NULL CHECK (outcome IN ('PASSED', 'FAILED', 'ERROR')),
    probe_version     TEXT NOT NULL CHECK (btrim(probe_version) <> ''),
    response_digest   TEXT,
    latency_ms        INTEGER CHECK (latency_ms IS NULL OR latency_ms >= 0),
    detail            TEXT NOT NULL DEFAULT '',
    probed_at         TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS llm_capability_probes_latest_idx
    ON llm_capability_probes (model_profile_id, capability, probed_at DESC);

CREATE TABLE IF NOT EXISTS llm_runtimes (
    runtime_id       TEXT PRIMARY KEY CHECK (runtime_id LIKE 'lrt:%'),
    name             TEXT NOT NULL CHECK (btrim(name) <> '' AND length(name) <= 80),
    state            TEXT NOT NULL DEFAULT 'DRAFT' CHECK (state IN ('DRAFT', 'ACTIVE', 'RETIRED')),
    -- What evidence an EXTERNAL model route may carry (§14.1-§14.3). RESTRICTED_NDA is never
    -- permitted: the egress gate refuses it under any policy, and so does this column.
    external_labels  TEXT[] NOT NULL DEFAULT ARRAY['PUBLIC']::TEXT[]
        CHECK (external_labels <@ ARRAY['PUBLIC', 'INTERNAL', 'CONFIDENTIAL_LAB']::TEXT[]),
    created_by       TEXT NOT NULL REFERENCES actors (actor_id),
    created_at       TIMESTAMPTZ NOT NULL,
    activated_by     TEXT REFERENCES actors (actor_id),
    activated_at     TIMESTAMPTZ,
    retired_at       TIMESTAMPTZ,

    CONSTRAINT llm_runtimes_draft_is_unactivated
        CHECK (state <> 'DRAFT' OR (activated_at IS NULL AND retired_at IS NULL)),
    CONSTRAINT llm_runtimes_active_says_who CHECK (
        state <> 'ACTIVE'
        OR (activated_at IS NOT NULL AND activated_by IS NOT NULL AND retired_at IS NULL)
    ),
    CONSTRAINT llm_runtimes_retired_says_when CHECK (state <> 'RETIRED' OR retired_at IS NOT NULL),
    CONSTRAINT llm_runtimes_activation_is_whole
        CHECK ((activated_at IS NULL) = (activated_by IS NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS llm_runtimes_one_active ON llm_runtimes (state) WHERE state = 'ACTIVE';

CREATE TABLE IF NOT EXISTS llm_slot_bindings (
    runtime_id        TEXT NOT NULL REFERENCES llm_runtimes (runtime_id),
    logical_slot      TEXT NOT NULL CHECK (logical_slot IN (
        'REASONING_PRIMARY', 'REASONING_ADVERSARIAL', 'FAST_UTILITY', 'CODE', 'PRIVATE_LOCAL',
        'VISION'
    )),
    model_profile_id  TEXT NOT NULL REFERENCES llm_models (model_profile_id),
    bound_by          TEXT NOT NULL REFERENCES actors (actor_id),
    bound_at          TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (runtime_id, logical_slot)
);

-- What each slot's roles need a model to have PROVEN (`llm_runtime.capabilities` holds the same
-- table; a test asserts they agree). EMBEDDING is not bindable: it is the built-in local embedder.
CREATE FUNCTION llm_slot_requirements(p_slot TEXT) RETURNS TEXT[] AS $$
    SELECT CASE p_slot
        WHEN 'REASONING_PRIMARY' THEN
            ARRAY['CHAT', 'STRUCTURED_JSON', 'ROLE_HYPOTHESIS', 'ROLE_SPECIALIST']
        WHEN 'REASONING_ADVERSARIAL' THEN ARRAY['CHAT', 'STRUCTURED_JSON', 'ROLE_CRITIQUE']
        WHEN 'FAST_UTILITY' THEN ARRAY['CHAT', 'STRUCTURED_JSON', 'ROLE_QUERY']
        WHEN 'CODE' THEN ARRAY['CHAT', 'CODE']
        WHEN 'VISION' THEN ARRAY['CHAT', 'VISION']
        WHEN 'PRIVATE_LOCAL' THEN ARRAY['CHAT', 'STRUCTURED_JSON']
    END::TEXT[]
$$ LANGUAGE sql IMMUTABLE;

-- The capabilities whose LATEST probe passed. What a lock may freeze, and nothing else.
CREATE FUNCTION llm_verified_capabilities(p_model TEXT) RETURNS TEXT[] AS $$
    SELECT coalesce(array_agg(capability ORDER BY capability), ARRAY[]::TEXT[])
      FROM (
        SELECT DISTINCT ON (capability) capability, outcome
          FROM llm_capability_probes
         WHERE model_profile_id = p_model
         ORDER BY capability, probed_at DESC, probe_id DESC
      ) latest
     WHERE outcome = 'PASSED'
$$ LANGUAGE sql STABLE;

-- Whether a model is bound in a runtime that is not retired.
CREATE FUNCTION llm_model_in_use(p_model TEXT) RETURNS TEXT AS $$
    SELECT r.state || ' runtime ' || r.runtime_id
      FROM llm_slot_bindings b JOIN llm_runtimes r USING (runtime_id)
     WHERE b.model_profile_id = p_model AND r.state IN ('DRAFT', 'ACTIVE')
     ORDER BY (r.state = 'ACTIVE') DESC
     LIMIT 1
$$ LANGUAGE sql STABLE;

CREATE FUNCTION llm_connections_guard() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'llm connection % is retired, never deleted', OLD.connection_id;
    END IF;
    IF (NEW.connection_id, NEW.name, NEW.provider_kind, NEW.base_url, NEW.reach, NEW.created_by,
        NEW.created_at)
       IS DISTINCT FROM
       (OLD.connection_id, OLD.name, OLD.provider_kind, OLD.base_url, OLD.reach, OLD.created_by,
        OLD.created_at) THEN
        RAISE EXCEPTION
            'llm connection %''s endpoint is its identity; a different endpoint is a new connection',
            OLD.connection_id;
    END IF;
    IF OLD.lifecycle = 'RETIRED' THEN
        RAISE EXCEPTION 'llm connection % is retired', OLD.connection_id;
    END IF;
    IF NEW.lifecycle <> 'ENABLED' AND EXISTS (
        SELECT 1 FROM llm_models m
         WHERE m.connection_id = OLD.connection_id AND llm_model_in_use(m.model_profile_id) LIKE 'ACTIVE%'
    ) THEN
        RAISE EXCEPTION
            'llm connection % serves the active runtime; deactivate the runtime before disabling it',
            OLD.connection_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER llm_connections_guard_trg BEFORE UPDATE OR DELETE ON llm_connections
    FOR EACH ROW EXECUTE FUNCTION llm_connections_guard();

CREATE FUNCTION llm_models_guard() RETURNS TRIGGER AS $$
DECLARE
    v_verified TEXT[];
    v_in_use   TEXT;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'llm model % is retired, never deleted', OLD.model_profile_id;
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.lifecycle <> 'DISCOVERED' OR NEW.lock_fingerprint IS NOT NULL THEN
            RAISE EXCEPTION 'a model is discovered first; it is tested and locked afterwards';
        END IF;
        IF (SELECT lifecycle FROM llm_connections WHERE connection_id = NEW.connection_id)
           <> 'ENABLED' THEN
            RAISE EXCEPTION 'llm connection % is not enabled', NEW.connection_id;
        END IF;
        RETURN NEW;
    END IF;
    IF (NEW.model_profile_id, NEW.connection_id, NEW.model_name, NEW.source, NEW.created_at)
       IS DISTINCT FROM
       (OLD.model_profile_id, OLD.connection_id, OLD.model_name, OLD.source, OLD.created_at) THEN
        RAISE EXCEPTION 'llm model %''s identity is immutable', OLD.model_profile_id;
    END IF;
    IF OLD.lifecycle = 'RETIRED' THEN
        RAISE EXCEPTION 'llm model % is retired', OLD.model_profile_id;
    END IF;
    IF NEW.lifecycle = OLD.lifecycle AND NEW.lifecycle <> 'TESTED' THEN
        IF (NEW.locked_capabilities, NEW.lock_fingerprint, NEW.locked_at, NEW.locked_by)
           IS DISTINCT FROM
           (OLD.locked_capabilities, OLD.lock_fingerprint, OLD.locked_at, OLD.locked_by) THEN
            RAISE EXCEPTION 'llm model %''s lock is changed only by locking or unlocking it',
                OLD.model_profile_id;
        END IF;
        RETURN NEW;
    END IF;
    v_in_use := llm_model_in_use(OLD.model_profile_id);
    IF NEW.lifecycle = 'TESTED' THEN
        IF OLD.lifecycle NOT IN ('DISCOVERED', 'TESTED', 'LOCKED') THEN
            RAISE EXCEPTION 'llm model % cannot become TESTED from %', OLD.model_profile_id,
                OLD.lifecycle;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM llm_capability_probes WHERE model_profile_id = OLD.model_profile_id) THEN
            RAISE EXCEPTION 'llm model % has no capability probe on record', OLD.model_profile_id;
        END IF;
        IF OLD.lifecycle = 'LOCKED' AND v_in_use IS NOT NULL THEN
            RAISE EXCEPTION 'llm model % is bound in the % and cannot be unlocked; unbind it first',
                OLD.model_profile_id, v_in_use;
        END IF;
    ELSIF NEW.lifecycle = 'LOCKED' THEN
        IF OLD.lifecycle <> 'TESTED' THEN
            RAISE EXCEPTION 'llm model % is locked only after it is tested (it is %)',
                OLD.model_profile_id, OLD.lifecycle;
        END IF;
        v_verified := llm_verified_capabilities(OLD.model_profile_id);
        IF NOT ('CHAT' = ANY (v_verified)) THEN
            RAISE EXCEPTION 'llm model % has not passed the CHAT probe; there is nothing to lock',
                OLD.model_profile_id;
        END IF;
        IF (SELECT array_agg(c ORDER BY c) FROM unnest(NEW.locked_capabilities) c)
           IS DISTINCT FROM v_verified THEN
            RAISE EXCEPTION
                'a lock freezes exactly the capabilities whose latest probe passed (%), not %',
                v_verified, NEW.locked_capabilities;
        END IF;
        IF (SELECT lifecycle FROM llm_connections WHERE connection_id = OLD.connection_id)
           <> 'ENABLED' THEN
            RAISE EXCEPTION 'llm connection % is not enabled', OLD.connection_id;
        END IF;
    ELSIF NEW.lifecycle = 'RETIRED' THEN
        IF v_in_use IS NOT NULL THEN
            RAISE EXCEPTION 'llm model % is bound in the % and cannot be retired',
                OLD.model_profile_id, v_in_use;
        END IF;
    ELSE
        RAISE EXCEPTION 'llm model % cannot move % -> %', OLD.model_profile_id, OLD.lifecycle,
            NEW.lifecycle;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER llm_models_guard_trg BEFORE INSERT OR UPDATE OR DELETE ON llm_models
    FOR EACH ROW EXECUTE FUNCTION llm_models_guard();

CREATE FUNCTION llm_capability_probes_guard() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP <> 'INSERT' THEN
        RAISE EXCEPTION 'llm_capability_probes is append-only: a probe is what the model answered';
    END IF;
    IF (SELECT lifecycle FROM llm_models WHERE model_profile_id = NEW.model_profile_id)
       IN ('LOCKED', 'RETIRED') THEN
        RAISE EXCEPTION 'llm model % is locked or retired; unlock it to test it again',
            NEW.model_profile_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER llm_capability_probes_guard_trg
    BEFORE INSERT OR UPDATE OR DELETE ON llm_capability_probes
    FOR EACH ROW EXECUTE FUNCTION llm_capability_probes_guard();

CREATE FUNCTION llm_connection_health_append_only() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'llm_connection_health is append-only: a check is what the endpoint answered';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER llm_connection_health_append_only_trg
    BEFORE UPDATE OR DELETE ON llm_connection_health
    FOR EACH ROW EXECUTE FUNCTION llm_connection_health_append_only();

CREATE FUNCTION llm_slot_bindings_guard() RETURNS TRIGGER AS $$
DECLARE
    v_runtime TEXT := coalesce(NEW.runtime_id, OLD.runtime_id);
    v_model   llm_models%ROWTYPE;
    v_conn    llm_connections%ROWTYPE;
    v_missing TEXT[];
BEGIN
    IF (SELECT state FROM llm_runtimes WHERE runtime_id = v_runtime) <> 'DRAFT' THEN
        RAISE EXCEPTION 'runtime %''s bindings are frozen: it is no longer a draft', v_runtime;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    IF TG_OP = 'UPDATE' AND (NEW.runtime_id, NEW.logical_slot) IS DISTINCT FROM
                            (OLD.runtime_id, OLD.logical_slot) THEN
        RAISE EXCEPTION 'a binding is replaced, not moved to another slot or runtime';
    END IF;
    SELECT * INTO v_model FROM llm_models WHERE model_profile_id = NEW.model_profile_id;
    IF v_model.lifecycle <> 'LOCKED' THEN
        RAISE EXCEPTION 'llm model % is %, and only a LOCKED model is bound to a slot',
            NEW.model_profile_id, v_model.lifecycle;
    END IF;
    SELECT array_agg(r) INTO v_missing
      FROM unnest(llm_slot_requirements(NEW.logical_slot)) r
     WHERE NOT (r = ANY (v_model.locked_capabilities));
    IF v_missing IS NOT NULL THEN
        RAISE EXCEPTION 'llm model % has not proven % which slot % requires',
            NEW.model_profile_id, v_missing, NEW.logical_slot;
    END IF;
    SELECT * INTO v_conn FROM llm_connections WHERE connection_id = v_model.connection_id;
    IF v_conn.lifecycle <> 'ENABLED' THEN
        RAISE EXCEPTION 'llm connection % is not enabled', v_conn.connection_id;
    END IF;
    IF NEW.logical_slot = 'PRIVATE_LOCAL' AND v_conn.reach <> 'LOCAL' THEN
        RAISE EXCEPTION
            'PRIVATE_LOCAL is served only by a LOCAL model; % reaches %', v_conn.name, v_conn.reach;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER llm_slot_bindings_guard_trg BEFORE INSERT OR UPDATE OR DELETE ON llm_slot_bindings
    FOR EACH ROW EXECUTE FUNCTION llm_slot_bindings_guard();

CREATE FUNCTION llm_runtimes_guard() RETURNS TRIGGER AS $$
DECLARE
    v_primary_caps TEXT[];
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'llm runtime % is retired, never deleted', OLD.runtime_id;
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.state <> 'DRAFT' THEN
            RAISE EXCEPTION 'a runtime is created as a draft and activated afterwards';
        END IF;
        RETURN NEW;
    END IF;
    IF (NEW.runtime_id, NEW.created_by, NEW.created_at) IS DISTINCT FROM
       (OLD.runtime_id, OLD.created_by, OLD.created_at) THEN
        RAISE EXCEPTION 'llm runtime %''s identity is immutable', OLD.runtime_id;
    END IF;
    IF OLD.state <> 'DRAFT' AND (NEW.name, NEW.external_labels) IS DISTINCT FROM
                                 (OLD.name, OLD.external_labels) THEN
        RAISE EXCEPTION 'llm runtime % is %; only a draft is edited', OLD.runtime_id, OLD.state;
    END IF;
    IF NEW.state = OLD.state THEN
        RETURN NEW;
    END IF;
    IF OLD.state = 'RETIRED' OR (OLD.state = 'ACTIVE' AND NEW.state <> 'RETIRED') THEN
        RAISE EXCEPTION 'llm runtime % cannot move % -> %', OLD.runtime_id, OLD.state, NEW.state;
    END IF;
    IF NEW.state = 'ACTIVE' THEN
        IF NOT EXISTS (SELECT 1 FROM llm_slot_bindings
                        WHERE runtime_id = OLD.runtime_id AND logical_slot = 'REASONING_PRIMARY')
           OR NOT EXISTS (SELECT 1 FROM llm_slot_bindings
                           WHERE runtime_id = OLD.runtime_id AND logical_slot = 'FAST_UTILITY') THEN
            RAISE EXCEPTION
                'runtime % lacks M3''s minimum route: REASONING_PRIMARY and FAST_UTILITY must be '
                'bound (EMBEDDING is the built-in local embedder)', OLD.runtime_id;
        END IF;
        IF EXISTS (
            SELECT 1 FROM llm_slot_bindings b
              JOIN llm_models m USING (model_profile_id)
              JOIN llm_connections c USING (connection_id)
             WHERE b.runtime_id = OLD.runtime_id
               AND (m.lifecycle <> 'LOCKED' OR c.lifecycle <> 'ENABLED')
        ) THEN
            RAISE EXCEPTION 'runtime % binds a model that is not locked or a connection that is not '
                'enabled', OLD.runtime_id;
        END IF;
        IF NOT EXISTS (SELECT 1 FROM llm_slot_bindings WHERE runtime_id = OLD.runtime_id
                          AND logical_slot = 'REASONING_ADVERSARIAL') THEN
            SELECT m.locked_capabilities INTO v_primary_caps
              FROM llm_slot_bindings b JOIN llm_models m USING (model_profile_id)
             WHERE b.runtime_id = OLD.runtime_id AND b.logical_slot = 'REASONING_PRIMARY';
            IF NOT ('ROLE_CRITIQUE' = ANY (v_primary_caps)) THEN
                RAISE EXCEPTION
                    'runtime %: REASONING_ADVERSARIAL is unbound, so the Adversarial Critic falls '
                    'back to REASONING_PRIMARY, whose model has not proven ROLE_CRITIQUE',
                    OLD.runtime_id;
            END IF;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER llm_runtimes_guard_trg BEFORE INSERT OR UPDATE OR DELETE ON llm_runtimes
    FOR EACH ROW EXECUTE FUNCTION llm_runtimes_guard();

COMMENT ON TABLE llm_connections IS
    'Model endpoints and a REFERENCE to their credential (environment variable or OS credential '
    'store) with a salted fingerprint -- never the credential. Configuration state (lifecycle) is '
    'separate from health (llm_connection_health).';
COMMENT ON TABLE llm_runtimes IS
    'Named LogicalSlot -> locked-model bindings (CognitiveRole -> LogicalSlot stays in code). One '
    'ACTIVE runtime serves new research runs; with none active the local catalog reasoner does.';
