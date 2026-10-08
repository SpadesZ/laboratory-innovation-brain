"""The episode page over real stored records: research run through the web workspace, read back.

A model route is applied (the stand-in, whose research answers come from the pack's catalog through
the real role contracts and parsers) and every assertion about the page is checked against the rows
the run wrote -- runs, observations, declared predictions, RelationJudgments, governed
BeliefRevisionEvents -- never against a fixture:

    explained      each executed check shows its observed outcome, and each governed move the
                   stored relations authorised is said with its decision; the count is exactly the
                   events this run's checks caused
    no match       with the deployed local model's certificate shape (only designated falsifiers,
                   each on another outcome than the catalog's), the normalization check's AGREES
                   matches no declared prediction: no relation and no move comes from it, and the
                   page says exactly that, naming what was declared -- while a check whose outcome
                   a falsifier did declare is shown with the move it governed
    not reached    a run without verification input says where it stopped, and that nothing moved
    continuation   run 2 shows run 1's checks as earlier ones -- not executed again -- and counts
                   none of run 1's belief changes as its own
    disclosure     L1 shows no identifier; the audit layer holds every record behind each check

A "check" here is any Run of the episode but its document ingestion -- chosen independently of the
read model's own rule, so the two are compared rather than copied.
"""

from __future__ import annotations

import datetime as dt
import html
import re
from collections.abc import Iterator

import pytest

from lab_brain.composition import INGEST_CAPABILITY
from lab_brain.core.episode import BeliefEpisode
from lab_brain.core.models import BeliefState
from lab_brain.core.repositories import (
    SqlAttestationStore,
    SqlBeliefEventStore,
    SqlRelationStore,
    SqlTransitionPolicyStore,
)
from lab_brain.core.repositories.belief_events import SqlBeliefTransitionDecisionStore
from lab_brain.core.repositories.conflicts import SqlConflictStore
from lab_brain.core.repositories.reviews import SqlReviewItemStore
from lab_brain.domains.silicon_photonics.product import product_vertical
from lab_brain.interfaces.web.pages import label
from lab_brain.research.episode_view import load_episode_view
from lab_brain.research.report_store import SqlResearchReportStore
from tests.debate_fixtures import CountingIds
from tests.e2e.test_research_episode_postgres import PROJECT
from tests.e2e.test_web_debate_retry_postgres import _activated, _deployment
from tests.e2e.test_web_llm_credentials_postgres import KEY, _post, _setup, _text
from tests.e2e.test_web_llm_runtime_postgres import _research
from tests.fake_llm_provider import FakeProvider
from tests.wsgi_client import Browser

pytestmark = pytest.mark.postgres

CHECK = "cap:sp.extraction_consistency"
OBSERVABLE = "sp.normalization_basis"
IDENTIFIER = re.compile(
    r"\b(?:epi|hyp|prd|run|job|obs|att|rel|bre|dec|art|lrt|inf|rrn|vpl|bdl|hst):[0-9a-zA-Z]"
)


@pytest.fixture
def fake() -> Iterator[FakeProvider]:
    provider = FakeProvider(api_key=KEY).start()
    yield provider
    provider.stop()


def _all(db, sql: str, *args: object) -> list[tuple]:  # type: ignore[no-untyped-def]
    return list(db.execute(sql, args).fetchall())


def _l1(markup: str) -> str:
    """The page as a reader sees it before opening anything."""
    main = re.search(r"<main.*?</main>", markup, flags=re.S)
    assert main is not None
    return _text(
        re.sub(r'<details id="v-[a-z]+" class="layer">.*?</details>', "", main.group(0), flags=re.S)
    )


def _audit(markup: str) -> str:
    return markup[markup.index('<details id="v-audit"') :]


def _section(l1: str, start: str, end: str) -> str:
    return l1[l1.index(start) : l1.index(end)]


