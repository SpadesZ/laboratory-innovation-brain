# SAI 3.5 — Appendix T: Semantic consistency report (candidate.3)

Version: `3.5.0-master-candidate.3`. Status: **CANDIDATE — NOT ACTIVE.** `READY_FOR_REAL_RESEARCH = false`. G0 is NOT PASSED.
Authority: informative. The record of Task S5: a requirement-by-requirement review of all
77 statements of [SAI 3.5](../SAI_3.5.md) §3 and the normative appendices, after the
corrections S1–S4 and the candidate.3 corrections of the Independent Chief Auditor's findings. It is an implementation agent's review, not the Independent Chief Auditor's.

## 1. Method

Two kinds of check were applied to every requirement.

**Mechanical** (enforced by [check_candidate.py](check_candidate.py) on every CI run): identifier,
key, level and section agree between §3 and the [registry](normative-statements.yaml); the full
statement and acceptance text agree; the owner component, gates and phase exist in the
architecture, acceptance and roadmap appendices; a traceability row, an implementation-status row
and an inherited-links row exist with the same values; evidence paths exist at their commits;
retired identifiers are mapped; load-bearing phrases are present; protected SAI 3.3/3.4 files are
byte-identical to `a38ad63`.

**Semantic** (this report): for each requirement, (a) is the obligation implementable as written,
(b) are inputs, outputs and states defined, (c) is the trust and authorization boundary explicit,
(d) is the acceptance test measurable, (e) does a concrete counterexample break it. Counterexamples
that concern the corrected definitions are executable in [semantic_reference.py](semantic_reference.py)
(S1-CE-1…11, S2-CE-1…10, S3-CE, ladder and termination cases) and every known-wrong variant of those
definitions is rejected by its self-test. The others are probes stated in the table; each is the
fixture the planned test must contain.

Verdicts: **consistent** (no change needed), **CORRECTED** (text changed in candidate.2; see
[change register](change-register.md) §6), **CLARIFIED** (wording made explicit, obligation
unchanged). 22 of 77 requirements were corrected or clarified; no identifier changed.

## 2. Findings that changed the specification

| Finding | Counterexample | Requirements | Resolution |
|---|---|---|---|
| F1 non-transitive distinguishability | A = 0, B = 0.75, C = 1.50, τ = 1 | MECH-001, HYP-002, SEL-001, SEL-002, NOV-002, CMP-005, EVI-002, LIFE-003, RPT-001 | [Appendix S](mechanism-distinguishability.md); S35-ISSUE-11 |
| F2 outcome-dependent cost matching | arm right at 10 stops; other right at 30 | CMP-002, CMP-005, CMP-008 | [Appendix J](matched-budget-protocol.md) §3.3–3.6; S35-ISSUE-12 |
| F3 epistemic stage on every record | a Registration or an Anomaly "in stage 2" | HYP-001, HYP-003, RPT-001, RPT-004, MOD-003 | Appendix C §3.1 scope; S35-ISSUE-13 |
| F4 exploration, spending and stops conflated | AL3-paid idea; stop before any experiment called complete | HYP-001, SEC-001, GOV-003, LIFE-002, LOOP-003, REG-003 | Appendix E §9; Appendix A §3.1; S35-ISSUE-14 |
| F5 force-fit when the true family is absent | best-fitting inadequate mechanism endorsed | MECH-002, CMP-005 metric 4 | adequacy before endorsement; S35-ISSUE-15, OD-18 |
| F6 member acceptance read as spending authority | member accepts, campaign spends money | PROB-001 | Owner gates still required |
| F7 (candidate.3) near-duplicate inflation of the maximum-clique diversity | (0, 0.9, 1.8, 2.7) plus 1.1, τ = 1: 2 → 3 | MECH-001, CMP-005 | definition kept; guarantee removed; descriptive only; S35-ISSUE-16 |
| F8 (candidate.3) realized cost unknowable at start | variable-cost model call; overrun; no headroom | CMP-002, CMP-008, COST-001 | reservation / settlement / retrospective checkpoints; S35-ISSUE-17 |
| F9 (candidate.3) merged evaluation outcomes | indistinguishable alternative counted as exact; stop folded into discovery; proposal as discovery | CMP-005, LOOP-003 | nine separate outcome categories; S35-ISSUE-18 |

