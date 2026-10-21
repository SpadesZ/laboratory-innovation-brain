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

Every case states its prediction vocabulary as research does (`CONTEXT.prediction_bindings`:
observable -> declared space), with canonical observable ids that are NOT their spaces' ids -- so a
model that writes a space id where the observable belongs, pairs an observable with another
binding's space, or names an observable of its own, fails the case as research would refuse it.

Every hypothesis a case accepts carries a TYPED falsifier: `falsifier_prediction_keys` names at
least one of its own predictions with relation_effect CONTRADICTS. A prose-only falsifier, a
designation of a SUPPORTS, PREDICTS or TESTS prediction, a key that names no prediction of the
same hypothesis -- each fails the case, because research would refuse that certificate.

ROLE_SPECIALIST AND ROLE_CRITIQUE ARE ASKED AS RESEARCH ASKS (probe-7.0.0). A live run failed where
the probe had passed: the probe showed short synthetic ids (`hyp:probe-contact`), research showed
`hyp:<uuid>`, and a model shortened one. So every id in a probe payload now has production's shape
(`hyp:` / `att:` + a UUID, fixed so the payload is), the context is built by the SAME function
research uses (`cognition.debate.specialist_context`, `critique_context`), which shows each id as
its alias, and the reply is judged by the same parser with the same alias resolution -- after the
same envelope repair (`roles.normalize_reply`), and with the same JSON schema sent. Five rivals over
five observations, as a domain's Stage A produces. A model qualified on the old short-id probes is
not qualified now: the probe version is part of every lock, and those locks are stale.

ROLE_HYPOTHESIS's suite includes the COVERAGE REVIEW (`coverage-review`): the review research runs
after Stage A, asked over synthetic hypotheses and one unaddressed synthetic check, judged by its
parser (every check certified by a grounded new rival, or declined with a reason). A route serves
it on the same slot, so a model must demonstrate it to be bound there.

