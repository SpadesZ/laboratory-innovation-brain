"""The database enforces the ledger and approval invariants, not only the Python gate (COST-001).

A pure budget gate is bypassed by anything that writes SQL -- a migration, a support script, a
future service. If "the ledger is append-only" and "an approval releases one action once" hold only
in `lab_brain.core.budget`, they hold only for callers who go through it.

So each invariant is asserted twice: once against the model and the gate in
tests/contract/test_budget_gate.py, once here against the schema.
"""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import os
import threading
from collections.abc import Iterator
from decimal import Decimal

import psycopg
import pytest

from lab_brain.core.budget import (
    BUDGET_OVERRUN_SCOPE,
    BudgetApproval,
    BudgetPolicy,
    BudgetRequest,
    DispatchOutcome,
    authorize_dispatch,
)
from lab_brain.core.models import Actor, ActorType, BudgetCaps, CostVector, ProjectMembership
from lab_brain.core.repositories import SqlBudgetApprovalClaims

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.requirement("COST-001"),
    pytest.mark.spec_test("T-COST-001"),
]

NOW = dt.datetime(2026, 9, 14, 12, 0, tzinfo=dt.UTC)
ACTION = "act:run_charge_dc_sweep#7"
DEFAULT_URL = "postgresql://lab_brain:lab_brain@localhost:5433/lab_brain"


@pytest.fixture
def seeded(db):  # type: ignore[no-untyped-def]
    """A project, an actor and one versioned policy. `db` truncates the core tables per test."""
    db.execute("DELETE FROM cost_entries")
    db.execute("DELETE FROM budget_approvals")
    db.execute("DELETE FROM budget_policies")
    db.execute(
        "INSERT INTO budget_policies (policy_id, policy_version, project_id, cap_money_estimate)"
        " VALUES ('pol:s', '1.0.0', 'prj:test', 50.00)"
    )
    return db


def _approval(db, approval_id: str = "apr:1", **overrides: object) -> None:  # type: ignore[no-untyped-def]
    values: dict[str, object] = {
        "approval_id": approval_id,
        "approver_actor_id": "act:test",
        "project_id": "prj:test",
        "episode_id": "ep:1",
        "action_ref": ACTION,
        "policy_id": "pol:s",
        "policy_version": "1.0.0",
        "granted_at": NOW,
        "expires_at": NOW + dt.timedelta(hours=1),
    }
    values.update(overrides)
    columns = ", ".join(values)
    placeholders = ", ".join(f"%({k})s" for k in values)
    db.execute(f"INSERT INTO budget_approvals ({columns}) VALUES ({placeholders})", values)


def _entry(db, entry_id: str, kind: str, **overrides: object) -> None:  # type: ignore[no-untyped-def]
    values: dict[str, object] = {
        "cost_entry_id": entry_id,
        "project_id": "prj:test",
        "episode_id": "ep:1",
        "actor_or_slot": "slot:planner",
        "action_ref": ACTION,
        "cost_kind": kind,
        "money_estimate": 1,
    }
    values.update(overrides)
    columns = ", ".join(values)
    placeholders = ", ".join(f"%({k})s" for k in values)
    db.execute(f"INSERT INTO cost_entries ({columns}) VALUES ({placeholders})", values)


# --------------------------------------------------------------------------------------------
# The ledger is append-only.
# --------------------------------------------------------------------------------------------


def test_a_cost_entry_cannot_be_updated(seeded):
    """A ledger whose rows can be edited is a report.

    Correcting a cost means recording a correcting entry, which leaves both visible.
    """
    _entry(seeded, "cost:1", "ESTIMATED")
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        seeded.execute(
            "UPDATE cost_entries SET money_estimate = 999 WHERE cost_entry_id = 'cost:1'"
        )


def test_a_cost_entry_cannot_be_deleted(seeded):
    """Deleting the expensive rows is the cheapest way to look under budget."""
    _entry(seeded, "cost:1", "ESTIMATED")
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        seeded.execute("DELETE FROM cost_entries WHERE cost_entry_id = 'cost:1'")


def test_estimate_and_actual_coexist_as_separate_rows(seeded):
    """Both survive. The estimate is the gate's input and the evidence for why the call ran."""
    _entry(seeded, "cost:1", "ESTIMATED", money_estimate=1)
    _entry(seeded, "cost:2", "ACTUAL", money_estimate=7)
    rows = seeded.execute(
        "SELECT cost_kind, money_estimate FROM cost_entries WHERE action_ref = %s "
        "ORDER BY cost_kind",
        (ACTION,),
    ).fetchall()
    assert [(r[0], int(r[1])) for r in rows] == [("ACTUAL", 7), ("ESTIMATED", 1)]


