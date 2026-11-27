"""The report each research run returned, kept as returned (`012d`).

`ResearchEpisodeService.run` returns an `EpisodeReport` assembled from the rows the authorities
wrote. A surface that shows the episode again later shows THAT report -- decoded back into the same
`EpisodeReport` type the CLI renders -- and never a second account recomputed outside the service.
What an episode IS now (suspended, completed, continued) is read live from the episode and the
research-run ledger; this is only what each run SAID.

The codec is structural: every `EpisodeReport` field round-trips to JSON and back to an equal
value, so a stored report renders exactly as the returned one did.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import types
import typing
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, get_args, get_origin, get_type_hints

from lab_brain.research.report import EpisodeReport


def report_to_json(report: EpisodeReport) -> dict[str, Any]:
    """The report as a JSON object. Datetimes are ISO 8601 with their offset."""
    encoded = json.loads(json.dumps(dataclasses.asdict(report), default=_encode))
    assert isinstance(encoded, dict)
    return encoded


def report_from_json(data: Mapping[str, Any]) -> EpisodeReport:
    """The `EpisodeReport` a stored object encodes. Raises on anything that does not fit it."""
    decoded = _decode(EpisodeReport, data)
    assert isinstance(decoded, EpisodeReport)
    return decoded


def _encode(value: object) -> str:
    if isinstance(value, dt.datetime):
        return value.isoformat()
    raise TypeError(f"{type(value).__name__} is not part of an EpisodeReport")


def _decode(kind: Any, value: Any) -> Any:
    origin = get_origin(kind)
    if origin in (typing.Union, types.UnionType):
        options = [a for a in get_args(kind) if a is not type(None)]
        if value is None:
            return None
        assert len(options) == 1, f"ambiguous optional {kind}"
        return _decode(options[0], value)
    if origin is tuple:
        (item, _ellipsis) = get_args(kind)
        if not isinstance(value, list):
            raise ValueError(f"expected a list for {kind}, got {type(value).__name__}")
        return tuple(_decode(item, v) for v in value)
    if dataclasses.is_dataclass(kind) and isinstance(kind, type):
        if not isinstance(value, dict):
            raise ValueError(f"expected an object for {kind.__name__}")
        hints = get_type_hints(kind)
        names = {f.name for f in dataclasses.fields(kind)}
        unknown = set(value) - names
        if unknown:
            raise ValueError(f"{kind.__name__} has no field(s) {sorted(unknown)}")
        return kind(**{k: _decode(hints[k], v) for k, v in value.items()})
    if kind is dt.datetime:
        return dt.datetime.fromisoformat(value)
    if kind in (str, int, bool):
        if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
            raise ValueError(f"expected {kind.__name__}, got {type(value).__name__}")
        return value
    raise TypeError(f"{kind} is not part of an EpisodeReport")


@dataclass(frozen=True)
class RecordedReport:
    research_run_id: str
    ordinal: int
    report: EpisodeReport
    recorded_at: dt.datetime


class SqlResearchReportStore:
    """PostgreSQL storage for `012d`. The binding to the run is the database's to check."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def record(self, research_run_id: str, report: EpisodeReport, *, at: dt.datetime) -> None:
        self._connection.execute(
            "INSERT INTO research_run_reports"
            " (research_run_id, episode_id, project_id, report, recorded_at)"
            " VALUES (%s, %s, %s, %s::jsonb, %s)",
            (
                research_run_id,
                report.episode_id,
                report.project_id,
                json.dumps(report_to_json(report)),
                at,
            ),
        )

    def for_episode(self, *, project_id: str, episode_id: str) -> tuple[RecordedReport, ...]:
        """The recorded reports of an episode's runs, by run ordinal. Scoped by project."""
        rows = self._connection.execute(
            "SELECT p.research_run_id, r.ordinal, p.report, p.recorded_at"
            " FROM research_run_reports p JOIN research_runs r USING (research_run_id)"
            " WHERE p.project_id = %s AND p.episode_id = %s ORDER BY r.ordinal",
            (project_id, episode_id),
        ).fetchall()
        return tuple(
            RecordedReport(
                research_run_id=str(row[0]),
                ordinal=int(row[1]),
                report=report_from_json(row[2] if isinstance(row[2], dict) else json.loads(row[2])),
                recorded_at=row[3],
            )
            for row in rows
        )


__all__ = [
    "RecordedReport",
    "SqlResearchReportStore",
    "report_from_json",
    "report_to_json",
]
