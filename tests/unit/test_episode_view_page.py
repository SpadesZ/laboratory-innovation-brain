"""The episode page reads in layers: L1 in words, L2 the reasoning, L3 the full audit.

    order          question, result, competing hypotheses, what was tested, what was learned,
                   next action -- then evidence and reasoning, then audit and provenance
    disclosure     L1 is open; L2 and L3 are collapsed `<details>`
    identifiers    L1 shows no record identifier; L3 shows every one, and the full report
    explanations   what an observed outcome did comes from the typed read model only: no declared
                   prediction matched (nothing moved), a match with its governed transition, a
                   match the policy refused, a match with no decision recorded, no prediction about
                   the observable at all, and no observation recorded -- each said as such
    history        a report from before machine falsifiers, and no report at all, render without
                   anything invented
    continuation   a check an earlier run executed is shown as such, never as executed again, and
                   its belief changes are not counted for this run
    i18n           every new message exists in both locales, and the headings follow the locale
    escaping       nothing a model, a report or a record supplies becomes markup

The same view over real stored episodes, through the web workspace and PostgreSQL, is in
`tests/e2e/test_web_episode_view_postgres.py`.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import html
import re

from lab_brain.core.models import RelationJudgmentTemplate, RelationType
from lab_brain.core.models.enums import EpistemicType
from lab_brain.core.models.prediction import Prediction
from lab_brain.interfaces.web import i18n, pages
from lab_brain.research.episode_view import (
    CheckResult,
    Decision,
    DeclaredPrediction,
    EpisodeView,
    ExecutedCheck,
    Relation,
    Transition,
    _split,
)
from lab_brain.research.report import (
    ActionLine,
    Conclusion,
    ContinuationSection,
    EpisodeReport,
    HypothesisLine,
    PendingAction,
    PlanLine,
)
from lab_brain.verification.workflows import ObservedOutcome
from tests.report_samples import full_report

HOSTILE = '<script>alert("x")</script><img src=x onerror=alert(1)>'
T0 = dt.datetime(2026, 10, 8, 9, 0, tzinfo=dt.UTC)
L1_ORDER = ("v-question", "v-result", "v-hypotheses", "v-tested", "v-learned", "v-next")
IDENTIFIER = re.compile(
    r"\b(?:epi|hyp|prd|run|job|obs|att|rel|bre|dec|art|cap|lrt|inf|rrn|vpl|bdl|crq|dbt|fan|hst):\S"
)


def _text(markup: str) -> str:
    inline = re.sub(r"</?(?:code|strong|span|a|time)\b[^>]*>", "", markup)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", inline)).split())


def _l1(markup: str) -> str:
    """What a reader sees before opening anything: every collapsed layer removed."""
    main = re.search(r"<main.*?</main>", markup, flags=re.S)
    assert main is not None
    return _text(
        re.sub(r'<details id="v-[a-z]+" class="layer">.*?</details>', "", main.group(0), flags=re.S)
    )


def _prediction(
    hypothesis: str, mechanism: str, outcome: str, effect: str, *, designated: bool, n: str = "1"
) -> DeclaredPrediction:
    return DeclaredPrediction(
        hypothesis_id=f"hyp:{hypothesis}",
        mechanism=mechanism,
        prediction_id=f"prd:{hypothesis}.{n}",
        observable="sp.normalization_basis",
        outcome_space="os:sp.normalization_basis@1.0.0",
        expected_outcome=outcome,
        effects=(effect,),
        designated_falsifier=designated,
    )


FALSIFIER = _prediction(
    "norm", "NORMALIZATION_BASIS_ISSUE", "DISAGREES", "CONTRADICTS", designated=True
)
#: Declared, but not the falsifier: what the hypothesis expects, not what would refute it.
SUPPORTING = _prediction(
    "norm", "NORMALIZATION_BASIS_ISSUE", "SPLIT_DEPENDENT", "SUPPORTS", designated=False, n="2"
)


def _result(**over: object) -> CheckResult:
    base = CheckResult(
        run_id="run:check",
        observation_id="obs:check",
        attestation_id="att:check",
        epistemic_type="OBSERVED",
        observable="sp.normalization_basis",
        outcome="AGREES",
        outcome_space="os:sp.normalization_basis@1.0.0",
        matched=(),
        unmatched=(FALSIFIER,),
        relations=(),
    )
    return dataclasses.replace(base, **over)


def _report(**over: object) -> EpisodeReport:
    """One run of a suspended episode: one executed check, a blocked simulation, a person's act."""
    base = dataclasses.replace(
        full_report(),
        episode_id="epi:view",
        goal="Why is Rs high?",
        hypotheses=(
            HypothesisLine(
                hypothesis_id="hyp:norm",
                mechanism="NORMALIZATION_BASIS_ISSUE",
                statement="A normalization basis issue.",
                falsifier="The normalization basis agrees between splits A and B.",
                minimal_test="cap:sp.extraction_consistency",
                predictions=("sp.normalization_basis = DISAGREES -> CONTRADICTS",),
                final_state="ACTIVE",
                objections=("MISSING_CONTROL: no control",),
                machine_falsifiers=("rendered at report time",),
            ),
        ),
        plans=(
            PlanLine("vpl:1", "ACT", "cap:sp.extraction_consistency", "sufficient", ("a", "b")),
            PlanLine("vpl:2", "ACT", "cap:sp.fourpoint_probe", "a person's act", ("c",)),
        ),
        completed=(
            ActionLine(
                capability_id="cap:sp.extraction_consistency",
                action_type="ANALYTICAL_RULE_CHECK",
                status="EXECUTED",
                job_id="job:check",
                run_id="run:check",
                backend="reader",
                outcomes=("sp.normalization_basis = **AGREES** (as recorded)",),
            ),
        ),
        pending=(
            PendingAction(
                capability_id="cap:sp.charge_ac_sweep",
                action_type="SIMULATION",
                best_next=True,
                would_decide=("DEPLETION_EFFECT -> CONTRADICTED if RS_BIAS_INSENSITIVE",),
                estimated_cost="30 s",
                blocked_because="no simulation backend is wired in this deployment",
                requires="a licence",
            ),
        ),
        conclusion=Conclusion(status="PROVISIONAL", statement="not confirmed; 1 remains"),
        continuation=None,
    )
    return dataclasses.replace(base, **over)


