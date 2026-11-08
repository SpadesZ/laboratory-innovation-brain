"""G0 security assurance: no consequential reader counts a post-screening SUPPORTS whose
verification authorization does not verify -- and every one still counts a signed one.

P2 (`g0-authorization-read-path-closure`) closed `SqlRelationStore.admitted_for_subject` and gave
the product's relation readers a verifier. Its tests prove one kind of bad authorization (a
forged signature) against the store and the loop's sink. This module re-asks the question
independently, for EVERY kind of bad authorization a writer holding the services' role can put in
the database, against EVERY consequential reader, through the readers' own product wiring:

    R1  transition inputs     `SqlRelationStore(support_verifier=...)`.admitted_for_subject
    R2  confirmation rule     `SqlEvidenceSink` -> the verification loop's `admitted_for_subject`
    R3  belief transition     `BeliefEpisode.attempt_transition`: the recorded decision snapshot
    R4  confirmation re-check `research.confirmation.confirmation_verifier`'s own relation store
    R5  episode view / report `episode_view._not_counted` ("recorded as support, but not counted")
    R6  acceptance scoring    `evaluation.collect.support_provenance` (scorer 2.3.0's facts)
    R7  evidence write path   `ProspectiveEvidenceSink`: recorded as CITES, never SUPPORTS
    R8  belief projection     `BeliefEpisode.project` -> `verified_history`: a decision row whose
                              snapshot carries such a SUPPORTS is refused (the bypass found here)

Bad authorizations the database ADMITS (SQL cannot verify Ed25519) -- each must be refused by
every reader above:

    forged_signature        a signature nobody with the person's key made
    rogue_authority         a correct signature, under a key that an UNPINNED authority enrolled
                            (the services' role can write enrolment rows; the pin is outside SQL)
    tampered_payload        a genuine signature over another rationale than the stored row's
    replayed_signature      a genuine signature of another authorization copied onto this row
    revoked_before_signing  a genuine signature under a key the authority later revoked with
                            effect before it signed

Bad authorizations the database REFUSES at write -- asserted so the readers' tests above do not
silently rest on an assumption about SQL: unsigned, another person's enrolment, no authorization
bound to the run, an authorization of another hypothesis, an authorization in another project,
and one authorization bound to a second job.

Engineering evidence only. G0 is NOT PASSED.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from lab_brain.core.belief import UnverifiedBeliefRevision, VerificationFailure
from lab_brain.core.episode import BeliefEpisode
from lab_brain.core.models import BeliefState, RelationType, TransitionPolicy, TransitionReason
from lab_brain.core.models.relation import RelationJudgment
from lab_brain.core.repositories import SqlBeliefEventStore, SqlTransitionPolicyStore
from lab_brain.core.repositories.belief_events import SqlBeliefTransitionDecisionStore
from lab_brain.core.repositories.conflicts import SqlConflictStore
from lab_brain.core.repositories.evidence import SqlAttestationStore, SqlRelationStore
from lab_brain.core.repositories.reviews import SqlReviewItemStore
from lab_brain.domains.silicon_photonics import vertical as sp
from lab_brain.domains.silicon_photonics.authority_policy import SiliconPhotonicsAuthorityPolicy
from lab_brain.domains.silicon_photonics.product import (
    diagnostic_declaration_set,
    product_vertical,
)
from lab_brain.evaluation.collect import support_provenance
from lab_brain.research.confirmation import confirmation_verifier
from lab_brain.research.episode_view import _not_counted
from lab_brain.research.service import declared_policies
from lab_brain.security.reviewer_identity import ReviewerTrust, SigningKey
from lab_brain.storage.postgres.verification_evidence import SqlEvidenceSink
from lab_brain.storage.postgres.warrants import sql_warrant_resolver
from lab_brain.verification import prospective
from tests.authorizer_keys import AUTHORITY_ACTOR, AuthorizerKeys
from tests.e2e.test_g0_exploratory_screening_postgres import rows
from tests.e2e.test_g0_forged_authorization_read_path_postgres import _digest, _support_as
from tests.e2e.test_g0_screening_independence_postgres import PROBE_METHOD, Guarded
from tests.e2e.test_g0_screening_independence_postgres import guarded as guarded
from tests.e2e.test_g0_screening_independence_postgres import standin as standin
from tests.e2e.test_research_episode_postgres import PROJECT
from tests.integration import test_g0_spend_admin_postgres as _roles

pytestmark = pytest.mark.postgres

su = _roles.su
roles = _roles.roles

PROBE = sp.CAP_FOURPOINT_PROBE

AUTHORITY = sp.VerticalAuthorityPolicy()

#: The bad authorizations the database admits; every reader must refuse each one.
ADMITTED_BAD = (
    "forged_signature",
    "rogue_authority",
    "tampered_payload",
    "replayed_signature",
    "revoked_before_signing",
)


# -- writing authorizations as the services' role ------------------------------------------------


def _insert(
    c: Any,
    g: Guarded,
    authorization_id: str,
    *,
    enrolment_id: str | None,
    signature: str | None,
    signed_at: dt.datetime | None,
    rationale: str,
    actor: str | None = None,
    project_id: str = PROJECT,
    hypothesis_id: str | None = None,
    episode_id: str | None = None,
) -> str:
    c.execute(
        "INSERT INTO verification_authorizations (authorization_id, project_id, episode_id,"
        " hypothesis_id, prediction_ids, capability_id, declaration_hash, actor_id, rationale,"
        " created_at, enrolment_id, signature, signed_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now(), %s, %s, %s)",
        (
            authorization_id,
            project_id,
            episode_id or g.episode,
            hypothesis_id or g.hypothesis,
            [g.prediction()],
            PROBE,
            _digest(g),
            actor or g.actor,
            rationale,
            enrolment_id,
            signature,
            signed_at,
        ),
    )
    return authorization_id


def _signed(
    g: Guarded,
    keys: AuthorizerKeys,
    authorization_id: str,
    rationale: str,
    *,
    actor: str | None = None,
) -> tuple[str, str, dt.datetime]:
    """(enrolment_id, signature, signed_at) a person enrolled under `keys` makes for this row."""
    return keys.signed_columns(
        keys.signer(PROJECT, actor or g.actor),
        authorization_id=authorization_id,
        project_id=PROJECT,
        episode_id=g.episode,
        hypothesis_id=g.hypothesis,
        prediction_ids=[g.prediction()],
        capability_id=PROBE,
        declaration_hash=_digest(g),
        rationale=rationale,
    )


def _bad_authorization(kind: str, app: Any, g: Guarded) -> str:
    """As the services' role: an authorization of `kind` that the database admits."""
    name = f"vauth:{kind}-{uuid.uuid4().hex[:8]}"
    if kind == "forged_signature":
        signer = g.keys.signer(PROJECT, g.actor)
        return _insert(
            app,
            g,
            name,
            enrolment_id=signer.enrolment_id,
            signature=SigningKey.generate().sign(b"a statement the person never signed"),
            signed_at=dt.datetime.now(dt.UTC),
            rationale="forged",
        )
    if kind == "rogue_authority":
        # A throwaway authority the deployment never pinned, enrolling a key for the real person
        # under the real authority's actor id. The enrolment row is written by the services' role.
        rogue = AuthorizerKeys(app, authority_actor=AUTHORITY_ACTOR)
        enrolment, signature, signed_at = _signed(g, rogue, name, "rogue")
        return _insert(
            app,
            g,
            name,
            enrolment_id=enrolment,
            signature=signature,
            signed_at=signed_at,
            rationale="rogue",
        )
    if kind == "tampered_payload":
        enrolment, signature, signed_at = _signed(g, g.keys, name, "what the person signed")
        return _insert(
            app,
            g,
            name,
            enrolment_id=enrolment,
            signature=signature,
            signed_at=signed_at,
            rationale="what the row now says",
        )
    if kind == "replayed_signature":
        original = f"{name}-original"
        enrolment, signature, signed_at = _signed(g, g.keys, original, "the original")
        _insert(
            app,
            g,
            original,
            enrolment_id=enrolment,
            signature=signature,
            signed_at=signed_at,
            rationale="the original",
        )
        return _insert(
            app,
            g,
            name,
            enrolment_id=enrolment,
            signature=signature,
            signed_at=signed_at,
            rationale="the original",
        )
    raise AssertionError(kind)


