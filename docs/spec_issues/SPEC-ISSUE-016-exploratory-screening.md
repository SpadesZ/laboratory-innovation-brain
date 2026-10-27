# SPEC-ISSUE-016: an outcome-independent screening reading is neither permitted nor forbidden

Severity: GATE
Status: OPEN
Blocks gate:
Raised: 2026-10-27
Raised by: G0 exploratory screening slice (`g0-exploratory-screening`), Auditor decision "Option A"
Affected: §9.1, §25.4, `VER-001`, `VER-002`, `VER-006`, `011k`, SAI 3.4 G0-S, `012y`

## The gap

The live G0 retest showed a real model declining, on the evidence, to propose a mechanism for an
open contact via; no hypothesis predicted contact connectivity, so verification never ran the
seconds-long inspection that shows it. The Auditor's decision is a governed screening stage that
runs such low-cost readings when NO hypothesis predicts them.

SAI 3.3 has two statements that bear on this and neither settles it:

- §9.1 / `VER-001`: *下一個 verification action 必須有 predicted discriminatory outcome + estimated
  cost* and *If no ACTIVE hypothesis declares a Prediction over action.produces, the action is NOT
  sufficient. Absence of a declared prediction is not evidence of discriminative power.*
- §25.4 (VS-SP-001 Definition of Done): *Verification Planner 先檢查 historical case / connectivity /
  extraction consistency 等低成本動作，再在需要時升級 simulator.*

Reading A: every execution of a verification capability is a "verification action", so an
unpredicted screening reading violates `VER-001` and may not run.
Reading B: `VER-001` governs the planner's choice of the next VERIFICATION action; a reading taken
under a separate, declared screening policy, recorded as its own operation, that instantiates no
relation and supports nothing, is not a verification action and is not governed by §9.1's
sufficiency -- while §25.4 asks for exactly such cheap checks first.

## What this slice implemented (provisional reading B), and what it did NOT change

- Screening is its own typed, persisted operation (`ScreeningPlan`, `ScreeningObservation`,
  `012y`), NEVER a `VerificationPlan`: `011k`'s VER-001 trigger is untouched and no plan records an
  unpredicted choice.
- Screening readings are admitted as Observation + Attestation (EVI-003/EVI-009) with no relation;
  a hypothesis proposed after them is recorded as conditioned, and `012y` refuses any SUPPORTS
  relation to it from the reading, from an older observation, or from a deterministic repeat.
- Verification never repeats a screened reading of the same input.
- No TransitionPolicy, warrant rule, signed-review rule or authority comparator changed.

## Decision needed

The maintainer / Owner rules Reading A or B. If B, a registry entry (proposed `VER-009`, T-VER-009)
states: *A screening reading MAY execute a registered low-cost, local, available capability whose
produced observables no admitted hypothesis predicts, only under a versioned ScreeningPolicy, as an
operation distinct from VerificationPlan; it MUST NOT instantiate a relation, and a hypothesis
proposed after viewing it MUST NOT gain support from it or from a deterministic repeat of it.* If A,
the feature flag `ResearchFeatures.exploratory_screening` is turned off and the stage removed.

No milestone is named under "Blocks gate" because SAI 3.3's milestones do not include G0; under
SAI 3.4 this decision must be made before any G0 acceptance that relies on screening.
