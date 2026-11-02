# SAI 3.5 — Appendix K: Traceability matrix (requirement → component → test → gate → phase)

Version: `3.5.0-master-candidate.1`. Status: **CANDIDATE — NOT ACTIVE.** `READY_FOR_REAL_RESEARCH = false`.
Authority: normative. Every row is generated from, and checked against, the
[registry](normative-statements.yaml) by the [candidate checker](check_candidate.py). Supersedes the
`3.5.0-discovery-candidate.1` version of this file (kept in git history).

## 1. How to use this matrix

- **Owner component**: the component of [Appendix B](architecture-end-to-end.md) §2 that must
  implement the requirement and own its test.
- **Planned test**: `T-S35-<AREA>-NNN`, specified by the acceptance clause of the statement in
  [SAI 3.5](../SAI_3.5.md) §3. Planned tests are obligations, never evidence; none is implemented.
- **Gates**: the SAI 3.4 G gates and SAI 3.5 G-D levels whose evidence would show the requirement in
  operation. A gate here is never satisfied by the requirement's test alone.
- **Phase**: the [roadmap](roadmap.md) phase in which the requirement must be built.
- **Status**: complete, partial, proposed, blocked or untested, with evidence in
  [implementation status](implementation-status.md).
- Inherited SAI 3.3 and SAI 3.4 links are in [compatibility.md](compatibility.md) §4.

## 2. Matrix

