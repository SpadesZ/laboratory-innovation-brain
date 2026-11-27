# ADR-0011: EvidenceUnit is canonical scientific identity; RetrievalRepresentation is a derived index artefact

Status: Accepted
Date: 2026-09-20
Affected Requirements: EVI-010, EVI-002, EVI-003, EVI-006, EVI-007, EVI-009, SEC-002
Spec amendment: `v3.3-a17` (§6.22 added, §17.25 added)
Spec issue: `SPEC-ISSUE-013`
Human Approval Required: Yes — P0 scientific semantics (§23.4 reserves "把 Evidence semantics 改成
單純 vector chunk" to the maintainer); granted by the ruling recorded in `v3.3-a17`

## Context

M1 is the first milestone in which a document is read, cut up and stored. Every retrieval system
built in the last few years answers "what is a chunk" the same way — a window of N tokens with M
tokens of overlap — and that answer is the default of every library one would reach for.

It is the wrong answer here, and the reason is not retrieval quality.

The smallest unit that can honestly support a scientific claim is the result **together with the
conditions that make it interpretable**. Cut

```
Reverse bias increased from 0 to -2 V.
The junction capacitance decreased from 0.515 to 0.345 pF/mm.
```

into two units and each half remains true, attributable, correctly statused and perfectly
well-formed. What has been lost is that the measurement was a measurement *of* anything. Nothing
downstream can detect it, because no field is missing — the conditions were not dropped, they were
filed separately. The corruption surfaces much later, as a corroboration that was never valid, and
by then the unit that caused it looks exactly like a good one.

The second half of the problem is what happens once vectors exist. A retrieved chunk arrives
carrying a body, a score and an apparent authority ("the index returned it, so it is what the
document says"). If that payload is allowed to *be* the evidence, then evidence identity silently
acquires a dependency on the embedding model, the reranker and the token window — and re-indexing
becomes an operation that edits science.

ADR-0010 is the same shape one layer down: one row conflating two different facts, where the
failure is not a missing check but an unanswerable question.

## Decision

Two objects, one reference.

| | Scope | Identity | Carries |
|---|---|---|---|
| `EvidenceUnit` | canonical, project-scoped | `(artifact_id, structural_path, content_digest)` | the evidence body, locator, structural path, conditions, field states, table/figure context, parser + segmenter provenance |
| `RetrievalRepresentation` | per index | `(evidence_unit_id, index_id)` | index kind, embedding model/version/dimensions, `payload_digest`, build time |

`RetrievalCandidate` carries an `evidence_unit_id` and a score. It does not carry a body.

Four consequences, each of which was a live temptation:

1. **Segmentation is structure-first, and fixed-token splitting is a fallback with a recorded
   reason.** Not a default with an escape hatch — the other way round. A unit produced by
   subdivision records `parent_unit_id`, `subdivision_index` and `subdivision_reason`, so "why is
   this cut here" is answerable from the row rather than from the segmenter's source.

2. **The canonical body is re-loaded by identity at admission, never taken from the candidate.**
   The retriever's output is a list of identifiers. `payload_digest` exists **not to be trusted but
   to make divergence detectable**: when the indexed text and the canonical body disagree, that is
   reported and the canonical body wins. A design where the candidate's body is used "because it is
   already in memory" is the whole failure mode, and it is cheaper, which is why it has to be
   structurally impossible rather than discouraged.

3. **`EvidenceUnit` holds no vector.** Vectors live only on `RetrievalRepresentation` and are
   retrieval provenance, not scientific provenance. Dropping every representation for an index must
   leave every `EvidenceUnit` byte-identical, and changing embedding model must not rewrite an
   `Attestation`.

4. **`EVI-007` is untouched and stays a separate rule.** It governs which embedding space may be
   compared with which; this governs whether a vector may be the evidence at all. An implementation
   can satisfy every clause of `EVI-007` — never mix spaces, dual-index the cutover, answer "which
   version retrieved this" — while treating the retrieved payload as the evidence body. Folding
   them together would give one Test ID two unrelated failure modes.

## Alternatives considered

**One `Chunk` object with an optional embedding.** Rejected, and it is the option the ecosystem
pushes towards. The moment the embedding is a nullable column on the evidence row, the row's
lifetime is coupled to the index's: re-embedding becomes an `UPDATE` on scientific data, and
"delete the index and rebuild it" becomes a destructive operation on evidence. It also makes the
wrong thing convenient — a retrieval result is already the evidence object, so admission has nothing
to re-resolve and the guard in (2) has nowhere to live.

**Fixed-token primary, with a post-hoc "did we split a condition" repair pass.** Rejected: the
repair pass needs to recognise that two units belong together, which is the same judgement the
segmenter declined to make, now made with less context and after the locator has been assigned. It
also fails silently in the one direction that matters — an unrecognised split is indistinguishable
from a document that genuinely said two unrelated things.

**Let a benchmark decide between structure-first and fixed-token.** Rejected, and this is why
`SPEC-ISSUE-013` was escalated rather than settled. Corpus-level recall and precision are largely
insensitive to whether conditions travelled with their result, because the retriever usually
surfaces the neighbouring chunk anyway. A threshold is the one form of pass condition that cannot
separate the two strategies, so `T-EVI-010` fixes the expected outcome **per case** and requires
the fixed-token baseline to be reported beside it.

**Defer the whole question to M2's DomainPack.** Rejected: table and figure structure is not
silicon-photonics-specific, §24.1 places Artifact/Claim/Observation/Attestation in the core column,
and a DomainPack re-deciding where evidence boundaries fall would be re-deciding it per domain —
the extension-boundary failure `EXT-001` exists to detect.

## Consequences

- A retrieval layer cannot be swapped in without passing through the admission seam. That is the
  point, and it costs one extra load per candidate at admission time. Measured against the
  alternative — an embedding upgrade that rewrites attestations — this is not a close trade.
- **Re-segmentation is not representable, and is stated rather than implied.** If the segmenter
  version changes, existing `EvidenceUnit` rows keep the boundaries the old version chose;
  `segmenter_id` / `segmenter_version` are recorded so affected units are *selectable*, by the same
  mechanism §6.18 uses to quarantine an extractor version. What does not exist yet is the
  re-segmentation path itself, because re-cutting evidence that Attestations already reference is a
  belief-affecting operation and belongs with the event infrastructure, not with a migration.
  Tracked as a known limitation in the M1-P1 readiness document.
- `EVI-007`'s future dense index plugs into the `RetrievalRepresentation` seam without touching
  `EvidenceUnit`. That is the property this split exists to buy, and it is the thing to check first
  if the seam is ever proposed to be simplified away.
- The `payload_digest` divergence check is a report, not a refusal. Refusing on divergence would
  make a stale index an outage; the canonical body already wins, so the remaining value is
  operational visibility.
