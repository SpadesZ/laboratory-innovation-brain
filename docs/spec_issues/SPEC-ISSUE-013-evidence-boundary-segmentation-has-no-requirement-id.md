# SPEC-ISSUE-013: the evidence boundary a retrieval chunk may not cross has no Requirement ID

Severity: GATE
Status: RESOLVED
Blocks gate: M1
Raised: 2026-09-20
Raised by: M1-P1 implementation slice (Research Memory ingestion / evidence foundation)
Resolved: 2026-09-20
Resolved by: `v3.3-a17` (maintainer ruling: adopt `EVI-010` / `T-EVI-010`)
Affected: §6.7, §6.8, §6.13, §6.20, §17.9, §17.22, §25.3 `EVI-002`/`EVI-007`, §26 `T-EVI-007`,
          §23.4 (the "Database implementation" row)

## The obligation nobody owns

A scientific document has to be cut into pieces before any of it can be retrieved. Where the cuts
fall decides what the system is later able to believe, because the smallest unit that can honestly
support a claim is *the result together with the conditions that make it interpretable*. Split

```
Reverse bias increased from 0 to -2 V.
The junction capacitance decreased from 0.515 to 0.345 pF/mm.
```

into two units and each half is still true, still attributable, still perfectly well-formed — and
the measurement has lost the only thing that made it a measurement of anything. Nothing in the
retrieval path afterwards can detect that, because there is no missing field to notice: the
conditions were not dropped, they were filed separately.

This is a hard obligation in substance. It is not one in the document.

## The gap, stated against the artifacts CI actually reads

**§6.7 is the only place the spec discusses it, and it is SHOULD-level.**

```
Layout-aware parsing：claim 與其 supporting table / figure / caption 不應被切散。
```

`不應` is §0.2's SHOULD-NOT. The M0a coverage audit records the consequence without editorial
comment:

```yaml
- section: '6.7'
  hard_must: 0
  basis: SHOULD only (layout-aware parsing)
```

and `docs/normative_statements.yaml` has **no entry at §6.7 at all** — not a deferred one, not a
SHOULD-level one. It is the only substantive subsection of §6 in that position. Under §23.5 that is
legal: a SHOULD is normative and deviating from it is ADR-worthy, but it is not a hard MUST and
`T-SPEC-002` has nothing to check. So the statement is real, unregistered, untested, and owned by
no Requirement ID.

**The neighbouring requirements stop short of it, in both directions.**

| Requirement | What it governs | Where it stops |
|---|---|---|
| `EVI-002` | a missing field is `UNKNOWN`/`NOT_REPORTED`, never a guessed value | says nothing about a field that is *present* but severed from its result |
| `EVI-005` | the record carries `conditions_schema_version`; `ConditionMatch` is versioned | governs the schema of conditions, not whether they stayed attached |
| `EVI-006` | the bundle hash is canonical over ordered attestation IDs | hashes whatever it is given; a bundle of mis-cut units hashes just as deterministically |
| `EVI-007` | vector retrieval filters by `embedding_model` + version; dual-index cutover | governs *which* vector space is compared, never what a vector is allowed to be |
| `EVI-009` | `MEASURED`/`SIMULATED` reference their Run/Artifact at admission | governs the reference, not the body the reference points at |

`EVI-007` is the closest and the most instructive. §6.13 and §6.20 are precise about embedding
version compatibility and completely silent about the status of the chunk itself. A system can
satisfy every clause of `EVI-007` — never mix spaces, dual-index the migration, answer "which
version retrieved this" — while treating the retrieved vector payload as the evidence body. The
requirement is about hygiene *between* indexes, not about what an index may claim to be.

**§17.22 names the stages and constrains none of their output.**

```
stage,  # SECRET_SCAN | RAW_STORE | PARSE_TEXT | PARSE_TABLE
        # | PARSE_FIGURE | CLAIM_EXTRACT | EMBED | INDEX
```

`PARSE_TABLE` and `PARSE_FIGURE` exist as distinct stages, which is evidence the spec intends
tables and figures to survive as structures rather than as flattened prose. It never says so. A
`PARSE_TABLE` stage that emitted a header-less run of numbers would report `SUCCEEDED` and be
conformant.

**§23.4 forbids the outcome but assigns it to nobody.**

The Human Steering Points table already names this exact failure as something an agent may not do
on its own authority:

| Human 決策點 | Agent 可自行做 | Agent 不可自行做 |
|---|---|---|
| Database implementation | index、query optimization、repository code | **把 Evidence semantics 改成單純 vector chunk；移除 provenance** |

That is the prohibition. It sits in the Agent Implementation Protocol, where it binds the agent's
conduct, and there is no Requirement/Test pair that makes a *system* which does it fail CI. §23.4
is a rule about who decides; §25.3 is where a rule about what the software must do would live.

## Why this cannot be implemented on a provisional reading

M1's first slice has to choose a segmentation strategy, and the two candidates are not a
refactoring apart:

```
fixed-token-primary   cut every N tokens, overlap by M, let ranking sort it out
structure-first       cut on document structure, subdivide only when a valid unit is oversized
```

An implementation of the first can score arbitrarily well on ordinary retrieval metrics while
being exactly what §23.4 prohibits, and — this is the part that makes it a gate issue rather than a
preference — **a benchmark cannot distinguish them unless the benchmark is written to.** Recall and
precision over a corpus of well-formed questions are largely insensitive to whether conditions
travelled with their result, because the retriever usually surfaces the neighbouring chunk too. The
failure appears later, in the belief path, as a corroboration that was never valid.

