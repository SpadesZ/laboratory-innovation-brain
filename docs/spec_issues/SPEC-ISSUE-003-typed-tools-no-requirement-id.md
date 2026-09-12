# SPEC-ISSUE-003: §10.2 typed-tools-only has no dedicated Requirement ID

Severity: GATE
Status: RESOLVED
Blocks gate: M0a
Raised: 2026-09-12
Raised by: implementation agent, P1 review
Affected: P19, §10.2, VER-002 / T-VER-002, §23.5

> The four fields above are machine-read by `scripts/check_requirement_coverage.py`. Now
> `RESOLVED`, so it no longer blocks `M0a`.

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

## Resolution

**Maintainer ruled Option 1 on 2026-09-12 (P2-fix).** `SIM-003` and `T-SIM-003` added:

> SIM-003 — Tool invocation MUST occur through a typed ToolRegistry. No tool, Capability or
> backend adapter may expose an arbitrary script-execution entry point (`eval_script`-class
> public interface). Untyped execution paths MUST be rejected by static conformance test.

The requirement/test invariant moves from **52 ↔ 52 to 53 ↔ 53**, recorded in the spec Version
Notes as amendment `v3.3-a1`. `SIM-003` is allocated to **M2**, alongside the ToolRegistry it
constrains.

The registry entry `tools.typed_only.no_arbitrary_script` now maps to `SIM-003` / `T-SIM-003`
and no longer cites this issue.

A static guard is already in place from P2-fix --
`tests/unit/test_no_arbitrary_script_execution.py` rejects `eval_script`-class callables, script
text parameters, and `eval`/`exec`/`compile` calls across `src/lab_brain`, with a non-vacuity
probe proving each pattern matches. It is unmarked because `T-SIM-003` additionally requires
"every invocation resolves through the typed ToolRegistry", which needs the registry to exist;
marking it now would discharge half a pass condition. The guard nonetheless runs from today, so
the forbidden shape cannot be introduced and later have to be removed.

## Superseded interim implementation

Until the ruling, the registry entry kept its `VER-002` mapping so `T-SPEC-002` stayed internally
consistent, and carried `spec_issue: SPEC-ISSUE-003` so the weakness was visible in data rather
than only in an audit document. Both are now removed: the mapping points at `SIM-003`.

## Resolution checklist

- [x] Spec maintainer picked Option 1 (2026-09-12)
- [x] §25.3, §26 and the invariant count updated (52 ↔ 52 -> 53 ↔ 53)
- [x] `docs/milestones.yaml` allocates `SIM-003` to M2
- [x] `docs/normative_statements.yaml` remaps `tools.typed_only.no_arbitrary_script` to SIM-003
- [x] `spec_issue` reference removed from that entry
- [x] Static guard landed (`tests/unit/test_no_arbitrary_script_execution.py`)
- [ ] **M2**: marked `T-SIM-003` asserting the ToolRegistry half as well