def _bad_support(kind: str, g: Guarded, roles: Any) -> str:
    """A SUPPORTS of the post-screening rival, resting on a `kind` authorization, admitted by the
    database. Returns the relation id."""
    if kind == "revoked_before_signing":
        authorization = g.authorize(f"revoked-{uuid.uuid4().hex[:8]}")
        observation, evidence = g.measured(authorization, authorization=authorization)
        with roles.connect(roles.app) as app:
            relation = _support_as(app, g, observation, evidence)
        ((signed_at,),) = rows(
            g.db,
            "SELECT signed_at FROM verification_authorizations WHERE authorization_id = %s",
            authorization,
        )
        # The authority learns the key was compromised before this authorization was signed.
        g.keys.revoke(
            PROJECT,
            g.keys.signer(PROJECT, g.actor),
            effective_at=signed_at - dt.timedelta(seconds=1),
        )
        return relation
    with roles.connect(roles.app) as app:
        authorization = _bad_authorization(kind, app, g)
        observation, evidence = g.measured(authorization, authorization=authorization)
        relation = _support_as(app, g, observation, evidence)
    assert rows(
        g.db, "SELECT relation_type FROM relation_judgments WHERE relation_id = %s", relation
    ) == [("SUPPORTS",)], "the database must admit it, or this test proves nothing about readers"
    return relation


