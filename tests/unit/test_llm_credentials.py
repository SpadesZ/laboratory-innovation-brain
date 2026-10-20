"""A pasted model-provider key: kept only in the credential store, found again by an opaque
reference, never repeated -- and the forms that ask for one only where one is needed.

Backend-free: the credential directory on a temporary path, the provider on 127.0.0.1, the forms
as HTML. The PostgreSQL half (rows, pages, restarts, rotation, removal) is
`tests/e2e/test_web_llm_credentials_postgres.py`.
"""

from __future__ import annotations

import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from lab_brain.interfaces.web import credential_forms
from lab_brain.interfaces.web.pages import Chrome
from lab_brain.llm_runtime.provider import OpenAICompatibleClient, ProviderError, ProviderFailure
from lab_brain.llm_runtime.secrets import (
    MAX_KEY_LENGTH,
    DirectoryCredentialStore,
    SecretError,
    SecretRef,
    SecretStore,
    SecretUnavailable,
    check_pasted_key,
    parse_secret_ref,
)

KEY = "sk-test-pasted-0123456789abcdef0123456789"
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _store(root: Path) -> SecretStore:
    return SecretStore(environ={}, credentials=DirectoryCredentialStore(root))


# -- the credential directory ---------------------------------------------------------------------


def test_a_pasted_key_is_one_file_named_by_an_opaque_id_and_nothing_else(tmp_path: Path):
    root = tmp_path / "credentials"
    store = _store(root)
    assert store.secure_store == "this deployment's credential directory"
    assert store.store_protection == "filesystem", "said as what it is: not encryption"
    ref = store.store(f"  {KEY}\n")
    assert ref.scheme == "file" and parse_secret_ref(str(ref)) == ref
    (only,) = list(root.iterdir())
    assert UUID.match(only.name) and str(ref) == f"file:lab-brain/llm/{only.name}"
    assert only.read_bytes() == KEY.encode("utf-8"), "the key, trimmed, and nothing beside it"
    assert store.resolve(ref) == KEY
    if sys.platform != "win32":  # NTFS has no POSIX modes; the container's volume does
        assert (os.stat(root).st_mode & 0o777) == 0o700
        assert (os.stat(only).st_mode & 0o777) == 0o600


def test_a_restarted_workspace_finds_the_key_and_a_removed_store_does_not(tmp_path: Path):
    root = tmp_path / "credentials"
    ref = _store(root).store(KEY)
    assert _store(root).resolve(ref) == KEY, "a new process, the same volume: the same key"
    for child in root.iterdir():
        child.unlink()
    root.rmdir()
    with pytest.raises(SecretUnavailable) as gone:
        _store(root).resolve(ref)
    assert gone.value.code == "missing" and KEY not in str(gone.value)


def test_forgetting_deletes_exactly_that_key_and_only_from_its_own_kind_of_store(tmp_path: Path):
    store = _store(tmp_path / "credentials")
    first, second = store.store(KEY), store.store(KEY + "x")
    store.forget(first)
    assert store.resolve(second) == KEY + "x"
    with pytest.raises(SecretUnavailable):
        store.resolve(first)
    store.forget(first)  # again: nothing to do, nothing raised
    store.forget(SecretRef("env", "SOMETHING"))  # the operator's variable is never touched
    foreign = SecretRef("wincred", "lab-brain/llm/00000000-0000-4000-8000-000000000000")
    with pytest.raises(SecretUnavailable) as other:
        store.resolve(foreign)
    assert other.value.code == "store_unavailable"


