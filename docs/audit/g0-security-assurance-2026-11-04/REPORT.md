# G0 security assurance: forged verification authorizations and the consequential readers

Date: 2026-11-04. Branch `claude/lib-implementation-agent-47evs0-g0`.
Baseline: `367163b710db999e6d549d646a3c9e86931f425b` (P2, `g0-authorization-read-path-closure`,
CI run `41482881644`). Commits on top: `7f203df` (fix and tests), `683c91a` (status inventory),
and the commit that adds this report.

**Status: implementation-side engineering evidence, not an independent audit. G0 remains NOT
PASSED. `READY_FOR_REAL_RESEARCH` stays false.**

Limits kept: zero cost (no paid model, no network, no Lumerical, no deployment); no database
extension installed; no production privilege or credential changed; every key is generated inside
the test process and discarded; `ACTIVE_SPEC.yaml` and the SAI 3.3/3.4 files are untouched; no
existing test weakened; P2's frozen evidence untouched.

## 1. Scope and method

P2's claims were not taken as given.

1. Every query in `src/` that reads `relation_judgments`, the verification-authorization tables,
   belief events or transition decisions was found by search, and each construction site was read.
2. For each consequential reader, a negative test drives the reader through its own product wiring,
   once for each kind of bad authorization the database admits, acting as the least-privilege
   services' role (created per test by `grant_database_roles`).
3. Each reader also has a positive control: a correctly signed authorization is counted.
4. The database's own write-time refusals are asserted separately, so the reader tests do not rest
   on an assumption about SQL.
5. Where a reader counted a bad support, the bypass was reproduced on the baseline first, the log
   kept under `evidence/`, and then fixed minimally.

## 2. Reader inventory

| # | Reader | Location | Verifies the signed authorization? | Proven by |
|---|---|---|---|---|
| R1 | transition inputs | `SqlRelationStore.admitted_for_subject`, `src/lab_brain/core/repositories/evidence.py:256` | yes | `test_no_reader_counts_a_support_on_a_bad_authorization`, `test_every_reader_counts_a_correctly_signed_support` |
| R2 | loop confirmation rule | `src/lab_brain/research/loop.py:486,1024,1155,1582,1610` via `SqlEvidenceSink` | yes | same pair |
| R3 | `BeliefEpisode.attempt_transition` snapshot | `src/lab_brain/core/episode.py:487` | yes | same pair; `test_a_bad_support_reaches_no_transition_through_the_product_episode`, `test_a_signed_support_reaches_the_product_episodes_decision` |
| R4 | confirmation re-check | `src/lab_brain/research/confirmation.py:95,150` | yes | same pair |
| R5 | episode view, "recorded as support, but not counted" | `src/lab_brain/interfaces/episode_view.py:448` | yes | same pair |
| R6 | acceptance scoring facts | `src/lab_brain/evaluation/collect.py:163` | yes | same pair |
| R7 | `ProspectiveEvidenceSink` write path | `src/lab_brain/research/prospective.py:544` | yes | same pair |
| R8 | belief projection (feeds the episode report `service.py:2002` and the loop `loop.py:469,1308`) | `src/lab_brain/core/episode.py:331`, `src/lab_brain/core/belief.py:560` | **no on `367163b`; fixed in `7f203df`** | `test_the_projection_refuses_a_decision_resting_on_a_forged_support`, `test_the_projection_keeps_a_decision_resting_on_a_signed_support`, `test_the_projection_refuses_a_snapshot_support_that_is_not_the_stored_relation` |
| R9 | `from_observation` (rival affirmations) | research loop | no, by design: it can only block a confirmation, never grant one | read |
| R10 | warrant resolver `.get` | warrants | no; delegates to R1/R8 | read |
| R11 | episode view `.get` | episode view | delegates to R5 | read |
| R12 | warrant-review question | `src/lab_brain/interfaces/app.py:3493`, `review_cli.py:171` | **no**; display only, a grant on it is inert (finding F4) | read |
| R13 | SQL confirmation rule (`012p`) | migration | no (SQL cannot verify Ed25519); covered by R4 | read |
| R14 | measurement recorder sink | write path | covered by R7 | read |

(File paths are those under `src/lab_brain/` on this branch; line numbers at `683c91a`.)

## 3. Tests added

`tests/e2e/test_g0_security_assurance_postgres.py` (17 tests):