def _good_support(g: Guarded) -> str:
    authorization = g.authorize(f"good-{uuid.uuid4().hex[:8]}")
    observation, evidence = g.measured(authorization, authorization=authorization)
    g.support(observation, [evidence], prediction=g.prediction())
    return f"rel:{observation}"


# -- the readers, as the product wires them ------------------------------------------------------


class _Ids:
    def decision_id(self) -> str:
        return f"dec:sa-{uuid.uuid4().hex}"

    def event_id(self) -> str:
        return f"bre:sa-{uuid.uuid4().hex}"

    def conflict_id(self) -> str:
        return f"cfl:sa-{uuid.uuid4().hex}"

    def review_id(self) -> str:
        return f"rev:sa-{uuid.uuid4().hex}"


def _episode(c: Any, relations: Any, trust: ReviewerTrust) -> BeliefEpisode:
    """`ResearchEpisodeService._brain`'s BeliefEpisode, over `relations` (no review queue: this
    module asks what a decision READS, not who is asked about it)."""
    authority = sp.VerticalAuthorityPolicy()
    v1 = SiliconPhotonicsAuthorityPolicy()
    declarations = diagnostic_declaration_set()
    return BeliefEpisode(
        policies=SqlTransitionPolicyStore(c),
        decisions=SqlBeliefTransitionDecisionStore(c),
        events=SqlBeliefEventStore(c),
        relations=relations,
        authority_classes=SqlAttestationStore(c),
        conflicts=SqlConflictStore(c),
        reviews=SqlReviewItemStore(c),
        ids=_Ids(),
        authority_policies={
            (v1.policy_id, v1.policy_version): v1,
            (authority.policy_id, authority.policy_version): authority,
        },
        warrants=sql_warrant_resolver(
            c, declaration_sets=(declarations,), active=declarations.ref, trust=trust
        ),
    )


def _product_relations(g: Guarded) -> SqlRelationStore:
    return SqlRelationStore(
        g.db, support_verifier=prospective.prospective_support_verifier(g.db, g.keys.trust)
    )


def _attempt(
    episode: BeliefEpisode, g: Guarded, policy_id: str, version: str, triggering: Any = ()
) -> Any:
    return episode.attempt_transition(
        project_id=PROJECT,
        hypothesis_id=g.hypothesis,
        policy_id=policy_id,
        policy_version=version,
        candidate_to_state=BeliefState.SUPPORTED,
        stakes="HIGH",
        occurred_at=dt.datetime.now(dt.UTC),
        trace_id=f"trc:sa-{uuid.uuid4().hex[:8]}",
        episode_id=g.episode,
        actor_id=g.actor,
        authority_policy_ref=(AUTHORITY.policy_id, AUTHORITY.policy_version),
        triggering_attestations=triggering,
    )


