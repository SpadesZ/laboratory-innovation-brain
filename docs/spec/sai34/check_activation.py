"""離線驗證分期架構對照與文件限定整合；不執行研究、API 或 solver。

執行：python docs/spec/sai34/check_activation.py --self-test
歷史 3.3 conformance 與已批准候選仍由原 checker 保護，本檔不改 runtime parser。
"""

from __future__ import annotations

import copy
import hashlib
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml

ROOT = Path(__file__).resolve().parents[3]
REGISTRY = Path(__file__).with_name("activation.yaml")
APPROVED = "eaea2c03e24b968c62ef9d60e7032f279f5e136c"


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=ROOT, encoding="utf-8", errors="strict"
    ).strip()


def check(data: dict) -> None:
    # 重用現有 parser，明確傳入此 worktree 的 3.3；不修改它的預設或 namespace。
    sys.path.insert(0, str(ROOT / "src"))
    from lab_brain.spec import load_spec

    candidate = yaml.safe_load(REGISTRY.with_name("normative-statements.yaml").read_text("utf-8"))
    entrypoint = yaml.safe_load((ROOT / "docs/spec/ACTIVE_SPEC.yaml").read_text("utf-8"))
    assert data["spec_version"] == entrypoint["architecture_version"] == "3.4.0-phased.1"
    assert data["status"] == entrypoint["activation_state"] == "PHASED_ARCHITECTURAL_BASIS"
    assert data["ready_for_real_research"] is entrypoint["ready_for_real_research"] is False
    assert entrypoint["executable_conformance_version"] == "3.3"
    assert entrypoint["full_runtime_activation"] == "DEFERRED"
    assert data["approved_candidate"]["sha"] == APPROVED
    assert data["integration_target"] == "integration-integrity-accounts"
    assert set(data["owner_authorization"]["authorized"]) == {
        "documentation_integration",
        "phased_activation_preparation",
        "G0_reliability_work",
        "pre_license_autonomous_modeling_preparation",
    }
    assert set(data["owner_authorization"]["does_not_authorize"]) == {
        "main_merge",
        "deployment",
        "production_data_changes",
        "paid_api_calls",
        "licensed_simulations",
        "SP_1.1.0_enablement",
        "scientific_readiness",
    }
    assert data["owner_decision_statuses"] == {f"D-{n:02}": "OPEN" for n in range(1, 9)}
    assert data["unresolved_security_decisions"] == ["A3", "A9", "A12"]

    legacy = load_spec(ROOT / "docs/spec/SAI_3.3.md")
    bindings = {req: [] for req in legacy.requirement_ids}
    for row in legacy.traceability:
        bindings[row.requirement_id].append(row.test_id)
    inherited = data["inherited_profile"]
    assert inherited["requirement_count"] == len(bindings) == 60
    assert inherited["test_id_count"] == len(legacy.test_ids) == 60
    assert inherited["requirement_test_bindings"] == bindings
    assert inherited["file_hashes"] == candidate["active_baselines"]
    for path, expected in inherited["file_hashes"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected, path

    frozen = set(candidate["documents"]) | {
        "docs/spec/sai34/normative-statements.yaml",
        "docs/spec/sai34/check_candidate.py",
    }
    assert set(data["frozen_candidate_files"]) == frozen
    for path, expected in data["frozen_candidate_files"].items():
        current = (ROOT / path).read_bytes()
        approved = subprocess.check_output(["git", "show", f"{APPROVED}:{path}"], cwd=ROOT)
        assert current == approved, path
        assert hashlib.sha256(current).hexdigest() == expected, path

    source_rows = {row["requirement_id"]: row for row in candidate["normative_statements"]}
    rows = data["normative_statements"]
    assert len(rows) == len(source_rows) == 18
    assert {row["requirement_id"] for row in rows} == set(source_rows)
    assert data["acceptance_gates"] == candidate["acceptance_gates"]
    for row in rows:
        req = row["requirement_id"]
        source = source_rows[req]
        assert row["statement_key"] == source["key"], req
        assert row["source_section"] == source["section"] and row["level"] == source["level"], req
        assert row["source_pass_condition"] == source["pass_condition"], req
        assert row["source_deferred_rationale"] == source["deferred_rationale"], req
        assert row["planned_tests"] == source["planned_tests"] and row["tests"] == [], req
        assert row["implementation_status"] == "SPECIFIED", req
        assert row["deferral_status"] == "DEFERRED" and row["deferred_rationale"], req
        assert row["deferral_owner"] == "specification_maintainer" and row["review_trigger"], req
        date.fromisoformat(row["review_at"])
        assert row["acceptance_gates"] == source["gates"], req
        assert row["candidate_milestone"] == source["milestone"], req
        assert row["legacy_dependencies"] and set(row["legacy_dependencies"]) <= set(bindings), req
        expected_tests = sorted(
            {test for dep in row["legacy_dependencies"] for test in bindings[dep]}
        )
        assert row["legacy_test_dependencies"] == expected_tests, req
        assert row["authorized_preparation_tracks"] and set(
            row["authorized_preparation_tracks"]
        ) <= {
            "P-G0",
            "P-MODEL",
        }, req
        assert set(row["owner_decisions"]) <= set(data["owner_decision_statuses"]), req
        assert row["adr"] == "ADR-0014" and row["candidate_adr"] == "ADR-0013", req

    tracks = data["tracks"]
    for track in ("P-G0", "P-MODEL"):
        assert tracks[track]["depends_on"] == ["P0-BASIS"], track
        assert tracks[track]["requires_lumerical"] is False, track
        assert tracks[track]["acceptance_status"] == "NOT_ACCEPTED", track
    assert tracks["P-G0"]["requires_model_builder"] is False
    assert tracks["P-G0"]["acceptance_gate"] == "G0"
    assert tracks["P-MODEL"]["requires_g0_acceptance"] is False
    assert data["later_gates"]["P-PORTABILITY"]["required_for_single_site"] is False
    deferred = data["later_gates"]["P-FULL-RUNTIME"]
    assert deferred["status"] == "DEFERRED" and deferred["rationale"] and deferred["owner"]
    date.fromisoformat(deferred["review_at"])

    expected_allowed = frozen | {
        ".github/workflows/ci.yml",
        "README.md",
        "IMPLEMENTATION_STATUS.md",
        "docs/spec/SAI_3.4.md",
        "docs/spec/ACTIVE_SPEC.yaml",
        "docs/adr/ADR-0014-phased-sai34-activation.md",
        "docs/spec/sai34/activation.yaml",
        "docs/spec/sai34/check_activation.py",
        "docs/spec/sai34/integration-activation.md",
    }
    assert set(data["allowed_documentation_paths"]) == expected_allowed
    assert git("rev-parse", "--is-shallow-repository") == "false"
    ancestors = set(git("rev-list", "HEAD").splitlines())
    assert {data["integration_base"], APPROVED, data["staging_candidate_merge"]} <= ancestors
    assert not set(data["coordination"]["must_not_be_ancestors"]) & ancestors
    assert data["coordination"]["agent_a_merge_authorized"] is False
    assert data["coordination"]["agent_a_acceptance_claimed"] is False
    changed = set(git("diff", "--name-only", data["integration_base"]).splitlines())
    untracked = set(git("ls-files", "--others", "--exclude-standard").splitlines())
    assert changed | untracked <= expected_allowed, sorted((changed | untracked) - expected_allowed)

    for path in data["documents"]:
        document = ROOT / path
        text = document.read_text("utf-8")
        assert data["spec_version"] in text, path
        for target in re.findall(r"\]\(([^)]+)\)", text):
            parsed = urlsplit(target)
            if parsed.scheme or not parsed.path:
                continue
            local = (document.parent / unquote(parsed.path)).resolve()
            assert local.is_relative_to(ROOT) and local.is_file(), (path, target)
    spec = (ROOT / entrypoint["architecture_spec"]).read_text("utf-8")
    assert "READY_FOR_REAL_RESEARCH = false" in spec
    for milestone in data["milestones"]:
        assert f"| {milestone} |" in spec, milestone
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text("utf-8"))
    job = workflow["jobs"]["spec-conformance"]
    assert any(
        step.get("uses", "").startswith("actions/checkout")
        and step.get("with", {}).get("fetch-depth") == 0
        for step in job["steps"]
    )
    assert any("check_activation.py --self-test" in step.get("run", "") for step in job["steps"])


