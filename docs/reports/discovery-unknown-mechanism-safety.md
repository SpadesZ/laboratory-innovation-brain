# Discovery: safe handling of unknown (out-of-catalog) mechanisms

Date: 2026-11-04. Branch: `claude/lib-implementation-agent-47evs0-discovery`, created from the P3
baseline `d7ec9f2f78f568c97b4ac1f785e13789fb3d7b77` (branch `discovery-independent-evaluation`).
Not pushed, not merged, not deployed.

> **ENGINEERING EVIDENCE ONLY.** Every world below is a developer-authored synthetic world. The
> held-out mechanism families were declared, by the same author lineage that wrote the engine and
> this safety gate, in the catalog the engine was developed against. Nothing here is independent
> scientific evidence, an independent or blind evaluation, or a statement about a real device.
> **Scientific acceptance: NOT PASSED. G-D: NOT PASSED.** `READY_FOR_REAL_RESEARCH` stays false.
> No model, paid call, simulator (no Lumerical), network, database write or real experiment was used.
> Discovery remains disconnected from the research flow.

Evidence (frozen, reproducible with `--check`):
[`docs/audit/discovery-unknown-mechanism-safety-2026-11-04/evidence/`](../audit/discovery-unknown-mechanism-safety-2026-11-04/evidence/),
produced by `scripts/discovery_safety_eval.py` at the final code commit `98c5ad9` (recorded in its
`manifest.json`; first generated at `0660c81`, re-bound after a type-only fix with every result file byte-identical).

---

## 1. Summary

| | P3 engine (B2) | Safe arm (B3, this branch) |
|---|---|---|
| Force-fit, true family absent, budget 12 (P3 seeds) | **78/195 = 0.400** | **9/195 = 0.046** |
| Force-fit, budget 24 (P3 seeds) | **92/195 = 0.472** | **5/195 = 0.026** |
| Force-fit, budget 48 (P3 seeds) | 94/195 = 0.482 | 4/195 = 0.021 |
| Force-fit, budget 12 / 24 / 48 (NEW seeds) | 79 / 88 / 90 of 195 | 11 / 7 / 7 of 195 |
| In-catalog accuracy (family left in), budget 12 (P3 seeds) | 218/240 = 0.908 | **153/240 = 0.637** |
| In-catalog accuracy, budget 24 (P3 seeds) | 238/240 = 0.992 | 236/240 = 0.983 |

- The P3 force-fit problem reproduces exactly (every run digest identical, 78 and 92 force-fits).
- The safe arm cuts force-fits by roughly a factor of ten at budgets 12, 24 and 48, on the frozen P3
  worlds and on new held-out worlds, and force-fits do **not** rise with budget from 12 upward.
- **The cost is real:** at small budgets (8 and 12) in-catalog accuracy falls sharply, because the
  safe arm will not endorse a claim whose predictions it could not afford to check. Those runs
  abstain with `ADEQUACY_UNVERIFIED` and a list of the experiments that would settle it -- they are
  not wrong answers, but they are not answers either. At budget 24 and above the cost disappears
  (236 vs 238 of 240). This trade-off is an **Owner decision** (§9).

## 2. Reproduction of the P3 force-fit problem

`scripts/discovery_safety_eval.py` first checks that the engine (`src/lab_brain/discovery/*.py` and
the ring catalog) and the P3 evaluation tooling (`src/lab_brain/discovery_eval/*.py`, the P3 script,
the example files) hash to their frozen manifests, then re-runs B2 through the frozen
`held_out.run_held_out` on the frozen P3 held-out worlds (base seed `2026610200`, 15 per class, 240
worlds, 195 primary) and compares with the recorded rows
(`evidence/reproduction.json`):

| Budget | Runs digest-identical to the P3 record | Force-fit (primary) | Recorded by P3 |
|---|---|---|---|
| 12 | 240/240 | 78/195 = 0.400 | 78 |
| 24 | 240/240 | 92/195 = 0.472 | 92 |

The P3 curve worlds (base seed `2026110200`) also reproduce: 1600/1600 B2 digests identical at caps
4..24. Offline, deterministic, no paid models.

## 3. Root cause

The decision code is `src/lab_brain/discovery/loop.py`, `_Investigation.next_action` (line 927):
when one distinguishable class is left (`if len(classes) == 1:`, line 962) and every member is
`supported` (line 271: passed `min_prospective_tests = 2` distinct "risky" experiments), and after
decisive replication and rival closure, it calls `self.conclude(classes[0])` (line 974) and the
result is `SURVIVING_PENDING_WARRANT_GATE`.

