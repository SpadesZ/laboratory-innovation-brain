# Review 2 — adversarial design review of the first draft

Isolated reviewer, read-only. Input: the first draft of the design (option "E": DOMAIN/REVIEW
warrants keyed on content, a unique-confirmation rule, replicates counted once, quarantine).
Asked to break it, including outside silicon photonics. Report as delivered (condensed only where
marked); resolutions in `../REPORT.zh-TW.md` §5.

## CRITICAL

**1. DOMAIN warrant + I5 + I6 do not make an outcome discriminate against rivals in the set.**
- **SP scenario.** Add a model rival R ("taper sections excluded from the drawn length", which is
  the catalog's own declared confounder) with `sp.normalization_basis = DISAGREES -> PREDICTS` — what
  `PREDICTION_EFFECT_MEANINGS` tells a model to write when rivals share an outcome. DISAGREES is
  observed. The normalization class is DOMAIN-warranted and SUPPORTED. R's PREDICTS never counts and
  never queues anything, so I6 holds and the class is CONFIRMED.
- **Clinical scenario.** "Troponin elevated" is declared for MI, and a myocarditis rival declares
  it PREDICTS: MI is confirmed.
- **The SUPPORTS variant.** If R declares SUPPORTS and the reviewer returns NOT_WARRANTED, or the
  review EXPIRES, the correct rejection ("o does not discriminate R because MI also produces it")
  is an argument that applies equally to C. Yet it removes I6's only blocker.
- **Incentive inversion.** An honest PREDICTS loses; over-claiming SUPPORTS blocks.
- **Fix (I6′).** A warranted SUPPORTS from observation x confirms only if no other member holds a
  non-CONTRADICTS relation from x. Only a warranted refutation of that member, or a reviewed
  discrimination verdict, unblocks it.

## HIGH

**2. Ungated refutation is a path to false confirmation, and CONTRADICTED is terminal.** A cheap
proxy check moves the true cause T to CONTRADICTED through T's proxy falsifier — the recorded
`epi:6174b0fe` shape. A later check matches C's DOMAIN tuple, so C becomes SUPPORTED. T's affirming
relation is never evaluated: no policy leaves CONTRADICTED, and the loop skips "holds both".
- **Fix:** I6′ treats a rival as excluded only by a warranted refutation, and reports label
  unwarranted refutations.

**3. The warrant does not scope authority, conditions, independence or the trace.**
- Authority classes are resolved over all admitted relations, and step 6 passes if any class meets
  the rule. A warranted coarse SUPPORTS together with an unwarranted DESIGN_INSPECTION relation
  therefore gives ALLOW.
- `_commit` passes all admitted relations as triggering, so the proxy enters
  `root_cause_evidence_ids` and the miner's suggested checks.
- 4b-before-5–7 turns would-be DENYs into reviews.
- **Fix:** per-relation evaluation; 4b after 7; trace and triggering scoped to warranted relations.

**4. "Unique" means unique among what has been tested so far.** The loop stops at the first
SUPPORTED, so I6 bites only when one observation supports two members.
- **Software incident:** pool saturation is the declared signature of pool exhaustion, but it can
  also be produced downstream by an untested slow-query regression.
- **Battery:** lithium loss is declared for SEI growth, but plating also consumes lithium.
- **Fix:** an expectation matrix; confirm only when every member is discriminated; otherwise
  SUPPORTED_UNDISCRIMINATED.

**5. The REVIEW path cannot work as specified.**
- The service closes non-waiting episodes, so an APPROVED grant can never confirm anything.
- REJECTED cannot be seen, so the item is either re-queued or waits forever.
- Nobody resumes after a grant.
- The loop halts at the first unwarranted support even when a DOMAIN-resolvable check exists.

## MEDIUM

6. **Declaration-set and policy staleness.** No digest; old versions keep warranting; `1.0.0`
   policies remain attemptable. Fix: a pinned digest, replay-only versions, retraction.
7. **Grant integrity.** No revocation; the episode actor can grant; I10 does not re-check binding
   or the prediction id. Fix: re-check from the immutable certificate; self-grant labels or
   refusal.
8. **I7 counts more independence than the baseline.** The observable in the line key makes one Run
   two lines, and ids or seeds create new lines. Fix: drop the observable and use content digests.
9. **Binding.** It is not a keyword rule, but it binds on the label, not the claim: paraphrases
   never bind and duplicate names block each other. Better: bind only if the hypothesis's
   predictions on the class observable match the declared pair; add an OUT_OF_SET_SIGNATURE note.

## LOW

10. **H1.** Omitting only the one field is safe; `exclude_defaults` would not be. Golden tests must
    include default-valued fields.
11. **Pending rival reviews.** I6 ignores a rival's other pending reviews (authority, blocking
    conflicts).
12. **Report wording.** SUPPORTED rivals disappear from the service conclusion under
    COMPETING_SUPPORT.

## Q6 — gate refutation?

**Recommendation:** in V1, gate refutation's *effect on confirmation*, and label unwarranted
refutations. Gate the transition itself once a review surface exists.

## Q7 — smaller designs

- **(a) Warrant at relation creation:** emit PREDICTS instead of an unwarranted SUPPORTS.
- **(b) Stage it:** V1a domain warrants, V1b grants.

## Verdict

Option E is the right direction: content-keyed, non-author warrants, unique confirmation and
derived quarantine. It is not approvable as written:
- its notion of discrimination is wrong (#1, #4);
- ungated refutation reopens false confirmation (#2);
- the warrant does not scope what the policy counts (#3);
- the REVIEW path cannot work (#5).
