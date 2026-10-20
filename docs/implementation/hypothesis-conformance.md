# ROLE_HYPOTHESIS as a conformance suite

Date: 2026-10-06
Scope: an operational follow-up to the third LOCAL smoke (`epi:a9cd60f1…`). **Not a milestone.**
No Requirement or Test ID was added and no milestone status changed. The research minimum (5 for
silicon photonics), VER-004 and the typed parser are unchanged. Routing, budget, the inference
deadline, egress, credentials, transport locality and the redirect policy are unchanged. The Lumi
Agent benchmark was not run.

## 1. What the smoke exposed

qwen2.5:7b passed ROLE_HYPOTHESIS at N=5 and was locked. In real research the Hypothesis Engine
produced the five hypotheses asked for and bound one prediction to `os:sp.cj_per_mm` -- a space it
named itself from the evidence's Cj figures, not one of the six the vertical declares. VER-004
refused it, as it should.

The parser was right. The false assurance was in qualification: the probe gave the model ONE
synthetic outcome space, so it never asked the model to choose among several while the evidence
named other quantities. A one-space pass was treated as evidence for the richer real context.

## 2. The suite

`probes.HYPOTHESIS_SUITE = "hypothesis-conformance@1.0.0"`, run under `probe-3.0.0`. ROLE_HYPOTHESIS
passes only if every case passes the real `parse_hypothesis_engine` at the same N -- the research's
(`debate_minimum`), as before:

| Case | Context | What a pass shows |
|---|---|---|
| `contextual-minimum` | the existing single-space certificate case (`os:probe.level`) | at least N distinct certificates, in the contract's shape |
| `multi-space` | a second synthetic bench: four declared spaces -- `os:probe.bench_level`, `os:probe.warmup_trend` (at **2.0.0**), `os:probe.plate_position`, `os:probe.repeatability` -- over six synthetic observations, one of which names the noise floor per hertz ("logged as noise_per_hz") and the room humidity, neither of them a declared space (`TEMPTING_QUANTITIES`) | at least N certificates, every prediction bound to a declared `(outcome_space_id, outcome_space_version)` pair and expecting an outcome that space admits |

- **The judge is the parser.** It already refused both kinds of error -- a space the engine was not
  shown (VER-004) and an outcome the chosen space does not admit; the suite now exercises both
  where they can actually occur. Using every declared space is not required: the runtime contract
  does not require it, and the suite tests adherence to the contract, not a stronger rule.
- **Nothing of a domain or project.** The cases carry no silicon-photonics identifier, space,
  mechanism or fixture text; their attestations are `att:probe-*`. A test reads the pack's
  identifiers and the smoke fixture and proves none appears.
- **No scalar.** There is no "number of spaces" capability: cardinality is not established as a
  monotonic model capability. The suite is fixed and versioned; a pass is a pass of every case.
- **What is recorded.** The probe row's `parameters` (`012l`, unchanged) say
  `{"minimum_hypotheses": N, "suite": "hypothesis-conformance@1.0.0", "cases": ["contextual-minimum",
  "multi-space"]}`; a failure's detail starts with the case that failed (for example
  `multi-space: the typed role parser refused it: … os:probe.noise_per_hz@1.0.0, which the engine
  was not shown …`); the latency is the slowest call's (each call must fit the deadline); the
  digest covers every reply. The cases run in order and the first failure decides. The model page
  shows "(asked for at least 5 hypotheses) -- conformance suite hypothesis-conformance@1.0.0".

## 3. The prompt and the contract say the rule

- `prm:hypothesis-engine` **2.1.0**: "Bind every prediction to an outcome space in
  CONTEXT.outcome_spaces: copy its outcome_space_id and outcome_space_version exactly, as the pair
  given there, and its expected_outcome verbatim from that same space's outcomes. Never invent or
  infer an outcome space from the evidence, even when the evidence names a quantity that sounds
  like an observable."
- Response contract **rc-1.1.0** (Hypothesis Engine): the same rule, and "if no given space fits a
  prediction, make a different prediction that one does" -- never a forced binding to a space that
  does not describe it.
- The parser is unchanged and authoritative. The debate benchmark report was regenerated for the
  longer prompt: digests and token estimates only; every verdict is identical.

## 4. Locks: the existing stale-lock mechanism does the work

- `QUALIFICATION_DIGEST` now covers the suite's version and every case's payload (taken at the
  generic floor), with the prompt and contract as before. Every lock made under the single-space
  probe is stale: readiness lists it, `load_active_runtime` refuses it before research or any
  credential, and the lock row is left as it was. No exception was added for any model.
