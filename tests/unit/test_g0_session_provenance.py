"""G0-A: how a research run was started, and the session's non-secret audit reference (`011n`).

Without a database: a run's provenance is declared by every caller and never defaulted; a
WEB_SESSION run names a reference of the form the database mints and nothing shaped like a
session's lookup key; the report carries the provenance, and its Markdown names the reference
and the origin -- non-secret only. The database rules are in
`tests/e2e/test_g0_session_provenance_postgres.py`.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import importlib.util
import sys

import pytest

from lab_brain.research.continuation import ResearchRunRecord
from lab_brain.research.render import render_markdown
from lab_brain.research.report import SessionProvenance
from lab_brain.research.report_store import report_from_json, report_to_json
from lab_brain.research.run_provenance import (
    ProvenanceRefused,
    RunOrigin,
    RunProvenance,
    provenance_line,
)
from lab_brain.research.service import ResearchRequest
from lab_brain.spec import repo_root
from tests.report_samples import full_report

REF = "sar:" + "0123456789abcdef" * 2
TOKEN = "q1w2e3r4t5y6u7i8o9p0-_ZXCVBNMasdfghjkl0123456789"
SESSION_HASH = hashlib.sha256(TOKEN.encode()).hexdigest()


def test_a_web_session_run_names_a_minted_reference_and_nothing_else():
    assert RunProvenance.web_session(REF).attested
    for forged in (None, "", TOKEN, SESSION_HASH, "sar:" + SESSION_HASH, "sar:ABC", REF + "0"):
        with pytest.raises(ProvenanceRefused):
            RunProvenance(RunOrigin.WEB_SESSION, forged)


@pytest.mark.parametrize("origin", [o for o in RunOrigin if o is not RunOrigin.WEB_SESSION])
def test_every_other_origin_names_no_session_and_attests_none(origin):
    assert not RunProvenance(origin).attested
    with pytest.raises(ProvenanceRefused):
        RunProvenance(origin, REF)


def test_the_origin_is_declared_by_every_caller_never_defaulted():
    with pytest.raises(TypeError, match="provenance"):
        ResearchRequest(project_id="prj:x", actor_id="act:x", goal="why", documents=())  # type: ignore[call-arg]
    with pytest.raises(TypeError, match="provenance"):
        ResearchRunRecord(  # type: ignore[call-arg]
            research_run_id="rrn:x",
            episode_id="epi:x",
            project_id="prj:x",
            actor_id="act:x",
            ordinal=1,
            hypothesis_set_id=None,
            verification_artifact_id=None,
            symptom=None,
            expected_behavior=None,
            observed_behavior=None,
            started_at=dt.datetime(2026, 10, 28, tzinfo=dt.UTC),
        )
    with pytest.raises(ValueError):
        RunProvenance("UNKNOWN")  # type: ignore[arg-type]


def test_the_report_carries_the_provenance_and_renders_it_non_secret():
    line = provenance_line(
        RunProvenance.web_session(REF),
        actor_id="act:ada",
        project_id="prj:rs",
        research_run_id="rrn:one",
        trace_id="trc:one",
    )
    report = dataclasses.replace(
        full_report(),
        provenance=(*full_report().provenance, line),
        session_provenance=SessionProvenance(
            origin="WEB_SESSION",
            session_audit_ref=REF,
            actor_id="act:ada",
            project_id="prj:rs",
            research_run_id="rrn:one",
            trace_id="trc:one",
        ),
    )
    assert report_from_json(report_to_json(report)) == report
    text = render_markdown(report)
    assert REF in text and "WEB_SESSION" in text and "act:ada" in text and "trc:one" in text
    assert TOKEN not in text and SESSION_HASH not in text
    # A report stored before `011n` reads back with no session provenance.
    stored = report_to_json(full_report())
    stored.pop("session_provenance")
    assert report_from_json(stored).session_provenance is None


@pytest.mark.parametrize("origin", list(RunOrigin))
def test_each_origin_says_in_the_report_whether_a_session_is_attested(origin):
    ref = REF if origin is RunOrigin.WEB_SESSION else None
    line = provenance_line(
        RunProvenance(origin, ref),
        actor_id="act:a",
        project_id="prj:p",
        research_run_id="rrn:r",
        trace_id="trc:t",
    )
    assert origin.value in line and "rrn:r" in line and "trc:t" in line
    assert ("no signed-in session is attested" in line) is (origin is not RunOrigin.WEB_SESSION)


def _migrate():  # type: ignore[no-untyped-def]
    name = "lab_brain_migrate_g0_session"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, repo_root() / "scripts" / "migrate.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_the_migration_applies_right_after_011m_and_mints_in_the_database():
    order = list(_migrate().APPLY_ORDER)
    at = order.index("011n_research_session_provenance.sql")
    assert order[at - 1] == "011m_screening_repeat_by_content.sql"
    sql = (repo_root() / "migrations" / "011n_research_session_provenance.sql").read_text()
    assert "NEW.session_audit_ref := 'sar:' || replace(gen_random_uuid()" in sql
    # The research tables never gain a column holding a session's lookup key.
    assert "ADD COLUMN IF NOT EXISTS session_hash" not in sql
