# Review 8 — attack suite re-run against `ed0670b` (same tester as reviews 4 and 6)

The tester used its own disposable database, with scratch scripts outside the repository. The
implementer's gate tests passed (83), and `git status` stayed clean. Report as delivered,
condensed; resolutions in `../REPORT.zh-TW.md` §5.

**Bottom line:** no wrong cause could be CONFIRMED without impersonating the PI, which is the
documented owner decision (A2).

**Benchmark (plain fixture):**
- least_cost is 10/10, every stop and cause as expected;
- simulate_first differs only on outage-contact (AWAITING_RESOURCE), the baseline's intended
  escalation, unchanged since `bc55458`.

## Fixed (demonstrated, with the refusal output)

| finding | result on `ed0670b` |
|---|---|
| N1 forged relation citing another episode's attestation | `relation rel:forged cites att:…, which does not record COMPENSATED of sp.carrier_profile for observation … in the episode` |
| A5 changing the runner on a current relation | `relation …'s actor changes only with its invalidation` |
| A3 new transition under superseded 1.0.0 | refused in Python through the policy store even with `superseded=` empty; with a store hiding `superseded_by`, SQL refuses: `event … cites policy:sp-vs001-promote@1.0.0, which policy:sp-vs001-promote@2.0.0 supersedes` |
| A3 bogus `dds:` ref on a CONFIRMED analysis | `…cites warrant dds:no-such-set@9#nothing, which no decision promoting … recorded for its support` |
| N3 invalidating a rival's shared affirmation | still HUMAN_ACTION_REQUIRED, with the "affirms the observation" note kept |
| earlier findings 1, 2, 3, 5, 6, 7, 8, 9 | still hold |
| A2 plain impersonation (APPROVED only) | no longer confirms the proxy: its DISAGREES is another declared class's signature, and approving a link does not make the hypothesis that class |

## Still exploitable (demonstrated)

1. **MED — the N2 fix works only if the expiry sweep runs.**
   - With the sweep, a new review is queued, and answering it confirms the true cause.
   - Without it, the overdue review stays QUEUED; a late answer is refused as expired, and the
     episode waits indefinitely.
   - Nothing in `src` calls `ReviewExpiryProcessor` or `sweep_projects`.
2. **LOW-MED (new) — a relation with no attestations passes the insert trigger.**
   - The trigger loops over `supporting_attestation_ids`, so an empty list checks nothing.
   - An empty-attestation CONTRADICTS on the confirmed contact hypothesis was accepted and
     DOMAIN-warranted, which dropped `confirmable` to None.
   - Impact is blocking only: a forged SUPPORTS fails the policy's authority check.
3. **LOW — the database accepts a forged CONFIRMED row for a cause the loop refused to confirm.**
   - Setup: two faults and no review queue. The loop ended HUMAN_ACTION_REQUIRED.
   - A direct CONFIRMED failure analysis citing the real `dds:` ref was accepted and became a
     precedent.
   - The ref check proves the ref was used for the promotion, not that the confirmation rule held.
4. **By design (A2) — impersonation plus `--is-class` confirms the proxy.**
   - `diagnostic_warrant_resolve(…, 'act:pi', …, 'dds:…#normalization_error')` from any
     connection, then resume, gives CONFIRMED.

## Suspected

- **A new over-blocking trade-off.** Invalidated relations from the supporting observation still
  count, so a legitimate withdrawal of a rival's affirmation never unblocks the candidate. Only a
  warranted refutation that leaves the rival CONTRADICTED does.
- **No blocking without a forger** was seen in the benchmark, the coarse case or the two-fault case.
