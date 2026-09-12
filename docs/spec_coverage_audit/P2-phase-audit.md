# Phase Audit — P2 (M0a-2): scientific identity models and migrations

Date: 2026-09-12
Spec: SAI 3.3
Milestone: M0a (IN_PROGRESS — **not** the M0a exit gate; that is P3)
Requirements in scope: ART-001, EVI-005
Auditor: implementation agent (self-audit)

## 1. Deliverables

| Planned | Delivered | Evidence |
|---|---|---|
| Core identity models | Artifact, SourceWork, Claim, Observation, Attestation, RelationJudgment | `src/lab_brain/core/models/` |
| Condition schema registry | Registry + versioned refs + domain comparator protocol | `src/lab_brain/evidence/condition_schema_registry.py` |
| Repository contracts | Protocols + in-memory implementation | `src/lab_brain/core/repositories/` |
| Migrations 001–004, 008 | Written **and applied** to PostgreSQL 17 + pgvector | `migrations/`, `scripts/migrate.py` |
| T-ART-001 | 22 model tests + 8 schema-constraint tests | `tests/contract/`, `tests/integration/` |
| T-EVI-005 | 23 model tests + 5 schema-constraint tests | same |

## 2. Evidence

```
ruff check / format --check      All checks passed / 42 files formatted
mypy (strict, 25 files)          Success: no issues found
pytest (no backends)             146 passed, 13 skipped
pytest (postgres profile)        159 passed
check_requirement_coverage.py    4/4 ok, 4 requirements with a passing test
```

The two profiles agree: 146 + 13 skipped = 159. No test result depends on how the suite was
invoked.

## 3. Design decisions worth recording

### ART-001 is enforced by construction, then again by the database

`artifact_id` is derived from `content_hash` by a total, injective function, recomputed on every
construction and rejected on mismatch. "Same bytes, two ids" and "one id, two contents" are
unrepresentable rather than discouraged.

The database repeats the rule independently — `artifact_id = 'art:' || content_hash` is a CHECK,
`content_hash` is UNIQUE. This is not redundancy for its own sake: a bulk load, a migration
script or a future service writing SQL never passes through Pydantic. An invariant that holds
only in the application layer holds only for callers who use that layer.

### Lineage defaults to self rather than being nullable

Every artifact is revision 1 of its own lineage unless it says otherwise. The nullable
alternative requires mutating the first artifact once a second revision appears, and until that
happened a lineage query would not return the original.

`next_revision` rejects identical bytes: the same content is the same artifact, not version n+1
of itself.

### EVI-005 is enforced in three places that cannot disagree

Model parses the reference eagerly; repository validates conditions before storing; the column
is a foreign key to `condition_schemas(schema_ref)`. Validating on read would let unauditable
records accumulate and fail only when somebody tried to use them.

Undeclared condition keys are **rejected**, not ignored. A misspelled key that is silently
dropped produces a record that looks fully specified and is not, and condition-aware retrieval
would then treat it as comparable.

### Comparison semantics stay domain-owned

Core validates structure and refuses to compare at all without a registered DomainPack
comparator. It never decides whether 1549 nm and 1550 nm are the same condition. A comparator
that misreports its own version is rejected — a ConditionMatch that cannot be attributed to real
rules is not reproducible.

### Structural enforcement of the abstention discipline

`EvidenceField` rejects a value behind an `UNKNOWN` or `NOT_REPORTED` status. That combination is
the hallucinated completion EVI-002 forbids, with the status saying "we do not know" while the
field offers something to read.

### Epistemic relations require provenance

`SUPPORTS` / `CONTRADICTS` / `TESTS` / `PREDICTS` move belief, so each must name supporting
attestations, an inference, or an actor — as a model validator *and* as a CHECK constraint.
Relations are bitemporal and never deleted; invalidation records a reason, because a silently
removed judgment is indistinguishable from one that was never made.

## 4. Corrections to earlier work

### SYS-001 reallocated from M0a to M0b

A P1 allocation error. Its §26 pass condition is "rejects bypass from cognition directly to
**EpistemicState** update **or** support arrays on Attestation/**Hypothesis**". Neither
`EpistemicStateProjection` nor `Hypothesis` exists in M0a, so only half of it is exercisable
here. Under the executed-coverage gate that would have meant claiming a requirement discharged
on half a pass condition — the exact pattern the P1 reviews were hunting.

The no-support-arrays invariant is enforced on the M0a models regardless, as an unmarked
architecture test. The marked T-SYS-001 asserts both halves in M0b.

### Harness defect: executed-coverage guards were not hermetic

Found by running the suite under both gate profiles rather than one. The guards in
`test_executed_coverage_guards.py` passed `{**os.environ, **env}` to their subprocesses, so with
`LAB_BRAIN_TEST_POSTGRES=1` set in the outer run the gated-skip fixture stopped being skipped and
that guard silently stopped guarding.

The subprocess environment is now scrubbed of every `LAB_BRAIN_TEST_*` variable before
`env_extra` is applied. A test of the harness that depends on the ambient shell is testing the
shell.

This is worth noting as a pattern: the defect was invisible under single-profile testing. Both
profiles are now run before each commit.

### CI could never have validated M0a

Discovered while reviewing the gate: the CI workflow had no PostgreSQL service, so the 13
schema-constraint tests were always skipped there. Since M0a–M4 declare
`gate_profile: [postgres]`, the executed-coverage gate could never be satisfied in CI — meaning
the final step of the ratchet would have fallen back to a local run, which is precisely the
"agent reports it passed" situation the gate exists to remove.

Added a third CI job, `backend`, with a `pgvector/pgvector:pg17` service. Kept separate from
`quality` so the AGT-007 guarantee stays observable: `quality` proves the suite is green with no
backend at all, `backend` proves the backend-dependent half. It also asserts migration
idempotency — a second `migrate.py` run must apply nothing.

## 5. Risk register movement

| Risk | Before | After |
|---|---|---|
| R-5 No PostgreSQL instance | open | **CLOSED** — PG17 + pgvector running, 5 migrations applied, 13 constraint tests passing |

## 6. What this audit does NOT establish

- **Registry completeness against the prose** — §23.5 (2) human gate, due at P3.
- **EVI-006** — canonical `EvidenceBundle` is P3; M0a is not complete.
- **Belief state of any kind** — no events, no projection, no TransitionPolicy until M0b.
- **Any ACL enforcement** — `actor_id` columns and foreign keys exist so they are not
  retrofitted, but nothing checks authorization until P4.
- **The real-environment half of TST-001** — no Lumerical seat (R-1).

## 7. Open question carried forward

**Cross-project identical bytes.** `artifact_id` is globally content-addressed while
`Artifact.project_id` is a single value, so the same PDF ingested into two projects is one row
with one project and one sensitivity label. Today that is harmless — nothing enforces ACL yet.
By P4 (SEC-002) it must be resolved, because surfacing project A's `RESTRICTED_NDA` artifact to
project B through content-hash duplicate detection would be a real SEC-001 leak. Recorded now
rather than discovered then.

## 8. Verdict

**P2 PASS.** ART-001 and EVI-005 have executable coverage at both the model and schema levels,
proven under the gate profile M0a declares. Two defects in earlier work were found and fixed
rather than carried forward.

Next: **P3 (M0a-3)** — canonical `EvidenceBundle` + hash (EVI-006), then the M0a gate audit,
which must also resolve SPEC-ISSUE-001 and SPEC-ISSUE-003.
