# SAI 3.5 — Requirement audit of D-001…D-046

Version: `3.5.0-master-candidate.4`. Status: **CANDIDATE — NOT ACTIVE.** `READY_FOR_REAL_RESEARCH = false`.
Authority: informative audit record. The normative successors are in [SAI 3.5](../SAI_3.5.md) §3
and the [registry](normative-statements.yaml); the mapping is the [change register](change-register.md).

## 0. How to read this audit

Each of the 46 requirements of `3.5.0-discovery-candidate.1` (the superseded
[discovery candidate](../SAI_3.5_Discovery_Candidate.md)) is audited individually against what an
external implementation agent with no conversation history would need. Fields:

- **Meaning and scope**: what the old statement obliged, precisely.
- **Dependencies and owner**: what it relies on, and the architectural owner of its successor(s).
- **I/O, schemas, states, trust boundaries**: as far as the old text defined them.
- **Behavior**: expected behavior, failure behavior and stop conditions.
- **Phase and prerequisites**: the [roadmap](roadmap.md) phase of the successor(s).
- **Acceptance**: the old planned test and pass condition, and the successor's test and kind.
- **Inherited**: the SAI 3.3 and SAI 3.4 obligations it relates to (unchanged by SAI 3.5).
- **Status**: implementation status of the successor(s) (complete, partial, proposed, blocked,
  untested; see [implementation status](implementation-status.md)). Every old statement was
  `SPECIFIED` with `tests: []`.
- **Ambiguity verdict**: CLEAR (an external agent can build and test it as written), AMBIGUOUS
  (it can be read in more than one testable way, or misses a needed element), INCOMPLETE (it covers
  only part of what is required).
- **Action**: kept, refined, split, merged, replaced or removed, with the reason.

Summary: kept 19, refined 19, split 5, merged 2, replaced 1, removed 0.
Verdicts: AMBIGUOUS 22, CLEAR 23, INCOMPLETE 1.

### D-001 — `candidate.additive`

Action: **refined** → S35-GOV-001

| Field | Audit |
|---|---|
| Meaning and scope | Spec-level rule: SAI 3.5 only adds; it may not weaken, replace, reinterpret or reorder any SAI 3.3/3.4 MUST, G0–G9 condition, HARD-LOCK or Owner gate; a conflict is a spec issue that stops the slice. |
| Dependencies and owner | Depends on SAI 3.3 §0.6 and AGT-015; SAI 3.4 §1; the candidate checker. Owner of the successor(s): SpecMaintenance. |
| I/O, schemas, states, trust boundaries | Inputs: SAI 3.3/3.4 files at a38ad63. Output: none at runtime; spec issues on conflict. Trust boundary: specification maintainers versus implementers. |
| Behavior | Expected: protected files byte-identical. Failure: a protected byte changes or a conflict is resolved by preference. Stop: the affected slice stops (AGT-015). |
| Phase and prerequisites | Old phase D0; successor phase P35-0; gates G-D0 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-001 — "SAI 3.3 and SAI 3.4 files, registries, milestones and ACTIVE_SPEC.yaml stay byte-identical to the base; a later conflict opens a spec issue and stops the affected slice." New: T-S35-GOV-001 (deterministic). |
| Inherited | SAI 3.4: ASM-018; SAI 3.3: TST-002, TST-003. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-GOV-001 complete. |
| Ambiguity verdict | **AMBIGUOUS** — 'Additive' did not say which text wins before activation, where a spec issue is recorded, or how 'additive' was tested; the branch itself broke it (9d44198 edited SAI 3.4 files while the candidate claimed none were edited). |
| Action and reason | refined: States precedence (inherited text wins until activation), the spec-issue register and a byte-identity acceptance test with no exception. |

### D-002 — `vision.target`

Action: **replaced** → S35-GOV-002

| Field | Audit |
|---|---|
| Meaning and scope | Product target: an autonomous AI scientist with four capabilities (discover problems, novel falsifiable hypotheses, reframing, independent validation), each with an operational meaning. |
| Dependencies and owner | Depends on SAI 3.4 ASM-001/002 (product target). Owner of the successor(s): SpecMaintenance. |
| I/O, schemas, states, trust boundaries | No runtime I/O; it defines the target that other requirements make operational. |
| Behavior | Expected: the four capabilities are described as targets. Failure: a capability is described as present. Stop: not applicable. |
| Phase and prerequisites | Old phase D0; successor phase P35-0; gates G-D1, G-D2, G-D3, G-D4 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-002 — "Each of the four capabilities has an operational definition tied to records and to the G-D level that would evidence it; none is described as present." New: T-S35-GOV-002 (deterministic). |
| Inherited | SAI 3.4: ASM-001, ASM-002; SAI 3.3: SYS-001. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-GOV-002 complete. |
| Ambiguity verdict | **INCOMPLETE** — Four capabilities do not cover the required twelve (model construction, licensed execution, validation chain, reports, production autonomy, governance were only implicit), and 'operational meaning' pointed to sections, not testable requirements. |
| Action and reason | replaced: Replaced by the twelve-capability target CAP-01..CAP-12, each mapped to requirements and gates. |

### D-003 — `vision.claim_discipline`

Action: **refined** → S35-GOV-004

| Field | Audit |
|---|---|
| Meaning and scope | Claim discipline: no artifact may claim discovery capability beyond the highest independently passed G-D level; engineering results are reported as engineering validity. |
| Dependencies and owner | Depends on SAI 3.4 ASM-018; G-D verdicts. Owner of the successor(s): SpecMaintenance. |
| I/O, schemas, states, trust boundaries | Inputs: documents, UI strings, reports, status files. Output: a claim audit. Trust boundary: implementer reports versus independent verdicts. |
| Behavior | Expected: every capability statement is backed by evidence. Failure: an unsupported claim. Stop: the document or release is blocked until corrected. |
| Phase and prerequisites | Old phase D0; successor phase P35-0; gates G-D0, G-D1, G-D2, G-D3, G-D4 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-003 — "A claim audit of documents, UI strings, reports and status files finds no capability claim above the highest independently passed G-D level, and engineering results are labeled as engineering validity." New: T-S35-GOV-004 (deterministic). |
| Inherited | SAI 3.4: ASM-018; SAI 3.3: UX-006. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-GOV-004 partial. |
| Ambiguity verdict | **AMBIGUOUS** — Covered only discovery capability, not every capability, and did not say that synthetic benchmark success is never real discovery validation; no claim-audit procedure was named. |
| Action and reason | refined: Extends the rule to every capability claim, names evidence paths at commits, and adds the synthetic-benchmark rule. |

### D-004 — `vision.novelty_falsifiability`

Action: **split** → S35-HYP-002, S35-NOV-001

| Field | Audit |
|---|---|
| Meaning and scope | A hypothesis is 'novel' only with a PriorArtSearchRecord with coverage; 'falsifiable' only with a typed CONTRADICTS prediction over a measurable observable in a frozen outcome space. |
| Dependencies and owner | Depends on SAI 3.3 SRC-003, VER-004, VER-006. Owner of the successor(s): HypothesisBrain, NoveltyAuditor. |
| I/O, schemas, states, trust boundaries | Inputs: PriorArtSearchRecord (SAI 3.3 §17.20), typed Prediction (§17.5.1). Output: novelty status and admission decision. |
| Behavior | Expected: novelty without coverage refused; non-falsifiable hypothesis not admitted. Failure: unbounded novelty claim. Stop: refusal at admission or at report time. |
| Phase and prerequisites | Old phase D2; successor phase P35-2; gates G-D1, G-D2, G-D3, G-D4 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-004 — "A novelty status without a PriorArtSearchRecord with coverage is refused; a hypothesis without a CONTRADICTS prediction over a measurable observable in a frozen outcome space is not called falsifiable." New: T-S35-HYP-002 (deterministic); T-S35-NOV-001 (deterministic). |
| Inherited | SAI 3.4: ASM-003; SAI 3.3: SRC-003, VER-004, VER-006. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-HYP-002 partial; S35-NOV-001 partial. |
| Ambiguity verdict | **AMBIGUOUS** — Mixed two independent obligations owned by different components (Novelty Auditor, admission) with different tests, and had no notion of novelty classes (rediscovery, optimization, model correction, new knowledge). |
| Action and reason | split: Falsifiability and mechanistic admission go to S35-HYP-002; prior-art bounding goes to S35-NOV-001; novelty classes are new in S35-NOV-002. |

