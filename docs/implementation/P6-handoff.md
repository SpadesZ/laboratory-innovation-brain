# P6 / M0b-3 — OPS-003, the execution seam

Baseline: `2f9d89ecabc4d05e7a3c49ca857e34185fbb18fa` (P5-fix, HARD PASS, CI run `34806356771`).

Scope boundary, held: `OPS-003` only. No `EPI-003`, no `EPI-005`, no `OPS-002`, no `SYS-001`. Two
migrations — `010a` (the slice) and `010b` (the audit fix) — and neither alters an existing table's
data.

A phase section is written **after** its commit exists, with the real SHA and the real test counts.

| Stage | SHA | Outcome |
|---|---|---|
| P6 | `ddcea7123b44565d74ba3fa9f4ab7801db8241b9` | CONDITIONAL FAIL — 2 × P1 |
| P6-fix | see the P6-fix section below | rework for both blockers |

---

## What was built

**`ExecutionSpan` (§17.19.1)** — exactly the declared fields, nothing added. No `project_id`,
because §17.19.1 declares none and inventing one would be the drift ADR-0010 was written about.
Two vocabularies the spec leaves unenumerated are derived rather than invented:

- `SpanType` from §12.5's chain (episode → retrieval → LLM call → job → run) plus `TOOL_CALL`,
  because §17.17's gate fires before each "LLM/tool call" and a tool dispatch that cannot be typed
  cannot be observed.
- `SpanStatus` — `SUCCEEDED`/`FAILED` from §17.16's Job and §17.22's StageResult, and `BLOCKED`
  kept separate because UX-002 states budget exhaustion classifies as POLICY_BLOCK and **not**
  FAILED. A governance refusal needs a supervisor; a breakage needs an engineer. (UX-002 is M1;
  this is consistency with it, not a claim to discharge it.)

**At most one subject.** §17.19.1 writes `model_call_id?/job_id?/retrieval_id?` as one alternation,
so the literal reading is "at most one, matching `span_type`". Enforced in the model *and* in the
DDL: a span with two subjects attributes its whole cost to both.

**Migration `010a_execution_spans.sql`** — the observability third of Appendix A's 010 slot.
`execution_spans` plus an `execution_span_cost_entries` join table, so OPS-003's "cost refs" are a
foreign key into `cost_entries` rather than an array of TEXT that can name a row which does not
exist. Opened once, closed once, never reopened, never deleted — by trigger, not by convention.

**The seam — `lab_brain.core.dispatch.dispatch_action`.** The point of the slice. Order:

```
open span RUNNING → authorize_dispatch → refused? close BLOCKED and RETURN
                 → record ESTIMATED → perform() → record ACTUAL → close SUCCEEDED
```

`perform` is a callable the function invokes, not a value it receives, so "we checked the budget
after spending the money" is unrepresentable here rather than merely absent.

**`SqlSpanRepository` / `SqlCostLedger`** — both require an autocommit connection, reusing P5-fix's
`require_durable_connection`. A span written inside a transaction the caller later rolls back is an
execution that happened and left no trace, which is the failure observability exists to remove.
One definition of "durable" in the package, not two that can drift.

---

## Two defects the tests found in my own first draft

Recording both, because the fix is the interesting part and a handoff that only lists what worked
is not a handoff.

**1. The estimate was recorded before the budget decision.** The reasoning was "a refusal's
magnitude is how an over-tight cap gets noticed". `cost_entries` holds one ESTIMATED row per
`action_ref`, so a refused attempt consumed that slot and the *legitimate* retry after a supervisor
approved the overrun could then never record its estimate — a governance refusal would have
permanently poisoned the action it refused. Fixed by asking first: the ledger records money, the
trace records attempts, and the BLOCKED span carries the reason, the exceeded dimensions and the
estimate in its metadata. Pinned by `test_an_approved_retry_of_a_refused_action_can_still_record_its_estimate`.

**2. A span's `actor_id` was handed an LLM slot.** `execution_spans.actor_id` is a foreign key into
`actors` (§14.4), while the ledger's `actor_or_slot` is deliberately wider because a §7.3 slot is
not an Actor. Passing the slot into the span produced a foreign-key violation, which is the schema
doing its job. The two fields now have their distinction documented on `DispatchableAction`.

Also corrected: `authorize_dispatch`'s claim-failure reason asserted the approval "was already
consumed" even when no such approval existed. Fail-closed either way, but the message was a claim
about something that had not happened; it now states both possibilities.

---

## Tests

Counts are after P6-fix, taken from `--collect-only` rather than remembered.

