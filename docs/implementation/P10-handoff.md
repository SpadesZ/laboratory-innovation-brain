# P10 — P9-final scope, EPI-004 authority, EPI-006 conflicts

Baseline: `ccc43fc76b525bdb13a2d84e7cdfe2d6ad363309` (P9, core read-side P0 **PASS**).
No P8/P9 architecture, `005d` or Decision semantics were rewritten.

| Phase | SHA | Content |
|---|---|---|
| 0 | `ef38fe656c5f4d4c93607985e399f0808ec9c4d5` | scope fail-loud + `v3.3-a13` |
| A | `88f469691ec308043fc99f815107371866a37c88` | EPI-004 authority comparator contract |
| B | `baaced90fe9d4e3c7b08e70361b416ad0c42983e` | EPI-006 typed blocking Conflict |

---

## Phase 0 — a wrong-target request was answered, not refused

Two scope guards existed and only one was real. `v3.3-a11` made mixed-project input fail loudly;
the target half never did. `replay` **filtered** on `target_id`, so asking for a hypothesis whose
events were not in the sequence returned an empty projection — and an empty projection is a
legitimate answer meaning "this hypothesis has no history yet". The caller got a confident wrong
result rather than an error, which is the failure shape this project keeps finding: the dangerous
version of a bug is the one that looks like success.

`_enforce_requested_scope` is now shared by `replay` and `verified_history`, refuses on both axes,
and reports them together so a caller who got the project *and* the target wrong does not have to
fix one, re-run, and discover the other. The filter is **gone**, not moved. `verified_history`
checks scope *before* authorization: an out-of-scope event is a wrong query, not an unauthorised
belief, and reporting it as `NOT_REDERIVABLE` would send whoever reads it hunting a forgery.

One existing test asserted the opposite and the opposite was wrong.
`test_replay_ignores_other_targets` pinned the silent filter as correct behaviour. It is now
`test_events_for_another_target_fail_loudly_rather_than_being_filtered`, with single-axis cases
(wrong-target/same-project, wrong-project/same-target) so neither guard can be standing in for the
other, plus mixed-target, mixed-project, and both-at-once.

**Five mutations, all red.** The fourth restores the exact code P9 shipped — the `target_id`
filter — and turns five tests red, which is the proof these tests would have caught it.

### `v3.3-a13`

A clarification only. T-EPI-005's "must be impossible to **store**" read as though persistence
carried the whole obligation, which is what made building only the write gate look like meeting
the requirement, while §17.14.1 also says "a stored event MUST NOT be accepted as authorized".
The amendment separates the classes:

- **storage-checkable forgery** — missing Decision, non-ALLOW, unbound `input_hash`, wrong
  project/subject/policy/from→to — **MUST** be refused at the persistence layer, including raw SQL.
- **semantic forgery** — all metadata legal, snapshot re-evaluates differently — does **not**
  require PostgreSQL to re-run the evaluator and the store **MAY** accept it, because duplicating
  §8.2.1 in SQL turns one definition of semantic truth into two that drift. The production
  read/replay path **MUST** re-derive and fail closed before any projection.
- T-EPI-005 **MUST** include the adversarial e2e that already exists: raw-SQL forgery, DB accepts,
  reload through production stores, verifier refuses, projection unchanged.

No Requirement or Test ID added, no normative statement added, EPI-005's semantics unchanged,
traceability still **59 ↔ 59**, and **SPEC-ISSUE-011 stays RESOLVED** — this clarifies where an
existing obligation is discharged, it does not create one.

---

## Phase A — EPI-004

The INCOMPARABLE → NEED_HUMAN_REVIEW path already existed from P7. What was missing was the
contract around it.

**`AuthorityPolicyRegistry`** resolves `(policy_id, policy_version)` or raises, and distinguishes
"no such comparator" from "that version is gone" — a bare mapping returns `None` for both, and
both then read as "no comparator took part", the one reading that must never be inferred. There is
no "latest": asking for `1.0.0` when only `2.0.0` is registered is an error, because §8.2.1's
determinism guarantee holds within one version and says nothing across two. Registration reads the
identity off the comparator rather than taking it as an argument, so a registry entry cannot
disagree with the object it holds. Replacing a version in place is refused. `as_mapping()` is the
read-only *view* P9's verifier consumes — a view rather than a copy, so wiring order does not
decide whether a stored Decision can be re-derived.

