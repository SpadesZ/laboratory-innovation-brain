# M0a Spec Coverage Audit — §23.5 (2)

Date: 2026-09-13 (rev 6)
Spec: SAI 3.3, amendments `v3.3-a1` … `v3.3-a7`
Milestone: **M0a — Scientific Identity Core**
Scope: **§6–§16**, as §23.5 defines a coverage audit

> **This document is rebuilt, not appended to.** Five rounds of corrections had left it narrating
> its own history, with superseded totals sitting beside current ones. Every number below is
> computed from `docs/normative_statements.yaml`,
> `docs/spec_coverage_audit/M0a_hard_must_counts.yaml` and
> `docs/spec_coverage_audit/M0a_obligation_inventory.yaml` by the same code the tests run, so there
> is exactly one set of figures and it is the live one.

## 1. What this audit is, and what it is not

§23.5 asks two different questions and only one of them is machine-checkable.

| | Question | Answered by |
|---|---|---|
| **(1)** | Does every Requirement ID have a test, and does every normative statement have an owner? | `T-SPEC-001` / `T-SPEC-002`, on every CI run |
| **(2)** | Has a human read §6–§16 and confirmed nothing normative is unaccounted for? | **this document**, plus the 148 rows of data it is generated from |

Part (2) is a human gate. What the harness can do is make the gate's *arithmetic* impossible to get
wrong silently, which is what five rounds of review pushed it to do. What it cannot do is decide
whether a sentence is an obligation. That judgement, and the sign-off, stay human.

## 2. The counting rule

One formula, applied to every section without exception:

```
delta = hard_must - (registry_live_must + registry_deferred_must)

  registry_live_must      entries for the section with level MUST and no deferred_rationale
  registry_deferred_must  entries with level MUST and a deferred_rationale, counted ONCE as
                          deferred and never also as covered
  SHOULD entries          excluded entirely from hard-MUST coverage
```

- **`registry-covered` counts hard MUSTs only.** §0.2 makes SHOULD normative and deviation
  ADR-worthy, so SHOULD statements are registered — but a SHOULD is not a hard MUST and must not pad
  a hard-MUST coverage count. §6.21 is the live case.
- **A DEFERRED entry is counted once, as deferred.** Counting it in both columns would drive the
  delta negative and mask a missing registration. §6.17 and §14.3 each hold one.
- **Coverage counts only at the section where the statement is registered.** No section is closed by
  pointing at an entry filed elsewhere.

### `hard_must` is derived, not judged per section

A section-level number with a prose justification is reviewable but not checkable, and it left one
move open: a section could be written off as `hard_must: 0` with a basis saying the rule was
*"registered at §12.4, its precise location"* — and nothing required that note to name **which**
statement, nor verified the named statement existed, still lived there, or said what the basis
claimed. §10.7 and §11 were both closed that way. Both claims were true; neither was checked.

So the count is derived from two declared inputs:

```
hard_must == REGISTERED occurrences at this section in M0a_obligation_inventory.yaml
             + len(keyword_free)     # registered MUSTs the spec states without a keyword
```

Every explicit `MUST / MUST NOT / 必須 / 不得 / 不可` in §6–§16 is listed individually and classified
as exactly one of:

| Classification | Meaning | Enforced in CI |
|---|---|---|
| `REGISTERED(target)` | this occurrence is the prose home of `target` | `target` resolves; **at most one** occurrence per statement key |
| `RESTATEMENT_OF(target)` | introduces no new obligation | `target` resolves, and its home section either registers it or declares it keyword-free |
| `NON_NORMATIVE_WITH_RATIONALE` | the keyword does no normative work | no target permitted; a rationale is **required** |

There is no fourth class and no default. An occurrence nobody has adjudicated fails CI rather than
being assumed benign.

| Classification | Occurrences |
|---|---:|
| `REGISTERED` | 52 |
| `RESTATEMENT_OF` | 17 |
| `NON_NORMATIVE_WITH_RATIONALE` | 3 |
| **Total** | **72** |

### A resolvable target is not a dischargeable one

Resolution proves the name exists. It does not prove the target **obliges the same thing**, and two
classifications were wrong in exactly that gap:

| Occurrence | Pointed at | Why that was wrong |
|---|---|---|
| `14.3#M1` 「超出 session solver budget 需 supervisor/human approval」 | `budget.gate.before_side_effect` | COST-001 obliged the gate to refuse **or** escalate before a side effect. A system that refuses **permanently** satisfies it completely — no supervisor, no approval, no way through. |
| `14.3#M3` 「measurement/simulation 需 artifact reference」 | `rootcause.traceable_to_run_artifact` | EPI-002 binds a **confirmed root cause**. A measurement admitted with no artifact reference never reaches it unless it later joins a root-cause confirmation — an M4 capability. This obligation holds at admission. |

