"""An OpenAI-compatible chat endpoint (`/models`, `/chat/completions`), with the standard library.

OpenAI, OpenRouter, vLLM, LM Studio and Ollama's `/v1` all speak this protocol, so one client
covers the hosted and the local cases. It is a TRANSPORT and nothing more: it is called by the
capability probes (fixed payloads, no project data) and by a runtime's `Completion`, which
`ScientificLLM` reaches only after the budget and egress gates. It never builds a prompt, reads a
context or interprets an answer.

Every message that comes back from a provider -- an error body above all, which some providers
fill with the key they were sent -- is REDACTED of the credential before it is raised, so no
refusal, health record or page can carry it.

A call carries the credential (`Authorization: Bearer ...`) and, for a research step, the prompt
with its evidence. So the transport itself refuses two ways those could travel further than the
endpoint the connection names, whoever built the client and whatever row it was built from:

    plaintext       http:// only to THIS machine (`plaintext_refusal`); any other host is https://.
                    Refused before a connection is opened: nothing is sent.
    redirects       never followed (`_NoRedirects`). urllib would re-send the request, Authorization
                    header included, to whatever the answer names -- another host, or https://
                    down to http://. A 3xx ends the call; neither its body nor its target is kept.

"This machine" is loopback, plus exactly the hosts the DEPLOYMENT declares (`local_hosts`: the
container deployment's `--host-gateway host.docker.internal`). Nothing here infers locality from a
host name: a function or client given no declaration treats `host.docker.internal` like any other
remote host. The declaration is carried explicitly from the process that knows it -- the web
workspace, `local_setup` -- through `LLMSettings` and `load_active_runtime` to the client built for
each call, so the last boundary before the network decides with it.
"""

from __future__ import annotations

import base64
import ipaddress
import json
import time
import urllib.error
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from http.client import HTTPMessage
from typing import IO, Any
from urllib.parse import urlsplit

from lab_brain.llm_runtime.secrets import redact

#: Bytes of a provider's error body kept, after redaction, for the operator to read.
_DETAIL = 240


class ProviderFailure(StrEnum):
    AUTH_FAILED = "AUTH_FAILED"
    UNREACHABLE = "UNREACHABLE"
    PROTOCOL_ERROR = "PROTOCOL_ERROR"


class ProviderError(RuntimeError):
    def __init__(self, failure: ProviderFailure, detail: str) -> None:
        super().__init__(f"{failure.value}: {detail}")
        self.failure = failure
        self.detail = detail


@dataclass(frozen=True)
class ChatReply:
    text: str
    latency_ms: int


#: The name Docker gives a container for the machine it runs on. It is this machine only for a
#: containerised workspace, so it counts as this machine only where the deployment declares it
#: (`local_hosts`) -- never because of the name. Declared, it is reached directly (no proxy).
DOCKER_HOST_GATEWAY = "host.docker.internal"


def is_loopback_url(url: str) -> bool:
    host = (urlsplit(url).hostname or "").strip("[]").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def is_this_machine_url(url: str, local_hosts: frozenset[str] = frozenset()) -> bool:
    """Loopback, or a host name the deployment declared to be this machine (`local_hosts`)."""
    return is_loopback_url(url) or (urlsplit(url).hostname or "").lower() in local_hosts


def plaintext_refusal(url: str, local_hosts: frozenset[str]) -> str | None:
    """Why a model-provider call may not go to `url`, or None when it may.

    https:// may go anywhere. Plaintext http:// may go only where there is no network to cross:
    this machine -- loopback, or a host the deployment declared to be this machine (`local_hosts`,
    which every caller must pass: there is no default to fall back on). So a LOCAL model may be
    plain http://, and an EXTERNAL one on any other host must be https:// -- wherever its
    credential came from. The reason names the scheme and host only: never the rest of the URL."""
    parts = urlsplit(url)
    scheme, host = parts.scheme.lower(), (parts.hostname or "")
    if host and scheme == "https":
        return None
    if host and scheme == "http" and is_this_machine_url(url, local_hosts):
        return None
    return (
        f"{scheme or '?'}://{host or '?'} is neither https:// nor this machine: a model-provider "
        "call carries the credential and the research prompt, so a service on another host must "
        "be reached over https://"
    )


