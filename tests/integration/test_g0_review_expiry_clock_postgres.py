"""G0 round 5, Q8 (time sources): an automatic review expiry is judged by the caller's clock.

`review_expire` (`011f`) refuses an expiry whose `p_now` is before the review's declared deadline
-- but `p_now` is whatever the caller passes. The product's sweep (`ReviewExpiryProcessor`) passes
its own clock; any writer of SQL can pass next week. An expiry records a REVIEW_EXPIRY governance
event as the declaring person's standing decision and closes the linked conflict as
ACCEPTED_AS_OPEN_QUESTION, so expiring early is a way to clear an inconvenient review (the
function's own words). The same shape as the belief gate's writer times (`011z`, round 4): the
database's clock bounds a time a writer supplies.

Fixed by `010e` (a REVIEW_EXPIRY event is not dated after the database clock plus the `011z` skew);
the sweep's refusal is reported per review, and the review stays outstanding.

Engineering evidence only. G0 is NOT PASSED.
"""

from __future__ import annotations

import datetime as dt

import pytest

from lab_brain.core.repositories.reviews import SqlReviewItemStore
from tests.integration.test_review_expiry_postgres import _escalate, _sweep
from tests.integration.test_review_expiry_postgres import world as world

pytestmark = pytest.mark.postgres


def test_q8_a_review_is_not_expired_before_its_deadline_by_a_future_clock(world):
    review = _escalate(world, "rev:q8", "cfl:q8")
    # Created at T0 (in the past) with a 48 h HIGH expiry: re-escalated now so the deadline is
    # ahead of the database clock.
    now = dt.datetime.now(dt.UTC)
    world.execute(
        "UPDATE review_items SET expires_at = %s WHERE review_id = %s",
        (now + dt.timedelta(days=2), review.review_id),
    )
    swept = _sweep(world, now=now + dt.timedelta(days=7))
    status = SqlReviewItemStore(world).get(review.project_id, review.review_id)
    print(f"Q8 sweep dated a week ahead: expired={swept.expired}; status={status.status}")  # type: ignore[union-attr]
    assert swept.expired == ()
    assert status is not None and status.status.value == "QUEUED"
