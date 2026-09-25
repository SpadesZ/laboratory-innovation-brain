"""§7.5's intent-aware SourcePolicy, and the stakes threshold that makes inverted retrieval a MUST.

    SRC-002  SourcePolicy 依 research intent 切換；當 decision.stakes >= policy threshold，Critic
             MUST 執行 inverted retrieval、保存 inverted EvidenceBundle，否則該 decision 不得進入
             BELIEF_REVISION。
    §7.2     當 decision.stakes >= SourcePolicy.inverted_retrieval_threshold 時 ...
    §7.5     SourceRouter 先過 privacy/rights/ACL，再依 research intent 選 SourcePolicy。

TWO POLICIES SHARE ONE NAME IN THE SPEC, AND THIS IS THE RETRIEVAL ONE. `lab_brain.evidence.
source_status.SourcePolicy` is EVI-008's status-to-outcome table -- what a retraction does to a
major revision. This module is §7.5's: which kinds of source a retrieval for a given research
intent may draw from, in what order, and at what stakes the Critic must go looking for the
opposite. They are
different decisions made at different times, so they are different objects; this one is named
`IntentSourcePolicy` so neither reads as the other.

THE SOURCE KINDS ARE §6.5's `TrustClass`. A second enum of "source classes" would be a parallel
vocabulary for the same thing, and the first time the two disagreed a DIAGNOSIS retrieval would
select internal runs under one name and exclude them under the other.

STAKES ARE ORDINAL AND THE POLICY DECLARES THE ORDER. §8.1 rules out uncalibrated numbers, so
`stakes` is a word, and "stakes >= threshold" needs an order the words do not carry themselves.
Each policy states it (`stakes_order`), and a stakes value the policy does not declare is REFUSED
rather than treated as low: an unknown stakes word is exactly how a high-stakes decision would slip
under the threshold.

THE DEFAULTS ARE §7.5's TABLE, TRANSCRIBED. They are core data, not domain knowledge -- §24.1 lists
the "SourcePolicy contract" in the Core MUST-know column -- and each carries a version so a bundle
records which reading of the table selected its evidence.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from enum import StrEnum

from lab_brain.core.models.enums import TrustClass
from lab_brain.core.models.prior_art import INTERNAL_TRUST_CLASSES


class ResearchIntentKind(StrEnum):
    """§7.5's five research intents. `ResearchIntent.intent` stores the value as a string."""

    DIAGNOSIS = "DIAGNOSIS"
    MECHANISM_DISCOVERY = "MECHANISM_DISCOVERY"
    NOVELTY_AUDIT = "NOVELTY_AUDIT"
    CROSS_DOMAIN_INNOVATION = "CROSS_DOMAIN_INNOVATION"
    REPLICATION = "REPLICATION"


#: The ordinal stakes vocabulary the default policies declare, lowest first. `ROUTINE`, `LOW`,
#: `NORMAL` and `HIGH` are the words the repository already uses on ReviewItems and HypothesisViews.
DEFAULT_STAKES_ORDER: tuple[str, ...] = ("ROUTINE", "LOW", "NORMAL", "HIGH", "CRITICAL")

EXTERNAL_TRUST_CLASSES: frozenset[TrustClass] = frozenset(TrustClass) - INTERNAL_TRUST_CLASSES


class SourcePolicyError(ValueError):
    """A policy is malformed, or was asked about an intent or a stakes value it does not declare."""


