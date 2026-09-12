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

| ID | Severity | Subject | Blocks gate | Status |
|---|---|---|---|---|
| [001](SPEC-ISSUE-001-registry-unique-requirement-ids.md) | GATE | T-SPEC-002 "unique Requirement IDs" contradicted the §23.6 example | M0a | **RESOLVED** — Reading B, 2026-09-12 |
| [002](SPEC-ISSUE-002-gh-namespace-missing.md) | EDITORIAL | `GH-xxx` missing from the §23.2 namespace table | — | OPEN |
| [003](SPEC-ISSUE-003-typed-tools-no-requirement-id.md) | GATE | §10.2 typed-tools-only had no dedicated Requirement ID | M0a | **RESOLVED** — Option 1, `SIM-003`, 2026-09-12 |
| [004](SPEC-ISSUE-004-heuristic-approval-no-requirement-id.md) | GATE | P16 heuristic approval governance has no Requirement ID | M7 | OPEN |
| [005](SPEC-ISSUE-005-novelty-coverage-no-requirement-id.md) | GATE | PriorArtSearchRecord / novelty coverage has no Requirement ID | M3 | OPEN |
| [006](SPEC-ISSUE-006-no-single-scalar-fom-no-requirement-id.md) | GATE | P10 "no single scalar FoM" has no Requirement ID | M4 | OPEN |
| [007](SPEC-ISSUE-007-cross-store-unit-of-work-no-requirement-id.md) | GATE | §12.3 cross-store unit of work has no Requirement ID | M1 | OPEN |
| [008](SPEC-ISSUE-008-fabrication-gate-no-requirement-id.md) | EDITORIAL | §14.3 fabrication human sign-off has no Requirement ID | — | OPEN |

Issues 004–008 were all raised by the **M0a Spec Coverage Audit** (§23.5 (2)) — the section-by-section
review of §6–§16 that a linter cannot perform. Each is a hard MUST in the prose with no Requirement
ID to map to, so adding one changes the `53 ↔ 53` invariant and is a maintainer decision, not an
agent decision. None of them blocks M0a.

## Enforcement

Two mechanisms, and neither depends on anyone remembering:

- `T-SPEC-002` verifies that a registry entry citing an issue names a file that exists, so an issue
  cannot be referenced and then quietly deleted.
- `scripts/check_requirement_coverage.py` refuses to let a milestone named by an OPEN `GATE` issue be
  marked DONE, and treats an unparseable issue header as a violation in its own right — an
  unreadable header would silently disable the first check.

A registry entry that rests on an unresolved issue names it in its `spec_issue` field.
