# SAI 3.5 — Appendix A: End-to-end research lifecycle

Version: `3.5.0-master-candidate.1`. Status: **CANDIDATE — NOT ACTIVE.** `READY_FOR_REAL_RESEARCH = false`.
Authority: normative. Refines S35-LIFE-001, S35-LIFE-002 and S35-LIFE-003 of [SAI 3.5](../SAI_3.5.md)
and places every other requirement in the stage where it applies. Nothing here exists in the
product yet; see [implementation status](implementation-status.md).

## 1. Objects

| Object | Meaning | Relation to inherited records |
|---|---|---|
| Campaign | the unit of autonomous research on one ResearchProblem (or a declared family of problems) in one project, with budgets, a stopping policy and, optionally, a covering ResearchEnvelope | new aggregate; contains SAI 3.3 research episodes and never replaces the SAI 3.3 §12.1 episode state machine |
| Episode | a SAI 3.3 research episode | unchanged; the campaign never sets an episode state |
| Stage | one step of the table in §2, with an owner component, inputs, durable outputs and a checkpoint | stage labels are not episode or Job enums; a mapping to existing enums needs an ADR and a migration (as in the SAI 3.4 architecture §2) |
| Checkpoint | the last committed, hash-bound output of a stage | restart resumes from it; a side effect is never repeated (S35-LIFE-001) |

Every durable output is bound to `project_id`, `campaign_id`, `episode_id`, `trace_id`,
`content_hash`, `schema_ref` (with version) and `producer_ref` (component, version, service
identity). A state advance accepts only committed outputs whose hash matches.

## 2. Stages

The table is a chain of responsibility, not a script: the cheapest sufficient path is chosen
(SAI 3.3 P11, VER-001), and a stage is skipped only with a recorded reason (§4). Stages L07 to L15
repeat until a termination condition (§6) holds.

| Stage | Name | Owner | Inputs | Durable outputs | Failure and stop | Requirements |
|---|---|---|---|---|---|---|
| L01 | Intake | CampaignOrchestrator | Owner or member question, flagged anomaly, FeedbackRecord, detected contradiction or gap | ResearchCampaign in DRAFT | an actor without project access or clearance is refused, with no egress | S35-LIFE-001, S35-LIFE-002 |
| L02 | Problem discovery and valuation | ProblemDiscovery | canonical records, anomalies, Conflicts, feedback | ResearchProblem, ProblemValuation | a problem without origin, links or provenance is refused | S35-PROB-001, S35-PROB-002, S35-PROB-003, S35-PROB-004 |
| L03 | Scoping and authorization | CampaignOrchestrator, GovernancePlane | problem, covering ResearchEnvelope or human acceptance | SCOPED campaign with budgets, stopping policy and autonomy level | without envelope or acceptance the campaign stays DRAFT and may use the zero-cost tier only | S35-LIFE-003, S35-SEC-001, S35-SEC-002, S35-REG-002 |
| L04 | Literature and prior art | NoveltyAuditor | PUBLIC queries, authorized providers | pinned passages, PriorArtSearchRecord with coverage and limitations | non-PUBLIC query refused before egress; an unreachable provider is recorded as a limitation | S35-NOV-001, S35-NOV-003 |
| L05 | Idea generation (stage 1) | HypothesisBrain | canonical EvidenceBundle, catalog, anomalies, residuals, reframings | ExploratoryIdea with InferenceProvenance | a call without bundle hash is refused; zero-cost tier only | S35-HYP-001, S35-HYP-004 |
| L06 | Admission and class partition (stage 2) | HypothesisBrain submits; SAI 3.3 §8 admission gate; MechanismExplorer | ideas with mechanism and typed predictions | admitted Hypothesis, MechanismClassPartition for experiment set E | a missing field or unbound prediction is refused; a duplicate becomes an alias | S35-HYP-002, S35-MECH-001 |
| L07 | Competing explanations and selection | ValidationLoop, VerificationPlanner | live classes, admitted evidence, capabilities, CostVector | rival registrations, SelectionDecision | nothing affordable discriminates → stop (S35-LOOP-003) | S35-SEL-001, S35-SEL-002 |
| L08 | Prospective registration | RegistrationRegistry | SelectionDecision, ResearchEnvelope or signed authorization | immutable Registration bound to one Job | outside every bound → AWAITING_REGISTRATION_AUTHORIZATION | S35-REG-001, S35-REG-002, S35-REG-003 |
| L09 | Model construction (simulation only) | PhysicalModelBuilder, ModelQualification | PhysicalModelSpec, qualification record | typed operation plan, BuildManifest, readback | missing authoritative parameter → UNKNOWN and ReviewItem; unqualified family → exploratory only | S35-MOD-001, S35-MOD-002, S35-MOD-003 |
| L10 | Execution | SimulatorWorkers or another capability | Job, Registration, fencing token, budget reservation, authorization | Runs, raw artifacts, attempt records, realized consumption | no seat → AWAITING_RESOURCE; undeterminable outcome → UNKNOWN, reconciled before retry | S35-SIM-001, S35-SIM-002, S35-SIM-003, S35-COST-001 |
| L11 | Numerical validation | NumericalValidation | Runs, frozen protocol, sweep plan | sweep results, convergence records, per-source uncertainty | an unconverged observable is UNKNOWN or FAIL and cannot discriminate | S35-VAL-001, S35-VAL-002, S35-VAL-003, S35-VAL-004 |
| L12 | Physical validation (physical claims only) | PhysicalValidation | independent references with uncertainty, split manifest | validation reports | no independent reference → BLOCKED | S35-VAL-005 |
| L13 | Evidence admission and belief transition | ValidationLoop | Runs, Observations, Registrations | Attestations, RelationJudgments, BeliefRevisionEvents through TransitionPolicy | evidence failing the prospective rules is stored as CITES | S35-EVI-001, S35-EVI-003, S35-REG-004, S35-HYP-003 |
| L14 | Confirmation (stage 3) | CausalWarrantGate | warrants, signed review, confirmation rule | Causal Warrant Gate decisions | no warrant or no qualifying review → the claim stays in stage 2 | S35-CWG-001, S35-CWG-002 |
| L15 | Feedback and reframing | ValidationLoop, ProblemDiscovery, MechanismExplorer, ResearchReframing | validation outcomes, residuals, anomalies | FeedbackRecords with dispositions, Reframings, new problems or classes | reframing cap reached → STOP_INSUFFICIENT | S35-LOOP-002, S35-REF-001, S35-REF-002, S35-REF-003, S35-MECH-002 |
| L16 | Reporting | ReportGenerator | canonical records | bilingual report and machine-verifiable bundle | a parity failure refuses the export | S35-RPT-001, S35-RPT-002, S35-RPT-003, S35-RPT-004 |
| L17 | Termination | CampaignOrchestrator | campaign state, budgets, stop events | closed campaign with a conclusion summary or StopRecord | the campaign always terminates (§6) | S35-LIFE-003, S35-LOOP-003, S35-SEC-006 |

