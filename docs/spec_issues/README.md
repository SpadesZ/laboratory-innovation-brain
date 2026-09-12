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

| ID | Severity | Subject | Must resolve before | Status |
|---|---|---|---|---|
| [SPEC-ISSUE-001](SPEC-ISSUE-001-registry-unique-requirement-ids.md) | GATE | T-SPEC-002 "unique Requirement IDs" contradicts the §23.6 example | M0a gate (P3) | OPEN |
| [SPEC-ISSUE-002](SPEC-ISSUE-002-gh-namespace-missing.md) | EDITORIAL | `GH-xxx` missing from the §23.2 namespace table | — | OPEN |
| [SPEC-ISSUE-003](SPEC-ISSUE-003-typed-tools-no-requirement-id.md) | GATE | §10.2 typed-tools-only has no dedicated Requirement ID | M0a gate (P3) | OPEN |

A registry entry that rests on an unresolved issue names it in its `spec_issue` field.
`T-SPEC-002` verifies the referenced file exists, so an issue cannot be cited and then quietly
forgotten.
