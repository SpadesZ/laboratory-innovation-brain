"""Capability probes: what a model is asked and how its answer is judged. Fixed, versioned.

A probe sends ONLY the fixed text in this module -- a synthetic question about a synthetic device,
no project, no evidence, no user text -- so a probe needs no egress decision: nothing of any
project leaves. Each answer is judged by code, never by another model:

    CHAT             the reply contains the word asked for
    STRUCTURED_JSON  the reply parses, as it stands, into exactly the object asked for
    ROLE_*           the reply to the real M3 role prompt (same template, same rendered CONTEXT
                     block `ScientificLLM` sends, same response contract a runtime sends) passes
                     the real typed role parser
    CODE             the reply parses as Python and defines the function asked for (parsed with
                     `ast`, NEVER executed)
    VISION           the reply names the colour of the image it was sent

The answer itself is not kept: its SHA-256 is, with the outcome, the latency and a redacted
reason, so the probe log shows what was proven without storing what a provider wrote.

ROLE_HYPOTHESIS IS PARAMETERISED. The Hypothesis Engine is asked for at least N competing
certificates, and N is the caller's: §7.4's generic floor is 2 (`GENERIC_HYPOTHESIS_MINIMUM`), and a
deployment's research asks for its own (a domain's Stage A wants one per catalogued mechanism). The
probe is run at the N asked for and its result RECORDS that N (`ProbeResult.parameters`), so the
evidence says what was demonstrated: a pass at 5 covers a requirement of 5 or less, a pass at 2 does
not cover 5. The material stays synthetic either way.

WHAT QUALIFIES A MODEL is fixed by `QUALIFICATION_DIGEST`: the probe version and payloads, the role
prompts they carry (id, version, text) and the response contracts. It is part of every lock
fingerprint, so a lock made before any of them changed no longer matches, and is refused as stale.
"""

from __future__ import annotations

import ast
import hashlib
import json
import struct
import zlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from lab_brain.cognition.llm import _render
from lab_brain.cognition.roles import (
    ADVERSARIAL_CRITIC,
    HYPOTHESIS_ENGINE,
    QUERY_REWRITER,
    RoleOutputRefused,
    parse_critique,
    parse_hypothesis_engine,
    parse_query_terms,
    parse_specialist,
)
from lab_brain.core.models.prediction import OutcomeSpace
from lab_brain.llm_runtime.capabilities import Capability
from lab_brain.llm_runtime.contracts import (
    CONTRACT_DIGEST,
    CRITIQUE_CONTRACT,
    HYPOTHESIS_CONTRACT,
    QUERY_CONTRACT,
    SPECIALIST_CONTRACT,
)
from lab_brain.llm_runtime.provider import OpenAICompatibleClient, ProviderError

#: 2.0.0: ROLE_HYPOTHESIS is run at the requested minimum and records it; the Hypothesis Engine
#: prompt it carries asks for CONTEXT.minimum_hypotheses (`cognition.roles`, prompt 2.0.0).
PROBE_VERSION = "probe-2.0.0"

#: §7.4 / EPI-001: Stage A returns at least two COMPETING certificates. What a deployment's research
#: asks for may be more; it is never less.
GENERIC_HYPOTHESIS_MINIMUM = 2

#: The order probes run in, and the default set (every capability).
PROBE_ORDER: tuple[Capability, ...] = tuple(Capability)


class ProbeOutcome(StrEnum):
    PASSED = "PASSED"
    #: The model answered, and the answer did not meet the probe.
    FAILED = "FAILED"
    #: The endpoint could not be asked (unreachable, refused the credential, not the protocol).
    ERROR = "ERROR"


@dataclass(frozen=True)
class ProbeResult:
    capability: Capability
    outcome: ProbeOutcome
    detail: str
    latency_ms: int | None = None
    response_digest: str | None = None
    #: What the probe demanded, where that varies (ROLE_HYPOTHESIS: `minimum_hypotheses`).
    parameters: Mapping[str, int] = field(default_factory=dict)


# -- the fixed payloads ----------------------------------------------------------------------------

