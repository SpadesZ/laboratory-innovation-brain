# Laboratory Innovation Brain - Implementation Status

System Version: 0.0.1
Current Milestones: **M4 — First Vertical (VS-SP-001)** and **M5 — External Evidence Expansion** —
both `IN_PROGRESS`, neither signed off.
(M0a **DONE** 2026-09-13, M0b **DONE** 2026-09-20, both on maintainer sign-off)

**M3 — Hypothesis Brain** is **DONE / HARD-LOCKED** 2026-09-27 on independent review sign-off at
`6416adb1f72ada341f82fb04731e1fababd140d9`. All **5** of its requirements (`EPI-001`, `LLM-002`,
`SRC-002`, `SRC-003`, `VER-008`) carry implementation and readiness evidence, every clause of the
exit gate is demonstrated -- role I/O and Position/Critique contracts, a measurable Critic bundle
divergence, and a BenchmarkPolicy calibrated on the fixed SiPho debate benchmark before any gate
enforces it -- and the review's two repairs (§7.6 adjudication from the record, R-12 closed by
`011j`) are in; see [`M3-readiness.md`](docs/implementation/M3-readiness.md) §1, §11 and §12. **The
executed-coverage ratchet now enforces M3 on every CI run.**

**M2 — Silicon Photonics Tool Layer** is **DONE / HARD-LOCKED** 2026-09-25 on independent review
sign-off at `66ef099f965a0f6a8e7aa1ecd836eec4555a26f3`. All **8** of its requirements carry
implementation and readiness evidence and both exit-gate clauses -- one extractor contract shared by
simulated and measured fixtures, and the license/resource queue -- are demonstrated through durable
rows; see [`M2-readiness.md`](docs/implementation/M2-readiness.md) §1 and the review repairs in §9–§11.
**The executed-coverage ratchet now enforces M2 on every CI run.** There is no Lumerical seat here
(Risk R-1): the contract is proven against a deterministic mock, and TST-001's licensed replay is
open and allocated to M4.

**M1 — Research Memory** is **DONE / HARD-LOCKED** 2026-09-23 on independent review sign-off at
`bdb72129a1075d69a30f5043a3491570ca7d4521`. All **21** of its requirements carry implementation and
readiness evidence, and every clause of the M1 exit gate is demonstrated; the per-requirement matrix
is [`M1-readiness.md`](docs/implementation/M1-readiness.md) §2. The ratchet enforces M1 on every CI
run.

**M4 — First Vertical (VS-SP-001)** is `IN_PROGRESS` from 2026-09-27 and **externally blocked on
TST-001**: all **7** requirements (`VER-001`, `VER-003`, `VER-004`, `VER-005`, `VER-007`, `EPI-002`,
`TST-001`) carry marked tests, and the fixed, non-cherry-picked VS-SP-001 benchmark passes the exit
gate -- 10/10 cases end where the fixture says, 0 unjustified escalations, 0 high-cost actions in
cheap-resolvable cases, against a simulate-first baseline that escalates 15 times; see
[`M4-readiness.md`](docs/implementation/M4-readiness.md) and
[`root_cause_benchmark_report.md`](benchmarks/root_cause_benchmark_report.md). The backends are
deterministic mocks. TST-001's licensed Lumerical replay was **attempted and cannot run here** --
no Lumerical/Ansys installation, no `lumapi`, no licence server or seat, no licensed provider module
and no Lumerical project for the case (Risk R-1; the probe is recorded in
[`M4-readiness.md`](docs/implementation/M4-readiness.md) §11). It is not emulated and not claimed.
Moving a milestone to DONE is the maintainer's act on independent review, not the implementing agent's -- an
agent that signs off its own work has verified nothing.

**M5 — External Evidence Expansion** is `IN_PROGRESS` from 2026-09-27 (was `DEFERRED`), taken up
while M4 awaits its review and built on M4's final SHA as a provisional baseline -- no M4 file was
changed. All **3** requirements (`GH-001`, `GH-002`, `GH-003`) carry marked tests and every clause
of the exit gate is demonstrated: external evidence enters with source, condition, rights and
provenance metadata; GitHub material traces to repository identity, resolved commit, retrieval time
and content hash; removing the GitHub provider leaves core cognition running and makes the novelty
audit say what it did not search. See [`M5-readiness.md`](docs/implementation/M5-readiness.md).
**Every external provider exercised is a deterministic fixture; no live GitHub or literature request
is part of the recorded verification**, and the optional `network`-marked live test was not run.
The review's P0 -- project B consuming project A's GitHub access policy, allowlist or credential --
is repaired and accepted: authorization is an `ExternalAccessScope` bound to one project at
registration, lookup, routing, retrieval, credential resolution, storage and in SQL (`002d`).
Snapshots that predate the repair fail closed on upgrade: `002e` quarantines every row whose project
and access scope cannot be proven coherent, and quarantined material is not a cache hit, not
admitted, not citable anew, and is the §6.18 replay selection. M5's gate profile is the normative
`[postgres]` (T-GH-001 is fixture-based; the live check is optional and evidence for nothing). See
`M5-readiness.md` §4.6, §4.7 and §5.7. M5 is **ready for independent review**.

**Product vertical -- `lab-brain research run`** (2026-09-28; not a milestone, no status changed). A
research goal plus local files in, one report out: ingestion, verbatim statements through M1's
admission gate, M5 literature (only with a query the actor declares public), M3's debate, M4's
verification loop, and a report of hypotheses, critique, belief, plans, executed checks and
**pending simulations**. With no simulator every SIMULATION capability is UNAVAILABLE, cheap checks
run, the best next simulation is reported BLOCKED and the episode is SUSPENDED -- nothing is mocked.
With no language model the debate runs on the pack's rule-based catalog reasoner, labelled as such.
See [`product-vertical.md`](docs/implementation/product-vertical.md), which also records two latent
defects the work found and fixed (`open_episode` without an id; a relative `--artifact-root`).
`research run --episode E` **continues** E and nothing else (`product-vertical.md` §8, `012c`): only
the opener's own SUSPENDED episode in the same project, resumed through `episode_resume`, over the
hypothesis set its first run debated -- never a second debate, never new inputs, never a check
executed twice. Unknown and foreign ids get one answer and write nothing; a finished episode
receives no new run; each run is recorded in `research_runs` under a lease on its episode.

