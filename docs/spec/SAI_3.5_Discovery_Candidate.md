> **SUPERSEDED — historical record.** This file is `3.5.0-discovery-candidate.1` of 2026-11-01,
> kept unchanged below this note. It is superseded by the master specification candidate
> [SAI_3.5.md](SAI_3.5.md) (`3.5.0-master-candidate.1`, now `3.5.0-master-candidate.2`, CANDIDATE — NOT ACTIVE). Its requirements
> D-001…D-046 are retired: each is audited in the [requirement audit](sai35/requirement-audit.md)
> and mapped to `S35-<AREA>-NNN` identifiers in the [change register](sai35/change-register.md).
> Its companion links now lead to the master's appendices, which were rewritten in place (earlier
> versions are in the repository history). Nothing in this file is an obligation, and no code, test
> or report may cite its D-NNN identifiers.

# SAI 3.5 Discovery Candidate — Autonomous Scientific Discovery with Independent Validation

Version: `3.5.0-discovery-candidate.1` · Date: 2026-11-01 ·
Base: `integration-integrity-accounts` @ `a38ad63a4f4ad83c895cbd1e32b2e760d878f356`

Status: **CANDIDATE — NOT ACTIVE — not integrated.** It does not change SAI 3.4 (`3.4.0-phased.1`), SAI 3.3 or the G0–G9 acceptance gates.

`READY_FOR_REAL_RESEARCH = false` · G0 is NOT PASSED · no G-D level has been evaluated.

## 0. Status, authority and how to read this candidate

**What this is.** A proposed extension of the product target. SAI 3.4 specifies governed autonomous
*modeling*: from a question to a validated simulation. This candidate specifies autonomous
*discovery*: finding the problem, proposing mechanisms that are new and testable, recovering from
failed hypotheses, and having findings validated by someone other than the system that proposed
them. It also specifies how anyone could find out whether discovery works: the independent G-D
acceptance framework (§6) and a matched-budget comparison (§7).

**What it is not.** It is not an active specification, not an Owner approval, not an
implementation and not evidence that any capability exists. [ACTIVE_SPEC.yaml](ACTIVE_SPEC.yaml)
is unchanged and still names the SAI 3.4 phased basis and the inherited SAI 3.3 executable
profile. No SAI 3.3 or SAI 3.4 file, registry, milestone, test or acceptance condition is edited.
The candidate checker records their SHA-256 at the base commit and fails if any byte changes.

**Inheritance.** Everything in [SAI 3.3](SAI_3.3.md) (a1–a18, P1–P28, 60 requirements and their
tests), the [SAI 3.4 phased basis](SAI_3.4.md) and the approved
[SAI 3.4 candidate contract](SAI_3.4_Candidate.md) (ASM-001–018, G0–G9) is inherited unchanged.
This candidate only adds. Where it names an existing mechanism, such as the Causal Warrant Gate,
TransitionPolicy or ReviewQueue, it uses that mechanism as it is and does not redefine it.

**Reading conventions.**

- MUST and SHOULD keep their SAI 3.3 §0.2 meaning.
- Each normative statement starts with an HTML comment `<!-- statement: key -->`, followed by a
  bold `D-NNN MUST` or `D-NNN SHOULD`. The rest of its section refines that statement.
- `D-001`…`D-046` (three digits) are SAI 3.5 candidate requirement IDs. They are distinct from
  SAI 3.4's Owner decisions `D-01`–`D-08` (two digits), which keep their meaning. SAI 3.5 Owner
  decisions are `OD-01`… ([decisions](sai35/decisions-and-review.md)).
- Planned tests are named `T-D-NNN`. In the [candidate registry](sai35/normative-statements.yaml)
  every statement has `tests: []` and `status: SPECIFIED`. A planned test is an obligation, never
  evidence.

**Two kinds of validity.** *Engineering validity* means code, tests, CI, mutation batteries and
record integrity show that a rule is enforced. *Scientific validity* means an independent
evaluation shows that the system finds true mechanisms, avoids false ones and that its findings
hold up. Engineering validity is necessary and never sufficient. This document keeps the two
apart, and so must every report that cites it.