| Requirement | Key | Owner component | Planned test | Gates | Phase | Status |
|---|---|---|---|---|---|---|
| S35-GOV-001 | `gov.precedence` | SpecMaintenance | T-S35-GOV-001 | G-D0 | P35-0 | complete |
| S35-GOV-002 | `gov.product_target` | SpecMaintenance | T-S35-GOV-002 | G-D1, G-D2, G-D3, G-D4 | P35-0 | complete |
| S35-GOV-003 | `gov.product_category` | CampaignOrchestrator | T-S35-GOV-003 | G9, G-D1 | P35-4 | proposed |
| S35-GOV-004 | `gov.claim_discipline` | SpecMaintenance | T-S35-GOV-004 | G-D0, G-D1, G-D2, G-D3, G-D4 | P35-0 | partial |
| S35-GOV-005 | `gov.not_active` | SpecMaintenance | T-S35-GOV-005 | G-D0 | P35-0 | complete |
| S35-LIFE-001 | `life.persisted_stages` | CampaignOrchestrator | T-S35-LIFE-001 | G8, G-D1 | P35-2 | partial |
| S35-LIFE-002 | `life.campaign_states` | CampaignOrchestrator | T-S35-LIFE-002 | G8, G-D1 | P35-2 | proposed |
| S35-LIFE-003 | `life.termination` | CampaignOrchestrator | T-S35-LIFE-003 | G8, G-D1 | P35-2 | partial |
| S35-PROB-001 | `prob.research_problem` | ProblemDiscovery | T-S35-PROB-001 | G-D1, G-D2 | P35-2 | proposed |
| S35-PROB-002 | `prob.valuation` | ProblemDiscovery | T-S35-PROB-002 | G-D1, G-D2 | P35-2 | proposed |
| S35-PROB-003 | `prob.anomaly_registry` | ProblemDiscovery | T-S35-PROB-003 | G-D1, G-D2, G-D3 | P35-2 | partial |
| S35-PROB-004 | `prob.contradictions_gaps` | ProblemDiscovery | T-S35-PROB-004 | G-D1, G-D2 | P35-2 | partial |
| S35-HYP-001 | `hyp.epistemic_stages` | DiscoveryLoop | T-S35-HYP-001 | G6, G-D1 | P35-2 | partial |
| S35-HYP-002 | `hyp.testable_mechanistic` | HypothesisBrain | T-S35-HYP-002 | G-D1, G-D2 | P35-2 | partial |
| S35-HYP-003 | `hyp.claim_states` | ValidationLoop | T-S35-HYP-003 | G6, G-D1 | P35-2 | proposed |
| S35-HYP-004 | `hyp.generation` | HypothesisBrain | T-S35-HYP-004 | G0, G-D1, G-D2 | P35-2 | partial |
| S35-MECH-001 | `mech.distinguishable_classes` | MechanismExplorer | T-S35-MECH-001 | G-D1, G-D2, G-D3 | P35-2 | partial |
| S35-MECH-002 | `mech.search_space_expansion` | MechanismExplorer | T-S35-MECH-002 | G-D1, G-D2 | P35-2 | partial |
| S35-REF-001 | `ref.triggers_and_kinds` | ResearchReframing | T-S35-REF-001 | G-D1, G-D2, G-D3 | P35-2 | partial |
| S35-REF-002 | `ref.failure_history` | ResearchReframing | T-S35-REF-002 | G-D1, G-D2, G-D3 | P35-2 | partial |
| S35-REF-003 | `ref.accounting` | ResearchReframing | T-S35-REF-003 | G-D1, G-D2, G-D3 | P35-2 | partial |
| S35-SEL-001 | `sel.discrimination_per_cost` | VerificationPlanner | T-S35-SEL-001 | G-D1, G-D2, G-D3 | P35-2 | partial |
| S35-SEL-002 | `sel.competing_explanations` | ValidationLoop | T-S35-SEL-002 | G6, G-D1, G-D2 | P35-2 | partial |
| S35-MOD-001 | `mod.from_scratch` | PhysicalModelBuilder | T-S35-MOD-001 | G1, G9 | P35-6 | proposed |
| S35-MOD-002 | `mod.typed_operations` | PhysicalModelBuilder | T-S35-MOD-002 | G1, G8 | P35-6 | proposed |
| S35-MOD-003 | `mod.qualification` | ModelQualification | T-S35-MOD-003 | G1, G3, G-D3 | P35-6 | proposed |
| S35-SIM-001 | `sim.licensed_internal` | SimulatorWorkers | T-S35-SIM-001 | G2, G8 | P35-7 | blocked |
| S35-SIM-002 | `sim.per_product_qualification` | ModelQualification | T-S35-SIM-002 | G2, G7-SITE, G8 | P35-7 | blocked |
| S35-SIM-003 | `sim.worker_contract` | SimulatorWorkers | T-S35-SIM-003 | G8 | P35-6 | proposed |
| S35-VAL-001 | `val.sweeps` | NumericalValidation | T-S35-VAL-001 | G2, G3 | P35-6 | proposed |
| S35-VAL-002 | `val.convergence` | NumericalValidation | T-S35-VAL-002 | G3, G-D3 | P35-7 | partial |
| S35-VAL-003 | `val.uncertainty` | NumericalValidation | T-S35-VAL-003 | G4, G5, G-D2, G-D3 | P35-2 | partial |
| S35-VAL-004 | `val.bounded_refinement` | PhysicalModelBuilder | T-S35-VAL-004 | G3, G6, G8 | P35-6 | proposed |
| S35-VAL-005 | `val.physical_validation` | PhysicalValidation | T-S35-VAL-005 | G4, G5, G-D4 | P35-8 | blocked |
| S35-LOOP-001 | `loop.propose_never_confirm` | DiscoveryLoop | T-S35-LOOP-001 | G6, G8, G-D1 | P35-2 | partial |
| S35-LOOP-002 | `loop.feedback` | ValidationLoop | T-S35-LOOP-002 | G-D1, G-D2, G-D3 | P35-2 | partial |
| S35-LOOP-003 | `loop.stop_insufficient` | ValidationLoop | T-S35-LOOP-003 | G-D1, G-D2, G-D3, G-D4 | P35-2 | partial |
| S35-CWG-001 | `cwg.exclusive_confirmation` | CausalWarrantGate | T-S35-CWG-001 | G6, G-D1, G-D2, G-D3, G-D4 | P35-2 | partial |
| S35-CWG-002 | `cwg.consequential_authorization` | CausalWarrantGate | T-S35-CWG-002 | G6, G-D2, G-D4 | P35-4 | partial |
| S35-REG-001 | `reg.prospective` | RegistrationRegistry | T-S35-REG-001 | G0, G6, G-D1 | P35-2 | partial |
| S35-REG-002 | `reg.envelope_registration` | RegistrationRegistry | T-S35-REG-002 | G8, G-D1 | P35-4 | proposed |
| S35-REG-003 | `reg.envelope_limits` | RegistrationRegistry | T-S35-REG-003 | G6, G-D1 | P35-4 | proposed |
| S35-REG-004 | `reg.no_retrospective_support` | ValidationLoop | T-S35-REG-004 | G0, G6, G-D1 | P35-2 | partial |
| S35-NOV-001 | `nov.prior_art_bound` | NoveltyAuditor | T-S35-NOV-001 | G-D2, G-D3, G-D4 | P35-2 | partial |
| S35-NOV-002 | `nov.classification` | NoveltyAuditor | T-S35-NOV-002 | G-D2, G-D3, G-D4 | P35-5 | proposed |
| S35-NOV-003 | `nov.literature` | NoveltyAuditor | T-S35-NOV-003 | G0, G-D2 | P35-5 | partial |
| S35-EVI-001 | `evi.proposals_not_evidence` | ValidationLoop | T-S35-EVI-001 | G6, G-D1 | P35-2 | partial |
| S35-EVI-002 | `evi.provenance` | GovernancePlane | T-S35-EVI-002 | G0, G6, G-D1 | P35-2 | partial |
| S35-EVI-003 | `evi.independence` | ValidationLoop | T-S35-EVI-003 | G4, G6, G-D2 | P35-2 | partial |
| S35-EVI-004 | `evi.contamination` | EvaluationPlane | T-S35-EVI-004 | G4, G-D1, G-D2 | P35-3 | partial |
| S35-RPT-001 | `rpt.bilingual_traceable` | ReportGenerator | T-S35-RPT-001 | G0, G9, G-D2 | P35-4 | partial |
| S35-RPT-002 | `rpt.reproducible_bundle` | ReportGenerator | T-S35-RPT-002 | G7-SITE, G9, G-D1 | P35-4 | partial |
| S35-RPT-003 | `rpt.terminology_language` | ReportGenerator | T-S35-RPT-003 | G0, G9 | P35-4 | proposed |
| S35-RPT-004 | `rpt.researcher_ux` | ResearcherWorkspace | T-S35-RPT-004 | G0, G9 | P35-4 | partial |
| S35-AUTO-001 | `auto.no_external_coding_agent` | DeploymentOperations | T-S35-AUTO-001 | G9, G-D3 | P35-4 | untested |
| S35-AUTO-002 | `auto.deployment_composition` | DeploymentOperations | T-S35-AUTO-002 | G8, G9 | P35-4 | untested |
| S35-AUTO-003 | `auto.out_of_envelope_stop` | CampaignOrchestrator | T-S35-AUTO-003 | G9 | P35-4 | proposed |
| S35-SEC-001 | `sec.autonomy_levels` | GovernancePlane | T-S35-SEC-001 | G8, G9 | P35-4 | proposed |
| S35-SEC-002 | `sec.owner_gates` | GovernancePlane | T-S35-SEC-002 | G8, G-D1, G-D3, G-D4 | P35-4 | partial |
| S35-SEC-003 | `sec.project_isolation` | GovernancePlane | T-S35-SEC-003 | G8, G-D1 | P35-2 | partial |
| S35-SEC-004 | `sec.identity` | GovernancePlane | T-S35-SEC-004 | G0, G8, G-D0 | P35-2 | partial |
| S35-SEC-005 | `sec.least_privilege` | GovernancePlane | T-S35-SEC-005 | G8 | P35-2 | proposed |
| S35-SEC-006 | `sec.owner_stop` | GovernancePlane | T-S35-SEC-006 | G8 | P35-4 | proposed |
| S35-COST-001 | `cost.realized_consumption` | CostGovernance | T-S35-COST-001 | G8, G-D1 | P35-2 | partial |
| S35-COST-002 | `cost.ceilings` | CostGovernance | T-S35-COST-002 | G8 | P35-4 | partial |
| S35-GD-001 | `gd.independence` | EvaluationPlane | T-S35-GD-001 | G-D0, G-D1, G-D2, G-D3, G-D4 | P35-3 | blocked |
| S35-GD-002 | `gd.levels` | EvaluationPlane | T-S35-GD-002 | G-D0, G-D1, G-D2, G-D3, G-D4 | P35-3 | blocked |
| S35-GD-003 | `gd.no_substitution` | EvaluationPlane | T-S35-GD-003 | G-D2, G-D3, G-D4 | P35-3 | proposed |
| S35-CMP-001 | `cmp.three_arms` | EvaluationPlane | T-S35-CMP-001 | G-D1, G-D2, G-D3, G-D4 | P35-3 | partial |
| S35-CMP-002 | `cmp.matching` | EvaluationPlane | T-S35-CMP-002 | G-D1, G-D2, G-D3, G-D4 | P35-3 | partial |
| S35-CMP-003 | `cmp.blinding` | EvaluationPlane | T-S35-CMP-003 | G-D1, G-D2, G-D3, G-D4 | P35-3 | proposed |
| S35-CMP-004 | `cmp.hidden_worlds` | EvaluationPlane | T-S35-CMP-004 | G-D0, G-D1, G-D2, G-D3, G-D4 | P35-3 | proposed |
| S35-CMP-005 | `cmp.metrics` | EvaluationPlane | T-S35-CMP-005 | G-D1, G-D2, G-D3, G-D4 | P35-3 | partial |
| S35-CMP-006 | `cmp.statistics` | EvaluationPlane | T-S35-CMP-006 | G-D0, G-D1, G-D2, G-D3, G-D4 | P35-3 | partial |
| S35-CMP-007 | `cmp.contamination` | EvaluationPlane | T-S35-CMP-007 | G-D0, G-D1, G-D2 | P35-3 | partial |
| S35-CMP-008 | `cmp.stopping` | EvaluationPlane | T-S35-CMP-008 | G-D1, G-D2, G-D3, G-D4 | P35-3 | partial |
| S35-CMP-009 | `cmp.zero_cost_first` | EvaluationPlane | T-S35-CMP-009 | G-D1, G-D2 | P35-3 | partial |

