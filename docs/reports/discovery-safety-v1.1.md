# Discovery safety v1.1: refit coverage fixpoint and localized predictive checks

Date: 2026-11-04. Branch: `claude/lib-implementation-agent-47evs0-discovery-v11`. Not pushed, not
merged, not deployed.

> **ENGINEERING EVIDENCE ONLY** on developer-authored synthetic worlds. The held-out mechanism
> families were declared, by the same author lineage that wrote the engine and both safety gates, in
> the catalog the engine was developed against. Nothing here is independent scientific evidence, an
> independent or blind evaluation, or a statement about a real device. **Scientific acceptance: NOT
> PASSED. G-D: NOT PASSED.** No model, paid call, simulator (no Lumerical), network, database write
> or real experiment was used. Discovery is NOT connected to real research execution.

| | SHA |
|---|---|
| Baseline (v1.0 branch head) | `0928602` (`092860276272fc369836b4ab5c0d54f6c5e12091`) |
| Reproduction-before (v1.0 vulnerable, tests + log) | `43a2f5f` |
| v1.1 gate and tests | `a3397f2` |
| **Design freeze** (protocol, plan, evaluation code, script) | **`53bd2a9`** (`53bd2a9a8165d718a4527b5d814b566ba9639772`) |
| Mutation battery entries | `d49d03e` |
| Evidence (generated at `d49d03e`, clean tree, from code byte-identical to `53bd2a9`) | `10d2a91` |
| Final code SHA | `53bd2a9`: no file under `src/` changed after the freeze. Later commits add only tests, docs, the status inventory and the mutation entries. The final branch head is given in the hand-off message, because a commit cannot contain its own SHA |

Evidence: [`docs/audit/discovery-safety-v1.1-2026-11-04/`](../audit/discovery-safety-v1.1-2026-11-04/).
It contains `refit-bypass-before.log`, `development.log` and `evidence/`, which holds the manifest,
`results.json`, the per-world rows and `interpreter_verification.json`. The evidence is produced by
`scripts/discovery_safety_v11_eval.py`. The v1.0 evidence and the P3 evidence are unchanged, and so
are the frozen engine and the v1.0 package files.

---

## 1. Summary

- **The refit bypass was real in v1.0.** v1.0 decides which experiments a claim "predicts a signal
  in" only once, at the fit made before the probes, and judges coverage against that set. On a
  development seed, v1.0 endorsed a **force-fit** whose own final fit predicts a ≥3σ signal in an
  experiment that was never run (`cutback`). **v1.1 closes this.** Coverage is now judged against the
  union of every signal set the refits produce. On the new held-out seeds and on every other set,
  no v1.1 endorsement left a signal experiment unrun (`endorsed_with_a_never_run_signal_experiment = 0`
  in all four sets).
- **Localized predictive checks** are pre-declared in `SafetyProtocolV11`: a per-experiment
  chi-square under the global fit, with Holm correction at a family-wise level of 0.01. They catch
  some of the `leakage.substrate`→`scatter.sidewall` force-fits whose deviation the global test
  dilutes.
- **New held-out seeds (drawn after the freeze), family removed, primary worlds, force-fits at
  budgets 8/12/24/48:**
  - B2 (frozen engine): 65/195, 80/195, 95/195, 96/195.
  - B3 (v1.0): 0/195, 6/195, 4/195, 3/195.
  - B4 (v1.1): **0/195, 4/195, 3/195, 2/195**.
  - False nulls at budget 24: B2 29, B3 8, B4 3.
- **The cost, stated plainly.** With the truth left in the catalog (the control), v1.1 identifies the
  truth correctly **less often than v1.0** on the new seeds:
  - Budget 12: 160/240 (B3) against 156/240 (B4).
  - Budget 24: 234 against 229.
  - Budget 48: 236 against 231.
  - The extra abstentions are mostly CLAIM_INADEQUATE, which is the localized check rejecting a
    correct claim (false alarms).
  - No false discovery was added.
  - The force-fit gains (2, 1 and 1 worlds out of 195) are small and **within each other's Wilson
    intervals**. The B3→B4 difference is not statistically resolved on 195 worlds.
- The **Owner-approved strict policy** (signal coverage 1.0) is the frozen default (§9).

## 2. Refit bypass: reproduction before, verification after

**Question.** Can a signal prediction that appears only after refitting bypass the coverage
requirement?

**Reproduction before (v1.0 code, unchanged).**
[`refit-bypass-before.log`](../audit/discovery-safety-v1.1-2026-11-04/refit-bypass-before.log) was
generated at `0928602`. It scans development seeds only: bases 5_000_000 (6 worlds per class),
1 (6 per class) and 7_000_000 (15 per class). It covers both the family-removed and the
family-left-in settings, at budgets 8, 12, 24 and 48: 3,456 runs and 1,435 v1.0 endorsements. Two
endorsements leave a final-fit signal experiment unrun:

- **Held-out world `geometry.width_narrow-00`** (seed 7008000), family REMOVED, budget 12:
  - v1.0 endorses `fcd.static + geometry.gap_large`. This is a **force-fit**, and the world is not
    aliased.
  - The fcd amplitude rises from 0.570 to 0.625 over the probes. That puts `cutback` above 3σ.
  - `cutback` costs 3 units and was never run. The budget went to a null probe (`power_sweep`)
    chosen from the stale signal set.
- **`leakage.substrate-04`** (seed 5010004), family LEFT IN, budget 12:
  - v1.0 endorses the truth, but its final fit predicts a signal in the never-run `tec_stabilized`.
  - The answer is right, but it got through the same hole.

The tests in `tests/unit/test_discovery_safety_v11_refit.py` pin this v1.0 behaviour (arm B3). They
keep passing, so the vulnerability stays documented:

- `test_v10_endorses_a_force_fit_whose_refitted_signal_was_never_run`
- `test_v10_endorses_an_in_catalog_claim_through_the_same_hole`
- `test_the_bypass_needs_the_refit_the_pre_probe_fit_predicts_nothing_there`

**Verification after (v1.1, arm B4).**
- On the same force-fit world, B4 abstains with `ADEQUACY_UNVERIFIED` (confidence PROVISIONAL):
  - `refit.emerged_after_refit ∋ cutback`
  - `refit.uncovered == ("cutback",)`
  - the only request it makes is `cutback`.
- On the in-catalog case, B4 withholds endorsement at budget 12. At budget 24 it runs
  `tec_stabilized` and endorses the truth.
- The ablation `refit_fixpoint=False` reopens the hole: the same gate endorses the force-fit again.
- An exhaustive check covers every engine claim on the development worlds at base 7_000_000
  (2 per class, both settings, budgets 8/12/24/48). Every B4 endorsement has every experiment of
  the union run, and so does the signal set recomputed from the final admitted data.
- In the frozen evaluation, B4 endorsed **0** runs with a never-run signal experiment.
- Signal predictions emerged after a refit in 25, 27, 26 and 7 B4 runs per set. Each was then either
  covered or left the claim unendorsed.

## 3. Design (all in `src/lab_brain/discovery_safety/v11/`, declared in `SafetyProtocolV11`)

v1.1 is a subpackage. It subclasses the v1.0 gate and edits no v1.0 file, so the v1.0 manifest and
the frozen-evidence test still hold. v1.0's thresholds are unchanged:

| Threshold | Value |
|---|---|
| `alpha_adequacy` | 0.01 |
| `z_adequacy` | 4 |
| `z_signal` | 3 |
| `signal_coverage` | **1.0** |
| `max_probe_replications` | 2 |

v1.1 adds the following:

