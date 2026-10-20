# M1-P1 — locked, and what the next M1 slice inherits

Locked baseline: **`f8e5e9c02ee98ed2a7faa6f604347b84b88c773b`**
Decision: M2 independent review — **PASS, M1-P1 HARD-LOCK APPROVED** (2026-09-21)
Milestone: **M1 — Research Memory**, `IN_PROGRESS` — the slice is locked, the milestone is not
M0a / M0b: `DONE`, hard-locked, untouched by all three phases

| Phase | SHA | Content |
|---|---|---|
| M1-P1 | `7462917e844f2c570443deb6c1ac5f864a40c5b9` | the slice: `SPEC-ISSUE-013` → `v3.3-a17`, `EVI-010`, the ingestion vertical, the benchmark |
| Repair-1 | `23b47dd14af9422306f7e588cf33bf9f1a042f84` | four audit findings, each closed by an existing precedent (`v3.3-a18`, ADR-0012) |
| Repair-2 | `f8e5e9c02ee98ed2a7faa6f604347b84b88c773b` | three fail-opens, all the same shape — **this is the locked SHA** |
| this | this commit | the lock recorded, and this handoff |

Per-slice evidence is in [`M1-P1-readiness.md`](M1-P1-readiness.md): §1–§9 the original slice, §10
Repair-1, §11 Repair-2, §12 the decision and the locked list.

---

## The one rule

**Reopen M1-P1 only if a later slice produces a reproducible violation of a locked invariant.**

Not for cleanup. Not for a refactor that would read better. Not for a fourth repair. The fourteen
locked items and where each lives are tabulated in §12 of the readiness document; that table
exists because a lock a later slice cannot *locate* is a lock it will break by accident.

What holds the lock mechanically, so going red is unambiguous:

| | |
|---|---|
| Tests over the locked surface | **222 collected** across 14 files |
| Mutation battery | **29/29 killed** — and all 29 anchor on M1-P1 guards, so the battery *is* this slice's lock |
| Schema drift guard | §17 canonical blocks ↔ Pydantic models ↔ migration DDL, compared every run |
| Requirement ↔ Test | **60 ↔ 60**, enforced by `T-SPEC-001` against the parsed §25.3 / §26 tables |

The mutation anchors are on the guards, not on refusal-message branches. A later slice that
rewords a refusal will not silently disarm one; a later slice that removes a guard will fail the
battery by name.

---

## What M1 actually stands at

Eight of twenty-one requirements have tests. Thirteen have none.

| Status | Requirements |
|---|---|
| Covered by the locked slice | `EVI-002`, `EVI-003`, `EVI-004`, `EVI-009`\*, `EVI-010`, `SEC-003`, `OPS-004`, `UX-004`\* |
| Untouched, no tests | `EVI-007`, `EVI-008`, `LLM-001`, `OPS-001`, `SEC-001`, `SEC-004`, `SRC-001`, `UX-001`, `UX-002`, `UX-003`, `UX-005`, `UX-006`, `UX-007` |

\* `EVI-009` and `UX-004` are **half** requirements at this baseline. Both halves that remain are
the same missing entity: `EVI-009`'s Run reference and `UX-004`'s Job-level retry are `OPS-001`.

All eight stay `IN_PROGRESS`, not `DONE`. The lock is on the *implementation*, not on the
requirement statuses — a requirement reaches `DONE` when its whole §26 pass condition executes,
and three of these eight have a clause waiting on an entity that does not exist yet.

### M1's exit gate, item by item

> local document/run ingest; source-work dedup; delayed mock job resumes episode; all scientific
> LLM calls persist bundle+provenance; UX-001~007 tests pass.

| Clause | State |
|---|---|
| local **document** ingest | built and locked |
| local **run** ingest | not built — needs `OPS-001` |
| source-work dedup | built and locked (`EVI-004`) |
| delayed mock job resumes episode | not built — `OPS-001` |
| all scientific LLM calls persist bundle + provenance | not built — `LLM-001`, and no LLM slot is configured |
| `UX-001`~`UX-007` pass | one of seven, and that one is half |

---

## Recommended next slice: `OPS-001` — Jobs and Runs

Stated as a recommendation with its evidence, not as a decision. The maintainer picks.

**Why it is first: six things are waiting on it, and nothing else unblocks more than one.**

| Waiting on `OPS-001` | What it needs |
|---|---|
| `EVI-009` (IN_PROGRESS, half) | a Run entity so a MEASURED/SIMULATED attestation can reference a run, not only an artifact |
| `UX-004` (IN_PROGRESS, half) | Job idempotency, so "retry resumes at the failed stage" is a property of a record rather than of a test |
| `OPS-003` (IN_PROGRESS) | §26 names `run → artifact`; today the artifact is reached through span metadata rather than a checked reference — **R-11** |
| `UX-002` | `Job.max_attempts`, `next_retry_at`, and the retry path the whole requirement is about |
| `UX-001` | the state precedence is derived *from* Job / ExecutionSpan / Artifact / ReviewItem / Conflict |
| `UX-007` | Job queue depth is one of its four inputs |

