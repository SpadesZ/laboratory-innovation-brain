"""Repair-2's three blockers, as permanent adversarial probes (EVI-010, SEC-002, §17.25).

All three were reproduced against the running system before anything was changed. Each was a
**fail-open**: the guard existed, was tested, and could be walked past.

    P0  verification keyed off `AdmissionRequest.evidence_unit_id`, so omitting an optional call
        parameter skipped the durable-link check, the occurrence check, the ACL check and
        segmentation re-derivation -- while the attestation named a forged unit on its own record.
    P1  the occurrence resolver was optional, so a gate constructed without one silently admitted
        evidence with no project scope established at all.
    P1  re-derivation ran whatever parser and segmenter it was constructed with, so a unit
        recording `some_other_segmenter 99.0.0` verified against the *current* segmenter and was
        admitted. It proved "some implementation produces this", not the recorded one.

The shape they share is worth naming: each guard was correct, and each had an input that turned it
off. That is why the probes below assert on the path being *taken* rather than on a verdict --
a verdict can be right for the wrong reason.
"""

from __future__ import annotations

import pytest

from lab_brain.core.models import (
    Attestation,
    EpistemicType,
    EvidenceUnit,
    EvidenceUnitType,
    ExtractionProvenance,
    SegmenterProvenance,
    SourceLocator,
)
from lab_brain.ingestion.admission_gate import (
    AdmissionRefusal,
    AdmissionRequest,
    EvidenceAdmissionGate,
    RefusalReason,
)
from lab_brain.ingestion.reverification import (
    Reverification,
    ReverificationFailure,
    SegmentationRegistry,
    SegmentationReverifier,
    default_registry,
)
from tests.conftest_fixtures import TOY_SCHEMA_REF
from tests.evidence_fixtures import (
    CONDITION_SENTENCE,
    RESULT_SENTENCE,
    fixture_artifact_id,
    fixture_bytes,
    segment_fixture,
)

PROJECT = "prj:test"
OTHER_PROJECT = "prj:other"

RECORDED = SegmenterProvenance(
    segmenter_id="evidence_aware_hierarchical",
    segmenter_version="1.0.0",
    parser_id="local_markdown",
    parser_version="1.0.0",
)


def _genuine() -> dict[str, EvidenceUnit]:
    return {unit.evidence_unit_id: unit for unit in segment_fixture().units}


def _bound_unit() -> EvidenceUnit:
    """A real unit that declares a bound condition -- the one a severed forgery imitates."""
    return next(
        unit for unit in segment_fixture().units if CONDITION_SENTENCE in unit.interpretive_text
    )


def _severed_unit() -> EvidenceUnit:
    """Storage-valid, segmentation-severed.

    Built through the ordinary constructor, so it carries a real derived identity, a consistent
    content digest and a consistent witness. Every storage-checkable property holds; the condition
    that makes its number interpretable exists nowhere. Only re-derivation can tell.
    """
    return EvidenceUnit.build(
        artifact_id=fixture_artifact_id(),
        unit_type=EvidenceUnitType.PROSE,
        structural_path="3/prose:1/0",
        locator=SourceLocator(label="§3"),
        body=RESULT_SENTENCE,
        provenance=RECORDED,
    )


def _reverifier(registry: SegmentationRegistry | None = None) -> SegmentationReverifier:
    return SegmentationReverifier(
        lambda artifact_id: fixture_bytes() if artifact_id == fixture_artifact_id() else None,
        registry=registry,
    )


def _attestation(evidence_unit_id: str | None) -> Attestation:
    return Attestation(
        claim_id="clm:cj-falls",
        epistemic_type=EpistemicType.REPORTED,
        source_work_id="swk:the-report",
        locator="§3",
        conditions={},
        conditions_schema_version=TOY_SCHEMA_REF,
        project_id=PROJECT,
        extractor_version="1.0.0",
        extraction_provenance=ExtractionProvenance(
            extractor_id="local_markdown", extractor_version="1.0.0"
        ),
        evidence_unit_id=evidence_unit_id,
    )


