# G0 finding F2: owner-only transition policy registration

Date: 2026-11-04 (report committed 2026-11-08). Branch `claude/lib-implementation-agent-47evs0-g0-f2`.
Baseline: `47451e124f629907c7350f7e3ead7d1c19aaef63` (the G0 security assurance report, which
records F2 as open).

**Status: implementation-side engineering evidence, not an independent audit. G0 remains NOT
PASSED. `READY_FOR_REAL_RESEARCH` stays false.** The fix (commit B) was **approved by the Owner on
2026-11-04 for owner-only TransitionPolicy registration** (F2 option (a): only the schema owner or
migrator may write `transition_policies`). **Integration still requires Independent Chief Auditor
review. Merging and deploying are not authorized.**

Limits kept: no database extension installed or used; no production privilege or credential
changed (all roles are throwaway roles on the local test server); no existing migration edited; no
existing test assertion weakened; zero cost (no paid model, no network, no Lumerical).

## 1. Commits

| | Commit | What |
|---|---|---|
| A | `4f646bc` | regression test only, no privilege change: `tests/e2e/test_g0_f2_policy_registration_postgres.py::test_the_services_role_cannot_register_a_policy_that_makes_a_hypothesis_supported`, marked `xfail(strict=True)`; reproduction log; status inventory (3611 collected) |
| B | `b56b5a6` | the fix (Owner-approved): `grant_database_roles` revokes writes on `transition_policies`; migration `011x`; owner-only registration path (`register_vertical_policies`, `lab-brain admin register-policies`, bootstrap); xfail marker removed; 10 further tests; 6 `f2_*` mutation entries; one existing test's setup moved to the owner path |
| B' | `ef5d713` | status inventory regenerated (84 migrations, 3621 collected) |
| B'' | `63a018d` | evidence logs |

Commit A can be taken without commit B: on unfixed code it is a strict xfail, so the suite stays
green; if the fix lands without removing the marker it becomes a hard failure (`XPASS(strict)`,
`evidence/f2_commit_a_test_against_fix.log`).

## 2. Reproduction before the fix

`evidence/f2_reproduction_before.log`, on the baseline with no source change. The services' role is
created exactly as a deployment creates it (`deployment/docker/service_roles.py`, then
`grant_database_roles`, i.e. `lab-brain admin db-roles`):

```
F2: services role registering policy:g0-f2-services-written-c61ca25c4388: refused=None
F2: services-role transition ALLOW event=bre:sa-86b6138e86ed489c81873962b4f1470d snapshot relations=[]
F2: honest product projection of hyp:384e7420-... -> SUPPORTED
1 failed   (with --runxfail)
1 xfailed  (as committed)
```

Attack chain: as the services' role, register an `ACTIVE -> SUPPORTED` policy that requires
nothing; run the product's `BeliefEpisode` under it (an event must cite a trigger; any admitted
attestation of the project serves, here the screening measurement, which is not a support); the
honest projection, wired with the product's relation store and verifier, reads SUPPORTED. No forged
support is involved.

## 3. Verification after the fix

Commit A's file with its marker kept gives `XPASS(strict)` on the fixed code (1 failed); commit B's
test passes (`refused=InsufficientPrivilege('permission denied for table transition_policies')`,
`projection -> ACTIVE`).

| Check | Command | Result |
|---|---|---|
| ruff | `ruff check src tests scripts` | all checks passed |
| ruff format | `ruff format --check src tests scripts` | 588 files already formatted |
| mypy | `python -m mypy` | no issues in 282 source files |
| spec | `pytest tests/spec -q` | 245 passed |
| F2 tests | F2 file, PostgreSQL | 11 passed |
| fresh database | drop/create `lib_g0`, `migrate.py` twice, `--status` | 84 applied; second run up to date; 0 pending |
| full PostgreSQL suite on that database (at `ef5d713`) | `LAB_BRAIN_TEST_POSTGRES=1 pytest -q` | **3617 passed, 4 skipped** (25:18), one complete run |
| full default suite (at `ef5d713`) | `pytest -q` | **2348 passed, 1273 skipped**, one complete run |
| status inventory | `update_status.py --check`; `--check --requirements-only` | up to date |
| requirement coverage | `check_requirement_coverage.py` | exit 0 |
| commit messages | `check_commit_messages.py` | no AI authorship found |

The first default run on commit B failed 2 status-freshness tests only because the inventory was
stale; it was regenerated (`ef5d713`) and the two runs above were made afterwards. The 4
PostgreSQL skips are live model, Lumerical, network and Windows Credential Manager. Local server:
PostgreSQL 16 without pgvector; CI uses `pgvector/pgvector:pg17`.

