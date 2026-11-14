"""Shared helpers for building a `ContextClassifier` in tests.

WHY THIS IS SHARED RATHER THAN COPIED INTO EACH SUITE. SEC-001's classification is now derived
from `ArtifactOccurrence` rows, so every test that reaches a model or an adapter has to supply a
store of occurrences. Six copies of that scaffolding would drift, and the one that drifted would
be the one whose fixture quietly labelled everything PUBLIC -- which is exactly the attack the
derivation closes.

`labelled(...)` builds a classifier over an explicit map, so a test's declared labels ARE the
data the production code reads. A test that wants an unclassifiable reference simply leaves it
out of the map, which is what a real project with no occurrence looks like.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping

from lab_brain.core.models.access import ArtifactOccurrence
from lab_brain.core.models.enums import SensitivityLabel
from lab_brain.core.models.identifiers import artifact_id_for, compute_content_hash
from lab_brain.security.classification import ContextClassifier

_INGESTED_AT = dt.datetime(2026, 9, 1, tzinfo=dt.UTC)


def artifact_id(name: str) -> str:
    """A well-formed content-addressed artifact id for a readable fixture name.

    `ArtifactOccurrence` validates the id's shape, and rightly: an occurrence naming something
    that is not a content address would be a row pointing at no bytes. So a fixture cannot use
    `"art:pub-1"`, and hashing the name gives a stable, readable-at-the-call-site id instead.
    """
    return artifact_id_for(compute_content_hash(name.encode("utf-8")))


def occurrence(
    artifact_id: str,
    project_id: str,
    label: SensitivityLabel,
    *,
    actor_id: str = "act:fixture",
) -> ArtifactOccurrence:
    return ArtifactOccurrence(
        artifact_id=artifact_id,
        project_id=project_id,
        sensitivity_label=label,
        ingested_by_actor_id=actor_id,
        ingested_at=_INGESTED_AT,
    )


def labelled(
    labels: Mapping[str, SensitivityLabel],
    *,
    project_id: str,
    attestations: Mapping[str, str] | None = None,
) -> ContextClassifier:
    """A classifier over an explicit `artifact_id -> label` map.

    An artifact absent from ``labels`` has no occurrence in this project and is therefore
    unclassifiable -- the same answer production gives, and the reason a test does not need a
    separate "missing" switch.
    """
    resolved = dict(attestations or {})

    def load_occurrence(artifact_id: str, asked_project: str) -> ArtifactOccurrence | None:
        label = labels.get(artifact_id)
        if label is None or asked_project != project_id:
            return None
        return occurrence(artifact_id, project_id, label)

    def artifact_of_attestation(attestation_id: str, asked_project: str) -> str | None:
        if asked_project != project_id:
            return None
        return resolved.get(attestation_id)

    return ContextClassifier(
        load_occurrence=load_occurrence,
        artifact_of_attestation=artifact_of_attestation,
    )


__all__ = ["artifact_id", "labelled", "occurrence"]
