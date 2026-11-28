# G0 trust boundaries, round 6: consequential readers apply the same trust rules, measurement provenance in SQL

Branch `claude/lib-implementation-agent-47evs0-g0-boundary6`, from `6415000` (round-5 head). Final
code commit `0489b23`; later commits add evidence, the status inventory and this report only.

Written by the round-6 engineer. Engineering evidence only; this is not an audit conclusion.

**G0 stays NOT PASSED.** Nothing is merged or deployed. No `main`, `ACTIVE_SPEC.yaml`,
`docs/spec/sai33|34|35`, frozen-evidence or `benchmarks/` change; no sealed material was read.
Four new forward migrations (`003g`, `002f`, `005g`, `005h`); they replace or rename functions and a
view that `005f`/`012p` defined, and no earlier migration file is edited. No grant or revoke was added. All commits
authored SpadesZ, with no AI attribution lines (`check_commit_messages.py` passed on each).

**Owner decisions recorded (2026-11-24).** The REVOKE commits `11a396b`, `6b52521` and `b90e975` are
APPROVED by the Owner; they were already on this branch and are unchanged; nothing was applied to
any deployment. `005f` is ADOPTED as the single definition of a counted belief event, including
that a stored snapshot quarantine excludes events; round 6 extends that definition (`005g`) rather
than adding a second one. T-1 key custody and the move to `strict` are NOT decided: the default
mode stays `enrolled` (now read from the database: no mode row means `enrolled`, see §3.1).

## 1. Commits

| SHA | What |
|---|---|
| `fa90ca7` | Reproductions only: T-1r (4 SQL readers count a support Python refuses; strict mode invisible to SQL) and Q-r (services quarantine a snapshot), 6 strict xfail (`evidence/reproduction_before.log`) |
| `81636fc` | Fix T-1r (`003g`, Python mode/verdict, owner commands, enumeration test) and Q-r (`002f`) |
| `b184ba6` | Reproductions only: Q-x, 2 strict xfail (`evidence/reproduction_before_qx.log`) |
| `25e6a78` | Fix Q-x (`005g`, `SqlRelationStore`) |
| `fed721f` | Reproductions only: E-1 (2) and T-1s (1, stays open), strict xfail (`evidence/reproduction_before_e1_t1s.log`) |
| `983b42a` | Fix E-1 (episode page) |
| `d962c5b` | Fix C-1 (`005h`) and its tests |
| `0c8eead` | Tests: database mode decides / setting may only agree; round-5 trace wiring |
| `a3e9fcf` | Status inventory spec baseline: 95 migrations |
| `9d0da03` | Mutation battery: 25 round-6 entries; 6 round-5 entries and 1 T-1 entry retargeted to the live definitions |
| `48d0957` | Evidence: battery SQL half at `9d0da03` (50/50 killed) |
| `bfe4ccf` | Test: the owner's verifier records the failure it finds; 3 T-1 entries also run it; battery Python pass 1 (28/31) |
| `4091647` | Evidence: battery pass 2 (the 3 survivors re-run, 3/3 killed) |
| `0489b23` | **Final code commit.** `003g`'s verdict column renamed `status` -> `verdict` (the first full run failed on it, see §4); log of that run kept |
| `161d827` | Evidence: the 9 battery entries on `003g` re-run after the rename (9/9 killed) |
| `17454ba` | Evidence: complete PostgreSQL run at `0489b23`; status inventory regenerated |
| (this) | This report |

## 2. Inventory of consequential readers

Rules: **Q** = quarantine exclusion (`005f` owner/policy/trigger quarantine; `005g` quarantined
evidence behind a counted relation); **M** = measurement provenance (the T-1 verified rule; `003g`
in SQL); **A** = actor authority (who may write what the reader trusts). "SQL=Py" means the SQL and
Python sides apply the same rule. All tests named are in `tests/e2e/` unless stated.

### SQL readers