def _recheck_store(g: Guarded) -> SqlRelationStore:
    """The relation store `research.confirmation.confirmation_verifier` decides from -- taken out
    of the verifier the product builds, not rebuilt here, so this reads what the re-check reads."""
    declarations = diagnostic_declaration_set()
    authority = sp.VerticalAuthorityPolicy()
    verify = confirmation_verifier(
        g.db,
        trust=g.keys.trust,
        declaration_sets=(declarations,),
        active=declarations.ref,
        authority_policies={(authority.policy_id, authority.policy_version): authority},
        declared_policies=declared_policies(
            product_vertical(
                outputs=None, jobs=None, broker=None, now=lambda: dt.datetime.now(dt.UTC)
            )
        ),
    )
    stores = [
        cell.cell_contents
        for cell in verify.__closure__ or ()
        if isinstance(cell.cell_contents, SqlRelationStore)
    ]
    assert len(stores) == 1, stores
    return stores[0]


def _readers(g: Guarded, relation_id: str) -> dict[str, bool]:
    """For each consequential reader: does it COUNT `relation_id` as support?"""
    relation = SqlRelationStore(g.db).get(PROJECT, relation_id)
    assert relation is not None
    verifier = prospective.prospective_support_verifier(g.db, g.keys.trust)

    inputs = {
        r.relation_id for r in _product_relations(g).admitted_for_subject(PROJECT, g.hypothesis)
    }
    loop = SqlEvidenceSink(
        connection=g.db,
        outputs=None,  # type: ignore[arg-type]
        support_verifier=verifier,
    )
    rule = {r.relation_id for r in loop.admitted_for_subject(PROJECT, g.hypothesis)}

    # R3: what a governed attempt records as its decision's inputs, under the loop's own policy.
    decided = _attempt(
        _episode(g.db, _product_relations(g), g.keys.trust),
        g,
        sp.PROMOTE_MEASURED_POLICY_ID,
        sp.WARRANTED_VERTICAL_POLICY_VERSION,
    )
    snapshot = {
        r.relation_id for r in decided.authorization.decision_input_snapshot.admitted_relations
    }

    recheck = {r.relation_id for r in _recheck_store(g).admitted_for_subject(PROJECT, g.hypothesis)}
    shown = _not_counted(g.db, PROJECT, relation_id, "SUPPORTS", g.hypothesis, verifier) is None
    (fact,) = [
        f
        for f in support_provenance(g.db, g.hypothesis, g.keys.trust)
        if f["relation_id"] == relation_id
    ]
    scored = not (fact["unverified_authorization"] or fact["unauthorized_verification"])

    # R7: the same outcome offered again through the product's write path.
    sink = prospective.ProspectiveEvidenceSink(
        SqlEvidenceSink(connection=g.db, outputs=None),  # type: ignore[arg-type]
        g.db,
        g.keys.trust,
    )
    again = relation.model_copy(update={"relation_id": f"{relation_id}:again"})
    stored = sink.add_relation(again)
    return {
        "R1 transition inputs": relation_id in inputs,
        "R2 confirmation rule": relation_id in rule,
        "R3 belief transition snapshot": relation_id in snapshot,
        "R4 confirmation re-check": relation_id in recheck,
        "R5 episode view": shown,
        "R6 acceptance scoring": scored,
        "R7 evidence write path": stored.relation_type is RelationType.SUPPORTS,
    }


# -- negative: every admitted bad authorization, every reader ------------------------------------


@pytest.mark.parametrize("kind", ADMITTED_BAD)
def test_no_reader_counts_a_support_on_a_bad_authorization(guarded, roles, kind):
    g = guarded
    relation = _bad_support(kind, g, roles)
    counted = _readers(g, relation)
    assert not any(counted.values()), f"{kind}: counted by {[k for k, v in counted.items() if v]}"
    # And the reason is the authorization, not something incidental.
    why = prospective.prospective_support_verifier(g.db, g.keys.trust)(
        SqlRelationStore(g.db).get(PROJECT, relation)  # type: ignore[arg-type]
    )
    assert why is not None and "011w" in why, why


