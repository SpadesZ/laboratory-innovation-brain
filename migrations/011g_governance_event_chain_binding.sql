-- 011g — a GovernanceEvent must belong to the chain it closes (`v3.3-a16`)
--
-- Forward-only. `005a`–`005d` and `011a`–`011f` are applied and their files are not touched.
--
-- WHAT `011f` PROVED, AND THE ONE THING IT DID NOT. `011f` made the closure reference a typed pair
-- and taught both `conflict_close` and the commit-boundary invariant to compare it:
--
--     ReviewItem -> ReviewResolution -> (resolution_event_kind, event id) <- Conflict
--
-- Every link there is checked. What is *not* checked is the far end of the reference: nothing loads
-- the referenced `GovernanceEvent` and asks whether that event was written for **this** review.
-- So a real, legitimately produced `REVIEW_EXPIRY` event could be presented as closure proof for a
-- different review in the same project:
--
--     Review A, Conflict A, QueuePolicy P   ->  GovernanceEvent G
--                                               subject_id          = Review A
--                                               related_conflict_id = Conflict A
--                                               policy              = P
--
--     raw SQL then writes
--         ReviewResolution B (EXPIRED, governance_event_id = G)
--         Review B   -> EXPIRED
--         Conflict B -> ACCEPTED_AS_OPEN_QUESTION, governance_event_id = G
--
-- and `011f` commits it: the resolution belongs to review B, the outcome agrees with the status,
-- the conflict and the resolution agree on (kind, id), and the event is a genuine REVIEW_EXPIRY in
-- the right project. Every existing check passes and a block lifted on an authority that was never
-- granted for it. This is the `v3.3-a14` substitution -- "an arbitrary event that merely belongs to
-- the same project MUST NOT be accepted as closure proof" -- reappearing one indirection further
-- out, at the only link the typed pair did not reach. §17.19.1 as amended by `v3.3-a15` already
-- says the pair must hold "for the same review/conflict chain"; `v3.3-a16` states what that chain
-- is, and this migration is what makes the sentence executable.
--
-- WHY THE EXISTING INVARIANT IS EXTENDED RATHER THAN JOINED BY A SECOND ONE. Closure validity is
-- one question. A separate constraint would be a second, independently maintainable notion of what
-- makes a closure legitimate, and the first thing two such notions do is disagree -- one of them
-- then says a chain is valid and the writer picks that one. `review_conflict_invariant_assert` is
-- already the single place that judges a terminal review against its conflict at COMMIT, and it is
-- already deferred for the reason `011d` gives: the one valid operation necessarily passes through
-- a forbidden intermediate state. The chain binding belongs in it.
--
-- WHAT IS REACHABLE AND WHAT IS STRUCTURAL, STATED BECAUSE THIS PROJECT COUNTS DEAD BRANCHES AS
-- DEFECTS. Of the facts proved below, six are reachable by raw SQL and each has a negative test
-- that isolates it: the review binding, the conflict binding, the policy id, the policy version,
-- the policy declarer, and the executor/resolver agreement. Three are *unrepresentable* rather
-- than merely wrong, and are written here anyway:
--
--   event_type / subject_type    a CHECK on `governance_events` admits one value each. Folded into
--                                the lookup predicate rather than given their own RAISE arms, so
--                                the cost is one branch instead of two -- and so that widening the
--                                vocabulary later stops this lookup matching instead of silently
--                                admitting a new kind as expiry closure proof.
--   the event's project          `review_resolutions_governance_event_in_project` is a composite
--                                foreign key, so a cross-project reference cannot be written at
--                                all. Checked here for the reason `011d` states about its own
--                                project comparisons: if that constraint were ever dropped this
--                                still catches it, and a check that is vacuous today is not a
--                                check that is wrong.
--   the queue policy row         `governance_events_policy_in_project` is the same shape. The
--                                lookup happens regardless, because the policy is where
--                                `declared_by_actor_id` is read from.
--
-- TWO FURTHER REPAIRS, BOTH NARROW.
--
--   `declared_by_actor_id` becomes required for REVIEW_EXPIRY. `011f` left it nullable while
--   simultaneously making `review_queue_policies.declared_by_actor_id` NOT NULL -- so for the only
--   event type that exists there is always a correct value, and "absent" stopped being a shape the
--   field can honestly take. Written as a CHECK keyed on `event_type` rather than a bare NOT NULL,
--   because that is the sentence §17.19.1 states and it stays correct if a second kind is ever
--   admitted with different provenance.
--
--   The executor must be ACTIVE. An unknown executor already fails on the actors foreign key; an
--   actor row with `active = FALSE` did not, so a decommissioned service account could still expire
--   reviews. Enforced as a BEFORE INSERT trigger and deliberately **not** in the deferred invariant:
--   the question is whether the executor was active *when the sweep ran*, and re-asking it at every
--   later commit would retroactively invalidate expiries that were legitimate when written -- and
--   would make deactivating a service account corrupt history rather than stop it.
--
-- WHAT IS STILL NOT IN SQL, UNCHANGED FROM `011d` AND `011f`. No belief semantics, no new authority
-- or approval-scope system, and no widening of `event_type`. Everything below is structural: that
-- the records referenced exist, belong to each other, belong to one project, and name the same
-- review, conflict, policy version and actors that the chain they close was built from.

