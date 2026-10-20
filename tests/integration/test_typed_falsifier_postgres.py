"""The typed falsifier in storage, in qualification and in locks, on PostgreSQL.

Every admitted hypothesis designates its falsifier: `hypotheses.falsifier_prediction_ids`, its own
predictions whose every declared effect is CONTRADICTS. `012n` checks the designation when the
hypothesis is ADMITTED -- its genesis event -- for any writer, raw SQL included:

    stored       a debate's certificates are written with their designations, which resolve to
                 CONTRADICTS predictions of the same hypothesis, and reload equal; the designation
                 is as immutable as the hypothesis
    refused      a genesis with no designation, one naming a SUPPORTS prediction, another
                 hypothesis's CONTRADICTS prediction, or no prediction at all -- each writes nothing;
                 the same certificate designating its own CONTRADICTS prediction is admitted
    raw SQL      a genesis INSERTed directly is held to the same rule -- no designation, a SUPPORTS
                 prediction, one that CONTRADICTS and SUPPORTS at once, the rival's, a blank or a
                 dangling id; the same hypothesis id's prediction in another project; a NULL
                 element. A transition written around admission (with a recorded ALLOW decision)
                 is accepted as a row -- no genesis is required before a transition -- and moves no
                 belief: the history does not verify, and nothing that verifies has a state
    qualified    a model whose falsifiers are prose only fails ROLE_HYPOTHESIS and cannot serve
                 REASONING_PRIMARY; a route qualified under the vocabulary semantics is refused by
                 readiness and by the runtime boundary, its evidence cannot be locked again, and
                 testing it under the typed falsifier gives a new route; no earlier row changes
"""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest

import lab_brain.llm_runtime.registry as registry_module
from lab_brain.core.belief import (
    EpistemicStateProjection,
    UnverifiedBeliefRevision,
    admit_hypothesis,
    replay,
    verified_history,
)
from lab_brain.core.models.inference import LogicalSlot
from lab_brain.core.repositories.belief_events import (
    SqlBeliefEventStore,
    SqlBeliefTransitionDecisionStore,
    SqlTransitionPolicyStore,
)
from lab_brain.core.repositories.hypotheses import SqlHypothesisStore
from lab_brain.llm_runtime.capabilities import Capability
from lab_brain.llm_runtime.probes import HYPOTHESIS_SUITE, PROBE_VERSION, QUALIFICATION_DIGEST
from lab_brain.llm_runtime.runtime import RuntimeUnavailable, SettingsRefused
from tests.debate_fixtures import ADMISSION_POLICY, PROJECT, TRACE, build_world
from tests.fake_llm_provider import FakeProvider
from tests.integration.test_hypothesis_conformance_postgres import _load, _model, _rows, _settings
from tests.integration.test_hypothesis_storage_postgres import (
    LATER,
    PROMOTE,
    REJECT,
    _case,
    _clone,
    _events,
)
from tests.unit.test_typed_falsifier import VOCABULARY_DIGEST

pytestmark = pytest.mark.postgres

LOCKS = "SELECT t::text FROM llm_model_locks t WHERE model_profile_id = %s ORDER BY locked_at"
PROBES = "SELECT t::text FROM llm_capability_probes t WHERE model_profile_id = %s ORDER BY 1"
SLOTS = (LogicalSlot.REASONING_PRIMARY, LogicalSlot.FAST_UTILITY)


# -- storage and admission -------------------------------------------------------------------------


@pytest.fixture
def debated(db):  # type: ignore[no-untyped-def]
    case = _case("hard-1")
    world = build_world(case, connection=db, transition_policies=(PROMOTE, REJECT))
    return world, world.debate.run(world.request(case))


