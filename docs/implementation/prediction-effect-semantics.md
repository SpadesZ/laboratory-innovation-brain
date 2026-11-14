# What a prediction effect means: SUPPORTS, PREDICTS, CONTRADICTS and TESTS, told and held true

Date: 2026-10-13
Scope: the failure the Qwen-vs-Gemini blind comparison recorded (`epi:d4c74098...`). **Not a
milestone.** No Requirement or Test ID was added and no milestone status changed. RelationJudgment
creation (an observation instantiates exactly the effect a prediction declared for the exact outcome
observed), TransitionPolicy, BeliefRevisionEvent, evidence admission and authority, the planner, the
verification loop, BudgetGate, egress, transport, credentials and provenance are unchanged. Nothing
is promoted: PREDICTS stays PREDICTS. The Lumi Agent benchmark was not run.

## 1. The failure, and its causes

The external route (`models/gemini-3.1-pro-preview`) proposed "Discontinuous contact connectivity",
declared `sp.contact_connectivity = DISCONTINUOUS -> PREDICTS` with the designated falsifier
`CONTINUOUS -> CONTRADICTS`, and the local connectivity check really observed DISCONTINUOUS. A
PREDICTS RelationJudgment was recorded, no transition was decided, and the episode stayed
PROVISIONAL. The evaluator's truth for `contact-open-via` is `contact_discontinuity`, stop
CONFIRMED.

**The core did what it is specified to do.** A relation is the declared effect; the SP promotion
policies require `(SUPPORTS,)`; CONFIRMED requires a SUPPORTED rival. Reproduced through PostgreSQL
and the web workspace (`tests/e2e/test_web_prediction_effects_postgres.py`): the same certificate
with SUPPORTS is promoted by an ALLOW decision and the episode is CONFIRMED; with PREDICTS nothing
moves; with falsifiers alone nothing is confirmed. The deterministic catalog, whose
`contact_discontinuity` declares `DISCONTINUOUS -> SUPPORTS`, confirms this case in the M4
benchmark with the same two checks.

**Cause 1 -- the contract named four effects and defined none (fixed).** Prompt 4.0.0 and contract
rc-3.0.0 listed `CONTRADICTS|PREDICTS|SUPPORTS|TESTS` and defined only CONTRADICTS (as the
falsifier). Nothing said that SUPPORTS is the only effect a policy counts as support, that PREDICTS
never is, or when SUPPORTS is warranted. The specification (§17.5.1, §17.8) lists the four without
defining PREDICTS. The model's choice of PREDICTS for every forecast is a reasonable reading of an
under-specified contract. Shadow simulation (section 5) reproduced the same choice in another model
family under the old contract, and not under the new one.

**Cause 2 -- the typed schema admitted an outcome with two meanings (fixed).** A certificate could
declare one outcome of an observable both SUPPORTS and CONTRADICTS, or forecast it and be refuted by
it. Not what happened here, and every recorded certificate is coherent; it is the code-checkable
part of the same semantics.

**Cause 3 -- evidence order was not reproducible (fixed).** Retrieval ranked ties by attestation id,
which is minted fresh at every admission -- in every run, even in one project. The same statements
reached the model in a different order (and, at the `max_items` cut, possibly a different selection)
each time. The recorded Qwen control and the historical Qwen run saw the same eight statements with
two pairs swapped, and produced different hypothesis sets.

**Cause 4 -- the local model's output depends on its prompt cache (diagnosed; not a code defect).**
Replaying the exact recorded Evidence Researcher request (context hash `577404c3...`, verified)
against Ollama: the first, cold request reproduced the historical and control output; every later
identical request -- the prompt prefix now cached -- returned the treatment's different output,
deterministically, also after another model was loaded and after a different long prompt. The two
blind arms therefore started from different evidence queries for a reason upstream of the variable
under test. The OpenAI-compatible transport has no lever on Ollama's prompt cache; this is recorded
as a reproducibility limit of local inference, with the outputs themselves in InferenceProvenance.

Not causes: egress, budget, the planner (it selected and ran the right check), the verification
backend, or the episode view (which reported the PREDICTS relation and the absent transition
correctly).

## 2. The design