def _view(*results: CheckResult, executed: tuple[ExecutedCheck, ...] | None = None) -> EpisodeView:
    return EpisodeView(
        executed=executed
        if executed is not None
        else (ExecutedCheck("run:check", "cap:sp.extraction_consistency", "SUCCEEDED", T0),),
        results={"run:check": results} if results else {},
        predictions={"hyp:norm": (FALSIFIER, SUPPORTING)},
        action_types={"cap:sp.fourpoint_probe": "MEASUREMENT"},
    )


def _page(
    report: EpisodeReport | None = None,
    view: EpisodeView | None = None,
    *,
    locale: str = "en",
    runs: list[pages.RunRow] | None = None,
    ordinal: int = 1,
) -> str:
    return pages.episode_page(
        actor_id="act:1",
        episode=pages.EpisodeRow(
            "epi:view",
            "prj:lab",
            "trc:1",
            "Why is Rs high?",
            "SUSPENDED",
            None,
            "awaiting simulator for cap:sp.charge_ac_sweep",
            T0,
            None,
            1,
        ),
        runs=runs
        or [pages.RunRow(1, "rrn:1", "act:1", T0, T0, "SUSPENDED:PROVISIONAL", recorded=True)],
        report=report,
        report_ordinal=ordinal,
        csrf="tok",
        continuable=True,
        view=view,
        chrome=pages.Chrome("act:1", locale),
    ).decode()


def test_l1_reads_in_the_researchers_order_and_the_deeper_layers_are_collapsed():
    markup = _page(_report(), _view(_result()))
    positions = [markup.index(f'id="{key}"') for key in (*L1_ORDER, "v-reasoning", "v-audit")]
    assert positions == sorted(positions)
    for key in ("v-reasoning", "v-audit"):
        assert re.search(rf'<details id="{key}" class="layer">', markup), key
        assert not re.search(rf'<details id="{key}"[^>]*\bopen\b', markup), "collapsed by default"
    for key in L1_ORDER:
        before = markup[: markup.index(f'id="{key}"')]
        assert before.count("<details") == before.count("</details>"), (
            f"{key} is not inside a layer"
        )


