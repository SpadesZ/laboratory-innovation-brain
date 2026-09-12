# SPEC-ISSUE-001: T-SPEC-002 "unique Requirement IDs" contradicts the §23.6 example

Severity: GATE
Status: RESOLVED
Blocks gate: M0a
Raised: 2026-09-12
Raised by: implementation agent, P1 review
Affected: TST-003 / T-SPEC-002, §23.6, §26

> The four fields above are machine-read by `scripts/check_requirement_coverage.py`. Now
> `RESOLVED`, so it no longer blocks `M0a`.

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

## Why this was escalated rather than decided in code

Reading B is the architecturally coherent one. But AGT-015 exists to stop a Coding Agent choosing
between readings of the specification, and "the other reading is obviously wrong" is exactly the
reasoning AGT-015 distrusts. Shipping B with a passing test would have presented an agent's
interpretation as a verified norm. The implementation used Reading B provisionally while this
issue stayed open; the maintainer ruling below is what makes it normative.

## Resolution

**Maintainer ruled Reading B on 2026-09-12 (P2-fix).** §26's `T-SPEC-002` pass condition now
reads:

> `statement_key` MUST be unique across the registry; each registry entry MUST reference exactly
> one valid Requirement ID. One Requirement ID MAY be referenced by multiple entries when it
> covers distinct normative statements in different sections.

Implemented by `check_registry_keys_unique` + `check_registry_requirements_resolvable` in
`src/lab_brain/spec/conformance.py`. The implementation did not change -- what changed is that it
now rests on settled spec text rather than on an agent's reading.

## Resolution checklist

- [x] Spec maintainer confirmed Reading B (2026-09-12)
- [x] §26 `T-SPEC-002` pass condition updated
- [x] `conformance.py` / test docstrings updated to cite the settled wording
- [x] Recorded in the spec Version Notes as amendment `v3.3-a1`
- [x] Issue closed; no registry entry cited it
