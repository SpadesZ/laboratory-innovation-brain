"""The database enforces the ledger and approval invariants, not only the Python gate (COST-001).

A pure budget gate is bypassed by anything that writes SQL -- a migration, a support script, a
future service. If "the ledger is append-only" and "an approval releases one action once" hold only
in `lab_brain.core.budget`, they hold only for callers who go through it.

So each invariant is asserted twice: once against the model and the gate in
tests/contract/test_budget_gate.py, once here against the schema.
"""

from __future__ import annotations

import datetime as dt

import psycopg
import pytest

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.requirement("COST-001"),
    pytest.mark.spec_test("T-COST-001"),
]

NOW = dt.datetime(2026, 9, 14, 12, 0, tzinfo=dt.UTC)
ACTION = "act:run_charge_dc_sweep#7"


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
