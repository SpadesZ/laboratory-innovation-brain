# G0 trust boundaries, round 5: one definition of a counted belief event, and measurement provenance (T-1)

Branch `claude/lib-implementation-agent-47evs0-g0-boundary5`, from `5dc4d59` (round-4 head). Code head
`22a9488`; `56f17c3` adds evidence logs only; this report is added by the lead.

Written by the lead from the implementation engineer's hand-back (the harness does not let subagents
write report files), with the lead's own checks in §9. This is not an audit conclusion.

**G0 stays NOT PASSED.** Nothing is merged or deployed. Round 4's `6b52521` and `b90e975` are
unchanged and still unapproved. One new commit needs Owner approval: `11a396b`. Three new forward
migrations: `005f`, `010e`, `003f`; no existing migration was edited. No `main`, spec, frozen
evidence or PR #1 change; no `S35-` identifiers in `src` or `tests`; all commits authored SpadesZ,
no AI authorship lines.

## 1. Commits

| SHA | What |
|---|---|
| `f1dc7ef` | Reproductions only: Q1–Q7, 8 strict xfail (`evidence/reproduction_before.log`) |
| `dffc1ba` | Fix for Q1–Q7: one SQL definition of a counted event, read by the SQL and Python readers; 512-case enumeration (the message names `012ta`; renamed in the next commit) |
| `d3fedb2` | Migration renamed `012ta` → `005f`; one flag per exclusion kind; enumeration also checked against an independent oracle; test for `012o`'s warrant check; sim-fidelity setup gets a stored Run |
| `aed5c8f` | Reproductions only: T-1 and Q8, 2 strict xfail (`evidence/reproduction_before_t1_q8.log`) |
| `216a12a` | Fix for Q8 (`010e`): a review expiry is judged at the database clock |
| `5f594c8` | T-1 prototype (`003f`, `security/measurement_provenance.py`, `SqlRelationStore`) |
| `11a396b` | **REQUIRES OWNER APPROVAL**: revoke the services' writes on the measurement key tables, and edits on nonces and signatures |
| `0a5c3bc` | Mutation battery: 33 new entries; 8 round-4 entries retargeted to the live definitions; 56/56 killed |
| `22a9488` | Regenerated status spec baseline (91 migrations) |
| `56f17c3` | Evidence: two complete full PostgreSQL runs at `22a9488` by the engineer |

## 2. Quarantined and excluded evidence: SQL versus Python

**Inventory.** The Python projection (`BeliefEpisode.project`) honoured the owner quarantine
(`012t`). These readers read raw events, so quarantined rows still decided: `cwg_state` (SQL
confirmation rule, `012p`); `011l` root-cause check; `012o` warrant-reference check; `012n` EPI-001
competing-set count; the `011z` gate's time bound and policy check; Python's
`HypothesisRevisionGate` (EPI-001); Python's `trace_root_cause`. Two more definitions diverged: the
stored external-snapshot quarantine (`002e`, `external_quarantined_attestations`, documented as
"passed to belief replay" but passed by no reader), and independence counting (the `011z` gate
counted an evidence line differently from `VerificationLoop._independence`).

| Id | Reader | Before the fix | Reproduction | Fix | Test |
|---|---|---|---|---|---|
| Q1 | `cwg_state` | a quarantined forged promotion read SUPPORTED in SQL, ACTIVE in Python | `f1dc7ef` | `dffc1ba` | `test_q1_the_sql_confirmation_rule_reads_the_state_the_projection_reads` |
| Q2 | `011l` root cause | took the quarantined promotion as the cause's state | `f1dc7ef` | `dffc1ba` | `test_q2_a_root_cause_is_not_confirmed_on_a_quarantined_promotion` |
| Q2b | `012o` warrant | accepted a warrant recorded only by a quarantined promotion; found while fixing Q2, **no pre-fix xfail** | none | `dffc1ba` (test `d3fedb2`) | `test_q2_a_warrant_recorded_only_by_a_quarantined_promotion_is_not_cited` |
| Q3 | `011z` time bound | a quarantined event dated 30 days ahead blocked every honest transition | `f1dc7ef` | `dffc1ba` | `test_q3_a_quarantined_future_event_does_not_block_honest_transitions` |
| Q4 | `011z` policy check | recorded transitions under a quarantined policy, which the projection then skipped | `f1dc7ef` | `dffc1ba` | `test_q4_the_gate_refuses_a_transition_under_a_quarantined_policy` |
| Q5 | EPI-001 (SQL and Python) | quarantined straw-man admissions counted as rivals (Python 5 vs projection 2) | `f1dc7ef` | `dffc1ba` | `test_q5_a_quarantined_admission_is_not_a_competing_hypothesis`, `test_q5_the_products_competing_set_reader_leaves_out_quarantined_admissions` |
| Q6 | all belief readers | an event triggered by an attestation from a later-quarantined external snapshot stayed SUPPORTED | `f1dc7ef` | `dffc1ba` | `test_q6_an_event_triggered_by_quarantined_external_evidence_is_skipped` |
| Q7 | `011z` independence | gate counted every current relation and a run-less attestation as one line; a claim of 2 lines over 1 real line passed | `f1dc7ef` | `dffc1ba` | `test_q7_the_gate_counts_independence_as_the_product_counts_it` |
| Q8 | `review_expire` | trusted the caller's `p_now`: a sweep dated a week ahead expired a review two days early | `aed5c8f` | `216a12a` | `test_q8_a_review_is_not_expired_before_its_deadline_by_a_future_clock` |
| Trace | Python `trace_root_cause` | followed the raw latest event; **no pre-fix xfail** | none | `dffc1ba` | `test_the_root_cause_trace_follows_the_promotion_that_counts` |