Both are now `REGISTERED` against owners that can fail: the first against COST-001, whose statement
and pass condition were amended to state the approval path; the second against **EVI-009**, minted
because nothing existing reached it (`ART-001` gives artifacts identity without obliging evidence to
cite one; `SIM-001` governs a simulation manifest's fields and a measurement has no solver version;
`EVI-003` forbids inference being *typed* measured but leaves a human-entered measured claim
untouched).

`14.3#M2` remains `RESTATEMENT_OF(inference.not_evidence)` — that target does oblige exactly the
inferred-marking the bullet restates.

### The registry's Test IDs must discharge, not decorate

§23.2 says a statement's `tests` are the tests that discharge it. Six pass conditions did not, and
were amended rather than left in place:

| Statement | The gap |
|---|---|
| `transition.decision.deterministic` | `T-EPI-005` tested the canonical operator, the ban on direct mutation and the event path — never that identical inputs plus an identical `policy_version` give an identical `TransitionDecision`. |
| `debate.rounds.not_fixed` | `T-LLM-002` tested metrics, baseline comparison and calibration. A system that always runs the configured maximum rounds passed all three. |
| `review.queue.stakes_sla_expiry` | `T-OPS-002` tested only the second half of OPS-002 (queue state feeding Capability availability). `stakes` / SLA / expiry were unverified. |
| `inference.no_provenance_not_usable` | `T-LLM-001` tested that a **new** output without provenance fails admission. §7.6 forbids *using* a stored provenance-less inference, which admission testing cannot reach. |
| `budget.overrun.supervisor_approval` | see above — permanent refusal satisfied the old wording. |
| `critique.independent_path.reject_or_irreversible` | §7.6 states **one rule with two triggers**: 重大 REJECT **and** irreversible action. `T-SRC-002` gated `BELIEF_REVISION`, so an irreversible dispatch touching no belief state was ungoverned — a tape-out submission costs six weeks and needed no critique at all. |

The last one is why the statement was renamed from `critique.independent_path.major_reject`: the old
key described one trigger and the rule has two. SRC-002 was extended rather than a 60th Requirement
minted, and `lab_brain.core.critique_gate.evaluate_dispatch` now makes it refusable — an irreversible
action with `causes_belief_revision = false` and no completed independent critique is blocked, and a
valid human approval does **not** substitute. Approval records accountability; critique records
independent challenge. §14.3's fabrication gate wants both.

### What is matched, and the two categories that escape matching

`MUST` / `MUST NOT` are matched **case-sensitively**: a lowercase "must" in prose is not §0.2's
keyword. `必須 / 不得 / 不可` are the spec's own vocabulary. Heading lines are excluded, on the rule
that a title asserting an obligation must state it in the body.

Two categories cannot be reached by matching, and both are declared rather than ignored:

**`需`-phrased occurrences (3, all in §14.3).** `需` reads as "requires" in some places and
"needs" in others, so matching it would manufacture obligations. Those that do carry one are
adjudicated by hand, marked `keyword: 需 (manual)`, with ids like `14.3#M1`.

**Keyword-free statements (18).** Obligations the spec states declaratively — a schema rule, a
table cell, `不是` / `不提供` / `都要` / `保存`. §10.5 is the clearest: *「「measurement 永遠最高」**不是**
core 假設。權威是 `(method, calibration, validated_range fit)` 的函數」* is a genuine obligation
carried entirely by `不是`. Legitimate — and also exactly where an unfounded count could hide, so
each must name its statement key **and** quote how the section states it. A statement neither
registered by an occurrence nor declared keyword-free fails CI.

### Completeness is checked against the document, not the registry

All **76** numbered headings in §6–§16 must appear in the count file, including the 36
whose count is 0 — "this section states no obligation" is a reviewable claim, silence is not. Drift
is checked in both directions, so a section renumbered by an amendment cannot leave a stale row
behind, and a heading-format change cannot quietly empty the check.

The heading exclusion gets its own guard, because an exclusion is a hiding place. §14.4.1's heading
is 「ReviewQueue **必須**接回 Verification Planner」; had its body stated nothing, the section would
have counted 0 and no scan would have objected. Any section whose *title* carries a hard keyword must
count at least one obligation.

### What is executable

