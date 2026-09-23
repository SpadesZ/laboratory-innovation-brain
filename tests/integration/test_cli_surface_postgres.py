"""T-UX-001 / T-UX-003 — the CLI over durable `012` rows, through the real `main()`.

WHAT WAS MISSING, AND WHY TESTING `run_inbox` DID NOT COVER IT.

`012` created `ingestion_items`, `ingestion_stage_results` and `error_records`. The UX projections
were tested against items a test constructed. `lab-brain inbox` printed a wiring message and
exited 2. So three separate things were true and the composition of them was not:

    the projection is correct        proven, against constructed items
    the schema holds its invariants  proven, against hand-written rows
    a production writer exists       NOT proven -- nothing wrote one
    the command can reach them       NOT proven -- it opened no connection

A test calling `run_inbox(items, out=...)` exercises the third argument of the second function in
the presentation layer. It cannot fail when there is no writer and cannot fail when there is no
connection, which is exactly what was broken. **These probes call `main()`.**

WHY `env` AND `connect` ARE PARAMETERS OF `main`. So a test can drive the real entry point
without mutating `os.environ` and hoping a teardown runs. The connection is still opened by
`main` from the DSN -- handing it an already-open one would test everything except the wiring.
"""

from __future__ import annotations

import datetime as dt
import io

import pytest

from lab_brain.composition import IngestionService
from lab_brain.core.models.enums import SensitivityLabel
from lab_brain.interfaces.cli import main
from lab_brain.interfaces.config import DSN_VARIABLE, ConfigurationError, read_settings
from lab_brain.storage.artifacts.local import LocalArtifactStore
from lab_brain.surface.disclosure import VIEW_TECHNICAL_SCOPE
from lab_brain.surface.ingestion_item import ItemState, derive_state
from tests.evidence_fixtures import fixture_bytes
from tests.postgres_fixtures import database_url

pytestmark = [pytest.mark.postgres]

PROJECT = "prj:test"
OTHER = "prj:other"
ACTOR = "act:test"
SUPPORT = "act:support"
OUTSIDER = "act:outsider"
TRACE = "trc:cli"
NOW = dt.datetime(2026, 9, 23, 9, 0, tzinfo=dt.UTC)


def env() -> dict[str, str]:
    return {DSN_VARIABLE: database_url()}


@pytest.fixture
def ingested(db, tmp_path):
    """A real ingestion, so the rows the CLI reads were written by production code."""
    for actor_id in (SUPPORT, OUTSIDER):
        db.execute(
            "INSERT INTO actors (actor_id, actor_type, display_name, active) "
            "VALUES (%s, 'HUMAN', %s, TRUE) ON CONFLICT DO NOTHING",
            (actor_id, actor_id),
        )
    db.execute(
        "INSERT INTO project_memberships (actor_id, project_id, role, sensitivity_clearance, "
        "approval_scopes, active) VALUES (%s, %s, 'RESEARCHER', ARRAY['INTERNAL'], "
        "ARRAY[]::text[], TRUE)",
        (ACTOR, PROJECT),
    )
    db.execute(
        "INSERT INTO project_memberships (actor_id, project_id, role, sensitivity_clearance, "
        "approval_scopes, active) VALUES (%s, %s, 'SUPPORT', ARRAY['INTERNAL'], %s, TRUE)",
        (SUPPORT, PROJECT, [VIEW_TECHNICAL_SCOPE]),
    )

    svc = IngestionService(
        connection=db, artifact_store=LocalArtifactStore(tmp_path), clock=lambda: NOW
    )
    job = svc.submit(project_id=PROJECT, actor_id=ACTOR, idempotency_key="idem:cli", trace_id=TRACE)
    result = svc.ingest(
        fixture_bytes(),
        job_id=job.job_id,
        actor_id=ACTOR,
        sensitivity_label=SensitivityLabel.INTERNAL,
        uri="file:///rs_anomaly_report.md",
    )
    assert result.succeeded
    return db, svc, result


# ---------------------------------------------------------------------------
# UX-001 — the inbox, end to end
# ---------------------------------------------------------------------------


