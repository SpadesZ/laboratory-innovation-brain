"""G0-B / G0-P / G0-A on a real research episode: the English and zh-TW renderings agree, and
rendering them changed no record.

Through the workspace, on a fresh database, with no model, simulator or network call:

    accounts     an administrator opens the project for its owner; the owner, signed in, runs
                 research with the pack's rule-based catalog reasoner (a stand-in for a model:
                 the record says so) on a sound device, so two simulations stay unavailable
    parity       the episode page and the exported summary, read in English and in zh-TW, pass
                 `bilingual_parity.check_html`: same blocks, statuses and their words, numbers,
                 units, identifiers, negations and claims; every unavailable simulation labelled
                 not performed with its reason and what it needs, in both; nothing English left
                 unmarked in the Chinese reading
    browser      the same pages, rendered by headless Chromium over a socket, pass the same check
    record       every row of every table is byte-identical before and after all of it (both
                 languages, both paths, the refused outsider); the summaries name the SHA-256 of
                 the record's export, which is unchanged
    isolation    a signed-in person who is not a member gets nothing in either language
    model text   with a stand-in language model (`tests.g0_standin`), whose wording has no curated
                 translation, the Chinese reading shows it as written and marks it untranslated --
                 and still passes every structural check
    known gap    `report.md` is the English record in every locale: G0-B's "an export falls back
                 to one language" -- kept as a strict expected failure until the product decides

WHAT THIS DOES NOT SHOW: that a Chinese sentence means what its English original means. That is
NOT VERIFIED offline; it needs an independent bilingual reviewer.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from wsgiref.simple_server import WSGIRequestHandler, make_server

import pytest

from lab_brain.interfaces.web.app import LOCALE_COOKIE
from lab_brain.interfaces.web.bilingual_parity import (
    ParityResult,
    canonical_snapshot,
    check_html,
    check_markdown,
    compare_canonical,
    unavailable_simulations,
)
from lab_brain.research.report import EpisodeReport
from lab_brain.research.report_store import SqlResearchReportStore
from tests.e2e.test_g0_exploratory_screening_postgres import SCREENING, device, research, standin
from tests.e2e.test_research_acceptance_without_lumerical_postgres import (
    Lab2,
    _device,
    _in,
    _research,
    journey,
)
from tests.e2e.test_research_episode_postgres import GOAL
from tests.e2e.test_web_debate_retry_postgres import _activated, _deployment
from tests.e2e.test_web_llm_credentials_postgres import _setup
from tests.wsgi_client import Browser

pytestmark = pytest.mark.postgres

__all__ = ["journey", "standin"]  # fixtures, used by name

SURFACES = ("page", "summary")


def _paths(episode: str) -> dict[str, str]:
    return {
        "page": f"/episodes/{episode}?run=1",
        "summary": f"/episodes/{episode}/runs/1/summary.html",
        "report.md": f"/episodes/{episode}/runs/1/report.md",
    }


def _render(browser: Browser, episode: str) -> dict[tuple[str, str], str]:
    """Every surface in both languages, as the person's browser receives it."""
    return {
        (surface, locale): _in(browser, locale, path)
        for locale in ("en", "zh-TW")
        for surface, path in _paths(episode).items()
    }


def _report(db: Any, project: str, episode: str) -> EpisodeReport:
    (recorded,) = SqlResearchReportStore(db).for_episode(project_id=project, episode_id=episode)
    return recorded.report


def _parity(rendered: dict[tuple[str, str], str], report: EpisodeReport) -> list[ParityResult]:
    unavailable = unavailable_simulations(report)
    return [
        check_html(
            rendered[(surface, "en")],
            rendered[(surface, "zh-TW")],
            surface=surface,
            unavailable=unavailable,
        )
        for surface in SURFACES
    ]


def _stored(db: Any, episode: str) -> str:
    return str(
        db.execute(
            "SELECT p.report::text FROM research_run_reports p JOIN research_runs r"
            " USING (research_run_id) WHERE r.episode_id = %s AND r.ordinal = 1",
            (episode,),
        ).fetchone()[0]
    )


# -- the browser path -----------------------------------------------------------------------------

_CHROMIUM = r"""
const { chromium } = require('playwright');
const job = JSON.parse(process.argv[1]);
(async () => {
  const browser = await chromium.launch();
  const out = {};
  for (const locale of ['en', 'zh-TW']) {
    const context = await browser.newContext({ javaScriptEnabled: false });
    await context.addCookies(Object.entries({ ...job.cookies, [job.localeCookie]: locale })
      .map(([name, value]) => ({ name, value, url: job.base })));
    const page = await context.newPage();
    for (const path of job.paths) {
      const reply = await page.goto(job.base + path);
      out[locale + ' ' + path] = { status: reply.status(), html: await page.content(),
        lang: await page.evaluate(() => document.documentElement.lang) };
    }
    await context.close();
  }
  await browser.close();
  process.stdout.write(JSON.stringify(out));
})().catch((e) => { console.error(e); process.exit(1); });
"""


