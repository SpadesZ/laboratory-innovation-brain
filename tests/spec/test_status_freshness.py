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

import re
import subprocess
import sys

from lab_brain.spec import repo_root, spec_path

STATUS = "IMPLEMENTATION_STATUS.md"


def status_text() -> str:
    return (repo_root() / STATUS).read_text(encoding="utf-8")


def spec_baseline_block() -> str:
    """Just the generated baseline block.

    Scoped deliberately. The first version of the amendment check searched the whole file for the
    latest amendment id, and a staleness injection walked straight past it: `v3.3-a10` also appears
    in the invariant-history table lower down, so the assertion passed while the header said a8.
    A check that can be satisfied by an unrelated part of the document is not checking the header.
    """
    text = status_text()
    begin = text.index("<!-- BEGIN GENERATED: spec-baseline -->")
    end = text.index("<!-- END GENERATED: spec-baseline -->")
    return text[begin:end]


def test_the_hermetic_blocks_are_current():
    """The requirement table, the coverage audit and the spec baseline, in one subprocess.

    All three are derived from the spec, the milestones, the markers and the migrations directory,
    so none needs a whole-suite outcome report and `--requirements-only` regenerates every one.
    """
    result = subprocess.run(
        [sys.executable, "scripts/update_status.py", "--check", "--requirements-only"],
        cwd=repo_root(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"{STATUS} is stale — run `python scripts/update_status.py`.\n"
        f"{result.stdout}{result.stderr}"
    )


# --------------------------------------------------------------------------------------------
# The manual header. AGT-003's recurrent blind spot.
#
# Each generated block in this file was generated only AFTER it had drifted and a human noticed:
# the requirement table in P1, the test inventory in P4 (it claimed 288 tests against a suite of
# 307), the coverage audit at M0a rev 6. The header was the last hand-typed surface and it drifted
# the same way -- twice inside the P5-fix slice alone:
#
#     "Spec amendments in force: v3.3-a1 … v3.3-a8"   while a9 had been in force for a day
#     "9 migrations applied"                          while there were 10, then 11
#
# Neither was caught by anything, because `--check` only looked at the blocks it generated, and
# these facts were not in a block. They are now.
#
# The test below re-derives the amendment span with a DIFFERENT parse from the generator's, rather
# than asserting the file matches what the generator would write -- that comparison is what
# `--check` above already does, and doing it twice would only prove the generator agrees with
# itself.
# --------------------------------------------------------------------------------------------


def test_the_spec_baseline_is_generated_not_written_by_hand():
    """The markers must survive. Losing them silently restores a hand-typed header."""
    text = status_text()
    for marker in (
        "<!-- BEGIN GENERATED: spec-baseline -->",
        "<!-- END GENERATED: spec-baseline -->",
    ):
        assert marker in text, f"{STATUS} lost {marker}; the header is hand-written again"


def test_the_stated_amendments_are_the_ones_the_spec_carries():
    """Independent cross-check of the fact that was wrong.

    Counts `v3.3-aN` rows straight out of the Version Notes table and compares against what the
    document claims, so a generator bug fails here rather than being ratified by `--check`.
    """
    numbers = sorted(
        {
            int(match.group(1))
            for match in re.finditer(
                r"^\|\s*\*{0,2}v3\.3-a(\d+)\*{0,2}\s*\|",
                spec_path().read_text(encoding="utf-8"),
                re.MULTILINE,
            )
        }
    )
    assert numbers, "no amendment rows parsed from the Version Notes; the table format changed"
    assert numbers == list(range(1, len(numbers) + 1)), (
        f"amendment numbering has a gap: {numbers}. An amendment that was withdrawn rather than "
        "superseded needs a Version Notes row saying so, or the ledger is not a ledger"
    )
    block = spec_baseline_block()
    assert f"`v3.3-a{numbers[-1]}` ({len(numbers)} amendments)" in block, (
        f"{STATUS}'s spec baseline does not state v3.3-a{numbers[-1]} and {len(numbers)} "
        f"amendments, which is what the spec carries. Block:\n{block}"
    )


def test_the_stated_migration_count_is_the_number_on_disk():
    """The other fact that was wrong, cross-checked the same way."""
    count = len(list((repo_root() / "migrations").glob("*.sql")))
    assert count > 0, "no migrations found; this check is comparing nothing"
    assert f"| Migrations declared | {count} —" in spec_baseline_block(), (
        f"{STATUS} does not state {count} declared migrations"
    )


def test_the_header_makes_no_claim_about_what_a_database_has_applied():
    """A document cannot verify a running system, so it must not assert one.

    The old header said "N migrations applied", which is a claim about somebody's PostgreSQL. It
    was wrong twice and could not have been checked even in principle -- `migrate.py --status` is
    the thing that answers it. Generating a number and calling it "applied" would have preserved
    the false claim behind a marker, which is worse than leaving it hand-typed.
    """
    header = status_text().split("## Requirement Status")[0]
    assert not re.search(r"\d+\s+migrations applied", header), (
        f"{STATUS} claims a number of applied migrations again; state what is *declared* and let "
        "`python scripts/migrate.py --status` answer for a given database"
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