**One definition, held true.** `core.models.prediction.PREDICTION_EFFECT_MEANINGS` gives each of
`PREDICTION_EFFECT_TYPES` one meaning, beside the set it describes:

| effect | meaning (abridged) |
|---|---|
| SUPPORTS | evidence FOR this hypothesis: its mechanism produces the outcome and its rivals' would not, so the outcome discriminates it; the only effect a transition policy counts as support |
| PREDICTS | a forecast that would not be evidence for it -- e.g. rivals forecast it too; recorded and compared; never counted as support |
| CONTRADICTS | evidence AGAINST it; the only effect counted as refutation; a falsifier is a designated CONTRADICTS prediction |
| TESTS | bears on it without a declared direction; recorded; never support or refutation |

"Only SUPPORTS is support" is not asserted on trust: core's `TransitionPolicy` would accept any
`required_relation_types`, so `tests/unit/test_prediction_effect_semantics.py` holds every policy
the product constructs to it -- the SP fidelity pair, the promotion pair, the diagnosis targets and
the admission policy -- and reads every `TransitionPolicy(...)` in the source with `ast`, so a policy
added later that required PREDICTS or TESTS fails the build, and with it the contract's words.

**The engine is told** (prompt `prm:hypothesis-engine` 5.0.0, rendered from the mapping): choose
each relation_effect by what observing the outcome would mean for THIS hypothesis; the four meanings;
declare SUPPORTS only for an outcome that would discriminate the hypothesis from its rivals, and
when none would, give it falsifiers only -- "never a SUPPORTS it has not earned"; one outcome has one
meaning. **The contract** (rc-4.0.0) says the same in its terms: SUPPORTS the only support,
CONTRADICTS the only refutation, PREDICTS and TESTS neither, SUPPORTS optional, one effect per
outcome.

**The parser enforces what code can judge.** `parse_hypothesis_engine` refuses a hypothesis that
gives one (observable, space id, version, outcome) two different effects. It does not -- and cannot
-- judge whether a SUPPORTS is warranted, and never requires one: a falsification-only certificate
is admitted. A PREDICTS forecast is admitted as PREDICTS.

**Evidence ties are broken by content.** `EvidenceResearcher.retrieve` orders equal-scoring
statements by `(-overlap, class preference, text, attestation id)`: the text is what every admission
of a statement shares. Relevance still decides first. The BM25 and dense retrievers already broke
ties by global evidence-unit id and are unchanged.

## 3. Versions and qualification

| | before | now |
|---|---|---|
| prompt `prm:hypothesis-engine` | 4.0.0 | **5.0.0** |
| response contract | rc-3.0.0 | **rc-4.0.0** |
| probe version | probe-5.0.0 | **probe-6.0.0** |
| ROLE_HYPOTHESIS suite | hypothesis-conformance@3.0.0 | **hypothesis-conformance@4.0.0** |
| `QUALIFICATION_DIGEST` | `43ce474f374e...` | **`e8b2be879673...`** |

The suite keeps its two synthetic, domain-agnostic cases; a case now also fails a certificate that
gives one outcome two effects, and passes falsifiers alone and a PREDICTS forecast. The digest
change stales every lock automatically: the three the deployment holds (`qwen2.5-coder:7b`
`lk:06d7d886...`, `qwen2.5:7b` `lk:271a4fad...`, `models/gemini-3.1-pro-preview` `lk:665f3759...`)
are recomputed in the tests as no longer current, and as current under the old digest.

## 4. Tests

- `tests/unit/test_prediction_effect_semantics.py`: every effect has one meaning and the prompt
  renders each; the contract's support/refutation/optional/coherence sentences; every registered
  policy reads only SUPPORTS or CONTRADICTS (raising ones SUPPORTS, lowering ones CONTRADICTS), and
  no `TransitionPolicy(...)` in the source requires PREDICTS or TESTS; a PREDICTS forecast stays
  PREDICTS; falsifiers alone are admitted; four incoherent pairs refused; different outcomes with
  different effects admitted; the suite passes falsifiers alone and a PREDICTS forecast and fails an
  incoherent certificate; the deployed locks are stale. In a toy domain, not silicon photonics.
- `tests/unit/test_evidence_tie_order.py`: tied statements in text order whatever ids were minted;
  the `max_items` cut keeps the same statements under every permutation of ids; relevance first.
