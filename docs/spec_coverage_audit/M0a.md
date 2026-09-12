# M0a Spec Coverage Audit — §23.5 (2)

Date: 2026-09-12 (rev 3 — coverage fix; deltas now machine-verified)
Spec: SAI 3.3, amendments `v3.3-a1` + `v3.3-a2` + `v3.3-a3`
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

Three rules that revision 2 did not apply consistently, and which caused its arithmetic to be
wrong:

- **`registry-covered` counts hard-MUST statements only.** §0.2 makes SHOULD normative and
  deviation ADR-worthy, so SHOULD statements are registered — but a SHOULD is not a hard MUST and
  must not pad a hard-MUST coverage count. §6.21 is the live case: three registry entries, one of
  them SHOULD-level, against two hard MUSTs. Counting all three showed coverage exceeding the
  requirement, which conceals gaps rather than revealing them.
- **A DEFERRED entry is counted once, as deferred.** Counting it in both columns would drive the
  delta negative and mask a missing registration. §6.17 and §14.3 each hold one.
- **Coverage is counted only at the section where the statement is registered.** Revision 2 closed
  §15.4 by pointing at a §7.2 entry. That move is no longer available, and it was wrong on the
  merits: §7.2 obliges the system to *record* debate metrics, §15.4 obliges the
  groupthink-reduction *claim* to be refutable by benchmark. A recorded metric that nobody can use
  to contradict the claim satisfies §7.2 and leaves §15.4 unmet.

`hard_must` is a **judged** count, not a raw keyword-match count. The raw scan over-counts three
ways, each resolved by reading and recorded per section in
`M0a_hard_must_counts.yaml`'s `basis` field: line-splitting (a rule wrapped across two lines
matches twice), restatement (a table row repeating a rule owned elsewhere), and descriptive prose
(overview text that describes rather than obliges).

### The arithmetic is executable

Revision 2 contained the row `§15.4: hard MUST = 2, registry-covered = 1, delta = 0`. That is
false, and it survived review because the table was prose — nothing recomputed it.

The judged counts now live in `M0a_hard_must_counts.yaml`; the coverage side is derived from
`normative_statements.yaml` by `lab_brain.spec.coverage_audit`; and
`tests/spec/test_m0a_coverage_audit.py` recomputes every delta on each CI run. A row that does not
balance fails the build. The test also refuses an audit that omits a registry section inside
§6–§16 — the quieter version of the same failure, where the numbers balance because a section was
never counted at all.

What remains human: the `hard_must` judgements, their recorded basis, and the sign-off.

## 3. Per-section reconciliation

Generated from the same data the test checks. 48 sections; §6–§16 as §23.5 scopes it.

| Section | hard MUST | registry-covered (live) | named deferred | SHOULD (excluded) | delta |
|---|---:|---:|---:|---:|---:|
| 6.1 | 2 | 2 | — | — | 0 |
| 6.2 | 1 | 1 | — | — | 0 |
| 6.3 | 2 | 2 | — | — | 0 |
| 6.4 | 1 | 1 | — | — | 0 |
| 6.5 | 0 | 0 | — | — | 0 |
| 6.7 | 0 | 0 | — | — | 0 |
| 6.8 | 1 | 1 | — | — | 0 |
| 6.11 | 1 | 1 | — | — | 0 |
| 6.13 | 1 | 1 | — | — | 0 |
| 6.14 | 0 | 0 | — | — | 0 |
| 6.15 | 1 | 1 | — | — | 0 |
| 6.16 | 5 | 5 | — | — | 0 |
| 6.17 | 2 | 1 | 1 | — | 0 |
| 6.18 | 2 | 2 | — | — | 0 |
| 6.19 | 1 | 1 | — | — | 0 |
| 6.20 | 2 | 2 | — | — | 0 |
| 6.21 | 2 | 2 | — | 1 | 0 |
| 7.1 | 0 | 0 | — | — | 0 |
| 7.2 | 2 | 2 | — | — | 0 |
| 7.5 | 1 | 1 | — | — | 0 |
| 7.6 | 1 | 1 | — | — | 0 |
| 8 | 0 | 0 | — | — | 0 |
| 8.1 | 2 | 2 | — | — | 0 |
| 8.2.1 | 2 | 2 | — | — | 0 |
| 9.1 | 4 | 4 | — | — | 0 |
| 9.4 | 1 | 1 | — | — | 0 |
| 9.5 | 1 | 1 | — | — | 0 |
| 9.6 | 1 | 1 | — | — | 0 |
| 10.2 | 2 | 2 | — | — | 0 |
| 10.2.1 | 2 | 2 | — | — | 0 |
| 10.2.2 | 1 | 1 | — | — | 0 |
| 10.3 | 1 | 1 | — | — | 0 |
| 10.4 | 1 | 1 | — | — | 0 |
| 10.5 | 2 | 2 | — | — | 0 |
| 10.6 | 1 | 1 | — | — | 0 |
| 10.7 | 0 | 0 | — | — | 0 |
| 11 | 0 | 0 | — | — | 0 |
| 12.3 | 1 | 1 | — | — | 0 |
| 12.4 | 1 | 1 | — | — | 0 |
| 12.5 | 1 | 1 | — | — | 0 |
| 13 | 0 | 0 | — | — | 0 |
| 14.1 | 2 | 2 | — | — | 0 |
| 14.3 | 2 | 1 | 1 | — | 0 |
| 14.4 | 1 | 1 | — | — | 0 |
| 14.4.1 | 1 | 1 | — | — | 0 |
| 14.5 | 2 | 2 | — | — | 0 |
| 15.4 | 2 | 2 | — | — | 0 |
| 16 | 0 | 0 | — | — | 0 |
| **Total** | **62** | **60** | **2** | 1 | **0** |