WHAT QUALIFIES A MODEL is fixed by `QUALIFICATION_DIGEST`: the probe version and payloads, the role
prompts they carry (id, version, text) and the response contracts. It is part of every lock
fingerprint, so a lock made before any of them changed no longer matches, and is refused as stale.
"""

from __future__ import annotations

import ast
import hashlib
import json
import struct
import uuid
import zlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from lab_brain.cognition.aliases import AliasTable
from lab_brain.cognition.debate import coverage_context, critique_context, specialist_context
from lab_brain.cognition.llm import _render
from lab_brain.cognition.roles import (
    ADVERSARIAL_CRITIC,
    COVERAGE_REVIEW,
    HYPOTHESIS_ENGINE,
    QUERY_REWRITER,
    RoleOutputRefused,
    binding_context,
    normalize_reply,
    parse_coverage_review,
    parse_critique,
    parse_hypothesis_engine,
    parse_query_terms,
    parse_specialist,
)
from lab_brain.core.models.prediction import OutcomeSpace
from lab_brain.llm_runtime.capabilities import Capability
from lab_brain.llm_runtime.contracts import (
    CONTRACT_DIGEST,
    COVERAGE_CONTRACT,
    CRITIQUE_CONTRACT,
    HYPOTHESIS_CONTRACT,
    QUERY_CONTRACT,
    SPECIALIST_CONTRACT,
    schema_for,
)
from lab_brain.llm_runtime.provider import OpenAICompatibleClient, ProviderError

#: 2.0.0: ROLE_HYPOTHESIS is run at the requested minimum and records it; the Hypothesis Engine
#: prompt it carries asks for CONTEXT.minimum_hypotheses (`cognition.roles`, prompt 2.0.0).
#: 3.0.0: ROLE_HYPOTHESIS is the conformance suite `HYPOTHESIS_SUITE`.
#: 4.0.0: the suite's cases declare observable -> space bindings (prompt 3.0.0, rc-2.0.0).
#: 5.0.0: every certificate designates a typed falsifier (prompt 4.0.0, rc-3.0.0).
#: 6.0.0: the relation effects are defined and one outcome takes one effect (prompt 5.0.0,
#: rc-4.0.0).
#: 7.0.0: production-shaped ids shown as aliases, through research's own context builders, five
#: rivals; every role reply judged after the same envelope repair, with the role's JSON schema
#: sent; ROLE_HYPOTHESIS includes the coverage review (rc-5.0.0).
PROBE_VERSION = "probe-7.0.0"

#: The ROLE_HYPOTHESIS conformance suite and its version, recorded with every result. 1.0.0: the
#: cases `contextual-minimum` and `multi-space`. 2.0.0: the same cases, each over declared
#: observable -> space bindings whose observable ids differ from their space ids. 3.0.0: the same
#: cases, and a case passes only if every hypothesis it accepts designates a typed falsifier.
#: 4.0.0: the same cases, under prompt 5.0.0's defined effects; a case also fails if a hypothesis
#: gives one outcome of an observable two different effects. Support is never required: a
#: falsification-only certificate passes, as research admits it.
#: 5.0.0: the same cases, plus `coverage-review`; evidence ids have production's shape.
HYPOTHESIS_SUITE = "hypothesis-conformance@5.0.0"

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


def production_id(prefix: str, label: str) -> str:
    """A canonical id of production's shape, `<prefix>:<uuid4>` -- fixed by `label`, so the
    payload (and the qualification digest) is the same on every machine."""
    digest = hashlib.sha256(f"lab-brain-probe:{prefix}:{label}".encode()).digest()
    return f"{prefix}:{uuid.UUID(bytes=digest[:16], version=4)}"


_QUESTION = "PROBE: why does the synthetic test resistor read high?"
_EVIDENCE = [
    {
        "attestation_id": production_id("att", "probe-1"),
        "trust_class": "INTERNAL_MEASUREMENT",
        "text": "The synthetic test resistor reads 30 percent above its nominal value at 25 C.",
    },
    {
        "attestation_id": production_id("att", "probe-2"),
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
        "attestation_id": production_id("att", "probe-3"),
        "trust_class": "INTERNAL_MEASUREMENT",
        "text": "At constant current the reading drifts upward by 4 percent over ten minutes.",
    },
    {
        "attestation_id": production_id("att", "probe-4"),
        "trust_class": "INTERNAL_MEASUREMENT",
        "text": "Six of the eight resistors on the die read high; the six sit near the die edge.",
    },
    {
        "attestation_id": production_id("att", "probe-5"),
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
#: The `contextual-minimum` case's vocabulary: one observable, read in that space.
_BINDINGS: Mapping[str, OutcomeSpace] = {"bench.resistor_reading": _SPACE}

#: The `multi-space` case: another synthetic bench, several declared spaces, and evidence that
#: names quantities which are NOT among them -- the shape of a real research context, where the
#: evidence talks about more than the domain declares. Nothing of any domain or project.
_MULTI_QUESTION = (
    "PROBE: why does channel A of the synthetic bench sensor read above its reference?"
)
_MULTI_EVIDENCE = [
    {
        "attestation_id": production_id("att", "probe-m1"),
        "trust_class": "INTERNAL_MEASUREMENT",
        "text": "Channel A of the synthetic bench sensor reads 25 percent above its reference.",
    },
    {
        "attestation_id": production_id("att", "probe-m2"),
        "trust_class": "INTERNAL_MEASUREMENT",
        "text": "After power-on the channel A reading rises for about twenty minutes, then holds.",
    },
    {
        "attestation_id": production_id("att", "probe-m3"),
        "trust_class": "INTERNAL_MEASUREMENT",
        "text": "Readings near the edge of the fixture plate are higher than at its centre.",
    },
    {
        "attestation_id": production_id("att", "probe-m4"),
        "trust_class": "INTERNAL_MEASUREMENT",
        "text": "Ten repeated readings on the same bench agree to within 1 percent.",
    },
    {
        "attestation_id": production_id("att", "probe-m5"),
        "trust_class": "INTERNAL_MEASUREMENT",
        "text": "The bench log also records the noise floor per hertz (logged as noise_per_hz) and "
        "a room humidity of 62 percent.",
    },
    {
        "attestation_id": production_id("att", "probe-m6"),
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
#: The `multi-space` case's vocabulary. The observable ids are not their spaces' ids, nor derived
#: from them: copying `os:probe.bench_level` as an observable fails, as it would in research.
_MULTI_BINDINGS: Mapping[str, OutcomeSpace] = dict(
    zip(
        (
            "bench.channel_offset",
            "bench.warmup_drift",
            "fixture.edge_gradient",
            "bench.repeat_spread",
        ),
        _MULTI_SPACES,
        strict=True,
    )
)
#: Five rivals, as a domain's Stage A produces, each under a production-shaped id.
_HYPOTHESES = [
    {
        "hypothesis_id": production_id("hyp", "contact"),
        "statement": "Oxidised contacts add series resistance.",
        "mechanism": "contact oxidation",
        "falsifier": "a four point measurement reads nominal",
        "assumptions": ["the pads carry the current"],
    },
    {
        "hypothesis_id": production_id("hyp", "thermal"),
        "statement": "Self heating raises the resistance.",
        "mechanism": "self heating",
        "falsifier": "the reading does not change with current",
        "assumptions": ["the current is high enough to heat"],
    },
    {
        "hypothesis_id": production_id("hyp", "edge"),
        "statement": "A process gradient toward the die edge raises sheet resistance there.",
        "mechanism": "die edge process gradient",
        "falsifier": "resistors at the die centre read as high as those at the edge",
        "assumptions": ["the high readings cluster by position"],
    },
    {
        "hypothesis_id": production_id("hyp", "anneal"),
        "statement": "The 450 C anneal degraded the metal-to-resistor interface.",
        "mechanism": "anneal interface degradation",
        "falsifier": "an unannealed die reads the same",
        "assumptions": ["the anneal followed metallisation"],
    },
    {
        "hypothesis_id": production_id("hyp", "meter"),
        "statement": "The meter's calibration has drifted high.",
        "mechanism": "meter calibration drift",
        "falsifier": "a reference resistor reads nominal on the same meter",
        "assumptions": ["the meter was last calibrated long ago"],
    },
]

#: The `coverage-review` case: one synthetic check no rival above discriminates on.
_COVERAGE_BINDINGS: Mapping[str, OutcomeSpace] = {
    "bench.resistor_reading": _SPACE,
    "bench.repeat_spread": OutcomeSpace(
        outcome_space_id="os:probe.repeatability",
        version="1.0.0",
        domain="probe",
        action_type="ANALYTICAL_RULE_CHECK",
        outcomes=("REPEATABLE", "SCATTERED"),
    ),
}
_UNADDRESSED = ("bench.repeat_spread",)
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
    """Judged as research reads a reply: `normalize_reply`'s envelope repair, then the parser."""

    def judge(text: str) -> str | None:
        try:
            parse(normalize_reply(text)[0])
        except RoleOutputRefused as refused:
            return f"the typed role parser refused it: {refused}"
        return None

    return judge


