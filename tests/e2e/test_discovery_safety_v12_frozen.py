"""The frozen safety v1.2 evidence: what it froze, that its numbers follow from its rows, and that a
subset re-run reproduces it. ENGINEERING EVIDENCE ONLY on developer-authored synthetic worlds."""

from __future__ import annotations

import hashlib
import json
from functools import cache
from typing import Any

from lab_brain.discovery.protocol import DISCOVERY
from lab_brain.discovery_eval import held_out
from lab_brain.discovery_safety.v12 import evaluation as ev
from lab_brain.discovery_safety.v12.grammar import grammar_from_declaration
from lab_brain.discovery_safety.v12.model import PLAN, SAFETY_V12
from lab_brain.domains.silicon_photonics import discovery_grammar
from lab_brain.domains.silicon_photonics.discovery_catalog import (
    MOTIVATING_EXPERIMENT,
    ring_catalog,
)
from lab_brain.spec import repo_root

ROOT = repo_root()
EVIDENCE = ROOT / "docs" / "audit" / "discovery-safety-v1.2-2026-11-08" / "evidence"
REPORT = ROOT / "docs" / "reports" / "discovery-safety-v1.2.md"
CREDITED = (ev.EXACT, ev.INDISTINGUISHABLE, ev.VALIDATED_NEW)


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


def test_the_manifest_froze_these_sources_this_protocol_plan_and_grammar():
    m = manifest()
    assert {k: _sha(k) for k in m["v12_sources_sha256"]} == m["v12_sources_sha256"]
    assert m["inputs"]["safety_protocol_digest"] == SAFETY_V12.digest
    assert m["inputs"]["plan_digest"] == PLAN.digest
    grammar = grammar_from_declaration(discovery_grammar.declaration())
    assert m["inputs"]["grammar_digest"] == grammar.digest
    assert m["design_freeze"]["v12_sources_identical_to_freeze"] is True
    assert all(v for k, v in m["frozen_inputs"].items() if k.endswith(("_manifest", "_matches")))
    for name, digest in m["rows_sha256"].items():
        assert hashlib.sha256((EVIDENCE / name).read_bytes()).hexdigest() == digest


def test_the_tables_follow_from_the_rows():
    base = PLAN.held_out[0].base_seed
    for setting, part in (("held_out", "primary"), ("control", "all")):
        data = rows(f"{setting}_{base}_rows.json")
        summary = results()[f"held_out_{base}"][setting]["by_budget"]
        for budget in PLAN.budgets:
            for arm in ev.ARM_IDS:
                mine = [
                    w["arms"][arm][str(budget)] for w in data if part == "all" or not w["aliased"]
                ]
                table = summary[str(budget)][arm][part]
                assert table["n"] == len(mine)
                for category in ev.SAI_CATEGORIES:
                    assert table["sai"][category]["k"] == sum(
                        r["category"] == category for r in mine
                    )


def test_nothing_below_supported_is_credited_and_no_earlier_arm_is_supported():
    base = PLAN.held_out[0].base_seed
    for name in (
        f"held_out_{base}_rows.json",
        f"control_{base}_rows.json",
        f"benchmark_{PLAN.benchmark_worlds.base_seed}_rows.json",
    ):
        for world in rows(name):
            for arm, by_budget in world["arms"].items():
                for r in by_budget.values():
                    if r["category"] in CREDITED:
                        assert r["level"] == "SUPPORTED"
                    if arm != "B5":
                        assert r["level"] != "SUPPORTED" and r["registrations"] == 0
                    if r["answer"] != "NONE" and r["level"] != "SUPPORTED":
                        assert r["category"] == ev.PROPOSAL_ONLY


def test_a_subset_re_run_reproduces_the_recorded_digests():
    catalog = ring_catalog()
    seeds = PLAN.held_out[0]
    worlds = held_out.held_out_worlds(
        catalog, seeds_per_class=seeds.per_group, base_seed=seeds.base_seed, protocol=DISCOVERY
    )
    grammar = grammar_from_declaration(discovery_grammar.declaration())
    recorded = {w["world_id"]: w for w in rows(f"held_out_{seeds.base_seed}_rows.json")}
    for world in (worlds[0], worlds[100]):
        for r in ev.held_out_records(
            catalog,
            world,
            budgets=(12,),
            motivating_experiment=MOTIVATING_EXPERIMENT,
            grammar=grammar,
            family_removed=True,
        ):
            assert recorded[world.spec.world_id]["arms"][r.arm]["12"]["digest"] == r.digest


def test_the_report_quotes_the_recorded_headline():
    text = REPORT.read_text(encoding="utf-8")
    base = PLAN.held_out[0].base_seed
    summary = results()[f"held_out_{base}"]
    for budget in PLAN.budgets:
        held = summary["held_out"]["by_budget"][str(budget)]["B5"]["primary"]
        control = summary["control"]["by_budget"][str(budget)]["B5"]["all"]
        assert f"{held['sai'][ev.VALIDATED_NEW]['k']}/195" in text
        assert f"{control['sai'][ev.EXACT]['k']}/240" in text
    assert "ENGINEERING EVIDENCE ONLY" in text and "G-D: NOT PASSED" in text
