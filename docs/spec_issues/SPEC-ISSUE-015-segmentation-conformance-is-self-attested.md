# SPEC-ISSUE-015: an evidence unit's segmentation conformance is self-attested

Severity: GATE
Status: RESOLVED
Blocks gate: M1
Raised: 2026-09-21
Raised by: M1-P1 audit (targeted repair), reproduced against PostgreSQL
Resolved: 2026-09-21
Resolved by: `v3.3-a18` (maintainer ruling: the `v3.3-a13` two-layer split, applied to segmentation)
Affected: §6.22 rule 1, §17.25, `EVI-010`, migration `003a`, `v3.3-a12`, `v3.3-a13`

## The gap, reproduced

`003a`'s trigger enforces §6.22 rule 1 as: *a unit that **declares** a bound condition must
contain it*. The declaration is `bound_condition_texts`, and it is written by the same party that
writes the body.

So the guard is skipped by not declaring anything:

```
INSERT INTO evidence_units (..., body, ...)      -- the severed result, on its own
VALUES (..., 'Cj decreased from 0.515 to 0.345 pF/mm.', ...)
-- bound_condition_texts omitted -> defaults to '{}' -> the trigger never fires

stored body      : 'Cj decreased from 0.515 to 0.345 pF/mm.'
bound_conditions : []          <-- empty, so the rule-1 trigger never fires
segmenter claimed: 's'         <-- unverifiable; any string is accepted
```

The row is now a canonical evidence unit. It has a well-formed derived identity, a real artifact,
a real locator, a plausible `segmenter_id`, and it satisfies every constraint in the table. The
condition that makes its number interpretable is nowhere, and **nothing objected** — which is
precisely the failure §6.22 opens by describing: no field is missing, because the conditions were
not dropped, they were filed separately.

`v3.3-a17`'s own words are the indictment: "`bound_condition_texts` 是使規則 1 可被執行的欄位 …
沒有它,規則 1 只是對 segmenter 行為的期望而非紀錄的性質". The amendment made the rule executable
*for units that opt in*, and an attacker does not opt in.

## Why "make PostgreSQL check it" is not the answer

The obvious repair is to have the database decide whether a body needs a condition. It must not:
that requires PostgreSQL to read scientific prose and judge whether a result is interpretable
without its setup — a natural-language judgement, in SQL, duplicated from the segmenter.

The repository has already ruled on exactly this shape. `v3.3-a13`, on belief transitions:

> refusing it would mean running `TransitionPolicy.evaluate` inside PostgreSQL, i.e. a second copy
> of the evaluator, and §8.2.1 would stop being the single source of semantic truth.

The same sentence applies with `bind_condition_result_groups` in place of `evaluate`.

## Readings

**Reading A — make `bound_condition_texts` NOT NULL and non-empty.**
*Rejected.* It forces a declaration on units that genuinely have no bound condition (a table, a
code block, an unconditioned statement), so producers would write a placeholder and the field
would stop meaning anything. It also does not help: a forger declares a condition the severed body
happens to contain.

**Reading B — teach the trigger to detect result-shaped prose without a condition.**
*Rejected.* Natural language in SQL, a second implementation of the binder, and the two drift.
This is what `v3.3-a13` refused.

**Reading C — the `v3.3-a13` two-layer split, applied to segmentation.**
Separate the storage-checkable half from the semantic half, and put each where it can actually be
enforced:

```
storage-checkable   the unit carries a segmentation witness binding its own conformance-relevant
                    fields. PostgreSQL recomputes the digest -- bytes, not language -- and refuses
                    a row whose witness does not bind its contents.

semantic            the production scientific-admission path RE-DERIVES the unit by re-running
                    the recorded parser and segmenter over the artifact's own bytes, and refuses
                    a unit that segmentation does not reproduce.
```

*This is the ruling.*

The second layer is what actually closes the hole, and it closes it completely: the artifact is
content-addressed, so the bytes are pinned; the segmenter is deterministic and version-recorded;
therefore "what would segmentation produce here" is computable at admission time. A severed unit
with omitted bindings is not among the units the segmenter produces from those bytes, so it is
refused — **without anything having to understand what it says**.

The first layer is not redundant, and it is not security theatre either. It is the exact analogue
of `input_hash` in `v3.3-a12`: it lets the *store* reject a partially-forged row (body edited,
witness left behind) cheaply and without re-serializing, and it makes the expensive check's
absence detectable. It does **not** stop a complete forgery by someone who knows the algorithm —
that is layer two's job, and saying so plainly is the same honesty `v3.3-a13` applied to its own
two classes.

**Reading D — accept it, and rely on database write permissions.**
*Rejected.* `011a`, `011c`, `011d` and `011g` each had to write down that a guard only reached by
a cooperative caller is a guard nothing holds. This is the fifth instance of that sentence.

## Resolution

Reading C, ruled by the maintainer and implemented by `v3.3-a18`:

- §17.25's `EvidenceUnit` gains `segmentation_witness`;
- `003b` adds the column NOT NULL with a shape CHECK and a digest-binding trigger, using
  `sha256()` over canonical bytes — a byte operation, not a language one;
- the admission gate gains a re-derivation step that re-runs parser + segmenter over the
  artifact's bytes and refuses a unit segmentation does not reproduce, with reason code
  `SEGMENTATION_NOT_REPRODUCIBLE`;
- re-derivation **fails closed**: an artifact whose bytes cannot be loaded refuses admission
  rather than skipping the check.

**No Requirement or Test ID is added.** `EVI-010` already obliges segmentation to preserve the
Minimum Evidence Boundary; this makes the obligation enforceable against a writer who did not run
the segmenter, which is what `v3.3-a13` did for `EPI-005`. Requirement ↔ Test stays **60 ↔ 60**.

## Cost, stated rather than discovered later

Re-derivation re-parses and re-segments the artifact on the admission path. On the locked fixture
that is sub-millisecond; on a large document it is not free, and it is per admission. The
mitigation available today is that the check is scoped to *scientific admission*, which is rare,
rather than to retrieval, which is not. If it ever needs to be cheaper the answer is a verified
cache keyed on `(artifact_id, parser_version, segmenter_version)` — **not** trusting the witness
alone, which would delete layer two and restore this issue.