**Research workspace -- `lab-brain web`** (2026-09-28; not a milestone, no status changed; not M7's
Web Knowledge Inbox). The Product Vertical in a browser, on this machine, as one actor: a form opens
a research run through `ResearchEpisodeService.run`, **Continue** re-enters a SUSPENDED episode
through the accepted continuation path, and a COMPLETED episode is read-only. Pages show the report
each run returned, recorded as returned (`012d_research_run_reports`), beside the episode's live
state -- a second renderer of the same data, with no script and no derivation. Authorization is the
server's on every request (read gate, opener binding, stored excerpts re-authorized against current
clearance); POSTs carry a CSRF token; loopback only. See
[`web-workspace.md`](docs/implementation/web-workspace.md).

Slice M1-P1: **HARD-LOCKED** 2026-09-21 at `f8e5e9c02ee98ed2a7faa6f604347b84b88c773b` on
independent M2 review. That lock is on the *slice*, predates the milestone locks above, and remains
in force independently of them. The fourteen locked items are tabulated in
[`M1-P1-readiness.md`](docs/implementation/M1-P1-readiness.md) §12; the slice handoff is
[`M1-P1-handoff.md`](docs/implementation/M1-P1-handoff.md).

Four statements this header used to carry were true when written and became false as the work
moved, and all four are left recorded rather than deleted: *"Thirteen of M1's twenty-one
requirements are still untouched"* (true at the M1-P1 lock, corrected at `bdb7212`), *"the slice is
locked, the milestone is not"* (true until the M1 sign-off above), *"M2 stays `IN_PROGRESS`
until its own independent review"* (true until the M2 sign-off above), and *"M3 is `IN_PROGRESS`
... submitted for independent review"* (true until the M3 sign-off above). A status file that
under-reports is read as a to-do list by whoever picks the work up next.

Last Updated: 2026-09-27

## Spec Baseline

<!-- BEGIN GENERATED: spec-baseline -->

Generated by `scripts/update_status.py` from the specification's Version Notes table and the `migrations/` directory. Hand-typed here until P5-fix, and wrong twice.

| | |
|---|---|
| Spec | SAI 3.3 — `docs/spec/SAI_3.3.md` |
| Spec amendments in force | `v3.3-a1` … `v3.3-a18` (18 amendments) |
| Migrations declared | 51 — `001_actors_projects.sql` … `012d_research_run_reports.sql` |

Whether a given database has *applied* those migrations is not a property of this repository and is not asserted here: run `python scripts/migrate.py --status`.

<!-- END GENERATED: spec-baseline -->

## Environment

- Python: 3.12.10 (`.venv`)
- PostgreSQL: 17 + pgvector via `compose.yaml` (host port 5433); **running**
- Lumerical availability: not available in this environment
- Lumerical seats available / concurrent limit: 0 / unknown — see Risk R-1
- Real-run gate mode: manual (no license seat; mock backends only)
- Ground-truth benchmark cases collected: 0 / target TBD — see Risk R-2
- Configured LLM slots: none (all 6 slots + EMBEDDING empty; §7.3 logical slots only)
- Verification backends available: none yet (PostgreSQL is storage, not a verification backend)
- External network mode: private (no egress configured)
- Configured external source adapters: none in any deployment; GitHub (fixture transport) and a
  PaperQA-style literature corpus (fixture) exist and are exercised in tests only
- GitHub connector auth mode / scope: not configured; private access requires a project allowlist
  AND a resolvable credential, and otherwise fails closed (GH-002)

Package manager note: the §18 tree lists `uv.lock`. `uv` could not be installed in this
environment, so dependencies are managed with `python -m venv` + `pip install -e`. This is
a tooling choice against an informative file listing, not a deviation from a normative
statement, so no ADR is raised. Switching to `uv` later requires no source change.

## Requirement Status

<!-- BEGIN GENERATED: requirement-status -->

Generated by `scripts/update_status.py` from `docs/milestones.yaml` and test markers. 60 requirements / 60 tests.