**One definition (`005f`).** View `belief_event_exclusions` gives each excluded event a reason
(OWNER_QUARANTINED: the event or its policy is quarantined; QUARANTINED_TRIGGER: a triggering
attestation comes from a quarantined external snapshot). `belief_replay(project, target)` is the
structural half of Python's replay: it orders events by `(occurred_at, event_id COLLATE "C")`,
applies the exclusions and cascades PREDECESSOR_MISSING. `belief_counted_state` and
`belief_evidence_lines` build on it. All the SQL readers above read these; Python reads the same view
(`SqlBeliefEventStore.withheld` and `trigger_quarantined` feed the projection; `counted_history`
feeds EPI-001 and the root-cause trace, wired in `research/service.py`). Python also re-derives each
decision, which SQL cannot, so Python can refuse more than SQL counts, never count what SQL excludes.

**Proof of equality.** `test_g0_counted_history_differential_postgres` runs all 2^9 = 512
combinations of 5 event quarantines, 3 policy quarantines and 1 snapshot quarantine; in each, SQL
`belief_replay`, the product projection, `counted_history` and `cwg_state` agree, and all equal an
oracle computed from the toggles alone. `belief_evidence_lines` equals
`VerificationLoop._independence` for every subset of the attestations (counts 0, 1 and 2 reached).

**Setup-only test changes (no assertion changed):** `test_sim_fidelity_vertical_postgres` gives its
simulated attestations their stored Run (they claimed 1 independence line that only the old upper
bound allowed); two `test_causal_warrant_counterexample_postgres` tests run on a synthetic 2045 clock
and make their review overdue by the database clock before expiring it.

## 3. T-1: measurement provenance (High)

**Threat.** The services' role is the only writer of runs, observations and attestations. Reproduced:
the services stored a four-point-probe run, its reading and a SUPPORTS for a pre-registered test, and
the relation reader admitted it. Signing cannot help against a compromised instrument or runner host,
key theft, a lying or mis-set sensor, or a wrong extraction from signed bytes to an observation value.
Owner, migrator and superuser remain the trust root (T-6).

**Prototype (`003f`, `measurement_provenance.py`).**
- Runner key: the runner holds an Ed25519 key (`MeasurementRunner`), digests bytes it produced itself
  and signs only its enrolled capabilities.
- Owner-only, append-only key registry: `measurement_signing_keys`,
  `measurement_signing_key_revocations` (instrument = `runs.backend_id`, capabilities, deciding actor,
  database clock, login role).
- Database-issued nonce: the database chooses value (`gen_random_uuid`) and time; one per job, only
  while QUEUED or RUNNING.
- Signed statement: canonical, domain-separated, versioned JSON over job id, run id, nonce,
  capability, instrument, raw digest and measurement time; relayed into append-only
  `measurement_signatures`.
- Verification (`MeasurementProvenance`): enrolled, in scope, not revoked before arrival, nonce bound
  to the job, digest equal to the run's recorded output artifacts, time between nonce issue and
  arrival + 5 minutes, valid signature. Otherwise UNSIGNED, UNKNOWN_KEY, KEY_REVOKED, OUT_OF_SCOPE,
  NONCE_MISMATCH, DIGEST_MISMATCH, TIME_MISMATCH or BAD_SIGNATURE, and not counted.
- Applied in every `SqlRelationStore` to each SUPPORTS in `admitted_for_subject` and `support_problem`.
- Mode `LAB_BRAIN_MEASUREMENT_PROVENANCE`: `enrolled` (default) enforces per (instrument, capability)
  once a key was ever enrolled for it, other pairs are NOT_REQUIRED and still count; `strict` enforces
  everywhere; any other value is strict.

**Tests.** The T-1 reproduction passes in strict mode. 12 PostgreSQL tests (signed positive control;
unsigned; own key; replay on same bytes and on other bytes; tampered bytes; precomputed signature;
revoked key; out-of-scope key; per-pair enforcement in default mode; services refused enrolment,
revocation, edits and nonce choice; database chooses nonce value and time), 14 unit tests, 1 privilege
test in `11a396b`.

