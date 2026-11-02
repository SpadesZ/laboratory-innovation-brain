# SAI 3.5 — Appendix C: Scientific records, schemas, persistent state and state machines

Version: `3.5.0-master-candidate.1`. Status: **CANDIDATE — NOT ACTIVE.** `READY_FOR_REAL_RESEARCH = false`.
Authority: normative. Refines the record and state obligations of [SAI 3.5](../SAI_3.5.md) §3.
These are logical schemas: no table, migration or runtime model exists for any record introduced
here. Each needs its own ADR, migration and tests (SAI 3.3 AGT-004, AGT-005).

## 1. Rules for every record

1. **Append-only.** Records are inserted, never updated in place or deleted; a correction or
   withdrawal is a new record or event that references the original (SAI 3.3 P2). The database
   refuses UPDATE and DELETE for normal writers.
2. **Envelope fields.** Every record carries `record_id`, `project_id`, `campaign_id` (where it
   applies), `schema_ref` with version, `content_hash` (canonical JSON, the repository's JCS
   profile), `created_at` from the database clock (never a client value), `producer_ref`
   (component, version, service identity) and `trace_id`.
3. **Provenance.** Every record carries `inputs[]` by id and hash, `policy_refs[]` (versions in force)
   and, for model-produced content, `inference_provenance_id` (S35-EVI-002, SAI 3.3 LLM-001).
4. **Project scope.** Reads and writes are scoped by project membership and clearance; a record from
   another project is never referenced without a project occurrence (S35-SEC-003).
5. **No belief writes.** No record here writes a belief state. Belief moves only through
   BeliefRevisionEvents authorized by TransitionPolicy (SAI 3.3 EPI-005), and CONFIRMED only through
   the Causal Warrant Gate (S35-CWG-001).
6. **UNKNOWN is a value.** A field that cannot be established is `UNKNOWN` with a reason, never a
   guessed default (SAI 3.3 EVI-002, P14).

## 2. Records