### D-005 — `e2e.chain`

Action: **refined** → S35-LIFE-001

| Field | Audit |
|---|---|
| Meaning and scope | Every campaign persists versioned inputs, outputs, governance decisions and restartable checkpoints per stage, bound to project, episode, trace, hash, schema and producer; skipped stages record why. |
| Dependencies and owner | Depends on SAI 3.4 ASM-002, ASM-007, ASM-017; SAI 3.3 OPS-001/003/004. Owner of the successor(s): CampaignOrchestrator. |
| I/O, schemas, states, trust boundaries | Inputs: stage inputs. Outputs: stage outputs and checkpoints. Schemas: undefined in the old candidate. Trust boundary: orchestrator versus stage components. |
| Behavior | Expected: restart resumes without repeating side effects. Failure: missing binding fields. Stop: refuse unbound outputs. |
| Phase and prerequisites | Old phase D2; successor phase P35-2; gates G8, G-D1 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-005 — "Every stage of a campaign persists scoped, hashed, versioned inputs, outputs and decisions with restartable checkpoints; a skipped stage records its reason." New: T-S35-LIFE-001 (deterministic). |
| Inherited | SAI 3.4: ASM-002, ASM-017; SAI 3.3: SYS-001, OPS-001, OPS-003. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-LIFE-001 partial. |
| Ambiguity verdict | **AMBIGUOUS** — 'Campaign' and 'stage' were not defined as records or states, and restart semantics were implicit. |
| Action and reason | refined: Binds to the lifecycle appendix stage list, adds campaign binding and a fault-injection acceptance test; campaign states are new (S35-LIFE-002). |

### D-006 — `autonomy.no_external_coding_agent`

Action: **split** → S35-AUTO-001, S35-AUTO-002

| Field | Audit |
|---|---|
| Meaning and scope | Production research must not depend on Codex, Claude Code or any other external coding agent; acceptance check T-D-006 in a deployment-equivalent environment. |
| Dependencies and owner | Depends on SAI 3.4 ASM-001 and G9. Owner of the successor(s): DeploymentOperations. |
| I/O, schemas, states, trust boundaries | Inputs: a deployment-equivalent environment, in-envelope cases. Outputs: process, network and repository audit logs. Trust boundary: development plane versus production (TB-6). |
| Behavior | Expected: zero coding-agent invocations. Failure: any invocation or attempt not refused. Stop: release blocked. |
| Phase and prerequisites | Old phase D4; successor phase P35-4; gates G8, G9, G-D3 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-006 — "In a deployment-equivalent environment with coding-agent binaries absent and their endpoints blocked, the full chain runs from a blank workspace to a bilingual report on an in-envelope case; audit logs show zero coding-agent invocations, refused attempts are logged and every human intervention is a ReviewItem." New: T-S35-AUTO-001 (empirical acceptance check); T-S35-AUTO-002 (deterministic). |
| Inherited | SAI 3.4: ASM-001; SAI 3.3: SIM-003. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-AUTO-001 untested; S35-AUTO-002 untested. |
| Ambiguity verdict | **AMBIGUOUS** — Combined a runtime behavior (no stage depends on an agent) with a deployment-content property (no binaries, credentials, routes) that need different, separately repeatable tests; behavior out of envelope was not stated. |
| Action and reason | split: Runtime independence with its acceptance check (S35-AUTO-001) and static deployment composition audit (S35-AUTO-002); safe out-of-envelope stop is new (S35-AUTO-003). |

### D-007 — `e2e.literature`

Action: **kept** → S35-NOV-003

| Field | Audit |
|---|---|
| Meaning and scope | Autonomous literature search only through authorized ExternalSourceAdapter providers, PUBLIC-only egress, pinned passages with license class, separate rights, and a record of what was actually searched. |
| Dependencies and owner | Depends on SAI 3.3 SRC-001/002, SEC-001/004; SAI 3.4 ASM-003. Owner of the successor(s): NoveltyAuditor. |
| I/O, schemas, states, trust boundaries | Inputs: PUBLIC query, provider. Outputs: pinned passages, search record with limitations. Trust boundary: TB-2 (product versus providers). |
| Behavior | Expected: non-PUBLIC queries refused before egress. Failure: an unpinned or unlicensed passage. Stop: refuse the passage or query. |
| Phase and prerequisites | Old phase D3; successor phase P35-5; gates G0, G-D2 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-007 — "Non-PUBLIC queries never leave the deployment; every passage is pinned with version, hash and license class; unreachable providers appear in the search record's limitations." New: T-S35-NOV-003 (deterministic). |
| Inherited | SAI 3.4: ASM-003; SAI 3.3: SRC-001, SRC-002, SEC-001, SEC-004. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-NOV-003 partial. |
| Ambiguity verdict | **CLEAR** — Testable as written. |
| Action and reason | kept: Meaning unchanged; moved to the novelty and prior-art area under a new ID. |

### D-008 — `e2e.model_from_scratch`

Action: **split** → S35-MOD-001, S35-MOD-002

| Field | Audit |
|---|---|
| Meaning and scope | Physical models are constructed from scratch from a unit-checked PhysicalModelSpec through a closed set of typed operations; no generated code, no hidden prebuilt project, no solver defaults for unknowns. |
| Dependencies and owner | Depends on SAI 3.4 ASM-004, ASM-005, ASM-015. Owner of the successor(s): PhysicalModelBuilder. |
| I/O, schemas, states, trust boundaries | Inputs: PhysicalModelSpec (ASM-004). Outputs: typed operation plan, BuildManifest, readback. Trust boundary: TB-3. |
| Behavior | Expected: readback matches the spec. Failure: missing parameter filled silently. Stop: UNKNOWN blocks construction or creates a ReviewItem. |
| Phase and prerequisites | Old phase D4; successor phase P35-6; gates G1, G8, G9 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-008 — "A new project is built from a typed PhysicalModelSpec in a blank workspace through typed operations only, with independent readback; unknown parameters block instead of defaulting." New: T-S35-MOD-001 (deterministic, then licensed); T-S35-MOD-002 (deterministic). |
| Inherited | SAI 3.4: ASM-004, ASM-005; SAI 3.3: SIM-003, EVI-002. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-MOD-001 proposed; S35-MOD-002 proposed. |
| Ambiguity verdict | **AMBIGUOUS** — Two obligations with different tests: from-scratch construction (workspace inventory, readback) and the closed operation catalog (static analysis, catalog versioning). |
| Action and reason | split: From-scratch construction (S35-MOD-001) and the governed typed operation catalog (S35-MOD-002); model qualification is new (S35-MOD-003). |

### D-009 — `e2e.licensed_internal_workers`

Action: **split** → S35-SIM-001, S35-SIM-002

| Field | Audit |
|---|---|
| Meaning and scope | Licensed CHARGE, MODE, FDTD and INTERCONNECT run only on internal qualified workers, license-governed, Owner-authorized and cost-governed; mocks never substitute; each product qualified separately. |
| Dependencies and owner | Depends on SAI 3.4 ASM-006, ASM-007, ASM-015; SAI 3.3 TST-001; license and SAI 3.4 D-04. Owner of the successor(s): ModelQualification, SimulatorWorkers. |
| I/O, schemas, states, trust boundaries | Inputs: Job, authorization, budget reservation, qualified worker. Outputs: attempt records with checkout and release. Trust boundary: TB-3 (license boundary). |
| Behavior | Expected: refusal before any side effect without authorization, budget or qualification. Failure: mock used as licensed. Stop: BLOCKED or WAITING_RESOURCE. |
| Phase and prerequisites | Old phase D4; successor phase P35-7; gates G2, G7-SITE, G8 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-009 — "Each licensed run records real entitlement checkout, solver identity, Owner authorization and reconciled cost on a qualified internal worker; a missing license or authorization blocks and never returns a mock success." New: T-S35-SIM-001 (deterministic offline, then licensed); T-S35-SIM-002 (deterministic and licensed). |
| Inherited | SAI 3.4: ASM-006, ASM-007, ASM-015; SAI 3.3: TST-001, COST-001, OPS-001, SIM-001. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-SIM-001 blocked; S35-SIM-002 blocked. |
| Ambiguity verdict | **AMBIGUOUS** — Execution governance and per-product qualification were in one statement; the worker execution contract (fencing, registration binding) was missing. |
| Action and reason | split: Governed licensed execution (S35-SIM-001) and per-product, per-worker qualification (S35-SIM-002); worker contract is new (S35-SIM-003). |

