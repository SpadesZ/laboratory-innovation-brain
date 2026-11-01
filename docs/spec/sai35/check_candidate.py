"""SAI 3.5 Discovery Candidate: offline structural check of the candidate documents.

Run: python docs/spec/sai35/check_candidate.py --self-test

What it proves: the candidate is NOT active (ACTIVE_SPEC.yaml and the SAI 3.3/3.4 files are
byte-identical to the base commit), every D-NNN statement is registered exactly once, the required
sections exist, and the G-D levels, arms, metrics, phases and decisions agree across documents.
What it does not prove: anything about discovery, physics, runtime behavior or the quality of the
prose. Planned tests are never counted as executed tests. No git history is needed.
"""

from __future__ import annotations

import copy
import hashlib
import re
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml

ROOT = Path(__file__).resolve().parents[3]
REGISTRY = "docs/spec/sai35/normative-statements.yaml"
BASE_REVISION = "a38ad63a4f4ad83c895cbd1e32b2e760d878f356"
ACTIVE_SPEC = "docs/spec/ACTIVE_SPEC.yaml"
WORKFLOW = ".github/workflows/ci.yml"
SAI34_REGISTRY = "docs/spec/sai34/normative-statements.yaml"
SAI34_ACTIVATION = "docs/spec/sai34/activation.yaml"
# Checked when present; the zh-TW summary may be added to the branch separately.
OPTIONAL_DOCUMENTS = ("docs/spec/sai35/REPORT.zh-TW.md",)

# The entrypoint must keep exactly the values it had at the base commit.
ACTIVE_SPEC_VALUES = {
    "schema_version": 1,
    "architecture_version": "3.4.0-phased.1",
    "architecture_spec": "docs/spec/SAI_3.4.md",
    "activation_registry": "docs/spec/sai34/activation.yaml",
    "activation_state": "PHASED_ARCHITECTURAL_BASIS",
    "effectiveness": (
        "Same-SHA full CI success and documentation-only publication to "
        "integration-integrity-accounts."
    ),
    "executable_conformance_version": "3.3",
    "executable_spec": "docs/spec/SAI_3.3.md",
    "executable_registry": "docs/normative_statements.yaml",
    "executable_milestones": "docs/milestones.yaml",
    "full_runtime_activation": "DEFERRED",
    "ready_for_real_research": False,
}

# SHA-256 of every SAI 3.3 / SAI 3.4 file at BASE_REVISION. SAI 3.5 may not change one byte.
# Exception, Owner decision OD-10: the SAI 3.4 activation allowlist (activation.yaml and
# check_activation.py) gained the SAI 3.5 candidate paths; their hashes are the patched ones.
PROTECTED = {
    "docs/spec/ACTIVE_SPEC.yaml": (
        "4b9ed134325071cc2b0b3ee097db9a7e5054991353529838281abd8e5ef51479"
    ),
    "docs/spec/SAI_3.3.md": "d7576691ef846ef05d8a0036434402a6fb0317f3c28af97597d4fc5dc375c1aa",
    "docs/normative_statements.yaml": (
        "0e49fdc7544c0cbf56821d7463f1d86e1ec2089484c454d4d0310813638bae29"
    ),
    "docs/milestones.yaml": "e35f3455dd97c378058dcf8bfe57844129227b68c8504cb9a6e28739c4e9ea5d",
    "docs/spec/SAI_3.4.md": "d2828c937f76231b844eeda8f84628fa3b8ae047abb06ab2181dd3f1885cc63c",
    "docs/spec/SAI_3.4_Candidate.md": (
        "78d2ddf536bd55f7532c776b70b8fc4bb22372edb09d829ecbdc4b39110b14ed"
    ),
    "docs/spec/sai34/acceptance.md": (
        "b3b525ae628a5ec70cf24ad54c372719d5b322f43b1de7ae956c74120189bc40"
    ),
    "docs/spec/sai34/activation.yaml": (
        "08f0f56787b681d6f546262b91fdfb24c0ed079b954ac23ab3b706743411022e"
    ),
    "docs/spec/sai34/change-impact.md": (
        "1ae46679c92f41d5e9a25758f09100b9638d0536f7ac4d2170c34365d2cb6d16"
    ),
    "docs/spec/sai34/check_activation.py": (
        "a9602a28170c8282d5c8f6b374e1703c7ae67551fddb1a6b89344dfac4580d83"
    ),
    "docs/spec/sai34/check_candidate.py": (
        "229e2c028327e597b90c07974a9e00ff6058842ab8f71a29b848ee1710673730"
    ),
    "docs/spec/sai34/decisions-and-review.md": (
        "22be410e5ce2b3e9b6d871a3b60effe097d3d325202569fdff93025ad70e40e2"
    ),
    "docs/spec/sai34/implementation-gap.md": (
        "b9942d736f7ff56ac9185b2fddb203dabc63dbbd608a950e323722f2bed6a725"
    ),
    "docs/spec/sai34/integration-activation.md": (
        "5000c6e161eaf90f03bcfbd5e8d751dd5d737213d3beb788a6d17e5cd611efe7"
    ),
    "docs/spec/sai34/normative-statements.yaml": (
        "3cde28259dcf3872bbdb8ae52958c6ef1f32608dfba06fd48fd2ea969e6ff075"
    ),
    "docs/architecture/sai34-autonomous-modeling.md": (
        "acd553336aaed057d1bbbf8948ef8d494e9dba6a612abf8fe68fd03facccd829"
    ),
    "docs/adr/ADR-0013-autonomous-scientific-modeling-candidate.md": (
        "483b4ab0c553548754f5690bd7b818568a1ff737f11390873c71db5bcc8d5862"
    ),
    "docs/adr/ADR-0014-phased-sai34-activation.md": (
        "157f2b7b24f7c9575ec7fde3e7253ea41c5d06d0e42690b68ee2739b8a585bbf"
    ),
}