It is also Appendix A's `006_jobs_runs.sql` — an unbuilt migration slot, so the schema shape is
already allocated rather than needing a number negotiated.

**And it is the natural owner of the biggest retained limitation.** There is no production
write-side repository contract (see below). `IngestionPipeline` takes `commit_rows` as an injected
callable, and the only implementations are in tests. A Job that resumes an ingestion has to
persist for real, from production code — so the slice that needs a production writer and the slice
that should build it are the same slice. Building the writer *now*, without a caller, would repeat
the pattern R-7, R-8 and R-10 all record: correct code, no live path, and a claim that outruns the
evidence.

**What `OPS-001` must not do to the lock.** Jobs will want to re-run ingestion. Re-running
ingestion over unchanged bytes must stay idempotent through the *derived* identity, not through a
new "skip if seen" branch — `tests/e2e/test_duplicate_ingest_postgres.py` holds that, and a Job
layer that dedupes above the pipeline would make those ten tests pass while the property they
describe stops being true of the system.

### After that, in rough dependency order

1. **`EVI-007` / `EVI-008`** — the embedding index and source-status check. `EVI-007` has a seam
   waiting for it (below). `EVI-008` needs a retracted/erratum fixture and `SourcePolicy`.
2. **`UX-001`, `UX-002`, `UX-003`, `UX-005`, `UX-006`, `UX-007`** — all become reachable once Job
   exists; `UX-003` and `UX-005` are the two that lean on things already built (ADR-0009's two-tier
   disclosure; `OPS-002`'s ReviewQueue, which is `DONE`).
3. **`LLM-001`** — needs a configured model slot, and note its §26 row is explicit that
   **admission alone is not enough**: an existing stored inference with no `InferenceProvenance`
   must be refused as the sole basis of a new belief transition. That is a read-side obligation on
   the belief path, which is the exact shape the P8 audit caught in `v3.3-a12`.
4. **`SRC-001`, `SEC-001`, `SEC-004`** — all three sit on the external boundary. `SRC-001`'s §26
   row uses *fake* connectors, so it is testable with no network; `SEC-001` and `SEC-004` need
   something to egress to and something to classify.

---

## What is already built and waiting for a caller

A later slice should look here before writing anything new. Each of these is finished, tested, and
has no live path — which is why none of them is claimed `DONE`.

| Seam | For | State |
|---|---|---|
| `RetrievalRepresentation` + `009a` / `009b`, `evidence/retriever.py` | `EVI-007` | The retrieval **boundary** is built and locked: candidates carry no body, and `CandidateResolver` re-loads every unit by identity. There is no embedding index. `IndexDivergence` already reports a stale or tampered index without letting it affect the evidence. |
| `IngestionPipeline(commit_rows=…)` | `OPS-001` | The write seam. Production implementation absent by design — the parameter exists because `OPS-004` needed the fault-injection point to be injectable. |
| `PostgresEvidenceUnitReader` | anything reading evidence | The read boundary, locked. Deliberately a reader: no cache, no unit of work, no write path. |
| `core/access.can_read_artifact` | `SEC-002`, **R-7** | Has a seam in the admission gate and is exercised end to end through it — but the wiring lives in the e2e test, because there is no production composition root. Narrower than "nothing calls the gate", not yet closed. Worth an explicit maintainer look when a composition root appears; **not reclassified here**. |
| `RefusalReason` (17 codes) | `UX-006` | A versioned `MessageCatalog` keyed by `reason_code` is exactly what `UX-006` requires, and this slice accumulated seventeen machine-readable codes that are already stable and tested. |
| `core/critique_gate.evaluate_dispatch` | M3/M4, **R-8** | Correct behaviour, no integration point. |
| `core/dispatch.dispatch_action` + budget gate | **R-10** | Has a caller; the caller dispatches only mocks. Closes when a real ingestion/LLM path runs through it. |

---

## Retained limitations — not closed, and not to be read as closed

The five from readiness §11 carry forward verbatim. The first is restated because it is the one
most likely to be misremembered:

1. **There is no production write-side repository contract for artifacts or evidence units.** The
   duplicate-ingest tests supply their own `commit_rows` / `_persist`. What they establish is that
   **the pipeline/schema composition supports idempotency when the persistence seam implements the
   required conflict semantics** — not that a writer exists which implements them. The read side
   has a boundary; the write side does not.
2. **Admission re-parses the artifact**, now with a registry lookup on top. Scoped to scientific
   admission. The only safe optimisation is a cache *of the re-derivation*, keyed on
   `(artifact_id, parser_version, segmenter_version, token_limit)`.
3. **`EVI-009`'s Run half and `UX-004`'s Job-level retry** are bound to `OPS-001`.
4. **Re-segmentation is not representable**, by design (ADR-0012). A changed boundary set produces
   a different id at the same structural path and hits the unique path index — the loud failure is
   the intent, not a gap.
5. **The registry holds one parser version and one segmenter version.** Cross-version verification
   is structurally supported and exercised only by a synthetic second version. The first real
   second version will be the first genuine test of it.

Carried forward from earlier milestones, unchanged by this slice: **R-1** (no Lumerical seat),
**R-2** (no ground-truth benchmark set), **R-4**, **R-7**, **R-8**, **R-9**, **R-10**, **R-11**,
**R-12**.

---

## Governance state at the lock

| | |
|---|---|
| Spec | SAI 3.3, amendments `v3.3-a1` … `v3.3-a18` |
| Requirement ↔ Test | **60 ↔ 60** |
| Spec issues | all fifteen **RESOLVED**; no OPEN GATE issue names any milestone |
| ADRs | 0001–0012 Accepted; 0010, 0011, 0012 are the same shape at three depths |
| Migrations | **29** declared, `001` … `011g` |
| Obligation inventory | **84** occurrences, in sync, every delta 0 |

Repair-2 added **no** new Requirement or Test ID, no amendment, no ADR and no migration — all
three blockers were already determined by `v3.3-a18`, `EVI-010` and `SEC-002`, so they were code
defects rather than specification ambiguities. A clarification would only have redefined the
requirement around the shortcut.

`v3.3-a18` and ADR-0012 are settled and are not to be overturned by a later slice.

---

## Verification at the locked SHA

Run in the mandated order, PostgreSQL last, so the outcome report the ratchet reads is the one
from the run that enabled the gate.

| Gate | Result |
|---|---|
| `ruff format --check` / `ruff check` | 163 files / all checks passed |
| `mypy` (strict) | clean, **79** source files |
| Backend-free suite | **941 passed**, 450 skipped |
| Migrations from empty | **29 applied** |
| Migration idempotency | `applied: 29, pending: 0` |
| Full suite, `postgres` profile | **1391 passed** |
| Executed-coverage ratchet | ok ×4; DONE `['M0a','M0b']`, IN_PROGRESS `['M1']` |
| `update_status.py --check` | up to date |
| Spec conformance | **205 passed**; **60 ↔ 60**; drift / unbound / stale all empty |
| Obligation inventory | **84**, in sync |
| Mutation battery | **29/29 killed** |
| Benchmark | current, **framing unchanged** |
| CI run [`35538447883`](https://github.com/SpadesZ/laboratory-innovation-brain/actions/runs/35538447883) | head_sha `f8e5e9c…`, all 4 jobs `success` |

### Local counts vs generic CI counts — a two-test difference, not a regression

| Run | Backend-free | PostgreSQL | Spec |
|---|---:|---:|---:|
| Local, full history | **941** | **1391** | **205** |
| Run `35538447883`, generic jobs | 939 (452 skipped) | 1389 (2 skipped) | 203 (2 skipped) |

The two are `test_this_repositorys_enforced_history_is_clean` and
`test_the_enforcement_floor_is_a_real_commit_in_this_repository`, both carrying `_needs_history`
in `tests/spec/test_commit_message_hygiene.py`. The generic jobs check out at depth 1, so the
enforcement floor is not present and the range cannot be walked — skipping is the designed
behaviour, and asserting anyway is what failed CI the first time that gate landed.

The rule is still enforced: the dedicated **`Commit hygiene` job checks out at `fetch-depth: 0`**,
walked the whole enforced range, and passed. `test_the_ci_job_checks_out_enough_history_to_walk_a_range`
fails if that job stops existing or its checkout is shallowed, so the chain holds from both ends.
**Do not read 939/1389 as a regression, and do not "fix" it by making the skipped tests assert
unconditionally** — a green test that checked no commits is worse than an honest skip, because it
is believed.

---

## Operational notes

Dev database `lab_brain` still carries a superseded `005c` and still needs dropping and
re-creating rather than migrating forward; `scripts/migrate.py` refuses it with a drift error,
which is the check working. No applied migration was edited in any M1-P1 phase.

Scratch databases from the M1-P1 phases are disposable. Earlier phases list theirs in their own
handoffs.

Commits in this slice carry no AI authorship or signature trailer, and the `Commit hygiene` job
enforces that over the whole history range on every push.
