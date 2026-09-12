# M0 — Foundation (M0a + M0b)

M0 is split into two gates by §26.1 because they have different dependency profiles: M0a is
testable with no Actor, no LLM and no simulator; M0b is testable with no DomainPack. Keeping
them separate stops governance plumbing from being justified by schema work that has not
been proven yet.

## M0a — Scientific Identity Foundation

Exit gate: artifact/claim identity + bundle hash + schema/spec conformance pass.

| Phase | Scope | Requirements |
|---|---|---|
| P1 | Repo skeleton, spec CI, normative registry, milestone catalog, ADRs | TST-002, TST-003 |
| P2 | Core identity models + migrations 001–004, 008 | SYS-001, ART-001, EVI-005 |
| P3 | Canonical `EvidenceBundle` + hash; M0a audit | EVI-006 |

### Why this order

The spec CI comes first because it is what makes every later slice auditable. Building models
before the traceability harness exists means the 52↔52 invariant is checked by hand, which is
the failure mode §23.5 is written to prevent.

Identity models come before `EvidenceBundle` because a bundle hashes ordered attestation IDs —
there is nothing to hash until attestation identity is settled.

### What M0a deliberately does not contain

- No Actor/ACL enforcement. The `actor_id` columns exist in migration 001 so foreign keys are
  not retrofitted later, but nothing checks authorization until P4.
- No `BeliefRevisionEvent`. Hypothesis and belief state are M0b.
- No parsers. `EVI-002`'s abstention discipline is a parser behaviour, tested in M1.
- No LLM call path, so `EVI-006`'s "bundle before every scientific LLM call" is proven at the
  bundle-construction level in M0a and at the call-wrapper level in M1.

## M0b — Execution/Governance Foundation

Exit gate: event replay + transition/authority tests + ACL/budget/trace contracts pass.

| Phase | Scope | Requirements |
|---|---|---|
| P4 | Actor/ACL, Budget/CostLedger, ExecutionSpan trace; migrations 006, 007 | SEC-002, COST-001, OPS-003 |
| P5 | Belief events, TransitionPolicy, AuthorityPolicy, Prediction, Conflict, ReviewItem; migrations 005, 010, 011; M0b audit | EPI-003, EPI-004, EPI-005, EPI-006, VER-006, OPS-002 |

### The two signatures that must not drift

EPI-005 makes exactly one transition operator normative:

```
TransitionPolicy.evaluate(
    hypothesis, admitted_relations, authority_policy,
    condition_matches, independence_summary, candidate_to_state
) -> TransitionDecision
```

No `should_transition`, no other arity. `T-EPI-005` asserts the absence of alternatives in the
codebase, not merely the presence of this one.

VER-006 adds the hypothetical twin, which must persist nothing:

```
TransitionPolicy.evaluate_hypothetical(
    hypothesis, admitted_relations, hypothetical_relations,
    authority_policy, condition_matches, independence_summary, candidate_to_state
) -> TransitionDecision
```

`T-VER-006` proves purity by asserting no relation rows, no `BeliefRevisionEvent` and an
unchanged projection after a call — purity claimed in a docstring is not purity.

### Ordering constraint

P4 precedes P5 because `TransitionDecision.review_item_spec` and the auto-created
`ReviewItem(AUTHORITY_CONFLICT)` required by EPI-004 need `ReviewItem` and an actor model to
exist. Building P5 first would mean stubbing the review path and then rewriting it.
