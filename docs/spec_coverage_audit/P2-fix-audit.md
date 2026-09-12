# Phase Audit — P2-fix: three blockers plus the maintainer spec patch

Date: 2026-09-12
Spec: SAI 3.3, amendment `v3.3-a1`
Milestone: M0a (IN_PROGRESS — **not** DONE; P3 remains unauthorized)
Requirements touched: ART-001, EVI-005, SIM-003 (new), TST-003
Scope: strictly the three named blockers and the two maintainer rulings. No new functionality.

## 1. Blocker 1 — EVI-005 payload validation in the database

**Confirmed as reported.** Migration 003 gives `conditions_schema_version` a foreign key, which
proves the declared version is *registered*. It says nothing about whether the `conditions` JSONB
conforms to it, so direct SQL could store `{"levle": 1.0}` against a perfectly valid version. A
record that looks fully specified and is not is exactly what makes condition-aware retrieval treat
incomparable data as comparable.

A CHECK constraint cannot express this — it may not reference another table. So a trigger.

| Artefact | Path |
|---|---|
| Implementation | `migrations/008a_condition_payload_validation.sql` |
| Apply order | `scripts/migrate.py` `APPLY_ORDER` (after 003, which creates the target tables) |
| Regression tests | `tests/integration/test_schema_constraints_postgres.py` |

`lab_brain_validate_conditions()` fires `BEFORE INSERT OR UPDATE OF conditions,
conditions_schema_version` on both `observations` and `attestations`. It enforces exactly the
subset the Python registry enforces: required keys present, keys absent from `properties`
rejected. No type checking, no nested schemas, no `$ref` — stated in the file header so the
absence is not later mistaken for a bug.

8 new tests: missing required (observation), undeclared key (observation), empty conditions,
missing required (attestation), undeclared key (attestation), plus **three positive controls** —
conforming observation, optional-field-omitted observation, conforming attestation — and one
proving `UPDATE` is covered, not only `INSERT`.

### Migration numbering

`008a`, not `009`. Appendix A reserves 001–012 and 009 is `009_vectors.sql`. The `a` suffix marks
an amendment to 008 rather than a new canonical migration. Editing the already-applied 008 was
rejected: the checksum guard in `migrate.py` exists to prevent exactly that, and routing around
one's own guard is worse than the numbering awkwardness.

## 2. Blocker 2 — comparator version binding

**Confirmed as reported.** The registry keyed comparators by `(domain, schema_id)` alone, so two
schema versions declaring different `comparator_version` values shared whichever comparator was
registered last.

The consequence is worse than a wrong comparison. `ConditionMatch` is persisted and later read to
explain why a belief transition was authorised. Under the defect, v1 conditions could be compared
under v2's tolerance rules while the stored match reported `tolerance_policy_version = c1` — the
record would attribute a decision to rules that were never applied.

| Artefact | Path |
|---|---|
| Implementation | `src/lab_brain/evidence/condition_schema_registry.py` |
| Regression tests | `tests/contract/test_comparator_version_binding.py` |

Binding is now: schema registration declares `comparator_version`; that version selects the
comparator. Three additional guards came out of thinking it through:

- **Fail closed on absent comparator.** Falling back to another registered one would apply
  undeclared rules silently.
- **Two implementations may not share one declared version.** A persisted match names only the
  version, so it must identify one implementation.
- **`compare()` re-checks** that the resolved comparator's `version`, the schema's
  `comparator_version` and the returned `tolerance_policy_version` all agree, and that the match's
  `schema_ref` is the one being compared under.

9 tests. The load-bearing one is
`test_v1_and_v2_reach_different_verdicts_on_the_same_level_difference`: c1 has zero tolerance, c2
has 1.0, and a 0.5 gap on `level` therefore yields `INCOMPATIBLE` under v1 and `EXACT` under v2.
Under the old binding these would have agreed. Also
`test_registration_order_does_not_decide_which_comparator_is_used` runs both registration orders,
since last-registered-wins was the precise mechanism of the defect.

## 3. Blocker 3 — `invalidate()` validator bypass

**Confirmed as reported.** `model_copy(update=...)` does not re-run validators, so
`invalidate(at=<before valid_from>)` produced an inverted validity interval.

Why it matters concretely: `as_of` replay selects `valid_from <= moment < valid_to`. An inverted
interval satisfies that for no instant, so the judgment disappears from every historical
reconstruction while the stored record looks properly closed, with a reason and an actor attached.
The belief state would be replayed without evidence the record claims to account for.

| Artefact | Path |
|---|---|
| Implementation | `src/lab_brain/core/models/relation.py` (`RelationJudgment.invalidate`) |
| Regression tests | `tests/unit/test_relation_invalidation.py` |

