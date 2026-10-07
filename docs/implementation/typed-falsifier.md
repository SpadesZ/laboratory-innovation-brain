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

## 5. Known, not fixed here

`verification.disagreement.rank_by_disagreement` takes every prediction's `expected_outcome` as the
rival's expectation, whatever its relation effect. Two rivals with IDENTICAL outcome -> effect
signatures (`HIGH -> SUPPORTS`, `LOW -> CONTRADICTS`) score a positive disagreement (1 under a
categorical metric; 0 with the SUPPORTS predictions alone). `LeastCostPlanner` reads
`disagreement > 0` as `SelectionCandidate.discriminating`, which `selection.rank` orders before the
Pareto and cost comparison -- so in the silicon-photonics planner a simulation whose two rivals
declare identical signatures (`cap:sp.charge_ac_sweep`, disagreement 0.5) is ranked and chosen
ahead of a cheaper sufficient analytical check (`cap:sp.extraction_consistency`), and the order
flips back when the identical CONTRADICTS predictions are removed. The typed falsifier makes a
CONTRADICTS prediction mandatory on every hypothesis, so the defect now applies to every certificate.
The ranking is left unchanged in this slice: the fix belongs with the selection semantics, and
nothing in it infers CONTRADICTS from an unequal outcome.