1. **Refit fixpoint (`refit_fixpoint`).**
   - The claim's signal set is recomputed after every admitted observation: each probe, each
     replicate and each exclusion as noise.
   - The cheapest affordable never-run signal experiment of the union is always probed before any
     null experiment.
   - Coverage is judged against the **union** of all signal sets, including the final fit's. The
     union contains v1.0's set, so on the same data the requirement is never weaker than v1.0's.
   - Probing stops when nothing affordable is left. A signal experiment still unrun at that point
     means `ADEQUACY_UNVERIFIED`, never an endorsement.
   - `RefitCoverage` records the initial, final and union sets, the emerged experiments, the
     uncovered ones, and stability.
2. **Localized predictive checks (`localized_check`, `alpha_localized = 0.01`,
   `localized_correction = holm-step-down`).**
   - For each distinct experiment among the admitted observations, the statistic is the chi-square
     of its standardised residuals under the hypothesis's global fit. Every entry of every
     replicate is included, with k residuals and k degrees of freedom. This is conservative: fitted
     residuals are smaller than the noise.
   - The family of per-experiment p-values is tested with Holm's step-down procedure at
     family-wise level 0.01.
   - Any rejection makes the hypothesis inadequate, alongside v1.0's global test. This applies
     everywhere adequacy is used: the claim, the replicate decision and the catalog-completeness
     check over every hypothesis the catalog expresses.
3. **Two rules found necessary on development seeds** (see `development.log`):
   - `defer_localized_replication = True`. A failure of the localized check alone is replicated
     only once nothing affordable is left to probe. A global failure is replicated at once, as in
     v1.0. In iteration 1, replicating a localized false alarm first spent the unit that the
     decisive probe needed, which produced a new force-fit (`nonlinear.tpa_fca-04`, budget 12). An
     unaffordable deferred replicate leaves the failure UNREPLICATED, and the gate abstains.
   - `max_noise_exclusions_per_experiment = 1`. In v1.0, a failing observation is excluded as
     noise whenever the claim fits without it. Repeated, this ratchet excluded two of three
     `cutback` runs, and a surrogate was endorsed (iteration 2, `leakage.substrate-03`, budget 24).
     In v1.1 a second failure in the same experiment counts as REPRODUCED.

**Design process.** The design was developed only on development seeds 5_000_000, 1 and 7_000_000,
in three logged iterations. `alpha_localized` and every z threshold were set before the first
iteration and **never tuned**. The evaluation plan (`EvaluationPlanV11`) is hashed with the protocol
in the manifest:

| Plan digest | Protocol digest |
|---|---|
| `sha256:bb67d168…` | `sha256:598c95aa…` |

The plan declares:
- the arms and the budgets 8/12/24/48;
- the checkpoint ladder 0.25/0.5/1.0 of the cap;
- the development and previously inspected ranges;
- the **new held-out ranges**. Their seeds come from fixed strings:
  `derived_base_seed(label) = 3_000_000_000 + 1000·(SHA-256(label) mod 10⁶)`, giving
  - held-out worlds: base 3931910000, 15 per class (240 worlds; 195 primary, 45 aliased);
  - benchmark world kinds: base 3320367000, 25 per kind (200 worlds).

The plan refuses any range within 20,000 of a range used before. The script's `--design-freeze`
check verified that the v1.1 sources were byte-identical to `53bd2a9` before it generated any
held-out world. Those worlds were generated only in the post-freeze evaluation run.

## 4. Results, separated by arm and budget

Categories (exactly one per run):
- **force-fit**: a mechanism claim separable from the truth. In held-out worlds this is any
  non-surrogate claim; in-catalog it is a false discovery.
- **false null**: `NO_EFFECT_BEYOND_NOISE` when there is an effect.
- **correct identification**: the frozen scorer's exact-truth rule. It is impossible when the family
  is removed.
- **indistinguishable alternative**: a claim of which no member can be separated from the truth by
  any available experiment. In held-out worlds this is a surrogate on an ALIASED world.
- **no claim**: an abstention, listed with its reason. B3 and B4 report the gate's reason (or
  `NO_ENGINE_CLAIM:<engine outcome>`); B2 reports the engine's stop outcome.

Other reporting conventions:
- Realized cost is the laboratory meter's charge.
- Intervals are Wilson 95%.
- The abstention-reason cells show the four largest reasons. The full counts are in `results.json`.
- **Stage-1 proposals are counted separately and are never an identification or a discovery.**
  `proposals_counted_as_identification = 0` everywhere, and the summariser raises an error if it is
  not.

### 4.1 New held-out evaluation (seeds drawn after the freeze) — HELD-OUT FOR v1.1

#### HELD-OUT FOR v1.1 (base 3931910000) -- family REMOVED (primary, non-aliased worlds; equal cap, COST_UNMATCHED)

| budget | arm | force-fit [Wilson 95%] | false null | correct identification | no claim (abstain) | abstention reasons | realized cost mean / median / p10-p90 / min-max |
|---|---|---|---|---|---|---|---|
| 8 | B2 | 65/195 [0.271, 0.402] | 11/195 [0.032, 0.098] | 0 (impossible) | 119/195 [0.540, 0.676] | STOPPED_UNEXPLAINED 66; STOPPED_INSUFFICIENT_VALIDATION 53 | 5.49 / 6 / 2-8 / 2-8 |
| 8 | B3 | 0/195 [0.000, 0.019] | 7/195 [0.018, 0.072] | 0 (impossible) | 188/195 [0.928, 0.983] | NO_ENGINE_CLAIM:STOPPED_UNEXPLAINED 66; NO_ENGINE_CLAIM:STOPPED_INSUFFICIENT_VALIDATION 53; ADEQUACY_UNVERIFIED 26; CATALOG_INCOMPLETE 21; ... | 6.41 / 8 / 2-8 / 2-8 |
| 8 | B4 | 0/195 [0.000, 0.019] | 6/195 [0.014, 0.066] | 0 (impossible) | 189/195 [0.934, 0.986] | NO_ENGINE_CLAIM:STOPPED_UNEXPLAINED 66; NO_ENGINE_CLAIM:STOPPED_INSUFFICIENT_VALIDATION 53; ADEQUACY_UNVERIFIED 23; CATALOG_INCOMPLETE 22; ... | 6.40 / 8 / 2-8 / 2-8 |
| 12 | B2 | 80/195 [0.344, 0.480] | 19/195 [0.063, 0.147] | 0 (impossible) | 96/195 [0.423, 0.562] | STOPPED_UNEXPLAINED 66; STOPPED_INSUFFICIENT_VALIDATION 30 | 6.48 / 6 / 2-12 / 2-12 |
| 12 | B3 | 6/195 [0.014, 0.066] | 9/195 [0.025, 0.085] | 0 (impossible) | 180/195 [0.877, 0.953] | NO_ENGINE_CLAIM:STOPPED_UNEXPLAINED 66; CATALOG_INCOMPLETE 46; NO_ENGINE_CLAIM:STOPPED_INSUFFICIENT_VALIDATION 30; CLAIM_INADEQUATE 17; ... | 8.28 / 10 / 2-12 / 2-12 |
| 12 | B4 | 4/195 [0.008, 0.051] | 8/195 [0.021, 0.079] | 0 (impossible) | 183/195 [0.895, 0.965] | NO_ENGINE_CLAIM:STOPPED_UNEXPLAINED 66; CATALOG_INCOMPLETE 47; NO_ENGINE_CLAIM:STOPPED_INSUFFICIENT_VALIDATION 30; CATALOG_INCOMPLETE_UNREPLICATED 18; ... | 8.27 / 10 / 2-12 / 2-12 |
| 24 | B2 | 95/195 [0.418, 0.557] | 29/195 [0.106, 0.205] | 0 (impossible) | 71/195 [0.300, 0.434] | STOPPED_UNEXPLAINED 68; STOPPED_INSUFFICIENT_VALIDATION 3 | 7.29 / 6 / 2-14 / 2-24 |
| 24 | B3 | 4/195 [0.008, 0.051] | 8/195 [0.021, 0.079] | 0 (impossible) | 183/195 [0.895, 0.965] | CATALOG_INCOMPLETE 93; NO_ENGINE_CLAIM:STOPPED_UNEXPLAINED 68; CLAIM_INADEQUATE 15; CATALOG_INCOMPLETE_UNREPLICATED 3; ... | 10.79 / 10 / 2-23 / 2-24 |
| 24 | B4 | 3/195 [0.005, 0.044] | 3/195 [0.005, 0.044] | 0 (impossible) | 189/195 [0.934, 0.986] | CATALOG_INCOMPLETE 96; NO_ENGINE_CLAIM:STOPPED_UNEXPLAINED 68; CLAIM_INADEQUATE 15; CATALOG_INCOMPLETE_UNREPLICATED 6; ... | 10.77 / 10 / 2-23 / 2-24 |
| 48 | B2 | 96/195 [0.423, 0.562] | 30/195 [0.110, 0.211] | 0 (impossible) | 69/195 [0.290, 0.423] | STOPPED_UNEXPLAINED 68; STOPPED_INSUFFICIENT_VALIDATION 1 | 7.48 / 6 / 2-14 / 2-48 |
| 48 | B3 | 3/195 [0.005, 0.044] | 8/195 [0.021, 0.079] | 0 (impossible) | 184/195 [0.902, 0.968] | CATALOG_INCOMPLETE 99; NO_ENGINE_CLAIM:STOPPED_UNEXPLAINED 68; CLAIM_INADEQUATE 15; CATALOG_INCOMPLETE_UNREPLICATED 1; ... | 11.25 / 10 / 2-23 / 2-48 |
| 48 | B4 | 2/195 [0.003, 0.037] | 4/195 [0.008, 0.051] | 0 (impossible) | 189/195 [0.934, 0.986] | CATALOG_INCOMPLETE 103; NO_ENGINE_CLAIM:STOPPED_UNEXPLAINED 68; CLAIM_INADEQUATE 15; CATALOG_INCOMPLETE_UNREPLICATED 2; ... | 11.22 / 10 / 2-23 / 2-48 |

