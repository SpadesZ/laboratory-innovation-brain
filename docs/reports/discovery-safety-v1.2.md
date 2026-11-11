# Discovery safety v1.2: budget-aware allocation, registered predictions, grammar discovery

Date: 2026-11-08. Branch: `claude/lib-implementation-agent-47evs0-discovery-v12`. Pushed for Independent Chief Auditor review; not
merged, not deployed.

> **ENGINEERING EVIDENCE ONLY** on developer-authored synthetic worlds. The held-out mechanism
> families, the term grammar, the engine and every safety gate share one author lineage, and the
> grammar's author had read the catalog's forward models. Nothing here is independent scientific
> evidence, an independent or blind evaluation, or a statement about a real device. **Scientific
> acceptance: NOT PASSED. G-D: NOT PASSED.** No model, paid call, simulator (no Lumerical),
> network call from the evaluation, database write or real experiment was used. Discovery is NOT
> connected to real research execution.

| | SHA |
|---|---|
| Baseline (audited v1.1 head) | `ed442bb` |
| Term grammar declared (before any discovery run) | `79ed32d` |
| **Design freeze** (v1.2 package, grammar, plan, evaluation script) | **`50549e2`** (`50549e26840e803b1175ee04c60341fbcb672048`) |
| Evidence, unit tests, mutation entries | `2b486c3` |
| Final code SHA | `50549e2`: no file under `src/` changed after the freeze; later commits add tests, docs, the status inventory and the interpreter record. The branch head is in the hand-off message |

Evidence: [`docs/audit/discovery-safety-v1.2-2026-11-08/`](../audit/discovery-safety-v1.2-2026-11-08/)
(`development.log`, `evidence/` with `manifest.json`, `results.json`, three row files, `run.log`,
`interpreter_verification.json`), produced by `scripts/discovery_safety_v12_eval.py`. The v1.0,
v1.1 and P3 evidence, the frozen engine, the evaluation tooling and the v1.0/v1.1 package files are
unchanged (the script verifies their manifests before running).

**Scoring follows SAI 3.5 candidate.4** (`classify_outcome` with `verified_evidence`, spec branch
`9461223`): every arm's final answer gets a category AND an evidential level, re-derived by the
evaluator from an evaluator-owned prediction ledger. An answer is SUPPORTED only if a prediction for
it was hashed into the ledger before the data it names was measured, and the evaluator re-scores
it as passed and risky. **B2, B3 and B4 never register predictions, so none of their answers is
SUPPORTED: under candidate.4 every one of them is PROPOSAL_ONLY (never credited, never an error).**
Their own answers, taken at face value, are reported beside (columns "own answer").

---

## 1. Summary

- **Root cause of v1.1's lost low-budget identifications (development seeds):** almost all are
  `ADEQUACY_UNVERIFIED` from budget exhaustion, not false alarms. At budget 12 on base 7_000_000,
  57 of the 62 lost worlds had a claim whose signal experiments were affordable in principle, but
  the frozen engine had spent the cap -- typically half of it on replicates of experiments it had
  already run (decisive replications, repeated prospective tests). Localized-check false alarms
  were 0-1 per 240 worlds per budget; probe order played no role (coverage needs every signal
  experiment whatever the order).
- **What fixed it:** a *gate-led* allocation: the frozen engine runs on an anytime ladder of caps
  up to half the budget (through a replay laboratory that never charges a measurement twice); if it
  has not claimed by then, the simplest adequate catalog hypothesis is taken as the claim and
  probed with the reserved half. The strict standard is unchanged (adequacy + `signal_coverage =
  1.0`) and made stricter (a registered, passed, risky prediction; no adequate distinguishable rival
  of no greater complexity). **The ladder alone recovered nothing** (the engine does not claim
  earlier at a smaller cap).
- **New held-out worlds, family LEFT IN (control), SUPPORTED exact identifications of B5:**
  125/240, 195/240, 226/240, 229/240 at budgets 8/12/24/48. B4's own (unregistered) correct
  answers: 63, 155, 233, 235; B2's own: 155, 214, 234, 235. B5 recovers most of the low-budget gap
  and **loses 7 and 6 worlds to B4 at budgets 24 and 48**.
- **New held-out worlds, family REMOVED, primary (195):** B5 answers a **validated new mechanism**
  (outside the catalog, matching the truth, through a registered prospective prediction the
  evaluator re-scored) in **30/195, 57/195, 61/195, 62/195** worlds at budgets 8/12/24/48. Its
  SUPPORTED errors (force-fit + wrong claim): 6, 3, 3, 5. B4's own force-fits at face value: 0, 3,
  1, 1. **At budget 8, B5's force-fits rose (6 vs 0): that requirement FAILED at budget 8.**
- **Benchmark world kinds:** B5 loses the noise-only kind entirely (0/25 at budgets 24 and 48,
  where B4's own answers are 24-25/25): a "no effect" claim is now held against every single class
  and four rival tests do not exclude classes at their smallest amplitude. A real negative result.

## 2. Root cause of v1.1's lost in-catalog identifications (development seeds only)

Method: on the development held-out worlds with the family LEFT IN (bases 7_000_000 and
8_000_000, 15 worlds per class, 240 each), every world where the frozen engine (B2) identified the
truth and v1.1 (B4) did not, bucketed by why (`development.log` §1):

| base | budget | B2 correct | B4 correct | lost | budget-bound: engine spend left too little | signal set costs more than the cap | false alarm, global | false alarm, localized only |
|---|---|---|---|---|---|---|---|---|
| 7_000_000 | 8 | 159 | 65 | 94 | 46 | 45 | 2 | 1 |
| 7_000_000 | 12 | 213 | 151 | 62 | 57 | 2 | 2 | 1 |
| 7_000_000 | 24 | 239 | 237 | 2 | 1 | 0 | 1 | 0 |
| 7_000_000 | 48 | 239 | 238 | 1 | 0 | 0 | 1 | 0 |
| 8_000_000 | 8 | 155 | 65 | 90 | 45 | 44 | 0 | 1 |
| 8_000_000 | 12 | 213 | 155 | 58 | 57 | 1 | 0 | 0 |
| 8_000_000 | 24 | 234 | 231 | 3 | 3 | 0 | 0 | 0 |
| 8_000_000 | 48 | 235 | 235 | 0 | 0 | 0 | 0 | 0 |

- **Budget exhaustion is the cause** (98 % of the losses at budget 12). The pinned case
  (`held_out-geometry.thickness-01`, budget 12, `test_root_cause_v11_loses_the_truth_to_the_engines_replicates`):
  the engine claims the truth after spending 11 of 12 units, at least 6 of them on replicates of
  experiments it had already run (`baseline` and `width_array` decisive replications, a second
  `tec_stabilized`); the claim's never-run signal experiments (`gas_cell_reference`, `gap_array`,
  2 units each) no longer fit.
- At budget 8 about half of the losses are **not recoverable by any allocation** under the strict
  standard: the claim's signal experiments cost more than 8 units (e.g. `scatter.sidewall` and
  `fcd.static`, 10 units). Only relaxing `signal_coverage` could recover those; the Owner kept it
  at 1.0, and it was not touched.
