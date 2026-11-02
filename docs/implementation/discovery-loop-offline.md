# Discovery Loop v0 (offline)

Status: **engineering candidate on branch `discovery-loop-offline`, based on `58c68be`
(`g0-owner-boundary-closure`). Not merged, not deployed.** `READY_FOR_REAL_RESEARCH` stays false.
G0 stays NOT PASSED. No migration, no database write, no model call, no simulator, no network.

Audit package (Traditional Chinese report, frozen evidence):
[`docs/audit/discovery-loop-offline-2026-11-01/`](../audit/discovery-loop-offline-2026-11-01/).
Evaluation refinements on branch `discovery-independent-evaluation` (realized-cost curves,
held-out mechanism classes, the hidden-world scaffold; the engine unchanged):
[`docs/audit/discovery-independent-evaluation-2026-11-02/`](../audit/discovery-independent-evaluation-2026-11-02/),
and the protocol for a genuinely independent evaluation:
[`docs/evaluation/discovery-independent-evaluation-protocol.md`](../evaluation/discovery-independent-evaluation-protocol.md)
(§10 below).
Handoff: [`discovery-loop-offline-handoff.zh-TW.md`](discovery-loop-offline-handoff.zh-TW.md).

---

## 1. What it is for

The existing loop (`verification/loop.py`) verifies a **fixed** set of rival hypotheses. It never
asks whether the right mechanism is in the set, whether an observation is explained by nothing in
the set, or whether two rivals can be told apart at all. The Causal Warrant Gate names that as an
inherent residual (V1 §5, T9: "an unnamed mechanism is not excluded").

The Discovery Loop is an offline v0 of those missing steps. Its point is discovery **quality**, not
hypothesis counts:

1. propose only mechanisms that some available experiment can tell apart;
2. notice observations that nothing live explains, and test them before believing them;
3. reframe when every hypothesis fails, without deleting the failures;
4. choose experiments by discrimination per unit cost, under a fixed budget;
5. stop, explicitly, when the budget or the available experiments cannot discriminate;
6. never confirm anything. The best outcome is "surviving, pending the Causal Warrant Gate".

## 2. Layout

| module | role |
|---|---|
| `src/lab_brain/discovery/model.py` | vocabularies and frozen records; no CONFIRMED anywhere |
| `catalog.py` | a domain's declared experiments and typed mechanism classes |
| `numerics.py` | exact box-constrained least squares (active-set enumeration); chi-square tail |
| `forward.py` | predictions and fits of a hypothesis against observations |
| `distinguish.py` | the separation statistic; indistinguishability classes |
| `protocol.py` | pre-registered thresholds and feature switches; the arms are configurations |
| `loop.py` | `investigate`: evaluate, notice, test, reframe, claim or stop |
| `baselines.py` | B0, the single-hypothesis baseline (a deterministic stand-in, not an LLM) |
| `handover.py` | the typed packet for the Causal Warrant Gate; draft §8.1 certificates |
| `worlds.py` | seeded synthetic worlds (common random numbers) |
| `metrics.py` | scoring by distinguishable classes; Wilson and bootstrap intervals |
| `benchmark.py` | matched-budget arms, ablations, manifest, defect demonstrations |
| `src/lab_brain/domains/silicon_photonics/discovery_catalog.py` | the ring-resonator scenario: 12 experiments (1 unavailable), 16 mechanism classes, 8 world kinds |
| `scripts/discovery_benchmark.py` | one complete run → frozen evidence; `--check` |

The engine is domain-agnostic. It imports no DomainPack and names no physical quantity
(`tests/unit/test_discovery_governance.py` parses its imports and identifiers). The scenario is
handed to it as data. The script is the composition root; `pyproject.toml` exempts that one file
from the §24.2 lint ban, with the reason written beside it.

## 3. Mechanisms and forward models

