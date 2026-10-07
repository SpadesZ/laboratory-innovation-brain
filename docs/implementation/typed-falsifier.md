# Every admitted hypothesis carries a typed falsifier

Date: 2026-10-07
Scope: the P1 the blind LOCAL verification smoke (`epi:ac49adeb...`) exposed. **Not a milestone.**
No Requirement or Test ID was added and no milestone status changed. The prediction vocabulary, the
planner, `verification.evidence.comparable()` and `evidence_from_run`, the TransitionPolicies, the
catalogs' content, the benchmarks, VER-004, the research minimum (5), budget, the inference
deadline, egress, credentials, transport locality and the redirect policy are unchanged. The Lumi
Agent benchmark was not run.

## 1. The P1

A RelationJudgment comes only from a relation effect a hypothesis's own Prediction declared before
the verification action ran, for the exact outcome observed (`comparable`: same observable, same
OutcomeSpace id and version, same outcome). In the smoke the deployed model wrote each falsifier in
prose ("the normalization length matches the drawn length") and declared only
`sp.normalization_basis = DISAGREES -> SUPPORTS`. The deterministic reader really ran and observed
`AGREES` -- the very outcome the prose falsifier named -- and nothing moved: no relation, no
TransitionPolicy decision, no BeliefRevisionEvent. That is correct behaviour for the certificate
admitted; the defect was admitting it. A prose falsifier is not a falsification contract.

Not solved by inferring an inverse outcome, by "not SUPPORTS means CONTRADICTS", by treating a
space as binary, by a post-hoc model judgement, or by a planner or workflow heuristic that invents a
RelationJudgment. `comparable()` still never infers anything from Y != X.

## 2. The typed falsifier

**The certificate designates it.** `HypothesisCertificate.falsifier_prediction_ids` -- beside, not
inside, M0b's hard-locked `Hypothesis` (whose prose `falsifier` stays, for explanation and the
Critic's inverted retrieval) -- names the carried predictions that ARE the falsifier. The
certificate refuses a designation it does not carry, a repeated one, and one whose prediction
declares anything but CONTRADICTS on this hypothesis. An empty designation still reads back (rows
admitted before this change), and admission refuses it.

**The engine's contract states it** (prompt `prm:hypothesis-engine` 4.0.0, contract `rc-3.0.0`):

```json
{"key": "h1", "falsifier": "<prose>", "falsifier_prediction_keys": ["f"],
 "predictions": [
   {"key": "s", "observable_ref": "...", "outcome_space_id": "...", "outcome_space_version": "...",
    "expected_outcome": "DISAGREES", "relation_effect": "SUPPORTS"},
   {"key": "f", "observable_ref": "...", "outcome_space_id": "...", "outcome_space_version": "...",
    "expected_outcome": "AGREES", "relation_effect": "CONTRADICTS"}]}
```

Every prediction carries a key unique within its hypothesis; `falsifier_prediction_keys` lists at
least one key of the hypothesis's own CONTRADICTS predictions. The prompt also says what the system
does with what is not declared: "A prediction relates only the outcome it names; an outcome no
prediction names relates to nothing." The falsifier need not share the SUPPORTS prediction's
observable, and no outcome is required to carry an effect.

