"""The model-provider transport, adversarially: where a credential and a research prompt may travel.

Two rules of `llm_runtime.provider`, each checked against real sockets:

    plaintext   http:// only to this machine; any other host is https://. A call to a remote
                http:// endpoint is refused before a connection is opened -- nothing is sent.
    redirects   never followed, the same-origin ones included. A redirecting endpoint -- https://
                down to http://, to another host, or to another path of itself -- gets its one
                request; the target gets nothing: no Authorization header, no prompt, no evidence.

"This machine" is loopback plus exactly the hosts a deployment DECLARES. The Docker host
(`host.docker.internal`) is never trusted for its name: undeclared, it is a remote host like any
other -- for the predicate, for a client built directly, and for a LOCAL row at the moment of use.

The four paths a call takes are all exercised: discovery and health (`list_models`), capability
probes (`run_probe`), and research inference (`RouteCompletion`, what `ScientificLLM` calls). The
settings service and an active runtime are driven end to end in
`tests/e2e/test_web_llm_transport_postgres.py`.
"""

from __future__ import annotations

import os
import socket
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
    endpoint_refusal,
    plaintext_refusal,
)
from lab_brain.llm_runtime.runtime import RouteCompletion, _Route
from tests.transport_endpoints import REDIRECT_BODY, TLS, Endpoint, make_tls

KEY = "sk-test-transport-0123456789abcdefABCDEF"
#: What a research call carries: a prompt with the project's evidence in it.
EVIDENCE = "EVIDENCE-7f3a: pad P4 read 41 ohm after the anneal; the oxide was not stripped"
REDIRECTS = (301, 302, 303, 307, 308)
GATEWAY = "host.docker.internal"
#: No declaration: loopback is this machine, nothing else is.
UNDECLARED: frozenset[str] = frozenset()
#: The container deployment's declaration (`--host-gateway host.docker.internal`).
DECLARED = frozenset({GATEWAY})


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


@pytest.fixture
def docker_host_resolves_here(monkeypatch: pytest.MonkeyPatch) -> None:
    """`host.docker.internal` resolves to 127.0.0.1, as Docker makes it resolve to the machine a
    container runs on -- so a test can reach an endpoint by that name. Name resolution only: what
    the workspace may SEND there is still decided by the declaration alone."""
    real = socket.getaddrinfo

    def resolve(host: object, *args: object, **kwargs: object) -> object:
        return real("127.0.0.1" if host == GATEWAY else host, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(socket, "getaddrinfo", resolve)


@pytest.fixture
def opened(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every URL a client opens (and the call still goes through)."""
    seen: list[str] = []
    original = urllib.request.OpenerDirector.open

    def recording(self, request, *args, **kwargs):  # type: ignore[no-untyped-def]
        seen.append(getattr(request, "full_url", str(request)))
        return original(self, request, *args, **kwargs)

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", recording)
    return seen


# -- plaintext ------------------------------------------------------------------------------------


def test_plaintext_goes_only_to_this_machine():
    for allowed in (
        "https://api.openai.com/v1",
        "https://10.0.0.5:8443/v1",
        "http://127.0.0.1:11434/v1",
        "http://127.8.9.10:8000/v1",
        "http://localhost:8000/v1",
        "http://[::1]:8000/v1",
    ):
        assert plaintext_refusal(allowed, UNDECLARED) is None, allowed
        assert plaintext_refusal(allowed, DECLARED) is None, allowed
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
        assert plaintext_refusal(refused, UNDECLARED) is not None, refused
        assert plaintext_refusal(refused, DECLARED) is not None, refused
    # The reason names a scheme and a host, never the rest of the address.
    reason = plaintext_refusal("http://user:hunter2@models.example.org/v1/secret-path", DECLARED)
    assert reason is not None and "hunter2" not in reason and "secret-path" not in reason


def test_the_docker_host_is_this_machine_only_where_the_deployment_declares_it():
    plain, tls = f"http://{GATEWAY}:11434/v1", f"https://{GATEWAY}:11434/v1"
    # Undeclared: a remote host like any other -- for plaintext, and for LOCAL even over https.
    assert plaintext_refusal(plain, UNDECLARED) is not None
    for reach in ("LOCAL", "EXTERNAL"):
        assert endpoint_refusal(plain, reach, UNDECLARED) is not None, reach
    assert "declared LOCAL but is not this machine" in str(
        endpoint_refusal(tls, "LOCAL", UNDECLARED)
    )
    assert endpoint_refusal(tls, "EXTERNAL", UNDECLARED) is None  # https:// goes anywhere
    # Declared: this machine.
    for reach in ("LOCAL", "EXTERNAL"):
        assert endpoint_refusal(plain, reach, DECLARED) is None, reach
    # Loopback needs no declaration -- including an EXTERNAL local gateway over plain http://.
    for reach in ("LOCAL", "EXTERNAL"):
        assert endpoint_refusal("http://127.0.0.1:4000/v1", reach, UNDECLARED) is None, reach
    # A declaration names one host, not its look-alikes, and makes no remote host local.
    for url in (f"http://{GATEWAY}.evil.test/v1", "http://models.example.org/v1"):
        assert endpoint_refusal(url, "EXTERNAL", DECLARED) is not None, url
        assert endpoint_refusal(url, "LOCAL", DECLARED) is not None, url


def test_a_client_built_without_a_declaration_never_trusts_the_docker_host(
    opened: list[str], docker_host_resolves_here: None
):
    endpoint = Endpoint().start()  # plain http://, answering as a provider
    try:
        url = f"http://{GATEWAY}:{endpoint.port}/v1"
        # Built directly, with no declaration: refused before a connection, though it would answer.
        bare = OpenAICompatibleClient(url, KEY)
        for call in (bare.list_models, lambda: bare.chat("m", EVIDENCE)):
            error = _refusal(call)
            assert error.failure is ProviderFailure.PROTOCOL_ERROR
            assert "neither https:// nor this machine" in error.detail
        assert opened == [] and endpoint.seen == []
        # Given the deployment's declaration, the same address is this machine and is reached.
        declared = OpenAICompatibleClient(url, KEY, local_hosts=(GATEWAY,))
        assert declared.list_models() == ["m"]
        assert declared.chat("m", "Reply with exactly one word: pong").text == "ok"
        assert [s.authorization for s in endpoint.seen] == [f"Bearer {KEY}"] * 2
    finally:
        endpoint.stop()


def test_loopback_plain_http_needs_no_declaration():
    """The local model, and an EXTERNAL local gateway on loopback: plain http:// as before."""
    endpoint = Endpoint().start()
    try:
        client = OpenAICompatibleClient(endpoint.origin + "/v1", KEY)
        assert client.list_models() == ["m"]
    finally:
        endpoint.stop()


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