-- ---------------------------------------------------------------------------------------------
-- 1. Refuse to evolve a database that already holds a chain this cannot reconcile
-- ---------------------------------------------------------------------------------------------
--
-- Same shape as `011b`, `011d`, `011e` and `011f`, and for the same reason: a constraint added over
-- data that violates it is a constraint that silently means less than it says. There is no correct
-- value to invent for an expiry somebody already executed -- attributing it to a policy author or
-- to an active actor after the fact would manufacture exactly the authority record this migration
-- exists to require -- so the migration stops and the operator decides. The RAISE aborts the whole
-- file, so nothing below is created either.

DO $$
DECLARE
    v_unattributed INTEGER;
    v_inactive     INTEGER;
    v_unchained    INTEGER;
BEGIN
    SELECT count(*) INTO v_unattributed
      FROM governance_events
     WHERE event_type = 'REVIEW_EXPIRY' AND declared_by_actor_id IS NULL;

    IF v_unattributed > 0 THEN
        RAISE EXCEPTION
            'refusing to require declared_by_actor_id on a REVIEW_EXPIRY: this database already '
            'holds % governance events with none, written before the field was required. The '
            'standing authority for an automatic expiry is the actor who declared the queue '
            'policy, and inferring it now -- least of all from the service account that ran the '
            'sweep -- would manufacture the authority record v3.3-a16 exists to require. '
            'Re-create the database from empty, or attribute each event by hand first',
            v_unattributed;
    END IF;

    SELECT count(*) INTO v_inactive
      FROM governance_events g
      JOIN actors a ON a.actor_id = g.actor_id
     WHERE g.event_type = 'REVIEW_EXPIRY' AND NOT a.active;

    IF v_inactive > 0 THEN
        RAISE EXCEPTION
            'refusing to require an active executor: this database already holds % REVIEW_EXPIRY '
            'events executed by an actor that is now inactive. Whether they were active at the '
            'time is not recoverable from these rows, and guessing either way rewrites what '
            'happened. Re-create the database from empty, or adjudicate each event by hand first',
            v_inactive;
    END IF;

    -- The chain binding itself. Every terminal GOVERNANCE closure already on disk must already
    -- satisfy what the invariant below will require of every later one; enforcing it only going
    -- forward would leave existing rows permanently unreadable by their own rule.
    SELECT count(*) INTO v_unchained
      FROM review_resolutions r
      JOIN review_items i
        ON i.review_id = r.review_id AND i.project_id = r.project_id
      JOIN governance_events g
        ON g.event_id = r.governance_event_id
      LEFT JOIN review_queue_policies p
        ON p.policy_id  = g.policy_id
       AND p.version    = g.policy_version
       AND p.project_id = g.project_id
     WHERE r.resolution_event_kind = 'GOVERNANCE'
       AND (g.project_id           IS DISTINCT FROM i.project_id
         OR g.subject_id           IS DISTINCT FROM i.review_id
         OR g.policy_id            IS DISTINCT FROM i.queue_policy_id
         OR g.policy_version       IS DISTINCT FROM i.queue_policy_version
         OR p.policy_id            IS NULL
         OR g.declared_by_actor_id IS DISTINCT FROM p.declared_by_actor_id
         OR g.actor_id             IS DISTINCT FROM r.resolved_by_actor_id);

    IF v_unchained > 0 THEN
        RAISE EXCEPTION
            'refusing to enforce the v3.3-a16 chain binding: this database already holds % '
            'GOVERNANCE closures citing an event that was not written for that review, policy '
            'version or actor. Those are the substitutions this migration exists to refuse, and '
            'adding the check now would report the invariant as enforced while leaving them '
            'standing. Re-create the database from empty, or adjudicate each closure by hand first',
            v_unchained;
    END IF;
