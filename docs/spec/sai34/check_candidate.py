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


def check(data: dict) -> None:
    assert data["status"] == "CANDIDATE" and data["owner_approval"] == "PENDING"
    assert data["ready_for_real_research"] is False
    assert re.fullmatch(r"[0-9a-f]{40}", data["source_revision"])
    assert data["deferred_rationale"] and data["review_trigger"]
    date.fromisoformat(data["review_at"])
    for path, expected in data["active_baselines"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected, path

    spec = (ROOT / data["spec_document"]).read_text(encoding="utf-8")
    pairs = re.findall(r"<!-- statement: ([\w.]+) -->\s*\*\*(ASM-\d{3}) MUST", spec)
    statements = data["normative_statements"]
    assert len(pairs) == len(statements) == 18
    assert len({key for key, _ in pairs}) == len({req for _, req in pairs}) == 18
    assert set(pairs) == {(s["key"], s["requirement_id"]) for s in statements}
    assert {req for _, req in pairs} == {f"ASM-{n:03}" for n in range(1, 19)}
    assert len(re.findall(r"\*\*ASM-\d{3} MUST：", spec)) == 18
    assert "READY_FOR_REAL_RESEARCH = false" in spec
    assert data["spec_version"] in spec
    acceptance = (REGISTRY.parent / "acceptance.md").read_text(encoding="utf-8")
    roadmap = (ROOT / "docs/architecture/sai34-autonomous-modeling.md").read_text(encoding="utf-8")
    decisions = (REGISTRY.parent / "decisions-and-review.md").read_text(encoding="utf-8")
    for gate in data["acceptance_gates"]:
        assert f"| {gate} |" in acceptance, gate
    for milestone in data["candidate_milestones"]:
        assert f"| {milestone} |" in roadmap, milestone
    for decision in data["owner_decisions"]:
        assert f"| {decision} |" in decisions, decision
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

    for path in data["documents"]:
        document = ROOT / path
        text = document.read_text(encoding="utf-8")
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
        for mutation in ("duplicate", "claimed_runtime_test", "readiness", "baseline"):
            damaged = copy.deepcopy(registry)
            if mutation == "duplicate":
                damaged["normative_statements"][1] = damaged["normative_statements"][0]
            elif mutation == "claimed_runtime_test":
                damaged["normative_statements"][0]["tests"] = ["T-ASM-001"]
            elif mutation == "readiness":
                damaged["ready_for_real_research"] = True
            else:
                damaged["active_baselines"]["docs/spec/SAI_3.3.md"] = "0" * 64
            try:
                check(damaged)
            except AssertionError:
                continue
            raise AssertionError(f"未拒絕反例：{mutation}")
    print("SAI 3.4 候選文件結構通過；18 條義務仍為 SPECIFIED，licensed/physical 驗收未執行。")
