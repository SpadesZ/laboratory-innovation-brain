"""The Causal Warrant Gate's sources, over PostgreSQL: one builder for every composition root.

The research service, its read side and the vertical test harness all resolve warrants the same
way -- certificates, attestations, observations and runs from their own stores, grants from
`012o` -- so the write path and the read path can never disagree about what a relation's warrant
or evidence line is. Each caller names the declaration sets its vertical registers, and the review
authorities whose enrolled reviewers' signatures it accepts (`012p`).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from lab_brain.core.models.failure import FailureAnalysis
from lab_brain.core.models.warrant import DiagnosticDeclarationSet, Link
from lab_brain.core.repositories.evidence import SqlAttestationStore, SqlRelationStore
from lab_brain.core.repositories.failures import ConfirmationVerifier
from lab_brain.core.repositories.hypotheses import SqlHypothesisStore
from lab_brain.core.repositories.jobs import SqlJobStore
from lab_brain.core.repositories.observations import SqlObservationStore
from lab_brain.core.repositories.warrants import SqlDiagnosticWarrantStore
from lab_brain.core.warrant import EpisodeOutcomes, WarrantResolver
from lab_brain.security.reviewer_identity import ReviewerTrust, grant_authenticator


def sql_warrant_resolver(
    connection: Any,
    *,
    declaration_sets: Sequence[DiagnosticDeclarationSet],
    active: str | None,
    trust: ReviewerTrust,
) -> WarrantResolver:
    """The resolver every composition root uses. `trust` is the deployment's pinned review
    authorities: an answer counts only if its reviewer's signature verifies under them, and an
    empty trust -- no authority configured -- counts no answer at all."""
    grants = SqlDiagnosticWarrantStore(connection)
    return WarrantResolver(
        certificates=SqlHypothesisStore(connection).get_certificate,
        attestations=SqlAttestationStore(connection).get,
        observations=SqlObservationStore(connection).get,
        runs=SqlJobStore(connection).get_run,
        grants=grants,
        authenticate=grant_authenticator(grants, trust),
        relations=SqlRelationStore(connection).get,
        declaration_sets=declaration_sets,
        active=active,
    )


def confirmation_verifier(
    connection: Any,
    trust: ReviewerTrust,
    *,
    declaration_sets: Sequence[DiagnosticDeclarationSet],
) -> ConfirmationVerifier:
    """Whether a stored confirmation may inform case memory and the miner (V1.1).

    The database refused it unless the confirmation rule held over the recorded evidence (`012p`),
    but SQL cannot check a signature. So every reviewer answer recorded on any relation of any
    member of the cause's hypothesis set must verify -- an answer that does not was counted by
    nothing the loop did, and the database cannot tell; a confirmation that it could have shaped
    is not relied on. Conservative by design: one bad answer in the set withholds the conclusion
    from reuse, never from the record.

    A DOMAIN warrant (`dds:`) must name a class of a declaration set this code registers: SQL
    accepted it against whatever the table held, and only the code is the domain's declaration.
    """
    store = SqlDiagnosticWarrantStore(connection)
    authenticate = grant_authenticator(store, trust)
    declared = {s.domain_ref(d) for s in declaration_sets for d in s.declarations}

    def verify(analysis: FailureAnalysis) -> str | None:
        for ref in analysis.warrant_refs:
            if ref.startswith("dds:") and ref not in declared:
                return f"its DOMAIN warrant {ref} names no declaration this code registers"
        rows = connection.execute(
            "SELECT g.grant_id FROM diagnostic_warrant_grants g"
            " JOIN hypotheses h ON h.hypothesis_id = g.hypothesis_id"
            " JOIN hypotheses c ON c.hypothesis_set_id = h.hypothesis_set_id"
            " WHERE c.project_id = %s AND c.hypothesis_id = %s AND g.project_id = %s"
            " ORDER BY g.grant_id",
            (analysis.project_id, analysis.confirmed_root_cause, analysis.project_id),
        ).fetchall()
        for (grant_id,) in rows:
            grant = store.grant(analysis.project_id, str(grant_id))
            why = "not readable" if grant is None else authenticate(grant)
            if why is not None:
                return f"the answer {grant_id} in its hypothesis set does not verify: {why}"
        return None

    return verify


def episode_outcomes(connection: Any) -> EpisodeOutcomes:
    """Every outcome the episode's own runs observed, as (observation, observable, space, version,
    outcome) -- read off the attestations, so an outcome nobody predicted is seen too."""

    def read(project_id: str, episode_id: str) -> tuple[tuple[str, Link], ...]:
        rows = connection.execute(
            "SELECT o.observation_id, o.metric_or_event, a.method ->> 'outcome_space',"
            " a.method ->> 'outcome'"
            " FROM attestations a"
            " JOIN observations o ON o.observation_id = a.observation_id"
            " JOIN runs r ON r.run_id = o.run_id"
            " JOIN jobs j ON j.job_id = r.job_id"
            " WHERE a.project_id = %s AND j.episode_id = %s"
            " ORDER BY o.observation_id",
            (project_id, episode_id),
        ).fetchall()
        found: list[tuple[str, Link]] = []
        for observation_id, observable, space, outcome in rows:
            if not space or "@" not in str(space) or outcome is None:
                continue
            space_id, version = str(space).rsplit("@", 1)
            found.append((str(observation_id), (str(observable), space_id, version, str(outcome))))
        return tuple(found)

    return read


__all__ = ["confirmation_verifier", "episode_outcomes", "sql_warrant_resolver"]
