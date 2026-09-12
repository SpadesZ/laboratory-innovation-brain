"""Regression: ``RelationJudgment.invalidate`` must re-run every validator.

The defect: ``invalidate`` built the closed judgment with ``model_copy(update=...)``, which does
not re-run validators. Passing ``at=`` an instant before ``valid_from`` produced a relation whose
validity interval was inverted -- valid at no instant at all.

Why that matters beyond tidiness. ``as_of`` replay selects relations with
``valid_from <= moment < valid_to``. An inverted interval satisfies that for nothing, so the
judgment silently disappears from every historical reconstruction while the stored record looks
properly closed, with a reason and an actor. The belief state would then be replayed without
evidence that the record claims was accounted for.

Unmarked: the Requirement this serves is SYS-001, allocated to M0b, whose pass condition also
covers EpistemicState. Claiming it here would discharge half a pass condition.
"""

from __future__ import annotations

import datetime as dt

import pytest

from lab_brain.core.models.enums import RelationType
from lab_brain.core.models.relation import RelationJudgment
from tests.conftest_fixtures import make_relation


def test_invalidate_rejects_a_close_time_before_valid_from():
    relation = make_relation()
    backdated = relation.valid_from - dt.timedelta(seconds=1)
    with pytest.raises(ValueError, match="precedes valid_from"):
        relation.invalidate(reason="quarantined", actor_id="act:1", at=backdated)


def test_invalidate_at_exactly_valid_from_is_allowed():
    """A zero-length interval is degenerate but ordered; the spec only forbids inversion."""
    relation = make_relation()
    closed = relation.invalidate(
        reason="retracted immediately", actor_id="act:1", at=relation.valid_from
    )
    assert closed.valid_to == relation.valid_from
    assert not closed.is_current


def test_invalidate_preserves_every_other_field():
    relation = make_relation(
        attributes={"note": "keep me"},
        supporting_attestation_ids=("att:1", "att:2"),
        condition_match_ref="cmt:1",
    )
    closed = relation.invalidate(reason="superseded", actor_id="act:9")

    assert closed.relation_id == relation.relation_id
    assert closed.from_entity_id == relation.from_entity_id
    assert closed.to_entity_id == relation.to_entity_id
    assert closed.relation_type is relation.relation_type
    assert closed.attributes == {"note": "keep me"}
    assert closed.supporting_attestation_ids == ("att:1", "att:2")
    assert closed.condition_match_ref == "cmt:1"
    assert closed.valid_from == relation.valid_from
    assert closed.created_at == relation.created_at

    assert closed.invalidation_reason == "superseded"
    assert closed.actor_id == "act:9"
    assert closed.valid_to is not None


def test_invalidate_does_not_mutate_the_original():
    relation = make_relation()
    relation.invalidate(reason="x", actor_id="act:1")
    assert relation.is_current
    assert relation.valid_to is None
    assert relation.invalidation_reason is None


def test_invalidated_relation_is_excluded_from_as_of_after_the_close():
    """The behaviour the inverted interval would have corrupted."""
    relation = make_relation()
    closed_at = relation.valid_from + dt.timedelta(hours=1)
    closed = relation.invalidate(reason="quarantined", actor_id="act:1", at=closed_at)

    assert closed.is_valid_at(relation.valid_from)
    assert closed.is_valid_at(closed_at - dt.timedelta(seconds=1))
    assert not closed.is_valid_at(closed_at)
    assert not closed.is_valid_at(closed_at + dt.timedelta(days=1))


def test_invalidate_re_runs_the_epistemic_provenance_rule():
    """Every validator re-runs, not only the interval one.

    An epistemic relation may only exist with provenance. `invalidate` supplies `actor_id`, which
    satisfies that rule -- but the rule must actually be evaluated rather than skipped, so a
    future change that drops provenance during closure fails here.
    """
    relation = RelationJudgment(
        from_entity_id="att:a",
        to_entity_id="hyp:b",
        relation_type=RelationType.SUPPORTS,
        project_id="prj:test",
        supporting_attestation_ids=("att:a",),
    )
    closed = relation.invalidate(reason="retracted", actor_id="act:1")
    assert closed.is_epistemic
    assert closed.actor_id == "act:1"

    # And the negative: constructing the same shape with no provenance at all is refused, which
    # is the rule `invalidate` now re-runs rather than bypasses.
    with pytest.raises(ValueError, match="requires provenance"):
        RelationJudgment.model_validate(
            closed.model_dump()
            | {"supporting_attestation_ids": (), "actor_id": None, "inference_provenance_id": None}
        )


def test_invalidating_an_already_closed_relation_keeps_the_interval_ordered():
    """Closing twice must not invert the interval either."""
    relation = make_relation()
    first = relation.invalidate(
        reason="first", actor_id="act:1", at=relation.valid_from + dt.timedelta(hours=2)
    )
    with pytest.raises(ValueError, match="precedes valid_from"):
        first.invalidate(
            reason="second", actor_id="act:2", at=relation.valid_from - dt.timedelta(hours=1)
        )
