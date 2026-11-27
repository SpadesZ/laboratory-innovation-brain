"""A model call's deadline, and what missing it is called -- against real sockets.

    TIMEOUT       the endpoint accepted the call and its answer did not arrive within the
                  client's timeout (for a model call, the deployment's inference deadline):
                  reachable, and too slow for the deadline
    UNREACHABLE   no connection could be made at all

The deadline's propagation to probes, readiness and the active runtime needs the registry and is
proven in `tests/integration/test_inference_deadline_postgres.py`; the web workspace's in
`tests/e2e/test_web_debate_retry_postgres.py`.
"""

from __future__ import annotations

import argparse
import socket
import threading
import time
from collections.abc import Iterator

import pytest

from lab_brain.interfaces.cli import _seconds
from lab_brain.llm_runtime.capabilities import Capability
from lab_brain.llm_runtime.probes import run_probe
from lab_brain.llm_runtime.provider import OpenAICompatibleClient, ProviderError, ProviderFailure
from lab_brain.llm_runtime.runtime import DEFAULT_INFERENCE_DEADLINE_S, checked_deadline

KEY = "sk-test-deadline-0123456789abcdefABCDEF"


@pytest.fixture
def silent_endpoint() -> Iterator[str]:
    """Accepts every connection and reads the request -- and never answers: a model still busy."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    server.settimeout(0.2)
    held: list[socket.socket] = []
    stop = threading.Event()

    def serve() -> None:
        while not stop.is_set():
            try:
                conn, _ = server.accept()
            except OSError:
                continue
            conn.recv(65536)
            held.append(conn)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.getsockname()[1]}/v1"
    stop.set()
    thread.join(2)
    for conn in held:
        conn.close()
    server.close()


def _refusal(call: object) -> ProviderError:
    with pytest.raises(ProviderError) as refused:
        call()  # type: ignore[operator]
    return refused.value


def test_an_answer_that_does_not_arrive_in_time_is_a_timeout(silent_endpoint: str):
    client = OpenAICompatibleClient(silent_endpoint, KEY, timeout=1.0)
    for call in (client.list_models, lambda: client.chat("m", "a research prompt")):
        started = time.monotonic()
        error = _refusal(call)
        waited = time.monotonic() - started
        assert error.failure is ProviderFailure.TIMEOUT
        assert error.detail == "the endpoint accepted the call and did not answer within 1 s"
        assert 0.9 <= waited < 5.0, waited
        assert KEY not in str(error)
    probe = run_probe(client, "m", Capability.CHAT)
    assert probe.outcome.value == "ERROR" and "TIMEOUT" in probe.detail


def test_an_endpoint_that_takes_no_connection_is_unreachable():
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()  # nothing listens there now
    client = OpenAICompatibleClient(f"http://127.0.0.1:{port}/v1", KEY, timeout=5.0)
    for call in (client.list_models, lambda: client.chat("m", "a research prompt")):
        error = _refusal(call)
        assert error.failure is ProviderFailure.UNREACHABLE, error
        assert "did not answer within" not in error.detail


def test_the_deadline_is_a_number_of_seconds_within_bounds():
    assert DEFAULT_INFERENCE_DEADLINE_S == 180.0
    assert checked_deadline(1200) == 1200.0
    for bad in (0, 0.5, -3, 86_401):
        with pytest.raises(ValueError):
            checked_deadline(bad)
    assert _seconds("1200") == 1200.0
    for bad in ("0", "abc", "100000"):
        with pytest.raises(argparse.ArgumentTypeError):
            _seconds(bad)
