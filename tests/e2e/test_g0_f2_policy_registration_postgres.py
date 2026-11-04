"""G0 finding F2: the services' role must not be able to register a transition policy.

THE ATTACK (`docs/audit/g0-security-assurance-2026-11-04/REPORT.md`, finding F2). Acting as the
deployment's least-privilege services' role -- created exactly as a deployment creates it
(`deployment/docker/service_roles.py`, then `lab-brain admin db-roles`, i.e.
`grant_database_roles`) -- a writer:

    1. registers an `ACTIVE -> SUPPORTED` transition policy that requires nothing;
    2. runs the product's own governed `BeliefEpisode` under it, which records an ALLOW decision
       and a belief event that re-derive from their own (empty) snapshot;
    3. leaves the honest, product-wired projection (`BeliefEpisode.project`, which feeds the loop's
       state, the confirmation re-check and the episode report's final state) to read SUPPORTED.

No forged support, no signature and no relation is needed: whoever holds the services' credentials
could make any hypothesis SUPPORTED. The R8 projection fix re-checks the SUPPORTS in a decision's
snapshot; an empty snapshot has nothing to re-check.

The test below asserts the SECURE behaviour: step 1 is refused by the database, and the honest
projection never reads SUPPORTED. Engineering evidence only. G0 is NOT PASSED.
"""

from __future__ import annotations

import uuid
from typing import Any

import psycopg
import pytest

from lab_brain.core.models import BeliefState, TransitionPolicy
from lab_brain.core.repositories import SqlTransitionPolicyStore
from lab_brain.core.repositories.evidence import SqlAttestationStore, SqlRelationStore
from tests.e2e.test_g0_screening_independence_postgres import Guarded
from tests.e2e.test_g0_screening_independence_postgres import guarded as guarded
from tests.e2e.test_g0_screening_independence_postgres import standin as standin
from tests.e2e.test_g0_security_assurance_postgres import (
    _accepting,
    _attempt,
    _episode,
    _product_relations,
)
from tests.e2e.test_research_episode_postgres import PROJECT
from tests.integration import test_g0_spend_admin_postgres as _roles

pytestmark = pytest.mark.postgres

# The deployment's least-privilege roles, created and dropped per test (`lab-brain admin db-roles`).
su = _roles.su
roles = _roles.roles

#: The database's refusals that count: no privilege, or the owner-only guard. Anything else (a
#: duplicate key, say) is not the boundary and must not pass for it.
REFUSALS = (psycopg.errors.InsufficientPrivilege, psycopg.errors.RaiseException)


def empty_promote() -> TransitionPolicy:
    """What the services' role tries to register: a promotion that requires nothing at all
    (a fresh id per test, so a policy left by an earlier run is never mistaken for a refusal)."""
    return TransitionPolicy(
        policy_id=f"policy:g0-f2-services-written-{uuid.uuid4().hex[:12]}",
        version="1.0.0",
        from_state=BeliefState.ACTIVE,
        candidate_to_state=BeliefState.SUPPORTED,
    )


def _registered(c: Any, policy: TransitionPolicy) -> bool:
    return SqlTransitionPolicyStore(c).get(policy.policy_id, policy.version) is not None


def _attack(g: Guarded, app: Any, policy: TransitionPolicy) -> tuple[Exception | None, Any]:
    """The whole F2 chain as the services' role; the database's refusal, if any, and the
    honest product projection afterwards."""
    refused: Exception | None = None
    try:
        SqlTransitionPolicyStore(app).register(policy)
    except psycopg.Error as exc:  # the database's own refusal
        refused = exc
    print(f"F2: services role registering {policy.policy_id}: refused={refused!r}")
    if refused is None:
        written = _attempt(
            _episode(app, SqlRelationStore(app, support_verifier=_accepting), g.keys.trust),
            g,
            policy.policy_id,
            policy.version,
            # An event cites a trigger; any admitted attestation of the project will do (here the
            # screening measurement the hypothesis was conditioned on -- not a support).
            (SqlAttestationStore(app).get(PROJECT, g.attestation),),
        )
        print(
            f"F2: services-role transition {written.authorization.result}"
            f" event={None if written.event is None else written.event.event_id}"
            " snapshot relations="
            f"{list(written.authorization.decision_input_snapshot.admitted_relations)}"
        )
    honest = _episode(g.db, _product_relations(g), g.keys.trust)
    projection = honest.project(project_id=PROJECT, hypothesis_id=g.hypothesis)
    print(f"F2: honest product projection of {g.hypothesis} -> {projection.current_state}")
    return refused, projection


@pytest.mark.xfail(
    strict=True,
    reason=(
        "G0 finding F2 is OPEN: grant_database_roles grants INSERT on transition_policies to the "
        "services' role and migration 005b refuses only UPDATE and DELETE, so the services' role "
        "registers an empty ACTIVE->SUPPORTED policy and the honest projection reads SUPPORTED. "
        "The fix (owner-only policy registration) awaits the Owner's decision."
    ),
)
def test_the_services_role_cannot_register_a_policy_that_makes_a_hypothesis_supported(
    guarded, roles
):
    g = guarded
    before = _episode(g.db, _product_relations(g), g.keys.trust).project(
        project_id=PROJECT, hypothesis_id=g.hypothesis
    )
    assert before.current_state is not BeliefState.SUPPORTED
    policy = empty_promote()
    with roles.connect(roles.app) as app:
        refused, projection = _attack(g, app, policy)
    assert refused is not None, "the services' role registered a transition policy"
    assert isinstance(refused, REFUSALS), refused
    assert not _registered(g.db, policy)
    assert projection.current_state is not BeliefState.SUPPORTED
    assert projection.current_state is before.current_state