| ID | Milestone | Status | Spec Test | Test files |
|---|---|---|---|---|
| ART-001 | M0a | DONE | `T-ART-001` | `contract/test_artifact_identity.py`, `integration/test_schema_constraints_postgres.py` |
| EVI-005 | M0a | DONE | `T-EVI-005` | `contract/test_comparator_version_binding.py`, `contract/test_condition_schema.py`, `integration/test_schema_constraints_postgres.py` |
| EVI-006 | M0a | DONE | `T-EVI-006` | `contract/test_evidence_bundle.py`, `integration/test_evidence_bundles_postgres.py` |
| TST-002 | M0a | DONE | `T-SPEC-001` | `spec/test_requirement_traceability.py` |
| TST-003 | M0a | DONE | `T-SPEC-002` | `spec/test_normative_statement_coverage.py` |
| SYS-001 | M0b | DONE | `T-SYS-001` | `e2e/test_episode_cognition_path_postgres.py`, `unit/test_sys001_static_conformance.py` |
| SEC-002 | M0b | DONE | `T-SEC-002` | `integration/test_artifact_occurrence_postgres.py`, `integration/test_inbox_authorization_postgres.py`, `security/test_project_scoped_access.py`, `security/test_scientific_read_authorization_postgres.py` |
| COST-001 | M0b | DONE | `T-COST-001` | `contract/test_budget_gate.py`, `e2e/test_m2_vertical_postgres.py`, `integration/test_cost_ledger_postgres.py`, `unit/test_budgeted_tool_dispatch.py` |
| EPI-003 | M0b | DONE | `T-EPI-003` | `contract/test_belief_replay.py`, `contract/test_belief_revision_event.py`, `e2e/test_belief_replay_postgres.py`, `integration/test_belief_events_postgres.py` |
| EPI-004 | M0b | DONE | `T-EPI-004` | `e2e/test_authority_review_loop_postgres.py`, `unit/test_authority_policy.py` |
| EPI-005 | M0b | DONE | `T-EPI-005` | `contract/test_belief_authorization_verification.py`, `contract/test_belief_transition.py`, `contract/test_transition_policy.py`, `e2e/test_belief_authorization_verification_postgres.py`, `e2e/test_cognition_transition_vertical_postgres.py`, `integration/test_transition_policies_postgres.py` |
| EPI-006 | M0b | DONE | `T-EPI-006` | `contract/test_conflict.py`, `integration/test_conflicts_postgres.py`, `integration/test_governance_event_chain_binding_postgres.py`, `integration/test_review_conflict_commit_invariant_postgres.py` |
| VER-006 | M0b | DONE | `T-VER-006` | `contract/test_prediction_sufficiency.py`, `e2e/test_hypothetical_evaluation_postgres.py` |
| OPS-002 | M0b | DONE | `T-OPS-002` | `integration/test_review_expiry_postgres.py`, `integration/test_review_queue_postgres.py` |
| OPS-003 | M0b | DONE | `T-OPS-003` | `contract/test_dispatch_seam.py`, `contract/test_execution_span.py`, `e2e/test_episode_trace_postgres.py`, `integration/test_execution_spans_postgres.py` |
| EVI-002 | M1 | DONE | `T-EVI-002` | `contract/test_evidence_admission.py` |
| EVI-003 | M1 | DONE | `T-EVI-003` | `contract/test_evidence_admission.py`, `contract/test_evidence_repair_probes.py` |
| EVI-004 | M1 | DONE | `T-EVI-004` | `contract/test_source_work_resolution.py` |
| EVI-007 | M1 | DONE | `T-EVI-007` | `contract/test_dense_retrieval.py` |
| EVI-008 | M1 | DONE | `T-EVI-008` | `integration/test_source_status_postgres.py` |
| EVI-009 | M1 | DONE | `T-EVI-009` | `contract/test_evidence_admission.py`, `contract/test_run_backed_evidence.py` |
| EVI-010 | M1 | DONE | `T-EVI-010` | `contract/test_evidence_benchmark.py`, `contract/test_evidence_repair2_probes.py`, `contract/test_evidence_repair_probes.py`, `contract/test_evidence_segmentation.py`, `contract/test_evidence_unit_identity.py`, `contract/test_retrieval_boundary.py`, `e2e/test_duplicate_ingest_postgres.py`, `e2e/test_ingestion_vertical_postgres.py`, `e2e/test_production_ingestion_writer_postgres.py`, `integration/test_evidence_occurrences_postgres.py`, `integration/test_evidence_units_postgres.py` |
| LLM-001 | M1 | DONE | `T-LLM-001` | `contract/test_llm_and_sources.py`, `integration/test_durable_provenance_and_episodes_postgres.py` |
| OPS-001 | M1 | DONE | `T-OPS-001` | `contract/test_job_lifecycle.py`, `contract/test_resource_demand_binding.py`, `e2e/test_m1_vertical_postgres.py`, `e2e/test_m2_vertical_postgres.py`, `integration/test_durable_provenance_and_episodes_postgres.py`, `integration/test_jobs_runs_postgres.py` |
| OPS-004 | M1 | DONE | `T-OPS-004` | `integration/test_cross_store_compensation.py` |
| SEC-001 | M1 | DONE | `T-SEC-001` | `security/test_egress_and_licensing.py`, `security/test_external_effect_authorization.py` |
| SEC-003 | M1 | DONE | `T-SEC-003` | `security/test_secret_scan_ordering.py` |
| SEC-004 | M1 | DONE | `T-SEC-004` | `security/test_egress_and_licensing.py` |
| SRC-001 | M1 | DONE | `T-SRC-001` | `contract/test_llm_and_sources.py` |
| UX-001 | M1 | DONE | `T-UX-001` | `contract/test_budget_and_cli.py`, `contract/test_ingestion_surfaces.py`, `integration/test_cli_surface_postgres.py`, `integration/test_inbox_authorization_postgres.py` |
| UX-002 | M1 | DONE | `T-UX-002` | `contract/test_budget_and_cli.py`, `contract/test_ingestion_surfaces.py` |
| UX-003 | M1 | DONE | `T-UX-003` | `contract/test_budget_and_cli.py`, `integration/test_cli_surface_postgres.py`, `security/test_diagnostics_disclosure.py` |
| UX-004 | M1 | DONE | `T-UX-004` | `e2e/test_stage_retry_resume_postgres.py`, `integration/test_cross_store_compensation.py` |
| UX-005 | M1 | DONE | `T-UX-005` | `integration/test_extraction_review_postgres.py`, `integration/test_inbox_authorization_postgres.py` |
| UX-006 | M1 | DONE | `T-UX-006` | `contract/test_budget_and_cli.py`, `contract/test_ingestion_surfaces.py` |
| UX-007 | M1 | DONE | `T-UX-007` | `contract/test_ingestion_surfaces.py`, `e2e/test_m2_vertical_postgres.py` |
| SIM-001 | M2 | DONE | `T-SIM-001` | `contract/test_simulation_contract.py`, `e2e/test_m2_vertical_postgres.py` |
| SIM-002 | M2 | DONE | `T-SIM-002` | `e2e/test_sim_fidelity_gate_postgres.py`, `e2e/test_sim_fidelity_vertical_postgres.py` |
| SIM-003 | M2 | DONE | `T-SIM-003` | `unit/test_typed_tool_registry.py` |
| EVI-001 | M2 | DONE | `T-EVI-001` | `domains/test_cj_rs_evidence_contract.py` |
| DOM-SP-001 | M2 | DONE | `T-DOM-SP-001` | `domains/test_domain_pack_boundary.py` |
| DOM-SP-002 | M2 | DONE | `T-DOM-SP-002` | `domains/test_shared_extractor_contract.py`, `e2e/test_m2_vertical_postgres.py` |
| VER-002 | M2 | DONE | `T-VER-002` | `e2e/test_m2_vertical_postgres.py`, `unit/test_capability_planning.py` |
| EXT-001 | M2 | DONE | `T-EXT-001` | `unit/test_extension_boundary.py` |
| EPI-001 | M3 | DONE | `T-EPI-001` | `e2e/test_hypothesis_brain_postgres.py`, `integration/test_belief_event_targets_postgres.py`, `integration/test_hypothesis_storage_postgres.py`, `unit/test_hypothesis_admission.py`, `unit/test_revision_gate.py` |
| LLM-002 | M3 | DONE | `T-LLM-002` | `contract/test_debate_benchmark.py`, `integration/test_hypothesis_storage_postgres.py`, `unit/test_benchmark_gate.py`, `unit/test_debate_protocol.py`, `unit/test_revision_gate.py` |
| SRC-002 | M3 | DONE | `T-SRC-002` | `contract/test_critique_gate.py`, `e2e/test_hypothesis_brain_postgres.py`, `integration/test_hypothesis_storage_postgres.py`, `unit/test_adjudication.py`, `unit/test_debate_protocol.py`, `unit/test_irreversible_dispatch.py`, `unit/test_revision_gate.py` |
| SRC-003 | M3 | DONE | `T-SRC-003` | `integration/test_prior_art_postgres.py`, `unit/test_novelty_audit.py` |
| VER-008 | M3 | DONE | `T-VER-008` | `unit/test_disagreement_metrics.py` |
| VER-001 | M4 | IN_PROGRESS | `T-VER-001` | `e2e/test_root_cause_benchmark_postgres.py`, `e2e/test_vs_sp_001_vertical_postgres.py`, `integration/test_verification_plans_postgres.py`, `unit/test_least_cost_planner.py` |
| VER-003 | M4 | IN_PROGRESS | `T-VER-003` | `unit/test_verification_selection.py` |
| VER-004 | M4 | IN_PROGRESS | `T-VER-004` | `unit/test_outcome_plausibility.py` |
| VER-005 | M4 | IN_PROGRESS | `T-VER-005` | `integration/test_verification_plans_postgres.py`, `unit/test_verification_selection.py` |
| VER-007 | M4 | IN_PROGRESS | `T-VER-007` | `unit/test_design_tradeoffs.py` |
| EPI-002 | M4 | IN_PROGRESS | `T-EPI-002` | `e2e/test_root_cause_provenance_postgres.py`, `unit/test_root_cause_trace.py` |
| TST-001 | M4 | IN_PROGRESS | `T-E2E-SP-001` | `e2e/test_root_cause_benchmark_postgres.py`, `e2e/test_vs_sp_001_licensed_replay.py`, `e2e/test_vs_sp_001_vertical_postgres.py` |
| GH-001 | M5 | IN_PROGRESS | `T-GH-001` | `e2e/test_external_evidence_postgres.py`, `integration/test_external_snapshots_postgres.py`, `unit/test_external_snapshots.py`, `unit/test_github_connector.py` |
| GH-002 | M5 | IN_PROGRESS | `T-GH-002` | `integration/test_external_access_scopes_postgres.py`, `integration/test_external_snapshot_quarantine_postgres.py`, `integration/test_external_snapshots_postgres.py`, `security/test_github_private_access.py`, `security/test_github_project_scope.py` |
| GH-003 | M5 | IN_PROGRESS | `T-GH-003` | `contract/test_external_source_registry.py`, `e2e/test_external_evidence_postgres.py`, `integration/test_external_snapshots_postgres.py`, `unit/test_external_admission.py`, `unit/test_external_snapshots.py` |
| HEU-001 | M7 | DEFERRED | `T-HEU-001` | — |

