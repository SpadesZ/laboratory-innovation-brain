"""An OpenAI-compatible model endpoint on 127.0.0.1, for tests: a provider the real transport talks
to over HTTP.

It is a TEST DOUBLE for a language-model provider, and nothing in the system under test knows it
is one: the workspace reaches it through the same `OpenAICompatibleClient`, over a real socket,
with a real Bearer credential, exactly as it would reach a hosted model. Its models:

    fake-reasoner   passes every probe; answers research prompts in the shapes the typed role
                    parsers read, by reading the SiPh pack's mechanism catalog (the same content the
                    local catalog reasoner has -- so a debate over it is comparable), and records
                    that it did
    fake-critic     the same, under another model id: a distinct model route for the Critic
    fake-chatty     chats, and answers every JSON request in prose: it fails STRUCTURED_JSON and
                    every role probe, and so can never be bound to a reasoning slot

A wrong or missing credential gets 401 with the key it was sent ECHOED in the error body, as some
providers do -- so a test can show the workspace never repeats it.

`redirect_to` (off by default) makes it answer EVERY request with a redirect there instead
(`redirect_status`, the request's path appended): a provider that moved, or one that tries to
send the call -- credential and prompt -- somewhere else. Its body carries `REDIRECT_BODY`, so a
test can show none of it is kept.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from lab_brain.cognition.catalog_reasoner import CatalogReasoner, reasoner_slots
from lab_brain.core.models.inference import LogicalSlot
from lab_brain.domains.silicon_photonics.product import mechanism_catalog

MODELS = ("fake-reasoner", "fake-critic", "fake-chatty")
REDIRECT_BODY = "moved: follow me to the new address"
_MARKER = "\n\nCONTEXT:\n"


@dataclass
class Call:
    model: str
    system: str | None
    prompt: str
    image: bool


@dataclass
class FakeProvider:
    api_key: str | None = None
    calls: list[Call] = field(default_factory=list)
    port: int = 0
    redirect_to: str | None = None
    redirect_status: int = 307
    redirected: int = 0
    _server: ThreadingHTTPServer | None = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/v1"

    def start(self) -> FakeProvider:
        provider = self
        reasoner = CatalogReasoner(mechanism_catalog())
        slot = reasoner_slots(mechanism_catalog(), (LogicalSlot.REASONING_PRIMARY,))[0]

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                return

            def _authorized(self) -> bool:
                if provider.api_key is None:
                    return True
                sent = self.headers.get("Authorization", "")
                if sent == f"Bearer {provider.api_key}":
                    return True
                self._send(401, {"error": {"message": f"Incorrect API key provided: {sent[7:]}"}})
                return False

            def _send(self, status: int, body: Any) -> None:
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _moved(self) -> bool:
                if provider.redirect_to is None:
                    return False
                provider.redirected += 1
                raw = REDIRECT_BODY.encode()
                self.send_response(provider.redirect_status)
                self.send_header("Location", provider.redirect_to + self.path)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return True

            def do_GET(self) -> None:
                if self._moved() or not self._authorized():
                    return
                if self.path == "/v1/models":
                    self._send(200, {"object": "list", "data": [{"id": m} for m in MODELS]})
                else:
                    self._send(404, {"error": {"message": "not found"}})

            def do_POST(self) -> None:
                if self._moved() or not self._authorized():
                    return
                if self.path != "/v1/chat/completions":
                    self._send(404, {"error": {"message": "not found"}})
                    return
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                model = body["model"]
                system = next(
                    (m["content"] for m in body["messages"] if m["role"] == "system"), None
                )
                user = next(m["content"] for m in body["messages"] if m["role"] == "user")
                image = isinstance(user, list)
                prompt = user[0]["text"] if image else user
                provider.calls.append(Call(model, system, prompt, image))
                text = _answer(model, prompt, image, reasoner, slot)
                self._send(
                    200,
                    {"choices": [{"message": {"role": "assistant", "content": text}}]},
                )

        self._server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self.port = self._server.server_address[1]
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def research_calls(self, model: str | None = None) -> list[Call]:
        """Calls that carried a research question (not a capability probe)."""
        return [
            c
            for c in self.calls
            if _MARKER in c.prompt
            and "PROBE:" not in c.prompt
            and (model is None or c.model == model)
        ]


def _answer(model: str, prompt: str, image: bool, reasoner: CatalogReasoner, slot: Any) -> str:
    if prompt.startswith("Reply with exactly one word: pong"):
        return "pong"
    if model == "fake-chatty":
        return "Certainly! Here is what you asked for, in prose rather than JSON."
    if image:
        return "Red."
    if prompt.startswith("Return exactly this JSON object"):
        return '{"probe": "structured", "value": 42}'
    if prompt.startswith("Write only a Python function named add"):
        return "def add(a, b):\n    return a + b\n"
    if _MARKER not in prompt:
        return "I have nothing to add."
    context = json.loads(prompt.split(_MARKER, 1)[1])
    if isinstance(context, dict) and str(context.get("question", "")).startswith("PROBE:"):
        return json.dumps(_probe_answer(prompt, context))
    return str(reasoner(prompt, slot))


def _probe_answer(prompt: str, ctx: dict[str, Any]) -> dict[str, Any]:
    """Valid answers to the capability probes' role prompts, built from what each context gives."""
    if "mode" in ctx:
        return {"terms": ["contact resistance", "oxidation"]}
    if "outcome_spaces" in ctx:
        space = ctx["outcome_spaces"][0]
        return {
            "hypotheses": [
                {
                    "key": key,
                    "statement": statement,
                    "mechanism": mechanism,
                    "assumptions": ["the reading is representative"],
                    "falsifier": falsifier,
                    "confounders": ["probe placement"],
                    "minimal_test_ref": "four point measurement",
                    "predictions": [
                        {
                            "observable_ref": "probe.resistance",
                            "outcome_space_id": space["outcome_space_id"],
                            "outcome_space_version": space["outcome_space_version"],
                            "expected_outcome": space["outcomes"][0],
                            "relation_effect": "SUPPORTS",
                        }
                    ],
                }
                for key, statement, mechanism, falsifier in (
                    ("h1", "Oxidised contacts add resistance.", "contact oxidation", "nominal 4PP"),
                    ("h2", "Self heating raises resistance.", "self heating", "no current effect"),
                )
            ],
            "position": {"mechanism_view": "contact oxidation", "uncertainties": []},
        }
    if "specialist" in ctx:
        return {
            "mechanism_view": "contact oxidation fits the pads",
            "favoured_hypothesis_ids": [ctx["hypotheses"][0]["hypothesis_id"]],
            "uncertainties": ["pad history"],
            "confounders": [],
            "proposed_predictions": [],
        }
    return {
        "objections": [
            {
                "target_id": ctx["hypotheses"][0]["hypothesis_id"],
                "kind": "CONFOUNDER",
                "severity": "CHALLENGES",
                "text": "the substrate may not have been stable",
                "evidence_attestation_ids": [ctx["evidence"][-1]["attestation_id"]],
            }
        ],
        "alternative_mechanisms": [],
        "falsifier_challenges": [],
    }


__all__ = ["MODELS", "REDIRECT_BODY", "Call", "FakeProvider"]
