"""Evaluator: freeze the protocol manifest BEFORE any run.

    python scripts/g0_eval_freeze.py --protocol <protocol.json> --package <generator-package.json> \
        --commitments <commitments.json> [--reference <dev package> ...] \
        [--truth <outside-repo/truth.sealed.json>] [--exclude CASE=REASON ...] --out <manifest.json>

Freezes the protocol version, the scorer id/version and source hashes, every input file's hash,
the case list, the truth commitments, the contamination findings and the exclusions. Give the
generator side the package and the printed manifest hash; nothing else.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from lab_brain.evaluation.manifest import freeze
from lab_brain.evaluation.sealing import TRUTH_ENV, load_sealed_truth, truth_location

ROOT = Path(__file__).resolve().parents[1]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--protocol", required=True)
    parser.add_argument("--package", required=True)
    parser.add_argument("--commitments", required=True)
    parser.add_argument("--reference", action="append", default=[])
    parser.add_argument("--no-exposed-screening", action="store_true")
    parser.add_argument("--truth")
    parser.add_argument("--allow-truth-in-repo", action="store_true", help="synthetic tests only")
    parser.add_argument("--exclude", action="append", default=[], metavar="CASE=REASON")
    parser.add_argument(
        "--root", default=str(ROOT), help="paths in the manifest are relative to it"
    )
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    truth = None
    if args.truth or os.environ.get(TRUTH_ENV):
        truth = load_sealed_truth(
            truth_location(
                args.truth, os.environ, repo=ROOT, allow_in_repo=args.allow_truth_in_repo
            )
        )
    declared = dict(item.split("=", 1) for item in args.exclude)
    manifest = freeze(
        root=Path(args.root),
        protocol_path=Path(args.protocol),
        package_path=Path(args.package),
        commitments=json.loads(Path(args.commitments).read_text(encoding="utf-8")),
        references=[Path(r) for r in args.reference],
        include_exposed_screening=not args.no_exposed_screening,
        truth=truth,
        declared_exclusions=declared,
    )
    Path(args.out).write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    found = manifest["contamination"]["findings"]
    sys.stdout.write(
        f"frozen {len(manifest['cases'])} cases; {len(found)} contamination findings; "
        f"{len(manifest['exclusions'])} exclusions\nmanifest_sha256 {manifest['manifest_sha256']}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
