"""A model-provider key pasted in the AI model settings, end to end on PostgreSQL.

The container deployment's case, driven as a browser drives it: the workspace keeps a pasted key
in its credential directory (`DirectoryCredentialStore`, the `credentials` volume) and the database
holds only an opaque reference and a fingerprint. Proven here:

    the normal external form takes the key; it is in the credential directory and nowhere else --
    not in any table, page, log or error the suite can see
    a restarted workspace finds it; a removed store is said plainly and repaired from the page
    rotation stops the old key at once and deletes it; removing a connection deletes a key no
    other live connection uses, and keeps one that another does
    the local model form has no credential field and goes straight to model discovery
    the advanced paths (an environment variable, an existing reference) still work
    refusals explain themselves and repeat nothing
    a runtime routed through a pasted key reasons research through the same gates as before
"""

from __future__ import annotations

import html
import logging
import re
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from lab_brain.interfaces.config import Settings
from lab_brain.interfaces.web import Workspace, allowed_hosts
from lab_brain.llm_runtime.secrets import DirectoryCredentialStore, SecretStore
from lab_brain.research.vertical import load_vertical_factory
from tests.e2e.test_research_episode_postgres import ACTOR, _member
from tests.e2e.test_web_llm_runtime_postgres import (
    _admin,
    _bind,
    _dump,
    _egress,
    _model,
    _research,
    _runtime,
)
from tests.fake_llm_provider import FakeProvider
from tests.postgres_fixtures import database_url
from tests.wsgi_client import Browser, Reply

pytestmark = pytest.mark.postgres

KEY = "sk-test-pasted-0123456789abcdefghijklmnop"
NEW_KEY = "sk-test-rotated-zyxwvutsrqponmlkjihgfedcba"
WRONG_KEY = "sk-test-mistyped-11112222333344445555"
CLOSED = "http://127.0.0.1:9/v1"  # the discard port: nothing answers


@pytest.fixture
def fake() -> Iterator[FakeProvider]:
    provider = FakeProvider(api_key=KEY).start()
    yield provider
    provider.stop()


@pytest.fixture
def ollama() -> Iterator[FakeProvider]:
    """A local model endpoint that, like Ollama, takes no credential."""
    provider = FakeProvider(api_key=None).start()
    yield provider
    provider.stop()


def _browser(
    tmp_path: Path,
    *,
    store: str = "credentials",
    ollama_url: str = CLOSED,
    credentials: object = "directory",
    environ: dict[str, str] | None = None,
    locale: str = "en",
) -> Browser:
    if credentials == "directory":
        secrets = SecretStore(
            environ=environ if environ is not None else {"FAKE_KEY": KEY},
            credentials=DirectoryCredentialStore(tmp_path / store),
        )
    else:
        secrets = SecretStore(environ=environ or {}, credentials=credentials)  # type: ignore[arg-type]
    return Browser(
        Workspace(
            actor_id=ACTOR,
            settings=Settings(dsn=database_url()),
            connect=lambda s: psycopg.connect(s.dsn),
            artifact_root=tmp_path / "artifacts",
            vertical_factory=load_vertical_factory("silicon_photonics"),
            allowed_hosts=allowed_hosts("127.0.0.1", 8765),
            secrets=secrets,
            default_locale=locale,
            ollama_url=ollama_url,
        )
    )


def _token(page: Reply) -> str:
    found = re.search(r'name="csrf" value="([^"]+)"', page.text)
    assert found
    return found.group(1)


def _text(page: Reply | str) -> str:
    markup = page.text if isinstance(page, Reply) else page
    inline = re.sub(r"</?(?:code|strong|span|a|time|label)\b[^>]*>", "", markup)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", inline)).split())


def _post(browser: Browser, path: str, fields: dict[str, str]) -> Reply:
    return browser.post(path, {"csrf": _token(browser.get("/settings/llm")), **fields})


def _add(browser: Browser, fake: FakeProvider, name: str, **credential: str) -> Reply:
    """The normal external form: provider, name, API key -- here an OpenAI-compatible service at
    a custom URL (the one advanced field a stand-in needs)."""
    return _post(
        browser,
        "/settings/llm/connections",
        {
            "provider": "custom",
            "name": name,
            "base_url": fake.base_url,
            "reach": "EXTERNAL",
            **credential,
        },
    )