### D-010 — `e2e.sweeps`

Action: **kept** → S35-VAL-001

| Field | Audit |
|---|---|
| Meaning and scope | Sweeps are pre-registered (parameters, ranges, sampling, observables, stopping rule, budget); each point is its own Run; outputs are model outputs, never measurements. |
| Dependencies and owner | Depends on SAI 3.3 EVI-009, SIM-001; SAI 3.4 ASM-012. Owner of the successor(s): NumericalValidation. |
| I/O, schemas, states, trust boundaries | Inputs: sweep plan. Outputs: one Run per point. Trust boundary: none new. |
| Behavior | Expected: refusal of unregistered sweeps. Failure: sweep output presented as measurement. Stop: refusal. |
| Phase and prerequisites | Old phase D4; successor phase P35-6; gates G2, G3 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-010 — "A sweep without a frozen plan is refused; every point is a Run with lineage to spec and plan; sweep outputs are admitted only as simulated, never as measured." New: T-S35-VAL-001 (deterministic). |
| Inherited | SAI 3.4: ASM-002, ASM-012; SAI 3.3: EVI-009, SIM-001. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-VAL-001 proposed. |
| Ambiguity verdict | **CLEAR** — Testable as written. |
| Action and reason | kept: Meaning unchanged; new ID. |

### D-011 — `e2e.convergence`

Action: **kept** → S35-VAL-002

| Field | Audit |
|---|---|
| Meaning and scope | A simulated observable may discriminate only after the ASM-008 convergence study passed for it; non-asymptotic or multi-branch results cannot discriminate. |
| Dependencies and owner | Depends on SAI 3.4 ASM-008; SAI 3.3 SIM-002. Owner of the successor(s): NumericalValidation. |
| I/O, schemas, states, trust boundaries | Inputs: Runs at three or more levels, frozen checks. Output: convergence record per observable. |
| Behavior | Expected: discrimination steps cite a passed convergence record. Failure: discrimination on an unconverged observable. Stop: UNKNOWN or FAIL. |
| Phase and prerequisites | Old phase D4; successor phase P35-7; gates G3, G-D3 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-011 — "A simulated observable without a passed ASM-008 convergence study cannot change the mechanism class partition or any belief state; non-asymptotic cases are UNKNOWN or FAIL." New: T-S35-VAL-002 (deterministic offline, then licensed). |
| Inherited | SAI 3.4: ASM-008; SAI 3.3: SIM-002. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-VAL-002 partial. |
| Ambiguity verdict | **CLEAR** — Testable as written. |
| Action and reason | kept: Meaning unchanged; new ID. |

### D-012 — `e2e.refinement`

Action: **kept** → S35-VAL-004

| Field | Audit |
|---|---|
| Meaning and scope | Refinement stays within ASM-011 bounds and produces immutable children; a mechanism change is a new hypothesis. |
| Dependencies and owner | Depends on SAI 3.4 ASM-011. Owner of the successor(s): PhysicalModelBuilder. |
| I/O, schemas, states, trust boundaries | Inputs: ModelPatch, RefinementPlan. Outputs: child spec versions with lineage. |
| Behavior | Expected: out-of-bounds patches refused before side effects. Failure: hypothesis drift to improve fit. Stop: ReviewItem. |
| Phase and prerequisites | Old phase D4; successor phase P35-6; gates G3, G6, G8 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-012 — "Refinement produces immutable child versions within approved bounds; a mechanism change creates a new hypothesis lineage with admission and pre-registration." New: T-S35-VAL-004 (deterministic). |
| Inherited | SAI 3.4: ASM-011; SAI 3.3: EPI-005. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-VAL-004 proposed. |
| Ambiguity verdict | **CLEAR** — Testable; the link to novelty class MODEL_CORRECTION is added in the new text. |
| Action and reason | kept: Meaning unchanged; adds the cross-reference to novelty classes. |

### D-013 — `e2e.physical_validation`

Action: **kept** → S35-VAL-005

| Field | Audit |
|---|---|
| Meaning and scope | Physical claims need independent physical validation; simulation agreement or trend never suffices. |
| Dependencies and owner | Depends on SAI 3.4 ASM-009, ASM-010; independent data (SAI 3.4 D-02). Owner of the successor(s): PhysicalValidation. |
| I/O, schemas, states, trust boundaries | Inputs: independent reference data with uncertainty, split manifest. Outputs: validation reports. |
| Behavior | Expected: holdout disjoint from construction and calibration. Failure: circular validation. Stop: BLOCKED without reference. |
| Phase and prerequisites | Old phase D5; successor phase P35-8; gates G4, G5, G-D4 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-013 — "A physical discovery claim without independent reference data and measurement uncertainty is refused; simulation-only agreement cannot pass G-D4." New: T-S35-VAL-005 (deterministic split checks, empirical acceptance). |
| Inherited | SAI 3.4: ASM-009, ASM-010; SAI 3.3: EVI-004, DOM-SP-002. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-VAL-005 blocked. |
| Ambiguity verdict | **CLEAR** — Testable; blocked by data. |
| Action and reason | kept: Meaning unchanged; new ID. |

### D-014 — `e2e.bilingual_report`

Action: **refined** → S35-RPT-001

| Field | Audit |
|---|---|
| Meaning and scope | Discovery reports are traceable and bilingual under ASM-016, covering the eight content classes plus discovery content; same identifiers, numbers, states and uncertainty in both languages. |
| Dependencies and owner | Depends on SAI 3.4 ASM-016; SAI 3.3 UX-006. Owner of the successor(s): ReportGenerator. |
| I/O, schemas, states, trust boundaries | Inputs: canonical records. Outputs: zh-TW and en reports and exports. Trust boundary: translation is derived presentation. |
| Behavior | Expected: structural and semantic parity. Failure: a field present in one language only, or a translation overwriting a record. Stop: export refused. |
| Phase and prerequisites | Old phase D2; successor phase P35-4; gates G0, G9, G-D2 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-014 — "zh-TW and en reports cover the eight ASM-016 classes plus problem provenance, mechanism classes with experiment-set version, anomaly states, reframing history, pre-registrations, validation outcomes and stop reasons, with identical identifiers, numbers and states and unchanged canonical hashes." New: T-S35-RPT-001 (deterministic and bilingual review). |
| Inherited | SAI 3.4: ASM-016; SAI 3.3: UX-006. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-RPT-001 partial. |
| Ambiguity verdict | **AMBIGUOUS** — Did not include epistemic stages, novelty class with coverage, envelopes or realized cost, and did not name the parity test. |
| Action and reason | refined: Adds the missing content classes and the parity and bilingual-review acceptance; reproducible bundle, glossary and UX are new (S35-RPT-002..004). |

### D-015 — `loop.problem_discovery`

Action: **refined** → S35-PROB-001

| Field | Audit |
|---|---|
| Meaning and scope | Problem discovery produces ResearchProblem records with origin and links; non-zero-cost work waits for a human member to accept the problem; no INTERNAL egress. |
| Dependencies and owner | Depends on SAI 3.3 SEC-001/002; SAI 3.4 ASM-014. Owner of the successor(s): ProblemDiscovery. |
| I/O, schemas, states, trust boundaries | Inputs: anomalies, literature gaps, failed hypotheses, Owner questions. Output: ResearchProblem. Trust boundary: TB-2 for any search. |
| Behavior | Expected: refusal of problems without origin or links. Failure: resource use without acceptance. Stop: refusal. |
| Phase and prerequisites | Old phase D1; successor phase P35-2; gates G-D1, G-D2 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-015 — "Every ResearchProblem has an origin and resolvable links; a problem not accepted by an active human member consumes no non-zero-cost resource; INTERNAL material never passes the egress gate." New: T-S35-PROB-001 (deterministic). |
| Inherited | SAI 3.4: ASM-014; SAI 3.3: SEC-001, SEC-002. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-PROB-001 proposed. |
| Ambiguity verdict | **AMBIGUOUS** — Origins omitted contradictions, knowledge gaps and validation residuals; per-problem human acceptance conflicted with envelope-bounded autonomy; no valuation of problems. |
| Action and reason | refined: Adds origins and allows envelope coverage instead of only per-problem acceptance; valuation and contradiction/gap detection are new (S35-PROB-002, S35-PROB-004). |

