"""The four M1-P1 audit findings, as permanent attack probes.

Each finding was reproduced against the running system before it was fixed. These are those
reproductions, kept so the fix cannot silently regress -- the same reasoning
``tests/spec/test_conformance_guards.py`` gives about itself: "the assertion passed" and "the
assertion can fail" are different claims.

    P0   EVI-003 trusted a caller-supplied flag, so the guard was opt-in for the one party who
         would never opt in.
    P1   §17.25's Attestation->EvidenceUnit reference lived only in the admission call, so a
         reloaded attestation could not name its evidence.
    P1   `EvidenceUnit` carried a project while its identity was project-independent, so the same
         document in two projects collided (schema half is in the PostgreSQL suite).
    P1   §6.22 rule 1 fired only when a unit declared its own bindings, so a raw writer skipped it
         by declaring nothing.

The postgres halves live in ``tests/integration/test_evidence_units_postgres.py``; what is here is
everything establishable without a database.
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
    compute_content_hash,
    segmentation_witness_for,
)
from lab_brain.ingestion.admission_gate import (
    AdmissionRefusal,
    AdmissionRequest,
    EvidenceAdmissionGate,
    RefusalReason,
)
from lab_brain.ingestion.reverification import SegmentationReverifier
from tests.conftest_fixtures import TOY_SCHEMA_REF, make_artifact
from tests.evidence_fixtures import (
    CONDITION_SENTENCE,
    RESULT_SENTENCE,
    fixture_artifact_id,
    fixture_bytes,
    segment_fixture,
)

PROJECT = "prj:test"

# NO module-level pytestmark here, unlike the sibling EVI-010 files. This module covers two
# requirements -- EVI-003's trust boundary and EVI-010's evidence contract -- and a module-level
# pair would combine with each test's own pair to claim (EVI-010, T-EVI-003), which §26 does not
# map. Every test below carries its own explicit pair instead.


def _units() -> dict[str, EvidenceUnit]:
    return {unit.evidence_unit_id: unit for unit in segment_fixture().units}


def _reverifier() -> SegmentationReverifier:
    return SegmentationReverifier(
        lambda artifact_id: fixture_bytes() if artifact_id == fixture_artifact_id() else None
    )


def _gate(units: dict[str, EvidenceUnit], **overrides) -> EvidenceAdmissionGate:
    kwargs: dict[str, object] = {
        "load_artifact": lambda _: None,
        "load_evidence_unit": lambda key: units.get(key),
        "resegment": _reverifier(),
        "is_present_in": lambda _unit, project: project == PROJECT,
    }
    kwargs.update(overrides)
    return EvidenceAdmissionGate(**kwargs)  # type: ignore[arg-type]


def _attestation(**extra) -> Attestation:
    provenance_id = extra.pop("inference_provenance_id", None)
    return Attestation(
        claim_id="clm:cj-falls",
        locator="§3",
        conditions={},
        conditions_schema_version=TOY_SCHEMA_REF,
        project_id=PROJECT,
        extractor_version="1.0.0",
        extraction_provenance=ExtractionProvenance(
            extractor_id="local_markdown",
            extractor_version="1.0.0",
            inference_provenance_id=provenance_id,
        ),
        **extra,
    )


# ---------------------------------------------------------------------------
# P0 — EVI-003 may not depend on a caller-supplied flag
# ---------------------------------------------------------------------------


@pytest.mark.requirement("EVI-003")
@pytest.mark.spec_test("T-EVI-003")
@pytest.mark.parametrize(
    "epistemic_type",
    [EpistemicType.MEASURED, EpistemicType.SIMULATED, EpistemicType.OBSERVED],
)
@pytest.mark.parametrize("flag", [{"llm_derived": False}, {}], ids=["explicit-false", "omitted"])
def test_inference_provenance_alone_refuses_a_factual_type(epistemic_type, flag):
    """THE P0 probe. Before the repair, all six of these were ADMITTED.

    The record carries ``inference_provenance_id`` -- §17.14 makes that mandatory on every
    LLM-generated object, so its presence *is* the record saying a model produced this. The
    submitter says otherwise, or says nothing. Both must refuse, because a guard the submitter
    can opt out of is not a guard: the one party guaranteed never to volunteer "this came from a
    model" is the party laundering a model's output into the evidence path.
    """
    artifact = make_artifact(b"a paper", uri="file:///p.pdf")
    attestation = _attestation(
        epistemic_type=epistemic_type,
        source_artifact_id=artifact.artifact_id,
        inference_provenance_id="inf:gpt-summary-1",
    )
    gate = EvidenceAdmissionGate(
        load_artifact=lambda key: artifact if key == artifact.artifact_id else None,
        load_evidence_unit=lambda _: None,
    )
    with pytest.raises(AdmissionRefusal) as caught:
        gate.admit(AdmissionRequest(attestation=attestation, **flag))

    assert caught.value.reason in {
        RefusalReason.INFERENCE_FLAG_CONTRADICTS_PROVENANCE,
        RefusalReason.INFERENCE_TYPED_AS_FACT,
    }


@pytest.mark.requirement("EVI-003")
@pytest.mark.spec_test("T-EVI-003")
def test_an_explicit_denial_and_a_silence_are_told_apart():
    """The two refusals are different defects and are reported as such.

    An explicit ``False`` beside a provenance that says otherwise means a *producer* is lying;
    an omission usually means a caller forgot. Collapsing them would lose the distinction that
    tells an operator which system to go and look at.
    """
    artifact = make_artifact(b"a paper", uri="file:///p.pdf")
    gate = EvidenceAdmissionGate(
        load_artifact=lambda key: artifact if key == artifact.artifact_id else None,
        load_evidence_unit=lambda _: None,
    )

    def refuse(**flag):
        attestation = _attestation(
            epistemic_type=EpistemicType.MEASURED,
            source_artifact_id=artifact.artifact_id,
            inference_provenance_id="inf:gpt",
        )
        with pytest.raises(AdmissionRefusal) as caught:
            gate.admit(AdmissionRequest(attestation=attestation, **flag))
        return caught.value.reason

    assert refuse(llm_derived=False) is RefusalReason.INFERENCE_FLAG_CONTRADICTS_PROVENANCE
    assert refuse() is RefusalReason.INFERENCE_TYPED_AS_FACT


@pytest.mark.requirement("EVI-003")
@pytest.mark.spec_test("T-EVI-003")
def test_the_flag_may_widen_but_never_narrow():
    """A caller volunteering LLM origin for a silent record is believed; the reverse is not.

    Both halves asserted, because a rule that only ever refuses would also pass the probes above
    while making the flag useless.
    """
    artifact = make_artifact(b"a paper", uri="file:///p.pdf")
    gate = EvidenceAdmissionGate(
        load_artifact=lambda key: artifact if key == artifact.artifact_id else None,
        load_evidence_unit=lambda _: None,
    )

    # Widening: no provenance, caller says it is an inference -> refused as a factual type.
    with pytest.raises(AdmissionRefusal) as caught:
        gate.admit(
            AdmissionRequest(
                attestation=_attestation(
                    epistemic_type=EpistemicType.MEASURED,
                    source_artifact_id=artifact.artifact_id,
                ),
                llm_derived=True,
            )
        )
    assert caught.value.reason is RefusalReason.INFERENCE_TYPED_AS_FACT

    # And the positive control: an ordinary measurement, nobody claiming anything, is admitted.
    admitted = gate.admit(
        AdmissionRequest(
            attestation=_attestation(
                epistemic_type=EpistemicType.MEASURED,
                source_artifact_id=artifact.artifact_id,
            )
        )
    )
    assert admitted.epistemic_type is EpistemicType.MEASURED


# ---------------------------------------------------------------------------
# P1 — the evidence reference must be durable
# ---------------------------------------------------------------------------


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_an_attestation_that_does_not_record_its_evidence_unit_is_refused():
    """THE P1 probe. §17.25 required the reference; it existed only in the call.

    Persist that attestation, restart, reload it, and it cannot say which passage it read. The
    locator does not close the gap -- a document routinely has several units at one human-facing
    position, which is exactly why ``structural_path`` is part of evidence identity.
    """
    units = _units()
    target = next(iter(units))
    with pytest.raises(AdmissionRefusal) as caught:
        _gate(units).admit(
            AdmissionRequest(
                attestation=_attestation(
                    epistemic_type=EpistemicType.REPORTED, source_work_id="swk:report"
                ),
                evidence_unit_id=target,
            )
        )
    assert caught.value.reason is RefusalReason.EVIDENCE_LINK_NOT_DURABLE


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_a_record_naming_a_different_unit_than_the_admission_is_refused():
    """The durable reference and the submitted one must agree, or neither is authoritative."""
    units = _units()
    first, second = list(units)[:2]
    with pytest.raises(AdmissionRefusal) as caught:
        _gate(units).admit(
            AdmissionRequest(
                attestation=_attestation(
                    epistemic_type=EpistemicType.REPORTED,
                    source_work_id="swk:report",
                    evidence_unit_id=second,
                ),
                evidence_unit_id=first,
            )
        )
    assert caught.value.reason is RefusalReason.EVIDENCE_LINK_NOT_DURABLE


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_the_reference_survives_a_serialisation_round_trip():
    """Durability, at the level this file can establish it: the field is on the record.

    The database half -- persist, reload from PostgreSQL, recover the unit without the request --
    is ``test_an_attestation_recovers_its_evidence_unit_after_reload`` in the postgres suite.
    """
    units = _units()
    target = next(iter(units))
    attestation = _attestation(
        epistemic_type=EpistemicType.REPORTED,
        source_work_id="swk:report",
        evidence_unit_id=target,
    )
    reloaded = Attestation.model_validate_json(attestation.model_dump_json())
    assert reloaded.evidence_unit_id == target
    assert units[reloaded.evidence_unit_id].body


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_a_reference_that_is_not_an_evidence_identity_is_refused():
    """A representation id or a content digest here would resolve to nothing."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="not an evidence unit identity"):
        _attestation(
            epistemic_type=EpistemicType.REPORTED,
            source_work_id="swk:report",
            evidence_unit_id="rrp:some-representation",
        )


