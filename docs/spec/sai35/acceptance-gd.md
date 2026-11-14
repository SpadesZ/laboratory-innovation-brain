# SAI 3.5 — Appendix I: G0–G9 and the independent G-D acceptance framework

Version: `3.5.0-master-candidate.5`. Status: **CANDIDATE — NOT ACTIVE.** No G-D level has been
evaluated. `READY_FOR_REAL_RESEARCH = false`.
Authority: normative. Refines S35-GD-001, S35-GD-002 and S35-GD-003 of [SAI 3.5](../SAI_3.5.md).
Supersedes the `3.5.0-discovery-candidate.1` version of this file (kept in git history).

## 1. Why a separate framework

G0–G9 accept a research workflow (G0) and an autonomous modeling, numerical and physical chain
(G1–G9). All of them can pass for a system that never finds anything new: a product can build
correct models, converge, match references and report bilingually while only confirming the
hypotheses it was handed. Discovery is a different claim, so it gets a different gate.

Rules at every level:

- **Independent verdict.** Only an evaluator assigned by the Owner, who is neither the implementer
  nor a second account of the implementer, signs a G-D verdict (S35-GD-001). The system, its
  developers and any development agent may prepare material but cannot sign.
- **No implication upward.** G-D*k* says nothing about G-D*k+1* (S35-GD-002).
- **No substitution.** No G-D result passes a G gate; no G gate passes a G-D level (S35-GD-003).
  The G prerequisites below are entry conditions, not substitutes.
- **Completing G0–G9 never implies discovery.** A product with every G gate accepted and no G-D
  verdict has shown no discovery capability.
- **Synthetic is not real.** A G-D1 pass, or any synthetic benchmark result, is never reported as
  validation of real discovery. Implementer-written worlds, such as those of the offline prototype
  on `118a4ac`, are never G-D evidence (S35-CMP-004).
- **Scope.** A verdict names its benchmark, model family, product commit, model identifiers and
  environment manifest, and applies only there.
- **States.** `PASS`, `FAIL`, `BLOCKED` (a prerequisite or decision is missing), `INVALID` (protocol
  breach, drift, contamination beyond the rule, or COST_UNMATCHED for a matched-budget claim) or
  `NOT_EVALUATED`. There is no `WARN`: a borderline result is FAIL for the claim.
- **Frozen first.** Every threshold is frozen at G-D0 before any arm runs. A missing threshold
  makes the level BLOCKED; the implementer never fills it in afterwards.

## 2. G0–G9 and G-D

| G gate (SAI 3.4) | Role for G-D | Never means |
|---|---|---|
| G0 | entry condition for G-D2 for the configuration evaluated; the G0 blind-evaluation tooling may be reused | that discovery works |
| G1, G2, G3 | entry conditions for G-D3 for the model family | that the system found a new mechanism |
| G4, G5, G6 | entry conditions for G-D4 for the scope | that a mechanism was discovered prospectively |
| G7-SITE | entry condition for G-D3 and G-D4 | cross-worker or cross-site discovery |
| G7-WORKER | needed only for a cross-worker discovery claim | — |
| G8 | its licensed parts are entry conditions for G-D3 | — |
| G9 | none directly; T-S35-AUTO-001 and G9 both test the absence of external coding agents and may share evidence, each issuing its own result | that the product discovers |

## 3. Levels

| Level | Entry conditions | Required evidence | Pass | Fail or other outcome |
|---|---|---|---|---|
| G-D0 | OD-02 (evaluator, hidden-world generator owner, custodian), OD-03 (protocol values) and OD-04 (local models) recorded; development data separated from sealed data | frozen protocol hash; evaluator-generated hidden worlds sealed by commitment; scorer source hashes; contamination report; environment manifest; signed assignments; arm configurations frozen by hash | every artifact exists, verifies by hash and predates any arm run on sealed cases | an artifact missing → BLOCKED; sealed material seen by the implementer → INVALID and re-seal |
| G-D1 | G-D0 PASS for the synthetic benchmark; zero-cost stage only | per-case outputs of arms A, B and C bound to manifest and environment hashes; realized consumption per case and arm; blinded scores; independent reproducibility re-runs | C exceeds B on the primary metric by at least the minimum effect at matched realized consumption, the interval excluding zero after multiplicity correction; C is non-inferior to B on weighted false discoveries; C stops correctly in no-mechanism worlds at least as often as B; the re-run invalid rate is under the frozen limit | a condition not met → FAIL; realized consumption not matchable → INVALID (COST_UNMATCHED); drift → INVALID |
| G-D2 | G-D0 PASS for the literature benchmark; G0 accepted for the configuration; OD-06 recorded; paid models only under OD-05 | as G-D1, on held-out real literature cases; contamination controls per case; blinded review of novelty class and falsifiability by at least two independent reviewers with agreement and adjudication | the G-D1 conditions on this benchmark; a pre-registered share of C's claims is judged falsifiable and correctly classed for novelty, and C's rate is not below B's | contamination above the frozen rule → INVALID for the affected cases; otherwise FAIL |
| G-D3 | G-D2 PASS; SAI 3.4 P-LICENSED entered; G1, G2, G3, G7-SITE and licensed G8 accepted for the model family; OD-07 recorded | evaluator-sealed simulation cases; prospective registrations; licensed Runs on qualified internal workers with checkout records; convergence evidence; scores for all arms | the G-D1 conditions on these cases; every discriminating simulated observable passed its convergence study; no CONFIRMED outside the Causal Warrant Gate | a mock or unqualified worker in any arm → INVALID; missing license or prerequisite → BLOCKED |
| G-D4 | G-D3 PASS for the scope; SAI 3.4 P-PHYSICAL entered; G4, G5 and G6 accepted for the scope; OD-08 recorded per experiment | registrations dated before fabrication or measurement; independent measurements with uncertainty; Causal Warrant Gate decisions; the evaluator's report | at least one pre-registered mechanism absent from the covered prior art is confirmed through the Causal Warrant Gate on independent physical data, with the comparison against arms A and B as frozen; confident wrong claims under the frozen limit | measurement not independent, or registration after the data existed → INVALID; no confirmation → FAIL (still reported) |

