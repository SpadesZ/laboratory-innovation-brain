# SAI 3.5 — Appendix S: Mechanism identity, distinguishability and diversity

Version: `3.5.0-master-candidate.5`. Status: **CANDIDATE — NOT ACTIVE.** `READY_FOR_REAL_RESEARCH = false`.
Authority: normative. Refines S35-MECH-001 of [SAI 3.5](../SAI_3.5.md) and the uses of
distinguishability in S35-HYP-002, S35-MECH-002, S35-SEL-001, S35-SEL-002, S35-CMP-005 and
S35-NOV-002. It replaces the class-partition definition of `3.5.0-master-candidate.1`, which
treated pairwise indistinguishability as an equivalence relation (§1). The executable form of every
definition and counterexample here is [semantic_reference.py](semantic_reference.py); the candidate
checker runs it.

## 1. Why candidate.1 was wrong

Candidate.1 put two hypotheses "in the same class under E" when no experiment separated them, and
counted classes. That is a partition only if indistinguishability is transitive. It is not.

**Mandatory counterexample (S1-CE-1).** One experiment, standard error 1, threshold τ = 1.
Mechanism A predicts 0, B predicts 0.75, C predicts 1.50.

| Pair | Separation | Verdict |
|---|---|---|
| A, B | 0.75 | `INDISTINGUISHABLE` |
| B, C | 0.75 | `INDISTINGUISHABLE` |
| A, C | 1.50 | `DISTINGUISHABLE` |

A transitive merge puts A, B and C in one class and reports diversity 1, although the experiment
can tell A from C. A raw count reports 3, although no experiment can tell B from either neighbour.
The defensible answer is 2: there exist two mechanisms (A and C) that the experiments can tell
apart, and no three. The [prototype on `118a4ac`](implementation-status.md) computes connected
components (a transitive merge), so it does not meet S35-MECH-001 as revised.

## 2. Physical mechanism identity

