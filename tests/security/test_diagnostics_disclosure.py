"""T-UX-003 — two-tier disclosure through the production service (§17.24, ADR-0009, SEC-001/002).

§26's pass condition, clause by clause:

    Default payload contains no stack trace, file path, repo name or prompt fragment;
    expansion without scope is denied;
    expansion with scope but lower clearance returns redacted detail retaining trace_id/job_id/
    span_id;
    cross-project error_id returns not-found (not permission-denied).

EXERCISED THROUGH `DiagnosticsService`, NOT A FORMATTER. §26 asks for the denial to happen
server-side, and a helper with an `include_technical` flag has already lost -- the decision is
then the caller's and every caller is a place to get it wrong. There is no such flag; the service
is given who is asking and decides what comes back.

THE FOURTH CLAUSE IS THE SUBTLE ONE. "Permission denied" for another project's id is an oracle:
an attacker enumerating ids learns which exist from the difference between two refusals. So the
test compares the two responses rather than only checking that an exception was raised.
"""

from __future__ import annotations

import datetime as dt
import inspect
import typing

import pytest

from lab_brain.core.models.access import Actor, ProjectMembership
from lab_brain.core.models.enums import ActorType, SensitivityLabel
from lab_brain.surface.catalog import default_catalog
from lab_brain.surface.disclosure import (
    VIEW_TECHNICAL_SCOPE,
    DiagnosticsService,
    ErrorNotFound,
    TechnicalDetail,
)
from lab_brain.surface.errors import ErrorClass, ErrorRecord

pytestmark = [pytest.mark.requirement("UX-003"), pytest.mark.spec_test("T-UX-003")]

NOW = dt.datetime(2026, 9, 21, 12, 0, tzinfo=dt.UTC)
PROJECT = "prj:test"
OTHER_PROJECT = "prj:other"

#: The in-memory Actor store every fixture below resolves against. It exists because `actor_of`
#: is a REQUIRED dependency of `DiagnosticsService` -- see
#: `test_the_service_cannot_be_constructed_without_actor_resolution`. Making the fixtures name
#: which accounts exist and which are active is the point: the old fixtures were asserting
#: "act:test is a real, active account" implicitly, by never being able to say otherwise.
ACTIVE_ACTOR = Actor(actor_id="act:test", actor_type=ActorType.HUMAN, display_name="Researcher")
DISABLED_ACTOR = Actor(
    actor_id="act:disabled", actor_type=ActorType.HUMAN, display_name="Departed", active=False
)
ACTORS: dict[str, Actor] = {a.actor_id: a for a in (ACTIVE_ACTOR, DISABLED_ACTOR)}

#: Deliberately full of the four things §26 names: a stack trace, a file path, a repo name and a
#: prompt fragment. A bland fixture would let a leaking implementation pass.
SECRET_DETAIL = TechnicalDetail(
    detail_ref="det:1",
    sensitivity=SensitivityLabel.RESTRICTED_NDA,
    component="FigureParser",
    message="Traceback (most recent call last): ValueError at foundry_pdk.py:184",
    stack_ref="stk:1",
    source_path="/srv/nda/acme-foundry/pdk-v7/process_rules.pdf",
    prompt_fragment="Given the ACME 220nm PDK sidewall angle of ...",
)

RECORD = ErrorRecord(
    error_id="ERR-20260921-0001",
    project_id=PROJECT,
    trace_id="trc:1",
    job_id="job:1",
    span_id="spn:1",
    error_class=ErrorClass.SYSTEM_ERROR,
    reason_code="PARSE_TEXT_FAILED",
    component="FigureParser",
    occurred_at=NOW,
    technical_detail_ref="det:1",
)

OTHER_RECORD = ErrorRecord(
    error_id="ERR-20260921-0999",
    project_id=OTHER_PROJECT,
    trace_id="trc:9",
    error_class=ErrorClass.SYSTEM_ERROR,
    reason_code="PARSE_TEXT_FAILED",
    component="FigureParser",
    occurred_at=NOW,
)


def _membership(
    *,
    scopes: tuple[str, ...] = (),
    clearance: tuple[SensitivityLabel, ...] = (),
    actor_id: str = "act:test",
    project_id: str = PROJECT,
    active: bool = True,
) -> ProjectMembership:
    return ProjectMembership(
        actor_id=actor_id,
        project_id=project_id,
        role="RESEARCHER",
        sensitivity_clearance=clearance,
        approval_scopes=scopes,
        active=active,
    )


