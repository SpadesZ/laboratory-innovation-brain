# M1-P1 Readiness — Research Memory Foundation + Evidence-Aware Hierarchical Chunking

Date: 2026-09-20; revised 2026-09-21 after the independent audit (§10); **revised again after
Repair-2 (§11)**
Milestone: **M1 — Research Memory**, `NOT_STARTED` → `IN_PROGRESS`
Slice scope: `EVI-002`, `EVI-003`, `EVI-004`, `EVI-009`, `EVI-010`, `SEC-003`, `OPS-004`, `UX-004`
Spec: SAI 3.3, amendments `v3.3-a1` … `v3.3-a18`
Baseline: `72391aa6af850324fe141d7c9585783fbdaca5dd` (M0a DONE, M0b DONE, both hard-locked)

> **This is not an M1 sign-off.** M1's exit gate names a delayed mock job resuming an episode
> (`OPS-001`), every scientific LLM call persisting bundle + provenance (`LLM-001`) and
> `UX-001`~`UX-007` passing. None of those exists. Twelve of M1's twenty-one requirements are
> untouched. What follows is the readiness of the eight this slice owns.

## 1. What this slice was for, and what it found

The slice was scoped to the ingestion/evidence foundation. Building it required answering a
question the specification did not: **where may a scientific document be cut?**

Evidence-boundary-preserving segmentation was stated once in the whole document — §6.7, as
`不應`, a SHOULD — with **no entry in `normative_statements.yaml` at all**, and
`M0a_hard_must_counts.yaml` already recording the consequence as `hard_must: 0, basis "SHOULD
only"`. The neighbouring requirements each stop short, and `EVI-007` is the instructive one:
§6.13 and §6.20 are precise about *which* embedding space may be compared and silent about what a
vector is allowed to **be**. An implementation can satisfy every clause of `EVI-007` — never mix
spaces, dual-index the cutover, answer "which version retrieved this" — while treating the
retrieved payload as the evidence body. §23.4 forbids an **agent** from doing that; nothing made a
**system** that does it fail CI.

Raised as `SPEC-ISSUE-013` (GATE, blocks M1) rather than resolved on a provisional reading, per
AGT-015 and §23.4. The maintainer adopted Reading D.

## 2. Governance outcome

| | |
|---|---|
| Spec issue | `SPEC-ISSUE-013` — **RESOLVED**, Reading D |
| Amendment | `v3.3-a17` — new §6.22, new §17.25, `EVI-010` / `T-EVI-010` |
| Requirement ↔ Test invariant | **59 ↔ 59 → 60 ↔ 60** |
| ADR | `ADR-0011` — EvidenceUnit is canonical identity; RetrievalRepresentation is derived |
| Registry | 10 new statements at §6.22, all MUST, all owned by `EVI-010` |
| Obligation inventory | +12 occurrences (10 REGISTERED, 2 RESTATEMENT_OF); §6.22 `hard_must: 10` |
| §6–§16 audit | 76 → **77** sections, 70 → **80** hard MUSTs, 72 → **84** occurrences, every delta 0 |
| M0a audit document | regenerated to **rev 7** — §3/§4 figures only; §5–§7 left as the sign-off record |

`v3.3-a17` is the first move of the Requirement ↔ Test invariant since `v3.3-a6`. Amendments
a12–a16 all held the count because each made an **existing** obligation uniquely executable;
this one adds an obligation no existing requirement could take without distortion.

§6.7 is **unchanged**. §6.22 states the hard obligation beside it rather than promoting it in
place, so the audit trail shows a new statement rather than a silently strengthened old one.

## 3. Per-requirement readiness

