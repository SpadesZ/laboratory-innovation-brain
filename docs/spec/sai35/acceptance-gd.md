# SAI 3.5 Discovery Candidate — G-D acceptance framework

Version: `3.5.0-discovery-candidate.1`. Refines D-035, D-036 and D-037 of the
[candidate](../SAI_3.5_Discovery_Candidate.md).
Status: **CANDIDATE — NOT ACTIVE.** No G-D level has been evaluated. `READY_FOR_REAL_RESEARCH = false`.

## 1. Why a separate framework

G0–G9 accept a research workflow (G0) and an autonomous modeling, numerical and physical chain
(G1–G9). They can all pass for a system that never finds anything new: a product can build correct
models, converge, match references and report bilingually while only ever confirming the
hypotheses it was handed. Discovery is a different claim, so it gets a different gate.

Rules that hold at every level:

- **Independent verdict.** Only an evaluator assigned by the Owner, who is not the implementer and
  not a second account of the implementer, can sign a G-D verdict (D-035). The system, its
  developers and any development agent can prepare material but cannot sign.
- **No implication upward.** Passing G-D*k* says nothing about G-D*k+1* (D-036).
- **No substitution.** No G-D result passes a G gate, and no G gate passes a G-D level (D-037).
  The G prerequisites listed below are *entry* conditions, not substitutes.
- **Scope.** A verdict names its benchmark, model family, product commit, model identifiers and
  environment manifest. It applies only there.
- **States.** Each level's result is one of `PASS`, `FAIL`, `BLOCKED` (a prerequisite or decision
  is missing), `INVALID` (protocol breach, drift or contamination beyond the rule) or
  `NOT_EVALUATED`. `WARN` does not exist here: a borderline result is FAIL for the claim.
- **Frozen first.** Every threshold is frozen at G-D0 before any arm runs. A threshold that is
  missing makes the level BLOCKED. It is never filled in afterwards by the implementer.

## 2. Levels

| Level | Entry conditions | Required evidence | Pass | Fail or other outcome |
|---|---|---|---|---|
| G-D0 | Owner decisions OD-02 (evaluator and custodian), OD-03 (protocol values) and OD-04 (local models) recorded; development data separated from sealed data | frozen protocol hash; sealed benchmark commitments; scorer source hashes; contamination report; environment manifest; evaluator and custodian assignment signed by the Owner; arm configurations frozen by hash | every listed artifact exists, verifies by hash, and was created before any arm ran on sealed cases | any artifact missing → BLOCKED; any sealed case or truth seen by the implementer → INVALID, and the affected cases must be re-sealed |
| G-D1 | G-D0 PASS for the synthetic benchmark; zero-cost stage only (local or deterministic models, offline) | per-case outputs of arms A, B and C bound to the manifest and environment hashes; blinded scores; reproducibility re-runs; budget ledgers for every arm | C exceeds B on the primary metric by at least the minimum effect, with the interval excluding zero after multiplicity correction; C is non-inferior to B on weighted false discoveries; C stops correctly on no-mechanism worlds at least as often as B; re-run invalid rate under the frozen limit | any pass condition not met → FAIL; budget mismatch or environment drift beyond the rule → INVALID |
| G-D2 | G-D0 PASS for the literature benchmark; G0 accepted for the product configuration evaluated; OD-06 (case rights) recorded; paid models only under OD-05 | everything for G-D1, on held-out real literature cases; contamination controls for each case; blinded expert review of novelty and falsifiability by at least two independent reviewers, with agreement and adjudication | the G-D1 conditions on this benchmark; in addition, a pre-registered share of C's claims is judged novel (PriorArtSearchRecord with coverage) and falsifiable by the reviewers, and C's rate is not below B's | contamination above the frozen rule → INVALID for affected cases; any condition not met → FAIL |
| G-D3 | G-D2 PASS; SAI 3.4 P-LICENSED entered; for the model family, G1, G2, G3, G7-SITE and the licensed parts of G8 accepted; OD-07 (license, worker and budget) recorded | evaluator-sealed simulation cases (a hidden configuration or mechanism built by the evaluator); the system's prospective predictions and pre-registrations; licensed Runs on internal workers with checkout records; convergence evidence; scores for all three arms | the G-D1 conditions on these cases; every simulated observable used to discriminate passed its convergence study; no CONFIRMED claim outside the Causal Warrant Gate | a mock or unqualified worker in any arm → INVALID; missing license or prerequisite → BLOCKED |
| G-D4 | G-D3 PASS for the scope; SAI 3.4 P-PHYSICAL entered; G4, G5 and G6 accepted for the scope; OD-08 (physical experiments and publication) recorded for each experiment | pre-registered predictions dated before fabrication or measurement; independent measurements with uncertainty; Causal Warrant Gate decisions; the evaluator's report | at least one pre-registered, previously unreported mechanism is confirmed through the Causal Warrant Gate on independent physical data, with the comparison against arms A and B as frozen; no confident wrong claim above the frozen limit | measurement not independent, or registration after the data existed → INVALID; no confirmation → FAIL (the result is still reported) |

