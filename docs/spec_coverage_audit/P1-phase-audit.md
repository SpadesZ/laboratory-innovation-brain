# Phase Audit — P1 (M0a-1): Repository skeleton + Spec CI

Date: 2026-09-12
Spec: SAI 3.3
Milestone: M0a (IN_PROGRESS — **this is not the M0a exit gate**)
Requirements in scope: TST-002, TST-003
Auditor: implementation agent (self-audit)

> The formal M0a Spec Coverage Audit under §23.5 (2) is due at **P3**, after `EvidenceBundle`
> lands. This record covers only the P1 slice.

## 1. Deliverables vs plan

| Planned | Delivered | Evidence |
|---|---|---|
| Repo skeleton per §18 | Yes, M0a subset only | `pyproject.toml`, `compose.yaml`, `Makefile`, `scripts/dev.ps1` |
| Normative Statement Registry | 77 statements, all 52 requirements covered | `docs/normative_statements.yaml` |
| Milestone catalog | 7 milestones, 52 requirements partitioned exactly once | `docs/milestones.yaml` |
| T-SPEC-001 (TST-002) | 10 assertions | `tests/spec/test_requirement_traceability.py` |
| T-SPEC-002 (TST-003) | 9 assertions | `tests/spec/test_normative_statement_coverage.py` |
| IMPLEMENTATION_STATUS.md | Generated table + environment + risks | `scripts/update_status.py` |
| ADR-0001…0009 | All 9 written, Accepted | `docs/adr/` |

Directories named in §18 but **not** created: `learning/`, `interfaces/dashboard`,
`integrations/lims`, `retrieval/graph_paths`, `domains/silicon_photonics/fabrication`,
`deployment/lab_server`, `deployment/air_gapped`. All are excluded by §18.1 or by the M5–M8
deferral. Left absent rather than stubbed — an empty package implies a contract that does not
exist yet.

## 2. Test evidence

```
ruff check src tests scripts   All checks passed
mypy (strict, 5 files)          Success: no issues found
pytest                          20 passed
```

### 2.1 Non-vacuity check

"20 tests pass" is not evidence that the tests constrain anything. Nine violations were
injected one at a time and the specific guarding assertion was required to fail:

| Injected violation | Result |
|---|---|
| Test marked with a Requirement ID the spec does not declare | CAUGHT |
| Marker pair absent from the §26 matrix | CAUGHT |
| Test declaring only one of the two markers | CAUGHT |
| Registry entry citing an unknown Test ID | CAUGHT |
| Registry entry with neither test nor deferral | CAUGHT |
| Deferral with no `review_at` | CAUGHT |
| Milestone catalog dropping a requirement | CAUGHT |
| Milestone marked DONE with an untested requirement | CAUGHT |
| Spec declaring a requirement count that disagrees with its tables | CAUGHT |

9/9 caught, 0 vacuous. Repository state verified restored afterwards (52 requirements,
77 statements, 52 allocations, 20 tests passing, probe file removed).

## 3. Agent operating rules (§23.1)

| Rule | Status | Note |
|---|---|---|
| AGT-001 read spec before coding | Met | Full 3070-line document read; §17, §23–26, Appendices A/F/G/I used directly |
| AGT-002 one acceptable slice | Met | No storage, schema, cognition or UI code in this slice |
| AGT-003 status file consistent | Met | Generated, and `test_status_freshness.py` fails CI if stale |
| AGT-004 no silent schema drift | N/A | No migrations in this slice |
| AGT-005 ADR for deviations | Met | 9 ADRs; the pip-vs-`uv` choice is against an informative file listing, not a normative statement, so no ADR raised |
| AGT-006 CLI + tests before dashboard | Met | No UI |
| AGT-007 CI without license/network/cloud | Met | Bare `pytest` needs no Postgres, seat or network; gated markers deselect and say so |
| AGT-015 do not resolve spec conflicts silently | Met | Two ambiguities recorded below rather than quietly decided |

## 4. Findings

### F-1 `GH-xxx` namespace missing from §23.2 — spec defect, non-blocking

§25.3 and §26 define `GH-001`, `GH-002`, `GH-003`. The §23.2 Requirement ID namespace table
does not list `GH`. This is an **incomplete list**, not two normative contracts contradicting
each other, so AGT-015 does not require blocking the slice.

Handling: `GH` added to `REQUIREMENT_NAMESPACES` in `spec/parser.py` with an inline comment
pointing at this finding. Recommend a spec issue adding `GH-xxx` to §23.2.

### F-2 T-SPEC-002 "unique Requirement IDs" is ambiguous — implemented reading recorded

Read literally as "each Requirement ID appears in at most one registry entry", the §23.6
excerpt fails its own rule: `VER-006` appears twice (`prediction.typed.contract`,
`sufficiency.hypothetical.sideeffect_free`) and `UX-001` appears twice
(`ingestion.state.derived`, `ingestion.duplicate.work_vs_bytes`).

One requirement legitimately covers several distinct MUSTs in different sections, so the
literal reading cannot be what is meant. Implemented reading: **statement keys are unique, and
each entry names exactly one resolvable Requirement ID.** Rationale recorded in the test
module docstring so the next reader does not have to rediscover it.

This is the kind of thing an agent would "fix" by writing a test the spec's own example
fails. Recorded instead.

### F-3 §10.2 typed-tools-only has no dedicated Requirement ID

P19 and §10.2 state a hard MUST (no arbitrary `eval_script`). None of the 52 requirements
targets it directly. Registered as `tools.typed_only.no_arbitrary_script` against `VER-002`,
whose test — "a backend with no capability descriptor cannot be planned" — is the nearest
enforcement point. The mapping is defensible but indirect. Flagged for the M0a gate audit;
a spec issue adding a dedicated ID would be cleaner.

### F-4 Spec test IDs are not yet bound to executing tests

50 of 52 requirements have no test. Expected at this point, and the reason
`docs/milestones.yaml` carries a `status` field: `test_completed_milestones_have_real_tests`
turns marker presence into a hard gate the moment a milestone flips to DONE, so a milestone
cannot be declared complete on prose.

## 5. What this audit does NOT establish

- **Registry completeness against the prose.** §23.5 (2) is explicit that this cannot be
  linted. Not attempted here; due at the M0a gate (P3).
- **Any scientific or storage behaviour.** No models, no migrations, no repositories exist yet.
- **Postgres conformance.** No instance provisioned (Risk R-5).
- **The real-environment half of TST-001.** No Lumerical seat (Risk R-1).

## 6. Verdict

**P1 PASS.** TST-002 and TST-003 have executable, non-vacuous coverage. The traceability
harness that makes every later slice auditable is in place and verified against injected
violations.

Proceed to **P2 (M0a-2)**: core identity models and migrations 001–004, 008
(`SYS-001`, `ART-001`, `EVI-005`).

Open findings carried forward: F-1, F-2, F-3 to the M0a gate audit.
