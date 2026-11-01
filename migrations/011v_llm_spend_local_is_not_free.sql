-- 011v: a model server on this machine is not presumed free.
--
-- 011t made the money the Owner's and refused every remote request without a ceiling. It left one
-- path open, and named it (spend-administration.md, Owner decision A3): with no ceiling configured,
-- a request to THIS machine was sent unmetered -- and a local endpoint may be a proxy (LiteLLM on
-- localhost) that forwards to a paid provider. The client now meters this machine like any endpoint
-- (`llm_runtime.spend`, `provider._reserve`). This migration closes the two ways the Owner's free
-- declaration itself could still cover a paid path:
--
--     wildcard      a declaration naming `*` made every model at an endpoint free. A proxy routes
--                   by model name, so `*` at a proxy covers whatever it forwards to. A new `*`
--                   declaration is refused, and an existing one no longer counts: only a
--                   declaration naming the exact model exempts it.
--     paid-proxy    a declared-free endpoint whose answer carries a paid provider's signs (a billing
--     evidence      header, a cost in its usage -- `spend.paid_proxy_signals`) is REPORTED. The
--                   report withdraws that declaration: `llm_spend_endpoint_is_free` is false for it
--                   until the Owner declares the endpoint free again (a new declaration). The
--                   services may report -- a report can only withdraw an exemption, never grant
--                   one -- and nobody edits or deletes one.
--
-- NOT CLOSED, and not closable from here: a proxy that strips every such sign. Whether an endpoint
-- is a model server or a proxy is a fact about the deployment the client cannot observe; the Owner's
-- declaration remains the trust root (SPEC-ISSUE-017).
--
-- Applied after 011s.

