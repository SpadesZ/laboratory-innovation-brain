# Review 3 — design critic on `661d8a0` (read-only)

Condensed as delivered. Resolutions are in the last column and in `../REPORT.zh-TW.md` §7.

The reviewer read the design record, all of `012p` and the diffs of the identity, resolver, loop,
repository, verifier, CLI, web and service code. It compared the SQL rule with `standing`/`resolve`
clause by clause and ran the two unit suites (62 passed). It did not run the PostgreSQL suites.

## What holds (reviewer)

- **Forged answers no longer count.**
  - The unsigned V1 resolve is dropped, and every new grant carries an enrolment and a
    signature-shaped value.
  - The SQL frame checks that the enrolment is that person's, is unrevoked, and that the answer
    is dated after both the enrolment and the question.
  - Base64 is canonical; the regexes were checked.
  - The statement covers every field, under a domain-separation tag.
- **The trust anchor is outside the database.** An authority never enrols itself, and an
  authority key is never a reviewer key. There is no default authenticator. With no authority, no
  REVIEW warrant counts; a malformed file raises.
- **The SQL rule mirrors `standing` closely for the code's declarations.** `CheckedLoop` holds the
  two together, and a refusal makes the loop record OPEN.
- **Readers of CONFIRMED rows.** Besides the page, only `similar_failures` and the miner read them,
  and both go through `trusted_confirmations`.
- **The `fan:30d9407f` flag** is exact, idempotent, append-only, displayed and excluded.
- **Protected areas are untouched**, and no test was weakened.

## Defects and resolutions

| # | sev. | finding (reviewer) | resolution |
|---|---|---|---|
| HIGH-1 | HIGH | Reuse did not re-derive the rule. A row written past the triggers (`session_replication_role`), or a forged SUPPORTED event plus a CONFIRMED row on a DOMAIN-warranted relation, was trusted; so was a `dwg:` reference naming no grant. Report a least-privilege role as a blocker. | **Fixed.** `research/confirmation.py` re-runs the loop's `ConfirmationRule` over the verified projection (every decision re-derived, every warrant re-checked) and requires `confirmable == cause` and cited warrants ⊆ those the verified record gives. Tests: `test_reuse_*`. A least-privilege database role is recorded as an architecture blocker (§9, §10). |
| MED-1 | MED | `review revoke` hard-coded `effective_at = now()` | **Fixed.** `--effective-at` (refused in the future); it lists the answers it withdraws. |
| MED-2 | MED | A revocation dated before an answer that already moved a belief, a rotated authority, or a V1 grant crashed continuation (`UnverifiedBeliefRevision`). The doc's test did not cover it. No rotation path. | **Fixed.** The loop records an OPEN analysis with the reason instead of failing. Tests: `test_revoking_a_key_after_its_answer_moved_a_belief…`, `test_reuse_refuses_a_history_that_no_longer_reverifies`. Rotation: `until=` on an authority line (enrolments before it still verify). |
| MED-3 | MED | Private keys must enter the `web` container, because the database is not published and signing and submitting are one command. The passphrase is environment-only; file modes mean nothing on NTFS. | **Owner decision / documented** (split offline signing from submitting). |
| MED-4 | MED | The run-start sweep expired every review type, so an expired authority-conflict review stops blocking. The bootstrap policy was declared in the researcher's name by default. | **Fixed.** The run-start sweep expires DIAGNOSTIC_WARRANT reviews only (tested). The bootstrap declares a queue only when `LAB_BRAIN_REVIEW_QUEUE_DECLARED_BY` names the declarer. |
| MED-5 | MED | The registry was not closed: a stranger set on other observables could collide class ids, and the SQL-active version could drift from the code's. | **Fixed.** `ensure` refuses any registered version the code does not declare, and any difference between SQL's active versions and the code's (tested). |
| MED-6 | MED | Flags are unauthenticated and permanent; `recorded_by` is self-asserted. | **Partly.** A person must be an active member of the project (SQL). Signed flags and retraction are an owner decision. |
| MED-7 | MED | Runner ≠ reviewer compares self-asserted labels (the workspace runs everything as one actor); one person can hold two labels. | **Documented** as a residual and owner decision (runner authentication); §2.4 re-scoped. |
| LOW-1 | LOW | The authorities file is read per use, not refused at start. | **Fixed.** Checked once before the command connects (exit 2; tested). |
| LOW-2 | LOW | SQL orders member ids by collation, Python by code point. | **Fixed** (`COLLATE "C"`). |
| LOW-3 | LOW | The flag digest depends on the session time zone. | **Fixed** (`SET timezone TO 'UTC'`); the column-set dependence is documented. |
| LOW-4 | LOW | `cwg_counted_grant` uses `LIMIT 1` without ORDER BY. | **Fixed** (a refusal first, then by id). |
| LOW-5 | LOW | The audit package was missing. | **Fixed** (this folder). |
| LOW-6 | LOW | SQL takes members from `hypotheses`, the loop from the debate's certificates. | **Documented**; the differential check covers every scenario run. |

## Residual risks (reviewer, accepted in the report)

- **The trust root:** the host operator who controls the authorities file, `.env` and the image;
  the holders of authority keys; and a reviewer misusing their own key.
- **Absence facts live in the database.** Revocations, refusals and flags can be deleted by a
  superuser; signatures prove presence, not absence.
- **SQL trusts recorded evidence**, so fabricated observations and runs pass it.
- **Requirements that limit discovery:**
  - no authority by default;
  - at least two people;
  - conclusions are withheld from reuse when any answer in the set fails to verify.

## Verdict (reviewer)

CONDITIONAL. The direction is acceptable as a fail-closed P0 hardening; not ready for sign-off until
HIGH-1, MED-1, MED-2, MED-4, MED-5 and the doc fixes are made. MED-3, MED-6 and MED-7 may go to the
owner as decisions, provided the documentation is corrected.