**Totals**: DEFERRED 1 · DONE 49 · IN_PROGRESS 10

<!-- END GENERATED: requirement-status -->

Statuses: TODO / IN_PROGRESS / BLOCKED / DONE / DEFERRED

## Tests

<!-- BEGIN GENERATED: test-inventory -->

Generated by `scripts/update_status.py` from the collection the last whole-suite `pytest` run recorded. Counts are **collected** tests, which is profile-independent: the `postgres` and backend-free profiles collect the same set and differ only in what they skip. `Backend-gated` counts tests carrying a `postgres` / `lumerical` / `network` marker.

| Suite | Collected | Backend-gated |
|---|---:|---:|
| Unit | 467 | — |
| Contract | 758 | — |
| Integration | 535 | 525 |
| E2E | 205 | 205 |
| Security | 129 | 14 |
| UX | 0 | — |
| Spec — `test_ci_workflow` | 6 | — |
| Spec — `test_commit_message_hygiene` | 56 | — |
| Spec — `test_conformance_guards` | 26 | — |
| Spec — `test_executed_coverage_guards` | 28 | — |
| Spec — `test_m0a_coverage_audit` | 11 | — |
| Spec — `test_m0a_obligation_inventory` | 19 | — |
| Spec — `test_marker_collection` | 5 | — |
| Spec — `test_migration_numbering` | 6 | — |
| Spec — `test_normative_statement_coverage` | 10 | — |
| Spec — `test_requirement_traceability` | 11 | — |
| Spec — `test_schema_drift` | 18 | — |
| Spec — `test_spec_issue_index` | 3 | — |
| Spec — `test_status_freshness` | 7 | — |
| `tests/domains/test_cj_rs_evidence_contract.py` | 18 | — |
| `tests/domains/test_domain_pack_boundary.py` | 14 | — |
| `tests/domains/test_shared_extractor_contract.py` | 9 | — |
| `tests/domains/test_vs_sp_001_pack.py` | 18 | — |
| **Total** | **2359** | **744** |

A bare `pytest` executes **1615** of the 2359 and skips the 744 backend-gated ones, so no PostgreSQL, Lumerical seat or network is needed (AGT-007). Setting the matching `LAB_BRAIN_TEST_*` variable runs them; a milestone whose `gate_profile` names a backend cannot be signed off by a run that skipped it.

<!-- END GENERATED: test-inventory -->

### Local counts and generic CI counts differ by exactly two, and that is not a regression

The figures above are from a **local run with full history**. Two GitHub jobs report two fewer:

| Run | Backend-free | `postgres` profile | Spec conformance |
|---|---:|---:|---:|
| Local, full history | **1296**, 625 skipped | **1921**, 0 skipped | **205** |
| Generic CI jobs (`fetch-depth: 1`) | 1294, 627 skipped | 1919, 2 skipped | 203, 2 skipped |

This table is hand-maintained and had drifted once already: it carried 941 / 1391 from the slice
that wrote it while the generated inventory directly above said otherwise. The **delta** between
the two rows is the claim being made, it has always been exactly two, and the absolute numbers move
with every slice — so they are restated here rather than left to be read as current.

The two are `test_this_repositorys_enforced_history_is_clean` and
`test_the_enforcement_floor_is_a_real_commit_in_this_repository`, both marked `_needs_history` in
`tests/spec/test_commit_message_hygiene.py`. A shallow checkout does not contain the enforcement
floor, so the range cannot be walked; the tests skip rather than assert over zero commits.

The rule is still enforced. The dedicated **`Commit hygiene` job checks out at `fetch-depth: 0`**
and runs the gate over the whole enforced range — and `test_the_ci_job_checks_out_enough_history_to_walk_a_range`,
which never skips, fails if that job stops existing or its checkout is shallowed. So a run that
*always* has the history is what holds the rule, and the generic jobs decline to assert what they
cannot see. Making these two assert unconditionally would turn an honest skip into a green test
that checked no commits, which is worse because it is believed.

## Architecture Decisions

