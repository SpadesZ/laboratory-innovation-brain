"""§7.4's Cognitive Role I/O Contract: what each role is given, and what it must hand back.

    §7    角色之間**只**透過有 schema 的物件溝通。
    §7.4  Hypothesis Engine   EvidenceBundle + open unknowns -> 2+ competing Hypothesis
                              Certificates
          Adversarial Critic  All positions + hypotheses + evidence map -> CritiqueReport,
                              falsifiers, missing controls; read-only on evidence
          Domain Specialist   Question + selected claims/hypotheses + domain evidence -> independent
                              Position + predictions/confounders
          Novelty Auditor     Sanitized surviving concept -> prior-art matrix + novelty status +
                              PriorArtSearchRecord
    §26.1 M3 exit gate: role I/O + Position/Critique contracts pass.

A MODEL'S REPLY IS UNTRUSTED INPUT, AND EACH ROLE'S PARSER IS ITS BOUNDARY. A role's output is JSON
text from a model; it becomes a typed object only after the parser here has checked it against the
role's contract. What each parser refuses is the shape a model would use to exceed its role:

    Hypothesis Engine   fewer than two proposals; a proposal missing a certificate field; a
                        prediction over an OutcomeSpace it was not shown, or an outcome outside it;
                        a falsifier not designated as one of its own CONTRADICTS predictions
    Domain Specialist   favouring a hypothesis that is not under consideration (a specialist does
                        not add rivals -- that is the Hypothesis Engine's job)
    Adversarial Critic  an objection to something that is not a target; citing an attestation it
                        was NOT shown (inventing evidence is the one thing §7.1 forbids every
                        role); a contradiction with no citation (`Objection` refuses that itself)
    Novelty Auditor     a matrix row naming a record the search did not return

A REFUSED OUTPUT IS STILL A DURABLE INFERENCE. The model was called and `ScientificInferenceService`
recorded what it said before the parser saw it; refusing the output means no typed object is built
from it -- no Position, no certificate, no critique -- not that the call is forgotten.

INPUTS ARE CHECKED TOO. `require_input` refuses a context missing a key the role's contract says it
receives: a critic handed no evidence map, or a specialist handed no hypotheses, would produce an
output whose absence of a citation meant nothing.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from lab_brain.cognition.aliases import resolve
from lab_brain.cognition.llm import PromptTemplate
from lab_brain.cognition.routing import CognitiveRole
from lab_brain.core.models.debate import (
    FalsifierChallenge,
    Objection,
    ObjectionKind,
    ObjectionSeverity,
    ProposedPrediction,
)
from lab_brain.core.models.enums import RelationType
from lab_brain.core.models.prediction import (
    PREDICTION_EFFECT_MEANINGS,
    PREDICTION_EFFECT_TYPES,
    OutcomeSpace,
)
from lab_brain.core.models.prior_art import (
    NoveltyScope,
    NoveltyStatus,
    PriorArtMatch,
    PriorArtOverlap,
)


class RoleOutputRefused(RuntimeError):
    """A role's output (or input) violates its §7.4 contract. No typed object is built from it."""

    def __init__(self, role: str, detail: str, *, inference_id: str | None = None) -> None:
        where = f" (inference {inference_id})" if inference_id else ""
        super().__init__(f"{role}{where}: {detail}")
        self.role = role
        self.detail = detail
        self.inference_id = inference_id


@dataclass(frozen=True)
class RoleContract:
    role: CognitiveRole
    prompt: PromptTemplate
    #: Context keys the role's input contract requires.
    requires: frozenset[str]


def effect_meanings() -> str:
    """The prediction effects and what each means, as the Hypothesis Engine is told them."""
    return " ".join(
        f"{effect.value} means: {meaning}."
        for effect, meaning in PREDICTION_EFFECT_MEANINGS.items()
    )


#: 2.0.0: the count is the CONTEXT's (`minimum_hypotheses`), never a number in the prompt. 1.0.0
#: said "at least two" while the context -- and the parser -- demanded the caller's minimum (a
#: domain's Stage A asks for one per catalogued mechanism; a later round may ask for one), so a
#: model was told two different counts at once.
#: 2.1.0: the binding rule is said, not only enforced. A model given several outcome spaces bound a
#: prediction to one it named itself from a quantity in the evidence; the parser refused it
#: (VER-004), as it still does -- the prompt now says where every space id and outcome comes from.
#: 3.0.0: the context's `prediction_bindings` replace `outcome_spaces`. A prediction's observable is
#: a canonical identifier the verification planner matches exactly, so the engine is shown the
#: domain's declared observable -> space bindings and copies the observable with its space; a model
#: shown only spaces wrote a space id where the observable belongs, and no check could match it.
#: 4.0.0: the falsifier is typed. Every prediction carries a key, and each certificate designates
#: (`falsifier_prediction_keys`) at least one of its own CONTRADICTS predictions as its falsifier. A
#: model that wrote a prose falsifier and only SUPPORTS predictions left an observed falsifying
#: outcome with nothing to relate to: no relation is ever inferred from a mismatch.
#: 5.0.0: the relation effects are defined (`PREDICTION_EFFECT_MEANINGS`). A model that was only
#: given their names declared a discriminating forecast as PREDICTS; the check observed it, the
#: PREDICTS relation was recorded, and no policy could count it as support -- correctly, and the
#: model was never told. The prompt now says what each effect means, that SUPPORTS is earned by
#: discrimination and may be absent, and that one outcome carries one effect per hypothesis.
HYPOTHESIS_ENGINE = RoleContract(
    role=CognitiveRole.HYPOTHESIS_ENGINE,
    prompt=PromptTemplate(
        "prm:hypothesis-engine",
        "5.0.0",
        "You are the Hypothesis Engine. From ONLY the evidence given, propose at least "
        "CONTEXT.minimum_hypotheses competing mechanisms -- never fewer -- as complete hypothesis "
        "certificates -- statement, mechanism, assumptions, falsifier, confounders, minimal test "
        "and typed predictions -- and your position. Bind every prediction to one entry of "
        "CONTEXT.prediction_bindings: copy that entry's observable_ref, outcome_space_id and "
        "outcome_space_version exactly, together, and its expected_outcome verbatim from that "
        "entry's outcomes. An outcome_space_id is not an observable_ref. Never invent or infer an "
        "observable or an outcome space from the evidence, even when the evidence names a quantity "
        "that sounds like one. Make every falsifier checkable: each hypothesis has at least one "
        "prediction with relation_effect CONTRADICTS whose expected_outcome is an outcome that "
        "would refute it, and lists that prediction's key in falsifier_prediction_keys. A "
        "prediction relates only the outcome it names; an outcome no prediction names relates to "
        "nothing. Choose each prediction's relation_effect by what observing its expected_outcome "
        f"would mean for THIS hypothesis. {effect_meanings()} Declare SUPPORTS only for an "
        "outcome that would discriminate the hypothesis from its rivals; when no declared outcome "
        "would, give it falsifiers only -- never a SUPPORTS it has not earned. An outcome has one "
        "meaning for a hypothesis: never declare the same outcome of an observable with different "
        "relation effects. Reply with JSON.",
    ),
    requires=frozenset({"question", "evidence", "prediction_bindings", "minimum_hypotheses"}),
)