VISION = (
    "an autonomous AI scientist capable of discovering research problems, generating genuinely "
    "novel and falsifiable physical hypotheses, reframing failed research, and independently "
    "validating scientific findings"
)
HEADINGS = {
    "0": "Status, authority and how to read this candidate",
    "1": "Product vision",
    "2": "End-to-end architecture",
    "3": "Discovery Loop",
    "4": "Discovery and validation",
    "5": "Human oversight and governance",
    "6": "Independent G-D acceptance framework",
    "7": "Matched-budget comparison",
    "8": "Non-goals and falsification",
    "9": "Activation boundary",
}
E2E_TERMS = (
    "literature", "from scratch", "Geometry", "materials", "doping", "meshes", "solver",
    "CHARGE", "MODE", "FDTD", "INTERCONNECT", "internal", "license-governed",
    "Owner-authorized", "cost-governed", "parameter sweep", "convergence",
    "refinement", "independent physical validation", "zh-TW", "en",
)  # fmt: skip
ARMS = {"A": "single LLM", "B": "existing LIB", "C": "LIB with Discovery"}
METRICS = [
    "true-mechanism discovery rate",
    "distinguishable diversity",
    "experimental efficiency",
    "false discoveries",
    "reproducibility",
]
GD_FRAMEWORK = {
    "separate_from_g0_g9": True,
    "g0_g9_completion_implies_discovery": False,
    "requires_independent_evaluator": True,
    "implementer_may_sign": False,
    "substitutes_for_g_gates": False,
    "evaluated_levels": [],
}
CONTRADICTIONS = (
    re.compile(r"READY_FOR_REAL_RESEARCH\s*=\s*true", re.I),
    re.compile(r"Status:\s*\*\*ACTIVE"),
    re.compile(r"\bG0 (?:is )?PASSED\b"),
    re.compile(r"\bSAI 3\.5 is (?:now )?active\b", re.I),
)
REQ = re.compile(r"\bD-\d{3}\b")
STATEMENT = re.compile(r"<!-- statement: ([\w.]+) -->\n\*\*(D-\d{3}) (MUST|SHOULD)\*\*")
SECTION = re.compile(r"^## (\d+)\. (.+)$", re.M)


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def load() -> dict:
    registry = yaml.safe_load(read(REGISTRY))
    paths = [*registry["documents"], ACTIVE_SPEC, WORKFLOW]
    paths += [path for path in OPTIONAL_DOCUMENTS if (ROOT / path).is_file()]
    return {
        "registry": registry,
        "texts": {path: read(path) for path in paths},
        "protected": {path: (ROOT / path).read_bytes() for path in PROTECTED},
    }


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("**", ""))


def paragraph(spec: str, req: str) -> str:
    """The statement paragraph that starts with the bold requirement ID."""
    for block in spec.split("\n\n"):
        if f"**{req} MUST**" in block or f"**{req} SHOULD**" in block:
            return flat(block)
    raise AssertionError(f"no statement paragraph for {req}")


