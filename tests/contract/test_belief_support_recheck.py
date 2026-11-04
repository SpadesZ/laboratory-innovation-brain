"""EPI-005 / 011w: the projection re-checks every SUPPORTS a stored decision counted.

`verify_stored_revision` re-derives a stored decision from its own snapshot, which proves the
verdict follows from the relations recorded in it -- not that each of them is support now. A
SUPPORTS of a post-screening hypothesis is support only when its verification authorization
verifies (011w), which SQL cannot check. Every current read asks that
(`SqlRelationStore.admitted_for_subject`); a decision row recorded by a writer that did not ask
must not become a belief. `support_check` is that question, asked of the snapshot's copies.

In-memory and pure, so each branch is reachable without a database; the end-to-end reproduction is
`tests/e2e/test_g0_security_assurance_postgres.py`.
"""

from __future__ import annotations

import pytest

from lab_brain.core.belief import VerificationFailure
from lab_brain.core.models import RelationType
from lab_brain.core.models.relation import RelationJudgment
from tests.contract.test_belief_authorization_verification import (
    authorization,
    event,
    failure,
    stores,
    verify,
)
from tests.contract.test_transition_policy import relation

pytestmark = [pytest.mark.requirement("EPI-005"), pytest.mark.spec_test("T-EPI-005")]


def test_a_support_the_check_accepts_still_verifies():
    """Positive control: a signed support (the check finds nothing) changes nothing."""
    asked: list[str] = []

    def check(r: RelationJudgment) -> str | None:
        asked.append(r.relation_id)
        return None

    assert verify(event(), stores(), support_check=check).event.event_id == "bre:1"
    assert asked == ["rel:1"]


def test_a_support_the_check_refuses_is_not_a_belief():
    reason = failure(
        event(),
        stores(),
        support_check=lambda r: "signature does not verify (011w): it licenses nothing",
    )
    assert reason is VerificationFailure.SUPPORT_UNVERIFIED


def test_a_check_that_cannot_run_refuses():
    def broken(r: RelationJudgment) -> str | None:
        raise RuntimeError("the database went away")

    assert (
        failure(event(), stores(), support_check=broken) is VerificationFailure.SUPPORT_UNVERIFIED
    )


def test_a_support_to_another_subject_is_refused_before_it_is_checked():
    """A snapshot SUPPORTS naming another hypothesis (or project) would be checked against THAT
    hypothesis's screening record -- one with none would pass unchecked. It is not this decision's
    support at all."""
    asked: list[str] = []

    def check(r: RelationJudgment) -> str | None:
        asked.append(r.relation_id)
        return None

    elsewhere = authorization(admitted_relations=(relation(to_entity_id="hyp:pre-screening"),))
    lookup = stores(decision=elsewhere)
    assert failure(event(), lookup, support_check=check) is VerificationFailure.SUPPORT_UNVERIFIED
    other_project = authorization(admitted_relations=(relation(project_id="prj:other"),))
    assert (
        failure(event(), stores(decision=other_project), support_check=check)
        is VerificationFailure.SUPPORT_UNVERIFIED
    )
    assert asked == []


def test_only_supports_are_asked_about():
    """CONTRADICTS can only block a promotion; the authorization rule is about support."""
    asked: list[str] = []

    def check(r: RelationJudgment) -> str | None:
        asked.append(r.relation_id)
        return "refused"

    both = authorization(
        admitted_relations=(
            relation(RelationType.CONTRADICTS, relation_id="rel:against"),
            relation(),
        )
    )
    assert failure(event(), stores(decision=both), support_check=check) is (
        VerificationFailure.SUPPORT_UNVERIFIED
    )
    assert asked == ["rel:1"]


def test_without_a_check_the_gate_is_unchanged():
    """In-memory relation sources hold no screening records; nothing is asked of them."""
    assert verify(event(), stores()).event.event_id == "bre:1"
