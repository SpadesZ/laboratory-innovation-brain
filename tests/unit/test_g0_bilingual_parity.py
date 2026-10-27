"""G0-B / G0-P: the offline structural parity check of a report's English and zh-TW renderings.

Each check is shown to pass on a controlled pair that agrees and to fail on the one change it
exists for: a hypothesis dropped from zh-TW, a sign flipped, a unit changed, a negation dropped,
a claim raised (status words, stored status, prose), an observation added in one language only,
the not-performed label or its reason omitted, an identifier changed, a field emptied, English
left unmarked in the Chinese reading, and an export that falls back to one language. Then the
product's own renderings -- `pages.episode_page` and `pages.summary_document` in both locales --
are checked as they are.

What this cannot show: whether a fluent Chinese sentence says what the English one says. A wrong
rendering with the same numbers, identifiers, negations and statuses passes; semantic quality is
NOT VERIFIED here and needs an independent bilingual reviewer.
"""

from __future__ import annotations

import dataclasses
import re

import pytest

from lab_brain.interfaces.web import pages
from lab_brain.interfaces.web.bilingual_parity import (
    CATEGORIES,
    Unavailable,
    check_html,
    check_markdown,
    compare_canonical,
    negations,
    numbers,
    unavailable_simulations,
)
from lab_brain.research.report import PendingAction
from tests.unit.test_episode_view_page import T0, _page, _report, _result, _view

SIM = Unavailable("cap:sp.mesh_sensitivity", "no simulator is wired here", "a licence seat")

EN_DOC = """<!doctype html><html lang="en"><body><main>
<section id="v-result" class="view"><h2>Current conclusion</h2>
<p><span class="state state-PROVISIONAL cs-PROVISIONAL" title="PROVISIONAL">Not confirmed</span>
The cause is not confirmed.</p></section>
<section id="v-hypotheses" class="view"><h2>Competing hypotheses</h2><ul>
<li><span class="tag tag-hyp">Hypothesis</span> <span title="hyp:a">contact gap</span>
<span class="state state-ACTIVE bs-ACTIVE" title="ACTIVE">Open</span></li>
<li><span class="tag tag-hyp">Hypothesis</span> <span title="hyp:b">mesh artefact</span>
<span class="state state-CONTRADICTED bs-CONTRADICTED" title="CONTRADICTED">Refuted (ruled out)</span>
</li></ul></section>
<section id="v-tested" class="view"><h2>Tested</h2><ul>
<li><span class="tag tag-obs">Observation</span> Rs fell by -12.5 Ω at 2 V, run <code>run:1</code></li>
<li><span title="cap:sp.mesh_sensitivity">mesh sensitivity</span>
<span class="state state-BLOCKED ws-BLOCKED" title="BLOCKED">cannot run here</span>
-- never run; its result is unknown.</li></ul></section>
<section id="v-support" class="view"><h2>Support</h2><div class="card hypothesis"><ul>
<li><span class="tag tag-pred">Prediction</span> Rs does not change with bias: contradicts it</li>
</ul></div></section>
<section id="v-why" class="view"><h2>Why</h2><ul>
<li>The excerpt does not establish the cause; the spread is 3 %.</li></ul></section>
<section id="v-next" class="view"><h2>Next</h2><div class="next">
<p>Best next: <span title="cap:sp.mesh_sensitivity">mesh sensitivity</span>.</p>
<p>no simulator is wired here; it needs a licence seat.</p></div></section>
<details id="v-reasoning" class="layer"><summary><h2>Reasoning</h2></summary><ul>
<li><code>att:1</code> report.md [§3]<blockquote>Rs did not follow the trend.</blockquote></li>
</ul></details>
<details id="v-audit" class="layer"><summary><h2>Audit</h2></summary>
<h3>Translations beside their originals</h3><p class="muted">Shown as written.</p></details>
</main></body></html>"""