@pytest.mark.requirement("UX-001")
@pytest.mark.spec_test("T-UX-001")
def test_production_ingestion_writes_the_rows_the_inbox_reads(ingested):
    """The writer half. One ingestion, one item, one stage row per stage that ran."""
    db, _svc, result = ingested

    items = db.execute(
        "SELECT item_id, project_id, trace_id, raw_artifact_id, source_kind FROM ingestion_items"
    ).fetchall()
    assert items == [
        (result.outcome.item_id, PROJECT, TRACE, result.artifact.artifact_id, "UPLOAD")
    ]

    stages = dict(
        db.execute(
            "SELECT stage, status FROM ingestion_stage_results WHERE item_id = %s",
            (result.outcome.item_id,),
        ).fetchall()
    )
    assert stages, "the ingestion recorded no stage results"
    assert stages["RAW_STORE"] == "SUCCEEDED"
    assert stages["SEGMENT"] == "SUCCEEDED"


@pytest.mark.requirement("UX-001")
@pytest.mark.spec_test("T-UX-001")
def test_the_inbox_has_no_stored_state_to_read(ingested):
    """§17.22, structurally. There is no column, so there is nothing to return.

    The strongest form of "state is derived": not that the reader computes it, but that a reader
    that wanted to shortcut could not. A UI's first instinct when a derivation is inconvenient is
    to write the answer down.
    """
    db, svc, _result = ingested
    columns = {
        row[0]
        for row in db.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'ingestion_items'"
        ).fetchall()
    }
    assert "state" not in columns

    item = svc.inbox(PROJECT)[0]
    assert not hasattr(item, "state")
    assert derive_state(item) is ItemState.READY


@pytest.mark.requirement("UX-001")
@pytest.mark.spec_test("T-UX-001")
def test_the_real_command_loads_durable_rows_and_renders_derived_state(ingested):
    """THE end-to-end probe: production ingestion -> durable rows -> new connection -> `main`.

    `main` opens its own connection from the DSN, which is what a separate process does. Nothing
    in this test hands it a live object.
    """
    _db, _svc, result = ingested
    out = io.StringIO()
    assert main(["inbox", "--project", PROJECT, "--actor", ACTOR], out=out, env=env()) == 0

    printed = out.getvalue()
    assert result.outcome.item_id in printed
    assert "READY" in printed
    assert "READY=1" in printed, "the summary line is missing or counted the wrong state"
    for state in ("BLOCKED=0", "FAILED=0", "PARTIAL=0"):
        assert state in printed, "zero counts are information and must be printed"


@pytest.mark.requirement("UX-001")
@pytest.mark.spec_test("T-UX-001")
def test_a_failed_parse_shows_as_failed_through_the_real_command(db, tmp_path):
    """The derivation is real, not a constant. Same command, different rows, different answer."""
    db.execute(
        "INSERT INTO project_memberships (actor_id, project_id, role, sensitivity_clearance, "
        "approval_scopes, active) VALUES (%s, %s, 'RESEARCHER', ARRAY['INTERNAL'], "
        "ARRAY[]::text[], TRUE)",
        (ACTOR, PROJECT),
    )
    svc = IngestionService(
        connection=db, artifact_store=LocalArtifactStore(tmp_path), clock=lambda: NOW
    )

    class _Broken:
        def parse(self, *_a, **_k):
            raise RuntimeError("figure extraction timed out")

    svc._pipeline._parser = _Broken()
    job = svc.submit(
        project_id=PROJECT, actor_id=ACTOR, idempotency_key="idem:broken", trace_id=TRACE
    )
    result = svc.ingest(
        fixture_bytes(),
        job_id=job.job_id,
        actor_id=ACTOR,
        sensitivity_label=SensitivityLabel.INTERNAL,
        uri="file:///broken.md",
    )

    out = io.StringIO()
    assert main(["inbox", "--project", PROJECT, "--actor", ACTOR], out=out, env=env()) == 0
    printed = out.getvalue()
    assert "FAILED=1" in printed
    assert "READY=0" in printed
    # The ErrorRecord the failure projected is quoted on the row, because that is what a user
    # passes to `explain`.
    errors = svc.inbox(PROJECT)[0].error_ids
    assert errors and errors[0] in printed
    assert not result.succeeded


