# SAI 3.5 Discovery Candidate — Owner decisions, risks and self-review

Version: `3.5.0-discovery-candidate.1`.
Status: **CANDIDATE — NOT ACTIVE.** Every decision below is **OPEN**. Writing them down decides
nothing. `READY_FOR_REAL_RESEARCH = false`.

## 1. Owner decisions

`OD-NN` are SAI 3.5 Owner decisions. The SAI 3.4 decisions `D-01`–`D-08`, the G0 line's decisions
A–F and the security decisions A3, A9 and A12 stay as they are and stay open.

| ID | Decision | Default until decided | Recommendation | Status |
|---|---|---|---|---|
| OD-01 | Accept SAI 3.5 as a candidate for review, modify it, or reject it | the candidate exists only on its branch; NOT ACTIVE; nothing depends on it | review it; keep it NOT ACTIVE until G-D0 is frozen and an integration plan exists | OPEN |
| OD-02 | Assign the independent G-D evaluator and the arm-label custodian | none assigned; G-D0 is BLOCKED | one evaluator who is not the implementer (not a second account of the same person), one separate custodian; at G-D2 and above, two independent domain reviewers | OPEN |
| OD-03 | Approve protocol values: primary metric, minimum effect, non-inferiority margins, false-discovery weights, multiplicity method, sample size, re-run invalid limit, no-mechanism share | none; G-D0 is BLOCKED | true-mechanism discovery rate as primary; +10 points minimum effect; 2-point margins; weights 10/3/3; Holm at α = 0.05; n from a pilot on separate development worlds | OPEN |
| OD-04 | Approve the local models for the zero-cost stages and declare their endpoints free | none; the zero-cost stage cannot run with a model | one pinned open-weight local model, declared free under the G0 spend administration (G0 decisions A3/A4/E2) | OPEN |
| OD-05 | Authorize a paid model stage, with a ceiling | not authorized | only after the zero-cost G-D1 report, with a small ceiling and a provider-side hard cap (G0 decision A5) | OPEN |
| OD-06 | Source and rights for held-out literature cases | none; G-D2 is BLOCKED | evaluator-curated cases resolved after every model's training cutoff, with per-source rights recorded and no redistribution of unclear material | OPEN |
| OD-07 | License, worker and budget for licensed simulation discovery (G-D3) | not authorized | wait for SAI 3.4 P-LICENSED (SAI 3.4 D-04, D-05, D-06, D-02); start with one CHARGE worker | OPEN |
| OD-08 | Physical experiments and publication for G-D4 | not authorized | authorize per experiment after G-D3 for the scope; review every publication separately | OPEN |
| OD-09 | How and when to integrate the G0 line (`58c68be`), the SAI 3.4 line (`a38ad63`) and the Discovery branch | not integrated | integrate the G0 line after its independent audit; then rebase the Discovery work on the integrated line; decide SAI 3.5 activation separately | OPEN |
| OD-10 | How SAI 3.5 candidate files may exist on the SAI 3.4 integration line while the SAI 3.4 change boundary stays byte-identical | PROPOSAL (A') implemented on this branch: every SAI 3.4 file equals `a38ad63`; CI runs the unmodified SAI 3.4 checker on a temporary worktree of HEAD minus exactly the paths in [candidate-paths.txt](candidate-paths.txt) ([check_sai34_boundary_without_candidate.py](check_sai34_boundary_without_candidate.py)); the bare SAI 3.4 checker on the full tree still fails, by design | (A') this mechanism, recommended; (B) an Owner-approved widening of the SAI 3.4 allowlist (`docs/spec/sai34/activation.yaml`, `check_activation.py`), which edits SAI 3.4 files — tried in `9d44198` and reverted; (C) keep SAI 3.5 off the integration line, on its own branch | OPEN |
| OD-11 | Prior-art coverage required before a discovery claim may be called novel | none beyond SAI 3.3 SRC-003 | require literature and patent classes with a recorded coverage record; internal-only search never supports a global claim | OPEN |
| OD-12 | Reframing policy: maximum reframings per problem and per campaign | none; with no policy, a campaign stops at its first failure | a small fixed cap (for example 2 per problem) in the synthetic stage, revisited after G-D1 | OPEN |
| OD-13 | Language of the normative text | English normative text, with a short zh-TW summary for the Owner; SAI 3.3 and 3.4 are written mainly in zh-TW | keep English for review; produce a zh-TW normative translation before any activation | OPEN |

## 2. Risks