- Repeated localized testing is **not** a material cause on development seeds (0-1 per 240 per
  budget). Probe choice is not a cause either: endorsement needs every signal experiment, so order
  cannot change whether coverage is reached; it only decides what is learned when it is not.

## 3. What was tried, measured separately (development seeds; `development.log` §2)

| change | effect on development seeds | kept? |
|---|---|---|
| Anytime ladder of engine caps to the FULL budget (replay laboratory, distinct measurements charged once) | control correct unchanged: 23 vs 23 (b8), 47 vs 47 (b12) of 80 -- the engine does not claim at a smaller cap, because its claim needs the replicates | kept as mechanism, insufficient alone |
| Registered predictions before every probe + support test after the null probes | -5 to -7 identifications at every budget (support tests found no budget left) | kept, re-ordered (support test before null probes) |
| **Gate-led claim**: ladder to `engine_fraction` x budget, then the simplest adequate catalog hypothesis is probed with the reserved rest | control correct (64 worlds) b8 19 -> 31, b12 38 -> 48; fraction 0.75 / 1.0 recovered less (25 / 19 at b8) | **kept, fraction 0.5** |
| Rival exclusion (no adequate, distinguishable rival of no greater complexity) | held-out/control force-fits at b8 3 -> 1 without it removing correct answers | kept |
| Rival exclusion over every catalog hypothesis, any complexity | control b24 46 -> 4 of 48 ("claim + small extra class" stays adequate) | **rejected** |
| "No effect" claim held against every single class | removed a gate-led null force-fit (`nonlinear.tpa_fca-00`, b12) | kept -- it later costs every noise-only benchmark world (§6) |
| Alpha spending over repeated predictive tests | implemented as Holm at family-wise 0.01 over every registered prediction of one mechanism (the ledger rule); no further look-spending for v1.1's localized checks, given §2 | kept |

The thresholds of v1.0/v1.1 (`alpha_adequacy` 0.01, `z_adequacy` 4, `z_signal` 3,
`alpha_localized` 0.01 Holm, `signal_coverage` 1.0) are unchanged. The new constants
(`engine_fraction` 0.5, `tau_risky` 3, `alpha_prospective` 0.01, `max_rival_tests` 4,
`max_discovery_tests` 3, `candidate_band` 0.5) were set on development seeds only; only
`engine_fraction` was compared across values (0.5 / 0.75 / 1.0).

## 4. Design (all in `src/lab_brain/discovery_safety/v12/`, declared in `SafetyProtocolV12`)

v1.2 subclasses the v1.1 gate and edits no v1.0/v1.1/engine file.

1. **Allocation** (`replay.py`). The frozen engine runs at caps 2, 3, ... up to `engine_fraction x
   budget`, through `ReplayLaboratory`: a re-run that asks for the k-th run of an experiment already
   measured gets the recorded reading at no charge; only new measurements reach the evaluator's
   metered laboratory. It stops at the first claim, or when the stop was not budget-bound. Every
   measurement any run made is admitted as data. If there is no claim, the gate leads: the
   simplest adequate hypothesis the catalog expresses (never one the engine refuted).