@pytest.mark.requirement("UX-001")
@pytest.mark.spec_test("T-UX-001")
def test_the_inbox_shows_only_this_projects_rows(ingested, tmp_path):
    """SEC-002 at the surface. A project's inbox is its own."""
    db, _svc, result = ingested
    db.execute(
        "INSERT INTO projects (project_id, name) VALUES (%s, 'Other') ON CONFLICT DO NOTHING",
        (OTHER,),
    )
    db.execute(
        "INSERT INTO project_memberships (actor_id, project_id, role, sensitivity_clearance, "
        "approval_scopes, active) VALUES (%s, %s, 'RESEARCHER', ARRAY['INTERNAL'], "
        "ARRAY[]::text[], TRUE)",
        (ACTOR, OTHER),
    )
    out = io.StringIO()
    assert main(["inbox", "--project", OTHER, "--actor", ACTOR], out=out, env=env()) == 0
    assert result.outcome.item_id not in out.getvalue()
    assert "READY=0" in out.getvalue()


# ---------------------------------------------------------------------------
# UX-003 — explain, through the real command
# ---------------------------------------------------------------------------


def _failed_error_id(db, tmp_path) -> tuple[str, IngestionService]:
    db.execute(
        "INSERT INTO project_memberships (actor_id, project_id, role, sensitivity_clearance, "
        "approval_scopes, active) VALUES (%s, %s, 'RESEARCHER', ARRAY['INTERNAL'], "
        "ARRAY[]::text[], TRUE)",
        (ACTOR, PROJECT),
    )
    db.execute(
        "INSERT INTO actors (actor_id, actor_type, display_name, active) "
        "VALUES (%s, 'HUMAN', 'Support', TRUE) ON CONFLICT DO NOTHING",
        (SUPPORT,),
    )
    db.execute(
        "INSERT INTO project_memberships (actor_id, project_id, role, sensitivity_clearance, "
        "approval_scopes, active) VALUES (%s, %s, 'SUPPORT', ARRAY['INTERNAL'], %s, TRUE)",
        (SUPPORT, PROJECT, [VIEW_TECHNICAL_SCOPE]),
    )
    svc = IngestionService(
        connection=db, artifact_store=LocalArtifactStore(tmp_path), clock=lambda: NOW
    )

    class _Broken:
        def parse(self, *_a, **_k):
            raise RuntimeError("NDA-2026-117 sidewall angle extraction failed")

    svc._pipeline._parser = _Broken()
    job = svc.submit(
        project_id=PROJECT, actor_id=ACTOR, idempotency_key="idem:explain", trace_id=TRACE
    )
    svc.ingest(
        fixture_bytes(),
        job_id=job.job_id,
        actor_id=ACTOR,
        sensitivity_label=SensitivityLabel.INTERNAL,
        uri="file:///broken.md",
    )
    errors = svc.inbox(PROJECT)[0].error_ids
    assert errors, "the failed parse projected no ErrorRecord"
    return errors[0], svc


@pytest.mark.requirement("UX-003")
@pytest.mark.spec_test("T-UX-003")
def test_explain_resolves_a_durable_error_and_prints_catalog_text(db, tmp_path):
    """The reference is `ERR-YYYYMMDD-NNNN`, which is the point: a human quotes it.

    Nothing model-generated reaches this output (§17.24) -- every line is a catalog entry keyed
    on `reason_code` or a trace reference from the row.
    """
    error_id, _svc = _failed_error_id(db, tmp_path)
    assert error_id.startswith("ERR-")

    out = io.StringIO()
    assert (
        main(["explain", error_id, "--project", PROJECT, "--actor", ACTOR], out=out, env=env()) == 0
    )
    printed = out.getvalue()
    assert error_id in printed
    assert TRACE in printed
    assert "Traceback" not in printed
    assert "NDA-2026-117" not in printed, "the raw failure text reached a default payload"


