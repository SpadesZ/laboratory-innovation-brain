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