## 3. Coverage by capability

| Capability | Requirements | Statuses |
|---|---|---|
| CAP-01 | S35-PROB-001, S35-PROB-002, S35-PROB-003, S35-PROB-004 | partial 2, proposed 2 |
| CAP-02 | S35-HYP-002, S35-HYP-004, S35-MECH-001, S35-NOV-001, S35-NOV-002, S35-NOV-003 | partial 5, proposed 1 |
| CAP-03 | S35-MECH-001, S35-MECH-002 | partial 2 |
| CAP-04 | S35-REF-001, S35-REF-002, S35-REF-003 | partial 3 |
| CAP-05 | S35-SEL-001, S35-SEL-002, S35-LOOP-001 | partial 3 |
| CAP-06 | S35-MOD-001, S35-MOD-002, S35-MOD-003 | proposed 3 |
| CAP-07 | S35-SIM-001, S35-SIM-002, S35-SIM-003 | blocked 2, proposed 1 |
| CAP-08 | S35-VAL-001, S35-VAL-002, S35-VAL-003, S35-VAL-004, S35-VAL-005 | blocked 1, partial 2, proposed 2 |
| CAP-09 | S35-HYP-001, S35-HYP-003, S35-LOOP-001, S35-LOOP-002, S35-LOOP-003, S35-EVI-001, S35-CWG-001, S35-CWG-002, S35-REG-001, S35-REG-004 | partial 9, proposed 1 |
| CAP-10 | S35-RPT-001, S35-RPT-002, S35-RPT-003, S35-RPT-004, S35-VAL-003 | partial 4, proposed 1 |
| CAP-11 | S35-AUTO-001, S35-AUTO-002, S35-AUTO-003, S35-GOV-003, S35-LIFE-001, S35-LIFE-002, S35-LIFE-003 | partial 2, proposed 3, untested 2 |
| CAP-12 | S35-SEC-001, S35-SEC-002, S35-SEC-003, S35-SEC-004, S35-SEC-005, S35-SEC-006, S35-COST-001, S35-COST-002, S35-EVI-002, S35-EVI-003, S35-EVI-004, S35-REG-002, S35-REG-003 | partial 8, proposed 5 |

