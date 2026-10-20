"""§7.3's model routing, and §7.1's roles it routes (M3 scope: PRIMARY/FAST/EMBEDDING minimum).

    §7.3  Model Router 提供 6 個 LLM logical slots + 1 個 EMBEDDING slot（不是 6 顆必備模型）。
    §26.1 M3 Hypothesis Brain: 6 core roles、selected Domain Specialists、PRIMARY/FAST/EMBEDDING
          minimum routing、stake-adaptive debate、Critic inverted retrieval。

A ROLE IS NOT A MODEL. §7's opening line is that the multi-agent design is "cognitive decomposition,
不是很多聊天機器人": six responsibilities, each routed to a pluggable slot, and one model may serve
several slots. So the router maps a role to a SLOT, and the slot to whatever model the deployment
configured -- a role never names a model, and swapping a provider is a configuration change that no
role notices.

THE MINIMUM IS REFUSED AT CONSTRUCTION. M3's scope names PRIMARY, FAST and EMBEDDING as the minimum
routing. A router missing one of them is refused when it is built rather than when the first role
reaches for the empty slot mid-debate, because a debate that fails in Stage B has already spent
Stage A's budget.

THE CRITIC'S ROUTE MAY FALL BACK, AND THAT IS §7.3'S OWN RULE. REASONING_ADVERSARIAL is optional:
"provider can differ but **evidence-path independence is primary**". When it is not configured the
Critic runs on REASONING_PRIMARY, and its independence has to come from the evidence path instead --
the inverted bundle (§7.2) -- which `ScientificInferenceService.critique` then checks
(`route_differs_from`): a critique on the same slot, model and bundle is refused as not independent.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum

from lab_brain.core.models.inference import LogicalSlot


class CognitiveRole(StrEnum):
    """§7.1's six core functions, plus the DomainPack-registered specialists as one kind."""

    SUPERVISOR = "SUPERVISOR"
    EVIDENCE_RESEARCHER = "EVIDENCE_RESEARCHER"
    HYPOTHESIS_ENGINE = "HYPOTHESIS_ENGINE"
    ADVERSARIAL_CRITIC = "ADVERSARIAL_CRITIC"
    VERIFICATION_PLANNER = "VERIFICATION_PLANNER"
    NOVELTY_AUDITOR = "NOVELTY_AUDITOR"
    DOMAIN_SPECIALIST = "DOMAIN_SPECIALIST"


#: §7.3's slots, as recorded in `InferenceProvenance.logical_slot` since `003e`.
ROUTE_SLOTS: frozenset[LogicalSlot] = frozenset(
    {
        LogicalSlot.REASONING_PRIMARY,
        LogicalSlot.REASONING_ADVERSARIAL,
        LogicalSlot.FAST_UTILITY,
        LogicalSlot.CODE,
        LogicalSlot.PRIVATE_LOCAL,
        LogicalSlot.VISION,
        LogicalSlot.EMBEDDING,
    }
)

#: M3's minimum routing (§26.1).
MINIMUM_ROUTE: frozenset[LogicalSlot] = frozenset(
    {LogicalSlot.REASONING_PRIMARY, LogicalSlot.FAST_UTILITY, LogicalSlot.EMBEDDING}
)

#: §7.3's table: which slot each role's work goes to.
_ROLE_SLOT: dict[CognitiveRole, LogicalSlot] = {
    CognitiveRole.SUPERVISOR: LogicalSlot.REASONING_PRIMARY,
    # §7.3: FAST_UTILITY is for "query rewrite、分類、欄位抽取、routing".
    CognitiveRole.EVIDENCE_RESEARCHER: LogicalSlot.FAST_UTILITY,
    CognitiveRole.HYPOTHESIS_ENGINE: LogicalSlot.REASONING_PRIMARY,
    CognitiveRole.ADVERSARIAL_CRITIC: LogicalSlot.REASONING_ADVERSARIAL,
    CognitiveRole.VERIFICATION_PLANNER: LogicalSlot.REASONING_PRIMARY,
    CognitiveRole.NOVELTY_AUDITOR: LogicalSlot.REASONING_PRIMARY,
    CognitiveRole.DOMAIN_SPECIALIST: LogicalSlot.REASONING_PRIMARY,
}


class RoutingError(RuntimeError):
    """The router cannot be built as configured, or a role has no route."""


class ModelRouter:
    """Role -> §7.3 slot, over the slots this deployment actually configured."""

    def __init__(self, configured: Iterable[LogicalSlot]) -> None:
        slots = frozenset(configured)
        legacy = sorted(s.value for s in slots - ROUTE_SLOTS)
        if legacy:
            raise RoutingError(
                f"{legacy} are not §7.3 route slots. They are M1's function labels, which "
                "`inference_provenance` still accepts for M1's records; a role routed to one would "
                "record a route §7.3 does not declare"
            )
        missing = sorted(s.value for s in MINIMUM_ROUTE - slots)
        if missing:
            raise RoutingError(
                f"the model router is missing {missing}. M3's minimum routing is "
                f"{sorted(s.value for s in MINIMUM_ROUTE)}; refusing here, before any debate "
                "starts, means no Stage A budget is spent on a debate whose Stage B cannot run"
            )
        self._configured = slots

    @property
    def configured(self) -> frozenset[LogicalSlot]:
        return self._configured

    def route(self, role: CognitiveRole) -> LogicalSlot:
        wanted = _ROLE_SLOT[role]
        if wanted in self._configured:
            return wanted
        if role is CognitiveRole.ADVERSARIAL_CRITIC:
            # §7.3: "provider can differ but evidence-path independence is primary". The critique's
            # independence is then carried by its bundle, and checked, not assumed.
            return LogicalSlot.REASONING_PRIMARY
        raise RoutingError(f"role {role.value} routes to {wanted.value}, which is not configured")

    def critic_route_is_distinct(self) -> bool:
        """Whether the Critic runs on its own slot, or must rely on evidence-path independence."""
        return LogicalSlot.REASONING_ADVERSARIAL in self._configured


__all__ = ["MINIMUM_ROUTE", "ROUTE_SLOTS", "CognitiveRole", "ModelRouter", "RoutingError"]