2. **Registered predictions** (`ledger.py`). Before every probe the gate registers, per claimed
   member, the predicted values of that run (fit to the data so far, with the standard deviation
   from the amplitudes' covariance) and the strongest alternatives' predictions (zero, and the two
   best-fitting other catalog hypotheses) into the **evaluator's** ledger. The rule: per entry
   z = (observed - predicted)/sqrt(sigma^2 + sd^2); pass iff chi-square p >= 0.01 and max |z| <= 4;
   risky iff the prediction is >= 3 standard units from a registered alternative.
3. **Endorsement** requires v1.1's criterion AND the ledger rule (a risky registered prediction
   passed; Holm over all of that mechanism's registrations rejects none) AND no open rival. Probe
   phases: never-run signal experiments (by separation from the alternatives per cost), v1.1's
   deferred localized resolution, a support test if no risky registered prediction has passed,
   rival tests (up to 4), then v1.1's null probes.
4. **Discovery** (`grammar.py`, `gate.py: discover`). On `CATALOG_INCOMPLETE`: every grammar shape
   (2,892) is fitted to the admitted data; the adequate ones (same v1.1 criterion) are the
   candidates. Up to 3 times: the never-run affordable experiment that separates most candidate
   pairs and candidate-vs-nothing per cost is chosen, **each candidate's prediction is registered,
   then the experiment is run**; failures are eliminated. A candidate is answered only if it passed
   a risky registered prediction, every still-adequate grammar shape is indistinguishable from it,
   its own never-run signal experiments were run (registered) and it stays adequate. Otherwise its
   best candidate is a PROPOSAL (counted, never credited).

### 4.1 The grammar, and how far the held-out families are from it

`src/lab_brain/domains/silicon_photonics/discovery_grammar.py` (plain data, committed at `79ed32d`
before any discovery run): readouts describe what each experiment entry measures (device channels
at declared conditions, from the experiment descriptions); laws are generic scalings per condition
axis (power exponents 0-2, width exponents -1..3, radius 0-2, wavelength -2..3, evanescent decay
lengths 128/64 nm from a silicon strip-guide estimate, categorical presence under TEC lock / laser
reference / polariser, chain-loss spread 10-100 %, extinction readout 0.5-4); two one-cause
compositions (index+loss, index+coupling). A structural test holds that it imports nothing from
`lab_brain` and names no catalog class, family, parameter or forward-model function.

**Honest statement: the grammar's author had read the catalog**, and its physics is the same
textbook physics the toy forward models gesture at. The distance of each catalog class to the
closest grammar shape (joint worst-case separation over all 11 experiments x 4 replicates, the
class at the smallest and largest amplitude of its declared range, the shape's amplitudes free):

| catalog class (each family is held out in turn) | distance at smallest amplitude | at largest amplitude | verdict (tau = 5) | closest grammar shape |
|---|---|---|---|---|
| `thermo.ambient` | 0.00 | 0.00 | exact | `index[stage=ambient,power_mw=P^0,width_nm=w^0,wavelength_nm=lambda^1]` |
| `thermo.self_heating` | 0.00 | 0.00 | exact | `index[stage=intrinsic,power_mw=P^1,width_nm=w^0,wavelength_nm=lambda^0]` |
| `fcd.static` | 0.00 | 0.00 | exact | `index[stage=intrinsic,power_mw=P^0,width_nm=w^0,wavelength_nm=lambda^2] + loss[stage=intrinsic,power_mw=P^0,width_nm=w^0,radius_um=R^0,wavelength_nm=lambda^2,geometry=propagation]` |
| `nonlinear.tpa_fca` | 0.49 | 1.96 | within tau over the whole range | `index[stage=ambient,power_mw=P^2,width_nm=w^0,wavelength_nm=lambda^0] + loss[stage=ambient,power_mw=P^2,width_nm=w^0,radius_um=R^0,wavelength_nm=lambda^0,geometry=bend-only]` |
| `nonlinear.fca_dominated` | 0.32 | 1.28 | within tau over the whole range | `index[stage=ambient,power_mw=P^2,width_nm=w^0,wavelength_nm=lambda^0] + loss[stage=ambient,power_mw=P^2,width_nm=w^0,radius_um=R^0,wavelength_nm=lambda^0,geometry=bend-only]` |
| `scatter.sidewall` | 1.30 | 6.50 | within tau only at small amplitudes | `loss[stage=intrinsic,power_mw=P^0,width_nm=w^-2,radius_um=R^0,wavelength_nm=lambda^-2,geometry=propagation]` |
| `geometry.width_wide` | 0.40 | 2.00 | within tau over the whole range | `index[stage=intrinsic,power_mw=P^0,width_nm=w^-2,wavelength_nm=lambda^2] + coupling[gap_nm=evanescent-field-128nm]` |
| `geometry.width_narrow` | 0.40 | 2.00 | within tau over the whole range | `index[stage=intrinsic,power_mw=P^0,width_nm=w^-2,wavelength_nm=lambda^2] + coupling[gap_nm=evanescent-field-128nm]` |
| `geometry.gap_small` | 0.20 | 1.00 | within tau over the whole range | `coupling[gap_nm=evanescent-field-128nm]` |
| `geometry.gap_large` | 0.20 | 1.00 | within tau over the whole range | `coupling[gap_nm=evanescent-field-128nm]` |
| `leakage.substrate` | 2.25 | 11.25 | within tau only at small amplitudes | `loss[stage=intrinsic,power_mw=P^0,width_nm=w^-1,radius_um=R^-1,wavelength_nm=lambda^3,geometry=bend-only]` |
| `chain.laser_drift` | 0.00 | 0.00 | exact | `laser[laser_reference=laser-error]` |
| `chain.fiber_coupling` | 0.89 | 3.56 | within tau over the whole range | `chain_loss[realignment=spread-0.25]` |
| `geometry.thickness` | 2.01 | 10.05 | within tau only at small amplitudes | `index[stage=intrinsic,power_mw=P^0,width_nm=w^0,wavelength_nm=lambda^2] + coupling[gap_nm=evanescent-field-128nm]` |
| `cladding.index_drift` | 2.86 | 14.30 | within tau only at small amplitudes | `index[stage=intrinsic,power_mw=P^0,width_nm=w^-2,wavelength_nm=lambda^2]` |
| `chain.polarization_drift` | 0.29 | 1.16 | within tau over the whole range | `polarization[polarization=er-2]` |

Four classes are **exactly expressible** (thermo.ambient, thermo.self_heating, fcd.static,
chain.laser_drift); eight are within tau over their whole declared range (both nonlinear regimes,
both width and both gap regimes, chain.fiber_coupling, chain.polarization_drift); four only at small
amplitudes (scatter.sidewall, leakage.substrate, geometry.thickness, cladding.index_drift). So the
"new-mechanism" results below largely measure rediscovery of families the grammar can express,
not discovery of anything outside the author's vocabulary.

## 5. Results on the NEW held-out seeds (drawn after the freeze)

Seeds: `derived_base_seed(label) = 3_000_000_000 + 1000 * (SHA-256(label) mod 10^6)`, labels in
`EvaluationPlanV12`: held-out worlds base **3340487000** (15 per class: 240 worlds, 195 primary, 45
aliased), benchmark world kinds base **3178418000** (25 per kind, 200 worlds). The plan refuses any
range within 20,000 of a range used before (all earlier evaluation ranges, v1.1's held-out ranges
included, and every development range). `--design-freeze 50549e2` verified that the v1.2 package,
the grammar and the script were byte-identical to the freeze before these worlds were generated.

Columns: the eight SAI candidate.4 categories (counts with 95 % Wilson intervals; exactly one per
run; "proposal-only (hits)": answers below SUPPORTED, with how many happen to match the truth --
uncredited); "own answer": the arm's own answer at face value (v1.1's legacy categories: correct
identification / force-fit); "answers / SUPPORTED": how many runs gave an answer, and how many of
those the evaluator re-derived as SUPPORTED; "grammar proposals (hits)": B5 candidate mechanisms left
as proposals beside an abstention, and how many match the truth (uncredited); realized cost is the
metered charge. **All tables are equal-cap comparisons and COST_UNMATCHED** (§5.5).

#### New held-out worlds, family REMOVED (primary, non-aliased; 195 per cell)

| budget | arm | exact ID | indist. alt. | validated new | correct abstention | false null | force-fit | wrong claim | proposal-only (hits) | own answer: correct / force-fit | answers / SUPPORTED | grammar proposals (hits) | cost mean / median |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 8 | B2 | 0/195 [0.000, 0.019] | 0 | 0/195 [0.000, 0.019] | 121/195 [0.551, 0.686] | 0/195 [0.000, 0.019] | 0/195 [0.000, 0.019] | 0/195 [0.000, 0.019] | 74 (0) | 0 / 61 | 74 / 0 | 0 (0) | 5.37 / 5 |
| 8 | B3 | 0/195 [0.000, 0.019] | 0 | 0/195 [0.000, 0.019] | 190/195 [0.941, 0.989] | 0/195 [0.000, 0.019] | 0/195 [0.000, 0.019] | 0/195 [0.000, 0.019] | 5 (0) | 0 / 0 | 5 / 0 | 0 (0) | 6.23 / 8 |
| 8 | B4 | 0/195 [0.000, 0.019] | 0 | 0/195 [0.000, 0.019] | 190/195 [0.941, 0.989] | 0/195 [0.000, 0.019] | 0/195 [0.000, 0.019] | 0/195 [0.000, 0.019] | 5 (0) | 0 / 0 | 5 / 0 | 0 (0) | 6.23 / 8 |
| 8 | B5 | 0/195 [0.000, 0.019] | 0 | 30/195 [0.110, 0.211] | 159/195 [0.755, 0.864] | 0/195 [0.000, 0.019] | 6/195 [0.014, 0.066] | 0/195 [0.000, 0.019] | 0 (0) | 0 / 6 | 36 / 36 | 91 (74) | 7.01 / 8 |
| 12 | B2 | 0/195 [0.000, 0.019] | 0 | 0/195 [0.000, 0.019] | 102/195 [0.453, 0.592] | 0/195 [0.000, 0.019] | 0/195 [0.000, 0.019] | 0/195 [0.000, 0.019] | 93 (0) | 0 / 71 | 93 / 0 | 0 (0) | 6.28 / 5 |
| 12 | B3 | 0/195 [0.000, 0.019] | 0 | 0/195 [0.000, 0.019] | 182/195 [0.889, 0.961] | 0/195 [0.000, 0.019] | 0/195 [0.000, 0.019] | 0/195 [0.000, 0.019] | 13 (0) | 0 / 8 | 13 / 0 | 0 (0) | 7.94 / 8 |
| 12 | B4 | 0/195 [0.000, 0.019] | 0 | 0/195 [0.000, 0.019] | 187/195 [0.921, 0.979] | 0/195 [0.000, 0.019] | 0/195 [0.000, 0.019] | 0/195 [0.000, 0.019] | 8 (0) | 0 / 3 | 8 / 0 | 0 (0) | 7.94 / 8 |
| 12 | B5 | 0/195 [0.000, 0.019] | 0 | 57/195 [0.233, 0.360] | 135/195 [0.624, 0.753] | 0/195 [0.000, 0.019] | 2/195 [0.003, 0.037] | 1/195 [0.001, 0.029] | 0 (0) | 0 / 2 | 60 / 60 | 81 (66) | 9.22 / 10 |
| 24 | B2 | 0/195 [0.000, 0.019] | 0 | 0/195 [0.000, 0.019] | 84/195 [0.363, 0.501] | 0/195 [0.000, 0.019] | 0/195 [0.000, 0.019] | 0/195 [0.000, 0.019] | 111 (0) | 0 / 79 | 111 / 0 | 0 (0) | 7.30 / 5 |
| 24 | B3 | 0/195 [0.000, 0.019] | 0 | 0/195 [0.000, 0.019] | 188/195 [0.928, 0.983] | 0/195 [0.000, 0.019] | 0/195 [0.000, 0.019] | 0/195 [0.000, 0.019] | 7 (0) | 0 / 3 | 7 / 0 | 0 (0) | 10.19 / 8 |
| 24 | B4 | 0/195 [0.000, 0.019] | 0 | 0/195 [0.000, 0.019] | 191/195 [0.949, 0.992] | 0/195 [0.000, 0.019] | 0/195 [0.000, 0.019] | 0/195 [0.000, 0.019] | 4 (0) | 0 / 1 | 4 / 0 | 0 (0) | 10.19 / 8 |
| 24 | B5 | 0/195 [0.000, 0.019] | 0 | 61/195 [0.252, 0.381] | 131/195 [0.603, 0.734] | 0/195 [0.000, 0.019] | 1/195 [0.001, 0.029] | 2/195 [0.003, 0.037] | 0 (0) | 0 / 0 | 64 / 64 | 85 (74) | 11.49 / 11 |
| 48 | B2 | 0/195 [0.000, 0.019] | 0 | 0/195 [0.000, 0.019] | 78/195 [0.334, 0.470] | 0/195 [0.000, 0.019] | 0/195 [0.000, 0.019] | 0/195 [0.000, 0.019] | 117 (0) | 0 / 82 | 117 / 0 | 0 (0) | 7.52 / 5 |
| 48 | B3 | 0/195 [0.000, 0.019] | 0 | 0/195 [0.000, 0.019] | 188/195 [0.928, 0.983] | 0/195 [0.000, 0.019] | 0/195 [0.000, 0.019] | 0/195 [0.000, 0.019] | 7 (0) | 0 / 3 | 7 / 0 | 0 (0) | 10.64 / 8 |
| 48 | B4 | 0/195 [0.000, 0.019] | 0 | 0/195 [0.000, 0.019] | 191/195 [0.949, 0.992] | 0/195 [0.000, 0.019] | 0/195 [0.000, 0.019] | 0/195 [0.000, 0.019] | 4 (0) | 0 / 1 | 4 / 0 | 0 (0) | 10.64 / 8 |
| 48 | B5 | 0/195 [0.000, 0.019] | 0 | 62/195 [0.257, 0.386] | 128/195 [0.587, 0.720] | 0/195 [0.000, 0.019] | 3/195 [0.005, 0.044] | 2/195 [0.003, 0.037] | 0 (0) | 0 / 1 | 67 / 67 | 88 (77) | 12.53 / 11 |

#### New held-out worlds, family REMOVED (aliased; 45 per cell)

| budget | arm | exact ID | indist. alt. | validated new | correct abstention | false null | force-fit | wrong claim | proposal-only (hits) | own answer: correct / force-fit | answers / SUPPORTED | grammar proposals (hits) | cost mean / median |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 8 | B2 | 0/45 [0.000, 0.079] | 0 | 0/45 [0.000, 0.079] | 0/45 [0.000, 0.079] | 15/45 [0.214, 0.479] | 0/45 [0.000, 0.079] | 0/45 [0.000, 0.079] | 30 (11) | 0 / 15 | 30 / 0 | 0 (0) | 7.02 / 7 |
| 8 | B3 | 0/45 [0.000, 0.079] | 0 | 0/45 [0.000, 0.079] | 0/45 [0.000, 0.079] | 41/45 [0.793, 0.965] | 0/45 [0.000, 0.079] | 0/45 [0.000, 0.079] | 4 (0) | 0 / 0 | 4 / 0 | 0 (0) | 7.93 / 8 |
| 8 | B4 | 0/45 [0.000, 0.079] | 0 | 0/45 [0.000, 0.079] | 0/45 [0.000, 0.079] | 41/45 [0.793, 0.965] | 0/45 [0.000, 0.079] | 0/45 [0.000, 0.079] | 4 (0) | 0 / 0 | 4 / 0 | 0 (0) | 7.93 / 8 |
| 8 | B5 | 0/45 [0.000, 0.079] | 0 | 0/45 [0.000, 0.079] | 0/45 [0.000, 0.079] | 42/45 [0.821, 0.977] | 0/45 [0.000, 0.079] | 3/45 [0.023, 0.179] | 0 (0) | 0 / 3 | 3 / 3 | 9 (2) | 7.93 / 8 |
| 12 | B2 | 0/45 [0.000, 0.079] | 0 | 0/45 [0.000, 0.079] | 0/45 [0.000, 0.079] | 3/45 [0.023, 0.179] | 0/45 [0.000, 0.079] | 0/45 [0.000, 0.079] | 42 (20) | 0 / 17 | 42 / 0 | 0 (0) | 8.27 / 8 |
| 12 | B3 | 0/45 [0.000, 0.079] | 0 | 0/45 [0.000, 0.079] | 0/45 [0.000, 0.079] | 32/45 [0.566, 0.823] | 0/45 [0.000, 0.079] | 0/45 [0.000, 0.079] | 13 (9) | 0 / 1 | 13 / 0 | 0 (0) | 11.18 / 12 |
| 12 | B4 | 0/45 [0.000, 0.079] | 0 | 0/45 [0.000, 0.079] | 0/45 [0.000, 0.079] | 33/45 [0.590, 0.840] | 0/45 [0.000, 0.079] | 0/45 [0.000, 0.079] | 12 (9) | 0 / 0 | 12 / 0 | 0 (0) | 11.18 / 12 |
| 12 | B5 | 0/45 [0.000, 0.079] | 9/45 [0.109, 0.338] | 0/45 [0.000, 0.079] | 0/45 [0.000, 0.079] | 33/45 [0.590, 0.840] | 0/45 [0.000, 0.079] | 3/45 [0.023, 0.179] | 0 (0) | 0 / 1 | 12 / 12 | 7 (1) | 10.64 / 11 |
| 24 | B2 | 0/45 [0.000, 0.079] | 0 | 0/45 [0.000, 0.079] | 0/45 [0.000, 0.079] | 1/45 [0.004, 0.116] | 0/45 [0.000, 0.079] | 0/45 [0.000, 0.079] | 44 (22) | 0 / 17 | 44 / 0 | 0 (0) | 8.38 / 8 |
| 24 | B3 | 0/45 [0.000, 0.079] | 0 | 0/45 [0.000, 0.079] | 0/45 [0.000, 0.079] | 22/45 [0.350, 0.630] | 0/45 [0.000, 0.079] | 0/45 [0.000, 0.079] | 23 (22) | 0 / 0 | 23 / 0 | 0 (0) | 17.11 / 21 |
| 24 | B4 | 0/45 [0.000, 0.079] | 0 | 0/45 [0.000, 0.079] | 0/45 [0.000, 0.079] | 22/45 [0.350, 0.630] | 0/45 [0.000, 0.079] | 0/45 [0.000, 0.079] | 23 (22) | 0 / 0 | 23 / 0 | 0 (0) | 17.11 / 21 |
| 24 | B5 | 0/45 [0.000, 0.079] | 19/45 [0.290, 0.567] | 1/45 [0.004, 0.116] | 0/45 [0.000, 0.079] | 24/45 [0.391, 0.671] | 0/45 [0.000, 0.079] | 1/45 [0.004, 0.116] | 0 (0) | 0 / 0 | 21 / 21 | 7 (1) | 15.89 / 19 |
| 48 | B2 | 0/45 [0.000, 0.079] | 0 | 0/45 [0.000, 0.079] | 0/45 [0.000, 0.079] | 1/45 [0.004, 0.116] | 0/45 [0.000, 0.079] | 0/45 [0.000, 0.079] | 44 (22) | 0 / 17 | 44 / 0 | 0 (0) | 8.38 / 8 |
| 48 | B3 | 0/45 [0.000, 0.079] | 0 | 0/45 [0.000, 0.079] | 0/45 [0.000, 0.079] | 22/45 [0.350, 0.630] | 0/45 [0.000, 0.079] | 0/45 [0.000, 0.079] | 23 (22) | 0 / 0 | 23 / 0 | 0 (0) | 17.18 / 21 |
| 48 | B4 | 0/45 [0.000, 0.079] | 0 | 0/45 [0.000, 0.079] | 0/45 [0.000, 0.079] | 22/45 [0.350, 0.630] | 0/45 [0.000, 0.079] | 0/45 [0.000, 0.079] | 23 (22) | 0 / 0 | 23 / 0 | 0 (0) | 17.18 / 21 |
| 48 | B5 | 0/45 [0.000, 0.079] | 19/45 [0.290, 0.567] | 1/45 [0.004, 0.116] | 0/45 [0.000, 0.079] | 24/45 [0.391, 0.671] | 0/45 [0.000, 0.079] | 1/45 [0.004, 0.116] | 0 (0) | 0 / 0 | 21 / 21 | 7 (1) | 15.98 / 19 |

#### Same worlds, family LEFT IN (control; 240 per cell)

| budget | arm | exact ID | indist. alt. | validated new | correct abstention | false null | force-fit | wrong claim | proposal-only (hits) | own answer: correct / force-fit | answers / SUPPORTED | grammar proposals (hits) | cost mean / median |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 8 | B2 | 0/240 [0.000, 0.016] | 0 | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 81/240 [0.281, 0.400] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 159 (155) | 155 / 0 | 159 / 0 | 0 (0) | 6.47 / 7 |
| 8 | B3 | 0/240 [0.000, 0.016] | 0 | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 174/240 [0.665, 0.778] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 66 (63) | 63 / 0 | 66 / 0 | 0 (0) | 7.94 / 8 |
| 8 | B4 | 0/240 [0.000, 0.016] | 0 | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 174/240 [0.665, 0.778] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 66 (63) | 63 / 0 | 66 / 0 | 0 (0) | 7.94 / 8 |
| 8 | B5 | 125/240 [0.458, 0.583] | 0 | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 115/240 [0.417, 0.542] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 0 (0) | 125 / 0 | 125 / 125 | 2 (1) | 7.90 / 8 |
| 12 | B2 | 0/240 [0.000, 0.016] | 0 | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 21/240 [0.058, 0.130] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 219 (214) | 214 / 0 | 219 / 0 | 0 (0) | 7.56 / 7 |
| 12 | B3 | 0/240 [0.000, 0.016] | 0 | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 82/240 [0.285, 0.404] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 158 (156) | 156 / 0 | 158 / 0 | 0 (0) | 11.83 / 12 |
| 12 | B4 | 0/240 [0.000, 0.016] | 0 | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 83/240 [0.288, 0.408] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 157 (155) | 155 / 0 | 157 / 0 | 0 (0) | 11.83 / 12 |
| 12 | B5 | 195/240 [0.758, 0.857] | 0 | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 45/240 [0.143, 0.242] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 0 (0) | 195 / 0 | 195 / 195 | 0 (0) | 11.69 / 12 |
| 24 | B2 | 0/240 [0.000, 0.016] | 0 | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 1/240 [0.001, 0.023] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 239 (234) | 234 / 0 | 239 / 0 | 0 (0) | 7.88 / 7 |
| 24 | B3 | 0/240 [0.000, 0.016] | 0 | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 7/240 [0.014, 0.059] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 233 (233) | 233 / 0 | 233 / 0 | 0 (0) | 21.29 / 21 |
| 24 | B4 | 0/240 [0.000, 0.016] | 0 | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 7/240 [0.014, 0.059] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 233 (233) | 233 / 0 | 233 / 0 | 0 (0) | 21.29 / 21 |
| 24 | B5 | 226/240 [0.904, 0.965] | 0 | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 14/240 [0.035, 0.096] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 0 (0) | 226 / 0 | 226 / 226 | 0 (0) | 20.31 / 20 |
| 48 | B2 | 0/240 [0.000, 0.016] | 0 | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 240 (235) | 235 / 0 | 240 / 0 | 0 (0) | 7.90 / 7 |
| 48 | B3 | 0/240 [0.000, 0.016] | 0 | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 5/240 [0.009, 0.048] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 235 (235) | 235 / 0 | 235 / 0 | 0 (0) | 22.20 / 21 |
| 48 | B4 | 0/240 [0.000, 0.016] | 0 | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 5/240 [0.009, 0.048] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 235 (235) | 235 / 0 | 235 / 0 | 0 (0) | 22.20 / 21 |
| 48 | B5 | 229/240 [0.920, 0.974] | 0 | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 11/240 [0.026, 0.080] | 0/240 [0.000, 0.016] | 0/240 [0.000, 0.016] | 0 (0) | 229 / 0 | 229 / 229 | 0 (0) | 21.33 / 20 |

#### Benchmark world kinds (200 per cell)

| budget | arm | exact ID | indist. alt. | validated new | correct abstention | false null | force-fit | wrong claim | proposal-only (hits) | own answer: correct / force-fit | answers / SUPPORTED | grammar proposals (hits) | cost mean / median |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 8 | B2 | 0/200 [0.000, 0.019] | 0 | 0/200 [0.000, 0.019] | 25/200 [0.086, 0.178] | 55/200 [0.218, 0.341] | 0/200 [0.000, 0.019] | 0/200 [0.000, 0.019] | 120 (113) | 113 / 5 | 120 / 0 | 0 (0) | 6.38 / 7 |
| 8 | B3 | 0/200 [0.000, 0.019] | 0 | 0/200 [0.000, 0.019] | 25/200 [0.086, 0.178] | 128/200 [0.571, 0.703] | 0/200 [0.000, 0.019] | 0/200 [0.000, 0.019] | 47 (46) | 46 / 0 | 47 / 0 | 0 (0) | 7.72 / 8 |
| 8 | B4 | 0/200 [0.000, 0.019] | 0 | 0/200 [0.000, 0.019] | 25/200 [0.086, 0.178] | 128/200 [0.571, 0.703] | 0/200 [0.000, 0.019] | 0/200 [0.000, 0.019] | 47 (46) | 46 / 0 | 47 / 0 | 0 (0) | 7.69 / 8 |
| 8 | B5 | 72/200 [0.297, 0.429] | 2/200 [0.003, 0.036] | 0/200 [0.000, 0.019] | 25/200 [0.086, 0.178] | 101/200 [0.436, 0.574] | 0/200 [0.000, 0.019] | 0/200 [0.000, 0.019] | 0 (0) | 72 / 0 | 74 / 74 | 0 (0) | 7.46 / 8 |
| 12 | B2 | 0/200 [0.000, 0.019] | 0 | 0/200 [0.000, 0.019] | 25/200 [0.086, 0.178] | 19/200 [0.062, 0.144] | 0/200 [0.000, 0.019] | 0/200 [0.000, 0.019] | 156 (149) | 149 / 5 | 156 / 0 | 0 (0) | 7.38 / 7 |
| 12 | B3 | 0/200 [0.000, 0.019] | 0 | 0/200 [0.000, 0.019] | 25/200 [0.086, 0.178] | 65/200 [0.264, 0.393] | 0/200 [0.000, 0.019] | 0/200 [0.000, 0.019] | 110 (109) | 109 / 0 | 110 / 0 | 0 (0) | 11.15 / 12 |
| 12 | B4 | 0/200 [0.000, 0.019] | 0 | 0/200 [0.000, 0.019] | 25/200 [0.086, 0.178] | 67/200 [0.273, 0.403] | 0/200 [0.000, 0.019] | 0/200 [0.000, 0.019] | 108 (107) | 107 / 0 | 108 / 0 | 0 (0) | 11.07 / 12 |
| 12 | B5 | 103/200 [0.446, 0.583] | 0 | 0/200 [0.000, 0.019] | 25/200 [0.086, 0.178] | 72/200 [0.297, 0.429] | 0/200 [0.000, 0.019] | 0/200 [0.000, 0.019] | 0 (0) | 103 / 0 | 103 / 103 | 0 (0) | 11.07 / 12 |
| 24 | B2 | 0/200 [0.000, 0.019] | 0 | 0/200 [0.000, 0.019] | 25/200 [0.086, 0.178] | 1/200 [0.001, 0.028] | 0/200 [0.000, 0.019] | 0/200 [0.000, 0.019] | 174 (167) | 167 / 5 | 174 / 0 | 0 (0) | 7.81 / 7 |
| 24 | B3 | 0/200 [0.000, 0.019] | 0 | 0/200 [0.000, 0.019] | 25/200 [0.086, 0.178] | 8/200 [0.020, 0.077] | 0/200 [0.000, 0.019] | 0/200 [0.000, 0.019] | 167 (167) | 167 / 0 | 167 / 0 | 0 (0) | 19.00 / 21 |
| 24 | B4 | 0/200 [0.000, 0.019] | 0 | 0/200 [0.000, 0.019] | 25/200 [0.086, 0.178] | 10/200 [0.027, 0.090] | 0/200 [0.000, 0.019] | 0/200 [0.000, 0.019] | 165 (165) | 165 / 0 | 165 / 0 | 0 (0) | 18.86 / 21 |
| 24 | B5 | 139/200 [0.628, 0.755] | 0 | 0/200 [0.000, 0.019] | 25/200 [0.086, 0.178] | 36/200 [0.133, 0.239] | 0/200 [0.000, 0.019] | 0/200 [0.000, 0.019] | 0 (0) | 139 / 0 | 139 / 139 | 0 (0) | 18.52 / 20 |
| 48 | B2 | 0/200 [0.000, 0.019] | 0 | 0/200 [0.000, 0.019] | 25/200 [0.086, 0.178] | 0/200 [0.000, 0.019] | 0/200 [0.000, 0.019] | 0/200 [0.000, 0.019] | 175 (168) | 168 / 5 | 175 / 0 | 0 (0) | 7.83 / 7 |
| 48 | B3 | 0/200 [0.000, 0.019] | 0 | 0/200 [0.000, 0.019] | 25/200 [0.086, 0.178] | 7/200 [0.017, 0.070] | 0/200 [0.000, 0.019] | 0/200 [0.000, 0.019] | 168 (168) | 168 / 0 | 168 / 0 | 0 (0) | 19.89 / 21 |
| 48 | B4 | 0/200 [0.000, 0.019] | 0 | 0/200 [0.000, 0.019] | 25/200 [0.086, 0.178] | 9/200 [0.024, 0.083] | 0/200 [0.000, 0.019] | 0/200 [0.000, 0.019] | 166 (166) | 166 / 0 | 166 / 0 | 0 (0) | 19.75 / 21 |
| 48 | B5 | 139/200 [0.628, 0.755] | 0 | 0/200 [0.000, 0.019] | 25/200 [0.086, 0.178] | 36/200 [0.133, 0.239] | 0/200 [0.000, 0.019] | 0/200 [0.000, 0.019] | 0 (0) | 139 / 0 | 139 / 139 | 0 (0) | 19.31 / 20 |

#### Realized-cost checkpoints (commit-at-termination; COST_UNMATCHED beyond this)

| setting | budget | checkpoint (units) | B2 exact / force-fit+wrong / no answer | B3 | B4 | B5 |
|---|---|---|---|---|---|---|
| held-out (primary) | 12 | 0.25 (3) | 0 / 0 / 153 | 0 / 0 / 154 | 0 / 0 / 154 | 0 / 0 / 179 |
| held-out (primary) | 12 | 0.5 (6) | 0 / 0 / 67 | 0 / 0 / 123 | 0 / 0 / 123 | 0 / 0 / 165 |
| held-out (primary) | 12 | 1 (12) | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 3 / 0 |
| held-out (primary) | 24 | 0.25 (6) | 0 / 0 / 67 | 0 / 0 / 123 | 0 / 0 / 123 | 0 / 0 / 166 |
| held-out (primary) | 24 | 0.5 (12) | 0 / 0 / 28 | 0 / 0 / 68 | 0 / 0 / 66 | 0 / 1 / 68 |
| held-out (primary) | 24 | 1 (24) | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 3 / 0 |
| held-out (primary) | 48 | 0.25 (12) | 0 / 0 / 28 | 0 / 0 / 68 | 0 / 0 / 66 | 0 / 1 / 68 |
| held-out (primary) | 48 | 0.5 (24) | 0 / 0 / 7 | 0 / 0 / 12 | 0 / 0 / 12 | 0 / 3 / 18 |
| held-out (primary) | 48 | 1 (48) | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 5 / 0 |
| control | 12 | 0.25 (3) | 0 / 0 / 210 | 0 / 0 / 240 | 0 / 0 / 240 | 0 / 0 / 240 |
| control | 12 | 0.5 (6) | 0 / 0 / 143 | 0 / 0 / 240 | 0 / 0 / 240 | 0 / 0 / 240 |
| control | 12 | 1 (12) | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 195 / 0 / 0 |
| control | 24 | 0.25 (6) | 0 / 0 / 143 | 0 / 0 / 240 | 0 / 0 / 240 | 0 / 0 / 240 |
| control | 24 | 0.5 (12) | 0 / 0 / 23 | 0 / 0 / 238 | 0 / 0 / 238 | 0 / 0 / 238 |
| control | 24 | 1 (24) | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 226 / 0 / 0 |
| control | 48 | 0.25 (12) | 0 / 0 / 23 | 0 / 0 / 238 | 0 / 0 / 238 | 0 / 0 / 238 |
| control | 48 | 0.5 (24) | 0 / 0 / 1 | 0 / 0 / 42 | 0 / 0 / 42 | 190 / 0 / 40 |
| control | 48 | 1 (48) | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 | 229 / 0 / 0 |

#### Benchmark per kind: B4's own correct answers vs B5 SUPPORTED exact identifications (budget 24)

| kind | B4 own correct | B5 exact (SUPPORTED) | B5 abstention reasons |
|---|---|---|---|
| composition | 20/25 | 19/25 | {'CLAIM_INADEQUATE': 6} |
| confounded_measurement_chain | 25/25 | 24/25 | {'ADEQUACY_UNVERIFIED': 1} |
| in_catalog_single | 24/25 | 25/25 | {} |
| inseparable_pair | 24/25 | 24/25 | {'ADEQUACY_UNVERIFIED': 1} |
| noise_glitch | 25/25 | 24/25 | {'ADEQUACY_UNVERIFIED': 1} |
| noise_only_null | 24/25 | 0/25 | {'ADEQUACY_UNVERIFIED': 23, 'CLAIM_INADEQUATE': 2} |
| outside_all_declared | 0/25 | 0/25 | {'NO_ENGINE_CLAIM:STOPPED_UNEXPLAINED': 25} |
| outside_initial_prior | 23/25 | 23/25 | {'CLAIM_INADEQUATE': 2} |

### 5.1 How to read it

- **Evidential status changes the picture for the earlier arms.** B2 answers in 74-117 of 195
  family-removed worlds and 159-240 of 240 control worlds, B3/B4 in 4-13 and 66-235: every one is
  PROPOSAL_ONLY, because none was preceded by a registered prediction. The gates' own endorsement
  rates (columns "own answer") are what v1.0/v1.1 reported; the evaluator-re-derived SUPPORTED rate
  of B2-B4 is 0 everywhere, by construction.
- **In-catalog identification (control).** B5's SUPPORTED exact identifications: 125/240, 195/240,
  226/240, 229/240. Against B4's own answers (63, 155, 233, 235): +62 and +40 at budgets 8 and 12,
  -7 and -6 at 24 and 48. B5 never claimed a wrong in-catalog mechanism in the control.
- **Force-fits (family removed, primary).** B5 SUPPORTED force-fits 6, 2, 1, 3 and wrong claims 0,
  1, 2, 2. The run log lists every SUPPORTED error, aliased worlds included: at budget 8 the gate-led or engine claim
  `geometry.thickness` for `thermo.self_heating` (4 worlds) and two others; null claims on
  `geometry.gap_*` worlds that are aliased by another held hypothesis (WRONG_CLAIM) or not
  (FORCE_FIT); two new-mechanism answers that do not match the truth (`fcd.static-07`,
  `geometry.width_narrow-14`, each at two or three budgets). B4's own force-fits at face value were
  0, 3, 1, 1. **So v1.2 did NOT keep force-fits at v1.1's level at budget 8 (6 vs 0, intervals
  [0.014, 0.066] vs [0.000, 0.019])**; at 12-48 the counts are within each other's intervals.
