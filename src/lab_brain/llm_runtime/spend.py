"""The monetary ceiling on external model requests -- fail closed, reserved before each request.

`OpenAICompatibleClient._request` is the one place a model request leaves the process. Before it
sends any request that has a BODY to an endpoint that is not this machine, it asks a `SpendGuard`
to RESERVE that request's provable worst case against the Owner's ceiling, and it sends nothing
unless the reservation succeeded. After the answer -- or the failure -- it SETTLES or RETAINS:

    worst case   input_bound = ceil(body_bytes x safety_multiplier)
                               + images x image_allowance_tokens + request_overhead_tokens
                 worst_case  = (input_bound x input_price + max_output x output_price) / 10^6
                 `body_bytes`: the UTF-8 length of the whole serialized request body. A token is
                 at least one byte of the text it encodes (byte-level BPE, SentencePiece with byte
                 fallback), so no prompt is billed more tokens than its body has bytes; the
                 multiplier (>= 1) and the overhead cover what a provider adds outside the body.
                 `max_output`: the `max_tokens` the request carries -- every chat request carries
                 one now, and a metered request without one is refused.
    reserve      atomic in PostgreSQL (`llm_spend_reserve`, migration 011r): the budget row is
                 locked, `charged + worst_case <= ceiling` checked and the worst case charged in
                 one transaction. Concurrent threads and processes cannot pass the ceiling.
    settle       the provider reported prompt and completion tokens: the charge becomes what they
                 cost -- unless they pass the reservation (OVERRUN: charged at the greater of the
                 two, and the budget's circuit opens; every later reservation is refused until
                 the Owner closes it)
    retain       no usage, malformed usage, an HTTP error, a timeout, a dropped connection: the
                 worst case stays charged. The provider may have billed and said nothing.

Which guard applies, decided at each request (`resolve`), first match wins:

    explicit     the guard a client was built with (`OpenAICompatibleClient(spend=...)`)
    installed    the process's guard (`install`), e.g. the live evaluation's
    environment  `LAB_BRAIN_LLM_SPEND_BUDGET=<budget id>` with `LAB_BRAIN_LLM_SPEND_DSN` (or
                 `LAB_BRAIN_DATABASE_URL`): a deployment's ceiling. A budget named here that cannot
                 be reached refuses every metered request -- a configured ceiling never silently
                 lapses.
    declarations no budget, but a database (`LAB_BRAIN_LLM_SPEND_DSN` or `LAB_BRAIN_DATABASE_URL`):
                 a guard with no ceiling. It lets through exactly the endpoints the Owner declared
                 free and refuses every other metered request.

FAIL CLOSED BY DEFAULT (011t). With no guard, or a guard with no budget, a request with a body to
an endpoint that is not this machine is REFUSED before a byte is sent. The one opt-out is the
Owner's: an endpoint (`host[:port]` and one model, or `*`) DECLARED FREE in the database by a
member of `lab_brain_spend_admin` (`declare_free_endpoint`), never by the services' role.

THIS MACHINE. A guard with a budget meters this machine too, unless the endpoint is declared free:
a local proxy (LiteLLM on localhost) may forward to a paid provider, and nothing here can tell. With
no budget configured at all, a request to this machine is sent unmetered -- unless the Owner says
`LAB_BRAIN_LLM_SPEND_METER_LOCAL=1`, when an undeclared local endpoint is refused like a remote one.
That last case is the residual (spend-administration.md): a deployment with no ceiling, pointed at
a paying local proxy, is unmetered.

NOT METERED, ever. A request with NO BODY (`GET /models`, the model list and health check): it
carries no prompt, generates nothing, and the client cannot send a body with it -- `_request`
exempts exactly `GET` without a payload.

WHO MAY CHANGE THE MONEY (011t). Creating a budget, declaring a price, changing a ceiling, closing a
circuit and declaring an endpoint free are the Owner's: SECURITY DEFINER functions that refuse any
session whose login role is not a member of `lab_brain_spend_admin`. The services' role may only
reserve, settle, retain and read (`lab-brain admin db-roles`).

The ledger rows carry the call id, model and endpoint host -- never the credential or the prompt.
"""

from __future__ import annotations

import datetime as dt
import math
import os
import threading
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

#: What a chat request may generate unless the deployment says otherwise
#: (`LAB_BRAIN_LLM_MAX_OUTPUT_TOKENS`, or the client's `max_output_tokens`). It bounds the output
#: side of every worst case; a provider that bills hidden reasoning tokens outside it is detected
#: at settlement (OVERRUN), not prevented -- the Owner verifies that per provider.
DEFAULT_MAX_OUTPUT_TOKENS = 16_384

_PER_MILLION = Decimal("0.000001")


