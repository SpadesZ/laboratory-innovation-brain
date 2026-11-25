# Discovery Loop: independent hidden-world evaluation protocol

**Status: protocol draft v0.2 for Owner approval, plus a FROZEN evaluation kit (§12-§15, round 6).
No independent evaluation has been run.** Every result produced so far is engineering evidence on
synthetic worlds written by the engine's own author lineage, or (the kit's dry run) on the PUBLIC
example file. `READY_FOR_REAL_RESEARCH` stays false; G0 stays NOT PASSED. Discovery stays isolated
and offline: no migration, no connection to the research flow, no production scientific
confirmation, no model, network, simulator or paid call.

**Round 6 changes.** §5's "every arm at every cap" design is superseded for the sealed set by
checkpoint accounting from ONE run per case and arm (SAI 3.5 Appendix J §3.3; §12.2). The kit,
its manifest, its pre-registered analysis plan, the evaluator runbook and a disclosed limitation of
the sealed set's key handling are in §12-§15.

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

> **Superseded for the sealed round-5 set by §12.2.** The design below (every arm at every cap,
> one run per cap) gives a budget-aware arm a fresh run, with knowledge of the cap, at every cap,
> and leads to the mean-cost / per-world matching problems of safety v1.3 and v1.4. The kit runs
> every arm ONCE per case at the cap and derives the answer at every checkpoint from that one
> trace. The text below is kept as the history of the protocol.

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
| **The frozen kit** (round 6): run traces, the evaluator's laboratory service, the pre-registered plan and its statistics | `src/lab_brain/discovery_eval/independent/` |
| The kit's scorer: candidate.5 at every checkpoint, from the evaluator's evidence | `src/lab_brain/discovery_safety/independent/checkpoint.py` |
| The kit's composition root: `verify`, `run`, `score`, `sign`, `dry-run`, `power`, `pin-arm`, `freeze` | `scripts/discovery_independent_kit.py` |
| The arm process (one fresh interpreter per case and arm), the arm registry, the manifest, the dry run | `benchmarks/discovery_independent/kit/` |

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

---

## 12. The frozen evaluation kit (round 6)

The kit lets a third-party evaluator (V), who alone holds the decryption key, run the 58 sealed
round-5 cases on V's own machine without the implementation side seeing any hidden truth at any
point. The implementation side prepared it, froze it and ran it on the PUBLIC example only.

### 12.1 What is pinned (`benchmarks/discovery_independent/kit/kit-manifest.json`)

| Pin | What |
|---|---|
| kit code | SHA-256 of every kit file (`discovery_eval/independent/*`, `discovery_safety/independent/*`, the composition root, the arm worker, the arm registry, the public commitments copy) and their canonical hash (`kit_code_hash`) |
| engine | SHA-256 of every `src/lab_brain/discovery/*.py` and the catalog module (`engine_hash`) |
| evaluator closure | SHA-256 of every `lab_brain` file the evaluator's process imports, measured in a fresh interpreter: the scorer (v1.2-v1.4 evaluator code), the hidden-world format, the catalog, the grammar |
| arms | per slot: the commit, the commit's `src` tree id, the entry point, the context (catalog, oracle, protocol, grammar), and the SHA-256 of every file of the arm process's import closure. B4 (the v1.1 baseline), B6 and B7 are pinned at the v1.4 design freeze `bff315f`; **B8 is an EMPTY slot** |
| scoring | SAI 3.5 candidate.5 categories judged by the frozen v1.4 evaluator rule (its digest), the grammar digest, the catalog ref and digest, the protocol digest |
| analysis plan | `lab_brain.discovery_eval.independent.plan.PLAN` in full and its digest (§12.4) |
| sealed set | archive SHA-256 `b23db527e50cf58f5e0a7d5a550b612fd8b0f4a274eaf6dbb5fa89693ca2fe83`, commitments root `sha256:839ac0110308102f990c1d2e9e5e246600c310f7adb71b59eeaf9c28db2dcf8b`, 58 cases, the commitments file's SHA-256, its source commit `3d54297` |
| dry run | SHA-256 of every committed dry-run output, and of the power analysis |
| environment | interpreter (CPython 3.13) and dependency versions |

The **freeze id** is the canonical hash of the manifest; `verify` prints it. **`verify`**
recomputes every pin: kit, engine and evaluator-closure files; the plan, rule, grammar and catalog
digests; each pinned arm's tree (materialized with `git archive` from its commit, refused if the
tree id differs or if it holds a link) and closure hashes; the commitments root; the ciphertext's
SHA-256 (from `--archive`, or streamed from the pinned git object, never decrypted); the dry-run
outputs; the interpreter. `run` and `score` call it first and **refuse on any mismatch**.