@pytest.mark.requirement("UX-003")
@pytest.mark.spec_test("T-UX-003")
def test_technical_detail_still_requires_the_scope_through_the_real_command(db, tmp_path):
    """§17.24: expansion is an authorization decision, checked server-side.

    `--technical` ASKS. The researcher holds no scope and is told there is more without being
    told what; the support actor holds the scope and gets the same payload plus whatever detail
    the store resolves -- which at M1 is none, and is reported as such rather than invented.
    """
    error_id, _svc = _failed_error_id(db, tmp_path)

    denied = io.StringIO()
    assert (
        main(
            ["explain", error_id, "--project", PROJECT, "--actor", ACTOR, "--technical"],
            out=denied,
            env=env(),
        )
        == 0
    )
    assert "DIAGNOSTICS_SCOPE_REQUIRED" in denied.getvalue()

    allowed = io.StringIO()
    assert (
        main(
            ["explain", error_id, "--project", PROJECT, "--actor", SUPPORT, "--technical"],
            out=allowed,
            env=env(),
        )
        == 0
    )
    assert "DIAGNOSTICS_SCOPE_REQUIRED" not in allowed.getvalue()


@pytest.mark.requirement("UX-003")
@pytest.mark.spec_test("T-UX-003")
def test_an_unknown_and_a_foreign_error_are_indistinguishable_through_the_real_command(
    db, tmp_path
):
    """THE oracle rule, at the command. §17.24 forbids the difference.

    An attacker enumerating ids learns which exist from any distinction -- including the
    existence of an error id in a project they cannot see, which is itself information about
    which projects are active and roughly how much is failing.

    Compared after substituting the id, so the only difference that could remain is a real one.
    """
    error_id, _svc = _failed_error_id(db, tmp_path)
    db.execute(
        "INSERT INTO projects (project_id, name) VALUES (%s, 'Other') ON CONFLICT DO NOTHING",
        (OTHER,),
    )
    db.execute("UPDATE error_records SET project_id = %s WHERE error_id = %s", (OTHER, error_id))

    missing = io.StringIO()
    assert (
        main(
            ["explain", "ERR-20260101-9999", "--project", PROJECT, "--actor", ACTOR],
            out=missing,
            env=env(),
        )
        == 1
    )
    foreign = io.StringIO()
    assert (
        main(["explain", error_id, "--project", PROJECT, "--actor", ACTOR], out=foreign, env=env())
        == 1
    )

    assert missing.getvalue().replace("ERR-20260101-9999", "<id>") == foreign.getvalue().replace(
        error_id, "<id>"
    )


@pytest.mark.requirement("UX-003")
@pytest.mark.spec_test("T-UX-003")
def test_a_non_member_gets_the_same_not_found(db, tmp_path):
    """Membership is checked BEFORE the lookup, so the response time does not differ either."""
    error_id, _svc = _failed_error_id(db, tmp_path)
    out = io.StringIO()
    assert (
        main(["explain", error_id, "--project", PROJECT, "--actor", OUTSIDER], out=out, env=env())
        == 1
    )
    assert "No such error reference" in out.getvalue()


# ---------------------------------------------------------------------------
# The configuration boundary
# ---------------------------------------------------------------------------


def test_the_command_refuses_to_guess_a_connection():
    """No default DSN. A command that quietly connected somewhere plausible would eventually
    report on the wrong database, confidently, and the report would look fine."""
    out = io.StringIO()
    assert main(["inbox", "--project", PROJECT, "--actor", ACTOR], out=out, env={}) == 2
    assert DSN_VARIABLE in out.getvalue()

    with pytest.raises(ConfigurationError):
        read_settings({})
    with pytest.raises(ConfigurationError):
        read_settings({DSN_VARIABLE: "   "})


def test_importing_the_cli_opens_no_connection():
    """Nothing connects at import time.

    `--help` must not need a database and importing this module must not either -- which is also
    what keeps every test that touches the CLI from becoming a database test.
    """
    import importlib
    import sys

    for name in ("lab_brain.interfaces.cli", "lab_brain.interfaces.config"):
        sys.modules.pop(name, None)
    module = importlib.import_module("lab_brain.interfaces.config")
    assert "psycopg" not in dir(module), "the driver is imported at module level"

    parser = importlib.import_module("lab_brain.interfaces.cli").build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--help"])
