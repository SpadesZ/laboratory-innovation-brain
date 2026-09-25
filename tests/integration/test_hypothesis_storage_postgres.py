"""M3's storage invariants, held by PostgreSQL for a writer that skips every Python gate.

`005e`, `011i`, `010c` and `003e` state the storage-checkable half of EPI-001, SRC-002 and LLM-002.
Every test starts from rows a real debate wrote (hard-1, through the SQL stores), then writes the
one violating row a support script or a future service could write -- by cloning a valid row and
changing exactly one thing, so the refusal can only be about that thing.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from lab_brain.core.belief import EpistemicStateProjection, admit_hypothesis
from lab_brain.core.models import BeliefState, RelationJudgment, RelationType, TransitionPolicy
from lab_brain.core.repositories.belief_events import SqlBeliefEventStore
from lab_brain.core.repositories.evidence import SqlRelationStore
from lab_brain.core.repositories.hypotheses import SqlHypothesisStore
from tests.debate_fixtures import (
    ADMISSION_POLICY,
    PROJECT,
    T0,
    TRACE,
    build_world,
    load_fixture,
    make_certificate,
    make_set,
)

pytestmark = [pytest.mark.postgres]

LATER = T0 + dt.timedelta(days=1)
PROMOTE = TransitionPolicy(
    policy_id="tp:m3.promote",
    version="1.0.0",
    from_state=BeliefState.ACTIVE,
    candidate_to_state=BeliefState.SUPPORTED,
    required_relation_types=(RelationType.SUPPORTS,),
)
REJECT = TransitionPolicy(
    policy_id="tp:m3.reject",
    version="1.0.0",
    from_state=BeliefState.ACTIVE,
    candidate_to_state=BeliefState.CONTRADICTED,
    required_relation_types=(RelationType.CONTRADICTS,),
)


def _case(case_id: str) -> dict[str, Any]:
    return next(c for c in load_fixture()["cases"] if c["case_id"] == case_id)


@pytest.fixture
def debated(db):  # type: ignore[no-untyped-def]
    case = _case("hard-1")
    world = build_world(case, connection=db, transition_policies=(PROMOTE, REJECT))
    return world, world.debate.run(world.request(case))


def _clone(db, table: str, key_column: str, key: str, **overrides: object) -> None:  # type: ignore[no-untyped-def]
    """INSERT a copy of one row with ``overrides`` applied, typed from the catalog."""
    columns = db.execute(
        "SELECT column_name, udt_name FROM information_schema.columns"
        " WHERE table_name = %s ORDER BY ordinal_position",
        (table,),
    ).fetchall()
    select, params = [], []
    for name, udt in columns:
        if name in overrides:
            kind = f"{udt[1:]}[]" if udt.startswith("_") else udt
            select.append(f"%s::{kind}")
            value = overrides[name]
            params.append(Jsonb(value) if udt == "jsonb" else value)
        else:
            select.append(name)
    names = ", ".join(n for n, _ in columns)
    db.execute(
        f"INSERT INTO {table} ({names}) SELECT {', '.join(select)} FROM {table}"
        f" WHERE {key_column} = %s",
        (*params, key),
    )


def _relation(
    db, relation_id: str, attestation_id: str, hypothesis_id: str, kind: RelationType
) -> None:  # type: ignore[no-untyped-def]
    SqlRelationStore(db).add(
        RelationJudgment(
            relation_id=relation_id,
            from_entity_id=attestation_id,
            to_entity_id=hypothesis_id,
            relation_type=kind,
            project_id=PROJECT,
            supporting_attestation_ids=(attestation_id,),
            valid_from=T0,
            created_at=T0,
        )
    )


def _attempt(world, hypothesis_id: str, policy: TransitionPolicy, basis):  # type: ignore[no-untyped-def]
    """M1's BeliefEpisode directly -- the writer that skipped `HypothesisBrain`'s preconditions."""
    return world.episode.attempt_transition(
        project_id=PROJECT,
        hypothesis_id=hypothesis_id,
        policy_id=policy.policy_id,
        policy_version=policy.version,
        candidate_to_state=policy.candidate_to_state,
        stakes="HIGH",
        occurred_at=LATER,
        trace_id=TRACE,
        triggering_attestations=basis,
    )


def _events(db, hypothesis_id: str) -> int:  # type: ignore[no-untyped-def]
    return db.execute(
        "SELECT count(*) FROM belief_revision_events WHERE target_id = %s", (hypothesis_id,)
    ).fetchone()[0]


# -- the debate's rows are real and reload exactly -------------------------------------------------


def test_the_debate_writes_every_object_durably_and_it_reloads_equal(debated, db):
    world, outcome = debated
    fresh_hypotheses = SqlHypothesisStore(db)
    assert (
        fresh_hypotheses.certificates_in_set(outcome.hypothesis_set.set_id) == outcome.certificates
    )
    assert fresh_hypotheses.get_set(outcome.hypothesis_set.set_id) == outcome.hypothesis_set
    for position in outcome.positions:
        assert world.debates.get_position(position.position_id) == position
    for critique in outcome.critiques:
        assert world.debates.get_critique(critique.critique_id) == critique
    assert world.debates.get_debate_record(outcome.record.debate_id) == outcome.record
    slots = {r[0] for r in db.execute("SELECT DISTINCT logical_slot FROM inference_provenance")}
    assert slots == {"REASONING_PRIMARY", "REASONING_ADVERSARIAL", "FAST_UTILITY"}  # 003e


# -- EPI-001 -------------------------------------------------------------------------------------


@pytest.mark.requirement("EPI-001")
@pytest.mark.spec_test("T-EPI-001")
def test_an_incomplete_certificate_cannot_be_stored(debated, db):
    _, outcome = debated
    source = outcome.certificates[0].hypothesis_id
    for column, value in (("assumptions", []), ("confounders", []), ("minimal_test_ref", " ")):
        with pytest.raises(psycopg.errors.CheckViolation):
            _clone(
                db,
                "hypotheses",
                "hypothesis_id",
                source,
                hypothesis_id=f"hyp:bad-{column}",
                **{column: value},
            )
    with pytest.raises(psycopg.errors.CheckViolation, match="has_an_author"):
        _clone(
            db,
            "hypotheses",
            "hypothesis_id",
            source,
            hypothesis_id="hyp:bad-author",
            inference_provenance_id=None,
            authored_by_actor_id=None,
        )


@pytest.mark.requirement("EPI-001")
@pytest.mark.spec_test("T-EPI-001")
def test_a_genesis_on_a_certificate_with_no_prediction_is_refused(debated, db):
    world, outcome = debated
    _clone(
        db,
        "hypotheses",
        "hypothesis_id",
        outcome.certificates[0].hypothesis_id,
        hypothesis_id="hyp:idea",
        mechanism="a bare idea",
    )
    basis = world.attestations[outcome.primary_bundle.ordered_attestation_ids[0]]
    with pytest.raises(psycopg.errors.RaiseException, match="no typed Prediction"):
        SqlBeliefEventStore(db).append(
            admit_hypothesis(
                event_id="bre:idea",
                policy=ADMISSION_POLICY,
                project_id=PROJECT,
                hypothesis_id="hyp:idea",
                prior=EpistemicStateProjection(
                    project_id=PROJECT, target_id="hyp:idea", current_state=None, last_event_id=None
                ),
                occurred_at=LATER,
                trace_id=TRACE,
                triggering_attestations=(basis,),
            )
        )
    assert _events(db, "hyp:idea") == 0


@pytest.mark.requirement("EPI-001")
@pytest.mark.spec_test("T-EPI-001")
def test_predictions_cannot_be_back_filled_or_invent_outcomes(debated, db):
    _, outcome = debated
    admitted = outcome.certificates[0]
    prediction = admitted.predictions[0].prediction_id
    with pytest.raises(psycopg.errors.RaiseException, match="already admitted"):
        _clone(db, "predictions", "prediction_id", prediction, prediction_id="prd:late")
    _clone(
        db,
        "hypotheses",
        "hypothesis_id",
        admitted.hypothesis_id,
        hypothesis_id="hyp:fresh",
        mechanism="fresh",
    )
    with pytest.raises(psycopg.errors.RaiseException, match="VER-004"):
        _clone(
            db,
            "predictions",
            "prediction_id",
            prediction,
            prediction_id="prd:magic",
            hypothesis_id="hyp:fresh",
            expected_outcome="RS_OSCILLATES",
            relation_effect_if_observed=[
                {"relation_type": "SUPPORTS", "to_entity_id": "hyp:fresh"}
            ],
        )
    with pytest.raises(psycopg.errors.RaiseException, match="not on its own hypothesis"):
        _clone(
            db,
            "predictions",
            "prediction_id",
            prediction,
            prediction_id="prd:elsewhere",
            hypothesis_id="hyp:fresh",
            relation_effect_if_observed=[
                {"relation_type": "SUPPORTS", "to_entity_id": admitted.hypothesis_id}
            ],
        )


@pytest.mark.requirement("EPI-001")
@pytest.mark.spec_test("T-EPI-001")
def test_a_single_plausible_cause_cannot_be_promoted_by_a_writer_that_skipped_the_gate(debated, db):
    """A root-cause set of one, stored and admitted around the service, then promoted around the
    brain: the database refuses the SUPPORTED event itself."""
    world, outcome = debated
    lonely_set = make_set("hst:lonely", inverted_retrieval_required=False)
    lonely = make_certificate("normalization_error", lonely_set)
    store = SqlHypothesisStore(db)
    store.add_set(lonely_set)
    store.add_certificate(lonely)
    basis = world.attestations[outcome.primary_bundle.ordered_attestation_ids[0]]
    SqlBeliefEventStore(db).append(
        admit_hypothesis(
            event_id="bre:lonely",
            policy=ADMISSION_POLICY,
            project_id=PROJECT,
            hypothesis_id=lonely.hypothesis_id,
            prior=EpistemicStateProjection(
                project_id=PROJECT,
                target_id=lonely.hypothesis_id,
                current_state=None,
                last_event_id=None,
            ),
            occurred_at=T0,
            trace_id=TRACE,
            triggering_attestations=(basis,),
        )
    )
    _relation(db, "rel:lonely", basis.attestation_id, lonely.hypothesis_id, RelationType.SUPPORTS)
    with pytest.raises(psycopg.errors.RaiseException, match="升級成 confirmed root cause"):
        _attempt(world, lonely.hypothesis_id, PROMOTE, (basis,))
    assert _events(db, lonely.hypothesis_id) == 1


# -- SRC-002 -------------------------------------------------------------------------------------


@pytest.mark.requirement("SRC-002")
@pytest.mark.spec_test("T-SRC-002")
def test_a_critique_cannot_claim_independence_its_provenance_does_not_exhibit(debated, db):
    _, outcome = debated
    critique = outcome.critiques[0]
    with pytest.raises(psycopg.errors.RaiseException, match="exhibited by the two records"):
        _clone(
            db,
            "critique_reports",
            "critique_id",
            critique.critique_id,
            critique_id="crq:overclaims",
            differs_in=["RETRIEVAL_BUNDLE", "REASONING_POLICY", "MODEL_ROUTE"],
        )
    # BEFORE-row triggers run ahead of CHECK constraints, so whichever speaks first refuses it.
    refused = (psycopg.errors.RaiseException, psycopg.errors.CheckViolation)
    with pytest.raises(refused):
        _clone(
            db,
            "critique_reports",
            "critique_id",
            critique.critique_id,
            critique_id="crq:none",
            differs_in=[],
        )
    with pytest.raises(refused):
        _clone(
            db,
            "critique_reports",
            "critique_id",
            critique.critique_id,
            critique_id="crq:same",
            inverted_bundle_id=critique.primary_bundle_id,
        )


@pytest.mark.requirement("SRC-002")
@pytest.mark.spec_test("T-SRC-002")
def test_an_inverted_bundle_that_is_the_primary_retrieval_again_is_refused(debated, db):
    _, outcome = debated
    critique = outcome.critiques[0]
    _clone(
        db,
        "evidence_bundles",
        "bundle_id",
        critique.primary_bundle_id,
        bundle_id="bdl:primary-again",
    )
    with pytest.raises(psycopg.errors.RaiseException, match="OWN retrieval"):
        _clone(
            db,
            "critique_reports",
            "critique_id",
            critique.critique_id,
            critique_id="crq:disguised",
            inverted_bundle_id="bdl:primary-again",
        )


@pytest.mark.requirement("SRC-002")
@pytest.mark.spec_test("T-SRC-002")
def test_a_position_must_name_the_bundle_its_inference_actually_saw(debated, db):
    _, outcome = debated
    engine, specialist = outcome.positions[0], outcome.positions[1]
    assert engine.bundle_id != specialist.bundle_id
    with pytest.raises(psycopg.errors.RaiseException, match="actually saw"):
        _clone(
            db,
            "positions",
            "position_id",
            engine.position_id,
            position_id="pos:lies",
            bundle_id=specialist.bundle_id,
        )


@pytest.mark.requirement("SRC-002")
@pytest.mark.spec_test("T-SRC-002")
def test_a_reject_with_no_independent_critique_is_refused_in_the_database(debated, db):
    world, outcome = debated
    lonely_set = make_set("hst:uncritiqued", root_cause=False, inverted_retrieval_required=False)
    lonely = make_certificate("normalization_error", lonely_set)
    store = SqlHypothesisStore(db)
    store.add_set(lonely_set)
    store.add_certificate(lonely)
    basis = world.attestations[outcome.primary_bundle.ordered_attestation_ids[0]]
    SqlBeliefEventStore(db).append(
        admit_hypothesis(
            event_id="bre:uncritiqued",
            policy=ADMISSION_POLICY,
            project_id=PROJECT,
            hypothesis_id=lonely.hypothesis_id,
            prior=EpistemicStateProjection(
                project_id=PROJECT,
                target_id=lonely.hypothesis_id,
                current_state=None,
                last_event_id=None,
            ),
            occurred_at=T0,
            trace_id=TRACE,
            triggering_attestations=(basis,),
        )
    )
    _relation(
        db, "rel:against", basis.attestation_id, lonely.hypothesis_id, RelationType.CONTRADICTS
    )
    with pytest.raises(psycopg.errors.RaiseException, match="重大 REJECT"):
        _attempt(world, lonely.hypothesis_id, REJECT, (basis,))
    assert _events(db, lonely.hypothesis_id) == 1


@pytest.mark.requirement("SRC-002")
@pytest.mark.spec_test("T-SRC-002")
def test_a_high_stakes_set_without_inverted_retrieval_cannot_enter_belief_revision(db):
    from lab_brain.cognition.debate import DebatePolicy

    case = _case("hard-1")
    world = build_world(
        case,
        connection=db,
        transition_policies=(PROMOTE, REJECT),
        policy=DebatePolicy(perform_inverted_retrieval=False),
    )
    outcome = world.debate.run(world.request(case))
    target = outcome.certificates[0].hypothesis_id
    basis = world.attestations[outcome.primary_bundle.ordered_attestation_ids[0]]
    _relation(db, "rel:for", basis.attestation_id, target, RelationType.SUPPORTS)
    with pytest.raises(psycopg.errors.RaiseException, match="inverted retrieval"):
        _attempt(world, target, PROMOTE, (basis,))
    assert _events(db, target) == 1


# -- append-only ---------------------------------------------------------------------------------


def test_every_m3_record_is_append_only(debated, db):
    _, outcome = debated
    for table, column, key in (
        ("hypothesis_sets", "set_id", outcome.hypothesis_set.set_id),
        ("hypotheses", "hypothesis_id", outcome.certificates[0].hypothesis_id),
        ("predictions", "prediction_id", outcome.certificates[0].predictions[0].prediction_id),
        ("positions", "position_id", outcome.positions[0].position_id),
        ("critique_reports", "critique_id", outcome.critiques[0].critique_id),
        ("debate_records", "debate_id", outcome.record.debate_id),
    ):
        with pytest.raises(psycopg.errors.RaiseException):
            db.execute(f"UPDATE {table} SET created_at = created_at WHERE {column} = %s", (key,))
        with pytest.raises(psycopg.errors.RaiseException):
            db.execute(f"DELETE FROM {table} WHERE {column} = %s", (key,))


# -- LLM-002 / 003e ------------------------------------------------------------------------------


@pytest.mark.requirement("LLM-002")
@pytest.mark.spec_test("T-LLM-002")
def test_the_debate_record_cannot_exceed_its_bound_or_misstate_a_metric(debated, db):
    _, outcome = debated
    key = outcome.record.debate_id
    with pytest.raises(psycopg.errors.CheckViolation, match="rounds_within_bound"):
        _clone(db, "debate_records", "debate_id", key, debate_id="dbt:long", rounds=9)
    with pytest.raises(psycopg.errors.CheckViolation):
        _clone(
            db,
            "debate_records",
            "debate_id",
            key,
            debate_id="dbt:odd",
            critic_bundle_divergence=1.5,
        )


@pytest.mark.requirement("LLM-002")
@pytest.mark.spec_test("T-LLM-002")
def test_a_benchmark_policy_row_must_carry_its_calibration_and_one_version_is_active(db):
    insert = (
        "INSERT INTO benchmark_policies (policy_id, version, domain, benchmark_set_id, metric_key,"
        " threshold, direction, calibrated_at, sample_size, calibration_artifact_refs, active)"
        " VALUES (%s, %s, 'silicon_photonics', 'bench:sp.rs_anomaly_debate',"
        " 'critic_bundle_divergence', 0.3333, 'AT_LEAST', %s, 10, %s, %s)"
    )
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(insert, ("bp:bare", "1.0.0", T0, [], False))
    db.execute(insert, ("bp:a", "1.0.0", T0, ["benchmark-run:x#sha256:1"], True))
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(insert, ("bp:b", "1.0.0", T0, ["benchmark-run:x#sha256:2"], True))
    with pytest.raises(psycopg.errors.RaiseException):
        db.execute("UPDATE benchmark_policies SET threshold = 0.1 WHERE policy_id = 'bp:a'")


def test_an_undeclared_route_slot_is_refused_by_003e(debated, db):
    _, outcome = debated
    inference = outcome.calls[0].inference.inference_id
    with pytest.raises(psycopg.errors.CheckViolation, match="logical_slot"):
        _clone(
            db,
            "inference_provenance",
            "inference_id",
            inference,
            inference_id="inf:vibes",
            logical_slot="VIBES",
        )