**`partial_order_violations`** checks the laws core is entitled to check: reflexive, converse,
deterministic, closed over the four results. None names a class or a physical quantity, which is
the only division §10.5 permits — core cannot know which class outranks which, but it can know
that a comparator claiming both directions at once is not an order. Transitivity is deliberately
**not** checked: it needs every triple, and a partial order may legitimately contain INCOMPARABLE
pairs that break naive chains, so asserting it would forbid exactly the orders §10.5.1 permits.

The reference comparator is `tests/toy_authority.py`, outside `src/`, and a test asserts core
names no authority class at all. Its classes are `TIER_A` / `TIER_B` / `SIDEBAND` rather than
`MEASURED` / `SIMULATED`, because a fixture with physical names invites the reading that core
knows measurement outranks simulation.

**Nine mutations, all red**: the four laws, the registry's two refusals, INCOMPARABLE coercion, a
missing comparator treated as no requirement, and empty admitted classes treated as satisfied.

### Two things the work found rather than review

1. **The reflexive law caught a bug in the fixture written to exercise it.** `SIDEBAND` was absent
   from the ranking, so `compare(SIDEBAND, SIDEBAND)` returned INCOMPARABLE. That is the only real
   evidence a law-checker works, so the fix carries a comment saying so.
2. **A latent import cycle became load-bearing.** `core.authority` imports `models.enums`, which
   executes `models/__init__`, which imports `models.transition`, which imported `authority` at
   runtime — so `import lab_brain.core.authority` failed outright while
   `import lab_brain.core.models` worked, depending purely on import order. `transition.py` uses
   `AuthorityPolicy` only in annotations, so it is now a `TYPE_CHECKING` import and both orders
   work. It surfaced because EPI-004's tests import the registry directly.

Also: the first version of the core-purity test banned the phrase "measurement is always" and
failed on `core/authority.py`'s own docstring, which quotes §10.5 saying that is *not* a core
assumption. Banning a quotation of the prohibition would have deleted the clearest statement of
the rule to satisfy a guard about breaking it, so the test is scoped to class names — a class name
is a ranking, a sentence saying there is no universal ranking is documentation.

---

## Phase B — EPI-006

`blocking_conflict_policy` listed `conflict_type` values that **nothing compared against**, and
`HypothesisView.blocking_conflict_ids` was a tuple of ids the *caller* had already judged blocking.
So the policy honoured whatever it was handed: forget to populate the ids and you got an ALLOW.
§17.19.3 rules that out — a conflict must not be represented only as strings or scattered flags.

`Conflict` now carries §17.19.3's declared fields with the seven `conflict_type` and five
`resolution_status` values as **closed enums**. Closed on purpose: a free-text type cannot be
matched against a policy, and an LLM-authored one would put the decision back where AGT-016 forbids
it, because a model deciding what counts as blocking is a model deciding belief.

`evaluate` matches declared types against typed records and decides for itself. Three conditions,
each load-bearing in a different direction: the type must be listed, the conflict's own `blocking`
flag must be set, and it must be unresolved.

- **`UNDER_REVIEW` counts as unresolved.** A human looking at a conflict has not resolved it, so
  escalating an AUTHORITY_CONFLICT to a ReviewItem does **not** clear the block — which is what
  §8.2.1's "no BeliefRevisionEvent may promote/reject until the review resolves" requires.
- **`ACCEPTED_AS_OPEN_QUESTION` is excluded deliberately** — that status is a decision to proceed
  with the conflict on the record, the one case where the answer is not "wait".

Closing is event-sourced: RESOLVED without a `resolution_event_id` is refused at construction,
RESOLVED without `resolved_at` too, and an open conflict carrying resolution details is refused
from the other side. `InMemoryConflictStore` has **no `delete` and no status setter** — asserted by
a test, because the absence is the contract. `resolve` takes the event id as a required keyword
with no default; re-resolving and re-recording are both refused; subject queries are keyed on
project first.

