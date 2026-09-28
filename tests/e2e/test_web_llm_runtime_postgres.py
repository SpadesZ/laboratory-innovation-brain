"""Research workspace V2 end to end on PostgreSQL: language, LLM settings, and real-LLM routing.

Driven as a browser drives it (pages fetched, the CSRF token read from a form, redirects and
cookies followed) against an OpenAI-compatible provider on 127.0.0.1 (`tests.fake_llm_provider`),
reached over a real socket with a real Bearer credential. No simulator exists and none is emulated.

    language          the interface switches; stored text, identifiers and the report do not
    credentials       referenced (env / OS store), fingerprinted, never stored, shown or echoed --
                      not even when the provider echoes a wrong key back
    lifecycle         connection configuration apart from health; discover -> test -> lock ->
                      unlock; invalid configuration refused
    binding           a slot takes only a locked model that PROVED what the slot's roles need
    active runtime    new research is reasoned by it through the same ScientificLLM, gates, typed
                      parsers and InferenceProvenance -- the model, route and provider on record
    fallback          the Critic's fallback to PRIMARY shown as such and recorded as such; no
                      runtime -> the catalog reasoner; an unusable runtime -> the run refused
    restart           settings, locks, the active runtime and the OS-stored credential persist

Every test that configures routes does so as an actor the operator granted LLM administration
(`012f`), and every test that sends a project's evidence to an EXTERNAL route first has that project
declare its own egress policy: a global runtime supplies routes, never that permission
(`test_web_llm_authority_postgres` holds the refusals).
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from lab_brain.interfaces.config import Settings
from lab_brain.interfaces.web import Workspace, allowed_hosts
from lab_brain.llm_runtime.secrets import SecretStore
from lab_brain.research.report_store import report_from_json
from lab_brain.research.vertical import load_vertical_factory
from tests.e2e.test_research_episode_postgres import ACTOR, GOAL, PROJECT, REPORT, _device, _member
from tests.fake_llm_provider import FakeProvider
from tests.postgres_fixtures import database_url
from tests.report_samples import leaves
from tests.wsgi_client import Browser, Reply

pytestmark = pytest.mark.postgres

KEY = "sk-test-labbrain-0123456789abcdefghij"
TYPED_KEY = "sk-test-typedin-9876543210zyxwvutsrq"
WRONG_KEY = "sk-test-wrongkey-00000000000000000000"


class MemoryCredentialStore:
    """Stands in for the operating system's credential store in these tests."""

    name = "test credential store"

    def __init__(self) -> None:
        self.items: dict[str, str] = {}

    def available(self) -> bool:
        return True

    def write(self, target: str, secret: str) -> None:
        self.items[target] = secret

    def read(self, target: str) -> str | None:
        return self.items.get(target)

    def delete(self, target: str) -> None:
        self.items.pop(target, None)


@pytest.fixture
def fake() -> Iterator[FakeProvider]:
    provider = FakeProvider(api_key=KEY).start()
    yield provider
    provider.stop()


def _browser(
    tmp_path: Path,
    *,
    environ: dict[str, str] | None = None,
    credentials: MemoryCredentialStore | None = None,
    actor: str = ACTOR,
) -> Browser:
    return Browser(
        Workspace(
            actor_id=actor,
            settings=Settings(dsn=database_url()),
            connect=lambda s: psycopg.connect(s.dsn),
            artifact_root=tmp_path / "artifacts",
            vertical_factory=load_vertical_factory("silicon_photonics"),
            allowed_hosts=allowed_hosts("127.0.0.1", 8765),
            secrets=SecretStore(
                environ={"FAKE_KEY": KEY} if environ is None else environ, credentials=credentials
            ),
        )
    )


def _token(page: Reply) -> str:
    found = re.search(r'name="csrf" value="([^"]+)"', page.text)
    assert found, "the page carries no form token"
    return found.group(1)


def _text(page: Reply | str) -> str:
    markup = page.text if isinstance(page, Reply) else page
    inline = re.sub(r"</?(?:code|strong|span|a)\b[^>]*>", "", markup)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", inline)).split())


