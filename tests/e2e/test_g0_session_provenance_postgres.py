"""G0-A: a research run started by a signed-in person names its session -- non-secretly (`011n`).

Driven through the workspace with accounts as a browser drives it, and then against the database
directly, as a writer that skips the workspace would:

recorded       a member's run (and continuation) records WEB_SESSION and the audit reference of
               the session it was started in; the reference names that person's session row, and
               is neither the cookie's token nor the session's `session_hash`, neither of which
               appears in any table but the session's own row, nor in any page or export
refused (SQL)  another actor's session, a revoked or expired one, a non-member or another project,
               an ADMIN who is not a member, an invented origin or reference -- each refused by the
               database itself
refused (HTTP) signed out, another member's project or episode, an administrator's research
immutable      origin and reference are never changed or deleted; revoking the session later
               leaves the run's record as it was; the report must say what the run recorded
migration      applies on a fresh schema and on one already holding runs, whose rows are marked
               LEGACY_UNATTESTED with no reference invented
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import psycopg
import pytest

from lab_brain.accounts.passwords import token_hash
from lab_brain.interfaces.config import Settings
from lab_brain.interfaces.web import Workspace, allowed_hosts
from lab_brain.interfaces.web.app import SESSION_COOKIE, AccountsConfig
from lab_brain.research.report_store import report_from_json
from lab_brain.research.vertical import load_vertical_factory
from lab_brain.spec import repo_root
from tests.account_fixtures import BASE_URL, CHEAP, PASSWORD, Lab
from tests.e2e.test_research_episode_postgres import GOAL, REPORT, _device
from tests.postgres_fixtures import database_url
from tests.wsgi_client import Browser, Reply

pytestmark = pytest.mark.postgres

REF_FORM = re.compile(r"^sar:[0-9a-f]{32}$")


def _browser(tmp_path: Path, lab: Lab) -> Browser:
    return Browser(
        Workspace(
            settings=Settings(dsn=database_url()),
            connect=lambda s: psycopg.connect(s.dsn),
            artifact_root=tmp_path / "artifacts",
            vertical_factory=load_vertical_factory("silicon_photonics"),
            allowed_hosts=allowed_hosts("127.0.0.1", 8765),
            accounts=AccountsConfig(mailer=lab.mail, base_url=BASE_URL, cost=CHEAP),
        )
    )


def _csrf(page: Reply) -> str:
    found = re.search(r'name="csrf" value="([^"]+)"', page.text)
    assert found, page.text[:400]
    return found.group(1)


def _signed_in(tmp_path: Path, lab: Lab, email: str) -> Browser:
    browser = _browser(tmp_path, lab)
    page = browser.get("/login")
    reply = browser.post(
        "/login", {"csrf": _csrf(page), "email": email, "password": PASSWORD, "next": "/"}
    )
    assert reply.status == 303, reply.text[:300]
    assert SESSION_COOKIE in browser.cookies
    return browser


def _session_ref(db: Any, browser: Browser) -> str:
    row = db.execute(
        "SELECT session_audit_ref FROM account_sessions WHERE session_hash = %s",
        (token_hash(browser.cookies[SESSION_COOKIE]),),
    ).fetchone()
    assert row is not None
    return str(row[0])


def _project(admin: Browser, owner: str) -> str:
    created = admin.post(
        "/projects",
        {
            "csrf": _csrf(admin.get("/projects")),
            "name": f"Rs anomaly of {owner}",
            "owner": owner,
            "clearance": ["INTERNAL", "PUBLIC"],
        },
    )
    assert created.status == 303, created.text[:400]
    return unquote(created.location.split("/projects/", 1)[1].split("?", 1)[0])


def _start(browser: Browser, tmp_path: Path, project_id: str) -> Reply:
    device = _device(tmp_path, "mesh-coarse-access")
    return browser.post(
        "/runs",
        {
            "csrf": _csrf(browser.get(f"/runs/new?project={project_id}")),
            "project": project_id,
            "goal": GOAL,
            "sensitivity": "INTERNAL",
        },
        {
            "measurement": [(REPORT.name, REPORT.read_bytes())],
            "verification_input": [(device.name, device.read_bytes())],
        },
    )


def _runs(db: Any, episode_id: str) -> list[tuple[Any, ...]]:
    return db.execute(
        "SELECT ordinal, actor_id, run_origin, session_audit_ref, research_run_id"
        " FROM research_runs WHERE episode_id = %s ORDER BY ordinal",
        (episode_id,),
    ).fetchall()


def _tables_holding(db: Any, needle: str) -> set[str]:
    """Every table of the schema whose rows' text contains `needle`."""
    tables = [
        str(r[0])
        for r in db.execute(
            "SELECT table_name FROM information_schema.tables"
            " WHERE table_schema = current_schema() AND table_type = 'BASE TABLE'"
        ).fetchall()
    ]
    return {
        t
        for t in tables
        if db.execute(
            f'SELECT EXISTS (SELECT 1 FROM "{t}" x WHERE strpos(x::text, %s) > 0)', (needle,)
        ).fetchone()[0]
    }