## 3. Campaign state machine

States: `DRAFT`, `SCOPED`, `RUNNING`, `AWAITING_REGISTRATION_AUTHORIZATION`, `AWAITING_RESOURCE`,
`AWAITING_HUMAN`, `AWAITING_JOB`, `REPORTING`, `CLOSED_CONCLUDED`,
`CLOSED_INSUFFICIENT_VALIDATION`, `CLOSED_STOPPED`. The closed states are terminal; follow-up work
is a new campaign that links back.

| State | Meaning |
|---|---|
| `DRAFT` | created; may use only the zero-cost tier |
| `SCOPED` | covered by an envelope or accepted by a human member; budgets and stopping policy frozen |
| `RUNNING` | stages L04–L15 in progress |
| `AWAITING_REGISTRATION_AUTHORIZATION` | a registration lies outside the envelope and waits for a signed human authorization |
| `AWAITING_RESOURCE` | a capability, seat or worker is unavailable |
| `AWAITING_HUMAN` | a ReviewItem is pending |
| `AWAITING_JOB` | a dispatched Job has not returned |
| `REPORTING` | the report and bundle are being produced |
| `CLOSED_CONCLUDED` | at least one validated outcome exists: a CONFIRMED claim, or a hypothesis CONTRADICTED or INCONCLUSIVE under a registered test |
| `CLOSED_INSUFFICIENT_VALIDATION` | no claim could be validated with the available independence, data, license, budget or authorization |
| `CLOSED_STOPPED` | stopped by budget, ceiling, Owner, safety or time |