_QUESTION = "PROBE: why does the synthetic test resistor read high?"
_EVIDENCE = [
    {
        "attestation_id": "att:probe-1",
        "trust_class": "INTERNAL_MEASUREMENT",
        "text": "The synthetic test resistor reads 30 percent above its nominal value at 25 C.",
    },
    {
        "attestation_id": "att:probe-2",
        "trust_class": "INTERNAL_MEASUREMENT",
        "text": "Its contact pads show visible oxidation; the substrate temperature was stable.",
    },
]
#: The Hypothesis Engine's probe gets more synthetic observations than the other role probes, so
#: that several distinct mechanisms are arguable when it is asked for several -- still nothing of
#: any project.
_HYPOTHESIS_EVIDENCE = [
    *_EVIDENCE,
    {
        "attestation_id": "att:probe-3",
        "trust_class": "INTERNAL_MEASUREMENT",
        "text": "At constant current the reading drifts upward by 4 percent over ten minutes.",
    },
    {
        "attestation_id": "att:probe-4",
        "trust_class": "INTERNAL_MEASUREMENT",
        "text": "Six of the eight resistors on the die read high; the six sit near the die edge.",
    },
    {
        "attestation_id": "att:probe-5",
        "trust_class": "INTERNAL_MEASUREMENT",
        "text": "The die was annealed at 450 C after metallisation; the probe needles are new.",
    },
]
_SPACE = OutcomeSpace(
    outcome_space_id="os:probe.level",
    version="1.0.0",
    domain="probe",
    action_type="MEASUREMENT",
    outcomes=("HIGH", "NOMINAL"),
)
_HYPOTHESES = [
    {
        "hypothesis_id": "hyp:probe-contact",
        "statement": "Oxidised contacts add series resistance.",
        "mechanism": "contact oxidation",
        "falsifier": "a four point measurement reads nominal",
        "assumptions": ["the pads carry the current"],
    },
    {
        "hypothesis_id": "hyp:probe-thermal",
        "statement": "Self heating raises the resistance.",
        "mechanism": "self heating",
        "falsifier": "the reading does not change with current",
        "assumptions": ["the current is high enough to heat"],
    },
]
_SPECIALIST_TEMPLATE = (
    "You are a domain specialist. State your independent position on the hypotheses given, over "
    "the evidence given only. Reply with JSON."
)


def _material(template: str, context: dict[str, object]) -> str:
    rendered, _ = _render(context)
    assert rendered is not None
    return template + rendered


