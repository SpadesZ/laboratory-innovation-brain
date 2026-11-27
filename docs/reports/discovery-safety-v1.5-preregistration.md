# Discovery safety v1.5: pre-registration of the single clean held-out evaluation

Committed BEFORE the design freeze F6 and before any v1.5 held-out seed exists. Everything below is
fixed by `src/lab_brain/discovery_safety/v15/model.py` (`PLAN`, `SAFETY_V15`) and
`scripts/discovery_safety_v15_eval.py` as of F6; this file restates it in prose.

> ENGINEERING EVIDENCE ONLY on developer-authored synthetic worlds. Not independent, not a
> scientific validation, nothing about a real device. v1.1 (B4) remains the offline baseline.

## Arms

| arm | what | role |
|---|---|---|
| B4 | frozen engine + safety gate v1.1 | the offline safety BASELINE ("v1.1 baseline" and "B4" are the same arm) |
| B7 | safety gate v1.4, unchanged | the previous round's arm |
| B8 | safety gate v1.5 = B7 + rival-targeted experiment choice (`v15/gate.py`, entry point `safe_investigate_v15`) | the candidate |

B8 as frozen (`SAFETY_V15`): before the fixed-order signal probes, while some affordable option
(experiment, 1-4 runs) is expected to refute >= 0.5 open rivals (sum over open rivals of the
probability that the rival's evaluator prediction fails the chi-square pass test at alpha 0.01 if
the claim is true; noncentral chi-square under the declared noise and both predictive SDs), run the
option with the most expected refutations per unit cost, registering the claim and the rival most
likely to fail; at most 6 such targeted tests; then v1.2's phases (signal probes, support test, up
to 6 rival tests, null probes). A claim of "no effect" (and the parsimony fallback to it) runs
exactly as B7 (development found rival-first testing of "no effect" reaching a false SUPPORTED).

The evaluator rule is v1.4's (`EVALUATOR_RULE_V14`), unchanged, for every arm. Every input that
decides SUPPORTED is computed by the evaluator from its own hash-chained ledger; a rival closes only
by a failed prediction (or a failed registration of the rival itself); grammar rivals and
"no effect" vs grammar shapes stay. Arms run in separate OS processes (`--arm-worker`).

## Worlds, seeds, caps

- Held-out worlds: `held_out.held_out_worlds`, 8 per class (128 worlds: primary + aliased), in two
  settings: family REMOVED (held-out primary / aliased) and family LEFT IN (control).
- Benchmark kinds: `ring_scenario`, 12 per kind (96 worlds).
- Base seeds: derived AFTER F6 is pushed: `PLAN.held_out_seeds(F6 full commit id)`, i.e.
  `base = 3_000_000_000 + 1000 * (int(SHA-256("lab-brain/discovery-safety-v1.5/held-out-seeds@1"
  || 0x00 || role || 0x00 || F6 || 0x00 || attempt)) mod 1_000_000)`, roles `held-out-worlds` and
  `benchmark-worlds`, first attempt 0 whose base is >= 20 000 from every earlier range (including
  v1.4's spent 3905077000 / 3168619000) and from the other role. A rerun, if unavoidable, starts at
  attempt 2 and is reported.
- Caps: 6, 8, 10, 12, 16, 24, 48; every arm runs every world once per cap.

## Scoring and metrics

- SAI 3.5 candidate.5 categories (spec `61af6ef`); an answer below SUPPORTED that is asserted is
  UNSUPPORTED_CLAIM (an error). SUPPORTED errors = FORCE_FIT + WRONG_CLAIM.
- Face-value own-correct / own-error (v1.1's categories) beside, so the baseline is not
  misrepresented (B4 never registers, so every B4 claim is UNSUPPORTED_CLAIM by convention).
- Efficiency: rivals closed by a FAILED prediction (never by separation alone) per run and per cost
  unit, by kind (null / catalog / grammar), with refutations of truth-matching identities counted
  separately as incorrect.
- Abstention breakdown (evaluator-side diagnosis, `v15/diagnose.py`): for abstentions on worlds
  whose truth a held hypothesis expresses: correct (INDISTINGUISHABLE, TRUTH_TEST_FAILED),
  noise-limited (WEAK_RIVAL), budget-limited (BUDGET_EXHAUSTED), avoidable (TRUTH_NOT_AT_RISK,
  NEVER_TARGETED, TARGETED_SURVIVED, SPENT_ELSEWHERE).

## Comparisons and CI method

Per-world matching at equal realized cost (v1.4's method, tolerance +-1 unit; the dearer arm
contributes its anytime answer at the lower cost; unmatched worlds are counted, never averaged),
paired bootstrap over worlds, 2000 resamples, 95 % percentile intervals, seeded by label. Pairs:
B8-B7, B8-B4, B7-B4, at every cap, in held-out primary, held-out aliased, control and benchmark.

## Primary metric, anchors, decision rule

- Primary: B8 - B7 face-value own-correct, per-world matched, at anchors 12, 16 and 24, in the
  CONTROL and BENCHMARK settings (where the truth is expressible and v1.4's abstention cost was
  measured); held-out primary is reported with the same anchors.
- Safety condition (must hold for any positive conclusion): **SUPPORTED errors must not rise**: B8's
  SUPPORTED-error count (judged against the truth, any setting, any cap) is <= B7's, and the
  matched B8-B7 SUPPORTED-error difference has no interval wholly above 0 at any cap.
- Decision:
  - "B8 reduces avoidable abstention without spending safety" iff the safety condition holds AND
    the B8-B7 own-correct interval lies wholly above 0 at at least two of the three anchors in at
    least one of control/benchmark, and is not wholly below 0 at any anchor in any setting.
  - "No improvement" (null result) otherwise if the safety condition holds; "safety regression" if
    it fails. Each outcome is reported as found.
- B8 vs B4 (the v1.1 baseline) is reported at every cap with intervals; no decision about replacing
  v1.1 follows from this synthetic evaluation (v1.1 stays the baseline).

## Procedure

1. Commit this pre-registration. 2. Commit and push F6 (the frozen v1.5 package, scripts). 3. Only
then derive seeds from F6's full id; run `scripts/discovery_safety_v15_eval.py --design-freeze F6`
once; commit its outputs unchanged. 4. `--check` reproduces every evidence file byte-identically
(the manifest's hashed body; commit and environment fields excluded). A failed or aborted run is
reported, not silently rerun.
