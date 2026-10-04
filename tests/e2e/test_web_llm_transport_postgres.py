"""Where a model-provider credential and a research prompt may travel, end to end on PostgreSQL.

`tests/unit/test_llm_transport.py` proves the transport's two rules over real sockets -- plaintext
only to this machine, no redirect ever followed. This file proves that every way INTO a provider
call honours them, driven as the workspace drives them:

    a new EXTERNAL http:// connection to another host is refused before a pasted key is stored --
    and an environment variable or an existing reference does not get around it
    this machine keeps plain http://: the local Ollama, the Docker host where it is declared
    a historical row -- written before the rule, or around it -- fails closed before any use:
    discovery, health, probes, key rotation, re-enabling, readiness, and an ACTIVE runtime, where
    research is refused before the credential is read
    a provider that redirects reaches nothing through any path: discovery, health, capability
    probes, research inference -- and none of its answer is kept
"""

from __future__ import annotations

import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path

import psycopg
import pytest

from lab_brain.llm_runtime.registry import SqlLLMRegistry
from lab_brain.llm_runtime.runtime import (
    LLMSettings,
    RuntimeUnavailable,
    SettingsRefused,
    load_active_runtime,
)
from lab_brain.llm_runtime.secrets import DirectoryCredentialStore, SecretStore, fingerprint
from tests.e2e.test_research_episode_postgres import ACTOR
from tests.e2e.test_web_llm_credentials_postgres import (
    KEY,
    _add,
    _browser,
    _connection,
    _files,
    _post,
    _setup,
    _text,
)
from tests.e2e.test_web_llm_runtime_postgres import (
    _bind,
    _dump,
    _egress,
    _model,
    _research,
    _runtime,
)
from tests.fake_llm_provider import REDIRECT_BODY, FakeProvider
from tests.transport_endpoints import Endpoint

pytestmark = pytest.mark.postgres

#: Another host over plaintext. Never contacted: every test shows no request was even opened.
REMOTE = "http://models.example.org/v1"
CONSTRAINT = "llm_connections_plaintext_only_on_this_machine"
_MIGRATION = Path(__file__).resolve().parents[2] / "migrations" / "012i_llm_transport.sql"


@pytest.fixture
def fake() -> Iterator[FakeProvider]:
    provider = FakeProvider(api_key=KEY).start()
    yield provider
    provider.stop()


@pytest.fixture
def ollama() -> Iterator[FakeProvider]:
    provider = FakeProvider(api_key=None).start()
    yield provider
    provider.stop()


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every URL the transport opens a request to (loopback stand-ins included)."""
    seen: list[str] = []
    original = urllib.request.OpenerDirector.open

    def recording(self, request, *args, **kwargs):  # type: ignore[no-untyped-def]
        seen.append(getattr(request, "full_url", str(request)))
        return original(self, request, *args, **kwargs)

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", recording)
    return seen


@pytest.fixture
def writes(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every key the credential directory is asked to keep (its name only)."""
    kept: list[str] = []
    original = DirectoryCredentialStore.write

    def recording(self, name: str, secret: str) -> None:  # type: ignore[no-untyped-def]
        kept.append(name)
        original(self, name, secret)

    monkeypatch.setattr(DirectoryCredentialStore, "write", recording)
    return kept


def _remote(urls: list[str]) -> list[str]:
    return [u for u in urls if "models.example.org" in u]


def _settings(db, tmp_path: Path, **kwargs: object) -> LLMSettings:  # type: ignore[no-untyped-def]
    secrets = SecretStore(
        environ={"FAKE_KEY": KEY},
        credentials=DirectoryCredentialStore(tmp_path / "credentials"),
    )
    return LLMSettings(db, secrets=secrets, actor_id=ACTOR, **kwargs)  # type: ignore[arg-type]


def _refused(call: Callable[[], object]) -> SettingsRefused:
    with pytest.raises(SettingsRefused) as refused:
        call()
    return refused.value


def _reinstate_constraint(db) -> None:  # type: ignore[no-untyped-def]
    """`012i`'s constraint, exactly as the migration adds it (NOT VALID)."""
    sql = _MIGRATION.read_text(encoding="utf-8")
    db.execute(sql[sql.index("ALTER TABLE") :])


