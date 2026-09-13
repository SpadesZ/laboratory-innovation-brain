"""Identical bytes in two projects must not carry one project's clearance into the other.

RISK R-7, and the reason P4 exists. `artifact_id` is globally content-addressed and
`artifacts.content_hash` is UNIQUE, so the same file ingested into two projects was physically one
row — carrying one `project_id` and one `sensitivity_label`. Whichever project ingested first owned
the classification. A `RESTRICTED_NDA` PDK document in project A, re-uploaded into project B by
someone with no NDA clearance, would have been *the same row*: content-hash duplicate detection
would hand B a reference to A's artifact, complete with A's label, and any check reading
`artifact.sensitivity_label` would have been consulting the wrong project's answer.

That is SEC-001 egress in the strict sense — RESTRICTED_NDA material leaving its approved boundary —
caused not by a missing check but by a data model that cannot represent the question.

So the model splits. `Artifact` is global content identity; `ArtifactOccurrence` is the
project-scoped facts: which project holds these bytes, under what label, ingested by whom. One
artifact, N occurrences, N independent labels.

These tests are written before the implementation, on purpose. A fail-closed default that has never
been observed failing closed is an assumption, and the failures here are the ones that would be
silent in production.
"""

from __future__ import annotations

import pytest

from lab_brain.core.access import AccessDecision, can_read_artifact
from lab_brain.core.models import (
    Actor,
    ActorType,
    ArtifactOccurrence,
    ProjectMembership,
    SensitivityLabel,
    artifact_id_for,
    compute_content_hash,
)

pytestmark = [pytest.mark.requirement("SEC-002"), pytest.mark.spec_test("T-SEC-002")]

SHARED_BYTES = b"foundry PDK rev 3: ring radius table"
ARTIFACT = artifact_id_for(compute_content_hash(SHARED_BYTES))

#: A different, harmless artifact in the same project. Used to show that holding *an*
#: occurrence is not holding the occurrence that was asked for.
PUBLIC_BYTES = b"seminar slides, cleared for release"
PUBLIC_ARTIFACT = artifact_id_for(compute_content_hash(PUBLIC_BYTES))

NDA_PROJECT = "proj:photonics-nda"
OPEN_PROJECT = "proj:teaching"
ALICE = "actor:alice"
BOB = "actor:bob"


def occurrence(
    project_id: str, label: SensitivityLabel, artifact_id: str = ARTIFACT
) -> ArtifactOccurrence:
    return ArtifactOccurrence(
        artifact_id=artifact_id,
        project_id=project_id,
        sensitivity_label=label,
        ingested_by_actor_id=ALICE,
    )


def actor(actor_id: str = ALICE, *, active: bool = True) -> Actor:
    return Actor(actor_id=actor_id, actor_type=ActorType.HUMAN, active=active)


def membership(actor_id: str, project_id: str, *clearance: SensitivityLabel) -> ProjectMembership:
    return ProjectMembership(
        actor_id=actor_id,
        project_id=project_id,
        role="researcher",
        sensitivity_clearance=frozenset(clearance),
    )


# --------------------------------------------------------------------------------------------
# R-7 proper: the same bytes, two projects, two independent classifications.
# --------------------------------------------------------------------------------------------


def test_the_same_bytes_can_carry_different_labels_in_different_projects():
    """The representational fix. Without it the rest of this file cannot even be expressed."""
    nda = occurrence(NDA_PROJECT, SensitivityLabel.RESTRICTED_NDA)
    teaching = occurrence(OPEN_PROJECT, SensitivityLabel.INTERNAL)

    assert nda.artifact_id == teaching.artifact_id, "content identity is global"
    assert nda.sensitivity_label is not teaching.sensitivity_label
    assert nda.occurrence_key != teaching.occurrence_key