A held hypothesis h declares a **mechanism**: a canonical, versioned forward model
F_h(θ, x) → predicted distribution of each observable at conditions x, with its parameter domain
Θ_h, its declared physics family and its assumptions (SAI 3.3 §8 and §17.5). Its **identity** is the
content hash of the canonical forward-model declaration (the repository's JCS profile), excluding
names, labels, wording, provenance and the proposing component.

- Two hypotheses with the same identity are **aliases**. An alias is recorded as such and never
  counts as a second mechanism, a second class, a new idea or novelty.
- Identity is necessary for sameness, not for indistinguishability: two different identities may
  still be experimentally indistinguishable (§3).
- A mechanism whose forward model cannot be stated (no typed predictions) has no identity and cannot
  be admitted (S35-HYP-002); it stays a stage-1 idea.

## 3. Pairwise experimental distinguishability

Inputs, all recorded and versioned: the experiment set **E** (each experiment's capability,
conditions, noise model and declared replicates r_e, so standard error se_e), the pre-registered
threshold **τ** (OD-17), and each hypothesis's parameter domain.

The separation of h and k under E is the worst case over parameters, jointly over experiments:

> D_E(h, k) = min over θ ∈ Θ_h, φ ∈ Θ_k of max over e ∈ E of |μ_h(e, θ) − μ_k(e, φ)| / se_e

The minimum over parameters means that a pair counts as separable only if no admissible choice of
parameters makes the two agree; the maximum is taken for one parameter pair across all experiments,
because one parameter value must explain every experiment (S1-CE-6 shows why per-experiment worst
cases would be wrong). Parameter uncertainty enters through Θ: a wider domain can only lower D
(S1-CE-4). More replicates lower se_e and can raise D (S1-CE-7).

D is computed, not assumed. The computation records a certified interval [D_lo, D_hi] (a finite
parameter cover gives D_hi; a certified cover error, Lipschitz bound or interval method gives
D_lo). Each unordered pair gets exactly one verdict:

| Verdict | Condition | Meaning |
|---|---|---|
| `DISTINGUISHABLE` | D_lo ≥ τ | some available experiment set, at the declared replicates, separates the pair for every parameter choice |
| `INDISTINGUISHABLE` | D_hi < τ, or same identity | some parameter choice makes the pair agree within τ on every experiment of E |
| `UNRESOLVED` | otherwise | the computation cannot certify either; treated as not distinguishable wherever that is conservative (§4–§6) |

Properties that follow, and that no implementation may break:

1. The relation is symmetric and reflexive. It is **not transitive**; no implementation may merge
   transitively, compute connected components, or use union-find to form "classes" for any count,
   score, novelty decision or refutation.
2. Every verdict names the E version, τ, the noise model and replicates, and the bound method. A
   change of E, τ, replicates or a parameter domain recomputes every affected verdict; a stale
   verdict cannot justify a later transition.
3. A verdict is a property of the pair under E, never of the names.

## 4. Diversity: certified bounds

**Effective mechanism diversity** under E is the largest number of held mechanisms that are
pairwise `DISTINGUISHABLE` (the maximum clique of the `DISTINGUISHABLE` graph; equivalently the
maximum independent set of the "not certified distinguishable" graph).

| Figure | Definition | Use |
|---|---|---|
| lower bound (headline) | maximum clique with `UNRESOLVED` treated as not distinguishable | every report, metric and score |
| upper bound | maximum clique with `UNRESOLVED` treated as distinguishable | reported beside the lower bound while any pair is `UNRESOLVED` |

What the definition guarantees (each is proved by the definition and checked by a counterexample):

- **Alias invariance** (S1-CE-2): an alias has the same identity, is `INDISTINGUISHABLE` from its
  original and has the same verdict against everything else, so no clique can hold both.
- **Correct on non-transitive chains** (S1-CE-1): the A–B–C chain gives 2, not 1 or 3.
- **Monotone, +1-bounded** (S1-CE-8): adding one mechanism never lowers the figure and raises it
  by at most 1, and only when the new mechanism is certified distinguishable from every member of
  some clique of the previous size.
- **Span-bounded**: for one observable with standard error se, the figure never exceeds
  ⌊span/(τ·se)⌋ + 1, where span is the range of the held predictions (S1-CE-11); in general it is
  bounded by the packing number of the held predictions under the separation metric.
- **Unresolved pairs never raise the headline** (S1-CE-5).

What it does **not** guarantee (corrected in candidate.3; candidate.2 overstated it):

- **It is not invariant under near-duplicates.** A mechanism `INDISTINGUISHABLE` from one already
  held can still raise the figure, because it can be distinguishable from members its near twin is
  not. Counterexample **S1-CE-11**: {0, 0.9, 1.8, 2.7} at τ = 1 has diversity 2; adding 1.1, which
  is `INDISTINGUISHABLE` from 0.9, makes {0, 1.1, 2.7} pairwise distinguishable, so the diversity
  becomes 3. The value 3 is correct for the defined quantity; what is wrong is any claim that
  near-duplicates cannot change it. S1-CE-3 is an instance where they happen not to.
- **It does not count distinct mechanism families or measure discovery ability.** It describes how
  widely the held set spreads under E. A proposer can raise it by adding hypotheses that are spread
  out, whether or not they are physically plausible. No heuristic that "removes near-duplicates"
  (for example greedy de-duplication) may replace it: such a rule computes a different, order-
  dependent quantity and is rejected by the semantic self-test.
- Consequently diversity is never a primary metric, is reported with the raw hypothesis count and
  the span beside it, and a diversity difference between arms is never by itself evidence that one
  arm discovers better (S35-CMP-005, SAI 3.5 §4).

Computation: exact for the sizes of a campaign or case (exhaustive or branch-and-bound); if a
deployment ever needs an approximation, it reports a certified lower bound (a found clique) and a
certified upper bound (for example a colouring of the complement), never an estimate.

The connected-component count of the "not certified distinguishable" graph is always at most the
lower bound (one representative per component is a clique); it may be shown as "clusters" in the
workspace for navigation, labelled as such, and never as diversity.

## 5. Claims, refutations and selection

- **What a claim reports** (S35-SEL-002). A claim for h reports its *neighbourhood*: every held
  mechanism that is not certified `DISTINGUISHABLE` from h under E, each with its verdict. This is
  not an equivalence class: in S1-CE-1 a claim for B cannot exclude A or C, while a claim for A
  excludes C but not B.
- **Refutation.** A refutation of h is applied only when no mechanism in h's neighbourhood survives
  the same evidence; otherwise it is recorded and held (the rule of S35-SEL-002, stated pairwise, so
  that it never depends on a transitive class).
- **Selection** (S35-SEL-001). The value of a candidate experiment e is the set of surviving pairs
  that are not `DISTINGUISHABLE` under E and become `DISTINGUISHABLE` under E ∪ {e}, weighted by the
  versioned policy, per unit of CostVector. An experiment that converts no pair is never ranked above
  one that converts a pair at equal cost.

## 6. Scoring and novelty

- **Scientific-evaluation outcomes** (S35-CMP-005 metric 1; candidate.3, two axes since
  candidate.4). Each case and arm gets exactly one outcome at the primary checkpoint, computed by
  the evaluator from sealed truth under the case's full experiment set; names never matter.

  *Axis 1, evidential level* of the final answer, re-derived by the evaluator from the arm's trace;
  the arm's own label is never trusted (S4-CE):

  | Level | Re-derived when | Claim states (S35-HYP-003) |
  |---|---|---|
  | `PROPOSAL` | no test of the claim whose prediction was recorded (hashed) before its data was requested and which the claim passes when the evaluator re-scores it under the pre-declared rule | PROPOSED, ADMITTED, REGISTERED, UNDER_TEST, CHALLENGED, INCONCLUSIVE |
  | `SUPPORTED` | such a test exists and passes on re-scoring, and every quantity deciding its pass or riskiness (noise model, predictive uncertainty, alternatives, thresholds) was computed by the evaluator from the data admitted before the registration, never supplied by the arm (S5-CE) | SUPPORTED |
  | `CONFIRMED` | additionally a re-derivable Causal Warrant Gate decision with a qualifying signed review | CONFIRMED (stage 3) |

  *Axis 2, outcome category.* Only an answer at `SUPPORTED` or `CONFIRMED` receives one of the
  claim categories below; every other answer is `PROPOSAL_ONLY` if the arm only proposed it and
  `UNSUPPORTED_CLAIM` if it asserted, endorsed or acted on it. The *stance* is re-derived from the
  trace too: an answer is proposed only if the arm labelled it a proposal and no record acted on it
  (no promoted belief, no report stating it as the cause, no later step taking it as a premise); a
  missing stance counts as asserted and a label never outweighs an action. The outcomes are reported as
  separate rates, per evidential level, and are never merged into one another:

  | Outcome | Condition | Credit |
  |---|---|---|
  | `EXACT_IDENTIFICATION` | the claimed mechanism has the true mechanism's identity | identification |
  | `INDISTINGUISHABLE_ALTERNATIVE` | another identity, certified `INDISTINGUISHABLE` from the truth | correct within experimental resolution, reported separately; never an exact identification |
  | `UNRESOLVED_ALTERNATIVE` | another identity, `UNRESOLVED` against the truth | none (listed in a sensitivity bound only) |
  | `CORRECT_ABSTENTION` | no claim, and no held mechanism was the truth or indistinguishable from it (including no-mechanism cases and true families absent from the catalog) | safety, reported separately; never an identification or a discovery |
  | `FALSE_NULL` | no claim, although a held mechanism was the truth or indistinguishable from it | none |
  | `FORCE_FIT` | a held mechanism distinguishable from the truth claimed while the truth is outside the held set | error |
  | `WRONG_CLAIM` | any other wrong claim, including any claim in a no-mechanism case | error |
  | `VALIDATED_NEW_MECHANISM` | a mechanism outside the arm's catalog at case start, matching the truth (identity or `INDISTINGUISHABLE`), that passed a prospectively registered test the arm did not control (at G-D4: the Causal Warrant Gate and S35-VAL-005) | the only outcome that counts as new-mechanism discovery |
  | `PROPOSAL_ONLY` | an answer at `PROPOSAL` that the arm only proposed, in or out of the catalog | none: never an identification, a discovery or a false discovery, whatever it says; the number of proposals that happen to match the truth is reported beside it and never credited |
  | `UNSUPPORTED_CLAIM` | an answer at `PROPOSAL` that the arm asserted, endorsed or acted on (candidate.5) | error, whether or not it matches the truth; reported beside the supported false-discovery rate, never folded into it and never hidden among proposals |

  Why both axes (candidate.4): in candidate.3 an in-catalog answer was credited whatever its
  evidence, so an arm that named the right mechanism without ever testing it scored like an arm
  that tested it, and the "prospective validation" of a new mechanism was a flag the arm set. A
  research agent is scored on what its evidence supports, not on what it guessed. Why the stance
  (candidate.5): with proposals neutral, an arm could assert untested conclusions at no cost, so
  its error rate fell as its evidence did. Every report therefore gives, per arm, the asserted,
  supported, unsupported and proposed answers (`outcome_report()`), so a lower error count bought
  with proposals or abstentions stays visible.

  The executable form is `classify_outcome()` with `verified_evidence()` and `assertion_status()` in
  [semantic_reference.py](semantic_reference.py) (S1-CE-9, S3-CE, S4-CE and S5-CE). The primary scalar is pre-registered under OD-03 from one category, never a
  sum of categories.
- **Effective diversity** (S35-CMP-005 metric 2) is the §4 lower bound under the case's full
  experiment set, with the upper bound and whether the true mechanism is in the arm's held set.
- **Novelty** (S35-NOV-002, Appendix D §3). Against the mechanisms of the covered prior art K, a
  finding's mechanism is `KNOWN_MECHANISM_REDISCOVERY` if it is `INDISTINGUISHABLE` from any member
  of K; if it is `UNRESOLVED` against any member it is at most a candidate with those pairs listed;
  only if it is `DISTINGUISHABLE` from every member may it be `NEW_PHYSICAL_KNOWLEDGE_CANDIDATE`
  (S1-CE-10). Renaming a known mechanism therefore produces a rediscovery, not novelty.
- **G-D scores** use only these definitions; an arm's diversity or novelty figure computed by any
  other rule is not a G-D figure.

## 7. Records

The `MechanismClassPartition` record of candidate.1 is replaced by `DistinguishabilityGraph`
([Appendix C](records-and-states.md) §2): experiment-set version, τ, noise model and replicates,
bound method, the held mechanisms with identities, every pair with [D_lo, D_hi] and verdict, the
aliases, the diversity lower and upper bounds, and the never-considered families. It is
deterministic for identical inputs, append-only, and recomputed into a new record whenever E, τ,
replicates or a domain changes.

## 8. Catalog adequacy and out-of-catalog truth

Distinguishability says which held mechanisms can be told apart; it says nothing about whether any
of them is true. When the true mechanism family is absent from the held set, the best-fitting held
mechanism is still wrong. Therefore (S35-MECH-002):

1. every held mechanism is tested for **adequacy** against the admitted data by a pre-registered
   criterion relative to the noise model (for example a goodness-of-fit or residual-structure test
   at a pre-registered level, consistent across replicates; OD-18), never by rank among the held
   mechanisms;
2. if no held mechanism is adequate, the system records the residual as an `UNEXPLAINED` anomaly,
   records catalog incompleteness, and may only: abstain from endorsing any mechanism, expand the
   search space (S35-MECH-002 order, including new mechanisms proposed as stage-1 ideas), reframe
   (S35-REF-001 `WIDEN_MECHANISM_SPACE`, `QUESTION_MEASUREMENT_CHAIN`), select an experiment that
   discriminates between the held mechanisms and "none of them is adequate", or stop with
   `INSUFFICIENT_VALIDATION`;
3. it never endorses, hands over or reports the best-fitting inadequate mechanism as a supported or
   likely explanation; a more expensive campaign is held to the same rule (a larger budget never
   relaxes the adequacy criterion).

## 9. Acceptance counterexamples

Each is a deterministic assertion of [semantic_reference.py](semantic_reference.py) and a required
fixture of T-S35-MECH-001 (and of the tests named) when the runtime is built.

| ID | Fixture | Required result | Rejects |
|---|---|---|---|
| S1-CE-1 | A = 0, B = 0.75, C = 1.50, se = 1, τ = 1 | A/B and B/C `INDISTINGUISHABLE`, A/C `DISTINGUISHABLE`; diversity [2, 2]; B's claim lists A and C | transitive merge (1), raw count (3) |
| S1-CE-2 | S1-CE-1 plus fifty aliases of B | diversity unchanged | renaming |
| S1-CE-3 | S1-CE-1 plus fifty forward models within 0.1 of B | diversity unchanged in this instance (an illustration, not a guarantee; see S1-CE-11) | — |
| S1-CE-4 | domains {0, 1, 2} and {2.5, 3} | `INDISTINGUISHABLE` | nominal-point comparison ignoring parameter uncertainty |
| S1-CE-5 | a pair with D_lo < τ ≤ D_hi | `UNRESOLVED`; lower bound unchanged, upper bound + 1 | counting unresolved pairs as distinct |
| S1-CE-6 | a second experiment separating A and B; a two-point domain separated jointly | diversity 3 under E2, 2 under E2 restricted to x; joint worst case `DISTINGUISHABLE` | stale E; per-experiment worst case |
| S1-CE-7 | four replicates | A/B `DISTINGUISHABLE` | ignoring declared replicates |
| S1-CE-8 | adding one mechanism | lower bound rises by at most 1 | non-monotone metrics (not gaming: see S1-CE-11) |
| S1-CE-9 | renamed truth; indistinguishable alternative; distinguishable claim | `EXACT_IDENTIFICATION`; `INDISTINGUISHABLE_ALTERNATIVE`; `WRONG_CLAIM` | name-based scoring; merging alternatives into identification |
| S1-CE-10 | renamed prior-art mechanism; unresolved comparison | rediscovery; at most a listed-unresolved candidate | novelty by renaming |
| S1-CE-11 | {0, 0.9, 1.8, 2.7}, τ = 1, then add 1.1 (`INDISTINGUISHABLE` from 0.9) | diversity 2, then 3; never above the span bound | any claim of near-duplicate invariance; greedy de-duplication heuristics |
| S3-CE | unresolved alternative; truth outside the catalog with a held claim, with no claim; truth in the catalog with no claim; no-mechanism case with and without a claim; out-of-catalog answer without evidence, supported and matching, supported and wrong | `UNRESOLVED_ALTERNATIVE`; `FORCE_FIT`; `CORRECT_ABSTENTION`; `FALSE_NULL`; `CORRECT_ABSTENTION`, `WRONG_CLAIM`; `PROPOSAL_ONLY`, `VALIDATED_NEW_MECHANISM`, `WRONG_CLAIM` | merging outcome categories; counting proposals as discoveries |
| S4-CE | an in-catalog answer that names the true mechanism: with no test, with a test registered after its data, with a test it failed, with a passed prospective test, with a Causal Warrant Gate decision; a wrong and a force-fitted answer without a test | hedged: `PROPOSAL_ONLY` (hit counted, uncredited) three times; `EXACT_IDENTIFICATION` at `SUPPORTED`; at `CONFIRMED`; `PROPOSAL_ONLY` twice, never a false discovery | crediting untested answers; trusting the arm's own evidential label |
| S5-CE | an untested in-catalog answer that names the truth, asserted and with no stance recorded; a force-fit labelled a proposal but promoted; an answer whose test passed with the arm's own uncertainty or alternatives, asserted and hedged; a run with one asserted untested force-fit, one supported identification, one hedged proposal and one abstention | `UNSUPPORTED_CLAIM` twice; `UNSUPPORTED_CLAIM`; `UNSUPPORTED_CLAIM`, `PROPOSAL_ONLY`; report: 2 asserted, 1 supported, 1 unsupported claim, 1 error, 1 proposal | hiding asserted conclusions as proposals; trusting a proposal label over an action; trusting arm-supplied uncertainty or alternatives |