def section_text(spec: str, number: str) -> str:
    starts = [(m.group(1), m.start()) for m in SECTION.finditer(spec)]
    for index, (name, start) in enumerate(starts):
        if name == number:
            end = starts[index + 1][1] if index + 1 < len(starts) else len(spec)
            return spec[start:end]
    raise AssertionError(f"missing section {number}")


def trace_row(statement: dict) -> str:
    asm = ", ".join(statement["related_sai34"]) or "—"
    sai33 = ", ".join(statement["related_sai33"]) or "—"
    return (
        f"| {statement['requirement_id']} | `{statement['key']}` | §{statement['section']} | "
        f"{asm} | {sai33} | {', '.join(statement['gates'])} | {statement['milestone']} |"
    )


def check(state: dict) -> None:
    data, texts, protected = state["registry"], state["texts"], state["protected"]

    # 1. The candidate declares itself inactive and changes nothing that is active.
    assert data["status"] == "CANDIDATE", "registry status must be CANDIDATE"
    assert data["activation_status"] == "NOT_ACTIVE", "registry must say NOT_ACTIVE"
    assert data["integrated"] is False, "the candidate is not integrated"
    assert data["owner_approval"] == "PENDING", "no Owner approval exists"
    assert data["ready_for_real_research"] is False, "READY_FOR_REAL_RESEARCH stays false"
    assert data["g0_status"] == "NOT_PASSED", "G0 is not passed"
    assert data["changes_sai34"] is False, "SAI 3.5 does not change SAI 3.4"
    assert data["changes_g0_g9"] is False, "SAI 3.5 does not change G0-G9"
    assert data["base_revision"] == BASE_REVISION, "base revision"
    assert data["deferred_rationale"] and data["review_trigger"], "deferral fields"
    date.fromisoformat(data["review_at"])
    for path, expected in PROTECTED.items():
        assert hashlib.sha256(protected[path]).hexdigest() == expected, f"changed: {path}"
    entry = yaml.safe_load(texts[ACTIVE_SPEC])
    assert entry == ACTIVE_SPEC_VALUES, "ACTIVE_SPEC.yaml differs from the base values"
    assert "3.5" not in texts[ACTIVE_SPEC] and "sai35" not in texts[ACTIVE_SPEC]
    for path in ("docs/normative_statements.yaml", "docs/milestones.yaml"):
        assert not REQ.search(protected[path].decode("utf-8")), f"D-NNN in active {path}"

    spec = texts[data["spec_document"]]
    status = [line for line in spec.splitlines() if line.startswith("Status:")]
    assert len(status) == 1, "exactly one status line"
    for term in ("CANDIDATE", "NOT ACTIVE", "not integrated", "does not change SAI 3.4", "G0–G9"):
        assert term in status[0], f"status line lacks {term!r}"
    assert "READY_FOR_REAL_RESEARCH = false" in spec, "spec must state readiness false"
    assert "G0 is NOT PASSED" in spec, "spec must state G0 is NOT PASSED"
    for path, text in texts.items():
        if path not in (ACTIVE_SPEC, WORKFLOW):
            assert data["spec_version"] in text, f"version missing in {path}"
        for pattern in CONTRADICTIONS:
            assert not pattern.search(text), f"{path}: {pattern.pattern}"

    # 2. Every D-NNN statement in the markdown is registered exactly once, and vice versa.
    statements = data["normative_statements"]
    pairs = STATEMENT.findall(spec)
    ids = [req for _, req, _ in pairs]
    keys = [key for key, _, _ in pairs]
    assert len(ids) == len(set(ids)) and len(keys) == len(set(keys)), "duplicate statement"
    registered = [s["requirement_id"] for s in statements]
    assert len(registered) == len(set(registered)), "duplicate requirement_id in registry"
    assert len({s["key"] for s in statements}) == len(statements), "duplicate key in registry"
    assert {(k, r, lvl) for k, r, lvl in pairs} == {
        (s["key"], s["requirement_id"], s["level"]) for s in statements
    }, "markdown statements and registry differ"
    assert registered == [f"D-{n:03}" for n in range(1, len(registered) + 1)], "ID sequence"
    assert f"`D-001`…`D-{len(registered):03}`" in spec, "namespace range in §0 is stale"
    for path, text in texts.items():
        dangling = set(REQ.findall(text)) - set(registered)
        assert not dangling, f"{path} references unregistered {sorted(dangling)}"

    # 3. Registry rows are complete and claim no runtime evidence.
    sai34 = yaml.safe_load(protected[SAI34_REGISTRY])
    asm_ids = {row["requirement_id"] for row in sai34["normative_statements"]}
    activation = yaml.safe_load(protected[SAI34_ACTIVATION])
    sai33_ids = set(activation["inherited_profile"]["requirement_test_bindings"])
    sections = {m.start(): m.group(1) for m in SECTION.finditer(spec)}
    for match in STATEMENT.finditer(spec):
        owner = max((pos for pos in sections if pos < match.start()), default=None)
        row = next((s for s in statements if s["requirement_id"] == match.group(2)), None)
        assert owner is not None and row is not None, match.group(2)
        assert sections[owner] == row["section"], f"{match.group(2)} is not in its section"
    trace = texts["docs/spec/sai35/traceability.md"]
    for s in statements:
        req = s["requirement_id"]
        assert s["level"] in ("MUST", "SHOULD") and s["status"] == "SPECIFIED", req
        assert s["tests"] == [], f"{req}: a candidate cannot claim runtime tests"
        assert s["planned_tests"] == [f"T-{req}"], req
        assert s["pass_condition"] and s["deferred_rationale"], req
        assert s["gates"] and set(s["gates"]) <= set(data["gd_levels"]), req
        assert s["milestone"] in data["roadmap_phases"], req
        assert set(s["related_sai34"]) <= asm_ids, f"{req}: unknown ASM"
        assert set(s["related_sai33"]) <= sai33_ids, f"{req}: unknown SAI 3.3 requirement"
        date.fromisoformat(s["review_at"])
        assert trace_row(s) in trace, f"traceability row drifted: {req}"

    # 4. Required sections and their load-bearing content.
    for number, title in HEADINGS.items():
        assert f"## {number}. {title}" in spec, f"missing heading §{number} {title}"
    assert VISION in flat(section_text(spec, "1")), "vision sentence missing from §1"
    e2e = flat(section_text(spec, "2"))
    for term in E2E_TERMS:
        assert term in e2e, f"§2 lacks {term!r}"
    by_key = {s["key"]: s["requirement_id"] for s in statements}
    required_keys = {
        "autonomy.no_external_coding_agent",
        "gd.independence",
        "compare.three_arms",
        "compare.metrics",
        "validation.stop_insufficient",
        "validation.cwg_only_confirmed",
    }
    assert required_keys <= set(by_key), f"missing {sorted(required_keys - set(by_key))}"
    agent = paragraph(spec, by_key["autonomy.no_external_coding_agent"])
    for term in ("must not depend on Codex, Claude Code or any other external coding agent",
                 "Acceptance check", "T-D-006", "zero coding-agent invocations"):  # fmt: skip
        assert term in agent, f"no-external-coding-agent statement lacks {term!r}"
    assert data["production_depends_on_external_coding_agent"] is False, "coding-agent flag"
    independence = paragraph(spec, by_key["gd.independence"])
    for term in ("Completing G0–G9 alone must never imply successful autonomous discovery",
                 "independent evaluator", "not the implementer"):  # fmt: skip
        assert term in independence, f"G-D independence statement lacks {term!r}"
    assert data["gd_framework"] == GD_FRAMEWORK, "G-D framework flags changed"
    assert data["gd_levels"] == [f"G-D{n}" for n in range(5)], "G-D levels"
    for level in data["gd_levels"]:
        assert f"| {level} |" in spec, f"G-D table lacks {level}"
        assert f"| {level} |" in texts["docs/spec/sai35/acceptance-gd.md"], level
    assert data["comparison_arms"] == ARMS, "comparison arms changed"
    arms = paragraph(spec, by_key["compare.three_arms"])
    protocol = texts["docs/spec/sai35/matched-budget-protocol.md"]
    for letter, name in ARMS.items():
        assert f"({letter}) {name}" in arms, f"arm {letter} missing from statement"
        assert f"**{letter} — {name}**" in protocol, f"arm {letter} missing from protocol"
    assert data["metrics"] == METRICS, "metric list changed"
    metrics = paragraph(spec, by_key["compare.metrics"]).lower()
    for metric in METRICS:
        assert metric in metrics, f"metric {metric!r} missing from statement"
        assert f"**{metric}**" in protocol.lower(), f"metric {metric!r} missing from protocol"
    assert "never raw hypothesis counts" in metrics, "diversity must exclude raw counts"
    assert "invalid" in metrics, "drifted re-runs must be invalid"
    stop = paragraph(spec, by_key["validation.stop_insufficient"])
    for term in ("INSUFFICIENT_VALIDATION", "STOPPED", "success of governance"):
        assert term in stop, f"stop statement lacks {term!r}"
    assert data["stop_outcomes"] == ["INSUFFICIENT_VALIDATION", "STOPPED"], "stop outcomes"
    assert data["stop_outcome_is_governance_success"] is True, "stop is governance success"
    assert data["confirmed_only_via"] == "causal_warrant_gate", "CONFIRMED only via CWG"
    cwg = paragraph(spec, by_key["validation.cwg_only_confirmed"])
    assert "only path to CONFIRMED" in cwg, "CWG statement lacks its rule"
    for state_name in data["epistemic_states"]:
        assert f"| `{state_name}` |" in spec, f"epistemic state {state_name} not tabled"
    for state_name in data["anomaly_states"]:
        assert f"| `{state_name}` |" in spec, f"anomaly state {state_name} not tabled"
    assert data["licensed_products"] == ["CHARGE", "MODE", "FDTD", "INTERCONNECT"], "products"
    gates = ["money", "licenses", "physical_experiments", "publication"]
    assert data["owner_gates"] == gates, "Owner gate classes"
    assert data["human_account_roles"] == ["ADMIN", "MEMBER"], "only ADMIN and MEMBER"
    assert data["unresolved_security_decisions"] == ["A3", "A9", "A12"], "A3/A9/A12 open"

    # 5. Roadmap and decisions agree with the registry; every decision is still open.
    roadmap = texts["docs/spec/sai35/roadmap.md"]
    for phase in data["roadmap_phases"]:
        assert f"| {phase} |" in roadmap, f"roadmap lacks {phase}"
    decisions = texts["docs/spec/sai35/decisions-and-review.md"]
    expected = dict.fromkeys(data["owner_decisions"], "OPEN")
    assert data["decision_statuses"] == expected, "every Owner decision stays OPEN"
    for decision in data["owner_decisions"]:
        row = next((x for x in decisions.splitlines() if x.startswith(f"| {decision} |")), "")
        assert row.endswith("| OPEN |"), f"decision {decision} missing or not OPEN"

    # 6. CI runs this checker beside the SAI 3.4 checkers.
    steps = yaml.safe_load(texts[WORKFLOW])["jobs"]["spec-conformance"]["steps"]
    runs = [str(step.get("run", "")) for step in steps]
    for command in ("docs/spec/sai34/check_candidate.py --self-test",
                    "docs/spec/sai34/check_activation.py --self-test",
                    "docs/spec/sai35/check_candidate.py --self-test"):  # fmt: skip
        assert any(command in run for run in runs), f"CI lacks {command}"

    # 7. Local links resolve.
    for path, text in texts.items():
        for target in re.findall(r"\]\(([^)]+)\)", text):
            parsed = urlsplit(target)
            if parsed.scheme or not parsed.path:
                continue
            local = ((ROOT / path).parent / unquote(parsed.path)).resolve()
            assert local.is_relative_to(ROOT) and local.is_file(), (path, target)