| From | Event | To |
|---|---|---|
| `DRAFT` | an envelope covers the problem, or a human member accepts it | `SCOPED` |
| `DRAFT` | Owner stop, or abandonment | `CLOSED_STOPPED` |
| `SCOPED` | start | `RUNNING` |
| `RUNNING` | a registration falls outside every bound | `AWAITING_REGISTRATION_AUTHORIZATION` |
| `AWAITING_REGISTRATION_AUTHORIZATION` | signed authorization recorded, or authorization refused or expired (the test is then excluded from selection) | `RUNNING` |
| `RUNNING` | a capability, seat or worker is unavailable | `AWAITING_RESOURCE` |
| `AWAITING_RESOURCE` | the resource becomes available, or the wait times out (re-planning) | `RUNNING` |
| `RUNNING` | a ReviewItem is required | `AWAITING_HUMAN` |
| `AWAITING_HUMAN` | the ReviewItem is resolved or expires (expiry is never consent) | `RUNNING` |
| `RUNNING` | a Job is dispatched | `AWAITING_JOB` |
| `AWAITING_JOB` | the Job's result, failure or UNKNOWN outcome is committed | `RUNNING` |
| `RUNNING` | a termination condition of §6 holds | `REPORTING` |
| any state except `DRAFT` and the closed states | Owner stop, envelope revocation, or ceiling reached without an Owner authorization | `REPORTING` (stop reason recorded) |
| `REPORTING` | report issued and at least one validated outcome exists | `CLOSED_CONCLUDED` |
| `REPORTING` | report issued; insufficient validation | `CLOSED_INSUFFICIENT_VALIDATION` |
| `REPORTING` | report issued; a stop reason is recorded | `CLOSED_STOPPED` |

Every other (state, event) pair is refused and logged (S35-LIFE-002). The waiting states of a
campaign mirror, and do not replace, the `AWAITING_*` states of its episodes (SAI 3.3 §12.1).

## 4. Skipping a stage

A stage may be skipped only with a recorded reason from this list: the evidence already admitted is
sufficient for the decision (SAI 3.3 §9.1); the stage does not apply (L09 without simulation, L12
without a physical claim); the needed capability is outside the envelope and no authorization was
given (the skip is then reported as NOT_PERFORMED). A skipped simulation is listed as NOT_PERFORMED
in the report with its reason and what would be needed, as G0-P requires.

## 5. Checkpoints and restart

Each stage commits its outputs and its checkpoint in one unit of work (SAI 3.3 OPS-004). A restart
reads the last committed checkpoint and re-enters the next stage; Jobs keep their SAI 3.3 and
SAI 3.4 idempotency, lease and fencing rules (ASM-007), so a restarted campaign never repeats an
external side effect and never resurrects a cancelled Job. A partial output after cancellation is
kept for diagnosis and is never admitted as evidence.

## 6. Stopping policy

The stopping policy is versioned and frozen at L03. It names: every budget dimension of
S35-LIFE-003 with its ceiling; the maximum number of reframings per problem and per campaign
(OD-12); the stagnation rule (for example, no change in the surviving class set after a declared
number of selections); the maximum wall time; and the action on each condition. A campaign
terminates when one holds: a validated outcome answers the problem; a budget or ceiling is reached;
stagnation; no affordable discriminating experiment remains; the reframing cap is reached; the
Owner stops it or revokes its envelope; a safety or isolation incident. Exhaustion and stagnation
never produce a discovery claim.

## 7. Worked example (informative)

A ring-resonator test die shows a resonance drift larger than its declared noise. L01 creates a
campaign from the flagged anomaly. L02 records a ResearchProblem with origin `ANOMALY`, linking the
observation by hash, and values it: the answer decides whether the thermal-tuning design must
change, available experiments can discriminate, and the expected cost is small. The project's
envelope (AL2: zero-cost capabilities over existing records) covers it, so L03 scopes it. L04
searches PUBLIC literature and records its coverage. L05 proposes thermo-optic drift, static
free-carrier dispersion and a measurement-chain artifact (laser wavelength error). L06 admits all
three with typed predictions; under the available experiment set they form three classes. The
existing drift record cannot support any of them (it predates their registration, S35-REG-004).
L07 selects a bias-dependent resonance measurement at two temperatures, which separates the most
classes per unit cost. A measurement is a physical experiment, which no envelope covers, so L08
moves the campaign to `AWAITING_REGISTRATION_AUTHORIZATION`; a project member signs the
registration and the Owner gate for lab time is recorded. A technician performs the measurement;
its capture time is recorded (L10). At L13 the registered test contradicts free-carrier dispersion.
Thermo-optic drift and the laser artifact stay indistinguishable with the available experiments,
so L15 records a FeedbackRecord and a `CHANGE_OBSERVABLE` reframing that names a wavelength-reference
measurement able to split them. The campaign's lab-time ceiling is spent, so it ends
`CLOSED_CONCLUDED` (one hypothesis contradicted under a registered test), reports the surviving
class as unresolved and proposes the next measurement to a human. Nothing was confirmed; no claim
reached stage 3.