-- -- the evidence ------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS llm_spend_paid_proxy_evidence (
    evidence_id     BIGSERIAL PRIMARY KEY,
    -- The free declaration this evidence withdraws: the latest one naming (host, model) when the
    -- report was made. A later declaration by the Owner is not withdrawn by it.
    declaration_id  BIGINT NOT NULL REFERENCES llm_spend_free_endpoints (declaration_id),
    endpoint_host   TEXT NOT NULL CHECK (endpoint_host = lower(endpoint_host)
                                         AND endpoint_host ~ '^[a-z0-9.\-\[\]:]+$'),
    model           TEXT NOT NULL CHECK (btrim(model) <> '' AND length(model) <= 200),
    -- What was seen: `header:<name>` or `usage.<field>` (names only -- never a value, a prompt or
    -- a credential).
    signals         TEXT[] NOT NULL CHECK (cardinality(signals) BETWEEN 1 AND 16
                                           AND array_position(signals, NULL) IS NULL),
    db_role         TEXT NOT NULL DEFAULT session_user,
    observed_at     TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX IF NOT EXISTS llm_spend_paid_proxy_evidence_declaration_idx
    ON llm_spend_paid_proxy_evidence (declaration_id);

CREATE OR REPLACE FUNCTION llm_spend_paid_proxy_evidence_append_only() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' AND llm_spend_writer() THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'llm_spend_paid_proxy_evidence is written only by llm_spend_report_paid_proxy, '
        'and never edited or deleted (% refused)', TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS llm_spend_paid_proxy_evidence_append_only ON llm_spend_paid_proxy_evidence;
CREATE TRIGGER llm_spend_paid_proxy_evidence_append_only
    BEFORE INSERT OR UPDATE OR DELETE ON llm_spend_paid_proxy_evidence
    FOR EACH ROW EXECUTE FUNCTION llm_spend_paid_proxy_evidence_append_only();

-- -- a free declaration names one model --------------------------------------------------------

CREATE OR REPLACE FUNCTION llm_spend_declare_free(
    p_host TEXT, p_model TEXT, p_reason TEXT, p_actor TEXT
) RETURNS VOID AS $$
BEGIN
    PERFORM llm_spend_require_admin('declaring an endpoint free');
    IF btrim(coalesce(p_model, '')) = '*' THEN
        RAISE EXCEPTION 'a free declaration names one model, not *: a proxy routes by model name, '
            'so * would declare free every model it forwards to a paid provider';
    END IF;
    PERFORM set_config('lab_brain.llm_spend_writer', 'on', TRUE);
    INSERT INTO llm_spend_free_endpoints (endpoint_host, model, free, reason, actor_id)
    VALUES (lower(p_host), p_model, TRUE, p_reason, p_actor);
    PERFORM set_config('lab_brain.llm_spend_writer', '', TRUE);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp;

-- -- whether a request is free -----------------------------------------------------------------

-- The latest declaration naming exactly (p_host, p_model) decides, and only while no paid-proxy
-- evidence withdrew it. `*` rows (from 011t) are not read. Never declared: not free.
CREATE OR REPLACE FUNCTION llm_spend_endpoint_is_free(p_host TEXT, p_model TEXT)
RETURNS BOOLEAN AS $$
    SELECT coalesce(
        (SELECT d.free AND NOT EXISTS (SELECT 1 FROM llm_spend_paid_proxy_evidence e
                                        WHERE e.declaration_id = d.declaration_id)
           FROM llm_spend_free_endpoints d
          WHERE d.endpoint_host = lower(p_host) AND d.model = p_model AND d.model <> '*'
          ORDER BY d.declaration_id DESC LIMIT 1),
        FALSE)
$$ LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp;

-- -- the services' report ----------------------------------------------------------------------

-- Withdraws the current free declaration of (p_host, p_model), if there is one, and returns the
-- evidence id; NULL when nothing was declared free (nothing to withdraw). Callable by the services:
-- it can only make the guard stricter.
CREATE OR REPLACE FUNCTION llm_spend_report_paid_proxy(
    p_host TEXT, p_model TEXT, p_signals TEXT[]
) RETURNS BIGINT AS $$
DECLARE
    d llm_spend_free_endpoints%ROWTYPE;
    v_id BIGINT;
    v_signal TEXT;
BEGIN
    IF p_signals IS NULL OR cardinality(p_signals) = 0 THEN
        RAISE EXCEPTION 'a paid-proxy report names what was seen';
    END IF;
    FOREACH v_signal IN ARRAY p_signals LOOP
        IF v_signal IS NULL OR v_signal !~ '^(header:|usage\.|body\.)[a-z0-9_.\-]{1,120}$' THEN
            RAISE EXCEPTION 'a paid-proxy signal is header:<name>, usage.<field> or body.<field>, '
                'never a value';
        END IF;
    END LOOP;
    SELECT * INTO d FROM llm_spend_free_endpoints
     WHERE endpoint_host = lower(p_host) AND model = p_model
     ORDER BY declaration_id DESC LIMIT 1;
    IF NOT FOUND OR NOT d.free THEN
        RETURN NULL;
    END IF;
    PERFORM set_config('lab_brain.llm_spend_writer', 'on', TRUE);
    INSERT INTO llm_spend_paid_proxy_evidence (declaration_id, endpoint_host, model, signals)
    VALUES (d.declaration_id, d.endpoint_host, d.model, p_signals)
    RETURNING evidence_id INTO v_id;
    PERFORM set_config('lab_brain.llm_spend_writer', '', TRUE);
    RETURN v_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp;

-- -- privileges ---------------------------------------------------------------------------------

REVOKE ALL ON FUNCTION llm_spend_report_paid_proxy(TEXT, TEXT, TEXT[]) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION llm_spend_report_paid_proxy(TEXT, TEXT, TEXT[]) TO lab_brain_spend_admin;
GRANT SELECT ON llm_spend_paid_proxy_evidence TO lab_brain_spend_admin;
-- The services' EXECUTE and SELECT are granted by `lab-brain admin db-roles` (deployment.py).
