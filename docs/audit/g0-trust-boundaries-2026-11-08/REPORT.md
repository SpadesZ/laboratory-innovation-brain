# G0 trust boundaries around belief transitions: R-2, R-3, R-1

Date: 2026-11-08 to 2026-11-11. Branch `claude/lib-implementation-agent-47evs0-g0-trust`, baseline `24fae8b`.

**Status:** implementation-side evidence, not an independent audit. **G0 remains NOT PASSED.** `READY_FOR_REAL_RESEARCH` stays false. Integration needs the Human Owner and the Independent Chief Auditor (ICA). One change (item 1) revokes a privilege from the services' role and needs Owner approval before merge or deployment.

**Limits kept:**
- No database extension installed.
- No real credentials touched; only throwaway test roles created by the product's own `grant_database_roles`.
- No existing migration edited; one new forward migration, `011y`.
- No existing assertion weakened. Three existing tests had their setup moved to the owner path or to stored data (§2, §3, §4).
- Zero cost.

## 1. Commits

| SHA | Message (short) |
|---|---|
| `176ef76` | Reproductions only: R-2, R-3 and R-1 through the real services' role (strict xfail, no fix). Adds `tests/e2e/test_g0_trust_boundaries_postgres.py` and `evidence/reproduction_before.log`. |
| `bfc7db4` | Close R-2: only the schema owner registers diagnostic declaration sets (`011y`). |
| `efcb974` | Close R-3: the belief projection honours only policies the installed code declares (also adds inert R-1 plumbing). |
| `7b076da` | Close R-1 (code part): a decision's snapshot must be what the database holds. |
| `583578e` | Regenerate the status inventory (85 migrations, 3636 collected). |
| `364e0cf` | Fixes from the first full PostgreSQL run (§8). |
| `5965984` | 16 `trust_*` mutation entries (additions only); wrap a comment line. |
| `6878b6a` | Evidence: `verification_after.log`, `trust_mutation_battery.log`. |

`scripts/check_commit_messages.py`: no AI authorship found.

**Files changed:**
- `migrations/011y_diagnostic_declaration_sets_are_the_owners.sql` (new)
- `scripts/migrate.py`, `scripts/mutation_battery.py`
- `src/lab_brain/core/belief.py`, `core/episode.py`, `core/repositories/evidence.py`, `core/repositories/warrants.py`
- `src/lab_brain/interfaces/cli.py`, `interfaces/deployment.py`, `interfaces/web/app.py`
- `src/lab_brain/research/service.py`, `research/confirmation.py`
- Tests: `tests/e2e/test_g0_trust_boundaries_postgres.py` (new, 15 tests), `tests/vertical_fixtures.py`, `tests/integration/test_least_privilege_postgres.py`, `tests/e2e/test_causal_warrant_v1_1_postgres.py`, `tests/e2e/test_g0_security_assurance_postgres.py`, `tests/e2e/test_sim_fidelity_vertical_postgres.py`
- `IMPLEMENTATION_STATUS.md`
- `docs/audit/g0-trust-boundaries-2026-11-08/evidence/` (three logs)

## 2. Item 1 (R-2): diagnostic declaration sets — vulnerable, fixed

