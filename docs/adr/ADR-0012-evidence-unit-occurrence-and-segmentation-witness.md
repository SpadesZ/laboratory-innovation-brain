# ADR-0012: EvidenceUnit is global; presence is an occurrence; conformance is re-derived, not attested

Status: Accepted
Date: 2026-09-21
Affected Requirements: EVI-010, EVI-003, SEC-002, EVI-004
Spec amendment: `v3.3-a18` (§17.25 revised, §17.25.1 added, §17.2 `evidence_unit_id?` added)
Spec issues: `SPEC-ISSUE-014`, `SPEC-ISSUE-015`
Human Approval Required: Yes — P0 scientific and security semantics; granted by the ruling
recorded in `v3.3-a18`

## Context

`v3.3-a17` and ADR-0011 established the canonical-evidence / retrieval-representation split. The
M1-P1 audit found that the canonical half was itself two objects wearing one row, and that its
central rule was enforced only against writers who volunteered to be checked. Both were
reproduced against PostgreSQL before anything was changed.

**One.** `EvidenceUnit` carried `project_id` while its identity was derived from
`(artifact_id, structural_path, content_digest)` — project-independent. With `evidence_unit_id` as
the primary key, the same document present in two projects collides on the second insert. The
visible symptom is a `UniqueViolation`; the real one is that the first project to ingest a
document owns its evidence, and the second gets a readable artifact with no evidence at all.

**Two.** §6.22 rule 1 was enforced by a trigger that fires only when a unit *declares* a bound
condition. Omit the declaration and the guard never runs. A raw `INSERT` of a severed result with
`bound_condition_texts` left empty produced a fully conformant canonical evidence unit whose
interpreting condition existed nowhere — the exact failure §6.22 opens by describing, and the one
with no downstream symptom because no field is missing.

## Decision

### 1. Global identity, project-scoped presence — ADR-0010, one layer down

| | Scope | Identity | Carries |
|---|---|---|---|
| `EvidenceUnit` | global | `evidence_unit_id` = f(`artifact_id`, `structural_path`, `content_digest`) | the canonical body, locator, contexts, bindings, segmenter provenance |
| `EvidenceUnitOccurrence` | per project | **`(evidence_unit_id, project_id)`** | presence, who ingested it, when |

One canonical body, N presences. An evidence unit with no occurrence in a project is **not
present** there and must not be retrievable or admissible there, however well cleared the
requester is elsewhere.

The identity derivation is **unchanged**. That is the point: the fix had to make project scope
representable *without* touching scientific identity, because making identity project-scoped is
the alternative ADR-0010 already rejected for `Artifact` — it would turn one measurement cited by
two projects into two independent supports and corrupt `EVI-004` counting.

### 2. Segmentation conformance is re-derived, not attested — `v3.3-a13`, applied to segmentation

Two layers, each where it can actually be enforced:

```
storage-checkable   segmentation_witness = SHA-256 over the unit's conformance-relevant
                    canonical bytes. PostgreSQL recomputes and compares -- a byte operation.
                    Refuses a row whose witness does not bind its contents.

semantic            scientific admission re-runs the recorded parser and segmenter over the
                    Artifact's content-addressed bytes and requires the unit to be among what
                    segmentation produces. Fails closed when the bytes cannot be loaded.
```

**The first layer does not stop a complete forgery and is not claimed to.** Anyone who knows the
algorithm can compute a consistent witness. Its value is exactly `input_hash`'s in `v3.3-a12`: it
lets the store cheaply reject a *partial* forgery — body edited, witness left behind — without
re-serializing or agreeing with the writer about field order.

**The second layer is what closes the hole.** The artifact is content-addressed, so its bytes are
pinned; the segmenter is deterministic and its version is on the row; therefore "what would
segmentation produce here" is computable at admission time, and a severed unit is not among the
answers. Nothing has to understand what the text says.

## Alternatives considered

**Put `project_id` into the identity derivation.** Rejected — see above, and ADR-0010's identical
rejection for `Artifact`. It also contradicts `v3.3-a17`'s clause fixing identity at three inputs,
pinned by `test_identity_does_not_depend_on_any_retrieval_parameter`.

**Composite primary key `(evidence_unit_id, project_id)`.** One line of DDL, and it stores the
canonical body once per project. "The canonical body" stops being singular, and two rows with one
identity can diverge under a repair script or a partial migration while each stays internally
consistent. EVI-010's guarantee is *resolve by identity, get the body*; this would make it
*resolve by identity and project, get a body*.

**Make `bound_condition_texts` NOT NULL and non-empty.** Rejected: it forces a declaration on
units that genuinely have no bound condition (tables, code blocks, unconditioned statements), so
producers write placeholders and the field stops meaning anything — and a forger simply declares a
condition the severed body happens to contain.

**Teach the trigger to recognise result-prose lacking a condition.** Natural language in SQL, a
second implementation of the binder, and the two drift. This is what `v3.3-a13` refused for
`evaluate`, and the same sentence applies with `bind_condition_result_groups` substituted.

**Rely on database write permissions.** `011a`, `011c`, `011d` and `011g` each had to write down
that a guard only reached by a cooperative caller is a guard nothing holds. This would be the
fifth instance.

## Consequences

- **`EvidenceUnit.project_id` is dropped, not made nullable** — the ADR-0010 reasoning verbatim: a
  column that still exists will be read, and a stale project on the identity row is worse than
  none because it looks authoritative. `003b` backfills every existing unit into one occurrence
  and then drops the column, so the old read is a hard error rather than a wrong answer.
- **Admission re-parses the artifact.** Sub-millisecond on the locked fixture, not free on a large
  document, and per admission. Scoped to scientific admission (rare) rather than retrieval
  (not rare). If it must get cheaper the answer is a verified cache keyed on
  `(artifact_id, parser_version, segmenter_version)` — **not** trusting the witness alone, which
  would delete layer two and restore `SPEC-ISSUE-015`.
- **`Attestation.evidence_unit_id` becomes a durable field.** §17.25 already required the
  reference; M1-P1 implemented it only as an admission-call parameter, so a reloaded attestation
  could not say which evidence it read. It is nullable because §17.2's one-source rule is
  unchanged and an attestation may cite a run or a work rather than a document unit.
- **Retrieval scope moves to the occurrence.** `RetrievalRepresentation.project_id` stays — an
  index is legitimately project-scoped — but it is no longer the only thing standing between a
  cross-project unit and a caller, because the occurrence is now the authority on presence.
- **Per-project divergence of the same evidence stays unrepresentable, deliberately.** Redaction
  produces different bytes, hence a different Artifact, hence different units. If a future
  requirement needs one work to appear differently per project without differing bytes, that is a
  new object and a new ruling.
