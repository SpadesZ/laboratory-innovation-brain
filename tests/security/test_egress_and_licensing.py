"""T-SEC-001 / T-SEC-004 — egress refusal and licence gating (§14.1, §14.2, §14.3, §14.5).

    T-SEC-001  RESTRICTED_NDA context 嘗試送 external connector 時被 policy engine 阻擋並留下
               audit event
    T-SEC-004  UNKNOWN/COPYLEFT code fixture is blocked from generation context unless explicit
               policy fixture allows it

THE ASSERTION THAT MATTERS MOST IS THE ONE ABOUT THE AUDIT TRAIL. A refusal that logs what it
blocked has copied restricted material into a log -- usually with weaker access control than the
store it came from -- so the refusal has become the leak. Several tests below check the *absence*
of the payload in the decision and in the log, which is a stranger thing to assert than a refusal
and the thing that actually goes wrong.
"""

from __future__ import annotations

import pytest

from lab_brain.core.models.enums import LicenseClass, SensitivityLabel
from lab_brain.security.egress import (
    CodeArtifact,
    CodePolicy,
    EgressAuditLog,
    EgressGate,
    EgressPolicy,
    EgressRequest,
    PrivacyMode,
    evaluate_and_audit,
    may_enter_generation_context,
    sanitised_providers,
)

PROJECT = "prj:test"
ACTOR = "act:test"

#: Recognisable, so a leak into a decision or a log is unmistakable in an assertion.
NDA_PAYLOAD = "ACME 220nm PDK: sidewall angle 83.4 deg, Cj 0.515 pF/mm at -2V, NDA-2026-117"

sec001 = [pytest.mark.requirement("SEC-001"), pytest.mark.spec_test("T-SEC-001")]
sec004 = [pytest.mark.requirement("SEC-004"), pytest.mark.spec_test("T-SEC-004")]


def _policy(**overrides) -> EgressPolicy:
    payload = {
        "policy_id": "egp:test",
        "version": "1.0.0",
        "project_id": PROJECT,
        "mode": PrivacyMode.RESEARCH,
        "declared_by_actor_id": "act:pi",
        "permitted_labels": frozenset({SensitivityLabel.PUBLIC}),
        "approved_providers": frozenset({"src:literature"}),
    }
    payload.update(overrides)
    return EgressPolicy(**payload)  # type: ignore[arg-type]


def _gate(
    policy: EgressPolicy | None = None,
    *,
    clearance: frozenset[SensitivityLabel] = frozenset({SensitivityLabel.PUBLIC}),
) -> EgressGate:
    return EgressGate(
        policy_for=lambda _project: policy,
        clearance_of=lambda _actor, _project: clearance,
    )


def _request(
    sensitivity: SensitivityLabel = SensitivityLabel.RESTRICTED_NDA,
    *,
    provider: str = "src:literature",
    content: str = NDA_PAYLOAD,
) -> EgressRequest:
    return EgressRequest(
        project_id=PROJECT,
        actor_id=ACTOR,
        provider_id=provider,
        sensitivity=sensitivity,
        content=content,
    )


# ---------------------------------------------------------------------------
# SEC-001
# ---------------------------------------------------------------------------


@pytest.mark.requirement("SEC-001")
@pytest.mark.spec_test("T-SEC-001")
def test_restricted_nda_is_blocked_and_leaves_an_audit_event():
    """THE T-SEC-001 fixture, both halves in one assertion set."""
    log = EgressAuditLog()
    decision = evaluate_and_audit(_gate(_policy()), _request(), log)

    assert not decision.permitted
    assert decision.reason_code == "EGRESS_BLOCKED_BY_POLICY"
    assert len(log.blocked()) == 1, "the refusal left no audit evidence"
    assert log.actors == [ACTOR], "the audit event does not say who tried"


@pytest.mark.requirement("SEC-001")
@pytest.mark.spec_test("T-SEC-001")
def test_the_refusal_never_records_the_restricted_payload():
    """THE assertion that is easy to invert.

    An audit trail quoting the NDA text it stopped from leaving has written that text somewhere
    with weaker access control than the store it came from. Checked against the whole serialised
    decision and the whole serialised log, not against a field somebody remembered.
    """
    log = EgressAuditLog()
    decision = evaluate_and_audit(_gate(_policy()), _request(), log)

    for surface in (repr(decision), repr(log)):
        assert "ACME" not in surface
        assert "83.4" not in surface
        assert "NDA-2026-117" not in surface
        assert "0.515" not in surface

    # A digest instead, so an incident review can correlate without reading the content.
    assert decision.content_digest.startswith("sha256:")
    assert len(decision.content_digest) == len("sha256:") + 64


