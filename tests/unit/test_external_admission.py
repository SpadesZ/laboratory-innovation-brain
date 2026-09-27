"""External admission without a database: what an admission may claim, and what it refuses.

The PostgreSQL half (`e2e/test_external_evidence_postgres.py`) shows the metadata lands in the
rows; this half pins the rules themselves -- REPORTED only, the durable record only, one work per
identity, and the §6.4 stage bounded by what the snapshot kept.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from lab_brain.core.models.attestation import Attestation
from lab_brain.core.models.claim import Claim
from lab_brain.core.models.enums import (
    EpistemicType,
    ExtractionStatus,
    SourceWorkStatus,
    TrustClass,
)
from lab_brain.core.models.external_source import ExternalSourceEventKind, Retention
from lab_brain.core.models.source_work import RetractionCheck, SourceWork, WorkIdentifier
from lab_brain.domains.silicon_photonics.condition_schema import SCHEMA_REF
from lab_brain.ingestion.admission_gate import AdmissionRequest
from lab_brain.sources.admission import (
    STAGE_CEILING,
    ExternalAdmissionRefused,
    ExternalEvidenceAdmission,
)
from tests.external_fixtures import (
    ACTOR,
    PROJECT,
    PUBLIC_REPO,
    REMOVABLE_REPO,
    UNLICENSED_REPO,
    build,
    file_locator,
)

SCHEMA = SCHEMA_REF
CONDITIONS = {"bias_v": "-2"}


@dataclass
class _Works:
    works: dict[str, SourceWork] = field(default_factory=dict)
    statuses: list[tuple[str, SourceWorkStatus]] = field(default_factory=list)

    def add(self, work: SourceWork) -> SourceWork:
        self.works[work.source_work_id] = work
        return work

    def find_by_identifier(self, scheme: str, value: str) -> SourceWork | None:
        for work in self.works.values():
            if any(i.scheme == scheme and i.value == value for i in work.identifiers):
                return work
        return None

    def record_status(self, source_work_id: str, check: RetractionCheck) -> None:
        self.statuses.append((source_work_id, check.status))


@dataclass
class _Sink:
    items: list[object] = field(default_factory=list)

    def add(self, item):  # type: ignore[no-untyped-def]
        self.items.append(item)
        return item


class _Gate:
    def admit(self, request: AdmissionRequest) -> Attestation:
        return request.attestation


def _admission(world, works: _Works | None = None):  # type: ignore[no-untyped-def]
    works, claims, attestations = works or _Works(), _Sink(), _Sink()
    admission = ExternalEvidenceAdmission(
        snapshots=world.store,
        works=works,
        claims=claims,
        attestations=attestations,
        gate=_Gate(),
        mint=world.mint,
        now=world.clock,
    )
    return admission, works


def _admit(admission, snapshot, **kw):  # type: ignore[no-untyped-def]
    return admission.admit(
        snapshot,
        proposition=kw.pop("proposition", "Rs is normalised by drawn length"),
        fragment=kw.pop("fragment", "L1"),
        conditions=CONDITIONS,
        conditions_schema_version=SCHEMA,
        actor_id=ACTOR,
        **kw,
    )


def _snap(world, provider: str, locator: str):  # type: ignore[no-untyped-def]
    return world.service.snapshot(provider, locator, project_id=PROJECT, actor_id=ACTOR)


def test_the_stage_an_admission_claims_is_bounded_by_what_was_kept():
    world = build()
    admission, _ = _admission(world)
    full = _snap(world, "github", file_locator(PUBLIC_REPO, "main", "extract/rs_extraction.py"))
    excerpt = _snap(world, "literature", "doi:10.5555/sp.2021.113#p2")
    metadata = _snap(world, "github", file_locator(UNLICENSED_REPO, "main", "rs.py"))
    assert (full.retention, excerpt.retention, metadata.retention) == (
        Retention.FULL_CONTENT,
        Retention.EXCERPT,
        Retention.METADATA_ONLY,
    )
    # The default claims the least.
    assert _admit(admission, metadata).attestation.extraction_status is (
        ExtractionStatus.STAGE_A_METADATA
    )
    deep = _admit(admission, full, stage=ExtractionStatus.STAGE_C_DEEP).attestation
    assert deep.extraction_status is ExtractionStatus.STAGE_C_DEEP
    assert deep.extraction_provenance.stage is ExtractionStatus.STAGE_C_DEEP
    assert _admit(admission, excerpt, stage=ExtractionStatus.STAGE_B_STRUCTURED)
    for snapshot, stage in (
        (metadata, ExtractionStatus.STAGE_B_STRUCTURED),
        (excerpt, ExtractionStatus.STAGE_C_DEEP),
        (full, ExtractionStatus.STAGE_D_HUMAN_VERIFIED),
    ):
        with pytest.raises(ExternalAdmissionRefused) as refused:
            _admit(admission, snapshot, stage=stage)
        assert refused.value.reason_code == "STAGE_BEYOND_RETENTION"
    assert ExtractionStatus.STAGE_D_HUMAN_VERIFIED not in STAGE_CEILING.values()


@pytest.mark.requirement("GH-003")
@pytest.mark.spec_test("T-GH-003")
def test_external_material_is_reported_and_admitted_only_from_the_record():
    world = build()
    admission, _ = _admission(world)
    code = _snap(world, "github", file_locator(PUBLIC_REPO, "main", "extract/rs_extraction.py"))
    paper = _snap(world, "literature", "doi:10.5555/sp.2019.041#p3")
    for snapshot, reason in (
        (code, "TECHNICAL_EVIDENCE_PROMOTION"),
        (paper, "EXTERNAL_EVIDENCE_PROMOTION"),
    ):
        for kind in (EpistemicType.MEASURED, EpistemicType.SIMULATED, EpistemicType.OBSERVED):
            with pytest.raises(ExternalAdmissionRefused) as refused:
                _admit(admission, snapshot, epistemic_type=kind)
            assert refused.value.reason_code == reason
    forged = paper.model_copy(
        update={"trust_class": TrustClass.PEER_REVIEWED, "rights_status": "x"}
    )
    with pytest.raises(ExternalAdmissionRefused, match="SNAPSHOT_NOT_ON_RECORD"):
        _admit(admission, forged)
    with pytest.raises(ExternalAdmissionRefused, match="NO_PROPOSITION"):
        _admit(admission, paper, proposition="  ")
    admitted = _admit(admission, paper)
    assert admitted.attestation.epistemic_type is EpistemicType.REPORTED
    assert admitted.attestation.locator == f"{paper.canonical_locator}#L1"
    assert admitted.attestation.method["content_hash"] == paper.content_hash
    events = [e.kind for e in world.store.events(PROJECT)]
    assert events.count(ExternalSourceEventKind.ADMITTED) == 1, "refusals admit nothing"


def test_one_work_per_identity_and_the_work_keeps_one_trust_class():
    world = build()
    admission, works = _admission(world)
    first = _admit(
        admission,
        _snap(world, "github", file_locator(PUBLIC_REPO, "main", "extract/rs_extraction.py")),
    )
    second = _admit(
        admission, _snap(world, "github", file_locator(PUBLIC_REPO, "v1.0", "README.md"))
    )
    assert first.source_work.source_work_id == second.source_work.source_work_id
    assert len(works.works) == 1
    assert works.statuses == [(first.source_work.source_work_id, SourceWorkStatus.UNKNOWN)]
    # A work already on record under another trust class is not silently re-typed.
    paper = _snap(world, "literature", "doi:10.5555/sp.2019.041#p3")
    works.works["swk:planted"] = SourceWork(
        source_work_id="swk:planted",
        work_type=first.source_work.work_type,
        title="planted",
        identifiers=(WorkIdentifier(scheme="doi", value="10.5555/sp.2019.041"),),
        trust_class=TrustClass.TECHNICAL_ARTIFACT,
        retraction_check=RetractionCheck(status=SourceWorkStatus.UNKNOWN),
    )
    with pytest.raises(ExternalAdmissionRefused, match="TRUST_CLASS_CONFLICT"):
        _admit(admission, paper)
    assert isinstance(first.claim, Claim)


def test_removal_after_admission_records_source_unavailable_on_the_admitted_work():
    """§6.16 / EVI-008: the conclusion resting on vanished material answers to its work's status,
    so the work admitted from the snapshot records SOURCE_UNAVAILABLE when the source goes --
    not at some later admission."""
    works = _Works()
    world = build(works=works)
    admission, _ = _admission(world, works)
    locator = file_locator(REMOVABLE_REPO, "main", "mesh.py")
    admitted = _admit(admission, _snap(world, "github", locator))
    untouched = _admit(
        admission, _snap(world, "github", file_locator(PUBLIC_REPO, "main", "README.md"))
    )
    world.transport.remove(REMOVABLE_REPO)
    with pytest.raises(Exception, match="SOURCE_REMOVED"):
        _snap(world, "github", locator)
    work_id = admitted.source_work.source_work_id
    assert (work_id, SourceWorkStatus.SOURCE_UNAVAILABLE) in works.statuses
    assert all(w != untouched.source_work.source_work_id for w, _ in works.statuses)
