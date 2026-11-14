# M1 — Research Memory: readiness for independent M2 sign-off

Date: 2026-09-23; revised after the final audit (§9), the second audit (§10), the third (§11) and
the closing security repair (§12)
Milestone: **M1 — Research Memory**, **`DONE` / HARD-LOCKED**
M1 hard-lock SHA: `bdb72129a1075d69a30f5043a3491570ca7d4521`
M1-P1 locked baseline: `f8e5e9c02ee98ed2a7faa6f604347b84b88c773b` (HARD-LOCKED, untouched)
M0a / M0b: `DONE`, hard-locked, untouched
Spec: SAI 3.3, amendments `v3.3-a1` … `v3.3-a18`. **No amendment, no ADR, no new Requirement or
Test ID was added by this work.** 60 ↔ 60 throughout.

> **Maintainer decision (2026-09-23).** Independent review signed off at
> `bdb72129a1075d69a30f5043a3491570ca7d4521`: **PASS — M1 DONE / HARD-LOCK APPROVED**. From that
> commit the executed-coverage ratchet enforces M1 on every CI run, exactly as it has enforced M0a
> since 2026-09-13 and M0b since 2026-09-20.
>
> The sentence this section used to carry — *"This document claims readiness for audit, not
> completion. M1's status is the maintainer's to change, and it is still `IN_PROGRESS`"* — is left
> recorded rather than deleted. It was true of the milestone when it was submitted, and the record
> of a claim being withheld and then granted is worth more than a document that reads as if the
> outcome were never in doubt. `M1-P1-readiness.md` §12 keeps the same shape for the same reason.
>
> **Reopen M1 only on a reproducible violation of a locked invariant** — not for cleanup, not for a
> refactor that would read better. The 21 requirements are now ratchet-enforced, so a regression in
> any of them fails CI rather than being noticed.

## 1. The exit gate, clause by clause

> local document/run ingest; source-work dedup; delayed mock job resumes episode; all scientific
> LLM calls persist bundle+provenance; UX-001~UX-007 tests pass.

Every row points at the evidence as it stands after the third repair. Earlier revisions of this
table named tests that have since been rewritten or that proved a weaker claim than the clause
makes; those descriptions are corrected here rather than preserved, because a readiness document
whose citations no longer resolve is worse than one with fewer rows.

| Clause | Where it is demonstrated |
|---|---|
| local **document** ingest | `e2e/test_m1_vertical_postgres.py::test_the_whole_m1_vertical_is_durable_and_authorized` steps 4–5, through `IngestionService` |
| local **run** ingest | the same test — the ingestion *is* a Run, minted by `job_complete` with the whole §17.4 manifest (`006a`) |
| source-work dedup | `contract/test_source_work_resolution.py` (EVI-004) + the vertical's `test_repeated_ingestion_stays_idempotent_by_derived_identity` |
| delayed mock job resumes **episode** | the vertical's steps 1–3: `episode_suspend` → **new connection** observes SUSPENDED → `episode_resume` → the *same* episode → the Run carries its trace. Not a Job reload; see §9. |
| **all** scientific LLM calls persist bundle+provenance | the vertical's step 7 calls `ScientificInferenceService.infer`, which does not return until the row reloads equal (`integration/test_durable_provenance_and_episodes_postgres.py`, 25 tests). The *all* is structural: `ScientificLLM`'s only public attribute is `configured_slots`, so no public surface returns unpersisted text — `test_no_public_method_anywhere_returns_unpersisted_scientific_output`. |
| UX-001~UX-007 pass | `contract/test_ingestion_surfaces.py` (38) and `contract/test_budget_and_cli.py` (18) for the projections; `integration/test_inbox_authorization_postgres.py` (17) and `integration/test_cli_surface_postgres.py` (18) for the same projections **through the real `main()` over durable rows**; `integration/test_extraction_review_postgres.py` (9); `e2e/test_stage_retry_resume_postgres.py` (5) |

