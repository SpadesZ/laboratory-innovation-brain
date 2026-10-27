"""The output contract a language-model route is given with each role prompt.

M3's role prompts end "Reply with JSON." -- enough for the local catalog reasoner, which is written
against the typed role parsers, and not enough for a general language model, which has never seen
them. The parsers are the gate and stay exactly as they are; what a model needs is to be told the
shape they accept.

So a language-model ROUTE carries a fixed system message per role: the JSON shape its parser
reads, generated here from the parsers' own enums. It is part of the route, not of the prompt or
the context:

    * it contains no project data, no evidence and no question -- nothing a gate must classify;
      what leaves with each call is still exactly the prompt and context the egress gate digested,
      plus this constant text;
    * it is versioned (`RESPONSE_CONTRACT_VERSION`) and hashed (`CONTRACT_DIGEST`); the digest is
      part of a locked model's fingerprint, and that fingerprint is the `model_version` every
      InferenceProvenance of the route records -- so an inference names the exact route,
      contracts included, that produced it;
    * the role-capability probes send the same contract, so a model is bindable only if, told
      this, it actually produces output the parsers accept.

A route also carries the role's JSON SCHEMA (`SCHEMAS`), sent as the OpenAI-compatible
`response_format` so a provider that supports schema-constrained output generates only replies of
that shape. The schema is constant text (no project data), part of the digest, and deliberately
the plainest JSON Schema subset -- object, array, string, enum, required -- which providers that
implement structured output accept. It narrows the form; the typed parsers remain the gate and
still refuse anything a schema cannot express (a binding that is not declared, an alias that names
nothing). A provider that rejects the parameter is answered without it, and the reply records that
(`provider.ChatReply.output_mode`), so nothing changes silently.

The catalog reasoner never receives it: it is not a model and does not need to be told.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from lab_brain.cognition.roles import (
    ADVERSARIAL_CRITIC,
    COVERAGE_REVIEW,
    HYPOTHESIS_ENGINE,
    QUERY_REWRITER,
    SCREENING_REVIEW,
)
from lab_brain.core.models.debate import ObjectionKind, ObjectionSeverity
from lab_brain.core.models.prediction import PREDICTION_EFFECT_TYPES

#: rc-1.1.0: the Hypothesis Engine's contract says where a prediction's outcome space comes from
#: (the pair as given in CONTEXT.outcome_spaces, never one named from the evidence).
#: rc-2.0.0: a prediction's observable_ref, outcome_space_id and outcome_space_version are copied
#: together from one entry of CONTEXT.prediction_bindings (prompt 3.0.0).
#: rc-3.0.0: every prediction has a key, and every hypothesis designates its typed falsifier --
#: `falsifier_prediction_keys`, keys of its own CONTRADICTS predictions (prompt 4.0.0).
#: rc-4.0.0: the relation effects are no longer bare names. SUPPORTS is the only support and
#: CONTRADICTS the only refutation; PREDICTS and TESTS are neither; SUPPORTS may be absent; an
#: outcome takes one effect per hypothesis, as the parser now enforces (prompt 5.0.0).
#: rc-5.0.0: the specialist and the critic name hypotheses and evidence by the short aliases they
#: are shown (`H1`, `E1`, ...), never by canonical ids they would have to copy; the coverage review
#: has a contract; every contract has a JSON schema, sent as `response_format` (`SCHEMAS`).
#: rc-6.0.0: the screening review has a contract and a schema (`ROLE_SCREENING_REVIEW`); before it,
#: a screening review call carried neither -- no system contract, no response_format.
RESPONSE_CONTRACT_VERSION = "rc-6.0.0"

#: Where a rendered context block begins (`cognition.llm._render`).
CONTEXT_MARKER = "\n\nCONTEXT:\n"

_BARE = (
    "Respond with ONE JSON object and nothing else: no prose before or after it, no code fences. "
    "Use only facts and identifiers given in CONTEXT. "
)

#: How a role names what CONTEXT shows it: the short reference, exactly as given.
_REFS = (
    "Every hypothesis_id and attestation_id in CONTEXT is a short reference such as H1 or E2; "
    "name hypotheses and evidence by exactly those references, as given -- never a longer, "
    "shortened, re-cased or invented one. "
)


def _choices(values: object) -> str:
    return "|".join(sorted(str(getattr(v, "value", v)) for v in values))  # type: ignore[attr-defined]


QUERY_CONTRACT = _BARE + (
    'Shape: {"terms": ["<search term>", ...]} with at least one non-empty term. When '
    'CONTEXT.mode is "INVERTED", give the terms that would find evidence CONTRADICTING the stated '
    "falsifiers."
)

HYPOTHESIS_CONTRACT = _BARE + (
    'Shape: {"hypotheses": [{"key": "<short unique id>", "statement": "<text>", '
    '"mechanism": "<short mechanism name>", "assumptions": ["<text>", ...], '
    '"falsifier": "<observation that would refute it>", '
    '"falsifier_prediction_keys": ["<key of one of this hypothesis\'s CONTRADICTS predictions>", '
    '...], "confounders": ["<text>", ...], '
    '"minimal_test_ref": "<the cheapest test or capability id that could refute it>", '
    '"predictions": [{"key": "<short id, unique within this hypothesis>", '
    '"observable_ref": "<an observable_ref from CONTEXT.prediction_bindings>", '
    '"outcome_space_id": "<that entry\'s outcome_space_id>", '
    '"outcome_space_version": "<that entry\'s outcome_space_version>", '
    '"expected_outcome": "<one of that entry\'s outcomes, verbatim>", '
    f'"relation_effect": "<{_choices(PREDICTION_EFFECT_TYPES)}>", '
    '"direction": "<optional>"}]}], '
    '"position": {"mechanism_view": "<your view>", "uncertainties": ["<text>", ...], '
    '"confounders": ["<text>", ...]}}. '
    "Give at least CONTEXT.minimum_hypotheses competing hypotheses with distinct keys and distinct "
    "mechanisms; every hypothesis needs at least one prediction over an entry of "
    "CONTEXT.prediction_bindings; lists may be empty but must be lists of non-empty strings. "
    "Copy each prediction's observable_ref, outcome_space_id and outcome_space_version together, "
    "exactly as one entry of CONTEXT.prediction_bindings gives them, and its expected_outcome "
    "from that entry's outcomes; an outcome_space_id is never an observable_ref. Never make up an "
    "observable or an outcome space or derive one from a quantity named in the evidence; if no "
    "given entry fits a prediction, make a different prediction that one does. Every hypothesis "
    "needs at least one prediction with relation_effect CONTRADICTS whose expected_outcome would "
    "refute it if observed, and falsifier_prediction_keys must list at least one such key of its "
    "own -- never a SUPPORTS, PREDICTS or TESTS prediction, and never another hypothesis's. A "
    "prediction relates only the outcome it names: an outcome no prediction names relates to "
    "nothing. A relation_effect is chosen by what observing the outcome would mean for that "
    "hypothesis, as the prompt defines each: SUPPORTS is the only effect counted as support and "
    "CONTRADICTS the only one counted as refutation; PREDICTS and TESTS are recorded and are "
    "neither. A hypothesis need not have a SUPPORTS prediction, and within one hypothesis the same "
    "outcome of the same observable takes one relation_effect."
)

SPECIALIST_CONTRACT = (
    _BARE
    + _REFS
    + (
        'Shape: {"mechanism_view": "<your independent view>", '
        '"favoured_hypothesis_ids": '
        '["<hypothesis_id values from CONTEXT.hypotheses only, e.g. H1>"], '
        '"uncertainties": ["<text>", ...], "confounders": ["<text>", ...], '
        '"proposed_predictions": [{"observable_ref": "<text>", "expected_outcome": "<text>"}]}. '
        "Never favour an id that is not in CONTEXT.hypotheses, and list each one once."
    )
)

CRITIQUE_CONTRACT = (
    _BARE
    + _REFS
    + (
        'Shape: {"objections": [{"target_id": '
        '"<a hypothesis_id from CONTEXT.hypotheses, e.g. H1>", '
        f'"kind": "<{_choices(ObjectionKind)}>", '
        f'"severity": "<{_choices(ObjectionSeverity)}>", "text": "<the objection>", '
        '"evidence_attestation_ids": '
        '["<attestation_id values from CONTEXT.evidence only, e.g. E1>"]}], '
        '"alternative_mechanisms": ["<mechanism no hypothesis covers>", ...], '
        '"falsifier_challenges": [{"target_id": "<a hypothesis_id>", "text": "<text>"}]}. '
        "kind and severity are separate fields, each one of the values listed for it. "
        "Cite only attestation ids present in CONTEXT.evidence; a CONTRADICTS objection must cite "
        "at least one. You do not decide which hypothesis is true."
    )
)

COVERAGE_CONTRACT = (
    _BARE
    + _REFS
    + (
        'Shape: {"hypotheses": [<a complete hypothesis certificate exactly as the Hypothesis '
        "Engine writes one -- key, statement, mechanism, assumptions, falsifier, "
        "falsifier_prediction_keys, confounders, minimal_test_ref, predictions -- plus "
        '"grounding_evidence_ids": ["<attestation_id values from CONTEXT.evidence, e.g. E1>", '
        '...]>], "declined": [{"observable_ref": "<the observable_ref of an entry of '
        'CONTEXT.unaddressed_checks>", "reason": "<why the evidence motivates no mechanism whose '
        'outcome there would differ>", "evidence_ids": ["<optional attestation_id values>"]}]}. '
        "Answer every entry of CONTEXT.unaddressed_checks exactly once: either at least one new "
        "hypothesis makes a SUPPORTS or CONTRADICTS prediction over its observable_ref, or it is "
        "declined. Either list may be empty. A new hypothesis's mechanism differs from every one "
        "in CONTEXT.existing_mechanisms and cites at least one grounding evidence id; its "
        "predictions copy observable_ref, outcome_space_id and outcome_space_version together from "
        "one entry of CONTEXT.prediction_bindings, with an expected_outcome from that entry's "
        "outcomes, and it designates at least one of its own CONTRADICTS predictions in "
        "falsifier_prediction_keys."
    )
)

SCREENING_CONTRACT = (
    _BARE
    + _REFS
    + (
        'Shape: {"hypotheses": [<a complete hypothesis certificate exactly as the Hypothesis '
        "Engine writes one -- key, statement, mechanism, assumptions, falsifier, "
        "falsifier_prediction_keys, confounders, minimal_test_ref, predictions -- plus "
        '"responds_to": ["<observation_ref values of ABNORMAL entries of '
        'CONTEXT.screening_observations, e.g. O1>", ...], "grounding_evidence_ids": '
        '["<attestation_id values from CONTEXT.evidence, e.g. E1>", ...]>], "declined": '
        '[{"observation_ref": "<an ABNORMAL entry\'s observation_ref>", "reason": "<why no new '
        'mechanism is proposed for it>"}]}. Answer every ABNORMAL reading exactly once: either '
        "one new hypothesis lists it in responds_to and makes a SUPPORTS or CONTRADICTS "
        "prediction over its observable_ref, or it is declined. Never respond to a NORMAL "
        "reading. A new hypothesis's mechanism differs from every one in "
        "CONTEXT.existing_mechanisms; its grounding_evidence_ids cite CONTEXT.evidence items that "
        "share words with what it states, never an observation ref; its predictions copy "
        "observable_ref, outcome_space_id and outcome_space_version together from one entry of "
        "CONTEXT.prediction_bindings, and it designates at least one of its own CONTRADICTS "
        "predictions in falsifier_prediction_keys."
    )
)

#: Every contract, by the role it serves. Its digest is part of every locked route's fingerprint.
CONTRACTS: Mapping[str, str] = {
    "ROLE_QUERY": QUERY_CONTRACT,
    "ROLE_HYPOTHESIS": HYPOTHESIS_CONTRACT,
    "ROLE_SPECIALIST": SPECIALIST_CONTRACT,
    "ROLE_CRITIQUE": CRITIQUE_CONTRACT,
    "ROLE_COVERAGE_REVIEW": COVERAGE_CONTRACT,
    "ROLE_SCREENING_REVIEW": SCREENING_CONTRACT,
}

# -- the schemas -------------------------------------------------------------------------------


def _str() -> dict[str, Any]:
    return {"type": "string"}


def _strs() -> dict[str, Any]:
    return {"type": "array", "items": _str()}


def _enum(values: object) -> dict[str, Any]:
    return {"type": "string", "enum": sorted(_choices(values).split("|"))}


def _object(properties: Mapping[str, Any], required: tuple[str, ...]) -> dict[str, Any]:
    return {"type": "object", "properties": dict(properties), "required": list(required)}


def _array(items: Mapping[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": dict(items)}


_PREDICTION = _object(
    {
        "key": _str(),
        "observable_ref": _str(),
        "outcome_space_id": _str(),
        "outcome_space_version": _str(),
        "expected_outcome": _str(),
        "relation_effect": _enum(PREDICTION_EFFECT_TYPES),
        "direction": _str(),
    },
    (
        "key",
        "observable_ref",
        "outcome_space_id",
        "outcome_space_version",
        "expected_outcome",
        "relation_effect",
    ),
)
_CERTIFICATE: dict[str, Any] = {
    "key": _str(),
    "statement": _str(),
    "mechanism": _str(),
    "assumptions": _strs(),
    "falsifier": _str(),
    "falsifier_prediction_keys": _strs(),
    "confounders": _strs(),
    "minimal_test_ref": _str(),
    "predictions": _array(_PREDICTION),
}

#: Each contract's JSON schema, under the same key. Constant, and digested with the contracts.
SCHEMAS: Mapping[str, Mapping[str, Any]] = {
    "ROLE_QUERY": _object({"terms": _strs()}, ("terms",)),
    "ROLE_HYPOTHESIS": _object(
        {
            "hypotheses": _array(_object(_CERTIFICATE, tuple(_CERTIFICATE))),
            "position": _object(
                {"mechanism_view": _str(), "uncertainties": _strs(), "confounders": _strs()},
                ("mechanism_view",),
            ),
        },
        ("hypotheses", "position"),
    ),
    "ROLE_SPECIALIST": _object(
        {
            "mechanism_view": _str(),
            "favoured_hypothesis_ids": _strs(),
            "uncertainties": _strs(),
            "confounders": _strs(),
            "proposed_predictions": _array(
                _object(
                    {"observable_ref": _str(), "expected_outcome": _str()},
                    ("observable_ref", "expected_outcome"),
                )
            ),
        },
        ("mechanism_view", "favoured_hypothesis_ids"),
    ),
    "ROLE_CRITIQUE": _object(
        {
            "objections": _array(
                _object(
                    {
                        "target_id": _str(),
                        "kind": _enum(ObjectionKind),
                        "severity": _enum(ObjectionSeverity),
                        "text": _str(),
                        "evidence_attestation_ids": _strs(),
                    },
                    ("target_id", "kind", "severity", "text", "evidence_attestation_ids"),
                )
            ),
            "alternative_mechanisms": _strs(),
            "falsifier_challenges": _array(
                _object({"target_id": _str(), "text": _str()}, ("target_id", "text"))
            ),
        },
        ("objections", "alternative_mechanisms", "falsifier_challenges"),
    ),
    "ROLE_COVERAGE_REVIEW": _object(
        {
            "hypotheses": _array(
                _object(
                    {**_CERTIFICATE, "grounding_evidence_ids": _strs()},
                    (*_CERTIFICATE, "grounding_evidence_ids"),
                )
            ),
            "declined": _array(
                _object(
                    {"observable_ref": _str(), "reason": _str(), "evidence_ids": _strs()},
                    ("observable_ref", "reason"),
                )
            ),
        },
        ("hypotheses", "declined"),
    ),
    "ROLE_SCREENING_REVIEW": _object(
        {
            "hypotheses": _array(
                _object(
                    {**_CERTIFICATE, "responds_to": _strs(), "grounding_evidence_ids": _strs()},
                    (*_CERTIFICATE, "responds_to", "grounding_evidence_ids"),
                )
            ),
            "declined": _array(
                _object(
                    {"observation_ref": _str(), "reason": _str()}, ("observation_ref", "reason")
                )
            ),
        },
        ("hypotheses", "declined"),
    ),
}


def contract_digest(
    contracts: Mapping[str, str],
    version: str = RESPONSE_CONTRACT_VERSION,
    schemas: Mapping[str, Mapping[str, Any]] = SCHEMAS,
) -> str:
    """The digest of a set of contracts and their schemas under a contract version: what a
    qualification names."""
    return hashlib.sha256(
        json.dumps(
            {
                "version": version,
                "contracts": dict(contracts),
                "schemas": {k: dict(v) for k, v in schemas.items()},
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


CONTRACT_DIGEST = contract_digest(CONTRACTS)


def role_of(material: str) -> str | None:
    """The contract key for the role this prompt speaks to; `None` for a prompt of no known role.

    Core roles are recognised by their versioned template, which every call begins with; a domain
    specialist (whose template the DomainPack writes) by the `specialist` field of its context.
    """
    for template, key in (
        (QUERY_REWRITER.prompt.template, "ROLE_QUERY"),
        (HYPOTHESIS_ENGINE.prompt.template, "ROLE_HYPOTHESIS"),
        (ADVERSARIAL_CRITIC.prompt.template, "ROLE_CRITIQUE"),
        (COVERAGE_REVIEW.prompt.template, "ROLE_COVERAGE_REVIEW"),
        (SCREENING_REVIEW.prompt.template, "ROLE_SCREENING_REVIEW"),
    ):
        if material.startswith(template):
            return key
    if CONTEXT_MARKER in material:
        try:
            context = json.loads(material.split(CONTEXT_MARKER, 1)[1])
        except ValueError:
            return None
        if isinstance(context, dict) and "specialist" in context:
            return "ROLE_SPECIALIST"
    return None


def contract_for(material: str) -> str | None:
    """The contract for the role this prompt speaks to; `None` for a prompt of no known role."""
    key = role_of(material)
    return None if key is None else CONTRACTS[key]


def schema_for(material: str) -> tuple[str, Mapping[str, Any]] | None:
    """(name, JSON schema) for the role this prompt speaks to; `None` for no known role."""
    key = role_of(material)
    return None if key is None else (key.lower(), SCHEMAS[key])


__all__ = [
    "CONTEXT_MARKER",
    "CONTRACTS",
    "CONTRACT_DIGEST",
    "COVERAGE_CONTRACT",
    "CRITIQUE_CONTRACT",
    "HYPOTHESIS_CONTRACT",
    "QUERY_CONTRACT",
    "RESPONSE_CONTRACT_VERSION",
    "SCHEMAS",
    "SCREENING_CONTRACT",
    "SPECIALIST_CONTRACT",
    "contract_digest",
    "contract_for",
    "role_of",
    "schema_for",
]
