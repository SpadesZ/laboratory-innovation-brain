# Review 1 — implementation attacker, first run against `fb7b684` (incomplete)

Condensed as delivered. Resolutions are in `../REPORT.zh-TW.md` §5.

**This run executed no attack.** The run was stopped by an automated safety check while the tester
was still reading the code. That was before it created a database or ran a script. What it
delivered is a source-level reading of `dc4fc12..fb7b684`. Every item below is a lead it did not
demonstrate. Review 4 is the executable re-run.

## Bottom line (source reading)

- For any reader that goes through `trusted_confirmations` or `confirmation_verifier`, no wrong
  cause looks confirmable or counted without the PI's key, as long as the warrant is a REVIEW grant.
- The DOMAIN (`dds:`) path was less clear.

## Suspected, not demonstrated

| # | severity (tester's) | lead |
|---|---|---|
| 1 | MED | The SQL rule counts answers whose signature it cannot verify. A database writer could insert a junk-signed enrolment and a grant under it, and then a CONFIRMED row could pass the SQL trigger. Python readers should still refuse it. |
| 2 | MED/HIGH | `SqlDeclarationSetStore.ensure` refuses only unknown versions of the code's own set ids. A set under a new id would go unnoticed, while SQL reads every active set. `confirmation_verifier` never checks that a `dds:` reference names a declaration the code registers. |
| 3 | note | If the application role owns the tables or is the superuser, it can disable triggers: every SQL guard is advisory to it, and the Python re-checks are the real control. |
| 4 | LOW | Base64 malleability: `b64decode(validate=True)` and the SQL patterns accept non-canonical padding bits, so one key or signature can be stored under several strings. |
| 5 | LOW | The authority-key-as-reviewer-key check is partial. Python compares only with the signing authority's key, so with two pinned authorities one could enrol the other's key. |
| 6 | note | `grant_statement` signs `rationale.strip()`; the impact looks nil. |
| 7 | not checked | The benchmark over-blocking differential, revocation and expiry timing, the flag digest, and Windows file permissions (`os.chmod(0o600)` does little on NTFS). |

## Hygiene

`git status` in `lib-review` was clean. No databases were created.