Every experiment that leads there is chosen relative to the **declared** hypotheses:

- `select` / `discrimination_utility` (lines 867 / 841) score an experiment by how well it separates
  pairs of declared live hypotheses;
- `risky` (line 246) and `prospective_test` (line 888) count a test as one the hypothesis "could have
  failed" when it separates it from the noise model or from another registered hypothesis;
- "passed" means "not refuted at alpha = 1e-3" (`fails`, line 349).

Nothing ever asks whether the survivor is **adequate on the experiments it was never run on**. When
the true family is absent, a surrogate that matches the truth on the two to four experiments the
engine happened to run survives and is claimed, while the experiment that would expose it is never
selected -- no declared rival is separated by it. It was usually affordable: in the P3 record, of the
78 force-fits at budget 12 the engine had spent 6.74 units on average and 60 left at least 3 units
unspent; at budget 24, 90 of 92 left at least 3 units. More budget made it worse (0.40 -> 0.47)
because widening found more surrogate compositions that fit the few experiments run.

A secondary finding, documented and **not** changed (the engine is frozen): the engine's
`SeparationOracle.classes` (`distinguish.py`, line 137) takes the transitive closure of pairwise
indistinguishability. Indistinguishability is not transitive (predictions 0, 0.75 and 1.5 with a
threshold of 1: A~B and B~C, yet A and C are distinguishable;
`tests/unit/test_discovery_safety_pairwise.py` shows the closure merging all three). The safety gate
never uses that closure.

## 4. Design

A new, versioned decision layer over the frozen engine (arm **B3**,
`lab_brain.discovery_safety.gate.safe_investigate`). The engine runs exactly as frozen; its own
result is kept untouched in `SafeRun.engine`. Then, before anything is endorsed:

1. **Adequacy probes.** Run the available experiments the claim was never tested on: first every
   experiment it *predicts a signal in* (an entry at least `z_signal = 3` sigma from zero at its
   fitted amplitudes), cheapest first, then the ones it predicts nothing in, while the budget lasts.
   A probe is a test the claim can fail whatever the rivals are.
2. **Pre-declared adequacy criterion, relative to the noise model.** Each claimed member is refitted
   to every admitted observation: adequate iff the chi-square p-value is at least
   `alpha_adequacy = 0.01` (ten times stricter than the engine's refutation alpha: endorsing asks for
   more than not-refuted) and no observation has an entry beyond `z_adequacy = 4` sigma (the engine's
   own anomaly threshold).
3. **Consistency across replicates.** A failure is replicated once (worst observation; at most
   `max_probe_replications = 2`). Inadequacy that persists without the original is *reproduced*; a
   replicate that fits attributes the original to noise and probing continues; no affordable
   replicate leaves it *unreplicated* (still not endorsed).
4. **Catalog completeness.** On inadequacy, every hypothesis the catalog expresses (the noise model,
   each class, each family pair -- distinct forward models only, a renamed duplicate counted once) is
   held to the same test. Some adequate: `CLAIM_INADEQUATE`. None: `CATALOG_INCOMPLETE` (or
   `CATALOG_INCOMPLETE_UNREPLICATED`).
5. **Decision.** Endorse (`ENDORSE_PENDING_WARRANT_GATE`, confidence `ADEQUATE`) only an adequate claim
   whose signal experiments were all run (`signal_coverage = 1.0`). Otherwise **ABSTAIN** -- never an
   automatic force-fit -- and leave what a person can act on:
   - (a) **abstention**: the scored result has no claim, no handover, an outcome outside
     `CLAIM_OUTCOMES` (`STOPPED_UNEXPLAINED` or `STOPPED_INSUFFICIENT_VALIDATION`), and the claimed
     records move to `STOPPED` with the reason;
   - (b) **unresolved anomalies**: an `UNEXPLAINED` anomaly record per observation outside the noise
     model under the claim's refit;
   - (c) **catalog incompleteness**: `catalog_incomplete`, `inadequacy_reproduced`,
     `adequate_alternatives`, `distinct_hypotheses_checked`;
   - (d) **new-family proposal** (catalog incomplete only): a `NewFamilyProposal` with
     `stage = STAGE_1_EXPLORATORY_IDEA`, `status = PROPOSAL_NOT_A_CLAIM`, a tabulated signature read off
     the residual means (entries at least 3 standard errors from zero), the observed nulls, the
     never-run experiments (where it predicts nothing), whether it fits the data it was read from,
     and the closest declared forward model; it never enters a claim, a handover or a score;
   - (e) **reframed question**: recorded as a `ReframingRecord` (`WIDEN_MECHANISM_SPACE` when the
     catalog is incomplete);
   - (f) **discriminating-experiment requests**, built **pairwise** (never through a chain): per pair of
     remaining candidates, the cheapest declared experiment whose one run separates them by at least
     `discriminating_tau = 5` sigma (worst case over amplitudes), else the most separating one with
     the number of replicates needed; between the proposal and each best-fitting declared
     hypothesis, the observed experiment whose replicate separates them most; for an unverified or
     single remaining candidate, the experiments it predicts a signal in and was never tested on.

