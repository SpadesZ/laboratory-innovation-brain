# M1 — Research Memory: readiness for independent M2 sign-off

Date: 2026-09-22; revised after the final audit (§9) and the second audit (§10)
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

**R-7 - CLOSED, and it was not closed by the previous repair.** The first attempt routed all four
surfaces through `ScientificReadGate` and then kept exporting the ACL-free loader as
`IngestionService.unauthorized_reader()`, on the theory that the name was the contract. It is not.
A production composition root that returns a canonical-body loader answering to nobody has a public
bypass whatever it is called -- and the M1 vertical itself was calling it to fetch bodies, which is
the strongest possible demonstration that the path was reachable.

| Surface | Before | After |
|---|---|---|
| `CandidateResolver` | occurrence presence only | `AuthorizedCandidateResolver`: descriptor -> ACL -> body |
| `IngestionService.evidence_for` | took no Actor | requires `actor_id`; one descriptor query, bodies only for ALLOW |
| `PostgresEvidenceUnitReader` | exported as `unauthorized_reader()` | **no accessor at all**; a private field of the trusted paths |
| `DiagnosticsService` | its own ordered clearance comparison | delegates to `ProjectMembership.clears`, the predicate `can_read_artifact` uses |

**The ordering is now the implementation and not only the docstring.** `AuthorizedCandidateResolver`
documented "authorize, THEN load" while doing the opposite: it needed `unit.artifact_id` to ask the
question, so it loaded every candidate and filtered afterwards. The filter was correct and the
RESTRICTED_NDA body of every refused unit had already been materialized in the process that was
about to decide it may not be. `UnitSecurityDescriptor` -- two ids, no text -- is what the decision
now consults, and `PostgresEvidenceUnitReader.artifact_of` / `security_index_for_project` are the
reads that produce one.

Fourteen probes in `security/test_scientific_read_authorization_postgres.py`. Three are structural
rather than behavioural, because the claims are structural:

* `test_the_composition_root_exposes_no_raw_reader` walks the PUBLIC surface and fails if any
  method returns the reader -- so re-adding the capability under a nicer name fails too.
* `test_an_unauthorized_body_is_never_loaded_by_the_authorized_path` supplies a loader that
  **raises if entered**, so a refused read reaching it fails loudly rather than producing a
  passing assertion about an empty list.
* `test_the_boundary_contains_no_second_acl` parses the module and fails if it grows its own
  `SensitivityLabel` comparison.

**R-11 - NARROWED, residual stated precisely.** `execution_spans.job_id` still carries no foreign
key and `010a` is applied, so it cannot gain one by edit. What changed is that a span naming a job
is now *checkable*: `jobs.episode_id` is a real foreign key (`006b`), `runs.job_id` is UNIQUE,
`jobs.result_run_id` is write-once, and `006a`'s deferred trigger makes an unclaimed Run
unrepresentable. **OPS-003 is not reopened** and stays DONE under the M0b lock.

## 6. Verification

Local, full history, PostgreSQL last.

| Gate | Result |
|---|---|
| `ruff format --check` / `ruff check` | clean |
| `mypy` (strict) | clean, **109** source files |
| Backend-free suite | **1133 passed**, 567 skipped |
| Migration replay from empty | **36 applied** |
| Migration idempotency | `pending 0` |
| Full PostgreSQL profile | **1700 passed** |
| Executed-coverage ratchet | ok ×4; DONE `['M0a','M0b']`, IN_PROGRESS `['M1']` |
| Status freshness | up to date |
| Spec conformance | **205 passed** |
| Requirement ↔ Test | **60 ↔ 60** |
| Obligation inventory | **84**, in sync |
| Schema drift / unbound / stale | all empty |
| Mutation battery | **66/66 killed** (29 M1-P1 + 21 + 8 + 8 second-audit) |
| M1-P1 benchmark | current, framing unchanged |

### Local vs generic CI counts

The two history-dependent commit-hygiene tests skip in shallow generic jobs and pass in the
dedicated full-history `Commit hygiene` job. This is designed behaviour, recorded at the M1-P1
lock, and is **not a regression**. Do not make those two assert unconditionally: a green test
that checked no commits is worse than an honest skip.

## 7. Remaining risks and limitations

1. **No LLM slot is configured.** `ScientificLLM` runs against a deterministic transport. What is
   proven is the provenance discipline, the SEC-001 ordering and the atomicity of
   `ScientificInferenceService.infer`, not that a model was called.
2. **No Lumerical seat (R-1), no ground-truth benchmark (R-2).** Unchanged.
3. **Section 17.3 is a declared subset.** Ten fields are absent, each because the entity it
   references does not exist yet; `006b`'s header lists every one with the requirement that brings
   it. `job_ids[]`/`run_ids[]` are *refused* rather than deferred - 17.8 forbids the
   parallel-array shape, so membership is a query.
4. **The dense index is in-memory.** `009a`/`009b` hold `RetrievalRepresentation` rows and
   `DenseEvidenceIndex` does not yet write to them. EVI-007's semantics are enforced and tested;
   the durable vector store is not built.
