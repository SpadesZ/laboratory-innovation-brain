"""G0-B / G0-P: `report.md` in Traditional Chinese, from the product's own words -- never translated.

The English export is the record's export, byte for byte as it was before a second language
existed (its digest is pinned below). The zh-TW export is the same report rendered line for line
with the workspace's curated vocabulary (`i18n`) and the pack's presentation catalog: every
science section in Chinese where a curated rendering exists, and every passage without one --
model-written text above all -- shown exactly as written and marked as original-language text.
Identifiers, digests, numbers, units, signs, stored values and quoted evidence are byte-identical.
`bilingual_parity.check_markdown` holds the pair to that, and catches each way it could fail.

What this cannot show: that a curated Chinese rendering says what its English original says, or
that an untranslated English passage would read the same translated. NOT VERIFIED offline.
"""

from __future__ import annotations

import dataclasses
import hashlib
import pickle
import re

import pytest

from lab_brain.domains.silicon_photonics import presentation as sp_presentation
from lab_brain.interfaces.web import pages
from lab_brain.interfaces.web.bilingual_parity import (
    check_markdown,
    unavailable_simulations,
)
from lab_brain.interfaces.web.i18n import Messages
from lab_brain.research.render import ENGLISH, render_markdown, render_recorded_since
from lab_brain.research.report import EvidenceLine, HypothesisLine, PendingAction
from tests.report_samples import full_report

#: SHA-256 of `render_markdown(full_report())` and of `full_report(" <b>|x|</b>")` as the English
#: export read before the zh-TW rendering existed: the record's export must not move by a byte.
ENGLISH_GOLDEN = {
    "": "f5af60a0fb332b4b8c20f6aab1b48518d0b24b68d7333160bf4dcd7a7fd770e9",
    " <b>|x|</b>": "3261c316d8789b77927182ed6cf4e6108245c591b27390006c28e08f98725e1a",
}

CANONICAL = "sha256:" + "c" * 64
UNTRANSLATED = Messages("zh-TW")("tr.md_untranslated")
QUOTE_MARK = Messages("zh-TW")("tr.md_quote")

#: A sentence no catalog renders: what a language model might write.
MODEL_TEXT = "The rib's sheet resistance is not uniform; it rose by +3.5 % at -2 V (unverified)."

SIMULATOR = (
    "no simulation backend is wired in this deployment: this repository has no licensed "
    "Lumerical provider, and no Lumerical installation or licence seat is configured "
    "(TST-001, risk R-1)"
)
NEEDS = (
    "a Lumerical DEVICE/CHARGE installation with a licence seat, and the licensed provider "
    "module wired in place of the missing backend"
)


def _terms(locale: str) -> pages.Terms:
    return pages.Terms(locale, sp_presentation.presentation(), sp_presentation.PRESENTATION_REF)


def _report(inject: str = ""):  # type: ignore[no-untyped-def]
    """The full sample, with the pack's declared words where the catalog has renderings, a
    model-written sentence, and two simulations that cannot run here."""
    base = full_report(inject)
    return dataclasses.replace(
        base,
        hypotheses=(
            *base.hypotheses,
            HypothesisLine(
                hypothesis_id="hyp:catalog",
                mechanism="mesh convergence artifact",
                statement=(
                    "A mesh convergence artifact in the access region inflates the extracted "
                    "series resistance."
                ),
                falsifier="refining the access mesh leaves the extracted Rs unchanged",
                minimal_test="cap:sp.mesh_sensitivity",
                predictions=("sp.mesh_stability = UNSTABLE SUPPORTS",),
                final_state="ACTIVE",
                objections=(MODEL_TEXT,),
            ),
        ),
        evidence=(
            *base.evidence,
            EvidenceLine(
                "att:quote",
                "rs_anomaly_report.md",
                "§3 Bias dependence / Table 1.",
                "INTERNAL_MEASUREMENT",
                "The series resistance did not follow the expected trend: 12.4 ohm.mm at 0 V.",
                "internal document",
            ),
        ),
        pending=(
            PendingAction(
                "cap:sp.mesh_sensitivity",
                "SIMULATION",
                True,
                ("mesh convergence artifact -> SUPPORTED if UNSTABLE",),
                "wall clock s 240",
                SIMULATOR,
                NEEDS,
            ),
            PendingAction(
                "cap:sp.charge_dc_sweep",
                "SIMULATION",
                False,
                (),
                "wall clock s 600",
                SIMULATOR,
                NEEDS,
            ),
        ),
    )


