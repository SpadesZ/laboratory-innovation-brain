# SAI 3.5 Discovery Candidate — Matched-budget comparison protocol

Version: `3.5.0-discovery-candidate.1`. Refines D-038 to D-046 of the
[candidate](../SAI_3.5_Discovery_Candidate.md).
Status: **CANDIDATE — NOT ACTIVE.** Nothing in this protocol has been run. The numbers marked
*proposed* are recommendations for Owner decision OD-03, not frozen values.

## 1. Question

Does adding the Discovery Loop make LIB better at finding true mechanisms, at the same cost, without
more false discoveries? Discovery is only worth its complexity if the answer is yes, measured on
cases nobody involved has seen, against a fair baseline.

## 2. Arms

| Arm | What runs | What it may not use |
|---|---|---|
| **A — single LLM** | the same model or models as B and C, driven by a frozen minimal loop: one fixed prompt template, the same tool interface (corpus search, experiment requests, stop), the same answer schema | LIB's structured debate, admission gate, verification planner, Causal Warrant Gate or Discovery Loop |
| **B — existing LIB** | the product research workflow at the frozen commit, with the Discovery Loop disabled: debate, coverage review, least-cost verification, evidence admission, TransitionPolicy and the Causal Warrant Gate; exploratory screening fixed to the same setting as in C | the Discovery Loop components of SAI 3.5 §3 |
| **C — LIB with Discovery** | arm B plus problem discovery, distinguishable-mechanism expansion, the anomaly registry, Research Reframing and discrimination-per-cost selection | anything B may not use besides the Discovery Loop; any extra budget |

Every arm returns the same answer schema for each case: the claimed mechanism (or none), its
epistemic state (SAI 3.5 D-027), evidence references, uncertainty by source, the experiments it ran
with their costs, and an optional `INSUFFICIENT_VALIDATION` or `STOPPED` outcome with its reason.

*Offline analogues.* The offline Discovery Loop v0 under development (see
[implementation status](implementation-status.md)) uses three synthetic baselines: B0
single-hypothesis, B1 LIB-without-discovery and B2 LIB+Discovery. B1 and B2 correspond to arms B
and C. B0 is a deterministic single-hypothesis policy, not an LLM, so it is not arm A. How the
offline baselines map to arms A, B and C at G-D1 is to be settled before G-D0 is frozen.

## 3. Matching

| Dimension | Rule |
|---|---|
| Models | identical model identifiers and digests, identical decoding settings (temperature, top-p, max tokens) in every arm. The primary comparison binds all LIB model slots to one model; a multi-model configuration is a separate, separately pre-registered comparison |
| Token budget | one cap per case covering input and output tokens across every call, including failures, retries and parsing repairs. Local tokens are counted even when they cost nothing |
| Compute budget | one cap per case in CPU and GPU seconds for model inference and local computation |
| Experiment budget | one cap per case in cost units, from a single frozen cost table that prices every experiment the same way in every arm |
| Licensed budget | at G-D3 and above, one cap per case in seat time per product, with checkout records |
| Tools and data | the same corpus snapshot (hash), the same experiment catalog, the same simulator access, the same egress permissions |
| Time | the same wall-clock limit per case |
| Seeds | the same seed list; each case uses the same seed in every arm |
| Environment | one environment manifest (commit, schema, packages, model digests, scorer hash) for all arms |

Unused budget is not carried over to another case or arm. When an arm reaches a cap, the case ends
as `STOPPED (budget)` and the answer it had at that point is scored. An attempt to exceed a cap is
recorded as an incident.

## 4. Benchmark

The benchmark is built and sealed by the independent evaluator before any arm runs on it (G-D0).

| Stratum | Content | Truth and sealing |
|---|---|---|
| Synthetic worlds (G-D1) | seeded generators of silicon-photonics-like worlds: a hidden true mechanism or set of mechanisms, distractor mechanisms, observationally equivalent rivals under part of the experiment catalog, anomalies, noise, a cost table and an experiment oracle. At least a pre-registered share are *no-mechanism-validatable* worlds, where the correct answer is INSUFFICIENT_VALIDATION | world parameters and seeds committed by hash; truth outside the repository; seeds drawn after the freeze |
| Held-out literature cases (G-D2) | problems from real literature whose resolution was published after the training cutoff of every model used, or held out from every corpus. The case gives what was known before the resolution; the experiment oracle reveals only the data the resolving work reports, when an arm requests and pays for that specific experiment | case material and truth sealed; resolution dates and rights recorded per case |
| Physical cases (G-D3, G-D4) | at G-D3, evaluator-built simulation cases with a hidden configuration or mechanism; at G-D4, real devices or processes with pre-registered measurements | sealed by the evaluator; independent measurement at G-D4 |

Every case in the frozen list stays in the denominator. Exclusions follow only the pre-registered
contamination rule (§7) and are reported.

## 5. Metrics

Exactly one metric is the primary metric (*proposed*: true-mechanism discovery rate). All five are
always reported, for every arm, with n, the estimate and an interval.