def test_l1_shows_no_record_identifier_and_l3_shows_every_one():
    result = _result(
        matched=(dataclasses.replace(FALSIFIER, expected_outcome="AGREES"),),
        unmatched=(),
        relations=(
            Relation(
                "rel:1",
                "CONTRADICTS",
                "hyp:norm",
                "NORMALIZATION_BASIS_ISSUE",
                "prd:norm.1",
                (
                    Transition(
                        "bre:1",
                        "hyp:norm",
                        "NORMALIZATION_BASIS_ISSUE",
                        "ACTIVE",
                        "CONTRADICTED",
                        "policy:reject@1.0.0",
                        "dec:1",
                        "ALLOW",
                    ),
                ),
                (),
            ),
        ),
    )
    report = _report()
    markup = _page(report, _view(result))
    l1 = _l1(markup)
    assert not IDENTIFIER.findall(l1), IDENTIFIER.findall(l1)
    audit = markup[markup.index('<details id="v-audit"') :]
    for record in (
        "run:check",
        "obs:check",
        "att:check",
        "rel:1",
        "prd:norm.1",
        "bre:1",
        "dec:1",
        "rrn:1",
        "epi:view",
        "trc:1",
    ):
        assert record in audit, record
    assert pages.report_html(report) in audit, "the full report, exactly as before"


def test_a_result_no_declared_prediction_matched_moves_nothing_and_is_said_so():
    l1 = _l1(_page(_report(), _view(_result())))
    assert "normalization basis = AGREES matched no declared prediction" in l1
    assert "neither supports nor contradicts any hypothesis, and no belief could move" in l1
    assert "NORMALIZATION_BASIS_ISSUE: DISAGREES -> CONTRADICTS, its machine falsifier" in l1
    assert "No governed belief change happened in this run." in l1
    assert "Would be refuted if normalization basis = DISAGREES" in l1
    assert "Would be refuted if normalization basis = SPLIT_DEPENDENT" not in l1, "not designated"
    assert "No root cause has been confirmed." in l1
    assert (
        "The author's own explanation, in prose (not adjudicated): The normalization basis agrees"
        in l1
    )


def _matched(*decisions: Decision, transitions: tuple[Transition, ...] = ()) -> CheckResult:
    agrees = dataclasses.replace(FALSIFIER, expected_outcome="AGREES")
    return _result(
        matched=(agrees,),
        unmatched=(),
        relations=(
            Relation(
                "rel:1",
                "CONTRADICTS",
                "hyp:norm",
                "NORMALIZATION_BASIS_ISSUE",
                agrees.prediction_id,
                transitions,
                decisions,
            ),
        ),
    )


def test_a_matched_falsifier_its_governed_transition_or_why_there_was_none():
    moved = Transition(
        "bre:1",
        "hyp:norm",
        "NORMALIZATION_BASIS_ISSUE",
        "ACTIVE",
        "CONTRADICTED",
        "p@1",
        "dec:1",
        "ALLOW",
    )
    l1 = _l1(_page(_report(), _view(_matched(transitions=(moved,)))))
    assert (
        "normalization basis = AGREES matched NORMALIZATION_BASIS_ISSUE's declared prediction "
        "(AGREES -> CONTRADICTS), its machine falsifier." in l1
    )
    assert (
        "NORMALIZATION_BASIS_ISSUE: ACTIVE -> CONTRADICTED, a governed transition (decision: ALLOW)."
        in l1
    )
    assert "1 governed belief change(s) happened in this run." in l1
    refused = Decision("dec:2", "hyp:norm", "NEED_HUMAN_REVIEW", "p@1", "ACTIVE", "CONTRADICTED")
    l1 = _l1(_page(_report(), _view(_matched(refused))))
    assert "its transition policy decided NEED_HUMAN_REVIEW; its state did not change" in l1
    assert "No governed belief change happened in this run." in l1
    l1 = _l1(_page(_report(), _view(_matched())))
    assert "no governed transition is recorded for this relation" in l1