| Reader | Decision it drives | Rules before round 6 | After round 6 | Test that proves it |
|---|---|---|---|---|
| `belief_event_exclusions` (view) | which stored events count, for every SQL and Python belief reader | Q (owner, policy, triggering snapshot attestation) | Q + an event whose decision counted a relation on quarantined evidence (`005g`) | `test_qx_a_promotion_that_counted_it_no_longer_counts`; `test_g0_counted_history_differential_postgres` (512 cases, unchanged, passes) |
| `belief_replay` / `belief_counted_state` / `cwg_state` | the belief state the SQL confirmation rule, `011l`, `012o`, `012n` read | Q; no M (SQL counted a promotion Python refused) | Q + M: a history in which a counted event's decision counted a SUPPORTS that does not count is refused whole (`HISTORY_REFUSED`), as `verified_history` refuses it (`003g`) | `test_t1r_the_sql_state_is_not_supported_on_a_measurement_python_refuses` |
| `cwg_evidence` | the confirmation rule's warranted support and refutations, the cited warrant check, member keys | current SUPPORTS/CONTRADICTS, warrant; no M, no Q on relations | + M on SUPPORTS (`003g`), + Q on any relation (`005g`) | `test_t1r_the_sql_confirmation_rule_does_not_count_a_support_python_refuses`; `test_g0_measurement_provenance_differential_postgres`; `test_qx_a_relation_on_a_quarantined_snapshot_is_support_nowhere` |
| `confirmation_rule_breaches`: observed outcomes, rival affirmations | evidence AGAINST a confirmation | raw relations and attestations, in SQL and in Python (`relations_from`, `episode_outcomes`) alike | unchanged: reading more can only refuse more, and both sides read the same rows | existing V1.1 suites |
| `cwg_bound_class`, own declaration in `confirmation_rule_breaches`, class name in `failure_analyses_confirmation_holds_the_rule` | which declared class binds a hypothesis; which refutations apply; the recorded class name | tie-break by database collation | byte-wise (`005h`, C-1) | `test_c1_the_confirmation_path_breaks_ties_bytewise` (x3), `test_c1_the_collation_hazard_is_real` |
| `cwg_counted_grant` (reviewer answers) | DOMAIN/REVIEW warrant of a relation | A: reviewer signature verified in Python only (confirmation re-check withholds reuse) | unchanged -- T-1s class, open | none new (see §6, T-1s) |
| `failure_analyses_trace_to_execution` (`011l`) | a CONFIRMED root cause | Q via `belief_replay` | + M via `belief_replay` | `test_t1r_a_root_cause_is_not_confirmed_on_a_support_python_refuses` |
| `failure_analyses_confirmation_is_warranted` (`012o`) | the warrant refs a CONFIRMED analysis may cite | Q via `belief_replay` | + M via `belief_replay` | round-5 `test_q2_a_warrant_recorded_only_by_a_quarantined_promotion_is_not_cited` (now also reverted-fix evidence, §5) |
| `hypothesis_revisions_meet_m3_preconditions` (`012n`, EPI-001) | competing-set count before SUPPORTED | Q via `belief_replay` | + M via `belief_replay` (a refused history's admission is not a rival: fail-closed, and Python's `counted_history` reads the same rows) | round-5 Q5 tests |
| `011z` gate: `belief_write_time_problem`, `belief_policy_problem` | whether an event may be written | Q | unchanged | round-5 Q3, Q4 |
| `011z` gate: `belief_snapshot_problem` | whether a decision snapshot may be written | stored/current relations, matches, classes, conflicts, independence (`005f`) | + M (`003g`), + Q on counted relations (`005g`); the `005f` body is kept, renamed, and called first | `test_t1r_the_write_gate_refuses_a_snapshot_counting_a_support_python_refuses`, `test_qx_a_promotion_that_counted_it_no_longer_counts` |
| `belief_evidence_lines` | the gate's independence bound | runs behind the snapshot's admitted relations | unchanged: called only after the snapshot check has refused any relation that does not count | round-5 Q7 |
| `diagnostic_warrant_review_enqueue` / `review_items_warrant_subject_is_a_gated_relation` (`012o`) | opening a warrant review (reviewer attention) | any current SUPPORTS/CONTRADICTS | unchanged: a grant on a relation that does not count still counts nothing (`cwg_evidence` filters it); cost is reviewer attention only | -- (left, Low) |
| `authority_conflict_escalate`, `review_expire`, `extraction_review_enqueue` | review pricing and expiry | one active queue policy per project (unique index, no ties); `010e` clock | unchanged | existing |
| `external_quarantine_blocks_citation` (`002e`) | a new relation, bundle or event citing quarantined evidence | Q at write time | unchanged | existing `002e` suite |
| `prospective_*` (`011s`, `011w` frame) | a SUPPORTS of a post-screening hypothesis at write time | the frame; the signature is Python-only | unchanged -- T-1s, open | `test_t1s_...` (strict xfail, open) |
| `provenance_scope_violations` (view) | a report, no decision | -- | unchanged | -- |

