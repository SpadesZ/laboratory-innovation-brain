"""Two-tier error disclosure (UX-003, §17.24, ADR-0009, SEC-001/SEC-002).

THREE RULES, and each one closes a different leak.

    technical_detail_ref is NOT inlined in the default payload. Expanding it is an authorization
    decision, not a UI toggle: it requires an ACL scope (VIEW_TECHNICAL_DIAGNOSTICS) checked
    server-side (SEC-002). Technical detail may contain NDA filenames, private repository paths,
    restricted prompt fragments and query content; leaking it bypasses SEC-001.

    Technical detail MUST be redacted against the requesting Actor's sensitivity_clearance before
    return; redaction MUST preserve trace_id / job_id / span_id so the audit trail survives.

    error_id lookup MUST be scoped by project membership. An error_id from another project
    returns not-found, never a permission-denied that confirms existence.

THE THIRD IS THE SUBTLE ONE. "Permission denied" for a resource in another project is an oracle:
an attacker enumerating ids learns which exist from the difference between two refusals, and the
existence of an error id in a project they cannot see is itself information (which projects are
active, roughly how much is failing). So a cross-project lookup returns the *same* answer as a
lookup for an id that was never issued. `ErrorNotFound` carries no distinction, and
`test_a_cross_project_lookup_is_indistinguishable_from_a_missing_one` compares the two responses
field by field rather than only checking the exception type.

WHY THIS IS A SERVICE AND NOT A FORMATTER. §26's T-UX-003 asks for the expansion to be denied
*server-side*. A formatting helper that takes an "include_technical" flag has already lost: the
decision is then the caller's, and every caller is a place to get it wrong. `DiagnosticsService`
owns the lookup, the scope check, the clearance redaction and the not-found semantics together,
and there is no path through it that returns detail without having checked all four.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from lab_brain.core.models.access import ProjectMembership
from lab_brain.core.models.enums import SensitivityLabel
from lab_brain.surface.catalog import MessageCatalog, RenderedMessage, render
from lab_brain.surface.errors import ErrorRecord, Remediation, remediations_for

#: The scope §17.24 names. A constant rather than a literal at each call site, because a typo in
#: a scope string is a silent grant: the comparison simply never matches nothing, and a
#: mis-spelled *required* scope would deny everyone rather than grant everyone -- but a
#: mis-spelled *held* scope in a test fixture would hide a real grant bug.
VIEW_TECHNICAL_SCOPE = "VIEW_TECHNICAL_DIAGNOSTICS"


class ErrorNotFound(Exception):
    """No such error reference *that you can see*.

    Deliberately one exception for two situations -- the id does not exist, and the id exists in
    a project you are not a member of. Splitting them would rebuild the oracle §17.24 forbids.
    """


@dataclass(frozen=True)
class TechnicalDetail:
    """The expanded tier. Every field here is potentially sensitive except the trace refs."""

    detail_ref: str
    sensitivity: SensitivityLabel
    component: str
    message: str
    stack_ref: str | None = None
    source_path: str | None = None
    prompt_fragment: str | None = None


@dataclass(frozen=True)
class DisclosurePayload:
    """What the service returns. ``technical`` is present only when all four checks passed."""

    message: RenderedMessage
    remediation_actions: tuple[Remediation, ...]
    trace_id: str
    job_id: str | None = None
    span_id: str | None = None
    technical: TechnicalDetail | None = None
    #: True when detail existed, was asked for, and was withheld. The user is told that there IS
    #: more rather than being left to wonder -- without being told what.
    technical_withheld: bool = False
    withheld_reason_code: str | None = None


def redact(detail: TechnicalDetail, clearance: frozenset[SensitivityLabel]) -> TechnicalDetail:
    """Blank the sensitive fields an actor is not cleared for.

    REDACTION, NOT REFUSAL. §17.24 requires the *detail* to be redacted and the trace references
    preserved, which is a different outcome from denying the expansion entirely: a support
    engineer without NDA clearance still needs `trace_id`/`job_id`/`span_id` to correlate the
    incident. Returning nothing would break the audit trail the rule explicitly protects.

    `component` survives because it names a subsystem, not content -- "FigureParser" tells you
    where to look and nothing about the document.
    """
    if _permits(clearance, detail.sensitivity):
        return detail
    return TechnicalDetail(
        detail_ref=detail.detail_ref,
        sensitivity=detail.sensitivity,
        component=detail.component,
        message="[redacted: insufficient sensitivity clearance]",
        stack_ref=detail.stack_ref,
        source_path=None,
        prompt_fragment=None,
    )


def _permits(clearance: frozenset[SensitivityLabel], required: SensitivityLabel) -> bool:
    """Whether ``clearance`` reaches ``required``.

    DELEGATED TO `ProjectMembership.clears`, which is the same predicate `can_read_artifact`
    uses. It used to be a separate ordered comparison here -- which agreed with the canonical one
    and was the dangerous kind of duplication: two copies of a rule that agree today and are
    edited separately. §14.1's labels are categories rather than a ladder, so an ordered
    comparison was also the shape most likely to be "improved" into `>=` and silently widen every
    grant.

    Fail-closed on an empty clearance set, which the canonical predicate already gives: an actor
    with no recorded clearance sees nothing classified, and empty is the column default.
    """
    return ProjectMembership(
        actor_id="_",
        project_id="_",
        role="_",
        sensitivity_clearance=clearance,
    ).clears(required)


class DiagnosticsService:
    """The production surface for UX-003. One path, four checks, no flags.

    There is no ``include_technical`` parameter. The caller says who is asking and what they are
    asking for; the service decides what comes back. A flag would move the decision to the
    caller, and §26 requires it to be made server-side.
    """

    def __init__(
        self,
        *,
        catalog: MessageCatalog,
        load_error: Callable[[str], ErrorRecord | None],
        load_detail: Callable[[str], TechnicalDetail | None],
        membership_of: Callable[[str, str], ProjectMembership | None],
    ) -> None:
        self._catalog = catalog
        self._load_error = load_error
        self._load_detail = load_detail
        self._membership_of = membership_of

    def default_payload(
        self, error_id: str, *, actor_id: str, project_id: str
    ) -> DisclosurePayload:
        """Tier one. Never contains technical detail, whatever the actor holds."""
        record = self._resolve(error_id, actor_id=actor_id, project_id=project_id)
        return DisclosurePayload(
            message=render(
                self._catalog,
                record.reason_code,
                error_id=record.error_id,
                technical_detail_ref=record.technical_detail_ref,
            ),
            remediation_actions=remediations_for(record.error_class),
            trace_id=record.trace_id,
            job_id=record.job_id,
            span_id=record.span_id,
        )

    def expand(self, error_id: str, *, actor_id: str, project_id: str) -> DisclosurePayload:
        """Tier two. Requires the scope, then redacts against clearance.

        The order matters: scope first, because an actor without it must not learn whether
        detail exists, let alone how sensitive it is.
        """
        record = self._resolve(error_id, actor_id=actor_id, project_id=project_id)
        membership = self._membership_of(actor_id, project_id)
        payload = self.default_payload(error_id, actor_id=actor_id, project_id=project_id)

        if membership is None or VIEW_TECHNICAL_SCOPE not in membership.approval_scopes:
            return DisclosurePayload(
                message=payload.message,
                remediation_actions=payload.remediation_actions,
                trace_id=payload.trace_id,
                job_id=payload.job_id,
                span_id=payload.span_id,
                technical=None,
                technical_withheld=True,
                withheld_reason_code="DIAGNOSTICS_SCOPE_REQUIRED",
            )

        if record.technical_detail_ref is None:
            return payload
        detail = self._load_detail(record.technical_detail_ref)
        if detail is None:
            return payload

        return DisclosurePayload(
            message=payload.message,
            remediation_actions=payload.remediation_actions,
            trace_id=payload.trace_id,
            job_id=payload.job_id,
            span_id=payload.span_id,
            technical=redact(detail, frozenset(membership.sensitivity_clearance)),
        )

    def _resolve(self, error_id: str, *, actor_id: str, project_id: str) -> ErrorRecord:
        """Membership first, then existence, and the two failures are indistinguishable.

        Checking membership before looking the id up matters: a lookup that ran first would make
        the response *time* differ between a real id in another project and a nonexistent one,
        which rebuilds a weaker version of the same oracle.
        """
        if self._membership_of(actor_id, project_id) is None:
            raise ErrorNotFound(error_id)
        record = self._load_error(error_id)
        if record is None or record.project_id != project_id:
            raise ErrorNotFound(error_id)
        return record


__all__ = [
    "VIEW_TECHNICAL_SCOPE",
    "DiagnosticsService",
    "DisclosurePayload",
    "ErrorNotFound",
    "TechnicalDetail",
    "redact",
]
