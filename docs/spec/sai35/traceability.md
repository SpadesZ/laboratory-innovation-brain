# SAI 3.5 Discovery Candidate — Traceability to SAI 3.4, SAI 3.3 and G0–G9

Version: `3.5.0-discovery-candidate.1`.
Status: **CANDIDATE — NOT ACTIVE.** This page shows how SAI 3.5 relates to the existing
specifications. It changes none of them. `READY_FOR_REAL_RESEARCH = false`.

## 1. What stays exactly as it is

| Item | State | How it is held |
|---|---|---|
| [ACTIVE_SPEC.yaml](../ACTIVE_SPEC.yaml) | unchanged; still names SAI 3.4 `3.4.0-phased.1` and the SAI 3.3 executable profile | SHA-256 and field values checked by [check_candidate.py](check_candidate.py) |
| [SAI 3.3](../SAI_3.3.md), [active registry](../../normative_statements.yaml), [milestones](../../milestones.yaml) | unchanged; 60 requirements and tests, M0a–M8 | SHA-256 checked here and by the SAI 3.4 checkers |
| [SAI 3.4 phased basis](../SAI_3.4.md) and every file in `docs/spec/sai34/` | unchanged; ASM-001–018, G0–G9, D-01–D-08 | SHA-256 checked here |
| [SAI 3.4 candidate](../SAI_3.4_Candidate.md), [architecture](../../architecture/sai34-autonomous-modeling.md), [ADR-0013](../../adr/ADR-0013-autonomous-scientific-modeling-candidate.md), [ADR-0014](../../adr/ADR-0014-phased-sai34-activation.md) | unchanged | SHA-256 checked here |
| G0 status | NOT PASSED | not affected by this candidate |
| Owner decisions D-01–D-08, G0 decisions A–F, security decisions A3/A9/A12 | OPEN | not affected by this candidate |

## 2. Section relation

| SAI 3.5 section | Builds on | Relation |
|---|---|---|
| §0 Status and authority | SAI 3.4 §1, §4; SAI 3.3 §0 | additive; conflicts follow AGT-015 (D-001) |
| §1 Product vision | SAI 3.4 candidate §1 (ASM-001) | widens the long-term target from autonomous modeling to autonomous discovery; adds claim discipline |
| §2 End-to-end architecture | SAI 3.4 candidate §1–§10; architecture contract §1–§4 | reuses the ASM chain unchanged and adds discovery stages before and around it |
| §3 Discovery Loop | SAI 3.3 §8 (hypotheses), §9 (least-cost verification) | new; uses admission, typed predictions and sufficiency as they are |
| §4 Discovery and validation | SAI 3.3 §8.2, §17.13; Causal Warrant Gate V1.1; SAI 3.4 ASM-010, ASM-013 | new role separation and claim-state projection; the CWG stays the only path to CONFIRMED |
| §5 Oversight and governance | SAI 3.3 §14; SAI 3.4 ASM-014 | adds the four Owner gate classes for discovery; roles unchanged |
| §6 G-D framework | SAI 3.4 acceptance (G0–G9) | separate framework; neither substitutes for the other |
| §7 Matched-budget comparison | SAI 3.3 §15; SAI 3.4 acceptance §4 | new evaluation protocol for discovery |
| §8 Non-goals and falsification | — | new |
| §9 Activation boundary | SAI 3.4 §4 (P-FULL-RUNTIME) | activation would need its own decision and migration |

## 3. G0–G9 and G-D

| G gate | Role for G-D | Never means |
|---|---|---|
| G0 | entry condition for G-D2 (the product configuration evaluated must have G0 accepted) | that discovery works |
| G1, G2, G3 | entry conditions for G-D3 for the model family | that the system found a new mechanism |
| G4, G5, G6 | entry conditions for G-D4 for the scope | that a mechanism was discovered prospectively |
| G7-SITE | entry condition for G-D3 and G-D4 | cross-worker or cross-site discovery |
| G7-WORKER | only when a cross-worker discovery claim is made | — |
| G8 | licensed parts are entry conditions for G-D3 | — |
| G9 | none directly; T-D-006 and G9 both test the absence of external coding agents and can share evidence, but each issues its own result | that the product discovers |

Completing all of G0–G9 never implies any G-D level (D-035). No G-D result changes any G gate
(D-037).

## 4. Requirement mapping

