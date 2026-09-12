# ADR-0007: Evidence authority is a domain-supplied partial order, not a fixed ladder

Status: Accepted
Date: 2026-09-12
Affected Requirements: EPI-004, SIM-002, EXT-001
Human Approval Required: Yes — P0 scientific semantics (granted via SAI 3.3 §10.5, §8.2.1)

## Context

Every system in this space eventually hardcodes `measurement > high-fidelity sim > coarse
sim > analytical`. It reads as obviously true and is frequently false: an uncalibrated
probe station measuring the wrong structure is weaker evidence than a converged simulation
of the right one.

Worse, a total order forces an answer where none exists. A coarse simulation under exactly
matched conditions versus a careful measurement under different conditions are not
comparable, and any hierarchy that ranks them has invented a scientific judgement.

## Constraints

- P15 Fidelity-aware authority; P27 Evidence authority, not simulator ladder.
- EPI-004: `AuthorityPolicy.compare` returns `STRONGER | WEAKER | EQUIVALENT | INCOMPARABLE`.
  `INCOMPARABLE` at a required gate MUST yield `NEED_HUMAN_REVIEW` plus an auto-created
  `ReviewItem(AUTHORITY_CONFLICT)`; no silent promotion or rejection.
- P17 / §24.1: core must not know that measurement outranks simulation, or that 1550 nm is
  a default. Those are DomainPack facts.
- SIM-002: a low-fidelity contradiction may only mark `CHALLENGED`, never `REJECTED`.

## Options Considered

1. **Core-level total order enum** — one line of code, and it embeds a physics claim in a
   domain-agnostic package. Fails EXT-001 the moment a second domain disagrees.
2. **Numeric authority score** — reintroduces a total order with extra steps, and makes
   `INCOMPARABLE` unrepresentable.
3. **DomainPack-registered `AuthorityPolicy` returning a four-valued comparison.**

## Decision

Option 3. Core defines the `AuthorityPolicy` interface and the four-valued result; the
DomainPack supplies the ordering. `INCOMPARABLE` is a first-class outcome, not an error.

When a required transition gate hits `INCOMPARABLE`, `TransitionPolicy.evaluate` returns
`NEED_HUMAN_REVIEW`, a `ReviewItem(AUTHORITY_CONFLICT)` and an `AUTHORITY_CONFLICT`
`Conflict` are created, and no `BeliefRevisionEvent` may promote or reject until the review
resolves.

## Consequences

- Positive: "we cannot tell which evidence is stronger" is a representable, routable state
  instead of a coin flip.
- Positive: adding a domain whose authority ordering differs requires no core change.
- Negative: `INCOMPARABLE` consumes human review capacity, which is finite (OPS-002). If it
  fires too often the DomainPack policy is underspecified — a signal worth having, though it
  will feel like friction early on.
- Negative: four-valued comparison cannot be used for a plain sort. Callers must handle the
  incomparable branch, and the type system makes them.

## Migration / Rollback

`AuthorityPolicy` implementations are versioned inside the DomainPack. Changing the ordering
is a policy version bump; past `BeliefRevisionEvent`s retain the version that authorised them.

## Tests / Evidence

- `T-EPI-004`: fixtures cover all four outcomes; required `INCOMPARABLE` blocks promotion and
  creates the review item.
- `T-SIM-002`: low-fidelity contradiction yields `CHALLENGED`, never `REJECTED`.
- `T-DOM-SP-001`: removing the Silicon Photonics plugin still leaves core bootable.