def test_no_prediction_about_the_observable_or_no_observation_recorded_is_said_as_such():
    l1 = _l1(_page(_report(), _view(_result(unmatched=()))))
    assert "No hypothesis declared a prediction about normalization basis" in l1
    l1 = _l1(_page(_report(), _view()))
    assert "no observed outcome is recorded for it" in l1
    assert "The stored records do not say what this result meant for the hypotheses." in l1


def test_the_tested_and_next_sections_separate_executed_human_and_unavailable_checks():
    l1 = _l1(_page(_report(), _view(_result())))
    executed = l1[l1.index("Executed in this run") : l1.index("Planned, needs a person")]
    assert (
        "extraction consistency (analytical check) EXECUTED -- observed normalization basis = AGREES"
        in executed
    )
    person = l1[l1.index("Planned, needs a person") : l1.index("Cannot run here")]
    assert "fourpoint probe (measurement)" in person
    assert "extraction consistency" not in person, "executed already, not a person's to do"
    assert (
        "charge ac sweep (simulation) BLOCKED"
        in l1[l1.index("Cannot run here") : l1.index("What was learned")]
    )
    nxt = l1[l1.index("Next action") :]
    assert (
        "Best next check: charge ac sweep (simulation). It cannot run here: no simulation backend"
        in nxt
    )
    assert "DEPLETION_EFFECT -> CONTRADICTED if RS_BIAS_INSENSITIVE" in nxt
    assert "A person can act now: fourpoint probe (measurement)." in nxt
    assert "The critic raised 1 objection(s)" in l1, "critique, kept apart from belief changes"


def test_a_historical_report_and_no_report_render_without_anything_invented():
    old = _report(
        hypotheses=tuple(
            dataclasses.replace(x, machine_falsifiers=()) for x in _report().hypotheses
        )
    )
    l1 = _l1(_page(old, EpisodeView()))
    assert "No machine falsifier is recorded for this hypothesis." in l1
    assert "The stored records do not say what this result meant" in l1
    recorded = _l1(_page(_report(), EpisodeView()))
    assert "Machine falsifier, as the run recorded it: rendered at report time" in recorded
    empty = _l1(_page(None, None))
    assert "No report of this research was recorded in the workspace." in empty
    assert "what it tested and learned is not known here" in empty
    assert "No check was executed" not in empty, "an unrecorded run is not an empty one"
    assert "No hypothesis was admitted." in empty


def test_a_continuation_shows_earlier_checks_as_earlier_and_counts_nothing_twice():
    earlier_move = Transition(
        "bre:old",
        "hyp:norm",
        "NORMALIZATION_BASIS_ISSUE",
        "ACTIVE",
        "CONTRADICTED",
        "p@1",
        "dec:old",
        "ALLOW",
    )
    earlier = dataclasses.replace(_matched(transitions=(earlier_move,)), run_id="run:old")
    view = EpisodeView(
        executed=(ExecutedCheck("run:old", "cap:sp.extraction_consistency", "SUCCEEDED", T0),),
        results={"run:old": (earlier,)},
        predictions={"hyp:norm": (FALSIFIER,)},
    )
    report = _report(
        completed=(),
        continuation=ContinuationSection(
            2, "SUSPENDED", "reused", ("run 1",), ("cap executed in run 1",)
        ),
    )
    runs = [
        pages.RunRow(
            1,
            "rrn:1",
            "act:1",
            T0 - dt.timedelta(hours=1),
            T0,
            "SUSPENDED:PROVISIONAL",
            recorded=True,
        ),
        pages.RunRow(2, "rrn:2", "act:1", T0 + dt.timedelta(hours=1), None, None, recorded=True),
    ]
    l1 = _l1(_page(report, view, runs=runs, ordinal=2))
    assert "Run 2 continued this research from where it stopped; it did not start over." in l1
    assert "No check was executed in this run." in l1
    shown = l1[l1.index("Executed in earlier runs, not repeated") : l1.index("What was learned")]
    assert "extraction consistency" in shown and "observed normalization basis = AGREES" in shown
    assert "Nothing was tested in this run, so no belief could move." in l1
    assert "governed belief change(s) happened in this run" not in l1
    # Run 1, viewed itself, does not see itself as "earlier".
    first = _l1(_page(dataclasses.replace(report, continuation=None), view, runs=runs, ordinal=1))
    assert "Executed in earlier runs" not in first


