"""The research question's classification, recorded with every research run (`012q`).

Data-organization audit 2026-10-15, F-01. The question's sensitivity label lived only in the
request that opened an episode; a continuation rebuilt its request under the default INTERNAL, so
a re-debate could reason over -- and, with an external route, send -- a question below its own
classification. Now:

    declared       an episode opens only under a classification its opener declares, on every
                   path (service, CLI); nothing is written otherwise
    carried        a continuation reasons under the episode's recorded classification, and a
                   different one -- lower or higher -- is refused before anything is written
    history        an episode opened before `012q` records none; it continues only under one its
                   next run declares, and every run after that carries it
    every writer   the database refuses a run without a classification, a continuation under
                   another one, and any edit of a recorded one

The end-to-end consequence for egress is
`test_web_debate_retry_postgres.test_a_continued_debate_reasons_under_the_questions_own_classification`.
"""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from lab_brain.core.models.enums import SensitivityLabel, TrustClass
from lab_brain.core.repositories.episodes import SqlEpisodeStore
from lab_brain.research.continuation import (
    ContinuationRefused,
    ResearchRunRecord,
    SqlResearchRunStore,
)
from lab_brain.research.run_provenance import RunProvenance
from lab_brain.research.service import InputDocument, QuestionNotCleared, ResearchRequest
from tests.e2e.test_research_continuation_postgres import _census, _cli, _service
from tests.e2e.test_research_episode_postgres import ACTOR, GOAL, PROJECT, REPORT, _device, _member

pytestmark = pytest.mark.postgres


def _document() -> InputDocument:
    return InputDocument(
        name=REPORT.name,
        data=REPORT.read_bytes(),
        media_type="text/markdown",
        uri=REPORT.resolve().as_uri(),
        trust_class=TrustClass.INTERNAL_MEASUREMENT,
    )


def _clear(db, *labels: str) -> None:  # type: ignore[no-untyped-def]
    db.execute(
        "UPDATE project_memberships SET sensitivity_clearance = %s WHERE actor_id = %s"
        " AND project_id = %s",
        (list(labels), ACTOR, PROJECT),
    )


def _open(tmp_path: Path, label: SensitivityLabel) -> str:
    """An episode that waits for a simulator (so it can be continued), opened under `label`."""
    device = _device(tmp_path, "mesh-coarse-access")
    report = _service(tmp_path).run(
        ResearchRequest(
            project_id=PROJECT,
            actor_id=ACTOR,
            goal=GOAL,
            documents=(_document(),),
            verification_input=(device.name, device.read_bytes()),
            sensitivity=label,
            provenance=RunProvenance.operator_cli(),
        )
    )
    assert report.episode_state == "SUSPENDED", report.episode_state
    return report.episode_id


def _continue(tmp_path: Path, episode_id: str, label: SensitivityLabel | None = None) -> object:
    return _service(tmp_path).run(
        ResearchRequest(
            project_id=PROJECT,
            actor_id=ACTOR,
            goal="",
            documents=(),
            episode_id=episode_id,
            sensitivity=label,
            provenance=RunProvenance.operator_cli(),
        )
    )


def _labels(db, episode_id: str) -> list[tuple[int, str | None]]:  # type: ignore[no-untyped-def]
    return [
        (int(r[0]), r[1])
        for r in db.execute(
            "SELECT ordinal, question_label FROM research_runs WHERE episode_id = %s"
            " ORDER BY ordinal",
            (episode_id,),
        ).fetchall()
    ]


def test_an_episode_opens_only_under_a_declared_classification(db, tmp_path):
    _member(db)
    before = _census(db)
    with pytest.raises(ValueError, match="declares its question's classification"):
        _service(tmp_path).run(
            ResearchRequest(
                project_id=PROJECT,
                actor_id=ACTOR,
                goal=GOAL,
                documents=(_document(),),
                provenance=RunProvenance.operator_cli(),
            )
        )
    code, printed = _cli(tmp_path, "--goal", GOAL, "--measurement", str(REPORT))
    assert code == 2 and "--sensitivity is required to open an episode" in printed, printed
    assert _census(db) == before, "nothing is written for an undeclared question"
    # Declared above what the asker may read (PUBLIC and INTERNAL here): refused on every path.
    with pytest.raises(QuestionNotCleared, match="does not include CONFIDENTIAL_LAB"):
        _service(tmp_path).run(
            ResearchRequest(
                project_id=PROJECT,
                actor_id=ACTOR,
                goal=GOAL,
                documents=(_document(),),
                sensitivity=SensitivityLabel.CONFIDENTIAL_LAB,
                provenance=RunProvenance.operator_cli(),
            )
        )
    code, printed = _cli(
        tmp_path, "--goal", GOAL, "--sensitivity", "RESTRICTED_NDA", "--measurement", str(REPORT)
    )
    assert code == 1 and "does not include RESTRICTED_NDA" in printed, printed
    assert _census(db) == before, "nor for one its asker could not read back"