class SpendRefused(RuntimeError):
    """A metered request was refused before anything was sent. The message names the model,
    host, budget and amounts -- never the credential or the prompt."""


@dataclass(frozen=True)
class SpendRequest:
    """What the guard knows of one request: its size, never its content."""

    call_id: str
    #: `host` or `host:port`, lower-case.
    endpoint_host: str
    model: str
    body_bytes: int
    image_count: int
    max_output_tokens: int


@dataclass(frozen=True)
class Reservation:
    call_id: str
    budget_id: str
    worst_case: Decimal


class SpendGuard(Protocol):
    #: True: requests to this machine are metered too (a local proxy to a paid provider).
    meter_this_machine: bool

    # Optional, read with `getattr` by the transport: `declared_free(endpoint_host, model) ->
    # bool`, whether the Owner declared this endpoint free. A guard without it declares none.

    def reserve(self, request: SpendRequest) -> Reservation:
        """Charge the request's worst case, or raise `SpendRefused`. Nothing is sent before."""
        ...

    def settle(self, reservation: Reservation, usage: Mapping[str, int] | None) -> str:
        """'SETTLED', 'OVERRUN', or 'RETAINED' (no usable usage). Never raises."""
        ...

    def retain(self, reservation: Reservation, reason: str) -> None:
        """Keep the worst case charged. Never raises."""
        ...


def new_call_id() -> str:
    return "llmcall:" + uuid.uuid4().hex


def worst_case_cost(
    *,
    body_bytes: int,
    image_count: int,
    max_output_tokens: int,
    input_per_mtok: Decimal,
    output_per_mtok: Decimal,
    safety_multiplier: Decimal = Decimal(1),
    image_allowance_tokens: int = 4096,
    request_overhead_tokens: int = 1024,
) -> tuple[int, Decimal]:
    """(input_bound_tokens, worst_case) -- the same arithmetic `llm_spend_reserve` performs in the
    database, which is the one that decides; this mirror exists to state and test it."""
    if max_output_tokens < 1 or body_bytes < 1 or image_count < 0:
        raise ValueError("a worst case needs a body, a max_tokens and a non-negative image count")
    if safety_multiplier < 1:
        raise ValueError("the safety multiplier is never below 1")
    input_bound = (
        math.ceil(Decimal(body_bytes) * safety_multiplier)
        + image_count * image_allowance_tokens
        + request_overhead_tokens
    )
    cost = (input_bound * input_per_mtok + max_output_tokens * output_per_mtok) * _PER_MILLION
    return input_bound, cost


def usage_tokens(usage: Mapping[str, int] | None) -> tuple[int, int, int | None] | None:
    """(prompt, completion, total) when the provider reported both prompt and completion tokens
    as non-negative integers; None otherwise -- and None means the worst case stays charged."""
    if not usage:
        return None
    prompt, completion, total = (
        usage.get("prompt_tokens"),
        usage.get("completion_tokens"),
        usage.get("total_tokens"),
    )

    def ok(value: object) -> bool:
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0

    if not (ok(prompt) and ok(completion)):
        return None
    return int(prompt), int(completion), int(total) if ok(total) else None  # type: ignore[arg-type]


class PostgresSpendGuard:
    """The guard backed by migrations 011r and 011t. Each operation is its own short autocommit
    transaction on its own connection: a reservation is durable and visible to every other
    process the moment it returns, whatever transaction the caller is in (a research run's
    rollback cannot erase it), and the guard is safe to share between threads.

    `budget_id` None: a guard with no ceiling -- it passes the endpoints the Owner declared free
    and refuses every other metered request. `meter_this_machine` (default True): a budget meters
    this machine as well, since a local endpoint may be a proxy to a paid provider; only the
    Owner's free declaration exempts one."""

    def __init__(
        self,
        dsn: str,
        budget_id: str | None,
        *,
        meter_this_machine: bool = True,
        connect: Callable[[str], Any] | None = None,
    ) -> None:
        self._dsn = dsn
        self.budget_id = budget_id
        self.meter_this_machine = meter_this_machine
        self._connect = connect or _autocommit_connect

    def _run(self, sql: str, args: tuple[object, ...]) -> Any:
        connection = self._connect(self._dsn)
        try:
            row = connection.execute(sql, args).fetchone()
        finally:
            connection.close()
        return row[0] if row else None

    def declared_free(self, endpoint_host: str, model: str) -> bool:
        """Whether the Owner declared this endpoint (and model) free. Any failure: not free."""
        try:
            return bool(
                self._run("SELECT llm_spend_endpoint_is_free(%s, %s)", (endpoint_host, model))
            )
        except Exception:  # unknown is not free: the request is metered, or refused
            return False

    def reserve(self, request: SpendRequest) -> Reservation:
        if self.budget_id is None:
            raise SpendRefused(
                f"no spend ceiling is configured for {request.endpoint_host}, and the Owner has "
                f"not declared {request.model} there free: nothing was sent"
            )
        try:
            cost = self._run(
                "SELECT llm_spend_reserve(%s, %s, %s, %s, %s, %s, %s)",
                (
                    self.budget_id,
                    request.call_id,
                    request.endpoint_host,
                    request.model,
                    request.body_bytes,
                    request.image_count,
                    request.max_output_tokens,
                ),
            )
        except Exception as refused:  # any failure to reserve refuses the request
            raise SpendRefused(_db_message(refused)) from None
        return Reservation(request.call_id, self.budget_id, Decimal(cost))

    def settle(self, reservation: Reservation, usage: Mapping[str, int] | None) -> str:
        tokens = usage_tokens(usage)
        if tokens is None:
            self.retain(reservation, "the reply carried no usable usage")
            return "RETAINED"
        try:
            return str(
                self._run("SELECT llm_spend_settle(%s, %s, %s, %s)", (reservation.call_id, *tokens))
            )
        except Exception:  # unsettled: the worst case stays charged
            return "RETAINED"

    def retain(self, reservation: Reservation, reason: str) -> None:
        try:
            self._run("SELECT llm_spend_retain(%s, %s)::text", (reservation.call_id, reason))
        except Exception:  # the reservation already holds the worst case
            return