| Requirement | §26 pass condition (abridged) | Implementation | Tests | PostgreSQL | Status |
|---|---|---|---|---|---|
| **EVI-002** | parser 缺欄位時輸出 UNKNOWN/NOT_REPORTED，不得生成 default scientific value | `ingestion/admission_gate.py` (`_check_no_invented_values`), `parsers/documents.py` (`_clean_unit`) | `contract/test_evidence_admission.py` (7) | indirect — the E2E asserts no invented value reached a stored unit | **READY** |
| **EVI-003** | LLM interpretation cannot be admitted as observed/simulated evidence | `admission_gate.py` (`_check_inference`, `INFERENCE_FORBIDDEN_TYPES`) | `contract/test_evidence_admission.py` (6) | no — a pure admission rule | **READY** |
| **EVI-004** | preprint/journal/review resolve to one work; DEPENDENCE_UNKNOWN contributes 0; promotion stays blocked | `ingestion/source_work_resolution.py`, `evidence/independence.py` | `contract/test_source_work_resolution.py` (14) | no — resolution is pure over injected lookups | **READY** |
| **EVI-009** | MEASURED/SIMULATED refused with no run/artifact ref; reference resolves; back-fill refused; INFERRED exempt but still not typeable as fact | `admission_gate.py` (`_check_reference`, `_check_backfill`) | `contract/test_evidence_admission.py` (7) | no | **READY (artifact half)** — see §6 |
| **EVI-010** | locked fixture, five cases, per-case outcome; seven metrics for both strategies; tampered payload cannot alter the evidence body | `core/models/evidence_unit.py`, `ingestion/segmentation.py`, `evidence/retriever.py`, `evidence/segmentation_benchmark.py`, `003a`, `009a` | `contract/test_evidence_unit_identity.py` (26), `test_evidence_segmentation.py` (19), `test_retrieval_boundary.py` (12), `test_evidence_benchmark.py` (13), `integration/test_evidence_units_postgres.py` (22), `e2e/test_ingestion_vertical_postgres.py` (12) | **yes** — 22 schema guards + 12 e2e | **READY** |
| **SEC-003** | fixture secret quarantined before immutable normal ingest; redacted derivative preserves audit linkage | `ingestion/secret_scanner.py`, `pipeline.py` (`_run_secret_scan`) | `security/test_secret_scan_ordering.py` (11) | no — the scan precedes both stores | **READY** |
| **OPS-004** | fault injection between artifact-store write and DB commit leaves no dangling reference; compensating path exercised | `pipeline.py` (`_store_raw`), `storage/artifacts/` | `integration/test_cross_store_compensation.py` (6) | **yes** — `test_a_failed_promotion_leaves_no_row_in_postgresql` | **READY** |
| **UX-004** | raw artifact durable before any parsing stage; retry reuses `raw_artifact_id`; secret-scan timeout is BLOCKED not FAILED | `pipeline.py` (ordering + `raw_artifact_is_durable`) | `integration/test_cross_store_compensation.py` (4) | **yes** — via the e2e vertical | **READY (ingest half)** — see §6 |

Requirements in M1 that this slice did **not** touch and that have no tests: `EVI-007`,
`EVI-008`, `LLM-001`, `OPS-001`, `SEC-001`, `SEC-004`, `SRC-001`, `UX-001`, `UX-002`, `UX-003`,
`UX-005`, `UX-006`, `UX-007`.

## 4. Verification

Run in the order the slice brief fixes, with the PostgreSQL profile **last** so it owns the
outcome report the ratchet reads.

| # | Gate | Result |
|---|---|---|
| 1 | commit hygiene | 5 messages in `1fc43c2..HEAD`, no AI attribution |
| 2 | `ruff check src tests scripts` | All checks passed |
| 3 | `ruff format --check` | 156 files already formatted |
| 4 | `mypy` (strict) | no issues in 76 source files |
| 5 | backend-free suite | **903 passed**, 425 skipped |
| 6 | migration replay from empty | **26 applied** |
| 7 | migration idempotency | `applied: 26, pending: 0` |
| 8 | full PostgreSQL profile | **1328 passed** |
| 9 | executed-coverage ratchet | ok ×4; DONE `['M0a','M0b']`, IN_PROGRESS `['M1']` |
| 10 | `update_status.py --check` | up to date |
| 11 | spec conformance | 205 passed |
| 12 | requirement/test traceability | 60 ↔ 60 |
| 13 | obligation inventory | 84 occurrences, in sync |
| 14 | mutation battery | **18/18 killed** |
| 15 | benchmark report | current |

