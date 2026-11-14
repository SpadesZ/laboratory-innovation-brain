# Probe evidence names its qualification semantics, and a full LOCAL verification smoke

Date: 2026-10-06
Scope: a P1 found in review of the conformance-suite slice, and the first LOCAL smoke through the
verification and belief path. **Not a milestone.** No Requirement or Test ID was added and no
milestone status changed. The qualification architecture, the suite, the prompts, the contracts, the
parser, the research minimum (5), VER-004, routing, budget, the deadline, egress, credentials,
transport locality and the redirect policy are unchanged. The Lumi Agent benchmark was not run.

## 1. The P1: evidence laundered across semantics

A lock's fingerprint names the qualification semantics in force when it is made
(`QUALIFICATION_DIGEST`: probe payloads, role prompts, response contracts), and a lock made under
other semantics is stale. But `lock()` decided which probe rows it could count by `probe_version`
alone, and a probe row did not record the semantics it ran under. So:

1. probes run under version V and semantics D1;
2. a prompt, a response contract or a probe payload changes -- D2 -- and nobody bumps V;
3. the existing lock is (correctly) stale; the operator unlocks the model;
4. `lock()` sees V == V and counts the D1 rows, and computes a fingerprint under D2 -- a lock that
   passes as current, on evidence from semantics no longer in force, without a test.

The guard depended on a developer remembering a version bump.

## 2. The fix

- **Each probe records the semantics it ran under.** `012m` adds
  `llm_capability_probes.qualification_digest` (64 hex characters, or NULL); the registry writes the
  digest in force with every probe. No row is rewritten: rows written before carry NULL, and the
  table stays append-only (`012e`'s guard is unchanged).
- **A lock counts only probes whose recorded digest is the one in force** (`registry.lock`). Any
  other digest -- or none -- is refused before anything is written: `lock.outdated_tests`, "model
  X's latest tests of … were not run under the qualification semantics in force (probe-3.0.0
  9a34d824c9fd; theirs: …); test it again before confirming it". The probe version is no longer
  what decides; it is part of the digest.