def _historical(db, name: str, url: str = REMOTE) -> str:  # type: ignore[no-untyped-def]
    """An ENABLED EXTERNAL connection written as before `012i` (or around it): the constraint is
    lifted for the insert and put back as the migration leaves it -- NOT VALID, so the row stays."""
    connection_id = f"llc:{name}"
    salt = SqlLLMRegistry(db).salt()
    with db.transaction():
        db.execute(f"ALTER TABLE llm_connections DROP CONSTRAINT {CONSTRAINT}")
        db.execute(
            "INSERT INTO llm_connections (connection_id, name, provider_kind, base_url, reach,"
            " secret_ref, secret_fingerprint, lifecycle, created_by, created_at, updated_at)"
            " VALUES (%s, %s, 'OPENAI_COMPATIBLE', %s, 'EXTERNAL', 'env:FAKE_KEY', %s,"
            " 'ENABLED', %s, now(), now())",
            (connection_id, name, url, fingerprint(KEY, salt), ACTOR),
        )
        _reinstate_constraint(db)
    return connection_id


def _rewrite_endpoint(db, connection_id: str, url: str) -> None:  # type: ignore[no-untyped-def]
    """A connection's endpoint is its identity (`012e`); this simulates a row that pointed there
    all along -- written before the rule -- by lifting the guard and the constraint for one
    UPDATE and putting both back."""
    with db.transaction():
        db.execute("ALTER TABLE llm_connections DISABLE TRIGGER llm_connections_guard_trg")
        db.execute(f"ALTER TABLE llm_connections DROP CONSTRAINT {CONSTRAINT}")
        db.execute(
            "UPDATE llm_connections SET base_url = %s WHERE connection_id = %s",
            (url, connection_id),
        )
        _reinstate_constraint(db)
        db.execute("ALTER TABLE llm_connections ENABLE TRIGGER llm_connections_guard_trg")


def _active_runtime(db, browser, fake: FakeProvider) -> tuple[str, str]:  # type: ignore[no-untyped-def]
    """An active runtime on the stand-in (EXTERNAL, loopback), with the project's egress
    declared: research reaches the provider. Returns (connection id, runtime id)."""
    assert _add(browser, fake, "fake", secret_value=KEY).status == 303
    connection_id = _connection(db, "fake")[0]
    assert _post(browser, f"/settings/llm/connections/{connection_id}/fetch", {}).status == 303
    ids = {}
    for name in ("fake-reasoner", "fake-critic"):
        ids[name] = _model(db, name, connection_id)
        assert _post(browser, f"/settings/llm/models/{ids[name]}/test", {}).status == 303
        assert _post(browser, f"/settings/llm/models/{ids[name]}/lock", {}).status == 303
    runtime_id = _runtime(browser, "transport runtime")
    for slot, model in (
        ("REASONING_PRIMARY", "fake-reasoner"),
        ("FAST_UTILITY", "fake-reasoner"),
        ("REASONING_ADVERSARIAL", "fake-critic"),
    ):
        assert _bind(browser, runtime_id, slot, ids[model]).status == 303
    assert _post(browser, f"/settings/llm/runtimes/{runtime_id}/activate", {}).status == 303
    _egress(browser, db)
    return connection_id, runtime_id


# -- a new connection -----------------------------------------------------------------------------


def test_a_remote_plaintext_service_is_refused_before_its_key_is_stored(
    db, tmp_path, opened, writes
):
    _setup(db)
    for locale, said in (
        ("en", "An external service must use https://"),
        ("zh-TW", "外部服務的網址必須是 https://"),
    ):
        browser = _browser(tmp_path, locale=locale)
        for provider in ("custom", "openai"):  # a preset whose address is overridden, too
            refused = _post(
                browser,
                "/settings/llm/connections",
                {
                    "provider": provider,
                    "name": "plain",
                    "base_url": REMOTE,
                    "reach": "EXTERNAL",
                    "secret_value": KEY,
                },
            )
            assert refused.status == 409 and said in _text(refused), _text(refused)[:400]
            assert KEY not in refused.text
    assert writes == [] and _files(tmp_path / "credentials") == {}, "no key was ever stored"
    assert db.execute("SELECT count(*) FROM llm_connections").fetchone()[0] == 0
    assert _remote(opened) == []
    assert KEY not in _dump(db)


