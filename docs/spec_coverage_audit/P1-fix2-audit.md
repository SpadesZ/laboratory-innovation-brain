# Phase Audit — P1-fix2: executed-test ratchet

Date: 2026-09-12
Spec: SAI 3.3
Milestone: M0a (IN_PROGRESS)
Requirements in scope: TST-002, TST-003
Trigger: second external review — original three findings PASS, one **new** blocker found
one layer down

## 1. The finding

Confirmed exactly as reported. After P1-fix the ratchet still read:

```python
covered = {r for test in collect_marked_tests() for r in test.requirement_ids}
```

`collect_marked_tests()` returns tests pytest **would collect**. Collection is not execution.
So this still passed the gate while executing nothing:

```python
@pytest.mark.skip(reason="not ready")
@pytest.mark.requirement("ART-001")
@pytest.mark.spec_test("T-ART-001")
def test_artifact():
    assert False
```

Static collector counts it. `--collect-only` cross-check counts it (skip is decided at run
time, not collection). DONE ratchet counts it. Session stays green.

The cross-check could not catch this by construction: it compares against collection, so it
guards "absent from pytest's collection" and is silent on "present in collection, never
executed".

### The case that was our own doing

The review listed four constructs. The fourth is the one worth naming: `tests/conftest.py`
skips `postgres` / `lumerical` / `network` tests so a bare `pytest` stays green without those
backends (AGT-007). That mechanism was converting **"deselected" into "covered"**. The code
written to keep CI honest about missing backends was the code manufacturing false coverage.

Same class as the P1 helper loophole: a milestone could reach DONE with zero executions of the
requirement's test.

## 2. Fix

Per the review's direction, no further extension of collection-rule modelling. The definition
of DONE was raised instead:

> Every Requirement of a DONE milestone must have >= 1 traceability test that **actually
> executed and passed**, in a run where every gate in that milestone's declared `gate_profile`
> was enabled. `SKIPPED` / `XFAIL(run=False)` / `XPASS` / `FAILED` / `ERROR` / `not_run` are
> not coverage.

| Component | Role |
|---|---|
| `lab_brain/spec/outcome_plugin.py` | pytest plugin; records each marked test's real outcome via pytest's own marker API |
| `lab_brain/spec/outcomes.py` | report loader + the four gate checks |
| `scripts/check_requirement_coverage.py` | post-session gate, wired into both CI jobs, `make`, `dev.ps1` |
| `gate_profile` on each milestone | which backend profiles the validating run must have enabled |

Three design points worth stating:

**Markers are read through pytest, not through the AST.** `iter_markers()` resolves function,
class and module level markers as pytest itself sees them, so this gate does not inherit any
error in `markers.py`. The two mechanisms are now independent.

**It cannot be a test.** A test asserting "every DONE requirement passed" would need the
outcomes of tests that have not run yet, and would depend on ordering. It has to run after the
session, which is why it is a script rather than an assertion.

**It fails closed.** A missing report is a violation; deleting `var/requirement_outcomes.json`
is not a way past the gate. `addopts` writes it on every run, so a stale permissive report
cannot survive either.

`COVERING_OUTCOMES` is deliberately `{"passed"}` alone. `xpassed` is excluded although it did
execute and pass: a test declared expected-to-fail is not an assertion the lab stands behind.

## 3. Negative tests — 28, using real pytest subprocesses

Asserting against a hand-built report would only prove the checker parses JSON, not that pytest
reports what the checker assumes. So each fixture is written to `tmp_path`, a real pytest
subprocess runs it, and the assertion reads the report that run produced.

The four named bypasses:

| Fixture | Recorded outcome | Counts as coverage |
|---|---|---|
| `@pytest.mark.skip` + `assert False` | `skipped` | no |
| `@pytest.mark.xfail(run=False)` | `xfailed` | no |
| module-level `pytestmark = skip` | `skipped` | no |
| class-level `@skip` on `TestArtifact` | `skipped` | no |
| `@pytest.mark.postgres`, gate unset | `skipped` | no |

Adjacent failure modes, plus the positive control without which the suite would pass by
rejecting everything:

| Fixture | Recorded outcome | Counts as coverage |
|---|---|---|
| plain failing test | `failed` | no |
| `@xfail` that unexpectedly passes | `xpassed` | no |
| fixture raising during setup | `error` | no |
| **plain passing test** | `passed` | **yes** |
| passing test with `LAB_BRAIN_TEST_POSTGRES=1` | `passed`, gates `["postgres"]` | yes |

Ratchet behaviour, parametrised over all six non-passing outcomes:

- DONE + any non-passing outcome -> violation
- DONE + `passed` -> clean
- IN_PROGRESS + `skipped` -> clean (the gate binds at DONE, or no work could start)
- DONE with `gate_profile: [postgres]` and a run with no gates -> violation; with `postgres`
  enabled -> clean
