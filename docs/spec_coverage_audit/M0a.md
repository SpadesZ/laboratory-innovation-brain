# M0a Spec Coverage Audit — §23.5 (2)

Date: 2026-09-12 (rev 4 — completeness against the document; §9.1 closed)
Spec: SAI 3.3, amendments `v3.3-a1` ... `v3.3-a4`
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

### `hard_must` is judged, and keyword scanning fails in both directions

The count is not a keyword-match total. Both failure directions are real, and both are recorded
per section in `M0a_hard_must_counts.yaml`'s `basis` field:

| Direction | Examples found in this audit |
|---|---|
| **False positive** | line-splitting (§6.17's three matches are two rules); restatement (§6.5's table row repeats GH-003; §8.2's lifecycle diagram repeats §8.2.1 and §6.18); descriptive prose (§9.3's `不可逆` is a cost characteristic of fabrication, §7.4's cells describe role I/O) |
| **False negative** | obligations phrased with no keyword. §10.5's "「measurement 永遠最高」**不是** core 假設" and §8.2's "No LLM may directly assign a scientific transition" carry neither MUST nor 不得 |

Every section was read, not only scanned. That is why §10.5 counts 1 rather than 0.

### Completeness is checked against the document, not the registry

Rev 3 verified that every *registry* section inside §6–§16 appeared in the count file. Necessary,
and not sufficient: it can only confirm that sections someone had already registered were counted.
A section of prose reaching neither the registry nor the count file was invisible to it.

That hole was not hypothetical. §10.5.1's two MUSTs — INCOMPARABLE must not be coerced into an
ordering, and DomainPack MUST expose `compare` — were unregistered, and the subtree looked covered
because `fidelity.low_cannot_reject` had been filed at §10.5. That rule appears **nowhere** in
§6–§16 prose; its home is the §25.3 requirement table, where it is now registered.

So the section list is parsed from `SAI_3.3.md`. All **76** numbered headings in §6–§16
must appear in the count file, including the 36 whose count is 0 — "this section states no
obligation" is a reviewable claim, silence is not. Drift is checked in both directions, so a
section renumbered by an amendment cannot leave a stale row behind either.

### The arithmetic is executable

Judged counts live in `M0a_hard_must_counts.yaml`; coverage is derived from
`normative_statements.yaml` by `lab_brain.spec.coverage_audit`; and
`tests/spec/test_m0a_coverage_audit.py` recomputes every delta on each CI run. A row that does not
balance fails the build, as does an uncounted heading, a stale row, or a heading-format change that
would quietly empty the completeness check.

What remains human: the `hard_must` judgements, their recorded basis, and the sign-off.

## 3. Per-section reconciliation

Generated from the same data the test checks. 76 sections — every numbered heading in
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
| 7.2 | 2 | 2 | — | — | 0 |
| 7.3 | 0 | 0 | — | — | 0 |
| 7.4 | 0 | 0 | — | — | 0 |
| 7.5 | 1 | 1 | — | — | 0 |
| 7.6 | 1 | 1 | — | — | 0 |
| 8 | 0 | 0 | — | — | 0 |
| 8.1 | 2 | 2 | — | — | 0 |
| 8.2 | 0 | 0 | — | — | 0 |
| 8.2.1 | 2 | 2 | — | — | 0 |
| 9 | 0 | 0 | — | — | 0 |
| 9.1 | 5 | 5 | — | — | 0 |
| 9.2 | 0 | 0 | — | — | 0 |
| 9.3 | 0 | 0 | — | — | 0 |
| 9.4 | 1 | 1 | — | — | 0 |
| 9.5 | 1 | 1 | — | — | 0 |
| 9.6 | 1 | 1 | — | — | 0 |
| 10 | 0 | 0 | — | — | 0 |
| 10.1 | 0 | 0 | — | — | 0 |
| 10.2 | 2 | 2 | — | — | 0 |
| 10.2.1 | 2 | 2 | — | — | 0 |
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
| 14.4 | 1 | 1 | — | — | 0 |
| 14.4.1 | 1 | 1 | — | — | 0 |
| 14.5 | 2 | 2 | — | — | 0 |
| 15 | 0 | 0 | — | — | 0 |
| 15.1 | 0 | 0 | — | — | 0 |
| 15.2 | 0 | 0 | — | — | 0 |
| 15.3 | 0 | 0 | — | — | 0 |
| 15.4 | 2 | 2 | — | — | 0 |
| 16 | 0 | 0 | — | — | 0 |
| 16.1 | 0 | 0 | — | — | 0 |
| **Total** | **64** | **62** | **2** | 1 | **0** |

**Every delta is 0.** 64 hard MUSTs = 62 registered live + 2 named deferred. The single
SHOULD-level entry (§6.21) is excluded from coverage and shown for transparency.

### Section notes

**§9.1 — the round-2 blocker, now closed.** Five hard MUSTs, not four. The fifth is
"Disagreement metrics ... MUST be deterministic, versioned and defined over the declared
OutcomeSpace", which had no registry entry. Now `disagreement.metric.deterministic_versioned` →
`VER-008` (amendment `v3.3-a4`).

It was **not** merged into `VER-004`. `VER-004` governs which *outcomes* count as plausible — they
must come from a declared, versioned OutcomeSpace. `VER-008` governs the *metric* that ranks how
far two predictions disagree. A planner could draw every outcome from a properly declared
OutcomeSpace and still rank them with an unversioned, non-deterministic distance function, and
`T-VER-004` would pass. Ranking that cannot be reproduced makes a VerificationPlan unexplainable
after the fact, which is what `VER-005`'s determinism prevents one layer up.

**§10.5 and §10.5.1 — re-attributed.** §10.5 carries one hard MUST: authority is a function of
(method, calibration, validated_range fit) and "measurement is always highest" is *not* a core
assumption (P27). §10.5.1 carries two: INCOMPARABLE must not be silently coerced into an ordering,
and DomainPack MUST expose `compare`. Both §10.5.1 MUSTs are now registered against `EPI-004`, and
`fidelity.low_cannot_reject` moved to §25.3, its actual prose home.

**§6.17 — one of two deferred.** `independence.dependence_unknown_counts_zero` is live;
`independence.basis.beyond_work` is DEFERRED with `review_at: M4_EXIT`, because v3.3 models
WORK-level independence only. Counted 1 live + 1 deferred, not 2 covered.

**§6.21 — two hard MUSTs, three entries, one excluded.** Retraction check status recorded even
when UNKNOWN (`EVI-008`) and a novelty status without a coverage record is unauditable
(`SRC-003`). The third entry, `source.retraction.check_performed`, is SHOULD-level.

**§14.3 — two hard MUSTs, one live and one deferred.** The external query gate is
`privacy.query_gate.no_private_identifiers` → `SEC-001`, distinct from §14.1's classification
rule: a sanitized query over RESTRICTED_NDA material still must not carry private identifiers. The
fabrication gate remains DEFERRED under `SEC-002` with `review_at: FIRST_FABRICATION_CAPABILITY` —
a trigger, not a date.

**§15.4 — closed in round 1 of this fix.** `debate.groupthink_reduction.falsifiable` → `LLM-002`
registered at its own section, not borrowed from §7.2: that entry obliges the metrics to be
*recorded*, this one obliges the claim to be *refutable*.

**§6.6 — flagged judgement.** Counted 0. The graph-DB migration trigger ("遷移由實測 traversal
workload 觸發") is phrased as a design note and recorded in ADR-0001 under P20, not as an
implementation obligation with a Requirement. A stricter reading is defensible; the count is 0 and
the basis says so, so a reviewer can overrule it rather than having to discover it.

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
| §23.5 (2) coverage audit | this document; 76 sections (every §6-§16 heading), 64 hard MUSTs, every delta 0, recomputed by `tests/spec/test_m0a_coverage_audit.py` |

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
