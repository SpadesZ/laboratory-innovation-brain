"""EPI-005: the read-side authorization gate, one case per fail-closed condition (`v3.3-a12`).

WHY THIS MODULE EXISTS SEPARATELY FROM THE E2E ONE. The e2e test proves the case that matters most
-- a semantically forged Decision, written by raw SQL, accepted by PostgreSQL, refused on read. But
most of the gate's conditions cannot be *reached* from e2e, because `005d` and the Pydantic model
already refuse them before a row exists. A mutation run made that concrete: removing the ALLOW
check, the linkage check, the missing-authorization check, the genesis check or the capability
sentinel left the whole postgres suite green.

That is not a reason to delete those checks. §17.14.1 puts the obligation on the reader precisely
because the writer is not the only way rows appear, and "the database would have caught it" is the
assumption this project keeps disproving -- a support script, a migration or a future service
writes SQL, and `model_copy` skips validators in process. So the gate is tested here against
in-memory stores, where an event can be put into each of those states directly.

Assertions are on :class:`VerificationFailure`, never on message text. A gate that failed closed
for the wrong reason would be indistinguishable from one that worked.
"""

from __future__ import annotations

import datetime as dt

import pytest

from lab_brain.core.belief import (
    BeliefScopeError,
    UnverifiedBeliefRevision,
    VerificationFailure,
    VerifiedBeliefRevision,
    authorize_transition,
    verified_history,
    verify_stored_revision,
)
from lab_brain.core.models import BeliefRevisionEvent, BeliefState, BeliefTargetType
from lab_brain.core.models.decision import BeliefTransitionDecision
from lab_brain.core.models.transition import TransitionOutcome
from tests.contract.test_transition_policy import hypothesis, policy, relation, summary

pytestmark = [pytest.mark.requirement("EPI-005"), pytest.mark.spec_test("T-EPI-005")]

T0 = dt.datetime(2026, 9, 16, 9, 0, tzinfo=dt.UTC)
PROJECT = "prj:photonics"
HYP = "hyp:rs-contact-resistance"
TRACE = "trc:verify-1"


class Lookup:
    """An in-memory decision *and* policy lookup, matching both Protocols structurally.

    One class rather than two because every test needs both and the pair is always consistent;
    splitting them would put half the setup in each test for no gain.
    """

    def __init__(
        self,
        decisions: dict[str, BeliefTransitionDecision] | None = None,
        policies: dict[tuple[str, str], object] | None = None,
        raises: Exception | None = None,
    ) -> None:
        self._decisions = decisions or {}
        self._policies = policies or {}
        self._raises = raises

    def get(self, *args: str):  # type: ignore[no-untyped-def]
        if len(args) == 2:
            return self._policies.get((args[0], args[1]))
        if self._raises is not None:
            raise self._raises
        return self._decisions.get(args[0])


def authorization(**overrides: object) -> BeliefTransitionDecision:
    """A real ALLOW, computed rather than asserted."""
    defaults: dict[str, object] = {
        "decision_id": "dec:1",
        "policy": policy(),
        "hypothesis": hypothesis(),
        "admitted_relations": (relation(),),
        "independence_summary": summary(),
        "candidate_to_state": BeliefState.SUPPORTED,
        "created_at": T0,
    }
    defaults.update(overrides)
    return authorize_transition(**defaults)  # type: ignore[arg-type]


def event(**overrides: object) -> BeliefRevisionEvent:
    defaults: dict[str, object] = {
        "event_id": "bre:1",
        "project_id": PROJECT,
        "target_type": BeliefTargetType.HYPOTHESIS,
        "target_id": HYP,
        "from_state": BeliefState.ACTIVE,
        "to_state": BeliefState.SUPPORTED,
        "triggering_relation_ids": ("rel:1",),
        "policy_id": "pol:hypothesis-default",
        "policy_version": "1.0.0",
        "authorization_decision_id": "dec:1",
        "occurred_at": T0,
        "trace_id": TRACE,
    }
    defaults.update(overrides)
    return BeliefRevisionEvent(**defaults)  # type: ignore[arg-type]