| ADR | Title | Status |
|---|---|---|
| ADR-0001 | PostgreSQL + JSONB + pgvector as the single v1 store | Accepted |
| ADR-0002 | Belief state is event-sourced, never updated in place | Accepted |
| ADR-0003 | Claim, Observation and Attestation are separate objects | Accepted |
| ADR-0004 | Retrieval policy switches on research intent | Accepted |
| ADR-0005 | Cost is a vector, never a single scalar | Accepted |
| ADR-0006 | `run_*` is backend-bound, `extract_*` is backend-agnostic | Accepted |
| ADR-0007 | Evidence authority is a domain-supplied partial order | Accepted |
| ADR-0008 | Typed predictions + side-effect-free hypothetical evaluation | Accepted |
| ADR-0009 | Two-tier error disclosure with an ACL-gated technical tier | Accepted |
| ADR-0010 | `Artifact` is global content identity; `ArtifactOccurrence` is project-scoped presence | Accepted |
| ADR-0011 | `EvidenceUnit` is canonical scientific identity; `RetrievalRepresentation` is a derived index artefact | Accepted |
| ADR-0012 | `EvidenceUnitOccurrence` is project-scoped presence; segmentation conformance is witnessed, then re-derived | Accepted |

ADRs 0001–0009 record decisions already fixed by SAI 3.3; ADR-0010, ADR-0011 and ADR-0012 record
ones made during implementation and ratified by amendments `v3.3-a8`, `v3.3-a17` and `v3.3-a18`;
they exist so the *reasoning* is available to whoever later wants to change one. 0002, 0003, 0007,
0008, 0009, 0010, 0011 and 0012 touch P0 scientific or security semantics and are marked as
requiring human approval, granted by the spec sections they cite.

0010, 0011 and 0012 are the same shape at three depths: one row conflating two different facts,
where the failure is not a missing check but an unanswerable question. 0010 separated *which bytes*
from *whose copy*; 0011 separates *what the evidence is* from *what the index returned*; 0012
applies 0010's split one layer down — global `EvidenceUnit` identity, project-scoped
`EvidenceUnitOccurrence` — rather than putting `project_id` into the scientific identity, which
would make one measurement cited by two projects count twice under `EVI-004`.

## Spec Coverage Audit

<!-- BEGIN GENERATED: coverage-audit -->

Generated by `scripts/update_status.py` from the same data `tests/spec/test_m0a_coverage_audit.py` and `tests/spec/test_m0a_obligation_inventory.py` recompute.

| | |
|---|---|
| Audit document | [`M0a.md`](docs/spec_coverage_audit/M0a.md) (rev 7) |
| Scope | §6–§16, all 77 numbered headings counted |
| Sections reconciled | 77 |
| Hard MUSTs | **80** = 78 registered live + 2 named deferred |
| Occurrences classified | **84** = 62 REGISTERED + 19 RESTATEMENT_OF + 3 NON_NORMATIVE_WITH_RATIONALE |
| Keyword-free statements declared | 18 |
| Unaccounted hard obligations | 0 (every delta is 0) |
| Requirement ↔ Test invariant | **60 ↔ 60** |

<!-- END GENERATED: coverage-audit -->

The §23.5 (2) gate audit **has been run** and every delta is 0. It is a human review gate, so the
figures above being green is a necessary condition for sign-off and not the sign-off itself.

Phase audits: `docs/spec_coverage_audit/` holds the P1, P1-fix, P1-fix2, P2 and P2-fix phase audits
alongside `M0a.md`. `M0a.md` was **rebuilt** at rev 6 rather than appended to: five rounds of
corrections had left superseded totals sitting beside current ones, so the document is now generated
from `M0a_hard_must_counts.yaml` and `M0a_obligation_inventory.yaml` in one pass.

### Spec issues (AGT-015)

All fifteen are **RESOLVED**. Five were raised by the M0a coverage audit and ruled on by the
maintainer in amendment `v3.3-a2`; the rest came from implementation slices that could not be
written honestly without a ruling — 009 from P5, 010/011 from P7–P9, 012 from the M0b sign-off
audit, 013 from M1-P1, and 014/015 from the M1-P1 audit repair.

| Issue | Severity | Blocks gate | Resolution |
|---|---|---|---|
| 001 | GATE | M0a | Reading B — `statement_key` unique, one Requirement ID per entry (`v3.3-a1`) |
| 002 | EDITORIAL | — | `GH-xxx` added to the §23.2 namespace table (`v3.3-a2`) |
| 003 | GATE | M0a | Option 1 — `SIM-003` / `T-SIM-003` added (`v3.3-a1`) |
| 004 | GATE | M7 | `HEU-001` / `T-HEU-001`, new `HEU-xxx` namespace (`v3.3-a2`) |
| 005 | GATE | M3 | `SRC-003` / `T-SRC-003` (`v3.3-a2`) |
| 006 | GATE | M4 | `VER-007` / `T-VER-007` (`v3.3-a2`) |
| 007 | GATE | M1 | `OPS-004` / `T-OPS-004`, fault-injection verified (`v3.3-a2`) |
| 008 | EDITORIAL | — | No new requirement; registered under `SEC-002`, DEFERRED with `review_at: FIRST_FABRICATION_CAPABILITY` (`v3.3-a2`) |
| 009 | GATE | M0b | `token_count` added to §9.4 `CostVector`; §17.19.1 states `NULL`/absent = uncapped, `0` = zero permitted (`v3.3-a10`) |
| 010 | GATE | M0b | §17.13 `BeliefRevisionEvent` gains `project_id` and `policy_id`; without them EPI-003 replay is unscoped and EPI-005 determinism has no anchor (`v3.3-a11`) |
| 011 | GATE | M0b | §17.14.1 `Decision` becomes the durable belief-transition authorization: re-derivable `decision_input_snapshot` + `input_hash`, fail closed (`v3.3-a12`; read side `v3.3-a13`) |
| 012 | GATE | M0b | Reading B — `GovernanceEvent(REVIEW_EXPIRY)`. A timeout is a governance act, not a belief transition, so a scheduler may not author a `BeliefRevisionEvent` (`v3.3-a15`; chain binding `v3.3-a16`) |
| 013 | GATE | M1 | Reading D — `EVI-010` / `T-EVI-010`. §6.7's segmentation SHOULD had no hard counterpart and no registry entry, and no requirement forbade a vector chunk being treated as the evidence body (`v3.3-a17`) |
| 014 | GATE | M1 | Reading C — §17.25.1 `EvidenceUnitOccurrence`. §17.25's identity is project-independent but its row was project-scoped, so the same document in a second project collided on the primary key and that project got no evidence at all (`v3.3-a18`, ADR-0012) |
| 015 | GATE | M1 | Two-layer split per `v3.3-a13` — a byte-level `segmentation_witness` in SQL, plus admission re-running the recorded segmenter. §6.22 rule 1 was enforced only when a unit declared its own bindings, so a raw writer skipped it by declaring nothing (`v3.3-a18`) |