Confidence is ordinal (`NONE` < `PROVISIONAL` < `ADEQUATE`), never a probability, and moves only on
discriminating evidence: `discriminating_tests_passed` counts **distinct** experiments against
**distinct** forward models, so replicates and renamed rivals add nothing.

**Why not change the engine.** `src/lab_brain/discovery/` and `src/lab_brain/discovery_eval/` are
frozen by the 2026-11-01 and 2026-11-02 manifests, which hash every file in those directories and
are enforced by tests. The gate is a separate package (`src/lab_brain/discovery_safety/`) that reads
them and changes neither. The **evaluator was not changed either**: the frozen `run_held_out`,
`run_full_catalog_control`, `curves.run_grid` and their scorers score B2 and B3 alike, so no evaluator
version was needed; the frozen evidence directories were not written.

**Thresholds were not tuned on the frozen test worlds.** `alpha_adequacy`, `z_adequacy`, `z_signal`,
`discriminating_tau` and the replicate allowance are the statistical defaults stated in
`SafetyProtocol` (and the engine's own anomaly / distinguishability thresholds). The probe order and
`signal_coverage = 1.0` (the only non-arbitrary values are 0 and 1: "every signal prediction checked")
were fixed on development seeds only -- held-out base seed `5000000` (6 worlds per class) and curve
base seed `1` -- before any evaluation seed in this report was run. The coverage alternatives in §7
were computed afterwards and are reported, not used to choose.

## 5. Implementation summary

| File | What |
|---|---|
| `src/lab_brain/discovery_safety/__init__.py` | package doc |
| `src/lab_brain/discovery_safety/model.py` | `SafetyProtocol` (hashed), decisions, abstention reasons, confidence, frozen records: `AdequacyTest`, `ProbeRecord`, `NewFamilyProposal`, `ExperimentRequest`, `SafetyAssessment`, `SafeRun` |
| `src/lab_brain/discovery_safety/pairwise.py` | non-transitive pairwise relations: `distinct_forward_models`, `indistinguishable_pairs`, `direct_neighbours` |
| `src/lab_brain/discovery_safety/gate.py` | `safe_investigate`, `safe_runner`, adequacy test, signal experiments, discriminating-test count, probes, replication, completeness, proposal, requests, decision |
| `src/lab_brain/discovery_safety/evaluation.py` | B3 recorder arm and summaries over the frozen evaluation tooling |
| `scripts/discovery_safety_eval.py` | composition root; writes and `--check`s the evidence |
| `pyproject.toml` | the §24.2 import-ban exemption for that one script (as for the two earlier discovery scripts) |
| `scripts/mutation_battery.py` | nine `safety_*` entries |
| `tests/unit/test_discovery_eval_governance.py` | the isolation test now also skips the sibling `discovery_safety` package when it lists engine importers (the product is still checked; the new package's own isolation test holds that nothing in the product imports it) |

## 6. Tests added

| File | Tests | Covers |
|---|---|---|
| `tests/unit/test_discovery_safety.py` | 31 (with parametrisation) | hidden families (6 worlds where the engine force-fits: abstain, never endorse), incompleteness detected and reproduced, development held-out worlds at budgets 12/24/48 (B2 force-fits >= 5, B3 0), confounder (laser drift mimicked by cladding drift: not endorsed; in-catalog confounded worlds: no false discovery), aliases (renamed duplicate changes no decision, confidence, probe or count beyond the one new pair table), replicates and renamed rivals do not raise `discriminating_tests_passed`, more budget never buys an endorsement of a surrogate, ADEQUATE only with full signal coverage, abstention well-formed (no claim/handover, open UNEXPLAINED anomaly, reframing, request, within budget, no CONFIRMED), engine result untouched, determinism, proposal stage-1 / residual means / fits / not in any claim, pairwise requests reach the threshold, single remaining candidate gets a prospective-test request, recovery by catalog extension and by affording the requested probes, positive control at budget 24, no added false discovery on in-catalog kinds, the null claim is probed too |
| `tests/unit/test_discovery_safety_pairwise.py` | 4 | the 0 / 0.75 / 1.5 counterexample: pairs kept, A and C never merged, the frozen closure differs, renamed duplicate is one model |
| `tests/unit/test_discovery_safety_governance.py` | 32 (with parametrisation) | no forbidden imports (domains, product, DB, network, clock, randomness), imports only the engine and the evaluation tooling, nothing in the product imports it, no CONFIRMED, stage-1 marker written once, frozen packages hold exactly their frozen files |
| `tests/e2e/test_discovery_safety_eval_frozen.py` | 7 | the evidence manifest froze these sources and this protocol; P3 force-fit reproduced (78, 92); headline equals the row counts; B3 < B2 at every budget and non-increasing 12 -> 24 -> 48; a subset re-run reproduces B3 digests on both seed sets; this report quotes the recorded numbers |

The discovery tests carry no requirement markers, as in P3 (no requirement of a DONE milestone is
claimed).

## 7. Results (exact numbers; 95% Wilson intervals)

Arms: **B2** = the frozen engine under `DISCOVERY`; **B3** = the same engine and protocol plus the
safety gate (`SafetyProtocol` digest
`sha256:27fc5feb4916271c37b5b1800998ea08ba816e0f2311711d96d7e55689675b25`).

### 7.1 True family absent -- frozen P3 held-out worlds (base seed 2026610200, 15/class, 195 primary)

| Budget | B2 force-fit | B3 force-fit | False null B2 / B3 | No claim (correct) B2 / B3 | B3 no claim with a record | Realized cost B2 / B3 |
|---|---|---|---|---|---|---|
| 8 | 60/195 = 0.308 [0.247, 0.376] | 0/195 = 0.000 [0.000, 0.019] | 9 / 6 | 126 / 189 | 189 | 5.50 / 6.29 |
| 12 | 78/195 = 0.400 [0.334, 0.470] | 9/195 = 0.046 [0.025, 0.085] | 17 / 6 | 100 / 180 | 180 | 6.56 / 8.25 |
| 24 | 92/195 = 0.472 [0.403, 0.542] | 5/195 = 0.026 [0.011, 0.059] | 25 / 3 | 78 / 187 | 187 | 7.56 / 10.82 |
| 48 | 94/195 = 0.482 [0.413, 0.552] | 4/195 = 0.021 [0.008, 0.051] | 28 / 2 | 73 / 189 | 189 | 7.76 / 11.20 |

Paired B3 - B2 force-fit (seeded paired bootstrap, seed 20261104, 2000 resamples): budget 12
-0.354 [-0.421, -0.287] (B3-only force-fits 0, B2-only 69); budget 24 -0.446 [-0.518, -0.380].

### 7.2 True family absent -- NEW held-out worlds (base seed 2026810400, 15/class, never run before)

| Budget | B2 force-fit | B3 force-fit | False null B2 / B3 | No claim B2 / B3 | Realized cost B2 / B3 |
|---|---|---|---|---|---|
| 8 | 63/195 = 0.323 [0.261, 0.392] | 0/195 = 0.000 [0.000, 0.019] | 8 / 4 | 124 / 191 | 5.38 / 6.22 |
| 12 | 79/195 = 0.405 [0.339, 0.475] | 11/195 = 0.056 [0.032, 0.098] | 19 / 9 | 97 / 175 | 6.24 / 7.95 |
| 24 | 88/195 = 0.451 [0.383, 0.521] | 7/195 = 0.036 [0.018, 0.072] | 25 / 6 | 82 / 182 | 6.88 / 10.13 |
| 48 | 90/195 = 0.462 [0.393, 0.532] | 7/195 = 0.036 [0.018, 0.072] | 27 / 6 | 78 / 182 | 7.07 / 10.48 |

### 7.3 How B3 decided (primary held-out worlds)

| Seeds, budget | Endorsed | NO_ENGINE_CLAIM | ADEQUACY_UNVERIFIED | CLAIM_INADEQUATE | CATALOG_INCOMPLETE (reproduced) | ..._UNREPLICATED | Proposals (fit their data) | With a request | Mean probe units |
|---|---|---|---|---|---|---|---|---|---|
| P3, 12 | 15 | 100 | 7 | 15 | 42 | 16 | 128 (126) | 150 | 1.68 |
| P3, 24 | 8 | 78 | 2 | 12 | 93 | 2 | 168 (165) | 182 | 3.26 |
| P3, 48 | 6 | 73 | 0 | 12 | 103 | 1 | 177 (174) | 189 | 3.44 |
| NEW, 12 | 20 | 97 | 9 | 13 | 44 | 12 | 133 (133) | 155 | 1.71 |
| NEW, 24 | 13 | 82 | 0 | 13 | 83 | 4 | 164 (163) | 176 | 3.25 |
| NEW, 48 | 13 | 78 | 0 | 13 | 89 | 2 | 169 (168) | 181 | 3.42 |

Every proposal is stage-1 only (`proposals_stage_1_only: true`). Abstention rate on held-out worlds
(all B3 no-claim outcomes / 195): P3 seeds 0.969 (8), 0.923 (12), 0.959 (24), 0.969 (48); NEW seeds
0.979, 0.897, 0.933, 0.933. Endorsement counts above include the few false nulls
(`NO_EFFECT_BEYOND_NOISE` endorsed). Aliased held-out worlds (45 per seed set; excluded from the
primary rates as in P3): at budget 12, P3 seeds, B3 made no claim on 31, claimed an alias on 12 and
something else on 2 (B2: 5 / 22 / 18).

**Budget monotonicity.** Aggregate force-fits do not rise from 12 to 24 to 48 on either seed set
(9 -> 5 -> 4; 11 -> 7 -> 7). Per world, B3 has 11 escalations on each seed set (B2: 35 and 27): on the
P3 seeds 9 of them are 8 -> 12 and 2 are 12 -> 24 (`leakage.substrate-02`, `scatter.sidewall-10`); on
the NEW seeds all 11 are 8 -> 12. The 8 -> 12 rise (0 -> 9 and 0 -> 11) is honest to report: at budget
8 B3 can rarely afford the coverage it requires and abstains on nearly everything; at 12 it can, and
some surrogates pass the probes it affords.

### 7.4 Positive control: true family IN the catalog (same worlds, family left in)

| Seeds, budget | B2 correct | B3 correct | False discoveries B2 / B3 | B3 decisions |
|---|---|---|---|---|
| P3, 8 | 158/240 = 0.658 | 63/240 = 0.263 | 0 / 0 | 95 ADEQUACY_UNVERIFIED, 82 no engine claim |
| P3, 12 | 218/240 = 0.908 [0.865, 0.939] | 153/240 = 0.637 [0.575, 0.696] | 1 / 1 | 64 ADEQUACY_UNVERIFIED |
| P3, 24 | 238/240 = 0.992 | 236/240 = 0.983 | 2 / 1 | 237 endorsed |
| P3, 48 | 238/240 = 0.992 | 237/240 = 0.988 | 2 / 1 | 238 endorsed |
| NEW, 8 | 153/240 = 0.637 | 65/240 = 0.271 | 3 / 1 | 87 ADEQUACY_UNVERIFIED |
| NEW, 12 | 214/240 = 0.892 | 151/240 = 0.629 | 5 / 5 | 63 ADEQUACY_UNVERIFIED |
| NEW, 24 | 235/240 = 0.979 | 234/240 = 0.975 | 5 / 2 | 236 endorsed |
| NEW, 48 | 235/240 = 0.979 | 235/240 = 0.979 | 5 / 2 | 237 endorsed |

The existing world generator, P3 curve seeds (base 2026110200, 25 per kind, 200 worlds; B2
reproduces P3 1600/1600):

| Cap | B2 correct | B3 correct | False discoveries B2 / B3 | Realized cost B2 / B3 |
|---|---|---|---|---|
| 4 | 69/200 = 0.345 | 33/200 = 0.165 | 2 / 0 | 3.89 / 3.96 |
| 6 | 97/200 = 0.485 | 39/200 = 0.195 | 3 / 0 | 5.50 / 5.98 |
| 8 | 141/200 = 0.705 | 77/200 = 0.385 | 4 / 1 | 6.59 / 7.72 |
| 10 | 151/200 = 0.755 | 103/200 = 0.515 | 4 / 1 | 7.21 / 9.43 |
| 12 | 173/200 = 0.865 [0.811, 0.905] | 130/200 = 0.650 [0.582, 0.713] | 4 / 1 | 7.70 / 11.13 |
| 16 | 191/200 = 0.955 | 174/200 = 0.870 | 4 / 1 | 8.07 / 14.19 |
| 20 | 193/200 = 0.965 | 191/200 = 0.955 | 4 / 0 | 8.17 / 17.11 |
| 24 | 194/200 = 0.970 | 193/200 = 0.965 | 4 / 0 | 8.22 / 19.07 |
| 48 | 196/200 = 0.980 | 196/200 = 0.980 | 4 / 0 | 8.26 / 20.15 |

At cap 12 by kind (B2 -> B3 correct): composition 20 -> 0 (B3 abstains: compositions predict signals in
many experiments and coverage is not affordable; B2's 2 false discoveries there go to 0),
outside_initial_prior 18 -> 2, in_catalog_single 25 -> 21, confounded_measurement_chain 24 -> 22,
noise_glitch 25 -> 24; inseparable_pair, noise_only_null and outside_all_declared unchanged. At cap 24
every kind is within one world of B2. Cap invariants (realized <= cap, meter = engine report, an
unconstrained run is identical at every larger cap) hold for all 3600 runs (1127 comparisons, 0
violations). B3's realized cost is higher: it spends what it has on probes.

### 7.5 Coverage option (Owner decision; reported, not used to choose)

P3 held-out worlds, primary force-fits / in-catalog control correct (of 195 / 240):

| `signal_coverage` | Budget 12 | Budget 24 |
|---|---|---|
| 1.0 (default) | 9 / 153 | 5 / 236 |
| 0.5 | 15 / 214 | 6 / 236 |
| 0.0 (probe what is affordable, require only adequacy) | 16 / 217 | 7 / 236 |

Even with no coverage requirement the probes alone cut budget-12 force-fits from 78 to 16 while
keeping in-catalog accuracy at 217/240 (B2: 218). The default 1.0 buys the last 7 force-fits at
budget 12 with 64 in-catalog abstentions.

## 8. Limitations and residual risks

1. **Same author, synthetic worlds.** Worlds, held-out families, engine and gate share an author
   lineage; the "new" seeds guard against seed overfitting, not design overfitting. ENGINEERING
   EVIDENCE ONLY.
2. **Residual force-fits** (9 / 5 / 4 at 12 / 24 / 48 on P3 seeds; 11 / 7 / 7 on NEW seeds) are
   mostly `leakage.substrate` claimed as `scatter.sidewall` (P3 seeds: 7 of 9 at 12, 4 of 4 at 48;
   NEW seeds: 7 of 11 at 12, 5 of 7 at 48), plus a few geometry surrogates (`gap_small` as
   `fcd.static + geometry.thickness`, `width_narrow` as `fcd.static`, `thickness` as
   `geometry.width_wide`): the deviation is localised in one or two experiments and diluted by the
   global chi-square over many degrees of freedom. A per-experiment predictive check would likely catch more; it was **not** implemented
   because it would be designed after seeing these results (it should be fixed on development seeds
   and evaluated on fresh seeds).
3. **False nulls remain** (6 / 3 / 2 at P3 12 / 24 / 48): small `geometry.gap*` effects, where the
   engine spends the budget before the gap array can be probed.
4. **In-catalog cost at low budgets** (§7.4): 218 -> 153 at 12, 158 -> 63 at 8. These are abstentions
   with requests, not false discoveries, but a user with budget 12 gets far fewer answers.
5. **The probe policy is generic, not optimal.** It does not know where an unknown mechanism will show
   up; it checks the claim's own predictions first. A different unknown family could hide in an
   experiment the claim predicts nothing in and that the budget does not reach.
6. **Proposals are tables read off residuals.** They fit the data they came from by construction; they
   predict nothing for never-run experiments; the closest declared model can sit within a few sigma
   on the observed experiments. They are stage-1 ideas only and support nothing.
7. **Aliased worlds** (no experiment separates the truth from some declared hypothesis) cannot be
   protected by any adequacy test; B3 still claims an alias in 12-23 of 45 such worlds. They are
   excluded from the primary rates, as in P3.
8. **The engine's transitive class closure** (§3) is unchanged in the frozen engine; the gate does not
   rely on it, but the engine's claim classes still do.
9. **Not connected** to the research flow, the Causal Warrant Gate, PostgreSQL LIB, Lumerical or any
   model; nothing here confirms anything.

## 9. Owner decisions required

1. **Coverage policy / abstention policy** (`signal_coverage`): 1.0 (default: never endorse a claim
   with an unchecked signal prediction; large in-catalog cost below budget ~20), 0.5, or 0.0 (§7.5).
   Alternatively a budget-dependent policy, or reporting `ADEQUACY_UNVERIFIED` claims as a separate,
   explicitly provisional tier rather than as abstentions.
2. **Adequacy threshold**: `alpha_adequacy = 0.01` and `z_adequacy = 4.0` (pre-declared). A stricter
   alpha abstains more on true in-catalog claims; a looser one lets more surrogates through.
3. **Replication allowance** (`max_probe_replications = 2`) and whether an unreplicated inadequacy
   should be reported differently from a reproduced one downstream.
4. **Whether to pursue a per-experiment predictive check** (limitation 2) as a v1.1, to be fixed on
   development seeds and evaluated on fresh seeds only.
5. **Whether the engine's transitive class closure** should be revisited in a future engine version
   (it is frozen here).
6. **Independent evaluation**: whether to run the protocol in
   `docs/evaluation/discovery-independent-evaluation-protocol.md` with B3 as an engine arm -- the only
   route to evidence that is not developer-authored.

## 10. Engineering evidence vs scientific evidence

- **Engineering (shown here):** the gate behaves as designed on developer-authored synthetic worlds;
  results are deterministic and reproducible (`python scripts/discovery_safety_eval.py --check`);
  realized cost never exceeds the cap and equals the laboratory meter; the frozen engine, evaluation
  tooling and P3 evidence are unchanged and reproduce bit for bit; nine targeted mutants of the gate
  are killed by the new tests.
- **Not scientific:** no real device, no real experiment, no real literature, no independent world
  author, no blind evaluation. Scientific acceptance remains **NOT PASSED**; G-D remains
  **NOT PASSED**.

## 11. Verification (observed on this branch, code at `98c5ad9`, status at `4f31408`)

| Check | Command | Result |
|---|---|---|
| Lint | `.venv/bin/python -m ruff check src tests scripts` | all checks passed |
| Format | `.venv/bin/python -m ruff format --check src tests scripts` | 620 files already formatted |
| Types | `.venv/bin/python -m mypy` | no issues in 306 source files |
| Spec conformance | `.venv/bin/python -m pytest tests/spec -q` | 245 passed |
| Focused safety tests | the three `tests/unit/test_discovery_safety*.py` files, `tests/e2e/test_discovery_safety_eval_frozen.py`, `tests/unit/test_discovery_eval_governance.py` | 104 passed |
| Default suite | `.venv/bin/python -m pytest -q` (no backend variables) | 2572 passed, 1203 skipped (backend-gated) |
| PostgreSQL suite | fresh `lib_disc` (dropdb/createdb), `scripts/migrate.py` twice (81 applied, then 0 pending), `LAB_BRAIN_TEST_POSTGRES=1 pytest -q` | 3771 passed, 4 skipped (Windows-only / no-seat skips) in 26 min 40 s |
| Requirement coverage | `scripts/check_requirement_coverage.py` after the PostgreSQL run | all four checks ok |
| Status inventory | `scripts/update_status.py` then `--check` and `--check --requirements-only` | up to date (collected tests 3701 -> 3775) |
| Evidence | `scripts/discovery_safety_eval.py --check` | evidence is current |
| Mutation | the nine `safety_*` entries of `scripts/mutation_battery.py` | 9/9 killed (and 9/9 when the safety test files are run without `-x`; per-mutant killing tests in the branch handoff) |
| Commit hygiene | `scripts/check_commit_messages.py` | no AI authorship found |
| GOV-005 | `grep -rn "S35-" src tests` | 0 hits |

The PostgreSQL server had stopped between sessions (stale pid file) and was restarted with
`pg_ctlcluster 16 main start` before the fresh database was created; only `lib_disc` was touched.