def endpoint_refusal(url: str, reach: str, local_hosts: frozenset[str]) -> str | None:
    """Why a connection's endpoint may not be USED under this deployment's declaration, or None.

    The two rules a stored row must still meet at the moment of use, whatever was true when it was
    written: a LOCAL endpoint is this machine (LOCAL skips the egress gate, so a LOCAL row naming a
    host this deployment did not declare would carry research off the machine unguarded), and
    every endpoint passes `plaintext_refusal`."""
    if reach == "LOCAL" and not is_this_machine_url(url, local_hosts):
        host = urlsplit(url).hostname or "?"
        return (
            f"{host} is declared LOCAL but is not this machine in this deployment: loopback "
            "is, and another host name only where the deployment declares it"
        )
    return plaintext_refusal(url, local_hosts)


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """Every redirect is refused, the same-origin ones included: one policy, no judgement of which
    target is safe. urllib would follow a 3xx with the original headers -- the credential among
    them -- to any host and any scheme. Declining here makes urllib raise the 3xx as an HTTPError,
    which `_request` turns into a refusal."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        return None


class OpenAICompatibleClient:
    """`local_hosts`: the hosts the deployment declared to be this machine, besides loopback. A
    client built without them -- by any caller -- treats every other host as remote."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        *,
        timeout: float = 120.0,
        local_hosts: Iterable[str] = (),
    ) -> None:
        self._base = base_url.rstrip("/")
        self._key = api_key
        self._timeout = timeout
        declared = frozenset(h.lower() for h in local_hosts)
        #: Not None: this endpoint is refused by the transport rule, and nothing is ever sent to it.
        self._refused = plaintext_refusal(base_url, declared)
        # This machine is reached directly, never through an environment proxy: a proxy would
        # carry a LOCAL call off the machine.
        direct = is_this_machine_url(base_url, declared)
        handlers: list[urllib.request.BaseHandler] = (
            [urllib.request.ProxyHandler({})] if direct else []
        )
        self._opener = urllib.request.build_opener(*handlers, _NoRedirects())

    def list_models(self) -> list[str]:
        body = self._request("GET", "/models", None)
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, list):
            raise ProviderError(ProviderFailure.PROTOCOL_ERROR, "the model list has no data array")
        names = sorted(
            {str(item["id"]) for item in data if isinstance(item, dict) and item.get("id")}
        )
        return names

    def chat(
        self,
        model: str,
        prompt: str,
        *,
        system: str | None = None,
        image_png: bytes | None = None,
    ) -> ChatReply:
        content: Any = prompt
        if image_png is not None:
            encoded = base64.b64encode(image_png).decode("ascii")
            content = [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
            ]
        messages: list[dict[str, Any]] = []
        if system is not None:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": content})
        started = time.monotonic()
        body = self._request(
            "POST", "/chat/completions", {"model": model, "messages": messages, "temperature": 0}
        )
        latency = int((time.monotonic() - started) * 1000)
        try:
            message = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(
                ProviderFailure.PROTOCOL_ERROR, "the reply carries no choices[0].message.content"
            ) from exc
        if isinstance(message, list):  # content parts
            message = "".join(str(p.get("text", "")) for p in message if isinstance(p, dict))
        if not isinstance(message, str):
            raise ProviderError(ProviderFailure.PROTOCOL_ERROR, "the reply content is not text")
        return ChatReply(text=message, latency_ms=latency)

    def _request(self, method: str, path: str, payload: dict[str, Any] | None) -> Any:
        if self._refused is not None:
            # Before a request is even built: no credential, no payload, no connection.
            raise ProviderError(ProviderFailure.PROTOCOL_ERROR, self._refused)
        headers = {"Accept": "application/json"}
        if self._key:
            headers["Authorization"] = f"Bearer {self._key}"
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self._base + path, data=data, headers=headers, method=method
        )
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                # An authentication refusal is ABOUT the credential, and providers quote it back --
                # often masked ("sk-proj-abc****wxyz"), a shape no redaction can recognise. Its body
                # is never read, kept or shown: the status says what happened.
                raise ProviderError(
                    ProviderFailure.AUTH_FAILED,
                    f"HTTP {exc.code}: the provider refused the credential",
                ) from None
            if 300 <= exc.code < 400:
                # Not followed (`_NoRedirects`). Its body and its Location are the redirecting
                # server's words, so neither is read into the record.
                raise ProviderError(
                    ProviderFailure.PROTOCOL_ERROR,
                    f"HTTP {exc.code}: the endpoint redirected the call, and a model-provider call "
                    "never follows a redirect (it would carry the credential and the request to "
                    "another address)",
                ) from None
            detail = self._clean(exc.read().decode("utf-8", "replace"))
            raise ProviderError(
                ProviderFailure.PROTOCOL_ERROR, f"HTTP {exc.code}: {detail}"
            ) from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise ProviderError(ProviderFailure.UNREACHABLE, self._clean(str(reason))) from None
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise ProviderError(
                ProviderFailure.PROTOCOL_ERROR, "the endpoint did not answer with JSON"
            ) from None

    def _clean(self, text: str) -> str:
        return redact(" ".join(text.split()), [self._key or ""])[:_DETAIL]


__all__ = [
    "DOCKER_HOST_GATEWAY",
    "ChatReply",
    "OpenAICompatibleClient",
    "ProviderError",
    "ProviderFailure",
    "endpoint_refusal",
    "is_loopback_url",
    "is_this_machine_url",
    "plaintext_refusal",
]
