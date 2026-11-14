"""The DomainPack-declared Domain Specialists (§7.1, §24.3's `register_specialists`) -- M3.

IN CORE, BECAUSE BOTH SIDES OF THE BOUNDARY NEED THE TYPE AND ONLY CORE IS SHARED. A pack declares a
specialist; `lab_brain.cognition` routes it. §24.2 allows `domains -> core` and
`cognition -> DomainPack registry/interface`, and `tests/unit/test_extension_boundary.py` holds the
stricter line that cognition imports nothing under `lab_brain.domains` -- so the declaration type
lives here, beside the other registries a pack writes into, and `lab_brain.domains.base`
re-exports it. §24.1 lists the DomainPack registry in core's MUST-know column; what core must NOT
know is any particular specialist, and it names none.
"""

from __future__ import annotations

from dataclasses import dataclass


class SpecialistDeclarationError(ValueError):
    """A specialist declaration is incomplete, or conflicts with one already registered."""


@dataclass(frozen=True)
class SpecialistRole:
    """§7.1's Domain Specialist, as a DomainPack declares one (M3).

    §7.1: 依領域提供獨立機制判斷 ... 只讀該 DomainPack 授權的 evidence、rules、tools、historical
    cases；不是 core；不得直接改 core epistemic semantics 或 evaluator. So a specialist is DATA core
    routes, not code core runs: an id, the prompt it reasons with, and the evidence domains it may
    read. Core never interprets `focus_terms` -- they are the specialist's own retrieval vocabulary,
    appended to the question when its domain evidence is retrieved.
    """

    role_id: str
    domain: str
    description: str
    prompt_id: str
    prompt_version: str
    prompt_template: str
    #: Condition-schema domains whose evidence this specialist may read (§7.1's "只讀").
    evidence_domains: tuple[str, ...]
    focus_terms: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("role_id", "domain", "prompt_id", "prompt_version", "prompt_template"):
            if not str(getattr(self, name)).strip():
                raise SpecialistDeclarationError(f"specialist role has a blank {name}")
        if not self.evidence_domains:
            raise SpecialistDeclarationError(
                f"specialist {self.role_id} declares no evidence domain; §7.1 limits a specialist "
                "to the evidence its DomainPack authorises, and 'none declared' would read as 'all'"
            )


class SpecialistRegistry:
    """Specialists a pack declares. Keyed by role id; one role is one registration."""

    def __init__(self) -> None:
        self._roles: dict[str, SpecialistRole] = {}

    def register(self, role: SpecialistRole) -> SpecialistRole:
        existing = self._roles.get(role.role_id)
        if existing is not None and existing != role:
            raise SpecialistDeclarationError(
                f"a different specialist is already registered as {role.role_id}"
            )
        self._roles[role.role_id] = role
        return role

    def for_domain(self, domain: str) -> tuple[SpecialistRole, ...]:
        return tuple(r for _, r in sorted(self._roles.items()) if r.domain == domain)

    def all(self) -> tuple[SpecialistRole, ...]:
        return tuple(r for _, r in sorted(self._roles.items()))

    def __len__(self) -> int:
        return len(self._roles)


__all__ = ["SpecialistDeclarationError", "SpecialistRegistry", "SpecialistRole"]