**Independent re-check by the main implementation agent (2026-11-04).** On a freshly recreated
database at `63a018d`: the F2 file, `tests/integration/test_least_privilege_postgres.py` and
`tests/e2e/test_g0_security_assurance_postgres.py` gave **33 passed**.

## 4. Design

Two layers; either refuses the services' role on its own.

1. **Privilege.** `grant_database_roles` adds `REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON
   transition_policies FROM <app>` after its `GRANT ... ON ALL TABLES`. Because the command revokes
   and re-grants on every run, the table stays read-only to the services after a second run, after
   migrations and after the role helper (`ensure_roles`).
2. **Database guard** (`migrations/011x_transition_policies_are_the_owners.sql`, a new forward
   migration in `scripts/migrate.py` `APPLY_ORDER` after `011w`). A `BEFORE INSERT` row trigger
   refuses unless `pg_has_role(current_user, <table owner>, 'MEMBER')` — the same boundary `011s`
   draws for `capability_declarations`. SQLSTATE 42501, message names `011x`; function is
   `SECURITY INVOKER` with `SET search_path = pg_catalog, public`. The services' role owns nothing
   (`grant_database_roles` refuses owners, superusers and roles able to set
   `session_replication_role`), so it cannot drop, disable or replace the trigger. UPDATE and DELETE
   stay refused for everyone by `005b`.