def _post(browser: Browser, path: str, fields: dict[str, object]) -> Reply:
    token = _token(browser.get("/settings/llm"))
    sent = {k: v for k, v in fields.items() if isinstance(v, str)}
    lists = {k: list(v) for k, v in fields.items() if isinstance(v, (list, tuple))}
    return browser.post(path, {"csrf": token, **sent, **lists})


def _connect(
    browser: Browser,
    fake: FakeProvider,
    *,
    name: str = "fake",
    reach: str = "EXTERNAL",
    mode: str = "env",
    env: str = "FAKE_KEY",
    value: str = "",
) -> Reply:
    return _post(
        browser,
        "/settings/llm/connections",
        {
            "name": name,
            "base_url": fake.base_url,
            "reach": reach,
            "secret_mode": mode,
            "env_name": env,
            "secret_value": value,
        },
    )


def _id(reply: Reply) -> str:
    assert reply.status == 303, reply.text[:2000]
    return reply.location.rsplit("/", 1)[1]


def _model(db, name: str, connection_id: str | None = None) -> str:  # type: ignore[no-untyped-def]
    sql = "SELECT model_profile_id FROM llm_models WHERE model_name = %s"
    params: tuple[str, ...] = (name,)
    if connection_id is not None:
        sql += " AND connection_id = %s"
        params = (name, connection_id)
    return str(db.execute(sql, params).fetchone()[0])


def _proven(browser: Browser, db, connection_id: str, *names: str) -> dict[str, str]:  # type: ignore[no-untyped-def]
    """Fetch, test and lock the named models. Returns name -> model id."""
    assert _post(browser, f"/settings/llm/connections/{connection_id}/fetch", {}).status == 303
    ids = {}
    for name in names:
        model_id = _model(db, name, connection_id)
        assert _post(browser, f"/settings/llm/models/{model_id}/test", {}).status == 303
        assert _post(browser, f"/settings/llm/models/{model_id}/lock", {}).status == 303
        ids[name] = model_id
    return ids


def _runtime(browser: Browser, name: str, labels: tuple[str, ...] = ("PUBLIC", "INTERNAL")) -> str:
    return _id(_post(browser, "/settings/llm/runtimes", {"name": name, "external_labels": labels}))


def _bind(browser: Browser, runtime_id: str, slot: str, model_id: str) -> Reply:
    return _post(
        browser, f"/settings/llm/runtimes/{runtime_id}/bind", {"slot": slot, "model": model_id}
    )


def _active(
    browser: Browser,
    db,
    fake: FakeProvider,
    *,
    critic: bool,
    labels: tuple[str, ...] = ("PUBLIC", "INTERNAL"),
) -> tuple[str, dict[str, str]]:  # type: ignore[no-untyped-def]
    connection_id = _id(_connect(browser, fake))
    ids = _proven(browser, db, connection_id, "fake-reasoner", "fake-critic")
    runtime_id = _runtime(browser, "fake runtime", labels)
    assert _bind(browser, runtime_id, "REASONING_PRIMARY", ids["fake-reasoner"]).status == 303
    assert _bind(browser, runtime_id, "FAST_UTILITY", ids["fake-reasoner"]).status == 303
    if critic:
        assert _bind(browser, runtime_id, "REASONING_ADVERSARIAL", ids["fake-critic"]).status == 303
    activated = _post(browser, f"/settings/llm/runtimes/{runtime_id}/activate", {})
    assert activated.status == 303, _text(activated)
    return runtime_id, ids


def _research(browser: Browser, tmp_path: Path, case: str | None = "mesh-coarse-access") -> Reply:
    token = _token(browser.get("/runs/new"))
    files: dict[str, list[tuple[str, bytes]]] = {
        "measurement": [(REPORT.name, REPORT.read_bytes())]
    }
    if case is not None:
        device = _device(tmp_path, case)
        files["verification_input"] = [(device.name, device.read_bytes())]
    return browser.post(
        "/runs", {"csrf": token, "project": PROJECT, "goal": GOAL, "sensitivity": "INTERNAL"}, files
    )


def _dump(db) -> str:  # type: ignore[no-untyped-def]
    """Every row of every table a workspace or a run writes, as text."""
    tables = [
        r[0]
        for r in db.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        ).fetchall()
    ]
    return "\n".join(
        str(row[0])
        for t in tables
        for row in db.execute(f"SELECT row_to_json(x)::text FROM {t} x").fetchall()
    )