def _connection(db, name: str) -> tuple[str, str | None, str | None]:  # type: ignore[no-untyped-def]
    row = db.execute(
        "SELECT connection_id, secret_ref, secret_fingerprint FROM llm_connections WHERE name = %s",
        (name,),
    ).fetchone()
    assert row is not None, name
    return str(row[0]), row[1], row[2]


def _files(root: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in root.iterdir()} if root.exists() else {}


def _form(page: Reply, form_id: str) -> str:
    found = re.search(rf'<form [^>]*id="{form_id}".*?</form>', page.text, flags=re.S)
    assert found, form_id
    return found.group(0)


def _setup(db) -> None:  # type: ignore[no-untyped-def]
    _member(db)
    _admin(db)


# -- the normal form ------------------------------------------------------------------------------


def test_a_pasted_key_is_kept_in_the_credential_directory_and_nowhere_else(
    db, tmp_path, fake, caplog, capsys
):
    _setup(db)
    caplog.set_level(logging.DEBUG)
    browser = _browser(tmp_path)
    overview = browser.get("/settings/llm")
    external = _form(overview, "f-external")
    assert re.search(r'<input type="password"[^>]*name="secret_value"', external)
    assert "protected by file permissions, not encrypted" in _text(external)

    added = _add(browser, fake, "pasted", secret_value=KEY)
    assert added.status == 303, _text(added)[:600]
    connection_id, ref, printed = _connection(db, "pasted")
    stored = _files(tmp_path / "credentials")
    (file_name,) = stored
    assert ref == f"file:lab-brain/llm/{file_name}", "an opaque reference to one file"
    assert (
        stored[file_name] == KEY.encode() and printed and re.fullmatch(r"\*{4}[0-9a-f]{4}", printed)
    )

    # The ordinary lifecycle, unchanged: get models -> test -> confirm.
    assert _post(browser, f"/settings/llm/connections/{connection_id}/fetch", {}).status == 303
    model_id = _model(db, "fake-reasoner", connection_id)
    assert _post(browser, f"/settings/llm/models/{model_id}/test", {}).status == 303
    assert _post(browser, f"/settings/llm/models/{model_id}/lock", {}).status == 303
    assert (
        db.execute(
            "SELECT lifecycle FROM llm_models WHERE model_profile_id = %s", (model_id,)
        ).fetchone()[0]
        == "LOCKED"
    )

    seen = [
        browser.get(path).text
        for path in (
            "/settings/llm",
            f"/settings/llm/connections/{connection_id}",
            f"/settings/llm/models/{model_id}",
            "/runtime",
            "/status",
        )
    ]
    assert all(KEY not in page for page in seen), "never on a page"
    assert KEY not in _dump(db), "never in any table"
    logged = caplog.text + capsys.readouterr().err
    assert KEY not in logged, "never in a log the suite can see"
    connection_page = seen[1]
    assert ref in connection_page and printed in connection_page, "reference and fingerprint only"
    assert "kept in the credential storage, fingerprint" in _text(connection_page)


def test_the_key_survives_a_restart_and_a_removed_store_is_said_and_repaired(db, tmp_path, fake):
    _setup(db)
    assert _add(_browser(tmp_path), fake, "pasted", secret_value=KEY).status == 303
    connection_id, ref, _ = _connection(db, "pasted")

    restarted = _browser(tmp_path)  # a new process, the same volume
    assert _post(restarted, f"/settings/llm/connections/{connection_id}/fetch", {}).status == 303

    for child in (tmp_path / "credentials").iterdir():  # `docker compose down -v`
        child.unlink()
    (tmp_path / "credentials").rmdir()
    emptied = _browser(tmp_path)
    overview = emptied.get("/settings/llm")
    assert "fix the API key of “pasted”." in _text(overview)
    refused = _post(emptied, f"/settings/llm/connections/{connection_id}/fetch", {})
    assert refused.status == 409
    assert "This connection's API key cannot be read." in _text(refused)
    assert KEY not in refused.text and KEY not in _dump(db)

    repaired = _post(
        emptied, f"/settings/llm/connections/{connection_id}/secret", {"secret_value": KEY}
    )
    assert repaired.status == 303, _text(repaired)[:600]
    assert _connection(db, "pasted")[1] != ref, "a fresh reference for the key pasted again"
    assert _post(emptied, f"/settings/llm/connections/{connection_id}/fetch", {}).status == 303


