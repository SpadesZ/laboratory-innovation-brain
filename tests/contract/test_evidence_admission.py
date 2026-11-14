"""T-EVI-002 / T-EVI-003 / T-EVI-009 — the memory admission gate (§14.3).

Three requirements share this gate and each has its own §26 pass condition:

    T-EVI-002  parser 缺欄位時輸出 UNKNOWN/NOT_REPORTED，不得生成 default scientific value
    T-EVI-003  LLM-generated interpretation 無法被 evidence admission gate 當作 observed/
               simulated evidence
    T-EVI-009  a MEASURED/SIMULATED fixture with no run/artifact reference is refused at
               admission; one with a reference round-trips and resolves to an existing Artifact;
               admitting first and back-filling is refused; an INFERRED record is not subject to
               the reference requirement but still cannot be typed MEASURED/SIMULATED

Every refusal is asserted on its ``RefusalReason``, not on message text. A test that accepted any
refusal would pass when the wrong guard fired, which is how a gate keeps working while checking
something other than what it is supposed to.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from lab_brain.core.models import (
    Attestation,
    EpistemicType,
    EvidenceField,
    ExtractionProvenance,
    FieldStatus,
)
from lab_brain.ingestion.admission_gate import (
    AdmissionRefusal,
    AdmissionRequest,
    EvidenceAdmissionGate,
    RefusalReason,
)
from tests.conftest_fixtures import TOY_SCHEMA_REF, make_artifact

PROJECT = "prj:test"
#: A fictional domain's schema. §24.1: a core test naming a photonics schema would make the core
#: suite depend on a DomainPack that does not exist until M2.
SCHEMA = TOY_SCHEMA_REF


def _attestation(
    epistemic_type: EpistemicType = EpistemicType.MEASURED,
    *,
    source_artifact_id: str | None = None,
    run_id: str | None = None,
    source_work_id: str | None = None,
    inference_provenance_id: str | None = None,
    field_states: dict[str, EvidenceField] | None = None,
) -> Attestation:
    sources = [source_artifact_id, run_id, source_work_id]
    if all(source is None for source in sources):
        source_work_id = "swk:unreferenced"
    return Attestation(
        claim_id="clm:cj-falls-with-reverse-bias",
        epistemic_type=epistemic_type,
        source_artifact_id=source_artifact_id,
        run_id=run_id,
        source_work_id=source_work_id,
        locator="§3 / Table 1 / row 2",
        conditions={"bias_v": -2.0},
        conditions_schema_version=SCHEMA,
        field_states=field_states or {},
        project_id=PROJECT,
        extractor_version="1.0.0",
        extraction_provenance=ExtractionProvenance(
            extractor_id="local_markdown",
            extractor_version="1.0.0",
            inference_provenance_id=inference_provenance_id,
        ),
    )


def _gate(
    *,
    artifacts: dict[str, object] | None = None,
    units: dict[str, object] | None = None,
    admitted: set[str] | None = None,
) -> EvidenceAdmissionGate:
    store = artifacts or {}
    unit_store = units or {}
    seen = admitted or set()
    return EvidenceAdmissionGate(
        load_artifact=lambda key: store.get(key),  # type: ignore[arg-type,return-value]
        load_evidence_unit=lambda key: unit_store.get(key),  # type: ignore[arg-type,return-value]
        already_admitted=lambda key: key in seen,
    )


# ---------------------------------------------------------------------------
# EVI-009 — the reference is required AT admission
# ---------------------------------------------------------------------------


@pytest.mark.requirement("EVI-009")
@pytest.mark.spec_test("T-EVI-009")
@pytest.mark.parametrize("epistemic_type", [EpistemicType.MEASURED, EpistemicType.SIMULATED])
def test_a_measured_or_simulated_record_with_no_reference_is_refused(epistemic_type):
    """A measurement nobody can trace to what produced it is a number with a label."""
    with pytest.raises(AdmissionRefusal) as caught:
        _gate().admit(AdmissionRequest(attestation=_attestation(epistemic_type)))
    assert caught.value.reason is RefusalReason.REFERENCE_MISSING


@pytest.mark.requirement("EVI-009")
@pytest.mark.spec_test("T-EVI-009")
def test_a_reference_to_an_artifact_that_does_not_exist_is_refused():
    """Fail closed. "Not found" treated as "probably fine" admits a missing measurement."""
    attestation = _attestation(source_artifact_id="art:sha256:" + "0" * 64)
    with pytest.raises(AdmissionRefusal) as caught:
        _gate(artifacts={}).admit(AdmissionRequest(attestation=attestation))
    assert caught.value.reason is RefusalReason.REFERENCED_ARTIFACT_NOT_FOUND


@pytest.mark.requirement("EVI-009")
@pytest.mark.spec_test("T-EVI-009")
def test_a_reference_that_resolves_round_trips():
    """The positive control. Without it every test above passes on a gate that refuses all."""
    artifact = make_artifact(b"measured impedance sweep", uri="file:///sweep.csv")
    attestation = _attestation(source_artifact_id=artifact.artifact_id)
    admitted = _gate(artifacts={artifact.artifact_id: artifact}).admit(
        AdmissionRequest(attestation=attestation)
    )
    assert admitted.attestation_id == attestation.attestation_id
    assert admitted.source_artifact_id == artifact.artifact_id


@pytest.mark.requirement("EVI-009")
@pytest.mark.spec_test("T-EVI-009")
def test_admitting_first_and_back_filling_the_reference_is_refused():
    """§25.3 states this explicitly: MUST NOT be admitted first and back-filled later.

    The sequence that would otherwise work: admit with no reference (refused above), or admit a
    REPORTED record and re-submit it as MEASURED with a reference attached. The second is what
    this covers -- the record is already admitted, so re-admission is refused whatever it now
    carries. A correction is a new attestation with its own provenance.
    """
    artifact = make_artifact(b"late arrival", uri="file:///late.csv")
    attestation = _attestation(source_artifact_id=artifact.artifact_id)
    gate = _gate(artifacts={artifact.artifact_id: artifact}, admitted={attestation.attestation_id})
    with pytest.raises(AdmissionRefusal) as caught:
        gate.admit(AdmissionRequest(attestation=attestation))
    assert caught.value.reason is RefusalReason.BACKFILL_REFUSED


@pytest.mark.requirement("EVI-009")
@pytest.mark.spec_test("T-EVI-009")
def test_an_inferred_record_is_exempt_from_the_reference_requirement():
    """INFERRED is outside EVI-009's scope -- but never a way around EVI-003."""
    attestation = _attestation(EpistemicType.INFERRED, source_work_id="swk:some-paper")
    assert _gate().admit(AdmissionRequest(attestation=attestation)) is attestation