def test_holding_the_artifact_in_one_project_grants_nothing_in_another():
    """The leak itself.

    Bob is fully cleared in the teaching project and the artifact exists globally. He must still be
    refused the NDA project's copy, because the occurrence he is entitled to is not the one he asked
    for. A check that reasoned "the artifact exists and Bob has clearance somewhere" would allow it.
    """
    decision = can_read_artifact(
        actor=actor(BOB),
        artifact_id=ARTIFACT,
        project_id=NDA_PROJECT,
        occurrence=None,  # no occurrence of these bytes in the NDA project for Bob's request
        membership=membership(BOB, OPEN_PROJECT, SensitivityLabel.INTERNAL),
    )
    assert not decision.allowed
    assert "not a member" in decision.reason


def test_clearance_in_one_project_does_not_carry_into_another():
    """Clearance is per membership, not per actor.

    Alice holds RESTRICTED_NDA clearance in the NDA project. That must not read across to the
    teaching project, where her membership grants less.
    """
    decision = can_read_artifact(
        actor=actor(),
        artifact_id=ARTIFACT,
        project_id=OPEN_PROJECT,
        occurrence=occurrence(OPEN_PROJECT, SensitivityLabel.RESTRICTED_NDA),
        membership=membership(ALICE, OPEN_PROJECT, SensitivityLabel.INTERNAL),
    )
    assert not decision.allowed
    assert "clearance" in decision.reason


# --------------------------------------------------------------------------------------------
# Fail-closed defaults. Each is a way "no decision" could become "allowed".
# --------------------------------------------------------------------------------------------


def test_no_membership_is_refused():
    """Absence of a membership row is a denial, not an absence of policy."""
    decision = can_read_artifact(
        actor=actor(BOB),
        artifact_id=ARTIFACT,
        project_id=NDA_PROJECT,
        occurrence=occurrence(NDA_PROJECT, SensitivityLabel.PUBLIC),
        membership=None,
    )
    assert not decision.allowed
    assert "not a member" in decision.reason


def test_membership_with_empty_clearance_is_refused_even_for_public():
    """An empty clearance set means *no* clearance, never *unrestricted*.

    The database default for `sensitivity_clearance` is `'{}'`, so this is the state every
    membership starts in. If empty meant unrestricted, every new member would begin fully cleared.
    """
    decision = can_read_artifact(
        actor=actor(BOB),
        artifact_id=ARTIFACT,
        project_id=OPEN_PROJECT,
        occurrence=occurrence(OPEN_PROJECT, SensitivityLabel.PUBLIC),
        membership=membership(BOB, OPEN_PROJECT),
    )
    assert not decision.allowed
    assert "clearance" in decision.reason


def test_a_missing_occurrence_is_refused_even_for_a_cleared_member():
    """The artifact existing globally is not the artifact being present here.

    Alice is cleared for RESTRICTED_NDA in the NDA project. If these bytes have no occurrence in
    that project, there is nothing for her to read, and the honest answer is a denial rather than a
    fallback to the artifact's global row.
    """
    decision = can_read_artifact(
        actor=actor(),
        artifact_id=ARTIFACT,
        project_id=NDA_PROJECT,
        occurrence=None,
        membership=membership(ALICE, NDA_PROJECT, SensitivityLabel.RESTRICTED_NDA),
    )
    assert not decision.allowed
    assert "no occurrence" in decision.reason


def test_a_membership_for_the_wrong_project_is_refused():
    """Guard against the check reading the membership without comparing its project."""
    decision = can_read_artifact(
        actor=actor(),
        artifact_id=ARTIFACT,
        project_id=NDA_PROJECT,
        occurrence=occurrence(NDA_PROJECT, SensitivityLabel.PUBLIC),
        membership=membership(ALICE, OPEN_PROJECT, SensitivityLabel.RESTRICTED_NDA),
    )
    assert not decision.allowed
    assert "not a member" in decision.reason


