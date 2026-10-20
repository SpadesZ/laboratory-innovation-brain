"""What serves the research service's model slots: an active language-model runtime, or nothing.

`ResearchEpisodeService` builds its `ScientificLLM` from EITHER this or, when none is given, the
local catalog reasoner -- the explicit fallback. There is one scientific inference path either way:
the same `ScientificLLM`, `ModelRouter`, budget gate, egress gate, typed role parsers and
`InferenceProvenance`. A runtime contributes only what `ScientificLLM` already takes from any
deployment:

    slots          the `ModelSlot` of each bound logical slot -- model, locked route version,
                   provider, and declared reach (LOCAL or EXTERNAL); never EMBEDDING, which stays
                   the built-in local embedder
    complete       the `Completion` transport, called only by `ScientificLLM` after the gates
    egress_policy  the policy the egress gate consults for an EXTERNAL route, per project: THAT
                   PROJECT'S OWN declaration (`012f`), narrowed to the routes this runtime serves.
                   A runtime supplies routes, never permission: a project that declared nothing
                   gets `None`, and the gate refuses its every external call
    egress_statement  how the report states the egress a given project's run was held to
    description    how the report names what reasoned, including the Critic's route
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from lab_brain.cognition.llm import Completion, ModelSlot
from lab_brain.core.models.inference import LogicalSlot
from lab_brain.security.egress import EgressPolicy


@dataclass(frozen=True)
class ReasoningRuntime:
    runtime_id: str
    name: str
    slots: tuple[ModelSlot, ...]
    complete: Completion
    egress_policy: Callable[[str], EgressPolicy | None]
    description: tuple[str, ...]
    egress_statement: Callable[[str], str]

    def __post_init__(self) -> None:
        bound = [s.logical_slot for s in self.slots]
        if LogicalSlot.EMBEDDING in bound:
            raise ValueError("EMBEDDING is the built-in local embedder, not a runtime slot")
        if len(bound) != len(set(bound)):
            raise ValueError("a runtime binds each logical slot at most once")


def active_runtime_name(connection: Any) -> str | None:
    """The name of the ACTIVE LLM runtime (`012e`), or `None`. A read, and nothing more: the
    command line uses it to refuse, since it never reaches a model itself (T-UX-006)."""
    row = connection.execute("SELECT name FROM llm_runtimes WHERE state = 'ACTIVE'").fetchone()
    return None if row is None else str(row[0])


__all__ = ["ReasoningRuntime", "active_runtime_name"]