5. **`technical_detail_ref` resolves to nothing.** `012` stores it as a pointer and no detail
   store backs it, so `explain --technical` for an actor holding the scope returns the default
   payload. Conservative in the right direction - the scope check, the redaction and the
   not-found semantics are all still the service's, and `DiagnosticsService` is not told detail
   exists when it does not.
6. **`NEEDS_REVIEW` is unreachable from durable rows.** §17.19.1's `subject_type` vocabulary is
   `CONFLICT | AUTHORITY_CONFLICT`, so no `ReviewItem` can point at an `IngestionItem` and
   `PostgresSurfaceStore` returns empty `review_ids`/`conflict_ids`. The derivation is proven at
   the projection level; inventing a subject type to fill the field would be a spec change
   smuggled in as a query, so it is stated instead.
7. **Error-id minting is bounded-retry, not sequenced.** `ERR-YYYYMMDD-NNNN` is computed from the
   day's maximum ordinal and retried on a primary-key collision. Correct under M1's single-writer
   ingestion and honest about its bound: a genuinely concurrent writer would need a sequence, and
   `SurfaceStoreError` names the situation rather than reusing an id.
8. **COST-001 is wired as a required seam, not as a live caller.** `decide_retry` refuses without
   a budget gate, and the tests inject both an allowing and a refusing one. No production loop
   retries yet, so the gate has no live caller to exercise.
9. **R-8, R-9, R-10, R-12** unchanged.

## 8. Governance

No SPEC-ISSUE was raised. Every requirement implemented here had a §26 pass condition that
determined the behaviour; where a reading was tight — UX-005's "parallel review surface", §7.6's
"sole basis", EVI-009's "produced Artifact(s)" — the narrower reading was implemented and the
reasoning recorded in the module that implements it.

`011h` extends `review_items.subject_type` by one member. That is a vocabulary extension, not a
change to M0b semantics, and `test_m0b_conflict_review_behaviour_is_unchanged` asserts it.


## 9. The final-audit repairs

| # | Blocker | Before | After |
|---|---|---|---|
| 1 | scientific reads bypass the ACL | four surfaces answered four different questions; an INTERNAL-cleared member received RESTRICTED_NDA bodies | one `ScientificReadGate` over `can_read_artifact`; 11 probes; **R-7 closed** |
| 2 | SEC-001 bypassable | `SourceRouter.search` and `ScientificLLM.invoke` reached transports directly | `AuthorizedExternalRunner` is a **required** constructor argument; `execute()` performs only on ALLOW; 16 probes with fatal spies |
| 3 | provenance not persisted | an in-memory object the vertical called "persisted" | `003d` + `SqlInferenceProvenanceStore`, append-only; write to new connection to reload to exact model equality; `BeliefBasisGate` reads the durable record |
| 4 | BudgetGate fail-open | `charge_budget=None` returned `retry=True` | no gate produces `BUDGET_GATE_UNAVAILABLE`, POLICY_BLOCK, audited, no retry; mutation anchor on the guard |
| 5 | "resumes episode" was a Job reload | a Job surviving a restart | `006b` + `ResearchEpisode`; episode suspends, a new connection finds it parked, the **same** episode resumes, the Run lands on its trace |
| 6 | `012` and the CLI missing | neither existed | `012_ingestion_items_errors.sql` with no `state` column; `lab-brain inbox` / `explain` at the entry point `pyproject.toml` has declared since M0a |

### The durable proofs, named

**persist provenance** -
`integration/test_durable_provenance_and_episodes_postgres.py::test_provenance_survives_a_new_connection_with_exact_equality`
and `e2e/test_m1_vertical_postgres.py::test_the_whole_m1_vertical_is_durable_and_authorized`
step 8: written through one connection, read through a `psycopg.connect(...)` that shares nothing,
`reloaded == written == output.provenance`, and the stored hash equals `bundle.canonical_hash`.

**resume episode** -
`...::test_the_episode_itself_suspends_and_resumes_across_a_reload` and the vertical's steps 1-3:
`episode_suspend`, then a new connection observes SUSPENDED and `found == parked`, then
`episode_resume` on that connection, then `resumed.episode_id == EPISODE`, `jobs_of(EPISODE)`
resolves, and the Run carries the episode's `trace_id`.

### What the battery found in this repair

`a_suspended_episode_need_not_record_when` **genuinely survived**. Every test reached the model
through `episode_suspend`, which sets state and timestamp in one statement, so `ResearchEpisode`'s
own validator was never what caught a contradictory pair - a reader would have believed it
load-bearing while a direct constructor call (a replay, a fixture, a backfill) produced a
SUSPENDED episode with no `suspended_at`, which a resumer reads as "parked at the epoch". Two
probes added; it now dies. One further anchor was stale after the budget restructure and was
re-anchored on the reclassification rather than deleted.


## 10. The second-audit repairs

The first four blockers were accepted. These four were the production-path half: each was a place
where a guard existed and the production wiring did not reach it, or reached around it.

