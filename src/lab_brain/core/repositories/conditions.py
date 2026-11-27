"""PostgreSQL storage for condition schema registrations and ConditionMatches (`008`, EVI-005).

`008` created both tables in M0a and nothing in `src` wrote either: schemas were inserted by test
fixtures and matches were computed and handed to `evaluate` without ever being stored. M4 is the
first writer of a RelationJudgment whose `condition_match_ref` is set -- VS-SP-001's relations carry
the match between a Run's conditions and the diagnosis's -- and `004`'s foreign key makes that
reference resolve. So the match is stored, exactly as computed, and read back through the model.

A registration is idempotent and immutable: registering the same `(domain, schema_id, version)`
again with the same JSON schema and comparator version is a no-op, and with a different one it is
refused. A schema version whose field set changed underneath stored conditions would make every
payload validated against it re-interpretable after the fact (§6.19).
"""

from __future__ import annotations

import json
from typing import Any

from lab_brain.core.models.condition import (
    ConditionMatch,
    ConditionMismatch,
    ConditionSchemaRef,
    ConditionSchemaRegistration,
)
from lab_brain.core.models.enums import ConditionMatchState
from lab_brain.core.repositories.budget import SqlConnection
from lab_brain.core.repositories.protocols import RepositoryError


class ConditionStoreError(RepositoryError):
    """A condition schema or match write violated an invariant."""


class SqlConditionSchemaStore:
    def __init__(self, connection: SqlConnection) -> None:
        self._connection = connection

    def ensure(self, registration: ConditionSchemaRegistration) -> ConditionSchemaRegistration:
        self._connection.execute(
            "INSERT INTO condition_schemas (domain, schema_id, version, json_schema,"
            " comparator_version) VALUES (%s, %s, %s, %s::jsonb, %s) ON CONFLICT DO NOTHING",
            (
                registration.domain,
                registration.schema_id,
                registration.version,
                json.dumps(registration.json_schema),
                registration.comparator_version,
            ),
        )
        row = self._connection.execute(
            "SELECT json_schema, comparator_version FROM condition_schemas"
            " WHERE domain = %s AND schema_id = %s AND version = %s",
            (registration.domain, registration.schema_id, registration.version),
        ).fetchone()
        if row is None or (row[0], row[1]) != (
            registration.json_schema,
            registration.comparator_version,
        ):
            raise ConditionStoreError(
                f"condition schema {registration.ref} is already registered differently. A "
                "registered schema version is immutable; a changed field set is a new version"
            )
        return registration


_MATCH_COLUMNS = (
    "condition_match_id",
    "state",
    "matched_fields",
    "mismatches",
    "unknowns",
    "tolerance_policy_version",
    "schema_ref",
    "rationale_ref",
    "created_at",
)


class SqlConditionMatchStore:
    def __init__(self, connection: SqlConnection) -> None:
        self._connection = connection

    def add(self, match: ConditionMatch) -> ConditionMatch:
        self._connection.execute(
            f"INSERT INTO condition_matches ({', '.join(_MATCH_COLUMNS)})"
            f" VALUES ({', '.join(['%s'] * len(_MATCH_COLUMNS))})",
            (
                match.condition_match_id,
                match.state.value,
                list(match.matched_fields),
                json.dumps([m.model_dump(mode="json") for m in match.mismatches]),
                list(match.unknowns),
                match.tolerance_policy_version,
                str(match.schema_ref),
                match.rationale_ref,
                match.created_at,
            ),
        )
        return match

    def get(self, condition_match_id: str) -> ConditionMatch | None:
        row = self._connection.execute(
            f"SELECT {', '.join(_MATCH_COLUMNS)} FROM condition_matches"
            " WHERE condition_match_id = %s",
            (condition_match_id,),
        ).fetchone()
        if row is None:
            return None
        values: dict[str, Any] = dict(zip(_MATCH_COLUMNS, row, strict=True))
        return ConditionMatch(
            condition_match_id=values["condition_match_id"],
            state=ConditionMatchState(values["state"]),
            matched_fields=tuple(values["matched_fields"]),
            mismatches=tuple(ConditionMismatch.model_validate(m) for m in values["mismatches"]),
            unknowns=tuple(values["unknowns"]),
            tolerance_policy_version=values["tolerance_policy_version"],
            schema_ref=ConditionSchemaRef.parse(values["schema_ref"]),
            rationale_ref=values["rationale_ref"],
            created_at=values["created_at"],
        )


__all__ = [
    "ConditionStoreError",
    "SqlConditionMatchStore",
    "SqlConditionSchemaStore",
]
