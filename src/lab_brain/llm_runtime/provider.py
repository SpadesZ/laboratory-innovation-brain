"""An OpenAI-compatible chat endpoint (`/models`, `/chat/completions`), with the standard library.

OpenAI, OpenRouter, vLLM, LM Studio and Ollama's `/v1` all speak this protocol, so one client
covers the hosted and the local cases. It is a TRANSPORT and nothing more: it is called by the
capability probes (fixed payloads, no project data) and by a runtime's `Completion`, which
`ScientificLLM` reaches only after the budget and egress gates. It never builds a prompt, reads a
context or interprets an answer.

Every message that comes back from a provider -- an error body above all, which some providers
fill with the key they were sent -- is REDACTED of the credential before it is raised, so no
refusal, health record or page can carry it.
"""

from __future__ import annotations

import base64
import ipaddress
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
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
#: containerised workspace, so it counts as LOCAL only where the deployment says so (see
#: `is_this_machine_url`); it is always reached directly, never through a proxy.
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


class OpenAICompatibleClient:
    def __init__(self, base_url: str, api_key: str | None, *, timeout: float = 120.0) -> None:
        self._base = base_url.rstrip("/")
        self._key = api_key
        self._timeout = timeout
        # This machine is reached directly, never through an environment proxy: a proxy would
        # carry a LOCAL call off the machine.
        direct = is_this_machine_url(base_url, frozenset({DOCKER_HOST_GATEWAY}))
        handlers: list[urllib.request.BaseHandler] = (
            [urllib.request.ProxyHandler({})] if direct else []
        )
        self._opener = urllib.request.build_opener(*handlers)

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
    "is_loopback_url",
    "is_this_machine_url",
]
