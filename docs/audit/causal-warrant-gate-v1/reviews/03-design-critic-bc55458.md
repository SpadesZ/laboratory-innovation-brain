# Review 3 — implementation review of `bc55458` against the draft review's findings

The same reviewer as review 2, read-only, judging the code at `bc55458`. Report as delivered;
resolutions in `../REPORT.zh-TW.md` §5.

## (a) Earlier findings

| # | status | evidence |
|---|---|---|
| 1 in-set rival affirms the outcome | RESOLVED for the same observation | `standing()`: a rival SUPPORTS or PREDICTS from the observation blocks; only a warranted CONTRADICTS lifts it; the check is structural, so a NOT_WARRANTED or EXPIRED review no longer unblocks. Residual: B1, B3. |
| 2 refutation gated | RESOLVED for confirmation; introduces over-block B4 | `warranted_transition_policies`; `diagnosis_targets` |
| 3 per-relation evaluation | RESOLVED | `_decide_warranted`; `counted_triggers`; `confirm_root_cause` and the 012o trigger require `warrant_refs` |
| 4 premature closure, silent rivals | NOT RESOLVED | out of scope by docstring; silent rivals never block; untested rivals not recorded |
| 5 resumability | RESOLVED (small gap) | a no-queue project closes INCONCLUSIVE |
| 6 staleness | PARTLY | digest only in tests; only the current set registered (B5); superseded versions still attemptable |
| 7 grant integrity | PARTLY | `verify` resolved; missing revocation, a self-grant bar, `considered_rival_ids` validation |
| 8 replicates | RESOLVED | |
| 9 binding | MOSTLY RESOLVED | "silence is agreement" creates B1 |
| 10 H1 | RESOLVED | |
| 11 other review kinds pending on a rival | NOT RESOLVED | |
| 12 report wording | RESOLVED | |

## (b) New problems

**B1 HIGH — false confirmation: a domain-declared refutation is ignored.**
- `agrees_with` treats silence as agreement. A hypothesis stating a class's exact mechanism and
  only its SUPPORTS outcome binds to the class.
- Refutation acts only through relations, and a relation exists only for an outcome the hypothesis
  predicted. So the domain can support it and never refute it.
- **Twin variant.** H2 is the catalog class with its full pair; H1 is a model copy with only the
  signature. Two observations of the observable disagree (DISAGREES, then AGREES). H2 holds both
  and is skipped; H1 is promoted; `standing()` treats H2 as a rival "excluded" by its own warranted
  refutation — which is actually a refutation of the candidate's class. Result: CONFIRMED.
- **Clinical analogue:** serial troponin readings.
- **Fix:** binding requires every refuting outcome declared as CONTRADICTS, and a warranted
  refutation on any member bound to the candidate's class blocks it.

**B2 HIGH — a "human" warrant can be minted by anything with shell access.**
`review resolve --actor X` accepts any id that is an active human member, so an agent driving
`research run --actor X` can approve its own proxy as X.
- **Minimum fix:** refuse `granted_by_actor_id` = the relation's `actor_id`. Record the channel;
  long term, authenticate it.

**B3 MEDIUM — the threat check depends on whether a review was queued.**
- With no queue, nothing threatens.
- A CONTRADICTS arriving after SUPPORTED is never queued.
- The shared-observation e2e test confirms only because no queue is configured.
- **Fix:** derive threats from the records, ignore excluded rivals, and have `standing()` queue
  what it waits on.

**B4 MEDIUM — over-blocking: an unwarranted relation vetoes a warranted move.** The "holds both"
skip counts unwarranted relations, so a bound contact hypothesis carrying a model proxy falsifier
is never promoted and nothing is queued.

**B5 MEDIUM — a catalog version bump breaks every past belief.** Only the current set is
registered. **Fix:** an archive of past sets, the digest in the ref, a runtime check.

**B6 MEDIUM — over-blocking with no human way out.** PREDICTS relations cannot be reviewed, and
there is no "does R produce o?" review, so a rival whose falsifier needs an unavailable capability
suspends the episode for good. **Fix:** a DISCRIMINATION review subject.

**B7 LOW.**
- `asked` per (hypothesis, policy) misses relations that arrive later.
- A DOMAIN warrant overrides NOT_WARRANTED.
- The CLI lacks the unclaimed-signature note.
- Expiry is ignored at resolution.
- The candidate among equivalent members is chosen in id order.

## (c) What would make an auditor reject it

1. B1 and B2.
2. B3 (a central positive test passes only without a queue).
3. #4 open while the docs claim relativity to the members proposed.
4. The design doc and spec amendments do not describe the code.
5. Supersession and the digest are enforced only by tests.
