"""The LLM runtime without a database: probes, contracts, credentials, transport, language.

A probe is judged by code -- the real typed role parsers for the role capabilities, `ast` (never
execution) for CODE. Credentials are references, refused when pasted as themselves, fingerprinted
without any character of the key, redacted from everything a provider says, and stored only in an
OS store -- or not at all. The interface language changes headings, never a stored value.
"""

from __future__ import annotations

import html
import re
import sys
import uuid
from typing import Any

import pytest

from lab_brain.cognition.roles import ADVERSARIAL_CRITIC, HYPOTHESIS_ENGINE, QUERY_REWRITER
from lab_brain.cognition.routing import CognitiveRole, ModelRouter
from lab_brain.core.models.inference import LogicalSlot
from lab_brain.interfaces.web import pages
from lab_brain.interfaces.web.i18n import LOCALES, keys, templates
from lab_brain.llm_runtime import contracts
from lab_brain.llm_runtime.capabilities import (
    BINDABLE_SLOTS,
    SLOT_REQUIREMENTS,
    Capability,
    critic_fallback,
    role_routes,
)
from lab_brain.llm_runtime.probes import PROBES, ProbeOutcome, run_probe
from lab_brain.llm_runtime.provider import (
    ChatReply,
    OpenAICompatibleClient,
    ProviderError,
    ProviderFailure,
    is_loopback_url,
)
from lab_brain.llm_runtime.secrets import (
    SecretError,
    SecretRef,
    SecretStore,
    SecretUnavailable,
    WindowsCredentialStore,
    fingerprint,
    parse_secret_ref,
    redact,
)
from tests.fake_llm_provider import FakeProvider, _probe_answer
from tests.report_samples import full_report, leaves

KEY = "sk-test-unit-0123456789abcdefghijkl"


class _Canned:
    """A client that answers every probe with one fixed text."""

    def __init__(self, text: str) -> None:
        self.text = text

    def chat(self, model: str, prompt: str, **_: Any) -> ChatReply:
        return ChatReply(self.text, 1)


def _context(capability: Capability) -> dict[str, Any]:
    import json

    return dict(json.loads(PROBES[capability].prompt.split(contracts.CONTEXT_MARKER, 1)[1]))


# -- probes ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "capability",
    [
        Capability.ROLE_QUERY,
        Capability.ROLE_HYPOTHESIS,
        Capability.ROLE_SPECIALIST,
        Capability.ROLE_CRITIQUE,
    ],
)
def test_a_role_probe_is_passed_only_by_what_the_real_parser_accepts(capability):
    import json

    valid = json.dumps(_probe_answer(PROBES[capability].prompt, _context(capability)))
    assert run_probe(_Canned(valid), "m", capability).outcome is ProbeOutcome.PASSED  # type: ignore[arg-type]
    fenced = run_probe(_Canned(f"```json\n{valid}\n```"), "m", capability)  # type: ignore[arg-type]
    assert fenced.outcome is ProbeOutcome.FAILED and "typed role parser refused" in fenced.detail
    prose = run_probe(_Canned("Sure! Here are some thoughts."), "m", capability)  # type: ignore[arg-type]
    assert prose.outcome is ProbeOutcome.FAILED
    assert PROBES[capability].system in contracts.CONTRACTS.values()


def test_the_basic_probes_judge_by_code_and_never_run_it(tmp_path):
    marker = tmp_path / "executed"
    hostile = f"def add(a, b):\n    return a + b\nopen({str(marker)!r}, 'w').write('x')\n"
    assert run_probe(_Canned(hostile), "m", Capability.CODE).outcome is ProbeOutcome.PASSED  # type: ignore[arg-type]
    assert not marker.exists(), "a CODE probe answer was executed"
    assert run_probe(_Canned("print(1)"), "m", Capability.CODE).outcome is ProbeOutcome.FAILED  # type: ignore[arg-type]
    good = '{"probe": "structured", "value": 42}'
    assert run_probe(_Canned(good), "m", Capability.STRUCTURED_JSON).outcome is ProbeOutcome.PASSED  # type: ignore[arg-type]
    assert run_probe(_Canned("{"), "m", Capability.STRUCTURED_JSON).outcome is ProbeOutcome.FAILED  # type: ignore[arg-type]
    assert run_probe(_Canned("PONG!"), "m", Capability.CHAT).outcome is ProbeOutcome.PASSED  # type: ignore[arg-type]
    assert run_probe(_Canned("blue"), "m", Capability.VISION).outcome is ProbeOutcome.FAILED  # type: ignore[arg-type]


def test_probes_carry_no_project_data_and_use_the_real_role_templates():
    assert PROBES[Capability.ROLE_QUERY].prompt.startswith(QUERY_REWRITER.prompt.template)
    assert PROBES[Capability.ROLE_HYPOTHESIS].prompt.startswith(HYPOTHESIS_ENGINE.prompt.template)
    assert PROBES[Capability.ROLE_CRITIQUE].prompt.startswith(ADVERSARIAL_CRITIC.prompt.template)
    for probe in PROBES.values():
        assert "prj:" not in probe.prompt and "epi:" not in probe.prompt


# -- contracts and routes ---------------------------------------------------------------------------