def _admin(db, actor: str = ACTOR) -> None:  # type: ignore[no-untyped-def]
    """The operator's grant (`lab-brain admin llm-admin`): LLM administration, `012f`."""
    db.execute(
        "INSERT INTO llm_administrators (actor_id, granted_at, granted_through)"
        " VALUES (%s, now(), 'OPERATOR_CLI')",
        (actor,),
    )


def _egress(browser: Browser, db, labels: tuple[str, ...] = ("PUBLIC", "INTERNAL")) -> Reply:  # type: ignore[no-untyped-def]
    """The project declares, through its own egress page, that its evidence may reach every
    EXTERNAL connection here. It must be out of Private Mode, and the declaring member must hold
    the LLM_EGRESS approval scope -- both the operator's decisions, made here in SQL."""
    db.execute("UPDATE projects SET privacy_mode = 'RESEARCH' WHERE project_id = %s", (PROJECT,))
    db.execute(
        "UPDATE project_memberships SET approval_scopes = ARRAY['LLM_EGRESS']"
        " WHERE actor_id = %s AND project_id = %s",
        (ACTOR, PROJECT),
    )
    external = [
        r[0]
        for r in db.execute(
            "SELECT connection_id FROM llm_connections WHERE reach = 'EXTERNAL'"
            " AND lifecycle = 'ENABLED'"
        ).fetchall()
    ]
    token = _token(browser.get(f"/projects/{PROJECT}/egress"))
    declared = browser.post(
        f"/projects/{PROJECT}/egress",
        {"csrf": token, "connections": external, "labels": list(labels)},
    )
    assert declared.status == 303, _text(declared)[:600]
    return declared


# -- language -------------------------------------------------------------------------------------


def test_the_interface_switches_language_and_the_research_does_not(db, tmp_path, fake):
    _member(db)
    browser = _browser(tmp_path)
    sent = _research(browser, tmp_path, case=None)
    episode = sent.location
    stored_before = db.execute("SELECT report::text FROM research_run_reports").fetchone()[0]
    english = browser.get(episode)
    assert '<html lang="en">' in english.text and "Episode state now:" in _text(english)
    markdown_en = browser.get(f"{episode}/runs/1/report.md").text

    token = _token(english)
    switched = browser.post("/locale", {"csrf": token, "locale": "zh-TW", "next": episode})
    assert switched.status == 303 and switched.location == episode
    cookie = switched.headers["Set-Cookie"]
    assert cookie.startswith("lb_locale=zh-TW;") and "HttpOnly" in cookie
    assert "SameSite=Strict" in cookie

    chinese = browser.get(episode)
    shown = _text(chinese)
    assert '<html lang="zh-TW">' in chinese.text
    assert "目前 episode 狀態" in shown and "LLM 設定" in shown
    assert "Episode state now:" not in shown
    (report,) = [
        report_from_json(json.loads(r[0]))
        for r in db.execute("SELECT report::text FROM research_run_reports").fetchall()
    ]
    missing = [
        leaf
        for leaf in leaves(report)
        if isinstance(leaf, str)
        and " ".join(leaf.replace("`", "").replace("**", "").split()) not in shown
    ]
    assert not missing, f"the zh-TW page lost stored text: {missing[:3]}"
    assert browser.get(f"{episode}/runs/1/report.md").text == markdown_en
    assert (
        db.execute("SELECT report::text FROM research_run_reports").fetchone()[0] == stored_before
    )
    assert "新研究" in _text(browser.get("/runs/new"))

    # Nothing but a known locale is set, and the way back is only ever this workspace.
    bogus = browser.post("/locale", {"csrf": token, "locale": "fr", "next": "/"})
    assert bogus.status == 303 and "Set-Cookie" not in bogus.headers
    away = browser.post("/locale", {"csrf": token, "locale": "en", "next": "//evil.test/x"})
    assert away.location == "/"
    assert '<html lang="en">' in browser.get("/").text


# -- credentials --------------------------------------------------------------------------------------