def _episode(db, browser: Browser, tmp_path, case: str | None) -> str:  # type: ignore[no-untyped-def]
    sent = _research(browser, tmp_path, case=case)
    assert sent.status == 303, _text(sent)[:500]
    ((episode,),) = _all(
        db, "SELECT episode_id FROM research_episodes WHERE project_id = %s", PROJECT
    )
    return str(episode)


def _checks(db, episode: str, after: object = None) -> list[tuple]:  # type: ignore[no-untyped-def]
    """(run, capability, observable, value, observation) for each check the episode executed."""
    return _all(
        db,
        "SELECT r.run_id, r.capability_id, o.metric_or_event,"
        " coalesce(o.value_text, o.value_numeric::text), o.observation_id"
        " FROM runs r JOIN jobs j ON j.job_id = r.job_id"
        " LEFT JOIN observations o ON o.run_id = r.run_id"
        " WHERE j.episode_id = %s AND r.capability_id <> %s"
        " AND (%s::timestamptz IS NULL OR r.start_time >= %s::timestamptz) ORDER BY r.start_time",
        episode,
        INGEST_CAPABILITY,
        after,
        after,
    )


def _states(db, episode: str) -> dict[str, int]:  # type: ignore[no-untyped-def]
    """How many of the episode's hypotheses are in each state, by their latest belief event."""
    counts: dict[str, int] = {}
    for (state,) in _all(
        db,
        "SELECT DISTINCT ON (e.target_id) e.to_state FROM belief_revision_events e"
        " JOIN hypotheses h ON h.hypothesis_id = e.target_id WHERE h.created_in_episode = %s"
        " ORDER BY e.target_id, e.occurred_at DESC",
        episode,
    ):
        counts[state] = counts.get(state, 0) + 1
    return counts


def _moves(db, observations: list[str]) -> list[tuple]:  # type: ignore[no-untyped-def]
    """(mechanism, from, to, decision, event, relation) for every governed move those observations
    caused -- through the relation each one is judged by. Genesis is not a move."""
    return _all(
        db,
        "SELECT h.mechanism, e.from_state, e.to_state, d.result, e.event_id, r.relation_id"
        " FROM relation_judgments r"
        " JOIN belief_revision_event_relations l ON l.relation_id = r.relation_id"
        " JOIN belief_revision_events e ON e.event_id = l.event_id"
        " JOIN hypotheses h ON h.hypothesis_id = e.target_id"
        " LEFT JOIN belief_transition_decisions d"
        " ON d.decision_id = e.authorization_decision_id"
        " WHERE r.from_entity_id = ANY (%s) AND e.from_state IS NOT NULL",
        observations,
    )


