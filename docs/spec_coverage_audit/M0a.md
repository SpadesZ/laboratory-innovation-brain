# M0a Spec Coverage Audit — §23.5 (2)

Date: 2026-09-12
Spec: SAI 3.3, amendment `v3.3-a1`
Milestone: **M0a — Scientific Identity Foundation**
Owner per §23.5: spec maintainer
Prepared by: implementation agent
Status: **AWAITING MAINTAINER SIGN-OFF — M0a not marked DONE**

> §23.5 (2) assigns this audit to the spec maintainer, not to the Coding Agent. What follows is the
> enumeration and analysis; the sign-off is not mine to give. `docs/milestones.yaml` still reads
> `M0a: IN_PROGRESS`, and `scripts/check_requirement_coverage.py` will enforce the DONE conditions
> the moment that changes.

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

So this document exists because the 79 passing spec tests prove nothing about completeness. A
registry containing one entry would pass all of them.

## 2. Method

§6–§16 were extracted and scanned line by line for normative keywords — `MUST`, `MUST NOT`,
`SHOULD`, and the spec's own Chinese vocabulary per §0.2 (`必須`, `不得`, `應`, `禁止`). That produced
**56 MUST-bearing and 6 SHOULD-bearing candidate lines across 41 subsections**, which were then
reviewed individually against the registry.

The enumeration is machine-assisted; the judgement is not. Three kinds of false positive had to be
resolved by reading:

- **Line-splitting.** A rule wrapped across two lines counts twice. §6.17's three hits are two rules.
- **Restatement.** §6.5's table row restates GH-003, already registered at §6.16.
- **Granularity mismatch.** A registry entry may cite §10.2 for a MUST the prose places at §10.2.1,
  or §8.1 for one at §8. Not gaps.

Raw counts and candidate lines are reproducible via the enumeration script; the per-section verdicts
below are the audit.

## 3. Result: 7 unregistered MUSTs found and registered

Each was a genuine hard MUST absent from the registry, and each maps cleanly to an existing
Requirement. All seven are now registered (registry: 77 → 84 entries).

| § | The MUST | Mapped to | Why it was not already covered |
|---|---|---|---|
| 6.8 | Data differing in wavelength / bias / temperature / geometry / doping / platform MUST NOT be merged directly | `EVI-005` | Other EVI-005 entries cover schema versioning and who defines comparison; none covered the prohibition on merging, which is the operative rule (P4) |
| 6.20 | Before and after cutover it MUST be answerable which embedding version a retrieval used | `EVI-007` | Distinct from the dual-index migration *procedure*: this is provenance of the version actually used |
| 7.2 | The system MUST record position diversity, bundle divergence, and whether the Critic changed the decision | `LLM-002` | The §15.4 entry covers threshold *calibration*; this covers collecting the metrics at all |
| 10.2.1 | All DomainPack tools MUST use one of four verb prefixes | `SIM-003` | Part of the typed-tool contract SIM-003 now owns after SPEC-ISSUE-003 |
| 10.2.1 | `validate_*` returns ValidationReport and MUST NOT mutate raw evidence | `DOM-SP-001` | A validator that can edit the evidence it judges is the evaluator-corruption path in the Risk Register |
| 10.2.2 | Domain run conditions (drive states, receiver settings, DSP assumptions) MUST be bound into the Run manifest | `SIM-001` | The §10.3 entry covers manifest completeness generically, not the domain binding |
| 10.6 | Sim/measurement disagreement MUST NOT be flattened by assuming measurement is always true; `SIM_TO_REAL_CONFLICT` MUST be preserved | `EPI-006` | The §17.19.3 entry covers Conflict typing in general, not this specific prohibition |

## 4. Result: 5 hard MUSTs with no Requirement ID to map to

These cannot be registered without inventing a norm. Adding a Requirement changes the `53 ↔ 53`
invariant, which only the maintainer can do — so each is raised as a spec issue with the options
laid out, exactly as SPEC-ISSUE-003 was before its ruling.

| Issue | § | Subject | Severity | Blocks gate |
|---|---|---|---|---|
| [004](../spec_issues/SPEC-ISSUE-004-heuristic-approval-no-requirement-id.md) | 6.11, 6.15 | P16 heuristic approval: `CandidateHeuristic` must await human approval and must not self-promote | GATE | M7 |
| [005](../spec_issues/SPEC-ISSUE-005-novelty-coverage-no-requirement-id.md) | 6.21, 7.5 | `PriorArtSearchRecord`: a novelty status with no coverage record is unauditable | GATE | M3 |
| [006](../spec_issues/SPEC-ISSUE-006-no-single-scalar-fom-no-requirement-id.md) | 10.4 | P10: multi-objective trade-offs must be preserved; no single scalar FoM decides | GATE | M4 |
| [007](../spec_issues/SPEC-ISSUE-007-cross-store-unit-of-work-no-requirement-id.md) | 12.3 | Cross-store writes must be compensated in one unit of work; no dangling artifact refs | GATE | M1 |
| [008](../spec_issues/SPEC-ISSUE-008-fabrication-gate-no-requirement-id.md) | 14.3 | Fabrication submission requires human sign-off | EDITORIAL | — |

