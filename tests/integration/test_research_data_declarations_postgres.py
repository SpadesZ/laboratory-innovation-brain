"""`012g`: what a researcher declared about research data -- stored as declared, and only so.

The declaration is bound to the ingestion item it describes: the same project, the same submitter,
one of the three kinds a researcher may declare, one of the four labels, and never changed after
the fact. The file, its artifact and its evidence live where every ingestion puts them; this table
holds none of it.
"""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from lab_brain.composition import IngestionService
from lab_brain.core.models.enums import SensitivityLabel, TrustClass
from lab_brain.research.data import NewFile, ResearchData
from lab_brain.storage.artifacts.local import LocalArtifactStore

pytestmark = pytest.mark.postgres

REPORT = Path(__file__).resolve().parents[2] / "fixtures" / "evidence" / "rs_anomaly_report.md"


def _item(db, tmp_path: Path) -> str:  # type: ignore[no-untyped-def]
    db.execute(
        "INSERT INTO project_memberships (actor_id, project_id, role, sensitivity_clearance,"
        " approval_scopes, active) VALUES ('act:test', 'prj:test', 'RESEARCHER',"
        " ARRAY['PUBLIC', 'INTERNAL'], ARRAY[]::text[], TRUE)"
    )
    data = ResearchData(connection=db, artifact_store=LocalArtifactStore(tmp_path.resolve()))
    (item,) = data.add(
        project_id="prj:test",
        actor_id="act:test",
        files=[NewFile(REPORT.name, REPORT.read_bytes(), "text/markdown")],
        kind=TrustClass.INTERNAL_MEASUREMENT,
        sensitivity=SensitivityLabel.INTERNAL,
    )
    return item


def _declare(db, item: str, **overrides: str) -> None:  # type: ignore[no-untyped-def]
    row = {
        "project_id": "prj:test",
        "actor_id": "act:test",
        "declared_kind": "EXPERT_HEURISTIC",
        "declared_label": "PUBLIC",
        "file_name": "again.md",
        **overrides,
    }
    db.execute(
        "INSERT INTO research_data_declarations (item_id, project_id, actor_id, declared_kind,"
        " declared_label, file_name, declared_at) VALUES (%s, %s, %s, %s, %s, %s, now())",
        (
            item,
            row["project_id"],
            row["actor_id"],
            row["declared_kind"],
            row["declared_label"],
            row["file_name"],
        ),
    )


def test_a_declaration_is_what_was_declared_and_is_never_changed(db, tmp_path):
    item = _item(db, tmp_path)
    assert db.execute(
        "SELECT declared_kind, declared_label, file_name FROM research_data_declarations"
        " WHERE item_id = %s",
        (item,),
    ).fetchone() == ("INTERNAL_MEASUREMENT", "INTERNAL", REPORT.name)
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        db.execute(
            "UPDATE research_data_declarations SET declared_kind = 'EXPERT_HEURISTIC'"
            " WHERE item_id = %s",
            (item,),
        )
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        db.execute("DELETE FROM research_data_declarations WHERE item_id = %s", (item,))
    with pytest.raises(psycopg.errors.UniqueViolation):
        _declare(db, item)


def test_a_declaration_belongs_to_its_items_project_and_submitter(db, tmp_path):
    item = _item(db, tmp_path)
    db.execute("INSERT INTO projects (project_id, name) VALUES ('prj:else', 'Else')")
    db.execute(
        "INSERT INTO actors (actor_id, actor_type, display_name) VALUES ('act:else', 'HUMAN', 'E')"
    )
    # An item imported without a declaration (as the CLI and the inbox import one).
    service = IngestionService(connection=db, artifact_store=LocalArtifactStore(tmp_path.resolve()))
    job = service.submit(
        project_id="prj:test", actor_id="act:test", idempotency_key="k:plain", trace_id="trc:plain"
    )
    plain = service.ingest(
        b"# Plain\n\nA note that was imported without any declaration.\n",
        job_id=job.job_id,
        actor_id="act:test",
        sensitivity_label=SensitivityLabel.INTERNAL,
        uri="inbox:plain.md",
    ).outcome.item_id
    with pytest.raises(psycopg.errors.RaiseException, match="belongs to project"):
        _declare(db, plain, project_id="prj:else")
    with pytest.raises(psycopg.errors.RaiseException, match="only its submitter declares it"):
        _declare(db, plain, actor_id="act:else")
    with pytest.raises(psycopg.errors.CheckViolation):
        _declare(db, plain, declared_kind="LLM_INFERENCE")
    with pytest.raises(psycopg.errors.CheckViolation):
        _declare(db, plain, declared_label="SECRET")
    with pytest.raises(psycopg.errors.CheckViolation):
        _declare(db, plain, file_name="  ")
    _declare(db, plain)
    assert item != plain