A mechanism class is one **parameter regime** of a declared mechanism (`MechanismClass`): a family,
a statement, a kind (physical or measurement chain), a tier (`INITIAL`, `VARIANT`, `EXTENDED`), one
amplitude parameter with a range that excludes zero, and a **tabulated** forward model. The domain
pack writes forward-model functions of each experiment's declared conditions; the catalog evaluates
them once into a sensitivity table, and the engine only reads the table (the same pattern as
`TabulatedMetric` in `verification/disagreement.py`). A class's identity is its table and range
(`fingerprint`), never its name.

A hypothesis is the noise model (no mechanism), one class, or a composition of two classes of
different families. Predictions are linear in each amplitude; noise is Gaussian with each entry's
declared sigma.

The ring scenario's classes: thermo-optic drift (ambient offset; self-heating variant), static
free-carrier dispersion, TPA+FCA (TPA-dominated; FCA-dominated variant), sidewall scattering, width
deviation (wide; narrow variant), coupling-gap deviation (narrow; wide variant), substrate leakage,
laser wavelength error and fibre-coupling loss (measurement chain); extended: device-layer
thickness, cladding index drift, input-polarisation drift (measurement chain). **The magnitudes are
toy numbers**; only signs and qualitative dependences are meant. The catalog is pinned by digest,
is not installed in the product vertical, and adds no condition-schema field.

## 4. Distinguishability

For hypotheses A, B and experiments X:

    sep_X(A, B) = min over amplitudes of sqrt( sum_entries ((mu_A - mu_B) / sigma)^2 )

the closest the two forward models can come, in noise units, in the **worst case** over both
amplitude ranges. A and B are **distinguishable** iff the whole available protocol, each experiment
run `distinguish_replicates` (4) times, separates them by at least `distinguish_tau` (5):
`sqrt(4) * sep_available(A, B) >= 5`. It is data-independent, so it cannot be tuned after the fact.

Indistinguishable hypotheses are one **class** (connected components of the indistinguishability
graph; transitive, which is the conservative reading). Consequences, each tested:

- a renamed duplicate (identical table) is recorded as an alias of the original and never counted
  or tested separately;
- a refutation is never applied to a hypothesis while one it cannot be separated from survives
  (`indistinguishable_guard`) — no resolution by fiat;
- a claim reports the whole class, and `CHANGE_OBSERVABLE` names any declared but unavailable
  experiment that would split it (ring: width vs thickness on a single-width die → the width array
  and the ellipsometer);
- diversity is the number of classes examined, so fifty indistinguishable variants add nothing.

## 5. The loop, per step

1. **Evaluate.** Every live hypothesis is fitted to the *admitted* observations (never the
   motivating one; never one attributed to noise). It is **refuted** if its chi-square p-value is
   below `alpha_refute` (1e-3), or if its chi-square exceeds the best live hypothesis's by more
   than `delta_chi2_refute` (10.828, a likelihood-ratio test at the same alpha). Each refutation
   records its leave-one-out basis: the observations it is pivotal on.
2. **Survival is prospective.** A hypothesis is SURVIVING only after passing tests it could have
   failed (worst-case separation ≥ 3 from the noise model or from another registered hypothesis)
   on `min_prospective_tests` (2) **distinct** experiments, all taken **after its registration**.
   Observations before registration may refute it, never support it.
3. **Anomalies.** An observation outside the noise model (|z| > 4) under every live hypothesis's
   best fit is an `UNEXPLAINED` anomaly. When every hypothesis has failed, each observation that
   alone carries a refutation becomes one too. Nothing removes an anomaly record.
4. **Noise test (pre-registered).** One replication. If a declared hypothesis explains the
   replicate and, on the entry where the original deviates most, the replicate sides with it rather
   than with the original, the original is `ATTRIBUTED_TO_NOISE`: excluded, and every refutation it
   was pivotal for is re-examined (a hypothesis that now fits returns to `UNDER_TEST` with a
   recorded reinstatement — never to support). Otherwise the deviation is `REPRODUCED` (original and
   replicate agree) or `UNSTABLE` (they disagree and nothing explains the replicate: possibly
   non-stationary; stays `UNEXPLAINED`).