def test_rotation_uses_the_new_key_at_once_and_deletes_the_old_one(db, tmp_path, fake):
    _setup(db)
    browser = _browser(tmp_path)
    assert _add(browser, fake, "rotated", secret_value=KEY).status == 303
    connection_id, old_ref, old_print = _connection(db, "rotated")
    old_file = old_ref.rsplit("/", 1)[1] if old_ref else ""
    fake.api_key = NEW_KEY  # the provider revoked the old key
    assert _post(browser, f"/settings/llm/connections/{connection_id}/fetch", {}).status == 409
    assert "fix the API key of “rotated”" in _text(browser.get("/settings/llm"))

    rotated = _post(
        browser, f"/settings/llm/connections/{connection_id}/secret", {"secret_value": NEW_KEY}
    )
    assert rotated.status == 303, _text(rotated)[:600]
    _, new_ref, new_print = _connection(db, "rotated")
    assert new_ref != old_ref and new_print != old_print
    stored = _files(tmp_path / "credentials")
    assert old_file not in stored and list(stored.values()) == [NEW_KEY.encode()]
    # Saving the new key checks the connection with it: the page stops asking for a fix.
    latest = db.execute(
        "SELECT outcome FROM llm_connection_health WHERE connection_id = %s"
        " ORDER BY checked_at DESC LIMIT 1",
        (connection_id,),
    ).fetchone()[0]
    assert latest == "REACHABLE"
    assert "fix the API key of “rotated”" not in _text(browser.get("/settings/llm"))

    assert _post(browser, f"/settings/llm/connections/{connection_id}/fetch", {}).status == 303
    fake.api_key = KEY  # the provider takes only the OLD key now: the workspace does not have it
    refused = _post(browser, f"/settings/llm/connections/{connection_id}/fetch", {})
    assert refused.status == 409 and "The service refused this API key" in _text(refused)
    for secret in (KEY, NEW_KEY):
        assert secret not in _dump(db) and secret not in refused.text


def test_removing_a_connection_keeps_a_key_another_live_connection_still_uses(db, tmp_path, fake):
    _setup(db)
    browser = _browser(tmp_path)
    assert _add(browser, fake, "first", secret_value=KEY).status == 303
    first, shared, _ = _connection(db, "first")
    assert shared is not None
    # Advanced: an existing credential reference -- the one the first connection stored.
    assert _add(browser, fake, "second", secret_ref=shared).status == 303
    second, also, _ = _connection(db, "second")
    assert also == shared and len(_files(tmp_path / "credentials")) == 1

    retire = {"lifecycle": "RETIRED"}
    assert _post(browser, f"/settings/llm/connections/{first}/lifecycle", retire).status == 303
    assert len(_files(tmp_path / "credentials")) == 1, "still referenced by `second`"
    assert _post(browser, f"/settings/llm/connections/{second}/fetch", {}).status == 303
    assert _post(browser, f"/settings/llm/connections/{second}/lifecycle", retire).status == 303
    assert _files(tmp_path / "credentials") == {}, "no live connection uses it: deleted"


# -- the local model ------------------------------------------------------------------------------


