"""Evaluator: record, or check, the environment a blind evaluation runs in.

    python scripts/g0_eval_environment.py capture --model-endpoint http://127.0.0.1:11434/v1 \
        --model-id qwen2.5:7b --model-digest sha256:<local digest> --out environment.json
    python scripts/g0_eval_environment.py verify environment.json --model-endpoint ... \
        --model-id ... --model-digest ...

`capture` refuses a dirty working tree, a model not served by this machine (the zero-cost
protocol), and a declared digest the local model server contradicts; `verify` exits 1 and lists
every difference when the environment is not the one recorded. `--database-url` (default
`LAB_BRAIN_DATABASE_URL`) records the migrations actually applied to the evaluation's database.
"""

from __future__ import annotations

import argparse
import json
import os
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
    parser.add_argument("--database-url", default=os.environ.get("LAB_BRAIN_DATABASE_URL", ""))
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    connection = None
    try:
        if args.database_url:
            import psycopg

            connection = psycopg.connect(args.database_url, connect_timeout=10)
        now = capture(
            ROOT,
            _apply_order(),
            endpoint=args.model_endpoint,
            model_id=args.model_id,
            model_digest=args.model_digest,
            allow_remote=args.allow_remote,
            allow_dirty=args.allow_dirty,
            connection=connection,
        )
    except EnvironmentRefused as refused:
        print(f"refused: {refused}", file=sys.stderr)
        return 1
    finally:
        if connection is not None:
            connection.close()
    if now["model"]["digest_source"] == "declared":
        print(
            "note: the model server did not report a digest; the model digest is declared, "
            "not measured",
            file=sys.stderr,
        )
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