def _service(
    membership: ProjectMembership | None,
    *,
    actors: dict[str, Actor] | None = None,
) -> DiagnosticsService:
    """The one supported construction. There is no membership-only mode to build.

    ``membership_of`` returns the row for the project it was granted in, so a membership of
    another project is not silently rewritten into a membership of this one -- the mismatch
    refusal in `can_access_project` has to be reachable for the probe below to mean anything.
    """
    errors = {RECORD.error_id: RECORD, OTHER_RECORD.error_id: OTHER_RECORD}
    store = ACTORS if actors is None else actors
    return DiagnosticsService(
        catalog=default_catalog(),
        load_error=lambda key: errors.get(key),
        load_detail=lambda ref: SECRET_DETAIL if ref == "det:1" else None,
        membership_of=lambda actor, project: (
            membership
            if membership is not None
            and membership.actor_id == actor
            and membership.project_id == project
            else None
        ),
        actor_of=store.get,
    )


# ---------------------------------------------------------------------------
# Clause 1 — the default payload leaks nothing
# ---------------------------------------------------------------------------


def test_the_default_payload_contains_no_technical_detail():
    """Four named leak classes, checked against the whole serialised payload.

    Serialised rather than field-by-field: a leak that appeared in a field the test did not think
    to check is exactly the one worth catching, and `repr` reaches every field.
    """
    payload = _service(_membership()).default_payload(
        RECORD.error_id, actor_id="act:test", project_id=PROJECT
    )
    body = repr(payload)
    for leak in (
        "Traceback",
        "foundry_pdk.py",
        "/srv/nda/",
        "acme-foundry",
        "220nm PDK sidewall",
        "stk:1",
    ):
        assert leak not in body, f"the default payload leaked {leak!r}"
    assert payload.technical is None
    # The pointer survives, so a cleared user knows there IS more to ask for.
    assert payload.message.technical_detail_ref == "det:1"


def test_the_default_payload_keeps_the_trace_references():
    """Without them a support conversation cannot correlate anything."""
    payload = _service(_membership()).default_payload(
        RECORD.error_id, actor_id="act:test", project_id=PROJECT
    )
    assert payload.trace_id == "trc:1"
    assert payload.job_id == "job:1"
    assert payload.span_id == "spn:1"


def test_holding_every_clearance_does_not_put_detail_in_the_default_payload():
    """Tier one is tier one for everyone. Clearance governs *expansion*, not the default."""
    cleared = _membership(
        scopes=(VIEW_TECHNICAL_SCOPE,), clearance=(SensitivityLabel.RESTRICTED_NDA,)
    )
    payload = _service(cleared).default_payload(
        RECORD.error_id, actor_id="act:test", project_id=PROJECT
    )
    assert payload.technical is None
    assert "Traceback" not in repr(payload)


# ---------------------------------------------------------------------------
# Clause 2 — expansion without scope is denied
# ---------------------------------------------------------------------------


def test_expansion_without_the_scope_is_denied_server_side():
    """The scope is checked by the service. There is no flag a caller could pass instead."""
    payload = _service(_membership()).expand(
        RECORD.error_id, actor_id="act:test", project_id=PROJECT
    )
    assert payload.technical is None
    assert payload.technical_withheld
    assert payload.withheld_reason_code == "DIAGNOSTICS_SCOPE_REQUIRED"
    assert "Traceback" not in repr(payload)


def test_an_actor_with_no_membership_cannot_expand():
    """No membership is not a weaker case of no scope -- it does not get to the scope check."""
    with pytest.raises(ErrorNotFound):
        _service(None).expand(RECORD.error_id, actor_id="act:outsider", project_id=PROJECT)


# ---------------------------------------------------------------------------
# Clause 3 — scope but lower clearance returns REDACTED detail, refs intact
# ---------------------------------------------------------------------------