| Suite | Tests | What |
|---|---|---|
| `contract/test_execution_span.py` | 35 | model, reconstruction ordering and determinism, parent rules, lifecycle |
| `contract/test_dispatch_seam.py` | 20 | the ordering guarantee, status, cost refs, ONCE through the seam |
| `integration/test_execution_spans_postgres.py` | 28 | every CHECK, close-once trigger, atomic close, FK-backed cost refs |
| `e2e/test_episode_trace_postgres.py` | 2 | T-OPS-003's reconstruction, and a refused step mid-episode |

The ordering guarantee is tested with an action that **raises if it is ever called**, so a gate that
ran beside the call instead of before it fails rather than passes. Asserting on the returned
decision would have passed either way.

`tests/postgres_fixtures.py` is new: the `db` fixture moved out of `tests/integration/conftest.py`
because T-OPS-003 is declared `e2e` in §26 and a fixture in a sibling conftest is invisible across
suites. The append-only tables are now truncated explicitly rather than reached by CASCADE, which
also removes a latent trap — `DELETE FROM cost_entries` fires the trigger that exists to stop it.

---

## Verification

| Check | Result |
|---|---|
| postgres profile | 552 passed |
| backend-free profile | 434 passed / 118 skipped |
| migration replay from empty | scratch DB, 0 → 12 applied, then 0 pending |
| full suite on the replayed DB | 552 passed |
| idempotency, dev DB | 12 declared / 12 applied / 0 pending |
| executed-coverage gate | 4/4 ok under `[postgres]` |
| `update_status.py --check` | current |
| ruff / ruff format / mypy strict | clean |

One observation worth recording rather than hiding: the first full postgres run after this slice
took 7m39s. Two subsequent runs took 42s and 31s on the same tree, so it was an environmental
stall (Docker Desktop had just been restarted), not a regression. Measured rather than assumed —
`--durations=12` shows the slowest test at 3.3s.

**Requirement ↔ Test invariant unchanged at 59 ↔ 59.** No new requirement, no new normative
statement, no amendment. §23.5 (2) occurrence inventory unchanged.

---

## Status: both requirements stay IN_PROGRESS

**`OPS-003` — IN_PROGRESS, deliberately.** §26's pass condition names `run → artifact`. A Run is
§17.4's manifest, living in Appendix A's `006_jobs_runs.sql`, which is not built (`OPS-001` is M1).
So the RUN span records a run with no row to point at, and the artifact is reached through span
metadata rather than a checked reference. Recorded as **R-11**. Marking OPS-003 DONE would be
discharging half a pass condition, which is precisely the error P2 corrected for `SYS-001`.

**`COST-001` — IN_PROGRESS**, per the P5-fix audit ruling, and R-10 stays open for the stated
reason: the seam's actions are mocks. What changed is the size of the gap, not its existence.

---

## P6-fix — two observability-integrity blockers (DONE)

Audit of `ddcea712` returned CONDITIONAL FAIL on two P1s. Both were real, both reproduced against
the live schema before being fixed, and neither needed the P6 architecture changed. One migration,
`010b`; `010a` untouched.

### Blocker 1 — span close and cost refs were not atomic

`SqlSpanRepository.close()` issued the status UPDATE and then one INSERT per cost ref. Under the
autocommit connection these stores *require*, each statement commits on its own:

```
close(span, SUCCEEDED, [cost:valid, cost:missing])
  1. span -> SUCCEEDED     committed
  2. cost:valid link       committed
  3. cost:missing          FK violation, raises
→ span SUCCEEDED, refs partial, and the close-once trigger refuses every retry
```

The two facts OPS-003 exists to make reliable were exactly the pair that could diverge, and
permanently — the span can never be closed again. Reproduced before fixing, not reasoned about.

**Fix:** `execution_span_close(span_id, status, end_time, metadata, cost_entry_ids[])` in `010b`
does the whole close in one statement, so under autocommit the statement's own atomicity is the
guarantee. Refs are validated before the UPDATE as well, so the ordinary failure writes nothing;
the FK remains the backstop. Wrapping it in a Python transaction was not available: these stores
refuse a connection they do not own precisely so they never commit somebody else's work, so the
atomic unit had to be the statement.

The concurrency property survives — the conditional `UPDATE ... WHERE status = 'RUNNING'` inside
the function takes the row lock, so of two concurrent closes exactly one returns TRUE.

### Blocker 2 — a parent span was not required to be in the same trace

`010a`'s FK was `parent_span_id REFERENCES execution_spans (span_id)` — parent must exist, nothing
about which trace. A child in trace B with a parent in trace A was accepted; `trace('B')` then
returned a child whose parent was absent, and `TraceView.ordered()` treated it as a **root**. A
corrupt cross-trace edge was silently laundered into a plausible tree. The in-memory store was
looser still: it validated parents not at all, while the file's docstring claimed both
implementations enforced the same contract. That claim was false and is now corrected in place.