def _pair(report=None):  # type: ignore[no-untyped-def]
    report = report if report is not None else _report()
    en = pages.markdown_export(report, (), terms=_terms("en"), canonical_digest=CANONICAL)
    zh = pages.markdown_export(report, (), terms=_terms("zh-TW"), canonical_digest=CANONICAL)
    return en, zh


@pytest.mark.parametrize("inject", sorted(ENGLISH_GOLDEN))
def test_the_english_export_is_byte_for_byte_the_record_export_it_always_was(inject):
    report = full_report(inject)
    text = render_markdown(report)
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == ENGLISH_GOLDEN[inject]
    assert render_markdown(report, ENGLISH) == text
    en = pages.markdown_export(report, (), terms=_terms("en"), canonical_digest=CANONICAL)
    assert en == text + render_recorded_since(())


def test_the_chinese_export_reads_in_chinese_and_is_in_structural_parity_with_the_english():
    report = _report()
    en, zh = _pair(report)
    result = check_markdown(en, zh, unavailable=unavailable_simulations(report))
    assert result.ok, result.findings
    assert result.aligned > 80
    assert result.untranslated > 0
    # Every science section, under a Chinese heading, in the same order.
    headings = [line for line in zh.splitlines() if line.startswith("## ")]
    for heading in (
        "## 結果",
        "## 研究步驟",
        "## 證據與來源",
        "## 互相競爭的假說",
        "## 辯論與反方審查",
        "## 各假說目前的狀態",
        "## 驗證計畫",
        "## 已完成的檢查",
        "## 等待中的模擬",
        "## 下一步",
        "## 來源追溯",
        "## 執行了什麼、沒執行什麼",
    ):
        assert heading in headings, heading
    assert not any(re.search(r"[A-Za-z]{4,}", h.removeprefix("## ")) for h in headings[:-1])


def test_curated_words_are_rendered_and_everything_else_is_shown_as_written_and_marked():
    en, zh = _pair()
    # The pack's declared mechanism, statement and falsifier: their curated renderings.
    assert "### 網格收斂假象（mesh convergence artifact） -- **ACTIVE**〔尚未判定〕" in zh
    assert "存取區的網格收斂假象使萃取出的串聯電阻（series resistance）被高估。" in zh
    # A model's sentence: exactly as written, marked, never paraphrased.
    assert f"- 反方意見：{MODEL_TEXT}{UNTRANSLATED}" in zh
    body, originals = zh.split("\n## " + Messages("zh-TW")("v.l3.originals"))
    assert body.count(MODEL_TEXT) == en.count(MODEL_TEXT) == 1
    # ... and listed after the report as having no curated translation.
    assert f"| {Messages('zh-TW')('tr.none')} | {MODEL_TEXT} |" in originals
    # Why a simulation cannot run, and what it needs: the catalog's curated sentences.
    assert "這個部署沒有接上任何模擬後端" in zh
    assert "已安裝並具授權席位的 Lumerical DEVICE/CHARGE" in zh


def test_every_unavailable_simulation_is_not_performed_with_its_reason_and_needs_in_chinese():
    report = _report()
    _, zh = _pair(report)
    lines = zh.splitlines()
    for p in report.pending:
        (at,) = [
            i
            for i, line in enumerate(lines)
            if f"`{p.capability_id}`" in line and "**BLOCKED**〔無法在此執行〕" in line
        ]
        block = "\n".join(lines[at : at + 4])
        assert "這個部署沒有接上任何模擬後端" in block
        assert "- 需要：已安裝並具授權席位的" in block


