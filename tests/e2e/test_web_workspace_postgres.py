"""The research workspace end to end on PostgreSQL: the product vertical through a browser.

Driven exactly as a browser drives it: pages are fetched, the form's CSRF token is read from the
page, files are uploaded as `multipart/form-data`, redirects are followed. No simulator exists here
and none is emulated. The user opens a research run from the form, reads the episode -- ingestion,
evidence, hypotheses, critique, belief, plans, completed checks, the action awaiting a person, the
blocked simulation, the conclusion, provenance -- comes back to it after the workspace restarted,
and continues the same suspended episode through the accepted continuation path.

What the page shows is checked against the rows the services wrote and against the report the run
returned (recorded as returned, `012d`): the page's report IS `report_html` of that report, and its
Markdown export IS `render_markdown` of it -- the CLI's renderer. Every refusal is checked for its
answer and for the database it leaves behind.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

import psycopg
import pytest

from lab_brain.interfaces.config import Settings
from lab_brain.interfaces.web import Workspace, allowed_hosts, pages
from lab_brain.interfaces.web.app import WITHHELD
from lab_brain.research.render import render_markdown
from lab_brain.research.report_store import report_from_json
from lab_brain.research.vertical import load_vertical_factory
from tests.e2e.test_research_continuation_postgres import CENSUS
from tests.e2e.test_research_episode_postgres import (
    ACTOR,
    CORPUS,
    GOAL,
    PROJECT,
    REPORT,
    SIMULATIONS,
    _device,
    _member,
)
from tests.postgres_fixtures import database_url
from tests.wsgi_client import Browser, Reply

pytestmark = pytest.mark.postgres

OTHER_PROJECT = "prj:other-lab"
MALLORY = "act:mallory"
COLLEAGUE = "act:colleague"
QUERY = "series resistance contact normalization reverse bias"


def _workspace(tmp_path: Path, actor: str = ACTOR) -> Browser:
    """A freshly started workspace for `actor` -- its own CSRF secret, nothing carried over."""
    return Browser(
        Workspace(
            actor_id=actor,
            settings=Settings(dsn=database_url()),
            connect=lambda s: psycopg.connect(s.dsn),
            artifact_root=tmp_path / "artifacts",
            vertical_factory=load_vertical_factory("silicon_photonics"),
            allowed_hosts=allowed_hosts("127.0.0.1", 8765),
        )
    )


def _token(page: Reply) -> str:
    found = re.search(r'name="csrf" value="([^"]+)"', page.text)
    assert found, "the page carries no form token"
    return found.group(1)


def _text(page: Reply | str) -> str:
    markup = page.text if isinstance(page, Reply) else page
    inline = re.sub(r"</?(?:code|strong|span|a)\b[^>]*>", "", markup)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", inline)).split())


def _census(db) -> dict[str, int]:  # type: ignore[no-untyped-def]
    return {
        t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        for t in (*CENSUS, "research_run_reports")
    }


def _start(
    browser: Browser,
    tmp_path: Path,
    *,
    case: str | None = "mesh-coarse-access",
    literature: bool = False,
    measurement: tuple[str, bytes] | None = None,
    goal: str = GOAL,
) -> Reply:
    """Fill in and send the new-run form as a researcher would."""
    token = _token(browser.get("/runs/new"))
    fields = {"csrf": token, "project": PROJECT, "goal": goal, "sensitivity": "INTERNAL"}
    files: dict[str, list[tuple[str, bytes]]] = {
        "measurement": [measurement or (REPORT.name, REPORT.read_bytes())]
    }
    if case is not None:
        device = _device(tmp_path, case)
        files["verification_input"] = [(device.name, device.read_bytes())]
    if literature:
        fields.update(literature_query=QUERY, literature_query_public="yes")
        files["literature_corpus"] = [(CORPUS.name, CORPUS.read_bytes())]
    return browser.post("/runs", fields, files)


def _stored(db, episode_id: str) -> list:  # type: ignore[no-untyped-def]
    rows = db.execute(
        "SELECT p.report FROM research_run_reports p JOIN research_runs r USING (research_run_id)"
        " WHERE p.episode_id = %s ORDER BY r.ordinal",
        (episode_id,),
    ).fetchall()
    return [report_from_json(r[0] if isinstance(r[0], dict) else json.loads(r[0])) for r in rows]


def test_a_researcher_runs_the_vertical_in_the_workspace_and_continues_it_later(db, tmp_path):
    _member(db)
    browser = _workspace(tmp_path)

    home = browser.get("/")
    assert home.status == 200 and PROJECT in home.text
    assert "No research yet." in _text(home)
    assert (
        f'<input type="hidden" name="project" value="{PROJECT}">' in browser.get("/runs/new").text
    )

    # -- input: the form, as a researcher fills it in ----------------------------------------
    sent = _start(browser, tmp_path, literature=True)
    assert sent.status == 303, sent.text
    assert sent.location.startswith("/episodes/epi:")
    episode_id = sent.location.rsplit("/", 1)[1]

    # -- what the services wrote: parked on the missing simulator, nothing simulated -----------
    state, reason = db.execute(
        "SELECT state, suspend_reason FROM research_episodes WHERE episode_id = %s", (episode_id,)
    ).fetchone()
    assert state == "SUSPENDED" and "cap:sp.mesh_sensitivity" in reason
    assert (
        db.execute(
            "SELECT count(*) FROM jobs WHERE capability_id = ANY(%s)", (list(SIMULATIONS),)
        ).fetchone()[0]
        == 0
    )
    assert (
        db.execute(
            "SELECT count(*) FROM runs WHERE capability_id = ANY(%s)", (list(SIMULATIONS),)
        ).fetchone()[0]
        == 0
    )
    (report,) = _stored(db, episode_id)

    # -- output: the episode, as the page shows it ---------------------------------------------
    page = browser.get(sent.location)
    assert page.status == 200
    shown = _text(page)
    assert pages.report_html(report) in page.text, "the page shows the report the run returned"
    assert (
        "Status now: Waiting -- can be continued waiting for a simulation that cannot run here "
        "(mesh sensitivity)" in shown
    )
    assert "awaiting simulator for cap:sp.mesh_sensitivity" in shown, "stored, in the details"
    assert f"{REPORT.name} document INTERNAL_MEASUREMENT READY" in shown
    for attestation_id in report_ids(db, episode_id, "attestation"):
        assert attestation_id in shown
    assert "External literature -- " in shown and "RETRACTED" in shown
    for mechanism, belief in db.execute(
        "SELECT h.mechanism, h.hypothesis_id FROM hypotheses h JOIN hypothesis_sets s"
        " ON s.set_id = h.hypothesis_set_id WHERE s.episode_id = %s",
        (episode_id,),
    ).fetchall():
        assert mechanism in shown and belief in shown
    assert shown.count("CONTRADICTED") >= 2
    assert "Debate and critique Debate dbt:" in shown
    for (plan_id,) in db.execute(
        "SELECT plan_id FROM verification_plans WHERE episode_id = %s", (episode_id,)
    ).fetchall():
        assert plan_id in shown
    for capability, run_id in db.execute(
        "SELECT capability_id, result_run_id FROM jobs WHERE episode_id = %s AND state ="
        " 'SUCCEEDED' AND idempotency_key LIKE 'vs:%%'",
        (episode_id,),
    ).fetchall():
        assert capability in shown and run_id in shown
    assert "Actions awaiting a person cap:sp.fourpoint_probe (MEASUREMENT)" in shown
    assert "cap:sp.mesh_sensitivity (SIMULATION, best next check) -- BLOCKED" in shown
    assert "Result PROVISIONAL -- not confirmed" in shown
    (run_1,) = db.execute(
        "SELECT research_run_id FROM research_runs WHERE episode_id = %s", (episode_id,)
    ).fetchone()
    assert f"research run {run_1} (run 1 of this episode)" in shown
    assert f'action="/episodes/{episode_id}/continue"' in page.text
    markdown = browser.get(f"/episodes/{episode_id}/runs/1/report.md")
    assert markdown.status == 200 and markdown.headers["Content-Type"].startswith("text/markdown")
    assert markdown.text == render_markdown(report), "the CLI's renderer, the same report"

    # -- later: the workspace was restarted; the episode is still there ------------------------
    stale = _token(page)
    later = _workspace(tmp_path)
    home = later.get("/")
    assert episode_id in home.text and "Waiting -- can be continued" in _text(home)
    assert later.post(f"/episodes/{episode_id}/continue", {"csrf": stale}).status == 403
    reopened = later.get(f"/episodes/{episode_id}")
    assert pages.report_html(report) in reopened.text
    before = _census(db)

    # -- continue it: the same episode, through the accepted continuation path -----------------
    continued = later.post(f"/episodes/{episode_id}/continue", {"csrf": _token(reopened)})
    assert continued.status == 303, continued.text
    assert continued.location == f"/episodes/{episode_id}?run=2"
    page = later.get(continued.location)
    shown = _text(page)
    first, second = _stored(db, episode_id)
    assert first == report
    assert pages.report_html(second) in page.text
    assert "Continuation: run 2 of this research" in shown
    assert (
        "Resumed from SUSPENDED (awaiting simulator for cap:sp.mesh_sensitivity) to "
        "EVIDENCE_GATHERING through episode_resume." in shown
    )
    assert "hypotheses RESUMED" in shown and "not debated again" in shown
    after = _census(db)
    for table in ("hypothesis_sets", "debate_records", "hypotheses", "jobs", "runs"):
        assert after[table] == before[table], table
    assert after["research_runs"] == 2 and after["research_run_reports"] == 2
    assert (
        db.execute(
            "SELECT state FROM research_episodes WHERE episode_id = %s", (episode_id,)
        ).fetchone()[0]
        == "SUSPENDED"
    )
    assert "Research report -- run 1" in _text(later.get(f"/episodes/{episode_id}?run=1"))


def report_ids(db, episode_id: str, kind: str) -> list[str]:  # type: ignore[no-untyped-def]
    """Ids the recorded report cites, of one kind."""
    (report,) = _stored(db, episode_id)[:1]
    assert kind == "attestation"
    return [line.attestation_id for line in report.evidence]


def test_a_completed_episode_is_read_only(db, tmp_path):
    _member(db)
    browser = _workspace(tmp_path)
    sent = _start(browser, tmp_path, case="contact-open-via")
    episode_id = sent.location.rsplit("/", 1)[1]
    page = browser.get(sent.location)
    shown = _text(page)
    assert "Status now: Finished" in shown and "CONFIRMED:hyp:" in shown
    assert "Result CONFIRMED" in shown and "it can be read" in shown
    assert "/continue" not in page.text
    before = _census(db)

    # The page offers no form; a request made anyway, with a valid token, is refused by the service.
    token = _token(browser.get("/runs/new"))
    refused = browser.post(f"/episodes/{episode_id}/continue", {"csrf": token})
    assert refused.status == 409
    assert f"Episode {episode_id} is COMPLETED (CONFIRMED:hyp:" in _text(refused)
    assert "a finished episode receives no new research run" in _text(refused)
    assert _census(db) == before


def test_another_actor_or_project_sees_nothing_and_writes_nothing(db, tmp_path):
    _member(db)
    _member(db, COLLEAGUE)
    db.execute("INSERT INTO projects (project_id, name) VALUES (%s, 'Other lab')", (OTHER_PROJECT,))
    db.execute(
        "INSERT INTO actors (actor_id, actor_type, display_name) VALUES (%s, 'HUMAN', 'Mallory')",
        (MALLORY,),
    )
    for project, active in ((OTHER_PROJECT, True), (PROJECT, False)):  # a lapsed membership
        db.execute(
            "INSERT INTO project_memberships (actor_id, project_id, role, sensitivity_clearance,"
            " approval_scopes, active) VALUES (%s, %s, 'RESEARCHER', ARRAY['PUBLIC', 'INTERNAL'],"
            " ARRAY[]::text[], %s)",
            (MALLORY, project, active),
        )
    sent = _start(_workspace(tmp_path), tmp_path)
    episode_id = sent.location.rsplit("/", 1)[1]
    before = _census(db)
    unknown = "epi:does-not-exist"

    mallory = _workspace(tmp_path, MALLORY)
    home = mallory.get("/")
    assert OTHER_PROJECT in home.text and PROJECT not in home.text and episode_id not in home.text
    token = _token(mallory.get("/runs/new"))
    for probe in (episode_id, unknown):
        seen = mallory.get(f"/episodes/{probe}")
        assert seen.status == 404 and f"No research {probe} for {MALLORY}." in _text(seen)
        assert mallory.get(f"/episodes/{probe}/runs/1/report.md").status == 404
        pushed = mallory.post(f"/episodes/{probe}/continue", {"csrf": token})
        assert pushed.status == 404 and f"No research {probe} for {MALLORY}." in _text(pushed)
    refused = mallory.post(
        "/runs",
        {"csrf": token, "project": PROJECT, "goal": "probe"},
        {"measurement": [(REPORT.name, REPORT.read_bytes())]},
    )
    assert refused.status == 403 and f"No research for {MALLORY} in {PROJECT}." in _text(refused)

    colleague = _workspace(tmp_path, COLLEAGUE)
    assert episode_id not in colleague.get("/").text
    seen = colleague.get(f"/episodes/{episode_id}")
    assert seen.status == 404 and f"No research {episode_id} for {COLLEAGUE}." in _text(seen)
    pushed = colleague.post(
        f"/episodes/{episode_id}/continue", {"csrf": _token(colleague.get("/runs/new"))}
    )
    assert pushed.status == 404

    # The opener, once their membership lapses, sees their own episode no more.
    db.execute(
        "UPDATE project_memberships SET active = FALSE WHERE actor_id = %s AND project_id = %s",
        (ACTOR, PROJECT),
    )
    lapsed = _workspace(tmp_path)
    assert lapsed.get(f"/episodes/{episode_id}").status == 404
    assert episode_id not in lapsed.get("/").text
    assert _census(db) == before


def test_an_excerpt_is_withheld_once_the_actor_may_no_longer_read_it(db, tmp_path):
    _member(db)
    browser = _workspace(tmp_path)
    sent = _start(browser, tmp_path, case=None)
    episode_id = sent.location.rsplit("/", 1)[1]
    (report,) = _stored(db, episode_id)
    excerpt = report.evidence[0].excerpt
    assert html.escape(excerpt) in browser.get(sent.location).text

    db.execute(
        "UPDATE project_memberships SET sensitivity_clearance = ARRAY['PUBLIC']"
        " WHERE actor_id = %s AND project_id = %s",
        (ACTOR, PROJECT),
    )
    page = browser.get(sent.location)
    assert page.status == 200
    assert html.escape(excerpt) not in page.text
    # Every excerpt is withheld wherever the page shows it: under Evidence and reasoning, and in
    # the full report the audit layer holds.
    assert page.text.count(html.escape(WITHHELD)) == 2 * len(report.evidence)
    markdown = browser.get(f"/episodes/{episode_id}/runs/1/report.md").text
    assert excerpt[:60] not in markdown and WITHHELD in markdown


def test_what_a_user_uploads_is_shown_as_text_never_as_markup(db, tmp_path):
    _member(db)
    browser = _workspace(tmp_path)
    hostile = "<script>alert(1)</script>"
    body = (
        "# Measurement\n\n" + hostile + " The series resistance is extremely high and weakly "
        "bias dependent while the junction capacitance trends normally.\n"
    ).encode()
    sent = _start(
        browser,
        tmp_path,
        case=None,
        measurement=("<img src=x onerror=alert(1)>.md", body),
        goal=f"{hostile} why is Rs high?",
    )
    assert sent.status == 303, sent.text
    for url in ("/", sent.location):
        page = browser.get(url)
        assert "<script>alert" not in page.text and "<img src=x" not in page.text
    page = browser.get(sent.location)
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page.text
    assert "&lt;img src=x onerror=alert(1)&gt;.md" in page.text


def test_forged_and_undeclared_requests_write_nothing(db, tmp_path):
    _member(db)
    browser = _workspace(tmp_path)
    token = _token(browser.get("/runs/new"))
    before = _census(db)
    upload = {"measurement": [(REPORT.name, REPORT.read_bytes())]}
    fields = {"project": PROJECT, "goal": GOAL}

    assert browser.post("/runs", fields, upload).status == 403
    assert browser.post("/runs", {**fields, "csrf": "guess"}, upload).status == 403
    forged = browser.post("/runs", {**fields, "csrf": token}, upload, origin="http://evil.test")
    assert forged.status == 403
    assert browser.get("/", host="evil.test:8765").status == 400

    corpus = {**upload, "literature_corpus": [(CORPUS.name, CORPUS.read_bytes())]}
    undeclared = browser.post("/runs", {**fields, "csrf": token, "literature_query": QUERY}, corpus)
    assert undeclared.status == 400
    assert "Confirm that the literature query may be made public" in _text(undeclared)
    alone = browser.post("/runs", {**fields, "csrf": token}, corpus)
    assert alone.status == 400 and "go together" in _text(alone)
    empty = browser.post("/runs", {"csrf": token, "project": PROJECT, "goal": " "}, upload)
    assert empty.status == 400 and "Describe the research question." in _text(empty)
    assert _census(db) == before
