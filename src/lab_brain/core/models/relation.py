"""RelationJudgment — the single source of truth for support and contradiction (§17.8).

Nothing else in the system may express "A supports B". Not an array on Hypothesis, not a
column on Attestation. The reason is concrete: a parallel array is a second store of the same
fact that nothing keeps in step with the relation table, and when they disagree there is no way
to tell which one the belief state was computed from.

Relations are bitemporal. ``valid_from`` / ``valid_to`` record when the judgment was held to be
true, which is what lets ``as_of`` replay reconstruct the belief state of a past date instead of
reconstructing today's relations with old events (§17.12).
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Self

from pydantic import Field, model_validator

from lab_brain.core.models.base import CoreModel, utc_now
from lab_brain.core.models.enums import RelationType
from lab_brain.core.models.identifiers import new_id

#: Relation types whose meaning is an epistemic effect on the target. These require a
#: provenance trail: either supporting attestations, or an InferenceProvenance if an LLM
#: proposed the judgment (LLM-001 / AGT-010).
EPISTEMIC_RELATION_TYPES = frozenset(
    {
        RelationType.SUPPORTS,
        RelationType.CONTRADICTS,
        RelationType.TESTS,
        RelationType.PREDICTS,
    }
)

#: Relation types that assert source identity rather than epistemic effect. Used by EVI-004 to
#: collapse corroboration across manifestations of one work.
IDENTITY_RELATION_TYPES = frozenset(
    {
        RelationType.SAME_WORK_AS,
        RelationType.CITES,
        RelationType.DERIVED_FROM,
    }
)


class RelationJudgment(CoreModel):
    """A provenance-bearing judgment that two entities stand in some relation."""

    relation_id: str = Field(default_factory=lambda: new_id("relation"))
    from_entity_id: str
    to_entity_id: str
    relation_type: RelationType

    attributes: dict[str, Any] = Field(default_factory=dict)
    #: Attestations that back this judgment. For an epistemic relation this is what makes the
    #: judgment auditable rather than asserted.
    supporting_attestation_ids: tuple[str, ...] = ()
    condition_match_ref: str | None = None
    #: Required when an LLM produced the judgment (AGT-010).
    inference_provenance_id: str | None = None
    #: Required when a human asserted it, so governance actions have an owner (§14.4).
    actor_id: str | None = None

    project_id: str
    valid_from: dt.datetime = Field(default_factory=utc_now)
    valid_to: dt.datetime | None = None
    invalidation_reason: str | None = None
    created_at: dt.datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _no_self_relation(self) -> Self:
        if self.from_entity_id == self.to_entity_id:
            raise ValueError(
                f"relation {self.relation_type} from an entity to itself is not meaningful "
                f"({self.from_entity_id})"
            )
        return self

    @model_validator(mode="after")
    def _validity_interval_is_ordered(self) -> Self:
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError(
                f"valid_to {self.valid_to.isoformat()} precedes valid_from "
                f"{self.valid_from.isoformat()}; as_of replay would return this relation for "
                "no instant at all"
            )
        return self

    @model_validator(mode="after")
    def _invalidation_is_accounted_for(self) -> Self:
        """Closing a relation records why. §17.12 invalidate_relation takes a reason."""
        if self.valid_to is not None and self.invalidation_reason is None:
            raise ValueError(
                "an invalidated relation must record invalidation_reason; a silently closed "
                "judgment is indistinguishable from one that was never made"
            )
        if self.valid_to is None and self.invalidation_reason is not None:
            raise ValueError("invalidation_reason is only meaningful once valid_to is set")
        return self

    @model_validator(mode="after")
    def _epistemic_relations_carry_provenance(self) -> Self:
        """An epistemic effect with no provenance is an unsourced assertion (P7).

        SUPPORTS/CONTRADICTS/TESTS/PREDICTS move belief. Each must name either the attestations
        it rests on, the inference that produced it, or the actor who asserted it.
        """
        if self.relation_type not in EPISTEMIC_RELATION_TYPES:
            return self
        has_provenance = bool(
            self.supporting_attestation_ids or self.inference_provenance_id or self.actor_id
        )
        if not has_provenance:
            raise ValueError(
                f"relation_type {self.relation_type} requires provenance: at least one of "
                "supporting_attestation_ids, inference_provenance_id or actor_id"
            )
        return self

    def is_valid_at(self, moment: dt.datetime) -> bool:
        """Whether this judgment was held at ``moment`` -- the ``as_of`` predicate."""
        if moment < self.valid_from:
            return False
        return self.valid_to is None or moment < self.valid_to

    @property
    def is_current(self) -> bool:
        return self.valid_to is None

    @property
    def is_epistemic(self) -> bool:
        return self.relation_type in EPISTEMIC_RELATION_TYPES

    def invalidate(
        self, *, reason: str, actor_id: str, at: dt.datetime | None = None
    ) -> RelationJudgment:
        """Return a closed copy of this judgment.

        A new object rather than a mutation: the relation row is superseded, and the reason plus
        the actor who decided are part of the record (§17.12).
        """
        closed_at = at or utc_now()
        return self.model_copy(
            update={
                "valid_to": closed_at,
                "invalidation_reason": reason,
                "actor_id": actor_id,
            }
        )


__all__ = [
    "EPISTEMIC_RELATION_TYPES",
    "IDENTITY_RELATION_TYPES",
    "RelationJudgment",
]