def test_one_estimate_per_action(seeded):
    """ "What did we think this would cost" must have a single answer.

    A retry is a new action_ref, not a second estimate quietly replacing the first.
    """
    _entry(seeded, "cost:1", "ESTIMATED")
    with pytest.raises(psycopg.errors.UniqueViolation):
        _entry(seeded, "cost:2", "ESTIMATED")


def test_an_unknown_cost_kind_is_rejected(seeded):
    with pytest.raises(psycopg.errors.CheckViolation):
        _entry(seeded, "cost:1", "PROBABLY_FINE")


def test_negative_costs_are_rejected(seeded):
    """A negative cost is a credit, and a budget that can be credited is not a cap."""
    with pytest.raises(psycopg.errors.CheckViolation):
        _entry(seeded, "cost:1", "ACTUAL", money_estimate=-5)


# --------------------------------------------------------------------------------------------
# Approvals are scoped and attributable.
# --------------------------------------------------------------------------------------------


def test_an_approval_requires_an_approver(seeded):
    """COST-001: the approval itself is an attributable event, not just its effect."""
    with pytest.raises(psycopg.errors.NotNullViolation):
        _approval(seeded, approver_actor_id=None)


def test_an_approval_requires_a_real_actor(seeded):
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        _approval(seeded, approver_actor_id="act:ghost")


def test_an_approval_requires_an_existing_policy_version(seeded):
    """Approving against caps that do not exist approves nothing in particular."""
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        _approval(seeded, policy_version="9.9.9")


def test_an_approval_window_must_run_forwards(seeded):
    """An expiry before the grant is not a window."""
    with pytest.raises(psycopg.errors.CheckViolation):
        _approval(seeded, expires_at=NOW - dt.timedelta(seconds=1))


def test_an_approval_cannot_be_consumed_by_another_action(seeded):
    """The replay case, at the schema level.

    The Python gate refuses a mismatched `action_ref`; this makes the same substitution impossible
    for anything writing SQL directly.
    """
    _approval(seeded)
    with pytest.raises(psycopg.errors.CheckViolation, match="consumed_by_its_own_action"):
        seeded.execute(
            "UPDATE budget_approvals SET consumed_at = %s, consumed_by_action = 'act:other'"
            " WHERE approval_id = 'apr:1'",
            (NOW,),
        )


def test_consumption_is_recorded_completely_or_not_at_all(seeded):
    """Half-recorded consumption would let an approval look unused while having been spent."""
    _approval(seeded)
    with pytest.raises(psycopg.errors.CheckViolation, match="consumption_is_complete"):
        seeded.execute(
            "UPDATE budget_approvals SET consumed_at = %s WHERE approval_id = 'apr:1'", (NOW,)
        )


def test_consuming_an_approval_for_its_own_action_is_allowed(seeded):
    """The constraint must be satisfiable, or approvals could never be spent."""
    _approval(seeded)
    seeded.execute(
        "UPDATE budget_approvals SET consumed_at = %s, consumed_by_action = %s"
        " WHERE approval_id = 'apr:1'",
        (NOW, ACTION),
    )
    row = seeded.execute(
        "SELECT consumed_by_action FROM budget_approvals WHERE approval_id = 'apr:1'"
    ).fetchone()
    assert row[0] == ACTION


# --------------------------------------------------------------------------------------------
# Caps.
# --------------------------------------------------------------------------------------------


def test_an_uncapped_dimension_is_null_not_zero(seeded):
    """NULL means "not limited here". Storing 0 would mean "nothing permitted"."""
    row = seeded.execute(
        "SELECT cap_money_estimate, cap_human_minutes FROM budget_policies"
        " WHERE policy_id = 'pol:s' AND policy_version = '1.0.0'"
    ).fetchone()
    assert int(row[0]) == 50
    assert row[1] is None, "an unstated cap must be NULL, not 0"