def test_credentials_are_referenced_never_stored_shown_or_echoed(db, tmp_path, fake):
    _member(db)
    _admin(db)
    store = MemoryCredentialStore()
    browser = _browser(tmp_path, credentials=store)
    seen: list[str] = []

    env_id = _id(_connect(browser, fake))
    page = browser.get(f"/settings/llm/connections/{env_id}")
    seen.append(page.text)
    ref, printed = db.execute(
        "SELECT secret_ref, secret_fingerprint FROM llm_connections WHERE connection_id = %s",
        (env_id,),
    ).fetchone()
    assert ref == "env:FAKE_KEY" and re.fullmatch(r"\*{4}[0-9a-f]{4}", printed)
    assert "env:FAKE_KEY" in page.text and printed in page.text

    typed_id = _id(_connect(browser, fake, name="typed", mode="store", value=TYPED_KEY))
    ref = db.execute(
        "SELECT secret_ref FROM llm_connections WHERE connection_id = %s", (typed_id,)
    ).fetchone()[0]
    assert (
        ref.startswith("wincred:lab-brain/llm/") and store.items[ref.split(":", 1)[1]] == TYPED_KEY
    )
    page = browser.get(f"/settings/llm/connections/{typed_id}")
    seen.append(page.text)
    assert re.search(r'<input type="password" name="secret_value"[^>]*>', page.text)
    assert 'name="secret_value" value' not in page.text

    # No secure store here: a typed-in credential is refused, and nothing is written.
    bare = _browser(tmp_path)
    count = db.execute("SELECT count(*) FROM llm_connections").fetchone()[0]
    refused = _connect(bare, fake, name="nostore", mode="store", value=TYPED_KEY)
    seen.append(refused.text)
    assert refused.status == 409 and "no secure credential store" in _text(refused)
    assert db.execute("SELECT count(*) FROM llm_connections").fetchone()[0] == count
    pasted = _connect(browser, fake, name="pasted", env=KEY)
    seen.append(pasted.text)
    assert pasted.status == 409 and "looks like a credential" in _text(pasted)

    # A wrong key: the provider echoes it back; the workspace records and shows it redacted.
    wrong = _browser(tmp_path, environ={"WRONG_KEY": WRONG_KEY})
    wrong_id = _id(_connect(wrong, fake, name="wrong", env="WRONG_KEY"))
    assert _post(wrong, f"/settings/llm/connections/{wrong_id}/health", {}).status == 303
    outcome, detail = db.execute(
        "SELECT outcome, detail FROM llm_connection_health WHERE connection_id = %s", (wrong_id,)
    ).fetchone()
    assert outcome == "AUTH_FAILED" and "[redacted]" in detail
    seen.append(wrong.get(f"/settings/llm/connections/{wrong_id}").text)
    seen.extend(browser.get(p).text for p in ("/settings/llm", "/runtime", "/runs/new"))

    everything = _dump(db) + "\n".join(seen)
    for secret in (KEY, TYPED_KEY, WRONG_KEY):
        assert secret not in everything, "a credential was stored or shown"
        assert secret[8:] not in everything


# -- lifecycle and invalid configuration ------------------------------------------------------------


