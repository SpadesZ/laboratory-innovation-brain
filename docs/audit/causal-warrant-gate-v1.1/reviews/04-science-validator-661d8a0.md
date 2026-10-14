# Review 4 — science validation of the SP declarations and the gate (`661d8a0`)

Condensed as delivered. The reviewer ran ordinary episodes from fixture data with `run_case`, on
its own database (created, migrated and dropped), and did not forge anything. Resolutions are in
the last column.

## Verdict (reviewer)

The gate does what it was built to do:
- an author's claim no longer counts as evidence;
- renamed mechanisms go to a person;
- shared predictions block confirmation.

But the SP declarations claim more than their checks can show. Each check is a binary rule over
design-file fields: it shows a fault's precondition is present. It never shows that the fault
produced this anomaly (high Rs, flat bias dependence, normal Cj).

## Per-class declarations (reviewer)

| class | signature / refutation | exclusive? | refutation sound? | main risk |
|---|---|---|---|---|
| contact discontinuity | DISCONTINUOUS / CONTINUOUS (drawn layout) | among the five, yes; lumps an open via with a thin overlap | **no**: a design reading cannot see a fabricated contact defect | terminal false refutation; "dominates" over-claimed from a 95 nm vs 100 nm rule flag |
| length normalization error | DISAGREES / AGREES (more than 1 % mismatch) | among the five, yes; blind to direction and size (the pack's own formula R·L means a shorter length *deflates* Rs) | mostly, for length | a 2 % or opposite-sign mismatch confirmed as the cause |
| mesh convergence artifact | UNSTABLE / STABLE | only in the mock | roughly | **category error**: a solver artefact cannot cause a *measured* anomaly, yet it is confirmed in the benchmark |
| dopant compensation | COMPENSATED / NOMINAL | in the mock; `classify_carrier` reads the echoed design inputs, not the solver's carrier density | **no**: a design-file solve cannot see process compensation | terminal false refutation; a ratio of 0.3 gives ≈1.4× ρ, not "several times" |
| probe contact artifact | ELEVATED / NOMINAL (4-point) | mostly | yes | magnitude-blind; never run (needs a person), and never blocks |

## Demonstrated (reviewer) and resolution

| # | variant | outcome at `661d8a0` | resolution |
|---|---|---|---|
| V1 | contact-open-via + normalization 510 µm | CONFIRMED normalization after one 2 s check; the open via was never inspected | **Fixed.** Before a confirmation, every cheap, automatic, available check that could move an untested rival runs. V1 now ends COMPETING_SUPPORT with both checks run (`test_two_faults_each_with_a_cheap_check_are_both_looked_at`). |
| V2 | contact-open-via + 1000 µm | as V1 | **Fixed**, as V1 |
| V5 | normalization-taper + 90 % counter-doping | CONFIRMED normalization; the dopant check (a simulation) was never run | **Not fixed by design.** The loop does not escalate to a simulation just to discriminate (VER-001, the cost gate). The conclusion names the untested rival by mechanism. Recorded residual. |
| V3/V4 | probe artifact + 510 µm / 250 µm | CONFIRMED normalization. 250 µm deflates Rs under R·L, yet "inflates" was asserted. | Declaration over-claim (size and direction). **Owner / domain expert.** The conclusion wording now says the signature shows the condition is present, not that it accounts for the anomaly's size. |
| V9 | normalization class unproposed; taper 1000 µm + 95 nm overlap | CONFIRMED contact; the normalization check was never run | **Fixed.** A declared class nobody proposed, whose cheap check could have observed its signature and did not, holds the conclusion (SUPPORTED_UNDISCRIMINATED, naming the class and the check). Test: `test_a_cause_the_domain_declares_but_nobody_proposed_holds_the_conclusion`. |
| V6 | probe artifact as in the fixture | contact, normalization, mesh and dopant all CONTRADICTED on design-file readings, terminally | Declaration over-claim (design-file refutation of fabricated-device classes). **Owner / domain expert** (a declaration version change). |
| V7 | V1's device, proxy normalization rival | the open via is never confirmable (2 % counts as another class's signature) | Declaration threshold and size-blindness: **owner / domain expert** |
| V8 | contact paraphrase + `--is-class` | recorded as "access contact discontinuity … dominates" against the reviewer's own account | The packet now shows the class statement `--is-class` would record, before it is used. Storing the reviewer's account beside the failure class, and a "refines class X" record: **owner decision**. |
| V10 | normalization unproposed, all proposed rivals refuted | waits for the probe; no note on the unproposed class | **Fixed** with V9: a cheap check of an unproposed class is named. |
| bench | mesh-coarse-access | CONFIRMED mesh artifact for a measured anomaly | Category error in the declarations: **owner / domain expert** |

## Wording (reviewer) and resolution

- **"The observed X is the declared signature of Y" over-states.** Fixed. Packet and conclusion
  now say:
  - "among the N classes … declares";
  - "shows that class's condition is present, not that it accounts for the anomaly's size or bias
    dependence".

  The packet also shows the class's refuting outcomes and the statement `--is-class` records.
- **"Never tested: hyp:… -- they are excluded only by not predicting the observation"** listed ids
  and said "excluded". Fixed: rivals are named by mechanism, and the note now says "nothing
  excluded them".
- **Recording a person-identified paraphrase under the class name merges sub-mechanisms.** Owner
  decision.
- **The catalog says the extraction "divides by" the length, but `extractors.py` multiplies Rs by
  L.** Recorded for the domain owner.

## Recommendations for a declaration version (reviewer; owner / domain expert)

| class | change |
|---|---|
| normalization | a signature with direction and size, stated as explaining magnitude only; handle the doped-taper confounder |
| contact | split open via from sub-rule overlap; CONTINUOUS refutes only a *drawn* discontinuity; add a measured contact observable (TLM/Kelvin) |
| dopant | a design-simulation NOMINAL should challenge, not refute, process compensation; add the unlisted low-carrier mechanisms; revisit the 0.3 threshold; classify the solver's output, not the echoed inputs (a rule version bump) |
| mesh | restrict to *simulated* anomalies (a typed measured-vs-simulated field); a directional signature |
| probe | signature: "2-point minus 4-point accounts for the excess Rs" |

Owner: a symptom-reproduction (sufficiency) requirement for CONFIRMED, with declared observables for
the Rs(V) slope and the Cj magnitude. Also add V1–V9 as regression cases in a new benchmark
version.