Schema drift: `all_drift()` empty, `unbound_canonical_schemas()` empty, `stale_exemptions()`
empty. §17.25's blocks are written **exact** (the `v3.3-a8` treatment of §17.1) precisely so the
guard can bind them field-for-field; ADR-0011's "no embedding on the evidence side" is held by
that comparison rather than by review.

## 5. Benchmark (T-EVI-010)

Locked fixture `fixtures/evidence/rs_anomaly_report.md`, digest
`sha256:8b30ebc93163b8965b8ad8d67b298b20edeb832e16c69aacd66291fd621a981b`, 518 tokens.
Full report: [`evidence_segmentation_report.md`](../../benchmarks/evidence_segmentation_report.md).

| Strategy | units | boundary | condition | table ctx | figure ctx | locator | recall@5 | precision@5 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| evidence-aware | 19 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.46 |
| fixed-token baseline | 3 | 1.00 | 1.00 | **0.00** | **0.00** | **0.00** | 1.00 | **0.57** |

All five cases PASS for the evidence-aware segmenter. That is the gate; the numbers are context.

**The finding, and it is the most important paragraph in this document.** The prohibited
strategy scores **equal or better on every metric a conventional evaluation reports** —
boundary completeness, condition retention, recall, and precision — while scoring **zero on all
three structural metrics**.

Both halves have an explanation:

- Its boundary score is 1.00 because a 200-token window over a 518-token document cuts it into
  three pieces, each large enough to contain any probe's fragments incidentally. That is not the
  Minimum Evidence Boundary §6.22 defines — the **smallest** complete unit — it is the opposite
  failure, reached by not really cutting. The metric cannot distinguish "kept together
  deliberately" from "never separated because nothing was separated".
- Its precision is higher for the same reason: with three units, retrieving five candidates
  returns everything, and everything contains all the relevant material.

So **a corpus-level threshold over the usual metrics would have selected the strategy §6.22
prohibits.** That is the concrete, measured form of the argument `SPEC-ISSUE-013` escalated, and
it is why the maintainer's ruling fixed the outcome per case instead of by score. Pinned by
`test_the_ordinary_retrieval_metrics_do_not_punish_the_baseline`, so a future change that makes
the ordinary metrics separate the two strategies fails and forces the framing to be re-examined.

## 6. Known limitations

Stated rather than implied. Each is a real gap, not a rough edge.

1. **`EVI-009`'s Run half is unexercised.** A Run reference is *recorded* and not *resolved*,
   because `Run` is not an entity until `OPS-001` (risk **R-11**). Inventing a fake Run record to
   make a lookup succeed is exactly what this gate exists to prevent, so the artifact-backed
   fixtures are what M1-P1 admits. Closes with `OPS-001`.

2. **`UX-004`'s retry half is modelled at the seam, not driven by a Job.** The test shows the
   parse stage re-runs against the stored bytes under the same `artifact_id`; the Job-level
   resume and idempotent callback that *drive* that retry are `OPS-001`. What is proven is that
   a retry needs no re-upload, not that the retry is orchestrated.

3. **Re-segmentation is not representable.** `003a`'s unique index on
   `(project_id, artifact_id, structural_path)` makes a second segmenter version writing
   different boundaries **fail loudly** rather than shadow the old ones. `segmenter_id` /
   `segmenter_version` are recorded so affected units are selectable by §6.18's quarantine
   mechanism, but the re-segmentation path itself does not exist: re-cutting evidence that
   Attestations already reference is belief-affecting and belongs with the event infrastructure,
   not a migration. See ADR-0011.

4. **No embedding index.** `EVI-007` is out of scope by design. Retrieval is deterministic BM25.
   What is built is the seam — `RetrievalRepresentation` carries the embedding fields and
   `EvidenceUnit` cannot — so a dense index plugs in without touching evidence identity.

5. **The secret scanner is pattern-based and text-only.** It covers provider keys, private-key
   blocks, inline credentials and bearer tokens. Binary content returns CLEAN, which is honest
   about coverage rather than a claim of safety. SEC-003's contract here is the **ordering** and
   the **branch**; improving detection later changes no caller.

