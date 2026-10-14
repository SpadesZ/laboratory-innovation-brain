"""The Causal Warrant Gate's sources, over PostgreSQL: one builder for every composition root.

The research service, its read side and the vertical test harness all resolve warrants the same
way -- certificates, attestations, observations and runs from their own stores, grants from
`012o` -- so the write path and the read path can never disagree about what a relation's warrant
or evidence line is. Each caller names the declaration sets its vertical registers.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from lab_brain.core.models.warrant import DiagnosticDeclarationSet
from lab_brain.core.repositories.evidence import SqlAttestationStore, SqlRelationStore
from lab_brain.core.repositories.hypotheses import SqlHypothesisStore
from lab_brain.core.repositories.jobs import SqlJobStore
from lab_brain.core.repositories.observations import SqlObservationStore
from lab_brain.core.repositories.warrants import SqlDiagnosticWarrantStore
from lab_brain.core.warrant import WarrantResolver


def sql_warrant_resolver(
    connection: Any,
    *,
    declaration_sets: Sequence[DiagnosticDeclarationSet],
    active: str | None,
) -> WarrantResolver:
    return WarrantResolver(
        certificates=SqlHypothesisStore(connection).get_certificate,
        attestations=SqlAttestationStore(connection).get,
        observations=SqlObservationStore(connection).get,
        runs=SqlJobStore(connection).get_run,
        grants=SqlDiagnosticWarrantStore(connection),
        relations=SqlRelationStore(connection).get,
        declaration_sets=declaration_sets,
        active=active,
    )


__all__ = ["sql_warrant_resolver"]
