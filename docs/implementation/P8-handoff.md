# P8 — SPEC-ISSUE-011 / `v3.3-a12`: durable, re-derivable transition authorization

Baseline: `ada623c4302c83e78ab251f41044d8ccff155719` (P7-fix, **PASS** on its three blockers).
Scope was one thing: discharge the gate issue P7-fix raised. `EPI-004`, `EPI-006` and M1 were not
started, and M1's Evidence-Aware Hierarchical Chunking stays in the M1 prompt.

## The ruling, and why the third clause is the one that matters

The maintainer ruled **Option 1 + Option 2**, and added a requirement neither option contained:
the authorization must carry inputs it can be **re-derived** from.

That addition is what closes the gap instead of relocating it. Option 1 alone — require a
`Decision` row — moves the forgery up one level: write the Decision too. Option 2 alone — fix the
vocabulary — makes a forged row well-formed. Requiring the six inputs of §8.2.1's canonical
operator, plus a hash that binds them, means a Decision that survives checking has to contain
inputs that genuinely evaluate to ALLOW under the immutable policy. At that point it is not a
forgery; it is an authorization. §8.2.1's determinism guarantee is what turns recomputation into a
check rather than a guess.

**Locator corrected first.** SPEC-ISSUE-011 cited §17.14, which is `InferenceProvenance`.
`Decision` is declared in the §17.14.1 contract block. Fixed in the issue, the amendment and every
cross-reference.

## `v3.3-a12`

1. **§17.14.1** — `Decision` becomes the durable belief-transition authorization. `decision_type`
   is fixed to `BELIEF_TRANSITION`; `result` uses `ALLOW / DENY / NEED_MORE_EVIDENCE /
   NEED_HUMAN_REVIEW`, the same vocabulary as `TransitionDecision.outcome`. Adds `project_id`,
   `policy_id`/`policy_version`, `from_state`/`to_state`.
2. **Immutable canonical `decision_input_snapshot` + `input_hash`**, sufficient to reconstruct all
   six operator inputs. An `AuthorityPolicy` is recorded by uniquely locatable identity and
   version and **not** by its comparison results — storing the results would put the authority
   rules beyond falsification, which is what §10.5.1 refuses for INCOMPARABLE. `input_hash` is
   computed over the canonical bytes themselves, so a store can verify the binding without
   re-serializing and without agreeing with the writer about field order.
3. **§17.13** — `authorization_decision_id`, required for every non-genesis event, naming a
   Decision with the same project/subject/policy/from→to and `result=ALLOW`.
4. **Re-derivability, fail closed** — re-evaluating the snapshot under the named immutable policy
   must reproduce the stored decision under canonical serialization, or the authorization is
   treated as absent.
5. **Ownership** — the obligation belongs to existing **EPI-005 / T-EPI-005**. A normative
   registry statement was added to §25.3 and §26; **no Requirement or Test ID was created**, and
   traceability stays **59 ↔ 59**.

Genesis is deliberately outside all of it: admission is §8's separate gate and does not borrow
transition authority. `target_id` still has no foreign key — **R-12**, waiting on `EPI-001` in M3.

## Enforced in four places, because a Python gate is not a schema guarantee

| Obligation | Where |
|---|---|
| Only a computed ALLOW can authorise | `authorize_transition` derives the verdict; there is no parameter to supply one |
| The stored snapshot must re-derive | `rederive_decision`, called by `record_transition` **before** anything is minted |
| The whole decision is compared, not just `outcome` | canonical serialization of `TransitionDecision` |
| The hash binds the inputs | model validator **and** a Postgres `CHECK` recomputing `sha256` over the stored bytes |
| Non-genesis event must cite an authorization | model validator + `CHECK ((from_state IS NULL) = (authorization_decision_id IS NULL))` |
| Authorization must be ALLOW for the same project/subject/policy/from→to | `belief_revision_events_require_authorization` trigger |
| Cross-project authorization unrepresentable | composite FK on `(decision_id, project_id)` |
| Authorization immutable after the fact | `belief_transition_decisions_are_append_only` trigger |

Migration **`005d`**. `005a`/`005b`/`005c` are applied and untouched.

`decision_input_snapshot` is `TEXT`, not `jsonb`, and that is load-bearing: the database verifies
`input_hash` by hashing the stored bytes, and `jsonb` normalises whitespace, key order and number
formatting, which would leave the check with nothing to do but trust the writer.

## Proving the guards are load-bearing

**Python — 7 mutations, each asserted to have applied and to compile first:**

| mutation | result |
|---|---|
| re-derivation comparison removed (the consistent forgery, R-13) | 3 failed, 35 passed |
| `input_hash` binding check removed in the gate | 1 failed, 37 passed |
| authority comparator identity check removed | 1 failed, 37 passed |
| ALLOW check removed (a DENY would authorise) | 3 failed, 35 passed |
| project/subject scoping of the authorization removed | 2 failed, 36 passed |
| required `authorization_decision_id` removed from the event model | 1 failed, 37 passed |
| `input_hash` validator removed from the Decision model | 1 failed, 37 passed |
| all restored | 38 passed |