def test_an_occurrence_from_another_project_is_refused():
    """And the mirror: the occurrence must belong to the project being asked about."""
    decision = can_read_artifact(
        actor=actor(),
        artifact_id=ARTIFACT,
        project_id=NDA_PROJECT,
        occurrence=occurrence(OPEN_PROJECT, SensitivityLabel.PUBLIC),
        membership=membership(ALICE, NDA_PROJECT, SensitivityLabel.PUBLIC),
    )
    assert not decision.allowed
    assert "different project" in decision.reason


def test_an_inactive_membership_is_refused():
    """Revocation has to take effect without deleting the audit trail of who once had access."""
    revoked = ProjectMembership(
        actor_id=ALICE,
        project_id=NDA_PROJECT,
        role="researcher",
        sensitivity_clearance=frozenset({SensitivityLabel.RESTRICTED_NDA}),
        active=False,
    )
    decision = can_read_artifact(
        actor=actor(),
        artifact_id=ARTIFACT,
        project_id=NDA_PROJECT,
        occurrence=occurrence(NDA_PROJECT, SensitivityLabel.RESTRICTED_NDA),
        membership=revoked,
    )
    assert not decision.allowed
    assert "not active" in decision.reason


def test_an_inactive_actor_is_refused_despite_correct_membership_and_clearance():
    """The hole this rework closes.

    `Actor.active` and `ProjectMembership.active` are different facts. Deactivating an account is
    the global, immediate action -- a departed researcher, a compromised service credential, a
    revoked agent role -- and it must not require walking every project to revoke each membership
    individually. The first version of this gate checked only the membership, so an account
    disabled centrally kept every grant it already held.
    """
    decision = can_read_artifact(
        actor=actor(active=False),
        artifact_id=ARTIFACT,
        project_id=NDA_PROJECT,
        occurrence=occurrence(NDA_PROJECT, SensitivityLabel.RESTRICTED_NDA),
        membership=membership(ALICE, NDA_PROJECT, SensitivityLabel.RESTRICTED_NDA),
    )
    assert not decision.allowed
    assert "actor" in decision.reason and "not active" in decision.reason


def test_an_inactive_actor_is_refused_before_any_project_question_is_asked():
    """A disabled account must not be told whether the project holds the artifact.

    Ordering is a disclosure decision, not a style one: answering "no occurrence here" to a
    deactivated credential leaks whether a project holds a given file.
    """
    decision = can_read_artifact(
        actor=actor(active=False),
        artifact_id=ARTIFACT,
        project_id=NDA_PROJECT,
        occurrence=None,
        membership=None,
    )
    assert not decision.allowed
    assert "not active" in decision.reason
    assert "occurrence" not in decision.reason


def test_a_missing_actor_is_refused():
    """Fail closed: an unresolvable actor is a denial, not an unchecked path.

    `actor` is a required parameter rather than an optional one defaulting to None-means-skip.
    An optional identity check is not a check.
    """
    decision = can_read_artifact(
        actor=None,
        artifact_id=ARTIFACT,
        project_id=NDA_PROJECT,
        occurrence=occurrence(NDA_PROJECT, SensitivityLabel.PUBLIC),
        membership=membership(ALICE, NDA_PROJECT, SensitivityLabel.PUBLIC),
    )
    assert not decision.allowed
    assert "could not be resolved" in decision.reason


def test_the_membership_must_belong_to_the_supplied_actor():
    """Both halves of the identity must agree, or the gate is checking two different people."""
    decision = can_read_artifact(
        actor=actor(BOB),
        artifact_id=ARTIFACT,
        project_id=NDA_PROJECT,
        occurrence=occurrence(NDA_PROJECT, SensitivityLabel.RESTRICTED_NDA),
        membership=membership(ALICE, NDA_PROJECT, SensitivityLabel.RESTRICTED_NDA),
    )
    assert not decision.allowed
    assert "not a member" in decision.reason


