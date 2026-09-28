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
    # M3 — Hypothesis Brain (EPI-001, SRC-002, LLM-002, SRC-003). Python guards only: the `005e` /
    # `011i` / `002b` triggers are exercised directly by the PostgreSQL tests, and a textual
    # mutation of an already-applied migration would change nothing in the database under test.
    Mutation(
        name="a_set_of_one_is_competing",
        guards="EPI-001 — a competing set holds >= 2 certificates",
        path="src/lab_brain/core/hypothesis_admission.py",
        old="    if len(certificates) < 2:",
        new="    if False:",
        tests=("tests/unit/test_hypothesis_admission.py",),
    ),
    Mutation(
        name="two_phrasings_are_two_rivals",
        guards="P6 — distinct mechanisms, not repetitions",
        path="src/lab_brain/core/hypothesis_admission.py",
        old="        if key in seen:",
        new="        if False:",
        tests=("tests/unit/test_hypothesis_admission.py",),
    ),
    Mutation(
        name="a_hypothesis_may_rest_on_no_evidence",
        guards="§6.18 — a genesis event cites the evidence it was reasoned from",
        path="src/lab_brain/core/hypothesis_admission.py",
        old="    if not basis:",
        new="    if False:",
        tests=("tests/unit/test_hypothesis_admission.py",),
    ),
    Mutation(
        name="a_basis_may_come_from_another_project",
        guards="SEC-002 — the basis resolves in the set's project",
        path="src/lab_brain/core/hypothesis_admission.py",
        old="        if found is None or found.project_id != hypothesis_set.project_id:",
        new="        if found is None:",
        tests=("tests/unit/test_hypothesis_admission.py",),
    ),
    Mutation(
        name="a_certificate_needs_no_prediction",
        guards="§8 — a certificate carries a typed Prediction",
        path="src/lab_brain/core/repositories/hypotheses.py",
        old="    if not certificate.predictions:",
        new="    if False:",
        tests=("tests/unit/test_hypothesis_admission.py",),
    ),
    Mutation(
        name="a_single_cause_may_be_promoted",
        guards="EPI-001 — no single plausible cause promoted to root cause",
        path="src/lab_brain/core/revision_gate.py",
        old="            if len(admitted) < 2:",
        new="            if False:",
        tests=("tests/unit/test_revision_gate.py",),
    ),
    Mutation(
        name="a_reject_needs_no_critique",
        guards="§7.6 — a REJECT needs an independent critique path",
        path="src/lab_brain/core/revision_gate.py",
        old="        if is_reject and not independent:",
        new="        if False:",
        tests=("tests/unit/test_revision_gate.py",),
    ),
    Mutation(
        name="high_stakes_needs_no_inversion",
        guards="SRC-002 — above the threshold, no inverted retrieval, no revision",
        path="src/lab_brain/core/revision_gate.py",
        old="        if hypothesis_set.inverted_retrieval_required and not inverted:",
        new="        if False:",
        tests=("tests/unit/test_revision_gate.py",),
    ),
    Mutation(
        name="model_opinion_may_adjudicate",
        guards="§7.6 — adjudication cites external evidence",
        path="src/lab_brain/core/revision_gate.py",
        old="and not admissible(\n            triggering_attestations\n        ):",
        new="and not triggering_attestations:",
        tests=("tests/unit/test_revision_gate.py",),
    ),
    Mutation(
        name="a_later_critique_counts",
        guards="a critique must precede the decision it licenses",
        path="src/lab_brain/core/revision_gate.py",
        old="            if c.differs_in and c.created_at <= at",
        new="            if c.differs_in",
        tests=("tests/unit/test_revision_gate.py",),
    ),
    Mutation(
        name="the_brain_skips_its_preconditions",
        guards="HypothesisBrain runs the M3 preconditions before M1's path",
        path="src/lab_brain/cognition/brain.py",
        old="        self._gate.require(\n",
        new="        self._gate.evaluate(\n",
        tests=("tests/e2e/test_hypothesis_brain_postgres.py",),
    ),
    Mutation(
        name="stakes_never_require_inversion",
        guards="§7.2 — stakes >= threshold requires the Critic's inversion",
        path="src/lab_brain/evidence/source_policy.py",
        old="        return self.rank(stakes) >= self.rank(self.inverted_retrieval_threshold)",
        new="        return False",
        tests=("tests/unit/test_debate_protocol.py", "tests/unit/test_revision_gate.py"),
    ),
    Mutation(
        name="the_critic_inverts_nothing",
        guards="§7.2 — the inverted retrieval reads the policy's inverted classes",
        path="src/lab_brain/cognition/evidence.py",
        old="        classes = policy.inverted_source_classes if inverted else policy.source_classes",
        new="        classes = policy.source_classes",
        tests=("tests/unit/test_debate_protocol.py",),
    ),
    Mutation(
        name="the_inversion_may_repeat_the_primary",
        guards="§7.2 — the Critic's retrieval excludes what the positions saw",
        path="src/lab_brain/cognition/debate.py",
        old="            exclude=primary.ordered_attestation_ids,",
        new="            exclude=(),",
        tests=("tests/unit/test_debate_protocol.py",),
    ),
    Mutation(
        name="a_critic_may_cite_what_it_was_not_shown",
        guards="§7.1 — no role supplies evidence from its own text",
        path="src/lab_brain/cognition/roles.py",
        old="        if invented:",
        new="        if False:",
        tests=("tests/unit/test_debate_protocol.py",),
    ),
    Mutation(
        name="an_irreversible_action_needs_no_critique",
        guards="SRC-002 — irreversible dispatch waits for critique",
        path="src/lab_brain/tools/dispatch.py",
        old="        if not irreversible:",
        new="        if True:",
        tests=("tests/unit/test_irreversible_dispatch.py",),
    ),
    Mutation(
        name="citing_anything_is_external_evidence",
        guards="§7.6 — the adjudicator is proven from the record, not from the act of citing",
        path="src/lab_brain/tools/dispatch.py",
        old="                adjudicated_by=basis.adjudicator,",
        new="                adjudicated_by=type(basis.adjudicator).EXTERNAL_EVIDENCE,",
        tests=("tests/unit/test_irreversible_dispatch.py",),
    ),
    Mutation(
        name="the_router_may_lack_the_minimum",
        guards="§26.1 — PRIMARY/FAST/EMBEDDING minimum routing",
        path="src/lab_brain/cognition/routing.py",
        old="        if missing:",
        new="        if False:",
        tests=("tests/unit/test_debate_protocol.py",),
    ),
    Mutation(
        name="rounds_run_to_the_maximum",
        guards="§7.2 — a round is earned by a trigger",
        path="src/lab_brain/cognition/debate.py",
        old="            if not triggers:",
        new="            if False:",
        tests=("tests/unit/test_debate_protocol.py", "tests/contract/test_debate_benchmark.py"),
    ),
    Mutation(
        name="always_max_is_acceptable",
        guards="v3.3-a6 — an always-maximum implementation fails the benchmark",
        path="src/lab_brain/cognition/debate_benchmark.py",
        old="    if all(r.rounds >= r.max_rounds for r in results):",
        new="    if False:",
        tests=("tests/contract/test_debate_benchmark.py",),
    ),
    Mutation(
        name="the_benchmark_cannot_say_no",
        guards="§15.4 / v3.3-a3 — the groupthink claim is refutable",
        path="src/lab_brain/cognition/debate_benchmark.py",
        old="        verdict=Verdict.REFUTED if reasons else Verdict.SUPPORTED,",
        new="        verdict=Verdict.SUPPORTED,",
        tests=("tests/contract/test_debate_benchmark.py",),
    ),
    Mutation(
        name="the_threshold_is_not_read_off_the_run",
        guards="LLM-002 — the calibrated threshold is the run's",
        path="src/lab_brain/cognition/debate_benchmark.py",
        old="        threshold=min(samples),",
        new="        threshold=max(samples),",
        tests=("tests/contract/test_debate_benchmark.py",),
    ),
    Mutation(
        name="an_armed_gate_passes_below_its_threshold",
        guards="LLM-002 — AT_LEAST means at least",
        path="src/lab_brain/core/models/benchmark.py",
        old="            return value >= self.threshold",
        new="            return True",
        tests=("tests/unit/test_benchmark_gate.py", "tests/unit/test_revision_gate.py"),
    ),
    Mutation(
        name="a_divergence_below_calibration_is_ignored",
        guards="LLM-002 — an armed gate blocks the revision",
        path="src/lab_brain/core/revision_gate.py",
        old="            if verdict.blocks:",
        new="            if False:",
        tests=("tests/unit/test_revision_gate.py",),
    ),
    Mutation(
        name="internal_novelty_may_be_global",
        guards="SRC-003 — internal novelty is not presented as global",
        path="src/lab_brain/core/models/prior_art.py",
        old="        if record.internal_only:",
        new="        if False:",
        tests=("tests/unit/test_novelty_audit.py",),
    ),
    # M3 review repairs: §7.6 adjudication from the record, and R-12.
    Mutation(
        name="inferred_evidence_adjudicates",
        guards="EVI-003 / §7.6 — an INFERRED record is model opinion",
        path="src/lab_brain/core/adjudication.py",
        old="    if attestation.epistemic_type not in FACTUAL_EPISTEMIC_TYPES:",
        new="    if False:",
        tests=("tests/unit/test_adjudication.py", "tests/unit/test_irreversible_dispatch.py"),
    ),
    Mutation(
        name="disputed_evidence_adjudicates",
        guards="§7.6 — contested evidence cannot settle a contest",
        path="src/lab_brain/core/adjudication.py",
        old="    if attestation.verification_status == VerificationStatus.DISPUTED:",
        new="    if False:",
        tests=("tests/unit/test_adjudication.py", "tests/unit/test_irreversible_dispatch.py"),
    ),
    Mutation(
        name="a_ghost_citation_is_skipped",
        guards="fail closed — a citation to nothing refuses the basis",
        path="src/lab_brain/core/adjudication.py",
        old="        if found is None or found.project_id != project_id:\n            raise AdjudicationBasisRefused(",
        new="        if found is None:\n            continue\n        if found.project_id != project_id:\n            raise AdjudicationBasisRefused(",
        tests=("tests/unit/test_adjudication.py", "tests/unit/test_irreversible_dispatch.py"),
    ),
    Mutation(
        name="another_projects_evidence_adjudicates",
        guards="SEC-002 — the basis resolves in the action's project",
        path="src/lab_brain/core/adjudication.py",
        old="        if found is None or found.project_id != project_id:",
        new="        if found is None:",
        tests=("tests/unit/test_adjudication.py", "tests/unit/test_irreversible_dispatch.py"),
    ),
    Mutation(
        name="dispatch_without_an_attestation_store",
        guards="fail closed — no store, no proof, no dispatch",
        path="src/lab_brain/tools/dispatch.py",
        old="            if self._attestations is None:\n                raise ToolDispatchRefused(",
        new="            if False:\n                raise ToolDispatchRefused(",
        tests=("tests/unit/test_irreversible_dispatch.py",),
    ),
    Mutation(
        name="the_brain_trusts_the_callers_objects",
        guards="§7.6 — evidence is read from the record",
        path="src/lab_brain/cognition/brain.py",
        old="            if found is None or found != attestation:",
        new="            if found is None:",
        tests=("tests/e2e/test_hypothesis_brain_postgres.py",),
    ),
    Mutation(
        name="every_reject_is_routine",
        guards="§7.6 — a root-cause REJECT is major",
        path="src/lab_brain/core/revision_gate.py",
        old="        is_reject = to_state is BeliefState.CONTRADICTED and (\n            hypothesis_set.root_cause or hypothesis_set.inverted_retrieval_required\n        )",
        new="        is_reject = False",
        tests=("tests/unit/test_revision_gate.py",),
    ),
    Mutation(
        name="every_reject_is_major",
        guards="M0b–M2 semantics — a routine REJECT needs no debate",
        path="src/lab_brain/core/revision_gate.py",
        old="        is_reject = to_state is BeliefState.CONTRADICTED and (\n            hypothesis_set.root_cause or hypothesis_set.inverted_retrieval_required\n        )",
        new="        is_reject = to_state is BeliefState.CONTRADICTED",
        tests=("tests/unit/test_revision_gate.py",),
    ),
    Mutation(
        name="the_in_memory_log_takes_any_target",
        guards="R-12 parity — the fake refuses what 011j refuses",
        path="src/lab_brain/core/repositories/belief_events.py",
        old="        if not self._hypothesis_exists(event.project_id, event.target_id):",
        new="        if False:",
        tests=("tests/unit/test_hypothesis_admission.py",),
    ),
    # -- M4 / VS-SP-001 ----------------------------------------------------------------
    Mutation(
        name="plan_choice_not_first_sufficient",
        guards="VER-001 — a plan's choice is its ranking's first sufficient action",
        path="src/lab_brain/core/models/verification.py",
        old="            if self.chosen_action_id is None or self.chosen_action_id != first_sufficient:",
        new="            if False:",
        tests=("tests/unit/test_verification_selection.py",),
    ),
    Mutation(
        name="ranking_ignores_sufficiency",
        guards="§9.2 step 1 — sufficiency ranks before cost",
        path="src/lab_brain/verification/selection.py",
        old="            not c.sufficient,",
        new="            False,",
        tests=("tests/unit/test_verification_selection.py",),
    ),
    Mutation(
        name="ranking_ignores_pareto_layer",
        guards="§9.2 step 3 — Pareto layer before the lexicographic fallback",
        path="src/lab_brain/verification/selection.py",
        old="            layers[c.action_id],",
        new="            0,",
        tests=("tests/unit/test_verification_selection.py",),
    ),
    Mutation(
        name="policy_admits_a_single_dimension",
        guards="VER-003 — a one-dimension Pareto filter is a normalized cost",
        path="src/lab_brain/core/models/verification.py",
        old="        if len(self.pareto_dimensions) < 2:",
        new="        if False:",
        tests=("tests/unit/test_verification_selection.py",),
    ),
    Mutation(
        name="plausible_outcome_need_not_be_declared",
        guards="VER-004 clause 1 — declared outcome",
        path="src/lab_brain/verification/plausibility.py",
        old="    if outcome not in space.outcomes:",
        new="    if False:",
        tests=("tests/unit/test_outcome_plausibility.py",),
    ),
    Mutation(
        name="plausible_outcome_may_be_excluded",
        guards="VER-004 clause 2 — explicit exclusion",
        path="src/lab_brain/verification/plausibility.py",
        old="    if outcome in space.explicit_exclusions:",
        new="    if False:",
        tests=("tests/unit/test_outcome_plausibility.py",),
    ),
    Mutation(
        name="plausible_outcome_ignores_validity_bounds",
        guards="VER-004 clause 2 — validity bounds",
        path="src/lab_brain/verification/plausibility.py",
        old="    violation = _bound_violation(space.validity_bounds, conditions)",
        new="    violation = None",
        tests=("tests/unit/test_outcome_plausibility.py",),
    ),
    Mutation(
        name="plausible_outcome_ignores_the_capability",
        guards="VER-004 clause 4 — the capability can yield it now",
        path="src/lab_brain/verification/plausibility.py",
        old="    if not capability.is_plannable or observable_ref not in capability.produces:",
        new="    if False:",
        tests=("tests/unit/test_outcome_plausibility.py",),
    ),
    Mutation(
        name="sufficiency_counts_implausible_outcomes",
        guards="§9.1 — only plausible outcomes can make an action sufficient",
        path="src/lab_brain/verification/sufficiency.py",
        old="                if not verdict.plausible:",
        new="                if False:",
        tests=("tests/unit/test_outcome_plausibility.py",),
    ),
    Mutation(
        name="producer_rule_removed",
        guards="VER-004 clause 4 — the domain's declared producers",
        path="src/lab_brain/domains/silicon_photonics/vertical.py",
        old="            if subject.capability_id not in _PRODUCERS[subject.observable_ref]:",
        new="            if False:",
        tests=("tests/unit/test_outcome_plausibility.py",),
    ),
    Mutation(
        name="existing_evidence_ignored",
        guards="VER-001 — admitted evidence that already decides means no new spend",
        path="src/lab_brain/verification/least_cost.py",
        old="                if verdict.outcome is TransitionOutcome.ALLOW:",
        new="                if False:",
        tests=("tests/unit/test_least_cost_planner.py",),
    ),
    Mutation(
        name="executed_checks_replanned",
        guards="VER-001 — an executed check is not offered again",
        path="src/lab_brain/verification/least_cost.py",
        old="        planned = tuple(a for a in matching if a.capability_id not in exclude)",
        new="        planned = tuple(matching)",
        tests=("tests/unit/test_least_cost_planner.py",),
    ),
    Mutation(
        name="planner_chooses_the_first_ranked",
        guards="VER-001 — the choice is the first SUFFICIENT action",
        path="src/lab_brain/verification/least_cost.py",
        old="            chosen_id = next((a for a in ranking.ranked_ids if summaries[a].sufficient), None)",
        new="            chosen_id = ranking.ranked_ids[0] if ranking.ranked_ids else None",
        tests=("tests/unit/test_least_cost_planner.py",),
    ),
    Mutation(
        name="evidence_ignores_the_space_version",
        guards="VER-004 — an outcome is comparable only in its bound version",
        path="src/lab_brain/verification/evidence.py",
        old="        and prediction.outcome_space_version == outcome.outcome_space_version",
        new="",
        tests=("tests/unit/test_run_evidence.py",),
    ),
    Mutation(
        name="evidence_from_a_failed_run",
        guards="EVI-009 — only a SUCCEEDED run is evidence",
        path="src/lab_brain/verification/evidence.py",
        old="    if run.status is not RunStatus.SUCCEEDED:",
        new="    if False:",
        tests=("tests/unit/test_run_evidence.py",),
    ),
    Mutation(
        name="root_cause_admits_model_statements",
        guards="EPI-002 — an LLM statement is not evidence",
        path="src/lab_brain/core/root_cause.py",
        old="            excluded = inadmissibility(witness)",
        new="            excluded = None",
        tests=("tests/unit/test_root_cause_trace.py",),
    ),
    Mutation(
        name="root_cause_admits_a_failed_run",
        guards="EPI-002 — the Run in the chain succeeded",
        path="src/lab_brain/core/root_cause.py",
        old="            if executed.status is not RunStatus.SUCCEEDED:",
        new="            if False:",
        tests=("tests/unit/test_root_cause_trace.py",),
    ),
    Mutation(
        name="root_cause_admits_missing_artifacts",
        guards="EPI-002 — the chain ends at stored artifacts",
        path="src/lab_brain/core/root_cause.py",
        old="            missing = [a for a in executed.output_artifacts if not artifact_exists(a)]",
        new="            missing = []",
        tests=("tests/unit/test_root_cause_trace.py",),
    ),
    Mutation(
        name="root_cause_from_a_routine_set",
        guards="EPI-001/EPI-002 — only a root-cause set's member is a root cause",
        path="src/lab_brain/core/root_cause.py",
        old="    if not hypothesis_set.root_cause:",
        new="    if False:",
        tests=("tests/unit/test_root_cause_trace.py",),
    ),
    Mutation(
        name="confirmation_without_evidence",
        guards="EPI-002 — a confirmed analysis names its evidence",
        path="src/lab_brain/core/models/failure.py",
        old="            if not self.root_cause_evidence_ids:",
        new="            if False:",
        tests=("tests/unit/test_root_cause_trace.py",),
    ),
    Mutation(
        name="miner_ignores_min_support",
        guards="§25.4 — one failure is not a pattern",
        path="src/lab_brain/core/root_cause.py",
        old="        if len(episodes) < min_support:",
        new="        if False:",
        tests=("tests/unit/test_root_cause_trace.py",),
    ),
    Mutation(
        name="candidate_may_be_active",
        guards="HEU-001 — a candidate is PENDING_REVIEW, never a rule",
        path="src/lab_brain/core/models/failure.py",
        old='    status: Literal["PENDING_REVIEW"] = "PENDING_REVIEW"',
        new='    status: str = "PENDING_REVIEW"',
        tests=("tests/unit/test_root_cause_trace.py",),
    ),
    Mutation(
        name="workflow_for_an_undeclared_capability",
        guards="VER-002 — a workflow executes a registered capability",
        path="src/lab_brain/verification/workflows.py",
        old="            if capabilities.get(capability_id) is None:",
        new="            if False:",
        tests=("tests/domains/test_vs_sp_001_pack.py",),
    ),
    Mutation(
        name="executed_workflow_without_a_run",
        guards="EPI-002 — an executed result names its Run",
        path="src/lab_brain/verification/workflows.py",
        old="        if executed and (self.run_id is None or not self.outcomes):",
        new="        if False:",
        tests=("tests/domains/test_vs_sp_001_pack.py",),
    ),
    Mutation(
        name="connectivity_rule_ignores_overlap",
        guards="DOM-SP-001 — the versioned overlap threshold",
        path="src/lab_brain/domains/silicon_photonics/diagnosis.py",
        old='        or _decimal(c.get("overlap_nm"), "overlap_nm") < MIN_CONTACT_OVERLAP_NM',
        new="        or False",
        tests=("tests/domains/test_vs_sp_001_pack.py",),
    ),
    Mutation(
        name="coarse_solve_claims_standard",
        guards="SIM-002 in VS-SP-001 — authority from the Run's validity, not the descriptor",
        path="src/lab_brain/domains/silicon_photonics/vertical_tools.py",
        old="    return backend_validity.fidelity_for(dict(run.backend_validity), SIM_STANDARD)",
        new="    return SIM_STANDARD",
        tests=("tests/e2e/test_vs_sp_001_vertical_postgres.py",),
    ),
    Mutation(
        name="loop_attempts_what_evaluate_refuses",
        guards="EPI-005 — the loop asks only for moves `evaluate` licenses",
        path="src/lab_brain/verification/loop.py",
        old="                    if verdict.outcome is not TransitionOutcome.ALLOW:",
        new="                    if False:",
        tests=("tests/e2e/test_vs_sp_001_vertical_postgres.py",),
    ),
    Mutation(
        name="loop_continues_past_confirmation",
        guards="§25.1 — a confirmed finding ends the search",
        path="src/lab_brain/verification/loop.py",
        old="            if self._supported(request):",
        new="            if False:",
        tests=("tests/e2e/test_vs_sp_001_vertical_postgres.py",),
    ),
    Mutation(
        name="run_output_skips_secret_scan",
        guards="SEC-003 — a run's output is scanned before storage",
        path="src/lab_brain/storage/postgres/run_outputs.py",
        old='        if scan.status is not SecretScanStatus.CLEAN:\n            raise RunOutputRefused(\n                f"run output',
        new='        if False:\n            raise RunOutputRefused(\n                f"run output',
        tests=("tests/integration/test_run_output_sink_postgres.py",),
    ),
    Mutation(
        name="run_output_not_compensated",
        guards="OPS-004 — a failed promotion removes the rows it created",
        path="src/lab_brain/storage/postgres/run_outputs.py",
        old="                if not had_artifact:",
        new="                if False:",
        tests=("tests/integration/test_run_output_sink_postgres.py",),
    ),
    Mutation(
        name="benchmark_cannot_see_escalation",
        guards="§26.1 M4 gate — unjustified escalation is counted",
        path="src/lab_brain/verification/root_cause_benchmark.py",
        old="            and any(t in CHEAP_TYPES for _, t in self.sufficient_alternatives)",
        new="            and False",
        tests=("tests/e2e/test_root_cause_benchmark_postgres.py",),
    ),
    # -- M5 / External Evidence Expansion (GH-001..003, §6.4, §6.16, SEC-003) ----------------
    Mutation(
        name="github_token_presented_unlisted",
        guards="GH-002 — a credential is presented only for an allowlisted repository",
        path="src/lab_brain/tool_providers/github/connector.py",
        old="        if parsed.full_name not in self._policy.private_allowlist:\n            return None",
        new="        if parsed.full_name not in self._policy.private_allowlist and self._policy.credential_ref is None:\n            return None",
        tests=("tests/security/test_github_private_access.py",),
    ),
    Mutation(
        name="github_allowlisted_without_credential_proceeds",
        guards="GH-002 — allowlisted without a credential is refused before any request",
        path="src/lab_brain/tool_providers/github/connector.py",
        old="        if token is None:\n            self._refuse(",
        new="        if False:\n            self._refuse(",
        tests=("tests/security/test_github_private_access.py",),
    ),
    Mutation(
        name="github_invisible_repo_not_audited",
        guards="GH-002 — an anonymous not-found is a refusal, audited by digest",
        path="src/lab_brain/tool_providers/github/connector.py",
        old="            if failed.kind == wire.NOT_FOUND and token is None:",
        new="            if False:",
        tests=("tests/security/test_github_private_access.py",),
    ),
    Mutation(
        name="github_refused_credential_not_audited",
        guards="GH-002 — a refused credential is audited, not a bare error",
        path="src/lab_brain/tool_providers/github/connector.py",
        old="            if failed.kind == wire.UNAUTHORIZED:",
        new="            if False:",
        tests=("tests/security/test_github_private_access.py",),
    ),
    Mutation(
        name="github_search_uses_credential",
        guards="GH-002 — discovery is always anonymous; a credential never widens a search",
        path="src/lab_brain/tool_providers/github/connector.py",
        old="query.limit, token=None)",
        new='query.limit, token=self._credentials.resolve(self._policy.project_id, self._policy.credential_ref or ""))',
        tests=("tests/security/test_github_private_access.py",),
    ),
    Mutation(
        name="github_vanished_commit_not_drift",
        guards="GH-001 — a pinned commit that no longer resolves is REF_DRIFT, never a substitute",
        path="src/lab_brain/tool_providers/github/connector.py",
        old="            if failed.kind == wire.NOT_FOUND and _COMMIT.match(ref):",
        new="            if False:",
        tests=("tests/unit/test_github_connector.py",),
    ),
    Mutation(
        name="github_locator_names_the_ref_not_the_commit",
        guards="GH-001 / §22 — the canonical locator names the resolved commit",
        path="src/lab_brain/tool_providers/github/connector.py",
        old='            canonical_locator=f"github:{info.full_name}@{commit}:{parsed.path}",',
        new='            canonical_locator=f"github:{info.full_name}@{parsed.ref}:{parsed.path}",',
        tests=("tests/unit/test_github_connector.py", "tests/unit/test_external_snapshots.py"),
    ),
    Mutation(
        name="registry_clamp_disabled",
        guards="GH-003 — a provider cannot label a record above its declared ceiling",
        path="src/lab_brain/sources/external.py",
        old="        if record.trust_class in declaration.trust_ceiling and not (",
        new="        if True or record.trust_class in declaration.trust_ceiling and not (",
        tests=("tests/contract/test_external_source_registry.py",),
    ),
    Mutation(
        name="registry_accepts_scientific_ceiling_for_technical",
        guards="GH-003 — a technical provider cannot declare a scientific trust ceiling",
        path="src/lab_brain/sources/external.py",
        old="        if declaration.technical_only and set(declaration.trust_ceiling) & SCIENTIFIC_TRUST:",
        new="        if False:",
        tests=("tests/contract/test_external_source_registry.py",),
    ),
    Mutation(
        name="registry_snapshot_capability_unchecked",
        guards="§17.21 — can_snapshot requires a retrieving adapter",
        path="src/lab_brain/sources/external.py",
        old="        if capabilities.can_snapshot and not isinstance(adapter, RetrievingAdapter):",
        new="        if False:",
        tests=("tests/contract/test_external_source_registry.py",),
    ),
    Mutation(
        name="registry_remove_is_a_noop",
        guards="M5 gate — removing the GitHub provider removes it from the searched set",
        path="src/lab_brain/sources/external.py",
        old="        if project_id is None:\n            self._adapters.pop(provider_id, None)",
        new="        if project_id is None:\n            pass",
        tests=(
            "tests/contract/test_external_source_registry.py",
            "tests/contract/test_external_provider_removal.py",
        ),
    ),
    Mutation(
        name="snapshot_cache_ignored",
        guards="§26.1 M5 — the pinned locator is the cache key; a second read is a cache hit",
        path="src/lab_brain/sources/snapshots.py",
        old="        if cached is not None:\n            if cached.content_hash",
        new="        if False:\n            if cached.content_hash",
        tests=("tests/unit/test_external_snapshots.py",),
    ),
    Mutation(
        name="pinned_rehash_served_from_cache",
        guards="§26.1 M5 — a pinned version that re-hashes differently is refused, not a cache hit",
        path="src/lab_brain/sources/snapshots.py",
        old="            if cached.content_hash != record.content_hash:",
        new="            if False:",
        tests=("tests/unit/test_external_snapshots.py",),
    ),
    Mutation(
        name="snapshot_ref_drift_not_recorded",
        guards="§6.16 — a request that now pins another version records REF_DRIFT",
        path="src/lab_brain/sources/snapshots.py",
        old="        drifted = [s for s in earlier if s.resolved_ref != snapshot.resolved_ref]",
        new="        drifted: list[ExternalSnapshot] = []",
        tests=("tests/unit/test_external_snapshots.py",),
    ),
    Mutation(
        name="retention_ignores_rights",
        guards="§20 Copyright/rights — no blanket fair use: unlicensed code keeps metadata only",
        path="src/lab_brain/sources/snapshots.py",
        old='        return Retention.METADATA_ONLY, f"{self.ref}:no-reuse-licence"',
        new='        return Retention.FULL_CONTENT, f"{self.ref}:no-reuse-licence"',
        tests=("tests/unit/test_external_snapshots.py",),
    ),
    Mutation(
        name="removal_not_recorded",
        guards="§6.16 — removed material marks earlier snapshots SOURCE_UNAVAILABLE",
        path="src/lab_brain/sources/snapshots.py",
        old="    if failed.kind is ConnectorErrorKind.SOURCE_REMOVED:\n        return list(earlier)",
        new="    if failed.kind is ConnectorErrorKind.SOURCE_REMOVED:\n        return []",
        tests=("tests/unit/test_external_snapshots.py",),
    ),
    Mutation(
        name="refusal_mistaken_for_removal",
        guards="§6.16 / GH-002 — a withdrawn authorization is a refusal, not a removal",
        path="src/lab_brain/sources/snapshots.py",
        old="        return [s for s in earlier if s.visibility is Visibility.PUBLIC]",
        new="        return list(earlier)",
        tests=("tests/security/test_github_private_access.py",),
    ),
    Mutation(
        name="vanished_public_repository_not_unavailable",
        guards="§6.16 — a public repository gone from anonymous view is unavailable, not only refused",
        path="src/lab_brain/sources/snapshots.py",
        old="        return [s for s in earlier if s.visibility is Visibility.PUBLIC]",
        new="        return []",
        tests=("tests/unit/test_external_snapshots.py",),
    ),
    Mutation(
        name="path_missing_at_new_head_is_removal",
        guards="§6.16 — a path missing at a moved branch does not unmake an earlier pinned version",
        path="src/lab_brain/sources/snapshots.py",
        old="        return [s for s in earlier if s.resolved_ref == failed.pinned_ref]",
        new="        return list(earlier)",
        tests=("tests/unit/test_external_snapshots.py",),
    ),
    Mutation(
        name="connector_error_forgets_pinned_version",
        guards="§6.16 — a failure after pinning carries the version it occurred at",
        path="src/lab_brain/tool_providers/github/connector.py",
        old="            raise self._structured(failed, commit) from failed",
        new="            raise self._structured(failed) from failed",
        tests=("tests/unit/test_external_snapshots.py",),
    ),
    Mutation(
        name="removal_not_propagated_to_work",
        guards="§6.16 / EVI-008 — a work admitted from vanished material records SOURCE_UNAVAILABLE",
        path="src/lab_brain/sources/snapshots.py",
        old="            self._mark_works(snapshot, provider_id)",
        new="            pass",
        tests=(
            "tests/unit/test_external_admission.py",
            "tests/e2e/test_external_evidence_postgres.py",
        ),
    ),
    Mutation(
        name="registry_accepts_internal_ceiling",
        guards="§6.5 — no external provider may label records as internal evidence or heuristics",
        path="src/lab_brain/sources/external.py",
        old="        if internal:\n            raise ConnectorRegistrationError(",
        new="        if False:\n            raise ConnectorRegistrationError(",
        tests=("tests/contract/test_external_source_registry.py",),
    ),
    Mutation(
        name="snapshot_model_accepts_internal_trust",
        guards="§6.5 — an external snapshot is never INTERNAL_* or EXPERT_HEURISTIC",
        path="src/lab_brain/core/models/external_source.py",
        old="        if self.trust_class in NON_EXTERNAL_TRUST:",
        new="        if False:",
        tests=("tests/unit/test_external_snapshots.py",),
    ),
    Mutation(
        name="audited_refusal_logged_with_locator",
        guards="GH-002 — a refusal the connector audited by digest is not re-logged with its locator",
        path="src/lab_brain/sources/snapshots.py",
        old="        if failed.audited:\n",
        new="        if False:\n",
        tests=("tests/security/test_github_private_access.py",),
    ),
    Mutation(
        name="sql_sink_secret_scan_skipped",
        guards="SEC-003 — external bytes are scanned before storage",
        path="src/lab_brain/storage/postgres/external_artifacts.py",
        old="        if scan.status is not SecretScanStatus.CLEAN:\n            raise SecretsFound(",
        new="        if False:\n            raise SecretsFound(",
        tests=("tests/integration/test_external_snapshots_postgres.py",),
    ),
    Mutation(
        name="snapshot_model_accepts_unpinned_code",
        guards="§22 GitHub provenance — a code snapshot is pinned to a commit SHA",
        path="src/lab_brain/core/models/external_source.py",
        old="            if not _COMMIT.match(self.resolved_ref):",
        new="            if False:",
        tests=("tests/unit/test_external_snapshots.py",),
    ),
    Mutation(
        name="snapshot_model_accepts_promoted_code",
        guards="GH-003 — a technical snapshot is TECHNICAL_ARTIFACT",
        path="src/lab_brain/core/models/external_source.py",
        old="        if self.source_type in TECHNICAL_SOURCE_TYPES and (",
        new="        if False and (",
        tests=("tests/unit/test_external_snapshots.py",),
    ),
    Mutation(
        name="refusal_event_may_name_locator",
        guards="GH-002 — an ACCESS_REFUSED event carries a digest, never the locator",
        path="src/lab_brain/core/models/external_source.py",
        old="        if refused and self.locator is not None:",
        new="        if False:",
        tests=("tests/unit/test_external_snapshots.py",),
    ),
    Mutation(
        name="literature_version_substituted",
        guards="§6.16 — a literature version the corpus does not hold is drift, not a substitute",
        path="src/lab_brain/tool_providers/literature/corpus.py",
        old='        if match["version"] is not None and match["version"] != paper["version"]:',
        new="        if False:",
        tests=("tests/unit/test_literature_adapter.py", "tests/unit/test_external_snapshots.py"),
    ),
    Mutation(
        name="admission_trusts_caller_snapshot",
        guards="M5 gate — provenance comes from the durable record, not a caller-built object",
        path="src/lab_brain/sources/admission.py",
        old="        if durable is None or durable != snapshot:",
        new="        if durable is None:",
        tests=("tests/unit/test_external_admission.py",),
    ),
    Mutation(
        name="admission_accepts_non_reported",
        guards="GH-003 / T-GH-003 — external material is admitted as REPORTED only",
        path="src/lab_brain/sources/admission.py",
        old="        if epistemic_type is not EpistemicType.REPORTED:",
        new="        if False:",
        tests=("tests/unit/test_external_admission.py",),
    ),
    Mutation(
        name="admission_stage_unbounded",
        guards="§6.4 — the claimed enrichment stage is bounded by what the snapshot kept",
        path="src/lab_brain/sources/admission.py",
        old="        if _STAGE_ORDER.index(stage) > _STAGE_ORDER.index(ceiling):",
        new="        if False:",
        tests=("tests/unit/test_external_admission.py",),
    ),
    Mutation(
        name="admission_retypes_existing_work",
        guards="EVI-004 — one work has one trust class; admission does not re-type it",
        path="src/lab_brain/sources/admission.py",
        old="            if work.trust_class is not durable.trust_class:",
        new="            if False:",
        tests=("tests/unit/test_external_admission.py",),
    ),
    Mutation(
        name="admission_mints_a_second_work",
        guards="EVI-004 — the same repository or DOI is one work however often it is cited",
        path="src/lab_brain/sources/admission.py",
        old="        work = self._works.find_by_identifier(identifier.scheme, identifier.value)",
        new="        work = None",
        tests=("tests/unit/test_external_admission.py",),
    ),
    # -- M5 P0 repair: one project's external access serves no other (GH-002) ---------------
    Mutation(
        name="connector_serves_another_project",
        guards="GH-002 — a connector refuses any project but its own before anything else",
        path="src/lab_brain/tool_providers/github/connector.py",
        old="        if project_id != self._policy.project_id:\n            self._refuse(",
        new="        if False:\n            self._refuse(",
        tests=("tests/security/test_github_project_scope.py",),
    ),
    Mutation(
        name="connector_fetch_presents_credential",
        guards="GH-002 — the project-unaware M1 fetch path is anonymous only",
        path="src/lab_brain/tool_providers/github/connector.py",
        old="        return self._read(parsed, locator, token=None).record",
        new="        return self._read(parsed, locator, token=self._access(parsed, locator)).record",
        tests=("tests/security/test_github_project_scope.py",),
    ),
    Mutation(
        name="credentials_resolve_across_projects",
        guards="GH-002 — a credential reference resolves in the asking project's namespace only",
        path="src/lab_brain/tool_providers/github/connector.py",
        old="        return self.secrets.get(project_id, {}).get(credential_ref)",
        new="        return next((v[credential_ref] for v in self.secrets.values() if credential_ref in v), None)",
        tests=("tests/security/test_github_project_scope.py",),
    ),
    Mutation(
        name="registry_registers_foreign_scope",
        guards="GH-002 — a scoped adapter is registered for its own project only",
        path="src/lab_brain/sources/external.py",
        old="        if scope is not None and (scope.provider != provider or scope.project_id != project_id):",
        new="        if False:",
        tests=("tests/security/test_github_project_scope.py",),
    ),
    Mutation(
        name="registry_lookup_falls_back_to_another_project",
        guards="GH-002 — a project gets its own adapter or a neutral one, never another project's",
        path="src/lab_brain/sources/external.py",
        old="        return scopes.get(project_id, scopes.get(None))",
        new="        return scopes.get(project_id, scopes.get(None, next(iter(scopes.values()), None)))",
        tests=("tests/security/test_github_project_scope.py",),
    ),
    Mutation(
        name="router_serves_another_project",
        guards="GH-002 — a project-bound router refuses requests for any other project",
        path="src/lab_brain/sources/external.py",
        old="        if project_id != self._project_id:\n            raise ProjectScopeMismatch(",
        new="        if False:\n            raise ProjectScopeMismatch(",
        tests=("tests/security/test_github_project_scope.py",),
    ),
    Mutation(
        name="router_holds_foreign_adapter",
        guards="GH-002 — a project-bound router cannot be given another project's adapter",
        path="src/lab_brain/sources/external.py",
        old="    if scope is not None and scope.project_id != project_id:\n        raise ProjectScopeMismatch(",
        new="    if False:\n        raise ProjectScopeMismatch(",
        tests=("tests/security/test_github_project_scope.py",),
    ),
    Mutation(
        name="service_skips_pre_egress_scope_check",
        guards="GH-002 — the service refuses a foreign scope before any egress, whatever the registry says",
        path="src/lab_brain/sources/snapshots.py",
        old="        if adapter is None or (scope is not None and scope.project_id != project_id):",
        new="        if adapter is None:",
        tests=("tests/security/test_github_project_scope.py",),
    ),
    Mutation(
        name="service_keeps_foreign_record",
        guards="GH-002 — a record read under another scope is refused before anything is kept",
        path="src/lab_brain/sources/snapshots.py",
        old="        self._within_scope(record, scope, project_id, locator)",
        new="        pass",
        tests=("tests/security/test_github_project_scope.py",),
    ),
    Mutation(
        name="service_keeps_unscoped_private_record",
        guards="GH-002 — private material from an adapter with no scope is never kept",
        path="src/lab_brain/sources/snapshots.py",
        old="        unscoped_private = record.visibility.value != Visibility.PUBLIC.value and scope is None",
        new="        unscoped_private = False",
        tests=("tests/security/test_github_project_scope.py",),
    ),
    Mutation(
        name="service_does_not_record_scope",
        guards="GH-002 — the scope a snapshot names is recorded before the snapshot",
        path="src/lab_brain/sources/snapshots.py",
        old="            self._store.record_access_scope(scope)",
        new="            pass",
        tests=(
            "tests/unit/test_external_snapshots.py",
            "tests/security/test_github_project_scope.py",
        ),
    ),
    Mutation(
        name="store_keeps_snapshot_under_foreign_scope",
        guards="GH-002 — a store keeps a snapshot only under a recorded scope of its own project",
        path="src/lab_brain/core/repositories/external_sources.py",
        old="            if scope is None or scope.project_id != snapshot.project_id:",
        new="            if False:",
        tests=("tests/unit/test_external_snapshots.py",),
    ),
    Mutation(
        name="scope_re_pointed",
        guards="GH-002 — a policy version cannot be re-pointed at another project",
        path="src/lab_brain/core/repositories/external_sources.py",
        old="    if stored != scope:",
        new="    if False:",
        tests=(
            "tests/unit/test_external_snapshots.py",
            "tests/integration/test_external_access_scopes_postgres.py",
        ),
    ),
    # -- M5 upgrade safety: pre-scope snapshots fail closed (GH-002, `002e`) ------------------
    Mutation(
        name="quarantined_snapshot_is_a_cache_hit",
        guards="GH-002 upgrade — a quarantined snapshot is never served from the cache",
        path="src/lab_brain/core/repositories/external_sources.py",
        old="                == (project_id, provider, canonical_locator)\n                and s.snapshot_id not in self._quarantine",
        new="                == (project_id, provider, canonical_locator)",
        tests=("tests/unit/test_external_snapshots.py",),
    ),
    Mutation(
        name="sql_quarantined_snapshot_is_a_cache_hit",
        guards="GH-002 upgrade — the SQL cache lookup skips quarantined rows",
        path="src/lab_brain/core/repositories/external_sources.py",
        old='            " (SELECT 1 FROM external_snapshot_quarantine q"\n            " WHERE q.snapshot_id = external_snapshots.snapshot_id)",',
        new='            " (SELECT 1 WHERE FALSE)",',
        tests=("tests/integration/test_external_snapshot_quarantine_postgres.py",),
    ),
    Mutation(
        name="admission_from_quarantined_snapshot",
        guards="GH-002 upgrade — nothing is admitted from a quarantined snapshot",
        path="src/lab_brain/sources/admission.py",
        old="        if quarantined is not None:\n            raise ExternalAdmissionRefused(",
        new="        if False:\n            raise ExternalAdmissionRefused(",
        tests=(
            "tests/unit/test_external_admission.py",
            "tests/integration/test_external_snapshot_quarantine_postgres.py",
        ),
    ),
    Mutation(
        name="quarantine_reason_forgotten",
        guards="GH-002 upgrade — a store reports a quarantine it holds",
        path="src/lab_brain/core/repositories/external_sources.py",
        old="        return self._quarantine.get(snapshot_id)",
        new="        return None",
        tests=("tests/unit/test_external_snapshots.py", "tests/unit/test_external_admission.py"),
    ),
    Mutation(
        name="replay_selection_empty",
        guards="§6.18 / GH-002 upgrade — evidence from quarantined snapshots is the replay selection",
        path="src/lab_brain/core/repositories/external_sources.py",
        old='            " WHERE project_id = %s ORDER BY attestation_id",',
        new='            " WHERE project_id = %s AND FALSE ORDER BY attestation_id",',
        tests=("tests/integration/test_external_snapshot_quarantine_postgres.py",),
    ),
    # -- product vertical: research run, end to end, with no simulator -----------------------
    Mutation(
        name="product_simulator_left_available",
        guards="product vertical -- a capability with no backend here is UNAVAILABLE, never attempted",
        path="src/lab_brain/domains/silicon_photonics/product.py",
        old="            capabilities.set_availability(capability.capability_id, Availability.UNAVAILABLE)",
        new="            pass",
        tests=(
            "tests/unit/test_research_vertical.py",
            "tests/e2e/test_research_episode_postgres.py",
        ),
    ),
    Mutation(
        name="product_research_without_membership",
        guards="product vertical -- a non-member gets no episode, no rows and no report (SEC-002)",
        path="src/lab_brain/research/service.py",
        old="        self._service.read_gate().require_project(\n            actor_id=request.actor_id, project_id=request.project_id\n        )",
        new="        pass",
        tests=("tests/e2e/test_research_episode_postgres.py",),
    ),
    Mutation(
        name="product_pending_includes_runnable_actions",
        guards="product vertical -- only what cannot run here is reported as pending",
        path="src/lab_brain/research/service.py",
        old="            if action_id not in blocked or not summary.sufficient:",
        new="            if not summary.sufficient:",
        tests=("tests/e2e/test_research_episode_postgres.py",),
    ),
    Mutation(
        name="product_blocked_episode_closed_as_finished",
        guards="product vertical -- an episode waiting on a simulator or a person is parked, not finished",
        path="src/lab_brain/research/service.py",
        old="        if stop in _WAITING or best is not None:",
        new="        if False:",
        tests=("tests/e2e/test_research_episode_postgres.py",),
    ),
    Mutation(
        name="product_literature_query_not_declared",
        guards="product vertical -- a provider is searched only with a query the actor declared public",
        path="src/lab_brain/interfaces/cli.py",
        old="        if not (args.literature_corpus and args.literature_query):",
        new="        if False:",
        tests=("tests/e2e/test_research_episode_postgres.py",),
    ),
    Mutation(
        name="reasoner_critic_uses_uninverted_evidence",
        guards="catalog reasoner -- the Critic objects only from the inverted evidence it was shown",
        path="src/lab_brain/cognition/catalog_reasoner.py",
        old='                if e["attestation_id"] not in inverted:\n                    continue',
        new="                pass",
        tests=("tests/unit/test_catalog_reasoner.py",),
    ),
    Mutation(
        name="classifier_ignores_cited_work_artifact",
        guards="SEC-001 -- external evidence is classified by its snapshot artifact, or refused",
        path="src/lab_brain/composition.py",
        old="                return own if own is not None else fallback(attestation_id, project_id)",
        new="                return own",
        tests=("tests/e2e/test_research_episode_postgres.py",),
    ),
    Mutation(
        name="continuation_scope_ignores_project",
        guards="episode continuation -- an episode is continued only from its own project",
        path="src/lab_brain/research/continuation.py",
        old='            " WHERE episode_id = %s AND project_id = %s AND ordinal = 1",',
        new='            " WHERE episode_id = %s AND %s::text IS NOT NULL AND ordinal = 1",',
        tests=("tests/e2e/test_research_continuation_postgres.py",),
    ),
    Mutation(
        name="continuation_ignores_opener_actor",
        guards="episode continuation -- only the actor who opened an episode continues it",
        path="src/lab_brain/research/service.py",
        old="        if opener is None or opener.actor_id != request.actor_id:",
        new="        if opener is None:",
        tests=("tests/e2e/test_research_continuation_postgres.py",),
    ),
    Mutation(
        name="continuation_skips_lifecycle_resume",
        guards="episode continuation -- a suspended episode resumes through episode_resume",
        path="src/lab_brain/research/service.py",
        old="            episode = episodes.resume(episode_id)",
        new="            episode = episodes.get(episode_id) or episode",
        tests=("tests/e2e/test_research_continuation_postgres.py",),
    ),
    Mutation(
        name="continuation_accepts_finished_episode",
        guards="episode continuation -- a finished episode is refused before anything is written",
        path="src/lab_brain/research/service.py",
        old="            if episode.state in (EpisodeState.COMPLETED, EpisodeState.ABANDONED):",
        new="            if False:",
        tests=("tests/e2e/test_research_continuation_postgres.py",),
    ),
    Mutation(
        name="continuation_debates_again",
        guards="episode continuation -- the recorded debate is reused, never a parallel one",
        path="src/lab_brain/research/service.py",
        old="        if resumed is not None:\n            outcome = resumed",
        new="        if False:\n            outcome = resumed",
        tests=("tests/e2e/test_research_continuation_postgres.py",),
    ),
    Mutation(
        name="continuation_forgets_executed_checks",
        guards="episode continuation -- a check an earlier run executed is not executed again",
        path="src/lab_brain/research/service.py",
        old="            planner = ExcludingPlanner(planner, _executed_before(run))",
        new="            planner = ExcludingPlanner(planner, frozenset())",
        tests=("tests/e2e/test_research_continuation_postgres.py",),
    ),
    Mutation(
        name="continuation_executed_before_empty",
        guards="episode continuation -- what the episode executed reaches both the loop and the pending question",
        path="src/lab_brain/research/service.py",
        old="    return frozenset(run.continuation.prior.executed)",
        new="    return frozenset()",
        tests=("tests/e2e/test_research_continuation_postgres.py",),
    ),
    Mutation(
        name="continuation_reuses_earlier_job_keys",
        guards="episode continuation -- a continuation's jobs are keyed in its own namespace",
        path="src/lab_brain/research/continuation.py",
        old="            key = self._namespace + key[len(self._prefix) :]",
        new="            key = key",
        tests=("tests/e2e/test_research_continuation_postgres.py",),
    ),
    Mutation(
        name="continuation_leaves_parked_jobs_queued",
        guards="episode continuation -- a job an earlier run parked is superseded, not left queued",
        path="src/lab_brain/research/service.py",
        old="            for parked in prior.parked:",
        new="            for parked in ():",
        tests=("tests/e2e/test_research_continuation_postgres.py",),
    ),
    Mutation(
        name="continuation_ignores_interrupted_run",
        guards="episode continuation -- a run whose process died is recorded INTERRUPTED",
        path="src/lab_brain/research/service.py",
        old="            interrupted = ledger.interrupt_live(",
        new="            interrupted = () if True else ledger.interrupt_live(",
        tests=("tests/e2e/test_research_continuation_postgres.py",),
    ),
    Mutation(
        name="continuation_ignores_live_run",
        guards="episode continuation -- a live run holds the episode",
        path="src/lab_brain/research/service.py",
        old="        if not ledger.lease(episode_id):\n            raise EpisodeInProgress(",
        new="        if not (ledger.lease(episode_id) or True):\n            raise EpisodeInProgress(",
        tests=("tests/e2e/test_research_continuation_postgres.py",),
    ),
    Mutation(
        name="continuation_takes_new_inputs",
        guards="episode continuation -- a continuation takes no new inputs, whatever the caller",
        path="src/lab_brain/research/service.py",
        old="        _require_nothing_new(request)\n",
        new="        pass\n",
        tests=("tests/e2e/test_research_continuation_postgres.py",),
    ),
    Mutation(
        name="open_episode_returns_another_episode",
        guards="episode ids -- opening never hands back another project's episode",
        path="src/lab_brain/composition.py",
        old="        if (stored.project_id, stored.trace_id, stored.goal) != (project_id, trace_id, goal):",
        new="        if False:",
        tests=("tests/e2e/test_research_continuation_postgres.py",),
    ),
    Mutation(
        name="verification_error_closes_episode",
        guards="episode continuation -- a verification error parks the episode for a retry",
        path="src/lab_brain/research/service.py",
        old='        elif any(s.stage == "verification" and s.status == "FAILED" for s in run.stages):',
        new="        elif False:",
        tests=("tests/e2e/test_research_continuation_postgres.py",),
    ),
    Mutation(
        name="workspace_host_unchecked",
        guards="research workspace -- only this machine's host names are answered",
        path="src/lab_brain/interfaces/web/app.py",
        old="        if host not in self._hosts:",
        new="        if False:",
        tests=("tests/unit/test_web_workspace.py",),
    ),
    Mutation(
        name="workspace_csrf_unchecked",
        guards="research workspace -- a state-changing request carries this workspace's token",
        path="src/lab_brain/interfaces/web/app.py",
        old='            if not hmac.compare_digest(form.value("csrf"), self._csrf):',
        new="            if False:",
        tests=("tests/e2e/test_web_workspace_postgres.py",),
    ),
    Mutation(
        name="workspace_origin_unchecked",
        guards="research workspace -- a cross-origin POST is refused",
        path="src/lab_brain/interfaces/web/app.py",
        old='            if origin is not None and origin not in {f"http://{h}" for h in self._hosts}:',
        new="            if False:",
        tests=("tests/e2e/test_web_workspace_postgres.py",),
    ),
    Mutation(
        name="workspace_episode_not_bound_to_opener",
        guards="research workspace -- an episode is shown only to the actor who opened it",
        path="src/lab_brain/interfaces/web/app.py",
        old='            " WHERE r.episode_id = %s AND r.ordinal = 1 AND r.actor_id = %s",',
        new='            " WHERE r.episode_id = %s AND r.ordinal = 1 AND %s::text IS NOT NULL",',
        tests=("tests/e2e/test_web_workspace_postgres.py",),
    ),
    Mutation(
        name="workspace_episode_ignores_membership",
        guards="research workspace -- a lapsed member sees their episode no more",
        path="src/lab_brain/interfaces/web/app.py",
        old="        if (\n            not self._gate(c)\n",
        new="        if False and (\n            not self._gate(c)\n",
        tests=("tests/e2e/test_web_workspace_postgres.py",),
    ),
    Mutation(
        name="workspace_projects_ignore_the_gate",
        guards="research workspace -- only projects the read gate admits are offered",
        path="src/lab_brain/interfaces/web/app.py",
        old="            if gate.authorize_project(actor_id=self._actor, project_id=str(r[0])).allowed",
        new="            if True",
        tests=("tests/e2e/test_web_workspace_postgres.py",),
    ),
    Mutation(
        name="workspace_excerpts_not_reauthorized",
        guards="research workspace -- a stored excerpt is shown only under current clearance",
        path="src/lab_brain/interfaces/web/app.py",
        old="            lines.append(line if readable else dataclasses.replace(line, excerpt=WITHHELD))",
        new="            lines.append(line)",
        tests=("tests/e2e/test_web_workspace_postgres.py",),
    ),
    Mutation(
        name="workspace_literature_query_not_declared",
        guards="research workspace -- a literature query is sent only when declared public",
        path="src/lab_brain/interfaces/web/app.py",
        old='            if form.value("literature_query_public") != "yes":',
        new="            if False:",
        tests=("tests/e2e/test_web_workspace_postgres.py",),
    ),
    Mutation(
        name="workspace_completed_episode_offers_continuation",
        guards="research workspace -- a finished episode is read-only",
        path="src/lab_brain/interfaces/web/app.py",
        old='                continuable=opened.row.state not in ("COMPLETED", "ABANDONED"),',
        new="                continuable=True,",
        tests=("tests/e2e/test_web_workspace_postgres.py",),
    ),
    Mutation(
        name="workspace_values_not_escaped",
        guards="research workspace -- nothing a user or report supplies becomes markup",
        path="src/lab_brain/interfaces/web/pages.py",
        old="    return value if isinstance(value, Html) else Html(html.escape(str(value), quote=True))",
        new="    return Html(str(value))",
        tests=("tests/unit/test_web_workspace.py",),
    ),
    Mutation(
        name="workspace_report_drops_blocked_simulations",
        guards="research workspace -- the page shows every field of the returned report",
        path="src/lab_brain/interfaces/web/pages.py",
        old="        for p in r.pending\n    ]",
        new="        for p in ()\n    ]",
        tests=("tests/unit/test_web_workspace.py",),
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