# ---------------------------------------------------------------------------
# P1 — segmentation conformance is re-derived, not attested
# ---------------------------------------------------------------------------


def _severed_unit() -> EvidenceUnit:
    """The forgery: the result, on its own, with the binding simply omitted.

    Built through the ordinary constructor, so it has a real derived identity, a consistent
    digest and a consistent witness. Every storage-checkable property holds. What is wrong with
    it is only visible by asking what segmentation actually produces -- which is the point.
    """
    return EvidenceUnit.build(
        artifact_id=fixture_artifact_id(),
        unit_type=EvidenceUnitType.PROSE,
        structural_path="3/prose:1/0",
        locator=SourceLocator(label="§3"),
        body=RESULT_SENTENCE,
        provenance=SegmenterProvenance(
            segmenter_id="evidence_aware_hierarchical",
            segmenter_version="1.0.0",
            parser_id="local_markdown",
            parser_version="1.0.0",
        ),
    )


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_a_severed_unit_with_no_declared_binding_is_refused_by_re_derivation():
    """THE P1 probe. Declaring nothing used to skip §6.22 rule 1 entirely.

    The unit is internally flawless: derived id, matching digest, matching witness, real
    artifact, resolvable locator. The condition that makes its number interpretable is nowhere,
    and ``bound_condition_texts`` is empty so the rule-1 trigger never fires.

    Re-derivation catches it without reading a word: this body is not one of the bodies the
    segmenter produces from those bytes.
    """
    severed = _severed_unit()
    units = {severed.evidence_unit_id: severed}

    assert severed.bound_condition_texts == ()
    assert CONDITION_SENTENCE not in severed.interpretive_text

    with pytest.raises(AdmissionRefusal) as caught:
        _gate(units).admit(
            AdmissionRequest(
                attestation=_attestation(
                    epistemic_type=EpistemicType.REPORTED,
                    source_work_id="swk:report",
                    evidence_unit_id=severed.evidence_unit_id,
                ),
                evidence_unit_id=severed.evidence_unit_id,
            )
        )
    assert caught.value.reason is RefusalReason.SEGMENTATION_NOT_REPRODUCIBLE


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_a_genuine_unit_from_the_same_artifact_is_admitted():
    """The positive control the probe above needs.

    Without it, a re-derivation that refused everything would pass the probe and break the
    system -- and the difference between the two units is exactly one omitted binding.
    """
    units = _units()
    target = next(
        unit.evidence_unit_id
        for unit in units.values()
        if CONDITION_SENTENCE in unit.interpretive_text
    )
    admitted = _gate(units).admit(
        AdmissionRequest(
            attestation=_attestation(
                epistemic_type=EpistemicType.REPORTED,
                source_work_id="swk:report",
                evidence_unit_id=target,
            ),
            evidence_unit_id=target,
        )
    )
    assert admitted.evidence_unit_id == target


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_admission_fails_closed_when_re_derivation_is_not_configured():
    """A deployment that cannot verify must not admit. Silence is not a pass."""
    units = _units()
    target = next(iter(units))
    with pytest.raises(AdmissionRefusal) as caught:
        _gate(units, resegment=None).admit(
            AdmissionRequest(
                attestation=_attestation(
                    epistemic_type=EpistemicType.REPORTED,
                    source_work_id="swk:report",
                    evidence_unit_id=target,
                ),
                evidence_unit_id=target,
            )
        )
    assert caught.value.reason is RefusalReason.SEGMENTATION_NOT_VERIFIABLE


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_admission_fails_closed_when_the_artifact_bytes_are_unavailable():
    """ "We could not check" and "this document has no evidence" are opposite facts."""
    units = _units()
    target = next(iter(units))
    with pytest.raises(AdmissionRefusal) as caught:
        _gate(units, resegment=SegmentationReverifier(lambda _: None)).admit(
            AdmissionRequest(
                attestation=_attestation(
                    epistemic_type=EpistemicType.REPORTED,
                    source_work_id="swk:report",
                    evidence_unit_id=target,
                ),
                evidence_unit_id=target,
            )
        )
    assert caught.value.reason is RefusalReason.SEGMENTATION_NOT_VERIFIABLE


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_stripping_a_binding_from_a_genuine_unit_is_refused():
    """The subtler forgery: take a real unit, keep its body, drop what binds it.

    Its identity is unchanged -- bindings are deliberately not part of identity -- so the unit
    still resolves, and its witness is recomputed consistently by the constructor. Only
    re-derivation notices that the segmenter does not produce it with an empty binding list.
    """
    genuine = next(unit for unit in segment_fixture().units if unit.bound_condition_texts)
    stripped = EvidenceUnit.build(
        artifact_id=genuine.artifact_id,
        unit_type=genuine.unit_type,
        structural_path=genuine.structural_path,
        locator=genuine.locator,
        body=genuine.body,
        provenance=genuine.provenance,
    )
    assert stripped.evidence_unit_id == genuine.evidence_unit_id
    assert stripped.bound_condition_texts == ()

    with pytest.raises(AdmissionRefusal) as caught:
        _gate({stripped.evidence_unit_id: stripped}).admit(
            AdmissionRequest(
                attestation=_attestation(
                    epistemic_type=EpistemicType.REPORTED,
                    source_work_id="swk:report",
                    evidence_unit_id=stripped.evidence_unit_id,
                ),
                evidence_unit_id=stripped.evidence_unit_id,
            )
        )
    assert caught.value.reason is RefusalReason.SEGMENTATION_NOT_REPRODUCIBLE


