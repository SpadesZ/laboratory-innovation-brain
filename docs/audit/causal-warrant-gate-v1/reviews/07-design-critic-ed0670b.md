# Review 7 — final pass on `ed0670b` (same reviewer as reviews 2, 3 and 5)

Read-only. Report as delivered, condensed; resolutions in `../REPORT.zh-TW.md` §5.

This round's claims hold:
- an identity grant is honoured only on the declared class's own signature;
- the waiver for approved links is gone;
- the unpredicted-signature check (N3) reads the episode's observed outcomes;
- the new SQL triggers are in place;
- invalidated rival affirmations still count.

No new false-confirmation path works without a human error. Four issues remain.

## Defects

1. **MEDIUM, latent here: an identity grant gets around the full-pair binding rule.**
   - A hypothesis that joins class C by `identifies_class_ref` never had to declare C's refuting
     outcome.
   - The episode-outcome scan looked only for *other* classes' signatures.
   - If C itself is not in the set (the CE-1 shape) and a second method observes C's refuting
     outcome, no family relation records it, and the identified member confirms.
   - Latent in SP: each observable comes from one check that runs once per episode.
   - **Fix:** treat an observed refuting outcome of the candidate's own class as blocking.
2. **LOW-MEDIUM: an identified hypothesis is recorded under its own wording.**
   - `failure_class` was the hypothesis's mechanism text, so a wrongly identified proxy would be
     filed under the proxy's words while resting on the class identity.
   - The class's declared statement was shown only for `dds:` refs.
   - **Fix:** record the class's canonical name and state its declaration.
3. **LOW-MEDIUM, over-blocking: genuinely co-occurring causes can never be concluded.**
   - COMPETING_SUPPORT parks the episode. The only way out is a person saying the two are one
     class, which is false for a real multi-cause failure.
   - **Fix:** a multi-cause conclusion, or a governed "close as co-occurring" action.
4. **LOW: quarantined evidence is read by the episode-outcome scan.**
   - `episode_outcomes` does not apply the §6.18 quarantine set, so a known-bad extractor's outcome
     could block a confirmation indefinitely.

## Checked and correct

- identity scope (`_identity`, re-checked by `verify`);
- an expired review may be asked again, while REJECTED stays terminal;
- the relation insert trigger binds the relation's prediction, outcome, attestation, observable
  and episode; `evidence_from_run` is the only writer of prediction-linked relations;
- superseded policies are refused both in SQL and through the policy store;
- `warrant_refs` must appear in a promoting decision's snapshot;
- invalidated affirmations still count.

## Verdict

Approve as a fail-closed P0 safety gate, not as `READY_FOR_REAL_RESEARCH`.

**What it now guarantees:**
- A model's own declared SUPPORTS or CONTRADICTS can no longer confirm or refute anything.
- Confirmation requires warranted support of one class, with rivals' affirmations discharged by a
  governed refutation, no unsettled counter-evidence, no foreign signature observed, and a
  conclusion whose warrants trace to the promoting decision.
- Replay and old snapshot hashes are preserved, and pre-gate conclusions are quarantined.

**What still gets a false confirmation through:**
- a reviewer approving or identifying wrongly (attributable, but resting on a self-asserted
  `--actor`);
- the own-class refutation gap (item 1).

**Main cost:** over-blocking.

**Before sign-off:**
- fix items 1 and 2;
- align the design document and the spec amendments with the code;
- record the deliberately open items as accepted residual risk.
