# A prediction's observable is a declared, canonical identifier

Date: 2026-10-07
Scope: the P1 the full LOCAL verification smoke exposed. **Not a milestone.** No Requirement or Test
ID was added and no milestone status changed. The planner, the capability descriptors, the
catalogs, the benchmark, VER-004's space and outcome checks, the research minimum (5), budget, the
inference deadline, egress, credentials, transport locality and the redirect policy are unchanged.
The Lumi Agent benchmark was not run.

## 1. The P1

`VerificationPlanner` matches `Prediction.observable_ref` EXACTLY against `Capability.produces` --
the planner consumes canonical typed identifiers. But the Hypothesis Engine was shown only the
declared OutcomeSpaces, its response contract called `observable_ref` "<what is observed>", and its
parser checked the space pair and the outcome, never the observable. The deployed model wrote
`os:sp.normalization_basis` where `sp.normalization_basis` belongs; the prediction was admitted,
and no verification action could ever match it.

Not solved by fuzzy matching, prefix stripping, aliases, similarity, a model normalising the value
or a planner heuristic, and no space id is turned into an observable by a naming convention.

## 2. The prediction vocabulary

**A DomainPack declares it, beside its spaces.** `DisagreementMetricRegistry` -- where a pack already
declares its OutcomeSpaces and the metrics bound to them (§24.3's `register_disagreement_metrics`) --
gains `declare_observable(observable_ref, outcome_space_id, version)`:

- the space must be declared first; one observable is read in exactly one space (a second binding
  is refused); several observables may share a space; an observable must be a canonical identifier;
- `observable_bindings(domain)` returns the domain's vocabulary, observable → declared space.

That is the whole representation: a binding from a canonical observable to a declared, versioned
space. It does not come from the backends installed here, so a prediction over an observable only
a simulation could check stays a valid prediction target.

- **Silicon photonics** declares the map it already kept (`vertical.prediction_bindings()`, the same
  map `space_for` reads): `sp.contact_connectivity`, `sp.normalization_basis`, `sp.mesh_stability`,
  `sp.carrier_profile`, `sp.probe_contact_resistance` → their `os:sp.*@1.0.0` spaces, and
  `sp.small_signal_impedance` → `os:sp.rs_bias_response@1.0.0`. Every catalog and fixture already
  predicted with exactly these pairs.
- **The toy test pack** declares `toy.widget_stiffness` → `os:toy.widget_verdict@1.0.0` through the
  same call; generic cognition and the LLM runtime name no domain's observable.

**The engine is shown it.** The debate reads the domain's bindings (and refuses to start a
Hypothesis Engine call for a domain that declares none) and renders them as
`CONTEXT.prediction_bindings` (`roles.binding_context`): per binding, `observable_ref`,
`outcome_space_id`, `outcome_space_version`, `outcomes`, `action_type`. The old `outcome_spaces`
list is gone, so there is no bare space list to copy an observable from.

**The parser enforces it.** `parse_hypothesis_engine(text, *, bindings, minimum)` admits a prediction
only when (observable_ref, outcome_space_id, outcome_space_version) is a declared binding and the
expected outcome is one that space admits. It refuses, each with its reason (VER-004):

| Refused | Example |
|---|---|
| a space the engine was not shown (unchanged) | `os:sp.contact_connectivity@2.0.0` |
| an observable not in the vocabulary -- including a space id written as the observable | `os:sp.normalization_basis`, `sp.cj_per_mm` |
| a declared observable with another binding's space, or a legal space with another observable | `sp.contact_connectivity` in `os:sp.normalization_basis@1.0.0` |
| an outcome the bound space does not admit (unchanged) | `ELEVATED` for connectivity |

No hypothesis has to use every observable or every space. An accepted prediction reaches the typed
`Prediction` unchanged, and the planner finds the capability that produces it by the same string.

## 3. Versions and qualification

