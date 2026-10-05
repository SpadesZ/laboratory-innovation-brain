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