@pytest.fixture
def lab(db: Any) -> Lab:
    return Lab(db)


@pytest.fixture
def world(lab: Lab, tmp_path: Path) -> dict[str, Any]:
    admin = lab.admin()
    ada = lab.member("ada@uni.example.edu", "Ada", admin=admin)
    bob = lab.member("bob@gmail.example", "Bob", admin=admin)
    admin_browser = _signed_in(tmp_path, lab, "owner@lab.example")
    return {
        "admin": admin,
        "ada": ada,
        "bob": bob,
        "admin_browser": admin_browser,
        "ada_project": _project(admin_browser, "ada@uni.example.edu"),
        "bob_project": _project(admin_browser, "bob@gmail.example"),
    }


def test_a_members_run_and_continuation_record_their_sessions_and_no_secret(
    lab, world, tmp_path, db
):
    ada = _signed_in(tmp_path, lab, "ada@uni.example.edu")
    token, first_ref = ada.cookies[SESSION_COOKIE], _session_ref(db, ada)
    started = _start(ada, tmp_path, world["ada_project"])
    assert started.status == 303, started.text[:1000]
    episode = unquote(started.location.split("/episodes/", 1)[1])

    ((ordinal, actor, origin, ref, run_id),) = _runs(db, episode)
    assert (ordinal, actor, origin, ref) == (1, world["ada"].actor_id, "WEB_SESSION", first_ref)
    assert REF_FORM.match(ref)
    session_hash = token_hash(token)
    assert ref not in (token, session_hash) and token not in ref and session_hash[4:36] not in ref
    # The reference names Ada's own session row; the audit trail binds actor/project/run/trace.
    (account_actor,) = db.execute(
        "SELECT a.actor_id FROM account_sessions s JOIN accounts a USING (account_id)"
        " WHERE s.session_audit_ref = %s",
        (ref,),
    ).fetchone()
    assert account_actor == world["ada"].actor_id
    trail = db.execute(
        "SELECT r.actor_id, r.project_id, r.research_run_id, r.trace_id, r.run_origin,"
        " r.session_audit_ref, e.trace_id FROM research_run_session_audit r"
        " JOIN research_episodes e USING (episode_id) WHERE r.research_run_id = %s",
        (run_id,),
    ).fetchone()
    assert trail[:3] == (world["ada"].actor_id, world["ada_project"], run_id)
    assert trail[3] == trail[6] and trail[4:6] == ("WEB_SESSION", ref)

    # The report carries it -- and the export renders it.
    (stored,) = db.execute(
        "SELECT report FROM research_run_reports WHERE research_run_id = %s", (run_id,)
    ).fetchone()
    report = report_from_json(stored if isinstance(stored, dict) else json.loads(stored))
    assert report.session_provenance is not None
    assert (
        report.session_provenance.origin,
        report.session_provenance.session_audit_ref,
        report.session_provenance.research_run_id,
        report.session_provenance.actor_id,
        report.session_provenance.project_id,
        report.session_provenance.trace_id,
    ) == ("WEB_SESSION", ref, run_id, world["ada"].actor_id, world["ada_project"], trail[3])
    export = ada.get(f"/episodes/{episode}/runs/1/report.md")
    assert export.status == 200 and ref in export.text and "WEB_SESSION" in export.text

    # Continued later, in another session: run 2 names the session that continued it.
    later = _signed_in(tmp_path, lab, "ada@uni.example.edu")
    second_ref = _session_ref(db, later)
    assert second_ref != first_ref
    continued = later.post(f"/episodes/{episode}/continue", {"csrf": _csrf(later.get("/"))})
    assert continued.status == 303, continued.text[:1000]
    runs = _runs(db, episode)
    assert [(r[0], r[2], r[3]) for r in runs] == [
        (1, "WEB_SESSION", first_ref),
        (2, "WEB_SESSION", second_ref),
    ]

    # The first session ends; run 1's record is exactly what it was.
    ada.post("/logout", {"csrf": _csrf(ada.get("/"))})
    assert db.execute(
        "SELECT revoked_at IS NOT NULL FROM account_sessions WHERE session_audit_ref = %s",
        (first_ref,),
    ).fetchone() == (True,)
    assert _runs(db, episode) == runs

    # Neither secret is anywhere but the session's own row -- nor in any page or export.
    tokens = [token, later.cookies[SESSION_COOKIE]]
    for secret in tokens:
        assert _tables_holding(db, secret) == set()
        assert _tables_holding(db, token_hash(secret)) == {"account_sessions"}
    pages = [
        later.get(f"/episodes/{episode}"),
        later.get(f"/episodes/{episode}/runs/1/report.md"),
        later.get(f"/episodes/{episode}/runs/2/report.md"),
        later.get(f"/episodes/{episode}/runs/2/summary.html"),
        later.get("/episodes"),
        world["admin_browser"].get(f"/admin/episodes/{episode}"),
        world["admin_browser"].get(f"/admin/episodes/{episode}/runs/1/report.md"),
    ]
    assert all(p.status == 200 for p in pages), [p.status for p in pages]
    assert second_ref in pages[2].text
    for page in pages:
        for secret in tokens:
            assert secret not in page.text and token_hash(secret) not in page.text


