"""The M1-P1 end-to-end story, against real PostgreSQL.

    local scientific document
      -> secret scan -> raw Artifact -> project occurrence
      -> structured parse -> evidence-aware segmentation -> EvidenceUnit records
      -> candidate retrieval -> canonical re-resolution
      -> scientific admission

One deterministic fixture drives all of it: ``fixtures/evidence/rs_anomaly_report.md``, which
contains condition/result prose, a table, a figure with surrounding text, two values the document
explicitly does not record, and source-work identity metadata.

What this file adds over the contract tests is that the objects survive a round trip through the
database and that the compensating path runs against a real transaction. A unit that satisfies
every Pydantic validator and cannot be stored is not evidence.
"""

from __future__ import annotations

import json

import psycopg
import pytest

from lab_brain.core.access import can_read_artifact
from lab_brain.core.models import (
    Actor,
    ActorType,
    Attestation,
    EpistemicType,
    EvidenceUnitType,
    ExtractionProvenance,
    ProjectMembership,
    SensitivityLabel,
)
from lab_brain.evidence.retriever import CandidateResolver, LexicalEvidenceIndex
from lab_brain.ingestion.admission_gate import (
    AdmissionRefusal,
    AdmissionRequest,
    EvidenceAdmissionGate,
    RefusalReason,
)
from lab_brain.ingestion.pipeline import IngestionError, IngestionPipeline, IngestionStage
from lab_brain.storage.artifacts.local import LocalArtifactStore
from tests.conftest_fixtures import TOY_SCHEMA_REF
from tests.evidence_fixtures import (
    CONDITION_SENTENCE,
    MISSING_FIELDS,
    RESULT_SENTENCE,
    fixture_bytes,
    fixture_digest,
)

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.requirement("EVI-010"),
    pytest.mark.spec_test("T-EVI-010"),
]

PROJECT = "prj:test"
OTHER_PROJECT = "prj:other"
ACTOR = "act:test"


# ---------------------------------------------------------------------------
# Persistence helpers — the PostgreSQL half of the cross-store unit of work
# ---------------------------------------------------------------------------


def _commit_rows(connection):
    def commit(artifact, occurrence) -> None:
        with connection.transaction():
            connection.execute(
                "INSERT INTO artifacts (artifact_id, content_hash, media_type, uri, "
                "source_origin, lineage_id, actor_id, secret_scan_status) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    artifact.artifact_id,
                    artifact.content_hash,
                    artifact.media_type,
                    artifact.uri,
                    artifact.source_origin.value,
                    artifact.lineage_id,
                    artifact.actor_id,
                    artifact.secret_scan_status.value,
                ),
            )
            connection.execute(
                "INSERT INTO artifact_occurrences (artifact_id, project_id, sensitivity_label, "
                "ingested_by_actor_id) VALUES (%s, %s, %s, %s)",
                (
                    occurrence.artifact_id,
                    occurrence.project_id,
                    occurrence.sensitivity_label.value,
                    occurrence.ingested_by_actor_id,
                ),
            )

    return commit


def _rollback_rows(connection):
    def rollback(artifact, occurrence) -> None:
        with connection.transaction():
            connection.execute(
                "DELETE FROM artifact_occurrences WHERE artifact_id = %s AND project_id = %s",
                (occurrence.artifact_id, occurrence.project_id),
            )
            connection.execute(
                "DELETE FROM artifacts WHERE artifact_id = %s", (artifact.artifact_id,)
            )

    return rollback


def _persist_units(connection, units) -> None:
    for unit in units:
        connection.execute(
            "INSERT INTO evidence_units (evidence_unit_id, project_id, artifact_id, unit_type, "
            "structural_path, locator, body, content_digest, parent_unit_id, subdivision_index, "
            "subdivision_reason, inherited_context, conditions, bound_condition_texts, "
            "table_context, figure_context, parser_id, parser_version, segmenter_id, "
            "segmenter_version, token_limit) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "%s, %s, %s)",
            (
                unit.evidence_unit_id,
                unit.project_id,
                unit.artifact_id,
                unit.unit_type.value,
                unit.structural_path,
                unit.locator.model_dump_json(),
                unit.body,
                unit.content_digest,
                unit.parent_unit_id,
                unit.subdivision_index,
                unit.subdivision_reason.value if unit.subdivision_reason else None,
                list(unit.inherited_context),
                json.dumps(unit.conditions),
                list(unit.bound_condition_texts),
                unit.table_context.model_dump_json() if unit.table_context else None,
                unit.figure_context.model_dump_json() if unit.figure_context else None,
                unit.provenance.parser_id,
                unit.provenance.parser_version,
                unit.provenance.segmenter_id,
                unit.provenance.segmenter_version,
                unit.provenance.token_limit,
            ),
        )


