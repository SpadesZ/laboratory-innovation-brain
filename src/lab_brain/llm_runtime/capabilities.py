"""What a model must have PROVEN before it may serve a logical slot, and which roles each serves.

§7.3's contract is CognitiveRole -> LogicalSlot -> ModelSlot. The first arrow is code
(`cognition.routing`) and is shown here read-only, derived from the router itself so it cannot
drift; the second is what an operator configures. A model is bindable to a slot only when every
capability that slot's roles depend on has been PROBED and passed -- a provider's own claims about
a model are hints, never capabilities.

The role capabilities are this system's own contracts: a slot's roles speak through typed role
parsers (`cognition.roles`), so a model serves REASONING_PRIMARY only if its answer to the
Hypothesis Engine and specialist prompts passes those parsers, FAST_UTILITY only if its query
rewrite does, and the Critic's slot only if its critique does. `migrations/012e` holds the same
table (`llm_slot_requirements`); a test asserts they agree.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

from lab_brain.cognition.routing import CognitiveRole, ModelRouter
from lab_brain.core.models.inference import LogicalSlot


class Capability(StrEnum):
    #: Answers a plain prompt at all.
    CHAT = "CHAT"
    #: Returns a bare JSON object when asked -- what every typed role parser reads.
    STRUCTURED_JSON = "STRUCTURED_JSON"
    #: The Evidence Researcher's query rewrite passes `parse_query_terms`.
    ROLE_QUERY = "ROLE_QUERY"
    #: The Hypothesis Engine's certificates pass `parse_hypothesis_engine`.
    ROLE_HYPOTHESIS = "ROLE_HYPOTHESIS"
    #: A domain specialist's position passes `parse_specialist`.
    ROLE_SPECIALIST = "ROLE_SPECIALIST"
    #: The Adversarial Critic's report passes `parse_critique`.
    ROLE_CRITIQUE = "ROLE_CRITIQUE"
    #: Writes a syntactically valid function when asked (parsed, never executed).
    CODE = "CODE"
    #: Reads an image it is sent.
    VISION = "VISION"


#: The slots an operator binds. EMBEDDING is the built-in local embedder in this version.
BINDABLE_SLOTS: tuple[LogicalSlot, ...] = (
    LogicalSlot.REASONING_PRIMARY,
    LogicalSlot.FAST_UTILITY,
    LogicalSlot.REASONING_ADVERSARIAL,
    LogicalSlot.PRIVATE_LOCAL,
    LogicalSlot.CODE,
    LogicalSlot.VISION,
)

#: M3's minimum route that an operator must bind (§26.1). EMBEDDING completes it, built in.
REQUIRED_SLOTS: frozenset[LogicalSlot] = frozenset(
    {LogicalSlot.REASONING_PRIMARY, LogicalSlot.FAST_UTILITY}
)

SLOT_REQUIREMENTS: Mapping[LogicalSlot, frozenset[Capability]] = {
    LogicalSlot.REASONING_PRIMARY: frozenset(
        {
            Capability.CHAT,
            Capability.STRUCTURED_JSON,
            Capability.ROLE_HYPOTHESIS,
            Capability.ROLE_SPECIALIST,
        }
    ),
    LogicalSlot.REASONING_ADVERSARIAL: frozenset(
        {Capability.CHAT, Capability.STRUCTURED_JSON, Capability.ROLE_CRITIQUE}
    ),
    LogicalSlot.FAST_UTILITY: frozenset(
        {Capability.CHAT, Capability.STRUCTURED_JSON, Capability.ROLE_QUERY}
    ),
    LogicalSlot.CODE: frozenset({Capability.CHAT, Capability.CODE}),
    LogicalSlot.VISION: frozenset({Capability.CHAT, Capability.VISION}),
    LogicalSlot.PRIVATE_LOCAL: frozenset({Capability.CHAT, Capability.STRUCTURED_JSON}),
}

#: The built-in embedding route (the research service's `EMBEDDING_SLOT`): local, always there.
BUILTIN_EMBEDDING = "hashing-embedder@1.0.0"


def role_routes() -> Mapping[CognitiveRole, LogicalSlot]:
    """The router's own table, read through its public API with every slot configured."""
    router = ModelRouter(frozenset(LogicalSlot) - _M1_FUNCTION_LABELS)
    return {role: router.route(role) for role in CognitiveRole}


def critic_fallback() -> LogicalSlot:
    """Where the Critic goes when REASONING_ADVERSARIAL is not configured -- the router's answer."""
    minimum = ModelRouter(
        {LogicalSlot.REASONING_PRIMARY, LogicalSlot.FAST_UTILITY, LogicalSlot.EMBEDDING}
    )
    return minimum.route(CognitiveRole.ADVERSARIAL_CRITIC)


def roles_on(slot: LogicalSlot) -> tuple[CognitiveRole, ...]:
    return tuple(role for role, routed in role_routes().items() if routed is slot)


#: M1's function labels: recordable in provenance, never routed to (`cognition.routing`).
_M1_FUNCTION_LABELS = frozenset(
    {
        LogicalSlot.HYPOTHESIS,
        LogicalSlot.CRITIQUE,
        LogicalSlot.EXTRACTION,
        LogicalSlot.PLANNING,
        LogicalSlot.SUMMARISATION,
        LogicalSlot.RELATION,
    }
)


__all__ = [
    "BINDABLE_SLOTS",
    "BUILTIN_EMBEDDING",
    "REQUIRED_SLOTS",
    "SLOT_REQUIREMENTS",
    "Capability",
    "critic_fallback",
    "role_routes",
    "roles_on",
]
