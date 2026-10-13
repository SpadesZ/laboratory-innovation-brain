"""Two false-confirmation counterexamples, preserved (Causal Warrant Gate V1, design stage).

1. PROXY SUPPORT. Recorded reproduction: `epi:7b56877f` (2026-10-13, `prj:bench-gemini`). Two
features together:

    the true mechanism is absent    no rival proposed a length normalization error
    a proxy SUPPORTS                a hypothesis whose mechanism (a missing contact-resistance
                                    correction) cannot change the normalization basis declared
                                    `sp.normalization_basis = DISAGREES -> SUPPORTS`

The check observed DISAGREES because of the true cause, every governed step did what it is
specified to do, and the loop CONFIRMED the wrong mechanism. Nothing in the architecture asks
whether the observable a hypothesis bound to can diagnose its mechanism; see
`docs/implementation/causal-warrant-gate-v1.md`.

2. SHARED SUPPORT. Found while designing the gate, not in a recorded run: when two rivals declare
SUPPORTS on the same outcome, the one observation promotes both, and the loop confirms whichever
hypothesis id sorts first -- in production a minted UUID, so the choice is arbitrary. Here the true
cause is SUPPORTED too and the other one is confirmed, with no note.

HOW IT IS REPRODUCED WITHOUT A MODEL. `run_case` takes the fixture as data, so the counterexample is
the fixture with the normalization rival's mechanism and statement replaced and its predictions kept
-- the certificate shape the recorded run produced. The deterministic scientist proposes it, the
real readers execute, and the real policies decide.

STRICT XFAIL, AND WHAT FLIPS IT. The negative test states the property the gate must establish and
is expected to fail with an AssertionError until the gate exists; `strict=True` turns an unexpected
pass into a failure, so the marker has to be removed by the change that fixes it. The positive
control is the same case with the catalog's own mechanism, and it must keep confirming.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from lab_brain.core.models.failure import ResolutionStatus
from lab_brain.verification.loop import StopReason
from tests.vertical_fixtures import case_by_id, load_fixture, run_case

pytestmark = pytest.mark.postgres

CASE = "normalization-taper"
PROXY_MECHANISM = "missing contact-resistance correction"


def _proxy_fixture() -> dict[str, Any]:
    """The fixture with the true mechanism replaced by one its own check cannot diagnose."""
    fx = copy.deepcopy(load_fixture())
    proxy = fx["mechanisms"]["normalization_error"]
    proxy["mechanism"] = PROXY_MECHANISM
    proxy["statement"] = (
        "The extraction omits the contact-resistance correction term, leaving the reported series "
        "resistance uncorrected."
    )
    proxy["falsifier"] = "the normalization basis agrees, so the correction was not missing"
    return fx


def _shared_outcome_fixture() -> dict[str, Any]:
    """The contact rival also claims the normalization check's outcomes, as its own pair does.

    An outcome two rivals both declare as SUPPORTS discriminates neither of them.
    """
    fx = copy.deepcopy(load_fixture())
    shared = copy.deepcopy(fx["mechanisms"]["normalization_error"]["predictions"])
    contact = fx["mechanisms"]["contact_discontinuity"]
    contact["predictions"] = [*contact["predictions"], *shared]
    return fx


def test_the_catalog_mechanism_still_confirms_on_its_own_check(db):
    """Positive control: the declared mechanism and its declared check confirm the true cause."""
    fx = load_fixture()
    run = run_case(db, fx, case_by_id(fx, CASE))
    assert run.result.stop_reason is StopReason.CONFIRMED
    assert run.mechanism_of(run.result.confirmed_root_cause) == "normalization_error"
    assert run.result.failure_analysis.failure_class == "length normalization error"


def test_the_counterexample_reproduces_the_recorded_mechanism(db):
    """Characterises today's path, so the xfail below cannot pass for an unrelated reason."""
    fx = _proxy_fixture()
    run = run_case(db, fx, case_by_id(fx, CASE))
    mechanisms = {c.hypothesis.mechanism for c in run.debate.certificates}
    assert PROXY_MECHANISM in mechanisms
    assert "length normalization error" not in mechanisms


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "Causal Warrant Gate V1 is not implemented: a SUPPORTS whose diagnostic link nobody "
        "accountable has warranted still confirms a root cause"
    ),
)
def test_a_support_on_a_non_diagnostic_observable_does_not_confirm(db):
    fx = _proxy_fixture()
    run = run_case(db, fx, case_by_id(fx, CASE))
    analysis = run.result.failure_analysis
    assert analysis.resolution_status is not ResolutionStatus.CONFIRMED, (
        f"{analysis.confirmed_root_cause} confirmed as {analysis.failure_class!r} on "
        "sp.normalization_basis, an observable its mechanism cannot change"
    )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "Causal Warrant Gate V1 is not implemented: two rivals SUPPORTED on one shared outcome "
        "and the loop confirms the one whose id sorts first"
    ),
)
def test_a_confirmed_cause_has_no_rival_supported_beside_it(db):
    fx = _shared_outcome_fixture()
    run = run_case(db, fx, case_by_id(fx, CASE))
    supported = sorted(
        {
            str(run.mechanism_of(t.hypothesis_id))
            for s in run.result.steps
            for t in s.transitions
            if t.to_state == "SUPPORTED" and t.event_id
        }
    )
    confirmed = run.result.failure_analysis.resolution_status is ResolutionStatus.CONFIRMED
    assert not (confirmed and len(supported) > 1), (
        f"confirmed {run.mechanism_of(run.result.confirmed_root_cause)} while {supported} were "
        "all SUPPORTED by the same normalization-basis outcome"
    )