def _replace(path: str, old: str, new: str) -> Callable[[dict], None]:
    def mutate(state: dict) -> None:
        assert old in state["texts"][path], f"self-test anchor missing: {old!r}"
        state["texts"][path] = state["texts"][path].replace(old, new)

    return mutate


def _set(*keys: str, value: object) -> Callable[[dict], None]:
    def mutate(state: dict) -> None:
        target = state["registry"]
        for key in keys[:-1]:
            target = target[key]
        target[keys[-1]] = value

    return mutate


def _statements(change: Callable[[list], None]) -> Callable[[dict], None]:
    return lambda state: change(state["registry"]["normative_statements"])


def _protected(path: str) -> Callable[[dict], None]:
    def mutate(state: dict) -> None:
        state["protected"][path] = state["protected"][path] + b"\n"

    return mutate


SPEC = "docs/spec/SAI_3.5_Discovery_Candidate.md"
MUTATIONS: dict[str, Callable[[dict], None]] = {
    "registry_active": _set("activation_status", value="ACTIVE"),
    "readiness": _set("ready_for_real_research", value=True),
    "integrated": _set("integrated", value=True),
    "g0_passed": _set("g0_status", value="PASSED"),
    "g0_g9_implies_discovery": _set(
        "gd_framework", "g0_g9_completion_implies_discovery", value=True
    ),
    "level_evaluated": _set("gd_framework", "evaluated_levels", value=["G-D1"]),
    "arm_removed": lambda s: s["registry"]["comparison_arms"].pop("A"),
    "metric_removed": lambda s: s["registry"]["metrics"].remove("reproducibility"),
    "decision_closed": _set("decision_statuses", "OD-10", value="CLOSED"),
    "duplicate_id": _statements(lambda rows: rows[1].update(requirement_id="D-001")),
    "missing_yaml_statement": _statements(lambda rows: rows.pop()),
    "runtime_test_claim": _statements(lambda rows: rows[0].update(tests=["T-D-001"])),
    "unknown_asm": _statements(lambda rows: rows[0].update(related_sai34=["ASM-099"])),
    "section_mismatch": _statements(lambda rows: rows[2].update(section="5")),
    "traceability_drift": _statements(lambda rows: rows[5].update(milestone="D0")),
    "extra_md_statement": _replace(
        SPEC,
        "## 8. Non-goals and falsification",
        "<!-- statement: extra.req -->\n**D-047 MUST** — extra.\n\n"
        "## 8. Non-goals and falsification",
    ),
    "dangling_reference": _replace(
        "docs/spec/sai35/roadmap.md", "## 1. Phases", "## 1. Phases\n\nSee D-099."
    ),
    "status_line_active": _replace(SPEC, "**CANDIDATE — NOT ACTIVE — not integrated.**", "ACTIVE"),
    "readiness_text": _replace(
        SPEC, "`READY_FOR_REAL_RESEARCH = false`", "`READY_FOR_REAL_RESEARCH = true`"
    ),
    "active_spec_values": _replace(
        ACTIVE_SPEC, "architecture_version: 3.4.0-phased.1", "architecture_version: 3.5.0"
    ),
    "protected_sai33": _protected("docs/spec/SAI_3.3.md"),
    "protected_sai34_activation": _protected("docs/spec/sai34/activation.yaml"),
    "protected_active_spec": _protected(ACTIVE_SPEC),
    "vision_removed": _replace(SPEC, "reframing\nfailed research", "revising work"),
    "coding_agent_removed": _replace(SPEC, "Codex, Claude Code or any other", "some"),
    "gd_implied": _replace(SPEC, "alone must never imply", "implies"),
    "arm_text_removed": _replace(SPEC, "**(A) single LLM**", "**(A) a baseline**"),
    "metric_text_removed": _replace(SPEC, "**experimental efficiency**", "**speed**"),
    "stop_removed": _replace(SPEC, "explicit `INSUFFICIENT_VALIDATION` or", "explicit"),
    "missing_heading": _replace(SPEC, "## 8. Non-goals and falsification", "## 8. Other"),
    "e2e_term_removed": _replace(SPEC, "*cost-governed*", "*priced*"),
    "decision_text_closed": _replace(
        "docs/spec/sai35/decisions-and-review.md",
        "keep SAI 3.5 on its own branch until integration | OPEN |",
        "keep SAI 3.5 on its own branch until integration | CLOSED |",
    ),
    "ci_step_removed": _replace(
        WORKFLOW, "python docs/spec/sai35/check_candidate.py --self-test", "true"
    ),
    "broken_link": _replace(
        "docs/spec/sai35/roadmap.md", "## 2. Dependency picture", "[x](missing.md)\n\n## 2."
    ),
}


def self_test(state: dict) -> None:
    for name, mutate in MUTATIONS.items():
        damaged = copy.deepcopy(state)
        mutate(damaged)
        try:
            check(damaged)
        except AssertionError:
            continue
        raise AssertionError(f"self-test: mutation {name!r} was not rejected")


if __name__ == "__main__":
    current = load()
    check(current)
    if "--self-test" in sys.argv:
        self_test(current)
        print(f"self-test: all {len(MUTATIONS)} mutations rejected")
    count = len(current["registry"]["normative_statements"])
    print(
        f"SAI 3.5 Discovery Candidate structure OK: {count} D-NNN statements, all SPECIFIED; "
        "NOT ACTIVE; SAI 3.3/3.4 and ACTIVE_SPEC.yaml unchanged; no G-D level evaluated."
    )