- `tests/e2e/test_web_prediction_effects_postgres.py`: the recorded failure as a regression, through
  the web workspace and PostgreSQL, on `contact-open-via`, with the stand-in route answering in
  three shapes (`FakeProvider(forecast_effect="PREDICTS")`, default, `falsifiers_only=True`):
  PREDICTS recorded and promoting nothing; SUPPORTS promoted by an ALLOW decision and CONFIRMED;
  falsifiers alone confirming nothing.
- Earlier tests changed only where they pinned the versions above.
- Eight mutation entries: the meanings dropped from the prompt; an effect without a meaning; the
  contract's support rule dropped; one outcome allowed two effects; a PREDICTS forecast admitted as
  SUPPORTS; an observed PREDICTS instantiated as SUPPORTS; a promotion policy requiring PREDICTS;
  ties broken by the minted id again. The two typed-falsifier prompt/contract entries re-anchored
  (the sentence they remove is now followed by the effect rule).
- The debate benchmark report regenerated: every verdict, round count and metric identical (10/10
  kept, 5 wins, 0 losses, the Critic changing 5 final sets); digests and token estimates only (the
  prompt is longer; cost ratio x3.42 -> x2.88). The evidence and root-cause reports are current and
  unchanged.

## 5. Shadow role simulation with isolated Claude subagents