6. **The condition/result binder is heuristic.** Two rules — quantitative adjacency and
   referential opening — deliberately biased toward keeping text together, because an over-large
   unit is a precision cost and an under-large one is a correctness failure. The binder's output
   is made checkable rather than trusted: a unit *declares* its bound conditions and the model
   and the `003a` trigger both refuse a unit that declares one it does not contain.

7. **No PDF parser.** The structural intermediate is what a later PDF parser targets. Adding OCR
   to satisfy a fixture would have coupled the first segmentation contract to one library's idea
   of a paragraph.

8. **`R-7` narrows but does not close.** `can_read_artifact` now has a live caller: the admission
   gate takes it as an injected `can_read` and the e2e exercises it with a real actor, a real
   membership and a cross-project negative. The ACL logic is not duplicated. It stays open until
   the remaining M1 read paths (`UX-003`'s diagnostic surface, `EVI-007`'s retrieval) also route
   through it.

## 7. Mutation battery

`scripts/mutation_battery.py`, **18/18 killed**. Each entry disables one guard by a textual
substitution and requires the tests that depend on it to fail; the anchor is verified before
substitution, so a moved guard reports `ANCHOR NOT FOUND` rather than a false kill.

| Guard | Mutation | Killed by |
|---|---|---|
| §6.22 r3 fixed-token not primary | always subdivide | `test_nothing_is_subdivided_at_the_declared_limit` |
| §6.22 r1 condition/result binding | never join sentences | `test_the_condition_and_its_result_land_in_one_unit` |
| §6.22 r1 declaration is checked | `severed = []` | `test_a_unit_declaring_a_condition_it_does_not_contain_is_refused` |
| §6.22 r5 table context required | skip the check | `test_a_table_unit_without_table_context_is_refused` |
| §6.22 r6 figure needs prose | caption alone suffices | `test_a_figure_with_no_explanatory_prose_is_refused` |
| §6.22 r3(b) baseline not admissible | skip the check | `test_a_benchmark_baseline_unit_is_refused_at_admission` |
| §6.22 r3–4 lineage all-or-nothing | skip the check | `test_partial_subdivision_lineage_is_refused` |
| EVI-010 canonical body re-resolved | trust the claimed body | `test_a_forged_body_is_refused_at_admission` |
| EVI-003 inference not a fact | skip the check | `test_an_inferred_record_still_cannot_be_typed_measured` |
| EVI-009 reference at admission | return early | `test_a_measured_or_simulated_record_with_no_reference_is_refused` |
| EVI-004 UNKNOWN contributes 0 | count it as independent | `test_dependence_unknown_contributes_zero` |
| EVI-004 same work counted once | skip the fold | `test_five_attestations_of_one_work_count_as_one` |
| EVI-004 heuristic ≠ independent | return INDEPENDENT | `test_a_title_author_match_is_flagged_for_review_not_merged` |
| SEC-003 scan before store | continue past quarantine | `test_a_suspected_credential_never_reaches_permanent_storage` |
| OPS-004 compensation runs | drop the rollback | `test_a_failed_promotion_rolls_the_database_back` |
| SEC-002 cross-project refused | skip the check | `test_admission_refuses_an_evidence_unit_from_another_project` |
| SEC-002 retrieval scope filter | rank every project | `test_retrieval_never_ranks_a_unit_from_another_project` |
| ADR-0011 identity is derived | skip the check | `test_identity_is_recomputed_and_a_mismatch_is_refused` |

## 8. Unresolved blockers

**None blocking this slice.** `SPEC-ISSUE-013` was the one gate issue and it is RESOLVED; no OPEN
GATE issue names M1.

