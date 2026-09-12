# SPEC-ISSUE-002: `GH-xxx` is missing from the §23.2 Requirement ID namespace table

Severity: **EDITORIAL** — no semantic consequence; does not gate a milestone
Status: OPEN
Raised: 2026-09-12
Raised by: implementation agent, P1 review
Affected: §23.2, §25.3, §26

## The gap

§25.3 and §26 define three requirements in a `GH` namespace:

| Requirement | Subject |
|---|---|
| `GH-001` | public repo discovery + ref/commit-pinned fetch + normalized provenance |
| `GH-002` | private repo access requires explicit auth/allowlist; fails closed |
| `GH-003` | GitHub technical/prior-art evidence is not auto-promoted to peer-reviewed evidence |

The §23.2 namespace table lists `SYS`, `ART`, `EVI`, `EPI`, `VER`, `SIM`, `DOM-SP`, `SEC`,
`OPS`, `COST`, `SRC`, `LLM`, `EXT`, `UX`, `TST` — and not `GH`.

## Why this is not treated as blocking

AGT-015 blocks a slice on *conflicting normative contracts*. Here nothing conflicts: §23.2 is
an incomplete enumeration, and §25.3/§26 unambiguously define the three requirements. No
reading of §23.2 forbids `GH`; it simply fails to mention it.

Had §23.2 instead stated that external-source requirements MUST use the `SRC` namespace, this
would be a genuine contradiction and the slice would have stopped.

## Implementation handling

`GH` is included in `REQUIREMENT_NAMESPACES` in `src/lab_brain/spec/parser.py`, with an inline
comment pointing at this issue. Without it, `REQUIREMENT_ID_RE` would reject `GH-001` and the
§26 matrix would fail to parse — so the alternative is not "stricter", it is "broken".

## Proposed wording

Add to the §23.2 namespace block:

```
GH-xxx      external code-hosting provider (GitHub and equivalents)
```

Alternatively, renumber `GH-001..003` into the `SRC` namespace. That is the larger change:
it alters three Requirement IDs and three Test IDs, so it needs an ADR rather than an
editorial fix.

## Resolution checklist

- [ ] Spec maintainer adds `GH-xxx` to §23.2, or decides on renumbering into `SRC`
- [ ] If renumbered: update §25.3, §26, `docs/normative_statements.yaml`, `docs/milestones.yaml`
- [ ] Inline comment in `parser.py` updated to cite the settled text
