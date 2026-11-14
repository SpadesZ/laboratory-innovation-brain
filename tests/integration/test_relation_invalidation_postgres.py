"""A relation's invalidation is final, and its author survives it (`012r`).

Data-organization audit 2026-10-15, F-02: an invalidated relation could be reopened by an UPDATE
that cleared `valid_to` and `invalidation_reason`, and the invalidation itself overwrote
`actor_id` -- the column the gate's separation of duties reads -- with the invalidator. Now:

    author        `actor_id` names who recorded the relation for its whole life; the store's
                  invalidation records the invalidator in `invalidated_by_actor_id`
    final         a closed relation is never reopened, re-dated, given another reason or
                  re-attributed, by any writer that goes through the triggers
    named         an invalidation says who made it
    never deleted a relation is invalidated, not deleted
    past triggers the invalidator column still exists only on a closed relation
    history       a relation closed before `012r` (its `actor_id` the invalidator, no
                  `invalidated_by_actor_id`) is left exactly as it was, and is final too
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import psycopg
import pytest

from lab_brain.core.models.enums import RelationType
from lab_brain.core.models.relation import RelationJudgment
from lab_brain.core.repositories.evidence import SqlRelationStore

pytestmark = pytest.mark.postgres

PROJECT = "prj:test"
AUTHOR = "act:test"
REVIEWER = "act:reviewer"
T0 = dt.datetime(2026, 10, 19, 9, 0, tzinfo=dt.UTC)


def _store(db: Any) -> SqlRelationStore:
    db.execute(
        "INSERT INTO actors (actor_id, actor_type, display_name) VALUES (%s, 'HUMAN', %s)"
        " ON CONFLICT DO NOTHING",
        (REVIEWER, REVIEWER),
    )
    return SqlRelationStore(db)


def _relation(store: SqlRelationStore, relation_id: str = "rel:cites") -> RelationJudgment:
    return store.add(
        RelationJudgment(
            relation_id=relation_id,
            from_entity_id="swk:a",
            to_entity_id="swk:b",
            relation_type=RelationType.CITES,
            actor_id=AUTHOR,
            project_id=PROJECT,
            valid_from=T0,
            created_at=T0,
        )
    )


def _row(db: Any, relation_id: str) -> tuple[Any, ...]:
    return tuple(
        db.execute(
            "SELECT actor_id, valid_to, invalidation_reason, invalidated_by_actor_id"
            " FROM relation_judgments WHERE relation_id = %s",
            (relation_id,),
        ).fetchone()
    )


def test_the_store_records_the_invalidator_beside_the_author(db):
    store = _store(db)
    _relation(store)
    closed = store.invalidate(
        project_id=PROJECT,
        relation_id="rel:cites",
        reason="the citation was a misread",
        actor_id=REVIEWER,
        at=T0 + dt.timedelta(hours=1),
    )
    assert (closed.actor_id, closed.invalidated_by_actor_id) == (AUTHOR, REVIEWER)
    assert _row(db, "rel:cites") == (
        AUTHOR,
        T0 + dt.timedelta(hours=1),
        "the citation was a misread",
        REVIEWER,
    )
    assert store.get(PROJECT, "rel:cites") == closed, "it round-trips"


@pytest.mark.parametrize(
    ("assignment", "refusal"),
    [
        (
            "valid_to = NULL, invalidation_reason = NULL, invalidated_by_actor_id = NULL",
            "an invalidation is final",
        ),
        ("valid_to = valid_to + interval '1 day'", "an invalidation is final"),
        ("invalidation_reason = 'another reason'", "an invalidation is final"),
        ("invalidated_by_actor_id = 'act:test'", "an invalidation is final"),
        ("actor_id = 'act:reviewer'", r"author \(actor_id act:test\) is immutable"),
    ],
)
def test_a_closed_relation_is_never_reopened_or_rewritten(db, assignment, refusal):
    store = _store(db)
    _relation(store)
    store.invalidate(
        project_id=PROJECT, relation_id="rel:cites", reason="withdrawn", actor_id=REVIEWER, at=T0
    )
    before = _row(db, "rel:cites")
    with pytest.raises(psycopg.errors.RaiseException, match=refusal):
        db.execute(f"UPDATE relation_judgments SET {assignment} WHERE relation_id = 'rel:cites'")
    assert _row(db, "rel:cites") == before


def test_a_current_relation_keeps_its_author_and_an_invalidation_names_its_maker(db):
    store = _store(db)
    _relation(store)
    with pytest.raises(psycopg.errors.RaiseException, match="is immutable"):
        db.execute(
            "UPDATE relation_judgments SET actor_id = %s WHERE relation_id = 'rel:cites'",
            (REVIEWER,),
        )
    with pytest.raises(psycopg.errors.RaiseException, match="names who made it"):
        db.execute(
            "UPDATE relation_judgments SET valid_to = %s, invalidation_reason = 'x'"
            " WHERE relation_id = 'rel:cites'",
            (T0,),
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "UPDATE relation_judgments SET invalidated_by_actor_id = %s"
            " WHERE relation_id = 'rel:cites'",
            (REVIEWER,),
        )
    assert _row(db, "rel:cites") == (AUTHOR, None, None, None)


def test_a_relation_is_never_deleted(db):
    store = _store(db)
    _relation(store)
    with pytest.raises(psycopg.errors.RaiseException, match="is never deleted"):
        db.execute("DELETE FROM relation_judgments WHERE relation_id = 'rel:cites'")
    store.invalidate(
        project_id=PROJECT, relation_id="rel:cites", reason="x", actor_id=REVIEWER, at=T0
    )
    with pytest.raises(psycopg.errors.RaiseException, match="is never deleted"):
        db.execute("DELETE FROM relation_judgments WHERE relation_id = 'rel:cites'")


def test_past_every_trigger_the_invalidator_exists_only_on_a_closed_relation(db):
    store = _store(db)
    _relation(store)
    db.execute("SET session_replication_role = replica")
    try:
        with pytest.raises(psycopg.errors.CheckViolation):
            db.execute(
                "UPDATE relation_judgments SET invalidated_by_actor_id = %s"
                " WHERE relation_id = 'rel:cites'",
                (REVIEWER,),
            )
    finally:
        db.execute("SET session_replication_role = origin")


def test_a_relation_closed_before_012r_is_left_as_it_was_and_is_final(db):
    store = _store(db)
    _relation(store, "rel:history")
    # As `012o` wrote an invalidation: the invalidator in actor_id, no invalidated_by_actor_id.
    db.execute("SET session_replication_role = replica")
    try:
        db.execute(
            "UPDATE relation_judgments SET valid_to = %s, invalidation_reason = 'withdrawn',"
            " actor_id = %s WHERE relation_id = 'rel:history'",
            (T0, REVIEWER),
        )
    finally:
        db.execute("SET session_replication_role = origin")
    history = _row(db, "rel:history")
    assert history == (REVIEWER, T0, "withdrawn", None)
    stored = store.get(PROJECT, "rel:history")
    assert stored is not None and not stored.is_current
    assert stored.invalidated_by_actor_id is None, "nothing is inferred for history"
    for assignment in (
        "valid_to = NULL, invalidation_reason = NULL",
        f"actor_id = '{AUTHOR}'",
        f"invalidated_by_actor_id = '{REVIEWER}'",
    ):
        with pytest.raises(psycopg.errors.RaiseException):
            db.execute(
                f"UPDATE relation_judgments SET {assignment} WHERE relation_id = 'rel:history'"
            )
    assert _row(db, "rel:history") == history
