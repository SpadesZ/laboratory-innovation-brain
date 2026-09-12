# ADR-0002: Belief state is event-sourced, never updated in place

Status: Accepted
Date: 2026-09-12
Affected Requirements: SYS-001, EPI-003, EPI-005
Human Approval Required: Yes — P0 scientific semantics (granted via SAI 3.3 §6.18, §17.13)

## Context

The obvious implementation of "this hypothesis is now supported" is `UPDATE hypothesis
SET status = 'SUPPORTED'`. That loses the only thing worth keeping: *why* the lab believes
it, and *what would have to change* for the belief to move back.

It also makes contamination unrecoverable. When an extractor version turns out to have a
systematic bug, an in-place store cannot answer "what would we believe if those
extractions had never happened?" without hand-editing rows — which is indistinguishable
from fabricating a belief history.

## Constraints

- P2 Append-only scientific record; P21 Event-sourced belief.
- §6.18: quarantine a bad extractor version, then **replay** events skipping the isolated
  attestations. Manual correction of current status is forbidden.
- AGT-009: all scientific state transitions go through `BeliefRevisionEvent`; static and
  contract tests must reject the direct repository update path.

## Options Considered

1. **Mutable status column + audit log** — cheapest. The audit log is decorative: nothing
   forces it to agree with the column, and replay cannot reconstruct state from it.
2. **Event-sourced, projection rebuilt on read** — correct, but recomputing from genesis
   on every read does not survive a real event volume.
3. **Event-sourced with checkpoint + delta projection** — append-only truth, bounded read
   cost.

## Decision

Option 3. `BeliefRevisionEvent` is the append-only truth. `EpistemicStateProjection` is
derived and disposable: it may be dropped and rebuilt at any time from full replay or from
checkpoint + delta.

A manual human correction is *also* an event, carrying `actor_id`. There is no code path
that writes `current_state` without appending an event first.

## Consequences

- Positive: contamination rollback is a replay, and its result is verifiable by re-running
  it. Nobody has to trust a hand-edit.
- Positive: "what did we believe on date D" is `as_of` replay, not archaeology.
- Negative: reading current state costs a projection lookup, and the projection can lag.
  Accepted: staleness is detectable via `last_event_id`, whereas a silently wrong status
  column is not.
- Negative: no `ORDER BY confidence DESC` over a mutable score. §8.1 rules out uncalibrated
  probabilities in v1 anyway, so nothing of value is lost.

## Migration / Rollback

Not rollback-able after the first real event is written without discarding belief history.
This is the load-bearing decision of the whole system; reversing it means a different
system.

## Tests / Evidence

- `T-EPI-003`: quarantine a triggering attestation, replay, assert the projection changed
  and history was preserved.
- `T-EPI-005`: direct LLM status assignment is rejected; only `evaluate` exists in the
  codebase (no `should_transition`).
- `T-SYS-001`: static test rejects writes to projection state from outside the projector.
