"""A scientific record cites only its own project's records (`012s`).

Data-organization audit 2026-10-15, F-03: references between scientific rows were checked for
existence, globally, or not at all, so a record in one project could rest on another project's
material. Two projects here, each holding its own artifact, run, attestation and inference, and
every reference below is tried both ways:

    observation     its run and its artifact are its project's
    attestation     its observation, artifact and run are its project's
    relation        every supporting attestation and its inference are its project's, and exist
    bundle member   an attestation of the bundle's project (a missing one is the foreign key's)
    heuristic       every source artifact and source episode is its project's
    update          moving a reference elsewhere is refused like writing it there
    history         `provenance_scope_violations` lists stored rows that break a rule
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import psycopg
import pytest

from lab_brain.cognition.llm import ScientificOutput
from lab_brain.core.models.inference import InferenceProvenance, LogicalSlot
from lab_brain.core.models.job import JobState
from lab_brain.core.repositories.inference import SqlInferenceProvenanceStore
from lab_brain.core.repositories.jobs import SqlJobStore
from tests.conftest_fixtures import make_artifact
from tests.job_fixtures import at, make_job, make_run
from tests.postgres_fixtures import place_artifact

pytestmark = pytest.mark.postgres

MINE = "prj:test"
THEIRS = "prj:other"
SCHEMA = "core/sch_scope@1.0.0"
T0 = dt.datetime(2026, 10, 19, 9, 0, tzinfo=dt.UTC)
PROVENANCE = '{"extractor_id": "ext:test", "extractor_version": "1.0.0"}'


def _artifact(db: Any, project: str) -> str:
    artifact = make_artifact(f"material held by {project}".encode())
    db.execute(
        "INSERT INTO artifacts (artifact_id, content_hash, uri, media_type, source_origin,"
        " lineage_id, lineage_revision) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            artifact.artifact_id,
            artifact.content_hash,
            artifact.uri,
            artifact.media_type,
            artifact.source_origin.value,
            artifact.lineage_id,
            artifact.lineage_revision,
        ),
    )
    place_artifact(db, artifact.artifact_id, project_id=project)
    return artifact.artifact_id


def _run(db: Any, project: str) -> str:
    jobs = SqlJobStore(db)
    job_id, run_id = f"job:{project}", f"run:{project}"
    jobs.submit(make_job(job_id, project_id=project))
    jobs.transition(job_id, JobState.RUNNING, at(1))
    jobs.complete(job_id, "idem:1", make_run(run_id, job_id=job_id, project_id=project))
    return run_id


def _inference(db: Any, project: str) -> str:
    inference_id = f"inf:{project}"
    SqlInferenceProvenanceStore(db).record(
        ScientificOutput(
            text="a judgment a model proposed",
            provenance=InferenceProvenance(
                inference_id=inference_id,
                role="relation_judge",
                logical_slot=LogicalSlot.RELATION,
                model_id="toy-model",
                model_version="1.0.0",
                prompt_id="prm:relation",
                prompt_version="1.0.0",
                evidence_bundle_hash="sha256:" + "c" * 64,
                created_at=T0,
                trace_id="trc:scope",
            ),
        ),
        project_id=project,
    )
    return inference_id


def _observation(db: Any, observation_id: str, project: str, **refs: str | None) -> None:
    db.execute(
        "INSERT INTO observations (observation_id, run_id, artifact_id, metric_or_event,"
        " conditions_schema_version, method_ref, project_id)"
        " VALUES (%s, %s, %s, 'toy_metric', %s, 'toy@1.0.0', %s)",
        (observation_id, refs.get("run_id"), refs.get("artifact_id"), SCHEMA, project),
    )


def _attestation(db: Any, attestation_id: str, project: str, **refs: str | None) -> None:
    observation_id = refs.get("observation_id")
    db.execute(
        "INSERT INTO attestations (attestation_id, claim_id, observation_id, epistemic_type,"
        " source_artifact_id, run_id, locator, conditions_schema_version, project_id,"
        " extractor_version, extraction_provenance)"
        " VALUES (%s, %s, %s, 'REPORTED', %s, %s, 'p.1', %s, %s, '1.0.0', %s::jsonb)",
        (
            attestation_id,
            None if observation_id else "clm:scope",
            observation_id,
            refs.get("source_artifact_id"),
            refs.get("run_id"),
            SCHEMA,
            project,
            PROVENANCE,
        ),
    )


def _relation(
    db: Any, relation_id: str, *, support: list[str], inference: str | None = None
) -> None:
    db.execute(
        "INSERT INTO relation_judgments (relation_id, from_entity_id, to_entity_id, relation_type,"
        " supporting_attestation_ids, inference_provenance_id, actor_id, project_id)"
        " VALUES (%s, 'swk:a', 'swk:b', 'CITES', %s, %s, 'act:test', %s)",
        (relation_id, support, inference, MINE),
    )


def _bundle(db: Any, bundle_id: str, *members: str) -> None:
    db.execute(
        "INSERT INTO evidence_bundles (bundle_id, schema_version, research_intent, stakes,"
        " query_text, query_hash, source_policy_id, source_policy_version, condition_filter,"
        " condition_schema_versions, project_id, canonical_hash)"
        " VALUES (%s, 1, 'DIAGNOSIS', 'HIGH', 'q', %s, 'sp:diagnosis', '1.0.0', '{}'::jsonb,"
        " '{}'::jsonb, %s, %s)",
        (bundle_id, "sha256:" + "d" * 64, MINE, "sha256:" + "e" * 64),
    )
    for position, member in enumerate(members):
        db.execute(
            "INSERT INTO evidence_bundle_members (bundle_id, position, attestation_id)"
            " VALUES (%s, %s, %s)",
            (bundle_id, position, member),
        )


def _candidate(db: Any, candidate_id: str, *, artifacts: list[str], episodes: list[str]) -> None:
    db.execute(
        "INSERT INTO candidate_heuristics (candidate_id, project_id, trigger_pattern,"
        " suggested_checks, rationale, source_artifact_ids, source_locators, source_episode_ids,"
        " miner_model_version, status, derived_from_failures, created_at)"
        " VALUES (%s, %s, 'a recurring pattern', ARRAY['check the contact'], 'seen twice', %s,"
        " ARRAY['p.1'], %s, 'miner@1.0.0', 'PENDING_REVIEW', ARRAY['fan:none'], %s)",
        (candidate_id, MINE, artifacts, episodes, T0),
    )


@pytest.fixture
def world(db: Any) -> dict[str, Any]:
    """Two projects, each with its own artifact, run, observation, attestation and inference."""
    db.execute("INSERT INTO projects (project_id, name) VALUES (%s, 'Other')", (THEIRS,))
    db.execute(
        "INSERT INTO condition_schemas (domain, schema_id, version, json_schema,"
        " comparator_version) VALUES ('core', 'sch_scope', '1.0.0',"
        ' \'{"type": "object", "properties": {}}\'::jsonb, \'1.0.0\')'
    )
    db.execute("INSERT INTO claims (claim_id, normalized_proposition) VALUES ('clm:scope', 'p')")
    refs: dict[str, Any] = {"db": db}
    for side, project in (("mine", MINE), ("theirs", THEIRS)):
        artifact = _artifact(db, project)
        run = _run(db, project)
        # One origin each (`observations_exactly_one_origin`): the artifact, and the run.
        _observation(db, f"obs:{side}", project, artifact_id=artifact)
        _observation(db, f"obs:{side}:run", project, run_id=run)
        _attestation(db, f"att:{side}", project, source_artifact_id=artifact)
        refs[side] = {
            "artifact": artifact,
            "run": run,
            "observation": f"obs:{side}",
            "attestation": f"att:{side}",
            "inference": _inference(db, project),
        }
        db.execute(
            "INSERT INTO research_episodes (episode_id, project_id, trace_id, goal, start_time)"
            " VALUES (%s, %s, 'trc:scope', 'g', %s)",
            (f"epi:{side}", project, T0),
        )
        refs[side]["episode"] = f"epi:{side}"
    return refs


def _refused(match: str) -> Any:
    return pytest.raises(psycopg.errors.RaiseException, match=match)


def test_an_observation_names_only_its_projects_run_and_artifact(world):
    db, theirs = world["db"], world["theirs"]
    with _refused(r"names run run:prj:other, which is not a run of prj:test"):
        _observation(db, "obs:x", MINE, run_id=theirs["run"])
    with _refused(r"names run run:nowhere, which is not a run of prj:test"):
        _observation(db, "obs:x", MINE, run_id="run:nowhere")
    with _refused(rf"names artifact {theirs['artifact']}, which has no occurrence in prj:test"):
        _observation(db, "obs:x", MINE, artifact_id=theirs["artifact"])
    _observation(db, "obs:ok", MINE, run_id=world["mine"]["run"])


def test_an_attestation_names_only_its_projects_observation_artifact_and_run(world):
    db, theirs = world["db"], world["theirs"]
    with _refused(r"names observation obs:theirs, which is not an observation of prj:test"):
        _attestation(
            db,
            "att:x",
            MINE,
            observation_id=theirs["observation"],
            source_artifact_id=world["mine"]["artifact"],
        )
    with _refused(rf"cites artifact {theirs['artifact']}, which has no occurrence in prj:test"):
        _attestation(db, "att:x", MINE, source_artifact_id=theirs["artifact"])
    with _refused(r"names run run:prj:other, which is not a run of prj:test"):
        _attestation(db, "att:x", MINE, run_id=theirs["run"])
    _attestation(
        db,
        "att:ok",
        MINE,
        observation_id=world["mine"]["observation"],
        run_id=world["mine"]["run"],
    )


def test_a_relation_rests_only_on_its_projects_attestations_and_inference(world):
    db = world["db"]
    with _refused(r"rests on \{att:theirs\}, which are not attestations of prj:test"):
        _relation(db, "rel:x", support=["att:mine", "att:theirs"])
    with _refused(r"rests on \{att:nowhere\}, which are not attestations of prj:test"):
        _relation(db, "rel:x", support=["att:nowhere"])
    with _refused(r"names inference inf:prj:other, which is not an inference of prj:test"):
        _relation(db, "rel:x", support=[], inference=world["theirs"]["inference"])
    with _refused(r"names inference inf:nowhere, which is not an inference of prj:test"):
        _relation(db, "rel:x", support=[], inference="inf:nowhere")
    _relation(db, "rel:ok", support=["att:mine"], inference=world["mine"]["inference"])


def test_a_bundle_holds_only_its_projects_attestations(world):
    db = world["db"]
    with _refused(r"bundle bdl:x cannot hold attestation att:theirs"):
        _bundle(db, "bdl:x", "att:mine", "att:theirs")
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        _bundle(db, "bdl:y", "att:nowhere")
    _bundle(db, "bdl:ok", "att:mine")


def test_a_candidate_heuristic_cites_only_its_projects_sources(world):
    db, mine, theirs = world["db"], world["mine"], world["theirs"]
    with _refused(rf"cites artifacts \{{{theirs['artifact']}\}} with no occurrence in prj:test"):
        _candidate(db, "chc:x", artifacts=[theirs["artifact"]], episodes=[mine["episode"]])
    with _refused(r"cites episodes \{epi:theirs\} that are not episodes of prj:test"):
        _candidate(db, "chc:x", artifacts=[mine["artifact"]], episodes=[theirs["episode"]])
    # Its own sources pass this rule, and the next one (`011l`: confirmed failures) is reached.
    with _refused(r"is not a CONFIRMED failure analysis of prj:test"):
        _candidate(db, "chc:x", artifacts=[mine["artifact"]], episodes=[mine["episode"]])


@pytest.mark.parametrize(
    ("table", "assignment", "refusal"),
    [
        ("observations", "artifact_id", "has no occurrence in prj:test"),
        ("observations", "run_id", "is not a run of prj:test"),
        ("attestations", "source_artifact_id", "has no occurrence in prj:test"),
    ],
)
def test_a_reference_moved_to_another_project_is_refused(world, table, assignment, refusal):
    db, theirs = world["db"], world["theirs"]
    value = theirs["run"] if assignment == "run_id" else theirs["artifact"]
    key = {
        "artifact_id": "observation_id = 'obs:mine'",
        "run_id": "observation_id = 'obs:mine:run'",
        "source_artifact_id": "attestation_id = 'att:mine'",
    }[assignment]
    with _refused(refusal):
        db.execute(f"UPDATE {table} SET {assignment} = %s WHERE {key}", (value,))


def test_the_view_lists_stored_rows_that_break_a_rule(world):
    db, theirs = world["db"], world["theirs"]
    assert db.execute("SELECT count(*) FROM provenance_scope_violations").fetchone() == (0,)
    # As a writer before `012s` could store them: past every trigger.
    db.execute("SET session_replication_role = replica")
    try:
        _attestation(db, "att:history", MINE, source_artifact_id=theirs["artifact"])
        _relation(db, "rel:history", support=["att:theirs"], inference="inf:nowhere")
    finally:
        db.execute("SET session_replication_role = origin")
    rows = db.execute(
        "SELECT record_kind, record_id, project_id, reference_kind, reference"
        " FROM provenance_scope_violations ORDER BY record_kind, reference_kind"
    ).fetchall()
    assert [tuple(r) for r in rows] == [
        ("attestation", "att:history", MINE, "artifact", theirs["artifact"]),
        ("relation", "rel:history", MINE, "inference", "inf:nowhere"),
        ("relation", "rel:history", MINE, "supporting attestation", "att:theirs"),
    ]
