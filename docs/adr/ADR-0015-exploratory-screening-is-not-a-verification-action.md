# ADR-0015: An exploratory screening reading is not a verification action (SPEC-ISSUE-016, Reading B)

Status: Accepted
Date: 2026-10-27
Affected Requirements: VER-001, VER-002, VER-006 (unchanged); §9.1, §25.4 (read, not amended)
Human Approval Required: Yes -- given (see Approval)

## Approval

The Owner's instruction, verbatim, in the G0 Exploratory Screening V2 closure request of
2026-10-27: "Resolve SPEC-ISSUE-016 using Reading B. Record the Owner's approval in an auditable
decision record. Preserve SAI 3.3's locked requirements and existing scientific authority." The
same request: "Keep screening disabled for production use until its updated contract and tests
pass." This record is that decision; nothing here widens it.

## Context

`docs/spec_issues/SPEC-ISSUE-016-exploratory-screening.md`. §9.1 / `VER-001` require every
VERIFICATION action to carry a predicted discriminatory outcome; §25.4 asks the planner to try
cheap checks (connectivity, extraction consistency) first. Neither says whether a low-cost reading
of an observable no hypothesis predicts may run at all. A live Gemini run showed the consequence of
"no": an open via was never inspected because no hypothesis predicted connectivity.

## Options Considered

- Reading A: every execution of a verification capability is a verification action, so an
  unpredicted reading violates VER-001 and may not run. Cost: the platform cannot discover a
  defect the evidence does not hint at, even when a seconds-long local check would show it.
- Reading B: VER-001 governs the planner's choice of the next verification action. A reading taken
  under a separate, versioned screening policy, recorded as its own operation, instantiating no
  relation and supporting nothing, is not a verification action. Cost: a second kind of execution
  to govern, and the risk of post-hoc hypotheses -- addressed by the contract below.

## Decision

Reading B. The screening contract, as implemented on `g0-exploratory-screening-v2`:

1. A screening reading is a `ScreeningObservation` under a `ScreeningPlan` (`012y`), never a
   `VerificationPlan`; `011k`'s VER-001 trigger is unchanged and still refuses any plan that
   chooses an unpredicted action.
2. Only registered, AVAILABLE capabilities of the cheapest action tiers, declared screenable by
   their DomainPack with a reference outcome and `LOCAL_NO_EGRESS` execution, needing no person,
   money, licence seat or irreversible step, with a workflow and their inputs on hand, are eligible;
   eligibility is checked again immediately before execution and fails closed.
3. A reading instantiates no relation. A hypothesis proposed after viewing it is recorded as
   conditioned; SQL refuses any SUPPORTS relation to it from the reading, from an older observation
   or from a deterministic repeat of the reading. Verification does not repeat a screened reading
   of the same input.
4. TransitionPolicy, the Causal Warrant Gate, signed review and authority comparison are
   unchanged. A screening reading can only stop a confirmation, never cause one.

SAI 3.3's locked registry, requirement count, Test IDs and milestones are NOT amended. The
proposed statement `VER-009` (SPEC-ISSUE-016) is recorded here as the contract's wording; adding
it to a registry is a separate maintainer action under the SAI 3.4 activation profile
(P-FULL-RUNTIME), not part of this decision.

Production stays off: `ResearchFeatures.exploratory_screening` defaults to False, and the web
workspace and the command line enable nothing on their own. Turning it on for real research is a
later Owner decision, after this contract's tests pass in CI.

## Consequences

- Positive: a cheap, local, outcome-independent look where nobody looked is possible and fully
  recorded; normal readings are kept.
- Negative: a mechanism proposed after screening can be confirmed only by a different, prospective
  check or a person; in VS-SP-001 the only cheap check for an open via is the one already read, so
  such mechanisms wait for a person or a measurement.
- Reading B is a reading of SAI 3.3, not an amendment; a future maintainer ruling that contradicts
  it supersedes this ADR, and the feature flag removes the stage.

## Migration / Rollback

Rollback: keep `exploratory_screening=False` (the default). `012y`/`012z` tables stay as an
append-only record; nothing reads them when screening is off.

## Tests / Evidence

`tests/unit/test_g0_exploratory_screening.py`, `tests/unit/test_g0_screening_closure.py`,
`tests/e2e/test_g0_exploratory_screening_postgres.py`, `tests/e2e/test_g0_screening_matrix_postgres.py`,
the screening probe in `tests/integration/test_role_qualification_postgres.py` / probe suite, and the
`scripts/mutation_battery.py` entries named `screening_*`, `sql_*screen*`.
