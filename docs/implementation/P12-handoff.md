# P12 — review resolution, `v3.3-a14`, and the last of the P11 blockers

Baseline: `6edd74296254520357804d1a1d055e5e1fd0f799` (P11, **FAIL**, targeted final rework).
Authority A-fix, conflict terminal semantics, `011a` persistence, the 19-migration baseline and
Phase 0 were all kept and not rewritten.

**This is the last patch of this agent session.** The next slice opens a fresh session, so the
handoff below is written to be read cold.

| Phase | SHA | Content |
|---|---|---|
| 1 | `547c6d68d0803958f0240b1800094cfd36aafc8f` | `v3.3-a14` spec amendment |
| 2–5 | `74ba27e1a918ad33735984b5028a8b7d9b5244be` | `011c`: review resolution, idempotent escalation, immutability, `meets()` conformance |

---

## The P0, and it was mine

P11's Phase D end-to-end test claimed to exercise "review resolution closes the conflict" and
**never touched the review**. The fixture pre-created `bre:resolution` before any escalation, the
`ReviewItem` sat at `QUEUED`, and that unrelated event was handed to `conflict_close` as the
closure proof. `conflict_close` never consulted the review, so it passed. The test was named
`test_resolving_the_review_closes_the_conflict_against_a_real_event`, and the P11 handoff repeated
the claim in a table of what had been verified.

Both tests built on it are deleted, and the fixture event is gone. Every closure in the module now
goes through a real resolution, and the event a closure cites is created **after** the escalation
by `_event_from_review`.

### Why it was possible: `v3.3-a14`

`decision_ref` appeared exactly once in §17.19.1 — a field in a list, optional, with no prose
saying what it referenced or when it was required. So §8.2.1's "no BeliefRevisionEvent may
promote/reject until the review resolves" had no definition of *resolves* to enforce. Same shape
as SPEC-ISSUE-011: the obligation existed and the object it needed did not.

`v3.3-a14` states four things in §17.19.1, and also settles the `subject_id` contradiction P11 had
resolved in a docstring rather than in the spec:

- **`subject_id`** — §17.19.3 is canonical; §8.2.1's INCOMPARABLE flow now reads *create Conflict,
  create `ReviewItem(subject_id=conflict_id)`, link `Conflict.review_id`*, with the hypothesis one
  hop away through `subject_refs`.
- **A terminal ReviewItem MUST carry `decision_ref`** — a terminal review without one is a human
  decision with no record of what was decided.
- **Outstanding review invariant** — while a `QUEUED` or `ASSIGNED` review is linked to a blocking
  Conflict, that Conflict must not reach any closing status. `ASSIGNED` included: somebody having
  picked the task up is not somebody having answered it.
- **Closure traceability** — the Conflict's `resolution_event_id` must be the event produced by
  *that* review's resolution. Neither an arbitrary same-project event nor another review's
  resolution may stand in.
- **Atomicity** — neither half-state may be observable after a crash or under concurrency.

No Requirement or Test ID added; traceability still **59 ↔ 59**; occurrence inventory unchanged.

One thing worth knowing about writing that amendment: the first version restated the outstanding-
review invariant as a `MUST` inside §8.2.1, and the §23.5 obligation inventory **failed** —
correctly, because §8.2.1 is inside the §6–§16 audit scope while the amendment row claimed no
hard-obligation keyword had been added there. The fix was to make §8.2.1 cross-reference §17.19.1
rather than restate it. Adjusting the claim instead of the prose would have been the tempting move.

---

## `011c`

**`review_resolutions`** is what `decision_ref` points at: `resolution_id`, `review_id`,
`project_id`, `outcome` (the four terminal values), `resolved_by_actor_id`, `resolved_at`,
`rationale`, `belief_revision_event_id`. `UNIQUE (review_id)` — one resolution per review, because
two would be two accounts of what a human decided. Composite FKs on both the review and the event,
so cross-project is unrepresentable.

**`conflict_close`** (body replaced, signature unchanged so no caller can opt out) looks up the
linked review and refuses while it is outstanding, requires `decision_ref`, resolves it, and
requires the closure event to equal that resolution's event.

**`review_resolve_and_close_conflict`** does resolution + terminalization + closure in one
statement.

### The closure-event rule came out uniform, and a test found that

The first draft made `belief_revision_event_id` nullable, reasoning a `REJECTED` review might
settle nothing. A test written against that draft tried to close a conflict as
`ACCEPTED_AS_OPEN_QUESTION` with no event and `conflicts_only_close` refused — **correctly**. The
locked P10 ruling is that *every* status which stops a conflict blocking carries its closure event,
with no exception unless the spec defines an alternative, and it does not. A per-status exemption
is how the terminal-state hole appeared in the first place. So the column is `NOT NULL`, the branch
is gone, and all four outcomes are parametrized with the conflict status each honestly implies
(`REJECTED` → `ACCEPTED_AS_OPEN_QUESTION` is §17.19.3's honest third option, and it still needs the
event).

### The atomicity test found something better than a bug

