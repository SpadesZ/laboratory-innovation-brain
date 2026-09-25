"""M3's preconditions on a belief transition of a certified hypothesis (EPI-001, SRC-002, LLM-002).

    EPI-001  單一看似合理原因不得直接被升級成 confirmed root cause。
    SRC-002  當 decision.stakes >= policy threshold，Critic MUST 執行 inverted retrieval、保存
             inverted EvidenceBundle，否則該 decision 不得進入 BELIEF_REVISION。... critique 的
             獨立性要求 retrieval bundle、reasoning policy 或 model route 至少一項與原推論不同，
             且 adjudication 引用 external evidence 或 verification result。
    §7.6     重大 REJECT / irreversible action 必須經 independent critique path。

A PRECONDITION, NOT A SECOND TRANSITION OPERATOR. §8.2.1's `TransitionPolicy.evaluate` is the only
thing that decides whether a hypothesis moves, and T-EPI-005 forbids another operator with another
name. This gate never says a transition SHOULD happen; it says one MAY NOT enter BELIEF_REVISION
yet, for reasons that are not about evidence strength -- the question was never contested, the
Critic never looked for the opposite, or the contest was settled by a model's opinion. When every
precondition holds, `evaluate` still decides, on the evidence, exactly as before.

SCOPE: CERTIFIED HYPOTHESES ONLY. A target with no M3 certificate is governed by M0b alone and this
gate reports `governs=False`: M0b's semantics are hard-locked and M3 does not reach back into them.
`011i` makes the same choice in SQL.

THE FOUR PRECONDITIONS:

    SINGLE_PLAUSIBLE_CAUSE          -> SUPPORTED in a root-cause set needs >= 2 admitted rivals
    NO_INDEPENDENT_CRITIQUE         -> CONTRADICTED (a REJECT) needs an independent critique (§7.6)
    NO_INVERTED_RETRIEVAL           any transition, when the set's stakes reached the policy's
                                    threshold, needs a critique with an inverted bundle (§7.2)
    ADJUDICATED_BY_MODEL_OPINION    a REJECT or an above-threshold decision must rest on at least
                                    one non-inferred attestation: external evidence or a
                                    verification result. A basis made only of INFERRED records is
                                    one model's opinion settling another's (§7.6, EVI-003)

and, when a calibrated BenchmarkPolicy is active for the Critic's bundle divergence, the set's
debate must meet it (LLM-002) -- with no active policy that reading is advisory and recorded. The
gate reads the DEBATE's divergence (everything the Critic's inverted retrievals added) rather than
one critique's: a critique that searched for evidence against a hypothesis and correctly found none
is a robust result, not a failed one, and a per-critique threshold would punish exactly that.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from lab_brain.core.benchmark_gate import GateVerdict
from lab_brain.core.models.attestation import Attestation
from lab_brain.core.models.belief_event import BeliefRevisionEvent, BeliefState
from lab_brain.core.models.enums import FACTUAL_EPISTEMIC_TYPES
from lab_brain.core.repositories.debate import DebateStore
from lab_brain.core.repositories.hypotheses import HypothesisStore


class RevisionPrecondition(StrEnum):
    SINGLE_PLAUSIBLE_CAUSE = "SINGLE_PLAUSIBLE_CAUSE"
    NO_INDEPENDENT_CRITIQUE = "NO_INDEPENDENT_CRITIQUE"
    NO_INVERTED_RETRIEVAL = "NO_INVERTED_RETRIEVAL"
    ADJUDICATED_BY_MODEL_OPINION = "ADJUDICATED_BY_MODEL_OPINION"
    CRITIQUE_BELOW_CALIBRATED_DIVERGENCE = "CRITIQUE_BELOW_CALIBRATED_DIVERGENCE"


@dataclass(frozen=True)
class RevisionGateVerdict:
    governs: bool
    refusals: tuple[tuple[RevisionPrecondition, str], ...] = ()
    gate_verdicts: tuple[GateVerdict, ...] = field(default_factory=tuple)

    @property
    def permitted(self) -> bool:
        return not self.refusals

    @property
    def codes(self) -> frozenset[RevisionPrecondition]:
        return frozenset(code for code, _ in self.refusals)


class RevisionPreconditionFailed(RuntimeError):
    def __init__(self, verdict: RevisionGateVerdict) -> None:
        super().__init__(
            "the transition may not enter BELIEF_REVISION: "
            + "; ".join(f"{code.value}: {detail}" for code, detail in verdict.refusals)
        )
        self.verdict = verdict


History = Callable[[str, str], Sequence[BeliefRevisionEvent]]
#: Given a set id, the LLM-002 verdict on that set's debate divergence.
DivergenceGate = Callable[[str], GateVerdict]


class HypothesisRevisionGate:
    """Reads the certificate, set, critiques and history; decides nothing about evidence."""

    def __init__(
        self,
        *,
        hypotheses: HypothesisStore,
        critiques: DebateStore,
        history: History,
        divergence_gate: DivergenceGate | None = None,
    ) -> None:
        self._hypotheses = hypotheses
        self._critiques = critiques
        self._history = history
        self._divergence_gate = divergence_gate

    def evaluate(
        self,
        *,
        project_id: str,
        hypothesis_id: str,
        to_state: BeliefState,
        triggering_attestations: Sequence[Attestation],
        at: dt.datetime,
    ) -> RevisionGateVerdict:
        certificate = self._hypotheses.get_certificate(hypothesis_id)
        if certificate is None or certificate.hypothesis.project_id != project_id:
            return RevisionGateVerdict(governs=False)
        hypothesis_set = self._hypotheses.get_set(certificate.hypothesis_set_id)
        assert hypothesis_set is not None  # `005e`'s foreign key; the in-memory store checks it

        refusals: list[tuple[RevisionPrecondition, str]] = []

        if to_state is BeliefState.SUPPORTED and hypothesis_set.root_cause:
            admitted = [
                c.hypothesis_id
                for c in self._hypotheses.certificates_in_set(hypothesis_set.set_id)
                if self._admitted(project_id, c.hypothesis_id)
            ]
            if len(admitted) < 2:
                refusals.append(
                    (
                        RevisionPrecondition.SINGLE_PLAUSIBLE_CAUSE,
                        f"root-cause set {hypothesis_set.set_id} holds {len(admitted)} admitted "
                        f"hypothesis ({admitted}); EPI-001 forbids upgrading a single plausible "
                        "cause directly to a confirmed root cause",
                    )
                )

        independent = [
            c
            for c in self._critiques.critiques_targeting(project_id, hypothesis_id)
            if c.differs_in and c.created_at <= at
        ]
        is_reject = to_state is BeliefState.CONTRADICTED
        if is_reject and not independent:
            refusals.append(
                (
                    RevisionPrecondition.NO_INDEPENDENT_CRITIQUE,
                    f"{hypothesis_id} would be REJECTED (-> CONTRADICTED) and no independent "
                    "critique targets it. §7.6: 重大 REJECT 必須經 independent critique path",
                )
            )
        inverted = [c for c in independent if c.inverted_bundle_id is not None]
        if hypothesis_set.inverted_retrieval_required and not inverted:
            refusals.append(
                (
                    RevisionPrecondition.NO_INVERTED_RETRIEVAL,
                    f"set {hypothesis_set.set_id} was debated at stakes {hypothesis_set.stakes} "
                    f"under {hypothesis_set.source_policy_id}@"
                    f"{hypothesis_set.source_policy_version}"
                    ", which requires the Critic's inverted retrieval, and no critique with an "
                    "inverted bundle targets this hypothesis (SRC-002, §7.2)",
                )
            )

        if is_reject or hypothesis_set.inverted_retrieval_required:
            factual = [
                a for a in triggering_attestations if a.epistemic_type in FACTUAL_EPISTEMIC_TYPES
            ]
            if not factual:
                refusals.append(
                    (
                        RevisionPrecondition.ADJUDICATED_BY_MODEL_OPINION,
                        f"the transition of {hypothesis_id} rests on "
                        f"{len(triggering_attestations)} attestation(s), none of them external "
                        "evidence or a verification result. §7.6: the adjudication MUST cite "
                        "external evidence or a verification result, not another model opinion",
                    )
                )

        verdicts: list[GateVerdict] = []
        if self._divergence_gate is not None and hypothesis_set.inverted_retrieval_required:
            verdict = self._divergence_gate(hypothesis_set.set_id)
            verdicts.append(verdict)
            if verdict.blocks:
                refusals.append(
                    (RevisionPrecondition.CRITIQUE_BELOW_CALIBRATED_DIVERGENCE, verdict.detail)
                )

        return RevisionGateVerdict(
            governs=True, refusals=tuple(refusals), gate_verdicts=tuple(verdicts)
        )

    def require(
        self,
        *,
        project_id: str,
        hypothesis_id: str,
        to_state: BeliefState,
        triggering_attestations: Sequence[Attestation],
        at: dt.datetime,
    ) -> RevisionGateVerdict:
        verdict = self.evaluate(
            project_id=project_id,
            hypothesis_id=hypothesis_id,
            to_state=to_state,
            triggering_attestations=triggering_attestations,
            at=at,
        )
        if not verdict.permitted:
            raise RevisionPreconditionFailed(verdict)
        return verdict

    def _admitted(self, project_id: str, hypothesis_id: str) -> bool:
        return any(e.from_state is None for e in self._history(project_id, hypothesis_id))


__all__ = [
    "DivergenceGate",
    "History",
    "HypothesisRevisionGate",
    "RevisionGateVerdict",
    "RevisionPrecondition",
    "RevisionPreconditionFailed",
]
