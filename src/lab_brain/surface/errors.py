"""Error classification and bounded retry (UX-002, §17.23, COST-001).

§17.23's opening line is the design brief: 錯誤分類的目的不是好看，而是決定「誰要動手」-- the point
of classifying an error is not presentation, it is deciding **who has to act**. Five classes, and
each one routes to a different person:

    USER_INPUT_ERROR       the researcher. Retrying a corrupt file burns budget forever.
    EXTRACTION_WARNING     a human reviewer. This is the UNKNOWN discipline working (EVI-002).
    POLICY_BLOCK           an approver. A retry loop against an ACL is indistinguishable from an
                           attack, so it emits an audit event instead.
    EXTERNAL_SERVICE_ERROR nobody -- the system retries, bounded.
    SYSTEM_ERROR           an administrator, and the system retries, bounded.

THE TWO RULES THAT ARE EASIEST TO GET WRONG, both stated outright in §17.23:

**Budget exhaustion is POLICY_BLOCK, not FAILED.** "The system is healthy; the policy stopped
it." Classifying it as a failure sends an engineer to investigate a system that is working, and
-- worse -- puts it in the auto-retry set, so the system would spend the budget it has just been
told it does not have.

**EXTRACTION_WARNING must not be rendered with failure styling.** Rendering it as an error trains
users to click ACCEPT to clear it, which silently reintroduces hallucinated completion. That is a
catalog `severity`, and the catalog carries WARNING for exactly this.

RETRY IS A FUNCTION OF THE CLASS, NOT OF THE CALLER. `may_auto_retry` takes the class and the
attempt count and nothing else, so a caller cannot argue its way into retrying a POLICY_BLOCK.
Budget is asked separately and afterwards: §17.23 says auto-retry *consumes* budget through
BudgetGate, so the gate has to be able to refuse an attempt that policy would otherwise permit --
and that refusal is itself a POLICY_BLOCK.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum


class ErrorClass(StrEnum):
    """§17.23's five classes. FROZEN -- a sixth requires an ADR.

    The stability tier is not decoration: downstream branch logic keys on this value to decide
    who is notified and whether a retry happens, so adding a member changes behaviour everywhere
    at once.
    """

    USER_INPUT_ERROR = "USER_INPUT_ERROR"
    EXTRACTION_WARNING = "EXTRACTION_WARNING"
    POLICY_BLOCK = "POLICY_BLOCK"
    EXTERNAL_SERVICE_ERROR = "EXTERNAL_SERVICE_ERROR"
    SYSTEM_ERROR = "SYSTEM_ERROR"


#: Classes §17.23 marks "MUST (bounded)" for auto-retry. Everything else is MUST NOT, and the set
#: is written as the permitted side rather than the forbidden side on purpose: a new class added
#: without thought defaults to *not* retrying, which is the safe direction.
AUTO_RETRYABLE: frozenset[ErrorClass] = frozenset(
    {ErrorClass.EXTERNAL_SERVICE_ERROR, ErrorClass.SYSTEM_ERROR}
)

#: Classes that require an audit event rather than a retry (§17.23, SEC-001/SEC-002).
AUDITED_CLASSES: frozenset[ErrorClass] = frozenset({ErrorClass.POLICY_BLOCK})


class RemediationAction(StrEnum):
    """§17.23's `action_key` vocabulary, exactly."""

    RETRY = "RETRY"
    RETRY_WITH_OCR = "RETRY_WITH_OCR"
    IGNORE_STAGE = "IGNORE_STAGE"
    MARK_UNKNOWN = "MARK_UNKNOWN"
    CORRECT_VALUE = "CORRECT_VALUE"
    ACCEPT = "ACCEPT"
    REUPLOAD = "REUPLOAD"
    REQUEST_ACCESS = "REQUEST_ACCESS"
    ESCALATE_HUMAN = "ESCALATE_HUMAN"
    VIEW_TECHNICAL = "VIEW_TECHNICAL"


@dataclass(frozen=True)
class Remediation:
    """§17.23's RemediationAction. ``label_key`` is a catalog key, never literal text."""

    action_key: RemediationAction
    label_key: str
    requires_scope: str | None = None


