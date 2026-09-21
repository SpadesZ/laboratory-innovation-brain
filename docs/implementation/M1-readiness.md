# M1 — Research Memory: readiness for independent M2 sign-off

Date: 2026-09-22
Milestone: **M1 — Research Memory**, `IN_PROGRESS`
M1-P1 locked baseline: `f8e5e9c02ee98ed2a7faa6f604347b84b88c773b` (HARD-LOCKED, untouched)
M0a / M0b: `DONE`, hard-locked, untouched
Spec: SAI 3.3, amendments `v3.3-a1` … `v3.3-a18`. **No amendment, no ADR, no new Requirement or
Test ID was added by this work.** 60 ↔ 60 throughout.

> This document claims readiness for audit, not completion. M1's status is the maintainer's to
> change, and it is still `IN_PROGRESS` in `docs/milestones.yaml`.

## 1. The exit gate, clause by clause

> local document/run ingest; source-work dedup; delayed mock job resumes episode; all scientific
> LLM calls persist bundle+provenance; UX-001~UX-007 tests pass.

| Clause | Where it is demonstrated |
|---|---|
| local **document** ingest | `e2e/test_m1_vertical_postgres.py::test_the_whole_m1_vertical_runs_through_production_composition`, through `IngestionService` |
| local **run** ingest | same test — the ingestion *is* a Run, minted by `job_complete` and carrying the §17.4 manifest |
| source-work dedup | `contract/test_source_work_resolution.py` (EVI-004) + `contract/test_ingestion_surfaces.py::test_a_same_work_duplicate_is_ready_and_keeps_its_attestation` |
| delayed mock job resumes | the vertical's step 1: submit → RUNNING → WAITING_RESOURCE → **new connection** → resume → one Run |
| LLM calls persist bundle+provenance | vertical step 6 + `contract/test_llm_and_sources.py` (11 tests) |
| UX-001~UX-007 pass | `contract/test_ingestion_surfaces.py` (38), `security/test_diagnostics_disclosure.py` (11), `integration/test_extraction_review_postgres.py` (9), `e2e/test_stage_retry_resume_postgres.py` (5) |

## 2. Requirement-by-requirement readiness

