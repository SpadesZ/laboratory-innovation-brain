# One falsifier authority: the designated typed falsifier

Date: 2026-10-08
Scope: the P1 the blind LOCAL smoke `epi:04d7d46b...` exposed in falsifier CONSUMPTION. **Not a
milestone.** No Requirement or Test ID was added and no milestone status changed. Typed-falsifier
storage and admission (`012n`), the exact outcome -> RelationJudgment rule, forecast disagreement,
TransitionPolicy, qualification, BudgetGate, routing, transport, locality, credentials and egress
are unchanged. The Lumi Agent benchmark was not run.

## 1. The P1

The smoke admitted a certificate whose prose falsifier read "The normalization basis agrees between
splits A and B." while its designated typed falsifier was `sp.normalization_basis = DISAGREES ->
CONTRADICTS`. Verification adjudicated the typed one. But the debate fed the prose to the two
cognitive paths that reason about falsifiers:

- `StructuredDebate._inverted_retrieval` -- `falsifiers = [c.hypothesis.falsifier for c in
  in_contention]`, shown to the Evidence Researcher's rewrite (`CONTEXT.falsifiers`) and joined
  into the inverted query text;
- `StructuredDebate._cross_examine` -- each hypothesis shown to the Adversarial Critic with
  `"falsifier": c.hypothesis.falsifier`.

So the Critic could search for, and argue from, one falsifier while verification and belief used
the opposite one. Not solved by judging whether prose and designation agree -- no model, embedding,
string similarity, keyword rule, outcome inversion or domain heuristic decides that -- and no
historical row is rewritten.

## 2. The design

**The designation is the only machine authority.** `HypothesisCertificate.falsifier_predictions`
returns the designated typed predictions in prediction-id order (the order
`falsifier_prediction_ids` is held in). `typed_falsifier_text(prediction)` renders one as text --
its admitted facts and nothing else:

    sp.normalization_basis = DISAGREES in os:sp.normalization_basis@1.0.0 -> CONTRADICTS hyp:... (prd:...)

observable, outcome, OutcomeSpace id and version, the declared effect(s), the hypothesis and the
prediction id. No second stored source of truth: it is computed from the certificate whenever it is
needed, in `core.models.hypothesis_set`, beside the certificate it reads.

| path | before | after |
|---|---|---|
| inverted retrieval: `CONTEXT.falsifiers` and the query text | `[c.hypothesis.falsifier for c in in_contention]` | `[typed_falsifier_text(p) for c in in_contention for p in c.falsifier_predictions]` |
| Adversarial Critic: each hypothesis's `"falsifier"` | `c.hypothesis.falsifier` | `"; ".join(typed_falsifier_text(p) for p in c.falsifier_predictions)` |
| verification, RelationJudgment, TransitionPolicy, belief | the designated predictions | unchanged |

The Critic is not shown the prose at all, so it has one falsifier per hypothesis -- the one
verification adjudicates. Several designated falsifiers are all rendered, in prediction-id order.
Specialists were never shown a falsifier and still are not.

**The report shows both, labelled.** `HypothesisLine.machine_falsifiers` (default empty, so a report
stored before it still decodes) carries the renderings; the Markdown and web report show each as
"Machine falsifier -- what verification adjudicates" beside "Model's explanation (prose falsifier,
not adjudicated)". A disagreement between them is visible, not resolved.

**Qualification is unchanged, and so is the digest (`43ce474f374e...`).** The Evidence Researcher's
`falsifiers` stays a list of strings and the Critic's `falsifier` a string; no prompt, response
contract, parser or probe payload changed. The roles' contracts are about the shape of what they
return (search terms; objections citing shown evidence), and a falsifier's text is input they read,
not a rule they are held to. The locks made under `43ce474f...` therefore remain the current
qualification evidence, and the models are not re-tested.

**The stand-ins phrase typed falsifiers as a model would.** The debate benchmark's deterministic
scientist (`tests/debate_fixtures.MockScientist`) turned falsifier prose into inverted search terms
by tokenising it. Shown typed renderings instead, it now phrases each in the words of the mechanism
whose designated falsifier it is (its own catalog knowledge), as a language model given a typed
falsifier would; an unknown falsifier is searched for in its own words. With that, every benchmark
verdict is unchanged (10/10 kept, 5 wins, 0 losses, the Critic changing 5 final sets); only
digests and token estimates moved (cost ratio x3.35 -> x3.42). The production catalog reasoner is
unchanged: it searches with the words of what it is shown, now the typed rendering.

## 3. Tests

`tests/unit/test_falsifier_authority.py`, every certificate written as the deployed model wrote its
own -- prose naming outcome A, designation naming B: such a certificate is admitted under the
unchanged rules and stored as written; the inverted Evidence Researcher is shown B and the stored
inverted query is built from B, never the prose; the Critic is shown B for each hypothesis, never
the prose; observing A relates nothing, observing B instantiates the predeclared CONTRADICTS from
that prediction; two designated falsifiers are rendered and consumed in prediction-id order,
identically on every run; the report shows the machine falsifier and the prose, labelled; the
rendering is the prediction's own fields in another domain. The sample report carries a machine
falsifier, so the web report's exhaustive field check and its escaping test cover it. Five mutation
entries: inverted retrieval reading the prose again or omitting the typed falsifier, the Critic
reading the prose again or omitting it, an outcome no prediction declares relating a hypothesis.

## 4. Verification

Code: `598ee46`. CI run `37655646657`: commit hygiene, spec conformance, lint/types/full suite and
the PostgreSQL backend profile, all green. `src` changed only in the certificate helper, the
debate's two falsifier consumers and the report; `verification`, `llm_runtime`, `roles`,
TransitionPolicy, the migrations and security are untouched.

| Run | Passed | Skipped |
|---|---|---|
| local, Windows: `pytest -q` | 1746 | 844: 842 PostgreSQL-gated, 1 Lumerical, 1 network |
| local, fresh database (61 migrations): `LAB_BRAIN_TEST_POSTGRES=1 pytest -q` | 2588 | 2: 1 Lumerical, 1 network |

ruff, ruff format and strict mypy (237 source files) clean; status, obligation inventory and
requirement coverage current; the evidence and root-cause (`--disposable`) benchmark reports current
and unchanged; the debate benchmark report regenerated with every verdict, round count and metric
identical (digests and token estimates only). Mutation battery, all entries on a fresh database:
**426/426 killed**, no anchor missing.

## 5. Deployed

`docker compose -p lab-brain-workspace up --build -d` from `598ee46`, `LAB_BRAIN_INFERENCE_DEADLINE`
still 1200; no migration was pending and `local-models` changed nothing. The qualification digest
is unchanged (`43ce474f374e...`), so the two locks made under it stayed current -- qwen2.5-coder:7b
`lk:06d7d886bcb85a5a`, qwen2.5:7b `lk:271a4fad2094aab1` -- and the applied `local-typed-falsifier`
was ready and loaded without a re-test (REASONING_PRIMARY and FAST_UTILITY -> qwen2.5-coder:7b,
REASONING_ADVERSARIAL -> qwen2.5:7b, every route LOCAL).

## 6. The same blind smoke, after the switch

Episode **`epi:08cf92c8-a2f7-4a42-b100-8290ddeb8aea`** (`prj:smoke-local`, PRIVATE, LOCAL-only), one
run of **1389 s**, the same inputs as before (the synthetic report already in the project, the same
`PS-501.device.json`, no evaluator field, no literature, no simulator).

**Seven model calls**, each with an `LLM_CALL` span, ESTIMATED and ACTUAL BudgetGate entries and
InferenceProvenance on its locked LOCAL route: Evidence Researcher (30 s) -> Hypothesis Engine
(prompt 4.0.0, 407 s) -> two specialists (131 s, 122 s) -> the inverted rewrite (40 s) -> the
Critic (qwen2.5:7b, 396 s) -> the engine certifying the Critic's alternative (258 s; nothing new
admitted). One round, stopped STABLE.

**What the Critic's paths were shown, from stored rows.** Each call records the canonical hash of
its context. Rebuilding the first round's two contexts from the stored certificates, positions,
bundles and admitted statements:

| call | episode | context with typed falsifiers | context with prose |
|---|---|---|---|
| inverted rewrite | `epi:04d7d46b` (`492856d`) | no match | **matches** `5a7df72d...` |
| Critic | `epi:04d7d46b` (`492856d`) | no match | **matches** `a807538d...` |
| inverted rewrite | `epi:08cf92c8` (`598ee46`) | **matches** `a58ff356...` | no match |
| Critic | `epi:08cf92c8` (`598ee46`) | **matches** `e633d5c9...` | no match |

The stored inverted query (`bdl:01bcd318...`) contains every designated rendering and none of the
prose.

**Machine falsifier and prose, per hypothesis** -- as stored, and as the report and the web page now
show them (each certificate one prediction, designated, CONTRADICTS only; none forecasts):

| Hypothesis | machine falsifier (adjudicated) | model's prose (explanation) |
|---|---|---|
| PROCESS_DEPENDENT_CONTACT_RESISTANCE | `sp.probe_contact_resistance = ELEVATED` (`os:sp.probe_contact_resistance@1.0.0`) | "The series resistance follows a normal trend across the same sweep." |
| MESH_ARTEFACT | `sp.carrier_profile = NOMINAL` (`os:sp.carrier_profile@1.0.0`) | "The capacitance curves are distinguishable within measurement uncertainty." |
| DEPLETION_EFFECT | `sp.small_signal_impedance = RS_BIAS_INSENSITIVE` (`os:sp.rs_bias_response@1.0.0`) | "The series resistance follows a normal trend across the same sweep." |
| NORMALIZATION_BASIS_ISSUE | `sp.normalization_basis = DISAGREES` (`os:sp.normalization_basis@1.0.0`) | "The capacitance curves are distinguishable within measurement uncertainty." |
| TRANSMISSION_LINE_MEASUREMENT | `sp.small_signal_impedance = RS_BIAS_INSENSITIVE` (`os:sp.rs_bias_response@1.0.0`) | "The capacitance curves are distinguishable within measurement uncertainty." |

**Verification consumed the same falsifiers.** Plan `vpl:73063f97...`: `cap:sp.extraction_consistency`
(SUFFICIENT: NORMALIZATION_BASIS_ISSUE -> CHALLENGED / CONTRADICTED if DISAGREES), the four-point
probe (CONTACT_RESISTANCE if ELEVATED) and the split lot (MESH_ARTEFACT if NOMINAL); disagreement
UNKNOWN for all (no forecasts); the extraction check is the Pareto front and was chosen. It ran: Job /
Run `run:eadba7be...`, backend `sp.local.normalization_basis_reader`, output `art:sha256:049ad77f...`;
Observation `obs:adb35cb2...` `sp.normalization_basis = AGREES`; attestation `att:057c5df4...`
(OBSERVED). AGREES matches no declared prediction, so no RelationJudgment, no decision and no
event followed. Plan `vpl:b79c3cbe...`: the extraction check excluded as run; the four-point probe, a
person's act (HUMAN_ACTION_REQUIRED). Pending, not emulated: `cap:sp.charge_ac_sweep` (best next:
DEPLETION_EFFECT and TRANSMISSION_LINE_MEASUREMENT -> CONTRADICTED if RS_BIAS_INSENSITIVE) and
`cap:sp.charge_dc_sweep` (MESH_ARTEFACT -> CONTRADICTED if NOMINAL). The episode is `SUSPENDED`
("awaiting simulator for cap:sp.charge_ac_sweep"); through `verified_history` -> `replay` all five
rivals are ACTIVE, each history one genesis event, verified 1/1.

**Blind comparison, after the run.** The evaluator truth for `contact-open-via` is
`contact_discontinuity` (expected stop CONFIRMED). The set holds no contact-discontinuity hypothesis
and no prediction over `sp.contact_connectivity`, so the local connectivity check was never a
candidate. Beside that: one admitted "hypothesis" names a measurement, not a mechanism
(TRANSMISSION_LINE_MEASUREMENT); MESH_ARTEFACT's falsifier reads the carrier profile; the prose
falsifiers repeat across hypotheses; the falsifiers for contact resistance and normalization are the
outcomes those mechanisms would produce; no hypothesis forecasts anything. These are **LOCAL MODEL
SCIENTIFIC-QUALITY failures**, recorded and not tuned around: the core consumed one falsifier per
hypothesis on every path and exposed the prose beside it.

**History is untouched.** Against a snapshot taken before the rebuild (cutoff
2026-10-07 18:09:27 UTC): 41 InferenceProvenance rows, 8 episodes, 9 research runs, 120 probe rows,
11 lock rows, 25 hypotheses, 30 predictions, 2 relations, 27 belief events, 2 decisions,
4 observations, 146 attestations, 8 plans, 7 jobs, 7 runs and 91 cost entries, identical; ingestion
items unchanged (3); no external snapshot; no egress policy.