- **A shortcut closed.** A lock's fingerprint is computed under the semantics in force when it is
  made, and `lock()` locked whatever the latest probe rows proved. So a stale model could be
  unlocked and locked again WITHOUT testing, and its new lock -- computed now, on probe rows from the
  single-space probe that still say `minimum_hypotheses: 5` -- would pass as current and fit. That
  is the stale-lock invariant ("the operator must re-test and re-lock") violated, reproducibly. The
  registry now refuses a lock whose counted probes ran under an earlier `PROBE_VERSION`
  (`lock.outdated_tests`; the page says, in both languages, to run the capability test again).
  `local_setup` says such a model and leaves it TESTED; it never re-tests on its own.
- Re-testing under the suite and locking gives a new route fingerprint; `llm_model_locks` and every
  InferenceProvenance row stay byte-for-byte as they were.

## 5. Tests

| # | Proven | Where |
|---|---|---|
| 1 | the single-space qualification is no longer current: its digest is not the one in force, and the route the deployment locked under it (`lk:09d58ebac3b9b558`, recomputed from its public parts) is that route only under the old digest | `tests/unit/test_hypothesis_conformance.py`; `tests/integration/test_hypothesis_conformance_postgres.py` |
| 2 | the multi-space case passes only declared pairs (the 2.0.0 space at 2.0.0) and legal outcomes; one space used is enough | unit |
| 3 | an invented space made from a tempting quantity (`os:probe.noise_per_hz`, `os:probe.humidity`) is FAILED, named as the multi-space case | unit; integration and e2e (the stand-in's `invent_space`): not locked for ROLE_HYPOTHESIS, not offered for primary reasoning, binding refused |
| 4 | a declared space with an outcome it does not admit is FAILED | unit |
| 5 | the multi-space case carries no silicon-photonics identifier, space, mechanism or fixture text | unit |
| 6 | N is enforced by each case on its own (four certificates fail at five, in either case; four pass at four) | unit |
| 7 | the suite's version and cases, the prompt and the contract are in the digest; changing any changes it | unit (`test_hypothesis_conformance.py`, `test_llm_qualification.py`) |
| 8 | a stale route is refused by readiness and by `load_active_runtime`; re-locking without re-testing is refused | integration; e2e (web research 409 before any model call; the refusal in zh-TW) |
| 9 | lock history and earlier InferenceProvenance are byte-for-byte as they were after re-qualification | integration (`llm_model_locks`, probe rows); e2e (`inference_provenance`, `llm_model_locks`, as `t::text`) |
| 10 | every budget, deadline, transport, locality, credential, redirect and egress test | the whole suite |

Mutation battery: seventeen new entries -- the multi-space case dropped, a failed case passed, the
case at the floor, one space declared, nothing tempting in the evidence, the suite not recorded, the
first latency recorded, the case and the suite version left out of the semantics, the parser
admitting an undeclared space or outcome, the prompt and the contract without the rule, a lock on
outdated tests, the refusal without its code, `local_setup` stopping on it, the model page without
the suite -- and three re-anchored (the probe's N, its record, the page's N).

## 6. Verification

Code: `5b642e5`. CI run `37352038662`: commit hygiene, spec conformance, lint/types/full suite and
the PostgreSQL backend profile, all green.

**Counts.** Every run collects **2504** tests; every skip is accounted for, and none failed.

| Run | Passed | Skipped | The skips |
|---|---|---|---|
| local, Windows: `pytest -q` | 1685 | 819 | 817 PostgreSQL-gated, 1 Lumerical, 1 network |
| CI, Linux: `pytest -q` | 1682 | 822 | the same 819 + the Windows Credential Manager test + 2 commit-range tests a shallow checkout cannot walk |
| local, fresh database (59 migrations): `LAB_BRAIN_TEST_POSTGRES=1 pytest -q` | 2502 | 2 | 1 Lumerical, 1 network |
| CI: the same | 2499 | 5 | 1 Lumerical, 1 network + the 3 environment skips |

| Check | Result |
|---|---|
| ruff check / ruff format / strict mypy | clean (237 source files) |
| `update_status.py --check` (also `--requirements-only`), obligation inventory, requirement coverage | current |
| evidence, debate and root-cause benchmark reports `--check` | current (the debate report regenerated for prompt 2.1.0: digests and token estimates only -- the token-cost ratio moved from x4.16 to x3.81 -- every verdict identical; the Lumi Agent benchmark was not run) |
| mutation battery, the seventeen new entries and the three re-anchored (fresh database) | 20/20 killed |
| mutation battery, all entries (fresh database) | 391/391 killed, no anchor missing (54 min) |

## 7. Deployed

`docker compose -p lab-brain-workspace up --build -d` from `5b642e5`, with
`LAB_BRAIN_INFERENCE_DEADLINE=1200` in the git-ignored `.env` (`web` runs with
`--inference-deadline 1200`); `local-models` changed nothing (a runtime was ACTIVE).

- *The single-space routes are stale.* qwen2.5:7b `lk:09d58ebac3b9b558` (locked under the
  single-space probe), qwen2.5-coder:7b `lk:c6f35bd72fe86213` and an earlier stand-in's: readiness of
  the ACTIVE `local-qualified` listed all three reasoning uses as "…made under qualification semantics
  no longer in force…", and `load_active_runtime` refused it before any credential. No research was
  started on it.
- *No shortcut.* With `local-qualified` retired and qwen2.5:7b unlocked, confirming it without a
  test was refused: 409, `lock.outdated_tests`, "…ran under probe-2.0.0, not the tests in force
  (probe-3.0.0); test it again before confirming it". It stayed TESTED; no lock row was added.
- *qwen2.5:7b, the suite at N=5 (463 s): FAILED.* CHAT 19.8 s, STRUCTURED_JSON 5.2 s, ROLE_QUERY
  11.4 s, ROLE_SPECIALIST 30.4 s, ROLE_CRITIQUE 57.2 s passed; CODE failed and VISION errored, as
  before. **ROLE_HYPOTHESIS FAILED** (205.9 s): `contextual-minimum` passed; in `multi-space` the reply
  was not JSON -- `multi-space: the typed role parser refused it: HYPOTHESIS_ENGINE: the output is not
  JSON (Expecting ',' delimiter: line 1 column 2397 (char 2396))`. The probe was not changed; the model
  was not locked again and stays TESTED.
- *qwen2.5-coder:7b, the same suite at N=5 (657 s): PASSED.* CHAT 24.3 s, STRUCTURED_JSON 4.9 s,
  ROLE_QUERY 15.3 s, **ROLE_HYPOTHESIS 253.9 s, both cases** (`{"minimum_hypotheses": 5, "suite":
  "hypothesis-conformance@1.0.0", "cases": ["contextual-minimum", "multi-space"]}`), ROLE_SPECIALIST
  45.6 s, ROLE_CRITIQUE 71.1 s, CODE 3.4 s; VISION errored (the model takes no images). Locked:
  **`lk:963d70828be54b8e`** (seven capabilities). `llm_model_locks` keeps `lk:c6f35bd72fe86213` beside
  it, and both of qwen2.5:7b's.
- *A new configuration.* `local-qualified` was retired; `local-conformance` (labels PUBLIC) binds
  REASONING_PRIMARY, FAST_UTILITY and REASONING_ADVERSARIAL to qwen2.5-coder:7b -- the only current
  eligible local model (PRIVATE_LOCAL and CODE unbound): ready, applied, loaded. The report says
  REASONING_ADVERSARIAL is the same locked model, "NOT an independent model route".
- *A new smoke episode* (`epi:2c4ef02a…`, `prj:smoke-local`, PRIVATE, LOCAL-only, the synthetic
  `rs_anomaly_report.md` selected as existing research data -- not uploaded again; 19 statements
  admitted; run 1 took 1315 s). Seven calls, all `ollama` on `lk:963d70828be54b8e`: Evidence
  Researcher; **Hypothesis Engine (prompt 2.1.0) -- parser ACCEPTED: five certificates, every
  prediction over a declared space with an outcome it admits** (`DEPLETION_EFFECT` and
  `PROCESS_DEPENDENT_CONTACT_RESISTANCE` → `os:sp.rs_bias_response@1.0.0` RS_BIAS_INSENSITIVE,
  `CONTACT_RESISTANCE` → `os:sp.probe_contact_resistance@1.0.0` ELEVATED, `MESH_ARTEFACT` →
  `os:sp.mesh_stability@1.0.0` UNSTABLE, `NORMALIZATION_BASIS` → `os:sp.normalization_basis@1.0.0`
  DISAGREES), and the set was admitted; the two domain specialists; the Critic's inverted retrieval;
  the Adversarial Critic; and the Hypothesis Engine again, asked to certify the Critic's alternatives
  (minimum 1) -- parser ACCEPTED: two certificates over declared spaces, both mechanisms already in the
  set, so none was admitted and the debate stopped STABLE after one round. Stages: hypotheses DONE
  ("5 competing hypotheses admitted after 1 debate round(s) and an independent critique");
  verification SKIPPED (no verification input was given). The episode is `COMPLETED / NOT_REACHED`:
  it reasoned past the hypothesis stage and stopped where this smoke gives it nothing to verify.
- *History is untouched.* Against a snapshot taken before the rebuild: the 13 earlier
  InferenceProvenance rows, the 4 earlier episodes and their 5 runs, the 56 probe rows made under
  earlier probes and the 4 lock rows are byte-identical; ingestion items are unchanged (3). The
  project has no egress policy; every call is LOCAL.

**What the deployment still lacks.** One qualified local model serves every reasoning use, so the
critique is not model-route independent; qwen2.5:7b does not qualify (it broke the JSON contract in
the multi-space case). This smoke supplies no verification input and no simulator is connected, so
nothing was verified. The scientific quality of the hypotheses was not assessed here.