@dataclass(frozen=True)
class IntentSourcePolicy:
    """One research intent's retrieval policy (§7.5).

    ``source_classes`` is ordered: the order is the preference §7.5's table states ("Internal
    matched runs ... first"), and ties in relevance are broken by it, so two policies admitting the
    same classes in a different order are different policies.

    ``inverted_source_classes`` is where the Critic's inverted retrieval may look. It is declared
    separately because inverting a DIAGNOSIS retrieval means leaving lab history -- §7.5's own
    warning is "避免只相信 lab history" -- so the Critic's classes are deliberately not the primary
    ones.
    """

    policy_id: str
    version: str
    intent: str
    source_classes: tuple[TrustClass, ...]
    inverted_source_classes: tuple[TrustClass, ...]
    stakes_order: tuple[str, ...] = DEFAULT_STAKES_ORDER
    inverted_retrieval_threshold: str = "HIGH"
    #: §7.5 MECHANISM_DISCOVERY: "要求至少一條外部反證搜尋".
    contradiction_search_required: bool = False
    #: §7.5 NOVELTY_AUDIT: the classes a search must have covered before any GLOBAL novelty scope.
    global_novelty_requires: frozenset[TrustClass] = field(default_factory=frozenset)
    #: How many evidence items one retrieval may place in a bundle.
    max_items: int = 8

    def __post_init__(self) -> None:
        if not self.policy_id.strip() or not self.version.strip() or not self.intent.strip():
            raise SourcePolicyError("a source policy needs an id, a version and an intent")
        if not self.source_classes:
            raise SourcePolicyError(
                f"source policy {self.ref} admits no source class; a retrieval under it could only "
                "ever return nothing, which reads in a bundle as 'we looked and found nothing'"
            )
        for name, classes in (
            ("source_classes", self.source_classes),
            ("inverted_source_classes", self.inverted_source_classes),
        ):
            if len(set(classes)) != len(classes):
                raise SourcePolicyError(f"source policy {self.ref} repeats a class in {name}")
        if len(set(self.stakes_order)) != len(self.stakes_order) or not self.stakes_order:
            raise SourcePolicyError(
                f"source policy {self.ref} declares a stakes order with a repeated or missing "
                "value; the threshold comparison needs one position per word"
            )
        if self.inverted_retrieval_threshold not in self.stakes_order:
            raise SourcePolicyError(
                f"source policy {self.ref} sets its inverted-retrieval threshold at "
                f"{self.inverted_retrieval_threshold!r}, which its stakes order "
                f"{list(self.stakes_order)} does not contain -- a threshold nobody can reach or "
                "that everything reaches, depending on how the lookup fails"
            )
        if not self.inverted_source_classes:
            raise SourcePolicyError(
                f"source policy {self.ref} declares nowhere for the Critic's inverted retrieval to "
                "look; SRC-002 makes that retrieval mandatory above the threshold, so a policy "
                "that cannot perform it would block every high-stakes decision permanently"
            )
        if self.max_items < 1:
            raise SourcePolicyError(f"source policy {self.ref} allows no items per retrieval")

    @property
    def ref(self) -> str:
        return f"{self.policy_id}@{self.version}"

    def rank(self, stakes: str) -> int:
        """Position of ``stakes`` in this policy's order. Refuses an undeclared value."""
        try:
            return self.stakes_order.index(stakes)
        except ValueError:
            raise SourcePolicyError(
                f"stakes {stakes!r} is not declared by source policy {self.ref} "
                f"(declared: {list(self.stakes_order)}). An undeclared stakes value is refused "
                "rather than read as low: that is exactly how a high-stakes decision would slip "
                "under the inverted-retrieval threshold"
            ) from None

    def requires_inverted_retrieval(self, stakes: str) -> bool:
        """§7.2: stakes >= inverted_retrieval_threshold."""
        return self.rank(stakes) >= self.rank(self.inverted_retrieval_threshold)

    def admits(self, trust_class: TrustClass) -> bool:
        return trust_class in self.source_classes

    def preference(self, trust_class: TrustClass) -> int:
        """Lower is preferred. A class the policy does not admit sorts last."""
        return (
            self.source_classes.index(trust_class)
            if trust_class in self.source_classes
            else len(self.source_classes)
        )


