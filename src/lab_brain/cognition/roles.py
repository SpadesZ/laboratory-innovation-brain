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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

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
from lab_brain.core.models.prediction import PREDICTION_EFFECT_TYPES, OutcomeSpace
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
HYPOTHESIS_ENGINE = RoleContract(
    role=CognitiveRole.HYPOTHESIS_ENGINE,
    prompt=PromptTemplate(
        "prm:hypothesis-engine",
        "4.0.0",
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
        "nothing. Reply with JSON.",
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
    return tuple(contract.prompt for contract in CORE_CONTRACTS)


def require_input(role: str, requires: frozenset[str], context: Mapping[str, object]) -> None:
    missing = sorted(requires - set(context))
    if missing:
        raise RoleOutputRefused(
            role,
            f"the input is missing {missing}; §7.4 fixes what a role receives, and a role given "
            "less than its contract says would produce output whose omissions mean nothing",
        )


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
    return tuple(proposals), position


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


# -- Domain Specialist ------------------------------------------------------------------------


def parse_specialist(
    text: str,
    *,
    role_id: str,
    hypothesis_ids: Sequence[str],
    inference_id: str | None = None,
) -> PositionDraft:
    """§7.4: independent Position + predictions/confounders, over the hypotheses it was SHOWN."""
    obj = _object(role_id, text, inference_id)
    favoured = _strings(
        role_id, obj.get("favoured_hypothesis_ids", []), "favoured_hypothesis_ids", inference_id
    )
    unknown = sorted(set(favoured) - set(hypothesis_ids))
    if unknown:
        raise RoleOutputRefused(
            role_id,
            f"the specialist favours {unknown}, which are not under consideration "
            f"({sorted(hypothesis_ids)}); a specialist states a position on the rivals it is "
            "shown, "
            "and adding rivals is the Hypothesis Engine's role",
            inference_id=inference_id,
        )
    proposals = []
    for p in obj.get("proposed_predictions", []) or []:
        if not isinstance(p, dict):
            raise RoleOutputRefused(
                role_id, "a proposed prediction is not an object", inference_id=inference_id
            )
        proposals.append(ProposedPrediction.model_validate(p))
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
    inference_id: str | None = None,
) -> CritiqueDraft:
    """§7.4: CritiqueReport, falsifiers, missing controls -- read-only on evidence, and cited."""
    role = ADVERSARIAL_CRITIC.role.value
    obj = _object(role, text, inference_id)
    shown = frozenset(shown_attestation_ids)
    objections: list[Objection] = []
    for o in obj.get("objections", []) or []:
        if not isinstance(o, dict):
            raise RoleOutputRefused(
                role, "an objection is not an object", inference_id=inference_id
            )
        target = _text(role, o, "target_id", inference_id)
        if target not in targets:
            raise RoleOutputRefused(
                role, f"objects to {target!r}, which is not a target", inference_id=inference_id
            )
        cited = _strings(
            role, o.get("evidence_attestation_ids", []), "evidence_attestation_ids", inference_id
        )
        invented = sorted(set(cited) - shown)
        if invented:
            raise RoleOutputRefused(
                role,
                f"cites {invented}, which it was not shown. §7.1: no role may supply evidence from "
                "its own generated text -- a citation to something outside the evidence map is "
                "exactly that",
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
    for c in obj.get("falsifier_challenges", []) or []:
        if not isinstance(c, dict) or c.get("target_id") not in targets:
            raise RoleOutputRefused(
                role, "a falsifier challenge names no target", inference_id=inference_id
            )
        challenges.append(
            FalsifierChallenge(target_id=c["target_id"], text=_text(role, c, "text", inference_id))
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
    "HYPOTHESIS_ENGINE",
    "NOVELTY_AUDITOR",
    "QUERY_REWRITER",
    "SPECIALIST_REQUIRES",
    "CritiqueDraft",
    "HypothesisProposal",
    "NoveltyDraft",
    "PositionDraft",
    "PredictionProposal",
    "RoleContract",
    "RoleOutputRefused",
    "binding_context",
    "core_prompts",
    "parse_critique",
    "parse_hypothesis_engine",
    "parse_novelty",
    "parse_query_terms",
    "parse_specialist",
    "require_input",
]