def test_each_executed_check_and_each_governed_move_is_explained_from_the_stored_records(
    db, tmp_path, fake
):
    _setup(db)
    browser = _deployment(tmp_path, inference_deadline=60)
    _activated(db, browser, fake)
    episode = _episode(db, browser, tmp_path, "contact-open-via")
    page = browser.get(f"/episodes/{episode}")
    assert page.status == 200
    l1 = _l1(page.text)

    checks = _checks(db, episode)
    assert any(c[1] == CHECK for c in checks), checks
    tested = _section(l1, "Executed in this run", "What was learned")
    for _, capability, observable, value, _ in checks:
        assert label(capability) in tested, capability
        assert f"observed {label(observable)} = {value}" in tested, (observable, value)
    moves = _moves(db, [c[4] for c in checks])
    assert moves, "the contact-open case moves belief through the stored relations"
    learned = _section(l1, "What was learned", "Next action")
    for mechanism, from_state, to_state, decision, _, _ in moves:
        assert (
            f"{mechanism}: {from_state} -> {to_state}, a governed transition"
            f" (decision: {decision})." in learned
        )
    assert f"{len(moves)} governed belief change(s) happened in this run." in learned
    assert "A person can act now" in l1 or "Best next check" in l1 or "No further check" in l1

    # Each card names as machine falsifiers exactly the predictions its certificate designates.
    cards = {
        html.unescape(mechanism).strip(): _text(card)
        for mechanism, card in re.findall(
            r'<div class="card hypothesis"><h3>([^<]*)(.*?)</div>', page.text, flags=re.S
        )
    }
    declared = _all(
        db,
        "SELECT h.mechanism, p.observable_ref, p.expected_outcome,"
        " p.prediction_id = ANY (h.falsifier_prediction_ids)"
        " FROM hypotheses h JOIN predictions p ON p.hypothesis_id = h.hypothesis_id"
        " WHERE h.created_in_episode = %s",
        episode,
    )
    assert any(d[3] for d in declared) and not all(d[3] for d in declared), declared
    for mechanism, observable, expected, designated in declared:
        shown = f"Would be refuted if {label(observable)} = {expected}" in cards[mechanism]
        assert shown == designated, (mechanism, observable, expected, designated)

    # Disclosure: no identifier in L1; the audit layer holds every record behind every check.
    assert not IDENTIFIER.findall(l1), IDENTIFIER.findall(l1)
    assert not re.search(r'<details id="v-(?:reasoning|audit)"[^>]*\bopen\b', page.text)
    audit = _audit(page.text)
    for run_id, _, _, _, observation in checks:
        assert run_id in audit and observation in audit
    for *_, event, relation in moves:
        assert event in audit and relation in audit

    # The read model agrees with the rows, record for record.
    view = load_episode_view(db, project_id=PROJECT, episode_id=episode)
    assert {(x.run_id, x.capability_id) for x in view.executed} == {(c[0], c[1]) for c in checks}
    read = {
        (t.event_id, rel.relation_id)
        for results in view.results.values()
        for r in results
        for rel in r.relations
        for t in rel.transitions
    }
    assert read == {(m[4], m[5]) for m in moves}

    # A recorded decision with no event: the registered rejection policy is asked, through the
    # real governed path, about the hypothesis this run SUPPORTED -- a transition it does not
    # govern -- and records its refusal over the run's relation; nothing moves. The audit layer
    # shows the decision in full; L1's count of belief changes is unchanged.
    ((hypothesis,),) = _all(
        db,
        "SELECT target_id FROM belief_revision_events WHERE event_id = %s",
        next(m[4] for m in moves if m[2] == "SUPPORTED"),
    )
    # The pack's authority comparators, as the research service and its loop supply them.
    vertical = product_vertical(
        outputs=None, jobs=None, broker=None, now=lambda: dt.datetime.now(dt.UTC)
    )
    refused = BeliefEpisode(
        policies=SqlTransitionPolicyStore(db),
        decisions=SqlBeliefTransitionDecisionStore(db),
        events=SqlBeliefEventStore(db),
        relations=SqlRelationStore(db),
        authority_classes=SqlAttestationStore(db),
        conflicts=SqlConflictStore(db),
        reviews=SqlReviewItemStore(db),
        ids=CountingIds(),
        authority_policies=vertical.authority_policies,
    ).attempt_transition(
        project_id=PROJECT,
        hypothesis_id=hypothesis,
        policy_id="policy:sp-fidelity-reject",
        policy_version="1.0.0",
        candidate_to_state=BeliefState.CONTRADICTED,
        stakes="HIGH",
        occurred_at=dt.datetime.now(dt.UTC),
        trace_id="trc:episode-view-refusal",
        episode_id=episode,
        authority_policy_ref=(
            vertical.authority_policy.policy_id,
            vertical.authority_policy.policy_version,
        ),
    )
    assert not refused.transitioned
    ((decision, result, policy, subject, from_state, to_state),) = _all(
        db,
        "SELECT decision_id, result, policy_id || '@' || policy_version, subject_id, from_state,"
        " to_state FROM belief_transition_decisions WHERE decision_id = %s",
        refused.authorization.decision_id,
    )
    assert result != "ALLOW" and not _all(
        db, "SELECT 1 FROM belief_revision_events WHERE authorization_decision_id = %s", decision
    )
    again = browser.get(f"/episodes/{episode}").text
    assert f"decision {decision} {result} {policy} {subject} {from_state} -> {to_state}" in _text(
        _audit(again)
    )
    assert decision not in _l1(again)
    assert f"{len(moves)} governed belief change(s) happened in this run." in _l1(again)