## 3. Requirement-by-requirement table

Columns: owner · gates · phase · status from the registry; inputs → outputs or states; trust and
authorization boundary; acceptance kind (the acceptance text itself is in §3 of the master and is
checked against the registry); the counterexample probe; verdict; open Owner decisions or open
decisions inherited from other lines.

| Requirement | Owner · gates · phase · status | Inputs → outputs / states | Trust and authorization boundary | Acceptance | Counterexample probe | Verdict | Open decisions |
|---|---|---|---|---|---|---|---|
| S35-GOV-001 | SpecMaintenance · G-D0 · P35-0 · complete | SAI 3.3/3.4 texts → precedence rule; spec issues | inherited text wins; no newer-text-wins | deterministic | one-byte edit of a protected file; an S35 text weakening an inherited MUST | consistent; checker enforces hashes | — |
| S35-GOV-002 | SpecMaintenance · G-D1, G-D2, G-D3, G-D4 · P35-0 · complete | §2 capability table → 12 targets with requirements and gates | claims bounded by implementation-status evidence | deterministic | capability row naming no gate; a capability described as present | consistent | OD-01 |
| S35-GOV-003 | CampaignOrchestrator · G9, G-D1 · P35-4 · proposed | campaign records → completion and termination classification | system-selected registered test; CWG for discovery | empirical | campaign stopped before any experiment counted as complete (candidate.1 allowed it) | CORRECTED (S4): three termination dimensions; safe stop is valid termination, not completion, never discovery | — |
| S35-GOV-004 | SpecMaintenance · G-D0, G-D1, G-D2, G-D3, G-D4 · P35-0 · partial | documents, UI strings, reports → claim audit | engineering vs scientific validity | deterministic | synthetic G-D-like result stated without a signed verdict; diversity figure without E version | consistent; diversity claims now also bound by S35-MECH-001 | — |
| S35-GOV-005 | SpecMaintenance · G-D0 · P35-0 · complete | registry flags, ACTIVE_SPEC.yaml → NOT ACTIVE | Owner OD-16 after ICA review | deterministic | an S35 identifier in src/ or tests/ on an implementation branch | consistent; engineering branches must cite Appendix S by name, not by S35 identifier, until activation | OD-16 |
| S35-LIFE-001 | CampaignOrchestrator · G8, G-D1 · P35-2 · partial | stage outputs → checkpoints bound to project, campaign, trace, hash | producer identity per component | deterministic | restart after a committed side effect without checkpoint | consistent | — |
| S35-LIFE-002 | CampaignOrchestrator · G8, G-D1 · P35-2 · proposed | campaign events → states; closed campaign → three dimensions | Owner stop; envelope revocation | deterministic | CLOSED_CONCLUDED without a validated outcome; stop read as completion | CORRECTED (S4): dimensions added; invalid CONCLUDED refused | — |
| S35-LIFE-003 | CampaignOrchestrator · G8, G-D1 · P35-2 · partial | budgets, stopping policy → termination with reason | ceilings raised only by Owner | deterministic | infinite reframing; exhaustion rendered as finding; 'unresolvable class' undefined | CORRECTED (S1 wording): UNRESOLVED distinguishability replaces 'unresolvable class' | OD-12 |
| S35-PROB-001 | ProblemDiscovery · G-D1, G-D2 · P35-2 · proposed | canonical records → ResearchProblem with origin and provenance | envelope or member acceptance scopes; Owner gates for money/licenses | deterministic | member accepts a problem, then the campaign spends money with no Owner gate | CORRECTED (S5): acceptance never gives money or license authority | OD-14, OD-15 |
| S35-PROB-002 | ProblemDiscovery · G-D1, G-D2 · P35-2 · proposed | problems, policy → deterministic ProblemValuation ranking | model opinion is one recorded input only | deterministic | inverting the model opinion re-orders by more than its criterion | consistent | — |
| S35-PROB-003 | ProblemDiscovery · G-D1, G-D2, G-D3 · P35-2 · partial | observations → Anomaly with append-only state events | EXPLAINED only via a CWG decision | deterministic | anomaly given an epistemic stage; inadequate best fit recorded as explained | consistent after S3 (anomaly has its own state machine, no stage); inadequacy now creates UNEXPLAINED (S35-MECH-002) | — |
| S35-PROB-004 | ProblemDiscovery · G-D1, G-D2 · P35-2 · partial | Conflicts, UNKNOWN fields, coverage gaps → problems | admitted evidence only | deterministic | condition-incompatible observations reported as a contradiction | consistent | — |
| S35-HYP-001 | DiscoveryLoop · G6, G-D1 · P35-2 · partial | ideas, hypotheses, claims → stage 1/2/3 | Discovery never writes stage 3; spending authorizes nothing scientific | deterministic | stage on a Registration or Observation; AL3-paid idea counted as evidence; 'zero-cost only' vs AL3 generation | CORRECTED (S3, S4): scope limited to hypotheses and claims; ladder of Appendix E §9 | OD-15 |
| S35-HYP-002 | HypothesisBrain · G-D1, G-D2 · P35-2 · partial | ExploratoryIdea → admitted Hypothesis with identity and verdicts | SAI 3.3 §8 admission gate | deterministic | renamed duplicate admitted as a new mechanism; 'joins that hypothesis's class' under A–B–C | CORRECTED (S1): alias by identity; verdicts, no class | — |
| S35-HYP-003 | ValidationLoop · G6, G-D1 · P35-2 · proposed | canonical events → ClaimStateProjection | projection never writes belief | deterministic | CONFIRMED projected without CWG decision | consistent; projection exists only for hypotheses and claims (S3) | — |
| S35-HYP-004 | HypothesisBrain · G0, G-D1, G-D2 · P35-2 · partial | EvidenceBundle → ideas with InferenceProvenance | no sealed reads; stage-1 output only | deterministic | new out-of-catalog mechanism without typed predictions submitted for admission | consistent; out-of-catalog proposals stay stage 1 (Appendix S §8) | — |
| S35-MECH-001 | MechanismExplorer · G-D1, G-D2, G-D3 · P35-2 · partial | hypotheses, E, τ, replicates → DistinguishabilityGraph and certified diversity | computed by MechanismExplorer; evaluator recomputes from sealed truth for G-D | deterministic | A = 0, B = 0.75, C = 1.50, τ = 1: transitive merge gives 1, raw count 3, correct 2; candidate.3: {0, 0.9, 1.8, 2.7} plus near-duplicate 1.1 raises diversity 2 → 3 | CORRECTED (S1, candidate.3): Appendix S; anti-inflation guarantee removed, diversity descriptive only; S1-CE-1…11 executable | OD-17 |
| S35-MECH-002 | MechanismExplorer · G-D1, G-D2 · P35-2 · partial | failures, residuals, inadequacy → expansion record, AdequacyAssessment | Hypothesis Brain proposals stay stage 1 | deterministic and empirical | true family absent: best-fitting held mechanism endorsed (force-fit 0.40 at budget 12, 0.47 at 24 on d7ec9f2) | CORRECTED (S1, Discovery safety): adequacy before endorsement; abstain/expand/reframe/discriminate/stop | OD-18 |
| S35-REF-001 | ResearchReframing · G-D1, G-D2, G-D3 · P35-2 · partial | failure triggers → typed Reframing | append-only; no belief move | deterministic | inadequacy of every held mechanism has no trigger in the text | consistent: inadequacy is routed through S35-MECH-002 and WIDEN_MECHANISM_SPACE (Appendix C §3.4 updated) | OD-12 |
| S35-REF-002 | ResearchReframing · G-D1, G-D2, G-D3 · P35-2 · partial | failure records → append-only lineage | no reinterpretation of contradicting evidence | deterministic | successor supported by the evidence that contradicted its predecessor | consistent | — |
| S35-REF-003 | ResearchReframing · G-D1, G-D2, G-D3 · P35-2 · partial | reframed hypothesis → new lineage and registration | pre-existing evidence is CITES | deterministic | abandoned branch dropped from denominators | consistent | OD-12 |
| S35-SEL-001 | VerificationPlanner · G-D1, G-D2, G-D3 · P35-2 · partial | surviving mechanisms, verdicts, CostVector → ranked plan | gated experiments wait for authorization | deterministic | 'separates the most surviving classes' undefined under non-transitivity | CORRECTED (S1): value = pairs converted to DISTINGUISHABLE per cost | — |
| S35-SEL-002 | ValidationLoop · G6, G-D1, G-D2 · P35-2 · partial | live explanations → rival closure, neighbourhoods | Validation identity distinct from generator | deterministic | claim for B in the A–B–C chain reported as one class with A and C, or excluding one of them | CORRECTED (S1): pairwise neighbourhood; refutation rule pairwise | — |
| S35-MOD-001 | PhysicalModelBuilder · G1, G9 · P35-6 · proposed | PhysicalModelSpec → typed operation plan, readback | no prebuilt project; UNKNOWN blocks | deterministic, then licensed | missing authoritative parameter filled by solver default | consistent | OD-07 |
| S35-MOD-002 | PhysicalModelBuilder · G1, G8 · P35-6 · proposed | plan → BuildManifest via closed catalog | no model-generated code reaches the solver | deterministic | free text reaching a solver command | consistent | — |
| S35-MOD-003 | ModelQualification · G1, G3, G-D3 · P35-6 · proposed | model family → qualification record | unqualified outputs cannot discriminate | deterministic | 'exploratory' output confused with epistemic stage 1 | CORRECTED (S5 wording): 'exploratory run' label | — |
| S35-SIM-001 | SimulatorWorkers · G2, G8 · P35-7 · blocked | authorized Job → licensed run with checkout/release | Owner authorization or envelope; budget reserved | deterministic offline, then licensed | mock serving a run marked licensed | consistent; blocked on license (no license used) | OD-07 |
| S35-SIM-002 | ModelQualification · G2, G7-SITE, G8 · P35-7 · blocked | product × worker → qualification | per product, per worker | deterministic and licensed | CHARGE qualification enabling MODE | consistent; blocked | OD-07 |
| S35-SIM-003 | SimulatorWorkers · G8 · P35-6 · proposed | typed request + registration + fencing → raw artifacts | worker identity has no belief writes | deterministic | late duplicate callback accepted twice | consistent | — |
| S35-VAL-001 | NumericalValidation · G2, G3 · P35-6 · proposed | registered sweep plan → per-point Runs | registration before run | deterministic | sweep points counted as independent evidence | consistent with S35-EVI-003 | — |
| S35-VAL-002 | NumericalValidation · G3, G-D3 · P35-7 · partial | convergence study → PASS/UNKNOWN/FAIL | solver flag insufficient | deterministic offline, then licensed | oscillating sequence used to discriminate | consistent | — |
| S35-VAL-003 | NumericalValidation · G4, G5, G-D2, G-D3 · P35-2 · partial | claim → per-source uncertainty | no probability for uncalibrated belief | deterministic | combination without independence assumption | consistent | — |
| S35-VAL-004 | PhysicalModelBuilder · G3, G6, G8 · P35-6 · proposed | ModelPatch → child version | mechanism change is a new hypothesis | deterministic | refinement silently swapping the mechanism to remove a residual (a hidden force-fit) | consistent; complements Appendix S §8 | — |
| S35-VAL-005 | PhysicalValidation · G4, G5, G-D4 · P35-8 · blocked | independent references → physical validation | builder does not control scoring | deterministic split checks, empirical acceptance | simulation agreement used as physical validation | consistent; blocked on physical data | OD-08 |
| S35-LOOP-001 | DiscoveryLoop · G6, G8, G-D1 · P35-2 · partial | Discovery vs Validation identities → permission matrix | no sealed reads; no verdict writes | deterministic | Discovery identity writing CONFIRMED | consistent | — |
| S35-LOOP-002 | ValidationLoop · G-D1, G-D2, G-D3 · P35-2 · partial | validation outcomes → FeedbackRecords with disposition | read-only for Discovery | deterministic | residual above threshold silently dropped | consistent; adequacy results flow through AdequacyAssessment | — |
| S35-LOOP-003 | ValidationLoop · G-D1, G-D2, G-D3, G-D4 · P35-2 · partial | insufficient validation → StopRecord | stop is governance success | deterministic and empirical | safe stop before any experiment rendered as completed or as discovery; candidate.3: correct stop counted as identification | CORRECTED (S4, candidate.3): scored as a separate correct abstention | — |
| S35-CWG-001 | CausalWarrantGate · G6, G-D1, G-D2, G-D3, G-D4 · P35-2 · partial | warrants → CONFIRMED | exclusive confirmation authority | deterministic | report generator displaying CONFIRMED without re-derivable decision | consistent | — |
| S35-CWG-002 | CausalWarrantGate · G6, G-D2, G-D4 · P35-4 · partial | signed review → consequential use | independent reviewer; Owner gate | deterministic | envelope or AL level standing in for a signed review; forged signature accepted | consistent; depends on G0 read-path closure (S35-ISSUE-06) | A3 |
| S35-REG-001 | RegistrationRegistry · G0, G6, G-D1 · P35-2 · partial | SelectionDecision → immutable Registration bound to one Job | signed authorization or covering envelope | deterministic | forged authorization accepted on read | consistent; trust root SPEC-ISSUE-018 open (S35-ISSUE-07) | OD-14 |
| S35-REG-002 | RegistrationRegistry · G8, G-D1 · P35-4 · proposed | envelope bounds → automatic registration | Owner-signed envelope; physical/publication never inside | deterministic | registration just outside a bound accepted | consistent | OD-14, OD-15 |
| S35-REG-003 | RegistrationRegistry · G6, G-D1 · P35-4 · proposed | envelope registration → CITES for post-screening hypotheses | envelope never replaces a per-hypothesis signature | deterministic | SUPPORTS whose only authorization is an envelope | CLARIFIED (S4): explicit sentence; OD-14 default kept | OD-14 |
| S35-REG-004 | ValidationLoop · G0, G6, G-D1 · P35-2 · partial | evidence lineage → SUPPORTS or CITES | 011p/011s rules at least | deterministic | evidence predating registration used as support | consistent | — |
| S35-NOV-001 | NoveltyAuditor · G-D2, G-D3, G-D4 · P35-2 · partial | PriorArtSearchRecord → bounded novelty | PUBLIC queries only | deterministic | novelty broader than coverage | consistent | OD-11 |
| S35-NOV-002 | NoveltyAuditor · G-D2, G-D3, G-D4 · P35-5 · proposed | finding, prior-art mechanisms → novelty class | Novelty Auditor; blinded reviewers at G-D2+ | deterministic and blinded review | renamed prior-art mechanism classed as new; unresolved comparison classed as new | CORRECTED (S1): identity and certified verdicts | OD-11, OD-17 |
| S35-NOV-003 | NoveltyAuditor · G0, G-D2 · P35-5 · partial | authorized adapters → pinned passages | egress gate | deterministic | provider outage omitted from limitations | consistent | — |
| S35-EVI-001 | ValidationLoop · G6, G-D1 · P35-2 · partial | discovery outputs → admission path | proposals are not evidence | deterministic | idea submitted as an Observation | consistent | — |
| S35-EVI-002 | GovernancePlane · G0, G6, G-D1 · P35-2 · partial | discovery records → provenance | record without provenance cannot justify a transition | deterministic | DistinguishabilityGraph without inputs by hash | CORRECTED (S1 record names) | — |
| S35-EVI-003 | ValidationLoop · G4, G6, G-D2 · P35-2 · partial | evidence → independent count | shared families count once | deterministic | three runs of one model counted three times | consistent | — |
| S35-EVI-004 | EvaluationPlane · G4, G-D1, G-D2 · P35-3 · partial | sealed material → audited reads | evaluation plane only | deterministic | route that read an answer still counted independent | consistent | — |
| S35-RPT-001 | ReportGenerator · G0, G9, G-D2 · P35-4 · partial | canonical records → zh-TW/en report | translation never overwrites canonical | deterministic and bilingual review | 'epistemic stage of every object' (no stage for most records) | CORRECTED (S3, S1, S4): stage for hypotheses and claims, verdicts and bounds, termination dimensions | OD-13 |
| S35-RPT-002 | ReportGenerator · G7-SITE, G9, G-D1 · P35-4 · partial | report → re-derivable bundle | independent re-derivation | deterministic | bundle without realized-cost traces needed to re-score checkpoints | consistent: 'budgets and realized consumption' covers attempt traces; Appendix J §3.3 needs them | — |
| S35-RPT-003 | ReportGenerator · G0, G9 · P35-4 · proposed | glossary → canonical zh-TW terms | state names untranslated | deterministic | one English term with two zh-TW terms | consistent; candidate.2 terms added to the glossary | OD-13 |
| S35-RPT-004 | ResearcherWorkspace · G0, G9 · P35-4 · partial | workspace → stages, states, budgets, stops | approvals are ReviewItem resolutions | deterministic | unperformed step shown green; stage shown on a problem | CORRECTED (S3) | — |
| S35-AUTO-001 | DeploymentOperations · G9, G-D3 · P35-4 · untested | deployment → full workflow without coding agents | coding-agent endpoints blocked | empirical acceptance check | workflow pausing for a developer to write model code | consistent | — |
| S35-AUTO-002 | DeploymentOperations · G8, G9 · P35-4 · untested | release image → audit | no development credentials in production | deterministic | coding-agent package in the image | consistent | — |
| S35-AUTO-003 | CampaignOrchestrator · G9 · P35-4 · proposed | out-of-envelope request → stop and ReviewItem | never widens own envelope | deterministic | stop that asks a developer to continue | consistent | — |
| S35-SEC-001 | GovernancePlane · G8, G9 · P35-4 · proposed | project → autonomy level | level ≤ Owner maximum; never confirmation | deterministic | AL3 model call treated as producing evidence | CORRECTED (S4): levels authorize actions and spending only | OD-15 |
| S35-SEC-002 | GovernancePlane · G8, G-D1, G-D3, G-D4 · P35-4 · partial | action classes → Owner gates | automation never signs; timeout never consent | deterministic | physical experiment citing only an envelope | consistent; PROB-001 aligned | OD-05, OD-07, OD-08 |
| S35-SEC-003 | GovernancePlane · G8, G-D1 · P35-2 · partial | records → project scope | sealed material evaluation-only | deterministic | cross-project cache key | consistent | — |
| S35-SEC-004 | GovernancePlane · G0, G8, G-D0 · P35-2 · partial | accounts → ADMIN/MEMBER only | second accounts never independent | deterministic | reviewer status granting a role | consistent; A3 open | A3 |
| S35-SEC-005 | GovernancePlane · G8 · P35-2 · proposed | identity × record class → allow/deny at DB | database rules, not only app checks | deterministic | superuser bypass | consistent; A12 open; services share one role today | A12 |
| S35-SEC-006 | GovernancePlane · G8 · P35-4 · proposed | Owner stop → cancellation before next side effect | checked at reservation and dispatch | deterministic | dispatch after revocation | consistent | — |
| S35-COST-001 | CostGovernance · G8, G-D1 · P35-2 · partial | attempts → maximum-cost reservations, then settlements | no endpoint presumed free | deterministic | failed retry missing from ledger; settlement above reservation absorbed silently | CORRECTED (candidate.3): reservation is the maximum cost; overrun is an incident; feeds Appendix J §3.4 | SPEC-ISSUE-017 |
| S35-COST-002 | CostGovernance · G8 · P35-4 · partial | ceilings → stop reservations | raise only by Owner | deterministic | automatic ceiling increase on timeout | consistent | — |
| S35-GD-001 | EvaluationPlane · G-D0, G-D1, G-D2, G-D3, G-D4 · P35-3 · blocked | verdict records → independent evaluator | implementer cannot sign | deterministic | implementer-signed G-D verdict | consistent; blocked on OD-02 | OD-02 |
| S35-GD-002 | EvaluationPlane · G-D0, G-D1, G-D2, G-D3, G-D4 · P35-3 · blocked | levels → frozen protocols | protocol hash | deterministic | protocol edited after freezing | consistent; frozen protocol now includes the checkpoint ladder and τ | OD-03, OD-17 |
| S35-GD-003 | EvaluationPlane · G-D2, G-D3, G-D4 · P35-3 · proposed | G-D vs G gates → prerequisites | no substitution | deterministic | G-D1 result cited as G0 evidence | consistent | — |
| S35-CMP-001 | EvaluationPlane · G-D1, G-D2, G-D3, G-D4 · P35-3 · partial | three arms → same model and schema | arm configs differ only in listed components | deterministic | arm A given a larger model | consistent | OD-04, OD-05 |
| S35-CMP-002 | EvaluationPlane · G-D1, G-D2, G-D3, G-D4 · P35-3 · partial | arm traces, frozen ladder → answers at checkpoints or COST_UNMATCHED | evaluator owns ladder and tolerance; runtime enforces reservations | deterministic | early-stopping arm moves the comparison point; straddling experiment credited; hidden retries; candidate.3: variable-cost model call whose cost is unknown at start; overrun; start without reservation headroom | CORRECTED (S2, candidate.3): reservation before execution, settlement after, retrospective checkpoints; S2-CE-1…10 executable | OD-03 |
| S35-CMP-003 | EvaluationPlane · G-D1, G-D2, G-D3, G-D4 · P35-3 · proposed | outputs → sealed labels, frozen scorer | custodian holds labels | deterministic | scorer hash drift | consistent | OD-02 |
| S35-CMP-004 | EvaluationPlane · G-D0, G-D1, G-D2, G-D3, G-D4 · P35-3 · proposed | evaluator generator → sealed worlds | implementer cannot read truth | deterministic | implementer-written worlds used as G-D evidence (the P3 situation) | consistent; P3 results remain engineering evidence | OD-02 |
| S35-CMP-005 | EvaluationPlane · G-D1, G-D2, G-D3, G-D4 · P35-3 · partial | frozen outputs → five metrics; nine outcome categories | scorer frozen | deterministic | 'equivalence class' credit under A–B–C; candidate.3: indistinguishable alternative counted as exact; correct stop folded into true-cause discovery; unvalidated proposal counted as discovery | CORRECTED (S1, S2, candidate.3): separate outcome categories (Appendix S §6, S3-CE); diversity descriptive only | OD-03, OD-17 |
| S35-CMP-006 | EvaluationPlane · G-D0, G-D1, G-D2, G-D3, G-D4 · P35-3 · partial | protocol → pre-registered statistics | analysis reads frozen values only | deterministic | primary checkpoint chosen after unsealing | consistent; ladder is pre-registered (S2) | OD-03 |
| S35-CMP-007 | EvaluationPlane · G-D0, G-D1, G-D2 · P35-3 · partial | cases → contamination report | exclusions by frozen rule | deterministic | silent exclusion | consistent | OD-06 |
| S35-CMP-008 | EvaluationPlane · G-D1, G-D2, G-D3, G-D4 · P35-3 · partial | caps, incidents → case/study stops | incidents invalidate | deterministic | case cut at cap credited with a straddling experiment; an operation started whose reservation exceeds the remaining cap | CORRECTED (S2, candidate.3) | OD-03 |
| S35-CMP-009 | EvaluationPlane · G-D1, G-D2 · P35-3 · partial | stage order → zero-cost first | paid stage needs Owner authorization | deterministic | negative zero-cost result overridden by a bigger model | consistent | OD-04, OD-05 |

## 4. Residual issues not resolved by text

- Exact diversity computation is exponential in the number of held mechanisms; OD-17 fixes the
  campaign size above which only certified bounds are reported.
- The adequacy criterion (OD-18) and the threshold τ (OD-17) are policy values; a poor choice can
  make the system abstain too often or too rarely. Both are frozen before G-D0 and never tuned on
  sealed cases.
- The forged-authorization read-path closure (S35-ISSUE-06) and the trust roots SPEC-ISSUE-017/018/019
  (S35-ISSUE-07) remain open; S35-REG-001, S35-REG-003 and S35-CWG-002 depend on them.
- Nothing in this report is runtime or scientific evidence; every requirement's status is
  unchanged by it unless the [implementation status](implementation-status.md) says otherwise.
