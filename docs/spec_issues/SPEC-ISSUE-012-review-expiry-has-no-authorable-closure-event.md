# SPEC-ISSUE-012: an automatically expired ReviewItem has no closure event anyone may author

Severity: GATE
Status: OPEN
Blocks gate: M0b
Raised: 2026-09-19
Raised by: M0b sign-off audit (P1-A, OPS-002 expiry liveness)
Affected: §14.4, §14.4.1, §17.19.1 (`v3.3-a14`), §17.19.3, §17.13, §8.2, §25.3 `OPS-002`,
          §26 `T-OPS-002`, AGT-016

## The obligation

§26's T-OPS-002 requires liveness:

> an item past its expiry leaves PENDING via the declared policy rather than parking there
> indefinitely (§14.4).

§14.4 says the same from the other side — the queue has an SLA/expiry policy precisely to avoid
"所有 uncertain item 永久卡在 PENDING".

M0b ships the seam (`ReviewQueue.expire`) and the deadlines (`011e`), and every expiry test calls
the seam by hand. **No production caller invokes it**, so the obligation is not discharged. Adding
that caller is a four-line change. What blocks it is the next paragraph.

## The gap: what event does a timeout produce?

§17.19.1 as amended by `v3.3-a14` makes the chain rigid, and every link is already locked:

```
review leaves PENDING  ->  terminal ReviewItem                     (§17.19.1: QUEUED|ASSIGNED
                                                                    are the only non-terminal
                                                                    statuses; EXPIRED is terminal)
terminal ReviewItem    ->  MUST carry decision_ref                 (v3.3-a14)
decision_ref           ->  durable ReviewResolution                (v3.3-a14, migration 011c)
ReviewResolution       ->  belief_revision_event_id  NOT NULL      (011c, LOCKED)
linked Conflict        ->  MUST be terminal, against THAT event    (v3.3-a14, 011d)
Conflict.resolution_event_id -> FK belief_revision_events          (011a, LOCKED)
```

So an automatic expiry must author a **`BeliefRevisionEvent`**. §17.13 gives that object exactly
one subject kind — a hypothesis's belief state — and §8.2 gives it one meaning:

> Every accepted transition emits BeliefRevisionEvent.

**An unanswered timeout is not a transition.** The hypothesis is exactly where it was; what changed
is that a block lifted because nobody answered in time. §17.19.3 says only

> Closing a Conflict is a state change and MUST record `resolution_event_id`.

and never says what *kind* of event that is. `011a` bound it to `belief_revision_events`, and `011a`
is locked.

### Every available construction, probed against the real schema

| # | Construction | Result |
|---|---|---|
| A | Second genesis event for the same hypothesis (`from_state` NULL) | **accepted by the database**, refused by `admit_hypothesis`; semantically it re-admits a hypothesis that was admitted once |
| B | Non-genesis `ACTIVE -> ACTIVE` citing the admission policy | refused — `005c`: an admission policy may not back a transition |
| C | A no-op `TransitionPolicy(ACTIVE -> ACTIVE)` to cite | **unrepresentable** — `005b` `CHECK (from_state <> candidate_to_state)` |
| D | Genesis event for a **fabricated** hypothesis id | accepted, and this is what the M0b test fixture does (see "What the current tests actually prove") |
| E | Point `resolution_event_id` at some non-belief event | no such object exists in the spec, and both FKs are locked to `belief_revision_events` |

C is the decisive one: **the schema makes "nothing changed" unsayable.** Every legal non-genesis
event is a real belief-state change, and every one of those needs an ALLOW from
`TransitionPolicy.evaluate` re-derivable from its own snapshot (`v3.3-a12`).

### And a real transition is circular

Suppose the expiry is modelled as `ACTIVE -> INCONCLUSIVE` ("nobody could adjudicate in time").
Probed:

```
policy that HONOURS the blocking conflict -> NEED_HUMAN_REVIEW (BLOCKING_CONFLICT)
    no ALLOW -> no event -> the conflict can never close.            CIRCULAR

policy that IGNORES the blocking conflict -> ALLOW (POLICY_SATISFIED)
    required_relation_types: (none)
    a scheduler has just decided a hypothesis is INCONCLUSIVE on no evidence.
```

The only policy that can produce the event is one that ignores the very conflict it is closing, and
running it is a background job authoring a scientific verdict. AGT-016 forbids LLM output alone
causing a status transition; it does not name schedulers, because the specification never
contemplated one writing belief.

## Why this is escalated rather than decided

The five readings below produce **different scientific outcomes for the same hypothesis**. That is
not an implementation detail an agent may settle (AGT-015).