Companion documents:
[G-D acceptance](sai35/acceptance-gd.md) ·
[matched-budget protocol](sai35/matched-budget-protocol.md) ·
[end-to-end architecture](sai35/architecture-end-to-end.md) ·
[implementation status](sai35/implementation-status.md) ·
[roadmap](sai35/roadmap.md) ·
[Owner decisions and self-review](sai35/decisions-and-review.md) ·
[traceability to SAI 3.4 and G0–G9](sai35/traceability.md) ·
[candidate registry](sai35/normative-statements.yaml) ·
[ADR-0016](../adr/ADR-0016-sai35-discovery-candidate.md).

<!-- statement: candidate.additive -->
**D-001 MUST** — SAI 3.5 is additive. No D-NNN statement may weaken, replace, reinterpret or
reorder any SAI 3.3 or SAI 3.4 MUST, any G0–G9 acceptance condition, any HARD-LOCK or any
existing Owner gate. A direct conflict found later is a spec issue that stops the affected slice
(AGT-015). It is not resolved by assuming that the newer document wins.

## 1. Product vision

The ultimate product target of SiPh Lab is **an autonomous AI scientist capable of discovering
research problems, generating genuinely novel and falsifiable physical hypotheses, reframing
failed research, and independently validating scientific findings.**

This sentence is a target, not a description of today's system. As of the base commit, none of
the four capabilities has been demonstrated, and G0 is NOT PASSED (see
[implementation status](sai35/implementation-status.md)).

<!-- statement: vision.target -->
**D-002 MUST** — The product target is the autonomous AI scientist stated above. Each of its four
capabilities has an operational meaning that can be checked:
(1) *discovering research problems*: proposing a problem with recorded provenance to an
unexplained observation, a literature gap or a failed hypothesis (§3);
(2) *generating genuinely novel and falsifiable physical hypotheses* (D-004);
(3) *reframing failed research*: append-only reframing that keeps the failure history (§3);
(4) *independently validating scientific findings*: validation by a role separated from discovery,
pre-registered, and ending at the existing Causal Warrant Gate (§4).

<!-- statement: vision.claim_discipline -->
**D-003 MUST** — No document, interface, report, status file or release note may claim any of the
four capabilities beyond the highest G-D level that an independent evaluator has passed for the
stated scope (§6). Engineering results such as tests, CI, mutation scores or deterministic
benchmarks are reported as engineering validity and are never presented as discovery capability.

<!-- statement: vision.novelty_falsifiability -->
**D-004 MUST** — A hypothesis is called *novel* only when its novelty status cites a
PriorArtSearchRecord with recorded sources, queries, date range and limitations (SAI 3.3 SRC-003).
Internal novelty is never presented as global novelty. A hypothesis is called *falsifiable* only
when it carries at least one typed prediction with a CONTRADICTS effect over an observable that an
available or Owner-approvable experiment can measure, within a frozen outcome space (SAI 3.3 §9.1
and §17.5.1).

A long list of plausible mechanisms is not novelty. A mechanism that no available experiment can
tell apart from a known one is not a discovery under that experiment set (§3).

## 2. End-to-end architecture

The full research chain extends the SAI 3.4 responsibility chain (ASM-002) with discovery stages.
It is a chain of responsibility, not a script: the cheapest sufficient path is still chosen, and a
stage may be skipped with a recorded reason.

```text
Problem Discovery ─► Literature & Prior-Art Search ─► Distinguishable-Mechanism Expansion
 ─► Hypothesis Admission (SAI 3.3 §8) ─► Discrimination-per-Cost Experiment Selection
 ─► Prospective Pre-registration ─► Physical Model Construction (typed spec, from scratch)
 ─► Licensed Lumerical Execution on internal workers (CHARGE / MODE / FDTD / INTERCONNECT)
 ─► Parameter Sweeps ─► Numerical Convergence Studies ─► Bounded Model Refinement
 ─► Independent Numerical and Physical Validation ─► Evidence Admission
 ─► TransitionPolicy / Causal Warrant Gate ─► Anomaly & Reframing Ledger update
 ─► Traceable bilingual (zh-TW / en) Scientific Report
```

Components, data flow, trust boundaries and the internal-worker design are in
[architecture-end-to-end.md](sai35/architecture-end-to-end.md).

<!-- statement: e2e.chain -->
**D-005 MUST** — Every discovery campaign persists versioned inputs, outputs, governance decisions
and restartable checkpoints for every stage of the chain above. Each output is bound to its
project, episode, trace, content hash, schema and producer. A skipped stage records why it was
skipped.