5. **Reframing** (append-only `ReframingRecord`, citing every hypothesis refuted so far and every
   open anomaly) when nothing live remains or a tested anomaly persists:
   `QUESTION_THE_MEASUREMENT_CHAIN` (register declared measurement-chain classes not held, and
   prefer chain-check experiments) → `WIDEN_MECHANISM_SPACE` (regime variants, extended classes,
   pairwise compositions — only those the admitted data do not refute and that are distinguishable
   from everything held; at most 8 per round, 2 rounds) → `NARROW_SCOPE` (what fits outside the
   anomalous experiments; informational, no claim) → `STOP_INSUFFICIENT`.
6. **Before a claim** (one class left, every member prospectively supported): replicate the
   observation a rival's refutation pivots on (decisive replication, within the 2-test noise
   allowance); register every declared rival of no greater complexity that the data do not refute
   and that is distinguishable from everything held, and discriminate it too (rival closure); then
   add every declared hypothesis of no greater complexity that no available experiment separates
   from the class (class closure). More complex indistinguishable hypotheses (the class plus a small
   extra contribution) are listed as `cannot_exclude`, not as rivals.
7. **Selection.** Expected weighted pairwise separation between live classes at their current best
   fits, each pair capped at one full separation (`selection_tau` = 4), divided by cost, under the
   remaining budget. Weights are the catalog prior (a floor for data-motivated hypotheses) times
   the fit p-value. If nothing affordable discriminates: `STOPPED_INSUFFICIENT_VALIDATION`.

## 6. States

| object | states |
|---|---|
| hypothesis | `PROPOSED`, `UNDER_TEST`, `SURVIVING`, `REFUTED`, `INDISTINGUISHABLE`, `STOPPED` |
| anomaly | `UNEXPLAINED`, `ACCOMMODATED` (fitted by a hypothesis not yet prospectively tested — accommodation is not explanation), `EXPLAINED`, `ATTRIBUTED_TO_NOISE` |
| reframing | `WIDEN_MECHANISM_SPACE`, `CHANGE_OBSERVABLE`, `QUESTION_THE_MEASUREMENT_CHAIN`, `NARROW_SCOPE`, `STOP_INSUFFICIENT` |
| outcome | `SURVIVING_PENDING_WARRANT_GATE`, `INDISTINGUISHABLE_CLASS_PENDING_WARRANT_GATE`, `NO_EFFECT_BEYOND_NOISE`, `STOPPED_INSUFFICIENT_VALIDATION`, `STOPPED_UNEXPLAINED` |

`transition` refuses leaving `REFUTED` except to `UNDER_TEST` with a recorded reinstatement reason;
`anomaly_transition` refuses leaving `ATTRIBUTED_TO_NOISE`. Histories are append-only tuples.

## 7. Handover to the Causal Warrant Gate

The gate cannot be invoked offline: it needs admitted certificates, typed predictions bound to
declared OutcomeSpaces, Runs and Attestations through the admission gate, relations, a DOMAIN or
signed REVIEW warrant per belief-moving relation, and `ConfirmationRule.standing` (SQL `012p`). The
loop has none of those records and must not invent them. So it hands over a typed packet
(`GateHandover`, status always `PENDING_CAUSAL_WARRANT_GATE`):

| packet field | gate input it maps to |
|---|---|
| `candidate_class` | the candidate set (one member, or a class no available experiment splits) |
| `rivals` (state, refutation basis, best separating experiment) | the rivals I6 requires to be excluded on **warranted** refutation; a chi-square refutation here is not one |
| `prospective_support` | the only observations that may ever count for each member (cf. `011s`) |
| `never_considered` | declared classes never registered: the closed-world residual (T9) |
| `open_anomalies`, `would_separate`, `cannot_exclude` | what a person must weigh |
| `requirements` | admission (`admit_hypothesis`), prediction binding (`bind`), new evidence (`011s`), warrant (`WarrantResolver`, signed review), the confirmation rule |