Aliased worlds (truth inseparable from a reduced-catalog hypothesis): indistinguishable-alternative (surrogate) claims / other claims / no claim

| budget | B2 | B3 | B4 |
|---|---|---|---|
| 8 | 12 / 19 / 14 of 45 | 0 / 1 / 44 of 45 | 0 / 1 / 44 of 45 |
| 12 | 20 / 24 / 1 of 45 | 16 / 5 / 24 of 45 | 15 / 5 / 25 of 45 |
| 24 | 20 / 24 / 1 of 45 | 19 / 0 / 26 of 45 | 19 / 0 / 26 of 45 |
| 48 | 20 / 24 / 1 of 45 | 19 / 0 / 26 of 45 | 19 / 0 / 26 of 45 |

#### HELD-OUT FOR v1.1 (base 3931910000) -- in-catalog control, family LEFT IN (equal cap, COST_UNMATCHED)

| budget | arm | correct identification [Wilson 95%] | indistinguishable alternative | force-fit / false discovery | false null | no claim | abstention reasons | stage-1 proposals | realized cost mean / median / p10-p90 / min-max |
|---|---|---|---|---|---|---|---|---|---|
| 8 | B2 | 162/240 [0.613, 0.731] | 0/240 [0.000, 0.016] | 1/240 [0.001, 0.023] | 2 | 75 | STOPPED_INSUFFICIENT_VALIDATION 75 | 0 | 6.52 / 7 / 3-8 / 3-8 |
| 8 | B3 | 61/240 [0.203, 0.313] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 1 | 178 | ADEQUACY_UNVERIFIED 100; NO_ENGINE_CLAIM:STOPPED_INSUFFICIENT_VALIDATION 75; CLAIM_INADEQUATE 2; ... | 1 | 7.93 / 8 / 8-8 / 7-8 |
| 8 | B4 | 61/240 [0.203, 0.313] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 1 | 178 | ADEQUACY_UNVERIFIED 99; NO_ENGINE_CLAIM:STOPPED_INSUFFICIENT_VALIDATION 75; CLAIM_INADEQUATE 3; ... | 1 | 7.91 / 8 / 8-8 / 3-8 |
| 12 | B2 | 211/240 [0.832, 0.914] | 0/240 [0.000, 0.016] | 1/240 [0.001, 0.023] | 3 | 25 | STOPPED_INSUFFICIENT_VALIDATION 25 | 0 | 7.61 / 7.5 / 3-12 / 3-12 |
| 12 | B3 | 160/240 [0.605, 0.723] | 0/240 [0.000, 0.016] | 1/240 [0.001, 0.023] | 3 | 76 | ADEQUACY_UNVERIFIED 48; NO_ENGINE_CLAIM:STOPPED_INSUFFICIENT_VALIDATION 25; CLAIM_INADEQUATE 2; ... | 1 | 11.81 / 12 / 11-12 / 11-12 |
| 12 | B4 | 156/240 [0.588, 0.708] | 0/240 [0.000, 0.016] | 1/240 [0.001, 0.023] | 3 | 80 | ADEQUACY_UNVERIFIED 49; NO_ENGINE_CLAIM:STOPPED_INSUFFICIENT_VALIDATION 25; CLAIM_INADEQUATE 5; ... | 1 | 11.77 / 12 / 11-12 / 3-12 |
| 24 | B2 | 236/240 [0.958, 0.994] | 0/240 [0.000, 0.016] | 1/240 [0.001, 0.023] | 3 | 0 |  | 0 | 8.06 / 7.5 / 3-13 / 3-21 |
| 24 | B3 | 234/240 [0.947, 0.989] | 0/240 [0.000, 0.016] | 1/240 [0.001, 0.023] | 0 | 5 | CLAIM_INADEQUATE 3; ADEQUACY_UNVERIFIED 2 | 0 | 21.45 / 21 / 19-24 / 17-24 |
| 24 | B4 | 229/240 [0.920, 0.974] | 0/240 [0.000, 0.016] | 1/240 [0.001, 0.023] | 0 | 10 | CLAIM_INADEQUATE 8; ADEQUACY_UNVERIFIED 2 | 0 | 21.22 / 21 / 19-24 / 3-24 |
| 48 | B2 | 236/240 [0.958, 0.994] | 0/240 [0.000, 0.016] | 1/240 [0.001, 0.023] | 3 | 0 |  | 0 | 8.06 / 7.5 / 3-13 / 3-21 |
| 48 | B3 | 236/240 [0.958, 0.994] | 0/240 [0.000, 0.016] | 1/240 [0.001, 0.023] | 0 | 3 | CLAIM_INADEQUATE 3 | 0 | 22.46 / 21 / 19-27 / 17-35 |
| 48 | B4 | 231/240 [0.930, 0.980] | 0/240 [0.000, 0.016] | 1/240 [0.001, 0.023] | 0 | 8 | CLAIM_INADEQUATE 8 | 0 | 22.21 / 21 / 19-27 / 3-35 |

#### HELD-OUT FOR v1.1 benchmark world kinds (base 3320367000, 200 worlds) (equal cap, COST_UNMATCHED)

