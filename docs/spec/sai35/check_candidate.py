"""SAI 3.5 master specification candidate: offline structural check of the candidate documents.

Run: python docs/spec/sai35/check_candidate.py --self-test

What it proves:
- the candidate is NOT active: registry flags, the master's status line, ACTIVE_SPEC.yaml values,
  and no S35 identifier in src/, tests/, scripts/, migrations/, the active registry or milestones;
- every SAI 3.3 / SAI 3.4 file and ACTIVE_SPEC.yaml is byte-identical to the base commit, with no
  exception;
- every S35 requirement statement in docs/spec/SAI_3.5.md agrees with the registry (identifier, key,
  level, section, full text and acceptance clause), and identifiers and keys are unique;
- every requirement has a traceability row (component, planned test, gates, phase, status), an
  implementation-status row with the same status and an inherited-links row, and its evidence paths
  exist (at their commits when those commits are present in this clone);
- every retired D-001..D-046 appears in the change register and in the requirement audit, with an
  action consistent with the registry, and the summary counts are recomputed;
- the required sections and their load-bearing content exist (twelve capabilities, the
  no-external-coding-agent requirement with its acceptance check, G-D independence, the three arms,
  the five metrics, stop-when-insufficient, Causal Warrant Gate exclusivity, the three epistemic
  stages, envelope-bounded automatic registration, every state table, appendix authorities,
  components, phases, Owner decisions and spec issues);
- docs/spec/sai35/candidate-paths.txt equals the paths actually changed relative to the base
  (ci.yml excepted), and CI runs the SAI 3.4 activation checker only through the OD-10 proposal A'
  wrapper; this part reads git, so the base commit must be present;
- local links resolve;
- candidate.2 semantics: the executable definitions and counterexamples of semantic_reference.py
  hold and every known-wrong variant (raw count, transitive merge, post-hoc cost matching,
  straddling credit, no ledger reconciliation, unresolved counted as distinct) is rejected; the
  registry flags for distinguishability, matched cost, epistemic-stage scope and termination
  dimensions are pinned; the counterexample tables exist; no normative text asserts an
  equivalence class; only ideas and hypotheses carry a stage field; the semantic consistency
  report assesses every requirement once.

What it does not prove: anything about discovery, physics, runtime behavior or the quality of the
prose. Planned tests are never counted as executed tests.
"""

from __future__ import annotations

import copy
import hashlib
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Callable
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml

ROOT = Path(__file__).resolve().parents[3]
REGISTRY = "docs/spec/sai35/normative-statements.yaml"
BASE_REVISION = "a38ad63a4f4ad83c895cbd1e32b2e760d878f356"
VERSION = "3.5.0-master-candidate.4"
MASTER = "docs/spec/SAI_3.5.md"
ACTIVE_SPEC = "docs/spec/ACTIVE_SPEC.yaml"
WORKFLOW = ".github/workflows/ci.yml"
CANDIDATE_PATHS = "docs/spec/sai35/candidate-paths.txt"
BOUNDARY_WRAPPER = "docs/spec/sai35/check_sai34_boundary_without_candidate.py"
SAI34_REGISTRY = "docs/spec/sai34/normative-statements.yaml"
SAI34_ACTIVATION = "docs/spec/sai34/activation.yaml"
TRACE = "docs/spec/sai35/traceability.md"
STATUS_DOC = "docs/spec/sai35/implementation-status.md"
COMPAT = "docs/spec/sai35/compatibility.md"
CHANGES = "docs/spec/sai35/change-register.md"
AUDIT = "docs/spec/sai35/requirement-audit.md"
RECORDS = "docs/spec/sai35/records-and-states.md"
LIFECYCLE = "docs/spec/sai35/lifecycle.md"
GOVERNANCE = "docs/spec/sai35/governance-security.md"
PROVENANCE = "docs/spec/sai35/provenance-novelty-independence.md"
ARCHITECTURE = "docs/spec/sai35/architecture-end-to-end.md"
ROADMAP = "docs/spec/sai35/roadmap.md"
DECISIONS = "docs/spec/sai35/decisions-and-review.md"
ISSUES = "docs/spec/sai35/open-spec-issues.md"
PROTOCOL = "docs/spec/sai35/matched-budget-protocol.md"
ACCEPTANCE = "docs/spec/sai35/acceptance-gd.md"
DEPLOYMENT = "docs/spec/sai35/deployment-autonomy.md"
DISTINGUISH = "docs/spec/sai35/mechanism-distinguishability.md"
CONSISTENCY = "docs/spec/sai35/semantic-consistency-report.md"
SEMANTIC_REFERENCE = "docs/spec/sai35/semantic_reference.py"
# Appendices that carry obligations: "equivalence class" may appear there only as a negation,
# because pairwise indistinguishability is not an equivalence relation (Appendix S §1).
NORMATIVE_TEXTS = (
    MASTER, LIFECYCLE, ARCHITECTURE, RECORDS, PROVENANCE, GOVERNANCE, ACCEPTANCE, PROTOCOL,
    DISTINGUISH,
    "docs/spec/sai35/ux-reports-glossary.md", DEPLOYMENT, ROADMAP, TRACE, COMPAT,
)  # fmt: skip
CODE_DIRS = ("src", "tests", "scripts", "migrations")
CODE_SUFFIXES = (".py", ".sql", ".md", ".yaml", ".yml", ".json", ".txt", ".toml")

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