def test_a_name_that_is_not_an_opaque_id_never_reaches_the_filesystem(tmp_path: Path):
    directory = DirectoryCredentialStore(tmp_path / "credentials")
    outside = tmp_path / "outside"
    outside.write_text("not yours", encoding="utf-8")
    for target in (
        "lab-brain/llm/../../outside",
        "../outside",
        "lab-brain/llm/" + "a" * 36,
        str(outside),
    ):
        with pytest.raises(SecretError):
            directory.read(target)
        with pytest.raises(SecretError):
            directory.write(target, KEY)
        with pytest.raises(SecretError):
            directory.delete(target)
    assert outside.read_text(encoding="utf-8") == "not yours"
    for text in ("file:lab-brain/llm/../x", "file:/etc/passwd", "file:" + "0" * 36):
        with pytest.raises(SecretError):
            parse_secret_ref(text)


def test_no_store_and_an_unusable_store_fail_closed(tmp_path: Path):
    with pytest.raises(SecretUnavailable) as none:
        SecretStore(environ={}, credentials=None).store(KEY)
    assert none.value.code == "store_unavailable" and KEY not in str(none.value)
    blocked = tmp_path / "a-file"
    blocked.write_text("", encoding="utf-8")
    store = _store(blocked)
    assert store.secure_store is None and store.store_protection is None
    with pytest.raises(SecretUnavailable) as unusable:
        store.store(KEY)
    assert unusable.value.code == "store_unavailable", "refused before any write is tried"


class _FailingStore:
    """A store whose write fails -- with the key in its own error, as a careless one might."""

    name = "failing"
    scheme = "file"
    protection = "filesystem"

    def __init__(self) -> None:
        self.deleted: list[str] = []

    def available(self) -> bool:
        return True

    def write(self, target: str, secret: str) -> None:
        raise OSError(f"disk full while writing {secret}")

    def read(self, target: str) -> str | None:
        return None

    def delete(self, target: str) -> None:
        self.deleted.append(target)


def test_a_failed_write_says_so_without_the_store_s_message_or_the_key():
    failing = _FailingStore()
    with pytest.raises(SecretUnavailable) as failed:
        SecretStore(environ={}, credentials=failing).store(KEY)
    assert failed.value.code == "write_failed"
    assert KEY not in str(failed.value) and failed.value.__cause__ is None
    assert failing.deleted, "whatever the store may have half-written is cleaned up"


def test_a_paste_that_is_not_one_key_is_refused_without_repeating_it():
    assert check_pasted_key(f"\t{KEY}  \n") == KEY
    for pasted, code in (
        ("", "empty"),
        ("   ", "empty"),
        (f"{KEY} {KEY}", "invalid"),
        (f"{KEY}\n{KEY}", "invalid"),
        (KEY + "\x00", "invalid"),
        ("k" * (MAX_KEY_LENGTH + 1), "invalid"),
    ):
        with pytest.raises(SecretError) as refused:
            check_pasted_key(pasted)
        assert refused.value.code == code
        assert not pasted.strip() or pasted.strip()[:20] not in str(refused.value)
    with pytest.raises(SecretError) as as_ref:
        parse_secret_ref(KEY)
    assert as_ref.value.code == "looks_like_key" and KEY not in str(as_ref.value)


# -- a provider's authentication refusal is never read --------------------------------------------


