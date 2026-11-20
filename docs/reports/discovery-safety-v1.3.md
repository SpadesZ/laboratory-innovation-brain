# Discovery safety v1.3: an evaluator-controlled evidence boundary, the noise-only root cause, matched-cost comparison

Date: 2026-11-15. Branch: `claude/lib-implementation-agent-47evs0-discovery-v13` (from the v1.2
head `e778cc4`). Pushed for Independent Chief Auditor review; not merged, not deployed.

> **ENGINEERING EVIDENCE ONLY** on developer-authored synthetic worlds. Worlds, held-out families,
> the term grammar, the engine, every safety gate AND the evaluator's rule share one author
> lineage. Nothing here is independent scientific evidence, a blind evaluation, or a statement
> about a real device. **Scientific acceptance: NOT PASSED. G-D: NOT PASSED.** No model, paid
> call, simulator (no Lumerical), network call from the evaluation, database write or real
> experiment was used. Discovery is NOT connected to real research execution.
>
> **v1.1 (B4) remains the current offline safety baseline** (Owner instruction). Neither v1.2 nor
> v1.3 is proposed as the new baseline in this report.

| | SHA |
|---|---|
| Baseline (v1.2 head) | `e778cc4` |
| Reproduction-before (v1.2 code unchanged; tests + log) | `8adc676` |
| v1.3 package and tests | `391ad81` |
| First design freeze (superseded, see §8) | `91c813f` (its evidence: `ab1841a`) |
| Second design freeze (superseded, see §8; its evidence was generated but not committed) | `04c4193` |
| **Design freeze** (v1.3 package, evaluation script, plan) | **`b46c397`** (`b46c397e1e0a48d306ee3ce5af8173a598d67d8b`) |
| Evidence, tests, mutation entries, report | later commits; the branch head is in the hand-off message |

Evidence: [`docs/audit/discovery-safety-v1.3-2026-11-11/`](../audit/discovery-safety-v1.3-2026-11-11/)
(`development.log`; `evidence/` with `reproduction_before.log`, `manifest.json`, `results.json`,
three row files, `run.log`, `interpreter_verification.json`), produced by
`scripts/discovery_safety_v13_reproduce_before.py` and `scripts/discovery_safety_v13_eval.py`.
The v1.0/v1.1/v1.2 evidence, the frozen engine (`src/lab_brain/discovery/`) and every v1.0/v1.1/v1.2
package file are unchanged (the script verifies their manifests before it runs).

**Scoring: SAI 3.5 candidate.5 (spec commit `61af6ef`)** -- `classify_outcome` with
`verified_evidence` (`arm_supplied_inputs`), `AnswerStance` / `assertion_status`, and
`outcome_report` counts. An answer the arm asserted, endorsed or acted on whose
evaluator-re-derived level is PROPOSAL is **UNSUPPORTED_CLAIM** -- an error, reported beside
FORCE_FIT and WRONG_CLAIM, whether or not it matches the truth (matches reported beside).
PROPOSAL_ONLY is only for an answer the arm itself labelled a proposal and did not act on; no arm
here presents its final answer that way, so PROPOSAL_ONLY is 0 everywhere. **Under candidate.5,
every endorsement of the engine (B2) and of v1.1 (B4) is UNSUPPORTED_CLAIM, because they never
register predictions. That is a consequence of the scoring convention, not a new finding about
v1.1's answers**; v1.1's own face-value metrics (its correct identifications and force-fits) are
reported in every table so that the baseline is not misrepresented.

---

## 1. Summary

- **The ICA finding is reproduced and closed by design.** On the unchanged v1.2 code an
  arm-supplied SD turned an engine force-fit into **FORCE_FIT / SUPPORTED**; arm-chosen
  alternatives, thresholds, labels and new-mechanism records each decided SUPPORTED (§2). In v1.3
  the arm registers only identity, experiment, runs and a data digest; every quantity that
  decides pass and riskiness is computed by the evaluator from its own hash-chained ledger (§3);
  all five attacks are refused in tests. Boundary achieved: every arm ran in a **separate OS
  process** that never received the world, truth, meter or ledger (JSON messages only); no
  OS-level sandbox.
- **v1.2 re-scored by the evaluator-controlled rule loses many of its SUPPORTED answers**: e.g.
  control, cap 24: v1.2's own payload rule 149 SUPPORTED, the v1.3 evaluator 125; held-out
  primary cap 24: 47 vs 37 (§5). Under candidate.5 the rest are UNSUPPORTED_CLAIM.
- **Noise-only root cause** (development seeds, §4): v1.2's rival and support tests were single
  runs that had to separate by 3 SD; the rivals of "no effect" (classes at their smallest declared
  amplitudes, 2.0-2.7 SD per run) could never be tested though 17-25 of 48 units were left; "no
  effect" could never be risky (measured against near-zero fitted alternatives); and the null was
  never reconsidered after a small-cap ladder claim. v1.3 (multi-run tests, smallest-declared-
  effect alternatives for "no effect", parsimony fallback): **fresh held-out noise-only worlds
  9/15 (cap 24) and 14/15 (cap 48) SUPPORTED exact, v1.2 0/15 and 0/15**; v1.1's own (unregistered)
  answers 15/15.
- **Matched realized cost, v1.3 (B6) vs the v1.1 baseline (B4), paired on identical worlds**
  (§6). On candidate.5 metrics B6 wins everywhere -- by construction, since B4 never registers.
  **On v1.1's own face-value terms the picture is mixed and v1.3 does NOT beat v1.1 overall:**
  own-correct difference B6 - B4 is positive at low cost (control +0.23 [0.16, 0.31] at ~6 units,
  +0.22 at ~8, +0.12 at ~12; held-out +0.04 at cap 12, COST_UNMATCHED), zero in the control at
  24/48 (COST_UNMATCHED), and **negative on the benchmark world kinds at 12 units (-0.10
  [-0.18, -0.02], COST_MATCHED) and at 24/48 (-0.067, -0.033, COST_UNMATCHED)**. Face-value errors
  are equal or lower for B6 except benchmark cap 8 (+0.017 [0, 0.042]).
- **v1.3's own SUPPORTED errors** on fresh worlds: held-out primary 1 force-fit at caps 24 and 48
  (`leakage.substrate-06` -> `scatter.sidewall`, which v1.1 also claims at face value), aliased 1
  wrong claim at cap 8, benchmark 2 wrong claims at cap 8 (one is a mechanism SUPPORTED on a
  noise-only world). v1.1 has no SUPPORTED errors only because it has no SUPPORTED answers.
- **Two re-freezes happened after held-out numbers had been seen** (§8). Neither changed decision
  logic, and every category, level, cost and ledger head of the final run equals the first run;
  but the held-out result is not "clean" in the strict sense: it was looked at before the final
  freeze.
- v1.1 stays the offline safety baseline. Scientific acceptance and G-D: NOT PASSED.

## 2. Reproduction before the fix (v1.2 code unchanged)

`scripts/discovery_safety_v13_reproduce_before.py` (log: `evidence/reproduction_before.log`; tests:
`tests/unit/test_discovery_safety_v13_reproduction.py`, committed at `8adc676` before any v1.3
code). Development world `held_out-chain.polarization_drift-00` and others, base 7_000_000.