def binding_context(bindings: Mapping[str, OutcomeSpace]) -> list[dict[str, object]]:
    """A domain's prediction vocabulary as the Hypothesis Engine is shown it: per declared
    observable, the space it is read in and that space's outcomes."""
    return [
        {
            "observable_ref": observable,
            "outcome_space_id": space.outcome_space_id,
            "outcome_space_version": space.version,
            "outcomes": list(space.outcomes),
            "action_type": space.action_type,
        }
        for observable, space in sorted(bindings.items())
    ]


ADVERSARIAL_CRITIC = RoleContract(
    role=CognitiveRole.ADVERSARIAL_CRITIC,
    prompt=PromptTemplate(
        "prm:adversarial-critic",
        "1.0.0",
        "You are the Adversarial Critic. Attack the assumptions, confounders, causal gaps and "
        "falsifiers of the hypotheses given, citing ONLY evidence from the evidence map by id. "
        "Name alternative mechanisms the evidence supports that no hypothesis covers. You do not "
        "decide which hypothesis is true. Reply with JSON.",
    ),
    requires=frozenset({"question", "hypotheses", "positions", "evidence"}),
)

QUERY_REWRITER = RoleContract(
    role=CognitiveRole.EVIDENCE_RESEARCHER,
    prompt=PromptTemplate(
        "prm:evidence-query-rewrite",
        "1.0.0",
        "You are the Evidence Researcher's query rewriter. Return the search terms that would find "
        "the evidence the question needs -- or, when asked for inverted retrieval, the evidence "
        "that would contradict the stated falsifiers. Reply with JSON.",
    ),
    requires=frozenset({"question", "mode"}),
)

NOVELTY_AUDITOR = RoleContract(
    role=CognitiveRole.NOVELTY_AUDITOR,
    prompt=PromptTemplate(
        "prm:novelty-auditor",
        "1.0.0",
        "You are the Novelty Auditor. Compare the sanitized concept with the prior-art records "
        "given, one matrix row per record, and state known / partially novel / novelty candidate "
        "and whether the coverage was internal or global. Reply with JSON.",
    ),
    requires=frozenset({"concept", "records", "coverage"}),
)

CORE_CONTRACTS: tuple[RoleContract, ...] = (
    HYPOTHESIS_ENGINE,
    ADVERSARIAL_CRITIC,
    QUERY_REWRITER,
    NOVELTY_AUDITOR,
)

SPECIALIST_REQUIRES = frozenset({"question", "hypotheses", "evidence", "specialist"})


def core_prompts() -> tuple[PromptTemplate, ...]:
    return (
        *(contract.prompt for contract in CORE_CONTRACTS),
        COVERAGE_REVIEW.prompt,
        SCREENING_REVIEW.prompt,
    )


def require_input(role: str, requires: frozenset[str], context: Mapping[str, object]) -> None:
    missing = sorted(requires - set(context))
    if missing:
        raise RoleOutputRefused(
            role,
            f"the input is missing {missing}; §7.4 fixes what a role receives, and a role given "
            "less than its contract says would produce output whose omissions mean nothing",
        )


#: The one envelope `normalize_reply` removes: the whole reply is ONE fenced block.
_FENCED = re.compile(r"\A```[A-Za-z]*[ \t]*\r?\n(.*)\r?\n```\Z", re.DOTALL)
STRIPPED_CODE_FENCE = "STRIPPED_CODE_FENCE"
STRIPPED_BYTE_ORDER_MARK = "STRIPPED_BYTE_ORDER_MARK"


def normalize_reply(text: str) -> tuple[str, str | None]:
    """The reply a parser reads, and the name of the repair made to get it (`None`: none).

    ONE DETERMINISTIC REPAIR, AND ONLY OF THE ENVELOPE. A reply that is entirely one Markdown code
    block (```json ... ```) is read as the block's content -- a real model sent exactly that and its
    hypotheses were otherwise well formed. Nothing inside the JSON is ever touched: no field is
    renamed, defaulted, truncated or completed, so a parser still refuses everything it refused. The
    raw reply stays the durable record; the caller records the repair beside it.
    """
    stripped = text.strip()
    marked = stripped.startswith("\ufeff")
    stripped = stripped.lstrip("\ufeff").strip()
    fenced = _FENCED.match(stripped)
    if fenced is not None:
        return fenced.group(1).strip(), STRIPPED_CODE_FENCE
    return stripped, STRIPPED_BYTE_ORDER_MARK if marked else None


def _list_field(
    role: str, obj: Mapping[str, Any], name: str, inference_id: str | None
) -> list[Any]:
    """A list field: absent or null reads as empty, anything that is not a list is refused --
    an empty string, a number or `false` is not "none" said another way."""
    value = obj.get(name)
    if value is None:
        return []
    if not isinstance(value, list):
        raise RoleOutputRefused(role, f"{name} must be a list", inference_id=inference_id)
    return value


def _object(role: str, text: str, inference_id: str | None) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, TypeError) as exc:
        raise RoleOutputRefused(
            role, f"the output is not JSON ({exc})", inference_id=inference_id
        ) from exc
    if not isinstance(value, dict):
        raise RoleOutputRefused(role, "the output is not a JSON object", inference_id=inference_id)
    return value


def _strings(role: str, value: object, name: str, inference_id: str | None) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise RoleOutputRefused(
            role, f"{name} must be a list of non-empty strings", inference_id=inference_id
        )
    return tuple(value)


def _text(role: str, obj: Mapping[str, Any], name: str, inference_id: str | None) -> str:
    value = obj.get(name)
    if not isinstance(value, str) or not value.strip():
        raise RoleOutputRefused(role, f"{name} is missing or blank", inference_id=inference_id)
    return value


# -- Evidence Researcher (FAST_UTILITY query rewrite) -----------------------------------------


