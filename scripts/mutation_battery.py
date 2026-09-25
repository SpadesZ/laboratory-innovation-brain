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

WITH THE POSTGRES PROFILE ENABLED. Some entries are killed only by PostgreSQL-gated tests, and a
skipped test is a passing test as far as the exit code is concerned -- so a run without
`LAB_BRAIN_TEST_POSTGRES=1` and a migrated `LAB_BRAIN_DATABASE_URL` reports those guards as having
no teeth when what it actually measured is that their tests did not run.
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
    # ------------------------------------------------------------------
    # M1 completion. Each anchors on the GUARD, never on a refusal message: a mutation that only
    # reworded a refusal would be killed by a string assertion and prove nothing about the rule.
    # ------------------------------------------------------------------
    Mutation(
        name="run_manifest_may_be_partially_persisted",
        guards="§17.4 / Repair A — the whole Run manifest survives the round trip",
        path="src/lab_brain/core/repositories/jobs.py",
        old="                    _json(proposed.environment),",
        new="                    _json({}),",
        tests=("tests/integration/test_jobs_runs_postgres.py",),
    ),
    Mutation(
        name="run_linkage_need_not_match_its_job",
        guards="§17.4 / §12.5 / Repair A — a Run may not contradict the Job it completes",
        path="src/lab_brain/core/repositories/jobs.py",
        old="        check_run_linkage(job, proposed)\n\n        # EVERY §17.4 FIELD IS PASSED.",
        new="        pass\n\n        # EVERY §17.4 FIELD IS PASSED.",
        tests=("tests/integration/test_jobs_runs_postgres.py",),
    ),
    Mutation(
        name="a_failed_run_leaves_its_job_unresolved",
        guards="Repair B — one completion mechanism; a FAILED run is still claimed by its job",
        path="src/lab_brain/core/repositories/jobs.py",
        old="                JobState.FAILED if proposed.status is RunStatus.FAILED else JobState.SUCCEEDED",
        new="                JobState.SUCCEEDED if True else JobState.FAILED",
        tests=("tests/contract/test_job_lifecycle.py",),
    ),
    Mutation(
        name="run_output_artifacts_need_not_resolve",
        guards="EVI-009 / Repair C — Attestation -> Run -> produced Artifact is walked",
        path="src/lab_brain/ingestion/admission_gate.py",
        old="        if not resolved:",
        new="        if False:",
        tests=("tests/contract/test_run_backed_evidence.py",),
    ),
    Mutation(
        name="run_artifacts_need_not_be_in_this_project",
        guards="SEC-002 / ADR-0010 — a run's outputs must have an occurrence in the project",
        path="src/lab_brain/ingestion/admission_gate.py",
        old="            if not present:",
        new="            if False:",
        tests=("tests/contract/test_run_backed_evidence.py",),
    ),
    Mutation(
        name="embedding_spaces_may_be_mixed",
        guards="EVI-007 / §6.13 — a cross-space cosine is silent garbage",
        path="src/lab_brain/evidence/dense_index.py",
        old="        if not space.compatible_with(self._space):",
        new="        if False:",
        tests=("tests/contract/test_dense_retrieval.py",),
    ),
    Mutation(
        name="cutover_may_promote_without_measuring",
        guards="EVI-007 / §6.20 — benchmark recall is verified before cutover",
        path="src/lab_brain/evidence/dense_index.py",
        old="        if self._report.recall < self.recall_floor:",
        new="        if False:",
        tests=("tests/contract/test_dense_retrieval.py",),
    ),
    Mutation(
        name="unavailable_source_status_reads_as_valid",
        guards="EVI-008 / §6.21 — 'could not ask' is not 'asked and it is fine'",
        path="src/lab_brain/evidence/source_status.py",
        old="        permissive = [s for s in INDETERMINATE_STATUSES if table[s] is RevisionOutcome.ALLOW]",
        new="        permissive = []",
        tests=("tests/integration/test_source_status_postgres.py",),
    ),
    Mutation(
        name="policy_block_may_be_auto_retried",
        guards="UX-002 / §17.23 — a retry loop against an ACL is indistinguishable from an attack",
        path="src/lab_brain/surface/errors.py",
        old="    if error_class not in AUTO_RETRYABLE:\n        return False",
        new="    if False:\n        return False",
        tests=("tests/contract/test_ingestion_surfaces.py",),
    ),
    Mutation(
        name="budget_exhaustion_classifies_as_failed",
        guards="UX-002 / §17.23 — budget exhaustion is POLICY_BLOCK, not FAILED",
        path="src/lab_brain/surface/errors.py",
        # Re-anchored after the fail-closed repair restructured this branch. The guard is
        # the RECLASSIFICATION -- a budget stop needs an approver, not an engineer -- so the
        # mutation keeps the refusal and changes only the class.
        old='            reason_code="BUDGET_EXHAUSTED",\n            error_class=ErrorClass.POLICY_BLOCK,',
        new='            reason_code="BUDGET_EXHAUSTED",\n            error_class=record.error_class,',
        tests=("tests/contract/test_ingestion_surfaces.py",),
    ),
    Mutation(
        name="a_same_work_duplicate_reads_as_discardable",
        guards="UX-001 / §17.22 — same-work duplicates must still attest (EVI-004)",
        path="src/lab_brain/surface/ingestion_item.py",
        old="        return self.same_work_as is not None and self.identical_bytes_of is None",
        new="        return False",
        tests=("tests/contract/test_ingestion_surfaces.py",),
    ),
    Mutation(
        name="a_policy_block_no_longer_outranks_a_failure",
        guards="UX-001 / §17.22 — the state precedence is normative and ordered",
        path="src/lab_brain/surface/ingestion_item.py",
        old='        if classes.get(result.reason_code or "") is ErrorClass.POLICY_BLOCK:',
        new="        if False:",
        tests=("tests/contract/test_ingestion_surfaces.py",),
    ),
    Mutation(
        name="diagnostics_expand_without_the_acl_scope",
        guards="UX-003 / §17.24 — expansion is an authorization decision, checked server-side",
        path="src/lab_brain/surface/disclosure.py",
        old="        if membership is None or VIEW_TECHNICAL_SCOPE not in membership.approval_scopes:",
        new="        if False:",
        tests=("tests/security/test_diagnostics_disclosure.py",),
    ),
    Mutation(
        name="cross_project_error_lookup_confirms_existence",
        guards="UX-003 / §17.24 — another project's error_id returns not-found, never denied",
        path="src/lab_brain/surface/disclosure.py",
        old="        if record is None or record.project_id != project_id:",
        new="        if record is None:",
        tests=("tests/security/test_diagnostics_disclosure.py",),
    ),
    Mutation(
        name="seat_exhaustion_reads_as_unavailable",
        guards="UX-007 / §17.24 — a seat shortage is degraded availability, not an error",
        path="src/lab_brain/surface/health.py",
        old='            status = ComponentStatus.DEGRADED\n            reason = "AWAITING_RESOURCE"',
        new='            status = ComponentStatus.UNAVAILABLE\n            reason = "AWAITING_RESOURCE"',
        tests=("tests/contract/test_ingestion_surfaces.py",),
    ),
    Mutation(
        name="an_llm_call_may_proceed_without_a_bundle",
        guards="LLM-001 / §17.14 — the bundle hash is what distinguishes two runs of one prompt",
        path="src/lab_brain/cognition/llm.py",
        old="        if bundle is None:",
        new="        if False:",
        tests=("tests/contract/test_llm_and_sources.py",),
    ),
    Mutation(
        name="a_legacy_inference_may_be_the_sole_basis",
        guards="LLM-001 / §7.6 — 無 provenance 的舊推論不可作為新 belief transition 的依據",
        path="src/lab_brain/cognition/llm.py",
        old="        if not unprovenanced:",
        new="        if True:",
        tests=("tests/contract/test_llm_and_sources.py",),
    ),
    Mutation(
        name="a_critique_need_not_change_the_route",
        guards="LLM-001 / §7.6 — 不同 provider 不是科學獨立性的充分條件",
        path="src/lab_brain/cognition/llm.py",
        old="        if not output.provenance.route_differs_from(original):",
        new="        if False:",
        tests=("tests/contract/test_llm_and_sources.py",),
    ),
    Mutation(
        name="restricted_nda_may_egress_under_a_policy",
        guards="SEC-001 / §14.1 — RESTRICTED_NDA has no policy exception",
        path="src/lab_brain/security/egress.py",
        old="        if request.sensitivity in NEVER_EGRESS:",
        new="        if False:",
        tests=("tests/security/test_egress_and_licensing.py",),
    ),
    Mutation(
        name="egress_needs_no_actor_clearance",
        guards="SEC-001 / §14.3 — policy AND Actor clearance, not either",
        path="src/lab_brain/security/egress.py",
        old="        if request.sensitivity not in clearance:",
        new="        if False:",
        tests=("tests/security/test_egress_and_licensing.py",),
    ),
    Mutation(
        name="unknown_licence_becomes_permissive",
        guards="SEC-004 / §14.5 — an unidentified licence is not an absent one",
        path="src/lab_brain/security/egress.py",
        old="        if LicenseClass.UNKNOWN not in permitted:",
        new="        if False:",
        tests=("tests/security/test_egress_and_licensing.py",),
    ),
    # ------------------------------------------------------------------
    # M1 final repair. The six audit blockers, each anchored on the guard that closes it.
    # ------------------------------------------------------------------
    Mutation(
        name="evidence_read_skips_the_acl",
        guards="SEC-002 / R-7 -- a project occurrence proves presence, not authorization",
        path="src/lab_brain/core/scientific_read.py",
        old="            if not decision.allowed:\n                continue\n            unit = self._load_unit(descriptor.evidence_unit_id)",
        new="            unit = self._load_unit(descriptor.evidence_unit_id)",
        tests=("tests/security/test_scientific_read_authorization_postgres.py",),
    ),
    Mutation(
        name="candidate_resolution_skips_the_acl",
        guards="SEC-002 / §17.25.1 -- a candidate from another index is dropped before any read",
        path="src/lab_brain/core/scientific_read.py",
        old="            if candidate.project_id != project_id:",
        new="            if False:",
        tests=("tests/security/test_scientific_read_authorization_postgres.py",),
    ),
    Mutation(
        name="an_external_effect_may_run_before_authorization",
        guards="SEC-001 -- the transport is reachable only on ALLOW",
        path="src/lab_brain/security/external.py",
        old="        if not decision.permitted:\n            raise ExternalEffectRefused(decision)\n        return perform()",
        new="        result = perform()\n        if not decision.permitted:\n            raise ExternalEffectRefused(decision)\n        return result",
        tests=("tests/security/test_external_effect_authorization.py",),
    ),
    Mutation(
        name="a_missing_egress_policy_reads_as_local",
        guards="SEC-001 / §14.2 -- locality is declared by the component, never inferred",
        path="src/lab_brain/security/external.py",
        old="        if effect.reach is ExternalReach.LOCAL:",
        new="        if True:",
        tests=("tests/security/test_external_effect_authorization.py",),
    ),
    Mutation(
        name="a_retry_may_run_with_no_budget_gate",
        guards="UX-002 / §17.23 -- auto-retry MUST pass BudgetGate; omitted is not allowed",
        path="src/lab_brain/surface/errors.py",
        old="    if charge_budget is None:",
        new="    if False:",
        tests=("tests/contract/test_budget_and_cli.py",),
    ),
    Mutation(
        name="stored_provenance_need_not_match_what_was_submitted",
        guards="LLM-001 / §7.6 -- a stored inference must be the one that was written",
        path="src/lab_brain/core/repositories/inference.py",
        old="        if stored != p:",
        new="        if False:",
        tests=("tests/integration/test_durable_provenance_and_episodes_postgres.py",),
    ),
    Mutation(
        name="a_suspended_episode_need_not_record_when",
        guards="OPS-001 / §17.3 -- a parked episode records when, or a resumer reads a fiction",
        path="src/lab_brain/core/models/episode.py",
        old="        if (self.state is EpisodeState.SUSPENDED) != (self.suspended_at is not None):",
        new="        if False:",
        tests=("tests/integration/test_durable_provenance_and_episodes_postgres.py",),
    ),
    Mutation(
        name="the_inbox_reads_state_instead_of_deriving_it",
        guards="UX-001 / §17.22 -- the CLI renders the derivation, it does not have its own",
        path="src/lab_brain/interfaces/cli.py",
        old="            state=derive_state(",
        new="            state=ItemState.READY if True else derive_state(",
        tests=("tests/contract/test_budget_and_cli.py",),
    ),
    # ------------------------------------------------------------------
    # M1 second audit. Four production-path blockers, each anchored on the guard that closes it.
    # ------------------------------------------------------------------
    Mutation(
        name="the_authorized_path_loads_a_body_before_deciding",
        guards="SEC-002 / R-7 -- authorize from the descriptor; the body is loaded only on ALLOW",
        path="src/lab_brain/core/scientific_read.py",
        old="            if not decision.allowed:\n                continue\n            unit = self._load_unit(descriptor.evidence_unit_id)",
        new="            unit = self._load_unit(descriptor.evidence_unit_id)\n            if not decision.allowed:\n                continue",
        tests=("tests/security/test_scientific_read_authorization_postgres.py",),
    ),
    Mutation(
        name="a_caller_may_downgrade_the_derived_classification",
        guards="SEC-001 / §14.1 -- escalation is a union; there is no subtraction",
        path="src/lab_brain/security/classification.py",
        old="            labels=frozenset(derived) | declared,",
        new="            labels=declared if declared else frozenset(derived),",
        tests=(
            "tests/security/test_external_effect_authorization.py",
            "tests/e2e/test_m1_vertical_postgres.py",
        ),
    ),
    Mutation(
        name="an_unclassifiable_context_reads_as_unrestricted",
        guards="SEC-001 / §14.3 -- absence of a classification is not permission",
        path="src/lab_brain/security/classification.py",
        old="    if not classification.usable:",
        new="    if False:",
        tests=("tests/security/test_external_effect_authorization.py",),
    ),
    Mutation(
        name="only_one_label_of_a_mixed_context_is_authorized",
        guards="SEC-001 / §14.1 -- labels are categories, so every one must be permitted",
        path="src/lab_brain/security/external.py",
        old="        for label in effect.labels:",
        new="        for label in effect.labels[:1]:",
        tests=("tests/security/test_external_effect_authorization.py",),
    ),
    Mutation(
        name="an_inference_is_returned_before_it_is_durable",
        guards="LLM-001 -- no usable output escapes without durable provenance",
        path="src/lab_brain/cognition/inference.py",
        old="        stored = self._store.get(identifier)\n        if stored is None:",
        new="        stored = self._store.get(identifier) or output.provenance\n        if False:",
        tests=("tests/integration/test_durable_provenance_and_episodes_postgres.py",),
    ),
    Mutation(
        name="a_failed_write_still_returns_the_model_text",
        guards="LLM-001 -- a crash between the call and the write yields nothing usable",
        path="src/lab_brain/cognition/inference.py",
        old='            raise InferenceNotDurable(identifier, trace_id, f"the write failed ({exc})") from exc',
        new="            pass",
        tests=("tests/integration/test_durable_provenance_and_episodes_postgres.py",),
    ),
    Mutation(
        name="the_inbox_reads_a_stored_state",
        guards="UX-001 / §17.22 -- the durable reader returns rows, never a state",
        path="src/lab_brain/storage/postgres/surface_store.py",
        old="            stage_results=self._stage_results(item_id),",
        new="            stage_results=(),",
        tests=("tests/integration/test_cli_surface_postgres.py",),
    ),
    Mutation(
        name="the_cli_resolves_an_error_without_the_project",
        guards="UX-003 / §17.24 -- a foreign error id is indistinguishable from a missing one",
        path="src/lab_brain/surface/disclosure.py",
        old="        if record is None or record.project_id != project_id:",
        new="        if record is None:",
        tests=("tests/integration/test_cli_surface_postgres.py",),
    ),
    # ------------------------------------------------------------------
    # M1 third audit. The production-integration blockers, anchored on the guards that close them.
    # ------------------------------------------------------------------
    Mutation(
        name="the_inbox_does_not_authorize_its_actor",
        guards="SEC-002 / §14.4 -- `--actor` must be consulted, not merely demanded",
        path="src/lab_brain/composition.py",
        old="        self.read_gate().require_project(actor_id=actor_id, project_id=project_id)",
        new="        pass",
        tests=("tests/integration/test_inbox_authorization_postgres.py",),
    ),
    Mutation(
        name="an_inactive_membership_still_admits",
        guards="SEC-002 -- revocation is a denial, not a retained grant",
        path="src/lab_brain/core/access.py",
        old="    if not membership.active:",
        new="    if False:",
        tests=(
            "tests/integration/test_inbox_authorization_postgres.py",
            "tests/security/test_project_scoped_access.py",
        ),
    ),
    Mutation(
        name="error_disclosure_skips_the_actor_check",
        guards="UX-003 / §17.24 -- a disabled account may not resolve an error reference",
        path="src/lab_brain/surface/disclosure.py",
        old="        return can_access_project(self._actor_of(actor_id), project_id, membership).allowed",
        new="        return membership is not None",
        tests=(
            # Backend-free first, and that is the point of adding it. Until the constructor
            # required `actor_of`, the membership-only branch was the one every in-memory fixture
            # ran, so no backend-free test could see this substitution at all: the mutation was
            # only killable where a real Actor store existed. It is now killed without Postgres.
            "tests/security/test_diagnostics_disclosure.py",
            "tests/integration/test_inbox_authorization_postgres.py",
            "tests/integration/test_cli_surface_postgres.py",
        ),
    ),
    Mutation(
        name="diagnostics_actor_resolution_is_optional_again",
        guards="SEC-002 -- there must be no supported membership-only construction",
        path="src/lab_brain/surface/disclosure.py",
        old="        actor_of: Callable[[str], Actor | None],",
        new="        actor_of: Callable[[str], Actor | None] | None = None,",
        tests=("tests/security/test_diagnostics_disclosure.py",),
    ),
    Mutation(
        name="the_inbox_ignores_open_reviews",
        guards="UX-005 / §17.22 -- NEEDS_REVIEW comes from the one ReviewQueue",
        path="src/lab_brain/storage/postgres/surface_store.py",
        old='            review_ids=self._review_ids(item_id, str(values["project_id"])),',
        new="            review_ids=(),",
        tests=("tests/integration/test_inbox_authorization_postgres.py",),
    ),
    Mutation(
        name="a_resolved_review_still_blocks_the_item",
        guards="UX-005 -- the state follows the queue, so an answered review releases the item",
        path="src/lab_brain/storage/postgres/surface_store.py",
        old='            "SELECT review_id FROM review_items WHERE project_id = %s AND status = ANY (%s)",',
        new='            "SELECT review_id FROM review_items WHERE project_id = %s AND %s IS NOT NULL",',
        tests=("tests/integration/test_inbox_authorization_postgres.py",),
    ),
    Mutation(
        name="a_non_blocking_conflict_is_treated_as_blocking",
        guards="§17.19.3 -- BLOCKING and unresolved, both",
        path="src/lab_brain/storage/postgres/surface_store.py",
        old='            "SELECT conflict_id FROM conflicts WHERE project_id = %s AND blocking "',
        new='            "SELECT conflict_id FROM conflicts WHERE project_id = %s AND TRUE "',
        tests=("tests/integration/test_inbox_authorization_postgres.py",),
    ),
    Mutation(
        name="the_cli_ignores_live_job_state",
        guards="UX-001 / §17.22 -- PROCESSING while a Job is still active",
        path="src/lab_brain/interfaces/cli.py",
        old="                jobs=() if jobs_for is None else jobs_for(item.item_id),",
        new="                jobs=(),",
        tests=("tests/integration/test_inbox_authorization_postgres.py",),
    ),
    Mutation(
        name="technical_detail_is_returned_without_redaction",
        guards="UX-003 / §17.24 -- detail is redacted against the actor's clearance",
        path="src/lab_brain/surface/disclosure.py",
        old="    if _permits(clearance, detail.sensitivity):",
        new="    if True:",
        tests=("tests/integration/test_cli_surface_postgres.py",),
    ),
    # ------------------------------------------------------------------
    # M2. The Silicon Photonics tool layer, anchored on the guards each requirement turns on.
    # ------------------------------------------------------------------
    Mutation(
        name="a_run_may_be_minted_before_its_validity_is_checked",
        guards="SIM-001 -- an incomplete validity record must never become a manifest",
        path="src/lab_brain/tools/execution.py",
        old="        validate_backend_validity(execution, validity)",
        new="        pass",
        tests=("tests/contract/test_simulation_contract.py",),
    ),
    Mutation(
        name="a_validity_schema_accepts_an_empty_required_field",
        guards="SIM-001 -- absent AND empty both count as missing",
        path="src/lab_brain/tools/simulation.py",
        old='            if payload.get(name) in (None, "", (), [], {})',
        new="            if payload.get(name) is None",
        tests=("tests/contract/test_simulation_contract.py",),
    ),
    Mutation(
        name="a_non_converged_run_keeps_the_fidelity_it_declared",
        guards="SIM-002 -- the declared authority class is a ceiling, not a claim",
        path="src/lab_brain/domains/silicon_photonics/backend_validity.py",
        old="    if not isinstance(status, str) or status not in CONVERGED_STATES:",
        new="    if False:",
        tests=(
            "tests/contract/test_simulation_contract.py",
            "tests/e2e/test_sim_fidelity_gate_postgres.py",
        ),
    ),
    Mutation(
        name="simulated_and_measured_authority_are_ranked",
        guards="SIM-002 / §10.6 -- a measurement does not automatically outrank a simulation",
        path="src/lab_brain/domains/silicon_photonics/authority_policy.py",
        old="        if _FAMILIES[a] != _FAMILIES[b]:",
        new="        if False:",
        tests=("tests/e2e/test_sim_fidelity_gate_postgres.py",),
    ),
    Mutation(
        name="the_tool_registry_accepts_a_foreign_request_type",
        guards="SIM-003 -- the payload type is checked before the implementation is reached",
        path="src/lab_brain/tools/registry.py",
        old="        if not isinstance(request, expected):",
        new="        if False:",
        tests=("tests/unit/test_typed_tool_registry.py",),
    ),
    Mutation(
        name="an_extract_tool_may_name_a_backend",
        guards="§10.2.1 / DOM-SP-002 -- `backend-agnostic` is a descriptor that CANNOT name one",
        path="src/lab_brain/tools/contracts.py",
        old="            if self.capability_id is not None:",
        new="            if False:",
        tests=("tests/unit/test_typed_tool_registry.py",),
    ),
    Mutation(
        name="a_quantity_may_carry_a_value_with_no_normalization_basis",
        guards="EVI-001 -- unit, basis and method travel with the number or it is not comparable",
        path="src/lab_brain/tools/extraction.py",
        old="            if missing:",
        new="            if False:",
        tests=("tests/domains/test_cj_rs_evidence_contract.py",),
    ),
    Mutation(
        name="a_simulated_source_need_not_name_its_run",
        guards="EVI-009 at the extraction boundary -- a solver result must trace to its Run",
        path="src/lab_brain/tools/extraction.py",
        old="            if self.run_id is None:",
        new="            if False:",
        tests=(
            "tests/domains/test_shared_extractor_contract.py",
            "tests/e2e/test_m2_vertical_postgres.py",
        ),
    ),
    Mutation(
        name="an_undescribed_backend_may_be_planned",
        guards="VER-002 / §9.5 -- a backend with no Capability descriptor MUST NOT be planned",
        path="src/lab_brain/verification/planner.py",
        old="        if not self._registry.for_backend(backend_id):",
        new="        if False:",
        tests=("tests/unit/test_capability_planning.py",),
    ),
    Mutation(
        name="the_planner_ignores_what_an_action_requires",
        guards="VER-002 -- produces AND requires, and the second half is the one easy to drop",
        path="src/lab_brain/verification/planner.py",
        old="            if not capability.satisfied_by(available):\n                continue",
        new="            if False:\n                continue",
        tests=("tests/unit/test_capability_planning.py",),
    ),
    Mutation(
        name="no_seat_becomes_a_failure_instead_of_a_wait",
        guards="§10.7 -- WAITING_RESOURCE, not FAILED; contention is not a simulation failure",
        path="src/lab_brain/tools/execution.py",
        old="                JobState.WAITING_RESOURCE,",
        new="                JobState.FAILED,",
        tests=(
            "tests/contract/test_simulation_contract.py",
            "tests/e2e/test_m2_vertical_postgres.py",
        ),
    ),
    Mutation(
        name="the_seat_is_not_released_when_the_backend_raises",
        guards="§10.7 -- the pool drains one lease per crash, and the symptom looks like a queue",
        path="src/lab_brain/tools/execution.py",
        old="        if lease is not None and broker is not None:\n            broker.release(lease.lease_id, now=now())",
        new="        pass",
        tests=("tests/contract/test_simulation_contract.py",),
    ),
    Mutation(
        name="a_domain_pack_may_be_installed_through_any_shape",
        guards="EXT-001 / §24.3 -- a pack core knows about specially is the boundary failing",
        path="src/lab_brain/domains/registry.py",
        old="        if not isinstance(pack, DomainPack):",
        new="        if False:",
        tests=("tests/unit/test_extension_boundary.py",),
    ),
    Mutation(
        name="a_validator_need_not_return_a_validation_report",
        guards="§17.19.2 / DOM-SP-001 -- never an unstructured boolean/string",
        path="src/lab_brain/tools/registry.py",
        old="            if not carries_report:",
        new="            if False:",
        tests=("tests/unit/test_typed_tool_registry.py",),
    ),
    Mutation(
        name="a_report_summary_may_contradict_its_findings",
        guards="§17.19.2 -- a gate and a human must not read one report two ways",
        path="src/lab_brain/core/models/validation.py",
        old="        if self.status is not expected:",
        new="        if False:",
        tests=("tests/domains/test_domain_pack_boundary.py",),
    ),
    # ------------------------------------------------------------------
    # M2 review repairs A-D. Each anchor sits on the guard the review found missing.
    # ------------------------------------------------------------------
    Mutation(
        name="a_tool_may_run_before_the_budget_gate",
        guards="COST-001 -- the call lives inside `perform`, which only ALLOW reaches",
        path="src/lab_brain/tools/dispatch.py",
        # Hoists the invocation out of the closure, which is the ONE edit that turns this module
        # back into the defect it closes: the tool runs, then the gate is asked.
        old="        captured: dict[str, ToolResult] = {}",
        new='        captured: dict[str, ToolResult] = {\n            "result": self._tools.invoke(action.tool_id, action.request)\n        }',
        tests=("tests/unit/test_budgeted_tool_dispatch.py",),
    ),
    Mutation(
        name="an_unpriceable_tool_is_dispatched_anyway",
        guards="COST-001 -- 'cheap' is not 'ungoverned', and no estimate is not a zero estimate",
        path="src/lab_brain/tools/dispatch.py",
        old="        if estimator is None:",
        new="        if False:",
        tests=("tests/unit/test_budgeted_tool_dispatch.py",),
    ),
    Mutation(
        name="the_actual_cost_is_the_estimate",
        guards="§17.17 -- two rows, so systematic under-estimation stays visible",
        path="src/lab_brain/tools/dispatch.py",
        old="                actual_cost=self._actual_cost(result, started),",
        new="                actual_cost=estimate,",
        tests=("tests/unit/test_budgeted_tool_dispatch.py",),
    ),
    Mutation(
        name="a_local_tool_need_not_declare_a_cost_contract",
        guards="COST-001 -- every tool call is gated, so every tool has a price",
        path="src/lab_brain/tools/contracts.py",
        old="            if self.cost_contract is None:",
        new="            if False:",
        tests=("tests/unit/test_typed_tool_registry.py",),
    ),
    Mutation(
        name="cj_rs_is_derived_without_its_declared_conditions",
        guards="EVI-001 -- bias/frequency provenance is required, not merely well-formed syntax",
        path="src/lab_brain/domains/silicon_photonics/extractors.py",
        old="        self._require_conditions(payload)",
        new="        pass",
        tests=("tests/domains/test_cj_rs_evidence_contract.py",),
    ),
    Mutation(
        name="a_missing_frequency_condition_is_recovered_from_the_series",
        guards="EVI-001 -- the arrays are not the record's claim about the arrays",
        path="src/lab_brain/domains/silicon_photonics/extractors.py",
        old='        frequency = _decimal(conditions.get("frequency_hz"))',
        new='        frequency = _decimal(conditions.get("frequency_hz")) or (\n            payload.series_named(SERIES_FREQUENCY).values[0]\n            if payload.series_named(SERIES_FREQUENCY)\n            else None\n        )',
        tests=("tests/domains/test_cj_rs_evidence_contract.py",),
    ),
    Mutation(
        name="the_request_may_replace_the_jobs_bound_demand",
        guards="§10.7 / §17.16 -- the durable Job is the requirement, the request is checked",
        path="src/lab_brain/tools/execution.py",
        old="    demand = _require_bound_demand(current, request)",
        new="    demand = request.resource_demand",
        tests=(
            "tests/contract/test_resource_demand_binding.py",
            "tests/e2e/test_m2_vertical_postgres.py",
        ),
    ),
    Mutation(
        name="the_submitted_job_carries_no_resource_requirement",
        guards="§17.16 -- a reloaded WAITING_RESOURCE job must name what it waits for",
        path="src/lab_brain/tools/execution.py",
        old='    return jobs.submit(job.model_copy(update={"resource_requirements": demand.as_requirements()}))',
        new="    return jobs.submit(job)",
        tests=(
            "tests/contract/test_resource_demand_binding.py",
            "tests/e2e/test_m2_vertical_postgres.py",
        ),
    ),
    Mutation(
        name="a_demand_need_not_match_the_capabilitys_license_constraint",
        guards="§17.18 -- a demand for a resource the action does not contend for",
        path="src/lab_brain/tools/execution.py",
        old="    if demand.resource_id not in declared:",
        new="    if False:",
        tests=("tests/unit/test_capability_planning.py",),
    ),
    # ------------------------------------------------------------------
    # M2 review repair E — the execution-scope binding. Eight guards, eight entries.
    #
    # EACH MUTATION MAKES ONE DIMENSION COMPARE AGAINST ITSELF rather than deleting the call.
    # Deleting a `require_same_scope(...)` would disable three dimensions at one of three
    # boundaries and prove only that *something* at that boundary is tested; reading the same
    # value into both `ExecutionScope`s leaves the other two dimensions live, so what survives or
    # dies is exactly one equality. That is the granularity the guards were written at, so it is
    # the granularity the battery has to attack them at.
    #
    # The review counted seven. There are eight: the capability chain
    # `ToolDescriptor -> SimulationRequest -> Job` has two links, not one, and the second is what
    # stops a Job accepting an execution its own Capability never planned.
    # ------------------------------------------------------------------
    Mutation(
        name="the_gated_project_need_not_be_the_executed_project",
        guards="§17.16 -- ToolAction.project_id == ToolRequest.project_id, before the gate",
        path="src/lab_brain/tools/dispatch.py",
        old="                project_id=action.request.project_id,",
        new="                project_id=action.project_id,",
        tests=("tests/unit/test_budgeted_tool_dispatch.py",),
    ),
    Mutation(
        name="the_gated_trace_need_not_be_the_executed_trace",
        guards="OPS-003 -- ToolAction.trace_id == ToolRequest.trace_id, before the gate",
        path="src/lab_brain/tools/dispatch.py",
        old="                trace_id=action.request.trace_id,",
        new="                trace_id=action.trace_id,",
        tests=("tests/unit/test_budgeted_tool_dispatch.py",),
    ),
    Mutation(
        name="a_sweep_envelope_may_wrap_another_projects_simulation",
        guards="§17.16 -- ChargeAcSweepRequest.project_id == simulation.project_id",
        path="src/lab_brain/domains/silicon_photonics/tools.py",
        old="                project_id=self.simulation.project_id,",
        new="                project_id=self.project_id,",
        tests=("tests/unit/test_typed_tool_registry.py",),
    ),
    Mutation(
        name="a_sweep_envelope_may_wrap_another_traces_simulation",
        guards="OPS-003 -- ChargeAcSweepRequest.trace_id == simulation.trace_id",
        path="src/lab_brain/domains/silicon_photonics/tools.py",
        old="                trace_id=self.simulation.trace_id,",
        new="                trace_id=self.trace_id,",
        tests=("tests/unit/test_typed_tool_registry.py",),
    ),
    Mutation(
        name="a_sweep_envelope_may_wrap_another_capabilitys_simulation",
        guards="§9.5 -- ToolDescriptor.capability_id == SimulationRequest.capability_id",
        path="src/lab_brain/domains/silicon_photonics/tools.py",
        old="                capability_id=self.simulation.capability_id,",
        new="                capability_id=CHARGE_AC_CAPABILITY,",
        tests=("tests/unit/test_typed_tool_registry.py",),
    ),
    Mutation(
        name="a_simulation_may_execute_against_another_projects_job",
        guards="SEC-002 -- SimulationRequest.project_id == Job.project_id, before any side effect",
        path="src/lab_brain/tools/execution.py",
        old="            project_id=current.project_id,",
        new="            project_id=request.project_id,",
        tests=("tests/contract/test_resource_demand_binding.py",),
    ),
    Mutation(
        name="a_simulation_may_execute_against_another_traces_job",
        guards="OPS-003 -- SimulationRequest.trace_id == Job.trace_id, before any side effect",
        path="src/lab_brain/tools/execution.py",
        old="            trace_id=current.trace_id,",
        new="            trace_id=request.trace_id,",
        tests=("tests/contract/test_resource_demand_binding.py",),
    ),
    Mutation(
        name="a_simulation_may_execute_against_another_capabilitys_job",
        guards="§17.18 -- SimulationRequest.capability_id == Job.capability_id",
        path="src/lab_brain/tools/execution.py",
        old="            capability_id=current.capability_id,",
        new="            capability_id=request.capability_id,",
        tests=("tests/contract/test_resource_demand_binding.py",),
    ),
    # ------------------------------------------------------------------
    # M2 final blocker — the Episode that pays is the Episode whose Job executes.
    #
    # Same discipline as repair E: one equality per entry, made to compare a value against
    # itself, so the other dimensions of the same comparison stay live. The episode is added at
    # the three existing boundaries (three entries) and at the new pre-gate Job binding, where all
    # four dimensions are compared and each gets its own entry -- the pre-gate check is what keeps
    # an approval unspent, and a guard that held the Episode but not, say, the project would still
    # spend one on a cross-project Job.
    #
    # The binding's own scope reading `self.episode_id` instead of `self.simulation.episode_id` is
    # NOT here: the model validator makes those equal, so that mutant is equivalent and would
    # survive for the right reason. What the binding must get right is WHICH JOB, and that is here.
    # ------------------------------------------------------------------
    Mutation(
        name="the_gated_episode_need_not_be_the_requested_episode",
        guards="COST-001 -- ToolAction.episode_id == ToolRequest.episode_id, before the gate",
        path="src/lab_brain/tools/dispatch.py",
        old="                episode_id=action.request.episode_id,",
        new="                episode_id=action.episode_id,",
        tests=("tests/unit/test_budgeted_tool_dispatch.py",),
    ),
    Mutation(
        name="a_sweep_envelope_may_wrap_another_episodes_simulation",
        guards="COST-001 -- ChargeAcSweepRequest.episode_id == simulation.episode_id",
        path="src/lab_brain/domains/silicon_photonics/tools.py",
        old=(
            '                layer="ChargeAcSweepRequest.simulation",\n'
            "                project_id=self.simulation.project_id,\n"
            "                trace_id=self.simulation.trace_id,\n"
            "                episode_id=self.simulation.episode_id,"
        ),
        new=(
            '                layer="ChargeAcSweepRequest.simulation",\n'
            "                project_id=self.simulation.project_id,\n"
            "                trace_id=self.simulation.trace_id,\n"
            "                episode_id=self.episode_id,"
        ),
        tests=("tests/unit/test_typed_tool_registry.py",),
    ),
    Mutation(
        name="a_simulation_may_execute_another_episodes_job",
        guards="§17.16 -- SimulationRequest.episode_id == Job.episode_id, at execution time",
        path="src/lab_brain/tools/execution.py",
        old="            episode_id=current.episode_id,",
        new="            episode_id=request.episode_id,",
        tests=("tests/contract/test_resource_demand_binding.py",),
    ),
    Mutation(
        name="the_budgeted_episode_need_not_be_the_jobs_episode",
        guards="COST-001 -- the executed Job's episode_id, compared BEFORE the approval is spent",
        path="src/lab_brain/tools/dispatch.py",
        old="                episode_id=job.episode_id,",
        new="                episode_id=binding.scope.episode_id,",
        tests=("tests/unit/test_budgeted_tool_dispatch.py",),
    ),
    Mutation(
        name="the_pre_gate_binding_ignores_the_jobs_project",
        guards="SEC-002 -- the executed Job's project_id, compared before the gate",
        path="src/lab_brain/tools/dispatch.py",
        old="                project_id=job.project_id,",
        new="                project_id=binding.scope.project_id,",
        tests=("tests/unit/test_budgeted_tool_dispatch.py",),
    ),
    Mutation(
        name="the_pre_gate_binding_ignores_the_jobs_trace",
        guards="OPS-003 -- the executed Job's trace_id, compared before the gate",
        path="src/lab_brain/tools/dispatch.py",
        old="                trace_id=job.trace_id,",
        new="                trace_id=binding.scope.trace_id,",
        tests=("tests/unit/test_budgeted_tool_dispatch.py",),
    ),
    Mutation(
        name="the_pre_gate_binding_ignores_the_jobs_capability",
        guards="§17.18 -- the executed Job's capability_id, compared before the gate",
        path="src/lab_brain/tools/dispatch.py",
        old="                capability_id=job.capability_id,",
        new="                capability_id=binding.scope.capability_id,",
        tests=("tests/unit/test_budgeted_tool_dispatch.py",),
    ),
    Mutation(
        name="a_run_request_may_bind_no_job",
        guards="fail closed -- a run_* request that names no durable Job is refused, not passed",
        path="src/lab_brain/tools/dispatch.py",
        old=(
            "            if descriptor.tool_class is ToolClass.RUN:\n"
            "                raise ToolDispatchRefused("
        ),
        new="            if False:\n                raise ToolDispatchRefused(",
        tests=("tests/unit/test_budgeted_tool_dispatch.py",),
    ),
    Mutation(
        name="an_unresolvable_bound_job_is_not_refused_as_wiring",
        guards="§17.16 -- a request naming a Job that does not exist is refused before the gate",
        path="src/lab_brain/tools/dispatch.py",
        old="        if job is None:\n            raise ToolDispatchRefused(",
        new="        if False:\n            raise ToolDispatchRefused(",
        tests=("tests/unit/test_budgeted_tool_dispatch.py",),
    ),
    Mutation(
        name="a_sweep_binds_a_job_other_than_the_one_it_executes",
        guards="the JobBinding names the nested request's job_id -- the Job the runner executes",
        path="src/lab_brain/domains/silicon_photonics/tools.py",
        old="            job_id=self.simulation.job_id,",
        new="            job_id=self.simulation.request_id,",
        tests=("tests/unit/test_typed_tool_registry.py",),
    ),
    Mutation(
        name="a_simulation_job_may_be_submitted_with_no_episode",
        guards="§17.16 -- an Episode-less simulation Job is refused before it is durable",
        path="src/lab_brain/tools/execution.py",
        old="    if job.episode_id is None:\n        raise ResourceBindingError(",
        new="    if False:\n        raise ResourceBindingError(",
        tests=("tests/contract/test_resource_demand_binding.py",),
    ),
    Mutation(
        name="a_tool_request_may_leave_its_episode_unstated",
        guards="never inferred -- ToolRequest.episode_id is required",
        path="src/lab_brain/tools/contracts.py",
        old="    trace_id: str\n    episode_id: str\n",
        new='    trace_id: str\n    episode_id: str = "epi:unstated"\n',
        tests=("tests/unit/test_typed_tool_registry.py",),
    ),
    Mutation(
        name="a_simulation_request_may_leave_its_episode_unstated",
        guards="never inferred -- SimulationRequest.episode_id is required",
        path="src/lab_brain/tools/simulation.py",
        old="    trace_id: str\n    episode_id: str\n    job_id: str\n",
        new='    trace_id: str\n    episode_id: str = "epi:unstated"\n    job_id: str\n',
        tests=("tests/unit/test_typed_tool_registry.py",),
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