All seven `ItemState` values are now reached from durable PostgreSQL rows through the shipped
command — READY, PROCESSING, NEEDS_REVIEW, DUPLICATE, PARTIAL, FAILED, BLOCKED — with §17.22's
precedence asserted rather than assumed. See §11.

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
| 8 | **LLM-001** | provenance at admission **and** a stored inference without it cannot be the sole basis of a transition | `cognition/inference.py` — `ScientificInferenceService.infer/critique`, the only public source of scientific text; `cognition/llm.py` is an internal seam; `003d` is the durable record | `integration/test_durable_provenance_and_episodes_postgres.py` (25), `contract/test_llm_and_sources.py` (21) | READY |
| 9 | **OPS-001** | delayed mock job 可 suspend/resume；重複 completion event 不建立第二個 run | `006`/`006a`, `core/models/job.py`, `repositories/jobs.py` | `contract/test_job_lifecycle.py` (29), `integration/test_jobs_runs_postgres.py` (28) | READY |
| 10 | **OPS-004** | fault injection between artifact store and DB commit leaves no dangling reference | `pipeline._store_raw`; boundary now owned by `composition.IngestionService` | `integration/test_cross_store_compensation.py` | READY |
| 11 | **SEC-001** | RESTRICTED_NDA 送 external connector 時被阻擋並留下 audit event | `security/egress.py` + `security/external.py` (mandatory runner) + `security/classification.py` (derived, never declared) | `security/test_external_effect_authorization.py` (26), `security/test_egress_and_licensing.py` (10) | READY |
| 12 | **SEC-003** | fixture secret quarantined before immutable ingest | `ingestion/secret_scanner.py`, `pipeline._run_secret_scan` | `security/test_secret_scan_ordering.py` | READY (locked) |
| 13 | **SEC-004** | UNKNOWN/COPYLEFT blocked from generation context unless policy permits | `security/egress.may_enter_generation_context` | `security/test_egress_and_licensing.py` (7 SEC-004) | READY |
| 14 | **SRC-001** | fake connectors replace real providers without changing SourceRouter/cognition | `sources/adapter.py` | `contract/test_llm_and_sources.py` (6 SRC) | READY |
| 15 | **UX-001** | every documented state through the precedence; no direct assignment; two duplicate semantics | `surface/ingestion_item.py` (derivation), `storage/postgres/surface_store.py` (durable rows + review/conflict/job projection), `interfaces/cli.py` | `contract/test_ingestion_surfaces.py`, `integration/test_inbox_authorization_postgres.py` — all seven states through the real command | READY |
| 16 | **UX-002** | POLICY_BLOCK/USER_INPUT_ERROR zero retries + audit; bounded retry; budget exhaustion is POLICY_BLOCK | `surface/errors.py` | `contract/test_ingestion_surfaces.py` | READY |
| 17 | **UX-003** | no technical detail by default; scope required; clearance redaction keeps trace refs; cross-project not-found | `surface/disclosure.py` — `can_access_project` **unconditionally**; `actor_of` is a required constructor argument, so there is no membership-presence mode to construct (§12) — plus `012b`'s `technical_details` | `security/test_diagnostics_disclosure.py` (19), `integration/test_cli_surface_postgres.py` — all five outcomes through the real command | READY |
| 18 | **UX-004** | raw artifact durable; retry re-runs only the failed stage reusing `raw_artifact_id`; duplicate callbacks create no second Run | `pipeline.resume`, `composition.IngestionService.retry` | `e2e/test_stage_retry_resume_postgres.py` (5) | READY |
| 19 | **UX-005** | low-confidence extraction creates a ReviewItem visible in queue depth and changes Capability availability | `011h` + `SqlReviewItemStore.enqueue_extraction_review`, now also projected onto the inbox row | `integration/test_extraction_review_postgres.py` (9), `integration/test_inbox_authorization_postgres.py` — enqueue → NEEDS_REVIEW → expire → READY | READY |
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
| `DiagnosticsService` | its own ordered clearance comparison | delegates to `ProjectMembership.clears`, the predicate `can_read_artifact` uses; and since §12 its project admission is `can_access_project` on every construction |

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

Local, full history, PostgreSQL last. These are the **final** M1 figures, after §12.

| Gate | Result |
|---|---|
| `ruff format` / `ruff check` | clean, 206 files |
| `mypy` (strict) | clean, **109** source files |
| Backend-free suite | **1141 passed**, 595 skipped |
| Migration replay from empty | **37 applied** (fresh `lab_brain_m1final`) |
| Migration idempotency | `pending 0`, second run a no-op |
| Full PostgreSQL profile | **1736 passed**, 0 skipped |
| Executed-coverage ratchet | ok ×4; DONE `['M0a','M0b']`, IN_PROGRESS `['M1']` |
| Status freshness | up to date |
| Spec conformance | **205 passed** |
| Requirement ↔ Test | **60 ↔ 60** |
| Obligation inventory | **84**, in sync |
| Schema drift / unbound / stale | all empty |
| Mutation battery | **75/75 killed** (29 M1-P1 + 21 + 8 + 8 + 8 third-audit + 1 §12) |
| M1-P1 benchmark | current — re-run produces a byte-identical report, framing unchanged |