def test_a_bad_support_reaches_no_transition_through_the_product_episode(guarded, roles):
    """R3 by outcome: with only a forged support on record, the loop's own promote policy has no
    SUPPORTS to count at all (not merely an unwarranted one)."""
    g = guarded
    _bad_support("forged_signature", g, roles)
    result = _attempt(
        _episode(g.db, _product_relations(g), g.keys.trust),
        g,
        sp.PROMOTE_MEASURED_POLICY_ID,
        sp.WARRANTED_VERTICAL_POLICY_VERSION,
    )
    assert result.event is None
    assert result.decision.reason_code is TransitionReason.MISSING_REQUIRED_RELATION_TYPE


# -- positive controls ------------------------------------------------------------------------


def test_every_reader_counts_a_correctly_signed_support(guarded):
    g = guarded
    relation = _good_support(g)
    counted = _readers(g, relation)
    assert all(counted.values()), f"not counted by {[k for k, v in counted.items() if not v]}"


def test_a_signed_support_reaches_the_product_episodes_decision(guarded):
    """R3 by outcome: with a signed support the loop's promote policy gets past "no SUPPORTS"
    (and stops at what the fixture does not supply) -- the support was read."""
    g = guarded
    relation = _good_support(g)
    result = _attempt(
        _episode(g.db, _product_relations(g), g.keys.trust),
        g,
        sp.PROMOTE_MEASURED_POLICY_ID,
        sp.WARRANTED_VERTICAL_POLICY_VERSION,
    )
    assert result.decision.reason_code is not TransitionReason.MISSING_REQUIRED_RELATION_TYPE
    assert relation in {
        r.relation_id for r in result.authorization.decision_input_snapshot.admitted_relations
    }


# -- the database's own refusals (so the reader tests above rest on nothing assumed) -----------


def _refused(g: Guarded, write: Callable[[], object], why: str) -> None:
    with (
        pytest.raises(psycopg.errors.RaiseException, match=why),
        g.db.transaction(force_rollback=True),
    ):
        write()


def test_the_database_refuses_an_unsigned_authorization(guarded, roles):
    g = guarded
    with (
        roles.connect(roles.app) as app,
        pytest.raises(psycopg.errors.RaiseException, match="unsigned"),
    ):
        _insert(
            app,
            g,
            "vauth:unsigned",
            enrolment_id=None,
            signature=None,
            signed_at=None,
            rationale="unsigned",
        )


def test_the_database_refuses_an_authorization_under_another_persons_enrolment(guarded, roles):
    g = guarded
    other = "act:sa-other-person"
    g.db.execute(
        "INSERT INTO actors (actor_id, actor_type, display_name) VALUES (%s, 'HUMAN', 'other')",
        (other,),
    )
    g.db.execute(
        "INSERT INTO project_memberships (project_id, actor_id, role) VALUES (%s, %s, 'MEMBER')"
        " ON CONFLICT DO NOTHING",
        (PROJECT, other),
    )
    enrolment, signature, signed_at = _signed(g, g.keys, "vauth:other", "x", actor=other)
    with (
        roles.connect(roles.app) as app,
        pytest.raises(psycopg.errors.RaiseException, match=r"is not .*authorizer key"),
    ):
        # Signed by `other`, under `other`'s enrolment, but in the episode person's name.
        _insert(
            app,
            g,
            "vauth:other",
            enrolment_id=enrolment,
            signature=signature,
            signed_at=signed_at,
            rationale="x",
        )


def test_the_database_refuses_a_support_with_no_authorization(guarded):
    g = guarded
    observation, evidence = g.measured("unbound")
    _refused(
        g,
        lambda: g.support(observation, [evidence], prediction=g.prediction()),
        "not pre-registered",
    )