| budget | arm | correct identification [Wilson 95%] | indistinguishable alternative | force-fit / false discovery | false null | no claim | abstention reasons | stage-1 proposals | realized cost mean / median / p10-p90 / min-max |
|---|---|---|---|---|---|---|---|---|---|
| 8 | B2 | 106/200 [0.461, 0.598] | 0/200 [0.000, 0.019] | 8/200 [0.020, 0.077] | 0 | 86 | STOPPED_INSUFFICIENT_VALIDATION 59; STOPPED_UNEXPLAINED 27 | 0 | 6.34 / 7 / 3-8 / 3-8 |
| 8 | B3 | 47/200 [0.182, 0.298] | 0/200 [0.000, 0.019] | 1/200 [0.001, 0.028] | 0 | 152 | ADEQUACY_UNVERIFIED 64; NO_ENGINE_CLAIM:STOPPED_INSUFFICIENT_VALIDATION 59; NO_ENGINE_CLAIM:STOPPED_UNEXPLAINED 27; ... | 27 | 7.71 / 8 / 6-8 / 6-8 |
| 8 | B4 | 47/200 [0.182, 0.298] | 0/200 [0.000, 0.019] | 1/200 [0.001, 0.028] | 0 | 152 | ADEQUACY_UNVERIFIED 64; NO_ENGINE_CLAIM:STOPPED_INSUFFICIENT_VALIDATION 59; NO_ENGINE_CLAIM:STOPPED_UNEXPLAINED 27; ... | 27 | 7.71 / 8 / 6-8 / 6-8 |
| 12 | B2 | 144/200 [0.654, 0.778] | 0/200 [0.000, 0.019] | 8/200 [0.020, 0.077] | 0 | 48 | STOPPED_UNEXPLAINED 26; STOPPED_INSUFFICIENT_VALIDATION 22 | 0 | 7.44 / 7 / 3-12 / 3-12 |
| 12 | B3 | 108/200 [0.471, 0.608] | 0/200 [0.000, 0.019] | 2/200 [0.003, 0.036] | 0 | 90 | ADEQUACY_UNVERIFIED 36; NO_ENGINE_CLAIM:STOPPED_UNEXPLAINED 26; NO_ENGINE_CLAIM:STOPPED_INSUFFICIENT_VALIDATION 22; ... | 26 | 11.15 / 12 / 6-12 / 6-12 |
| 12 | B4 | 107/200 [0.466, 0.603] | 0/200 [0.000, 0.019] | 2/200 [0.003, 0.036] | 0 | 91 | ADEQUACY_UNVERIFIED 36; NO_ENGINE_CLAIM:STOPPED_UNEXPLAINED 26; NO_ENGINE_CLAIM:STOPPED_INSUFFICIENT_VALIDATION 22; ... | 27 | 11.15 / 12 / 6-12 / 6-12 |
| 24 | B2 | 164/200 [0.761, 0.867] | 0/200 [0.000, 0.019] | 8/200 [0.020, 0.077] | 0 | 28 | STOPPED_UNEXPLAINED 26; STOPPED_INSUFFICIENT_VALIDATION 2 | 0 | 8.03 / 7 / 3-13 / 3-24 |
| 24 | B3 | 164/200 [0.761, 0.867] | 0/200 [0.000, 0.019] | 3/200 [0.005, 0.043] | 0 | 33 | NO_ENGINE_CLAIM:STOPPED_UNEXPLAINED 26; CLAIM_INADEQUATE 5; NO_ENGINE_CLAIM:STOPPED_INSUFFICIENT_VALIDATION 2 | 26 | 18.95 / 21 / 6-24 / 6-24 |
| 24 | B4 | 164/200 [0.761, 0.867] | 0/200 [0.000, 0.019] | 2/200 [0.003, 0.036] | 0 | 34 | NO_ENGINE_CLAIM:STOPPED_UNEXPLAINED 26; CLAIM_INADEQUATE 6; NO_ENGINE_CLAIM:STOPPED_INSUFFICIENT_VALIDATION 2 | 26 | 18.95 / 21 / 6-24 / 6-24 |
| 48 | B2 | 166/200 [0.772, 0.876] | 0/200 [0.000, 0.019] | 8/200 [0.020, 0.077] | 0 | 26 | STOPPED_UNEXPLAINED 26 | 0 | 8.10 / 7 / 3-13 / 3-36 |
| 48 | B3 | 166/200 [0.772, 0.876] | 0/200 [0.000, 0.019] | 3/200 [0.005, 0.043] | 0 | 31 | NO_ENGINE_CLAIM:STOPPED_UNEXPLAINED 26; CLAIM_INADEQUATE 5 | 26 | 20.10 / 21 / 6-27 / 6-48 |
| 48 | B4 | 166/200 [0.772, 0.876] | 0/200 [0.000, 0.019] | 2/200 [0.003, 0.036] | 0 | 32 | NO_ENGINE_CLAIM:STOPPED_UNEXPLAINED 26; CLAIM_INADEQUATE 6 | 26 | 20.11 / 21 / 6-27 / 6-48 |


**How to read the new held-out results.**
- With the family removed, B4's force-fits are ≤ B3's at every budget: 0 vs 0, 4 vs 6, 3 vs 4 and
  2 vs 3. Its false nulls are also ≤ B3's: 6 vs 7, 8 vs 9, 3 vs 8 and 4 vs 8.
- These differences are small, and every one of them lies inside the other arm's Wilson interval.
- B4's realized cost is the same as B3's to within 0.03 units on average.
- With the family left in (the control), B4 identifies the truth correctly 0, 4, 5 and 5 fewer times
  than B3 at budgets 8, 12, 24 and 48. Neither arm made any indistinguishable-alternative claims,
  and the false discoveries are equal.
- On the benchmark world kinds, B4 equals B3 in correct identifications (−1 at budget 12) and has
  one fewer false discovery at 24 and 48.

### 4.2 Equal caps are not equal costs: realized-cost checkpoints

All the tables above are **EQUAL_CAP comparisons and are COST_UNMATCHED**. At the same cap the safe
arms spend more than B2: for example, mean realized cost at budget 24 in the control is 21.2–21.5
units for B3/B4 against 8.1 for B2. "B2 at cap 24" is therefore not a matched comparison with
"B4 at cap 24".

**Checkpoint method.**
- The pre-registered ladder is checkpoints at 25%, 50% and 100% of each cap.
- An arm's answer at checkpoint c is the last answer it committed while its cumulative charge was
  ≤ c. Each experiment is charged in full when it starts.
- **None of the three arms produces anytime answers.** The frozen engine's `investigate` returns a
  single result at its end: it has no per-step hook, and its `StepRecord`s carry no interim claim.
  Both gates decide once, after the engine. An answer is therefore committed only at termination.
  At checkpoint c it counts when the run's whole realized cost is ≤ c; otherwise the run has
  `NO_ANSWER_COMMITTED`. This is exact, not estimated.
- **What is missing:** how an arm *would* have answered had it been stopped at c. Answering that
  needs an anytime hook in the frozen engine, which this work may not add. Any comparison that would
  need it is **COST_UNMATCHED**, and none is reported.
- At 100% of the cap every run has committed, so the checkpoint table equals the equal-cap table.

**What the checkpoints show.** At every intermediate checkpoint B2 has committed many force-fits.
B3 and B4 have committed almost none, because they have committed almost nothing yet. For example,
at 50% of cap 48 (24 units), B2 has 95 force-fits while B3 and B4 have 2 each, with 12–13 runs
still uncommitted. On the control, B2 commits 209 correct identifications by 12 units, and the safe
arms commit 0 by 12 units. The safety arms buy their force-fit reduction partly by spending more
before answering.
#### HELD-OUT FOR v1.1 held-out (primary): committed FORCE-FITS -- realized-cost checkpoints (commit-at-termination)

