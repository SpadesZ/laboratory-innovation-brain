"""T-EVI-010 — the retrieval/admission boundary (EVI-010, §6.22, §17.25, ADR-0011).

Pass condition (§26), the retrieval half:

    a retrieval candidate whose index payload has been altered MUST NOT change the admitted
    evidence body -- final resolution reloads the canonical unit by identity; deleting and
    rebuilding an index changes no `evidence_unit_id`; and a retrieved payload cannot be admitted
    as an Attestation without passing the ordinary admission gates.

THE ATTACK. An index holds a copy of the text. If admission reads that copy, whoever can write to
the index can write scientific evidence, and the resulting attestation is well-formed, correctly
statused and cites a real locator in a real document. The only thing wrong with it is that the
document does not say it.
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
    SubdivisionReason,
)
from lab_brain.evidence.retriever import CandidateResolver, LexicalEvidenceIndex
from lab_brain.ingestion.admission_gate import (
    AdmissionRefusal,
    AdmissionRequest,
    EvidenceAdmissionGate,
    RefusalReason,
)
from lab_brain.ingestion.fixed_token_baseline import BaselineRun, FixedTokenBaselineSegmenter
from lab_brain.ingestion.reverification import SegmentationReverifier
from tests.conftest_fixtures import TOY_SCHEMA_REF
from tests.evidence_fixtures import (
    RESULT_SENTENCE,
    fixture_artifact_id,
    fixture_bytes,
    parse_fixture,
    segment_fixture,
)

PROJECT = "prj:test"
OTHER_PROJECT = "prj:other"

FORGED = "The junction capacitance increased to 9.999 pF/mm under forward bias."


@pytest.fixture
def indexed():
    """The locked fixture, segmented and indexed. Returns (units, index, resolver)."""
    units = {unit.evidence_unit_id: unit for unit in segment_fixture().units}
    index = LexicalEvidenceIndex()
    index.add_all(units.values(), project_id=PROJECT)
    return units, index, CandidateResolver(lambda key: units.get(key))


def _attestation(**extra) -> Attestation:
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
        **extra,
    )


def _reverifier():
    """Re-segment the locked fixture from its own bytes (SPEC-ISSUE-015's semantic layer)."""
    return SegmentationReverifier(
        lambda artifact_id: fixture_bytes() if artifact_id == fixture_artifact_id() else None
    )


def _gate(units, **overrides):
    """A gate wired the way a deployment is, with one seam swappable per test.

    Presence and re-derivation default to *working*, so a test that wants a specific refusal
    disables exactly one thing and the refusal it gets names that thing. Defaulting them to
    absent would make every test here pass on SEGMENTATION_NOT_VERIFIABLE and prove nothing.
    """
    kwargs = {
        "load_artifact": lambda _: None,
        "load_evidence_unit": lambda key: units.get(key),
        "resegment": _reverifier(),
        "is_present_in": lambda _unit, project: project == PROJECT,
    }
    kwargs.update(overrides)
    return EvidenceAdmissionGate(**kwargs)


# ---------------------------------------------------------------------------
# A candidate is an identifier, not content
# ---------------------------------------------------------------------------


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_retrieval_returns_identifiers_and_the_body_comes_from_the_store(indexed):
    """The seam itself: resolution re-loads every unit by ``evidence_unit_id``."""
    units, index, resolver = indexed
    candidates = index.search("junction capacitance reverse bias", project_id=PROJECT, limit=5)
    assert candidates, "the fixture's condition/result unit was not retrievable at all"

    resolved, divergences = resolver.resolve(candidates, index=index)
    assert divergences == ()
    for entry in resolved:
        assert entry.body == units[entry.candidate.evidence_unit_id].body


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_a_tampered_index_payload_cannot_alter_the_evidence_body(indexed):
    """THE attack. The index is rewritten; the canonical body is unchanged and wins."""
    units, index, resolver = indexed
    target = next(unit.evidence_unit_id for unit in units.values() if RESULT_SENTENCE in unit.body)
    index.tamper(target, FORGED)

    resolved, _ = resolver.resolve(
        index.search("junction capacitance", project_id=PROJECT, limit=5), index=index
    )
    bodies = {entry.candidate.evidence_unit_id: entry.body for entry in resolved}

    assert FORGED not in bodies.get(target, ""), (
        "the tampered index payload reached the resolved evidence body"
    )
    assert RESULT_SENTENCE in bodies[target]
    assert units[target].body == bodies[target]


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_a_tampered_index_is_reported_as_divergent(indexed):
    """§17.25: payload_digest exists to make divergence detectable, not to be trusted."""
    units, index, resolver = indexed
    target = next(iter(units))
    index.tamper(target, FORGED)

    _, divergences = resolver.resolve(
        index.search("junction capacitance reverse bias split", project_id=PROJECT, limit=20),
        index=index,
    )
    assert any(divergence.evidence_unit_id == target for divergence in divergences), (
        "an index holding text the canonical unit does not say went unreported"
    )


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_a_forged_body_is_refused_at_admission(indexed):
    """The second line. Even submitted directly, a non-canonical body does not become evidence."""
    units, _, _ = indexed
    target = next(iter(units))
    with pytest.raises(AdmissionRefusal) as caught:
        _gate(units).admit(
            AdmissionRequest(
                attestation=_attestation(evidence_unit_id=target),
                evidence_unit_id=target,
                claimed_body=FORGED,
            )
        )
    assert caught.value.reason is RefusalReason.EVIDENCE_BODY_NOT_CANONICAL


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_the_canonical_body_is_admitted(indexed):
    """The positive control, and it now exercises the whole admission contract.

    Canonical body, durable link on the record, presence in the project, and a unit that
    re-segmentation actually reproduces. Every one of those is a separate refusal elsewhere in
    this file; here they all hold, which is what keeps the negatives from passing vacuously.
    """
    units, _, _ = indexed
    target = next(iter(units))
    admitted = _gate(units).admit(
        AdmissionRequest(
            attestation=_attestation(evidence_unit_id=target),
            evidence_unit_id=target,
            claimed_body=units[target].body,
        )
    )
    assert admitted is not None
    assert admitted.evidence_unit_id == target


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_a_candidate_pointing_at_a_unit_that_does_not_resolve_is_refused():
    """A candidate that cannot be re-loaded by identity cannot become evidence."""
    gate = EvidenceAdmissionGate(load_artifact=lambda _: None, load_evidence_unit=lambda _: None)
    with pytest.raises(AdmissionRefusal) as caught:
        gate.admit(
            AdmissionRequest(attestation=_attestation(), evidence_unit_id="evu:sha256:" + "9" * 64)
        )
    assert caught.value.reason is RefusalReason.EVIDENCE_UNIT_NOT_FOUND


# ---------------------------------------------------------------------------
# The baseline is measured, never admitted
# ---------------------------------------------------------------------------


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_a_benchmark_baseline_unit_is_refused_at_admission():
    """§6.22 rule 3(b). Baseline units exist to be measured against, never to be admitted."""
    baseline = FixedTokenBaselineSegmenter(window=40, overlap=5).segment(
        parse_fixture(), run=BaselineRun(reason="T-EVI-010 comparison")
    )
    units = {unit.evidence_unit_id: unit for unit in baseline}
    target = next(iter(units))
    assert units[target].subdivision_reason is SubdivisionReason.BENCHMARK_BASELINE

    with pytest.raises(AdmissionRefusal) as caught:
        _gate(units).admit(
            AdmissionRequest(
                attestation=_attestation(evidence_unit_id=target), evidence_unit_id=target
            )
        )
    assert caught.value.reason is RefusalReason.BASELINE_UNIT_NOT_ADMISSIBLE


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_producing_baseline_units_requires_an_explicit_marker():
    """A bare boolean would be defaultable; this cannot be reached without naming it."""
    with pytest.raises(TypeError):
        FixedTokenBaselineSegmenter().segment(parse_fixture(), project_id=PROJECT)  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="must state why"):
        BaselineRun(reason="  ")


