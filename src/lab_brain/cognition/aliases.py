"""Short references a model is shown in place of canonical identifiers, and their resolution.

WHY. A role that must name a hypothesis or an attestation used to be shown its canonical id
(`hyp:6f488e12-...`) and asked to copy it back. A real model shortened one to its first eight
characters; the parser refused it, correctly, and the debate stopped. The capability probe had
passed, because it used short synthetic ids (`hyp:probe-contact`) -- so qualification never asked
for what research needed.

So a model is never asked to copy a canonical id. It is shown `H1`, `H2`, ... for hypotheses and
`E1`, `E2`, ... for evidence, and the parser maps each reference back. The table is:

    deterministic   numbered in the order the items were first shown in this debate, so the same
                    debate shows the same aliases, and a hypothesis keeps its alias in every call
    bijective       one alias per canonical id and one canonical id per alias; a canonical id that
                    could be read as an alias is refused, so no reference is ambiguous
    strict          a reference resolves only if it is EXACTLY an alias of something this call
                    showed, or EXACTLY the canonical id of something it showed. A prefix, a changed
                    case, an alias of something not shown, an invented one: none resolves
    recorded        each call records the aliases it showed (`shown`) in its InferenceProvenance
                    parameters, so the stored reply can be read back to canonical ids without
                    re-running anything

Canonical ids stay the identity everywhere else: what is stored, admitted and cited is always the
canonical id the alias resolved to.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from typing import Any

#: What an alias looks like. A canonical id of this shape would be ambiguous, and is refused.
ALIAS_SHAPE = re.compile(r"^[A-Z][0-9]+$")


class AliasTable:
    """`prefix` + 1, 2, ... in order of `add`. Append-only: an alias, once given, never changes."""

    def __init__(self, prefix: str) -> None:
        if not re.fullmatch(r"[A-Z]", prefix):
            raise ValueError(f"an alias prefix is one capital letter, not {prefix!r}")
        self._prefix = prefix
        self._by_alias: dict[str, str] = {}
        self._by_id: dict[str, str] = {}

    def add(self, canonical: str) -> str:
        """The alias of `canonical`, given now if it has none. Idempotent."""
        if canonical in self._by_id:
            return self._by_id[canonical]
        if not canonical.strip() or ALIAS_SHAPE.match(canonical):
            raise ValueError(
                f"{canonical!r} cannot be aliased: a canonical id that is blank or reads as an "
                "alias would make a reference ambiguous"
            )
        alias = f"{self._prefix}{len(self._by_alias) + 1}"
        self._by_alias[alias] = canonical
        self._by_id[canonical] = alias
        return alias

    def alias(self, canonical: str) -> str:
        return self._by_id[canonical]

    def shown(self, canonical_ids: Collection[str]) -> dict[str, str]:
        """alias -> canonical id, for exactly the items one call showed (each added first)."""
        return {self.add(c): c for c in canonical_ids}


def aliased(
    items: Sequence[Mapping[str, Any]], key: str, table: AliasTable
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """`items` as a model is shown them -- `item[key]` replaced by its alias -- and alias ->
    canonical id for exactly those items."""
    shown: dict[str, str] = {}
    out: list[dict[str, Any]] = []
    for item in items:
        canonical = str(item[key])
        alias = table.add(canonical)
        shown[alias] = canonical
        out.append({**item, key: alias})
    return out, shown


def resolve(ref: str, shown: Mapping[str, str]) -> str | None:
    """The canonical id `ref` names among what a call `shown` (alias -> canonical), or None.

    Exactly an alias, or exactly a canonical id that was shown -- nothing else. A canonical id is
    accepted because a reply recorded before aliases (or a model that copies one in full) names it
    without ambiguity; a prefix of one is never accepted, however unique it happens to be.
    """
    if ref in shown:
        return shown[ref]
    if ref in shown.values():
        return ref
    return None


__all__ = ["ALIAS_SHAPE", "AliasTable", "aliased", "resolve"]