def stores(**overrides: object) -> Lookup:
    """The consistent, passing world: the honest authorization and the policy that produced it."""
    decision = overrides.pop("decision", authorization())
    assert isinstance(decision, BeliefTransitionDecision)
    return Lookup(
        decisions={decision.decision_id: decision},
        policies={(decision.policy_id, decision.policy_version): policy()},
        **overrides,  # type: ignore[arg-type]
    )


def verify(ev: BeliefRevisionEvent, lookup: Lookup, **kwargs: object) -> VerifiedBeliefRevision:
    return verify_stored_revision(
        event=ev,
        decisions=lookup,
        policies=lookup,
        **kwargs,  # type: ignore[arg-type]
    )


def failure(ev: BeliefRevisionEvent, lookup: Lookup, **kwargs: object) -> VerificationFailure:
    with pytest.raises(UnverifiedBeliefRevision) as caught:
        verify(ev, lookup, **kwargs)
    return caught.value.reason


# --------------------------------------------------------------------------------------------
# The gate is passable.
# --------------------------------------------------------------------------------------------


def test_an_honest_stored_event_verifies():
    """Or belief could never be read back at all."""
    verified = verify(event(), stores())
    assert verified.origin == "TRANSITION"
    assert verified.event.event_id == "bre:1"


def test_a_genesis_event_verifies_as_an_admission():
    """§8's admission gate, checked against its own rule rather than exempted from checking."""
    verified = verify(
        event(from_state=None, to_state=BeliefState.ACTIVE, authorization_decision_id=None),
        stores(),
    )
    assert verified.origin == "ADMISSION"


# --------------------------------------------------------------------------------------------
# One case per fail-closed condition the ruling named.
# --------------------------------------------------------------------------------------------


def test_a_non_genesis_event_with_no_authorization_is_refused():
    """The model refuses this too, and `model_copy` skips the model.

    Built with `model_copy` on purpose: that is how a stored event ends up in this state in
    process, and it is why the gate cannot delegate the check to the constructor.
    """
    unauthorized = event().model_copy(update={"authorization_decision_id": None})
    assert failure(unauthorized, stores()) is VerificationFailure.AUTHORIZATION_MISSING


def test_an_authorization_that_does_not_exist_is_refused():
    assert (
        failure(event(authorization_decision_id="dec:missing"), stores())
        is VerificationFailure.AUTHORIZATION_NOT_FOUND
    )


def test_a_snapshot_that_cannot_be_hydrated_is_refused():
    """A stored row that no longer satisfies the Decision model authorises nothing.

    Treated as absent rather than as a transient read error, because from the projector's side
    those are indistinguishable and only one of the two readings is safe.
    """
    broken = stores()
    broken._raises = ValueError("decision_input_snapshot: candidate_to_state missing")
    assert failure(event(), broken) is VerificationFailure.SNAPSHOT_NOT_HYDRATABLE


def test_a_decision_of_another_type_does_not_authorise_a_transition():
    """§17.14.1 reserves `Decision` for other decision types; none of them authorise this."""
    other = authorization().model_copy(update={"decision_type": "BUDGET_APPROVAL"})
    assert failure(event(), stores(decision=other)) is VerificationFailure.WRONG_DECISION_TYPE


