"""Evaluator: seal a truth file (fresh salt per case) and write its public commitments.

    python scripts/g0_eval_seal.py --truth <outside-repo/truth.json> \
        --sealed-out <outside-repo/truth.sealed.json> --commitments-out <commitments.json>

The input is a `g0-eval/evaluator-truth@1` document whose cases are `{"truth": {...}}`. The sealed
output (truth + salts) belongs OUTSIDE the repository and is refused inside it; the commitments
file holds one hash per case and their root, and is the only part that may be published.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from lab_brain.evaluation.sealing import (
    commitments_document,
    load_sealed_truth,
    seal,
    truth_location,
)

ROOT = Path(__file__).resolve().parents[1]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--truth", help="unsealed truth (or $LAB_BRAIN_G0_EVAL_TRUTH)")
    parser.add_argument("--sealed-out", required=True)
    parser.add_argument("--commitments-out", required=True)
    parser.add_argument("--allow-truth-in-repo", action="store_true", help="synthetic tests only")
    args = parser.parse_args(argv)
    source = truth_location(
        args.truth, os.environ, repo=ROOT, allow_in_repo=args.allow_truth_in_repo
    )
    sealed_out = truth_location(
        args.sealed_out, {}, repo=ROOT, allow_in_repo=args.allow_truth_in_repo
    )
    sealed = seal(json.loads(source.read_text(encoding="utf-8")))
    sealed_out.write_text(json.dumps(sealed, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    public = commitments_document(load_sealed_truth(sealed_out))
    Path(args.commitments_out).write_text(json.dumps(public, indent=1) + "\n", encoding="utf-8")
    sys.stdout.write(f"sealed {len(public['cases'])} cases; commitment root {public['root']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
