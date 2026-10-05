# Role qualification: what a lock demonstrated, and locks made under other rules

Date: 2026-10-05
Scope: an operational follow-up to the second LOCAL smoke (`epi:500ca3b7…`). **Not a milestone.**
No Requirement or Test ID was added and no milestone status changed. The research minimum is
unchanged (one competing hypothesis per catalogued mechanism; 5 for silicon photonics). Routing,
CognitiveRole/LogicalSlot contracts, budget, the inference deadline, egress, credentials, transport
locality and the redirect policy are unchanged. The Lumi Agent benchmark was not run.

## 1. What the smoke exposed

The Hypothesis Engine answered inside the deadline with two hypotheses and the typed parser refused
it: `expected at least 5 hypotheses, got 2`. The model had been locked as having proven
ROLE_HYPOTHESIS, and readiness had said READY.

- **P1-A, a prompt that contradicted its contract.** The Hypothesis Engine prompt (1.0.0) said "at
  least two"; its response contract and its context said `CONTEXT.minimum_hypotheses`, and this
  vertical passes 5. The model did what the prompt said.
- **P1-B, a capability without an amount.** The ROLE_HYPOTHESIS probe asked for at least 2 and
  recorded only PASSED. A lock said "ROLE_HYPOTHESIS", never "for how many", so a runtime whose
  research needs 5 was READY on evidence for 2.
- **P1-C, locks that outlived their rules.** A lock fingerprint named the probe payloads and
  contracts it was made under, but nothing checked it again: a lock made under an earlier probe or
  prompt stayed usable.

## 2. The prompt obeys the context (P1-A)

`prm:hypothesis-engine` **2.0.0**: "propose at least CONTEXT.minimum_hypotheses competing
mechanisms -- never fewer". The prompt names no number of its own; the context carries the
research's minimum, and the typed parser (`parse_hypothesis_engine(..., minimum=)`) stays the judge.
Every inference made after the change records 2.0.0 in InferenceProvenance; the earlier ones keep
1.0.0. Only the prompt's text and version changed (the debate benchmark report's per-case digests and
token estimates moved with it; every verdict is identical).

## 3. ROLE_HYPOTHESIS is qualified evidence (P1-B)

**The requirement is the research's.** `research.service.debate_minimum(vertical)` -- one competing
hypothesis per mechanism the vertical's DomainPack catalogues -- is what Stage A asks for, and the
same function gives the workspace the number its LLM settings and runtime are held to
(`ResearchEpisodeService.hypothesis_minimum()`, a read). The generic LLM runtime is **given** N
(`LLMSettings(hypothesis_minimum=)`, `load_active_runtime(..., hypothesis_minimum=)`, both
required where research runs) and imports no domain. Without research (`local_setup`) it uses the
generic floor, §7.4's 2: that is generic capability, not fitness for a domain.

**The probe demonstrates N and records it.** `probes.hypothesis_probe(N)` asks the model, over the
probe's own synthetic evidence (`att:probe-1` … `att:probe-5`, never a project's), for at least N
competing hypotheses, and judges the answer with the real parser at N. The result carries
`parameters = {"minimum_hypotheses": N}` -- on PASSED, FAILED and ERROR alike -- and `012l` stores it
on the probe row. Earlier rows carry none and so demonstrate no minimum. There is no score: the
record is "asked for N, and the parser accepted / refused it".

**A lock carries what it demonstrated.** `registry.qualification_of` takes, for each locked
capability, the parameters of the passing probe the lock counted; the lock fingerprint includes them.
Evidence for 2 and evidence for 5 are different routes (`lk:` differs).

**Fitness is checked where it matters.** `readiness.hypothesis_fit_problem`: a slot that needs
ROLE_HYPOTHESIS (REASONING_PRIMARY) is fit for research requiring N only if its lock demonstrated at
least N. N=5 serves 5, 3 and 2; N=2 does not serve 5; nothing serves more than it demonstrated.
Readiness reports it ("REASONING_PRIMARY: model qwen2.5:7b demonstrated ROLE_HYPOTHESIS for at least
2 competing hypotheses; this deployment's research requires 5"), activation needs readiness, and
`load_active_runtime` refuses the same route before a credential is read, so research never starts on
it.

**What the operator sees.** The model page lists ROLE_HYPOTHESIS as "(asked for at least 5
hypotheses)" beside its latest result and every row of its test history; the checklist says, in
both languages, which model on which use demonstrated how many and how many this deployment's
research needs, and that testing it again asks for that many. A use is not offered a model that
demonstrated too few for it (nor one whose lock is stale, §4): the configuration page lists it as
not eligible, with the reason. The generic capability (it can propose competing hypotheses) and the
domain's demand (this research needs 5) are two statements, never one number.

## 4. A lock made under other rules is stale (P1-C)

