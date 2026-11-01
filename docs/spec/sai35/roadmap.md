# SAI 3.5 Discovery Candidate — Roadmap

Version: `3.5.0-discovery-candidate.1`.
Status: **CANDIDATE — NOT ACTIVE.** These phases are proposals. None has started under this
candidate, and none changes `docs/milestones.yaml` (M0a–M8), the SAI 3.4 profile milestones or the
G0–G9 gates. No durations are given because none has been measured.

## 1. Phases

Phase IDs `D0`…`D6` are SAI 3.5 roadmap phases. They are not SAI 3.4 Owner decisions (`D-01`–`D-08`)
and not SAI 3.5 requirements (`D-001`…).

| Phase | Goal | Depends on (SAI 3.4 / G0–G9 / SAI 3.5) | Acceptance (exit evidence) | Owner gates |
|---|---|---|---|---|
| D0 | Candidate review and G-D0 protocol freeze | SAI 3.4 P0-BASIS (in force on this line); nothing licensed; independent of P-G0 and P-MODEL | Owner decision on the candidate (OD-01); evaluator and custodian assigned (OD-02); protocol values approved (OD-03); synthetic benchmark sealed; G-D0 PASS by the evaluator | OD-01, OD-02, OD-03, OD-04 |
| D1 | Offline Discovery Loop v0 and G-D1 at zero cost | D0 for any scored claim; development can start earlier, but results before the freeze are exploratory; no license, no paid API | the Discovery Loop records of SAI 3.5 §3 work offline in synthetic worlds; arms A, B and C run under the matched-budget protocol; independent G-D1 verdict (PASS, FAIL or INVALID, reported whatever it is) | OD-04 (local models declared free); no money |
| D2 | Integrate the Discovery Loop into the governed product | an integration decision for the G0 line and the SAI 3.4 line (OD-09); SAI 3.4 activation-checker scope (OD-10); D1 reviewed | persistent records with ADRs and migrations; epistemic-state projection (D-027); bilingual discovery reports (D-014); project isolation tests; PostgreSQL suite in CI; no G-D level passes by integration alone | OD-09, OD-10 |
| D3 | Retrospective held-out literature discovery (G-D2) | D2; G0 accepted for the product configuration (P-G0 acceptance); literature case rights (OD-06) | sealed literature benchmark with contamination controls; local-model stage first; blinded expert review; independent G-D2 verdict | OD-06; OD-05 only if a paid model stage is proposed |
| D4 | Prospective simulation discovery (G-D3) | D3; SAI 3.4 P-LICENSED (SAI 3.4 D-02, D-04, D-05, D-06); for the model family G1, G2, G3, G7-SITE and licensed G8 accepted | evaluator-sealed licensed simulation cases on internal workers; convergence evidence for each discriminating observable; independent G-D3 verdict | OD-07, plus the SAI 3.4 license decisions |
| D5 | Prospective physical discovery (G-D4) | D4; SAI 3.4 P-PHYSICAL (SAI 3.4 D-02, D-03, D-08); G4, G5 and G6 for the scope | pre-registered predictions before fabrication or measurement; independent measurements; confirmation through the Causal Warrant Gate; independent G-D4 verdict | OD-08 for each experiment and for any publication |
| D6 | Activation and runtime conformance of SAI 3.5 (optional) | an Owner decision to activate; ADR-0016 accepted; a migration path like SAI 3.4 P-FULL-RUNTIME | D-NNN migrated into the active registry with real tests; checkers and status inventory updated; full CI | Owner activation decision |

## 2. Dependency picture

```text
SAI 3.4 P0-BASIS ──► D0 ──► D1 ──────────────► D2 ──► D3 ──► D4 ──► D5
                              (zero cost)       ▲      ▲      ▲      ▲
G0 line integration (OD-09) ────────────────────┘      │      │      │
P-G0 acceptance (G0) ──────────────────────────────────┘      │      │
P-LICENSED + G1/G2/G3/G7-SITE/G8 ──────────────────────────────┘      │
P-PHYSICAL + G4/G5/G6 ─────────────────────────────────────────────────┘
D6 (activation) is separate and optional at any point after D2.
```

## 3. Rules for every phase

- A phase is DONE only when its exit evidence exists and the right party accepts it: the Owner for
  decisions, the independent evaluator for G-D verdicts. A developer, a coding agent or CI cannot
  mark a phase DONE.
- A FAIL or INVALID verdict is a legitimate outcome. It is recorded. The next phase can still be
  planned, but no claim can rest on the failed level.
- No phase relaxes an SAI 3.4 or G0–G9 condition to make progress. A conflict stops the slice
  (D-001, AGT-015).
- Licensed, paid and physical work happens only after its Owner gate (D-030).