@pytest.fixture
def ingested(db, tmp_path):
    """Run the whole vertical once, persisting to PostgreSQL. Returns the pieces it produced."""
    store = LocalArtifactStore(tmp_path / "artifacts")
    pipeline = IngestionPipeline(store, _commit_rows(db), _rollback_rows(db))
    outcome = pipeline.ingest(
        fixture_bytes(),
        project_id=PROJECT,
        actor_id=ACTOR,
        sensitivity_label=SensitivityLabel.INTERNAL,
        uri="file:///rs_anomaly_report.md",
    )
    assert outcome.artifact is not None
    _persist_units(db, outcome.evidence_units)
    return outcome, store, db


def _load_unit(db):
    from lab_brain.core.models import (
        EvidenceUnit,
        FigureContext,
        SegmenterProvenance,
        SourceLocator,
        TableContext,
    )

    def load(evidence_unit_id: str):
        row = db.execute(
            "SELECT evidence_unit_id, project_id, artifact_id, unit_type, structural_path, "
            "locator, body, content_digest, parent_unit_id, subdivision_index, "
            "subdivision_reason, inherited_context, conditions, bound_condition_texts, "
            "table_context, figure_context, parser_id, parser_version, segmenter_id, "
            "segmenter_version, token_limit "
            "FROM evidence_units WHERE evidence_unit_id = %s",
            (evidence_unit_id,),
        ).fetchone()
        if row is None:
            return None
        return EvidenceUnit(
            evidence_unit_id=row[0],
            project_id=row[1],
            artifact_id=row[2],
            unit_type=EvidenceUnitType(row[3]),
            structural_path=row[4],
            locator=SourceLocator.model_validate(row[5]),
            body=row[6],
            content_digest=row[7],
            parent_unit_id=row[8],
            subdivision_index=row[9],
            subdivision_reason=row[10],
            inherited_context=tuple(row[11]),
            conditions=row[12],
            bound_condition_texts=tuple(row[13]),
            table_context=TableContext.model_validate(row[14]) if row[14] else None,
            figure_context=FigureContext.model_validate(row[15]) if row[15] else None,
            provenance=SegmenterProvenance(
                parser_id=row[16],
                parser_version=row[17],
                segmenter_id=row[18],
                segmenter_version=row[19],
                token_limit=row[20],
            ),
        )

    return load


# ---------------------------------------------------------------------------
# The story
# ---------------------------------------------------------------------------


def test_the_whole_vertical_runs_and_every_stage_is_recorded(ingested):
    """Each stage produced a real result, in the order §17.22 fixes."""
    outcome, store, _ = ingested

    order = [result.stage for result in outcome.stage_results]
    assert order[0] is IngestionStage.SECRET_SCAN
    assert order[1] is IngestionStage.RAW_STORE
    assert order.index(IngestionStage.SEGMENT) > order.index(IngestionStage.RAW_STORE)

    assert outcome.raw_artifact_is_durable
    assert store.open(outcome.artifact.content_hash) == fixture_bytes()
    assert outcome.evidence_units


def test_the_fixture_is_locked(ingested):
    """§26 requires a fixed fixture. Editing it fails here with the new digest.

    A benchmark whose corpus can drift silently is a benchmark whose numbers mean nothing across
    two runs, and the pass conditions are stated per case against *this* document.
    """
    assert fixture_digest() == (
        "sha256:8b30ebc93163b8965b8ad8d67b298b20edeb832e16c69aacd66291fd621a981b"
    ), (
        "the locked T-EVI-010 fixture changed. If that was deliberate, update this digest in the "
        "same commit so the change is visible in review rather than absorbed silently."
    )


def test_no_critical_evidence_boundary_was_split(ingested):
    """The condition and its result survived the round trip in one unit (§6.22 rule 1)."""
    _, _, connection = ingested
    rows = connection.execute(
        "SELECT body, inherited_context FROM evidence_units WHERE project_id = %s", (PROJECT,)
    ).fetchall()
    holding = [
        body
        for body, inherited in rows
        if CONDITION_SENTENCE in (body + "\n".join(inherited))
        and RESULT_SENTENCE in (body + "\n".join(inherited))
    ]
    assert holding, "the bias condition and the capacitance result are in different stored units"


def test_table_and_figure_context_survived_persistence(ingested):
    """Rules 5 and 6, after a round trip rather than only in memory."""
    _, _, connection = ingested

    table = connection.execute(
        "SELECT table_context FROM evidence_units WHERE unit_type = 'TABLE' AND project_id = %s",
        (PROJECT,),
    ).fetchone()
    assert table is not None
    context = table[0]
    assert "Cj" in context["headers"]
    assert context["units"][context["headers"].index("Cj")] == "pF/mm"
    assert context["rows"], "the table round-tripped without its rows"

    figure = connection.execute(
        "SELECT figure_context FROM evidence_units WHERE unit_type = 'FIGURE' AND project_id = %s",
        (PROJECT,),
    ).fetchone()
    assert figure is not None
    assert figure[0]["caption"]
    assert figure[0]["surrounding_prose"], "the figure round-tripped without its explanatory prose"


