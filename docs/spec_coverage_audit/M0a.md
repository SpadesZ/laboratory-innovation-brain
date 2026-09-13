# M0a Spec Coverage Audit — §23.5 (2)

Date: 2026-09-12 (rev 5 — occurrence-level inventory; seven sections re-adjudicated)
Spec: SAI 3.3, amendments `v3.3-a1` ... `v3.3-a5`
Milestone: **M0a — Scientific Identity Foundation**
Owner per §23.5: spec maintainer
Prepared by: implementation agent
Status: **AWAITING MAINTAINER SIGN-OFF — M0a not marked DONE**

> §23.5 (2) assigns this audit to the spec maintainer, not to the Coding Agent. What follows is the
> enumeration and reconciliation; the sign-off is not mine to give. `docs/milestones.yaml` still
> reads `M0a: IN_PROGRESS`, and `scripts/check_requirement_coverage.py` enforces the DONE
> conditions the moment that changes.

## 1. What this audit is, and what it is not

§23.5 splits coverage into two responsibilities that are easy to conflate:

```
(1) machine-checkable — T-SPEC-002:
    registry internal consistency; every entry resolves; no dangling references.

(2) human-checkable — Spec Coverage Audit:
    "every hard MUST in the prose reached the registry".
    Cannot be derived from prose by a linter.
```

And it is explicit about the consequence:

> Coding Agent 不得因 T-SPEC-002 通過就推論 registry 完整。

So this document exists because a passing T-SPEC-002 proves nothing about completeness. A
registry containing one entry would pass it.

Revision history matters here, because two successive revisions of this audit were themselves
wrong: rev 1 declared §6.21 clean while citing it in a spec issue, and rev 2 carried a row
asserting `2 - 1 = 0`. Both survived because the reconciliation was prose. Rev 3 makes the
arithmetic executable — see §2.

Pass condition, §23.5 (2): *逐節列出該節 hard MUST 數與已登錄數，差額為 0 或有具名 DEFERRED.*

## 2. Counting rule

One formula, applied to every section without exception:

```
delta = hard_must - (registry_live_must + registry_deferred_must)

  registry_live_must      entries for the section with level MUST and no deferred_rationale
  registry_deferred_must  entries with level MUST and a deferred_rationale, counted ONCE as
                          deferred and never also as covered
  SHOULD entries          excluded entirely from hard-MUST coverage
```

- **`registry-covered` counts hard-MUST statements only.** §0.2 makes SHOULD normative and
  deviation ADR-worthy, so SHOULD statements are registered — but a SHOULD is not a hard MUST and
  must not pad a hard-MUST coverage count. §6.21 is the live case.
- **A DEFERRED entry is counted once, as deferred.** Counting it in both columns would drive the
  delta negative and mask a missing registration. §6.17 and §14.3 each hold one.
- **Coverage is counted only at the section where the statement is registered.** No section is
  closed by pointing at an entry filed elsewhere.

### `hard_must` is derived from the occurrence inventory, not judged per section

Rev 4 judged one number per section and recorded a prose `basis` for it. That was reviewable but not
checkable, and it left one move open. A section could be written off as `hard_must: 0` with a basis
saying the rule was **"registered at §12.4, its precise location"** — and nothing required that note
to name *which* statement, nor verified that the named statement existed, still lived there, or said
what the basis claimed. §10.7 and §11 were both closed exactly that way. Both claims were true;
neither was checked.

So the count is now derived from two declared inputs:

```
hard_must == REGISTERED occurrences at this section in M0a_obligation_inventory.yaml
             + len(keyword_free)     # registered MUSTs the spec states without a keyword
```

Every explicit `MUST / MUST NOT / 必須 / 不得 / 不可` in §6–§16 is listed individually in
`M0a_obligation_inventory.yaml` and classified as exactly one of:

| Classification | Meaning | Constraint enforced in CI |
|---|---|---|
| `REGISTERED(target)` | this occurrence is the prose home of `target` | `target` resolves; **at most one** occurrence per statement key |
| `RESTATEMENT_OF(target)` | introduces no new obligation | `target` resolves, and its home section either registers it or declares it keyword-free |
| `NON_NORMATIVE_WITH_RATIONALE` | the keyword does no normative work | no target permitted; a rationale is **required** |

There is no fourth class and no default. An occurrence nobody has looked at fails CI rather than
being assumed benign.

**50 REGISTERED + 19 RESTATEMENT_OF + 3 NON_NORMATIVE = 72 occurrences**
(3 of them adjudicated by hand — see below).

| Classification | Occurrences |
|---|---:|
| `REGISTERED` | 50 |
| `RESTATEMENT_OF` | 19 |
| `NON_NORMATIVE_WITH_RATIONALE` | 3 |
| **Total** | **72** |

### What is matched, and the two categories that escape matching

`MUST` / `MUST NOT` are matched **case-sensitively**: a lowercase "must" in prose is not the keyword
§0.2 defines. `必須 / 不得 / 不可` are the spec's own vocabulary. Heading lines are excluded, on the
rule that a title asserting an obligation must state it in the body.

Two categories cannot be reached by matching, and both are declared rather than ignored:

**`需`-phrased occurrences (3, all in §14.3).** `需` reads as "requires" in some places and
"needs" in others, so matching it would manufacture obligations. The occurrences that do carry one
are adjudicated by hand, marked `keyword: 需 (manual)`, and given ids of the form `14.3#M1`. All
three are RESTATEMENT_OF: the solver-budget gate restates `budget.gate.before_side_effect` (§17.17),
and the memory-admission gate restates `inference.not_evidence` (§3) plus
`rootcause.traceable_to_run_artifact` (§25.3).

**Keyword-free statements (18).** Obligations the spec states declaratively — a schema rule, a
table cell, `不是` / `不提供` / `都要` / `保存`. §10.5 is the clearest: *「「measurement 永遠最高」**不是**
core 假設。權威是 `(method, calibration, validated_range fit)` 的函數」* is a genuine obligation
carried entirely by `不是`. These are legitimate, and they are also exactly where an unfounded count
could hide, so each must name its statement key **and** quote how the section states it. A statement
that is neither registered by an occurrence nor declared keyword-free fails CI.

### Completeness is checked against the document, not the registry

All **76** numbered headings in §6–§16 must appear in the count file, including the 36
whose count is 0 — "this section states no obligation" is a reviewable claim, silence is not. Drift
is checked in both directions, so a section renumbered by an amendment cannot leave a stale row
behind, and a heading-format change cannot quietly empty the check.

The heading exclusion gets its own guard, because an exclusion is a hiding place. §14.4.1's heading
is 「ReviewQueue **必須**接回 Verification Planner」; had its body stated nothing, the section would
have counted 0 and no scan would have objected. Any section whose *title* carries a hard keyword must
count at least one obligation.

### The arithmetic is executable, and so is the bookkeeping

| Artefact | Checked by |
|---|---|
| per-section deltas | `tests/spec/test_m0a_coverage_audit.py` (11 tests) |
| occurrence classification, targets, counts | `tests/spec/test_m0a_obligation_inventory.py` (19 tests) |
| inventory still matches the document | `scripts/rebuild_obligation_inventory.py --check`, in CI |

Seven of the inventory tests are negative fixtures: dropping an adjudication, breaking a target,
claiming a second prose home, inflating a count, rewording a quote, un-declaring a keyword-free
statement, and loading a malformed row must each **fail**. A guard that has not been shown to fire
is not a guard.

What remains human: the adjudications, the keyword-free rationales, and the sign-off.

## 3. Per-section reconciliation

