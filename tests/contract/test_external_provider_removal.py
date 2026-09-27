"""M5's third exit-gate clause, and the novelty-audit boundary (§26.1 M5, SRC-003, AGT-008).

    M5 gate   移除 GitHub provider 不影響 core cognition
    §22       停用 GitHub connector 後 core cognition 仍可啟動
    §7.1      Novelty Auditor: external paper/patent/GitHub prior-art audit; 沒搜到不能宣告全球唯一

GitHub is prior art for the novelty audit -- a TECHNICAL_ARTIFACT class the coverage record can
name -- and nothing else. With the provider removed, the audit still runs and says, in its coverage
record, that the class was not searched; a GLOBAL novelty claim that needs it is then refused by
SRC-003's rule, not quietly accepted. The M3 debate runs unchanged, because it never depended on a
provider in the first place.
"""

from __future__ import annotations

import datetime as dt

from lab_brain.cognition.novelty import PriorArtSearch, PriorArtSourceBinding, SanitizedConcept
from lab_brain.core.models.enums import SensitivityLabel, TrustClass
from lab_brain.core.models.prior_art import (
    DateRange,
    NoveltyAssessment,
    NoveltyScope,
    NoveltyStatus,
    novelty_coverage_problems,
)
from lab_brain.core.repositories.prior_art import InMemoryPriorArtStore
from lab_brain.evidence.source_policy import SourcePolicyRegistry, default_source_policies
from tests.classification_fixtures import labelled
from tests.debate_fixtures import build_world
from tests.external_fixtures import ACTOR, PROJECT, build

BINDINGS = (
    PriorArtSourceBinding("github", (TrustClass.TECHNICAL_ARTIFACT,)),
    PriorArtSourceBinding("literature", (TrustClass.PEER_REVIEWED, TrustClass.PREPRINT)),
)
CONCEPT = SanitizedConcept(
    subject_id="hyp:concept",
    text="series resistance extraction for carrier depletion phase shifters",
    declared_label=SensitivityLabel.PUBLIC,
    sanitized_by_actor_id="act:pi",
)


def _search(world):  # type: ignore[no-untyped-def]
    router = world.registry.router(
        project_id=PROJECT, runner=world.runner, classifier=labelled({}, project_id=PROJECT)
    )
    counter = iter(range(1, 100))
    return PriorArtSearch(
        router=router,
        bindings=BINDINGS,
        internal=None,
        store=InMemoryPriorArtStore(),
        mint=lambda kind: f"pas:{next(counter)}",
        now=lambda: dt.datetime(2026, 9, 27, tzinfo=dt.UTC),
    ).search(
        concept=CONCEPT,
        queries=("series resistance phase shifter",),
        date_range=DateRange(start=dt.date(2015, 1, 1), end=dt.date(2026, 9, 27)),
        policy=SourcePolicyRegistry(default_source_policies()).for_intent("NOVELTY_AUDIT"),
        project_id=PROJECT,
        episode_id="epi:m5",
        actor_id=ACTOR,
        include_internal=False,
    )


def _global(record) -> NoveltyAssessment:  # type: ignore[no-untyped-def]
    return NoveltyAssessment(
        assessment_id="nov:1",
        project_id=PROJECT,
        episode_id="epi:m5",
        subject_id=CONCEPT.subject_id,
        search_id=record.search_id,
        status=NoveltyStatus.NOVELTY_CANDIDATE,
        scope=NoveltyScope.GLOBAL,
        global_coverage_required=(TrustClass.TECHNICAL_ARTIFACT, TrustClass.PEER_REVIEWED),
        prior_art_matrix=(),
        created_at=dt.datetime(2026, 9, 27, tzinfo=dt.UTC),
    )


def test_github_is_prior_art_the_coverage_record_names():
    record, hits = _search(build())
    assert {s.provider_id for s in record.sources} == {"github", "literature"}
    assert any(
        h.source_type == "repository" and h.trust_class == "TECHNICAL_ARTIFACT" for h in hits
    )
    assert novelty_coverage_problems(record, _global(record)) == []


def test_without_the_github_provider_the_audit_runs_and_cannot_claim_global_novelty():
    world = build()
    world.registry.remove("github")
    record, hits = _search(world)
    assert {s.provider_id for s in record.sources} == {"literature"}
    assert "github is declared but not registered" in record.limitations
    assert all(h.trust_class != "TECHNICAL_ARTIFACT" for h in hits)
    problems = novelty_coverage_problems(record, _global(record))
    assert any("did not cover" in p and "TECHNICAL_ARTIFACT" in p for p in problems)


def test_core_cognition_runs_with_no_external_provider_at_all():
    """The M3 debate -- hypotheses, critique, admission -- needs no GitHub adapter."""
    world = build_world()
    outcome = world.debate.run(world.request())
    assert len(outcome.certificates) >= 2
    assert outcome.hypothesis_set.root_cause
