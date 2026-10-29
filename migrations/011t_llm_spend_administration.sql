-- 011t: the Owner administers the money; the services only spend within it.
--
-- WHY. 011r made the ceiling atomic and the ledger append-only, but its guard was a session flag
-- (`set_config('lab_brain.llm_spend_writer', 'on', true)`) that ANY role may set, its functions
-- were EXECUTE-able by PUBLIC, and `lab-brain admin db-roles` gives the services' role row writes
-- on every table. Connected as that least-privilege role, a research process could raise its own
-- ceiling, close a circuit an overrun opened, create a budget, declare a price of zero, or forge
-- the flag and zero what it was charged (tests/integration/test_g0_spend_admin_postgres.py, run
-- before this migration). The ceiling bound only an honest caller.
--
-- WHAT.
--
--     lab_brain_spend_admin  a NOLOGIN role. Only a member of it -- a login role the operator
--                            grants it to, the Owner's -- may create a budget, declare a price,
--                            change a ceiling, close a circuit, or declare an endpoint free. The
--                            check is `pg_has_role(session_user, ..., 'MEMBER')` inside SECURITY
--                            DEFINER functions, so neither SET ROLE nor a forged setting passes
--                            it; EXECUTE is revoked from PUBLIC as well.
--     the services' role     may reserve, settle and retain (EXECUTE granted by `db-roles`, not
--                            here: the role's name is the deployment's) and read. `db-roles`
--                            revokes its row writes on these tables.
--     the writes             happen only inside functions owned by the migrator, which owns the
--                            tables: every trigger now also requires `current_user` to be the
--                            tables' owner, so the flag alone -- set by anyone, even a role a
--                            deployment granted table writes by mistake -- writes nothing.
--     free endpoints         an endpoint (`host[:port]`, and one model or `*`) the Owner declared
--                            genuinely free: requests to it are not metered. Nothing else is
--                            exempt once a ceiling is configured -- this machine included, since a
--                            local proxy (LiteLLM on localhost) may forward to a paid provider.
--                            Append-only: a revocation is a later row.
--
-- THE TRUST ROOT THAT REMAINS. The migrator (superuser, or the tables' owner) passes every check
-- here by construction, and whoever holds `lab_brain_spend_admin` decides the money. This
-- migration separates those from ordinary research execution; it does not make them trustworthy.
--
-- Idempotent, so it can be applied by hand before `scripts/migrate.py` records it.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'lab_brain_spend_admin') THEN
        CREATE ROLE lab_brain_spend_admin NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOREPLICATION NOBYPASSRLS;
    END IF;
END
$$;

-- Which database role wrote each row: the Owner's login for a declaration, the services' for a
-- reservation. `session_user` -- not changed by SET ROLE or by a SECURITY DEFINER function.
ALTER TABLE llm_spend_budgets ADD COLUMN IF NOT EXISTS db_role TEXT NOT NULL DEFAULT session_user;
ALTER TABLE llm_spend_prices ADD COLUMN IF NOT EXISTS db_role TEXT NOT NULL DEFAULT session_user;
ALTER TABLE llm_spend_ledger ADD COLUMN IF NOT EXISTS db_role TEXT NOT NULL DEFAULT session_user;