Generated from the same data the tests check. 76 sections — every numbered heading in
§6–§16, as §23.5 scopes it.

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
| 14.3 | 2 | 1 | 1 | — | 0 |
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
| **Total** | **68** | **66** | **2** | 1 | **0** |

**Every delta is 0.** 68 hard MUSTs = 66 registered live + 2 named deferred, of which
50 have an explicit-keyword occurrence and 18 are declared keyword-free. The single
SHOULD-level entry (§6.21) is excluded from coverage and shown for transparency.

### What the occurrence inventory changed

Rev 4 totalled 64 hard MUSTs; rev 5 totals 68. The difference is not a re-tally — it is seven
sections whose count was wrong in a way section-level arithmetic could not see.

| Section | Rev 4 | Rev 5 | What occurrence-level adjudication found |
|---|---:|---:|---|
| §7.2 | 2 | 3 | Rev 4's own basis named **three** obligations — metrics recorded, round count not fixed, inverted retrieval — while the number said 2. `debate.rounds.not_fixed` (occurrence `7.2#2`) did not exist. Registered under `LLM-002`. |
| §7.6 | 1 | 3 | Both keyword occurrences were unowned. `critique.independent_path.major_reject` → `SRC-002`, `inference.no_provenance_not_usable` → `LLM-001`. |
| §8 / §8.1 | 0 / 2 | 1 / 0 | Rev 4 counted §8 as 0 because the admission-gate rule was "registered at §8.1, its precise location". It is stated at **§8**; §8.1 is the certificate schema. And §8.1's second entry, `hypothesis.competing.minimum_two`, is not stated in §8.1 at all — its home is §3's P6 and EPI-001's §25.3 row. |
| §8.2.1 | 2 | 3 | `transition.decision.deterministic` (identical inputs + `policy_version` → identical `TransitionDecision`) was unowned. `belief.transition.policy` is satisfied by routing every transition through `TransitionPolicy.evaluate` **even if that call is irreproducible**, so it cannot discharge this. → `EPI-005`. |
| §10.2 / §10.2.1 | 2 / 2 | 1 / 3 | `extractor.backend_agnostic` was filed at §10.2, but the sentence is in §10.2.1's tool table. §10.2's own rule is stated with `不提供` and has no keyword occurrence. |
| §14.4 | 1 | 2 | Rev 4's basis read "ReviewQueue carries stakes, SLA/expiry and capacity" while the single statement credited was `acl.actor.required_for_approval_egress` — the `actor_id` rule. `OPS-002` states two obligations and only the §14.4.1 half was registered; `review.queue.stakes_sla_expiry` is the other. |
| §10.7, §11 | 0 | 0 | Unchanged, but no longer asserted. `10.7#1` is `RESTATEMENT_OF(job.long_running.suspend_resume_idempotent)` and `11#1` is `RESTATEMENT_OF(domain.core_no_domain_import)`, both resolved against the registry by CI. |

Five statements were added, all mapped to **existing** Requirements able to discharge them — no
Requirement or Test ID was minted, and the invariant stays **58 ↔ 58**. Two statements were
re-sectioned and one re-homed out of the audited range, matching the `fidelity.low_cannot_reject`
correction from rev 4.

### Section notes

**§9.1 — five hard MUSTs.** Two keyword occurrences (`MUST NOT invent outcomes`; disagreement
metrics `MUST be deterministic, versioned`) and three keyword-free contract rules. Closed in round 2
as `VER-008`, which was **not** merged into `VER-004`: `VER-004` governs which *outcomes* count as
plausible, `VER-008` governs the *metric* that ranks how far two predictions disagree. A planner
could draw every outcome from a properly declared OutcomeSpace and still rank them with an
unversioned distance function, and `T-VER-004` would pass.

**§10.5 and §10.5.1 — re-attributed in rev 4, confirmed here.** §10.5's one obligation is
keyword-free (`不是`). §10.5.1's two are both explicit and both registered against `EPI-004`.