So "pick the better-scoring one" is not available as a tiebreak. Whether evidence-boundary
preservation is an obligation or an optimisation determines what the benchmark is even measuring,
and that is a scientific-semantics decision reserved to the maintainer by §23.4 and by AGT-015.

## Readings

**Reading A — it stays a SHOULD.** §6.7 already says it; an implementation that violates it is
deviating from a SHOULD and owes an ADR under AGT-005. *Against:* nothing detects the deviation. An
ADR is owed by an agent that knows it deviated; fixed-token splitting is the default behaviour of
every retrieval library, so the deviation arrives without anyone deciding on it. A SHOULD whose
breach is invisible is not a weaker rule, it is not a rule.

**Reading B — fold it into `EVI-007`.** Both concern retrieval representation, and `EVI-007` is
already M1. *Against:* `T-EVI-007`'s pass condition is entirely about mixed embedding versions and
dual-index cutover. Adding segmentation to it would give one Test ID two unrelated failure modes,
and the §26 row could pass on the embedding half while the segmentation half was never exercised —
the shape `v3.3-a6` refused when it declined to read §14.3's artifact-reference obligation into
`EPI-002`.

**Reading C — fold it into `EVI-002`.** Both are about not inventing scientific content.
*Against:* `EVI-002` governs the *absence* of a value. Severing a condition from its result invents
nothing and omits nothing; every field is present and correctly statused. `EVI-002`'s test cannot
be extended to catch it without changing what `EVI-002` means.

**Reading D — a new Requirement/Test pair.** Moves the invariant to 60 ↔ 60. *Against:* the count
is load-bearing and every previous move was a maintainer ruling. That is an argument for escalating,
which is this document, not an argument against the reading.

## Proposed wording (Reading D, if the maintainer agrees)

A new §6.22 stating the obligation in the normative-architecture chapter where §6.7's SHOULD
already lives, and a §17 contract giving the two objects that must not be confused:

```
Segmentation MUST preserve the Minimum Evidence Boundary: the smallest complete unit
that can independently support a scientific claim, observation or measurement while
retaining the conditions required to interpret it.

Segmentation MUST be structure-first. Fixed-token splitting MUST NOT be the primary
splitter; it is permitted only to subdivide a single valid evidence unit that exceeds a
declared limit, or as an explicit benchmark baseline.

A vector or index chunk is NOT evidence identity and is NOT the canonical evidence body.
Candidate retrieval MAY use vectors; scientific evidence admission and EvidenceBundle
construction MUST resolve back to canonical evidence records and continue through the
applicable condition, source, independence and authority filters. A retrieved payload
MUST NOT become an Attestation by virtue of having been retrieved.
```

with `EVI-010` / `T-EVI-010` allocated to M1, and `T-EVI-010`'s pass condition written as a fixed
benchmark fixture with per-case expected outcomes rather than a corpus-level score threshold — for
the reason above, a threshold is the one thing that cannot separate the two strategies.

## Resolution

The maintainer adopted **Reading D**. `v3.3-a17` adds §6.22 and §17.25, adds `EVI-010` to §25.3 and
`T-EVI-010` to §26, allocates `EVI-010` to M1, and moves the invariant **59 ↔ 59 → 60 ↔ 60**.

Three parts of the ruling are worth recording because they are what keeps it narrow:

- **§6.7's SHOULD is not deleted or promoted in place.** It remains the layout-aware-parsing
  guidance it always was. §6.22 states the hard obligation beside it, so the audit trail shows a
  new statement rather than a silently strengthened old one, and `M0a_obligation_inventory.yaml`
  gains rows that name it.
- **The benchmark's pass condition is per-case, not a threshold.** §26's row fixes the expected
  outcome for each fixture case and requires the fixed-token baseline to be reported alongside. A
  fixed-token-primary implementation that happens to score well is non-conformant by construction,
  which is precisely what a threshold could not express.
- **The identity boundary is a contract, not a naming convention.** §17.25 states that the canonical
  evidence unit's identity is independent of embedding model, version, dimensionality, reranker and
  token-window strategy, so deleting and rebuilding an index cannot change scientific evidence
  identity and changing an embedding model cannot rewrite an Attestation. Without that clause
  `EVI-010` would be a style rule; with it, `EVI-007`'s future dual-index migration has something
  it is forbidden from disturbing.

## Alternatives considered and rejected

- **Promote §6.7's `不應` to `必須` and register it under a new statement key with no new
  Requirement ID.** This was the cheapest option and it fails on ownership: `check_registry_*`
  requires every statement to name exactly one Requirement ID, and none of the existing ones can
  take it without the Reading B / Reading C objections above.
- **Leave it to M2's DomainPack.** Table and figure structure is not silicon-photonics-specific, and
  §24.1 puts Artifact/Claim/Observation/Attestation in the core column. A DomainPack that had to
  re-decide where evidence boundaries fall would be re-deciding it per domain, which is the
  extension-boundary failure `EXT-001` exists to detect.
- **Defer to `EVI-008`'s retraction/dedup gate.** Different object. `EVI-008` governs whether a
  *work* may support a revision; this governs whether the *unit* extracted from it was ever a
  coherent piece of evidence.