def test_a_continuation_carries_the_recorded_classification_and_cannot_change_it(db, tmp_path):
    _member(db)
    _clear(db, "PUBLIC", "INTERNAL", "CONFIDENTIAL_LAB")
    episode_id = _open(tmp_path, SensitivityLabel.CONFIDENTIAL_LAB)
    _continue(tmp_path, episode_id)
    assert _labels(db, episode_id) == [(1, "CONFIDENTIAL_LAB"), (2, "CONFIDENTIAL_LAB")]
    before = _census(db)
    for other in (SensitivityLabel.INTERNAL, SensitivityLabel.RESTRICTED_NDA):
        with pytest.raises(ContinuationRefused, match="keeps that classification"):
            _continue(tmp_path, episode_id, other)
    code, printed = _cli(tmp_path, "--episode", episode_id, "--sensitivity", "PUBLIC")
    assert code == 1 and "keeps that classification and cannot carry PUBLIC" in printed, printed
    assert _census(db) == before, "a refused continuation writes nothing"
    # Declaring the recorded classification is not a change.
    _continue(tmp_path, episode_id, SensitivityLabel.CONFIDENTIAL_LAB)
    assert [label for _, label in _labels(db, episode_id)] == ["CONFIDENTIAL_LAB"] * 3


def test_a_question_is_continued_only_by_someone_still_cleared_for_it(db, tmp_path):
    """The opener's clearance is read again at each continuation: lowered since the episode
    opened, the question is not asked again -- on any path -- and nothing is written."""
    _member(db)
    _clear(db, "PUBLIC", "INTERNAL", "CONFIDENTIAL_LAB")
    episode_id = _open(tmp_path, SensitivityLabel.CONFIDENTIAL_LAB)
    _clear(db, "PUBLIC", "INTERNAL")
    before = _census(db)
    with pytest.raises(ContinuationRefused, match="does not include it; it is not continued"):
        _continue(tmp_path, episode_id)
    code, printed = _cli(tmp_path, "--episode", episode_id)
    assert code == 1 and "does not include it" in printed, printed
    assert _census(db) == before, "a question its asker can no longer read is not asked again"
    assert _labels(db, episode_id) == [(1, "CONFIDENTIAL_LAB")]


def test_an_episode_opened_before_012q_continues_only_under_a_declared_classification(db, tmp_path):
    _member(db)
    _clear(db, "PUBLIC", "INTERNAL", "CONFIDENTIAL_LAB")
    episode_id = _open(tmp_path, SensitivityLabel.INTERNAL)
    # History: the opening run recorded before `012q`, written as such past the triggers.
    db.execute("SET session_replication_role = replica")
    try:
        db.execute(
            "UPDATE research_runs SET question_label = NULL WHERE episode_id = %s", (episode_id,)
        )
    finally:
        db.execute("SET session_replication_role = origin")
    before = _census(db)
    with pytest.raises(ContinuationRefused, match="opened before its question's classification"):
        _continue(tmp_path, episode_id)
    code, printed = _cli(tmp_path, "--episode", episode_id)
    assert code == 1 and "Declare it to continue" in printed, printed
    assert _census(db) == before
    _continue(tmp_path, episode_id, SensitivityLabel.CONFIDENTIAL_LAB)
    _continue(tmp_path, episode_id)
    assert _labels(db, episode_id) == [
        (1, None),
        (2, "CONFIDENTIAL_LAB"),
        (3, "CONFIDENTIAL_LAB"),
    ], "declared once, carried from then on; the history row is left as it was"


