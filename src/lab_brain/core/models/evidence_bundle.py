"""EvidenceBundle — the reproducible identity of one retrieval (§17.14.1, EVI-006).

A bundle is what an LLM was shown. Its hash is what makes "the model concluded X because it saw Y"
checkable later, which is the whole basis of InferenceProvenance: same prompt and same model but
different retrieval context are different inferences, and without a bundle hash they are
indistinguishable in the record.

The hash covers a *declared* field set, not the whole object. ``bundle_id`` and ``created_at`` are
excluded deliberately: two retrievals that selected the same evidence under the same policy are the
same bundle, and folding a UUID or a timestamp in would make every bundle unique and the hash
useless for the comparison it exists to support.

What IS covered, per §17.14.1 — schema version, research intent, the query, source policy and its
version, the condition filter and condition schema versions, the **ordered** attestation IDs, and
source snapshot refs.

Ordering is significant. ``ordered_attestation_ids`` is a sequence because rank affects what a model
attends to; two retrievals returning the same evidence in a different order are different bundles
and hash differently.

``canonical_hash`` and ``query_hash`` are computed fields rather than stored inputs. A stored hash
that disagrees with its content would make provenance unverifiable, so the disagreement is made
*unrepresentable* instead of merely validated — there is no way to pass one in.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Self

from pydantic import Field, computed_field, model_validator

from lab_brain.core.canonical_json import canonical_hash as _canonical_hash
from lab_brain.core.models.base import CoreModel, utc_now
from lab_brain.core.models.identifiers import new_id

#: Bumped when the hash field set or its serialization changes. Carried *inside* the hashed payload,
#: so a bundle hashed under one schema version cannot collide with one hashed under another — which
#: is what makes a future change to the field set safe rather than silent.
BUNDLE_SCHEMA_VERSION = 1

#: Fields that are deliberately NOT part of bundle identity, with the reason. Referenced by
#: T-EVI-006 so the exclusion is asserted rather than assumed.
IDENTITY_EXCLUDED_FIELDS = {
    "bundle_id": "a fresh UUID would make every bundle unique and the hash useless",
    "created_at": "the same retrieval repeated tomorrow is the same bundle",
    "retrieval_trace_id": "observability, not content",
    "project_id": "scoping, not retrieval content",
}


class ResearchIntent(CoreModel):
    """Why this retrieval happened (§7.5 / SRC-002).

    A named value rather than a Python enum: the intent is part of bundle identity and §6.16
    expects the intent set to grow, so adding one should not be a code change in core.
    """

    intent: str
    #: Decision stakes, used by SRC-002 to decide whether inverted retrieval is mandatory. Ordinal,
    #: not a probability — §8.1 rules out uncalibrated numbers in v1.
    stakes: str | None = None


class EvidenceBundle(CoreModel):
    """A hashable, reproducible record of one retrieval."""

    bundle_id: str = Field(default_factory=lambda: new_id("evidence_bundle"))
    schema_version: int = BUNDLE_SCHEMA_VERSION

    research_intent: ResearchIntent
    query_text: str

    source_policy_id: str
    source_policy_version: str

    condition_filter: dict[str, Any] = Field(default_factory=dict)
    #: Which condition schema version each filtered domain was interpreted under. A filter on
    #: `setting` means different things across schema versions, so the bundle is not reproducible
    #: without this (EVI-005).
    condition_schema_versions: dict[str, str] = Field(default_factory=dict)

    #: Ordered, and the order is part of identity.
    ordered_attestation_ids: tuple[str, ...] = ()
    source_snapshot_refs: tuple[str, ...] = ()

    retrieval_trace_id: str | None = None
    project_id: str
    created_at: dt.datetime = Field(default_factory=utc_now)

    # -- hashing ----------------------------------------------------------

    def hash_fields(self) -> dict[str, Any]:
        """The exact field set the hash is computed over.

        A method rather than an inline dict at the call site: this field set *is* the contract,
        so it needs one place to read and one place to change.
        """
        return {
            "schema_version": self.schema_version,
            "research_intent": {
                "intent": self.research_intent.intent,
                "stakes": self.research_intent.stakes,
            },
            "query_text": self.query_text,
            "source_policy_id": self.source_policy_id,
            "source_policy_version": self.source_policy_version,
            "condition_filter": self.condition_filter,
            "condition_schema_versions": self.condition_schema_versions,
            # A list, not a sorted set: order is significant.
            "ordered_attestation_ids": list(self.ordered_attestation_ids),
            "source_snapshot_refs": list(self.source_snapshot_refs),
        }

    def compute_hash(self) -> str:
        """Recompute the hash from current content.

        Exists separately from the ``canonical_hash`` property so a repository can verify a
        *stored* hash against a freshly computed one. Reading the property alone would prove
        nothing -- it is computed either way.
        """
        return _canonical_hash(self.hash_fields())

    @computed_field  # type: ignore[prop-decorator]
    @property
    def canonical_hash(self) -> str:
        """RFC 8785 canonical hash over :meth:`hash_fields`."""
        return self.compute_hash()

    @computed_field  # type: ignore[prop-decorator]
    @property
    def query_hash(self) -> str:
        """Hash of the query alone.

        Lets a bundle be matched without carrying the query text, which may itself be restricted —
        §14.3 forbids sending private identifiers or exact confidential geometry outbound.
        """
        return _canonical_hash(self.query_text)

    @model_validator(mode="before")
    @classmethod
    def _reject_supplied_hashes(cls, data: Any) -> Any:
        """Give a direct error when a caller tries to supply a derived hash.

        ``extra="forbid"`` would already reject it, but as a generic "extra inputs are not
        permitted". Round-tripping ``model_dump()`` is the common way to hit this, so the message
        should say what to do.
        """
        if not isinstance(data, dict):
            return data
        supplied = sorted({"canonical_hash", "query_hash"} & set(data))
        if supplied:
            raise ValueError(
                f"{supplied} are derived, not inputs. The hash is computed from the bundle "
                "content so a stored value cannot disagree with it. When round-tripping "
                "model_dump(), drop these keys first."
            )
        return data

    @model_validator(mode="after")
    def _attestation_ids_are_not_duplicated(self) -> Self:
        """A repeated attestation double-counts evidence inside a single bundle.

        EVI-004 resolves independence *across* sources. Listing one attestation twice in one
        retrieval defeats that before any count is reached.
        """
        seen: set[str] = set()
        duplicates: list[str] = []
        for attestation_id in self.ordered_attestation_ids:
            if attestation_id in seen:
                duplicates.append(attestation_id)
            seen.add(attestation_id)
        if duplicates:
            raise ValueError(
                f"ordered_attestation_ids contains duplicates {sorted(set(duplicates))}; one "
                "attestation appearing twice in a bundle double-counts it as evidence"
            )
        return self

    # -- comparison -------------------------------------------------------

    def is_equivalent_to(self, other: EvidenceBundle) -> bool:
        """Whether two bundles represent the same retrieval, ignoring id and timestamp."""
        return self.canonical_hash == other.canonical_hash

    @property
    def attestation_count(self) -> int:
        return len(self.ordered_attestation_ids)

    @property
    def is_empty(self) -> bool:
        """A retrieval that found nothing.

        Still a valid bundle: "we looked under this policy and found nothing" is a reproducible,
        auditable result, and suppressing it would leave no record that the search happened.
        """
        return not self.ordered_attestation_ids


__all__ = [
    "BUNDLE_SCHEMA_VERSION",
    "IDENTITY_EXCLUDED_FIELDS",
    "EvidenceBundle",
    "ResearchIntent",
]