def parse_query_terms(text: str, *, inference_id: str | None = None) -> tuple[str, ...]:
    obj = _object(QUERY_REWRITER.role.value, text, inference_id)
    terms = _strings(QUERY_REWRITER.role.value, obj.get("terms"), "terms", inference_id)
    if not terms:
        raise RoleOutputRefused(
            QUERY_REWRITER.role.value, "no search terms were returned", inference_id=inference_id
        )
    return terms


# -- Hypothesis Engine --------------------------------------------------------------------------


@dataclass(frozen=True)
class PredictionProposal:
    #: Unique within its hypothesis: what `falsifier_prediction_keys` names.
    key: str
    observable_ref: str
    outcome_space_id: str
    outcome_space_version: str
    expected_outcome: str
    relation_effect: RelationType
    direction: str | None = None


@dataclass(frozen=True)
class HypothesisProposal:
    key: str
    statement: str
    mechanism: str
    assumptions: tuple[str, ...]
    #: Prose, for explanation and the Critic's inverted retrieval.
    falsifier: str
    confounders: tuple[str, ...]
    minimal_test_ref: str
    predictions: tuple[PredictionProposal, ...]
    #: The typed falsifier: keys of this hypothesis's own CONTRADICTS predictions, at least one.
    falsifier_prediction_keys: tuple[str, ...]


@dataclass(frozen=True)
class PositionDraft:
    mechanism_view: str
    favoured: tuple[str, ...] = ()
    uncertainties: tuple[str, ...] = ()
    confounders: tuple[str, ...] = ()
    proposed_predictions: tuple[ProposedPrediction, ...] = ()


def parse_hypothesis_engine(
    text: str,
    *,
    bindings: Mapping[str, OutcomeSpace],
    minimum: int,
    inference_id: str | None = None,
) -> tuple[tuple[HypothesisProposal, ...], PositionDraft]:
    """§7.4: EvidenceBundle + open unknowns -> 2+ competing Hypothesis Certificates.

    ``minimum`` is 2 for Stage A (EPI-001) and may be 1 when a later round asks the engine to
    certify an alternative the Critic named. It is never 0: a round that asked for hypotheses and
    received none would record a debate that did not happen.

    ``bindings`` is the domain's prediction vocabulary (observable_ref -> the declared space it is
    read in), exactly as the engine was shown it. A prediction is admitted only over a declared
    (observable, space id, version) binding with an outcome that space admits: the planner matches
    the observable to what a capability produces, exactly, so an observable that is not canonical
    would be a prediction nothing could ever check.

    Every certificate carries a TYPED falsifier: `falsifier_prediction_keys` names at least one of
    its own predictions, each with relation_effect CONTRADICTS. A belief moves only by a relation a
    prediction declared before the check ran -- never one inferred from an outcome that merely
    differs from a SUPPORTS prediction -- so a falsifier that is only prose could never refute
    anything. A CONTRADICTS prediction that is not designated does not count, and neither does a
    designation of another hypothesis's prediction or of one that does not contradict.

    A hypothesis gives each outcome of an observable at most one relation effect. No SUPPORTS
    prediction is required: a certificate whose only typed content is its falsifiers is admitted,
    because support is earned by an outcome that discriminates, and none may be declared.
    """
    role = HYPOTHESIS_ENGINE.role.value
    obj = _object(role, text, inference_id)
    raw = obj.get("hypotheses")
    if not isinstance(raw, list) or len(raw) < max(1, minimum):
        raise RoleOutputRefused(
            role,
            f"expected at least {max(1, minimum)} hypotheses, got "
            f"{len(raw) if isinstance(raw, list) else 'none'}. §7.4: the Hypothesis Engine returns "
            "2+ COMPETING certificates, and EPI-001 counts them",
            inference_id=inference_id,
        )
    proposals = _proposals(role, raw, bindings, inference_id)
    position_raw = obj.get("position")
    if not isinstance(position_raw, dict):
        raise RoleOutputRefused(role, "the engine states no position", inference_id=inference_id)
    position = PositionDraft(
        mechanism_view=_text(role, position_raw, "mechanism_view", inference_id),
        uncertainties=_strings(
            role, position_raw.get("uncertainties", []), "uncertainties", inference_id
        ),
        confounders=_strings(
            role, position_raw.get("confounders", []), "confounders", inference_id
        ),
    )
    return proposals, position