def test_an_outcome_no_hypothesis_declared_moves_nothing_and_the_page_says_so(db, tmp_path, fake):
    fake.inverted_falsifier = True
    _setup(db)
    browser = _deployment(tmp_path, inference_deadline=60)
    _activated(db, browser, fake)
    episode = _episode(db, browser, tmp_path, "contact-open-via")

    # The rows: the normalization check ran and observed AGREES; every hypothesis declared about
    # that observable only a falsifier on another outcome; so no relation and no move exists.
    checks = [c for c in _checks(db, episode) if c[1] == CHECK]
    assert len(checks) == 1, _checks(db, episode)
    _, _, observable, value, observation = checks[0]
    assert (observable, value) == (OBSERVABLE, "AGREES")
    declared = _all(
        db,
        "SELECT h.mechanism, p.expected_outcome, e ->> 'relation_type',"
        " p.prediction_id = ANY (h.falsifier_prediction_ids)"
        " FROM hypotheses h JOIN predictions p ON p.hypothesis_id = h.hypothesis_id,"
        " jsonb_array_elements(p.relation_effect_if_observed) e"
        " WHERE h.created_in_episode = %s AND p.observable_ref = %s ORDER BY h.mechanism",
        episode,
        OBSERVABLE,
    )
    assert declared and all(d[1] != "AGREES" and d[3] for d in declared), declared
    assert not _all(db, "SELECT 1 FROM relation_judgments WHERE from_entity_id = %s", observation)
    assert not _moves(db, [observation])
    moves = _moves(db, [c[4] for c in _checks(db, episode) if c[4]])

    # The page says what the rows say.
    page = browser.get(f"/episodes/{episode}").text
    l1 = _l1(page)
    learned = _section(l1, "What was learned", "Next action")
    assert (
        "normalization basis = AGREES matched no declared prediction, so it neither supports nor"
        " contradicts any hypothesis, and no belief could move." in learned
    )
    assert "Declared about normalization basis:" in learned
    for mechanism, expected, effect, _ in declared:
        assert f"{mechanism}: {expected} -> {effect}, its machine falsifier" in learned
    for mechanism, from_state, to_state, decision, _, _ in moves:
        assert (
            f"{mechanism}: {from_state} -> {to_state}, a governed transition"
            f" (decision: {decision})." in learned
        )
    assert (
        f"{len(moves)} governed belief change(s) happened in this run." in learned
        if moves
        else "No governed belief change happened in this run." in learned
    )
    mechanisms = [
        r[0]
        for r in _all(db, "SELECT mechanism FROM hypotheses WHERE created_in_episode = %s", episode)
    ]
    hypotheses = _section(l1, "Competing hypotheses", "What was tested")
    result = _section(l1, "Result", "Competing hypotheses")
    for state, n in _states(db, episode).items():
        assert f"{state} {n}" in result, (state, n, result)
    for mechanism in mechanisms:
        assert mechanism in hypotheses
    assert "Would be refuted if normalization basis = DISAGREES" in hypotheses
    assert "No root cause has been confirmed." in l1
    assert not IDENTIFIER.findall(l1), IDENTIFIER.findall(l1)
    assert observation in _audit(page)

    # The blind episode's genuine mismatch: one OutcomeSpace, another outcome -- not a space
    # mismatch, and not pending. The read model and the reasoning layer both say so.
    view = load_episode_view(db, project_id=PROJECT, episode_id=episode)
    (result,) = [r for rs in view.results.values() for r in rs if r.observation_id == observation]
    assert not result.matched and not result.incomparable and result.unmatched
    assert {p.outcome_space for p in result.unmatched} == {result.outcome_space}
    reasoning = _text(
        page[page.index('<details id="v-reasoning"') : page.index('<details id="v-audit"')]
    )
    for mechanism, expected, effect, _ in declared:
        assert (
            f"normalization basis = {expected} -> {effect}, its machine falsifier -- not what was"
            " observed: the check observed AGREES" in reasoning
        ), mechanism
    assert "not comparable" not in reasoning