def test_identifiers_numbers_stored_values_and_quotes_are_byte_identical():
    report = _report()
    en, zh = _pair(report)
    body = zh.split("\n## " + Messages("zh-TW")("v.l3.originals"))[0]
    for ident in ("epi:full", "hyp:catalog", "att:quote", "cap:sp.mesh_sensitivity", "rrn:full"):
        assert en.count(f"`{ident}`") == body.count(f"`{ident}`"), ident
    for excerpt in (e.excerpt for e in report.evidence):
        quoted = f"'{excerpt}'"
        assert quoted in en and f"{quoted}{QUOTE_MARK}" in zh
    for value in ("-2 V", "12.4 ohm.mm", "+3.5 %", "TST-001", "R-1"):
        assert en.count(value) == body.count(value), value


def test_the_chinese_export_names_the_canonical_record_export_it_was_rendered_from():
    en, zh = _pair()
    preamble = [line for line in zh.splitlines() if line.startswith("> ")]
    assert any(CANONICAL in line for line in preamble)
    assert CANONICAL not in en, "the record's export is unchanged: it names no digest"
    # The renderings it used, beside their originals, after the report.
    tail = zh.split("\n## " + Messages("zh-TW")("v.l3.originals"))[1]
    assert sp_presentation.PRESENTATION_REF in tail
    assert "| 網格收斂假象（mesh convergence artifact） | mesh convergence artifact |" in tail


@pytest.mark.parametrize(
    ("name", "mutate", "expected"),
    [
        (
            "a quoted excerpt reworded",
            lambda zh: zh.replace("did not follow the expected trend", "followed no trend", 1),
            "ORIGINAL",
        ),
        (
            "a citation's locator changed",
            lambda zh: zh.replace("[§3 Bias dependence / Table 1.]", "[§4]", 1),
            "CITATIONS",
        ),
        (
            "a refuted hypothesis shown as supported",
            lambda zh: zh.replace(
                "**CONTRADICTED**〔已被否證（排除）〕", "**SUPPORTED**〔獲得支持〕", 1
            ),
            "STATUS",
        ),
        (
            "a stored value's words raised",
            lambda zh: zh.replace("**ACTIVE**〔尚未判定〕", "**ACTIVE**〔已確認〕", 1),
            "STATUS",
        ),
        (
            "an untranslated passage's mark removed",
            lambda zh: zh.replace(f"{MODEL_TEXT}{UNTRANSLATED}", MODEL_TEXT, 1),
            "LANGUAGE",
        ),
        (
            "a model's sentence paraphrased in Chinese",
            lambda zh: zh.replace(f"{MODEL_TEXT}{UNTRANSLATED}", "脊部片電阻均勻。", 1),
            "NEGATION",
        ),
        (
            "a sign flipped",
            lambda zh: zh.replace("+3.5 % at -2 V", "+3.5 % at 2 V", 1),
            "NUMBERS",
        ),
        (
            "a simulation's reason dropped",
            lambda zh: zh.replace("這個部署沒有接上任何模擬後端", "（略）", 2),
            "NOT_PERFORMED",
        ),
    ],
)
def test_each_way_the_chinese_export_could_go_wrong_is_caught(name, mutate, expected):
    report = _report()
    en, zh = _pair(report)
    changed = mutate(zh)
    assert changed != zh, name
    found = check_markdown(en, changed, unavailable=unavailable_simulations(report)).checks()
    assert expected in found, (name, found)


def test_hostile_text_in_every_field_stays_text_and_the_pair_still_agrees():
    report = _report(" <b>|x|</b> *y*")
    en, zh = _pair(report)
    assert "<b>|x|</b>" in zh
    result = check_markdown(en, zh, unavailable=unavailable_simulations(report))
    assert result.ok, result.findings


def test_rendering_both_languages_mutates_no_stored_report():
    report = _report()
    frozen = pickle.dumps(report)
    terms = _terms("zh-TW")
    _pair(report)
    pages.markdown_export(report, (), terms=terms, canonical_digest=CANONICAL)
    assert pickle.dumps(report) == frozen
    assert terms.presentation == sp_presentation.presentation(), "the catalog is only read"
