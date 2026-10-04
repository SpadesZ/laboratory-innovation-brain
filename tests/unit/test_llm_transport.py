"""The model-provider transport, adversarially: where a credential and a research prompt may travel.

Two rules of `llm_runtime.provider`, each checked against real sockets:

    plaintext   http:// only to this machine; any other host is https://. A call to a remote
                http:// endpoint is refused before a connection is opened -- nothing is sent.
    redirects   never followed, the same-origin ones included. A redirecting endpoint -- https://
                down to http://, to another host, or to another path of itself -- gets its one
                request; the target gets nothing: no Authorization header, no prompt, no evidence.

The four paths a call takes are all exercised: discovery and health (`list_models`), capability
probes (`run_probe`), and research inference (`RouteCompletion`, what `ScientificLLM` calls). The
settings service and an active runtime are driven end to end in
`tests/e2e/test_web_llm_transport_postgres.py`.
"""

from __future__ import annotations

import os
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from lab_brain.cognition.llm import ModelSlot
from lab_brain.core.models.inference import LogicalSlot
from lab_brain.llm_runtime.capabilities import Capability
from lab_brain.llm_runtime.probes import run_probe
from lab_brain.llm_runtime.provider import (
    OpenAICompatibleClient,
    ProviderError,
    ProviderFailure,
    plaintext_refusal,
)
from lab_brain.llm_runtime.runtime import RouteCompletion, _Route
from tests.transport_endpoints import REDIRECT_BODY, TLS, Endpoint, make_tls

KEY = "sk-test-transport-0123456789abcdefABCDEF"
#: What a research call carries: a prompt with the project's evidence in it.
EVIDENCE = "EVIDENCE-7f3a: pad P4 read 41 ohm after the anneal; the oxide was not stripped"
REDIRECTS = (301, 302, 303, 307, 308)


@pytest.fixture(scope="session")
def tls(tmp_path_factory: pytest.TempPathFactory) -> TLS:
    made = make_tls(tmp_path_factory.mktemp("tls"))
    if made is None:
        if os.environ.get("CI"):
            pytest.fail("CI must run the TLS transport tests: openssl is missing")
        pytest.skip("openssl is needed to make the throwaway test certificate")
    return made


@pytest.fixture
def endpoints(tls: TLS, monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., Endpoint]]:
    """Start endpoints; the client trusts the test CA the way it trusts any extra root."""
    monkeypatch.setenv("SSL_CERT_FILE", str(tls.ca))
    started: list[Endpoint] = []

    def start(*, secure: bool = True, **options: object) -> Endpoint:
        endpoint = Endpoint(tls=tls if secure else None, **options).start()  # type: ignore[arg-type]
        started.append(endpoint)
        return endpoint

    yield start
    for endpoint in started:
        endpoint.stop()


def _refusal(call: Callable[[], object]) -> ProviderError:
    with pytest.raises(ProviderError) as refused:
        call()
    return refused.value


def _said(error: ProviderError) -> str:
    return f"{error} {error.detail}"


# -- plaintext ------------------------------------------------------------------------------------


def test_plaintext_goes_only_to_this_machine():
    for allowed in (
        "https://api.openai.com/v1",
        "https://10.0.0.5:8443/v1",
        "http://127.0.0.1:11434/v1",
        "http://127.8.9.10:8000/v1",
        "http://localhost:8000/v1",
        "http://[::1]:8000/v1",
        "http://host.docker.internal:11434/v1",  # the transport's default: the Docker host
    ):
        assert plaintext_refusal(allowed) is None, allowed
    for refused in (
        "http://api.openai.com/v1",
        "http://models.example.org/v1",
        "http://10.0.0.5:11434/v1",
        "http://192.168.1.20:8000/v1",
        "http://127.0.0.1.nip.io/v1",
        "http://localhost.evil.test/v1",
        "http://host.docker.internal.evil.test/v1",
        "http://[::ffff:203.0.113.9]/v1",
        "ftp://files.example.org/v1",
        "models.example.org/v1",
    ):
        assert plaintext_refusal(refused) is not None, refused
    # The Docker host is this machine only where the deployment says so.
    assert plaintext_refusal("http://host.docker.internal:11434/v1", frozenset()) is not None
    # The reason names a scheme and a host, never the rest of the address.
    reason = plaintext_refusal("http://user:hunter2@models.example.org/v1/secret-path")
    assert reason is not None and "hunter2" not in reason and "secret-path" not in reason


def test_nothing_is_sent_to_a_remote_plaintext_endpoint(monkeypatch: pytest.MonkeyPatch):
    opened: list[str] = []

    def refuse_to_open(self: object, request: object, *args: object, **kw: object) -> object:
        opened.append(getattr(request, "full_url", str(request)))
        raise AssertionError("a connection was opened")

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", refuse_to_open)
    client = OpenAICompatibleClient("http://models.example.org/v1", KEY)
    for call in (lambda: client.list_models(), lambda: client.chat("m", EVIDENCE)):
        error = _refusal(call)
        assert error.failure is ProviderFailure.PROTOCOL_ERROR
        assert "neither https:// nor this machine" in error.detail
        assert KEY not in _said(error) and EVIDENCE not in _said(error)
    probe = run_probe(client, "m", Capability.CHAT)
    assert probe.outcome.value != "PASSED" and "neither https://" in probe.detail
    assert opened == [], "not even a connection"