@dataclass(frozen=True)
class ErrorRecord:
    """§17.23's projection of `Job.structured_error` + `ExecutionSpan`.

    NOT A SECOND SOURCE OF TRUTH, which §17.23 says outright. Nothing here is authoritative: the
    class and code come from whatever failed, the attempt counts come from the Job. Constructing
    one is projection, not a write.

    ``technical_detail_ref`` is a POINTER. Inlining the detail here would put NDA filenames,
    private repository paths and prompt fragments into the object a default payload is built
    from, and `disclosure.py` would then be redacting something it had already leaked.
    """

    error_id: str
    project_id: str
    trace_id: str
    error_class: ErrorClass
    reason_code: str
    component: str
    occurred_at: dt.datetime
    attempt_count: int = 0
    max_attempts: int = 1
    next_retry_at: dt.datetime | None = None
    job_id: str | None = None
    span_id: str | None = None
    item_id: str | None = None
    technical_detail_ref: str | None = None
    remediation_actions: tuple[Remediation, ...] = ()
    resolved_at: dt.datetime | None = None

    @property
    def attempts_exhausted(self) -> bool:
        return self.attempt_count >= self.max_attempts

    @property
    def is_terminal_for_the_user(self) -> bool:
        """Whether the user is looking at a final state rather than a retry in flight."""
        return not AUTO_RETRYABLE.intersection({self.error_class}) or self.attempts_exhausted


class BudgetRefused(Exception):
    """A retry was affordable by policy and refused by budget (COST-001).

    Its own exception type because the *classification* changes: §17.23 says budget exhaustion is
    POLICY_BLOCK, not FAILED. A caller that treated this as an ordinary failure would put the
    work back in the auto-retry set and spend the budget it was just told it does not have.
    """


@dataclass(frozen=True)
class RetryDecision:
    """Whether another attempt happens, and why not when it does not."""

    retry: bool
    reason_code: str
    error_class: ErrorClass
    next_retry_at: dt.datetime | None = None
    #: Set when the decision is "stop and surface this", so UX-001 can read the terminal state.
    terminal: bool = False
    #: §17.23: POLICY_BLOCK emits an audit event instead of retrying.
    audit_required: bool = False


def may_auto_retry(error_class: ErrorClass, attempt_count: int, max_attempts: int) -> bool:
    """Policy only, and NOT sufficient on its own.

    Split deliberately: `may_auto_retry(POLICY_BLOCK, ...)` is False regardless of how much
    budget exists, and no amount of available budget may turn it True. Folding budget in here
    would make the two questions one, and the one answer would be overridable.

    A `True` here is a NECESSARY condition, never a permission. `decide_retry` is the only
    function that authorises an attempt, because it is the only one that asks the budget gate --
    and §17.23 requires both. A caller that branched on this alone would retry without ever
    consulting COST-001.
    """
    if error_class not in AUTO_RETRYABLE:
        return False
    return attempt_count < max_attempts


def decide_retry(
    record: ErrorRecord,
    *,
    now: dt.datetime,
    backoff: dt.timedelta = dt.timedelta(seconds=30),
    charge_budget: Callable[[ErrorRecord], None] | None = None,
) -> RetryDecision:
    """The whole UX-002 retry rule, in one place.

    ORDER MATTERS AND IS NOT ARBITRARY.

    1. Class first. POLICY_BLOCK and USER_INPUT_ERROR stop here and never reach the budget gate --
       asking the gate would make an ACL refusal look like a spending decision, and a retry loop
       against an ACL is what §17.23 says is indistinguishable from an attack.
    2. Attempt bound next. `max_attempts` is the Job's, so the bound is durable across process
       restarts rather than living in a worker's memory.
    3. Budget last, and only for an attempt that policy already permits. A refusal here is
       reclassified to POLICY_BLOCK with `BUDGET_EXHAUSTED`, because §17.23 is explicit that the
       system is healthy and the policy stopped it.

    `next_retry_at` is CLEARED on every terminal outcome. §17.23: "exhausted retries transition
    the surface to FAILED with next_retry_at cleared". A stale timestamp on a dead item tells a
    user to wait for something that will never happen.
    """
    if record.error_class in AUDITED_CLASSES:
        return RetryDecision(
            retry=False,
            reason_code=record.reason_code,
            error_class=ErrorClass.POLICY_BLOCK,
            next_retry_at=None,
            terminal=True,
            audit_required=True,
        )
    if record.error_class not in AUTO_RETRYABLE:
        return RetryDecision(
            retry=False,
            reason_code=record.reason_code,
            error_class=record.error_class,
            next_retry_at=None,
            terminal=True,
        )
    if record.attempts_exhausted:
        return RetryDecision(
            retry=False,
            reason_code="RETRY_LIMIT_REACHED",
            error_class=record.error_class,
            next_retry_at=None,
            terminal=True,
        )

    # NO BUDGET SEAM MEANS NO RETRY. §17.23: "Auto-retry consumes budget through BudgetGate
    # (COST-001)". An omitted gate used to mean "proceed", which made the requirement hold only
    # for callers who remembered to pass one -- and a caller that forgets gets the permissive
    # answer, which is the fail-open shape audit has now found four times in this repository.
    #
    # Classified POLICY_BLOCK rather than SYSTEM_ERROR: the system is not broken, it is
    # unauthorised to spend. That also keeps it out of AUTO_RETRYABLE, so an unwired deployment
    # cannot retry its way around the missing gate.
    if charge_budget is None:
        return RetryDecision(
            retry=False,
            reason_code="BUDGET_GATE_UNAVAILABLE",
            error_class=ErrorClass.POLICY_BLOCK,
            next_retry_at=None,
            terminal=True,
            audit_required=True,
        )

    try:
        charge_budget(record)
    except BudgetRefused:
        # Reclassified, not merely annotated. The class is what decides who acts, and a
        # budget stop needs an approver rather than an engineer.
        return RetryDecision(
            retry=False,
            reason_code="BUDGET_EXHAUSTED",
            error_class=ErrorClass.POLICY_BLOCK,
            next_retry_at=None,
            terminal=True,
            audit_required=True,
        )
    return RetryDecision(
        retry=True,
        reason_code=record.reason_code,
        error_class=record.error_class,
        next_retry_at=now + backoff,
    )