def test_a_cap_column_can_hold_zero_and_null_in_the_same_row(seeded):
    """§17.19.1 / `v3.3-a10`: the schema has to be able to state both, or the rule is unstorable.

    The Python gate used to read `0` as uncapped because `CostVector`'s defaults gave it no way to
    tell the two apart. The DDL always could -- these columns are nullable -- so the disagreement
    was one-sided, and this is the half that was already right. Asserted anyway: `BudgetCaps` is
    now bound to these columns by tests/spec/test_schema_drift.py, and a later migration that made
    a cap column NOT NULL DEFAULT 0 would silently re-create the ambiguity in the store while the
    model still claimed to distinguish them.
    """
    seeded.execute(
        "INSERT INTO budget_policies"
        " (policy_id, policy_version, project_id, cap_token_count, cap_money_estimate)"
        " VALUES ('pol:frozen', '1.0.0', 'prj:test', 0, NULL)"
    )
    row = seeded.execute(
        "SELECT cap_token_count, cap_money_estimate FROM budget_policies"
        " WHERE policy_id = 'pol:frozen'"
    ).fetchone()
    assert row[0] == 0, "a cap of zero must survive the round trip as 0, not as NULL"
    assert row[1] is None


def test_a_negative_cap_is_rejected(seeded):
    """A cap below zero is not a cap; the gate would compare against nonsense."""
    with pytest.raises(psycopg.errors.CheckViolation):
        seeded.execute(
            "INSERT INTO budget_policies (policy_id, policy_version, project_id, cap_token_count)"
            " VALUES ('pol:bad', '1.0.0', 'prj:test', -1)"
        )


# --------------------------------------------------------------------------------------------
# The token dimension. `v3.3-a10` / COST-001.
# --------------------------------------------------------------------------------------------


def test_the_ledger_records_tokens_as_their_own_column(seeded):
    """COST-001 names tokens among the minimum dimensions; a value the store drops is not recorded.

    Written against the column rather than the model because that is where the requirement bites:
    a `token_count` that exists only in Python is recorded until the process exits.
    """
    _entry(seeded, "cost:1", "ACTUAL", token_count=12_345, compute_units=7)
    row = seeded.execute(
        "SELECT token_count, compute_units FROM cost_entries WHERE cost_entry_id = 'cost:1'"
    ).fetchone()
    assert row[0] == 12_345
    assert row[1] == 7, "tokens and compute units are separate columns, not one number"


def test_negative_token_counts_are_rejected(seeded):
    with pytest.raises(psycopg.errors.CheckViolation):
        _entry(seeded, "cost:1", "ACTUAL", token_count=-1)


def test_an_approval_carries_a_token_overrun_that_defaults_to_zero(seeded):
    """`approved_overrun` is an amount, so its zero means zero headroom -- not "unlimited"."""
    _approval(seeded)
    row = seeded.execute(
        "SELECT overrun_token_count FROM budget_approvals WHERE approval_id = 'apr:1'"
    ).fetchone()
    assert row[0] == 0


# --------------------------------------------------------------------------------------------
# ONCE, enforced by the database rather than by the caller's memory. §17.17.1.
#
# The Python gate can only be *told* which approvals were already spent. Two dispatches that are
# both told "none" are both correct on their inputs and both release the same overrun. So the
# transition from unconsumed to consumed has to be indivisible, and only the store can make it so.
# --------------------------------------------------------------------------------------------


@pytest.fixture
def second_connection() -> Iterator[psycopg.Connection]:
    """A genuinely separate session, so the race below is a race and not two calls in one client."""
    connection = psycopg.connect(
        os.environ.get("LAB_BRAIN_DATABASE_URL", DEFAULT_URL), autocommit=True, connect_timeout=5
    )
    with connection:
        yield connection


def test_a_claim_records_who_consumed_it_and_when(seeded):
    _approval(seeded)
    assert SqlBudgetApprovalClaims(seeded).claim("apr:1", ACTION, NOW) is True
    row = seeded.execute(
        "SELECT consumed_at, consumed_by_action FROM budget_approvals WHERE approval_id = 'apr:1'"
    ).fetchone()
    assert row[0] == NOW
    assert row[1] == ACTION


def test_a_second_claim_of_the_same_approval_returns_false(seeded):
    """Not an exception. A caller that must distinguish winning from losing should not have to
    do it by catching."""
    _approval(seeded)
    claims = SqlBudgetApprovalClaims(seeded)
    assert claims.claim("apr:1", ACTION, NOW) is True
    assert claims.claim("apr:1", ACTION, NOW + dt.timedelta(seconds=1)) is False