## 4. Coverage by gate

| Gate | Requirements whose evidence it would carry |
|---|---|
| G0 | S35-HYP-004, S35-REG-001, S35-REG-004, S35-NOV-003, S35-EVI-002, S35-RPT-001, S35-RPT-003, S35-RPT-004, S35-SEC-004 |
| G1 | S35-MOD-001, S35-MOD-002, S35-MOD-003 |
| G2 | S35-SIM-001, S35-SIM-002, S35-VAL-001 |
| G3 | S35-MOD-003, S35-VAL-001, S35-VAL-002, S35-VAL-004 |
| G4 | S35-VAL-003, S35-VAL-005, S35-EVI-003, S35-EVI-004 |
| G5 | S35-VAL-003, S35-VAL-005 |
| G6 | S35-HYP-001, S35-HYP-003, S35-SEL-002, S35-VAL-004, S35-LOOP-001, S35-CWG-001, S35-CWG-002, S35-REG-001, S35-REG-003, S35-REG-004, S35-EVI-001, S35-EVI-002, S35-EVI-003 |
| G7-SITE | S35-SIM-002, S35-RPT-002 |
| G7-WORKER | — |
| G8 | S35-LIFE-001, S35-LIFE-002, S35-LIFE-003, S35-MOD-002, S35-SIM-001, S35-SIM-002, S35-SIM-003, S35-VAL-004, S35-LOOP-001, S35-REG-002, S35-AUTO-002, S35-SEC-001, S35-SEC-002, S35-SEC-003, S35-SEC-004, S35-SEC-005, S35-SEC-006, S35-COST-001, S35-COST-002 |
| G9 | S35-GOV-003, S35-MOD-001, S35-RPT-001, S35-RPT-002, S35-RPT-003, S35-RPT-004, S35-AUTO-001, S35-AUTO-002, S35-AUTO-003, S35-SEC-001 |
| G-D0 | S35-GOV-001, S35-GOV-004, S35-GOV-005, S35-SEC-004, S35-GD-001, S35-GD-002, S35-CMP-004, S35-CMP-006, S35-CMP-007 |
| G-D1 | S35-GOV-002, S35-GOV-003, S35-GOV-004, S35-LIFE-001, S35-LIFE-002, S35-LIFE-003, S35-PROB-001, S35-PROB-002, S35-PROB-003, S35-PROB-004, S35-HYP-001, S35-HYP-002, S35-HYP-003, S35-HYP-004, S35-MECH-001, S35-MECH-002, S35-REF-001, S35-REF-002, S35-REF-003, S35-SEL-001, S35-SEL-002, S35-LOOP-001, S35-LOOP-002, S35-LOOP-003, S35-CWG-001, S35-REG-001, S35-REG-002, S35-REG-003, S35-REG-004, S35-EVI-001, S35-EVI-002, S35-EVI-004, S35-RPT-002, S35-SEC-002, S35-SEC-003, S35-COST-001, S35-GD-001, S35-GD-002, S35-CMP-001, S35-CMP-002, S35-CMP-003, S35-CMP-004, S35-CMP-005, S35-CMP-006, S35-CMP-007, S35-CMP-008, S35-CMP-009 |
| G-D2 | S35-GOV-002, S35-GOV-004, S35-PROB-001, S35-PROB-002, S35-PROB-003, S35-PROB-004, S35-HYP-002, S35-HYP-004, S35-MECH-001, S35-MECH-002, S35-REF-001, S35-REF-002, S35-REF-003, S35-SEL-001, S35-SEL-002, S35-VAL-003, S35-LOOP-002, S35-LOOP-003, S35-CWG-001, S35-CWG-002, S35-NOV-001, S35-NOV-002, S35-NOV-003, S35-EVI-003, S35-EVI-004, S35-RPT-001, S35-GD-001, S35-GD-002, S35-GD-003, S35-CMP-001, S35-CMP-002, S35-CMP-003, S35-CMP-004, S35-CMP-005, S35-CMP-006, S35-CMP-007, S35-CMP-008, S35-CMP-009 |
| G-D3 | S35-GOV-002, S35-GOV-004, S35-PROB-003, S35-MECH-001, S35-REF-001, S35-REF-002, S35-REF-003, S35-SEL-001, S35-MOD-003, S35-VAL-002, S35-VAL-003, S35-LOOP-002, S35-LOOP-003, S35-CWG-001, S35-NOV-001, S35-NOV-002, S35-AUTO-001, S35-SEC-002, S35-GD-001, S35-GD-002, S35-GD-003, S35-CMP-001, S35-CMP-002, S35-CMP-003, S35-CMP-004, S35-CMP-005, S35-CMP-006, S35-CMP-008 |
| G-D4 | S35-GOV-002, S35-GOV-004, S35-VAL-005, S35-LOOP-003, S35-CWG-001, S35-CWG-002, S35-NOV-001, S35-NOV-002, S35-SEC-002, S35-GD-001, S35-GD-002, S35-GD-003, S35-CMP-001, S35-CMP-002, S35-CMP-003, S35-CMP-004, S35-CMP-005, S35-CMP-006, S35-CMP-008 |