- **Discovery (family removed).** Validated new mechanisms: **30/195 [0.110, 0.211], 57/195
  [0.233, 0.365], 61/195 [0.251, 0.385], 62/195 [0.256, 0.390]**. Each passed a prediction for an
  experiment never run before, registered before it ran and re-scored by the evaluator. Beside
  them, 81-91 grammar proposals per budget were left uncredited (66-77 of them match the truth).
  Under the stricter "match at the world's true amplitude" reading, see `new_mechanism_point_match`
  in `results.json`. Because the grammar expresses most held-out families (§4.1), this is
  rediscovery within the author's vocabulary, not discovery outside it.
- **Benchmark world kinds.** B5 72(+2 indistinguishable)/200, 103, 139, 139 against B4's own 46,
  107, 165, 166. The whole deficit at 24-48 is the noise-only kind (table above: 0/25 vs 24/25) plus
  six compositions (CLAIM_INADEQUATE). No B5 answer on the undeclared, non-stationary truth
  (`outside_all_declared`): 25/25 correct abstentions at every budget.

### 5.5 Cost matching

Equal caps, unequal realized costs: at budget 24 the safe arms spend ~19-21 units in the control
against B2's 7.9. No arm commits an answer before it stops (B5's ladder runs inside the gate and
nothing is answered before the gate decides), so the realized-cost checkpoints are
commit-at-termination: an answer counts at checkpoint c only if the whole run cost at most c
(experiments charged in full when started). How an arm *would* have answered if stopped at c is not
available, and every comparison needing it is **COST_UNMATCHED**. The checkpoint table above shows
B5 committing nothing at 25 % and 50 % of the cap in the control (like B3/B4), while B2 has
committed most of its answers by 50 %.

