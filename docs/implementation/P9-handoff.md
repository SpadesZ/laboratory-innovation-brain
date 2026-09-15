# P9 — read-side authorization verification (`v3.3-a12`, second half)

Baseline: `0fed0b37ec7a3aadf6ca82022733275e804753c1` (P8, **CONDITIONAL FAIL**, one P0).
Scope was exactly the P0. `v3.3-a12`'s core design is unchanged: `005d`'s Decision schema, the
hash binding and the event linkage are all as shipped. `EPI-004`, `EPI-006` and M1 were not
started.

## The finding, and why it was right

P8 implemented `v3.3-a12` on the **write** path only. `record_transition` re-derived the
authorization before minting an event; `replay` accepted a bare `BeliefRevisionEvent` and applied
the transition.

So a Decision could be **semantically forged while staying perfectly well-formed**: a canonical,
complete six-input snapshot, a correct `input_hash`, correct project / subject / policy /
from→to, and `result` recorded as ALLOW — with a snapshot that, actually evaluated under the
immutable policy, returns DENY or a NEED_* outcome. `005d` accepts that row, and **it is right
to**. Refusing it would mean running `TransitionPolicy.evaluate` inside PostgreSQL, i.e. a second
copy of the evaluator, and §8.2.1 would stop being the single source of semantic truth and become
one of two definitions that drift. The limit is real. The conclusion drawn from it was not.

**No spec text changed, because the spec already said it.** §17.14.1:

> If it does not [re-derive], or if the inputs cannot be reconstructed, the authorization MUST be
> treated as absent — the event MUST NOT be created and a stored event MUST NOT be accepted as
> authorized.

"MUST NOT be created" is the write path. "MUST NOT be accepted as authorized" is the read path.
Only the first was built, so this was an implementation gap and not a specification deficiency —
recorded that way rather than patched with a new amendment.

## The seam

    stored event
      -> DecisionStore                       (the §17.14.1 authorization it cites)
      -> exact TransitionPolicyStore         ((policy_id, version), never "latest")
      -> AuthorityPolicy resolver            (only if the snapshot names one)
      -> rederive_decision                   (canonical serialization, whole decision)
      -> VerifiedBeliefRevision
      -> replay / projector

`replay` now takes `VerifiedBeliefRevision` and nothing else. The pure fold is unchanged and still
directly testable — what changed is that obtaining the capability requires passing the gate, so a
DB-loaded event cannot reach a scientific projection. That is deliberate: "the caller should
verify" is the version of the rule P8 shipped, and it is the version that fails silently.

`VerifiedBeliefRevision` uses the same module-private sentinel as `AuthorizedRevision`, and is no
more a security boundary than that one is. Someone who imports the sentinel can mint one, and
`tests/conftest_fixtures.py::forged_verification` does exactly that so the reducer's own tests stay
about ordering and quarantine rather than about authorization. The property is that the gate cannot
be skipped *by accident*, and that the line skipping it appears in a diff.

### Fail-closed conditions

Each carries its own `VerificationFailure` reason, so tests assert on state rather than prose — a
gate that failed closed for the wrong reason would be indistinguishable from one that worked.

| reason | condition |
|---|---|
| `AUTHORIZATION_MISSING` | non-genesis event citing no Decision |
| `AUTHORIZATION_NOT_FOUND` | the cited Decision does not exist |
| `SNAPSHOT_NOT_HYDRATABLE` | the stored row no longer satisfies the Decision model |
| `WRONG_DECISION_TYPE` | not a `BELIEF_TRANSITION` decision |
| `NOT_AN_ALLOW` | `DENY` / `NEED_MORE_EVIDENCE` / `NEED_HUMAN_REVIEW` |
| `LINKAGE_MISMATCH` | project, subject, policy id, policy version, `from_state` or `to_state` differs |
| `POLICY_NOT_FOUND` | that exact policy version is not registered |
| `COMPARATOR_UNRESOLVED` | the snapshot names an `AuthorityPolicy` that cannot be resolved |
| `NOT_REDERIVABLE` | hash mismatch, comparator identity mismatch, or the re-evaluation differs |
| `GENESIS_CLAIMS_AUTHORIZATION` | a genesis event carrying a transition authorization |

