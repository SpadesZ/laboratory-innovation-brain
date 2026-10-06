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

ROLE_HYPOTHESIS IS A CONFORMANCE SUITE (`HYPOTHESIS_SUITE`), not one call: every case, at the same
N, must pass the real parser. `contextual-minimum` is the single-space certificate case;
`multi-space` declares several synthetic outcome spaces (one at a version other than 1.0.0) over
evidence that names quantities none of them is (`TEMPTING_QUANTITIES`), so a model that binds a
prediction to a space it was not given, or to an outcome its chosen space does not admit, fails --
as research would refuse it (VER-004). Nothing requires every space to be used: the runtime
contract does not. The result records the suite, its cases and N; there is no score.

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
#: 3.0.0: ROLE_HYPOTHESIS is the conformance suite `HYPOTHESIS_SUITE`.
PROBE_VERSION = "probe-3.0.0"

#: The ROLE_HYPOTHESIS conformance suite and its version, recorded with every result. 1.0.0: the
#: cases `contextual-minimum` and `multi-space`.
HYPOTHESIS_SUITE = "hypothesis-conformance@1.0.0"

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
    #: What the probe demanded, where that varies (ROLE_HYPOTHESIS: `minimum_hypotheses`, and the
    #: `suite` and `cases` it was run as).
    parameters: Mapping[str, object] = field(default_factory=dict)


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

#: The `multi-space` case: another synthetic bench, several declared spaces, and evidence that
#: names quantities which are NOT among them -- the shape of a real research context, where the
#: evidence talks about more than the domain declares. Nothing of any domain or project.
_MULTI_QUESTION = (
    "PROBE: why does channel A of the synthetic bench sensor read above its reference?"
)
_MULTI_EVIDENCE = [
    {
        "attestation_id": "att:probe-m1",
        "trust_class": "INTERNAL_MEASUREMENT",
        "text": "Channel A of the synthetic bench sensor reads 25 percent above its reference.",
    },
    {
        "attestation_id": "att:probe-m2",
        "trust_class": "INTERNAL_MEASUREMENT",
        "text": "After power-on the channel A reading rises for about twenty minutes, then holds.",
    },
    {
        "attestation_id": "att:probe-m3",
        "trust_class": "INTERNAL_MEASUREMENT",
        "text": "Readings near the edge of the fixture plate are higher than at its centre.",
    },
    {
        "attestation_id": "att:probe-m4",
        "trust_class": "INTERNAL_MEASUREMENT",
        "text": "Ten repeated readings on the same bench agree to within 1 percent.",
    },
    {
        "attestation_id": "att:probe-m5",
        "trust_class": "INTERNAL_MEASUREMENT",
        "text": "The bench log also records the noise floor per hertz (logged as noise_per_hz) and "
        "a room humidity of 62 percent.",
    },
    {
        "attestation_id": "att:probe-m6",
        "trust_class": "INTERNAL_MEASUREMENT",
        "text": "The bench reference was replaced last week, and the channel A cable is new.",
    },
]
#: Quantities the `multi-space` evidence names that no declared space is: a model that makes one
#: into an outcome space (os:probe.noise_per_hz, say) fails the case.
TEMPTING_QUANTITIES = ("noise_per_hz", "humidity")
_MULTI_SPACES = (
    OutcomeSpace(
        outcome_space_id="os:probe.bench_level",
        version="1.0.0",
        domain="probe",
        action_type="MEASUREMENT",
        outcomes=("ABOVE_REFERENCE", "AT_REFERENCE", "BELOW_REFERENCE"),
    ),
    OutcomeSpace(
        outcome_space_id="os:probe.warmup_trend",
        version="2.0.0",
        domain="probe",
        action_type="MEASUREMENT",
        outcomes=("RISES_THEN_HOLDS", "STEADY", "KEEPS_RISING"),
    ),
    OutcomeSpace(
        outcome_space_id="os:probe.plate_position",
        version="1.0.0",
        domain="probe",
        action_type="MEASUREMENT",
        outcomes=("EDGE_HIGHER", "UNIFORM", "CENTRE_HIGHER"),
    ),
    OutcomeSpace(
        outcome_space_id="os:probe.repeatability",
        version="1.0.0",
        domain="probe",
        action_type="MEASUREMENT",
        outcomes=("REPEATABLE", "SCATTERED"),
    ),
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


def _hypothesis_case(
    question: str,
    evidence: list[dict[str, str]],
    declared: tuple[OutcomeSpace, ...],
    minimum: int,
) -> _Probe:
    """One case of the suite: the real role prompt and contract over synthetic evidence and
    `declared` spaces -- rendered as the debate renders them -- judged by the real parser at
    `minimum`, against exactly the spaces declared."""
    if not GENERIC_HYPOTHESIS_MINIMUM <= minimum <= 50:
        raise ValueError(
            f"a hypothesis minimum is between {GENERIC_HYPOTHESIS_MINIMUM} and 50, not {minimum}"
        )
    spaces = {(s.outcome_space_id, s.version): s for s in declared}
    return _Probe(
        _material(
            HYPOTHESIS_ENGINE.prompt.template,
            {
                "question": question,
                "evidence": evidence,
                "outcome_spaces": [
                    {
                        "outcome_space_id": s.outcome_space_id,
                        "outcome_space_version": s.version,
                        "outcomes": list(s.outcomes),
                        "action_type": s.action_type,
                    }
                    for _, s in sorted(spaces.items())
                ],
                "minimum_hypotheses": minimum,
                "alternatives_to_certify": [],
                "existing_mechanisms": [],
            },
        ),
        HYPOTHESIS_CONTRACT,
        _role(lambda text: parse_hypothesis_engine(text, spaces=spaces, minimum=minimum)),
    )


def hypothesis_probe(minimum: int) -> _Probe:
    """The `contextual-minimum` case: `minimum` competing certificates over one declared space."""
    return _hypothesis_case(_QUESTION, _HYPOTHESIS_EVIDENCE, (_SPACE,), minimum)


def multi_space_probe(minimum: int) -> _Probe:
    """The `multi-space` case: `minimum` competing certificates, every prediction bound to one of
    several declared spaces, over evidence naming quantities that none of them is."""
    return _hypothesis_case(_MULTI_QUESTION, _MULTI_EVIDENCE, _MULTI_SPACES, minimum)


def hypothesis_suite(minimum: int) -> tuple[tuple[str, _Probe], ...]:
    """ROLE_HYPOTHESIS at `minimum`: every case, in order, at the same minimum."""
    return (
        ("contextual-minimum", hypothesis_probe(minimum)),
        ("multi-space", multi_space_probe(minimum)),
    )


#: One probe per capability -- except ROLE_HYPOTHESIS, whose probe is `hypothesis_suite`.
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


def qualification_inputs() -> dict[str, object]:
    """What the qualification semantics in force are made of, as `qualification_digest` takes it.
    The ROLE_HYPOTHESIS suite enters with its version and every case's payload, taken at the
    generic floor: the minimum is a lock's own recorded parameter, not semantics."""
    return {
        "probe_version": PROBE_VERSION,
        "contracts": CONTRACT_DIGEST,
        "probes": {c.value: [p.prompt, p.system] for c, p in PROBES.items()}
        | {
            Capability.ROLE_HYPOTHESIS.value: {
                "suite": HYPOTHESIS_SUITE,
                "cases": {
                    name: [p.prompt, p.system]
                    for name, p in hypothesis_suite(GENERIC_HYPOTHESIS_MINIMUM)
                },
            }
        },
        "prompts": {
            role.prompt.prompt_id: [role.prompt.prompt_version, role.prompt.template]
            for role in (QUERY_REWRITER, HYPOTHESIS_ENGINE, ADVERSARIAL_CRITIC)
        }
        | {"probe:specialist": ["-", _SPECIALIST_TEMPLATE]},
    }


#: Part of every lock fingerprint (`registry.lock_fingerprint`), and recorded with every probe
#: (`012m`): a lock counts only probes run under the digest in force.
QUALIFICATION_DIGEST = qualification_digest(**qualification_inputs())  # type: ignore[arg-type]


def run_probe(
    client: OpenAICompatibleClient,
    model: str,
    capability: Capability,
    *,
    hypothesis_minimum: int = GENERIC_HYPOTHESIS_MINIMUM,
) -> ProbeResult:
    """`hypothesis_minimum`: what ROLE_HYPOTHESIS is run at -- the requirement the caller wants
    demonstrated, recorded with the result. Ignored by every other capability."""
    if capability is Capability.ROLE_HYPOTHESIS:
        return _run_suite(client, model, hypothesis_minimum)
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
            capability, ProbeOutcome.ERROR, f"{failed.failure.value}: {failed.detail}"
        )
    digest = "sha256:" + hashlib.sha256(reply.text.encode("utf-8")).hexdigest()
    reason = probe.judge(reply.text.strip())
    if reason is None:
        return ProbeResult(capability, ProbeOutcome.PASSED, "", reply.latency_ms, digest)
    return ProbeResult(capability, ProbeOutcome.FAILED, reason[:300], reply.latency_ms, digest)