## 6. What failed (negative results, reported as found)

1. **Force-fits at budget 8 rose** (6/195 vs B4's 0/195): the gate-led claim at budget 8 has only
   about 4 units of reserve, and a surrogate that is adequate on the few experiments run can pass
   its registered probes (`geometry.thickness` for `thermo.self_heating`, 4 worlds).
2. **Noise-only worlds are lost** (0/25 at budgets 24 and 48): holding "no effect" against every
   single class means classes at their smallest amplitude stay adequate, and four rival tests do
   not exclude them. The rule removed a null force-fit on development seeds; its cost here is
   larger than that benefit.
3. **High-budget in-catalog identification is 6-7 worlds below v1.1's own answers** (control, 24 and
   48) and 26-27 below on the benchmark kinds: the stricter endorsement (registered support, rival
   exclusion) costs answers v1.1 gave.
4. **Wrong new mechanisms**: two worlds (`fcd.static-07`, `geometry.width_narrow-14`) got a
   SUPPORTED new-mechanism answer that is distinguishable from the truth -- a registered prediction
   held, but the answer is wrong elsewhere in the full experiment set.
5. **The anytime ladder alone** recovered nothing (§3); only the gate-led claim did.
6. **No look-based alpha spending for v1.1's localized checks** was added; the root cause did not
   call for it, so the "repeated testing" hypothesis stays untested beyond §2's counts.

