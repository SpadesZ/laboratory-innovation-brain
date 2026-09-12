-- 004b_evidence_bundle_immutability.sql
--
-- Evidence bundles are append-only once written (P2, EVI-006).
--
-- Migration 004a made a bundle *storable* and its ordering *reconstructable*. It did not make it
-- *immutable*, which leaves the guarantee hollow: `UPDATE evidence_bundles SET query_text = ...`
-- silently rewrites what an LLM is recorded as having been shown, while `canonical_hash` still
-- reads as valid to anyone who does not recompute it. The same applies to the member rows --
-- repointing `attestation_id`, re-homing a member to another bundle, reordering `position`, or
-- deleting a member all change the evidence set that a stored hash claims to cover.
--
-- That is worse than an ordinary data bug. A bundle hash exists so that "the model concluded X
-- because it saw Y" can be checked later. A mutable bundle means the check passes against whatever
-- the row says today, so the audit trail confirms a history that may never have happened.
--
-- Corrections create a NEW bundle. That is not a workaround: a different evidence set *is* a
-- different retrieval, and 004a deliberately left `canonical_hash` non-unique so the same
-- retrieval may recur as its own row.
--
-- Not done here: recomputing the JCS hash in plpgsql. Two implementations of a canonicalisation
-- standard is how hashes start disagreeing (see 004a). Immutability is enforced structurally
-- instead, so the application-side hash stays the only one.

CREATE FUNCTION lab_brain_reject_bundle_mutation() RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION
        'evidence_bundles is append-only: % on bundle % is refused. A bundle records what an LLM '
        'was shown; rewriting it would leave canonical_hash asserting a retrieval that never '
        'happened. Create a new bundle instead (EVI-006, P2).',
        TG_OP, coalesce(NEW.bundle_id, OLD.bundle_id)
        USING ERRCODE = 'restrict_violation';
END;
$$;

COMMENT ON FUNCTION lab_brain_reject_bundle_mutation() IS
    'EVI-006 / P2: evidence bundles are append-only. Corrections create a new bundle.';

CREATE FUNCTION lab_brain_reject_bundle_member_mutation() RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION
        'evidence_bundle_members is append-only: % on bundle % is refused. Repointing, re-homing, '
        'reordering or deleting a member changes the evidence set the stored canonical_hash '
        'claims to cover. Create a new bundle instead (EVI-006, P2).',
        TG_OP, coalesce(NEW.bundle_id, OLD.bundle_id)
        USING ERRCODE = 'restrict_violation';
END;
$$;

COMMENT ON FUNCTION lab_brain_reject_bundle_member_mutation() IS
    'EVI-006 / P2: bundle membership and ordering are append-only.';

-- All columns, not a subset. A column-level trigger list would have to be extended by hand every
-- time the table gains a field, and the field most likely to be forgotten is the one added under
-- deadline pressure.
CREATE TRIGGER evidence_bundles_no_update
    BEFORE UPDATE ON evidence_bundles
    FOR EACH ROW EXECUTE FUNCTION lab_brain_reject_bundle_mutation();

CREATE TRIGGER evidence_bundles_no_delete
    BEFORE DELETE ON evidence_bundles
    FOR EACH ROW EXECUTE FUNCTION lab_brain_reject_bundle_mutation();

CREATE TRIGGER evidence_bundle_members_no_update
    BEFORE UPDATE ON evidence_bundle_members
    FOR EACH ROW EXECUTE FUNCTION lab_brain_reject_bundle_member_mutation();

CREATE TRIGGER evidence_bundle_members_no_delete
    BEFORE DELETE ON evidence_bundle_members
    FOR EACH ROW EXECUTE FUNCTION lab_brain_reject_bundle_member_mutation();

-- Note on the 004a ON DELETE CASCADE: it is now unreachable, because deleting a bundle is itself
-- refused. Left in place deliberately -- if a future migration ever relaxes the bundle-delete
-- trigger, the cascade must still be there to avoid orphan member rows.
