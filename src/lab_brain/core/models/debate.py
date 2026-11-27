"""§17.14.1's debate objects: what the cognitive roles are allowed to say to each other (M3).

    §7  角色之間**只**透過有 schema 的物件溝通：EvidenceBundle、Position、Hypothesis、
        CritiqueReport、VerificationPlan、RelationJudgment 與 Shared Scientific State。

WHY THESE ARE TYPED AND NOT TRANSCRIPTS. A debate whose record is a chat log can only be audited by
reading it, and "did the Critic actually look at different evidence" is then a question about
prose. §15.4 requires that question to be measurable -- *Critic evidence-bundle divergence* -- and
it is measurable only if a critique names the bundle it examined. So a `CritiqueReport` carries
`primary_bundle_id` and `inverted_bundle_id` as identities, and a `Position` carries the bundle its
view was formed from, and the divergence is a function of two rows.

A POSITION IS NOT EVIDENCE AND A CRITIQUE IS NOT A VERDICT. Both are inferences (P3, EVI-003): each
carries `inference_provenance_id` and neither can move belief. §7.1 says the Adversarial Critic
"不負責 final truth；不能只靠語言說服力淘汰假說". An objection therefore has to *cite* evidence the
critic was shown -- the citation is checked against the bundles, not trusted -- and even a cited
objection only marks a hypothesis as challenged in the debate. Moving its belief state is
`TransitionPolicy`'s, on evidence, through a BeliefRevisionEvent.

`proposed_predictions` ARE PROPOSALS. §17.14.1 says so outright: they "MUST be materialized as typed
Prediction objects (17.5.1) bound to a declared OutcomeSpace version before they can participate in
sufficiency computation". So they are kept as a small typed record that cannot be mistaken for a
`Prediction` -- no `relation_effect_if_observed`, no admission -- and "A Position alone never makes
an action sufficient" holds by the absence of the fields that would let it.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from enum import StrEnum
from typing import Any, Self

from pydantic import Field, model_validator

from lab_brain.core.models.base import CoreModel, utc_now


class ResearchContract(CoreModel):
    """§17.14.1's ResearchContract: the Supervisor/PI role's output (§7.4).

    What the debate is FOR, stated before it starts: the question, the research intent that selects
    the SourcePolicy (§7.5), what would count as done, and when to stop. A debate that decided its
    own stopping condition after seeing its results could always stop where it liked the answer.
    """

    contract_id: str
    project_id: str
    question: str
    intent: str
    success_criteria: tuple[str, ...] = ()
    constraints: dict[str, Any] = Field(default_factory=dict)
    privacy_mode: str
    budget_id: str | None = None
    stop_conditions: tuple[str, ...] = ()
    actor_id: str

    @model_validator(mode="after")
    def _a_contract_states_its_question_and_its_owner(self) -> Self:
        for name in ("question", "intent", "privacy_mode", "actor_id"):
            if not getattr(self, name).strip():
                raise ValueError(
                    f"research contract {self.contract_id} has a blank {name}. §7.1's Supervisor "
                    "owns goal decomposition and termination; a contract that does not say what it "
                    "asks, under which intent, or who asked it cannot be held to either"
                )
        return self


class ProposedPrediction(CoreModel):
    """A debate-stage proposal (§17.14.1). Deliberately NOT a §17.5.1 `Prediction`.

    It has no `relation_effect_if_observed` and no admission: §17.14.1 forbids a proposal from
    participating in sufficiency, and the surest way to keep it out is not to give it the field
    sufficiency reads.
    """

    observable_ref: str
    expected_outcome: str
    outcome_space_id: str | None = None
    outcome_space_version: str | None = None


class Position(CoreModel):
    """§17.14.1's Position: one role's independent view, formed from one bundle (§7.2 Stage A).

    ``project_id`` is not in §17.14.1's block, for the reason §17.4 and §17.16 omit it: the schema
    reaches the project through ``episode_id``. SEC-002 scopes every read by project, so the row
    carries it; `schema_drift.UNBOUND` records the difference rather than hiding it.
    """

    position_id: str
    project_id: str
    role_id: str
    episode_id: str
    hypothesis_refs: tuple[str, ...] = ()
    mechanism_view: str
    supporting_relation_ids: tuple[str, ...] = ()
    uncertainties: tuple[str, ...] = ()
    proposed_predictions: tuple[ProposedPrediction, ...] = ()
    confounders: tuple[str, ...] = ()
    #: The retrieval this view was formed from. Required: §7.2's anti-groupthink source is
    #: "different EvidenceBundle", and a position with no bundle cannot be compared to another.
    bundle_id: str
    #: Required. A position is an inference (P3); one with no provenance is exactly what §7.6
    #: forbids as a basis.
    inference_provenance_id: str
    created_at: dt.datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _a_position_says_something(self) -> Self:
        if not self.mechanism_view.strip():
            raise ValueError(
                f"position {self.position_id} ({self.role_id}) states no mechanism view. §7.2 "
                "Stage A collects independent positions; an empty one counts toward diversity "
                "without contributing anything to it"
            )
        if len(set(self.hypothesis_refs)) != len(self.hypothesis_refs):
            raise ValueError(f"position {self.position_id} references a hypothesis twice")
        return self


class ObjectionKind(StrEnum):
    """§7.1: what the Adversarial Critic attacks."""

    ASSUMPTION = "ASSUMPTION"
    CONFOUNDER = "CONFOUNDER"
    CAUSAL_GAP = "CAUSAL_GAP"
    COUNTEREXAMPLE = "COUNTEREXAMPLE"
    MISSING_CONTROL = "MISSING_CONTROL"


class ObjectionSeverity(StrEnum):
    """How far an objection reaches. Ordinal, and neither value moves belief.

    ``CONTRADICTS`` means the critic cites evidence it reads as contradicting the target. That is a
    claim about the evidence, adjudicated later by `TransitionPolicy` on admitted relations -- the
    critic's own reading is an inference and settles nothing (§7.6).
    """

    CHALLENGES = "CHALLENGES"
    CONTRADICTS = "CONTRADICTS"


class Objection(CoreModel):
    """One attack on one target, bound to the evidence the critic cites for it.

    ``evidence_attestation_ids`` may be empty only for a CHALLENGES objection. A CONTRADICTS
    objection with no citation is the "語言說服力" §7.1 refuses: an assertion that a hypothesis is
    wrong, supported by nothing but its own phrasing.
    """

    target_id: str
    kind: ObjectionKind
    severity: ObjectionSeverity
    text: str
    evidence_attestation_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _a_contradiction_cites_evidence(self) -> Self:
        if not self.text.strip():
            raise ValueError(f"objection against {self.target_id} has no text")
        if self.severity is ObjectionSeverity.CONTRADICTS and not self.evidence_attestation_ids:
            raise ValueError(
                f"objection against {self.target_id} claims CONTRADICTS and cites no evidence. "
                "§7.1: the critic cannot eliminate a hypothesis by persuasiveness alone -- a "
                "contradiction is a claim about evidence, and one that names none is a claim about "
                "nothing"
            )
        return self


class FalsifierChallenge(CoreModel):
    """§7.1's falsifier attack: the stated falsifier would not actually falsify the target."""

    target_id: str
    text: str