## 7. Mutation check

Scope: only the logic v1.2 adds -- eight `safety_v12_*` entries in `scripts/mutation_battery.py`
(additions only), each on a line in `src/lab_brain/discovery_safety/v12/`. Command:
`python scripts/mutation_battery.py --only <the eight names>`. Result: **8/8 killed**.

| mutant | killed by |
|---|---|
| `safety_v12_riskless_prediction_supports` | `test_discovery_safety_v12.py::test_a_passed_but_riskless_prediction_supports_nothing` |
| `safety_v12_retrospective_registration_counts` | `test_discovery_safety_v12.py::test_a_prediction_registered_after_its_data_supports_nothing` |
| `safety_v12_no_alpha_spending` | `test_discovery_safety_v12.py::test_holm_spends_alpha_over_every_registration_of_a_mechanism` |
| `safety_v12_registration_digest_unchecked` | `test_discovery_safety_v12.py::test_a_tampered_registration_is_refused` |
| `safety_v12_replay_charges_twice` | `test_discovery_safety_v12.py::test_v12_recovers_that_identification_with_evidential_support` |
| `safety_v12_ladder_ignores_engine_share` | `test_discovery_safety_v12.py::test_v12_recovers_that_identification_with_evidential_support` |
| `safety_v12_no_gate_led_claim` | `test_discovery_safety_v12.py::test_v12_recovers_that_identification_with_evidential_support` |
| `safety_v12_unsupported_new_mechanism_credited` | `test_discovery_safety_v12.py::test_the_same_answer_without_its_ledger_is_only_a_proposal` |