### D-016 — `loop.mechanism_classes`

Action: **merged** → S35-MECH-001

| Field | Audit |
|---|---|
| Meaning and scope | Mechanism expansion is measured by distinguishable mechanism classes under the experiment set; raw hypothesis counts are never diversity; counts name the experiment-set version. |
| Dependencies and owner | Depends on SAI 3.3 EPI-001, LLM-002. Owner of the successor(s): MechanismExplorer. |
| I/O, schemas, states, trust boundaries | Inputs: admitted hypotheses, experiment set E. Output: class count. |
| Behavior | Expected: renamed variants do not increase the count. Failure: count-based diversity. Stop: report refused. |
| Phase and prerequisites | Old phase D1; successor phase P35-2; gates G-D1, G-D2, G-D3 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-016 — "No report or metric presents a raw hypothesis count as diversity; every class count names its experiment-set version." New: T-S35-MECH-001 (deterministic). |
| Inherited | SAI 3.4: —; SAI 3.3: EPI-001, LLM-002. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-MECH-001 partial. |
| Ambiguity verdict | **CLEAR** — Testable, but inseparable from D-017, which defines the classes it counts. |
| Action and reason | merged: Merged with D-017: the metric and its class definition are one obligation with one test. |

### D-017 — `loop.mechanism_class_definition`

Action: **merged** → S35-MECH-001

| Field | Audit |
|---|---|
| Meaning and scope | Two hypotheses are one class under E when their typed predictions cannot be told apart within tolerance for every experiment in E; deterministic, versioned, recomputed; undecidable pairs merged and listed. |
| Dependencies and owner | Depends on SAI 3.3 VER-006, VER-008. Owner of the successor(s): MechanismExplorer. |
| I/O, schemas, states, trust boundaries | Inputs: typed predictions, E, tolerances. Output: versioned partition with merged pairs. |
| Behavior | Expected: deterministic partition. Failure: non-deterministic or unlisted merges. Stop: not applicable. |
| Phase and prerequisites | Old phase D1; successor phase P35-2; gates G-D1, G-D2, G-D3 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-017 — "The partition is deterministic and versioned, recomputed when the experiment set changes, merges undecidable pairs conservatively and lists them." New: T-S35-MECH-001 (deterministic). |
| Inherited | SAI 3.4: —; SAI 3.3: VER-006, VER-008. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-MECH-001 partial. |
| Ambiguity verdict | **AMBIGUOUS** — 'Cannot be told apart within tolerance' did not say over which parameter ranges (best or worst case), at how many replicates, or against which threshold; the offline prototype had to choose. |
| Action and reason | merged: Merged with D-016 and made precise: worst case over the whole parameter ranges, declared replicates, pre-registered threshold. |

### D-018 — `loop.anomaly_state`

Action: **refined** → S35-PROB-003

| Field | Audit |
|---|---|
| Meaning and scope | Anomaly registry with explicit append-only states; never deleted or dropped; state changes record trigger, evidence and actor. |
| Dependencies and owner | Depends on SAI 3.3 EPI-003, EPI-006; SAI 3.4 ASM-012/013. Owner of the successor(s): ProblemDiscovery. |
| I/O, schemas, states, trust boundaries | Inputs: admitted observations, detection rules. Output: anomaly records and state events. |
| Behavior | Expected: only listed transitions. Failure: deletion or silent omission. Stop: refusal. |
| Phase and prerequisites | Old phase D1; successor phase P35-2; gates G-D1, G-D2, G-D3 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-018 — "Anomalies move only through the listed states with append-only events; EXPLAINED requires a Causal Warrant Gate confirmation; no anomaly disappears from records or reports." New: T-S35-PROB-003 (deterministic). |
| Inherited | SAI 3.4: ASM-012, ASM-013; SAI 3.3: EPI-003, EPI-006. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-PROB-003 partial. |
| Ambiguity verdict | **AMBIGUOUS** — The state set lacked ACCOMMODATED and ATTRIBUTED_TO_NOISE, which the offline prototype needed (accommodation is not explanation; noise attribution after a pre-registered replication). |
| Action and reason | refined: Union of the candidate and prototype state sets with an explicit transition table. |

### D-019 — `loop.reframing`

Action: **refined** → S35-REF-002

| Field | Audit |
|---|---|
| Meaning and scope | Reframing is append-only, links failed hypotheses, anomalies and the earlier problem, never hides failure history and never turns failure into support. |
| Dependencies and owner | Depends on SAI 3.4 ASM-011/012. Owner of the successor(s): ResearchReframing. |
| I/O, schemas, states, trust boundaries | Inputs: failed hypotheses, anomalies. Output: Reframing record. |
| Behavior | Expected: failure history preserved. Failure: edited or deleted history; failure reinterpreted as support. Stop: refusal. |
| Phase and prerequisites | Old phase D1; successor phase P35-2; gates G-D1, G-D2, G-D3 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-019 — "A reframing appends a record linked to failed hypotheses, anomalies and the prior problem; no failure record is deleted or edited; evidence that failed a hypothesis never supports it or its successor." New: T-S35-REF-002 (deterministic). |
| Inherited | SAI 3.4: ASM-011, ASM-012; SAI 3.3: EPI-003, EPI-005. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-REF-002 partial. |
| Ambiguity verdict | **AMBIGUOUS** — Triggers were limited to failed hypotheses; assumption, observable and model failures, and the reframing kinds, were undefined. |
| Action and reason | refined: Keeps the failure-history obligation and extends links to assumptions, observables and models; triggers and kinds are new (S35-REF-001). |

### D-020 — `loop.reframing_accounting`

Action: **kept** → S35-REF-003

| Field | Audit |
|---|---|
| Meaning and scope | A reframed hypothesis is new, needs new prospective validation, stays in the denominators, and reframings are capped by policy and budget. |
| Dependencies and owner | Depends on SAI 3.4 ASM-010; OD-12. Owner of the successor(s): ResearchReframing. |
| I/O, schemas, states, trust boundaries | Inputs: Reframing. Output: successor hypothesis with lineage. |
| Behavior | Expected: pre-existing evidence cannot support the successor. Failure: denominators drop abandoned branches. Stop: cap reached → STOP_INSUFFICIENT. |
| Phase and prerequisites | Old phase D1; successor phase P35-2; gates G-D1, G-D2, G-D3 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-020 — "Reframed hypotheses carry new lineage and need prospective validation; every reframing and abandoned branch stays in metric denominators; the reframing cap is enforced." New: T-S35-REF-003 (deterministic). |
| Inherited | SAI 3.4: ASM-010; SAI 3.3: EPI-003. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-REF-003 partial. |
| Ambiguity verdict | **CLEAR** — Testable; the cap value is an Owner decision (OD-12). |
| Action and reason | kept: Meaning unchanged; new ID. |

### D-021 — `loop.experiment_selection`

Action: **refined** → S35-SEL-001

| Field | Audit |
|---|---|
| Meaning and scope | Experiments are chosen to discriminate between classes per unit cost, deterministically, without uncalibrated EIG; gated experiments are only proposed. |
| Dependencies and owner | Depends on SAI 3.3 VER-001/002/003/005. Owner of the successor(s): VerificationPlanner. |
| I/O, schemas, states, trust boundaries | Inputs: surviving classes, capabilities, CostVector. Output: ranked plan. |
| Behavior | Expected: deterministic ranking. Failure: dispatch before a gate. Stop: no affordable discriminating experiment → stop. |
| Phase and prerequisites | Old phase D1; successor phase P35-2; gates G-D1, G-D2, G-D3 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-021 — "Identical state and policy yield an identical ranked plan by classes separated per CostVector; no uncalibrated information-gain value is used; gated experiments are only proposed until authorized." New: T-S35-SEL-001 (deterministic). |
| Inherited | SAI 3.4: ASM-002; SAI 3.3: VER-001, VER-002, VER-003, VER-005. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-SEL-001 partial. |
| Ambiguity verdict | **AMBIGUOUS** — 'Separates the most surviving classes' lacked a weighting rule and did not name the owning component (planner versus Discovery Loop). |
| Action and reason | refined: Assigns the Verification Planner and a versioned weighting policy; independent evaluation of competing explanations is new (S35-SEL-002). |

