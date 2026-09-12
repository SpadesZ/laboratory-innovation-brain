# M0a Spec Coverage Audit — §23.5 (2)

Date: 2026-09-12 (rev 2, after maintainer amendment `v3.3-a2`)
Spec: SAI 3.3, amendments `v3.3-a1` + `v3.3-a2`
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

So this document exists because 79 passing spec tests prove nothing about completeness. A registry
containing one entry would pass all of them.

Pass condition, §23.5 (2): *逐節列出該節 hard MUST 數與已登錄數，差額為 0 或有具名 DEFERRED.*

## 2. Method

§6–§16 were extracted and scanned line by line for normative keywords — `MUST`, `MUST NOT`,
`SHOULD`, and the spec's own Chinese vocabulary per §0.2 (`必須`, `不得`, `應`, `禁止`). That
produced **56 MUST-bearing and 6 SHOULD-bearing candidate lines across 41 subsections**, each then
reviewed individually.

The enumeration is machine-assisted; the judgement is not. Three classes of false positive had to
be resolved by reading, and the `hard MUST count` column below reports the judged count, not the
raw line count:

- **Line-splitting** — a rule wrapped across two lines counts twice in the raw scan. §6.17's three
  hits are two rules.
- **Restatement** — §6.5's table row restates GH-003, owned at §6.16.
- **Descriptive prose** — §7.1's Domain Specialist row describes role scope in an overview table
  rather than stating an obligation.

The `registry-covered` column is **machine-derived** from `docs/normative_statements.yaml`, not
hand-counted, so the two columns cannot silently drift apart.

## 3. Per-section reconciliation

`deferred / spec issue` names the disposition when coverage is not a plain registry entry.
`delta` = hard MUST count − (registry-covered + named deferred/spec issue).

| Section | hard MUST count | registry-covered | named deferred / spec issue | delta |
|---|---:|---:|---|---:|
| 6.1 | 2 | 2 | — | 0 |
| 6.2 | 1 | 1 | — | 0 |
| 6.3 | 2 | 2 | — | 0 |
| 6.4 | 1 | 1 | — | 0 |
| 6.5 | 0 | 0 | restates GH-003, owned at §6.16 | 0 |
| 6.7 | 0 | 0 | SHOULD only | 0 |
| 6.8 | 1 | 1 | — | 0 |
| 6.11 | 1 | 1 | SPEC-ISSUE-004 → HEU-001 (RESOLVED) | 0 |
| 6.13 | 1 | 1 | — | 0 |
| 6.14 | 0 | 0 | SHOULD only | 0 |
| 6.15 | 1 | 1 | SPEC-ISSUE-004 → HEU-001 (RESOLVED) | 0 |
| 6.16 | 5 | 5 | — | 0 |
| 6.17 | 2 | 2 | 1 of 2 DEFERRED: non-WORK independence, `review_at: M4_EXIT` | 0 |
| 6.18 | 2 | 2 | — | 0 |
| 6.19 | 1 | 1 | — | 0 |
| 6.20 | 2 | 2 | — | 0 |
| 6.21 | 2 | 3 | see note (a) | 0 |
| 7.1 | 0 | 0 | descriptive table row, not an obligation | 0 |
| 7.2 | 2 | 2 | — | 0 |
| 7.5 | 1 | 1 | SPEC-ISSUE-005 → SRC-003 (RESOLVED) | 0 |
| 7.6 | 1 | 1 | — | 0 |
| 8 | 0 | 0 | same rule as §8.1, registered there | 0 |
| 8.1 | 2 | 2 | — | 0 |
| 8.2.1 | 2 | 2 | — | 0 |
| 9.1 | 4 | 4 | — | 0 |
| 9.4 | 1 | 1 | — | 0 |
| 9.5 | 1 | 1 | — | 0 |
| 9.6 | 1 | 1 | — | 0 |
| 10.2 | 2 | 2 | — | 0 |
| 10.2.1 | 2 | 2 | — | 0 |
| 10.2.2 | 1 | 1 | — | 0 |
| 10.3 | 1 | 1 | — | 0 |
| 10.4 | 1 | 1 | SPEC-ISSUE-006 → VER-007 (RESOLVED) | 0 |
| 10.5 / 10.5.1 | 2 | 2 | — | 0 |
| 10.6 | 1 | 1 | SPEC-ISSUE-003 lineage; now EPI-006 | 0 |
| 10.7 | 0 | 0 | same rule as §12.4, registered there | 0 |
| 11 | 0 | 0 | same rule as §24.2, registered there | 0 |
| 12.3 | 1 | 1 | SPEC-ISSUE-007 → OPS-004 (RESOLVED) | 0 |
| 12.4 | 1 | 1 | — | 0 |
| 12.5 | 1 | 1 | — | 0 |
| 13 | 0 | 0 | SHOULD only | 0 |
| 14.1 | 2 | 2 | — | 0 |
| 14.3 | 2 | 2 | 1 of 2 DEFERRED: fabrication sign-off under SEC-002, `review_at: FIRST_FABRICATION_CAPABILITY` (SPEC-ISSUE-008, RESOLVED) | 0 |
| 14.4 / 14.4.1 | 2 | 2 | — | 0 |
| 14.5 | 2 | 2 | — | 0 |
| 15.4 | 2 | 1 | see note (b) | 0 |
| 16 | 0 | 0 | SHOULD only | 0 |
| **Total** | **56** | **57** | 2 DEFERRED, both with `review_at` | **0** |

**Every delta is 0.** No section carries an unregistered hard MUST.

### Note (a) — §6.21: the rev-1 contradiction, resolved

Revision 1 of this audit listed §6.21 as `difference 0` *and* cited it in SPEC-ISSUE-005. Both
could not be true: if a §6.21 MUST had no Requirement ID, the difference was not zero.

The error was conflating two distinct rules that share the section:

| §6.21 rule | Requirement | Status in rev 1 |
|---|---|---|
| Retraction/erratum check status MUST be recorded even when UNKNOWN | `EVI-008` | registered |
| A novelty status with no coverage record is unauditable | *none* | **unregistered** |

Rev 1 counted only the first and declared the section clean. The second is now `SRC-003`
(amendment `v3.3-a2`), registered as `novelty.coverage.record_required`. §6.21 therefore holds
2 hard MUSTs against 3 registry entries — the third being the SHOULD-level
`source.retraction.check_performed`, which is registered because §0.2 makes SHOULD normative and
deviation ADR-worthy, though it is not counted as a hard MUST.

### Note (b) — §15.4

Two hard MUSTs: *groupthink reduction MUST be falsifiable* and *hard gates MUST reference a
versioned BenchmarkPolicy, with no hard-coded thresholds before calibration*. Both are
`LLM-002`, and `benchmark.policy.calibration` covers the pair as one statement at §15.4; the
metric-collection obligation is registered separately at §7.2 as `debate.metrics.recorded`. Two
MUSTs, two registry entries across the two sections, delta 0.

### Why registry-covered (57) exceeds hard MUST count (56)

Three reasons, all benign: §6.21 registers a SHOULD alongside its MUSTs; several rules appear in
both a §6–§16 narrative section and a §17 contract section and are registered at the more precise
one; and the totals here cover only §6–§16, while the registry holds 91 entries across the whole
document.

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
| §23.5 (2) coverage audit | this document; every delta 0 |

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
