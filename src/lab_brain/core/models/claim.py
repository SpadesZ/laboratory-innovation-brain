"""Claim — the identity of a scientific proposition (§17.2).

A Claim is not evidence and holds no numbers. It is the thing many sources can independently
witness. Resolving this identity *before* counting corroboration is what stops one measurement
quoted by four papers from reading as five independent supports (P22, EVI-004).
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Self

from pydantic import Field, model_validator

from lab_brain.core.models.base import CoreModel, utc_now
from lab_brain.core.models.enums import ClaimIdentityStatus
from lab_brain.core.models.identifiers import new_id


class Claim(CoreModel):
    """A scientific proposition that sources may attest to.

    Carries no ``supporting_attestation_ids`` and no ``evidence_for`` array. Support is resolved
    only through RelationJudgment (SYS-001); a parallel array here would be a second source of
    truth that nothing keeps in step with the relation table.
    """

    claim_id: str = Field(default_factory=lambda: new_id("claim"))

    #: The proposition in a normalised form, used for identity resolution. Not a display string
    #: and not a place for numbers -- values live on Attestation, under their own conditions.
    normalized_proposition: str

    #: Which DomainPack's vocabulary the proposition is written in, if any. Core does not
    #: interpret it.
    domain: str | None = None

    #: The boundaries within which the proposition is asserted, e.g. a device class or platform.
    #: Free-form because the meaning is domain-owned; comparability is decided by ConditionMatch.
    scope: dict[str, Any] = Field(default_factory=dict)

    identity_status: ClaimIdentityStatus = ClaimIdentityStatus.PROVISIONAL
    #: Set when `identity_status` is MERGED: the surviving claim this one folded into.
    merged_into_claim_id: str | None = None
    created_at: dt.datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _merge_target_is_consistent(self) -> Self:
        if self.identity_status is ClaimIdentityStatus.MERGED:
            if self.merged_into_claim_id is None:
                raise ValueError(
                    "identity_status MERGED requires merged_into_claim_id; a merged claim with "
                    "no target silently drops the attestations pointing at it"
                )
            if self.merged_into_claim_id == self.claim_id:
                raise ValueError("claim cannot be merged into itself")
        elif self.merged_into_claim_id is not None:
            raise ValueError(
                "merged_into_claim_id is only meaningful when identity_status is MERGED"
            )
        return self

    @property
    def counts_toward_corroboration(self) -> bool:
        """A provisional or merged identity cannot yet anchor an independence count.

        Counting against an unresolved identity is the double-counting EVI-004 forbids, arriving
        one step earlier than expected.
        """
        return self.identity_status is ClaimIdentityStatus.RESOLVED


__all__ = ["Claim"]
