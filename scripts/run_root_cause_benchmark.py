"""Generate the VS-SP-001 root-cause benchmark report (M4's exit gate, §26.1, VER-001).

Writes ``benchmarks/root_cause_benchmark_report.md`` from the locked fixture, running every case
under M4's least-cost planner and the simulate-first baseline through the same loop, on PostgreSQL
-- the governed belief path M1 built is PostgreSQL-only, and the benchmark runs the real one.

    python scripts/run_root_cause_benchmark.py --disposable            # regenerate the report
    python scripts/run_root_cause_benchmark.py --disposable --check    # fail if it is stale
    python scripts/run_root_cause_benchmark.py --disposable --candidate  # benchmark 1.1.0 under
                                                    # the candidate declarations (not active)

THE DATABASE IS WIPED, CASE BY CASE. Each episode starts from an empty database (the same reset
the PostgreSQL test fixture performs), because cases must not see each other and the stores run in
autocommit as production does. So the script refuses to run without ``--disposable``: point
``LAB_BRAIN_DATABASE_URL`` (or ``--database-url``) at a freshly migrated scratch database. In CI the
check is ``tests/e2e/test_root_cause_benchmark_postgres.py`` in the backend job, against the test
database.

``--check`` makes the report an artifact rather than a snapshot. The pass conditions live in
``lab_brain.verification.root_cause_benchmark``; this script publishes, it does not judge.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from lab_brain.verification.root_cause_benchmark import render_report  # noqa: E402
from tests.postgres_fixtures import reset_database  # noqa: E402
from tests.vertical_fixtures import (  # noqa: E402
    FIXTURE_PATH,
    candidate_declarations,
    run_benchmark,
)

REPORT_PATH = ROOT / "benchmarks" / "root_cause_benchmark_report.md"
#: Benchmark 1.1.0 under the candidate declaration version 1.1.0, which the product does not
#: register: evidence for the owner's decision, not a gate (see `product.CANDIDATE_VERSION`).
CANDIDATE_FIXTURE = ROOT / "fixtures" / "vertical" / "sp_rs_root_cause_benchmark_1.1.0.json"
CANDIDATE_REPORT = ROOT / "benchmarks" / "root_cause_benchmark_report_1.1.0_candidate.md"
CANDIDATE_CHECK = "tests/e2e/test_sp_candidate_declarations_postgres.py"


def build_report(connection: object) -> str:
    run = run_benchmark(connection, reset_database)
    return render_report(run, FIXTURE_PATH.relative_to(ROOT).as_posix()) + "\n"


def build_candidate_report(connection: object) -> str:
    candidate, registered = candidate_declarations()
    run = run_benchmark(
        connection,
        reset_database,
        path=CANDIDATE_FIXTURE,
        declarations=candidate,
        registered=registered,
    )
    return (
        render_report(
            run,
            CANDIDATE_FIXTURE.relative_to(ROOT).as_posix(),
            title="VS-SP-001 root-cause benchmark 1.1.0 under CANDIDATE declarations (not active)",
            checked_by=CANDIDATE_CHECK,
            declarations=f"{candidate.ref} ({candidate.digest}), registered beside 1.0.0",
        )
        + "\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if the report is stale")
    parser.add_argument("--database-url", default=os.environ.get("LAB_BRAIN_DATABASE_URL", ""))
    parser.add_argument(
        "--disposable",
        action="store_true",
        help="confirm the database may be wiped (every table is truncated between cases)",
    )
    parser.add_argument(
        "--candidate",
        action="store_true",
        help="benchmark 1.1.0 under the candidate declarations, into its own report",
    )
    args = parser.parse_args(argv)
    if not args.disposable:
        print("refusing: this benchmark truncates every table; pass --disposable for a scratch DB")
        return 2
    if not args.database_url:
        print("refusing: set LAB_BRAIN_DATABASE_URL or pass --database-url")
        return 2

    import psycopg

    path = CANDIDATE_REPORT if args.candidate else REPORT_PATH
    with psycopg.connect(args.database_url, autocommit=True) as connection:
        report = (build_candidate_report if args.candidate else build_report)(connection)
    if args.check:
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current.replace("\r\n", "\n") != report:
            print(f"FAIL  {path.relative_to(ROOT)} is stale; regenerate it")
            return 1
        print(f"OK    {path.relative_to(ROOT)} is current")
        return 0
    path.write_text(report, encoding="utf-8", newline="\n")
    print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
