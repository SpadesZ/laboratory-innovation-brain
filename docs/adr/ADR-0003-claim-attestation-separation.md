# ADR-0003: Claim, Observation and Attestation are separate objects

Status: Accepted
Date: 2026-09-12
Affected Requirements: SYS-001, EVI-003, EVI-004
Human Approval Required: Yes — P0 scientific semantics (granted via SAI 3.3 §6.2, §17.2)

## Context

The natural RAG-shaped model is "evidence = a number found in a paper". Under that model,
one measurement cited by five papers produces five evidence rows. Every corroboration
count downstream then reads "five independent supports" for what is actually one
measurement transitively quoted four times.

This is not a rounding error. It biases *every* belief update in the same direction —
toward whatever is most frequently cited — and it does so invisibly, because each
individual row is factually correct.

## Constraints

- P22 Claim identity before corroboration.
- §6.2: `Claim` (proposition identity) / `Observation` (internal backend fact, wired
  directly to Run/Artifact) / `Attestation` (a named source's witness at a locator under
  conditions) are three distinct objects.
- EVI-004: same underlying work must resolve through Claim/SourceWork resolution;
  corroboration must not double-count.
- §17.2: `Attestation` carries no `support_targets[]` / `contradict_targets[]`.

## Options Considered

1. **Flat evidence rows** — one table, simple queries, systematically corrupt counting.
2. **Evidence rows + a dedup pass at read time** — pushes identity resolution into every
   consumer. The first consumer that forgets it reintroduces the bug silently.
3. **Three objects with identity resolved at write time.**

## Decision

Option 3.

- `Claim` is proposition identity. Five papers citing one result attest to *one* Claim.
- `Observation` is an internal backend fact. Per §17.2.1 it does **not** need a
  self-Attestation to exist; it is wired straight to Run/Artifact.
- `Attestation` is a named external witness. When an internal result is later written up in
  a paper, that produces a SourceWork/Attestation describing *how the document reports it* —
  which keeps the observation distinct from the document reporting it.

Support and contradiction are expressed **only** as `RelationJudgment`. No entity carries a
parallel array of what supports it.

## Consequences

- Positive: `min_independent_attestations` is computable, because independence is a property
  of resolved works rather than of row counts.
- Positive: the preprint/journal/mirror case has one correct answer instead of a heuristic.
- Negative: ingestion must resolve SourceWork and Claim identity before writing, which is
  more work per document and can fail. That failure is surfaced as `NEEDS_REVIEW` rather
  than guessed — the whole point.
- Negative: "how many sources support X" is a join, not a column read.
- v3.3 models WORK-level independence only. GROUP / SAMPLE / INSTRUMENT / METHOD correlation
  is deferred (§6.17); a policy demanding a stronger basis must escalate to human review
  rather than pretend the basis is satisfied.

## Migration / Rollback

Collapsing back to flat evidence would require discarding claim identity, which destroys
the ability to recompute corroboration. Effectively irreversible.

## Tests / Evidence

- `T-EVI-004`: preprint + journal + review fixtures resolve to one SourceWork;
  `DEPENDENCE_UNKNOWN` contributes 0 to the independent count until resolved.
- `T-SYS-001`: static test rejects `support_targets` / `evidence_for` style arrays.