def test_unauthenticated_cross_project_and_administrator_requests_are_refused(
    lab, world, tmp_path, db
):
    def count() -> int:
        return int(db.execute("SELECT count(*) FROM research_runs").fetchone()[0])

    before = count()
    anonymous = _browser(tmp_path, lab)
    refused = anonymous.post(
        "/runs",
        {"csrf": "x", "project": world["ada_project"], "goal": "x", "sensitivity": "PUBLIC"},
    )
    assert refused.status == 303 and refused.location.startswith("/login")
    bob = _signed_in(tmp_path, lab, "bob@gmail.example")
    assert _start(bob, tmp_path, world["ada_project"]).status in (403, 404)
    admin = world["admin_browser"]
    assert _start(admin, tmp_path, world["ada_project"]).status == 403, (
        "an ADMIN gets no scientific access to a project they are not a member of"
    )
    assert count() == before

    ada = _signed_in(tmp_path, lab, "ada@uni.example.edu")
    started = _start(ada, tmp_path, world["ada_project"])
    episode = unquote(started.location.split("/episodes/", 1)[1])
    for other in (bob, admin):
        assert other.post(
            f"/episodes/{episode}/continue", {"csrf": _csrf(other.get("/"))}
        ).status in (
            403,
            404,
        )
    assert len(_runs(db, episode)) == 1


# -- the database, for every writer ---------------------------------------------------------------


