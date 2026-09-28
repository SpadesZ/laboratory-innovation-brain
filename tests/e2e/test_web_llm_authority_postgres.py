"""The P0 this closes, end to end: a global runtime never manufactures another project's egress.

Before `012f`, any active member of any project administered the deployment's LLM runtime, and the
active runtime declared one egress policy for EVERY project -- authored by its activator, in RESEARCH
mode whatever the project's own mode. So an actor of project A could configure an external route
and thereby let project B's evidence leave, although nobody in B had allowed it.

Driven as a browser drives it, against an OpenAI-compatible provider on 127.0.0.1 over real HTTP:

    administration   a member who is not an LLM administrator is refused every LLM settings page
                     and action, and nothing is written
    isolation        A (administrator, member of A) activates an external route and authorizes A;
                     B's evidence still reaches no model -- refused by the egress gate, recorded, and
                     said so in B's report -- and A cannot declare B's egress
    B's own choice   a member of B without the LLM_EGRESS scope may read B's policy, not declare it;
                     with it, B declares, and only then does B's evidence use the route; a
                     withdrawal closes it again
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.e2e.test_research_episode_postgres import GOAL, REPORT
from tests.e2e.test_web_llm_runtime_postgres import (
    KEY,
    _active,
    _admin,
    _browser,
    _dump,
    _text,
    _token,
)
from tests.fake_llm_provider import FakeProvider
from tests.wsgi_client import Browser, Reply

pytestmark = pytest.mark.postgres


@pytest.fixture
def fake() -> Iterator[FakeProvider]:
    provider = FakeProvider(api_key=KEY).start()
    yield provider
    provider.stop()


A, B = "act:alice", "act:bob"
PA, PB = "prj:alpha", "prj:beta"


def _world(db) -> None:  # type: ignore[no-untyped-def]
    for project, name in ((PA, "Alpha"), (PB, "Beta")):
        db.execute(
            "INSERT INTO projects (project_id, name, privacy_mode) VALUES (%s, %s, 'RESEARCH')",
            (project, name),
        )
    for actor, project, scopes in ((A, PA, ["LLM_EGRESS"]), (B, PB, [])):
        db.execute(
            "INSERT INTO actors (actor_id, actor_type, display_name) VALUES (%s, 'HUMAN', %s)",
            (actor, actor),
        )
        db.execute(
            "INSERT INTO project_memberships (actor_id, project_id, role, sensitivity_clearance,"
            " approval_scopes, active) VALUES (%s, %s, 'RESEARCHER', ARRAY['PUBLIC', 'INTERNAL'],"
            " %s, TRUE)",
            (actor, project, scopes),
        )


def _research(browser: Browser, project: str) -> Reply:
    token = _token(browser.get("/runs/new"))
    return browser.post(
        "/runs",
        {"csrf": token, "project": project, "goal": GOAL, "sensitivity": "INTERNAL"},
        {"measurement": [(REPORT.name, REPORT.read_bytes())]},
    )


def _declare(browser: Browser, project: str, db, *, withdraw: bool = False) -> Reply:  # type: ignore[no-untyped-def]
    page = browser.get(f"/projects/{project}/egress")
    token = _token(page) if 'name="csrf"' in page.text else _token(browser.get("/"))
    external = [
        r[0]
        for r in db.execute(
            "SELECT connection_id FROM llm_connections WHERE reach = 'EXTERNAL'"
        ).fetchall()
    ]
    fields: dict[str, object] = {"csrf": token}
    if withdraw:
        fields["withdraw"] = "yes"
    else:
        fields.update(connections=external, labels=["PUBLIC", "INTERNAL"])
    return browser.post(f"/projects/{project}/egress", fields)  # type: ignore[arg-type]


def test_project_membership_does_not_administer_the_deployment_llm_runtime(
    db, tmp_path: Path, fake: FakeProvider
):
    _world(db)
    bob = _browser(tmp_path, actor=B)
    before = _dump(db)
    refused = bob.get("/settings/llm")
    assert refused.status == 403
    assert f"{B} is not an LLM administrator of this deployment" in _text(refused)
    token = _token(bob.get("/"))
    for path, fields in (
        (
            "/settings/llm/connections",
            {
                "name": "sneaky",
                "base_url": fake.base_url,
                "reach": "EXTERNAL",
                "secret_mode": "none",
            },
        ),
        ("/settings/llm/runtimes", {"name": "sneaky", "external_labels": "INTERNAL"}),
    ):
        answer = bob.post(path, {"csrf": token, **fields})
        assert answer.status == 403, (path, _text(answer)[:300])
    assert _dump(db) == before, "a refused member wrote something"
    assert fake.calls == []


def test_a_global_runtime_never_authorizes_another_projects_egress(
    db, tmp_path: Path, fake: FakeProvider
):
    _world(db)
    _admin(db, A)
    alice = _browser(tmp_path, actor=A)
    bob = _browser(tmp_path, actor=B)
    _active(alice, db, fake, critic=True)
    assert _declare(alice, PA, db).status == 303

    # B's evidence reaches no model: nobody in B allowed it.
    runtime = _text(bob.get("/runtime"))
    assert f"{PB} Beta: no external egress" in runtime
    assert "/settings/llm/runtimes/" not in bob.get("/runtime").text
    sent = _research(bob, PB)
    assert sent.status == 303, _text(sent)[:400]
    report = _text(bob.get(sent.location))
    assert "hypotheses FAILED ExternalEffectRefused" in report
    assert (
        f"Project egress ({PB}): this project has declared no external-model egress policy"
        in report
    )
    assert fake.research_calls() == [], "project B's evidence reached a model"
    assert db.execute("SELECT count(*) FROM inference_provenance").fetchone()[0] == 0

    # A -- the deployment's administrator, and A's own egress authority -- cannot declare B's.
    count = db.execute("SELECT count(*) FROM project_llm_egress_policies").fetchone()[0]
    assert _declare(alice, PB, db).status == 404
    assert alice.get(f"/projects/{PB}/egress").status == 404
    assert db.execute("SELECT count(*) FROM project_llm_egress_policies").fetchone()[0] == count

    # A member of B without the scope reads B's policy and cannot declare it.
    page = bob.get(f"/projects/{PB}/egress")
    assert page.status == 200
    assert "You may read this project's policy but not declare it" in _text(page)
    refused = _declare(bob, PB, db)
    assert refused.status == 409 and "LLM_EGRESS approval scope" in _text(refused)

    # The operator grants B's member the scope; B decides for B.
    db.execute(
        "UPDATE project_memberships SET approval_scopes = ARRAY['LLM_EGRESS'] WHERE actor_id = %s",
        (B,),
    )
    assert _declare(bob, PB, db).status == 303
    assert "Beta: INTERNAL, PUBLIC to fake" in _text(bob.get("/runtime"))
    sent = _research(bob, PB)
    report = _text(bob.get(sent.location))
    assert "hypotheses DONE" in report
    (policy,) = db.execute(
        "SELECT policy_id FROM project_llm_egress_policies WHERE project_id = %s", (PB,)
    ).fetchone()
    assert f"Project egress ({PB}): policy {policy} version 1, declared by {B}" in report
    assert fake.research_calls(), "B's own authorization opened the route for B"

    # B's privacy mode is B's own, read at every call: switched to PRIVATE by the operator,
    # nothing of B's leaves, whatever B declared.
    db.execute("UPDATE projects SET privacy_mode = 'PRIVATE' WHERE project_id = %s", (PB,))
    calls = len(fake.research_calls())
    sent = _research(bob, PB)
    report = _text(bob.get(sent.location))
    assert "hypotheses FAILED ExternalEffectRefused" in report
    assert f"Project egress ({PB}): the project is in Private Mode" in report
    assert len(fake.research_calls()) == calls
    db.execute("UPDATE projects SET privacy_mode = 'RESEARCH' WHERE project_id = %s", (PB,))

    # Withdrawn, closed again -- a new version, the old one kept.
    assert _declare(bob, PB, db, withdraw=True).status == 303
    calls = len(fake.research_calls())
    sent = _research(bob, PB)
    assert "hypotheses FAILED ExternalEffectRefused" in _text(bob.get(sent.location))
    assert len(fake.research_calls()) == calls
    versions = db.execute(
        "SELECT version, cardinality(approved_connection_ids) FROM project_llm_egress_policies"
        " WHERE project_id = %s ORDER BY version",
        (PB,),
    ).fetchall()
    assert versions == [(1, 1), (2, 0)]
    history = _text(bob.get(f"/projects/{PB}/egress"))
    assert re.search(r"Version 2: every approval withdrawn by act:bob", history)