The index table in `docs/spec_issues/README.md` reported 002 and 004–008 as OPEN for two days
after they were resolved, because it was prose beside machine-read headers. It is now compared
against those headers by `tests/spec/test_spec_issue_index.py`.

Requirement ↔ Test invariant history. The current value is generated above; this records how it
moved, because each step was a maintainer ruling rather than a count correction:

| Amendment | Invariant | What changed |
|---|---|---|
| baseline | 52 ↔ 52 | as first parsed from §25.3 / §26 |
| `v3.3-a1` | 53 ↔ 53 | `SIM-003` (SPEC-ISSUE-003, typed tools) |
| `v3.3-a2` | 57 ↔ 57 | `HEU-001`, `SRC-003`, `VER-007`, `OPS-004` (SPEC-ISSUE-004…007) |
| `v3.3-a3` | 57 ↔ 57 | §15.4 groupthink falsifiability registered; no new ID |
| `v3.3-a4` | 58 ↔ 58 | `VER-008` (§9.1's disagreement metric) |
| `v3.3-a5` | 58 ↔ 58 | occurrence inventory; four owners found among existing requirements |
| `v3.3-a6` | **59 ↔ 59** | `EVI-009` (§14.3 admission-time artifact reference) |
| `v3.3-a7` | 59 ↔ 59 | §7.6's second trigger folded into `SRC-002`; no new ID |
| `v3.3-a8` | 59 ↔ 59 | `Artifact` / `ArtifactOccurrence` contract split (ADR-0010); no new ID |
| `v3.3-a9` | 59 ↔ 59 | §17.17 `CostEntry` gains `project_id` / `cost_kind`; §17.17.1 `BudgetApproval` declared; no new ID |
| `v3.3-a10` | 59 ↔ 59 | §9.4 `CostVector` gains `token_count`; §17.19.1 states cap `NULL` vs `0` (SPEC-ISSUE-009); no new ID |
| `v3.3-a11` | 59 ↔ 59 | §17.13 `BeliefRevisionEvent` gains `project_id` / `policy_id` (SPEC-ISSUE-010); no new ID |
| `v3.3-a12` | 59 ↔ 59 | §17.14.1 `Decision` as durable belief-transition authorization (SPEC-ISSUE-011); no new ID |
| `v3.3-a13` | 59 ↔ 59 | the two forgery classes and where each is refused; clarification only, no new ID |
| `v3.3-a14` | 59 ↔ 59 | `subject_id` conflict resolved to §17.19.3; review resolution made durable; no new ID |
| `v3.3-a15` | 59 ↔ 59 | `GovernanceEvent(REVIEW_EXPIRY)` (SPEC-ISSUE-012); obligation read into OPS-002/EPI-006, no new ID |
| `v3.3-a16` | 59 ↔ 59 | a `GovernanceEvent` must belong to the chain it closes; clarification only, no new ID |
| `v3.3-a17` | **60 ↔ 60** | `EVI-010` (SPEC-ISSUE-013, §6.22 + §17.25: evidence-boundary segmentation, and a vector chunk is not evidence identity) |
| `v3.3-a18` | 60 ↔ 60 | §17.25.1 `EvidenceUnitOccurrence` and the `segmentation_witness` (SPEC-ISSUE-014, SPEC-ISSUE-015); both obligations `EVI-010` and `SEC-002` already imposed, so no new ID |

Amendments a12–a16 all kept the invariant because each made an **existing** obligation uniquely
executable rather than adding one. `v3.3-a17` is the first move since `v3.3-a6`, and it moved for
the same reason a6 did: the obligation had no owner that could take it without distortion.
`EVI-010` is deliberately separate from `EVI-007` — that governs which embedding space may be
compared, this governs whether a vector may be the evidence at all. An implementation can satisfy
every clause of `EVI-007` while failing `EVI-010`.

`VER-007` is deliberately separate from `VER-003`: that governs the *cost* of a verification
action, this the *quality* of a design. A multi-dimensional `CostVector` and a scalar-ranked design
space can coexist while `T-VER-003` passes.


## Known Risks / Technical Debt

1. **R-1 Lumerical seat (spec Risk Register, P1)** — no license seat in this environment.
   All Silicon Photonics `run_*` tools are exercised against mocks until a seat exists.
   TST-001 requires the same case to replay on a real project in a licensed environment;
   that half of TST-001 cannot be discharged here and is **open**. **Attempted 2026-09-27 and
   externally blocked** -- the probe of every prerequisite and the enabled licensed gate's failure
   are recorded in [`M4-readiness.md`](docs/implementation/M4-readiness.md) §11.

   **M2 made this concrete rather than closing it.** `lab_brain.tool_providers.lumerical` contains
   exactly one module — a deterministic mock that stamps `solver_id = mock.charge.ac`, never
   `CHARGE`. Two tests hold the line: `test_no_vendor_sdk_is_imported_anywhere_in_the_shipped_package`
   fails if any module in `src/` imports `lumapi` or a relative, and
   `test_the_mock_never_claims_to_be_a_vendor_solver` fails if the mock's identity stops announcing
   itself. What M2 proves is the **contract** — a backend driven from a §17.4 request, returning a
   §17.4 execution, declaring its validity schema and contending for a seat through §10.7. A real
   backend implements the same Protocol and changes nothing above it.
2. **R-2 Ground-truth benchmark (spec Risk Register, P1)** — no curated Rs-anomaly cases
   collected. M4's exit gate demands a *fixed, non-cherry-picked* benchmark set, so case
   collection is on the critical path and needs human scientific input (§23.4), not agent
   invention.
3. ~~**R-3 Open spec issues**~~ — **CLOSED 2026-09-13; reopened 2026-09-15 for SPEC-ISSUE-011 and
   closed by `v3.3-a12`; reopened again 2026-09-16 when the P8 audit found that amendment
   discharged on the write path only, and closed once the read-side gate landed.** All eleven spec issues are RESOLVED, in the spec text
   and the registry rather than only in their own status headers. No OPEN GATE issue names any
   milestone. The reopening is left visible rather than tidied away: it is the record of a gate
   issue being raised, ruled on by the maintainer, and discharged, which is the process working.
   The count moved from eight to eleven as SPEC-ISSUE-009 (P5, COST-001), SPEC-ISSUE-010 and
   SPEC-ISSUE-011 (both P7, EPI-003/EPI-005) were raised and ruled.
   `tests/spec/test_spec_issue_index.py` compares the index against the document headers, so this
   sentence can no longer disagree with the directory it describes.
4. **R-4 `markers.py` reimplements pytest's collection rules** — coverage counting depends on a
   static model of `python_files` / `python_functions` / `python_classes`. A pytest upgrade or a
   config change could make the model disagree with reality.
   Mitigation: `tests/spec/test_marker_collection.py` compares the model against real
   `--collect-only` output on every run, **in both directions**. The second direction was added
   2026-09-13 after it caught a live bug: the model read only decorator lists, so module-level
   `pytestmark` was honoured by pytest and invisible to the matrix — `SRC-002` had a passing,
   executed test and was reported as having none. Under-reporting, but still a false coverage
   statement, and the same blind spot would have hidden over-reporting.
   Residual risk: the node-ID half of the cross-check parses `-q` text output, which is not a
   stable API. The marker half now reads the outcome plugin's own report instead.
5. ~~**R-5 No PostgreSQL instance yet**~~ — **CLOSED 2026-09-12 (P2).** PostgreSQL 17 + pgvector
   is running; migrations 001–004/008 applied; 13 schema-constraint tests confirm the CHECK
   constraints and foreign keys actually reject rather than merely existing. CI gained a
   `backend` job with a PostgreSQL service, so `gate_profile: [postgres]` is satisfiable in CI
   rather than only on a developer machine — without it the last step of the ratchet would have
   fallen back to "the agent says it passed locally".
6. ~~**R-6 CI has not yet run against a remote push**~~ — **CLOSED 2026-09-12.** Run
   [34674213878](https://github.com/SpadesZ/laboratory-innovation-brain/actions/runs/34674213878)
   on `331de32`: both jobs `success`. `spec-conformance` reported 51 passed, status table
   current, spec tables 52 requirements / 52 tests; `quality` reported ruff, format, mypy strict
   and the full suite green. CI is now an executed gate, not an authored file.

7. **R-7 Cross-project identical bytes** — **MITIGATED, NOT CLOSED.** The representational half is
   done: `artifacts` no longer carries `project_id` or `sensitivity_label` (dropped, not nullable),
   migration `002a` moves both to `artifact_occurrences` keyed on `(artifact_id, project_id)`, and
   §17.1 / §17.1.1 / the Pydantic models / the DDL now agree — enforced by
   `tests/spec/test_schema_drift.py`, which compares all three on every run.
   `lab_brain.core.access.can_read_artifact` fails closed on seven paths, including `Actor.active`
   and `ProjectMembership.active` independently. 22 negative security tests plus 8 schema tests.
   **Why it stays open:** nothing calls the gate. There is no read path to guard until M1's
   ingestion and retrieval exist, so the leak is unrepresentable but the enforcement is
   unexercised in a live path. Closes when a caller exists and is tested end to end.
8. **R-8 `critique_gate` has no caller** — `lab_brain.core.critique_gate.evaluate_dispatch` makes
   §7.6's dispatch refusal executable and is exercised by `tests/contract/test_critique_gate.py`,
   but nothing dispatches actions yet. It is a policy with correct behaviour and no integration
   point until M3/M4, so the *rule* is proven and its *enforcement in a live path* is not.
9. **R-9 Reclassification history is not representable** — `artifact_occurrences` has primary key
   `(artifact_id, project_id)`, so there is exactly one classification per artifact per project and
   an `UPDATE` overwrites it silently. "What was this labelled at the moment it was sent" is the
   first question an NDA incident review asks, and this schema cannot answer it.
   An earlier draft of the `ArtifactOccurrence` docstring claimed reclassification was append-only;
   the schema could not support that, so the claim was removed rather than softened. Event-sourced
   classification belongs with `EPI-003`, which brings the event infrastructure it needs.
10. **R-10 The budget gate's caller dispatches only mock actions** — **NARROWED 2026-09-15 (P6),
    NOT CLOSED.** It was "the budget gate has no caller", the third instance of the shape R-7 and
    R-8 describe. `lab_brain.core.dispatch.dispatch_action` is now that caller, and it is the only
    one: it opens a span, asks `authorize_dispatch`, and **returns without invoking the action**
    when the budget refuses. That ordering is proven rather than asserted — the negative tests
    pass an action that raises if it is ever reached, so a gate that ran beside the call instead of
    before it fails them.
    **Why it stays open:** the actions are mocks. There is no LLM slot configured and no Lumerical
    seat (R-1), so what has been demonstrated is that the seam refuses before *a* side effect, not
    before a real one. The remaining gap is the same one R-1 describes, and it closes when M1
    brings a real ingestion/LLM path through this function.
    What is now genuinely closed: the gate has a caller; the caller records the trace and the cost
    refs either way; a refused dispatch writes nothing to the ledger and performs nothing; a
    failed action records no actual cost; the ledger is append-only and an approval is claimable
    exactly once, durably, across concurrent sessions.
11. **R-11 A span may name a Job or a Run that does not exist** — `execution_spans.job_id` and the
    RUN span's subject carry no foreign key, because Appendix A's `006_jobs_runs.sql` is not built
    (`OPS-001` is M1). An FK to a missing table is not a stricter schema, it is an unapplyable
    migration, so the references are recorded now and unvalidated. This is the reason **OPS-003
    stays IN_PROGRESS**: §26's pass condition names `run → artifact`, and the artifact is currently
    reached through span metadata rather than a checked reference. The trace contract, the seam,
    the status vocabulary and the cost refs are real and exercised end to end; the last link is
    not. Closes with `OPS-001`/M1, which brings Job and Run as entities.
12. **R-12 A belief event may name a hypothesis that does not exist** — the genesis half is now
    closed: `admit_hypothesis` is an explicit admission path requiring an admission policy, and
    `005c` enforces the pairing in SQL, so a dropped predecessor can no longer be recorded as a
    beginning. `target_id` still carries no foreign key, because `Hypothesis` is `EPI-001` in M3. — two halves of the same gap, both waiting on `EPI-001` (M3).
    `belief_revision_events.target_id` carries no foreign key because `Hypothesis` is not an
    entity yet; same reasoning as R-11's `job_id`, and an FK to a missing table is an unapplyable
    migration rather than a stricter schema.
    The second half is sharper. `record_transition` **cannot** create a target's first event, and
    that is correct rather than missing: a hypothesis with no events has no state, and a
    `TransitionPolicy` always declares a `from_state`, so every policy-authorised transition has a
    predecessor. The first state is assigned by §8's Hypothesis Admission Gate. Until that exists,
    a genesis event can only be appended directly to the store — which the e2e test does, with the
    reason stated. So there is exactly one un-gated way into the event log, and it is the one M3
    closes. Pinned by
    `test_the_gate_cannot_create_a_genesis_event_and_that_is_deliberate`, so relaxing the check to
    "make the first event work" fails loudly.
13. ~~**R-13 A stored belief event carries no durable proof a policy authorised it**~~ —
    **Closed 2026-09-15, REOPENED the same day by the P8 audit, closed again 2026-09-16.** The
    reopening is left visible because what it records is worth keeping: `v3.3-a12` was implemented
    on the write path only.
    **The gap.** `record_transition` re-derived an authorization before minting an event, but
    `replay` took a bare `BeliefRevisionEvent`. A Decision could therefore be *semantically*
    forged while staying perfectly well-formed — canonical snapshot, correct `input_hash`, correct
    project/subject/policy/from→to, `result` recorded as ALLOW — with a snapshot that actually
    evaluates to DENY or a NEED_* outcome. `005d` accepts that row and is right to: refusing it
    would mean running `TransitionPolicy.evaluate` inside PostgreSQL, i.e. a second copy of the
    evaluator, and §8.2.1 would stop being the single source of semantic truth. §17.14.1 already
    covered this — "the event MUST NOT be created" *and* "a stored event MUST NOT be accepted as
    authorized" — so the specification was not deficient and no spec text changed; only half of it
    had been built.
    **Now closed on both sides.** A production read seam runs stored event → DecisionStore → the
    exact `TransitionPolicy` version → AuthorityPolicy resolver → `rederive_decision` →
    `VerifiedBeliefRevision`, and `replay` accepts nothing else, so a DB-loaded event cannot reach
    a scientific projection. Nine fail-closed conditions, each with its own reason code. A named
    comparator that cannot be resolved is a refusal rather than a fallback to `None`, and stored
    comparison results are never consulted (§17.14.1, §10.5.1).
    **Residual, and it is a deployment property rather than a record gap.** When an
    `AuthorityPolicy` took part, re-derivation needs that DomainPack comparator present, because
    core must not import a DomainPack (§24.2). It is named by identity and version, so absence is
    detectable and the gate refuses instead of guessing. An authorization computed with no
    comparator re-derives from the record alone.

## Next Recommended Task

**M1-P1 is hard-locked** at `f8e5e9c02ee98ed2a7faa6f604347b84b88c773b` on independent M2 review
(2026-09-21). Reopen it only on a **reproducible violation** of a locked invariant produced by a
later slice — not for cleanup, and not for a refactor. The fourteen locked items and where each
lives are in [`M1-P1-readiness.md`](docs/implementation/M1-P1-readiness.md) §12.

**Recommended: `OPS-001` — Jobs and Runs**, as slice M1-P2. It is the only open M1 requirement that
unblocks more than one other: `EVI-009`'s Run half, `UX-004`'s Job-level retry half, `OPS-003`'s
`run → artifact` reference (**R-11**), `UX-002`'s retry path, `UX-001`'s state derivation and
`UX-007`'s queue depth all wait on Job and Run existing as entities. Appendix A already allocates
the migration slot (`006_jobs_runs.sql`), and three requirements that are `IN_PROGRESS` on half a
pass condition can only become whole through it.

It is also the natural owner of the largest retained limitation: **there is no production
write-side repository contract**. `IngestionPipeline` takes `commit_rows` as an injected callable
and the only implementations are in tests, so what is proven today is that the pipeline is
idempotent and the schema accepts its output — *not* that a production writer exists. A Job that
resumes an ingestion has to persist from production code, so the slice that needs the writer and
the slice that should build it are the same one. Building it now, with no caller, would repeat the
pattern R-7, R-8 and R-10 each record.

Full dependency ordering for the remaining twelve, the seams that already exist and are waiting for
a caller, and what `OPS-001` must not do to the lock:
[`M1-P1-handoff.md`](docs/implementation/M1-P1-handoff.md).

M1-P1 delivered the Research Memory ingestion/evidence foundation and nothing else. The
per-requirement readiness matrix, the benchmark numbers and the known limitations are in
[`M1-P1-readiness.md`](docs/implementation/M1-P1-readiness.md).

**What it found, and why it changed a requirement count.** Evidence-boundary-preserving
segmentation was stated once in the whole specification — at §6.7, as `不應`, a SHOULD — with no
registry entry and no Requirement ID. Nothing made a system that treats a vector chunk as the
evidence body fail CI, although §23.4 forbids an *agent* from building one. Raised as
`SPEC-ISSUE-013`, ruled on by the maintainer as Reading D, and resolved by `v3.3-a17`:
**`EVI-010` / `T-EVI-010`, 59 ↔ 59 → 60 ↔ 60**, the first move of that invariant since `v3.3-a6`.

**The benchmark's finding is worth reading before the next slice.** On the locked fixture the
prohibited fixed-token baseline scores **1.00 boundary completeness, 1.00 condition retention and
a higher precision@5** than the evidence-aware segmenter — while scoring **0.00 on table context,
figure context and locator recovery**. A corpus-level threshold over the usual retrieval metrics
would therefore have *selected the prohibited strategy*. That is the concrete form of the argument
`SPEC-ISSUE-013` escalated, and it is why §26's pass condition is per case. Anyone proposing to
simplify the retrieval seam should start there.

**Eight requirements have tests that pass; none is DONE.** M1 is IN_PROGRESS, which means the
executed-coverage ratchet is not yet enforcing it — the ratchet enforces a milestone only once it
is DONE. The eight are covered because their tests exist and execute, not because a gate holds
them.

When PASS is returned, the next slice is **`EVI-007`** (dense retrieval into the seam
`RetrievalRepresentation` already defines) or **`UX-001`** (the seven-state `IngestionItem`
projection over the `StageResult`s the pipeline already emits). Both plug into existing seams and
neither needs a new contract.
