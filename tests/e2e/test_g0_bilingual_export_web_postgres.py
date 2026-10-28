"""G0-B / G0-P / G0-A through the workspace: every export in both languages, traceable, and no
record changed.

On a fresh database, with no model, simulator or network call, a signed-in project member runs
research with the pack's rule-based catalog reasoner, then reads -- in English and in zh-TW -- the
episode page, `summary.html` and `report.md`:

    locale rule  `report.md` and `summary.html` follow the reader's language (`lb_locale`);
                 `?lang=en|zh-TW` names one explicitly; any other value is refused. English
                 `report.md` is the record's export, byte for byte, under its old file name.
    digests      both summaries name the SAME SHA-256 of the record's export (English report.md);
                 each also names the SHA-256 of `report.md` in its own language; the zh-TW
                 `report.md` names the record export's digest it was rendered from; every export
                 carries its own digest as a `Repr-Digest` header
    parity       page, summary and `report.md` pass `bilingual_parity` in full -- including the
                 citations (same attestations, locators, artifacts, hashes) and the quoted
                 evidence (same bytes); every unavailable simulation is not performed, with its
                 reason and what it needs, in both
    citations    each cited attestation shows the locator, source artifact, content hash and
                 project occurrence exactly as the canonical rows hold them
    session      the run's session provenance (origin, non-secret audit reference, actor, project,
                 run, trace) in every export, both languages; never a session's lookup key
    record       every row of every table is byte-identical before and after; the stored report is
                 unchanged
    isolation    a signed-in non-member gets 404 for every surface and language, nothing leaked
    browser      headless Chromium renders the zh-TW summary and `report.md` the same

NOT VERIFIED here: whether any Chinese sentence means what its English original means.
"""

from __future__ import annotations

import base64
import hashlib
import json
import shutil
import subprocess
from typing import Any

import pytest

from lab_brain.interfaces.web.app import LOCALE_COOKIE
from lab_brain.interfaces.web.bilingual_parity import (
    canonical_snapshot,
    check_html,
    check_markdown,
    compare_canonical,
    unavailable_simulations,
)
from tests.e2e.test_g0_bilingual_parity_postgres import _outsider_token, _report, _served, _stored
from tests.e2e.test_research_acceptance_without_lumerical_postgres import (
    Lab2,
    _device,
    _in,
    _research,
    journey,
)
from tests.e2e.test_research_episode_postgres import GOAL
from tests.wsgi_client import Browser, Reply

pytestmark = pytest.mark.postgres

__all__ = ["journey"]  # a fixture, used by name

LOCALES = ("en", "zh-TW")


def _get(browser: Browser, locale: str, path: str) -> Reply:
    _in(browser, locale, "/")
    reply = browser.get(path)
    assert reply.status == 200, (locale, path, reply.text[:400])
    return reply