**SQL — additive, not by dropping constraints.** A scratch database built up to `005c` is the exact
schema the P7-fix audit passed. The decisive comparison:

| attempt | up to `005c` | with `005d` |
|---|---|---|
| supported append path, legal policy + transition + evidence, **no authorization at all** | **ACCEPTED** | REFUSED |

The other two forgery classes (`DENY`-backed, dangling authorization) could not be *expressed*
before `005d` — there was no column and no table — which is the gap itself rather than a guard.
Reported that way instead of as a refusal.

The raw-SQL battery in `tests/integration/test_belief_events_postgres.py` covers the classes the
maintainer named: no Decision; forged `DENY` / `NEED_MORE_EVIDENCE` / `NEED_HUMAN_REVIEW`; wrong
`input_hash`; wrong project; wrong subject; wrong policy; wrong from→to; genesis carrying an
authorization; UPDATE and DELETE on a stored authorization; unregistered policy version; a decision
that revises nothing; a non-`BELIEF_TRANSITION` type; half an authority identity.

## Two findings from writing the tests, not from reviewing them

1. **`model_copy(update=...)` does not re-run Pydantic validators.** The first version of
   "a Decision whose hash does not match its inputs cannot be built" passed a tampered hash
   through `model_copy` and did **not** raise. So a mismatched `input_hash` can exist in process,
   and the gate must not rely on construction having checked it. `rederive_decision` verifies the
   binding itself, and there is now a test for each layer — the honest constructor, and the gate.
2. **Adding a parameter with a `DEFAULT` created a second overload** of
   `belief_revision_event_append` rather than replacing the 15-argument one, so every existing call
   failed with `AmbiguousFunction`. `005d` drops the old signature explicitly and the new parameter
   is required: an append whose authorization was forgotten should not silently become a genesis
   event.

Also fixed, and it was a pre-existing gap in a guard rather than in this change: the schema-drift
parser read `ADD COLUMN IF NOT EXISTS x` as a column named `IF`. `v3.3-a12` added the project's
first idempotent column and produced two wrong answers at once — a phantom column and the real one
reported missing. The parse is now pinned by its own test.

## Verification

All on a database created empty and migrated by `scripts/migrate.py`:

- **Migrations**: 17 declared, 17 applied from empty; re-run reports `applied 17 / pending 0`.
- **Full suite, `postgres` profile**: **729 passed**, 0 failed, 60.9 s.
- **Backend-free**: **539 passed, 190 skipped** — AGT-007 holds.
- `ruff check`, `ruff format --check`, `mypy` (strict, 44 files): clean.
- `scripts/check_requirement_coverage.py`: exit 0. **No OPEN GATE spec issue** now names any
  milestone.
- `scripts/update_status.py --check`: up to date.

## Status, and the judgement behind it

`SPEC-ISSUE-011` is **RESOLVED**; **R-13 is closed**; **R-3 closes again**.

`EPI-003` and `EPI-005` stay **IN_PROGRESS**, and this is a judgement rather than an oversight.
The authorization story is complete and its residual is a deployment property, not a record gap —
when an `AuthorityPolicy` took part, re-derivation needs that DomainPack comparator present,
because core must not import a DomainPack (§24.2) and the spec forbids storing its results. It is
named by identity and version, so its absence is detectable and re-derivation refuses rather than
guessing; an authorization computed with no comparator re-derives from the record alone.

What is **not** complete is T-EPI-005's cognition path. §8.2.1's `evaluate` is exercised against
hand-built `HypothesisView` and `RelationJudgment` values, and nothing yet produces those from
admitted evidence: `EPI-006` (conflict detection) and `EPI-004` (`EpistemicStateProjection`) are
both TODO, and §26's T-EPI-003 names the projection directly. Marking either requirement DONE would
discharge the half of the pass condition that was easier to reach — the error P2 corrected for
`SYS-001`, and the reason `OPS-003` and `COST-001` are still IN_PROGRESS too.

## Operational note

The development database `lab_brain` was reported in the P7-fix handoff as carrying a superseded
`005c`; it still needs dropping and re-creating rather than migrating forward. No applied migration
was edited and the ledger was not touched. Scratch databases from this work, all disposable:
`lab_brain_a12`, `lab_brain_a12b`, `lab_brain_a12final`, `lab_brain_pre005d`, plus the P7-fix ones
(`lab_brain_p7fix`, `lab_brain_verify`, `lab_brain_pre005c`).

## Carried forward, not started

- `EPI-004` (`EpistemicStateProjection`) and `EPI-006` (conflict detection) — the next slices.
- **M1 Evidence-Aware Hierarchical Chunking**, for the M1 prompt: minimal evidence boundary,
  structure-first, table/figure context, conditions + locator, token fallback, retrieval benchmark.