# ---------------------------------------------------------------------------
# The witness — the storage-checkable half, and what it does not claim
# ---------------------------------------------------------------------------


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_a_witness_that_does_not_bind_the_body_is_refused():
    """The partial forgery: edit the body, leave the witness behind."""
    from pydantic import ValidationError

    unit = _severed_unit()
    forged_body = "Cj increased to 9.999 pF/mm."
    digest = compute_content_hash(forged_body.encode("utf-8"))
    with pytest.raises(ValidationError, match="does not bind this unit's contents"):
        EvidenceUnit.model_validate(
            unit.model_dump()
            | {
                "body": forged_body,
                "content_digest": digest,
                "evidence_unit_id": __import__(
                    "lab_brain.core.models.identifiers", fromlist=["x"]
                ).evidence_unit_id_for(unit.artifact_id, unit.structural_path, digest),
            }
        )


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_the_witness_does_not_bind_created_at_or_source_work():
    """Deliberate: those are not outputs of segmentation.

    Binding them would make the witness un-recomputable by a re-derivation that legitimately
    produces the same evidence at a different time, which would turn the cheap layer into a
    source of false refusals.
    """
    unit = _severed_unit()
    same = segmentation_witness_for(
        artifact_id=unit.artifact_id,
        structural_path=unit.structural_path,
        body=unit.body,
        inherited_context=unit.inherited_context,
        bound_condition_texts=unit.bound_condition_texts,
        parser_id=unit.provenance.parser_id,
        parser_version=unit.provenance.parser_version,
        segmenter_id=unit.provenance.segmenter_id,
        segmenter_version=unit.provenance.segmenter_version,
    )
    assert same == unit.segmentation_witness


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_the_witness_changes_when_a_binding_changes():
    """Otherwise the cheap layer would bind nothing that matters."""
    unit = _severed_unit()
    with_binding = segmentation_witness_for(
        artifact_id=unit.artifact_id,
        structural_path=unit.structural_path,
        body=unit.body,
        inherited_context=(),
        bound_condition_texts=(CONDITION_SENTENCE,),
        parser_id=unit.provenance.parser_id,
        parser_version=unit.provenance.parser_version,
        segmenter_id=unit.provenance.segmenter_id,
        segmenter_version=unit.provenance.segmenter_version,
    )
    assert with_binding != unit.segmentation_witness