| # | Requirement | §26 pass condition (abridged) | Implementation | Tests | Status |
|---|---|---|---|---|---|
| 1 | **EVI-002** | parser 缺欄位時輸出 UNKNOWN/NOT_REPORTED，不得生成 default scientific value | `admission_gate._check_no_invented_values`, `parsers/documents._clean_unit` | `contract/test_evidence_admission.py` | READY |
| 2 | **EVI-003** | LLM interpretation cannot be admitted as observed/simulated evidence | `admission_gate._check_inference` (provenance-derived, tri-state flag) | `contract/test_evidence_admission.py`, `test_evidence_repair_probes.py` | READY |
| 3 | **EVI-004** | preprint/journal/review resolve to one work; DEPENDENCE_UNKNOWN contributes 0 | `ingestion/source_work_resolution.py`, `evidence/independence.py` | `contract/test_source_work_resolution.py` | READY |
| 4 | **EVI-007** | mixed embedding versions never compared; dual-index migration preserves benchmark recall before cutover | `evidence/dense_index.py` — `EmbeddingSpace`, `DenseEvidenceIndex`, `DualIndexCutover` | `contract/test_dense_retrieval.py` (18) | READY |
| 5 | **EVI-008** | retracted/erratum fixture records source status and blocks/flags per SourcePolicy | `evidence/source_status.py` — check writes, decision reads the record | `integration/test_source_status_postgres.py` (10) | READY |
| 6 | **EVI-009** | MEASURED/SIMULATED refused with no run/artifact ref; reference resolves; back-fill refused | `admission_gate._check_reference` + `_check_run_reference` (resolves → produced → in-project) | `contract/test_evidence_admission.py`, `test_run_backed_evidence.py` (14) | READY |
| 7 | **EVI-010** | locked fixture, five cases, seven metrics, tampered payload cannot alter the body | locked at M1-P1; untouched | 222 tests over the locked surface | READY (locked) |
| 8 | **LLM-001** | provenance at admission **and** a stored inference without it cannot be the sole basis of a transition | `cognition/llm.py` — `ScientificLLM` + `BeliefBasisGate` | `contract/test_llm_and_sources.py` (11 LLM) | READY |
| 9 | **OPS-001** | delayed mock job 可 suspend/resume；重複 completion event 不建立第二個 run | `006`/`006a`, `core/models/job.py`, `repositories/jobs.py` | `contract/test_job_lifecycle.py` (29), `integration/test_jobs_runs_postgres.py` (28) | READY |
| 10 | **OPS-004** | fault injection between artifact store and DB commit leaves no dangling reference | `pipeline._store_raw`; boundary now owned by `composition.IngestionService` | `integration/test_cross_store_compensation.py` | READY |
| 11 | **SEC-001** | RESTRICTED_NDA 送 external connector 時被阻擋並留下 audit event | `security/egress.py` — `EgressGate`, `EgressAuditLog` | `security/test_egress_and_licensing.py` (10 SEC-001) | READY |
| 12 | **SEC-003** | fixture secret quarantined before immutable ingest | `ingestion/secret_scanner.py`, `pipeline._run_secret_scan` | `security/test_secret_scan_ordering.py` | READY (locked) |
| 13 | **SEC-004** | UNKNOWN/COPYLEFT blocked from generation context unless policy permits | `security/egress.may_enter_generation_context` | `security/test_egress_and_licensing.py` (7 SEC-004) | READY |
| 14 | **SRC-001** | fake connectors replace real providers without changing SourceRouter/cognition | `sources/adapter.py` | `contract/test_llm_and_sources.py` (6 SRC) | READY |
| 15 | **UX-001** | every documented state through the precedence; no direct assignment; two duplicate semantics | `surface/ingestion_item.py` | `contract/test_ingestion_surfaces.py` | READY |
| 16 | **UX-002** | POLICY_BLOCK/USER_INPUT_ERROR zero retries + audit; bounded retry; budget exhaustion is POLICY_BLOCK | `surface/errors.py` | `contract/test_ingestion_surfaces.py` | READY |
| 17 | **UX-003** | no technical detail by default; scope required; clearance redaction keeps trace refs; cross-project not-found | `surface/disclosure.py` — `DiagnosticsService` | `security/test_diagnostics_disclosure.py` (11) | READY |
| 18 | **UX-004** | raw artifact durable; retry re-runs only the failed stage reusing `raw_artifact_id`; duplicate callbacks create no second Run | `pipeline.resume`, `composition.IngestionService.retry` | `e2e/test_stage_retry_resume_postgres.py` (5) | READY |
| 19 | **UX-005** | low-confidence extraction creates a ReviewItem visible in queue depth and changes Capability availability | `011h` + `SqlReviewItemStore.enqueue_extraction_review` | `integration/test_extraction_review_postgres.py` (9) | READY |
| 20 | **UX-006** | every reason_code resolves; unknown fails closed to a generic entry; no render path invokes a model | `surface/catalog.py` | `contract/test_ingestion_surfaces.py` | READY |
| 21 | **UX-007** | Capability unavailable + connector degraded reflected without a status table; seat exhaustion is degraded, not error | `surface/health.py` | `contract/test_ingestion_surfaces.py` | READY |

## 3. The three audit repairs

| | Before | After |
|---|---|---|
| **A** — partial Run manifest | `job_complete` took 13 of §17.4's 21 fields; eight were silently replaced by column defaults, so `InMemoryJobStore` kept them and `SqlJobStore` did not | `006a` takes all 21. A shared scenario builds a Run with nothing at its default and asserts canonical model equality after round-trip, against both stores |
| **A** — linkage | PostgreSQL *derived* `trace_id`/`capability_id`; in-memory ignored them. A contradictory callback was silently corrected in one backend and silently trusted in the other | One shared `check_run_linkage` table over four fields, checked never derived, plus `006a`'s trigger for writers that never call a repository |
| **B** — second completion path | `add_run` was INSERT-then-UPDATE; a durable Run could exist with `jobs.result_run_id IS NULL` | `add_run` **deleted**. Failed runs go through `job_complete` (which required letting a FAILED job name its Run). The pairing is enforced at COMMIT by a deferred constraint trigger, both directions |
| **C** — forged artifact provenance | `output_artifacts=["art:does-not-exist"]` backed a MEASURED attestation; a TEXT[] element cannot carry a foreign key | The chain is walked: Artifact resolution + ADR-0010 occurrence presence, two new refusal codes |

## 4. Production composition

```
IngestionService (lab_brain/composition.py)
  submit ──────────────► jobs.submit                 Job durable before any work
  suspend / resume ────► jobs.transition             WAITING_RESOURCE survives a reload
  ingest ──┬───────────► IngestionPipeline
           │              SECRET_SCAN → RAW_STORE → parse → segment
           ├── commit_rows ──► [txn] artifact + occurrence   ← boundary owned HERE
           ├── persist_evidence ─► [txn] units + occurrences ← boundary owned HERE
           └── jobs.complete ──► job_complete (own row lock) ← OUTSIDE both txns
  evidence_for ────────► PostgresEvidenceUnitReader   rebuilt through the model
  admission_gate ──────► EvidenceAdmissionGate        every resolver supplied
```

