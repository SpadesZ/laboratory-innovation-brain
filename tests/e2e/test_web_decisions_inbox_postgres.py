"""The decisions inbox, with a real warrant question waiting (Causal Warrant Gate V1.1).

A diagnosis episode asks a person whether an observation bears on a hypothesis as its author
claimed. The inbox shows that question to the people who can answer it -- an enrolled reviewer,
a member of the project -- in words, with the command that signs the answer, and to nobody else:

    shown           to the enrolled reviewer, cleared for the research's classification
    not enrolled    a member who is not an enrolled reviewer is told one waits, not what it says
    classification  research classified above a person's clearance -- or whose classification was
                    never recorded -- is not shown, only counted (fail closed)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import psycopg
import pytest

from lab_brain.accounts.mail import MemoryMailer
from lab_brain.interfaces.config import Settings
from lab_brain.interfaces.web import Workspace, allowed_hosts
from lab_brain.interfaces.web.app import AccountsConfig
from lab_brain.research.vertical import load_vertical_factory
from tests.account_fixtures import BASE_URL, CHEAP, PASSWORD, Lab
from tests.debate_fixtures import PROJECT
from tests.e2e.test_causal_warrant_counterexample_postgres import CASE, REVIEWER, _proxy, _queue
from tests.postgres_fixtures import database_url
from tests.vertical_fixtures import case_by_id, run_case
from tests.wsgi_client import Browser

pytestmark = pytest.mark.postgres


def _signed_in(tmp_path: Path, email: str) -> Browser:
    browser = Browser(
        Workspace(
            settings=Settings(dsn=database_url()),
            connect=lambda s: psycopg.connect(s.dsn),
            artifact_root=tmp_path / "artifacts",
            vertical_factory=load_vertical_factory("silicon_photonics"),
            allowed_hosts=allowed_hosts("127.0.0.1", 8765),
            accounts=AccountsConfig(mailer=MemoryMailer(), base_url=BASE_URL, cost=CHEAP),
        )
    )
    page = browser.get("/login")
    token = re.search(r'name="csrf" value="([^"]+)"', page.text)
    assert token
    reply = browser.post(
        "/login", {"csrf": token.group(1), "email": email, "password": PASSWORD, "next": "/"}
    )
    assert reply.status == 303, reply.text[:300]
    return browser


def _label(db: Any, episode_id: str, label: str) -> None:
    """The question's classification, as the research service records it with the opening run
    (`012q`); written past the triggers because this harness drives the loop directly."""
    db.execute("SET session_replication_role = replica")
    try:
        db.execute(
            "INSERT INTO research_runs (research_run_id, episode_id, project_id, actor_id,"
            " ordinal, started_at, question_label) VALUES (%s, %s, %s, %s, 1, now(), %s)",
            (f"rrn:{episode_id}", episode_id, PROJECT, REVIEWER, label),
        )
    finally:
        db.execute("SET session_replication_role = origin")


@pytest.fixture
def waiting(db: Any) -> dict[str, Any]:
    _queue(db)
    fx = _proxy()
    run = run_case(db, fx, case_by_id(fx, CASE))
    assert run.request is not None
    lab = Lab(db)
    # The enrolled reviewer, signed in to their own account (bound to their actor).
    reviewer, token = lab.service().bootstrap_admin(
        email="pi@lab.example", display_name="The PI", actor_id=REVIEWER
    )
    lab.service().reset_password(token=token, password=PASSWORD)
    return {"lab": lab, "episode": run.request.episode_id, "reviewer": reviewer}


def test_the_enrolled_reviewer_is_asked_in_words_with_the_command_that_signs(waiting, db, tmp_path):
    unlabelled = _signed_in(tmp_path, "pi@lab.example").get("/inbox")
    assert "1 question(s) in your projects concern research classified above" in unlabelled.text
    _label(db, waiting["episode"], "INTERNAL")
    page = _signed_in(tmp_path, "pi@lab.example").get("/inbox")
    assert page.status == 200
    assert "Is this observation evidence for this explanation?" in page.text
    assert "contact-resistance correction" in page.text, "the explanation, in words"
    assert "is claimed to support this explanation" in page.text
    assert "lab-brain review resolve" in page.text and f"--actor {REVIEWER}" in page.text
    assert "classified above" not in page.text


def test_others_are_told_a_question_waits_but_not_what_it_says(waiting, db, tmp_path):
    _label(db, waiting["episode"], "CONFIDENTIAL_LAB")
    lab, admin = waiting["lab"], waiting["reviewer"]
    member = lab.member("ada@uni.example.edu", "Ada", admin=admin)
    db.execute(
        "INSERT INTO project_memberships (actor_id, project_id, role, sensitivity_clearance,"
        " approval_scopes, active) VALUES (%s, %s, 'MEMBER', ARRAY['PUBLIC', 'INTERNAL',"
        " 'CONFIDENTIAL_LAB'], '{}', TRUE)",
        (member.actor_id, PROJECT),
    )
    ada = _signed_in(tmp_path, "ada@uni.example.edu").get("/inbox")
    assert "1 question(s) wait for an enrolled reviewer" in ada.text
    assert "contact-resistance correction" not in ada.text
    # The reviewer's own clearance (PUBLIC, INTERNAL) does not include the research's class.
    pi = _signed_in(tmp_path, "pi@lab.example").get("/inbox")
    assert "classified above what you may read" in pi.text
    assert "contact-resistance correction" not in pi.text