def _run_suite(client: OpenAICompatibleClient, model: str, minimum: int) -> ProbeResult:
    """ROLE_HYPOTHESIS: every case of the suite at `minimum`, in order; the first that fails (or
    cannot be asked) decides, and its name leads the detail. The latency is the slowest call's --
    each call must fit the deadline -- and the digest covers every reply received."""
    cases = hypothesis_suite(minimum)
    parameters: dict[str, object] = {
        "minimum_hypotheses": minimum,
        "suite": HYPOTHESIS_SUITE,
        "cases": [name for name, _ in cases],
    }
    replies: dict[str, str] = {}
    slowest = 0

    def digest() -> str:
        return "sha256:" + hashlib.sha256(json.dumps(replies, sort_keys=True).encode()).hexdigest()

    for name, probe in cases:
        try:
            reply = client.chat(model, probe.prompt, system=probe.system)
        except ProviderError as failed:
            return ProbeResult(
                Capability.ROLE_HYPOTHESIS,
                ProbeOutcome.ERROR,
                f"{name}: {failed.failure.value}: {failed.detail}"[:300],
                parameters=parameters,
            )
        replies[name] = hashlib.sha256(reply.text.encode("utf-8")).hexdigest()
        slowest = max(slowest, reply.latency_ms)
        reason = probe.judge(reply.text.strip())
        if reason is not None:
            return ProbeResult(
                Capability.ROLE_HYPOTHESIS,
                ProbeOutcome.FAILED,
                f"{name}: {reason}"[:300],
                slowest,
                digest(),
                parameters,
            )
    return ProbeResult(
        Capability.ROLE_HYPOTHESIS, ProbeOutcome.PASSED, "", slowest, digest(), parameters
    )


__all__ = [
    "GENERIC_HYPOTHESIS_MINIMUM",
    "HYPOTHESIS_SUITE",
    "PROBES",
    "PROBE_IMAGE_PNG",
    "PROBE_ORDER",
    "PROBE_VERSION",
    "QUALIFICATION_DIGEST",
    "TEMPTING_QUANTITIES",
    "ProbeOutcome",
    "ProbeResult",
    "hypothesis_probe",
    "hypothesis_suite",
    "multi_space_probe",
    "qualification_digest",
    "qualification_inputs",
    "run_probe",
]