END;
$$;

-- ---------------------------------------------------------------------------------------------
-- 2. A REVIEW_EXPIRY names the authority it executed
-- ---------------------------------------------------------------------------------------------
--
-- `011f` made `review_queue_policies.declared_by_actor_id` NOT NULL and then left the event's copy
-- optional. For the only event type in the vocabulary there is therefore always a correct value,
-- and an absent one can only mean the writer declined to record it -- which is the state
-- §17.19.1's "MUST NOT be inferred from the service account that executes the sweep" is about.
--
-- KEYED ON `event_type`, NOT A BARE NOT NULL. The two are equivalent while the vocabulary holds one
-- value, and they stop being equivalent the moment it does not. A second kind would have to state
-- its own provenance rule rather than inherit this one by accident, which is the same reason
-- `review_resolutions_governance_only_expires` is written as an implication.

ALTER TABLE governance_events
    DROP CONSTRAINT IF EXISTS governance_events_expiry_names_its_authority;
ALTER TABLE governance_events
    ADD CONSTRAINT governance_events_expiry_names_its_authority
    CHECK (event_type <> 'REVIEW_EXPIRY' OR declared_by_actor_id IS NOT NULL);

COMMENT ON COLUMN governance_events.declared_by_actor_id IS
    'v3.3-a16: for REVIEW_EXPIRY this is REQUIRED and MUST equal the declared_by_actor_id of the '
    'exact ReviewQueuePolicy(policy_id, policy_version, project_id) this event cites. It is the '
    'standing authority the expiry executed, never the service account that executed it.';

-- ---------------------------------------------------------------------------------------------
-- 3. The executor must be an active actor, judged when the expiry is written
-- ---------------------------------------------------------------------------------------------
--
-- `actor_id` is already `NOT NULL REFERENCES actors`, so an executor the database never heard of
-- fails closed. An actor row that exists and is switched off did not, and "switched off" is how a
-- decommissioned scheduler, a departed reviewer's automation and a revoked integration are all
-- represented -- SEC-002 already treats an inactive actor as BLOCKed everywhere else.
--
-- NO `event_type` GUARD IN THE BODY. The CHECK on that column admits one value, so a branch
-- returning early for other kinds is a branch nothing can reach. When a second kind is admitted it
-- must decide its own executor rule, and the amendment that adds it is where that decision belongs.

CREATE OR REPLACE FUNCTION governance_events_executor_is_active()
RETURNS TRIGGER AS $$
DECLARE
    v_active BOOLEAN;