def test_a_route_is_told_the_contract_of_the_role_it_serves():
    assert contracts.contract_for(PROBES[Capability.ROLE_QUERY].prompt) == contracts.QUERY_CONTRACT
    assert (
        contracts.contract_for(PROBES[Capability.ROLE_CRITIQUE].prompt)
        == contracts.CRITIQUE_CONTRACT
    )
    assert (
        contracts.contract_for(PROBES[Capability.ROLE_SPECIALIST].prompt)
        == contracts.SPECIALIST_CONTRACT
    )
    assert contracts.contract_for("free text") is None
    for contract in contracts.CONTRACTS.values():
        assert "no code fences" in contract


def test_the_role_table_shown_is_the_routers_own():
    router = ModelRouter(
        set(LogicalSlot)
        - {
            LogicalSlot.HYPOTHESIS,
            LogicalSlot.CRITIQUE,
            LogicalSlot.EXTRACTION,
            LogicalSlot.PLANNING,
            LogicalSlot.SUMMARISATION,
            LogicalSlot.RELATION,
        }
    )
    assert role_routes() == {role: router.route(role) for role in CognitiveRole}
    assert role_routes()[CognitiveRole.ADVERSARIAL_CRITIC] is LogicalSlot.REASONING_ADVERSARIAL
    assert critic_fallback() is LogicalSlot.REASONING_PRIMARY
    assert set(SLOT_REQUIREMENTS) == set(BINDABLE_SLOTS)
    assert LogicalSlot.EMBEDDING not in BINDABLE_SLOTS


# -- credentials --------------------------------------------------------------------------------------


def test_a_reference_is_never_the_credential_itself():
    assert parse_secret_ref("env:OPENAI_API_KEY") == SecretRef("env", "OPENAI_API_KEY")
    for bad in (KEY, f"env:{KEY}", "env:has space", "file:/etc/passwd", "Bearer abcdefghijklmnopq"):
        with pytest.raises(SecretError):
            parse_secret_ref(bad)


def test_a_fingerprint_says_which_key_without_any_of_it():
    printed = fingerprint(KEY, "salt" * 8)
    assert re.fullmatch(r"\*{4}[0-9a-f]{4}", printed)
    assert all(chunk not in KEY for chunk in re.findall(r"[0-9a-f]{3,}", printed))
    assert fingerprint(KEY, "other" * 8) != printed or fingerprint(KEY + "x", "salt" * 8) != printed
    assert redact(f"bad key {KEY} and sk-ant-another-0123456789ab", [KEY]).count("[redacted]") == 2


def test_a_typed_in_credential_fails_closed_without_an_os_store():
    store = SecretStore(environ={}, credentials=None)
    assert store.secure_store is None
    with pytest.raises(SecretUnavailable, match="no secure credential store"):
        store.store(KEY)
    with pytest.raises(SecretUnavailable, match="not set"):
        store.resolve(SecretRef("env", "MISSING"))


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Credential Manager")
def test_windows_credential_manager_round_trip():
    credentials = WindowsCredentialStore()
    target = f"lab-brain/llm/{uuid.uuid4()}"
    try:
        credentials.write(target, KEY)
        assert credentials.read(target) == KEY
    finally:
        credentials.delete(target)
    assert credentials.read(target) is None


# -- the transport --------------------------------------------------------------------------------


def test_the_transport_speaks_openai_compatible_http_and_redacts_what_comes_back():
    fake = FakeProvider(api_key=KEY).start()
    try:
        client = OpenAICompatibleClient(fake.base_url, KEY)
        assert client.list_models() == ["fake-chatty", "fake-critic", "fake-reasoner"]
        assert client.chat("fake-reasoner", "Reply with exactly one word: pong").text == "pong"
        wrong = OpenAICompatibleClient(fake.base_url, "sk-test-wrong-99999999999999999999")
        with pytest.raises(ProviderError) as refused:
            wrong.list_models()
        assert refused.value.failure is ProviderFailure.AUTH_FAILED
        assert "sk-test-wrong" not in str(refused.value) and "[redacted]" in str(refused.value)
    finally:
        fake.stop()
    with pytest.raises(ProviderError) as down:
        OpenAICompatibleClient(fake.base_url, KEY, timeout=2).list_models()
    assert down.value.failure is ProviderFailure.UNREACHABLE
    assert is_loopback_url("http://127.0.0.1:1/v1") and is_loopback_url("http://[::1]:9/v1")
    assert not is_loopback_url("http://127.0.0.1.nip.io/v1")


# -- language -------------------------------------------------------------------------------------


def test_every_interface_message_exists_in_every_locale_with_the_same_placeholders():
    import string

    import lab_brain.interfaces.web.settings_pages  # noqa: F401 - registers its messages

    for key in keys():
        texts = templates(key)
        assert len(texts) == len(LOCALES) and all(t.strip() for t in texts), key
        fields = [{f for _, f, _, _ in string.Formatter().parse(t) if f} for t in texts]
        assert all(f == fields[0] for f in fields), (key, fields)


def test_the_report_keeps_every_stored_value_in_any_interface_language():
    report = full_report()
    english = pages.report_html(report)
    chinese = pages.report_html(report, locale="zh-TW")
    assert english != chinese
    assert "Competing hypotheses" in english and "競爭假說" in chinese
    shown = " ".join(
        html.unescape(
            re.sub(r"<[^>]+>", " ", re.sub(r"</?(?:code|strong|span|a)\b[^>]*>", "", chinese))
        ).split()
    )
    for leaf in leaves(report):
        if isinstance(leaf, str):
            assert " ".join(leaf.replace("`", "").replace("**", "").split()) in shown, leaf