**§6.17 — one of two deferred.** `independence.dependence_unknown_counts_zero` (occurrence `6.17#1`,
restated by `6.17#2`) is live; `independence.basis.beyond_work` (`6.17#3`) is DEFERRED with
`review_at: M4_EXIT`, because v3.3 models WORK-level independence only.

**§14.3 — two keyword occurrences plus three manual.** The external query gate is
`privacy.query_gate.no_private_identifiers` → `SEC-001`, distinct from §14.1's classification rule:
a sanitized query over RESTRICTED_NDA material still must not carry private identifiers. The
fabrication gate remains DEFERRED under `SEC-002` with `review_at: FIRST_FABRICATION_CAPABILITY` — a
trigger, not a date. The solver-budget and memory-admission gates are `需`-phrased restatements.

**§15.4 — closed in round 1.** `debate.groupthink_reduction.falsifiable` → `LLM-002` registered at
its own section, not borrowed from §7.2: that entry obliges the metrics to be *recorded*, this one
obliges the claim to be *refutable*. The one-prose-home rule now makes borrowing impossible.

**§9.3 / §9.4 — the false-positive case.** Three occurrences of `不可` / `不得`; one is an
obligation (`cost.vector.not_single_scalar`) and two are `不可逆` describing a fabrication cost
profile. Classified `NON_NORMATIVE_WITH_RATIONALE` with the reason recorded, not silently dropped.

**§6.6 — flagged judgement, carried forward.** Counted 0. The graph-DB migration trigger is phrased
as a design note and recorded in ADR-0001 under P20, not as an implementation obligation. A stricter
reading is defensible; the basis says so, so a reviewer can overrule it rather than discover it.

## 4. Findings, and what was done about them

### 4.1 Seven unregistered hard MUSTs, mapped to existing requirements

| § | The MUST | Mapped to |
|---|---|---|
| 6.8 | Data differing in wavelength / bias / temperature / geometry / doping / platform MUST NOT be merged | `EVI-005` |
| 6.20 | It MUST be answerable which embedding version a retrieval used | `EVI-007` |
| 7.2 | Position diversity, bundle divergence and Critic decision-change MUST be recorded | `LLM-002` |
| 10.2.1 | All DomainPack tools MUST use one of four verb prefixes | `SIM-003` |
| 10.2.1 | `validate_*` returns ValidationReport and MUST NOT mutate raw evidence | `DOM-SP-001` |
| 10.2.2 | Domain run conditions MUST be bound into the Run manifest | `SIM-001` |
| 10.6 | Sim/measurement disagreement MUST NOT be flattened; `SIM_TO_REAL_CONFLICT` preserved | `EPI-006` |

### 4.2 Five hard MUSTs with no Requirement ID — all now ruled on

Raised as spec issues rather than registered against an approximate owner. Maintainer ruled all
five on 2026-09-12 (amendment `v3.3-a2`), moving the invariant **53 ↔ 53 → 57 ↔ 57**:

| Issue | § | New requirement | Milestone |
|---|---|---|---|
| [004](../spec_issues/SPEC-ISSUE-004-heuristic-approval-no-requirement-id.md) | 6.11, 6.15 | `HEU-001` / `T-HEU-001` (new `HEU-xxx` namespace) | M7 |
| [005](../spec_issues/SPEC-ISSUE-005-novelty-coverage-no-requirement-id.md) | 6.21, 7.5 | `SRC-003` / `T-SRC-003` | M3 |
| [006](../spec_issues/SPEC-ISSUE-006-no-single-scalar-fom-no-requirement-id.md) | 10.4 | `VER-007` / `T-VER-007` | M4 |
| [007](../spec_issues/SPEC-ISSUE-007-cross-store-unit-of-work-no-requirement-id.md) | 12.3 | `OPS-004` / `T-OPS-004`, fault-injection verified | M1 |
| [008](../spec_issues/SPEC-ISSUE-008-fabrication-gate-no-requirement-id.md) | 14.3 | **none** — registered under `SEC-002`, DEFERRED | — |