@pytest.mark.requirement("SEC-001")
@pytest.mark.spec_test("T-SEC-001")
def test_no_project_policy_can_permit_restricted_nda():
    """§14.1 gives RESTRICTED_NDA no policy exception, so the check runs before the policy loads.

    A policy that could lift it would make the strongest label the weakest guarantee -- the one
    whose protection depends on nobody having edited a configuration row.
    """
    permissive = _policy(
        permitted_labels=frozenset(SensitivityLabel),
        approved_providers=frozenset({"src:literature"}),
    )
    decision = _gate(permissive, clearance=frozenset(SensitivityLabel)).evaluate(_request())
    assert not decision.permitted
    assert "under any project policy" in decision.detail


@pytest.mark.requirement("SEC-001")
@pytest.mark.spec_test("T-SEC-001")
def test_private_mode_allows_no_egress_at_all():
    """§14.2: Private Mode is "No egress". Even PUBLIC material, even an approved provider."""
    decision = _gate(_policy(mode=PrivacyMode.PRIVATE)).evaluate(
        _request(SensitivityLabel.PUBLIC, content="a published abstract")
    )
    assert not decision.permitted
    assert "Private Mode" in decision.detail


@pytest.mark.requirement("SEC-001")
@pytest.mark.spec_test("T-SEC-001")
def test_absence_of_a_policy_is_not_permission():
    """The fail-closed default. §14.3's gates are approvals, and an unapproved action is refused."""
    decision = _gate(None).evaluate(_request(SensitivityLabel.PUBLIC, content="public"))
    assert not decision.permitted
    assert "no declared egress policy" in decision.detail


@pytest.mark.requirement("SEC-001")
@pytest.mark.spec_test("T-SEC-001")
def test_policy_and_clearance_are_both_required():
    """§14.3 requires policy AND Actor clearance.

    A project may approve a class of material without every member being allowed to send it, so
    a policy permitting CONFIDENTIAL_LAB does not let an uncleared actor egress it.
    """
    policy = _policy(
        permitted_labels=frozenset({SensitivityLabel.PUBLIC, SensitivityLabel.CONFIDENTIAL_LAB})
    )
    request = _request(SensitivityLabel.CONFIDENTIAL_LAB, content="unpublished topology")

    uncleared = _gate(policy, clearance=frozenset({SensitivityLabel.PUBLIC})).evaluate(request)
    assert not uncleared.permitted
    assert uncleared.reason_code == "EGRESS_CLEARANCE_MISSING"

    cleared = _gate(
        policy, clearance=frozenset({SensitivityLabel.PUBLIC, SensitivityLabel.CONFIDENTIAL_LAB})
    ).evaluate(request)
    assert cleared.permitted, "the positive control failed; the gate may be refusing everything"


@pytest.mark.requirement("SEC-001")
@pytest.mark.spec_test("T-SEC-001")
def test_an_unapproved_provider_is_refused_even_for_public_material():
    decision = _gate(_policy()).evaluate(
        _request(SensitivityLabel.PUBLIC, provider="src:random-web", content="public")
    )
    assert not decision.permitted
    assert "not an approved provider" in decision.detail


@pytest.mark.requirement("SEC-001")
@pytest.mark.spec_test("T-SEC-001")
def test_the_decision_records_which_policy_version_decided():
    """An approval nobody can reconstruct is not auditable. Same reason EVI-008 versions its."""
    decision = _gate(_policy()).evaluate(
        _request(SensitivityLabel.PUBLIC, content="public abstract")
    )
    assert decision.permitted
    assert decision.policy_id == "egp:test"
    assert decision.policy_version == "1.0.0"


@pytest.mark.requirement("SEC-001")
@pytest.mark.spec_test("T-SEC-001")
def test_a_private_project_reaches_no_providers_at_all():
    """The router-facing view of the same rule, so a caller cannot enumerate its way around it."""
    available = ["src:literature", "src:patents"]
    assert sanitised_providers(_policy(mode=PrivacyMode.PRIVATE), available) == ()
    assert sanitised_providers(None, available) == ()
    assert sanitised_providers(_policy(), available) == ("src:literature",)


