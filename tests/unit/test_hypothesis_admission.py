"""EPI-001: §8's Hypothesis Admission Gate and the competing set it admits into.

    §8       只有通過 Hypothesis Admission Gate，補齊 mechanism、prediction、falsifier、
             assumptions、confounders 與 minimum test ...
    EPI-001  至少維護 2 個 competing hypotheses；單一看似合理原因不得直接被升級成 confirmed root
             cause。

Every refusal is asserted on its reason code AND on what it left behind: a refused set writes
nothing -- no set row, no certificate, no genesis event -- because a half-admitted competing set is
the single plausible cause EPI-001 forbids, made durable.
"""

from __future__ import annotations

import pytest

from lab_brain.core.hypothesis_admission import (
    AdmissionRefusal,
    HypothesisAdmissionRefused,
    check_competing,
    mechanism_key,
)
from lab_brain.core.models.belief_event import BeliefState
from tests.debate_fixtures import (
    ADMISSION_POLICY,
    PROJECT,
    T0,
    TRACE,
    build_world,
    make_certificate,
    make_set,
    state_of,
)

pytestmark = [pytest.mark.requirement("EPI-001"), pytest.mark.spec_test("T-EPI-001")]


def _basis(world) -> tuple[str, ...]:  # type: ignore[no-untyped-def]
    return tuple(sorted(world.attestations))[:2]


def _admit(world, hypothesis_set, certificates, *, basis=None):  # type: ignore[no-untyped-def]
    return world.admission.admit_set(
        hypothesis_set,
        certificates,
        basis=_basis(world) if basis is None else basis,
        policy=ADMISSION_POLICY,
        event_ids=[f"bre:{c.hypothesis_id.split(':', 1)[1]}" for c in certificates],
        occurred_at=T0,
        trace_id=TRACE,
    )


def _nothing_written(world, hypothesis_set, certificates) -> None:  # type: ignore[no-untyped-def]
    assert world.hypotheses.get_set(hypothesis_set.set_id) is None
    for c in certificates:
        assert world.hypotheses.get_certificate(hypothesis_set.project_id, c.hypothesis_id) is None
        assert world.events.history(PROJECT, c.hypothesis_id) == ()


def test_a_complete_competing_set_is_admitted_with_grounded_genesis_events():
    world = build_world()
    hs = make_set()
    certificates = [make_certificate(k, hs) for k in ("contact_discontinuity", "mesh_artifact")]
    admitted = _admit(world, hs, certificates)

    assert admitted.hypothesis_ids == tuple(c.hypothesis_id for c in certificates)
    for certificate, event in zip(certificates, admitted.events, strict=True):
        assert event.target_id == certificate.hypothesis_id
        assert event.from_state is None
        # The genesis event cites the evidence the certificate was reasoned from (§6.18).
        assert event.triggering_attestation_ids == _basis(world)
        assert state_of(world, certificate.hypothesis_id) is BeliefState.ACTIVE
    assert len(world.hypotheses.certificates_in_set(hs.set_id)) == 2


def test_a_single_certificate_is_not_a_competing_set_and_writes_nothing():
    world = build_world()
    hs = make_set()
    only = [make_certificate("contact_discontinuity", hs)]
    with pytest.raises(HypothesisAdmissionRefused) as refused:
        _admit(world, hs, only)
    assert refused.value.reason is AdmissionRefusal.NOT_COMPETING
    _nothing_written(world, hs, only)


def test_two_phrasings_of_one_mechanism_are_one_hypothesis_counted_twice():
    world = build_world()
    hs = make_set()
    certificates = [
        make_certificate("contact_discontinuity", hs),
        make_certificate("mesh_artifact", hs, mechanism="  ACCESS   Contact discontinuity "),
    ]
    assert mechanism_key(certificates[0]) == mechanism_key(certificates[1])
    with pytest.raises(HypothesisAdmissionRefused) as refused:
        _admit(world, hs, certificates)
    assert refused.value.reason is AdmissionRefusal.DUPLICATE_MECHANISM
    _nothing_written(world, hs, certificates)


@pytest.mark.parametrize(
    ("overrides", "missing"),
    [
        ({"assumptions": ()}, "no assumptions"),
        ({"confounders": ()}, "no confounders"),
        ({"minimal_test_ref": None}, "no minimal test"),
    ],
)
def test_an_incomplete_certificate_refuses_the_whole_set(overrides, missing):
    """All or nothing: the complete rival is not admitted alone when its partner is refused."""
    world = build_world()
    hs = make_set()
    certificates = [
        make_certificate("contact_discontinuity", hs),
        make_certificate("mesh_artifact", hs, **overrides),
    ]
    with pytest.raises(HypothesisAdmissionRefused) as refused:
        _admit(world, hs, certificates)
    assert refused.value.reason is AdmissionRefusal.INCOMPLETE_CERTIFICATE
    assert missing in refused.value.detail
    _nothing_written(world, hs, certificates)


