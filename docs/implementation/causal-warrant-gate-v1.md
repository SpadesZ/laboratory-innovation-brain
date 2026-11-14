# Scientific Causal Warrant Gate V1

Status: **implemented on branch `causal-warrant-gate-v1`, not merged, not deployed.** Baseline
`41b3cec`. `READY_FOR_REAL_RESEARCH` stays false: this gate is necessary for it, not sufficient
(§11). The deployed database was read, never written. The audit package (Traditional Chinese
report, read-only evidence, test and mutation records) is in `docs/audit/causal-warrant-gate-v1/`.

"The recorded run" is `epi:7b56877f…` (2026-10-13, `prj:bench-gemini`, case
`normalization-taper`).

---

## 1. Root cause

### 1.1 What was recorded

| link | record | content |
|---|---|---|
| hypothesis set | 6 hypotheses, none a length normalization error | the true mechanism was never a rival |
| hypothesis | `hyp:7c899579…`, mechanism "missing correction artefact" | from a second engine call (`inf:cac51f0d…`) certifying an alternative the critic (`inf:b72a20f2…`) named |
| predictions | `sp.normalization_basis = DISAGREES -> SUPPORTS` (`prd:1165a3f6…`); `= AGREES -> CONTRADICTS` (designated falsifier) | both on an observable a missing contact-resistance term cannot change |
| check | `cap:sp.extraction_consistency`, `run:28f7d82c…` | compares the extraction's normalization length with the drawn length, nothing else |
| observation | DISAGREES, `att:e6831355…` (DESIGN_INSPECTION) | caused by the true mechanism (taper-inclusive 1000 µm against the drawn 500 µm) |
| relation | `rel:51f1fdc4…` SUPPORTS | the prediction's declared effect, copied; actor = the researcher, no link to the model |
| decision | `policy:sp-vs001-promote@1.0.0` ALLOW (`dec:7d6d7411…`) | one SUPPORTS, authority DESIGN_INSPECTION, condition EXACT, one Run |
| conclusion | `fan:30d9407f…` CONFIRMED, failure_class "missing correction artefact" | the model's mechanism string; 5 of 6 rivals never tested |

### 1.2 The mechanism

Every component did what it is specified to do. The defect is a missing distinction.

1. **Matching is exact and correct.** `comparable()` matched the typed prediction to the observed
   outcome.
2. **The relation's type is the author's claim.** `verification/evidence.py` copied
   `relation_type=effect.relation_type`. For a model-authored prediction, that is the model's
   assertion that the outcome *discriminates its mechanism*. That requirement existed only as
   prompt text, and the model is shown observable names, not what they measure.
3. **EPI-002 guards the wrong layer for this failure.** `core/root_cause.py` refuses a model
   statement as evidence at the *attestation* layer. Here the attestation was a genuine Run output,
   and the model's statement re-entered one layer up, as the relation type.
4. **The policy checks presence, not warrant.** Step 4 of `TransitionPolicy._decide` asked only
   whether a SUPPORTS was present. Steps 5–7 concern the observation, not the link from the
   observation to the mechanism.
5. **The loop equated SUPPORTED with CONFIRMED.** It stopped at the first SUPPORTED member in
   hypothesis-id order and recorded the model's text as the failure class.

**Root cause.** A model-authored SUPPORTS effect was admitted as the relation that authorises
promotion and confirmation. So the author's unverified claim of diagnostic relevance and
discrimination was treated as evidence — the class of claim EPI-002 forbids one layer down.

**Contributing conditions:**
- the true mechanism was absent from the set (closed world);
- the falsifier was on the same proxy observable;
- the decisive fact (1000 µm against 500 µm) existed only in the device project, while the report
  pointed at contact resistance;
- the alternative-certification call saw only mechanism names.

### 1.3 The same defect elsewhere in the record (independently verified)