| Record | Owner | Key fields (beyond §1) | Requirements |
|---|---|---|---|
| ResearchCampaign | CampaignOrchestrator | problem_ids[], envelope_id?, autonomy_level, budgets (tokens, compute_s, money, experiments, seat_time per product, wall_time, reframings), stopping_policy_ref, state, episode_ids[] | S35-LIFE-001–003 |
| CampaignStateEvent | CampaignOrchestrator | campaign_id, from_state, to_state, event, reason, actor_or_policy | S35-LIFE-002 |
| StageCheckpoint | CampaignOrchestrator | campaign_id, stage (L01–L17), outputs[] by hash, skipped (bool), skip_reason?, side_effect_refs[] | S35-LIFE-001 |
| ResearchProblem | ProblemDiscovery | origin (`ANOMALY`, `CONTRADICTION`, `KNOWLEDGE_GAP`, `FAILED_HYPOTHESIS`, `VALIDATION_RESIDUAL`, `LITERATURE_GAP`, `OWNER_QUESTION`), source_refs[] by id and hash, statement, scope, accepted_by? (human member), covering_envelope_id? | S35-PROB-001 |
| ProblemValuation | ProblemDiscovery | problem_id, policy_version, criteria{decision_relevance, discriminability, expected_cost, unexplained_weight, novelty_potential (with coverage ref)}, rationale per criterion, model_opinion_ref?, rank | S35-PROB-002 |
| Anomaly | ProblemDiscovery | observation_refs[], detection_rule_ref, conditions, state (§3.3) | S35-PROB-003 |
| AnomalyStateEvent | ProblemDiscovery, ValidationLoop, CausalWarrantGate | anomaly_id, from, to, trigger, evidence_refs[], actor_or_policy, cwg_decision_ref? (required for EXPLAINED) | S35-PROB-003 |
| ExploratoryIdea | HypothesisBrain | statement, candidate_mechanism, draft_predictions[], sources (catalog, literature, anomaly, residual, reframing), inference_provenance_id; stage = 1 | S35-HYP-001, S35-HYP-004 |
| Hypothesis | admission gate (SAI 3.3 §8.1, unchanged) | as SAI 3.3 §8.1 and §17.5; SAI 3.5 adds a reference to its MechanismClassPartition membership through the partition record, not a new field on the certificate | S35-HYP-002 |
| ExperimentSet | MechanismExplorer | version, experiments[] (capability, conditions, replicates, availability), cost_table_ref | S35-MECH-001 |
| MechanismClassPartition | MechanismExplorer | experiment_set_version, threshold, replicates, classes[] (member hypothesis ids), merged_pairs[] with reason (`UNDECIDABLE`, `INDISTINGUISHABLE`, `ALIAS`), never_considered[] | S35-MECH-001, S35-MECH-002 |
| SearchSpaceExpansion | MechanismExplorer | trigger, order step (measurement chain, regime variant, composition, extended class, new mechanism), added[], refused[] with reason, before and after class counts | S35-MECH-002 |
| SelectionDecision | VerificationPlanner | live_classes[], candidates[] with separation and CostVector, policy_version, chosen experiment, gate_required | S35-SEL-001 |
| RivalClosure | ValidationLoop | candidate_class, registered_rivals[], cannot_exclude[], indistinguishable[] | S35-SEL-002 |
| ResearchEnvelope | RegistrationRegistry | owner_decision_ref, authorizer enrolment and Ed25519 signature (scope `RESEARCH_ENVELOPE`), autonomy_level, bounds{problem scope, mechanism families, capabilities with declaration hashes, model routes, licensed products with seat-time ceilings, money and compute ceilings, max registrations, max reframings}, valid_from, valid_until | S35-REG-002, S35-SEC-001 |
| EnvelopeRevocation | GovernancePlane | envelope_id, effective_at, actor, reason | S35-SEC-006 |
| Registration | RegistrationRegistry | hypothesis_id, prediction_ids[], capability_ref with declaration hash, analysis_plan_hash, decision_rule, job_id (exactly one), authorization: either signed_authorization_ref (enrolled person, Ed25519) or envelope_id with the bound check result, reservation_ref | S35-REG-001, S35-REG-002 |
| SweepPlan | NumericalValidation | parameters, ranges, sampling, observables, stopping rule, budget, registration_id | S35-VAL-001 |
| ConvergenceRecord | NumericalValidation | observable, levels (≥ 3), residual and conservation checks, domain-size study, verdict (`PASS`, `UNKNOWN`, `FAIL`) | S35-VAL-002 |
| UncertaintyRecord | NumericalValidation | claim_ref, numerical, input_parameters, measurement_or_reference, model_form, extraction, mapping (each a value, a bound or `UNKNOWN`), combination_rule with independence assumption | S35-VAL-003 |
| FeedbackRecord | ValidationLoop | validation_outcome_ref, outcome_state, refutation_bases[], anomalies_changed[], failed_assumptions[], unqualified_or_unconverged[], residual_summary, disposition (consumer, action, time) | S35-LOOP-002 |
| Reframing | ResearchReframing | kind (§3.4), trigger_ref, failed_refs[] (hypotheses, anomalies, assumptions, observables, models, problems), what_changes, rationale, successor_refs[] | S35-REF-001–003 |
| NoveltyAssessment | NoveltyAuditor | finding_ref, prior_art_search_ids[], coverage classes, novelty class ([Appendix D](provenance-novelty-independence.md) §3), model training cutoffs, memorization-probe result, stage at assessment | S35-NOV-001, S35-NOV-002 |
| StopRecord | ValidationLoop, CampaignOrchestrator | outcome (`INSUFFICIENT_VALIDATION` or `STOPPED`), reason, what_was_tried[], realized cost, what_would_be_needed | S35-LOOP-003 |
| ClaimStateProjection | ValidationLoop | claim_ref, stage, state (§3.2), derived_from[] (canonical event ids); rebuildable, never authoritative | S35-HYP-001, S35-HYP-003 |
| ReportBundle | ReportGenerator | report hashes (zh-TW, en), canonical record ids and hashes per statement, environment manifest, policy versions, registrations, budgets and realized consumption | S35-RPT-001, S35-RPT-002 |

## 3. State machines

### 3.1 Epistemic stages

| Stage | Name | Entry condition | Allowed uses |
|---|---|---|---|
| `EXPLORATORY_IDEA` | exploratory idea (stage 1) | any proposal of the Discovery side not yet admitted | zero-cost tier only; never shown as a hypothesis or a finding |
| `TESTABLE_HYPOTHESIS` | testable hypothesis (stage 2) | admitted under SAI 3.3 §8 with typed predictions and assigned to a mechanism class | registration, testing, belief moves through TransitionPolicy; reported with its claim state |
| `EVIDENCE_SUPPORTED_CONCLUSION` | evidence-supported conclusion (stage 3) | CONFIRMED through the Causal Warrant Gate and still re-derivable | consequential use, subject to S35-CWG-002 and the Owner gates |

