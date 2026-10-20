"""PostgreSQL storage for Observations (§17.2), which M4 is the first milestone to write from a Run.

`observations` has existed since `003`; until VS-SP-001 nothing admitted a Run's output as an
Observation, so there was no SQL store (M2's vertical says so: "admitting a simulated observation as
evidence needs the Claim/Observation identity work that M4's VS-SP-001 vertical owns"). The table
keeps `value_numeric` and `value_text` apart; this store maps the model's single `value` onto them.
EVI-005's schema validation runs in the database (`008a`) for every writer.
"""

from __future__ import annotations

import json
from typing import Any

from lab_brain.core.models.observation import Observation
from lab_brain.core.repositories.budget import SqlConnection

_COLUMNS = (
    "observation_id",
    "run_id",
    "artifact_id",
    "metric_or_event",
    "value_ref",
    "value_numeric",
    "value_text",
    "unit",
    "conditions",
    "conditions_schema_version",
    "method_ref",
    "project_id",
    "created_at",
)


class SqlObservationStore:
    def __init__(self, connection: SqlConnection) -> None:
        self._connection = connection

    def add(self, observation: Observation) -> Observation:
        value = observation.value
        numeric = (
            float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None
        )
        text = None if numeric is not None or value is None else str(value)
        self._connection.execute(
            f"INSERT INTO observations ({', '.join(_COLUMNS)})"
            f" VALUES ({', '.join(['%s'] * len(_COLUMNS))})",
            (
                observation.observation_id,
                observation.run_id,
                observation.artifact_id,
                observation.metric_or_event,
                observation.value_ref,
                numeric,
                text,
                observation.unit,
                json.dumps(observation.conditions),
                observation.conditions_schema_version,
                observation.method_ref,
                observation.project_id,
                observation.created_at,
            ),
        )
        return observation

    def get(self, project_id: str, observation_id: str) -> Observation | None:
        row = self._connection.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM observations"
            " WHERE project_id = %s AND observation_id = %s",
            (project_id, observation_id),
        ).fetchone()
        if row is None:
            return None
        values: dict[str, Any] = dict(zip(_COLUMNS, row, strict=True))
        numeric = values.pop("value_numeric")
        text = values.pop("value_text")
        values["value"] = numeric if numeric is not None else text
        return Observation.model_validate(values)


__all__ = ["SqlObservationStore"]
