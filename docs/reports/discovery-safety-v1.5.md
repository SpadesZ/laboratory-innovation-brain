# Discovery safety v1.5: where B7's abstention comes from, a rival-targeted arm (B8), one clean holdout

Date: 2026-11-27. Branch: `claude/lib-implementation-agent-47evs0-discovery-v15` (from the v1.4
head `0eac9b3`). Pushed for review; not merged, not deployed.

> **ENGINEERING EVIDENCE ONLY** on developer-authored synthetic worlds. Worlds, held-out families,
> the term grammar, the engine, every safety gate, the evaluator's rule AND the new diagnosis share
> one author lineage. Nothing here is independent scientific evidence or a statement about a real
> device. **Scientific acceptance: NOT PASSED. G-D: NOT PASSED.** No model, paid call, simulator
> (no Lumerical), network call from the evaluation or real experiment was used.
>
> **v1.1 (B4) remains the offline safety baseline.** B8 is not proposed as a replacement.

| | SHA |
|---|---|
| Baseline (v1.4 head) | `0eac9b3` |
| v1.5 package, diagnosis, B8 drafts, tests, mutation entries, import guard, resume | `67e0bbc` .. `2710cd5` |
| **Pre-registration** | **`2193930`** |
| **Design freeze F6** (pushed before any seed was derived) | **`dad7ed4`** (`dad7ed43693a10234e248990d8ce56990528e739`) |
| Full PostgreSQL suite at F6; worlds finished before the machine restart | `69811ad` |
| Resume determinism proof; mutation run | `3de5df5`, `bad3a64` |
| Held-out evidence, report, status | later commits (head in the hand-off) |

Evidence: [`docs/audit/discovery-safety-v1.5-2026-11-25/`](../audit/discovery-safety-v1.5-2026-11-25/)
(`development.log`, `development/` row files and logs, `evidence/` held-out manifest, results, rows,
`run.log`; `heldout_interruption_finished_worlds.txt`, `heldout_resume_determinism.{py,log}`,
`mutation_v15.log`, `suite/full-postgres-suite-dad7ed4.log`), produced by
`scripts/discovery_safety_v15_eval.py`. Pre-registration:
[`discovery-safety-v1.5-preregistration.md`](discovery-safety-v1.5-preregistration.md).
The v1.0-v1.4 packages, the v1.4 script and every earlier evidence directory are unchanged.

## 1. Summary

- **Pre-registered outcome: SAFETY REGRESSION.** The safety condition ("SUPPORTED errors must not
  rise") FAILED on the single clean held-out run: B8 made **7 SUPPORTED errors in 2,464 runs, B7 3,
  B4 0** (B4 never reaches SUPPORTED by construction). B8's extra four are one held-out primary world
  (`geometry.width_narrow-02`, caps 12, 16, 24, 48), a wrong new mechanism SUPPORTED. B7's three
  (and three of B8's) are one aliased world (`cladding.index_drift-03`, caps 16, 24, 48): the first
  SUPPORTED errors of B7 on clean held-out data. B8 is therefore **not** an improvement under the
  pre-registered rule, whatever its abstention gains.
- **Root cause of B7's abstention cost (section 2, spent v1.4 outputs and development).** Correct
  abstentions are rare (1-2 of 128 control worlds per cap). The largest share is **noise-limited**:
  open grammar rivals whose prediction is within 2-4.5 SD of the TRUE response on every available
  experiment even at 4 runs (45-57 of 128 at caps 6-16). About a third is **avoidable**: the budget
  goes to the engine ladder and v1.2's fixed-order signal probes before any rival test
  (SPENT_ELSEWHERE, 12-29 per cap) or the truth is never put at risk (4-31). Budget-limited: 0-3.
- **B8 (rival-targeted, rival-first) did what it was built to do on the abstention side.** Control,
  per-world matched B8 - B7 own-correct: **+0.070 [+0.008, +0.133] at cap 12, +0.133 [+0.070,
  +0.203] at 16, +0.113 [+0.038, +0.198] at 24**; benchmark +0.085 [+0.032, +0.149] at 12, within
  noise at 16/24; noise-limited abstentions fell (control cap 16: 51 -> 33). Against the v1.1
  baseline B4, B8 still answers less often at matched cost in control (-0.219 [-0.312, -0.125] at
  12; B7 -0.281) and on the benchmark (-0.181 [-0.287, -0.074] at 12; B7 -0.250).
- **Why B8 failed safety (section 4.3), one mechanism twice.** The evaluator's v1.4 rival set only
  contains alternatives that the arm's OWN data constrain. A grammar shape with a term the data do
  not constrain predicts nothing and is no rival; "no effect" is held against grammar shapes only
  at their fit. An arm that chooses its experiments to close the rivals it can currently see --
  which is exactly what rival-targeted selection does -- can reach SUPPORTED without ever measuring
  where a wrong answer would show. Development caught one instance ("no effect", fixed in the arm);
  the held-out run found a second (a new mechanism whose error shows only on the unmeasured gap
  array). The weakness is in the rule; B7 is exposed too (its aliased error).
- **Efficiency.** B8 refuted more rivals per run than B7 in held-out primary at every cap but 8 (e.g.
  cap 16: 5.58 vs 2.74 per run) and in control at caps 6, 8, 10, 16, 24, 48, mostly grammar shapes; catalog-class
  refutations rose 2-4x (control cap 16: 59 vs 19). On the benchmark kinds at caps 12-16 B8 refuted
  fewer per run. Refutation counts are dominated by the grammar's size (hundreds of shapes close on
  one failed prediction) and are reported by kind.
- **v1.1 (B4) stays the offline baseline.** Neither B7 nor B8 is a replacement candidate.

## 2. Root cause of B7's abstention cost (diagnosis; spent and development data only)

**Method (evaluator-side, `v15/diagnose.py`).** For every B7 abstention on a world whose truth a
held hypothesis expresses ("supportable"), the evaluator takes the truth's identity T and asks, on
the run's own ledger, why T is not SUPPORTED. Each open rival R of T is placed by
s = max over available experiments (1-4 runs) of the separation of R's prediction (fitted to the
data) from the world's TRUE noise-free mean -- an oracle quantity used only to classify:
INDISTINGUISHABLE (s < 2: one test fails R with probability < ~0.3), WEAK (2 <= s < 4.5: closure by
one test is a coin toss), REFUTABLE (s >= 4.5). Run-level cause (first that applies):
TRUTH_TEST_FAILED (Holm rejects a registration of T) and INDISTINGUISHABLE are **correct**
abstentions; WEAK_RIVAL is **noise-limited**; BUDGET_EXHAUSTED (every open rival was put at risk,
the refuting tests cost more than the unspent budget) is **budget-limited**; TRUTH_NOT_AT_RISK (T
never passed a risky registration: the arm held or tested another claim), NEVER_TARGETED /
TARGETED_SURVIVED (refuting tests affordable, rival not or unsuccessfully tested) and
SPENT_ELSEWHERE (refuting tests unaffordable, and some refutable rival was never put at risk: the
budget went to tests that did not target it) are **avoidable**.