def _red_png(size: int = 16) -> bytes:
    """A solid red PNG, built here: nothing is read from disk or sent but these bytes."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    row = b"\x00" + b"\xff\x00\x00" * size
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(row * size))
        + chunk(b"IEND", b"")
    )


PROBE_IMAGE_PNG = _red_png()


@dataclass(frozen=True)
class _Probe:
    prompt: str
    system: str | None
    judge: Callable[[str], str | None]  # None = passed; else why it failed
    image: bool = False


def _chat(text: str) -> str | None:
    return None if "pong" in text.lower() else "the reply does not contain 'pong'"


def _structured(text: str) -> str | None:
    try:
        value = json.loads(text)
    except ValueError:
        return "the reply is not bare JSON (prose or code fences around it are not accepted)"
    return None if value == {"probe": "structured", "value": 42} else "the JSON is not the object"


def _code(text: str) -> str | None:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return "the reply does not parse as Python"
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "add" and len(node.args.args) == 2:
            return None
    return "the reply defines no function add(a, b)"


def _vision(text: str) -> str | None:
    return None if "red" in text.lower() else "the reply does not name the image's colour (red)"


def _role(parse: Callable[[str], object]) -> Callable[[str], str | None]:
    def judge(text: str) -> str | None:
        try:
            parse(text)
        except RoleOutputRefused as refused:
            return f"the typed role parser refused it: {refused}"
        return None

    return judge


def hypothesis_probe(minimum: int) -> _Probe:
    """The Hypothesis Engine's probe at `minimum` competing certificates: the real role prompt and
    contract over synthetic evidence, judged by the real parser at that same minimum."""
    if not GENERIC_HYPOTHESIS_MINIMUM <= minimum <= 50:
        raise ValueError(
            f"a hypothesis minimum is between {GENERIC_HYPOTHESIS_MINIMUM} and 50, not {minimum}"
        )
    spaces = {(_SPACE.outcome_space_id, _SPACE.version): _SPACE}
    return _Probe(
        _material(
            HYPOTHESIS_ENGINE.prompt.template,
            {
                "question": _QUESTION,
                "evidence": _HYPOTHESIS_EVIDENCE,
                "outcome_spaces": [
                    {
                        "outcome_space_id": _SPACE.outcome_space_id,
                        "outcome_space_version": _SPACE.version,
                        "outcomes": list(_SPACE.outcomes),
                        "action_type": _SPACE.action_type,
                    }
                ],
                "minimum_hypotheses": minimum,
                "alternatives_to_certify": [],
                "existing_mechanisms": [],
            },
        ),
        HYPOTHESIS_CONTRACT,
        _role(lambda text: parse_hypothesis_engine(text, spaces=spaces, minimum=minimum)),
    )


PROBES: dict[Capability, _Probe] = {
    Capability.CHAT: _Probe("Reply with exactly one word: pong", None, _chat),
    Capability.STRUCTURED_JSON: _Probe(
        "Return exactly this JSON object and nothing else, no code fences: "
        '{"probe": "structured", "value": 42}',
        None,
        _structured,
    ),
    Capability.ROLE_QUERY: _Probe(
        _material(QUERY_REWRITER.prompt.template, {"question": _QUESTION, "mode": "PRIMARY"}),
        QUERY_CONTRACT,
        _role(parse_query_terms),
    ),
    Capability.ROLE_HYPOTHESIS: hypothesis_probe(GENERIC_HYPOTHESIS_MINIMUM),
    Capability.ROLE_SPECIALIST: _Probe(
        _material(
            _SPECIALIST_TEMPLATE,
            {
                "question": _QUESTION,
                "specialist": "probe.specialist",
                "hypotheses": [
                    {k: h[k] for k in ("hypothesis_id", "statement", "mechanism")}
                    for h in _HYPOTHESES
                ],
                "evidence": _EVIDENCE,
            },
        ),
        SPECIALIST_CONTRACT,
        _role(
            lambda text: parse_specialist(
                text,
                role_id="probe.specialist",
                hypothesis_ids=[str(h["hypothesis_id"]) for h in _HYPOTHESES],
            )
        ),
    ),
    Capability.ROLE_CRITIQUE: _Probe(
        _material(
            ADVERSARIAL_CRITIC.prompt.template,
            {
                "question": _QUESTION,
                "hypotheses": _HYPOTHESES,
                "positions": [
                    {
                        "role_id": "HYPOTHESIS_ENGINE",
                        "mechanism_view": "contact oxidation is the likelier mechanism",
                        "hypothesis_refs": ["hyp:probe-contact"],
                    }
                ],
                "evidence": _EVIDENCE,
                "inverted_attestation_ids": ["att:probe-2"],
            },
        ),
        CRITIQUE_CONTRACT,
        _role(
            lambda text: parse_critique(
                text,
                targets=[str(h["hypothesis_id"]) for h in _HYPOTHESES],
                shown_attestation_ids=[e["attestation_id"] for e in _EVIDENCE],
            )
        ),
    ),
    Capability.CODE: _Probe(
        "Write only a Python function named add that returns the sum of its two arguments. "
        "No prose, no code fences.",
        None,
        _code,
    ),
    Capability.VISION: _Probe(
        "What single colour fills this image? Answer with one word.", None, _vision, image=True
    ),
}


def qualification_digest(
    *,
    probe_version: str,
    contracts: str,
    probes: Mapping[str, object],
    prompts: Mapping[str, object],
) -> str:
    """The semantics a model is qualified under, as one digest: change any part and every lock
    made before no longer matches it."""
    return hashlib.sha256(
        json.dumps(
            {
                "version": probe_version,
                "contracts": contracts,
                "probes": dict(probes),
                "prompts": dict(prompts),
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


#: Part of every lock fingerprint (`registry.lock_fingerprint`). The ROLE_HYPOTHESIS payload is
#: taken at the generic floor: its minimum is the lock's own recorded parameter, not semantics.
QUALIFICATION_DIGEST = qualification_digest(
    probe_version=PROBE_VERSION,
    contracts=CONTRACT_DIGEST,
    probes={c.value: [p.prompt, p.system] for c, p in PROBES.items()},
    prompts={
        role.prompt.prompt_id: [role.prompt.prompt_version, role.prompt.template]
        for role in (QUERY_REWRITER, HYPOTHESIS_ENGINE, ADVERSARIAL_CRITIC)
    }
    | {"probe:specialist": ["-", _SPECIALIST_TEMPLATE]},
)


def run_probe(
    client: OpenAICompatibleClient,
    model: str,
    capability: Capability,
    *,
    hypothesis_minimum: int = GENERIC_HYPOTHESIS_MINIMUM,
) -> ProbeResult:
    """`hypothesis_minimum`: what ROLE_HYPOTHESIS is run at -- the requirement the caller wants
    demonstrated, recorded with the result. Ignored by every other capability."""
    parameters: dict[str, int] = {}
    if capability is Capability.ROLE_HYPOTHESIS:
        probe = hypothesis_probe(hypothesis_minimum)
        parameters = {"minimum_hypotheses": hypothesis_minimum}
    else:
        probe = PROBES[capability]
    try:
        reply = client.chat(
            model,
            probe.prompt,
            system=probe.system,
            image_png=PROBE_IMAGE_PNG if probe.image else None,
        )
    except ProviderError as failed:
        return ProbeResult(
            capability,
            ProbeOutcome.ERROR,
            f"{failed.failure.value}: {failed.detail}",
            parameters=parameters,
        )
    digest = "sha256:" + hashlib.sha256(reply.text.encode("utf-8")).hexdigest()
    reason = probe.judge(reply.text.strip())
    if reason is None:
        return ProbeResult(
            capability, ProbeOutcome.PASSED, "", reply.latency_ms, digest, parameters
        )
    return ProbeResult(
        capability, ProbeOutcome.FAILED, reason[:300], reply.latency_ms, digest, parameters
    )


__all__ = [
    "GENERIC_HYPOTHESIS_MINIMUM",
    "PROBES",
    "PROBE_IMAGE_PNG",
    "PROBE_ORDER",
    "PROBE_VERSION",
    "QUALIFICATION_DIGEST",
    "ProbeOutcome",
    "ProbeResult",
    "hypothesis_probe",
    "qualification_digest",
    "run_probe",
]
