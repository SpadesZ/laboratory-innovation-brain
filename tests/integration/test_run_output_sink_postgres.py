"""A Run's raw output is stored, hashed and placed in its project before the Run exists -- and a
failure between the two stores leaves no dangling row (§25.4, OPS-004, SEC-003)."""

from __future__ import annotations

import datetime as dt
import hashlib

import pytest

from lab_brain.storage.artifacts.interface import ArtifactStoreError
from lab_brain.storage.artifacts.local import InMemoryArtifactStore
from lab_brain.storage.postgres.run_outputs import RunOutputRefused, SqlRunOutputSink

pytestmark = pytest.mark.postgres

T0 = dt.datetime(2026, 9, 27, tzinfo=dt.UTC)


class _PromoteFails(InMemoryArtifactStore):
    def promote(self, staging_id: str, content_hash: str) -> str:
        raise ArtifactStoreError("object store unavailable at promote")


def test_an_emitted_output_is_content_addressed_present_in_its_project_and_idempotent(db):
    sink = SqlRunOutputSink(connection=db, store=InMemoryArtifactStore(), now=lambda: T0)
    data = b'{"solver_id": "mock.charge.dc", "net_carrier_cm3": ["5E17"]}'
    artifact_id = sink.emit(project_id="prj:test", media_type="application/json", data=data)
    assert artifact_id == "art:sha256:" + hashlib.sha256(data).hexdigest()
    assert db.execute(
        "SELECT source_origin, secret_scan_status FROM artifacts WHERE artifact_id = %s",
        (artifact_id,),
    ).fetchone() == ("RUN_OUTPUT", "CLEAN")
    assert db.execute(
        "SELECT count(*) FROM artifact_occurrences WHERE artifact_id = %s AND project_id ="
        " 'prj:test'",
        (artifact_id,),
    ).fetchone() == (1,)
    assert sink.read(artifact_id) == data
    assert sink.emit(project_id="prj:test", media_type="application/json", data=data) == artifact_id


def test_a_promotion_failure_is_compensated_and_leaves_no_row(db):
    sink = SqlRunOutputSink(connection=db, store=_PromoteFails(), now=lambda: T0)
    with pytest.raises(ArtifactStoreError):
        sink.emit(project_id="prj:test", media_type="application/json", data=b'{"x": 1}')
    assert db.execute("SELECT count(*) FROM artifacts").fetchone() == (0,)
    assert db.execute("SELECT count(*) FROM artifact_occurrences").fetchone() == (0,)


def test_a_compensation_never_removes_rows_an_earlier_identical_emit_wrote(db):
    store = InMemoryArtifactStore()
    good = SqlRunOutputSink(connection=db, store=store, now=lambda: T0)
    data = b'{"same": "bytes"}'
    artifact_id = good.emit(project_id="prj:test", media_type="application/json", data=data)
    failing = SqlRunOutputSink(connection=db, store=_PromoteFails(), now=lambda: T0)
    with pytest.raises(ArtifactStoreError):
        failing.emit(project_id="prj:test", media_type="application/json", data=data)
    assert db.execute(
        "SELECT count(*) FROM artifacts WHERE artifact_id = %s", (artifact_id,)
    ).fetchone() == (1,)


def test_an_output_carrying_a_credential_is_refused_before_anything_is_stored(db):
    sink = SqlRunOutputSink(connection=db, store=InMemoryArtifactStore(), now=lambda: T0)
    leaked = b'{"log": "connected with AKIAABCDEFGHIJKLMNOP"}'
    with pytest.raises(RunOutputRefused, match="SEC-003"):
        sink.emit(project_id="prj:test", media_type="application/json", data=leaked)
    assert db.execute("SELECT count(*) FROM artifacts").fetchone() == (0,)