ZH_DOC = """<!doctype html><html lang="zh-TW"><body><main>
<section id="v-result" class="view"><h2>目前結論</h2>
<p><span class="state state-PROVISIONAL cs-PROVISIONAL" title="PROVISIONAL">尚未確認</span>
原因尚未確認。</p></section>
<section id="v-hypotheses" class="view"><h2>互相競爭的假說</h2><ul>
<li><span class="tag tag-hyp">假說</span> <span title="hyp:a">接點缺口</span>
<span class="state state-ACTIVE bs-ACTIVE" title="ACTIVE">尚未判定</span></li>
<li><span class="tag tag-hyp">假說</span> <span title="hyp:b">網格假象</span>
<span class="state state-CONTRADICTED bs-CONTRADICTED" title="CONTRADICTED">已被否證（排除）</span>
</li></ul></section>
<section id="v-tested" class="view"><h2>檢查</h2><ul>
<li><span class="tag tag-obs">觀察</span> 在 2 V 時 Rs 下降 -12.5 Ω，執行 <code>run:1</code></li>
<li><span title="cap:sp.mesh_sensitivity">網格敏感度模擬</span>
<span class="state state-BLOCKED ws-BLOCKED" title="BLOCKED">無法在此執行</span>
——從未執行；結果仍屬未知。</li></ul></section>
<section id="v-support" class="view"><h2>支持</h2><div class="card hypothesis"><ul>
<li><span class="tag tag-pred">預測</span> Rs 不隨偏壓改變：牴觸此假說</li>
</ul></div></section>
<section id="v-why" class="view"><h2>為什麼</h2><ul>
<li>這段摘錄不足以確立原因；離散為 3 %。</li></ul></section>
<section id="v-next" class="view"><h2>下一步</h2><div class="next">
<p>最佳的下一步：<span title="cap:sp.mesh_sensitivity">網格敏感度模擬</span>。</p>
<p>這裡沒有接上模擬器；需要授權席位。</p></div></section>
<details id="v-reasoning" class="layer"><summary><h2>推理</h2></summary><ul>
<li><code>att:1</code> report.md [§3]<blockquote>Rs did not follow the trend.</blockquote></li>
</ul></details>
<details id="v-audit" class="layer"><summary><h2>稽核</h2></summary>
<h3>翻譯與原文對照</h3><table>
<tr><td>這裡沒有接上模擬器</td><td>no simulator is wired here</td><td>策展翻譯</td></tr>
<tr><td>授權席位</td><td>a licence seat</td><td>策展翻譯</td></tr></table></details>
</main></body></html>"""


def _check(zh: str = ZH_DOC, en: str = EN_DOC) -> set[str]:
    return set(check_html(en, zh, surface="fixture", unavailable=(SIM,)).checks())


def _once(old: str, new: str, doc: str = ZH_DOC) -> str:
    assert doc.count(old) == 1, old
    return doc.replace(old, new)


def test_a_pair_that_agrees_passes_every_check_and_counts_each_category():
    result = check_html(EN_DOC, ZH_DOC, surface="fixture", unavailable=(SIM,))
    assert result.ok, result.findings
    assert result.coverage["hypotheses"] == (2, 2)
    assert result.coverage["observations"] == (1, 1)
    assert result.coverage["predictions"] == (1, 1)
    assert set(result.coverage) == set(CATEGORIES)
    assert result.aligned > 20


