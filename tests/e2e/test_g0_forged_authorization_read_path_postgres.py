"""A forged authorization must not reach the inputs of any epistemic decision (011w read paths).

The auditor's finding: SQL cannot verify Ed25519, so a verification authorization with a forged
signature passes 011w's frame, and a SUPPORTS relation resting on it is admitted by the database.
The evaluation collector rejected it (`unverified_authorization`), but the collector only SCORES.

This file asks the question that matters: does such a row, written by an ordinary SERVICES-role
connection (the least-privilege role a deployment's services use -- `lab-brain admin db-roles`),
reach the inputs the product DECIDES from? Every belief decision reads one function:
`SqlRelationStore.admitted_for_subject` -- the transition authorization's `DecisionInputSnapshot`
(`core.episode`), the verification loop's confirmation rule (`SqlEvidenceSink`), and the re-check
a confirmed conclusion must pass before it is reused (`research.confirmation`). The first test
was written first and failed on f41758c: the forged support was returned to all of them.

After the fix:
    admitted_for_subject  a SUPPORTS of a post-screening hypothesis is admitted only when the
                          store was given a verifier and it finds no problem; given none, it is
                          never admitted (fail closed). The product passes
                          `prospective_support_verifier` -- 011s's SQL rules on the rows as they
                          are now, and the authorization's signatures under the pinned authority.
    legitimate support    signed by the enrolled person: admitted as before.
    pre-screening         untouched: no conditioning record, no check.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from psycopg.types.json import Jsonb

from lab_brain.core.repositories.evidence import SqlRelationStore
from lab_brain.security.reviewer_identity import ReviewerTrust, SigningKey
from lab_brain.storage.postgres.verification_evidence import SqlEvidenceSink
from lab_brain.verification import prospective
from tests.e2e.test_g0_exploratory_screening_postgres import rows
from tests.e2e.test_g0_screening_independence_postgres import Guarded
from tests.e2e.test_g0_screening_independence_postgres import guarded as guarded
from tests.e2e.test_g0_screening_independence_postgres import standin as standin
from tests.e2e.test_research_episode_postgres import PROJECT
from tests.integration import test_g0_spend_admin_postgres as _roles

pytestmark = pytest.mark.postgres

# The deployment's least-privilege roles, created and dropped per test (`lab-brain admin db-roles`).
su = _roles.su
roles = _roles.roles

PROBE = "cap:sp.fourpoint_probe"


def _digest(g: Guarded) -> str:
    ((digest,),) = rows(
        g.db, "SELECT declaration_hash FROM capability_declarations WHERE capability_id = %s", PROBE
    )
    return str(digest)


def _forge(app: Any, g: Guarded, name: str, signature: str) -> str:
    """As the services' role: an authorization in the episode person's name, under their real
    enrolment, with a signature nobody with their key made."""
    signer = g.keys.signer(PROJECT, g.actor)
    authorization = f"vauth:{name}"
    app.execute(
        "INSERT INTO verification_authorizations (authorization_id, project_id, episode_id,"
        " hypothesis_id, prediction_ids, capability_id, declaration_hash, actor_id, rationale,"
        " created_at, enrolment_id, signature, signed_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now(), %s, %s, %s)",
        (
            authorization,
            PROJECT,
            g.episode,
            g.hypothesis,
            [g.prediction()],
            PROBE,
            _digest(g),
            g.actor,
            "forged by a service",
            signer.enrolment_id,
            signature,
            dt.datetime.now(dt.UTC),
        ),
    )
    return authorization


def _support_as(app: Any, g: Guarded, observation: str, evidence: str) -> str:
    """As the services' role: SUPPORTS from `observation` to the post-screening rival."""
    relation = f"rel:{observation}"
    app.execute(
        "INSERT INTO relation_judgments (relation_id, from_entity_id, to_entity_id,"
        " relation_type, attributes, supporting_attestation_ids, project_id)"
        " VALUES (%s, %s, %s, 'SUPPORTS', %s, %s, %s)",
        (
            relation,
            observation,
            g.hypothesis,
            Jsonb({"prediction_id": g.prediction(), "outcome": "ELEVATED"}),
            [evidence],
            PROJECT,
        ),
    )
    return relation


def _decision_inputs(g: Guarded, store: SqlRelationStore) -> set[str]:
    return {r.relation_id for r in store.admitted_for_subject(PROJECT, g.hypothesis)}


def test_a_forged_authorization_never_reaches_the_decision_inputs(guarded, roles):
    g = guarded
    forged_signature = SigningKey.generate().sign(b"a statement the person never signed")
    with roles.connect(roles.app) as app:
        authorization = _forge(app, g, "forged", forged_signature)
        observation, evidence = g.measured("forged", authorization=authorization)
        relation = _support_as(app, g, observation, evidence)
    # The services' role wrote both rows, and the database admitted them (the frame holds).
    assert rows(
        g.db, "SELECT relation_type FROM relation_judgments WHERE relation_id = %s", relation
    ) == [("SUPPORTS",)]

    # Every reader the product decides from, as constructed by default ...
    assert relation not in _decision_inputs(g, SqlRelationStore(g.db)), (
        "the forged support reached the transition authorization's inputs"
    )
    loop_default = SqlEvidenceSink(connection=g.db, outputs=None)  # type: ignore[arg-type]
    assert relation not in {
        r.relation_id for r in loop_default.admitted_for_subject(PROJECT, g.hypothesis)
    }, "the forged support reached the verification loop's confirmation rule"
    # ... and as the product wires them: with the verifier, under the pinned authority.
    verifier = prospective.prospective_support_verifier(g.db, g.keys.trust)
    assert relation not in _decision_inputs(g, SqlRelationStore(g.db, support_verifier=verifier))
    loop_reads = SqlEvidenceSink(
        connection=g.db,
        outputs=None,  # type: ignore[arg-type]
        support_verifier=verifier,
    )
    assert relation not in {
        r.relation_id for r in loop_reads.admitted_for_subject(PROJECT, g.hypothesis)
    }
    assert "signature does not verify" in (verifier(_relation(g, relation)) or "")


