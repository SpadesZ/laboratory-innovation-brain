"""T-SRC-003 (integration): coverage is durable and retrievable, and the database holds the rule.

    §26 T-SRC-003  novelty fixture without a `PriorArtSearchRecord` is rejected; recorded coverage
                   (sources / queries / date range / limitations) is retrievable; an internal-only
                   search cannot yield a global-novelty claim.

The auditor runs through the budgeted, provenance-recording dispatcher against PostgreSQL; the
"providers" are deterministic local corpora and no external search took place. `002b` is then
tested directly: a writer that skips `NoveltyAuditor` meets the same refusals.
"""

from __future__ import annotations

import datetime as dt

import psycopg
import pytest
from psycopg.types.json import Jsonb

from lab_brain.cognition.novelty import NoveltyRefused, SanitizedConcept
from lab_brain.core.models.enums import SensitivityLabel, TrustClass
from lab_brain.core.models.prior_art import DateRange, NoveltyScope
from lab_brain.core.repositories.prior_art import SqlPriorArtStore
from tests.debate_fixtures import (
    ACTOR,
    EPISODE,
    LITERATURE,
    PATENTS,
    PROJECT,
    TRACE,
    MockScientist,
    budget_policy,
    build_world,
    load_fixture,
    novelty_tools,
)

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.requirement("SRC-003"),
    pytest.mark.spec_test("T-SRC-003"),
]

WINDOW = DateRange(start=dt.date(2015, 1, 1), end=dt.date(2026, 9, 1))
CONCEPT = SanitizedConcept(
    subject_id="hyp:graded-rib",
    text="graded dopant compensation rib series resistance",
    declared_label=SensitivityLabel.INTERNAL,
    sanitized_by_actor_id="act:pi",
)


def _run(db, adapters, *, scientist=None):  # type: ignore[no-untyped-def]
    world = build_world(connection=db, scientist=scientist)
    store = SqlPriorArtStore(db)
    search, auditor = novelty_tools(world, adapters, store)
    policy = world.source_policies.for_intent("NOVELTY_AUDIT")
    record, hits = search.search(
        concept=CONCEPT,
        queries=["dopant compensation series resistance", "graded rib doping"],
        date_range=WINDOW,
        policy=policy,
        project_id=PROJECT,
        episode_id=EPISODE,
        actor_id=ACTOR,
    )

    def assess():  # type: ignore[no-untyped-def]
        return auditor.assess(
            concept=CONCEPT,
            record=record,
            hits=hits,
            policy=policy,
            stakes="NORMAL",
            trace_id=TRACE,
            actor_id=ACTOR,
            budget_policy=budget_policy(),
        )

    return world, store, record, assess


def test_recorded_coverage_is_retrievable_through_a_fresh_store(db):
    _, _, record, assess = _run(db, [LITERATURE, PATENTS])
    assessment = assess()
    reloaded = SqlPriorArtStore(db)
    assert reloaded.search(record.search_id) == record
    assert reloaded.assessment(assessment.assessment_id) == assessment
    stored = reloaded.search(record.search_id)
    assert stored is not None
    assert {s.provider_id for s in stored.sources} >= {"src:literature", "src:patents"}
    assert stored.queries and stored.date_range == WINDOW and stored.limitations
    # The auditor's judgment is a durable, provenanced inference over a bundle naming the hits.
    row = db.execute(
        "SELECT b.source_policy_id, b.source_snapshot_refs FROM inference_provenance i"
        " JOIN evidence_bundles b ON b.canonical_hash = i.evidence_bundle_hash"
        " WHERE i.inference_id = %s",
        (assessment.inference_provenance_id,),
    ).fetchone()
    assert row[0] == "srcpol:novelty-audit"
    assert sorted(row[1]) == sorted(record.external_source_record_ids)


def test_an_internal_only_search_cannot_yield_a_global_claim_through_the_auditor(db):
    fx = load_fixture()
    boastful = MockScientist(
        mechanisms=fx["mechanisms"],
        primary_terms=fx["primary_terms"],
        outcome_space=fx["outcome_space"],
        claim_global_novelty=True,
    )
    _, _, record, assess = _run(db, [], scientist=boastful)
    assert record.internal_only
    with pytest.raises(NoveltyRefused):
        assess()
    assert db.execute("SELECT count(*) FROM novelty_assessments").fetchone()[0] == 0


def _raw_assessment(db, search_id: str, *, scope: str, required: list[str]) -> None:  # type: ignore[no-untyped-def]
    db.execute(
        "INSERT INTO novelty_assessments (assessment_id, project_id, episode_id, subject_id,"
        " search_id, novelty_status, scope, global_coverage_required, prior_art_matrix,"
        " created_at)"
        " VALUES (%s, %s, %s, 'hyp:graded-rib', %s, 'NOVELTY_CANDIDATE', %s, %s, %s, now())",
        (f"nov:raw-{scope.lower()}", PROJECT, EPISODE, search_id, scope, required, Jsonb([])),
    )


def test_the_database_refuses_a_global_claim_over_an_internal_only_search(db):
    _, _, record, _ = _run(db, [])
    assert record.internal_only
    with pytest.raises(psycopg.errors.RaiseException, match="internal"):
        _raw_assessment(db, record.search_id, scope="GLOBAL", required=["PEER_REVIEWED", "PATENT"])
    _raw_assessment(db, record.search_id, scope="INTERNAL", required=[])  # the honest claim


def test_the_database_refuses_a_global_claim_over_an_uncovered_class(db):
    _, _, record, _ = _run(db, [LITERATURE])
    assert TrustClass.PATENT not in record.covered_trust_classes
    with pytest.raises(psycopg.errors.RaiseException):
        _raw_assessment(db, record.search_id, scope="GLOBAL", required=["PEER_REVIEWED", "PATENT"])


def test_a_novelty_status_without_a_search_record_is_rejected_by_the_database(db):
    build_world(connection=db)  # the project and episode rows
    with pytest.raises(psycopg.errors.RaiseException, match="MUST be refused"):
        _raw_assessment(db, "pas:never-ran", scope="INTERNAL", required=[])


def test_a_search_record_whose_counts_do_not_match_its_records_is_refused(db):
    _, _, record, _ = _run(db, [LITERATURE, PATENTS])
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "INSERT INTO prior_art_search_records SELECT 'pas:miscounted', project_id, episode_id,"
            " intent, sources, queries, date_range, retrieved_at, source_policy_version,"
            " result_count, deduped_work_count + 1, limitations, coverage_notes,"
            " external_source_record_ids, inference_provenance_id"
            " FROM prior_art_search_records WHERE search_id = %s",
            (record.search_id,),
        )
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        db.execute(
            "UPDATE prior_art_search_records SET limitations = '{}' WHERE search_id = %s",
            (record.search_id,),
        )


def test_the_internal_scope_is_what_a_person_is_shown(db):
    from lab_brain.cognition.novelty import present

    _, _, record, assess = _run(db, [])
    assessment = assess()
    assert assessment.scope is NoveltyScope.INTERNAL
    assert "NOT a global novelty claim" in present(assessment, record)
