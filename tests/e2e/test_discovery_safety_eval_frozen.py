"""The frozen out-of-catalog safety evidence still describes this tree.

`docs/audit/discovery-unknown-mechanism-safety-2026-11-04/evidence/` holds one complete run of
`scripts/discovery_safety_eval.py`. This test holds it to the code: the safety package's and the
script's sources must be the ones its manifest froze, the engine and the P3 evaluation tooling must
still be the frozen ones, the P3 force-fit must be the reproduced baseline, the recorded headline
numbers must be the counts of the recorded rows, and re-running a subset must reproduce the
recorded digests exactly. An edit to the gate fails here until the evidence is regenerated.

Offline and backend-free: no database, model, simulator or network.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from lab_brain.discovery.model import stable_digest
from lab_brain.discovery.protocol import DISCOVERY
from lab_brain.discovery_eval import held_out
from lab_brain.discovery_safety import evaluation as ev
from lab_brain.discovery_safety.model import SAFETY
from lab_brain.domains.silicon_photonics.discovery_catalog import (
    MOTIVATING_EXPERIMENT,
    ring_catalog,
)
from lab_brain.spec import repo_root

EVIDENCE = (
    repo_root() / "docs" / "audit" / "discovery-unknown-mechanism-safety-2026-11-04" / "evidence"
)
P3 = repo_root() / "docs" / "audit" / "discovery-independent-evaluation-2026-11-02" / "evidence"
REPORT = repo_root() / "docs" / "reports" / "discovery-unknown-mechanism-safety.md"


def _load(name: str, where: Path = EVIDENCE) -> Any:
    path = where / name
    assert path.exists(), f"{path} is missing; run scripts/discovery_safety_eval.py"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def manifest():
    return _load("manifest.json")


def test_the_manifest_froze_these_safety_sources_and_this_protocol(manifest):
    for relative, digest in manifest["safety_sources_sha256"].items():
        assert hashlib.sha256((repo_root() / relative).read_bytes()).hexdigest() == digest, relative
    package = repo_root() / "src" / "lab_brain" / "discovery_safety"
    frozen = {p for p in manifest["safety_sources_sha256"] if "discovery_safety/" in p}
    assert frozen == {p.resolve().relative_to(repo_root()).as_posix() for p in package.glob("*.py")}
    assert manifest["inputs"]["safety_protocol_digest"] == SAFETY.digest
    assert manifest["inputs"]["engine_protocol_digest"] == DISCOVERY.digest
    assert manifest["inputs_digest"] == stable_digest(manifest["inputs"])
    body = {k: v for k, v in manifest.items() if k not in ("manifest_sha256", "code_commit")}
    assert manifest["manifest_sha256"] == stable_digest(body)
    tooling = manifest["engine_and_evaluation_tooling"]
    assert tooling["engine_sources_match_frozen_manifest"] is True
    assert tooling["evaluation_sources_match_frozen_manifest"] is True
    assert manifest["evidence_class"].startswith("ENGINEERING EVIDENCE ONLY")


def test_the_p3_force_fit_was_reproduced_before_anything_new(manifest):
    repro = _load("reproduction.json")
    assert repro["reproduced"] is True
    recorded = _load("held_out.json", P3)["summary"]
    for budget in ("12", "24"):
        b2 = repro["B2"][budget]
        assert b2["digest_identical_to_recorded"] == b2["runs"] == 240
        assert b2["force_fit"] == b2["recorded_force_fit"]
        assert b2["force_fit"] == recorded[budget]["arms"]["B2"]["force_fit"]["k"]
    assert (repro["B2"]["12"]["force_fit"], repro["B2"]["24"]["force_fit"]) == (78, 92)


@pytest.mark.parametrize("name", ["held_out_p3_seeds", "held_out_new_seeds"])
def test_the_headline_is_the_count_of_the_recorded_rows(name):
    summary = _load(f"{name}.json")
    rows = _load(f"{name}_rows.json")
    for budget, arms in summary["headline_primary"].items():
        for arm, numbers in arms.items():
            mine = [r["arms"][arm][budget] for r in rows if not r["aliased"]]
            assert numbers["force_fit"]["k"] == sum(r["force_fit"] for r in mine)
            assert numbers["false_null"]["k"] == sum(r["false_null"] for r in mine)
            assert numbers["force_fit"]["n"] == len(mine) == 195
    assert summary["never_confirmed"] and summary["budget_never_exceeded"]


def test_the_safe_arm_force_fits_less_than_the_engine_at_every_recorded_budget():
    for name in ("held_out_p3_seeds", "held_out_new_seeds"):
        head = _load(f"{name}.json")["headline_primary"]
        for budget, arms in head.items():
            assert arms["B3"]["force_fit"]["k"] < arms["B2"]["force_fit"]["k"], (name, budget)
        b3 = [head[b]["B3"]["force_fit"]["k"] for b in ("12", "24", "48")]
        assert b3[0] >= b3[1] >= b3[2], (name, b3)


def test_rerunning_a_subset_reproduces_the_recorded_safe_arm_digests(manifest):
    catalog = ring_catalog()
    for name, key in (
        ("held_out_p3_seeds", "p3_held_out_worlds"),
        ("held_out_new_seeds", "new_held_out_worlds"),
    ):
        inputs = manifest["inputs"][key]
        worlds = held_out.held_out_worlds(
            catalog,
            seeds_per_class=inputs["seeds_per_class"],
            base_seed=inputs["base_seed"],
            protocol=DISCOVERY,
        )
        assert stable_digest(worlds) == inputs["specs_digest"]
        rows = {r["world_id"]: r for r in _load(f"{name}_rows.json")}
        chosen = worlds[:: inputs["seeds_per_class"] * 4]
        recorder = ev.SafeArmRecorder()
        for row in held_out.run_held_out(
            catalog,
            chosen,
            arms=(recorder.arm(),),
            budget=12,
            motivating_experiment=MOTIVATING_EXPERIMENT,
            protocol=DISCOVERY,
        ):
            assert rows[row.world_id]["arms"]["B3"]["12"]["digest"] == row.digest, row.world_id


def test_the_report_quotes_the_recorded_numbers():
    text = REPORT.read_text(encoding="utf-8")
    assert "ENGINEERING EVIDENCE ONLY" in text and "NOT PASSED" in text
    for name in ("held_out_p3_seeds", "held_out_new_seeds"):
        head = _load(f"{name}.json")["headline_primary"]
        for budget in ("12", "24", "48"):
            for arm in ("B2", "B3"):
                assert f"{head[budget][arm]['force_fit']['k']}/195" in text, (name, budget, arm)