class CritiqueReport(CoreModel):
    """§17.14.1's CritiqueReport, plus the two fields that make §7.6's independence checkable.

    ``inverted_bundle_id`` is CONDITIONALLY required (§7.2): when the decision's stakes reach the
    SourcePolicy's `inverted_retrieval_threshold` it must be present, and the decision may not enter
    BELIEF_REVISION otherwise. The condition belongs to the policy, not to this object, so the model
    allows `None` and `lab_brain.core.revision_gate` refuses it where the policy says so.

    ``original_inference_id`` and ``differs_in`` are not in §17.14.1's block. §7.6 requires the
    critique path to differ from the original inference in bundle, reasoning policy or model route,
    and a report that could not say *which* inference it critiqued could not be checked for that at
    all. ``differs_in`` is derived at write time by comparing the two provenance rows and re-checked
    by the database (`005e`), so a report cannot claim an axis it did not change.
    """

    critique_id: str
    project_id: str
    episode_id: str
    target_ids: tuple[str, ...] = Field(min_length=1)
    objections: tuple[Objection, ...] = ()
    alternative_mechanisms: tuple[str, ...] = ()
    falsifier_challenges: tuple[FalsifierChallenge, ...] = ()
    #: Conflict ids (§17.19.3). References, never inline payloads.
    blocking_conflicts: tuple[str, ...] = ()
    primary_bundle_id: str
    inverted_bundle_id: str | None = None
    #: The inference whose conclusion this critique examined (§7.6).
    original_inference_id: str
    #: Which of §7.6's three axes differ from the original. Derived, never asserted by the model.
    differs_in: tuple[str, ...] = ()
    inference_provenance_id: str
    created_at: dt.datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _a_critique_is_about_something_it_names(self) -> Self:
        if (
            self.inverted_bundle_id is not None
            and self.inverted_bundle_id == self.primary_bundle_id
        ):
            raise ValueError(
                f"critique {self.critique_id} names bundle {self.primary_bundle_id} as both the "
                "primary and the inverted retrieval. §7.2's inverted retrieval is the Critic's OWN "
                "retrieval; reusing the primary bundle under a second name is the groupthink it "
                "exists to break"
            )
        stray = sorted(
            {o.target_id for o in self.objections}
            | {c.target_id for c in self.falsifier_challenges}
        )
        stray = [target for target in stray if target not in self.target_ids]
        if stray:
            raise ValueError(
                f"critique {self.critique_id} objects to {stray}, which are not among its targets "
                f"{list(self.target_ids)}"
            )
        if len(set(self.differs_in)) != len(self.differs_in):
            raise ValueError(f"critique {self.critique_id} lists an independence axis twice")
        return self

    @property
    def performed_inverted_retrieval(self) -> bool:
        return self.inverted_bundle_id is not None

    @property
    def contradicted_targets(self) -> frozenset[str]:
        """Targets the critic cites evidence against. Debate bookkeeping, never a belief state."""
        return frozenset(
            o.target_id for o in self.objections if o.severity is ObjectionSeverity.CONTRADICTS
        )

    @property
    def cited_attestation_ids(self) -> frozenset[str]:
        return frozenset(a for o in self.objections for a in o.evidence_attestation_ids)