**What it is and is not.** Four isolated Claude Code subagents were each given one Hypothesis
Engine request verbatim -- the system message (response contract) and the user message (prompt and
CONTEXT) -- told to use no tools, and returned one JSON reply. Each reply was judged offline by the
real parser and measured by a script; **nothing was sent to the deployment, recorded as an
inference, admitted, or related to any observation.** This is shadow role simulation, not governed
inference: no route, no lock, no qualification, no BudgetGate, no egress decision, no
InferenceProvenance. Isolation was by instruction (the subagents could technically read the
repository, which holds the benchmark's truth); each subagent's usage record shows one tool use,
and each delivered its reply by hand-back. The replies were preserved from those hand-backs (the
subagents' transcripts were not retained). The subagents are the same model family as the
orchestrating agent. One reply per condition.

**Inputs.** (a) The exact first Hypothesis Engine request of `epi:d4c74098`: its CONTEXT rebuilt from
the stored bundle and the pack's bindings, verified against the stored context hash
(`f55038cc...`, match); rendered by the baseline code (`b6a5845`, from a worktree) and by this
change. (b) A synthetic optical-link loss case written for this experiment, in no repository and
in no benchmark: some outcomes are produced by several plausible mechanisms (a fault located at the
connector: a dirty or a damaged end face), one essentially by one (loss rising toward long
wavelengths: a macrobend). The new-contract inputs are byte-identical to what this change renders.

**Measures** (generic, from the replies alone): an *over-claim* is a SUPPORTS on an outcome another
hypothesis of the same set also affirms; a *candidate under-claim* a PREDICTS no rival affirms; for
the recorded case, the relation each recorded observation would instantiate.

| reply | effects S/P/C | over-claims | AGREES -> | DISCONTINUOUS -> |
|---|---|---|---|---|
| Gemini, recorded (old contract, real) | 0/5/5 | 0 | extraction artefact: CONTRADICTS | contact connectivity: **PREDICTS** |
| Claude shadow, old contract | 1/8/7 | 0 | normalization: CONTRADICTS | contact discontinuity: **PREDICTS** |
| Claude shadow, new contract | 5/6/8 | 0 | normalization: CONTRADICTS | contact connectivity: **SUPPORTS**; process contact: CONTRADICTS |
| Claude shadow, toy, old contract | 3/10/11 | **2** (AT_CONNECTOR, shared) | -- | -- |
| Claude shadow, toy, new contract | 5/11/19 | 0 | -- | -- |

On the toy case the old contract put SUPPORTS on the shared `AT_CONNECTOR` (two rivals) and PREDICTS
on the discriminating `RISES_TOWARD_LONG_WAVELENGTH`; the new one reversed both. Every reply passed
both the baseline and the new parser.

**Can subagents serve the scientific roles?** For shadow experiments over rendered requests, yes,
as above: cheap, fast and comparable, if their outputs stay outside the record. **Not as governed
roles.** A Claude Code subagent has no HTTP endpoint the transport can reach, no model identity a
lock can name, no qualification, no budget or egress gate, and its output would have to be
inserted -- the fabrication this system exists to refuse. A governed Claude route would be an
ordinary connection: Anthropic's OpenAI-compatible endpoint registered in the LLM settings with an
API key (its model fetched or declared), qualified by the same probes, locked, bound and
egress-authorized per project like any other -- an independent model identity with its own lock.
No such key is registered here, so it was not created.

## 6. Verification

Code: `8ca7411`. CI run `38387811612`: commit hygiene, spec conformance, lint/types/full suite and
the PostgreSQL backend profile, all green. `src` changed only in `core/models/prediction.py` (the
meanings), `cognition/roles.py` (prompt 5.0.0, the coherence rule), `llm_runtime/contracts.py`
(rc-4.0.0), `llm_runtime/probes.py` (versions) and `cognition/evidence.py` (the tie-break); no
migration; TransitionPolicy, RelationJudgment creation, BeliefRevisionEvent, admission, the planner,
the loop, BudgetGate, egress and transport are untouched.

| Run | Passed | Skipped |
|---|---|---|
| local, Windows: `pytest -q` | 1776 | 851 backend-gated |
| local, fresh database (61 migrations): `LAB_BRAIN_TEST_POSTGRES=1 pytest -q` | 2625 | 2: 1 Lumerical, 1 network |

ruff, ruff format and strict mypy (238 source files) clean; status, obligation inventory and
requirement coverage current; the evidence and root-cause (`--disposable`) benchmark reports current
and unchanged; the debate benchmark report regenerated as in section 4. Mutation battery, every
entry, on a fresh database and in a separate worktree of `8ca7411`: **448/448 killed**, no anchor missing (the 440 earlier entries, two of them re-anchored, and the eight above).

## 7. Deployed: re-qualification and the governed runs after the change

`docker compose -p lab-brain-workspace up --build -d` from `8ca7411`; `local-models` changed nothing.
The applied runtime was refused at once ("lock ... was made under qualification semantics no longer
in force"), as designed. It was retired, the three models unlocked and given the full default
capability test under `probe-6.0.0` (digest `e8b2be879673...`), and locked with exactly what each
proved:

| model | ROLE_HYPOTHESIS (suite @4.0.0, N=5) | new lock |
|---|---|---|
| `models/gemini-3.1-pro-preview` (connection `a`) | PASSED (104.9 s); ROLE_CRITIQUE still FAILED | `lk:2b48e377a4355cff` |
| `qwen2.5-coder:7b` | **FAILED**, `multi-space`: designated a SUPPORTS prediction as its falsifier (an existing rule; it passed under probe-5.0.0) | `lk:f14109bc296cdf49` (no ROLE_HYPOTHESIS) |
| `qwen2.5:7b` | FAILED, as before (no designated falsifier) | `lk:f80baa75bc60a828` (no ROLE_HYPOTHESIS) |

One qualification attempt each; the failing models were not re-tested until they passed. **No local
model now qualifies for REASONING_PRIMARY**, so the earlier local runtime cannot be rebuilt without
the operator's decision (section 9).

**Governed runs**, runtime `exp-gemini31-effects` (`lrt:e8604a60...`: PRIMARY Gemini
`lk:2b48e377...`, FAST `qwen2.5-coder:7b`, ADVERSARIAL `qwen2.5:7b`, external labels PUBLIC),
project `prj:bench-gemini` (RESEARCH; egress `lep:f245c028...`: connection `a`, PUBLIC only), the same
report (`8b30ebc9...`) and question, one run each, the case's device as verification input (device
fields only). Truth was read only after all three were recorded.

| case (truth) | episode | hypotheses (S/P/C) | executed -> observed -> relation | result |
|---|---|---|---|---|
| `contact-open-via` (contact discontinuity) | `epi:6174b0fe...` | 6, none over `sp.contact_connectivity` (4/1/5 in the first set) | extraction -> AGREES -> CONTRADICTS "missing correction" (ALLOW) | SUSPENDED: no contact hypothesis, so the connectivity check was never a candidate |
| `normalization-taper` (normalization error) | `epi:7b56877f...` | 6 (4/1/5) | extraction -> DISAGREES -> **SUPPORTS "missing correction artefact"** -> ALLOW `policy:sp-vs001-promote` | **CONFIRMED -- the wrong mechanism** (section 8) |
| `mesh-coarse-access` (mesh artefact) | `epi:12265cfd...` | 5 (4/1/5) | extraction -> AGREES -> CONTRADICTS "missing extraction correction" (ALLOW) | SUSPENDED awaiting a simulator; nothing confirmed |

Every relation is the declared effect for the exact outcome observed, every belief move has its ALLOW
decision, and no PREDICTS relation was promoted. The effect labels changed as intended: the first
certificate sets carry 4 SUPPORTS, 1 PREDICTS and 5 CONTRADICTS each (the recorded run: 0, 5 and 5),
with no SUPPORTS on an outcome a rival also affirms.

Run time 1353 s, 1575 s and 510 s; Gemini 4 calls per run (151-747 s in all, slower than on
2026-10-08), the local Critic 284-704 s. BudgetGate ACTUAL 5548, 5861 and 4672 tokens (visible text
only; Gemini's hidden reasoning tokens are not counted). The runtime was retired afterwards: no
runtime is applied, and new research uses the local catalog reasoner, the explicit fallback.

**History is untouched.** Against a snapshot taken before the rebuild (2026-10-13 11:06:30 UTC):
11 episodes, 40 hypotheses, 50 predictions, 4 relations, 43 belief events, 3 decisions,
8 observations, 62 InferenceProvenance rows, 152 probe rows and 12 lock rows created before it,
identical; the only new episodes are the three above.

## 8. For independent review: a model-declared SUPPORTS confirmed a mis-attributed mechanism

`epi:7b56877f...` is preserved as the reproduction. Gemini's "missing correction artefact" (the
contact-resistance correction term absent from the extraction) declared `sp.normalization_basis =
DISAGREES -> SUPPORTS`. The normalization check compares the extraction's normalization length with
the drawn length; a missing contact-resistance term does not change it. The check observed
DISAGREES -- because of the true cause, a normalization length error (taper-inclusive 1000 um
against the drawn 500 um) -- and every governed step then did what it is specified to do: SUPPORTS
from the declared prediction, an EXACT/COMPATIBLE condition match and one independent Run, ALLOW,
SUPPORTED, CONFIRMED. The conclusion names the wrong mechanism.

What failed is the warrant of a model-authored SUPPORTS: nothing in the architecture checks that a
mechanism the model wrote is one the observable it bound to can diagnose. The DomainPack declares
observables and their spaces, not which mechanisms an observable discriminates; the catalog's
curated pairs are correct by construction, a model's are not. Before this change the same model
labelled the forecast PREDICTS and the case would not have been confirmed -- by accident, not by a
check -- and any model that wrote SUPPORTS (the local model did, in `epi:ac49adeb...`) was exposed
to the same path. The new contract makes a model's labels mean what the policies read; it also makes
this gap reachable more often.

Not repaired here: closing it changes scientific semantics (TransitionPolicy or DomainPack) and needs
an approved design. Candidate directions, none implemented: a domain-declared diagnosticity -- which
observable outcomes may support which declared mechanism classes -- that a model's hypothesis must
be mapped to before its SUPPORTS can promote; or a promotion policy for model-authored hypotheses
that requires more than one independent line of support or a person's review. Until then a
CONFIRMED conclusion reached from one model-declared SUPPORTS is not evidence of the mechanism.
READY_FOR_REAL_RESEARCH stays false.

Taken up by the Causal Warrant Gate (2026-10-14, branch `causal-warrant-gate-v1`):
[`causal-warrant-gate-v1.md`](causal-warrant-gate-v1.md).

## 9. Remaining limitations

- Each governed case was run once and each shadow condition sampled once; mechanism coverage varied
  between runs (contact connectivity proposed on 2026-10-08, not in the three runs above).
- Local inference is not reproducible across prompt-cache states (section 1, cause 4).
- The baseline local model no longer qualifies for primary reasoning; whether to re-test it, keep the
  catalog fallback, or use an external route for egress-authorized projects is the operator's
  decision.
- The shadow subagents' isolation was by instruction, and they are not an independent model family
  from the agent that designed the prompt.