<!-- statement: autonomy.no_external_coding_agent -->
**D-006 MUST** — Production research must not depend on Codex, Claude Code or any other external
coding agent. A clean production deployment contains no coding-agent executable, session, personal
login, credential or network route. No research stage hands work to such an agent, edits the
repository, or waits for a developer to write model code. **Acceptance check (T-D-006):** in a
deployment-equivalent environment where coding-agent binaries are absent and their network
endpoints are blocked, the full chain runs from a blank workspace to a bilingual report on an
in-envelope case. Process and network audit logs show zero coding-agent invocations. Every attempt
to reach one is refused and logged. Every human intervention is a recorded ReviewItem.

This restates ASM-001 for discovery and does not weaken it. Governed model calls through
ScientificLLM and ModelRouter are allowed under the existing egress, sensitivity and budget gates.
They return typed proposals only, with no shell, raw SDK, arbitrary code or deployment rights.

<!-- statement: e2e.literature -->
**D-007 MUST** — Autonomous literature search runs only through ExternalSourceAdapter providers
that the project has authorized. A query leaves the deployment only when it has been declared
PUBLIC. Every retrieved passage is pinned by version and hash and carries its license class. Read,
execute, modify and redistribute rights are judged separately (ASM-003). A search records what was
actually searched, not what was configured; a provider that could not be reached appears in the
record's limitations.

<!-- statement: e2e.model_from_scratch -->
**D-008 MUST** — Physical models are constructed from scratch from a versioned, unit-checked
PhysicalModelSpec (ASM-004). Geometry, materials, doping, contacts and boundaries, meshes and
solver settings are configured only through the closed set of typed operations of a reviewed
deterministic constructor (ASM-005). No model-generated code runs, no hidden prebuilt project is
reused as if it were new, and no unknown parameter is filled with a solver default.

<!-- statement: e2e.licensed_internal_workers -->
**D-009 MUST** — Licensed Lumerical CHARGE, MODE, FDTD and INTERCONNECT run only on internal,
qualified workers owned by the deployment. Execution is *license-governed* (actual entitlement
checkout and release are recorded; a missing or mismatched license blocks the run), *Owner-authorized*
(a campaign may use a licensed product only under a recorded Owner authorization naming product,
scope and period), and *cost-governed* (budget is reserved before execution and every attempt is
reconciled; ASM-006, ASM-007). A mock never stands in for a licensed run. No external agent operates
a solver. Each product is qualified separately; qualifying one does not qualify another.

<!-- statement: e2e.sweeps -->
**D-010 MUST** — A parameter sweep is pre-registered before it runs: parameters, ranges, sampling,
observables, stopping rule and budget. Each sweep point is its own Run with lineage to the spec and
the sweep plan. Sweep outputs are model outputs under stated conditions. They are never presented
as measurements.

<!-- statement: e2e.convergence -->
**D-011 MUST** — A simulated observable may serve as discriminating evidence in the Discovery Loop
only after the numerical convergence study required by ASM-008 has passed for that observable:
frozen residual and conservation checks, at least three comparable mesh or step levels, and domain
size studies. A solver's own "converged" flag is not enough. Non-asymptotic or multi-branch results
are UNKNOWN or FAIL and cannot discriminate between mechanisms.

<!-- statement: e2e.refinement -->
**D-012 MUST** — Model refinement stays within ASM-011: pre-approved assumptions, parameter ranges,
development data and budget, producing immutable child versions. Refinement may not quietly turn
the hypothesis under test into a different one to improve the fit. A change to a physical mechanism
is a new hypothesis with its own lineage, admission and pre-registration.

<!-- statement: e2e.physical_validation -->
**D-013 MUST** — A physical discovery claim needs independent physical validation (ASM-009,
ASM-010): reference data that is independent of the construction and calibration sources, with
measurement uncertainty, under comparable conditions. Agreement between simulations, or a plausible
trend, never validates a physical discovery on its own.

<!-- statement: e2e.bilingual_report -->
**D-014 MUST** — Discovery reports are traceable and bilingual (zh-TW and en) under ASM-016. Beyond
the eight ASM-016 content classes, they cover the problem statement and its provenance, the
mechanism classes and the experiment set they were counted under, the anomalies and their states,
the reframing history including the failed hypotheses, the pre-registrations, every validation
outcome and every stop reason. Both languages carry the same identifiers, numbers, states and
uncertainty. Canonical records are never overwritten by a translation.

## 3. Discovery Loop