**On the spent v1.4 held-out outputs** (base 3905077000, B7 re-run unchanged with the diagnosis:
1791/1792 runs identical to the recorded rows in ledger chain head and category; one differs only in
the arm's result digest). Control setting (truth in the catalog, 128 worlds), abstentions only:

| cap | SUPPORTED | abstained | truth test failed | truth not at risk | indistinguishable | weak rival | spent elsewhere | budget exhausted | correct / noise-limited / budget / avoidable |
|---|---|---|---|---|---|---|---|---|---|
| 6 | 22 | 106 | 1 | 31 | 0 | 45 | 29 | 0 | 1 / 45 / 0 / 60 |
| 8 | 19 | 109 | 2 | 28 | 0 | 54 | 23 | 2 | 2 / 54 / 2 / 51 |
| 10 | 37 | 91 | 2 | 24 | 0 | 52 | 12 | 1 | 2 / 52 / 1 / 36 |
| 12 | 41 | 87 | 2 | 13 | 0 | 57 | 14 | 1 | 2 / 57 / 1 / 27 |
| 16 | 54 | 74 | 2 | 9 | 0 | 50 | 10 | 3 | 2 / 50 / 3 / 19 |
| 24 | 87 | 41 | 1 | 4 | 0 | 32 | 1 | 3 | 1 / 32 / 3 / 5 |
| 48 | 121 | 7 | 1 | 4 | 0 | 2 | 0 | 0 | 1 / 2 / 0 / 4 |

(NEVER_TARGETED and TARGETED_SURVIVED were 0 at every cap.) Held-out aliased (24 worlds, truth
expressed only by an alias): 14-22 of 24 per cap are TRUTH_NOT_AT_RISK (B7 never tests the alias),
1-3 INDISTINGUISHABLE. Open rivals in the abstentions are almost all **grammar shapes** (e.g. cap
12: 10 749 grammar, 11 catalog, 1 "no effect").

Reading:
1. **Correct abstention is rare** (1-2 per cap). The data could have separated the truth from its
   open rivals in almost every case.
2. **The largest share is noise-limited (WEAK_RIVAL: 45-57 of 128 at caps 6-16).** Many adequate
   grammar shapes predict the truth's response to within 2-4.5 combined SD on every available
   experiment even at 4 runs; one test closes such a rival only with probability ~0.3-0.9, so
   closure needs repeated tests.
3. **About a third is avoidable (27-60 per cap below 24 units):** SPENT_ELSEWHERE (12-29) -- the
   ledgers show B7 spending the whole small budget on the engine ladder and v1.2's fixed-order
   signal probes (e.g. control `fcd.static-00` of base 8 000 000, cap 12: six signal probes and no rival test,
   while a greedy cover of refuting tests for its 57 open grammar rivals cost 8 units); and TRUTH_NOT_AT_RISK (4-31):
   the gate held another claim and never put the truth at risk.
4. **Budget-limited abstention is small** (0-3 per cap).
5. **Oracle bound.** No strict oracle arm was run. The diagnosis gives, per abstention, the greedy
   cover cost of refuting tests computed from the true means (`cover_cost` in the row files); for
   SPENT_ELSEWHERE runs this cover was 2-23 units, i.e. often within the cap, but it is computed
   AFTER the run's own data were collected and is not an achievable-policy bound.

## 3. B8 design (`src/lab_brain/discovery_safety/v15/`)

Entry point: **`lab_brain.discovery_safety.v15.gate.safe_investigate_v15`** (same interface as
`safe_investigate_v14`; `v15.evaluation.run_arm("B8", ...)` builds it as the evaluation does).
Self-contained arm; the evaluator rule is v1.4's, byte for byte (`EVALUATOR_RULE_V14`).

- **Rival-targeted choice** (`targeted_option`): for each affordable (experiment, 1-4 runs), the
  expected number of open rivals refuted = sum over open rivals of P(the rival's evaluator
  prediction fails the chi-square pass test at alpha 0.01 | the claim is true), from a noncentral
  chi-square under the declared instrument noise and both predictive SDs (the |z| <= 4 part
  ignored, conservative). Choose the most expected refutations per unit cost; register the claim
  and the rival most likely to fail; nothing else is sent.
- **Rival-first** (`probe_fixpoint`): these targeted tests run BEFORE the fixed-order signal probes
  while one is expected to refute >= 0.5 rivals (at most 6); then v1.2's phases unchanged
  (signal probes, support test, up to 6 rival tests with B7's choice, null probes).
- **"No effect" runs exactly as B7** (`_targeting`): see 4.3.
- What did not change (asserted by tests): support (`self_supported`), the open-rival set,
  rival predictions, registrations (identity, experiment, runs only), the evaluator, its rule.

## 4. Adversarial tests and findings (`tests/unit/test_discovery_safety_v15.py`)

### 4.1 Tests (all pass)

| attack | result |
|---|---|
| rival "closed" by separation only: claim and rival registered on an experiment separating them by 3.5-5 SD; reading exactly halfway | both pass; rival stays open; not SUPPORTED |
| registering the rival itself (it passes) | closes nothing |
| every closure in real B8 ledgers re-derived independently | every closure is the rival's own failed prediction on a passed claim test (or its own failed registration) |
| false declared data digest, 5-run registration (limit 4), registration never measured | digest recorded but not relied on; RUNS_OUT_OF_RANGE; INCOMPLETE: none supports |
| arm writes a measurement / reads the ledger | the laboratory exposes only motivating, measure, register, register_identity |
| lying arm (gate believes everything supported, no rivals) | asserts a claim; evaluator scores UNSUPPORTED_CLAIM |
| grammar rival omitted (rule without grammar rivals) | that rule would SUPPORT a B8 claim the full rule withholds (family-removed `gap_small-00`, cap 8); the full rule keeps every grammar rival |
| B8 decides support/rivals exactly as B7 | only `_targeting`, `targeted_option`, `rival_test`, `probe_fixpoint` differ |
| process boundary | B8's category, level, cost, chain head and digest identical in and out of process |
| wrong-checkout import | the script and its arm processes refuse to run if `lab_brain` resolves outside this checkout |
| interrupted run | resumes from finished worlds; only missing worlds recomputed |
| expected refutations | noncentral chi-square matches Monte Carlo within 0.02 |

Mutation battery, `safety_v15_*` (4 entries, additions only): see section 9.

### 4.2 Residual false endorsement found (development), and whether B7 can make it

- **What**: B8's second draft (rival-first for every claim) answered **"no effect", SUPPORTED, on
  `geometry.gap_small-01`** (base 8 000 000, 2 per class, family removed) at caps 6, 8 and 10 --
  a FORCE_FIT (the truth is a coupling shift whose family the arm's catalog lacks).
- **Root cause**: an evaluator-rule weakness reachable by EXPERIMENT CHOICE. "No effect" is held
  against catalog rivals at their smallest declared effects and against grammar shapes at their
  FIT (a shape is a rival only if its fitted prediction is >= 3 SD from zero on some available
  experiment at 4 runs). Draft-B8 tested "no effect" first where its catalog rivals were cheapest
  to refute (baseline, power_sweep, fiber_recouple), each test refuted the rival it targeted, and on
  the few readings collected the true out-of-catalog shift was too small to make any grammar shape
  fit >= 3 SD from zero. Every rival was closed by a failed prediction -- the rule was followed --
  yet the answer is wrong: the rule's rival set for "no effect" depends on what the arm chose to
  measure.
- **Fix in the arm, not the rule**: B8 runs a claim of "no effect" exactly as B7 (asserted: on that
  world B8's and B7's ledgers are identical at caps 6, 8, 10). A test documents the residual
  (`test_known_residual_rival_first_testing_of_no_effect_reaches_a_false_supported`).
- **Can B7 make the same error?** The weakness is in the evaluator's rule, so ANY arm, B7
  included, can reach it if its experiment sequence happens to (or is chosen to) avoid the
  experiments where the effect shows. B7 did not on this world (it abstained: its fixed-order
  signal probes measured other experiments first), had 0 SUPPORTED errors in v1.4's held-out run,
  and has no SUPPORTED "no effect" error in this round's held-out either (its three SUPPORTED
  errors there are of the kind in 4.3); but that is a property of its experiment
  order on these worlds, not a guarantee. B8 is now exposed exactly as much as B7. An adversarial
  arm can exploit it deliberately. Recommended rule-level remedies (for the spec owner; not done
  here): require "no effect" to have been put at risk on every available experiment class where
  the catalog or the grammar can express an effect, or hold "no effect" against grammar shapes at
  their smallest DETECTABLE effect rather than their fit. Relates to S35-ISSUE-23 (rival scope).

### 4.3 The held-out finding: the same weakness for a new-mechanism answer

On the clean held-out run B8 SUPPORTED a wrong new mechanism on `geometry.width_narrow-02` (held-out
primary) at caps 12-48, and B7 and B8 both SUPPORTED a wrong new mechanism on the aliased
`cladding.index_drift-03` at caps 16-48 (table in section 5; diagnosis run post hoc on the recorded
worlds, nothing changed). For `width_narrow-02` the mechanism is the one of 4.2: the evaluator's
rival set contains only alternatives the data constrain; the true response differs from the answer
only on the gap array, which B8's rival-targeted tests never chose (they target rivals that exist
on the current data, and no rival predicted anything there); a grammar composition that expresses
the truth exists but its coupling term is unconstrained by B8's data, so it predicts nothing and is
no rival. B7 abstained on that world because its fixed-order signal probes kept the budget away
from early closure. For `cladding.index_drift-03` the truth lies outside the declared grammar and
the answer is a near miss (judge separation 5.26 vs tau 5), the known limitation "a mechanism
outside the grammar is invisible", now observed as a SUPPORTED error of both arms. The arm-side
patch of 4.2 (only for "no effect") did not cover this case; a rule-level remedy is listed in
section 8.

## 5. Pre-registration, freeze, seeds, the single held-out run

- Pre-registration `2193930`; freeze F6 **`dad7ed43693a10234e248990d8ce56990528e739`**, pushed
  before any seed was derived; `--design-freeze` checked that the v1.5 package and both scripts are
  byte-identical to F6.
- Seeds `PLAN.held_out_seeds(F6)`: held-out worlds base **3034793000** (attempt 0; 8 per class: 128
  worlds, 104 primary + 24 aliased, in the family-removed and the control setting), benchmark
  kinds base **3140118000** (attempt 0; 12 per kind, 96 worlds). 352 world tasks x 7 caps x 3 arms.
- **Interruption and resume (reported, not hidden).** The machine restarted during the run (after
  the first start at 2026-11-27 ~10:36 UTC). Before the restart **121 of the 352 world tasks** had
  finished, all in the family-removed setting (indices 0-120 of 128); their names, checkpoint keys
  and finish times are in `heldout_interruption_finished_worlds.txt`. The run was RESUMED with the
  same command and the same seeds (no new seeds, attempt still 0) using the resume mechanism
  committed before the freeze (`2710cd5`): finished worlds are read from their checkpoint, the
  other 231 computed. **Per-world determinism was shown before trusting the checkpoint:** four of
  the finished worlds (indices 0, 37, 74, 120: `chain.fiber_coupling-00`, `fcd.static-05`,
  `geometry.width_wide-02`, `thermo.self_heating-00`) were re-run from nothing in boundary mode and
  all 21 records of each were identical to the checkpointed ones (`heldout_resume_determinism.log`).
  The complete `--check` (section 9) re-ran all 352 tasks from nothing.
- **A second incident**: the v1.5 mutation battery (4 entries) ran while the resumed run was in its
  family-removed phase; it rewrites v1.5 source files temporarily. Every process of the run
  (evaluator, pool workers, arm processes) had started and imported the v1.5 modules before the
  battery began (process start 04:07:11 UTC, battery 04:12-04:22), the files were restored
  byte-identically (`git diff dad7ed4` empty; restored files keep their original mtime and size, so
  no stale bytecode is used), and the full `--check` reproduces the evidence from nothing. It should
  not have been run concurrently; it is recorded here.
- Elapsed (resumed part) 5 288 s; exit 0; every run within its cap; every ledger verified.
  Evidence committed unchanged at `4d84288`.

Equal-cap tables (realized costs differ; matched comparisons in section 6). "refuted" = distinct
identities closed by a FAILED prediction, by kind, with refutations of truth-matching identities
("incorrect") excluded from the count and shown after the semicolon. Abstentions are those on
supportable worlds, bucketed as in section 2.


#### held-out primary (family removed)

| cap | arm | n | credited | SUPPORTED errors | UNSUPPORTED_CLAIM | own correct / own error | refuted (null/catalog/grammar; incorrect) | per run / per unit | abstained: correct / noise / budget / avoidable | cost mean / at cap |
|---|---|---|---|---|---|---|---|---|---|---|
| 6 | B4 | 104 | 0 | 0 | 0 | 104 / 0 | 0 (0/0/0; 0) | 0.0 / 0.0 | 0 / 0 / 0 / 0 | 5.0288 / 0.7019 |
| 6 | B7 | 104 | 3 | 0 | 0 | 104 / 0 | 1457 (17/41/1399; 0) | 3.1743 / 2.6832 | 0 / 0 / 0 / 0 | 5.2212 / 0.4038 |
| 6 | B8 | 104 | 3 | 0 | 0 | 104 / 0 | 1873 (17/51/1805; 0) | 3.894 / 3.3809 | 0 / 0 / 0 / 0 | 5.3269 / 0.5096 |
| 8 | B4 | 104 | 0 | 0 | 1 | 103 / 1 | 0 (0/0/0; 0) | 0.0 / 0.0 | 0 / 0 / 0 / 0 | 6.1923 / 0.5096 |
| 8 | B7 | 104 | 3 | 0 | 0 | 104 / 0 | 3996 (15/44/3937; 0) | 7.0726 / 5.5423 | 0 / 0 / 0 / 0 | 6.9327 / 0.4808 |
| 8 | B8 | 104 | 3 | 0 | 0 | 104 / 0 | 4127 (17/50/4060; 0) | 7.0187 / 5.7963 | 0 / 0 / 0 / 0 | 6.8462 / 0.4135 |
| 10 | B4 | 104 | 0 | 0 | 4 | 100 / 4 | 0 (0/0/0; 0) | 0.0 / 0.0 | 0 / 0 / 0 / 0 | 7.25 / 0.4519 |
| 10 | B7 | 104 | 3 | 0 | 0 | 104 / 0 | 3188 (16/46/3126; 0) | 4.958 / 3.8973 | 0 / 0 / 0 / 0 | 7.8654 / 0.2404 |
| 10 | B8 | 104 | 3 | 0 | 0 | 104 / 0 | 4042 (17/54/3971; 0) | 6.1804 / 4.9901 | 0 / 0 / 0 / 0 | 7.7885 / 0.2212 |
| 12 | B4 | 104 | 0 | 0 | 4 | 100 / 4 | 0 (0/0/0; 0) | 0.0 / 0.0 | 0 / 0 / 0 / 0 | 8.0 / 0.3462 |
| 12 | B7 | 104 | 4 | 0 | 0 | 104 / 0 | 2297 (15/50/2232; 0) | 3.2908 / 2.494 | 0 / 0 / 0 / 0 | 8.8558 / 0.1635 |
| 12 | B8 | 104 | 4 | 1 | 0 | 103 / 1 | 3974 (16/52/3906; 0) | 5.558 / 4.3432 | 0 / 0 / 0 / 0 | 8.7981 / 0.1923 |
| 16 | B4 | 104 | 0 | 0 | 6 | 98 / 6 | 0 (0/0/0; 0) | 0.0 / 0.0 | 0 / 0 / 0 / 0 | 9.1731 / 0.2019 |
| 16 | B7 | 104 | 5 | 0 | 0 | 104 / 0 | 2128 (18/47/2063; 0) | 2.7352 / 2.0344 | 0 / 0 / 0 / 0 | 10.0577 / 0.1058 |
| 16 | B8 | 104 | 14 | 1 | 0 | 103 / 1 | 4478 (17/54/4407; 0) | 5.5766 / 4.2405 | 0 / 0 / 0 / 0 | 10.1538 / 0.1346 |
| 24 | B4 | 104 | 0 | 0 | 1 | 103 / 1 | 0 (0/0/0; 0) | 0.0 / 0.0 | 0 / 0 / 0 / 0 | 10.3077 / 0.0673 |
| 24 | B7 | 104 | 6 | 0 | 0 | 104 / 0 | 2094 (18/47/2029; 0) | 2.3795 / 1.7913 | 0 / 0 / 0 / 0 | 11.2404 / 0.0288 |
| 24 | B8 | 104 | 14 | 1 | 0 | 103 / 1 | 4520 (17/51/4452; 0) | 5.039 / 3.8208 | 0 / 0 / 0 / 0 | 11.375 / 0.0288 |
| 48 | B4 | 104 | 0 | 0 | 3 | 101 / 3 | 0 (0/0/0; 0) | 0.0 / 0.0 | 0 / 0 / 0 / 0 | 10.8462 / 0.0 |
| 48 | B7 | 104 | 7 | 0 | 0 | 104 / 0 | 2087 (17/48/2022; 0) | 2.1694 / 1.6524 | 0 / 0 / 0 / 0 | 12.1442 / 0.0 |
| 48 | B8 | 104 | 15 | 1 | 0 | 103 / 1 | 4534 (17/54/4463; 0) | 4.5891 / 3.5175 | 0 / 0 / 0 / 0 | 12.3942 / 0.0 |

#### control (family left in)

| cap | arm | n | credited | SUPPORTED errors | UNSUPPORTED_CLAIM | own correct / own error | refuted (null/catalog/grammar; incorrect) | per run / per unit | abstained: correct / noise / budget / avoidable | cost mean / at cap |
|---|---|---|---|---|---|---|---|---|---|---|
| 6 | B4 | 128 | 0 | 0 | 23 | 23 / 0 | 0 (0/0/0; 0) | 0.0 / 0.0 | 0 / 0 / 0 / 105 | 5.9609 / 0.9609 |
| 6 | B7 | 128 | 27 | 0 | 0 | 27 / 0 | 2891 (1/45/2845; 0) | 5.0017 / 3.789 | 0 / 49 / 0 / 52 | 5.9609 / 0.9609 |
| 6 | B8 | 128 | 23 | 0 | 0 | 23 / 0 | 3196 (10/77/3109; 3) | 5.0252 / 4.1832 | 2 / 47 / 2 / 54 | 5.9688 / 0.9688 |
| 8 | B4 | 128 | 0 | 0 | 37 | 36 / 1 | 0 (0/0/0; 0) | 0.0 / 0.0 | 0 / 0 / 0 / 91 | 7.9375 / 0.9375 |
| 8 | B7 | 128 | 25 | 0 | 0 | 25 / 0 | 3326 (1/48/3277; 1) | 4.3763 / 3.2898 | 0 / 53 / 1 / 49 | 7.8984 / 0.9453 |
| 8 | B8 | 128 | 32 | 0 | 0 | 32 / 0 | 4857 (14/79/4764; 4) | 6.1326 / 4.8137 | 2 / 41 / 1 / 52 | 7.8828 / 0.9062 |
| 10 | B4 | 128 | 0 | 0 | 55 | 53 / 2 | 0 (0/0/0; 0) | 0.0 / 0.0 | 0 / 0 / 0 / 73 | 9.8906 / 0.8984 |
| 10 | B7 | 128 | 41 | 0 | 0 | 41 / 0 | 3121 (10/28/3083; 2) | 3.3237 / 2.4908 | 0 / 48 / 2 / 37 | 9.7891 / 0.8984 |
| 10 | B8 | 128 | 44 | 0 | 0 | 44 / 0 | 4493 (16/77/4400; 4) | 4.6608 / 3.5829 | 1 / 37 / 3 / 43 | 9.7969 / 0.875 |
| 12 | B4 | 128 | 0 | 0 | 85 | 83 / 2 | 0 (0/0/0; 0) | 0.0 / 0.0 | 0 / 0 / 0 / 43 | 11.7969 / 0.8359 |
| 12 | B7 | 128 | 43 | 0 | 0 | 43 / 0 | 4506 (14/20/4472; 2) | 4.0018 / 2.9743 | 0 / 54 / 2 / 29 | 11.8359 / 0.8984 |
| 12 | B8 | 128 | 54 | 0 | 0 | 54 / 0 | 4503 (16/61/4426; 2) | 3.9604 / 2.9625 | 0 / 41 / 2 / 31 | 11.875 / 0.9219 |
| 16 | B4 | 128 | 0 | 0 | 115 | 113 / 2 | 0 (0/0/0; 0) | 0.0 / 0.0 | 0 / 0 / 0 / 13 | 15.5703 / 0.6719 |
| 16 | B7 | 128 | 58 | 0 | 0 | 58 / 0 | 3508 (13/19/3476; 5) | 2.421 / 1.7444 | 0 / 51 / 3 / 16 | 15.7109 / 0.8594 |
| 16 | B8 | 128 | 75 | 0 | 0 | 75 / 0 | 4421 (16/59/4346; 3) | 3.0385 / 2.2061 | 0 / 33 / 0 / 20 | 15.6562 / 0.8281 |
| 24 | B4 | 128 | 0 | 0 | 124 | 123 / 1 | 0 (0/0/0; 0) | 0.0 / 0.0 | 0 / 0 / 0 / 4 | 21.125 / 0.1875 |
| 24 | B7 | 128 | 86 | 0 | 0 | 86 / 0 | 4117 (13/14/4090; 5) | 2.131 / 1.4563 | 0 / 34 / 1 / 7 | 22.0859 / 0.4141 |
| 24 | B8 | 128 | 95 | 0 | 0 | 95 / 0 | 4939 (16/58/4865; 4) | 2.5778 / 1.757 | 0 / 26 / 0 / 7 | 21.9609 / 0.4219 |
| 48 | B4 | 128 | 0 | 0 | 124 | 123 / 1 | 0 (0/0/0; 0) | 0.0 / 0.0 | 0 / 0 / 0 / 4 | 22.125 / 0.0 |
| 48 | B7 | 128 | 121 | 0 | 0 | 121 / 0 | 4370 (13/10/4347; 7) | 1.8828 / 1.2366 | 0 / 2 / 0 / 5 | 27.6094 / 0.0156 |
| 48 | B8 | 128 | 119 | 0 | 0 | 119 / 0 | 5405 (15/57/5333; 7) | 2.3779 / 1.5916 | 0 / 4 / 0 / 5 | 26.5312 / 0.0156 |

#### benchmark kinds

| cap | arm | n | credited | SUPPORTED errors | UNSUPPORTED_CLAIM | own correct / own error | refuted (null/catalog/grammar; incorrect) | per run / per unit | abstained: correct / noise / budget / avoidable | cost mean / at cap |
|---|---|---|---|---|---|---|---|---|---|---|
| 6 | B4 | 96 | 0 | 0 | 5 | 17 / 0 | 0 (0/0/0; 0) | 0.0 / 0.0 | 0 / 0 / 0 / 79 | 5.9896 / 0.9896 |
| 6 | B7 | 96 | 10 | 0 | 0 | 22 / 0 | 1401 (1/49/1351; 0) | 3.2734 / 2.5198 | 0 / 16 / 0 / 58 | 5.7917 / 0.875 |
| 6 | B8 | 96 | 7 | 0 | 0 | 19 / 0 | 1561 (2/88/1471; 0) | 3.3213 / 2.833 | 0 / 10 / 0 / 67 | 5.7396 / 0.8438 |
| 8 | B4 | 96 | 0 | 0 | 24 | 36 / 0 | 0 (0/0/0; 0) | 0.0 / 0.0 | 0 / 0 / 0 / 60 | 7.7188 / 0.8438 |
| 8 | B7 | 96 | 16 | 0 | 0 | 28 / 0 | 1855 (2/52/1801; 0) | 3.4225 / 2.5657 | 0 / 19 / 0 / 49 | 7.5312 / 0.8125 |
| 8 | B8 | 96 | 18 | 0 | 0 | 30 / 0 | 1842 (2/75/1765; 0) | 3.2316 / 2.6017 | 0 / 12 / 0 / 54 | 7.375 / 0.7188 |
| 10 | B4 | 96 | 0 | 0 | 40 | 51 / 1 | 0 (0/0/0; 0) | 0.0 / 0.0 | 0 / 0 / 0 / 44 | 9.4583 / 0.8333 |
| 10 | B7 | 96 | 23 | 0 | 0 | 35 / 0 | 1648 (3/33/1612; 1) | 2.4597 / 1.8434 | 0 / 20 / 0 / 41 | 9.3125 / 0.7917 |
| 10 | B8 | 96 | 26 | 0 | 0 | 38 / 0 | 1659 (3/75/1581; 1) | 2.4148 / 1.9003 | 0 / 12 / 1 / 45 | 9.0938 / 0.7292 |
| 12 | B4 | 96 | 0 | 0 | 54 | 65 / 1 | 0 (0/0/0; 0) | 0.0 / 0.0 | 0 / 0 / 0 / 30 | 11.1354 / 0.7604 |
| 12 | B7 | 96 | 27 | 0 | 0 | 39 / 0 | 1342 (2/29/1311; 2) | 1.6692 / 1.2357 | 0 / 20 / 0 / 37 | 11.3125 / 0.7604 |
| 12 | B8 | 96 | 35 | 0 | 0 | 47 / 0 | 781 (3/63/715; 2) | 0.9654 / 0.7313 | 0 / 14 / 1 / 34 | 11.125 / 0.7917 |
| 16 | B4 | 96 | 0 | 0 | 66 | 76 / 2 | 0 (0/0/0; 0) | 0.0 / 0.0 | 0 / 0 / 0 / 18 | 14.1979 / 0.4896 |
| 16 | B7 | 96 | 41 | 0 | 0 | 53 / 0 | 1693 (3/29/1661; 2) | 1.6453 / 1.2058 | 0 / 20 / 3 / 20 | 14.625 / 0.6771 |
| 16 | B8 | 96 | 45 | 0 | 0 | 57 / 0 | 863 (3/58/802; 3) | 0.8411 / 0.6227 | 0 / 13 / 2 / 24 | 14.4375 / 0.6667 |
| 24 | B4 | 96 | 0 | 0 | 77 | 88 / 1 | 0 (0/0/0; 0) | 0.0 / 0.0 | 0 / 0 / 0 / 7 | 19.0208 / 0.1667 |
| 24 | B7 | 96 | 63 | 0 | 0 | 75 / 0 | 799 (3/30/766; 7) | 0.5958 / 0.4121 | 0 / 8 / 3 / 10 | 20.1979 / 0.3542 |
| 24 | B8 | 96 | 59 | 0 | 0 | 71 / 0 | 878 (3/63/812; 3) | 0.6567 / 0.4594 | 0 / 8 / 4 / 13 | 19.9062 / 0.3438 |
| 48 | B4 | 96 | 0 | 0 | 79 | 90 / 1 | 0 (0/0/0; 0) | 0.0 / 0.0 | 0 / 0 / 0 / 5 | 20.1771 / 0.0 |
| 48 | B7 | 96 | 78 | 0 | 0 | 90 / 0 | 800 (3/36/761; 8) | 0.5212 / 0.3487 | 0 / 1 / 0 / 5 | 23.8958 / 0.0417 |
| 48 | B8 | 96 | 76 | 0 | 0 | 88 / 0 | 963 (3/70/890; 6) | 0.6257 / 0.4227 | 0 / 3 / 0 / 5 | 23.7292 / 0.0312 |

Aliased held-out worlds (24): SUPPORTED errors B7 1 per cap at 16, 24, 48; B8 the same; credited
B7 2/3/5/7, B8 2/4/5/8 at caps 12/16/24/48; B4 0 credited and 0-13 UNSUPPORTED_CLAIM.

SUPPORTED errors judged against the truth: **B4 0, B7 3, B8 7** (of 2,464 runs each):

| world | setting | arms, caps | answer | why wrong |
|---|---|---|---|---|
| `geometry.width_narrow-02` | held-out primary | B8 at 12, 16, 24, 48 (B7 abstained) | new mechanism `index[intrinsic, w^-2, lambda^1]`, SUPPORTED | truth (width-narrow class, removed) also shifts the gap-array coupling; the answer does not (3.6 sigma per run there; judge separation 6.9 > tau 5). gap_array never measured; the grammar CAN express the truth (index + coupling composition fits the noise-free truth with chi2 0.09) but on the arm's data the coupling term is unconstrained, so that shape is no rival; of the 120 adequate shapes none is >= 1.05 SD from the answer on gap_array at 4 runs |
| `cladding.index_drift-03` | held-out aliased | B7 and B8 at 16, 24, 48 | new mechanism `index + coupling` composition, SUPPORTED | the truth is outside the grammar (best grammar fit to the noise-free truth chi2 21); the answer is off by 4.2 sigma per run on width_array (measured, absorbed by noise and fit) and the judge separation 5.26 just exceeds tau 5 |

## 6. Per-world matched comparisons (fresh held-out seeds)

Differences Y - X over worlds matched at equal realized cost (+-1 unit), paired bootstrap 95 %
intervals (2000 resamples); "(Y dearer, X dearer)" = unmatched worlds and which arm spent more.
B4 is the v1.1 baseline (the "B8 vs v1.1" comparison is B8-B4).


#### held-out primary: B7-B4

| anchor cap | matched / worlds (Y dearer, X dearer) | own correct | credited | SUPPORTED errors | own error | refuted | avoidable abstention |
|---|---|---|---|---|---|---|---|
| 6 | 88/104 (16, 0) | +0.000 [+0.000, +0.000] | +0.034 [+0.000, +0.080] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +13.35 [+3.68, +30.74] | +0.000 [+0.000, +0.000] |
| 8 | 88/104 (16, 0) | +0.011 [+0.000, +0.034] | +0.034 [+0.000, +0.080] | +0.000 [+0.000, +0.000] | -0.011 [-0.034, +0.000] | +40.10 [+19.85, +63.92] | +0.000 [+0.000, +0.000] |
| 10 | 88/104 (16, 0) | +0.023 [+0.000, +0.057] | +0.034 [+0.000, +0.080] | +0.000 [+0.000, +0.000] | -0.023 [-0.057, +0.000] | +33.45 [+14.95, +57.80] | +0.000 [+0.000, +0.000] |
| 12 | 88/104 (16, 0) | +0.034 [+0.000, +0.080] | +0.034 [+0.000, +0.080] | +0.000 [+0.000, +0.000] | -0.034 [-0.080, +0.000] | +31.68 [+13.38, +54.50] | +0.000 [+0.000, +0.000] |
| 16 | 83/104 (17, 4) | +0.072 [+0.024, +0.133] | +0.036 [+0.000, +0.084] | +0.000 [+0.000, +0.000] | -0.072 [-0.133, -0.024] | +30.19 [+11.59, +53.87] | +0.000 [+0.000, +0.000] |
| 24 | 75/104 (16, 13) | +0.040 [+0.000, +0.093] | +0.040 [+0.000, +0.080] | +0.000 [+0.000, +0.000] | -0.040 [-0.093, +0.000] | +32.05 [+10.96, +58.56] | +0.000 [+0.000, +0.000] |
| 48 | 81/104 (16, 7) | +0.049 [+0.012, +0.099] | +0.049 [+0.012, +0.099] | +0.000 [+0.000, +0.000] | -0.049 [-0.099, -0.012] | +30.07 [+10.28, +55.33] | +0.000 [+0.000, +0.000] |

#### held-out primary: B8-B4

| anchor cap | matched / worlds (Y dearer, X dearer) | own correct | credited | SUPPORTED errors | own error | refuted | avoidable abstention |
|---|---|---|---|---|---|---|---|
| 6 | 89/104 (15, 0) | +0.000 [+0.000, +0.000] | +0.034 [+0.000, +0.079] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +17.85 [+6.29, +33.78] | +0.000 [+0.000, +0.000] |
| 8 | 89/104 (15, 0) | +0.011 [+0.000, +0.034] | +0.034 [+0.000, +0.079] | +0.000 [+0.000, +0.000] | -0.011 [-0.034, +0.000] | +42.17 [+16.57, +76.98] | +0.000 [+0.000, +0.000] |
| 10 | 89/104 (15, 0) | +0.022 [+0.000, +0.056] | +0.034 [+0.000, +0.079] | +0.000 [+0.000, +0.000] | -0.022 [-0.056, +0.000] | +37.44 [+13.38, +71.42] | +0.000 [+0.000, +0.000] |
| 12 | 89/104 (15, 0) | +0.022 [+0.000, +0.056] | +0.034 [+0.000, +0.079] | +0.000 [+0.000, +0.000] | -0.022 [-0.056, +0.000] | +39.01 [+13.79, +70.96] | +0.000 [+0.000, +0.000] |
| 16 | 84/104 (16, 4) | +0.071 [+0.024, +0.131] | +0.095 [+0.036, +0.167] | +0.000 [+0.000, +0.000] | -0.071 [-0.131, -0.024] | +44.65 [+18.75, +80.11] | +0.000 [+0.000, +0.000] |
| 24 | 72/104 (16, 16) | +0.042 [+0.000, +0.083] | +0.083 [+0.028, +0.153] | +0.000 [+0.000, +0.000] | -0.042 [-0.083, +0.000] | +47.22 [+18.01, +84.17] | +0.000 [+0.000, +0.000] |
| 48 | 78/104 (19, 7) | +0.051 [+0.013, +0.103] | +0.090 [+0.026, +0.154] | +0.000 [+0.000, +0.000] | -0.051 [-0.103, -0.013] | +43.67 [+16.59, +80.65] | +0.000 [+0.000, +0.000] |

#### held-out primary: B8-B7

| anchor cap | matched / worlds (Y dearer, X dearer) | own correct | credited | SUPPORTED errors | own error | refuted | avoidable abstention |
|---|---|---|---|---|---|---|---|
| 6 | 104/104 (0, 0) | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +4.00 [+0.22, +9.17] | +0.000 [+0.000, +0.000] |
| 8 | 104/104 (0, 0) | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +10.11 [-14.00, +39.83] | +0.000 [+0.000, +0.000] |
| 10 | 104/104 (0, 0) | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +10.86 [-8.62, +38.11] | +0.000 [+0.000, +0.000] |
| 12 | 104/104 (0, 0) | -0.010 [-0.029, +0.000] | +0.000 [+0.000, +0.000] | +0.010 [+0.000, +0.029] | +0.010 [+0.000, +0.029] | +16.47 [-2.88, +45.22] | +0.000 [+0.000, +0.000] |
| 16 | 100/104 (3, 1) | -0.010 [-0.030, +0.000] | +0.000 [+0.000, +0.000] | +0.010 [+0.000, +0.030] | +0.010 [+0.000, +0.030] | +20.89 [+2.85, +47.97] | +0.000 [+0.000, +0.000] |
| 24 | 97/104 (4, 3) | -0.010 [-0.031, +0.000] | +0.041 [+0.010, +0.082] | +0.010 [+0.000, +0.031] | +0.010 [+0.000, +0.031] | +22.35 [+3.86, +50.22] | +0.000 [+0.000, +0.000] |
| 48 | 94/104 (8, 2) | -0.011 [-0.032, +0.000] | +0.021 [+0.000, +0.053] | +0.011 [+0.000, +0.032] | +0.011 [+0.000, +0.032] | +22.72 [+3.61, +50.40] | +0.000 [+0.000, +0.000] |

#### control: B7-B4

| anchor cap | matched / worlds (Y dearer, X dearer) | own correct | credited | SUPPORTED errors | own error | refuted | avoidable abstention |
|---|---|---|---|---|---|---|---|
| 6 | 128/128 (0, 0) | +0.031 [-0.047, +0.117] | +0.211 [+0.141, +0.289] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +22.59 [+7.72, +40.70] | -0.414 [-0.500, -0.320] |
| 8 | 128/128 (0, 0) | -0.086 [-0.180, +0.000] | +0.195 [+0.125, +0.266] | +0.000 [+0.000, +0.000] | -0.008 [-0.023, +0.000] | +24.83 [+9.80, +44.82] | -0.320 [-0.422, -0.227] |
| 10 | 128/128 (0, 0) | -0.086 [-0.188, +0.008] | +0.305 [+0.227, +0.383] | +0.000 [+0.000, +0.000] | -0.016 [-0.039, +0.000] | +19.10 [+8.14, +34.52] | -0.305 [-0.406, -0.203] |
| 12 | 128/128 (0, 0) | -0.281 [-0.383, -0.180] | +0.320 [+0.242, +0.406] | +0.000 [+0.000, +0.000] | -0.016 [-0.039, +0.000] | +31.12 [+15.07, +52.01] | -0.133 [-0.227, -0.039] |
| 16 | 128/128 (0, 0) | -0.422 [-0.516, -0.328] | +0.453 [+0.367, +0.539] | +0.000 [+0.000, +0.000] | -0.008 [-0.023, +0.000] | +27.41 [+13.06, +46.49] | +0.008 [-0.062, +0.078] |
| 24 | 71/128 (47, 10) | -0.268 [-0.380, -0.169] | +0.648 [+0.535, +0.761] | +0.000 [+0.000, +0.000] | -0.014 [-0.042, +0.000] | +36.23 [+12.97, +66.55] | +0.042 [+0.000, +0.099] |
| 48 | 56/128 (62, 10) | -0.089 [-0.179, -0.018] | +0.804 [+0.696, +0.893] | +0.000 [+0.000, +0.000] | -0.018 [-0.054, +0.000] | +6.46 [+3.41, +10.11] | +0.018 [+0.000, +0.054] |

#### control: B8-B4

| anchor cap | matched / worlds (Y dearer, X dearer) | own correct | credited | SUPPORTED errors | own error | refuted | avoidable abstention |
|---|---|---|---|---|---|---|---|
| 6 | 128/128 (0, 0) | +0.000 [-0.062, +0.070] | +0.180 [+0.117, +0.250] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +24.97 [+12.12, +41.16] | -0.398 [-0.500, -0.305] |
| 8 | 128/128 (0, 0) | -0.031 [-0.117, +0.055] | +0.250 [+0.180, +0.320] | +0.000 [+0.000, +0.000] | -0.008 [-0.023, +0.000] | +38.11 [+18.92, +61.05] | -0.297 [-0.391, -0.203] |
| 10 | 128/128 (0, 0) | -0.094 [-0.180, -0.008] | +0.320 [+0.242, +0.406] | +0.000 [+0.000, +0.000] | -0.016 [-0.039, +0.000] | +34.15 [+17.64, +55.37] | -0.211 [-0.305, -0.117] |
| 12 | 128/128 (0, 0) | -0.219 [-0.312, -0.125] | +0.422 [+0.344, +0.508] | +0.000 [+0.000, +0.000] | -0.016 [-0.039, +0.000] | +34.46 [+17.94, +55.77] | -0.094 [-0.188, +0.000] |
| 16 | 128/128 (0, 0) | -0.289 [-0.383, -0.195] | +0.586 [+0.500, +0.672] | +0.000 [+0.000, +0.000] | -0.008 [-0.023, +0.000] | +34.55 [+18.16, +53.02] | +0.039 [-0.039, +0.117] |
| 24 | 85/128 (38, 5) | -0.082 [-0.141, -0.024] | +0.847 [+0.765, +0.918] | +0.000 [+0.000, +0.000] | -0.012 [-0.035, +0.000] | +38.22 [+16.12, +65.73] | +0.012 [+0.000, +0.035] |
| 48 | 71/128 (52, 5) | +0.000 [+0.000, +0.000] | +0.915 [+0.845, +0.972] | +0.000 [+0.000, +0.000] | -0.014 [-0.042, +0.000] | +10.94 [+5.76, +17.86] | +0.000 [+0.000, +0.000] |

#### control: B8-B7

| anchor cap | matched / worlds (Y dearer, X dearer) | own correct | credited | SUPPORTED errors | own error | refuted | avoidable abstention |
|---|---|---|---|---|---|---|---|
| 6 | 128/128 (0, 0) | -0.031 [-0.086, +0.023] | -0.031 [-0.086, +0.023] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +2.38 [-10.03, +13.24] | +0.016 [-0.055, +0.086] |
| 8 | 128/128 (0, 0) | +0.055 [+0.000, +0.109] | +0.055 [+0.000, +0.109] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +11.95 [-4.42, +30.88] | +0.023 [-0.039, +0.094] |
| 10 | 128/128 (0, 0) | +0.031 [-0.031, +0.094] | +0.031 [-0.031, +0.094] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +8.62 [-10.12, +28.16] | +0.039 [-0.031, +0.117] |
| 12 | 128/128 (0, 0) | +0.070 [+0.008, +0.133] | +0.070 [+0.008, +0.133] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | -0.70 [-15.88, +13.09] | +0.023 [-0.039, +0.094] |
| 16 | 128/128 (0, 0) | +0.133 [+0.070, +0.203] | +0.133 [+0.070, +0.203] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +7.16 [-5.44, +20.88] | +0.031 [-0.023, +0.094] |
| 24 | 106/128 (8, 14) | +0.113 [+0.038, +0.198] | +0.113 [+0.038, +0.198] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +4.79 [-8.86, +20.09] | -0.009 [-0.047, +0.028] |
| 48 | 77/128 (19, 32) | +0.013 [-0.039, +0.078] | +0.013 [-0.039, +0.078] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +5.95 [+1.06, +12.12] | -0.013 [-0.039, +0.000] |

#### benchmark: B7-B4

| anchor cap | matched / worlds (Y dearer, X dearer) | own correct | credited | SUPPORTED errors | own error | refuted | avoidable abstention |
|---|---|---|---|---|---|---|---|
| 6 | 90/96 (0, 6) | +0.056 [+0.000, +0.122] | +0.111 [+0.056, +0.178] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +15.57 [+0.82, +34.51] | -0.233 [-0.322, -0.144] |
| 8 | 95/96 (0, 1) | -0.084 [-0.179, +0.011] | +0.168 [+0.095, +0.242] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +19.53 [+3.40, +42.79] | -0.116 [-0.200, -0.032] |
| 10 | 96/96 (0, 0) | -0.167 [-0.271, -0.073] | +0.229 [+0.146, +0.312] | +0.000 [+0.000, +0.000] | -0.010 [-0.031, +0.000] | +15.91 [+1.47, +37.17] | -0.042 [-0.125, +0.042] |
| 12 | 96/96 (0, 0) | -0.250 [-0.354, -0.146] | +0.292 [+0.198, +0.385] | +0.000 [+0.000, +0.000] | -0.010 [-0.031, +0.000] | +15.30 [+3.12, +33.83] | +0.052 [-0.031, +0.135] |
| 16 | 90/96 (5, 1) | -0.233 [-0.333, -0.144] | +0.422 [+0.322, +0.522] | +0.000 [+0.000, +0.000] | -0.011 [-0.033, +0.000] | +17.63 [+3.70, +38.67] | +0.011 [-0.067, +0.089] |
| 24 | 69/96 (21, 6) | -0.130 [-0.217, -0.058] | +0.594 [+0.478, +0.696] | +0.000 [+0.000, +0.000] | -0.014 [-0.043, +0.000] | +7.99 [+1.75, +16.90] | +0.029 [-0.043, +0.101] |
| 48 | 61/96 (28, 7) | -0.082 [-0.148, -0.016] | +0.656 [+0.541, +0.770] | +0.000 [+0.000, +0.000] | -0.016 [-0.049, +0.000] | +4.11 [+0.67, +9.07] | +0.049 [+0.000, +0.115] |

#### benchmark: B8-B4

| anchor cap | matched / worlds (Y dearer, X dearer) | own correct | credited | SUPPORTED errors | own error | refuted | avoidable abstention |
|---|---|---|---|---|---|---|---|
| 6 | 88/96 (0, 8) | +0.023 [-0.023, +0.068] | +0.080 [+0.034, +0.136] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +17.69 [+5.93, +35.51] | -0.136 [-0.216, -0.057] |
| 8 | 93/96 (0, 3) | -0.065 [-0.161, +0.032] | +0.194 [+0.118, +0.280] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +19.77 [+4.13, +42.88] | -0.065 [-0.161, +0.032] |
| 10 | 94/96 (0, 2) | -0.128 [-0.223, -0.032] | +0.277 [+0.191, +0.362] | +0.000 [+0.000, +0.000] | -0.011 [-0.032, +0.000] | +17.60 [+4.98, +37.45] | +0.000 [-0.096, +0.096] |
| 12 | 94/96 (0, 2) | -0.181 [-0.287, -0.074] | +0.372 [+0.277, +0.479] | +0.000 [+0.000, +0.000] | -0.011 [-0.032, +0.000] | +7.74 [+3.59, +13.55] | +0.032 [-0.064, +0.138] |
| 16 | 82/96 (10, 4) | -0.146 [-0.244, -0.049] | +0.512 [+0.415, +0.610] | +0.000 [+0.000, +0.000] | -0.012 [-0.037, +0.000] | +7.71 [+2.27, +15.72] | +0.049 [-0.049, +0.146] |
| 24 | 74/96 (15, 7) | -0.176 [-0.257, -0.095] | +0.595 [+0.486, +0.703] | +0.000 [+0.000, +0.000] | -0.014 [-0.041, +0.000] | +9.62 [+3.62, +17.81] | +0.054 [-0.014, +0.122] |
| 48 | 65/96 (23, 8) | -0.138 [-0.231, -0.062] | +0.646 [+0.523, +0.769] | +0.000 [+0.000, +0.000] | -0.015 [-0.046, +0.000] | +6.97 [+3.06, +11.69] | +0.062 [+0.015, +0.123] |

#### benchmark: B8-B7

| anchor cap | matched / worlds (Y dearer, X dearer) | own correct | credited | SUPPORTED errors | own error | refuted | avoidable abstention |
|---|---|---|---|---|---|---|---|
| 6 | 94/96 (0, 2) | -0.032 [-0.085, +0.021] | -0.032 [-0.085, +0.021] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +1.66 [-7.43, +7.71] | +0.096 [+0.032, +0.160] |
| 8 | 94/96 (0, 2) | +0.021 [-0.021, +0.064] | +0.021 [-0.021, +0.064] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.36 [-3.81, +4.10] | +0.053 [-0.011, +0.117] |
| 10 | 94/96 (0, 2) | +0.032 [-0.011, +0.074] | +0.032 [-0.011, +0.074] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.07 [-14.94, +12.98] | +0.043 [-0.011, +0.096] |
| 12 | 94/96 (0, 2) | +0.085 [+0.032, +0.149] | +0.085 [+0.032, +0.149] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | -5.97 [-21.00, +4.48] | -0.021 [-0.085, +0.043] |
| 16 | 94/96 (0, 2) | +0.043 [-0.021, +0.117] | +0.043 [-0.021, +0.117] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | -8.85 [-24.04, +1.53] | +0.043 [-0.021, +0.106] |
| 24 | 83/96 (5, 8) | -0.048 [-0.120, +0.012] | -0.048 [-0.120, +0.012] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.10 [-1.89, +2.23] | +0.036 [+0.000, +0.084] |
| 48 | 75/96 (10, 11) | -0.027 [-0.067, +0.000] | -0.027 [-0.067, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.29 [-0.47, +0.96] | +0.000 [+0.000, +0.000] |

Decision rule (pre-registered), applied:
- Safety condition: SUPPORTED-error count B8 7 > B7 3: **FAILS**. (No matched B8-B7
  SUPPORTED-error interval lies wholly above 0; the count condition alone fails.)
- Own-correct B8-B7, control: above 0 at all three anchors (12, 16, 24); benchmark: above 0 at 12
  only; not wholly below 0 anywhere. This would have met the improvement clause.
- **Outcome: "safety regression".** B8 does not reduce avoidable abstention without spending
  safety.

## 7. Efficiency: rivals refuted by a failed prediction

Per run and per cost unit, distinct identities closed by a failed prediction (never by separation),
truth-matching refutations excluded (from the equal-cap tables):

| setting | cap | B7 per run / per unit | B8 per run / per unit | B7 catalog+null | B8 catalog+null |
|---|---|---|---|---|---|
| held-out primary | 12 | 3.29 / 2.49 | 5.56 / 4.34 | 65 | 68 |
| held-out primary | 16 | 2.74 / 2.03 | 5.58 / 4.24 | 65 | 71 |
| control | 12 | 4.00 / 2.97 | 3.96 / 2.96 | 34 | 77 |
| control | 16 | 2.42 / 1.74 | 3.04 / 2.21 | 32 | 75 |
| control | 24 | 2.13 / 1.46 | 2.58 / 1.76 | 27 | 74 |
| benchmark | 12 | 1.67 / 1.24 | 0.97 / 0.73 | 31 | 66 |
| benchmark | 16 | 1.65 / 1.21 | 0.84 / 0.62 | 32 | 61 |

B4 refutes nothing (it registers nothing). Incorrect refutations (a failed prediction of an identity
expressing the truth, i.e. noise) were 0-8 per cell for both arms. The grammar-shape count is not a
measure of scientific progress (one failed prediction closes hundreds of near-identical shapes);
catalog + "no effect" refutations are the more meaningful column, and there B8 refutes about twice
as many rivals as B7 at the same cost. Matched per-world refuted differences are in section 6.

Challenging "abstention is safe": avoidable abstention is a real cost -- at cap 12 in control B7
withheld 29 avoidable and 54 noise-limited answers the data could have supported; B8 cut the
noise-limited ones (41) but not the avoidable ones (31), and paid for it with a safety failure.

## 8. What improved, what failed, what remains unproven

Improved (synthetic, developer-authored worlds only):
- A measured root cause of B7's abstention cost, with an evaluator-side diagnosis (correct /
  noise-limited / budget-limited / avoidable) and a refutation metric that never counts separation.
- B8 answers correctly more often than B7 at matched cost in control (+0.07 to +0.13 at caps
  12-24) and on the benchmark at cap 12, and refutes about twice as many catalog rivals per cost.

Failed:
- **Safety**: B8 7 SUPPORTED errors vs B7 3 on the clean held-out (pre-registered outcome: safety
  regression). The mechanism is a rule weakness that rival-targeted selection exploits by
  construction (it targets the rivals it can see, so it never measures where unseen rivals would
  appear). Development found it once for "no effect"; the arm-side fix was local and did not cover
  new-mechanism answers.
- B8 did not reduce AVOIDABLE abstention (it converted noise-limited abstentions); both v1.4 and v1.5
  arms still answer less often than v1.1 at matched cost below ~24 units in control and benchmark.
- B7 is no longer at 0 SUPPORTED errors on clean data (3 on one aliased world whose truth is
  outside the grammar).

Remains unproven / open:
- Everything is one author lineage (worlds, families, grammar, gates, rule, diagnosis). The
  diagnosis thresholds (2 and 4.5 SD) are conventions.
- **Rule-level finding for the spec owner (S35-ISSUE-23, rival scope):** the v1.4 rival set depends
  on what the arm measured. Candidate remedies: require every available experiment class on which
  the catalog or the grammar can express a response to have been measured (or a declared reason
  why not) before SUPPORTED; treat a grammar shape whose term is unconstrained by the data as a
  rival at its smallest detectable effect rather than as no prediction; hold "no effect" against
  grammar shapes at their smallest detectable effect. None of this was implemented (the spec is the
  lead's).
- The oracle bound in section 2 is a post-hoc cover cost, not an achievable-policy bound.
- Per-world matching conditions on realized cost; unmatched worlds are reported, not estimated.
- The process boundary is a same-user subprocess, not a sandbox.
- Recommended next step if B8's idea is pursued: give rival-targeted selection an explicit
  coverage obligation (measure each unmeasured available experiment class once before claiming),
  pre-register it, and evaluate on a NEW held-out derived from a new freeze; the seeds used here are
  spent.

## 9. Verification

(filled in after the `--check` run and the final suite)
