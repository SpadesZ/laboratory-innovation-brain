"""A cumulative cap on an external model's use across a whole live evaluation -- fail closed.

Each research run has its own Budget Gate, which caps that run. Nothing capped the EVALUATION: a
matrix of 25 cases x 4 configurations is 100 runs, each within its own budget and together
unbounded. This module is the cap across runs, checked before every episode is started:

    unset         an external primary with no `LAB_BRAIN_LIVE_MAX_CALLS` and
                  `LAB_BRAIN_LIVE_MAX_TOKENS` is refused before any call (`LiveBudgetMissing`)
    spent         read from the canonical record -- the LLM_CALL spans of `model_id` and the token
                  counts the provider reported on them -- never from a counter the harness keeps
    unmetered     a call the provider reported no usage for is charged the per-call ceiling
                  (`reserve_tokens / reserve_calls`), never zero
    before each   refused (`LiveBudgetExhausted`) when what was spent plus one episode's reserve
                  would pass a cap, so the overshoot is bounded by one episode's own Budget Gate

The amount of money is not computed here: no model route declares a unit price, and this module
does not invent one (see docs/evaluation/G0-real-llm-evaluation-proposal.zh-TW.md §3).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


class LiveBudgetMissing(RuntimeError):
    """An external model was configured without a cumulative cap."""


class LiveBudgetExhausted(RuntimeError):
    """The next episode could pass the evaluation's cumulative cap."""


@dataclass(frozen=True)
class LiveCap:
    max_calls: int
    max_tokens: int
    #: What one episode may still use: checked BEFORE it starts.
    reserve_calls: int = 10
    reserve_tokens: int = 60_000

    def __post_init__(self) -> None:
        for name in ("max_calls", "max_tokens", "reserve_calls", "reserve_tokens"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")


def cap_from_env(*, external: bool, env: Mapping[str, str] = os.environ) -> LiveCap | None:
    """The configured cap: None only for a model on this machine, fail closed for an external."""
    calls, tokens = (
        env.get("LAB_BRAIN_LIVE_MAX_CALLS", ""),
        env.get("LAB_BRAIN_LIVE_MAX_TOKENS", ""),
    )
    if not calls or not tokens:
        if external:
            raise LiveBudgetMissing(
                "an external primary needs LAB_BRAIN_LIVE_MAX_CALLS and LAB_BRAIN_LIVE_MAX_TOKENS "
                "(the Owner's cumulative cap) before any call is made"
            )
        return None
    try:
        return LiveCap(
            max_calls=int(calls),
            max_tokens=int(tokens),
            reserve_calls=int(env.get("LAB_BRAIN_LIVE_RESERVE_CALLS", "10")),
            reserve_tokens=int(env.get("LAB_BRAIN_LIVE_RESERVE_TOKENS", "60000")),
        )
    except ValueError as bad:
        raise LiveBudgetMissing(f"the cumulative cap is not valid: {bad}") from bad


def spent(connection: Any, model_id: str, cap: LiveCap) -> tuple[int, int]:
    """(calls, tokens) the canonical record shows for `model_id`; unmetered calls at the ceiling."""
    rows = connection.execute(
        "SELECT s.metadata FROM execution_spans s"
        " JOIN inference_provenance ip ON ip.inference_id = s.model_call_id"
        " WHERE s.span_type = 'LLM_CALL' AND ip.model_id = %s",
        (model_id,),
    ).fetchall()
    ceiling = -(-cap.reserve_tokens // cap.reserve_calls)
    tokens = 0
    for (metadata,) in rows:
        meta = metadata if isinstance(metadata, Mapping) else {}
        reported = meta.get("provider_total_tokens")
        tokens += int(reported) if isinstance(reported, int) and reported >= 0 else ceiling
    return len(rows), tokens


def check_before_episode(connection: Any, model_id: str, cap: LiveCap | None) -> None:
    """Refuse the next episode when it could pass the cap."""
    if cap is None:
        return
    calls, tokens = spent(connection, model_id, cap)
    if calls + cap.reserve_calls > cap.max_calls or tokens + cap.reserve_tokens > cap.max_tokens:
        raise LiveBudgetExhausted(
            f"{model_id}: {calls} calls and {tokens} tokens spent; one more episode may use "
            f"{cap.reserve_calls} calls and {cap.reserve_tokens} tokens, over the cap of "
            f"{cap.max_calls} calls / {cap.max_tokens} tokens"
        )


__all__ = [
    "LiveBudgetExhausted",
    "LiveBudgetMissing",
    "LiveCap",
    "cap_from_env",
    "check_before_episode",
    "spent",
]
