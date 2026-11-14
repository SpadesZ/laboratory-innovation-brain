-- 007c_capabilities.sql
--
-- VER-002 / §9.5 / §17.18. The capabilities half of Appendix A's `007` slot; `007a` took the cost
-- half in M0b-2 and its header already recorded that this half "lands with VER-002 in M2".
--
-- WHAT THIS TABLE IS FOR, in one sentence: a backend with no descriptor MUST NOT be plannable, and
-- the only way "no descriptor" can be a fact rather than a convention is for descriptors to live
-- somewhere a planner has to look.
--
-- NO created_at, AND THAT IS DELIBERATE. `schema_drift.BINDINGS` binds this table field-for-field
-- against §17.18's canonical block and the `Capability` model, in BOTH directions -- a column the
-- spec does not declare is reported as drift exactly like a declared field that is missing. §17.18
-- declares fifteen fields and no audit timestamp, so the table has fifteen columns. Registration
-- history is `version`: §9.5's descriptor is versioned, a change gets a new version, and a
-- `created_at` on a row that is replaced in place would record when the CURRENT descriptor was
-- written rather than when the capability was first offered -- which is the question it looks like
-- it answers. §17.4's Run records which `capability_id` executed and when; that is the audit trail.
--
-- NO FOREIGN KEY TO projects. A Capability is not project-scoped: §9.5's registry describes what
-- the *system* can do, and the same CHARGE capability is available to every project that holds a
-- license seat. What is project-scoped is the Job that consumes it (`006`), and SEC-002 is enforced
-- there. Adding a project column here would force one descriptor row per project and make
-- "is this backend plannable" a question with N answers.

CREATE TABLE IF NOT EXISTS capabilities (
    capability_id   TEXT PRIMARY KEY,

    -- NULL for a core capability (a repository lookup, a human review). A DomainPack's
    -- capabilities name their domain, which is what makes DOM-SP-001's "remove the plugin and core
    -- still starts" a filter rather than a code change.
    domain          TEXT,

    -- §9.3's verification action types. CHECKed rather than left free: the planner ranks by action
    -- type, and an unrecognised value would rank against nothing and be silently unplannable.
    action_type     TEXT NOT NULL CHECK (action_type IN (
                        'EXISTING_EVIDENCE_LOOKUP',
                        'ANALYTICAL_RULE_CHECK',
                        'HISTORICAL_CASE_COMPARISON',
                        'NUMERICAL_SURROGATE',
                        'SIMULATION',
                        'MEASUREMENT',
                        'FABRICATION',
                        'HUMAN_EXPERT_REVIEW')),

    backend_id      TEXT NOT NULL,

    -- §9.5's matching surface. TEXT[] because these are opaque observable/artifact kind names --
    -- core checks set membership and never interprets them, which is what keeps `Cj_per_length`
    -- out of the core schema (§24.1, §24.2).
    requires        TEXT[] NOT NULL DEFAULT '{}',
    produces        TEXT[] NOT NULL DEFAULT '{}',

    -- Domain-supplied and compared by AuthorityPolicy (ADR-0007). NOT an ordered column and
    -- deliberately not an enum: core holds no ranking, and a CHECK listing the legal classes here
    -- would be core declaring a domain's vocabulary.
    authority_class TEXT NOT NULL,

    availability    TEXT NOT NULL DEFAULT 'AVAILABLE'
                        CHECK (availability IN ('AVAILABLE', 'DEGRADED', 'UNAVAILABLE')),

    conditions_schema_version TEXT REFERENCES condition_schemas (schema_ref),

    privacy_constraints TEXT[] NOT NULL DEFAULT '{}',
    license_constraints TEXT[] NOT NULL DEFAULT '{}',

    irreversible    BOOLEAN NOT NULL DEFAULT FALSE,
    earliest_available_at TIMESTAMPTZ,

    -- §17.18: "reference to the implementation of estimate_cost(params) -> CostVector". The NAME
    -- of the estimator, resolved by CapabilityRegistry. Storing a callable would make the row
    -- unserialisable and "which estimator priced this action" unanswerable after the fact.
    estimate_cost_contract TEXT NOT NULL,

    version         TEXT NOT NULL,

    -- §9.5: a capability that produces nothing can never be selected, so a descriptor that
    -- declares nothing is a registration nobody will notice is wrong. Refused at the row, because
    -- the Python validator only guards records built through the model.
    CONSTRAINT capabilities_produce_something
        CHECK (cardinality(produces) > 0),

    -- An action that consumes what it yields satisfies its own precondition, and the planner would
    -- schedule it against itself.
    CONSTRAINT capabilities_requires_disjoint_from_produces
        CHECK (NOT (requires && produces)),

    -- §10.7's WAITING_RESOURCE exists for contention over a finite external resource. A license
    -- constraint on a repository lookup would park work waiting for a seat that does not exist.
    CONSTRAINT capabilities_license_only_where_contended
        CHECK (cardinality(license_constraints) = 0
               OR action_type IN ('SIMULATION', 'MEASUREMENT', 'FABRICATION')),

    CONSTRAINT capabilities_id_shape CHECK (capability_id ~ '^cap:[a-z0-9][a-z0-9_.\-]*$')
);

