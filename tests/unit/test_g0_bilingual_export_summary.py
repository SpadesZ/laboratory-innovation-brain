"""G0-B / G0-P: traceable citations in both languages' summary and page, and the L3 report's own
interface words in the reader's language.

Each citation is what the canonical records hold for the attestation the report cites: its id,
the source artifact (and its occurrence in the project) or source work, the exact locator, the
artifact's content hash and, where recorded, the evidence unit and its digest -- with the quoted
evidence in its original language, the same bytes in English and in zh-TW. The parity checker
compares the two languages' citations (CITATIONS) and quotes (ORIGINAL), and catches a change.
"""

from __future__ import annotations

import re

import pytest

from lab_brain.domains.silicon_photonics import presentation as sp_presentation
from lab_brain.interfaces.web import pages
from lab_brain.interfaces.web.bilingual_parity import check_html, unavailable_simulations
from tests.unit.test_episode_view_page import T0, _report, _result, _view
from tests.unit.test_g0_bilingual_parity import PENDING

EXCERPT = "Rs is 12 ohm mm at -2 V"

CITATIONS = (
    pages.Citation(
        attestation_id="att:1",
        locator="unit 3",
        source_artifact_id="art:sha256:" + "a" * 64,
        content_hash="sha256:" + "a" * 64,
        occurrence_project_id="prj:lab",
        source_work_id=None,
        source_work=None,
        evidence_unit_id="evu:sha256:" + "b" * 64,
        unit_digest="sha256:" + "d" * 64,
    ),
)


def _terms(locale: str) -> pages.Terms:
    return pages.Terms(locale, sp_presentation.presentation(), sp_presentation.PRESENTATION_REF)


def _summary(locale: str, citations=CITATIONS) -> str:  # type: ignore[no-untyped-def]
    return pages.summary_document(
        episode=pages.EpisodeRow(
            "epi:view", "prj:lab", "trc:1", "Why is Rs high?", "SUSPENDED", None, None, T0, None, 1
        ),
        runs=[pages.RunRow(1, "rrn:1", "act:1", T0, T0, "SUSPENDED:PROVISIONAL", recorded=True)],
        report=_report(pending=PENDING),
        report_ordinal=1,
        view=_view(_result()),
        terms=_terms(locale),
        project_name="Rs anomaly",
        source_digest="sha256:" + "0" * 64,
        language_digest="sha256:" + ("0" if locale == "en" else "1") * 64,
        exported_at=T0,
        citations=citations,
    ).decode()


def test_both_summaries_cite_each_attestation_with_its_record_and_the_original_quote():
    for locale in ("en", "zh-TW"):
        markup = _summary(locale)
        (section,) = re.findall(r'<section id="v-citations".*?</section>', markup, re.S)
        for value in (
            "att:1",
            "art:sha256:" + "a" * 64,
            "sha256:" + "a" * 64,
            "prj:lab",
            "evu:sha256:" + "b" * 64,
            "sha256:" + "d" * 64,
            "[unit 3]",
            f"<blockquote>{EXCERPT}</blockquote>",
        ):
            assert value in section, (locale, value)
    zh = _summary("zh-TW")
    assert "原文引述" in zh, "the quote is marked as original-language text"


def test_the_two_summaries_are_in_parity_including_citations_and_digests():
    en, zh = _summary("en"), _summary("zh-TW")
    report = _report(pending=PENDING)
    result = check_html(en, zh, surface="summary", unavailable=unavailable_simulations(report))
    assert result.ok, result.findings
    assert result.coverage["citations"][0] > 0
    # Both name the same canonical export; each names its own language's export.
    assert "sha256:" + "0" * 64 in zh and "sha256:" + "1" * 64 in zh


@pytest.mark.parametrize(
    ("name", "old", "new", "expected"),
    [
        (
            "a quote translated",
            f"<blockquote>{EXCERPT}</blockquote>",
            "<blockquote>Rs 為 12</blockquote>",
            "ORIGINAL",
        ),
        ("a locator changed", "[unit 3]", "[unit 4]", "CITATIONS"),
        (
            "a content hash changed",
            "<code>sha256:" + "a" * 64,
            "<code>sha256:" + "e" * 64,
            "CITATIONS",
        ),
    ],
)
def test_a_changed_citation_or_quote_is_caught(name, old, new, expected):
    en, zh = _summary("en"), _summary("zh-TW")
    assert old in zh
    changed = zh.replace(old, new, 1)
    assert expected in check_html(en, changed, surface="summary").checks(), name


def test_the_page_shows_the_same_citations_in_both_languages():
    report = _report(pending=PENDING)
    pages_ = {
        locale: pages.episode_page(
            actor_id="act:1",
            episode=pages.EpisodeRow(
                "epi:view",
                "prj:lab",
                "trc:1",
                "Why is Rs high?",
                "SUSPENDED",
                None,
                None,
                T0,
                None,
                1,
            ),
            runs=[pages.RunRow(1, "rrn:1", "act:1", T0, T0, "SUSPENDED:PROVISIONAL", True)],
            report=report,
            report_ordinal=1,
            csrf="tok",
            continuable=True,
            view=_view(_result()),
            chrome=pages.Chrome("act:1", locale),
            terms=_terms(locale),
            citations=CITATIONS,
        ).decode()
        for locale in ("en", "zh-TW")
    }
    for markup in pages_.values():
        assert "sha256:" + "a" * 64 in markup and "evu:sha256:" + "b" * 64 in markup
    result = check_html(
        pages_["en"], pages_["zh-TW"], surface="page", unavailable=unavailable_simulations(report)
    )
    assert result.ok, result.findings


def test_the_zh_tw_full_report_has_no_hard_coded_english_interface_words():
    report = _report(pending=PENDING)
    zh = str(pages.report_html(report, locale="zh-TW"))
    for word in (", licence ", ", kept ", ", status ", "not admitted", "-- job ", ", run <code>"):
        assert word not in zh, word
    en = str(pages.report_html(report, locale="en"))
    for word in ("licence", "kept", "-- job ", ", run <code>"):
        assert word in en, word
