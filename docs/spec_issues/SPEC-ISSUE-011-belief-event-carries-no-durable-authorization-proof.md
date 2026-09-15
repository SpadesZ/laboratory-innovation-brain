# SPEC-ISSUE-011: a stored BeliefRevisionEvent carries no durable proof that a policy authorised it

Severity: GATE
Status: OPEN
Blocks gate: M0b
Raised: 2026-09-15
Raised by: P7 audit (EPI-003, EPI-005)
Affected: §17.13, §17.14 `Decision`, §8.2.1, §25.3 `EPI-005`, §26 `T-EPI-005`, AGT-016

## The gap

EPI-005 and AGT-016 state the same rule twice:

> Hypothesis state transition MUST be authorized by versioned TransitionPolicy and emitted as
> BeliefRevisionEvent; LLM cannot directly mutate status.

> Agent MUST use TransitionPolicy/AuthorityPolicy operators; LLM output alone cannot cause
> scientific status transition.

`TransitionPolicy.evaluate` returns a `TransitionDecision` (§8.2.1) and `record_transition` refuses
to build an event unless that decision is an ALLOW for exactly this policy, version and transition.
But **a stored event is indistinguishable from one that was never evaluated at all.**

§17.13's event records `policy_id` and `policy_version` — which policy *would have* authorised it —
and nothing about the decision. §8.2.1's `TransitionDecision` is a return value with no identity:
no `decision_id`, and nothing persists it. So:

```
construct BeliefRevisionEvent(...)          # any caller, no evaluate() call
store.append(event)                          # policy exists, refs resolve, states are consistent
-> indistinguishable from an authorised revision, forever
```

Migration `005c` closes what is closable without new semantics: an event's recorded
`(from_state, to_state)` must be exactly the pair its cited policy governs, admission policies back
only genesis events, and transition policies back only non-genesis ones. That removes the
*inconsistent* forgeries. It cannot remove the *consistent* one — an event that names a real policy
and records the transition that policy governs, for which no ALLOW was ever computed.

Python-side, `lab_brain.core.belief` now issues an in-process `AuthorizedRevision` capability that
only `record_transition` and `admit_hypothesis` can mint, and `SqlBeliefEventStore.append` accepts
nothing else. That closes the accidental and the review-visible bypass. It is **not** durable: the
capability lives in one process, so a support script, a migration or a future service writing SQL
is not bound by it, and nothing in the stored row records that it was ever held.

## Why this is escalated rather than decided

There is a candidate representation already in the specification, which is exactly why the choice
is not an agent's to make. §17.14 declares:

```
Decision {
  decision_id, episode_id, decision_type, subject_id,
  result, policy_refs[], triggering_event_ids[], actor_id?, created_at
}
```

A persisted `Decision` with `decision_type` naming a belief transition, `result` = ALLOW,
`policy_refs` = the policy version, and `triggering_event_ids` citing the event would be durable
proof, and the direction (`Decision -> event`) is enforceable with the same deferred-constraint
mechanism `005c` uses for orphan events.

But three things are unstated, and each is normative:

1. **Whether a `BeliefRevisionEvent` MUST be backed by a `Decision` row.** §17.13 declares no
   back-reference and §17.14 imposes no obligation. Asserting the requirement would be writing a
   normative statement.
2. **The `decision_type` and `result` vocabularies.** Neither is enumerated anywhere. Inventing
   `BELIEF_TRANSITION` / `ALLOW` would put an agent's vocabulary into the audit record of every
   belief revision in the system.
3. **Which Requirement ID owns §17.14's `Decision`.** No entry in `docs/normative_statements.yaml`
   registers it, so there is no test id to discharge it against — the same shape as the five
   unregistered hard MUSTs SPEC-ISSUE-004…008 raised.

AGT-015 applies directly: this is a normative contract that does not say what an implementation
must do, and the agent may not settle it by picking the reading it prefers.

## Options for the maintainer

1. **Persist §17.14's `Decision` and require a belief event to be backed by one.** Adds no new
   entity; needs `decision_type` / `result` vocabularies, a Requirement ID for §17.14, and a
   statement of the obligation. Deferred-constraint enforcement is already demonstrated in `005c`.
2. **Add a `decision_id?` back-reference to §17.13's `BeliefRevisionEvent`.** Makes the proof
   reachable from the event rather than only by scanning decisions, at the cost of another
   amendment to §17.13 (this would be its third, after `v3.3-a11`).
3. **Record the authorisation inside the event as a signed/derived token** — e.g. a canonical hash
   of the `TransitionDecision`, verifiable by re-running `evaluate`. Durable and self-contained, but
   it invents a field and a verification procedure the specification does not describe.
4. **Rule that the in-process capability is sufficient for M0b** and defer durable proof to M1,
   recording it as a named risk. Honest, and leaves the hole open in the record.

No option is implemented. The implementation ships the in-process capability and `005c`'s
consistency constraints, and states the residual as risk **R-13**.

## Why it does not block M0b today

`M0b` is `IN_PROGRESS`, and `scripts/check_requirement_coverage.py` refuses an OPEN GATE issue only
against a milestone marked DONE. `EPI-005` therefore stays `IN_PROGRESS` and M0b cannot be signed
off while this is open — which is the correct consequence, not a workaround.

## Resolution checklist

- [ ] Maintainer picks an option
- [ ] Spec updated accordingly (and a Requirement ID assigned to §17.14 if option 1)
- [ ] `docs/normative_statements.yaml` gains an entry for the obligation
- [ ] Durable enforcement added and proven by a negative test writing raw SQL
- [ ] This issue closed