BEGIN
    -- Always found and never NULL: `actor_id` is a NOT NULL foreign key and `actors.active` is
    -- NOT NULL DEFAULT TRUE, so this is a two-valued test rather than a three-valued one.
    SELECT active INTO v_active FROM actors WHERE actor_id = NEW.actor_id;

    IF NOT v_active THEN
        RAISE EXCEPTION
            'governance event %: actor % is not active, so it cannot execute an automatic expiry. '
            'A deactivated service account or a departed reviewer''s automation would otherwise '
            'keep lifting blocks with nobody accountable, and the review stays outstanding instead '
            '-- which is the fail-closed direction',
            NEW.event_id, NEW.actor_id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS governance_events_executor_is_active ON governance_events;
CREATE TRIGGER governance_events_executor_is_active
    BEFORE INSERT ON governance_events
    FOR EACH ROW EXECUTE FUNCTION governance_events_executor_is_active();

-- ---------------------------------------------------------------------------------------------
-- 4. The commit-boundary invariant learns what chain a GovernanceEvent belongs to
-- ---------------------------------------------------------------------------------------------
--
-- Replaces `011f`'s body. Every check `011f` made is preserved verbatim; one block is added, in the
-- terminal branch, for the case `resolution_event_kind = 'GOVERNANCE'`.
--
-- IT RE-READS EVERY ROW, STILL. Nothing here trusts a trigger's NEW -- see `011d`'s note. The
-- identity arrives from the trigger; every value, including the event now, is read back at commit.

CREATE OR REPLACE FUNCTION review_conflict_invariant_assert(
    p_project_id TEXT,
    p_review_id  TEXT
) RETURNS VOID AS $$
DECLARE
    v_review         review_items;
    v_resolution     review_resolutions;
    v_conflict       conflicts;
    v_outstanding    BOOLEAN;
    v_conflict_event TEXT;
    v_event          governance_events;
    v_declared_by    TEXT;
