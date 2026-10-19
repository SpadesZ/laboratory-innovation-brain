# Review 1 — independent science review of the candidate SP declarations 1.1.0 (`f150bc0`)

Reviewer: a separately scoped agent, given read-only access to the code and its own disposable
database (`lab_brain_sci_p6`, created, migrated and dropped by it). It did not write the candidate.
It ran 94 ordinary episodes from fixture data — every variant under both declaration versions —
with the harness's SQL/Python agreement check on; no check failed and no episode raised. Its
episode records and scripts are in `../evidence/` (`review_episodes_batch*.jsonl`,
`review-scripts/`). Condensed from its report; resolutions are at the end.

## Verdict (reviewer)

Each withdrawal points the right way: a design-file reading cannot refute a defect made in
fabrication, and a solver-mesh property cannot cause an anomaly measured on silicon. 1.1.0 removes
every false mesh confirmation and every false design-file exclusion of the contact and dopant
classes the reviewer constructed. **The revision is not ready to activate:**

1. **The mesh withdrawal is incomplete.** UNSTABLE still counts as the mesh class's declared
   signature. Observing it holds back every other class's confirmation, and neither `review_only`
   nor a person's refusal releases that (`verification/loop.py` `_observed_signatures`;
   `012p` `confirmation_rule_breaches`).
2. **One changed expectation was wrong.** In probe-lab-closed the candidate asks for a split lot,
   which produces only a carrier profile: it cannot discriminate contact and does not test the
   probe artifact, the case's truth; it is a 6-week, $40k, irreversible fabrication.
3. **`review_only` is keyed to the link, not to the evidence source.** A calibrated measurement on
   fabricated silicon (the split lot's NOMINAL) loses its automatic authority to refute too.

The candidate leaves magnitude, direction and symptom-consistency problems in place; they still
produce false confirmations under both versions.

## Per link (reviewer)

| link | verdict |
|---|---|
| contact CONTRADICTS (drawn layout) | withdrawal justified; the class then has no refutation this deployment can run — split drawn from fabricated, add a measured contact observable (TLM, Kelvin, PCM chain) |
| dopant CONTRADICTS (design-file solve) | justified in direction; too broad, since it also withdraws a calibrated measurement's refutation — scope by evidence family |
| mesh SUPPORTS | justified but insufficient (item 1 above) |
| contact SUPPORTS | unchanged; size- and symptom-blind (a 95 nm overlap against a 100 nm rule adds a few percent); an open terminal is also hard to square with a normal Cj |
| dopant SUPPORTS | unchanged; a ratio of 0.32 gives about 1.5–1.7× resistivity, not several-fold |
| normalization SUPPORTS | unchanged; blind to direction and size under R×L — a rule version, not `review_only`; the catalog's "divides by" contradicts the extractor |
| normalization, mesh CONTRADICTS | sound |
| probe | category right; signature should say "2-point minus 4-point accounts for the excess"; not executable here |

## Benchmark cases (reviewer)

- mesh-coarse-access: agree that mesh must not be confirmed and the probe is next; `truth:
  mesh_artifact` is wrong (the device is physically nominal), as is outage-mesh's; even after the
  probe the episode cannot conclude (item 1).
- probe-lab-closed: disagree with the 1.1.0 expectation (item 2). The right stop waits for the
  probe station or stops naming what design readings left open; 1.0.0 had the right stop for the
  wrong reason. The expectation had also been taken, after the fact, from the 2026-10-15
  experiment's output.
- The three added cases: expectations correct; the two normalization cases are honestly marked as
  known limitations of both versions.

## Counterexamples (reviewer; least-cost unless noted)

| variant | device | 1.0.0 | 1.1.0 | expected |
|---|---|---|---|---|
| C1 | counter-doping 3E17; mesh 40 nm | CONFIRMED mesh | dopant SUPPORTED, blocked by UNSTABLE | dopant |
| C13 | C1, probe closed | CONFIRMED mesh | AWAITING_REVIEW; no answer confirms dopant | dopant |
| C16 (simulate-first) | as C1 | CONFIRMED dopant | CONFIRMED dopant | dopant — so 1.1.0's C1 result depends on check order |
| C8/C9 (simulate-first) | normalization 1000 or open via; mesh 40 | COMPETING | blocked by UNSTABLE | the real cause |
| C2 | anode overlap 95 nm | CONFIRMED contact | same | not confirmed |
| C10 | counter-doping 3E17; overlap 95 nm | CONFIRMED contact | same; dopant never tested | dopant |
| C3 | counter-doping 1.6E17 (ratio 0.32) | CONFIRMED dopant | same | not confirmed |
| C4, C11, probe-lab-closed | probe closed (± mesh, ± weak doping) | mesh confirmed or false exclusions | split lot | wait for the probe |
| C6 | non-converged solve; probe closed | split lot | split lot | a converged re-run (already in 1.0.0) |
| C7, C14 | two faults, one cheap | the cheap class confirmed | same | not a unique confirmation (review 04's V5) |

Not counterexamples: C5 (1.1.0 better), C12, C15, C8/C9 under least-cost.

## Could not test (reviewer)

Probe and split-lot outcomes (no workflow; producing them would mean forging observations), a
person's answer to a warrant review (needs memberships, a queue policy and key enrolment the rules
forbade), simulated-anomaly scenarios (would need the fixture's symptom text changed), real
Lumerical physics, contacts with several vias per region. Magnitudes are textbook estimates.

## Resolution (authors, `sp-declarations-candidate`)

- **Status: the candidate stays NOT ACTIVE and is marked not ready** (`product.py`). Nothing the
  product concludes changes; 1.0.0 remains the only registered version.
- Benchmark 1.1.0 revised: probe-lab-closed keeps 1.0.0's expected stop, for the stated reason, and
  is a known limitation of 1.1.0; the two mesh cases' truth is corrected (the 1.0.0 value kept as
  `truth_in_1_0_0`); C1, C13, C2, C10 and C3 are added, each a known limitation. Under the
  candidate, every case that is not a known limitation ends where the benchmark says, and every
  known limitation still ends wrong (`tests/e2e/test_sp_candidate_declarations_postgres.py`;
  `evidence/benchmark_1.1.0_revised_under_candidate.txt`).
- Not done, for the owner and a domain expert: the measured/simulated distinction or a rule that an
  unwarranted review-only signature does not hold other classes back (item 1, a change to the loop
  and `012p` together); scoping `review_only` by evidence family (item 3); size- and direction-aware
  signatures; a temporary-resource model for a closed station and a rule against an irreversible
  fabrication as the next step; declared PCM/e-test checks; a benchmark run with a review queue.