def test_every_message_exists_in_both_locales_and_the_headings_follow_the_locale():
    for key in sorted(i18n.keys()):
        if key.startswith(("v.", "act.")) or key == "ep.waiting.debate":
            assert all(t.strip() for t in i18n.templates(key)), key
    zh = _l1(_page(_report(), _view(_result()), locale="zh-TW"))
    for heading in ("研究任務", "結果", "互相競爭的假說", "做了哪些檢查", "學到了什麼", "下一步"):
        assert heading in zh, heading
    assert "NORMALIZATION_BASIS_ISSUE" in zh and "AGREES" in zh, "stored values are not translated"


def test_nothing_a_model_a_report_or_a_record_supplies_becomes_markup():
    report = _report(
        goal=HOSTILE,
        hypotheses=tuple(
            dataclasses.replace(
                x, mechanism=HOSTILE, statement=HOSTILE, falsifier=HOSTILE, objections=(HOSTILE,)
            )
            for x in _report().hypotheses
        ),
    )
    hostile = dataclasses.replace(FALSIFIER, mechanism=HOSTILE, expected_outcome=HOSTILE)
    view = EpisodeView(
        executed=(ExecutedCheck("run:check", "cap:sp.extraction_consistency", "SUCCEEDED", T0),),
        results={
            "run:check": (_result(outcome=HOSTILE, observable=HOSTILE, unmatched=(hostile,)),)
        },
        predictions={"hyp:norm": (hostile,)},
    )
    markup = _page(report, view)
    assert "<script" not in markup and "<img" not in markup
    assert "&lt;script&gt;" in markup


def _reasoning(markup: str) -> str:
    return _text(
        markup[markup.index('<details id="v-reasoning"') : markup.index('<details id="v-audit"')]
    )


def test_l2_separates_observed_facts_interpretations_and_each_predictions_status():
    pending = dataclasses.replace(
        FALSIFIER,
        prediction_id="prd:norm.3",
        observable="sp.carrier_profile",
        outcome_space="os:sp.carrier_profile@1.0.0",
        expected_outcome="NOMINAL",
    )
    view = dataclasses.replace(
        _view(_result(unmatched=(FALSIFIER, SUPPORTING))),
        predictions={"hyp:norm": (FALSIFIER, SUPPORTING, pending)},
    )
    l2 = _reasoning(_page(_report(), view))
    assert "Observed facts extraction consistency: normalization basis = AGREES (OBSERVED)" in l2
    assert (
        "normalization basis = DISAGREES -> CONTRADICTS, its machine falsifier -- not what was"
        " observed: the check observed AGREES" in l2
    ), "observed, with another outcome: not pending"
    assert "normalization basis = SPLIT_DEPENDENT -> SUPPORTS -- not what was observed" in l2
    assert (
        "carrier profile = NOMINAL -> CONTRADICTS, its machine falsifier -- not observed yet" in l2
    )
    assert "Model interpretations" in l2
    assert "These are critique-stage judgments, not governed belief changes." in l2
    result = _matched()
    view = dataclasses.replace(_view(result), predictions={"hyp:norm": result.matched})
    matched = _reasoning(_page(_report(), view))
    assert (
        "normalization basis = AGREES -> CONTRADICTS, its machine falsifier -- observed" in matched
    )