def _hypothesis_case(
    question: str,
    evidence: list[dict[str, str]],
    bindings: Mapping[str, OutcomeSpace],
    minimum: int,
) -> _Probe:
    """One case of the suite: the real role prompt and contract over synthetic evidence and a
    declared prediction vocabulary -- rendered as the debate renders it -- judged by the real parser
    at `minimum`, against exactly the bindings declared."""
    if not GENERIC_HYPOTHESIS_MINIMUM <= minimum <= 50:
        raise ValueError(
            f"a hypothesis minimum is between {GENERIC_HYPOTHESIS_MINIMUM} and 50, not {minimum}"
        )
    return _Probe(
        _material(
            HYPOTHESIS_ENGINE.prompt.template,
            {
                "question": question,
                "evidence": evidence,
                "prediction_bindings": binding_context(bindings),
                "minimum_hypotheses": minimum,
                "alternatives_to_certify": [],
                "existing_mechanisms": [],
            },
        ),
        HYPOTHESIS_CONTRACT,
        _role(lambda text: parse_hypothesis_engine(text, bindings=bindings, minimum=minimum)),
    )


def hypothesis_probe(minimum: int) -> _Probe:
    """The `contextual-minimum` case: `minimum` competing certificates over one declared binding."""
    return _hypothesis_case(_QUESTION, _HYPOTHESIS_EVIDENCE, _BINDINGS, minimum)


def multi_space_probe(minimum: int) -> _Probe:
    """The `multi-space` case: `minimum` competing certificates, every prediction over one of
    several declared bindings, over evidence naming quantities that none of them is."""
    return _hypothesis_case(_MULTI_QUESTION, _MULTI_EVIDENCE, _MULTI_BINDINGS, minimum)


def specialist_probe() -> _Probe:
    """ROLE_SPECIALIST as research asks it: `specialist_context` over five production-shaped
    rivals and the observations, each id shown as its alias; judged by `parse_specialist` with the
    aliases that call showed."""
    context, shown_h, _ = specialist_context(
        question=_QUESTION,
        specialist="probe.specialist",
        hypotheses=[
            {k: h[k] for k in ("hypothesis_id", "statement", "mechanism")} for h in _HYPOTHESES
        ],
        evidence=_HYPOTHESIS_EVIDENCE,
        hypothesis_aliases=AliasTable("H"),
        evidence_aliases=AliasTable("E"),
    )
    ids = [str(h["hypothesis_id"]) for h in _HYPOTHESES]
    return _Probe(
        _material(_SPECIALIST_TEMPLATE, context),
        SPECIALIST_CONTRACT,
        _role(
            lambda text: parse_specialist(
                text, role_id="probe.specialist", hypothesis_ids=ids, shown=shown_h
            )
        ),
    )