### Python readers

| Reader | Decision it drives | Before | After | Test |
|---|---|---|---|---|
| `SqlRelationStore.admitted_for_subject` | every decision's input relations (transition attempts, the loop's rule, the confirmation re-check, independence) | M (`003f`, mode from the services' environment), 011w verifier | M with the Owner's database mode and the owner's verdict (`003g`); Q on relations (`005g`); byte-wise tie-break | differential, T2, Q-x, `test_t1r_the_database_mode_decides_and_the_setting_may_only_agree` |
| `SqlRelationStore.support_problem` (stored decisions) | refusing a history (SUPPORT_UNVERIFIED) | M, 011s/011w | M as above (unchanged otherwise; Q is handled as an event exclusion, not a refusal) | T1 |
| `BeliefEpisode.project` | the product's belief state | Q via `withheld`/`trigger_quarantined` | Q now includes `005g` (same view) | Q-x, round-5 Q6 |
| `SqlBeliefEventStore.counted_history` → EPI-001 gate, root-cause trace | competing set; which promotion the trace follows | Q via `belief_replay` | + M via `belief_replay`; the service's wiring now held by a test | `test_r5_gap_the_products_root_cause_trace_reads_the_counted_history`; round-5 trace test |
| `research.confirmation` re-check | whether a CONFIRMED conclusion is reused | Python projection + rule + reviewer signatures | through the readers above | existing |
| `research.episode_view._not_counted` (the episode page) | what the page claims counts as support | 011w only | + M + Q, through the same relation store (E-1) | `test_e1_the_episode_page_does_not_show_a_refused_measurement_as_counted`, `..._quarantined_evidence_as_counted` |
| `evaluation.collect.support_provenance` | facts the benchmark scorer reads (not a product decision) | 011s/011w facts | unchanged: does not report M or Q; changing it changes the scorer's input contract | -- (left, Low) |
| `review_cli._packet`, web `_question_of` | what a reviewer is shown | raw relation | unchanged: display, no claim that it counts | -- |

### Actor authority over what the readers trust

| Table / rule | Writer before | Writer after |
|---|---|---|
| `owner_quarantines` (`012t`), transition policies (`011x`), declaration sets (`011y`), review-queue policies (`010d`), measurement keys (`003f`) | schema owner | unchanged |
| `external_snapshot_quarantine` (`002e`) | any writer | schema owner, with the deciding person and a reason (`002f`, Q-r) |
| measurement-provenance mode | the services' own environment variable | schema owner, append-only table (`003g`); the variable may only agree |
| measurement verifier verdicts | (none) | schema owner, append-only (`003g`) |
| belief decisions and events | the services' role, through the `011z` gate, or directly while `6b52521` is not applied in a deployment | unchanged (T-2r) |

## 3. Objectives

### 3.1 T-1r: SQL/Python divergence on measurement provenance (High)

**Threat.** Python (`SqlRelationStore` + `MeasurementProvenance`) refused an unsigned or unverified
SUPPORTS for an enrolled (instrument, capability); every SQL reader of the same evidence counted it,
and the strict mode was an environment variable of the services' own process.

**Reproduction (`fa90ca7`, 5 strict xfail, each failed for the intended reason before the fix):**
after the owner enrols a key for the pair of a stored, unsigned measurement that already promoted a
hypothesis: the projection refuses the history (SUPPORT_UNVERIFIED) while `cwg_state` read SUPPORTED
(T1); `cwg_evidence` listed the SUPPORTS Python did not admit (T2); the `011z` snapshot check
accepted the decision counting it (T3); `011l` accepted the cause as SUPPORTED and the analysis was
refused only later by `012o` for want of a warrant (T4); no owner setting of the mode existed (T5).

**Fix (`003g`, `81636fc`).**
- `measurement_provenance_modes`: the Owner's mode, schema owner only, append-only, database clock
  and login role stamped; `measurement_provenance_mode()` is the latest row, `enrolled` if none.
  Python reads it (`effective_strict`); `LAB_BRAIN_MEASUREMENT_PROVENANCE` may only state the same
  mode, otherwise `ProvenanceModeMismatch` (a reader is never built on a weaker mode). The services
  cannot write the table (trigger; tested).
- `measurement_verifications`: the owner-run verifier's verdict per relayed signature (owner only,
  append-only, one per run, the judged key id and signature copied by the guard). Owner commands:
  `lab-brain admin verify-measurements --actor`, `lab-brain admin measurement-mode MODE --reason --actor`
  (`verify_pending`, `verify_run`, `set_mode`).
