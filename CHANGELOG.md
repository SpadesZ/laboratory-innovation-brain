# Changelog

Implementation history of Laboratory Innovation Brain. Specification changes live in the
Version Notes table of `docs/spec/SAI_3.3.md`, not here.

## [Unreleased]

### M0a — Scientific Identity Foundation (in progress)

#### Added

- Repository skeleton per §18, scoped to what M0a needs — `learning/`, `interfaces/dashboard`,
  `integrations/lims` and other §18.1 exclusions are deliberately absent rather than stubbed.
- `lab_brain.spec`: machine-readable projection of the specification. Parses the §25.3
  requirement table, the §24.5 EXT-001 declaration and the §26 traceability matrix directly
  from the spec document, so the tables cannot drift from CI.
- `docs/normative_statements.yaml`: Normative Statement Registry (§23.6). 77 statements
  covering all 52 requirements; the first 17 entries transcribed verbatim from the §23.6
  excerpt.
- `docs/milestones.yaml`: §26.1 gate order plus a requirement-to-milestone allocation that
  partitions all 52 requirements exactly once.
- `T-SPEC-001` (TST-002) — 10 assertions: Requirement ID uniqueness and well-formedness, the
  self-asserted 52↔52 count invariant, every requirement has a test, no matrix row or test
  marker references an unknown ID, marker pairs exist in the matrix, and the milestone
  catalog partitions every requirement.
- `T-SPEC-002` (TST-003) — 9 assertions: registry key uniqueness, requirement/test
  resolvability, test-or-explicit-deferral, review dates on deferrals, agreement with the §26
  matrix, normative vocabulary, and a ratchet requiring real tests once a milestone is DONE.
- ADR-0001 … ADR-0009 recording the architecture decisions SAI 3.3 already fixed.
- `scripts/update_status.py`: derives the IMPLEMENTATION_STATUS.md requirement table from
  milestone allocation and test markers, with `--check` for CI (AGT-003).
- `compose.yaml` (PostgreSQL 17 + pgvector on host port 5433), `Makefile`, `scripts/dev.ps1`.

#### Fixed (P1-fix, after external review returned CONDITIONAL PASS)

- **`EXT-001` declared in both §25.3 and §24.5 was silently overwritten.** `parse_requirements`
  ended in a plain dict write, so the duplicate was collapsed before
  `len(ids) == len(set(ids))` could count it — and `test_requirement_ids_are_unique` claimed in
  its docstring to catch exactly this. Now raises `SpecParseError`, with a regression test that
  injects the duplicate into the real spec text.
- **The "real test" ratchet could be satisfied by a function pytest never collects.** The static
  collector looked for decorators without checking collectability, so a marked
  `helper_that_never_runs()` counted as coverage and a milestone could reach DONE with nothing
  executing. Audit found two further paths the review had not: markers on methods of any
  non-`Test*` class, and on `Test*` classes defining `__init__` (which pytest skips).
  `markers.py` now models pytest's collection rules and returns `RejectedMarker` for anything
  failing them; `T-SPEC-001` asserts that list is empty.

#### Added (P1-fix)

- `.github/workflows/ci.yml` — spec conformance runs first and alone (a normative break blocks
  the slice under AGT-015), then ruff, format check, mypy strict and the full suite. Before
  this, the `make check` target was executed by nothing, so "CI verified" rested on the agent's
  own report while TST-003 requires *Spec CI MUST verify*.
- `lab_brain.spec.conformance` — all checks as pure functions returning violation lists, so the
  same function can be asserted `== []` against the repository and `!= []` against a broken
  fixture.
- 26 negative tests in `tests/spec/test_conformance_guards.py`: every guard must be able to
  fail. Replaces P1's evidence, which was a document describing repository edits that were
  reverted — not durable, not re-runnable, not visible in CI. Fixtures use `tmp_path`; the
  repository is never mutated.
- `tests/spec/test_marker_collection.py` — cross-checks the static collector against real
  `pytest --collect-only` output, since reproducing pytest's rules is a model that can drift.
  Includes a guard that the parsed output is non-empty, so the cross-check cannot pass by
  comparing nothing.
- `docs/spec_issues/` with a `BLOCKING` / `GATE` / `EDITORIAL` severity scale, and an optional
  `spec_issue` field on registry entries whose existence `T-SPEC-002` verifies.

#### Notes

- A bare `pytest` run needs no PostgreSQL, no Lumerical seat and no network (AGT-007).
- Three spec ambiguities are now formal records rather than docstring asides. Recording an
  interpretation in a comment and then passing the test presents an agent's reading as a
  verified norm, which is what AGT-015 prohibits. SPEC-ISSUE-001 (T-SPEC-002 "unique
  Requirement IDs" contradicts its own §23.6 example) and SPEC-ISSUE-003 (§10.2
  typed-tools-only has no dedicated Requirement ID, and `T-VER-002` does not discharge it) are
  GATE severity: work continues on a provisional reading, both must be resolved before the M0a
  gate. SPEC-ISSUE-002 (`GH-xxx` missing from §23.2) is editorial.