`draft_certificates` turns the packet into unadmitted core `Hypothesis` certificates (statement,
mechanism, falsifier naming the best separating experiment, minimal test). It does **not** produce
`Prediction`s: those must bind to a DomainPack-declared OutcomeSpace, and the discovery observables
have none. Nothing in the packet satisfies any requirement; the tests prove the loop cannot emit
CONFIRMED and cannot count pre-registration data as support.

## 8. Offline evaluation

Three arms, the same worlds, seeds and budget (12 units; 8 and 16 for sensitivity):

- **B0 single hypothesis**: the most prior-likely initial mechanism consistent with the motivating
  observation, tested once on the cheapest experiment where it predicts an effect, accepted if its
  fit passes. A deterministic stand-in for "one confident answer". **Not an LLM.**
- **B1 existing LIB style**: `investigate` with every discovery switch off — a re-implementation of
  the existing loop's policy shape (fixed set, discrimination per cost, the same refutation rule,
  one prospective test), **not** the PostgreSQL-backed `VerificationLoop`.
- **B2 LIB + Discovery**: all switches on. Four ablations switch one feature group off each.

Eight world kinds × 25 seeds: in-catalog single; outside the initial prior; an inseparable pair
(correct = report the class); noise glitch on a true in-catalog mechanism; noise only (symptom and
first measurement are flukes; correct = the noise model); confounded measurement chain; composition;
truth outside every declared class (non-stationary; correct = no claim). The evaluation seeds were
not run while the protocol was being written (development used `DEVELOPMENT_BASE_SEED`).

Metrics are classes, never counts: correct outcome (the truth's class exactly — the truth, nothing
an available experiment separates from it, and every equally simple alternative it cannot be
separated from), false discovery, overclaim, distinguishable diversity, budget, budget per correct
outcome, open anomalies, per-kind rates, seed-block spread, paired B2−baseline differences;
Wilson intervals for proportions, seeded bootstrap for means. Results:
[`REPORT.zh-TW.md`](../audit/discovery-loop-offline-2026-11-01/REPORT.zh-TW.md).

## 9. Limitations

- **Toy forward models, one author.** The worlds and the engine were written by the same
  implementer. The benchmark is engineering evidence that the algorithm behaves as designed, not
  scientific validity and not an independent blind evaluation.
- **The protocol was revised during development** on development seeds (severity, decisive
  replication, comparative refutation, rival closure, the replication rule). The evaluation seeds
  were then run once. Development and evaluation worlds share generators and kinds, so the
  held-out seeds guard against seed-level overfitting only, not against design-level overfitting.
- **Closed world, one level up.** Widening draws only on declared classes and pairwise
  compositions. A truly new mechanism can only be *reported as unexplained*, never proposed.
- **Linear forward models in one amplitude.** No interactions, no nonlinear regimes, no correlated
  or heavy-tailed noise beyond the single injected glitch; a non-stationary effect can be
  misattributed (the replication test has no time model).
- **Worst-case distinguishability is conservative.** Pairs that coincide only at an edge of their
  ranges are merged even when the data would separate them; classes can be larger than necessary.
- **Weak secondary effects** (a composition whose second component never produces an anomaly) are
  missed: compositions are only entertained when single mechanisms fail.
- **B2 spends more budget** than the baselines (severity, replications, rival closure).
- **The gate is not invoked.** The handover is a packet; nothing here exercises admission, warrant
  or `ConfirmationRule` on discovery output.

## 10. Evaluation limits, the refinements, and the independent protocol

The §8 benchmark compares arms at one nominal budget, on worlds whose generator, kinds and catalog
share the engine's author, with two baselines that are deterministic substitutes. Branch
`discovery-independent-evaluation` adds three offline refinements and a protocol, without touching
the engine (its sources still match the 2026-11-01 manifest, and the frozen main run reproduces
digest for digest through the new harness).

**Tooling** (`src/lab_brain/discovery_eval/`, beside the frozen package because its manifest hashes
every file in `lab_brain/discovery`; under the same §24.2 import ban, with its own structural test):

