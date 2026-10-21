"""The live failure, replayed through the web workspace: rivals that miss the cheapest check.

A real model proposed five well-formed rivals for a device whose cathode via never reached metal,
and none said anything about contact connectivity; the seconds-long inspection that settles it was
never planned. Here a stand-in model route gives the SAME shape -- five rivals, one per declared
observable except connectivity, in its own words -- on all three acceptance cases, and the
coverage review is answered as a model might: a new rival, in its own words, grounded on evidence.

    no leak         the review is shown the same unaddressed checks for every device: they follow
                    from the rivals and the capabilities, never from what the device holds
    cheapest check  the connectivity inspection is planned and runs; no simulation runs
    the gate holds  on the open-via device it observes DISCONTINUOUS, the outcome the new rival
                    declared in advance as SUPPORTS -- and because a model's own mechanism has no
                    domain warrant, a person must review it: the belief does not move, the
                    episode is not CONFIRMED, and the page says which of diagnosis, evidence,
                    authorization and belief change has happened
    refutation      on the sound device it observes CONTINUOUS, which the rival declared would
                    CONTRADICT it
    the record      the debate records the review, every reply attempt, and the provider's usage
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest

from lab_brain.cognition.roles import COVERAGE_REVIEW, HYPOTHESIS_ENGINE
from lab_brain.domains.silicon_photonics import vertical as sp
from lab_brain.research.report_store import SqlResearchReportStore
from tests.e2e.test_research_episode_postgres import PROJECT
from tests.e2e.test_web_debate_retry_postgres import _activated, _deployment
from tests.e2e.test_web_llm_credentials_postgres import KEY, _setup, _text
from tests.e2e.test_web_llm_runtime_postgres import _research, _token
from tests.fake_llm_provider import FakeProvider

pytestmark = pytest.mark.postgres

MARKER = "\n\nCONTEXT:\n"
#: The rival a model might add, in its own words -- not the catalog's mechanism name.
OPEN_VIA = "open cathode access via (model wording)"
CASES = ("contact-open-via", "probe-artifact")


def _context(prompt: str) -> dict[str, Any]:
    return dict(json.loads(prompt.split(MARKER, 1)[1]))


def _rivals_without_connectivity(ctx: dict[str, Any]) -> str:
    def prediction(key: str, b: dict[str, Any], outcome: str, effect: str) -> dict[str, str]:
        return {
            "key": key,
            "observable_ref": b["observable_ref"],
            "outcome_space_id": b["outcome_space_id"],
            "outcome_space_version": b["outcome_space_version"],
            "expected_outcome": outcome,
            "relation_effect": effect,
        }

    rivals = [
        {
            "key": f"h{n}",
            "statement": f"a model's mechanism read from {b['observable_ref']}",
            "mechanism": f"model mechanism {n} ({b['observable_ref']})",
            "assumptions": ["the splits differ only in process"],
            "falsifier": "its refuting outcome is observed",
            "falsifier_prediction_keys": ["f"],
            "confounders": ["probe contact"],
            "minimal_test_ref": b["observable_ref"],
            "predictions": [
                prediction("s", b, b["outcomes"][1], "SUPPORTS"),
                prediction("f", b, b["outcomes"][0], "CONTRADICTS"),
            ],
        }
        for n, b in enumerate(ctx["prediction_bindings"])
        if b["observable_ref"] != sp.OBS_CONNECTIVITY
    ]
    return json.dumps({"hypotheses": rivals, "position": {"mechanism_view": "contact resistance"}})


def _certify(ctx: dict[str, Any]) -> str:
    grounds = [e["attestation_id"] for e in ctx["evidence"] if "contact" in e["text"].lower()]
    b = next(c for c in ctx["unaddressed_checks"] if c["observable_ref"] == sp.OBS_CONNECTIVITY)

    def prediction(key: str, outcome: str, effect: str) -> dict[str, str]:
        return {
            "key": key,
            "observable_ref": b["observable_ref"],
            "outcome_space_id": b["outcome_space_id"],
            "outcome_space_version": b["outcome_space_version"],
            "expected_outcome": outcome,
            "relation_effect": effect,
        }

    return json.dumps(
        {
            "hypotheses": [
                {
                    "key": "via",
                    "statement": "A contact via is not tied to metal, so access current is cut.",
                    "mechanism": OPEN_VIA,
                    "assumptions": ["the extracted Rs includes the access path"],
                    "falsifier": "every contact is connected",
                    "falsifier_prediction_keys": ["f"],
                    "confounders": ["probe contact resistance"],
                    "minimal_test_ref": b["check"],
                    "predictions": [
                        prediction("s", "DISCONTINUOUS", "SUPPORTS"),
                        prediction("f", "CONTINUOUS", "CONTRADICTS"),
                    ],
                    "grounding_evidence_ids": grounds[:2],
                }
            ],
            "declined": [
                {"observable_ref": c["observable_ref"], "reason": "no evidence points there"}
                for c in ctx["unaddressed_checks"]
                if c["observable_ref"] != sp.OBS_CONNECTIVITY
            ],
        }
    )


@pytest.fixture
def fake() -> Iterator[FakeProvider]:
    reviews: list[dict[str, Any]] = []

    def rewrite(prompt: str, answer: str) -> str:
        if MARKER not in prompt or "PROBE:" in prompt:
            return answer
        if prompt.startswith(HYPOTHESIS_ENGINE.prompt.template) and not _context(prompt).get(
            "alternatives_to_certify"
        ):
            return _rivals_without_connectivity(_context(prompt))
        if prompt.startswith(COVERAGE_REVIEW.prompt.template):
            reviews.append(_context(prompt))
            return _certify(_context(prompt))
        return answer

    provider = FakeProvider(api_key=KEY, rewrite=rewrite).start()
    provider.reviews = reviews  # type: ignore[attr-defined]
    yield provider
    provider.stop()


def _all(db, sql: str, *args: object) -> list[tuple]:  # type: ignore[no-untyped-def]
    return list(db.execute(sql, args).fetchall())


def test_the_review_finds_the_cheap_check_and_the_warrant_gate_still_decides(db, tmp_path, fake):
    _setup(db)
    browser = _deployment(tmp_path, inference_deadline=60)
    _activated(db, browser, fake)
    episodes: dict[str, str] = {}
    for case in CASES:
        before = {r[0] for r in _all(db, "SELECT episode_id FROM research_episodes")}
        sent = _research(browser, tmp_path, case=case)
        assert sent.status == 303, _text(sent)[:500]
        (episodes[case],) = {
            r[0] for r in _all(db, "SELECT episode_id FROM research_episodes")
        } - before

    # No leak: every device's review was shown the same checks, named by cost and coverage.
    reviews = fake.reviews  # type: ignore[attr-defined]
    assert len(reviews) == len(CASES)
    assert all(r["unaddressed_checks"] == reviews[0]["unaddressed_checks"] for r in reviews)
    assert [c["observable_ref"] for c in reviews[0]["unaddressed_checks"]] == [sp.OBS_CONNECTIVITY]
    assert "PS-50" not in json.dumps(reviews), "no device content reaches the review"

    # No simulation ran or was emulated, in any case.
    assert not _all(
        db,
        "SELECT 1 FROM jobs WHERE project_id = %s AND capability_id = ANY(%s)",
        PROJECT,
        [sp.CAP_MESH_SENSITIVITY, sp.CAP_CHARGE_DC, "cap:sp.charge_ac_sweep"],
    )

    def observed(episode: str) -> list[str]:
        return [
            r[0]
            for r in _all(
                db,
                "SELECT o.value_text FROM observations o JOIN runs u ON u.run_id = o.run_id"
                " JOIN jobs j ON j.job_id = u.job_id"
                " WHERE j.episode_id = %s AND o.metric_or_event = %s",
                episode,
                sp.OBS_CONNECTIVITY,
            )
        ]

    def via(episode: str) -> str:
        ((hid,),) = _all(
            db,
            "SELECT h.hypothesis_id FROM hypotheses h WHERE h.created_in_episode = %s"
            " AND h.mechanism = %s",
            episode,
            OPEN_VIA,
        )
        return str(hid)

    # The open via: the cheap check ran, and observed what the new rival declared as support.
    open_via = episodes["contact-open-via"]
    assert observed(open_via) == ["DISCONTINUOUS"]
    rival = via(open_via)
    relations = _all(
        db,
        "SELECT relation_type FROM relation_judgments WHERE to_entity_id = %s",
        rival,
    )
    assert ("SUPPORTS",) in relations
    decisions = {
        r[0]
        for r in _all(
            db,
            "SELECT result FROM belief_transition_decisions WHERE subject_id = %s"
            " AND to_state = 'SUPPORTED'",
            rival,
        )
    }
    assert decisions == {"NEED_HUMAN_REVIEW"}, decisions
    assert not _all(
        db,
        "SELECT 1 FROM belief_revision_events WHERE target_id = %s AND to_state = 'SUPPORTED'",
        rival,
    ), "no belief moved on a model's mechanism without a warrant"
    ((state, outcome),) = _all(
        db,
        "SELECT state, coalesce(outcome_status, '') FROM research_episodes WHERE episode_id = %s",
        open_via,
    )
    assert "CONFIRMED" not in outcome and state == "SUSPENDED", (state, outcome)

    # The sound device: the same check observed the outcome the rival said would refute it.
    sound = episodes["probe-artifact"]
    assert observed(sound) == ["CONTINUOUS"]
    assert ("CONTRADICTS",) in _all(
        db, "SELECT relation_type FROM relation_judgments WHERE to_entity_id = %s", via(sound)
    )

    # The record: the review, each reply attempt, and what the provider metered.
    (recorded,) = SqlResearchReportStore(db).for_episode(project_id=PROJECT, episode_id=open_via)
    report = recorded.report
    assert report.debate is not None and report.debate.reliability is not None
    reliability = report.debate.reliability
    assert reliability.policy == "debate:research-run@1.1.0"
    assert reliability.coverage_status == "DONE" and reliability.refused == 0
    assert [(c.observable, c.disposition) for c in reliability.coverage] == [
        (sp.OBS_CONNECTIVITY, "CERTIFIED")
    ]
    assert report.usage and all(u.metered_calls == u.calls for u in report.usage)
    assert sum(u.total_tokens for u in report.usage) > 0

    # The page keeps diagnosis, evidence, authorization and belief apart -- in zh-TW.
    browser.post("/locale", {"csrf": _token(browser.get("/")), "locale": "zh-TW", "next": "/"})
    page = _text(browser.get(f"/episodes/{open_via}").text)
    for said in (
        "診斷：檢查觀察到的結果，正是這個假說事先宣告為支持的結果。",
        "證據：已記錄，可追溯到該檢查的執行紀錄。",
        "授權：尚待決定",
        "信念：沒有改變。",
        "最初的假說沒有涵蓋的低成本檢查",
        "新增了一個對立假說",
    ):
        assert said in page, said
    assert report.conclusion.status != "CONFIRMED", report.conclusion
