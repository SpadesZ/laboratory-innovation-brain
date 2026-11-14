"""Durable storage for Positions, CritiqueReports and debate records (§17.14.1, SRC-002, LLM-002).

TWO FACTS THIS STORE WILL NOT TAKE ON TRUST, because §7.2 and §7.6 are only worth anything if they
are facts rather than assertions:

    a Position was formed from its bundle    the Position's inference was produced from the bundle
                                             the Position names -- provenance hash == bundle hash
    a critique is independent                 `differs_in` equals the axes derived from the two
                                             provenance rows (`independence_axes`), and is not empty

Both are checked here for the in-memory store and by `005e`'s triggers for PostgreSQL, with one
derivation (`independence_axes`) mirrored by the SQL so the two cannot disagree about what
"independent" means.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from lab_brain.core.critique_gate import CritiqueAxis
from lab_brain.core.models.debate import (
    CritiqueReport,
    DebateRecord,
    FalsifierChallenge,
    Objection,
    Position,
    ProposedPrediction,
)
from lab_brain.core.models.evidence_bundle import EvidenceBundle
from lab_brain.core.models.inference import InferenceProvenance
from lab_brain.core.repositories.budget import SqlConnection
from lab_brain.core.repositories.protocols import RepositoryError


class DebateStoreError(RepositoryError):
    """A debate object write violated an invariant."""


#: The order `differs_in` is stored in. Fixed, so equal sets compare equal as tuples.
AXIS_ORDER: tuple[CritiqueAxis, ...] = (
    CritiqueAxis.RETRIEVAL_BUNDLE,
    CritiqueAxis.REASONING_POLICY,
    CritiqueAxis.MODEL_ROUTE,
)


def independence_axes(
    original: InferenceProvenance, critique: InferenceProvenance
) -> tuple[str, ...]:
    """§7.6's three axes along which ``critique`` differs from ``original``. Mirrored by `005e`.

    MODEL_ROUTE is the (model, version, slot) triple -- §7.3's route. Provider alone is not an axis:
    §7.6 opens by saying 不同 provider 不是科學獨立性的充分條件.
    """
    axes: list[CritiqueAxis] = []
    if critique.evidence_bundle_hash != original.evidence_bundle_hash:
        axes.append(CritiqueAxis.RETRIEVAL_BUNDLE)
    if critique.source_policy_version != original.source_policy_version:
        axes.append(CritiqueAxis.REASONING_POLICY)
    if (critique.model_id, critique.model_version, critique.logical_slot) != (
        original.model_id,
        original.model_version,
        original.logical_slot,
    ):
        axes.append(CritiqueAxis.MODEL_ROUTE)
    return tuple(axis.value for axis in AXIS_ORDER if axis in axes)


@runtime_checkable
class DebateStore(Protocol):
    def add_position(self, position: Position) -> Position: ...

    def get_position(self, position_id: str) -> Position | None: ...

    def add_critique(self, critique: CritiqueReport) -> CritiqueReport: ...

    def get_critique(self, critique_id: str) -> CritiqueReport | None: ...

    def critiques_targeting(
        self, project_id: str, hypothesis_id: str
    ) -> tuple[CritiqueReport, ...]: ...

    def add_debate_record(self, record: DebateRecord) -> DebateRecord: ...

    def get_debate_record(self, debate_id: str) -> DebateRecord | None: ...

    def records_for_set(self, set_id: str) -> tuple[DebateRecord, ...]: ...


class InMemoryDebateStore:
    """Backend-free implementation. Refuses what `005e` refuses."""

    def __init__(
        self,
        *,
        bundle: Callable[[str], EvidenceBundle | None],
        provenance: Callable[[str], InferenceProvenance | None],
        hypothesis_exists: Callable[[str, str], bool],
    ) -> None:
        self._bundle = bundle
        self._provenance = provenance
        self._hypothesis_exists = hypothesis_exists
        self._positions: dict[str, Position] = {}
        self._critiques: dict[str, CritiqueReport] = {}
        self._records: dict[str, DebateRecord] = {}

    def add_position(self, position: Position) -> Position:
        if position.position_id in self._positions:
            if self._positions[position.position_id] != position:
                raise DebateStoreError(f"position {position.position_id} is append-only")
            return position
        bundle = self._bundle(position.bundle_id)
        provenance = self._provenance(position.inference_provenance_id)
        if bundle is None or provenance is None:
            raise DebateStoreError(
                f"position {position.position_id} names a bundle or an inference that does not "
                "resolve"
            )
        if bundle.project_id != position.project_id:
            raise DebateStoreError(
                f"position {position.position_id} names another project's bundle"
            )
        if provenance.evidence_bundle_hash != bundle.canonical_hash:
            raise DebateStoreError(
                f"position {position.position_id} names bundle {position.bundle_id} but its "
                f"inference was produced from bundle hash {provenance.evidence_bundle_hash}; the "
                "bundle a position names must be the one its model saw (§7.2)"
            )
        missing = [
            ref
            for ref in position.hypothesis_refs
            if not self._hypothesis_exists(position.project_id, ref)
        ]
        if missing:
            raise DebateStoreError(
                f"position {position.position_id} references unknown hypotheses {missing}"
            )
        self._positions[position.position_id] = position
        return position

    def get_position(self, position_id: str) -> Position | None:
        return self._positions.get(position_id)

    def add_critique(self, critique: CritiqueReport) -> CritiqueReport:
        if critique.critique_id in self._critiques:
            if self._critiques[critique.critique_id] != critique:
                raise DebateStoreError(f"critique {critique.critique_id} is append-only")
            return critique
        original = self._provenance(critique.original_inference_id)
        own = self._provenance(critique.inference_provenance_id)
        if original is None or own is None:
            raise DebateStoreError(
                f"critique {critique.critique_id} cites an inference that does not resolve"
            )
        derived = independence_axes(original, own)
        if not derived:
            raise DebateStoreError(
                f"critique {critique.critique_id} differs from {critique.original_inference_id} in "
                "no axis; §7.6 requires a different bundle, reasoning policy or model route"
            )
        if tuple(sorted(critique.differs_in)) != tuple(sorted(derived)):
            raise DebateStoreError(
                f"critique {critique.critique_id} claims independence along "
                f"{list(critique.differs_in)} but its provenance differs along {list(derived)}"
            )
        primary = self._bundle(critique.primary_bundle_id)
        if primary is None or primary.project_id != critique.project_id:
            raise DebateStoreError(f"critique {critique.critique_id} names no valid primary bundle")
        if critique.inverted_bundle_id is not None:
            inverted = self._bundle(critique.inverted_bundle_id)
            if inverted is None or inverted.project_id != critique.project_id:
                raise DebateStoreError(
                    f"critique {critique.critique_id} names no valid inverted bundle"
                )
            if inverted.canonical_hash == primary.canonical_hash:
                raise DebateStoreError(
                    f"critique {critique.critique_id}'s inverted bundle is the same retrieval as "
                    "its primary bundle; §7.2's inverted retrieval is the Critic's OWN retrieval"
                )
        missing = [
            t for t in critique.target_ids if not self._hypothesis_exists(critique.project_id, t)
        ]
        if missing:
            raise DebateStoreError(f"critique {critique.critique_id} targets unknown {missing}")
        self._critiques[critique.critique_id] = critique
        return critique

    def get_critique(self, critique_id: str) -> CritiqueReport | None:
        return self._critiques.get(critique_id)

    def critiques_targeting(
        self, project_id: str, hypothesis_id: str
    ) -> tuple[CritiqueReport, ...]:
        return tuple(
            sorted(
                (
                    c
                    for c in self._critiques.values()
                    if c.project_id == project_id and hypothesis_id in c.target_ids
                ),
                key=lambda c: (c.created_at, c.critique_id),
            )
        )

    def add_debate_record(self, record: DebateRecord) -> DebateRecord:
        if record.debate_id in self._records:
            if self._records[record.debate_id] != record:
                raise DebateStoreError(f"debate record {record.debate_id} is append-only")
            return record
        self._records[record.debate_id] = record
        return record

    def get_debate_record(self, debate_id: str) -> DebateRecord | None:
        return self._records.get(debate_id)

    def records_for_set(self, set_id: str) -> tuple[DebateRecord, ...]:
        return tuple(
            sorted(
                (r for r in self._records.values() if r.set_id == set_id),
                key=lambda r: (r.created_at, r.debate_id),
            )
        )


_POSITION_COLUMNS = (
    "position_id",
    "project_id",
    "role_id",
    "episode_id",
    "hypothesis_refs",
    "mechanism_view",
    "supporting_relation_ids",
    "uncertainties",
    "proposed_predictions",
    "confounders",
    "bundle_id",
    "inference_provenance_id",
    "created_at",
)

_CRITIQUE_COLUMNS = (
    "critique_id",
    "project_id",
    "episode_id",
    "target_ids",
    "objections",
    "alternative_mechanisms",
    "falsifier_challenges",
    "blocking_conflicts",
    "primary_bundle_id",
    "inverted_bundle_id",
    "original_inference_id",
    "differs_in",
    "inference_provenance_id",
    "created_at",
)

_RECORD_COLUMNS = (
    "debate_id",
    "project_id",
    "episode_id",
    "set_id",
    "rounds",
    "max_rounds",
    "stop_reason",
    "escalation_triggers",
    "position_ids",
    "critique_ids",
    "position_diversity",
    "critic_bundle_divergence",
    "critic_changed_final_set",
    "initial_hypothesis_ids",
    "surviving_hypothesis_ids",
    "surviving_hypothesis_diversity",
    "additional_evidence_items",
    "additional_token_count",
    "metric_versions",
    "gate_evaluations",
    "per_round",
    "created_at",
)


def _json_default(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"{type(value).__name__} is not JSON serialisable")


class SqlDebateStore:
    """PostgreSQL implementation. The independence and bundle checks are `005e`'s triggers."""

    def __init__(self, connection: SqlConnection) -> None:
        self._connection = connection

    def add_position(self, position: Position) -> Position:
        p = position
        self._connection.execute(
            f"INSERT INTO positions ({', '.join(_POSITION_COLUMNS)}) "
            f"VALUES ({', '.join(['%s'] * len(_POSITION_COLUMNS))}) "
            "ON CONFLICT (position_id) DO NOTHING",
            (
                p.position_id,
                p.project_id,
                p.role_id,
                p.episode_id,
                list(p.hypothesis_refs),
                p.mechanism_view,
                list(p.supporting_relation_ids),
                list(p.uncertainties),
                json.dumps([pp.model_dump(mode="json") for pp in p.proposed_predictions]),
                list(p.confounders),
                p.bundle_id,
                p.inference_provenance_id,
                p.created_at,
            ),
        )
        stored = self.get_position(p.position_id)
        if stored != p:
            raise DebateStoreError(f"position {p.position_id} is already recorded differently")
        return p

    def get_position(self, position_id: str) -> Position | None:
        row = self._connection.execute(
            f"SELECT {', '.join(_POSITION_COLUMNS)} FROM positions WHERE position_id = %s",
            (position_id,),
        ).fetchone()
        if row is None:
            return None
        values: dict[str, Any] = dict(zip(_POSITION_COLUMNS, row, strict=True))
        values["proposed_predictions"] = tuple(
            ProposedPrediction.model_validate(pp) for pp in values["proposed_predictions"]
        )
        return Position.model_validate(values)

    def add_critique(self, critique: CritiqueReport) -> CritiqueReport:
        c = critique
        self._connection.execute(
            f"INSERT INTO critique_reports ({', '.join(_CRITIQUE_COLUMNS)}) "
            f"VALUES ({', '.join(['%s'] * len(_CRITIQUE_COLUMNS))}) "
            "ON CONFLICT (critique_id) DO NOTHING",
            (
                c.critique_id,
                c.project_id,
                c.episode_id,
                list(c.target_ids),
                json.dumps([o.model_dump(mode="json") for o in c.objections]),
                list(c.alternative_mechanisms),
                json.dumps([f.model_dump(mode="json") for f in c.falsifier_challenges]),
                list(c.blocking_conflicts),
                c.primary_bundle_id,
                c.inverted_bundle_id,
                c.original_inference_id,
                list(c.differs_in),
                c.inference_provenance_id,
                c.created_at,
            ),
        )
        stored = self.get_critique(c.critique_id)
        if stored != c:
            raise DebateStoreError(f"critique {c.critique_id} is already recorded differently")
        return c

    def get_critique(self, critique_id: str) -> CritiqueReport | None:
        row = self._connection.execute(
            f"SELECT {', '.join(_CRITIQUE_COLUMNS)} FROM critique_reports WHERE critique_id = %s",
            (critique_id,),
        ).fetchone()
        return None if row is None else _critique_from_row(row)

    def critiques_targeting(
        self, project_id: str, hypothesis_id: str
    ) -> tuple[CritiqueReport, ...]:
        rows = self._connection.execute(
            f"SELECT {', '.join(_CRITIQUE_COLUMNS)} FROM critique_reports "
            "WHERE project_id = %s AND %s = ANY (target_ids) ORDER BY created_at, critique_id",
            (project_id, hypothesis_id),
        ).fetchall()
        return tuple(_critique_from_row(row) for row in rows)

    def add_debate_record(self, record: DebateRecord) -> DebateRecord:
        r = record
        self._connection.execute(
            f"INSERT INTO debate_records ({', '.join(_RECORD_COLUMNS)}) "
            f"VALUES ({', '.join(['%s'] * len(_RECORD_COLUMNS))}) "
            "ON CONFLICT (debate_id) DO NOTHING",
            (
                r.debate_id,
                r.project_id,
                r.episode_id,
                r.set_id,
                r.rounds,
                r.max_rounds,
                r.stop_reason,
                list(r.escalation_triggers),
                list(r.position_ids),
                list(r.critique_ids),
                r.position_diversity,
                r.critic_bundle_divergence,
                r.critic_changed_final_set,
                list(r.initial_hypothesis_ids),
                list(r.surviving_hypothesis_ids),
                r.surviving_hypothesis_diversity,
                r.additional_evidence_items,
                r.additional_token_count,
                json.dumps(r.metric_versions),
                json.dumps(list(r.gate_evaluations), default=_json_default),
                json.dumps(list(r.per_round), default=_json_default),
                r.created_at,
            ),
        )
        stored = self.get_debate_record(r.debate_id)
        if stored is None:  # pragma: no cover - the insert either landed or conflicted
            raise DebateStoreError(f"debate record {r.debate_id} vanished after being written")
        return stored

    def get_debate_record(self, debate_id: str) -> DebateRecord | None:
        row = self._connection.execute(
            f"SELECT {', '.join(_RECORD_COLUMNS)} FROM debate_records WHERE debate_id = %s",
            (debate_id,),
        ).fetchone()
        if row is None:
            return None
        values: dict[str, Any] = dict(zip(_RECORD_COLUMNS, row, strict=True))
        return DebateRecord.model_validate(values)

    def records_for_set(self, set_id: str) -> tuple[DebateRecord, ...]:
        rows = self._connection.execute(
            "SELECT debate_id FROM debate_records WHERE set_id = %s ORDER BY created_at, debate_id",
            (set_id,),
        ).fetchall()
        found = (self.get_debate_record(str(row[0])) for row in rows)
        return tuple(r for r in found if r is not None)


def _critique_from_row(row: tuple[object, ...]) -> CritiqueReport:
    values: dict[str, Any] = dict(zip(_CRITIQUE_COLUMNS, row, strict=True))
    values["objections"] = tuple(Objection.model_validate(o) for o in values["objections"])
    values["falsifier_challenges"] = tuple(
        FalsifierChallenge.model_validate(f) for f in values["falsifier_challenges"]
    )
    return CritiqueReport.model_validate(values)


__all__ = [
    "AXIS_ORDER",
    "DebateStore",
    "DebateStoreError",
    "InMemoryDebateStore",
    "SqlDebateStore",
    "independence_axes",
]
