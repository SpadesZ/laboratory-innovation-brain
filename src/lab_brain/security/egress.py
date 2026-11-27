"""Egress policy and licence gating (SEC-001, SEC-004, §14.1, §14.2, §14.3, §14.5).

TWO REQUIREMENTS, ONE MODULE, because both answer "may this material leave, or enter, a context
where it can no longer be controlled" -- and both fail the same way when they fail: silently, with
a plausible-looking result.

SEC-001. RESTRICTED_NDA/CONFIDENTIAL context MUST NOT leave the approved boundary; external
connector/model egress requires policy + Actor clearance, otherwise fail closed and emit audit
evidence.

THE AUDIT EVIDENCE MUST NOT CONTAIN THE PAYLOAD. This is the part that is easy to get exactly
backwards. An audit trail quoting the NDA text it stopped from leaving has copied that text into
a log -- usually with weaker access control than the store it came from -- and the refusal has
become the leak. `EgressDecision` carries a content DIGEST and never the content, and
`AuditLog.record` refuses a note long enough to hold a payload.

SEC-004. External code 保存 license_class = PERMISSIVE | COPYLEFT | PROPRIETARY | UNKNOWN；
UNKNOWN/COPYLEFT 原始碼不得默認進入 code-generation context，除非 project policy 明確允許.

UNKNOWN IS NOT PERMISSIVE. The convenient reading -- "we could not identify a licence, so there
probably isn't one to worry about" -- is exactly inverted: an unidentified licence is more likely
to be restrictive than less, and a generated artefact carrying copyleft code nobody identified is
a legal problem discovered at publication. `DEFAULT_CODE_POLICY` permits PERMISSIVE only, and a
policy is a *declaration* with an approver, so permitting UNKNOWN is possible and attributable.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from lab_brain.core.models.enums import LicenseClass, SensitivityLabel

#: §14.1's table, as a rule rather than prose. RESTRICTED_NDA is 禁止外部 API / cloud model;
#: CONFIDENTIAL_LAB is 預設 local；需 explicit project policy. Both therefore refuse by default,
#: and the difference is whether a policy can lift the refusal -- which `EgressPolicy` expresses.
NEVER_EGRESS: frozenset[SensitivityLabel] = frozenset({SensitivityLabel.RESTRICTED_NDA})

#: Requires an explicit project policy AND actor clearance.
POLICY_GATED_EGRESS: frozenset[SensitivityLabel] = frozenset({SensitivityLabel.CONFIDENTIAL_LAB})

#: The `ProjectMembership.approval_scopes` entry that authorises declaring a project's own
#: external-model egress policy (`012f`). A named scope, as `BUDGET_OVERRUN` is: granted explicitly
#: to a membership, or absent.
LLM_EGRESS_SCOPE = "LLM_EGRESS"


class PrivacyMode(StrEnum):
    """§14.2's three modes."""

    PRIVATE = "PRIVATE"
    RESEARCH = "RESEARCH"
    NOVELTY_AUDIT = "NOVELTY_AUDIT"