The Discovery Loop is the part of the system that decides *what to look at next*. It can propose;
it never confirms (§4).

```text
          ┌──────────── anomaly registry (explicit states) ◄──────────────┐
          ▼                                                              │
 Problem Discovery ─► Mechanism Expansion ─► class partition under E ─► Discrimination
          ▲              (distinguishable classes, not counts)            per cost
          │                                                              │
 Research Reframing ◄── failed / inconclusive hypotheses ◄── validation (§4) ◄┘
   (append-only)
```

<!-- statement: loop.problem_discovery -->
**D-015 MUST** — Problem discovery produces ResearchProblem records. Each states its origin
(`ANOMALY`, `LITERATURE_GAP`, `FAILED_HYPOTHESIS` or `OWNER_QUESTION`) and links to the records
behind it. A discovered problem may consume resources beyond the zero-cost tier only after an
active human project member accepts it. Problem discovery never sends INTERNAL material past the
egress gate.

<!-- statement: loop.mechanism_classes -->
**D-016 MUST** — Mechanism expansion is measured by the number of *distinguishable mechanism
classes* under the experiment set available to the campaign. A raw count of hypotheses is never
reported as diversity, breadth or coverage. Every reported class count names the experiment-set
version it was computed under.

<!-- statement: loop.mechanism_class_definition -->
**D-017 MUST** — Two admitted hypotheses belong to the same class under experiment set *E* when,
for every experiment in *E*, their typed predictions cannot be told apart within the declared
tolerance and measurement uncertainty. The partition is deterministic, versioned and recomputed
whenever *E* changes. When distinguishability cannot be decided, the hypotheses count as one class
for diversity, which is the conservative choice. Every pair that was merged this way is listed.

<!-- statement: loop.anomaly_state -->
**D-018 MUST** — Unexplained observations are kept in an anomaly registry with explicit,
append-only states (below). An anomaly is never deleted and never quietly dropped from a report. A
state change records its trigger, its evidence references and the actor or policy behind it.

| Anomaly state | Meaning | Entry condition |
|---|---|---|
| `UNEXPLAINED` | an admitted observation that no admitted hypothesis predicts | detection rule or a researcher flags it |
| `UNDER_INVESTIGATION` | at least one problem or hypothesis targets it | linked ResearchProblem |
| `PROVISIONALLY_EXPLAINED` | an explaining hypothesis is SUPPORTED, not CONFIRMED | TransitionPolicy decision |
| `EXPLAINED` | the explaining hypothesis is CONFIRMED | Causal Warrant Gate decision only |
| `ARTIFACT` | an independent check shows it is a measurement or numerical artifact | recorded validation |
| `UNRESOLVED_INSUFFICIENT` | the available experiments, independence or budget cannot resolve it | INSUFFICIENT_VALIDATION outcome |
| `WITHDRAWN` | its source was retracted or found contaminated | source event |

`EXPLAINED` returns to `UNDER_INVESTIGATION` when the confirmation behind it is withdrawn on
re-derivation. `PROVISIONALLY_EXPLAINED` is never displayed as explained.

<!-- statement: loop.reframing -->
**D-019 MUST** — When hypotheses fail, Research Reframing creates a new, append-only Reframing
record. It links to the failed or inconclusive hypotheses, the anomalies and the earlier problem
that led to it, and states what changed and why. Reframing never deletes, edits or hides failure
history. It cannot turn a failed hypothesis into support: the earlier hypothesis keeps its last
belief state, and evidence that failed it cannot be reinterpreted as support for it or for its
successor.

<!-- statement: loop.reframing_accounting -->
**D-020 MUST** — A reframed hypothesis is a new hypothesis with its own lineage. It is marked as
proposed after the failure, and it needs new prospective validation (§4); the evidence available
when it was proposed cannot support it. Every reframing and every abandoned branch stays in the
denominators of the discovery metrics. The number of reframings per problem and per campaign is
capped by a versioned policy and by the budget.

<!-- statement: loop.experiment_selection -->
**D-021 MUST** — Experiments are chosen to discriminate between mechanism classes per unit of
cost: the selection prefers the experiment that separates the most currently surviving classes for
the lowest CostVector, using SAI 3.3 §9 sufficiency and deterministic ordering. Uncalibrated
expected-information-gain numbers are not used (SAI 3.3 §9.2). An experiment that needs money, a
license, a physical experiment or publication is only proposed; it runs after its Owner gate (§5).

