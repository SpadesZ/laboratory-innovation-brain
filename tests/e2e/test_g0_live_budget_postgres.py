"""`spent` reads the canonical LLM_CALL spans of a real (stand-in) research episode."""

from __future__ import annotations

import pytest

from lab_brain.evaluation.live_budget import (
    LiveBudgetExhausted,
    LiveCap,
    check_before_episode,
    spent,
)
from tests.e2e.test_g0_screening_independence_postgres import guarded as guarded
from tests.e2e.test_g0_screening_independence_postgres import standin as standin

pytestmark = pytest.mark.postgres


def test_spent_matches_the_episodes_model_calls_and_the_cap_refuses_the_next(guarded):
    db = guarded.db
    models = db.execute(
        "SELECT ip.model_id, count(*) FROM execution_spans s"
        " JOIN inference_provenance ip ON ip.inference_id = s.model_call_id"
        " WHERE s.span_type = 'LLM_CALL' GROUP BY ip.model_id ORDER BY 2 DESC"
    ).fetchall()
    assert models, "the episode made model calls"
    model, calls = models[0]
    cap = LiveCap(max_calls=10_000, max_tokens=10_000_000)
    counted, tokens = spent(db, model, cap)
    assert counted == calls and tokens > 0
    check_before_episode(db, model, cap)
    with pytest.raises(LiveBudgetExhausted):
        check_before_episode(db, model, LiveCap(max_calls=calls + 1, max_tokens=10_000_000))