def _proposals(
    role: str,
    raw: Sequence[Any],
    bindings: Mapping[str, OutcomeSpace],
    inference_id: str | None,
) -> tuple[HypothesisProposal, ...]:
    """Certificates, each checked as `parse_hypothesis_engine` documents. Keys are unique."""
    proposals: list[HypothesisProposal] = []
    keys: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise RoleOutputRefused(
                role, "a hypothesis is not an object", inference_id=inference_id
            )
        key = _text(role, item, "key", inference_id)
        if key in keys:
            raise RoleOutputRefused(
                role, f"hypothesis key {key!r} repeats", inference_id=inference_id
            )
        keys.add(key)
        predictions_raw = item.get("predictions")
        if not isinstance(predictions_raw, list) or not predictions_raw:
            raise RoleOutputRefused(
                role,
                f"hypothesis {key!r} carries no typed prediction; §8.1 predictions are typed "
                "objects, not prose, and a certificate without one is not admissible",
                inference_id=inference_id,
            )
        predictions: list[PredictionProposal] = []
        for p in predictions_raw:
            if not isinstance(p, dict):
                raise RoleOutputRefused(
                    role, "a prediction is not an object", inference_id=inference_id
                )
            prediction_key = p.get("key")
            if not isinstance(prediction_key, str) or not prediction_key.strip():
                raise RoleOutputRefused(
                    role,
                    f"hypothesis {key!r} has a prediction with no key; every prediction carries a "
                    "key unique within its hypothesis, so that a falsifier can name it",
                    inference_id=inference_id,
                )
            if any(q.key == prediction_key for q in predictions):
                raise RoleOutputRefused(
                    role,
                    f"hypothesis {key!r} repeats prediction key {prediction_key!r}",
                    inference_id=inference_id,
                )
            observable = _text(role, p, "observable_ref", inference_id)
            space_key = (
                _text(role, p, "outcome_space_id", inference_id),
                _text(role, p, "outcome_space_version", inference_id),
            )
            if space_key not in {(s.outcome_space_id, s.version) for s in bindings.values()}:
                raise RoleOutputRefused(
                    role,
                    f"hypothesis {key!r} predicts over outcome space "
                    f"{space_key[0]}@{space_key[1]}, "
                    "which the engine was not shown; a prediction may only be bound to a declared "
                    "space it was given (VER-004)",
                    inference_id=inference_id,
                )
            space = bindings.get(observable)
            if space is None:
                raise RoleOutputRefused(
                    role,
                    f"hypothesis {key!r} predicts over observable {observable!r}, which is not in "
                    f"the prediction vocabulary it was given ({', '.join(sorted(bindings))}); an "
                    "observable_ref is copied from a declared binding, never made up or derived "
                    "from an outcome space id (VER-004)",
                    inference_id=inference_id,
                )
            if (space.outcome_space_id, space.version) != space_key:
                raise RoleOutputRefused(
                    role,
                    f"hypothesis {key!r} reads observable {observable!r} in "
                    f"{space_key[0]}@{space_key[1]}; it is declared in {space.ref} -- an "
                    "observable and its space are copied together (VER-004)",
                    inference_id=inference_id,
                )
            expected = _text(role, p, "expected_outcome", inference_id)
            if not space.admits(expected):
                raise RoleOutputRefused(
                    role,
                    f"hypothesis {key!r} expects {expected!r}, which {space.ref} does not admit "
                    f"({sorted(space.outcomes)}); a planner MUST NOT invent outcomes",
                    inference_id=inference_id,
                )
            effect_raw = _text(role, p, "relation_effect", inference_id)
            try:
                effect = RelationType(effect_raw)
            except ValueError:
                raise RoleOutputRefused(
                    role, f"unknown relation effect {effect_raw!r}", inference_id=inference_id
                ) from None
            if effect not in PREDICTION_EFFECT_TYPES:
                raise RoleOutputRefused(
                    role,
                    f"relation effect {effect.value} cannot move belief (§17.5.1)",
                    inference_id=inference_id,
                )
            # One observed outcome means one thing for a hypothesis. Observing an outcome declared
            # both SUPPORTS and CONTRADICTS (or forecast and refuting) would relate it both ways at
            # once, and no transition could be adjudicated from it.
            for q in predictions:
                same_outcome = (
                    q.observable_ref,
                    q.outcome_space_id,
                    q.outcome_space_version,
                    q.expected_outcome,
                ) == (observable, *space_key, expected)
                if same_outcome and q.relation_effect is not effect:
                    raise RoleOutputRefused(
                        role,
                        f"hypothesis {key!r} declares {observable} = {expected} both "
                        f"{q.relation_effect.value} and {effect.value}; an outcome has one meaning "
                        "for a hypothesis, so it carries one relation effect",
                        inference_id=inference_id,
                    )
            direction = p.get("direction")
            predictions.append(
                PredictionProposal(
                    key=prediction_key,
                    observable_ref=observable,
                    outcome_space_id=space_key[0],
                    outcome_space_version=space_key[1],
                    expected_outcome=expected,
                    relation_effect=effect,
                    direction=direction if isinstance(direction, str) else None,
                )
            )
        falsifiers = _typed_falsifier(role, key, item, predictions, inference_id)
        proposals.append(
            HypothesisProposal(
                key=key,
                statement=_text(role, item, "statement", inference_id),
                mechanism=_text(role, item, "mechanism", inference_id),
                assumptions=_strings(role, item.get("assumptions"), "assumptions", inference_id),
                falsifier=_text(role, item, "falsifier", inference_id),
                confounders=_strings(role, item.get("confounders"), "confounders", inference_id),
                minimal_test_ref=_text(role, item, "minimal_test_ref", inference_id),
                predictions=tuple(predictions),
                falsifier_prediction_keys=falsifiers,
            )
        )
    return tuple(proposals)


def _typed_falsifier(
    role: str,
    key: str,
    item: Mapping[str, Any],
    predictions: Sequence[PredictionProposal],
    inference_id: str | None,
) -> tuple[str, ...]:
    """The certificate's designated falsifier predictions, each one of its own CONTRADICTS ones."""
    raw = item.get("falsifier_prediction_keys")
    if not isinstance(raw, list) or not raw:
        raise RoleOutputRefused(
            role,
            f"hypothesis {key!r} designates no typed falsifier: falsifier_prediction_keys must "
            "name at least one of its own predictions whose relation_effect is CONTRADICTS. The "
            "prose falsifier explains; only a designated typed prediction can refute it",
            inference_id=inference_id,
        )
    designated = tuple(
        dict.fromkeys(_strings(role, raw, "falsifier_prediction_keys", inference_id))
    )
    by_key = {p.key: p for p in predictions}
    for name in designated:
        target = by_key.get(name)
        if target is None:
            raise RoleOutputRefused(
                role,
                f"hypothesis {key!r} designates falsifier prediction {name!r}, which is not one "
                f"of its predictions ({', '.join(sorted(by_key))}); a falsifier is one of the "
                "hypothesis's own typed predictions",
                inference_id=inference_id,
            )
        if target.relation_effect is not RelationType.CONTRADICTS:
            raise RoleOutputRefused(
                role,
                f"hypothesis {key!r} designates falsifier prediction {name!r}, whose "
                f"relation_effect is {target.relation_effect.value}; a falsifier is a declared "
                "outcome that would CONTRADICT the hypothesis",
                inference_id=inference_id,
            )
    return designated


# -- Hypothesis coverage review -----------------------------------------------------------------

#: 1.0.0: one call after Stage A, only when a cheap executable check is left that no hypothesis
#: discriminates on (`cognition.coverage`). It names the GAP, never an answer: the same entries are
#: shown whatever the device turns out to be, and declining is a first-class reply.
COVERAGE_REVIEW = RoleContract(
    role=CognitiveRole.HYPOTHESIS_ENGINE,
    prompt=PromptTemplate(
        "prm:hypothesis-coverage-review",
        "1.0.0",
        "You are the Hypothesis Engine, reviewing the coverage of the competing hypotheses "
        "already proposed (CONTEXT.hypotheses). Each entry of CONTEXT.unaddressed_checks is a "
        "check that can run here at low cost -- no person, no licence seat, no money -- and "
        "whose outcome no current hypothesis makes a SUPPORTS or CONTRADICTS prediction about. "
        "Address every entry, from ONLY the evidence given. Either certify a NEW competing "
        "hypothesis -- a mechanism the evidence makes plausible, distinct from "
        "CONTEXT.existing_mechanisms -- as a complete certificate whose typed predictions are "
        "bound to entries of CONTEXT.prediction_bindings exactly as the Hypothesis Engine binds "
        "them, at least one of them SUPPORTS or CONTRADICTS over that entry's observable_ref, "
        "with a typed CONTRADICTS falsifier, citing in grounding_evidence_ids the evidence ids "
        "that make the mechanism plausible; or decline the entry, giving the reason the evidence "
        "motivates no mechanism whose outcome there would differ. A check being cheap or "
        "available is not evidence for any mechanism: never propose a mechanism only because a "
        "check exists, and never restate or change an existing hypothesis. "
        f"{effect_meanings()} Reply with JSON.",
    ),
    requires=frozenset(
        {
            "question",
            "evidence",
            "prediction_bindings",
            "hypotheses",
            "existing_mechanisms",
            "unaddressed_checks",
        }
    ),
)

