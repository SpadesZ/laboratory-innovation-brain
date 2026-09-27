"""A local, rule-based reasoner behind the scientific model slots: a declared mechanism catalog.

    §7.3   Model Router 提供 6 個 LLM logical slots ...（不是 6 顆必備模型）
    §7.1   the multi-agent design is cognitive decomposition, 不是很多聊天機器人

WHAT THIS IS, AND WHAT IT IS NOT. A deployment with no language model configured still has to
propose competing hypotheses, critique them and rewrite retrieval queries, or nothing downstream of
the debate can run. This is the `Completion` a `ScientificLLM` slot calls in that deployment: a
deterministic reader of a DomainPack's declared mechanism catalog. It is NOT a language model and
never claims to be one -- its `ModelSlot` names it `rules:<catalog id>`, provider `local-rules`,
reach LOCAL, and every InferenceProvenance it produces carries that identity, so a reader of any
hypothesis, position or critique can see exactly what produced it.

EVERYTHING IT SAYS COMES FROM TWO PLACES. The catalog (domain knowledge the pack declares: each
mechanism's statement, assumptions, falsifier, typed predictions, and the words in a record that
point at it or against it) and the CONTEXT block `ScientificLLM` appends to each prompt (the
evidence the role was shown, by attestation id). It reads no file, calls nothing, and never sees
an answer:

    Hypothesis Engine   every catalog mechanism up to the requested minimum, ranked by how often
                        the evidence shown mentions its cues; certificates are the catalog's
    Critic              a COUNTEREXAMPLE only where evidence it was shown (the inverted retrieval)
                        contains a mechanism's counter-cue, citing that attestation; alternative
                        mechanisms the evidence points at that no hypothesis covers
    query rewriter      the catalog's primary terms; for inverted retrieval, the falsifiers' words
    specialists         which catalog mechanisms the domain evidence mentions
    novelty auditor     lexical overlap only, and never a GLOBAL claim from internal coverage

It is a mediocre scientist on purpose: it cannot invent a mechanism the catalog does not declare,
and a record that never uses the catalog's words moves nothing. That is the honest ceiling of a
deployment with no model, and the report says which reasoner ran.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from lab_brain.cognition.llm import ModelSlot
from lab_brain.cognition.roles import (
    ADVERSARIAL_CRITIC,
    HYPOTHESIS_ENGINE,
    NOVELTY_AUDITOR,
    QUERY_REWRITER,
)
from lab_brain.core.models.inference import LogicalSlot
from lab_brain.security.external import ExternalReach

_CONTEXT_MARKER = "\n\nCONTEXT:\n"
PROVIDER = "local-rules"


@dataclass(frozen=True)
class CatalogPrediction:
    observable_ref: str
    outcome_space_id: str
    outcome_space_version: str
    expected_outcome: str
    relation_effect: str


@dataclass(frozen=True)
class CatalogMechanism:
    """One mechanism a DomainPack declares, with what would point at it and against it."""

    key: str
    statement: str
    mechanism: str
    assumptions: tuple[str, ...]
    confounders: tuple[str, ...]
    falsifier: str
    minimal_test_ref: str
    predictions: tuple[CatalogPrediction, ...]
    #: Lower-case phrases whose presence in a record points AT this mechanism.
    cues: tuple[str, ...]
    #: Lower-case phrases whose presence in a record points AGAINST it.
    counter_cues: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.predictions:
            raise ValueError(f"mechanism {self.key} declares no typed prediction")
        if not self.cues:
            raise ValueError(f"mechanism {self.key} declares no cue; nothing could point at it")


@dataclass(frozen=True)
class MechanismCatalog:
    catalog_id: str
    version: str
    mechanisms: tuple[CatalogMechanism, ...]
    #: The query rewriter's terms for primary retrieval.
    primary_terms: tuple[str, ...]

    def __post_init__(self) -> None:
        keys = [m.key for m in self.mechanisms]
        if len(set(keys)) != len(keys) or len({m.mechanism for m in self.mechanisms}) != len(keys):
            raise ValueError(f"catalog {self.catalog_id} declares a mechanism twice")
        if len(keys) < 2:
            raise ValueError("a catalog of fewer than two mechanisms cannot compete")

    @property
    def ref(self) -> str:
        return f"{self.catalog_id}@{self.version}"


def reasoner_slots(
    catalog: MechanismCatalog, slots: Sequence[LogicalSlot]
) -> tuple[ModelSlot, ...]:
    """The slots this reasoner serves, named for what it is -- never a model name it is not."""
    return tuple(
        ModelSlot(
            slot,
            f"rules:{catalog.catalog_id}",
            catalog.version,
            provider=PROVIDER,
            reach=ExternalReach.LOCAL,
        )
        for slot in slots
    )


def _context(material: str) -> dict[str, Any]:
    if _CONTEXT_MARKER not in material:
        return {}
    loaded: dict[str, Any] = json.loads(material.split(_CONTEXT_MARKER, 1)[1])
    return loaded


def _tokens(text: str) -> list[str]:
    return [t for t in "".join(c if c.isalnum() else " " for c in text.lower()).split() if t]


@dataclass
class CatalogReasoner:
    """The `Completion` (prompt, slot) -> reply. Deterministic; see the module docstring."""

    catalog: MechanismCatalog
    #: Every prompt answered, for a caller that wants to show exactly what the reasoner read.
    prompts_seen: list[str] = field(default_factory=list)

    def __call__(self, material: str, slot: ModelSlot) -> str:
        self.prompts_seen.append(material)
        ctx = _context(material)
        if material.startswith(HYPOTHESIS_ENGINE.prompt.template):
            return json.dumps(self._engine(ctx))
        if material.startswith(ADVERSARIAL_CRITIC.prompt.template):
            return json.dumps(self._critic(ctx))
        if material.startswith(QUERY_REWRITER.prompt.template):
            return json.dumps(self._rewrite(ctx))
        if material.startswith(NOVELTY_AUDITOR.prompt.template):
            return json.dumps(self._novelty(ctx))
        if "specialist" in ctx:
            return json.dumps(self._specialist(ctx))
        raise ValueError(
            f"{PROVIDER} ({self.catalog.ref}) has no rule for this prompt; it answers only the "
            "declared role contracts"
        )

    # -- reading -----------------------------------------------------------------------------

    @property
    def _by_key(self) -> dict[str, CatalogMechanism]:
        return {m.key: m for m in self.catalog.mechanisms}

    def _key_of(self, mechanism: str) -> str | None:
        return next((m.key for m in self.catalog.mechanisms if m.mechanism == mechanism), None)

    def _scores(self, texts: Sequence[str]) -> dict[str, int]:
        corpus = " ".join(texts).lower()
        return {m.key: sum(corpus.count(c) for c in m.cues) for m in self.catalog.mechanisms}

    def _certificate(self, mechanism: CatalogMechanism) -> dict[str, Any]:
        return {
            "key": mechanism.key,
            "statement": mechanism.statement,
            "mechanism": mechanism.mechanism,
            "assumptions": list(mechanism.assumptions),
            "falsifier": mechanism.falsifier,
            "confounders": list(mechanism.confounders),
            "minimal_test_ref": mechanism.minimal_test_ref,
            "predictions": [
                {
                    "observable_ref": p.observable_ref,
                    "outcome_space_id": p.outcome_space_id,
                    "outcome_space_version": p.outcome_space_version,
                    "expected_outcome": p.expected_outcome,
                    "relation_effect": p.relation_effect,
                }
                for p in mechanism.predictions
            ],
        }

    # -- roles -------------------------------------------------------------------------------

    def _engine(self, ctx: Mapping[str, Any]) -> dict[str, Any]:
        order = [m.key for m in self.catalog.mechanisms]
        by_key = self._by_key
        if ctx.get("alternatives_to_certify"):
            wanted = set(ctx["alternatives_to_certify"])
            existing = set(ctx.get("existing_mechanisms", []))
            keys = [
                k
                for k in order
                if by_key[k].mechanism in wanted and by_key[k].mechanism not in existing
            ]
        else:
            scores = self._scores([e["text"] for e in ctx.get("evidence", [])])
            ranked = sorted(order, key=lambda k: (-scores[k], order.index(k)))
            keys = ranked[: max(2, int(ctx.get("minimum_hypotheses", 2)))]
            lead = by_key[keys[0]] if keys else None
            return {
                "hypotheses": [self._certificate(by_key[k]) for k in keys],
                "position": {
                    "mechanism_view": (
                        f"the evidence shown mentions {lead.mechanism} most often"
                        if lead is not None and scores[lead.key] > 0
                        else "the evidence shown names none of the catalog's mechanisms; every "
                        "catalog mechanism is proposed as an open rival"
                    ),
                    "uncertainties": ["which catalog mechanism the verification checks isolate"],
                    "confounders": list(lead.confounders) if lead is not None else [],
                },
            }
        return {
            "hypotheses": [self._certificate(by_key[k]) for k in keys],
            "position": {
                "mechanism_view": "certifying the alternatives the critique named",
                "uncertainties": [],
                "confounders": [],
            },
        }

    def _specialist(self, ctx: Mapping[str, Any]) -> dict[str, Any]:
        scores = self._scores([e["text"] for e in ctx.get("evidence", [])])
        favoured = [
            h["hypothesis_id"]
            for h in ctx.get("hypotheses", [])
            if (key := self._key_of(h["mechanism"])) is not None and scores[key] > 0
        ]
        names = sorted(m.mechanism for m in self.catalog.mechanisms if scores[m.key] > 0)
        return {
            "mechanism_view": (
                "the domain evidence mentions "
                + (", ".join(names) if names else "none of the catalog's mechanisms")
            ),
            "favoured_hypothesis_ids": favoured,
            "uncertainties": ["how much of the domain evidence the shown bundle covers"],
            "confounders": [],
            "proposed_predictions": [],
        }

    def _rewrite(self, ctx: Mapping[str, Any]) -> dict[str, Any]:
        if ctx.get("mode") == "PRIMARY":
            return {"terms": list(self.catalog.primary_terms)}
        terms: list[str] = []
        for falsifier in ctx.get("falsifiers", []):
            for token in _tokens(falsifier):
                if token not in terms:
                    terms.append(token)
        return {"terms": terms or list(self.catalog.primary_terms)}

    def _critic(self, ctx: Mapping[str, Any]) -> dict[str, Any]:
        by_key = self._by_key
        inverted = set(ctx.get("inverted_attestation_ids", []))
        evidence = ctx.get("evidence", [])
        objections: list[dict[str, Any]] = []
        present: set[str] = set()
        for h in ctx.get("hypotheses", []):
            key = self._key_of(h["mechanism"])
            if key is None:
                continue
            present.add(key)
            for e in evidence:
                if e["attestation_id"] not in inverted:
                    continue
                text = e["text"].lower()
                hits = [c for c in by_key[key].counter_cues if c in text]
                if hits:
                    objections.append(
                        {
                            "target_id": h["hypothesis_id"],
                            "kind": "COUNTEREXAMPLE",
                            "severity": "CONTRADICTS",
                            "text": (
                                f"{e['attestation_id']} states '{hits[0]}', which the catalog "
                                f"lists against {h['mechanism']}"
                            ),
                            "evidence_attestation_ids": [e["attestation_id"]],
                        }
                    )
        scores = self._scores([e["text"] for e in evidence])
        alternatives = [
            m.mechanism for m in self.catalog.mechanisms if m.key not in present and scores[m.key]
        ]
        return {
            "objections": objections,
            "alternative_mechanisms": alternatives,
            "falsifier_challenges": [],
        }

    def _novelty(self, ctx: Mapping[str, Any]) -> dict[str, Any]:
        concept = set(_tokens(ctx.get("concept", "")))
        matrix = []
        for record in ctx.get("records", []):
            shared = concept & set(_tokens(record.get("title", "")))
            overlap = "FULL" if len(shared) >= 4 else ("PARTIAL" if shared else "NONE")
            matrix.append({"record_id": record["record_id"], "overlap": overlap, "note": ""})
        overlaps = {m["overlap"] for m in matrix}
        status = (
            "KNOWN"
            if "FULL" in overlaps
            else ("PARTIALLY_NOVEL" if "PARTIAL" in overlaps else "NOVELTY_CANDIDATE")
        )
        # Never GLOBAL from internal coverage: SRC-003's rule, applied by the reasoner as well.
        scope = "INTERNAL" if ctx.get("coverage", {}).get("internal_only", True) else "GLOBAL"
        return {"matrix": matrix, "status": status, "scope": scope}


__all__ = [
    "PROVIDER",
    "CatalogMechanism",
    "CatalogPrediction",
    "CatalogReasoner",
    "MechanismCatalog",
    "reasoner_slots",
]
