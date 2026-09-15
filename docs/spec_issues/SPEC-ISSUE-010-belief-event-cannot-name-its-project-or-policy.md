# SPEC-ISSUE-010: a BeliefRevisionEvent cannot name its project or the policy that authorised it

Severity: GATE
Status: RESOLVED
Blocks gate: M0b
Raised: 2026-09-15
Raised by: P7 / M0b-4 implementation (EPI-003, EPI-005)
Affected: §17.13, §8.2.1, §25.3 `EPI-003` / `EPI-005`, §26 `T-EPI-003` / `T-EPI-005`

## The two gaps

§17.13 declares:

```
BeliefRevisionEvent {
  event_id, target_type, target_id,
  from_state?, to_state,
  triggering_attestation_ids[], triggering_relation_ids[],
  policy_version, actor_id?, inference_provenance_id?,
  rationale_artifact_or_record_ref?, occurred_at, trace_id
}
```

**1. No `project_id`.** EPI-003 requires EpistemicState to be rebuildable by replaying these
events, and SEC-002 scopes every read to a project. With no project on the event there is no
expressible notion of a belief history belonging to a project, so:

- a replay cannot be scoped — rebuilding one project's belief state means replaying every event in
  the installation and hoping the target ids do not collide;
- "this event cites an attestation from another project" is not a statement the schema can make,
  let alone refuse. That is the same shape as risk R-7: the check is not missing, the *question*
  cannot be asked.

**2. No `policy_id`.** §8.2.1's `TransitionDecision` carries **both** `policy_id` and
`policy_version`, and `TransitionPolicy` is keyed on `policy_id, version`. The event records only
`policy_version`. So an event says it was authorised at version `1.2.0` without saying by which
policy, and two policies both at `1.2.0` — which is the normal case, since versions are per-policy
— are indistinguishable in the record.

This directly undermines the determinism obligation EPI-005 states:

> identical inputs + identical `policy_version` MUST return identical `TransitionDecision`

That sentence is only meaningful *per policy*. An auditor re-deriving a past revision has the
inputs and the version, and no way to select the policy to re-run. The event is therefore not
replayable in the sense EPI-003 requires, which is the requirement's whole point.

## Why this is not editorial

Both are fields, not wording. An implementation has three options and two are worse:

1. **Add the fields to the canonical block** (chosen). The event can be scoped and re-derived.
2. **Add them to the model and the table without amending §17.13.** This is precisely the drift
   ADR-0010 was written about and `tests/spec/test_schema_drift.py` exists to catch: an
   implementation growing fields the spec never declared. It was refused for `ExecutionSpan` in P6
   for the same reason and recorded as a gap instead.
3. **Leave them out.** Then EPI-003's replay is installation-wide and EPI-005's determinism claim
   has no anchor. Both requirements would be reported as satisfied by tests that never exercised
   the property.

Under AGT-015 an agent may not pick. Escalated.

## Resolution

**Maintainer ruled on 2026-09-15 (amendment `v3.3-a11`).** §17.13's `BeliefRevisionEvent` gains:

- `project_id` — required. A belief revision belongs to exactly one project, and every reference it
  carries must resolve inside that project.
- `policy_id` — required, beside the existing `policy_version`. Together they identify the exact
  `TransitionPolicy` row (§8.2.1 keys it on `policy_id, version`), so a past decision can be
  re-run rather than assumed.

**No Requirement or Test ID is added, and no normative statement is added.** EPI-003 already
obliged the event stream to be replayable and EPI-005 already obliged the decision to be
reproducible under a stated policy version; this makes both *representable*. `§17.13` is outside
the §6–§16 audit range, so the §23.5 (2) occurrence inventory is unchanged. Requirement ↔ Test
stays **59 ↔ 59**.

## Considered and deliberately not added

- **`reason_code`.** `TransitionDecision` computes one, and an event that dropped it would lose the
  machine-readable "why". Left out because it is *derivable*: given `policy_id`, `policy_version`
  and the same inputs, re-running `evaluate` reproduces the reason code, so storing it would be a
  second copy of a derived fact — the shape of defect §17.17's `cost_kind` note warns about, in
  reverse. The human-readable why already has a home in
  `rationale_artifact_or_record_ref?`. Revisit if a reason code ever stops being derivable.
- **A `Conflict` reference.** `TransitionDecision.blocking_conflict_ids[]` exists, but a blocking
  conflict *prevents* an event, so a recorded event has none by construction. `EPI-006` owns
  `Conflict`; adding a field here would anticipate it.

## Note recorded, not amended

§8.2.1's prose says an LLM may not turn `ACTIVE` into "SUPPORTED/REJECTED", but §8.2's lifecycle
diagram — the normative one — has no `REJECTED` state; its negative terminal is `CONTRADICTED`.
Read as shorthand, not as a ninth state. The implementation uses §8.2's vocabulary exactly. Flagged
here so the next reader does not have to re-derive that conclusion.

## Resolution checklist

- [x] Maintainer picks an option
- [x] §17.13 gains `project_id` and `policy_id`
- [x] Version Notes gain the `v3.3-a11` row
- [x] Implementation landed in P7 Phase A — `9b0724fd9df777d5e0a66c9365b7e5bbe8c16cad`
- [x] This issue closed

Resolved: 2026-09-15 (same day it was raised; the ruling came back within the slice).

The implementation box was left open at the Phase A commit and is ticked now against that SHA.
`project_id` and `policy_id` reached §17.13, the Pydantic `BeliefRevisionEvent`, and
`belief_revision_events` in migration `005a`; the schema-drift guard binds all three, and
`tests/spec/test_schema_drift.py::test_the_a11_belief_event_fields_reached_the_spec_the_model_and_the_table`
pins both fields by name so a tidy-up cannot remove them from the canonical block instead.

What the two fields then made possible, which is the test of whether the amendment was worth
making: `project_id` is what `SqlBeliefEventStore.history(project_id, target_id)` scopes on and what
migration `005c` uses to make a cross-project trigger reference structurally unrepresentable;
`policy_id` is what `005b`'s foreign key and `005c`'s governance trigger resolve against.

**A gap this amendment did not close** is recorded separately as
[SPEC-ISSUE-011](SPEC-ISSUE-011-belief-event-carries-no-durable-authorization-proof.md): the event
now names the policy that *would have* authorised it, and still carries no durable proof that a
policy decision actually did.
