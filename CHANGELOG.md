# Changelog

Implementation history of Laboratory Innovation Brain. Specification changes live in the
Version Notes table of `docs/spec/SAI_3.3.md`, not here.

## [Unreleased]

### M0a — Scientific Identity Foundation (in progress)

#### Added

- Repository skeleton per §18, scoped to what M0a needs — `learning/`, `interfaces/dashboard`,
  `integrations/lims` and other §18.1 exclusions are deliberately absent rather than stubbed.
- `lab_brain.spec`: machine-readable projection of the specification. Parses the §25.3
  requirement table, the §24.5 EXT-001 declaration and the §26 traceability matrix directly
  from the spec document, so the tables cannot drift from CI.
- `docs/normative_statements.yaml`: Normative Statement Registry (§23.6). 77 statements
  covering all 52 requirements; the first 17 entries transcribed verbatim from the §23.6
  excerpt.
- `docs/milestones.yaml`: §26.1 gate order plus a requirement-to-milestone allocation that
  partitions all 52 requirements exactly once.
- `T-SPEC-001` (TST-002) — 10 assertions: Requirement ID uniqueness and well-formedness, the
  self-asserted 52↔52 count invariant, every requirement has a test, no matrix row or test
  marker references an unknown ID, marker pairs exist in the matrix, and the milestone
  catalog partitions every requirement.
- `T-SPEC-002` (TST-003) — 9 assertions: registry key uniqueness, requirement/test
  resolvability, test-or-explicit-deferral, review dates on deferrals, agreement with the §26
  matrix, normative vocabulary, and a ratchet requiring real tests once a milestone is DONE.
- ADR-0001 … ADR-0009 recording the architecture decisions SAI 3.3 already fixed.
- `scripts/update_status.py`: derives the IMPLEMENTATION_STATUS.md requirement table from
  milestone allocation and test markers, with `--check` for CI (AGT-003).
- `compose.yaml` (PostgreSQL 17 + pgvector on host port 5433), `Makefile`, `scripts/dev.ps1`.

#### Notes

- A bare `pytest` run needs no PostgreSQL, no Lumerical seat and no network (AGT-007).
- Two spec observations logged for the M0a audit rather than silently resolved: the `GH-xxx`
  namespace is missing from the §23.2 table, and T-SPEC-002's "unique Requirement IDs" phrasing
  is violated by §23.6's own excerpt if read literally. Neither is a contradiction between
  normative contracts, so neither blocks the slice under AGT-015.