| finding | evidence |
|---|---|
| **Unwarranted refutation, recorded three times.** Every CONTRADICTED event in `prj:bench-gemini` is a Gemini-authored `sp.normalization_basis = AGREES -> CONTRADICTS` against a contact-resistance-correction mechanism: `epi:d4c74098` "Uncorrected extraction artefact", `epi:6174b0fe` "missing_correction", `epi:12265cfd` "missing_extraction_correction". They were right only by luck, and rejection is final for the episode. | `evidence/supports_history.out.txt` |
| **The converse failure.** In `epi:d4c74098` the true cause declared DISCONTINUOUS as PREDICTS, was observed, and was never confirmed. The effect label set the evidential weight in both directions. | mission 3 record |
| **Shared support.** Two rivals declaring SUPPORTS on one outcome were both promoted, and the loop confirmed whichever id sorted first. In production ids are UUIDs, so the choice is arbitrary. Reproduced without a model. A latent instance exists in `prj:smoke-local`. | tests, verifier report |
| **Relation provenance laundered.** Relations carried the researcher's actor id and no inference id, so the model's authorship survived only through `attributes.prediction_id`. | `rel:51f1fdc4` |

### 1.4 Contamination of later research

**Facts (read-only):**
- `fan:30d9407f…` is the only CONFIRMED analysis in the deployment.
- There are 0 heuristic candidates, 0 review items and 0 review resolutions.
- Two plans of `epi:12265cfd…` record `precedents: ["fan:30d9407f…"]`. They match only because
  the loop's symptom defaults to the goal and the three bench runs share a question.
- Precedents are decision-inert, unrendered and never in a model context.
- The later episode's evidence bundles drew only on the original input report.

**Latent:** the miner (`MIN_SUPPORT = 2`, keyed on free-text class and symptom) would have turned
one recurrence into a PENDING_REVIEW heuristic.

---

## 2. Scientific semantics

| level | question | who may answer | where |
|---|---|---|---|
| prediction matching | did the observed typed outcome equal the predicted one? | the system | RelationJudgment creation, unchanged |
| diagnostic relevance and discrimination | does this outcome bear on this mechanism as declared — produced by it and not its rivals (SUPPORTS), impossible under it (CONTRADICTS)? | a DomainPack declaration or an accountable person, **never the author** | the diagnostic warrant |
| warranted support / refutation | does the policy count it? | the pure policy, over warranted relations only | `TransitionPolicy` |
| confirmation | is this the cause, relative to the rivals considered? | the loop, from unique, discriminating, warranted support | `VerificationLoop.standing` |

**Invariants:**
- **I1 Matching is not support.** Relations are created exactly as before, and now name their
  author's inference.
- **I2 Warrant.** Under a gated policy, each required SUPPORTS or CONTRADICTS counts only with a
  warrant:
  - DOMAIN: a registered declaration set binds the hypothesis to a class (exact mechanism *and* the
    whole declaration: signature as SUPPORTS, every refuting outcome as CONTRADICTS, nothing that
    disagrees), and the observed outcome is that class's signature or refutation;
  - REVIEW: a person's WARRANTED grant for exactly that relation and its prediction. A person's
    refusal outranks a declaration.

  A grant may also carry a person's explicit statement that the hypothesis *is* a declared class.
  It is honoured only where the warranted outcome is that class's signature, and it is the only
  way an unbound paraphrase joins a class.
- **I3 Authorship.** Warrant resolution never reads authorship.
- **I4 Unknown is not a verdict.** An unknown warrant is never a rejection and never a belief move.
  A person is asked only where a warrant would change the verdict.
- **I5 Exclusive signatures.** Within a declaration set, a signature is exclusive.
- **I6 Confirmation.** CONFIRMED requires:
  - exactly one SUPPORTED class, by warranted support;
  - no warranted refutation anywhere in the candidate's class (a bound copy is the same class,
    never a rival);
  - no rival affirming (SUPPORTS or PREDICTS) the observation the support rests on, unless that
    rival is *excluded* — rejected through the governed policy on a warranted refutation. A coarse
    challenge does not exclude.
  - no unsettled relation that could overturn the conclusion: support for a rival not excluded, or
    a refutation of the candidate's class. This is read from the records whether or not a review
    could be queued.
  - no outcome observed anywhere in the episode, predicted or not, that is the signature of
    another declared class. Only the candidate's own class (bound or identified) accounts for its
    signature; approving a link does not.
  - no outcome observed anywhere in the episode that the candidate's own class cannot produce (a
    declared refuting outcome on its observable). It is read off the observations, because a
    member identified by a person never had to predict it.
  - Affirmations count even if their relation was later invalidated.
- **I7 Independence.** Evidence lines (capability, backend, inputs, parameters), not Runs, are
  independent.
