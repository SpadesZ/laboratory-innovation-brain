# Discovery Loop: independent hidden-world evaluation protocol

**Status: protocol draft v0.1 for Owner approval, plus offline tooling. No independent evaluation
has been run.** Every result produced so far is engineering evidence on synthetic worlds written by
the engine's own author lineage. `READY_FOR_REAL_RESEARCH` stays false; G0 stays NOT PASSED.
Discovery stays isolated and offline: no migration, no connection to the research flow, no
production scientific confirmation, no model, network, simulator or paid call.

Traditional Chinese summary: [`discovery-independent-evaluation-protocol.zh-TW.md`](discovery-independent-evaluation-protocol.zh-TW.md).
Engine design: [`docs/implementation/discovery-loop-offline.md`](../implementation/discovery-loop-offline.md).
Offline refinements (cost curves, held-out classes, scaffold):
[`docs/audit/discovery-independent-evaluation-2026-11-02/`](../audit/discovery-independent-evaluation-2026-11-02/).

---

## 0. The question, and what this protocol cannot answer

> On hidden worlds its authors never saw -- including worlds whose true mechanism is absent from its
> catalog -- does adding Discovery to the LIB workflow reach the true cause more often, with fewer
> false discoveries, per unit of experimental cost **actually consumed**?

A pass answers that question for the synthetic world distribution the world authors wrote, against
the engine's declared experiment interface. It says nothing about physical reality, real literature
or real models (§10).

## 1. Roles and separation

| Role | Does | Must not |
|---|---|---|
| **Owner** | Approves this protocol with its values filled in (§11), names the people, authorizes any model or paid resource, decides on the result | Pass world content to the engine author or arm operators |
| **Engine author (E)** | Freezes the engine, its catalog and protocol; publishes the engine manifest | Author, see, or receive any hidden world, any per-case output before scoring, or any score before the run is closed |
| **World author(s) (W)** | Writes hidden worlds against the frozen interface (§3); seals them; keeps the sealed file outside the repository | Show worlds to E or to arm operators; change a world after the commitment is published |
| **Evaluator (V)** | Freezes the run manifest; runs every arm blind; operates the laboratory service; reveals and scores with a frozen scorer | Tune anything; re-run selectively; report case content before scoring |
| **Arm operators** | Run arm A and arm B harnesses (§6) exactly as frozen | See sealed files, scores, or other arms' outputs |
| **Reviewer (R)** | Checks independence declarations and the scoring audit trail | -- |

Separation rules:

- W, E and V are **different people**. An AI agent session, or a chain of sessions, that wrote or
  edited the engine, its catalog or this tooling counts as the engine author and may not be W or V.
  The same holds for the author lineage of `benchmarks/discovery_independent/example.hidden-worlds.json`.
