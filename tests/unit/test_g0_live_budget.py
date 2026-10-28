"""The cumulative cap on an external model across a live evaluation (backend-free, fake rows)."""

from __future__ import annotations

from typing import Any

import pytest

from lab_brain.evaluation.live_budget import (
    LiveBudgetExhausted,
    LiveBudgetMissing,
    LiveCap,
    cap_from_env,
    check_before_episode,
    spent,
)


class _Rows:
    """A connection whose LLM_CALL spans for one model carry these metadata objects."""

    def __init__(self, metadata: list[Any]) -> None:
        self._metadata = metadata
        self.asked: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, sql: str, params: tuple[Any, ...]) -> Any:
        self.asked.append((sql, params))
        rows = [(m,) for m in self._metadata]
        return type("R", (), {"fetchall": lambda _self: rows})()


def test_an_external_model_without_a_cap_is_refused_before_any_call():
    with pytest.raises(LiveBudgetMissing):
        cap_from_env(external=True, env={})
    with pytest.raises(LiveBudgetMissing):
        cap_from_env(external=True, env={"LAB_BRAIN_LIVE_MAX_CALLS": "10"})
    with pytest.raises(LiveBudgetMissing):
        cap_from_env(
            external=True,
            env={"LAB_BRAIN_LIVE_MAX_CALLS": "x", "LAB_BRAIN_LIVE_MAX_TOKENS": "1"},
        )
    assert cap_from_env(external=False, env={}) is None


def test_the_cap_reads_the_owners_numbers_and_rejects_nonsense():
    cap = cap_from_env(
        external=True,
        env={"LAB_BRAIN_LIVE_MAX_CALLS": "350", "LAB_BRAIN_LIVE_MAX_TOKENS": "1800000"},
    )
    assert cap == LiveCap(max_calls=350, max_tokens=1_800_000)
    with pytest.raises(ValueError):
        LiveCap(max_calls=0, max_tokens=1)


def test_spent_counts_reported_tokens_and_charges_unmetered_calls_the_ceiling():
    cap = LiveCap(max_calls=100, max_tokens=1_000_000, reserve_calls=10, reserve_tokens=60_000)
    rows = _Rows([{"provider_total_tokens": 5000}, {}, {"provider_total_tokens": "lots"}, None])
    calls, tokens = spent(rows, "models/m", cap)
    assert calls == 4 and tokens == 5000 + 3 * 6000
    assert rows.asked[0][1] == ("models/m",)


def test_the_next_episode_is_refused_when_it_could_pass_either_cap():
    cap = LiveCap(max_calls=20, max_tokens=100_000, reserve_calls=10, reserve_tokens=60_000)
    check_before_episode(_Rows([{"provider_total_tokens": 1000}] * 10), "m", cap)
    with pytest.raises(LiveBudgetExhausted, match="calls"):
        check_before_episode(_Rows([{"provider_total_tokens": 1}] * 11), "m", cap)
    with pytest.raises(LiveBudgetExhausted, match="tokens"):
        check_before_episode(_Rows([{"provider_total_tokens": 41_000}]), "m", cap)
    check_before_episode(_Rows([{}] * 50), "m", None)  # a local model: no cap
