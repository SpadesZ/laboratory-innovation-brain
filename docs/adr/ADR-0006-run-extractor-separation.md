# ADR-0006: `run_*` is backend-bound, `extract_*` is backend-agnostic

Status: Accepted
Date: 2026-09-12
Affected Requirements: SIM-001, DOM-SP-002, VER-002
Human Approval Required: No (records SAI 3.3 §10.2, §25.2, AGT-014)

## Context

If "run CHARGE and give me Rs" is one function, then Rs is defined by whatever CHARGE
returned. Two consequences follow. Simulated and measured Rs become incomparable, because
each carries its own private extraction convention. And the evaluator becomes editable by
whoever edits the runner — the corruption path P0 in the risk register is about.

## Constraints

- P26 Backend-agnostic metrics.
- AGT-014 / DOM-SP-002: the *same* extractor contract must accept simulation arrays and
  measurement arrays and produce comparable output with recorded normalisation provenance.
- P19 Typed tools only: no arbitrary `eval_script`.
- §10.2 tool classes: `run_*` (backend-bound) / `extract_*` (backend-agnostic) /
  `inspect_*` (reads without solving) / `validate_*` (returns `ValidationReport`).

## Options Considered

1. **Fused run-and-extract per backend** — fewest moving parts, and the only way to compare
   sim against measurement is a second, differently-written extractor.
2. **Shared extractor with a backend-specific fast path** — the fast path is where the two
   definitions silently diverge.
3. **Strict separation: `run_*` emits raw arrays + manifest; `extract_*` consumes arrays.**

## Decision

Option 3, with the four tool classes named above.

`run_*` produces raw arrays, a reproducibility manifest and a `BackendValidity` record —
never a metric. `extract_*` consumes arrays from *any* origin and records its normalisation
basis, units and method. `validate_*` returns a structured `ValidationReport` and is
explicitly forbidden from modifying raw evidence.

Consequently `extract_cj_rs` has no idea whether its input came from CHARGE or from a probe
station, which is exactly what makes the sim-to-real comparison meaningful.

## Consequences

- Positive: sim-to-real conflict becomes a detectable, typed `Conflict` instead of two
  incomparable numbers.
- Positive: the evaluator is immutable relative to the runner — an agent tuning a solver
  config cannot move the metric definition with it.
- Negative: an extra artifact hop (arrays land in the numerical store before extraction).
  Accepted: that artifact is the reproducibility evidence.
- Negative: extractors need their own fixtures for both array origins. That is `T-DOM-SP-002`.

## Migration / Rollback

Reversing this would merge the metric definition into each backend adapter and forfeit
sim-to-real comparability. Not planned.

## Tests / Evidence

- `T-DOM-SP-002`: one `extract_cj_rs` contract passes simulated and measured fixtures.
- `T-SIM-001`: a run manifest missing solver/project/conditions/validity is refused
  promotion to formal evidence.