- Each role signs a conflict-of-interest declaration (prior access to the engine's development
  worlds, seeds, evidence directories or this repository's discovery tests).
- Communication between W and E is limited to the published interface (§3) and to questions about
  it, logged and answered publicly to all world authors.
- At least two world authors contribute, each writing at least 40% of their worlds in held-out
  families (§4); one world author alone is still one author's distribution.

## 2. Timeline: commit, then reveal

| Step | Who | What | Published |
|---|---|---|---|
| T0 | Owner | Approves this protocol with every value of §11 fixed | protocol SHA-256 |
| T1 | E | Freezes the engine: commit SHA, SHA-256 of every `src/lab_brain/discovery/*.py` and the catalog module (the `sources_sha256` block of `benchmark.manifest`), catalog ref and digest, every arm's protocol digest; environment manifest (interpreter, platform, `pyproject.toml` and lock hashes, the `lab_brain.evaluation.environment`-style report) | engine manifest |
| T2 | E → W | Releases the interface: the catalog (experiments, entries, sigmas, costs, declared classes and prior), the motivating experiment, the cap grid | interface digest = catalog digest |
| T3 | W | Writes worlds (§3, §4) outside the repository; validates with `parse_hidden_worlds`; seals with `seal` (fresh 32-byte salts); keeps the sealed file; hands V the engine package | commitments root |
| T4 | V | Freezes the run manifest: engine manifest hash, package root, scorer source SHA-256s, statistics seed and resamples, cap grid, arm harness hashes, model pins | run manifest hash |
| T5 | V, operators | Blind runs: every arm, every case, every cap, once (§5); outputs bound to the package root and run manifest | output digests |
| T6 | W → V | Reveal: V runs `reveal` (refuses any case whose recomputed commitment differs, any added or dropped case, any altered public part) | sealed file (after scoring) |
| T7 | V | Scores with the frozen scorer; R audits | score report |
| T8 | Owner | Decides | decision record |

A crash may be re-run once with the same seed (the run is deterministic, so the result is the same
or the crash recurs); any other re-run, any change to the engine, harness or scorer after T4, or any
look at per-case outputs before T6 voids the run and **burns the world set** (a new set must be
written and sealed). Amendments are allowed only before T4 and are published.

## 3. What is sealed, what is public

**The hidden-world file** (`lab-brain/discovery-hidden-worlds@1`; schema
`benchmarks/discovery_independent/hidden-worlds.schema.json`; authoritative validator
`lab_brain.discovery_eval.hidden_worlds.parse_hidden_worlds`):

- `interface`: the engine catalog's ref and digest, and the motivating experiment. A file written
  against another catalog is refused.
- Per world, `public.removed`: experiments this world's lab cannot run and why. The only per-world
  text any arm sees.
- Per world, `hidden`: `category`, `seed`, `effects` and `noise`. An effect is either a declared
  class of the catalog at an amplitude inside its declared range, or a **tabulated** effect the
  engine does not have (`effect_id`, a sensitivity table over declared experiment entries, an
  amplitude, an optional session slope for non-stationary effects). Noise is Gaussian at a scale of
  each entry's declared sigma, with optional single glitches.
- Non-integer numbers are decimal strings (the commitment hashes canonical JSON, which refuses
  floats). `example_only` must be false for a hidden set; a hidden set is refused inside the
  repository.

**Validation refuses** malformed files (wrong kind, missing or extra keys at any depth, floats,
out-of-range or non-finite numbers, duplicate ids, unknown experiments or entries, a declared
amplitude outside its range, an effect named like an engine class, a category its effects do not
satisfy) and **truth leaks**: a removal reason or suite name containing, as a token, a truth class
id, family, mechanism, regime, effect id, telling category or world id; a removed motivating
experiment; a `held_out` world the engine cannot in fact separate from one of its own hypotheses.
The check is lexical; a paraphrase is not detected, so V also reads every removal reason.

**Sealing** mirrors `lab_brain.evaluation.sealing` with its own domain tags:
`case_id = "case-" + sha256(CASE_DOMAIN || salt)[:12]`,
`commitment = sha256(COMMIT_DOMAIN || salt || canonical_json({case_id, world_id, public, hidden}))`,
`root = canonical_hash({case_id: commitment})`. The **engine package**
(`lab-brain/discovery-engine-cases@1`) holds the interface, per opaque case id only the public part,
the commitments and the root, ordered by case id: world ids, author order and categories do not
reach the engine side. `parse_engine_package` refuses any key outside its schema and any truth key
(`hidden`, `effects`, `amplitude`, `seed`, `category`, `salt`, `world_id`, ...) at any depth.

**Process separation.** In the real run the laboratory is a separate service process owned by V,
holding the sealed file; the engine process has no read access to it (separate container or user,
sealed file not mounted) and calls only `motivating()` and `measure(experiment, replicate,
session)`. The service meters realized cost itself (§5) and refuses an experiment beyond the cap or
unavailable in the world. The in-process `blind_laboratory` of the offline tooling guards against
accidental exposure only: in one Python process a closure is reachable.

**Information each arm receives** (identical for all arms): the catalog's question; the experiment
interface with costs, entries and sigmas; the declared catalog; the motivating observation; the
measurement tool; the cap; the case's removed experiments and reasons. Nothing else: no case or
world id, category, seed, other arms' outputs, or any evidence directory of this repository.

## 4. World composition and the held-out mechanism classes

Per world author, before sealing (counts are minimums for the whole set; values in §11):

| Category | Truth | Correct outcome |
|---|---|---|
| `declared` | one catalog class (initial, variant or extended; with or without removed experiments, glitches, measurement-chain artefacts) | the truth's class by the metrics rule: the truth, nothing an available experiment separates from it, and every equally simple alternative it cannot be separated from |
| `composition` | two catalog classes of different families | its class, same rule |
| `null` | no effect | `NO_EFFECT_BEYOND_NOISE` |
| `held_out` | at least one tabulated effect of a family absent from the catalog and prior; stationary; distinguishable from every engine hypothesis | **no claim** |
| `aliased_held_out` | as `held_out`, but some engine hypothesis cannot be separated from it | scored separately (below) |
| `non_stationary` | an effect that changes with the measurement session | **no claim** |

**Unseen mechanism classes.** A held-out family is one that appears nowhere in the engine's
catalog: not as an initial class, a variant, an extended class, a component of a composition, or a
prior weight. W writes its forward model as a table over the declared experiment interface, not by
renaming or rescaling a catalog class. At seal time V verifies, from the forward models alone, that
the truth's fixed-amplitude predictions are separated from **every** hypothesis the engine's catalog
can express (the noise model, each class, each family pair) by at least the engine's own `tau` over
the available protocol replicated `R` times (`truth_aliases`). If not, the world is
`aliased_held_out`; labelling it `held_out` is refused.

**Scoring an unseen class.** No mechanism the engine can name is true, so:

- **correct** = no claim: `STOPPED_UNEXPLAINED`, `STOPPED_INSUFFICIENT_VALIDATION`, a
  `NARROW_SCOPE` or `CHANGE_OBSERVABLE` record without a claim. Reported separately: whether the
  stop left a record a person can act on (an open anomaly or a reframing record) or was silent
  (stopped before testing anything);
- **force-fit** (a false discovery) = any claimed mechanism class;
- **false null** (a false discovery) = `NO_EFFECT_BEYOND_NOISE`: the effect is real;
- `aliased_held_out`: a claim of an alias is a **surrogate** (reported; neither correct nor counted
  as an engine false discovery in the primary rates); any other claim is a force-fit; worlds of this
  category are excluded from the primary endpoints.

An arm that can name mechanisms outside the catalog (arm A, and arm B if its hypothesis generation
is open) may name the held-out mechanism. That is **open-world correct**: scored by V with a frozen
rubric mapping free-text mechanisms to hidden effect ids (two raters blind to arm, agreement
reported), and reported as its own endpoint. Engine arms score zero there by construction; this is
an honest difference between the arms, not a defect to hide.

## 5. Realized-cost comparison

- **Caps.** One grid `C` (default `4, 6, 8, 10, 12, 16, 20, 24`). Every arm runs every case at every
  cap. A cap is a ceiling the arm may not exceed; it is never reported as the cost.
- **Realized cost** = the sum of declared costs of the experiments the laboratory service actually
  ran, counted by the service, not by the arm. The engine's own report must equal it. A run that
  reaches the cap is refused its next experiment by the service; an overspend attempt voids that run
  (scored as a failure) and is reported.
- **Common random numbers.** The noise of the k-th run of experiment E in a world is fixed by the
  world seed, so arms that run the same experiment the same number of times read the same numbers.
- **Per cap and arm:** correct and false-discovery rates (Wilson 95%), realized cost (mean with a
  seeded percentile bootstrap, median, p90, max), utilisation (realized / nominal), the share of runs
  that ran out of budget, realized cost per correct outcome (ratio bootstrap), and the share of
  experiments followed by a refutation (discriminating-experiment share).
- **Cost-discovery curves:** correct rate against cap, each point annotated with the realized mean;
  and correct rate against realized mean cost.
- **Area under the curve:** per case, the trapezoidal area under its 0/1 correct-at-cap curve over
  `[min C, max C]`, divided by the range; the arm's AUC is the mean over cases (a seeded bootstrap
  over cases), and paired AUC differences are bootstrapped over cases.