**Authorized administration.** The only legitimate policies are those the code declares
(`ADMISSION_POLICY` and the vertical's `transition_policies`). `register_vertical_policies`
registers missing declared policies only when `SqlTransitionPolicyStore.may_register()` (the same
owner test) holds, otherwise raises `PolicyRegistrationRefused` naming the operator command, before
anything is written. `ResearchEpisodeService._register` uses it. `lab-brain admin register-policies
[--domain]` (migrator; idempotent) prints `registered` or `present` per declared policy and lists
every registered row the product does not declare (`undeclared policy@version`) without touching it.
`deployment/docker/bootstrap.sh` runs it at every start (after the four steps the container test
pins).

**Why not a SECURITY DEFINER function.** It would need to know which policies are legitimate; that
list lives in the code, which SQL cannot read, so it would need an owner-maintained allow-list —
the owner registering the policies anyway, plus one more definer function to keep safe.

**History.** The guard fires on INSERT only. Existing rows, including any written by the services
before `011x`, stay readable; decisions and events citing them still re-derive. Nothing is deleted
or quarantined; that is an Owner decision (R-3).

**Changed existing test setup.** `tests/integration/test_least_privilege_postgres.py` ran
`run_case` as the services' role, which on a fresh database registered the case's policies. The two
affected tests now call `register_case_policies(db)` (new in `tests/vertical_fixtures.py`) as the
owner first. Their assertions are unchanged.

## 5. Tests (`tests/e2e/test_g0_f2_policy_registration_postgres.py`, 11)

| Test | Proves |
|---|---|
| `test_the_services_role_cannot_register_a_policy_that_makes_a_hypothesis_supported` | the full attack through the real services' role and the product projection: refused (by privilege or guard), policy absent, projection stays ACTIVE |
| `test_the_guard_refuses_the_services_role_where_insert_was_granted_by_mistake` | with INSERT granted by hand, `011x` still refuses; the next `db-roles` run revokes the grant |
| `test_the_services_role_cannot_change_erase_or_switch_off_the_guard` | refused: UPDATE, DELETE, TRUNCATE, DISABLE TRIGGER (named and ALL), DROP TRIGGER, replacing or dropping the function, `SET session_replication_role`, `ALTER DEFAULT PRIVILEGES FOR ROLE <owner>`, `ALTER TABLE ... OWNER TO`; a self-GRANT grants nothing; with UPDATE/DELETE granted by mistake, `005b` still refuses |
| `test_repeated_grants_role_helpers_and_migrations_do_not_reopen_it` | after `db-roles` twice, `ensure_roles`, `migrate.py` again and `db-roles` again: SELECT only, trigger present and enabled; the auditor role reads but cannot insert |
| `test_a_temporary_table_shadowing_the_policies_does_not_help` | a session-local `transition_policies` table cannot satisfy the decision/event foreign keys; projection unchanged |
| `test_an_owner_registered_policy_still_governs_a_legitimate_transition` | positive control: owner-registered policy, signed measured support, product verifier → SUPPORTED |
| `test_registered_policies_stay_readable_and_their_decisions_still_re_derive` | historical rows (including a legacy row) readable; history re-derives |
| `test_the_operator_command_registers_the_declared_policies_as_the_owner` | exit 0, idempotent; undeclared rows listed, untouched |
| `test_the_service_path_refuses_a_missing_policy_under_the_services_role` | `PolicyRegistrationRefused` under the services' role; the owner registers; no-op when nothing missing |
| `test_the_operator_command_refuses_the_services_role` | exit 2; nothing registered |
| `test_residual_the_services_role_privileges_on_the_trust_roots` | records the privilege matrix; `transition_policies` and `schema_migrations` read-only; no TRUNCATE anywhere |

## 6. Privilege matrix of the services' role (`evidence/privilege_matrix_before_after.log`)

| Table | Before | After | Write-time guard |
|---|---|---|---|
| transition_policies | S I U D | **S** | **011x owner-only INSERT**; 005b blocks U/D |
| belief_transition_decisions | S I U D | S I U D | FK to policy; no UPDATE |
| belief_revision_events | S I U D | S I U D | policy FK, superseded-policy refusal, authorization and evidence triggers |
| relation_judgments, attestations | S I U D | S I U D | screening guard, project and observation checks |
| verification_authorizations | S I U D | S I U D | signed and prospective frames (Ed25519 verified on read) |
| enrolment and revocation tables | S I U D | S I U D | member checks; append-only |
| capability_declarations | S I U D | S I U D | 011s owner-only INSERT |
| capabilities | S I U D | S I U D | declared contract fixed |
| diagnostic_declaration_sets | S I U D | S I U D | well-formed, append-only (R-2) |
| diagnostic_warrant_grants, review_resolutions | S I U D | S I U D | closure and review invariants |
| review_queue_policies | S I U D | S I U D | none (R-4) |
| schema_migrations, llm_spend_budgets, account_change_audit | S | S | already revoked |

S/I/U/D = SELECT/INSERT/UPDATE/DELETE. No table grants TRUNCATE, before or after.

## 7. Re-assessment of consequential read paths and residual risks

The readers R1–R8 of the G0 security assurance report are unchanged and still verify signed
authorizations; R8 (the projection) additionally cannot be fed by a services-written policy now.
Only F2 was fixed.

| Id | Risk | Severity | Probed? |
|---|---|---|---|
| R-1 | General A12 boundary: the services' role writes evidence, decisions and events. For a hypothesis with no screening record, the projection does not compare a snapshot SUPPORTS against a stored, verified relation; the 2.0.0 promote policies still require a diagnostic warrant, which the projection re-checks | High (pre-existing) | no |
| R-2 | `diagnostic_declaration_sets` is writable by the services' role and read by the SQL confirmation rule (`012p`); it can loosen that write-time gate or deny service; the Python readers use the code's set. Same shape as F2 | Medium | no |
| R-3 | policy rows written before `011x` are kept and honoured; `register-policies` lists undeclared ones; nothing reviews them automatically | Medium (deployment history) | readability only |
| R-4 | `review_queue_policies` has no guard (capacity, SLA, expiry, declaring person); no path to SUPPORTED found | Low/Medium | no |
| R-5 | `capabilities` writable; an undeclared kind cannot support a post-screening hypothesis | Low | — |
| R-6 | enrolments and revocations (F3) append-only and verified against pinned keys on every read | Low | prior pass |
| R-7 | the owner, migrator and any superuser are fully trusted | accepted trust root | — |
| R-8 | a future migration recreating `transition_policies` would lose the trigger; `db-roles` would still revoke | Low | — |

## 8. Mutation battery (`evidence/f2_mutation_battery.log`): 6/6 killed

Scope: six additions to `scripts/mutation_battery.py`, each disabling one layer of the fix; only the
F2 test file is run, with `-x`; SQL mutants are applied to cloned template databases, never to the
migration file. This is not a whole-repository mutation run.

| Entry | First test that kills it |
|---|---|
| `f2_services_role_keeps_insert_on_policies` | `test_the_guard_refuses_the_services_role_where_insert_was_granted_by_mistake` |
| `f2_policy_guard_admits_every_role` | same |
| `f2_policy_guard_only_warns` | same |
| `f2_policy_guard_fires_on_update` | same |
| `f2_service_registers_policies_as_any_role` | `test_the_service_path_refuses_a_missing_policy_under_the_services_role` |
| `f2_every_role_may_register_policies` | same |

The end-to-end attack test alone fails only when both layers are off; a two-layer mutant spans two
files and cannot be one battery entry.

## 9. Owner decisions

Taken: owner-only TransitionPolicy registration (F2 option (a)), 2026-11-04.

Open:
1. Integration of commits A and B after Independent Chief Auditor review (merge and deploy not
   authorized).
2. F2 option (b) in addition: the projection accepts only the vertical's declared policies.
3. Review or quarantine of policy rows written before `011x` (R-3).
4. The owner-only rule for `diagnostic_declaration_sets`, and possibly `review_queue_policies`
   (R-2, R-4).
5. Privilege separation and SECURITY DEFINER write paths for decisions and events (R-1, A12).

G0 remains NOT PASSED. This report does not replace the Independent Chief Auditor's review.