def test_neither_an_environment_variable_nor_an_existing_reference_gets_around_it(
    db, tmp_path, fake, opened, writes
):
    _setup(db)
    browser = _browser(tmp_path)
    # An existing stored key, kept by a legitimate connection on this machine.
    assert _add(browser, fake, "loop", secret_value=KEY).status == 303
    stored_ref = _connection(db, "loop")[1]
    assert stored_ref is not None and len(writes) == 1
    for credential in ({"env_name": "FAKE_KEY"}, {"secret_ref": stored_ref}):
        refused = _post(
            browser,
            "/settings/llm/connections",
            {"provider": "custom", "name": "plain", "base_url": REMOTE, **credential},
        )
        assert refused.status == 409 and "must use https://" in _text(refused)
    settings = _settings(db, tmp_path)
    for mode, extra in (
        ("none", {}),
        ("env", {"env_name": "FAKE_KEY"}),
        ("ref", {"secret_ref": stored_ref}),
        ("store", {"secret_value": KEY}),
    ):
        refusal = _refused(
            lambda m=mode, e=extra: settings.add_connection(
                name="plain", base_url=REMOTE, reach="EXTERNAL", secret_mode=m, **e
            )
        )
        assert refusal.code == "url.plaintext", mode
    assert len(writes) == 1, "only the legitimate connection's key was ever stored"
    names = {r[0] for r in db.execute("SELECT name FROM llm_connections").fetchall()}
    assert names == {"loop"}
    # Nor raw SQL: the database refuses a new ENABLED plaintext connection to another host.
    with pytest.raises(psycopg.errors.CheckViolation, match=CONSTRAINT):
        db.execute(
            "INSERT INTO llm_connections (connection_id, name, provider_kind, base_url, reach,"
            " lifecycle, created_by, created_at, updated_at) VALUES ('llc:raw', 'raw',"
            " 'OPENAI_COMPATIBLE', %s, 'EXTERNAL', 'ENABLED', %s, now(), now())",
            (REMOTE, ACTOR),
        )
    assert _remote(opened) == []


def test_this_machine_still_uses_plain_http(db, tmp_path, fake, ollama):
    _setup(db)
    # The local Ollama: no credential, plain http:// on loopback, straight to its models.
    local = _browser(tmp_path, ollama_url=ollama.base_url)
    assert _post(local, "/settings/llm/ollama", {}).status == 303
    row = db.execute(
        "SELECT reach, base_url, (SELECT count(*) FROM llm_models m"
        " WHERE m.connection_id = c.connection_id) FROM llm_connections c WHERE reach = 'LOCAL'"
    ).fetchone()
    assert row[0] == "LOCAL" and row[1] == ollama.base_url and row[2] == 3
    # The Docker host, where the deployment declares it: still this machine.
    gateway = _settings(db, tmp_path, local_hosts=("host.docker.internal",))
    made = gateway.add_connection(
        name="docker-host",
        base_url="http://host.docker.internal:11434/v1",
        reach="LOCAL",
        secret_mode="none",
    )
    assert made.reach == "LOCAL"
    # And loopback declared EXTERNAL -- the stand-in every routing and egress test uses.
    assert _add(local, fake, "loop", secret_value=KEY).status == 303
    loop = _connection(db, "loop")[0]
    assert _post(local, f"/settings/llm/connections/{loop}/fetch", {}).status == 303


# -- a historical row -----------------------------------------------------------------------------