#: The effects that make a prediction discriminate: the outcome moves belief one way or the other.
DISCRIMINATING_EFFECTS = frozenset({RelationType.SUPPORTS, RelationType.CONTRADICTS})


@dataclass(frozen=True)
class CoverageDecline:
    observable_ref: str
    reason: str
    #: Canonical attestation ids the reason cites, if any.
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class CoverageDraft:
    proposals: tuple[HypothesisProposal, ...]
    #: Proposal key -> the canonical attestation ids that ground it (at least one each).
    grounding: Mapping[str, tuple[str, ...]]
    declined: tuple[CoverageDecline, ...]
    #: Proposal key -> cited attestation id -> the content words they share (when checked).
    relevance: Mapping[str, Mapping[str, tuple[str, ...]]] = field(default_factory=dict)


def parse_coverage_review(
    text: str,
    *,
    bindings: Mapping[str, OutcomeSpace],
    unaddressed: Sequence[str],
    existing_mechanisms: Sequence[str],
    evidence_refs: Mapping[str, str],
    shown_attestation_ids: Sequence[str],
    evidence_texts: Mapping[str, str] | None = None,
    inference_id: str | None = None,
) -> CoverageDraft:
    """Every unaddressed observable answered exactly once: certified by a new, grounded rival
    that discriminates on it, or declined with a reason. Anything else is refused.

    The certificates are checked as `parse_hypothesis_engine` checks them. On top: each one is a
    mechanism no hypothesis already proposes, discriminates (SUPPORTS or CONTRADICTS) on at least
    one unaddressed observable, and cites the evidence it rests on -- resolved exactly against what
    the review was shown, never invented. No hypothesis is ever required: declining every entry is
    a complete reply.
    """
    role = HYPOTHESIS_ENGINE.role.value
    obj = _object(role, text, inference_id)
    raw = _list_field(role, obj, "hypotheses", inference_id)
    declined_raw = _list_field(role, obj, "declined", inference_id)
    proposals = _proposals(role, raw, bindings, inference_id)
    gaps = tuple(dict.fromkeys(unaddressed))
    taken = {" ".join(m.lower().split()) for m in existing_mechanisms}
    covered: dict[str, str] = {}
    grounding: dict[str, tuple[str, ...]] = {}
    relevance: dict[str, Mapping[str, tuple[str, ...]]] = {}
    for proposal, item in zip(proposals, raw, strict=True):
        name = " ".join(proposal.mechanism.lower().split())
        if name in taken:
            raise RoleOutputRefused(
                role,
                f"hypothesis {proposal.key!r} proposes {proposal.mechanism!r}, which is already "
                "under consideration; a coverage review adds rivals, it does not restate them",
                inference_id=inference_id,
            )
        taken.add(name)
        addresses = sorted(
            {
                p.observable_ref
                for p in proposal.predictions
                if p.relation_effect in DISCRIMINATING_EFFECTS and p.observable_ref in gaps
            }
        )
        if not addresses:
            raise RoleOutputRefused(
                role,
                f"hypothesis {proposal.key!r} makes no SUPPORTS or CONTRADICTS prediction over an "
                f"unaddressed check ({', '.join(gaps)}); a coverage review certifies only rivals "
                "that the unaddressed checks would discriminate",
                inference_id=inference_id,
            )
        for observable in addresses:
            covered.setdefault(observable, proposal.key)
        cited = item.get("grounding_evidence_ids")
        if not isinstance(cited, list) or not cited:
            raise RoleOutputRefused(
                role,
                f"hypothesis {proposal.key!r} cites no evidence in grounding_evidence_ids; a rival "
                "proposed to cover a check must rest on evidence, never on the check existing",
                inference_id=inference_id,
            )
        grounding[proposal.key] = resolve_refs(
            role,
            _strings(role, cited, "grounding_evidence_ids", inference_id),
            shown=evidence_refs,
            allowed=shown_attestation_ids,
            what="evidence items",
            inference_id=inference_id,
        )
        relevance[proposal.key] = require_relevant_grounding(
            role, proposal, grounding[proposal.key], evidence_texts, inference_id
        )
    declined: list[CoverageDecline] = []
    for d in declined_raw:
        if not isinstance(d, dict):
            raise RoleOutputRefused(role, "a decline is not an object", inference_id=inference_id)
        observable = _text(role, d, "observable_ref", inference_id)
        if observable not in gaps:
            raise RoleOutputRefused(
                role,
                f"declines {observable!r}, which is not an unaddressed check ({', '.join(gaps)})",
                inference_id=inference_id,
            )
        if observable in covered or any(x.observable_ref == observable for x in declined):
            raise RoleOutputRefused(
                role,
                f"answers {observable!r} twice; each unaddressed check is either covered by a new "
                "hypothesis or declined, once",
                inference_id=inference_id,
            )
        cited = d.get("evidence_ids") or []
        declined.append(
            CoverageDecline(
                observable_ref=observable,
                reason=_text(role, d, "reason", inference_id),
                evidence=resolve_refs(
                    role,
                    _strings(role, cited, "evidence_ids", inference_id),
                    shown=evidence_refs,
                    allowed=shown_attestation_ids,
                    what="evidence items",
                    inference_id=inference_id,
                ),
            )
        )
    missing = [g for g in gaps if g not in covered and all(x.observable_ref != g for x in declined)]
    if missing:
        raise RoleOutputRefused(
            role,
            f"leaves {missing} unanswered; every unaddressed check is covered by a new hypothesis "
            "or declined with a reason",
            inference_id=inference_id,
        )
    return CoverageDraft(
        proposals=proposals, grounding=grounding, declined=tuple(declined), relevance=relevance
    )


# -- Grounding relevance ---------------------------------------------------------------------

#: Words that carry no mechanism: a citation sharing only these with a hypothesis is not about it.
_FUNCTION_WORD_TEXT = (
    "a an and are as at be been being but by can could did do does each for from had has have "
    "how if in into is it its may might more most no nor not of on or other our out over same "
    "shall should so some such than that the their them then there these they this those "
    "through to too under until up upon very was we were what when where which while who whom "
    "why will with would yet also both only own any all"
)
_FUNCTION_WORDS = frozenset(_FUNCTION_WORD_TEXT.split())


