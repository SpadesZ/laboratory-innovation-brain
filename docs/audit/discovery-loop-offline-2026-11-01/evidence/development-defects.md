# Defects found during development, before their fixes

All of these were found on the DEVELOPMENT worlds (`DEVELOPMENT_BASE_SEED = 1`) or on the toy
catalog in `tests/discovery_fixtures.py`. The evaluation worlds (`EVALUATION_BASE_SEED =
2026110100`) were run once, after the protocol was frozen at `c92e7df`. This file is the honest
record that the protocol was shaped by what the development runs showed.

## Naive versions that the tests show failing

| naive version | how it fails | test |
|---|---|---|
| diversity = number of hypotheses examined | 50 renamed copies / indistinguishable variants raise it from 3 to 53; the class count stays 3 | `test_the_naive_hypothesis_count_is_gamed_by_fifty_indistinguishable_variants` |
| support = every admitted observation the hypothesis could have failed, whatever its time | a hypothesis registered after two observations it fits is called "tested on two experiments" with zero prospective data | `test_retrospective_observations_never_count_as_support` |
| (measured on the frozen run) the same naive support rule | would have counted 88 widened or closure-screened hypotheses as prospectively tested when they were not | `defects.json` → `retrospective_support` |

## Engine defects found and fixed during development

1. **Claims after one observation, from a glitch.** First smoke run (2 worlds per kind): in
   noise-only worlds both B1 and B2 claimed `fcd.static` / `scatter.sidewall` after a single
   (glitched) measurement, because one observation refuted every rival at once.
   Fix: severity (`min_prospective_tests = 2` distinct experiments) and a pre-registered decisive
   replication of the observation a rival's refutation pivots on.
2. **Closed-world claims with a single test.** `chain.laser_drift` was claimed when the truth was
   `cladding.index_drift` (and `width_wide` for `thermo.self_heating`, `scatter.sidewall` for
   `chain.polarization_drift`): once one hypothesis was left, no experiment ever tested a declared
   rival nobody had registered. Fix: rival closure before a claim (declared alternatives of no
   greater complexity that the data do not refute must be discriminated too).
3. **Weak alternatives never resolved.** In noise-only worlds the noise model and small-amplitude
   classes stayed jointly live until the budget ran out: an absolute goodness-of-fit test has little
   power against a specific small deviation. Fix: the comparative half of the refutation rule
   (`delta_chi2_refute = 10.828`, a likelihood-ratio test at the same alpha), shared by B1 and B2.
4. **Bloated classes.** The class closure added every composition "member + a tiny second effect"
   that no available experiment separates from the member. Fix: parsimony -- the class takes
   alternatives no more complex than its members; the rest are listed as `cannot_exclude`.
5. **The replication test (found by the toy glitch test).** The first rule compared only the
   original with its replicate, and re-examined only refutations resting on the glitch ALONE:
   - toy seed 5: a 7-sigma glitch offset by -2.4 sigma of noise differed from its replicate by
     2.998 sqrt(2) sigma, under the 3.0 threshold: "REPRODUCED"; every hypothesis stayed refuted;
     `STOPPED_UNEXPLAINED`;
   - toy seed 3: the true hypothesis's refutation rested jointly on the glitch and a good
     observation, so it was not a reference for the test: "UNSTABLE"; `STOPPED_UNEXPLAINED`.
   Fix: the replicate is attributed to noise when a declared hypothesis explains it and, on the
   entry where the original deviates most, it sides with that hypothesis rather than with the
   original; every refutation the noise-attributed observation was pivotal for is re-examined.
   Regression: `test_a_glitch_is_tested_attributed_to_noise_and_its_refutations_withdrawn[1..7]`.
