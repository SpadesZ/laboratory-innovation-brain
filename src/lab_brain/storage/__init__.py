"""Storage backends. §6.6: PostgreSQL is the single source of truth for rows; bytes live beside it.

The split is not an abstraction for its own sake -- it is the reason OPS-004 exists. Two stores
with no transaction between them need an explicit compensating unit of work, and putting the byte
store behind a named seam is what makes that compensation testable by fault injection rather than
by hoping.
"""

__all__: list[str] = []