<!-- statement: loop.termination -->
**D-022 MUST** — Every campaign runs under explicit budgets (tokens, compute, experiments,
licensed seat time and wall time) and a versioned stopping policy. It always terminates, and it
records the termination reason. Budget exhaustion or stagnation ends the campaign as STOPPED or
INSUFFICIENT_VALIDATION. It is never reported as a discovery.

## 4. Discovery and validation

Discovery proposes; validation independently disposes. The two are separate roles with separate
permissions, so that a system cannot both make a claim and certify it.

<!-- statement: validation.role_separation -->
**D-023 MUST** — Discovery and validation are separate roles, identities and permissions. The
discovery side cannot write validation verdicts, cannot change validators, protocols, tolerances or
scoring, and cannot read sealed references, holdouts, ground truth or scoring credentials. The
validation side does not generate the hypotheses it validates. A component that has seen a sealed
answer no longer counts as independent for that case.

<!-- statement: validation.preregistration -->
**D-024 MUST** — Each validation is pre-registered prospectively, before its data exists. The
pre-registration names the hypothesis, the predictions, the experiment or capability, the analysis
and the decision rule. It is dated by the database clock, it is immutable, and a human project
member authorizes it whenever it uses money, a license or a physical experiment. A change after
registration is a new registration. The old one and its outcome stay on record.

<!-- statement: validation.no_retrospective_self_support -->
**D-025 MUST** — There is no retrospective self-support. Evidence that existed before a hypothesis
was proposed, evidence the hypothesis was derived from, evidence with an unknown capture time, and
evidence whose lineage reaches any of these cannot support that hypothesis. Such evidence is
recorded as context (CITES), never as SUPPORTS. These rules are at least as strict as the G0
prospective-evidence rules `011p` and `011s` implemented on the G0 line at `58c68be`: known capture
time, clean lineage, declared capability kind, and pre-authorization by a human member. That line
is not integrated into this base.

<!-- statement: validation.cwg_only_confirmed -->
**D-026 MUST** — The existing Causal Warrant Gate (V1.1) remains the only path to CONFIRMED.
Discovery adds no shortcut and no automatic warrant. It does not widen DISCRIMINATION review or
multi-cause confirmation (SAI 3.4 D-03 stays open), and it does not enable SP 1.1.0. A numerical
match, a reproduced trend or agreement among several models never upgrades a claim to CONFIRMED by
itself.

<!-- statement: validation.epistemic_states -->
**D-027 MUST** — Every discovery claim carries an explicit epistemic state from the table below.
The state is a projection derived from canonical records (admission, pre-registrations,
BeliefRevisionEvents, Causal Warrant Gate decisions and governance outcomes). It never writes a
belief state itself. Only the transitions listed are allowed; any other transition is refused and
logged.

| State | Meaning | Derived from |
|---|---|---|
| `PROPOSED` | an idea generated by discovery; not yet a hypothesis | discovery record |
| `ADMITTED` | passed the SAI 3.3 §8 Hypothesis Admission Gate | admission |
| `PREREGISTERED` | a prospective test is frozen and authorized | pre-registration |
| `UNDER_TEST` | the authorized test is running | Job / Run |
| `SUPPORTED` | TransitionPolicy allowed SUPPORTED; not confirmed | BeliefRevisionEvent |
| `CHALLENGED` | as in SAI 3.3 §8.2 | BeliefRevisionEvent |
| `CONTRADICTED` | as in SAI 3.3 §8.2; the hypothesis failed its test | BeliefRevisionEvent |
| `INCONCLUSIVE` | as in SAI 3.3 §8.2 | BeliefRevisionEvent |
| `CONFIRMED` | confirmed through the Causal Warrant Gate | CWG decision only |
| `INSUFFICIENT_VALIDATION` | the required validation cannot be done with the independence, data, license, budget or authorization available | governance outcome |
| `STOPPED` | the campaign was stopped by budget, Owner, safety or time | governance outcome |
| `REFRAMED` | annotation: a Reframing record supersedes this line of work; the last belief state is kept | Reframing record |
| `WITHDRAWN` | an input was retracted or found contaminated | source event |