## 8. Reproducibility

- Pure Python numerics (the engine's own least squares and chi-square tail; the grammar fit uses
  normal equations in `math`), string-seeded `random.Random`, digests over fixed six-decimal
  floats, sorted iteration; worlds run in parallel (`--jobs 4`) and are merged in a fixed order.
  The manifest's hashed body holds no interpreter detail.
- Written under CPython 3.13.18. `--check` with `PYTHONHASHSEED=12345` under 3.13: **evidence is
  current** (every file byte-identical). Under CPython 3.12.3 (a separate virtual environment with
  the recorded dependency versions): every file matched, and the check refused with
  **INTERPRETER MISMATCH** until 3.12 was recorded with `--record-interpreter`, after which
  3.12 is listed in `interpreter_verification.json`.
- The manifest's `code_commit` reads `50549e2...+dirty`: while the evaluation ran,
  `scripts/mutation_battery.py` (not imported by it) had uncommitted additions. `code_commit` is
  outside the hashed body; the `--check` runs above reproduce every file from the committed tree.

## 9. Limitations and residual risks

- Same author lineage for worlds, held-out families, grammar, engine and gates; the grammar's author
  had read the catalog (§4.1). The validated-new-mechanism rate is rediscovery inside a vocabulary
  that expresses most held-out families.