| Artefact | Checked by |
|---|---|
| per-section deltas | `tests/spec/test_m0a_coverage_audit.py` |
| occurrence classification, targets, derived counts | `tests/spec/test_m0a_obligation_inventory.py` |
| inventory still matches the document | `scripts/rebuild_obligation_inventory.py --check`, in CI |
| §7.6 dispatch refusals | `tests/contract/test_critique_gate.py` |
| the status document's own numbers | `scripts/update_status.py --check`, in both whole-suite CI jobs |

Seven of the inventory tests are negative fixtures: dropping an adjudication, breaking a target,
claiming a second prose home, inflating a count, rewording a quote, un-declaring a keyword-free
statement, and loading a malformed row must each **fail**. A guard not shown to fire is not a guard.

## 3. Per-section reconciliation

Generated from the same data the tests check. 76 sections — every numbered heading in
§6–§16.

| Section | hard MUST | registry-covered (live) | named deferred | SHOULD (excluded) | delta |
|---|---:|---:|---:|---:|---:|
| 6 | 0 | 0 | — | — | 0 |
| 6.1 | 2 | 2 | — | — | 0 |
| 6.2 | 1 | 1 | — | — | 0 |
| 6.3 | 2 | 2 | — | — | 0 |
| 6.4 | 1 | 1 | — | — | 0 |
| 6.5 | 0 | 0 | — | — | 0 |
| 6.6 | 0 | 0 | — | — | 0 |
| 6.7 | 0 | 0 | — | — | 0 |
| 6.8 | 1 | 1 | — | — | 0 |
| 6.9 | 0 | 0 | — | — | 0 |
| 6.10 | 0 | 0 | — | — | 0 |
| 6.11 | 1 | 1 | — | — | 0 |
| 6.12 | 0 | 0 | — | — | 0 |
| 6.13 | 1 | 1 | — | — | 0 |
| 6.14 | 0 | 0 | — | — | 0 |
| 6.15 | 1 | 1 | — | — | 0 |
| 6.16 | 5 | 5 | — | — | 0 |
| 6.17 | 2 | 1 | 1 | — | 0 |
| 6.18 | 2 | 2 | — | — | 0 |
| 6.19 | 1 | 1 | — | — | 0 |
| 6.20 | 2 | 2 | — | — | 0 |
| 6.21 | 2 | 2 | — | 1 | 0 |
| 7 | 0 | 0 | — | — | 0 |
| 7.1 | 0 | 0 | — | — | 0 |
| 7.2 | 3 | 3 | — | — | 0 |
| 7.3 | 0 | 0 | — | — | 0 |
| 7.4 | 0 | 0 | — | — | 0 |
| 7.5 | 1 | 1 | — | — | 0 |
| 7.6 | 3 | 3 | — | — | 0 |
| 8 | 1 | 1 | — | — | 0 |
| 8.1 | 0 | 0 | — | — | 0 |
| 8.2 | 0 | 0 | — | — | 0 |
| 8.2.1 | 3 | 3 | — | — | 0 |
| 9 | 0 | 0 | — | — | 0 |
| 9.1 | 5 | 5 | — | — | 0 |
| 9.2 | 0 | 0 | — | — | 0 |
| 9.3 | 0 | 0 | — | — | 0 |
| 9.4 | 1 | 1 | — | — | 0 |
| 9.5 | 1 | 1 | — | — | 0 |
| 9.6 | 1 | 1 | — | — | 0 |
| 10 | 0 | 0 | — | — | 0 |
| 10.1 | 0 | 0 | — | — | 0 |
| 10.2 | 1 | 1 | — | — | 0 |
| 10.2.1 | 3 | 3 | — | — | 0 |
| 10.2.2 | 1 | 1 | — | — | 0 |
| 10.3 | 1 | 1 | — | — | 0 |
| 10.4 | 1 | 1 | — | — | 0 |
| 10.5 | 1 | 1 | — | — | 0 |
| 10.5.1 | 2 | 2 | — | — | 0 |
| 10.6 | 1 | 1 | — | — | 0 |
| 10.7 | 0 | 0 | — | — | 0 |
| 11 | 0 | 0 | — | — | 0 |
| 12 | 0 | 0 | — | — | 0 |
| 12.1 | 0 | 0 | — | — | 0 |
| 12.2 | 0 | 0 | — | — | 0 |
| 12.3 | 1 | 1 | — | — | 0 |
| 12.4 | 1 | 1 | — | — | 0 |
| 12.5 | 1 | 1 | — | — | 0 |
| 13 | 0 | 0 | — | — | 0 |
| 13.1 | 0 | 0 | — | — | 0 |
| 13.2 | 0 | 0 | — | — | 0 |
| 13.3 | 0 | 0 | — | — | 0 |
| 14 | 0 | 0 | — | — | 0 |
| 14.1 | 2 | 2 | — | — | 0 |
| 14.2 | 0 | 0 | — | — | 0 |
| 14.3 | 4 | 3 | 1 | — | 0 |
| 14.4 | 2 | 2 | — | — | 0 |
| 14.4.1 | 1 | 1 | — | — | 0 |
| 14.5 | 2 | 2 | — | — | 0 |
| 15 | 0 | 0 | — | — | 0 |
| 15.1 | 0 | 0 | — | — | 0 |
| 15.2 | 0 | 0 | — | — | 0 |
| 15.3 | 0 | 0 | — | — | 0 |
| 15.4 | 2 | 2 | — | — | 0 |
| 16 | 0 | 0 | — | — | 0 |
| 16.1 | 0 | 0 | — | — | 0 |
| **Total** | **70** | **68** | **2** | 1 | **0** |