def test_a_historical_plaintext_connection_fails_closed_before_any_use(
    db, tmp_path, opened, writes
):
    _setup(db)
    legacy = _historical(db, "legacy")
    settings = _settings(db, tmp_path)
    browser = _browser(tmp_path)

    fetched = _post(browser, f"/settings/llm/connections/{legacy}/fetch", {})
    assert fetched.status == 409 and "must use https://" in _text(fetched)
    for step in (
        lambda: settings.fetch_models(legacy),
        lambda: settings.check_health(legacy),
        lambda: settings.replace_secret(legacy, secret_mode="store", secret_value=KEY),
    ):
        assert _refused(step).code == "url.plaintext"
    model = settings.declare_model(legacy, "gpt-legacy")  # a name: nothing is sent
    assert _refused(lambda: settings.test_model(model.model_profile_id)).code == "url.plaintext"
    assert db.execute("SELECT count(*) FROM llm_capability_probes").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM llm_connection_health").fetchone()[0] == 0
    assert writes == [], "no key was stored for it"

    # It can always be switched off; it cannot be switched back on.
    settings.set_connection_lifecycle(legacy, "DISABLED")
    assert _refused(lambda: settings.set_connection_lifecycle(legacy, "ENABLED")).code == (
        "url.plaintext"
    )
    with pytest.raises(psycopg.errors.CheckViolation, match=CONSTRAINT):
        db.execute(
            "UPDATE llm_connections SET lifecycle = 'ENABLED' WHERE connection_id = %s", (legacy,)
        )
    settings.set_connection_lifecycle(legacy, "RETIRED")
    assert _remote(opened) == [], "not one request was opened to it"


def test_a_historical_plaintext_route_is_never_reasoned_through(db, tmp_path, fake, opened):
    _setup(db)
    browser = _browser(tmp_path)
    connection_id, runtime_id = _active_runtime(db, browser, fake)
    _rewrite_endpoint(db, connection_id, REMOTE)
    calls = len(fake.calls)
    secrets = SecretStore(credentials=DirectoryCredentialStore(tmp_path / "credentials"))

    with pytest.raises(RuntimeUnavailable, match="neither https://"):
        load_active_runtime(db, secrets)
    refused = _research(browser, tmp_path)
    assert refused.status == 409 and "neither https://" in _text(refused)
    blockers = _settings(db, tmp_path).readiness(runtime_id).blockers
    assert any("neither https://" in b for b in blockers), blockers
    assert len(fake.calls) == calls and _remote(opened) == []
    assert KEY not in _dump(db)


# -- redirects ------------------------------------------------------------------------------------


def test_no_path_through_the_service_follows_a_redirect(db, tmp_path, fake):
    _setup(db)
    browser = _browser(tmp_path)
    connection_id, _ = _active_runtime(db, browser, fake)
    # Had any redirect been followed, this target would have answered -- as a provider.
    target = Endpoint().start()
    try:
        fake.redirect_to = target.origin

        # Research inference: the prompt and its evidence go to the named endpoint and no further.
        fake.redirect_status = 307
        ran = _research(browser, tmp_path)
        assert ran.status == 303, _text(ran)[:400]
        assert (
            "hypotheses FAILED ProviderError: PROTOCOL_ERROR: HTTP 307: the endpoint redirected"
            in _text(browser.get(ran.location))
        ), "the run stops at its first model call; nothing is reasoned by whatever answers there"
        assert fake.research_calls() == [], "the redirecting endpoint answered nothing"

        # Discovery.
        fake.redirect_status = 302
        fetched = _post(browser, f"/settings/llm/connections/{connection_id}/fetch", {})
        assert fetched.status == 409 and "redirected the call" in _text(fetched)
        # Health.
        assert _post(browser, f"/settings/llm/connections/{connection_id}/health", {}).status == 303
        outcome, detail = db.execute(
            "SELECT outcome, detail FROM llm_connection_health WHERE connection_id = %s"
            " ORDER BY checked_at DESC LIMIT 1",
            (connection_id,),
        ).fetchone()
        assert outcome == "PROTOCOL_ERROR" and "HTTP 302: the endpoint redirected" in detail
        # Capability probes (a model not yet locked).
        fake.redirect_status = 308
        chatty = _model(db, "fake-chatty", connection_id)
        assert _post(browser, f"/settings/llm/models/{chatty}/test", {}).status == 303
        probes = db.execute(
            "SELECT outcome, detail FROM llm_capability_probes WHERE model_profile_id = %s",
            (chatty,),
        ).fetchall()
        assert probes and all(o != "PASSED" and "redirected" in d for o, d in probes)

        assert fake.redirected >= 4
        assert target.seen == [], "no Authorization header, prompt or evidence reached the target"
        everything = _dump(db)
        assert KEY not in everything and REDIRECT_BODY not in everything
        assert target.origin not in everything, "nor was the redirect's target kept"
    finally:
        target.stop()