- `test_no_reader_counts_a_support_on_a_bad_authorization`, parametrized over `forged_signature`,
  `rogue_authority` (valid signature, but the key was enrolled by an authority that is not pinned;
  the services' role wrote the enrolment row), `tampered_payload`, `replayed_signature`,
  `revoked_before_signing`. Each run checks R1–R7 through product wiring and asserts that the
  refusal reason is the authorization.
- `test_a_bad_support_reaches_no_transition_through_the_product_episode`.
- Positive controls: `test_every_reader_counts_a_correctly_signed_support` (R1–R7),
  `test_a_signed_support_reaches_the_product_episodes_decision`.
- Database refusals at write: `test_the_database_refuses_an_unsigned_authorization`,
  `test_the_database_refuses_an_authorization_under_another_persons_enrolment`,
  `test_the_database_refuses_a_support_with_no_authorization`,
  `test_the_database_refuses_a_support_on_another_hypothesis_authorization`,
  `test_the_database_refuses_binding_one_authorization_to_a_second_job`,
  `test_the_database_refuses_an_authorization_of_another_project`.
- R8: the three projection tests listed in §2.

`tests/contract/test_belief_support_recheck.py` (6 tests, EPI-005 / T-EPI-005): the check accepts;
refuses; raises (a raising check is a refusal); a relation to another subject or project is refused
before the check; only SUPPORTS relations are asked; without a check, behavior is unchanged.

Negative controls covered: wrong key (rogue authority), forged signature, tampered payload, replay
(signature and job binding), missing authorization, another hypothesis, another project, another
person's enrolment, revoked key. Each is refused by every reader or by the database at write.

## 4. Bypass found and fixed: the belief projection (R8)

**Attack.** Acting as the services' least-privilege role: write a forged verification
authorization and a SUPPORTS that rests on it (the database admits both, because SQL cannot verify
Ed25519). Run the product's `BeliefEpisode` with a verifier that accepts everything, which records an
ALLOW decision and a belief event that re-derive from their own snapshot.

**On `367163b`.** The honest, product-wired reader's transition inputs correctly excluded the forged
relation (`[]`), yet `BeliefEpisode.project` returned **SUPPORTED**. `verify_stored_revision`
re-derives the decision and re-checks warrants but never asked whether each SUPPORTS in the snapshot
is still support. P2's statement that decision and event rows are "re-derived and verified on read"
therefore did not cover the authorization. The same projection feeds the loop's state, the
confirmation re-check and the episode report's `final_state`.

Precondition with the product's own policies: the 2.0.0 promote policies also need the forged support
to be warranted (a DOMAIN link, or a reviewer's genuine grant on the observed link). The test uses a
registered promote policy without a warrant requirement to make the chain deterministic; finding F2
shows that the services' role can register such a policy itself.

Excerpt of `evidence/projection_forged_support_before.log`:

```
REPRODUCTION: honest product projection of hyp:... -> SUPPORTED applied ('bre:...', 'bre:sa-...')
REPRODUCTION: product transition inputs [] forged relation rel:obs:ind-projection-forged
E   Failed: DID NOT RAISE UnverifiedBeliefRevision
```

**Fix (`7f203df`).** `verify_stored_revision` and `verified_history` take an optional
`support_check`. With a check, every SUPPORTS in the decision snapshot must be a relation to the
decision's own subject and project and must pass the check; a raising check is a refusal
(`VerificationFailure.SUPPORT_UNVERIFIED`). `SqlRelationStore.support_problem` is the product's
check: for a SUPPORTS of a hypothesis with a screening conditioning record, the snapshot copy must
have the stored relation's content, and the store's verifier must find no problem; with no verifier,
it is not support (fail closed). `BeliefEpisode.project` passes it. In-memory stores, which hold no
screening records, are unchanged.

**Independent re-check by the main implementation agent (2026-11-04).** On a freshly recreated
database: the four relevant files (`tests/e2e/test_g0_security_assurance_postgres.py`,
`tests/e2e/test_g0_forged_authorization_read_path_postgres.py`,
`tests/contract/test_belief_support_recheck.py`,
`tests/contract/test_belief_authorization_verification.py`) gave **58 passed**. With only the three
source files reverted to `367163b`, `-k projection` gave **2 failed, 1 passed** (the two refusal
tests fail, the signed-support control passes), confirming that the tests detect the bypass and the
fix closes it. Source restored afterwards.

## 5. Other findings

- **F2 (open, high): the services' role can register transition policies.**
  `grant_database_roles` grants INSERT on `transition_policies`, and migration `005b` blocks only
  UPDATE and DELETE. As the services' role, a probe registered an `ACTIVE -> SUPPORTED` policy with
  no requirements and recorded an ALLOW decision and event under it; the honest projection then
  reads SUPPORTED with an empty snapshot. No forged support is needed, so any holder of the services'
  credentials can make any hypothesis SUPPORTED. The R8 fix cannot close this. Evidence:
  `evidence/services_role_registers_policy_before.log` (the probe was a temporary test and is not
  committed). Candidate fixes, both Owner decisions: (a) only the schema owner may write
  `transition_policies` (a trigger like the one on `capability_declarations`, or a REVOKE); (b) the
  projection accepts only the installed vertical's declared policies.
- **F3: enrolment and revocation rows are writable by the services' role.** The readers are not
  harmed: the `rogue_authority` case shows every read verifies the enrolling authority's signature
  against the pinned keys.
- **F4: the warrant-review question (R12) does not say when a support is not counted.** The product
  never queues such a relation, but `diagnostic_warrant_review_enqueue` can be called directly. A
  reviewer's grant on it is inert.

## 6. Results (observed)

| Check | Command | Result |
|---|---|---|
| ruff | `ruff check src tests scripts` | all checks passed |
| ruff format | `ruff format --check src tests scripts` | 587 files already formatted |
| mypy | `python -m mypy` | success, no issues in 282 source files |
| reproduction on `367163b` | `pytest tests/e2e/test_g0_security_assurance_postgres.py -k projection` | 2 failed, 1 passed |
| new and P2 read-path tests after the fix | `LAB_BRAIN_TEST_POSTGRES=1 pytest` on the two e2e files | 22 passed |
| contract tests | the two contract files | 36 passed |
| full default suite (before the status regeneration) | `pytest -q` | 1 failed, 2347 passed, 1262 skipped |
| fresh database migration | drop/create `lib_g0`, `scripts/migrate.py` twice, `--status` | 83 applied; second run up to date |
| full PostgreSQL suite on the fresh database (before the status regeneration) | `LAB_BRAIN_TEST_POSTGRES=1 pytest -q` | 1 failed, 3605 passed, 4 skipped (37 min) |
| status inventory | `scripts/update_status.py`, then `--check` and `--check --requirements-only` | up to date |
| spec conformance after regeneration | `pytest tests/spec -q` | 245 passed |
| requirement coverage | `scripts/check_requirement_coverage.py` | exit 0 |

The single failure in each full suite was
`tests/spec/test_status_freshness.py::test_the_hermetic_blocks_are_current`, because the inventory
was stale at that point; it passes after the regeneration (`tests/spec` 245 passed). These are two
runs with one known stale-inventory failure each, not one complete green run; the CI result for the
final pushed commit is the authoritative full run. The 4 PostgreSQL skips are live model, Lumerical,
network and Windows Credential Manager. The mutation battery was not extended or re-run. The local
server is PostgreSQL 16 without pgvector; CI uses `pgvector/pgvector:pg17`.

## 7. Database-level trust options (analysis only)

Read-only facts on the test server: `pgcrypto 1.3` is available; `pgsodium`, `plpython3u` and
`pg_tle` are not; only `plpgsql` is installed in the database. Nothing was installed or granted.

| Option | What it gives | What it cannot do | Cost and risk |
|---|---|---|---|
| separate roles and privileges: revoke INSERT on trust-root tables (`transition_policies`, enrolment and revocation tables, `belief_transition_decisions`, `belief_revision_events`) from the services' role | closes F2, F3 and the R8 precondition | verify a signature | changes production grants: Owner decision |
| SECURITY DEFINER write functions owned by the migrator (the `011t` spend-ledger pattern) | single write path; caller-role check; database clock; refuse policy ids not on an owner-maintained allow-list | verify a signature | needs `SET search_path` and an owner that cannot log in |
| triggers that reject unsigned rows | already present (the `011w` frame); keep | tell a forged signature from a real one | none |
| CHECK constraints | format checks (already present) | anything semantic | none |
| row-level security | `WITH CHECK (false)` for writes ≈ REVOKE; later per-project read isolation | verify signatures; binds no table owner or BYPASSRLS role (which `grant_database_roles` already refuses) | more machinery than REVOKE |
| pgcrypto | hashing, HMAC | Ed25519; an HMAC key in the database is readable by anyone who can run SQL | — |
| pgsodium `crypto_sign_verify_detached` | verify Ed25519 at admission | — | not available here; maintenance mode upstream; needs a superuser to install; moves the pinned authority keys, and so the trust root, into the database owner role (SPEC-ISSUE-018 item 4) |
| plpython3u | arbitrary verification | — | untrusted language, superuser: not recommended |
| external notarization (Owner-held append-only hash chain of decision and event ids) | detects rewriting by a compromised services host | prevent it | only if the host itself is not trusted |

Recommendation: privilege separation plus SECURITY DEFINER write paths first; keep Ed25519
verification in Python on every read, which now includes the projection. No test demonstration was
built, because demonstrating a REVOKE would itself change a shared role definition.

## 8. Design proposal: independently signed evaluator-environment attestations

Addresses SPEC-ISSUE-019 item 4 (today `verifier_id` is asserted, not signed). Reuses the
SPEC-ISSUE-018 enrolment machinery and folds in the SPEC-ISSUE-017 served-digest question.
Specification text only; nothing implemented; no key created.

**Who signs.** An evaluator: an active human actor who is not the implementation agent, not an
author or committer in the evaluated commit range, not the person who ran the evaluated episodes,
and not an author of the scored hypotheses. The evaluator's Ed25519 key is enrolled by an evaluation
authority (the Owner or a person the Owner names; a key distinct from the review authorities) with
scope `EVALUATION_ATTESTATION` inside the authority's signature.

**Key custody.** The evaluator's key lives only on the evaluator's own device (hardware token or
offline machine). The authority's public key is pinned in a file outside the repository and outside
anything an agent can read or write (`LAB_BRAIN_EVALUATION_AUTHORITIES`). Never in the repository,
CI secrets, the database or an agent session.

**What is bound** (canonical JSON, domain tag `lab-brain/g0-eval/environment-attestation@1`):
`attestation_id`; `commit_sha` and `tree_clean`; `environment_sha256` and the verification record's
`record_sha256`; `dependency_lock_sha256`, Python version and platform; `db_schema_sha256` (ordered
applied migrations with file hashes, plus a schema-dump hash); `test_inventory_sha256`, the outcomes
file hash and the pass/fail/skip counts; `scorer_sha256`; model id, model digest and
`digest_source`; `manifest_sha256` and `outputs_sha256`; `challenge_id` and a 32-byte `nonce` issued
by the authority; `issued_at` and `expires_at`; evaluator actor id and `enrolment_id`.

**Verification** (required for an ACCEPTANCE score):

1. Reject unknown or missing fields, non-canonical bytes, a wrong tag or kind.
2. The enrolment verifies under a pinned evaluation authority, with the right scope, for that actor,
   enrolled before `issued_at`, not revoked with effect at or before it.
3. The signature verifies over the exact canonical bytes.
4. Separation of duties holds (the "who signs" rule).
5. Every digest equals the value the verifier recomputes now; the commit is the one being accepted;
   `digest_source` is `served`.
6. The nonce belongs to an issued, unconsumed challenge bound to that commit; the time is within the
   window (for example 72 hours); the nonce is then recorded as consumed in an append-only ledger the
   services' role cannot write.
7. Any failure refuses ACCEPTANCE. A DIAGNOSTIC score still states that it is not an acceptance
   result.

**Revocation.** The authority signs a revocation with `effective_at`; attestations signed at or after
it are void. The Owner can void earlier attestations by id with a signed list; an acceptance resting
on a voided attestation is reopened.

**Negative controls** (each must be refused): self-signed by the implementer (key not enrolled by a
pinned authority, or signer is an author or committer in the range); stale SHA; wrong environment
digest; wrong lock, schema or test-inventory digest; replayed nonce, or a nonce issued for another
commit; signature over a different payload; expired; signed after the key's revocation; enrolment of
the wrong scope; authority not pinned; model digest only declared, not served, for ACCEPTANCE.

No reference verifier was implemented: the required fields, the custody rule and the separation of
duties are SPEC-ISSUE-018/019 decisions, and implementing them first would build a provisional
reading into the acceptance path.

## 9. Residual risks

- F2 is open and high: a holder of the services' credentials can make any hypothesis SUPPORTED.
- The general A12 boundary (the services' role can write any row the SQL frames admit) is unchanged.
- Writer-supplied facts (capture times, lineage, media types, run start times) remain unverifiable.
- Revocation fails closed for whole histories: a backdated revocation makes affected projections
  raise rather than change.
- F4: a warrant-review question can show a support that is not counted.
- The trust root is still the pinned authority file and whoever controls the deployment
  configuration.
- All of this is implementation-side testing.

## 10. Owner decisions required

1. F2: owner-only writes to `transition_policies` (trigger or REVOKE), and/or a vertical policy
   allow-list in the projection.
2. Privilege separation for the trust-root tables plus SECURITY DEFINER write paths for decisions
   and events; separately, whether to install an in-database Ed25519 verifier such as pgsodium
   (SPEC-ISSUE-018 item 4), which would move the pinned keys into the database.
3. Revocation semantics: refuse the whole history that relies on a key revoked before it signed
   (current behavior, following `WARRANT_UNVERIFIED`), or roll back only the affected events.
4. Adopt, amend or reject the evaluator-environment attestation design of §8 (SPEC-ISSUE-019 item 4).
5. Whether the warrant-review question must say when a support is not counted (F4).

G0 remains NOT PASSED. This report does not replace the Independent Chief Auditor's review.