**006 is the one worth singling out.** It looks like `VER-003` covers it — both say "not a single
scalar". They do not overlap: `VER-003` governs the *cost* of a verification action, P10 the
*quality* of a design. A system could hold a perfectly multi-dimensional `CostVector` while ranking
every candidate design by one scalar Q, and `T-VER-003` would pass.

**008 is the only one that did not add a requirement.** Fabrication is unenforceable rather than
unenforced: §26.1's milestones end at M8 and none submits a tape-out, and §9.3 lists `fabrication`
as an action type so the planner's cost model can *represent* it. It carries
`review_at: FIRST_FABRICATION_CAPABILITY` — a trigger rather than a date, because the relevant
event is the registration of a fabrication Capability, not the passage of time. `T-SPEC-002`
enforces that a DEFERRED entry has a `review_at`, so the trigger cannot be dropped silently.

### 4.3 SPEC-ISSUE-002 also closed

`GH-xxx` added to the §23.2 namespace table. `GH-001..003` keep their identifiers, so the
invariant was unaffected by this issue. The `parser.py` comment explaining why `GH` was tolerated
undeclared is gone.

## 5. M0a exit gate status

§26.1's exit gate: *artifact/claim identity + bundle hash + schema/spec conformance pass; testable
without Actor/LLM/Simulator.*

| Condition | Evidence |
|---|---|
| `ART-001` content-addressed identity | 22 model tests + 8 schema-constraint tests |
| `EVI-005` versioned condition schemas | 32 model tests + 13 schema tests (payload triggers, comparator version binding) |
| `EVI-006` canonical bundle hash | 25 model tests + 30 persistence tests (ordering, immutability) |
| `TST-002` traceability | 11 assertions, `T-SPEC-001` |
| `TST-003` registry coverage | 10 assertions, `T-SPEC-002` |
| Migrations | 8 applied; re-run reports 0 pending |
| Testable without Actor/LLM/Simulator | full suite green with no backend at all; no LLM or simulator code exists |
| No OPEN GATE spec issue against M0a | SPEC-ISSUE-001 and -003 RESOLVED |
| `gate_profile: [postgres]` | postgres profile green in CI's `backend` job |
| §23.5 (2) coverage audit | this document; 76 sections (every §6-§16 heading), 68 hard MUSTs over 72 classified occurrences, every delta 0, recomputed by `tests/spec/test_m0a_coverage_audit.py` + `tests/spec/test_m0a_obligation_inventory.py` |

All conditions are met on the evidence. **I have not flipped the status.** Under §23.5 the sign-off
is the maintainer's, and an agent marking its own milestone complete on the strength of its own
audit is the exact failure this gate is positioned to prevent.

## 6. What remains untrue after this audit

- **Scope is §6–§16**, as §23.5 defines it. §17's contracts are exercised by the requirement tests;
  §0–§5 and §18–§27 are governance and narrative.
- **Keyword scanning can miss a MUST expressed without a keyword.** An obligation stated in plain
  prose would not appear in the candidate list. Each subsection's surrounding text was read while
  judging, but this is the residual risk of the method and it is not zero.
- **12 of 57 requirements have executable tests.** The other 45 are allocated to M0b–M8 and remain
  `TODO`; the executed-coverage gate will not let those milestones close without them.
- **No scientific behaviour is demonstrated.** M0a is identity and schema. No belief event, no
  hypothesis, no retrieval, no verification planning exists.

## 7. Requested decision

**Sign off or reject.** If accepted, `docs/milestones.yaml` may move `M0a` to `DONE`, at which
point the executed-coverage gate begins enforcing it on every CI run — including the
`gate_profile: [postgres]` condition, so a run that skipped the backend tests could not sign it
off.

All eight spec issues are now RESOLVED; none is outstanding.
