"""The artifact read gate (SEC-002, §14.1, §14.4).

Every refusal below is a separate way the previous shape could have said yes. The gate answers one
question -- *may this actor read these bytes in this project* -- and it needs all three parts of the
question, which is exactly what risk R-7 made impossible: with ``project_id`` and
``sensitivity_label`` living on the globally content-addressed artifact row, "in this project" had
no representation, and the answer defaulted to whichever project ingested the bytes first.

FAIL-CLOSED MEANS THE ABSENCE OF A REASON TO ALLOW IS A DENIAL.

    unresolved actor       an unidentified request cannot be authorised
    wrong artifact         the occurrence must be an occurrence of the identity being asked about
    inactive actor         the account is disabled globally; every grant it holds is suspended
    no membership          not "no policy applies", a denial
    empty clearance set    not "unrestricted", a denial -- and it is the DB column default
    no occurrence          the artifact existing globally is not it being present here
    mismatched project     on either the membership or the occurrence
    inactive membership    revocation without deleting the audit trail

`Actor.active` and `ProjectMembership.active` are separate facts and both are required. Disabling
an account is the global action; revoking a membership is the per-project one. Checking only the
second means a centrally disabled credential keeps every grant it already held.

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

from lab_brain.core.models.access import Actor, ArtifactOccurrence, ProjectMembership


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
    actor: Actor | None,
    artifact_id: str,
    project_id: str,
    occurrence: ArtifactOccurrence | None,
    membership: ProjectMembership | None,
) -> AccessDecision:
    """Decide whether ``actor`` may read ``artifact_id`` as it exists in ``project_id``.

    ``artifact_id`` is the identity the caller is *asking about*, and the occurrence must be an
    occurrence of it. Without that binding the gate answers about whatever record it was handed: a
    lookup keyed on the wrong id, or a cache returning a neighbouring row, would let a PUBLIC
    seminar deck authorise reading a RESTRICTED_NDA document, with every individual check passing
    honestly on the wrong record.

    ``actor`` is a required parameter, not an optional one that defaults to skipping the identity
    check. An optional identity check is not a check: the caller who forgets it gets a pass rather
    than an error, which is the failure mode every other guard in this repository was built to
    remove.

    Order matters for the message, not the verdict. The actor is resolved first, so a deactivated
    credential is never told whether the project holds the artifact -- answering "no occurrence
    here" to a disabled account leaks the contents of a project it has no standing in. Then
    membership, so an outsider learns they are not a member rather than learning what is inside.
    """
    if actor is None:
        return AccessDecision(
            False,
            "the requesting actor could not be resolved; an unidentified request cannot be "
            "authorised (§14.4: no governance without 'who')",
        )
    actor_id = actor.actor_id
    if not actor.active:
        # Distinct from an inactive membership, and the distinction is the point. Deactivating an
        # account is the global, immediate action -- a departed researcher, a compromised service
        # credential, a revoked agent role -- and it must not require walking every project to
        # revoke each membership one at a time. Checking only the membership left a centrally
        # disabled account holding every grant it already had.
        return AccessDecision(
            False,
            f"actor {actor_id} is not active; the account is disabled globally, so every grant it "
            "holds is suspended regardless of project membership",
        )

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
            f"there is no occurrence of {artifact_id} in {project_id}. The artifact may exist "
            "globally -- content identity is shared -- but presence in one project grants nothing "
            "in another (R-7)",
        )
    if occurrence.project_id != project_id:
        return AccessDecision(
            False,
            f"the supplied occurrence belongs to a different project ({occurrence.project_id}, "
            f"not {project_id}); its label classifies that project's copy, not this one",
        )
    if occurrence.artifact_id != artifact_id:
        # Checked before the label, deliberately. Clearance is evaluated against whatever
        # occurrence is supplied, so a substituted-but-readable record would pass the clearance
        # check honestly -- on the wrong artifact. Binding identity first also means the refusal
        # names the real problem instead of blaming clearance.
        return AccessDecision(
            False,
            f"the supplied occurrence is for a different artifact ({occurrence.artifact_id}), "
            f"not the requested {artifact_id}; holding one occurrence in a project is not holding "
            "the one that was asked for",
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