- The prediction ledger is evaluator-owned but in the same process as the arm (as `CostMeter` is);
  it guards against accidental, not adversarial, misuse.
- Matching a new mechanism to the truth follows SAI's worst case over parameter domains; the
  candidate's domain is the protocol's fixed band (fitted value x 0.5..1.5). A wider band would make
  matching easier; it was fixed before evaluation and never tuned on evaluation worlds.
- Distinguishability is binary here, so SAI's UNRESOLVED_ALTERNATIVE cannot occur.
- One evaluation seed range per setting; no paired bootstrap was run for B5.
- Previously inspected ranges (P3, v1.0-new, v1.1 held-out) were not re-run for B5.

## 10. Owner decisions

- **DECIDED (2026-11-04), kept:** STRICT adequacy (`signal_coverage = 1.0`); v1.2 adds requirements
  and relaxes none.
- **OPEN:**
  1. Whether evidential support (a registered, re-scored prediction) is the standard for every
     endorsement -- under it, v1.0/v1.1/the engine have no SUPPORTED answers at all.
  2. Whether to adopt v1.2's gate-led allocation, given +62/+40 control identifications at budgets 8
     and 12 against 6 force-fits at budget 8 and -6/-7 at 24/48.
  3. The "no effect" rule (hold it against every single class, losing noise-only worlds, or only
     against equal complexity, re-admitting null force-fits).
  4. `engine_fraction` (0.5), `max_rival_tests` (4), `candidate_band` (0.5), `tau_risky` (3).
  5. Whether a grammar-validated new mechanism may leave the stage-1 status at all, and who writes an
     independent grammar (authored outside this lineage, without reading the catalog).
  6. Commissioning an independent protocol (worlds, families and grammar authored elsewhere).

## 11. Verification

Run at `688671c` (CPython 3.13.18 in `.venv`; ruff 0.17.4). The commit that records this section
changes documentation only.

| check | result |
|---|---|
| `ruff check src tests scripts` | All checks passed |
| `ruff format --check src tests scripts` | 641 files already formatted |
| `mypy` (strict) | no issues in 318 source files |
| `pytest tests/spec -q` | 245 passed |
| focused: `tests/unit/test_discovery_safety*.py` + the v1.0/v1.1/v1.2 frozen-evidence e2e tests | 145 passed |
| full default suite (`pytest -q`, no backend) | **2643 passed, 1203 skipped**, 0 failed |
| full PostgreSQL suite on a FRESH `lib_disc` (dropped, recreated, `migrate.py` twice: 81 applied, then up to date) | **3842 passed, 4 skipped** (network and Windows only), 0 failed -- run twice: before and after regenerating the status inventory, each on a freshly recreated database |
| `update_status.py` | regenerated (`688671c`); `--check` and `--check --requirements-only`: up to date |
| `check_requirement_coverage.py` | passed (milestones DONE: M0a, M0b, M1, M2, M3) |
| `discovery_safety_v12_eval.py --check` | evidence is current (CPython 3.13, `PYTHONHASHSEED=12345`); CPython 3.12.3: INTERPRETER MISMATCH until recorded, then reproduced and recorded |
| v1.0 and v1.1 frozen-evidence tests | pass (their files untouched) |
| mutation battery, `safety_v12_*` | 8/8 killed |
| `check_commit_messages.py` | no AI authorship found |
| `S35-` identifiers in `src/` or `tests/` | none |

## Lead implementation agent's independent check (2026-11-11)

- All branch commits authored `SpadesZ`; no AI authorship lines; no file under `src/lab_brain/discovery/` (frozen engine) changed; no existing `docs/audit` evidence or migration modified or deleted; no `S35-` identifiers in `src/` or `tests/`.
- `PYTHONHASHSEED=12345 python scripts/discovery_safety_v12_eval.py --check` (CPython 3.13.18): **evidence is current** (402 s).
- `pytest tests/unit/test_discovery_safety_v12.py tests/e2e/test_discovery_safety_v12_frozen.py`: 26 passed. `ruff check src tests scripts`: clean.