def test_scope_without_clearance_returns_redacted_detail_that_keeps_the_trace_refs():
    """THE clause that is easy to over-implement into a refusal.

    §17.24 requires redaction and requires the trace references to survive it. Denying outright
    would be simpler and would break the audit trail the rule explicitly protects -- a support
    engineer without NDA clearance still needs to correlate the incident.
    """
    scoped_but_uncleared = _membership(
        scopes=(VIEW_TECHNICAL_SCOPE,), clearance=(SensitivityLabel.INTERNAL,)
    )
    payload = _service(scoped_but_uncleared).expand(
        RECORD.error_id, actor_id="act:test", project_id=PROJECT
    )

    assert payload.technical is not None, "expansion was refused rather than redacted"
    assert payload.technical.source_path is None
    assert payload.technical.prompt_fragment is None
    assert "redacted" in payload.technical.message
    assert "Traceback" not in repr(payload)
    assert "acme-foundry" not in repr(payload)

    # The audit trail survives redaction. This is the half a refusal would destroy.
    assert payload.trace_id == "trc:1"
    assert payload.job_id == "job:1"
    assert payload.span_id == "spn:1"
    assert payload.technical.component == "FigureParser"


def test_scope_with_clearance_returns_the_detail_intact():
    """The positive control. Without it every assertion above could be a service that hides
    everything from everyone."""
    cleared = _membership(
        scopes=(VIEW_TECHNICAL_SCOPE,), clearance=(SensitivityLabel.RESTRICTED_NDA,)
    )
    payload = _service(cleared).expand(RECORD.error_id, actor_id="act:test", project_id=PROJECT)
    assert payload.technical is not None
    assert payload.technical.source_path == SECRET_DETAIL.source_path
    assert payload.technical.prompt_fragment == SECRET_DETAIL.prompt_fragment


def test_an_empty_clearance_set_sees_nothing_classified():
    """Fail-closed, which is §17.15's rule applied to the read side."""
    scoped_no_clearance = _membership(scopes=(VIEW_TECHNICAL_SCOPE,), clearance=())
    payload = _service(scoped_no_clearance).expand(
        RECORD.error_id, actor_id="act:test", project_id=PROJECT
    )
    assert payload.technical is not None
    assert payload.technical.source_path is None


# ---------------------------------------------------------------------------
# Clause 4 — cross-project is not-found, not permission-denied
# ---------------------------------------------------------------------------


def test_a_cross_project_lookup_is_indistinguishable_from_a_missing_one():
    """THE UX-003 probe. §17.24: an error_id from another project returns not-found, never a
    permission-denied that confirms existence.

    Compared rather than merely caught. Two refusals that differ in type, message or any
    attribute rebuild the oracle: an attacker enumerating ids learns which exist from the
    difference, and which projects are active from that.
    """
    service = _service(_membership(scopes=(VIEW_TECHNICAL_SCOPE,)))

    with pytest.raises(ErrorNotFound) as real_elsewhere:
        service.default_payload(OTHER_RECORD.error_id, actor_id="act:test", project_id=PROJECT)
    with pytest.raises(ErrorNotFound) as never_issued:
        service.default_payload("ERR-20260921-4242", actor_id="act:test", project_id=PROJECT)

    assert type(real_elsewhere.value) is type(never_issued.value)
    # The only difference permitted is the id the caller themselves supplied.
    assert real_elsewhere.value.args[0] == OTHER_RECORD.error_id
    assert never_issued.value.args[0] == "ERR-20260921-4242"
    for forbidden in ("permission", "denied", "forbidden", "access", OTHER_PROJECT):
        assert forbidden not in str(real_elsewhere.value).lower()


def test_expansion_of_another_projects_error_is_also_not_found():
    """The oracle must not reappear on the expansion path."""
    service = _service(_membership(scopes=(VIEW_TECHNICAL_SCOPE,)))
    with pytest.raises(ErrorNotFound):
        service.expand(OTHER_RECORD.error_id, actor_id="act:test", project_id=PROJECT)


def test_membership_is_checked_before_the_error_is_looked_up():
    """Ordering, so a real id in another project and a nonexistent one do the same work.

    A lookup that ran first would make the two paths differ in observable effort, which is a
    weaker version of the same oracle. Asserted by instrumenting the loader.
    """
    looked_up: list[str] = []

    service = DiagnosticsService(
        catalog=default_catalog(),
        load_error=lambda key: (looked_up.append(key), None)[1],
        load_detail=lambda _ref: None,
        membership_of=lambda _actor, _project: None,
        actor_of=ACTORS.get,
    )
    with pytest.raises(ErrorNotFound):
        service.default_payload("ERR-1", actor_id="act:outsider", project_id=PROJECT)
    assert looked_up == [], "the error store was queried before membership was established"


