# G0 trust boundaries, round 4: T-2, T-3, R15, R-4 (T-1 and R-5 assessed only)

Date: 2026-11-11 to 2026-11-20. Branch `claude/lib-implementation-agent-47evs0-g0-boundary4`, baseline `e2872de`, final code commit `7927618`, evidence `fd3ddec`.

**Status:** implementation-side evidence, not an independent audit. **G0 remains NOT PASSED.** `READY_FOR_REAL_RESEARCH` stays false. Nothing is merged or deployed. **Two commits change production privileges and need Owner approval**; each is separate from the code it completes, and the code works with and without them.

**Limits kept:**
- No database extension, no real credentials, no cost.
- No existing migration edited. Three new forward migrations, appended to `APPLY_ORDER` in this order: `011z`, `012t`, `010d`.
- No earlier round's evidence touched.
- No existing assertion weakened; tests whose setup moved are listed in §8.

## 1. Commits

| SHA | What |
|---|---|
| `fb89d36` | Reproductions only (strict xfail, no fix): 8 PostgreSQL tests through the real services' role and 3 unit tests, plus `reproduction_before.log`. All 11 reproduce on `e2872de`. |
| `8d69bd3` | T-2: the migrator's write gate for belief decisions and events (`011z`); the SQL stores and `BeliefEpisode` write through it. |
| `81d6559` | T-3 and T-2(d): the owner's append-only quarantine (`012t`), honoured by the readers, plus `lab-brain admin quarantine`. |
| `9632b46` | R15: the report's moves list and the episode view mark events the projection does not count. |
| `c52f4a7` | R-4: owner-only guard on `review_queue_policies` (`010d`). |
| `6b52521` | **REQUIRES OWNER APPROVAL**: revoke the services' row writes on the four belief tables (T-2). |
| `b90e975` | **REQUIRES OWNER APPROVAL**: revoke the services' row writes on `review_queue_policies` (R-4). |
| `90911b1` | 23 `round4_*` mutation-battery entries (additions only). |
| `7927618` | Regenerated status inventory (88 migrations). |
| `fd3ddec` | Evidence logs. |

All 10 commits are authored SpadesZ; `check_commit_messages.py` finds no AI authorship.

## 2. T-2: belief decisions and events written by the services' role (Medium)

**Status:** vulnerable; fixed for the product's write path; raw SQL is closed only by the Owner-gated REVOKE.

**Reproduced on `e2872de`** through the services' role and the product's episode wiring:

| Attack | Before the fix |
|---|---|
| (a) snapshot omits an open SIM_TO_REAL conflict that blocks the policy | projection reads SUPPORTED |
| (b) `independent_count=50` claimed with one stored evidence line (policy needs 3) | projection reads SUPPORTED |
| (c) promotion dated 30 days ahead; an honest challenge recorded now | challenge skipped; SUPPORTED |
| (d) one forged row: an honest NEED_MORE_EVIDENCE decision copied as ALLOW, plus an event | whole history refused (`NOT_REDERIVABLE`); the owner's DELETE refused |
| (a) again with plain INSERTs | SUPPORTED |

**Fix: `011z`, the write gate.** `belief_transition_record` and `belief_admission_record` are migrator-owned SECURITY DEFINER functions with a fixed search path; EXECUTE revoked from PUBLIC and granted to the services' role by `db-roles`. Before recording a decision (and, for an ALLOW, its event in the same statement through the existing 005d append) the gate checks:
- the policy is registered, of the right kind, and not superseded;
- the snapshot's view is of the decision's own subject and project;
- every relation is the stored, current relation with equal content;
- every condition match equals the stored match (id, state, fields, unknowns, tolerance);
- the authority classes equal those of the stored attestations;
- the conflicts are exactly the subject's currently unresolved conflicts (id, type, blocking, status);
- a WORK independence count is at most the number of distinct evidence lines (capability, backend, inputs, parameters) behind the subject's current relations; an attestation with no stored run counts as at most one line; a non-WORK count above zero is refused;
- the record is not dated more than 5 minutes after the database clock, and an event is not dated before the subject's latest event.

The database clock and the calling login role are stored in `belief_write_records` (owner-only trigger, append-only). **Design change:** instead of overwriting row times (which decide replay order and would change existing histories), the gate bounds the supplied time to [latest event, database clock + 5 min] and records the clock alongside.

**After the fix, without the REVOKE** (`focused_without_revoke.log` at `c52f4a7`: 123 passed, 1 strict xfail): (a), (b), (c), the R-1 forgeries and a back-dated event are refused at write time with typed reasons; an honest transition is recorded with the services' login role; PUBLIC and the auditor cannot execute the gate; the services cannot alter its record or functions. The raw-INSERT variant stays strict xfail: without the REVOKE the services' own code can skip the gate.