def default_source_policies(version: str = "1.0.0") -> tuple[IntentSourcePolicy, ...]:
    """§7.5's table, one policy per intent."""
    internal_first = (
        TrustClass.INTERNAL_RUN,
        TrustClass.INTERNAL_MEASUREMENT,
        TrustClass.EXPERT_HEURISTIC,
    )
    literature = (TrustClass.PEER_REVIEWED, TrustClass.PREPRINT)
    return (
        IntentSourcePolicy(
            policy_id="srcpol:diagnosis",
            version=version,
            intent=ResearchIntentKind.DIAGNOSIS,
            source_classes=internal_first,
            # "仍需 contradiction check，避免只相信 lab history": the Critic leaves lab history.
            inverted_source_classes=(*literature, TrustClass.TECHNICAL_ARTIFACT),
        ),
        IntentSourcePolicy(
            policy_id="srcpol:mechanism-discovery",
            version=version,
            intent=ResearchIntentKind.MECHANISM_DISCOVERY,
            source_classes=(*internal_first, *literature),
            inverted_source_classes=(*literature, TrustClass.INTERNAL_MEASUREMENT),
            contradiction_search_required=True,
        ),
        IntentSourcePolicy(
            policy_id="srcpol:novelty-audit",
            version=version,
            intent=ResearchIntentKind.NOVELTY_AUDIT,
            source_classes=(*literature, TrustClass.PATENT, TrustClass.TECHNICAL_ARTIFACT),
            inverted_source_classes=(TrustClass.PATENT, TrustClass.WEB),
            # Novelty is cheap to claim and expensive to retract once published: the threshold
            # sits lower than DIAGNOSIS's.
            inverted_retrieval_threshold="NORMAL",
            global_novelty_requires=frozenset({TrustClass.PEER_REVIEWED, TrustClass.PATENT}),
        ),
        IntentSourcePolicy(
            policy_id="srcpol:cross-domain",
            version=version,
            intent=ResearchIntentKind.CROSS_DOMAIN_INNOVATION,
            source_classes=(*literature, TrustClass.TECHNICAL_ARTIFACT, *internal_first),
            inverted_source_classes=(*internal_first, TrustClass.PATENT),
        ),
        IntentSourcePolicy(
            policy_id="srcpol:replication",
            version=version,
            intent=ResearchIntentKind.REPLICATION,
            source_classes=(TrustClass.PEER_REVIEWED, TrustClass.INTERNAL_MEASUREMENT),
            inverted_source_classes=(TrustClass.PREPRINT, TrustClass.INTERNAL_RUN),
        ),
    )


class SourcePolicyRegistry:
    """One active policy per intent, and every registered version still resolvable.

    Resolvable because a bundle names `(source_policy_id, source_policy_version)`, and a policy that
    could no longer be looked up would leave every bundle retrieved under it unexplainable.
    """

    def __init__(self, policies: Iterable[IntentSourcePolicy] = ()) -> None:
        self._by_ref: dict[tuple[str, str], IntentSourcePolicy] = {}
        self._active: dict[str, IntentSourcePolicy] = {}
        for policy in policies:
            self.register(policy)

    def register(self, policy: IntentSourcePolicy) -> IntentSourcePolicy:
        key = (policy.policy_id, policy.version)
        existing = self._by_ref.get(key)
        if existing is not None and existing != policy:
            raise SourcePolicyError(
                f"a different source policy is already registered as {policy.ref}; a version is "
                "replaced by publishing a new one, not by editing the old one in place"
            )
        self._by_ref[key] = policy
        self._active[policy.intent] = policy
        return policy

    def for_intent(self, intent: str) -> IntentSourcePolicy:
        found = self._active.get(intent)
        if found is None:
            raise SourcePolicyError(
                f"no source policy is declared for research intent {intent!r} (declared: "
                f"{sorted(self._active)}). §7.5 selects evidence by intent; an undeclared intent "
                "has no rule for what may be retrieved, and a default would be a rule nobody chose"
            )
        return found

    def resolve(self, policy_id: str, version: str) -> IntentSourcePolicy:
        found = self._by_ref.get((policy_id, version))
        if found is None:
            raise SourcePolicyError(f"no source policy {policy_id}@{version} is registered")
        return found

    def __iter__(self) -> Iterator[IntentSourcePolicy]:
        return iter(sorted(self._active.values(), key=lambda p: p.intent))


__all__ = [
    "DEFAULT_STAKES_ORDER",
    "EXTERNAL_TRUST_CLASSES",
    "IntentSourcePolicy",
    "ResearchIntentKind",
    "SourcePolicyError",
    "SourcePolicyRegistry",
    "default_source_policies",
]
