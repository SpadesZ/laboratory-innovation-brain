# ADR-0010: Artifact is global content identity; ArtifactOccurrence is project-scoped presence

Status: Accepted
Date: 2026-09-13
Affected Requirements: ART-001, SEC-001, SEC-002
Spec amendment: `v3.3-a8` (§17.1 rewritten, §17.1.1 added)
Human Approval Required: Yes — P0 security semantics (granted via SAI 3.3 §14.1, §14.4, §17.1)

## Context

`artifact_id` is content-addressed and `artifacts.content_hash` carries a UNIQUE index. That is
deliberate and correct: the same bytes are the same artifact everywhere, which is what makes
provenance chains join up and what makes duplicate detection cheap.

M0a then placed `project_id` and `sensitivity_label` on that same row. Those are not properties of
the bytes. They are properties of *a project's copy* of the bytes, and there can be several.

The consequence is not a missing check — it is an unanswerable question. A foundry PDK document
classified `RESTRICTED_NDA` in project A and re-uploaded into project B is **physically one row**.
Content-hash duplicate detection hands B a reference to A's artifact, and every subsequent check
reading `artifact.sensitivity_label` consults A's answer about B's copy. Whichever project ingested
the bytes first owns the classification for everyone. No amount of authorisation logic repairs this,
because "what is this labelled *here*" has no representation to consult.

Recorded as risk R-7 at the end of P2 and carried through M0a as a known defect, on the grounds that
nothing enforced ACLs yet. That was a reasonable deferral and it expired the moment P4 built the
enforcement.

## Decision

Two objects, one shared identity.

| | Scope | Identity | Carries |
|---|---|---|---|
| `Artifact` | global | `artifact_id` = `'art:' \|\| content_hash` | bytes, hash, media type, URI, lineage, origin, rights, secret-scan status |
| `ArtifactOccurrence` | per project | **`(artifact_id, project_id)`** | `sensitivity_label`, who ingested it, when |

One `Artifact` may have many `ArtifactOccurrence` rows, each with its own label. An artifact with no
occurrence in a project is **not present** in that project, and must not be readable there however
well cleared the requester is elsewhere.

Three consequences worth stating explicitly, because each was a live temptation:

1. **The columns are dropped, not made nullable.** A column that still exists will be read, and a
   stale label on the global row is worse than no label because it looks authoritative. Migration
   `002a` backfills every existing artifact into one occurrence and then drops both columns, so the
   old read is a hard error rather than a wrong answer.

2. **Identity semantics are unchanged.** `artifact_id` still derives from content alone; revision
   lineage (`lineage_id`, `lineage_revision`, `previous_artifact_id`) still describes the *bytes'*
   version history and remains on `Artifact`. Splitting project scope out does not make identity
   project-scoped — the opposite, it removes the only thing that made identity look project-scoped.

3. **`Actor.active` and `ProjectMembership.active` are separate gates.** Disabling an account is the
   global action; revoking a membership is the per-project one. The read gate requires both, because
   checking only the membership leaves a centrally disabled credential holding every grant it had.

## Alternatives considered

**Keep one row and add a project-scoped label table only for "shared" artifacts.** Rejected: it
makes the common path and the leak path different code, and the leak path is the one nobody
exercises. Whether an artifact is shared is not knowable at ingest.

**Make `artifact_id` project-scoped (hash + project).** Rejected: it destroys the property the
content-addressing exists for. The same measurement referenced from two projects would become two
artifacts, and every independence and corroboration calculation that depends on "same bytes, same
artifact" (EVI-004) would silently count one measurement twice. That trades a confidentiality bug
for a scientific one.

**Keep the fields and rely on the application layer to pass `project_id` everywhere.** Rejected: it
was the status quo, and the status quo could not express the question. It also puts the guarantee
entirely in caller discipline, which a migration or a support script bypasses.

## Consequences

- Any code reading `artifact.sensitivity_label` or `artifact.project_id` now fails to compile or
  errors at runtime. That is the point; there were four such sites and all are updated.
- Reclassification history is **not** representable. The current schema holds exactly one
  classification per `(artifact_id, project_id)` and an `UPDATE` overwrites it silently. This is
  stated rather than implied: an earlier draft of the model docstring claimed reclassification was
  append-only, which the schema could not support. Event-sourced classification belongs with
  `EPI-003` and is tracked as risk **R-9**.
- `SEC-002` remains only partially discharged. The read gate holds and is tested from both the model
  and the schema side; egress and approval-authority do not exist yet, and nothing yet *calls* the
  gate because there is no read path until M1.
- A conformance guard (`tests/spec/test_schema_drift.py`) now compares §17's canonical schemas
  against both the Pydantic models and the migration DDL, so this class of drift fails CI instead of
  surviving three review rounds.
