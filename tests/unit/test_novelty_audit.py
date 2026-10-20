"""SRC-003 in memory: a novelty status rests on a recorded search, and internal is never global.

    SRC-003  任何 novelty status MUST 引用 PriorArtSearchRecord，記錄 sources、queries、date range 與
             limitations。無覆蓋率記錄的 novelty status MUST 被拒絕；internal novelty MUST NOT 被當作
             global novelty 呈現。

The prior-art "providers" are deterministic local corpora (`tests.debate_fixtures.CorpusAdapter`).
No external search was performed by these tests, and none of their records claims one was.
The PostgreSQL integration half is `tests/integration/test_prior_art_postgres.py`.
"""

from __future__ import annotations

import datetime as dt

import pytest

from lab_brain.cognition.novelty import NoveltyRefused, SanitizedConcept, present
from lab_brain.core.models.enums import SensitivityLabel, TrustClass
from lab_brain.core.models.prior_art import (
    DateRange,
    NoveltyAssessment,
    NoveltyScope,
    NoveltyStatus,
)
from lab_brain.core.repositories.prior_art import InMemoryPriorArtStore, PriorArtStoreError
from tests.debate_fixtures import (
    ACTOR,
    EPISODE,
    LITERATURE,
    PATENTS,
    PROJECT,
    TRACE,
    CorpusAdapter,
    MockScientist,
    budget_policy,
    build_world,
    load_fixture,
    novelty_tools,
)

pytestmark = [pytest.mark.requirement("SRC-003"), pytest.mark.spec_test("T-SRC-003")]

WINDOW = DateRange(start=dt.date(2015, 1, 1), end=dt.date(2026, 9, 1))
CONCEPT = SanitizedConcept(
    subject_id="hyp:graded-rib",
    text="graded dopant compensation rib series resistance",
    declared_label=SensitivityLabel.INTERNAL,
    sanitized_by_actor_id="act:pi",
)


def _audit(adapters, *, internal=True, date_range=WINDOW, scientist=None, concept=CONCEPT):  # type: ignore[no-untyped-def]
    world = build_world(scientist=scientist)
    store = InMemoryPriorArtStore()
    search, auditor = novelty_tools(world, adapters, store, internal=internal)
    policy = world.source_policies.for_intent("NOVELTY_AUDIT")
    record, hits = search.search(
        concept=concept,
        queries=["dopant compensation series resistance", "graded rib doping"],
        date_range=date_range,
        policy=policy,
        project_id=PROJECT,
        episode_id=EPISODE,
        actor_id=ACTOR,
    )

    def assess():  # type: ignore[no-untyped-def]
        return auditor.assess(
            concept=concept,
            record=record,
            hits=hits,
            policy=policy,
            stakes="NORMAL",
            trace_id=TRACE,
            actor_id=ACTOR,
            budget_policy=budget_policy(),
        )

    return world, store, record, hits, assess


def _claiming_global() -> MockScientist:
    fx = load_fixture()
    return MockScientist(
        mechanisms=fx["mechanisms"],
        primary_terms=fx["primary_terms"],
        outcome_space=fx["outcome_space"],
        claim_global_novelty=True,
    )


def test_the_search_records_sources_queries_date_range_and_limitations():
    _, store, record, hits, _ = _audit([LITERATURE, PATENTS])
    assert store.search(record.search_id) == record
    assert {s.provider_id for s in record.sources} == {
        "src:literature",
        "src:patents",
        "internal:lab-records",
    }
    assert record.queries == ("dopant compensation series resistance", "graded rib doping")
    assert record.date_range == WINDOW
    assert record.limitations and any("沒搜到不能宣告全球唯一" in n for n in record.limitations)
    assert record.deduped_work_count == len(hits) == len(record.external_source_record_ids)
    assert {TrustClass.PEER_REVIEWED, TrustClass.PATENT} <= record.covered_trust_classes
    assert not record.internal_only


def test_a_covered_search_supports_a_global_status_bound_to_it():
    _, store, record, _, assess = _audit([LITERATURE, PATENTS])
    assessment = assess()
    assert assessment.scope is NoveltyScope.GLOBAL
    assert assessment.search_id == record.search_id
    assert assessment.status is NoveltyStatus.KNOWN  # the literature already has it, FULL overlap
    assert store.assessment(assessment.assessment_id) == assessment
    assert assessment.inference_provenance_id is not None


def test_an_internal_only_search_yields_an_internal_status_presented_as_such():
    _, _, record, _, assess = _audit([])
    assert record.internal_only
    assessment = assess()
    assert assessment.scope is NoveltyScope.INTERNAL
    rendered = present(assessment, record)
    assert "NOT a global novelty claim" in rendered
    assert "Limitations" in rendered


def test_an_internal_only_search_cannot_yield_a_global_novelty_claim():
    """The auditor claims GLOBAL over internal records; the claim is refused and nothing stored."""
    _, store, record, _, assess = _audit([], scientist=_claiming_global())
    with pytest.raises(NoveltyRefused, match="MUST NOT be presented as global"):
        assess()
    assert store._assessments == {}
    assert record.internal_only


def test_a_global_claim_over_a_search_that_skipped_the_patent_corpus_is_refused():
    _, _, record, _, assess = _audit([LITERATURE], scientist=_claiming_global())
    assert TrustClass.PATENT not in record.covered_trust_classes
    with pytest.raises(NoveltyRefused, match="PATENT"):
        assess()


def test_an_unreachable_provider_is_a_limitation_not_a_source():
    down = CorpusAdapter("src:patents", TrustClass.PATENT, PATENTS.corpus, reachable=False)
    _, _, record, _, assess = _audit([LITERATURE, down], scientist=_claiming_global())
    assert "src:patents" not in {s.provider_id for s in record.sources}
    assert any("src:patents was unreachable" in n for n in record.limitations)
    with pytest.raises(NoveltyRefused):
        assess()


def test_a_search_with_no_date_range_cannot_support_any_novelty_status():
    _, _, record, _, assess = _audit([LITERATURE, PATENTS], date_range=None)
    assert record.date_range is None
    with pytest.raises(NoveltyRefused, match="no date range"):
        assess()


def test_a_novelty_status_without_a_search_record_is_rejected():
    store = InMemoryPriorArtStore()
    orphan = NoveltyAssessment(
        assessment_id="nov:orphan",
        project_id=PROJECT,
        episode_id=EPISODE,
        subject_id="hyp:graded-rib",
        search_id="pas:never-ran",
        status=NoveltyStatus.NOVELTY_CANDIDATE,
        scope=NoveltyScope.INTERNAL,
    )
    with pytest.raises(PriorArtStoreError, match="MUST be refused"):
        store.add_assessment(orphan)


def test_a_concept_must_be_sanitized_by_a_person():
    with pytest.raises(ValueError, match="P12"):
        SanitizedConcept(
            subject_id="hyp:x",
            text="graded rib",
            declared_label=SensitivityLabel.INTERNAL,
            sanitized_by_actor_id=" ",
        )


def test_no_status_says_novel_without_qualification():
    assert {s.value for s in NoveltyStatus} == {"KNOWN", "PARTIALLY_NOVEL", "NOVELTY_CANDIDATE"}