def _sha(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _repr_digest(body: bytes) -> str:
    return "sha-256=:" + base64.b64encode(hashlib.sha256(body).digest()).decode() + ":"


def test_every_export_reads_in_both_languages_traceably_and_changes_no_record(
    db: Any, journey: Lab2
) -> None:
    j = journey
    episode = _research(j, db, _device("probe-artifact"))
    report = _report(db, j.project, episode)
    unavailable = unavailable_simulations(report)
    stored = _stored(db, episode)
    before = canonical_snapshot(db)
    base = f"/episodes/{episode}/runs/1"
    page, summary, md = f"/episodes/{episode}?run=1", f"{base}/summary.html", f"{base}/report.md"

    got = {
        (s, loc): _get(j.owner, loc, p)
        for loc in LOCALES
        for s, p in (("page", page), ("summary", summary), ("report.md", md))
    }
    text = {k: v.text for k, v in got.items()}

    # The locale rule: an explicit `lang` gives the same file whatever the reader's language.
    for loc in LOCALES:
        for other in LOCALES:
            assert _get(j.owner, other, f"{md}?lang={loc}").body == got[("report.md", loc)].body
        assert got[("report.md", loc)].headers["Content-Language"] == loc
    for path in (f"{md}?lang=fr", f"{summary}?lang=xx"):
        _in(j.owner, "en", "/")
        assert j.owner.get(path).status == 404, path
    assert 'filename="' in got[("report.md", "en")].headers["Content-Disposition"]
    assert ".zh-TW.md" in got[("report.md", "zh-TW")].headers["Content-Disposition"]
    assert ".zh-TW.md" not in got[("report.md", "en")].headers["Content-Disposition"]

    # Parity of every surface, citations and quotes included.
    for surface in ("page", "summary"):
        result = check_html(
            text[(surface, "en")],
            text[(surface, "zh-TW")],
            surface=surface,
            unavailable=unavailable,
        )
        assert result.ok, (surface, result.findings)
    assert check_html(text[("summary", "en")], text[("summary", "zh-TW")], surface="s").coverage[
        "citations"
    ][0] >= len(report.evidence)
    markdown = check_markdown(
        text[("report.md", "en")], text[("report.md", "zh-TW")], unavailable=unavailable
    )
    assert markdown.ok, markdown.findings
    assert markdown.aligned > 100 and markdown.untranslated > 0
    assert "## 互相競爭的假說" in text[("report.md", "zh-TW")]
    assert text[("report.md", "zh-TW")].count("**BLOCKED**〔無法在此執行〕") == len(unavailable)

    # Digests: one record export, named by both summaries; each language's own file, named by
    # its summary and its own header; the Chinese file names the record export it came from.
    canonical, chinese = _sha(text[("report.md", "en")]), _sha(text[("report.md", "zh-TW")])
    assert canonical != chinese
    assert canonical in text[("summary", "en")] and canonical in text[("summary", "zh-TW")]
    assert chinese in text[("summary", "zh-TW")] and chinese not in text[("summary", "en")]
    assert f"`{canonical}`" in text[("report.md", "zh-TW")]
    for reply in got.values():
        if "Repr-Digest" in reply.headers:
            assert reply.headers["Repr-Digest"] == _repr_digest(reply.body)
    assert all(
        "Repr-Digest" in got[(s, loc)].headers for s in ("summary", "report.md") for loc in LOCALES
    )

    # Citations, as the canonical rows hold them, in both summaries and pages.
    for line in report.evidence:
        locator, artifact, unit = db.execute(
            "SELECT locator, source_artifact_id, evidence_unit_id FROM attestations"
            " WHERE attestation_id = %s",
            (line.attestation_id,),
        ).fetchone()
        (content_hash,) = db.execute(
            "SELECT content_hash FROM artifacts WHERE artifact_id = %s", (artifact,)
        ).fetchone()
        for loc in LOCALES:
            for surface in ("summary", "page"):
                markup = text[(surface, loc)]
                for value in (line.attestation_id, locator, artifact, content_hash, j.project):
                    assert f"<code>{value}</code>" in markup, (surface, loc, value)
        assert unit is None or all(unit in text[("summary", loc)] for loc in LOCALES)

    # Session provenance, in every export and both languages; nothing secret.
    session = report.session_provenance
    assert session is not None and session.origin == "WEB_SESSION" and session.session_audit_ref
    if session is not None:
        for (surface, loc), body in text.items():
            assert session.origin in body and session.research_run_id in body, (surface, loc)
            if session.session_audit_ref:
                assert session.session_audit_ref in body, (surface, loc)
            assert "session_hash" not in body
        hashes = [str(r[0]) for r in db.execute("SELECT session_hash FROM account_sessions")]
        assert not any(h and h in body for h in hashes for body in text.values())

    # Isolation: a signed-in non-member gets nothing, in either language.
    for loc in LOCALES:
        j.outsider.post(
            "/locale", {"csrf": _outsider_token(j.outsider), "locale": loc, "next": "/"}
        )
        for path in (page, summary, md, f"{md}?lang=zh-TW", f"{summary}?lang=en"):
            refused = j.outsider.get(path)
            assert refused.status == 404, (loc, path)
            assert GOAL not in refused.text

    # The record: no row of any table changed, the stored report is as written.
    assert compare_canonical(before, canonical_snapshot(db)) == ()
    assert _stored(db, episode) == stored
    assert _report(db, j.project, episode) == report

    # The browser path, if Chromium is at hand: the zh-TW summary and report.md as rendered.
    seen = _chromium(j.owner, [summary, md])
    if seen is None:
        pytest.skip("node with the playwright package is not available")
    if seen is not None:
        assert seen[f"zh-TW {md}"]["body"] == text[("report.md", "zh-TW")]
        assert seen[f"en {md}"]["body"] == text[("report.md", "en")]
        rendered = check_html(
            seen[f"en {summary}"]["body"],
            seen[f"zh-TW {summary}"]["body"],
            surface="summary",
            unavailable=unavailable,
        )
        assert rendered.ok, rendered.findings
        assert compare_canonical(before, canonical_snapshot(db)) == ()


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
      const html = path.endsWith('.md') ? await reply.text() : await page.content();
      out[locale + ' ' + path] = { status: reply.status(), body: html };
    }
    await context.close();
  }
  await browser.close();
  process.stdout.write(JSON.stringify(out));
})().catch((e) => { console.error(e); process.exit(1); });
"""


def _chromium(browser: Browser, paths: list[str]) -> dict[str, dict[str, Any]] | None:
    """Each path in both languages through headless Chromium; None without node + playwright."""
    if shutil.which("node") is None:
        return None
    probe = subprocess.run(
        ["node", "-e", "require('playwright')"], capture_output=True, text=True, check=False
    )
    if probe.returncode != 0:
        return None
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
    for value in result.values():
        assert value["status"] == 200
    return result