| budget | checkpoint (units) | B2 FORCE_FIT / no answer yet | B3 FORCE_FIT / no answer yet | B4 FORCE_FIT / no answer yet |
|---|---|---|---|---|
| 8 | 0.25 (2) | 0 / 159 | 0 / 159 | 0 / 159 |
| 8 | 0.5 (4) | 17 / 137 | 0 / 153 | 0 / 153 |
| 8 | 1 (8) | 65 / 0 | 0 / 0 | 0 / 0 |
| 12 | 0.25 (3) | 2 / 157 | 0 / 159 | 0 / 159 |
| 12 | 0.5 (6) | 59 / 69 | 0 / 131 | 0 / 131 |
| 12 | 1 (12) | 80 / 0 | 6 / 0 | 4 / 0 |
| 24 | 0.25 (6) | 59 / 69 | 0 / 131 | 0 / 131 |
| 24 | 0.5 (12) | 79 / 31 | 0 / 72 | 0 / 72 |
| 24 | 1 (24) | 95 / 0 | 4 / 0 | 3 / 0 |
| 48 | 0.25 (12) | 79 / 31 | 0 / 72 | 0 / 72 |
| 48 | 0.5 (24) | 95 / 3 | 2 / 12 | 2 / 13 |
| 48 | 1 (48) | 96 / 0 | 3 / 0 | 2 / 0 |

#### HELD-OUT FOR v1.1 control: committed CORRECT IDENTIFICATIONS -- realized-cost checkpoints (commit-at-termination)

| budget | checkpoint (units) | B2 CORRECT_IDENTIFICATION / no answer yet | B3 CORRECT_IDENTIFICATION / no answer yet | B4 CORRECT_IDENTIFICATION / no answer yet |
|---|---|---|---|---|
| 8 | 0.25 (2) | 0 / 240 | 0 / 240 | 0 / 240 |
| 8 | 0.5 (4) | 38 / 201 | 0 / 240 | 0 / 239 |
| 8 | 1 (8) | 162 / 0 | 61 / 0 | 61 / 0 |
| 12 | 0.25 (3) | 30 / 210 | 0 / 240 | 0 / 239 |
| 12 | 0.5 (6) | 93 / 146 | 0 / 240 | 0 / 239 |
| 12 | 1 (12) | 211 / 0 | 160 / 0 | 156 / 0 |
| 24 | 0.25 (6) | 93 / 146 | 0 / 240 | 0 / 239 |
| 24 | 0.5 (12) | 209 / 27 | 0 / 240 | 0 / 237 |
| 24 | 1 (24) | 236 / 0 | 234 / 0 | 229 / 0 |
| 48 | 0.25 (12) | 209 / 27 | 0 / 240 | 0 / 237 |
| 48 | 0.5 (24) | 236 / 0 | 192 / 44 | 189 / 42 |
| 48 | 1 (48) | 236 / 0 | 236 / 0 | 231 / 0 |


### 4.3 Previously inspected evaluation sets (NOT held-out for v1.1)

The P3 seeds (2026610200) and v1.0's new seeds (2026810400) were inspected before v1.1. They are
reported for continuity only and labelled `PREVIOUSLY_INSPECTED_NOT_HELD_OUT_FOR_V1_1`. They were
never used to design or tune v1.1. On each set, v1.0's recorded B2 and B3 digests were reproduced
**1920/1920** before anything was reported.

Force-fits (primary worlds, family removed) at budgets 8/12/24/48:

| Set | B2 | B3 | B4 |
|---|---|---|---|
| P3 seeds | 60, 78, 92, 94 | 0, 9, 5, 4 | 0, 6, 4, 3 |
| v1.0-new seeds | 63, 79, 88, 90 | 0, 11, 7, 7 | 0, 9, 7, 7 |

The full tables follow.
#### PREVIOUSLY INSPECTED (base 2026610200; NOT held-out for v1.1) -- family REMOVED (primary, non-aliased worlds; equal cap, COST_UNMATCHED)

| budget | arm | force-fit [Wilson 95%] | false null | correct identification | no claim (abstain) | abstention reasons | realized cost mean / median / p10-p90 / min-max |
|---|---|---|---|---|---|---|---|
| 8 | B2 | 60/195 [0.247, 0.376] | 9/195 [0.025, 0.085] | 0 (impossible) | 126/195 [0.577, 0.710] | STOPPED_UNEXPLAINED 68; STOPPED_INSUFFICIENT_VALIDATION 58 | 5.50 / 6 / 2-8 / 2-8 |
| 8 | B3 | 0/195 [0.000, 0.019] | 6/195 [0.014, 0.066] | 0 (impossible) | 189/195 [0.934, 0.986] | NO_ENGINE_CLAIM:STOPPED_UNEXPLAINED 68; NO_ENGINE_CLAIM:STOPPED_INSUFFICIENT_VALIDATION 58; ADEQUACY_UNVERIFIED 26; CATALOG_INCOMPLETE 16; ... | 6.29 / 8 / 2-8 / 2-8 |
| 8 | B4 | 0/195 [0.000, 0.019] | 6/195 [0.014, 0.066] | 0 (impossible) | 189/195 [0.934, 0.986] | NO_ENGINE_CLAIM:STOPPED_UNEXPLAINED 68; NO_ENGINE_CLAIM:STOPPED_INSUFFICIENT_VALIDATION 58; ADEQUACY_UNVERIFIED 25; CATALOG_INCOMPLETE 16; ... | 6.29 / 8 / 2-8 / 2-8 |
| 12 | B2 | 78/195 [0.334, 0.470] | 17/195 [0.055, 0.135] | 0 (impossible) | 100/195 [0.443, 0.582] | STOPPED_UNEXPLAINED 70; STOPPED_INSUFFICIENT_VALIDATION 30 | 6.56 / 6 / 2-12 / 2-12 |
| 12 | B3 | 9/195 [0.025, 0.085] | 6/195 [0.014, 0.066] | 0 (impossible) | 180/195 [0.877, 0.953] | NO_ENGINE_CLAIM:STOPPED_UNEXPLAINED 70; CATALOG_INCOMPLETE 42; NO_ENGINE_CLAIM:STOPPED_INSUFFICIENT_VALIDATION 30; CATALOG_INCOMPLETE_UNREPLICATED 16; ... | 8.25 / 10 / 2-12 / 2-12 |
| 12 | B4 | 6/195 [0.014, 0.066] | 6/195 [0.014, 0.066] | 0 (impossible) | 183/195 [0.895, 0.965] | NO_ENGINE_CLAIM:STOPPED_UNEXPLAINED 70; CATALOG_INCOMPLETE 43; NO_ENGINE_CLAIM:STOPPED_INSUFFICIENT_VALIDATION 30; CATALOG_INCOMPLETE_UNREPLICATED 18; ... | 8.25 / 10 / 2-12 / 2-12 |
| 24 | B2 | 92/195 [0.403, 0.542] | 25/195 [0.088, 0.182] | 0 (impossible) | 78/195 [0.334, 0.470] | STOPPED_UNEXPLAINED 73; STOPPED_INSUFFICIENT_VALIDATION 5 | 7.56 / 6 / 2-16 / 2-24 |
| 24 | B3 | 5/195 [0.011, 0.059] | 3/195 [0.005, 0.044] | 0 (impossible) | 187/195 [0.921, 0.979] | CATALOG_INCOMPLETE 93; NO_ENGINE_CLAIM:STOPPED_UNEXPLAINED 73; CLAIM_INADEQUATE 12; NO_ENGINE_CLAIM:STOPPED_INSUFFICIENT_VALIDATION 5; ... | 10.82 / 10 / 2-22 / 2-24 |
| 24 | B4 | 4/195 [0.008, 0.051] | 1/195 [0.001, 0.029] | 0 (impossible) | 190/195 [0.941, 0.989] | CATALOG_INCOMPLETE 94; NO_ENGINE_CLAIM:STOPPED_UNEXPLAINED 73; CLAIM_INADEQUATE 12; NO_ENGINE_CLAIM:STOPPED_INSUFFICIENT_VALIDATION 5; ... | 10.85 / 10 / 2-22 / 2-24 |
| 48 | B2 | 94/195 [0.413, 0.552] | 28/195 [0.101, 0.200] | 0 (impossible) | 73/195 [0.309, 0.444] | STOPPED_UNEXPLAINED 73 | 7.76 / 6 / 2-16 / 2-42 |
| 48 | B3 | 4/195 [0.008, 0.051] | 2/195 [0.003, 0.037] | 0 (impossible) | 189/195 [0.934, 0.986] | CATALOG_INCOMPLETE 103; NO_ENGINE_CLAIM:STOPPED_UNEXPLAINED 73; CLAIM_INADEQUATE 12; CATALOG_INCOMPLETE_UNREPLICATED 1 | 11.20 / 10 / 2-22 / 2-44 |
| 48 | B4 | 3/195 [0.005, 0.044] | 0/195 [0.000, 0.019] | 0 (impossible) | 192/195 [0.956, 0.995] | CATALOG_INCOMPLETE 105; NO_ENGINE_CLAIM:STOPPED_UNEXPLAINED 73; CLAIM_INADEQUATE 12; CATALOG_INCOMPLETE_UNREPLICATED 2 | 11.24 / 10 / 2-23 / 2-44 |