Carried forward, unchanged by this slice: **R-1** (no Lumerical seat), **R-2** (no ground-truth
benchmark set), **R-4** (`markers.py` models pytest's collection rules), **R-8**
(`critique_gate` has no caller), **R-9** (reclassification history not representable), **R-10**
(budget gate dispatches only mocks), **R-11** (span may name a Job or Run that does not exist),
**R-12** (belief event may name a hypothesis that does not exist). **R-7** is narrowed — see §6.8.

## 9. Requested decision

**Audit and sign off, or reject.** M1 stays `IN_PROGRESS` either way; this slice claims eight
requirements READY, not a milestone. Three things are worth an auditor's attention first:

1. **the invariant moved.** 59 ↔ 59 → 60 ↔ 60 is a maintainer ruling with governance
   consequences, and `SPEC-ISSUE-013` states the four readings and the objection to each.
2. **the benchmark's finding** (§5) — the prohibited strategy wins on the conventional metrics.
   If that is wrong, the per-case pass condition loses its justification.
3. **the three "READY (half)" entries** in §3 and §6, which are the places this slice's claim is
   narrower than its requirement's full §26 text.

## 10. Audit repair (2026-09-21)

The independent audit returned four findings. All four were **reproduced against the running
system before anything was changed**, and the reproductions are kept as permanent probes in
`tests/contract/test_evidence_repair_probes.py` — the same reasoning
`tests/spec/test_conformance_guards.py` gives about itself.

Governance: **`SPEC-ISSUE-014`** and **`SPEC-ISSUE-015`**, both RESOLVED by **`v3.3-a18`**, with
**ADR-0012**. Each applies an existing precedent rather than inventing a shape, and **no
Requirement or Test ID is added** — the invariant stays **60 ↔ 60**, because all four are
obligations `EVI-003`, `EVI-010` and `SEC-002` already imposed and that the implementation had
made unenforceable.

| # | Finding, as reproduced | Ruling | Precedent applied |
|---|---|---|---|
| **P0** | `MEASURED` + `inference_provenance_id` + flag omitted → **ADMITTED**, ×3 types | inference status is derived from `extraction_provenance`; the flag may widen, never narrow; contradiction fails closed | — (clarification of EVI-003) |
| **P1** | `'evidence_unit_id' on Attestation? -> False` | the §17.25 reference becomes a durable column (`003c`), enforced at admission | — (§17.25 already required it) |
| **P1** | `insert into prj:a: OK` / `insert into prj:b: UniqueViolation` | global identity, project-scoped presence: `EvidenceUnitOccurrence` (§17.25.1, `003b`) | **ADR-0010**, one layer down |
| **P1** | severed body + `bound_condition_texts: []` → stored, nothing objected | two layers: a byte-level witness in SQL, and admission **re-running the segmenter** over the artifact's pinned bytes | **`v3.3-a13`**, its two forgery classes |

### What each ruling refused, and why

- **Not** `project_id` in the identity derivation. ADR-0010 rejected the identical move for
  `Artifact`: one measurement cited by two projects would become two identities and `EVI-004`
  would count it twice.
- **Not** a composite primary key. It stores the canonical body once per project, so "resolve by
  identity, get *the* body" becomes "get *a* body", and two rows under one identity can diverge
  while each stays internally consistent.
- **Not** natural language in SQL. `v3.3-a13` refused a second copy of `evaluate` in PostgreSQL
  for the reason that applies verbatim to `bind_condition_result_groups`.
- The witness **does not** stop a complete forgery and is not claimed to. It is `input_hash`'s
  analogue: it rejects a *partial* forgery cheaply. Re-derivation is what closes the hole.

### Verification after repair

| Gate | Result |
|---|---|
| `ruff format --check` / `ruff check` | 159 files unchanged / all checks passed |
| `mypy` (strict) | no issues in 77 source files |
| backend-free suite | **923 passed**, 440 skipped |
| migration replay from empty | **29 applied** |
| migration idempotency | `applied: 29, pending: 0` |
| full PostgreSQL profile | **1363 passed** |
| executed-coverage ratchet | ok ×4; DONE `['M0a','M0b']`, IN_PROGRESS `['M1']` |
| spec conformance | 205 passed; **60 ↔ 60**; drift/unbound/stale all empty |
| obligation inventory | 84 occurrences, in sync |
| mutation battery | **25/25 killed** |
| benchmark report | current, **framing unchanged** |

### Two mutation findings worth recording

The battery found defects in the repair itself, which is what it is for:

1. `cross_project_unit_admitted` reported **ANCHOR NOT FOUND** — it targeted a line ADR-0012
   deleted. Removed rather than left permanently failing; superseded by `presence_is_not_consulted`.
2. `evidence_link_need_not_be_durable` **survived** as originally written. Disabling the
   `evidence_unit_id is None` branch changes nothing, because `None != unit_id` means the
   comparison below still refuses. The branch is a message refinement, not an independent guard.
   The battery now anchors on the comparison and `_check_durable_link` says so, so nobody later
   "simplifies away" a guard believing it was one.

### Known limitations added by the repair

- **Admission re-parses the artifact.** Sub-millisecond on the locked fixture, not free on a large
  document, per admission. Scoped to scientific admission (rare) rather than retrieval (not rare).
  If it must get cheaper the answer is a verified cache keyed on
  `(artifact_id, parser_version, segmenter_version)` — **not** trusting the witness alone, which
  would delete the semantic layer and restore `SPEC-ISSUE-015`.
- **Per-project divergence of the same evidence stays unrepresentable**, deliberately. Redaction
  produces different bytes, hence a different Artifact, hence different units.
- **`_check_durable_link` enforces a conditional obligation.** `attestations.evidence_unit_id` is
  nullable because §17.2's one-source rule is unchanged: an Attestation may witness a Run or a
  SourceWork. A NOT NULL column could not express that without forbidding the other two.

### Unchanged by the repair

`EVI-004`, `SEC-003` and `OPS-004` were not refactored — they passed the audit and had no finding
against them. The benchmark framing is untouched: the fixed-token baseline still scores **1.00
boundary, 1.00 condition, higher precision@5** while zeroing all three structural metrics, and
that remains the measured justification for §26's per-case pass condition.

## 11. Repair-2 (2026-09-21)

The audit of the Repair-1 SHA returned **three blockers and two regression gaps**. All three
blockers were **fail-opens of the same shape**: the guard was correct, was tested, and had an
input that turned it off. Each was reproduced against the running system before anything changed,
and the reproductions are permanent probes in `tests/contract/test_evidence_repair2_probes.py`.

**Governance: no spec amendment, no new Requirement/Test ID. 60 ↔ 60 unchanged.** All three are
already derivable from `v3.3-a18`, `EVI-010` and `SEC-002` — the specification determined the
required behaviour and the implementation did not deliver it, which is a code defect and not an
ambiguity. Using a clarification to redefine behaviour around an implementation shortcut is
exactly what the brief forbade, and nothing here needed one.

### Attack before / after

| Blocker | Attack, as reproduced on `23b47dd` | After |
|---|---|---|
| **P0** durable reference bypass | forged unit on `Attestation.evidence_unit_id`, request field omitted → **ADMITTED** (durable-link, occurrence, ACL and re-derivation all skipped) | `SEGMENTATION_NOT_REPRODUCIBLE` — and the probe asserts the *far-end* guard fired, so the whole chain provably ran |
| **P0** request may not substitute | — | request names a unit the record does not → `EVIDENCE_LINK_NOT_DURABLE`; the two disagree → `EVIDENCE_LINK_NOT_DURABLE` |
| **P1** occurrence fail-open | gate built without `is_present_in` → **ADMITTED**, project scope never established | `PROJECT_SCOPE_NOT_VERIFIABLE`; wrong project → `CROSS_PROJECT_UNIT`; correct project → proceeds |
| **P1** provenance not bound | unit recording `some_other_segmenter 99.0.0` → **ADMITTED**, because the *current* segmenter reproduced the body | `RECORDED_IMPLEMENTATION_UNAVAILABLE` |

### What changed, and why in that shape

**`Attestation.evidence_unit_id` is the trigger.** It is the half that *survives* — what a
reloaded record, an auditor or a replay has. `AdmissionRequest.evidence_unit_id` is now a
consistency assertion that may only agree; it can neither narrow nor suppress. The decision to
verify is made from the record alone in `_check_evidence_unit`.

**Occurrence resolution fails closed.** `if resolver is not None` made SEC-002 opt-in for whoever
constructed the gate. A missing resolver now refuses with its own reason, distinct from "the
resolver said no" — different remedies, so different codes. `project_id` is **not** back on
`EvidenceUnit`; ADR-0012 stands.

**Re-derivation resolves the recorded implementation.** `SegmentationReverifier` now takes the
**unit**, looks its `(parser_id, version)` and `(segmenter_id, version)` up in a
`SegmentationRegistry`, and refuses when either is absent. It never substitutes the current
version. The registry has two entries today, and that is precisely why it must exist: with one
implementation and no registry, every historical unit silently verifies against today's code.
The recorded `token_limit` travels too, or a unit subdivided under a tighter limit would not
reproduce.

### Regression gaps

**Full-vertical duplicate ingest** (`tests/e2e/test_duplicate_ingest_postgres.py`, 10 tests).
Repair-1 proved schema behaviour with raw `INSERT`s, which says nothing about running
`IngestionPipeline.ingest()` twice. Case A (same bytes, same project) — no duplicate artifact, no
duplicate unit, occurrence still valid and singular, second ingest does not fail on the existing
content-addressed artifact, provenance and witness preserved. Case B (same bytes, two projects) —
one global artifact identity, one canonical body per evidence identity, one occurrence each,
independent retrieval, and **neither project loses access because the other ingested first**.

**Canonical read boundary** — closed, modestly. `PostgresEvidenceUnitReader` is a reader, not a
repository layer: no cache, no unit of work, no write path. Every load rebuilds through the model,
so identity, digest, witness, rule 1 and typed context are all re-checked, and a drifted row
raises `EvidenceUnitReadError` naming the unit rather than being returned as evidence. The e2e
now uses it instead of an inline rebuild.

### Verification

| Gate | Result |
|---|---|
| `ruff format --check` / `ruff check` | 163 files formatted / all checks passed |
| `mypy` (strict) | no issues in **79** source files |
| backend-free suite | **941 passed**, 450 skipped |
| migration replay from empty | **29 applied** |
| migration idempotency | `applied: 29, pending: 0` |
| full PostgreSQL profile | **1391 passed** |
| executed-coverage ratchet | ok ×4; DONE `['M0a','M0b']`, IN_PROGRESS `['M1']` |
| status freshness | up to date |
| spec conformance | 205 passed |
| Requirement ↔ Test | **60 ↔ 60** |
| obligation inventory | 84 occurrences, in sync |
| schema drift / unbound / stale | all empty |
| mutation battery | **29/29 killed** |
| benchmark | current, **framing unchanged** |

### What the mutation battery found in Repair-2 itself

Two stale anchors (`evidence_link_need_not_be_durable`, `presence_is_not_consulted`) reported
**ANCHOR NOT FOUND** because Repair-2 had moved the guards they targeted; both re-anchored on the
new ones. More usefully, `reverification_token_limit_not_restored` **genuinely survived**:
replacing `factory(provenance.token_limit)` with `factory(None)` broke nothing, because no test
re-verified a unit segmented under a non-default limit. That is the same defect class as the three
blockers — a correct guard nothing exercised — so two probes were added and it now dies.

### Remaining P2 limitations

Stated so they are not read as closed:

1. **There is still no production repository contract for artifacts or evidence units.** The
   duplicate-ingest tests supply their own `commit_rows` / `_persist` helpers. `IngestionPipeline`
   takes `commit_rows` as an injected callable because OPS-004 needed the fault-injection point
   to be a parameter, and nothing has since supplied a production writer. So what is proven is
   that **the pipeline is idempotent and the schema accepts what it produces** — not that a
   production writer exists which does this correctly. The read side now has a boundary
   (`PostgresEvidenceUnitReader`); the write side does not.
2. **Admission re-parses the artifact**, now with a registry lookup on top. Unchanged in
   character from Repair-1: scoped to scientific admission, and the only safe optimisation is a
   cache *of the re-derivation* keyed on
   `(artifact_id, parser_version, segmenter_version, token_limit)`.
3. **`EVI-009`'s Run half and `UX-004`'s Job-level retry** remain bound to `OPS-001`, unchanged.
4. **Re-segmentation is still not representable**, by design (ADR-0012).
5. **The registry holds one parser version and one segmenter version.** Historical verification
   across versions is *structurally* supported and is exercised only by a synthetic second
   version in the probes. The first real second version will be the first genuine test of it.

**M1-P1 is not claimed hard-locked.** M1 stays `IN_PROGRESS`; M0a and M0b are untouched and DONE.