@pytest.mark.parametrize(
    ("name", "old", "new", "expected"),
    [
        (
            "a hypothesis dropped in zh-TW",
            '<li><span class="tag tag-hyp">假說</span> <span title="hyp:b">網格假象</span>',
            '<li><span title="hyp:b">網格假象</span>',
            {"STRUCTURE", "COVERAGE"},
        ),
        ("a sign flipped", "下降 -12.5 Ω", "下降 12.5 Ω", {"NUMBERS"}),
        ("a unit changed", "下降 -12.5 Ω", "下降 -12.5 kΩ", {"NUMBERS"}),
        ("a number changed", "離散為 3 %", "離散為 8 %", {"NUMBERS"}),
        ("a negation dropped", "Rs 不隨偏壓改變", "Rs 隨偏壓改變", {"NEGATION"}),
        ("a negation dropped from a conclusion", "原因尚未確認", "原因已確認", {"NEGATION"}),
        (
            "a claim raised in the status words",
            'title="PROVISIONAL">尚未確認</span>',
            'title="PROVISIONAL">已確認</span>',
            {"STATUS"},
        ),
        (
            "a claim raised in the stored status",
            'cs-PROVISIONAL" title="PROVISIONAL">尚未確認',
            'cs-CONFIRMED" title="CONFIRMED">已確認',
            {"STATUS"},
        ),
        (
            # Only the stored status moves; the words are the original's. The word check alone
            # reads the English status and would pass this -- the status comparison must not.
            "a stored status raised under unchanged words",
            'cs-PROVISIONAL" title="PROVISIONAL">尚未確認',
            'cs-CONFIRMED" title="CONFIRMED">尚未確認',
            {"STATUS"},
        ),
        (
            "a refuted hypothesis shown as supported",
            'bs-CONTRADICTED" title="CONTRADICTED">已被否證（排除）',
            'bs-SUPPORTED" title="SUPPORTED">獲得支持',
            {"STATUS"},
        ),
        (
            "a confirmation added to the prose",
            "這段摘錄不足以確立原因",
            "這段摘錄不足以確立原因，但已確認接點缺口",
            {"CLAIM"},
        ),
        (
            "an observation added in zh-TW only",
            '</li></ul></section>\n<section id="v-support"',
            '</li><li><span class="tag tag-obs">觀察</span> 接點開路</li></ul></section>\n'
            '<section id="v-support"',
            {"STRUCTURE", "COVERAGE"},
        ),
        (
            "the not-performed label omitted",
            '<span class="state state-BLOCKED ws-BLOCKED" title="BLOCKED">無法在此執行</span>',
            "",
            {"STRUCTURE", "NOT_PERFORMED"},
        ),
        (
            "the reason a simulation did not run omitted",
            "<p>這裡沒有接上模擬器；需要授權席位。</p>",
            "<p>需要授權席位。</p>",
            {"NOT_PERFORMED"},
        ),
        (
            "an identifier changed",
            "<code>run:1</code></li>",
            "<code>run:2</code></li>",
            {"IDENTIFIERS"},
        ),
        (
            "a hypothesis's identifier changed",
            '<span title="hyp:a">接點缺口</span>',
            '<span title="hyp:c">接點缺口</span>',
            {"IDENTIFIERS"},
        ),
        (
            "a citation's excerpt emptied",
            "<blockquote>Rs did not follow the trend.</blockquote>",
            "<blockquote></blockquote>",
            {"NON_EMPTY", "NEGATION"},
        ),
        (
            "English left unmarked in the Chinese reading",
            "這段摘錄不足以確立原因；離散為 3 %。",
            "The excerpt does not establish the cause; the spread is 3 %.",
            {"LANGUAGE"},
        ),
        (
            "a curated rendering that drops the negation of its original",
            "<td>這裡沒有接上模擬器</td>",
            "<td>這裡接上模擬器</td>",
            {"NEGATION"},
        ),
    ],
)
def test_each_change_is_caught_by_its_check(name, old, new, expected):
    found = _check(_once(old, new))
    assert expected <= found, (name, found)


def test_a_passage_shown_in_english_and_marked_untranslated_is_honest_not_a_finding():
    marked = _once(
        "這段摘錄不足以確立原因；離散為 3 %。",
        '<span lang="en">The excerpt does not establish the cause; the spread is 3 %.</span>'
        '<span class="untr">（未翻譯，顯示英文原文）</span>',
    )
    result = check_html(EN_DOC, marked, surface="fixture", unavailable=(SIM,))
    assert result.ok, result.findings
    assert result.untranslated == 1


def test_an_export_that_falls_back_to_one_language_fails():
    fallback = EN_DOC.replace('<html lang="en">', '<html lang="zh-TW">')
    assert {"SINGLE_LANGUAGE", "LANGUAGE"} <= _check(fallback)
    md = "# Report\n\n- `hyp:a` is not confirmed at -12.5 Ω\n"
    result = check_markdown(md, md)
    assert result.checks() == {"SINGLE_LANGUAGE"}
    assert "byte for byte" in result.findings[0].detail


def test_markdown_pairs_are_compared_line_by_line():
    en = (
        "## Result\n\n- `hyp:a` is not confirmed at -12.5 Ω\n"
        "- `cap:sp.mesh_sensitivity` (SIMULATION) -- **BLOCKED**: no simulator is wired here\n"
        "  - requires: a licence seat\n"
    )
    zh = (
        "## 結果\n\n- `hyp:a` 在 -12.5 Ω 時尚未確認\n"
        "- `cap:sp.mesh_sensitivity`（模擬）-- **BLOCKED**：這裡沒有接上模擬器\n"
        "  - 需要：授權席位\n"
    )
    assert check_markdown(en, zh, unavailable=(SIM,)).ok
    assert "NUMBERS" in check_markdown(en, zh.replace("-12.5 Ω", "12.5 Ω")).checks()
    assert "NEGATION" in check_markdown(en, zh.replace("尚未確認", "已確認")).checks()
    assert "IDENTIFIERS" in check_markdown(en, zh.replace("`hyp:a`", "`hyp:b`")).checks()
    assert "STRUCTURE" in check_markdown(en, zh + "- 新觀察\n").checks()
    assert (
        "NOT_PERFORMED"
        in check_markdown(en, zh.replace("**BLOCKED**", "**未執行**"), unavailable=(SIM,)).checks()
    )


