"""T-EVI-008 — retraction / erratum / version status, with the record persisted (§6.21).

§26's pass condition: *retracted/erratum fixture records source status and blocks/flags major
belief promotion per SourcePolicy.*

Both halves are asserted, and the first is the one that is easy to lose. "Records source status"
is not satisfied by a function returning a status -- it has to survive to the row, because the
failure §6.21 is written against is the one you discover six months later. So every fixture below
is written to `source_works.retraction_check` and read back.

FIVE FIXTURES, deterministic, no network:

    normal      ACTIVE                -> ALLOW
    newer       SUPERSEDED            -> flag, and names its successor
    erratum     ERRATUM_ISSUED        -> flag
    retracted   RETRACTED             -> BLOCK, and names the notice
    unavailable provider raises       -> SOURCE_UNAVAILABLE, never ALLOW

The last one is the requirement's real subject. A registry that cannot be reached returns the
same *bytes* as one that found no retraction -- an empty result -- and a system that conflates
them records "checked, fine" for a paper nobody checked.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from lab_brain.core.models.enums import SourceWorkStatus, SourceWorkType, TrustClass
from lab_brain.core.models.source_work import RetractionCheck, SourceWork
from lab_brain.evidence.source_status import (
    INDETERMINATE_STATUSES,
    RevisionOutcome,
    SourcePolicy,
    SourceStatusError,
    SourceStatusReport,
    check_source_work,
    evaluate_major_revision,
)

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.requirement("EVI-008"),
    pytest.mark.spec_test("T-EVI-008"),
]

NOW = dt.datetime(2026, 9, 21, 12, 0, tzinfo=dt.UTC)


class _FakeRegistry:
    """A deterministic retraction registry. No network, no clock, no ordering dependence."""

    def __init__(self, answers: dict[str, SourceStatusReport], *, unreachable: bool = False):
        self._answers = answers
        self._unreachable = unreachable

    def provider_id(self) -> str:
        return "fake.crossref"

    def lookup(self, work: SourceWork) -> SourceStatusReport:
        if self._unreachable:
            raise SourceStatusError("connection refused")
        report = self._answers.get(work.source_work_id)
        if report is None:
            # "No notice on file" is a real ACTIVE answer -- distinct from being unable to ask,
            # which is the branch above. Conflating them is the defect this file is about.
            return SourceStatusReport(
                status=SourceWorkStatus.ACTIVE, checked_against="fake.crossref"
            )
        return report


def _work(source_work_id: str, *, check: RetractionCheck | None = None) -> SourceWork:
    return SourceWork(
        source_work_id=source_work_id,
        work_type=SourceWorkType.JOURNAL_ARTICLE,
        title="Reverse-bias capacitance anomaly in a ring modulator",
        trust_class=TrustClass.PEER_REVIEWED,
        retraction_check=check or RetractionCheck(),
    )


def _persist(db, work: SourceWork) -> None:
    db.execute(
        "INSERT INTO source_works (source_work_id, work_type, title, trust_class, "
        "retraction_check) VALUES (%s, %s, %s, %s, %s) "
        "ON CONFLICT (source_work_id) DO UPDATE SET retraction_check = EXCLUDED.retraction_check",
        (
            work.source_work_id,
            work.work_type.value,
            work.title,
            work.trust_class.value,
            work.retraction_check.model_dump_json(),
        ),
    )


def _reload(db, source_work_id: str) -> RetractionCheck:
    row = db.execute(
        "SELECT retraction_check FROM source_works WHERE source_work_id = %s", (source_work_id,)
    ).fetchone()
    payload = row[0] if isinstance(row[0], dict) else json.loads(row[0])
    return RetractionCheck.model_validate(payload)


def _checked(db, work: SourceWork, registry: _FakeRegistry) -> SourceWork:
    """Run the check, persist it, read it back, and decide from the reloaded record."""
    check = check_source_work(work, registry, now=NOW)
    stored = work.model_copy(update={"retraction_check": check})
    _persist(db, stored)
    return stored.model_copy(update={"retraction_check": _reload(db, work.source_work_id)})


# ---------------------------------------------------------------------------
# The five fixtures
# ---------------------------------------------------------------------------


def test_a_normal_publication_is_recorded_active_and_allows_a_major_revision(db):
    work = _checked(db, _work("swk:normal"), _FakeRegistry({}))
    assert work.retraction_check.status is SourceWorkStatus.ACTIVE
    assert work.retraction_check.checked_at == NOW
    assert evaluate_major_revision(work).outcome is RevisionOutcome.ALLOW


def test_a_superseded_preprint_records_its_successor_and_is_flagged(db):
    """§6.21's first clause: preprint vs 正式版.

    The successor id is asserted because a SUPERSEDED status that does not say *by what* tells a
    reviewer a revision is questionable without telling them where to look instead.
    """
    registry = _FakeRegistry(
        {
            "swk:preprint": SourceStatusReport(
                status=SourceWorkStatus.SUPERSEDED,
                superseded_by_source_work_id="swk:journal-version",
                checked_against="fake.crossref",
            )
        }
    )
    work = _checked(db, _work("swk:preprint"), registry)
    assert work.retraction_check.status is SourceWorkStatus.SUPERSEDED
    assert work.retraction_check.superseded_by_source_work_id == "swk:journal-version"

    decision = evaluate_major_revision(work)
    assert decision.outcome is RevisionOutcome.NEEDS_HUMAN_REVIEW
    assert "swk:journal-version" in decision.reason


def test_an_erratum_is_recorded_and_flagged_rather_than_silently_accepted(db):
    registry = _FakeRegistry(
        {
            "swk:erratum": SourceStatusReport(
                status=SourceWorkStatus.ERRATUM_ISSUED,
                notice_locator="doi:10.1000/erratum.1",
                checked_against="fake.crossref",
            )
        }
    )
    work = _checked(db, _work("swk:erratum"), registry)
    assert work.retraction_check.status is SourceWorkStatus.ERRATUM_ISSUED
    assert work.retraction_check.notice_locator == "doi:10.1000/erratum.1"
    assert evaluate_major_revision(work).outcome is RevisionOutcome.NEEDS_HUMAN_REVIEW


def test_a_retracted_paper_blocks_a_major_revision_and_names_the_notice(db):
    """THE fixture §26 names. Blocked, recorded, and the notice locator survives the round trip."""
    registry = _FakeRegistry(
        {
            "swk:retracted": SourceStatusReport(
                status=SourceWorkStatus.RETRACTED,
                notice_locator="doi:10.1000/retraction.7",
                checked_against="fake.crossref",
            )
        }
    )
    work = _checked(db, _work("swk:retracted"), registry)
    assert work.retraction_check.status is SourceWorkStatus.RETRACTED

    decision = evaluate_major_revision(work)
    assert decision.outcome is RevisionOutcome.BLOCK
    assert not decision.permitted
    assert "doi:10.1000/retraction.7" in decision.reason
    assert decision.policy_version == "1.0.0"


def test_an_unreachable_registry_is_recorded_and_never_reads_as_valid(db):
    """THE defect §6.21 exists to prevent.

    The provider raises. What must NOT happen is an ACTIVE record, a missing record, or an
    exception the caller has nothing to store for. What does happen: SOURCE_UNAVAILABLE, with the
    timestamp and the failure attributed to the provider, and a major revision that does not
    proceed.
    """
    work = _checked(db, _work("swk:offline"), _FakeRegistry({}, unreachable=True))
    assert work.retraction_check.status is SourceWorkStatus.SOURCE_UNAVAILABLE
    assert work.retraction_check.checked_at == NOW
    assert "fake.crossref" in (work.retraction_check.checked_against or "")

    decision = evaluate_major_revision(work)
    assert decision.outcome is not RevisionOutcome.ALLOW
    assert not decision.permitted


# ---------------------------------------------------------------------------
# The rules the policy itself must obey
# ---------------------------------------------------------------------------


def test_a_work_nobody_checked_does_not_read_as_checked(db):
    """An unchecked work and a work checked-as-unknown reach the same outcome, deliberately.

    They are the same epistemic situation. The reason string distinguishes them for whoever has
    to act, which is where the difference is actually useful.
    """
    never = _work("swk:unchecked")
    _persist(db, never)
    decision = evaluate_major_revision(never)
    assert decision.outcome is RevisionOutcome.NEEDS_HUMAN_REVIEW
    assert "no recorded status check" in decision.reason


def test_a_policy_that_allows_on_an_indeterminate_status_cannot_be_constructed():
    """The rule, enforced where it cannot be forgotten.

    A deployment is free to choose whether an erratum blocks or flags. It is not free to decide
    that "we could not ask" means "fine" -- that erases the distinction the record is kept for,
    and it is the one configuration change that would silently undo this whole requirement.
    """
    from lab_brain.evidence.source_status import DEFAULT_SOURCE_POLICY

    for status in INDETERMINATE_STATUSES:
        permissive = dict(DEFAULT_SOURCE_POLICY)
        permissive[status] = RevisionOutcome.ALLOW
        with pytest.raises(ValueError, match="ALLOW"):
            SourcePolicy(policy_id="reckless", outcomes=permissive)


def test_a_policy_missing_a_status_cannot_be_constructed():
    """A status with no entry falls through, which is how 'unavailable' becomes 'fine'."""
    from lab_brain.evidence.source_status import DEFAULT_SOURCE_POLICY

    incomplete = dict(DEFAULT_SOURCE_POLICY)
    del incomplete[SourceWorkStatus.RETRACTED]
    with pytest.raises(ValueError, match="no outcome for"):
        SourcePolicy(policy_id="incomplete", outcomes=incomplete)


def test_a_deployment_may_choose_to_block_on_an_erratum(db):
    """ "blocks/flags ... per SourcePolicy" -- the policy genuinely decides, and it is recorded."""
    strict = SourcePolicy(
        policy_id="source_policy.strict",
        version="2.0.0",
        outcomes={
            **dict.fromkeys(SourceWorkStatus, RevisionOutcome.NEEDS_HUMAN_REVIEW),
            SourceWorkStatus.ACTIVE: RevisionOutcome.ALLOW,
            SourceWorkStatus.ERRATUM_ISSUED: RevisionOutcome.BLOCK,
            SourceWorkStatus.RETRACTED: RevisionOutcome.BLOCK,
        },
    )
    registry = _FakeRegistry(
        {
            "swk:erratum": SourceStatusReport(
                status=SourceWorkStatus.ERRATUM_ISSUED, checked_against="fake.crossref"
            )
        }
    )
    work = _checked(db, _work("swk:erratum"), registry)

    assert evaluate_major_revision(work).outcome is RevisionOutcome.NEEDS_HUMAN_REVIEW
    strict_decision = evaluate_major_revision(work, policy=strict)
    assert strict_decision.outcome is RevisionOutcome.BLOCK
    assert strict_decision.policy_id == "source_policy.strict"
    assert strict_decision.policy_version == "2.0.0"


def test_the_decision_is_a_pure_function_of_the_stored_record(db):
    """Auditability: re-running the decision months later must give the same answer.

    `evaluate_major_revision` never consults a provider, so a past decision can be reconstructed
    from the row. A function that looked up would give a different answer once the registry moved
    on -- and "why was this allowed in March" would become unanswerable. Same split `v3.3-a13`
    draws between acting and deciding.
    """
    registry = _FakeRegistry(
        {"swk:stable": SourceStatusReport(status=SourceWorkStatus.RETRACTED, checked_against="x")}
    )
    work = _checked(db, _work("swk:stable"), registry)
    first = evaluate_major_revision(work)

    # The registry changes its mind. The recorded decision does not.
    registry._answers["swk:stable"] = SourceStatusReport(
        status=SourceWorkStatus.ACTIVE, checked_against="x"
    )
    again = evaluate_major_revision(work)
    assert again == first
