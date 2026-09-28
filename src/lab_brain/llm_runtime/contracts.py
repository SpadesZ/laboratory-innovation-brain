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

The catalog reasoner never receives it: it is not a model and does not need to be told.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from lab_brain.cognition.roles import ADVERSARIAL_CRITIC, HYPOTHESIS_ENGINE, QUERY_REWRITER
from lab_brain.core.models.debate import ObjectionKind, ObjectionSeverity
from lab_brain.core.models.prediction import PREDICTION_EFFECT_TYPES

RESPONSE_CONTRACT_VERSION = "rc-1.0.0"

#: Where a rendered context block begins (`cognition.llm._render`).
CONTEXT_MARKER = "\n\nCONTEXT:\n"

_BARE = (
    "Respond with ONE JSON object and nothing else: no prose before or after it, no code fences. "
    "Use only facts and identifiers given in CONTEXT. "
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
    '"falsifier": "<observation that would refute it>", "confounders": ["<text>", ...], '
    '"minimal_test_ref": "<the cheapest test or capability id that could refute it>", '
    '"predictions": [{"observable_ref": "<what is observed>", '
    '"outcome_space_id": "<an outcome_space_id from CONTEXT.outcome_spaces>", '
    '"outcome_space_version": "<that space\'s version>", '
    '"expected_outcome": "<one of that space\'s outcomes, verbatim>", '
    f'"relation_effect": "<{_choices(PREDICTION_EFFECT_TYPES)}>", '
    '"direction": "<optional>"}]}], '
    '"position": {"mechanism_view": "<your view>", "uncertainties": ["<text>", ...], '
    '"confounders": ["<text>", ...]}}. '
    "Give at least CONTEXT.minimum_hypotheses competing hypotheses with distinct keys and distinct "
    "mechanisms; every hypothesis needs at least one prediction over a space in "
    "CONTEXT.outcome_spaces; lists may be empty but must be lists of non-empty strings."
)

SPECIALIST_CONTRACT = _BARE + (
    'Shape: {"mechanism_view": "<your independent view>", '
    '"favoured_hypothesis_ids": ["<hypothesis_id values from CONTEXT.hypotheses only>"], '
    '"uncertainties": ["<text>", ...], "confounders": ["<text>", ...], '
    '"proposed_predictions": [{"observable_ref": "<text>", "expected_outcome": "<text>"}]}. '
    "Never favour an id that is not in CONTEXT.hypotheses."
)

CRITIQUE_CONTRACT = _BARE + (
    'Shape: {"objections": [{"target_id": "<a hypothesis_id from CONTEXT.hypotheses>", '
    f'"kind": "<{_choices(ObjectionKind)}>", '
    f'"severity": "<{_choices(ObjectionSeverity)}>", "text": "<the objection>", '
    '"evidence_attestation_ids": ["<attestation_id values from CONTEXT.evidence only>"]}], '
    '"alternative_mechanisms": ["<mechanism no hypothesis covers>", ...], '
    '"falsifier_challenges": [{"target_id": "<a hypothesis_id>", "text": "<text>"}]}. '
    "Cite only attestation ids present in CONTEXT.evidence; a CONTRADICTS objection must cite at "
    "least one. You do not decide which hypothesis is true."
)

#: Every contract, by the role it serves. Its digest is part of every locked route's fingerprint.
CONTRACTS: Mapping[str, str] = {
    "ROLE_QUERY": QUERY_CONTRACT,
    "ROLE_HYPOTHESIS": HYPOTHESIS_CONTRACT,
    "ROLE_SPECIALIST": SPECIALIST_CONTRACT,
    "ROLE_CRITIQUE": CRITIQUE_CONTRACT,
}

CONTRACT_DIGEST = hashlib.sha256(
    json.dumps(
        {"version": RESPONSE_CONTRACT_VERSION, "contracts": dict(CONTRACTS)},
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")
).hexdigest()


def contract_for(material: str) -> str | None:
    """The contract for the role this prompt speaks to; `None` for a prompt of no known role.

    Core roles are recognised by their versioned template, which every call begins with; a domain
    specialist (whose template the DomainPack writes) by the `specialist` field of its context.
    """
    for template, contract in (
        (QUERY_REWRITER.prompt.template, QUERY_CONTRACT),
        (HYPOTHESIS_ENGINE.prompt.template, HYPOTHESIS_CONTRACT),
        (ADVERSARIAL_CRITIC.prompt.template, CRITIQUE_CONTRACT),
    ):
        if material.startswith(template):
            return contract
    if CONTEXT_MARKER in material:
        try:
            context = json.loads(material.split(CONTEXT_MARKER, 1)[1])
        except ValueError:
            return None
        if isinstance(context, dict) and "specialist" in context:
            return SPECIALIST_CONTRACT
    return None


__all__ = [
    "CONTEXT_MARKER",
    "CONTRACTS",
    "CONTRACT_DIGEST",
    "CRITIQUE_CONTRACT",
    "HYPOTHESIS_CONTRACT",
    "QUERY_CONTRACT",
    "RESPONSE_CONTRACT_VERSION",
    "SPECIALIST_CONTRACT",
    "contract_for",
]
