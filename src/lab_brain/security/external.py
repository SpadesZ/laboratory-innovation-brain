"""The authorized external-effect boundary (SEC-001, §14.2, §14.3).

WHY AN OPTIONAL GATE IS NOT A GATE.

`EgressGate` decided correctly and nothing was obliged to ask it. `SourceRouter.search` called
`adapter.search` directly; `ScientificLLM.invoke` called its transport directly. SEC-001 says
external connector/model egress *requires* policy and Actor clearance — and a requirement that a
caller may decline to satisfy is a convention.

So authorization is no longer something a caller performs before the effect. It is the only way
to reach the effect:

    ExternalEffect(...)          declares WHAT is about to leave and WHERE it is going
    AuthorizedExternalRunner     the only object holding the transports
    runner.execute(effect, fn)   authorizes, and calls ``fn`` only if authorization allowed

`SourceRouter` and `ScientificLLM` take a runner as a **required constructor argument**. There is
no default and no `None` branch: a deployment that has not wired authorization cannot build the
objects that perform external effects.

LOCAL IS DECLARED, NOT INFERRED. §14.2's Private Mode has legitimate local providers and local
models, and they must keep working with no egress at all. The dangerous version of that is "no
policy configured, so this must be local" — which is exactly how an unwired production
deployment would look. So locality is a property the adapter or slot *declares*
(`ExternalReach.LOCAL`), the runner records the declaration, and a test asserts that a provider
which merely lacks a policy is refused rather than treated as local.

AUDIT WITHOUT PAYLOAD. Every refusal is recorded through `EgressAuditLog`, which is structurally
incapable of holding content — see `egress.py`. The runner never puts the material into the
decision or the log, only its digest.

THE CLASSIFICATION IS NOT THE CALLER'S TO STATE. `ExternalEffect` carries an
`EgressClassification` — the output of `ContextClassifier`, derived from `ArtifactOccurrence`
rows that ingestion wrote — rather than a `SensitivityLabel` a caller passed in. Making the gate
unbypassable while still letting the caller say what it was sending meant the gate decided
correctly about a fiction, and RESTRICTED_NDA material declared PUBLIC left the boundary with
every check passing honestly.

A CONJUNCTION, BECAUSE §14.1'S LABELS ARE CATEGORIES. Material carrying several labels is asked
about once per label, and the first refusal is the answer. This adds no policy here: the rule for
each label is still `EgressGate`'s, asked once per category rather than once per effect. The
alternative — collapsing a mixed set to "the most restrictive" — would require the ordering
`can_read_artifact` refuses to invent.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeVar

from lab_brain.core.models.enums import SensitivityLabel
from lab_brain.security.classification import ClassificationRefused, EgressClassification
from lab_brain.security.egress import (
    EgressAuditLog,
    EgressDecision,
    EgressGate,
    EgressOutcome,
    EgressRequest,
)

T = TypeVar("T")


class ExternalReach(StrEnum):
    """Whether an effect leaves the approved boundary.

    DECLARED BY THE COMPONENT, never inferred. `LOCAL` is a statement that the provider or model
    runs inside the boundary — an on-disk corpus, a model on this machine — and §14.2's Private
    Mode depends on those continuing to work. Inferring it from a missing policy would make an
    unwired deployment look exactly like a local one, which is the failure this whole module is
    about.
    """

    LOCAL = "LOCAL"
    EXTERNAL = "EXTERNAL"


class ExternalEffectRefused(Exception):
    """An external effect was refused before it happened.

    Raised rather than returned, and the transport is never reached. A returned decision would
    leave it to the caller to honour, which is the shape this module exists to remove.
    """

    def __init__(self, decision: EgressDecision) -> None:
        super().__init__(f"{decision.reason_code}: {decision.detail}")
        self.decision = decision


@dataclass(frozen=True)
class ExternalEffect:
    """A declaration of what is about to leave, and where to.

    ``material`` is the content itself so the runner can digest it. It is never copied into a
    decision or a log — `EgressDecision` has no content field.

    ``classification`` comes from `ContextClassifier` and is refused at construction if it is not
    usable. There is no `SensitivityLabel` parameter here at all, which is the point: an effect
    over unclassifiable material is unrepresentable rather than merely rejected later, so no
    branch anywhere has to remember to check it.
    """

    project_id: str
    actor_id: str
    provider_id: str
    classification: EgressClassification
    material: str
    reach: ExternalReach = ExternalReach.EXTERNAL

    def __post_init__(self) -> None:
        if not self.classification.usable:
            raise ClassificationRefused(self.classification)

    @property
    def labels(self) -> tuple[SensitivityLabel, ...]:
        """The categories this effect must be authorized for, in a stable order.

        Sorted so a refusal names the same label every run: an audit entry whose reason depends
        on set iteration order is one nobody can diff between two incidents.
        """
        return tuple(sorted(self.classification.labels, key=lambda label: label.value))

    def _request(self, label: SensitivityLabel) -> EgressRequest:
        return EgressRequest(
            project_id=self.project_id,
            actor_id=self.actor_id,
            provider_id=self.provider_id,
            sensitivity=label,
            content=self.material,
        )


#: The decision recorded for an effect that never left the boundary. A real decision object
#: rather than `None`, so callers and auditors see one uniform shape and a local path still has
#: a digest recorded against it.
def _local_decision(effect: ExternalEffect) -> EgressDecision:
    return EgressDecision(
        outcome=EgressOutcome.ALLOW,
        reason_code="LOCAL_EFFECT_NO_EGRESS",
        detail=(
            f"{effect.provider_id} is declared LOCAL, so nothing leaves the approved boundary "
            "(§14.2 Private Mode). Declared by the component, never inferred from a missing "
            "policy"
        ),
        content_digest=effect._request(effect.labels[0]).content_digest,
    )


class AuthorizedExternalRunner:
    """The only way an external side effect happens.

    ``execute`` is the whole interface: it authorizes, and calls the effect **only** on ALLOW.
    There is no `authorize()` that returns a verdict for a caller to act on, because that is the
    signature that lets a caller ignore it.
    """

    def __init__(self, *, gate: EgressGate, audit: EgressAuditLog) -> None:
        self._gate = gate
        self._audit = audit

    @property
    def audit(self) -> EgressAuditLog:
        return self._audit

    def execute(self, effect: ExternalEffect, perform: Callable[[], T]) -> T:
        """Authorize, then perform. Refuses by raising, and ``perform`` is never called.

        THE ORDER IS THE GUARANTEE, and it is why the adversarial tests use a spy that raises if
        entered: asserting on the returned decision would pass equally against an implementation
        that called the transport first and refused afterwards.
        """
        decision = self.authorize(effect)
        if not decision.permitted:
            raise ExternalEffectRefused(decision)
        return perform()

    def authorize(self, effect: ExternalEffect) -> EgressDecision:
        """The decision, exposed for auditing and for UX surfaces. Never a permission to proceed.

        Callers that want the effect use `execute`. This exists so a health page or an error
        surface can explain *why* a provider is unreachable for this actor without performing
        anything.

        EVERY LABEL, AND THE FIRST REFUSAL WINS. §14.1's labels are categories rather than a
        ladder, so material carrying several of them has to satisfy the policy for each. The rule
        per label is entirely `EgressGate`'s -- this loop adds none -- and it stops at the first
        BLOCK so a refusal names a real label rather than a summary nobody can act on.
        """
        if effect.reach is ExternalReach.LOCAL:
            return _local_decision(effect)

        allowed: EgressDecision | None = None
        for label in effect.labels:
            decision = self._gate.evaluate(effect._request(label))
            if not decision.permitted:
                # §17.23: a POLICY_BLOCK emits an audit event rather than being retried. Recorded
                # here rather than by the caller, because a caller that forgot would satisfy the
                # gate and not the requirement.
                self._audit.record(decision, actor_id=effect.actor_id)
                return decision
            allowed = decision
        # `labels` is never empty -- `ExternalEffect` refuses an unusable classification at
        # construction -- so this is the last ALLOW rather than a default.
        assert allowed is not None
        return allowed


__all__ = [
    "AuthorizedExternalRunner",
    "ExternalEffect",
    "ExternalEffectRefused",
    "ExternalReach",
]
