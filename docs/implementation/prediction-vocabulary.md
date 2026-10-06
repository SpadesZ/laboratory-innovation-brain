# A prediction's observable is a declared, canonical identifier

Date: 2026-10-07
Scope: the P1 the full LOCAL verification smoke exposed. **Not a milestone.** No Requirement or Test
ID was added and no milestone status changed. The planner, the capability descriptors, the
catalogs, the benchmark, VER-004's space and outcome checks, the research minimum (5), budget, the
inference deadline, egress, credentials, transport locality and the redirect policy are unchanged.
The Lumi Agent benchmark was not run.

## 1. The P1

`VerificationPlanner` matches `Prediction.observable_ref` EXACTLY against `Capability.produces` --
the planner consumes canonical typed identifiers. But the Hypothesis Engine was shown only the
declared OutcomeSpaces, its response contract called `observable_ref` "<what is observed>", and its
parser checked the space pair and the outcome, never the observable. The deployed model wrote
`os:sp.normalization_basis` where `sp.normalization_basis` belongs; the prediction was admitted,
and no verification action could ever match it.

Not solved by fuzzy matching, prefix stripping, aliases, similarity, a model normalising the value
or a planner heuristic, and no space id is turned into an observable by a naming convention.

## 2. The prediction vocabulary

**A DomainPack declares it, beside its spaces.** `DisagreementMetricRegistry` -- where a pack already
declares its OutcomeSpaces and the metrics bound to them (§24.3's `register_disagreement_metrics`) --
gains `declare_observable(observable_ref, outcome_space_id, version)`:

- the space must be declared first; one observable is read in exactly one space (a second binding
  is refused); several observables may share a space; an observable must be a canonical identifier;
- `observable_bindings(domain)` returns the domain's vocabulary, observable → declared space.

That is the whole representation: a binding from a canonical observable to a declared, versioned
space. It does not come from the backends installed here, so a prediction over an observable only
a simulation could check stays a valid prediction target.

- **Silicon photonics** declares the map it already kept (`vertical.prediction_bindings()`, the same
  map `space_for` reads): `sp.contact_connectivity`, `sp.normalization_basis`, `sp.mesh_stability`,
  `sp.carrier_profile`, `sp.probe_contact_resistance` → their `os:sp.*@1.0.0` spaces, and
  `sp.small_signal_impedance` → `os:sp.rs_bias_response@1.0.0`. Every catalog and fixture already
  predicted with exactly these pairs.
- **The toy test pack** declares `toy.widget_stiffness` → `os:toy.widget_verdict@1.0.0` through the
  same call; generic cognition and the LLM runtime name no domain's observable.

**The engine is shown it.** The debate reads the domain's bindings (and refuses to start a
Hypothesis Engine call for a domain that declares none) and renders them as
`CONTEXT.prediction_bindings` (`roles.binding_context`): per binding, `observable_ref`,
`outcome_space_id`, `outcome_space_version`, `outcomes`, `action_type`. The old `outcome_spaces`
list is gone, so there is no bare space list to copy an observable from.

**The parser enforces it.** `parse_hypothesis_engine(text, *, bindings, minimum)` admits a prediction
only when (observable_ref, outcome_space_id, outcome_space_version) is a declared binding and the
expected outcome is one that space admits. It refuses, each with its reason (VER-004):

| Refused | Example |
|---|---|
| a space the engine was not shown (unchanged) | `os:sp.contact_connectivity@2.0.0` |
| an observable not in the vocabulary -- including a space id written as the observable | `os:sp.normalization_basis`, `sp.cj_per_mm` |
| a declared observable with another binding's space, or a legal space with another observable | `sp.contact_connectivity` in `os:sp.normalization_basis@1.0.0` |
| an outcome the bound space does not admit (unchanged) | `ELEVATED` for connectivity |

No hypothesis has to use every observable or every space. An accepted prediction reaches the typed
`Prediction` unchanged, and the planner finds the capability that produces it by the same string.

## 3. Versions and qualification

- `prm:hypothesis-engine` **3.0.0** (context `prediction_bindings`; "copy that entry's
  observable_ref, outcome_space_id and outcome_space_version exactly, together … An
  outcome_space_id is not an observable_ref. Never invent or infer an observable or an outcome
  space from the evidence …").
- Response contract **rc-2.0.0** (each prediction's three identifiers copied together from one
  entry of `CONTEXT.prediction_bindings`; never make up or derive an observable or a space).
- `probe-4.0.0`, suite **`hypothesis-conformance@2.0.0`**: the same two cases, each over declared
  bindings whose observable ids are neither their spaces' ids nor derivable from them
  (`bench.resistor_reading` → `os:probe.level`; `bench.channel_offset`, `bench.warmup_drift`,
  `fixture.edge_gradient`, `bench.repeat_spread` → the four multi-space spaces). A model that copies
  `os:…` into `observable_ref` fails the case. No "observable capability" score.
- `QUALIFICATION_DIGEST` moved from `9a34d824…` to **`5f82fb7a…`**; through the HARD-LOCKED
  semantics mechanism every existing lock is stale, its probe evidence cannot be locked again, and
  each model must be tested under the new contract.

## 4. Tests

| # | Proven | Where |
|---|---|---|
| 1 | the engine receives the domain's canonical bindings (and no bare space list) | `tests/unit/test_prediction_vocabulary.py` |
| 2 | a space id used as the observable (the smoke's exact failure) is refused | same; the qualification suite refuses it case by case; `tests/integration/test_prediction_vocabulary_postgres.py` (a stand-in that does it fails ROLE_HYPOTHESIS and cannot serve primary reasoning) |
| 3 | a valid observable with another space's id or version is refused | unit |
| 4 | an invented observable is refused | unit |
| 5 | a correct pair with an invalid outcome is refused | unit |
| 6 | valid bindings pass unchanged into Prediction | unit (parser and a real debate) |
| 7 | the planner matches an accepted prediction to `Capability.produces` with no normalisation; through the web with a model route, the contact-connectivity check REALLY runs (Job, Run, artifact), its Observation is admitted as evidence from that Run, RelationJudgments follow, and every belief move has its ALLOW decision | unit; `tests/e2e/test_web_prediction_vocabulary_postgres.py` |
| 8 | an observable only a simulation reads stays a valid prediction target | unit |
| 9 | the toy pack supplies its own vocabulary; generic cognition names no silicon-photonics observable | unit |
| 10 | a route qualified under the outcome-space-only contract is stale (readiness, `load_active_runtime`), its evidence cannot be locked again, and a re-test gives a new route; the deployed coder route `lk:963d70828be54b8e`, recomputed, is current only under the previous digest | integration; unit |
| 11 | earlier lock and probe rows byte-for-byte | integration |
| 12 | budget, deadline, transport, credentials, locality, redirect and egress | the whole suite |

The earlier slices' tests that built answers with free-text observables or read `outcome_spaces`
were updated to the vocabulary; their intent is unchanged.

Mutation battery: seven new entries (the parser's observable gate and its pairing check, the
engine's context, a prediction's observable on the way to the planner, the pack's declaration, the
registry's declared-space rule, the suite's observable ids) and five re-anchored (the multi-space
case at the floor and with one binding, the parser's space check, the prompt's and the contract's
binding rule).