def test_the_database_refuses_a_support_on_another_hypothesis_authorization(guarded):
    """An authorization is bound to one hypothesis: a correctly signed pre-registration of a
    sibling hypothesis licenses no support of the rival."""
    g = guarded
    ((other,),) = rows(
        g.db,
        "SELECT hypothesis_id FROM hypotheses WHERE created_in_episode = %s"
        " AND hypothesis_id <> %s ORDER BY hypothesis_id LIMIT 1",
        g.episode,
        g.hypothesis,
    )
    name = "vauth:sibling"
    enrolment, signature, signed_at = g.keys.signed_columns(
        g.keys.signer(PROJECT, g.actor),
        authorization_id=name,
        project_id=PROJECT,
        episode_id=g.episode,
        hypothesis_id=other,
        prediction_ids=[g.prediction()],
        capability_id=PROBE,
        declaration_hash=_digest(g),
        rationale="sibling",
    )
    # Refused when it is written: only a post-screening hypothesis is pre-registered (011s), and
    # a run bound to the rival's authorization supports no other conditioned hypothesis (rule (l),
    # `prospective_authorization_problem`: "authorized as a test of X, not of Y").
    with pytest.raises(psycopg.errors.RaiseException, match="was not proposed after screening"):
        _insert(
            g.db,
            g,
            name,
            enrolment_id=enrolment,
            signature=signature,
            signed_at=signed_at,
            rationale="sibling",
            hypothesis_id=other,
        )


def test_the_database_refuses_binding_one_authorization_to_a_second_job(guarded):
    """Replay of one pre-registration to a second run: one job per authorization."""
    g = guarded
    authorization = g.authorize("once")
    g.measured("once-first", authorization=authorization)
    with pytest.raises(psycopg.errors.UniqueViolation), g.db.transaction(force_rollback=True):
        g.measured("once-second", authorization=authorization)


def test_the_database_refuses_an_authorization_of_another_project(guarded, roles):
    """An authorization recorded in another project cannot license a job in this one."""
    g = guarded
    other = "prj:sa-other"
    g.db.execute(
        "INSERT INTO projects (project_id, name, privacy_mode) VALUES (%s, 'other', 'PRIVATE')"
        " ON CONFLICT DO NOTHING",
        (other,),
    )
    with (
        roles.connect(roles.app) as app,
        pytest.raises(psycopg.errors.RaiseException, match="was not proposed after screening"),
    ):
        # This project's hypothesis has no conditioning record in the other project.
        signer = g.keys.signer(PROJECT, g.actor)
        _insert(
            app,
            g,
            "vauth:other-project",
            enrolment_id=signer.enrolment_id,
            signature=SigningKey.generate().sign(b"x"),
            signed_at=dt.datetime.now(dt.UTC),
            rationale="other project",
            project_id=other,
        )


# -- R8: the belief projection (the bypass this assurance pass found) ---------------------------

#: A registered policy that counts SUPPORTS without a diagnostic warrant. It stands for any
#: decision whose snapshot holds a SUPPORTS that counted -- under the product's own 2.0.0 policies
#: that is a SUPPORTS that is also warranted (a DOMAIN link of a class-bound hypothesis, or a
#: reviewer's grant on the observed link, which says nothing about the pre-registration).
UNWARRANTED_PROMOTE = TransitionPolicy(
    policy_id="policy:g0-sa-promote-unwarranted",
    version="1.0.0",
    from_state=BeliefState.ACTIVE,
    candidate_to_state=BeliefState.SUPPORTED,
    required_relation_types=(RelationType.SUPPORTS,),
)


def _promote(g: Guarded, writer: Any, relations: Any, relation_id: str) -> Any:
    """As `writer`, through the governed episode over `relations`: ACTIVE -> SUPPORTED."""
    if (
        SqlTransitionPolicyStore(g.db).get(
            UNWARRANTED_PROMOTE.policy_id, UNWARRANTED_PROMOTE.version
        )
        is None
    ):
        SqlTransitionPolicyStore(g.db).register(UNWARRANTED_PROMOTE)
    return _attempt(
        _episode(writer, relations, g.keys.trust),
        g,
        UNWARRANTED_PROMOTE.policy_id,
        UNWARRANTED_PROMOTE.version,
        # The measurement the support rests on: admissible evidence for the event (SRC-002).
        (SqlAttestationStore(g.db).get(PROJECT, f"att:{relation_id.removeprefix('rel:')}"),),
    )