class _Quiet(WSGIRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 -- the base's name
        return None


def _served(browser: Browser) -> Iterator[str]:
    """The workspace on a socket, for Chromium. The workspace answers only to the Host it was
    built for, so each request is presented under that Host -- nothing else is changed."""
    app = browser._app

    def as_built(environ: dict[str, Any], start_response: Any) -> Any:
        environ["HTTP_HOST"] = browser.host
        return app(environ, start_response)

    server = make_server("127.0.0.1", 0, as_built, handler_class=_Quiet)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


def _chromium(browser: Browser, paths: list[str]) -> dict[str, dict[str, Any]]:
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    probe = subprocess.run(
        ["node", "-e", "require('playwright')"], capture_output=True, text=True, check=False
    )
    if probe.returncode != 0:
        pytest.skip("the playwright package is not available to node")
    served = _served(browser)
    base = next(served)
    try:
        job = {
            "base": base,
            "paths": paths,
            "cookies": {k: v for k, v in browser.cookies.items() if k != LOCALE_COOKIE},
            "localeCookie": LOCALE_COOKIE,
        }
        done = subprocess.run(
            ["node", "-e", _CHROMIUM, json.dumps(job)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    finally:
        next(served, None)
    assert done.returncode == 0, done.stderr[-2000:]
    result: dict[str, dict[str, Any]] = json.loads(done.stdout)
    return result


# -- the tests ------------------------------------------------------------------------------------


def test_a_signed_in_owners_report_reads_the_same_in_both_languages_and_changes_no_record(
    db: Any, journey: Lab2
) -> None:
    j = journey
    episode = _research(j, db, _device("probe-artifact"))
    report = _report(db, j.project, episode)
    unavailable = unavailable_simulations(report)
    assert {u.capability_id for u in unavailable} >= {"cap:sp.mesh_sensitivity"}
    assert len(unavailable) >= 2, "a best next simulation and at least one more"
    stored = _stored(db, episode)
    before = canonical_snapshot(db)

    rendered = _render(j.owner, episode)
    results = _parity(rendered, report)
    for result in results:
        assert result.ok, (result.surface, result.findings)
        assert result.aligned > 100, result.surface
        hypotheses = result.coverage["hypotheses"]
        assert hypotheses[0] == hypotheses[1] >= len(report.hypotheses), result.coverage
        assert result.coverage["predictions"][0] > 0 and result.coverage["next_steps"][0] > 0
    # The zh-TW summary says, for EVERY unavailable simulation, that it did not run and why.
    zh_summary = rendered[("summary", "zh-TW")]
    assert zh_summary.count("無法在此執行") >= len(unavailable)
    assert zh_summary.count("這裡無法執行：") == len(unavailable)

    # The browser path: the same pages, rendered by Chromium over a socket.
    paths = [_paths(episode)["page"], _paths(episode)["summary"]]
    seen = _chromium(j.owner, paths)
    for path, surface in zip(paths, SURFACES, strict=True):
        en, zh = seen[f"en {path}"], seen[f"zh-TW {path}"]
        assert en["status"] == zh["status"] == 200
        assert (en["lang"], zh["lang"]) == ("en", "zh-TW")
        chromium = check_html(en["html"], zh["html"], surface=surface, unavailable=unavailable)
        assert chromium.ok, (surface, chromium.findings)

    # Isolation (G0-A): a signed-in non-member gets nothing, in either language.
    for locale in ("en", "zh-TW"):
        j.outsider.post(
            "/locale",
            {"csrf": _outsider_token(j.outsider), "locale": locale, "next": "/"},
        )
        for path in _paths(episode).values():
            refused = j.outsider.get(path)
            assert refused.status == 404, (locale, path)
            assert GOAL not in refused.text

    # The record (G0-B, G0-P): no row of any table changed; the report is as written, and both
    # summaries name the digest of the same, unchanged export.
    assert compare_canonical(before, canonical_snapshot(db)) == ()
    assert _stored(db, episode) == stored
    export = rendered[("report.md", "en")]
    digest = "sha256:" + hashlib.sha256(export.encode("utf-8")).hexdigest()
    assert digest in rendered[("summary", "en")] and digest in rendered[("summary", "zh-TW")]
    assert _in(j.owner, "en", _paths(episode)["report.md"]) == export


def _outsider_token(browser: Browser) -> str:
    from tests.e2e.test_web_accounts_postgres import _csrf

    return _csrf(browser.get("/"))


def test_model_written_text_is_shown_as_written_and_marked_and_parity_still_holds(
    db: Any, tmp_path: Path, standin: Any
) -> None:
    fake, _model = standin
    _setup(db)
    browser = _deployment(tmp_path, inference_deadline=60, research_features=SCREENING)
    _activated(db, browser, fake)
    episode = research(browser, device("contact-open-via"))
    (recorded,) = SqlResearchReportStore(db).for_episode(
        project_id=_project(db, episode), episode_id=episode
    )
    stored = _stored(db, episode)
    before = canonical_snapshot(db)
    rendered = _render(browser, episode)
    for result in _parity(rendered, recorded.report):
        assert result.ok, (result.surface, result.findings)
        assert result.untranslated > 0, "the stand-in's wording has no curated rendering"
    assert "未翻譯" in rendered[("page", "zh-TW")]
    assert compare_canonical(before, canonical_snapshot(db)) == ()
    assert _stored(db, episode) == stored


def _project(db: Any, episode: str) -> str:
    return str(
        db.execute(
            "SELECT project_id FROM research_episodes WHERE episode_id = %s", (episode,)
        ).fetchone()[0]
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "G0-B gap, demonstrated: report.md is the English record in every locale -- an export "
        "that falls back to one language. The zh-TW export is summary.html; whether report.md "
        "stays the language-neutral record or gains a zh-TW rendering is a product decision."
    ),
)
def test_the_markdown_export_reads_in_the_readers_language(db: Any, journey: Lab2) -> None:
    j = journey
    episode = _research(j, db, _device("probe-artifact"))
    rendered = _render(j.owner, episode)
    result = check_markdown(
        rendered[("report.md", "en")],
        rendered[("report.md", "zh-TW")],
        unavailable=unavailable_simulations(_report(db, j.project, episode)),
    )
    assert result.checks() <= {"SINGLE_LANGUAGE"}, result.findings
    assert result.ok, result.findings
