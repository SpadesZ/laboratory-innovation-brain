"""SourceWork — the identity of one academic work, however many times it manifests.

A preprint, the journal version, a mirror and a review copy are four Artifacts and **one**
SourceWork. That collapse is what makes corroboration counting honest: five papers citing one
measurement attest to one work, not five independent supports (§6.2, EVI-004).

The spec names SourceWork in §5.1 and Appendix D and allocates it migration 002, but gives no
field list. The shape below is derived from what EVI-004 and EVI-008 require of it: stable
external identifiers to resolve identity by, and a recorded retraction/erratum status.
"""

from __future__ import annotations

import datetime as dt
from typing import Self

from pydantic import Field, model_validator

from lab_brain.core.models.base import CoreModel, utc_now
from lab_brain.core.models.enums import (
    SourceWorkStatus,
    SourceWorkType,
    TrustClass,
)
from lab_brain.core.models.identifiers import new_id


class WorkIdentifier(CoreModel):
    """One external identifier for a work, e.g. ``doi:10.1000/xyz``.

    Kept as a typed pair rather than a free-text string so identity resolution can compare
    like with like -- a DOI match is strong evidence of same-work, a title match is not.
    """

    scheme: str
    value: str

    def __str__(self) -> str:
        return f"{self.scheme}:{self.value}"

    @model_validator(mode="after")
    def _normalise(self) -> Self:
        # DOIs are case-insensitive; comparing them case-sensitively would split one work into
        # two identities and re-inflate the corroboration count EVI-004 exists to protect.
        if self.scheme.lower() == "doi":
            object.__setattr__(self, "value", self.value.lower())
        object.__setattr__(self, "scheme", self.scheme.lower())
        return self


class RetractionCheck(CoreModel):
    """EVI-008: the check status MUST be recorded even when the result is UNKNOWN.

    An unrecorded check is indistinguishable from a passed check, which is precisely the
    ambiguity that lets a retracted source support a major belief revision.
    """

    status: SourceWorkStatus = SourceWorkStatus.UNKNOWN
    checked_at: dt.datetime | None = None
    checked_against: str | None = None
    notice_locator: str | None = None
    superseded_by_source_work_id: str | None = None

    @property
    def blocks_major_revision(self) -> bool:
        return self.status in {
            SourceWorkStatus.RETRACTED,
            SourceWorkStatus.WITHDRAWN,
        }


class SourceWork(CoreModel):
    """The identity of an academic work, independent of any particular file."""

    source_work_id: str = Field(default_factory=lambda: new_id("source_work"))
    work_type: SourceWorkType
    title: str
    identifiers: tuple[WorkIdentifier, ...] = ()
    authors: tuple[str, ...] = ()
    venue: str | None = None
    published_year: int | None = Field(default=None, ge=1600, le=2200)
    canonical_locator: str | None = None

    #: Artifacts that are manifestations of this work. A preprint PDF and the journal PDF are
    #: two entries here, not two SourceWorks.
    manifestation_artifact_ids: tuple[str, ...] = ()

    trust_class: TrustClass
    retraction_check: RetractionCheck = Field(default_factory=RetractionCheck)
    created_at: dt.datetime = Field(default_factory=utc_now)

    @property
    def status(self) -> SourceWorkStatus:
        return self.retraction_check.status

    def identifier_for(self, scheme: str) -> str | None:
        for identifier in self.identifiers:
            if identifier.scheme == scheme.lower():
                return identifier.value
        return None

    @property
    def identifier_keys(self) -> frozenset[str]:
        """Normalised ``scheme:value`` strings, for same-work resolution."""
        return frozenset(str(identifier) for identifier in self.identifiers)


__all__ = ["RetractionCheck", "SourceWork", "WorkIdentifier"]