**Eleven mutations, all red.**

---

## Verification

| gate | result |
|---|---|
| Migrations from empty | 17 declared, 17 applied, `pending 0` on re-run |
| Full suite, `postgres` profile | **831 passed**, 0 failed |
| Backend-free | **632 passed / 199 skipped** (AGT-007) |
| `ruff check` / `ruff format --check` | clean |
| `mypy` (strict) | clean, 46 source files |
| Executed-coverage ratchet | exit 0 |
| `update_status.py --check` | up to date |
| Spec traceability | 59 ↔ 59 |
| Mutations | 5 scope + 9 authority + 11 conflict, **all red**, all restored green |

---

## Requirement status — what is still IN_PROGRESS and why

Statuses are **derived** by `update_status.py` (milestone IN_PROGRESS + a marked test exists), not
hand-set, so none of these could have been hard-promoted.

| ID | Status | What is missing |
|---|---|---|
| `EPI-003` | IN_PROGRESS | §26's T-EPI-003 names `EpistemicStateProjection`; `BeliefProjection` has no `belief_level` or `unresolved_conflicts` |
| `EPI-004` | IN_PROGRESS | T-EPI-004 requires INCOMPARABLE to **auto-create** ReviewItem(AUTHORITY_CONFLICT). `ReviewItemSpec` is the typed pending interface and is tested as such; nothing creates the record, which needs ReviewItem storage (UX-005) |
| `EPI-005` | IN_PROGRESS | cognition path: `evaluate` runs against hand-built `HypothesisView` / `RelationJudgment`; nothing derives those from admitted evidence |
| `EPI-006` | IN_PROGRESS | **no `conflicts` table.** T-EPI-006 is contract/e2e; invariants hold in the model and the in-memory store but not in the database, and this project's own history says a Python-only guard is not a schema guarantee |
| `COST-001`, `OPS-003`, `SEC-002` | IN_PROGRESS | unchanged by this slice |

The honest summary of Phase B: the **contract** is done and the **persistence** is not. A
migration plus the postgres half of T-EPI-006 is the next increment for EPI-006, and
`ReviewItem` storage is the next one for EPI-004.

---

## M1 Evidence-Aware Hierarchical Chunking — LOCKED HANDOFF, not implemented

No embedding index and no chunker was built in this slice. The six requirements, to be followed
when M1 opens and **not** to be replaced with LangChain-style fixed-token chunking:

1. **Minimum Evidence Boundary** — find the smallest complete evidence boundary that can
   independently support one claim or observation. Conditions and results must not be split apart.
2. **Structure-first** — section / subsection / paragraph / table / figure-caption / code-log block
   take priority over token counts.
3. **Table/figure context binding** — a table must retain header, unit and row context; a figure
   must be bound to its caption *and* the relevant surrounding text.
4. **Conditions + locator preserved** — a chunk must resolve back to an Artifact/SourceWork
   locator and must retain conditions, units and method/provenance. **An embedding must never be
   the evidence itself.**
5. **Fixed-token only as fallback** — secondary subdivision or a token safety limit when an
   evidence unit is too large. Never the primary splitter.
6. **Retrieval benchmark** — a fixed scientific fixture comparing a fixed-token baseline against
   Evidence-Aware Hierarchical Chunking, measuring at minimum evidence-boundary completeness,
   correct locator recovery, condition retention, table/figure retrieval, and candidate
   recall/precision.

**Vectors do candidate retrieval only.** The final `EvidenceBundle` must still pass
condition/source/authority filtering. Treating a vector chunk as the evidence body would make the
epistemic record depend on an embedding model's version — precisely what EVI-005's
comparator-version binding exists to prevent elsewhere.

---

## Operational note

Dev database `lab_brain` still carries a superseded `005c` and needs dropping and re-creating
rather than migrating forward. No applied migration was edited. Scratch databases, all disposable:
`lab_brain_p9`, `lab_brain_a12`, `lab_brain_a12b`, `lab_brain_a12final`, `lab_brain_pre005d`,
`lab_brain_p7fix`, `lab_brain_verify`, `lab_brain_pre005c`.
