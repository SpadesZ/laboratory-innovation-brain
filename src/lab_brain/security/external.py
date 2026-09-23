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
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeVar

from lab_brain.core.models.enums import SensitivityLabel
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
    """

    project_id: str
    actor_id: str
    provider_id: str
    sensitivity: SensitivityLabel
    material: str
    reach: ExternalReach = ExternalReach.EXTERNAL


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
        content_digest=EgressRequest(
            project_id=effect.project_id,
            actor_id=effect.actor_id,
            provider_id=effect.provider_id,
            sensitivity=effect.sensitivity,
            content=effect.material,
        ).content_digest,
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
        """
        if effect.reach is ExternalReach.LOCAL:
            return _local_decision(effect)

        decision = self._gate.evaluate(
            EgressRequest(
                project_id=effect.project_id,
                actor_id=effect.actor_id,
                provider_id=effect.provider_id,
                sensitivity=effect.sensitivity,
                content=effect.material,
            )
        )
        if not decision.permitted:
            # §17.23: a POLICY_BLOCK emits an audit event rather than being retried. Recorded
            # here rather than by the caller, because a caller that forgot would satisfy the gate
            # and not the requirement.
            self._audit.record(decision, actor_id=effect.actor_id)
        return decision


__all__ = [
    "AuthorizedExternalRunner",
    "ExternalEffect",
    "ExternalEffectRefused",
    "ExternalReach",
]