**REVOKE `6b52521` (Owner approval):** `db-roles` revokes INSERT, UPDATE, DELETE, TRUNCATE on `belief_transition_decisions`, `belief_revision_events`, `belief_revision_event_attestations`, `belief_revision_event_relations`. Then the raw variant is refused (InsufficientPrivilege) and privileges stay SELECT-only after repeated `db-roles`/`migrate.py`.

**(d) denial of service:** SQL cannot run `evaluate`, so a decision that passes the gate but does not re-derive can still make the projection refuse the history; the remedy is the quarantine (§3).

## 3. T-3: rows written before `011x`/`011y` block for good (Medium)

**Status:** vulnerable, fixed.

**Reproduced:** a pre-`011y` declaration set makes `ensure()` refuse every run, and the owner's DELETE is refused; a pre-`011x` policy makes the projection refuse every history with an event under it (`UNDECLARED_POLICY`).

**Fix: `012t`, the owner's quarantine.** `owner_quarantines` records kind (policy, declaration set, belief event), id and version, a reason (≥ 10 characters), deciding actor, database clock and login role. Owner-only (same membership test as `011x`), append-only, refuses non-existent rows, one quarantine per row; the quarantined row is never changed. `diagnostic_declarations` leaves a quarantined set out (and it supersedes nothing); the projection skips a quarantined event and every event under a quarantined policy as `OWNER_QUARANTINED`, and the cascade skips dependants. Command: `lab-brain admin quarantine {policy,declaration-set,event} REF --reason ... --actor ...`; it refuses the installed code's own policies and sets; `register-policies` lists quarantined rows. There is deliberately no reversal.

**After:** with the set quarantined, `ensure()` passes and the row is byte-identical; with the policy quarantined, the projection reads ACTIVE; with the forged event quarantined, the history reads ACTIVE and the row is kept; the services' role is refused (command exits 2); the owner cannot UPDATE or DELETE a quarantine.

## 4. R15: raw history display (Low, display only)

**Status:** vulnerable, fixed. `research.service.belief_moves` appends `-- not counted: <why>` to skipped moves (or all moves of a refused history). `load_episode_view(..., belief=...)` sets `Transition.not_counted`; the web workspace passes the new `research.confirmation.belief_reader`. The page says in English and Traditional Chinese that a recorded move was not counted. A view built without a belief reader marks nothing (T-7).

## 5. T-5: `review_queue_policies` (R-4) and `capabilities` (R-5)

**R-4: vulnerable, fixed.** Reproduced: the services' role deactivated a project's queue and declared one that expires every review after one minute in a member's name; `review_expire` then records REVIEW_EXPIRY governance events as that person's decision and closes conflicts as ACCEPTED_AS_OPEN_QUESTION, so human review effectively stops (no path to SUPPORTED found). Fix: `010d` refuses INSERT, UPDATE, DELETE except by the owner; the operator's `review-queue` command (migrator) still works. **REVOKE `b90e975` (Owner approval)** makes the table SELECT-only for the services.

**R-5: assessed only.** The services legitimately update capability availability, so a REVOKE would break the product. Governance readers (`011p`, `011s`) compare capability kinds with owner-registered declarations, so a change can only cause refusal; `authority_class` matters only through attestations (T-1). Remaining risk: denial of service.

## 6. T-1: fabricated stored measurements (analysis only)

Needs provenance the services' role cannot produce: per-instrument acquisition keys held outside the services' credentials, enrolled and revocable like `011w` authorizer keys; a signed acquisition frame at measurement time (raw-data SHA-256, instrument id and serial, calibration record id and hash, the job/run id bound by the prospective authorization, conditions, operator, monotonic counter or trusted timestamp); deterministic, versioned extraction from signed data (simulations signed by the runner with code and input hashes); signature verification by every deciding reader. Remaining even then: compromised instrument hosts or keys, fabrication before signing, trust in the extractor. Needs Owner decisions on key custody, enrolment, rotation and revocation.

## 7. Readers that changed

- **R8 (projection):** adds `OWNER_QUARANTINED`; rows written through the gate are checked at write time; rows written before `011z`, or raw without the REVOKE, are checked only at read time.
- **R13 (SQL confirmation rule):** leaves quarantined sets out; `cwg_state` still reads raw events (T-4).
- **R15 (raw history display):** marks events the projection does not count.

## 8. Tests whose setup moved (no assertion changed)

- `test_g0_trust_boundaries_postgres`: the R-1/R-3 attacker writes its decision with a plain INSERT (these tests ask what the projection makes of rows the gate never saw); after the REVOKE that writer is the owner, standing for rows written before the revocation.
- `test_belief_events_postgres`, `test_belief_replay_postgres`, `test_belief_authorization_verification_postgres` (4 call sites): snapshots use contract-fixture relations that are not stored rows; now recorded as the owner via `tests/postgres_fixtures.record_decision_before_the_gate`.
- `test_least_privilege_postgres` (REVOKE commit only): UPDATE/DELETE on belief tables now expect InsufficientPrivilege instead of the append-only RaiseException (still refused, one layer earlier).
- `test_sim_fidelity_vertical_postgres`: no change needed.

