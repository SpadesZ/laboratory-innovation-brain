"""Generate the T-LLM-002 debate benchmark report (LLM-002, §15.4, §26).

Writes ``benchmarks/debate_benchmark_report.md`` from the locked fixture, running every case
under the DEBATE, BASELINE and NO_INVERTED conditions with the same deterministic reasoner, and
reading the calibrated BenchmarkPolicy off the result.

    python scripts/run_debate_benchmark.py            # regenerate the report
    python scripts/run_debate_benchmark.py --check    # fail if the committed report is stale

``--check`` makes the report an artifact rather than a snapshot: a change to the debate that moves
any round count, metric or the calibrated threshold fails it, and the diff shows what moved. The
pass conditions themselves live in ``tests/contract/test_debate_benchmark.py``; this script
publishes, it does not judge.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from lab_brain.cognition.debate_benchmark import calibrate, evaluate, render_report  # noqa: E402
from tests.debate_fixtures import (  # noqa: E402
    CALIBRATED_AT,
    CALIBRATION_POLICY_ID,
    CALIBRATION_VERSION,
    DOMAIN,
    FIXTURE_PATH,
    benchmark_runner,
    fixture_digest,
    load_fixture,
)

REPORT_PATH = ROOT / "benchmarks" / "debate_benchmark_report.md"


def build_report() -> str:
    run = evaluate(load_fixture(), benchmark_runner(), fixture_digest=fixture_digest())
    policy = calibrate(
        run,
        domain=DOMAIN,
        policy_id=CALIBRATION_POLICY_ID,
        version=CALIBRATION_VERSION,
        calibrated_at=CALIBRATED_AT,
    )
    return render_report(run, policy, FIXTURE_PATH.relative_to(ROOT).as_posix())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if the report is stale")
    args = parser.parse_args(argv)
    report = build_report()
    if args.check:
        current = REPORT_PATH.read_text(encoding="utf-8") if REPORT_PATH.exists() else ""
        if current.replace("\r\n", "\n") != report:
            print(
                f"{REPORT_PATH.relative_to(ROOT)} is stale; run scripts/run_debate_benchmark.py",
                file=sys.stderr,
            )
            return 1
        print(f"{REPORT_PATH.relative_to(ROOT)} is current")
        return 0
    REPORT_PATH.write_text(report, encoding="utf-8", newline="\n")
    print(f"wrote {REPORT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