| From | Allowed to | Never allowed |
|---|---|---|
| `PROPOSED` | `ADMITTED`, `WITHDRAWN`, `STOPPED` | any belief state without admission |
| `ADMITTED` | `PREREGISTERED`, `INSUFFICIENT_VALIDATION`, `WITHDRAWN`, `STOPPED` | `SUPPORTED` or `CONFIRMED` without a test |
| `PREREGISTERED` | `UNDER_TEST`, `INSUFFICIENT_VALIDATION`, `STOPPED` | editing the registration in place |
| `UNDER_TEST` | `SUPPORTED`, `CHALLENGED`, `CONTRADICTED`, `INCONCLUSIVE` (TransitionPolicy decision only), `STOPPED` | `CONFIRMED` directly |
| `SUPPORTED` | `CONFIRMED` (CWG only), `CHALLENGED`, `CONTRADICTED`, `PREREGISTERED` (a new test), `INSUFFICIENT_VALIDATION` | `CONFIRMED` by any other path |
| `CHALLENGED`, `INCONCLUSIVE` | `PREREGISTERED` (a new test), `CONTRADICTED`, `REFRAMED`, `INSUFFICIENT_VALIDATION`, `STOPPED` | `SUPPORTED` from re-reading old evidence |
| `CONTRADICTED` | `REFRAMED` (annotation; a successor starts at `PROPOSED`); a further belief move only under SAI 3.3 TransitionPolicy on new prospective evidence | `SUPPORTED` or `CONFIRMED` through reframing or reinterpretation |
| `CONFIRMED` | `CHALLENGED`, `CONTRADICTED` or `WITHDRAWN` when re-derivation or new evidence withdraws it | silent removal |
| `INSUFFICIENT_VALIDATION` | `PREREGISTERED`, only with new resources and a new registration | `CONFIRMED` or `SUPPORTED` directly |
| `STOPPED` | none in this campaign; a new campaign links back to it | resumption without a new authorization |

<!-- statement: validation.stop_insufficient -->
**D-028 MUST** — The system must be able to stop. When validation is insufficient, the outcome is
an explicit `INSUFFICIENT_VALIDATION` or `STOPPED` state with its reason, what was tried, what it
cost and what would be needed to continue. Such an outcome is a success of governance, not a
failure of the system. It is scored as correct in every case where no mechanism can be validated
with the available means (§7). A confident claim made where a stop was warranted is a false
discovery.

<!-- statement: validation.uncertainty -->
**D-029 MUST** — Every discovery claim reports its scientific uncertainty separately by source:
numerical, input parameters, measurement or reference, model form, extraction and mapping. Belief
stays ordinal (SAI 3.3 §8.1) until calibration exists. An uncalibrated number is never displayed as
a probability that the claim is true. Unknown uncertainty is shown as UNKNOWN.

## 5. Human oversight and governance

<!-- statement: oversight.owner_gates -->
**D-030 MUST** — Four classes of action need a recorded Owner gate before they happen: spending
money (paid models, paid compute, purchases), using licenses (Lumerical products, seats,
entitlements), physical experiments (fabrication, measurement, lab time) and publication (any
external release of findings, data or claims). The authorization names the actor, time, scope,
ceiling and expiry. Automation never signs for the Owner, and a timeout is never consent.

<!-- statement: oversight.evidence_governance -->
**D-031 MUST** — Discovery outputs are proposals, not evidence. They enter the scientific record only
through the existing Artifact, Observation and Attestation admission path (ASM-012), keeping Run,
validity, conditions, uncertainty, source dependence and model-family identity. Records are
append-only. Corrections and withdrawals are new events that leave the original in place.

<!-- statement: oversight.provenance -->
**D-032 MUST** — Every discovery record (problem, mechanism class partition, anomaly state change,
reframing, pre-registration, selection decision, stop) carries provenance: its inputs by hash, the
producing component and version, InferenceProvenance for every model call, the policy versions in
force, and the trace. A record without provenance cannot justify a later transition.

<!-- statement: oversight.project_isolation -->
**D-033 MUST** — Discovery records, benchmark material, worker sessions, caches and evaluator
access are scoped to a project and to the reader's current clearance. A record from another project
is never reused without a project occurrence. Sealed evaluation material is reachable only by the
evaluation plane.

<!-- statement: oversight.accounts -->
**D-034 MUST** — Human account roles stay ADMIN and MEMBER. Project membership, independent
scientific reviewer authorization, independent evaluator assignment and worker service identity are
separate governance concepts and grant no account role. A second account of the same natural person
never counts as an independent reviewer or evaluator. The SAI 3.4 security decisions A3, A9 and A12
stay open and are not settled by this candidate.