def test_connection_configuration_health_and_model_lifecycle(db, tmp_path, fake):
    _member(db)
    _admin(db)
    browser = _browser(tmp_path)
    before = db.execute("SELECT count(*) FROM llm_connections").fetchone()[0]
    for fields, reason in (
        ({"base_url": "http://10.0.0.5:8000/v1", "reach": "LOCAL"}, "only be declared of this"),
        ({"base_url": "http://user:pw@127.0.0.1:9/v1"}, "carries no credentials"),
        ({"base_url": "ftp://127.0.0.1/v1"}, "http:// or https://"),
        ({"name": "Bad Name"}, "lower-case letters"),
    ):
        reply = _post(
            browser,
            "/settings/llm/connections",
            {
                "name": "fake",
                "base_url": fake.base_url,
                "reach": "EXTERNAL",
                "secret_mode": "env",
                "env_name": "FAKE_KEY",
                **fields,
            },
        )
        assert reply.status == 409 and reason in _text(reply), (fields, _text(reply)[:300])
    assert db.execute("SELECT count(*) FROM llm_connections").fetchone()[0] == before

    connection_id = _id(_connect(browser, fake))
    duplicate = _connect(browser, fake)
    assert duplicate.status == 409 and "already exists" in _text(duplicate)
    assert _post(browser, f"/settings/llm/connections/{connection_id}/fetch", {}).status == 303
    states = dict(
        db.execute(
            "SELECT model_name, lifecycle FROM llm_models WHERE source = 'FETCHED'"
        ).fetchall()
    )
    assert states == dict.fromkeys(("fake-reasoner", "fake-critic", "fake-chatty"), "DISCOVERED")
    declared = _post(
        browser, f"/settings/llm/connections/{connection_id}/declare", {"model_name": "my-model"}
    )
    assert declared.status == 303

    reasoner = _model(db, "fake-reasoner")
    early = _post(browser, f"/settings/llm/models/{reasoner}/lock", {})
    assert early.status == 409 and "locked only after it is tested" in _text(early)
    assert _post(browser, f"/settings/llm/models/{reasoner}/test", {}).status == 303
    outcomes = dict(
        db.execute(
            "SELECT DISTINCT ON (capability) capability, outcome FROM llm_capability_probes"
            " WHERE model_profile_id = %s ORDER BY capability, probed_at DESC",
            (reasoner,),
        ).fetchall()
    )
    assert set(outcomes.values()) == {"PASSED"} and len(outcomes) == 8
    assert _post(browser, f"/settings/llm/models/{reasoner}/lock", {}).status == 303
    lifecycle, fingerprint = db.execute(
        "SELECT lifecycle, lock_fingerprint FROM llm_models WHERE model_profile_id = %s",
        (reasoner,),
    ).fetchone()
    assert lifecycle == "LOCKED" and fingerprint.startswith("lk:")
    again = _post(browser, f"/settings/llm/models/{reasoner}/test", {})
    assert again.status == 409 and "unlock it to test it again" in _text(again)
    assert _post(browser, f"/settings/llm/models/{reasoner}/unlock", {}).status == 303
    assert _post(browser, f"/settings/llm/models/{reasoner}/lock", {}).status == 303

    # Health is what the endpoint answers; configuration is what the operator decided.
    fake.stop()
    assert _post(browser, f"/settings/llm/connections/{connection_id}/health", {}).status == 303
    health, lifecycle = db.execute(
        "SELECT h.outcome, c.lifecycle FROM llm_connection_health h JOIN llm_connections c"
        " USING (connection_id) WHERE h.connection_id = %s ORDER BY h.checked_at DESC LIMIT 1",
        (connection_id,),
    ).fetchone()
    assert (health, lifecycle) == ("UNREACHABLE", "ENABLED")
    assert (
        db.execute(
            "SELECT lifecycle FROM llm_models WHERE model_profile_id = %s", (reasoner,)
        ).fetchone()[0]
        == "LOCKED"
    )
    fields = {"lifecycle": "DISABLED"}
    assert (
        _post(browser, f"/settings/llm/connections/{connection_id}/lifecycle", fields).status == 303
    )
    refused = _post(browser, f"/settings/llm/connections/{connection_id}/fetch", {})
    assert refused.status == 409 and "is DISABLED" in _text(refused)

    # LLM settings are deployment administration: membership of the project is not enough.
    _member(db, "act:colleague")
    colleague = _browser(tmp_path, actor="act:colleague")
    assert colleague.get("/settings/llm").status == 403
    stranger = _browser(tmp_path, actor="act:test")
    assert stranger.get("/settings/llm").status == 403


# -- binding ------------------------------------------------------------------------------------------