if __name__ == "__main__":
    registry = yaml.safe_load(REGISTRY.read_text("utf-8"))
    check(registry)
    if "--self-test" in sys.argv:
        # ponytail: 小型破壞反例檢查治理邊界；不增加 runtime 測試框架或新 requirement。
        for mutation in (
            "readiness",
            "owner_closed",
            "runtime_test_claim",
            "g0_waits_builder",
            "model_waits_g0",
            "runtime_allowed",
            "agent_a_merged",
            "scope_expanded",
        ):
            damaged = copy.deepcopy(registry)
            if mutation == "readiness":
                damaged["ready_for_real_research"] = True
            elif mutation == "owner_closed":
                damaged["owner_decision_statuses"]["D-07"] = "CLOSED"
            elif mutation == "runtime_test_claim":
                damaged["normative_statements"][0]["tests"] = ["T-ASM-001"]
            elif mutation == "g0_waits_builder":
                damaged["tracks"]["P-G0"]["requires_model_builder"] = True
            elif mutation == "model_waits_g0":
                damaged["tracks"]["P-MODEL"]["requires_g0_acceptance"] = True
            elif mutation == "runtime_allowed":
                damaged["allowed_documentation_paths"].append("src/lab_brain/core/warrant.py")
            elif mutation == "agent_a_merged":
                damaged["coordination"]["agent_a_merge_authorized"] = True
            else:
                damaged["owner_authorization"]["authorized"].append("paid_api_calls")
            try:
                check(damaged)
            except AssertionError:
                continue
            raise AssertionError(f"未拒絕反例：{mutation}")
    print("SAI 3.4 分期對照通過：60 條繼承＋18 條 planned，僅文件整合，G0/物理接受未宣稱。")
