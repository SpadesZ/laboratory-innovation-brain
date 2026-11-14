"""SAI 3.4 候選文件的離線結構檢查；不證明物理正確或散文覆蓋完整。

執行：python docs/spec/sai34/check_candidate.py --self-test
保留 active 3.3 基準；planned tests 永遠不當成已執行的測試證據。
"""

from __future__ import annotations

import copy
import hashlib
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml

ROOT = Path(__file__).resolve().parents[3]
REGISTRY = Path(__file__).with_name("normative-statements.yaml")


def check(data: dict, documents: dict[str, str] | None = None) -> None:
    assert data["status"] == "CANDIDATE" and data["owner_approval"] == "PENDING"
    assert data["ready_for_real_research"] is False
    assert re.fullmatch(r"[0-9a-f]{40}", data["source_revision"])
    assert data["deferred_rationale"] and data["review_trigger"]
    date.fromisoformat(data["review_at"])
    for path, expected in data["active_baselines"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected, path

    if documents is None:
        documents = {path: (ROOT / path).read_text(encoding="utf-8") for path in data["documents"]}
    spec = documents[data["spec_document"]]
    pairs = re.findall(r"<!-- statement: ([\w.]+) -->\s*\*\*(ASM-\d{3}) MUST", spec)
    statements = data["normative_statements"]
    assert len(pairs) == len(statements) == 18
    assert len({key for key, _ in pairs}) == len({req for _, req in pairs}) == 18
    assert set(pairs) == {(s["key"], s["requirement_id"]) for s in statements}
    assert {req for _, req in pairs} == {f"ASM-{n:03}" for n in range(1, 19)}
    assert len(re.findall(r"\*\*ASM-\d{3} MUST：", spec)) == 18
    assert "READY_FOR_REAL_RESEARCH = false" in spec
    assert data["spec_version"] in spec
    acceptance = documents["docs/spec/sai34/acceptance.md"]
    roadmap = documents["docs/architecture/sai34-autonomous-modeling.md"]
    decisions = documents["docs/spec/sai34/decisions-and-review.md"]
    for gate in data["acceptance_gates"]:
        assert f"| {gate} |" in acceptance, gate
    for milestone in data["candidate_milestones"]:
        assert f"| {milestone} |" in roadmap, milestone
    for decision in data["owner_decisions"]:
        assert f"| {decision} |" in decisions, decision

    assert data["acceptance_gates"] == [f"G{n}" for n in range(10)]
    pre = data["pre_lumerical_research_gate"]
    assert pre["gate"] == "G0" and pre["subconditions"] == [f"G0-{s}" for s in "ALSBP"]
    for field in ("requires_authenticated_researcher", "requires_genuine_governed_llm"):
        assert pre[field] is True, field
    for field in ("catalog_or_mock_satisfies", "requires_lumerical", "executed_in_this_revision"):
        assert pre[field] is False, field
    for condition in pre["subconditions"]:
        assert f"| {condition} " in acceptance, condition
    assert "CatalogReasoner/mock/fake/canned responses" in acceptance
    content = [
        "hypotheses",
        "predictions",
        "observations",
        "interpretations",
        "uncertainty",
        "conclusions",
        "limitations",
        "exports",
    ]
    assert data["bilingual_scientific_content"] == content
    asm16 = next(line for line in spec.splitlines() if line.startswith("**ASM-016 MUST"))
    for term in ("假說", "預測", "觀察", "解釋", "不確定度", "結論", "限制", "匯出", "canonical"):
        assert term in asm16, term
    assert "不被翻譯覆寫" in asm16 and "可機器驗證狀態" in asm16
    assert data["human_account_roles"] == ["ADMIN", "MEMBER"]
    assert data["separate_governance_concepts"] == [
        "project_membership",
        "independent_scientific_reviewer_authorization",
        "worker_service_identity",
    ]
    offline = data["offline_development_gate"]
    assert offline["approval_status"] == "PENDING" and offline["activates_sai34"] is False
    assert offline["required_architecture_scopes"] == ["D-01", "D-03", "D-05", "D-06"]
    assert offline["later_decisions"] == {
        "D-02": ["C34-A3", "C34-A4"],
        "D-04": ["C34-A3"],
        "D-08": ["C34-A4"],
    }
    a0 = next(line for line in roadmap.splitlines() if line.startswith("| C34-A0 |"))
    a2 = next(line for line in roadmap.splitlines() if line.startswith("| C34-A2 |"))
    assert "不要求 D-02/D-04/D-08 全部結案" in a0
    assert "G0" in a2 and "真實 LLM" in a2 and "synthetic" in a2
    scopes = data["reproducibility_scopes"]
    assert scopes["single_site"] == {"gate": "G7-SITE", "baseline_required": True}
    assert scopes["cross_worker"] == {
        "gate": "G7-WORKER",
        "blocks_single_site": False,
        "requires_second_qualified_worker": True,
    }
    assert scopes["cross_site"] == {
        "requires_target_site_qualification_and_replay": True,
        "implied_by_single_installation": False,
    }
    g7 = next(line for line in acceptance.splitlines() if line.startswith("| G7 |"))
    assert "G7-SITE" in g7 and "G7-WORKER" in g7 and "沒有第二 worker 不阻擋單站接受" in g7
    assert data["unresolved_security_decisions"] == ["A3", "A9", "A12"]
    assert data["decision_statuses"] == dict.fromkeys(data["owner_decisions"], "OPEN")
    assert set(data["auditor_recommendations"]) == set(data["owner_decisions"])
    for decision in data["owner_decisions"]:
        row = next(line for line in decisions.splitlines() if line.startswith(f"| {decision} |"))
        assert "| OPEN；" in row, decision
    confirmation = data["human_confirmation"]
    assert confirmation["quote"] == "我human同意上述"
    assert confirmation["authorizes_runtime_development"] is False
    assert confirmation["authorizes_activation_or_deployment"] is False
    assert "A3/A9/A12" in data["auditor_recommendations"]["D-07"]
    for text in documents.values():
        for contradiction in (
            "D-01–D-08 有裁決",
            "所有結果明示 synthetic",
            "離線＋兩個合格 licensed worker 環境",
            "授權前測試只驗證軟體與安全契約",
            "Owner、project OWNER、ADMIN、科研 reviewer、worker service identity 是不同權限角色",
        ):
            assert contradiction not in text, contradiction
    for statement in statements:
        req = statement["requirement_id"]
        assert statement["level"] == "MUST" and statement["status"] == "SPECIFIED", req
        assert statement["tests"] == [], f"{req}: candidate cannot claim runtime tests"
        assert statement["planned_tests"] == [f"T-{req}"], req
        assert statement["deferred_rationale"] and statement["pass_condition"], req
        assert statement["milestone"] in data["candidate_milestones"], req
        assert statement["gates"] and set(statement["gates"]) <= set(data["acceptance_gates"]), req
        date.fromisoformat(statement["review_at"])
        assert re.search(rf"^## {re.escape(statement['section'])}\.", spec, re.M), req

    by_requirement = {statement["requirement_id"]: statement for statement in statements}
    for req in ("ASM-002", "ASM-012", "ASM-014", "ASM-016", "ASM-018"):
        assert "G0" in by_requirement[req]["gates"], req
    for term in content:
        assert term in by_requirement["ASM-016"]["pass_condition"], term

    for path in data["documents"]:
        document = ROOT / path
        text = documents[path]
        assert data["spec_version"] in text, path
        for target in re.findall(r"\]\(([^)]+)\)", text):
            parsed = urlsplit(target)
            if parsed.scheme or not parsed.path:
                continue
            local = (document.parent / unquote(parsed.path)).resolve()
            assert local.is_relative_to(ROOT) and local.is_file(), (path, target)
    active = (ROOT / "docs/normative_statements.yaml").read_text(encoding="utf-8")
    assert not re.search(r"\bASM-\d{3}\b", active)


if __name__ == "__main__":
    registry = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    check(registry)
    if "--self-test" in sys.argv:
        # ponytail: 用小型破壞反例守住文件閘門，不另建測試框架。
        for mutation in (
            "duplicate",
            "claimed_runtime_test",
            "readiness",
            "baseline",
            "mock_g0",
            "missing_science",
            "all_decisions_at_a0",
            "cross_worker_blocks_site",
            "third_account_role",
            "closed_decision",
        ):
            damaged = copy.deepcopy(registry)
            if mutation == "duplicate":
                damaged["normative_statements"][1] = damaged["normative_statements"][0]
            elif mutation == "claimed_runtime_test":
                damaged["normative_statements"][0]["tests"] = ["T-ASM-001"]
            elif mutation == "readiness":
                damaged["ready_for_real_research"] = True
            elif mutation == "baseline":
                damaged["active_baselines"]["docs/spec/SAI_3.3.md"] = "0" * 64
            elif mutation == "mock_g0":
                damaged["pre_lumerical_research_gate"]["catalog_or_mock_satisfies"] = True
            elif mutation == "missing_science":
                damaged["bilingual_scientific_content"].remove("observations")
            elif mutation == "all_decisions_at_a0":
                damaged["offline_development_gate"]["required_architecture_scopes"].append("D-04")
            elif mutation == "cross_worker_blocks_site":
                damaged["reproducibility_scopes"]["cross_worker"]["blocks_single_site"] = True
            elif mutation == "third_account_role":
                damaged["human_account_roles"].append("REVIEWER")
            else:
                damaged["decision_statuses"]["D-07"] = "CLOSED"
            try:
                check(damaged)
            except AssertionError:
                continue
            raise AssertionError(f"未拒絕反例：{mutation}")
        documents = {
            path: (ROOT / path).read_text(encoding="utf-8") for path in registry["documents"]
        }
        for contradiction in ("labels_only", "a0_blocks_all", "two_workers_for_site"):
            damaged_docs = documents.copy()
            if contradiction == "labels_only":
                path = registry["spec_document"]
                damaged_docs[path] = re.sub(
                    r"^\*\*ASM-016 MUST.*$",
                    "**ASM-016 MUST：只需翻譯介面標籤。**",
                    damaged_docs[path],
                    flags=re.M,
                )
            elif contradiction == "a0_blocks_all":
                path = "docs/architecture/sai34-autonomous-modeling.md"
                damaged_docs[path] = re.sub(
                    r"^\| C34-A0 \|.*$",
                    "| C34-A0 | 規格啟用 | D-01–D-08 有裁決 | SPECIFIED |",
                    damaged_docs[path],
                    flags=re.M,
                )
            else:
                path = "docs/spec/sai34/acceptance.md"
                damaged_docs[path] = re.sub(
                    r"^\| G7 \|.*$",
                    "| G7 | 可重現 | 必須兩個 worker | 單站不得通過 | license |",
                    damaged_docs[path],
                    flags=re.M,
                )
            try:
                check(registry, damaged_docs)
            except AssertionError:
                continue
            raise AssertionError(f"未拒絕規範矛盾：{contradiction}")
    print("SAI 3.4 候選修正通過；18 條義務仍為 SPECIFIED，G0/licensed/physical 驗收未執行。")