def content_terms(text: str) -> frozenset[str]:
    """The words of `text` that could name a mechanism: lower-cased, alphanumeric, three letters
    or more, not a function word, a plural `s` folded. Declared and deterministic; a lexical rule,
    not a judgment of meaning."""
    words = "".join(c if c.isalnum() else " " for c in text.lower()).split()
    return frozenset(
        w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w
        for w in words
        if len(w) >= 3 and w not in _FUNCTION_WORDS
    )


def shared_terms(proposal: HypothesisProposal, evidence_text: str) -> tuple[str, ...]:
    """What a cited evidence item and a proposed hypothesis have in common, word for word."""
    said = content_terms(
        " ".join(
            (
                proposal.statement,
                proposal.mechanism,
                proposal.falsifier,
                *proposal.assumptions,
                *proposal.confounders,
            )
        )
    )
    return tuple(sorted(said & content_terms(evidence_text)))


def require_relevant_grounding(
    role: str,
    proposal: HypothesisProposal,
    cited: Sequence[str],
    evidence_texts: Mapping[str, str] | None,
    inference_id: str | None,
) -> dict[str, tuple[str, ...]]:
    """Each cited evidence item -> the content terms it shares with the proposal; refused when
    NONE of them shares any. A valid evidence id that says nothing about the mechanism is a
    citation in form only. `evidence_texts` None skips the check (a caller with no texts)."""
    if evidence_texts is None:
        return {}
    overlap = {c: shared_terms(proposal, evidence_texts.get(c, "")) for c in cited}
    if not any(overlap.values()):
        raise RoleOutputRefused(
            role,
            f"hypothesis {proposal.key!r} cites {len(cited)} evidence item(s), none of which "
            "shares a single content word with its statement, mechanism, assumptions, confounders "
            "or falsifier; grounding must be evidence about the mechanism, not any valid id",
            inference_id=inference_id,
        )
    return overlap


# -- Post-screening hypothesis review ---------------------------------------------------------

#: 1.0.0: one call after a screening stage that found an ABNORMAL reading -- an outcome that differs
#: from the domain's declared reference outcome on a check no hypothesis predicted. The model is
#: shown every reading, normal and abnormal; it may propose rivals that account for the abnormal
#: ones, or decline. Whatever it proposes is recorded as conditioned on what it saw, and the
#: readings themselves can never support it.
SCREENING_REVIEW = RoleContract(
    role=CognitiveRole.HYPOTHESIS_ENGINE,
    prompt=PromptTemplate(
        "prm:hypothesis-screening-review",
        "1.0.0",
        "You are the Hypothesis Engine. Low-cost exploratory readings were taken on checks no "
        "current hypothesis (CONTEXT.hypotheses) predicted. CONTEXT.screening_observations lists "
        "every reading with the domain's reference outcome; a reading whose finding is ABNORMAL "
        "differs from that reference. For EACH abnormal reading, either propose a NEW competing "
        "hypothesis -- a mechanism distinct from CONTEXT.existing_mechanisms that would account "
        "for it -- as a complete certificate bound to CONTEXT.prediction_bindings exactly as the "
        "Hypothesis Engine binds them, with a typed CONTRADICTS falsifier and a SUPPORTS or "
        "CONTRADICTS prediction over the abnormal reading's observable_ref, listing in "
        "responds_to the observation refs it accounts for and in grounding_evidence_ids the ids "
        "of CONTEXT.evidence that make the mechanism plausible; or decline the reading with a "
        "reason. A reading you were shown can never count as support for a hypothesis proposed "
        "after it: prefer predictions over checks that have NOT been read yet, so a later, "
        "independent check can test the mechanism. Never restate an existing hypothesis, and "
        "never propose a mechanism only because a reading is unusual without evidence that makes "
        f"it plausible. {effect_meanings()} Reply with JSON.",
    ),
    requires=frozenset(
        {
            "question",
            "evidence",
            "prediction_bindings",
            "hypotheses",
            "existing_mechanisms",
            "screening_observations",
        }
    ),
)


@dataclass(frozen=True)
class ScreeningDecline:
    observation: str
    reason: str


@dataclass(frozen=True)
class ScreeningDraft:
    proposals: tuple[HypothesisProposal, ...]
    #: Proposal key -> canonical attestation ids that ground it.
    grounding: Mapping[str, tuple[str, ...]]
    #: Proposal key -> the canonical screened observation ids it accounts for.
    responds_to: Mapping[str, tuple[str, ...]]
    #: Proposal key -> cited attestation id -> the content words they share.
    relevance: Mapping[str, Mapping[str, tuple[str, ...]]]
    declined: tuple[ScreeningDecline, ...]


