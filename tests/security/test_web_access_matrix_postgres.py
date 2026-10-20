"""Every route of the workspace with accounts, for five people (SEC-002, R-7, the account policy).

    anonymous  signed out
    outsider   an active member of the laboratory, not in the project
    member     in the project at PUBLIC only, and not the one who opened its research
    owner      in the project at INTERNAL and PUBLIC, who opened its research
    admin      an active ADMIN, not a member of the project

The project holds one research episode, its report, and the artifacts the run used and made. A
GET is checked for its status and, on a listing page, that the project's name and the episode
never appear to someone outside it. A POST is checked for its refusal, and afterwards nothing a
refused POST could have written has changed. The ADMIN reads everything through the oversight
pages and writes no research.

`test_every_route_is_in_the_matrix` reads the routes the application dispatches on from its
source: a new route that is not in the matrix -- or named below as checked elsewhere -- fails it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import pytest

from lab_brain.accounts.projects import LabProjects
from tests.account_fixtures import Lab
from tests.e2e.test_web_accounts_postgres import _browser, _csrf, _sign_in
from tests.wsgi_client import Browser

pytestmark = pytest.mark.postgres

PEOPLE = ("anonymous", "outsider", "member", "owner", "admin")
SIGNED_IN = PEOPLE[1:]
APP = Path(__file__).resolve().parents[2] / "src" / "lab_brain" / "interfaces" / "web" / "app.py"

#: (route as the application dispatches on it, method, URL, form, {person: status}, hidden from).
#: `hidden from`: people whose page must not name the project or show the episode.
Entry = tuple[str, str, str, dict[str, Any], dict[str, int], tuple[str, ...]]

_ALL_200 = dict.fromkeys(SIGNED_IN, 200)
_ADMIN_ONLY = {"outsider": 403, "member": 403, "owner": 403, "admin": 200}
_OPENER_ONLY = {"outsider": 404, "member": 404, "owner": 200, "admin": 404}
#: An administrator's route for a record that does not exist: refused to the others, not found
#: by the administrator.
_ADMIN_ONLY_UNKNOWN = {"outsider": 403, "member": 403, "owner": 403, "admin": 404}

GETS: list[Entry] = [
    ('"/"', "GET", "/", {}, _ALL_200, ("outsider", "admin")),
    ('"/data"', "GET", "/data?project={p}", {}, _ALL_200, ("outsider", "admin")),
    ('"/episodes"', "GET", "/episodes", {}, _ALL_200, ("outsider", "member", "admin")),
    ('"/status"', "GET", "/status", {}, _ALL_200, ()),
    ('"/runs/new"', "GET", "/runs/new?project={p}", {}, _ALL_200, ("outsider", "admin")),
    ('"/runtime"', "GET", "/runtime", {}, _ALL_200, ("outsider", "admin")),
    ('"/projects"', "GET", "/projects", {}, _ALL_200, ("outsider", "admin")),
    ('"/inbox"', "GET", "/inbox", {}, _ALL_200, ("outsider", "admin")),
    ('"/account"', "GET", "/account", {}, _ALL_200, ("outsider", "admin")),
    ("_EPISODE_PATH", "GET", "/episodes/{e}", {}, _OPENER_ONLY, ()),
    ("_MARKDOWN_PATH", "GET", "/episodes/{e}/runs/1/report.md", {}, _OPENER_ONLY, ()),
    ("_SUMMARY_PATH", "GET", "/episodes/{e}/runs/1/summary.html", {}, _OPENER_ONLY, ()),
    (
        "_EGRESS_PATH",
        "GET",
        "/projects/{p}/egress",
        {},
        {"outsider": 404, "member": 200, "owner": 200, "admin": 404},
        (),
    ),
    (
        "_PROJECT_PATH",
        "GET",
        "/projects/{p}",
        {},
        {"outsider": 404, "member": 200, "owner": 200, "admin": 303},
        (),
    ),
    ('"/settings/llm"', "GET", "/settings/llm", {}, _ADMIN_ONLY, ()),
    ("_CONNECTION_PATH", "GET", "/settings/llm/connections/con:none", {}, _ADMIN_ONLY_UNKNOWN, ()),
    ("_MODEL_PATH", "GET", "/settings/llm/models/mdl:none", {}, _ADMIN_ONLY_UNKNOWN, ()),
    ("_RUNTIME_PATH", "GET", "/settings/llm/runtimes/rt:none", {}, _ADMIN_ONLY_UNKNOWN, ()),
    ('"/admin"', "GET", "/admin", {}, _ADMIN_ONLY, ()),
    ("_ADMIN_ACCOUNT_PATH", "GET", "/admin/accounts/{ada}", {}, _ADMIN_ONLY, ()),
    ("_ADMIN_PROJECT_PATH", "GET", "/admin/projects/{p}", {}, _ADMIN_ONLY, ()),
    ("_ADMIN_EPISODE_PATH", "GET", "/admin/episodes/{e}", {}, _ADMIN_ONLY, ()),
    ("_ADMIN_EXPORT_PATH", "GET", "/admin/episodes/{e}/runs/1/report.md", {}, _ADMIN_ONLY, ()),
    ("_ADMIN_MATERIAL_PATH", "GET", "/admin/projects/{p}/artifacts/{a}", {}, _ADMIN_ONLY, ()),
]

#: Refused writes: every person here must be refused, and nothing may change.
POSTS: list[Entry] = [
    (
        '"/projects"',
        "POST",
        "/projects",
        {"name": "Forged project", "owner": "bob@gmail.example", "clearance": "RESTRICTED_NDA"},
        {"outsider": 409, "member": 409, "owner": 409},
        (),
    ),
    (
        '"/data"',
        "POST",
        "/data",
        {"project": "{p}", "kind": "measurement", "sensitivity": "PUBLIC"},
        {"outsider": 403, "admin": 403},
        (),
    ),
    (
        '"/runs"',
        "POST",
        "/runs",
        {"project": "{p}", "goal": "Forged research", "sensitivity": "PUBLIC"},
        {"outsider": 403, "admin": 403},
        (),
    ),
    (
        '"/runs/review"',
        "POST",
        "/runs/review",
        {"project": "{p}", "goal": "Forged research", "sensitivity": "PUBLIC"},
        {"outsider": 403, "admin": 403},
        (),
    ),
    (
        '"/runs/new"',
        "POST",
        "/runs/new",
        {"project": "{p}"},
        {"outsider": 200, "admin": 200},
        ("outsider", "admin"),
    ),
    (
        "_CONTINUE_PATH",
        "POST",
        "/episodes/{e}/continue",
        {},
        {"outsider": 404, "member": 404, "admin": 404},
        (),
    ),
    (
        "_EGRESS_PATH",
        "POST",
        "/projects/{p}/egress",
        {"connections": "con:any", "labels": "PUBLIC"},
        {"outsider": 404, "member": 409, "admin": 404},
        (),
    ),
    (
        "_MEMBERS_PATH",
        "POST",
        "/projects/{p}/members",
        {"email": "bob@gmail.example", "clearance": "INTERNAL"},
        {"outsider": 404, "member": 409, "owner": 409},
        (),
    ),
    (
        "_MEMBERS_PATH",
        "POST",
        "/projects/{p}/members/change",
        {"actor": "{cy_actor}", "clearance": "INTERNAL", "owner": "1"},
        {"outsider": 404, "member": 409, "owner": 409},
        (),
    ),
    (
        "_MEMBERS_PATH",
        "POST",
        "/projects/{p}/members/remove",
        {"actor": "{cy_actor}"},
        {"outsider": 404, "member": 409, "owner": 409},
        (),
    ),
    (
        "_ADMIN_ACTION_PATH",
        "POST",
        "/admin/accounts/{bob}/suspend",
        {"reason": "forged"},
        {"outsider": 403, "member": 403, "owner": 403},
        (),
    ),
    (
        "_ADMIN_ACTION_PATH",
        "POST",
        "/admin/accounts/{ada}/role",
        {"role": "ADMIN"},
        {"outsider": 403, "member": 403, "owner": 403},
        (),
    ),
    (
        '"/status/check"',
        "POST",
        "/status/check",
        {},
        {"outsider": 403, "member": 403, "owner": 403},
        (),
    ),
    *[
        (
            f'"/settings/llm/{path}"',
            "POST",
            f"/settings/llm/{path}",
            {},
            {"outsider": 403, "member": 403, "owner": 403},
            (),
        )
        for path in ("connections", "runtimes", "assign", "ollama")
    ],
    *[
        (
            name,
            "POST",
            url,
            {},
            {"outsider": 403, "member": 403, "owner": 403},
            (),
        )
        for name, url in (
            ("_CONNECTION_PATH", "/settings/llm/connections/con:none/disable"),
            ("_MODEL_PATH", "/settings/llm/models/mdl:none/confirm"),
            ("_RUNTIME_PATH", "/settings/llm/runtimes/rt:none/activate"),
        )
    ],
]

#: Routes this matrix does not drive, and where they are checked instead.
ELSEWHERE = {
    '"/healthz"': "test_signed_out_only_the_sign_in_pages_and_the_health_check_answer (below)",
    '"/locale"': "tests/e2e/test_web_accounts_postgres.py::test_the_language_switch_stays_on_this_workspace",
    '"/logout"': "tests/e2e/test_web_accounts_postgres.py::test_sign_out_suspension_and_reset_end_sessions",
    '"/account/password"': "tests/integration/test_accounts_postgres.py (lockout, sessions)",
    '"/login"': "test_signed_out_only_the_sign_in_pages_and_the_health_check_answer (below)",
    '"/register"': "test_signed_out_only_the_sign_in_pages_and_the_health_check_answer (below)",
    '"/verify"': "test_signed_out_only_the_sign_in_pages_and_the_health_check_answer (below)",
    '"/password/forgot"': "test_signed_out_only_the_sign_in_pages_and_the_health_check_answer (below)",
    '"/password/reset"': "test_signed_out_only_the_sign_in_pages_and_the_health_check_answer (below)",
}

#: What a refused POST could write. Compared before and after every refusal.
_WRITTEN = (
    "SELECT count(*) FROM research_runs",
    "SELECT count(*) FROM research_episodes",
    "SELECT count(*) FROM projects",
    "SELECT count(*) FROM ingestion_items",
    "SELECT count(*) FROM artifact_occurrences",
    "SELECT count(*) FROM project_llm_egress_policies",
    "SELECT string_agg(actor_id || role || array_to_string(sensitivity_clearance, ',')"
    " || active::text, ';' ORDER BY actor_id, project_id) FROM project_memberships",
    "SELECT string_agg(account_id || system_role || status, ';' ORDER BY account_id) FROM accounts",
    "SELECT count(*) FROM llm_connections",
)


@dataclass
class World:
    lab: Lab
    browsers: dict[str, Browser]
    values: dict[str, str]
    project_name: str


@pytest.fixture
def world(db: Any, tmp_path: Path) -> World:
    from tests.e2e.test_research_episode_postgres import GOAL, REPORT, _device

    lab = Lab(db)
    admin = lab.admin()
    ada = lab.member("ada@uni.example.edu", "Ada", admin=admin)
    bob = lab.member("bob@gmail.example", "Bob", admin=admin)
    cy = lab.member("cy@lab.example", "Cy", admin=admin)
    projects = LabProjects(db, now=lab.clock)
    name = "Matrix project"
    project_id = projects.create(
        admin, name=name, owner_account_id=ada.account_id, clearance=["INTERNAL", "PUBLIC"]
    )
    projects.add_member(project_id, by=admin, member_account_id=cy.account_id, clearance=["PUBLIC"])
    projects.create(
        admin, name="Bob's own", owner_account_id=bob.account_id, clearance=["INTERNAL"]
    )
    browsers = {person: _browser(tmp_path, lab.mail) for person in PEOPLE}
    for person, email in (
        ("outsider", "bob@gmail.example"),
        ("member", "cy@lab.example"),
        ("owner", "ada@uni.example.edu"),
        ("admin", "owner@lab.example"),
    ):
        assert _sign_in(browsers[person], email).status == 303, person
    owner = browsers["owner"]
    device = _device(tmp_path, "mesh-coarse-access")
    started = owner.post(
        "/runs",
        {
            "csrf": _csrf(owner.get(f"/runs/new?project={project_id}")),
            "project": project_id,
            "goal": GOAL,
            "sensitivity": "INTERNAL",
        },
        {
            "measurement": [(REPORT.name, REPORT.read_bytes())],
            "verification_input": [(device.name, device.read_bytes())],
        },
    )
    assert started.status == 303, started.text[:500]
    episode = unquote(started.location.split("/episodes/", 1)[1])
    (artifact,) = db.execute(
        "SELECT artifact_id FROM artifact_occurrences WHERE project_id = %s"
        " ORDER BY artifact_id LIMIT 1",
        (project_id,),
    ).fetchone()
    values = {
        "p": project_id,
        "e": episode,
        "a": str(artifact),
        "ada": ada.account_id,
        "bob": bob.account_id,
        "cy_actor": cy.actor_id,
    }
    return World(lab, browsers, values, name)


def _fill(text: str, values: dict[str, str]) -> str:
    return text.format(**values)


def _written(db: Any) -> tuple[Any, ...]:
    return tuple(db.execute(sql).fetchone()[0] for sql in _WRITTEN)


def test_every_route_is_in_the_matrix() -> None:
    source = APP.read_text(encoding="utf-8")
    dispatched = {f'"{p}"' for p in re.findall(r'path == "([^"]+)"', source)}
    dispatched |= {f'"{p}"' for p in re.findall(r'^\s+"(/[a-z/]+)": \(self\._', source, flags=re.M)}
    dispatched |= set(re.findall(r"^(_[A-Z_]+_PATH) = re\.compile", source, flags=re.M))
    covered = {e[0] for e in GETS + POSTS} | {k.split(" ")[0] for k in ELSEWHERE}
    assert dispatched - covered == set(), "routes with no access check in the matrix"


#: What each of an ADMIN's oversight reads records, before anything is shown.
_RECORDS = {
    "_ADMIN_PROJECT_PATH": "project-summary",
    "_ADMIN_EPISODE_PATH": "episode-reports:{e}",
    "_ADMIN_MATERIAL_PATH": "material:{a}",
}


def test_every_read_is_its_authorized_peoples(world: World) -> None:
    observed: dict[str, dict[str, int]] = {}
    db = world.lab.connection
    for route, _method, url, _form, expected, hidden in GETS:
        target = _fill(url, world.values)
        for person in PEOPLE:
            reply = world.browsers[person].get(target)
            observed.setdefault(f"{route} {target}", {})[person] = reply.status
            if person == "anonymous":
                assert reply.status == 303 and reply.location.startswith("/login?next="), target
                continue
            assert reply.status == expected[person], (target, person, reply.status)
            if person == "admin" and route in _RECORDS:
                subject = _fill(_RECORDS[route], world.values)
                assert db.execute(
                    "SELECT 1 FROM admin_access_log WHERE project_id = %s AND subject = %s",
                    (world.values["p"], subject),
                ).fetchone(), f"{target}: the look is recorded"
            if person in hidden:
                assert world.project_name not in reply.text, (target, person)
                assert world.values["e"] not in reply.text, (target, person)


def test_every_refused_write_is_refused_and_writes_nothing(world: World) -> None:
    db = world.lab.connection
    before = _written(db)
    for route, method, url, form, expected, hidden in POSTS:
        target = _fill(url, world.values)
        filled = {k: _fill(v, world.values) for k, v in form.items()}
        anonymous = world.browsers["anonymous"].post(target, {"csrf": "x", **filled})
        assert anonymous.status == 303 and anonymous.location.startswith("/login?expired=1"), target
        for person, status in expected.items():
            browser = world.browsers[person]
            files = {"files": [("forged.csv", b"a,b\n1,2\n")]} if route == '"/data"' else None
            reply = browser.post(target, {"csrf": _csrf(browser.get("/")), **filled}, files)
            assert reply.status == status, (method, target, person, reply.status)
            if person in hidden:
                assert world.project_name not in reply.text, (target, person)
        assert _written(db) == before, f"{method} {target} changed what it must not"


def test_signed_out_only_the_sign_in_pages_and_the_health_check_answer(world: World) -> None:
    anonymous, admin = world.browsers["anonymous"], world.browsers["admin"]
    for path in ("/login", "/register", "/password/forgot"):
        assert anonymous.get(path).status == 200, path
        assert admin.get(path).status == (303 if path != "/password/forgot" else 200), path
    for path in ("/verify?token=forged", "/password/reset?token=forged"):
        assert anonymous.get(path).status == 410, path
    token = _csrf(anonymous.get("/login"))
    for path, form in (
        ("/verify", {"token": "forged", "name": "X", "password": "p" * 16, "repeat": "p" * 16}),
        ("/password/reset", {"token": "forged", "password": "p" * 16, "repeat": "p" * 16}),
    ):
        assert anonymous.post(path, {"csrf": token, **form}).status == 410, path
    assert anonymous.get("/healthz").status == 200
    assert anonymous.get("/healthz").text == "ok", "nothing about any actor"
    for browser in (anonymous, admin):
        reply = browser._call("PUT", "/", b"", "", host=None)
        assert reply.status == 405