- `measurement_run_status(run)`: NOT_REQUIRED / UNSIGNED by the same mode and enrolment rule as
  Python; for a signed run NONCE_MISMATCH, UNKNOWN_KEY, KEY_REVOKED (before arrival), OUT_OF_SCOPE
  re-checked structurally, then PENDING_VERIFICATION until a verdict exists, then the verdict.
  `measurement_support_problem(project, attestations)` names the first that does not count.
- Python `MeasurementProvenance.run` requires, besides its own verification, the database's VERIFIED
  (new status PENDING_VERIFICATION); the verifier uses `own_only=True`.
- Readers: `cwg_evidence` leaves the SUPPORTS out; `belief_replay` refuses a history in which a
  counted, not owner-quarantined event's decision counted such a SUPPORTS (every event
  `HISTORY_REFUSED`), mirroring `verified_history`, so `cwg_state`, `011l`, `012o`, `012n` and
  Python's `counted_history` follow; `belief_snapshot_problem` is the `005f` check (renamed
  `belief_snapshot_problem_005f`, body unchanged) followed by the measurement check.

**Tests.** The 5 T-1r reproductions pass. `test_g0_measurement_provenance_differential_postgres`
enumerates enrolled x signature {none, valid, invalid, revoked-before-arrival} x verdict {absent,
present} x mode {enrolled, strict} (24 reachable cases; revoked requires enrolment, a verdict
requires a signature) and asserts SQL status-counts == Python `.counts` == relation admitted by
Python == relation listed by `cwg_evidence` == an independent oracle; both outcomes reached in both
modes. Also: services cannot write verdicts or modes or edit them; the database mode decides and
the setting may only agree; the verifier records the failure it finds (3 cases); and a residual test
(below).

**Setup-only changes to existing tests (no assertion changed):** the T-1 strict-mode tests now
record the owner's strict mode as well as setting the variable (`_strict`), and `_status` runs the
owner's verifier before reading a status; `_measure` takes an optional `instrument`.

**What remains (stated).** (a) The owner is the trust root: a VERIFIED verdict the owner writes by
hand for a bad signature is counted by SQL and refused by Python (Python refuses more, never counts
more; asserted by `test_t1r_residual_a_verdict_the_owner_writes_by_hand_is_counted_by_sql_only`).
(b) No real runner exists; the tests hold the runner key in-process. (c) Signing cannot show a
compromised runner host, a stolen key, a lying or mis-set sensor, or that the observation value
extracted from the signed bytes is faithful. (d) Default mode `enrolled` still counts measurements of
any pair with no enrolled key (NOT_REQUIRED), by Owner decision. (e) A signed measurement now counts
only after the owner runs the verifier: an operational step the Owner must schedule.