# ---------------------------------------------------------------------------
# Clause 5 (SEC-002) — Actor resolution is a dependency, not an option
#
# §17.24's scoping clause says "scoped by project membership", and the previous implementation
# read that literally: a membership ROW existing was the whole check. SEC-002 is the rule that
# says what membership means -- `Actor.active` AND `ProjectMembership.active`, both, because
# disabling an account is the global action and revoking a membership is the per-project one.
#
# The seam was the CONSTRUCTOR. `actor_of` defaulted to None and `_admitted` then fell back to
# `membership is not None`. So the weak rule was not dead code reachable only by mistake -- it
# was reachable from the supported public API, and every fixture that omitted the resolver was
# testing a service that no deployment used.
# ---------------------------------------------------------------------------


def test_the_service_cannot_be_constructed_without_actor_resolution():
    """Probe 1. The membership-only mode must not be *constructible*, not merely unused.

    Checked two ways, because they fail differently. The signature check is the structural claim
    -- a future edit that restores `actor_of: ... | None = None` fails here even if every
    behavioural probe below still passes, because they would all pass by supplying a resolver.
    The TypeError is the claim that the structural fact is actually enforced at runtime.
    """
    parameter = inspect.signature(DiagnosticsService.__init__).parameters["actor_of"]
    assert parameter.default is inspect.Parameter.empty, (
        "actor_of has a default again; an optional identity check is not a check -- the caller "
        "who omits it gets a pass rather than an error (SEC-002)"
    )
    # The resolver itself must not be optional. `Callable[[str], Actor | None]` is correct -- an
    # actor id that resolves to nothing is a refusal, decided by `can_access_project`. What is
    # forbidden is `... | None` around the whole callable, which is the no-resolver mode.
    hint = typing.get_type_hints(DiagnosticsService.__init__)["actor_of"]
    assert type(None) not in typing.get_args(hint), (
        f"actor_of is typed {hint!r}, which still admits a service with no Actor resolution"
    )

    with pytest.raises(TypeError, match="actor_of"):
        DiagnosticsService(  # type: ignore[call-arg]
            catalog=default_catalog(),
            load_error=lambda _key: None,
            load_detail=lambda _ref: None,
            membership_of=lambda _actor, _project: None,
        )


def test_an_unknown_actor_is_indistinguishable_from_a_missing_error():
    """Probe 2. No Actor row at all -- §14.4's "no governance without who"."""
    service = _service(_membership(actor_id="act:ghost", scopes=(VIEW_TECHNICAL_SCOPE,)))
    with pytest.raises(ErrorNotFound) as unknown_actor:
        service.default_payload(RECORD.error_id, actor_id="act:ghost", project_id=PROJECT)
    with pytest.raises(ErrorNotFound) as never_issued:
        service.default_payload("ERR-20260921-4242", actor_id="act:test", project_id=PROJECT)
    assert type(unknown_actor.value) is type(never_issued.value)
    for forbidden in ("permission", "denied", "forbidden", "inactive", "actor"):
        assert forbidden not in str(unknown_actor.value).lower()


def test_an_inactive_actor_with_an_active_membership_is_refused():
    """Probe 3. THE defect this repair closes, stated as a fixture.

    Under the old constructor this exact combination -- a centrally disabled account, an active
    membership row, a service built without `actor_of` -- resolved the error reference and, with
    the scope held, expanded it. Deactivating the account did nothing until someone walked every
    project and revoked each grant by hand.
    """
    disabled_member = _membership(
        actor_id="act:disabled",
        scopes=(VIEW_TECHNICAL_SCOPE,),
        clearance=(SensitivityLabel.RESTRICTED_NDA,),
    )
    assert DISABLED_ACTOR.active is False and disabled_member.active is True

    service = _service(disabled_member)
    with pytest.raises(ErrorNotFound):
        service.default_payload(RECORD.error_id, actor_id="act:disabled", project_id=PROJECT)
    with pytest.raises(ErrorNotFound):
        service.expand(RECORD.error_id, actor_id="act:disabled", project_id=PROJECT)


def test_an_active_actor_with_an_inactive_membership_is_refused():
    """Probe 4. The other half of SEC-002's conjunction -- revocation without deleting the row."""
    revoked = _membership(scopes=(VIEW_TECHNICAL_SCOPE,), active=False)
    service = _service(revoked)
    with pytest.raises(ErrorNotFound):
        service.default_payload(RECORD.error_id, actor_id="act:test", project_id=PROJECT)
    with pytest.raises(ErrorNotFound):
        service.expand(RECORD.error_id, actor_id="act:test", project_id=PROJECT)


