-- 011r: a fail-closed MONETARY ceiling on external language-model requests.
--
-- WHY. The live evaluation had call and token caps (`lab_brain.evaluation.live_budget`), checked
-- before each episode, and no proven cap on money: no route declared a unit price, `chat()` sent no
-- `max_tokens` (so one request's output -- and its cost -- was the provider's choice), a provider
-- that refuses `response_format` turned one logical call into two billed requests, qualification
-- probes and timed-out requests left no usage anywhere, and two processes could both pass a
-- "spent + reserve <= cap" check made outside any transaction. The Independent Chief Auditor asked
-- for a fail-closed cost ceiling before any real model testing
-- (docs/audit/g0-evidence-auth-cost-closure-2026-10-28/cost-path-audit.md).
--
-- WHAT. Every request with a body that `OpenAICompatibleClient._request` -- the single HTTP
-- chokepoint -- would send to an endpoint that is not this machine is RESERVED here first, at a
-- worst case it can prove, and only then sent:
--
--     input_bound  = CEIL(body_bytes x safety_multiplier) + images x image_allowance_tokens
--                    + request_overhead_tokens
--     worst_case   = (input_bound x input_per_mtok + max_output_tokens x output_per_mtok) / 10^6
--
-- `body_bytes` is the UTF-8 length of the whole serialized request body. ASSUMPTION, stated: a
-- token is at least one byte of the text it encodes (byte-level BPE; SentencePiece with byte
-- fallback), so the prompt cannot be billed more tokens than the body has bytes. JSON escaping
-- only lengthens the body. What a provider adds that is NOT in the body -- chat-template markers,
-- an instruction it wraps a schema in -- is what `request_overhead_tokens` and the multiplier
-- (never below 1) are for. `max_output_tokens` is the `max_tokens` the request carries; a request
-- without one is refused. That the PROVIDER honours `max_tokens` -- including any hidden
-- "reasoning"/"thinking" tokens it bills as output -- is the residual assumption the Owner must
-- verify per provider; settlement detects a provider that does not (OVERRUN, below).
--
-- THE RESERVATION IS ATOMIC. `llm_spend_reserve` locks the budget row (SELECT ... FOR UPDATE),
-- refuses when `charged + worst_case > ceiling`, and charges the worst case in the same
-- transaction that writes the RESERVATION row. Concurrent threads and processes serialize on that
-- row lock: however many race, the sum they reserve never passes the ceiling. CHECK
-- `llm_spend_budgets_within_ceiling` holds it in the table itself.
--
-- SETTLEMENT NEVER UNDER-CHARGES WHAT IT CANNOT PROVE.
--
--     SETTLED    the provider reported prompt and completion tokens, within the bound: the charge
--                becomes prompt x input + billed_output x output, where billed_output is
--                GREATEST(completion_tokens, total_tokens - prompt_tokens) -- a total that exceeds
--                its parts (hidden reasoning tokens) is billed as output
--     RETAINED   no usage, malformed usage, an HTTP error, a timeout, a dropped connection: the
--                provider may have billed and said nothing, so the WORST CASE stays charged
--     OVERRUN    reported usage passed the reservation -- in money, in prompt tokens (the byte
--                bound broke) or in output tokens (`max_tokens` was not honoured): the charge is
--                the greater of reported and reserved, and the CIRCUIT OPENS. Every later
--                reservation on this budget is refused until the Owner closes it
--                (`llm_spend_set_ceiling(..., close_circuit => TRUE)`) with a ceiling at least
--                what is charged
--
-- A process that dies between reservation and settlement leaves the worst case charged forever:
-- the fail-closed direction.
--
-- APPEND-ONLY, AND WRITTEN ONLY BY THESE FUNCTIONS. Ledger rows are never updated or deleted;
-- an estimate and its settlement are two rows. The budget row's money columns change only inside
-- the functions (a transaction-local setting they raise; a direct UPDATE is refused), its
-- parameters never change, and it is never deleted. This guards against an accidental write, not
-- against a role that can set the flag itself: database privileges are the deployment's.
-- Rows carry the call id, model and endpoint host -- never the credential, never the prompt.
--
-- PRICES ARE THE OWNER'S, never invented here. Each is declared per (budget, endpoint host,
-- model) with its currency (the budget's own), source and source date; a later declaration
-- supersedes, none is edited. A model with no declared price on that host is refused, not
-- estimated.

CREATE TABLE llm_spend_budgets (
    budget_id               TEXT PRIMARY KEY CHECK (budget_id ~ '^[a-z0-9][a-z0-9._:-]{0,79}$'),
    currency                TEXT NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
    ceiling                 NUMERIC(20, 8) NOT NULL CHECK (ceiling > 0),
    -- Reserved worst cases not yet settled plus settled charges: what the ceiling is held against.
    charged                 NUMERIC(30, 12) NOT NULL DEFAULT 0 CHECK (charged >= 0),
    circuit_open            BOOLEAN NOT NULL DEFAULT FALSE,
    opened_by_call          TEXT,
    safety_multiplier       NUMERIC(8, 4) NOT NULL DEFAULT 1 CHECK (safety_multiplier >= 1),
    image_allowance_tokens  INTEGER NOT NULL DEFAULT 4096 CHECK (image_allowance_tokens >= 0),
    request_overhead_tokens INTEGER NOT NULL DEFAULT 1024 CHECK (request_overhead_tokens >= 0),
    declared_by             TEXT NOT NULL CHECK (btrim(declared_by) <> ''),
    declared_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (budget_id, currency),
    -- The ceiling, held by the table: only an OVERRUN (which opens the circuit) may pass it.
    CONSTRAINT llm_spend_budgets_within_ceiling CHECK (circuit_open OR charged <= ceiling),
    CONSTRAINT llm_spend_budgets_open_names_its_call
        CHECK (circuit_open = (opened_by_call IS NOT NULL))
);

CREATE TABLE llm_spend_prices (
    price_id        BIGSERIAL PRIMARY KEY,
    budget_id       TEXT NOT NULL,
    currency        TEXT NOT NULL,
    -- `host` or `host:port`, lower-case, exactly as the client names the endpoint.
    endpoint_host   TEXT NOT NULL CHECK (endpoint_host = lower(endpoint_host)
                                         AND endpoint_host ~ '^[a-z0-9.\-\[\]:]+$'),
    model           TEXT NOT NULL CHECK (btrim(model) <> '' AND length(model) <= 200),
    input_per_mtok  NUMERIC(20, 8) NOT NULL CHECK (input_per_mtok >= 0),
    output_per_mtok NUMERIC(20, 8) NOT NULL CHECK (output_per_mtok >= 0),
    -- Where the Owner read the price, and when: a price nobody can trace is not declared.
    source          TEXT NOT NULL CHECK (btrim(source) <> ''),
    source_date     DATE NOT NULL,
    declared_by     TEXT NOT NULL CHECK (btrim(declared_by) <> ''),
    declared_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- In the budget's own currency: no conversion is ever made.
    FOREIGN KEY (budget_id, currency) REFERENCES llm_spend_budgets (budget_id, currency)
);

CREATE INDEX llm_spend_prices_lookup_idx
    ON llm_spend_prices (budget_id, endpoint_host, model, declared_at DESC, price_id DESC);

CREATE TABLE llm_spend_ledger (
    entry_id            BIGSERIAL PRIMARY KEY,
    budget_id           TEXT NOT NULL REFERENCES llm_spend_budgets (budget_id),
    kind                TEXT NOT NULL
        CHECK (kind IN ('RESERVATION', 'SETTLEMENT', 'RETAINED', 'OVERRUN', 'CEILING')),
    call_id             TEXT CHECK (call_id IS NULL OR call_id ~ '^llmcall:[0-9a-f]{32}$'),
    endpoint_host       TEXT,
    model               TEXT,
    price_id            BIGINT REFERENCES llm_spend_prices (price_id),
    body_bytes          BIGINT CHECK (body_bytes >= 1),
    image_count         INTEGER CHECK (image_count >= 0),
    max_output_tokens   BIGINT CHECK (max_output_tokens >= 1),
    input_bound_tokens  BIGINT CHECK (input_bound_tokens >= 1),
    worst_case          NUMERIC(30, 12) CHECK (worst_case >= 0),
    prompt_tokens       BIGINT CHECK (prompt_tokens >= 0),
    completion_tokens   BIGINT CHECK (completion_tokens >= 0),
    total_tokens        BIGINT CHECK (total_tokens >= 0),
    -- What this call is charged once this row is written (the worst case on a reservation).
    amount              NUMERIC(30, 12) CHECK (amount >= 0),
    charged_after       NUMERIC(30, 12) NOT NULL CHECK (charged_after >= 0),
    ceiling_after       NUMERIC(20, 8) NOT NULL CHECK (ceiling_after > 0),
    actor_id            TEXT,
    reason              TEXT,
    recorded_at         TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT llm_spend_ledger_call_rows_name_a_call
        CHECK ((kind = 'CEILING') = (call_id IS NULL)),
    CONSTRAINT llm_spend_ledger_reservation_is_complete
        CHECK (kind <> 'RESERVATION' OR (endpoint_host IS NOT NULL AND model IS NOT NULL
               AND price_id IS NOT NULL AND body_bytes IS NOT NULL AND image_count IS NOT NULL
               AND max_output_tokens IS NOT NULL AND input_bound_tokens IS NOT NULL
               AND worst_case IS NOT NULL AND amount = worst_case)),
    CONSTRAINT llm_spend_ledger_settlement_has_usage
        CHECK (kind NOT IN ('SETTLEMENT', 'OVERRUN')
               OR (prompt_tokens IS NOT NULL AND completion_tokens IS NOT NULL)),
    CONSTRAINT llm_spend_ledger_ceiling_is_attributed
        CHECK (kind <> 'CEILING' OR (actor_id IS NOT NULL AND btrim(actor_id) <> ''
               AND reason IS NOT NULL AND btrim(reason) <> ''))
);

-- One reservation per request, and at most one ending for it.
CREATE UNIQUE INDEX llm_spend_ledger_one_reservation
    ON llm_spend_ledger (call_id) WHERE kind = 'RESERVATION';
CREATE UNIQUE INDEX llm_spend_ledger_one_ending
    ON llm_spend_ledger (call_id) WHERE kind IN ('SETTLEMENT', 'RETAINED', 'OVERRUN');
CREATE INDEX llm_spend_ledger_budget_idx ON llm_spend_ledger (budget_id, entry_id);

-- -- immutability ------------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION llm_spend_writer() RETURNS BOOLEAN LANGUAGE sql STABLE AS $$
    SELECT coalesce(current_setting('lab_brain.llm_spend_writer', TRUE), '') = 'on'
$$;

CREATE OR REPLACE FUNCTION llm_spend_ledger_append_only() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NOT llm_spend_writer() THEN
            RAISE EXCEPTION 'llm_spend_ledger is written only by the llm_spend_* functions';
        END IF;
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'llm_spend_ledger is append-only: % refused', TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER llm_spend_ledger_append_only
    BEFORE INSERT OR UPDATE OR DELETE ON llm_spend_ledger
    FOR EACH ROW EXECUTE FUNCTION llm_spend_ledger_append_only();

CREATE OR REPLACE FUNCTION llm_spend_prices_append_only() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'llm_spend_prices is append-only: a new price is a new declaration (% refused)',
        TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER llm_spend_prices_append_only
    BEFORE UPDATE OR DELETE ON llm_spend_prices
    FOR EACH ROW EXECUTE FUNCTION llm_spend_prices_append_only();

CREATE OR REPLACE FUNCTION llm_spend_budgets_guarded() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'a spend budget is never deleted: its ledger refers to it';
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
        OR NEW.declared_at IS DISTINCT FROM OLD.declared_at THEN
        RAISE EXCEPTION 'a spend budget''s parameters never change: declare a new budget';
    END IF;
    IF NOT llm_spend_writer() THEN
        RAISE EXCEPTION 'a spend budget''s ceiling, charge and circuit change only through the '
            'llm_spend_* functions, each of which writes the ledger row that explains it';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER llm_spend_budgets_guarded
    BEFORE INSERT OR UPDATE OR DELETE ON llm_spend_budgets
    FOR EACH ROW EXECUTE FUNCTION llm_spend_budgets_guarded();

-- -- the operations ----------------------------------------------------------------------------

-- Reserve one request's worst case, or raise. Returns the worst case reserved.
CREATE OR REPLACE FUNCTION llm_spend_reserve(
    p_budget TEXT, p_call TEXT, p_host TEXT, p_model TEXT,
    p_body_bytes BIGINT, p_images INTEGER, p_max_output BIGINT
) RETURNS NUMERIC AS $$
DECLARE
    b llm_spend_budgets%ROWTYPE;
    pr llm_spend_prices%ROWTYPE;
    v_input BIGINT;
    v_cost NUMERIC;
BEGIN
    IF p_max_output IS NULL OR p_max_output < 1 THEN
        RAISE EXCEPTION 'SPEND_REFUSED: the request carries no max_tokens, so its output and '
            'its cost have no bound';
    END IF;
    IF p_body_bytes IS NULL OR p_body_bytes < 1 OR p_images IS NULL OR p_images < 0 THEN
        RAISE EXCEPTION 'SPEND_REFUSED: the request size is not known';
    END IF;
    -- The row lock every concurrent reservation on this budget queues behind.
    SELECT * INTO b FROM llm_spend_budgets WHERE budget_id = p_budget FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'SPEND_REFUSED: no spend budget % is declared', p_budget;
    END IF;
    IF b.circuit_open THEN
        RAISE EXCEPTION 'SPEND_REFUSED: budget % is halted after an overrun on %; the Owner '
            'must review and close the circuit', p_budget, b.opened_by_call;
    END IF;
    SELECT * INTO pr FROM llm_spend_prices
     WHERE budget_id = p_budget AND endpoint_host = lower(p_host) AND model = p_model
     ORDER BY declared_at DESC, price_id DESC LIMIT 1;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'SPEND_REFUSED: no price is declared for model % at % under budget %',
            p_model, lower(p_host), p_budget;
    END IF;
    v_input := CEIL(p_body_bytes * b.safety_multiplier)::BIGINT
               + p_images::BIGINT * b.image_allowance_tokens + b.request_overhead_tokens;
    v_cost := (v_input * pr.input_per_mtok + p_max_output * pr.output_per_mtok) * 0.000001;
    IF b.charged + v_cost > b.ceiling THEN
        RAISE EXCEPTION 'SPEND_REFUSED: the request may cost up to % %; % of the % % ceiling is '
            'already charged', v_cost, b.currency, b.charged, b.ceiling, b.currency;
    END IF;
    PERFORM set_config('lab_brain.llm_spend_writer', 'on', TRUE);
    UPDATE llm_spend_budgets SET charged = charged + v_cost WHERE budget_id = p_budget;
    INSERT INTO llm_spend_ledger (budget_id, kind, call_id, endpoint_host, model, price_id,
        body_bytes, image_count, max_output_tokens, input_bound_tokens, worst_case, amount,
        charged_after, ceiling_after)
    VALUES (p_budget, 'RESERVATION', p_call, lower(p_host), p_model, pr.price_id, p_body_bytes,
        p_images, p_max_output, v_input, v_cost, v_cost, b.charged + v_cost, b.ceiling);
    PERFORM set_config('lab_brain.llm_spend_writer', '', TRUE);
    RETURN v_cost;
END;
$$ LANGUAGE plpgsql;

-- Settle a reservation to the provider's reported usage. Returns 'SETTLED' or 'OVERRUN'.
CREATE OR REPLACE FUNCTION llm_spend_settle(
    p_call TEXT, p_prompt BIGINT, p_completion BIGINT, p_total BIGINT
) RETURNS TEXT AS $$
DECLARE
    r llm_spend_ledger%ROWTYPE;
    b llm_spend_budgets%ROWTYPE;
    pr llm_spend_prices%ROWTYPE;
    v_output BIGINT;
    v_actual NUMERIC;
    v_charge NUMERIC;
    v_over BOOLEAN;
BEGIN
    IF p_prompt IS NULL OR p_completion IS NULL OR p_prompt < 0 OR p_completion < 0
        OR (p_total IS NOT NULL AND p_total < 0) THEN
        RAISE EXCEPTION 'a settlement needs the prompt and completion tokens the provider reported';
    END IF;
    SELECT * INTO r FROM llm_spend_ledger WHERE call_id = p_call AND kind = 'RESERVATION';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'no reservation % to settle', p_call;
    END IF;
    SELECT * INTO b FROM llm_spend_budgets WHERE budget_id = r.budget_id FOR UPDATE;
    SELECT * INTO pr FROM llm_spend_prices WHERE price_id = r.price_id;
    v_output := GREATEST(p_completion, coalesce(p_total - p_prompt, 0));
    v_actual := (p_prompt * pr.input_per_mtok + v_output * pr.output_per_mtok) * 0.000001;
    v_over := v_actual > r.worst_case OR p_prompt > r.input_bound_tokens
              OR v_output > r.max_output_tokens;
    v_charge := CASE WHEN v_over THEN GREATEST(v_actual, r.worst_case) ELSE v_actual END;
    PERFORM set_config('lab_brain.llm_spend_writer', 'on', TRUE);
    UPDATE llm_spend_budgets
       SET charged = charged - r.worst_case + v_charge,
           circuit_open = circuit_open OR v_over,
           opened_by_call = CASE WHEN circuit_open THEN opened_by_call
                                 WHEN v_over THEN p_call END
     WHERE budget_id = r.budget_id
     RETURNING * INTO b;
    INSERT INTO llm_spend_ledger (budget_id, kind, call_id, endpoint_host, model, price_id,
        prompt_tokens, completion_tokens, total_tokens, worst_case, amount, charged_after,
        ceiling_after, reason)
    VALUES (r.budget_id, CASE WHEN v_over THEN 'OVERRUN' ELSE 'SETTLEMENT' END, p_call,
        r.endpoint_host, r.model, r.price_id, p_prompt, p_completion, p_total, r.worst_case,
        v_charge, b.charged, b.ceiling,
        CASE WHEN v_over THEN 'reported usage passed the reservation; circuit opened' END);
    PERFORM set_config('lab_brain.llm_spend_writer', '', TRUE);
    RETURN CASE WHEN v_over THEN 'OVERRUN' ELSE 'SETTLED' END;
END;
$$ LANGUAGE plpgsql;

-- Keep a reservation charged at its worst case: no usable usage, an error, a timeout.
CREATE OR REPLACE FUNCTION llm_spend_retain(p_call TEXT, p_reason TEXT) RETURNS VOID AS $$
DECLARE
    r llm_spend_ledger%ROWTYPE;
    b llm_spend_budgets%ROWTYPE;
BEGIN
    SELECT * INTO r FROM llm_spend_ledger WHERE call_id = p_call AND kind = 'RESERVATION';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'no reservation % to retain', p_call;
    END IF;
    SELECT * INTO b FROM llm_spend_budgets WHERE budget_id = r.budget_id FOR UPDATE;
    PERFORM set_config('lab_brain.llm_spend_writer', 'on', TRUE);
    INSERT INTO llm_spend_ledger (budget_id, kind, call_id, endpoint_host, model, price_id,
        worst_case, amount, charged_after, ceiling_after, reason)
    VALUES (r.budget_id, 'RETAINED', p_call, r.endpoint_host, r.model, r.price_id,
        r.worst_case, r.worst_case, b.charged, b.ceiling, left(coalesce(p_reason, ''), 240));
    PERFORM set_config('lab_brain.llm_spend_writer', '', TRUE);
END;
$$ LANGUAGE plpgsql;

-- The Owner's change of ceiling, and the only way to close an open circuit.
CREATE OR REPLACE FUNCTION llm_spend_set_ceiling(
    p_budget TEXT, p_ceiling NUMERIC, p_actor TEXT, p_reason TEXT, p_close_circuit BOOLEAN
) RETURNS VOID AS $$
DECLARE
    b llm_spend_budgets%ROWTYPE;
BEGIN
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
$$ LANGUAGE plpgsql;
