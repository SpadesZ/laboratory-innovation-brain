# Phase Audit — P1-fix: response to external P1 review

Date: 2026-09-12
Spec: SAI 3.3
Milestone: M0a (IN_PROGRESS — not the M0a exit gate)
Requirements in scope: TST-002, TST-003
Trigger: external review returned **P1 = CONDITIONAL PASS** with 2 blockers + 1 CI gap

## 1. Findings and disposition

| # | Review finding | Severity | Disposition |
|---|---|---|---|
| 1 | `EXT-001` duplicate declaration silently overwritten | BLOCKER | Fixed + regression test |
| 2 | "Real test" ratchet bypassable by a marked non-test function | BLOCKER | Fixed + 5 tests; scope was wider than reported |
| 3 | No CI on GitHub; `make check` executed by nothing | HIGH | `.github/workflows/ci.yml` added |
| F-2 | Agent chose a reading of an ambiguous spec clause | Process | Escalated as SPEC-ISSUE-001 |
| F-3 | typed-tools-only mapped to `VER-002` without equivalence | Process | Escalated as SPEC-ISSUE-003 |
| — | Mutation evidence not durable ("edited and reverted") | HIGH | 26 permanent negative tests |

All six accepted. No finding was disputed.

## 2. Blocker 1 — `EXT-001` collision

**Confirmed as reported.** `parse_requirements` ended with a plain dict write:

```python
requirements[ext_match.group(1)] = SpecRequirement(...)
```

A duplicate `EXT-001` in §25.3 would be overwritten, so `len(ids) == len(set(ids))` counted a
collapsed dict and passed. The docstring of `test_requirement_ids_are_unique` claimed it would
"catch EXT-001 colliding with a table row" — **the test asserted something it did not do.**
That is worse than the missing check: a false claim in a test is load-bearing for later audits.

**Fix** — `src/lab_brain/spec/parser.py`: membership check before insertion, raising
`SpecParseError` naming both sections and the 51 + 1 = 52 arithmetic from §25.3.

**Regression test** —
`test_conformance_guards.py::test_ext_001_declared_in_both_sections_is_rejected` injects a
duplicate row into the real spec text and requires the parse to fail. Also added:
`test_missing_ext_001_declaration_is_rejected` for the inverse.

## 3. Blocker 2 — uncollectable markers counted as coverage

**Confirmed, and the hole was larger than reported.** The review identified marked non-test
functions. Audit of the same code found a second path: the class branch accepted *any*
`ast.ClassDef`, so a marked method inside `class Helper:` also counted. A third existed —
pytest skips `Test*` classes that define `__init__`, and that was not modelled either.

Three ways to claim coverage that never executes, each satisfying
`test_completed_milestones_have_real_tests`. This was the worst defect in P1: the harness whose
entire purpose is preventing unverified coverage claims could itself be given one.

**Fix** — `src/lab_brain/spec/markers.py` now models pytest's collection rules: module
`test_*.py`, function `test_*`, methods only inside `Test*` classes without `__init__`, no
nesting deeper than one class. Markers failing any rule are returned as `RejectedMarker` with a
reason rather than dropped — silently discarding them would let someone believe they had
marked a test.

New assertion in T-SPEC-001:
`test_no_traceability_marker_sits_on_an_uncollected_function`.

**Regression tests** — 5 cases, each asserting both non-counting and reporting:

| Case | Expected |
|---|---|
| `helper_that_never_runs()` with both markers | not counted, reported |
| marked method on `class Helper:` | not counted, reported |
| marked method on `class TestWithInit:` with `__init__` | not counted, reported |
| marked method on `class TestArtifact:` (valid) | **counted**, not reported |
| marked `test_*` in `helpers.py` | not counted, not reported (outside the glob) |

Plus `test_milestone_marked_done_without_a_collected_test_is_reported`, which is the review's
exact scenario: a milestone marked DONE whose only evidence is `helper_not_collected()` must
still fail the ratchet.