Three boundaries, not one, because they fail differently. The artifact store is not
transactional — OPS-004's compensation owns that. A single enclosing transaction would be either
too short to protect the evidence write or too long to let a concurrent completion run.

## 5. R-7 and R-11

**R-7 — MITIGATED, NOT CLOSED.** `IngestionService.admission_gate` is a production composition
root that routes the admission read path through `can_read_artifact` — the one ACL
implementation — and supplies every fail-closed resolver, so none of those branches is reached by
misconfiguration. That is a real narrowing.

It does not close, and the uncovered surfaces are named rather than implied:

1. **Retrieval** — `CandidateResolver` checks occurrence presence (§17.25.1) and does **not**
   consult `can_read_artifact`. A project member with insufficient sensitivity clearance can
   retrieve a candidate whose artifact they could not read directly.
2. **Diagnostics** — `DiagnosticsService` implements its own clearance comparison against
   `SensitivityLabel` rather than calling the ACL. The behaviour agrees today; two copies of one
   rule is what ADR-0012's shape exists to avoid.
3. **Evidence read** — `PostgresEvidenceUnitReader` deliberately enforces no ACL, by design and
   documented in its own header.

Closing R-7 requires those three to route through one boundary. That is a coherent slice and not
this one.

**R-11 — NARROWED, and the residual is different in kind.** `execution_spans.job_id` still
carries no foreign key, and `010a` is applied so it cannot gain one by edit. What has changed is
that Jobs and Runs are now real, durable and internally consistent: `runs.job_id` is UNIQUE and
checked, `jobs.result_run_id` is a real foreign key and write-once, and `006a`'s deferred trigger
makes an unclaimed Run unrepresentable. A span naming a job can now be *checked* by a join, which
was impossible before. **OPS-003 is not reopened** — it stays DONE under the M0b lock.

## 6. Verification

Local, full history, PostgreSQL last.

| Gate | Result |
|---|---|
| `ruff format --check` / `ruff check` | clean |
| `mypy` (strict) | clean, **98** source files |
| Backend-free suite | **1089 passed**, 516 skipped |
| Migration replay from empty | **32 applied** |
| Migration idempotency | `pending 0` |
| Full PostgreSQL profile | **1605 passed** |
| Executed-coverage ratchet | ok ×4; DONE `['M0a','M0b']`, IN_PROGRESS `['M1']` |
| Status freshness | up to date |
| Spec conformance | **205 passed** |
| Requirement ↔ Test | **60 ↔ 60** |
| Obligation inventory | **84**, in sync |
| Schema drift / unbound / stale | all empty |
| Mutation battery | **50/50 killed** (29 M1-P1 + 21 new) |
| M1-P1 benchmark | current, framing unchanged |

### Local vs generic CI counts

The two history-dependent commit-hygiene tests skip in shallow generic jobs and pass in the
dedicated full-history `Commit hygiene` job. This is designed behaviour, recorded at the M1-P1
lock, and is **not a regression**. Do not make those two assert unconditionally: a green test
that checked no commits is worse than an honest skip.

## 7. Remaining risks and limitations

1. **R-7 uncovered read surfaces** — three, named in §5.
2. **No LLM slot is configured.** `ScientificLLM` is exercised against a deterministic
   transport. What is proven is the *provenance discipline*, not that any model was called.
3. **No Lumerical seat (R-1), no ground-truth benchmark (R-2).** Unchanged.
4. **Episodes do not exist.** §17.3's `ResearchEpisode` is not built, so `Job.episode_id` is
   nullable and unchecked, and the vertical's "resumes an episode" is demonstrated as a Job
   resuming across a durable reload. This is the honest reading of what exists.
5. **The dense index is in-memory.** `009a`/`009b` hold `RetrievalRepresentation` rows and
   `DenseEvidenceIndex` does not yet persist to them. EVI-007's *semantics* are enforced and
   tested; the durable vector store is not built.
6. **`InferenceProvenance` has no table.** It is produced, validated and carried; persisting it
   belongs with the belief-path slice that consumes it (M3's `EPI-001`).
7. **UX-002's BudgetGate integration is a seam.** `decide_retry` takes `charge_budget` and the
   tests inject a refusal; COST-001's real gate is wired by the caller, and no production caller
   retries yet.
8. **R-9, R-8, R-10, R-12** unchanged.

## 8. Governance

No SPEC-ISSUE was raised. Every requirement implemented here had a §26 pass condition that
determined the behaviour; where a reading was tight — UX-005's "parallel review surface", §7.6's
"sole basis", EVI-009's "produced Artifact(s)" — the narrower reading was implemented and the
reasoning recorded in the module that implements it.

`011h` extends `review_items.subject_type` by one member. That is a vocabulary extension, not a
change to M0b semantics, and `test_m0b_conflict_review_behaviour_is_unchanged` asserts it.
