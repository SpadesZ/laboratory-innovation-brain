# SAI 3.5 — Appendix M: Compatibility with SAI 3.3 and SAI 3.4

Version: `3.5.0-master-candidate.4`. Status: **CANDIDATE — NOT ACTIVE.** `READY_FOR_REAL_RESEARCH = false`.
Authority: normative. Refines S35-GOV-001 of [SAI 3.5](../SAI_3.5.md). The requirement table of §4
is checked against the [registry](normative-statements.yaml).

## 1. Rule

Every inherited obligation is kept unchanged and wins on conflict until activation. SAI 3.5 only
adds or refines in the sense of adding conditions; it never removes a condition, lowers a threshold,
opens a path that an inherited rule closes, or reorders gates. The protected files are byte-identical
to `a38ad63` (checked by [check_candidate.py](check_candidate.py)); the SAI 3.4 boundary checker
runs unmodified (OD-10 proposal A', [decisions](decisions-and-review.md)).

## 2. SAI 3.3 obligation families

| Inherited family | Content | What SAI 3.5 adds or refines | Weakened? |
|---|---|---|---|
| §0 governance (§0.2–§0.6), AGT-015 | normative language, three-piece rule, change control, no normative override, conflicts block the slice | S35 spec issues follow the same rule (S35-GOV-001); requirement ↔ registry ↔ planned test for every S35 statement | no |
| P1–P28 principles | evidence before belief, append-only, inference is not evidence, falsifiability, competing hypotheses, cheapest sufficient verification, human owns scientific semantics, typed tools, event-sourced belief, cost first-class, default-deny sensitive ingestion, … | applied to discovery records: append-only (Appendix C §1), proposals never evidence (S35-EVI-001), falsifiable admission (S35-HYP-002), classes over counts (S35-MECH-001), cheapest path (S35-LIFE-001), typed operations (S35-MOD-002) | no |
| SYS-001, ART-001 | canonical scientific state path; artifact identity | every discovery record enters through the same path (S35-EVI-001); provenance by hash (S35-EVI-002) | no |
| SIM-001–003 | run manifest; low-fidelity contradiction only CHALLENGED; typed ToolRegistry, no `eval_script` | convergence before discrimination (S35-VAL-002); closed operation catalog (S35-MOD-002); worker contract (S35-SIM-003) | no |
| EVI-001–010 | units and conditions; UNKNOWN not filled; inference not evidence; claim identity and independence; condition schema; EvidenceBundle; embeddings; retraction check; Run reference; minimum evidence boundary | per-source uncertainty (S35-VAL-003); independence across model families and shared assumptions (S35-EVI-003); contamination defenses (S35-EVI-004) | no |
| EPI-001–006 | ≥2 competing hypotheses; trace to Run; BeliefRevisionEvent replay; AuthorityPolicy; durable re-derivable TransitionPolicy decisions (read and write path); typed Conflicts | three epistemic stages and claim projection that never writes belief (S35-HYP-001, S35-HYP-003); rival closure (S35-SEL-002); contradictions from Conflicts (S35-PROB-004) | no |
| VER-001–008 | least-cost sufficient verification, capability descriptors, CostVector, OutcomeSpace, deterministic SelectionPolicy, typed predictions, no single scalar FoM, versioned disagreement metric | class-level discrimination per cost on the same machinery (S35-SEL-001); no uncalibrated EIG | no |
| DOM-SP-001–002, EXT-001 | domain validators versioned; backend-agnostic extractors; removable domain plugins | model qualification per model family (S35-MOD-003); the discovery engine stays domain-agnostic | no |
| SRC-001–003, GH-001–003 | ExternalSourceAdapter; intent-aware source policy; novelty needs PriorArtSearchRecord; GitHub provenance | coverage classes, cutoffs and novelty classes (S35-NOV-001, S35-NOV-002); literature search unchanged (S35-NOV-003) | no |
| HEU-001 | heuristics need human approval | unchanged; no discovery record becomes an approved heuristic automatically | no |
| LLM-001–002 | InferenceProvenance; calibrated BenchmarkPolicy for debate gates | Hypothesis Brain contract (S35-HYP-004); G-D metrics separate from debate metrics | no |
| SEC-001–004 | egress fail-closed; Actor/ACL and occurrence-scoped reads; secret scan; license class | project scope for discovery records (S35-SEC-003); least-privilege identities (S35-SEC-005); envelopes never include non-PUBLIC egress (S35-REG-002) | no |
| OPS-001–004 | Jobs with suspend/resume; ReviewQueue capacity; trace; cross-store unit of work | campaign checkpoints and restart (S35-LIFE-001); Owner stop (S35-SEC-006); every human authorization is a ReviewItem (S35-RPT-004) | no |
| COST-001 | BudgetGate before every action with an approval path | realized consumption and ceilings (S35-COST-001, S35-COST-002); no endpoint presumed free | no |
| UX-001–007 | derived ingestion state, five error classes, redacted diagnostics, MessageCatalog, derived system health | glossary (S35-RPT-003) and workspace content (S35-RPT-004); no sixth error class | no |
| TST-001–003 | mock and licensed replay; ID uniqueness and traceability; registry coverage | S35 registry and checker; TST-001's licensed replay stays an M4 blocker | no |
| AGT-001–017, §23.4 | implementation-agent protocol; human steering points | autonomy never decides a §23.4 steering point (Appendix E §2) | no |
| M0a–M8, HARD-LOCKs | milestone gates and executed-coverage ratchet | phases P35-0…P35-9 do not change any milestone or ratchet | no |

## 3. SAI 3.4 obligation families

| Inherited family | Content | What SAI 3.5 adds or refines | Weakened? |
|---|---|---|---|
| ASM-001 | production autonomy without external coding agents; capability envelope; safe stop | static and dynamic acceptance checks (S35-AUTO-001, S35-AUTO-002); out-of-envelope stop (S35-AUTO-003) | no |
| ASM-002 | governed chain with persisted stages; G0 definition | discovery stages around the chain (Appendix A); campaign aggregate (S35-LIFE-001–003) | no |
| ASM-003 | sources, rights, families | unchanged for literature (S35-NOV-003) | no |
| ASM-004, ASM-005, ASM-015 | typed PhysicalModelSpec; deterministic constructor; domain boundary | from-scratch construction and operation catalog restated with tests (S35-MOD-001, S35-MOD-002) | no |
| ASM-006, ASM-007 | licensed provider and worker; Job/Run resources and recovery | registration binding and raw-outputs-only (S35-SIM-001–003) | no |
| ASM-008, ASM-009, ASM-010 | numerical validation; physical validation; benchmark independence | convergence before discrimination; independent physical validation; evaluator-generated hidden worlds (S35-VAL-002, S35-VAL-005, S35-CMP-004) | no |
| ASM-011 | bounded refinement and stop conditions | mechanism change is a new hypothesis; MODEL_CORRECTION class (S35-VAL-004) | no |
| ASM-012, ASM-013 | evidence admission; Causal Warrant Gate, no automatic warrant | the gate is the exclusive confirmation authority (S35-CWG-001); consequential conclusions need independent signed review (S35-CWG-002) | no |
| ASM-014 | human intervention, ReviewQueue, ADMIN/MEMBER only, A3/A9/A12 open | autonomy levels and envelopes as advance, bounded Owner authorization (S35-SEC-001, S35-REG-002); roles unchanged (S35-SEC-004) | no; see §5 tension 1 |
| ASM-016 | bilingual scientific content and exports, canonical records not overwritten | discovery content, glossary, workspace (S35-RPT-001, S35-RPT-003, S35-RPT-004) | no |
| ASM-017 | reproducible rebuild and replay; G7-SITE and G7-WORKER | reproducible report bundle (S35-RPT-002); independent reproducibility metric (S35-CMP-005) | no |
| ASM-018 | separate offline and G0 acceptance; readiness false until the Owner | G-D separate from G0–G9 and never implied by them (S35-GD-001–003) | no |
| G0–G9 (G0-A/L/S/B/P, G7-SITE, G7-WORKER) | acceptance gates | G-D prerequisites only; no S35 requirement passes or substitutes a G gate | no |
| D-01–D-08 | Owner decisions | stay OPEN; SAI 3.5 phases name them as prerequisites (roadmap) | no |
| P0-BASIS, P-G0, P-MODEL, P-LICENSED, P-PHYSICAL, P-PORTABILITY, P-FULL-RUNTIME | phased activation | P35 phases depend on them and change none | no |
| `READY_FOR_REAL_RESEARCH = false`, ACTIVE_SPEC.yaml | readiness and the active entrypoint | unchanged and byte-identical | no |

## 4. Requirement → inherited links

| Requirement | SAI 3.4 obligations it builds on | SAI 3.3 requirements it relies on | Replaces |
|---|---|---|---|
| S35-GOV-001 | ASM-018 | TST-002, TST-003 | D-001 |
| S35-GOV-002 | ASM-001, ASM-002 | SYS-001 | D-002 |
| S35-GOV-003 | ASM-001 | SYS-001, VER-001 | new |
| S35-GOV-004 | ASM-018 | UX-006 | D-003 |
| S35-GOV-005 | ASM-018 | TST-003 | new |
| S35-LIFE-001 | ASM-002, ASM-007, ASM-017 | SYS-001, OPS-001, OPS-003, OPS-004 | D-005 |
| S35-LIFE-002 | ASM-002 | OPS-001, OPS-003 | new |
| S35-LIFE-003 | ASM-007, ASM-011 | COST-001 | D-022 |
| S35-PROB-001 | ASM-014 | SEC-001, SEC-002 | D-015 |
| S35-PROB-002 | ASM-002 | VER-001, VER-005 | new |
| S35-PROB-003 | ASM-012, ASM-013 | EPI-003, EPI-006 | D-018 |
| S35-PROB-004 | ASM-012 | EPI-006, EVI-002, EVI-005 | new |
| S35-HYP-001 | ASM-013 | EPI-001, EPI-002, EPI-005, SYS-001 | D-027 |
| S35-HYP-002 | — | VER-004, VER-006, EPI-001 | D-004 |
| S35-HYP-003 | ASM-013, ASM-018 | EPI-003, EPI-005, SYS-001 | D-027 |
| S35-HYP-004 | ASM-002 | LLM-001, EVI-003, EVI-006 | new |
| S35-MECH-001 | — | EPI-001, LLM-002, VER-006, VER-008 | D-016, D-017 |
| S35-MECH-002 | — | EPI-001 | new |
| S35-REF-001 | ASM-011 | EPI-003 | new |
| S35-REF-002 | ASM-011, ASM-012 | EPI-003, EPI-005 | D-019 |
| S35-REF-003 | ASM-010 | EPI-003 | D-020 |
| S35-SEL-001 | ASM-002 | VER-001, VER-002, VER-003, VER-005 | D-021 |
| S35-SEL-002 | ASM-013 | EPI-001, VER-006 | new |
| S35-MOD-001 | ASM-004, ASM-005 | SIM-003, EVI-002 | D-008 |
| S35-MOD-002 | ASM-005, ASM-015 | SIM-003 | D-008 |
| S35-MOD-003 | ASM-008, ASM-009 | SIM-001, DOM-SP-001 | new |
| S35-SIM-001 | ASM-006, ASM-007 | TST-001, COST-001, OPS-001, SIM-001 | D-009 |
| S35-SIM-002 | ASM-006, ASM-015 | SIM-001 | D-009 |
| S35-SIM-003 | ASM-005, ASM-007 | OPS-001, OPS-004, SIM-003 | new |
| S35-VAL-001 | ASM-002, ASM-012 | EVI-009, SIM-001 | D-010 |
| S35-VAL-002 | ASM-008 | SIM-002 | D-011 |
| S35-VAL-003 | ASM-008, ASM-009, ASM-016 | EVI-001, EVI-002 | D-029 |
| S35-VAL-004 | ASM-011 | EPI-005 | D-012 |
| S35-VAL-005 | ASM-009, ASM-010 | EVI-004, DOM-SP-002 | D-013 |
| S35-LOOP-001 | ASM-010, ASM-013 | SEC-002, EPI-005 | D-023 |
| S35-LOOP-002 | ASM-012 | EPI-003, OPS-003 | new |
| S35-LOOP-003 | ASM-011, ASM-018 | EPI-001 | D-028 |
| S35-CWG-001 | ASM-013 | EPI-002, EPI-004, EPI-005 | D-026 |
| S35-CWG-002 | ASM-013, ASM-014 | SEC-002, EPI-005 | new |
| S35-REG-001 | ASM-010 | VER-006, EPI-005 | D-024 |
| S35-REG-002 | ASM-007, ASM-014 | COST-001, SEC-002 | new |
| S35-REG-003 | ASM-013, ASM-014 | EPI-005, SEC-002 | new |
| S35-REG-004 | ASM-012, ASM-013 | EVI-004, EVI-009, EPI-002 | D-025 |
| S35-NOV-001 | ASM-003 | SRC-003 | D-004 |
| S35-NOV-002 | ASM-009, ASM-013 | SRC-003 | new |
| S35-NOV-003 | ASM-003 | SRC-001, SRC-002, SEC-001, SEC-004 | D-007 |
| S35-EVI-001 | ASM-012 | EVI-003, EVI-009, SYS-001 | D-031 |
| S35-EVI-002 | ASM-002, ASM-017 | LLM-001, OPS-003, ART-001 | D-032 |
| S35-EVI-003 | ASM-010, ASM-012 | EVI-004 | new |
| S35-EVI-004 | ASM-010 | EVI-004, SEC-002 | new |
| S35-RPT-001 | ASM-016 | UX-006 | D-014 |
| S35-RPT-002 | ASM-017 | OPS-003, ART-001 | new |
| S35-RPT-003 | ASM-016 | UX-006 | new |
| S35-RPT-004 | ASM-014, ASM-016 | UX-002, UX-005, UX-007, OPS-002 | new |
| S35-AUTO-001 | ASM-001 | SIM-003 | D-006 |
| S35-AUTO-002 | ASM-001 | SIM-003, SEC-001 | D-006 |
| S35-AUTO-003 | ASM-001, ASM-014 | OPS-002, UX-005 | new |
| S35-SEC-001 | ASM-014 | SEC-002, COST-001 | new |
| S35-SEC-002 | ASM-007, ASM-014 | COST-001, OPS-002, SEC-002 | D-030 |
| S35-SEC-003 | ASM-014 | SEC-002 | D-033 |
| S35-SEC-004 | ASM-014 | SEC-002 | D-034 |
| S35-SEC-005 | ASM-014 | SEC-002, OPS-004 | new |
| S35-SEC-006 | ASM-007, ASM-014 | OPS-001, COST-001 | new |
| S35-COST-001 | ASM-007 | COST-001, VER-003 | new |
| S35-COST-002 | ASM-007 | COST-001 | new |
| S35-GD-001 | ASM-018 | TST-003 | D-035 |
| S35-GD-002 | ASM-018 | LLM-002 | D-036 |
| S35-GD-003 | ASM-018 | — | D-037 |
| S35-CMP-001 | — | LLM-002 | D-038 |
| S35-CMP-002 | — | COST-001, VER-003 | D-039 |
| S35-CMP-003 | ASM-010 | — | D-040 |
| S35-CMP-004 | ASM-010 | LLM-002 | D-041 |
| S35-CMP-005 | ASM-017 | LLM-002 | D-042 |
| S35-CMP-006 | — | LLM-002 | D-043 |
| S35-CMP-007 | ASM-010 | EVI-004 | D-044 |
| S35-CMP-008 | ASM-007 | COST-001 | D-045 |
| S35-CMP-009 | ASM-007, ASM-018 | COST-001 | D-046 |

## 5. Tensions examined (none is a weakening)

1. **SAI 3.3 P12 "human owns scientific semantics" and §2 "not a system that replaces researcher
   judgment" versus an autonomous AI scientist.** Autonomy acts only inside an Owner-signed envelope
   and never decides a §23.4 steering point (validators, fidelity thresholds, benchmark ground
   truth, heuristic promotion, NDA classes, connectors); confirmations need a signed human review
   (S35-CWG-002). The human keeps scientific semantics; the system does the bounded work. Recorded
   for review as S35-ISSUE-10.
2. **SAI 3.3 §8.2 hypothesis lifecycle versus SAI 3.5 claim states.** The claim state is a
   projection that maps onto §8.2 and never replaces it ([Appendix C](records-and-states.md) §3.2);
   S35-ISSUE-04.
3. **SAI 3.3 §12.1 episode state machine versus the campaign.** A campaign contains episodes and
   never sets their states (S35-LIFE-002); S35-ISSUE-05.
4. **Per-hypothesis pre-authorization (G0 line rule (l), `011w`) versus envelope registration.**
   Default: an envelope does not satisfy rule (l) (S35-REG-003); OD-14 decides; S35-ISSUE-01.
5. **SAI 3.3 §14.2 Novelty Audit mode versus automatic prior-art search.** Automatic search uses
   only PUBLIC sanitized queries through authorized adapters, as the Novelty Audit mode requires
   (S35-NOV-003); S35-ISSUE-09.
