"""Reproductions BEFORE the v1.3 fix: on the unchanged v1.2 code, arm-supplied quantities decide SUPPORTED.

Each test asserts the v1.2 behaviour the Independent Chief Auditor found (they pass because v1.2 is
vulnerable, and v1.2 is frozen, so they keep passing: they document the baseline the v1.3
evaluator replaces). The v1.3 counterparts, which assert the same attacks are refused, are in
`test_discovery_safety_v13.py`. Development seeds only (base 7_000_000). ENGINEERING EVIDENCE ONLY.
"""

from __future__ import annotations

import importlib.util
from functools import cache
from types import ModuleType

from lab_brain.spec import repo_root

SCRIPT = repo_root() / "scripts" / "discovery_safety_v13_reproduce_before.py"


@cache
def script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("discovery_safety_v13_reproduce_before", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_r1_an_inflated_sd_turns_a_failing_force_fit_into_a_supported_answer():
    log: list[str] = []
    out = script().r1_inflated_sd(log)
    assert out["before"] == ("PROPOSAL_ONLY", "PROPOSAL")
    assert (out["category"], out["level"]) == ("FORCE_FIT", "SUPPORTED")
    assert any("HONEST sd -> passed False" in line for line in log)


def test_r2_a_non_discriminating_prediction_is_risky_against_the_arms_own_alternative():
    out = script().r2_weak_alternatives([])
    assert out == {"risky_with_none": True, "risky_with_rival": False}


def test_r3_the_arm_writes_the_rules_thresholds():
    assert script().r3_arm_rule([]) == {"passed": True, "risky": True}


def test_r4_the_arm_files_another_hypothesis_prediction_under_its_claim():
    assert script().r4_arm_label([]) == {"supported": True}


def test_r5_the_evaluator_reads_the_new_mechanism_from_the_arms_run_record():
    out = script().r5_arm_answer([])
    assert out["honest"] == ("VALIDATED_NEW_MECHANISM", "SUPPORTED")
    assert out["forged"] == ("WRONG_CLAIM", "SUPPORTED")
