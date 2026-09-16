# P13 — the `v3.3-a14` invariant moves to the commit boundary

Baseline: `a5ca44f77244c879320a705c1ff2eec1c5d70e6f` (P12, **FAIL**, one persistence-atomicity P0).

The P12 audit's verdict was narrow and correct: `review_resolve_and_close_conflict` is
directionally right, and `v3.3-a14`'s cross-table invariant was not enforced for arbitrary database
writes. Nothing in `011a`–`011c` was rewritten. No applied migration was edited. No spec amendment
was needed — `v3.3-a14` already states the obligation; it was not being enforced.

| Phase | SHA | Content |
|---|---|---|
| 0 | `d95f73e7ea3ceea73274d54ef070546e13d0509b` | P12's local lint fix, previously **unpushed** |
| 1 | `09350f7e425f93a0f35083bdf5454973b4b7c3ce` | `011d`: the invariant at COMMIT, plus the raw-SQL and concurrency suites |
| 2 | this commit | this handoff |

**One baseline note that cost the first ten minutes.** The P12 handoff reported
`d95f73e7ea3ceea73274d54ef070546e13d0509b` as a lint-fix SHA, and the audit reported remote `main`
as still `a5ca44f...`. Both were true: the commit existed **locally and had never been pushed**.
`git fetch` settles this in one command and the fetch is why this session started with one.

---

## The P0, reproduced before it was fixed

Reasoning about whether a bypass exists is how the P11 hole survived a handoff. So both halves were
demonstrated committing, on a scratch database migrated through `011c` and nothing further:

```
BEFORE 011d (migrations through 011c)
  P0-A  COMMITTED  -> review=APPROVED  conflict=UNDER_REVIEW
  P0-B  COMMITTED  -> review=QUEUED    conflict=RESOLVED

AFTER 011d
  P0-A  refused at commit: review rvw:1 is APPROVED but conflict cfl:1 is still UNDER_REVIEW
  P0-B  refused at commit: conflict cfl:1 is RESOLVED while review rvw:1 is still QUEUED
```

**Why both were reachable.** Every guard `011c` added lives inside a function, and a function is
something a writer can decline to call. `review_items_terminal_needs_a_decision` asks whether a
terminal review *has* a `decision_ref` and never looks at the conflict, so P0-A committed with a
perfectly valid resolution row. `conflicts_only_close` validates closure fields and immutability,
so a bare `UPDATE conflicts` never reached `conflict_close`'s review check and P0-B committed too.
This is `011a`'s own opening paragraph, for the fifth time: a guard that holds for callers who go
through the guard holds for callers who go through the guard.

---

## `011d`

**A deferred constraint trigger on each of the three tables**, all calling one function,
`review_conflict_invariant_assert(project_id, review_id)`.

**Why deferred, and this is the part worth being precise about.** The one *valid* operation
necessarily passes through a forbidden intermediate state: inside
`review_resolve_and_close_conflict` the review is terminalized before its conflict is closed, so
between those two statements the row pair reads exactly like P0-A. A per-statement trigger would
look stricter, pass every bypass test, and make the only correct way to resolve a review
impossible. The obligation is about what survives COMMIT. `test_an_intermediate_half_state_inside_one_transaction_is_allowed`
pins that down from the other side, and a companion test asserts the intermediate state is never
visible to another session — "permitted inside one transaction" must not quietly become
"observable while it lasts".

**What the function checks**, all against re-read committed values rather than a trigger's `NEW`:

- outstanding (`QUEUED`/`ASSIGNED`) → no `decision_ref`, and every linked conflict still
  `OPEN`/`UNDER_REVIEW`;
- terminal → `decision_ref` exists, resolves to a real row, that row's `review_id` is **this**
  review, project matches, `outcome` equals `status`, every linked conflict is terminal, and each
  conflict's `resolution_event_id` is that resolution's `belief_revision_event_id`.

**"Linked" means `conflicts.review_id`,** and the alternative is defensible enough to say why it
was rejected. That is the relation §8.2.1 creates, the one `v3.3-a14` means, the one
`conflict_close` consults, and the only one that is a checked, project-scoped, write-once foreign
key. §17.19.3's `ReviewItem.subject_id = conflict_id` is the same fact's other direction on the
supported path, but it is not gating: `subject_id` is deliberately not a foreign key (`011b`),
several reviews can name one conflict as subject after a raw-SQL insert, and treating that as
gating would let a stray queued row deadlock a conflict its real reviewer had already resolved.