| # | Blocker | Before | After |
|---|---|---|---|
| 1 | R-7 not closed | `unauthorized_reader()` exported; the resolver loaded then filtered | accessor deleted; `UnitSecurityDescriptor` -> ACL -> body; 14 probes, three structural |
| 2 | classification was caller-supplied | `invoke(sensitivity=PUBLIC)` over NDA evidence: the gate answered correctly about a fiction | `ContextClassifier` derives from `ArtifactOccurrence`; `escalate` is a union, so there is no downgrade operator |
| 3 | call and write were two operations | `invoke(); record_inference()` -- a crash between them left an output with no provenance | `ScientificInferenceService.infer`: authorize -> invoke -> write -> reload -> compare; `DurableInference` is the only object carrying text |
| 4 | CLI printed a wiring message | `main` exited 2; nothing wrote `012` rows | `PostgresSurfaceStore` writes them; `main` opens its own connection from one explicit config boundary |

### The attacks, before and after

**1. Read a body you may not read.** *Before:* `svc.unauthorized_reader().load_for_project(p)` --
one public call, every canonical body, no Actor. *After:* the method does not exist, and
`test_the_composition_root_exposes_no_raw_reader` fails if anything returns the reader.

**1b. Materialize a refused body.** *Before:* `resolve()` loaded every candidate to read
`unit.artifact_id`, then filtered. *After:* the descriptor answers the question; the probe's
loader raises if entered.

**2. Send NDA material declared PUBLIC.** *Before:* a supported call. *After:*
`derived | declared` -- `test_a_caller_cannot_declare_nda_context_as_public` and the vertical's
`test_external_egress_cannot_bypass_the_gate` both attempt the downgrade against a transport that
raises if entered.

**2b. Launder classification through an unresolvable reference.** *Before:* n/a. *After:*
`require_artifacts` refuses an unresolved reference and an empty set; `ExternalEffect.__post_init__`
refuses it again so the bad state is unrepresentable. Both layers have their own probe, because
the battery showed the outer one surviving behind the inner one.

**3. Use an inference whose provenance was never written.** *Before:* the caller held the text and
was trusted to call `record_inference`. *After:* `infer` does not return until the row reloads
equal; the fault-injection probe fails the write **after** the model was called
(`transport.calls == 1`) and asserts the exception names the write, carries no model text, leaves
no row, and is refused by `BeliefBasisGate`.

**4. Report on the wrong database, or on nothing.** *Before:* `lab-brain inbox` exited 2 always.
*After:* real rows, real connection, real `main()`. `test_the_command_refuses_to_guess_a_connection`
pins that there is no default DSN, and
`test_an_unknown_and_a_foreign_error_are_indistinguishable_through_the_real_command` pins §17.24's
oracle rule at the command rather than at the service.

### The durable proofs, named

**production ingestion -> durable `012` rows -> new process -> CLI output** --
`integration/test_cli_surface_postgres.py::test_production_ingestion_writes_the_rows_the_inbox_reads`
then `::test_the_real_command_loads_durable_rows_and_renders_derived_state`, and the vertical's
step 11: `main(["inbox", ...], env={LAB_BRAIN_DATABASE_URL: ...})` opens its own connection and
prints `READY=1` with the item id. `::test_a_failed_parse_shows_as_failed_through_the_real_command`
is the control that the state is derived rather than constant.

**atomic inference** --
`integration/test_durable_provenance_and_episodes_postgres.py::test_one_operation_calls_the_model_and_leaves_the_record_durable`
and `::test_a_failure_between_the_model_call_and_the_write_yields_no_usable_output`, plus the
vertical's step 7, which calls `svc.inference_service(...).infer(...)` and no longer composes
`invoke(); record_inference()` anywhere.

### One migration was repaired

`012a_duplicate_is_content_identity.sql` drops `ingestion_items_not_its_own_duplicate`. The CHECK
read as an obvious sanity rule and was, under ART-001, unsatisfiable for the only case it
described: identical bytes are the *same* artifact, so a duplicate item's
`duplicate_of_artifact_id` necessarily equals its `raw_artifact_id`. It forbade the correct value
and permitted only wrong ones. Forward-only, because editing an applied file is what the checksum
guard exists to catch. Nothing else in `012` moved -- no `state` column, both retry CHECKs and the
deferred stage/error trigger are untouched.

### What the battery found in this repair

Two mutations survived on the first run and both were the same shape: **a second layer masking the
first**. `an_unclassifiable_context_reads_as_unrestricted` survived because
`ExternalEffect.__post_init__` caught what `require_*` was supposed to; `a_failed_write_still_returns_the_model_text`
survived because the post-commit absence check caught what the write's `except` was supposed to.
Both layers are wanted, and defence in depth that is only *tested* in depth is one edit away from
being a single layer. Each now has its own probe.

Two further anchors were **stale** after the descriptor restructure (`ANCHOR NOT FOUND`) and were
re-anchored rather than deleted -- an anchor that stops applying is a guard nobody is checking any
more. Re-anchoring surfaced a genuine gap: no probe covered
`candidate.project_id != project_id`, the §17.25.1 scope check that drops a foreign candidate
before any query runs. It has one now, with both loaders fatal.

Final: **66/66 killed.**
