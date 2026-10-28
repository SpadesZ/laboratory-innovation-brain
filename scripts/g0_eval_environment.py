"""Evaluator: record, or check, the environment a blind evaluation runs in.

    python scripts/g0_eval_environment.py capture --model-endpoint http://127.0.0.1:11434/v1 \
        --model-id qwen2.5:7b --model-digest sha256:<local digest> --out environment.json
    python scripts/g0_eval_environment.py verify environment.json --model-endpoint ... \
        --model-id ... --model-digest ...

`capture` refuses a dirty working tree and a model not served by this machine (the zero-cost
protocol); `verify` exits 1 and lists every difference when the environment is not the one recorded.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from lab_brain.evaluation.environment import EnvironmentRefused, capture, verify

ROOT = Path(__file__).resolve().parents[1]


def _apply_order() -> tuple[str, ...]:
    sys.path.insert(0, str(ROOT / "scripts"))
    from migrate import APPLY_ORDER  # type: ignore[import-not-found]

    return tuple(APPLY_ORDER)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=("capture", "verify"))
    parser.add_argument("recorded", nargs="?")
    parser.add_argument("--model-endpoint", required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--model-digest", required=True)
    parser.add_argument("--allow-remote", action="store_true", help="an Owner-authorized paid run")
    parser.add_argument("--allow-dirty", action="store_true", help="a dry run that proves nothing")
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    try:
        now = capture(
            ROOT,
            _apply_order(),
            endpoint=args.model_endpoint,
            model_id=args.model_id,
            model_digest=args.model_digest,
            allow_remote=args.allow_remote,
            allow_dirty=args.allow_dirty,
        )
    except EnvironmentRefused as refused:
        print(f"refused: {refused}", file=sys.stderr)
        return 1
    if args.mode == "capture":
        text = json.dumps(now, indent=1, sort_keys=True) + "\n"
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
        print(now["environment_sha256"])
        return 0
    if not args.recorded:
        parser.error("verify needs the recorded environment.json")
    drift = verify(json.loads(Path(args.recorded).read_text(encoding="utf-8")), now)
    for line in drift:
        print(f"drift: {line}", file=sys.stderr)
    if not drift:
        print("the environment is the one recorded")
    return 1 if drift else 0


if __name__ == "__main__":
    raise SystemExit(main())
