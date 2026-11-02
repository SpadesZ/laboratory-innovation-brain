# SAI 3.5 — Appendix H: Dependency-aware roadmap from the current G0 state to the complete product

Version: `3.5.0-master-candidate.1`. Status: **CANDIDATE — NOT ACTIVE.** `READY_FOR_REAL_RESEARCH = false`.
Authority: normative for phase prerequisites, exit evidence and Owner gates; informative for
ordering where no dependency is stated. No durations are given because none has been measured.
These phases change neither `docs/milestones.yaml` (M0a–M8), the SAI 3.4 profile milestones nor
G0–G9. Supersedes the `D0`…`D6` phases of the discovery candidate (see the
[change register](change-register.md)).

## 1. Starting point (2026-11-02)

- G0 is NOT PASSED. The G0 line (`f41758c`) is unintegrated and awaits the Independent Chief Auditor;
  its forged-authorization read-path bypass is fixed on the unmerged branch
  `g0-authorization-read-path-closure`, pending audit.
- The offline Discovery Loop (`118a4ac`) is unintegrated and not independently reviewed; its
  independent hidden-world evaluation is being designed on `discovery-independent-evaluation`.
- SAI 3.4 tracks P-G0 and P-MODEL may start (SAI 3.4 §2); P-LICENSED and P-PHYSICAL need their
  Owner decisions; nothing is licensed.

## 2. Phases

| Phase | Goal | Prerequisites | Exit evidence | Owner gates |
|---|---|---|---|---|
| P35-0 | Candidate review and integration plan | this candidate | Independent Chief Auditor review of SAI 3.5; Owner decisions OD-01 (candidate), OD-09 (integration order), OD-10 (SAI 3.4 boundary mechanism) | OD-01, OD-09, OD-10 |
| P35-1 | G0 closure on an integrated line (SAI 3.4 P-G0) | independent audit of the G0 line including the read-path fix; integration per OD-09 | the G0 blind evaluation run by an independent evaluator on the integrated line; G0 accepted by the Owner (SAI 3.4 G0-A/L/S/B/P) | G0 Owner decisions A–F on that line; SAI 3.4 D-07 for identity |
| P35-2 | Discovery records and the offline loop in the product, at zero cost | P35-0; integration of the reviewed discovery line (OD-09); development may start earlier, results before the G-D0 freeze are exploratory | migrations, ADRs and tests for the records of [Appendix C](records-and-states.md); the Discovery and Validation sides with separate identities; claim-state projection; FeedbackRecords; StopRecords; PostgreSQL suite and mutation entries in CI | OD-12 (reframing caps) |
| P35-3 | G-D0 freeze and G-D1 at zero cost | P35-2; evaluator, generator owner and custodian assigned; protocol values approved; local models declared free | G-D0 PASS (frozen protocol, sealed evaluator-generated hidden worlds, contamination report); arms A, B and C run; independent G-D1 verdict (PASS, FAIL or INVALID, reported whatever it is) | OD-02, OD-03, OD-04 |
| P35-4 | Envelope-bounded production workflow without external coding agents (before licensing) | P35-1 (G0 accepted for the configuration); P35-2 | ResearchEnvelope and automatic registration; autonomy levels AL1–AL3; Owner gates and stop; realized-cost governance; bilingual discovery reports and bundles; T-S35-AUTO-002 audit and T-S35-AUTO-001 check without licensed simulation | OD-14 (envelope and rule (l)), OD-15 (autonomy levels), OD-05 only if paid models are used |
| P35-5 | G-D2: retrospective held-out literature discovery | P35-3 (G-D0 for the literature benchmark); P35-4; G0 accepted for the configuration evaluated | sealed literature benchmark with contamination controls; local-model stage first; blinded expert review of novelty class and falsifiability; independent G-D2 verdict | OD-06; OD-05 if a paid stage is proposed; OD-11 |
| P35-6 | Pre-license physical model construction (SAI 3.4 P-MODEL) | P35-0; a named SAI 3.4 C34-A0 offline-slice approval; may run in parallel with P35-1 to P35-5 | PhysicalModelSpec, operation catalog, deterministic constructor, readback double, model qualification records, fake worker with fencing; G1 offline parts; T-S35-MOD-001/002/003 offline parts | SAI 3.4 D-01, D-03, D-05, D-06 (C34-A0 scope) |
| P35-7 | Licensed simulation (SAI 3.4 P-LICENSED) and G-D3 | P35-6; G-D2 PASS for G-D3 entry; SAI 3.4 D-02, D-04, D-05, D-06 | qualified CHARGE worker first, then MODE, FDTD, INTERCONNECT each qualified separately; G1, G2, G3, G7-SITE and licensed G8 for the model family; AL4 envelopes; evaluator-sealed simulation cases; independent G-D3 verdict | OD-07 and the SAI 3.4 license decisions |
| P35-8 | Physical validation (SAI 3.4 P-PHYSICAL) and G-D4 | P35-7; G-D3 PASS for the scope; SAI 3.4 D-02, D-03, D-08 | independent references; G4, G5, G6 and G9 for the scope; pre-registered physical experiments; confirmation through the Causal Warrant Gate; independent G-D4 verdict | OD-08 for each experiment and publication |
| P35-9 | Activation and runtime conformance of SAI 3.5 | P35-0; Independent Chief Auditor review; explicit Owner approval; may happen before or after the capability phases, but never turns a requirement's status into complete by itself | the steps of the [activation proposal](activation-proposal.md): registry migration with real test bindings, checker and ACTIVE_SPEC changes, status inventory | OD-16 |

## 3. Dependency picture

```text
P35-0 ──► P35-2 ──► P35-3 (G-D0, G-D1) ──► P35-5 (G-D2) ──► P35-7 (G-D3) ──► P35-8 (G-D4)
  │          │                                 ▲                ▲                ▲
  │          └──────► P35-4 (envelope, AUTO) ──┘                │                │
  ├──► P35-1 (G0 accepted) ──► P35-4, P35-5                     │                │
  ├──► P35-6 (P-MODEL, offline construction) ───────────────────┘                │
  │        SAI 3.4 P-LICENSED decisions ──► P35-7                                 │
  │        SAI 3.4 P-PHYSICAL decisions ─────────────────────────────────────────┘
  └──► P35-9 (activation; Independent Chief Auditor + Owner) — separate, optional timing
```

The complete product for a scope is reached at the end of P35-8 for that scope, together with the
Owner's readiness decision (SAI 3.5 §2.3).

## 4. Rules for every phase

- A phase is DONE only when its exit evidence exists and the right party accepts it: the Owner for
  decisions and acceptance, the independent evaluator for G-D verdicts, the Independent Chief
  Auditor for audits. A developer, a coding agent or CI cannot mark a phase DONE.
- A FAIL or INVALID verdict is a legitimate outcome. It is recorded; the next phase can be planned,
  but no claim can rest on the failed level.
- No phase relaxes an SAI 3.3 or SAI 3.4 condition, or a G0–G9 condition, to make progress. A
  conflict stops the slice (S35-GOV-001, AGT-015).
- Money, licenses, physical experiments and publication happen only after their Owner gate
  (S35-SEC-002).
- Each phase's requirements are those whose registry `phase` field names it
  ([traceability](traceability.md)).