- **Budget-to-first-correct (BFC):** per case, the smallest cap at which the arm is correct, and the
  realized cost at that cap; censored above `max C`. Reported: the share solved within the grid
  (Wilson), the censored lower median with a bootstrap interval, the mean realized cost at first
  correct among solved cases, and the share that stays correct at every larger cap. BFC selects the
  cap after the fact; it describes the arm, it is not an operating point.
- **Matched budget** means equal caps **and** reported realized use. Two arms are compared at equal
  caps; a claim about efficiency compares realized cost per correct outcome, always next to the
  false-discovery rate (an arm that stops early with wrong answers is not efficient).
- **Invariants checked on every run:** realized cost never exceeds the cap; the meter equals the
  engine's report; a run that ended with at least the dearest available experiment's cost unspent
  is the same run at every larger cap (by construction: no choice was ever restricted). The correct
  rate itself is not monotone in the cap by construction; where it falls is reported.

## 6. Arms

| Arm | Real definition | Current deterministic substitute (offline only) |
|---|---|---|
| **A** single frontier LLM | One pinned model receives the §3 information set and a `measure` tool with the same costs and cap; it outputs a typed final answer (claim class, no claim, or stop) | **B0 "single hypothesis"**: the most prior-likely initial class consistent with the motivating observation, tested once on the cheapest experiment where it predicts an effect. **It is NOT an LLM** and says nothing about how any model behaves |
| **B** the real existing LIB workflow | The PostgreSQL-backed `VerificationLoop` (`src/lab_brain/verification/loop.py`) with its real hypothesis generation, admission, budget gate and confirmation rule, driven by a harness | **B1 "existing LIB style"**: `investigate` with every discovery switch off -- a re-implementation of the loop's policy *shape* inside this engine. **It is NOT the PostgreSQL LIB `VerificationLoop`** |
| **C** LIB + Discovery | B with the Discovery Loop integrated into the research flow | **B2**: the offline engine with every switch on, in isolation. Discovery is **not** connected to the research flow; connecting it is an Owner decision |