The earlier revision of this table reported 1133 / 1726 and 74/74 against 592 skips. Those were
correct for the third repair and are superseded, not corrected: §12 adds eight probes and one
mutation anchor, and the PostgreSQL figure moved because the run that produced 1726 skipped two
tests that this one executed.

### Local vs generic CI counts

The two history-dependent commit-hygiene tests skip in shallow generic jobs and pass in the
dedicated full-history `Commit hygiene` job. This is designed behaviour, recorded at the M1-P1
lock, and is **not a regression**. Do not make those two assert unconditionally: a green test
that checked no commits is worse than an honest skip.

| Run | Backend-free | `postgres` profile | Spec conformance |
|---|---|---|---|
| Local, full history | 1141 passed / 595 skipped | 1736 passed / 0 skipped | 205 passed |
| Generic CI jobs (`fetch-depth: 1`) | 1139 passed / 597 skipped | 1734 passed / 2 skipped | 203 passed / 2 skipped |

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
5. **Error-id minting is bounded-retry, not sequenced.** `ERR-YYYYMMDD-NNNN` is computed from the
   day's maximum ordinal and retried on a primary-key collision. Correct under M1's single-writer
   ingestion and honest about its bound: a genuinely concurrent writer would need a sequence, and
   `SurfaceStoreError` names the situation rather than reusing an id.
6. **COST-001 is wired as a required seam, not as a live caller.** `decide_retry` refuses without
   a budget gate, and the tests inject both an allowing and a refusing one. No production loop
   retries yet, so the gate has no live caller to exercise.
7. **Technical detail is one row per failed stage, written by ingestion only.** `012b` is backed
   by the ingestion pipeline and nothing else, so an error projected by a future subsystem will
   have a `NULL` pointer until that subsystem writes one — which the trigger permits and the
   service renders as the default payload.
8. **R-8, R-9, R-10, R-12** unchanged.

Two limitations recorded in the previous revision are **removed rather than downgraded**, and the
second was not a limitation at all:

* *`technical_detail_ref` resolves to nothing* — `012b` and `PostgresSurfaceStore.record_technical_detail` now back it, and all five §17.24 outcomes are proven through the real command.
* *`NEEDS_REVIEW` is unreachable because §17.19.1's vocabulary is `CONFLICT | AUTHORITY_CONFLICT`* — **this was false when it was written.** `011h` had already added `EXTRACTION_UNCERTAINTY` and `enqueue_extraction_review` was already writing those rows. The reader simply never queried them. A stated limitation that is false is more dangerous than an unstated one: it tells the next reader to stop looking.

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


## 11. The third-audit repairs

Four production-integration blockers. Each is the same shape: a guard existed, and the production
wiring reached around it or never reached it.

| # | Blocker | Before | After |
|---|---|---|---|
| 1 | the inbox ignored `--actor` | the flag was required, parsed and discarded; any string reached any project's items | `IngestionService.inbox(actor_id=..., project_id=...)` raises unless `can_access_project` allows; five refusals, one indistinguishable answer |
| 2 | the durable item carried no review/conflict/job | `review_ids`/`conflict_ids` empty, no live Job list; six of seven states unreachable | projected from `review_items` (`EXTRACTION_UNCERTAINTY`), `conflicts.subject_refs` and the Job store; all seven states proven through the real command |
| 3 | public unpersisted scientific text | `ScientificLLM.invoke`/`.critique` were public and returned `ScientificOutput` | internal seams; `ScientificLLM`'s public surface is `configured_slots` alone; `infer`/`critique` on the durable service are the only sources of text |
| 4 | `technical_detail_ref` pointed at nothing | no detail store; `--technical` returned the default payload to a scoped actor | `012b`'s `technical_details`, written by ingestion, resolved by `diagnostics()`; five outcomes proven |

### The attacks, before and after

