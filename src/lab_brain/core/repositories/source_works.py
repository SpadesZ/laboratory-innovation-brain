"""PostgreSQL storage for SourceWorks and Claims (§17.2, EVI-004, EVI-008), first written by M5.

M1 created `source_works`, `source_work_identifiers` and `claims` and exercised them from tests; no
production path wrote a SourceWork, because the only external material M1-M4 admitted arrived as
fixtures. M5's external admission is the first writer, so this is the store.

`retraction_check` is the one column that changes after insert, and only through
`record_status`: EVI-008 requires the check's result to be recorded even when it is UNKNOWN or
SOURCE_UNAVAILABLE, and a provider reporting that cited material has disappeared is exactly such a
result (§6.16). Everything else about a work is what it was when it was admitted.
"""

from __future__ import annotations

import json
from typing import Any, cast

from lab_brain.core.models.claim import Claim
from lab_brain.core.models.source_work import RetractionCheck, SourceWork, WorkIdentifier
from lab_brain.core.repositories.budget import SqlConnection


class SqlSourceWorkStore:
    def __init__(self, connection: SqlConnection) -> None:
        self._connection = connection

    def add(self, work: SourceWork) -> SourceWork:
        self._connection.execute(
            "INSERT INTO source_works (source_work_id, work_type, title, authors, venue,"
            " published_year, canonical_locator, manifestation_artifact_ids, trust_class,"
            " retraction_check, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,"
            " %s::jsonb, %s)",
            (
                work.source_work_id,
                work.work_type.value,
                work.title,
                list(work.authors),
                work.venue,
                work.published_year,
                work.canonical_locator,
                list(work.manifestation_artifact_ids),
                work.trust_class.value,
                work.retraction_check.model_dump_json(),
                work.created_at,
            ),
        )
        for identifier in work.identifiers:
            self._connection.execute(
                "INSERT INTO source_work_identifiers (source_work_id, scheme, value)"
                " VALUES (%s, %s, %s)",
                (work.source_work_id, identifier.scheme, identifier.value),
            )
        return work

    def get(self, source_work_id: str) -> SourceWork | None:
        row = self._connection.execute(
            "SELECT source_work_id, work_type, title, authors, venue, published_year,"
            " canonical_locator, manifestation_artifact_ids, trust_class, retraction_check,"
            " created_at FROM source_works WHERE source_work_id = %s",
            (source_work_id,),
        ).fetchone()
        if row is None:
            return None
        identifiers = self._connection.execute(
            "SELECT scheme, value FROM source_work_identifiers WHERE source_work_id = %s"
            " ORDER BY scheme, value",
            (source_work_id,),
        ).fetchall()
        values: dict[str, Any] = {
            "source_work_id": row[0],
            "work_type": row[1],
            "title": row[2],
            "authors": tuple(cast("list[str]", row[3])),
            "venue": row[4],
            "published_year": row[5],
            "canonical_locator": row[6],
            "manifestation_artifact_ids": tuple(cast("list[str]", row[7])),
            "trust_class": row[8],
            "retraction_check": row[9],
            "created_at": row[10],
            "identifiers": tuple(
                WorkIdentifier(scheme=str(s), value=str(v)) for s, v in identifiers
            ),
        }
        return SourceWork.model_validate(values)

    def find_by_identifier(self, scheme: str, value: str) -> SourceWork | None:
        """EVI-004: an identifier names one work. The index `002` declares makes it unique."""
        row = self._connection.execute(
            "SELECT source_work_id FROM source_work_identifiers WHERE scheme = %s AND value = %s",
            (scheme, value),
        ).fetchone()
        return None if row is None else self.get(str(row[0]))

    def record_status(self, source_work_id: str, check: RetractionCheck) -> None:
        """EVI-008: the check's result, recorded -- including UNKNOWN and SOURCE_UNAVAILABLE."""
        self._connection.execute(
            "UPDATE source_works SET retraction_check = %s::jsonb WHERE source_work_id = %s",
            (check.model_dump_json(), source_work_id),
        )


class SqlClaimStore:
    def __init__(self, connection: SqlConnection) -> None:
        self._connection = connection

    def add(self, claim: Claim) -> Claim:
        self._connection.execute(
            "INSERT INTO claims (claim_id, normalized_proposition, domain, scope, identity_status,"
            " merged_into_claim_id, created_at) VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s)",
            (
                claim.claim_id,
                claim.normalized_proposition,
                claim.domain,
                json.dumps(claim.scope),
                claim.identity_status.value,
                claim.merged_into_claim_id,
                claim.created_at,
            ),
        )
        return claim


__all__ = ["SqlClaimStore", "SqlSourceWorkStore"]
