# SAI 3.5 — Change register (D-NNN → S35 identifiers)

Version: `3.5.0-master-candidate.1`. Status: **CANDIDATE — NOT ACTIVE.** `READY_FOR_REAL_RESEARCH = false`.
Authority: informative record, enforced by the [candidate checker](check_candidate.py): every
retired `D-NNN` appears here, every new identifier it names is registered, and the counts below are
recomputed from this table and the [registry](normative-statements.yaml).

## 1. Identifier scheme

SAI 3.5 requirements are named `S35-<AREA>-NNN` (three digits), for example `S35-GOV-001`. The
prefix `S35-` cannot be confused with SAI 3.4's Owner decisions `D-01`…`D-08` (two digits), with
SAI 3.3 requirement families (`EPI-001`, `SEC-002`, …), with SAI 3.4 obligations (`ASM-001`…`ASM-018`)
or with the retired candidate IDs `D-001`…`D-046`. Planned tests are `T-S35-<AREA>-NNN`. Areas:

| Area | Section of [SAI 3.5](../SAI_3.5.md) | Scope |
|---|---|---|
| GOV | §3.1 | Governance of this specification |
| LIFE | §3.2 | Research lifecycle |
| PROB | §3.3 | Problem discovery |
| HYP | §3.4 | Hypotheses and epistemic stages |
| MECH | §3.5 | Mechanism space |
| REF | §3.6 | Research Reframing |
| SEL | §3.7 | Competing explanations and experiment selection |
| MOD | §3.8 | Physical model construction |
| SIM | §3.9 | Licensed simulation on internal workers |
| VAL | §3.10 | Sweeps, convergence, uncertainty, refinement and physical validation |
| LOOP | §3.11 | Discovery–Validation feedback loop |
| CWG | §3.12 | Confirmation authority |
| REG | §3.13 | Prospective registration and the research envelope |
| NOV | §3.14 | Novelty and prior art |
| EVI | §3.15 | Evidence, provenance, independence and contamination |
| RPT | §3.16 | Reports and researcher experience |
| AUTO | §3.17 | Production autonomy without external coding agents |
| SEC | §3.18 | Identity, permissions, autonomy levels and Owner authority |
| COST | §3.19 | Cost governance |
| GD | §3.20 | G-D acceptance |
| CMP | §3.21 | Matched-budget comparison |

The retired `D-001`…`D-046` keep their historical meaning in the superseded
[discovery candidate](../SAI_3.5_Discovery_Candidate.md). No runtime code, test or report may use
them. Roadmap phases are `P35-0`…`P35-9` (the earlier `D0`…`D6` phase names are retired too).

## 2. Summary

| Action | Old requirements | Meaning |
|---|---|---|
| kept | 19 | meaning unchanged; new identifier, at most editorial wording |
| refined | 19 | same obligation, made precise or extended; one new identifier |
| split | 5 | one old requirement became two or more requirements with separate tests |
| merged | 2 | two or more old requirements became one |
| replaced | 1 | superseded by a requirement with a different scope |
| removed | 0 | dropped with a reason; no successor |

Totals: **46 old requirements → 77 SAI 3.5 requirements.** 50 identifiers carry
old content (one per kept or refined requirement, one or more per split, one per merge or
replacement); **27 requirements are new**. The count was not preserved: requirements were
split, merged or added wherever an external implementation agent needed a separate, testable
obligation.

## 3. Old → new