# -- https, and redirects -------------------------------------------------------------------------


def test_https_providers_still_work(endpoints: Callable[..., Endpoint]):
    provider = endpoints()
    client = OpenAICompatibleClient(provider.origin + "/v1", KEY)
    assert client.list_models() == ["m"]
    assert client.chat("m", "Reply with exactly one word: pong").text == "ok"
    assert [s.authorization for s in provider.seen] == [f"Bearer {KEY}"] * 2


def test_an_https_to_http_redirect_reaches_nothing(endpoints: Callable[..., Endpoint]):
    # The plain target answers as a provider: had the redirect been followed, the call would
    # have SUCCEEDED -- with the credential sent in clear.
    target = endpoints(secure=False)
    for status in REDIRECTS:
        origin = endpoints(redirect=(status, target.origin + "{path}"))
        client = OpenAICompatibleClient(origin.origin + "/v1", KEY)
        for call in (client.list_models, lambda c=client: c.chat("m", EVIDENCE)):
            error = _refusal(call)
            assert error.failure is ProviderFailure.PROTOCOL_ERROR
            assert f"HTTP {status}: the endpoint redirected the call" in error.detail
            said = _said(error)
            assert KEY not in said and EVIDENCE not in said
            assert target.origin not in said and REDIRECT_BODY not in said
    assert target.seen == [], "the http:// target received no request at all"


def test_a_redirect_to_another_host_reaches_nothing(endpoints: Callable[..., Endpoint]):
    elsewhere = endpoints(host="localhost")  # https://, a different origin, answering normally
    for status in REDIRECTS:
        origin = endpoints(redirect=(status, elsewhere.origin + "{path}"))
        client = OpenAICompatibleClient(origin.origin + "/v1", KEY)
        assert "redirected" in _refusal(client.list_models).detail
        assert "redirected" in _refusal(lambda c=client: c.chat("m", EVIDENCE)).detail
    assert elsewhere.seen == [], "no Authorization header, no prompt reached the other host"


def test_a_redirect_never_carries_the_research_prompt(endpoints: Callable[..., Endpoint]):
    target = endpoints(host="localhost")
    origin = endpoints(redirect=(307, target.origin + "{path}"))  # 307/308 would keep the body
    slot = ModelSlot(LogicalSlot.REASONING_PRIMARY, "m", "route-fingerprint", provider="x")
    complete = RouteCompletion(
        {slot.logical_slot: _Route(OpenAICompatibleClient(origin.origin + "/v1", KEY), "m")}
    )
    error = _refusal(lambda: complete(f"Question: why?\n\nCONTEXT:\n{EVIDENCE}", slot))
    assert EVIDENCE not in _said(error) and KEY not in _said(error)
    assert target.seen == []
    # The endpoint the connection names did receive the call -- that is what it is for.
    assert len(origin.seen) == 1 and EVIDENCE.encode() in origin.seen[0].body


def test_a_same_origin_redirect_is_refused_too(endpoints: Callable[..., Endpoint]):
    """The policy is one rule: no redirect is followed. A same-origin https:// one would be safe,
    but deciding which are safe is a judgement the transport does not make."""
    origin = endpoints()
    origin.redirect = (308, origin.origin + "/v2{path}")
    client = OpenAICompatibleClient(origin.origin + "/v1", KEY)
    assert "HTTP 308: the endpoint redirected" in _refusal(client.list_models).detail
    assert [s.path for s in origin.seen] == ["/v1/models"], "/v2/... was never requested"


def test_a_capability_probe_is_not_redirected(endpoints: Callable[..., Endpoint]):
    target = endpoints(secure=False)
    origin = endpoints(redirect=(302, target.origin + "{path}"))
    client = OpenAICompatibleClient(origin.origin + "/v1", KEY)
    for capability in (Capability.CHAT, Capability.STRUCTURED_JSON):
        result = run_probe(client, "m", capability)
        assert result.outcome.value != "PASSED"
        assert "redirected" in result.detail and KEY not in result.detail
    assert target.seen == []


def test_the_test_certificate_is_trusted_only_where_the_test_says_so(
    tls: TLS, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The client verifies certificates as it always does: without the test CA, the same endpoint
    is refused -- so the tests above prove the policy over real, verified TLS."""
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    endpoint = Endpoint(tls=tls).start()
    try:
        error = _refusal(OpenAICompatibleClient(endpoint.origin + "/v1", KEY).list_models)
    finally:
        endpoint.stop()
    assert error.failure is ProviderFailure.UNREACHABLE and "CERTIFICATE_VERIFY_FAILED" in str(
        error
    )