class EgressOutcome(StrEnum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"


@dataclass(frozen=True)
class EgressPolicy:
    """A project's declared egress rules, with an author.

    `declared_by_actor_id` is required for the reason `011e` requires it of a queue policy: a
    policy with no author is a permission nobody granted, and the service account that acted on
    it would look like the source of the decision.
    """

    policy_id: str
    version: str
    project_id: str
    mode: PrivacyMode
    declared_by_actor_id: str
    #: Labels this project has explicitly approved for external use. RESTRICTED_NDA is refused
    #: even if listed -- see `_check`, and the test that pins it.
    permitted_labels: frozenset[SensitivityLabel] = frozenset({SensitivityLabel.PUBLIC})
    #: Providers approved for this project. Empty means none: §14.2's Private Mode is "No egress".
    approved_providers: frozenset[str] = frozenset()


@dataclass(frozen=True)
class EgressRequest:
    """What is being sent, where, by whom.

    ``content`` is present so the gate can digest it and is NEVER copied into the decision.
    """

    project_id: str
    actor_id: str
    provider_id: str
    sensitivity: SensitivityLabel
    content: str

    @property
    def content_digest(self) -> str:
        return f"sha256:{hashlib.sha256(self.content.encode('utf-8')).hexdigest()}"


@dataclass(frozen=True)
class EgressDecision:
    """Why egress was allowed or refused.

    NO CONTENT FIELD, and that is the design. Everything here is safe to write to an audit log
    with weaker access control than the store the content came from -- which is where audit logs
    usually live.
    """

    outcome: EgressOutcome
    reason_code: str
    detail: str
    content_digest: str
    policy_id: str | None = None
    policy_version: str | None = None

    @property
    def permitted(self) -> bool:
        return self.outcome is EgressOutcome.ALLOW


class EgressGate:
    """SEC-001. Fail-closed, and the refusal leaves evidence without leaving the payload."""

    def __init__(
        self,
        *,
        policy_for: Callable[[str], EgressPolicy | None],
        clearance_of: Callable[[str, str], frozenset[SensitivityLabel]],
    ) -> None:
        self._policy_for = policy_for
        self._clearance_of = clearance_of

    def evaluate(self, request: EgressRequest) -> EgressDecision:
        digest = request.content_digest

        # 1. The absolute rule first. §14.1: RESTRICTED_NDA is 禁止外部 API / cloud model, with
        # no policy exception -- so this is checked before the policy is even loaded. A policy
        # that could permit it would make the strongest label the weakest guarantee.
        if request.sensitivity in NEVER_EGRESS:
            return EgressDecision(
                outcome=EgressOutcome.BLOCK,
                reason_code="EGRESS_BLOCKED_BY_POLICY",
                detail=(
                    f"{request.sensitivity.value} content may not reach an external provider "
                    "under any project policy (§14.1). Use a local model or tool"
                ),
                content_digest=digest,
            )

        policy = self._policy_for(request.project_id)
        if policy is None:
            return EgressDecision(
                outcome=EgressOutcome.BLOCK,
                reason_code="EGRESS_BLOCKED_BY_POLICY",
                detail=(
                    f"project {request.project_id} has no declared egress policy, so no external "
                    "use has been approved. Absence of a rule is not permission (§14.3)"
                ),
                content_digest=digest,
            )

        if policy.mode is PrivacyMode.PRIVATE:
            return EgressDecision(
                outcome=EgressOutcome.BLOCK,
                reason_code="EGRESS_BLOCKED_BY_POLICY",
                detail=f"project {request.project_id} is in Private Mode: §14.2 allows no egress",
                content_digest=digest,
                policy_id=policy.policy_id,
                policy_version=policy.version,
            )

        if request.provider_id not in policy.approved_providers:
            return EgressDecision(
                outcome=EgressOutcome.BLOCK,
                reason_code="EGRESS_BLOCKED_BY_POLICY",
                detail=(
                    f"{request.provider_id} is not an approved provider for {request.project_id}"
                ),
                content_digest=digest,
                policy_id=policy.policy_id,
                policy_version=policy.version,
            )

        if request.sensitivity not in policy.permitted_labels:
            return EgressDecision(
                outcome=EgressOutcome.BLOCK,
                reason_code="EGRESS_BLOCKED_BY_POLICY",
                detail=(
                    f"{request.sensitivity.value} is not in this project's permitted labels; "
                    "§14.1 defaults CONFIDENTIAL_LAB to local unless a policy says otherwise"
                ),
                content_digest=digest,
                policy_id=policy.policy_id,
                policy_version=policy.version,
            )

        # 2. Policy permits the label; the ACTOR still has to be cleared for it. Both, because
        # §14.3 requires policy AND Actor clearance -- a project may approve a class of material
        # without every member being allowed to send it.
        clearance = self._clearance_of(request.actor_id, request.project_id)
        if request.sensitivity not in clearance:
            return EgressDecision(
                outcome=EgressOutcome.BLOCK,
                reason_code="EGRESS_CLEARANCE_MISSING",
                detail=(
                    f"actor {request.actor_id} is not cleared for "
                    f"{request.sensitivity.value} in {request.project_id}"
                ),
                content_digest=digest,
                policy_id=policy.policy_id,
                policy_version=policy.version,
            )

        return EgressDecision(
            outcome=EgressOutcome.ALLOW,
            reason_code="EGRESS_PERMITTED",
            detail=f"{request.sensitivity.value} approved for {request.provider_id}",
            content_digest=digest,
            policy_id=policy.policy_id,
            policy_version=policy.version,
        )


# ---------------------------------------------------------------------------
# SEC-004
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CodePolicy:
    """Which licence classes a project permits in code-generation context.

    A DECLARATION WITH AN AUTHOR, for the same reason `EgressPolicy` is. §14.5 permits UNKNOWN
    and COPYLEFT only 除非 project policy 明確允許 -- "explicitly permits" means somebody said
    so, and the record has to show who.
    """

    policy_id: str
    version: str
    project_id: str
    declared_by_actor_id: str
    permitted: frozenset[LicenseClass] = frozenset({LicenseClass.PERMISSIVE})


#: The default. PERMISSIVE only -- UNKNOWN and COPYLEFT are what §14.5 names, and PROPRIETARY is
#: excluded because permitting it by default would be stranger still.
DEFAULT_CODE_POLICY = frozenset({LicenseClass.PERMISSIVE})


@dataclass(frozen=True)
class CodeArtifact:
    """External code arriving at a generation context."""

    artifact_id: str
    license_class: LicenseClass
    license_identifier: str | None = None
    provenance: str | None = None


@dataclass(frozen=True)
class CodeAdmission:
    permitted: bool
    reason_code: str
    detail: str
    license_class: LicenseClass


def may_enter_generation_context(
    artifact: CodeArtifact, policy: CodePolicy | None
) -> CodeAdmission:
    """SEC-004. UNKNOWN never silently becomes permissive.

    The failure this prevents: an implementation treating "no licence recorded" as "no licence
    restriction". An unidentified licence is more likely to be restrictive than less, and a
    generated artefact carrying unidentified copyleft is a legal problem discovered at
    publication -- by which time it is in a paper.

    `provenance` is required for anything permitted. A licence class with no record of where it
    came from cannot be re-checked when the policy changes, and SEC-004 says 保存 license_class
    AND provenance.
    """
    permitted = DEFAULT_CODE_POLICY if policy is None else policy.permitted

    if artifact.license_class is LicenseClass.UNKNOWN:
        if LicenseClass.UNKNOWN not in permitted:
            return CodeAdmission(
                permitted=False,
                reason_code="LICENSE_UNKNOWN",
                detail=(
                    f"{artifact.artifact_id} has no identified licence and this project does not "
                    "explicitly permit unknown-licence code in generation context (§14.5). An "
                    "unidentified licence is not an absent one"
                ),
                license_class=artifact.license_class,
            )
    elif artifact.license_class not in permitted:
        return CodeAdmission(
            permitted=False,
            reason_code="LICENSE_BLOCKS_CODE_GENERATION",
            detail=(
                f"{artifact.artifact_id} is {artifact.license_class.value} and this project "
                f"permits {sorted(c.value for c in permitted)} in generation context"
            ),
            license_class=artifact.license_class,
        )

    if artifact.provenance is None:
        return CodeAdmission(
            permitted=False,
            reason_code="LICENSE_UNKNOWN",
            detail=(
                f"{artifact.artifact_id} records licence {artifact.license_class.value} with no "
                "provenance. SEC-004 requires both: a class nobody can trace cannot be re-checked "
                "when the policy changes"
            ),
            license_class=artifact.license_class,
        )

    return CodeAdmission(
        permitted=True,
        reason_code="LICENSE_PERMITTED",
        detail=f"{artifact.license_class.value} permitted by policy",
        license_class=artifact.license_class,
    )


@dataclass
class EgressAuditLog:
    """Audit evidence for refused egress (§17.23's POLICY_BLOCK rule, SEC-001).

    STRUCTURALLY INCAPABLE OF HOLDING A PAYLOAD. There is no content field, and `record` takes a
    decision -- which has none either. An audit log that could quote what it blocked would be the
    leak, written somewhere with weaker access control than the store it copied from.
    """

    entries: list[EgressDecision] = field(default_factory=list)
    actors: list[str] = field(default_factory=list)

    def record(self, decision: EgressDecision, *, actor_id: str) -> None:
        self.entries.append(decision)
        self.actors.append(actor_id)

    def blocked(self) -> tuple[EgressDecision, ...]:
        return tuple(e for e in self.entries if not e.permitted)


def evaluate_and_audit(
    gate: EgressGate, request: EgressRequest, log: EgressAuditLog
) -> EgressDecision:
    """The path callers use: every refusal is audited, and no payload is written.

    Bundled into one function so "audit the refusal" is not something each caller remembers.
    §17.23 requires a POLICY_BLOCK to emit an audit event rather than be retried, and a caller
    that evaluated without logging would satisfy the gate and not the requirement.
    """
    decision = gate.evaluate(request)
    if not decision.permitted:
        log.record(decision, actor_id=request.actor_id)
    return decision


def sanitised_providers(policy: EgressPolicy | None, available: Sequence[str]) -> tuple[str, ...]:
    """Which providers a project may actually reach. Empty when no policy exists."""
    if policy is None or policy.mode is PrivacyMode.PRIVATE:
        return ()
    return tuple(sorted(p for p in available if p in policy.approved_providers))


__all__ = [
    "DEFAULT_CODE_POLICY",
    "LLM_EGRESS_SCOPE",
    "NEVER_EGRESS",
    "POLICY_GATED_EGRESS",
    "CodeAdmission",
    "CodeArtifact",
    "CodePolicy",
    "EgressAuditLog",
    "EgressDecision",
    "EgressGate",
    "EgressOutcome",
    "EgressPolicy",
    "EgressRequest",
    "PrivacyMode",
    "evaluate_and_audit",
    "may_enter_generation_context",
    "sanitised_providers",
]