Aliased worlds (truth inseparable from a reduced-catalog hypothesis): indistinguishable-alternative (surrogate) claims / other claims / no claim

| budget | B2 | B3 | B4 |
|---|---|---|---|
| 8 | 11 / 16 / 18 of 45 | 0 / 0 / 45 of 45 | 0 / 0 / 45 of 45 |
| 12 | 22 / 18 / 5 of 45 | 12 / 2 / 31 of 45 | 12 / 2 / 31 of 45 |
| 24 | 24 / 20 / 1 of 45 | 23 / 1 / 21 of 45 | 23 / 1 / 21 of 45 |
| 48 | 24 / 20 / 1 of 45 | 23 / 1 / 21 of 45 | 23 / 1 / 21 of 45 |

#### PREVIOUSLY INSPECTED (base 2026610200) -- control (equal cap, COST_UNMATCHED)

| budget | arm | correct identification [Wilson 95%] | indistinguishable alternative | force-fit / false discovery | false null | no claim | abstention reasons | stage-1 proposals | realized cost mean / median / p10-p90 / min-max |
|---|---|---|---|---|---|---|---|---|---|
| 8 | B2 | 158/240 [0.596, 0.715] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 0 | 82 | STOPPED_INSUFFICIENT_VALIDATION 82 | 0 | 6.52 / 7 / 3-8 / 3-8 |
| 8 | B3 | 63/240 [0.211, 0.322] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 0 | 177 | ADEQUACY_UNVERIFIED 95; NO_ENGINE_CLAIM:STOPPED_INSUFFICIENT_VALIDATION 82 | 0 | 7.93 / 8 / 8-8 / 7-8 |
| 8 | B4 | 63/240 [0.211, 0.322] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 0 | 177 | ADEQUACY_UNVERIFIED 95; NO_ENGINE_CLAIM:STOPPED_INSUFFICIENT_VALIDATION 82 | 0 | 7.93 / 8 / 8-8 / 7-8 |
| 12 | B2 | 218/240 [0.865, 0.939] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 1 | 21 | STOPPED_INSUFFICIENT_VALIDATION 21 | 0 | 7.67 / 8 / 3-12 / 3-12 |
| 12 | B3 | 153/240 [0.575, 0.696] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 1 | 86 | ADEQUACY_UNVERIFIED 64; NO_ENGINE_CLAIM:STOPPED_INSUFFICIENT_VALIDATION 21; CATALOG_INCOMPLETE 1 | 1 | 11.83 / 12 / 11-12 / 11-12 |
| 12 | B4 | 152/240 [0.571, 0.692] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 0 | 88 | ADEQUACY_UNVERIFIED 65; NO_ENGINE_CLAIM:STOPPED_INSUFFICIENT_VALIDATION 21; CATALOG_INCOMPLETE 1; ... | 1 | 11.83 / 12 / 11-12 / 11-12 |
| 24 | B2 | 238/240 [0.970, 0.998] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 2 | 0 |  | 0 | 7.93 / 8 / 3-12 / 3-19 |
| 24 | B3 | 236/240 [0.958, 0.994] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 1 | 3 | CATALOG_INCOMPLETE 1; CATALOG_INCOMPLETE_UNREPLICATED 1; CLAIM_INADEQUATE 1 | 2 | 21.38 / 21 / 19-24 / 12-24 |
| 24 | B4 | 235/240 [0.952, 0.991] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 1 | 4 | CLAIM_INADEQUATE 2; CATALOG_INCOMPLETE 1; CATALOG_INCOMPLETE_UNREPLICATED 1 | 2 | 21.38 / 21 / 19-24 / 12-24 |
| 48 | B2 | 238/240 [0.970, 0.998] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 2 | 0 |  | 0 | 7.93 / 8 / 3-12 / 3-19 |
| 48 | B3 | 237/240 [0.964, 0.996] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 1 | 2 | CATALOG_INCOMPLETE 1; CLAIM_INADEQUATE 1 | 1 | 22.21 / 21 / 19-27 / 12-36 |
| 48 | B4 | 237/240 [0.964, 0.996] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 1 | 2 | CATALOG_INCOMPLETE 1; CLAIM_INADEQUATE 1 | 1 | 22.23 / 21 / 19-27 / 12-36 |

#### PREVIOUSLY INSPECTED (base 2026810400; NOT held-out for v1.1) -- family REMOVED (primary, non-aliased worlds; equal cap, COST_UNMATCHED)