def critique_probe() -> _Probe:
    """ROLE_CRITIQUE as research asks it: `critique_context` over five production-shaped rivals,
    the engine's position and the observations (one from the inverted retrieval), each id shown as
    its alias; judged by `parse_critique` with those aliases."""
    context, shown_h, shown_e = critique_context(
        question=_QUESTION,
        hypotheses=_HYPOTHESES,
        positions=[
            {
                "role_id": "HYPOTHESIS_ENGINE",
                "mechanism_view": "contact oxidation is the likelier mechanism",
                "hypothesis_refs": [str(_HYPOTHESES[0]["hypothesis_id"])],
            }
        ],
        evidence=_HYPOTHESIS_EVIDENCE,
        inverted_attestation_ids=[str(_HYPOTHESIS_EVIDENCE[1]["attestation_id"])],
        hypothesis_aliases=AliasTable("H"),
        evidence_aliases=AliasTable("E"),
    )
    targets = [str(h["hypothesis_id"]) for h in _HYPOTHESES]
    shown = [str(e["attestation_id"]) for e in _HYPOTHESIS_EVIDENCE]
    return _Probe(
        _material(ADVERSARIAL_CRITIC.prompt.template, context),
        CRITIQUE_CONTRACT,
        _role(
            lambda text: parse_critique(
                text,
                targets=targets,
                shown_attestation_ids=shown,
                hypothesis_refs=shown_h,
                evidence_refs=shown_e,
            )
        ),
    )


def coverage_probe() -> _Probe:
    """The `coverage-review` case: `coverage_context` over rivals that all predict the reading
    and one synthetic check none of them discriminates on; judged by `parse_coverage_review`."""
    rivals = [
        {
            **{k: h[k] for k in ("hypothesis_id", "statement", "mechanism")},
            "discriminates_on": ["bench.resistor_reading"],
        }
        for h in _HYPOTHESES[:3]
    ]
    checks: list[dict[str, Any]] = [
        {
            "observable_ref": "bench.repeat_spread",
            "outcome_space_id": "os:probe.repeatability",
            "outcome_space_version": "1.0.0",
            "outcomes": ["REPEATABLE", "SCATTERED"],
            "check": "cap:probe.repeat_readings",
            "action_type": "ANALYTICAL_RULE_CHECK",
        }
    ]
    context, _, shown_e = coverage_context(
        question=_QUESTION,
        hypotheses=rivals,
        evidence=_HYPOTHESIS_EVIDENCE,
        bindings=_COVERAGE_BINDINGS,
        unaddressed_checks=checks,
        hypothesis_aliases=AliasTable("H"),
        evidence_aliases=AliasTable("E"),
    )
    existing = [str(h["mechanism"]) for h in rivals]
    shown = [str(e["attestation_id"]) for e in _HYPOTHESIS_EVIDENCE]
    return _Probe(
        _material(COVERAGE_REVIEW.prompt.template, context),
        COVERAGE_CONTRACT,
        _role(
            lambda text: parse_coverage_review(
                text,
                bindings=_COVERAGE_BINDINGS,
                unaddressed=_UNADDRESSED,
                existing_mechanisms=existing,
                evidence_refs=shown_e,
                shown_attestation_ids=shown,
            )
        ),
    )


def hypothesis_suite(minimum: int) -> tuple[tuple[str, _Probe], ...]:
    """ROLE_HYPOTHESIS at `minimum`: every case, in order, at the same minimum. The coverage
    review takes no minimum: it may certify none."""
    return (
        ("contextual-minimum", hypothesis_probe(minimum)),
        ("multi-space", multi_space_probe(minimum)),
        ("coverage-review", coverage_probe()),
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
    Capability.ROLE_SPECIALIST: specialist_probe(),
    Capability.ROLE_CRITIQUE: critique_probe(),
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
            for role in (QUERY_REWRITER, HYPOTHESIS_ENGINE, ADVERSARIAL_CRITIC, COVERAGE_REVIEW)
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
            response_schema=schema_for(probe.prompt) if probe.system is not None else None,
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
            reply = client.chat(
                model, probe.prompt, system=probe.system, response_schema=schema_for(probe.prompt)
            )
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
    "coverage_probe",
    "critique_probe",
    "hypothesis_probe",
    "hypothesis_suite",
    "multi_space_probe",
    "production_id",
    "qualification_digest",
    "qualification_inputs",
    "run_probe",
    "specialist_probe",
]