def test_a_membership_of_another_project_grants_nothing_here():
    """Probe 5. Holding a project does not grant a neighbour (R-7 restated on this surface)."""
    elsewhere = _membership(project_id=OTHER_PROJECT, scopes=(VIEW_TECHNICAL_SCOPE,))
    service = _service(elsewhere)
    with pytest.raises(ErrorNotFound):
        service.default_payload(RECORD.error_id, actor_id="act:test", project_id=PROJECT)


def test_an_active_actor_with_an_active_membership_still_resolves():
    """Probe 6. The positive control.

    Without it every refusal above is satisfied by a service that refuses everyone, and the
    repair would look correct while having removed the feature.
    """
    payload = _service(_membership()).default_payload(
        RECORD.error_id, actor_id="act:test", project_id=PROJECT
    )
    assert payload.trace_id == "trc:1"
    assert payload.technical is None


def test_technical_expansion_reveals_no_second_refusal_path():
    """Probe 7. `--technical` must not distinguish the reasons a lookup failed.

    The withheld path returns a payload with `DIAGNOSTICS_SCOPE_REQUIRED`; the unauthorized path
    raises. If an unauthorized actor got the withheld payload instead of the raise, the presence
    of the error id would be confirmed by the very flag meant to be the stricter ask.
    """
    refusals = {}
    for actor_id, membership in (
        ("act:disabled", _membership(actor_id="act:disabled", scopes=(VIEW_TECHNICAL_SCOPE,))),
        ("act:test", _membership(scopes=(VIEW_TECHNICAL_SCOPE,), active=False)),
        ("act:ghost", _membership(actor_id="act:ghost", scopes=(VIEW_TECHNICAL_SCOPE,))),
        ("act:test", _membership(project_id=OTHER_PROJECT, scopes=(VIEW_TECHNICAL_SCOPE,))),
    ):
        service = _service(membership)
        with pytest.raises(ErrorNotFound) as raised:
            service.expand(RECORD.error_id, actor_id=actor_id, project_id=PROJECT)
        refusals[actor_id, membership.project_id, membership.active] = (
            type(raised.value),
            raised.value.args,
        )

    assert len(set(refusals.values())) == 1, refusals
    # And the SAME answer a never-issued id gets, so the flag confirms nothing.
    with pytest.raises(ErrorNotFound) as absent:
        _service(_membership(scopes=(VIEW_TECHNICAL_SCOPE,))).expand(
            RECORD.error_id.replace("0001", "4242"), actor_id="act:test", project_id=PROJECT
        )
    assert type(absent.value) is next(iter(refusals.values()))[0]


def test_no_error_or_detail_lookup_happens_before_project_authorization():
    """Probe 8. Ordering under the *new* predicate, for every refusal reason.

    The existing ordering probe covers "no membership". This one covers the three SEC-002
    refusals the old code could not even reach, because a store queried before the Actor check
    makes the disabled-account path do observably different work from the stranger path.
    """

    def instrumented(membership: ProjectMembership) -> tuple[DiagnosticsService, list, list]:
        """Loaders that always succeed, so the ONLY thing stopping them is the ACL."""
        errors_read: list[str] = []
        details_read: list[str] = []
        service = DiagnosticsService(
            catalog=default_catalog(),
            load_error=lambda key: (errors_read.append(key), RECORD)[1],
            load_detail=lambda ref: (details_read.append(ref), SECRET_DETAIL)[1],
            membership_of=lambda actor, project: (
                membership
                if membership.actor_id == actor and membership.project_id == project
                else None
            ),
            actor_of=ACTORS.get,
        )
        return service, errors_read, details_read

    for actor_id, member in (
        ("act:disabled", _membership(actor_id="act:disabled", scopes=(VIEW_TECHNICAL_SCOPE,))),
        ("act:test", _membership(scopes=(VIEW_TECHNICAL_SCOPE,), active=False)),
        ("act:ghost", _membership(actor_id="act:ghost", scopes=(VIEW_TECHNICAL_SCOPE,))),
    ):
        service, errors_read, details_read = instrumented(member)
        with pytest.raises(ErrorNotFound):
            service.expand(RECORD.error_id, actor_id=actor_id, project_id=PROJECT)
        assert errors_read == [], f"{actor_id}: the error store was read before authorization"
        assert details_read == [], f"{actor_id}: technical detail was read before authorization"