Now reconstructed via `RelationJudgment.model_validate(self.model_dump() | {...})`, which re-runs
every field and model validator. 7 tests: backdated close rejected, close at exactly `valid_from`
allowed (degenerate but ordered — the spec forbids inversion, not zero length), all other fields
preserved, original not mutated, `as_of` behaviour around the close instant, the epistemic
provenance rule re-runs, and closing an already-closed relation cannot invert it either.

## 4. Maintainer spec patch

### SPEC-ISSUE-001 — Reading B

§26's `T-SPEC-002` pass condition now reads: `statement_key` MUST be unique; each entry MUST
reference exactly one valid Requirement ID; one Requirement ID MAY be referenced by multiple
entries covering distinct statements in different sections.

The assertions in `conformance.py` did not change — they already implemented Reading B
provisionally. What changed is that they now rest on settled spec text rather than an agent's
reading. Docstrings in `conformance.py` and `test_normative_statement_coverage.py` updated to
quote the ruling instead of citing an open issue.

### SPEC-ISSUE-003 — Option 1, `SIM-003` added

| Change | Location |
|---|---|
| `SIM-003` requirement row | §25.3 |
| `T-SIM-003` matrix row | §26 |
| `52 ↔ 52` -> `53 ↔ 53` | change summary (line 28), §26, §25.3 arithmetic note |
| Amendment record | Version Notes, `v3.3-a1` |
| Milestone allocation | `docs/milestones.yaml`, M2 |
| Registry remap | `tools.typed_only.no_arbitrary_script` -> `SIM-003` / `T-SIM-003`, `spec_issue` removed |
| Static guard | `tests/unit/test_no_arbitrary_script_execution.py` |

The guard rejects `eval_script`-class callables and methods, parameters carrying script or code
text, and `eval` / `exec` / `compile` calls across `src/lab_brain`. It includes two non-vacuity
checks: one asserting the scan target is non-empty, and one probe file proving each pattern
actually matches the shape it claims to — a typo in a regex would otherwise leave the guard
permanently green.

**The guard is unmarked.** `T-SIM-003`'s pass condition also requires "every invocation resolves
through the typed ToolRegistry", which needs the registry to exist (M2). Marking it now would
claim a requirement discharged on half a pass condition — the same error corrected for SYS-001 in
P2. `SIM-003` therefore shows `TODO` against M2, and the guard runs from today anyway so the
forbidden shape cannot be introduced and later have to be removed.

Both issues are `Status: RESOLVED` **after** all spec, registry, milestone and code changes
landed, not before. `scripts/check_requirement_coverage.py` reads those headers, so a premature
flip would have silently unblocked M0a.

## 5. Test failures found and fixed during the fix

Two, both stale **tests** rather than defective code — worth recording because both were caused by
the intentional changes and neither was in the reported scope:

**`test_comparator_must_not_misreport_its_own_version`** registered `LyingComparator` on top of
`ToyComparator`, which the new "two implementations may not share one version" guard correctly
rejects. Rewritten to use its own registry with `LyingComparator` as the sole comparator.

**`test_requirement_count_drift_is_reported`** hardcoded `"**52 requirements"`. Now reads the
count from the parsed spec and decrements it. A guard needing a hand edit every time the spec is
amended is a guard that will eventually be edited into passing.

## 6. Evidence

```
backend-free profile     168 passed, 21 skipped
postgres profile         189 passed
migrations               6 applied
migrations idempotency   pending 0 on re-run
ruff check               All checks passed
ruff format --check      45 files already formatted
mypy (strict, 25 files)  Success: no issues found
executed-coverage gate   4/4 ok
spec conformance         79 passed (53 requirements / 53 tests)
```

The two profiles agree exactly: 168 + 21 skipped = 189.

## 7. What this audit does NOT establish

- **M0a is not DONE.** `EVI-006` (canonical `EvidenceBundle`) is unimplemented and is P3 scope,
  which is not authorized. The milestone remains `IN_PROGRESS`.
- **`SIM-003` is not discharged.** Static half only; the ToolRegistry half is M2.
- **§23.5 (2) Spec Coverage Audit not run.** The human review that every hard MUST in §6–§16
  reached the registry is still outstanding, due at the M0a gate.
- **Full JSON Schema semantics are not implemented** in the payload trigger, by design and stated
  in the migration header.
- **SPEC-ISSUE-002 remains OPEN** (editorial; `GH-xxx` missing from the §23.2 namespace table). It
  gates nothing.

## 8. Divergence risk worth flagging

`docs/spec/SAI_3.3.md` in this repository now carries amendment `v3.3-a1`. The original at
`../SAI_3.3_System_Analysis_with_AI_Laboratory_Innovation_Brain.md` does **not**. CI parses the
in-repo copy, so the repo is authoritative for conformance — but if the desktop original is ever
copied over it, the amendment is lost and the invariant silently reverts to 52 ↔ 52.
`T-SPEC-001` would catch the resulting inconsistency, though only after the fact.