BEGIN
    SELECT * INTO v_review
      FROM review_items
     WHERE review_id = p_review_id AND project_id = p_project_id;

    IF NOT FOUND THEN
        RETURN;
    END IF;

    v_outstanding := v_review.status IN ('QUEUED', 'ASSIGNED');

    IF v_outstanding THEN
        IF v_review.decision_ref IS NOT NULL THEN
            RAISE EXCEPTION
                'review % is % but carries decision_ref %. An outstanding review must not look '
                'answered -- a reader checking decision_ref would conclude a human had decided',
                v_review.review_id, v_review.status, v_review.decision_ref;
        END IF;
    ELSE
        IF v_review.decision_ref IS NULL THEN
            RAISE EXCEPTION
                'review % is % with no decision_ref. §17.19.1 as amended by v3.3-a14 requires a '
                'terminal review to record how it was resolved; without it the review is a human '
                'decision with no record of what was decided',
                v_review.review_id, v_review.status;
        END IF;

        SELECT * INTO v_resolution
          FROM review_resolutions
         WHERE resolution_id = v_review.decision_ref;

        IF NOT FOUND THEN
            RAISE EXCEPTION
                'review % is % and names resolution %, which does not exist. A terminal review '
                'whose decision_ref resolves to nothing is unauditable',
                v_review.review_id, v_review.status, v_review.decision_ref;
        END IF;

        IF v_resolution.review_id IS DISTINCT FROM v_review.review_id THEN
            RAISE EXCEPTION
                'review % names resolution %, which resolved review % instead. A terminal review '
                'must cite the record of its own resolution; borrowing another review''s makes one '
                'human decision stand in for a second that never happened',
                v_review.review_id, v_resolution.resolution_id, v_resolution.review_id;
        END IF;

        IF v_resolution.project_id IS DISTINCT FROM v_review.project_id THEN
            RAISE EXCEPTION
                'review % in % names resolution % in %. A decision recorded in one project cannot '
                'resolve another project''s review (SEC-002)',
                v_review.review_id, v_review.project_id,
                v_resolution.resolution_id, v_resolution.project_id;
        END IF;

        IF v_resolution.outcome IS DISTINCT FROM v_review.status THEN
            RAISE EXCEPTION
                'review % is % but its resolution % records outcome %. These are two accounts of '
                'the same decision and must agree; whichever a reader consulted first would settle '
                'the belief',
                v_review.review_id, v_review.status,
                v_resolution.resolution_id, v_resolution.outcome;
        END IF;

        -- `v3.3-a15`: a GovernanceEvent closure is only ever the product of an expiry, and the
        -- CHECK on `review_resolutions` says so too. Repeated here because the CHECK guards one
        -- row and this guards the pair at commit.
        IF v_resolution.resolution_event_kind = 'GOVERNANCE'
           AND v_resolution.outcome <> 'EXPIRED' THEN
            RAISE EXCEPTION
                'resolution % closes review % as % against a GovernanceEvent. v3.3-a15 permits '
                'GOVERNANCE only for EXPIRED: APPROVED, CORRECTED and REJECTED are decisions '
                'somebody made, and a governance event records that nobody did',
                v_resolution.resolution_id, v_review.review_id, v_resolution.outcome;
        END IF;

        -- -----------------------------------------------------------------------------------
        -- `v3.3-a16`: the event must have been written for THIS chain
        -- -----------------------------------------------------------------------------------
        --
        -- Up to here the reference is checked for agreement -- the resolution and the conflict
        -- name the same (kind, id). That proves the two halves of the closure tell one story; it
        -- does not prove the story is this review's. Everything below loads the far end and asks.
        IF v_resolution.resolution_event_kind = 'GOVERNANCE' THEN
            -- THE PREDICATE CARRIES `event_type` AND `subject_type`. Both are CHECK-constrained to
            -- a single value, so no row can fail them today -- they are here so that admitting a
            -- second event type is a decision somebody has to make about *this* lookup, rather
            -- than a new kind quietly inheriting the right to close a review by expiry.
            --
            -- Looked up on `event_id` alone. Scoping by project would make the project comparison
            -- below vacuous -- a cross-project event would simply not be found, and the error
            -- would say "does not exist" about a row that does. Same arrangement, same reason, as
            -- `011d`'s resolution lookup.
            SELECT * INTO v_event
              FROM governance_events
             WHERE event_id     = v_resolution.governance_event_id
               AND event_type   = 'REVIEW_EXPIRY'
               AND subject_type = 'REVIEW_ITEM';

            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'resolution % closes review % against governance event %, which is not a '
                    'REVIEW_EXPIRY over a REVIEW_ITEM. v3.3-a15 permits exactly that combination '
                    'as expiry closure proof, and anything else is an event closing a block it '
                    'does not describe',
                    v_resolution.resolution_id, v_review.review_id,
                    v_resolution.governance_event_id;
            END IF;

            IF v_event.project_id IS DISTINCT FROM v_review.project_id THEN
                RAISE EXCEPTION
                    'governance event % is in % but closes review % in %. An expiry recorded in '
                    'one project cannot close another project''s review (SEC-002)',
                    v_event.event_id, v_event.project_id,
                    v_review.review_id, v_review.project_id;
            END IF;

            -- THE SUBSTITUTION THIS MIGRATION EXISTS FOR. A genuine REVIEW_EXPIRY event, in the
            -- right project, for a different review. Everything `011f` checks passes; this is the
            -- only place the borrowed authority becomes visible.
            IF v_event.subject_id IS DISTINCT FROM v_review.review_id THEN
                RAISE EXCEPTION
                    'governance event % was written for review %, but resolution % presents it as '
                    'proof that review % expired. An event that merely belongs to the same project '
                    'is not proof that THIS review lapsed -- that substitution is the authority '
                    'this check exists to refuse (§17.19.1, v3.3-a16)',
                    v_event.event_id, v_event.subject_id,
                    v_resolution.resolution_id, v_review.review_id;
            END IF;

            -- THE EXACT VERSION THE ITEM WAS PRICED BY. `review_expire` refuses a mismatch for
            -- callers who go through it; this is the same rule for a writer who did not. A policy
            -- the reviewer never saw is not the deadline they were given, and citing a laxer
            -- version retroactively is how an early expiry would be made to look legitimate.
            IF v_event.policy_id      IS DISTINCT FROM v_review.queue_policy_id
               OR v_event.policy_version IS DISTINCT FROM v_review.queue_policy_version THEN
                RAISE EXCEPTION
                    'governance event % cites policy %@% but review % was priced by %@%. v3.3-a15 '
                    'requires the version the item was priced by; an expiry re-interpreted under a '
                    'policy the reviewer never saw is not the deadline they were given',
                    v_event.event_id, v_event.policy_id, v_event.policy_version,
                    v_review.review_id, v_review.queue_policy_id, v_review.queue_policy_version;
            END IF;

            -- Unrepresentable today -- `governance_events_policy_in_project` is a composite
            -- foreign key. The lookup happens regardless, because the policy row is where the
            -- standing authority is read from, so the NOT FOUND arm costs nothing beyond saying
            -- what it would mean.
            SELECT declared_by_actor_id INTO v_declared_by
              FROM review_queue_policies
             WHERE policy_id  = v_event.policy_id
               AND version    = v_event.policy_version
               AND project_id = v_event.project_id;

            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'governance event % cites queue policy %@% in %, which does not exist. An '
                    'expiry executed under a policy nobody can produce is an expiry nobody '
                    'authorised',
                    v_event.event_id, v_event.policy_id, v_event.policy_version,
                    v_event.project_id;
            END IF;

            -- TWO ACTORS, AND EACH MUST BE THE RIGHT ONE. `declared_by_actor_id` is carried from
            -- the policy and never from the executor (§17.19.1). Letting the event name a
            -- different author would make the sweep look authorised by somebody who declared
            -- nothing -- which is precisely the inference the amendment forbids, arrived at by
            -- writing it down instead of deriving it.
            IF v_event.declared_by_actor_id IS DISTINCT FROM v_declared_by THEN
                RAISE EXCEPTION
                    'governance event % says policy %@% was declared by %, but that policy records '
                    '%. The standing authority for an automatic expiry is the actor who declared '
                    'the policy, and it MUST NOT be restated by whoever wrote the event',
                    v_event.event_id, v_event.policy_id, v_event.policy_version,
                    v_event.declared_by_actor_id, v_declared_by;
            END IF;

            IF v_event.actor_id IS DISTINCT FROM v_resolution.resolved_by_actor_id THEN
                RAISE EXCEPTION
                    'governance event % was executed by % but resolution % records % as having '
                    'resolved review %. These are two accounts of who ran this expiry and must '
                    'agree; whichever a reader consulted first would name the accountable party',
                    v_event.event_id, v_event.actor_id, v_resolution.resolution_id,
                    v_resolution.resolved_by_actor_id, v_review.review_id;
            END IF;

            -- THE CONFLICT, FROM THE EVENT'S SIDE. The loop below asks the same question from the
            -- review's side, and both are needed: this one catches an event naming a conflict this
            -- review does not gate, and the loop catches a gated conflict the event does not name.
            IF v_event.related_conflict_id IS NOT NULL THEN
                PERFORM 1
                   FROM conflicts
                  WHERE conflict_id = v_event.related_conflict_id
                    AND review_id   = v_review.review_id
                    AND project_id  = v_review.project_id;

                IF NOT FOUND THEN
                    RAISE EXCEPTION
                        'governance event % says it closed conflict %, which review % does not '
                        'gate. An expiry closes the block its own review was raised for; naming '
                        'another review''s conflict claims an authority this deadline never '
                        'carried',
                        v_event.event_id, v_event.related_conflict_id, v_review.review_id;
                END IF;
            END IF;
        END IF;
    END IF;

    FOR v_conflict IN
        SELECT * FROM conflicts WHERE review_id = v_review.review_id
    LOOP
        IF v_conflict.project_id IS DISTINCT FROM v_review.project_id THEN
            RAISE EXCEPTION
                'conflict % in % is gated by review % in %. A review cannot gate another project''s '
                'conflict (SEC-002)',
                v_conflict.conflict_id, v_conflict.project_id,
                v_review.review_id, v_review.project_id;
        END IF;

        IF v_outstanding THEN
            IF v_conflict.resolution_status NOT IN ('OPEN', 'UNDER_REVIEW') THEN
                RAISE EXCEPTION
                    'conflict % is % while review % is still %. §17.19.1 as amended by v3.3-a14 '
                    'forbids an outstanding review beside a closed conflict -- ASSIGNED included, '
                    'since somebody having picked the task up is not somebody having answered. The '
                    'belief would be unblocked by a human decision nobody made',
                    v_conflict.conflict_id, v_conflict.resolution_status,
                    v_review.review_id, v_review.status;
            END IF;
        ELSE
            IF v_conflict.resolution_status IN ('OPEN', 'UNDER_REVIEW') THEN
                RAISE EXCEPTION
                    'review % is % but conflict % is still %. v3.3-a14 forbids a terminal review '
                    'beside an unresolved conflict: the human has decided and the block is still '
                    'in place, which no later reader can distinguish from nobody having looked',
                    v_review.review_id, v_review.status,
                    v_conflict.conflict_id, v_conflict.resolution_status;
            END IF;

            -- THE PAIR, BOTH HALVES (`v3.3-a15`). Agreeing on the id is no longer sufficient:
            -- the kind is part of what the closure claims happened.
            IF v_conflict.resolution_event_kind IS DISTINCT FROM v_resolution.resolution_event_kind
            THEN
                RAISE EXCEPTION
                    'conflict % closed against a % event but review %''s resolution % recorded a % '
                    'event. The Conflict and the ReviewResolution must reference the same '
                    '(kind, id) pair',
                    v_conflict.conflict_id, v_conflict.resolution_event_kind,
                    v_review.review_id, v_resolution.resolution_id,
                    v_resolution.resolution_event_kind;
            END IF;

            v_conflict_event := COALESCE(
                v_conflict.resolution_event_id, v_conflict.governance_event_id);

            IF v_conflict_event IS DISTINCT FROM v_resolution.resolution_event_id THEN
                RAISE EXCEPTION
                    'conflict % closed as % against event %, but review %''s resolution % produced '
                    'event %. An event that merely belongs to the same project is not proof that '
                    'this review resolved',
                    v_conflict.conflict_id, v_conflict.resolution_status, v_conflict_event,
                    v_review.review_id, v_resolution.resolution_id,
                    v_resolution.resolution_event_id;
            END IF;

            -- THE CONFLICT, FROM THE REVIEW'S SIDE (`v3.3-a16`). The event must say it closed the
            -- conflict that is in fact closing against it. A NULL here is the readable case and is
            -- not benign: the event claims it closed nothing while a conflict cites it as the
            -- reason its block lifted.
            IF v_resolution.resolution_event_kind = 'GOVERNANCE'
               AND v_event.related_conflict_id IS DISTINCT FROM v_conflict.conflict_id THEN
                RAISE EXCEPTION
                    'conflict % closed against governance event %, but that event says it closed '
                    '%. The expiry record and the block it lifted must name each other; otherwise '
                    'the conflict was unblocked by an event that never claimed to have done it',
                    v_conflict.conflict_id, v_event.event_id,
                    COALESCE(v_event.related_conflict_id, 'no conflict at all');
            END IF;
        END IF;
    END LOOP;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION review_conflict_invariant_assert(TEXT, TEXT) IS
    'v3.3-a14/a15/a16: the complete ReviewItem <-> Conflict cross-table invariant, evaluated '
    'against committed values. Called from deferred constraint triggers on all three tables, so no '
    'writer can reach a forbidden half-state by declining to call review_resolve_and_close_conflict '
    'or review_expire. A GOVERNANCE closure additionally proves the referenced GovernanceEvent was '
    'written for this exact review, conflict, queue-policy version and pair of actors.';