def test_the_locator_round_trips_to_the_stored_document(ingested):
    """A unit resolves back to a re-checkable position in the bytes that are actually stored."""
    outcome, store, connection = ingested
    source = store.open(outcome.artifact.content_hash).decode("utf-8")

    rows = connection.execute(
        "SELECT structural_path, locator FROM evidence_units WHERE project_id = %s", (PROJECT,)
    ).fetchall()
    assert rows
    for path, locator in rows:
        start, end = locator["start_offset"], locator["end_offset"]
        assert start is not None and end is not None, f"{path} stored no offsets"
        assert source[start:end].strip(), f"{path}'s locator resolves to empty text"


def test_no_scientific_default_was_invented(ingested):
    """EVI-002 at the end of the vertical.

    The fixture states that the wafer identifier and implant dose were not recorded. Nothing in
    the pipeline may supply a typical value for either, and nothing may put them into a unit's
    conditions.
    """
    _, _, connection = ingested
    rows = connection.execute(
        "SELECT conditions, body FROM evidence_units WHERE project_id = %s", (PROJECT,)
    ).fetchall()
    for conditions, body in rows:
        for field in MISSING_FIELDS:
            assert field not in conditions, (
                f"the pipeline supplied a value for {field}, which the document does not record"
            )
        assert "1.2e18" not in body


def test_retrieval_resolves_back_to_the_canonical_stored_unit(ingested):
    """Candidate retrieval, then re-resolution from the database by identity."""
    outcome, _, connection = ingested
    index = LexicalEvidenceIndex()
    index.add_all(outcome.evidence_units)

    candidates = index.search("junction capacitance reverse bias", project_id=PROJECT, limit=5)
    assert candidates

    resolved, divergences = CandidateResolver(_load_unit(connection)).resolve(
        candidates, index=index
    )
    assert resolved, "no candidate resolved back to a stored unit"
    assert divergences == ()
    for entry in resolved:
        stored = connection.execute(
            "SELECT body FROM evidence_units WHERE evidence_unit_id = %s",
            (entry.candidate.evidence_unit_id,),
        ).fetchone()
        assert stored is not None and entry.body == stored[0]


def test_a_tampered_candidate_cannot_alter_the_stored_evidence_body(ingested):
    """The attack, end to end and against the database."""
    outcome, _, connection = ingested
    index = LexicalEvidenceIndex()
    index.add_all(outcome.evidence_units)

    target = next(
        unit.evidence_unit_id for unit in outcome.evidence_units if RESULT_SENTENCE in unit.body
    )
    forged = "The junction capacitance increased to 9.999 pF/mm."
    index.tamper(target, forged)

    resolved, divergences = CandidateResolver(_load_unit(connection)).resolve(
        index.search("junction capacitance", project_id=PROJECT, limit=10), index=index
    )
    bodies = {entry.candidate.evidence_unit_id: entry.body for entry in resolved}
    assert forged not in bodies.get(target, "")
    assert RESULT_SENTENCE in bodies[target]
    assert any(divergence.evidence_unit_id == target for divergence in divergences)


def test_admission_refuses_a_body_that_is_not_the_stored_one(ingested):
    """The admission gate, wired to the database loader and to the real read gate."""
    outcome, _, connection = ingested
    target = outcome.evidence_units[0].evidence_unit_id

    actor = Actor(actor_id=ACTOR, actor_type=ActorType.HUMAN, display_name="Test")
    membership = ProjectMembership(
        actor_id=ACTOR,
        project_id=PROJECT,
        role="researcher",
        sensitivity_clearance=frozenset({SensitivityLabel.INTERNAL}),
    )

    def can_read(artifact_id: str, project_id: str) -> bool:
        row = connection.execute(
            "SELECT artifact_id, project_id, sensitivity_label, ingested_by_actor_id, ingested_at "
            "FROM artifact_occurrences WHERE artifact_id = %s AND project_id = %s",
            (artifact_id, project_id),
        ).fetchone()
        occurrence = None
        if row is not None:
            from lab_brain.core.models import ArtifactOccurrence

            occurrence = ArtifactOccurrence(
                artifact_id=row[0],
                project_id=row[1],
                sensitivity_label=SensitivityLabel(row[2]),
                ingested_by_actor_id=row[3],
                ingested_at=row[4],
            )
        return bool(can_read_artifact(actor, artifact_id, project_id, occurrence, membership))

    gate = EvidenceAdmissionGate(
        load_artifact=lambda _: None,
        load_evidence_unit=_load_unit(connection),
        can_read=can_read,
    )
    attestation = Attestation(
        claim_id="clm:cj-falls",
        epistemic_type=EpistemicType.REPORTED,
        source_work_id="swk:rs-anomaly-report",
        locator="§3",
        conditions={},
        conditions_schema_version=TOY_SCHEMA_REF,
        project_id=PROJECT,
        extractor_version="1.0.0",
        extraction_provenance=ExtractionProvenance(
            extractor_id="local_markdown", extractor_version="1.0.0"
        ),
    )

    with pytest.raises(AdmissionRefusal) as caught:
        gate.admit(
            AdmissionRequest(
                attestation=attestation,
                evidence_unit_id=target,
                claimed_body="Something the document does not say.",
            )
        )
    assert caught.value.reason is RefusalReason.EVIDENCE_BODY_NOT_CANONICAL

    # The positive control, through the same real read gate.
    admitted = gate.admit(
        AdmissionRequest(
            attestation=attestation,
            evidence_unit_id=target,
            claimed_body=_load_unit(connection)(target).body,
        )
    )
    assert admitted is attestation