## 6. Independent G-D acceptance framework

G-D is a separate acceptance framework for discovery. It sits beside G0–G9 and changes none of
them. Details per level are in [acceptance-gd.md](sai35/acceptance-gd.md).

<!-- statement: gd.independence -->
**D-035 MUST** — G-D acceptance is independent of G0–G9. Completing G0–G9 alone must never imply
successful autonomous discovery. A G-D level passes only when an independent evaluator, assigned
by the Owner and not the implementer, issues the verdict on that level's frozen protocol. The
system under test, its developers and any development agent cannot issue a G-D verdict.

<!-- statement: gd.levels -->
**D-036 MUST** — G-D has five levels, each with entry conditions, required evidence and pass or
fail criteria frozen before evaluation. Passing a lower level never implies a higher one. A level's
result applies only to the scope it was evaluated in (benchmark, model family, product
configuration and environment).

| Level | Name | Short pass condition |
|---|---|---|
| G-D0 | Protocol frozen | benchmark sealed, protocol and statistics pre-registered, evaluator assigned, environment captured |
| G-D1 | Offline synthetic discovery | in sealed synthetic worlds with hidden true mechanisms, arm C beats arm B under the matched-budget protocol at zero cost |
| G-D2 | Retrospective held-out literature discovery | the same on held-out real literature cases with contamination controls, with blinded expert review of novelty and falsifiability |
| G-D3 | Prospective simulation discovery | prospective discovery in evaluator-sealed licensed simulation cases on internal workers |
| G-D4 | Prospective physical discovery | prospective, pre-registered discovery confirmed by independent physical experiments |

<!-- statement: gd.no_substitution -->
**D-037 MUST** — G-D and G0–G9 do not substitute for each other in either direction. No G-D
result passes any G gate. G-D2 needs G0 accepted for the product configuration it evaluates. G-D3
needs, for its model family, the applicable G1, G2, G3, G7-SITE and licensed G8 results. G-D4
additionally needs G4, G5 and G6 for its scope. A run before those prerequisites is labeled
exploratory and cannot be signed as a G-D pass.

## 7. Matched-budget comparison

Whether discovery helps is an empirical question. It is answered by comparing three arms on the
same sealed cases under the same budget. The full protocol is in
[matched-budget-protocol.md](sai35/matched-budget-protocol.md).

<!-- statement: compare.three_arms -->
**D-038 MUST** — Every G-D1 to G-D4 evaluation compares three arms on the same cases:
**(A) single LLM**: the same model or models driven by a frozen, minimal prompt-and-tool loop,
without LIB's governance, debate, planner or Discovery Loop;
**(B) existing LIB**: the frozen product research workflow with the Discovery Loop off;
**(C) LIB with Discovery**: arm B plus the Discovery Loop of §3.
All arms produce the same answer schema: claimed mechanism, epistemic state, evidence references,
uncertainty, and the option to stop with INSUFFICIENT_VALIDATION.

<!-- statement: compare.matching -->
**D-039 MUST** — The arms are matched on: the same model or models (identifier, digest and decoding
settings); the same token, compute, experiment and licensed-seat budget, counting failures and
retries; the same tools and data access (corpus snapshot, experiment catalog and cost table); the
same time limit; the same seeds per case; and the same environment manifest. Unused budget is not
transferred. A budget overrun ends the case as STOPPED, and the attempt to exceed it is reported.

<!-- statement: compare.blinding -->
**D-040 MUST** — Scoring is blinded. The evaluator is not the implementer. Arm identities are
replaced by sealed labels held by a custodian until scoring is complete. The scorer is
deterministic and hash-frozen. Human judgments, such as novelty and falsifiability at G-D2 and
above, come from at least two independent blinded domain reviewers, with their agreement reported
and a pre-registered adjudication rule.

<!-- statement: compare.benchmark -->
**D-041 MUST** — The benchmark is frozen and sealed before any arm runs. It contains: synthetic
worlds with hidden true mechanisms, observationally equivalent rivals, anomalies, noise and cost
tables, including worlds in which no mechanism can be validated with the available experiments;
held-out real literature cases whose resolution the arms cannot have seen; and, later, physical
cases. Implementers never see sealed cases or truth. Every case stays in the denominator.