**1. Read a project's inbox you do not belong to.** *Before:* `lab-brain inbox --project prj:x
--actor anything` printed the table. *After:* five varied-by-one-fact probes — unknown actor,
globally disabled account, no membership, revoked membership, member of another project — each
refused, each producing a byte-identical answer once the actor id is substituted
(`test_every_refusal_is_the_same_answer_except_for_the_names`). The refusal is the *service's*,
not a rendering choice: `test_the_service_raises_rather_than_returning_an_empty_view`.

**1b. Learn a project exists by getting an empty table.** *Before:* n/a. *After:* the refusal
prints no header, no summary line and no item id — an empty table would itself tell a non-member
the project is real and simply quiet.

**1c. Resolve an error reference on a disabled account.** *Before:* `DiagnosticsService` checked
only that a membership row existed, so a centrally disabled account and a revoked membership both
kept working. *After:* `can_access_project`, the same predicate, and
`test_a_disabled_account_and_a_revoked_membership_cannot_resolve_an_error` compares all three
refusals — including a stranger's — for equality, then repeats it with `--technical` to check the
scope message has not become a side channel.

**2. Be told a document is READY while a human owes it a review.** *Before:* NEEDS_REVIEW was
unreachable from durable rows, so every reviewed item printed READY. *After:* ingest →
`enqueue_extraction_review` → `NEEDS_REVIEW` → `review_expire` → `READY`, with nothing written to
the item in between: the state follows the queue, so an implementation that latched a flag would
still say NEEDS_REVIEW after the answer.

**2b. Be told a document is READY while it is still being parsed.** *Before:* `jobs_for` was
accepted and ignored. *After:* a second QUEUED job attached to the item flips it to PROCESSING and
back when the job finishes — the Job's state, not a latch.

**3. Obtain scientific model text that no row records.** *Before:* `llm.invoke(...)` returned
`ScientificOutput`, publicly. *After:* `ScientificLLM`'s public surface is exactly
`['configured_slots']`, asserted; no public method of either class returns `ScientificOutput`,
asserted over every member rather than by name; and inside `src/` the only caller of the raw seams
is `cognition/inference.py`, asserted by scanning the shipped package.

**3b. Obtain an unpersisted *critique*.** The more damaging half, because a critique is the object
that makes a belief look independently corroborated. `ScientificInferenceService.critique` is
durable on the same terms, and a route-identical critique is refused **before** the write — so the
model may have been called and no record exists that a later reader would count as corroboration.

**4. Read technical detail you are not cleared for.** *Before:* unreachable, because nothing
resolved. *After:* five outcomes, each through `main()`: the default payload never carries detail
*even for an actor holding every scope*; `--technical` without the scope is refused; scope without
clearance returns `[redacted …]` **while preserving `trace_id`/`job_id`/`span_id` and
`component`**; scope with clearance returns it; and a cross-project `detail_ref` is
unrepresentable rather than merely unreachable — `012b`'s deferred trigger refuses the row.

### Two design decisions worth naming

**`can_access_project` was extracted, not duplicated.** The inbox and error disclosure needed the
same four refusals `can_read_artifact` already made, and the instruction not to create a second
ACL is binding. So the first half of `can_read_artifact` became a named function that
`can_read_artifact` itself calls — every message and every ordering unchanged, which the existing
SEC-002 suite proves. It is deliberately *not* sufficient for evidence: membership is not
clearance, and a surface returning canonical bodies on the strength of it would be R-7 again.

**`012a`'s sibling repair.** The test that made a foreign error by relabelling this project's row
now fails, because `012b`'s trigger refuses an error and its detail in different projects. The
shortcut was creating exactly the inconsistency the trigger exists to prevent; the probe inserts a
genuine foreign row instead, which is also what an attacker enumerating ids would be guessing at.

### What the battery found

`error_disclosure_skips_the_actor_check` survived: every existing `explain` refusal probe used an
actor with **no membership row**, so `membership is not None` already refused and the stronger
predicate was never load-bearing. The disabled-account probe above is what kills it. Two of the
eight new anchors sit on `surface_store.py` queries rather than on Python branches, because that
is where the review and conflict semantics actually live.

Final: **74/74 killed.**


## 12. The closing security repair — Actor resolution is a dependency, not an option

One defect remained after §11, and it was in the **constructor**, which is why three rounds of
behavioural audit walked past it.

### What was wrong

`DiagnosticsService.__init__` declared `actor_of: Callable[[str], Actor | None] | None = None`,
and `_admitted` branched on it:

```python
membership = self._membership_of(actor_id, project_id)
if self._actor_of is None:
    return membership is not None                 # ← membership-presence-only authorization