# SHA-256 of every SAI 3.3 / SAI 3.4 file at BASE_REVISION. SAI 3.5 may not change one byte; there
# is no exception (the OD-10 allowlist widening of 9d44198 was reverted).
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
        "d4e9b2ca8aafc86077594337cf737327ab245d590604184f0cafd34e2953c92f"
    ),
    "docs/spec/sai34/change-impact.md": (
        "1ae46679c92f41d5e9a25758f09100b9638d0536f7ac4d2170c34365d2cb6d16"
    ),
    "docs/spec/sai34/check_activation.py": (
        "a00a27b6559c16260a9bb1e7cfafc7afc5dd839eaed4932ee38d09fdfb84c8e1"
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

AREAS = (
    "GOV", "LIFE", "PROB", "HYP", "MECH", "REF", "SEL", "MOD", "SIM", "VAL", "LOOP",
    "CWG", "REG", "NOV", "EVI", "RPT", "AUTO", "SEC", "COST", "GD", "CMP",
)  # fmt: skip
STATUS_VALUES = ["complete", "partial", "proposed", "blocked", "untested"]
ACTIONS = ("kept", "refined", "split", "merged", "replaced", "removed")
RETIRED = [f"D-{n:03}" for n in range(1, 47)]
ARMS = {"A": "single frontier LLM", "B": "existing LIB workflow", "C": "LIB with Discovery"}
METRICS = [
    "true-cause discovery",
    "effective mechanism diversity",
    "discriminating-experiment efficiency",
    "false discoveries",
    "independent reproducibility",
]
EPISTEMIC_STAGES = ["EXPLORATORY_IDEA", "TESTABLE_HYPOTHESIS", "EVIDENCE_SUPPORTED_CONCLUSION"]
EPISTEMIC_STAGE_SCOPE = ["ExploratoryIdea", "Hypothesis", "ClaimStateProjection"]
DISTINGUISHABILITY = {
    "definition": DISTINGUISH,
    "identity": "forward_model_content_hash",
    "verdicts": ["DISTINGUISHABLE", "INDISTINGUISHABLE", "UNRESOLVED"],
    "relation_is_transitive": False,
    "transitive_merge_allowed": False,
    "diversity": "max_pairwise_certified_distinguishable_set",
    "unresolved_counts_in_headline": False,
    "near_duplicate_invariant": False,
    "diversity_role": "descriptive_never_primary",
    "adequacy_required_before_endorsement": True,
}
MATCHED_COST = {
    "primary_rule": "frozen_realized_cost_checkpoints",
    "checkpoints_frozen_before_any_arm_runs": True,
    "reservation_before_start": True,
    "checkpoint_accounting": "retrospective_on_settled_cost",
    "operations_charged_from_start": True,
    "unsettled_charged_at": "reservation",
    "overrun_or_missing_headroom": "incident_cost_unmatched",
    "straddling_attempt_supplies_checkpoint": False,
    "score_depends_only_on_own_trace": True,
    "min_final_cost_rule": "secondary_only",
    "unmatched_label": "COST_UNMATCHED",
}
TERMINATION_DIMENSIONS = {
    "operational_termination": ["VALID", "INVALID"],
    "experimental_completion": ["NOT_PERFORMED", "PARTIAL", "COMPLETED"],
    "scientific_acceptance": ["NONE", "PENDING_CAUSAL_WARRANT_GATE", "ACCEPTED_DISCOVERY"],
    "stop_before_experiment": ["VALID", "NOT_PERFORMED", "NONE"],
}
S1_COUNTEREXAMPLES = [*(f"S1-CE-{n}" for n in range(1, 12)), "S3-CE"]
S2_COUNTEREXAMPLES = [f"S2-CE-{n}" for n in range(1, 11)]
EVALUATION_OUTCOMES = [
    "EXACT_IDENTIFICATION",
    "INDISTINGUISHABLE_ALTERNATIVE",
    "UNRESOLVED_ALTERNATIVE",
    "CORRECT_ABSTENTION",
    "FALSE_NULL",
    "FORCE_FIT",
    "WRONG_CLAIM",
    "VALIDATED_NEW_MECHANISM",
    "PROPOSAL_ONLY",
]
EVIDENCE_LEVELS = ["PROPOSAL", "SUPPORTED", "CONFIRMED"]
S4_COUNTEREXAMPLES = ["S4-CE"]
GD_FRAMEWORK = {
    "separate_from_g0_g9": True,
    "g0_g9_completion_implies_discovery": False,
    "requires_independent_evaluator": True,
    "implementer_may_sign": False,
    "substitutes_for_g_gates": False,
    "synthetic_success_is_real_discovery_validation": False,
    "evaluated_levels": [],
}
ENVELOPE = {
    "automatic_registration_inside_bounds": True,
    "authorizes_conclusions": False,
    "never_inside": [
        "physical_experiments",
        "fabrication",
        "publication",
        "irreversible_actions",
        "non_public_egress",
        "validator_protocol_policy_changes",
    ],
    "satisfies_per_hypothesis_preauthorization": "NO_UNTIL_OD-14",
}
# State tables that must exist, per registry list, in the named appendix.
STATE_TABLES = {
    "epistemic_stages": RECORDS,
    "claim_states": RECORDS,
    "anomaly_states": RECORDS,
    "reframing_kinds": RECORDS,
    "campaign_states": LIFECYCLE,
    "autonomy_levels": GOVERNANCE,
    "novelty_classes": PROVENANCE,
}
# Load-bearing phrases per statement key (checked in the master's statement paragraph).
REQUIRED_PHRASES = {
    "auto.no_external_coding_agent": (
        "production research must not depend on Codex, Claude Code or any other external coding "
        "agent",
        "*Acceptance (T-S35-AUTO-001",
        "zero coding-agent invocations",
        "coding-agent executables are absent",
    ),
    "gd.independence": (
        "completing G0–G9 never implies successful autonomous discovery",
        "independent evaluator",
        "Synthetic benchmark success is never reported as real discovery validation",
    ),
    "cmp.three_arms": (
        "(A) single frontier LLM",
        "(B) existing LIB workflow",
        "(C) LIB with Discovery",
    ),
    "cmp.metrics": (
        *METRICS,
        "never raw hypothesis counts",
        "invalid",
        "two axes that are never merged",
        "outcome rates at the primary checkpoint: exact identification",
        "experimentally indistinguishable alternative",
        "correct abstention",
        "independently validated new-mechanism discovery",
        "counted only as a proposal",
        "no outcome category is folded into another",
        "never taken from the arm's own label",
        "every answer below SUPPORTED",
        "is counted only as a proposal, never as an identification, a discovery or a false "
        "discovery",
    ),
    "cmp.matching": (
        "actual realized consumption",
        "COST_UNMATCHED",
        "information exposure",
        "frozen before any arm runs and independent of outcomes",
        "reserves its maximum cost before it starts",
        "settles its realized cost after it ends",
        "checkpoints are evaluated retrospectively on settled costs",
        "straddles a checkpoint supplies nothing to it",
        "early stopping cannot move the comparison point",
        "only a labelled secondary sensitivity analysis",
    ),
    "mech.distinguishable_classes": (
        "never its name",
        "DISTINGUISHABLE, INDISTINGUISHABLE or UNRESOLVED",
        "Pairwise indistinguishability is not an equivalence relation",
        "may merge pairs transitively",
        "never a raw count of hypotheses",
        "A = 0, B = 0.75 and C = 1.50 at threshold 1",
        "it is not invariant under near-duplicates",
        "{0, 0.9, 1.8, 2.7} at threshold 1 giving diversity 2 that rises to 3",
        "diversity 2 (neither 1 nor 3)",
    ),
    "mech.search_space_expansion": (
        "tested for adequacy",
        "never by its rank among the held mechanisms",
        "a larger budget never relaxes the criterion",
    ),
    "gov.product_category": (
        "is a valid operational termination but not a completed experimental campaign",
        "stopped safely before any experiment ran",
        "never a discovery",
    ),
    "life.campaign_states": (
        "operational termination",
        "experimental completion",
        "scientific acceptance",
    ),
    "sec.autonomy_levels": ("authorizes actions and spending only", "creates no evidence"),
    "loop.stop_insufficient": (
        "INSUFFICIENT_VALIDATION",
        "STOPPED",
        "success of governance",
        "valid operational termination",
        "never a discovery",
    ),
    "cwg.exclusive_confirmation": ("exclusive confirmation authority", "only path to CONFIRMED"),
    "hyp.epistemic_stages": (
        "exploratory idea",
        "testable hypothesis",
        "evidence-supported conclusion",
        "Discovery may propose but never confirm",
        "Hypotheses and scientific claims, and only they",
        "carry no epistemic stage",
        "that authorization admits nothing",
    ),
    "reg.envelope_registration": (
        "ResearchEnvelope",
        "without a per-registration human action",
        "are never inside an envelope",
    ),
    "reg.envelope_limits": (
        "never weakens the independent authorization of consequential conclusions",
        "never replaces an individual signed authorization that an inherited rule requires",
        "OD-14",
    ),
    "gov.precedence": ("inherited text wins on any conflict", "spec issue"),
    "gov.not_active": ("CANDIDATE — NOT ACTIVE", "Independent Chief Auditor"),
}
CONTRADICTIONS = (
    re.compile(r"READY_FOR_REAL_RESEARCH\s*=\s*true", re.I),
    re.compile(r"Status:\s*\*\*ACTIVE"),
    re.compile(r"\bG0 (?:is )?PASSED\b"),
    re.compile(r"\bSAI 3\.5 is (?:now )?active\b", re.I),
)
REQ = re.compile(r"\bS35-(?!ISSUE-)([A-Z]+)-(\d{3})\b")
TEST = re.compile(r"\bT-S35-[A-Z]+-\d{3}\b")
OLD = re.compile(r"\bD-(\d{3})\b")
STATEMENT = re.compile(r"<!-- statement: ([\w.]+) -->\n\*\*(S35-[A-Z]+-\d{3}) (MUST|SHOULD)\*\*")
SUBSECTION = re.compile(r"^### (3\.\d+) ", re.M)
EVIDENCE = re.compile(r"^(?:([0-9a-f]{7,40}):)?([\w./-]+)$")
CHANGE_ROW = re.compile(r"^\| (D-\d{3}) \| `([\w.]+)` \| (\w+) \| ([^|]*) \| [^|]+ \|$", re.M)


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def changed_paths() -> set[str]:
    """Paths the working tree changes relative to the base, as the SAI 3.4 checker sees them."""
    diff = git("diff", "--name-only", BASE_REVISION)
    assert diff.returncode == 0, f"base commit {BASE_REVISION} unavailable: {diff.stderr}"
    untracked = git("ls-files", "--others", "--exclude-standard").stdout
    return (set(diff.stdout.splitlines()) | set(untracked.splitlines())) - {""}


def code_mentions() -> list[str]:
    """Files under the code directories that mention an S35 requirement identifier."""
    found = []
    for directory in CODE_DIRS:
        for path in sorted((ROOT / directory).rglob("*")):
            if path.suffix in CODE_SUFFIXES and REQ.search(
                path.read_text(encoding="utf-8", errors="replace")
            ):
                found.append(str(path.relative_to(ROOT)))
    return found


def evidence_status(registry: dict) -> dict[str, bool | None]:
    """True: exists; False: missing; None: its commit is not in this clone (not verifiable)."""
    result: dict[str, bool | None] = {}
    commits: dict[str, bool] = {}
    for statement in registry["normative_statements"]:
        for ref in statement["evidence"]:
            match = EVIDENCE.match(ref)
            if not match:
                result[ref] = False
                continue
            sha, path = match.groups()
            if sha is None:
                result[ref] = (ROOT / path).exists()
                continue
            if sha not in commits:
                commits[sha] = git("cat-file", "-e", f"{sha}^{{commit}}").returncode == 0
            result[ref] = (git("cat-file", "-e", ref).returncode == 0) if commits[sha] else None
    return result


def load() -> dict:
    registry = yaml.safe_load(read(REGISTRY))
    paths = [*registry["documents"], ACTIVE_SPEC, WORKFLOW, CANDIDATE_PATHS]
    return {
        "registry": registry,
        "texts": {path: read(path) for path in paths},
        "protected": {path: (ROOT / path).read_bytes() for path in PROTECTED},
        "changed": changed_paths(),
        "code_mentions": code_mentions(),
        "evidence": evidence_status(registry),
        "semantic": semantic_reference(),
    }


def semantic_reference() -> str:
    """Run the executable definitions and counterexamples, and their wrong-variant self-test."""
    run = subprocess.run(
        [sys.executable, "-I", str(ROOT / SEMANTIC_REFERENCE), "--self-test"],
        capture_output=True,
        text=True,
    )
    return "OK" if run.returncode == 0 else (run.stdout + run.stderr).strip()


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def paragraph(spec: str, req: str, level: str = "MUST") -> str:
    """The statement paragraph (without its comment line) that starts with the bold identifier."""
    for block in spec.split("\n\n"):
        lines = block.strip().split("\n", 1)
        if len(lines) == 2 and lines[1].startswith(f"**{req} {level}**"):
            return flat(lines[1])
    raise AssertionError(f"no statement paragraph for {req}")


def composed(s: dict) -> str:
    return flat(
        f"**{s['requirement_id']} {s['level']}** — {s['text']} "
        f"*Acceptance ({s['planned_tests'][0]}, {s['acceptance_kind']}):* {s['acceptance']}"
    )


def trace_row(s: dict) -> str:
    return (
        f"| {s['requirement_id']} | `{s['key']}` | {s['owner_component']} | "
        f"{s['planned_tests'][0]} | {', '.join(s['gates'])} | {s['phase']} | {s['status']} |"
    )


def inherited_row(s: dict) -> str:
    inherited = s["inherited"]
    return (
        f"| {s['requirement_id']} | {', '.join(inherited['sai34']) or '—'} | "
        f"{', '.join(inherited['sai33']) or '—'} | {', '.join(s['replaces']) or 'new'} |"
    )


def table_rows(text: str, first: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith(f"| {first} |")]


def check(state: dict) -> None:  # one linear list of document rules
    data, texts, protected = state["registry"], state["texts"], state["protected"]
    spec = texts[MASTER]

    # 1. The candidate declares itself inactive and changes nothing that is active.
    assert data["spec_version"] == VERSION, "spec version"
    assert data["status"] == "CANDIDATE", "registry status must be CANDIDATE"
    assert data["activation_status"] == "NOT_ACTIVE", "registry must say NOT_ACTIVE"
    assert data["integrated"] is False, "the candidate is not integrated"
    assert data["owner_approval"] == "PENDING", "no Owner approval exists"
    assert data["ready_for_real_research"] is False, "READY_FOR_REAL_RESEARCH stays false"
    assert data["g0_status"] == "NOT_PASSED", "G0 is not passed"
    assert data["changes_sai34"] is False and data["changes_g0_g9"] is False, "no SAI 3.4 change"
    assert data["base_revision"] == BASE_REVISION, "base revision"
    assert data["spec_document"] == MASTER, "master document"
    assert data["deferred_rationale"] and data["review_trigger"], "deferral fields"
    date.fromisoformat(data["review_at"])
    for path, expected in PROTECTED.items():
        assert hashlib.sha256(protected[path]).hexdigest() == expected, f"changed: {path}"
    assert yaml.safe_load(texts[ACTIVE_SPEC]) == ACTIVE_SPEC_VALUES, "ACTIVE_SPEC.yaml values"
    assert "3.5" not in texts[ACTIVE_SPEC] and "sai35" not in texts[ACTIVE_SPEC]
    for path in ("docs/normative_statements.yaml", "docs/milestones.yaml"):
        assert not REQ.search(protected[path].decode("utf-8")), f"S35 identifier in {path}"
    assert not state["code_mentions"], f"S35 identifiers in code: {state['code_mentions']}"

    status = [line for line in spec.splitlines() if line.startswith("Status:")]
    assert len(status) == 1, "exactly one status line in the master"
    for term in ("CANDIDATE — NOT ACTIVE", "Not integrated", "does not change SAI 3.4", "G0–G9"):
        assert term in status[0], f"status line lacks {term!r}"
    assert "`READY_FOR_REAL_RESEARCH = false`" in spec, "master must state readiness false"
    assert "G0 is NOT PASSED" in spec, "master must state G0 is NOT PASSED"
    for path, text in texts.items():
        if path not in (ACTIVE_SPEC, WORKFLOW, CANDIDATE_PATHS):
            assert VERSION in text, f"version missing in {path}"
        for pattern in CONTRADICTIONS:
            assert not pattern.search(text), f"{path}: {pattern.pattern}"

    # 2. Every S35 statement in the master agrees with the registry, and identifiers are unique.
    statements = data["normative_statements"]
    by_id = {s["requirement_id"]: s for s in statements}
    pairs = STATEMENT.findall(spec)
    md_ids = [req for _, req, _ in pairs]
    md_keys = [key for key, _, _ in pairs]
    assert len(md_ids) == len(set(md_ids)) and len(md_keys) == len(set(md_keys)), "duplicate"
    assert len(by_id) == len(statements), "duplicate requirement_id in the registry"
    assert len({s["key"] for s in statements}) == len(statements), "duplicate key in registry"
    assert [s["requirement_id"] for s in statements] == md_ids, "registry order or set differs"
    assert {(k, r, lvl) for k, r, lvl in pairs} == {
        (s["key"], s["requirement_id"], s["level"]) for s in statements
    }, "master statements and registry differ"
    assert list(data["areas"]) == list(AREAS), "areas changed"
    per_area = Counter()
    subsections = [(m.start(), m.group(1)) for m in SUBSECTION.finditer(spec)]
    for match in STATEMENT.finditer(spec):
        s = by_id[match.group(2)]
        area, number = REQ.match(s["requirement_id"]).groups()
        per_area[area] += 1
        assert area == s["area"] and int(number) == per_area[area], f"ID sequence: {match.group(2)}"
        owner = [name for pos, name in subsections if pos < match.start()]
        assert owner and owner[-1] == s["section"] == data["areas"][area]["section"], (
            f"{s['requirement_id']} is not in its section"
        )
        assert paragraph(spec, s["requirement_id"], s["level"]) == composed(s), (
            f"statement text differs from the registry: {s['requirement_id']}"
        )

    # 3. Registry rows are complete and claim no runtime evidence.
    sai34 = yaml.safe_load(protected[SAI34_REGISTRY])
    asm_ids = {row["requirement_id"] for row in sai34["normative_statements"]}
    activation = yaml.safe_load(protected[SAI34_ACTIVATION])
    sai33_ids = set(activation["inherited_profile"]["requirement_test_bindings"])
    assert data["status_values"] == STATUS_VALUES, "status vocabulary"
    for s in statements:
        req = s["requirement_id"]
        assert s["level"] in ("MUST", "SHOULD"), req
        assert s["tests"] == [], f"{req}: a candidate cannot claim executed tests"
        assert s["planned_tests"] == [f"T-{req}"], req
        assert s["text"] and s["acceptance"] and s["acceptance_kind"] and s["missing"], req
        assert s["status"] in STATUS_VALUES, f"{req}: status {s['status']!r}"
        if s["status"] in ("complete", "partial"):
            assert s["evidence"], f"{req}: {s['status']} needs evidence"
        for ref in s["evidence"]:
            assert state["evidence"].get(ref) is not False, f"{req}: evidence missing: {ref}"
        assert s["owner_component"] in data["components"], f"{req}: unknown component"
        assert s["phase"] in data["roadmap_phases"], f"{req}: unknown phase"
        assert s["gates"] and set(s["gates"]) <= set(data["gates"]), f"{req}: unknown gate"
        assert set(s["inherited"]["sai34"]) <= asm_ids, f"{req}: unknown SAI 3.4 obligation"
        assert set(s["inherited"]["sai33"]) <= sai33_ids, f"{req}: unknown SAI 3.3 requirement"
        assert set(s["replaces"]) <= set(RETIRED), f"{req}: unknown retired identifier"

    # 4. Traceability, status and inherited-links rows.
    for s in statements:
        req = s["requirement_id"]
        assert trace_row(s) in texts[TRACE].splitlines(), f"traceability row drifted: {req}"
        rows = table_rows(texts[STATUS_DOC], req)
        assert len(rows) == 1 and rows[0].startswith(f"| {req} | {s['status']} |"), (
            f"implementation-status row drifted: {req}"
        )
        assert inherited_row(s) in texts[COMPAT].splitlines(), f"inherited row drifted: {req}"

    # 5. Every retired D-NNN is mapped, audited and counted.
    rows = {m.group(1): m.groups()[1:] for m in CHANGE_ROW.finditer(texts[CHANGES])}
    assert sorted(rows) == RETIRED, f"change register lacks {sorted(set(RETIRED) - set(rows))}"
    actions = Counter()
    for old, (_key, action, new_text) in rows.items():
        assert action in ACTIONS, f"{old}: action {action!r}"
        actions[action] += 1
        new = [] if new_text.strip() == "—" else [x.strip() for x in new_text.split(",")]
        assert set(new) <= set(by_id), f"{old}: unregistered successor {new}"
        assert set(new) == {s["requirement_id"] for s in statements if old in s["replaces"]}, (
            f"{old}: change register and registry 'replaces' disagree"
        )
        expected_count = {"split": None, "removed": 0}.get(action, 1)
        if expected_count is None:
            assert len(new) >= 2, f"{old}: a split needs two or more successors"
        else:
            assert len(new) == expected_count, f"{old}: {action} needs {expected_count} successor"
        if action == "merged":
            assert len(by_id[new[0]]["replaces"]) >= 2, f"{old}: merge into a single source"
        audit_line = f"Action: **{action}** → {', '.join(new)}"
        assert f"### {old} — `" in texts[AUDIT] and audit_line in texts[AUDIT], f"audit: {old}"
    new_reqs = [s for s in statements if not s["replaces"]]
    new_section = texts[CHANGES].split("## 4.", 1)[1].split("## 5.", 1)[0]
    listed_new = {line.split("|")[1].strip() for line in new_section.splitlines()
                  if line.startswith("| S35-")}  # fmt: skip
    assert listed_new == {s["requirement_id"] for s in new_reqs}, "new-requirement table drifted"
    for action in ACTIONS:
        assert f"| {action} | {actions[action]} |" in texts[CHANGES], f"summary count: {action}"
    totals = (
        f"**{len(RETIRED)} old requirements → {len(statements)} SAI 3.5 requirements.**",
        f"**{len(new_reqs)} requirements are new**",
    )
    for total in totals:
        assert total in texts[CHANGES], f"change-register totals stale: {total}"
    counts = data["counts"]
    assert counts["retired"] == len(RETIRED) and counts["requirements"] == len(statements)
    assert counts["new_requirements"] == len(new_reqs), "registry counts: new"
    assert counts["audit_actions"] == {k: v for k, v in actions.items() if v}, "audit counts"
    assert counts["status"] == dict(Counter(s["status"] for s in statements)), "status counts"

    # 6. Required sections and their load-bearing content.
    capabilities = data["capabilities"]
    assert [c["id"] for c in capabilities] == [f"CAP-{n:02}" for n in range(1, 13)], "12 CAPs"
    for c in capabilities:
        assert c["requirements"] and set(c["requirements"]) <= set(by_id), c["id"]
        assert c["gates"] and set(c["gates"]) <= set(data["gates"]), c["id"]
        row = next(
            (x for x in spec.splitlines() if x.startswith(f"| {c['id']} | {c['name']} |")), ""
        )
        tail = f"| {', '.join(c['requirements'])} | {', '.join(c['gates'])} | no |"
        assert row.endswith(tail), f"capability row missing or drifted: {c['id']}"
    assert "### 2.2 The twelve capabilities" in spec, "capability section"
    by_key = {s["key"]: s for s in statements}
    for key, phrases in REQUIRED_PHRASES.items():
        assert key in by_key, f"required statement missing: {key}"
        text = paragraph(spec, by_key[key]["requirement_id"], by_key[key]["level"])
        for phrase in phrases:
            assert phrase in text, f"{key} lacks {phrase!r}"
    assert "## 4. Acceptance check" in texts[DEPLOYMENT], "no-coding-agent acceptance procedure"
    assert data["production_depends_on_external_coding_agent"] is False, "coding-agent flag"
    assert data["gd_framework"] == GD_FRAMEWORK, "G-D framework flags changed"
    assert data["gd_levels"] == [f"G-D{n}" for n in range(5)], "G-D levels"
    for level in data["gd_levels"]:
        assert f"| {level} |" in texts[ACCEPTANCE], f"acceptance-gd lacks {level}"
    assert data["comparison_arms"] == ARMS, "comparison arms changed"
    for letter, name in ARMS.items():
        assert f"**{letter} — {name}**" in texts[PROTOCOL], f"arm {letter} missing from protocol"
    assert data["metrics"] == METRICS, "metric list changed"
    for metric in METRICS:
        assert f"**{metric}**" in texts[PROTOCOL], f"metric {metric!r} missing from protocol"
    assert data["stop_outcomes"] == ["INSUFFICIENT_VALIDATION", "STOPPED"], "stop outcomes"
    assert data["stop_outcome_is_governance_success"] is True, "stop is governance success"
    assert data["confirmed_only_via"] == "causal_warrant_gate", "CONFIRMED only via the gate"
    assert data["epistemic_stages"] == EPISTEMIC_STAGES, "three epistemic stages"
    assert data["envelope"] == ENVELOPE, "envelope flags changed"
    assert data["licensed_products"] == ["CHARGE", "MODE", "FDTD", "INTERCONNECT"], "products"
    assert data["owner_gates"] == ["money", "licenses", "physical_experiments", "publication"]
    assert data["human_account_roles"] == ["ADMIN", "MEMBER"], "only ADMIN and MEMBER"
    assert data["unresolved_security_decisions"] == ["A3", "A9", "A12"], "A3/A9/A12 open"
    for field, path in STATE_TABLES.items():
        assert data[field], field
        for name in data[field]:
            assert f"| `{name}` |" in texts[path], f"{field}: {name} not tabled in {path}"

    # 6b. Candidate.2 semantics: executable counterexamples, registry flags and their documents.
    assert state["semantic"] == "OK", f"semantic reference failed: {state['semantic']}"
    assert data["distinguishability"] == DISTINGUISHABILITY, "distinguishability flags changed"
    assert data["matched_cost"] == MATCHED_COST, "matched-cost flags changed"
    assert data["epistemic_stage_scope"] == EPISTEMIC_STAGE_SCOPE, "epistemic stage scope changed"
    assert data["termination_dimensions"] == TERMINATION_DIMENSIONS, "termination dimensions"
    assert data["evaluation_outcomes"] == EVALUATION_OUTCOMES, "evaluation outcomes changed"
    assert data["evidence_levels"] == EVIDENCE_LEVELS, "evidence levels changed"
    assert data["credit_requires_evidence_level"] == "SUPPORTED", "credit without evidence"
    assert data["evidence_level_source"] == "evaluator_rederived_from_trace", "self-declared"
    for level in EVIDENCE_LEVELS:
        assert f"| `{level}` |" in texts[DISTINGUISH], f"evidence level {level} not tabled"
    for ce in S4_COUNTEREXAMPLES:
        assert f"| {ce} |" in texts[DISTINGUISH], f"Appendix S lacks counterexample {ce}"
    for outcome in EVALUATION_OUTCOMES:
        assert f"| `{outcome}` |" in texts[DISTINGUISH], f"outcome {outcome} not tabled"
    for claim in ("Near-duplicates cannot raise", "non-gameable", "near-duplicate invariant"):
        for path in NORMATIVE_TEXTS:
            assert claim not in texts[path], f"{path}: unsupported guarantee {claim!r}"
    for ce in S1_COUNTEREXAMPLES:
        assert f"| {ce} |" in texts[DISTINGUISH], f"Appendix S lacks counterexample {ce}"
    for ce in S2_COUNTEREXAMPLES:
        assert f"| {ce} |" in texts[PROTOCOL], f"Appendix J lacks counterexample {ce}"
    for value in DISTINGUISHABILITY["verdicts"]:
        assert f"| `{value}` |" in texts[DISTINGUISH], f"verdict {value} not tabled in Appendix S"
    for dimension, values in TERMINATION_DIMENSIONS.items():
        if dimension != "stop_before_experiment":
            row = next((x for x in texts[LIFECYCLE].splitlines()
                        if x.startswith(f"| {dimension.replace('_', ' ')} |")), "")  # fmt: skip
            assert row and all(f"`{v}`" in row for v in values), f"lifecycle lacks {dimension}"
    assert "| MechanismClassPartition |" not in texts[RECORDS], "transitive partition record"
    records = texts[RECORDS].split("## 2. Records", 1)[1].split("## 3.", 1)[0]
    staged = {line.split("|")[1].strip() for line in records.splitlines()
              if line.startswith("| ") and "stage =" in line}  # fmt: skip
    assert staged == {"ExploratoryIdea", "Hypothesis"}, f"stage field outside its scope: {staged}"
    assert "## 9. Authorization ladder" in texts[GOVERNANCE], "authorization ladder missing"
    assert "### 3.6 Adversarial examples" in texts[PROTOCOL], "matched-cost adversarial examples"
    assert "### 3.5 Secondary sensitivity analyses (never primary)" in texts[PROTOCOL]
    for path in NORMATIVE_TEXTS:
        for match in re.finditer(r"equivalence class", flat(texts[path])):
            before = flat(texts[path])[max(0, match.start() - 8) : match.start()]
            assert before.endswith(("not an ", "no ")), f"{path}: equivalence class asserted"
    rows = [
        x for x in texts[CONSISTENCY].splitlines() if REQ.match(x[2:] if x.startswith("| ") else "")
    ]
    assert sorted({REQ.match(x[2:]).group(0) for x in rows}) == sorted(by_id), (
        "semantic consistency report must assess every requirement exactly once"
    )
    assert len(rows) == len(by_id), "semantic consistency report has duplicate rows"

    # 7. Appendices, components, phases, decisions and spec issues.
    for appendix in data["appendices"]:
        path, authority = appendix["path"], appendix["authority"]
        assert authority in ("normative", "informative") and path in data["documents"], path
        name = Path(path).name
        nav = f"| {appendix['id']} | [{name}](sai35/{name}) | {authority} |"
        assert nav in spec, f"navigation row missing or authority drifted: {name}"
        assert re.search(rf"^Authority: {authority}\b", texts[path], re.M), f"authority: {name}"
    for component in data["components"]:
        assert f"| {component} |" in texts[ARCHITECTURE], f"component not specified: {component}"
    for phase in data["roadmap_phases"]:
        assert f"| {phase} |" in texts[ROADMAP], f"roadmap lacks {phase}"
    assert data["decision_statuses"] == dict.fromkeys(data["owner_decisions"], "OPEN"), "OD open"
    for decision in data["owner_decisions"]:
        row = next(
            (x for x in texts[DECISIONS].splitlines() if x.startswith(f"| {decision} |")), ""
        )
        assert row.endswith("| OPEN |"), f"decision {decision} missing or not OPEN"
    for issue in data["open_spec_issues"]:
        assert table_rows(texts[ISSUES], issue), f"spec issue missing: {issue}"

    # 8. CI runs this checker beside the SAI 3.4 checkers; the SAI 3.4 activation checker runs only
    #    through the OD-10 proposal A' wrapper, on the tree without the candidate.
    steps = yaml.safe_load(texts[WORKFLOW])["jobs"]["spec-conformance"]["steps"]
    runs = [str(step.get("run", "")) for step in steps]
    wrapped = (
        f"python {BOUNDARY_WRAPPER} --self-test -- python docs/spec/sai34/check_activation.py "
        "--self-test"
    )
    for command in ("docs/spec/sai34/check_candidate.py --self-test", wrapped,
                    "docs/spec/sai35/check_candidate.py --self-test"):  # fmt: skip
        assert any(command in run for run in runs), f"CI lacks {command}"
    for run in runs:
        if "check_activation.py" in run:
            assert run.strip() == wrapped, f"SAI 3.4 checker run outside the wrapper: {run!r}"

    # 9. candidate-paths.txt lists exactly what the candidate changes (ci.yml excepted).
    listed = [
        line.strip()
        for line in texts[CANDIDATE_PATHS].splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert listed == sorted(set(listed)), "candidate-paths.txt must be sorted and unique"
    assert set(listed) == state["changed"] - {WORKFLOW}, (
        "candidate-paths.txt differs from the actual changed paths: "
        f"unlisted {sorted(state['changed'] - {WORKFLOW} - set(listed))}, "
        f"listed but unchanged {sorted(set(listed) - state['changed'])}"
    )
    forbidden = ("src/", "migrations/", "tests/", "scripts/", ".github/", "docs/spec/sai34/")
    for path in listed:
        assert path not in PROTECTED and not path.startswith(forbidden), path

    # 10. References resolve: S35 identifiers, planned tests, retired identifiers, local links.
    planned = {s["planned_tests"][0] for s in statements}
    for path, text in texts.items():
        dangling = {m.group(0) for m in REQ.finditer(text)} - set(by_id)
        assert not dangling, f"{path} references unregistered {sorted(dangling)}"
        assert not set(TEST.findall(text)) - planned, f"{path}: unknown planned test"
        bad_old = {f"D-{n}" for n in OLD.findall(text) if not 1 <= int(n) <= len(RETIRED)}
        assert not bad_old, f"{path} references unknown retired identifiers {sorted(bad_old)}"
        for target in re.findall(r"\]\(([^)]+)\)", text):
            parsed = urlsplit(target)
            if parsed.scheme or not parsed.path:
                continue
            local = ((ROOT / path).parent / unquote(parsed.path)).resolve()
            assert local.is_relative_to(ROOT) and local.is_file(), (path, target)
    assert not re.search(r"\*\*D-\d{3} (?:MUST|SHOULD)\*\*", spec), "retired statement in master"


def _replace(path: str, old: str, new: str) -> Callable[[dict], None]:
    """Replace `old` in a document; whitespace in `old` also matches a line break (wrapped text)."""
    pattern = re.compile(r"\s+".join(re.escape(word) for word in old.split(" ")))

    def mutate(state: dict) -> None:
        damaged, count = pattern.subn(lambda _: new, state["texts"][path])
        assert count, f"self-test anchor missing: {old!r}"
        state["texts"][path] = damaged

    return mutate


def _set(*keys: str, value: object) -> Callable[[dict], None]:
    def mutate(state: dict) -> None:
        target = state["registry"]
        for key in keys[:-1]:
            target = target[key]
        target[keys[-1]] = value

    return mutate


def _row(index: int, **changes: object) -> Callable[[dict], None]:
    return lambda state: state["registry"]["normative_statements"][index].update(changes)


def _protected(path: str) -> Callable[[dict], None]:
    def mutate(state: dict) -> None:
        state["protected"][path] = state["protected"][path] + b"\n"

    return mutate


def _first_line(path: str, prefix: str, new: str) -> Callable[[dict], None]:
    def mutate(state: dict) -> None:
        lines = state["texts"][path].splitlines()
        index = next(i for i, line in enumerate(lines) if line.startswith(prefix))
        lines[index] = new
        state["texts"][path] = "\n".join(lines)

    return mutate


def _both(old: str, new: str) -> Callable[[dict], None]:
    """Change a phrase in the master AND in the registry, so only the required-phrase rule can
    catch it (a one-sided edit is already caught as registry drift)."""

    def mutate(state: dict) -> None:
        _replace(MASTER, old, new)(state)
        hits = 0
        for row in state["registry"]["normative_statements"]:
            for field in ("text", "acceptance"):
                if old in row[field]:
                    row[field] = row[field].replace(old, new)
                    hits += 1
        assert hits, f"self-test anchor missing in registry: {old!r}"

    return mutate


MUTATIONS: dict[str, Callable[[dict], None]] = {
    # registry state
    "registry_active": _set("activation_status", value="ACTIVE"),
    "readiness": _set("ready_for_real_research", value=True),
    "integrated": _set("integrated", value=True),
    "g0_passed": _set("g0_status", value="PASSED"),
    "g0_g9_implies_discovery": _set(
        "gd_framework", "g0_g9_completion_implies_discovery", value=True
    ),
    "synthetic_is_real": _set(
        "gd_framework", "synthetic_success_is_real_discovery_validation", value=True
    ),
    "level_evaluated": _set("gd_framework", "evaluated_levels", value=["G-D1"]),
    "arm_removed": lambda s: s["registry"]["comparison_arms"].pop("A"),
    "metric_removed": lambda s: s["registry"]["metrics"].remove("independent reproducibility"),
    "envelope_authorizes_conclusions": _set("envelope", "authorizes_conclusions", value=True),
    "coding_agent_dependency": _set("production_depends_on_external_coding_agent", value=True),
    "decision_closed": _set("decision_statuses", "OD-10", value="CLOSED"),
    "stage_removed": lambda s: s["registry"]["epistemic_stages"].pop(),
    "capability_removed": lambda s: s["registry"]["capabilities"].pop(),
    # statements and registry rows
    "duplicate_id": _row(1, requirement_id="S35-GOV-001"),
    "missing_yaml_statement": lambda s: s["registry"]["normative_statements"].pop(),
    "runtime_test_claim": _row(0, tests=["T-S35-GOV-001"]),
    "bad_status": _row(3, status="done"),
    "partial_without_evidence": _row(5, evidence=[]),
    "unknown_component": _row(4, owner_component="Oracle"),
    "unknown_phase": _row(4, phase="P35-11"),
    "unknown_gate": _row(4, gates=["G10"]),
    "unknown_asm": _row(0, inherited={"sai34": ["ASM-099"], "sai33": []}),
    "unknown_sai33": _row(0, inherited={"sai34": [], "sai33": ["XYZ-001"]}),
    "unknown_retired": _row(0, replaces=["D-047"]),
    "text_drift": _row(2, text="LIB is a chatbot."),
    "acceptance_drift": _row(2, acceptance="none."),
    "section_mismatch": _row(6, section="3.9"),
    "trace_drift": _row(7, phase="P35-9"),
    "status_drift": _row(7, status="blocked"),
    "evidence_missing": lambda s: s["evidence"].update(
        {s["registry"]["normative_statements"][5]["evidence"][0]: False}
    ),
    "s35_in_code": lambda s: s["code_mentions"].append("src/lab_brain/discovery/x.py"),
    # master text
    "extra_md_statement": _replace(
        MASTER,
        "## 4. What would falsify",
        "<!-- statement: extra.req -->\n**S35-CMP-010 MUST** — extra.\n\n## 4. What would falsify",
    ),
    "retired_statement_in_master": _replace(
        MASTER, "## 5. Activation boundary", "**D-001 MUST** — old.\n\n## 5. Activation boundary"
    ),
    "unknown_retired_reference": _replace(ROADMAP, "## 2. Phases", "## 2. Phases\n\nSee D-099."),
    "dangling_reference": _replace(ROADMAP, "## 2. Phases", "## 2. Phases\n\nSee S35-GOV-099."),
    "dangling_test": _replace(ROADMAP, "## 2. Phases", "## 2. Phases\n\nSee T-S35-GOV-099."),
    "status_line_active": _replace(MASTER, "**CANDIDATE — NOT ACTIVE.** Not integrated", "ACTIVE"),
    "readiness_text": _replace(
        MASTER, "`READY_FOR_REAL_RESEARCH = false`", "`READY_FOR_REAL_RESEARCH = true`"
    ),
    "g0_passed_text": _replace(DECISIONS, "## 2. Risks", "G0 PASSED\n\n## 2. Risks"),
    "capability_row_removed": _first_line(MASTER, "| CAP-07 |", "| CAP-07 | gone |"),
    "coding_agent_text_removed": _replace(MASTER, "Codex, Claude Code or any other", "some"),
    "gd_text_removed": _replace(MASTER, "never implies successful autonomous discovery", "implies"),
    "arm_text_removed": _replace(MASTER, "(A) single frontier LLM", "(A) a baseline"),
    "metric_text_removed": _replace(MASTER, "discriminating-experiment efficiency", "speed"),
    "stop_text_removed": _replace(MASTER, "success of governance", "failure"),
    "cwg_text_removed": _replace(MASTER, "exclusive confirmation authority", "an authority"),
    "stage_text_removed": _replace(MASTER, "Discovery may propose but never confirm", "anything"),
    "envelope_text_removed": _replace(
        MASTER, "without a per-registration human action", "with a human action"
    ),
    "envelope_limits_removed": _replace(
        MASTER, "never weakens the independent authorization", "may weaken the authorization"
    ),
    "acceptance_procedure_removed": _replace(DEPLOYMENT, "## 4. Acceptance check", "## 4. Notes"),
    "active_spec_values": _replace(
        ACTIVE_SPEC, "architecture_version: 3.4.0-phased.1", "architecture_version: 3.5.0"
    ),
    # protected files
    "protected_sai33": _protected("docs/spec/SAI_3.3.md"),
    "protected_sai34_activation": _protected("docs/spec/sai34/activation.yaml"),
    "protected_sai34_checker": _protected("docs/spec/sai34/check_activation.py"),
    "protected_active_spec": _protected(ACTIVE_SPEC),
    "protected_milestones": _protected("docs/milestones.yaml"),
    # appendices and tables
    "trace_row_removed": _first_line(TRACE, "| S35-SEL-001 |", "| S35-SEL-001 | gone |"),
    "inherited_row_removed": _first_line(COMPAT, "| S35-SEL-001 |", "| S35-SEL-001 | gone |"),
    "status_row_removed": _first_line(STATUS_DOC, "| S35-SEL-001 |", "| S35-SEL-001 | x | y | z |"),
    "change_row_removed": _first_line(CHANGES, "| D-017 |", "| removed |"),
    "change_action_wrong": lambda s: _replace(
        CHANGES,
        next(x for x in s["texts"][CHANGES].splitlines() if x.startswith("| D-007 |")),
        next(x for x in s["texts"][CHANGES].splitlines() if x.startswith("| D-007 |")).replace(
            "| kept |", "| removed |"
        ),
    )(s),
    "audit_section_removed": _replace(AUDIT, "### D-033 — ", "### X-033 — "),
    "summary_count_wrong": _first_line(CHANGES, "| kept |", "| kept | 99 | wrong |"),
    "appendix_authority_mismatch": _replace(
        LIFECYCLE, "Authority: normative.", "Authority: informative."
    ),
    "component_row_removed": _replace(ARCHITECTURE, "| CausalWarrantGate |", "| Gate |"),
    "phase_row_removed": _replace(ROADMAP, "| P35-6 |", "| P35-six |"),
    "decision_text_closed": _replace(
        DECISIONS,
        "off the integration line, on its own branch | OPEN |",
        "off the integration line, on its own branch | CLOSED |",
    ),
    "issue_row_removed": _first_line(ISSUES, "| S35-ISSUE-06 |", "| removed |"),
    "claim_state_row_removed": _replace(RECORDS, "| `INCONCLUSIVE` |", "| INCONCLUSIVE |"),
    "campaign_state_row_removed": _replace(LIFECYCLE, "| `REPORTING` |", "| REPORTING |"),
    "autonomy_row_removed": _replace(GOVERNANCE, "| `AL4` |", "| AL4 |"),
    "novelty_row_removed": _replace(PROVENANCE, "| `MODEL_CORRECTION` |", "| MODEL_CORRECTION |"),
    "protocol_arm_removed": _replace(PROTOCOL, "**A — single frontier LLM**", "**A**"),
    # CI, candidate paths, links
    "ci_step_removed": _replace(
        WORKFLOW, "python docs/spec/sai35/check_candidate.py --self-test", "true"
    ),
    "bare_sai34_checker_in_ci": _replace(
        WORKFLOW,
        "python docs/spec/sai35/check_sai34_boundary_without_candidate.py --self-test\n"
        "          -- python docs/spec/sai34/check_activation.py --self-test",
        "python docs/spec/sai34/check_activation.py --self-test",
    ),
    "candidate_path_unlisted": lambda s: s["changed"].add("docs/spec/sai35/extra.md"),
    "candidate_path_runtime": lambda s: s["texts"].update(
        {CANDIDATE_PATHS: s["texts"][CANDIDATE_PATHS] + "src/lab_brain/x.py\n"}
    ),
    "broken_link": _replace(ROADMAP, "## 3. Dependency picture", "[x](missing.md)\n\n## 3."),
    # candidate.2 semantics
    "semantic_reference_failed": lambda s: s.update({"semantic": "AssertionError"}),
    "transitive_merge_allowed": _set("distinguishability", "transitive_merge_allowed", value=True),
    "relation_transitive": _set("distinguishability", "relation_is_transitive", value=True),
    "unresolved_in_headline": _set(
        "distinguishability", "unresolved_counts_in_headline", value=True
    ),
    "post_hoc_matching_primary": _set("matched_cost", "min_final_cost_rule", value="primary"),
    "straddle_allowed": _set("matched_cost", "straddling_attempt_supplies_checkpoint", value=True),
    "stage_scope_universal": _set("epistemic_stage_scope", value=["every_record"]),
    "stop_counted_complete": _set(
        "termination_dimensions", "stop_before_experiment", value=["VALID", "COMPLETED", "NONE"]
    ),
    "mech_text_transitive": _both(
        "Pairwise indistinguishability is not an equivalence relation", "Classes are formed"
    ),
    "mech_counterexample_removed": _both("diversity 2 (neither 1 nor 3)", "diversity 1"),
    "matching_post_hoc_text": _both(
        "frozen before any arm runs and independent of outcomes", "chosen after the runs"
    ),
    "straddle_text_removed": _both(
        "straddles a checkpoint supplies nothing to it", "straddles a checkpoint counts"
    ),
    "stage_scope_text_removed": _both(
        "Hypotheses and scientific claims, and only they", "Every scientific object"
    ),
    "adequacy_text_removed": _both("a larger budget never relaxes the criterion", "ok"),
    "stop_called_complete": _both("valid operational termination but not a", "a"),
    "envelope_replaces_signature": _both(
        "never replaces an individual signed authorization", "replaces any authorization"
    ),
    "equivalence_class_asserted": _replace(
        ACCEPTANCE, "there is no equivalence class", "there is an equivalence class"
    ),
    "s1_counterexample_row_removed": _first_line(DISTINGUISH, "| S1-CE-1 |", "| removed |"),
    "s2_counterexample_row_removed": _first_line(PROTOCOL, "| S2-CE-2 |", "| removed |"),
    "partition_record_back": _replace(
        RECORDS, "| DistinguishabilityGraph |", "| MechanismClassPartition |"
    ),
    "stage_on_problem": _replace(
        RECORDS, "covering_envelope_id? |", "covering_envelope_id?; stage = 1 |"
    ),
    "ladder_removed": _replace(GOVERNANCE, "## 9. Authorization ladder", "## 9. Notes"),
    "termination_row_removed": _first_line(LIFECYCLE, "| experimental completion |", "| x |"),
    "consistency_row_removed": _first_line(CONSISTENCY, "| S35-CMP-002 |", "| removed |"),
    # candidate.3
    "near_duplicate_invariance_claimed": _set(
        "distinguishability", "near_duplicate_invariant", value=True
    ),
    "diversity_primary": _set("distinguishability", "diversity_role", value="primary"),
    "checkpoints_on_reservation": _set(
        "matched_cost", "checkpoint_accounting", value="charged_at_reservation"
    ),
    "overrun_tolerated": _set("matched_cost", "overrun_or_missing_headroom", value="tolerated"),
    "outcomes_merged": lambda s: s["registry"]["evaluation_outcomes"].remove(
        "INDISTINGUISHABLE_ALTERNATIVE"
    ),
    "guarantee_reasserted": _replace(
        DISTINGUISH, "What it does **not** guarantee", "Near-duplicates cannot raise it"
    ),
    "s1_ce11_removed": _first_line(DISTINGUISH, "| S1-CE-11 |", "| removed |"),
    "s2_ce7_removed": _first_line(PROTOCOL, "| S2-CE-7 |", "| removed |"),
    "outcome_row_removed": _replace(
        DISTINGUISH, "| `VALIDATED_NEW_MECHANISM` |", "| VALIDATED_NEW_MECHANISM |"
    ),
    "near_dup_text_removed": _both(
        "it is not invariant under near-duplicates", "it is invariant under near-duplicates"
    ),
    "settlement_text_removed": _both(
        "checkpoints are evaluated retrospectively on settled costs", "checkpoints use caps"
    ),
    "credit_without_evidence": _set("credit_requires_evidence_level", value="PROPOSAL"),
    "self_declared_evidence": _set("evidence_level_source", value="arm_label"),
    "evidence_level_removed": lambda s: s["registry"]["evidence_levels"].remove("SUPPORTED"),
    "s4_ce_removed": _first_line(DISTINGUISH, "| S4-CE |", "| removed |"),
    "proposal_credit_text": _both("every answer below SUPPORTED", "every answer below PROPOSAL"),
    "arm_label_trusted_text": _both(
        "never taken from the arm's own label", "taken from the arm's own label"
    ),
    "outcomes_text_merged": _both(
        "no outcome category is folded into another", "categories may be summed"
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
    rows = current["registry"]["normative_statements"]
    statuses = Counter(s["status"] for s in rows)
    evidence = current["evidence"].values()
    print(
        f"SAI 3.5 master candidate structure OK: {len(rows)} S35 requirements ("
        + ", ".join(f"{k} {statuses.get(k, 0)}" for k in STATUS_VALUES)
        + f"); {len(RETIRED)} retired D-NNN all mapped and audited; NOT ACTIVE; every SAI 3.3/3.4 "
        f"file and ACTIVE_SPEC.yaml byte-identical to {BASE_REVISION[:7]} (no exception); "
        f"candidate-paths.txt equals the {len(current['changed'] - {WORKFLOW})} changed paths; "
        "CI runs the SAI 3.4 checker only via the OD-10 proposal A' wrapper; "
        "semantic reference OK; "
        "evidence refs: "
        f"{sum(v is True for v in evidence)} verified, {sum(v is None for v in evidence)} not "
        "verifiable in this clone; no G-D level evaluated; nothing here is runtime acceptance."
    )