## 5. Namespaces

| Namespace | Meaning | Defined in |
|---|---|---|
| `S35-<AREA>-NNN` | SAI 3.5 requirements | [SAI 3.5](../SAI_3.5.md) §3; scheme in the [change register](change-register.md) §1 |
| `T-S35-<AREA>-NNN` | planned tests (obligations, not evidence) | the acceptance clause of each statement |
| `CAP-01`…`CAP-12` | the twelve final capabilities | [SAI 3.5](../SAI_3.5.md) §2.2 |
| `G-D0`…`G-D4` | discovery acceptance levels | [acceptance-gd.md](acceptance-gd.md) |
| `P35-0`…`P35-9` | SAI 3.5 roadmap phases | [roadmap.md](roadmap.md) |
| `OD-01`…`OD-16` | SAI 3.5 Owner decisions | [decisions-and-review.md](decisions-and-review.md) |
| `S35-ISSUE-NN` | SAI 3.5 spec issues | [open-spec-issues.md](open-spec-issues.md) |
| `D-001`…`D-046` | retired discovery-candidate requirements | [change register](change-register.md), [requirement audit](requirement-audit.md) |
| `D-01`…`D-08` | SAI 3.4 Owner decisions (unchanged) | [SAI 3.4 decisions](../sai34/decisions-and-review.md) |
| `ASM-001`…`ASM-018`, `G0`…`G9` | SAI 3.4 obligations and gates (unchanged) | [SAI 3.4 candidate](../SAI_3.4_Candidate.md) |