def test_the_database_holds_the_classification_rule_for_every_writer(db, tmp_path):
    _member(db)
    _clear(db, "PUBLIC", "INTERNAL", "CONFIDENTIAL_LAB")
    episode_id = _open(tmp_path, SensitivityLabel.CONFIDENTIAL_LAB)
    ledger = SqlResearchRunStore(db)
    opening = ledger.opener(project_id=PROJECT, episode_id=episode_id)
    assert opening is not None and opening.question_label == "CONFIDENTIAL_LAB"
    SqlEpisodeStore(db).resume(episode_id)

    def run(label: str | None) -> ResearchRunRecord:
        return ResearchRunRecord(
            research_run_id=f"rrn:direct-{label}",
            episode_id=episode_id,
            project_id=PROJECT,
            actor_id=ACTOR,
            ordinal=2,
            hypothesis_set_id=opening.hypothesis_set_id,
            verification_artifact_id=opening.verification_artifact_id,
            symptom=opening.symptom,
            expected_behavior=opening.expected_behavior,
            observed_behavior=opening.observed_behavior,
            started_at=opening.started_at,
            question_label=label,
            provenance=RunProvenance.operator_cli(),
        )

    for label, refusal in (
        (None, "declares no classification for its question"),
        ("INTERNAL", "is classified CONFIDENTIAL_LAB; research run rrn:direct-INTERNAL carries"),
        ("PUBLIC", "a continuation keeps the question's classification"),
    ):
        with pytest.raises(psycopg.errors.RaiseException, match=refusal):
            ledger.start(run(label))
    for value in ("INTERNAL", None):
        with pytest.raises(psycopg.errors.RaiseException, match="is recorded once"):
            db.execute(
                "UPDATE research_runs SET question_label = %s WHERE episode_id = %s",
                (value, episode_id),
            )
    # Past every trigger, the column still holds only a classification.
    db.execute("SET session_replication_role = replica")
    try:
        with pytest.raises(psycopg.errors.CheckViolation):
            db.execute(
                "UPDATE research_runs SET question_label = 'SECRET' WHERE episode_id = %s",
                (episode_id,),
            )
    finally:
        db.execute("SET session_replication_role = origin")
    assert _labels(db, episode_id) == [(1, "CONFIDENTIAL_LAB")]


def test_the_web_asks_an_older_episode_for_its_classification_before_continuing(db, tmp_path):
    """The research page of an episode opened before `012q` asks for the question's
    classification in its continue form, at levels the researcher holds; continuing without one,
    or with one above their access, is refused and writes nothing."""
    from tests.e2e.test_web_workspace_postgres import _text, _token, _workspace

    _member(db)  # PUBLIC and INTERNAL
    episode_id = _open(tmp_path, SensitivityLabel.INTERNAL)
    db.execute("SET session_replication_role = replica")
    try:
        db.execute(
            "UPDATE research_runs SET question_label = NULL WHERE episode_id = %s", (episode_id,)
        )
    finally:
        db.execute("SET session_replication_role = origin")
    browser = _workspace(tmp_path)
    page = browser.get(f"/episodes/{episode_id}")
    form = page.text[page.text.index(f'action="/episodes/{episode_id}/continue"') :]
    form = form[: form.index("</form>")]
    assert 'name="sensitivity" value="INTERNAL" required>' in form
    assert 'name="sensitivity" value="CONFIDENTIAL_LAB" required disabled>' in form
    before = _census(db)
    token = _token(page)
    bare = browser.post(f"/episodes/{episode_id}/continue", {"csrf": token})
    assert bare.status == 409 and "Declare it to continue" in _text(bare), _text(bare)[:600]
    above = browser.post(
        f"/episodes/{episode_id}/continue", {"csrf": token, "sensitivity": "CONFIDENTIAL_LAB"}
    )
    assert above.status == 409 and "does not include “Lab confidential”" in _text(above)
    assert _census(db) == before
    declared = browser.post(
        f"/episodes/{episode_id}/continue", {"csrf": token, "sensitivity": "INTERNAL"}
    )
    assert declared.status == 303, _text(declared)[:600]
    assert _labels(db, episode_id) == [(1, None), (2, "INTERNAL")]
    # From now on it is recorded: the form asks nothing more.
    assert 'name="sensitivity"' not in browser.get(f"/episodes/{episode_id}").text