def test_both_active_flags_are_required_independently():
    """Neither flag substitutes for the other.

    An active actor with a revoked membership and a deactivated actor with a live membership must
    both be refused -- otherwise one of the two flags is decorative.
    """
    live_actor_dead_membership = can_read_artifact(
        actor=actor(),
        artifact_id=ARTIFACT,
        project_id=NDA_PROJECT,
        occurrence=occurrence(NDA_PROJECT, SensitivityLabel.PUBLIC),
        membership=ProjectMembership(
            actor_id=ALICE,
            project_id=NDA_PROJECT,
            role="researcher",
            sensitivity_clearance=frozenset({SensitivityLabel.PUBLIC}),
            active=False,
        ),
    )
    dead_actor_live_membership = can_read_artifact(
        actor=actor(active=False),
        artifact_id=ARTIFACT,
        project_id=NDA_PROJECT,
        occurrence=occurrence(NDA_PROJECT, SensitivityLabel.PUBLIC),
        membership=membership(ALICE, NDA_PROJECT, SensitivityLabel.PUBLIC),
    )
    assert not live_actor_dead_membership.allowed
    assert not dead_actor_live_membership.allowed
    assert live_actor_dead_membership.reason != dead_actor_live_membership.reason, (
        "the two refusals must be distinguishable, or an operator cannot tell which flag to fix"
    )


def test_an_occurrence_for_a_different_artifact_is_refused():
    """The gate must answer about the artifact that was *asked for*.

    Alice is an active, fully cleared member of the NDA project, and the occurrence handed to the
    gate is a real one from that same project -- it is simply a different artifact. Without binding
    the decision to the requested identity, the gate would approve reading the NDA document on the
    strength of a PUBLIC seminar deck, and every field it checked would look correct.

    This is a caller-side mistake the gate must not inherit: one lookup keyed on the wrong id, or a
    cache returning a neighbouring row, becomes an authorisation bypass.
    """
    decision = can_read_artifact(
        actor=actor(),
        artifact_id=ARTIFACT,
        project_id=NDA_PROJECT,
        occurrence=occurrence(NDA_PROJECT, SensitivityLabel.PUBLIC, PUBLIC_ARTIFACT),
        membership=membership(ALICE, NDA_PROJECT, SensitivityLabel.PUBLIC),
    )
    assert not decision.allowed
    assert "different artifact" in decision.reason
    assert ARTIFACT in decision.reason and PUBLIC_ARTIFACT in decision.reason


def test_the_clearance_check_cannot_be_satisfied_by_a_more_permissive_neighbour():
    """The sharpest form: the substituted occurrence is one the actor genuinely may read.

    Clearance is checked against the label of whatever occurrence is supplied. Hand it a PUBLIC
    occurrence while asking for a RESTRICTED_NDA artifact and the clearance check passes honestly --
    on the wrong record. Identity has to be bound *before* the label is consulted.
    """
    decision = can_read_artifact(
        actor=actor(),
        artifact_id=ARTIFACT,
        project_id=NDA_PROJECT,
        occurrence=occurrence(NDA_PROJECT, SensitivityLabel.PUBLIC, PUBLIC_ARTIFACT),
        membership=membership(ALICE, NDA_PROJECT, SensitivityLabel.PUBLIC),
    )
    assert not decision.allowed
    assert "clearance" not in decision.reason, (
        "identity must be refused before clearance is considered, or the refusal blames the "
        "wrong thing"
    )


def test_a_matching_artifact_identity_is_allowed():
    """The gate stays passable when the occurrence really is the one requested."""
    decision = can_read_artifact(
        actor=actor(),
        artifact_id=PUBLIC_ARTIFACT,
        project_id=NDA_PROJECT,
        occurrence=occurrence(NDA_PROJECT, SensitivityLabel.PUBLIC, PUBLIC_ARTIFACT),
        membership=membership(ALICE, NDA_PROJECT, SensitivityLabel.PUBLIC),
    )
    assert decision.allowed