CREATE TABLE IF NOT EXISTS llm_spend_free_endpoints (
    declaration_id  BIGSERIAL PRIMARY KEY,
    -- As `llm_spend_prices.endpoint_host`: `host` or `host:port`, lower-case, as the client names it.
    endpoint_host   TEXT NOT NULL CHECK (endpoint_host = lower(endpoint_host)
                                         AND endpoint_host ~ '^[a-z0-9.\-\[\]:]+$'),
    -- One model, or `*` for every model this endpoint serves.
    model           TEXT NOT NULL CHECK (btrim(model) <> '' AND length(model) <= 200),
    -- TRUE declares it free; FALSE revokes an earlier declaration. The latest row decides.
    free            BOOLEAN NOT NULL,
    reason          TEXT NOT NULL CHECK (btrim(reason) <> '' AND length(reason) <= 500),
    actor_id        TEXT NOT NULL CHECK (btrim(actor_id) <> ''),
    db_role         TEXT NOT NULL DEFAULT session_user,
    declared_at     TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX IF NOT EXISTS llm_spend_free_endpoints_lookup_idx
    ON llm_spend_free_endpoints (endpoint_host, model, declaration_id DESC);

-- -- the writer: the flag, AND the tables' owner -------------------------------------------------

-- Inside the SECURITY DEFINER functions below `current_user` is their owner, the migrator, who
-- owns these tables. A role that only set the flag is not.
CREATE OR REPLACE FUNCTION llm_spend_writer() RETURNS BOOLEAN LANGUAGE sql STABLE AS $$
    SELECT coalesce(current_setting('lab_brain.llm_spend_writer', TRUE), '') = 'on'
       AND current_user = (SELECT pg_get_userbyid(c.relowner) FROM pg_catalog.pg_class c
                            WHERE c.oid = 'public.llm_spend_ledger'::regclass)
$$;

CREATE OR REPLACE FUNCTION llm_spend_is_admin() RETURNS BOOLEAN LANGUAGE sql STABLE AS $$
    SELECT pg_has_role(session_user, 'lab_brain_spend_admin', 'MEMBER')
$$;

CREATE OR REPLACE FUNCTION llm_spend_require_admin(p_what TEXT) RETURNS VOID AS $$
BEGIN
    IF NOT llm_spend_is_admin() THEN
        RAISE EXCEPTION 'SPEND_ADMIN_REQUIRED: % is the Owner''s spend administration; % is not a '
            'member of lab_brain_spend_admin', p_what, session_user
            USING ERRCODE = 'insufficient_privilege';
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Prices: written only by `llm_spend_declare_price` now, never edited or deleted.
CREATE OR REPLACE FUNCTION llm_spend_prices_append_only() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NOT llm_spend_writer() THEN
            RAISE EXCEPTION 'a price is declared only through llm_spend_declare_price, by the '
                'Owner''s spend administration';
        END IF;
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'llm_spend_prices is append-only: a new price is a new declaration (% refused)',
        TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS llm_spend_prices_append_only ON llm_spend_prices;
CREATE TRIGGER llm_spend_prices_append_only
    BEFORE INSERT OR UPDATE OR DELETE ON llm_spend_prices
    FOR EACH ROW EXECUTE FUNCTION llm_spend_prices_append_only();

-- Budgets: created only by `llm_spend_declare_budget`; the rest as 011r.
CREATE OR REPLACE FUNCTION llm_spend_budgets_guarded() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'a spend budget is never deleted: its ledger refers to it';
    END IF;
    IF NOT llm_spend_writer() THEN
        RAISE EXCEPTION 'a spend budget is created, and its ceiling, charge and circuit change, '
            'only through the llm_spend_* functions, each of which writes the row that explains it';
    END IF;
    IF TG_OP = 'INSERT' THEN
        IF NEW.charged <> 0 OR NEW.circuit_open OR NEW.opened_by_call IS NOT NULL THEN
            RAISE EXCEPTION 'a spend budget starts with nothing charged and its circuit closed';
        END IF;
        RETURN NEW;
    END IF;
    IF NEW.budget_id IS DISTINCT FROM OLD.budget_id
        OR NEW.currency IS DISTINCT FROM OLD.currency
        OR NEW.safety_multiplier IS DISTINCT FROM OLD.safety_multiplier
        OR NEW.image_allowance_tokens IS DISTINCT FROM OLD.image_allowance_tokens
        OR NEW.request_overhead_tokens IS DISTINCT FROM OLD.request_overhead_tokens
        OR NEW.declared_by IS DISTINCT FROM OLD.declared_by
        OR NEW.declared_at IS DISTINCT FROM OLD.declared_at
        OR NEW.db_role IS DISTINCT FROM OLD.db_role THEN
        RAISE EXCEPTION 'a spend budget''s parameters never change: declare a new budget';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION llm_spend_free_endpoints_append_only() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' AND llm_spend_writer() THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'llm_spend_free_endpoints is written only by llm_spend_declare_free and '
        'llm_spend_revoke_free, and never edited (% refused)', TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS llm_spend_free_endpoints_append_only ON llm_spend_free_endpoints;
CREATE TRIGGER llm_spend_free_endpoints_append_only
    BEFORE INSERT OR UPDATE OR DELETE ON llm_spend_free_endpoints
    FOR EACH ROW EXECUTE FUNCTION llm_spend_free_endpoints_append_only();

-- -- the Owner's administration ---------------------------------------------------------------

CREATE OR REPLACE FUNCTION llm_spend_declare_budget(
    p_budget TEXT, p_currency TEXT, p_ceiling NUMERIC, p_actor TEXT,
    p_multiplier NUMERIC, p_image_allowance INTEGER, p_overhead INTEGER
) RETURNS VOID AS $$
BEGIN
    PERFORM llm_spend_require_admin('declaring a spend budget');
    PERFORM set_config('lab_brain.llm_spend_writer', 'on', TRUE);
    INSERT INTO llm_spend_budgets (budget_id, currency, ceiling, safety_multiplier,
        image_allowance_tokens, request_overhead_tokens, declared_by)
    VALUES (p_budget, p_currency, p_ceiling, p_multiplier, p_image_allowance, p_overhead, p_actor);
    PERFORM set_config('lab_brain.llm_spend_writer', '', TRUE);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp;

CREATE OR REPLACE FUNCTION llm_spend_declare_price(
    p_budget TEXT, p_currency TEXT, p_host TEXT, p_model TEXT, p_input NUMERIC, p_output NUMERIC,
    p_source TEXT, p_source_date DATE, p_actor TEXT
) RETURNS BIGINT AS $$
DECLARE
    v_id BIGINT;
BEGIN
    PERFORM llm_spend_require_admin('declaring a price');
    PERFORM set_config('lab_brain.llm_spend_writer', 'on', TRUE);
    INSERT INTO llm_spend_prices (budget_id, currency, endpoint_host, model, input_per_mtok,
        output_per_mtok, source, source_date, declared_by)
    VALUES (p_budget, p_currency, lower(p_host), p_model, p_input, p_output, p_source,
        p_source_date, p_actor)
    RETURNING price_id INTO v_id;
    PERFORM set_config('lab_brain.llm_spend_writer', '', TRUE);
    RETURN v_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp;

-- 011r's body, now the Owner's alone.
CREATE OR REPLACE FUNCTION llm_spend_set_ceiling(
    p_budget TEXT, p_ceiling NUMERIC, p_actor TEXT, p_reason TEXT, p_close_circuit BOOLEAN
) RETURNS VOID AS $$
DECLARE
    b llm_spend_budgets%ROWTYPE;
BEGIN
    PERFORM llm_spend_require_admin(CASE WHEN p_close_circuit THEN 'closing a circuit'
                                         ELSE 'changing a ceiling' END);
    SELECT * INTO b FROM llm_spend_budgets WHERE budget_id = p_budget FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'no spend budget % is declared', p_budget;
    END IF;
    PERFORM set_config('lab_brain.llm_spend_writer', 'on', TRUE);
    -- The table's CHECK refuses a closed circuit with more charged than the new ceiling.
    UPDATE llm_spend_budgets
       SET ceiling = p_ceiling,
           circuit_open = circuit_open AND NOT p_close_circuit,
           opened_by_call = CASE WHEN p_close_circuit THEN NULL ELSE opened_by_call END
     WHERE budget_id = p_budget
     RETURNING * INTO b;
    INSERT INTO llm_spend_ledger (budget_id, kind, charged_after, ceiling_after, actor_id, reason)
    VALUES (p_budget, 'CEILING', b.charged, b.ceiling, p_actor,
        CASE WHEN p_close_circuit THEN 'circuit closed: ' ELSE '' END || coalesce(p_reason, ''));
    PERFORM set_config('lab_brain.llm_spend_writer', '', TRUE);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp;

CREATE OR REPLACE FUNCTION llm_spend_declare_free(
    p_host TEXT, p_model TEXT, p_reason TEXT, p_actor TEXT
) RETURNS VOID AS $$
BEGIN
    PERFORM llm_spend_require_admin('declaring an endpoint free');
    PERFORM set_config('lab_brain.llm_spend_writer', 'on', TRUE);
    INSERT INTO llm_spend_free_endpoints (endpoint_host, model, free, reason, actor_id)
    VALUES (lower(p_host), p_model, TRUE, p_reason, p_actor);
    PERFORM set_config('lab_brain.llm_spend_writer', '', TRUE);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp;

CREATE OR REPLACE FUNCTION llm_spend_revoke_free(
    p_host TEXT, p_model TEXT, p_reason TEXT, p_actor TEXT
) RETURNS VOID AS $$
BEGIN
    PERFORM llm_spend_require_admin('revoking a free endpoint');
    PERFORM set_config('lab_brain.llm_spend_writer', 'on', TRUE);
    INSERT INTO llm_spend_free_endpoints (endpoint_host, model, free, reason, actor_id)
    VALUES (lower(p_host), p_model, FALSE, p_reason, p_actor);
    PERFORM set_config('lab_brain.llm_spend_writer', '', TRUE);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp;

-- Whether requests for `p_model` at `p_host` are free: the latest declaration naming the model
-- decides; with none, the latest naming `*`. Never declared: not free.
CREATE OR REPLACE FUNCTION llm_spend_endpoint_is_free(p_host TEXT, p_model TEXT)
RETURNS BOOLEAN AS $$
    SELECT coalesce(
        (SELECT free FROM llm_spend_free_endpoints
          WHERE endpoint_host = lower(p_host) AND model = p_model
          ORDER BY declaration_id DESC LIMIT 1),
        (SELECT free FROM llm_spend_free_endpoints
          WHERE endpoint_host = lower(p_host) AND model = '*'
          ORDER BY declaration_id DESC LIMIT 1),
        FALSE)
$$ LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp;

-- -- the services' operations: the migrator's functions, executed by grant only -----------------

ALTER FUNCTION llm_spend_reserve(TEXT, TEXT, TEXT, TEXT, BIGINT, INTEGER, BIGINT)
    SECURITY DEFINER SET search_path = public, pg_temp;
ALTER FUNCTION llm_spend_settle(TEXT, BIGINT, BIGINT, BIGINT)
    SECURITY DEFINER SET search_path = public, pg_temp;
ALTER FUNCTION llm_spend_retain(TEXT, TEXT)
    SECURITY DEFINER SET search_path = public, pg_temp;

-- -- privileges ---------------------------------------------------------------------------------

REVOKE ALL ON FUNCTION llm_spend_reserve(TEXT, TEXT, TEXT, TEXT, BIGINT, INTEGER, BIGINT) FROM PUBLIC;
REVOKE ALL ON FUNCTION llm_spend_settle(TEXT, BIGINT, BIGINT, BIGINT) FROM PUBLIC;
REVOKE ALL ON FUNCTION llm_spend_retain(TEXT, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION llm_spend_set_ceiling(TEXT, NUMERIC, TEXT, TEXT, BOOLEAN) FROM PUBLIC;
REVOKE ALL ON FUNCTION llm_spend_declare_budget(TEXT, TEXT, NUMERIC, TEXT, NUMERIC, INTEGER, INTEGER)
    FROM PUBLIC;
REVOKE ALL ON FUNCTION llm_spend_declare_price(TEXT, TEXT, TEXT, TEXT, NUMERIC, NUMERIC, TEXT, DATE,
    TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION llm_spend_declare_free(TEXT, TEXT, TEXT, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION llm_spend_revoke_free(TEXT, TEXT, TEXT, TEXT) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION llm_spend_set_ceiling(TEXT, NUMERIC, TEXT, TEXT, BOOLEAN),
    llm_spend_declare_budget(TEXT, TEXT, NUMERIC, TEXT, NUMERIC, INTEGER, INTEGER),
    llm_spend_declare_price(TEXT, TEXT, TEXT, TEXT, NUMERIC, NUMERIC, TEXT, DATE, TEXT),
    llm_spend_declare_free(TEXT, TEXT, TEXT, TEXT),
    llm_spend_revoke_free(TEXT, TEXT, TEXT, TEXT)
    TO lab_brain_spend_admin;
GRANT USAGE ON SCHEMA public TO lab_brain_spend_admin;
GRANT SELECT ON llm_spend_budgets, llm_spend_prices, llm_spend_ledger, llm_spend_free_endpoints
    TO lab_brain_spend_admin;
-- `llm_spend_endpoint_is_free` only reads, and every role may ask it (EXECUTE stays PUBLIC).
