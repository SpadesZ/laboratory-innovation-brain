# SAI 3.5 — Autonomous AI Scientist for Silicon Photonics (master specification)

Version: `3.5.0-master-candidate.3` · Date: 2026-11-04 ·
Base: `integration-integrity-accounts` @ `a38ad63a4f4ad83c895cbd1e32b2e760d878f356`

Status: **CANDIDATE — NOT ACTIVE.** Not integrated; it does not change SAI 3.4 (`3.4.0-phased.1`), SAI 3.3 or the G0–G9 acceptance gates.

`READY_FOR_REAL_RESEARCH = false` · G0 is NOT PASSED · no G-D level has been evaluated.

This master specification supersedes the discovery candidate `3.5.0-discovery-candidate.1`, which
is kept unchanged below its new header as a [historical record](SAI_3.5_Discovery_Candidate.md).
Its requirements D-001…D-046 are retired; each one is audited in the
[requirement audit](sai35/requirement-audit.md) and mapped in the
[change register](sai35/change-register.md).

## 0. Status, authority and precedence

### 0.1 What this document is

The implementation-ready master specification candidate of SiPh Lab, also called LIB (Laboratory
Innovation Brain): what the finished product is, what it must do, how each obligation is tested,
which component owns it, in which phase it is built, which gate evidences it, and what exists
today. It is written so that an implementation agent with no conversation history can build the
product from it, together with the inherited SAI 3.3 and SAI 3.4 documents.

### 0.2 What it is not

It is not active, not an Owner approval, not an implementation and not evidence that any capability
exists. [ACTIVE_SPEC.yaml](ACTIVE_SPEC.yaml) is unchanged and still names the SAI 3.4 phased basis
and the inherited SAI 3.3 executable profile. No SAI 3.3 or SAI 3.4 file, registry, milestone, test
or acceptance condition is edited; the [candidate checker](sai35/check_candidate.py) fails if one
byte of them differs from the base commit.

### 0.3 Authority and precedence

1. **Inherited obligations first.** Every obligation of [SAI 3.3](SAI_3.3.md) (P1–P28, the 60
   requirements and their tests, the HARD-LOCKs, the agent protocol AGT-001–017) and of
   [SAI 3.4](SAI_3.4.md) with its approved [candidate contract](SAI_3.4_Candidate.md)
   (ASM-001–018, G0–G9, Owner decisions D-01–D-08, security decisions A3, A9 and A12) is
   inherited unchanged. Until SAI 3.5 is activated they win on any conflict (S35-GOV-001).
2. **No newer-text-wins.** A conflict between SAI 3.5 and an inherited text, or inside SAI 3.5, is
   recorded in [open spec issues](sai35/open-spec-issues.md) and stops the affected slice
   (SAI 3.3 §0.6, AGT-015). It is never resolved by preferring the newer or more code-like text.
3. **Inside SAI 3.5.** The statements of §3 are the normative requirements. Appendices marked
   *normative* in §1 refine them (schemas, state machines, procedures, tables); a difference between
   an appendix and §3 is a spec issue. Appendices marked *informative* carry no obligation.
4. **Machine-readable registry.** [normative-statements.yaml](sai35/normative-statements.yaml) must
   agree with §3 statement by statement; the checker enforces it.
5. **Decisions stay with the Owner.** Every Owner decision OD-01…OD-18
   ([decisions](sai35/decisions-and-review.md)) is OPEN. Writing a recommendation decides nothing.

### 0.4 Reading conventions

- MUST, SHOULD and MAY keep their SAI 3.3 §0.2 meaning. Every requirement here is a MUST.
- Each requirement starts with an HTML comment `<!-- statement: key -->` followed by a bold
  `S35-<AREA>-NNN MUST`. The identifier scheme is stated in the
  [change register](sai35/change-register.md) §1; it cannot be confused with SAI 3.4's `D-01`…`D-08`.
- Each requirement ends with its acceptance test: `T-S35-<AREA>-NNN`, its kind (deterministic,
  empirical, licensed, review) and its pass condition. Every planned test is an obligation, never
  evidence: the registry holds `tests: []` for all of them.
- Status words (complete, partial, proposed, blocked, untested) are defined in
  [implementation status](sai35/implementation-status.md) §2. *Complete* means the stated acceptance
  test exists and passes; for this candidate that is true only of documentation-level requirements
  and never means that a capability is demonstrated.
- Evidence is written `<commit>:<path>`; a path without a commit prefix is on this branch.
- Owner decisions are `OD-NN`; roadmap phases are `P35-0`…`P35-9`; components are named as in the
  [architecture](sai35/architecture-end-to-end.md); spec issues are `S35-ISSUE-NN`.

### 0.5 Language

The normative text is English. A Traditional Chinese (zh-TW) normative edition is Owner decision
OD-13; until it exists, the [bilingual glossary](sai35/ux-reports-glossary.md) §3 fixes the zh-TW
term for every term used here, and the [zh-TW report](sai35/REPORT.zh-TW.md) summarizes the
candidate for the Owner without normative force.

### 0.6 Revision candidate.2

`3.5.0-master-candidate.2` revises `3.5.0-master-candidate.1` (branch
`sai-3.5-master-specification` @ `15586fc`) after the Independent Chief Auditor's CONDITIONAL PASS.
It keeps every identifier, the 77 requirements, the twelve capabilities and the architecture, and
corrects four semantic defects: pairwise indistinguishability treated as an equivalence relation
(S35-MECH-001 and its uses; new [Appendix S](sai35/mechanism-distinguishability.md)); an
outcome-dependent matched-cost rule (S35-CMP-002, [Appendix J](sai35/matched-budget-protocol.md)
§3); epistemic stages applied to every record (S35-HYP-001); and an unclear relation between
exploration, spending, admission, support, confirmation and safe stops (S35-GOV-003, S35-LIFE-002,
S35-LOOP-003, S35-SEC-001, S35-REG-003, [Appendix E](sai35/governance-security.md) §9,
[Appendix A](sai35/lifecycle.md) §3.1). Every changed statement is listed in the
[change register](sai35/change-register.md) §6 and assessed in the
[semantic consistency report](sai35/semantic-consistency-report.md). The definitions and their
counterexamples are executable in [semantic_reference.py](sai35/semantic_reference.py), which the
candidate checker runs.

### 0.6.1 Revision candidate.3

`3.5.0-master-candidate.3` corrects three findings of the Independent Chief Auditor's review of
candidate.2, again without changing any identifier: (1) the maximum-clique diversity of
S35-MECH-001 can rise when a near-duplicate is added (counterexample S1-CE-11: {0, 0.9, 1.8, 2.7}
plus 1.1 at τ = 1 goes from 2 to 3); the definition is kept and the unsupported anti-inflation
guarantees are removed; (2) S35-CMP-002, S35-COST-001 and Appendix J §3.3 now separate
pre-execution cost reservation from post-execution settlement and evaluate checkpoints
retrospectively on settled costs, so variable-cost model calls are counted at what they cost while
overspend and cross-checkpoint evidence leakage stay impossible (S2-CE-7…10); (3) S35-CMP-005,
Appendix S §6 and Appendix I §5 separate exact identification, experimentally indistinguishable
alternatives, correct abstention and independently validated new-mechanism discovery (S3-CE). See
the [change register](sai35/change-register.md) §7.

### 0.7 Two kinds of validity

*Engineering validity*: code, tests, CI, mutation batteries and record integrity show that a rule is
enforced. *Scientific validity*: an independent evaluation shows that the system finds true causes,
avoids false ones, and that its findings hold up. Engineering validity is necessary and never
sufficient. Every document and report keeps the two apart (S35-GOV-004).

## 1. Navigation map

| Appendix | Document | Authority | Holds |
|---|---|---|---|
| A | [lifecycle.md](sai35/lifecycle.md) | normative | end-to-end research lifecycle: stages, inputs, outputs, checkpoints, campaign state machine |
| B | [architecture-end-to-end.md](sai35/architecture-end-to-end.md) | normative | components and responsibility boundaries, planes, trust boundaries, reuse of existing code |
| C | [records-and-states.md](sai35/records-and-states.md) | normative | scientific records, schemas, persistent state, every state machine |
| D | [provenance-novelty-independence.md](sai35/provenance-novelty-independence.md) | normative | provenance, novelty classes and prior-art coverage, evidence independence, contamination defenses |
| E | [governance-security.md](sai35/governance-security.md) | normative | identities, human authorization, autonomy levels, research envelope, permissions, cost governance, Owner authority |
| F | [ux-reports-glossary.md](sai35/ux-reports-glossary.md) | normative | researcher experience, report structure, bilingual glossary |
| G | [deployment-autonomy.md](sai35/deployment-autonomy.md) | normative | deployment architecture, production autonomy without external coding agents and its acceptance check |
| H | [roadmap.md](sai35/roadmap.md) | normative | dependency-aware phases from the current G0 state to the complete product, gates and Owner gates |
| I | [acceptance-gd.md](sai35/acceptance-gd.md) | normative | G0–G9 and G-D relationship, G-D levels, permitted claims, scoring rules |
| J | [matched-budget-protocol.md](sai35/matched-budget-protocol.md) | normative | A/B/C comparison: arms, matching, hidden worlds, metrics, statistics, contamination, stopping |
| K | [traceability.md](sai35/traceability.md) | normative | requirement → component → test → gate → phase matrix |
| L | [implementation-status.md](sai35/implementation-status.md) | informative | per-requirement status with evidence paths and commits |
| M | [compatibility.md](sai35/compatibility.md) | normative | inherited SAI 3.3 and SAI 3.4 obligation families, what SAI 3.5 adds, no-weakening analysis |
| N | [activation-proposal.md](sai35/activation-proposal.md) | informative | the proposal for how SAI 3.5 could become the active master specification |
| O | [decisions-and-review.md](sai35/decisions-and-review.md) | informative | Owner decisions, risks, self-review, OD-10 resolution proposal |
| P | [open-spec-issues.md](sai35/open-spec-issues.md) | informative | open SAI 3.5 spec issues |
| Q | [requirement-audit.md](sai35/requirement-audit.md) | informative | individual audit of the retired D-001…D-046 |
| R | [change-register.md](sai35/change-register.md) | informative | old → new identifiers, new requirements, identifier scheme, candidate.2 revisions |
| S | [mechanism-distinguishability.md](sai35/mechanism-distinguishability.md) | normative | mechanism identity, pairwise distinguishability, certified diversity bounds, scoring and novelty against prior art, catalog adequacy, counterexamples |
| T | [semantic-consistency-report.md](sai35/semantic-consistency-report.md) | informative | requirement-by-requirement semantic consistency audit of candidate.2 |

