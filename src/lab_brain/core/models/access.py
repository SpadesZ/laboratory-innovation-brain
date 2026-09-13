"""Actor, project membership and project-scoped artifact occurrence (§14.4, SEC-002).

WHY `ArtifactOccurrence` EXISTS — risk R-7.

`artifact_id` is globally content-addressed and `artifacts.content_hash` carries a UNIQUE index,
because content identity is the point: the same bytes are the same artifact everywhere. M0a then put
``project_id`` and ``sensitivity_label`` on that same row, which quietly made two unrelated claims
share one slot.

The consequence is not a missing check. It is that the question cannot be asked. A foundry PDK
document classified ``RESTRICTED_NDA`` in project A, re-uploaded into project B, is *the same row*:
content-hash duplicate detection hands B a reference to A's artifact, and every subsequent check
reading ``artifact.sensitivity_label`` consults A's answer about B's copy. Whichever project
ingested first owns the classification for everyone.

So the two facts separate:

    Artifact             global. These bytes, this hash, this lineage, these rights.
    ArtifactOccurrence   per project. These bytes are present in THIS project, under THIS label,
                         ingested by THIS actor.

One artifact, N occurrences, N independent labels. Deciding access then requires naming the project,
which is the property the old shape could not express.
"""

from __future__ import annotations

import datetime as dt

from pydantic import Field, field_validator

from lab_brain.core.models.base import CoreModel, utc_now
from lab_brain.core.models.enums import ActorType, SensitivityLabel
from lab_brain.core.models.identifiers import parse_content_hash


class Actor(CoreModel):
    """A human, service account or agent role (§14.4).

    ``active`` rather than deletion: revoking access must not erase who held it. An audit asking
    "who could read this in March" needs the row to still exist.
    """

    actor_id: str
    actor_type: ActorType
    display_name: str | None = None
    active: bool = True
    created_at: dt.datetime = Field(default_factory=utc_now)


class ProjectMembership(CoreModel):
    """What one actor may do in one project.

    ``sensitivity_clearance`` is a **set**, not a level. §14.1's labels are categories of handling
    rather than a ladder: ``CONFIDENTIAL_LAB`` is unpublished lab work and ``INTERNAL`` is meeting
    notes, and neither contains the other. Modelling them as an ordered rank would mean granting one
    silently granted others -- and because the enum happens to be declared most-restrictive-first,
    that mistake would look correct in a code review.

    The default is the empty set: a membership grants nothing until clearance is stated. This
    mirrors the ``'{}'`` column default in migration 001, so an actor added directly in SQL starts
    fail-closed too.
    """

    actor_id: str
    project_id: str
    role: str
    sensitivity_clearance: frozenset[SensitivityLabel] = frozenset()
    approval_scopes: frozenset[str] = frozenset()
    active: bool = True
    granted_at: dt.datetime = Field(default_factory=utc_now)
    granted_by_actor_id: str | None = None

    def clears(self, label: SensitivityLabel) -> bool:
        """Exact set membership. See the class docstring for why this is not a comparison."""
        return label in self.sensitivity_clearance


class ArtifactOccurrence(CoreModel):
    """The presence of one artifact's bytes in one project, under that project's label.

    Immutable like every other core model. Reclassification is a new occurrence row plus an
    event, not an in-place edit -- the same reason belief state is event-sourced (P14, EPI-003):
    a label that can be overwritten cannot answer "what was this classified as when it was sent".
    """

    artifact_id: str
    project_id: str
    #: Required, no default. P28 wants unclassified data treated as strictest, and a field that
    #: defaults to anything can be forgotten. Requiring it means an unclassified occurrence cannot
    #: be constructed; the admission gate applies FAIL_CLOSED_SENSITIVITY explicitly in M1.
    sensitivity_label: SensitivityLabel
    ingested_by_actor_id: str | None = None
    ingested_at: dt.datetime = Field(default_factory=utc_now)

    @field_validator("artifact_id")
    @classmethod
    def _must_be_content_addressed(cls, value: str) -> str:
        """An occurrence of something that is not a content-addressed artifact is meaningless."""
        if not value.startswith("art:"):
            raise ValueError(
                f"artifact_id {value!r} is not content-addressed; an occurrence must point at an "
                "'art:' identity so the bytes it refers to are unambiguous"
            )
        parse_content_hash(value.removeprefix("art:"))
        return value

    @property
    def occurrence_key(self) -> tuple[str, str]:
        """Identity of the occurrence: the artifact *and* the project, never one alone."""
        return (self.artifact_id, self.project_id)


__all__ = ["Actor", "ArtifactOccurrence", "ProjectMembership"]
