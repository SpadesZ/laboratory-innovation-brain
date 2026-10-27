"""Evaluator: report contamination of a holdout package against dev packages and the exposed cases.

    python scripts/g0_eval_check_contamination.py --package <holdout/generator-package.json> \
        [--reference <dev/generator-package.json> ...] [--no-exposed-screening] \
        [--truth <outside-repo/truth.sealed.json>] [--json <report.json>]

Reports exact and n-gram text overlap, source/device family overlap and duplicated experimental
units. With `--truth` (or `$LAB_BRAIN_G0_EVAL_TRUTH`) the secret truth strings are compared too;
the report names fields and reference units, never the matched text. Exit status 1 when anything
was found -- whether that excludes cases or fails the evaluation is decided by the frozen
protocol's `contamination_policy` at freeze time, not here.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from lab_brain.evaluation import contamination
from lab_brain.evaluation.packages import load_generator_package
from lab_brain.evaluation.sealing import TRUTH_ENV, load_sealed_truth, truth_location

ROOT = Path(__file__).resolve().parents[1]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--package", required=True)
    parser.add_argument("--reference", action="append", default=[])
    parser.add_argument("--no-exposed-screening", action="store_true")
    parser.add_argument("--truth")
    parser.add_argument("--allow-truth-in-repo", action="store_true", help="synthetic tests only")
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--min-chars", type=int, default=20)
    parser.add_argument("--ngram", type=int, default=8)
    parser.add_argument("--near-threshold-permille", type=int, default=500)
    parser.add_argument("--json")
    args = parser.parse_args(argv)
    truth = None
    if args.truth or os.environ.get(TRUTH_ENV):
        path = truth_location(
            args.truth, os.environ, repo=ROOT, allow_in_repo=args.allow_truth_in_repo
        )
        truth = load_sealed_truth(path).truth()
    holdout = contamination.units_from_package(
        load_generator_package(Path(args.package)), "holdout", truth
    )
    reference: list[contamination.Unit] = []
    for ref in args.reference:
        reference.extend(
            contamination.units_from_package(load_generator_package(Path(ref)), f"reference:{ref}")
        )
    if not args.no_exposed_screening:
        reference.extend(contamination.units_from_exposed_screening(Path(args.root)))
    findings = contamination.check(
        holdout,
        reference,
        min_chars=args.min_chars,
        ngram=args.ngram,
        near_threshold_permille=args.near_threshold_permille,
    )
    result = contamination.report(findings)
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    for f in findings:
        sys.stdout.write(f"{f.case_id}\t{f.kind}\t{f.field}\t{f.reference}\t{f.score}\n")
    sys.stdout.write(f"{len(findings)} findings; contaminated: {result['contaminated_cases']}\n")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