| Old | Old key | Action | New | Reason |
|---|---|---|---|---|
| D-001 | `candidate.additive` | refined | S35-GOV-001 | States precedence (inherited text wins until activation), the spec-issue register and a byte-identity acceptance test with no exception. |
| D-002 | `vision.target` | replaced | S35-GOV-002 | Replaced by the twelve-capability target CAP-01..CAP-12, each mapped to requirements and gates. |
| D-003 | `vision.claim_discipline` | refined | S35-GOV-004 | Extends the rule to every capability claim, names evidence paths at commits, and adds the synthetic-benchmark rule. |
| D-004 | `vision.novelty_falsifiability` | split | S35-HYP-002, S35-NOV-001 | Falsifiability and mechanistic admission go to S35-HYP-002; prior-art bounding goes to S35-NOV-001; novelty classes are new in S35-NOV-002. |
| D-005 | `e2e.chain` | refined | S35-LIFE-001 | Binds to the lifecycle appendix stage list, adds campaign binding and a fault-injection acceptance test; campaign states are new (S35-LIFE-002). |
| D-006 | `autonomy.no_external_coding_agent` | split | S35-AUTO-001, S35-AUTO-002 | Runtime independence with its acceptance check (S35-AUTO-001) and static deployment composition audit (S35-AUTO-002); safe out-of-envelope stop is new (S35-AUTO-003). |
| D-007 | `e2e.literature` | kept | S35-NOV-003 | Meaning unchanged; moved to the novelty and prior-art area under a new ID. |
| D-008 | `e2e.model_from_scratch` | split | S35-MOD-001, S35-MOD-002 | From-scratch construction (S35-MOD-001) and the governed typed operation catalog (S35-MOD-002); model qualification is new (S35-MOD-003). |
| D-009 | `e2e.licensed_internal_workers` | split | S35-SIM-001, S35-SIM-002 | Governed licensed execution (S35-SIM-001) and per-product, per-worker qualification (S35-SIM-002); worker contract is new (S35-SIM-003). |
| D-010 | `e2e.sweeps` | kept | S35-VAL-001 | Meaning unchanged; new ID. |
| D-011 | `e2e.convergence` | kept | S35-VAL-002 | Meaning unchanged; new ID. |
| D-012 | `e2e.refinement` | kept | S35-VAL-004 | Meaning unchanged; adds the cross-reference to novelty classes. |
| D-013 | `e2e.physical_validation` | kept | S35-VAL-005 | Meaning unchanged; new ID. |
| D-014 | `e2e.bilingual_report` | refined | S35-RPT-001 | Adds the missing content classes and the parity and bilingual-review acceptance; reproducible bundle, glossary and UX are new (S35-RPT-002..004). |
| D-015 | `loop.problem_discovery` | refined | S35-PROB-001 | Adds origins and allows envelope coverage instead of only per-problem acceptance; valuation and contradiction/gap detection are new (S35-PROB-002, S35-PROB-004). |
| D-016 | `loop.mechanism_classes` | merged | S35-MECH-001 | Merged with D-017: the metric and its class definition are one obligation with one test. |
| D-017 | `loop.mechanism_class_definition` | merged | S35-MECH-001 | Merged with D-016 and made precise: worst case over the whole parameter ranges, declared replicates, pre-registered threshold. |
| D-018 | `loop.anomaly_state` | refined | S35-PROB-003 | Union of the candidate and prototype state sets with an explicit transition table. |
| D-019 | `loop.reframing` | refined | S35-REF-002 | Keeps the failure-history obligation and extends links to assumptions, observables and models; triggers and kinds are new (S35-REF-001). |
| D-020 | `loop.reframing_accounting` | kept | S35-REF-003 | Meaning unchanged; new ID. |
| D-021 | `loop.experiment_selection` | refined | S35-SEL-001 | Assigns the Verification Planner and a versioned weighting policy; independent evaluation of competing explanations is new (S35-SEL-002). |
| D-022 | `loop.termination` | refined | S35-LIFE-003 | Binds termination to the campaign states and extends the budget dimensions. |
| D-023 | `validation.role_separation` | refined | S35-LOOP-001 | Names the Discovery-side components and adds the permission-matrix acceptance; the matrix itself is S35-SEC-005. |
| D-024 | `validation.preregistration` | refined | S35-REG-001 | Binds one Job and the declaration hash and allows a covering envelope as the authorization route; envelope rules are new (S35-REG-002, S35-REG-003). |
| D-025 | `validation.no_retrospective_self_support` | refined | S35-REG-004 | Names the 011s rules (a)–(k) at f41758c and the eleven defect fixtures as acceptance. |
| D-026 | `validation.cwg_only_confirmed` | refined | S35-CWG-001 | Makes the gate the exclusive authority for writing and displaying CONFIRMED; consequential authorization is new (S35-CWG-002). |
| D-027 | `validation.epistemic_states` | split | S35-HYP-001, S35-HYP-003 | The three epistemic stages (S35-HYP-001) and the claim-state projection with transitions (S35-HYP-003). |
| D-028 | `validation.stop_insufficient` | kept | S35-LOOP-003 | Meaning unchanged; new ID. |
| D-029 | `validation.uncertainty` | kept | S35-VAL-003 | Meaning unchanged; adds the combination rule already in SAI 3.4 acceptance §3. |
| D-030 | `oversight.owner_gates` | refined | S35-SEC-002 | Allows envelope pre-authorization for money and licenses within ceilings; physical experiments and publication stay per action. |
| D-031 | `oversight.evidence_governance` | kept | S35-EVI-001 | Meaning unchanged; new ID. |
| D-032 | `oversight.provenance` | kept | S35-EVI-002 | Meaning unchanged; record list extended. |
| D-033 | `oversight.project_isolation` | kept | S35-SEC-003 | Meaning unchanged; new ID. |
| D-034 | `oversight.accounts` | kept | S35-SEC-004 | Meaning unchanged; new ID. |
| D-035 | `gd.independence` | refined | S35-GD-001 | Adds that synthetic benchmark success is never reported as real discovery validation and that a second account of the implementer is excluded. |
| D-036 | `gd.levels` | kept | S35-GD-002 | Meaning unchanged; new ID. |
| D-037 | `gd.no_substitution` | kept | S35-GD-003 | Meaning unchanged; new ID. |
| D-038 | `compare.three_arms` | refined | S35-CMP-001 | Names arm A as the single frontier LLM, defines the model per stage, and states that B0 is not arm A. |
| D-039 | `compare.matching` | refined | S35-CMP-002 | Matches on actual realized consumption with a pre-registered rule and COST_UNMATCHED label, and adds information exposure and experimental conditions. |
| D-040 | `compare.blinding` | kept | S35-CMP-003 | Meaning unchanged; new ID. |
| D-041 | `compare.benchmark` | refined | S35-CMP-004 | Requires an evaluator-owned hidden-world generator and excludes implementer-written worlds from G-D evidence. |
| D-042 | `compare.metrics` | refined | S35-CMP-005 | Renamed to the requested five metrics: true-cause discovery, effective mechanism diversity, discriminating-experiment efficiency, false discoveries, independent reproducibility. |
| D-043 | `compare.statistics` | kept | S35-CMP-006 | Meaning unchanged; new ID. |
| D-044 | `compare.contamination` | kept | S35-CMP-007 | Meaning unchanged; new ID. |
| D-045 | `compare.stopping` | kept | S35-CMP-008 | Meaning unchanged; new ID. |
| D-046 | `compare.zero_cost_first` | kept | S35-CMP-009 | Meaning unchanged; new ID. |

