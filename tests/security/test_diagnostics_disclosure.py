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

import pytest

from lab_brain.core.models.access import ProjectMembership
from lab_brain.core.models.enums import SensitivityLabel
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
    *, scopes: tuple[str, ...] = (), clearance: tuple[SensitivityLabel, ...] = ()
) -> ProjectMembership:
    return ProjectMembership(
        actor_id="act:test",
        project_id=PROJECT,
        role="RESEARCHER",
        sensitivity_clearance=clearance,
        approval_scopes=scopes,
    )


def _service(membership: ProjectMembership | None) -> DiagnosticsService:
    errors = {RECORD.error_id: RECORD, OTHER_RECORD.error_id: OTHER_RECORD}
    return DiagnosticsService(
        catalog=default_catalog(),
        load_error=lambda key: errors.get(key),
        load_detail=lambda ref: SECRET_DETAIL if ref == "det:1" else None,
        membership_of=lambda actor, project: (
            membership if project == PROJECT and membership is not None else None
        ),
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
    )
    with pytest.raises(ErrorNotFound):
        service.default_payload("ERR-1", actor_id="act:outsider", project_id=PROJECT)
    assert looked_up == [], "the error store was queried before membership was established"
