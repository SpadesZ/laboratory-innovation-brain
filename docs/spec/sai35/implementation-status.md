# SAI 3.5 Discovery Candidate — Implementation status

Version: `3.5.0-discovery-candidate.1` · Inspected: 2026-11-01.
Status: **CANDIDATE — NOT ACTIVE.** `READY_FOR_REAL_RESEARCH = false`. G0 is NOT PASSED.

This page says what exists, by source inspection, and what does not. It is conservative: a
component is IMPLEMENTED only when its code and tests can be located. Nothing here was re-run for
this document except the documentation checkers. File names are evidence of code, not of
scientific capability.

## 1. Two lines of development

| Line | Commit | Content | Integration |
|---|---|---|---|
| SAI 3.4 integration line | `integration-integrity-accounts` @ `a38ad63` (this candidate's base) | `f3fadf6` code plus the SAI 3.4 documents | — |
| G0 line | `g0-owner-boundary-closure` @ `58c68be` | `f3fadf6` plus 72 G0 commits: reliability, exploratory screening, prospective evidence (`011p`, `011s`), spend administration (`011t`), account audit (`011u`), evaluation tooling | **not integrated** with `a38ad63`. The common ancestor is `f3fadf6`. `58c68be` does not contain the SAI 3.4 documents, and `a38ad63` does not contain the G0 code |
| Discovery line | `discovery-loop-offline`, created from `58c68be` | offline Discovery Loop v0 (see §3) | not integrated; not reviewed |

Paths below without a prefix exist on this base. Paths written as `58c68be:<path>` exist only on the
G0 line. Reports on the G0 line state that its final state passed the full PostgreSQL suite and an
861/861 mutation battery; that is the G0 line's own engineering evidence. It was not re-run here,
and it is not scientific evidence (`58c68be:docs/audit/g0-owner-boundary-closure-2026-10-28/REPORT.zh-TW.md`).

## 2. Status words

- **IMPLEMENTED** — code and tests can be located; scope as stated.
- **PARTIAL** — reusable parts exist; the SAI 3.5 capability does not.
- **MOCK ONLY** — a deterministic stand-in exists; the real capability does not.
- **ABSENT** — no code found by inspection and search.
- **IN PROGRESS (not reviewed)** — being written on a branch; not inspected or accepted here.

## 3. Component status

| Component (SAI 3.5) | This base `a38ad63` | G0 line `58c68be` | Evidence | Missing for SAI 3.5 |
|---|---|---|---|---|
| Governed research workflow (episode, ingestion, debate, verification, report) | PARTIAL | PARTIAL, with G0 reliability work | `src/lab_brain/research/service.py`; `58c68be:src/lab_brain/research/service.py` | discovery stages; G0 acceptance (NOT PASSED) |
| Real LLM runtime behind ScientificLLM / ModelRouter | PARTIAL | PARTIAL; spend administration and local free-endpoint guard | `src/lab_brain/llm_runtime/runtime.py`, `src/lab_brain/llm_runtime/local_setup.py`; `58c68be:migrations/011t_llm_spend_administration.sql` | no G0-accepted real-model research; G0 report: no real LLM results, no blind evaluation run |
| Rule-based fallback reasoner | IMPLEMENTED (not an LLM) | IMPLEMENTED | `src/lab_brain/cognition/catalog_reasoner.py` | cannot count toward G0 or G-D |
| Autonomous literature search (D-007) | PARTIAL | PARTIAL | `src/lab_brain/research/literature.py` (PUBLIC-query egress); `src/lab_brain/tool_providers/literature/corpus.py` ("Not a live literature API": a JSON fixture corpus) | a real literature provider; autonomous query planning; rights per passage at scale |
| Prior-art and novelty record (D-004) | IMPLEMENTED (SRC-003 scope) | IMPLEMENTED | `src/lab_brain/cognition/novelty.py` | coverage requirements for discovery claims (OD-11) |
| Competing hypotheses and admission | IMPLEMENTED (M3 scope) | IMPLEMENTED | `src/lab_brain/cognition/debate.py`; SAI 3.3 §8 admission | class-based diversity measurement |
| Problem discovery (D-015) | ABSENT | ABSENT | search found no ResearchProblem record or origin model | everything |
| Distinguishable mechanism classes (D-016, D-017) | ABSENT | PARTIAL concept only: the G0 scorer checks for at least two pre-screening hypotheses discriminating on different observables | `58c68be:src/lab_brain/evaluation/scoring.py` (`competing_pre_screening`) | equivalence-class partition under an experiment set |
| Anomaly registry with explicit states (D-018) | ABSENT | ABSENT | VS-SP-001 treats one anomaly as its research question (SAI 3.3 §25.1); no general state machine found | everything |
| Research Reframing (D-019, D-020) | ABSENT | ABSENT | search for "reframing" in `src/` found nothing on either line | everything |
| Experiment selection per cost (D-021) | PARTIAL: least-cost sufficient verification | PARTIAL | `src/lab_brain/verification/least_cost.py`, `src/lab_brain/verification/sufficiency.py` | discrimination across mechanism classes per cost |
| Exploratory screening | ABSENT | IMPLEMENTED, off by default | `58c68be:src/lab_brain/verification/screening.py`; `58c68be:docs/adr/ADR-0015-exploratory-screening-is-not-a-verification-action.md` | — (not required by SAI 3.5) |
| Prospective pre-registration and no retrospective self-support (D-024, D-025) | ABSENT | IMPLEMENTED for post-screening hypotheses | `58c68be:migrations/011p_screening_support_is_prospective_in_time.sql`, `58c68be:migrations/011s_prospective_evidence_authorization.sql`, `58c68be:src/lab_brain/verification/prospective.py` | extension to discovery and reframed hypotheses; signed authorization (G0 decision B3); integration |
| Causal Warrant Gate V1.1 (D-026) | IMPLEMENTED (integration candidate; limited scientific scope) | IMPLEMENTED | `src/lab_brain/core/warrant.py`, `src/lab_brain/security/reviewer_identity.py`, `src/lab_brain/research/confirmation.py` | nothing new; DISCRIMINATION and multi-cause stay Owner decisions |
| Epistemic state projection for discovery claims (D-027) | ABSENT | ABSENT | — | projection over existing records |
| Explicit INSUFFICIENT_VALIDATION / STOPPED outcome (D-028) | PARTIAL: reports keep unperformed checks and UNKNOWN visible | PARTIAL | `src/lab_brain/research/report.py` | a typed discovery-level stop outcome and its scoring |
| Physical model construction from scratch (D-008) | ABSENT (SPECIFIED in SAI 3.4) | ABSENT | [SAI 3.4 implementation gap](../sai34/implementation-gap.md) | PhysicalModelSpec, typed constructor, readback |
| Licensed Lumerical execution on internal workers (D-009) | MOCK ONLY | MOCK ONLY | `src/lab_brain/tool_providers/lumerical/mock.py`, `src/lab_brain/tool_providers/lumerical/mock_vertical.py`; `tests/e2e/test_vs_sp_001_licensed_replay.py` fails by design when enabled; no `lumapi` import | provider, worker, sandbox, qualification, license |
| Parameter sweeps (D-010) | MOCK ONLY | MOCK ONLY | mock DC-sweep capability in `src/lab_brain/tool_providers/lumerical/mock_vertical.py` | real, pre-registered sweeps |
| Numerical convergence studies (D-011) | PARTIAL: trend validators and a mock mesh-sensitivity capability | PARTIAL | `src/lab_brain/domains/silicon_photonics/validators.py` | the ASM-008 study on real runs |
| Bounded model refinement (D-012) | ABSENT | ABSENT | — | ModelPatch, policy, lineage |
| Independent physical validation (D-013) | ABSENT | ABSENT | — | independent references and validators |
| Bilingual reports (D-014) | PARTIAL: workspace i18n | PARTIAL: zh-TW science export and bilingual structural-parity checks; semantic quality NOT VERIFIED | `src/lab_brain/interfaces/web/i18n.py`, `src/lab_brain/research/render.py`; G0 report §8 | discovery content; G0-B acceptance |
| Evaluation tooling (sealing, freeze, contamination, blind runner, scorer, statistics, environment manifest) | ABSENT | IMPLEMENTED for G0; no blind evaluation has been run | `58c68be:src/lab_brain/evaluation/`, `58c68be:scripts/g0_eval_seal.py`, `58c68be:scripts/g0_eval_freeze.py`, `58c68be:scripts/g0_eval_environment.py`, `58c68be:scripts/g0_eval_score.py`, `58c68be:docs/evaluation/G0-blind-evaluation-protocol.zh-TW.md` | G-D metrics, arm handling, sealed G-D benchmark |
| Matched-budget A/B/C harness (D-038 to D-046) | ABSENT | ABSENT | — | everything; see offline v0 below |
| Owner gates for money (D-030) | PARTIAL | PARTIAL: an Owner-only spend administration role; unbudgeted remote requests refused by default | `58c68be:migrations/011t_llm_spend_administration.sql` | license, physical and publication gates for discovery |
| Accounts, project isolation (D-033, D-034) | IMPLEMENTED (integration candidate) | IMPLEMENTED; plus interaction-key lifecycle and account-change audit (detection, not prevention) | `src/lab_brain/accounts/service.py`; `58c68be:migrations/011u_account_change_audit.sql` | A3, A9 and A12 open |
| No external coding agent in production (D-006) | NOT TESTED | NOT TESTED | G9 and T-D-006 not run | a deployment-equivalent check |

### Offline Discovery Loop v0

The offline Discovery Loop v0 is being developed on branch `discovery-loop-offline` from `58c68be`:
module `lab_brain.discovery`, synthetic seeded worlds, and baselines B0 single-hypothesis, B1
LIB-without-discovery and B2 LIB+Discovery. Status: **in progress, not reviewed.** At the time of
writing the branch pointed at `58c68be` itself, with no committed Discovery code visible to this
review. Its results, when they exist, are engineering evidence about synthetic worlds. They are not
a G-D1 verdict unless an independent evaluator runs them under a frozen G-D0 protocol.

## 4. What this means

- No SAI 3.5 capability is implemented. The Discovery Loop, mechanism classes, anomaly states,
  reframing, the epistemic-state projection and the A/B/C harness do not exist on either line.
- Reusable parts exist but sit on two unintegrated lines. The most relevant ones for SAI 3.5 are
  the prospective-evidence rules and the evaluation tooling, and those are only on the G0 line.
- Licensed simulation, model construction, refinement and physical validation are absent on both
  lines. This is a gap in implementation and also an external gate (license, data), not only the
  external gate.
