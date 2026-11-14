# SPEC-ISSUE-014: the same evidence cannot exist in two projects at once

Severity: GATE
Status: RESOLVED
Blocks gate: M1
Raised: 2026-09-21
Raised by: M1-P1 audit (targeted repair), reproduced against PostgreSQL
Resolved: 2026-09-21
Resolved by: `v3.3-a18` (maintainer ruling: Reading C — the ADR-0010 split, one layer down)
Affected: §17.25, §17.1, §17.1.1, §6.22, `ART-001`, `SEC-002`, `EVI-004`, `EVI-010`, ADR-0010

## The contradiction, reproduced

§17.25 states both of these, and they cannot both hold:

```
EvidenceUnit { evidence_unit_id, project_id, artifact_id, ... }

evidence_unit_id 的 identity 由 (artifact_id, structural_path, content_digest) 決定
```

The identity derivation is **project-independent** — deliberately, and correctly. The row is
**project-scoped**. Migration `003a` therefore makes `evidence_unit_id` the PRIMARY KEY of a table
that also carries `project_id`, and the two facts collide the moment the same document is present
in two projects, which ADR-0010 exists precisely to permit:

```
insert into prj:a: OK
insert into prj:b: UniqueViolation   <-- project B cannot hold the same evidence
```

This is not a hypothetical. `artifact_occurrences` already allows one Artifact to be present in
many projects under different labels; the evidence extracted from it then cannot follow.

## Why it matters more than a failed INSERT

The failure mode is not "an error is raised". It is that **whichever project ingested the document
first owns its evidence**, and the second project's ingestion silently produces no evidence units
at all — the pipeline's `SEGMENT` stage succeeds, the rows fail, and the project ends up with an
artifact it can read and evidence it cannot.

That is the same shape as risk **R-7**, one layer down. R-7 was "`sensitivity_label` on the global
artifact row means *what is this labelled here* has no representation". This is "*which projects
hold this evidence* has no representation". In both cases the defect is not a missing check but an
unanswerable question.

## Readings

**Reading A — put `project_id` into the identity derivation.**
`evidence_unit_id = f(project_id, artifact_id, structural_path, content_digest)`. The collision
disappears; every project gets its own ids.

*Rejected.* It destroys the property the derivation exists for, and ADR-0010 already rejected the
identical move for `Artifact`: "the same measurement referenced from two projects would become two
artifacts, and every independence and corroboration calculation that depends on *same bytes, same
artifact* (EVI-004) would silently count one measurement twice." Evidence units inherit that
reasoning exactly — two projects citing the same sentence of the same paper are citing one piece of
evidence. It also contradicts `v3.3-a17`'s own clause that identity is fixed at three inputs, which
`test_identity_does_not_depend_on_any_retrieval_parameter` pins.

**Reading B — composite primary key `(evidence_unit_id, project_id)`, keeping the row as it is.**
Mechanically minimal: one line of DDL.

*Rejected.* It stores the canonical evidence body once per project. "The canonical body" then
stops being singular, and the guarantee EVI-010 rests on — resolve by identity, get *the* body —
becomes "resolve by identity and project, get *a* body". Two rows with one identity can diverge:
a repair script, a partial migration or a re-segmentation touching one project leaves two different
texts claiming to be the same evidence, and nothing detects it because each row is internally
consistent.

**Reading C — the ADR-0010 split: global identity, project-scoped presence.**
`evidence_units` holds the canonical body and drops `project_id`; a new
`evidence_unit_occurrences` keyed on `(evidence_unit_id, project_id)` records presence. One body,
N presences, exactly as one `Artifact` has N `ArtifactOccurrence`s.

*This is the ruling.* It changes no scientific identity, keeps one canonical body, makes "which
projects hold this evidence" representable, and gives the read gate the same object shape it
already uses for artifacts.

**Reading D — forbid the same artifact in two projects.**
*Rejected.* ADR-0010 exists because that happens routinely and must be supported; a foundry PDK
document legitimately appears in several projects under different labels.

## Resolution

Reading C, ruled by the maintainer and implemented by `v3.3-a18`:

- §17.25's `EvidenceUnit` block loses `project_id`;
- new **§17.25.1 `EvidenceUnitOccurrence`**, identity `(evidence_unit_id, project_id)`;
- migration `003b` performs the forward split;
- `SEC-002`'s project scoping for evidence reads resolves through the occurrence, not through a
  column on the identity row.

**No Requirement or Test ID is added.** `EVI-010` already obliges evidence identity to be stable
and project scope to be enforced; `SEC-002` already obliges reads to be occurrence-scoped. This
amendment makes both **representable**, which is the same thing `v3.3-a11` did for
`BeliefRevisionEvent.project_id`. Requirement ↔ Test stays **60 ↔ 60**.

Recorded in **ADR-0012**, which states the parallel with ADR-0010 explicitly so the next object
with a global identity and a project-scoped presence is not re-litigated a third time.

## What stays unresolved, deliberately

Per-project *divergence* of the same evidence — one project redacting a passage the other keeps —
is **not** representable and is not meant to be. Redaction produces different bytes, therefore a
different Artifact, therefore different evidence units. If a future requirement needs one work to
appear differently per project without differing bytes, that is a new object and a new ruling, not
an extension of the occurrence.