| budget | arm | force-fit [Wilson 95%] | false null | correct identification | no claim (abstain) | abstention reasons | realized cost mean / median / p10-p90 / min-max |
|---|---|---|---|---|---|---|---|
| 8 | B2 | 63/195 [0.261, 0.392] | 8/195 [0.021, 0.079] | 0 (impossible) | 124/195 [0.566, 0.700] | STOPPED_UNEXPLAINED 75; STOPPED_INSUFFICIENT_VALIDATION 49 | 5.38 / 6 / 2-8 / 2-8 |
| 8 | B3 | 0/195 [0.000, 0.019] | 4/195 [0.008, 0.051] | 0 (impossible) | 191/195 [0.949, 0.992] | NO_ENGINE_CLAIM:STOPPED_UNEXPLAINED 75; NO_ENGINE_CLAIM:STOPPED_INSUFFICIENT_VALIDATION 49; ADEQUACY_UNVERIFIED 24; CATALOG_INCOMPLETE_UNREPLICATED 18; ... | 6.22 / 7 / 2-8 / 2-8 |
| 8 | B4 | 0/195 [0.000, 0.019] | 3/195 [0.005, 0.044] | 0 (impossible) | 192/195 [0.956, 0.995] | NO_ENGINE_CLAIM:STOPPED_UNEXPLAINED 75; NO_ENGINE_CLAIM:STOPPED_INSUFFICIENT_VALIDATION 49; CATALOG_INCOMPLETE_UNREPLICATED 20; ADEQUACY_UNVERIFIED 19; ... | 6.22 / 7 / 2-8 / 2-8 |
| 12 | B2 | 79/195 [0.339, 0.475] | 19/195 [0.063, 0.147] | 0 (impossible) | 97/195 [0.428, 0.567] | STOPPED_UNEXPLAINED 76; STOPPED_INSUFFICIENT_VALIDATION 21 | 6.24 / 6 / 2-12 / 2-12 |
| 12 | B3 | 11/195 [0.032, 0.098] | 9/195 [0.025, 0.085] | 0 (impossible) | 175/195 [0.847, 0.933] | NO_ENGINE_CLAIM:STOPPED_UNEXPLAINED 76; CATALOG_INCOMPLETE 44; NO_ENGINE_CLAIM:STOPPED_INSUFFICIENT_VALIDATION 21; CLAIM_INADEQUATE 13; ... | 7.95 / 9 / 2-12 / 2-12 |
| 12 | B4 | 9/195 [0.025, 0.085] | 7/195 [0.018, 0.072] | 0 (impossible) | 179/195 [0.871, 0.949] | NO_ENGINE_CLAIM:STOPPED_UNEXPLAINED 76; CATALOG_INCOMPLETE 47; NO_ENGINE_CLAIM:STOPPED_INSUFFICIENT_VALIDATION 21; CATALOG_INCOMPLETE_UNREPLICATED 14; ... | 7.94 / 9 / 2-12 / 2-12 |
| 24 | B2 | 88/195 [0.383, 0.521] | 25/195 [0.088, 0.182] | 0 (impossible) | 82/195 [0.353, 0.491] | STOPPED_UNEXPLAINED 77; STOPPED_INSUFFICIENT_VALIDATION 5 | 6.88 / 6 / 2-13 / 2-24 |
| 24 | B3 | 7/195 [0.018, 0.072] | 6/195 [0.014, 0.066] | 0 (impossible) | 182/195 [0.889, 0.961] | CATALOG_INCOMPLETE 83; NO_ENGINE_CLAIM:STOPPED_UNEXPLAINED 77; CLAIM_INADEQUATE 13; NO_ENGINE_CLAIM:STOPPED_INSUFFICIENT_VALIDATION 5; ... | 10.13 / 9 / 2-21 / 2-24 |
| 24 | B4 | 7/195 [0.018, 0.072] | 3/195 [0.005, 0.044] | 0 (impossible) | 185/195 [0.908, 0.972] | CATALOG_INCOMPLETE 87; NO_ENGINE_CLAIM:STOPPED_UNEXPLAINED 77; CLAIM_INADEQUATE 11; CATALOG_INCOMPLETE_UNREPLICATED 5; ... | 10.11 / 9 / 2-21 / 2-24 |
| 48 | B2 | 90/195 [0.393, 0.532] | 27/195 [0.097, 0.194] | 0 (impossible) | 78/195 [0.334, 0.470] | STOPPED_UNEXPLAINED 78 | 7.07 / 6 / 2-13 / 2-41 |
| 48 | B3 | 7/195 [0.018, 0.072] | 6/195 [0.014, 0.066] | 0 (impossible) | 182/195 [0.889, 0.961] | CATALOG_INCOMPLETE 89; NO_ENGINE_CLAIM:STOPPED_UNEXPLAINED 78; CLAIM_INADEQUATE 13; CATALOG_INCOMPLETE_UNREPLICATED 2 | 10.48 / 9 / 2-21 / 2-45 |
| 48 | B4 | 7/195 [0.018, 0.072] | 3/195 [0.005, 0.044] | 0 (impossible) | 185/195 [0.908, 0.972] | CATALOG_INCOMPLETE 94; NO_ENGINE_CLAIM:STOPPED_UNEXPLAINED 78; CLAIM_INADEQUATE 11; CATALOG_INCOMPLETE_UNREPLICATED 2 | 10.47 / 9 / 2-21 / 2-45 |

Aliased worlds (truth inseparable from a reduced-catalog hypothesis): indistinguishable-alternative (surrogate) claims / other claims / no claim

| budget | B2 | B3 | B4 |
|---|---|---|---|
| 8 | 11 / 21 / 13 of 45 | 0 / 1 / 44 of 45 | 0 / 1 / 44 of 45 |
| 12 | 21 / 24 / 0 of 45 | 12 / 8 / 25 of 45 | 12 / 7 / 26 of 45 |
| 24 | 21 / 24 / 0 of 45 | 20 / 3 / 22 of 45 | 20 / 1 / 24 of 45 |
| 48 | 21 / 24 / 0 of 45 | 20 / 3 / 22 of 45 | 20 / 1 / 24 of 45 |

#### PREVIOUSLY INSPECTED (base 2026810400) -- control (equal cap, COST_UNMATCHED)

| budget | arm | correct identification [Wilson 95%] | indistinguishable alternative | force-fit / false discovery | false null | no claim | abstention reasons | stage-1 proposals | realized cost mean / median / p10-p90 / min-max |
|---|---|---|---|---|---|---|---|---|---|
| 8 | B2 | 153/240 [0.575, 0.696] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 3 | 84 | STOPPED_INSUFFICIENT_VALIDATION 84 | 0 | 6.53 / 7 / 3-8 / 3-8 |
| 8 | B3 | 65/240 [0.218, 0.330] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 1 | 174 | ADEQUACY_UNVERIFIED 87; NO_ENGINE_CLAIM:STOPPED_INSUFFICIENT_VALIDATION 84; CLAIM_INADEQUATE 2; ... | 1 | 7.94 / 8 / 8-8 / 7-8 |
| 8 | B4 | 64/240 [0.215, 0.326] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 1 | 175 | ADEQUACY_UNVERIFIED 87; NO_ENGINE_CLAIM:STOPPED_INSUFFICIENT_VALIDATION 84; CLAIM_INADEQUATE 2; ... | 2 | 7.94 / 8 / 8-8 / 7-8 |
| 12 | B2 | 214/240 [0.846, 0.925] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 5 | 21 | STOPPED_INSUFFICIENT_VALIDATION 21 | 0 | 7.74 / 8 / 3-12 / 3-12 |
| 12 | B3 | 151/240 [0.567, 0.688] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 5 | 84 | ADEQUACY_UNVERIFIED 63; NO_ENGINE_CLAIM:STOPPED_INSUFFICIENT_VALIDATION 21 | 0 | 11.85 / 12 / 11-12 / 11-12 |
| 12 | B4 | 149/240 [0.558, 0.680] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 4 | 87 | ADEQUACY_UNVERIFIED 63; NO_ENGINE_CLAIM:STOPPED_INSUFFICIENT_VALIDATION 21; CATALOG_INCOMPLETE 1; ... | 2 | 11.82 / 12 / 11-12 / 8-12 |
| 24 | B2 | 235/240 [0.952, 0.991] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 5 | 0 |  | 0 | 8.09 / 8 / 3-13 / 3-22 |
| 24 | B3 | 234/240 [0.947, 0.989] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 2 | 4 | CLAIM_INADEQUATE 3; ADEQUACY_UNVERIFIED 1 | 0 | 21.38 / 21 / 19-24 / 19-24 |
| 24 | B4 | 233/240 [0.941, 0.986] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 1 | 6 | CLAIM_INADEQUATE 4; ADEQUACY_UNVERIFIED 1; CATALOG_INCOMPLETE 1 | 1 | 21.30 / 21 / 19-24 / 8-24 |
| 48 | B2 | 235/240 [0.952, 0.991] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 5 | 0 |  | 0 | 8.09 / 8 / 3-13 / 3-22 |
| 48 | B3 | 235/240 [0.952, 0.991] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 2 | 3 | CLAIM_INADEQUATE 3 | 0 | 22.48 / 21 / 19-27 / 19-38 |
| 48 | B4 | 234/240 [0.947, 0.989] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 1 | 5 | CLAIM_INADEQUATE 4; CATALOG_INCOMPLETE 1 | 1 | 22.39 / 21 / 19-27 / 8-38 |