def test_a_claim_for_an_action_the_approval_was_not_granted_for_returns_false(seeded):
    """The `action_ref` is in the WHERE clause, not only in the table's CHECK constraint."""
    _approval(seeded)
    assert SqlBudgetApprovalClaims(seeded).claim("apr:1", "act:something_else#1", NOW) is False
    row = seeded.execute(
        "SELECT consumed_at FROM budget_approvals WHERE approval_id = 'apr:1'"
    ).fetchone()
    assert row[0] is None, "a refused claim must leave the approval spendable"


def test_a_claim_on_an_unknown_approval_returns_false(seeded):
    assert SqlBudgetApprovalClaims(seeded).claim("apr:ghost", ACTION, NOW) is False


def test_two_concurrent_sessions_claiming_one_approval_produce_one_winner(
    seeded, second_connection
):
    """The property the whole module exists for, across two real connections.

    Both statements are released at once by a barrier. PostgreSQL takes a row lock for the duration
    of the UPDATE, so the loser blocks, re-evaluates `consumed_at IS NULL` against the committed row
    and matches nothing.

    A SELECT-then-UPDATE would pass every sequential test above and fail here: under READ COMMITTED
    both sessions can read `consumed_at IS NULL` and both proceed. That is why the condition lives
    in the write.
    """
    _approval(seeded)
    start = threading.Barrier(2)

    def attempt(connection) -> bool:
        start.wait(timeout=10)
        return SqlBudgetApprovalClaims(connection).claim("apr:1", ACTION, NOW)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = [
            f.result(timeout=30)
            for f in [pool.submit(attempt, c) for c in (seeded, second_connection)]
        ]

    assert results.count(True) == 1, f"expected exactly one winner, got {results}"
    rows = seeded.execute(
        "SELECT count(*) FROM budget_approvals WHERE consumed_at IS NOT NULL"
    ).fetchone()
    assert rows[0] == 1


def test_authorize_dispatch_over_a_real_ledger_releases_once(seeded):
    """The gate and the store wired together: one release, then refusal, against real SQL.

    The approver is constructed in Python because the gate is pure and takes the records as inputs
    -- but the *claim* goes to the database, which is the half that could not be faked.
    """
    _approval(seeded)
    supervisor = Actor(actor_id="act:test", actor_type=ActorType.HUMAN)
    membership = ProjectMembership(
        actor_id="act:test",
        project_id="prj:test",
        role="supervisor",
        approval_scopes=frozenset({BUDGET_OVERRUN_SCOPE}),
    )
    request = BudgetRequest(
        action_ref=ACTION,
        project_id="prj:test",
        episode_id="ep:1",
        actor_id="slot:planner",
        estimate=CostVector(money_estimate=Decimal("75.00")),
        consumed=CostVector(),
        policy=BudgetPolicy(
            policy_id="pol:s",
            policy_version="1.0.0",
            project_id="prj:test",
            caps=BudgetCaps(money_estimate=Decimal("50.00")),
        ),
        now=NOW,
        approval=BudgetApproval(
            approval_id="apr:1",
            approver_actor_id="act:test",
            project_id="prj:test",
            episode_id="ep:1",
            action_ref=ACTION,
            policy_id="pol:s",
            policy_version="1.0.0",
            approved_overrun=CostVector(money_estimate=Decimal("100.00")),
            granted_at=NOW - dt.timedelta(minutes=5),
            expires_at=NOW + dt.timedelta(minutes=30),
        ),
        approver=supervisor,
        approver_membership=membership,
    )
    claims = SqlBudgetApprovalClaims(seeded)

    first = authorize_dispatch(request, claims)
    second = authorize_dispatch(request, claims)

    assert first.outcome is DispatchOutcome.ALLOWED_BY_APPROVAL
    assert second.outcome is DispatchOutcome.BLOCKED
    assert "already consumed" in second.reason


def test_a_policy_is_versioned_not_overwritten(seeded):
    """Caps change; approvals are granted against a version. Both versions must coexist."""
    seeded.execute(
        "INSERT INTO budget_policies (policy_id, policy_version, project_id, cap_money_estimate)"
        " VALUES ('pol:s', '2.0.0', 'prj:test', 10.00)"
    )
    rows = seeded.execute(
        "SELECT policy_version FROM budget_policies WHERE policy_id = 'pol:s'"
        " ORDER BY policy_version"
    ).fetchall()
    assert [r[0] for r in rows] == ["1.0.0", "2.0.0"]
