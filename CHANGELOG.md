# Changelog

Implementation history of Laboratory Innovation Brain. Specification changes live in the
Version Notes table of `docs/spec/SAI_3.3.md`, not here.

## [Unreleased]

### M0a — Scientific Identity Foundation (in progress)

### M0a-2 — scientific identity models (P2)

#### Added

- Core entities: `Artifact`, `SourceWork`, `Claim`, `Observation`, `Attestation`,
  `RelationJudgment`, plus `EvidenceField`, `ConditionSchemaRef`, `ConditionMatch`. All frozen,
  all `extra="forbid"` — a typo'd `sensitivity_lable` that is silently dropped produces a record
  that looks classified and is not.
- Content addressing (ART-001): `artifact_id` is derived from `content_hash` by a total,
  injective function and recomputed on every construction. "Same bytes, two ids" and "one id,
  two contents" are unrepresentable rather than discouraged. Streaming and path hashing for
  payloads larger than memory.
- `ConditionSchemaRegistry` (EVI-005): schema versions are immutable contracts; unregistered
  versions and undeclared condition keys are rejected at write time. Comparison semantics stay
  domain-owned — core refuses to compare without a registered DomainPack comparator, and rejects
  a comparator that misreports its own version.
- Repository protocols with an in-memory implementation that enforces the same write-time
  invariants as SQL. A fake that accepts what the real store rejects makes a green suite
  meaningless.
- Migrations 001, 002, 003, 004, 008 and `scripts/migrate.py`. Apply order is declared, not
  alphabetical: 008 precedes 003 because attestations carry a foreign key to a registered
  condition schema. Applied migrations are checksummed, so editing one after it has been applied
  fails the run instead of silently diverging two environments.
- CI `backend` job with a PostgreSQL service. Without it, `gate_profile: [postgres]` could never
  be satisfied in CI and the final step of the ratchet would fall back to a local run.

#### Fixed

- Executed-coverage guards were not hermetic: they passed `{**os.environ, **env}` to their
  subprocesses, so with `LAB_BRAIN_TEST_POSTGRES=1` set in the outer run the gated-skip fixture
  stopped being skipped and that guard silently stopped guarding. Found by running both gate
  profiles rather than one.

#### Changed

- `SYS-001` reallocated from M0a to M0b. Its §26 pass condition names `EpistemicState` and
  `Hypothesis`, neither of which exists in M0a, so only half of it was exercisable there — which
  under the executed-coverage gate would have meant claiming a requirement discharged on half a
  pass condition. The no-support-arrays invariant is enforced on the M0a models regardless.
- Ruff line length 95 -> 100.

#### Notes

- Risk R-5 closed: PostgreSQL 17 + pgvector running, migrations applied, 13 schema-constraint
  tests confirming the constraints actually reject.
- New R-7: `artifact_id` is globally content-addressed while `Artifact.project_id` is a single
  value, so the same file in two projects is one row with one sensitivity label. Harmless until
  ACL enforcement exists; must be resolved by P4/SEC-002.

### M0a-1 — repository skeleton and spec CI (P1, P1-fix, P1-fix2)

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

#### Fixed (P1-fix2, after the second review found a new bypass one layer down)

- **A collected test counted as coverage even when it never executed.** The DONE ratchet read
  `collect_marked_tests()`, which returns tests pytest *would collect*. `@pytest.mark.skip`,
  `@pytest.mark.xfail(run=False)`, a module- or class-level skip, and — worst — our own
  `conftest.py` backend-gate skips are all collected while running no assertion. The last was
  self-inflicted: the mechanism keeping a bare `pytest` green without PostgreSQL (AGT-007) was
  converting "deselected" into "covered". The `--collect-only` cross-check could not catch this
  by construction, since it guards absence from collection, not absence of execution.

  DONE now means: every Requirement of a DONE milestone has >= 1 traceability test that
  **executed and passed**, in a run where every gate in the milestone's `gate_profile` was
  enabled. Enforced by `scripts/check_requirement_coverage.py` after the session — it cannot be
  a test, because a test asserting "every DONE requirement passed" would need outcomes of tests
  that have not run yet.

#### Added (P1-fix2)

- `lab_brain.spec.outcome_plugin` — pytest plugin recording each marked test's real outcome
  through pytest's own `iter_markers()`, so this gate does not inherit any error in the AST
  model in `markers.py`. `COVERING_OUTCOMES` is `{"passed"}` alone; `xpassed` is excluded
  because a test declared expected-to-fail is not an assertion the lab stands behind.
- `gate_profile` on every milestone. M0a–M4 declare `[postgres]`, which turns Risk R-5 from a
  note into a machine condition: they cannot be signed off by a run that skipped every
  PostgreSQL test.
- 28 executed-coverage guards using **real pytest subprocesses** over generated fixtures,
  reading the report that run produced. Covers all four named bypasses, five adjacent failure
  modes (failed, xpassed, setup error, missing report, wrong schema version) and a positive
  control, plus the ratchet parametrised over every non-passing outcome.
- GATE severity is now enforced rather than documented. Spec issues carry machine-readable
  `Severity:` / `Status:` / `Blocks gate:` fields; a DONE milestone named by an OPEN GATE issue
  is a violation, and so is an unparseable header — which would silently disable that check.

#### Changed (P1-fix2)

- `check_completed_milestones_have_tests` renamed to
  `check_completed_milestones_have_collected_tests`, so its insufficiency is visible at the call
  site instead of buried in a docstring.
- `TestOutcome` dataclass renamed to `RecordedOutcome`: pytest warned
  `cannot collect test class 'TestOutcome' because it has a __init__ constructor` wherever it was
  imported into a test module — the exact `Test*` + `__init__` case `markers.py` models.
- `xfail(run=False)` is now labelled `xfailed` rather than `skipped`. It was correctly excluded
  from coverage either way, but the label was wrong and would have misled a report reader.

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