def _relation(g: Guarded, relation_id: str) -> Any:
    found = SqlRelationStore(g.db).get(PROJECT, relation_id)
    assert found is not None
    return found


def test_a_signed_authorization_still_reaches_them(guarded):
    g = guarded
    authorization = g.authorize("signed")
    observation, evidence = g.measured("signed", authorization=authorization)
    g.support(observation, [evidence], prediction=g.prediction())
    relation = f"rel:{observation}"
    verified = SqlRelationStore(
        g.db, support_verifier=prospective.prospective_support_verifier(g.db, g.keys.trust)
    )
    assert relation in _decision_inputs(g, verified)
    # The verification loop's reader passes the verifier on to the store it reads through.
    loop_reads = SqlEvidenceSink(
        connection=g.db,
        outputs=None,  # type: ignore[arg-type]
        support_verifier=prospective.prospective_support_verifier(g.db, g.keys.trust),
    )
    assert relation in {
        r.relation_id for r in loop_reads.admitted_for_subject(PROJECT, g.hypothesis)
    }
    # The same row, read with no authority pinned, is not support.
    unpinned = SqlRelationStore(
        g.db, support_verifier=prospective.prospective_support_verifier(g.db, ReviewerTrust())
    )
    assert relation not in _decision_inputs(g, unpinned)
    assert relation not in _decision_inputs(g, SqlRelationStore(g.db))


def test_a_pre_screening_hypothesis_is_read_as_before(guarded):
    """No conditioning record, no authorization check: its admitted relations are unchanged."""
    g = guarded
    ((other,),) = rows(
        g.db,
        "SELECT hypothesis_id FROM hypotheses WHERE created_in_episode = %s AND hypothesis_id"
        " NOT IN (SELECT hypothesis_id FROM screening_conditioned_hypotheses)"
        " ORDER BY hypothesis_id LIMIT 1",
        g.episode,
    )
    plain = {r.relation_id for r in SqlRelationStore(g.db).admitted_for_subject(PROJECT, other)}
    raw = {
        r[0]
        for r in rows(
            g.db,
            "SELECT relation_id FROM relation_judgments WHERE project_id = %s AND to_entity_id = %s"
            " AND valid_to IS NULL AND relation_type IN ('SUPPORTS','CONTRADICTS','TESTS',"
            "'PREDICTS')",
            PROJECT,
            other,
        )
    }
    assert plain == raw


def test_every_product_reader_that_decides_is_given_the_verifier():
    """The research service and the confirmation re-check build every relation reader with the
    verifier. (A reader built without one still fails closed -- it admits no post-screening
    support at all -- so a forgotten site loses support, never gains a forged one.)"""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "src" / "lab_brain"
    found = 0
    for path in ("research/service.py", "research/confirmation.py"):
        text = (root / path).read_text("utf-8")
        for constructor in ("SqlRelationStore(", "SqlEvidenceSink("):
            start = 0
            while (at := text.find(constructor, start)) != -1:
                start = at + 1
                close = text.find(")", at)
                after = text[close + 1 : close + 20]
                if after.startswith((".load_artifact", ".from_observation")):
                    continue  # reads an artifact or one observation's relations, not a subject's
                found += 1
                assert "support_verifier" in text[at : close + 1], (path, text[at : close + 1])
    assert found >= 7


def test_the_episode_view_marks_a_forged_support_as_not_counted(guarded, roles):
    """The episode page's relation model (`episode_view._relation`) asks the same verifier every
    decision asks, and says when a recorded SUPPORTS is not counted."""
    from lab_brain.research.episode_view import _not_counted

    g = guarded
    with roles.connect(roles.app) as app:
        authorization = _forge(app, g, "shown", SigningKey.generate().sign(b"x"))
        observation, evidence = g.measured("shown", authorization=authorization)
        forged = _support_as(app, g, observation, evidence)
    signed_observation, signed_evidence = g.measured("shown-ok", authorization=g.authorize("ok"))
    g.support(signed_observation, [signed_evidence], prediction=g.prediction())
    signed = f"rel:{signed_observation}"
    verifier = prospective.prospective_support_verifier(g.db, g.keys.trust)

    def why(relation: str, check: Any) -> str | None:
        return _not_counted(g.db, PROJECT, relation, "SUPPORTS", g.hypothesis, check)

    assert "signature does not verify" in (why(forged, verifier) or "")
    assert why(signed, verifier) is None
    assert why(signed, None) is not None, "no verifier: not counted, never assumed"
    assert _not_counted(g.db, PROJECT, signed, "CITES", g.hypothesis, None) is None
