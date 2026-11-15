"""The frozen safety v1.3 evidence: what it froze, and that its tables follow from its rows.
ENGINEERING EVIDENCE ONLY on developer-authored synthetic worlds."""

from __future__ import annotations

import hashlib
import json
from functools import cache
from typing import Any

from lab_brain.discovery_safety.v13 import evaluation as ev
from lab_brain.discovery_safety.v13.model import EVALUATOR_RULE, PLAN, SAFETY_V13
from lab_brain.spec import repo_root

ROOT = repo_root()
EVIDENCE = ROOT / "docs" / "audit" / "discovery-safety-v1.3-2026-11-11" / "evidence"


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
    assert {k: _sha(k) for k in m["v13_sources_sha256"]} == m["v13_sources_sha256"]
    assert m["inputs"]["safety_protocol_digest"] == SAFETY_V13.digest
    assert m["inputs"]["evaluator_rule_digest"] == EVALUATOR_RULE.digest
    assert m["inputs"]["plan_digest"] == PLAN.digest
    assert m["design_freeze"]["v13_sources_identical_to_freeze"] is True
    assert all(v for k, v in m["frozen_inputs"].items() if k.endswith(("_manifest", "_matches")))
    for name, digest in m["rows_sha256"].items():
        assert hashlib.sha256((EVIDENCE / name).read_bytes()).hexdigest() == digest
    text = (EVIDENCE / "results.json").read_text(encoding="utf-8")
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == m["results_sha256"]


def _cells() -> list[tuple[str, str, dict[str, Any]]]:
    out = []
    for name in manifest()["rows_sha256"]:
        for world in rows(name):
            for arm, by_budget in world["arms"].items():
                for budget, cell in by_budget.items():
                    out.append((f"{world['setting']}:{arm}:{budget}", world["kind"], cell))
    return out


def test_no_answer_below_supported_is_credited_and_asserted_ones_are_errors():
    for _, _, cell in _cells():
        if cell["category"] in ev.CREDITED:
            assert cell["level"] == "SUPPORTED"
        if cell["level"] == "PROPOSAL":
            assert cell["category"] == (
                ev.UNSUPPORTED_CLAIM if cell["asserted"] else ev.PROPOSAL_ONLY
            )


def test_the_benchmark_table_counts_follow_from_the_rows():
    counts: dict[tuple[str, str], int] = {}
    for key, _, cell in _cells():
        if key.startswith("benchmark:"):
            _, arm, budget = key.split(":")
            counts[(arm, budget)] = counts.get((arm, budget), 0) + (
                cell["category"] == ev.UNSUPPORTED_CLAIM
            )
    by_budget = results()["benchmark"]["by_budget"]
    for (arm, budget), k in counts.items():
        assert by_budget[budget][arm]["all"]["unsupported_claim"] == k


def test_every_run_stayed_within_its_cap_and_every_ledger_was_intact():
    for key, _, cell in _cells():
        assert cell["spent"] <= int(key.split(":")[2])
        assert cell["chain_head"].startswith("sha256:")