- **I8 Named warrants.** A confirmation names its warrants, and the database refuses refs that are
  neither declaration refs nor WARRANTED grants on the cause.
- **I9 Quarantine.** Conclusions without warrants feed neither the miner nor case memory.
- **I10 Re-checked on read.** Every recorded per-relation fact and warrant is re-checked against
  its source on the read path:
  - the *stored* relation;
  - the attestation's own record of the outcome;
  - the cited declaration-set version;
  - the grant.
- **I11 No self-certification.** No model output, no direct table write, no episode actor and no
  hypothesis author can create a grant. No relation can borrow another observable's, another
  observation's or another episode's attestation.
- **I12 Everything else is unchanged:**
  - PREDICTS and TESTS never count;
  - qualification, prompts, contracts, probes, `QUALIFICATION_DIGEST`, BudgetGate, egress and
    security are untouched;
  - every stored decision re-derives byte-exact.

**CONFIRMED now means:** exactly one class in the considered set has support whose diagnostic link
an accountable source warranted, traced to a Run and an Artefact. Its class has no warranted
refutation. Every rival that predicts the same observation was rejected on warranted evidence. No
unsettled question could overturn it, no other declared mechanism's signature was observed, and no
outcome its own class cannot produce was observed. A member of a declared class is recorded as that
class. It is relative to the rivals proposed and the domain's declarations; rivals never tested are
named in the conclusion (§9).

---

## 3. Design: options, selection, and four rounds of independent review

| design | verdict |
|---|---|
| domain-declared applicability only | necessary, not sufficient: novel mechanisms would be stranded |
| typed causal warrant written by the model | rejected as authority: self-certification |
| independent verification alone (≥2 lines) | insufficient: two proxy checks both "match", and every single-check catalog case would be blocked |
| human review keyed on authorship | spoofable (authorship is a provider label), and costs a review per model run |
| **content-keyed warrant (DOMAIN or REVIEW) + discrimination rule + quarantine** | **selected** |

The design changed four times under independent review (§10):
- the draft was reviewed;
- the first implementation (`bc55458`) was reviewed;
- the fixes (`7e3cc43`) were reviewed;
- the second fixes (`ed0670b`) were given a final pass, whose small items `134c07b` closes.

Each round found real defects. The rules in §2 are the result.

---

## 4. Implementation: integration points

### Core
- `core/models/transition.py`:
  - `RelationEvidence` per gated relation, carried in `HypothesisView.relation_evidence`;
  - `TransitionPolicy.diagnostic_warrant_required`;
  - reasons `DIAGNOSTIC_WARRANT_MISSING` and `DIAGNOSTIC_WARRANT_REFUSED`;
  - step 4b `_decide_warranted`, one evaluation per gated required type: steps 5–7 run over
    warranted relations' own facts, and a person is asked only if warranting would pass.
- The §8.2.1 arity is unchanged; `core/models/decision.py` omits an empty `relation_evidence` from
  the canonical form, so stored hashes are unchanged.

### Declarations
- `core/models/warrant.py`:
  - `DiagnosticDeclaration` and `DiagnosticDeclarationSet`: exclusive signatures, `binds` needs
    the whole declaration, `signature_of`, `digest`;
  - `DiagnosticWarrantGrant`.
- `cognition/catalog_reasoner.py` `diagnostic_declarations` derives the set from the existing
  catalog.
- SP `product.py` `diagnostic_declaration_set()` is checked against `DECLARATION_DIGESTS` when the
  pack loads.

### Resolution and replay
- `core/warrant.py` `WarrantResolver`:
  - `resolve` and `verify`;
  - facts from attestations and Runs;
  - an outcome must agree with the attestation's record;
  - a grant must match its relation and prediction;
  - `verify` compares the stored relation with the snapshot's copy.
- `storage/postgres/warrants.py` is the shared builder.
- `core/belief.py` `verify_stored_revision` raises `WARRANT_UNVERIFIED`.

### Episode
- `core/episode.py`:
  - resolves the view;
  - queues DIAGNOSTIC_WARRANT reviews (records the refusal when none can be queued);
  - `counted_triggers`: an event cites only warranted relations;
  - `superseded_versions` and `superseded=` refuse new attempts under a superseded version.