# ---------------------------------------------------------------------------
# Project scope (SEC-002) on the new read paths
# ---------------------------------------------------------------------------


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_retrieval_never_ranks_a_unit_from_another_project(indexed):
    """SEC-002 / R-7 on the retrieval path. Filtered before scoring, not after."""
    _, index, _ = indexed
    foreign = EvidenceUnit.build(
        artifact_id="art:sha256:" + "7" * 64,
        unit_type=EvidenceUnitType.PROSE,
        structural_path="1/prose:0/0",
        locator=SourceLocator(label="§1"),
        body="The junction capacitance of the confidential split was 0.111 pF/mm.",
        provenance=SegmenterProvenance(
            segmenter_id="evidence_aware_hierarchical",
            segmenter_version="1.0.0",
            parser_id="local_markdown",
            parser_version="1.0.0",
        ),
    )
    index.add(foreign, project_id=OTHER_PROJECT)

    candidates = index.search("junction capacitance", project_id=PROJECT, limit=50)
    assert foreign.evidence_unit_id not in {c.evidence_unit_id for c in candidates}
    assert all(candidate.project_id == PROJECT for candidate in candidates)


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_admission_refuses_an_evidence_unit_from_another_project():
    """Presence in one project grants nothing in another, at the admission boundary."""
    foreign = EvidenceUnit.build(
        artifact_id="art:sha256:" + "7" * 64,
        unit_type=EvidenceUnitType.PROSE,
        structural_path="1/prose:0/0",
        locator=SourceLocator(label="§1"),
        body="Confidential.",
        provenance=SegmenterProvenance(
            segmenter_id="s", segmenter_version="1", parser_id="p", parser_version="1"
        ),
    )
    units = {foreign.evidence_unit_id: foreign}
    with pytest.raises(AdmissionRefusal) as caught:
        # Presence says no: the unit exists globally and has no occurrence in PROJECT. That is
        # now the whole check -- after ADR-0012 the unit carries no project of its own to
        # disagree with, so asking the occurrence is asking the authority on presence.
        _gate(units, is_present_in=lambda _unit, _project: False).admit(
            AdmissionRequest(
                attestation=_attestation(evidence_unit_id=foreign.evidence_unit_id),
                evidence_unit_id=foreign.evidence_unit_id,
            )
        )
    assert caught.value.reason is RefusalReason.CROSS_PROJECT_UNIT


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_admission_consults_the_existing_read_gate(indexed):
    """SEC-002 is injected, not reimplemented (R-7).

    The gate takes a ``can_read`` callable and refuses when it says no. The real caller passes
    ``lab_brain.core.access.can_read_artifact``, which stays the only copy of the ACL logic --
    a second copy here would be a second thing to keep in step with it.
    """
    units, _, _ = indexed
    target = next(iter(units))
    refused: list[tuple[str, str]] = []

    def deny(artifact_id: str, project_id: str) -> bool:
        refused.append((artifact_id, project_id))
        return False

    with pytest.raises(AdmissionRefusal) as caught:
        _gate(units, can_read=deny).admit(
            AdmissionRequest(
                attestation=_attestation(evidence_unit_id=target), evidence_unit_id=target
            )
        )
    assert caught.value.reason is RefusalReason.READ_NOT_PERMITTED
    assert refused == [(units[target].artifact_id, PROJECT)], (
        "the read gate was not consulted with the unit's artifact and the attestation's project"
    )


@pytest.mark.requirement("EVI-010")
@pytest.mark.spec_test("T-EVI-010")
def test_retrieval_is_bounded(indexed):
    """§17.12: all traversal APIs MUST be bounded."""
    _, index, _ = indexed
    with pytest.raises(ValueError, match="bounded"):
        index.search("anything", project_id=PROJECT, limit=0)