# --------------------------------------------------------------------------------------------
# Clearance is exact, not ordered. The enum is ordered most-restrictive-first, which invites the
# assumption that holding a stricter label implies the looser ones.
# --------------------------------------------------------------------------------------------


def test_clearance_is_a_set_membership_not_a_ranking():
    """RESTRICTED_NDA clearance alone does not confer INTERNAL access.

    §14.1's labels are categories of handling, not a security ladder: `CONFIDENTIAL_LAB` is
    unpublished lab work and `INTERNAL` is meeting notes, and neither contains the other. Treating
    the enum's declaration order as a total order would silently widen every grant.
    """
    decision = can_read_artifact(
        actor=actor(),
        artifact_id=ARTIFACT,
        project_id=NDA_PROJECT,
        occurrence=occurrence(NDA_PROJECT, SensitivityLabel.INTERNAL),
        membership=membership(ALICE, NDA_PROJECT, SensitivityLabel.RESTRICTED_NDA),
    )
    assert not decision.allowed
    assert "clearance" in decision.reason


@pytest.mark.parametrize("label", list(SensitivityLabel))
def test_every_label_requires_its_own_explicit_clearance(label):
    """No label is exempt. PUBLIC included -- the project boundary applies to all of them."""
    granted = can_read_artifact(
        actor=actor(),
        artifact_id=ARTIFACT,
        project_id=NDA_PROJECT,
        occurrence=occurrence(NDA_PROJECT, label),
        membership=membership(ALICE, NDA_PROJECT, label),
    )
    assert granted.allowed, label

    withheld = can_read_artifact(
        actor=actor(),
        artifact_id=ARTIFACT,
        project_id=NDA_PROJECT,
        occurrence=occurrence(NDA_PROJECT, label),
        membership=membership(ALICE, NDA_PROJECT),
    )
    assert not withheld.allowed, label


# --------------------------------------------------------------------------------------------
# The decision must be usable as evidence, and the gate must be passable.
# --------------------------------------------------------------------------------------------


def test_a_cleared_member_reading_their_own_project_is_allowed():
    """A gate that refuses everything is not a gate."""
    decision = can_read_artifact(
        actor=actor(),
        artifact_id=ARTIFACT,
        project_id=NDA_PROJECT,
        occurrence=occurrence(NDA_PROJECT, SensitivityLabel.RESTRICTED_NDA),
        membership=membership(ALICE, NDA_PROJECT, SensitivityLabel.RESTRICTED_NDA),
    )
    assert decision.allowed
    assert NDA_PROJECT in decision.reason


def test_every_decision_records_a_reason():
    """§17.24: a refusal the user cannot act on is a support ticket.

    Also an audit requirement -- SEC-002 wants the denial recorded, and a bare boolean cannot be
    recorded as anything useful.
    """
    for decision in (
        can_read_artifact(actor(), ARTIFACT, NDA_PROJECT, None, None),
        can_read_artifact(
            actor(),
            ARTIFACT,
            NDA_PROJECT,
            occurrence(NDA_PROJECT, SensitivityLabel.PUBLIC),
            membership(ALICE, NDA_PROJECT, SensitivityLabel.PUBLIC),
        ),
    ):
        assert isinstance(decision, AccessDecision)
        assert decision.reason.strip(), "a decision with no reason cannot be audited"


def test_the_decision_is_deterministic():
    """Same inputs, same verdict and same reason -- otherwise the audit record is not reproducible."""
    args = (
        actor(),
        ARTIFACT,
        NDA_PROJECT,
        occurrence(NDA_PROJECT, SensitivityLabel.RESTRICTED_NDA),
        membership(ALICE, NDA_PROJECT, SensitivityLabel.RESTRICTED_NDA),
    )
    first, second = can_read_artifact(*args), can_read_artifact(*args)
    assert (first.allowed, first.reason) == (second.allowed, second.reason)