A stage-3 claim whose decision no longer re-derives falls back to stage 2 with its state recomputed
(SAI 3.3 `v3.3-a13`). The Discovery side never writes stage 3 (S35-HYP-001, S35-LOOP-001).

### 3.2 Claim states (projection)

| State | Stage | Meaning | Derived from |
|---|---|---|---|
| `PROPOSED` | 1 | an exploratory idea | ExploratoryIdea |
| `ADMITTED` | 2 | passed the SAI 3.3 §8 admission gate | admission |
| `REGISTERED` | 2 | a prospective test is registered and authorized | Registration |
| `UNDER_TEST` | 2 | the registered test is running | Job and Run |
| `SUPPORTED` | 2 | TransitionPolicy allowed SUPPORTED; not a conclusion | BeliefRevisionEvent |
| `CHALLENGED` | 2 | as SAI 3.3 §8.2 | BeliefRevisionEvent |
| `CONTRADICTED` | 2 | as SAI 3.3 §8.2; the hypothesis failed its test | BeliefRevisionEvent |
| `INCONCLUSIVE` | 2 | as SAI 3.3 §8.2 | BeliefRevisionEvent |
| `CONFIRMED` | 3 | confirmed through the Causal Warrant Gate | Causal Warrant Gate decision only |
| `INSUFFICIENT_VALIDATION` | 2 | the required validation cannot be done with the available independence, data, license, budget or authorization | StopRecord |
| `STOPPED` | 1 or 2 | the campaign stopped (budget, ceiling, Owner, safety, time) | StopRecord |
| `WITHDRAWN` | any | an input was retracted or found contaminated | source or contamination event |

`REFRAMED` is an annotation, not a state: a Reframing supersedes the line of work and the claim keeps
its last state. Mapping to SAI 3.3 §8.2: `PROPOSED` ↔ DRAFT; `ADMITTED`, `REGISTERED`, `UNDER_TEST`
↔ ADMITTED/ACTIVE; the four belief states are identical; `REFRAMED` ↔ EVOLVED/SUPERSEDED. The
projection never replaces §8.2 states (spec issue S35-ISSUE-04 records the mapping for review).

| From | Allowed to | Never allowed |
|---|---|---|
| `PROPOSED` | `ADMITTED`, `WITHDRAWN`, `STOPPED` | any belief state without admission |
| `ADMITTED` | `REGISTERED`, `INSUFFICIENT_VALIDATION`, `WITHDRAWN`, `STOPPED` | `SUPPORTED` or `CONFIRMED` without a registered test |
| `REGISTERED` | `UNDER_TEST`, `INSUFFICIENT_VALIDATION`, `STOPPED` | editing the registration in place |
| `UNDER_TEST` | `SUPPORTED`, `CHALLENGED`, `CONTRADICTED`, `INCONCLUSIVE` (TransitionPolicy only), `STOPPED` | `CONFIRMED` directly |
| `SUPPORTED` | `CONFIRMED` (Causal Warrant Gate only), `CHALLENGED`, `CONTRADICTED`, `REGISTERED` (a new test), `INSUFFICIENT_VALIDATION` | `CONFIRMED` by any other path |
| `CHALLENGED`, `INCONCLUSIVE` | `REGISTERED` (a new test), `CONTRADICTED`, `INSUFFICIENT_VALIDATION`, `STOPPED` | `SUPPORTED` from re-reading old evidence |
| `CONTRADICTED` | a further belief move only under TransitionPolicy on new prospective evidence; a successor starts at `PROPOSED` | `SUPPORTED` or `CONFIRMED` through reframing or reinterpretation |
| `CONFIRMED` | `CHALLENGED`, `CONTRADICTED` or `WITHDRAWN` when new evidence or re-derivation withdraws it | silent removal |
| `INSUFFICIENT_VALIDATION` | `REGISTERED`, only with new resources and a new registration | `SUPPORTED` or `CONFIRMED` directly |
| `STOPPED` | none in this campaign; a new campaign links back | resumption without a new authorization |
| `WITHDRAWN` | none | reinstatement without a new record |

### 3.3 Anomaly states

