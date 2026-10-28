"""G0-A in every export: how the run was started, in both languages, and nothing secret.

The report's session provenance (`011n`) is rendered as its own block in `report.md`, the summary
and the page, English and zh-TW alike: the origin named in the product's curated words (only a
signed-in web session is attested; every other origin says so), the session's NON-SECRET audit
reference, and the actor, project, run and trace it binds -- identical in both languages and
checked by the parity checker. A report stored before `011n` has no block in `report.md`, so its
export is unchanged; the page and summary say it was not recorded.
"""

from __future__ import annotations

import dataclasses

import pytest

from lab_brain.interfaces.web import pages
from lab_brain.interfaces.web.bilingual_parity import check_html, check_markdown
from lab_brain.interfaces.web.i18n import Messages
from lab_brain.research.report import SessionProvenance
from lab_brain.research.run_provenance import RunOrigin
from tests.unit.test_g0_bilingual_export_markdown import CANONICAL, _report, _terms
from tests.unit.test_g0_bilingual_export_summary import _summary

REF = "sar:0b9c3f1e-6d7a-4c1e-9a52-1f2e3d4c5b6a"


def _with(origin: RunOrigin):  # type: ignore[no-untyped-def]
    return dataclasses.replace(
        _report(),
        session_provenance=SessionProvenance(
            origin=origin.value,
            session_audit_ref=REF if origin is RunOrigin.WEB_SESSION else None,
            actor_id="act:ada",
            project_id="prj:rs",
            research_run_id="rrn:one",
            trace_id="trc:one",
        ),
    )


def _md(report, locale):  # type: ignore[no-untyped-def]
    return pages.markdown_export(report, (), terms=_terms(locale), canonical_digest=CANONICAL)


@pytest.mark.parametrize("origin", list(RunOrigin))
def test_report_md_names_how_the_run_was_started_in_both_languages(origin):
    report = _with(origin)
    en, zh = _md(report, "en"), _md(report, "zh-TW")
    assert check_markdown(en, zh).ok, check_markdown(en, zh).findings
    words = Messages("zh-TW")(f"so.{origin.value}")
    assert f"- 啟動方式：**{origin.value}**〔{words}〕" in zh
    assert f"- Origin: **{origin.value}**" in en
    for text in (en, zh):
        assert "`act:ada`" in text and "`rrn:one`" in text and "`trc:one`" in text
        assert (f"`{REF}`" in text) is (origin is RunOrigin.WEB_SESSION)
        assert "session_hash" not in text
    if origin is not RunOrigin.WEB_SESSION:
        assert "No signed-in session is attested for this run." in en
        assert "這次執行沒有可證明的已登入工作階段。" in zh
        assert "未證明工作階段" in words


def test_a_changed_reference_or_a_raised_origin_is_caught():
    report = _with(RunOrigin.WEB_SESSION)
    en, zh = _md(report, "en"), _md(report, "zh-TW")
    assert "IDENTIFIERS" in check_markdown(en, zh.replace(REF, "sar:other")).checks()
    unattested = _md(_with(RunOrigin.OPERATOR_CLI), "zh-TW")
    raised = unattested.replace(
        Messages("zh-TW")("so.OPERATOR_CLI"), Messages("zh-TW")("so.WEB_SESSION")
    )
    en_cli = _md(_with(RunOrigin.OPERATOR_CLI), "en")
    assert "STATUS" in check_markdown(en_cli, raised).checks()


def test_a_report_stored_before_session_provenance_exports_as_it_always_did():
    report = _report()
    assert report.session_provenance is None
    assert "Session provenance" not in _md(report, "en")


def test_the_summaries_and_pages_carry_the_same_session_block_in_both_languages(monkeypatch):
    report = _with(RunOrigin.WEB_SESSION)
    monkeypatch.setattr("tests.unit.test_g0_bilingual_export_summary._report", lambda **_: report)
    en, zh = _summary("en"), _summary("zh-TW")
    for markup in (en, zh):
        assert f"<code>{REF}</code>" in markup and "session_hash" not in markup
    assert check_html(en, zh, surface="summary").ok
    assert "IDENTIFIERS" in check_html(en, zh.replace(REF, "sar:other"), surface="summary").checks()
    page = {
        locale: pages.episode_page(
            actor_id="act:1",
            episode=pages.EpisodeRow(
                "epi:full",
                "prj:rs",
                "trc:one",
                "Why?",
                "SUSPENDED",
                None,
                None,
                report.started_at,
                None,
                1,
            ),
            runs=[],
            report=report,
            report_ordinal=1,
            csrf="tok",
            continuable=False,
            chrome=pages.Chrome("act:1", locale),
            terms=_terms(locale),
        ).decode()
        for locale in ("en", "zh-TW")
    }
    assert f"<code>{REF}</code>" in page["zh-TW"]
    assert "已登入的網頁工作階段" in page["zh-TW"]
    assert check_html(page["en"], page["zh-TW"], surface="page").ok