Machine-readable and tooling: [normative-statements.yaml](sai35/normative-statements.yaml)
(normative registry), [check_candidate.py](sai35/check_candidate.py) (document checker),
[semantic_reference.py](sai35/semantic_reference.py) (executable definitions and counterexamples),
[check_sai34_boundary_without_candidate.py](sai35/check_sai34_boundary_without_candidate.py) and
[candidate-paths.txt](sai35/candidate-paths.txt) (OD-10 proposal A'). Decision records:
[ADR-0017](../adr/ADR-0017-sai35-master-specification-scope.md) (master scope and the OD-10
proposal) and [ADR-0016](../adr/ADR-0016-sai35-discovery-candidate.md) (superseded in part).
Historical: [SAI_3.5_Discovery_Candidate.md](SAI_3.5_Discovery_Candidate.md).

## 2. Vision and scientific success criteria

### 2.1 The product

SiPh Lab is an **autonomous AI scientist for silicon photonics**. Inside a research envelope the
Owner has approved, it finds research problems worth solving, proposes mechanistically distinct and
falsifiable explanations, builds and runs the physical models and experiments that tell them apart,
reframes the research when its assumptions fail, hands every conclusion to an independent
confirmation authority, and reports what it found and what it could not establish, in Traditional
Chinese and English, reproducibly. It is not a literature summarizer, a chatbot, a simulation
launcher or a hypothesis-review assistant (S35-GOV-003).

This is a target. Today none of the capabilities below is demonstrated in the product (§2.5).

### 2.2 The twelve capabilities

| ID | Capability (final target) | Counts as present only when | Requirements | Evidence gates | Demonstrated today |
|---|---|---|---|---|---|
| CAP-01 | Discover valuable research problems, anomalies, contradictions and knowledge gaps | a ResearchProblem with origin, provenance and a recorded valuation is created from canonical records without a human posing the question | S35-PROB-001, S35-PROB-002, S35-PROB-003, S35-PROB-004 | G-D1, G-D2 | no |
| CAP-02 | Generate genuinely novel, mechanistically distinguishable, falsifiable hypotheses | an admitted hypothesis has a mechanism, a typed CONTRADICTS prediction, certified distinguishability from every held mechanism under the experiment set, and a novelty class bounded by prior-art coverage | S35-HYP-002, S35-HYP-004, S35-MECH-001, S35-NOV-001, S35-NOV-002, S35-NOV-003 | G-D2, G-D3 | no |
| CAP-03 | Explore alternative physical mechanisms and expand the effective search space | after failure, residual structure or inadequacy of every held mechanism, certified-distinguishable new mechanisms are registered in a recorded order, never-considered families are listed, and no inadequate mechanism is endorsed | S35-MECH-001, S35-MECH-002 | G-D1, G-D2 | no |
| CAP-04 | Research Reframing when assumptions, observables, models or hypotheses fail | a typed, append-only Reframing with trigger and kind starts a new lineage while the full failure history stays visible and in the denominators | S35-REF-001, S35-REF-002, S35-REF-003 | G-D1, G-D2, G-D3 | no |
| CAP-05 | Independently evaluate competing explanations and select discriminating experiments | rivals are closed and evaluated by a separate Validation identity, and the next experiment maximizes class discrimination per cost | S35-SEL-001, S35-SEL-002, S35-LOOP-001 | G6, G-D1, G-D2, G-D3 | no |
| CAP-06 | Construct physical models from scratch through governed typed scientific operations | a qualified model family is built in a blank workspace from a PhysicalModelSpec by catalog operations only, with independent readback | S35-MOD-001, S35-MOD-002, S35-MOD-003 | G1, G9 | no |
| CAP-07 | Autonomously execute licensed Lumerical CHARGE, MODE, FDTD and INTERCONNECT through internal workers | a licensed run on a qualified internal worker under authorization, reservation and fencing records checkout, release and raw outputs | S35-SIM-001, S35-SIM-002, S35-SIM-003 | G2, G7-SITE, G8 | no |
| CAP-08 | Parameter sweeps, convergence studies, uncertainty analysis, model refinement and independent physical validation | registered sweeps, per-observable convergence before discrimination, per-source uncertainty, bounded refinement and independent references | S35-VAL-001, S35-VAL-002, S35-VAL-003, S35-VAL-004, S35-VAL-005 | G3, G4, G5 | no |
| CAP-09 | A continuous Discovery–Validation feedback loop with immutable evidence and independent causal confirmation | validation outcomes return as FeedbackRecords, evidence is append-only and prospective, and only the Causal Warrant Gate confirms | S35-HYP-001, S35-HYP-003, S35-LOOP-001, S35-LOOP-002, S35-LOOP-003, S35-EVI-001, S35-CWG-001, S35-CWG-002, S35-REG-001, S35-REG-004 | G6, G-D1, G-D2, G-D3, G-D4 | no |
| CAP-10 | Reproducible, traceable, bilingual (zh-TW/en) reports with explicit uncertainty and limitations | a report in both languages with parity, a re-derivable bundle, glossary terms and per-source uncertainty | S35-RPT-001, S35-RPT-002, S35-RPT-003, S35-RPT-004, S35-VAL-003 | G0, G9 | no |
| CAP-11 | The complete production research workflow without external coding agents | a deployment-equivalent run from blank workspace to report with zero coding-agent invocations, closed by a validated outcome or an explicit stop | S35-AUTO-001, S35-AUTO-002, S35-AUTO-003, S35-GOV-003, S35-LIFE-001, S35-LIFE-002, S35-LIFE-003 | G9 | no |
| CAP-12 | Project isolation, identity, permissions, safety, provenance, cost limits, Owner authority and scientific governance | least-privilege identities, project scope, envelopes and autonomy levels, Owner gates and stop, provenance and contamination defenses, realized-cost ceilings | S35-SEC-001, S35-SEC-002, S35-SEC-003, S35-SEC-004, S35-SEC-005, S35-SEC-006, S35-COST-001, S35-COST-002, S35-EVI-002, S35-EVI-003, S35-EVI-004, S35-REG-002, S35-REG-003 | G0, G8 | no |

### 2.3 Scientific success criteria

Success is claimed only per scope (benchmark or case set, model family, product commit, model
identifiers, environment) and only at the level an independent party has verified.

| Level of success | Requires | Then one may say (scope only) |
|---|---|---|
| Specified | this candidate reviewed by the Independent Chief Auditor | "Discovery is specified and under development." |
| Engineered | the requirement's acceptance tests pass in CI on the integration line | "The rule is enforced in software." Engineering validity only |
| Research workflow accepted | SAI 3.4 G0 accepted by the Owner after independent audit | "The governed real-model research workflow is accepted for this configuration." Not discovery |
| Discovery shown in synthetic worlds | G-D1 PASS by the independent evaluator on evaluator-generated hidden worlds | the G-D1 sentence of [acceptance-gd.md](sai35/acceptance-gd.md) §3; never "discovers real physics" |
| Retrospective literature discovery | G-D2 PASS | the G-D2 sentence; not prospective, not physically true |
| Prospective simulation discovery | G-D3 PASS, with G1, G2, G3, G7-SITE and licensed G8 for the model family | the G-D3 sentence; not physical discovery |
| **Final product target for a scope** | G-D4 PASS for the scope; G0–G9 accepted for the configuration and model family; arm C beats arm B and is not matched by arm A under [the protocol](sai35/matched-budget-protocol.md); the Owner accepts readiness | "It prospectively proposed a mechanism that independent physical experiments confirmed through the Causal Warrant Gate." `READY_FOR_REAL_RESEARCH` changes only by Owner decision |

A single finding is scientifically acceptable only when it is a stage-3 claim confirmed by the
Causal Warrant Gate (S35-CWG-001), with its novelty class bounded by prior-art coverage
(S35-NOV-001, S35-NOV-002), per-source uncertainty (S35-VAL-003), independent physical validation if
it is a physical claim (S35-VAL-005), and a reproducible bundle (S35-RPT-002).

### 2.4 Non-goals

SAI 3.5 does not claim that the system can discover anything today; set `READY_FOR_REAL_RESEARCH`
to true; pass G0 or any of G0–G9; activate itself; replace an Owner gate, a signed review or the
Causal Warrant Gate with automation; treat simulation agreement as physical truth or hypothesis
count as diversity; promise a timeline, success rate or accuracy; require a named LLM vendor or a
paid service; or add runtime code, migrations, tests or dependencies in this delivery.

### 2.5 Where things stand (2026-11-04)

G0 is NOT PASSED. The SAI 3.4 integration line (`a38ad63`) holds the governed research workflow, the
Causal Warrant Gate V1.1, accounts and a deterministic Lumerical mock. The unintegrated G0 line
(`f41758c`) adds prospective-evidence rules, signed verification authorizations, local-endpoint
metering and blind-evaluation tooling; the forged-authorization read-path bypass an auditor found
there is fixed on the unmerged branch `g0-authorization-read-path-closure`, pending independent
audit. The unintegrated discovery line (`118a4ac`) holds an offline Discovery Loop prototype whose
synthetic result (0.89 correct outcomes for the discovery arm) is engineering evidence only: the
worlds share an author with the engine, its baseline B0 is a deterministic stand-in rather than an
LLM, and its B1 re-implements the loop policy rather than running the real LIB. A protocol and
tooling for an independent hidden-world evaluation are on `discovery-independent-evaluation` @ `d7ec9f2` (pushed, not reviewed); its
offline results are again same-author engineering evidence, and they show the discovery arm
force-fitting when the true mechanism family is missing from its vocabulary (0.40 force-fit at
budget 12) and spending about four times the realized cost of B1. No
licensed simulation, model construction or physical validation exists.

Engineering branches of 2026-11-04 (pushed, unmerged, not independently reviewed):
`claude/lib-implementation-agent-47evs0-g0` @ `47451e1` (from `367163b`) re-checks every SUPPORTS a
stored belief decision counted, closing a second forged-authorization path through the belief
projection, and records an open, higher-severity finding (the services' database role can register
transition policies) that needs an Owner privilege decision; G0 stays NOT PASSED.
`claude/lib-implementation-agent-47evs0-discovery` @ `0928602` (from `d7ec9f2`) adds an offline
adequacy-before-endorsement safety gate over the frozen Discovery engine (S35-MECH-002 as revised):
on the same-author held-out worlds the force-fit rate falls from 0.40 to 0.046 at budget 12 and from
0.47 to 0.026 at budget 24, at the cost of in-catalog accuracy at budget 12 (0.908 to 0.637). Both
are engineering evidence only.

Second round (2026-11-04 to 2026-11-08, pushed, unmerged, not independently reviewed):
`claude/lib-implementation-agent-47evs0-g0-f2` @ `24fae8b` (from `47451e1`) closes finding F2 with
owner-only TransitionPolicy registration (approved by the Owner on 2026-11-04): the services' role
loses write privileges on `transition_policies` and migration `011x` refuses any non-owner insert;
G0 stays NOT PASSED. `claude/lib-implementation-agent-47evs0-discovery-v11` @ `aa05dfd` (from
`0928602`, design frozen at `53bd2a9`) closes a refit coverage bypass found in v1.0 and adds
pre-registered per-experiment checks; on newly generated held-out worlds force-fits are 4/195 at
budget 12 (v1.0: 6) with correct in-catalog identifications 156/240 (v1.0: 160), both differences
inside their intervals; equal caps, not matched realized cost. Details:
[implementation status](sai35/implementation-status.md).

## 3. Normative requirements

The 77 requirements below are grouped in 21 areas. Each names its acceptance test; the
[traceability matrix](sai35/traceability.md) gives its owner component, gates, phase and status, and
[compatibility.md](sai35/compatibility.md) its inherited links.

### 3.1 Governance of this specification (GOV)

<!-- statement: gov.precedence -->
**S35-GOV-001 MUST** — SAI 3.5 inherits every SAI 3.3 obligation (P1–P28, the 60 requirements and
their tests, the HARD-LOCKs) and every SAI 3.4 obligation (ASM-001–018, G0–G9, Owner decisions
D-01–D-08, security decisions A3, A9 and A12) unchanged. Until SAI 3.5 is activated, the inherited
text wins on any conflict. No S35 statement may weaken, replace, reinterpret or reorder an inherited
MUST, gate or Owner gate. A conflict found later is recorded as an S35 spec issue in
open-spec-issues.md and stops the affected slice (AGT-015); it is never resolved by assuming that
the newer text wins. *Acceptance (T-S35-GOV-001, deterministic):* the candidate checker proves every
SAI 3.3/3.4 file and ACTIVE_SPEC.yaml byte-identical to a38ad63 with no exception and rejects a
one-byte mutation; compatibility.md lists every inherited obligation family with a no-weakening
verdict; every recorded conflict has an open spec issue.

<!-- statement: gov.product_target -->
**S35-GOV-002 MUST** — The product target of SiPh Lab (LIB) is an autonomous AI scientist for
silicon photonics with the twelve capabilities CAP-01 to CAP-12 of §2, each defined operationally by
the S35 requirements it lists and evidenced only by the gates it names. This is a target, not a
description of the current system: no capability may be described as present beyond the evidence
recorded in implementation-status.md. *Acceptance (T-S35-GOV-002, deterministic):* the checker finds
all twelve capability rows in §2, each naming at least one registered requirement and at least one
gate, and the registry's capability list matches; the claim audit of S35-GOV-004 finds no capability
described as present without an evidence path.

<!-- statement: gov.product_category -->
**S35-GOV-003 MUST** — LIB is a research agent, not a literature summarizer, chatbot, simulation
launcher or hypothesis-review assistant. A campaign is a completed experimental campaign only when
the system has itself selected, registered and run at least one discriminating test and the campaign
ends in a validated outcome state (a claim CONFIRMED through the Causal Warrant Gate, or a
hypothesis CONTRADICTED or INCONCLUSIVE under a registered test). A campaign that ends in an
explicit INSUFFICIENT_VALIDATION or STOPPED record, including one stopped safely before any
experiment ran, is a valid operational termination but not a completed experimental campaign, and it
is never a discovery; a scientifically accepted discovery further needs a stage-3 claim under
S35-CWG-001 and S35-CWG-002 and the conditions of §2.3. A workflow that ends at a summary, an
answer, a launched run or a list of hypotheses for a human to review does not meet the product
target. *Acceptance (T-S35-GOV-003, empirical):* on the frozen G9 and G-D1 case sets, every campaign
is classified on the three termination dimensions of lifecycle.md §3.1; every campaign counted as
completed carries at least one registered test the system selected and ran and ends in a validated
outcome state; a campaign stopped before any experiment is counted as a valid operational
termination with experimental completion NOT_PERFORMED and never as completed or as a discovery; a
campaign that ends with only a summary, an answer, a launched run or an unreviewed hypothesis list
is scored as not meeting the target.

<!-- statement: gov.claim_discipline -->
**S35-GOV-004 MUST** — No document, interface, report, status file or release note may claim a
capability beyond verified evidence: an evidence path at a named commit and, for discovery
capability, the highest G-D level an independent evaluator has passed for the stated scope.
Engineering results (tests, CI, mutation batteries, deterministic or synthetic benchmarks) are
reported as engineering validity and never as scientific validity; success on a synthetic benchmark
is never reported as validation of real discovery. *Acceptance (T-S35-GOV-004, deterministic):* the
candidate checker rejects its listed forbidden claims (readiness set to true, G0 marked as passed,
SAI 3.5 marked as active) in every SAI 3.5 document; before activation, a claim audit of UI strings,
reports and status files lists every capability statement with its evidence path and G-D level and
finds none without.

<!-- statement: gov.not_active -->
**S35-GOV-005 MUST** — SAI 3.5 is CANDIDATE — NOT ACTIVE until an Independent Chief Auditor has
reviewed it and the Owner has explicitly approved its activation (OD-16) by the steps of
activation-proposal.md. Until then ACTIVE_SPEC.yaml, the SAI 3.3 executable profile and the SAI 3.4
phased registry stay unchanged, and no runtime code, test, report or status may cite an S35
requirement as an active obligation or as satisfied. *Acceptance (T-S35-GOV-005, deterministic):*
the checker verifies registry status CANDIDATE and activation_status NOT_ACTIVE, the master status
line, the ACTIVE_SPEC.yaml values and hash, and that no S35 identifier appears in src/, tests/,
docs/normative_statements.yaml or docs/milestones.yaml.

### 3.2 Research lifecycle (LIFE)

<!-- statement: life.persisted_stages -->
**S35-LIFE-001 MUST** — Every campaign persists, for every lifecycle stage of lifecycle.md, its
versioned inputs, outputs, governance decisions and a restartable checkpoint. Each output is bound
to project, campaign, episode, trace, content hash, schema version and producer (component, version
and identity). The cheapest sufficient path is chosen: a stage may be skipped only with a recorded
reason, and a restart resumes from the last committed checkpoint without repeating a side effect.
*Acceptance (T-S35-LIFE-001, deterministic):* a fault-injection test stops the orchestrator after
each stage's commit and restarts it; the campaign resumes at the next stage, no side effect repeats,
and every output row carries every binding field; a skipped stage without a reason is refused.

<!-- statement: life.campaign_states -->
**S35-LIFE-002 MUST** — A campaign has exactly the states and transitions of the campaign state
machine of lifecycle.md: DRAFT, SCOPED, RUNNING, the waiting states, REPORTING and the three closed
states CLOSED_CONCLUDED, CLOSED_INSUFFICIENT_VALIDATION and CLOSED_STOPPED. A campaign contains SAI
3.3 research episodes and does not replace the §12.1 episode state machine. Any other transition is
refused and logged. Every closed campaign records three separate dimensions of lifecycle.md §3.1:
operational termination (VALID or INVALID), experimental completion (NOT_PERFORMED, PARTIAL or
COMPLETED) and scientific acceptance (NONE, PENDING_CAUSAL_WARRANT_GATE or ACCEPTED_DISCOVERY); no
value of one dimension implies a value of another. *Acceptance (T-S35-LIFE-002, deterministic):* a
table-driven test attempts every (state, event) pair; exactly the listed transitions succeed and
every refusal is logged with its reason; episodes inside a campaign still follow §12.1; a campaign
closed CLOSED_STOPPED before any registered test records VALID, NOT_PERFORMED and NONE;
CLOSED_CONCLUDED without a validated outcome is refused.

<!-- statement: life.termination -->
**S35-LIFE-003 MUST** — Every campaign runs under explicit budgets (tokens, compute, money,
experiments, licensed seat time, wall time and reframings) and a versioned stopping policy fixed
before it starts. It always terminates and records its termination reason. Budget exhaustion,
stagnation or distinguishability that stays UNRESOLVED ends it as CLOSED_INSUFFICIENT_VALIDATION or
CLOSED_STOPPED; neither is ever reported as a discovery. *Acceptance (T-S35-LIFE-003,
deterministic):* a property test over randomized campaigns with finite budgets shows every run
terminating within its caps with a recorded reason; a campaign closed by exhaustion is never
rendered or exported as a finding.

### 3.3 Problem discovery (PROB)

<!-- statement: prob.research_problem -->
**S35-PROB-001 MUST** — Problem Discovery produces ResearchProblem records. Each records its origin
(ANOMALY, CONTRADICTION, KNOWLEDGE_GAP, FAILED_HYPOTHESIS, VALIDATION_RESIDUAL, LITERATURE_GAP or
OWNER_QUESTION), links the records behind it by id and hash, and carries provenance (S35-EVI-002). A
problem may consume resources beyond the zero-cost tier only inside an active ResearchEnvelope that
covers it (S35-REG-002) or after an active human project member accepts it; spending money or using
a license still needs the Owner gates of S35-SEC-002, which a member's acceptance never gives.
Problem discovery never sends non-PUBLIC material past the egress gate. *Acceptance (T-S35-PROB-001,
deterministic):* a ResearchProblem without origin, source links or provenance is refused; a problem
outside every envelope and not accepted cannot reserve non-zero budget; a problem accepted by a
member without a covering envelope or Owner gate cannot reserve money or license budget; an egress
audit shows no INTERNAL-labelled source in any outbound query.

<!-- statement: prob.valuation -->
**S35-PROB-002 MUST** — Problem Discovery ranks candidate problems by a recorded ProblemValuation
over the versioned criteria of records-and-states.md: decision relevance (which belief or design
choice the answer can change), discriminability with the available experiments, expected cost,
weight of unexplained evidence, and novelty potential bounded by prior-art coverage. The ranking is
deterministic for identical inputs and policy version. A model's opinion may be one recorded input
but never the ranking itself. *Acceptance (T-S35-PROB-002, deterministic):* identical inputs and
policy version give an identical ranking; a valuation missing a criterion or its rationale is
refused; inverting the model-opinion input changes at most that criterion's score, never the
ordering rule.

<!-- statement: prob.anomaly_registry -->
**S35-PROB-003 MUST** — Unexplained observations are kept in an anomaly registry with the explicit,
append-only states of records-and-states.md: UNEXPLAINED, UNDER_INVESTIGATION, ACCOMMODATED,
PROVISIONALLY_EXPLAINED, EXPLAINED, ATTRIBUTED_TO_NOISE, ARTIFACT, UNRESOLVED_INSUFFICIENT and
WITHDRAWN. An anomaly is never deleted and never silently dropped from a report. Every state change
records its trigger, evidence references and the actor or policy. ACCOMMODATED and
PROVISIONALLY_EXPLAINED are never displayed as explained, and EXPLAINED requires a Causal Warrant
Gate confirmation. *Acceptance (T-S35-PROB-003, deterministic):* a transition-table test lets only
the listed transitions succeed; the database refuses UPDATE and DELETE on anomaly rows; a campaign
report lists every anomaly with its current state; EXPLAINED without a Causal Warrant Gate decision
reference is refused.

<!-- statement: prob.contradictions_gaps -->
**S35-PROB-004 MUST** — Problem Discovery detects contradictions and knowledge gaps from canonical
records. A contradiction is a typed SAI 3.3 Conflict (EPI-006) between admitted evidence, or between
admitted evidence and an admitted prediction, under comparable conditions. A knowledge gap is a
recorded absence: an UNKNOWN or NOT_REPORTED field that blocks a decision, an untested prediction of
a live hypothesis, or a prior-art area the coverage record marks as not searched. Each detected
contradiction or gap is recorded with its basis and may originate a ResearchProblem. *Acceptance
(T-S35-PROB-004, deterministic):* fixtures with two condition-compatible contradicting observations
yield one Conflict and one CONTRADICTION problem; condition-incompatible ones yield none (P4); a
blocking UNKNOWN field yields a KNOWLEDGE_GAP problem citing the field.

### 3.4 Hypotheses and epistemic stages (HYP)

<!-- statement: hyp.epistemic_stages -->
**S35-HYP-001 MUST** — Hypotheses and scientific claims, and only they, carry one of three epistemic
stages: (1) exploratory idea, any proposed hypothesis or claim not yet admitted; (2) testable
hypothesis, admitted under the SAI 3.3 §8 Hypothesis Admission Gate with its mechanism identity and
distinguishability verdicts recorded (S35-MECH-001); (3) evidence-supported conclusion, a claim
CONFIRMED through the Causal Warrant Gate that still re-derives. ResearchProblem, Observation,
Anomaly, ExperimentSet, Registration, Run, PhysicalModelSpec and every other record keep their own
schemas and state machines of records-and-states.md and carry no epistemic stage; a stage never sets
or replaces their states, and their states never imply a stage. Discovery may propose but never
confirm: no Discovery component writes stage 3. A stage-1 idea is never the subject of a budget
reservation for a test, never shown as a hypothesis or a finding, and never evidence; the model
calls that generate or screen ideas are charged to the generating activity under its own
authorization (AL2 at zero cost, AL3 within the envelope's ceilings, or an Owner gate), and that
authorization admits nothing (governance-security.md §9). *Acceptance (T-S35-HYP-001,
deterministic):* static and contract tests show Discovery identities have no write path to CONFIRMED
or to Causal Warrant Gate tables; every rendered hypothesis and claim shows its stage and no other
record type renders one; a record of another type submitted with a stage field is refused; a budget
reservation for a test that names a stage-1 idea is refused, while an authorized idea-generation
call is charged and its output stays stage 1; a stage-3 label without a re-derivable Causal Warrant
Gate decision is refused on read.

<!-- statement: hyp.testable_mechanistic -->
**S35-HYP-002 MUST** — A hypothesis is admitted (stage 2) only with a stated physical or
measurement-chain mechanism, assumptions, confounders, a minimal test and at least one typed
Prediction bound to a declared OutcomeSpace version that carries a CONTRADICTS effect over an
observable some available or Owner-approvable experiment can measure (SAI 3.3 §8 and §17.5.1). It is
called falsifiable only under those conditions, and mechanistically distinct only when it is
certified DISTINGUISHABLE under S35-MECH-001 from every held hypothesis; otherwise it is recorded
with its verdicts against each held hypothesis it is not certified distinguishable from, and as an
alias when its mechanism identity equals one already held. *Acceptance (T-S35-HYP-002,
deterministic):* admission refuses a hypothesis lacking any listed field, a prediction not bound to
a declared OutcomeSpace, or one with no CONTRADICTS effect; a renamed duplicate (identical
forward-model identity) is recorded as an alias, never as a new mechanism; a hypothesis that is not
certified distinguishable from a held one is never reported as mechanistically distinct.

<!-- statement: hyp.claim_states -->
**S35-HYP-003 MUST** — Every discovery claim carries a claim state from the transition table of
records-and-states.md: PROPOSED, ADMITTED, REGISTERED, UNDER_TEST, SUPPORTED, CHALLENGED,
CONTRADICTED, INCONCLUSIVE, CONFIRMED, INSUFFICIENT_VALIDATION, STOPPED and WITHDRAWN, with REFRAMED
as an annotation. The state is a projection derived from canonical records (admission,
registrations, BeliefRevisionEvents, Causal Warrant Gate decisions and governance outcomes); it
never writes a belief state, and it maps onto, without replacing, the SAI 3.3 §8.2 lifecycle. Only
the listed transitions are allowed. *Acceptance (T-S35-HYP-003, deterministic):* replaying the
canonical event log reproduces every projected state; each forbidden transition of the table is
attempted and refused; deleting the projection and rebuilding it gives identical states.

<!-- statement: hyp.generation -->
**S35-HYP-004 MUST** — The Hypothesis Brain generates exploratory ideas and candidate mechanisms
through ScientificLLM and ModelRouter only, from a canonical EvidenceBundle, with
InferenceProvenance on every output. It may draw on the domain mechanism catalog, literature,
anomalies, residuals and reframing records, and it may propose mechanisms absent from the catalog
when they come with typed predictions. Its outputs are stage-1 proposals: they never set a state,
never count as evidence (P3), and are generated without access to sealed references, holdouts or
evaluation truth. *Acceptance (T-S35-HYP-004, deterministic):* the model-call wrapper refuses a call
without a bundle hash; every idea row carries InferenceProvenance; a static and database test proves
the Hypothesis Brain identity cannot read sealed tables; an idea without typed predictions cannot be
submitted for admission.

### 3.5 Mechanism space (MECH)

<!-- statement: mech.distinguishable_classes -->
**S35-MECH-001 MUST** — Mechanism identity, distinguishability and diversity follow
mechanism-distinguishability.md. A mechanism's identity is the content hash of its canonical
forward-model declaration, never its name; equal identities are aliases. For every pair of held
hypotheses the Mechanism Explorer computes, under the experiment set E available to the campaign at
its declared replicates and noise model, a certified interval for the worst-case joint separation
over both parameter domains, and records one verdict against the pre-registered threshold:
DISTINGUISHABLE, INDISTINGUISHABLE or UNRESOLVED. Pairwise indistinguishability is not an
equivalence relation: no count, score, novelty decision or refutation may merge pairs transitively.
Mechanism diversity is never a raw count of hypotheses: it is the largest number of held hypotheses
that are pairwise certified DISTINGUISHABLE under E, reported as a lower bound with UNRESOLVED pairs
treated as not distinguishable and, while any pair is UNRESOLVED, with an upper bound beside it.
This figure is invariant under aliases, never decreases when a mechanism is added, rises by at most
one per added mechanism and never exceeds the packing bound of the predictions' span under E; it is
not invariant under near-duplicates, which can raise it (counterexample S1-CE-11), so it describes
the spread of the held set and is never by itself evidence of discovery ability or of distinct
mechanism families. The verdicts are deterministic, versioned and recomputed whenever E, the
threshold, the replicates or a parameter domain changes; every reported figure names the version of
E and lists the aliases and UNRESOLVED pairs. *Acceptance (T-S35-MECH-001, deterministic):* the
counterexamples S1-CE-1 to S1-CE-11 of mechanism-distinguishability.md hold, including A = 0, B =
0.75 and C = 1.50 at threshold 1 giving A/B and B/C INDISTINGUISHABLE, A/C DISTINGUISHABLE and
diversity 2 (neither 1 nor 3), and {0, 0.9, 1.8, 2.7} at threshold 1 giving diversity 2 that rises
to 3 when the near-duplicate 1.1 is added; adding fifty aliases leaves the diversity unchanged;
adding one mechanism raises it by at most one; no document or report claims near-duplicate
invariance; a transitive merge or connected-component count is rejected; identical inputs give
identical verdicts; changing E recomputes them; the report generator refuses a diversity figure
without an E version.

<!-- statement: mech.search_space_expansion -->
**S35-MECH-002 MUST** — When every live hypothesis fails, when a tested anomaly persists, when
validation leaves residual structure, or when no held mechanism is adequate, the Mechanism Explorer
expands the effective search space in a recorded order: measurement-chain mechanisms, regime
variants of declared mechanisms, compositions, extended declared mechanisms, and new mechanisms
proposed by the Hypothesis Brain (S35-HYP-004). It adds only candidates that the admitted data do
not already refute and that are certified DISTINGUISHABLE from every held mechanism. Before any held
mechanism is endorsed, each is tested for adequacy against the admitted data by the pre-registered
criterion of mechanism-distinguishability.md §8 relative to the noise model, never by its rank among
the held mechanisms; when none is adequate, the system records an UNEXPLAINED anomaly and the
catalog's incompleteness and may only abstain, expand, reframe, request an experiment that
discriminates the held mechanisms from "none is adequate", or stop, and a larger budget never
relaxes the criterion. The record states the search space before and after, the mechanism families
never considered, and that a truth outside every considered family can only be reported as
unexplained. *Acceptance (T-S35-MECH-002, deterministic and empirical):* deterministic: on a world
whose truth is a composition or lies outside the initial prior, expansion registers it when
certified distinguishable and lists the never-considered families otherwise; on a world whose true
family is absent from the catalog no held mechanism is endorsed at any budget, the anomaly is
recorded, and the outcome is an abstention, a stage-1 proposal, a reframing, a
discriminating-experiment request or a stop; empirical: in G-D1 hidden worlds of those kinds, arm
C's true-cause discovery and its force-fit rate (endorsing an inadequate held mechanism) are
reported per world kind and per budget.

### 3.6 Research Reframing (REF)

<!-- statement: ref.triggers_and_kinds -->
**S35-REF-001 MUST** — Research Reframing is triggered when an assumption, an observable, a model or
a hypothesis fails: every live hypothesis is contradicted, a tested anomaly persists, an assumption
is shown false, an observable cannot discriminate, or a model fails qualification or validation.
Each reframing has one kind from records-and-states.md (QUESTION_ASSUMPTION, CHANGE_OBSERVABLE,
CORRECT_MODEL, QUESTION_MEASUREMENT_CHAIN, WIDEN_MECHANISM_SPACE, NARROW_SCOPE or STOP_INSUFFICIENT)
and states its trigger, what changes and why. *Acceptance (T-S35-REF-001, deterministic):* a fixture
for each trigger produces a Reframing of an allowed kind citing the trigger record; a Reframing
without trigger, kind or rationale is refused.

<!-- statement: ref.failure_history -->
**S35-REF-002 MUST** — A Reframing record is append-only and links every failed or inconclusive
hypothesis, anomaly, assumption, observable, model and earlier problem that led to it. Reframing
never deletes, edits or hides failure history. It cannot turn failure into support: earlier
hypotheses keep their last belief state, and evidence that failed them cannot be reinterpreted as
support for them or for a successor. *Acceptance (T-S35-REF-002, deterministic):* the database
refuses UPDATE and DELETE on reframing and failure records; after a reframing every failed
hypothesis is still listed with its last state in the report; a SUPPORTS relation from evidence that
contradicted the predecessor to the successor is refused.

<!-- statement: ref.accounting -->
**S35-REF-003 MUST** — A reframed hypothesis is a new hypothesis with its own lineage, marked as
proposed after the failure, and it needs a new prospective registration (S35-REG-001); evidence
available when it was proposed cannot support it. Every reframing and every abandoned branch stays
in the denominators of the discovery metrics. Reframings per problem and per campaign are capped by
a versioned policy (OD-12) and by the budget. *Acceptance (T-S35-REF-003, deterministic):* the
successor's lineage names its predecessor and the reframing; pre-existing evidence is stored as
CITES; the metric computation counts abandoned branches; reaching the cap ends further reframing
with STOP_INSUFFICIENT.

### 3.7 Competing explanations and experiment selection (SEL)

<!-- statement: sel.discrimination_per_cost -->
**S35-SEL-001 MUST** — The Verification Planner selects experiments that discriminate among the
surviving held mechanisms per unit of cost: it prefers the experiment that converts the most
surviving pairs from not certified distinguishable to DISTINGUISHABLE
(mechanism-distinguishability.md §5), weighted as the versioned policy states, for the lowest
CostVector, using SAI 3.3 §9 sufficiency and a versioned deterministic SelectionPolicy. Uncalibrated
expected-information-gain numbers are not used (SAI 3.3 §9.2). An experiment that needs money, a
license, a physical experiment or publication is proposed and runs only after its gate (S35-SEC-002,
S35-REG-002). *Acceptance (T-S35-SEL-001, deterministic):* identical inputs and policy give an
identical ranked plan; an experiment that converts no surviving pair is never ranked above one that
does at equal cost; a gated experiment is never dispatched before its authorization record exists.

<!-- statement: sel.competing_explanations -->
**S35-SEL-002 MUST** — Competing explanations are evaluated independently of the component that
generated them. Before any claim leaves the Discovery side, the Validation Loop evaluates every live
explanation against the same admitted evidence with the same pre-registered rule, registers every
declared rival of no greater complexity that the data do not refute and that is not certified
INDISTINGUISHABLE from the candidate (rival closure), and discriminates it too. A refutation is
never applied to a hypothesis while a hypothesis that is not certified distinguishable from it
survives the same evidence. A claim reports every held hypothesis that is not certified
distinguishable from it, with its verdict, and what cannot be excluded; this neighbourhood is not an
equivalence class. *Acceptance (T-S35-SEL-002, deterministic):* with a declared but unregistered
rival, no claim is handed over until the rival is registered and discriminated; a pair that is not
certified distinguishable is reported together and neither member is refuted alone; in the A–B–C
chain of mechanism-distinguishability.md §1 a claim for B lists A and C and a claim for A lists B
only; the evaluation runs under a Validation identity distinct from the generator's.

### 3.8 Physical model construction (MOD)

<!-- statement: mod.from_scratch -->
**S35-MOD-001 MUST** — The Physical Model Builder constructs physical models from scratch in a blank
workspace from a versioned, unit-checked PhysicalModelSpec (ASM-004): geometry, materials, doping,
contacts and boundaries, meshes, solver settings and observables. No hidden prebuilt project is
reused as if it were new, and no unknown or contradictory parameter is filled with a solver default;
a missing authoritative parameter is UNKNOWN and blocks construction or creates a ReviewItem.
*Acceptance (T-S35-MOD-001, deterministic, then licensed):* offline, a fixed spec yields a typed
operation plan whose readback double matches the spec within tolerance, a spec with a missing
required field is refused, and the before and after workspace inventories show no prebuilt project;
licensed (G1), the same on a qualified worker.

<!-- statement: mod.typed_operations -->
**S35-MOD-002 MUST** — Model construction uses only the closed, versioned catalog of governed typed
scientific operations of a reviewed deterministic constructor (ASM-005): region, material, contact,
doping, solver, mesh and monitor operations with typed parameters. No model-generated code, script,
shell or free-form solver command runs. A new operation enters the catalog only through normal
software review and a new catalog version, never at run time. Every build produces a BuildManifest
and an independent readback comparison. *Acceptance (T-S35-MOD-002, deterministic):* a static test
proves no operation accepts free text that reaches the solver; a plan naming an operation absent
from the pinned catalog version is refused; every BuildManifest carries the spec hash, operation DAG
hash, catalog version and readback result.

<!-- statement: mod.qualification -->
**S35-MOD-003 MUST** — Model Qualification qualifies each model family (DomainPack payload version,
constructor version and solver product) before its outputs may discriminate between mechanisms:
analytical limits, manufactured or conservation cases, readback and units round-trip, each with a
recorded scope. Outputs of an unqualified or out-of-scope model family are recorded as exploratory
runs (a run label, not an epistemic stage); they cannot move a claim beyond stage 2 or count in the
discovery metrics. *Acceptance (T-S35-MOD-003, deterministic):* a run under a model family without
an in-scope qualification record is admitted only as an exploratory run; qualification evidence
names its cases and scope; a new constructor version invalidates the qualification.

### 3.9 Licensed simulation on internal workers (SIM)

<!-- statement: sim.licensed_internal -->
**S35-SIM-001 MUST** — Licensed Lumerical CHARGE, MODE, FDTD and INTERCONNECT run only on internal,
qualified workers owned by the deployment, through a dedicated provider behind the SimulationBackend
seam. Execution is license-governed (actual entitlement checkout and release are recorded; a missing
or mismatched license blocks the run), Owner-authorized (only under an Owner authorization or a
ResearchEnvelope naming product, scope, seat-time ceiling and period) and cost-governed (budget
reserved before execution, every attempt reconciled). A mock never stands in for a licensed run, and
no external agent operates a solver. *Acceptance (T-S35-SIM-001, deterministic offline, then
licensed):* offline, a run request without authorization, budget reservation or qualified worker is
refused before any side effect, and the mock provider can never serve a run marked licensed;
licensed (G2), every attempt record carries checkout and release, exit status, logs and output
arrays.

<!-- statement: sim.per_product_qualification -->
**S35-SIM-002 MUST** — Each licensed product (CHARGE, MODE, FDTD, INTERCONNECT) and each worker is
qualified separately: installation, SDK compatibility, design-environment license, solve and HPC
entitlements, and the OS and version matrix. Qualifying one product or worker never qualifies
another, and a coupling of products is qualified as a coupling (ASM-015). *Acceptance
(T-S35-SIM-002, deterministic and licensed):* the capability registry refuses to dispatch a product
whose qualification record is missing for the worker; a CHARGE qualification does not enable MODE;
licensed qualification runs are recorded per product and worker.

<!-- statement: sim.worker_contract -->
**S35-SIM-003 MUST** — A simulator worker accepts only a typed operation plan or SimulationRequest
bound to a Job, a registration id (S35-REG-001) and a fencing token, runs it in an isolated per-job
workspace under a non-human worker service identity, and returns raw artifacts, readback and attempt
records only, never a verdict or a belief move. Heartbeats, fencing and timeouts apply; a stale
worker cannot write back; an undeterminable outcome is UNKNOWN and is reconciled before any retry
(ASM-005, ASM-007). *Acceptance (T-S35-SIM-003, deterministic):* fault injection with a fake worker
yields one accepted result for duplicate and late callbacks; a request without registration id or
valid fencing token is refused; the worker identity has no write access to belief, warrant or
registration tables.

### 3.10 Sweeps, convergence, uncertainty, refinement and physical validation (VAL)

<!-- statement: val.sweeps -->
**S35-VAL-001 MUST** — A parameter sweep is registered before it runs: parameters, ranges, sampling,
observables, stopping rule and budget. Each sweep point is its own Run with lineage to the spec and
the sweep plan. Sweep outputs are model outputs under stated conditions and are never presented as
measurements. *Acceptance (T-S35-VAL-001, deterministic):* a sweep without a registered plan is
refused; every point Run references the plan; the report labels sweep outputs as simulated under
their conditions.

<!-- statement: val.convergence -->
**S35-VAL-002 MUST** — A simulated observable may discriminate between mechanisms only after the
numerical convergence study required by ASM-008 has passed for that observable: frozen residual and
conservation checks, at least three comparable mesh or step levels, and domain-size studies. A
solver's converged flag is not enough. Non-asymptotic, oscillating or multi-branch results are
UNKNOWN or FAIL and cannot discriminate. *Acceptance (T-S35-VAL-002, deterministic offline, then
licensed):* a discrimination step citing an observable without a passed convergence record is
refused; manufactured non-monotone sequences yield UNKNOWN; licensed (G3), convergence evidence
exists per observable.

<!-- statement: val.uncertainty -->
**S35-VAL-003 MUST** — Every claim reports its uncertainty separately by source: numerical, input
parameters, measurement or reference, model form, extraction and mapping. Sources are combined only
when their independence assumptions hold; otherwise covariance or conservative bounds are kept.
Belief stays ordinal (SAI 3.3 §8.1) until calibration exists; an uncalibrated number is never shown
as the probability that a claim is true, and unknown uncertainty is shown as UNKNOWN. *Acceptance
(T-S35-VAL-003, deterministic):* a claim payload missing a source field is refused (UNKNOWN is
allowed); the renderer never prints a probability for an uncalibrated belief; a combination without
its recorded independence assumption is refused.

<!-- statement: val.bounded_refinement -->
**S35-VAL-004 MUST** — Model refinement stays within ASM-011: pre-approved assumptions, parameter
ranges, development data and budget, producing immutable child versions, with every validation
re-run for the child. Refinement may not quietly change the hypothesis under test to improve the
fit: a change of physical mechanism is a new hypothesis with its own lineage, admission and
registration, and a correction of model form is classified MODEL_CORRECTION (S35-NOV-002).
*Acceptance (T-S35-VAL-004, deterministic):* a ModelPatch outside the approved fields or ranges is
refused before any side effect; a patch classified as a mechanism change creates a new hypothesis
instead of a child version; a child inherits no PASS from its parent.

<!-- statement: val.physical_validation -->
**S35-VAL-005 MUST** — A physical claim needs independent physical validation (ASM-009, ASM-010):
reference data independent of the construction and calibration sources, with measurement
uncertainty, under comparable conditions, scored by a process the builder does not control.
Agreement between simulations, or a plausible trend, never validates a physical claim on its own.
*Acceptance (T-S35-VAL-005, deterministic split checks, empirical acceptance):* the split manifest
proves the holdout disjoint from construction and calibration families; a claim citing only
simulation agreement cannot reach stage 3; G4 and G5 evidence exists per observable.

### 3.11 Discovery–Validation feedback loop (LOOP)

<!-- statement: loop.propose_never_confirm -->
**S35-LOOP-001 MUST** — Discovery and validation are separate roles with separate service identities
and permissions. The Discovery side (Problem Discovery, Hypothesis Brain, Mechanism Explorer,
Research Reframing) proposes: it cannot write validation verdicts, belief states or confirmations,
cannot change validators, protocols, tolerances or scoring, and cannot read sealed references,
holdouts, ground truth or scoring credentials. The Validation side does not generate the hypotheses
it validates. A component that has seen a sealed answer no longer counts as independent for that
case. *Acceptance (T-S35-LOOP-001, deterministic):* a permission-matrix test runs every Discovery
identity against every validation, belief, warrant and sealed table and expects refusal; a
validation run whose identity authored the hypothesis is refused.

<!-- statement: loop.feedback -->
**S35-LOOP-002 MUST** — Every validation outcome feeds back to Discovery as an append-only
FeedbackRecord within the same campaign: the outcome and its state, refutation bases, anomalies
created or changed, failed assumptions, unconverged or unqualified observables, and the residual
structure left after the best surviving fit. Discovery reads validation results only through these
records, and each FeedbackRecord is consumed by Problem Discovery, the Mechanism Explorer or
Research Reframing with a recorded disposition. *Acceptance (T-S35-LOOP-002, deterministic):* after
each validation outcome a FeedbackRecord exists; each record has a disposition before the campaign
may close; a residual above the pre-registered threshold yields a VALIDATION_RESIDUAL problem or a
reframing.

<!-- statement: loop.stop_insufficient -->
**S35-LOOP-003 MUST** — The system must be able to stop. When validation is insufficient, the
outcome is an explicit INSUFFICIENT_VALIDATION or STOPPED record with its reason, what was tried,
what it cost and what would be needed to continue. Such an outcome is a valid operational
termination and a success of governance, not a failure of the system; it is not a completed
experimental campaign unless S35-GOV-003 holds, and it is never a discovery. It is scored as a
correct abstention, reported separately from identification, where no held mechanism can be
validated with the available means, and a stop made before any experiment is reported with
experimental completion NOT_PERFORMED. A confident claim where a stop was warranted is a false
discovery. *Acceptance (T-S35-LOOP-003, deterministic and empirical):* deterministic: a campaign
that cannot discriminate within budget ends with a StopRecord carrying all four fields; a campaign
stopped before any experiment is reported as VALID, NOT_PERFORMED and NONE and is never rendered as
a finding; empirical: in G-D1 no-mechanism worlds a correct stop is scored correct and a confident
claim is scored a false discovery.

### 3.12 Confirmation authority (CWG)

<!-- statement: cwg.exclusive_confirmation -->
**S35-CWG-001 MUST** — The existing Causal Warrant Gate (V1.1) is the exclusive confirmation
authority: it is the only path to CONFIRMED and to stage 3. No other component, including Discovery,
the Validation Loop, the report generator or an evaluator, writes or displays CONFIRMED except as a
projection of a re-derivable Causal Warrant Gate decision. SAI 3.5 adds no shortcut, no automatic
warrant and no widening of DISCRIMINATION review or multi-cause confirmation (SAI 3.4 D-03 stays
open), and it does not enable SP 1.1.0. A numerical match, a reproduced trend or model agreement
never upgrades a claim by itself. *Acceptance (T-S35-CWG-001, deterministic):* a database and static
test proves no writer other than the gate's path can produce CONFIRMED; a CONFIRMED projection whose
decision fails re-derivation is withdrawn on read; every discovery hand-over carries the status
PENDING_CAUSAL_WARRANT_GATE.

<!-- statement: cwg.consequential_authorization -->
**S35-CWG-002 MUST** — A consequential conclusion (a CONFIRMED claim, any claim released outside the
project, and any claim used to justify a physical experiment, fabrication or publication) requires
independent human authorization: the Causal Warrant Gate's signed review by an enrolled reviewer who
is not the campaign's runner, not an author of the hypothesis and not a second account of either,
plus the Owner gate for the action. No ResearchEnvelope, autonomy level, automation or timeout
provides this authorization. *Acceptance (T-S35-CWG-002, deterministic):* a confirmation signed
under the enrolment of the hypothesis author, the runner or a second account of either is refused; a
release or physical-experiment request citing a claim without a qualifying signed review is refused;
the presence of an envelope changes neither result.

### 3.13 Prospective registration and the research envelope (REG)

<!-- statement: reg.prospective -->
**S35-REG-001 MUST** — Every validation test is registered prospectively, before its data exists. A
Registration names the hypothesis, the predictions, the capability and its declaration hash, the
analysis-plan hash and the decision rule. It is dated by the database clock, immutable and bound to
exactly one Job, and it carries either a signed human authorization or a reference to a
ResearchEnvelope that covers it (S35-REG-002). A change after registration is a new registration;
the old one and its outcome stay on record. *Acceptance (T-S35-REG-001, deterministic):* a Job
running a validation without a registration is refused; UPDATE of a registration is refused; a
client-supplied timestamp is ignored; one registration binds one Job only; a registration with
neither a valid signed authorization nor a covering envelope is refused.

<!-- statement: reg.envelope_registration -->
**S35-REG-002 MUST** — Inside an active ResearchEnvelope the system may create a Registration
without a per-registration human action. A ResearchEnvelope is an Owner-approved record signed by an
enrolled authorizer (scope RESEARCH_ENVELOPE), unexpired and unrevoked, with machine-checkable
bounds: project, problem scope, mechanism families, capabilities and their declaration hashes, model
routes, licensed products and seat-time ceilings, money and compute ceilings, maximum registrations
and reframings, autonomy level and validity period. An automatic registration is valid only if every
bound holds at registration time; otherwise a signed per-registration human authorization is
required. Physical experiments, fabrication, publication, irreversible actions, non-PUBLIC egress
and changes to validators, protocols or policies are never inside an envelope. *Acceptance
(T-S35-REG-002, deterministic):* for each bound, a registration just outside it is refused and one
inside it is accepted; an expired, revoked, unsigned or wrongly scoped envelope covers nothing; an
envelope naming a physical-experiment, fabrication or publication capability is refused at creation.

<!-- statement: reg.envelope_limits -->
**S35-REG-003 MUST** — Automatic registration never weakens the independent authorization of
consequential conclusions. An envelope authorizes registration and execution only: it never
authorizes CONFIRMED, a signed review, a warrant, a release or a belief move, and evidence gathered
under it passes every admission and prospective-evidence rule unchanged (S35-REG-004). A
ResearchEnvelope never replaces an individual signed authorization that an inherited rule requires.
Whether an envelope registration satisfies a rule that requires a per-hypothesis human
pre-authorization (rule (l) of migration 011s with the 011w signatures on the G0 line) is Owner
decision OD-14; until it is decided it does not, and such evidence is recorded as CITES for those
hypotheses. *Acceptance (T-S35-REG-003, deterministic):* a CONFIRMED path that cites only an
envelope authorization is refused; for a post-screening hypothesis, a SUPPORTS relation whose only
authorization is an envelope registration is stored as CITES while OD-14 is open.

<!-- statement: reg.no_retrospective_support -->
**S35-REG-004 MUST** — There is no retrospective self-support. Evidence that existed before a
hypothesis was registered, evidence the hypothesis was derived from, evidence with an unknown
capture time, and evidence whose lineage reaches any of these cannot support that hypothesis; it is
recorded as context (CITES), never as SUPPORTS. These rules are at least as strict as the
prospective-evidence rules of migrations 011p and 011s (rules (a)–(k)) on the G0 line at f41758c:
known capture time, clean lineage to depth 16, declared capability kind and fail-closed
classification. *Acceptance (T-S35-REG-004, deterministic):* the eleven 011s defect fixtures
(unknown capture time, lineage to screening output, cycles, depth over 16, misdeclared kind) applied
to discovery hypotheses are all stored as CITES; a hypothesis registered after an observation cannot
cite it as support.

### 3.14 Novelty and prior art (NOV)

<!-- statement: nov.prior_art_bound -->
**S35-NOV-001 MUST** — A novelty claim is bounded by prior-art coverage. It cites a
PriorArtSearchRecord (SAI 3.3 §17.20, SRC-003) recording the sources actually searched, queries,
date range, coverage classes (at least literature and patents unless OD-11 decides otherwise) and
limitations. Internal novelty is never presented as global novelty, a claim is never broader than
its coverage record supports, and the record states each model's training cutoff against the
prior-art dates it relies on. *Acceptance (T-S35-NOV-001, deterministic):* a novelty status without
a covering record is refused; a record without coverage classes or limitations is refused; the
report prints the coverage scope next to every novelty statement.

<!-- statement: nov.classification -->
**S35-NOV-002 MUST** — Every finding carries one novelty class assigned by the Novelty Auditor with
the criteria of provenance-novelty-independence.md: KNOWN_MECHANISM_REDISCOVERY (the mechanism has
the identity of, or is certified INDISTINGUISHABLE under S35-MECH-001 from, a mechanism in covered
prior art), ENGINEERING_OPTIMIZATION (a better design or operating point within known mechanisms,
with no mechanism claim), MODEL_CORRECTION (a change of model form or parameters that removes a
residual under known physics) or NEW_PHYSICAL_KNOWLEDGE (a mechanism certified DISTINGUISHABLE from
every mechanism in covered prior art, or a quantitative relation absent from it); a mechanism
UNRESOLVED against a prior-art mechanism is at most a candidate with those pairs listed.
NEW_PHYSICAL_KNOWLEDGE may be asserted only for a stage-3 claim with independent physical validation
(S35-VAL-005); before that the strongest label is NEW_PHYSICAL_KNOWLEDGE_CANDIDATE, shown with its
stage. *Acceptance (T-S35-NOV-002, deterministic and blinded review):* deterministic: a
NEW_PHYSICAL_KNOWLEDGE label without stage 3, S35-VAL-005 evidence and a covering prior-art record
is refused; a renamed prior-art mechanism is classed KNOWN_MECHANISM_REDISCOVERY; empirical (G-D2
and above): blinded reviewers' class assignments are compared with the auditor's and the agreement
is reported.

<!-- statement: nov.literature -->
**S35-NOV-003 MUST** — Autonomous literature search runs only through ExternalSourceAdapter
providers the project has authorized. A query leaves the deployment only when declared PUBLIC. Every
retrieved passage is pinned by version and hash and carries its license class; read, execute, modify
and redistribute rights are judged separately (ASM-003). A search records what was actually
searched, not what was configured, and an unreachable provider appears in the record's limitations.
*Acceptance (T-S35-NOV-003, deterministic):* a non-PUBLIC query is refused before egress; every
passage row has version, hash and license class; a provider outage appears in the limitations of the
search record.

### 3.15 Evidence, provenance, independence and contamination (EVI)

<!-- statement: evi.proposals_not_evidence -->
**S35-EVI-001 MUST** — Discovery outputs are proposals, not evidence. They enter the scientific
record only through the existing Artifact, Observation and Attestation admission path (ASM-012),
keeping Run, validity, conditions, uncertainty, source dependence and model-family identity.
Scientific records are append-only; corrections and withdrawals are new events that leave the
original in place. *Acceptance (T-S35-EVI-001, deterministic):* a discovery output submitted as an
Observation without a Run or Artifact reference is refused (EVI-009); UPDATE and DELETE on
scientific records are refused; a withdrawal leaves the original readable.

<!-- statement: evi.provenance -->
**S35-EVI-002 MUST** — Every discovery record (problem, valuation, anomaly state change, idea,
distinguishability graph, adequacy assessment, reframing, registration, envelope, selection
decision, feedback, stop and novelty assessment) carries provenance: inputs by hash, the producing
component, version and identity, InferenceProvenance for every model call, the policy versions in
force, and the trace. A record without provenance cannot justify a later transition. *Acceptance
(T-S35-EVI-002, deterministic):* inserting any listed record type without a provenance field is
refused; a transition citing a record that lacks provenance is refused.

<!-- statement: evi.independence -->
**S35-EVI-003 MUST** — Evidence independence for discovery claims follows SAI 3.3 claim identity and
SAI 3.4 source families: observations sharing a source work, a source family, a device or process
batch, a model family or shared modeling assumptions count once; repeated runs, mesh levels and
sweep points of one model never increase the count of independent evidence; DEPENDENCE_UNKNOWN
counts zero. Evidence produced by the campaign that generated the hypothesis counts as independent
only if it was registered before it existed (S35-REG-001) and its lineage is clean (S35-REG-004).
*Acceptance (T-S35-EVI-003, deterministic):* three runs of one model, a preprint and its journal
version, and two solvers sharing one material model each yield an independent count of one; an
unknown dependence yields zero.

<!-- statement: evi.contamination -->
**S35-EVI-004 MUST** — The deployment defends against contamination in research, not only in
evaluation: sealed references, holdouts and evaluation truth live in the evaluation plane and are
unreadable by Discovery and Validation identities; every read of sealed material is audited; a
component or model route that has seen a sealed answer is marked non-independent for that case;
novelty and rediscovery claims about literature record the model training cutoff and a
memorization-probe result; a detected contamination is reported and never silently dropped.
*Acceptance (T-S35-EVI-004, deterministic):* every non-evaluation identity is refused on sealed
tables and each refusal is logged; a case whose answer was read by a route marks that route
non-independent in the case record; a literature novelty claim without cutoff and probe fields is
refused.

### 3.16 Reports and researcher experience (RPT)

<!-- statement: rpt.bilingual_traceable -->
**S35-RPT-001 MUST** — Every campaign report is traceable and bilingual (zh-TW and en) under
ASM-016. Beyond the eight ASM-016 content classes (hypotheses, predictions, observations,
interpretations, uncertainty, conclusions, limitations, exports), it covers the problem and its
provenance, the epistemic stage of every hypothesis and claim and the state of every other record,
the distinguishability verdicts and certified diversity bounds with their experiment-set version,
anomalies and their states, the reframing history including failed hypotheses, the registrations and
envelopes used, every validation outcome, the novelty class with its coverage scope, realized cost,
every stop reason and the three termination dimensions. Both languages carry the same identifiers,
numbers, units, states and uncertainty; a translation never overwrites a canonical record.
*Acceptance (T-S35-RPT-001, deterministic and bilingual review):* a structural parity test over both
languages and every export format finds every applicable field present with equal identifiers,
numbers, units and states; canonical hashes are unchanged after rendering; an independent bilingual
reviewer checks semantic parity on the frozen case set.

<!-- statement: rpt.reproducible_bundle -->
**S35-RPT-002 MUST** — Every report ships with a machine-verifiable bundle: canonical record
identifiers and hashes for every statement, the environment manifest (commit, schema, packages,
model identifiers and digests, solver versions), the policy versions, registrations, budgets and
realized consumption, so that an independent party can re-derive every state and re-score every
metric from the bundle without access to the original session. *Acceptance (T-S35-RPT-002,
deterministic):* re-deriving every claim state and metric from the bundle in a clean environment
reproduces the report's values; a bundle missing any listed element fails validation.

<!-- statement: rpt.terminology_language -->
**S35-RPT-003 MUST** — Scientific and governance terms in reports, interfaces and messages use the
bilingual glossary of ux-reports-glossary.md: each English term has exactly one canonical zh-TW
term, and state names and identifiers are never translated. The normative text of this specification
is English; a zh-TW normative edition is Owner decision OD-13 and, if approved, is checked term by
term against the glossary. User-facing error text still comes from the versioned MessageCatalog
(UX-006). *Acceptance (T-S35-RPT-003, deterministic):* a glossary lint over the MessageCatalog and
report templates finds every glossary term rendered with its canonical zh-TW term and every state
name untranslated; no English term in the glossary has two zh-TW terms.

<!-- statement: rpt.researcher_ux -->
**S35-RPT-004 MUST** — The researcher workspace shows, for every campaign and in both languages, the
epistemic stage of each hypothesis and claim, the state of every other record, open anomalies,
pending registrations and authorizations, budgets with realized consumption, the active envelope and
autonomy level, and every stop reason. No step that has not passed is shown as verified or green;
UNKNOWN, NOT_PERFORMED and INSUFFICIENT_VALIDATION are shown as such; every authorization a
researcher gives is a recorded ReviewItem resolution with actor and time. *Acceptance
(T-S35-RPT-004, deterministic):* UI tests in both locales show each listed element; a fixture with
an unperformed simulation renders NOT_PERFORMED, never a success style; every approve action creates
a ReviewItem resolution event.

### 3.17 Production autonomy without external coding agents (AUTO)

<!-- statement: auto.no_external_coding_agent -->
**S35-AUTO-001 MUST** — The complete production research workflow runs without external coding
agents: production research must not depend on Codex, Claude Code or any other external coding
agent. No stage hands work to such an agent, edits the repository, runs generated code, or waits for
a developer to write model code. Governed model calls through ScientificLLM and ModelRouter are
allowed under the egress, sensitivity and budget gates; they return typed proposals only, with no
shell, raw SDK, arbitrary code or deployment rights. *Acceptance (T-S35-AUTO-001, empirical
acceptance check):* in a deployment-equivalent environment where coding-agent executables are absent
and their network endpoints are blocked, the full workflow runs from a blank workspace to a
bilingual report on the frozen in-envelope cases (before licensing without licensed simulation;
under G9 with it); process, network and repository audit logs show zero coding-agent invocations;
every attempt to reach one is refused and logged; every human intervention is a recorded ReviewItem.
The procedure is deployment-autonomy.md §4.

<!-- statement: auto.deployment_composition -->
**S35-AUTO-002 MUST** — A production deployment contains no coding-agent executable, session,
personal developer login, credential or network route, and no path by which a research stage can
modify the deployed code or configuration. Development tools exist only in the development plane.
Each release records an image inventory and an egress allowlist from which this can be audited.
*Acceptance (T-S35-AUTO-002, deterministic):* a static audit of each release image and egress
allowlist finds no coding-agent binary, package, credential, configuration directory or endpoint
from the maintained denylist, and no writable path from research services to code or configuration;
the audit report is attached to the release.

<!-- statement: auto.out_of_envelope_stop -->
**S35-AUTO-003 MUST** — A request outside the versioned capability envelope (ASM-001) or outside the
active ResearchEnvelope stops safely: the campaign records what is out of scope and creates a
ReviewItem with the exact gap and at most two options. It never asks for a coding agent or a
developer to continue, and it never widens its own envelope. *Acceptance (T-S35-AUTO-003,
deterministic):* out-of-envelope fixtures (unknown model family, unqualified product, exceeded
bound) each produce a stop and a ReviewItem with the gap and options; no outbound connection to a
development endpoint occurs; no envelope row changes.

### 3.18 Identity, permissions, autonomy levels and Owner authority (SEC)

<!-- statement: sec.autonomy_levels -->
**S35-SEC-001 MUST** — Autonomy is set per project by the autonomy levels of governance-security.md:
AL0 manual, AL1 propose-only (the default without an envelope), AL2 envelope-autonomous at zero
cost, AL3 envelope-autonomous with budgeted model and compute use, and AL4 envelope-autonomous with
licensed simulation on qualified workers. The level is a bound of the active ResearchEnvelope and
never exceeds the maximum the Owner set for the project (OD-15). No level covers physical
experiments, fabrication, publication, CONFIRMED, or changes to validators, protocols, thresholds or
policies. A level authorizes actions and spending only: an action it permits, such as an AL3 model
call, admits no hypothesis, creates no evidence and moves no belief; admission, registration,
support and confirmation each need their own record and authority (governance-security.md §9).
*Acceptance (T-S35-SEC-001, deterministic):* for each level, an action of the next level is refused
and an action of the level is permitted; without an envelope only AL1 actions are permitted; an
envelope above the project maximum is refused at creation; an AL3 idea-generation call within the
ceiling is permitted and its output stays stage 1 with no SUPPORTS relation.

<!-- statement: sec.owner_gates -->
**S35-SEC-002 MUST** — Four classes of action need a recorded Owner gate before they happen:
spending money (paid models, paid compute, purchases), using licenses (Lumerical products, seats,
entitlements), physical experiments (fabrication, measurement, lab time) and publication (any
external release of findings, data or claims). An Owner-signed ResearchEnvelope may pre-authorize
money and license use within its ceilings; physical experiments and publication are authorized per
action. Every authorization names actor, time, scope, ceiling and expiry; automation never signs for
the Owner, and a timeout is never consent. *Acceptance (T-S35-SEC-002, deterministic):* each action
class without a covering authorization is refused before any side effect; an expired authorization
covers nothing; a physical-experiment or publication request citing only an envelope is refused.

<!-- statement: sec.project_isolation -->
**S35-SEC-003 MUST** — Discovery records, envelopes, registrations, benchmark material, worker
sessions, caches and evaluator access are scoped to a project and to the reader's current clearance.
A record from another project is never reused without a project occurrence. Sealed evaluation
material is reachable only by the evaluation plane. *Acceptance (T-S35-SEC-003, deterministic):* the
route and repository access matrix extended to discovery records refuses every cross-project read
and write; every worker cache key includes the project id; sealed reads from non-evaluation
identities are refused.

<!-- statement: sec.identity -->
**S35-SEC-004 MUST** — Human account roles stay ADMIN and MEMBER. Project membership, independent
scientific reviewer authorization, independent evaluator assignment, envelope-authorizer enrolment
and worker service identity are separate governance concepts and grant no account role. A second
account of the same natural person never counts as an independent reviewer or evaluator. The SAI 3.4
security decisions A3, A9 and A12 stay open and are not settled here. *Acceptance (T-S35-SEC-004,
deterministic):* the account model admits only ADMIN and MEMBER; granting reviewer, evaluator or
authorizer status changes no account role; enrolment refuses a key already enrolled to another
person.

<!-- statement: sec.least_privilege -->
**S35-SEC-005 MUST** — Every component acts under its own service identity with the least privilege
of the permission matrix in governance-security.md, which is the authority for which identity may
read or write which record class. Database rules hold the matrix for every normal writer;
application checks do not replace them. A change to the matrix needs an ADR and an Owner-visible
ReviewItem. *Acceptance (T-S35-SEC-005, deterministic):* a generated test enumerates every
(identity, record class, operation) cell and expects exactly the matrix's allow or deny at the
database layer, using non-superuser roles.

<!-- statement: sec.owner_stop -->
**S35-SEC-006 MUST** — The Owner can stop any campaign and revoke any envelope or authorization at
any time. A stop or revocation takes effect before the next side effect of every affected Job (it is
checked at reservation and at dispatch); running work is cancelled under ASM-007 with its costs
kept; and the campaign closes as CLOSED_STOPPED with the stop recorded. *Acceptance (T-S35-SEC-006,
deterministic):* after a revocation every subsequent reservation and dispatch under the envelope is
refused; a running fake job is cancelled and its partial cost recorded; the campaign state becomes
CLOSED_STOPPED.

### 3.19 Cost governance (COST)

<!-- statement: cost.realized_consumption -->
**S35-COST-001 MUST** — Every model call, compute use, licensed run and experiment reserves its
maximum cost before its side effect (pre-execution reservation) and records its actual realized
consumption afterwards (post-execution settlement, never above the reservation without an overrun
incident) (tokens, compute seconds, money, seat time, wall time), including failures, retries and
parsing repairs. Realized consumption is reconciled against reservations per campaign and per
envelope and reported with every result. No endpoint, local or remote, is presumed free: a free
declaration is an Owner act for one exact model at one endpoint (rule 011v of the G0 line).
*Acceptance (T-S35-COST-001, deterministic):* a call without a reservation is refused before
sending; ledger totals equal the sum of attempt records including failures; a settlement above its
reservation is recorded as an overrun incident; a request to an undeclared local endpoint is refused
unsent; a wildcard free declaration is refused.

<!-- statement: cost.ceilings -->
**S35-COST-002 MUST** — Campaigns and envelopes have money, token, compute, seat-time and wall-time
ceilings. Reaching a ceiling stops further reservations and closes or pauses the campaign with the
reason; it never triggers an automatic increase. Raising a ceiling is an Owner authorization through
the approval path of SAI 3.3 requirement COST-001 and never happens by timeout. *Acceptance
(T-S35-COST-002, deterministic):* at the ceiling the next reservation is refused and the campaign
records the stop; a ceiling change without an Owner authorization record is refused.

### 3.20 G-D acceptance (GD)

<!-- statement: gd.independence -->
**S35-GD-001 MUST** — G-D acceptance is independent of G0–G9: completing G0–G9 never implies
successful autonomous discovery. A G-D level passes only when an independent evaluator, assigned by
the Owner and neither the implementer nor a second account of the implementer, issues the verdict on
that level's frozen protocol; the system, its developers and any development agent cannot issue a
G-D verdict. Synthetic benchmark success is never reported as real discovery validation. *Acceptance
(T-S35-GD-001, deterministic):* every G-D verdict record names an evaluator outside the implementer
list and a frozen protocol hash; the claim audit rejects any document stating a G-D result without a
signed verdict.

<!-- statement: gd.levels -->
**S35-GD-002 MUST** — G-D has five levels, G-D0 to G-D4, defined in acceptance-gd.md, each with
entry conditions, required evidence and pass and fail criteria frozen before evaluation. Passing a
lower level never implies a higher one. A level's result applies only to the scope it was evaluated
in (benchmark, model family, product commit, model identifiers and environment). *Acceptance
(T-S35-GD-002, deterministic):* each verdict record names its level, scope and frozen protocol hash;
a protocol changed after freezing makes the verdict INVALID.

<!-- statement: gd.no_substitution -->
**S35-GD-003 MUST** — G-D and G0–G9 do not substitute for each other in either direction. No G-D
result passes any G gate. G-D2 needs G0 accepted for the product configuration it evaluates; G-D3
needs, for its model family, G1, G2, G3, G7-SITE and the licensed parts of G8; G-D4 additionally
needs G4, G5 and G6 for its scope. A run before its prerequisites is exploratory and cannot be
signed as a G-D pass. *Acceptance (T-S35-GD-003, deterministic):* a G-D verdict record without its
prerequisite gate records is refused; no G gate record may cite a G-D verdict as evidence.

### 3.21 Matched-budget comparison (CMP)

<!-- statement: cmp.three_arms -->
**S35-CMP-001 MUST** — Every G-D1 to G-D4 evaluation compares three arms on the same cases: (A)
single frontier LLM, one model driven by a frozen minimal prompt-and-tool loop without LIB's
governance, debate, planner or Discovery Loop; (B) existing LIB workflow, the frozen product
research workflow with the Discovery Loop off; (C) LIB with Discovery, arm B plus the Discovery
Loop. In the primary comparison arm A and every LIB model slot use the same model: in a zero-cost
stage it is the strongest local model the Owner approved (OD-04), and a frontier model is used only
in an Owner-authorized paid stage (OD-05). All arms return the same answer schema, including the
option to stop with INSUFFICIENT_VALIDATION. *Acceptance (T-S35-CMP-001, deterministic):* the frozen
arm configurations differ only in the listed components; their model identifiers and digests are
equal; every case output of every arm validates against the one answer schema.

<!-- statement: cmp.matching -->
**S35-CMP-002 MUST** — The arms are matched on model versions (identifier, digest and decoding
settings); on information exposure (the same corpus snapshot, case material, tool descriptions and
experiment catalog, no arm sees sealed truth, and prompts and tool outputs are logged for audit); on
experimental conditions (the same cost table, simulator access, time limit, seeds per case and
environment manifest); and on resources, by actual realized consumption, not only by caps. Every arm
runs under the same caps. The primary analysis scores every arm at the realized-cost checkpoints of
matched-budget-protocol.md §3.3, frozen before any arm runs and independent of outcomes: every
atomic operation (model call, tool call, experiment, retry, repair or failure) reserves its maximum
cost before it starts and may start only if that reservation fits under the cap, and settles its
realized cost after it ends; checkpoints are evaluated retrospectively on settled costs, with every
operation started before an answer charged in full and an unsettled operation charged its
reservation; an arm's answer at a checkpoint is the last answer it committed while its cumulative
settled charge was within the checkpoint, so an atomic operation that straddles a checkpoint
supplies nothing to it; and an arm's answer depends only on its own trace, so early stopping cannot
move the comparison point. A case whose consumption records are incomplete, unreconciled or not
comparable within the frozen tolerance, or in which an operation started without reservation
headroom or settled above its reservation, is COST_UNMATCHED; it stays in the denominator, scored
against the arm whose records are deficient, and a comparison with more such cases than the frozen
limit cannot support a claim that one arm is better at equal budget. Matching at the smallest final
realized consumption among the arms, or by any rule chosen after execution, is only a labelled
secondary sensitivity analysis. *Acceptance (T-S35-CMP-002, deterministic):* the evaluation harness
refuses to score an arm whose manifest differs from another's in a matched field; realized
consumption per case and arm is recorded including failures, retries and model calls; the
counterexamples S2-CE-1 to S2-CE-10 of matched-budget-protocol.md §3.6 hold (an early-stopping arm
does not move the comparison point, a straddling experiment is excluded at its checkpoint, a
variable-cost call is counted at its settled cost, an unsettled call at its reservation, and an
unreconciled ledger, unequal caps, missing reservation headroom, an overrun or a post-hoc checkpoint
yield COST_UNMATCHED or a refusal); every secondary matching is labelled secondary.

<!-- statement: cmp.blinding -->
**S35-CMP-003 MUST** — Scoring is blinded. The evaluator is not the implementer. Arm identities are
replaced by sealed labels held by a custodian until scoring is complete. The scorer is deterministic
and hash-frozen. Human judgments, such as novelty class and falsifiability at G-D2 and above, come
from at least two independent blinded domain reviewers, with their agreement reported and a
pre-registered adjudication rule. *Acceptance (T-S35-CMP-003, deterministic):* the scorer's hash
equals the frozen hash; outputs shown to reviewers carry sealed labels only; the custodian's key is
unsealed only after every score is recorded.

<!-- statement: cmp.hidden_worlds -->
**S35-CMP-004 MUST** — The benchmark is frozen and sealed by the independent evaluator before any
arm runs. Synthetic worlds come from a hidden-world generator owned and seeded by the evaluator
after the freeze, which the implementers cannot read; worlds written by the implementer of the
system under test are development material only and never G-D evidence. The benchmark includes
worlds with hidden true mechanisms, observationally equivalent rivals, compositions,
measurement-chain confounds, anomalies and noise, and worlds where no mechanism can be validated;
later strata are held-out literature cases and physical cases. Every case stays in the denominator.
*Acceptance (T-S35-CMP-004, deterministic):* the G-D0 package holds generator commitments and seeds
drawn after the freeze; the implementer access log shows no read of generator parameters or truth;
the case-list hash is unchanged at scoring.

<!-- statement: cmp.metrics -->
**S35-CMP-005 MUST** — Five metrics are reported for every arm, each with definition, unit, n and
interval: (1) true-cause discovery, reported as separate outcome rates at the primary checkpoint and
never merged: exact identification (the true mechanism's identity), experimentally indistinguishable
alternative (another identity certified INDISTINGUISHABLE from it under the case's full experiment
set), unresolved alternative (never credited), correct abstention (no claim where no held mechanism
was acceptable), false null, force-fit, other wrong claims, and independently validated
new-mechanism discovery (a mechanism outside the catalog at case start that matches the truth and
passed a prospectively registered test the arm did not control), while an exploratory proposal that
was not so validated is counted only as a proposal; (2) effective mechanism diversity, the certified
lower and upper bounds of S35-MECH-001 under the case's experiment set, never raw hypothesis counts
or transitive class counts; (3) discriminating-experiment efficiency, experiments and realized cost
until no held mechanism certified distinguishable from the true one survives, censored at the
budget; (4) false discoveries, the false-discovery rate at SUPPORTED or higher plus a weighted score
in which confident wrong claims weigh more; (5) independent reproducibility, the share of a
pre-registered subset that the evaluator reproduces in a fresh environment from the frozen manifest,
where any manifest drift makes the re-run invalid. Exactly one primary metric is pre-registered, and
no outcome category is folded into another to form it. *Acceptance (T-S35-CMP-005, deterministic):*
the scorer computes all five metrics from the frozen outputs; the outcome counterexamples S3-CE of
mechanism-distinguishability.md §9 are classified as stated, including an indistinguishable
alternative never counted as an exact identification and an unvalidated proposal never counted as a
discovery; recomputation from the bundle gives identical numbers; a report missing a metric, its n
or its interval is rejected.

<!-- statement: cmp.statistics -->
**S35-CMP-006 MUST** — Statistics are pre-registered before unsealing: the experimental unit (case),
paired comparisons across arms on the same cases, interval methods, the minimum effect of interest,
non-inferiority margins, multiplicity correction across metrics and comparisons, sample size with
its justification, and any interim analysis with its error-spending rule. There is no optional
stopping, no cherry-picked seed and no post-hoc exclusion. *Acceptance (T-S35-CMP-006,
deterministic):* the frozen protocol contains every listed element; the analysis code reads only the
frozen values; an exclusion not produced by a pre-registered rule invalidates the run.

<!-- statement: cmp.contamination -->
**S35-CMP-007 MUST** — Contamination controls are frozen with the protocol: model training cutoff
against case resolution dates, overlap checks of case material against development data and public
corpora, memorization probes, fresh synthetic seeds generated after the freeze, and a pre-registered
rule for contaminated cases decided before unsealing. A contamination finding is reported and never
silently dropped. *Acceptance (T-S35-CMP-007, deterministic):* the G-D0 package contains the
contamination report; every excluded case names the rule that excluded it; the report lists every
finding.

<!-- statement: cmp.stopping -->
**S35-CMP-008 MUST** — Stopping rules are frozen with the protocol. A case ends on budget
exhaustion, time limit, or the arm's own STOPPED or INSUFFICIENT_VALIDATION outcome, and the answers
the arm held at the frozen realized-cost checkpoints (S35-CMP-002) are scored. A study ends at its
pre-registered n, at a pre-registered interim boundary, or on a governance incident (any arm
breaching egress, budget or isolation), which invalidates the affected runs. A paid stage ends at
the Owner's ceiling and is reported as partial. *Acceptance (T-S35-CMP-008, deterministic):* an
operation whose reservation does not fit under the remaining cap is refused before it starts; a case
reaching the cap is scored on the answers it held, an operation straddling a checkpoint supplies
nothing to it, and the case is scored; an incident marks the affected runs INVALID; a paid stage at
its ceiling is labelled partial.

<!-- statement: cmp.zero_cost_first -->
**S35-CMP-009 MUST** — A zero-cost first stage comes before any paid stage: local models declared
free under the spend administration, and offline hidden synthetic worlds, with no paid API, no
license and no physical experiment. Its result is reported to the Owner whatever it shows. A paid,
licensed or physical stage starts only after an Owner authorization with a ceiling (S35-SEC-002),
and a negative zero-cost result is not overridden by running a bigger model on the same sealed
cases. *Acceptance (T-S35-CMP-009, deterministic):* the paid-stage harness refuses to start without
the zero-cost report reference and an Owner authorization; re-running sealed cases with another
model is refused.

## 4. What would falsify "Discovery helps"

For an evaluated scope, the claim "LIB with Discovery (C) discovers better than the existing LIB
workflow (B)" is falsified if, under the frozen protocol, any of the following holds:

1. C does not exceed B on the primary metric by the pre-registered minimum effect, with the interval
   excluding zero after multiplicity correction;
2. C's weighted false-discovery score is worse than B's beyond the non-inferiority margin;
3. C's diversity advantage disappears when counted as certified diversity (S35-MECH-001) instead of hypotheses;
4. C stops correctly in no-mechanism worlds less often than B;
5. C's advantage disappears at the frozen realized-cost checkpoints, holds only under a secondary matching, or depends on a tool, data or
   information-exposure mismatch (the comparison is then COST_UNMATCHED or INVALID);
6. C's independent reproducibility re-runs exceed the pre-registered invalid or disagreement rate.

If the single frontier LLM arm (A) matches C within the minimum effect, the added complexity of LIB
is not justified for discovery on that scope, even if C beats B. Negative and null results are
recorded and reported to the Owner; they are never repaired by re-tuning on the same sealed cases.

## 5. Activation boundary

SAI 3.5 stays CANDIDATE — NOT ACTIVE (S35-GOV-005). It may become the primary active master
specification only after an Independent Chief Auditor review and explicit Owner approval (OD-16),
by the steps and the checker and registry changes listed in the
[activation proposal](sai35/activation-proposal.md). Until then no runtime code, test, report or
status may cite an S35 requirement as an active obligation or as satisfied.