def test_the_local_model_needs_no_credential_and_goes_straight_to_its_models(db, tmp_path, ollama):
    _setup(db)
    browser = _browser(tmp_path, ollama_url=ollama.base_url, locale="zh-TW")
    overview = browser.get("/settings/llm")
    local = _form(overview, "f-ollama")
    for field in ('name="secret_value"', 'name="env_name"', 'name="secret_ref"', "API 金鑰<"):
        assert field not in local, field
    assert "✓ 已連上本機 Ollama（3 個模型）。" in _text(local)
    assert 'id="kind-ollama" checked' in overview.text

    # One step: the connection is made (LOCAL, no credential) and its models fetched. A credential
    # field a client sends anyway is not read.
    went = _post(browser, "/settings/llm/ollama", {"secret_value": KEY})
    assert went.status == 303, _text(went)[:600]
    rows = db.execute(
        "SELECT connection_id, reach, secret_ref, base_url FROM llm_connections"
    ).fetchall()
    assert len(rows) == 1 and rows[0][1:] == ("LOCAL", None, ollama.base_url)
    assert db.execute("SELECT count(*) FROM llm_models").fetchone()[0] == 3
    assert _files(tmp_path / "credentials") == {} and KEY not in _dump(db)
    page = browser.get("/settings/llm")
    assert "選一個「local-ollama」的模型，執行模型能力測試。" in _text(page)
    assert "已新增為「local-ollama」" in _text(_form(page, "f-ollama"))
    assert _post(browser, "/settings/llm/ollama", {}).status == 303
    assert db.execute("SELECT count(*) FROM llm_connections").fetchone()[0] == 1, "reused"


def test_an_unreachable_ollama_is_said_and_nothing_is_created(db, tmp_path):
    _setup(db)
    browser = _browser(tmp_path, ollama_url=CLOSED, locale="zh-TW")
    assert "✗ 目前連不上本機 Ollama" in _text(_form(browser.get("/settings/llm"), "f-ollama"))
    refused = _post(browser, "/settings/llm/ollama", {})
    assert refused.status == 409
    assert "目前連不上本機 Ollama，所以沒有新增任何連線。" in _text(refused)
    assert db.execute("SELECT count(*) FROM llm_connections").fetchone()[0] == 0


# -- the advanced paths and the refusals ----------------------------------------------------------


def test_the_advanced_variable_and_reference_paths_still_work(db, tmp_path, fake):
    _setup(db)
    browser = _browser(tmp_path)
    assert _add(browser, fake, "by-variable", env_name="FAKE_KEY").status == 303
    assert _connection(db, "by-variable")[1] == "env:FAKE_KEY"
    assert _add(browser, fake, "by-reference", secret_ref="env:FAKE_KEY").status == 303
    assert _connection(db, "by-reference")[1] == "env:FAKE_KEY"
    for name in ("by-variable", "by-reference"):
        connection_id = _connection(db, name)[0]
        assert _post(browser, f"/settings/llm/connections/{connection_id}/fetch", {}).status == 303
    assert _files(tmp_path / "credentials") == {}, "nothing stored for a reference"


def test_every_credential_refusal_explains_itself_and_repeats_nothing(db, tmp_path, fake):
    _setup(db)
    browser = _browser(tmp_path)
    before = db.execute("SELECT count(*) FROM llm_connections").fetchone()[0]
    cases = (
        ({"secret_ref": KEY}, "What you pasted as a reference is a key itself."),
        ({"secret_value": KEY, "env_name": "FAKE_KEY"}, "Fill in only one of"),
        ({"secret_value": f"{KEY} {KEY}"}, "That is not a single API key"),
        ({"env_name": "NOT_SET_ANYWHERE"}, "The environment variable is not set"),
        ({"secret_ref": "file:lab-brain/llm/../../x"}, "not in a known form"),
    )
    for fields, said in cases:
        refused = _add(browser, fake, "refused", **fields)
        assert refused.status == 409, fields
        assert said in _text(refused), (fields, _text(refused)[:400])
        assert KEY not in refused.text, fields
    assert db.execute("SELECT count(*) FROM llm_connections").fetchone()[0] == before
    assert _files(tmp_path / "credentials") == {}, "a refused form stores nothing"

    assert _add(browser, fake, "mistyped", secret_value=WRONG_KEY).status == 303
    connection_id = _connection(db, "mistyped")[0]
    refused = _post(browser, f"/settings/llm/connections/{connection_id}/fetch", {})
    assert "The service refused this API key (authentication failed)." in _text(refused)
    detail = db.execute(
        "SELECT detail FROM llm_connection_health WHERE connection_id = %s", (connection_id,)
    ).fetchone()[0]
    assert detail == "HTTP 401: the provider refused the credential"
    assert "fix the API key of “mistyped”." in _text(browser.get("/settings/llm"))
    for leaked in (WRONG_KEY, "Incorrect API key"):
        assert leaked not in _dump(db) and leaked not in refused.text, leaked