### Loop
- `verification/loop.py`:
  - `_revise`: the both-sides skip counts warranted evidence only; a person is asked again when a
    new unsettled relation appears;
  - `standing()` implements I6;
  - `_ask` queues what the rule waits on;
  - stop reasons AWAITING_REVIEW, SUPPORTED_UNDISCRIMINATED, COMPETING_SUPPORT, all resumable;
  - the episode's observed outcomes, from `storage/postgres/warrants.py::episode_outcomes`, and
    every relation an observation produced (`SqlRelationStore.from_observation`);
  - line-based `_independence`;
  - notes: an unclaimed or foreign signature, an own-class refuting outcome, untested rivals, the
    declared-class statement of a conclusion of a declared class (bound or identified);
  - `_conclude` records a member of a declared class under the class's canonical name.
- `verification/sufficiency.py` projects the facts and DOMAIN warrant a planned result would get.
  Without this the planner saw no sufficient check and the gate refused everything — found and
  fixed during implementation.

### Conclusions and memory
- `core/root_cause.py`: `confirm_root_cause(warrant_refs=…)` refuses with `UNWARRANTED`, and the
  miner skips unwarranted conclusions.
- `core/repositories/failures.py`: `similar_failures` skips them too.

### Product
- SP `authority_policy.py` (reject and challenge `2.0.0`) and `vertical.py` (promote `2.0.0`);
  `diagnosis_targets()` uses only `2.0.0`, and `1.0.0` stays registered for re-derivation.
- `research/service.py`:
  - wiring;
  - AWAITING_REVIEW and SUPPORTED_UNDISCRIMINATED park the episode (resumable);
  - the conclusion lists SUPPORTED members that are not confirmed.

### Reviews
- `core/repositories/warrants.py` (SQL and in-memory twin).
- `interfaces/review_cli.py`: `lab-brain review list|show|resolve|expire`.
  - `show` prints the claim, the observation and every rival's effect on that observable, plus the
    domain's attribution of the outcome ("the declared signature of X") and the `--is-class`
    reference.
  - `resolve --is-class` records the identity statement.
  - `expire` runs OPS-002's `ReviewExpiryProcessor` for the project, so an overdue review is
    closed by expiry (never answered late) and the next run asks again. `list` marks reviews past
    their deadline. Nothing in the product schedules the sweep.

### Provenance
- `verification/evidence.py`: a relation names the inference that authored its prediction.

### Migration `012o_causal_warrant_gate.sql`
- the policy flag;
- the `DIAGNOSTIC_WARRANT` subject: one review per relation, and the subject must be a gated
  relation;
- `diagnostic_warrant_review_enqueue`;
- `diagnostic_warrant_grants`, append-only. For every writer, its trigger requires:
  - an outstanding review;
  - an active human member;
  - neither the episode's actor nor the hypothesis's author;
  - a matching relation and prediction.

  A deferred constraint makes every grant the closure of its review.
- the `WARRANT_GRANT` closure kind;
- `diagnostic_warrant_resolve`: atomic, no answers after expiry; optional `identifies_class_ref`;
- an expired review may be asked again; a refused one never;
- a prediction-instantiated relation must describe its own observation: the prediction is the
  target's; the outcome is predicted; it cites at least one attestation, and each records that
  outcome of the prediction's observable and space, for that observation, from a run of the
  hypothesis's episode. The resolver warrants nothing without an attestation;
- relation content immutable, and its actor changes only with its invalidation;
- no new belief event under a superseded policy version;
- `failure_analyses.warrant_refs`, required for a new CONFIRMED row. Each ref must appear as a
  SUPPORTS warrant in the snapshot of a decision that promoted the cause. The check fires after the
  EPI-002 trace check.

---

## 5. Threat model: before and after