@pytest.mark.requirement("SEC-001")
@pytest.mark.spec_test("T-SEC-001")
def test_an_allowed_egress_is_not_audited_as_a_block():
    """The log is evidence of refusals. Recording permitted traffic would bury them."""
    log = EgressAuditLog()
    evaluate_and_audit(_gate(_policy()), _request(SensitivityLabel.PUBLIC, content="public"), log)
    assert log.blocked() == ()


# ---------------------------------------------------------------------------
# SEC-004
# ---------------------------------------------------------------------------


def _code(
    license_class: LicenseClass, *, provenance: str | None = "src:github/acme@v1"
) -> CodeArtifact:
    return CodeArtifact(
        artifact_id="art:snippet",
        license_class=license_class,
        license_identifier=None,
        provenance=provenance,
    )


@pytest.mark.requirement("SEC-004")
@pytest.mark.spec_test("T-SEC-004")
@pytest.mark.parametrize("blocked", [LicenseClass.UNKNOWN, LicenseClass.COPYLEFT])
def test_unknown_and_copyleft_are_blocked_from_generation_context(blocked):
    """§14.5 names both. The default policy permits PERMISSIVE only."""
    admission = may_enter_generation_context(_code(blocked), None)
    assert not admission.permitted
    assert admission.license_class is blocked


@pytest.mark.requirement("SEC-004")
@pytest.mark.spec_test("T-SEC-004")
def test_unknown_does_not_silently_become_permissive():
    """THE SEC-004 probe, and the reading it refuses.

    "We could not identify a licence, so there probably isn't one to worry about" is exactly
    inverted: an unidentified licence is more likely to be restrictive than less, and generated
    code carrying unidentified copyleft is a legal problem discovered at publication.

    The refusal has its OWN code, distinct from a known-but-forbidden class, because the remedy
    differs -- one needs the licence identified, the other needs a policy decision.
    """
    unknown = may_enter_generation_context(_code(LicenseClass.UNKNOWN), None)
    copyleft = may_enter_generation_context(_code(LicenseClass.COPYLEFT), None)
    assert unknown.reason_code == "LICENSE_UNKNOWN"
    assert copyleft.reason_code == "LICENSE_BLOCKS_CODE_GENERATION"
    assert "not an absent one" in unknown.detail


@pytest.mark.requirement("SEC-004")
@pytest.mark.spec_test("T-SEC-004")
def test_permissive_code_with_provenance_is_admitted():
    """The positive control."""
    admission = may_enter_generation_context(_code(LicenseClass.PERMISSIVE), None)
    assert admission.permitted
    assert admission.reason_code == "LICENSE_PERMITTED"


@pytest.mark.requirement("SEC-004")
@pytest.mark.spec_test("T-SEC-004")
def test_an_explicit_policy_may_permit_unknown_and_records_who_declared_it():
    """§14.5's escape hatch: 除非 project policy 明確允許.

    "Explicitly permits" means somebody said so, so the policy carries an author. A permission
    with no author is one nobody granted, and the service account acting on it would look like
    the source of the decision.
    """
    permissive_policy = CodePolicy(
        policy_id="cdp:test",
        version="1.0.0",
        project_id=PROJECT,
        declared_by_actor_id="act:pi",
        permitted=frozenset({LicenseClass.PERMISSIVE, LicenseClass.UNKNOWN}),
    )
    admission = may_enter_generation_context(_code(LicenseClass.UNKNOWN), permissive_policy)
    assert admission.permitted
    assert permissive_policy.declared_by_actor_id == "act:pi"

    # The escape hatch is narrow: permitting UNKNOWN does not also permit COPYLEFT.
    still_blocked = may_enter_generation_context(_code(LicenseClass.COPYLEFT), permissive_policy)
    assert not still_blocked.permitted


@pytest.mark.requirement("SEC-004")
@pytest.mark.spec_test("T-SEC-004")
def test_a_licence_class_with_no_provenance_is_refused():
    """SEC-004 requires license_class AND provenance.

    A class nobody can trace cannot be re-checked when the policy changes -- and "this was marked
    permissive at some point by someone" is not a record anyone can act on later.
    """
    admission = may_enter_generation_context(_code(LicenseClass.PERMISSIVE, provenance=None), None)
    assert not admission.permitted
    assert admission.reason_code == "LICENSE_UNKNOWN"
    assert "no provenance" in admission.detail


@pytest.mark.requirement("SEC-004")
@pytest.mark.spec_test("T-SEC-004")
def test_proprietary_code_is_blocked_by_default():
    """Not named by §14.5's sentence, and permitting it by default would be stranger still."""
    assert not may_enter_generation_context(_code(LicenseClass.PROPRIETARY), None).permitted