def test_without_a_store_the_page_says_so_and_a_pasted_key_is_refused(db, tmp_path, fake):
    _setup(db)
    browser = _browser(tmp_path, credentials=None, environ={"FAKE_KEY": KEY})
    external = _form(browser.get("/settings/llm"), "f-external")
    assert 'name="secret_value"' not in external
    assert "has no credential storage for a pasted key" in _text(external)
    refused = _add(browser, fake, "nowhere", secret_value=KEY)
    assert refused.status == 409
    assert "This deployment has no credential storage available" in _text(refused)
    assert db.execute("SELECT count(*) FROM llm_connections").fetchone()[0] == 0
    assert KEY not in refused.text

    class Refusing:
        name = "refusing"
        scheme = "file"
        protection = "filesystem"

        def available(self) -> bool:
            return True

        def write(self, target: str, secret: str) -> None:
            raise OSError("no space left on device")

        def read(self, target: str) -> str | None:
            return None

        def delete(self, target: str) -> None:
            return None

    failing = _browser(tmp_path, credentials=Refusing())
    refused = _add(failing, fake, "unsaved", secret_value=KEY)
    assert refused.status == 409
    assert "The key could not be saved" in _text(refused)
    assert db.execute("SELECT count(*) FROM llm_connections").fetchone()[0] == 0


def test_a_key_stored_for_a_connection_the_database_refused_is_deleted(
    db, tmp_path, fake, monkeypatch
):
    from lab_brain.llm_runtime.registry import RegistryRefused, SqlLLMRegistry

    _setup(db)
    browser = _browser(tmp_path)

    def refuse(self: object, **_: object) -> None:
        raise RegistryRefused("the database refused the connection")

    monkeypatch.setattr(SqlLLMRegistry, "create_connection", refuse)
    refused = _add(browser, fake, "orphan", secret_value=KEY)
    assert refused.status == 409
    assert _files(tmp_path / "credentials") == {}, "no key is left behind for nothing"


# -- routing and egress, unchanged ----------------------------------------------------------------


def test_a_runtime_on_a_pasted_key_reasons_research_through_the_same_gates(db, tmp_path, fake):
    _setup(db)
    browser = _browser(tmp_path)
    assert _add(browser, fake, "fake", secret_value=KEY).status == 303
    connection_id = _connection(db, "fake")[0]
    assert _post(browser, f"/settings/llm/connections/{connection_id}/fetch", {}).status == 303
    ids = {}
    for name in ("fake-reasoner", "fake-critic"):
        ids[name] = _model(db, name, connection_id)
        assert _post(browser, f"/settings/llm/models/{ids[name]}/test", {}).status == 303
        assert _post(browser, f"/settings/llm/models/{ids[name]}/lock", {}).status == 303
    runtime_id = _runtime(browser, "pasted runtime")
    for slot, model in (
        ("REASONING_PRIMARY", "fake-reasoner"),
        ("FAST_UTILITY", "fake-reasoner"),
        ("REASONING_ADVERSARIAL", "fake-critic"),
    ):
        assert _bind(browser, runtime_id, slot, ids[model]).status == 303
    assert _post(browser, f"/settings/llm/runtimes/{runtime_id}/activate", {}).status == 303

    # No project egress yet: the project's evidence reaches no external model.
    refused = _research(browser, tmp_path)
    assert "hypotheses FAILED ExternalEffectRefused" in _text(browser.get(refused.location))
    assert fake.research_calls() == []

    _egress(browser, db)
    restarted = _browser(tmp_path)  # and across a restart, the stored key is found again
    sent = _research(restarted, tmp_path)
    assert sent.status == 303, _text(sent)[:500]
    recorded = db.execute(
        "SELECT DISTINCT logical_slot, model_id FROM inference_provenance"
    ).fetchall()
    assert set(recorded) == {
        ("REASONING_PRIMARY", "fake-reasoner"),
        ("FAST_UTILITY", "fake-reasoner"),
        ("REASONING_ADVERSARIAL", "fake-critic"),
    }
    assert fake.research_calls(), "the provider answered research with the pasted key"
    assert KEY not in _dump(db)