### D-022 — `loop.termination`

Action: **refined** → S35-LIFE-003

| Field | Audit |
|---|---|
| Meaning and scope | Every campaign runs under explicit budgets and a versioned stopping policy, always terminates, and exhaustion is never a discovery. |
| Dependencies and owner | Depends on SAI 3.3 COST-001; SAI 3.4 ASM-007/011. Owner of the successor(s): CampaignOrchestrator. |
| I/O, schemas, states, trust boundaries | Inputs: budgets, stopping policy. Output: termination reason. |
| Behavior | Expected: termination within caps. Failure: unbounded loop or exhaustion reported as finding. Stop: STOPPED or INSUFFICIENT_VALIDATION. |
| Phase and prerequisites | Old phase D1; successor phase P35-2; gates G8, G-D1 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-022 — "Every campaign terminates within its budgets with a recorded reason; exhaustion and stagnation end as STOPPED or INSUFFICIENT_VALIDATION and are never reported as discoveries." New: T-S35-LIFE-003 (deterministic). |
| Inherited | SAI 3.4: ASM-007, ASM-011; SAI 3.3: COST-001. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-LIFE-003 partial. |
| Ambiguity verdict | **AMBIGUOUS** — Did not include money and reframings in the budget list or bind termination to campaign closed states. |
| Action and reason | refined: Binds termination to the campaign states and extends the budget dimensions. |

### D-023 — `validation.role_separation`

Action: **refined** → S35-LOOP-001

| Field | Audit |
|---|---|
| Meaning and scope | Discovery and validation are separate roles, identities and permissions; discovery cannot write verdicts or read sealed material; validation does not generate what it validates. |
| Dependencies and owner | Depends on SAI 3.3 SEC-002, EPI-005; SAI 3.4 ASM-010/013. Owner of the successor(s): DiscoveryLoop. |
| I/O, schemas, states, trust boundaries | Inputs: identities and permissions. Outputs: refusals. Trust boundary: Discovery versus validation versus evaluation planes. |
| Behavior | Expected: every cross-role write refused. Failure: self-certification. Stop: refusal. |
| Phase and prerequisites | Old phase D2; successor phase P35-2; gates G6, G8, G-D1 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-023 — "Discovery identities cannot write verdicts, change validators, protocols or scoring, or read sealed material; validation does not generate the hypotheses it validates; access attempts are refused and logged." New: T-S35-LOOP-001 (deterministic). |
| Inherited | SAI 3.4: ASM-010, ASM-013; SAI 3.3: SEC-002, EPI-005. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-LOOP-001 partial. |
| Ambiguity verdict | **AMBIGUOUS** — Did not list which components are Discovery-side, and had no permission-matrix test. |
| Action and reason | refined: Names the Discovery-side components and adds the permission-matrix acceptance; the matrix itself is S35-SEC-005. |

### D-024 — `validation.preregistration`

Action: **refined** → S35-REG-001

| Field | Audit |
|---|---|
| Meaning and scope | Each validation is pre-registered before its data exists, dated by the database clock, immutable, and authorized by a human member when it uses money, a license or a physical experiment. |
| Dependencies and owner | Depends on SAI 3.4 ASM-010; G0 line 011s/011w. Owner of the successor(s): RegistrationRegistry. |
| I/O, schemas, states, trust boundaries | Inputs: hypothesis, predictions, capability, analysis, decision rule. Output: Registration. |
| Behavior | Expected: changes create new registrations. Failure: edited registration or back-dated time. Stop: refusal. |
| Phase and prerequisites | Old phase D2; successor phase P35-2; gates G0, G6, G-D1 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-024 — "A validation without an earlier immutable registration supports nothing; registrations are dated by the database clock and need human authorization when money, licenses or physical experiments are used." New: T-S35-REG-001 (deterministic). |
| Inherited | SAI 3.4: ASM-010; SAI 3.3: VER-006, EPI-005. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-REG-001 partial. |
| Ambiguity verdict | **AMBIGUOUS** — Did not bind the registration to a Job or to the capability declaration hash, and per-registration human authorization was the only route, which excludes envelope-bounded automatic registration. |
| Action and reason | refined: Binds one Job and the declaration hash and allows a covering envelope as the authorization route; envelope rules are new (S35-REG-002, S35-REG-003). |

### D-025 — `validation.no_retrospective_self_support`

Action: **refined** → S35-REG-004

| Field | Audit |
|---|---|
| Meaning and scope | No retrospective self-support: pre-existing, derived-from, unknown-time and tainted-lineage evidence cannot support a hypothesis; recorded as CITES; at least as strict as G0 rules 011p and 011s. |
| Dependencies and owner | Depends on G0 line 011p, 011s; SAI 3.3 EVI-004/009. Owner of the successor(s): ValidationLoop. |
| I/O, schemas, states, trust boundaries | Inputs: evidence lineage and capture times. Output: SUPPORTS or CITES. |
| Behavior | Expected: tainted evidence stored as CITES. Failure: retrospective support. Stop: not applicable. |
| Phase and prerequisites | Old phase D2; successor phase P35-2; gates G0, G6, G-D1 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-025 — "Every 011p/011s refusal case, applied to discovery and reframed hypotheses, records CITES instead of SUPPORTS; a genuinely new, pre-registered, clean-lineage check can support." New: T-S35-REG-004 (deterministic). |
| Inherited | SAI 3.4: ASM-012, ASM-013; SAI 3.3: EVI-004, EVI-009, EPI-002. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-REG-004 partial. |
| Ambiguity verdict | **CLEAR** — Testable; the cited G0 commit is updated to f41758c and the rule list is named. |
| Action and reason | refined: Names the 011s rules (a)–(k) at f41758c and the eleven defect fixtures as acceptance. |

### D-026 — `validation.cwg_only_confirmed`

Action: **refined** → S35-CWG-001

| Field | Audit |
|---|---|
| Meaning and scope | The Causal Warrant Gate V1.1 remains the only path to CONFIRMED; no shortcut, no widening of DISCRIMINATION or multi-cause; SP 1.1.0 not enabled. |
| Dependencies and owner | Depends on SAI 3.4 ASM-013, D-03. Owner of the successor(s): CausalWarrantGate. |
| I/O, schemas, states, trust boundaries | Inputs: warrants, signed reviews, confirmation rule. Output: CONFIRMED decisions. |
| Behavior | Expected: no other writer of CONFIRMED. Failure: confirmation by agreement or match. Stop: refusal. |
| Phase and prerequisites | Old phase D2; successor phase P35-2; gates G6, G-D1, G-D2, G-D3, G-D4 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-026 — "The number of CONFIRMED discovery claims not re-derivable through the Causal Warrant Gate is zero; no discovery component can mint a warrant." New: T-S35-CWG-001 (deterministic). |
| Inherited | SAI 3.4: ASM-013; SAI 3.3: EPI-002, EPI-004, EPI-005. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-CWG-001 partial. |
| Ambiguity verdict | **CLEAR** — Testable; 'exclusive' and 'projection only' added for display paths. |
| Action and reason | refined: Makes the gate the exclusive authority for writing and displaying CONFIRMED; consequential authorization is new (S35-CWG-002). |

### D-027 — `validation.epistemic_states`

Action: **split** → S35-HYP-001, S35-HYP-003