def test_a_slot_takes_only_a_locked_model_that_proved_what_its_roles_need(db, tmp_path, fake):
    _member(db)
    _admin(db)
    browser = _browser(tmp_path)
    external = _id(_connect(browser, fake))
    ids = _proven(browser, db, external, "fake-reasoner", "fake-chatty")
    runtime_id = _runtime(browser, "binding")
    page = browser.get(f"/settings/llm/runtimes/{runtime_id}")
    options = re.findall(r'<option value="(llm:[^"]+)">', page.text)
    assert ids["fake-reasoner"] in options and ids["fake-chatty"] not in options
    assert "fake-chatty (not proven: ROLE_HYPOTHESIS, ROLE_SPECIALIST, STRUCTURED_JSON)" in _text(
        page
    )

    forced = _bind(browser, runtime_id, "REASONING_PRIMARY", ids["fake-chatty"])
    assert forced.status == 409 and "has not proven" in _text(forced)
    remote = _bind(browser, runtime_id, "PRIVATE_LOCAL", ids["fake-reasoner"])
    assert remote.status == 409 and "PRIVATE_LOCAL is served only by a LOCAL model" in _text(remote)
    local = _id(_connect(browser, fake, name="local", reach="LOCAL"))
    local_ids = _proven(browser, db, local, "fake-reasoner")
    assert _bind(browser, runtime_id, "PRIVATE_LOCAL", local_ids["fake-reasoner"]).status == 303

    assert _bind(browser, runtime_id, "REASONING_PRIMARY", ids["fake-reasoner"]).status == 303
    early = _post(browser, f"/settings/llm/runtimes/{runtime_id}/activate", {})
    assert early.status == 409
    assert "FAST_UTILITY is part of M3's minimum route and is not bound" in _text(early)
    held = _post(browser, f"/settings/llm/models/{ids['fake-reasoner']}/unlock", {})
    assert held.status == 409 and "unbind it first" in _text(held)
    assert db.execute("SELECT count(*) FROM llm_runtimes WHERE state = 'ACTIVE'").fetchone()[0] == 0


# -- the active runtime ----------------------------------------------------------------------------


def test_an_active_runtime_reasons_new_research_through_the_provenance_path(db, tmp_path, fake):
    _member(db)
    _admin(db)
    browser = _browser(tmp_path)
    _active(browser, db, fake, critic=True)
    _egress(browser, db)
    runtime = _text(browser.get("/runtime"))
    assert "The Adversarial Critic has its own model route: fake-critic" in runtime
    assert (
        "External model routes (fake) may carry at most evidence classified PUBLIC, INTERNAL -- "
        "and only a project's evidence, only if THAT project's own egress policy approves"
        in runtime
    )
    assert f"{PROJECT} Rs anomaly: INTERNAL, PUBLIC to fake" in runtime
    assert "The active LLM runtime fake runtime serves the model slots" in _text(
        browser.get("/runs/new")
    )

    sent = _research(browser, tmp_path)
    assert sent.status == 303, _text(sent)[:500]
    episode_id = sent.location.rsplit("/", 1)[1]
    locks = dict(
        db.execute(
            "SELECT model_name, lock_fingerprint FROM llm_models WHERE lock_fingerprint IS NOT NULL"
        ).fetchall()
    )
    recorded = db.execute(
        "SELECT DISTINCT logical_slot, model_id, model_version, provider FROM inference_provenance"
    ).fetchall()
    assert set(recorded) == {
        ("REASONING_PRIMARY", "fake-reasoner", locks["fake-reasoner"], "fake"),
        ("FAST_UTILITY", "fake-reasoner", locks["fake-reasoner"], "fake"),
        ("REASONING_ADVERSARIAL", "fake-critic", locks["fake-critic"], "fake"),
    }
    inferences = db.execute("SELECT count(*) FROM inference_provenance").fetchone()[0]
    calls = fake.research_calls()
    assert len(calls) == inferences, "one provider call per recorded inference, no more"
    assert {c.model for c in calls} == {"fake-reasoner", "fake-critic"}
    assert all(c.system and c.system.startswith("Respond with ONE JSON object") for c in calls)
    spans = db.execute(
        "SELECT count(*) FROM execution_spans WHERE span_type = 'LLM_CALL' AND status = 'SUCCEEDED'"
    ).fetchone()[0]
    assert spans >= inferences, "every model call passed the budget gate's span"

    page = _text(browser.get(sent.location))
    assert "Reasoner: the active LLM runtime fake runtime" in page
    (policy,) = db.execute("SELECT policy_id FROM project_llm_egress_policies").fetchone()
    assert (
        f"Project egress ({PROJECT}): policy {policy} version 1, declared by {ACTOR} for this "
        "project (RESEARCH mode): evidence classified INTERNAL, PUBLIC may reach fake" in page
    )
    assert "No language model is configured" not in page
    assert "language model: REASONING_ADVERSARIAL -> fake-critic@" in page
    assert (
        db.execute(
            "SELECT state FROM research_episodes WHERE episode_id = %s", (episode_id,)
        ).fetchone()[0]
        == "SUSPENDED"
    )
    assert (
        db.execute("SELECT count(*) FROM jobs WHERE capability_id LIKE 'cap:sp.mesh%%'").fetchone()[
            0
        ]
        == 0
    )