def test_l3_shows_every_decision_on_a_relation_even_without_a_transition():
    """A relation the policy considered and did not move on is as auditable as one it moved on."""
    refused = Decision(
        "dec:review",
        "hyp:norm",
        "NEED_HUMAN_REVIEW",
        "policy:reject@1.0.0",
        "ACTIVE",
        "CONTRADICTED",
    )
    denied = Decision("dec:deny", "hyp:norm", "DENY", "policy:promote@1.0.0", "ACTIVE", "SUPPORTED")
    markup = _page(_report(), _view(_matched(refused, denied)))
    audit = _text(markup[markup.index('<details id="v-audit"') :])
    for line in (
        "decision dec:review NEED_HUMAN_REVIEW policy:reject@1.0.0 hyp:norm ACTIVE -> CONTRADICTED",
        "decision dec:deny DENY policy:promote@1.0.0 hyp:norm ACTIVE -> SUPPORTED",
    ):
        assert line in audit, line
    assert "dec:review" not in _l1(markup), "L1 names the decision, not its record"


def _typed(prediction: DeclaredPrediction) -> Prediction:
    space, _, version = prediction.outcome_space.rpartition("@")
    return Prediction(
        prediction_id=prediction.prediction_id,
        hypothesis_id=prediction.hypothesis_id,
        project_id="prj:lab",
        observable_ref=prediction.observable,
        outcome_space_id=space,
        outcome_space_version=version,
        expected_outcome=prediction.expected_outcome,
        relation_effect_if_observed=(
            RelationJudgmentTemplate(
                relation_type=RelationType.CONTRADICTS, to_entity_id=prediction.hypothesis_id
            ),
        ),
    )


def test_the_read_model_splits_by_comparable_including_outcome_space_identity():
    observed = ObservedOutcome(
        observable_ref="sp.normalization_basis",
        outcome_space_id="os:sp.normalization_basis",
        outcome_space_version="1.0.0",
        outcome="AGREES",
        epistemic_type=EpistemicType.OBSERVED,
        authority_class="DESIGN_INSPECTION",
        method_ref="sp.rule.normalization_basis@1.0.0",
    )
    # The latest blind episode's records: DISAGREES -> CONTRADICTS declared, AGREES observed, one
    # space -- a genuine other outcome.
    blind = FALSIFIER
    same = dataclasses.replace(FALSIFIER, prediction_id="prd:same", expected_outcome="AGREES")
    # The same outcome string in another version, or another space: not comparable at all.
    version = dataclasses.replace(
        same, prediction_id="prd:v2", outcome_space="os:sp.normalization_basis@2.0.0"
    )
    space = dataclasses.replace(same, prediction_id="prd:space", outcome_space="os:sp.other@1.0.0")
    over = (blind, same, version, space)
    typed = {p.prediction_id: _typed(p) for p in over}
    assert _split(over, typed, observed) == ((same,), (blind,), (version, space))
    assert _split(over, typed, None) == ((), (), over), "no recorded space: nothing comparable"


def test_a_prediction_in_another_outcome_space_is_not_comparable_on_the_page():
    v2 = dataclasses.replace(
        FALSIFIER, expected_outcome="AGREES", outcome_space="os:sp.normalization_basis@2.0.0"
    )
    view = dataclasses.replace(
        _view(_result(unmatched=(), incomparable=(v2,))), predictions={"hyp:norm": (v2,)}
    )
    markup = _page(_report(), view)
    l1, l2 = _l1(markup), _reasoning(markup)
    assert "normalization basis = AGREES matched no declared prediction" in l1
    assert (
        "NORMALIZATION_BASIS_ISSUE: AGREES -> CONTRADICTS, its machine falsifier -- declared in"
        " another outcome space or version, so not comparable" in l1
    )
    assert "No governed belief change happened in this run." in l1
    assert (
        "normalization basis = AGREES -> CONTRADICTS, its machine falsifier -- not comparable:"
        " declared in os:sp.normalization_basis@2.0.0, observed in"
        " os:sp.normalization_basis@1.0.0; nothing is inferred" in l2
    )
    assert "not what was observed" not in l2 and "not observed yet" not in l2
    unknown = dataclasses.replace(
        _view(_result(unmatched=(), incomparable=(v2,), outcome_space=None)),
        predictions={"hyp:norm": (v2,)},
    )
    markup = _page(_report(), unknown)
    assert "the observation does not record its outcome space, so not comparable" in _l1(markup)
    assert "observed in an outcome space the record does not name" in _reasoning(markup)
