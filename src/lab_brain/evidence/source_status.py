"""Retraction / erratum / version status for external reported evidence (EVI-008, §6.21).

WHAT §6.21 ASKS FOR, AND THE ONE WORD THAT MATTERS.

    外部 reported evidence 要支撐重大 belief revision 前，**應**通過：
      1. source-work version 檢查(preprint vs 正式版)
      2. retraction / erratum 檢查
      3. source-work dedup(避免同一 work 重複計數)
    檢查狀態 MUST 被記錄(EVI-008)，即使檢查結果是 UNKNOWN。

The check itself is a SHOULD. **Recording its status is a MUST, including when the status is
UNKNOWN.** That asymmetry is the whole requirement, and it exists because the failure it prevents
is silent: a system that could not reach the retraction registry, and therefore recorded nothing,
is indistinguishable six months later from one that checked and found the paper fine.

SO "UNAVAILABLE" IS NOT "VALID", AND THIS MODULE REFUSES TO LET IT BECOME SO.

`SourceStatusUnavailable` is a distinct outcome from `ACTIVE`, it is recorded as
`SOURCE_UNAVAILABLE`, and no policy shipped here maps it to ALLOW. The convenient implementation
-- treat a lookup failure as "no retraction found" -- produces exactly the record §6.21 is
written against. Note that "no retraction found" and "could not ask" are the same *bytes* from
most registries: an empty result set. Distinguishing them is the provider's job, and the protocol
below forces it by having `lookup` return a report or raise, never `None`-meaning-both.

DEDUP IS NOT HERE. §6.21's third clause is source-work dedup, which `EVI-004` already owns in
`source_work_resolution`. Implementing it again here would be a second answer to "are these the
same work", and the two would disagree the first time one was changed.

WHAT DECIDES. `SourcePolicy` maps a status to an outcome. It is data, not code, because §26 says
the fixture must "block **or** flag ... per SourcePolicy" -- the requirement is that the policy
decides and the decision is traceable, not that retraction always blocks.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from lab_brain.core.models.enums import SourceWorkStatus
from lab_brain.core.models.source_work import RetractionCheck, SourceWork


class RevisionOutcome(StrEnum):
    """What a recorded status permits for a *major* belief revision.

    ``NEEDS_HUMAN_REVIEW`` is the one that must exist. Without it every uncertain status has to be
    forced into ALLOW or BLOCK, and both are wrong: blocking on every unreachable registry stops
    research, and allowing on one makes the check decorative. It is the same reasoning §8.2.1
    applies to `INCOMPARABLE`.
    """

    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"


class SourceStatusError(RuntimeError):
    """A provider could not answer. Raised, never returned as an empty result.

    Deliberately not a return value: an empty result set is what a registry returns for "this
    paper has no retraction notice", and a provider that signalled failure the same way would
    make the two indistinguishable at the one point where the difference matters.
    """


@dataclass(frozen=True)
class SourceStatusReport:
    """What a provider found."""

    status: SourceWorkStatus
    #: Where the notice lives, so a human can read it. A RETRACTED status with no locator is a
    #: claim about a paper with no way to check the claim.
    notice_locator: str | None = None
    #: For SUPERSEDED: the work that replaces this one (preprint -> journal version).
    superseded_by_source_work_id: str | None = None
    #: The registry or service consulted, recorded so a stale answer can be attributed.
    checked_against: str = "unknown-provider"


class SourceStatusProvider(Protocol):
    """A retraction/erratum registry.

    ``lookup`` returns a report or raises ``SourceStatusError``. There is no third option, and
    that is the point -- see the module docstring.
    """

    def provider_id(self) -> str: ...

    def lookup(self, work: SourceWork) -> SourceStatusReport: ...


#: The default policy. Every status has an entry: a status missing from the map would fall through
#: to whatever the lookup returned, which is how "unavailable" becomes "fine".
#:
#: RETRACTED blocks. ERRATUM_ISSUED and SUPERSEDED flag rather than block -- an erratum usually
#: corrects a detail and the paper's other results stand, and a preprint superseded by its journal
#: version is normally still citable. Which of the two a deployment wants is a policy choice; what
#: is not a choice is that UNKNOWN and SOURCE_UNAVAILABLE never reach ALLOW.
DEFAULT_SOURCE_POLICY: dict[SourceWorkStatus, RevisionOutcome] = {
    SourceWorkStatus.ACTIVE: RevisionOutcome.ALLOW,
    SourceWorkStatus.RETRACTED: RevisionOutcome.BLOCK,
    SourceWorkStatus.WITHDRAWN: RevisionOutcome.BLOCK,
    SourceWorkStatus.ERRATUM_ISSUED: RevisionOutcome.NEEDS_HUMAN_REVIEW,
    SourceWorkStatus.SUPERSEDED: RevisionOutcome.NEEDS_HUMAN_REVIEW,
    SourceWorkStatus.UNKNOWN: RevisionOutcome.NEEDS_HUMAN_REVIEW,
    SourceWorkStatus.SOURCE_UNAVAILABLE: RevisionOutcome.NEEDS_HUMAN_REVIEW,
}

#: Statuses that mean "we do not know", as opposed to "we know and it is fine". Kept as a named
#: set so the rule "an unknown status is never ALLOW" can be asserted against the policy rather
#: than re-derived by every reader.
INDETERMINATE_STATUSES: frozenset[SourceWorkStatus] = frozenset(
    {SourceWorkStatus.UNKNOWN, SourceWorkStatus.SOURCE_UNAVAILABLE}
)


@dataclass(frozen=True)
class SourcePolicy:
    """A named, versioned mapping from status to outcome.

    Versioned because §17.20's `PriorArtSearchRecord` records a `source_policy_version`, and a
    decision whose policy nobody can reconstruct is not auditable. Validated on construction: a
    policy that allowed a major revision on an indeterminate status would be the exact defect
    EVI-008 exists to prevent, so it cannot be built.
    """

    policy_id: str = "source_policy.default"
    version: str = "1.0.0"
    outcomes: dict[SourceWorkStatus, RevisionOutcome] | None = None

    def __post_init__(self) -> None:
        table = self.outcomes if self.outcomes is not None else DEFAULT_SOURCE_POLICY
        missing = set(SourceWorkStatus) - set(table)
        if missing:
            raise ValueError(
                f"source policy {self.policy_id} has no outcome for "
                f"{sorted(s.value for s in missing)}; a status with no entry falls through to "
                "whatever the lookup returned, which is how 'unavailable' becomes 'fine'"
            )
        permissive = [s for s in INDETERMINATE_STATUSES if table[s] is RevisionOutcome.ALLOW]
        if permissive:
            raise ValueError(
                f"source policy {self.policy_id} maps {sorted(s.value for s in permissive)} to "
                "ALLOW. §6.21 requires the check status to be recorded precisely so that 'we "
                "could not ask' is distinguishable from 'we asked and it is fine'; allowing on "
                "it erases the distinction the record was kept for"
            )

    def outcome_for(self, status: SourceWorkStatus) -> RevisionOutcome:
        table = self.outcomes if self.outcomes is not None else DEFAULT_SOURCE_POLICY
        return table[status]


@dataclass(frozen=True)
class RevisionDecision:
    """Why a major revision was allowed, blocked or escalated."""

    outcome: RevisionOutcome
    status: SourceWorkStatus
    policy_id: str
    policy_version: str
    reason: str

    @property
    def permitted(self) -> bool:
        return self.outcome is RevisionOutcome.ALLOW


def check_source_work(
    work: SourceWork,
    provider: SourceStatusProvider,
    *,
    now: dt.datetime,
) -> RetractionCheck:
    """Consult ``provider`` and return the check to record on the work.

    ALWAYS RETURNS A CHECK. A provider that raises produces `SOURCE_UNAVAILABLE` with the
    timestamp and the provider it failed against -- not an exception propagated to a caller who
    would then have nothing to store. "MUST be recorded, even when the result is UNKNOWN" is not
    satisfiable by a function that can decline to produce a result.

    The failure is *recorded*, not swallowed: `SOURCE_UNAVAILABLE` is a status no shipped policy
    maps to ALLOW, so a registry outage stops a major revision rather than silently permitting it.
    """
    try:
        report = provider.lookup(work)
    except SourceStatusError as exc:
        return RetractionCheck(
            status=SourceWorkStatus.SOURCE_UNAVAILABLE,
            checked_at=now,
            checked_against=f"{provider.provider_id()}: {exc}",
        )
    return RetractionCheck(
        status=report.status,
        checked_at=now,
        checked_against=report.checked_against,
        notice_locator=report.notice_locator,
        superseded_by_source_work_id=report.superseded_by_source_work_id,
    )


def evaluate_major_revision(
    work: SourceWork,
    *,
    policy: SourcePolicy | None = None,
) -> RevisionDecision:
    """Decide whether ``work`` may support a major belief revision (§6.21, EVI-008).

    Reads the *recorded* check on the work rather than performing a lookup. That split is
    deliberate and mirrors `v3.3-a13`'s: checking is an action with a timestamp and a provider,
    deciding is a pure function of the record. A decision function that also looked things up
    could not be re-run to audit a past decision, because the registry would have moved on.

    A work that was never checked carries `RetractionCheck()`, whose status defaults to UNKNOWN --
    so "nobody ran the check" and "the check said unknown" reach the same outcome. They are
    genuinely the same epistemic situation, and the reason string distinguishes them for whoever
    has to act.
    """
    active = policy or SourcePolicy()
    check = work.retraction_check
    outcome = active.outcome_for(check.status)

    if check.checked_at is None:
        reason = (
            f"source work {work.source_work_id} has no recorded status check. §6.21 requires the "
            "check status to be recorded before external reported evidence supports a major "
            "belief revision"
        )
    elif check.status is SourceWorkStatus.RETRACTED:
        locator = check.notice_locator or "no notice locator recorded"
        reason = (
            f"source work {work.source_work_id} is RETRACTED ({locator}), checked against "
            f"{check.checked_against} at {check.checked_at.isoformat()}"
        )
    elif check.status is SourceWorkStatus.SUPERSEDED:
        successor = check.superseded_by_source_work_id or "an unrecorded successor"
        reason = (
            f"source work {work.source_work_id} is SUPERSEDED by {successor}; the superseding "
            "version is what a major revision should rest on"
        )
    else:
        reason = (
            f"source work {work.source_work_id} is {check.status.value}, checked against "
            f"{check.checked_against} at {check.checked_at.isoformat()}"
        )

    return RevisionDecision(
        outcome=outcome,
        status=check.status,
        policy_id=active.policy_id,
        policy_version=active.version,
        reason=reason,
    )


__all__ = [
    "DEFAULT_SOURCE_POLICY",
    "INDETERMINATE_STATUSES",
    "RevisionDecision",
    "RevisionOutcome",
    "SourcePolicy",
    "SourceStatusError",
    "SourceStatusProvider",
    "SourceStatusReport",
    "check_source_work",
    "evaluate_major_revision",
]