**The parser is the admission boundary.** `parse_hypothesis_engine` refuses, before anything is
admitted: no designation (absent or empty) -- including a certificate that carries a CONTRADICTS
prediction it did not designate; a key naming no prediction of the same hypothesis (dangling, or
the rival's); a designated SUPPORTS, PREDICTS or TESTS prediction; a prediction with no key or a
repeated key; and, as before for every prediction, an invalid observable, space, version or
outcome. `debate._certificate` maps the engine's keys to the minted prediction ids, so the
designation survives intact.

**Every writer is held to it.** `certificate_completeness_problems` (shared by the admission gate
and the in-memory store) adds "no typed falsifier". Migration `012n` adds
`hypotheses.falsifier_prediction_ids TEXT[]` (default empty; history is not rewritten) and restates
`011j`'s genesis function with one more check: a hypothesis is admitted only if its designation is
non-empty and every designated id is a prediction of the same hypothesis in the same project whose
every effect is CONTRADICTS. `hypotheses` and `predictions` are immutable, so what was admitted
stays what was checked. The check runs at the genesis event, as `011i`'s typed-Prediction check
does, and the database does not require a genesis event before a transition (the M0b-M2 suites
write transitions on hypotheses that have only their identity row). A raw writer who also records
an ALLOW decision can therefore store a transition of a hypothesis never admitted -- the same
DB-level acceptance `test_belief_authorization_verification_postgres` documents for a forged
authorization. It moves no belief: the read side re-derives every decision (`verified_history`) and
`replay` applies no transition without its predecessor, so the hypothesis has no state. Requiring a
genesis event in SQL would change those suites' invariants and is left to its own change.

**The pack's catalog declares its own.** `CatalogMechanism.falsifier_prediction_keys` (refused when
empty or not naming one of its CONTRADICTS predictions); silicon photonics designates the
CONTRADICTS half of each mechanism's declared pair -- the typed form of the falsifier it already
stated (e.g. normalization: `sp.normalization_basis = AGREES`).

**After admission nothing changed:** ObservedOutcome -> exact comparable Prediction -> its
predeclared relation effect -> RelationJudgment -> TransitionPolicy -> BeliefRevisionEvent ->
EpistemicStateProjection.

## 3. Versions and qualification

| | before | now |
|---|---|---|
| prompt `prm:hypothesis-engine` | 3.0.0 | **4.0.0** |
| response contract | rc-2.0.0 | **rc-3.0.0** |
| probe version | probe-4.0.0 | **probe-5.0.0** |
| ROLE_HYPOTHESIS suite | hypothesis-conformance@2.0.0 | **hypothesis-conformance@3.0.0** |
| `QUALIFICATION_DIGEST` | `5f82fb7a15f5...` | **`43ce474f374e...`** |

The suite keeps its two synthetic, domain-agnostic cases (`contextual-minimum`, `multi-space`); a
case now passes only if every hypothesis it accepts designates a typed falsifier, judged by the
real parser. The digest change stales every lock made before, automatically.

## 4. Tests

- `tests/unit/test_typed_falsifier.py` (backend-free): every parser refusal above; the exact
  falsifying outcome with CONTRADICTS admitted as declared, over any declared binding, with other
  outcomes left unrelated; the certificate's refusals; the admission gate refusing a prose-only and
  an undesignated certificate and writing nothing; the pack's catalog; a debate whose every
  certificate designates its own CONTRADICTS predictions; in the toy domain, a mismatch with a
  SUPPORTS prediction and an outcome no prediction names relating nothing, while the exact
  designated outcome yields CONTRADICTS from that prediction, traceable to its Run; generic code
  importing no domain pack; the suite failing each adversarial reply; the two locks the LOCAL
  deployment holds recomputed and no longer current.
- `tests/integration/test_typed_falsifier_postgres.py`: designations stored, resolving and
  immutable; `012n` refusing a genesis -- through the store and INSERTed directly -- with no
  designation, a SUPPORTS, mixed, rival, blank or dangling designation, a NULL element, or the same
  hypothesis id's prediction in another project; a transition written around admission accepted as
  a row but moving no belief (the history does not verify); a prose-only model failing
  ROLE_HYPOTHESIS;
  a route qualified under the vocabulary semantics stale until tested again, every earlier row
  unchanged.
- `tests/e2e/test_web_typed_falsifier_postgres.py`: through the web workspace with a model route,
  the normalization check really runs, observes `AGREES` -- the falsifier the normalization
  hypothesis designated -- and the path Run -> Observation -> Attestation (OBSERVED) ->
  RelationJudgment CONTRADICTS from that prediction -> TransitionPolicy decision ->
  BeliefRevisionEvent with its ALLOW decision is in the database; no relation exists that a
  prediction did not declare for the exact outcome observed.
- Fifteen mutation entries (missing designation, broken link, wrong effect, inference from a
  mismatch, the observed CONTRADICTS path); two vocabulary entries re-anchored.