Two things it deliberately does **not** do. A named comparator that cannot be resolved is a
refusal, never a fallback to `None`: re-deriving without the comparator that was used answers a
different question and the answer would read as a confirmation. And the stored comparison results
are never consulted — §17.14.1 forbids storing them at all, because that would put the authority
rules beyond falsification (§10.5.1).

`verified_history` refuses a history containing one unverifiable revision rather than filtering it
out, for the same reason `replay` refuses mixed-project input: a history minus a revision is a
different history, and a projection built from the remainder would be a plausible answer that hides
the fact that something wrote a belief nobody authorised.

## The adversarial test

`tests/e2e/test_belief_authorization_verification_postgres.py`, written the way the audit
specified:

1. Build a canonical six-input snapshot whose inputs supply **zero** independent attestations
   against a policy that requires two, and assert that it really evaluates to non-ALLOW.
2. Insert the Decision by **raw SQL** with `result` and `evaluated_decision` both recording ALLOW,
   the correct `input_hash` over the canonical bytes, and correct project/subject/policy/from→to.
3. Assert **the database accepts it, and that this is expected**. This assertion is load-bearing:
   without it, a future schema change that started refusing the row would make the read-gate test
   below pass for a reason unrelated to the read gate, and the gap would reopen silently.
4. Append the event through `belief_revision_event_append` — it succeeds, with legal evidence.
5. Reload through the real stores, run the real projector, and assert `NOT_REDERIVABLE` with the
   projection unmoved: still `ACTIVE` from admission, `applied == ("bre:0",)`.

Plus the positive round trip — `authorize_transition → persist → reload → verify → replay` reaching
`SUPPORTED` with `origin` `["ADMISSION", "TRANSITION"]` — and a test that handing `replay` a stored
event directly no longer works, because "we changed the signature" is only a guarantee while
something checks it.

## What the mutation run found, and it was worth running

Eight read-gate guards, mutated one at a time, each asserted to have applied and to compile first.

**First pass: five of the eight left the entire postgres suite green** — the ALLOW check, the
linkage check, the missing-authorization check, the genesis check and the capability sentinel. All
five are *also* enforced by `005d` or by the Pydantic model, which is why no e2e case could reach
them. That is not a reason to trust them: `model_copy(update=...)` skips validators in process, a
support script writes SQL, and "the database would have caught it" is the assumption this project
keeps disproving.

`tests/contract/test_belief_authorization_verification.py` now covers each against in-memory
stores, including the linkage check parametrized over all six components one at a time — a
conjunction that covered five of six would otherwise pass. The semantic forgery is pinned there
too, without a database, so the guard is provable in the backend-free profile (AGT-007).

**Second pass: all eight red.**

| mutation | result |
|---|---|
| re-derivation removed from the read gate (the P0) | 5 failed, 41 passed |
| ALLOW check removed | 3 failed, 43 passed |
| linkage check removed | 6 failed, 40 passed |
| policy resolution removed | 2 failed, 44 passed |
| comparator resolution made to fall back to `None` | 2 failed, 44 passed |
| missing-authorization check removed | 1 failed, 45 passed |
| genesis authorization check removed | 1 failed, 45 passed |
| capability sentinel removed | 1 failed, 45 passed |
| all restored | 46 passed |

One more thing the tests found rather than review: the `WRONG_DECISION_TYPE` branch formatted
`decision_type.value`, which raised `AttributeError` when a Decision reached it carrying a bare
string — reachable via `model_copy`. A verification gate that crashes while reporting a refusal has
turned a fail-closed path into an outage. Now formatted with `!r`.

## Verification

