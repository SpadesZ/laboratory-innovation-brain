"""The HTTP transport's mapping of GitHub responses onto the transport vocabulary -- offline.

`urlopen` is replaced by a stub for every test here, so no request leaves this process; what is
checked is the translation (status codes, rate-limit headers, base64 content, URL errors), which is
the part a live call cannot be relied on to exercise. The live half is
`tests/integration/test_github_network.py`, marked `network` and deselected by default.
"""

from __future__ import annotations

import base64
import email.message
import io
import json
import urllib.error

import pytest

from lab_brain.tool_providers.github import transport as wire
from lab_brain.tool_providers.github.transport import HttpGitHubTransport, TransportError


class _Response(io.BytesIO):
    def __enter__(self):  # type: ignore[no-untyped-def]
        return self

    def __exit__(self, *exc):  # type: ignore[no-untyped-def]
        return False


def _stub(monkeypatch, handler):  # type: ignore[no-untyped-def]
    seen: list[object] = []

    def fake(request, timeout):  # type: ignore[no-untyped-def]
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(wire.urllib.request, "urlopen", fake)
    return seen


def _http_error(code: int, **headers: str) -> urllib.error.HTTPError:
    message = email.message.Message()
    for key, value in headers.items():
        message[key] = value
    return urllib.error.HTTPError("https://api.github.com/x", code, "err", message, None)


def test_a_file_is_read_at_the_commit_and_the_token_rides_only_in_the_header(monkeypatch):
    body = {"encoding": "base64", "content": base64.b64encode(b"print(1)\n").decode()}
    seen = _stub(monkeypatch, lambda _r: _Response(json.dumps(body).encode()))
    data = HttpGitHubTransport().read_file("o", "r", "a" * 40, "src/x.py", token="t0k")
    assert data == b"print(1)\n"
    (request,) = seen
    assert "ref=" + "a" * 40 in request.full_url
    assert "t0k" not in request.full_url
    assert request.get_header("Authorization") == "Bearer t0k"


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (_http_error(404), wire.NOT_FOUND),
        (_http_error(401), wire.UNAUTHORIZED),
        (
            _http_error(403, **{"X-RateLimit-Remaining": "0", "Retry-After": "30"}),
            wire.RATE_LIMITED,
        ),
        (_http_error(429), wire.RATE_LIMITED),
        (_http_error(451), wire.GONE),
        (urllib.error.URLError("no route"), wire.NETWORK),
    ],
)
def test_responses_map_to_the_transport_vocabulary(monkeypatch, error, kind):  # type: ignore[no-untyped-def]
    def raise_(_r):  # type: ignore[no-untyped-def]
        raise error

    _stub(monkeypatch, raise_)
    with pytest.raises(TransportError) as failed:
        HttpGitHubTransport().repository("o", "r", token=None)
    assert failed.value.kind == kind
    if (
        kind == wire.RATE_LIMITED
        and isinstance(error, urllib.error.HTTPError)
        and error.code == 403
    ):
        assert failed.value.retry_after_s == 30
