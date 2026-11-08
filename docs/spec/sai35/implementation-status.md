# SAI 3.5 — Appendix L: Implementation status

Version: `3.5.0-master-candidate.3` · Inspected: 2026-11-04, candidate.3 (candidate.1: 2026-11-02).
Status: **CANDIDATE — NOT ACTIVE.** `READY_FOR_REAL_RESEARCH = false`. G0 is NOT PASSED.
Authority: informative. The status column is checked against the
[registry](normative-statements.yaml); evidence paths are checked to exist at their commits when
those commits are present. Supersedes the `3.5.0-discovery-candidate.1` version of this file (kept
in git history).

This page says what exists, by source inspection, and what does not. A file is evidence of code,
never of scientific capability. Nothing here was re-run for this document except the documentation
checkers; the test and mutation figures quoted below are those recorded by each line's own report.

## 1. Lines of development

| Line | Commit | Content | Integration |
|---|---|---|---|
| SAI 3.4 integration line | `integration-integrity-accounts` @ `a38ad63` (this candidate's base) | `f3fadf6` code plus the SAI 3.4 documents: governed research workflow, debate, admission, least-cost verification, Causal Warrant Gate V1.1, accounts, deterministic Lumerical mock | — |
| G0 line (WS1) | `g0-reliability-authenticity-closure` @ `f41758c` (from `58c68be`) | prospective evidence (`011p`, `011s`), spend administration (`011t`), account audit (`011u`), local endpoints not free (`011v`), signed verification authorizations (`011w`), frozen blind-evaluation inputs and environment checks; its report records 3567 passed / 0 failed on the full PostgreSQL suite and a 910/911 then 1/1 mutation battery | **not integrated**; awaits the Independent Chief Auditor; G0 NOT PASSED |
| G0 read-path closure | `g0-authorization-read-path-closure`, pushed (from `f41758c`; source code at `2a96ee8`, no source change after it; local head observed at `367163b`; the final head is reported by the lead) | fixes the forged-authorization read-path bypass an auditor found on WS1: a SUPPORTS of a post-screening hypothesis is admitted to decision inputs only when its authorization verifies, fail closed without a verifier; acceptance blind scores require both the runner's and an independent evaluator's environment verification, other scores are labelled diagnostic; as reported there, full PostgreSQL suite 3583 passed / 0 failed, complete mutation battery 928/929 at `2a96ee8` with the one survivor killed afterwards by an added test | **fixed on this pushed, unmerged branch, pending independent audit** |
| Discovery line (WS2) | `discovery-loop-offline` @ `118a4ac` (from `58c68be`) | offline Discovery Loop v0 (`src/lab_brain/discovery/`), ring-resonator catalog pinned by digest, seeded synthetic worlds, baselines B0/B1/B2, frozen benchmark evidence | not integrated; not independently reviewed |
| Independent discovery evaluation | `discovery-independent-evaluation` @ `d7ec9f2`, from `118a4ac` | protocol (roles, sealing, held-out families, realized-cost curves, arms A/B/C), hidden-world format and loader, cost–discovery curves and held-out-family runs on same-author worlds | pushed; not reviewed; no independent world author yet, so no independent result; same-author results show force-fitting on held-out families and no realized-cost-matched comparison |

| G0 security assurance | `claude/lib-implementation-agent-47evs0-g0` @ `47451e1` (from `367163b`) | reader inventory R1–R14 with negative and positive controls for forged, rogue-authority, tampered, replayed and revoked authorizations; fixes a forged SUPPORTS reaching belief through the belief projection (`SUPPORT_UNVERIFIED`); finding F2 open: the services' role can register transition policies and so make any hypothesis SUPPORTED; DB-trust analysis and evaluator-attestation design (`docs/audit/g0-security-assurance-2026-11-04/REPORT.md`); CI run `41786976679` success | pushed; not merged; not independently audited; G0 NOT PASSED |
| G0 F2 closure | `claude/lib-implementation-agent-47evs0-g0-f2` @ `24fae8b` (from `47451e1`) | owner-only TransitionPolicy registration (Owner-approved 2026-11-04): `grant_database_roles` revokes writes on `transition_policies`, migration `011x` refuses non-owner inserts, owner command `lab-brain admin register-policies`; strict-xfail regression test (commit `4f646bc`) then fix (`b56b5a6`); full PostgreSQL suite 3617 passed / 4 skipped and default suite 2348 passed at `ef5d713`; 6 `f2_*` mutants killed; residual risks R-1…R-8 (`docs/audit/g0-f2-closure-2026-11-04/REPORT.md`) | pushed; not merged; not independently audited; G0 NOT PASSED |
| Discovery safety v1.1 | `claude/lib-implementation-agent-47evs0-discovery-v11` @ `aa05dfd` (from `0928602`; design frozen `53bd2a9`) | refit-coverage bypass reproduced in v1.0 and closed (signal set recomputed after every observation); Holm-corrected per-experiment checks; new held-out seeds drawn after the freeze: force-fit B2/B3/B4 = 80/6/4 of 195 at budget 12, correct in-catalog identifications 211/160/156 of 240; equal caps only (the frozen engine has no anytime answers, so checkpoint comparisons are COST_UNMATCHED); full PostgreSQL suite 3816 passed / 4 skipped; 8 mutants killed (`docs/reports/discovery-safety-v1.1.md`) | pushed; not merged; engineering evidence only; not connected to research execution |
| Discovery safety | `claude/lib-implementation-agent-47evs0-discovery` @ `0928602` (from `d7ec9f2`) | offline safety gate `src/lab_brain/discovery_safety/` over the frozen engine: adequacy probes, pre-declared adequacy test, replication, catalog-completeness check, abstention with anomalies, reframing, stage-1 new-family proposals and pairwise discriminating-experiment requests; same-author worlds: force-fit 78→9 of 195 at budget 12 and 92→5 at budget 24, in-catalog accuracy 218→153 of 240 at budget 12 and 238→236 at 24 (`docs/reports/discovery-unknown-mechanism-safety.md`) | pushed; not merged; engineering evidence only; not connected to research execution |

Evidence written `<commit>:<path>` exists at that commit; a path without a prefix is on this branch.

## 2. Status words

- **complete** — the requirement's acceptance test exists and passes, with evidence. For this
  candidate only documentation-level requirements are complete; complete never means a capability is
  demonstrated.
- **partial** — reusable parts exist on some line (named), but the requirement is not met.
- **proposed** — specified only; nothing found by inspection and search.
- **blocked** — cannot progress until an external decision or resource exists (named).
- **untested** — a property is asserted or designed, but no test has ever exercised it.

## 3. Summary

| Status | Requirements |
|---|---|
| complete | 3 |
| partial | 45 |
| proposed | 22 |
| blocked | 5 |
| untested | 2 |
| **total** | **77** |

| Area | complete | partial | proposed | blocked | untested |
|---|---|---|---|---|---|
| GOV | 3 | 1 | 1 | 0 | 0 |
| LIFE | 0 | 2 | 1 | 0 | 0 |
| PROB | 0 | 2 | 2 | 0 | 0 |
| HYP | 0 | 3 | 1 | 0 | 0 |
| MECH | 0 | 2 | 0 | 0 | 0 |
| REF | 0 | 3 | 0 | 0 | 0 |
| SEL | 0 | 2 | 0 | 0 | 0 |
| MOD | 0 | 0 | 3 | 0 | 0 |
| SIM | 0 | 0 | 1 | 2 | 0 |
| VAL | 0 | 2 | 2 | 1 | 0 |
| LOOP | 0 | 3 | 0 | 0 | 0 |
| CWG | 0 | 2 | 0 | 0 | 0 |
| REG | 0 | 2 | 2 | 0 | 0 |
| NOV | 0 | 2 | 1 | 0 | 0 |
| EVI | 0 | 4 | 0 | 0 | 0 |
| RPT | 0 | 3 | 1 | 0 | 0 |
| AUTO | 0 | 0 | 1 | 0 | 2 |
| SEC | 0 | 3 | 3 | 0 | 0 |
| COST | 0 | 2 | 0 | 0 | 0 |
| GD | 0 | 0 | 1 | 2 | 0 |
| CMP | 0 | 7 | 2 | 0 | 0 |

## 4. Per-requirement status

| Requirement | Status | Evidence (path at commit; no prefix = this branch) | Missing or blocking |
|---|---|---|---|
| S35-GOV-001 | complete | `docs/spec/sai35/check_candidate.py`<br>`docs/spec/sai35/compatibility.md`<br>`docs/spec/sai35/open-spec-issues.md` | nothing for the documentation scope; the procedure is exercised only when a conflict is found |
| S35-GOV-002 | complete | `docs/spec/SAI_3.5.md`<br>`docs/spec/sai35/check_candidate.py` | specification scope only: no capability is demonstrated |
| S35-GOV-003 | proposed | — | no campaign aggregate, no closed loop from selection to registered test in the product |
| S35-GOV-004 | partial | `docs/spec/sai35/check_candidate.py` | the checker scans SAI 3.5 documents only; no claim audit of UI strings, reports or status files exists |
| S35-GOV-005 | complete | `docs/spec/sai35/check_candidate.py` | nothing for the candidate state; activation itself is OD-16 |
| S35-LIFE-001 | partial | `a38ad63:src/lab_brain/research/service.py`<br>`a38ad63:src/lab_brain/tools/execution.py` | research episodes and Jobs persist; campaign stages, discovery checkpoints and skip reasons do not exist |
| S35-LIFE-002 | proposed | — | no campaign record or state machine on any line |
| S35-LIFE-003 | partial | `118a4ac:src/lab_brain/discovery/loop.py`<br>`a38ad63:src/lab_brain/core/budget.py` | the offline loop terminates under a fixed budget; no product campaign with a versioned stopping policy exists |
| S35-PROB-001 | proposed | — | no ResearchProblem record on any line |
| S35-PROB-002 | proposed | — | no problem valuation on any line |
| S35-PROB-003 | partial | `118a4ac:src/lab_brain/discovery/model.py` | offline frozen anomaly records with four states only; no persistent registry, no CWG link |
| S35-PROB-004 | partial | `a38ad63:src/lab_brain/core/models/conflict.py`<br>`a38ad63:src/lab_brain/core/repositories/conflicts.py` | typed Conflict records exist; no detector turns conflicts or gaps into problems |
| S35-HYP-001 | partial | `118a4ac:tests/unit/test_discovery_governance.py`<br>`a38ad63:src/lab_brain/core/hypothesis_admission.py` | the offline loop has no CONFIRMED by design and the product has an admission gate; no stage field or projection exists |
| S35-HYP-002 | partial | `a38ad63:src/lab_brain/core/hypothesis_admission.py`<br>`a38ad63:src/lab_brain/core/models/prediction.py` | the §8 admission gate and typed predictions exist; mechanistic distinctness under an experiment set is not checked in the product |
| S35-HYP-003 | proposed | — | no claim-state projection over canonical records; the offline loop has its own six hypothesis states |
| S35-HYP-004 | partial | `a38ad63:src/lab_brain/cognition/debate.py`<br>`a38ad63:src/lab_brain/llm_runtime/runtime.py` | debate generates competing hypotheses with provenance; no real-model research is G0-accepted; no proposal of mechanisms outside a catalog |
| S35-MECH-001 | partial | `118a4ac:src/lab_brain/discovery/distinguish.py`<br>`118a4ac:src/lab_brain/discovery/metrics.py` | offline prototype on linear toy forward models; its `classes()` computes connected components (a transitive merge), which candidate.2 forbids, so only its pairwise separation oracle is reusable; the revised definition exists only as executable documentation (`docs/spec/sai35/semantic_reference.py`), not as product code; not integrated, not independently reviewed |
| S35-MECH-002 | partial | `118a4ac:src/lab_brain/discovery/loop.py` | offline widening draws only on declared classes and pairwise compositions; no model-proposed new mechanism; on `d7ec9f2` the discovery arm force-fits an available mechanism when the true family is absent (about 0.40 at budget 12, 0.47 at 24, same-author worlds); the adequacy-before-endorsement rule of candidate.2 is not in the product; an offline safety gate implementing it over the frozen engine is on `claude/lib-implementation-agent-47evs0-discovery` @ `0928602` (engineering evidence on same-author worlds, thresholds pending OD-18) |
| S35-REF-001 | partial | `118a4ac:src/lab_brain/discovery/loop.py` | offline reframing covers four kinds over hypotheses and anomalies; assumption, observable and model failures are not triggers |
| S35-REF-002 | partial | `118a4ac:src/lab_brain/discovery/model.py` | offline append-only records; no persistence, no relation-level refusal |
| S35-REF-003 | partial | `118a4ac:src/lab_brain/discovery/loop.py` | offline caps (two widening rounds) and prospective support rule; no product lineage or policy |
| S35-SEL-001 | partial | `a38ad63:src/lab_brain/verification/least_cost.py`<br>`118a4ac:src/lab_brain/discovery/loop.py` | least-cost sufficient verification exists over fixed rivals; class-level discrimination per cost exists only offline |
| S35-SEL-002 | partial | `118a4ac:src/lab_brain/discovery/loop.py`<br>`118a4ac:src/lab_brain/discovery/handover.py` | offline rival and class closure; no separate Validation identity |
| S35-MOD-001 | proposed | — | SPECIFIED in SAI 3.4 only; no PhysicalModelSpec, constructor or readback on any line |
| S35-MOD-002 | proposed | — | no operation catalog or constructor on any line |
| S35-MOD-003 | proposed | — | no model-family qualification record on any line |
| S35-SIM-001 | blocked | `a38ad63:src/lab_brain/tool_providers/lumerical/mock.py` | mock only; no licensed provider or worker; blocked by license, site entitlement and SAI 3.4 D-04 |
| S35-SIM-002 | blocked | `a38ad63:src/lab_brain/tool_providers/lumerical/__init__.py` | provider slot declares mock only; blocked by license and site qualification (SAI 3.4 D-04) |
| S35-SIM-003 | proposed | `a38ad63:src/lab_brain/tools/execution.py` | Job/Run and lease seams exist; no worker, fencing token or registration binding |
| S35-VAL-001 | proposed | `a38ad63:src/lab_brain/tool_providers/lumerical/mock_vertical.py` | a mock DC sweep only; no registered sweep plan |
| S35-VAL-002 | partial | `a38ad63:src/lab_brain/domains/silicon_photonics/validators.py` | trend validators and a mock mesh-sensitivity capability only; no convergence study on real runs |
| S35-VAL-003 | partial | `a38ad63:src/lab_brain/research/report.py` | reports keep UNKNOWN and unperformed checks visible; no per-source uncertainty record |
| S35-VAL-004 | proposed | — | no ModelPatch, refinement policy or lineage on any line |
| S35-VAL-005 | blocked | — | no independent reference data, holdout or validator; blocked by SAI 3.4 D-02 (data and accuracy thresholds) |
| S35-LOOP-001 | partial | `118a4ac:src/lab_brain/discovery/handover.py` | offline hand-over is always pending the gate; no separate service identities or database permissions |
| S35-LOOP-002 | partial | `118a4ac:src/lab_brain/discovery/loop.py` | offline loop feeds refutations and anomalies back in memory; no FeedbackRecord or disposition |
| S35-LOOP-003 | partial | `118a4ac:src/lab_brain/discovery/loop.py`<br>`a38ad63:src/lab_brain/research/report.py` | offline STOPPED_INSUFFICIENT_VALIDATION outcome; no typed product StopRecord |
| S35-CWG-001 | partial | `a38ad63:src/lab_brain/core/warrant.py`<br>`a38ad63:src/lab_brain/research/confirmation.py`<br>`118a4ac:src/lab_brain/discovery/handover.py` | the gate exists with limited scientific scope; it is not yet wired to discovery claims |
| S35-CWG-002 | partial | `a38ad63:src/lab_brain/security/reviewer_identity.py` | signed review exists for warrant answers; release and physical-experiment gating by claim does not; second-account detection depends on A3 |
| S35-REG-001 | partial | `f41758c:src/lab_brain/verification/prospective.py`<br>`f41758c:migrations/011s_prospective_evidence_authorization.sql`<br>`f41758c:migrations/011w_signed_verification_authorizations.sql` | signed per-hypothesis authorizations exist on the unintegrated G0 line; the forged-authorization read-path bypass found there is fixed on the pushed, unmerged branch g0-authorization-read-path-closure (source at 2a96ee8), pending independent audit; no envelope reference |
| S35-REG-002 | proposed | — | no ResearchEnvelope on any line |
| S35-REG-003 | proposed | — | no envelope; the rule (l) interaction is an open Owner decision (OD-14) |
| S35-REG-004 | partial | `f41758c:migrations/011p_screening_support_is_prospective_in_time.sql`<br>`f41758c:migrations/011s_prospective_evidence_authorization.sql`<br>`118a4ac:src/lab_brain/discovery/loop.py` | rules exist for post-screening hypotheses on the unintegrated G0 line and offline in the loop; not applied to discovery records |
| S35-NOV-001 | partial | `a38ad63:src/lab_brain/cognition/novelty.py` | SRC-003 records exist; coverage classes, cutoff fields and bounding of discovery claims do not |
| S35-NOV-002 | proposed | — | no novelty classification on any line |
| S35-NOV-003 | partial | `a38ad63:src/lab_brain/research/literature.py` | PUBLIC-query egress exists; the literature provider is a JSON fixture corpus, not a live API |
| S35-EVI-001 | partial | `a38ad63:src/lab_brain/research/service.py` | the admission path exists for the research workflow; discovery outputs are not wired to it |
| S35-EVI-002 | partial | `a38ad63:src/lab_brain/research/service.py`<br>`f41758c:src/lab_brain/research/run_provenance.py` | InferenceProvenance and run provenance exist; discovery record types do not |
| S35-EVI-003 | partial | `a38ad63:src/lab_brain/evidence/independence.py` | source-work independence exists; model-family and shared-assumption dependence do not |
| S35-EVI-004 | partial | `f41758c:src/lab_brain/evaluation/contamination.py`<br>`f41758c:src/lab_brain/evaluation/sealing.py` | G0 evaluation sealing and contamination tooling on the unintegrated G0 line; no production-side sealed plane |
| S35-RPT-001 | partial | `f41758c:src/lab_brain/research/render.py`<br>`a38ad63:src/lab_brain/interfaces/web/i18n.py` | zh-TW science export and structural parity on the G0 line (semantic quality not verified); no discovery content |
| S35-RPT-002 | partial | `f41758c:src/lab_brain/evaluation/environment.py` | an environment manifest exists for G0 blind evaluation; no report bundle |
| S35-RPT-003 | proposed | — | the glossary exists in this specification only; no lint |
| S35-RPT-004 | partial | `a38ad63:src/lab_brain/interfaces/web/i18n.py` | a bilingual research workspace exists; no campaign, envelope or discovery views |
| S35-AUTO-001 | untested | — | the product is not designed around coding agents, but no deployment-equivalent check has ever run |
| S35-AUTO-002 | untested | — | no release image audit exists |
| S35-AUTO-003 | proposed | — | no envelope or out-of-envelope stop |
| S35-SEC-001 | proposed | — | no autonomy levels on any line |
| S35-SEC-002 | partial | `f41758c:migrations/011t_llm_spend_administration.sql` | an Owner-only spend administration role on the unintegrated G0 line; no license, physical-experiment or publication gate |
| S35-SEC-003 | partial | `a38ad63:src/lab_brain/accounts/service.py` | project isolation exists for the current records; discovery records, workers and evaluator scope do not exist |
| S35-SEC-004 | partial | `a38ad63:src/lab_brain/accounts/service.py`<br>`f41758c:migrations/011w_signed_verification_authorizations.sql` | ADMIN/MEMBER and key enrolment exist; A3, A9 and A12 open; no evaluator or envelope-authorizer enrolment |
| S35-SEC-005 | proposed | — | services share one database role today; no per-component identities |
| S35-SEC-006 | proposed | — | no campaign or envelope to stop |
| S35-COST-001 | partial | `a38ad63:src/lab_brain/core/budget.py`<br>`f41758c:migrations/011v_llm_spend_local_is_not_free.sql` | BudgetGate and CostLedger exist; local metering is on the unintegrated G0 line; no campaign or envelope reconciliation |
| S35-COST-002 | partial | `a38ad63:src/lab_brain/core/budget.py` | session budgets with an approval path exist; campaign and envelope ceilings do not |
| S35-GD-001 | blocked | — | no evaluator assigned (OD-02); no G-D level evaluated |
| S35-GD-002 | blocked | — | no frozen protocol, evaluator or benchmark (OD-02, OD-03) |
| S35-GD-003 | proposed | — | no verdict records exist to check |
| S35-CMP-001 | partial | `118a4ac:src/lab_brain/discovery/baselines.py`<br>`118a4ac:src/lab_brain/discovery/benchmark.py` | offline arms B0, B1 and B2 only: B0 is a deterministic stand-in, not an LLM, so arm A does not exist; B1 re-implements the loop policy, not the real LIB workflow |
| S35-CMP-002 | partial | `118a4ac:src/lab_brain/discovery/benchmark.py` | the offline run matched worlds, seeds and caps, but not realized consumption: B2 spent about four times B1's budget; no evaluator implements the frozen realized-cost checkpoints, nor the reservation-before-execution and retrospective settlement of candidate.3 (the rules exist only in `docs/spec/sai35/semantic_reference.py`); equal caps on any line are not matched realized cost |
| S35-CMP-003 | proposed | — | no blinded scoring of discovery outputs; the offline run was scored by its author |
| S35-CMP-004 | proposed | — | the offline worlds share an author with the engine; protocol and tooling for an independent hidden-world evaluation are on discovery-independent-evaluation @ d7ec9f2 (pushed, not reviewed); no independent worlds yet |
| S35-CMP-005 | partial | `118a4ac:src/lab_brain/discovery/metrics.py` | offline correct outcome, false discovery, class diversity and budget metrics; its class diversity is a transitive count, not the certified diversity of candidate.2; no scorer separates the nine outcome categories of candidate.3 (Appendix S §6); no independent reproducibility |
| S35-CMP-006 | partial | `118a4ac:src/lab_brain/discovery/metrics.py`<br>`f41758c:src/lab_brain/evaluation/stats.py` | Wilson and bootstrap intervals exist; no evaluator-frozen statistical plan |
| S35-CMP-007 | partial | `f41758c:src/lab_brain/evaluation/contamination.py` | G0 contamination tooling on the unintegrated G0 line; no G-D contamination report |
| S35-CMP-008 | partial | `118a4ac:src/lab_brain/discovery/benchmark.py` | offline per-case budget stops; no study-level or incident rules |
| S35-CMP-009 | partial | `118a4ac:docs/audit/discovery-loop-offline-2026-11-01/REPORT.zh-TW.md` | the offline run was zero-cost engineering evidence, not a G-D stage reported to the Owner |

## 5. Notes on the evidence

- **Offline Discovery Loop (`118a4ac`).** 200 worlds, matched budget caps of 12 units, Wilson 95%
  intervals: correct outcome B0 0.08, B1 0.31, B2 0.89; false discovery B0 0.37, B1 0.25, B2 0.01;
  B2 spent about four times B1's budget and was worse per correct outcome. The worlds and the engine
  share an author and the forward models are toy linear models. This is **engineering evidence about
  synthetic worlds**: not a G-D1 verdict, not independent or blind, and not evidence of discovery
  capability (S35-GOV-004). B0 is a deterministic stand-in, not an LLM; B1 re-implements the loop
  policy, not the real LIB workflow. The loop never invokes the Causal Warrant Gate; it emits a
  hand-over packet with status pending.
- **G0 line (`f41758c`) and the read-path closure.** Engineering evidence: each rule has failing-then-
  passing tests and mutation entries. No real-LLM research result, no blind evaluation and no
  physical validation exists on either branch. The read-path fix is unmerged and unaudited.
- **Licensed simulation, model construction, refinement, physical validation.** Absent on every line.
  This is a gap in implementation and also an external gate (license, data); not only the external
  gate.

## 6. Open risks

| Risk | State |
|---|---|
| G0 line unintegrated and unaudited | P35-1 cannot start until the audit and OD-09 |
| forged-authorization read path on WS1 | fixed on the unmerged branch, pending audit; S35-REG-001, S35-REG-004 and S35-CWG-002 depend on it |
| A3, A9, A12 open | identity independence and database-authority limits unresolved (SAI 3.4) |
| implementer-written synthetic worlds | not G-D evidence; the independent evaluation is still in design |
| arm A missing | no single-LLM arm exists on any line |
| matched budget by caps only | realized consumption differed fourfold offline; S35-CMP-002 (candidate.2) requires scoring at frozen realized-cost checkpoints; no evaluator implements it |
| transitive mechanism classes in the prototype | `118a4ac` and its descendants count connected components; any metric computed that way is not an S35-MECH-001 figure |
| force-fit when the true family is absent | measured on `d7ec9f2` (same-author worlds); S35-MECH-002 now forbids it; the offline safety gate cuts it about tenfold but lowers low-budget in-catalog accuracy; parameters OD-18 open |
| services' role can register transition policies (G0 finding F2) | closed on the unmerged branch `claude/lib-implementation-agent-47evs0-g0-f2` @ `24fae8b` (Owner-approved owner-only registration); open on every other line until integrated; residual R-2 (`diagnostic_declaration_sets`) has the same shape |
| three unintegrated lines plus this candidate | integration order is OD-09 |