@pytest.mark.requirement("EVI-009")
@pytest.mark.spec_test("T-EVI-009")
def test_an_inferred_record_still_cannot_be_typed_measured():
    """The exemption in the previous test is not a door into the factual types (EVI-003)."""
    attestation = _attestation(
        EpistemicType.MEASURED,
        source_work_id="swk:some-paper",
        inference_provenance_id="inf:1",
    )
    with pytest.raises(AdmissionRefusal) as caught:
        _gate().admit(AdmissionRequest(attestation=attestation, llm_derived=True))
    assert caught.value.reason is RefusalReason.INFERENCE_TYPED_AS_FACT


@pytest.mark.requirement("EVI-009")
@pytest.mark.spec_test("T-EVI-009")
def test_reported_and_derived_records_need_no_run_or_artifact():
    """EVI-009's scope is MEASURED and SIMULATED.

    A paper reporting someone else's measurement has a source work, not a run of ours. Widening
    the rule to REPORTED would make every citation a measurement we performed.
    """
    for epistemic_type in (EpistemicType.REPORTED, EpistemicType.DERIVED):
        attestation = _attestation(epistemic_type, source_work_id="swk:cited-paper")
        assert _gate().admit(AdmissionRequest(attestation=attestation)) is attestation


# ---------------------------------------------------------------------------
# EVI-003 — an inference is never a fact
# ---------------------------------------------------------------------------


@pytest.mark.requirement("EVI-003")
@pytest.mark.spec_test("T-EVI-003")
@pytest.mark.parametrize(
    "epistemic_type",
    [EpistemicType.OBSERVED, EpistemicType.SIMULATED, EpistemicType.MEASURED],
)
def test_llm_derived_text_cannot_be_admitted_as_a_factual_type(epistemic_type):
    """The negative fixture §26 asks for: LLM text claiming a measured result, refused."""
    artifact = make_artifact(b"a paper about capacitance", uri="file:///paper.pdf")
    attestation = _attestation(
        epistemic_type,
        source_artifact_id=artifact.artifact_id,
        inference_provenance_id="inf:gpt-summary-1",
    )
    with pytest.raises(AdmissionRefusal) as caught:
        _gate(artifacts={artifact.artifact_id: artifact}).admit(
            AdmissionRequest(attestation=attestation, llm_derived=True)
        )
    assert caught.value.reason is RefusalReason.INFERENCE_TYPED_AS_FACT


@pytest.mark.requirement("EVI-003")
@pytest.mark.spec_test("T-EVI-003")
def test_the_refusal_is_not_repaired_by_relabelling():
    """§26: refused, not silently corrected to INFERRED.

    A gate that relabelled would admit the content under a different name and the caller would
    never learn that what it submitted was not evidence. Asserted by the gate raising rather than
    returning anything at all -- there is no repaired record to inspect.
    """
    attestation = _attestation(
        EpistemicType.MEASURED,
        source_work_id="swk:paper",
        inference_provenance_id="inf:1",
    )
    with pytest.raises(AdmissionRefusal):
        _gate().admit(AdmissionRequest(attestation=attestation, llm_derived=True))
    # The submitted record is untouched: it is frozen, and nothing wrote a corrected copy.
    assert attestation.epistemic_type is EpistemicType.MEASURED