def _episode(db: Any, project_id: str, episode_id: str) -> str:
    db.execute(
        "INSERT INTO research_episodes (episode_id, project_id, trace_id, goal, state, start_time)"
        " VALUES (%s, %s, %s, 'why', 'EVIDENCE_GATHERING', now())",
        (episode_id, project_id, f"trc:{episode_id}"),
    )
    return episode_id


def _insert(
    db: Any,
    episode_id: str,
    project_id: str,
    actor_id: str,
    origin: str,
    ref: str | None,
    *,
    label: str = "INTERNAL",
    started: str = "now()",
) -> None:
    db.execute(
        "INSERT INTO research_runs (research_run_id, episode_id, project_id, actor_id, ordinal,"
        " started_at, question_label, run_origin, session_audit_ref)"
        f" VALUES ('rrn:direct', %s, %s, %s, 1, {started}, %s, %s, %s)",
        (episode_id, project_id, actor_id, label, origin, ref),
    )


def test_the_database_refuses_every_run_a_signed_in_session_does_not_vouch_for(
    lab, world, tmp_path, db
):
    ada_id, bob_id, admin_id = (world[k].actor_id for k in ("ada", "bob", "admin"))
    mine, theirs = world["ada_project"], world["bob_project"]
    ada_ref = _session_ref(db, _signed_in(tmp_path, lab, "ada@uni.example.edu"))
    bob_ref = _session_ref(db, _signed_in(tmp_path, lab, "bob@gmail.example"))
    admin_ref = _session_ref(db, world["admin_browser"])
    revoked = _signed_in(tmp_path, lab, "ada@uni.example.edu")
    revoked_ref = _session_ref(db, revoked)
    revoked.post("/logout", {"csrf": _csrf(revoked.get("/"))})
    # Signed in on the fixtures' clock, a week before the database's: long expired.
    lab.service().sign_in(email="ada@uni.example.edu", password=PASSWORD)
    (expired_ref,) = db.execute(
        "SELECT s.session_audit_ref FROM account_sessions s JOIN accounts a USING (account_id)"
        " WHERE a.actor_id = %s ORDER BY s.created_at LIMIT 1",
        (ada_id,),
    ).fetchone()
    episode = _episode(db, mine, "epi:direct")
    other = _episode(db, theirs, "epi:theirs")

    for args, refusal in (
        ((episode, mine, ada_id, "WEB_SESSION", bob_ref), "session of another account"),
        ((episode, mine, ada_id, "WEB_SESSION", revoked_ref), "revoked"),
        ((episode, mine, ada_id, "WEB_SESSION", expired_ref), "expired"),
        ((episode, mine, ada_id, "WEB_SESSION", "sar:" + "0" * 32), "names no session"),
        ((other, theirs, ada_id, "WEB_SESSION", ada_ref), "not an active member"),
        ((episode, mine, admin_id, "WEB_SESSION", admin_ref), "not an active member"),
        ((episode, mine, ada_id, "LEGACY_UNATTESTED", None), "cannot be LEGACY_UNATTESTED"),
        ((episode, mine, ada_id, "WEB_SESSION", None), "<NULL>, which names no session"),
        ((episode, mine, ada_id, "OPERATOR_CLI", ada_ref), "session_ref_iff_web_session"),
        ((episode, mine, ada_id, "BROWSER", None), "origin_is_known"),
    ):
        with pytest.raises(psycopg.Error, match=refusal):
            _insert(db, *args)
    with pytest.raises(psycopg.Error, match="before its session began"):
        _insert(
            db, episode, mine, ada_id, "WEB_SESSION", ada_ref, started="now() - interval '1 day'"
        )
    # A member, but not cleared for the question's classification.
    with pytest.raises(psycopg.Error, match="cleared for CONFIDENTIAL_LAB"):
        _insert(db, other, theirs, bob_id, "WEB_SESSION", bob_ref, label="CONFIDENTIAL_LAB")
    assert db.execute("SELECT count(*) FROM research_runs").fetchone() == (0,)

    # Ada's own live session in her own project: recorded -- and then never changed.
    _insert(db, episode, mine, ada_id, "WEB_SESSION", ada_ref)
    for change in (
        "SET session_audit_ref = %s",
        "SET run_origin = 'OPERATOR_CLI', session_audit_ref = NULL",
    ):
        params = (expired_ref,) if "%s" in change else ()
        with pytest.raises(psycopg.Error, match="recorded once and never changed"):
            db.execute(
                f"UPDATE research_runs {change} WHERE research_run_id = 'rrn:direct'", params
            )
    with pytest.raises(psycopg.Error, match=r"append-only|never deleted"):
        db.execute("DELETE FROM research_runs WHERE research_run_id = 'rrn:direct'")
    db.execute(
        "UPDATE account_sessions SET revoked_at = now() WHERE session_audit_ref = %s", (ada_ref,)
    )
    assert db.execute(
        "SELECT run_origin, session_audit_ref FROM research_runs WHERE research_run_id = 'rrn:direct'"
    ).fetchone() == ("WEB_SESSION", ada_ref)

    # A session's reference is the database's to mint, and never changes.
    with pytest.raises(psycopg.Error, match="never changes"):
        db.execute(
            "UPDATE account_sessions SET session_audit_ref = %s WHERE session_audit_ref = %s",
            ("sar:" + "1" * 32, bob_ref),
        )
    chosen = "sar:" + "2" * 32
    db.execute(
        "INSERT INTO account_sessions (session_hash, account_id, created_at, last_seen_at,"
        " expires_at, session_audit_ref) VALUES (%s, %s, now(), now(), now() + interval '1 hour', %s)",
        ("f" * 64, world["bob"].account_id, chosen),
    )
    (minted,) = db.execute(
        "SELECT session_audit_ref FROM account_sessions WHERE session_hash = %s", ("f" * 64,)
    ).fetchone()
    assert minted != chosen and REF_FORM.match(minted)

    # The report must say what the run recorded, and carry no session's lookup key.
    db.execute(
        "UPDATE research_runs SET finished_at = now(), outcome = 'SUSPENDED:PROVISIONAL'"
        " WHERE research_run_id = 'rrn:direct'"
    )

    def report(*, omit: bool = False, line: str = "", **provenance: object) -> str:
        said = {
            "origin": "WEB_SESSION",
            "session_audit_ref": ada_ref,
            "research_run_id": "rrn:direct",
            "actor_id": ada_id,
            "project_id": mine,
            "trace_id": "trc:epi:direct",
            **provenance,
        }
        return json.dumps(
            {
                "episode_id": episode,
                "project_id": mine,
                "actor_id": ada_id,
                "episode_state": "SUSPENDED",
                "conclusion": {"status": "PROVISIONAL"},
                "provenance": ["research run `rrn:direct`", line],
                "session_provenance": None if omit else said,
            }
        )

    def record(text: str) -> None:
        db.execute(
            "INSERT INTO research_run_reports (research_run_id, episode_id, project_id, report,"
            " recorded_at) VALUES ('rrn:direct', %s, %s, %s::jsonb, now())",
            (episode, mine, text),
        )

    (hash_,) = db.execute(
        "SELECT session_hash FROM account_sessions WHERE session_audit_ref = %s", (ada_ref,)
    ).fetchone()
    for text, refusal in (
        (report(omit=True), "does not say how the run was started"),
        (report(session_audit_ref=bob_ref), "misstates its session provenance"),
        (report(origin="OPERATOR_CLI", session_audit_ref=None), "misstates"),
        (report(line=f"session {hash_}"), "lookup key"),
    ):
        with pytest.raises(psycopg.Error, match=refusal):
            record(text)
    record(report())