CREATE INDEX IF NOT EXISTS capabilities_domain_idx      ON capabilities (domain);
CREATE INDEX IF NOT EXISTS capabilities_action_type_idx ON capabilities (action_type);


-- §10.7's license/seat accounting, and the reason it is a table rather than a counter.
--
-- "How many seats are in use" computed from a variable is correct for one process and wrong for
-- two -- the same argument `006`'s `runs.job_id UNIQUE` makes about duplicate callbacks. Two
-- schedulers both read "one seat free", both dispatch, and the vendor's license manager refuses
-- the second execution at a point where the Job has already been told it is RUNNING.
--
-- So a seat is a ROW, `resource_id` carries the declared seat count, and a lease insert fails when
-- the pool is full. The refusal is then a fact about the database rather than a race between
-- readers, and WAITING_RESOURCE is what the loser records.
--
-- NOT A SECOND QUEUE. §10.7 puts queueing on the Job (`state`, `resource_requirements`), and this
-- holds only the *seats*: which resource, how many exist, and who currently holds one. A job
-- waiting for a seat is WAITING_RESOURCE in `jobs`, exactly as it was before this table existed.
CREATE TABLE IF NOT EXISTS resource_pools (
    resource_id     TEXT PRIMARY KEY,
    display_name    TEXT NOT NULL,

    -- 0 is legal and means "declared, and none available" -- an environment with no Lumerical seat
    -- is exactly that, and it is NOT the same as an undeclared resource. The first parks jobs in
    -- WAITING_RESOURCE; the second is a wiring error the broker refuses.
    total_seats     INTEGER NOT NULL CHECK (total_seats >= 0),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS resource_leases (
    lease_id        TEXT PRIMARY KEY,
    resource_id     TEXT NOT NULL REFERENCES resource_pools (resource_id),

    -- The Job holding the seat. UNIQUE so a job cannot hold two seats of the same resource by
    -- retrying its own acquisition -- a duplicate dispatch would otherwise consume the pool.
    job_id          TEXT NOT NULL REFERENCES jobs (job_id),
    seats           INTEGER NOT NULL CHECK (seats > 0),
    acquired_at     TIMESTAMPTZ NOT NULL,

    -- NULL while held. Released leases are retained rather than deleted: "who was holding the
    -- seats when this job was refused one" is the question a contention incident actually asks,
    -- and a DELETE answers it with silence.
    released_at     TIMESTAMPTZ,

    CONSTRAINT resource_leases_released_after_acquired
        CHECK (released_at IS NULL OR released_at >= acquired_at)
);

-- One HELD lease per (resource, job). A released one may be re-acquired, so the uniqueness is
-- partial rather than a plain UNIQUE.
CREATE UNIQUE INDEX IF NOT EXISTS resource_leases_one_held_per_job
    ON resource_leases (resource_id, job_id)
    WHERE released_at IS NULL;

CREATE INDEX IF NOT EXISTS resource_leases_held_idx
    ON resource_leases (resource_id)
    WHERE released_at IS NULL;


-- The seat ceiling, enforced where two writers cannot both win.
--
-- A BEFORE trigger rather than application logic, for the reason in the header: the check and the
-- insert have to be one atomic act. `pg_advisory_xact_lock` serialises acquisitions per resource
-- so the SUM below cannot be read by two transactions that then both insert -- a plain SELECT
-- under READ COMMITTED would not see the other's uncommitted row.
CREATE OR REPLACE FUNCTION resource_lease_within_pool() RETURNS TRIGGER AS $$
DECLARE
    declared INTEGER;
    held     INTEGER;
BEGIN
    IF NEW.released_at IS NOT NULL THEN
        RETURN NEW;
    END IF;

    PERFORM pg_advisory_xact_lock(hashtext('resource_pool:' || NEW.resource_id));

    SELECT total_seats INTO declared FROM resource_pools WHERE resource_id = NEW.resource_id;
    SELECT COALESCE(SUM(seats), 0) INTO held
      FROM resource_leases
     WHERE resource_id = NEW.resource_id
       AND released_at IS NULL
       AND lease_id <> NEW.lease_id;

    IF held + NEW.seats > declared THEN
        RAISE EXCEPTION
            'resource % has % seat(s) and % already held; lease of % would exceed the pool. '
            '§10.7 parks the job in WAITING_RESOURCE -- it is not a simulation failure',
            NEW.resource_id, declared, held, NEW.seats
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS resource_leases_within_pool ON resource_leases;
CREATE TRIGGER resource_leases_within_pool
    BEFORE INSERT OR UPDATE ON resource_leases
    FOR EACH ROW EXECUTE FUNCTION resource_lease_within_pool();