<!-- statement: compare.metrics -->
**D-042 MUST** — Five metrics are reported for every arm, each with its definition, unit, n and
interval: (1) **true-mechanism discovery rate**; (2) **distinguishable diversity**: the number of
equivalence classes under the available experiments, never raw hypothesis counts; (3)
**experimental efficiency**: experiments and cost until correct discrimination; (4) **false
discoveries**: the false-discovery rate, with confident wrong claims weighted more heavily; (5)
**reproducibility**: seed and environment re-runs, where any environment-manifest drift makes the
re-run invalid. Exactly one primary metric is pre-registered.

<!-- statement: compare.statistics -->
**D-043 MUST** — Statistics are pre-registered before unsealing: the experimental unit (case),
paired comparisons across arms on the same cases, interval methods, the minimum effect of interest,
non-inferiority margins, multiplicity correction across metrics and comparisons, sample size with
its justification, and any interim analysis with its error-spending rule. There is no
optional stopping, no cherry-picked seeds and no post-hoc exclusion.

<!-- statement: compare.contamination -->
**D-044 MUST** — Contamination controls are frozen with the protocol: model training cutoff versus
case resolution dates, overlap checks of case material against development data and public corpora,
memorization probes, fresh synthetic seeds generated after the freeze, and a pre-registered rule
for contaminated cases decided before unsealing. A contamination finding is reported. It is never
silently dropped.

<!-- statement: compare.stopping -->
**D-045 MUST** — Stopping rules are frozen with the protocol. A case ends on budget exhaustion,
time limit, or the arm's own STOPPED or INSUFFICIENT_VALIDATION outcome. A study ends at its
pre-registered n, or at a pre-registered interim boundary, or on a governance incident (any arm
breaching egress, budget or isolation), which invalidates the affected runs. A paid stage ends at
the Owner's ceiling and is reported as partial.

<!-- statement: compare.zero_cost_first -->
**D-046 MUST** — A zero-cost first stage comes before any paid stage. It uses local models and
offline synthetic worlds, with no paid API, no license and no physical experiment. Its result is
reported to the Owner whatever it shows. A paid, licensed or physical stage starts only after an
Owner authorization with a ceiling (§5), and a negative zero-cost result is not overridden by
running a bigger model on the same sealed cases.

## 8. Non-goals and falsification

This candidate does **not**:

- claim that the system can discover anything today, or that any G-D level has been passed;
- set READY_FOR_REAL_RESEARCH to true, pass G0, or pass any of G0–G9;
- activate SAI 3.5, edit ACTIVE_SPEC.yaml, or add D-NNN to the active registry or milestones;
- replace a human Owner gate, a signed review, or the Causal Warrant Gate with automation;
- treat simulation agreement as physical truth, or hypothesis count as diversity;
- promise any timeline, success rate or physical accuracy;
- name a required LLM vendor or require paid services;
- add runtime code, migrations, tests or dependencies in this delivery.

**What would falsify the claim that Discovery helps.** For a given evaluated scope, the claim
"LIB with Discovery (C) discovers better than existing LIB (B)" is falsified if, under the frozen
protocol, any of the following holds:

1. C does not exceed B on the primary metric by the pre-registered minimum effect, with the
   interval excluding zero after multiplicity correction;
2. C's weighted false-discovery score is worse than B's beyond the non-inferiority margin;
3. C's diversity advantage disappears when it is counted as equivalence classes under the available
   experiments instead of raw hypotheses;
4. C fails to stop with INSUFFICIENT_VALIDATION in worlds where no mechanism can be validated more
   often than B does;
5. C's advantage depends on a budget, tool or data mismatch, which makes the comparison invalid;
6. the reproducibility re-runs of C exceed the pre-registered invalid or disagreement rate.

If the single-LLM arm A matches C within the minimum effect, the added complexity of LIB is not
justified for discovery on that scope, even if C beats B. Negative and null results are recorded
and reported to the Owner. They are not repaired by re-tuning on the same sealed cases.

## 9. Activation boundary

This candidate becomes active only through a separate, explicit sequence, none of which has
happened: an Owner decision on the candidate ([OD-01](sai35/decisions-and-review.md)), acceptance of
[ADR-0016](../adr/ADR-0016-sai35-discovery-candidate.md), a reviewed integration plan for the
unintegrated branches, an update of the SAI 3.4 activation checker's documentation boundary, and a
migration of D-NNN into the active registry with real tests. Until then no runtime code, test,
report or status may cite a D-NNN statement as an active obligation or as satisfied.