def test_a_debates_certificates_are_stored_with_designations_that_resolve(debated, db):
    _, outcome = debated
    for certificate in outcome.certificates:
        (designated,) = db.execute(
            "SELECT falsifier_prediction_ids FROM hypotheses"
            " WHERE project_id = %s AND hypothesis_id = %s",
            (PROJECT, certificate.hypothesis_id),
        ).fetchone()
        assert designated and sorted(designated) == list(certificate.falsifier_prediction_ids)
        effects = db.execute(
            "SELECT p.hypothesis_id, e ->> 'relation_type', e ->> 'to_entity_id'"
            " FROM predictions p, jsonb_array_elements(p.relation_effect_if_observed) e"
            " WHERE p.prediction_id = ANY (%s)",
            (designated,),
        ).fetchall()
        assert {tuple(r) for r in effects} == {
            (certificate.hypothesis_id, "CONTRADICTS", certificate.hypothesis_id)
        }
    reloaded = SqlHypothesisStore(db).certificates_in_set(outcome.hypothesis_set.set_id)
    assert reloaded == outcome.certificates
    with pytest.raises(psycopg.errors.RaiseException):
        db.execute(
            "UPDATE hypotheses SET falsifier_prediction_ids = '{}' WHERE hypothesis_id = %s",
            (outcome.certificates[0].hypothesis_id,),
        )


def _certificate_rows(db, outcome, hypothesis_id: str, designated: list[str], **hypothesis) -> None:  # type: ignore[no-untyped-def]
    """A copy of the first certificate as `hypothesis_id`, carrying copies of its SUPPORTS and its
    falsifier predictions as its own (`<id>.s`, `<id>.f`), designating `designated`; `hypothesis`
    overrides further columns of the copy."""
    source = outcome.certificates[0]
    (falsifier,) = source.falsifier_prediction_ids
    (supports,) = (p.prediction_id for p in source.predictions if p.prediction_id != falsifier)
    _clone(
        db,
        "hypotheses",
        "hypothesis_id",
        source.hypothesis_id,
        hypothesis_id=hypothesis_id,
        mechanism=f"the mechanism of {hypothesis_id}",
        falsifier_prediction_ids=designated,
        **hypothesis,
    )
    for suffix, kind, original in (("s", "SUPPORTS", supports), ("f", "CONTRADICTS", falsifier)):
        _clone(
            db,
            "predictions",
            "prediction_id",
            original,
            prediction_id=f"{hypothesis_id}.{suffix}",
            hypothesis_id=hypothesis_id,
            relation_effect_if_observed=[{"relation_type": kind, "to_entity_id": hypothesis_id}],
        )


def _genesis(db, world, outcome, hypothesis_id: str) -> None:  # type: ignore[no-untyped-def]
    basis = world.attestations[outcome.primary_bundle.ordered_attestation_ids[0]]
    SqlBeliefEventStore(db).append(
        admit_hypothesis(
            event_id=f"bre:{hypothesis_id}",
            policy=ADMISSION_POLICY,
            project_id=PROJECT,
            hypothesis_id=hypothesis_id,
            prior=EpistemicStateProjection(
                project_id=PROJECT, target_id=hypothesis_id, current_state=None, last_event_id=None
            ),
            occurred_at=LATER,
            trace_id=TRACE,
            triggering_attestations=(basis,),
        )
    )


@pytest.mark.parametrize(
    ("designated", "refusal"),
    [
        ([], "its certificate has no typed falsifier"),
        (["hyp:x.s"], "its designated falsifier hyp:x.s is not a CONTRADICTS prediction"),
        (["hyp:x.f", "<rival>"], "is not a CONTRADICTS prediction of its own"),
        (["prd:nowhere"], "its designated falsifier prd:nowhere is not"),
    ],
    ids=["none", "supports", "rivals", "dangling"],
)
def test_a_genesis_without_its_own_typed_falsifier_is_refused(debated, db, designated, refusal):
    world, outcome = debated
    rival = outcome.certificates[1].falsifier_prediction_ids[0]
    designated = [rival if d == "<rival>" else d for d in designated]
    _certificate_rows(db, outcome, "hyp:x", designated)
    with pytest.raises(psycopg.errors.RaiseException, match=refusal) as refused:
        _genesis(db, world, outcome, "hyp:x")
    if rival in designated:
        assert rival in str(refused.value) and "hyp:x.f" not in str(refused.value), (
            "the refusal names the foreign designation, not the hypothesis's own"
        )
    assert _events(db, "hyp:x") == 0