## 9. Results at `7927618` (implementation agent)

| Check | Result |
|---|---|
| ruff 0.17.4 check / format --check | pass / 591 files formatted |
| mypy | no issues, 282 files |
| `pytest tests/spec` | 245 passed |
| Fresh `lib_g0`, `migrate.py` twice | 88 applied, then up to date |
| Full PostgreSQL suite, fresh `lib_g0`, one complete run | **3653 passed, 4 skipped** |
| Full default suite, one complete run | **2351 passed, 1306 skipped** |
| Repeat full PostgreSQL suite after the mutation battery, fresh `lib_g0` | 3653 passed, 4 skipped |
| `check_requirement_coverage.py` after that run; `update_status.py --check` | exit 0; up to date |

The 4 skips are live model, Lumerical, network and Windows Credential Manager. The first coverage line in `verification_after.log` recorded `tail`'s exit status; it is superseded by the check after the repeat run. An exploratory full run of uncommitted work (12 failures, 47 errors: gate refusing fixture decisions, sim-fidelity independence claim, stale inventory) is not counted as a result.

## 10. Mutation battery

23 `round4_*` entries; each disables one layer and runs only the round-4 test files with `-x`; SQL mutants run on cloned template databases. **23/23 killed** (`round4_mutation_battery.log`). Covered: the 7 gate checks; gate running as caller; gate record admitting any role; missing EXECUTE grant; quarantine owner-only, append-only, declarations view, projection skip, per-policy withholding, refusing the product's own rules; three R15 marks; `010d` owner check and INSERT-only variant; both REVOKEs. Gaps: `load_episode_view` → `_relation` wiring has no direct test; the gate's superseded-policy branch has no dedicated test. This is a targeted run, not a whole-repository mutation run.

## 11. Residual risks

| Id | Risk | Severity |
|---|---|---|
| T-1 | Fabricated but stored measurements (§6) | High (pre-existing) |
| T-2r | Without the REVOKE the services can skip the gate; pre-`011z` rows checked only at read time; a gate-passing non-re-derivable decision blocks its history until quarantined; writer time chosen inside the window; independence check is an upper bound | Medium (Low with the REVOKE) |
| T-3r | A quarantine cannot be reversed; a quarantined set holding a declared id/version blocks re-registration | Low |
| T-4 | SQL confirmation rule reads raw events (including quarantined ones) and unverified grant signatures | Medium |
| R-4r | Without the REVOKE only the trigger guards the table; `review_expire` takes a caller-supplied `p_now` | Low |
| R-5 | `capabilities` writable by the services; only denial of service found | Low |
| T-6 | Owner, migrator, superusers fully trusted; the quarantine adds an owner power | Accepted trust root |
| T-7 | In-memory or wrapped event stores honour no quarantine; an episode view without a belief reader marks nothing | Low |

## 12. Lead implementation agent's independent check (2026-11-20)

- Local head equals `origin` at `fd3ddec`; all 10 commits authored SpadesZ, no AI authorship lines.
- Only new migrations (`010d`, `011z`, `012t`); no existing migration or earlier `docs/audit` evidence modified or deleted; frozen Discovery engine untouched; no `S35-` identifiers in `src/` or `tests/`.
- Before the fix: commit `fb89d36` on a fresh database `lib_r4b`, `tests/e2e/test_g0_boundary_round4_postgres.py` and `tests/unit/test_g0_r15_history_display.py`: **11 xfailed (strict)** — every reproduced attack succeeds.
- After the fix: `fd3ddec` on a fresh database `lib_r4a` (migrated twice), the round-4, round-3 trust-boundary and least-privilege tests: **41 passed**.

## 13. Owner decisions

1. **Approve or reject `6b52521`** (revoke row writes on the four belief tables from the services' role).
2. **Approve or reject `b90e975`** (revoke row writes on `review_queue_policies` from the services' role).
3. Approve the gate design, including the time window instead of overwriting times, and the independence upper bound.
4. Approve the quarantine as the procedure for pre-`011x`/`011y` rows and forged belief rows (owner only, append-only, no reversal), and decide who may be named as deciding actor.
5. If T-1 is pursued: key custody and enrolment for signed instrument provenance.
6. Integration only after the Independent Chief Auditor's review. This report does not replace that review.

Evidence: `docs/audit/g0-boundary-round4-2026-11-11/evidence/` (`reproduction_before.log`, `focused_without_revoke.log`, `verification_after.log`, `round4_mutation_battery.log`).
