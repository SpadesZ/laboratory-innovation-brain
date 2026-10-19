# Candidate SP declarations 1.1.0 — status

**Not active. Not ready to activate.** The product registers and reasons under
`sp.rs_anomaly_mechanisms@1.0.0` only; 1.1.0 is code for the owner's decision.

## What 1.1.0 is

1.0.0 with three links left to a person (`review_only`, `012t`), because their check cannot
observe what the link claims:

| class | link | why |
|---|---|---|
| contact discontinuity | CONTRADICTS (CONTINUOUS) | a drawn-layout reading cannot refute a fabricated defect |
| dopant compensation | CONTRADICTS (NOMINAL) | a design-file solve cannot refute process compensation |
| mesh convergence artifact | SUPPORTS (UNSTABLE) | a coarse simulation mesh does not explain a measured anomaly |

## Evidence

- Benchmark 1.1.0 (`fixtures/vertical/sp_rs_root_cause_benchmark_1.1.0.json`, a new file; 1.0.0 is
  untouched): 18 cases. Under the candidate, 10 end where it says; the 8 that do not are exactly
  the cases it marks as known limitations
  (`benchmarks/root_cause_benchmark_report_1.1.0_candidate.md`, checked by
  `tests/e2e/test_sp_candidate_declarations_postgres.py`).
- Control: under 1.0.0, mesh-coarse-access still confirms a mesh artifact; the change is the
  declarations' alone.
- SQL and the loop agree on every episode (the harness's differential check), and SQL's warrant
  function reads each withdrawn link as no DOMAIN warrant (read directly).
- Mutation battery: 8/8 entries for `012t` and the candidate killed.
- Independent science review (94 episodes, both versions): `reviews/01-independent-science-review-f150bc0.md`.

## Why not ready

From the review: the mesh withdrawal is incomplete (an observed UNSTABLE still holds every other
class back, whatever a person answers); `review_only` is keyed to the link rather than the evidence
source; and the candidate's escalation to a split lot when the probe station is closed is
unjustified. Size-, direction- and symptom-blind signatures remain in both versions. Each is listed
with its counterexample in the review and as a known-limitation case in benchmark 1.1.0.

## Decisions for the owner and a domain expert

1. Whether to pursue 1.1.0, and how to finish the mesh withdrawal (a measured/simulated field on
   the anomaly, or not counting an unwarranted review-only signature against other classes).
2. Scoping withdrawals by evidence family (design reading vs. measurement on fabricated devices).
3. Size- and direction-aware signatures (normalization, contact, dopant thresholds).
4. A temporary-resource model for a closed station, and a rule against an irreversible fabrication
   as the next step while a rival's check is only temporarily unavailable.
