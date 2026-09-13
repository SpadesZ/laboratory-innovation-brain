"""Repository hygiene: IMPLEMENTATION_STATUS.md must agree with the code (AGT-003).

The requirement table has been generated since P1. The Tests table was not, and it drifted: it
claimed "288 passed with postgres; 237 + 51 skipped without" while the suite had grown to 307, and
`update_status.py --check` passed anyway because it only ever looked at the requirement block. CI
was green on a number nobody recomputed, which is the same failure the executed-coverage ratchet was
built to remove -- relocated from coverage to documentation.

So both blocks are generated now, and this file checks what can be checked from inside a pytest
session. Freshness of the *test inventory* cannot be: it is derived from the whole-suite outcome
report, which the plugin writes at session finish, so any report visible here is from an earlier run.
That check belongs after the suite, and CI runs `scripts/update_status.py --check` in the two jobs
that execute the whole suite.

Deliberately unmarked with requirement/spec_test markers. AGT-003 is an *agent operating rule*, not
one of the Requirement IDs, and claiming one here would inflate the traceability matrix with
something the spec never asked for.
"""

from __future__ import annotations

import subprocess
import sys

from lab_brain.spec import repo_root

STATUS = "IMPLEMENTATION_STATUS.md"


def test_requirement_status_table_is_current():
    """Hermetic: the requirement table is derived from the spec, milestones and markers only."""
    result = subprocess.run(
        [sys.executable, "scripts/update_status.py", "--check", "--requirements-only"],
        cwd=repo_root(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"{STATUS} requirement table is stale — run `python scripts/update_status.py`.\n"
        f"{result.stdout}{result.stderr}"
    )


def test_the_test_inventory_is_generated_not_written_by_hand():
    """The block must carry its generated markers, whatever its contents currently are.

    This is the guard against the actual regression: the table was prose, so it could hold any
    number at all and no check would object. Losing the markers would silently restore that, and
    `--check` would go back to validating only half the file while still reporting success.
    """
    text = (repo_root() / STATUS).read_text(encoding="utf-8")
    for marker in (
        "<!-- BEGIN GENERATED: test-inventory -->",
        "<!-- END GENERATED: test-inventory -->",
    ):
        assert marker in text, f"{STATUS} lost {marker}; the Tests table is hand-written again"

    begin = text.index("<!-- BEGIN GENERATED: test-inventory -->")
    end = text.index("<!-- END GENERATED: test-inventory -->")
    block = text[begin:end]
    assert "| **Total** |" in block, f"{STATUS} test inventory has no total row"
    # The sentence that was wrong. It must now be derived, so it must mention the marker-derived
    # gated count rather than a remembered pair of numbers.
    assert "Backend-gated" in block, f"{STATUS} test inventory no longer reports the gated count"


def test_checking_the_inventory_refuses_a_partial_report(tmp_path):
    """`--check` must fail closed when it cannot see a whole-suite report.

    Without this, running the check in a job that only executed `pytest tests/spec` would generate
    the table from a hundred-odd tests and call the file current -- shrinking every number while
    reporting success. The refusal is why the spec-conformance job uses `--requirements-only`
    explicitly instead of getting a quietly wrong answer.
    """
    report = repo_root() / "var" / "requirement_outcomes.json"
    original = report.read_bytes() if report.is_file() else None
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        '{"schema_version": 1, "enabled_gates": [], "tests": [],'
        ' "collection": {"collected": 1, "gated": 0, "node_digest": "deadbeefdeadbeef",'
        ' "by_file": {"tests/spec/test_status_freshness.py": {"collected": 1, "gated": 0}}}}',
        encoding="utf-8",
    )
    try:
        result = subprocess.run(
            [sys.executable, "scripts/update_status.py", "--check"],
            cwd=repo_root(),
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 1, result.stdout + result.stderr
        assert "whole-suite run" in result.stdout, result.stdout
    finally:
        if original is None:
            report.unlink(missing_ok=True)
        else:
            report.write_bytes(original)