| # | threat | before | after |
|---|---|---|---|
| T1 | proxy observable (CE-1, recorded) | CONFIRMED | never promoted; a review on the relation; the report names the unproposed class whose signature was observed |
| T2 | shared outcome, SUPPORTS or PREDICTS (CE-2) | both promoted; arbitrary confirmation | not confirmed until the rival is rejected on a warranted refutation (its own check); untestable rival → nothing confirmed |
| T3 | correlated repeats | each Run counted | one evidence line |
| T4 | spoofed provenance | n/a | resolution never reads authorship (`ast` test) |
| T5 | class-name mimicry | n/a | binding needs the whole declaration; the conclusion states the declared class in its own words |
| T6 | self-certification | n/a | no output field reaches resolution; author and episode actor cannot grant |
| T7 | reviewer error | n/a | per relation, attributable, rationale required, answered once, before expiry, by an active human member |
| T8 | forged snapshot or rewritten relation | n/a | re-checked against the stored relation and attestation; relation content immutable |
| T9 | closed world | n/a | **inherent residual**: an unnamed mechanism is not excluded; untested rivals named |
| T10 | downstream propagation | 2 inert precedents | unwarranted conclusions excluded from the miner and case memory |
| T11 | policy downgrade | n/a | superseded versions refused; targets guard-tested |
| T12 | unwarranted refutation (recorded ×3) | CONTRADICTED by ALLOW | gated; only a governed rejection on a warranted refutation excludes a rival |
| T13 | wrong declaration | trusted | still trusted, code-reviewed; digest checked at load |
| T14 | alternative laundering | as any hypothesis | same gate |
| T15 | benchmark leakage | n/a | gate tests written for two non-SP toy domains |
| T16 | direct table writes | n/a | grants, relations and confirmations guarded by triggers for every writer |
| T17 | a second cause | n/a | any observed signature of another declared class, predicted or not, blocks a unique confirmation; two SUPPORTED classes → COMPETING_SUPPORT (resumable) |
| T18 | a forged relation borrowing an observation | n/a | refused at insert; the resolver mirrors the check |
| T19 | invalidating a rival's affirmation | n/a | still counted |
| T20 | a reviewer approving without knowing the domain's attribution | n/a | the packet shows it; approval alone does not join a class |
| T21 | an identified member whose class's refuting outcome is observed by another check | n/a | blocks confirmation, predicted or not |
| T22 | a review nobody answers before its deadline | n/a | `review expire` closes it through OPS-002; the next run asks again |
| T23 | a relation claiming an outcome with no attestation | n/a | refused at insert; the resolver warrants nothing |

---

## 6. Unknown and novel mechanisms

An uncatalogued mechanism still goes through the whole loop. It is proposed, planned for and
checked; then:

1. Its support or refutation queues a DIAGNOSTIC_WARRANT review. The belief does not move, and the
   episode parks as AWAITING_REVIEW.
2. A person answers with `lab-brain review resolve`, and a resumed episode lets the answer count:
   - **APPROVED**: the move is allowed with a REVIEW warrant, and the conclusion records the grant.
     If the observed outcome is a declared class's signature, the reviewer must also say, with
     `--is-class`, that the hypothesis *is* that class. Approving the link alone leaves it
     unconfirmed. End-to-end tests cover both cases.
   - **REJECTED**: terminal for that relation. It is never re-asked, and the hypothesis is not
     rejected for want of a warrant.

A reviewed link becomes domain knowledge only through a code-reviewed DomainPack change.

---

## 7. Migration, versioning, history

- **Re-derivation.** The policy versions that decided history (`1.0.0`) stay registered. All six
  decisions stored in the deployment re-serialise byte-exact and re-evaluate to their stored
  verdicts (`fixtures/history/pre_gate_decisions.json`).
- **The wrong confirmation under the gate.** The snapshot behind it, under promote `2.0.0`, gives
  DIAGNOSTIC_WARRANT_MISSING.
- **No row is rewritten.** `fan:30d9407f…` stays CONFIRMED on record, with no warrant refs, so it is
  no longer a precedent or a mining input.
- **No prompt, contract or probe changed.** Every qualification lock stays valid.
- **The benchmark reports are byte-identical.** All ten root-cause cases keep their verdicts.
- **Spec amendments to record:**
  - §8.2.1: the policy flag, the reasons, the view field, and per-type gated evaluation;
  - §17.19.1: the `DIAGNOSTIC_WARRANT` subject and the `WARRANT_GRANT` closure kind (v3.3-a15);
  - EPI-002 extension: a confirmed cause's support is warranted;
  - the loop's confirmation rule and stop reasons;
  - EVI-004: WORK independence of run-derived evidence counts lines;
  - relation content immutability.

---

## 8. Verification

Full numbers, logs and CI links are in `docs/audit/causal-warrant-gate-v1/`.

