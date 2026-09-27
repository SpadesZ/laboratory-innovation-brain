# M3 — Hypothesis Brain: readiness for independent sign-off

Date: 2026-09-26; revised the same day for the two blockers the independent M3 review named (§11)
Milestone: **M3 — Hypothesis Brain**, **`DONE` / HARD-LOCKED** 2026-09-27 on independent review
sign-off at `6416adb1f72ada341f82fb04731e1fababd140d9` (§12)
M2: **`DONE` / HARD-LOCKED** 2026-09-25 at `66ef099f965a0f6a8e7aa1ecd836eec4555a26f3`; the sign-off
is recorded at `a3209b8` and the executed-coverage ratchet enforces its 8 requirements on every run
M1 / M1-P1 / M0a / M0b: `DONE`, hard-locked — **no behaviour changed** (§5 lists every additive edit;
§11H lists the fixture updates R-12's closure required, none of which changes an assertion)
Spec: SAI 3.3, amendments `v3.3-a1` … `v3.3-a18`. **No amendment, no ADR, no new Requirement or
Test ID, and no SPEC-ISSUE was raised by this work.** Interpretations the text left open are stated
in §4 where they are made.

Scope, exactly: `EPI-001`, `LLM-002`, `SRC-002`, `SRC-003`, `VER-008`. M4 was not started.

## 1. The exit gate, clause by clause

> role I/O + Position/Critique contracts pass; Critic bundle divergence measurable; benchmark
> thresholds are calibrated and stored in BenchmarkPolicy before gate enforcement.

| Clause | Where it is demonstrated |
|---|---|
| **role I/O contracts** — 6 core roles + N specialists (§7.4) | `cognition/roles.py` parses every model reply against its role's contract before a typed object exists; `unit/test_debate_protocol.py` (33) refuses each shape a model would use to exceed its role: <2 certificates, a missing certificate field, a prediction over an OutcomeSpace the engine was not shown or an outcome outside it, a non-belief effect, a specialist favouring a rival it was not shown, a critic citing evidence it was not shown or objecting to a non-target, a novelty row for a record the search did not return, a role given less input than its contract. Supervisor/PI → `ResearchContract` → `DebateRequest.from_contract` (human-authored in M3, §4.8); Verification Planner → Stage C's ranked actions (§4.7). |
| **Position / Critique contracts** | `core/models/debate.py` + `005e`. A `Position` names the bundle its inference was produced from and `005e` refuses one whose provenance hash differs (`integration/test_hypothesis_storage_postgres.py::test_a_position_must_name_the_bundle_its_inference_actually_saw`). A `CritiqueReport` names the inference it critiques and its `differs_in` axes, which `005e` **re-derives** from the two provenance rows and refuses on any mismatch or when empty; an inverted bundle that is the primary retrieval again is refused by hash. |
| **Critic bundle divergence measurable** | `cognition/debate_metrics.py::bundle_divergence` (versioned `critic-new-evidence-share@1.0.0`), recorded per round and for the debate on every `DebateRecord`; `unit/test_debate_protocol.py::test_the_critic_inverts_the_retrieval_and_the_inverted_bundle_is_saved_and_traceable`, and after a cold reload in `e2e/test_hypothesis_brain_postgres.py::test_the_inverted_bundle_and_its_divergence_are_traceable_after_a_reload`. |
| **thresholds calibrated and stored in BenchmarkPolicy before gate enforcement** | `cognition/debate_benchmark.py::calibrate` reads the threshold off the fixed benchmark run and produces an **inactive** `BenchmarkPolicy` (metric, threshold, direction, sample size, two calibration artifacts, version); `010c` stores it; only `BenchmarkStore.activate` arms a gate. Before that every verdict is ADVISORY: `contract/test_debate_benchmark.py::test_no_hard_gate_before_calibration_and_an_enforced_one_after_activation`. No gate module contains a typed threshold: `unit/test_benchmark_gate.py::test_no_gate_module_compares_a_metric_against_a_typed_number` parses them. |

The published benchmark is [`benchmarks/debate_benchmark_report.md`](../../benchmarks/debate_benchmark_report.md),
regenerated and checked by `scripts/run_debate_benchmark.py [--check]`.

## 2. Requirement-by-requirement readiness

| # | Requirement | §26 pass condition (abridged) | Implementation | Tests | Status |
|---|---|---|---|---|---|
| 1 | **EPI-001** | root-cause episode 在驗證前保留至少兩個 active/competing hypotheses (e2e) | `core/hypothesis_admission.py` — §8's gate: complete certificate, predictions bound to a declared OutcomeSpace version, resolvable provenance, **≥2 distinct mechanisms per set**, a **grounded** genesis event citing the bundle it was reasoned from, all-or-nothing per set. `core/revision_gate.py` refuses `→ SUPPORTED` in a root-cause set with <2 admitted rivals; `011i` refuses the same promotion and the prediction-less genesis in SQL. | `unit/test_hypothesis_admission.py` (20), `unit/test_revision_gate.py`, `integration/test_hypothesis_storage_postgres.py`, **`e2e/test_hypothesis_brain_postgres.py`** (3 EPI-001) | READY |
| 2 | **LLM-002** | fixed SiPho benchmark; debate vs baseline/disabled on the same cases, refutable; BenchmarkPolicy stores metric/threshold/sample size/artifacts/version; no hard gate before calibration; per-case rounds vary with difficulty (benchmark) | `cognition/debate.py` records §15.4's five metrics with versions; `cognition/debate_benchmark.py` runs DEBATE / BASELINE / NO_INVERTED over `fixtures/debate/sp_rs_anomaly_debate.json`, returns a **SUPPORTED/REFUTED** verdict, checks rounds against the fixture's difficulty order, calibrates; `core/benchmark_gate.py` + `DebateGate` arm only on an active policy | **`contract/test_debate_benchmark.py`** (15), `unit/test_benchmark_gate.py` (15), `unit/test_debate_protocol.py`, `integration/test_hypothesis_storage_postgres.py` | READY |
| 3 | **SRC-002** | DIAGNOSIS/NOVELTY differ; high-stakes without inverted retrieval refused BELIEF_REVISION; inverted bundle + divergence traceable; critique independent on bundle/policy/route and adjudicated by external evidence; irreversible action not dispatched without critique, even with `causes_belief_revision=false` and with a valid human approval (e2e) | `evidence/source_policy.py` (§7.5's table, ordinal stakes, per-policy threshold); the Critic's own retrieval over the policy's **inverted** classes, excluding the primary evidence, saved as a bundle; `core/revision_gate.py` + `011i` (REJECT needs an independent critique; above-threshold needs an inverted one; adjudication needs a non-INFERRED attestation); `tools/dispatch.py` attaches M0b's `critique_gate` at the R-8 extension point for irreversible Capabilities/estimates | `unit/test_debate_protocol.py`, `unit/test_revision_gate.py`, `unit/test_irreversible_dispatch.py` (7), `integration/test_hypothesis_storage_postgres.py`, **`e2e/test_hypothesis_brain_postgres.py`** (5 SRC-002) | READY |
| 4 | **SRC-003** | no PriorArtSearchRecord → rejected; coverage retrievable; internal-only cannot yield global (integration) | `cognition/novelty.py` — `PriorArtSearch` records only sources it actually searched (unreachable / unauthorized ones become limitations), `NoveltyAuditor` checks the model's status against the record and stores nothing on refusal; `core/models/prior_art.py::novelty_coverage_problems` is the one statement of the rule; `002b` holds it in SQL | `unit/test_novelty_audit.py` (10), **`integration/test_prior_art_postgres.py`** (7) | READY |
| 5 | **VER-008** | unbound or unversioned metric rejected; identical input + version → identical result across runs; two domains register different metrics, neither core-supplied (unit) | `verification/disagreement.py` — registration tabulates the domain's metric over the declared outcomes **twice** and keeps the table, refusing non-determinism, asymmetry, non-Decimal values, d(x,x)≠0; `rank_by_disagreement` reads only the table. SP pack: ordinal `dm:sp.rs_response_rank_distance`; ToyDomain: categorical `dm:toy.categorical_mismatch` | **`unit/test_disagreement_metrics.py`** (13, incl. a fresh-interpreter run under three hash seeds and an AST probe that core/verification/cognition define no metric) | READY |

## 3. The M3 reasoning flow, end to end

One question, `hard-1` of the fixed benchmark, through `HypothesisBrain` on PostgreSQL
(`e2e/test_hypothesis_brain_postgres.py`), every arrow a durable row:

1. **Question → evidence.** FAST_UTILITY query rewrite over an empty seed bundle (stored), then the
   primary retrieval under `srcpol:diagnosis` — internal matched runs first (§7.5) — stored as an
   EvidenceBundle.
2. **Stage A.** The Hypothesis Engine (REASONING_PRIMARY) proposes ≥2 complete certificates from
   that bundle only. §8's gate admits the set: certificates + typed predictions (`011i`), one
   genesis event each citing the primary bundle's attestations. The pack's two Domain Specialists
   each read their own domain bundle and state a Position; every Position names its bundle and
   `005e` checks the model saw exactly that bundle.
3. **Stage B.** The Critic's inverted retrieval reads the policy's *inverted* classes (literature
   and technical artifacts for a diagnosis) for evidence against the rivals' falsifiers, excluding
   everything the positions saw; the bundle is saved. The Critic (REASONING_ADVERSARIAL) cross-examines
   and its CritiqueReport is admitted only with independence `005e` re-derives. A cited
   contradiction (`MAY_REJECT`) and a named alternative (`BUNDLES_MATERIALLY_CONFLICT`) escalate:
   the engine certifies the alternative, §8 admits it, round 2 finds nothing new, no trigger, stop.
4. **Stage C.** VerificationPlanner (M2) + the pack's disagreement metric rank the CHARGE AC sweep
   over **every active rival**, the challenged ones included — a critique moves no belief (§7.6).
5. **Record.** DebateRecord: rounds, stop reason, triggers, position diversity, Critic divergence,
   whether the Critic changed the set, surviving diversity, extra evidence and tokens, metric
   versions, the LLM-002 gate reading (ADVISORY until a calibrated policy is activated).
6. **Belief.** `HypothesisBrain.attempt_revision` runs M3's preconditions, then M1's unchanged
   `BeliefEpisode`: the true mechanism is promoted on the inverted retrieval's external evidence
   with a durable, re-derivable Decision; its rivals stay ACTIVE. Every model call left one
   LLM_CALL span and two ledger rows (COST-001), and its provenance (LLM-001).

The benchmark (§1) runs the same flow in memory over all ten cases and three conditions.

## 4. Architectural decisions and the interpretations they rest on

1. **Extend, never fork.** M3 adds no second transition operator, no second budget gate, no
   second provenance path, no second tool path. Model calls go through `BudgetedInferenceDispatcher`
   → `ScientificInferenceService` (M1); transitions through `BeliefEpisode` (M1) behind a
   precondition gate; irreversible dispatch through M0b's `critique_gate`, attached inside M2's
   `BudgetedToolDispatcher` at the extension point M0b named (R-8).
2. **A precondition gate, not an evaluator.** `HypothesisRevisionGate` never says a transition
   *should* happen; it says one *may not enter* BELIEF_REVISION yet. `TransitionPolicy.evaluate`
   still decides on evidence (T-EPI-005 forbids a second operator).
3. **The database holds the storage-checkable half** (`v3.3-a13`'s split) for a writer that skips
   every Python gate: `005e` (certificate completeness, positions formed from their bundle,
   exhibited critique independence, inverted ≠ primary, append-only), `011i` (prediction
   membership, no back-filled predictions, the four revision rules), `010c` (calibration fields,
   one active version per gate, immutable versions), `002b` (coverage rules), `003e` (route slots).
4. **Critic divergence is the new-evidence share**, not Jaccard distance: the inverted retrieval
   excludes the primary evidence, so a Jaccard distance would be 1 for every non-empty retrieval
   and measure only whether anything was found. The gate reads the **debate-level** value (union of
   every round's inverted retrieval): a critique that searched and correctly found nothing new is
   a robust result, and a per-critique threshold would punish it.
5. **Calibration rule.** threshold = the smallest debate-level divergence among DEBATE cases that
   kept the true mechanism, `AT_LEAST`, sample size = those cases, artifacts = fixture digest +
   per-case table digest. The policy is produced **inactive**; activation is a separate act.
6. **"重大 REJECT"** (§7.6) is a REJECT that removes a rival from a **root-cause** set, or one in a
   set whose stakes reached its SourcePolicy's threshold. First read as *every* REJECT of a
   certificate (`011i`), which was equivalent while only debated hypotheses had certificates; R-12's
   closure made every hypothesis a certificate, so `011j` states the scope precisely (§11H). M0b's
   `critique_gate` already models "major" as a property of the REJECT (`is_major_reject`), and every
   set a debate admits is root-cause by default, so every REJECT the review accepted keeps its rule.
7. **Stakes are ordinal words each policy declares**; an undeclared word is refused rather than
   read as low (§8.1 rules out uncalibrated numbers). Inversion is required at
   `stakes ≥ policy.inverted_retrieval_threshold` (HIGH for diagnosis, NORMAL for novelty audit).
8. **Supervisor/PI and Verification Planner.** In M3 the Supervisor's `ResearchContract` is authored
   by a person and the debate request derives from it (`DebateRequest.from_contract`); task order,
   termination and gates are deterministic code. No Supervisor model call is made — the strict
   reading of "不能自行宣告物理真理". The Verification Planner's output here is Stage C's ranked
   candidate actions; the persisted VerificationPlan with a SelectionPolicy is VER-001/VER-005 (M4).
9. **Specialists and metrics are DomainPack declarations** (§24.3's `register_specialists`,
   `register_disagreement_metrics`). The declaration types live in `core/specialists.py` because the
   extension-boundary test forbids `cognition → domains`; core names no specialist and ships no metric.
10. **HypothesisSet** is the competing set EPI-001 counts, with `root_cause`, `stakes` and
    `inverted_retrieval_required` frozen at creation — a later policy cannot re-judge an old debate.
    `HypothesisBrain` reads stakes from the set (closing M1's "`stakes` is a parameter because
    `Hypothesis` does not exist until EPI-001 in M3").
11. **A genesis event cites its basis.** Admission resolves the bundle's attestations in the set's
    project and refuses an empty or foreign basis (`UNGROUNDED`), so §6.18's contamination rollback
    reaches a hypothesis proposed from contaminated evidence.

## 5. What changed outside the new packages (all additive)

| File | Change | Why it is not a behaviour change to a locked milestone |
|---|---|---|
| `tools/dispatch.py` (M2) | `ToolAction.critique_id`, optional `critiques=` lookup, `_require_independent_critique` before the gate | acts only on an **irreversible** Capability or estimate; every M2 capability is reversible and M2's 26 dispatch tests pass unchanged |
| `cognition/llm.py`, `cognition/inference.py` (M1) | optional `context=` appended to the rendered prompt and hashed into the record | absent context → byte-identical material; M1's provenance tests pass unchanged |
| `core/models/inference.py`, `identifiers.py`, `models/__init__.py` | §7.3 slot values; M3 id prefixes; exports | enum/prefix additions only |
| `domains/base.py`, `domains/registry.py`, SP `plugin.py`, `tests/toy_domain.py` | §24.3's `register_specialists` / `register_disagreement_metrics`; the debate benchmark id | new registries; existing registrations untouched |
| `spec/schema_drift.py` | binds `OutcomeSpace`, `BenchmarkPolicy`; records M3's unbound schemas with reasons | the guard got stricter, not looser |
| `scripts/migrate.py`, `tests/postgres_fixtures.py`, `scripts/mutation_battery.py` | six migrations appended; M3 tables truncated; `admit_hypothesis_identity`; 34 M3 mutations | infrastructure |
| `core/repositories/belief_events.py` (M0b) | `InMemoryBeliefEventStore(known_hypotheses=…)`: the fake refuses an unadmitted target, as `011j` does | M0b's own parity rule ("a fake that accepts what the database rejects makes a green suite meaningless"); its two in-memory tests now name the hypothesis they append for |
| 12 pre-M3 PostgreSQL test files (§11H) | each admits the hypotheses it revises before writing events | identity only: no assertion, expected outcome or state sequence changed |

Two M3 names were changed during the full regression because they collided with locked M1
structural probes, and the probes were **not** edited: `novelty_assessments.status` →
`novelty_status` (T-EPI-005's "no undeclared `status` column"), and `StructuredDebate._critique` →
`_cross_examine` (the "only `ScientificInferenceService` reaches the raw seams" text probe).

## 6. Migrations

Appended in order: `003e_model_route_slots`, `010c_outcome_spaces_benchmark_policies`,
`005e_hypotheses_and_debate`, `011i_predictions`, `002b_prior_art_search`, and — for R-12 —
`011j_belief_event_targets` (§11H): 44 declared in total. Applied to a fresh database from empty
and re-run idempotently (§8). No migration already committed was edited: `011j` replaces `011i`'s
two functions with `CREATE OR REPLACE`. Schema-drift binds the two §17 blocks `010c` matches field
for field.

## 7. Adversarial cases tested

- an engine that proposes a single cause; a set of one written **around** the admission service
  and promoted **around** the brain (refused by the gate and by `011i`);
- two phrasings of one mechanism; an incomplete / prediction-less / author-less certificate (the
  whole set is refused and nothing is written); a prediction outside its space, a back-filled
  prediction, a prediction whose effect lands on another hypothesis;
- a basis borrowed from another project through an unscoped lookup;
- a Critic citing evidence it was not shown (refused; its inference is still durable);
- a critique that changes no bundle, policy or route (refused as not independent); a critique row
  that overclaims its axes, claims none, or presents the primary retrieval again as "inverted";
- a Position that names a bundle other than the one its model saw;
- a REJECT adjudicated only by INFERRED records; a REJECT with no critique; a critique written
  after the decision; a high-stakes transition after a debate without inverted retrieval;
- an irreversible dispatch with no critique, with a valid human approval, with a critique that was
  never stored, of another Episode, or that cites nothing — the fatal-spy tool is never entered and
  the approval claim is never spent;
- **a valid independent critique (differs in bundle and route, durable, same Episode) that cites
  only INFERRED records** — refused as MODEL_OPINION, in memory and on PostgreSQL, even with a human
  approval; one citing only DISPUTED evidence; one citing a ghost beside real evidence; one whose
  evidence an unscoped store returns from another project; a dispatcher with no attestation store;
- a caller handing the brain a relabelled attestation object (refused `EVIDENCE_NOT_ON_RECORD`);
  a REJECT whose only basis is on record as INFERRED;
- a belief event for a hypothesis nobody admitted, through the Python store, the append function
  and a bare INSERT; one naming another project's hypothesis; the foreign key with its explanatory
  trigger switched off; `011j` replayed over an orphan history (it refuses with the remedy);
- a yes-man Critic (the benchmark returns **REFUTED**); a debate forced to its maximum rounds on
  every case (the benchmark's round-count check fails it although every metric is recorded);
- a metric that drifts between evaluations, is asymmetric, returns floats, is bound to an
  undeclared space, is unversioned, or changes under one version;
- a GLOBAL novelty claim over an internal-only search, over a search that skipped the patent
  corpus, over an unreachable provider, or with no date range; a status with no search record.

## 8. Verification

Measured locally on 2026-09-26 (Windows, Python 3.12.10, PostgreSQL 17 in Docker on port 5433),
against a database created empty for this purpose (`lab_brain_m3r1`). CI results are in the final
report.

| Gate | Result |
|---|---|
| `ruff format --check` / `ruff check` (src tests scripts) | 300 files formatted / all checks passed |
| `mypy` (strict, `lab_brain`) | no issues in 164 source files |
| backend-free `pytest` | **1472 passed**, 666 skipped (PostgreSQL-gated) |
| `scripts/migrate.py` from an empty database, then again | **44 applied**, then `pending: 0` |
| PostgreSQL profile, full suite (`LAB_BRAIN_TEST_POSTGRES=1`) | **2138 passed, 0 failed** — M0a–M2 regression included, with `011j` in force |
| `scripts/mutation_battery.py` with the PostgreSQL profile | **154/154 killed** (120 pre-M3 + 34 M3) |
| `check_requirement_coverage.py` | DONE `[M0a, M0b, M1, M2]`, IN_PROGRESS `[M3]`, all checks ok |
| `update_status.py --check`, `rebuild_obligation_inventory.py --check` | current; 84 occurrences in sync |
| `run_benchmark.py --check`, `run_debate_benchmark.py --check` | both reports current |

These are the counts after the review repairs (§11); the first submission measured 1452 / 2108 /
145, on 43 migrations.

Two M3 mutations survived the first battery run and each exposed a real test gap, closed before
this table was measured: the admission service's own project check (a lookup that scopes by project
had been hiding it) and the inverted retrieval's exclusion of primary evidence (disjoint class sets
under `srcpol:diagnosis` had made it vacuous; the test now uses MECHANISM_DISCOVERY, whose classes
overlap).

## 9. Remaining risks and deliberately deferred work

1. **R-12 is closed** (§11H). What remains of it: a database that already holds events for
   hypotheses nobody admitted cannot take `011j` until those targets are admitted — deliberately;
   the migration refuses with a count and the remedy instead of validating around them.
2. **A Run's witness is recognised by its `run_id` source.** VERIFICATION_RESULT vs EXTERNAL_EVIDENCE
   is a distinction for the record; both are accepted adjudicators, so nothing turns on it yet.
3. **The model is a deterministic mock.** The benchmark measures what the *protocol* does with
   evidence under an answer-blind, mechanism-aware reasoner; it says nothing about a real model's
   reasoning. Ten cases, one domain: the calibrated threshold is a calibration of this benchmark,
   not a population estimate, and is re-calibrated as a new version when the fixture, metric
   version or route changes. No external model, search, licensed tool or real execution occurred.
4. **Position diversity is lexical.** It uses the deterministic hashing embedder EVI-007 declares
   (named in the metric version); a semantic embedding model is a configuration change.
5. **No Supervisor model call and no persisted VerificationPlan** (§4.8) — M4's VER-001/VER-005.
6. **§12.1 episode states.** `research_episodes` still reaches only M1's states; the
   HYPOTHESIS_FORMATION state belongs to the episode lifecycle requirement, not to M3's five.
7. **The benchmark report is regenerated, not diffed in CI.** `run_debate_benchmark.py --check`
   and `test_the_committed_report_is_current` hold it to the code.

## 10. Governance

Every M3 requirement has marked tests of its §26 kind (e2e for EPI-001 and SRC-002, benchmark for
LLM-002, integration for SRC-003, unit for VER-008) that ran and passed under the PostgreSQL
profile. M3 remains `IN_PROGRESS` in `docs/milestones.yaml`; the ratchet will enforce it only when
the maintainer marks it `DONE` on independent review.

## 11. The independent M3 review — two blockers, repaired

The review accepted the architecture and named two blockers. Nothing else was redesigned.

### G (SRC-002) — citing evidence was treated as being adjudicated by it

**Defect.** `BudgetedToolDispatcher` set a critique's adjudicator to EXTERNAL_EVIDENCE whenever the
CritiqueReport cited *any* attestation. An INFERRED attestation is a model's interpretation (EVI-003),
so a valid independent critique citing only model-generated records released an irreversible action
on another model's opinion — exactly what §7.6 refuses.

**Repair.** `core/adjudication.py` is the one statement of §7.6 adjudication, used by both triggers.
The dispatcher re-reads every cited attestation from the attestation store **in the action's
project** and fails closed: a citation that does not resolve (or resolves to another project's row)
refuses the action; INFERRED and DISPUTED records are set aside; only what remains can make the
adjudicator EXTERNAL_EVIDENCE — or VERIFICATION_RESULT when it is a Run's witness — and nothing left
is MODEL_OPINION, which M0b's unchanged `evaluate_dispatch` refuses. A dispatcher with no attestation
store cannot show the adjudication and refuses. On the belief path, `HypothesisRevisionGate` applies
the same `admissible` rule, and `HypothesisBrain` re-reads each supplied basis attestation and
refuses an object that is not the record (`EVIDENCE_NOT_ON_RECORD`), so a caller cannot relabel an
INFERRED note as MEASURED. For a writer that skips the brain, `011j`'s deferred constraint trigger
`belief_revisions_are_adjudicated_by_evidence` holds the same rule in SQL: a major REJECT, or any
transition in an above-threshold set, must cite at least one attestation whose RECORDED type is not
INFERRED and whose status is not DISPUTED.

**Evidence.** `unit/test_adjudication.py` (11), `unit/test_irreversible_dispatch.py` (13, six new —
headed by `test_a_valid_independent_critique_citing_only_inferred_evidence_does_not_release_the_action`),
`unit/test_revision_gate.py`, and on PostgreSQL
`e2e/test_hypothesis_brain_postgres.py::test_an_irreversible_action_is_not_released_by_a_critique_citing_only_inferred_records`,
`::test_a_reject_adjudicated_only_by_inferred_records_is_refused`,
`::test_a_relabelled_attestation_is_not_the_record_and_real_evidence_is`, and
`integration/test_hypothesis_storage_postgres.py::test_a_major_reject_resting_only_on_inferred_records_is_refused_by_the_database`. Mutations that restore the
original defect (`citing_anything_is_external_evidence`) or drop any one exclusion are killed.

### H (EPI-001) — R-12: a belief event could target a hypothesis nobody admitted

**Defect.** `belief_revision_events.target_id` had no foreign key, which `v3.3-a12` leaves to
EPI-001/M3; any writer could record a history for a hypothesis that never passed §8's gate.

**Repair.** `011j_belief_event_targets.sql`:

- **Identity is the pair.** `hypotheses` is re-keyed on `(project_id, hypothesis_id)` — M0b's
  identity for a history ("two projects may legitimately use the same hypothesis id"), which a
  global key would have broken and which the locked conflicts suite exercises. `predictions` and
  `parent_id` follow with composite keys.
- **The foreign key.** `belief_revision_events (project_id, target_id)` references
  `hypotheses (project_id, hypothesis_id)` — every write path, raw SQL included. `011i`'s trigger,
  replaced with project-scoped lookups, says why before the key speaks.
- **Existing histories.** A database holding events for unadmitted targets is refused with a count
  and the remedy (admit them, then re-run), not validated around with `NOT VALID`.
- **The REJECT scope** (§4.6), so M2's SIM-002 reject path keeps its hard-locked semantics now that
  its hypotheses are certificates.

`SqlHypothesisStore` / `InMemoryHypothesisStore` read certificates by the pair, and the in-memory
event log refuses an unadmitted target for M0b's parity reason.

**Fixture updates, and only fixture updates.** The M0b–M2 PostgreSQL suites wrote events for ids no
gate had admitted. `tests/postgres_fixtures.admit_hypothesis_identity` gives each the identity it
always meant: a human-authored §8 certificate with one typed prediction in a routine set. Twelve
files call it before their first event (two helpers that mint an id per event call it per event);
the diff removes no assertion and changes no expected outcome — its only removed lines are import
lines and two in-memory store constructors that now name their hypothesis.

**Evidence.** `integration/test_belief_event_targets_postgres.py` (6): the Python store, the append
function and a bare INSERT all refuse an unadmitted target; another project's hypothesis is not a
target; the foreign key holds with the trigger disabled; two projects keep separate histories for
one id; the schema carries the pair; `011j` refuses to run over an orphan history.
`integration/test_hypothesis_storage_postgres.py` pins the REJECT scope from both sides. The full
PostgreSQL regression passes with the constraint in place (§8).

## 12. Sign-off

**M3 DONE / HARD-LOCKED**, 2026-09-27, on independent review, at
`6416adb1f72ada341f82fb04731e1fababd140d9` -- the commit that proved §7.6 adjudication from the durable
record and closed R-12 (§11, repairs G and H). Recorded, not decided, by the implementing agent:
`docs/milestones.yaml` moves M3 to `DONE`, and from this commit the executed-coverage ratchet
enforces all five M3 requirements on every CI run under `gate_profile: [postgres]`, as it already
does for M0a, M0b, M1 and M2.

What the lock covers is the accepted architecture: §8's admission gate and the competing
HypothesisSet; `HypothesisBrain` as the precondition gate in front of M1's unchanged `BeliefEpisode`;
the stake-adaptive StructuredDebate with the Critic's own inverted retrieval and exhibited
independence (`005e`); §7.6 adjudication proven from the record (`core.adjudication`) on both
triggers; the calibrated, inactive-until-activated BenchmarkPolicy and the fixed debate benchmark;
coverage-recorded novelty; DomainPack-declared, tabulated disagreement metrics; and `011j`'s
`(project_id, hypothesis_id)` identity with every belief event referencing an admitted hypothesis.
Later milestones may extend these at their declared extension points; they may not refactor them
for cleanliness. Reopen only on a reproducible violation of a locked invariant or a demonstrated
spec contradiction.

What the lock does not cover, because it was never claimed: a real model (the benchmark's reasoner
is a deterministic mock), a Supervisor model call and the persisted VerificationPlan (M4).
