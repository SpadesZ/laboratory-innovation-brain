"""Whether a stored confirmation may be relied on: re-derived from the record, not re-read (V1.1).

WHY RE-DERIVE. `012p` refuses a CONFIRMED row unless the confirmation rule holds over the recorded
evidence -- for every writer that goes through its triggers. It cannot see two things: whether a
reviewer's signature verifies, and whether a belief event it reads is one a governed decision
re-derives. Every process here holds a superuser credential, so a writer can also step past the
triggers altogether. Case memory and the miner therefore do not take a CONFIRMED row's word for it:
before relying on one, this re-derives the conclusion in Python.

    1. every reviewer answer in the cause's hypothesis set verifies, and every DOMAIN warrant names
       a declaration the code registers (`storage.postgres.warrants.confirmation_verifier`);
    2. the loop's own rule (`verification.loop.ConfirmationRule`), applied over the VERIFIED
       projection -- every stored decision re-derived, every warrant re-checked against its
       source -- confirms exactly this cause now;
    3. the warrants the row cites are warrants the verified record gives that cause's support.

A forged event, a forged row or an unverifiable answer fails one of these. A refusal withholds the
conclusion from reuse and says why; it never edits the record. "Now" is deliberate: a conclusion
that later evidence would no longer confirm is not one to generalise from.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from lab_brain.core.authority import AuthorityPolicy
from lab_brain.core.episode import BeliefEpisode
from lab_brain.core.models.base import utc_now
from lab_brain.core.models.belief_event import BeliefState
from lab_brain.core.models.enums import RelationType
from lab_brain.core.models.failure import FailureAnalysis
from lab_brain.core.models.hypothesis_set import HypothesisCertificate, HypothesisSet
from lab_brain.core.models.relation import RelationJudgment
from lab_brain.core.models.warrant import DiagnosticDeclarationSet
from lab_brain.core.repositories.belief_events import (
    SqlBeliefEventStore,
    SqlBeliefTransitionDecisionStore,
    SqlTransitionPolicyStore,
)
from lab_brain.core.repositories.conflicts import SqlConflictStore
from lab_brain.core.repositories.evidence import SqlAttestationStore, SqlRelationStore
from lab_brain.core.repositories.failures import ConfirmationVerifier
from lab_brain.core.repositories.hypotheses import SqlHypothesisStore
from lab_brain.core.repositories.reviews import SqlReviewItemStore
from lab_brain.core.warrant import EpisodeOutcomes
from lab_brain.security.reviewer_identity import ReviewerTrust
from lab_brain.storage.postgres.warrants import (
    confirmation_verifier as answers_and_declarations,
)
from lab_brain.storage.postgres.warrants import episode_outcomes, sql_warrant_resolver
from lab_brain.verification.loop import ConfirmationRule


class _NoIds:
    """A reader writes nothing, so it mints nothing; asking is a defect."""

    def __getattr__(self, name: str) -> Any:
        raise RuntimeError(f"the confirmation re-check wrote something ({name})")


@dataclass(frozen=True)
class _Reads:
    belief: BeliefEpisode
    evidence: SqlRelationStore
    declarations: DiagnosticDeclarationSet | None
    episode_outcomes: EpisodeOutcomes | None
    relations_from: Callable[[str, str], Sequence[RelationJudgment]] | None
    now: Callable[[], dt.datetime]


@dataclass(frozen=True)
class _Query:
    project_id: str
    episode_id: str
    hypothesis_set: HypothesisSet
    certificates: tuple[HypothesisCertificate, ...]


def confirmation_verifier(
    connection: Any,
    *,
    trust: ReviewerTrust,
    declaration_sets: Sequence[DiagnosticDeclarationSet],
    active: str | None,
    authority_policies: Mapping[tuple[str, str], AuthorityPolicy],
    now: Callable[[], dt.datetime] = utc_now,
) -> ConfirmationVerifier:
    """The deployment's reuse check, for `SqlFailureStore(verify=...)` and the episode page."""
    first = answers_and_declarations(connection, trust, declaration_sets=declaration_sets)
    relations = SqlRelationStore(connection)
    hypotheses = SqlHypothesisStore(connection)
    belief = BeliefEpisode(
        policies=SqlTransitionPolicyStore(connection),
        decisions=SqlBeliefTransitionDecisionStore(connection),
        events=SqlBeliefEventStore(connection),
        relations=relations,
        authority_classes=SqlAttestationStore(connection),
        conflicts=SqlConflictStore(connection),
        reviews=SqlReviewItemStore(connection),
        ids=_NoIds(),
        authority_policies=authority_policies,
        warrants=sql_warrant_resolver(
            connection, declaration_sets=declaration_sets, active=active, trust=trust
        ),
    )
    rule = ConfirmationRule(
        _Reads(
            belief=belief,
            evidence=relations,
            declarations=next((s for s in declaration_sets if s.ref == active), None),
            episode_outcomes=episode_outcomes(connection),
            relations_from=relations.from_observation,
            now=now,
        )
    )

    def verify(analysis: FailureAnalysis) -> str | None:
        refused = first(analysis)
        if refused is not None:
            return refused
        cause = analysis.confirmed_root_cause
        certificate = (
            None if cause is None else hypotheses.get_certificate(analysis.project_id, cause)
        )
        hypothesis_set = (
            None if certificate is None else hypotheses.get_set(certificate.hypothesis_set_id)
        )
        if cause is None or certificate is None or hypothesis_set is None:
            return f"{analysis.failure_analysis_id} names no admitted cause to re-derive"
        query = _Query(
            project_id=analysis.project_id,
            episode_id=analysis.episode_id,
            hypothesis_set=hypothesis_set,
            certificates=hypotheses.certificates_in_set(hypothesis_set.set_id),
        )
        try:
            standing = rule.standing(query)
            view = belief.hypothesis_view(
                project_id=analysis.project_id,
                hypothesis_id=cause,
                current_state=BeliefState.SUPPORTED,
                stakes=hypothesis_set.stakes,
                admitted_relations=relations.admitted_for_subject(analysis.project_id, cause),
            )
        except Exception as exc:  # a history that does not re-verify is a refusal, not a pass
            return f"the belief history behind {cause} does not re-verify: {exc}"
        if standing.confirmable != cause:
            why = "; ".join(standing.notes) or "no member is confirmable"
            return (
                f"re-derived over the verified record, the confirmation rule does not confirm "
                f"{cause} now: {why}"
            )
        given = {
            r.warrant_ref
            for r in view.relation_evidence
            if r.relation_type is RelationType.SUPPORTS and r.warrant_ref is not None
        }
        if not set(analysis.warrant_refs) <= given:
            extra = sorted(set(analysis.warrant_refs) - given)
            return f"it cites {', '.join(extra)}, which the verified record does not give {cause}"
        return None

    return verify


__all__ = ["confirmation_verifier"]