## 3. What each level allows anyone to say

| Level passed | May say (for the stated scope only) | May not say |
|---|---|---|
| none | "Discovery is specified and under development." | anything about discovery performance |
| G-D0 | "A discovery evaluation is frozen and ready." | anything about results |
| G-D1 | "In these synthetic worlds, at matched budget and zero cost, the Discovery Loop found hidden mechanisms better than the baselines." | that it discovers real physics; that it beats other models |
| G-D2 | "On these held-out literature cases, it re-discovered published mechanisms better than the baselines, and reviewers judged the claims novel and falsifiable at the reported rate." | that the claims are physically true; prospective discovery |
| G-D3 | "In evaluator-sealed licensed simulations, it discovered hidden mechanisms prospectively." | physical discovery; other model families or solvers |
| G-D4 | "It prospectively proposed a mechanism that independent physical experiments confirmed through the Causal Warrant Gate." | generality beyond the scope; READY_FOR_REAL_RESEARCH, which still needs the SAI 3.4 gates and the Owner |

## 4. Scoring rules shared by all levels

- **Unit.** One case is one world, one literature case, or one physical case. Steps, tokens,
  sweep points and repeated runs never increase n.
- **Correct stop.** In a case where no mechanism can be validated with the available experiments,
  `INSUFFICIENT_VALIDATION` or `STOPPED` with a correct reason is the correct answer (D-028). In any
  other case a stop is scored as "not discovered", not as a false discovery.
- **Equivalence.** A claim is correct when it lies in the true mechanism's equivalence class under
  the case's full experiment set (D-017). The evaluator computes the partition from sealed truth.
- **Crashes.** A crashed or timed-out case stays in the denominator as "not discovered" for that
  arm. The crash is reported.
- **Governance breaches.** An arm that breaches egress, budget, isolation or the Owner gates on a
  case gets that case marked INVALID and reported as an incident. If incidents exceed the frozen
  limit, the level is INVALID.
- **Reproducibility.** A pre-registered subset of cases is re-run with the same seeds and
  environment. A re-run whose environment manifest differs in commit, schema, packages, model
  digest or scorer hash is INVALID, not "reproduced".

## 5. Relation to the G0 blind-evaluation tooling

The G0 line at `58c68be` (not integrated into this base) contains sealing, contamination checking,
freezing, a blind runner, a deterministic scorer, Wilson and bootstrap intervals and an environment
manifest (`src/lab_brain/evaluation/`, `scripts/g0_eval_*.py`; see
[implementation status](implementation-status.md)). G-D can reuse that tooling once it is
integrated and reviewed. Its G0 scorer measures research reliability for G0 and is not a G-D
scorer. G-D needs its own metrics (D-042), its own arm handling and its own sealed benchmark.
