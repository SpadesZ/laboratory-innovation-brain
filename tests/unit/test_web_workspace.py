"""The research workspace without a database: what it renders, what it parses, what it refuses.

The report a run returned is shown field by field (the web page is a second renderer of the SAME
`EpisodeReport` the CLI renders, and drops nothing), stored and read back unchanged, and never
becomes markup. Forged, foreign-host and malformed requests are refused before a database
connection is even opened.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import html
import io
import json
import re
from pathlib import Path
from typing import Any

import pytest

from lab_brain.interfaces import cli
from lab_brain.interfaces.config import Settings
from lab_brain.interfaces.web import Workspace, allowed_hosts, pages
from lab_brain.interfaces.web.forms import FormError, read_form
from lab_brain.research.report_store import report_from_json, report_to_json
from lab_brain.research.vertical import load_vertical_factory
from tests.report_samples import full_report, leaves
from tests.wsgi_client import Browser, _multipart

HOSTILE = '<script>alert("x")</script><img src=x onerror=alert(1)>'


def _text(markup: str) -> str:
    """What a reader sees: inline tags dropped, block tags as breaks, entities decoded."""
    inline = re.sub(r"</?(?:code|strong|span|a)\b[^>]*>", "", markup)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", inline)).split())


def _shown(leaf: Any) -> str:
    if isinstance(leaf, bool):
        return "best next check" if leaf else "also sufficient"
    if isinstance(leaf, dt.datetime):
        return leaf.isoformat()
    return " ".join(str(leaf).replace("`", "").replace("**", "").split())


# -- the stored report ----------------------------------------------------------------------------


def test_a_stored_report_reads_back_as_the_report_that_was_returned():
    report = full_report()
    encoded = report_to_json(report)
    assert json.loads(json.dumps(encoded)) == encoded, "plain JSON"
    assert report_from_json(encoded) == report
    bare = dataclasses.replace(report, literature=None, debate=None, continuation=None)
    assert report_from_json(report_to_json(bare)) == bare


def test_a_stored_object_that_is_not_a_report_is_refused():
    encoded = report_to_json(full_report())
    with pytest.raises(ValueError, match="no field"):
        report_from_json({**encoded, "invented": 1})
    with pytest.raises(ValueError, match="expected int"):
        report_from_json({**encoded, "debate": {**encoded["debate"], "rounds": "2"}})
    with pytest.raises(ValueError, match="expected a list"):
        report_from_json({**encoded, "stages": "DONE"})


# -- the report as HTML ---------------------------------------------------------------------------


def test_the_web_report_shows_every_field_of_the_report_the_run_returned():
    report = full_report()
    shown = _text(pages.report_html(report))
    missing = [leaf for leaf in leaves(report) if _shown(leaf) not in shown]
    assert not missing, f"the web report drops {missing}"


def test_nothing_a_report_carries_becomes_markup():
    report = full_report(HOSTILE)
    markup = pages.report_html(report)
    assert "<script" not in markup and "<img" not in markup
    assert "&lt;script&gt;" in markup
    shown = _text(markup)
    assert all(_shown(leaf) in shown for leaf in leaves(report) if isinstance(leaf, str))
    page = pages.episode_page(
        actor_id=HOSTILE,
        episode=_episode("SUSPENDED", goal=HOSTILE),
        runs=[_run(HOSTILE)],
        report=report,
        report_ordinal=1,
        csrf='"><script>',
        continuable=True,
        notice=HOSTILE,
    ).decode()
    assert "<script" not in page and "<img" not in page


def test_inline_code_and_emphasis_are_presentation_of_escaped_text():
    assert pages.rich("run `<b>x</b>` **now**") == (
        "run <code>&lt;b&gt;x&lt;/b&gt;</code> <strong>now</strong>"
    )
    assert pages.state('SUSPENDED" onclick="x') == (
        '<span class="state state-SUSPENDED">SUSPENDED&quot; onclick=&quot;x</span>'
    )


def _episode(state: str, goal: str = "why") -> pages.EpisodeRow:
    return pages.EpisodeRow("epi:1", "prj:1", "trc:1", goal, state, None, "awaiting", "t0", None, 1)


def _run(actor: str = "act:1") -> pages.RunRow:
    return pages.RunRow(1, "rrn:1", actor, "t0", "t1", "SUSPENDED:PROVISIONAL", recorded=True)


def test_a_finished_episode_page_offers_no_continuation():
    for finished in ("COMPLETED", "ABANDONED"):
        page = pages.episode_page(
            actor_id="act:1",
            episode=_episode(finished),
            runs=[_run()],
            report=None,
            report_ordinal=None,
            csrf="tok",
            continuable=False,
        ).decode()
        assert "/continue" not in page and "it can be read" in page
    page = pages.episode_page(
        actor_id="act:1",
        episode=_episode("SUSPENDED"),
        runs=[_run()],
        report=None,
        report_ordinal=None,
        csrf="tok",
        continuable=True,
    ).decode()
    assert 'action="/episodes/epi:1/continue"' in page and 'value="tok"' in page


# -- request bodies -------------------------------------------------------------------------------


def _environ(body: bytes, content_type: str) -> dict[str, Any]:
    return {
        "CONTENT_LENGTH": str(len(body)),
        "CONTENT_TYPE": content_type,
        "wsgi.input": io.BytesIO(body),
    }


def test_a_multipart_form_is_read_as_a_browser_sends_it():
    body, content_type = _multipart(
        {"goal": "why ", "csrf": "t"},
        {
            "measurement": [("uploads/a.md", b"alpha"), ("b.md", b"beta")],
            "note": [("", b"")],
        },
    )
    form = read_form(_environ(body, content_type), limit=10_000)
    assert form.value("goal") == "why" and form.value("absent") == ""
    assert [(u.filename, u.data) for u in form.uploads("measurement")] == [
        ("a.md", b"alpha"),
        ("b.md", b"beta"),
    ]
    assert form.uploads("note") == (), "an unused file input is no upload"


def test_an_oversized_or_unreadable_body_is_refused_before_it_is_parsed():
    with pytest.raises(FormError, match="accepts 10"):
        read_form(_environ(b"x" * 11, "application/x-www-form-urlencoded"), limit=10)
    with pytest.raises(FormError, match="unsupported"):
        read_form(_environ(b"{}", "application/json"), limit=10)
    with pytest.raises(FormError, match="no readable length"):
        read_form({"CONTENT_LENGTH": "many", "wsgi.input": io.BytesIO()}, limit=10)


# -- requests refused before any database is touched ---------------------------------------------


def _unreachable(_settings: Settings) -> Any:
    raise AssertionError("a refused request must not reach the database")


def _workspace() -> Workspace:
    return Workspace(
        actor_id="act:1",
        settings=Settings(dsn="postgresql://unused"),
        connect=_unreachable,
        artifact_root=Path("."),
        vertical_factory=load_vertical_factory("silicon_photonics"),
        allowed_hosts=allowed_hosts("127.0.0.1", 8765),
        csrf_token="the-token",
    )


def test_forged_foreign_and_malformed_requests_are_refused_before_the_database():
    browser = Browser(_workspace())
    assert browser.get("/", host="attacker.example:8765").status == 400
    assert browser.get("/", host="127.0.0.1:9999").status == 400
    assert browser.post("/runs", {"csrf": "wrong", "goal": "g"}).status == 403
    assert browser.post("/runs", {"goal": "g"}).status == 403
    for origin in ("http://attacker.example", "null"):
        forged = browser.post("/runs", {"csrf": "the-token"}, origin=origin)
        assert forged.status == 403
    assert browser._call("PUT", "/", b"", "", host=None).status == 405
    refused = browser.post("/episodes/epi:1/continue", {"csrf": "x"})
    assert refused.status == 403
    headers = refused.headers
    assert "default-src 'none'" in headers["Content-Security-Policy"]
    assert "script-src" not in headers["Content-Security-Policy"]
    assert headers["X-Content-Type-Options"] == "nosniff"


def test_an_oversized_upload_is_refused_before_the_database(monkeypatch):
    monkeypatch.setattr("lab_brain.interfaces.web.app.MAX_UPLOAD_BYTES", 100)
    reply = Browser(_workspace()).post(
        "/runs", {"csrf": "the-token"}, {"measurement": [("a.md", b"x" * 500)]}
    )
    assert reply.status == 400 and "accepts 100" in reply.text


def test_loopback_names_are_the_only_hosts_a_loopback_workspace_answers():
    assert allowed_hosts("127.0.0.1", 8765) == (
        "127.0.0.1:8765",
        "localhost:8765",
        "[::1]:8765",
    )


# -- `lab-brain web` ------------------------------------------------------------------------------


class _Connection:
    def close(self) -> None:
        return None


def test_lab_brain_web_serves_the_workspace_as_its_actor(monkeypatch, tmp_path):
    served: dict[str, Any] = {}

    def serve(workspace: Workspace, *, host: str, port: int) -> None:
        served.update(workspace=workspace, host=host, port=port)

    monkeypatch.setattr("lab_brain.interfaces.web.serve", serve)
    out = io.StringIO()
    code = cli.main(
        ["web", "--actor", "act:x", "--artifact-root", str(tmp_path), "--port", "9001"],
        out=out,
        env={"LAB_BRAIN_DATABASE_URL": "postgresql://unused"},
        connect=lambda s: _Connection(),
    )
    assert code == 0, out.getvalue()
    assert (served["host"], served["port"]) == ("127.0.0.1", 9001)
    assert "Research workspace for act:x: http://127.0.0.1:9001/" in out.getvalue()
    home = Browser(served["workspace"], host="localhost:9001").get("/", host="evil:9001")
    assert home.status == 400


def test_lab_brain_web_refuses_to_serve_beyond_this_machine(tmp_path):
    out = io.StringIO()
    code = cli.main(
        ["web", "--actor", "act:x", "--artifact-root", str(tmp_path), "--host", "0.0.0.0"],
        out=out,
        env={"LAB_BRAIN_DATABASE_URL": "postgresql://unused"},
        connect=lambda s: _Connection(),
    )
    assert code == 2 and "serves this machine only" in out.getvalue()