| ID | Risk | Defense in this candidate | Residual |
|---|---|---|---|
| R35-01 | Hypothesis count is mistaken for discovery ability | diversity only as equivalence classes under available experiments (D-016, D-017) | class computation depends on correct prediction typing |
| R35-02 | Reframing hides failures (garden of forking paths) | append-only reframing; failures stay in denominators; prospective validation for reframed hypotheses (D-019, D-020) | a determined writer with database authority can still bypass triggers (A12) |
| R35-03 | Discovery certifies itself | role separation; Causal Warrant Gate only; sealed evaluation plane (D-023, D-026, D-035) | the separation is designed, not built |
| R35-04 | Benchmark contamination inflates results | sealing, cutoff dates, overlap checks, memorization probes, fresh seeds (D-044) | contamination can never be ruled out completely for literature cases |
| R35-05 | Unfair comparison (budget, tools, seeds) | matched-budget protocol; mismatch makes the run INVALID (D-039) | hidden costs such as prompt engineering effort are hard to match |
| R35-06 | G0–G9 progress is read as discovery progress | explicit non-implication and separate verdicts (D-035, D-037) | readers may still conflate them; documents must repeat it |
| R35-07 | Synthetic success is over-generalized | claim discipline per level (D-003; acceptance-gd §3) | synthetic worlds encode the designer's assumptions |
| R35-08 | Pressure to show progress skips the stop | INSUFFICIENT_VALIDATION scored as correct where warranted; confident wrong claims weighted heavily (D-028) | weights are a value judgment (OD-03) |
| R35-09 | Two unintegrated lines diverge further | integration decision OD-09; the candidate names both lines and does not merge either | the longer the delay, the costlier the integration |
| R35-10 | The SAI 3.4 activation checker blocks any new file on the integration line | OD-10 proposal A': the unmodified SAI 3.4 checker runs on HEAD minus the enumerated candidate paths; the wrapper refuses protected, runtime, migration, test and script paths and any mismatch between the list and the real diff; its self-test control proves the SAI 3.4 checker still rejects the full tree | A' relies on the candidate list; two checkers compare it with the real diff. If the Owner rejects A', option B or C applies |

## 3. Critical self-review

This is the author's own review. It is **not** an independent review and not an Owner acceptance.

| Finding | Handling | Remaining state |
|---|---|---|
| The vision sentence could be read as a present capability | §1 says it is a target; D-003 limits claims to passed G-D levels; status files say G0 is NOT PASSED | must be repeated in any later summary |
| "Novel" is easy to claim and hard to check | D-004 ties novelty to a PriorArtSearchRecord with coverage (SRC-003); OD-11 sets coverage | reviewers' novelty judgments remain subjective; agreement is reported |
| Counting mechanisms rewards verbosity | D-016 and D-017 count classes, conservatively merging undecidable pairs | needs typed predictions that are good enough to compare |
| Reframing could launder a failed hypothesis | D-019: no conversion of failure into support; D-020: new lineage and prospective validation | relies on the prospective rules, which exist only on the G0 line |
| A system able to stop could stop too often | a stop is scored as "not discovered" where a mechanism was discoverable (acceptance-gd §4) | the no-mechanism share is a protocol choice |
| Matching "the same model" is ambiguous for multi-slot LIB | the primary comparison binds every slot to one model; multi-model is separate | multi-model results are not covered by the primary claim |
| The offline baselines B0/B1/B2 do not map one-to-one onto arms A/B/C | stated in the protocol; mapping to be settled before G-D0 | the offline-branch paragraph in the implementation status is provisional and will be reconciled with that branch |
| The candidate cannot pass the SAI 3.4 activation checker without editing a protected file | commit `9d44198` did widen the SAI 3.4 allowlist while this page said the files were not edited; that commit is reverted, so every SAI 3.4 file equals `a38ad63` again with no exception, and proposal A' replaces it | OD-10 stays OPEN; A' is a proposal, not an approval |
| The text is in English while SAI 3.3/3.4 are in zh-TW | a short zh-TW summary for the Owner; OD-13 | a normative zh-TW version is needed before activation |
| Document checks could be mistaken for acceptance | the checker verifies structure, IDs, hashes and the not-active state only | prose completeness still needs human review |

## 4. Reading the verification evidence

The [candidate checker](check_candidate.py) proves only that: the candidate is not active;
ACTIVE_SPEC.yaml and the SAI 3.3/3.4 files are byte-identical to the base; every D-NNN statement is
registered once; the required sections exist; the G-D levels, arms, metrics, phases and decisions
are consistent across documents; and local links resolve. It proves nothing about discovery,
physics or the quality of the prose.