- **Gate unit tests** (`tests/unit/test_causal_warrant_gate.py`), over two non-SP toy domains:
  - declarations and binding;
  - authorship independence;
  - resolver re-checks: stored relation, attestation outcome, grant prediction;
  - policy gating, per type, with no borrowing; replicates;
  - refusals and their precedence;
  - snapshot hashing;
  - every clause of the confirmation rule: shared PREDICTS, coarse challenge, refuted copy, late
    refutation, unsettled rival support, foreign signature, competition;
  - the read path;
  - the product target guard, superseded versions, the runtime digest.
- **History** (`tests/unit/test_pre_gate_history.py`): the real stored decisions.
- **SP end to end** (`tests/e2e/test_causal_warrant_counterexample_postgres.py`):
  - the catalog control;
  - novel mechanism APPROVED → confirmed;
  - proxy never promoted (review, provenance);
  - no queue → parked;
  - REJECTED terminal;
  - member-only, no self-grant, no late answers;
  - shared SUPPORTS and PREDICTS, with and without a queue;
  - an untestable rival;
  - the unproposed-class note;
  - an unwarranted falsifier neither vetoes nor is ignored;
  - the CLI, including `review expire` and a re-ask after it;
  - an identified paraphrase recorded as its declared class;
  - direct grant inserts, relation rewrites, empty-attestation relations and fake warrant refs
    refused.
- **Mutation battery.** One entry per rule, each naming the test that kills it, run in full on a
  fresh database.

---

## 9. Limitations and unresolved risks

- **Closed world (T9) is inherent.** Rivals that never predicted the observation are not excluded
  by evidence; the conclusion names them as "never tested".
- **A rival that only PREDICTS the same outcome, with an untestable falsifier, parks the episode.**
  An identity statement resolves a paraphrase of the candidate's class. For a genuinely different
  mechanism there is no DISCRIMINATION review in which a person could say "R does not produce o".
  This is narrow over-blocking, by design for now.
- **Rivals stuck on other reasons do not block.** A rival stuck at CONDITION_MATCH_UNKNOWN or
  INDEPENDENCE_BASIS_NOT_MODELLED creates no review, so it does not block confirmation.
- **Single-member projects cannot grant**, since the episode's actor may not answer.
- **Measured falsifiers cannot exclude a rival** while the only reject policy is simulation-gated.
  This is latent: there are no measurement workflows here.
- **Declarations are trusted domain knowledge.** The SP set asserts that each class's signature is
  exclusive among its five classes. A catalog version bump must keep the old set registered.
- **Binding is by exact mechanism plus the whole declaration**, so model paraphrases go to review.
  V2 could show models the declared class names (contract and probe change, then requalification).
- **The converse failure is not repaired.** A true cause labelled PREDICTS is not promoted;
  relabelling after execution is forbidden.
- **Planning still follows model-declared effects** when choosing checks; projections are now
  honest about which results would need a person.
- **No revocation of grants.** The answering actor is a parameter of the CLI and the database
  function (the existing `--actor` model), so a holder of database access can answer as any member.
  Separation of duties is only as strong as that identity. An authenticated channel (per-person
  database roles or a verified token) is an owner decision.
- **No product path declares a review-queue policy**, so warrant reviews cannot be queued until an
  operator declares one. Episodes park, fail closed.
- **A forged event committed directly makes later projections of that hypothesis fail closed
  permanently.** The read path refuses it rather than repairing it.
- **Model-run episodes now need a person** for most belief moves: more human work, by design.
- **Genuinely co-occurring causes are never concluded.** Two SUPPORTED classes park the episode as
  COMPETING_SUPPORT. The identity statement is the only way out, and it is false for two distinct
  causes, so a reviewer must not use it to unblock one. A multi-cause conclusion, or a governed
  "close as co-occurring" action, is an owner decision.
- **The expiry sweep is not scheduled.** `lab-brain review expire` runs it on demand. This gap was
  already there for every review type; scheduling it is an operations decision.
- **No §6.18 quarantine set is applied** by the episode-outcome scan, just as the loop's belief
  projection applies none today. A quarantined outcome can only block (fail closed); it cannot
  confirm.
