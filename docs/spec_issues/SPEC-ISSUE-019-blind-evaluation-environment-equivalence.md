# SPEC-ISSUE-019: which environment differences make a blind evaluation a different experiment

Severity: GATE
Status: OPEN
Blocks gate: M4
Raised: 2026-11-01
Raised by: G0 reliability closure (`g0-reliability-authenticity-closure`), blind-evaluation freezing audit
Affected: G0 acceptance (SAI 3.4 G0), `docs/evaluation/G0-blind-evaluation-protocol.zh-TW.md`, `lab_brain.evaluation.environment`, `lab_brain.evaluation.runner`

## The gap

The blind-evaluation protocol asks for a reproducible run, but no normative text says which
differences between the recorded environment and the environment that ran invalidate a score. The
closure now pins, and `verify` reports, every field it records: commit, clean tree, migration
files and the migrations applied to the database, libraries, Python, scorer, model id, digest and
digest source (served or declared), endpoint, LAB_BRAIN_* settings (secrets only as set) and
platform. The runner refuses to start on any difference and the scorer refuses a run whose
environment changed while it ran.

That is the strictest reading. Some fields may be harmless (a different patch version of an
unrelated library, a different machine architecture for a deterministic scorer); others are not
observable at all (the weights behind a model whose server reports no digest).

## Competing readings

- Reading A: any recorded difference invalidates the run (implemented).
- Reading B: an Owner-approved list of fields may differ, each with a stated reason, recorded with
  the score.
- Reading C: as A, and a model whose digest is only declared (not served) may not be used for a
  G0 acceptance run at all.

## Follow-up (2026-11-02)

An ACCEPTANCE score now requires the runner's before/after check and the evaluator's own
verification record (no difference, clean tree, served model digest). A DIAGNOSTIC score says it
is not an acceptance result. The served-digest requirement for acceptance applies reading C
provisionally.

## What needs an Owner / maintainer decision

1. Accept A, or define the B list.
2. Whether a declared-only model digest is acceptable for an acceptance run (C).
3. Whether the evaluator must pass `--database-url` (the applied-schema pin) for every run.
4. Whether an acceptance verification must be signed with an enrolled evaluator key (today the
   verifier's id is asserted).