## 5. Python-version-dependent reproducibility

**What could depend on the interpreter.**

| Source of variation | Assessment |
|---|---|
| Numerics | Every result is computed in pure Python. The engine's least squares and chi-square tail are its own (`discovery/numerics.py`, using `math` only); no numpy, scipy or other compiled numerics are imported. |
| Random draws | Worlds draw from `random.Random(f"…")`. Seeding a string uses version-2 seeding (SHA-512 of the string), and `random()`, `gauss()` and `randrange()` are unchanged across CPython 3.12/3.13. |
| Float formatting in digests | Digests hash floats as fixed six-decimal strings after rounding to six places. Evidence JSON is written with `sort_keys`. |
| Hash seeds and set/dict order | Every iteration that feeds a result runs over a list, a dict in insertion order, or a sorted collection. Set iteration over strings, whose order depends on PYTHONHASHSEED, never decides an order. |
| Dependencies | pydantic 2.14.2, pydantic-core 2.50.2, PyYAML 6.0.3 and cryptography 50.0.2 are recorded in the manifest's `environment` block. None of them enters a Discovery computation. |

The manifest's **hashed body therefore contains no interpreter detail**. The interpreter, platform and
dependency versions sit in an `environment` block outside the hash.

**What was verified, by execution:**

1. The evidence was written under CPython 3.13.18 (local).
2. `--check` under **CPython 3.12.3**, with the same dependency versions and the default
   (randomised) hash seed, reproduced **every evidence file byte for byte**: 11 data files plus the
   manifest's hashed body. It still **refused with `INTERPRETER MISMATCH` (exit 2)**, because 3.12
   was not yet recorded as verified. This is the explicit refusal the check is designed to give.
3. `--check --record-interpreter` under 3.12.3 matched again and recorded CPython 3.12 in
   `evidence/interpreter_verification.json`.
4. `--check` under CPython 3.13 with `PYTHONHASHSEED=12345` reproduced every file: RESULT_HS.

**Strictness is kept.**
- Any byte difference in any evidence file, or in the manifest's hashed body, gives `STALE` (exit 1).
  When the interpreter also differs, the check adds an "INTERPRETER MISMATCH as well" note.
- An interpreter that is not recorded gives exit 2, even when every file matches.
- Nothing is ever accepted on a mismatch.
- CI runs CPython 3.12, which is now recorded as reproducing the evidence. The `--check` mode is not
  part of CI; the e2e test is interpreter-independent and checks content only.

**v1.0's evidence check (not modified).** By reading its code, without running it under 3.12:
`scripts/discovery_safety_eval.py --check` compares the whole manifest except `code_commit`, and that
includes `interpreter: "CPython 3.13.x"`. Under 3.12 it would therefore report
`manifest.json: differs` without naming the interpreter as the cause. The check fails, so it never
passes silently, but the message is unclear. This is recorded as a residual item. v1.0's script is
hash-frozen, so it was not changed.

## 6. Mutation check

Scope: **only the logic v1.1 adds**. That is eight `safety_v11_*` entries in
`scripts/mutation_battery.py` (additions only), each targeting a line in
`src/lab_brain/discovery_safety/v11/`. The whole repository was not mutated. Command:
`python scripts/mutation_battery.py --only <the eight names>`. Result: **8/8 killed**.

| Mutant | Killed by (first failing test) |
|---|---|
| `safety_v11_coverage_judged_at_the_pre_probe_fit` | `test_discovery_safety_v11_refit.py::test_v11_does_not_endorse_the_force_fit_the_refit_exposed` |
| `safety_v11_emerged_signal_probed_as_null` | `test_discovery_safety_v11_refit.py::test_an_emerged_signal_experiment_is_probed_before_any_null_one` |
| `safety_v11_localized_check_ignored` | `test_discovery_safety_v11_localized.py::test_v11_rejects_it_and_names_the_experiment_and_its_worst_observation` |
| `safety_v11_localized_check_uncorrected` (no Holm) | `test_discovery_safety_v11_localized.py::test_v11_rejects_it_and_names_the_experiment_and_its_worst_observation` |
| `safety_v11_localized_failure_replicated_before_probing` | `test_discovery_safety_v11_dev.py::test_a_deviation_confined_to_one_experiment_is_no_longer_endorsed` |
| `safety_v11_exclusion_ratchet_reopened` | `test_discovery_safety_v11_dev.py::test_one_experiment_cannot_be_excluded_as_noise_twice` |
| `safety_v11_checkpoint_counts_unfinished_runs` | `test_discovery_safety_v11_eval.py::test_a_checkpoint_counts_only_runs_whose_whole_cost_fits` |
| `safety_v11_proposal_counted_as_identification` | `test_discovery_safety_v11_eval.py::test_a_proposal_is_never_an_identification_and_the_summary_refuses_one` |

## 7. Limitations and residual risks

- **Same author lineage.** Worlds, held-out families, the engine and both gates share one author
  lineage. The "new held-out seeds" are new draws from the same generators, not new mechanisms.
- **Small, unresolved gains.** B4's force-fit reduction over B3 (2, 1 and 1 worlds of 195 at
  budgets 12, 24 and 48) is inside the Wilson intervals. It is not statistically established.
- **A measurable cost in the control.** In-catalog correct identifications fall by 4–5 of 240 at
  budgets 12–48 on the new seeds. These are abstentions (mostly CLAIM_INADEQUATE) caused by
  localized false alarms. Repeated adequacy testing during probing inflates the per-run false-alarm
  rate above the nominal 0.01.
- **Residual force-fits remain** (2–4 of 195 at budgets 12–48), mostly `leakage.substrate` claimed
  as `scatter.sidewall`. In those worlds the distinguishing experiment is barely resolved, or was
  never run within the budget.
- **No anytime answers.** Section 4.2 cannot say what an arm would answer if it were stopped early.
- **Thresholds were reused unchanged from v1.0.** No sensitivity sweep of `alpha_localized` was run
  on evaluation seeds. That is deliberate, because it would amount to tuning on them.
- **`max_noise_exclusions_per_experiment = 1`** can make a true claim abstain in a world with two
  independent glitches in one experiment.

## 8. Skipped items

- No anytime-answer comparison. The frozen engine has no hook for one; see §4.2.
- No re-run of v1.0's own `--check` under 3.12; see §5.

## 9. Owner decisions

- **DECIDED (Human Owner, 2026-11-04).** Keep the **STRICT** setting: `signal_coverage = 1.0`, so
  nothing is endorsed without verified adequacy. Lower in-catalog accuracy at low budgets is
  accepted in exchange for far fewer force-fits. This is the frozen default for v1.1. It is recorded
  in `SafetyProtocolV11`'s docstring, and it was not loosened to raise accuracy.
- **OPEN.**
  - Whether to adopt v1.1 over v1.0. v1.1 gives a modest force-fit and false-null reduction and
    closes the refit hole, at a cost of 4–5/240 in-catalog identifications.
  - The thresholds: `alpha_adequacy`, `alpha_localized`, the z thresholds, and the two new rules
    (`defer_localized_replication`, `max_noise_exclusions_per_experiment`).
  - The replication allowance.
  - Whether to commission an independent protocol: worlds and mechanisms authored outside this
    lineage.
  - Whether to fund an anytime-answer hook in a *new* engine version. Answering this needs the
    engine's freeze to be lifted.
  - Whether to update v1.0's `--check` so that it reports an interpreter mismatch explicitly.

## 10. Verification
