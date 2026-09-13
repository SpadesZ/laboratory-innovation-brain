"""The artifact read gate (SEC-002, §14.1, §14.4).

Every refusal below is a separate way the previous shape could have said yes. The gate answers one
question -- *may this actor read these bytes in this project* -- and it needs all three parts of the
question, which is exactly what risk R-7 made impossible: with ``project_id`` and
``sensitivity_label`` living on the globally content-addressed artifact row, "in this project" had
no representation, and the answer defaulted to whichever project ingested the bytes first.

FAIL-CLOSED MEANS THE ABSENCE OF A REASON TO ALLOW IS A DENIAL.

    no membership          not "no policy applies", a denial
    empty clearance set    not "unrestricted", a denial -- and it is the DB column default
    no occurrence          the artifact existing globally is not it being present here
    mismatched project     on either the membership or the occurrence
    inactive membership    revocation without deleting the audit trail

CLEARANCE IS A SET, NOT A LEVEL. §14.1's labels are categories of handling rather than a security
ladder, and ``SensitivityLabel`` happens to be declared most-restrictive-first, so writing
``label >= clearance`` would look right and silently widen every grant. ``CONFIDENTIAL_LAB``
(unpublished lab work) does not contain ``INTERNAL`` (meeting notes); they are different kinds of
thing. Access is exact membership.

This module is pure: no I/O, no clock, no ambient state. The caller loads the occurrence and the
membership and passes them in, so the decision can be replayed from an audit record rather than
re-derived against a database that has since changed.
"""

from __future__ import annotations

from dataclasses import dataclass

from lab_brain.core.models.access import ArtifactOccurrence, ProjectMembership


@dataclass(frozen=True)
class AccessDecision:
    """A verdict plus the reason for it.

    ``reason`` is populated on allow as well as deny. §17.24 wants a refusal a user can act on, and
    SEC-002 wants the decision auditable -- a bare boolean records nothing about *why* access was
    granted, which is the question an incident review actually asks.
    """

    allowed: bool
    reason: str

    def __bool__(self) -> bool:
        return self.allowed


def can_read_artifact(
    actor_id: str,
    project_id: str,
    occurrence: ArtifactOccurrence | None,
    membership: ProjectMembership | None,
) -> AccessDecision:
    """Decide whether ``actor_id`` may read the artifact as it exists in ``project_id``.

    Order matters for the message, not the verdict: membership is checked first so an outsider is
    told they are not a member rather than being told the artifact is absent, which would leak
    whether the project holds it.
    """
    if membership is None:
        return AccessDecision(
            False,
            f"{actor_id} is not a member of {project_id}; membership is required before any "
            "artifact in a project can be read",
        )
    if membership.actor_id != actor_id or membership.project_id != project_id:
        # A membership for someone else, or for a different project, is not a membership here.
        # Checking this rather than trusting the caller's lookup: the gate is the last line, and a
        # repository bug that returned the wrong row must not become an authorisation bug.
        return AccessDecision(
            False,
            f"{actor_id} is not a member of {project_id}; the supplied membership is "
            f"{membership.actor_id} in {membership.project_id}",
        )
    if not membership.active:
        return AccessDecision(
            False,
            f"{actor_id}'s membership of {project_id} is not active; access was revoked and the "
            "row is retained only so the audit trail survives",
        )

    if occurrence is None:
        return AccessDecision(
            False,
            f"there is no occurrence of that artifact in {project_id}. The artifact may exist "
            "globally -- content identity is shared -- but presence in one project grants nothing "
            "in another (R-7)",
        )
    if occurrence.project_id != project_id:
        return AccessDecision(
            False,
            f"the supplied occurrence belongs to a different project ({occurrence.project_id}, "
            f"not {project_id}); its label classifies that project's copy, not this one",
        )

    if not membership.clears(occurrence.sensitivity_label):
        held = ", ".join(sorted(label.value for label in membership.sensitivity_clearance))
        return AccessDecision(
            False,
            f"{actor_id} lacks clearance for {occurrence.sensitivity_label.value} in {project_id} "
            f"(holds: {held or 'none'}). Clearance is exact: a label not listed is not granted, "
            "and no label implies another",
        )

    return AccessDecision(
        True,
        f"{actor_id} is an active member of {project_id} with "
        f"{occurrence.sensitivity_label.value} clearance, and the artifact has an occurrence there",
    )


__all__ = ["AccessDecision", "can_read_artifact"]
