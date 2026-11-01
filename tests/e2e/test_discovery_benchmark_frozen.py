"""The frozen offline discovery benchmark still describes this tree.

`docs/audit/discovery-loop-offline-2026-11-01/evidence/` holds the manifest and results of one
complete run of `scripts/discovery_benchmark.py` on the EVALUATION seeds. This test holds them to the
code: the engine's and the scenario's source hashes, the catalog and world-spec digests, and every
arm's protocol digest must be what the manifest froze, and re-running the first world of each kind
must reproduce the recorded result digests exactly. An edit to the engine therefore fails here until
the evidence is regenerated -- which is the point of freezing it.

Offline and backend-free: no database, model, simulator or network.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from lab_brain.discovery import benchmark
from lab_brain.discovery.model import stable_digest
from lab_brain.domains.silicon_photonics.discovery_catalog import (
    EVALUATION_BASE_SEED,
    ring_scenario,
)
from lab_brain.spec import repo_root

EVIDENCE = repo_root() / "docs" / "audit" / "discovery-loop-offline-2026-11-01" / "evidence"
SEEDS_PER_KIND = 25


def _load(name: str) -> Any:
    path: Path = EVIDENCE / name
    assert path.exists(), f"{path} is missing; run scripts/discovery_benchmark.py"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def scenario():
    return ring_scenario(SEEDS_PER_KIND, base_seed=EVALUATION_BASE_SEED)


def test_the_manifest_froze_these_sources_this_catalog_and_these_worlds(scenario):
    manifest = _load("manifest.json")
    assert manifest["sources_sha256"] == benchmark.source_hashes(scenario, repo_root())
    assert manifest["catalog"]["digest"] == scenario.catalog.digest
    assert manifest["worlds"]["specs_digest"] == stable_digest(scenario.worlds)
    assert manifest["worlds"]["base_seed"] == EVALUATION_BASE_SEED
    frozen = {a["arm"]: a["protocol_digest"] for a in manifest["arms"]}
    current = {a.arm_id: a.protocol.digest for a in (*benchmark.ARMS, *benchmark.ABLATIONS)}
    assert frozen == current
    body = {k: v for k, v in manifest.items() if k not in ("manifest_sha256", "code_commit")}
    assert manifest["manifest_sha256"] == stable_digest(body)


def test_rerunning_the_first_world_of_each_kind_reproduces_the_recorded_results(scenario):
    rows = {row["world_id"]: row for row in _load("world_rows.json")}
    firsts = {}
    for world in scenario.worlds:
        firsts.setdefault(world.kind, world)
    subset = type(scenario)(**{**scenario.__dict__, "worlds": tuple(firsts.values())})
    bench = benchmark.run(subset, _load("manifest.json")["budget"], benchmark.ARMS)
    for run in bench.worlds:
        recorded = rows[run.world.world_id]["arms"]
        for result in run.results:
            assert recorded[result.arm]["digest"] == result.digest, (
                run.world.world_id,
                result.arm,
            )


def test_the_frozen_results_state_their_own_invariants():
    results = _load("results.json")
    assert results["never_confirmed"] is True
    assert results["budget_never_exceeded"] is True
    assert results["matched"]["same_worlds_seeds_and_budget_for_every_arm"] is True
    assert results["reproducibility"]["two_runs_identical"] is True
    assert (
        results["reproducibility"]["results_identical"]
        == results["reproducibility"]["results_compared"]
    )
    for arm in ("B0", "B1", "B2"):
        assert results["main"]["arms"][arm]["correct_outcome"]["n"] == 8 * SEEDS_PER_KIND