All on a database created empty and migrated by `scripts/migrate.py`:

- **Migrations**: 17 declared, 17 applied from empty; re-run reports `applied 17 / pending 0`.
- **Full suite, `postgres` profile**: **761 passed**, 0 failed, 49.4 s.
- **Backend-free**: **562 passed, 199 skipped** — AGT-007 holds, no PostgreSQL, licence or network
  needed. 32 tests were added this slice (23 contract, 9 e2e).
- `ruff check`, `ruff format --check`, `mypy` (strict, 44 files): clean.
- `scripts/check_requirement_coverage.py`: exit 0, no OPEN GATE spec issue naming any milestone.
- `scripts/update_status.py --check`: up to date.

## Status

`SPEC-ISSUE-011` is **RESOLVED** and **R-13 is closed**, both with the reopen left visible. A gate
issue raised under AGT-015, ruled on by the maintainer, discharged by half, caught by audit and
then discharged properly is the process working; tidying the history away would remove the only
evidence that it did.

`EPI-003` and `EPI-005` stay **IN_PROGRESS**. The authorization story is now complete on both
paths, and its one residual is a deployment property rather than a record gap: when an
`AuthorityPolicy` took part, re-derivation needs that DomainPack comparator present, because core
must not import a DomainPack (§24.2). It is named by identity and version, so absence is detectable
and the gate refuses rather than guessing.

What is still missing is T-EPI-005's **cognition path**. §8.2.1's `evaluate` is exercised against
hand-built `HypothesisView` and `RelationJudgment` values, and nothing yet derives those from
admitted evidence: `EPI-006` (conflict detection) and `EPI-004` (`EpistemicStateProjection`) are
both TODO, and §26's T-EPI-003 names the projection directly.

### One observation for the maintainer, not acted on

§26's T-EPI-005 row currently phrases the raw-SQL obligation as "must be impossible to **store**".
That wording is what made it easy to build the write gate and call the requirement met. A future
clarification naming the read path as well would make recurrence harder to miss. Raised rather than
written, because it is a change to the normative test registry and that is the maintainer's call
(AGT-015).

## Operational note

The development database `lab_brain` still carries a superseded `005c` and needs dropping and
re-creating rather than migrating forward. No applied migration was edited and the ledger was not
touched. Scratch databases from this and the previous slice, all disposable: `lab_brain_a12`,
`lab_brain_a12b`, `lab_brain_a12final`, `lab_brain_pre005d`, `lab_brain_p7fix`,
`lab_brain_verify`, `lab_brain_pre005c`.

## Carried forward — M1, not started

`EPI-004` and `EPI-006` are the next slices. M1 remains closed, and its **Evidence-Aware
Hierarchical Chunking** requirement is recorded here in full so it is not lost:

1. **Minimal evidence boundary** — a chunk is the smallest span that carries the claim, not a
   window that happens to contain it.
2. **Structure-first** — segment on document structure (sections, paragraphs, table and figure
   boundaries), not on character or token offsets.
3. **Table/figure bound to body-text context** — a table or figure travels with the prose that
   interprets it; a detached caption is not evidence of what the number means.
4. **Conditions + locator preserved** — every chunk keeps the `conditions` it was measured under
   and a locator that resolves back into the source artifact, or it cannot become an Attestation.
5. **Fixed token windows are a fallback only** — used when structure cannot be recovered, and
   recorded as such rather than silently mixed with structural chunks.
6. **A retrieval benchmark measuring safety and accuracy** — not recall alone; the failure mode
   that matters is a confidently retrieved chunk that does not support the claim.

**Vectors do candidate retrieval only.** A vector chunk is never the evidence itself: the evidence
is the Attestation with its conditions and locator, and embedding similarity is a way to find
candidates for a human or a policy to judge. Treating the chunk as the evidence would make the
epistemic record depend on an embedding model's version, which is precisely what EVI-005's
comparator-version binding exists to prevent elsewhere.