**Every delta is 0.** 70 hard MUSTs = 68 registered live + 2 named deferred, of
which 52 have an explicit-keyword occurrence and 18 are declared keyword-free. The
1 SHOULD-level entry is excluded from coverage and shown for transparency.

### Section notes

**§7.2 — three obligations.** Metrics recorded, round count not fixed
(`debate.rounds.not_fixed`), high-stakes inverted retrieval. `7.2#4` restates the third's
enforcement half. A system can record diversity and cost faithfully while always running 8 rounds
and satisfy `debate.metrics.recorded`, which is why the second is its own statement.

**§7.6 — two obligations plus one keyword-free.** The independent critique path (both triggers) and
the ban on using provenance-less inferences; `inference.provenance.required` is stated with 保存 and
carries no keyword.

**§8 / §8.1 — the admission gate lives in §8.** §8.1 is the certificate schema. `§8.1`'s other
former entry, `hypothesis.competing.minimum_two`, is not stated in §8.1 at all — its home is §3's P6
and EPI-001's §25.3 row — so it moved out of the audited range.

**§8.2.1 — determinism is separate from authority.** `belief.transition.policy` is satisfied by
routing every transition through `TransitionPolicy.evaluate` *even if that call is irreproducible*,
so `transition.decision.deterministic` cannot be folded into it.

**§9.1 — five hard MUSTs.** Two keyword occurrences (`MUST NOT invent outcomes`; disagreement metrics
`MUST be deterministic, versioned`) and three keyword-free contract rules. `VER-008` was **not**
merged into `VER-004`: `VER-004` governs which *outcomes* count as plausible, `VER-008` the *metric*
ranking how far two predictions disagree. A planner could draw every outcome from a properly declared
OutcomeSpace and still rank them with an unversioned distance function, and `T-VER-004` would pass.

**§9.3 / §9.4 — the false-positive case.** Three occurrences of `不可` / `不得`; one is an obligation
(`cost.vector.not_single_scalar`) and two are `不可逆` describing a fabrication cost profile.
Classified `NON_NORMATIVE_WITH_RATIONALE` with the reason recorded, not silently dropped.

**§10.2 / §10.2.1 — re-attributed.** `extractor.backend_agnostic`'s sentence is in §10.2.1's tool
table, not §10.2, whose own rule uses `不提供` and has no keyword occurrence.

**§10.5 / §10.5.1.** §10.5's one obligation is keyword-free (`不是`). §10.5.1's two are explicit and
both registered against `EPI-004`.