- `prm:hypothesis-engine` **3.0.0** (context `prediction_bindings`; "copy that entry's
  observable_ref, outcome_space_id and outcome_space_version exactly, together … An
  outcome_space_id is not an observable_ref. Never invent or infer an observable or an outcome
  space from the evidence …").
- Response contract **rc-2.0.0** (each prediction's three identifiers copied together from one
  entry of `CONTEXT.prediction_bindings`; never make up or derive an observable or a space).
- `probe-4.0.0`, suite **`hypothesis-conformance@2.0.0`**: the same two cases, each over declared
  bindings whose observable ids are neither their spaces' ids nor derivable from them
  (`bench.resistor_reading` → `os:probe.level`; `bench.channel_offset`, `bench.warmup_drift`,
  `fixture.edge_gradient`, `bench.repeat_spread` → the four multi-space spaces). A model that copies
  `os:…` into `observable_ref` fails the case. No "observable capability" score.
- `QUALIFICATION_DIGEST` moved from `9a34d824…` to **`5f82fb7a…`**; through the HARD-LOCKED
  semantics mechanism every existing lock is stale, its probe evidence cannot be locked again, and
  each model must be tested under the new contract.

## 4. Tests

| # | Proven | Where |
|---|---|---|
| 1 | the engine receives the domain's canonical bindings (and no bare space list) | `tests/unit/test_prediction_vocabulary.py` |
| 2 | a space id used as the observable (the smoke's exact failure) is refused | same; the qualification suite refuses it case by case; `tests/integration/test_prediction_vocabulary_postgres.py` (a stand-in that does it fails ROLE_HYPOTHESIS and cannot serve primary reasoning) |
| 3 | a valid observable with another space's id or version is refused | unit |
| 4 | an invented observable is refused | unit |
| 5 | a correct pair with an invalid outcome is refused | unit |
| 6 | valid bindings pass unchanged into Prediction | unit (parser and a real debate) |
| 7 | the planner matches an accepted prediction to `Capability.produces` with no normalisation; through the web with a model route, the contact-connectivity check REALLY runs (Job, Run, artifact), its Observation is admitted as evidence from that Run, RelationJudgments follow, and every belief move has its ALLOW decision | unit; `tests/e2e/test_web_prediction_vocabulary_postgres.py` |
| 8 | an observable only a simulation reads stays a valid prediction target | unit |
| 9 | the toy pack supplies its own vocabulary; generic cognition names no silicon-photonics observable | unit |
| 10 | a route qualified under the outcome-space-only contract is stale (readiness, `load_active_runtime`), its evidence cannot be locked again, and a re-test gives a new route; the deployed coder route `lk:963d70828be54b8e`, recomputed, is current only under the previous digest | integration; unit |
| 11 | earlier lock and probe rows byte-for-byte | integration |
| 12 | budget, deadline, transport, credentials, locality, redirect and egress | the whole suite |

The earlier slices' tests that built answers with free-text observables or read `outcome_spaces`
were updated to the vocabulary; their intent is unchanged.

Mutation battery: seven new entries (the parser's observable gate and its pairing check, the
engine's context, a prediction's observable on the way to the planner, the pack's declaration, the
registry's declared-space rule, the suite's observable ids) and five re-anchored (the multi-space
case at the floor and with one binding, the parser's space check, the prompt's and the contract's
binding rule).

## 5. Verification

Code: `a183917`. CI run `37484742432`: commit hygiene, spec conformance, lint/types/full suite and
the PostgreSQL backend profile, all green.

**Counts.** Every run collects **2524** tests; every skip is accounted for, and none failed.

| Run | Passed | Skipped | The skips |
|---|---|---|---|
| local, Windows: `pytest -q` | 1698 | 826 | 824 PostgreSQL-gated, 1 Lumerical, 1 network |
| CI, Linux: `pytest -q` | 1695 | 829 | the same 826 + the Windows Credential Manager test + 2 commit-range tests a shallow checkout cannot walk |
| local, fresh database (60 migrations): `LAB_BRAIN_TEST_POSTGRES=1 pytest -q` | 2522 | 2 | 1 Lumerical, 1 network |
| CI: the same | 2519 | 5 | 1 Lumerical, 1 network + the 3 environment skips |

| Check | Result |
|---|---|
| ruff check / ruff format / strict mypy | clean (237 source files) |
| `update_status.py --check` (also `--requirements-only`), obligation inventory, requirement coverage | current |
| evidence, debate and root-cause benchmark reports `--check` | current (the debate report regenerated for prompt 3.0.0: digests and token estimates only -- the cost ratio moved from x3.81 to x3.78 -- every verdict identical; the Lumi Agent benchmark was not run) |
| mutation battery, the vocabulary entries, the re-anchored ones and their neighbours (fresh database) | 15/15 killed |
| mutation battery, all entries (fresh database) | 401/401 killed, no anchor missing (60 min) |

## 6. Deployed, and re-qualified

`docker compose -p lab-brain-workspace up --build -d` from `a183917`, with
`LAB_BRAIN_INFERENCE_DEADLINE=1200` in the git-ignored `.env`; `local-models` changed nothing.

- *Every lock stale, automatically.* qwen2.5-coder:7b `lk:963d70828be54b8e`, qwen2.5:7b
  `lk:7a0fadf2440fff87` and an earlier stand-in's: "...made under qualification semantics no longer
  in force...". The applied `local-verification` was not ready on any slot and
  `load_active_runtime` refused it. Retired; both models unlocked; confirming the coder again at
  once was refused: "...were not run under the qualification semantics in force (probe-4.0.0
  5f82fb7a15f5; theirs: probe-3.0.0 9a34d824c9fd)".
- *qwen2.5-coder:7b under the final semantics (609 s):* CHAT, STRUCTURED_JSON, ROLE_QUERY,
  **ROLE_HYPOTHESIS (the binding suite at N=5, 230 s)**, ROLE_SPECIALIST, ROLE_CRITIQUE and CODE passed;
  VISION errored (no images). Locked: **`lk:de37c0ddb915b220`**.
- *qwen2.5:7b under the final semantics (511 s):* CHAT, STRUCTURED_JSON, ROLE_QUERY,
  **ROLE_HYPOTHESIS (217 s -- it failed the outcome-space-only suite twice with malformed JSON and
  passes the binding suite)**, ROLE_SPECIALIST and ROLE_CRITIQUE passed; CODE failed; VISION errored.
  Locked: **`lk:427cdea03b491e41`**.
- *The configuration* `local-vocabulary` (labels PUBLIC), the preferred routing, both models
  genuinely qualified: REASONING_PRIMARY and FAST_UTILITY -> qwen2.5-coder:7b, REASONING_ADVERSARIAL
  -> qwen2.5:7b. Ready, applied, loaded; the report says "The Adversarial Critic has its own model
  route".

## 7. The same blind verification smoke

Episode **`epi:ac49adeb...`** (`prj:smoke-local`, PRIVATE, LOCAL-only), one run of **1534 s**: the
synthetic `rs_anomaly_report.md` already in the project and the same `PS-501.device.json`
(`nominal_device` merged with `contact-open-via`'s `device`, no answer field; the stored artifact
`art:sha256:3741fc2d...` is byte-identical). No literature, no simulator, the benchmark unchanged.

**Model calls** (seven; each with an `LLM_CALL` span, ESTIMATED and ACTUAL BudgetGate entries, and
InferenceProvenance naming model, route, prompt id and version and EvidenceBundle hash; all
`ollama`, LOCAL): Evidence Researcher (coder, 28 s) -> **Hypothesis Engine (coder, prompt 3.0.0,
409 s)** -> two specialists (coder, 171 s and 132 s) -> the Critic's inverted retrieval (coder, 13 s)
-> **Adversarial Critic (qwen2.5:7b, its own route, 368 s)** -> the engine certifying the Critic's
alternative (coder, 407 s).

**Hypotheses -- parser ACCEPTED, every prediction over a declared canonical binding:**

| Hypothesis | observable_ref | OutcomeSpace | expects |
|---|---|---|---|
| PROCESS_DEPENDENT_CONTACT_RESISTANCE | `sp.probe_contact_resistance` | `os:sp.probe_contact_resistance@1.0.0` | ELEVATED |
| DEPLETION_CAPACITANCE_EFFECT | `sp.carrier_profile` | `os:sp.carrier_profile@1.0.0` | NOMINAL |
| MESH_ARTEFACT | `sp.mesh_stability` | `os:sp.mesh_stability@1.0.0` | UNSTABLE |
| NORMALIZATION_BASIS_ISSUE | `sp.normalization_basis` | `os:sp.normalization_basis@1.0.0` | DISAGREES |
| SMALL_SIGNAL_IMPEDANCE_EFFECT | `sp.small_signal_impedance` | `os:sp.rs_bias_response@1.0.0` | RS_BIAS_INSENSITIVE |

Each with relation SUPPORTS on that outcome only. One specialist favoured process-dependent contact
resistance, the other a numerical artefact. The Critic (primary bundle `bdl:9508064c...`, inverted
`bdl:5c30d6ea...`) raised three MISSING_CONTROL objections and named one alternative (a
small-signal-impedance effect); the engine's certification of it admitted nothing new.

**Verification -- the canonical path, executed:**

- Plan `vpl:e761e2f5...`: candidates `cap:sp.extraction_consistency`, `cap:sp.fourpoint_probe`,
  `cap:sp.fabricate_split_lot` -- each matched by its observable, each SUFFICIENT because one of its
  outcomes would move a rival (extraction: NORMALIZATION_BASIS_ISSUE -> SUPPORTED if DISAGREES;
  four-point: PROCESS_DEPENDENT_CONTACT_RESISTANCE -> SUPPORTED if ELEVATED). Chosen: the cheapest,
  `cap:sp.extraction_consistency` (ANALYTICAL_RULE_CHECK).
- **It really ran:** Job `job:4d898b4b...` / Run `run:4d898b4b...`, backend
  `sp.local.normalization_basis_reader`, input the device artifact, output artifact
  `art:sha256:049ad77f...` (durable, `cas://`). Observation `obs:9cae82b4...`:
  `sp.normalization_basis = AGREES`; admitted as attestation `att:5da04fcb...` (OBSERVED), tied to
  that Run and Observation. Its BudgetGate entries are on the ledger too (2 s estimated, 0 actual).
- Plan `vpl:fa760388...`: candidates four-point and split-lot; chosen `cap:sp.fourpoint_probe`
  (MEASUREMENT), which no pack can execute -- a person's act, listed as such. The simulations that
  would decide next (`cap:sp.charge_ac_sweep` for the impedance hypothesis, `cap:sp.mesh_sensitivity`)
  are listed BLOCKED: pending, not emulated; no simulation job exists in the project. The episode is
  `SUSPENDED` ("awaiting simulator for cap:sp.charge_ac_sweep"), its run PROVISIONAL.
- **Belief:** the observed AGREES is the outcome NORMALIZATION_BASIS_ISSUE's claim excludes, but the
  model declared no relation for it -- only SUPPORTS-if-DISAGREES. A relation is the prediction's
  declaration, never inferred from a mismatch, so no RelationJudgment, no TransitionPolicy decision
  and no BeliefRevisionEvent followed: the five rivals remain ACTIVE (their admissions under
  `tp:research.admission@1.0.0` are the only events), and no belief changed without an ALLOW
  decision. The pack's own catalog states both the supporting and the falsifying outcome for every
  mechanism (e.g. normalization: DISAGREES SUPPORTS, AGREES CONTRADICTS); the model's set did not.

**Blind comparison, after the run.** The evaluator truth for `contact-open-via` is
`contact_discontinuity`. The model's set holds no contact-discontinuity hypothesis and no
prediction over `sp.contact_connectivity`, so `cap:sp.inspect_contact_connectivity` -- the local check
that reads the cathode's missing via -- was never a candidate: a **LOCAL MODEL SCIENTIFIC-QUALITY
limitation**, the same as before. Separately, the pipeline was correct: canonical predictions, a
sufficient plan, a real deterministic check, admitted evidence, no simulation, every call budgeted,
provenanced and local.

**History is untouched.** Against a snapshot taken before the rebuild: 27 earlier
InferenceProvenance rows, 6 earlier episodes and their 7 runs, 88 probe rows and 7 lock rows,
byte-identical; ingestion items unchanged (3). The project has no egress policy.