## 5. Disagreement ranking (fixed separately)

The typed falsifier made a CONTRADICTS prediction mandatory on every hypothesis, which exposed a P1
in `rank_by_disagreement`: it compared falsifying outcomes as if they were rival forecasts, so rivals
with identical signatures scored a positive disagreement and the planner could prefer a simulation
over a cheaper sufficient check. Fixed in its own change; see
[`forecast-disagreement.md`](forecast-disagreement.md).

## 6. Verification

Code: `cdcc267`. CI run `37566892555`: commit hygiene, spec conformance, lint/types/full suite and
the PostgreSQL backend profile, all green.

| Run | Passed | Skipped |
|---|---|---|
| local, Windows: `pytest -q` | 1723 | 844: 842 PostgreSQL-gated, 1 Lumerical, 1 network |
| local, fresh database (61 migrations): `LAB_BRAIN_TEST_POSTGRES=1 pytest -q` | 2565 | 2: 1 Lumerical, 1 network |

| Check | Result |
|---|---|
| ruff check / ruff format / strict mypy | clean (237 source files) |
| `update_status.py --check`, obligation inventory, requirement coverage | current |
| evidence and root-cause (`--disposable`) benchmark reports | current, unchanged |
| debate benchmark report | regenerated: digests and token estimates only (cost ratio x3.78 -> x3.35), every verdict identical |
| mutation battery, all entries (fresh database) | 416/416 killed, no anchor missing (resumed at entry 30 after an output-decoding stop in the runner's environment; no entry survived) |

Raw SQL cannot bypass the designation: a genesis INSERTed directly is refused with no designation,
a SUPPORTS, mixed, rival, blank or dangling designation, the same hypothesis id's prediction in
another project, or a NULL element. A transition written around admission under a recorded ALLOW
decision is stored as a row (the database requires no genesis before a transition, as the M0b-M2
suites rely on) and moves no belief: its history does not verify and `replay` gives no state.

The ranking P1 found here was fixed separately (`492856d`, [`forecast-disagreement.md`](forecast-disagreement.md));
the deployment below runs both.

## 7. Deployed, and re-qualified

`docker compose -p lab-brain-workspace up --build -d` from `492856d`, with
`LAB_BRAIN_INFERENCE_DEADLINE=1200` in the git-ignored `.env`; the migration step applied `012n`
and `local-models` changed nothing.

- *Every lock stale, automatically.* qwen2.5-coder:7b `lk:de37c0ddb915b220`, qwen2.5:7b
  `lk:427cdea03b491e41` and an earlier stand-in's: "...made under qualification semantics no longer
  in force...". The applied `local-vocabulary` was NOT READY on every slot and
  `load_active_runtime` refused it. Retired; both models unlocked; confirming the coder again at
  once was refused (`lock.outdated_tests`): "...were not run under the qualification semantics in
  force (probe-5.0.0 43ce474f374e; theirs: probe-4.0.0 5f82fb7a15f5)".
- *qwen2.5-coder:7b under the final semantics (1289 s):* CHAT, STRUCTURED_JSON, ROLE_QUERY,
  **ROLE_HYPOTHESIS (`hypothesis-conformance@3.0.0` at N=5, slowest case 509 s)**, ROLE_SPECIALIST,
  ROLE_CRITIQUE and CODE passed; VISION errored (no images). Locked: **`lk:06d7d886bcb85a5a`**.
- *qwen2.5:7b under the final semantics (593 s):* CHAT, STRUCTURED_JSON, ROLE_QUERY,
  ROLE_SPECIALIST and ROLE_CRITIQUE passed; **ROLE_HYPOTHESIS failed** (multi-space: the reply was
  not JSON); CODE failed; VISION errored. Locked: **`lk:271a4fad2094aab1`** (CHAT, ROLE_CRITIQUE,
  ROLE_QUERY, ROLE_SPECIALIST, STRUCTURED_JSON) -- eligible for REASONING_ADVERSARIAL, and listed
  as not eligible for REASONING_PRIMARY ("not proven: ROLE_HYPOTHESIS").
- *The configuration* `local-typed-falsifier` (`lrt:36a5f7c0...`, labels PUBLIC): REASONING_PRIMARY
  and FAST_UTILITY -> qwen2.5-coder:7b, REASONING_ADVERSARIAL -> qwen2.5:7b, every route LOCAL.
  Ready, applied, loaded.

## 8. The same blind verification smoke

Episode **`epi:04d7d46b-6bef-4266-8f92-758ae9f5a2cc`** (`prj:smoke-local`, PRIVATE, LOCAL-only), one
run of **1613 s**: the synthetic `rs_anomaly_report.md` already in the project
(`art:sha256:8b30ebc9...`) and the same `PS-501.device.json` (`nominal_device` merged with
`contact-open-via`'s `device`, no evaluator field; `art:sha256:3741fc2d...`, byte-identical). No
literature, no simulator, the benchmark unchanged.

**Model calls** (seven; each with an `LLM_CALL` span, ESTIMATED and ACTUAL BudgetGate entries, and
InferenceProvenance naming model, route, prompt id and version and EvidenceBundle hash; all
`ollama`, LOCAL): Evidence Researcher (coder, 35 s) -> **Hypothesis Engine (coder, prompt 4.0.0,
498 s)** -> two specialists (coder, 151 s and 135 s) -> the Critic's inverted retrieval (coder,
21 s) -> **Adversarial Critic (qwen2.5:7b, its own route, 404 s)** -> the engine certifying the
Critic's alternative (coder, 361 s; three certificates repeating admitted mechanisms, none
admitted). One debate round, stopped STABLE.