- **A lock already made on unproven evidence is refused at use** (`registry.lock_problem`): after the
  fingerprint check, every locked capability's counted probe must carry the digest in force.
  Readiness lists it, `load_active_runtime` refuses it before research or any credential, and the
  guide says it as the stale-lock step ("…counts tests (…) whose qualification semantics were not
  recorded or are no longer in force; test it again and confirm it again"). Every lock made before
  `012m` therefore needs one re-test -- the fail-closed reading of "semantics that cannot be proven".
- The semantics are still the same digest; it is now built by `probes.qualification_inputs()` (and
  `contracts.contract_digest`) so that a test can change one part of it with the version unchanged.
  `QUALIFICATION_DIGEST` did not change value (`9a34d824…`).

## 3. Tests

| Proven | Where |
|---|---|
| a prompt-text change alone (probe version unchanged) makes the lock stale and its evidence unusable: unlock → immediate re-lock refused; after a test under the digest in force a new lock succeeds, under a new fingerprint | `tests/integration/test_probe_semantics_postgres.py` |
| the same for a response-contract change alone (`contract_digest`, contract version unchanged) | same |
| the same for a probe-payload change alone | same |
| probe rows that recorded no semantics qualify nothing; a lock already made on them is refused by readiness and by `load_active_runtime` | same |
| earlier probe and lock rows byte-for-byte after re-qualification; every probe records the digest it ran under | same; `tests/e2e/test_web_hypothesis_conformance_postgres.py` (web: research refused before any model call, the re-lock refusal in zh-TW, InferenceProvenance, lock and probe rows as `t::text` -- with only the digest changed) |
| the guide says a lock on unproven evidence as the stale-lock step | `tests/unit/test_web_llm_guide.py` |

Mutation battery: three new entries (a probe recorded without semantics, a lock on unproven evidence
trusted at use, the guide's pattern) and two re-anchored (the lock's check, now on the digest; the
suite version in the digest).

## 4. Verification

Code: `206910f`. CI run `37414840731`: commit hygiene, spec conformance, lint/types/full suite and
the PostgreSQL backend profile, all green.

**Counts.** Every run collects **2508** tests; every skip is accounted for, and none failed.

| Run | Passed | Skipped | The skips |
|---|---|---|---|
| local, Windows: `pytest -q` | 1685 | 823 | 821 PostgreSQL-gated, 1 Lumerical, 1 network |
| CI, Linux: `pytest -q` | 1682 | 826 | the same 823 + the Windows Credential Manager test + 2 commit-range tests a shallow checkout cannot walk |
| local, fresh database (60 migrations): `LAB_BRAIN_TEST_POSTGRES=1 pytest -q` | 2506 | 2 | 1 Lumerical, 1 network |
| CI: the same | 2503 | 5 | 1 Lumerical, 1 network + the 3 environment skips |

The bare run before `update_status.py` regenerated the file for `012m` had the two status-freshness
failures (1683 passed, 2 failed, 823 skipped); the counts above were taken after.

| Check | Result |
|---|---|
| ruff check / ruff format / strict mypy | clean (237 source files) |
| `update_status.py --check` (also `--requirements-only`), obligation inventory, requirement coverage | current |
| evidence, debate and root-cause benchmark reports `--check` | current (the Lumi Agent benchmark was not run) |
| mutation battery, the semantics entries and their neighbours (fresh database) | 11/11 killed |
| mutation battery, all entries (fresh database) | 394/394 killed, no anchor missing (64 min) |

## 5. Deployed, and re-qualified

`docker compose -p lab-brain-workspace up --build -d` from `206910f`, with
`LAB_BRAIN_INFERENCE_DEADLINE=1200` in the git-ignored `.env`; `init` applied `012m` (60 migrations).

- *Unproven evidence is refused.* The coder's lock `lk:963d70828be54b8e` -- made the day before on
  `probe-3.0.0` rows that recorded no semantics -- was refused by readiness and by
  `load_active_runtime` ("...counts tests (CHAT, CODE, ROLE_CRITIQUE, ROLE_HYPOTHESIS, ROLE_QUERY,
  ROLE_SPECIALIST, STRUCTURED_JSON) whose qualification semantics were not recorded..."). On start,
  `local-models` tried to lock the TESTED qwen2.5:7b and was refused for the same reason; the rest
  of the setup went on.
- *The P1, closed, live.* `local-conformance` retired, the coder unlocked and confirmed again at
  once: 409 `lock.outdated_tests` -- "...were not run under the qualification semantics in force
  (probe-3.0.0 9a34d824c9fd; theirs: probe-3.0.0, semantics not recorded)". The probe version was the
  SAME as the one in force; the version-only check would have let it through. No lock row was added.
- *qwen2.5-coder:7b, tested again (616 s):* every probe recorded `9a34d824c9fd`. CHAT, STRUCTURED_JSON,
  ROLE_QUERY, **ROLE_HYPOTHESIS (the suite at N=5, 240 s)**, ROLE_SPECIALIST, ROLE_CRITIQUE and CODE
  passed; VISION errored (the model takes no images). Locked again: `lk:963d70828be54b8e` -- the same
  route fingerprint, because the route (endpoint, model, capabilities, N, semantics) is the same;
  `llm_model_locks` records both lock events.
- *qwen2.5:7b, tested under the same semantics (438 s):* CHAT, STRUCTURED_JSON, ROLE_QUERY,
  ROLE_SPECIALIST and **ROLE_CRITIQUE passed**; ROLE_HYPOTHESIS failed again, identically
  (`multi-space: ... the output is not JSON (Expecting ',' delimiter: line 1 column 2397 (char
  2396))`); CODE failed; VISION errored. A failed ROLE_HYPOTHESIS does not disqualify what it passed:
  locked as **`lk:7a0fadf2440fff87`** with exactly CHAT, ROLE_CRITIQUE, ROLE_QUERY, ROLE_SPECIALIST,
  STRUCTURED_JSON -- eligible for REASONING_ADVERSARIAL (CHAT, STRUCTURED_JSON, ROLE_CRITIQUE), not
  for REASONING_PRIMARY.
- *The configuration* `local-verification` (labels PUBLIC): REASONING_PRIMARY and FAST_UTILITY ->
  qwen2.5-coder:7b (`lk:963d70828be54b8e`), **REASONING_ADVERSARIAL -> qwen2.5:7b
  (`lk:7a0fadf2440fff87`)**: ready, applied, loaded. The report says "The Adversarial Critic has its
  own model route: qwen2.5:7b on REASONING_ADVERSARIAL, distinct from REASONING_PRIMARY."

## 6. The full LOCAL verification smoke

Episode **`epi:cf079785...`** (`prj:smoke-local`, PRIVATE, LOCAL-only), one run of **1537 s**.
Inputs: the synthetic `rs_anomaly_report.md` already in the project (19 statements admitted, not
uploaded again) and, as the verification input, `PS-501.device.json` -- the benchmark's
`nominal_device` merged with case `contact-open-via`'s `device`, exactly as the test helper builds
it. The file carries no `truth`, `expected`, note or answer field; the stored verification artifact
(`art:sha256:3741fc2d...`) is byte-identical to it; the report reads "device PS-501, drawn length
500 um, 2 contacts". No literature, no simulator.

- **Model calls** (seven; each with an `LLM_CALL` span, an ESTIMATED and an ACTUAL BudgetGate entry,
  and InferenceProvenance naming the model, route, prompt id and version and the EvidenceBundle hash;
  all `ollama`, LOCAL): Evidence Researcher (coder, 40 s) -> **Hypothesis Engine** (coder, prompt
  2.1.0, 441 s) -> two domain specialists (coder, 159 s and 186 s) -> the Critic's inverted retrieval
  (coder, 16 s) -> **Adversarial Critic (qwen2.5:7b, its own route, 360 s)** -> the Hypothesis Engine
  certifying the Critic's alternatives (coder, 329 s).
- **Hypotheses -- parser ACCEPTED:** five, every prediction over a declared space with an outcome it
  admits: PROCESS_DEPENDENT_CONTACT_RESISTANCE -> `os:sp.probe_contact_resistance` ELEVATED;
  DEPLETION_EFFECT -> `os:sp.carrier_profile` NOMINAL; MESH_ARTEFACT -> `os:sp.mesh_stability`
  UNSTABLE; NORMALIZATION_BASIS_ISSUE -> `os:sp.normalization_basis` DISAGREES; RS_BIAS_INSENSITIVE
  -> `os:sp.rs_bias_response` RS_BIAS_INSENSITIVE. The engine favoured process-dependent contact
  resistance; one specialist agreed, the other suggested a numerical artefact.
- **Critic:** ran over the primary bundle and an inverted one (`bdl:69991180...`); five
  MISSING_CONTROL objections, alternatives NUMERICAL_ARTIFACT, PROCESS_VARIABILITY, SIMULATION_ERROR;
  trigger BUNDLES_MATERIALLY_CONFLICT. The engine's certification of them was accepted by the parser
  and admitted nothing new; the debate stopped STABLE after one round.
- **Verification:** one plan (`vpl:04b53e6b...`) with **no candidate action** ->
  `NO_SUFFICIENT_ACTION`; no Job, no Run, no Observation, no output artifact; no simulation job
  anywhere in the project. Belief: only the five admissions (none -> ACTIVE under
  `tp:research.admission@1.0.0`); no belief move, so no RelationJudgment or transition was needed,
  and none was made without an ALLOW decision. Failure analysis INCONCLUSIVE; the episode is
  `COMPLETED / INCONCLUSIVE:NO_SUFFICIENT_ACTION`, the run's result PROVISIONAL.

**Why no action was a candidate -- a typed-contract gap, stopped and reported, not fixed.** The
planner takes candidates from the predictions' `observable_ref` values, matched exactly against what
each capability produces (`sp.contact_connectivity`, `sp.normalization_basis`, ...). The Hypothesis
Engine's contract gives `observable_ref` as free text ("what is observed"), its context declares
outcome spaces but no observables, and the parser does not check it. The model wrote each space id
as the observable (`os:sp.normalization_basis`), so nothing matched -- not even the local,
deterministic normalization check that could adjudicate NORMALIZATION_BASIS_ISSUE. The report then
says "No further check available here would change a decision", which is not what happened. No
prompt rule, planner, parser, catalog or benchmark was changed.

**Blind comparison, after the run.** The benchmark's evaluator truth for `contact-open-via` is
`contact_discontinuity` (its expected stop CONFIRMED). The model's set holds no contact-discontinuity
hypothesis and no prediction over `os:sp.contact_connectivity`, so even with observables that
matched, the contact-connectivity reader would not have been planned to adjudicate the true cause: a
**model scientific-quality limitation** of qwen2.5-coder:7b here. The run did not reach the true
cause, and does not claim to.

**History is untouched.** Against a snapshot taken before the rebuild: the 20 earlier
InferenceProvenance rows, the 5 earlier episodes and their 6 runs, the 72 probe rows written before
`012m` (on their original columns) and the 5 earlier lock rows are byte-identical; ingestion items
are unchanged (3). The project has no egress policy; every call is LOCAL.
