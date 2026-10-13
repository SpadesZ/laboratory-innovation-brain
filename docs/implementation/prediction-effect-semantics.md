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