**§10.7 / §11 — zero, with a named target.** `10.7#1` is
`RESTATEMENT_OF(job.long_running.suspend_resume_idempotent)` (§12.4) and `11#1` is
`RESTATEMENT_OF(domain.core_no_domain_import)` (§24.2, enforced by `T-EXT-001`'s import scan). Both
targets are resolved against the registry by CI rather than asserted in prose.

**§14.3 — four obligations.** Two keyword, two `需`-phrased. See the discharge discussion above.

**§14.4 — two.** `review.queue.stakes_sla_expiry` is the first half of OPS-002; `review.capacity.
planner` (§14.4.1) is the second. `acl.actor.required_for_approval_egress` is keyword-free (都要).

**§15.4 — two.** `debate.groupthink_reduction.falsifiable` is registered at its own section, not
borrowed from §7.2: that entry obliges the metrics to be *recorded*, this one obliges the claim to be
*refutable*. The one-prose-home rule now makes borrowing impossible.

**§6.6 — flagged judgement.** Counted 0. The graph-DB migration trigger is phrased as a design note
and recorded in ADR-0001 under P20, not as an implementation obligation. A stricter reading is
defensible; the basis says so, so a reviewer can overrule it rather than discover it.

## 4. Requirements and statements this audit produced

Requirement ↔ Test invariant: **59 ↔ 59**. 103 normative statements
registered across the whole document.

New Requirement IDs minted during the audit, each because no existing requirement could discharge
the obligation without distortion:

| ID | Obligation | Milestone |
|---|---|---|
| `HEU-001` | Candidate heuristics await human approval; miners use approved sources only | M7 |
| `SRC-003` | Novelty status needs a coverage record; internal novelty is not global | M3 |
| `VER-007` | Design quality is not a single scalar FoM | M4 |
| `VER-008` | Disagreement metrics are deterministic and versioned | M3 |
| `OPS-004` | Cross-store writes share one unit of work | M1 |
| `EVI-009` | MEASURED/SIMULATED evidence must reference its Run/Artifact at admission | M1 |

Statements added against **existing** requirements, where an owner did exist:
`debate.rounds.not_fixed` (LLM-002), `critique.independent_path.reject_or_irreversible` (SRC-002),
`inference.no_provenance_not_usable` (LLM-001), `transition.decision.deterministic` (EPI-005),
`review.queue.stakes_sla_expiry` (OPS-002), `budget.overrun.supervisor_approval` (COST-001),
`governance.fabrication.human_signoff` (SEC-002, DEFERRED).

**Fabrication is the one deliberate deferral.** It is unenforceable rather than unenforced: §26.1's
milestones end at M8 and none submits a tape-out. It carries
`review_at: FIRST_FABRICATION_CAPABILITY` — a trigger, not a date, because the relevant event is the
registration of a fabrication Capability. `T-SPEC-002` enforces that a DEFERRED entry has a
`review_at`, so the trigger cannot be dropped silently. The second deferral,
`independence.basis.beyond_work` (§6.17, `review_at: M4_EXIT`), records that v3.3 models WORK-level
independence only — GROUP / SAMPLE / INSTRUMENT / METHOD correlation is the other half of
corroboration inflation and is not modelled.

All eight spec issues (`SPEC-ISSUE-001` … `-008`) are **RESOLVED**; none is outstanding.

## 5. M0a exit gate status

§26.1's exit gate: *artifact/claim identity + bundle hash + schema/spec conformance pass; testable
without Actor/LLM/Simulator.*

| Condition | Evidence |
|---|---|
| `ART-001` content-addressed identity | model + schema-constraint tests, `T-ART-001` |
| `EVI-005` versioned condition schemas | model + schema tests (payload triggers, comparator version binding), `T-EVI-005` |
| `EVI-006` canonical bundle hash | model + persistence tests (ordering, immutability), `T-EVI-006` |
| `TST-002` traceability | `T-SPEC-001` |
| `TST-003` registry coverage | `T-SPEC-002` |
| Migrations | 8 applied; re-run reports 0 pending |
| Testable without Actor/LLM/Simulator | whole suite green with no backend at all; no LLM or simulator code exists |
| No OPEN GATE spec issue against M0a | all eight RESOLVED |
| `gate_profile: [postgres]` | postgres profile green in CI's `backend` job |
| §23.5 (2) coverage audit | this document: 76 sections, 70 hard MUSTs over 72 classified occurrences, every delta 0 |

M0a's allocated requirements are `ART-001`, `EVI-005`, `EVI-006`, `TST-002`, `TST-003` — all 5 have a
test that executed and passed under the declared `postgres` profile.

## 6. What remains untrue after this audit

- **Scope is §6–§16**, as §23.5 defines it. §17's contracts are exercised by the requirement tests;
  §0–§5 and §18–§27 are governance and narrative.
- **Keyword scanning misses obligations stated without a keyword.** 18 such statements are declared
  with a rationale, which converts the risk from invisible to reviewed — it does not eliminate it. An
  obligation the reader also missed would still be absent.
- **6 of 59 requirements have executable tests.** The other 53 are allocated
  to M0b–M8 and remain `TODO`. The executed-coverage gate will not let those milestones close
  without them.
- **No scientific behaviour is demonstrated.** M0a is identity and schema. No belief event, no
  hypothesis, no retrieval, no verification planning exists. `critique_gate` is a pure policy
  function with no caller yet.

## 7. Requested decision

**Sign off or reject.** If accepted, `docs/milestones.yaml` may move `M0a` to `DONE`, at which point
the executed-coverage gate begins enforcing it on every CI run — including the
`gate_profile: [postgres]` condition, so a run that skipped the backend tests could not sign it off.