return can_access_project(self._actor_of(actor_id), project_id, membership).allowed
```

§11 repaired the *production* path — `composition.diagnostics()` supplies the resolver — and the
docstring argued the weak branch was reachable only by contract tests building a service from a
dict. That argument is the one this repository declines to accept everywhere else. **The weak mode
was reachable from the supported public API.** Anyone constructing the service the documented way,
minus one keyword, got SEC-002's predicate replaced by "a membership row exists" — and got it
silently, because omitting an optional argument is not an error.

It is the same defect class as UX-002's `charge_budget=None` returning `retry=True` (§9 blocker 4)
and the inbox's unconsulted `--actor` (§11 blocker 1): *a check that is present but optional*.
Three instances now, in three different subsystems.

### The repair

`actor_of` is a **required** keyword argument, and `_admitted` has one branch:

```python
membership = self._membership_of(actor_id, project_id)
return can_access_project(self._actor_of(actor_id), project_id, membership).allowed
```

`can_access_project` is unchanged and is still the single ACL — no second predicate was written,
and the five refusals (unresolved Actor / inactive Actor / no membership / actor-project mismatch /
inactive membership) are decided where `can_read_artifact` and the inbox decide them.

### The attack, before and after

Fixture: a centrally **disabled** Actor holding an **active** membership with
`VIEW_TECHNICAL_DIAGNOSTICS` and `RESTRICTED_NDA` clearance — i.e. a departed researcher whose
account was disabled and whose per-project grants were never walked.

| | `default_payload` | `expand` |
|---|---|---|
| **Before** | ADMITTED, `trace_id=trc:1` | ADMITTED, technical detail returned, `source_path=/srv/nda/acme-foundry/pdk-v7/process_rules.pdf` |
| **After** | `ErrorNotFound` | `ErrorNotFound` |

The leaked field is the point: §17.24's technical tier is exactly the NDA filename / private path /
prompt-fragment material SEC-001 exists to contain, so the old constructor turned a disabled
account into a readable one.

Constructing the service without `actor_of` now raises
`TypeError: DiagnosticsService.__init__() missing 1 required keyword-only argument: 'actor_of'`.

### The eight probes

All in `security/test_diagnostics_disclosure.py`, backend-free, alongside the eleven §17.24
probes that were already there (19 total in the file).

| # | Probe | What it pins |
|---|---|---|
| 1 | `test_the_service_cannot_be_constructed_without_actor_resolution` | structural — `inspect.signature` has no default **and** `get_type_hints` shows no `\| None` around the callable, then the `TypeError` proves it is enforced |
| 2 | `test_an_unknown_actor_is_indistinguishable_from_a_missing_error` | §14.4 "no governance without who", and the refusal names no reason |
| 3 | `test_an_inactive_actor_with_an_active_membership_is_refused` | **the defect**, as a fixture; asserts the two `active` flags genuinely disagree first |
| 4 | `test_an_active_actor_with_an_inactive_membership_is_refused` | the other half of SEC-002's conjunction |
| 5 | `test_a_membership_of_another_project_grants_nothing_here` | R-7 restated on this surface |
| 6 | `test_an_active_actor_with_an_active_membership_still_resolves` | positive control — without it, "refuse everyone" passes 2–5 |
| 7 | `test_technical_expansion_reveals_no_second_refusal_path` | `--technical` is not a side channel: all four refusals are byte-identical and equal a never-issued id's |
| 8 | `test_no_error_or_detail_lookup_happens_before_project_authorization` | ordering under the *new* predicate, with loaders that always succeed, for each of the three SEC-002 refusals |

Probe 8 is the one worth arguing for. The pre-existing ordering probe covered "no membership"
only, and it used a loader returning `None` — so it could not tell "not read" from "read and found
nothing". This one supplies loaders that return the record and the secret detail unconditionally,
so the **only** thing that can stop them is the ACL.

Every fixture that previously omitted `actor_of` now supplies an explicit in-memory Actor store
(`tests/security/test_diagnostics_disclosure.py`, `tests/contract/test_budget_and_cli.py`). That is
not ceremony: those fixtures were implicitly asserting "this actor exists and is active" by having
no way to say otherwise.

### What the battery found

One new anchor, and one existing anchor moved:

* `diagnostics_actor_resolution_is_optional_again` restores the `| None = None` default and is
  killed by probe 1. Without it, a future edit could reopen the seam and every behavioural probe
  would still pass — they all supply a resolver.
* `error_disclosure_skips_the_actor_check` (from §11) gained
  `tests/security/test_diagnostics_disclosure.py` as its **first** target. It was previously
  killable only under PostgreSQL, because the membership-only branch was the one every in-memory
  fixture ran — so no backend-free test could observe the substitution at all. It is now killed
  without a database.

Final: **75/75 killed.**

### Nothing else was reopened

No locked M1-P1 invariant, no M0a/M0b surface, and no other module was touched. The change set is
`surface/disclosure.py` (constructor signature, one branch removed, docstrings), the two test
fixtures, eight new probes and one mutation entry.