# -- the migration --------------------------------------------------------------------------------


def _migrations() -> list[Any]:
    import importlib.util
    import sys

    name = "lab_brain_migrate_g0_session_e2e"
    spec = importlib.util.spec_from_file_location(name, repo_root() / "scripts" / "migrate.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return list(module.load_migrations())


@pytest.fixture
def scratch() -> Any:
    """A schema of its own in the test database, inside a transaction that is rolled back."""
    connection = psycopg.connect(database_url(), autocommit=False)
    schema = f"g0_session_scratch_{os.getpid()}"
    try:
        connection.execute(f'CREATE SCHEMA "{schema}"')
        connection.execute(f'SET LOCAL search_path TO "{schema}"')
        yield connection
    finally:
        connection.rollback()
        connection.close()


def test_the_migration_applies_fresh_and_over_stored_runs_without_inventing_a_reference(scratch):
    migrations = _migrations()
    names = [m.filename for m in migrations]
    cut = names.index("011n_research_session_provenance.sql")
    for migration in migrations[:cut]:
        scratch.execute(migration.sql)
    # What a deployment holds before `011n`: a person, a project, a finished run, a session.
    scratch.execute(
        "INSERT INTO actors (actor_id, actor_type, display_name) VALUES ('act:old', 'HUMAN', 'Old')"
    )
    scratch.execute("INSERT INTO projects (project_id, name) VALUES ('prj:old', 'Old')")
    scratch.execute(
        "INSERT INTO research_episodes (episode_id, project_id, trace_id, goal, state, start_time)"
        " VALUES ('epi:old', 'prj:old', 'trc:old', 'why', 'EVIDENCE_GATHERING', now())"
    )
    scratch.execute(
        "INSERT INTO research_runs (research_run_id, episode_id, project_id, actor_id, ordinal,"
        " started_at, question_label) VALUES ('rrn:old', 'epi:old', 'prj:old', 'act:old', 1,"
        " now(), 'INTERNAL')"
    )
    scratch.execute(
        "UPDATE research_runs SET finished_at = now(), outcome = 'SUSPENDED:PROVISIONAL'"
    )
    scratch.execute(
        "INSERT INTO accounts (account_id, actor_id, email, display_name, system_role, status,"
        " email_verified_at, email_verified_by, approved_at)"
        " VALUES ('acc:00000000-0000-0000-0000-000000000001', 'act:old', 'old@lab.example', 'Old',"
        " 'ADMIN', 'ACTIVE', now(), 'OPERATOR', now())"
    )
    scratch.execute(
        "INSERT INTO account_sessions (session_hash, account_id, created_at, last_seen_at,"
        " expires_at) VALUES (%s, 'acc:00000000-0000-0000-0000-000000000001', now(), now(),"
        " now() + interval '1 hour')",
        ("a" * 64,),
    )
    scratch.execute(migrations[cut].sql)
    assert scratch.execute(
        "SELECT run_origin, session_audit_ref FROM research_runs"
    ).fetchall() == [("LEGACY_UNATTESTED", None)]
    (ref,) = scratch.execute("SELECT session_audit_ref FROM account_sessions").fetchone()
    assert REF_FORM.match(ref)
    assert scratch.execute(
        "SELECT column_default FROM information_schema.columns"
        " WHERE table_schema = current_schema() AND table_name = 'research_runs'"
        " AND column_name = 'run_origin'"
    ).fetchone() == (None,), "every new run declares its origin"

    # And on an empty schema, every migration through `011n` applies.
    scratch.execute('CREATE SCHEMA "g0_session_fresh"')
    scratch.execute('SET LOCAL search_path TO "g0_session_fresh"')
    for migration in migrations[: cut + 1]:
        scratch.execute(migration.sql)
    assert scratch.execute(
        "SELECT count(*) FROM information_schema.columns WHERE table_schema = 'g0_session_fresh'"
        " AND table_name IN ('research_runs', 'account_sessions')"
        " AND column_name IN ('run_origin', 'session_audit_ref')"
    ).fetchone() == (3,)