def test_the_same_certificate_designating_its_own_contradiction_is_admitted(debated, db):
    world, outcome = debated
    _certificate_rows(db, outcome, "hyp:y", ["hyp:y.f"])
    _genesis(db, world, outcome, "hyp:y")
    assert _events(db, "hyp:y") == 1
    stored = SqlHypothesisStore(db).get_certificate(PROJECT, "hyp:y")
    assert stored is not None and stored.falsifier_prediction_ids == ("hyp:y.f",)


# -- raw SQL: no writer gets around the designation ------------------------------------------------


def _raw_event(  # type: ignore[no-untyped-def]
    db, outcome, event_id, hypothesis_id, policy, *, from_state=None, decision=None
) -> None:
    """A belief event INSERTed directly with the evidence it cites, in one transaction -- no store,
    no append function, no Python gate."""
    basis = outcome.primary_bundle.ordered_attestation_ids[0]
    with db.transaction():
        db.execute(
            "INSERT INTO belief_revision_events (event_id, project_id, target_type, target_id,"
            " from_state, to_state, policy_id, policy_version, occurred_at, trace_id,"
            " authorization_decision_id)"
            " VALUES (%s, %s, 'HYPOTHESIS', %s, %s, %s, %s, %s, %s, %s, %s)",
            (
                event_id,
                PROJECT,
                hypothesis_id,
                from_state,
                policy.candidate_to_state.value,
                policy.policy_id,
                policy.version,
                LATER,
                TRACE,
                decision,
            ),
        )
        db.execute(
            "INSERT INTO belief_revision_event_attestations (event_id, attestation_id, project_id)"
            " VALUES (%s, %s, %s)",
            (event_id, basis, PROJECT),
        )


def _mixed(db, hypothesis_id: str) -> None:  # type: ignore[no-untyped-def]
    """`<id>.m`: a prediction of the hypothesis declaring CONTRADICTS and SUPPORTS at once."""
    _clone(
        db,
        "predictions",
        "prediction_id",
        f"{hypothesis_id}.f",
        prediction_id=f"{hypothesis_id}.m",
        relation_effect_if_observed=[
            {"relation_type": "CONTRADICTS", "to_entity_id": hypothesis_id},
            {"relation_type": "SUPPORTS", "to_entity_id": hypothesis_id},
        ],
    )


@pytest.mark.parametrize(
    ("designated", "refusal"),
    [
        ([], "its certificate has no typed falsifier"),
        (["hyp:r.s"], "its designated falsifier hyp:r.s is not a CONTRADICTS prediction"),
        (["hyp:r.m"], "its designated falsifier hyp:r.m is not a CONTRADICTS prediction"),
        (["<rival>"], "is not a CONTRADICTS prediction of its own"),
        ([""], "its designated falsifier  is not"),
        (["prd:nowhere"], "its designated falsifier prd:nowhere is not"),
        (["hyp:r.f"], None),
    ],
    ids=["none", "supports", "mixed", "rivals", "blank", "dangling", "own-contradiction"],
)
def test_a_raw_genesis_insert_is_held_to_the_same_designation(debated, db, designated, refusal):
    _, outcome = debated
    rival = outcome.certificates[1].falsifier_prediction_ids[0]
    designated = [rival if d == "<rival>" else d for d in designated]
    _certificate_rows(db, outcome, "hyp:r", designated)
    _mixed(db, "hyp:r")
    if refusal is None:
        _raw_event(db, outcome, "bre:raw", "hyp:r", ADMISSION_POLICY)
        assert _events(db, "hyp:r") == 1
        return
    with pytest.raises(psycopg.errors.RaiseException, match=refusal):
        _raw_event(db, outcome, "bre:raw", "hyp:r", ADMISSION_POLICY)
    assert _events(db, "hyp:r") == 0