@pytest.mark.requirement("EVI-003")
@pytest.mark.spec_test("T-EVI-003")
def test_llm_derived_inference_without_provenance_is_refused():
    """LLM-001 / AGT-010: an inference with no model/prompt/bundle provenance is unauditable."""
    attestation = _attestation(EpistemicType.INFERRED, source_work_id="swk:paper")
    with pytest.raises(AdmissionRefusal) as caught:
        _gate().admit(AdmissionRequest(attestation=attestation, llm_derived=True))
    assert caught.value.reason is RefusalReason.INFERENCE_PROVENANCE_MISSING


@pytest.mark.requirement("EVI-003")
@pytest.mark.spec_test("T-EVI-003")
def test_llm_derived_inference_with_provenance_is_admitted_as_an_inference():
    """The positive control: EVI-003 restricts the *type*, it does not ban the record."""
    attestation = _attestation(
        EpistemicType.INFERRED,
        source_work_id="swk:paper",
        inference_provenance_id="inf:gpt-summary-1",
    )
    admitted = _gate().admit(AdmissionRequest(attestation=attestation, llm_derived=True))
    assert admitted.is_inference


# ---------------------------------------------------------------------------
# EVI-002 — absence is recorded, never filled
# ---------------------------------------------------------------------------


@pytest.mark.requirement("EVI-002")
@pytest.mark.spec_test("T-EVI-002")
@pytest.mark.parametrize("status", [FieldStatus.UNKNOWN, FieldStatus.NOT_REPORTED])
def test_an_absent_field_cannot_carry_a_value(status):
    """A value behind an absent status is the hallucinated completion EVI-002 forbids.

    Refused at construction, so a record like this cannot exist in memory to be admitted.
    """
    with pytest.raises(ValidationError, match="must be empty, not filled with a guess"):
        EvidenceField(name="implant_dose", value=1.2e18, status=status)


@pytest.mark.requirement("EVI-002")
@pytest.mark.spec_test("T-EVI-002")
def test_the_gate_refuses_an_absent_field_that_carries_a_value():
    """The same rule at the admission boundary, for records that arrive from storage.

    The model guards a record being built; this guards one being admitted, and a row written
    before the validator existed reaches the gate without ever passing the model's check.
    """
    attestation = _attestation(
        EpistemicType.REPORTED,
        source_work_id="swk:paper",
        field_states={
            "implant_dose": EvidenceField(name="implant_dose", status=FieldStatus.UNKNOWN)
        },
    )
    # Written AFTER construction, deliberately. Both `EvidenceField` and `Attestation` validate
    # this on build, so a record shaped this way cannot be constructed -- which is correct, and
    # is also why the only honest way to reach the gate's copy of the check is to bypass the
    # model the same way a pre-validator database row would.
    object.__setattr__(attestation.field_states["implant_dose"], "value", 1.2e18)

    with pytest.raises(AdmissionRefusal) as caught:
        _gate().admit(AdmissionRequest(attestation=attestation))
    assert caught.value.reason is RefusalReason.INVENTED_SCIENTIFIC_VALUE


@pytest.mark.requirement("EVI-002")
@pytest.mark.spec_test("T-EVI-002")
def test_a_missing_field_is_admitted_as_unknown():
    """The positive control, and the behaviour EVI-002 actually wants.

    The fixture's method section states that the wafer identifier and implant dose were not
    recorded. The correct extraction says so; it does not supply a typical dose.
    """
    attestation = _attestation(
        EpistemicType.REPORTED,
        source_work_id="swk:paper",
        field_states={
            "wafer_identifier": EvidenceField(
                name="wafer_identifier", status=FieldStatus.NOT_REPORTED
            ),
            "implant_dose": EvidenceField(name="implant_dose", status=FieldStatus.UNKNOWN),
            "bias_v": EvidenceField(
                name="bias_v", value=-2.0, unit="V", status=FieldStatus.EXPLICIT
            ),
        },
    )
    admitted = _gate().admit(AdmissionRequest(attestation=attestation))
    assert admitted.unknown_fields() == ("implant_dose", "wafer_identifier")
    assert admitted.high_weight_fields() == ("bias_v",)


@pytest.mark.requirement("EVI-002")
@pytest.mark.spec_test("T-EVI-002")
def test_an_explicit_field_with_no_value_is_refused():
    """The inverse: EXPLICIT means the document said it, so there has to be something to read."""
    with pytest.raises(ValidationError, match="should be NOT_REPORTED"):
        EvidenceField(name="bias_v", status=FieldStatus.EXPLICIT)


@pytest.mark.requirement("EVI-002")
@pytest.mark.spec_test("T-EVI-002")
def test_the_parser_reports_an_absent_table_unit_as_absent_not_as_a_guess():
    """EVI-002 at the parser, where the temptation to infer a unit is strongest.

    A units row with a dash means the column has no unit. The parser records ``None``; it does
    not look at the numbers and decide they are probably volts.
    """
    from lab_brain.ingestion.parsers.documents import MarkdownDocumentParser

    document = MarkdownDocumentParser().parse(
        "| Split | Count |\n| [-] | [-] |\n| A | 4 |\n",
        artifact_id="art:sha256:" + "a" * 64,
    )
    table = document.blocks[0]
    assert table.table_units == (None, None)