def test_an_external_route_carries_only_the_evidence_it_was_permitted(db, tmp_path, fake):
    _member(db)
    _admin(db)
    browser = _browser(tmp_path)
    _active(browser, db, fake, critic=True, labels=("PUBLIC",))
    # The project would let INTERNAL leave; the runtime lets no project send more than PUBLIC.
    _egress(browser, db)
    sent = _research(browser, tmp_path)
    page = _text(browser.get(sent.location))
    assert "hypotheses FAILED ExternalEffectRefused" in page
    assert fake.research_calls() == [], "the egress gate refused before the transport was reached"
    assert db.execute("SELECT count(*) FROM inference_provenance").fetchone()[0] == 0


def test_the_critic_fallback_is_shown_and_recorded_as_a_fallback(db, tmp_path, fake):
    _member(db)
    _admin(db)
    browser = _browser(tmp_path)
    runtime_id, ids = _active(browser, db, fake, critic=False)
    _egress(browser, db)
    shown = _text(browser.get(f"/settings/llm/runtimes/{runtime_id}"))
    assert (
        "FALLBACK: REASONING_ADVERSARIAL is not bound, so the Adversarial Critic runs on "
        "REASONING_PRIMARY (fake-reasoner). That is NOT model-route independence" in shown
    )
    same = _runtime(browser, "same model")
    for slot in ("REASONING_PRIMARY", "FAST_UTILITY", "REASONING_ADVERSARIAL"):
        assert _bind(browser, same, slot, ids["fake-reasoner"]).status == 303
    assert "a separate slot, NOT an independent model route" in _text(
        browser.get(f"/settings/llm/runtimes/{same}")
    )

    sent = _research(browser, tmp_path)
    critiques = db.execute(
        "SELECT DISTINCT logical_slot FROM inference_provenance WHERE role = 'critic'"
    ).fetchall()
    assert critiques == [("REASONING_PRIMARY",)]
    assert "the Adversarial Critic runs on REASONING_PRIMARY" in _text(browser.get(sent.location))

    # Deactivated: the explicit fallback reasons, and says so.
    assert _post(browser, f"/settings/llm/runtimes/{runtime_id}/retire", {}).status == 303
    assert "No LLM runtime is active" in _text(browser.get("/runtime"))
    calls = len(fake.calls)
    second = _research(browser, tmp_path, case=None)
    assert len(fake.calls) == calls, "no model was called"
    models = db.execute(
        "SELECT DISTINCT model_id FROM inference_provenance p JOIN research_runs r"
        " ON r.episode_id = %s WHERE p.trace_id = (SELECT trace_id FROM research_episodes"
        " WHERE episode_id = %s)",
        (second.location.rsplit("/", 1)[1], second.location.rsplit("/", 1)[1]),
    ).fetchall()
    assert models == [("rules:sp.rs_anomaly_mechanisms",)]


def test_an_unusable_active_runtime_refuses_research_rather_than_rerouting_it(db, tmp_path, fake):
    _member(db)
    _admin(db)
    _active(_browser(tmp_path), db, fake, critic=True)
    # Restarted without the variable the credential lives in.
    browser = _browser(tmp_path, environ={})
    before = db.execute("SELECT count(*) FROM research_episodes").fetchone()[0]
    refused = _research(browser, tmp_path)
    assert refused.status == 409
    assert "the environment variable FAKE_KEY is not set" in _text(refused)
    assert db.execute("SELECT count(*) FROM research_episodes").fetchone()[0] == before
    assert fake.research_calls() == []
    assert "cannot be used right now" in _text(browser.get("/runtime"))


