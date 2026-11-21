"""The frozen safety v1.4 evidence: its freeze, its derived seeds, and that its tables follow from rows.

ENGINEERING EVIDENCE ONLY on developer-authored synthetic worlds.
"""

from __future__ import annotations

import hashlib
import json
from functools import cache
from typing import Any

import pytest

from lab_brain.discovery_safety.v13 import evaluation as ev13
from lab_brain.discovery_safety.v14 import costmatch
from lab_brain.discovery_safety.v14.model import (
    EVALUATOR_RULE_V14,
    HOLDOUT_DOMAIN,
    PLAN,
    SAFETY_V14,
)
from lab_brain.spec import repo_root

ROOT = repo_root()
AUDIT = ROOT / "docs" / "audit" / "discovery-safety-v1.4-2026-11-21"
EVIDENCE = AUDIT / "evidence"
HIDDEN = EVIDENCE / "hidden_example"
FREEZE = "bff315f03b61a9f720593a0a691b5d9afa39445c"


@cache
def manifest() -> dict[str, Any]:
    return json.loads((EVIDENCE / "manifest.json").read_text(encoding="utf-8"))


@cache
def results() -> dict[str, Any]:
    return json.loads((EVIDENCE / "results.json").read_text(encoding="utf-8"))


@cache
def rows(name: str) -> list[dict[str, Any]]:
    return json.loads((EVIDENCE / name).read_text(encoding="utf-8"))


def _sha(path: str) -> str:
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def test_the_manifest_froze_these_sources_this_protocol_rule_and_plan():
    m = manifest()
    assert {k: _sha(k) for k in m["v14_sources_sha256"]} == m["v14_sources_sha256"]
    assert m["inputs"]["safety_protocol_digest"] == SAFETY_V14.digest
    assert m["inputs"]["evaluator_rule_digest"] == EVALUATOR_RULE_V14.digest
    assert m["inputs"]["plan_digest"] == PLAN.digest
    assert m["design_freeze"]["v14_sources_identical_to_freeze"] is True
    assert all(v for k, v in m["frozen_inputs"].items() if k.endswith(("_manifest", "_matches")))
    for name, digest in m["rows_sha256"].items():
        assert hashlib.sha256((EVIDENCE / name).read_bytes()).hexdigest() == digest
    text = (EVIDENCE / "results.json").read_text(encoding="utf-8")
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == m["results_sha256"]


def test_the_held_out_seeds_are_the_ones_derived_from_the_freeze_commit():
    freeze = manifest()["design_freeze"]
    assert freeze["commit"] == FREEZE
    assert freeze["held_out_seed_rule"]["domain"] == HOLDOUT_DOMAIN
    seeds = PLAN.held_out_seeds(FREEZE)
    assert freeze["held_out_seed_rule"]["seeds"] == seeds
    r = results()
    assert r["held_out_worlds"]["base_seed"] == seeds["held-out-worlds"]["base_seed"]
    assert r["benchmark"]["base_seed"] == seeds["benchmark-worlds"]["base_seed"]


def _cells() -> list[tuple[str, dict[str, Any]]]:
    out = []
    for name in manifest()["rows_sha256"]:
        for world in rows(name):
            for arm, by_budget in world["arms"].items():
                for budget, cell in by_budget.items():
                    out.append((f"{world['setting']}:{arm}:{budget}", cell))
    return out


def test_no_answer_below_supported_is_credited_and_every_run_stayed_within_its_cap():
    for key, cell in _cells():
        if cell["category"] in ev13.CREDITED:
            assert cell["level"] == "SUPPORTED"
        if cell["level"] == "PROPOSAL":
            assert cell["category"] == ev13.UNSUPPORTED_CLAIM
        assert cell["spent"] <= int(key.split(":")[2])
        assert cell["chain_head"].startswith("sha256:")


def test_the_per_world_comparisons_follow_from_the_rows():
    name = next(n for n in manifest()["rows_sha256"] if n.startswith("benchmark_"))
    block = results()["benchmark"]["matched"]["B7-B4"]["per_world"]
    for stored in block[:3]:
        again = costmatch.per_world_matched(
            rows(name),
            "B7",
            "B4",
            stored["anchor_cap"],
            tolerance=PLAN.per_world_tolerance,
            resamples=PLAN.bootstrap_resamples,
            label=f"benchmark-{results()['benchmark']['base_seed']}",
        )
        assert json.loads(json.dumps(again)) == stored


def test_the_hidden_world_demonstration_used_the_example_file_only_and_verified_its_reveal():
    if not HIDDEN.exists():
        pytest.skip("the example demonstration is written in its own commit")
    r = json.loads((HIDDEN / "results.json").read_text(encoding="utf-8"))
    assert r["example_only"] is True and r["reveal_verified"] is True
    package = json.loads((HIDDEN / "example.engine-package.json").read_text(encoding="utf-8"))
    assert package["root"] == r["package_root"] and package["example_only"] is True
    assert "hidden" not in json.dumps(package["cases"])
