# SAI 3.5 — Appendix J: Matched-budget A/B/C comparison protocol

Version: `3.5.0-master-candidate.5`. Status: **CANDIDATE — NOT ACTIVE.** Nothing in this protocol
has been run. Values marked *proposed* are recommendations for Owner decision OD-03, not frozen.
Authority: normative. Refines S35-CMP-001–009 of [SAI 3.5](../SAI_3.5.md). Supersedes the
`3.5.0-discovery-candidate.1` version of this file (kept in git history).

## 1. Question

Does adding the Discovery Loop make LIB better at finding true causes, at the same realized cost,
without more false discoveries, and is LIB with Discovery better than a single frontier LLM given
the same resources? The answer must come from cases nobody involved in the implementation has seen,
against fair baselines, scored by someone other than the implementer.

## 2. Arms

| Arm | What runs | What it may not use |
|---|---|---|
| **A — single frontier LLM** | one model driven by a frozen minimal loop: one fixed prompt template, the same tool interface as the other arms (corpus search, experiment requests, stop), the same answer schema | LIB's governance chain, structured debate, admission gate, Verification Planner, Causal Warrant Gate or Discovery Loop |
| **B — existing LIB workflow** | the product research workflow at the frozen commit with the Discovery Loop disabled: debate, admission, least-cost verification, evidence admission, TransitionPolicy and the Causal Warrant Gate | the Discovery Loop components (Problem Discovery, Mechanism Explorer, Research Reframing, class-level selection and rival closure) |
| **C — LIB with Discovery** | arm B plus the Discovery Loop | anything B may not use except the Discovery Loop; any extra resources |

Model per stage: in the primary comparison arm A and every LIB model slot use the same model. In a
zero-cost stage that is the strongest local open-weight model the Owner approved and declared free
(OD-04); a frontier model is used only in an Owner-authorized paid stage with a ceiling (OD-05). A
multi-model LIB configuration is a separate, separately pre-registered comparison.

Answer schema (all arms, every case): claimed mechanism or none; its epistemic stage and claim state as the arm states them (the evaluator re-derives the evidential level from the trace and ignores the stated one); for each test the arm relies on, the hash of its prediction and the time it was recorded, before the data was requested;
evidence references; uncertainty by source; experiments run with realized costs; an optional
`INSUFFICIENT_VALIDATION` or `STOPPED` outcome with reason; and an **anytime answer** after every
experiment or model-call batch, stamped with its cumulative realized charge (needed for §3.3).