def test_settings_locks_and_the_active_runtime_survive_a_restart(db, tmp_path, fake):
    _member(db)
    _admin(db)
    store = MemoryCredentialStore()  # the operating system's store outlives the process
    first = _browser(tmp_path, environ={}, credentials=store)
    connection_id = _id(_connect(first, fake, mode="store", value=KEY))
    ids = _proven(first, db, connection_id, "fake-reasoner")
    runtime_id = _runtime(first, "persisted")
    assert _bind(first, runtime_id, "REASONING_PRIMARY", ids["fake-reasoner"]).status == 303
    assert _bind(first, runtime_id, "FAST_UTILITY", ids["fake-reasoner"]).status == 303
    assert _post(first, f"/settings/llm/runtimes/{runtime_id}/activate", {}).status == 303
    _egress(first, db)

    again = _browser(tmp_path, environ={}, credentials=store)
    overview = _text(again.get("/settings/llm"))
    assert "fake" in overview and "persisted ACTIVE" in overview
    assert "LOCKED" in _text(again.get(f"/settings/llm/models/{ids['fake-reasoner']}"))
    assert "Ready to activate." in _text(again.get("/runtime"))
    sent = _research(again, tmp_path, case=None)
    assert sent.status == 303
    assert db.execute("SELECT DISTINCT model_id FROM inference_provenance").fetchall() == [
        ("fake-reasoner",)
    ]


def test_the_runtime_page_speaks_to_researchers_and_keeps_the_ids_one_click_away(
    db, tmp_path, fake
):
    _member(db)
    _admin(db)
    browser = _browser(tmp_path)
    runtime_id, _ids = _active(browser, db, fake, critic=False)
    token = _token(browser.get("/runtime"))
    assert (
        browser.post("/locale", {"csrf": token, "locale": "zh-TW", "next": "/runtime"}).status
        == 303
    )
    page = browser.get("/runtime").text
    main = _text(re.sub(r"<details.*?</details>", " ", page, flags=re.S))
    for name in (
        "主要推理",
        "快速輔助",
        "獨立批判",
        "語意向量",
        "假說產生與比較",
        "證據與資料搜尋",
    ):
        assert name in main, name
    assert "「反方審查」改由「主要推理」（fake-reasoner）執行" in main
    for raw in (
        "REASONING_PRIMARY",
        "REASONING_ADVERSARIAL",
        "ROLE_HYPOTHESIS",
        "HYPOTHESIS_ENGINE",
    ):
        assert not re.search(rf"(?<![A-Za-z0-9_]){raw}(?![A-Za-z0-9_])", main), raw
    details = _text(" ".join(re.findall(r"<details.*?</details>", page, flags=re.S)))
    for raw in (
        "REASONING_PRIMARY",
        "REASONING_ADVERSARIAL",
        "ROLE_HYPOTHESIS",
        "HYPOTHESIS_ENGINE",
    ):
        assert raw in details, raw
    # Nothing underneath was renamed: the rows and the router say what they said.
    assert db.execute(
        "SELECT logical_slot FROM llm_slot_bindings WHERE runtime_id = %s ORDER BY 1", (runtime_id,)
    ).fetchall() == [("FAST_UTILITY",), ("REASONING_PRIMARY",)]


def test_the_command_line_never_reaches_a_model_and_refuses_while_a_runtime_is_active(
    db, tmp_path, fake
):
    import io

    from lab_brain.interfaces import cli

    _member(db)
    _admin(db)
    _active(_browser(tmp_path), db, fake, critic=True)
    before = db.execute("SELECT count(*) FROM research_episodes").fetchone()[0]
    out = io.StringIO()
    code = cli.main(
        [
            "research",
            "run",
            "--project",
            PROJECT,
            "--actor",
            ACTOR,
            "--goal",
            GOAL,
            "--measurement",
            str(REPORT),
            "--artifact-root",
            str(tmp_path / "artifacts"),
        ],
        out=out,
        env={"LAB_BRAIN_DATABASE_URL": database_url()},
        connect=lambda s: psycopg.connect(s.dsn, autocommit=True),
    )
    assert code == 2
    assert "the command line never calls a language model" in out.getvalue()
    assert db.execute("SELECT count(*) FROM research_episodes").fetchone()[0] == before
    assert fake.research_calls() == []
