"""Evaluator: reveal the sealed truth and score a run's outputs against the frozen manifest.

    python scripts/g0_eval_score.py --manifest <manifest.json> --outputs <outputs.json> \
        [--truth <outside-repo/truth.sealed.json>] [--json <score.json>] \
        [--purpose acceptance --environment-verification <verification.json>]

`--purpose acceptance` (a score a gate may rely on) also refuses unless the runner verified the
environment before and after the run AND the evaluator's own verification record
(`g0_eval_environment.py verify --verifier <id> --out verification.json`) shows the same
environment with no difference, a clean tree and a model digest the server measured. The default,
`diagnostic`, scores whatever ran and prints that it is not an acceptance result.

Refuses (exit 2, nothing scored) on freeze drift, a scorer source change, outputs bound to another
manifest or naming unfrozen cases, a truth reveal that does not match its commitment, or
contamination under the `fail` policy. Otherwise every frozen case is in the denominator, with
its status; each metric prints n, k, rate, Wilson 95% and the seeded bootstrap 95% interval, plus
the conservative figure that counts exclusions as failures.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from lab_brain.evaluation.manifest import ScoringRefused, score_run
from lab_brain.evaluation.sealing import load_sealed_truth, truth_location

ROOT = Path(__file__).resolve().parents[1]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--outputs", required=True)
    parser.add_argument("--truth")
    parser.add_argument("--allow-truth-in-repo", action="store_true", help="synthetic tests only")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--json")
    parser.add_argument("--purpose", choices=("diagnostic", "acceptance"), default="diagnostic")
    parser.add_argument("--environment-verification")
    args = parser.parse_args(argv)
    truth = load_sealed_truth(
        truth_location(args.truth, os.environ, repo=ROOT, allow_in_repo=args.allow_truth_in_repo)
    )
    try:
        result = score_run(
            manifest=json.loads(Path(args.manifest).read_text(encoding="utf-8")),
            root=Path(args.root),
            outputs=json.loads(Path(args.outputs).read_text(encoding="utf-8")),
            truth=truth,
            purpose=args.purpose.upper(),
            environment_verification=(
                json.loads(Path(args.environment_verification).read_text(encoding="utf-8"))
                if args.environment_verification
                else None
            ),
        )
    except ScoringRefused as exc:
        sys.stderr.write(f"REFUSED: {exc}\n")
        return 2
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    summary = result["summary"]
    sys.stdout.write(f"{result['standing']}\n")
    label = "SYNTHETIC " if result["synthetic"] else ""
    sys.stdout.write(
        f"{label}suite {result['suite']}: {summary['frozen_cases']} frozen cases "
        f"{summary['status_counts']}; bootstrap seed {result['bootstrap_seed']}\n"
    )
    for name, m in summary["metrics"].items():
        c = m["conservative"]
        sys.stdout.write(
            f"{name}: k={m['k']} n={m['n']} rate={m['rate']} wilson95={m['wilson95']} "
            f"bootstrap95={m['bootstrap95']} excluded={m['excluded']} "
            f"| conservative k={c['k']} n={c['n']} rate={c['rate']}\n"
        )
    for item in summary["excluded"]:
        sys.stdout.write(f"EXCLUDED {item['case_id']}: {item['reason']}\n")
    for item in summary["not_completed"]:
        sys.stdout.write(f"{item['status']} {item['case_id']}: {item['reason']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
