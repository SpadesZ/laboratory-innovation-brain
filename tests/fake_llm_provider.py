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

`delay` (off by default) makes it a SLOW model: given a chat call's (prompt, system), the seconds
it waits before answering -- so a test can run one role into the caller's deadline and leave the
rest fast.

`redirect_to` (off by default) makes it answer EVERY request with a redirect there instead
(`redirect_status`, the request's path appended): a provider that moved, or one that tries to
send the call -- credential and prompt -- somewhere else. Its body carries `REDIRECT_BODY`, so a
test can show none of it is kept.

`invent_space` (off by default) makes its Hypothesis Engine probe answers INVENTIVE: given several
outcome spaces, it binds one prediction to a space it named itself from a quantity in the evidence
(`INVENTED_SPACE`) -- the error a real model made -- and is otherwise as valid as ever.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from lab_brain.cognition.catalog_reasoner import CatalogReasoner, reasoner_slots
from lab_brain.core.models.inference import LogicalSlot
from lab_brain.domains.silicon_photonics.product import mechanism_catalog

MODELS = ("fake-reasoner", "fake-critic", "fake-chatty")
REDIRECT_BODY = "moved: follow me to the new address"
#: What an inventive model binds a prediction to: a quantity the probe's evidence names, made into
#: an outcome space id it was never given.
INVENTED_SPACE = ("os:probe.noise_per_hz", "1.0.0")
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
    delay: Callable[[str, str | None], float] | None = None
    redirect_to: str | None = None
    redirect_status: int = 307
    redirected: int = 0
    invent_space: bool = False
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
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                except OSError:  # a caller that gave up waiting (its deadline) has gone
                    return

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
                if provider.delay is not None and (wait := provider.delay(prompt, system)) > 0:
                    time.sleep(wait)
                text = _answer(model, prompt, image, reasoner, slot, provider.invent_space)
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


def _answer(
    model: str,
    prompt: str,
    image: bool,
    reasoner: CatalogReasoner,
    slot: Any,
    invent: bool = False,
) -> str:
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
        return json.dumps(_probe_answer(prompt, context, invent=invent))
    return str(reasoner(prompt, slot))


#: Distinct mechanisms for the Hypothesis Engine's probe: as many as its context asks for (the
#: probe is run at the deployment's minimum), so the stand-in qualifies wherever a real model would.
_PROBE_MECHANISMS = (
    ("h1", "Oxidised contacts add resistance.", "contact oxidation", "nominal 4PP"),
    ("h2", "Self heating raises resistance.", "self heating", "no current effect"),
    ("h3", "Edge dies carry a thinner film.", "edge film thinning", "edge and centre agree"),
    ("h4", "The anneal grew a resistive silicide.", "anneal silicide", "unannealed die reads high"),
    ("h5", "New needles press too lightly.", "needle contact force", "harder press reads nominal"),
    (
        "h6",
        "Moisture raised the surface leakage.",
        "surface moisture",
        "dry nitrogen changes nothing",
    ),
)


def _probe_answer(prompt: str, ctx: dict[str, Any], *, invent: bool = False) -> dict[str, Any]:
    """Valid answers to the capability probes' role prompts, built from what each context gives --
    but for `invent`, one prediction bound to `INVENTED_SPACE` wherever several spaces are given."""
    if "mode" in ctx:
        return {"terms": ["contact resistance", "oxidation"]}
    if "outcome_spaces" in ctx:
        space = ctx["outcome_spaces"][0]
        answer = {
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
                for key, statement, mechanism, falsifier in _PROBE_MECHANISMS[
                    : max(2, int(ctx.get("minimum_hypotheses", 2)))
                ]
            ],
            "position": {"mechanism_view": "contact oxidation", "uncertainties": []},
        }
        if invent and len(ctx["outcome_spaces"]) > 1:
            prediction = answer["hypotheses"][-1]["predictions"][0]
            prediction["outcome_space_id"], prediction["outcome_space_version"] = INVENTED_SPACE
        return answer
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


__all__ = ["INVENTED_SPACE", "MODELS", "REDIRECT_BODY", "Call", "FakeProvider"]