**Residual risk, stated plainly.** This is a *reimplementation* of pytest's rules, so it can
drift from pytest. `tests/spec/test_marker_collection.py` compares the static model against
real `pytest --collect-only` output on every run, including a guard that the parsed output is
non-empty so the cross-check cannot pass by comparing nothing. Recorded as Risk R-4; the
cross-check parses `-q` text, which is not a stable API.

## 4. CI gap

**Confirmed.** No `.github/` existed. The claim "Spec CI" was wrong; it was a CI-ready harness.
TST-003's wording is *Spec CI MUST verify*, so the gap was against the requirement itself.

`.github/workflows/ci.yml` runs on every push, PR and manual dispatch:

- **job `spec-conformance`** (first, alone): `pytest tests/spec`, then
  `update_status.py --check`, then the environment report. Isolated because a normative break
  blocks the slice under AGT-015 — lint output from an unshippable slice is noise.
- **job `quality`** (needs the above): ruff check, ruff format --check, mypy strict, full suite.

No PostgreSQL, no Lumerical, no network. `LAB_BRAIN_TEST_*` stay unset, so backend tests are
deselected rather than silently passing.

Not yet proven: the first remote run. Recorded as Risk R-6 — a workflow that has never executed
is not a gate.

## 5. Durable mutation evidence

The review's sharpest point: P1's only evidence for "9/9 caught" was a document the agent wrote
about a process it ran and reverted. Unverifiable and unrepeatable.

Restructured. All conformance logic moved to `src/lab_brain/spec/conformance.py` as pure
functions returning violation lists. The same function is now called twice:

- `test_requirement_traceability.py` / `test_normative_statement_coverage.py` assert `== []`
  against the real repository;
- `test_conformance_guards.py` asserts `!= []` against a fixture violating exactly one rule.

26 negative tests, in CI, on every commit. Fixtures are written to `tmp_path`; **the repository
is never mutated.**

## 6. F-2 and F-3 — process correction

The review was right that this was a process failure, not just a documentation gap. Recording an
interpretation in a docstring and then passing the test presents an agent's reading as a
verified norm. AGT-015 exists to prevent exactly that.

`docs/spec_issues/` now holds formal records with competing readings, proposed wording and a
resolution checklist, plus a severity scale (`BLOCKING` / `GATE` / `EDITORIAL`) that states the
effect on implementation. SPEC-ISSUE-001 and -003 are GATE: work continues on a provisional
reading, and both must be resolved before the M0a gate.

To stop this decaying into comments, registry entries carry an optional `spec_issue` field and
`T-SPEC-002` verifies the referenced file exists
(`test_cited_spec_issues_exist`) — with its own negative test for a dangling reference.

On F-3 specifically: agreed that `T-VER-002` does not discharge typed-tools-only. A backend can
hold a valid `Capability` descriptor and still expose `eval_script`. The registry keeps the
`VER-002` mapping for internal consistency but now carries `spec_issue: SPEC-ISSUE-003`, and the
issue states that adding a 53rd requirement would break the `52 ↔ 52` invariant — so only the
maintainer can resolve it.

## 7. Evidence

```
ruff check src tests scripts     All checks passed
ruff format --check              14 files already formatted
mypy (strict, 6 files)           Success: no issues found
pytest                           51 passed in 2.00s
```

Suite composition: 11 T-SPEC-001 · 10 T-SPEC-002 · 26 harness guards · 3 collection
cross-check · 1 status freshness.

One earlier run took 260s. Re-measured with `--durations`: 2.0s total, slowest item 1.07s
(the `--collect-only` subprocess). The outlier was first-touch filesystem overhead on newly
written files, not test cost.

## 8. What this audit still does NOT establish

- **Registry completeness against the prose** — §23.5 (2), human gate, due at P3.
- **Any scientific or storage behaviour** — no models, migrations or repositories exist.
- **Postgres conformance** — no instance provisioned (R-5).
- **That CI works** — authored, never executed remotely (R-6).
- **The real-environment half of TST-001** — no Lumerical seat (R-1).

## 9. Verdict

Both blockers fixed with regression tests that fail without the fix. CI gap closed pending its
first remote run. Mutation evidence is now executable rather than narrated.

Requesting re-review before P2. Two GATE spec issues need maintainer decisions before the M0a
gate at P3, but neither blocks P2.