### 3.2 Q-r: snapshot-quarantine denial of service (Low)

**Reproduction (`fa90ca7`).** The services' role inserted an external-snapshot quarantine; with
`005f` that demoted a SUPPORTED belief triggered by the snapshot's attestation.
**Fix (`002f`).** A new quarantine requires schema-owner membership (the `012t` test) and records
`decided_by_actor_id` and a reason (>= 10 chars); the database stamps time and login role. Rows
already present are kept. Still append-only and irreversible; the fail-safe direction (a quarantined
snapshot counts nowhere) is unchanged. `SqlExternalSourceStore.quarantine` takes `actor_id`, `reason`.
**Tests.** `test_qr_the_services_cannot_demote_a_belief_by_quarantining_a_snapshot`,
`test_qr_an_owners_quarantine_records_who_and_why_and_stays`; round-5 Q6 still passes with the
owner's quarantine. Setup-only: the round-5 helper, the `002e` integration test and the 005f
differential test now name the deciding person and a reason. **Remains:** no CLI kind for snapshot
quarantine (owner uses the store or SQL); reviewer authority other than the owner is not modelled.

### 3.3 Gaps found by the widened inventory

- **Q-x (Medium).** A relation that cited an external attestation before its snapshot was
  quarantined stayed admitted by Python and SQL, and a promotion that counted it still counted.
  Reproduced (`b184ba6`). Fix (`005g`), routed through `005f`: the exclusion view's
  QUARANTINED_TRIGGER now also covers an event whose decision counted a relation resting on
  quarantined evidence (Python reads the same view); `quarantined_evidence_problem` is read by
  `cwg_evidence`, the `011z` snapshot check and `SqlRelationStore.admitted_for_subject`. Tests: the
  two Q-x tests; the 512-case `005f` differential still passes.
- **E-1 (Low).** The episode page marked as counted a SUPPORTS every decision refuses (measurement
  provenance, quarantined evidence). Reproduced (`fed721f`); fixed by reading the same relation store
  (`983b42a`). Tests: two E-1 tests; the existing 011w page tests still pass.
- **T-1s (Medium, OPEN).** SQL cannot verify Ed25519 signatures on verification authorizations
  (`011w`) or reviewer answers (`012p` grants); `cwg_evidence` counts a SUPPORTS on a forged
  authorization that Python refuses. Reproduced and left as a strict xfail
  (`test_t1s_the_sql_confirmation_rule_does_not_count_support_on_a_forged_authorization`). Not
  fixed: the `003g` pattern (owner-run verifier, verdict table read by both sides) would make every
  post-screening support wait for an owner step, which changes the product flow -- an Owner decision.
  Python's re-check still withholds such a conclusion from reuse.

### 3.4 C-1: collation-dependent ordering (Low)

Audit of every `ORDER BY` without `COLLATE` in the live (last-defined) SQL functions and views. Fixed (`005h`), because a single row is picked and decides
something: `cwg_bound_class` (binding class), the candidate's own declaration in
`confirmation_rule_breaches`, the class name in `failure_analyses_confirmation_holds_the_rule`.
Python: `admitted_for_subject` tie-break `relation_id COLLATE "C"` (snapshot hash determinism).
Left, with reason: orderings that only choose which problem a message names (`prospective_*`,
`screening_basis_problem`, `string_agg`/`array_agg` for messages, `belief_snapshot_problem`'s
authority-class comparison, which sorts both sides alike); review-queue policy picks (a unique
index allows one active policy per project, so no ties); LLM spend picks (`llm_spend_reserve`
`price_id DESC`; not on the counted path); Python history reads (Python re-sorts by
`(occurred_at, event_id)` before deciding). Tests: the hazard is real (C and `en-US-x-icu`
disagree on `'B-set' < 'a-set'`), and each live definition carries the byte-wise tie-break. No
behavioural run on a non-C database was made: the suite's databases are C.UTF-8.

### 3.5 Round-5 gaps

