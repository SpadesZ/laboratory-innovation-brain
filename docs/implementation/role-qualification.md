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