**Before arm A can run:** an Owner-approved model -- by default a local model under Owner policy, or
a hosted one only with the enforced spend ceiling (`lab_brain.llm_runtime.spend`, the G0 live-budget
guard) and Owner-declared prices; pinned model id, provider, version or weights SHA-256, tokenizer,
decoding parameters (temperature 0 or a fixed seed; number of samples), max tokens, system prompt and
tool schema hashes, harness commit; a frozen answer schema mapped onto the outcome vocabulary; a
frozen rubric for open-world answers.

**Before arm B can run:** a harness that (i) turns the catalog into LIB hypotheses and the
laboratory service's readings into Runs and Attestations through the admission gate, each
prediction bound to a DomainPack-declared OutcomeSpace (the discovery observables have none today:
an Owner decision, §23.4); (ii) gives each case a fresh, migrated database (`lab_brain_*` per run);
(iii) enforces the cap through the existing budget gate and the laboratory meter; (iv) maps LIB's
terminal states onto the outcome vocabulary (a warranted SUPPORTED class → a claim; nothing
confirmed is possible without warrants, and none exist in an evaluation database); (v) pins the
same model as arm A for any model-backed step. Arm C needs the same harness plus the integration.

**Contamination controls.** No arm process can read the sealed file, the evidence directories of
this repository, earlier outputs or the network (no web tool; container without egress except an
Owner-approved model endpoint). Every prompt and tool call is logged and hashed; V's scorer searches
them for truth strings (as the G0 scorer's leak check does). Worlds are new by construction, but a
model may know the physics of a held-out mechanism from training: that is part of what arm A is,
and it is measured by the open-world endpoint, not removed.

**Information exposure controls.** The §3 information set is identical across arms; any extra
input to one arm is declared before T4 as inherent to that arm (a model's prior knowledge) or
removed.

## 7. Metrics

| Metric | Definition | Role |
|---|---|---|
| True-cause discovery | Correct outcome by §4's rule on expressible truths; no claim on unexpressible ones; open-world correct reported apart | primary |
| False discoveries | A claim disjoint from the truth's class (expressible), any claim (unexpressible), a false null; force-fit and surrogate rates on held-out worlds | co-primary (safety) |
| Effective mechanism diversity | The number of **distinguishable** classes an arm examined (connected components of the indistinguishability graph), never a count of hypotheses; for free-text arms, after mapping onto catalog fingerprints or "novel" | secondary, never a success criterion |
| Discriminating-experiment efficiency | Share of experiments followed by at least one refutation; distinguishable classes resolved per realized unit | secondary |
| Realized-cost efficiency | Realized cost per correct outcome; AUC; BFC | secondary |
| Independent reproducibility | (i) the same engine SHA on the same sealed worlds reproduces every output digest; (ii) a second evaluator's independent scorer agrees on every case; (iii) a second world author's set shows the primary effect in the same direction | required for a positive conclusion |

**Pre-registered statistics.**

- Primary endpoint (one): the paired difference in AUC of correct rate over the cap grid, C − B, on
  primary (non-aliased) cases, with a seeded paired bootstrap 95% interval over cases; clustered by
  world author (cluster bootstrap) when there are several.
- Co-primary safety endpoint: the false-discovery rate difference C − B at the reference cap
  (default 12), non-inferiority margin `δ` (default 0.02), paired bootstrap interval; and the
  held-out force-fit rate difference C − B.
- Secondary family: per cap, the paired correct-rate difference with an exact McNemar test,
  Holm-adjusted across caps and comparisons, with Bonferroni-widened intervals; BFC; realized cost per
  correct; held-out correct and with-record rates; diversity; discriminating share; the same for
  C − A.
- Paired comparisons only: every arm on the same cases, the same caps and common random numbers.
- Fixed sample size, no interim looks, no optional stopping. Guidance: a paired AUC difference of
  0.10 with a per-case standard deviation near 0.4 needs about 130 primary cases for 80% power at
  two-sided 5%; at least 30% of cases are `held_out`.
- Stopping rules: an engine crash, an overspend attempt or a meter mismatch in more than 2% of runs
  stops the run; it is fixed under a new engine SHA, and the world set is burned if any output was
  inspected. A truth leak found by the scorer voids the affected arm.

**What would falsify "Discovery helps"** (for the world distribution written):

- the upper bound of the primary interval is below +0.02 (an improvement too small to matter is
  ruled in or a harm is shown); or
- C's false-discovery rate exceeds B's by more than `δ` (interval excluding zero); or
- C's held-out force-fit rate exceeds B's (interval excluding zero); or
- the effect appears for one world author and reverses for another.

"Discovery helps" is **supported** only if the primary lower bound is above zero, both safety
endpoints hold, and reproducibility (i)-(iii) holds. Anything else is **inconclusive**. A positive
result at caps where C's realized cost is several times B's is reported as exactly that: more
discoveries for more experiments, not efficiency.

## 8. Scoring procedure (V)

1. Verify the run manifest hash, the engine manifest against the engine sources, the scorer source
   hashes and the package root (`parse_engine_package`).
2. Reveal: `reveal(sealed, package, catalog, protocol)`; any mismatch refuses scoring.
3. `score_outputs`: every committed case appears with a status; a missing output fails every
   metric; outputs naming uncommitted cases, another package root, or a hypothesis outside the
   catalog are refused.
4. Compute §7 with the frozen seed and resamples; publish per-case rows and the sealed file.

## 9. Offline tooling available now

| Piece | Where |
|---|---|
| Blind, metered laboratory; truth-leak search | `src/lab_brain/discovery_eval/blind.py` |
| Realized-cost curves, AUC, BFC, McNemar, Holm, invariants | `src/lab_brain/discovery_eval/curves.py` |
| Held-out families (same author), aliasing, force-fit scoring | `src/lab_brain/discovery_eval/held_out.py` |
| Hidden-world format, validation, sealing, blind run, scoring | `src/lab_brain/discovery_eval/hidden_worlds.py` |
| Schema and **example** file (not a hidden set) | `benchmarks/discovery_independent/` |
| One complete run, frozen; `--check` | `scripts/discovery_independent_eval.py` |

Still to build before an independent run: the laboratory as a separate service process; the arm A
harness; the arm B harness on the real PostgreSQL LIB; the open-world rubric; a cluster bootstrap
over world authors; the run-manifest freeze for arm harnesses and model pins.

## 10. What remains unvalidated even after a synthetic independent pass

- **Physical reality.** Forward models are toy tables: linear in one amplitude, Gaussian noise of
  known sigma, no interactions, no drift model beyond a declared slope, magnitudes uncalibrated. A
  world author's tables are still invented, not measured.
- **Real literature.** The catalog is not derived from, or checked against, the literature; no arm
  reads papers; nothing tests whether the mechanisms a real lab should consider are in the catalog.
- **Real models.** Until arm A and the real arm B run with pinned models, nothing is known about how
  a language model, or the real LIB workflow with its model-backed steps, compares.
- **Real experiments.** Costs, availability, failure modes, operator error, sample variation and
  instrument drift are declared numbers, not observed ones.
- **The Causal Warrant Gate.** Discovery hands over a packet; admission, warrants and
  `ConfirmationRule.standing` are never exercised on its output. Nothing here confirms anything.
- **Generalisation.** One scenario (ring drift and loss), one interface, a few world authors.

## 11. Values the Owner fixes before T0 (defaults)

Cap grid `4, 6, 8, 10, 12, 16, 20, 24`; reference cap 12; at least 2 world authors and 130 primary
cases, at least 30% `held_out`; non-inferiority margin `δ = 0.02`; minimal important AUC difference
0.02 (falsification) and 0.10 (power); bootstrap seed and 2000 resamples; arm A model and its
pins; whether arm B runs on the real PostgreSQL LIB (needs the harness and OutcomeSpace decision);
the evaluator, the world authors and the reviewer.