def _refusal(status: int, message: str) -> ProviderError:
    """What the transport makes of a provider that answers every request with `status` and an
    OpenAI-style error `message`."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

        def do_GET(self) -> None:
            body = ('{"error": {"message": "' + message + '"}}').encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        client = OpenAICompatibleClient(f"http://127.0.0.1:{server.server_address[1]}/v1", KEY)
        with pytest.raises(ProviderError) as refused:
            client.list_models()
    finally:
        server.shutdown()
    return refused.value


def test_a_masked_key_in_an_authentication_refusal_never_leaves_the_transport():
    masked = "sk-proj-abc1****************************wxyz"
    refused = _refusal(401, f"Incorrect API key provided: {masked}.")
    assert refused.failure is ProviderFailure.AUTH_FAILED
    said = f"{refused} {refused.detail}"
    assert "abc1" not in said and "wxyz" not in said and "Incorrect API key" not in said
    assert said.startswith("AUTH_FAILED: HTTP 401: the provider refused the credential")


def test_any_other_refusal_that_quotes_the_key_is_kept_only_redacted():
    # A 401/403 body is never read; any other error's body is, so it is redacted against the key.
    refused = _refusal(429, f"Rate limit reached for key {KEY}; retry later")
    assert refused.failure is ProviderFailure.PROTOCOL_ERROR
    said = f"{refused} {refused.detail}"
    assert KEY not in said and KEY[8:] not in said
    assert "HTTP 429: " in said and "[redacted]" in said and "retry later" in said


# -- the forms ------------------------------------------------------------------------------------


def _card(locale: str, protection: str | None, *, reachable: bool = True) -> str:
    chrome = Chrome("act:x", locale, "tok", "/settings/llm", "llm")
    return str(
        credential_forms.add_connection_card(
            chrome,
            providers=("openai", "openrouter", "custom"),
            protection=protection,
            store="Windows Credential Manager" if protection == "os" else "the directory",
            ollama=credential_forms.OllamaState(
                "http://127.0.0.1:11434/v1", reachable, 4 if reachable else 0
            ),
        )
    )


def _form(markup: str, form_id: str) -> str:
    found = re.search(rf'<form [^>]*id="{form_id}".*?</form>', markup, flags=re.S)
    assert found, form_id
    return found.group(0)


CREDENTIAL_FIELDS = ('name="secret_value"', 'name="env_name"', 'name="secret_ref"')


def test_the_local_model_form_has_no_credential_field_and_says_whether_ollama_answers():
    for locale in ("en", "zh-TW"):
        for protection in ("filesystem", "os", None):
            ollama = _form(_card(locale, protection), "f-ollama")
            assert not any(field in ollama for field in CREDENTIAL_FIELDS), (locale, protection)
            assert 'action="/settings/llm/ollama"' in ollama
    zh = _form(_card("zh-TW", "filesystem"), "f-ollama")
    assert "✓ 已連上本機 Ollama（4 個模型）。" in zh and ">取得可用模型</button>" in zh
    down = _form(_card("zh-TW", "filesystem", reachable=False), "f-ollama")
    assert "✗ 目前連不上本機 Ollama" in down
    assert 'id="kind-ollama" checked' in _card("en", "filesystem"), "Ollama first when it answers"


def test_the_external_form_asks_for_the_key_and_says_accurately_what_keeps_it():
    external = _form(_card("zh-TW", "filesystem"), "f-external")
    assert re.search(r'<input type="password"[^>]*name="secret_value"', external)
    assert " value=" not in re.search(r'<input type="password"[^>]*>', external).group(0)
    assert "以檔案權限保護，未加密" in external, "filesystem isolation, said as such"
    assert "加密保存" not in external and "encrypted" not in _card("en", "filesystem").replace(
        "not encrypted", ""
    )
    assert 'name="env_name"' in external and 'name="secret_ref"' in external
    advanced = re.search(r'<details class="advanced">.*?</details>', external, flags=re.S)
    assert advanced and 'name="env_name"' in advanced.group(0), "the variable is advanced"
    assert 'name="secret_value"' not in advanced.group(0), "the key is not"
    os_store = _form(_card("en", "os"), "f-external")
    assert "Windows Credential Manager" in os_store and "encrypt" not in os_store
    no_store = _form(_card("zh-TW", None), "f-external")
    assert 'name="secret_value"' not in no_store and "沒有可以保存金鑰的憑證儲存空間" in no_store


def test_exactly_one_credential_source_or_none():
    assert credential_forms.one_source(KEY, "", "") == "store"
    assert credential_forms.one_source("", "OPENAI_API_KEY", "") == "env"
    assert credential_forms.one_source("", "", "env:X") == "ref"
    assert credential_forms.one_source(" ", "", "") == "none"
    with pytest.raises(ValueError):
        credential_forms.one_source(KEY, "OPENAI_API_KEY", "")