def test_a_certificate_without_a_typed_prediction_is_an_idea():
    world = build_world()
    hs = make_set()
    certificates = [
        make_certificate("contact_discontinuity", hs),
        make_certificate("mesh_artifact", hs, predictions=False),
    ]
    with pytest.raises(HypothesisAdmissionRefused) as refused:
        _admit(world, hs, certificates)
    assert refused.value.reason is AdmissionRefusal.INCOMPLETE_CERTIFICATE
    assert "no typed Prediction" in refused.value.detail
    _nothing_written(world, hs, certificates)


def test_a_certificate_with_no_author_is_refused():
    world = build_world()
    hs = make_set()
    certificates = [
        make_certificate("contact_discontinuity", hs),
        make_certificate("mesh_artifact", hs, author=None),
    ]
    with pytest.raises(HypothesisAdmissionRefused) as refused:
        _admit(world, hs, certificates)
    assert "no author" in refused.value.detail


@pytest.mark.parametrize(
    ("override", "why"),
    [
        ({"expected_outcome": "RS_OSCILLATES"}, "not declared"),
        ({"outcome_space_version": "9.9.9"}, "not declared"),
    ],
)
def test_a_prediction_outside_its_declared_outcome_space_is_unbound(override, why):
    world = build_world()
    hs = make_set()
    certificates = [
        make_certificate("contact_discontinuity", hs),
        make_certificate("mesh_artifact", hs, **override),
    ]
    with pytest.raises(HypothesisAdmissionRefused) as refused:
        _admit(world, hs, certificates)
    assert refused.value.reason is AdmissionRefusal.PREDICTION_UNBOUND
    _nothing_written(world, hs, certificates)


def test_an_llm_certificate_whose_inference_was_never_recorded_is_text():
    world = build_world()
    hs = make_set()
    certificates = [
        make_certificate("contact_discontinuity", hs),
        make_certificate(
            "mesh_artifact", hs, author=None, inference_provenance_id="inf:never-recorded"
        ),
    ]
    with pytest.raises(HypothesisAdmissionRefused) as refused:
        _admit(world, hs, certificates)
    assert refused.value.reason is AdmissionRefusal.PROVENANCE_UNRESOLVED


def test_a_certificate_from_another_episode_is_not_a_member_of_the_set():
    world = build_world()
    hs = make_set()
    certificates = [
        make_certificate("contact_discontinuity", hs),
        make_certificate("mesh_artifact", hs, created_in_episode="epi:elsewhere"),
    ]
    with pytest.raises(HypothesisAdmissionRefused) as refused:
        _admit(world, hs, certificates)
    assert refused.value.reason is AdmissionRefusal.WRONG_SCOPE


def test_a_set_reasoned_from_no_evidence_is_ungrounded():
    world = build_world()
    hs = make_set()
    certificates = [make_certificate(k, hs) for k in ("contact_discontinuity", "mesh_artifact")]
    with pytest.raises(HypothesisAdmissionRefused) as refused:
        _admit(world, hs, certificates, basis=())
    assert refused.value.reason is AdmissionRefusal.UNGROUNDED
    _nothing_written(world, hs, certificates)


def test_a_basis_borrowed_from_another_project_does_not_resolve():
    """SEC-002 through the lookup: an attestation id that exists elsewhere is not evidence here."""
    world = build_world()
    hs = make_set(project_id="prj:other")
    certificates = [make_certificate(k, hs) for k in ("contact_discontinuity", "mesh_artifact")]
    with pytest.raises(HypothesisAdmissionRefused) as refused:
        _admit(world, hs, certificates)
    assert refused.value.reason is AdmissionRefusal.UNGROUNDED
    assert "does not resolve in project prj:other" in refused.value.detail


