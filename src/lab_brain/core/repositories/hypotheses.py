"""Durable storage for competing sets, Hypothesis certificates and their Predictions (EPI-001).

WHAT THIS STORE IS NOT: an admission gate. `lab_brain.core.hypothesis_admission` decides whether a
certificate is admissible and `lab_brain.core.belief.admit_hypothesis` records the genesis event;
this module stores what was decided. The invariants a writer could violate by going around both --
an incomplete certificate, a prediction outside its OutcomeSpace, a prediction back-filled after
admission -- are refused again by `005e` and `011i`, because a store that trusted its callers would
hold only for the callers who came through Python.

THE IN-MEMORY STORE REFUSES WHAT THE DATABASE REFUSES, for the reason every fake in this repository
does: a backend-free test that passed against a fake which accepted an incomplete certificate would
be a test of the fake.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from typing import Protocol, runtime_checkable

from lab_brain.core.models.hypothesis import Hypothesis
from lab_brain.core.models.hypothesis_set import HypothesisCertificate, HypothesisSet
from lab_brain.core.models.prediction import OutcomeSpace, Prediction, bind
from lab_brain.core.repositories.budget import SqlConnection
from lab_brain.core.repositories.protocols import RepositoryError


class HypothesisStoreError(RepositoryError):
    """A set, certificate or prediction write violated an invariant."""


@runtime_checkable
class HypothesisStore(Protocol):
    def add_set(self, hypothesis_set: HypothesisSet) -> HypothesisSet: ...

    def get_set(self, set_id: str) -> HypothesisSet | None: ...

    def add_certificate(self, certificate: HypothesisCertificate) -> HypothesisCertificate: ...

    def get_certificate(self, hypothesis_id: str) -> HypothesisCertificate | None: ...

    def certificates_in_set(self, set_id: str) -> tuple[HypothesisCertificate, ...]: ...


_SET_COLUMNS = (
    "set_id",
    "project_id",
    "episode_id",
    "question",
    "research_intent",
    "stakes",
    "root_cause",
    "source_policy_id",
    "source_policy_version",
    "inverted_retrieval_required",
    "created_at",
)

_HYPOTHESIS_COLUMNS = (
    "hypothesis_id",
    "project_id",
    "hypothesis_set_id",
    "statement",
    "mechanism",
    "assumptions",
    "falsifier",
    "confounders",
    "minimal_test_ref",
    "parent_id",
    "created_in_episode",
    "inference_provenance_id",
    "authored_by_actor_id",
    "created_at",
)

_PREDICTION_COLUMNS = (
    "prediction_id",
    "project_id",
    "hypothesis_id",
    "observable_ref",
    "outcome_space_id",
    "outcome_space_version",
    "expected_outcome",
    "direction",
    "conditions",
    "conditions_schema_version",
    "relation_effect_if_observed",
    "inference_provenance_id",
    "created_at",
)


def certificate_completeness_problems(certificate: HypothesisCertificate) -> list[str]:
    """§8's admission fields, as the table checks them. Empty when complete.

    Shared by the in-memory store and the admission gate so the two cannot disagree about what
    "complete" means. The PostgreSQL CHECKs in `005e` are the third statement of the same rule, and
    `tests/integration/test_hypothesis_storage_postgres.py` holds them to it.
    """
    h = certificate.hypothesis
    problems: list[str] = []
    if not h.assumptions:
        problems.append("no assumptions")
    if not h.confounders:
        problems.append("no confounders")
    if not (h.minimal_test_ref or "").strip():
        problems.append("no minimal test")
    if not h.created_in_episode:
        problems.append("no episode")
    if h.inference_provenance_id is None and certificate.authored_by_actor_id is None:
        problems.append("no author (neither an inference nor an actor)")
    if not certificate.predictions:
        problems.append("no typed Prediction")
    return problems


class InMemoryHypothesisStore:
    """Backend-free implementation. Refuses what `005e`/`011i` refuse."""

    def __init__(self, *, outcome_space: Callable[[str, str], OutcomeSpace | None]) -> None:
        self._sets: dict[str, HypothesisSet] = {}
        self._certificates: dict[str, HypothesisCertificate] = {}
        self._outcome_space = outcome_space

    def add_set(self, hypothesis_set: HypothesisSet) -> HypothesisSet:
        existing = self._sets.get(hypothesis_set.set_id)
        if existing is not None:
            if existing != hypothesis_set:
                raise HypothesisStoreError(f"set {hypothesis_set.set_id} is append-only")
            return existing
        self._sets[hypothesis_set.set_id] = hypothesis_set
        return hypothesis_set

    def get_set(self, set_id: str) -> HypothesisSet | None:
        return self._sets.get(set_id)

    def add_certificate(self, certificate: HypothesisCertificate) -> HypothesisCertificate:
        h = certificate.hypothesis
        existing = self._certificates.get(h.hypothesis_id)
        if existing is not None:
            if existing != certificate:
                raise HypothesisStoreError(f"hypothesis {h.hypothesis_id} is append-only")
            return existing
        hypothesis_set = self._sets.get(certificate.hypothesis_set_id)
        if hypothesis_set is None or hypothesis_set.project_id != h.project_id:
            raise HypothesisStoreError(
                f"hypothesis {h.hypothesis_id} names set {certificate.hypothesis_set_id}, which "
                f"does not exist in {h.project_id}"
            )
        if hypothesis_set.episode_id != h.created_in_episode:
            raise HypothesisStoreError(
                f"hypothesis {h.hypothesis_id} was created in {h.created_in_episode} but its set "
                f"belongs to {hypothesis_set.episode_id}"
            )
        problems = certificate_completeness_problems(certificate)
        if problems:
            raise HypothesisStoreError(
                f"hypothesis {h.hypothesis_id}'s certificate is incomplete: {problems}"
            )
        for prediction in certificate.predictions:
            space = self._outcome_space(
                prediction.outcome_space_id, prediction.outcome_space_version
            )
            if space is None:
                raise HypothesisStoreError(
                    f"prediction {prediction.prediction_id} names outcome space "
                    f"{prediction.outcome_space_ref}, which is not declared"
                )
            try:
                bind(prediction, space)
            except ValueError as refused:
                raise HypothesisStoreError(str(refused)) from refused
        self._certificates[h.hypothesis_id] = certificate
        return certificate

    def get_certificate(self, hypothesis_id: str) -> HypothesisCertificate | None:
        return self._certificates.get(hypothesis_id)

    def certificates_in_set(self, set_id: str) -> tuple[HypothesisCertificate, ...]:
        return tuple(
            sorted(
                (c for c in self._certificates.values() if c.hypothesis_set_id == set_id),
                key=lambda c: (c.created_at, c.hypothesis_id),
            )
        )


class SqlHypothesisStore:
    """PostgreSQL implementation. One transaction per certificate; reads rebuild through models."""

    def __init__(self, connection: SqlConnection) -> None:
        self._connection = connection

    def add_set(self, hypothesis_set: HypothesisSet) -> HypothesisSet:
        s = hypothesis_set
        self._connection.execute(
            f"INSERT INTO hypothesis_sets ({', '.join(_SET_COLUMNS)}) "
            f"VALUES ({', '.join(['%s'] * len(_SET_COLUMNS))}) ON CONFLICT (set_id) DO NOTHING",
            (
                s.set_id,
                s.project_id,
                s.episode_id,
                s.question,
                s.research_intent,
                s.stakes,
                s.root_cause,
                s.source_policy_id,
                s.source_policy_version,
                s.inverted_retrieval_required,
                s.created_at,
            ),
        )
        stored = self.get_set(s.set_id)
        if stored != s:
            raise HypothesisStoreError(f"set {s.set_id} is already recorded differently")
        return s

    def get_set(self, set_id: str) -> HypothesisSet | None:
        row = self._connection.execute(
            f"SELECT {', '.join(_SET_COLUMNS)} FROM hypothesis_sets WHERE set_id = %s", (set_id,)
        ).fetchone()
        return (
            None
            if row is None
            else HypothesisSet.model_validate(dict(zip(_SET_COLUMNS, row, strict=True)))
        )

    def add_certificate(self, certificate: HypothesisCertificate) -> HypothesisCertificate:
        """Certificate and predictions, together or not at all.

        One transaction, because `011i` refuses a prediction on an ADMITTED hypothesis and admission
        is a separate step: a certificate written without its predictions could never be completed.
        """
        h = certificate.hypothesis
        transaction = getattr(self._connection, "transaction", None)
        if transaction is None:  # pragma: no cover - every production connection has one
            raise HypothesisStoreError("the hypothesis store needs a transactional connection")
        with transaction():
            self._connection.execute(
                f"INSERT INTO hypotheses ({', '.join(_HYPOTHESIS_COLUMNS)}) "
                f"VALUES ({', '.join(['%s'] * len(_HYPOTHESIS_COLUMNS))})",
                (
                    h.hypothesis_id,
                    h.project_id,
                    certificate.hypothesis_set_id,
                    h.statement,
                    h.mechanism,
                    list(h.assumptions),
                    h.falsifier,
                    list(h.confounders),
                    h.minimal_test_ref,
                    h.parent_id,
                    h.created_in_episode,
                    h.inference_provenance_id,
                    certificate.authored_by_actor_id,
                    certificate.created_at,
                ),
            )
            for p in certificate.predictions:
                self._connection.execute(
                    f"INSERT INTO predictions ({', '.join(_PREDICTION_COLUMNS)}) "
                    f"VALUES ({', '.join(['%s'] * len(_PREDICTION_COLUMNS))})",
                    (
                        p.prediction_id,
                        p.project_id,
                        p.hypothesis_id,
                        p.observable_ref,
                        p.outcome_space_id,
                        p.outcome_space_version,
                        p.expected_outcome,
                        p.direction,
                        json.dumps(p.conditions),
                        p.conditions_schema_version,
                        json.dumps(
                            [e.model_dump(mode="json") for e in p.relation_effect_if_observed]
                        ),
                        p.inference_provenance_id,
                        certificate.created_at,
                    ),
                )
        stored = self.get_certificate(h.hypothesis_id)
        if stored != certificate:
            raise HypothesisStoreError(
                f"hypothesis {h.hypothesis_id} did not round-trip; the stored certificate differs "
                "from the one written"
            )
        return stored

    def get_certificate(self, hypothesis_id: str) -> HypothesisCertificate | None:
        row = self._connection.execute(
            f"SELECT {', '.join(_HYPOTHESIS_COLUMNS)} FROM hypotheses WHERE hypothesis_id = %s",
            (hypothesis_id,),
        ).fetchone()
        if row is None:
            return None
        values = dict(zip(_HYPOTHESIS_COLUMNS, row, strict=True))
        predictions = self._predictions_for(hypothesis_id)
        hypothesis = Hypothesis(
            hypothesis_id=str(values["hypothesis_id"]),
            project_id=str(values["project_id"]),
            statement=str(values["statement"]),
            mechanism=str(values["mechanism"]),
            assumptions=tuple(values["assumptions"]),  # type: ignore[arg-type]
            prediction_ids=tuple(sorted(p.prediction_id for p in predictions)),
            falsifier=str(values["falsifier"]),
            confounders=tuple(values["confounders"]),  # type: ignore[arg-type]
            minimal_test_ref=values["minimal_test_ref"],  # type: ignore[arg-type]
            parent_id=values["parent_id"],  # type: ignore[arg-type]
            created_in_episode=values["created_in_episode"],  # type: ignore[arg-type]
            inference_provenance_id=values["inference_provenance_id"],  # type: ignore[arg-type]
        )
        created_at = values["created_at"]
        assert isinstance(created_at, dt.datetime)
        return HypothesisCertificate(
            hypothesis=hypothesis,
            hypothesis_set_id=str(values["hypothesis_set_id"]),
            predictions=predictions,
            authored_by_actor_id=values["authored_by_actor_id"],  # type: ignore[arg-type]
            created_at=created_at,
        )

    def certificates_in_set(self, set_id: str) -> tuple[HypothesisCertificate, ...]:
        rows = self._connection.execute(
            "SELECT hypothesis_id FROM hypotheses WHERE hypothesis_set_id = %s "
            "ORDER BY created_at, hypothesis_id",
            (set_id,),
        ).fetchall()
        found = (self.get_certificate(str(row[0])) for row in rows)
        return tuple(c for c in found if c is not None)

    def _predictions_for(self, hypothesis_id: str) -> tuple[Prediction, ...]:
        rows = self._connection.execute(
            f"SELECT {', '.join(_PREDICTION_COLUMNS)} FROM predictions WHERE hypothesis_id = %s "
            "ORDER BY prediction_id",
            (hypothesis_id,),
        ).fetchall()
        predictions = []
        for row in rows:
            values = dict(zip(_PREDICTION_COLUMNS, row, strict=True))
            values.pop("created_at")
            predictions.append(Prediction.model_validate(values))
        return tuple(predictions)


__all__ = [
    "HypothesisStore",
    "HypothesisStoreError",
    "InMemoryHypothesisStore",
    "SqlHypothesisStore",
    "certificate_completeness_problems",
]
