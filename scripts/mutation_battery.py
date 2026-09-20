"""Targeted mutation battery — proof that the M1-P1 guards have teeth.

WHY THIS IS A COMMITTED SCRIPT rather than something run once by hand. Earlier slices ran
mutations ad hoc and recorded the result in a commit message, which is evidence that expires: it
says the guards had teeth at one commit, and nothing re-checks it. This repository has already
written down twice -- `test_conformance_guards.py`, `check_commit_messages.py` -- that a check
nobody can re-run is a claim rather than a check.

HOW IT WORKS. Each entry disables exactly one guard by a textual substitution, runs only the
tests that are supposed to depend on it, and requires them to FAIL. A mutation that survives
means one of two things, and both are defects:

    the guard does nothing            the substitution changed no behaviour
    nothing tests the guard           the behaviour changed and every test still passed

The anchor text is checked before the substitution is applied, so a refactor that moves a guard
reports ANCHOR NOT FOUND rather than silently mutating nothing and reporting a false kill.

NOT RUN IN CI. It edits source files in place, and a CI job that rewrites the checkout to prove a
point is a job that can leave the checkout rewritten. The restore is in a `finally`, but "we
restore it afterwards" is exactly the reasoning this repository declines to accept elsewhere. Run
it before a milestone gate and record the result in the readiness document.

    python scripts/mutation_battery.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: The interpreter that has the project installed. `sys.executable` would be correct when this is
#: run as `python scripts/mutation_battery.py` from the venv and wrong when it is not, and a
#: battery that silently ran against a different interpreter would report meaningless results.
PY = ROOT / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


@dataclass(frozen=True)
class Mutation:
    name: str
    guards: str
    path: str
    old: str
    new: str
    tests: tuple[str, ...]


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        name="fixed_token_becomes_primary",
        guards="§6.22 rule 3 — fixed-token splitting must not be the primary splitter",
        path="src/lab_brain/ingestion/segmentation.py",
        old="        if token_count(body) <= self._token_limit:",
        new="        if False:",
        tests=("tests/contract/test_evidence_segmentation.py",),
    ),
    Mutation(
        name="condition_result_binding_removed",
        guards="§6.22 rule 1 — the condition/result boundary binding",
        path="src/lab_brain/ingestion/segmentation.py",
        old="        joins = (_states_condition(previous) and _states_result(sentence)) or bool(\n            _DEPENDENT_OPENER.match(sentence)\n        )",
        new="        joins = False",
        tests=(
            "tests/contract/test_evidence_segmentation.py",
            "tests/contract/test_evidence_benchmark.py",
        ),
    ),
    Mutation(
        name="bound_condition_check_removed",
        guards="the declaration that makes rule 1 checkable on the record",
        path="src/lab_brain/core/models/evidence_unit.py",
        old="        severed = [text for text in self.bound_condition_texts if text not in available]",
        new="        severed = []",
        tests=("tests/contract/test_evidence_unit_identity.py",),
    ),
    Mutation(
        name="table_context_not_required",
        guards="§6.22 rule 5 — table header/unit retention",
        path="src/lab_brain/core/models/evidence_unit.py",
        old="        if self.unit_type is EvidenceUnitType.TABLE and self.table_context is None:",
        new="        if False:",
        tests=("tests/contract/test_evidence_unit_identity.py",),
    ),
    Mutation(
        name="figure_prose_not_required",
        guards="§6.22 rule 6 — a caption alone is not sufficient",
        path="src/lab_brain/core/models/evidence_unit.py",
        old="        return bool(self.caption) and bool(self.surrounding_prose)",
        new="        return bool(self.caption)",
        tests=(
            "tests/contract/test_evidence_segmentation.py",
            "tests/contract/test_evidence_benchmark.py",
        ),
    ),
    Mutation(
        name="canonical_body_not_reresolved",
        guards="EVI-010 — canonical evidence vs retrieval payload separation",
        path="src/lab_brain/ingestion/admission_gate.py",
        old="        if request.claimed_body is not None and request.claimed_body != unit.body:",
        new="        if False:",
        tests=("tests/contract/test_retrieval_boundary.py",),
    ),
    Mutation(
        name="inference_admitted_as_fact",
        guards="EVI-003 — an LLM inference may not be admitted as observed/simulated/measured",
        path="src/lab_brain/ingestion/admission_gate.py",
        old="        if attestation.epistemic_type in INFERENCE_FORBIDDEN_TYPES:",
        new="        if False:",
        tests=("tests/contract/test_evidence_admission.py",),
    ),
    Mutation(
        name="reference_not_required_at_admission",
        guards="EVI-009 — MEASURED/SIMULATED must reference their Run/Artifact at admission",
        path="src/lab_brain/ingestion/admission_gate.py",
        old="        if attestation.epistemic_type not in REFERENCE_REQUIRED_TYPES:\n            return",
        new="        if True:\n            return",
        tests=("tests/contract/test_evidence_admission.py",),
    ),
    Mutation(
        name="secret_scan_after_raw_store",
        guards="SEC-003 — the scan runs before anything becomes addressable",
        path="src/lab_brain/ingestion/pipeline.py",
        old="        if not scan.may_reach_normal_storage:\n            return outcome",
        new="        if False:\n            return outcome",
        tests=("tests/security/test_secret_scan_ordering.py",),
    ),
    Mutation(
        name="no_compensation_on_promote_failure",
        guards="OPS-004 — the cross-store compensating unit of work",
        path="src/lab_brain/ingestion/pipeline.py",
        old="                self._rollback_rows(artifact, occurrence)",
        new="                pass",
        tests=("tests/integration/test_cross_store_compensation.py",),
    ),
    Mutation(
        name="unknown_counts_as_independent",
        guards="EVI-004 / §6.17 — DEPENDENCE_UNKNOWN contributes 0",
        path="src/lab_brain/evidence/independence.py",
        old="            if relation is IndependenceRelation.UNKNOWN:\n                has_unknown_relation = True",
        new="            if False:\n                has_unknown_relation = True",
        tests=("tests/contract/test_source_work_resolution.py",),
    ),
    Mutation(
        name="same_work_counted_twice",
        guards="EVI-004 — corroboration must not double-count one work",
        path="src/lab_brain/evidence/independence.py",
        old="        if work in seen_works:\n            dependent += 1\n            continue",
        new="        if False:\n            dependent += 1\n            continue",
        tests=("tests/contract/test_source_work_resolution.py",),
    ),
    Mutation(
        name="heuristic_match_treated_as_independent",
        guards="EVI-004 — an unresolved same-work guess is UNKNOWN, not INDEPENDENT",
        path="src/lab_brain/ingestion/source_work_resolution.py",
        old="    if resolution.needs_review:\n        return IndependenceRelation.UNKNOWN",
        new="    if False:\n        return IndependenceRelation.UNKNOWN",
        tests=("tests/contract/test_source_work_resolution.py",),
    ),
    Mutation(
        name="baseline_units_admissible",
        guards="§6.22 rule 3(b) — a benchmark baseline unit is never evidence",
        path="src/lab_brain/ingestion/admission_gate.py",
        old="        if unit.subdivision_reason is SubdivisionReason.BENCHMARK_BASELINE:",
        new="        if False:",
        tests=("tests/contract/test_retrieval_boundary.py",),
    ),
    # `cross_project_unit_admitted` lived here until the M1-P1 repair. It anchored on
    # `unit.project_id != attestation.project_id`, a line ADR-0012 deleted: a unit no longer
    # carries a project, and presence is resolved through the occurrence. Superseded by
    # `presence_is_not_consulted` below. Removed rather than left reporting ANCHOR NOT FOUND
    # forever -- a permanently failing entry trains the reader to ignore the output.
    Mutation(
        name="retrieval_ignores_project_scope",
        guards="SEC-002 — retrieval filters by project before scoring",
        path="src/lab_brain/evidence/retriever.py",
        old="            if representation.project_id == project_id",
        new="            if True",
        tests=("tests/contract/test_retrieval_boundary.py",),
    ),
    Mutation(
        name="identity_depends_on_nothing_checked",
        guards="ADR-0011 — evidence identity is derived, not assigned",
        path="src/lab_brain/core/models/evidence_unit.py",
        old="        if self.evidence_unit_id != expected:",
        new="        if False:",
        tests=("tests/contract/test_evidence_unit_identity.py",),
    ),
    # --- M1-P1 repair (v3.3-a18). One entry per audit finding. -------------------------
    Mutation(
        name="evi003_trusts_the_caller_flag",
        guards="EVI-003 (P0) -- inference status is derived from provenance, not asserted",
        path="src/lab_brain/ingestion/admission_gate.py",
        old="        is_inference = canonical_inference or bool(request.llm_derived)",
        new="        is_inference = bool(request.llm_derived)",
        tests=("tests/contract/test_evidence_repair_probes.py",),
    ),
    Mutation(
        name="evi003_flag_contradiction_ignored",
        guards="EVI-003 (P0) -- a flag contradicting canonical provenance fails closed",
        path="src/lab_brain/ingestion/admission_gate.py",
        old="        if canonical_inference and request.llm_derived is False:",
        new="        if False:",
        tests=("tests/contract/test_evidence_repair_probes.py",),
    ),
    Mutation(
        name="evidence_link_need_not_be_durable",
        guards="17.25 (P1) -- the Attestation must record the unit, not just the call",
        path="src/lab_brain/ingestion/admission_gate.py",
        # Anchored on the COMPARISON in `_check_link_assertion_agrees`. Repair-2 moved this
        # guard: the request field is now an assertion that may only agree with the record, so
        # what has to hold is that a disagreement refuses.
        old="        if asserted != durable:",
        new="        if False:",
        tests=("tests/contract/test_evidence_repair_probes.py",),
    ),
    Mutation(
        name="segmentation_conformance_self_attested",
        guards="SPEC-ISSUE-015 (P1) -- admission re-derives rather than trusting the row",
        path="src/lab_brain/ingestion/admission_gate.py",
        old="        if match is None:",
        new="        if False:",
        tests=("tests/contract/test_evidence_repair_probes.py",),
    ),
    Mutation(
        name="re_derivation_may_be_skipped",
        guards="SPEC-ISSUE-015 (P1) -- an unverifiable admission fails closed",
        path="src/lab_brain/ingestion/admission_gate.py",
        old="        if self._resegment is None:",
        new="        if False and self._resegment is None:",
        tests=("tests/contract/test_evidence_repair_probes.py",),
    ),
    Mutation(
        name="stored_bindings_need_not_match_segmentation",
        guards="SPEC-ISSUE-015 (P1) -- stripped bindings are caught by re-derivation",
        path="src/lab_brain/ingestion/admission_gate.py",
        old="        if match.bound_condition_texts != unit.bound_condition_texts:",
        new="        if False:",
        tests=("tests/contract/test_evidence_repair_probes.py",),
    ),
    Mutation(
        name="witness_does_not_bind_contents",
        guards="17.25 (P1) -- the storage-checkable half rejects a partial forgery",
        path="src/lab_brain/core/models/evidence_unit.py",
        old="        if self.segmentation_witness != expected:",
        new="        if False:",
        tests=("tests/contract/test_evidence_repair_probes.py",),
    ),
    Mutation(
        name="presence_is_not_consulted",
        guards="SEC-002 / 17.25.1 (P1) -- a resolver answering 'not here' is obeyed",
        path="src/lab_brain/ingestion/admission_gate.py",
        # The companion to `occurrence_check_is_optional`: that one proves a MISSING resolver
        # refuses, this one proves a resolver that answers NO is not ignored. Repair-2 split the
        # single `if resolver is not None and not resolver(...)` into those two cases, so one
        # anchor can no longer cover both.
        old="        if not self._is_present_in(unit.evidence_unit_id, attestation.project_id):",
        new="        if False:",
        tests=(
            "tests/contract/test_retrieval_boundary.py",
            "tests/contract/test_evidence_repair2_probes.py",
        ),
    ),
    # --- Repair-2 (three fail-open blockers). Each anchors on the GUARD, not on a message
    # branch: every one of these was a case where the rule was correct and an input turned it off.
    Mutation(
        name="request_field_decides_whether_to_verify",
        guards="EVI-010 (P0) -- the DURABLE reference triggers verification, not the call",
        path="src/lab_brain/ingestion/admission_gate.py",
        old="        evidence_unit_id = request.attestation.evidence_unit_id",
        new="        evidence_unit_id = request.evidence_unit_id",
        tests=("tests/contract/test_evidence_repair2_probes.py",),
    ),
    Mutation(
        name="occurrence_check_is_optional",
        guards="SEC-002 / 17.25.1 (P1) -- a missing occurrence resolver fails closed",
        path="src/lab_brain/ingestion/admission_gate.py",
        old="        if self._is_present_in is None:",
        new="        if False:",
        tests=("tests/contract/test_evidence_repair2_probes.py",),
    ),
    Mutation(
        name="recorded_provenance_ignored_for_reverification",
        guards="17.25 / ADR-0012 (P1) -- re-derivation resolves the RECORDED implementation",
        path="src/lab_brain/ingestion/reverification.py",
        # Substituting the current default is precisely the defect: the body reproduces, so
        # without the registry lookup a unit claiming any segmenter version verifies.
        old="        segmenter = self._registry.segmenter_for(provenance)",
        new="        segmenter = EvidenceAwareSegmenter()",
        tests=("tests/contract/test_evidence_repair2_probes.py",),
    ),
    Mutation(
        name="reverification_token_limit_not_restored",
        guards="17.25 (P1) -- the recorded token limit travels with the segmenter version",
        path="src/lab_brain/ingestion/reverification.py",
        old="        return factory(provenance.token_limit) if factory is not None else None",
        new="        return factory(None) if factory is not None else None",
        tests=(
            "tests/contract/test_evidence_segmentation.py",
            "tests/contract/test_evidence_repair2_probes.py",
        ),
    ),
    Mutation(
        name="subdivision_lineage_may_be_partial",
        guards="§6.22 rules 3-4 — subdivision lineage is all or nothing",
        path="src/lab_brain/core/models/evidence_unit.py",
        old="        if present and len(present) != 3:",
        new="        if False:",
        tests=("tests/contract/test_evidence_unit_identity.py",),
    ),
)


def run(mutation: Mutation) -> tuple[bool, str]:
    target = ROOT / mutation.path
    # A real file copy rather than holding the source in memory: if this process is killed
    # mid-run, the backup on disk is what lets the working tree be restored by hand.
    backup = target.with_suffix(target.suffix + ".mutation-backup")
    shutil.copy2(target, backup)
    try:
        source = target.read_text(encoding="utf-8")
        if mutation.old not in source:
            return False, "ANCHOR NOT FOUND — the mutation did not apply"
        target.write_text(source.replace(mutation.old, mutation.new, 1), encoding="utf-8")

        result = subprocess.run(
            [
                str(PY),
                "-m",
                "pytest",
                *mutation.tests,
                "-q",
                "-x",
                "--no-header",
                "-p",
                "no:cacheprovider",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            tail = [
                ln
                for ln in result.stdout.strip().splitlines()
                if ln.startswith(("FAILED", "ERROR"))
            ]
            first = tail[0] if tail else result.stdout.strip().splitlines()[-1]
            return True, f"killed by {first[:100]}"
        return False, "SURVIVED — tests still pass with the guard disabled"
    finally:
        shutil.move(backup, target)


def main() -> int:
    killed = 0
    print(f"{len(MUTATIONS)} mutations\n")
    for mutation in MUTATIONS:
        ok, detail = run(mutation)
        killed += ok
        status = "KILLED " if ok else "SURVIVED"
        print(f"[{status}] {mutation.name}")
        print(f"           {mutation.guards}")
        print(f"           {detail}\n")
    print(f"{killed}/{len(MUTATIONS)} killed")
    return 0 if killed == len(MUTATIONS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