## 4. New requirements (no old counterpart)

| New | Key | Reason |
|---|---|---|
| S35-GOV-003 | `gov.product_category` | Capability 'not a summarizer, chatbot, simulation launcher or hypothesis-review assistant' had no testable statement. |
| S35-GOV-005 | `gov.not_active` | The old activation boundary (§9) was prose without an ID or test; activation needs Independent Chief Auditor review and Owner approval. |
| S35-LIFE-002 | `life.campaign_states` | No campaign state machine existed; an implementation agent could not build the orchestrator. |
| S35-PROB-002 | `prob.valuation` | Capability 1 asks for valuable problems; no valuation rule existed. |
| S35-PROB-004 | `prob.contradictions_gaps` | Capability 1 names contradictions and knowledge gaps; no detection rule existed. |
| S35-HYP-004 | `hyp.generation` | The Hypothesis Brain had no contract: inputs, provenance, sealed-material exclusion, new-mechanism proposals. |
| S35-MECH-002 | `mech.search_space_expansion` | Capability 3 (explore alternative mechanisms, expand the effective search space) had no statement. |
| S35-REF-001 | `ref.triggers_and_kinds` | Capability 4 names assumption, observable, model and hypothesis failures; only hypothesis failure was a trigger. |
| S35-SEL-002 | `sel.competing_explanations` | Capability 5 asks for independent evaluation of competing explanations; rival closure was only in the prototype. |
| S35-MOD-003 | `mod.qualification` | The model qualification component had no requirement. |
| S35-SIM-003 | `sim.worker_contract` | The worker execution contract (registration binding, fencing, raw outputs only) was missing. |
| S35-LOOP-002 | `loop.feedback` | Capability 9 requires validation results, anomalies, failures and residual structure to feed back to Discovery. |
| S35-CWG-002 | `cwg.consequential_authorization` | Consequential conclusions needed an explicit independent-authorization rule that no envelope can satisfy. |
| S35-REG-002 | `reg.envelope_registration` | Automatic prospective registration within an Owner-approved research envelope was required and absent. |
| S35-REG-003 | `reg.envelope_limits` | Automatic registration must not weaken independent authorization of consequential conclusions. |
| S35-NOV-002 | `nov.classification` | Findings must distinguish rediscovery, engineering optimization, model correction and new physical knowledge. |
| S35-EVI-003 | `evi.independence` | Evidence independence for discovery claims (model families, shared assumptions) was implicit. |
| S35-EVI-004 | `evi.contamination` | Contamination defenses existed only for evaluation, not for production research. |
| S35-RPT-002 | `rpt.reproducible_bundle` | Capability 10 asks for reproducible reports; no report bundle was specified. |
| S35-RPT-003 | `rpt.terminology_language` | A bilingual glossary and language rule were required. |
| S35-RPT-004 | `rpt.researcher_ux` | The researcher UX had no requirement. |
| S35-AUTO-003 | `auto.out_of_envelope_stop` | Out-of-envelope requests had no safe-stop rule for production autonomy. |
| S35-SEC-001 | `sec.autonomy_levels` | Autonomy levels were required and absent. |
| S35-SEC-005 | `sec.least_privilege` | Permissions had no least-privilege matrix; services share one database role today. |
| S35-SEC-006 | `sec.owner_stop` | Owner authority lacked an immediate stop and revocation rule. |
| S35-COST-001 | `cost.realized_consumption` | Realized consumption (not only caps) must be recorded for cost governance and for the A/B/C comparison. |
| S35-COST-002 | `cost.ceilings` | Campaign and envelope ceilings were missing. |

## 5. Other identifiers

| Earlier | Now | Note |
|---|---|---|
| `T-D-001`…`T-D-046` | `T-S35-<AREA>-NNN` | planned tests, never executed evidence |
| roadmap `D0`…`D6` | `P35-0`…`P35-9` | see [roadmap](roadmap.md) |
| `OD-01`…`OD-13` | `OD-01`…`OD-16` | meanings of OD-01…OD-13 kept (OD-10 rewritten for proposal A'); OD-14…OD-16 new |
| `3.5.0-discovery-candidate.1` | `3.5.0-master-candidate.1` | version of the candidate |
