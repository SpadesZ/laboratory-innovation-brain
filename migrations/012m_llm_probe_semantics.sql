-- What qualification semantics a capability probe was actually run under.
--
-- A lock's fingerprint names the qualification semantics in force when it was made
-- (`llm_runtime.probes.QUALIFICATION_DIGEST`: probe payloads, role prompts, response contracts), and
-- a lock made under other semantics is stale. But a probe row named only its `probe_version`, so a
-- lock made NOW could count probe rows run under earlier semantics whenever a prompt, contract or
-- payload changed without a version bump -- evidence from old semantics laundered into a current
-- lock. Each probe now records the digest it ran under, and a lock counts a probe only when that
-- digest is the one in force (`registry.lock`, `registry.lock_problem`).
--
-- Rows written before carry none: their semantics cannot be proven, so they qualify nothing -- the
-- model is tested again. No row is rewritten; the table stays append-only (`012e`).

ALTER TABLE llm_capability_probes
    ADD COLUMN IF NOT EXISTS qualification_digest TEXT
    CHECK (qualification_digest IS NULL OR qualification_digest ~ '^[0-9a-f]{64}$');

COMMENT ON COLUMN llm_capability_probes.qualification_digest IS
    'The qualification-semantics digest in force when the probe ran (012m). NULL for earlier rows: '
    'unproven, so never counted by a lock.';
