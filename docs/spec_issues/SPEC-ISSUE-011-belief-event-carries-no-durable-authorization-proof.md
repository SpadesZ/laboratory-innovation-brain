# SPEC-ISSUE-011: a stored BeliefRevisionEvent carries no durable proof that a policy authorised it

Severity: GATE
Status: RESOLVED
Blocks gate: M0b
Raised: 2026-09-15
Raised by: P7 audit (EPI-003, EPI-005)
Affected: §17.13, §17.14.1 `Decision`, §8.2.1, §25.3 `EPI-005`, §26 `T-EPI-005`, AGT-016
Resolved: 2026-09-16 (first marked resolved 2026-09-15; reopened the same day by the P8 audit
          because the obligation was discharged on the write path only -- see the history below)
Resolved by: `v3.3-a12` (maintainer ruling: Option 1 + Option 2, plus re-derivable input)

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


---

## Ruling and resolution (`v3.3-a12`, 2026-09-15)

**Section locator corrected first.** This issue originally cited §17.14, which is
`InferenceProvenance`. `Decision` is declared in the §17.14.1 contract block. The maintainer
caught it; every reference above and in the amendment now says §17.14.1.

**The ruling was Option 1 + Option 2, with a third requirement neither option contained:** the
authorization must carry inputs from which it can be *re-derived*. That addition is what closes
the gap rather than relocating it. Option 1 alone (require a `Decision` row) would have moved the
forgery up one level -- write the Decision too. Option 2 alone (fix the vocabulary) would have
made a forged row well-formed. Requiring the six inputs of §8.2.1's canonical operator, plus a
hash that binds them, means a Decision that survives checking has to contain inputs that genuinely
evaluate to ALLOW under the immutable policy. At that point it is not a forgery; it is an
authorization. §8.2.1's determinism guarantee is what turns recomputation into a check.

### What the amendment states

1. `Decision` is the durable belief-transition authorization. `decision_type` is fixed to
   `BELIEF_TRANSITION`; `result` uses `ALLOW / DENY / NEED_MORE_EVIDENCE / NEED_HUMAN_REVIEW`,
   the same vocabulary as `TransitionDecision.outcome`.
2. It MUST carry an immutable canonical `decision_input_snapshot` + `input_hash` sufficient to
   reconstruct all six operator inputs. An `AuthorityPolicy` is recorded by uniquely locatable
   identity and version, never by its comparison results -- storing the results would put the
   authority rules beyond falsification, which is what §10.5.1 refuses for INCOMPARABLE.
3. §17.13 gains `authorization_decision_id`, required for every non-genesis event, which MUST
   name a Decision with the same project/subject/policy/from→to and `result=ALLOW`.
4. Re-evaluating the snapshot under the named immutable policy MUST reproduce the stored decision
   under canonical serialization, and MUST fail closed otherwise.
5. The obligation belongs to the existing **EPI-005 / T-EPI-005**. A normative registry statement
   was added; **no Requirement or Test ID was created**, and the traceability count stays 59 ↔ 59.

Genesis is deliberately outside all of this: admission is §8's separate gate and does not borrow
transition authority. `target_id` still has no foreign key, which remains **R-12** and waits on
`EPI-001` in M3.

### How it is enforced

| Obligation | Where |
|---|---|
| Only a computed ALLOW can authorise | `authorize_transition` derives the verdict; there is no parameter to supply one |
| The stored snapshot must re-derive | `rederive_decision`, called by `record_transition` before anything is minted |
| Whole decision compared, not just the outcome | canonical serialization of `TransitionDecision` |
| Hash binds the inputs | model validator, and a Postgres `CHECK` that recomputes `sha256` over the stored bytes |
| Non-genesis event must cite an authorization | model validator + `CHECK ((from_state IS NULL) = (authorization_decision_id IS NULL))` |
| Authorization must be ALLOW, same project/subject/policy/from→to | `belief_revision_events_require_authorization` trigger |
| Cross-project authorization unrepresentable | composite FK on `(decision_id, project_id)` |
| Authorization cannot be edited afterwards | `belief_transition_decisions_are_append_only` trigger |

