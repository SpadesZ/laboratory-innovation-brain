# SPEC-ISSUE-001: T-SPEC-002 "unique Requirement IDs" contradicts the §23.6 example

Severity: GATE
Status: OPEN
Blocks gate: M0a
Raised: 2026-09-12
Raised by: implementation agent, P1 review
Affected: TST-003 / T-SPEC-002, §23.6, §26

> The four fields above are machine-read by `scripts/check_requirement_coverage.py`. While
> `Status: OPEN` and `Severity: GATE`, milestone `M0a` cannot be marked DONE.

## The statement

§26, pass condition for `T-SPEC-002`:

> registry entries have unique Requirement IDs; every entry maps to at least one existing
> Test ID or carries an explicit DEFERRED rationale with review date; no entry references an
> unknown requirement or test.

## Why it is ambiguous

"Registry entries have unique Requirement IDs" admits two readings.

**Reading A — each Requirement ID appears in at most one registry entry.**
Under this reading, §23.6's own excerpt is invalid:

| Requirement | Entries in the §23.6 excerpt |
|---|---|
| `VER-006` | `prediction.typed.contract` (§17.5.1), `sufficiency.hypothetical.sideeffect_free` (§9.1) |
| `UX-001` | `ingestion.state.derived` (§17.22), `ingestion.duplicate.work_vs_bytes` (§17.22) |

A test implementing Reading A would fail on the specification's own example. It would also be
structurally wrong: §23.5 exists precisely so that *several* hard MUSTs in different sections
can map to one Requirement ID.

**Reading B — each entry names exactly one, unambiguously resolving Requirement ID, and
statement keys are unique.**
Consistent with the §23.6 excerpt and with §23.5's stated purpose.

## Why this is not resolved in code

Reading B is the architecturally coherent one. But AGT-015 exists to stop a Coding Agent
choosing between readings of the specification, and "the other reading is obviously wrong" is
exactly the reasoning AGT-015 distrusts. Choosing B and shipping a passing test would present
an agent's interpretation as a verified norm.

## Provisional implementation (must not be treated as a resolution)

Reading B, as `check_registry_keys_unique` + `check_registry_requirements_resolvable` in
`src/lab_brain/spec/conformance.py`.

## Proposed wording

Replace the clause in the §26 `T-SPEC-002` pass condition with:

> `statement_key` MUST be unique across the registry; each registry entry MUST reference
> exactly one valid Requirement ID. One Requirement ID MAY be referenced by multiple entries
> when it covers distinct normative statements in different sections.

## Resolution checklist

- [ ] Spec maintainer confirms Reading B or states Reading A with a corrected §23.6 excerpt
- [ ] §26 `T-SPEC-002` pass condition updated
- [ ] `conformance.py` docstrings updated to cite the settled wording instead of this issue
- [ ] This issue closed, and the `spec_issue` reference removed from any registry entry
