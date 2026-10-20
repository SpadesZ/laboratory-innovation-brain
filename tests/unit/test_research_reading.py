"""How a researcher reads a result: in their language, in the order they ask, and never more
certain than the record.

    language      with the Silicon Photonics pack's curated renderings, the zh-TW primary view
                  reads in Traditional Chinese with the English scientific terms beside it, and
                  neither locale shows a stored status, outcome or identifier as such
    untranslated  text without a curated rendering -- what a language model wrote -- is shown as
                  written, marked, counted, and listed beside its original; never guessed
    record        rendering changes no record: the full report stays as written, and every
                  rendering the page used sits beside its original in the audit layer
    kinds         L1 marks each line as a hypothesis, prediction, observation, interpretation
                  or confirmed finding -- and only a confirmation carries the last
    why           the page says why the system can or cannot conclude: rivals still open, support
                  that is not confirmation, conflicting evidence, checks that never ran (unknown,
                  nothing assumed in their place), and who reasoned, from inference provenance
    next          what a check that has not run would decide comes from the declared predictions
    summary       the exported summary is a derived document that names its source's digest and
                  the renderings it used, and carries no form

The same reading over real stored episodes, through the web workspace and PostgreSQL, is in
`tests/e2e/test_web_research_reading_postgres.py`.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import html
import re

from lab_brain.domains.silicon_photonics import diagnosis, product
from lab_brain.domains.silicon_photonics import vertical as sp
from lab_brain.interfaces.web import pages
from lab_brain.research.episode_view import (
    CheckResult,
    DeclaredPrediction,
    EpisodeView,
    ExecutedCheck,
    Relation,
    Transition,
)
from lab_brain.research.report import (
    ActionLine,
    Conclusion,
    EpisodeReport,
    HypothesisLine,
    PendingAction,
    PlanLine,
)
from tests.report_samples import full_report

T0 = dt.datetime(2026, 10, 20, 9, 0, tzinfo=dt.UTC)
VERTICAL = product.product_vertical(outputs=None, jobs=None, broker=None, now=lambda: T0)
MECHANISMS = {m.key: m for m in VERTICAL.catalog.mechanisms}
#: Every stored value L1 must name in words, never show as stored.
STORED = (
    "ACTIVE",
    "SUPPORTED",
    "CONTRADICTED",
    "CHALLENGED",
    "PROVISIONAL",
    "CONFIRMED",
    "EXECUTED",
    "BLOCKED",
    "ALLOW",
    "SUPPORTS",
    "CONTRADICTS",
    *(o for space in sp.outcome_spaces() for o in space.outcomes),
)
IDENTIFIER = re.compile(r"\b(?:epi|hyp|prd|run|obs|att|rel|bre|dec|cap|rrn|vpl|dbt):\S")
MODEL_WRITTEN = "hot-carrier trapping at the buried-oxide interface"


def _terms(locale: str) -> pages.Terms:
    return pages.Terms(
        locale,
        VERTICAL.presentation,
        VERTICAL.presentation_ref,
        {c.capability_id: c.produces for c in VERTICAL.planning_capabilities},
        {c.capability_id: c.action_type.value for c in VERTICAL.planning_capabilities},
    )


def _text(markup: str) -> str:
    inline = re.sub(r"</?(?:code|strong|span|a|time)\b[^>]*>", "", markup)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", inline)).split())


def _l1(markup: str) -> str:
    main = re.search(r"<main.*?</main>", markup, flags=re.S)
    assert main is not None
    return _text(
        re.sub(r'<details id="v-[a-z]+" class="layer">.*?</details>', "", main.group(0), flags=re.S)
    )


def _section(markup: str, key: str) -> str:
    found = re.search(rf'<section id="v-{key}" class="view">.*?</section>', markup, flags=re.S)
    assert found is not None, key
    return _text(found.group(0))


def _predictions(key: str) -> tuple[DeclaredPrediction, ...]:
    m = MECHANISMS[key]
    return tuple(
        DeclaredPrediction(
            hypothesis_id=f"hyp:{key}",
            mechanism=m.mechanism,
            prediction_id=f"prd:{key}.{p.key}",
            observable=p.observable_ref,
            outcome_space=f"{p.outcome_space_id}@{p.outcome_space_version}",
            expected_outcome=p.expected_outcome,
            effects=(p.relation_effect,),
            designated_falsifier=p.key in m.falsifier_prediction_keys,
        )
        for p in m.predictions
    )


def _line(key: str, state: str, objections: tuple[str, ...] = ()) -> HypothesisLine:
    m = MECHANISMS[key]
    return HypothesisLine(
        hypothesis_id=f"hyp:{key}",
        mechanism=m.mechanism,
        statement=m.statement,
        falsifier=m.falsifier,
        minimal_test=m.minimal_test_ref,
        predictions=(),
        final_state=state,
        objections=objections,
    )


def _observed(
    key: str, run: str, outcome: str, relation: str, *, to_state: str | None
) -> CheckResult:
    """One check's outcome, matched to `key`'s prediction of it, with the governed move (if
    `to_state`) the relation triggered."""
    declared = _predictions(key)
    matched = tuple(p for p in declared if p.expected_outcome == outcome)
    moves = (
        (
            Transition(
                f"bre:{key}",
                f"hyp:{key}",
                MECHANISMS[key].mechanism,
                "ACTIVE",
                to_state,
                "tp@1",
                f"dec:{key}",
                "ALLOW",
            ),
        )
        if to_state
        else ()
    )
    return CheckResult(
        run_id=run,
        observation_id=f"obs:{run}",
        attestation_id=f"att:{run}",
        epistemic_type="OBSERVED",
        observable=declared[0].observable,
        outcome=outcome,
        outcome_space=declared[0].outcome_space,
        matched=matched,
        unmatched=tuple(p for p in declared if p not in matched),
        relations=tuple(
            Relation(
                f"rel:{run}.{p.prediction_id}",
                relation,
                f"hyp:{key}",
                MECHANISMS[key].mechanism,
                p.prediction_id,
                moves,
                (),
            )
            for p in matched
        ),
    )


def _blocked(capability: str, best: bool) -> PendingAction:
    return PendingAction(
        capability_id=capability,
        action_type="SIMULATION",
        best_next=best,
        would_decide=("mesh convergence artifact -> SUPPORTED if UNSTABLE",),
        estimated_cost="30 s",
        blocked_because=product.SIMULATOR_UNAVAILABLE,
        requires=product.SIMULATOR_REQUIRES,
    )


def _insufficient() -> tuple[EpisodeReport, EpisodeView]:
    """The pre-Lumerical case: both design checks ran and refuted two rivals; the three left
    need simulations that cannot run here and a measurement a person makes."""
    connectivity = _observed(
        "contact_discontinuity",
        "run:conn",
        diagnosis.CONTINUOUS,
        "CONTRADICTS",
        to_state="CONTRADICTED",
    )
    normalization = _observed(
        "normalization_error", "run:norm", diagnosis.AGREES, "CONTRADICTS", to_state="CONTRADICTED"
    )
    report = dataclasses.replace(
        full_report(),
        episode_id="epi:rs",
        goal="Why is Rs extremely high and weakly bias dependent?",
        hypotheses=(
            _line("contact_discontinuity", "CONTRADICTED"),
            _line("normalization_error", "CONTRADICTED"),
            _line("mesh_artifact", "ACTIVE", ("MISSING_CONTROL: no mesh refinement study",)),
            _line("dopant_compensation", "ACTIVE"),
            _line("probe_artifact", "ACTIVE"),
        ),
        plans=(PlanLine("vpl:1", "ACT", sp.CAP_FOURPOINT_PROBE, "a person's act", ()),),
        completed=(
            ActionLine(
                sp.CAP_INSPECT_CONNECTIVITY,
                "ANALYTICAL_RULE_CHECK",
                "EXECUTED",
                "job:1",
                "run:conn",
                "reader",
                (),
            ),
            ActionLine(
                sp.CAP_EXTRACTION_CONSISTENCY,
                "ANALYTICAL_RULE_CHECK",
                "EXECUTED",
                "job:2",
                "run:norm",
                "reader",
                (),
            ),
        ),
        pending=(_blocked(sp.CAP_MESH_SENSITIVITY, True), _blocked(sp.CAP_CHARGE_DC, False)),
        conclusion=Conclusion(status="PROVISIONAL", statement="not confirmed; 3 remain"),
        continuation=None,
    )
    view = EpisodeView(
        executed=(
            ExecutedCheck("run:conn", sp.CAP_INSPECT_CONNECTIVITY, "SUCCEEDED", T0),
            ExecutedCheck("run:norm", sp.CAP_EXTRACTION_CONSISTENCY, "SUCCEEDED", T0),
        ),
        results={"run:conn": (connectivity,), "run:norm": (normalization,)},
        predictions={f"hyp:{k}": _predictions(k) for k in MECHANISMS},
        action_types={sp.CAP_FOURPOINT_PROBE: "MEASUREMENT"},
    )
    return report, view


def _page(report: EpisodeReport, view: EpisodeView, locale: str, *, terms: bool = True) -> str:
    return pages.episode_page(
        actor_id="act:1",
        episode=pages.EpisodeRow(
            report.episode_id,
            "prj:lab",
            "trc:1",
            report.goal,
            "SUSPENDED",
            None,
            f"awaiting simulator for {sp.CAP_MESH_SENSITIVITY}",
            T0,
            None,
            1,
        ),
        runs=[pages.RunRow(1, "rrn:1", "act:1", T0 + dt.timedelta(minutes=1), T0, None, True)],
        report=report,
        report_ordinal=1,
        csrf="tok",
        continuable=True,
        view=view,
        chrome=pages.Chrome("act:1", locale),
        terms=_terms(locale) if terms else None,
    ).decode()


def _english_share(text: str) -> float:
    runs = re.findall(r"[A-Za-z][A-Za-z'\-]*(?:[ ,;:()/]+[A-Za-z][A-Za-z'\-]*){2,}", text)
    return sum(len(r) for r in runs) / max(len(text), 1)


def test_zh_tw_reads_in_chinese_with_english_terms_and_no_stored_value_shown_as_such():
    report, view = _insufficient()
    markup = _page(report, view, "zh-TW")
    l1 = _l1(markup)
    for rendering in (
        "網格收斂假象（mesh convergence artifact）",
        "存取區或接點的不連續主導了串聯電阻（series resistance, Rs）。",
        "接點連通性（contact connectivity） = 連續（continuous）",
        "已被否證（排除）",
        "尚未判定",
        "這個部署沒有接上任何模擬後端",
    ):
        assert rendering in l1, rendering
    assert "未翻譯" not in l1, "every word here is the pack's, and the pack renders all of it"
    for value in STORED:
        assert not re.search(rf"(?<![A-Za-z_]){value}(?![A-Za-z_])", l1), value
    assert not IDENTIFIER.findall(l1), IDENTIFIER.findall(l1)
    # The English left is the terms kept beside the Chinese, and the researcher's own question.
    assert _english_share(l1.replace(report.goal, "")) < 0.25, _english_share(l1)


def test_english_reads_in_words_too():
    report, view = _insufficient()
    l1 = _l1(_page(report, view, "en"))
    assert "mesh sensitivity simulation (simulation)" in l1
    assert "contact connectivity inspection: observed contact connectivity = continuous" in l1
    for value in STORED:
        assert not re.search(rf"(?<![A-Za-z_]){value}(?![A-Za-z_])", l1), value
    assert not IDENTIFIER.findall(l1)


def test_model_written_text_is_shown_as_written_marked_and_listed_never_guessed():
    report, view = _insufficient()
    model = dataclasses.replace(
        report.hypotheses[2],
        hypothesis_id="hyp:model",
        mechanism=MODEL_WRITTEN,
        statement="Trapped hot carriers raise the access resistance.",
    )
    report = dataclasses.replace(report, hypotheses=(*report.hypotheses, model))
    markup = _page(report, view, "zh-TW")
    l1 = _l1(markup)
    assert f"{MODEL_WRITTEN}（未翻譯，顯示英文原文）" in l1
    assert "Trapped hot carriers raise the access resistance.（未翻譯，顯示英文原文）" in l1
    assert "本頁有 2 段文字沒有經策展的中文翻譯" in l1
    audit = _text(markup[markup.index('<details id="v-audit"') :])
    assert f"（無翻譯） {MODEL_WRITTEN} 無策展翻譯：以英文原文顯示" in audit
    english = _l1(_page(report, view, "en"))
    assert MODEL_WRITTEN in english and "untranslated" not in english


def test_rendering_changes_no_record_and_each_rendering_sits_beside_its_original():
    report, view = _insufficient()
    before = dataclasses.replace(report)
    markup = _page(report, view, "zh-TW")
    assert report == before
    audit = markup[markup.index('<details id="v-audit"') :]
    assert pages.report_html(report, locale="zh-TW") in audit, "the full report, as written"
    assert "網格收斂假象（mesh convergence artifact） mesh convergence artifact 策展翻譯" in _text(
        audit
    )
    assert "sp.presentation@1.0.0" in _text(audit)
    # Without the pack's renderings nothing is invented: the words are shown as written.
    bare = _l1(_page(report, view, "zh-TW", terms=False))
    assert "mesh convergence artifact（未翻譯，顯示英文原文）" in bare


def test_l1_marks_each_kind_of_line_and_only_a_confirmation_is_a_finding():
    report, view = _insufficient()
    l1 = _l1(_page(report, view, "zh-TW"))
    for tag in ("假說", "預測", "觀察", "解讀"):
        assert tag in l1, tag
    assert "已確認的發現" not in l1
    confirmed = _confirmed()
    result = _section(_page(*confirmed, "zh-TW"), "result")
    assert result.startswith("目前結論 目前狀態：")
    assert "已確認的發現 已確認 根本原因：網格收斂假象（mesh convergence artifact）" in result


def test_why_names_what_is_open_and_every_check_that_never_ran():
    report, view = _insufficient()
    why = _section(_page(report, view, "zh-TW"), "why")
    assert "系統目前還不能下結論" in why
    assert (
        "仍有 3 個假說尚未判定（未獲支持，也未排除）：網格收斂假象（mesh convergence artifact）"
        in why
    )
    assert (
        "以下檢查沒有執行，結果未知、未經驗證，也沒有以任何假設值代替："
        "網格敏感度模擬（mesh sensitivity）（模擬）、CHARGE 直流掃描模擬（DC sweep）（模擬）" in why
    )
    assert "等待人員執行：四點探針量測（four-point probe）" in why
    assert "假說與反方審查來自本機的規則式目錄推理器，沒有使用語言模型。" in why
    assert "證據不足時，系統不會宣告確認" in why
    hypotheses = _section(_page(report, view, "zh-TW"), "hypotheses")
    assert "尚未檢驗。能檢驗它的是網格敏感度模擬" in hypotheses
    assert "這裡無法執行，結果未知（未驗證）" in hypotheses


def test_why_says_support_is_not_confirmation_and_names_conflicting_evidence():
    report, view = _insufficient()
    supported = _observed(
        "probe_artifact", "run:probe", diagnosis.ELEVATED, "SUPPORTS", to_state="SUPPORTED"
    )
    # The same hypothesis, challenged by a second reading of the same observable.
    against = _observed(
        "probe_artifact", "run:probe2", diagnosis.NOMINAL, "CONTRADICTS", to_state=None
    )
    report = dataclasses.replace(
        report,
        hypotheses=tuple(
            dataclasses.replace(x, final_state="SUPPORTED")
            if x.hypothesis_id == "hyp:probe_artifact"
            else x
            for x in report.hypotheses
        ),
        completed=(
            *report.completed,
            ActionLine(
                sp.CAP_FOURPOINT_PROBE,
                "MEASUREMENT",
                "EXECUTED",
                "job:3",
                "run:probe",
                "probe station",
                (),
            ),
            ActionLine(
                sp.CAP_FOURPOINT_PROBE,
                "MEASUREMENT",
                "EXECUTED",
                "job:4",
                "run:probe2",
                "probe station",
                (),
            ),
        ),
        plans=(),
    )
    view = dataclasses.replace(
        view, results={**view.results, "run:probe": (supported,), "run:probe2": (against,)}
    )
    markup = _page(report, view, "zh-TW")
    why = _section(markup, "why")
    assert (
        "「量測探針接觸假象（probe contact artifact）」獲得支持；但只要仍有對立假說未被排除，支持就不等於確認"
        in why
    )
    assert "關於「量測探針接觸假象（probe contact artifact）」的證據互相矛盾" in why
    support = _section(markup, "support")
    card = support[support.index("量測探針接觸假象（probe contact artifact） 獲得支持") :]
    assert "支持它的觀察 觀察 四點探針量測" in card
    assert "挑戰它的觀察 觀察 四點探針量測" in card
    assert "這個關係沒有任何經治理程序的狀態轉移紀錄" in card, "a relation nothing acted on"


def _confirmed() -> tuple[EpisodeReport, EpisodeView]:
    """Every rival refuted and the mesh artifact supported: a confirmation, from its record."""
    report, view = _insufficient()
    mesh = _observed(
        "mesh_artifact", "run:mesh", diagnosis.UNSTABLE, "SUPPORTS", to_state="SUPPORTED"
    )
    report = dataclasses.replace(
        report,
        hypotheses=tuple(
            dataclasses.replace(
                x,
                final_state="SUPPORTED"
                if x.hypothesis_id == "hyp:mesh_artifact"
                else "CONTRADICTED",
            )
            for x in report.hypotheses
        ),
        completed=(
            *report.completed,
            ActionLine(
                sp.CAP_MESH_SENSITIVITY, "SIMULATION", "EXECUTED", "job:5", "run:mesh", "solver", ()
            ),
        ),
        pending=(),
        plans=(),
        conclusion=Conclusion(
            status="CONFIRMED", statement="confirmed", confirmed_hypothesis="hyp:mesh_artifact"
        ),
    )
    return report, dataclasses.replace(view, results={**view.results, "run:mesh": (mesh,)})


def test_why_explains_a_confirmation_from_its_record():
    why = _section(_page(*_confirmed(), "zh-TW"), "why")
    assert "系統可以下結論" in why
    assert "已被觀察否證的對立假說：存取區接點不連續（access contact discontinuity）" in why
    assert "限制：本研究從未檢驗的對立假說" not in why, "every rival here was refuted"
    assert (
        "支持的觀察：網格敏感度模擬（mesh sensitivity）：觀察到 "
        "網格收斂穩定性（mesh stability） = 不穩定（unstable）" in why
    )
    assert "以下檢查沒有執行" not in why


def test_the_language_models_that_reasoned_are_named_from_inference_provenance():
    report, view = _insufficient()
    assert report.debate is not None
    report = dataclasses.replace(
        report,
        debate=dataclasses.replace(
            report.debate,
            reasoner="language model: REASONING_ADVERSARIAL -> qwen2.5:7b@845dbda0 via ollama; "
            "REASONING_PRIMARY -> qwen2.5:14b@7cdf5a0 via ollama",
        ),
    )
    zh = _section(_page(report, view, "zh-TW"), "why")
    assert (
        "假說與反方審查由語言模型產生（依推論來源紀錄）：獨立批判：qwen2.5:7b@845dbda0 via ollama、"
        "主要推理：qwen2.5:14b@7cdf5a0 via ollama。" in zh
    )
    en = _section(_page(report, view, "en"), "why")
    assert "Primary reasoning: qwen2.5:14b@7cdf5a0 via ollama" in en


def test_what_an_unrun_check_would_decide_comes_from_the_declared_predictions():
    report, view = _insufficient()
    nxt = _section(_page(report, view, "zh-TW"), "next")
    assert "最佳的下一項檢查：網格敏感度模擬（mesh sensitivity）（模擬）。" in nxt
    assert (
        "若 網格收斂穩定性（mesh stability） = 不穩定（unstable）："
        "支持「網格收斂假象（mesh convergence artifact）」" in nxt
    )
    assert (
        "若 網格收斂穩定性（mesh stability） = 穩定（stable）："
        "否證「網格收斂假象（mesh convergence artifact）」" in nxt
    )
    assert "需要：已安裝並具授權席位的 Lumerical DEVICE/CHARGE，以及" in nxt
    assert "SUPPORTED if UNSTABLE" not in nxt, "derived from the predictions, not the run's prose"


def test_the_summary_is_a_derived_document_naming_its_source_and_carrying_no_form():
    report, view = _insufficient()
    document = pages.summary_document(
        episode=pages.EpisodeRow(
            report.episode_id,
            "prj:lab",
            "trc:1",
            report.goal,
            "SUSPENDED",
            None,
            None,
            T0,
            None,
            1,
        ),
        runs=[pages.RunRow(1, "rrn:1", "act:1", T0 + dt.timedelta(minutes=1), T0, None, True)],
        report=report,
        report_ordinal=1,
        view=view,
        terms=_terms("zh-TW"),
        project_name="Ring resonator drift",
        source_digest="sha256:" + "ab" * 32,
        exported_at=T0,
    ).decode()
    assert document.startswith('<!doctype html><html lang="zh-TW">')
    assert "<form" not in document and "<script" not in document
    text = _text(document)
    positions = [
        text.index(heading)
        for heading in (
            "研究摘要（衍生文件）",
            "目前結論",
            "互相競爭的假說與各自的證據狀態",
            "實際做了哪些檢查、觀察到什麼",
            "支持或挑戰各假說的證據",
            "為什麼能（或不能）下結論",
            "下一步該做什麼",
            "本摘要的來源",
        )
    ]
    assert positions == sorted(positions)
    provenance = text[text.index("本摘要的來源") :]
    assert "由第 1 次執行所記錄的報告衍生" in provenance
    assert "sha256:" + "ab" * 32 in provenance
    assert "sp.presentation@1.0.0" in provenance
    assert "以英文原文顯示的段落數（無策展翻譯） 0" in provenance