def _autocommit_connect(dsn: str) -> Any:
    import psycopg

    return psycopg.connect(dsn, autocommit=True, connect_timeout=10)


def _db_message(error: BaseException) -> str:
    """The database's refusal, first line only; a connection failure as a plain sentence."""
    primary = getattr(getattr(error, "diag", None), "message_primary", None)
    if primary:
        return str(primary)[:400]
    return f"the spend ledger could not be reached ({type(error).__name__}), so nothing is sent"


class _Unreachable:
    """A ceiling the environment names but that cannot be built: every metered request refused."""

    meter_this_machine = True

    def __init__(self, why: str) -> None:
        self._why = why

    def reserve(self, request: SpendRequest) -> Reservation:
        raise SpendRefused(self._why)

    def settle(self, reservation: Reservation, usage: Mapping[str, int] | None) -> str:
        return "RETAINED"

    def retain(self, reservation: Reservation, reason: str) -> None:
        return


# -- which guard applies -------------------------------------------------------------------------

_lock = threading.Lock()
_installed: SpendGuard | None = None
_installed_required = False
_from_env: dict[tuple[str, str, bool], SpendGuard] = {}


def install(guard: SpendGuard | None, *, required: bool = True) -> None:
    """Make `guard` the process's guard (None removes it). `required` is kept for callers of 011r:
    a remote request with no guard is refused whatever it says (011t)."""
    global _installed, _installed_required
    with _lock:
        _installed = guard
        _installed_required = required and guard is not None


@contextmanager
def installed(guard: SpendGuard, *, required: bool = True) -> Iterator[SpendGuard]:
    previous, previous_required = _installed, _installed_required
    install(guard, required=required)
    try:
        yield guard
    finally:
        with _lock:
            globals()["_installed"] = previous
            globals()["_installed_required"] = previous_required


def _flag(env: Mapping[str, str], name: str) -> bool:
    return env.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def required(env: Mapping[str, str] = os.environ) -> bool:
    """Whether a remote request with no guard is refused: always, since 011t. There is no switch
    that sends one unmetered; the Owner's free declaration is the only exemption."""
    return True


def resolve(explicit: SpendGuard | None, env: Mapping[str, str] = os.environ) -> SpendGuard | None:
    if explicit is not None:
        return explicit
    if _installed is not None:
        return _installed
    budget = env.get("LAB_BRAIN_LLM_SPEND_BUDGET", "").strip()
    dsn = env.get("LAB_BRAIN_LLM_SPEND_DSN", "") or env.get("LAB_BRAIN_DATABASE_URL", "")
    if not budget and not dsn:
        return None
    # With a budget, this machine is metered unless declared free. Without one, only when the
    # Owner says so: otherwise the deployment would refuse its own local models.
    local = bool(budget) or _flag(env, "LAB_BRAIN_LLM_SPEND_METER_LOCAL")
    key = (dsn, budget, local)
    with _lock:
        if key not in _from_env:
            _from_env[key] = (
                PostgresSpendGuard(dsn, budget or None, meter_this_machine=local)
                if dsn
                else _Unreachable(
                    f"LAB_BRAIN_LLM_SPEND_BUDGET names {budget}, but no database is configured "
                    "(LAB_BRAIN_LLM_SPEND_DSN or LAB_BRAIN_DATABASE_URL), so nothing is sent"
                )
            )
        return _from_env[key]