`related_sai34` names the ASM obligations each D-NNN builds on. `related_sai33` names inherited
SAI 3.3 requirements it relies on. Neither field changes those requirements. The G-D column lists
the levels whose evidence would show the requirement in operation. The phase is the
[roadmap](roadmap.md) phase where it is first needed.

| D-NNN | Key | § | SAI 3.4 ASM | SAI 3.3 requirements | G-D levels | Phase |
|---|---|---|---|---|---|---|
| D-001 | `candidate.additive` | §0 | ASM-018 | TST-002, TST-003 | G-D0 | D0 |
| D-002 | `vision.target` | §1 | ASM-001, ASM-002 | SYS-001 | G-D1, G-D2, G-D3, G-D4 | D0 |
| D-003 | `vision.claim_discipline` | §1 | ASM-018 | UX-006 | G-D0, G-D1, G-D2, G-D3, G-D4 | D0 |
| D-004 | `vision.novelty_falsifiability` | §1 | ASM-003 | SRC-003, VER-004, VER-006 | G-D2, G-D3, G-D4 | D2 |
| D-005 | `e2e.chain` | §2 | ASM-002, ASM-017 | SYS-001, OPS-001, OPS-003 | G-D1, G-D2, G-D3 | D2 |
| D-006 | `autonomy.no_external_coding_agent` | §2 | ASM-001 | SIM-003 | G-D3, G-D4 | D4 |
| D-007 | `e2e.literature` | §2 | ASM-003 | SRC-001, SRC-002, SEC-001, SEC-004 | G-D2 | D3 |
| D-008 | `e2e.model_from_scratch` | §2 | ASM-004, ASM-005 | SIM-003, EVI-002 | G-D3 | D4 |
| D-009 | `e2e.licensed_internal_workers` | §2 | ASM-006, ASM-007, ASM-015 | TST-001, COST-001, OPS-001, SIM-001 | G-D3, G-D4 | D4 |
| D-010 | `e2e.sweeps` | §2 | ASM-002, ASM-012 | EVI-009, SIM-001 | G-D3 | D4 |
| D-011 | `e2e.convergence` | §2 | ASM-008 | SIM-002 | G-D3 | D4 |
| D-012 | `e2e.refinement` | §2 | ASM-011 | EPI-005 | G-D3 | D4 |
| D-013 | `e2e.physical_validation` | §2 | ASM-009, ASM-010 | EVI-004, DOM-SP-002 | G-D4 | D5 |
| D-014 | `e2e.bilingual_report` | §2 | ASM-016 | UX-006 | G-D2, G-D3, G-D4 | D2 |
| D-015 | `loop.problem_discovery` | §3 | ASM-014 | SEC-001, SEC-002 | G-D1, G-D2 | D1 |
| D-016 | `loop.mechanism_classes` | §3 | — | EPI-001, LLM-002 | G-D1, G-D2, G-D3 | D1 |
| D-017 | `loop.mechanism_class_definition` | §3 | — | VER-006, VER-008 | G-D1, G-D2, G-D3 | D1 |
| D-018 | `loop.anomaly_state` | §3 | ASM-012, ASM-013 | EPI-003, EPI-006 | G-D1, G-D2, G-D3 | D1 |
| D-019 | `loop.reframing` | §3 | ASM-011, ASM-012 | EPI-003, EPI-005 | G-D1, G-D2, G-D3 | D1 |
| D-020 | `loop.reframing_accounting` | §3 | ASM-010 | EPI-003 | G-D1, G-D2, G-D3 | D1 |
| D-021 | `loop.experiment_selection` | §3 | ASM-002 | VER-001, VER-002, VER-003, VER-005 | G-D1, G-D2, G-D3 | D1 |
| D-022 | `loop.termination` | §3 | ASM-007, ASM-011 | COST-001 | G-D1, G-D2, G-D3 | D1 |
| D-023 | `validation.role_separation` | §4 | ASM-010, ASM-013 | SEC-002, EPI-005 | G-D1, G-D2, G-D3, G-D4 | D2 |
| D-024 | `validation.preregistration` | §4 | ASM-010 | VER-006, EPI-005 | G-D1, G-D2, G-D3, G-D4 | D2 |
| D-025 | `validation.no_retrospective_self_support` | §4 | ASM-012, ASM-013 | EVI-004, EVI-009, EPI-002 | G-D1, G-D2, G-D3, G-D4 | D2 |
| D-026 | `validation.cwg_only_confirmed` | §4 | ASM-013 | EPI-002, EPI-004, EPI-005 | G-D1, G-D2, G-D3, G-D4 | D2 |
| D-027 | `validation.epistemic_states` | §4 | ASM-013, ASM-018 | EPI-003, EPI-005, SYS-001 | G-D1, G-D2, G-D3, G-D4 | D2 |
| D-028 | `validation.stop_insufficient` | §4 | ASM-011, ASM-018 | EPI-001 | G-D1, G-D2, G-D3, G-D4 | D1 |
| D-029 | `validation.uncertainty` | §4 | ASM-008, ASM-009, ASM-016 | EVI-001, EVI-002 | G-D2, G-D3, G-D4 | D2 |
| D-030 | `oversight.owner_gates` | §5 | ASM-007, ASM-014 | COST-001, OPS-002, SEC-002 | G-D1, G-D2, G-D3, G-D4 | D2 |
| D-031 | `oversight.evidence_governance` | §5 | ASM-012 | EVI-003, EVI-009, SYS-001 | G-D1, G-D2, G-D3, G-D4 | D2 |
| D-032 | `oversight.provenance` | §5 | ASM-002, ASM-017 | LLM-001, OPS-003, ART-001 | G-D1, G-D2, G-D3, G-D4 | D2 |
| D-033 | `oversight.project_isolation` | §5 | ASM-014 | SEC-002 | G-D1, G-D2, G-D3, G-D4 | D2 |
| D-034 | `oversight.accounts` | §5 | ASM-014 | SEC-002 | G-D0, G-D2, G-D4 | D0 |
| D-035 | `gd.independence` | §6 | ASM-018 | TST-003 | G-D0, G-D1, G-D2, G-D3, G-D4 | D0 |
| D-036 | `gd.levels` | §6 | ASM-018 | LLM-002 | G-D0, G-D1, G-D2, G-D3, G-D4 | D0 |
| D-037 | `gd.no_substitution` | §6 | ASM-018 | — | G-D2, G-D3, G-D4 | D0 |
| D-038 | `compare.three_arms` | §7 | — | LLM-002 | G-D1, G-D2, G-D3, G-D4 | D1 |
| D-039 | `compare.matching` | §7 | — | COST-001, VER-003 | G-D1, G-D2, G-D3, G-D4 | D1 |
| D-040 | `compare.blinding` | §7 | ASM-010 | — | G-D1, G-D2, G-D3, G-D4 | D1 |
| D-041 | `compare.benchmark` | §7 | ASM-010 | LLM-002 | G-D0, G-D1, G-D2, G-D3, G-D4 | D0 |
| D-042 | `compare.metrics` | §7 | ASM-017 | LLM-002 | G-D1, G-D2, G-D3, G-D4 | D1 |
| D-043 | `compare.statistics` | §7 | — | LLM-002 | G-D0, G-D1, G-D2, G-D3, G-D4 | D0 |
| D-044 | `compare.contamination` | §7 | ASM-010 | EVI-004 | G-D0, G-D1, G-D2 | D0 |
| D-045 | `compare.stopping` | §7 | ASM-007 | COST-001 | G-D1, G-D2, G-D3, G-D4 | D1 |
| D-046 | `compare.zero_cost_first` | §7 | ASM-007, ASM-018 | COST-001 | G-D1, G-D2 | D1 |

## 5. Namespaces

| Namespace | Meaning | Defined in |
|---|---|---|
| `D-001`…`D-046` | SAI 3.5 candidate requirements | this candidate |
| `T-D-001`…`T-D-046` | planned tests (obligations, not evidence) | [registry](normative-statements.yaml) |
| `G-D0`…`G-D4` | discovery acceptance levels | [acceptance-gd.md](acceptance-gd.md) |
| `D0`…`D6` | SAI 3.5 roadmap phases | [roadmap.md](roadmap.md) |
| `OD-01`…`OD-13` | SAI 3.5 Owner decisions | [decisions-and-review.md](decisions-and-review.md) |
| `D-01`…`D-08` | SAI 3.4 Owner decisions (unchanged) | [SAI 3.4 decisions](../sai34/decisions-and-review.md) |
| `ASM-001`…`ASM-018`, `G0`…`G9` | SAI 3.4 obligations and gates (unchanged) | [SAI 3.4 candidate](../SAI_3.4_Candidate.md) |