def remediations_for(error_class: ErrorClass) -> tuple[Remediation, ...]:
    """What a user may be offered. Label keys, never text (UX-006).

    `VIEW_TECHNICAL` carries its scope requirement on the action itself rather than being
    filtered out by whoever renders: an action offered and then refused is worse than one never
    offered, and the scope belongs with the action so every surface applies the same rule.
    """
    view_technical = Remediation(
        action_key=RemediationAction.VIEW_TECHNICAL,
        label_key="ACTION_VIEW_TECHNICAL",
        requires_scope="VIEW_TECHNICAL_DIAGNOSTICS",
    )
    match error_class:
        case ErrorClass.USER_INPUT_ERROR:
            return (
                Remediation(RemediationAction.REUPLOAD, "ACTION_REUPLOAD"),
                Remediation(RemediationAction.RETRY_WITH_OCR, "ACTION_RETRY_WITH_OCR"),
            )
        case ErrorClass.EXTRACTION_WARNING:
            # No ACCEPT. §17.23 warns that rendering this as an error trains users to click
            # ACCEPT to clear it, which silently reintroduces hallucinated completion -- so the
            # cheap dismissal is not offered and the honest options are.
            return (
                Remediation(RemediationAction.MARK_UNKNOWN, "ACTION_MARK_UNKNOWN"),
                Remediation(RemediationAction.CORRECT_VALUE, "ACTION_CORRECT_VALUE"),
                Remediation(RemediationAction.ESCALATE_HUMAN, "ACTION_ESCALATE_HUMAN"),
            )
        case ErrorClass.POLICY_BLOCK:
            return (Remediation(RemediationAction.REQUEST_ACCESS, "ACTION_REQUEST_ACCESS"),)
        case ErrorClass.EXTERNAL_SERVICE_ERROR:
            return (Remediation(RemediationAction.RETRY, "ACTION_RETRY"), view_technical)
        case ErrorClass.SYSTEM_ERROR:
            return (
                Remediation(RemediationAction.RETRY, "ACTION_RETRY"),
                Remediation(RemediationAction.ESCALATE_HUMAN, "ACTION_ESCALATE_HUMAN"),
                view_technical,
            )
    raise AssertionError(f"unhandled error class {error_class}")  # pragma: no cover


@dataclass
class AuditLog:
    """Where POLICY_BLOCK refusals are recorded (§17.23, SEC-001).

    DELIBERATELY CANNOT HOLD A PAYLOAD. `note` is a short operator string and there is no field
    for the content that was refused. SEC-001 requires a blocked egress to leave audit evidence
    *without* logging the restricted payload -- an audit trail that quotes the NDA text it
    stopped from leaving is the leak it was preventing, written somewhere with weaker access
    control than the thing it copied from.
    """

    entries: list[tuple[str, str, str, str]] = field(default_factory=list)

    def record(self, *, project_id: str, actor_id: str, reason_code: str, note: str) -> None:
        if len(note) > 200:
            raise ValueError(
                "audit notes are short operator strings. A note long enough to hold a payload is "
                "how the restricted content ends up in the audit log (SEC-001)"
            )
        self.entries.append((project_id, actor_id, reason_code, note))

    def for_project(self, project_id: str) -> tuple[tuple[str, str, str, str], ...]:
        return tuple(e for e in self.entries if e[0] == project_id)


__all__ = [
    "AUDITED_CLASSES",
    "AUTO_RETRYABLE",
    "AuditLog",
    "BudgetRefused",
    "ErrorClass",
    "ErrorRecord",
    "Remediation",
    "RemediationAction",
    "RetryDecision",
    "decide_retry",
    "may_auto_retry",
    "remediations_for",
]