**Fix:** `010b` adds `UNIQUE (span_id, trace_id)` (needed only as a composite FK target — `span_id`
is already the primary key) and replaces the FK with `(parent_span_id, trace_id) REFERENCES
execution_spans (span_id, trace_id)`. MATCH SIMPLE still allows a root with no parent. The old
constraint is dropped by its exact name, not `IF EXISTS`, so a name mismatch fails loudly instead
of leaving the weak FK in place while reporting success.

`InMemorySpanRepository.open()` now enforces parent existence and same-trace. `TraceView.ordered()`
raises `TraceCorruptionError` on an orphan, a foreign-trace span, or a cycle, rather than repairing
its own input — a reconstruction that silently fixes corruption produces output that reads as
evidence and is not.

`InMemorySpanRepository(ledger=...)` closes the cost-ref half of the parity gap: given the ledger,
it validates refs exactly as `execution_span_close` does. Without one it cannot, and that is now a
documented parameter with a pinning test rather than an unstated asymmetry. The dispatch seam
passes the ledger it already holds.

### Fixtures added

- invalid second ref → span still RUNNING, **0** links (not 1)
- refused close → the span is still closable afterwards
- all refs valid → terminal status and every ref visible together
- two concurrent closes across two real sessions → exactly one winner
- the refusal names the missing entry (message quality, asserted separately from state)
- `execution_span_close` refuses closing to RUNNING
- cross-trace parent rejected by the DB; same-trace parent accepted
- in-memory: orphan parent and cross-trace parent both refused at `open()`
- `ordered()` raises on orphan, foreign-trace span, and cycle
- in-memory close with an unresolvable ref leaves the span open and retryable

**Mutation, cleanly attributable.** Restoring the pre-`010b` two-step close (exact text, asserted
to have applied, and compiled before trusting) turns the two atomicity tests red on the right
assertions: `RUNNING` vs `SUCCEEDED`, and `SpanLifecycleError: span was not open` on the retry —
i.e. the state and the permanence, not a message regex. The first attempt at this failed only on
the error wording; the tests were restructured so the state is what is asserted, with message
quality as its own separate test.

### Verification

| Check | Result |
|---|---|
| postgres profile | 568 passed |
| backend-free profile | 441 passed / 127 skipped |
| migration replay from empty | scratch DB, 0 → 13 applied, then 0 pending |
| full suite on the replayed DB | 568 passed |
| idempotency, dev DB | 13 declared / 13 applied / 0 pending |
| executed-coverage gate | 4/4 ok under `[postgres]` |
| `update_status.py --check` | current |
| ruff / ruff format / mypy strict | clean |

The AGT-003 header guard fired twice more during this fix, on `010b` taking the count to 13 — which
is what it is for.

`OPS-003` remains **IN_PROGRESS** and `COST-001` remains **IN_PROGRESS**. R-10 stays NARROWED,
R-11 stays open. No new requirement, no amendment, invariant unchanged at 59 ↔ 59.

---

## Unresolved, carried forward

1. **R-10** — narrowed: the gate now has a caller, and the caller is proven to refuse before the
   side effect. The actions are mocks. Closes when M1 brings a real path through `dispatch_action`.
2. **R-11** (new) — a span may name a Job or Run that has no row. Closes with `OPS-001`/M1.
3. **R-7, R-8, R-9** — unchanged. R-8 in particular: `critique_gate` still has no caller.
   `dispatch_action` is where it will attach, and wiring it in now would have been claiming an M3
   requirement (`SRC-002`) from an M0b slice. The extension point is named in the module docstring
   rather than built.
4. **The in-memory span store does not check cost refs unless given a ledger.** Now a parameter
   with a pinning test rather than a silence; the dispatch seam supplies one. The default is the
   weaker behaviour because nothing can resolve a ref without something to resolve it against.
5. **`ExecutionSpan` is not bound by the schema-drift guard** — added to `UNBOUND` with the reason:
   §17.19.1's `model_call_id?/job_id?/retrieval_id?` alternation is not parseable as three field
   names, so binding it would compare 11 canonical fields against 13 implemented ones and report
   the three subjects as undeclared. Bindable once §17.19.1 states them separately, which is a
   maintainer amendment rather than an agent decision.
6. **Trace reads are not project-scoped.** §17.19.1 declares no `project_id` on ExecutionSpan and
   none was invented. The scope would have to come from the Episode, which is M1.
7. **`CHANGELOG.md` still stops at M0a-2.** Unchanged from P5-fix; still out of scope.