## 4. What each level allows anyone to say

| Level passed | May say (for the stated scope only) | May not say |
|---|---|---|
| none | "Discovery is specified and under development." | anything about discovery performance |
| G-D0 | "A discovery evaluation is frozen and ready." | anything about results |
| G-D1 | "In these evaluator-generated synthetic worlds, at matched realized consumption and zero cost, LIB with Discovery found hidden mechanisms better than the baselines." | that it discovers real physics; that it beats other models |
| G-D2 | "On these held-out literature cases, it re-identified published mechanisms better than the baselines, and reviewers judged its claims falsifiable and correctly classed at the reported rate." | that the claims are physically true; prospective discovery |
| G-D3 | "In evaluator-sealed licensed simulations, it discovered hidden mechanisms prospectively." | physical discovery; other model families or solvers |
| G-D4 | "It prospectively proposed a mechanism that independent physical experiments confirmed through the Causal Warrant Gate." | generality beyond the scope; `READY_FOR_REAL_RESEARCH`, which still needs the SAI 3.4 gates and the Owner |

## 5. Scoring rules for all levels

- **Unit.** One case is one world, one literature case or one physical case. Steps, tokens, sweep
  points and repeated runs never increase n.
- **Outcomes.** Each case and arm is scored with exactly one outcome of
  [Appendix S](mechanism-distinguishability.md) §6 (exact identification, indistinguishable
  alternative, unresolved alternative, correct abstention, false null, force-fit, wrong claim,
  validated new mechanism, proposal only), computed by the evaluator from sealed truth, after the
  evaluator re-derives the answer's evidential level from the trace: only a SUPPORTED or CONFIRMED
  answer gets a claim outcome, every other answer is a proposal (candidate.4); there is no
  equivalence class and no transitive merge. The rates are reported separately and never merged: a
  correct abstention is a safety result, not an identification; an indistinguishable alternative is
  correct within experimental resolution, not an exact identification; an exploratory proposal is
  never a discovery. In a case where no mechanism can be validated, `INSUFFICIENT_VALIDATION` or
  `STOPPED` with a correct reason is a correct abstention (S35-LOOP-003); a stop elsewhere is a false
  null when a held mechanism matched the truth, not a false discovery.
- **Matched cost.** Every arm is scored on the answers it held at the frozen realized-cost
  checkpoints, primary at c*, with reservation before execution and retrospective settlement
  ([Appendix J](matched-budget-protocol.md) §3.3); runs at equal caps are not thereby matched;
  COST_UNMATCHED cases stay in the denominator.
- **Force-fit.** Endorsing a held mechanism that fails the adequacy criterion, in a case whose true
  family is outside the held set, is a false discovery when stated at SUPPORTED or higher and is
  reported as a force-fit at every level (S35-MECH-002).
- **Termination dimensions.** Every case reports operational termination, experimental completion
  and scientific acceptance ([lifecycle.md](lifecycle.md) §3.1); a stop before any experiment is
  scored by the outcome rule above and is never counted as a completed campaign.
- **Crashes.** A crashed or timed-out case stays in the denominator as "not discovered"; the crash
  is reported.
- **Governance breaches.** A breach of egress, budget, isolation or an Owner gate marks the case
  INVALID and is an incident; above the frozen limit the level is INVALID.
- **Reproducibility.** A pre-registered subset is re-run by the evaluator in a fresh environment
  from the frozen manifest. A re-run whose manifest differs in commit, schema, packages, model
  digest or scorer hash is INVALID, not "reproduced".
- **Acceptance versus diagnostic scores.** A score counts toward a verdict only if the runner's and
  the evaluator's environment verifications both pass; any other score is labelled diagnostic. (The
  G0 line implements this distinction for G0 on the unmerged branch
  `g0-authorization-read-path-closure`, pending audit.)

## 6. Relation to the G0 blind-evaluation tooling

The G0 line (`f41758c`) has sealing, contamination checks, freezing, a blind runner, a deterministic
scorer, Wilson and bootstrap intervals and an environment manifest
(`f41758c:src/lab_brain/evaluation/`, `f41758c:docs/evaluation/G0-blind-evaluation-protocol.zh-TW.md`).
G-D may reuse that tooling after integration and review. Its G0 scorer measures research reliability
for G0 and is not a G-D scorer: G-D needs its own metrics (S35-CMP-005), arm handling, realized
consumption matching and evaluator-generated hidden worlds.
