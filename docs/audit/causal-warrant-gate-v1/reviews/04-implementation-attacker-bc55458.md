# Review 4 — executable adversarial testing of `bc55458`

Isolated tester with its own disposable database and a scratch directory outside the repository.
Asked to break the gate and to report only what it could demonstrate, separated from suspicions.
Report as delivered; resolutions in `../REPORT.zh-TW.md` §5.

**Bottom line:** only one route produced a wrong mechanism CONFIRMED through a full `run_case`
episode: one direct SQL write placing a grant in `diagnostic_warrant_grants` without
`diagnostic_warrant_resolve` (finding 1). Fixture shaping alone produced no factually wrong DOMAIN
confirmation on the mock backends. It did find three logic gaps (findings 5–7) where a confirmation
rests on evidence the domain's own rules do not accept.
- The attacker's 17 tests passed and 1 was skipped; the implementer's 54 gate tests passed.

## Demonstrated (ranked)

1. **HIGH — direct grant INSERT bypasses the gate and confirms the recorded proxy.**
   - What happened: an `AGENT_ROLE` actor who is not a member inserted a WARRANTED grant. The
     review stayed QUEUED and no resolution row was written.
   - Result: `stop CONFIRMED … failure_class missing contact-resistance correction … warrant_refs
     ('dwg:forged',)`.
   - Why: the membership check existed only inside the function; the trigger checked only that the
     grant matched its review and relation.
   - Fix: the trigger requires an outstanding review and an active HUMAN member, and a deferred
     constraint trigger requires the WARRANT_GRANT resolution.
2. **HIGH/MED — the resolver trusts mutable `relation_judgments` rows.**
   - Test K: one UPDATE (type, prediction, outcome) yields a DOMAIN warrant, although the
     attestation still records AGREES.
   - Test J: after an APPROVED grant, the relation's prediction and outcome are rewritten and the
     REVIEW warrant stands; the grant's `prediction_id` is never compared.
   - Fix: take the outcome from the attestation, compare the grant's prediction, and add a BEFORE
     UPDATE trigger allowing only `valid_to` and `invalidation_reason`.
3. **MED — the read path re-checks against the snapshot's copy of the relation.**
   - Test F: a retargeted relation id with contact's signature (never observed) passes as an ALLOW
     with a DOMAIN record, and the honest `project()` returns SUPPORTED under the gated 2.0.0
     policy.
   - Fix: `verify` loads the stored relation and requires equality.
4. **MED — superseded 1.0.0 still authorises new transitions, and the CONFIRMED guard only counts
   refs.**
   - `attempt_transition(promote@1.0.0)` on the proxy gives ALLOW, with the verified state
     SUPPORTED.
   - `failure_analyses` accepts `warrant_refs=('dds:no-such-set@9#nothing',)`, and case memory
     returns it.
   - The loop itself declined to confirm.
   - Fix: refuse superseded versions, and validate the refs in the trigger.
5. **MED — a coarse refutation discharges a rival that shares the observation, against SIM-002.**
   - Contact-open-via with the mesh rival also PREDICTS-ing DISCONTINUOUS, non-converged: mesh is
     only CHALLENGED at SIM_COARSE, yet `standing()` confirms contact.
   - Fix: a rival is excluded only if it is CONTRADICTED, or if the reject policy would ALLOW.
6. **MED-LOW — a missing queue fails open, and another class's observed signature is dropped.**
   - Test H, a device with both an open via and a 1000 µm normalization length: with a queue the
     loop waits; without one it CONFIRMS contact, although its own note names the normalization
     signature.
   - Test H2: after the reviewer REJECTs the proxy, the resumed run CONFIRMS contact and the note
     is gone.
   - Fix: threaten on unreviewed gated relations, treat a foreign declared signature as
     undischarged, and emit the note at the conclusion.
7. **LOW-MED — copying a class's mechanism string binds (test N).**
   - The contact-resistance narrative is confirmed under the normalization class.
   - `DiagnosticDeclaration.statement` is never rendered.
   - Fix: render the class statement.
8. **LOW — the hypothesis's author can warrant their own link.** Fix: refuse when the actor equals
   `authored_by_actor_id`.
9. **LOW — with two gated required types, one warranted type suffices.** Fix: require a warranted
   relation per type.

## Refused as intended

- a wrong hypothesis or type in a grant;
- a resolution disagreeing with its grant;
- a second grant for one review;
- UPDATE or DELETE of a grant;
- EXPIRED without a decision;
- a lying resolver's fake REVIEW or DOMAIN records (`WARRANT_UNVERIFIED`);
- the benchmark: least_cost is 10/10 correct. simulate_first differs only on outage-contact, the
  baseline's intended escalation.

## Suspected

- The CLI `--actor` identity is self-asserted.
- DOMAIN wins over NOT_WARRANTED.
- A forged committed event makes later projections of that hypothesis fail closed permanently.
- A PREDICTS-only rival whose refutation cannot be observed vetoes confirmation, with no review
  path.