class DebateRecord(CoreModel):
    """What one structured debate measured (LLM-002: diversity / bundle-divergence / cost).

    Not a §17 schema -- §7.2 says the system MUST record position diversity, bundle divergence and
    whether the Critic changed the decision, and names no object to record them in. This is that
    object, persisted in `005e`.

    A METRIC THAT COULD NOT BE MEASURED IS `None`, NOT ZERO. One position has no pairwise
    diversity; a debate whose Critic performed no inverted retrieval has no bundle divergence.
    Recording 0 for either would report "no diversity" and "no divergence" -- findings -- where the
    truth is that the question did not arise.
    """

    debate_id: str
    project_id: str
    episode_id: str
    set_id: str
    rounds: int = Field(ge=1)
    max_rounds: int = Field(ge=1)
    stop_reason: str
    escalation_triggers: tuple[str, ...] = ()
    position_ids: tuple[str, ...] = ()
    critique_ids: tuple[str, ...] = ()
    position_diversity: Decimal | None = None
    critic_bundle_divergence: Decimal | None = None
    critic_changed_final_set: bool
    initial_hypothesis_ids: tuple[str, ...]
    surviving_hypothesis_ids: tuple[str, ...]
    surviving_hypothesis_diversity: Decimal | None = None
    additional_evidence_items: int = Field(ge=0)
    additional_token_count: int = Field(ge=0)
    #: Which metric implementation versions produced the numbers above.
    metric_versions: dict[str, str]
    #: Each LLM-002 gate consulted: metric, value, policy ref or ADVISORY, and the verdict.
    gate_evaluations: tuple[dict[str, Any], ...] = ()
    #: One entry per round: what triggered it and what it changed.
    per_round: tuple[dict[str, Any], ...] = ()
    created_at: dt.datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _rounds_are_bounded_and_metrics_are_fractions(self) -> Self:
        if self.rounds > self.max_rounds:
            raise ValueError(
                f"debate {self.debate_id} ran {self.rounds} rounds over its bound {self.max_rounds}"
            )
        for name in (
            "position_diversity",
            "critic_bundle_divergence",
            "surviving_hypothesis_diversity",
        ):
            value = getattr(self, name)
            if value is not None and not (Decimal(0) <= value <= Decimal(1)):
                raise ValueError(f"debate {self.debate_id} records {name}={value} outside [0, 1]")
        if not self.stop_reason.strip():
            raise ValueError(f"debate {self.debate_id} records no stop reason")
        return self


__all__ = [
    "CritiqueReport",
    "DebateRecord",
    "FalsifierChallenge",
    "Objection",
    "ObjectionKind",
    "ObjectionSeverity",
    "Position",
    "ProposedPrediction",
    "ResearchContract",
]