**Designed only:** separate runner process or host with OS key custody (tests keep the key
in-process); an `lab-brain admin` enrolment command; signing or re-deriving the extracted observation
value; SQL readers verifying signatures (needs an extension, or an owner-run verifier writing an
owner-only verified table); signed runners for the existing offline backends, which run inside the
services' process, so signing them now would prove nothing.

## 4. Privilege commits needing Owner approval

- `11a396b` (new): revoke INSERT, UPDATE, DELETE, TRUNCATE on the two key tables and UPDATE, DELETE,
  TRUNCATE on nonces and signatures. The `003f` triggers already refuse these writes.
- `6b52521`, `b90e975` (round 4): unchanged, pending.

## 5. Results

| Check | Result |
|---|---|
| ruff check / format --check | pass (599 files) |
| mypy | no issues, 283 files |
| `pytest tests/spec` | 245 passed |
| fresh database, `migrate.py` twice | 91 applied, then up to date |
| engineer's complete PostgreSQL runs at `22a9488` | run 1 on fresh `lib_r5_final`: 3695 passed, 4 skipped; rerun after a worker restart on the recreated database: 3695 passed, 4 skipped (`evidence/full_postgres_22a9488_run1.log`, `..._run2_rerun.log`) |
| lead's complete PostgreSQL run at `22a9488` | see §9 |
| mutation battery (targeted, not whole-repository) | 56/56 killed: 23 round-4 (8 retargeted) and 33 new |
| default suite (no PostgreSQL) | not run separately; the non-PostgreSQL tests run inside each full run |

The 4 skips are live model, Lumerical, network and Windows Credential Manager. An exploratory full run
on uncommitted work (12 failures: migration name format, stale status file, the sim-fidelity
independence claim, a checksum change mid-run) is not counted; all were fixed before `22a9488`.

Mutation gaps: no mutant for the `COLLATE "C"` ordering (the test database is C.UTF-8, so it would
survive); the NONCE_MISMATCH branch is defence in depth behind the `003f` trigger.

## 6. Residual risks

| Id | Risk | Severity |
|---|---|---|
| T-1r | default mode still counts measurements of any instrument with no enrolled key; no real runner exists; SQL readers (`cwg` rule, `011l`) cannot verify signatures, a new SQL/Python divergence; compromised runner host, key theft, lying sensors and the extraction step remain | High; Medium once runners run in strict mode |
| T-2r | without REVOKE `6b52521` the services can skip the gate | Medium (Low with it) |
| C-1 | ordering of identical timestamps depends on collation; new functions use `COLLATE "C"`; older raw-ordering SQL no longer on the counted path is unchanged | Low |
| Q-r | quarantine is irreversible; a snapshot quarantine (any writer may add one) now demotes beliefs: fail-safe, but a denial-of-service path | Low |
| R-4r, R-5, T-3r, T-6, T-7 | as in round 4; R-4r's caller-time part closed by `010e` | Low / accepted |

## 7. Owner decisions

1. Approve `11a396b`, `6b52521`, `b90e975`. Recommended.
2. Adopt `005f` as the single definition of a counted event, including that a stored snapshot
   quarantine now excludes events (so external-evidence quarantine can demote beliefs). Recommended.
3. T-1: decide key custody (a runner host separate from the services), the enrolment procedure, when
   to move to `strict`, and funding of signed runners plus a verifier for the SQL readers. Recommended:
   keep `enrolled` until a runner exists.
4. Integrate only after ICA review.

## 8. What failed or stayed open

- Q2b and the trace fix had no strict-xfail reproduction committed before the fix.
- The T-1 prototype introduces a new SQL/Python divergence (SQL readers do not verify signatures).
- The status test inventory was not regenerated by the engineer.

## 9. Lead's independent checks

All by the lead, independently of the engineer, on 2026-11-21.

| Check | Result |
|---|---|
| reproductions before the fix | worktree at `f1dc7ef`, fresh database `lib_r5rep` (`migrate.py` twice: 88 applied, then up to date): `tests/e2e/test_g0_boundary_round5_postgres.py` **8 xfailed** (Q1, Q2, Q3, Q4, Q5 x2, Q6, Q7): every attack succeeded before the fix |
| complete PostgreSQL suite at `22a9488` | fresh database `lib_r5full` (`migrate.py` twice: 91 applied, then up to date): **3695 passed, 4 skipped, 0 failed** in 23 min 30 s, one complete run, exit 0 |
| branch hygiene | head `56f17c3` equals origin; 10 commits, all SpadesZ, no Co-Authored-By; migrations only added (none edited); no `S35-` in src or tests; no earlier audit evidence or spec file changed; `22a9488`..`56f17c3` adds evidence logs only |

Not re-checked by the lead: the mutation battery (56/56, engineer's log), and the T-1 and Q8
reproductions at `aed5c8f` (engineer's log `evidence/reproduction_before_t1_q8.log`).