**Every delta is 0.** 62 hard MUSTs = 60 registered live + 2 named
deferred. The single SHOULD-level entry (§6.21) is excluded from the coverage count and shown for
transparency.

### Section notes

**§6.17 — one of two deferred.** `independence.dependence_unknown_counts_zero` is live;
`independence.basis.beyond_work` is DEFERRED with `review_at: M4_EXIT`, because v3.3 models
WORK-level independence only and a policy demanding a stronger basis must escalate to human review
rather than assume independence. Counted as 1 live + 1 deferred = 2, not as 2 covered.

**§6.21 — two hard MUSTs, three entries, one excluded.** The hard MUSTs are that the
retraction/erratum check status is recorded even when UNKNOWN (`EVI-008`) and that a novelty status
without a coverage record is unauditable (`SRC-003`, added in `v3.3-a2`). The third entry,
`source.retraction.check_performed`, is SHOULD-level and excluded.

Revision 1 of this audit listed §6.21 as difference 0 *and* cited it in SPEC-ISSUE-005 — which
could not both be true. The cause was conflating the two rules above; the novelty one was
unregistered at the time.

**§14.3 — two hard MUSTs, one live and one deferred.** The external query gate (private
identifiers and exact confidential geometry must not be sent out) is now registered here as
`privacy.query_gate.no_private_identifiers` → `SEC-001`. It is distinct from §14.1's
`privacy.restricted.no_egress`, which classifies *data* by sensitivity label: a sanitized query
over RESTRICTED_NDA material still must not carry private identifiers. Before this fix §14.3 held
only its fabrication MUST, giving `hard_must=2, live=0, deferred=1, delta=1`.

The fabrication gate remains DEFERRED under `SEC-002` with
`review_at: FIRST_FABRICATION_CAPABILITY` — a trigger rather than a date, since the relevant event
is registering a fabrication Capability, not elapsed time.

**§15.4 — the blocker, now closed.** Two hard MUSTs: the groupthink-reduction claim must be
falsifiable, and hard gates must reference a versioned `BenchmarkPolicy` with no pre-calibration
thresholds. Only the second was registered. `debate.groupthink_reduction.falsifiable` → `LLM-002`
now covers the first at its own section.

`T-LLM-002`'s pass condition was also sharpened (amendment `v3.3-a3`, **no new Requirement or Test
ID** — the invariant stays 57 ↔ 57) so that "falsifiable" is something a test can actually fail:
the fixed benchmark must compare the debate mechanism against a baseline/disabled condition on the
same cases. Without that comparison the claim could only ever be illustrated, never refuted.

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
| §23.5 (2) coverage audit | this document; 48 sections, 62 hard MUSTs, every delta 0, recomputed by `tests/spec/test_m0a_coverage_audit.py` |

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