| Metric | Definition | Notes |
|---|---|---|
| **True-mechanism discovery rate** | share of cases in which the arm's final claim lies in the true mechanism's equivalence class under the case's full experiment set; in a no-mechanism-validatable case, a correct INSUFFICIENT_VALIDATION counts as discovered | the claim is scored at its stated epistemic state; a correct mechanism held only as PROPOSED does not count |
| **Distinguishable diversity** | number of distinct equivalence classes among the arm's admitted hypotheses, under the experiments available in the case; also whether the true class was among them (*class coverage*) | raw hypothesis counts are never reported as diversity; merged pairs whose distinguishability was undecidable are listed |
| **Experimental efficiency** | experiments and cost units consumed until correct discrimination, meaning the true class is the only surviving class | censored at the budget; reported as a cost-to-discrimination curve and median with censoring, not as a mean over successes only |
| **False discoveries** | false-discovery rate = wrong claims at SUPPORTED or higher ÷ all claims at SUPPORTED or higher; plus a weighted score: wrong CONFIRMED × w_c, wrong SUPPORTED × w_s, a confident claim where a stop was correct × w_stop | *proposed* weights w_c = 10, w_s = 3, w_stop = 3; frozen under OD-03 |
| **Reproducibility** | re-run a pre-registered subset with the same seeds and environment; report the share with the same final claim and state | a re-run whose environment manifest drifted in commit, schema, packages, model digest or scorer hash is INVALID and reported as such; an invalid rate above the frozen limit invalidates the comparison |

## 6. Statistics

Frozen before unsealing, under OD-03:

- **Unit:** the case. Arms are compared as *paired* observations on the same cases.
- **Comparisons:** C vs B (primary), C vs A and B vs A (secondary).
- **Binary metrics:** paired difference with an exact McNemar test and a case-resampling bootstrap
  interval (fixed seed), or Newcombe's interval for paired proportions. Single-arm proportions use
  the Wilson interval.
- **Count and cost metrics:** paired Wilcoxon signed-rank and a paired bootstrap interval;
  efficiency uses a censoring-aware comparison.
- **Minimum effect of interest:** *proposed* +10 percentage points on the primary metric for C over B.
- **Non-inferiority:** *proposed* margin of 2 percentage points on the false-discovery rate and
  on the correct-stop rate for no-mechanism worlds.
- **Multiplicity:** Holm–Bonferroni across the five metrics and three comparisons, family-wise
  α = 0.05 (*proposed*), with the primary metric declared in advance.
- **Sample size:** a power or precision calculation for the primary metric is frozen with its
  assumptions. Before that, an exploratory pilot runs on separate development worlds that never
  become part of the sealed set.
- **Interim looks:** none unless pre-registered with an error-spending rule.
- **Reporting:** all cases, all arms, all metrics, including null and negative results.

## 7. Contamination controls

- Every literature case records the resolution publication date against each model's documented
  training cutoff. A case not clearly after every cutoff is excluded before unsealing.
- Case texts are checked for overlap against development data and public corpora with a frozen
  method and threshold (the G0 line's `evaluation/contamination.py` is a candidate tool once
  integrated and reviewed).
- Memorization probes ask each model to complete case-specific identifiers. A positive probe
  triggers the pre-registered rule for that case.
- Synthetic seeds are generated after the freeze by the evaluator. Implementers have no access to
  the generator's sealed parameters.
- The rule for contaminated cases (exclude, or re-seal and replace) is decided at G-D0, before any
  unsealing. Every exclusion is reported with its reason.

## 8. Stopping rules

| Level | Stops when | Result |
|---|---|---|
| Case | budget cap, time limit, or the arm's own STOPPED or INSUFFICIENT_VALIDATION | the answer at that point is scored |
| Study | the pre-registered n is reached, or a pre-registered interim boundary is crossed | final analysis |
| Incident | an arm breaches egress, budget, isolation or an Owner gate | the affected runs are INVALID and reported; above the frozen limit, the study is INVALID |
| Paid stage | the Owner's ceiling is reached | reported as partial; no extrapolation |

## 9. Stage order and cost

1. **Zero-cost stage (required first).** Offline synthetic worlds; deterministic policies or local
   open-weight models declared free under the spend administration (G0 Owner decisions A3/A4);
   no paid API, no license, no physical experiment. The result goes to the Owner whatever it is.
2. **Local literature stage.** Held-out literature cases with the same local models; still zero cost.
3. **Paid model stage (optional).** Only under Owner decision OD-05 with a ceiling. A negative
   zero-cost result is not overturned by running a bigger model on the same sealed cases; a new
   question needs a new sealed set.
4. **Licensed stage.** G-D3, only after SAI 3.4 P-LICENSED and OD-07.
5. **Physical stage.** G-D4, only after SAI 3.4 P-PHYSICAL and OD-08 for each experiment.

## 10. What falsifies "Discovery helps"

See SAI 3.5 §8. In short: no primary-metric gain at the minimum effect, worse weighted false
discoveries, a diversity gain that disappears when counted as equivalence classes, worse stopping on
no-mechanism worlds, a gain that depends on a mismatch, or an unreproducible gain. If arm A matches
arm C, the extra machinery is not justified for discovery on that scope.