**What an attacker gained** (reproduced on the baseline as the real services' role):
- **Weaker write-time gate.** An uncatalogued account's support had no warrant in SQL. The services' role registered a one-class set naming that mechanism with the observed signature, and the SQL confirmation rule then read the link as `DOMAIN`-warranted — a warrant nobody accountable gave.
- **Blocked confirmations.** A rogue class declaring the cause's own observed outcome as another mechanism's signature made the SQL rule report a breach, so the database refused a legitimate confirmation.
- **Permanent denial of service.** Any undeclared set makes `SqlDeclarationSetStore.ensure` raise on every research run. The table is append-only (`012p`), so only a superuser disabling triggers could remove the row.
- The Python readers were not loosened (the R4 re-check re-derives with the code's own set). The harm was to the SQL gate and to availability.

**Fix:**
- `011y` adds a `BEFORE INSERT` guard: the same owner-membership test as `011s`/`011x`, SQLSTATE 42501, fixed `search_path`, ordered before the well-formedness trigger. Existing rows untouched; `012p` still refuses UPDATE/DELETE.
- `grant_database_roles` revokes INSERT, UPDATE, DELETE and TRUNCATE on the table on every run.
- New `SqlDeclarationSetStore.may_register()`. `ensure()` refuses a missing version under a non-owner role with `DeclarationRegistrationRefused` (naming the operator command) before writing anything.
- `lab-brain admin register-policies` (run as the migrator by `deployment/docker/bootstrap.sh`) now also registers the vertical's declaration sets.
- A SECURITY DEFINER registration function was rejected for the same reason as F2: SQL cannot read the code's declarations.

**Tests (after the fix):** both reproductions refused; a mistaken INSERT grant is still refused by the guard and revoked by the next `db-roles`; the services' role cannot UPDATE, DELETE, TRUNCATE, disable/drop the trigger, replace the function, set `session_replication_role` or self-grant; repeated `db-roles`/`migrate.py` leave SELECT only and the trigger enabled; positive control: the owner registers (idempotent), the services' role then reads and passes `ensure()` without writing; the auditor role has SELECT only.

**Setup moved to the owner path:** `register_case_policies` now also registers the declaration set as the owner. In the least-privilege test, the services' `DELETE` is now refused with `InsufficientPrivilege` instead of `RaiseException` (still refused, one layer earlier).

## 3. Item 2 (R-3, F2 option (b)): undeclared policies — vulnerable, fixed

**Reproduced:** the owner registers a "requires nothing" promote policy (standing in for a pre-`011x` row); the services' role runs an episode under it; the projection read **SUPPORTED**.

**Decision: implement.** `011x` stops only new rows; older rows kept deciding beliefs.
- Declared historical versions stay accepted (superseded 1.0.0 policies remain declared).
- The check compares content, not only the name.
- `register-policies` lists every undeclared or differing row with the number of decisions and events the projection would refuse, before anything is refused.
- Refusal fails closed for the whole history, like every other `UnverifiedBeliefRevision`.

Silently filtering events, write-time-only checks and trusting the owner-only table were rejected: none covers rows written before `011x`.

**Fix:** `verify_stored_revision` and `verified_history` take `declared_policies`; a transition re-derives only under a declared policy whose registered row equals the code's declaration; otherwise typed reason `UNDECLARED_POLICY`. Wired into the research service's deciding episode (`ResearchEpisodeService._belief_episode`), its report reader, `research.confirmation.confirmation_verifier` (now required), and the web app's reuse check. `None` keeps the old behaviour for in-process and fixture wirings.

**Tests:** both product readers refuse with `UNDECLARED_POLICY` while the same history without the list reads SUPPORTED; the operator listing prints the refusal counts; positive control reads ACTIVE; a differing row under a declared name is refused.

## 4. Item 3 (R-1): snapshot evidence — partly vulnerable, code part fixed

| Probe on the baseline (services' role) | Projection | Vulnerable? |
|---|---|---|
| Unscreened hypothesis; snapshot counts a SUPPORTS that is not stored | SUPPORTED | yes |
| Snapshot authority class `MEAS_CALIBRATED`; stored attestation gives `DESIGN_INSPECTION` | SUPPORTED | yes |
| Snapshot condition match EXACT; database records PARTIAL | SUPPORTED | yes |
| Declared 2.0.0 promote policy: phantom SUPPORTS with forged warrant record | refused, `WARRANT_UNVERIFIED` | no |
| Raw event with no decision, or citing NEED_MORE_EVIDENCE | database refuses (`005d`) | no |

The 2.0.0 gate reads condition matches straight from the snapshot, so the condition-match forgery applies to the product's 2.0.0 promote policies. This was established by reading `_decide_warranted.thresholds`; it is not demonstrated end to end.

**Fix:** `SqlRelationStore.snapshot_problem(decision)`, applied by `BeliefEpisode.project` to every stored decision after re-derivation. It checks the snapshot's subject and project; that every relation is epistemic, of that subject and project, and equal by content to the stored relation (later invalidation is not a change); every condition match equals the stored match; the authority classes are exactly those of the stored attestations. A mismatch, or a check that cannot run, refuses with typed reason `EVIDENCE_UNVERIFIED`.

**Setup moved:** `test_sim_fidelity_vertical_postgres` now stores its condition match before use; assertions unchanged.

**Proposed privilege separation — design only, production grants not changed:**
1. Revoke the services' row writes on `belief_transition_decisions`, `belief_revision_events`, `belief_revision_event_attestations`, `belief_revision_event_relations`.
2. Add a migrator-owned SECURITY DEFINER `belief_transition_record(decision, event)` (fixed `search_path`, executable only by the services' role) that refuses missing/superseded policies, snapshot relations not equal to stored current rows, differing condition matches, authority classes not recomputed from attestations, and a conflict set other than the subject's currently unresolved conflicts; it stamps database-clock times and writes through `belief_revision_event_append`.
3. Python re-derivation and read-time checks stay (SQL cannot run `evaluate`).

Stored-but-fabricated measurements (general A12) still need signed instrument-side provenance.

## 5. Privilege matrix change (services' role)

| Table | Before | After | Write-time guard |
|---|---|---|---|
| `diagnostic_declaration_sets` | SELECT, INSERT, UPDATE, DELETE | **SELECT** | **`011y` owner-only INSERT**; `012p` blocks UPDATE/DELETE |

All other F2 matrix rows unchanged.

## 6. Reader reassessment

| # | Reader | Status now |
|---|---|---|
| R1 | Transition inputs | Unchanged (`011w`). |
| R2 | Loop confirmation rule | Belief state from the checked projection. |
| R3 | Episode attempt | Built by `_belief_episode`; prior projection checked. |
| R4 | Confirmation re-check | Declared policies plus snapshot check. |
| R5–R7, R9–R11, R14 | — | Unchanged. |
| R8 | Projection | Adds `UNDECLARED_POLICY`, `EVIDENCE_UNVERIFIED`. Remaining: conflict omission, ungated independence summary, writer-supplied times. **Medium.** |
| R12 | Warrant-review question (F4) | Unchanged. **Low.** |
| R13 | SQL confirmation rule | Reads only owner-registered declarations; still reads raw events and unverifiable grant signatures. **Medium.** |
| R15 (new) | Raw history display ("moves" list, episode transitions) | Lists events the projection refuses without marking them. **Low** (display only). |

## 7. Residual risks

| Id | Risk | Severity |
|---|---|---|
| T-1 | General A12: the services' role writes observations, attestations and relations; a fabricated but stored measurement cannot be told from a real one. | High (pre-existing) |
| T-2 | Decisions and events still services-writable: conflict omission, ungated independence counts, writer times; one forged row can make a whole history refuse (denial of service). | Medium |
| T-3 | Declaration-set rows written before `011y` block every run and need a superuser to remove; no quarantine procedure. | Medium |
| T-4 | SQL confirmation rule reads raw events and unverified grant signatures. | Medium |
| T-5 | `review_queue_policies` (R-4) and `capabilities` (R-5) unchanged. | Low/Medium |
| T-6 | Owner, migrator and superusers fully trusted. | Accepted trust root |
| T-7 | Tools building `BeliefEpisode` without `declared_policies` read every registered policy. | Low |

## 8. Results (implementation agent)

| Check | Result |
|---|---|
| `ruff check src tests scripts` / `ruff format --check` | pass / 589 files formatted |
| `python -m mypy` | no issues, 282 files |
| `pytest tests/spec -q` | 245 passed |
| Fresh database, `migrate.py` twice | 85 applied; second run up to date |
| Full PostgreSQL suite on a fresh database at `5965984` | **3632 passed, 4 skipped**, one complete run; repeated after the mutation battery with the same result |
| Full default suite at `5965984` | **2348 passed, 1288 skipped**, one complete run |
| `update_status.py --check`, requirement coverage | up to date; exit 0 |

The 4 PostgreSQL skips are live model, Lumerical, network and Windows Credential Manager. The first full PostgreSQL run (before `364e0cf`) had 6 failures, fixed without weakening any assertion: a raw-SQL forgery test now again reports `NOT_REDERIVABLE` (snapshot check moved after re-derivation); the `011w` structural count restored by keeping the report reader's own construction; four sim-fidelity tests now store their condition match first.

## 9. Mutation battery

16 entries added to `scripts/mutation_battery.py` (nothing existing edited); each disables one layer and runs only the trust-boundaries file with `-x`; SQL mutants run on cloned template databases. This is a targeted run, not a whole-repository mutation run. **16/16 killed** (`evidence/trust_mutation_battery.log`).

Not covered: the report reader's declared-policy line; the snapshot subject comparison for non-SUPPORTS relations; the "a check that raises is a refusal" branch.

## 10. Lead implementation agent's independent check (2026-11-11)

- Tree clean; local head equals `origin` at `6878b6a`; all 8 commits authored `SpadesZ`, no AI authorship lines.
- The only migration change is the new file `011y`; no existing migration or `docs/audit` evidence modified or deleted; frozen Discovery engine untouched; no `S35-` identifiers in `src/` or `tests/`.
- Fresh database `lib_g0v`, `migrate.py` twice, then `tests/e2e/test_g0_trust_boundaries_postgres.py`: **15 passed**.
- Reproduction before the fix: commit `176ef76` on a fresh database `lib_g0b`: **2 passed, 6 xfailed (strict)** — all six attacks (R-2 ×2, R-3 ×1, R-1 ×3) succeed without the fixes.

## 11. Owner decisions

1. **Production privilege change (item 1):** approve owner-only registration of `diagnostic_declaration_sets` (`011y` plus the REVOKE). Required before merge or deployment.
2. Adopt the declared-policy rule in the projection (item 2), including whole-history fail-closed refusal and the operator listing as the pre-upgrade review step.
3. Approve, amend or reject the SECURITY DEFINER write path for decisions and events (§4).
4. A quarantine procedure for rows written before `011y`/`011x` (T-3).
5. Integration after Independent Chief Auditor review.

This report does not replace the Independent Chief Auditor's review.