**Hypotheses -- parser ACCEPTED; each certificate one prediction, designated as its falsifier.** As
the model wrote them (keys from its output; ids as stored):

| Hypothesis | prose falsifier | typed falsifier (designated) |
|---|---|---|
| PROCESS_DEPENDENT_CONTACT_RESISTANCE `h1` | "A transmission-line measurement on the same wafer shows a normal Rs bias dependence." | `p1` `prd:4be47006...`: `sp.probe_contact_resistance` in `os:sp.probe_contact_resistance@1.0.0` = ELEVATED -> CONTRADICTS |
| MESH_ARTEFACT `h2` | "A mesh-sensitivity sweep on the simulated structure shows no significant effect on Rs." | `p2` `prd:e0df586a...`: `sp.mesh_stability` in `os:sp.mesh_stability@1.0.0` = UNSTABLE -> CONTRADICTS |
| DEPLETION_EFFECT `h3` | "The capacitance curves in Figure 2 are distinguishable within measurement uncertainty." | `p3` `prd:26676939...`: `sp.small_signal_impedance` in `os:sp.rs_bias_response@1.0.0` = RS_BIAS_INSENSITIVE -> CONTRADICTS |
| INSTRUMENTATION_OFFSET `h4` | "An instrumentation offset would appear on both splits equally and would not survive the re-measure." | `p4` `prd:6b230534...`: `sp.probe_contact_resistance` in `os:sp.probe_contact_resistance@1.0.0` = NOMINAL -> CONTRADICTS |
| NORMALIZATION_BASIS_ISSUE `h5` | "The normalization basis agrees between splits A and B." | `p5` `prd:2a42a88e...`: `sp.normalization_basis` in `os:sp.normalization_basis@1.0.0` = DISAGREES -> CONTRADICTS |

Every designated id is a prediction of the same hypothesis whose only effect is CONTRADICTS on it.
No certificate declared a SUPPORTS or PREDICTS prediction.

**Verification.**

