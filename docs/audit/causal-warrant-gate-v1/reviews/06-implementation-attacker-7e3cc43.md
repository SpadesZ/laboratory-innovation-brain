# Review 6 — attack suite re-run against `7e3cc43` (same tester as review 4)

Own disposable database, scratch scripts outside the repository. The implementer's 73 gate tests
passed and `git status` stayed clean. Report as delivered; resolutions in `../REPORT.zh-TW.md` §5.

**Bottom line:** one forged `relation_judgments` INSERT still produced a wrong cause CONFIRMED
with no human involved (N1). Findings 3, 5, 6, 7 and 9 are fixed; 1, 2, 4 and 8 are partly fixed.
The fix also introduced a new over-blocking failure: a review that expires unanswered blocks the
true cause permanently.

**Benchmark (plain fixture):** least_cost is 10/10, every stop and cause as expected.
simulate_first differs only on outage-contact (AWAITING_RESOURCE), the baseline's intended
escalation.

## The nine original findings

1. **Direct grant INSERT: fixed for direct writes.**
   - A non-member: `act:llm-agent is not an active human member`.
   - A member without a resolution: `grant … is not the closure of review …`.
   - Still possible: impersonation through the function (A2).
2. **UPDATE of relation content: fixed** (`… content is immutable`). A forged INSERT still works
   (N1).
3. **Lying snapshot: fixed** (`the snapshot's copy of … is not the relation stored`).
4. **Superseded versions and fake refs: partly fixed.**
   - With `superseded=` wired, the attempt is refused, and non-`dds:` refs are refused.
   - The default (nothing wired) and `dds:`-shaped refs still pass (A3).
5. **Coarse exclusion: fixed.**
6. **Two faults: fixed.** The result is HUMAN_ACTION_REQUIRED either way, with a note naming the
   normalization signature.
7. **Class statement: fixed.** The conclusion states the declared class.
8. **Author self-grant: fixed.** A bypass remains (A5).
9. **Per-type gating: fixed.**

## Still exploitable, or new (demonstrated)

- **N1 HIGH — one forged relation INSERT confirms the wrong cause.**
  - Episode B (outage-mesh, truth mesh_artifact) gets a SUPPORTS relation for its dopant
    hypothesis, citing episode A's COMPENSATED attestation, observation and condition match.
  - Result: `CONFIRMED dopant_compensation … refs ('dds:…#dopant_compensation',) … truth
    mesh_artifact`.
  - **Fix:** a BEFORE INSERT trigger (prediction ↔ target, `from_entity_id` = the attestation's
    observation, observable and space match, the run is from the hypothesis's episode), mirrored in
    the resolver.
- **A2 MED — anyone can answer as someone else.** `diagnostic_warrant_resolve(…, 'act:pi', …)` from
  any connection confirmed the proxy. **Fix:** bind the actor to an authenticated session.
- **N2 MED (new over-blocking) — an expired review blocks the true cause forever.** The control
  (answered before expiry) confirms; after expiry, the late answer is refused, nobody may ask again,
  and contact stays SUPPORTED but unconfirmable. **Fix:** allow a new review after expiry.
- **A3 MED.**
  - A `BeliefEpisode` without `superseded=` allows promote@1.0.0, and the read path never checks
    supersession.
  - A CONFIRMED row with `dds:no-such-set@9#nothing` is accepted and becomes a precedent.
  - **Fix:** derive supersession from the store, check it on events, and validate `dds:` refs.
- **N3 MED-LOW — invalidating a rival's shared affirmation lets the candidate confirm.**
  `SqlRelationStore.invalidate(..., reason="tidy")` turns HUMAN_ACTION_REQUIRED into CONFIRMED.
  **Fix:** count invalidated affirmations, or govern invalidation.
- **A5 LOW — `UPDATE relation_judgments SET actor_id` on a current relation is accepted**, so the
  runner can then grant. **Fix:** let `actor_id` change only with `valid_to`.
- **N4 LOW, by design** — outage-contact plus a coarse mesh confirms contact while mesh is never
  tested (seat held). Only a note records it.

## Suspected

- A cross-observable variant of N1 inside one episode.
- A denial of service: a forged INSERT claiming another class's signature would block every
  confirmation, because the signature rule reads relation attributes.
