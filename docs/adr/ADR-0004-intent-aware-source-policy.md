# ADR-0004: Retrieval policy switches on research intent

Status: Accepted
Date: 2026-09-12
Affected Requirements: SRC-001, SRC-002
Human Approval Required: No (records SAI 3.3 §6.16, §7.5)

## Context

A single retrieval strategy tuned for "find evidence about X" is actively harmful for two
of the system's jobs. Diagnosis wants the closest comparable conditions. Novelty audit
wants the opposite: the strongest prior art that would make the idea unoriginal. An
adversarial critic wants the evidence that would *refute* the current position.

A retriever optimised for semantic similarity to the current hypothesis will, by
construction, return agreement. Running it for all three intents manufactures consensus and
calls it corroboration.

## Constraints

- P24 Intent-aware retrieval.
- SRC-002: when `decision.stakes >= policy threshold`, the Critic MUST perform inverted
  retrieval and persist the inverted `EvidenceBundle`, or the decision may not enter
  `BELIEF_REVISION`.
- SRC-001: all external access goes through `ExternalSourceAdapter` / `SourceRouter`;
  provider SDKs must not leak into cognition or domain code.

## Options Considered

1. **One retriever, prompt-level steering** — the retrieval set is identical, so the
   critic argues against a bundle that was selected to agree. Cheap and useless.
2. **Intent-parameterised `SourcePolicy` + a distinct inverted retriever.**

## Decision

Option 2. `SourcePolicy` is selected by `research_intent` (DIAGNOSIS, NOVELTY_AUDIT, ...) and
is versioned, because a bundle is only reproducible if the policy that produced it is
identifiable.

High-stakes decisions additionally require a separate inverted retrieval pass whose bundle
is persisted as `CritiqueReport.inverted_bundle_id`. Bundle divergence between the primary
and inverted bundles is measurable, which is what makes "the critic actually looked
elsewhere" an assertion rather than a hope.

## Consequences

- Positive: "did the critic see disconfirming evidence" is answerable from stored bundle IDs.
- Positive: swapping a provider is an adapter change; cognition source is untouched.
- Negative: high-stakes decisions cost at least two retrieval passes. That is the intended
  price — §9 charges cost explicitly rather than hiding it.
- Negative: more policy versions to maintain. Mitigated by versioning them as data, not code.

## Migration / Rollback

`SourcePolicy` is configuration (`configs/source_policies.yaml`). Adding or retiring an
intent is a config + migration change, not a code change.

## Tests / Evidence

- `T-SRC-001`: replacing real providers with fakes requires no SourceRouter/cognition edits.
- `T-SRC-002`: DIAGNOSIS and NOVELTY use different policies; a high-stakes decision without
  inverted retrieval is refused entry to `BELIEF_REVISION`.