**A loop, not a single row.** `conflicts.review_id` is not unique, and
`review_resolve_and_close_conflict`'s `SELECT conflict_id INTO v_conflict_id FROM conflicts WHERE
review_id = ...` takes one row when two match — so a second conflict pointed at the same review
would be left open behind a terminal review. That is P0-A by another route, and it has a test.

**Pre-flight guard**, the same shape as `011b`'s before it added the review foreign key: the
migration refuses to install over a database that already holds a forbidden pair. A constraint
added over data that violates it means less than it says, and there is no correct value to
reconcile such a row against.

### The mutation that survived, and what was done about it

Nine mutations, eight red immediately. The ninth — the `conflicts` trigger re-reading `review_id`
from the table instead of trusting `NEW` — **passed green**. The draft had written that re-read as
obvious hygiene for a deferred trigger, and it turned out to guard a state the schema cannot
produce:

- `conflicts_only_close` makes `review_id` writable exactly once, from NULL, so any statement that
  establishes the link carries the value in `NEW` and queues its own event;
- the only remaining gap would be "close an unlinked conflict, then link it in the same
  transaction", and the second half is refused outright — a terminal conflict admits no further
  UPDATE.

Both were probed against the real database rather than argued. The branch was removed, with the
reasoning left in the migration. This is the P12 blank-rationale lesson applied in the other
direction: a check nothing can reach is not a stronger guarantee, it is an untested claim. The
re-read that *is* load-bearing lives in `review_conflict_invariant_assert`, which reads every row
it judges — that is what makes deferring the check to COMMIT correct, and deleting it goes red.

Nine of nine red after the rework. SQL mutations were proven additively: the migration is mutated,
applied to a uniquely-named scratch database built from empty, and restored.

---

## The tests

`tests/integration/test_review_conflict_commit_invariant_postgres.py`, **22 tests**, none of which
go through a repository except the one that is supposed to. A test calling `SqlConflictStore` would
exercise `conflict_close` again — the function that was already right. The bug was everything that
reaches the tables without it, so these speak SQL and assert on `commit()`.

The eight the audit required, plus what they turned up on the way: all three closing statuses
against both outstanding statuses; a resolution deleted out from under a terminal review; a
resolution's `outcome` and `belief_revision_event_id` rewritten after the fact — the quietest way
to change what a human decided, since neither row a reader would think to check is touched.

### Real concurrency, and why P12's was not

P12's atomicity test called the function twice in a row on one connection. A second call after the
first has committed is a duplicate, not a race: it never has two transactions holding conflicting
intentions at the same time, which is the only situation where a lost update or an orphan appears.
Both races now use two independent connections and a `threading.Barrier`.

- **Resolution race** — different resolution ids *and* different closure events per session, so a
  lost update anywhere in the chain shows up as two records disagreeing about which decision closed
  the block. Exactly one winner; `review.decision_ref`, `resolution_id`,
  `belief_revision_event_id` and `conflict.resolution_event_id` all describe it.
- **Escalation race** — different proposed review ids. Exactly one review row, the conflict points
  at it, no orphan, and the retry returns the winner. The loser may raise or observe the winner
  depending on when its snapshot was taken; both are correct, and asserting which one happens would
  be testing the scheduler.

### Two existing tests were rewritten, because they depended on a state the spec forbids

`test_an_unrelated_same_project_event_is_not_closure_proof` and
`test_another_reviews_resolution_event_is_not_closure_proof` both needed a genuinely resolved review
so `conflict_close` would reach its traceability branch — and both got there by **committing**
`status='APPROVED', decision_ref=...` while the conflict sat at UNDER_REVIEW. That is P0-A used as
setup. They passed because nothing enforced the pair.

The rewrite keeps the resolution completely genuine and never commits it: the terminal review lives
inside an unfinished transaction, which is where the supported path puts it too, and
`conflict_close` raises on the substituted event before COMMIT is attempted. The assertion is
stronger than before — the old version proved a substitution was refused *from a state the database
should not have allowed to exist*.

---

## Verification

Run in the mandated order, with the full PostgreSQL profile last so the outcome report the ratchet
reads is the one from the run that enabled the gate.

| gate | result |
|---|---|
| `ruff check src tests scripts` | clean |
| `ruff format --check` | clean, 106 files |
| `mypy` (strict) | clean, 50 source files |
| Backend-free suite | **686 passed / 290 skipped** (AGT-007) |
| Migrations from empty | **21** declared, 21 applied |
| Migration idempotency | `pending 0` on re-run; `011d` re-appliable, still exactly 3 constraint triggers |
| Full suite, `postgres` profile | **976 passed**, 0 failed |
| Executed-coverage ratchet | exit 0 |
| `update_status.py --check` | up to date |
| Spec conformance / traceability | 149 passed, **59 ↔ 59** |
| Obligation inventory | 72 occurrences, in sync |
| Mutations | 9 SQL, all red after the ninth was removed rather than kept untested |

---

## Requirement status — unchanged, and deliberately

Derived by `update_status.py`, not hand-set.

| ID | Status |
|---|---|
| `EPI-003` | IN_PROGRESS |
| `EPI-004` | IN_PROGRESS |
| `EPI-005` | IN_PROGRESS |
| `EPI-006` | IN_PROGRESS |
| `SYS-001` | TODO |
| `UX-005` | TODO |

**EPI-004 and EPI-006 stay IN_PROGRESS for P12's reason, which this slice does not touch.** Both
§26 rows say the ReviewItem is **auto**-created, and nothing calls the escalation seam
automatically. The vertical is persisted, is now genuinely atomic, and still has to be *invoked* —
the orchestration that would invoke it is `SYS-001`'s episode loop, which is TODO. Making a
persistence invariant unbypassable is not the same as automating the caller, and marking either
DONE would claim an automation that is one caller short.

The new test file carries `EPI-006` / `T-EPI-006` and **one** pair, not two. Markers multiply out,
so declaring EPI-004 as well would claim `(EPI-004, T-EPI-006)` — a pair §26 does not map, and
T-SPEC-001 says so. T-EPI-006's row is the one naming "a Conflict linked to the auto-created
ReviewItem" and "resolving a Conflict without a resolution_event_id is rejected". EPI-004's side of
the same invariant keeps its own pair in the e2e loop.

---

## For the next session — M1, still LOCKED, still not started

No chunker and no embedding index exists, and none was built here. The seven requirements carry
forward verbatim and are **not** to be replaced with LangChain-style fixed-token chunking:

1. **Minimum evidence boundary** — the smallest complete boundary that can independently support
   one claim or observation. Conditions and results must not be split apart.
2. **Structure-first** — section / subsection / paragraph / table / figure-caption / code-log block
   take priority over token counts.
3. **Table/figure context binding** — a table retains header, unit and row context; a figure is
   bound to its caption **and** the relevant surrounding text.
4. **Conditions + locator + provenance** — a chunk resolves back to an Artifact/SourceWork locator
   and retains conditions, units and method/provenance.
5. **Fixed-token only as fallback** — secondary subdivision or a token safety limit when an
   evidence unit is too large. Never the primary splitter.
6. **Scientific retrieval benchmark vs a fixed-token baseline** — a fixed fixture measuring at
   minimum evidence-boundary completeness, correct locator recovery, condition retention,
   table/figure retrieval, and candidate recall/precision.
7. **Vectors do candidate retrieval only** — a vector chunk is **not** the evidence, and the final
   `EvidenceBundle` still passes condition/source/authority filtering. Treating a chunk as the
   evidence body would make the epistemic record depend on an embedding model's version, which is
   what EVI-005's comparator-version binding exists to prevent elsewhere.

### Still open, unchanged from P12

- **`SYS-001` episode loop** is the blocker on EPI-004/EPI-006 reaching DONE.
- **`EPI-004`'s remaining gap** is only the automatic invocation; the seam is `core/escalation.py`
  plus `SqlReviewItemStore.escalate_authority_conflict`.
- **`UX-005`** needs ReviewQueue depth and human-review Capability availability.
- **Prediction** still owes the other half of Appendix A's `011` slot.

---

## Operational note

Dev database `lab_brain` still carries a superseded `005c` and still needs dropping and re-creating
rather than migrating forward — `scripts/migrate.py` refuses it with a drift error, which is the
check working. No applied migration was edited in this session.

Scratch databases created here, all disposable: `lab_brain_p13`, `lab_brain_p13empty`,
`lab_brain_p13pre`, `lab_brain_p13post`, `lab_brain_mut011d0`…`lab_brain_mut011d8`. P12's are still
listed in `P12-handoff.md`.