@pytest.mark.parametrize(
    "result",
    [
        TransitionOutcome.DENY,
        TransitionOutcome.NEED_MORE_EVIDENCE,
        TransitionOutcome.NEED_HUMAN_REVIEW,
    ],
)
def test_a_non_allow_authorization_does_not_authorise(result):
    """Only ALLOW authorises. NEED_HUMAN_REVIEW is the dangerous one -- it reads as progress."""
    refused = authorization().model_copy(update={"result": result})
    assert failure(event(), stores(decision=refused)) is VerificationFailure.NOT_AN_ALLOW


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("project_id", "prj:other"),
        ("subject_id", "hyp:something-else"),
        ("policy_id", "pol:other"),
        ("policy_version", "2.0.0"),
        ("from_state", BeliefState.CHALLENGED),
        ("to_state", BeliefState.CONTRADICTED),
    ],
)
def test_an_authorization_that_covers_something_else_is_refused(field, value):
    """Every component of the linkage, one at a time.

    Parametrized rather than written as one combined case so a check that covered five of the six
    still fails here -- which is the mistake a hand-written conjunction actually makes.
    """
    mismatched = authorization().model_copy(update={field: value})
    assert failure(event(), stores(decision=mismatched)) is VerificationFailure.LINKAGE_MISMATCH


def test_an_unregistered_policy_version_is_refused():
    """An authorization that cannot be re-run is the thing `v3.3-a12` forbids."""
    lookup = stores()
    lookup._policies = {}
    assert failure(event(), lookup) is VerificationFailure.POLICY_NOT_FOUND


def test_a_named_comparator_that_cannot_be_resolved_is_refused():
    """Not a fallback to `None`: re-deriving without it answers a different question.

    §17.14.1 forbids storing the comparison results, so there is nothing to fall back on -- by
    design, because stored results would put the authority rules beyond falsification (§10.5.1).
    """

    class Comparator:
        policy_id = "auth:toy"
        policy_version = "1.0.0"

        def compare(self, a: str, b: str):  # pragma: no cover - identity is what matters here
            raise AssertionError("must not be called")

        def meets(self, required_rule: str, candidate: str) -> bool:
            return True

    with_comparator = authorization(authority_policy=Comparator())
    assert (
        failure(event(), stores(decision=with_comparator))
        is VerificationFailure.COMPARATOR_UNRESOLVED
    )

    verified = verify(
        event(),
        stores(decision=with_comparator),
        authority_policies={("auth:toy", "1.0.0"): Comparator()},
    )
    assert verified.origin == "TRANSITION"


def test_a_semantically_forged_authorization_is_refused():
    """The P0 case, at contract level: consistent, ALLOW-labelled, and it re-derives to non-ALLOW.

    The e2e module proves the same thing through PostgreSQL. This one pins it without a database,
    so it runs in the backend-free profile too -- the guard should not be provable only where a
    container is available (AGT-007).
    """
    really_refused = authorization(independence_summary=summary(independent_count=0))
    assert really_refused.result is not TransitionOutcome.ALLOW

    claimed = really_refused.model_copy(
        update={
            "result": TransitionOutcome.ALLOW,
            "evaluated": really_refused.evaluated.model_copy(
                update={"outcome": TransitionOutcome.ALLOW}
            ),
        }
    )
    assert claimed.authorizes_transition, "the forgery must look valid on its face"
    assert claimed.input_hash == claimed.decision_input_snapshot.input_hash()

    assert failure(event(), stores(decision=claimed)) is VerificationFailure.NOT_REDERIVABLE


def test_a_tampered_input_hash_is_refused_on_read():
    """The binding is re-checked here, not trusted from construction."""
    tampered = authorization().model_copy(update={"input_hash": "sha256:" + "0" * 64})
    assert failure(event(), stores(decision=tampered)) is VerificationFailure.NOT_REDERIVABLE


def test_a_genesis_event_carrying_an_authorization_is_refused():
    """The other direction: admission must not borrow transition authority (§8)."""
    genesis = event(
        from_state=None, to_state=BeliefState.ACTIVE, authorization_decision_id=None
    ).model_copy(update={"authorization_decision_id": "dec:1"})
    assert failure(genesis, stores()) is VerificationFailure.GENESIS_CLAIMS_AUTHORIZATION


# --------------------------------------------------------------------------------------------
# The capability, and the history.
# --------------------------------------------------------------------------------------------


