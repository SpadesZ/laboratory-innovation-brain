"""The blind evaluation's environment manifest: reproducible, zero-cost, drift detected."""

from __future__ import annotations

import copy
import subprocess
from pathlib import Path

import pytest

from lab_brain.evaluation import environment
from lab_brain.evaluation.environment import EnvironmentRefused, capture, environment_hash, verify

REPO = Path(__file__).resolve().parents[2]
LOCAL = {
    "endpoint": "http://127.0.0.1:11434/v1",
    "model_id": "qwen2.5:7b",
    "model_digest": "sha256:" + "a" * 64,
}


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "r"
    (root / "migrations").mkdir(parents=True)
    (root / "migrations" / "001_a.sql").write_text("SELECT 1;\n")
    (root / "migrations" / "002_b.sql").write_text("SELECT 2;\n")
    for args in (
        ["init", "-q"],
        ["-c", "user.name=T", "-c", "user.email=t@example.com", "add", "-A"],
        ["-c", "user.name=T", "-c", "user.email=t@example.com", "commit", "-q", "-m", "x"],
    ):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    return root


ORDER = ("001_a.sql", "002_b.sql")


def test_capture_pins_code_schema_libraries_scorer_and_model(tmp_path):
    root = _repo(tmp_path)
    m = capture(root, ORDER, **LOCAL)
    assert m["code"]["clean"] and len(m["code"]["commit"]) == 40
    assert [line.split()[0] for line in m["schema"]["migrations"]] == list(ORDER)
    assert m["libraries"]["distributions"] and m["scorer"]["sources"]
    assert m["model"]["zero_cost"] is True
    assert m["environment_sha256"] == environment_hash(m)
    assert verify(m, capture(root, ORDER, **LOCAL)) == []


def test_a_remote_model_leaves_the_zero_cost_protocol_unless_authorized(tmp_path):
    root = _repo(tmp_path)
    remote = {**LOCAL, "endpoint": "https://generativelanguage.googleapis.com/v1beta/openai"}
    with pytest.raises(EnvironmentRefused, match="zero-cost"):
        capture(root, ORDER, **remote)
    paid = capture(root, ORDER, allow_remote=True, **remote)
    assert paid["model"]["zero_cost"] is False


def test_a_dirty_tree_is_refused_unless_recorded_as_a_dry_run(tmp_path):
    root = _repo(tmp_path)
    (root / "migrations" / "001_a.sql").write_text("SELECT 'edited';\n")
    with pytest.raises(EnvironmentRefused, match="uncommitted"):
        capture(root, ORDER, **LOCAL)
    assert capture(root, ORDER, allow_dirty=True, **LOCAL)["code"]["clean"] is False


def test_every_kind_of_drift_is_reported(tmp_path):
    root = _repo(tmp_path)
    recorded = capture(root, ORDER, **LOCAL)
    (root / "migrations" / "002_b.sql").write_text("SELECT 3;\n")
    now = capture(root, ORDER, allow_dirty=True, **{**LOCAL, "model_digest": "sha256:" + "b" * 64})
    drift = " ".join(verify(recorded, now))
    assert "schema" in drift and "model digest" in drift
    tampered = copy.deepcopy(recorded)
    tampered["scorer"]["version"] = "9.9.9"
    assert verify(tampered, recorded) == [
        "the recorded manifest does not hash to its own environment_sha256"
    ]


def test_a_model_without_a_digest_is_refused(tmp_path):
    with pytest.raises(EnvironmentRefused, match="digest"):
        environment.model_state(
            endpoint=LOCAL["endpoint"], model_id="m", model_digest="", allow_remote=False
        )


def test_the_script_captures_this_repository(tmp_path):
    out = tmp_path / "env.json"
    result = subprocess.run(
        [
            str(REPO / ".venv/bin/python"),
            str(REPO / "scripts/g0_eval_environment.py"),
            "capture",
            "--model-endpoint", LOCAL["endpoint"],
            "--model-id", LOCAL["model_id"],
            "--model-digest", LOCAL["model_digest"],
            "--allow-dirty",
            "--out", str(out),
        ],
        capture_output=True,
        text=True,
    )  # fmt: skip
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().startswith("sha256:") and out.is_file()
