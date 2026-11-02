# SAI 3.5 — Appendix J: Matched-budget A/B/C comparison protocol

Version: `3.5.0-master-candidate.1`. Status: **CANDIDATE — NOT ACTIVE.** Nothing in this protocol
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

Answer schema (all arms, every case): claimed mechanism or none; its epistemic stage and claim state;
evidence references; uncertainty by source; experiments run with realized costs; an optional
`INSUFFICIENT_VALIDATION` or `STOPPED` outcome with reason; and an **anytime answer** after every
experiment or model-call batch, stamped with cumulative realized consumption (needed for §3.2).

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
| Realized consumption | recorded per case and arm for every attempt, converted to cost units by the frozen cost table; the basis of the primary analysis (§3.2) |

Unused budget is not carried over. Reaching a cap ends the case as `STOPPED (budget)` and the
answer held then is scored; an attempt to exceed a cap is an incident.

### 3.2 Comparison at matched realized consumption

Caps alone do not match arms: an arm may stop early and spend little while another spends its whole
cap. The primary analysis therefore compares arms at matched **realized** consumption:

1. For each case, the matched level is the smallest final realized consumption among the arms being
   compared (*proposed* rule; OD-03 freezes the rule).
2. Each arm is scored on the anytime answer it held when its cumulative realized consumption first
   reached the matched level, or on its final answer if it never exceeded that level.
3. Secondary analyses: final answers at the cap; cost-to-discrimination curves; realized cost per
   correct outcome.
4. If an arm's realized consumption is incomplete (missing attempt records), or anytime answers are
   missing, or the measured consumption cannot be compared within the frozen tolerance, the
   comparison is **COST_UNMATCHED**: it is reported, and it cannot support a claim that one arm is
   better at equal budget (S35-CMP-002).

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
| **true-cause discovery** | share of cases whose final claim lies in the true cause's equivalence class under the case's full experiment set; in a no-mechanism case a correct `INSUFFICIENT_VALIDATION` counts as correct | scored at the claim's stated state; a correct mechanism held only as an exploratory idea does not count |
| **effective mechanism diversity** | number of distinct distinguishable mechanism classes among the arm's admitted hypotheses under the case's experiment set, and whether the true class was among them | never raw hypothesis counts; undecidable merged pairs are listed |
| **discriminating-experiment efficiency** | experiments and realized cost units consumed until the true class is the only surviving class | censored at the cap; reported as a cost-to-discrimination curve and median with censoring |
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
| Case | cap, time limit, or the arm's own STOPPED or INSUFFICIENT_VALIDATION | the answer held then is scored |
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
diversity gain that disappears when counted as distinguishable classes, worse stopping in
no-mechanism worlds, a gain that disappears at matched realized consumption or depends on a
mismatch, or an unreproducible gain. If arm A matches arm C, the extra machinery is not justified
for discovery on that scope.