def parse_screening_review(
    text: str,
    *,
    bindings: Mapping[str, OutcomeSpace],
    abnormal: Mapping[str, str],
    existing_mechanisms: Sequence[str],
    evidence_refs: Mapping[str, str],
    observation_refs: Mapping[str, str],
    shown_attestation_ids: Sequence[str],
    evidence_texts: Mapping[str, str] | None = None,
    inference_id: str | None = None,
) -> ScreeningDraft:
    """Every abnormal reading answered exactly once: accounted for by a new, grounded rival that
    predicts over its observable, or declined with a reason.

    `abnormal` is canonical observation id -> observable_ref, for the abnormal readings only;
    `observation_refs` is alias -> canonical id for every reading shown. A proposal may respond to
    an abnormal reading only; its grounding must be shown evidence with substantive overlap
    (`require_relevant_grounding`), never the reading itself.
    """
    role = HYPOTHESIS_ENGINE.role.value
    obj = _object(role, text, inference_id)
    raw = _list_field(role, obj, "hypotheses", inference_id)
    declined_raw = _list_field(role, obj, "declined", inference_id)
    proposals = _proposals(role, raw, bindings, inference_id)
    taken = {" ".join(m.lower().split()) for m in existing_mechanisms}
    answered: dict[str, str] = {}
    grounding: dict[str, tuple[str, ...]] = {}
    responds: dict[str, tuple[str, ...]] = {}
    relevance: dict[str, Mapping[str, tuple[str, ...]]] = {}
    for proposal, item in zip(proposals, raw, strict=True):
        name = " ".join(proposal.mechanism.lower().split())
        if name in taken:
            raise RoleOutputRefused(
                role,
                f"hypothesis {proposal.key!r} proposes {proposal.mechanism!r}, which is already "
                "under consideration; a screening review adds rivals, it does not restate them",
                inference_id=inference_id,
            )
        taken.add(name)
        refs = item.get("responds_to")
        if not isinstance(refs, list) or not refs:
            raise RoleOutputRefused(
                role,
                f"hypothesis {proposal.key!r} names no abnormal reading in responds_to",
                inference_id=inference_id,
            )
        observations = resolve_refs(
            role,
            _strings(role, refs, "responds_to", inference_id),
            shown=observation_refs,
            allowed=list(abnormal),
            what="abnormal readings",
            inference_id=inference_id,
        )
        predicted = {
            p.observable_ref
            for p in proposal.predictions
            if p.relation_effect in DISCRIMINATING_EFFECTS
        }
        for observation in observations:
            if abnormal[observation] not in predicted:
                raise RoleOutputRefused(
                    role,
                    f"hypothesis {proposal.key!r} responds to a reading of "
                    f"{abnormal[observation]} but makes no SUPPORTS or CONTRADICTS prediction "
                    "over it; a rival that accounts for a reading says what that reading means",
                    inference_id=inference_id,
                )
            if observation in answered:
                raise RoleOutputRefused(
                    role,
                    f"two hypotheses respond to the same reading ({answered[observation]!r} and "
                    f"{proposal.key!r}); propose one rival per abnormal reading",
                    inference_id=inference_id,
                )
            answered[observation] = proposal.key
        cited = item.get("grounding_evidence_ids")
        if not isinstance(cited, list) or not cited:
            raise RoleOutputRefused(
                role,
                f"hypothesis {proposal.key!r} cites no evidence in grounding_evidence_ids; an "
                "unusual reading alone is not a reason for any particular mechanism",
                inference_id=inference_id,
            )
        grounds = resolve_refs(
            role,
            _strings(role, cited, "grounding_evidence_ids", inference_id),
            shown=evidence_refs,
            allowed=shown_attestation_ids,
            what="evidence items",
            inference_id=inference_id,
        )
        relevance[proposal.key] = require_relevant_grounding(
            role, proposal, grounds, evidence_texts, inference_id
        )
        grounding[proposal.key] = grounds
        responds[proposal.key] = observations
    declined: list[ScreeningDecline] = []
    for d in declined_raw:
        if not isinstance(d, dict):
            raise RoleOutputRefused(role, "a decline is not an object", inference_id=inference_id)
        (observation,) = resolve_refs(
            role,
            (_text(role, d, "observation_ref", inference_id),),
            shown=observation_refs,
            allowed=list(abnormal),
            what="abnormal readings",
            inference_id=inference_id,
        )
        if observation in answered or any(x.observation == observation for x in declined):
            raise RoleOutputRefused(
                role,
                "answers an abnormal reading twice; each is accounted for or declined, once",
                inference_id=inference_id,
            )
        declined.append(
            ScreeningDecline(observation=observation, reason=_text(role, d, "reason", inference_id))
        )
    missing = [
        o for o in abnormal if o not in answered and all(x.observation != o for x in declined)
    ]
    if missing:
        names = {c: a for a, c in observation_refs.items()}
        raise RoleOutputRefused(
            role,
            f"leaves {[names.get(m, m) for m in missing]} unanswered; every abnormal reading is "
            "accounted for by a new hypothesis or declined with a reason",
            inference_id=inference_id,
        )
    return ScreeningDraft(
        proposals=proposals,
        grounding=grounding,
        responds_to=responds,
        relevance=relevance,
        declined=tuple(declined),
    )


# -- Domain Specialist ------------------------------------------------------------------------


def resolve_refs(
    role: str,
    refs: Sequence[str],
    *,
    shown: Mapping[str, str],
    allowed: Sequence[str],
    what: str,
    inference_id: str | None,
) -> tuple[str, ...]:
    """Each reference a reply makes, as the canonical id it names -- or the reply is refused.

    `shown` is alias -> canonical id for what the call showed (`cognition.aliases`); `allowed` the
    canonical ids a reference may name here. A reference resolves only exactly (an alias, or a
    canonical id in full); two references to one item are refused rather than merged, because a
    reply that lists the same rival twice is not saying what its author meant.
    """
    usable = {alias: canonical for alias, canonical in shown.items() if canonical in allowed}
    usable.update({c: c for c in allowed})
    out: list[str] = []
    for ref in refs:
        canonical = resolve(ref, usable)
        if canonical is None:
            names = sorted(a for a in shown if shown[a] in allowed) or sorted(allowed)
            raise RoleOutputRefused(
                role,
                f"{ref!r} is not under consideration: it is none of the {what} this call showed "
                f"({', '.join(names)}). A reference is copied exactly as given -- never shortened, "
                "re-cased or made up -- and a specialist or critic adds no rivals of its own",
                inference_id=inference_id,
            )
        if canonical in out:
            raise RoleOutputRefused(
                role,
                f"{ref!r} names {what[:-1] if what.endswith('s') else what} already listed; each "
                "is listed once",
                inference_id=inference_id,
            )
        out.append(canonical)
    return tuple(out)


def parse_specialist(
    text: str,
    *,
    role_id: str,
    hypothesis_ids: Sequence[str],
    shown: Mapping[str, str] | None = None,
    inference_id: str | None = None,
) -> PositionDraft:
    """§7.4: independent Position + predictions/confounders, over the hypotheses it was SHOWN.

    `shown` maps the aliases the specialist saw (`H1`, ...) to canonical hypothesis ids; the
    position records the canonical ids. Favouring anything not under consideration -- a hypothesis
    it was not shown, an id it shortened -- is refused: adding rivals is the Hypothesis Engine's
    role, and a shortened id names nothing.
    """
    obj = _object(role_id, text, inference_id)
    favoured = resolve_refs(
        role_id,
        _strings(
            role_id,
            obj.get("favoured_hypothesis_ids", []),
            "favoured_hypothesis_ids",
            inference_id,
        ),
        shown=shown or {},
        allowed=hypothesis_ids,
        what="hypotheses under consideration",
        inference_id=inference_id,
    )
    proposals = []
    raw_proposals = _list_field(role_id, obj, "proposed_predictions", inference_id)
    for p in raw_proposals:
        if not isinstance(p, dict):
            raise RoleOutputRefused(
                role_id, "a proposed prediction is not an object", inference_id=inference_id
            )
        try:
            proposals.append(ProposedPrediction.model_validate(p))
        except ValidationError as bad:
            raise RoleOutputRefused(
                role_id,
                f"a proposed prediction is malformed ({bad.error_count()} error(s): "
                f"{bad.errors()[0]['loc']} {bad.errors()[0]['msg']})",
                inference_id=inference_id,
            ) from None
    return PositionDraft(
        mechanism_view=_text(role_id, obj, "mechanism_view", inference_id),
        favoured=favoured,
        uncertainties=_strings(
            role_id, obj.get("uncertainties", []), "uncertainties", inference_id
        ),
        confounders=_strings(role_id, obj.get("confounders", []), "confounders", inference_id),
        proposed_predictions=tuple(proposals),
    )