**The semantics are one digest.** `probes.QUALIFICATION_DIGEST` covers the probe version
(`probe-2.0.0`), every probe's payload and system text, the response contracts, and the role prompts
the runtime serves (id, version, text: Evidence Researcher, Hypothesis Engine, Adversarial Critic,
and the specialist probe's template). Changing any of them changes it.

**The fingerprint names them.** `lock_fingerprint(connection, model, capabilities, qualification)`
= endpoint, model, capabilities, what they demonstrated, and `QUALIFICATION_DIGEST`. It is still
recorded as `model_version` in every inference the route produces.

**Staleness is recomputed, never stored.** `SqlLLMRegistry.lock_problem(model)` recomputes the
fingerprint the lock would have NOW and compares it with the one it was given. A mismatch means the
lock was made under semantics no longer in force; readiness lists it (and does not weigh what such a
lock demonstrated), and `load_active_runtime` refuses it -- after the deadline check, before the fit
check and before any credential is read. The lock itself is not touched.

**History is kept.** `012l` adds `llm_model_locks`: every lock a model has had, recorded by trigger
when it is made (and every lock standing at migration, once), append-only. The model row keeps only
its current lock, as before. A stale lock stays exactly as it was until the operator re-qualifies:
retire the configuration that uses it, unlock, test (under the rules in force, at the research's N),
confirm, bind a new configuration, apply. That gives a new fingerprint; the old one stays in
`llm_model_locks` and in every InferenceProvenance row produced under it.

**The guide.** A stale lock is its own checklist step ("confirmed under earlier test rules … test
it again and confirm it again; the earlier confirmation stays on record"); when the APPLIED
configuration is unusable for a reason the guide knows (stale lock, too few hypotheses, too slow),
it says that reason as that step rather than as raw text.

## 5. Tests

| # | Proven | Where |
|---|---|---|
| 1 | the prompt asks for `CONTEXT.minimum_hypotheses`, names no count, version 2.0.0 | `tests/unit/test_llm_qualification.py` |
| 2 | evidence for 2: not ready, not activated, not loaded where research needs 5 | `tests/integration/test_role_qualification_postgres.py`; `tests/e2e/test_web_role_qualification_postgres.py` (web research 409) |
| 3 | evidence for 5 serves 5, 3 and 2 | integration |
| 4 | evidence for 5 does not serve 6 | integration |
| 5 | the requirement is `debate_minimum` of the vertical (5 for silicon photonics; 3 for a three-mechanism stand-in); the web probes at it; no domain import in `llm_runtime` | unit; e2e |
| 6 | a change of probe, prompt or contract makes an earlier lock stale | unit (digest sensitivity and composition); integration; e2e |
| 7 | a stale lock is refused by readiness and by `load_active_runtime`, and by web research before any model call | integration; e2e |
| 8 | neither the stale lock nor any InferenceProvenance is rewritten; `llm_model_locks` is append-only | integration; e2e |
| 9 | re-qualifying gives a new route fingerprint; later inferences name it, earlier ones keep theirs | integration; e2e |
| 10 | qwen2.5:7b tested under the corrected contract at N=5 | deployed, §6 |
| 11 | every budget, deadline, egress, locality, credential and redirect test | the whole suite |

Mutation battery: twenty-three new entries -- the prompt's count, the probe's N and its record,
the settings service's probe and readiness requirement, readiness and runtime fit and stale checks,
the fit comparison, the lock's qualification, the fingerprint's qualification and semantics, the
digest's prompts and contracts, the requirement's source, the workspace's two propagations, the
model page's stale note and demonstrated N, the guide's active-configuration step, and not offering
an unfit or stale model -- and three re-anchored.

## 6. Verification

Code: `3d38796`, and `f1cf598` -- found while re-qualifying the deployed model: the model page escaped
the capability label it appended N to, and a use's choices still offered a model readiness would
refuse (a stale lock, or too few hypotheses). CI runs `37275058700` and `37292461951`: commit
hygiene, spec conformance, lint/types/full suite and the PostgreSQL backend profile, all green.

**Counts.** Every run collects **2491** tests; every skip is accounted for, and none failed.

| Run | Passed | Skipped | The skips |
|---|---|---|---|
| local, Windows: `pytest -q` | 1677 | 814 | 812 PostgreSQL-gated, 1 Lumerical, 1 network |
| CI, Linux: `pytest -q` | 1674 | 817 | the same 814 + the Windows Credential Manager test + 2 commit-range tests a shallow checkout cannot walk |
| local, fresh database (59 migrations): `LAB_BRAIN_TEST_POSTGRES=1 pytest -q` | 2489 | 2 | 1 Lumerical, 1 network |
| CI: the same | 2486 | 5 | 1 Lumerical, 1 network + the 3 environment skips |

The bare run before `update_status.py` regenerated the file for `012l` had the two status-freshness
failures (1675 passed, 2 failed, 814 skipped); the counts above were taken after.

| Check | Result |
|---|---|
| ruff check / ruff format / strict mypy | clean (237 source files) |
| `update_status.py --check` (also `--requirements-only`), obligation inventory, requirement coverage | current |
| evidence, debate and root-cause benchmark reports `--check` | current (the debate report regenerated for prompt 2.0.0: digests and token estimates only; the Lumi Agent benchmark was not run) |
| mutation battery, the twenty new entries and the three re-anchored (fresh database) | 23/23 killed |
| mutation battery, all entries at `3d38796` (fresh database) | 371/371 killed -- 297, then the remaining 74 after a Windows file lock (WinError 1224) stopped the battery while it restored `service.py`; the backup was byte-identical to HEAD and was put back, no test result was involved |
| mutation battery, the three entries added by `f1cf598` | 3/3 killed |
| mutation battery, all entries at `f1cf598` (fresh database) | 374/374 killed, no anchor missing (55 min) |

## 7. Deployed

`docker compose -p lab-brain-workspace up --build -d` from `3d38796`, then from `f1cf598`, with
`LAB_BRAIN_INFERENCE_DEADLINE=1200` in the git-ignored `.env`; `init` applied `012l` (59
migrations) and `llm_model_locks` received the three locks standing then.

- *The old locks are stale.* Under the semantics in force, every lock made before is refused:
  qwen2.5:7b `lk:0de60d9b48831245`, qwen2.5-coder:7b `lk:c6f35bd72fe86213`, and an earlier
  transport stand-in's on a DISABLED connection. Readiness of the ACTIVE `local-first` listed
  REASONING_PRIMARY, FAST_UTILITY and REASONING_ADVERSARIAL as "…was made under qualification
  semantics no longer in force…"; `load_active_runtime` refused it before reading any credential;
  the settings page named the step ("“qwen2.5:7b”, assigned to Fast processing, was confirmed under
  earlier test rules"), and the model page said the confirmation predates the rules in force. No
  research was started on it.
- *Re-qualified by the operator's steps, through the pages.* `local-first` retired; qwen2.5:7b
  unlocked and tested under `probe-2.0.0` with the 1200 s deadline: CHAT 22.8 s, STRUCTURED_JSON
  4.6 s, ROLE_QUERY 14.0 s, **ROLE_HYPOTHESIS passed at `{"minimum_hypotheses": 5}` in 171.1 s**
  (the real parser at 5), ROLE_SPECIALIST 30.5 s, ROLE_CRITIQUE 57.7 s; CODE failed (the reply is not
  Python), VISION errored (the model takes no images) -- as before. It genuinely passed, so it was
  locked again: **`lk:09d58ebac3b9b558`**, the same six capabilities. `llm_model_locks` holds both
  (`lk:0de60d9b48831245` 2026-09-28, `lk:09d58ebac3b9b558` 2026-10-05). qwen2.5-coder:7b was not
  needed and was not tested; its lock stays stale and unbound. The minimum stayed 5.
- *A new configuration.* `local-qualified` (labels PUBLIC), the three reasoning uses on qwen2.5:7b
  as approved for the first LOCAL smoke (PRIVATE_LOCAL and CODE unbound): ready, applied, loaded. The
  second rebuild's `local-models` changed nothing (a runtime was ACTIVE).
- *A new smoke episode* (`epi:a9cd60f1…`, `prj:smoke-local`, PRIVATE, LOCAL-only, the synthetic
  `rs_anomaly_report.md` selected as existing research data -- not uploaded again; 19 statements
  admitted): the Evidence Researcher answered, then the Hypothesis Engine (prompt **2.0.0**, route
  `lk:09d58ebac3b9b558`) answered inside the deadline with **five** competing hypotheses -- the
  count is met -- and the typed parser refused the answer on another rule: `hypothesis 'h4' predicts
  over outcome space os:sp.cj_per_mm@1.0.0, which the engine was not shown; a prediction may only be
  bound to a declared space` (VER-004). The vertical declares six outcome spaces and none is
  `os:sp.cj_per_mm`: the model invented one. The episode is `SUSPENDED / NOT_REACHED` with that
  reason (no hypothesis set), resumable; run 1 took 326 s. Both calls are in InferenceProvenance with
  the new route (the refused output kept), all `ollama`, LOCAL; the project has no egress policy. The
  report says the requirement ("asked for at least 5 … demonstrated at least that many, under the
  qualification semantics in force") and that REASONING_ADVERSARIAL is NOT an independent model
  route.
- *History is untouched.* Against a snapshot taken before the rebuild: the 11 earlier
  InferenceProvenance rows (route `lk:0de60d9b48831245`, prompt 1.0.0), the three earlier episodes
  (`epi:226036fa…` COMPLETED, `epi:500ca3b7…` and `epi:4d4c9488…` SUSPENDED), their 4 runs and the 48
  probe rows made under `probe-1.0.0` are byte-identical; ingestion items are unchanged (3).

**What the deployment still lacks.** The smoke now passes the count and stops on binding discipline:
qwen2.5:7b bound one prediction to an outcome space it was not given. Its probe declares one outcome
space, the vertical six, so the probe did not exercise that discipline at the vertical's breadth.
Nothing was relaxed: the parser stays the judge, the minimum stays 5.