| Field | Audit |
|---|---|
| Meaning and scope | Every discovery claim carries an explicit epistemic state from a table, derived as a projection, with allowed transitions only. |
| Dependencies and owner | Depends on SAI 3.3 §8.2, EPI-003/005; SAI 3.4 ASM-013. Owner of the successor(s): DiscoveryLoop, ValidationLoop. |
| I/O, schemas, states, trust boundaries | Inputs: canonical records. Output: projected claim state. |
| Behavior | Expected: replay reproduces states. Failure: forbidden transition. Stop: refusal and log. |
| Phase and prerequisites | Old phase D2; successor phase P35-2; gates G6, G-D1 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-027 — "The projection is rebuilt from canonical records alone; every transition outside the allowed table is refused and logged; the projection never writes a belief state." New: T-S35-HYP-001 (deterministic); T-S35-HYP-003 (deterministic). |
| Inherited | SAI 3.4: ASM-013, ASM-018; SAI 3.3: EPI-003, EPI-005, SYS-001. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-HYP-001 partial; S35-HYP-003 proposed. |
| Ambiguity verdict | **AMBIGUOUS** — Thirteen states mixed epistemic stage with process state; the three stages (idea, testable hypothesis, evidence-supported conclusion) and the mapping to SAI 3.3 §8.2 were not stated. |
| Action and reason | split: The three epistemic stages (S35-HYP-001) and the claim-state projection with transitions (S35-HYP-003). |

### D-028 — `validation.stop_insufficient`

Action: **kept** → S35-LOOP-003

| Field | Audit |
|---|---|
| Meaning and scope | The system must be able to stop: INSUFFICIENT_VALIDATION or STOPPED with reason, attempts, cost and needs; a governance success; confident claims where a stop was warranted are false discoveries. |
| Dependencies and owner | Depends on SAI 3.3 EPI-001; SAI 3.4 ASM-011/018. Owner of the successor(s): ValidationLoop. |
| I/O, schemas, states, trust boundaries | Inputs: campaign state. Output: StopRecord. |
| Behavior | Expected: explicit stop record. Failure: confident claim instead of stop. Stop: by definition. |
| Phase and prerequisites | Old phase D1; successor phase P35-2; gates G-D1, G-D2, G-D3, G-D4 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-028 — "In no-mechanism-validatable cases the system ends with INSUFFICIENT_VALIDATION or STOPPED with reason, attempts, cost and needs; the scorer counts it as correct; a confident claim there counts as a false discovery." New: T-S35-LOOP-003 (deterministic and empirical). |
| Inherited | SAI 3.4: ASM-011, ASM-018; SAI 3.3: EPI-001. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-LOOP-003 partial. |
| Ambiguity verdict | **CLEAR** — Testable as written. |
| Action and reason | kept: Meaning unchanged; new ID. |

### D-029 — `validation.uncertainty`

Action: **kept** → S35-VAL-003

| Field | Audit |
|---|---|
| Meaning and scope | Uncertainty reported separately by source; ordinal belief until calibrated; no uncalibrated probability; UNKNOWN shown. |
| Dependencies and owner | Depends on SAI 3.4 ASM-008/009/016. Owner of the successor(s): NumericalValidation. |
| I/O, schemas, states, trust boundaries | Inputs: uncertainty components. Output: claim uncertainty fields. |
| Behavior | Expected: all sources present or UNKNOWN. Failure: probability shown for uncalibrated belief. Stop: refusal. |
| Phase and prerequisites | Old phase D2; successor phase P35-2; gates G4, G5, G-D2, G-D3 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-029 — "Each claim lists uncertainty by source with UNKNOWN where unknown; no uncalibrated number is displayed as a probability of truth." New: T-S35-VAL-003 (deterministic). |
| Inherited | SAI 3.4: ASM-008, ASM-009, ASM-016; SAI 3.3: EVI-001, EVI-002. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-VAL-003 partial. |
| Ambiguity verdict | **CLEAR** — Testable; the combination rule (only under independence) is added from SAI 3.4 acceptance §3. |
| Action and reason | kept: Meaning unchanged; adds the combination rule already in SAI 3.4 acceptance §3. |

### D-030 — `oversight.owner_gates`

Action: **refined** → S35-SEC-002

| Field | Audit |
|---|---|
| Meaning and scope | Four action classes need a recorded Owner gate: money, licenses, physical experiments, publication; automation never signs; timeouts are never consent. |
| Dependencies and owner | Depends on SAI 3.3 COST-001, OPS-002, SEC-002; SAI 3.4 ASM-007/014. Owner of the successor(s): GovernancePlane. |
| I/O, schemas, states, trust boundaries | Inputs: action requests, authorizations. Output: allow or refuse. |
| Behavior | Expected: refusal before any side effect without authorization. Failure: implicit consent. Stop: refusal. |
| Phase and prerequisites | Old phase D2; successor phase P35-4; gates G8, G-D1, G-D3, G-D4 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-030 — "Money, license, physical-experiment and publication actions without a valid recorded Owner authorization produce zero side effects; timeouts never authorize." New: T-S35-SEC-002 (deterministic). |
| Inherited | SAI 3.4: ASM-007, ASM-014; SAI 3.3: COST-001, OPS-002, SEC-002. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-SEC-002 partial. |
| Ambiguity verdict | **AMBIGUOUS** — Did not say whether an Owner can pre-authorize classes of action within ceilings (needed for envelope autonomy) or which classes never can be. |
| Action and reason | refined: Allows envelope pre-authorization for money and licenses within ceilings; physical experiments and publication stay per action. |

### D-031 — `oversight.evidence_governance`

Action: **kept** → S35-EVI-001

| Field | Audit |
|---|---|
| Meaning and scope | Discovery outputs are proposals; they enter the record only through the admission path; records are append-only. |
| Dependencies and owner | Depends on SAI 3.4 ASM-012; SAI 3.3 EVI-003/009. Owner of the successor(s): ValidationLoop. |
| I/O, schemas, states, trust boundaries | Inputs: discovery outputs. Outputs: Observations and Attestations through admission. |
| Behavior | Expected: unbound outputs refused. Failure: discovery output admitted as evidence. Stop: refusal. |
| Phase and prerequisites | Old phase D2; successor phase P35-2; gates G6, G-D1 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-031 — "No discovery output is admitted as evidence outside the admission path; corrections are new events and originals remain." New: T-S35-EVI-001 (deterministic). |
| Inherited | SAI 3.4: ASM-012; SAI 3.3: EVI-003, EVI-009, SYS-001. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-EVI-001 partial. |
| Ambiguity verdict | **CLEAR** — Testable as written. |
| Action and reason | kept: Meaning unchanged; new ID. |

### D-032 — `oversight.provenance`

Action: **kept** → S35-EVI-002

| Field | Audit |
|---|---|
| Meaning and scope | Every discovery record carries provenance: inputs by hash, producer and version, InferenceProvenance, policy versions, trace. |
| Dependencies and owner | Depends on SAI 3.3 LLM-001, OPS-003, ART-001. Owner of the successor(s): GovernancePlane. |
| I/O, schemas, states, trust boundaries | Inputs: discovery records. Output: provenance fields. |
| Behavior | Expected: records without provenance refused. Failure: unjustified transitions. Stop: refusal. |
| Phase and prerequisites | Old phase D2; successor phase P35-2; gates G0, G6, G-D1 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-032 — "Every discovery record carries input hashes, producer and version, InferenceProvenance, policy versions and trace; a record without them cannot justify a transition." New: T-S35-EVI-002 (deterministic). |
| Inherited | SAI 3.4: ASM-002, ASM-017; SAI 3.3: LLM-001, OPS-003, ART-001. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-EVI-002 partial. |
| Ambiguity verdict | **CLEAR** — Testable; the record list is extended to the new record types. |
| Action and reason | kept: Meaning unchanged; record list extended. |

### D-033 — `oversight.project_isolation`

Action: **kept** → S35-SEC-003

| Field | Audit |
|---|---|
| Meaning and scope | Discovery records, benchmark material, worker sessions, caches and evaluator access are project- and clearance-scoped; sealed material only in the evaluation plane. |
| Dependencies and owner | Depends on SAI 3.3 SEC-002; SAI 3.4 ASM-014. Owner of the successor(s): GovernancePlane. |
| I/O, schemas, states, trust boundaries | Inputs: reads and writes. Output: allow or refuse. |
| Behavior | Expected: cross-project access refused. Failure: leakage. Stop: refusal. |
| Phase and prerequisites | Old phase D2; successor phase P35-2; gates G8, G-D1 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-033 — "Cross-project reads of discovery records, benchmarks, sessions or caches are refused without a project occurrence; sealed material is unreachable from the control plane." New: T-S35-SEC-003 (deterministic). |
| Inherited | SAI 3.4: ASM-014; SAI 3.3: SEC-002. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-SEC-003 partial. |
| Ambiguity verdict | **CLEAR** — Testable; envelopes and registrations added to the list. |
| Action and reason | kept: Meaning unchanged; new ID. |

