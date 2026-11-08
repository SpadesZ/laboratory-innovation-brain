"""The frozen safety v1.1 evidence still describes this tree.

`docs/audit/discovery-safety-v1.1-2026-11-04/evidence/` holds one complete run of
`scripts/discovery_safety_v11_eval.py`. This test holds it to the code: the v1.1 package's and the
script's sources must be the ones its manifest froze (and the ones of the design-freeze commit), the
protocol and plan digests must be today's, every recorded table must be the count of the recorded
rows, the v1.0 digests must have been reproduced, a re-run subset must reproduce the recorded B4
digests, and the report must quote the recorded numbers.

Interpreter-independent on purpose: it never compares the recorded interpreter with the running
one (that is `--check`'s job, which refuses an unverified interpreter explicitly). Offline and
backend-free.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from lab_brain.discovery.model import stable_digest
from lab_brain.discovery.protocol import DISCOVERY
from lab_brain.discovery_eval import held_out
from lab_brain.discovery_safety.v11 import evaluation as ev
from lab_brain.discovery_safety.v11.model import (
    HELD_OUT_V11,
    PLAN,
    PREVIOUSLY_INSPECTED,
    SAFETY_V11,
)
from lab_brain.domains.silicon_photonics.discovery_catalog import (
    MOTIVATING_EXPERIMENT,
    ring_catalog,
)
from lab_brain.spec import repo_root

AUDIT = repo_root() / "docs" / "audit" / "discovery-safety-v1.1-2026-11-04"
EVIDENCE = AUDIT / "evidence"
REPORT = repo_root() / "docs" / "reports" / "discovery-safety-v1.1.md"
FRESH = PLAN.held_out[0].base_seed


def _text(name: str) -> str:
    path = EVIDENCE / name
    assert path.exists(), f"{path} is missing; run scripts/discovery_safety_v11_eval.py"
    return path.read_text(encoding="utf-8")


def _load(name: str) -> Any:
    return json.loads(_text(name))


@pytest.fixture(scope="module")
def manifest() -> Any:
    return _load("manifest.json")


@pytest.fixture(scope="module")
def results() -> Any:
    return _load("results.json")


def test_the_manifest_froze_these_sources_this_protocol_and_this_plan(manifest):
    for relative, digest in manifest["v11_sources_sha256"].items():
        assert hashlib.sha256((repo_root() / relative).read_bytes()).hexdigest() == digest, relative
    package = repo_root() / "src" / "lab_brain" / "discovery_safety" / "v11"
    frozen = {p for p in manifest["v11_sources_sha256"] if "/v11/" in p}
    assert frozen == {p.resolve().relative_to(repo_root()).as_posix() for p in package.glob("*.py")}
    inputs = manifest["inputs"]
    assert inputs["safety_protocol_digest"] == SAFETY_V11.digest
    assert inputs["plan_digest"] == PLAN.digest
    assert inputs["engine_protocol_digest"] == DISCOVERY.digest
    assert manifest["inputs_digest"] == stable_digest(inputs)
    body = {
        k: v
        for k, v in manifest.items()
        if k not in ("manifest_sha256", "code_commit", "environment")
    }
    assert manifest["manifest_sha256"] == stable_digest(body)
    assert all(
        manifest["frozen_inputs"][k] is True for k in manifest["frozen_inputs"] if "match" in k
    )
    freeze = manifest["design_freeze"]
    assert freeze["v11_sources_identical_to_freeze"] is True
    assert freeze["protocol_digest"] == SAFETY_V11.digest and freeze["plan_digest"] == PLAN.digest
    assert len(freeze["commit"]) == 40
    assert manifest["evidence_class"].startswith("ENGINEERING EVIDENCE ONLY")
    env = manifest["environment"]
    assert env["interpreter_key"].startswith("CPython 3.") and env["dependencies"]


def test_every_evidence_file_is_the_one_the_manifest_hashed(manifest):
    assert hashlib.sha256(_text("results.json").encode()).hexdigest() == manifest["results_sha256"]
    for name, digest in manifest["rows_sha256"].items():
        assert hashlib.sha256(_text(name).encode()).hexdigest() == digest, name


def test_the_sets_are_labelled_held_out_or_previously_inspected(results):
    assert results[f"held_out_{FRESH}"]["role"] == HELD_OUT_V11
    assert results["benchmark"]["role"] == HELD_OUT_V11
    for seeds in PLAN.previously_inspected:
        block = results[f"previously_inspected_{seeds.base_seed}"]
        assert block["role"] == PREVIOUSLY_INSPECTED
        repro = block["v10_digests_reproduced"]
        assert repro["identical"] == repro["compared"] > 0


def _sets(results: Any) -> list[str]:
    return [k for k in results if k.startswith(("held_out_", "previously_inspected_"))]


def test_the_tables_are_the_counts_of_the_recorded_rows(results):
    for key in _sets(results):
        base = results[key]["base_seed"]
        rows = _load(f"held_out_{base}_rows.json")
        for budget, arms in results[key]["held_out"]["by_budget"].items():
            if budget == "comparison_basis":
                continue
            for arm, tables in arms.items():
                mine = [r["arms"][arm][budget] for r in rows if not r["aliased"]]
                for category in ev.CATEGORIES:
                    assert tables["primary"][category]["k"] == sum(
                        m["category"] == category for m in mine
                    ), (key, budget, arm, category)
                assert tables["primary"]["realized_cost"]["n"] == len(mine)
                assert tables["primary"]["proposals_counted_as_identification"] == 0
        assert results[key]["never_confirmed"] and results[key]["budget_never_exceeded"]


def test_no_v11_endorsement_left_a_signal_experiment_unrun(results):
    for key in [*_sets(results), "benchmark"]:
        assert results[key]["v11_additions"]["endorsed_with_a_never_run_signal_experiment"] == 0


def test_rerunning_a_subset_reproduces_the_recorded_b4_digests():
    catalog = ring_catalog()
    seeds = PLAN.held_out[0]
    worlds = held_out.held_out_worlds(
        catalog, seeds_per_class=seeds.per_group, base_seed=seeds.base_seed, protocol=DISCOVERY
    )
    assert stable_digest(worlds) == _load("results.json")[f"held_out_{FRESH}"]["specs_digest"]
    rows = {r["world_id"]: r for r in _load(f"held_out_{FRESH}_rows.json")}
    chosen = worlds[:: seeds.per_group * 4]
    recorder = ev.SafeArmRecorderV11()
    for row in held_out.run_held_out(
        catalog,
        chosen,
        arms=(recorder.arm(),),
        budget=12,
        motivating_experiment=MOTIVATING_EXPERIMENT,
        protocol=DISCOVERY,
    ):
        assert rows[row.world_id]["arms"]["B4"]["12"]["digest"] == row.digest, row.world_id


def test_the_report_quotes_the_recorded_numbers(results, manifest):
    text = REPORT.read_text(encoding="utf-8")
    assert "ENGINEERING EVIDENCE ONLY" in text and "NOT PASSED" in text
    assert manifest["design_freeze"]["commit"][:7] in text
    head = results[f"held_out_{FRESH}"]["held_out"]["by_budget"]
    for budget in ("8", "12", "24", "48"):
        for arm in ev.ARM_IDS:
            t = head[budget][arm]["primary"]["FORCE_FIT"]
            assert f"{t['k']}/{t['n']}" in text, (budget, arm)


def test_the_v10_refit_reproduction_log_is_kept():
    log = (AUDIT / "refit-bypass-before.log").read_text(encoding="utf-8")
    assert "VERDICT: v1.0 IS VULNERABLE" in log and "held_out-geometry.width_narrow-00" in log