Migration `005d`. `005a`/`005b`/`005c` were applied and are untouched.

### What remains, and it is not this issue

Re-derivation needs the DomainPack comparator to be present when an `AuthorityPolicy` took part,
because core must not import a DomainPack (§24.2) and the spec forbids storing its results. That
is a deployment property, not a gap in the record: the comparator is named by identity and version,
so its absence is detectable and `rederive_decision` refuses rather than guessing. An
authorization computed with no comparator re-derives from the record alone.


---

## Reopened, then closed again (P8 audit, 2026-09-16)

The P8 audit returned **CONDITIONAL FAIL** with one P0, and it was correct. `v3.3-a12` was
implemented on the **write** path only.

**What was missing.** `record_transition` re-derived the authorization before minting an event, but
`replay` accepted a bare `BeliefRevisionEvent`. So a Decision could be *semantically* forged while
remaining perfectly well-formed — canonical six-input snapshot, correct `input_hash`, correct
project/subject/policy/from→to, `result` recorded as ALLOW — with a snapshot that, actually
evaluated, returns DENY or a NEED_* outcome. `005d` accepts that row, and **correctly so**:
deciding otherwise would require running `TransitionPolicy.evaluate` inside PostgreSQL, which
would mean a second copy of the evaluator and §8.2.1 ceasing to be the single source of semantic
truth. The limit is real; the conclusion drawn from it was wrong.

**This issue did not need another amendment.** §17.14.1 already said it:

> If it does not [re-derive], or if the inputs cannot be reconstructed, the authorization MUST be
> treated as absent — the event MUST NOT be created and a stored event MUST NOT be accepted as
> authorized.

"MUST NOT be created" is the write path. "MUST NOT be accepted as authorized" is the read path,
and only the first was built. The specification was not deficient, so no spec text changed in this
round.

**The fix: a production read-side verification seam.**

    stored event -> DecisionStore -> exact TransitionPolicyStore -> AuthorityPolicy resolver
    -> rederive_decision -> VerifiedBeliefRevision -> replay/projector

`replay` now takes `VerifiedBeliefRevision` and nothing else, so a DB-loaded event cannot reach a
scientific projection. The pure fold is unchanged and still directly testable; what changed is
that obtaining the capability requires passing the gate. Making the hole unrepresentable rather
than discouraged is the whole point — "the caller should verify" is the version of the rule that
P8 shipped.

Fail-closed, each with its own `VerificationFailure` reason so tests assert on state rather than
on prose: authorization missing; authorization not found; snapshot not hydratable; wrong decision
type; not an ALLOW; linkage mismatch (project, subject, policy id, policy version, from_state,
to_state — parametrized one at a time); policy version not registered; named comparator
unresolvable; not re-derivable. A named-but-unavailable comparator is a **refusal**, never a
fallback to `None`: re-deriving without the comparator that was used answers a different question
and the answer would read as a confirmation. Stored comparison results are never consulted,
because §17.14.1 forbids storing them (§10.5.1).

`verified_history` refuses a history containing one unverifiable revision rather than filtering it
out. A history minus a revision is a different history, and returning a projection built from the
rest would hide that something wrote a belief nobody authorised.

**The adversarial test the audit specified**, in
`tests/e2e/test_belief_authorization_verification_postgres.py`: forge the Decision by raw SQL,
assert the database accepts it *and that this is expected*, append the event through
`belief_revision_event_append`, reload through the real stores, run the real projector, and assert
`NOT_REDERIVABLE` with the projection unmoved. The "database accepts it" assertion is deliberate —
without it, a future schema change that started refusing the row would make the read-gate test
pass for a reason unrelated to the read gate.

**What the mutation run found.** The first pass over eight read-gate guards left five of them
green: the ALLOW check, the linkage check, the missing-authorization check, the genesis check and
the capability sentinel. All five are also enforced by `005d` or by the Pydantic model, which is
why no e2e case could reach them — and is exactly why they still need testing, since `model_copy`
skips validators in process and a support script writes SQL. A contract module now covers each
against in-memory stores; all eight mutations go red.