def test_a_run_that_was_not_reached_says_where_it_stopped_and_that_nothing_moved(
    db, tmp_path, fake
):
    _setup(db)
    browser = _deployment(tmp_path, inference_deadline=60)
    _activated(db, browser, fake)
    episode = _episode(db, browser, tmp_path, None)
    (recorded,) = SqlResearchReportStore(db).for_episode(project_id=PROJECT, episode_id=episode)
    report = recorded.report
    assert report.conclusion.status == "NOT_REACHED" and not report.completed
    stopped = next(
        (s for s in report.stages if s.status in ("FAILED", "REFUSED")),
        next(s for s in report.stages if s.status == "SKIPPED"),
    )
    l1 = _l1(browser.get(f"/episodes/{episode}").text)
    assert "Not reached -- the research stopped before verification." in l1
    assert f"It stopped at the {stopped.stage} step ({stopped.status})." in l1
    assert "No check was executed in this run." in l1
    assert "Nothing was tested in this run, so no belief could move." in l1
    assert not _checks(db, episode)
    assert not IDENTIFIER.findall(l1), IDENTIFIER.findall(l1)


def test_a_continuation_shows_earlier_checks_as_earlier_and_counts_none_of_their_moves(
    db, tmp_path, fake
):
    _setup(db)
    browser = _deployment(tmp_path, inference_deadline=60)
    _activated(db, browser, fake)
    episode = _episode(db, browser, tmp_path, "mesh-coarse-access")
    ((state,),) = _all(db, "SELECT state FROM research_episodes WHERE episode_id = %s", episode)
    assert state == "SUSPENDED", "parked on the simulator this deployment does not have"
    checks = _checks(db, episode)
    assert checks, "run 1 executed what it could"
    moves = _moves(db, [c[4] for c in checks if c[4]])

    continued = _post(browser, f"/episodes/{episode}/continue", {})
    assert continued.status == 303, _text(continued)[:500]
    ((began,),) = _all(
        db,
        "SELECT started_at FROM research_runs WHERE episode_id = %s AND ordinal = 2",
        episode,
    )
    assert not _checks(db, episode, began), "nothing new could run: the simulator is still absent"
    second = _l1(browser.get(f"/episodes/{episode}?run=2").text)
    assert "Run 2 continued this research from where it stopped; it did not start over." in second
    assert "Showing run 2 of 2." in second
    assert "No check was executed in this run." in second
    earlier = _section(second, "Executed in earlier runs, not repeated", "What was learned")
    assert label(INGEST_CAPABILITY) not in earlier, "document ingestion is not a check"
    for _, capability, observable, value, _ in checks:
        assert label(capability) in earlier, capability
        if observable is not None:
            assert f"observed {label(observable)} = {value}" in earlier
    assert "Nothing was tested in this run, so no belief could move." in second
    assert "governed belief change(s) happened in this run" not in second
    assert "Best next check:" in second and "It cannot run here:" in second
    assert not IDENTIFIER.findall(second), IDENTIFIER.findall(second)

    first = _l1(browser.get(f"/episodes/{episode}?run=1").text)
    assert "Executed in earlier runs" not in first, "run 1 has no earlier run"
    assert (
        f"{len(moves)} governed belief change(s) happened in this run." in first
        if moves
        else "No governed belief change happened in this run." in first
    )