- **A CONFIRMED row written directly by a database writer** is checked for warrants traced to the
  promoting decision, not for the confirmation rule. This is the same trust class as the
  self-asserted actor: anyone with database access. A dedicated write function or a stored standing
  record would close it (V1.1).
- **Withdrawing a rival's affirmation does not unblock the candidate.** Invalidated affirmations
  count. Only a warranted refutation that leaves the rival CONTRADICTED discharges it.

## 10. Independent reviews

Three reviewers ran independently:
- a root-cause verifier;
- a design critic, who reviewed the draft and then each implementation;
- an implementation attacker, with executable attacks on its own database.

The full reports and how each was resolved are in the audit package.

| round | key findings | resolution |
|---|---|---|
| verifier (baseline) | 9/9 claims confirmed; added three unwarranted rejections, the converse failure, laundered provenance, weak xfails | symmetric gating; provenance; precise tests |
| critic (draft) | in-set discrimination; ungated refutation; per-relation thresholds; resumability | I6, refutation gate, `_decide_warranted`, service and CLI |
| critic (`bc55458`) | B1 silence-binds false-confirmation path; B2 self-grant; B3 queue-dependent threats; B4 unwarranted veto; B5 runtime integrity | whole-declaration binding and class family; DB self-grant refusal; record-derived threats; warranted-only skip; digest at load, superseded refusal |
| attacker (`bc55458`) | direct grant INSERT confirmed the proxy; mutable relations; snapshot-copy replay; coarse exclusion; foreign signature; author grant; per-type gating | trigger plus deferred closure constraint; immutability trigger; stored-relation re-check; governed-rejection exclusion; signature rule; author refusal; per-type evaluation |
| critic (`7e3cc43`) | approve as a fail-closed gate with conditions; N1 paraphrase deadlock; N2 approval waives a foreign signature; N3 unpredicted signatures unseen; N4 single-member, measured falsifiers | identity statement (`--is-class`) and attribution in the packet; waiver removed; episode-wide outcome scan; COMPETING_SUPPORT resumable; N4 documented |
| attacker (`7e3cc43`) | forged cross-episode relation INSERT confirmed the wrong cause; an expired review blocked forever; superseded only where wired; `dds:`-shaped fake refs; invalidation discharged a rival; actor rewrite; answering actor is a parameter | relation insert trigger and resolver mirror; re-ask after expiry; supersession from the store and in SQL; refs bound to the promoting decision; invalidated affirmations counted; actor change only with invalidation; identity model documented as an owner decision |
| critic, final pass (`ed0670b`) | approve as a fail-closed P0 gate, not as ready for real research; 1 an identified member ignored its class's refuting outcome (latent); 2 an identified cause recorded in its author's words; 3 co-occurring causes cannot be concluded; 4 the outcome scan ignores quarantine | 1 and 2 fixed in `134c07b` (own-class scan; class name and declaration recorded); 3 and 4 documented (§9, §12) |
| attacker, final pass (`ed0670b`) | no false confirmation without impersonating the PI (A2, owner decision); the re-ask after expiry needs the sweep nothing calls; an empty-attestation relation passed the insert trigger (blocking only); a directly written CONFIRMED row bypasses the confirmation rule; withdrawing a rival's affirmation never unblocks | `review expire` command; empty-attestation relations refused in SQL and in the resolver; the last two documented (§9) |

## 11. Not ready for real research

`READY_FOR_REAL_RESEARCH` stays false. The gate removes one class of unjustified confirmation and
one of unjustified rejection. It does not:
- make hypothesis sets complete (T9);
- make declarations correct (T13);
- make models choose diagnostic checks (planning).

## 12. Decisions for the owner

1. Which project role may answer warrant reviews; whether the answering channel must be
   authenticated.
2. A default review-queue policy per project, and the command that declares it.
3. Whether a DISCRIMINATION review subject (V1.1) should resolve the narrow over-blocking case in
   §9.
4. Whether to annotate `fan:30d9407f…` visibly beyond its derived exclusion.
5. Merge, deploy, and whether to re-run the governed Gemini cases. That costs external calls under
   the existing egress authorisation.
6. V2: show declared class names to models (requires requalification).
7. A multi-cause conclusion, or a governed "close as co-occurring" action (§9).
8. Scheduling OPS-002's expiry sweep, and a dedicated write path for CONFIRMED rows (§9).