*Offline analogues.* The offline prototype (`118a4ac`) used B0 (single hypothesis), B1 (LIB style)
and B2 (LIB + Discovery). B0 is a deterministic stand-in, **not an LLM**, so it is not arm A. B1
re-implements the loop's policy shape in the same engine; it is **not** the real LIB workflow, so it
is not arm B. Its result (correct outcome 0.89 for B2 versus 0.31 for B1 and 0.08 for B0, with B2
spending about four times B1's budget) is engineering evidence about implementer-written synthetic
worlds, not a G-D1 verdict.

## 3. Matching

### 3.1 Matched dimensions

| Dimension | Rule |
|---|---|
| Model versions | identical identifiers, digests (measured from the server where possible; a declared-only digest is recorded as such) and decoding settings in every arm |
| Information exposure | the same corpus snapshot (hash), case material, tool descriptions, experiment catalog and cost table; no arm sees sealed truth; prompts and tool outputs logged for audit; no arm receives information another arm generated |
| Experimental conditions | the same simulator access and qualification, time limit per case, seed per case, egress permissions and environment manifest (commit, schema, packages, model digests, scorer hash) |
| Resource caps | one cap per case for tokens (input and output, including failures, retries and parsing repairs), compute seconds, experiment cost units, licensed seat time (G-D3 and above) and wall time |
| Realized consumption | recorded per case and arm for every attempt, converted to cost units by the frozen cost table; the basis of the primary analysis at frozen checkpoints (§3.3) |

Unused budget is not carried over. Reaching a cap ends the case as `STOPPED (budget)` and the
answer held then is scored; an attempt to exceed a cap is an incident.

### 3.2 Why candidate.1's rule was replaced

Candidate.1 matched each case at the smallest *final* realized consumption among the arms. That
level is chosen after execution and depends on outcomes: an arm that happens to be right early and
stops pulls the comparison point down to where the other arms have not yet converged (S2-CE-1
below), the comparison budget differs from case to case for reasons the protocol does not control,
and an arm's score depends on the other arms' traces. It is kept only as a labelled secondary
sensitivity analysis (§3.5).

### 3.3 Primary comparison at frozen realized-cost checkpoints

1. **Frozen ladder.** At G-D0, before any arm runs, the evaluator freezes a strictly increasing
   ladder of realized-cost checkpoints c₁ < … < c_K in frozen cost units, all at or below the common
   cap, and one **primary checkpoint** c* among them (*proposed*: c* equal to the cap, with the
   ladder at 25 %, 50 % and 100 % of the cap; OD-03). The ladder, c*, the cost table and the
   tolerance are in the protocol hash. A checkpoint not in the frozen ladder is refused by the
   analysis code (S2-CE-5).
2. **Reservation before execution.** Every atomic operation (model call, tool call, simulation,
   experiment request, retry, parsing repair) reserves its **maximum** cost in frozen cost units
   before it starts: for a model call, the maximum input and output tokens it may consume times the
   frozen price; for an experiment, its cost-table entry; for a timed operation, its timeout times
   the rate. It may start only if the settled cost of everything before it plus the reservations of
   everything in flight, including its own, fits under the cap. This is what prevents overspend; it
   is enforced at run time (S35-COST-001).
3. **Settlement after execution.** When the operation ends, its realized cost is settled from the
   meter or provider ledger and the unused part of the reservation is released. A settlement above
   the reservation is an **overrun incident**. An operation that cannot be settled (crash, missing
   bill) is charged its full reservation, so missing data can only make an arm look more expensive.
   Local and declared-free model calls are settled in cost units like any other.
4. **Retrospective checkpoint accounting.** After the case, the analysis replays the trace with
   settled costs. The cumulative charge at time t is the settled cost of every operation **started**
   at or before t, including operations still in flight at t, charged in full. An arm's answer at
   checkpoint c is the last anytime answer it committed while that charge was ≤ c; if none, it holds
   no claim at c. Because an operation's result can only be used after it ends, and the operation is
   charged from its start, an operation that straddles c (the charge before it ≤ c, the charge
   including it > c) cannot supply evidence to the answer at c (S2-CE-2), whatever its realized cost
   turns out to be. Variable-cost operations are therefore counted at what they actually cost
   (S2-CE-7), without letting the runtime spend beyond its reservations and without letting a result
   leak into an earlier checkpoint.
5. **Early stopping.** An arm that stops at cumulative charge s holds its final answer at every
   checkpoint ≥ s. Stopping moves no checkpoint and changes no other arm's score: each arm's answer
   at c is a function of its own trace only (S2-CE-1). An arm that stops early with a wrong answer is
   scored wrong at every later checkpoint.
6. **Cap.** Reaching the cap ends the case as `STOPPED (budget)`; an operation whose reservation
   does not fit under the remaining cap is refused before it starts and is an incident if it runs
   (S35-CMP-008).
7. **Primary result.** The primary analysis compares arms on their answers at c*, paired by case,
   with the statistics of §6. The other checkpoints give the pre-registered anytime curve, reported
   in full and never used to pick the primary point.

### 3.4 COST_UNMATCHED

A case is **COST_UNMATCHED** at a checkpoint when any compared arm, for that case:

- has an attempt ledger whose total differs from the independent meter or provider ledger by more
  than the frozen tolerance (missing failures, retries, repairs or model calls; S2-CE-3);
- has no anytime answer stamped with its cumulative charge;
- ran under a different cap, cost table or environment manifest (S2-CE-6), or the checkpoint exceeds
  its cap;
- has consumption in a dimension the frozen cost table cannot convert;
- started an operation without reservation headroom under the cap, or settled an operation above
  its reservation (S2-CE-8, S2-CE-9): these are budget incidents (§8), and the affected run is also
  INVALID under S35-CMP-008.

A COST_UNMATCHED case stays in the denominator. In the primary analysis it is scored, for each claim
of superiority, against the arm whose records are deficient (that arm is scored incorrect when the
claim is that it is better, and correct when the claim is that it is worse), so a deficient record
can never help the arm that produced it. If the share of COST_UNMATCHED cases exceeds the frozen
limit (*proposed* 5 %), the whole comparison is COST_UNMATCHED and cannot support a claim that one
arm is better at equal budget (S35-CMP-002).

### 3.5 Secondary sensitivity analyses (never primary)

Labelled secondary, reported with the primary result, and never able to replace or override it:
final answers at the cap; the candidate.1 rule (each case matched at the smallest final realized
consumption among the arms); area under the anytime-correctness curve over the frozen ladder;
cost-to-discrimination curves; realized cost per correct outcome; and any matching that a reviewer
proposes after unsealing. A conclusion that holds only under a secondary analysis is reported as
such and is not a G-D result.

### 3.6 Adversarial examples (acceptance fixtures of T-S35-CMP-002)

Executable in [semantic_reference.py](semantic_reference.py); ladder 25, 50, 100; c* = 50 in the
fixtures.

| ID | Fixture | Candidate.1 rule | Required result |
|---|---|---|---|
| S2-CE-1 | X is right at cost 10 and stops; Y is right at 30 | matched at 10: X right, Y wrong, "X better at equal budget" | at c*: both right; Y's score is unchanged when X's trace changes |
| S2-CE-2 | an experiment starts at 40 and costs 30 (ends at 70) with the decisive result | answer after the experiment credited at 50 | answer at 50 is the one held before the experiment; at 100 the result counts |
| S2-CE-3 | ledger 35, recorded attempts 10 (hidden failures or retries) | arm looks cheap | COST_UNMATCHED |
| S2-CE-4 | twenty model calls of 2 units, then a 5-unit experiment | calls ignored as "free" | charged 45: no claim at 25, claim at 50 |
| S2-CE-5 | the analyst picks checkpoint 30 after seeing results | accepted | refused |
| S2-CE-6 | one arm with a lower cap | compared anyway | COST_UNMATCHED |
| S2-CE-7 | a model call reserves 30, settles 5, then the decisive answer | charged 30 (or ignored) | charged 5 retrospectively: the answer counts at checkpoint 25 |
| S2-CE-8 | 80 settled, then a call reserving 30 under a cap of 100 (it settles at 10) | accepted because the settlement fit | incident: started without reservation headroom; COST_UNMATCHED |
| S2-CE-9 | a call reserves 10 and settles 12 | charged 12 silently | overrun incident; COST_UNMATCHED |
| S2-CE-10 | a call reserving 40 crashes without a bill, then an answer | charged 0 | charged its reservation 40: no claim at 25, claim at 50 |

## 4. Benchmark and hidden-world generation

The benchmark is built and sealed by the independent evaluator before any arm runs (G-D0).

| Stratum | Content | Truth and sealing |
|---|---|---|
| Synthetic hidden worlds (G-D1) | evaluator-owned generator of silicon-photonics-like worlds: hidden true mechanisms or compositions, distractors, observationally equivalent rivals under part of the catalog, measurement-chain confounds, anomalies, noise, a cost table and an experiment oracle; a pre-registered share of no-mechanism-validatable worlds | generator parameters and code sealed by commitment and unreadable by implementers; seeds drawn after the freeze; implementer-written worlds are development material only |
| Held-out literature cases (G-D2) | problems whose resolution was published after every model's training cutoff, or held out from every corpus; the oracle reveals only data the resolving work reports, when an arm requests and pays for that experiment | case material and truth sealed; resolution dates and rights recorded per case (OD-06) |
| Physical cases (G-D3, G-D4) | at G-D3 evaluator-built licensed simulation cases with a hidden configuration or mechanism; at G-D4 real devices or processes with pre-registered measurements | sealed by the evaluator; independent measurement at G-D4 |

Every case in the frozen list stays in the denominator; exclusions follow only the pre-registered
contamination rule (§7). A protocol, a sealed hidden-world format and tooling for an independent
hidden-world evaluation are on `discovery-independent-evaluation` @ `d7ec9f2` (pushed, not reviewed); no independent world author has yet
supplied worlds, so no independent result exists.

## 5. Metrics

Exactly one metric is primary (*proposed*: true-cause discovery). All five are always reported, for
every arm, with n, the estimate and an interval.

| Metric | Definition | Notes |
|---|---|---|
| **true-cause discovery** (evidential level × outcome category; candidate.4) | at the primary checkpoint, the evaluator re-derives the answer's evidential level (PROPOSAL, SUPPORTED, CONFIRMED) from the trace; only SUPPORTED or CONFIRMED answers get a claim outcome of [Appendix S](mechanism-distinguishability.md) §6: exact identification, indistinguishable alternative, unresolved alternative, correct abstention, false null, force-fit, wrong claim, validated new mechanism; every lower answer is PROPOSAL_ONLY; every category's rate is reported separately with n and a Wilson interval, and none is folded into another | the primary scalar is one pre-registered category (*proposed*: exact-identification rate over the cases whose truth is in the arm's catalog, with force-fit and correct-abstention rates as pre-registered safety endpoints); proposals never count as identifications, discoveries or false discoveries; correct proposals are counted, uncredited |
| **effective mechanism diversity** | certified lower bound (with the upper bound) on the largest number of the arm's admitted hypotheses that are pairwise `DISTINGUISHABLE` under the case's full experiment set ([Appendix S](mechanism-distinguishability.md) §4), and whether the true mechanism was held | never raw hypothesis counts and never a transitive class count; `UNRESOLVED` pairs are listed; descriptive only: not invariant under near-duplicates (S1-CE-11), reported with the raw count and the span, never primary and never by itself evidence that an arm discovers better |
| **discriminating-experiment efficiency** | experiments and realized cost units charged until every surviving held mechanism is in the true mechanism's neighbourhood (none certified distinguishable from it survives) and every other is refuted | censored at the cap; reported as a cost-to-discrimination curve and median with censoring |
| **false discoveries** | false-discovery rate (wrong claims at SUPPORTED or higher ÷ claims at SUPPORTED or higher) and a weighted score: wrong CONFIRMED × w_c, wrong SUPPORTED × w_s, confident claim where a stop was correct × w_stop | *proposed* w_c = 10, w_s = 3, w_stop = 3 (OD-03) |
| **independent reproducibility** | share of a pre-registered subset that the evaluator re-runs in a fresh environment from the frozen manifest with the same final claim and state | any manifest drift makes the re-run invalid, not reproduced; an invalid rate above the frozen limit invalidates the comparison |

## 6. Statistics

Frozen before unsealing (OD-03):

- **Unit:** the case; arms are compared as paired observations on the same cases.
- **Comparisons:** C vs B (primary), C vs A and B vs A (secondary).
- **Binary metrics:** paired difference with an exact McNemar test and a case-resampling bootstrap
  interval (fixed seed), or Newcombe's interval for paired proportions; single-arm proportions use
  the Wilson interval.
- **Count and cost metrics:** paired Wilcoxon signed-rank and a paired bootstrap interval;
  efficiency uses a censoring-aware comparison.
- **Minimum effect of interest:** *proposed* +10 percentage points on the primary metric for C over B.
- **Non-inferiority:** *proposed* 2-point margins on the false-discovery rate and on the correct-stop
  rate in no-mechanism worlds.
- **Multiplicity:** Holm–Bonferroni across five metrics and three comparisons, family-wise
  α = 0.05 (*proposed*), with the primary metric declared in advance.
- **Sample size:** a power or precision calculation for the primary metric, frozen with its
  assumptions, after an exploratory pilot on separate development worlds that never enter the
  sealed set.
- **Interim looks:** none unless pre-registered with an error-spending rule.
- **Reporting:** every case, arm and metric, including null and negative results.

## 7. Contamination controls

- Each literature case records its resolution date against each model's documented training cutoff;
  a case not clearly after every cutoff is excluded before unsealing.
- Case material is checked for overlap against development data and public corpora with a frozen
  method and threshold (the G0 line's `evaluation/contamination.py` is a candidate tool once
  integrated and reviewed).
- Memorization probes ask each model to complete case-specific identifiers; a positive probe
  triggers the pre-registered rule.
- Synthetic seeds are generated after the freeze by the evaluator; implementers have no access to the
  generator's sealed parameters.
- The rule for contaminated cases (exclude, or re-seal and replace) is decided at G-D0, before any
  unsealing; every exclusion is reported with its reason.

## 8. Stopping rules

| Level | Stops when | Result |
|---|---|---|
| Case | cap, time limit, or the arm's own STOPPED or INSUFFICIENT_VALIDATION | the answers held at the frozen checkpoints are scored (§3.3) |
| Study | the pre-registered n, or a pre-registered interim boundary | final analysis |
| Incident | an arm breaches egress, budget, isolation or an Owner gate | affected runs INVALID and reported; above the frozen limit the study is INVALID |
| Paid stage | the Owner's ceiling is reached | reported as partial; no extrapolation |

## 9. Stage order and cost

1. **Zero-cost stage (required first).** Evaluator hidden synthetic worlds; local models declared
   free under the spend administration; no paid API, no license, no physical experiment. The result
   goes to the Owner whatever it shows.
2. **Local literature stage.** Held-out literature cases with the same local models; zero cost.
3. **Paid model stage (optional).** Only under OD-05 with a ceiling. A negative zero-cost result is
   not overturned by a bigger model on the same sealed cases; a new question needs a new sealed set.
4. **Licensed stage.** G-D3, only after SAI 3.4 P-LICENSED and OD-07.
5. **Physical stage.** G-D4, only after SAI 3.4 P-PHYSICAL and OD-08 for each experiment.

## 10. What falsifies "Discovery helps"

See SAI 3.5 §4: no primary-metric gain at the minimum effect, worse weighted false discoveries, a
diversity gain that disappears when counted as certified diversity ([Appendix S](mechanism-distinguishability.md)), worse stopping in
no-mechanism worlds, a gain that disappears at matched realized consumption or depends on a
mismatch, or an unreproducible gain. If arm A matches arm C, the extra machinery is not justified
for discovery on that scope.