def test_a_designation_holds_no_null_and_no_prediction_of_another_project(debated, db):
    _, outcome = debated
    with pytest.raises(psycopg.errors.CheckViolation):
        _certificate_rows(db, outcome, "hyp:z", ["hyp:z.f", None])  # type: ignore[list-item]
    # The same hypothesis id in another project, with its own CONTRADICTS prediction.
    source = outcome.certificates[0]
    db.execute("INSERT INTO projects (project_id, name) VALUES ('prj:elsewhere', 'Elsewhere')")
    _clone(
        db,
        "research_episodes",
        "episode_id",
        source.hypothesis.created_in_episode,
        episode_id="epi:elsewhere",
        project_id="prj:elsewhere",
    )
    _clone(
        db,
        "hypothesis_sets",
        "set_id",
        source.hypothesis_set_id,
        set_id="hst:elsewhere",
        project_id="prj:elsewhere",
        episode_id="epi:elsewhere",
    )
    _clone(
        db,
        "hypotheses",
        "hypothesis_id",
        source.hypothesis_id,
        hypothesis_id="hyp:c",
        project_id="prj:elsewhere",
        hypothesis_set_id="hst:elsewhere",
        created_in_episode="epi:elsewhere",
        inference_provenance_id=None,
        authored_by_actor_id="act:test",
        falsifier_prediction_ids=[],
    )
    _clone(
        db,
        "predictions",
        "prediction_id",
        source.falsifier_prediction_ids[0],
        prediction_id="hyp:c.elsewhere",
        project_id="prj:elsewhere",
        hypothesis_id="hyp:c",
        inference_provenance_id=None,
        relation_effect_if_observed=[{"relation_type": "CONTRADICTS", "to_entity_id": "hyp:c"}],
    )
    # hyp:c here designates hyp:c's prediction there: same hypothesis id, another project.
    _certificate_rows(db, outcome, "hyp:c", ["hyp:c.elsewhere"])
    with pytest.raises(
        psycopg.errors.RaiseException, match=r"hyp:c\.elsewhere is not a CONTRADICTS"
    ):
        _raw_event(db, outcome, "bre:raw-c", "hyp:c", ADMISSION_POLICY)
    assert _events(db, "hyp:c") == 0


def test_a_transition_written_around_admission_moves_no_belief(debated, db):
    """Skipping the genesis event skips its checks, and the database does not require one before a
    transition -- the M0b-M2 suites write transitions on hypotheses that have only their identity
    row. So the row is accepted, as `test_belief_authorization_verification_postgres` documents for
    a forged authorization; what holds is the read side: the history does not verify, and nothing
    that verifies puts the hypothesis in any state."""
    _, outcome = debated
    source = outcome.certificates[0]
    # A routine copy of the set, so no debate-specific rule speaks before admission would.
    _clone(
        db,
        "hypothesis_sets",
        "set_id",
        source.hypothesis_set_id,
        set_id="hst:routine",
        root_cause=False,
        inverted_retrieval_required=False,
    )
    _certificate_rows(db, outcome, "hyp:u", [], hypothesis_set_id="hst:routine")
    snapshot = "{}"
    db.execute(
        "INSERT INTO belief_transition_decisions (decision_id, project_id, subject_id, result,"
        " policy_id, policy_version, from_state, to_state, decision_input_snapshot, input_hash,"
        " evaluated_decision, created_at) VALUES ('dec:forged', %s, 'hyp:u', 'ALLOW', %s, %s,"
        " 'ACTIVE', 'SUPPORTED', %s, 'sha256:' || encode(sha256(convert_to(%s, 'UTF8')), 'hex'),"
        " 'ALLOW', %s)",
        (PROJECT, PROMOTE.policy_id, PROMOTE.version, snapshot, snapshot, LATER),
    )
    _raw_event(
        db, outcome, "bre:skip", "hyp:u", PROMOTE, from_state="ACTIVE", decision="dec:forged"
    )
    history = SqlBeliefEventStore(db).history(PROJECT, "hyp:u")
    assert [e.event_id for e in history] == ["bre:skip"], "the row is in the table"
    stores = {
        "decisions": SqlBeliefTransitionDecisionStore(db),
        "policies": SqlTransitionPolicyStore(db),
    }
    with pytest.raises(UnverifiedBeliefRevision):
        verified_history(project_id=PROJECT, target_id="hyp:u", events=history, **stores)
    projection = replay(PROJECT, "hyp:u", ())
    assert projection.current_state is None, "never admitted, in no state"