| State | Meaning | Entry condition |
|---|---|---|
| `UNEXPLAINED` | an admitted observation no live admitted hypothesis predicts within the noise model | detection rule, or a researcher flags it |
| `UNDER_INVESTIGATION` | at least one problem or hypothesis targets it | linked ResearchProblem |
| `ACCOMMODATED` | fitted by a hypothesis registered after it; accommodation is not explanation | fit by a hypothesis without a passed prospective test |
| `PROVISIONALLY_EXPLAINED` | an explaining hypothesis is SUPPORTED, not CONFIRMED | TransitionPolicy decision |
| `EXPLAINED` | the explaining hypothesis is CONFIRMED | Causal Warrant Gate decision only |
| `ATTRIBUTED_TO_NOISE` | a pre-registered replication did not reproduce it and the replicate fits a declared hypothesis | registered replication outcome |
| `ARTIFACT` | an independent check shows a measurement or numerical artifact | recorded validation |
| `UNRESOLVED_INSUFFICIENT` | the available experiments, independence or budget cannot resolve it | StopRecord with INSUFFICIENT_VALIDATION |
| `WITHDRAWN` | its source was retracted or found contaminated | source event |

Allowed transitions: `UNEXPLAINED` → `UNDER_INVESTIGATION`, `ACCOMMODATED`, `ATTRIBUTED_TO_NOISE`,
`ARTIFACT`, `UNRESOLVED_INSUFFICIENT`, `WITHDRAWN`; `UNDER_INVESTIGATION` → `ACCOMMODATED`,
`PROVISIONALLY_EXPLAINED`, `ATTRIBUTED_TO_NOISE`, `ARTIFACT`, `UNRESOLVED_INSUFFICIENT`,
`WITHDRAWN`; `ACCOMMODATED` → `PROVISIONALLY_EXPLAINED`, `UNDER_INVESTIGATION` (the accommodating
hypothesis failed), `WITHDRAWN`; `PROVISIONALLY_EXPLAINED` → `EXPLAINED`, `UNDER_INVESTIGATION`,
`WITHDRAWN`; `EXPLAINED` → `UNDER_INVESTIGATION` (the confirmation was withdrawn on re-derivation),
`WITHDRAWN`; `UNRESOLVED_INSUFFICIENT` → `UNDER_INVESTIGATION` (new resources and a new campaign).
`ATTRIBUTED_TO_NOISE`, `ARTIFACT` and `WITHDRAWN` are terminal except for a new contrary
registered result, which opens a new anomaly linked to the old one. No anomaly is ever deleted.

### 3.4 Reframing kinds

| Kind | Trigger | What changes |
|---|---|---|
| `QUESTION_ASSUMPTION` | an assumption of the live hypotheses is shown false or untested and decisive | the assumption becomes a hypothesis to test; dependent hypotheses are re-registered |
| `CHANGE_OBSERVABLE` | no available observable separates the surviving classes | a different observable or experiment that would split them is named (and gated if it needs a resource) |
| `CORRECT_MODEL` | a model family fails qualification or validation, or leaves systematic residuals under known physics | a model-form correction (novelty class MODEL_CORRECTION if it holds) with a new lineage |
| `QUESTION_MEASUREMENT_CHAIN` | anomalies or failures are consistent with an instrument or processing artifact | measurement-chain classes are registered and chain-check experiments preferred |
| `WIDEN_MECHANISM_SPACE` | every live class fails or a tested anomaly persists | S35-MECH-002 expansion in its recorded order |
| `NARROW_SCOPE` | the problem holds only in part of its conditions | the scope is narrowed; informational, no claim beyond the narrowed scope |
| `STOP_INSUFFICIENT` | the cap, budget or available experiments cannot continue | the campaign proceeds to a StopRecord |

### 3.5 Registration and envelope states

| Record | States | Rule |
|---|---|---|
| Registration | `REGISTERED` → `BOUND` (to its one Job) → `EXECUTED` or `VOID` (Job cancelled before any data) | never edited; a change is a new registration; the outcome always stays on record |
| ResearchEnvelope | `ACTIVE` → `EXPIRED` (at valid_until) or `REVOKED` (EnvelopeRevocation) | an envelope covers nothing once expired or revoked; checked at reservation and at dispatch |

### 3.6 Campaign states

Defined in [lifecycle.md](lifecycle.md) §3.

## 4. Persistence and migration rules

New records live in PostgreSQL (ADR-0001) with database rules for append-only behavior, project
scope and the permission matrix (S35-SEC-005). Each record type is introduced by its own migration
with schema version and forward and backward strategy, its ADR, contract tests and mutation-battery
entries. Existing canonical records are never back-filled with references they did not have; a
legacy record without a SAI 3.5 field reads as `UNKNOWN` or legacy, never as validated. The
offline prototype's frozen dataclasses on `118a4ac` are a reference for these schemas, not their
implementation.
