"""M3's Hypothesis Brain: the debate, and the only way its hypotheses reach belief revision.

    §16 / §26.1  M3 Hypothesis Brain -- 6 core roles、selected Domain Specialists、PRIMARY/FAST/
                 EMBEDDING minimum routing、stake-adaptive debate、Critic inverted retrieval.

A COMPOSITION, NOT A NEW AUTHORITY. Everything that decides lives elsewhere and is reused as is:

    StructuredDebate          what the roles say, admitted through §8's gate (EPI-001)
    HypothesisRevisionGate    whether a certified hypothesis MAY enter BELIEF_REVISION yet
                              (EPI-001 / SRC-002 / LLM-002) -- a precondition, never a verdict
    BeliefEpisode             M1's governed path: `TransitionPolicy.evaluate`, the durable
                              authorization, the event, the escalation. Hard-locked, unchanged

`attempt_revision` runs the gate FIRST and M1's path SECOND, so a refused precondition writes no
Decision, no event and no review item, and a permitted one is decided on the evidence exactly as it
was before M3. `011i` refuses the same transitions in SQL for any writer that skips this class.

STAKES COME FROM THE SET. `BeliefEpisode.hypothesis_view` takes `stakes` as a parameter because, in
M1, "`Hypothesis` does not exist until EPI-001 in M3". It exists now: a certified hypothesis's
stakes are its competing set's, frozen when the set was admitted, and a caller cannot restate them.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

from lab_brain.cognition.debate import DebateOutcome, DebateRequest, StructuredDebate
from lab_brain.cognition.debate_metrics import CRITIC_BUNDLE_DIVERGENCE, DebateGate
from lab_brain.core.benchmark_gate import GateVerdict
from lab_brain.core.episode import BeliefEpisode, EpisodeRefused, EpisodeResult
from lab_brain.core.models.attestation import Attestation
from lab_brain.core.models.belief_event import BeliefState
from lab_brain.core.models.condition import ConditionMatch
from lab_brain.core.models.transition import IndependenceSummary
from lab_brain.core.repositories.debate import DebateStore
from lab_brain.core.repositories.hypotheses import HypothesisStore
from lab_brain.core.revision_gate import DivergenceGate, HypothesisRevisionGate


def set_divergence_gate(debates: DebateStore, gate: DebateGate) -> DivergenceGate:
    """LLM-002 over a set: the most recent debate's Critic divergence against the armed policy.

    No debate on record is a value of `None`, which an armed gate fails and an unarmed one records
    as advisory -- a set nobody debated has no divergence to be calibrated against.
    """

    def verdict(set_id: str) -> GateVerdict:
        records = debates.records_for_set(set_id)
        latest = max(records, key=lambda r: (r.created_at, r.debate_id)) if records else None
        return gate.evaluate(
            CRITIC_BUNDLE_DIVERGENCE, None if latest is None else latest.critic_bundle_divergence
        )

    return verdict


class HypothesisBrain:
    """Debate a question, then revise its hypotheses only through the M3 preconditions."""

    def __init__(
        self,
        *,
        debate: StructuredDebate,
        hypotheses: HypothesisStore,
        revision_gate: HypothesisRevisionGate,
        episode: BeliefEpisode,
    ) -> None:
        self._debate = debate
        self._hypotheses = hypotheses
        self._gate = revision_gate
        self._episode = episode

    def debate(self, request: DebateRequest) -> DebateOutcome:
        return self._debate.run(request)

    def attempt_revision(
        self,
        *,
        project_id: str,
        hypothesis_id: str,
        policy_id: str,
        policy_version: str,
        candidate_to_state: BeliefState,
        occurred_at: dt.datetime,
        trace_id: str,
        triggering_attestations: Sequence[Attestation],
        actor_id: str | None = None,
        authority_policy_ref: tuple[str, str] | None = None,
        condition_matches: Sequence[ConditionMatch] = (),
        independence_summary: IndependenceSummary | None = None,
        inference_provenance_id: str | None = None,
        rationale_artifact_or_record_ref: str | None = None,
    ) -> EpisodeResult:
        """§7.6 / §7.2 / EPI-001 preconditions, then M1's governed transition, unchanged.

        Raises `RevisionPreconditionFailed` (nothing written) when a precondition refuses, and
        `EpisodeRefused` for a hypothesis with no M3 certificate: this path revises certified
        hypotheses, whose stakes and episode it can read rather than be told.
        """
        certificate = self._hypotheses.get_certificate(hypothesis_id)
        if certificate is None or certificate.hypothesis.project_id != project_id:
            raise EpisodeRefused(
                f"{hypothesis_id} has no M3 certificate in {project_id}; the Hypothesis Brain "
                "revises only hypotheses admitted through §8's gate"
            )
        hypothesis_set = self._hypotheses.get_set(certificate.hypothesis_set_id)
        assert hypothesis_set is not None  # `005e`'s foreign key; the in-memory store checks it
        self._gate.require(
            project_id=project_id,
            hypothesis_id=hypothesis_id,
            to_state=candidate_to_state,
            triggering_attestations=triggering_attestations,
            at=occurred_at,
        )
        return self._episode.attempt_transition(
            project_id=project_id,
            hypothesis_id=hypothesis_id,
            policy_id=policy_id,
            policy_version=policy_version,
            candidate_to_state=candidate_to_state,
            stakes=hypothesis_set.stakes,
            occurred_at=occurred_at,
            trace_id=trace_id,
            episode_id=hypothesis_set.episode_id,
            actor_id=actor_id,
            authority_policy_ref=authority_policy_ref,
            condition_matches=condition_matches,
            independence_summary=independence_summary,
            triggering_attestations=triggering_attestations,
            inference_provenance_id=inference_provenance_id,
            rationale_artifact_or_record_ref=rationale_artifact_or_record_ref,
            detected_by_actor_or_slot="cognition.brain",
        )


__all__ = ["HypothesisBrain", "set_divergence_gate"]