### D-034 — `oversight.accounts`

Action: **kept** → S35-SEC-004

| Field | Audit |
|---|---|
| Meaning and scope | Human roles stay ADMIN and MEMBER; other governance concepts grant no role; a second account is never independent; A3/A9/A12 stay open. |
| Dependencies and owner | Depends on SAI 3.4 ASM-014; A3, A9, A12. Owner of the successor(s): GovernancePlane. |
| I/O, schemas, states, trust boundaries | Inputs: account and enrolment data. Output: role checks. |
| Behavior | Expected: no third role. Failure: role inflation. Stop: refusal. |
| Phase and prerequisites | Old phase D0; successor phase P35-2; gates G0, G8, G-D0 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-034 — "Only ADMIN and MEMBER account roles exist; evaluator and reviewer independence is not satisfied by a second account of the same natural person; A3, A9 and A12 remain OPEN." New: T-S35-SEC-004 (deterministic). |
| Inherited | SAI 3.4: ASM-014; SAI 3.3: SEC-002. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-SEC-004 partial. |
| Ambiguity verdict | **CLEAR** — Testable; envelope-authorizer enrolment added. |
| Action and reason | kept: Meaning unchanged; new ID. |

### D-035 — `gd.independence`

Action: **refined** → S35-GD-001

| Field | Audit |
|---|---|
| Meaning and scope | G-D acceptance is independent of G0–G9; only an independent Owner-assigned evaluator issues G-D verdicts. |
| Dependencies and owner | Depends on SAI 3.4 ASM-018; OD-02. Owner of the successor(s): EvaluationPlane. |
| I/O, schemas, states, trust boundaries | Inputs: frozen protocol, outputs. Output: signed verdict. |
| Behavior | Expected: verdict only by the evaluator. Failure: implementer verdict. Stop: verdict invalid. |
| Phase and prerequisites | Old phase D0; successor phase P35-3; gates G-D0, G-D1, G-D2, G-D3, G-D4 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-035 — "Every G-D verdict is signed by an Owner-assigned evaluator who is not the implementer; no G-D status is derived from G0-G9 results; the system cannot issue a verdict." New: T-S35-GD-001 (deterministic). |
| Inherited | SAI 3.4: ASM-018; SAI 3.3: TST-003. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-GD-001 blocked. |
| Ambiguity verdict | **CLEAR** — Testable; the synthetic-benchmark rule is added. |
| Action and reason | refined: Adds that synthetic benchmark success is never reported as real discovery validation and that a second account of the implementer is excluded. |

### D-036 — `gd.levels`

Action: **kept** → S35-GD-002

| Field | Audit |
|---|---|
| Meaning and scope | G-D has five levels with frozen criteria; lower never implies higher; results are scope-bound. |
| Dependencies and owner | Depends on acceptance-gd.md. Owner of the successor(s): EvaluationPlane. |
| I/O, schemas, states, trust boundaries | Inputs: level protocol. Output: level verdict. |
| Behavior | Expected: scope named in every verdict. Failure: extrapolation. Stop: INVALID on protocol change. |
| Phase and prerequisites | Old phase D0; successor phase P35-3; gates G-D0, G-D1, G-D2, G-D3, G-D4 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-036 — "Each level has frozen entry conditions, evidence and pass or fail criteria before evaluation; a missing threshold makes the level BLOCKED; results name their scope." New: T-S35-GD-002 (deterministic). |
| Inherited | SAI 3.4: ASM-018; SAI 3.3: LLM-002. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-GD-002 blocked. |
| Ambiguity verdict | **CLEAR** — Testable as written. |
| Action and reason | kept: Meaning unchanged; new ID. |

### D-037 — `gd.no_substitution`

Action: **kept** → S35-GD-003

| Field | Audit |
|---|---|
| Meaning and scope | G-D and G0–G9 do not substitute; G-D2/3/4 prerequisites on G gates. |
| Dependencies and owner | Depends on SAI 3.4 G0–G9. Owner of the successor(s): EvaluationPlane. |
| I/O, schemas, states, trust boundaries | Inputs: gate records. Output: entry decision. |
| Behavior | Expected: verdict refused without prerequisites. Failure: substitution. Stop: exploratory label. |
| Phase and prerequisites | Old phase D0; successor phase P35-3; gates G-D2, G-D3, G-D4 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-037 — "No G gate changes because of a G-D result and no G-D level passes without its listed G prerequisites; earlier runs are labeled exploratory." New: T-S35-GD-003 (deterministic). |
| Inherited | SAI 3.4: ASM-018; SAI 3.3: —. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-GD-003 proposed. |
| Ambiguity verdict | **CLEAR** — Testable as written. |
| Action and reason | kept: Meaning unchanged; new ID. |

### D-038 — `compare.three_arms`

Action: **refined** → S35-CMP-001

| Field | Audit |
|---|---|
| Meaning and scope | Every G-D1..G-D4 evaluation compares three arms: (A) single LLM, (B) existing LIB, (C) LIB with Discovery, with one answer schema. |
| Dependencies and owner | Depends on OD-04, OD-05. Owner of the successor(s): EvaluationPlane. |
| I/O, schemas, states, trust boundaries | Inputs: frozen arm configurations. Outputs: per-case answers. |
| Behavior | Expected: arms differ only in listed components. Failure: an arm with extra tools. Stop: INVALID. |
| Phase and prerequisites | Old phase D1; successor phase P35-3; gates G-D1, G-D2, G-D3, G-D4 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-038 — "Every G-D1 to G-D4 evaluation reports arms A, B and C on the same cases with the same answer schema, including the stop option." New: T-S35-CMP-001 (deterministic). |
| Inherited | SAI 3.4: —; SAI 3.3: LLM-002. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-CMP-001 partial. |
| Ambiguity verdict | **AMBIGUOUS** — 'Single LLM' did not say which model in a zero-cost stage versus a paid stage; the requested arm is a single frontier LLM, and the offline B0 stand-in was easy to mistake for it. |
| Action and reason | refined: Names arm A as the single frontier LLM, defines the model per stage, and states that B0 is not arm A. |

### D-039 — `compare.matching`

Action: **refined** → S35-CMP-002

| Field | Audit |
|---|---|
| Meaning and scope | Arms are matched on models, budgets (caps), tools, data, time, seeds and environment; unused budget not transferred; overruns end as STOPPED. |
| Dependencies and owner | Depends on SAI 3.3 COST-001, VER-003; OD-03. Owner of the successor(s): EvaluationPlane. |
| I/O, schemas, states, trust boundaries | Inputs: manifests, caps. Output: matched runs. |
| Behavior | Expected: identical manifests. Failure: mismatch. Stop: INVALID. |
| Phase and prerequisites | Old phase D1; successor phase P35-3; gates G-D1, G-D2, G-D3, G-D4 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-039 — "Budget ledgers show identical caps per case for every arm across models, tokens, compute, experiments, licensed time, tools, data, time, seeds and environment; any mismatch makes the comparison INVALID." New: T-S35-CMP-002 (deterministic). |
| Inherited | SAI 3.4: —; SAI 3.3: COST-001, VER-003. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-CMP-002 partial. |
| Ambiguity verdict | **AMBIGUOUS** — Matching on caps alone let an arm spend four times another's realized budget (the offline B2 versus B1) while still 'matched'; information exposure was not listed as a matched dimension. |
| Action and reason | refined: Matches on actual realized consumption with a pre-registered rule and COST_UNMATCHED label, and adds information exposure and experimental conditions. |

### D-040 — `compare.blinding`

Action: **kept** → S35-CMP-003

| Field | Audit |
|---|---|
| Meaning and scope | Blinded scoring by a non-implementer, sealed arm labels, deterministic hash-frozen scorer, two independent blinded reviewers for human judgments. |
| Dependencies and owner | Depends on OD-02. Owner of the successor(s): EvaluationPlane. |
| I/O, schemas, states, trust boundaries | Inputs: outputs with sealed labels. Output: scores. |
| Behavior | Expected: unsealing only after scoring. Failure: unblinding. Stop: INVALID. |
| Phase and prerequisites | Old phase D1; successor phase P35-3; gates G-D1, G-D2, G-D3, G-D4 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-040 — "The evaluator scores with sealed arm labels held by a custodian; the scorer is hash-frozen; at G-D2 and above two independent blinded reviewers judge novelty and falsifiability with agreement reported." New: T-S35-CMP-003 (deterministic). |
| Inherited | SAI 3.4: ASM-010; SAI 3.3: —. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-CMP-003 proposed. |
| Ambiguity verdict | **CLEAR** — Testable as written. |
| Action and reason | kept: Meaning unchanged; new ID. |

