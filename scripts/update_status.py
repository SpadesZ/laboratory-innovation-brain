"""Regenerate the Requirement Status table in IMPLEMENTATION_STATUS.md.

AGT-003 requires IMPLEMENTATION_STATUS.md to agree with the actual implementation state.
A hand-maintained 52-row table does not stay in agreement with anything, so the table is
derived from data that cannot lie about itself:

    milestone allocation   docs/milestones.yaml
    test evidence          @pytest.mark.requirement / @pytest.mark.spec_test in tests/
    spec test IDs          the §26 matrix

Status derivation:
    DEFERRED     milestone status is DEFERRED
    DONE         milestone status is DONE and a marked test exists
    IN_PROGRESS  milestone is IN_PROGRESS and a marked test exists
    BLOCKED      milestone is DONE but no marked test exists -- an inconsistency that
                 T-SPEC-002 also fails on, surfaced here rather than hidden
    TODO         otherwise

Usage:
    python scripts/update_status.py          # rewrite the table
    python scripts/update_status.py --check  # exit 1 if the file is stale (for CI)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lab_brain.spec import (
    collect_marked_tests,
    load_milestones,
    load_spec,
    repo_root,
)

BEGIN = "<!-- BEGIN GENERATED: requirement-status -->"
END = "<!-- END GENERATED: requirement-status -->"

TESTS_BEGIN = "<!-- BEGIN GENERATED: test-inventory -->"
TESTS_END = "<!-- END GENERATED: test-inventory -->"

AUDIT_BEGIN = "<!-- BEGIN GENERATED: coverage-audit -->"
AUDIT_END = "<!-- END GENERATED: coverage-audit -->"

#: Where the pytest plugin leaves its report. A build artifact, gitignored.
REPORT = Path("var") / "requirement_outcomes.json"

#: Human-readable group per test directory, in table order.
_GROUPS: tuple[tuple[str, str], ...] = (
    ("tests/unit", "Unit"),
    ("tests/contract", "Contract"),
    ("tests/integration", "Integration"),
    ("tests/e2e", "E2E"),
    ("tests/security", "Security"),
    ("tests/ux", "UX"),
    ("tests/spec", "Spec"),
)


class StaleReport(RuntimeError):
    """The outcome report cannot validate the current tree."""


def collect_node_digest() -> str:
    """Digest of the node ids pytest collects right now, computed as the plugin computes it.

    ``--requirement-outcomes`` is redirected to a throwaway path. ``addopts`` in pyproject.toml
    always enables the report, and ``pytest_sessionfinish`` fires under ``--collect-only`` too, so
    without the redirect this staleness check would overwrite the real report with one in which
    every test is ``not_run`` -- destroying the evidence
    ``scripts/check_requirement_coverage.py`` reads. The option takes the last value given, so the
    flag below wins over the one in ``addopts``.
    """
    with tempfile.TemporaryDirectory() as scratch:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                "--no-header",
                "-p",
                "no:randomly",
                f"--requirement-outcomes={Path(scratch) / 'collect_only.json'}",
            ],
            cwd=repo_root(),
            capture_output=True,
            text=True,
            check=False,
        )
    node_ids = sorted(
        line.strip()
        for line in result.stdout.splitlines()
        if "::" in line and not line.startswith(" ")
    )
    if not node_ids:
        raise StaleReport(
            "pytest --collect-only returned no node ids, so staleness cannot be checked:\n"
            + (result.stdout or "")
            + (result.stderr or "")
        )
    return hashlib.sha256("\n".join(node_ids).encode("utf-8")).hexdigest()[:16]


def load_collection() -> dict[str, object]:
    """Read the collection recorded by the last pytest run, refusing a stale or partial one.

    Three refusals, because each is a way the old hand-written table stayed wrong:

    * **missing** -- fail closed. Deleting the report must not be a way past the check.
    * **partial** -- a ``pytest tests/spec`` report describes a hundred-odd tests, not the suite.
      Letting it generate the table would silently shrink every number.
    * **stale** -- the recorded ``node_digest`` must match a fresh collection, or "the doc matches
      the report" is satisfiable while both are out of date. That is precisely the state
      IMPLEMENTATION_STATUS.md was in when it claimed 288 tests and the suite had 307.
    """
    path = repo_root() / REPORT
    if not path.is_file():
        raise StaleReport(
            f"{REPORT.as_posix()} not found. Run the whole suite first:\n"
            f"  pytest --requirement-outcomes={REPORT.as_posix()}"
        )
    report = json.loads(path.read_text(encoding="utf-8"))
    collection = report.get("collection")
    if not isinstance(collection, dict) or not collection.get("by_file"):
        raise StaleReport(
            f"{REPORT.as_posix()} predates the collection block; re-run the whole suite."
        )

    directories = {p.split("/")[1] for p in collection["by_file"] if p.count("/") >= 1}
    expected = {
        entry.name
        for entry in (repo_root() / "tests").iterdir()
        if entry.is_dir() and entry.name != "__pycache__" and any(entry.glob("test_*.py"))
    }
    if not expected <= directories:
        raise StaleReport(
            "the report covers only "
            + ", ".join(sorted(directories))
            + "; the test inventory needs a whole-suite run (missing: "
            + ", ".join(sorted(expected - directories))
            + ")"
        )

    fresh = collect_node_digest()
    if fresh != collection.get("node_digest"):
        raise StaleReport(
            f"{REPORT.as_posix()} is stale: it records node_digest "
            f"{collection.get('node_digest')} but the tree now collects {fresh}. Re-run the suite."
        )
    return collection


def build_test_inventory(collection: dict[str, object]) -> str:
    """The test table, derived from the recorded collection rather than typed by hand."""
    by_file: dict[str, dict[str, int]] = collection["by_file"]  # type: ignore[assignment]

    rows: list[tuple[str, int, int]] = []
    accounted: set[str] = set()
    for prefix, label in _GROUPS:
        files = sorted(p for p in by_file if p.startswith(prefix + "/"))
        if not files:
            rows.append((label, 0, 0))
            continue
        accounted.update(files)
        if prefix == "tests/spec":
            # The spec suite is the audit harness itself, so per-file is the useful granularity:
            # which guard exists matters more than how many guards there are.
            for path in files:
                rows.append(
                    (
                        f"Spec — `{Path(path).stem}`",
                        by_file[path]["collected"],
                        by_file[path]["gated"],
                    )
                )
        else:
            rows.append(
                (
                    label,
                    sum(by_file[p]["collected"] for p in files),
                    sum(by_file[p]["gated"] for p in files),
                )
            )

    for path in sorted(set(by_file) - accounted):
        rows.append((f"`{path}`", by_file[path]["collected"], by_file[path]["gated"]))

    total = int(collection["collected"])  # type: ignore[arg-type]
    gated = int(collection["gated"])  # type: ignore[arg-type]

    lines = [
        TESTS_BEGIN,
        "",
        "Generated by `scripts/update_status.py` from the collection the last whole-suite `pytest` "
        "run recorded. Counts are **collected** tests, which is profile-independent: the "
        "`postgres` and backend-free profiles collect the same set and differ only in what they "
        "skip. `Backend-gated` counts tests carrying a `postgres` / `lumerical` / `network` "
        "marker.",
        "",
        "| Suite | Collected | Backend-gated |",
        "|---|---:|---:|",
    ]
    for label, collected, gate_count in rows:
        lines.append(f"| {label} | {collected} | {gate_count or '—'} |")
    lines.extend(
        [
            f"| **Total** | **{total}** | **{gated}** |",
            "",
            f"A bare `pytest` executes **{total - gated}** of the {total} and skips the {gated} "
            "backend-gated ones, so no PostgreSQL, Lumerical seat or network is needed (AGT-007). "
            "Setting the matching `LAB_BRAIN_TEST_*` variable runs them; a milestone whose "
            "`gate_profile` names a backend cannot be signed off by a run that skipped it.",
            "",
            TESTS_END,
        ]
    )
    return "\n".join(lines)


def build_table() -> str:
    spec = load_spec()
    catalog = load_milestones()

    evidence: dict[str, list[str]] = {}
    for test in collect_marked_tests():
        for requirement_id in test.requirement_ids:
            evidence.setdefault(requirement_id, []).append(test.module)

    lines = [
        BEGIN,
        "",
        "Generated by `scripts/update_status.py` from `docs/milestones.yaml` and test "
        f"markers. {len(spec.requirements)} requirements / {len(spec.test_ids)} tests.",
        "",
        "| ID | Milestone | Status | Spec Test | Test files |",
        "|---|---|---|---|---|",
    ]

    for milestone in catalog.milestones:
        for requirement_id in milestone.requirements:
            modules = sorted(set(evidence.get(requirement_id, [])))
            has_test = bool(modules)
            if milestone.status == "DEFERRED":
                status = "DEFERRED"
            elif milestone.status == "DONE":
                status = "DONE" if has_test else "BLOCKED"
            elif milestone.status == "IN_PROGRESS" and has_test:
                status = "IN_PROGRESS"
            else:
                status = "TODO"
            test_ids = ", ".join(f"`{t}`" for t in spec.tests_for(requirement_id))
            files = ", ".join(f"`{m}`" for m in modules) or "—"
            lines.append(
                f"| {requirement_id} | {milestone.milestone_id} | {status} | {test_ids} | {files} |"
            )

    counts: dict[str, int] = {}
    for line in lines:
        for status in ("DEFERRED", "BLOCKED", "IN_PROGRESS", "DONE", "TODO"):
            if f"| {status} |" in line:
                counts[status] = counts.get(status, 0) + 1
                break
    summary = " · ".join(f"{status} {counts[status]}" for status in sorted(counts))
    lines.extend(["", f"**Totals**: {summary}", "", END])
    return "\n".join(lines)


def build_coverage_audit() -> str:
    """The §23.5 (2) audit's headline figures, derived rather than transcribed.

    These are the numbers that drifted worst. The section previously read "rev 3 ... 64 hard MUSTs
    = 62 live + 2 named deferred" and "Unregistered hard MUST found: not yet assessed" long after
    both were false, because nothing recomputed them and the audit document was edited separately.
    Generating them here means the two files cannot disagree.

    Needs no outcome report, so it is regenerated in ``--requirements-only`` mode too.
    """
    from lab_brain.spec import load_registry
    from lab_brain.spec.coverage_audit import (
        load_hard_must_counts,
        load_keyword_free,
        load_obligation_inventory,
        reconcile,
        spec_headings,
        unbalanced,
    )

    spec = load_spec()
    rows = reconcile(load_registry(), load_hard_must_counts())
    inventory = load_obligation_inventory()
    keyword_free = load_keyword_free()

    hard = sum(row.hard_must for row in rows)
    live = sum(row.live_must for row in rows)
    deferred = sum(row.deferred_must for row in rows)
    registered = sum(1 for row in inventory if row.classification == "REGISTERED")
    restatement = sum(1 for row in inventory if row.classification == "RESTATEMENT_OF")
    non_normative = sum(
        1 for row in inventory if row.classification == "NON_NORMATIVE_WITH_RATIONALE"
    )
    keyword_free_total = sum(len(keys) for keys in keyword_free.values())
    imbalance = unbalanced(rows)

    return "\n".join(
        [
            AUDIT_BEGIN,
            "",
            "Generated by `scripts/update_status.py` from the same data "
            "`tests/spec/test_m0a_coverage_audit.py` and "
            "`tests/spec/test_m0a_obligation_inventory.py` recompute.",
            "",
            "| | |",
            "|---|---|",
            "| Audit document | [`M0a.md`](docs/spec_coverage_audit/M0a.md) (rev 6) |",
            f"| Scope | §6–§16, all {len(spec_headings())} numbered headings counted |",
            f"| Sections reconciled | {len(rows)} |",
            f"| Hard MUSTs | **{hard}** = {live} registered live + {deferred} named deferred |",
            f"| Occurrences classified | **{len(inventory)}** = {registered} REGISTERED + "
            f"{restatement} RESTATEMENT_OF + {non_normative} NON_NORMATIVE_WITH_RATIONALE |",
            f"| Keyword-free statements declared | {keyword_free_total} |",
            "| Unaccounted hard obligations | "
            + (
                f"**{len(imbalance)} — the audit does not balance**"
                if imbalance
                else "0 (every delta is 0)"
            )
            + " |",
            f"| Requirement ↔ Test invariant | **{len(spec.requirements)} ↔ "
            f"{len(spec.test_ids)}** |",
            "",
            AUDIT_END,
        ]
    )


def _replace_block(text: str, begin: str, end: str, body: str) -> str:
    head, _, rest = text.partition(begin)
    _, _, tail = rest.partition(end)
    return f"{head}{body}{tail}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 if the file is out of date")
    parser.add_argument(
        "--requirements-only",
        action="store_true",
        help="skip the test inventory, which needs a whole-suite outcome report",
    )
    args = parser.parse_args()

    status_file = repo_root() / "IMPLEMENTATION_STATUS.md"
    original = status_file.read_text(encoding="utf-8")
    for begin, end in ((BEGIN, END), (TESTS_BEGIN, TESTS_END), (AUDIT_BEGIN, AUDIT_END)):
        if begin not in original or end not in original:
            print(f"error: {status_file.name} is missing the {begin} markers")
            return 2

    updated = _replace_block(original, BEGIN, END, build_table())
    # Derived from the registry and the audit data, so it needs no outcome report and is checked
    # in every job -- including the spec-conformance one.
    updated = _replace_block(updated, AUDIT_BEGIN, AUDIT_END, build_coverage_audit())

    if args.requirements_only:
        # For the spec-conformance job, which runs only `pytest tests/spec` and therefore has no
        # whole-suite report to derive the test inventory from.
        note = "requirement table and coverage-audit summary"
    else:
        try:
            updated = _replace_block(
                updated, TESTS_BEGIN, TESTS_END, build_test_inventory(load_collection())
            )
        except StaleReport as error:
            print(f"error: {error}")
            return 1
        note = "requirement table, coverage-audit summary and test inventory"

    if updated == original:
        print("IMPLEMENTATION_STATUS.md is up to date")
        return 0
    if args.check:
        print("error: IMPLEMENTATION_STATUS.md is stale; run scripts/update_status.py")
        return 1
    status_file.write_text(updated, encoding="utf-8")
    print(f"IMPLEMENTATION_STATUS.md {note} regenerated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