**Reading A — expiry closes the conflict as `ACCEPTED_AS_OPEN_QUESTION`, event authored by the
SLA policy's approving actor.**
The lab supervisor who declared "HIGH stakes lapse after 48h" is the human whose standing decision
the sweep executes, so `resolved_by_actor_id` is answerable from §14.4's actor model. Still needs an
event, and construction C says there is none to author. Requires either a new event kind or
relaxing `011c`'s NOT NULL.

**Reading B — `resolution_event_id` need not be a `BeliefRevisionEvent`.**
The most natural reading of §17.19.3's own words, which say "event" and nothing more. Needs a
governance/audit event object the spec does not define, and a forward migration relaxing two locked
FKs. Arguably the cleanest long-term answer: "a block lifted" and "a belief moved" are different
facts and currently share one table.

**Reading C — expiry is a real belief transition (`ACTIVE -> INCONCLUSIVE`).**
Expressible in §8.2's lifecycle and needs no schema change — but it makes a timeout a scientific
conclusion, reached with no evidence and no human, and it is circular unless the authorising policy
ignores the blocking conflict.

**Reading D — an expired review does not close its conflict; the conflict stays open and the
review stays outstanding, with the breach reported.**
Preserves `v3.3-a14` untouched and needs no event at all. But EPI-004 reviews *always* gate a
conflict, so T-OPS-002's liveness clause becomes vacuous for every review M0b creates — which is
the state §14.4 exists to forbid.

**Reading E — expiry requires a human to countersign; the sweep only surfaces the item.**
Honest about authority and consistent with §14.4's actor_id rule, but "requires a human" is what
the SLA existed to bound. It converts liveness into a louder queue rather than a guarantee.

## Proposed wording (Reading B, if the maintainer agrees)

Add to §17.19.3:

```
resolution_event_id references the event that closed the Conflict. Where the closure
was produced by a ReviewItem resolution that moved a belief, this is the
BeliefRevisionEvent that resolution produced (17.19.1, v3.3-a14).

Where a Conflict closes WITHOUT a belief transition -- an SLA expiry under 14.4, or a
withdrawal of the evidence the conflict rested on -- it MUST instead reference a
GovernanceEvent recording the actor, the declared policy that authorised the closure,
and the reason. A Conflict MUST NOT close with no event of either kind.

A scheduler or maintenance process MUST NOT author a BeliefRevisionEvent. Automatic
closure is a governance act, not a scientific one.
```

and a `GovernanceEvent` contract in §17.19.2 beside `BenchmarkPolicy`. Requirement ↔ Test would
stay 59 ↔ 59 if the obligation is read into the existing `OPS-002` / `T-OPS-002` pair; a new
`OPS-00x` would move it to 60 ↔ 60 and is the maintainer's call.

## What the current tests actually prove, stated plainly

`tests/integration/test_review_queue_postgres.py` passes, and its closure-event helper writes

```python
"SELECT belief_revision_event_append(%s, %s, 'HYPOTHESIS', %s, NULL, 'ACTIVE', ...)",
(event_id, PROJECT, f"hyp:{event_id}", ...)
```

— a genesis event for a **hypothesis that does not exist**, invented to satisfy the foreign key.
That is construction D. The tests therefore prove the *seam* is correct (it routes through the
locked `011c` path, refuses a not-yet-expired item, refuses an already-resolved one, and leaves no
`011d` half-state) and prove **nothing** about which event a real expiry may cite. The helper is
renamed and documented in place rather than quietly left, so the next reader sees the placeholder.

## Effect on M0b

**OPS-002 is NOT_READY** until this is resolved. Depth, capacity, `earliest_available_at`, stakes
and the SLA/expiry policy at creation are all discharged; the liveness clause is not. No production
expiry caller was added, because adding one means choosing a reading above.

## Alternatives considered and rejected

- **Let the sweep author the event under a service-account actor.** §14.4 admits service-account
  actors, so the *actor* is answerable — but the actor was never the hard half. The event is, and
  a service account authoring `ACTIVE -> INCONCLUSIVE` is still a machine deciding a hypothesis.
- **Fabricate a hypothesis to hang the event on**, as the fixture does. Puts a hypothesis in the
  belief log that no one proposed, and every later replay would have to explain it.
- **Relax `011c`'s `belief_revision_event_id` to nullable.** Reintroduces exactly the hole `011c`
  closed: a per-status exemption is how the terminal-state hole appeared in the P10 audit, and the
  locked ruling is that every status which stops a conflict blocking carries its closure event.