def test_the_verification_capability_cannot_be_constructed_directly():
    """Same pattern as `AuthorizedRevision`, and not a security boundary either.

    Someone who imports the private sentinel can mint one, and `tests/conftest_fixtures.py`
    does exactly that for the reducer's own tests. The property is that it cannot happen by
    accident and that the line doing it appears in a diff.
    """
    with pytest.raises(UnverifiedBeliefRevision, match="cannot be constructed directly"):
        VerifiedBeliefRevision(event=event(), origin="TRANSITION")


def test_a_history_with_one_unverifiable_revision_is_refused_whole():
    """Refused, not filtered.

    A history containing one unverifiable revision is not that history minus the revision.
    Returning a projection built from the rest would be a plausible answer that hides the fact
    that something wrote a belief nobody authorised.
    """
    good = event(event_id="bre:1")
    bad = event(event_id="bre:2", authorization_decision_id="dec:missing")

    with pytest.raises(UnverifiedBeliefRevision) as caught:
        verified_history(
            project_id=PROJECT,
            target_id=HYP,
            events=[good, bad],
            decisions=stores(),
            policies=stores(),
        )
    assert caught.value.reason is VerificationFailure.AUTHORIZATION_NOT_FOUND


def test_a_verified_history_is_ordered_by_occurrence():
    """Deterministic input to a deterministic fold, ordered on `(occurred_at, event_id)`."""
    later = event(event_id="bre:2", occurred_at=T0 + dt.timedelta(hours=1))
    earlier = event(event_id="bre:1")

    revisions = verified_history(
        project_id=PROJECT,
        target_id=HYP,
        events=[later, earlier],
        decisions=stores(),
        policies=stores(),
    )
    assert [r.event.event_id for r in revisions] == ["bre:1", "bre:2"]


# --------------------------------------------------------------------------------------------
# Request scope. `verified_history` answers a question about one target in one project, and it
# must refuse anything else rather than narrowing to it.
# --------------------------------------------------------------------------------------------


def history(project_id: str, target_id: str, events: list[BeliefRevisionEvent]):  # type: ignore[no-untyped-def]
    return verified_history(
        project_id=project_id,
        target_id=target_id,
        events=events,
        decisions=stores(),
        policies=stores(),
    )


def test_a_verified_history_refuses_a_wrong_target_request():
    """Same project, and not the requested target.

    The dangerous case, because narrowing would return an empty tuple and an empty history is a
    legitimate answer -- "this hypothesis has no events yet" -- so the caller would get a
    confident wrong result rather than an error.
    """
    with pytest.raises(BeliefScopeError, match="target"):
        history(PROJECT, "hyp:not-this-one", [event()])


def test_a_verified_history_refuses_a_wrong_project_request():
    """The other single-axis case, so neither guard can be standing in for the other."""
    with pytest.raises(BeliefScopeError, match="project"):
        history("prj:not-this-one", HYP, [event()])


def test_a_verified_history_refuses_mixed_targets():
    """One requested target present, one not. Partial narrowing is still narrowing."""
    mine = event(event_id="bre:1")
    theirs = event(event_id="bre:2", target_id="hyp:other")

    with pytest.raises(BeliefScopeError, match="target"):
        history(PROJECT, HYP, [mine, theirs])


def test_a_verified_history_refuses_mixed_projects():
    mine = event(event_id="bre:1")
    theirs = event(event_id="bre:2", project_id="prj:other")

    with pytest.raises(BeliefScopeError, match="project"):
        history(PROJECT, HYP, [mine, theirs])


def test_scope_is_checked_before_authorization():
    """An out-of-scope event is a wrong query, not an unauthorised belief.

    Ordering matters for the reader: reporting this as `NOT_REDERIVABLE` or
    `AUTHORIZATION_NOT_FOUND` would send whoever sees it looking for a forgery. The event below
    would fail verification too -- its authorization does not exist -- and the scope error must
    still win.
    """
    out_of_scope = event(target_id="hyp:other", authorization_decision_id="dec:missing")

    with pytest.raises(BeliefScopeError):
        history(PROJECT, HYP, [out_of_scope])