def test_the_field_readers_are_what_the_checks_rely_on():
    assert numbers("Rs -12.5 Ω, 2 V, 500 um, +3 %") == numbers("+3 %，500 µm，2 V，Rs -12.5 Ω")
    assert numbers("-12.5 Ω") != numbers("12.5 Ω") != numbers("12.5 kΩ")
    assert numbers("trace `trc:9f2a-77` at sha256:" + "a" * 64) == numbers("")
    assert negations("the access path stays undepleted and does not move") == 2
    assert negations("存取區接點不連續（discontinuous）") == 1, "the gloss is not counted again"
    assert negations("它的機器否證條件") == 0, "falsifying negates nothing"


def test_canonical_snapshots_name_every_table_that_changed():
    before = {"observations": "a", "attestations": "b", "research_run_reports": "c"}
    assert compare_canonical(before, dict(before)) == ()
    changed = compare_canonical(before, {**before, "research_run_reports": "d"})
    assert [(f.check, f.where) for f in changed] == [("CANONICAL", "research_run_reports")]


# -- the product's own renderings -----------------------------------------------------------------

#: Two simulations that cannot run here: the best next one, and one also sufficient.
PENDING = (
    PendingAction(
        capability_id="cap:sp.charge_ac_sweep",
        action_type="SIMULATION",
        best_next=True,
        would_decide=("DEPLETION_EFFECT -> CONTRADICTED if RS_BIAS_INSENSITIVE",),
        estimated_cost="30 s",
        blocked_because="no simulation backend is wired in this deployment",
        requires="a licence",
    ),
    PendingAction(
        capability_id="cap:sp.charge_dc_sweep",
        action_type="SIMULATION",
        best_next=False,
        would_decide=(),
        estimated_cost="40 s",
        blocked_because="no CHARGE seat is configured",
        requires="a CHARGE licence seat",
    ),
)


def _summary(locale: str) -> str:
    report = _report(pending=PENDING)
    return pages.summary_document(
        episode=pages.EpisodeRow(
            "epi:view", "prj:lab", "trc:1", "Why is Rs high?", "SUSPENDED", None, None, T0, None, 1
        ),
        runs=[pages.RunRow(1, "rrn:1", "act:1", T0, T0, "SUSPENDED:PROVISIONAL", recorded=True)],
        report=report,
        report_ordinal=1,
        view=_view(_result()),
        terms=pages.Terms(locale),
        project_name="Rs anomaly",
        source_digest="sha256:" + "0" * 64,
        exported_at=T0,
    ).decode()


def test_the_episode_page_in_both_languages_is_in_structural_parity():
    report = _report(pending=PENDING)
    en = _page(report, _view(_result()), locale="en")
    zh = _page(report, _view(_result()), locale="zh-TW")
    result = check_html(en, zh, surface="page", unavailable=unavailable_simulations(report))
    assert result.ok, result.findings
    assert result.coverage["hypotheses"][0] >= 1


def test_the_exported_summary_names_why_every_unavailable_simulation_did_not_run_in_both():
    """G0-P in the per-language export: every simulation that cannot run -- not only the best
    next one -- is named as not performed WITH its reason and what it needs, in both languages."""
    report = _report(pending=PENDING)
    en, zh = _summary("en"), _summary("zh-TW")
    result = check_html(en, zh, surface="summary", unavailable=unavailable_simulations(report))
    assert result.ok, result.findings
    for markup in (en, zh):
        assert "no CHARGE seat is configured" in markup
        assert "a CHARGE licence seat" in markup


def test_a_mutated_product_rendering_is_caught():
    report = _report(pending=PENDING)
    en = _page(report, _view(_result()), locale="en")
    zh = _page(report, _view(_result()), locale="zh-TW")
    dropped = re.sub(r'<li[^>]*><span class="tag tag-pred">.*?</li>', "", zh, count=1, flags=re.S)
    assert dropped != zh
    assert {"STRUCTURE", "COVERAGE"} <= set(check_html(en, dropped, surface="page").checks())
    raised = zh.replace('title="PROVISIONAL">尚未確認<', 'title="PROVISIONAL">已確認<', 1)
    assert raised != zh
    assert "STATUS" in check_html(en, raised, surface="page").checks()
    one_language = check_html(en, en.replace('lang="en"', 'lang="zh-TW"'), surface="page")
    assert "SINGLE_LANGUAGE" in one_language.checks()


def test_unavailable_simulations_are_read_from_the_canonical_report():
    report = dataclasses.replace(_report(), pending=PENDING)
    assert [u.capability_id for u in unavailable_simulations(report)] == [
        "cap:sp.charge_ac_sweep",
        "cap:sp.charge_dc_sweep",
    ]
