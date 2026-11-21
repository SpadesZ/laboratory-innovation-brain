"""`counted_events` (the in-memory store's `counted_history`) is the structural cascade of
`core.belief.replay`: for every history of up to five moves over four states, with ties in time,
it counts exactly the events the replay applies, in the same order (G0 round 5, `012ta`).

The SQL half (`belief_replay`) is held to the product projection by
tests/e2e/test_g0_counted_history_differential_postgres.py.
"""

from __future__ import annotations

import datetime as dt
import itertools

from lab_brain.core.belief import replay
from lab_brain.core.models import BeliefState
from lab_brain.core.repositories.belief_events import counted_events
from tests.contract.test_belief_replay import HYP, PROJECT, T0, event, verified

STATES = (BeliefState.ACTIVE, BeliefState.CHALLENGED, BeliefState.SUPPORTED)
MOVES = tuple((a, b) for a, b in itertools.permutations(STATES, 2))


def _history(moves: tuple[tuple[BeliefState, BeliefState], ...], ties: bool) -> list[object]:
    events = [event(event_id="bre:0", from_state=None, to_state=BeliefState.ACTIVE, occurred_at=T0)]
    for i, (a, b) in enumerate(moves, start=1):
        # With `ties`, moves 1 and 2 share a time: the order is then the event id's.
        hours = 1 if ties and i == 2 else i
        events.append(
            event(
                event_id=f"bre:{10 - i}",
                from_state=a,
                to_state=b,
                occurred_at=T0 + dt.timedelta(hours=hours),
            )
        )
    return events


def test_counted_events_is_the_replays_cascade() -> None:
    cases = 0
    for length in range(4):
        for moves in itertools.product(MOVES, repeat=length):
            for ties in (False, True):
                history = _history(moves, ties)
                projection = replay(PROJECT, HYP, verified(*history))  # type: ignore[arg-type]
                counted = counted_events(history)  # type: ignore[arg-type]
                assert tuple(e.event_id for e in counted) == projection.applied, moves
                cases += 1
    assert cases == 2 * sum(len(MOVES) ** n for n in range(4))
