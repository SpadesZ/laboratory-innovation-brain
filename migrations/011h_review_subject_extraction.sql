-- 011h_review_subject_extraction.sql
--
-- UX-005 / §17.22 / §14.4.1.
--
-- UX-005: "NEEDS_REVIEW MUST be represented by a ReviewItem so it feeds ReviewQueue capacity and
-- human-review Capability availability (OPS-002). A parallel review surface that bypasses
-- ReviewQueue is prohibited."
--
-- `011b` shipped `review_items` with `subject_type IN ('CONFLICT', 'AUTHORITY_CONFLICT')`,
-- because M0b's only reviewable subjects were conflicts. A low-confidence extraction is neither,
-- so an ingestion item needing review had nowhere to go in the existing table.
--
-- WHY THIS IS AN EXTENSION AND NOT A REOPENING OF M0b.
--
-- The alternative -- an `extraction_reviews` table with its own queue -- is exactly the "parallel
-- review surface" UX-005 prohibits, and the prohibition has teeth: ReviewQueue capacity feeds
-- `HumanReviewCapability.availability` (§14.4.1), so a second queue would consume the same
-- humans' attention while being invisible to the planner that is supposed to price it. The
-- system would then plan as though reviewers were free.
--
-- So this ADDS a vocabulary member and changes nothing else. Every M0b behaviour is untouched:
-- the escalation path, the SLA/expiry policy, `review_expire`, the conflict-closure invariant and
-- the `011d` commit-boundary trigger all read `subject_type` only to distinguish
-- AUTHORITY_CONFLICT, and none of them changes meaning because a third value exists. OPS-002 and
-- EPI-004/EPI-006 stay DONE and are not reopened.
--
-- NO FOREIGN KEY on `subject_id`, consistent with `011b`'s decision for the same column. `011b`
-- records why: `subject_id` is deliberately not a foreign key, because the subject's table
-- depends on the type and PostgreSQL has no polymorphic reference. `011d`'s header explains why
-- treating it as gating would be wrong.

ALTER TABLE review_items DROP CONSTRAINT review_items_subject_type_check;

ALTER TABLE review_items ADD CONSTRAINT review_items_subject_type_check
    CHECK (subject_type IN (
        'CONFLICT',
        'AUTHORITY_CONFLICT',
        -- UX-005. The subject is the IngestionItem whose extraction was uncertain, not the
        -- Attestation: §17.22 attaches `review_ids[]` to the item, and a reviewer needs the whole
        -- document context to judge whether a field really is unknown (EVI-002). Pointing at one
        -- Attestation would show them a value with nothing to compare it against.
        'EXTRACTION_UNCERTAINTY'
    ));

COMMENT ON COLUMN review_items.subject_type IS
    'CONFLICT / AUTHORITY_CONFLICT (M0b, EPI-006/EPI-004) and EXTRACTION_UNCERTAINTY (M1, '
    'UX-005). One queue, because ReviewQueue depth is what prices human attention in §14.4.1 -- '
    'a second review surface would consume the same reviewers while being invisible to the '
    'planner.';

-- The production enqueue path for UX-005, mirroring `authority_conflict_escalate`.
--
-- PRICED FROM THE ACTIVE POLICY, never from the caller. `011e` made that the rule for the
-- escalation path and the reason is the same here: a caller that supplied its own `due_at` could
-- give itself an SLA nobody agreed to, and the queue's capacity accounting would then be pricing
-- work against deadlines it did not set.
--
-- IDEMPOTENT on `review_id`, like the escalation path. A retrying ingestion worker must not
-- enqueue the same uncertain extraction twice -- the second copy would consume real reviewer
-- capacity for work already waiting, and §14.4.1 prices human attention from exactly that depth.
CREATE FUNCTION extraction_review_enqueue(
    p_review_id     TEXT,
    p_project_id    TEXT,
    p_item_id       TEXT,
    p_stakes        TEXT,
    p_reason        TEXT,
    p_trace_id      TEXT,
    p_created_at    TIMESTAMPTZ,
    -- How much reviewer time this item is expected to cost. A parameter rather than a
    -- zero default: 14.4.1 prices human attention from the SUM of these, so an item
    -- costing 0 occupies a queue slot while telling the planner review is still free.
    p_estimated_minutes INTEGER DEFAULT 30
) RETURNS TEXT AS $$
DECLARE
    v_policy  review_queue_policies%ROWTYPE;
    v_existing TEXT;
BEGIN
    IF p_estimated_minutes <= 0 THEN
        RAISE EXCEPTION
            'review % would cost 0 reviewer minutes. 14.4.1 prices human attention from the '
            'sum of these, so a zero-cost item occupies a slot while telling the planner '
            'review is still free', p_review_id;
    END IF;

    SELECT review_id INTO v_existing FROM review_items WHERE review_id = p_review_id;
    IF FOUND THEN
        RETURN v_existing;
    END IF;

    SELECT * INTO v_policy
      FROM review_queue_policies
     WHERE project_id = p_project_id AND active
     ORDER BY effective_from DESC
     LIMIT 1;
    IF NOT FOUND THEN
        RAISE EXCEPTION
            'project % has no active review queue policy, so review % would have no deadline and '
            'could park in PENDING indefinitely (§14.4)', p_project_id, p_review_id;
    END IF;

    INSERT INTO review_items (
        review_id, project_id, subject_type, subject_id, stakes, reason, trace_id,
        created_at, queue_policy_id, queue_policy_version, due_at, expires_at, status,
        estimated_human_minutes
    ) VALUES (
        p_review_id, p_project_id, 'EXTRACTION_UNCERTAINTY', p_item_id, p_stakes, p_reason,
        p_trace_id, p_created_at, v_policy.policy_id, v_policy.version,
        p_created_at + make_interval(mins => v_policy.default_sla_minutes),
        p_created_at + make_interval(mins => v_policy.default_expiry_minutes),
        'QUEUED', p_estimated_minutes
    );
    RETURN p_review_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION extraction_review_enqueue IS
    'UX-005: enqueue a low-confidence extraction into the ONE ReviewQueue. Priced from the '
    'active policy, idempotent on review_id so a retrying worker cannot consume reviewer '
    'capacity twice for the same item.';
