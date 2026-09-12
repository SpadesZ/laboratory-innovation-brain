# SPEC-ISSUE-003: §10.2 typed-tools-only has no dedicated Requirement ID

Severity: GATE
Status: OPEN
Blocks gate: M0a
Raised: 2026-09-12
Raised by: implementation agent, P1 review
Affected: P19, §10.2, VER-002 / T-VER-002, §23.5

> The four fields above are machine-read by `scripts/check_requirement_coverage.py`. While
> `Status: OPEN` and `Severity: GATE`, milestone `M0a` cannot be marked DONE.

## The unregistered MUST

P19 and §10.2 state a hard normative rule:

> **Typed Tools Only** — 不使用 arbitrary script execution / no arbitrary `eval_script`.

It appears in the Risk Register as a P0 defence ("Evaluator corruption: typed tools +
immutable evaluator + hidden validation gate") and in Appendix F's boot prompt. None of the 52
Requirement IDs targets it.

## Why the current mapping is inadequate

`tools.typed_only.no_arbitrary_script` is registered against `VER-002`, whose §26 pass
condition is:

> Planner 對無 capability descriptor 的 backend 不可規劃；有 descriptor 時依 produces/requires match.

These are different propositions, and neither implies the other:

- A backend can have a perfectly well-formed `Capability` descriptor and *still* expose an
  `eval_script(code: str)` entry point. `T-VER-002` passes; arbitrary execution remains.
- Conversely, tools can be strictly typed while the planner is entirely unconstrained.

So `T-VER-002` does not discharge the typed-tools MUST. The registry currently overstates its
coverage, and the M0a audit must not close this by default.

## Why it is recorded rather than fixed

Adding a 53rd Requirement ID would break the `52 ↔ 52` invariant that §26 and the change
summary both assert, and that `T-SPEC-001` enforces. Only the spec maintainer can change that
count. An agent minting `SIM-003` would be manufacturing a norm.

## Options for the maintainer

1. **Add a dedicated requirement** (e.g. `SIM-003` "tool invocation MUST occur through a typed
   registry; no arbitrary script execution path may exist") with a matching Test ID. Updates
   the invariant to 53 ↔ 53. Cleanest, and makes the P0 risk-register defence testable.
2. **Extend the `VER-002` pass condition** to explicitly include "no tool exposes an untyped
   script-execution entry point". Preserves 52 ↔ 52; makes one requirement carry two ideas.
3. **Declare it architectural**, discharged by `T-SYS-001` static analysis rather than by a
   behavioural test. Requires stating that in §23.6 with a DEFERRED rationale.

Option 1 is recommended: a P0 risk-register defence with no dedicated test is the pattern §0.3
warns about ("only a Requirement with no Test = will never be implemented").

## Interim implementation

The registry entry keeps its `VER-002` mapping so `T-SPEC-002` stays internally consistent, and
carries `spec_issue: SPEC-ISSUE-003` so the weakness is visible in data rather than only in an
audit document. A static guard against untyped execution paths will be implemented with the
tool registry in M2 regardless of how this issue resolves.

## Resolution checklist

- [ ] Spec maintainer picks option 1, 2 or 3
- [ ] If option 1: §25.3, §26 and the invariant count updated; `docs/milestones.yaml` allocates
      the new requirement
- [ ] `docs/normative_statements.yaml` remaps `tools.typed_only.no_arbitrary_script`
- [ ] `spec_issue` reference removed from that entry