**None blocks M0a.** Each concerns machinery that does not exist before the milestone named: the
Heuristic Miner is M7, the Novelty Auditor M3, design comparison M4, the artifact store M1.
Fabrication is outside v3.3 entirely, which is an accounting rather than an omission.

The one worth singling out is **006**. It is easy to assume `VER-003` covers it — both say "not a
single scalar". They do not overlap: `VER-003` is about the *cost* of a verification action,
P10 about the *quality* of a design. A system could hold a perfectly multi-dimensional `CostVector`
while ranking every candidate design by one scalar Q, and `T-VER-003` would pass.

## 5. Per-section reconciliation

§23.5's pass condition is "逐節列出該節 hard MUST 數與已登錄數,差額為 0 或有具名 DEFERRED".

After this audit every section in §6–§16 reconciles: either the difference is zero, or the residual
is a named spec issue. Sections not listed had no unregistered hard MUST.

| § | Disposition |
|---|---|
| 6.1–6.4, 6.13, 6.16–6.19, 6.21 | difference 0 |
| 6.5 | restates GH-003 (registered at 6.16) |
| 6.7, 6.14 | SHOULD only; no hard MUST |
| 6.8 | **registered this audit** → EVI-005 |
| 6.11, 6.15 | SPEC-ISSUE-004 |
| 6.20 | **registered this audit** → EVI-007 |
| 7.1 | descriptive table row (role scope overview), not a normative statement |
| 7.2 | **registered this audit** → LLM-002; inverted-retrieval half already SRC-002 |
| 7.5 | SPEC-ISSUE-005 |
| 7.6, 8, 8.1, 8.2.1 | difference 0 (8 is 8.1 at coarser granularity) |
| 9.1, 9.4, 9.5, 9.6 | difference 0 |
| 10.2.1 | **2 registered this audit** → SIM-003, DOM-SP-001 |
| 10.2.2 | **registered this audit** → SIM-001 |
| 10.3, 10.5.1, 10.7 | difference 0 |
| 10.4 | SPEC-ISSUE-006 |
| 10.6 | **registered this audit** → EPI-006 |
| 11, 12.4, 14.1, 14.4, 14.5, 15.4 | difference 0 |
| 12.3 | SPEC-ISSUE-007 |
| 13, 16 | SHOULD only; no hard MUST |
| 14.3 | egress half is SEC-001; fabrication half is SPEC-ISSUE-008 |

## 6. M0a exit gate status

§26.1's exit gate: *artifact/claim identity + bundle hash + schema/spec conformance pass; testable
without Actor/LLM/Simulator.*

| Condition | Evidence |
|---|---|
| `ART-001` content-addressed identity | 22 model tests + 8 schema-constraint tests, passing |
| `EVI-005` versioned condition schemas | 32 model tests + 13 schema tests, incl. payload triggers and comparator version binding |
| `EVI-006` canonical bundle hash | 25 model tests + 11 persistence tests; RFC 8785, cross-process stable under 4 hash seeds |
| `TST-002` traceability | 11 assertions, `T-SPEC-001` |
| `TST-003` registry coverage | 10 assertions, `T-SPEC-002` |
| Migrations 001–004, 008 (+004a, 008a) | 7 applied; re-run reports 0 pending |
| Testable without Actor/LLM/Simulator | 226 passed with no backend at all; no LLM or simulator code exists |
| No OPEN GATE spec issue against M0a | SPEC-ISSUE-001 and -003 both RESOLVED |
| `gate_profile: [postgres]` | 258 passed with postgres enabled, in CI's `backend` job |

All conditions are met on the evidence. **I have not flipped the status.** Under §23.5 the sign-off
is the maintainer's, and an agent marking its own milestone complete on the strength of its own audit
is the exact failure this gate is positioned to prevent.

## 7. What remains untrue after this audit

- **This audit covers §6–§16 only**, as §23.5 scopes it. §17's contracts are exercised by the
  requirement tests; §0–§5 and §18–§27 are governance and narrative.
- **Keyword scanning can miss a MUST expressed without a keyword.** A sentence stating an obligation
  in plain prose would not appear in the candidate list. I read each subsection's surrounding text
  while judging, but this is the residual risk of the method and it is not zero.
- **12 of 53 requirements have executable tests.** The other 41 are allocated to M0b–M5 and remain
  `TODO`; the executed-coverage gate will not permit those milestones to close without them.
- **No scientific behaviour is demonstrated.** M0a is identity and schema. No belief event, no
  hypothesis, no retrieval, no verification planning exists yet.

## 8. Requested decisions

1. **Sign off or reject this audit.** If accepted, `docs/milestones.yaml` may move `M0a` to `DONE`,
   at which point the executed-coverage gate begins enforcing it on every CI run.
2. **Rule on SPEC-ISSUE-004 through 008.** None blocks M0a; 007 blocks M1, which is the next
   milestone after M0b, so it is the most time-sensitive.
3. **SPEC-ISSUE-002** (`GH-xxx` missing from §23.2) remains open and editorial.
