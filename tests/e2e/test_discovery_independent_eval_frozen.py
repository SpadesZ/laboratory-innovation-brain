"""The frozen discovery evaluation refinements still describe this tree.

`docs/audit/discovery-independent-evaluation-2026-11-02/evidence/` holds one complete run of
`scripts/discovery_independent_eval.py`: realized-cost curves, the held-out-class experiment and the
hidden-world scaffold demonstration. This test holds them to the code: the engine's sources must be
the ones the 2026-11-01 manifest froze, the evaluation tooling's sources and inputs must be what this
manifest froze, and re-running a subset must reproduce the recorded digests exactly. An edit to the
engine, the evaluation package, the script or the example fails here until the evidence is
regenerated -- the point of freezing it.

Offline and backend-free: no database, model, simulator or network.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from lab_brain.discovery import benchmark
from lab_brain.discovery.model import stable_digest
from lab_brain.discovery.protocol import DISCOVERY
from lab_brain.discovery_eval import curves, held_out
from lab_brain.domains.silicon_photonics.discovery_catalog import (
    MOTIVATING_EXPERIMENT,
    ring_scenario,
)
from lab_brain.spec import repo_root

EVIDENCE = (
    repo_root() / "docs" / "audit" / "discovery-independent-evaluation-2026-11-02" / "evidence"
)
FROZEN_ENGINE = repo_root() / "docs" / "audit" / "discovery-loop-offline-2026-11-01" / "evidence"


def _load(name: str, where: Path = EVIDENCE) -> Any:
    path = where / name
    assert path.exists(), f"{path} is missing; run scripts/discovery_independent_eval.py"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def manifest():
    return _load("manifest.json")


@pytest.fixture(scope="module")
def scenario(manifest):
    worlds = manifest["inputs"]["curve_worlds"]
    return ring_scenario(worlds["seeds_per_kind"], base_seed=worlds["base_seed"])


def test_the_engine_is_the_one_the_2026_11_01_manifest_froze(manifest, scenario):
    frozen = _load("manifest.json", FROZEN_ENGINE)
    current = benchmark.source_hashes(scenario, repo_root())
    assert manifest["engine"]["sources_sha256"] == current == frozen["sources_sha256"]
    assert manifest["engine"]["sources_match_frozen_manifest"] is True
    assert manifest["engine"]["frozen_manifest_sha256"] == frozen["manifest_sha256"]


def test_the_manifest_froze_these_evaluation_sources_and_inputs(manifest, scenario):
    for relative, digest in manifest["evaluation_sources_sha256"].items():
        path = repo_root() / relative
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, relative
    package = repo_root() / "src" / "lab_brain" / "discovery_eval"
    frozen_files = {p for p in manifest["evaluation_sources_sha256"] if "discovery_eval/" in p}
    assert frozen_files == {
        p.resolve().relative_to(repo_root()).as_posix() for p in package.glob("*.py")
    }
    inputs = manifest["inputs"]
    assert inputs["catalog"]["digest"] == scenario.catalog.digest
    assert inputs["curve_worlds"]["specs_digest"] == stable_digest(scenario.worlds)
    worlds = held_out.held_out_worlds(
        scenario.catalog,
        seeds_per_class=inputs["held_out_worlds"]["seeds_per_class"],
        base_seed=inputs["held_out_worlds"]["base_seed"],
        protocol=DISCOVERY,
    )
    assert inputs["held_out_worlds"]["specs_digest"] == stable_digest(worlds)
    assert {a["arm"]: a["protocol_digest"] for a in inputs["arms"]} == {
        a.arm_id: a.protocol.digest for a in benchmark.ARMS
    }
    assert manifest["inputs_digest"] == stable_digest(inputs)
    body = {k: v for k, v in manifest.items() if k not in ("manifest_sha256", "code_commit")}
    assert manifest["manifest_sha256"] == stable_digest(body)


def test_rerunning_the_first_world_of_each_kind_reproduces_every_cap(manifest, scenario):
    rows = {row["world_id"]: row for row in _load("cost_curve_rows.json")}
    firsts: dict[str, Any] = {}
    for world in scenario.worlds:
        firsts.setdefault(world.kind, world)
    subset = type(scenario)(**{**scenario.__dict__, "worlds": tuple(firsts.values())})
    caps = tuple(manifest["inputs"]["caps"])
    for row in curves.run_grid(subset, caps, benchmark.ARMS):
        recorded = rows[row.world_id]["arms"][row.arm][str(row.cap)]
        assert recorded["digest"] == row.digest, (row.world_id, row.arm, row.cap)
        assert recorded["spent"] == row.spent <= row.cap


def test_rerunning_held_out_worlds_reproduces_the_recorded_results(manifest, scenario):
    rows = {row["world_id"]: row for row in _load("held_out_rows.json")}
    inputs = manifest["inputs"]["held_out_worlds"]
    worlds = held_out.held_out_worlds(
        scenario.catalog,
        seeds_per_class=inputs["seeds_per_class"],
        base_seed=inputs["base_seed"],
        protocol=DISCOVERY,
    )
    chosen = worlds[:: inputs["seeds_per_class"] * 4]
    budget = manifest["inputs"]["held_out_budgets"][0]
    for row in held_out.run_held_out(
        scenario.catalog,
        chosen,
        arms=benchmark.ARMS,
        budget=budget,
        motivating_experiment=MOTIVATING_EXPERIMENT,
        protocol=DISCOVERY,
    ):
        assert rows[row.world_id]["arms"][row.arm][str(budget)]["digest"] == row.digest


def test_the_frozen_results_state_their_own_invariants():
    check = _load("cross_check.json")
    assert check["engine_sources_match_frozen_manifest"] is True
    assert check["run_digest_matches"] is True and check["correct_matches"] is True
    costs = _load("cost_curves.json")
    invariants = costs["invariants"]
    assert invariants["realized_within_cap"] and invariants["meter_equals_engine_report"]
    assert invariants["unconstrained_runs_identical_at_larger_caps"]["violations"] == []
    assert invariants["unconstrained_share_non_decreasing"] is True
    assert costs["determinism"]["identical"] == costs["determinism"]["compared"] > 0
    assert costs["never_confirmed"] is True
    held = _load("held_out.json")
    assert held["never_confirmed"] is True and held["budget_never_exceeded"] is True
    assert "SAME AUTHOR" in held["author_note"]
    scaffold = _load("scaffold_example.json")
    assert scaffold["notice"].startswith("EXAMPLE ONLY")
    assert set(scaffold["refusals_demonstrated"]) == {
        "example_used_as_hidden_set",
        "public_part_altered_after_commitment",
        "removal_reason_names_the_truth",
    }
