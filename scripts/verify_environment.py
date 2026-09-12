"""Report what this environment can and cannot verify.

AGT-007 requires the core suite to pass with no PostgreSQL, no Lumerical seat and no network.
The risk that creates is the opposite one: a green run that silently skipped everything that
touches a real backend. This script names what is unavailable so IMPLEMENTATION_STATUS.md can
say so honestly instead of implying full coverage.

Usage:
    python scripts/verify_environment.py
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from lab_brain.spec import load_milestones, load_registry, load_spec

OK = "ok"
ABSENT = "absent"


def _check_module(name: str) -> tuple[str, str]:
    return (OK, name) if importlib.util.find_spec(name) else (ABSENT, name)


def _check_docker() -> tuple[str, str]:
    if not shutil.which("docker"):
        return ABSENT, "docker not on PATH"
    try:
        result = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return ABSENT, f"docker present but not usable: {exc}"
    if result.returncode != 0:
        return ABSENT, "docker present, daemon not responding"
    return OK, f"docker server {result.stdout.strip()}"


def _check_postgres() -> tuple[str, str]:
    url = os.environ.get("LAB_BRAIN_DATABASE_URL")
    if not url:
        return ABSENT, "LAB_BRAIN_DATABASE_URL unset"
    if not importlib.util.find_spec("psycopg"):
        return ABSENT, "psycopg not installed"
    import psycopg

    try:
        with psycopg.connect(url, connect_timeout=5) as conn:
            row = conn.execute("select version()").fetchone()
        return OK, str(row[0]).split(",")[0] if row else OK
    except Exception as exc:
        # Broad by intent: this reports reachability, it does not handle failures.
        return ABSENT, f"connect failed: {type(exc).__name__}"


def main() -> int:
    print("Laboratory Innovation Brain — environment report")
    print(f"  python            : {sys.version.split()[0]}")

    spec = load_spec()
    registry = load_registry()
    catalog = load_milestones()
    print(f"  spec              : v{spec.version} at {spec.path.name}")
    print(
        f"  spec tables       : {len(spec.requirements)} requirements / {len(spec.test_ids)} tests"
    )
    print(f"  registry          : {len(registry.statements)} normative statements")
    active = [m.milestone_id for m in catalog.milestones if m.status == "IN_PROGRESS"]
    print(f"  current milestone : {', '.join(active) or 'none marked IN_PROGRESS'}")

    print("\nBackends:")
    for label, (state, detail) in {
        "docker": _check_docker(),
        "postgres": _check_postgres(),
        "psycopg": _check_module("psycopg"),
        "pydantic": _check_module("pydantic"),
    }.items():
        print(f"  {label:<18}: {state:<7} {detail}")

    print("\nOpt-in test gates (unset = those tests are deselected):")
    for var in (
        "LAB_BRAIN_TEST_POSTGRES",
        "LAB_BRAIN_TEST_LUMERICAL",
        "LAB_BRAIN_TEST_NETWORK",
    ):
        print(f"  {var:<26}: {os.environ.get(var) or '(unset)'}")

    print("\nA bare `pytest` run proves core logic only. Anything requiring a real backend")
    print("is deselected, not passed — report it that way in IMPLEMENTATION_STATUS.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