### D-041 — `compare.benchmark`

Action: **refined** → S35-CMP-004

| Field | Audit |
|---|---|
| Meaning and scope | The benchmark is frozen and sealed before any arm runs, with synthetic worlds, held-out literature and later physical cases; implementers never see truth; every case stays in the denominator. |
| Dependencies and owner | Depends on OD-02; discovery-independent-evaluation @ d7ec9f2 (protocol and tooling pushed, not reviewed). Owner of the successor(s): EvaluationPlane. |
| I/O, schemas, states, trust boundaries | Inputs: generator, case material. Output: sealed benchmark. |
| Behavior | Expected: commitments before runs. Failure: implementer access. Stop: re-seal. |
| Phase and prerequisites | Old phase D0; successor phase P35-3; gates G-D0, G-D1, G-D2, G-D3, G-D4 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-041 — "The benchmark is sealed before any arm runs, contains hidden-mechanism synthetic worlds including no-mechanism-validatable worlds, held-out literature cases and later physical cases, and keeps every case in the denominator." New: T-S35-CMP-004 (deterministic). |
| Inherited | SAI 3.4: ASM-010; SAI 3.3: LLM-002. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-CMP-004 proposed. |
| Ambiguity verdict | **AMBIGUOUS** — Did not require that the synthetic generator itself be owned by the evaluator; worlds written by the implementer (the offline benchmark) could be read as G-D material. |
| Action and reason | refined: Requires an evaluator-owned hidden-world generator and excludes implementer-written worlds from G-D evidence. |

### D-042 — `compare.metrics`

Action: **refined** → S35-CMP-005

| Field | Audit |
|---|---|
| Meaning and scope | Five metrics for every arm (true-mechanism discovery rate, distinguishable diversity, experimental efficiency, false discoveries, reproducibility), one primary metric. |
| Dependencies and owner | Depends on OD-03. Owner of the successor(s): EvaluationPlane. |
| I/O, schemas, states, trust boundaries | Inputs: frozen outputs. Output: metric table with n and intervals. |
| Behavior | Expected: all five with intervals. Failure: raw counts as diversity. Stop: report refused. |
| Phase and prerequisites | Old phase D1; successor phase P35-3; gates G-D1, G-D2, G-D3, G-D4 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-042 — "All five metrics are reported per arm with definition, n, estimate and interval; diversity is counted only as equivalence classes; drifted re-runs are INVALID; exactly one primary metric is pre-registered." New: T-S35-CMP-005 (deterministic). |
| Inherited | SAI 3.4: ASM-017; SAI 3.3: LLM-002. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-CMP-005 partial. |
| Ambiguity verdict | **AMBIGUOUS** — 'Reproducibility' did not say by whom (a self re-run is not independent), and efficiency did not use realized cost. |
| Action and reason | refined: Renamed to the requested five metrics: true-cause discovery, effective mechanism diversity, discriminating-experiment efficiency, false discoveries, independent reproducibility. |

### D-043 — `compare.statistics`

Action: **kept** → S35-CMP-006

| Field | Audit |
|---|---|
| Meaning and scope | Statistics pre-registered before unsealing; paired comparisons, intervals, minimum effect, margins, multiplicity, sample size, interim rules; no optional stopping. |
| Dependencies and owner | Depends on OD-03. Owner of the successor(s): EvaluationPlane. |
| I/O, schemas, states, trust boundaries | Inputs: protocol. Output: frozen analysis plan. |
| Behavior | Expected: analysis reads frozen values only. Failure: post-hoc exclusion. Stop: INVALID. |
| Phase and prerequisites | Old phase D0; successor phase P35-3; gates G-D0, G-D1, G-D2, G-D3, G-D4 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-043 — "The frozen protocol names unit, paired tests, intervals, minimum effect, margins, multiplicity, sample size and interim rules before unsealing; the analysis follows it exactly." New: T-S35-CMP-006 (deterministic). |
| Inherited | SAI 3.4: —; SAI 3.3: LLM-002. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-CMP-006 partial. |
| Ambiguity verdict | **CLEAR** — Testable as written. |
| Action and reason | kept: Meaning unchanged; new ID. |

### D-044 — `compare.contamination`

Action: **kept** → S35-CMP-007

| Field | Audit |
|---|---|
| Meaning and scope | Contamination controls frozen with the protocol: cutoffs, overlap checks, memorization probes, fresh seeds, pre-registered rule; findings reported. |
| Dependencies and owner | Depends on OD-03, OD-06. Owner of the successor(s): EvaluationPlane. |
| I/O, schemas, states, trust boundaries | Inputs: case material, model cutoffs. Output: contamination report. |
| Behavior | Expected: every exclusion names its rule. Failure: silent drop. Stop: INVALID for affected cases. |
| Phase and prerequisites | Old phase D0; successor phase P35-3; gates G-D0, G-D1, G-D2 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-044 — "Every case has recorded cutoff comparison, overlap check and memorization probe results; contaminated cases follow the rule frozen before unsealing and are reported." New: T-S35-CMP-007 (deterministic). |
| Inherited | SAI 3.4: ASM-010; SAI 3.3: EVI-004. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-CMP-007 partial. |
| Ambiguity verdict | **CLEAR** — Testable as written. |
| Action and reason | kept: Meaning unchanged; new ID. |

### D-045 — `compare.stopping`

Action: **kept** → S35-CMP-008

| Field | Audit |
|---|---|
| Meaning and scope | Stopping rules frozen: per case (budget, time, own stop), per study (n, interim, incident), paid stage at the Owner ceiling. |
| Dependencies and owner | Depends on OD-03, OD-05. Owner of the successor(s): EvaluationPlane. |
| I/O, schemas, states, trust boundaries | Inputs: caps, incidents. Output: stop decisions. |
| Behavior | Expected: cut at cap and scored. Failure: overrun. Stop: by definition. |
| Phase and prerequisites | Old phase D1; successor phase P35-3; gates G-D1, G-D2, G-D3, G-D4 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-045 — "Cases and studies end only by the frozen rules; governance incidents invalidate affected runs; paid stages end at the Owner ceiling and are reported as partial." New: T-S35-CMP-008 (deterministic). |
| Inherited | SAI 3.4: ASM-007; SAI 3.3: COST-001. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-CMP-008 partial. |
| Ambiguity verdict | **CLEAR** — Testable as written. |
| Action and reason | kept: Meaning unchanged; new ID. |

### D-046 — `compare.zero_cost_first`

Action: **kept** → S35-CMP-009

| Field | Audit |
|---|---|
| Meaning and scope | A zero-cost first stage precedes any paid stage; its result goes to the Owner whatever it shows; a negative result is not overridden by a bigger model on the same cases. |
| Dependencies and owner | Depends on OD-04, OD-05. Owner of the successor(s): EvaluationPlane. |
| I/O, schemas, states, trust boundaries | Inputs: local models, offline worlds. Output: zero-cost report. |
| Behavior | Expected: paid stage refused without the report and authorization. Failure: re-running sealed cases. Stop: refusal. |
| Phase and prerequisites | Old phase D1; successor phase P35-3; gates G-D1, G-D2 (see [roadmap](roadmap.md)). |
| Acceptance | Old: T-D-046 — "The zero-cost stage runs and is reported before any paid, licensed or physical stage; spend ledgers for that stage are zero; later stages carry an Owner authorization with a ceiling." New: T-S35-CMP-009 (deterministic). |
| Inherited | SAI 3.4: ASM-007, ASM-018; SAI 3.3: COST-001. None is changed. |
| Status | Old: SPECIFIED, no test. Successor: S35-CMP-009 partial. |
| Ambiguity verdict | **CLEAR** — Testable as written. |
| Action and reason | kept: Meaning unchanged; new ID. |

