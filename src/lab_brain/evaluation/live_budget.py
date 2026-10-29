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

MONEY is capped by code, per REQUEST, not per episode (`lab_brain.llm_runtime.spend`, migration
011r). For an external primary the evaluation REQUIRES the Owner's spend ceiling and unit prices
(`spend_from_env`): without them it is refused before the first call, probes included. They are
declared into the evaluation's database and a guard is installed for the process, REQUIRED -- so
every request with a body to a host that is not this machine, from any client the workspace
builds, is reserved at its provable worst case before it is sent, atomically against the ceiling,
and a model or host with no declared price is refused. Prices are the Owner's, with source and
date; nothing here invents one (docs/evaluation/G0-real-llm-evaluation-proposal.zh-TW.md §3).

THIS MACHINE IS METERED TOO (011t). A local endpoint may be a proxy that forwards to a paid
provider (LiteLLM on localhost), so the evaluation's guard meters it like a remote one: an unpriced
local critic or utility is refused, unless the Owner declares it FREE --
`LAB_BRAIN_LIVE_FREE_ENDPOINTS="127.0.0.1:11434 qwen2.5:7b; 127.0.0.1:11434 *"` (`host[:port]` and a
model, or `*`), with `LAB_BRAIN_LIVE_FREE_REASON` saying why. The declarations are made through the
Owner's spend administration (`lab_brain_spend_admin`), as the budget and prices are: the DSN the
evaluation declares with must be the Owner's (in a fresh evaluation database, the migrator's).
"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from lab_brain.llm_runtime import spend


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


#: The variables an external primary needs, besides the call and token caps.
SPEND_VARIABLES = (
    "LAB_BRAIN_LIVE_SPEND_CEILING",
    "LAB_BRAIN_LIVE_SPEND_CURRENCY",
    "LAB_BRAIN_LIVE_PRICE_INPUT_PER_MTOK",
    "LAB_BRAIN_LIVE_PRICE_OUTPUT_PER_MTOK",
    "LAB_BRAIN_LIVE_PRICE_SOURCE",
    "LAB_BRAIN_LIVE_PRICE_DATE",
)


@dataclass(frozen=True)
class LiveSpend:
    """The Owner's monetary ceiling and the primary's unit prices, for one evaluation."""

    budget_id: str
    currency: str
    ceiling: Decimal
    input_per_mtok: Decimal
    output_per_mtok: Decimal
    source: str
    source_date: dt.date
    safety_multiplier: Decimal = Decimal(1)


def spend_from_env(*, external: bool, env: Mapping[str, str] = os.environ) -> LiveSpend | None:
    """The Owner's spend ceiling and prices: None only for a model on this machine; for an
    external primary, every one of `SPEND_VARIABLES` or `LiveBudgetMissing` -- before any call."""
    if not external:
        return None
    missing = [name for name in SPEND_VARIABLES if not env.get(name, "").strip()]
    if missing:
        raise LiveBudgetMissing(
            "an external primary needs the Owner's monetary ceiling and unit prices before any "
            "call is made (no price is ever estimated here): set " + ", ".join(missing)
        )
    try:
        declared = LiveSpend(
            budget_id=env.get("LAB_BRAIN_LIVE_SPEND_BUDGET", "") or "g0-live",
            currency=env["LAB_BRAIN_LIVE_SPEND_CURRENCY"].strip().upper(),
            ceiling=Decimal(env["LAB_BRAIN_LIVE_SPEND_CEILING"]),
            input_per_mtok=Decimal(env["LAB_BRAIN_LIVE_PRICE_INPUT_PER_MTOK"]),
            output_per_mtok=Decimal(env["LAB_BRAIN_LIVE_PRICE_OUTPUT_PER_MTOK"]),
            source=env["LAB_BRAIN_LIVE_PRICE_SOURCE"].strip(),
            source_date=dt.date.fromisoformat(env["LAB_BRAIN_LIVE_PRICE_DATE"].strip()),
            safety_multiplier=Decimal(env.get("LAB_BRAIN_LIVE_SPEND_MULTIPLIER", "") or "1"),
        )
    except (InvalidOperation, ValueError) as bad:
        raise LiveBudgetMissing(f"the spend ceiling or a price is not valid: {bad}") from bad
    if declared.ceiling <= 0 or declared.input_per_mtok < 0 or declared.output_per_mtok < 0:
        raise LiveBudgetMissing("the ceiling is positive and no price is negative")
    if declared.safety_multiplier < 1:
        raise LiveBudgetMissing("the safety multiplier is never below 1")
    return declared


@dataclass(frozen=True)
class FreeEndpoint:
    """An endpoint the Owner declares costs nothing: `host[:port]` and a model, or `*`."""

    endpoint_host: str
    model: str


