# Spec Issues

Open questions about SAI 3.3 itself, raised under AGT-015:

> Agent MUST NOT resolve spec conflicts via "newer-looking" prose; conflicting normative
> contracts block the slice and require spec issue/ADR.

An agent is not permitted to settle an ambiguity in the specification by picking the reading
it prefers. When one is found, it is recorded here with the exact competing readings and a
proposed wording, and the decision is escalated to the spec maintainer.

## Severity

| Severity | Meaning | Effect on implementation |
|---|---|---|
| `BLOCKING` | Two normative contracts directly contradict each other | The slice stops immediately (AGT-015) |
| `GATE` | A single statement is ambiguous, or a mapping is indirect. Work can continue on a provisional reading | MUST be resolved before the named milestone gate |
| `EDITORIAL` | Incomplete list or typo with no semantic consequence | Track only |

## Index

This table is a reading aid. **The `Status:` line inside each issue document is the authority** —
that is what `lab_brain.spec.outcomes.load_spec_issues` parses and what the executed-coverage gate
enforces. The two are compared by `tests/spec/test_spec_issue_index.py`, because this table said
"OPEN" for six issues that had been RESOLVED for two days and nothing objected.

| ID | Severity | Subject | Blocks gate | Status |
|---|---|---|---|---|
| [001](SPEC-ISSUE-001-registry-unique-requirement-ids.md) | GATE | T-SPEC-002 "unique Requirement IDs" contradicted the §23.6 example | M0a | **RESOLVED** — Reading B, `v3.3-a1` |
| [002](SPEC-ISSUE-002-gh-namespace-missing.md) | EDITORIAL | `GH-xxx` missing from the §23.2 namespace table | — | **RESOLVED** — `v3.3-a2` |
| [003](SPEC-ISSUE-003-typed-tools-no-requirement-id.md) | GATE | §10.2 typed-tools-only had no dedicated Requirement ID | M0a | **RESOLVED** — Option 1, `SIM-003`, `v3.3-a1` |
| [004](SPEC-ISSUE-004-heuristic-approval-no-requirement-id.md) | GATE | P16 heuristic approval governance has no Requirement ID | M7 | **RESOLVED** — `HEU-001`, `v3.3-a2` |
| [005](SPEC-ISSUE-005-novelty-coverage-no-requirement-id.md) | GATE | PriorArtSearchRecord / novelty coverage has no Requirement ID | M3 | **RESOLVED** — `SRC-003`, `v3.3-a2` |
| [006](SPEC-ISSUE-006-no-single-scalar-fom-no-requirement-id.md) | GATE | P10 "no single scalar FoM" has no Requirement ID | M4 | **RESOLVED** — `VER-007`, `v3.3-a2` |
| [007](SPEC-ISSUE-007-cross-store-unit-of-work-no-requirement-id.md) | GATE | §12.3 cross-store unit of work has no Requirement ID | M1 | **RESOLVED** — `OPS-004`, `v3.3-a2` |
| [008](SPEC-ISSUE-008-fabrication-gate-no-requirement-id.md) | EDITORIAL | §14.3 fabrication human sign-off has no Requirement ID | — | **RESOLVED** — under `SEC-002`, `v3.3-a2` |
| [009](SPEC-ISSUE-009-cost-vector-has-no-token-dimension.md) | GATE | COST-001 requires token accounting `CostVector` cannot represent; cap `0` vs `NULL` undefined | M0b | **RESOLVED** — `token_count` + cap semantics, `v3.3-a10` |
| [010](SPEC-ISSUE-010-belief-event-cannot-name-its-project-or-policy.md) | GATE | `BeliefRevisionEvent` names neither its project nor the policy that authorised it, so EPI-003 replay is unscoped and EPI-005 determinism has no anchor | M0b | **RESOLVED** — `project_id` + `policy_id`, `v3.3-a11` |
| [011](SPEC-ISSUE-011-belief-event-carries-no-durable-authorization-proof.md) | GATE | A stored belief event carries no durable proof a policy decision authorised it; §17.14's `Decision` could hold it but no obligation, vocabulary or Requirement ID is stated | M0b | OPEN |

Issues 004–008 were all raised by the **M0a Spec Coverage Audit** (§23.5 (2)) — the section-by-section
review of §6–§16 that a linter cannot perform. Each is a hard MUST in the prose with no Requirement
ID to map to, so adding one changes the `53 ↔ 53` invariant and is a maintainer decision, not an
agent decision. None of them blocks M0a.

Issues 009 and 010 came from the opposite direction: not a coverage audit but an implementation
slice that could not be written honestly without a ruling — 009 from P5 / `COST-001`, where a
requirement named a dimension its own type could not hold, and 010 from P7 / `EPI-003`+`EPI-005`,
where the event the requirements are about could name neither its project nor its authorising
policy. Both are the same shape: an obligation that the schema made unrepresentable rather than
merely unchecked.

## Enforcement

Two mechanisms, and neither depends on anyone remembering:

- `T-SPEC-002` verifies that a registry entry citing an issue names a file that exists, so an issue
  cannot be referenced and then quietly deleted.
- `scripts/check_requirement_coverage.py` refuses to let a milestone named by an OPEN `GATE` issue be
  marked DONE, and treats an unparseable issue header as a violation in its own right — an
  unreadable header would silently disable the first check.

A registry entry that rests on an unresolved issue names it in its `spec_issue` field.