def max_output_tokens(env: Mapping[str, str] = os.environ) -> int:
    """The deployment's `max_tokens` for every chat request."""
    raw = env.get("LAB_BRAIN_LLM_MAX_OUTPUT_TOKENS", "").strip()
    if not raw:
        return DEFAULT_MAX_OUTPUT_TOKENS
    value = int(raw)
    if value < 1:
        raise ValueError("LAB_BRAIN_LLM_MAX_OUTPUT_TOKENS is a positive number of tokens")
    return value


# -- the Owner's declarations --------------------------------------------------------------------
#
# Each is a SECURITY DEFINER function (011t) that refuses a session whose login role is not a member
# of `lab_brain_spend_admin`: `connection` is the Owner's, never the services'.

#: The role whose members administer the money (migration 011t).
SPEND_ADMIN_ROLE = "lab_brain_spend_admin"


def declare_budget(
    connection: Any,
    budget_id: str,
    *,
    currency: str,
    ceiling: Decimal,
    actor_id: str,
    safety_multiplier: Decimal = Decimal(1),
    image_allowance_tokens: int = 4096,
    request_overhead_tokens: int = 1024,
) -> None:
    """A new budget: nothing charged, circuit closed. Its parameters never change afterwards."""
    connection.execute(
        "SELECT llm_spend_declare_budget(%s, %s, %s, %s, %s, %s, %s)::text",
        (
            budget_id,
            currency,
            ceiling,
            actor_id,
            safety_multiplier,
            image_allowance_tokens,
            request_overhead_tokens,
        ),
    )


def declare_price(
    connection: Any,
    budget_id: str,
    *,
    endpoint_host: str,
    model: str,
    currency: str,
    input_per_mtok: Decimal,
    output_per_mtok: Decimal,
    source: str,
    source_date: dt.date,
    actor_id: str,
) -> None:
    """The Owner's unit price for `model` at `endpoint_host`, as read from `source` on
    `source_date`. Never computed here; a later declaration supersedes this one."""
    connection.execute(
        "SELECT llm_spend_declare_price(%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            budget_id,
            currency,
            endpoint_host.lower(),
            model,
            input_per_mtok,
            output_per_mtok,
            source,
            source_date,
            actor_id,
        ),
    )


def set_ceiling(
    connection: Any,
    budget_id: str,
    ceiling: Decimal,
    *,
    actor_id: str,
    reason: str,
    close_circuit: bool = False,
) -> None:
    """The Owner's new ceiling -- and, after reviewing an overrun, the only way to resume."""
    connection.execute(
        "SELECT llm_spend_set_ceiling(%s, %s, %s, %s, %s)::text",
        (budget_id, ceiling, actor_id, reason, close_circuit),
    )


def declare_free_endpoint(
    connection: Any, endpoint_host: str, model: str, *, reason: str, actor_id: str
) -> None:
    """The Owner's statement that `model` (or `*`, every model) at `endpoint_host` costs nothing
    -- a local model server, not a proxy to a paid provider. Requests to it are not metered.
    `reason` says why; it is kept with the declaration."""
    connection.execute(
        "SELECT llm_spend_declare_free(%s, %s, %s, %s)::text",
        (endpoint_host.lower(), model, reason, actor_id),
    )


def revoke_free_endpoint(
    connection: Any, endpoint_host: str, model: str, *, reason: str, actor_id: str
) -> None:
    """Withdraw a free declaration: requests to the endpoint are metered (or refused) again."""
    connection.execute(
        "SELECT llm_spend_revoke_free(%s, %s, %s, %s)::text",
        (endpoint_host.lower(), model, reason, actor_id),
    )


@dataclass(frozen=True)
class BudgetState:
    currency: str
    ceiling: Decimal
    charged: Decimal
    circuit_open: bool


def budget_state(connection: Any, budget_id: str) -> BudgetState | None:
    row = connection.execute(
        "SELECT currency, ceiling, charged, circuit_open FROM llm_spend_budgets"
        " WHERE budget_id = %s",
        (budget_id,),
    ).fetchone()
    return BudgetState(*row) if row else None


__all__ = [
    "DEFAULT_MAX_OUTPUT_TOKENS",
    "SPEND_ADMIN_ROLE",
    "BudgetState",
    "PostgresSpendGuard",
    "Reservation",
    "SpendGuard",
    "SpendRefused",
    "SpendRequest",
    "budget_state",
    "declare_budget",
    "declare_free_endpoint",
    "declare_price",
    "install",
    "installed",
    "max_output_tokens",
    "new_call_id",
    "required",
    "resolve",
    "revoke_free_endpoint",
    "set_ceiling",
    "usage_tokens",
    "worst_case_cost",
]