def free_endpoints_from_env(
    env: Mapping[str, str] = os.environ,
) -> tuple[tuple[FreeEndpoint, ...], str]:
    """(the endpoints `LAB_BRAIN_LIVE_FREE_ENDPOINTS` declares free, the Owner's reason). Each
    entry is `host[:port] model`, separated by `;`. A declaration without a reason is refused."""
    raw = env.get("LAB_BRAIN_LIVE_FREE_ENDPOINTS", "").strip()
    reason = env.get("LAB_BRAIN_LIVE_FREE_REASON", "").strip()
    if not raw:
        return (), reason
    if not reason:
        raise LiveBudgetMissing(
            "LAB_BRAIN_LIVE_FREE_ENDPOINTS declares endpoints free; LAB_BRAIN_LIVE_FREE_REASON "
            "must say why (a local model server, not a proxy to a paid provider)"
        )
    endpoints = []
    for entry in raw.split(";"):
        parts = entry.split()
        if not parts:
            continue
        if len(parts) != 2:
            raise LiveBudgetMissing(
                f"a free endpoint is `host[:port] model` (or `*`), not {entry.strip()!r}"
            )
        endpoints.append(FreeEndpoint(parts[0].lower(), parts[1]))
    return tuple(endpoints), reason


def install_live_spend_guard(
    dsn: str,
    declared: LiveSpend,
    *,
    endpoint_host: str,
    model: str,
    actor_id: str,
    env: Mapping[str, str] = os.environ,
) -> spend.PostgresSpendGuard:
    """Declare the budget, the primary's price and the Owner's free endpoints
    (`free_endpoints_from_env`) in the evaluation's (fresh) database, through the spend
    administration functions, and install its guard for this process as REQUIRED -- metering this
    machine too. Returns the guard; `spend.install(None)` removes it."""
    import psycopg

    free, reason = free_endpoints_from_env(env)
    with psycopg.connect(dsn, autocommit=True) as connection:
        spend.declare_budget(
            connection,
            declared.budget_id,
            currency=declared.currency,
            ceiling=declared.ceiling,
            actor_id=actor_id,
            safety_multiplier=declared.safety_multiplier,
        )
        spend.declare_price(
            connection,
            declared.budget_id,
            endpoint_host=endpoint_host,
            model=model,
            currency=declared.currency,
            input_per_mtok=declared.input_per_mtok,
            output_per_mtok=declared.output_per_mtok,
            source=declared.source,
            source_date=declared.source_date,
            actor_id=actor_id,
        )
        for endpoint in free:
            spend.declare_free_endpoint(
                connection,
                endpoint.endpoint_host,
                endpoint.model,
                reason=reason,
                actor_id=actor_id,
            )
    guard = spend.PostgresSpendGuard(dsn, declared.budget_id, meter_this_machine=True)
    spend.install(guard, required=True)
    return guard


def install_local_free_guard(
    dsn: str, *, actor_id: str, env: Mapping[str, str] = os.environ
) -> spend.PostgresSpendGuard:
    """For an evaluation whose models are all on this machine (no spend ceiling): the Owner must
    declare each local endpoint free (`free_endpoints_from_env`) -- an undeclared one may be a
    proxy to a paid provider. Declares them and installs, REQUIRED, a guard with no budget that
    meters this machine: a request to any endpoint not declared free is refused unsent."""
    import psycopg

    free, reason = free_endpoints_from_env(env)
    if not free:
        raise LiveBudgetMissing(
            "an evaluation on this machine without a spend ceiling needs the Owner's declaration "
            "that its endpoints are free: set LAB_BRAIN_LIVE_FREE_ENDPOINTS and "
            "LAB_BRAIN_LIVE_FREE_REASON (or the spend ceiling and prices)"
        )
    with psycopg.connect(dsn, autocommit=True) as connection:
        for endpoint in free:
            spend.declare_free_endpoint(
                connection,
                endpoint.endpoint_host,
                endpoint.model,
                reason=reason,
                actor_id=actor_id,
            )
    guard = spend.PostgresSpendGuard(dsn, None, meter_this_machine=True)
    spend.install(guard, required=True)
    return guard


def check_spend_before_episode(connection: Any, budget_id: str | None) -> None:
    """Refuse the next episode once an overrun has opened the budget's circuit. Each request is
    refused by the guard anyway; this stops the evaluation at an episode boundary, with a reason."""
    if budget_id is None:
        return
    state = spend.budget_state(connection, budget_id)
    if state is None:
        raise LiveBudgetMissing(f"the spend budget {budget_id} is not declared")
    if state.circuit_open:
        raise LiveBudgetExhausted(
            f"spend budget {budget_id} is halted after an overrun ({state.charged} "
            f"{state.currency} charged of {state.ceiling}); the Owner must review it"
        )


__all__ = [
    "SPEND_VARIABLES",
    "FreeEndpoint",
    "LiveBudgetExhausted",
    "LiveBudgetMissing",
    "LiveCap",
    "LiveSpend",
    "cap_from_env",
    "check_before_episode",
    "check_spend_before_episode",
    "free_endpoints_from_env",
    "install_live_spend_guard",
    "install_local_free_guard",
    "spend_from_env",
    "spent",
]