def _gate(units: dict[str, EvidenceUnit], **overrides) -> EvidenceAdmissionGate:
    """A gate wired the way a deployment is, with one seam swappable per test.

    Every seam defaults to *working*, so a test that wants a specific refusal disables exactly one
    thing and the refusal names that thing. Defaulting them to absent would make every probe here
    pass on the first fail-closed check and prove nothing about the rest.
    """
    kwargs: dict[str, object] = {
        "load_artifact": lambda _: None,
        "load_evidence_unit": lambda key: units.get(key),
        "resegment": _reverifier(),
        "is_present_in": lambda _unit, project: project == PROJECT,
    }
    kwargs.update(overrides)
    return EvidenceAdmissionGate(**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# P0 — the durable reference is the trigger; the request field cannot suppress
# ---------------------------------------------------------------------------


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_a_forged_unit_is_refused_even_when_the_request_names_nothing():
    """THE P0 probe. Before Repair-2 this was ADMITTED.

    The attestation names a forged unit on its own durable record. The admission call leaves the
    optional assertion out. Every EVI-010 guard used to key off that parameter, so omitting it
    skipped all of them -- durable link, occurrence, ACL and re-derivation -- and a severed unit
    entered the evidence path.

    The refusal must be `SEGMENTATION_NOT_REPRODUCIBLE` specifically: that is the guard at the far
    end of the chain, so getting it proves the whole chain ran rather than that something early
    happened to object.
    """
    severed = _severed_unit()
    with pytest.raises(AdmissionRefusal) as caught:
        _gate({severed.evidence_unit_id: severed}).admit(
            AdmissionRequest(attestation=_attestation(severed.evidence_unit_id))
        )
    assert caught.value.reason is RefusalReason.SEGMENTATION_NOT_REPRODUCIBLE


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_a_genuine_unit_is_admitted_with_the_request_field_omitted():
    """The positive control the probe above needs.

    Same call shape -- durable reference present, request assertion omitted -- and it succeeds.
    Without this, a gate that refused every omitted-assertion admission would pass the probe
    above while breaking the ordinary path.
    """
    units = _genuine()
    target = _bound_unit().evidence_unit_id
    admitted = _gate(units).admit(AdmissionRequest(attestation=_attestation(target)))
    assert admitted.evidence_unit_id == target


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_every_verification_stage_runs_when_only_the_record_names_the_unit():
    """The chain, observed rather than inferred.

    Each seam is instrumented, and all three must be consulted for an admission whose request
    field is absent. Asserting only the verdict would pass on a gate that happened to refuse for
    one reason while skipping the other two.
    """
    units = _genuine()
    target = _bound_unit().evidence_unit_id
    seen: dict[str, object] = {}

    def watch_presence(unit_id: str, project_id: str) -> bool:
        seen["presence"] = (unit_id, project_id)
        return True

    def watch_read(artifact_id: str, project_id: str) -> bool:
        seen["read"] = (artifact_id, project_id)
        return True

    verifier = _reverifier()

    def watch_resegment(unit: EvidenceUnit) -> Reverification:
        seen["resegment"] = unit.evidence_unit_id
        return verifier(unit)

    _gate(
        units,
        is_present_in=watch_presence,
        can_read=watch_read,
        resegment=watch_resegment,
    ).admit(AdmissionRequest(attestation=_attestation(target)))

    assert seen["presence"] == (target, PROJECT), "the occurrence check did not run"
    assert seen["read"] == (units[target].artifact_id, PROJECT), "the ACL check did not run"
    assert seen["resegment"] == target, "segmentation re-derivation did not run"


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_a_request_naming_a_unit_the_record_does_not_is_refused():
    """The assertion may agree with the record; it may not substitute for it."""
    units = _genuine()
    with pytest.raises(AdmissionRefusal) as caught:
        _gate(units).admit(
            AdmissionRequest(
                attestation=_attestation(None),
                evidence_unit_id=_bound_unit().evidence_unit_id,
            )
        )
    assert caught.value.reason is RefusalReason.EVIDENCE_LINK_NOT_DURABLE


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_a_request_disagreeing_with_the_record_is_refused():
    """Two references, one record. If they differ, neither is authoritative."""
    units = _genuine()
    durable = _bound_unit().evidence_unit_id
    other = next(key for key in units if key != durable)
    with pytest.raises(AdmissionRefusal) as caught:
        _gate(units).admit(
            AdmissionRequest(attestation=_attestation(durable), evidence_unit_id=other)
        )
    assert caught.value.reason is RefusalReason.EVIDENCE_LINK_NOT_DURABLE


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_an_attestation_naming_no_unit_still_admits_normally():
    """§17.2's one-source rule is unchanged: an Attestation may witness a Run or a SourceWork.

    The trigger is the record naming a unit, not the record existing, so a citation with no
    evidence unit must not be dragged into a verification it has no subject for.
    """
    admitted = _gate({}).admit(AdmissionRequest(attestation=_attestation(None)))
    assert admitted.evidence_unit_id is None


# ---------------------------------------------------------------------------
# P1 — occurrence verification fails closed
# ---------------------------------------------------------------------------


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_admission_refuses_when_no_occurrence_resolver_is_configured():
    """THE P1 probe. `if resolver is not None` made project scope opt-in for the deployer.

    `v3.3-a18` requires admission scope to resolve through EvidenceUnitOccurrence. A gate that
    cannot resolve presence has not established scope, and an unverifiable scope is refused
    rather than assumed -- the same fail-closed reading `can_read_artifact` applies to an
    unresolved actor.
    """
    units = _genuine()
    with pytest.raises(AdmissionRefusal) as caught:
        _gate(units, is_present_in=None).admit(
            AdmissionRequest(attestation=_attestation(_bound_unit().evidence_unit_id))
        )
    assert caught.value.reason is RefusalReason.PROJECT_SCOPE_NOT_VERIFIABLE


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_presence_in_another_project_authorizes_nothing():
    """The unit exists globally and is present elsewhere; this project still gets nothing."""
    units = _genuine()
    target = _bound_unit().evidence_unit_id

    def present_only_in_other(unit_id: str, project_id: str) -> bool:
        return project_id == OTHER_PROJECT

    with pytest.raises(AdmissionRefusal) as caught:
        _gate(units, is_present_in=present_only_in_other).admit(
            AdmissionRequest(attestation=_attestation(target))
        )
    assert caught.value.reason is RefusalReason.CROSS_PROJECT_UNIT


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_a_confirmed_occurrence_in_the_attestations_project_proceeds():
    """The positive control: only a confirmed occurrence in *this* project continues."""
    units = _genuine()
    target = _bound_unit().evidence_unit_id
    asked: list[tuple[str, str]] = []

    def present(unit_id: str, project_id: str) -> bool:
        asked.append((unit_id, project_id))
        return project_id == PROJECT

    admitted = _gate(units, is_present_in=present).admit(
        AdmissionRequest(attestation=_attestation(target))
    )
    assert admitted.evidence_unit_id == target
    assert asked == [(target, PROJECT)], (
        "presence was not resolved for the attestation's own project"
    )


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_scope_is_resolved_by_unit_identity_not_by_a_project_on_the_unit():
    """ADR-0012 is not re-opened: the unit carries no project to consult."""
    assert "project_id" not in EvidenceUnit.model_fields


# ---------------------------------------------------------------------------
# P1 — re-verification is bound to the RECORDED implementation
# ---------------------------------------------------------------------------


def _unit_recording(provenance: SegmenterProvenance) -> EvidenceUnit:
    """A byte-identical copy of a genuine unit, recording different provenance.

    The witness is recomputed consistently by the constructor, so every storage-checkable
    property still holds -- which is exactly the case that used to slip through: the *current*
    segmenter produces this body, so a verifier that ran the current segmenter said yes.
    """
    genuine = _bound_unit()
    return EvidenceUnit.build(
        artifact_id=genuine.artifact_id,
        unit_type=genuine.unit_type,
        structural_path=genuine.structural_path,
        locator=genuine.locator,
        body=genuine.body,
        provenance=provenance,
        bound_condition_texts=genuine.bound_condition_texts,
    )


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_an_unregistered_segmenter_version_is_refused_even_though_the_body_reproduces():
    """THE P1 probe, and the subtle one.

    The body is byte-identical to a genuine unit, so the *current* segmenter reproduces it
    exactly. Before Repair-2 that was enough. It must not be: §17.25 requires the **recorded**
    provenance to be reproducible, and a unit claiming a segmenter this build does not have is a
    unit whose provenance nobody can check.
    """
    unit = _unit_recording(
        SegmenterProvenance(
            segmenter_id="some_other_segmenter",
            segmenter_version="99.0.0",
            parser_id="local_markdown",
            parser_version="1.0.0",
        )
    )
    with pytest.raises(AdmissionRefusal) as caught:
        _gate({unit.evidence_unit_id: unit}).admit(
            AdmissionRequest(attestation=_attestation(unit.evidence_unit_id))
        )
    assert caught.value.reason is RefusalReason.RECORDED_IMPLEMENTATION_UNAVAILABLE


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_an_unregistered_parser_version_is_refused():
    """Both halves of the recorded provenance are resolved, not just the segmenter."""
    unit = _unit_recording(
        SegmenterProvenance(
            segmenter_id="evidence_aware_hierarchical",
            segmenter_version="1.0.0",
            parser_id="local_markdown",
            parser_version="0.0.1-retired",
        )
    )
    with pytest.raises(AdmissionRefusal) as caught:
        _gate({unit.evidence_unit_id: unit}).admit(
            AdmissionRequest(attestation=_attestation(unit.evidence_unit_id))
        )
    assert caught.value.reason is RefusalReason.RECORDED_IMPLEMENTATION_UNAVAILABLE


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_a_supported_recorded_version_reproduces_successfully():
    """The positive control. Without it the two probes above pass on a verifier that refuses all."""
    units = _genuine()
    target = _bound_unit().evidence_unit_id
    assert (
        _gate(units).admit(AdmissionRequest(attestation=_attestation(target))).evidence_unit_id
        == target
    )


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_the_reverifier_resolves_the_unit_not_the_current_default():
    """Asserted against the registry directly, so the binding is visible rather than inferred.

    A registry with the recorded segmenter *removed* must fail for a unit that records it, even
    though the production default would have reproduced that unit perfectly.
    """
    empty = SegmentationRegistry()
    outcome = _reverifier(registry=empty)(_bound_unit())
    assert outcome.units is None
    assert outcome.failure is ReverificationFailure.IMPLEMENTATION_NOT_REGISTERED
    assert "not registered in this build" in outcome.detail

    # And the default registry does resolve it -- so the failure above is the registry's doing,
    # not a broken unit.
    assert _reverifier(registry=default_registry())(_bound_unit()).units is not None


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_a_historical_unit_is_verified_under_its_own_recorded_version():
    """Registering a second version must not change how version 1 units are verified.

    Modelled with a deliberately wrong "v2": it returns nothing. A unit recording v1 still
    verifies, because v1 is what is resolved for it -- and a unit recording v2 fails, proving the
    lookup is by recorded identity rather than by recency.
    """
    genuine = _bound_unit()
    registry = default_registry()
    registry.register_segmenter(
        "evidence_aware_hierarchical",
        "2.0.0",
        # A v2 that segments nothing. If re-derivation reached for "the newest", a v1 unit would
        # stop verifying the moment this line was added.
        lambda _token_limit: _NullSegmenter(),  # type: ignore[arg-type,return-value]
    )
    verifier = _reverifier(registry=registry)

    assert verifier(genuine).units, "a v1 unit stopped verifying when v2 was registered"

    v2_unit = _unit_recording(
        SegmenterProvenance(
            segmenter_id="evidence_aware_hierarchical",
            segmenter_version="2.0.0",
            parser_id="local_markdown",
            parser_version="1.0.0",
        )
    )
    assert verifier(v2_unit).units == (), "the v2 unit was not verified under v2"


class _NullSegmenter:
    """A stand-in second version that produces no units. See the test above."""

    def segment(self, _document: object) -> _NullResult:
        return _NullResult()


class _NullResult:
    units: tuple[EvidenceUnit, ...] = ()


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_unavailable_bytes_and_unavailable_implementation_are_distinguished():
    """Different operational problems, different remedies, so different reasons.

    An unreachable artifact store is fixed by fixing the store. A retired segmenter version is
    not, and reporting them identically would send an operator to the wrong place.
    """
    units = _genuine()
    target = _bound_unit().evidence_unit_id
    starved = SegmentationReverifier(lambda _artifact_id: None)

    with pytest.raises(AdmissionRefusal) as caught:
        _gate(units, resegment=starved).admit(AdmissionRequest(attestation=_attestation(target)))
    assert caught.value.reason is RefusalReason.SEGMENTATION_NOT_VERIFIABLE
    assert "ARTIFACT_BYTES_UNAVAILABLE" in caught.value.detail


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_the_recorded_token_limit_is_restored_when_re_deriving():
    """The recorded token limit travels with the segmenter version, or subdivisions vanish.

    Found by the mutation battery: replacing ``factory(provenance.token_limit)`` with
    ``factory(None)`` survived every test, because nothing re-verified a unit that had been
    segmented under a non-default limit. So the restoration was untested, which is the same
    defect class as the three blockers -- a correct guard nothing exercised.

    A unit subdivided under a 25-token limit does not exist at the default 320: rule 3(a)'s
    fallback never fires, so the sub-units are not among what segmentation produces and a
    legitimate historical unit would be refused. Restoring the limit is what keeps
    re-verification honest about *that* run rather than about today's configuration.
    """
    subdivided = [unit for unit in segment_fixture(token_limit=25).units if unit.is_subdivision]
    assert subdivided, "the fixture produced no subdivisions at a 25-token limit"

    unit = subdivided[0]
    assert unit.provenance.token_limit == 25

    outcome = _reverifier()(unit)
    assert outcome.units is not None, f"re-derivation could not run: {outcome.detail}"
    assert any(produced.evidence_unit_id == unit.evidence_unit_id for produced in outcome.units), (
        "a unit segmented under a 25-token limit was not reproduced; the recorded limit was not "
        "restored, so re-derivation ran under the current default instead"
    )


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_a_subdivided_unit_is_admitted_end_to_end_under_its_recorded_limit():
    """The same property at the admission boundary, not just at the reverifier."""
    result = segment_fixture(token_limit=25)
    units = {unit.evidence_unit_id: unit for unit in result.units}
    subdivided = next(unit for unit in result.units if unit.is_subdivision)

    admitted = _gate(units).admit(
        AdmissionRequest(attestation=_attestation(subdivided.evidence_unit_id))
    )
    assert admitted.evidence_unit_id == subdivided.evidence_unit_id
