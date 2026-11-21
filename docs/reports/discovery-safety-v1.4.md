# Discovery safety v1.4: per-world cost matching, rival closure by failed prediction, a clean holdout

Date: 2026-11-21. Branch: `claude/lib-implementation-agent-47evs0-discovery-v14` (from the v1.3
head `c022f3a`). Pushed for review; not merged, not deployed.

> **ENGINEERING EVIDENCE ONLY** on developer-authored synthetic worlds. Worlds, held-out families,
> the term grammar, the engine, every safety gate AND the evaluator's rule share one author
> lineage. Nothing here is independent scientific evidence or a statement about a real device.
> **Scientific acceptance: NOT PASSED. G-D: NOT PASSED.** No model, paid call, simulator (no
> Lumerical), network call from the evaluation or real experiment was used. Discovery is NOT
> connected to real research execution.
>
> **v1.1 (B4) remains the offline safety baseline.** No independent evaluation exists; v1.4 is not
> proposed as a replacement.

| | SHA |
|---|---|
| Baseline (v1.3 head) | `c022f3a` |
| Reproductions before any v1.4 code (v1.3 unchanged) | `6c0f698`, `06bc7d6` |
| v1.4 package, script, tests, v1.3 re-analysis, mutation entries | `3bb43cf` |
| **Design freeze F** (pushed before any seed was derived) | **`bff315f`** (`bff315f03b61a9f720593a0a691b5d9afa39445c`) |
| Held-out evidence (the single clean run) | `24c1df5` |
| Hidden-world example, frozen-evidence test, report draft | `7635925` |
| Status inventory, final report | later doc-only commits (head in the hand-off) |

Evidence: [`docs/audit/discovery-safety-v1.4-2026-11-21/`](../audit/discovery-safety-v1.4-2026-11-21/)
(`development.log`, `mutation_first_run.log`; `evidence/` with `v13_reanalysis.{json,log}`,
`manifest.json`, `results.json`, three row files, `run.log`, `hidden_example/`), produced by
`scripts/discovery_safety_v14_eval.py`. The frozen engine, every v1.0-v1.3 package file and every
earlier evidence directory are unchanged (the script checks their manifests before it runs).

**Scoring: SAI 3.5 candidate.5** (spec `61af6ef`). An asserted answer below SUPPORTED is
UNSUPPORTED_CLAIM (an error). Every input deciding SUPPORTED is computed by the evaluator from its
own hash-chained ledger; the arm registers identity, experiment and number of runs only. **One
evaluator, one rule: the v1.4 rule scores every arm**; the v1.3 rule's level is reported beside.
B4 (v1.1) never registers, so every B4 endorsement is UNSUPPORTED_CLAIM by convention; its
face-value columns (own correct / own error) are reported so the baseline is not misrepresented.

---

## 1. Summary