def test_an_unscoped_lookup_cannot_ground_a_set_in_another_projects_evidence():
    """The service checks the project itself rather than trusting the lookup to have scoped it."""
    from lab_brain.core.hypothesis_admission import HypothesisAdmissionService

    world = build_world()
    foreign = next(iter(world.attestations.values())).model_copy(update={"project_id": "prj:other"})
    service = HypothesisAdmissionService(
        store=world.hypotheses,
        append=world.events.append,
        outcome_space=world.registries.disagreement_metrics.outcome_space,
        provenance=world.provenance.get,
        attestations=lambda _project, _attestation: foreign,
    )
    hs = make_set()
    certificates = [make_certificate(k, hs) for k in ("contact_discontinuity", "mesh_artifact")]
    with pytest.raises(HypothesisAdmissionRefused) as refused:
        service.admit_set(
            hs,
            certificates,
            basis=(foreign.attestation_id,),
            policy=ADMISSION_POLICY,
            event_ids=["bre:a", "bre:b"],
            occurred_at=T0,
            trace_id=TRACE,
        )
    assert refused.value.reason is AdmissionRefusal.UNGROUNDED
    _nothing_written(world, hs, certificates)


def test_an_alternative_restating_an_admitted_mechanism_adds_no_rival():
    world = build_world()
    hs = make_set()
    _admit(world, hs, [make_certificate(k, hs) for k in ("contact_discontinuity", "mesh_artifact")])
    restated = make_certificate("dopant_compensation", hs, mechanism="Mesh convergence ARTIFACT")
    with pytest.raises(HypothesisAdmissionRefused) as refused:
        world.admission.admit_alternative(
            hs,
            restated,
            basis=_basis(world),
            policy=ADMISSION_POLICY,
            event_id="bre:restated",
            occurred_at=T0,
            trace_id=TRACE,
        )
    assert refused.value.reason is AdmissionRefusal.DUPLICATE_MECHANISM
    assert world.hypotheses.get_certificate(PROJECT, restated.hypothesis_id) is None


def test_a_genuine_alternative_joins_the_set_with_its_own_genesis():
    world = build_world()
    hs = make_set()
    _admit(world, hs, [make_certificate(k, hs) for k in ("contact_discontinuity", "mesh_artifact")])
    rival = make_certificate("dopant_compensation", hs)
    event = world.admission.admit_alternative(
        hs,
        rival,
        basis=_basis(world),
        policy=ADMISSION_POLICY,
        event_id="bre:rival",
        occurred_at=T0,
        trace_id=TRACE,
    )
    assert event.target_id == rival.hypothesis_id and event.from_state is None
    assert len(world.hypotheses.certificates_in_set(hs.set_id)) == 3


def test_check_competing_is_the_p6_rule_on_its_own():
    hs = make_set()
    with pytest.raises(HypothesisAdmissionRefused):
        check_competing([], hs)
    check_competing(
        [make_certificate(k, hs) for k in ("contact_discontinuity", "normalization_error")], hs
    )


def test_the_debate_admits_at_least_two_competing_certificates_before_verification():
    """The in-memory half of T-EPI-001; the PostgreSQL e2e runs the same flow durably."""
    world = build_world()
    outcome = world.debate.run(world.request())
    assert outcome.competing_before_verification >= 2
    for certificate in outcome.certificates:
        assert state_of(world, certificate.hypothesis_id) is BeliefState.ACTIVE


def test_a_single_cause_engine_is_refused_before_anything_is_admitted():
    """The adversarial reasoner: an engine that proposes one mechanism. §7.4 requires 2+."""
    from lab_brain.cognition.roles import RoleOutputRefused
    from tests.debate_fixtures import MockScientist, load_fixture

    fx = load_fixture()
    world = build_world(
        scientist=MockScientist(
            mechanisms=fx["mechanisms"],
            primary_terms=fx["primary_terms"],
            outcome_space=fx["outcome_space"],
            single_cause=True,
        )
    )
    with pytest.raises(RoleOutputRefused, match="at least 2 hypotheses"):
        world.debate.run(world.request())
    assert world.events.history(PROJECT, "hyp:anything") == ()


def test_the_in_memory_log_refuses_an_event_for_a_hypothesis_nobody_admitted():
    """R-12 parity (`011j`): the backend-free store refuses what the foreign key refuses."""
    from lab_brain.core.belief import EpistemicStateProjection, admit_hypothesis
    from lab_brain.core.repositories.belief_events import BeliefEventError

    world = build_world()
    basis = next(iter(world.attestations.values()))
    with pytest.raises(BeliefEventError, match="never admitted"):
        world.events.append(
            admit_hypothesis(
                event_id="bre:ghost",
                policy=ADMISSION_POLICY,
                project_id=PROJECT,
                hypothesis_id="hyp:ghost",
                prior=EpistemicStateProjection(
                    project_id=PROJECT,
                    target_id="hyp:ghost",
                    current_state=None,
                    last_event_id=None,
                ),
                occurred_at=T0,
                trace_id=TRACE,
                triggering_attestations=(basis,),
            )
        )
    assert world.events.history(PROJECT, "hyp:ghost") == ()
