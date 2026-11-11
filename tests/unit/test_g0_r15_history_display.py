"""G0 R15: the raw history display marks every event the projection does not count.

The report's "governed moves" list and the episode view's transitions read the stored events
directly; the projection may skip some (a quarantined trigger, a missing predecessor, an owner's
quarantine) or refuse the whole history. A display that lists them plainly tells a reader a belief
moved when the product's own reader says it did not (docs/audit/g0-trust-boundaries-2026-11-08,
§6 R15). Display only; engineering evidence; G0 is NOT PASSED.
"""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pytest

from lab_brain.core.belief import (
    EpistemicStateProjection,
    SkipReason,
    UnverifiedBeliefRevision,
    VerificationFailure,
)
from lab_brain.core.models import BeliefState
from lab_brain.research.episode_view import Relation, Transition
from tests.unit.test_episode_view_page import _page, _report, _result, _view


def _event(event_id: str, from_state: str | None, to_state: str) -> SimpleNamespace:
    return SimpleNamespace(
        event_id=event_id,
        from_state=None if from_state is None else BeliefState(from_state),
        to_state=BeliefState(to_state),
        policy_id="policy:p",
        policy_version="1.0.0",
    )


HISTORY = (
    _event("bre:genesis", None, "ACTIVE"),
    _event("bre:promote", "ACTIVE", "SUPPORTED"),
)


@pytest.mark.xfail(strict=True, reason="R15 reproduction: the report lists moves unmarked")
def test_the_reports_moves_mark_an_event_the_projection_skipped():
    from lab_brain.research.service import belief_moves

    projection = EpistemicStateProjection(
        project_id="prj:p",
        target_id="hyp:h",
        current_state=BeliefState.ACTIVE,
        last_event_id="bre:genesis",
        applied=("bre:genesis",),
        skipped=(("bre:promote", SkipReason.OWNER_QUARANTINED),),
    )
    moves = belief_moves(HISTORY, projection)
    assert moves[0] == "genesis -> ACTIVE (policy:p@1.0.0, `bre:genesis`)"
    assert moves[1].startswith("ACTIVE -> SUPPORTED (policy:p@1.0.0, `bre:promote`)")
    assert "not counted" in moves[1] and "OWNER_QUARANTINED" in moves[1], moves[1]


@pytest.mark.xfail(strict=True, reason="R15 reproduction: the report lists moves unmarked")
def test_the_reports_moves_mark_every_event_of_a_history_the_projection_refuses():
    from lab_brain.research.service import belief_moves

    refused = UnverifiedBeliefRevision(
        VerificationFailure.UNDECLARED_POLICY, "a rule nobody declared"
    )
    moves = belief_moves(HISTORY, refused)
    assert all("not counted" in m and "UNDECLARED_POLICY" in m for m in moves), moves


@pytest.mark.xfail(strict=True, reason="R15 reproduction: the episode view shows it as a move")
def test_the_episode_view_marks_a_transition_the_projection_does_not_count():
    transition = Transition(
        "bre:promote",
        "hyp:norm",
        "NORMALIZATION_BASIS_ISSUE",
        "ACTIVE",
        "SUPPORTED",
        "policy:p@1.0.0",
        "dec:1",
        "ALLOW",
    )
    marked = dataclasses.replace(
        transition,
        not_counted="the projection refuses this history (UNDECLARED_POLICY)",
    )
    relation = Relation(
        "rel:1", "SUPPORTS", "hyp:norm", "NORMALIZATION_BASIS_ISSUE", None, (marked,), ()
    )
    for locale, words in (("en", "not counted"), ("zh-TW", "不計入")):
        markup = _page(_report(), _view(_result(relations=(relation,))), locale=locale)
        assert words in markup, locale
        assert "UNDECLARED_POLICY" in markup