**Adding B8 without changing kit code.** `pin-arm --arm-id B8 --commit SHA --entry MODULE:FUNC`
fills the slot (commit, tree id, closure hashes) in `arm-registry.json`; then `freeze` writes a new
manifest. The entry point is called as `entry(arm_name, catalog=, oracle=, budget=, lab=, grammar=)`
and returns the v1.3 `ArmAnswer` schema (or a dict of it); it may call `lab.declare(answer)` to
commit anytime answers. A new freeze must be committed and pushed BEFORE any sealed run; the plan
then makes B8 - B4 the primary comparison (§12.4).

### 12.2 One run per case and arm; checkpoints from its trace

Every pinned arm runs every case **once**, at the plan's cap (48 units), in a fresh interpreter
(`arm_worker.py`) that loads only the arm's pinned tree. The evaluator's process holds the world,
the meter and an append-only, hash-chained **trace** (`trace.py`): START, MOTIVATING, MEASURE
(experiment, replicate, session, frozen cost, charge before and after, the values), REGISTER
(identity, experiment, runs), DECLARE (an answer, stamped by the evaluator with the charge and the
number of evidence events at that moment), REFUSED, INCIDENT, END (status and the meter's charge).

- **The answer at checkpoint c** is the answer of the last DECLARE whose charge is <= c; if there is
  none, the arm holds no claim at c. The charge of a declaration is the frozen cost of every
  experiment started before it. Experiment costs here are fixed, so the reservation of an
  experiment equals its settlement and no experiment straddles a declaration (Appendix J §3.3.2-4:
  an experiment whose reservation does not fit under the cap never starts).
- **SUPPORTED at checkpoint c** is recomputed by the evaluator from the trace's MOTIVATING, MEASURE
  and REGISTER events **before** that declaration only, replayed into a fresh v1.3 evaluator ledger
  (chain values, data digests and run counts recomputed, never read from the trace), and judged by
  the frozen v1.4 rule (evaluator-computed predictions; rivals closed only by a failed prediction;
  grammar rivals). A later result cannot reach an earlier checkpoint.
- **Early stopping** (S2-CE-1): an arm that stops at charge s holds its final answer at every
  checkpoint >= s; an arm's rows are a function of its own trace only.
- **Anytime answers.** The legacy arms (B4, B6, B7) commit only a final answer, so below their
  realized cost they hold no claim. That is the intended estimand: what the arm knows after
  spending c when it was given the full cap, not what it would do if told the cap were c.

**Trace-derived answer vs a fresh capped run.** For an arm whose choices do not depend on its cap
and that declares after every experiment, the answer at c from the one trace IS the answer of a
fresh run capped at c, with the same evidence (proved by test on the example worlds:
`test_for_a_cap_independent_deterministic_arm_the_trace_answer_equals_a_fresh_capped_run`). The
legacy arms are not of that kind: they plan with their cap (`engine_fraction * budget`,
`affordable()`), so a fresh capped run explores differently, and below their realized cost they
hold no answer in the trace. The dry run measures this cell by cell on the example
(`dry-run/equivalence.json`). Fresh capped runs are made ONLY on public data; the sealed run never
makes them.

**Why this is primary, and per-world matching (v1.4) is not.** v1.4 ran every arm at every cap and
matched worlds post hoc at the lower of two realized costs within ±1 unit, dropping unmatched
worlds. That conditions on realized cost (a post-treatment variable), selects the matched subset,
gives every arm a fresh, cap-aware run per cap, and makes one arm's comparison point depend on the
other arm's trace. Checkpoint accounting keeps every case in the denominator, fixes the comparison
points before any run (the frozen ladder), and makes each arm's score a function of its own single
trace (Appendix J §3.3; S35-ISSUE-22 option B). Per-world matching remains a description of the v1.4
engineering evidence; the kit does not compute it.

### 12.3 Evaluator-controlled evidence and adversarial arms

The arm reaches the world only through `measure`, `motivating`, `register` and `declare` messages.
Everything that decides SUPPORTED -- the observations, the registrations' data digests, every
prediction, every rival and its closure -- is computed by the evaluator from its own trace. The
arm's stated level is recorded and ignored. A run is **COMPLETED** only when the arm answered within
the rules; otherwise it is **CRASHED** (raised, died, went silent past the wall-clock limit),
**INVALID** (an unknown operation or key, a malformed value, an outcome outside the vocabulary, a
dated declaration, a session going back, an answer whose `spent` differs from the meter, an
experiment beyond the cap, a guard violation), or **TRUNCATED** (message flood). A trace that fails
verification at scoring is **TAMPERED**; a truth string (world id, effect id, salt) in an arm's
output is a **LEAK**. All of these are DEFICIENT: never credited, counted as an error, and scored
against the arm in every paired comparison (Appendix J §3.4).

The arm process guard (an audit hook installed before any arm code; it cannot be removed from
Python) refuses reads outside the arm tree and the interpreter, all writes, process creation,
sockets, ctypes and directory changes, and ends the run INVALID. **It is defence in depth for Python
arms, not a sandbox**: the boundary that matters is the operating system's (§13 step 4).

### 12.4 The pre-registered analysis plan (frozen before any result)

| Item | Value |
|---|---|
| cap (one run) | 48 cost units |
| checkpoint ladder | 6, 8, 12, 16, 24, 32, 48; any other checkpoint is refused by the code (S2-CE-5) |
| primary checkpoint c* | 48 (= the cap; Appendix J's proposal) |
| primary metric | EXACT_IDENTIFICATION (candidate.5, SUPPORTED on the evaluator's evidence) over cases whose truth the catalog expresses (declared, composition, null) |
| primary comparison | B8 - B4 if B8 is pinned at freeze time, else **B7 - B4** (one endpoint, no multiplicity) |
| safety co-primary | candidate.5 ERROR indicator (FORCE_FIT, WRONG_CLAIM, UNSUPPORTED_CLAIM, or deficient) over all non-aliased cases at c*; non-inferiority margin 0.02 on the upper bound |
| interval | paired percentile bootstrap over cases, 10,000 resamples, SHA-256 counter-mode indices, seed 20261124, 95 % |
| deficient records | scored against their own arm; study INVALID if > 2 % of runs are incidents (INVALID/TAMPERED/TRUNCATED) or > 5 % of cases have a deficient run in a compared arm |
| decision | BETTER iff primary lower bound > 0 and safety upper bound <= 0.02; WORSE iff primary upper bound < 0 or safety lower bound > 0; SAFETY_FAIL iff primary lower bound > 0 and safety upper bound > 0.02; else INCONCLUSIVE |
| secondary (labelled, never primary) | every filled comparison of (B8-B4, B7-B4, B6-B4, B8-B7, B7-B6) at every checkpoint for exact, credited, error and face-value correct; exact McNemar with Holm across comparisons per (metric, checkpoint); anytime curves; area under the credited curve; per-category counts; realized-cost distributions |

### 12.5 Statistical power with 58 cases (`kit/power-analysis.json`)

For a binary per-case indicator, the minimum detectable paired difference at 80 % power and
two-sided 5 % is about `k * sqrt(D / (n + k^2))`, k = 2.80, D the share of discordant cases
(checked by simulating the plan's bootstrap: 0.76-0.81 power at the computed difference).

| primary cases n | D = 0.2 | D = 0.3 | D = 0.4 | D = 0.5 |
|---|---|---|---|---|
| 20 | 0.24 | 0.29 | 0.34 | 0.38 |
| 29 | 0.21 | 0.25 | 0.29 | 0.33 |
| 40 | 0.18 | 0.22 | 0.26 | 0.29 |
| 58 | 0.15 | 0.19 | 0.22 | 0.24 |

The number of primary (expressible) cases is not public before the reveal; it is at most 58.

**What 58 cases can support:** a large difference in exact identification (roughly 0.2-0.35
depending on n and discordance), in particular where one arm is near zero under candidate.5 (B4's
unregistered endorsements are UNSUPPORTED_CLAIM by construction); a gross safety failure.
**What they cannot support:** differences of 10 points or less (Appendix J's proposed minimum
effect of interest needs roughly 130+ primary cases); non-inferiority at 0.02 unless the candidate
makes no error the baseline does not (one net extra error out of 58 gives an upper bound of 0.052);
a rate bound tighter than about 6 % from zero events (Wilson upper bound for 0/58); any per-category
claim (a category may hold a handful of cases); any statement about another world author's
distribution, physical reality, a language model or the PostgreSQL LIB workflow.

## 13. Evaluator runbook

Prerequisites: a machine the implementation side has no access to; git with the repository
(including the hidden-cases branch); CPython 3.13 with the repository's pinned dependencies
(`pip install -e .`); `openssl`.

1. **Check out the freeze** and verify the kit with no secret material present:
   `git checkout <freeze commit>`;
   `python scripts/discovery_independent_kit.py verify --archive round5-hidden-worlds.tar.gz.enc`.
   It must print `verify: OK` and the freeze id published in the kit report. Any MISMATCH: stop.
2. **Reproduce the public dry run** in your environment:
   `python scripts/discovery_independent_kit.py dry-run --check` (every file byte-identical) and
   `power --check`. A difference means your environment differs; stop and report it.
3. **Decrypt on your machine only**, outside the repository, into a directory readable by you
   alone (mode 0700):
   `openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass file:KEYFILE -in
   round5-hidden-worlds.tar.gz.enc | tar xzf - -C /secure/round5`. Confirm the engine package's root
   equals the pinned commitments root (`run` refuses otherwise).
4. **Isolate the arms.** Run the kit as an account that can read the sealed directory, and make
   sure arm processes cannot read it: run the kit in a container in which only the evaluator's
   process can read the sealed directory, or use a separate unprivileged account for arm processes
   with no read access to it, and no network egress for either. The in-process guard (§12.3) is
   defence in depth only.
5. **Run once:** `python scripts/discovery_independent_kit.py run --package
   /secure/round5/<engine package>.json --sealed /secure/round5/<sealed file>.json --out
   /secure/results`. `run` verifies the kit, checks the package against the pinned commitments and
   every sealed world against its commitment before any arm runs, runs every pinned arm once per
   case, and writes traces and `run-summary.json`. It prints no truth. **Publish the SHA-256 of
   `run-summary.json`** (T5 output digest) before scoring. A run is made once; `run` refuses an
   output directory that already holds one. A crash of the kit itself may be repeated once from the
   same freeze; anything else burns the set (§2).
6. **Reveal and score:** `score` (same arguments). It re-verifies, reveals, scores every trace at
   every checkpoint (a trace that does not match the head recorded in the run summary is TAMPERED),
   applies the frozen plan, and writes `rows.json`, `results.json` and `results-digest.json`.
7. **Sign and publish:** `keygen --key K` once (publish the public key), then `sign --key K --out
   /secure/results`; publish the results directory (traces, rows, results, digest, signature) and,
   after scoring, the sealed file. Anyone can check with `verify-signature --out DIR
   --public-key KEY`.

**Who must NOT hold the key:** the engine author lineage (every session that wrote or edited the
engine, its catalog, the arms or this kit), the arm operators, and anyone who will report or act
on per-case outputs before the run is closed. The key reaches V from the Owner directly, never
through an implementation session.

**V attests**, in a signed statement published with the results: the kit freeze id verified; the
archive SHA-256 and commitments root verified; the dry run reproduced; decryption only on V's
machine; arm processes could not read the sealed material; one run, no re-runs (or the single
permitted kit-crash re-run, disclosed); no look at per-case outputs before `run` completed; no
change to the kit, engine, arms, plan or scorer after the freeze; every deviation disclosed; V's
conflicts of interest (§1).

## 14. Disclosed evaluation limitation: the round-5 decryption key

**On 2026-11-24 the decryption key of the round-5 archive was displayed in the lead implementation
session's transcript, at the Owner's request.** This is recorded as an **evaluation limitation**,
not as a confirmed exposure of hidden answers: nobody decrypted the archive, and no hidden case
content was read by the implementation side. But the barrier is weaker than designed: someone with
access to that transcript could have decrypted the cases. The plaintext working copies in the
implementation container are being deleted by the lead; the encrypted archive on GitHub
(`b23db527e50cf58f5e0a7d5a550b612fd8b0f4a274eaf6dbb5fa89693ca2fe83`) is the only copy of the cases,
and the key is held by the Owner.

Recommendations to V and the Owner:

- Treat it as a **disclosed limitation** in every report of the round-5 results, next to the
  procedural (not institutional) independence of the single AI world author.
- The kit was frozen after the disclosure, but its arms are pinned at `bff315f` (2026-11-21), before
  the key existed outside the author's session, and no arm, plan or scoring choice was changed after
  it; this narrows, but does not remove, the risk.
- **Stronger option: regenerate a fresh sealed set.** An independent author who is not of the
  implementation lineage writes new worlds against the frozen interface (§3, §4), seals them with
  fresh salts, encrypts with a key generated on the author's or V's machine and never shown in any
  implementation session (the key travels from author to V directly, or V generates the key pair
  and the author encrypts to V's public key, e.g. `age -r` or `openssl pkeyutl`), and publishes only
  the commitments root and the archive SHA-256. The kit runs unchanged on the new set after a new
  freeze that changes only the pinned sealed-set hashes (`SEALED_SET` and the commitments copy):
  arms, plan and scorer stay pinned. If both sets are run, the fresh set is primary and the round-5
  set is secondary, labelled with this limitation.

## 15. What the kit does not change

The kit evaluates the offline arms B4, B6, B7 (and B8 when pinned) on synthetic hidden worlds of one
AI world author. It is not the G-D comparison of SAI 3.5 Appendix J (arms A and B do not exist
offline), says nothing about physical reality, real literature, language models or the PostgreSQL
LIB workflow (§10), and confirms nothing.