I could not construct "review terminal, conflict still open". Inside the function the same
`p_event_id` goes to both the resolution insert and the close, so traceability cannot disagree with
itself, and the only other post-update failure needs a conflict closed while its review was
outstanding — forbidden. **The half-state is unreachable by construction**, which is a stronger
guarantee than a test for it. So the test asserts the reachable property (a failed second attempt
leaves no resolution row) plus a direct SQL scan for the forbidden pair. The second attempt is
refused by `review_resolutions_one_per_review`, earlier and stronger than expected.

### The other three blockers

- **Idempotent escalation.** `011b` accepted an already-`UNDER_REVIEW` conflict and overwrote
  `review_id`, so a retried episode could queue a second reviewer and orphan the first. The
  function returns the existing review id, and the update is conditioned on `review_id IS NULL` so
  two concurrent escalations resolve to one winner. The store reads the returned id rather than
  assuming its own proposal won.
- **Immutability completed.** `review_id` is written once from NULL; `supporting_refs` and
  `episode_id` join the immutable set — both are scientific provenance, and `011a` left both
  editable.
- **`meets()` conformance.** The P11 check compared `bool(actual)`, which accepts `1`, `"yes"` and
  any truthy stand-in. It now requires an exact `bool` and asks each pair twice, because a
  comparator that answers correctly when registered and differently afterwards registers cleanly
  and then decides beliefs inconsistently. Both adversarial fixtures are refused at registration.

### Mutations: 9, and the ninth is the point

Eight red immediately. The ninth — the blank-rationale validator — **passed green**, because the
check was written and nothing tested it. It has a test now and goes red. Running them is how that
surfaced; reading the code would not have.

---

## Verification

| gate | result |
|---|---|
| Migrations from empty | **20** declared, 20 applied, `pending 0` on re-run |
| Full suite, `postgres` profile | **954 passed**, 0 failed |
| Backend-free | **686 passed / 268 skipped** (AGT-007) |
| `ruff check` / `ruff format --check` | clean |
| `mypy` (strict) | clean, 50 source files |
| Executed-coverage ratchet | exit 0 |
| `update_status.py --check` | up to date |
| Spec traceability | 59 ↔ 59 |
| Mutations | 3 Python + 6 SQL, all red after the ninth got its test |

SQL mutations were proven **additively**: the migration is mutated, applied to a uniquely-named
scratch database built from empty, and restored. Nothing is ever dropped.

---

## Requirement status

Derived by `update_status.py` from milestone state plus marked tests — not hand-set.

| ID | Status | What is missing |
|---|---|---|
| `EPI-003` | IN_PROGRESS | §26's T-EPI-003 names `EpistemicStateProjection`; `BeliefProjection` has no `belief_level` or `unresolved_conflicts` |
| `EPI-004` | IN_PROGRESS | see below |
| `EPI-005` | IN_PROGRESS | cognition path: `evaluate` runs against hand-built `HypothesisView` / `RelationJudgment`; nothing derives those from admitted evidence |
| `EPI-006` | IN_PROGRESS | see below |
| `UX-005` | TODO | ReviewQueue capacity and human-review Capability availability do not exist. The `review_items` schema is a shared foundation and does **not** discharge it |
| `SYS-001`, `VER-006`, `OPS-002` | TODO | unchanged |
| `COST-001`, `OPS-003`, `SEC-002` | IN_PROGRESS | unchanged |

**EPI-004 and EPI-006 stay IN_PROGRESS for one shared reason.** Both §26 rows say the ReviewItem is
**auto**-created, and nothing calls the escalation seam automatically. The vertical exists, is
persisted, and is now genuinely tested end to end — but it has to be *invoked*, and the
orchestration that would invoke it is `SYS-001`'s episode loop, which is TODO. Marking either DONE
would claim an automation that is one caller short.

---

## For the next session — M1 Evidence-Aware Hierarchical Chunking, LOCKED

No chunker and no embedding index exists, and none is to be built until M1 opens. The seven
requirements, to be carried forward verbatim and **not** replaced with LangChain-style fixed-token
chunking:

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

### Other work the next session should know is open

- **`SYS-001` episode loop** is the blocker on EPI-004/EPI-006 reaching DONE.
- **`EPI-004`'s remaining gap** is only the automatic invocation; the seam is
  `core/escalation.py` plus `SqlReviewItemStore.escalate_authority_conflict`.
- **`UX-005`** needs ReviewQueue depth and human-review Capability availability. `review_items` is
  deliberately narrow — its `subject_type` CHECK admits only the two conflict kinds, so adding a
  new subject type is a deliberate act.
- **Prediction** still owes the other half of Appendix A's `011` slot.

---

## Operational note

Dev database `lab_brain` still carries a superseded `005c` and needs dropping and re-creating
rather than migrating forward. No applied migration was edited in this session. Scratch databases,
all disposable: `lab_brain_p12final`, `lab_brain_p12`, `lab_brain_p12b`, `lab_brain_p12c`,
`lab_brain_mut*`, `lab_brain_p11d`, `lab_brain_p11`, `lab_brain_p10`, `lab_brain_p9`,
`lab_brain_a12`, `lab_brain_a12b`, `lab_brain_a12final`, `lab_brain_pre005d`, `lab_brain_p7fix`,
`lab_brain_verify`, `lab_brain_pre005c`.