Q2b and the trace fix had no pre-fix reproduction. Evidence now: battery entry
`round6_r5gap_q2b_warrant_fix_reverted` reverts `005f`'s `012o` fix and runs only Q2b's test --
killed; `round6_r5gap_trace_history_fix_reverted` reverts `counted_history` and runs only the trace
test -- killed; `round6_r5gap_trace_wired_to_raw_history` hands the service's trace the raw history
-- killed by the new wiring test (nothing held that wiring before).

### 3.6 Mutation battery (targeted, not whole-repository)

81 entries: 23 round-4, 33 round-5/T-1, 25 round-6; 6 round-5 entries retargeted to `005g`/`003g`
(where the view and `belief_replay` now live) and 1 T-1 entry to the new anchor. SQL half 50/50
killed (`evidence/round6_mutation_battery_sql.log`). Python half first pass 28/31: three T-1
Python checks (unknown key, revocation, scope) survived because `003g`'s SQL status re-checks the
same facts, so the Python check no longer changed what counts -- it still decides the verdict the
owner's verifier records, which no test asserted. A test was added and the three entries re-run:
3/3 killed (`..._py_pass1.log`, `..._py_pass2.log`). After the verdict-column rename (`0489b23`)
the 9 entries mutating `003g` were re-run: 9/9 killed (`..._003g_rerun.log`). Result: 81/81 killed,
of which 78 on the first pass and 3 after a test was added; the other 72 entries were not re-run
after `0489b23` (the rename touches only `003g`, `verify_run` and one test's insert). Gaps: no mutant for the SQL
structural re-checks (revocation, scope, nonce) in `measurement_run_status`, which are defence in
depth behind the Python verifier's verdict and immutable rows.


## 4. Results

| Check | Result |
|---|---|
| `ruff check src tests scripts` / `ruff format --check src tests scripts` | pass (601 files) at `0489b23` |
| `mypy` | no issues, 283 source files |
| `pytest tests/spec` | 245 passed |
| fresh database, `migrate.py` twice | `g6_final`: 95 applied, then "migrations up to date" (recorded in the full-run log header) |
| **complete PostgreSQL suite at `0489b23`** | fresh `g6_final`, `PYTHONPATH=/home/user/wt/g0b6/src`: **3718 passed, 4 skipped, 1 xfailed, 0 failed**, 3895 s (64 min 55 s; the machine was shared), exit 0 -- `evidence/full_postgres_0489b23.log`. One run, not combined from parts |
| earlier complete run at `bfe4ccf` (not counted) | 1 failed, 3717 passed, 4 skipped, 1 xfailed (25 min 27 s): `test_cognition_cannot_write_a_projection_because_there_is_nothing_to_write_to` refused the new bare `status` column of `measurement_verifications`; fixed in `0489b23` by renaming it -- `evidence/full_postgres_bfe4ccf_run1_failed.log` |
| `update_status.py`, then `--check` | regenerated after the run at `0489b23`; `--check`: up to date (3723 collected = 3718 + 4 + 1) |
| mutation battery (targeted, NOT whole-repository) | 81/81 killed (78 first pass, 3 after an added test); see §3.6 |
| reproductions before each fix | T-1r 5 + Q-r 1 (`fa90ca7`), Q-x 2 (`b184ba6`), E-1 2 + T-1s 1 (`fed721f`): every one failed for the stated reason (`--runxfail` output in the three `reproduction_before*.log`) |

The 4 skips are live model, Lumerical, network and Windows Credential Manager. The 1 xfail is T-1s,
open by design (§3.3).

**Subprocess imports (coordinator's note).** The shared `.venv` has an editable install pointing at
the main checkout. The final run used `PYTHONPATH=/home/user/wt/g0b6/src`. The first full run
(`bfe4ccf`), the targeted runs and the battery runs before `161d827` did not set it; in those, the
only subprocesses the affected tests launch are `scripts/migrate.py` (which puts its own tree's
`src` first on `sys.path`) and the battery's own `pytest` (whose `pythonpath = src` is this tree),
so they imported this tree. The `003g` re-run (`161d827`) set `PYTHONPATH`.

## 5. Residual risks

| Id | Risk | Severity |
|---|---|---|
| T-1r | Closed as a SQL/Python divergence. Remaining: default mode `enrolled` counts pairs with no enrolled key; no real runner or OS key custody; compromised runner host, key theft, lying sensors and the extraction step; the owner can hand-write a VERIFIED verdict that SQL counts and Python refuses; a signed measurement counts only after the owner runs the verifier | High until runners and strict mode exist; Medium after |
| T-1s | SQL cannot verify Ed25519 on verification authorizations (`011w`) or reviewer answers (`012p`); the SQL confirmation rule counts support on a forged authorization that Python refuses (strict xfail) | Medium |
| T-2r | the services can write belief rows directly until the approved REVOKE `6b52521` is applied in a deployment | Medium (Low once applied) |
| Q-r | Closed: only the schema owner, with a recorded decision, adds a snapshot quarantine; quarantine stays irreversible | Low (residual: owner error) |
| Q-x | Closed (`005g`) | -- |
| E-1 | Closed for the episode page; `evaluation.collect` (scorer facts) does not report measurement provenance or quarantine | Low |
| C-1 | Live single-row picks fixed; message-only orderings and LLM spend picks left; no behavioural test on a non-C database | Low |
| R-review | warrant reviews can be opened on relations that do not count (reviewer attention only) | Low |
| R-4r, R-5, T-3r, T-6, T-7 | as in round 5 | Low / accepted |

## 6. Owner decisions needed

1. **T-1s**: whether to extend the `003g` pattern (owner-run verifier, verdict tables read by SQL and
   Python) to verification authorizations and reviewer answers. It closes the divergence but puts an
   owner step before every post-screening support and every reviewer answer counts.
2. **T-1** (unchanged): key custody (a runner host separate from the services), the enrolment
   procedure, when to record `strict` (`lab-brain admin measurement-mode strict`), and who runs and
   schedules `lab-brain admin verify-measurements`.
3. Apply the approved REVOKEs (`11a396b`, `6b52521`, `b90e975`) when a deployment exists; round 6
   adds no privilege change (`002f`/`003g` guards refuse non-owners whatever the grants), but the
   new owner-only tables (`measurement_provenance_modes`, `measurement_verifications`) could be added
   to the same revocation later -- not done here, as it would be a new privilege change.
4. Integrate only after ICA review.

## 7. What failed or stayed open

- The first complete run at `bfe4ccf` failed one test (bare `status` column); fixed in `0489b23` and
  the suite re-run completely on a fresh database.
- Battery first pass: 3 T-1 Python-check entries survived (redundant with `003g`'s SQL re-checks for
  counting); a test of the recorded verdicts was added, then 3/3 killed.
- T-1s reproduced and left open (strict xfail).
- No CLI kind for snapshot quarantine; no behavioural C-1 run on a non-C database; no mutants for
  `003g`'s SQL structural re-checks (revocation, scope, nonce), which are defence in depth.
- A report file could be written in this session; this report was written by the engineer, not the
  lead, and nothing in it was independently re-checked.

## Lead's independent checks (2026-11-28)

By the lead, separately from the engineer, with `PYTHONPATH` set to the tree under test:

| Check | Result |
|---|---|
| reproductions at `fa90ca7` (before any fix), fresh database `lib_g6rep`, 91 migrations then up to date | 6 xfailed (T-1r ×5, Q-r ×1): every reproduced gap present before the fix |
| round-5/6 G0 tests, provenance differential, counted-history differential, snapshot quarantine and `tests/spec` at `2e31ced`, fresh database `lib_g6head`, 95 migrations then up to date | 297 passed, 1 xfailed (T-1s, open by design), 5 min 54 s |
| commits after the final code commit `0489b23` | evidence, status inventory and report only |

Not re-checked by the lead: the complete PostgreSQL run (the engineer's log at `0489b23` is the record) and the mutation battery.