- missing report -> `OutcomeReportError`
- wrong `schema_version` -> rejected

### End-to-end proof on this repository

`docs/milestones.yaml` was temporarily flipped `M0a: IN_PROGRESS -> DONE` and the gate run
against the real outcome report:

```
FAIL  DONE milestones have passing tests
        M0a is DONE but SYS-001 has no marked test in the outcome report
        M0a is DONE but ART-001 has no marked test in the outcome report
        M0a is DONE but EVI-005 has no marked test in the outcome report
        M0a is DONE but EVI-006 has no marked test in the outcome report
FAIL  DONE milestones ran their declared gate profile
        M0a is DONE and declares gate_profile ['postgres'] but the report was produced with [] enabled
FAIL  no OPEN GATE spec issue blocks a DONE milestone
        M0a is DONE but SPEC-ISSUE-001 is an OPEN GATE issue against it
        M0a is DONE but SPEC-ISSUE-003 is an OPEN GATE issue against it
exit: 1
```

All three dimensions bit. File restored; suite re-verified at 79 passed.

## 4. GATE governance — done now rather than deferred to P3

The review classed this as "before P3, not a P2 blocker". Implemented now because it is small
and because a severity scale nothing enforces is worse than no scale: it reads like a
guarantee.

`docs/spec_issues/README.md` says GATE issues MUST be resolved before their named gate, but
`T-SPEC-002` only checked that the file existed. So `SPEC-ISSUE-001 = OPEN`, `M0a = DONE`,
`CI = PASS` was reachable.

Each issue now carries machine-readable `Severity:` / `Status:` / `Blocks gate:` fields.
`check_no_open_gate_issues_for_completed_milestones` refuses a DONE milestone named by an OPEN
GATE issue. `check_spec_issue_headers_are_parseable` is the second half: an unreadable header
would silently disable the first check, so it is a violation in its own right — as is a GATE
issue with no `Blocks gate:` field, which enforces nothing.

Also caught: a GATE issue naming a milestone that does not exist.

## 5. Incidental findings during this slice

**`gate_profile: [postgres]` on M0a–M4.** Risk R-5 was previously prose. It is now a machine
condition: those milestones cannot be signed off without PostgreSQL tests having run. This
constrains our own future work, which is the point.

**`TestOutcome` dataclass renamed to `RecordedOutcome`.** pytest emitted
`PytestCollectionWarning: cannot collect test class 'TestOutcome' because it has a __init__
constructor` wherever it was imported into a test module — the exact `Test*` + `__init__` case
`markers.py` models. A dataclass that looks like a test class in every importing module is a
trap; renamed rather than suppressed.

**`xfail(run=False)` reports at setup, not call.** The first implementation labelled it
`skipped` because the setup branch matched before checking `wasxfail`. It was correctly
excluded from coverage either way, but the label was wrong and would have misled anyone reading
the report. Fixed; the negative test asserts the label, not just the exclusion.

## 6. Evidence

```
ruff check src tests scripts     All checks passed
ruff format --check              18 files already formatted
mypy (strict, 8 files)           Success: no issues found
pytest                           79 passed in ~13s
check_requirement_coverage.py    4/4 checks ok, exit 0
update_status.py                 up to date
```

Suite: 11 T-SPEC-001 · 10 T-SPEC-002 · 26 conformance guards · 28 executed-coverage guards ·
3 collection cross-check · 1 status freshness.

Runtime rose from 2.0s to ~13s. That is 10 real pytest subprocesses; the cost buys the only
evidence that pytest's reported outcomes match what the gate assumes.

## 7. Two layers, stated plainly

| Layer | Question | Strength |
|---|---|---|
| `markers.py` + cross-check | is there a test pytest would collect? | necessary, **not sufficient** |
| outcome report + coverage gate | did a test execute and pass under the required profile? | **authoritative** |

The static check is retained for a fast source-level signal and renamed
`check_completed_milestones_have_collected_tests` so its insufficiency is visible at the call
site rather than buried in a docstring.

## 8. What this audit still does NOT establish

- **Registry completeness against the prose** — §23.5 (2), human gate, due at P3.
- **Any scientific or storage behaviour** — no models, migrations or repositories exist.
- **Postgres conformance** — no instance provisioned (R-5), now gate-enforced.
- **The real-environment half of TST-001** — no Lumerical seat (R-1).

Two GATE spec issues remain OPEN and now mechanically block `M0a` from reaching DONE. They need
maintainer decisions, not agent decisions.

## 9. Verdict

The ratchet now rests on execution rather than collection, proven by subprocess fixtures for all
four named bypasses plus five adjacent failure modes and a positive control. GATE severity has
teeth. Risk R-5 is machine-enforced.

Requesting the narrow re-review offered: executed-test ratchet + CI.