def test_the_project_acl_is_enforced_on_the_new_read_path(ingested):
    """R-7's closing condition: a caller exists and is tested end to end.

    An actor with a membership of another project reaches the same admission path and is refused
    by ``can_read_artifact`` -- the existing gate, not a second copy.
    """
    outcome, _, connection = ingested
    target = outcome.evidence_units[0].evidence_unit_id

    outsider = Actor(actor_id="act:outsider", actor_type=ActorType.HUMAN, display_name="Out")
    elsewhere = ProjectMembership(
        actor_id="act:outsider",
        project_id=OTHER_PROJECT,
        role="researcher",
        sensitivity_clearance=frozenset({SensitivityLabel.INTERNAL}),
    )

    decision = can_read_artifact(outsider, outcome.artifact.artifact_id, PROJECT, None, elsewhere)
    assert not decision.allowed
    assert "not a member" in decision.reason

    gate = EvidenceAdmissionGate(
        load_artifact=lambda _: None,
        load_evidence_unit=_load_unit(connection),
        can_read=lambda artifact_id, project_id: bool(
            can_read_artifact(outsider, artifact_id, project_id, None, elsewhere)
        ),
    )
    attestation = Attestation(
        claim_id="clm:cj-falls",
        epistemic_type=EpistemicType.REPORTED,
        source_work_id="swk:rs-anomaly-report",
        locator="§3",
        conditions={},
        conditions_schema_version=TOY_SCHEMA_REF,
        project_id=PROJECT,
        extractor_version="1.0.0",
        extraction_provenance=ExtractionProvenance(
            extractor_id="local_markdown", extractor_version="1.0.0"
        ),
    )
    with pytest.raises(AdmissionRefusal) as caught:
        gate.admit(AdmissionRequest(attestation=attestation, evidence_unit_id=target))
    assert caught.value.reason is RefusalReason.READ_NOT_PERMITTED


def test_a_failed_promotion_leaves_no_row_in_postgresql(db, tmp_path):
    """OPS-004 against a real transaction rather than a stand-in.

    The in-memory tests prove the pipeline calls the compensator; this proves the compensator
    actually removes the rows from PostgreSQL, which is the half a fake cannot establish.
    """

    class _FailingStore(LocalArtifactStore):
        def promote(self, staging_id: str, content_hash: str) -> str:
            raise RuntimeError("injected promotion failure")

    store = _FailingStore(tmp_path / "artifacts")
    pipeline = IngestionPipeline(store, _commit_rows(db), _rollback_rows(db))

    before = db.execute("SELECT count(*) FROM artifacts").fetchone()[0]
    with pytest.raises(IngestionError, match="no dangling reference remains"):
        pipeline.ingest(
            fixture_bytes(),
            project_id=PROJECT,
            actor_id=ACTOR,
            sensitivity_label=SensitivityLabel.INTERNAL,
            uri="file:///rs_anomaly_report.md",
        )

    assert db.execute("SELECT count(*) FROM artifacts").fetchone()[0] == before
    assert db.execute("SELECT count(*) FROM artifact_occurrences").fetchone()[0] == 0
    assert store.list_staged() == ()


def test_a_stored_unit_that_severs_its_condition_is_rejected_by_postgresql(ingested):
    """The rule 1 trigger, reached through the same table the vertical writes to."""
    outcome, _, connection = ingested
    unit = outcome.evidence_units[0]
    with pytest.raises(psycopg.errors.CheckViolation, match="separated from what makes it"):
        connection.execute(
            "UPDATE evidence_units SET bound_condition_texts = %s WHERE evidence_unit_id = %s",
            (["A condition this unit does not contain at all."], unit.evidence_unit_id),
        )