- Plan `vpl:d20854c2...`: candidates `cap:sp.extraction_consistency` (ANALYTICAL_RULE_CHECK,
  AVAILABLE, 2 s) and `cap:sp.fourpoint_probe` (MEASUREMENT, a person's act; 90 human minutes,
  250 money, 14400 s). Both SUFFICIENT -- extraction: NORMALIZATION_BASIS_ISSUE -> CHALLENGED /
  CONTRADICTED if DISAGREES; four-point: PROCESS_DEPENDENT_CONTACT_RESISTANCE if ELEVATED,
  INSTRUMENTATION_OFFSET if NOMINAL. Affirmative disagreement UNKNOWN for both (no forecasts at
  all); for the four-point probe the pre-fix pooled rule would have scored 1 from the two
  falsifiers (ELEVATED vs NOMINAL) and marked it discriminating. Both in the same (sufficient, not
  discriminating) group; the extraction check alone is the Pareto front and dominates the probe on
  the policy's Pareto dimensions (`slp:sp.vs001@1.0.0`). Chosen: `cap:sp.extraction_consistency`.
- **It really ran:** Job `job:1243e8bd...` / Run `run:1243e8bd...`, backend
  `sp.local.normalization_basis_reader`, input the device artifact, output
  `art:sha256:049ad77f...` (content-addressed: the same bytes the same reader produced from the same
  device in the previous smoke). Observation `obs:774535d2...`: `sp.normalization_basis = AGREES`;
  admitted as attestation `att:03151cd4...` (OBSERVED), tied to that Run and Observation.
- **No relation.** The only prediction over that observable declares DISAGREES -> CONTRADICTS.
  AGREES matches no declared prediction exactly, so no RelationJudgment, no TransitionPolicy
  decision and no BeliefRevisionEvent followed -- nothing was inferred from the outcome differing
  from DISAGREES. The model's typed falsifier for this hypothesis is DISAGREES; the sentence of its
  prose falsifier reads "agrees". Only the typed one is adjudicated.
- Plan `vpl:309de623...`: the extraction check excluded as already executed; candidate and choice
  `cap:sp.fourpoint_probe`, which no pack executes: a person's act, listed as such
  (HUMAN_ACTION_REQUIRED). Pending, not emulated: `cap:sp.charge_ac_sweep` (best next:
  DEPLETION_EFFECT -> CONTRADICTED if RS_BIAS_INSENSITIVE) and `cap:sp.mesh_sensitivity`
  (MESH_ARTEFACT -> CONTRADICTED if UNSTABLE); no simulation job exists in the project. The episode
  is `SUSPENDED` ("awaiting simulator for cap:sp.charge_ac_sweep"), its run PROVISIONAL.
- **Belief:** through the production read path (`verified_history` -> `replay`) all five rivals are
  ACTIVE, each history one genesis event under `tp:research.admission@1.0.0`, verified 1/1. No belief
  moved, and none without an ALLOW decision.

**Blind comparison, after the run.** The evaluator truth for `contact-open-via` is
`contact_discontinuity` (expected stop CONFIRMED, cheaply resolvable). The model's set holds no
contact-discontinuity hypothesis and no prediction over `sp.contact_connectivity`, so
`cap:sp.inspect_contact_connectivity` -- the local check that reads the missing cathode via -- was
never a candidate: a **LOCAL MODEL SCIENTIFIC-QUALITY failure**, the same as before. Beside it, the
model's typed falsifiers for three mechanisms are the opposite of the pack's own catalog over the
same observables (which designates NOMINAL, STABLE and AGREES as the falsifying outcomes where the
model wrote ELEVATED, UNSTABLE and DISAGREES), and it declared no forecast for any hypothesis --
also model quality: the
contract checks that a falsifier is typed, the hypothesis's own and CONTRADICTS, not which outcome
refutes a mechanism. The pipeline was correct: canonical typed predictions, a sufficient plan, a
real deterministic check, admitted evidence, no relation from a mismatch, no simulation, every call
budgeted, provenanced and local.

**History is untouched.** Against a snapshot taken before the rebuild (cutoff
2026-10-07 14:36:20 UTC): 34 InferenceProvenance rows, 7 episodes and their 8 runs, 104 probe rows,
9 lock rows, 20 hypotheses (pre-`012n` columns), 25 predictions, 2 relations, 22 belief events, 2
decisions, 3 observations, 126 attestations, 6 plans, 6 jobs, 6 runs and 75 cost entries,
identical; ingestion items unchanged (3). No external snapshot; the project has no egress policy.