| # | arm-supplied quantity | what the reproduction shows on v1.2 |
|---|---|---|
| R1 | predictive SD | The engine's force-fit `scatter.sidewall` (truth `chain.polarization_drift`, family removed) fails its honest prediction on `polarization_controlled` (p = 2.8e-7, max \|z\| 4.78). Registered with SD x 1000 and an alternative placed at 1e7, the v1.2 ledger re-scores it passed and risky: the evaluator's outcome becomes **FORCE_FIT / SUPPORTED** |
| R2 | alternatives | A prediction equal to the rival `thermo.ambient`'s own prediction, filed for `thermo.self_heating`, is "risky" against the arm's only alternative "none" and SUPPORTED; with the rival as alternative it is not risky. In v1.2's OWN registrations on development worlds (3 per class, both settings, budgets 12/24), **198 of 508 passed risky registrations were risky only against "none" while "no effect" was already refuted by the data registered before them** |
| R3 | rule thresholds | the payload carries `tau_risky`, `z_max`, `alpha`; with `tau_risky = 0` a riskless prediction (identical to its only alternative) is risky and SUPPORTED (alpha is partly protected: Holm uses the evaluator's alpha) |
| R4 | fingerprint label | `thermo.ambient`'s predicted values filed under `scatter.sidewall`'s fingerprint make `scatter.sidewall` SUPPORTED |
| R5 | new-mechanism forward model | the evaluator read the answered grammar candidate (tables, fingerprint) from the arm's run record: swapping its tables for another shape's keeps **SUPPORTED** and turns the category into WRONG_CLAIM |

## 3. Design: the evaluator-controlled boundary (`src/lab_brain/discovery_safety/v13/`)

v1.3 adds a subpackage; no v1.0/v1.1/v1.2 file and no engine file was edited.

1. **What the arm registers** (`ledger.py`): only an IDENTITY (a catalog hypothesis's forward-model
   fingerprint, a grammar shape's fingerprint, or "no effect"), an experiment, a number of runs
   n (1..4), and optionally a digest of the data it used (compared, never relied on). A v1.2
   payload handed to the v1.3 laboratory is reduced to its identity and experiment; its
   predicted values, SD, alternatives and rule are discarded.
2. **Ledger**: append-only, hash-chained (each event carries the SHA-256 of its body and its
   predecessor's chain value); MEASURE events are written by the evaluator's laboratory itself;
   each REGISTER event stores the evaluator's own digest of every measurement before it.
   `verify_chain` recomputes all of it before every score.
3. **What the evaluator computes** (`rule.py`, `EvaluatorRule`), for each registration, from the
   measurements it recorded BEFORE it: the identity refitted by the evaluator (a catalog
   hypothesis within its declared domain, a grammar shape by least squares, "no effect" = 0),
   predictive SD from its own fit covariance, noise = the instrument sigma it owns divided by
   sqrt(n); pass iff chi-square p >= 0.01 and every |z| <= 4 on the mean of the next n runs of
   that experiment. **Alternatives chosen by the evaluator**: every catalog hypothesis, every
   grammar shape and "no effect" ADEQUATE on the earlier data (global test, tolerant of one
   aberrant reading), at its own fit; for a "no effect" identity, every adequate catalog
   hypothesis at its **smallest declared effect** (the bound of its amplitude domain nearest
   zero, SD 0) -- an equivalence-style test whose smallest effects of interest are the catalog's
   declared domains. Risky iff >= 3 combined SD from at least one alternative.
4. **The evaluator's verdict** (`rule.verdict`): SUPPORTED iff (a) a complete registration passed
   and is risky, (b) Holm at family-wise 0.01 over all its complete registrations rejects none,
   and (c) **no open rival**: no rival -- "no effect" if it is still viable, and every viable
   catalog hypothesis with no more components that is distinguishable from the answer under the
   full experiment set -- that no passed registration separated from the answer and whose own
   registration never failed. (c) was added on development seeds after a glitch-driven claim on a
   noise world was SUPPORTED by a test risky only against an irrelevant alternative.
   A new-mechanism answer is rebuilt by the evaluator from its identity (the grammar shape,
   refitted to all data, band 0.5); it is held against "no effect" only (grammar shapes declare
   no domain to judge distinguishability).
5. **Boundary actually achieved.** In the evaluation every arm (B2, B4, B5, B6) runs in a
   **separate OS process** (a fresh interpreter, `--arm-worker`) that receives only its catalog
   as it holds it at case start, the available experiments and the cap; it reaches the
   laboratory only by JSON messages (`motivating`, `measure`, `register`, `register_v12`, `done`).
   The world, its truth, the meter and the ledger live only in the evaluator's process; the
   evaluator never unpickles anything an arm sends. A test shows the in-process and the
   process-separated runs give identical answers and ledger heads. Limits: the arm process and
   the evaluator run as the same OS user on one machine (no OS-level sandbox), and the arm
   process could import the catalog module (it already holds the catalog; it never sees a
   world). In-process use (`EvaluatorLaboratory`) is only an object-capability boundary.
6. **The v1.3 gate** (B6, `gate.py`, subclasses v1.2's gate): registers identities only;
   decides "is my claim supported?" with the evaluator's public rule on its own copy of the
   record; support and rival tests may use n runs (the smallest n at which the evaluator's
   separation reaches 3, if affordable); a rival is closed when a passed registration separated it
   or its own registration failed; and a **parsimony fallback**: if the claim is not endorsed
   while "no effect" is still viable and budget remains, "no effect" is assessed with what is
   left. Every v1.0/v1.1/v1.2 threshold, `signal_coverage = 1.0`, the anytime ladder and the
   gate-led claim are unchanged.

## 4. Root cause of v1.2's lost noise-only worlds (development seeds only)

`development.log` §C (`--diagnose-noise 25 --budgets 24,48`, benchmark base 1, 25 noise-only
worlds, v1.2 code unchanged). Every noise-only world carries a 7-sigma glitch on its first reading.

| v1.2 blocking reason | b24 | b48 |
|---|---|---|
| "no effect" claimed, rivals open AND no risky registered pass | 8 | 15 |
| "no effect" claimed, rivals open | 1 | 1 |
| "no effect" claimed, no risky registered pass only | 0 | 1 |
| non-null claim from the small-cap ladder; "no effect" stays an open rival and is never reconsidered | 13 | 5 |
| non-null claim at ladder cap 2-3 from the glitched first reading; CATALOG_INCOMPLETE | 3 | 3 |

- **Rivals can never be tested.** Open rivals of "no effect" are classes at their smallest
  amplitudes (`geometry.gap_large` 2.33, `leakage.substrate` 2.25, `nonlinear.tpa_fca` 2.71
  single-run units at the declared lower bound; 2.0-2.5 at their fit including parameter SD).
  v1.2's rival test is a single run that must separate by `tau_risky = 3`, so "no affordable test"
  is returned for every such rival, although the oracle (4 replicates, tau 5) calls them
  distinguishable -- and **17-25 units of the 48 were left unspent**.
- **"No effect" could never be risky.** v1.2 measured riskiness against the zero prediction (the
  null's own) and the best-fitting catalog alternatives, which on null data are fitted to near zero.
- **The null is never reconsidered** once the anytime ladder's small cap produced a mechanism
  claim from a few noisy readings.
- **Fix (v1.3)**: multi-run registered tests; null riskiness against smallest declared effects; the
  parsimony fallback. On development seeds noise-only identification went 0/5 -> 3/5 (b24) and
  5/5 (b48) (`development.log` §D1). The glitch-at-cap-2 cases are only partly addressed (the
  evaluator's one-outlier-tolerant viability; the ladder itself was not changed).

## 5. Results on FRESH held-out seeds (drawn after the freeze)

Seeds: `derived_base_seed(label)` with labels in `EvaluationPlanV13`: held-out worlds base
**3218044000** (10 per class: 160 worlds, 130 primary, 30 aliased), benchmark kinds base
**3729592000** (15 per kind, 120 worlds). The plan refuses any range within 20,000 of every
earlier range (v1.2's list, v1.2's own held-out ranges and every development range).
`--design-freeze b46c397` verified the v1.3 package and the script byte-identical to the freeze
before generating.

Columns: "credited" = EXACT + INDISTINGUISHABLE + VALIDATED_NEW at SUPPORTED; "UNSUPPORTED_CLAIM
(match)" = asserted answers below SUPPORTED (how many match the truth anyway; never credited);
FORCE_FIT / WRONG_CLAIM with 95 % Wilson intervals; "errors" = FORCE_FIT + WRONG_CLAIM +
UNSUPPORTED_CLAIM (candidate.5); "own correct / own error" = the answer at face value judged
against the truth (an abstention is correct when nothing held matches the truth); "v1.1-native" =
v1.1's legacy categories of the answer at face value (correct identification / force-fit). All
these tables are **equal-cap and COST_UNMATCHED**; matched comparisons are in §6.


#### held-out family REMOVED, primary

| cap | arm | n | credited (exact/indist/new) | asserted | SUPPORTED | UNSUPPORTED_CLAIM (match) | PROPOSAL_ONLY | FORCE_FIT | WRONG_CLAIM | errors | false null | correct abst. | own correct / own error | v1.1-native correct / force-fit | cost mean |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 6 | B2 | 130 | 0 (0/0/0) | 45 | 0 | 45 (0) | 0 | 0 | 0 | 45 | 0 | 85 | 85 / 45 | 0 / 39 | 4.6 |
| 6 | B4 | 130 | 0 (0/0/0) | 2 | 0 | 2 (0) | 0 | 0 | 0 | 2 | 0 | 128 | 128 / 2 | 0 / 0 | 4.9462 |
| 6 | B5 | 130 | 14 (0/0/14) | 15 | 15 | 0 (0) | 0 | 1 | 0 | 1 | 0 | 115 | 129 / 1 | 0 / 0 | 5.2615 |
| 6 | B6 | 130 | 14 (0/0/14) | 14 | 14 | 0 (0) | 0 | 0 | 0 | 0 | 0 | 116 | 130 / 0 | 0 / 0 | 5.1692 |
| 8 | B2 | 130 | 0 (0/0/0) | 45 | 0 | 45 (0) | 0 | 0 | 0 | 45 | 0 | 85 | 85 / 45 | 0 / 40 | 5.1462 |
| 8 | B4 | 130 | 0 (0/0/0) | 1 | 0 | 1 (0) | 0 | 0 | 0 | 1 | 0 | 129 | 129 / 1 | 0 / 0 | 6.0462 |
| 8 | B5 | 130 | 17 (0/0/17) | 27 | 19 | 8 (8) | 0 | 2 | 0 | 10 | 0 | 103 | 128 / 2 | 0 / 2 | 6.8923 |
| 8 | B6 | 130 | 17 (0/0/17) | 17 | 17 | 0 (0) | 0 | 0 | 0 | 0 | 0 | 113 | 130 / 0 | 0 / 0 | 6.7769 |
| 12 | B2 | 130 | 0 (0/0/0) | 58 | 0 | 58 (0) | 0 | 0 | 0 | 58 | 0 | 72 | 72 / 58 | 0 / 49 | 6.1538 |
| 12 | B4 | 130 | 0 (0/0/0) | 5 | 0 | 5 (0) | 0 | 0 | 0 | 5 | 0 | 125 | 125 / 5 | 0 / 2 | 7.7846 |
| 12 | B5 | 130 | 29 (0/0/29) | 38 | 29 | 9 (9) | 0 | 0 | 0 | 9 | 0 | 92 | 130 / 0 | 0 / 0 | 9.0538 |
| 12 | B6 | 130 | 29 (0/0/29) | 29 | 29 | 0 (0) | 0 | 0 | 0 | 0 | 0 | 101 | 130 / 0 | 0 / 0 | 8.7154 |
| 24 | B2 | 130 | 0 (0/0/0) | 78 | 0 | 78 (0) | 0 | 0 | 0 | 78 | 0 | 52 | 52 / 78 | 0 / 59 | 7.0846 |
| 24 | B4 | 130 | 0 (0/0/0) | 2 | 0 | 2 (0) | 0 | 0 | 0 | 2 | 0 | 128 | 128 / 2 | 0 / 1 | 9.9 |
| 24 | B5 | 130 | 36 (0/0/36) | 47 | 37 | 10 (10) | 0 | 1 | 0 | 11 | 0 | 83 | 129 / 1 | 0 / 1 | 11.1615 |
| 24 | B6 | 130 | 41 (0/0/41) | 42 | 42 | 0 (0) | 0 | 1 | 0 | 1 | 0 | 88 | 129 / 1 | 0 / 1 | 10.9308 |
| 48 | B2 | 130 | 0 (0/0/0) | 79 | 0 | 79 (0) | 0 | 0 | 0 | 79 | 0 | 51 | 51 / 79 | 0 / 60 | 7.1154 |
| 48 | B4 | 130 | 0 (0/0/0) | 3 | 0 | 3 (0) | 0 | 0 | 0 | 3 | 0 | 127 | 127 / 3 | 0 / 1 | 10.2385 |
| 48 | B5 | 130 | 36 (0/0/36) | 47 | 37 | 10 (10) | 0 | 1 | 0 | 11 | 0 | 83 | 129 / 1 | 0 / 1 | 12.0077 |
| 48 | B6 | 130 | 41 (0/0/41) | 42 | 42 | 0 (0) | 0 | 1 | 0 | 1 | 0 | 88 | 129 / 1 | 0 / 1 | 11.8846 |

#### held-out family REMOVED, aliased

| cap | arm | n | credited (exact/indist/new) | asserted | SUPPORTED | UNSUPPORTED_CLAIM (match) | PROPOSAL_ONLY | FORCE_FIT | WRONG_CLAIM | errors | false null | correct abst. | own correct / own error | v1.1-native correct / force-fit | cost mean |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 6 | B2 | 30 | 0 (0/0/0) | 16 | 0 | 16 (3) | 0 | 0 | 0 | 16 | 14 | 0 | 3 / 13 | 0 / 10 | 5.8667 |
| 6 | B4 | 30 | 0 (0/0/0) | 1 | 0 | 1 (0) | 0 | 0 | 0 | 1 | 29 | 0 | 0 / 1 | 0 / 0 | 5.9667 |
| 6 | B5 | 30 | 0 (0/0/0) | 2 | 0 | 2 (0) | 0 | 0 | 0 | 2 | 28 | 0 | 0 / 2 | 0 / 0 | 5.8333 |
| 6 | B6 | 30 | 0 (0/0/0) | 0 | 0 | 0 (0) | 0 | 0 | 0 | 0 | 30 | 0 | 0 / 0 | 0 / 0 | 5.8667 |
| 8 | B2 | 30 | 0 (0/0/0) | 23 | 0 | 23 (8) | 0 | 0 | 0 | 23 | 7 | 0 | 8 / 15 | 0 / 11 | 6.8667 |
| 8 | B4 | 30 | 0 (0/0/0) | 3 | 0 | 3 (0) | 0 | 0 | 0 | 3 | 27 | 0 | 0 / 3 | 0 / 0 | 7.9333 |
| 8 | B5 | 30 | 0 (0/0/0) | 2 | 1 | 1 (0) | 0 | 0 | 1 | 2 | 28 | 0 | 0 / 2 | 0 / 1 | 7.7333 |
| 8 | B6 | 30 | 0 (0/0/0) | 1 | 1 | 0 (0) | 0 | 0 | 1 | 1 | 29 | 0 | 0 / 1 | 0 / 1 | 7.7667 |
| 12 | B2 | 30 | 0 (0/0/0) | 30 | 0 | 30 (14) | 0 | 0 | 0 | 30 | 0 | 0 | 14 / 16 | 0 / 11 | 7.8 |
| 12 | B4 | 30 | 0 (0/0/0) | 10 | 0 | 10 (6) | 0 | 0 | 0 | 10 | 20 | 0 | 6 / 4 | 0 / 1 | 11.1 |
| 12 | B5 | 30 | 3 (0/3/0) | 5 | 3 | 2 (2) | 0 | 0 | 0 | 2 | 25 | 0 | 5 / 0 | 0 / 0 | 10.3667 |
| 12 | B6 | 30 | 3 (0/3/0) | 3 | 3 | 0 (0) | 0 | 0 | 0 | 0 | 27 | 0 | 3 / 0 | 0 / 0 | 10.5333 |
| 24 | B2 | 30 | 0 (0/0/0) | 30 | 0 | 30 (14) | 0 | 0 | 0 | 30 | 0 | 0 | 14 / 16 | 0 / 11 | 7.8667 |
| 24 | B4 | 30 | 0 (0/0/0) | 13 | 0 | 13 (13) | 0 | 0 | 0 | 13 | 17 | 0 | 13 / 0 | 0 / 0 | 16.4667 |
| 24 | B5 | 30 | 4 (0/4/0) | 12 | 4 | 8 (8) | 0 | 0 | 0 | 8 | 18 | 0 | 12 / 0 | 0 / 0 | 14.3667 |
| 24 | B6 | 30 | 11 (0/11/0) | 11 | 11 | 0 (0) | 0 | 0 | 0 | 0 | 19 | 0 | 11 / 0 | 0 / 0 | 15.3333 |
| 48 | B2 | 30 | 0 (0/0/0) | 30 | 0 | 30 (14) | 0 | 0 | 0 | 30 | 0 | 0 | 14 / 16 | 0 / 11 | 7.8667 |
| 48 | B4 | 30 | 0 (0/0/0) | 13 | 0 | 13 (13) | 0 | 0 | 0 | 13 | 17 | 0 | 13 / 0 | 0 / 0 | 16.4667 |
| 48 | B5 | 30 | 4 (0/4/0) | 12 | 4 | 8 (8) | 0 | 0 | 0 | 8 | 18 | 0 | 12 / 0 | 0 / 0 | 14.3667 |
| 48 | B6 | 30 | 12 (0/12/0) | 12 | 12 | 0 (0) | 0 | 0 | 0 | 0 | 18 | 0 | 12 / 0 | 0 / 0 | 15.6 |

#### control (family LEFT IN)

| cap | arm | n | credited (exact/indist/new) | asserted | SUPPORTED | UNSUPPORTED_CLAIM (match) | PROPOSAL_ONLY | FORCE_FIT | WRONG_CLAIM | errors | false null | correct abst. | own correct / own error | v1.1-native correct / force-fit | cost mean |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 6 | B2 | 160 | 0 (0/0/0) | 77 | 0 | 77 (72) | 0 | 0 | 0 | 77 | 83 | 0 | 72 / 5 | 72 / 0 | 5.4437 |
| 6 | B4 | 160 | 0 (0/0/0) | 29 | 0 | 29 (28) | 0 | 0 | 0 | 29 | 131 | 0 | 28 / 1 | 28 / 0 | 5.9875 |
| 6 | B5 | 160 | 62 (62/0/0) | 75 | 62 | 13 (13) | 0 | 0 | 0 | 13 | 85 | 0 | 75 / 0 | 75 / 0 | 5.9062 |
| 6 | B6 | 160 | 65 (65/0/0) | 65 | 65 | 0 (0) | 0 | 0 | 0 | 0 | 95 | 0 | 65 / 0 | 65 / 0 | 5.9125 |
| 8 | B2 | 160 | 0 (0/0/0) | 109 | 0 | 109 (103) | 0 | 0 | 0 | 109 | 51 | 0 | 103 / 6 | 103 / 0 | 6.5125 |
| 8 | B4 | 160 | 0 (0/0/0) | 46 | 0 | 46 (43) | 0 | 0 | 0 | 46 | 114 | 0 | 43 / 3 | 43 / 0 | 7.9125 |
| 8 | B5 | 160 | 75 (75/0/0) | 86 | 75 | 11 (11) | 0 | 0 | 0 | 11 | 74 | 0 | 86 / 0 | 86 / 0 | 7.8563 |
| 8 | B6 | 160 | 78 (78/0/0) | 78 | 78 | 0 (0) | 0 | 0 | 0 | 0 | 82 | 0 | 78 / 0 | 78 / 0 | 7.8625 |
| 12 | B2 | 160 | 0 (0/0/0) | 143 | 0 | 143 (137) | 0 | 0 | 0 | 143 | 17 | 0 | 137 / 6 | 137 / 0 | 7.6688 |
| 12 | B4 | 160 | 0 (0/0/0) | 98 | 0 | 98 (95) | 0 | 0 | 0 | 98 | 62 | 0 | 95 / 3 | 95 / 0 | 11.75 |
| 12 | B5 | 160 | 90 (90/0/0) | 126 | 90 | 36 (36) | 0 | 0 | 0 | 36 | 34 | 0 | 126 / 0 | 126 / 0 | 11.5125 |
| 12 | B6 | 160 | 114 (114/0/0) | 114 | 114 | 0 (0) | 0 | 0 | 0 | 0 | 46 | 0 | 114 / 0 | 114 / 0 | 11.5125 |
| 24 | B2 | 160 | 0 (0/0/0) | 159 | 0 | 159 (153) | 0 | 0 | 0 | 159 | 1 | 0 | 153 / 6 | 153 / 0 | 8.2 |
| 24 | B4 | 160 | 0 (0/0/0) | 152 | 0 | 152 (152) | 0 | 0 | 0 | 152 | 8 | 0 | 152 / 0 | 152 / 0 | 21.15 |
| 24 | B5 | 160 | 125 (125/0/0) | 149 | 125 | 24 (24) | 0 | 0 | 0 | 24 | 11 | 0 | 149 / 0 | 149 / 0 | 20.0063 |
| 24 | B6 | 160 | 152 (152/0/0) | 152 | 152 | 0 (0) | 0 | 0 | 0 | 0 | 8 | 0 | 152 / 0 | 152 / 0 | 20.275 |
| 48 | B2 | 160 | 0 (0/0/0) | 160 | 0 | 160 (154) | 0 | 0 | 0 | 160 | 0 | 0 | 154 / 6 | 154 / 0 | 8.2312 |
| 48 | B4 | 160 | 0 (0/0/0) | 154 | 0 | 154 (154) | 0 | 0 | 0 | 154 | 6 | 0 | 154 / 0 | 154 / 0 | 22.375 |
| 48 | B5 | 160 | 121 (121/0/0) | 149 | 121 | 28 (28) | 0 | 0 | 0 | 28 | 11 | 0 | 149 / 0 | 149 / 0 | 21.15 |
| 48 | B6 | 160 | 152 (152/0/0) | 152 | 152 | 0 (0) | 0 | 0 | 0 | 0 | 8 | 0 | 152 / 0 | 152 / 0 | 21.5875 |

#### benchmark world kinds

| cap | arm | n | credited (exact/indist/new) | asserted | SUPPORTED | UNSUPPORTED_CLAIM (match) | PROPOSAL_ONLY | FORCE_FIT | WRONG_CLAIM | errors | false null | correct abst. | own correct / own error | v1.1-native correct / force-fit | cost mean |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 6 | B2 | 120 | 0 (0/0/0) | 42 | 0 | 42 (38) | 0 | 0 | 0 | 42 | 63 | 15 | 53 / 4 | 38 / 3 | 5.5333 |
| 6 | B4 | 120 | 0 (0/0/0) | 4 | 0 | 4 (4) | 0 | 0 | 0 | 4 | 101 | 15 | 19 / 0 | 4 / 0 | 5.975 |
| 6 | B5 | 120 | 18 (18/0/0) | 21 | 18 | 3 (3) | 0 | 0 | 0 | 3 | 84 | 15 | 36 / 0 | 21 / 0 | 5.6 |
| 6 | B6 | 120 | 16 (16/0/0) | 16 | 16 | 0 (0) | 0 | 0 | 0 | 0 | 89 | 15 | 31 / 0 | 16 / 0 | 5.6833 |
| 8 | B2 | 120 | 0 (0/0/0) | 65 | 0 | 65 (61) | 0 | 0 | 0 | 65 | 40 | 15 | 76 / 4 | 61 / 3 | 6.65 |
| 8 | B4 | 120 | 0 (0/0/0) | 22 | 0 | 22 (22) | 0 | 0 | 0 | 22 | 83 | 15 | 37 / 0 | 22 / 0 | 7.7333 |
| 8 | B5 | 120 | 31 (31/0/0) | 33 | 31 | 2 (2) | 0 | 0 | 0 | 2 | 72 | 15 | 48 / 0 | 33 / 0 | 7.3417 |
| 8 | B6 | 120 | 30 (30/0/0) | 32 | 32 | 0 (0) | 0 | 0 | 2 | 2 | 73 | 15 | 45 / 2 | 30 / 2 | 7.4917 |
| 12 | B2 | 120 | 0 (0/0/0) | 93 | 0 | 93 (86) | 0 | 0 | 0 | 93 | 12 | 15 | 101 / 7 | 86 / 4 | 7.725 |
| 12 | B4 | 120 | 0 (0/0/0) | 70 | 0 | 70 (66) | 0 | 0 | 0 | 70 | 35 | 15 | 81 / 4 | 66 / 2 | 11.1583 |
| 12 | B5 | 120 | 49 (49/0/0) | 58 | 50 | 8 (8) | 0 | 0 | 1 | 9 | 47 | 15 | 72 / 1 | 57 / 1 | 10.825 |
| 12 | B6 | 120 | 54 (54/0/0) | 54 | 54 | 0 (0) | 0 | 0 | 0 | 0 | 51 | 15 | 69 / 0 | 54 / 0 | 11.0667 |
| 24 | B2 | 120 | 0 (0/0/0) | 105 | 0 | 105 (97) | 0 | 0 | 0 | 105 | 0 | 15 | 112 / 8 | 97 / 4 | 8.3917 |
| 24 | B4 | 120 | 0 (0/0/0) | 99 | 0 | 99 (97) | 0 | 0 | 0 | 99 | 6 | 15 | 112 / 2 | 97 / 1 | 19.1083 |
| 24 | B5 | 120 | 69 (69/0/0) | 81 | 70 | 11 (11) | 0 | 0 | 1 | 12 | 24 | 15 | 95 / 1 | 80 / 1 | 18.025 |
| 24 | B6 | 120 | 89 (89/0/0) | 89 | 89 | 0 (0) | 0 | 0 | 0 | 0 | 16 | 15 | 104 / 0 | 89 / 0 | 18.5583 |
| 48 | B2 | 120 | 0 (0/0/0) | 105 | 0 | 105 (97) | 0 | 0 | 0 | 105 | 0 | 15 | 112 / 8 | 97 / 4 | 8.3917 |
| 48 | B4 | 120 | 0 (0/0/0) | 100 | 0 | 100 (97) | 0 | 0 | 0 | 100 | 5 | 15 | 112 / 3 | 97 / 2 | 20.2917 |
| 48 | B5 | 120 | 68 (68/0/0) | 80 | 69 | 11 (11) | 0 | 0 | 1 | 12 | 25 | 15 | 94 / 1 | 79 / 1 | 18.8417 |
| 48 | B6 | 120 | 93 (93/0/0) | 93 | 93 | 0 (0) | 0 | 0 | 0 | 0 | 12 | 15 | 108 / 0 | 93 / 0 | 19.9667 |

#### B5 under v1.2's own payload rule (candidate.4 reading) vs the v1.3 evaluator
held-out primary {'12': (38, 29), '24': (47, 37), '48': (47, 37), '6': (15, 15), '8': (27, 19)}
control {'12': (126, 90), '24': (149, 125), '48': (149, 121), '6': (75, 62), '8': (86, 75)}
benchmark {'12': (58, 50), '24': (81, 70), '48': (80, 69), '6': (21, 18), '8': (33, 31)}

#### noise_only per kind
composition {'24': {'B2': (0, 12, 15), 'B4': (0, 12, 13), 'B5': (8, 12, 5), 'B6': (12, 12, 0)}, '48': {'B2': (0, 12, 15), 'B4': (0, 12, 13), 'B5': (8, 12, 5), 'B6': (12, 12, 0)}}
confounded_measurement_chain {'24': {'B2': (0, 15, 15), 'B4': (0, 15, 15), 'B5': (15, 15, 0), 'B6': (15, 15, 0)}, '48': {'B2': (0, 15, 15), 'B4': (0, 15, 15), 'B5': (15, 15, 0), 'B6': (15, 15, 0)}}
in_catalog_single {'24': {'B2': (0, 15, 15), 'B4': (0, 15, 15), 'B5': (11, 14, 3), 'B6': (14, 14, 0)}, '48': {'B2': (0, 15, 15), 'B4': (0, 15, 15), 'B5': (11, 14, 3), 'B6': (14, 14, 0)}}
inseparable_pair {'24': {'B2': (0, 15, 15), 'B4': (0, 15, 15), 'B5': (15, 15, 0), 'B6': (15, 15, 0)}, '48': {'B2': (0, 15, 15), 'B4': (0, 15, 15), 'B5': (15, 15, 0), 'B6': (15, 15, 0)}}
noise_glitch {'24': {'B2': (0, 15, 15), 'B4': (0, 15, 15), 'B5': (10, 13, 3), 'B6': (13, 13, 0)}, '48': {'B2': (0, 15, 15), 'B4': (0, 15, 15), 'B5': (10, 13, 3), 'B6': (13, 13, 0)}}
noise_only_null {'24': {'B2': (0, 15, 15), 'B4': (0, 15, 15), 'B5': (0, 0, 0), 'B6': (9, 9, 0)}, '48': {'B2': (0, 15, 15), 'B4': (0, 15, 15), 'B5': (0, 0, 0), 'B6': (14, 14, 0)}}
outside_all_declared {'24': {'B2': (0, 15, 0), 'B4': (0, 15, 0), 'B5': (0, 15, 0), 'B6': (0, 15, 0)}, '48': {'B2': (0, 15, 0), 'B4': (0, 15, 0), 'B5': (0, 15, 0), 'B6': (0, 15, 0)}}
outside_initial_prior {'24': {'B2': (0, 10, 15), 'B4': (0, 10, 11), 'B5': (10, 11, 1), 'B6': (11, 11, 0)}, '48': {'B2': (0, 10, 15), 'B4': (0, 10, 12), 'B5': (9, 10, 1), 'B6': (10, 10, 0)}}

#### matched: held-out primary

| Y@cap - X@cap | basis | cost Y vs X | credited | errors (c5) | SUPPORTED errors | own correct | own error |
|---|---|---|---|---|---|---|---|
| B6@6 - B4@6 | COST_MATCHED | 5.1692 vs 4.9462 | +0.108 [+0.054, +0.162] | -0.015 [-0.038, +0.000] | +0.000 [+0.000, +0.000] | +0.015 [+0.000, +0.038] | -0.015 [-0.038, +0.000] |
| B6@8 - B4@8 | COST_UNMATCHED | 6.7769 vs 6.0462 | +0.131 [+0.077, +0.192] | -0.008 [-0.023, +0.000] | +0.000 [+0.000, +0.000] | +0.008 [+0.000, +0.023] | -0.008 [-0.023, +0.000] |
| B6@12 - B4@12 | COST_UNMATCHED | 8.7154 vs 7.7846 | +0.223 [+0.154, +0.292] | -0.038 [-0.077, -0.008] | +0.000 [+0.000, +0.000] | +0.038 [+0.008, +0.077] | -0.038 [-0.077, -0.008] |
| B6@24 - B4@24 | COST_UNMATCHED | 10.9308 vs 9.9 | +0.315 [+0.238, +0.400] | -0.008 [-0.023, +0.000] | +0.008 [+0.000, +0.023] | +0.008 [+0.000, +0.023] | -0.008 [-0.023, +0.000] |
| B6@24 - B4@48 | COST_UNMATCHED | 10.9308 vs 10.2385 | +0.315 [+0.238, +0.400] | -0.015 [-0.038, +0.000] | +0.008 [+0.000, +0.023] | +0.015 [+0.000, +0.038] | -0.015 [-0.038, +0.000] |
| B6@6 - B5@6 | COST_MATCHED | 5.1692 vs 5.2615 | +0.000 [+0.000, +0.000] | -0.008 [-0.023, +0.000] | -0.008 [-0.023, +0.000] | +0.008 [+0.000, +0.023] | -0.008 [-0.023, +0.000] |
| B6@8 - B5@8 | COST_MATCHED | 6.7769 vs 6.8923 | +0.000 [+0.000, +0.000] | -0.077 [-0.123, -0.031] | -0.015 [-0.038, +0.000] | +0.015 [+0.000, +0.038] | -0.015 [-0.038, +0.000] |
| B6@12 - B5@12 | COST_MATCHED | 8.7154 vs 9.0538 | +0.000 [+0.000, +0.000] | -0.069 [-0.115, -0.031] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] |
| B6@24 - B5@24 | COST_MATCHED | 10.9308 vs 11.1615 | +0.038 [+0.000, +0.085] | -0.077 [-0.123, -0.031] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] |
| B6@48 - B5@48 | COST_MATCHED | 11.8846 vs 12.0077 | +0.038 [-0.008, +0.085] | -0.077 [-0.123, -0.031] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] |
| B5@6 - B4@6 | COST_MATCHED | 5.2615 vs 4.9462 | +0.108 [+0.062, +0.162] | -0.008 [-0.031, +0.015] | +0.008 [+0.000, +0.023] | +0.008 [-0.015, +0.031] | -0.008 [-0.031, +0.015] |
| B5@6 - B4@8 | COST_UNMATCHED | 5.2615 vs 6.0462 | +0.108 [+0.062, +0.169] | +0.000 [-0.023, +0.023] | +0.008 [+0.000, +0.023] | +0.000 [-0.023, +0.023] | +0.000 [-0.023, +0.023] |
| B5@8 - B4@12 | COST_UNMATCHED | 6.8923 vs 7.7846 | +0.131 [+0.077, +0.192] | +0.038 [-0.015, +0.100] | +0.015 [+0.000, +0.038] | +0.023 [-0.015, +0.062] | -0.023 [-0.062, +0.015] |
| B5@12 - B4@24 | COST_UNMATCHED | 9.0538 vs 9.9 | +0.223 [+0.154, +0.300] | +0.054 [+0.008, +0.108] | +0.000 [+0.000, +0.000] | +0.015 [+0.000, +0.038] | -0.015 [-0.038, +0.000] |
| B5@24 - B4@48 | COST_UNMATCHED | 11.1615 vs 10.2385 | +0.277 [+0.208, +0.354] | +0.062 [+0.015, +0.115] | +0.008 [+0.000, +0.023] | +0.015 [+0.000, +0.038] | -0.015 [-0.038, +0.000] |
| B2@8 - B4@6 | COST_MATCHED | 5.1462 vs 4.9462 | +0.000 [+0.000, +0.000] | +0.331 [+0.254, +0.415] | +0.000 [+0.000, +0.000] | -0.331 [-0.415, -0.254] | +0.331 [+0.254, +0.415] |
| B2@12 - B4@8 | COST_MATCHED | 6.1538 vs 6.0462 | +0.000 [+0.000, +0.000] | +0.438 [+0.354, +0.531] | +0.000 [+0.000, +0.000] | -0.438 [-0.531, -0.354] | +0.438 [+0.354, +0.531] |
| B2@48 - B4@12 | COST_UNMATCHED | 7.1154 vs 7.7846 | +0.000 [+0.000, +0.000] | +0.569 [+0.485, +0.654] | +0.000 [+0.000, +0.000] | -0.569 [-0.654, -0.485] | +0.569 [+0.485, +0.654] |
| B2@48 - B4@24 | COST_UNMATCHED | 7.1154 vs 9.9 | +0.000 [+0.000, +0.000] | +0.592 [+0.508, +0.677] | +0.000 [+0.000, +0.000] | -0.592 [-0.677, -0.508] | +0.592 [+0.508, +0.677] |
| B2@48 - B4@48 | COST_UNMATCHED | 7.1154 vs 10.2385 | +0.000 [+0.000, +0.000] | +0.585 [+0.500, +0.669] | +0.000 [+0.000, +0.000] | -0.585 [-0.669, -0.500] | +0.585 [+0.500, +0.669] |
| B6@6 - B2@6 | COST_MATCHED | 5.1692 vs 4.6 | +0.108 [+0.062, +0.162] | -0.346 [-0.423, -0.262] | +0.000 [+0.000, +0.000] | +0.346 [+0.262, +0.423] | -0.346 [-0.423, -0.262] |
| B6@6 - B2@8 | COST_MATCHED | 5.1692 vs 5.1462 | +0.108 [+0.054, +0.162] | -0.346 [-0.431, -0.262] | +0.000 [+0.000, +0.000] | +0.346 [+0.262, +0.431] | -0.346 [-0.431, -0.262] |
| B6@8 - B2@12 | COST_UNMATCHED | 6.7769 vs 6.1538 | +0.131 [+0.069, +0.192] | -0.446 [-0.531, -0.362] | +0.000 [+0.000, +0.000] | +0.446 [+0.362, +0.531] | -0.446 [-0.531, -0.362] |
| B6@8 - B2@24 | COST_UNMATCHED | 6.7769 vs 7.0846 | +0.131 [+0.077, +0.185] | -0.600 [-0.685, -0.515] | +0.000 [+0.000, +0.000] | +0.600 [+0.515, +0.685] | -0.600 [-0.685, -0.515] |
| B6@8 - B2@48 | COST_UNMATCHED | 6.7769 vs 7.1154 | +0.131 [+0.077, +0.192] | -0.608 [-0.692, -0.523] | +0.000 [+0.000, +0.000] | +0.608 [+0.523, +0.692] | -0.608 [-0.692, -0.523] |

#### matched: control

| Y@cap - X@cap | basis | cost Y vs X | credited | errors (c5) | SUPPORTED errors | own correct | own error |
|---|---|---|---|---|---|---|---|
| B6@6 - B4@6 | COST_MATCHED | 5.9125 vs 5.9875 | +0.406 [+0.331, +0.487] | -0.181 [-0.237, -0.125] | +0.000 [+0.000, +0.000] | +0.231 [+0.156, +0.312] | -0.006 [-0.019, +0.000] |
| B6@8 - B4@8 | COST_MATCHED | 7.8625 vs 7.9125 | +0.487 [+0.412, +0.562] | -0.287 [-0.362, -0.212] | +0.000 [+0.000, +0.000] | +0.219 [+0.138, +0.306] | -0.019 [-0.044, +0.000] |
| B6@12 - B4@12 | COST_MATCHED | 11.5125 vs 11.75 | +0.713 [+0.637, +0.781] | -0.613 [-0.688, -0.531] | +0.000 [+0.000, +0.000] | +0.119 [+0.037, +0.206] | -0.019 [-0.044, +0.000] |
| B6@48 - B4@24 | COST_UNMATCHED | 21.5875 vs 21.15 | +0.950 [+0.912, +0.981] | -0.950 [-0.981, -0.912] | +0.000 [+0.000, +0.000] | +0.000 [-0.025, +0.025] | +0.000 [+0.000, +0.000] |
| B6@48 - B4@48 | COST_UNMATCHED | 21.5875 vs 22.375 | +0.950 [+0.912, +0.981] | -0.963 [-0.988, -0.931] | +0.000 [+0.000, +0.000] | -0.013 [-0.031, +0.000] | +0.000 [+0.000, +0.000] |
| B6@6 - B5@6 | COST_MATCHED | 5.9125 vs 5.9062 | +0.019 [-0.031, +0.069] | -0.081 [-0.125, -0.037] | +0.000 [+0.000, +0.000] | -0.062 [-0.100, -0.025] | +0.000 [+0.000, +0.000] |
| B6@8 - B5@8 | COST_MATCHED | 7.8625 vs 7.8563 | +0.019 [-0.031, +0.075] | -0.069 [-0.113, -0.031] | +0.000 [+0.000, +0.000] | -0.050 [-0.087, -0.019] | +0.000 [+0.000, +0.000] |
| B6@12 - B5@12 | COST_MATCHED | 11.5125 vs 11.5125 | +0.150 [+0.100, +0.206] | -0.225 [-0.287, -0.163] | +0.000 [+0.000, +0.000] | -0.075 [-0.119, -0.025] | +0.000 [+0.000, +0.000] |
| B6@24 - B5@24 | COST_MATCHED | 20.275 vs 20.0063 | +0.169 [+0.113, +0.231] | -0.150 [-0.206, -0.094] | +0.000 [+0.000, +0.000] | +0.019 [+0.000, +0.044] | +0.000 [+0.000, +0.000] |
| B6@48 - B5@48 | COST_MATCHED | 21.5875 vs 21.15 | +0.194 [+0.131, +0.250] | -0.175 [-0.231, -0.119] | +0.000 [+0.000, +0.000] | +0.019 [+0.000, +0.044] | +0.000 [+0.000, +0.000] |
| B5@6 - B4@6 | COST_MATCHED | 5.9062 vs 5.9875 | +0.388 [+0.312, +0.463] | -0.100 [-0.175, -0.025] | +0.000 [+0.000, +0.000] | +0.294 [+0.219, +0.369] | -0.006 [-0.025, +0.000] |
| B5@8 - B4@8 | COST_MATCHED | 7.8563 vs 7.9125 | +0.469 [+0.394, +0.544] | -0.219 [-0.300, -0.138] | +0.000 [+0.000, +0.000] | +0.269 [+0.194, +0.344] | -0.019 [-0.044, +0.000] |
| B5@12 - B4@12 | COST_MATCHED | 11.5125 vs 11.75 | +0.562 [+0.494, +0.637] | -0.388 [-0.494, -0.287] | +0.000 [+0.000, +0.000] | +0.194 [+0.119, +0.269] | -0.019 [-0.044, +0.000] |
| B5@48 - B4@24 | COST_MATCHED | 21.15 vs 21.15 | +0.756 [+0.688, +0.819] | -0.775 [-0.838, -0.706] | +0.000 [+0.000, +0.000] | -0.019 [-0.056, +0.013] | +0.000 [+0.000, +0.000] |
| B5@48 - B4@48 | COST_UNMATCHED | 21.15 vs 22.375 | +0.756 [+0.694, +0.825] | -0.787 [-0.850, -0.725] | +0.000 [+0.000, +0.000] | -0.031 [-0.056, -0.006] | +0.000 [+0.000, +0.000] |
| B2@8 - B4@6 | COST_MATCHED | 6.5125 vs 5.9875 | +0.000 [+0.000, +0.000] | +0.500 [+0.419, +0.575] | +0.000 [+0.000, +0.000] | +0.469 [+0.388, +0.544] | +0.031 [+0.006, +0.062] |
| B2@12 - B4@8 | COST_MATCHED | 7.6688 vs 7.9125 | +0.000 [+0.000, +0.000] | +0.606 [+0.525, +0.681] | +0.000 [+0.000, +0.000] | +0.588 [+0.506, +0.662] | +0.019 [+0.000, +0.044] |
| B2@48 - B4@12 | COST_UNMATCHED | 8.2312 vs 11.75 | +0.000 [+0.000, +0.000] | +0.388 [+0.312, +0.469] | +0.000 [+0.000, +0.000] | +0.369 [+0.300, +0.450] | +0.019 [+0.000, +0.044] |
| B2@48 - B4@24 | COST_UNMATCHED | 8.2312 vs 21.15 | +0.000 [+0.000, +0.000] | +0.050 [+0.019, +0.087] | +0.000 [+0.000, +0.000] | +0.013 [+0.000, +0.031] | +0.037 [+0.013, +0.069] |
| B2@48 - B4@48 | COST_UNMATCHED | 8.2312 vs 22.375 | +0.000 [+0.000, +0.000] | +0.037 [+0.013, +0.069] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.037 [+0.013, +0.069] |
| B6@6 - B2@6 | COST_MATCHED | 5.9125 vs 5.4437 | +0.406 [+0.331, +0.487] | -0.481 [-0.562, -0.406] | +0.000 [+0.000, +0.000] | -0.044 [-0.156, +0.062] | -0.031 [-0.062, -0.006] |
| B6@6 - B2@8 | COST_MATCHED | 5.9125 vs 6.5125 | +0.406 [+0.331, +0.481] | -0.681 [-0.750, -0.606] | +0.000 [+0.000, +0.000] | -0.237 [-0.338, -0.138] | -0.037 [-0.069, -0.013] |
| B6@8 - B2@12 | COST_MATCHED | 7.8625 vs 7.6688 | +0.487 [+0.406, +0.562] | -0.894 [-0.938, -0.844] | +0.000 [+0.000, +0.000] | -0.369 [-0.469, -0.269] | -0.037 [-0.069, -0.013] |
| B6@8 - B2@24 | COST_UNMATCHED | 7.8625 vs 8.2 | +0.487 [+0.412, +0.569] | -0.994 [-1.000, -0.981] | +0.000 [+0.000, +0.000] | -0.469 [-0.556, -0.381] | -0.037 [-0.069, -0.013] |
| B6@8 - B2@48 | COST_UNMATCHED | 7.8625 vs 8.2312 | +0.487 [+0.412, +0.562] | -1.000 [-1.000, -1.000] | +0.000 [+0.000, +0.000] | -0.475 [-0.556, -0.388] | -0.037 [-0.069, -0.013] |

#### matched: benchmark

| Y@cap - X@cap | basis | cost Y vs X | credited | errors (c5) | SUPPORTED errors | own correct | own error |
|---|---|---|---|---|---|---|---|
| B6@6 - B4@6 | COST_MATCHED | 5.6833 vs 5.975 | +0.133 [+0.075, +0.192] | -0.033 [-0.067, -0.008] | +0.000 [+0.000, +0.000] | +0.100 [+0.033, +0.167] | +0.000 [+0.000, +0.000] |
| B6@8 - B4@8 | COST_MATCHED | 7.4917 vs 7.7333 | +0.250 [+0.175, +0.325] | -0.167 [-0.242, -0.092] | +0.017 [+0.000, +0.042] | +0.067 [-0.008, +0.142] | +0.017 [+0.000, +0.042] |
| B6@12 - B4@12 | COST_MATCHED | 11.0667 vs 11.1583 | +0.450 [+0.367, +0.533] | -0.583 [-0.667, -0.492] | +0.000 [+0.000, +0.000] | -0.100 [-0.183, -0.017] | -0.033 [-0.067, -0.008] |
| B6@24 - B4@24 | COST_UNMATCHED | 18.5583 vs 19.1083 | +0.742 [+0.667, +0.817] | -0.825 [-0.892, -0.758] | +0.000 [+0.000, +0.000] | -0.067 [-0.117, -0.017] | -0.017 [-0.042, +0.000] |
| B6@48 - B4@48 | COST_UNMATCHED | 19.9667 vs 20.2917 | +0.775 [+0.700, +0.850] | -0.833 [-0.900, -0.767] | +0.000 [+0.000, +0.000] | -0.033 [-0.067, -0.008] | -0.025 [-0.058, +0.000] |
| B6@6 - B5@6 | COST_MATCHED | 5.6833 vs 5.6 | -0.017 [-0.042, +0.000] | -0.025 [-0.058, +0.000] | +0.000 [+0.000, +0.000] | -0.042 [-0.083, -0.008] | +0.000 [+0.000, +0.000] |
| B6@8 - B5@8 | COST_MATCHED | 7.4917 vs 7.3417 | -0.008 [-0.042, +0.017] | +0.000 [-0.033, +0.033] | +0.017 [+0.000, +0.042] | -0.025 [-0.058, +0.000] | +0.017 [+0.000, +0.042] |
| B6@12 - B5@12 | COST_MATCHED | 11.0667 vs 10.825 | +0.042 [+0.008, +0.083] | -0.075 [-0.125, -0.033] | -0.008 [-0.025, +0.000] | -0.025 [-0.058, +0.000] | -0.008 [-0.025, +0.000] |
| B6@24 - B5@24 | COST_UNMATCHED | 18.5583 vs 18.025 | +0.167 [+0.100, +0.242] | -0.100 [-0.158, -0.050] | -0.008 [-0.025, +0.000] | +0.075 [+0.025, +0.125] | -0.008 [-0.025, +0.000] |
| B6@24 - B5@48 | COST_UNMATCHED | 18.5583 vs 18.8417 | +0.175 [+0.108, +0.242] | -0.100 [-0.158, -0.050] | -0.008 [-0.025, +0.000] | +0.083 [+0.033, +0.142] | -0.008 [-0.025, +0.000] |
| B5@6 - B4@6 | COST_MATCHED | 5.6 vs 5.975 | +0.150 [+0.092, +0.217] | -0.008 [-0.050, +0.033] | +0.000 [+0.000, +0.000] | +0.142 [+0.083, +0.208] | +0.000 [+0.000, +0.000] |
| B5@8 - B4@8 | COST_MATCHED | 7.3417 vs 7.7333 | +0.258 [+0.183, +0.342] | -0.167 [-0.233, -0.100] | +0.000 [+0.000, +0.000] | +0.092 [+0.025, +0.167] | +0.000 [+0.000, +0.000] |
| B5@12 - B4@12 | COST_MATCHED | 10.825 vs 11.1583 | +0.408 [+0.325, +0.492] | -0.508 [-0.600, -0.417] | +0.008 [+0.000, +0.025] | -0.075 [-0.158, +0.000] | -0.025 [-0.058, +0.000] |
| B5@48 - B4@24 | COST_UNMATCHED | 18.8417 vs 19.1083 | +0.567 [+0.475, +0.650] | -0.725 [-0.800, -0.642] | +0.008 [+0.000, +0.025] | -0.150 [-0.217, -0.092] | -0.008 [-0.025, +0.000] |
| B5@48 - B4@48 | COST_UNMATCHED | 18.8417 vs 20.2917 | +0.567 [+0.483, +0.650] | -0.733 [-0.808, -0.650] | +0.008 [+0.000, +0.025] | -0.150 [-0.217, -0.083] | -0.017 [-0.042, +0.000] |
| B2@6 - B4@6 | COST_MATCHED | 5.5333 vs 5.975 | +0.000 [+0.000, +0.000] | +0.317 [+0.233, +0.400] | +0.000 [+0.000, +0.000] | +0.283 [+0.200, +0.367] | +0.033 [+0.008, +0.067] |
| B2@12 - B4@8 | COST_MATCHED | 7.725 vs 7.7333 | +0.000 [+0.000, +0.000] | +0.592 [+0.500, +0.675] | +0.000 [+0.000, +0.000] | +0.533 [+0.442, +0.617] | +0.058 [+0.025, +0.100] |
| B2@24 - B4@12 | COST_UNMATCHED | 8.3917 vs 11.1583 | +0.000 [+0.000, +0.000] | +0.292 [+0.208, +0.375] | +0.000 [+0.000, +0.000] | +0.258 [+0.183, +0.342] | +0.033 [+0.008, +0.067] |
| B2@24 - B4@24 | COST_UNMATCHED | 8.3917 vs 19.1083 | +0.000 [+0.000, +0.000] | +0.050 [+0.017, +0.092] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.050 [+0.017, +0.092] |
| B2@24 - B4@48 | COST_UNMATCHED | 8.3917 vs 20.2917 | +0.000 [+0.000, +0.000] | +0.042 [+0.008, +0.075] | +0.000 [+0.000, +0.000] | +0.000 [+0.000, +0.000] | +0.042 [+0.008, +0.075] |
| B6@6 - B2@6 | COST_MATCHED | 5.6833 vs 5.5333 | +0.133 [+0.075, +0.192] | -0.350 [-0.433, -0.267] | +0.000 [+0.000, +0.000] | -0.183 [-0.292, -0.075] | -0.033 [-0.067, -0.008] |
| B6@8 - B2@8 | COST_UNMATCHED | 7.4917 vs 6.65 | +0.250 [+0.175, +0.333] | -0.525 [-0.617, -0.442] | +0.017 [+0.000, +0.042] | -0.258 [-0.358, -0.167] | -0.017 [-0.058, +0.025] |
| B6@8 - B2@12 | COST_MATCHED | 7.4917 vs 7.725 | +0.250 [+0.175, +0.333] | -0.758 [-0.842, -0.683] | +0.017 [+0.000, +0.042] | -0.467 [-0.558, -0.375] | -0.042 [-0.092, +0.008] |
| B6@8 - B2@24 | COST_UNMATCHED | 7.4917 vs 8.3917 | +0.250 [+0.175, +0.333] | -0.858 [-0.917, -0.792] | +0.017 [+0.000, +0.042] | -0.558 [-0.642, -0.458] | -0.050 [-0.100, +0.000] |
| B6@8 - B2@48 | COST_UNMATCHED | 7.4917 vs 8.3917 | +0.250 [+0.175, +0.325] | -0.858 [-0.917, -0.800] | +0.017 [+0.000, +0.042] | -0.558 [-0.650, -0.467] | -0.050 [-0.100, +0.000] |


### 5.1 How to read it

- Every B2/B4 endorsement is UNSUPPORTED_CLAIM under candidate.5 (they register nothing). Their
  face-value columns are what v1.1 itself would report: control 152/160 (cap 24) and 154/160
  (cap 48) correct, held-out force-fits 0-2 per 130.
- B5 (v1.2 unchanged) is re-scored by the v1.3 evaluator from its registrations' identities and
  experiments; the "B5 under v1.2's own payload rule" line gives its v1.2-rule count beside. The
  gap (e.g. 149 vs 125 in the control at cap 24) is answers whose v1.2 support rested on
  arm-supplied quantities.
- Noise-only benchmark worlds (per-kind line "noise_only_null", tuples = credited, own correct,
  errors): v1.3 9/15 and 14/15 at caps 24/48; v1.2 0/15; v1.1's own 15/15.
- B6 abstains more than B4 at face value on the benchmark kinds at 12-48 units (false nulls 51,
  16, 12 vs 35, 6, 5): the evaluator-controlled support and the open-rival requirement cost answers
  v1.1 gives.

## 6. Matched realized cost (paired on identical worlds, paired bootstrap 95 % intervals)

See the "matched" tables above: for each cap of X, Y's cap with the nearest mean realized cost;
COST_MATCHED only if the interval of the mean cost difference lies within +-1 unit. Rows marked
COST_UNMATCHED are reported but are not matched comparisons. Answers are committed when an arm
stops (commit-at-termination); cost is the evaluator's meter.

Reading (B6 vs B4, the question that matters for the baseline):
- held-out primary: B6 credits 14-41 validated new mechanisms per 130 (B4 none, it has no
  discovery stage); face-value own-correct +0.015 [0, 0.038] at cap 6 (COST_MATCHED), +0.008 to
  +0.038 at other caps (COST_UNMATCHED: B6 spends 0.7-1.0 unit more).
- control: own-correct +0.231, +0.219, +0.119 at ~6, ~8, ~12 units (all COST_MATCHED, intervals
  exclude 0); 0.000 and -0.013 [-0.031, 0] at 24/48 (COST_UNMATCHED).
- benchmark kinds: own-correct +0.100 [0.033, 0.167] at ~6 (matched), +0.067 [-0.008, 0.142] at ~8
  (matched), **-0.100 [-0.183, -0.017] at ~11 (matched)**, -0.067 and -0.033 at caps 24/48
  (COST_UNMATCHED). Own-error +0.017 [0, 0.042] at ~8, otherwise <= 0.
- B2 (engine) at matched cost has more own-correct answers than B4 at low cost in the control
  (+0.47 at ~6-7 units) and many more face-value errors in the held-out setting (+0.33 to +0.59).

## 7. What remains scientifically unproven

- Everything here is developer-authored: worlds, families, grammar, gates AND the evaluator's
  rule (its alternative set, smallest-effect convention, one-outlier tolerance and open-rival
  requirement were chosen by the same lineage, on development seeds). An independent evaluator
  rule and independent worlds are needed before any of this is evidence.
- The smallest-effect-of-interest for "no effect" is the catalog's declared amplitude domains; a
  real effect below those domains is invisible to it by construction.
- Riskiness is "separated from at least one viable alternative"; the open-rival check covers
  "no effect" and no-more-complex catalog hypotheses only, not grammar shapes. A claim can be
  SUPPORTED while a grammar alternative is still viable (observed: SUPPORTED wrong claims at cap 8).
- The process boundary is a same-user subprocess, not an OS sandbox; in-process use is only an
  object-capability boundary.
- Grammar rediscovery: the validated new mechanisms rediscover families the grammar can express
  (v1.2 report §4.1); not discovery outside the author's vocabulary.
- Held-out numbers were seen before the two re-freezes (§8).

## 8a. Owner decisions

- **Keep v1.1 as the baseline** (instruction followed). Whether any later version may replace it
  needs an independent evaluation; on face-value metrics v1.3 does not dominate v1.1 (§6).
- Whether candidate.5's evaluator-controlled support becomes the standard for every endorsement
  (under it v1.1 and the engine have no SUPPORTED answers at all).
- The evaluator rule's conventions: smallest declared effect as the null's effect of interest;
  one-outlier-tolerant viability; open rivals limited to no-more-complex catalog hypotheses;
  max 4 runs per test.
- The parsimony fallback to "no effect" (it produced one SUPPORTED null force-fit on development
  seeds and none on the fresh held-out worlds).
- Commissioning an independent evaluator rule, worlds and grammar.

## 8. Process notes: two re-freezes after held-out results had been seen

**Held-out results WERE seen before each re-freeze.** Neither re-freeze changed any decision
logic, threshold, plan or seed; both were forced by checks, and the evidence on the branch is the
run from the final freeze `b46c397`.

1. **`91c813f` -> `04c4193` (governance).** The first freeze was evaluated on the fresh held-out
   seeds (evidence committed at `ab1841a`; I read its tables). The full default test suite then
   failed `test_discovery_safety_governance.py`: the v1.3 package imported `subprocess` (to start
   the arm process) and `random` (the bootstrap), which the safety package may not import. Fix: the
   composition root starts the arm process and the package only serves its pipes (`serve_run`); the
   paired bootstrap draws indices from SHA-256 in counter mode (a different but equally fixed
   resampling stream, so bootstrap intervals changed slightly). Re-run from `04c4193`.
2. **`04c4193` -> `b46c397` (determinism).** Comparing that re-run with the first run: the held-out
   and control row files were byte-identical, but in the benchmark file the arm's self-reported
   result digest of one world (`outside_initial_prior-08`, every arm and cap) differed, with every
   category, cost and ledger head identical. Cause: the arm process kept the frozen engine's
   `SeparationOracle` across cases, and that cache stores the float of whichever argument order was
   asked first, so a digest depended on which worlds the pool happened to give that process
   earlier -- `--check` could not have been reliable. Fix: one oracle per case in the arm process
   (an opaque per-case token, naming no world or truth). Re-run from `b46c397`; §9 compares it with
   the earlier runs.

Other notes:
- Plan reduced before the first freeze, for run time: 10 worlds per held-out class (160 worlds:
  130 primary, 30 aliased; v1.2 used 15) and 15 per benchmark kind (120), caps 6, 8, 12, 24, 48.
- B3 (v1.0) was not re-run; v1.0 is two versions behind the baseline.

## 9. Verification

Code unchanged since the final freeze `b46c397` except tests, docs, the status inventory and the
evidence. CPython 3.13.18 in `.venv`, ruff 0.17.4.

| check | result |
|---|---|
| `ruff check src tests scripts` / `ruff format --check` | All checks passed / 653 files already formatted |
| `mypy` (strict) | no issues in 325 source files |
| `pytest tests/spec -q` | 245 passed |
| focused: `test_discovery_safety_v13.py`, `..._v13_reproduction.py`, governance, `e2e/test_discovery_safety_v13_frozen.py` | pass (part of the runs below) |
| full default suite (`pytest -q`, no backend) | **2671 passed, 1203 skipped**, 0 failed |
| full PostgreSQL suite, ONE complete run on a FRESH `lib_disc` (dropped, recreated, `migrate.py` twice: 81 applied, then up to date) | **3870 passed, 4 skipped**, 0 failed (22 min 39 s) |
| `update_status.py` | regenerated; `--check`: up to date (after both runs) |
| `check_requirement_coverage.py` | passed (milestones DONE: M0a, M0b, M1, M2, M3) |
| evidence vs earlier runs | final run (`b46c397`) vs first run (`91c813f`): held-out and benchmark row files byte-identical; control rows differ only in 6 arm result digests; every category, level, cost and ledger head identical |
| `discovery_safety_v13_eval.py --check` | under **CPython 3.12.3** (separate venv, recorded dependency versions, `PYTHONHASHSEED=12345`): every evidence file reproduced byte-identically; the check refused with INTERPRETER MISMATCH as designed; 3.12 was then recorded in `interpreter_verification.json`. The evidence itself was written under CPython 3.13.18; a separate 3.13 `--check` was not run (one complete re-run takes ~70 min) |
| mutation battery, `safety_v13_*` (7 entries, additions only) | first run **3/7 killed** (tests too weak on the verdict parts, the null-rival rule and the chain value); three tests added; **7/7 killed** |
| `check_commit_messages.py` | no AI authorship found |
| `S35-` identifiers in `src/` or `tests/` | none |
| v1.0/v1.1/v1.2 package files, frozen engine, earlier evidence | unchanged (`git diff e778cc4` on them is empty; the script checks their manifests) |