# -- Adversarial Critic -----------------------------------------------------------------------


@dataclass(frozen=True)
class CritiqueDraft:
    objections: tuple[Objection, ...]
    alternative_mechanisms: tuple[str, ...]
    falsifier_challenges: tuple[FalsifierChallenge, ...]


def parse_critique(
    text: str,
    *,
    targets: Sequence[str],
    shown_attestation_ids: Sequence[str],
    hypothesis_refs: Mapping[str, str] | None = None,
    evidence_refs: Mapping[str, str] | None = None,
    inference_id: str | None = None,
) -> CritiqueDraft:
    """§7.4: CritiqueReport, falsifiers, missing controls -- read-only on evidence, and cited.

    `hypothesis_refs` / `evidence_refs` map the aliases the critic saw (`H1`, `E1`, ...) to
    canonical ids; the draft carries canonical ids only. A target or a citation that does not
    resolve exactly to something the critic was shown is refused.
    """
    role = ADVERSARIAL_CRITIC.role.value
    obj = _object(role, text, inference_id)
    shown = tuple(shown_attestation_ids)
    objections: list[Objection] = []
    raw_objections = _list_field(role, obj, "objections", inference_id)
    for o in raw_objections:
        if not isinstance(o, dict):
            raise RoleOutputRefused(
                role, "an objection is not an object", inference_id=inference_id
            )
        (target,) = resolve_refs(
            role,
            (_text(role, o, "target_id", inference_id),),
            shown=hypothesis_refs or {},
            allowed=targets,
            what="target hypotheses",
            inference_id=inference_id,
        )
        raw_cited = _strings(
            role, o.get("evidence_attestation_ids", []), "evidence_attestation_ids", inference_id
        )
        refs = {a: c for a, c in (evidence_refs or {}).items() if c in shown}
        invented = sorted(
            r for r in raw_cited if resolve(r, {**refs, **{s: s for s in shown}}) is None
        )
        if invented:
            raise RoleOutputRefused(
                role,
                f"cites {invented}, which it was not shown. §7.1: no role may supply evidence from "
                "its own generated text -- a citation to something outside the evidence map is "
                "exactly that",
                inference_id=inference_id,
            )
        cited = resolve_refs(
            role,
            raw_cited,
            shown=refs,
            allowed=shown,
            what="evidence items",
            inference_id=inference_id,
        )
        try:
            objections.append(
                Objection(
                    target_id=target,
                    kind=ObjectionKind(_text(role, o, "kind", inference_id)),
                    severity=ObjectionSeverity(_text(role, o, "severity", inference_id)),
                    text=_text(role, o, "text", inference_id),
                    evidence_attestation_ids=cited,
                )
            )
        except ValueError as exc:
            raise RoleOutputRefused(role, str(exc), inference_id=inference_id) from exc
    challenges = []
    raw_challenges = _list_field(role, obj, "falsifier_challenges", inference_id)
    for c in raw_challenges:
        if not isinstance(c, dict) or not isinstance(c.get("target_id"), str):
            raise RoleOutputRefused(
                role, "a falsifier challenge names no target", inference_id=inference_id
            )
        (target,) = resolve_refs(
            role,
            (c["target_id"],),
            shown=hypothesis_refs or {},
            allowed=targets,
            what="target hypotheses",
            inference_id=inference_id,
        )
        challenges.append(
            FalsifierChallenge(target_id=target, text=_text(role, c, "text", inference_id))
        )
    return CritiqueDraft(
        objections=tuple(objections),
        alternative_mechanisms=_strings(
            role, obj.get("alternative_mechanisms", []), "alternative_mechanisms", inference_id
        ),
        falsifier_challenges=tuple(challenges),
    )


# -- Novelty Auditor --------------------------------------------------------------------------


@dataclass(frozen=True)
class NoveltyDraft:
    status: NoveltyStatus
    scope: NoveltyScope
    matrix: tuple[PriorArtMatch, ...]


def parse_novelty(
    text: str, *, record_ids: Sequence[str], inference_id: str | None = None
) -> NoveltyDraft:
    role = NOVELTY_AUDITOR.role.value
    obj = _object(role, text, inference_id)
    matrix = []
    for row in obj.get("matrix", []) or []:
        if not isinstance(row, dict) or row.get("record_id") not in record_ids:
            raise RoleOutputRefused(
                role,
                f"a matrix row names {row.get('record_id') if isinstance(row, dict) else row!r}, "
                "which the search did not return",
                inference_id=inference_id,
            )
        matrix.append(
            PriorArtMatch(
                record_id=row["record_id"],
                overlap=PriorArtOverlap(_text(role, row, "overlap", inference_id)),
                note=str(row.get("note", "")),
            )
        )
    try:
        status = NoveltyStatus(_text(role, obj, "status", inference_id))
        scope = NoveltyScope(_text(role, obj, "scope", inference_id))
    except ValueError as exc:
        raise RoleOutputRefused(role, str(exc), inference_id=inference_id) from exc
    return NoveltyDraft(status=status, scope=scope, matrix=tuple(matrix))


__all__ = [
    "ADVERSARIAL_CRITIC",
    "CORE_CONTRACTS",
    "COVERAGE_REVIEW",
    "DISCRIMINATING_EFFECTS",
    "HYPOTHESIS_ENGINE",
    "NOVELTY_AUDITOR",
    "QUERY_REWRITER",
    "SCREENING_REVIEW",
    "SPECIALIST_REQUIRES",
    "STRIPPED_BYTE_ORDER_MARK",
    "STRIPPED_CODE_FENCE",
    "CoverageDecline",
    "CoverageDraft",
    "CritiqueDraft",
    "HypothesisProposal",
    "NoveltyDraft",
    "PositionDraft",
    "PredictionProposal",
    "RoleContract",
    "RoleOutputRefused",
    "ScreeningDecline",
    "ScreeningDraft",
    "binding_context",
    "content_terms",
    "core_prompts",
    "normalize_reply",
    "parse_coverage_review",
    "parse_critique",
    "parse_hypothesis_engine",
    "parse_novelty",
    "parse_query_terms",
    "parse_screening_review",
    "parse_specialist",
    "require_input",
    "require_relevant_grounding",
    "resolve_refs",
    "shared_terms",
]