def _measured_support(g: Guarded, name: str, authorization: str, writer: Any) -> str:
    """A four-point probe reading recorded the way a calibrated measurement is (MEASURED,
    MEAS_CALIBRATED), on a run bound to `authorization`; its SUPPORTS written by `writer`."""
    export = g.artifact(f"probe export {name}", captured_at=g.later)
    run = g.run(
        name,
        authorization=authorization,
        capability_id=PROBE,
        backend_id="lab.probe_station",
        input_artifacts=(),
        input_parameters={"variant": name},
        output_artifacts=(export,),
    )
    observation = g.observe(run, name, sp.OBS_PROBE, "ELEVATED")
    with g.db.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute("SELECT * FROM attestations WHERE attestation_id = %s", (g.attestation,))
        row = cur.fetchone()
    assert row is not None
    row.update(
        attestation_id=f"att:{observation}",
        observation_id=observation,
        run_id=run,
        method=PROBE_METHOD,
        epistemic_type="MEASURED",
        authority_class=sp.MEAS_CALIBRATED,
    )
    row.pop("created_at", None)
    g.db.execute(
        f"INSERT INTO attestations ({', '.join(row)}) VALUES ({', '.join(['%s'] * len(row))})",
        [Jsonb(v) if isinstance(v, dict | list) else v for v in row.values()],
    )
    return _support_as(writer, g, observation, f"att:{observation}")


def _accepting(relation: RelationJudgment) -> str | None:
    """The verifier a writer with the services' role can give its own copy of the code."""
    return None


def test_the_projection_refuses_a_decision_resting_on_a_forged_support(guarded, roles):
    """The writer runs the product's own episode with a verifier that accepts everything, over the
    services' role: a format-perfect decision and event, re-derivable from their snapshot. The
    projection every reader of belief uses (`BeliefEpisode.project`: the loop's state, the
    confirmation re-check, the episode report's final state) must not fold it in."""
    g = guarded
    with roles.connect(roles.app) as app:
        forged = _bad_authorization("forged_signature", app, g)
        relation = _measured_support(g, "projection-forged", forged, app)
        written = _promote(g, app, SqlRelationStore(app, support_verifier=_accepting), relation)
    assert written.event is not None, "the writer's episode must have recorded the transition"
    assert relation in {
        r.relation_id for r in written.authorization.decision_input_snapshot.admitted_relations
    }

    honest = _episode(g.db, _product_relations(g), g.keys.trust)
    with pytest.raises(UnverifiedBeliefRevision) as caught:
        honest.project(project_id=PROJECT, hypothesis_id=g.hypothesis)
    assert caught.value.reason is VerificationFailure.SUPPORT_UNVERIFIED
    assert relation in str(caught.value)

    # A reader built without a verifier fails closed the same way (never accepts it).
    bare = _episode(g.db, SqlRelationStore(g.db), g.keys.trust)
    with pytest.raises(UnverifiedBeliefRevision):
        bare.project(project_id=PROJECT, hypothesis_id=g.hypothesis)


def test_the_projection_keeps_a_decision_resting_on_a_signed_support(guarded):
    """Positive control: the same governed transition over a signed support re-verifies."""
    g = guarded
    relation = _measured_support(g, "projection-signed", g.authorize("projection"), g.db)
    written = _promote(g, g.db, _product_relations(g), relation)
    assert written.event is not None
    assert relation in {
        r.relation_id for r in written.authorization.decision_input_snapshot.admitted_relations
    }
    honest = _episode(g.db, _product_relations(g), g.keys.trust)
    projection = honest.project(project_id=PROJECT, hypothesis_id=g.hypothesis)
    assert projection.current_state is BeliefState.SUPPORTED
    assert written.event.event_id in projection.applied


def test_the_projection_refuses_a_snapshot_support_that_is_not_the_stored_relation(guarded):
    """A decision's copy of a signed support, altered after it was read (here: another
    prediction), is not the relation the database admitted -- its write-time checks never saw it."""
    g = guarded
    relation_id = _good_support(g)
    stored = SqlRelationStore(g.db).get(PROJECT, relation_id)
    assert stored is not None
    altered = stored.model_copy(
        update={"attributes": {**stored.attributes, "outcome": "SOMETHING ELSE"}}
    )
    check = _product_relations(g).support_problem
    assert check(stored) is None
    assert "not the relation stored" in (check(altered) or "")