# -- qualification and locks -----------------------------------------------------------------------


@pytest.fixture
def local_model() -> Iterator[FakeProvider]:
    provider = FakeProvider(api_key=None).start()
    yield provider
    provider.stop()


@pytest.fixture
def _administrator(db):  # type: ignore[no-untyped-def]
    db.execute(
        "INSERT INTO llm_administrators (actor_id, granted_at, granted_through)"
        " VALUES ('act:test', now(), 'OPERATOR_CLI')"
    )


@pytest.mark.usefixtures("_administrator")
def test_a_model_whose_falsifiers_are_prose_only_does_not_qualify(db):  # type: ignore[no-untyped-def]
    prose = FakeProvider(api_key=None, prose_falsifier=True).start()
    try:
        model_id = _model(db, prose.base_url)
        llm = _settings(db)
        rows = {r.capability: r for r in llm.test_model(model_id)}
    finally:
        prose.stop()
    hypothesis = rows[Capability.ROLE_HYPOTHESIS.value]
    assert hypothesis.outcome == "FAILED"
    assert hypothesis.detail.startswith("contextual-minimum: the typed role parser refused it")
    assert "designates no typed falsifier" in hypothesis.detail
    assert hypothesis.parameters["suite"] == HYPOTHESIS_SUITE
    locked = llm.lock(model_id)
    assert "ROLE_HYPOTHESIS" not in (locked.locked_capabilities or ())
    runtime = llm.create_runtime("prose falsifiers", ["PUBLIC"])
    with pytest.raises(SettingsRefused):
        llm.bind(runtime.runtime_id, LogicalSlot.REASONING_PRIMARY, model_id)


@pytest.mark.usefixtures("_administrator")
def test_a_route_qualified_under_the_vocabulary_is_stale_until_tested_again(
    db, local_model, monkeypatch
):
    assert QUALIFICATION_DIGEST != VOCABULARY_DIGEST
    model_id = _model(db, local_model.base_url)
    llm = _settings(db)
    # Tested, locked and applied while the vocabulary semantics were in force.
    with monkeypatch.context() as then:
        then.setattr(registry_module, "QUALIFICATION_DIGEST", VOCABULARY_DIGEST)
        llm.test_model(model_id)
        old = llm.lock(model_id)
        runtime = llm.create_runtime("vocabulary", ["PUBLIC"])
        for slot in SLOTS:
            llm.bind(runtime.runtime_id, slot, model_id)
        llm.activate(runtime.runtime_id)
        assert _load(db)
    locks, probes = _rows(db, LOCKS, model_id), _rows(db, PROBES, model_id)

    # Under the typed falsifier: stale, refused at readiness and at the boundary, untouched.
    assert "no longer in force" in str(llm.registry.lock_problem(old))
    assert any("no longer in force" in b for b in llm.readiness(runtime.runtime_id).blockers)
    with pytest.raises(RuntimeUnavailable, match="no longer in force"):
        _load(db)
    llm.retire_runtime(runtime.runtime_id)
    llm.unlock(model_id)
    with pytest.raises(SettingsRefused, match="not run under the qualification semantics") as no:
        llm.lock(model_id)
    assert f"theirs: {PROBE_VERSION} {VOCABULARY_DIGEST[:12]}" in str(no.value)

    # Tested under the typed falsifier: a new route; every earlier row as it was.
    llm.test_model(model_id)
    new = llm.lock(model_id)
    assert new.lock_fingerprint not in (None, old.lock_fingerprint)
    assert llm.registry.lock_problem(new) is None
    after_locks, after_probes = _rows(db, LOCKS, model_id), _rows(db, PROBES, model_id)
    assert after_locks[: len(locks)] == locks and len(after_locks) == len(locks) + 1
    assert [r for r in after_probes if r in probes] == probes