- **Mean-cost matching misled (shown on v1.3's own frozen rows, §2).** v1.3 called a cell
  COST_MATCHED when the arms' MEAN realized cost was close. World by world the costs were not
  close: e.g. benchmark cap 48, mean costs 19.97 vs 20.29, but per-world differences from -24 to +10
  units and 48/120 worlds more than 1 unit apart; held-out cap 6 was "COST_MATCHED" while B6 spent
  up to 4 units more on 21 worlds; B4 hit its cap on 97.5 % of benchmark worlds at cap 6 (B6: 82 %).
  v1.3's headline benchmark result at ~12 units, own-correct **-0.100 [-0.183, -0.017]
  COST_MATCHED**, becomes **-0.077 [-0.171, +0.009]** on 117 worlds matched one by one.
- **New method (`v14/costmatch.py`).** Each run at cap k is the arm's anytime answer for budget k.
  For an anchor cap K, each world is compared at the LOWER of the two arms' realized costs at K;
  the dearer arm contributes the answer it gave under a smaller cap at that cost (within ±1 unit);
  a world without such an answer is UNMATCHED and counted, never averaged. Cost quantiles and
  the cap-censored share are reported beside every table. The cap grid was made denser (6, 8, 10,
  12, 16, 24, 48) so that more worlds match.
- **Root cause of every residual false endorsement of v1.3 (§4): one evaluator defect and one
  missing rival class.** (1) v1.3 closed a rival when a passed test SEPARATED the predictions; the
  rival's own prediction passed the same runs (it often fitted them better). (2) The open-rival
  check ignored the grammar; and (2b, found during development) "no effect" was never held against
  a grammar-expressible effect. Fixed in the **evaluator rule** (closure only by a failed
  prediction; grammar rivals, one cause each; "no effect" against grammar shapes at their fit) and
  in the **arm** (B7's rival tests aim at 4.5 SD and close the most rivals per unit cost). Each
  failure was reproduced in a test committed before the fix.
- **Clean holdout: frozen at `bff315f`, pushed, then seeds derived from that commit id; run once
  (exit 0); evidence committed unchanged (`24c1df5`).** No re-freeze happened.
- **Held-out result (§5, §6).** B7 had **0 SUPPORTED errors in 2,464 B7 runs** (every setting and cap; e.g. 0/104 per cap on held-out primary, Wilson 95 % upper bound 3.6 %); B6 judged by
  its own v1.3 rule had 11 (8 held-out primary across caps, 3 benchmark). The price is abstention:
  at matched cost B7's face-value own-correct is **below** v1.1's in the control setting (cap 12:
  -0.244 [-0.346, -0.142]; cap 16: -0.433) and on the benchmark kinds (cap 12: -0.260 [-0.365,
  -0.156]); it catches up only at the largest caps where it also spends more (control cap 48:
  B7 121/128 correct at mean cost 29.2 vs v1.1 123/128 at 22.6; 67 of 128 worlds unmatched
  because B7 was dearer). On held-out primary worlds B7 beats B4 on own-error (-0.045 [-0.091,
  -0.011] at cap 12) and credits 7-10 validated new mechanisms per 104 worlds.
- **v1.1 (B4) stays the offline safety baseline.** v1.4 is safer at SUPPORTED but answers much
  less often below ~24 units; it is not a replacement candidate without an independent evaluation.

## 2. What the mean-cost match hid (v1.3's frozen rows re-read, development data)

`scripts/discovery_safety_v14_eval.py --reanalyse-v13` (`evidence/v13_reanalysis.{json,log}`;
reproducible with `--check`). "v1.3 basis" is what a ±1-unit interval on the MEAN cost difference
says (equal caps); the per-world columns use the new method (tolerance ±1, 2000 paired-bootstrap
resamples). Credited and own-correct are v1.3's categories as recorded in round 4.

| setting | cap | mean cost B6 vs B4 | v1.3 basis | per-world cost diff (min / p10 / p90 / max) | worlds beyond ±1 | at cap B6 / B4 | per-world matched (B6 dearer, B4 dearer) | own correct, per-world | credited, per-world |
|---|---|---|---|---|---|---|---|---|---|
| held_out_primary | 6 | 5.1692 vs 4.9462 | COST_MATCHED | -2 / -1 / 3 / 4 | 22/130 | 0.3846 / 0.6923 | 108/130 (21, 1) | +0.019 [+0.000, +0.046] | +0.130 [+0.065, +0.194] |
| held_out_primary | 8 | 6.7769 vs 6.0462 | COST_UNMATCHED | -4 / -2 / 5 / 5 | 56/130 | 0.4385 / 0.4692 | 108/130 (21, 1) | +0.019 [+0.000, +0.046] | +0.139 [+0.074, +0.204] |
| held_out_primary | 12 | 8.7154 vs 7.7846 | COST_UNMATCHED | -6 / -4 / 5 / 9 | 69/130 | 0.1615 / 0.3385 | 104/130 (24, 2) | +0.029 [+0.000, +0.067] | +0.144 [+0.077, +0.212] |
| held_out_primary | 24 | 10.9308 vs 9.9 | COST_UNMATCHED | -10 / -5 / 6 / 9 | 78/130 | 0.0077 / 0.0231 | 83/130 (28, 19) | +0.012 [+0.000, +0.036] | +0.193 [+0.108, +0.277] |
| held_out_primary | 48 | 11.8846 vs 10.2385 | COST_UNMATCHED | -14 / -1 / 6 / 9 | 67/130 | 0.0 / 0.0 | 95/130 (29, 6) | +0.000 [+0.000, +0.000] | +0.168 [+0.095, +0.253] |
| control | 6 | 5.9125 vs 5.9875 | COST_MATCHED | -3 / 0 / 0 / 1 | 2/160 | 0.9313 / 0.9875 | 158/160 (0, 2) | +0.234 [+0.152, +0.316] | +0.411 [+0.335, +0.487] |
| control | 8 | 7.8625 vs 7.9125 | COST_MATCHED | -5 / 0 / 0 / 2 | 8/160 | 0.9375 / 0.9187 | 158/160 (0, 2) | +0.215 [+0.127, +0.304] | +0.487 [+0.405, +0.563] |
| control | 12 | 11.5125 vs 11.75 | COST_MATCHED | -9 / -1 / 0 / 1 | 5/160 | 0.7125 / 0.8187 | 157/160 (0, 3) | +0.134 [+0.057, +0.223] | +0.726 [+0.656, +0.796] |
| control | 24 | 20.275 vs 21.15 | COST_UNMATCHED | -19 / -2 / 1 / 3 | 42/160 | 0.1125 / 0.1812 | 119/160 (4, 37) | +0.017 [+0.000, +0.042] | +0.975 [+0.941, +1.000] |
| control | 48 | 21.5875 vs 22.375 | COST_UNMATCHED | -19 / -3 / 2 / 4 | 61/160 | 0.0 / 0.0 | 105/160 (16, 39) | +0.000 [+0.000, +0.000] | +0.971 [+0.933, +1.000] |
| benchmark | 6 | 5.6833 vs 5.975 | COST_MATCHED | -3 / -2 / 0 / 1 | 12/120 | 0.8167 / 0.975 | 108/120 (0, 12) | +0.111 [+0.037, +0.194] | +0.148 [+0.083, +0.213] |
| benchmark | 8 | 7.4917 vs 7.7333 | COST_MATCHED | -4 / -1 / 0 / 1 | 4/120 | 0.7917 / 0.8583 | 118/120 (0, 2) | +0.076 [+0.000, +0.153] | +0.263 [+0.186, +0.339] |
| benchmark | 12 | 11.0667 vs 11.1583 | COST_MATCHED | -4 / -1 / 1 / 5 | 13/120 | 0.65 / 0.8167 | 117/120 (0, 3) | -0.077 [-0.171, +0.009] | +0.470 [+0.376, +0.564] |
| benchmark | 24 | 18.5583 vs 19.1083 | COST_UNMATCHED | -15 / -2 / 1 / 9 | 35/120 | 0.1583 / 0.125 | 95/120 (6, 19) | -0.053 [-0.105, +0.000] | +0.726 [+0.632, +0.811] |
| benchmark | 48 | 19.9667 vs 20.2917 | COST_UNMATCHED | -24 / -2 / 3 / 10 | 48/120 | 0.0 / 0.0 | 89/120 (10, 21) | +0.000 [-0.034, +0.034] | +0.753 [+0.663, +0.843] |

How it misleads, concretely:
1. **Different per-world costs under an equal mean.** Every "COST_MATCHED" cell above has worlds
   1-9 units apart in both directions (control cap 12: one world 9 units cheaper for B6).
2. **Early stopping and caps censor differently.** At cap 6 v1.1 ended at its cap on 69 % of
   held-out and 97.5 % of benchmark worlds; v1.3 on 38 % and 82 %. The cheaper arm stopped by its own
   choice, the dearer one was cut off: equal means, different processes.
3. **The paired difference is confounded by cost.** Splitting the benchmark cap-12 pairs by which
   arm spent more: own-correct difference -0.29 where B4 spent more (7 worlds), -0.09 within
   tolerance (107). The mean mixes them.
4. **Unmatched cells vanish under the old rule.** At caps 24/48 v1.3 printed COST_UNMATCHED and
   offered no matched estimate; the per-world method matches 83-119 worlds and states which arm
   was dearer on the rest.

## 3. Design (`src/lab_brain/discovery_safety/v14/`, beside v1.0-v1.3, none edited)

1. **Evaluator rule v1.4** (`model.EvaluatorRuleV14`, `rule.py`). v1.3's boundary is unchanged: the
   arm registers identity, experiment, runs (and an optional data digest); the evaluator refits
   each identity to the data recorded before the registration, owns sigma, alternatives and
   thresholds. Changes:
   - **closure**: a rival R of answer A is closed iff R's evaluator prediction (refitted to the data
     before a PASSED registration of A; for a "no effect" answer a catalog rival at its smallest
     declared effect) FAILS the pass test on that registration's runs, or a registration of R
     itself failed. Separation alone closes nothing.
   - **grammar rivals**: every grammar shape adequate on all data whose fitted prediction is >= 3
     combined SD from A's fitted prediction for 4 runs of some AVAILABLE experiment. A grammar
     shape is one cause (a declared composition is one cause moving two channels). "No effect"
     is held against grammar shapes at their fit (a shape fitted >= 3 SD from zero is evidence of an
     effect); catalog rivals of "no effect" stay at their smallest declared effects.
   - SUPPORTED iff a complete registration passed and is risky, Holm over its registrations rejects
     none, and no v1.4 rival is open.
2. **Arm B7** (`gate.py`, subclasses the v1.3 gate): decides by the public v1.4 verdict on its own
   record; rival tests register the claim (and the lead rival) for n <= 4 runs of one experiment
   chosen to reach 4.5 combined SD from as many open rivals as possible per unit cost (fallback:
   v1.3's 3-SD test of the strongest rival); up to 6 rival tests (v1.3: 4).
3. **Boundary** (preserved). Every arm ran in a separate OS process (`--arm-worker`), JSON messages
   only; the world, truth, meter and ledger stayed in the evaluator process. The five v1.3 ledger
   attacks (arm-supplied SD, alternatives, thresholds, labels, new-mechanism records) are refused
   under the v1.4 rule in `tests/unit/test_discovery_safety_v14.py`; B7's answers are identical in
   process and across the process boundary (same categories, costs, ledger heads, digests).
   Limits as in v1.3: same OS user, no sandbox.
4. **Hidden-world harness** (`--hidden-package P --hidden-sealed S`): the engine side reads only the
   engine package (`parse_engine_package`); the evaluator's laboratory serves the sealed worlds by
   opaque case id; B4, B6 and B7 run blind in their own processes at every cap; then `reveal`
   verifies every commitment before scoring under candidate.5 with per-world comparisons. A
   tabulated truth is judged by `truth_separation` (the engine's tau); non-stationary truths match
   nothing; aliased claims of an alias are INDISTINGUISHABLE (surrogate). A non-example file inside
   the repository is refused. **Demonstrated only on `example.hidden-worlds.json`** (§7).

## 4. Root causes of the residual false endorsements (development seeds only)

Reproduced on unchanged v1.3 in `tests/unit/test_discovery_safety_v14_reproduction.py`
(`6c0f698`, `06bc7d6`, before any v1.4 code); details in `development.log` §A.

| world (v1.3 round 4, now development) | v1.3 SUPPORTED wrong answer | root cause | v1.4 |
|---|---|---|---|
| held-out `leakage.substrate-06`, caps 24/48 | `scatter.sidewall` (force-fit) | cutback test: claim p = 0.022, rival `chain.polarization_drift` and "no effect" p = 0.19 pass the same run (separation 3.41) -- closed by separation; also 648 adequate grammar shapes separated | rule: rival stays open (169 open rivals); B7 abstains (correct) |
| aliased `geometry.width_wide-03`, cap 8 | `geometry.thickness` | catalog rivals legitimately refuted, but 270 adequate grammar shapes predict a power-sweep / width-array response >= 3 SD away; neither experiment was run | rule: grammar rivals open; B7 abstains |
| benchmark `noise_glitch-06`, cap 8 | `laser_drift+gap_small` | simpler rival `laser_drift` p = 0.48 on the run that "closed" it (claim p = 0.013) | rule: rival open; B7 abstains |
| benchmark `noise_only_null-04`, cap 8 (noise-only world) | `geometry.gap_large` | "no effect" p = 0.55 on the run that "closed" it (claim p = 0.012) | rule: "no effect" open; B7 abstains |
| held-out `geometry.gap_small-01` (base 8 000 000), cap 12 -- found in development | "no effect" (force-fit) | kappa 1.3, 1.1, 2.7 (sigma 1); "no effect" held only against catalog classes at smallest effects, and the coupling family was removed | rule: 543 grammar shapes fitted >= 3 SD from zero are rivals; B7 does not claim |

Scoring defect vs arm defect: closure-by-separation and the missing grammar rivals were defects
of the evaluator's rule (fixed in the rule; every arm is scored by it). The arm change only lets
B7 test against the stricter rule efficiently. Under the v1.4 rule B6's wrong endorsements become
UNSUPPORTED_CLAIM -- still errors under candidate.5.

## 5. Held-out results (fresh seeds derived from F, run once)

Seeds: `PLAN.held_out_seeds("bff315f03b61a9f720593a0a691b5d9afa39445c")` -> held-out worlds base
**3905077000** (8 per class: 128 worlds, 104 primary, 24 aliased; family-removed and control
settings), benchmark kinds base **3168619000** (12 per kind, 96 worlds); attempt 0 for both (no
overlap). Elapsed 5,450 s, exit 0. Every run stayed within its cap and every ledger verified.

Equal-cap tables (realized costs differ; the matched comparisons are in §6). "credited" =
EXACT + INDISTINGUISHABLE + VALIDATED_NEW at SUPPORTED under the v1.4 rule; "SUPPORTED (v1.3 rule)"
is the level the v1.3 rule would give the same answer.

#### held-out primary

| cap | arm | n | credited | SUPPORTED (v1.3 rule) | UNSUPPORTED_CLAIM (match) | FORCE_FIT / WRONG | false null | own correct / own error | cost mean / median / p90 / at cap |
|---|---|---|---|---|---|---|---|---|---|
| 6 | B4 | 104 | 0 | 0 (0) | 1 (0) | 0 / 0 | 0 | 103 / 1 | 5.0577 / 6.0 / 6.0 / 0.7115 |
| 6 | B6 | 104 | 7 | 7 (9) | 2 (1) | 0 / 0 | 0 | 103 / 1 | 5.0769 / 5.0 / 6.0 / 0.3269 |
| 6 | B7 | 104 | 7 | 7 (7) | 0 (0) | 0 / 0 | 0 | 104 / 0 | 5.0769 / 5.0 / 6.0 / 0.3269 |
| 8 | B4 | 104 | 0 | 0 (0) | 1 (0) | 0 / 0 | 0 | 103 / 1 | 6.2404 / 7.0 / 8.0 / 0.5 |
| 8 | B6 | 104 | 7 | 7 (10) | 3 (2) | 0 / 0 | 0 | 103 / 1 | 6.7019 / 7.0 / 8.0 / 0.3942 |
| 8 | B7 | 104 | 7 | 7 (7) | 0 (0) | 0 / 0 | 0 | 104 / 0 | 6.6827 / 7.0 / 8.0 / 0.3846 |
| 10 | B4 | 104 | 0 | 0 (0) | 5 (0) | 0 / 0 | 0 | 99 / 5 | 7.2019 / 8.0 / 10.0 / 0.4423 |
| 10 | B6 | 104 | 7 | 7 (16) | 9 (8) | 0 / 0 | 0 | 103 / 1 | 7.7981 / 8.0 / 10.0 / 0.2212 |
| 10 | B7 | 104 | 7 | 7 (7) | 0 (0) | 0 / 0 | 0 | 104 / 0 | 7.5865 / 7.0 / 10.0 / 0.1923 |
| 12 | B4 | 104 | 0 | 0 (0) | 4 (0) | 0 / 0 | 0 | 100 / 4 | 7.9327 / 8.0 / 12.0 / 0.3077 |
| 12 | B6 | 104 | 7 | 7 (27) | 20 (19) | 0 / 0 | 0 | 103 / 1 | 9.125 / 10.0 / 12.0 / 0.2019 |
| 12 | B7 | 104 | 7 | 7 (7) | 0 (0) | 0 / 0 | 0 | 104 / 0 | 8.7212 / 9.0 / 12.0 / 0.1442 |
| 16 | B4 | 104 | 0 | 0 (0) | 3 (0) | 0 / 0 | 0 | 101 / 3 | 9.1731 / 8.0 / 16.0 / 0.2019 |
| 16 | B6 | 104 | 8 | 8 (29) | 21 (19) | 0 / 0 | 0 | 102 / 2 | 10.0673 / 10.0 / 14.0 / 0.0673 |
| 16 | B7 | 104 | 7 | 7 (7) | 0 (0) | 0 / 0 | 0 | 104 / 0 | 9.6635 / 10.0 / 14.0 / 0.0673 |
| 24 | B4 | 104 | 0 | 0 (0) | 2 (0) | 0 / 0 | 0 | 102 / 2 | 10.1442 / 8.0 / 20.0 / 0.0481 |
| 24 | B6 | 104 | 10 | 10 (31) | 21 (20) | 0 / 0 | 0 | 103 / 1 | 11.3654 / 12.0 / 16.0 / 0.0288 |
| 24 | B7 | 104 | 9 | 9 (9) | 0 (0) | 0 / 0 | 0 | 104 / 0 | 11.0288 / 10.0 / 16.0 / 0.0481 |
| 48 | B4 | 104 | 0 | 0 (0) | 2 (0) | 0 / 0 | 0 | 102 / 2 | 10.5192 / 8.0 / 20.0 / 0.0096 |
| 48 | B6 | 104 | 10 | 10 (31) | 21 (20) | 0 / 0 | 0 | 103 / 1 | 12.25 / 12.0 / 20.0 / 0.0 |
| 48 | B7 | 104 | 10 | 10 (10) | 0 (0) | 0 / 0 | 0 | 104 / 0 | 11.9808 / 10.0 / 22.0 / 0.0 |

#### control

| cap | arm | n | credited | SUPPORTED (v1.3 rule) | UNSUPPORTED_CLAIM (match) | FORCE_FIT / WRONG | false null | own correct / own error | cost mean / median / p90 / at cap |
|---|---|---|---|---|---|---|---|---|---|
| 6 | B4 | 128 | 0 | 0 (0) | 23 (20) | 0 / 0 | 105 | 20 / 3 | 5.9688 / 6.0 / 6.0 / 0.9844 |
| 6 | B6 | 128 | 19 | 19 (43) | 24 (24) | 0 / 0 | 85 | 43 / 0 | 5.8906 / 6.0 / 6.0 / 0.9141 |
| 6 | B7 | 128 | 22 | 22 (21) | 0 (0) | 0 / 0 | 106 | 22 / 0 | 5.8906 / 6.0 / 6.0 / 0.9141 |
| 8 | B4 | 128 | 0 | 0 (0) | 37 (34) | 0 / 0 | 91 | 34 / 3 | 7.8906 / 8.0 / 8.0 / 0.9219 |
| 8 | B6 | 128 | 19 | 19 (51) | 32 (32) | 0 / 0 | 77 | 51 / 0 | 7.8438 / 8.0 / 8.0 / 0.9141 |
| 8 | B7 | 128 | 19 | 19 (19) | 0 (0) | 0 / 0 | 109 | 19 / 0 | 7.8438 / 8.0 / 8.0 / 0.9141 |
| 10 | B4 | 128 | 0 | 0 (0) | 54 (51) | 0 / 0 | 74 | 51 / 3 | 9.8203 / 10.0 / 10.0 / 0.875 |
| 10 | B6 | 128 | 33 | 33 (82) | 49 (49) | 0 / 0 | 46 | 82 / 0 | 9.8516 / 10.0 / 10.0 / 0.9141 |
| 10 | B7 | 128 | 37 | 37 (37) | 0 (0) | 0 / 0 | 91 | 37 / 0 | 9.8516 / 10.0 / 10.0 / 0.9141 |
| 12 | B4 | 128 | 0 | 0 (0) | 72 (69) | 0 / 0 | 56 | 69 / 3 | 11.7188 / 12.0 / 12.0 / 0.8047 |
| 12 | B6 | 128 | 33 | 33 (94) | 61 (61) | 0 / 0 | 34 | 94 / 0 | 11.7031 / 12.0 / 12.0 / 0.7266 |
| 12 | B7 | 128 | 41 | 41 (41) | 0 (0) | 0 / 0 | 87 | 41 / 0 | 11.8516 / 12.0 / 12.0 / 0.875 |
| 16 | B4 | 128 | 0 | 0 (0) | 112 (110) | 0 / 0 | 16 | 110 / 2 | 15.6016 / 16.0 / 16.0 / 0.75 |
| 16 | B6 | 128 | 37 | 37 (116) | 79 (79) | 0 / 0 | 12 | 116 / 0 | 15.6406 / 16.0 / 16.0 / 0.7344 |
| 16 | B7 | 128 | 54 | 54 (54) | 0 (0) | 0 / 0 | 74 | 54 / 0 | 15.7422 / 16.0 / 16.0 / 0.8359 |
| 24 | B4 | 128 | 0 | 0 (0) | 123 (122) | 0 / 0 | 5 | 122 / 1 | 21.1953 / 21.0 / 24.0 / 0.1875 |
| 24 | B6 | 128 | 46 | 46 (123) | 77 (77) | 0 / 0 | 5 | 123 / 0 | 20.5625 / 21.0 / 24.0 / 0.1016 |
| 24 | B7 | 128 | 87 | 87 (87) | 0 (0) | 0 / 0 | 41 | 87 / 0 | 22.4297 / 23.0 / 24.0 / 0.4766 |
| 48 | B4 | 128 | 0 | 0 (0) | 124 (123) | 0 / 0 | 4 | 123 / 1 | 22.6328 / 21.0 / 29.0 / 0.0 |
| 48 | B6 | 128 | 47 | 47 (123) | 76 (76) | 0 / 0 | 5 | 123 / 0 | 22.3359 / 21.0 / 31.0 / 0.0 |
| 48 | B7 | 128 | 121 | 121 (121) | 0 (0) | 0 / 0 | 7 | 121 / 0 | 29.1953 / 26.0 / 45.0 / 0.0781 |

#### benchmark

| cap | arm | n | credited | SUPPORTED (v1.3 rule) | UNSUPPORTED_CLAIM (match) | FORCE_FIT / WRONG | false null | own correct / own error | cost mean / median / p90 / at cap |
|---|---|---|---|---|---|---|---|---|---|
| 6 | B4 | 96 | 0 | 0 (0) | 10 (8) | 0 / 0 | 74 | 20 / 2 | 5.9896 / 6.0 / 6.0 / 0.9896 |
| 6 | B6 | 96 | 10 | 10 (13) | 3 (3) | 0 / 0 | 71 | 25 / 0 | 5.75 / 6.0 / 6.0 / 0.8333 |
| 6 | B7 | 96 | 10 | 10 (10) | 0 (0) | 0 / 0 | 74 | 22 / 0 | 5.75 / 6.0 / 6.0 / 0.8333 |
| 8 | B4 | 96 | 0 | 0 (0) | 29 (27) | 0 / 0 | 55 | 39 / 2 | 7.75 / 8.0 / 8.0 / 0.8542 |
| 8 | B6 | 96 | 12 | 12 (30) | 18 (18) | 0 / 0 | 54 | 42 / 0 | 7.5417 / 8.0 / 8.0 / 0.8125 |
| 8 | B7 | 96 | 12 | 12 (12) | 0 (0) | 0 / 0 | 72 | 24 / 0 | 7.5521 / 8.0 / 8.0 / 0.8229 |
| 10 | B4 | 96 | 0 | 0 (0) | 42 (40) | 0 / 0 | 42 | 52 / 2 | 9.4479 / 10.0 / 10.0 / 0.8021 |
| 10 | B6 | 96 | 22 | 22 (46) | 24 (22) | 0 / 0 | 38 | 56 / 2 | 9.3854 / 10.0 / 10.0 / 0.8333 |
| 10 | B7 | 96 | 22 | 22 (22) | 0 (0) | 0 / 0 | 62 | 34 / 0 | 9.3958 / 10.0 / 10.0 / 0.8438 |
| 12 | B4 | 96 | 0 | 0 (0) | 55 (53) | 0 / 0 | 29 | 65 / 2 | 11.1562 / 12.0 / 12.0 / 0.7604 |
| 12 | B6 | 96 | 27 | 27 (48) | 21 (21) | 0 / 0 | 36 | 60 / 0 | 11.2083 / 12.0 / 12.0 / 0.6667 |
| 12 | B7 | 96 | 28 | 28 (28) | 0 (0) | 0 / 0 | 56 | 40 / 0 | 11.3229 / 12.0 / 12.0 / 0.7812 |
| 16 | B4 | 96 | 0 | 0 (0) | 71 (70) | 0 / 0 | 13 | 82 / 1 | 14.1771 / 15.0 / 16.0 / 0.4479 |
| 16 | B6 | 96 | 34 | 34 (62) | 28 (28) | 0 / 0 | 22 | 74 / 0 | 14.5208 / 16.0 / 16.0 / 0.6354 |
| 16 | B7 | 96 | 42 | 42 (41) | 0 (0) | 0 / 0 | 42 | 54 / 0 | 14.5833 / 16.0 / 16.0 / 0.6875 |
| 24 | B4 | 96 | 0 | 0 (0) | 81 (80) | 0 / 0 | 3 | 92 / 1 | 18.8229 / 21.0 / 24.0 / 0.1146 |
| 24 | B6 | 96 | 35 | 35 (74) | 39 (38) | 0 / 0 | 10 | 85 / 1 | 18.7083 / 20.0 / 24.0 / 0.1562 |
| 24 | B7 | 96 | 53 | 53 (52) | 0 (0) | 0 / 0 | 31 | 65 / 0 | 20.1042 / 23.0 / 24.0 / 0.3333 |
| 48 | B4 | 96 | 0 | 0 (0) | 81 (80) | 0 / 0 | 3 | 92 / 1 | 19.6562 / 21.0 / 27.0 / 0.0 |
| 48 | B6 | 96 | 37 | 37 (79) | 42 (42) | 0 / 0 | 5 | 91 / 0 | 20.2812 / 20.0 / 31.0 / 0.0 |
| 48 | B7 | 96 | 77 | 77 (74) | 0 (0) | 0 / 0 | 7 | 89 / 0 | 24.5417 / 23.0 / 38.0 / 0.0104 |

Aliased held-out worlds (24): B7 had no SUPPORTED error at any cap; it credited 3 (cap 24) and 7
(cap 48: 6 aliases, 1 new mechanism) and otherwise abstained (false nulls, because an alias is a
correct-in-kind answer). B6: 1 credited at caps 24/48, 8 UNSUPPORTED_CLAIM.

SUPPORTED errors judged against the truth (any rule, face value): B7 **0** in every setting and
cap. B6 under its own v1.3 rule: held-out primary 8 (e.g. `leakage.substrate-03` claimed as
`scatter.sidewall` at caps 12/16/24, `geometry.gap_small-03` as "no effect" at cap 6 -- the same
two patterns as in §4), benchmark 3 (`noise_only_null-06` at cap 24, two partial composition
claims at cap 10). Under the v1.4 rule none of these is SUPPORTED.

## 6. Per-world matched comparisons (fresh held-out seeds)

Differences Y - X over the worlds matched at equal realized cost (±1 unit), paired-bootstrap 95 %
intervals; "(Y dearer, X dearer)" = unmatched worlds and which arm spent more there.

#### held-out primary (family removed, 104 worlds): B7-B4

| anchor cap | matched / worlds (Y dearer, X dearer) | cost point median | credited | errors (c5) | SUPPORTED errors | own correct | own error |
|---|---|---|---|---|---|---|---|
| 6 | 86/104 (15, 3) | 5.0 | +0.081 [+0.023, +0.151] | -0.012 [-0.035, +0.000] | +0.000 [+0.000, +0.000] | +0.012 [+0.000, +0.035] | -0.012 [-0.035, +0.000] |
| 8 | 89/104 (15, 0) | 6.0 | +0.079 [+0.022, +0.135] | -0.011 [-0.034, +0.000] | +0.000 [+0.000, +0.000] | +0.011 [+0.000, +0.034] | -0.011 [-0.034, +0.000] |
| 10 | 89/104 (15, 0) | 7.0 | +0.079 [+0.022, +0.135] | -0.022 [-0.056, +0.000] | +0.000 [+0.000, +0.000] | +0.022 [+0.000, +0.056] | -0.022 [-0.056, +0.000] |
| 12 | 88/104 (16, 0) | 8.0 | +0.080 [+0.023, +0.136] | -0.045 [-0.091, -0.011] | +0.000 [+0.000, +0.000] | +0.045 [+0.011, +0.091] | -0.045 [-0.091, -0.011] |
| 16 | 87/104 (16, 1) | 9.0 | +0.080 [+0.034, +0.138] | -0.034 [-0.080, +0.000] | +0.000 [+0.000, +0.000] | +0.034 [+0.000, +0.080] | -0.034 [-0.080, +0.000] |
| 24 | 73/104 (18, 13) | 8.0 | +0.096 [+0.041, +0.164] | -0.014 [-0.041, +0.000] | +0.000 [+0.000, +0.000] | +0.014 [+0.000, +0.041] | -0.014 [-0.041, +0.000] |
| 48 | 83/104 (18, 3) | 9.0 | +0.084 [+0.036, +0.157] | -0.012 [-0.036, +0.000] | +0.000 [+0.000, +0.000] | +0.012 [+0.000, +0.036] | -0.012 [-0.036, +0.000] |

#### held-out primary (family removed, 104 worlds): B6-B4

| anchor cap | matched / worlds (Y dearer, X dearer) | cost point median | credited | errors (c5) | SUPPORTED errors | own correct | own error |
|---|---|---|---|---|---|---|---|
| 6 | 86/104 (15, 3) | 5.0 | +0.081 [+0.023, +0.140] | +0.012 [-0.023, +0.058] | +0.000 [+0.000, +0.000] | +0.000 [-0.035, +0.035] | +0.000 [-0.035, +0.035] |
| 8 | 89/104 (15, 0) | 6.0 | +0.079 [+0.022, +0.135] | +0.011 [-0.022, +0.045] | +0.000 [+0.000, +0.000] | +0.000 [-0.034, +0.034] | +0.000 [-0.034, +0.034] |
| 10 | 89/104 (15, 0) | 7.0 | +0.079 [+0.022, +0.135] | +0.000 [-0.045, +0.045] | +0.000 [+0.000, +0.000] | +0.011 [-0.022, +0.056] | -0.011 [-0.056, +0.022] |
| 12 | 88/104 (16, 0) | 8.0 | +0.080 [+0.023, +0.136] | +0.000 [-0.057, +0.057] | +0.000 [+0.000, +0.000] | +0.034 [+0.000, +0.080] | -0.034 [-0.080, +0.000] |
| 16 | 87/104 (16, 1) | 9.0 | +0.092 [+0.034, +0.149] | +0.000 [-0.046, +0.046] | +0.000 [+0.000, +0.000] | +0.023 [+0.000, +0.057] | -0.023 [-0.057, +0.000] |
| 24 | 76/104 (16, 12) | 8.0 | +0.105 [+0.039, +0.184] | +0.026 [-0.026, +0.079] | +0.000 [+0.000, +0.000] | +0.013 [+0.000, +0.039] | -0.013 [-0.039, +0.000] |
| 48 | 85/104 (16, 3) | 9.0 | +0.094 [+0.035, +0.165] | +0.024 [-0.024, +0.071] | +0.000 [+0.000, +0.000] | +0.012 [+0.000, +0.035] | -0.012 [-0.035, +0.000] |

#### held-out primary (family removed, 104 worlds): B7-B6

| anchor cap | matched / worlds (Y dearer, X dearer) | cost point median | credited | errors (c5) | SUPPORTED errors | own correct | own error |
|---|---|---|---|---|---|---|---|
| 6 | 104/104 (0, 0) | 5.0 | +0.000 [+0.000, +0.000] | -0.019 [-0.048, +0.000] | +0.000 [+0.000, +0.000] | +0.010 [+0.000, +0.029] | -0.010 [-0.029, +0.000] |
| 8 | 104/104 (0, 0) | 7.0 | +0.000 [+0.000, +0.000] | -0.019 [-0.048, +0.000] | +0.000 [+0.000, +0.000] | +0.010 [+0.000, +0.029] | -0.010 [-0.029, +0.000] |
| 10 | 104/104 (0, 0) | 7.0 | +0.000 [+0.000, +0.000] | -0.029 [-0.067, +0.000] | +0.000 [+0.000, +0.000] | +0.010 [+0.000, +0.029] | -0.010 [-0.029, +0.000] |
| 12 | 104/104 (0, 0) | 9.0 | +0.000 [+0.000, +0.000] | -0.096 [-0.154, -0.038] | +0.000 [+0.000, +0.000] | +0.010 [+0.000, +0.029] | -0.010 [-0.029, +0.000] |
| 16 | 104/104 (0, 0) | 10.0 | -0.010 [-0.029, +0.000] | -0.106 [-0.163, -0.048] | +0.000 [+0.000, +0.000] | +0.019 [+0.000, +0.048] | -0.019 [-0.048, +0.000] |
| 24 | 102/104 (1, 1) | 10.0 | -0.010 [-0.029, +0.000] | -0.088 [-0.147, -0.039] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] |
| 48 | 102/104 (1, 1) | 10.0 | -0.010 [-0.029, +0.000] | -0.088 [-0.147, -0.039] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] |

#### control (family left in, 128 worlds): B7-B4

| anchor cap | matched / worlds (Y dearer, X dearer) | cost point median | credited | errors (c5) | SUPPORTED errors | own correct | own error |
|---|---|---|---|---|---|---|---|
| 6 | 126/128 (1, 1) | 6.0 | +0.167 [+0.103, +0.230] | -0.183 [-0.254, -0.119] | +0.000 [+0.000, +0.000] | +0.008 [-0.071, +0.087] | -0.024 [-0.056, +0.000] |
| 8 | 127/128 (1, 0) | 8.0 | +0.142 [+0.087, +0.205] | -0.291 [-0.370, -0.213] | +0.000 [+0.000, +0.000] | -0.126 [-0.213, -0.039] | -0.024 [-0.055, +0.000] |
| 10 | 127/128 (1, 0) | 10.0 | +0.244 [+0.165, +0.323] | -0.409 [-0.496, -0.323] | +0.000 [+0.000, +0.000] | -0.142 [-0.236, -0.039] | -0.024 [-0.055, +0.000] |
| 12 | 127/128 (1, 0) | 12.0 | +0.299 [+0.220, +0.378] | -0.567 [-0.654, -0.480] | +0.000 [+0.000, +0.000] | -0.244 [-0.346, -0.142] | -0.024 [-0.055, +0.000] |
| 16 | 127/128 (1, 0) | 16.0 | +0.417 [+0.331, +0.504] | -0.866 [-0.921, -0.803] | +0.000 [+0.000, +0.000] | -0.433 [-0.520, -0.339] | -0.016 [-0.039, +0.000] |
| 24 | 66/128 (50, 12) | 23.0 | +0.697 [+0.591, +0.803] | -0.955 [-1.000, -0.894] | +0.000 [+0.000, +0.000] | -0.258 [-0.364, -0.152] | +0.000 [+0.000, +0.000] |
| 48 | 50/128 (67, 11) | 23.0 | +0.800 [+0.680, +0.900] | -0.960 [-1.000, -0.900] | +0.000 [+0.000, +0.000] | -0.160 [-0.260, -0.060] | +0.000 [+0.000, +0.000] |

#### control (family left in, 128 worlds): B6-B4

| anchor cap | matched / worlds (Y dearer, X dearer) | cost point median | credited | errors (c5) | SUPPORTED errors | own correct | own error |
|---|---|---|---|---|---|---|---|
| 6 | 126/128 (1, 1) | 6.0 | +0.143 [+0.087, +0.206] | +0.008 [-0.087, +0.103] | +0.000 [+0.000, +0.000] | +0.175 [+0.079, +0.270] | -0.024 [-0.056, +0.000] |
| 8 | 127/128 (1, 0) | 8.0 | +0.142 [+0.087, +0.205] | -0.039 [-0.134, +0.055] | +0.000 [+0.000, +0.000] | +0.126 [+0.039, +0.213] | -0.024 [-0.055, +0.000] |
| 10 | 127/128 (1, 0) | 10.0 | +0.220 [+0.150, +0.291] | -0.063 [-0.181, +0.047] | +0.000 [+0.000, +0.000] | +0.181 [+0.071, +0.283] | -0.024 [-0.055, +0.000] |
| 12 | 127/128 (1, 0) | 12.0 | +0.236 [+0.165, +0.315] | -0.079 [-0.197, +0.039] | +0.000 [+0.000, +0.000] | +0.181 [+0.087, +0.283] | -0.024 [-0.055, +0.000] |
| 16 | 127/128 (1, 0) | 16.0 | +0.283 [+0.205, +0.362] | -0.244 [-0.346, -0.134] | +0.000 [+0.000, +0.000] | +0.055 [-0.008, +0.126] | -0.016 [-0.039, +0.000] |
| 24 | 91/128 (5, 32) | 21.0 | +0.341 [+0.242, +0.440] | -0.352 [-0.462, -0.253] | +0.000 [+0.000, +0.000] | +0.000 [-0.033, +0.033] | -0.011 [-0.033, +0.000] |
| 48 | 86/128 (16, 26) | 21.0 | +0.337 [+0.233, +0.442] | -0.360 [-0.465, -0.256] | +0.000 [+0.000, +0.000] | -0.012 [-0.035, +0.000] | -0.012 [-0.035, +0.000] |

#### control (family left in, 128 worlds): B7-B6

| anchor cap | matched / worlds (Y dearer, X dearer) | cost point median | credited | errors (c5) | SUPPORTED errors | own correct | own error |
|---|---|---|---|---|---|---|---|
| 6 | 128/128 (0, 0) | 6.0 | +0.023 [+0.000, +0.055] | -0.188 [-0.258, -0.117] | +0.000 [+0.000, +0.000] | -0.164 [-0.234, -0.102] | +0.000 [+0.000, +0.000] |
| 8 | 128/128 (0, 0) | 8.0 | +0.000 [+0.000, +0.000] | -0.250 [-0.328, -0.180] | +0.000 [+0.000, +0.000] | -0.250 [-0.328, -0.180] | +0.000 [+0.000, +0.000] |
| 10 | 128/128 (0, 0) | 10.0 | +0.031 [+0.008, +0.062] | -0.383 [-0.469, -0.305] | +0.000 [+0.000, +0.000] | -0.352 [-0.438, -0.266] | +0.000 [+0.000, +0.000] |
| 12 | 128/128 (0, 0) | 12.0 | +0.047 [+0.016, +0.086] | -0.477 [-0.562, -0.391] | +0.000 [+0.000, +0.000] | -0.430 [-0.516, -0.344] | +0.000 [+0.000, +0.000] |
| 16 | 128/128 (0, 0) | 16.0 | +0.133 [+0.078, +0.195] | -0.617 [-0.703, -0.531] | +0.000 [+0.000, +0.000] | -0.484 [-0.570, -0.398] | +0.000 [+0.000, +0.000] |
| 24 | 72/128 (56, 0) | 22.0 | +0.125 [+0.056, +0.208] | -0.347 [-0.458, -0.236] | +0.000 [+0.000, +0.000] | -0.222 [-0.319, -0.125] | +0.000 [+0.000, +0.000] |
| 48 | 61/128 (67, 0) | 22.0 | +0.131 [+0.049, +0.213] | -0.246 [-0.344, -0.148] | +0.000 [+0.000, +0.000] | -0.115 [-0.197, -0.049] | +0.000 [+0.000, +0.000] |

#### benchmark kinds (96 worlds): B7-B4

| anchor cap | matched / worlds (Y dearer, X dearer) | cost point median | credited | errors (c5) | SUPPORTED errors | own correct | own error |
|---|---|---|---|---|---|---|---|
| 6 | 89/96 (0, 7) | 6.0 | +0.112 [+0.056, +0.180] | -0.101 [-0.169, -0.045] | +0.000 [+0.000, +0.000] | +0.034 [-0.034, +0.112] | -0.022 [-0.056, +0.000] |
| 8 | 95/96 (0, 1) | 8.0 | +0.126 [+0.063, +0.200] | -0.295 [-0.389, -0.211] | +0.000 [+0.000, +0.000] | -0.147 [-0.253, -0.042] | -0.021 [-0.053, +0.000] |
| 10 | 96/96 (0, 0) | 10.0 | +0.219 [+0.135, +0.302] | -0.427 [-0.531, -0.323] | +0.000 [+0.000, +0.000] | -0.188 [-0.292, -0.083] | -0.021 [-0.052, +0.000] |
| 12 | 96/96 (0, 0) | 12.0 | +0.292 [+0.208, +0.396] | -0.573 [-0.667, -0.479] | +0.000 [+0.000, +0.000] | -0.260 [-0.365, -0.156] | -0.021 [-0.052, +0.000] |
| 16 | 87/96 (9, 0) | 15.0 | +0.448 [+0.345, +0.552] | -0.713 [-0.816, -0.621] | +0.000 [+0.000, +0.000] | -0.253 [-0.356, -0.161] | -0.011 [-0.034, +0.000] |
| 24 | 70/96 (20, 6) | 20.0 | +0.471 [+0.357, +0.586] | -0.786 [-0.871, -0.686] | +0.000 [+0.000, +0.000] | -0.314 [-0.429, -0.214] | +0.000 [+0.000, +0.000] |
| 48 | 60/96 (30, 6) | 19.0 | +0.517 [+0.400, +0.650] | -0.750 [-0.867, -0.633] | +0.000 [+0.000, +0.000] | -0.233 [-0.333, -0.133] | +0.000 [+0.000, +0.000] |

#### benchmark kinds (96 worlds): B6-B4

| anchor cap | matched / worlds (Y dearer, X dearer) | cost point median | credited | errors (c5) | SUPPORTED errors | own correct | own error |
|---|---|---|---|---|---|---|---|
| 6 | 89/96 (0, 7) | 6.0 | +0.112 [+0.056, +0.180] | -0.067 [-0.135, -0.011] | +0.000 [+0.000, +0.000] | +0.067 [+0.000, +0.146] | -0.022 [-0.056, +0.000] |
| 8 | 95/96 (0, 1) | 8.0 | +0.126 [+0.063, +0.200] | -0.105 [-0.179, -0.032] | +0.000 [+0.000, +0.000] | +0.042 [-0.032, +0.116] | -0.021 [-0.053, +0.000] |
| 10 | 96/96 (0, 0) | 10.0 | +0.219 [+0.135, +0.302] | -0.177 [-0.281, -0.073] | +0.000 [+0.000, +0.000] | +0.042 [-0.031, +0.115] | +0.000 [-0.042, +0.042] |
| 12 | 96/96 (0, 0) | 12.0 | +0.281 [+0.198, +0.385] | -0.354 [-0.458, -0.260] | +0.000 [+0.000, +0.000] | -0.052 [-0.125, +0.031] | -0.021 [-0.052, +0.000] |
| 16 | 86/96 (10, 0) | 15.0 | +0.395 [+0.291, +0.500] | -0.500 [-0.616, -0.372] | +0.000 [+0.000, +0.000] | -0.093 [-0.174, -0.012] | -0.012 [-0.035, +0.000] |
| 24 | 82/96 (6, 8) | 19.0 | +0.329 [+0.232, +0.427] | -0.402 [-0.512, -0.293] | +0.000 [+0.000, +0.000] | -0.073 [-0.134, -0.024] | +0.000 [-0.037, +0.037] |
| 48 | 77/96 (10, 9) | 19.0 | +0.351 [+0.247, +0.455] | -0.403 [-0.506, -0.286] | +0.000 [+0.000, +0.000] | -0.039 [-0.091, +0.000] | -0.013 [-0.039, +0.000] |

#### benchmark kinds (96 worlds): B7-B6

| anchor cap | matched / worlds (Y dearer, X dearer) | cost point median | credited | errors (c5) | SUPPORTED errors | own correct | own error |
|---|---|---|---|---|---|---|---|
| 6 | 96/96 (0, 0) | 6.0 | +0.000 [+0.000, +0.000] | -0.031 [-0.073, +0.000] | +0.000 [+0.000, +0.000] | -0.031 [-0.073, +0.000] | +0.000 [+0.000, +0.000] |
| 8 | 96/96 (0, 0) | 8.0 | +0.010 [+0.000, +0.031] | -0.188 [-0.271, -0.115] | +0.000 [+0.000, +0.000] | -0.177 [-0.260, -0.104] | +0.000 [+0.000, +0.000] |
| 10 | 96/96 (0, 0) | 10.0 | +0.000 [+0.000, +0.000] | -0.250 [-0.333, -0.167] | +0.000 [+0.000, +0.000] | -0.229 [-0.312, -0.156] | -0.021 [-0.052, +0.000] |
| 12 | 96/96 (0, 0) | 12.0 | +0.010 [+0.000, +0.031] | -0.219 [-0.302, -0.135] | +0.000 [+0.000, +0.000] | -0.208 [-0.292, -0.135] | +0.000 [+0.000, +0.000] |
| 16 | 95/96 (1, 0) | 16.0 | +0.084 [+0.021, +0.158] | -0.284 [-0.379, -0.200] | +0.000 [+0.000, +0.000] | -0.200 [-0.284, -0.116] | +0.000 [+0.000, +0.000] |
| 24 | 84/96 (11, 1) | 20.0 | +0.107 [+0.036, +0.179] | -0.357 [-0.464, -0.262] | +0.000 [+0.000, +0.000] | -0.238 [-0.333, -0.155] | -0.012 [-0.036, +0.000] |
| 48 | 68/96 (27, 1) | 19.0 | +0.132 [+0.059, +0.221] | -0.309 [-0.426, -0.206] | +0.000 [+0.000, +0.000] | -0.176 [-0.279, -0.088] | +0.000 [+0.000, +0.000] |

Reading (B7 / B6 vs the v1.1 baseline B4):
- **Held-out primary (unknown mechanism)**: B7 is never worse than v1.1 and makes fewer face-value
  errors (own-error -0.045 [-0.091, -0.011] at ~8 units); it credits 7-10 % validated new
  mechanisms (v1.1 cannot). 15-18 worlds per cap are unmatched because B7 spent more.
- **Control (truth in the catalog)**: B7 has no errors under candidate.5 but answers much less
  often than v1.1 at matched cost: own-correct -0.126 (8 units) to -0.433 (16 units); at the
  largest caps the matched subset shrinks (50/128 at cap 48, 67 worlds where B7 was dearer).
  B6 (v1.3) at matched cost was better than v1.1 at face value at 6-12 units and equal above.
- **Benchmark kinds**: same pattern: B7 own-correct -0.147 to -0.314 below v1.1 at 8-24 units.
- **B7 vs B6**: fewer errors under candidate.5 everywhere (B6's v1.3-rule endorsements are
  UNSUPPORTED_CLAIM under v1.4), but face-value own-correct is lower by 0.12-0.48 in control and
  0.03-0.24 on the benchmark kinds: the stricter evidence requirement costs answers that were
  right.

## 7. Hidden-world harness, demonstrated on the example file only

`--hidden-example` (`evidence/hidden_example/`): the example's 8 worlds, sealed with reproducible
example salts (a real set is sealed by its author with fresh salts), the engine package, blind runs
of B4/B6/B7 at every cap in separate processes, reveal verified against the commitments, scored
under candidate.5 with per-world comparisons. Result on the 8 example worlds (format material, not evidence about anything): at cap 48, B7 6 credited and 0 errors, B6 4 credited and 2 UNSUPPORTED_CLAIM, B4 6 UNSUPPORTED_CLAIM (all v1.1 endorsements are unregistered); per-world B7 - B4 at cap 48 matched 5 of 7 primary worlds. No hidden set was read, listed or run.
Run on a real set: `python scripts/discovery_safety_v14_eval.py --hidden-package P --hidden-sealed
S --out DIR` (both files outside the repository).

## 8. What failed, and the trade-offs

- **Abstention cost.** The fix removes every SUPPORTED error seen, but B7 is clearly below v1.1's
  face-value correct rate at matched cost below ~24 units in the control and benchmark settings.
  The grammar admits many adequate alternatives until power, width and wavelength dependence have
  been measured, and B7's budget runs out first (at-cap share at cap 24: control 48 % vs B6 10 %).
- **B7 spends more at large caps** (control cap 48 mean 29.2 vs 22.3 for B6 and 22.6 for B4), so
  many large-cap worlds are unmatched; its high large-cap credited count is partly bought with cost.
- **Multiple testing.** More registered tests mean more chances for a true claim to fail Holm (seen
  on a development `thermo.ambient` world whose ambient drift failed a 3-run wavelength test).
- Mutation battery: first run 9/10 killed (`safety_v14_failed_claim_test_closes_rival` survived);
  one test added; 10/10.
- Plan reduced for run time (8 per class, 12 per kind, 7 caps; v1.3: 10/15, 5 caps).

## 9. What remains scientifically unproven

- Everything is developer-authored: worlds, families, grammar, gates AND the evaluator's rule. The
  v1.4 conventions (grammar shapes as rivals, one cause per shape, 4-run distinguishability at 3 SD,
  "no effect" vs grammar at fit, tau_close 4.5) were chosen on development seeds by the same
  lineage. An independent rule and independent worlds are required.
- "Distinguishable" for grammar rivals is relative to the declared grammar; a mechanism outside it
  is still invisible. Smallest effects of interest for "no effect" remain the catalog's domains.
- Zero SUPPORTED errors in 2,464 B7 runs bounds the rate only for this world distribution (per-cap
  Wilson upper bound ~3.6 % on 104 held-out primary worlds).
- Per-world matching conditions on realized cost (a post-treatment variable): matched worlds are a
  selected subset; unmatched worlds are reported but not estimated.
- The process boundary is a same-user subprocess, not a sandbox.

## 10. Owner decisions

1. **Keep v1.1 as the baseline** (recommended; followed). v1.4 is safer at SUPPORTED but answers
   far less often at moderate budgets; neither v1.3 nor v1.4 should replace v1.1 without an
   independent evaluation.
2. **Adopt the per-world matched comparison (with cost quantiles and unmatched counts) as the
   standard for every cost claim** (recommended); retire mean-cost COST_MATCHED labels.
3. **Adopt "closure only by a failed prediction" in the evaluator rule** (recommended: it is a
   correctness fix). The grammar-rival requirement is a policy choice with a large abstention cost;
   recommend keeping it for SUPPORTED and reporting the answers it withholds as proposals.
4. Commission the independent hidden-world run of B4/B6/B7 with the harness here (needs the other
   author's sealed set and an evaluator who is not this lineage).

## 11. Verification

Code unchanged since `7635925` (later commits: status inventory and this report). CPython 3.13.18
in `.venv`, `PYTHONHASHSEED=12345` for every evaluation run.

| check | result |
|---|---|
| `ruff check src tests scripts` / `ruff format --check src tests scripts` | All checks passed / 663 files already formatted |
| `mypy` (strict, as the repository runs it) | no issues in 331 source files |
| focused: `test_discovery_safety_v14.py`, `..._v14_reproduction.py`, `e2e/test_discovery_safety_v14_frozen.py`, safety governance | pass (part of the runs below) |
| full default suite (`pytest -q`, no backend), at `3bb43cf` before the e2e test | 2701 passed, 1203 skipped, 0 failed |
| **full PostgreSQL suite at `7635925`** | **run by the lead at 7635925 on a fresh DB (`lib_d5full`, `migrate.py` twice: 81 applied, then up to date): 3905 passed, 4 skipped, 0 failed in 21 min 59 s (one complete run, exit 0).** (My own complete run at `7635925` on a fresh `lib_disc5`, `migrate.py` twice: 81 applied, then up to date, finished with 3905 passed, 4 skipped, 0 failed in 59 min 58 s; it ran concurrently with the `--check` run, and the lead's run is the one of record.) |
| `pytest tests/spec` | included in the full runs above (no failures) |
| `update_status.py` | regenerated after the full run; `--check`: up to date |
| `check_requirement_coverage.py` | passed (milestones DONE: M0a, M0b, M1, M2, M3) |
| held-out evidence `--check` (complete second run from F, CPython 3.13) | **every evidence file reproduced byte-identically** ("evidence is current"; 6,047 s). A reproduction, not a second look: nothing was changed or re-frozen |
| `--reanalyse-v13 --check` | reanalysis is current |
| hidden-world example | generated by the frozen script; reveal verified; not re-run under `--check` |
| mutation battery, `safety_v14_*` (10 entries, additions only) | first run 9/10 killed; one test added; 10/10 |
| `check_commit_messages.py` | no AI authorship found |
| `S35-` identifiers in `src/` or `tests/` | none |
| frozen engine, v1.0-v1.3 packages, `discovery_eval`, earlier evidence | unchanged (`git diff c022f3a` on them is empty; the script checks their manifests) |
| clean-holdout procedure | freeze `bff315f` pushed before seed derivation; seeds from its full id; one run (exit 0) committed unchanged at `24c1df5`; no re-freeze; no post-hoc bug found |