| module | role |
|---|---|
| `blind.py` | a laboratory exposing only `motivating`/`measure`; refuses unavailable experiments and readings that are not exactly the declared entries; a cost meter that counts and caps **realized** cost independently of the engine; a token-level truth-leak search |
| `curves.py` | every world × cap × arm through the blind, metered laboratory; per cap: rates (Wilson), realized cost (bootstrap, median, p90, max), utilisation, exhaustion, realized cost per correct (ratio bootstrap); paired McNemar with Holm; AUC of correct rate over caps; censored budget-to-first-correct; invariants |
| `held_out.py` | worlds whose true mechanism **family** is removed from the engine's catalog and prior (all tiers), aliasing classified before any run, scoring as correct (no claim) / force-fit / false null / surrogate; a control with the family left in |
| `hidden_worlds.py` | the format in which a different author supplies sealed hidden worlds (schema `benchmarks/discovery_independent/hidden-worlds.schema.json`), validation that refuses malformed or truth-leaking files, commit-then-reveal sealing after `evaluation.sealing`, an engine package with opaque case ids, a blind runner and the evaluator's scorer |

`scripts/discovery_independent_eval.py` runs it once and freezes the evidence; `--check` re-runs.

**What the refinements show** (synthetic, same author lineage; details and intervals in the
2026-11-02 report):

- **Realized cost.** On fresh seeds, B2's correct rate rises with the cap (0.345 at cap 4 to 0.97
  at 24) while it actually spends 3.9 to 8.2 units; B1 stays near 0.30 spending about 1.9, B0 near
  0.08 spending 1.2. At cap 4 B2 is not significantly better than B1 (+0.05, Holm p = 0.25) and is
  worse on easy in-catalog worlds (11/25 vs 24/25): severity and replication spend the budget first.
  Realized cost per correct outcome is lower for B1 at every cap. B2's false-discovery rate stays
  at 0.01-0.02 at every cap, B1's near 0.24.
- **Held-out families.** With the true family absent from the catalog, B2 force-fits 0.40 of the
  non-aliased worlds at cap 12 (B0 0.395, B1 0.53) and 0.47 at cap 24. Its guarantee is relative to
  the declared rivals: it runs only experiments that separate declared hypotheses, so a surrogate
  that matches the truth on those experiments is claimed. Every B2 no-claim leaves a record (an open
  anomaly or a reframing); B0's are mostly silent. With the family left in, B2 is correct on 0.91 of
  the same worlds.
- **Invariants.** Realized cost never exceeds the cap; the meter equals the engine's report; a run
  that ended with at least the dearest experiment's cost unspent is the same run at every larger cap
  (3309 comparisons, no violation).

**Limits that remain** until the independent protocol runs:

- the worlds, the held-out families, the example file and the tooling share the engine's author
  lineage; fresh seeds guard against seed-level, not design-level, overfitting;
- B0 is not a language model and B1 is not the PostgreSQL `VerificationLoop`; arm A needs an
  Owner-approved pinned model, arm B a harness driving the real LIB (and an OutcomeSpace decision);
- the blind laboratory is in-process (accidental exposure only); the protocol requires a separate
  laboratory process the engine cannot read;
- the truth-leak checks are lexical;
- nothing here is physical, literature-based or model-based evidence, and the Causal Warrant Gate
  is still never invoked.

**The protocol** ([`discovery-independent-evaluation-protocol.md`](../evaluation/discovery-independent-evaluation-protocol.md))
fixes roles (world author ≠ engine author ≠ evaluator, an engine-author AI lineage included),
commit-then-reveal over sealed worlds, a frozen engine SHA and environment manifest, blind runs,
evaluator scoring, held-out families with "no claim" as the correct outcome, realized-cost curves
with AUC and budget-to-first-correct, the real definitions of arms A/B/C next to their current
substitutes, pre-registered statistics with one primary endpoint, and the results that would
falsify "Discovery helps".
