-- 004_relations.sql
--
-- RelationJudgment (§17.8) — the single source of truth for support and contradiction.
--
-- Bitemporal on purpose. `valid_from` / `valid_to` record when a judgment was *held*, which is
-- what lets as_of replay reconstruct the belief state of a past date. Without it, replaying old
-- events against today's relations produces a state the lab never actually held (§17.12).
--
-- Relations are never deleted. Invalidation sets valid_to and records a reason, because a
-- silently removed judgment is indistinguishable from one that was never made (P2).

CREATE TABLE relation_judgments (
    relation_id               TEXT PRIMARY KEY,
    from_entity_id            TEXT NOT NULL,
    to_entity_id              TEXT NOT NULL,
    relation_type             TEXT NOT NULL
        CHECK (relation_type IN ('SUPPORTS', 'CONTRADICTS', 'TESTS', 'PREDICTS',
                                 'PRODUCES', 'DERIVED_FROM', 'INSTANTIATES', 'SUPERSEDES',
                                 'SAME_WORK_AS', 'CITES', 'SUGGESTS_CHECK')),

    attributes                JSONB NOT NULL DEFAULT '{}'::jsonb,
    supporting_attestation_ids TEXT[] NOT NULL DEFAULT '{}',
    condition_match_ref       TEXT REFERENCES condition_matches (condition_match_id),
    -- Required for LLM-produced judgments (AGT-010). FK added in M0b with the provenance table.
    inference_provenance_id   TEXT,
    actor_id                  TEXT REFERENCES actors (actor_id),

    project_id                TEXT NOT NULL REFERENCES projects (project_id),
    valid_from                TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_to                  TIMESTAMPTZ,
    invalidation_reason       TEXT,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT relation_judgments_no_self_relation
        CHECK (from_entity_id <> to_entity_id),
    CONSTRAINT relation_judgments_interval_ordered
        CHECK (valid_to IS NULL OR valid_to >= valid_from),
    -- Closing a relation records why; opening one must not pretend to have been closed.
    CONSTRAINT relation_judgments_invalidation_accounted
        CHECK ((valid_to IS NULL) = (invalidation_reason IS NULL)),
    -- P7: an epistemic effect with no provenance is an unsourced assertion. SUPPORTS,
    -- CONTRADICTS, TESTS and PREDICTS move belief, so each must name the attestations it rests
    -- on, the inference that produced it, or the actor who asserted it.
    CONSTRAINT relation_judgments_epistemic_provenance
        CHECK (relation_type NOT IN ('SUPPORTS', 'CONTRADICTS', 'TESTS', 'PREDICTS')
               OR cardinality(supporting_attestation_ids) > 0
               OR inference_provenance_id IS NOT NULL
               OR actor_id IS NOT NULL)
);

-- Traversal indexes. §17.12 requires every traversal to be bounded, so these support
-- limit+order queries rather than full scans.
CREATE INDEX relation_judgments_from_idx
    ON relation_judgments (from_entity_id, relation_type, valid_from DESC);
CREATE INDEX relation_judgments_to_idx
    ON relation_judgments (to_entity_id, relation_type, valid_from DESC);
CREATE INDEX relation_judgments_current_idx
    ON relation_judgments (from_entity_id, to_entity_id) WHERE valid_to IS NULL;
CREATE INDEX relation_judgments_project_idx ON relation_judgments (project_id, created_at DESC);

-- EvidenceIndependence (§6.17). Separate from relation_judgments because it answers a different
-- question: not "does A support B" but "are A and B the same underlying work".
--
-- EVI-004: DEPENDENCE_UNKNOWN contributes 0 to min_independent_attestations. It is stored
-- rather than treated as absent, so an unresolved pair stays visible as supporting context
-- without being counted as independent.
CREATE TABLE evidence_independence (
    a_id          TEXT NOT NULL,
    b_id          TEXT NOT NULL,
    relation      TEXT NOT NULL
        CHECK (relation IN ('INDEPENDENT', 'DERIVED_FROM', 'SAME_WORK', 'CITES', 'UNKNOWN')),
    -- Only WORK is implemented in v3.3. A policy declaring a stronger basis MUST escalate to
    -- human review rather than assume independence (§6.17).
    basis         TEXT NOT NULL DEFAULT 'WORK'
        CHECK (basis IN ('WORK', 'GROUP', 'SAMPLE', 'INSTRUMENT', 'METHOD')),
    rationale_ref TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (a_id, b_id, basis),
    CONSTRAINT evidence_independence_distinct CHECK (a_id <> b_id)
);

CREATE INDEX evidence_independence_b_idx ON evidence_independence (b_id, basis);
