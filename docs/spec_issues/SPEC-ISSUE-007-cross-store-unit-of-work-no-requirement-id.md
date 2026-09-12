# SPEC-ISSUE-007: Cross-store unit of work has no dedicated Requirement ID

Severity: GATE
Status: OPEN
Blocks gate: M1
Raised: 2026-09-12
Raised by: M0a Spec Coverage Audit (§23.5 (2))
Affected: §12.3, §17.12, §18 `core/repositories/unit_of_work.py`

## The unregistered MUST

§12.3:

> artifact store 與 PostgreSQL 的跨界寫入必須在同一 unit of work 內補償，避免 orphan artifact
> 或 dangling ref。

§18's repository tree lists `core/repositories/unit_of_work.py`, so an implementation is expected. No
Requirement ID demands one.

## Why it matters

Two stores, no distributed transaction. Artifact bytes land in the artifact store; the row lands in
PostgreSQL. A failure between them leaves either an orphan blob — wasteful but harmless — or a
dangling reference, which is not harmless: `artifact_id` is the root of every provenance chain, so a
row pointing at bytes that were never written makes a claim untraceable in exactly the way ART-001
exists to prevent, while looking perfectly well-formed in the database.

ART-001's test covers identity and hashing, not write ordering across two stores.

## Why it is not blocking now

M0a stores no artifact bytes: `Artifact.uri` is recorded but nothing writes to an artifact store
until the M1 ingestion pipeline. Recorded as `Blocks gate: M1`.

## Options for the maintainer

1. **Add a dedicated requirement** (e.g. `OPS-004` / `T-OPS-004`): a cross-store write MUST be
   compensated within one unit of work; a failure between stores MUST leave no dangling reference,
   proven by fault injection. Moves the invariant to 54 ↔ 54.
2. **Extend `ART-001`**'s pass condition: an artifact row whose bytes are absent from the artifact
   store MUST be rejected or quarantined. Preserves 53 ↔ 53 and puts the rule beside the identity
   guarantee it protects.
3. **Extend `UX-004`**, which already governs write ordering during ingestion (raw artifact durably
   stored before any parsing stage).

Option 2 or 3 is likely tidier than a new requirement, since both already own adjacent guarantees.

## Resolution checklist

- [ ] Maintainer picks an option
- [ ] Spec updated accordingly (and the invariant count, if option 1)
- [ ] `docs/normative_statements.yaml` gains an entry for §12.3
- [ ] This issue closed
