"""T-VER-006's "persists nothing" clause, asserted by counting rows in a real database.

    §17.5.1  evaluate_hypothetical MUST be side-effect free: it MUST NOT persist RelationJudgment,
             MUST NOT emit BeliefRevisionEvent, and MUST NOT mutate any projection.

WHY THIS NEEDS POSTGRESQL WHEN §26 SAYS contract/unit. Because "persists nothing" is a claim about
persistence, and the only convincing version of it is a before-and-after count of the tables that
would hold the side effects. An in-memory assertion that a list stayed empty proves the test did
not append to its own list.

The three tables are named individually rather than swept, so a future side effect landing in a new
one fails here loudly rather than passing because the sweep did not know about it.

WHAT MAKES THIS MORE THAN A FORMALITY. `evaluate_hypothetical` lives on `TransitionPolicy`, a frozen
model that holds no connection and no store -- so it is side-effect free by construction rather than
by discipline. The risk the requirement is really about is the *planner*: a sufficiency computation
that helpfully wrote the hypothetical relations down "so they can be reviewed later" would produce a
`relation_judgments` row asserting an experiment nobody ran, and every later `evaluate` would admit
it as evidence. That is what this counts.
"""

from __future__ import annotations

import datetime as dt

import pytest

from lab_brain.core.belief import EpistemicStateProjection, admit_hypothesis
from lab_brain.core.episode import BeliefEpisode
from lab_brain.core.models import (
    BeliefState,
    IndependenceSummary,
    OutcomeSpace,
    Prediction,
    RelationJudgment,
    RelationJudgmentTemplate,
    RelationType,
    TransitionOutcome,
    TransitionPolicy,
)
from lab_brain.core.models.attestation import (
    Attestation,
    EpistemicType,
    ExtractionProvenance,
)
from lab_brain.core.models.prediction import bind
from lab_brain.core.repositories import (
    SqlAttestationStore,
    SqlBeliefEventStore,
    SqlRelationStore,
    SqlTransitionPolicyStore,
)
from lab_brain.core.repositories.belief_events import SqlBeliefTransitionDecisionStore
from lab_brain.core.repositories.conflicts import SqlConflictStore
from lab_brain.core.repositories.reviews import SqlReviewItemStore
from lab_brain.core.sufficiency import evaluate_sufficiency
from tests.conftest_fixtures import make_artifact
from tests.postgres_fixtures import admit_hypothesis_identity

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.requirement("VER-006"),
    pytest.mark.spec_test("T-VER-006"),
]

T0 = dt.datetime(2026, 9, 16, 15, 0, tzinfo=dt.UTC)
PROJECT = "prj:test"
HYP = "hyp:rs-contact-resistance"
TRACE = "trc:hypothetical"

#: The tables a side effect would land in. Named, not swept -- see the module docstring.
_SIDE_EFFECT_TABLES = (
    "relation_judgments",
    "belief_revision_events",
    "belief_transition_decisions",
)

GENESIS = TransitionPolicy(
    policy_id="pol:admission",
    version="1.0.0",
    from_state=BeliefState.DRAFT,
    candidate_to_state=BeliefState.ACTIVE,
    is_admission=True,
)
PROMOTE = TransitionPolicy(
    policy_id="pol:promote",
    version="1.0.0",
    from_state=BeliefState.ACTIVE,
    candidate_to_state=BeliefState.SUPPORTED,
    required_relation_types=(RelationType.SUPPORTS,),
)

SPACE = OutcomeSpace(
    outcome_space_id="osp:trend",
    version="1.0.0",
    domain="toy",
    action_type="measurement",
    outcomes=("INCREASES", "FLAT", "DECREASES"),
)
PREDICTION = Prediction(
    prediction_id="prd:1",
    hypothesis_id=HYP,
    project_id=PROJECT,
    observable_ref="obs:contact-resistance-vs-anneal",
    outcome_space_id=SPACE.outcome_space_id,
    outcome_space_version=SPACE.version,
    expected_outcome="DECREASES",
    relation_effect_if_observed=(
        RelationJudgmentTemplate(relation_type=RelationType.SUPPORTS, to_entity_id=HYP),
    ),
)


class _Ids:
    def decision_id(self) -> str:
        return "dec:1"

    def event_id(self) -> str:
        return "bre:1"

    def conflict_id(self) -> str:
        return "cfl:1"

    def review_id(self) -> str:
        return "rvw:1"


@pytest.fixture
def world(db):  # type: ignore[no-untyped-def]
    """An admitted hypothesis with no supporting relation, so the prediction is discriminating."""
    # M3 / R-12 (`011j`): a belief event names a hypothesis admitted through §8's gate in its own
    # project, so the identity this fixture always meant is established first.
    admit_hypothesis_identity(db, HYP)
    artifact = make_artifact(b"a hypothetical fixture")
    db.execute(
        "INSERT INTO artifacts (artifact_id, content_hash, uri, media_type, source_origin,"
        " lineage_id, lineage_revision) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            artifact.artifact_id,
            artifact.content_hash,
            artifact.uri,
            artifact.media_type,
            artifact.source_origin.value,
            artifact.lineage_id,
            artifact.lineage_revision,
        ),
    )
    db.execute("INSERT INTO claims (claim_id, normalized_proposition) VALUES ('clm:1', 'rs')")
    db.execute(
        "INSERT INTO condition_schemas (domain, schema_id, version, json_schema,"
        " comparator_version) VALUES ('core', 'sch_test', '1.0.0', %s::jsonb, '1.0.0')",
        ('{"type": "object", "properties": {}}',),
    )
    policies = SqlTransitionPolicyStore(db)
    policies.register(GENESIS)
    policies.register(PROMOTE)

    attestation = SqlAttestationStore(db).add(
        Attestation(
            attestation_id="att:genesis",
            claim_id="clm:1",
            epistemic_type=EpistemicType.REPORTED,
            source_artifact_id=artifact.artifact_id,
            locator="p.1",
            conditions_schema_version="core/sch_test@1.0.0",
            project_id=PROJECT,
            extractor_version="1.0.0",
            extraction_provenance=ExtractionProvenance(
                extractor_id="ext:t", extractor_version="1.0.0"
            ),
        )
    )
    SqlBeliefEventStore(db).append(
        admit_hypothesis(
            event_id="bre:genesis",
            policy=GENESIS,
            project_id=PROJECT,
            hypothesis_id=HYP,
            prior=EpistemicStateProjection(
                project_id=PROJECT, target_id=HYP, current_state=None, last_event_id=None
            ),
            occurred_at=T0,
            trace_id=TRACE,
            triggering_attestations=(attestation,),
        )
    )
    return db


def _episode(world) -> BeliefEpisode:  # type: ignore[no-untyped-def]
    return BeliefEpisode(
        policies=SqlTransitionPolicyStore(world),
        decisions=SqlBeliefTransitionDecisionStore(world),
        events=SqlBeliefEventStore(world),
        relations=SqlRelationStore(world),
        authority_classes=SqlAttestationStore(world),
        conflicts=SqlConflictStore(world),
        reviews=SqlReviewItemStore(world),
        ids=_Ids(),
    )


def _counts(world) -> dict[str, int]:  # type: ignore[no-untyped-def]
    return {
        table: world.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in _SIDE_EFFECT_TABLES
    }


def test_a_sufficiency_computation_writes_no_row_anywhere(world):
    """The headline clause. Counted before and after, table by table."""
    episode = _episode(world)
    view = episode.hypothesis_view(
        project_id=PROJECT,
        hypothesis_id=HYP,
        current_state=BeliefState.ACTIVE,
        stakes="HIGH",
        admitted_relations=(),
    )
    before = _counts(world)
    before_projection = episode.project(project_id=PROJECT, hypothesis_id=HYP)

    result = evaluate_sufficiency(
        policy=PROMOTE,
        hypothesis=view,
        admitted_relations=(),
        candidate_to_state=BeliefState.SUPPORTED,
        action_produces=PREDICTION.observable_ref,
        predictions=(bind(PREDICTION, SPACE),),
        outcome_spaces=(SPACE,),
    )

    assert result.sufficient is True, "the fixture must make this a real hypothetical"
    assert result.baseline.outcome is TransitionOutcome.NEED_MORE_EVIDENCE
    assert result.discriminating_outcomes[0][1].outcome is TransitionOutcome.ALLOW

    assert _counts(world) == before, "evaluate_hypothetical persisted something"
    assert episode.project(project_id=PROJECT, hypothesis_id=HYP) == before_projection


def test_the_hypothetical_relation_is_not_in_the_relation_table(world):
    """Specifically, and by id.

    The row that would exist if a planner had helpfully written it down is the dangerous one: it
    would be a `SUPPORTS` judgment asserting a measurement nobody made, and every later `evaluate`
    would admit it as evidence. Asserting the absence by id says that in one line.
    """
    hypothetical = bind(PREDICTION, SPACE).hypothetical_relations(project_id=PROJECT)
    assert len(hypothetical) == 1

    evaluate_sufficiency(
        policy=PROMOTE,
        hypothesis=_episode(world).hypothesis_view(
            project_id=PROJECT,
            hypothesis_id=HYP,
            current_state=BeliefState.ACTIVE,
            stakes="HIGH",
            admitted_relations=(),
        ),
        admitted_relations=(),
        candidate_to_state=BeliefState.SUPPORTED,
        action_produces=PREDICTION.observable_ref,
        predictions=(bind(PREDICTION, SPACE),),
        outcome_spaces=(SPACE,),
    )

    assert SqlRelationStore(world).get(PROJECT, hypothetical[0].relation_id) is None
    assert SqlRelationStore(world).admitted_for_subject(PROJECT, HYP) == ()


def test_the_projection_after_a_hypothetical_is_the_projection_before_it(world):
    """ "MUST NOT mutate any projection", read back out of the database rather than compared in
    memory -- the projection is derived, so the only way to change it is to change the events."""
    episode = _episode(world)
    before = episode.project(project_id=PROJECT, hypothesis_id=HYP, projected_at=T0)
    assert before.current_state is BeliefState.ACTIVE

    for _ in range(3):
        evaluate_sufficiency(
            policy=PROMOTE,
            hypothesis=episode.hypothesis_view(
                project_id=PROJECT,
                hypothesis_id=HYP,
                current_state=BeliefState.ACTIVE,
                stakes="HIGH",
                admitted_relations=(),
            ),
            admitted_relations=(),
            candidate_to_state=BeliefState.SUPPORTED,
            action_produces=PREDICTION.observable_ref,
            predictions=(bind(PREDICTION, SPACE),),
            outcome_spaces=(SPACE,),
        )

    assert episode.project(project_id=PROJECT, hypothesis_id=HYP, projected_at=T0) == before


def test_a_hypothetical_does_not_become_the_real_transition(world):
    """The seam that would collapse the whole distinction: a planner discovers an outcome *would*
    promote the belief and promotes it.

    `evaluate_hypothetical` returns a `TransitionDecision`, and nothing downstream accepts one:
    `authorize_transition` computes its own from the six real inputs. So the hypothetical says
    ALLOW, the real attempt says NEED_MORE_EVIDENCE, and no event is written.
    """
    episode = _episode(world)
    view = episode.hypothesis_view(
        project_id=PROJECT,
        hypothesis_id=HYP,
        current_state=BeliefState.ACTIVE,
        stakes="HIGH",
        admitted_relations=(),
    )
    projected = PROMOTE.evaluate_hypothetical(
        view,
        (),
        bind(PREDICTION, SPACE).hypothetical_relations(project_id=PROJECT),
        None,
        (),
        IndependenceSummary(),
        BeliefState.SUPPORTED,
    )
    assert projected.outcome is TransitionOutcome.ALLOW

    real = episode.attempt_transition(
        project_id=PROJECT,
        hypothesis_id=HYP,
        policy_id="pol:promote",
        policy_version="1.0.0",
        candidate_to_state=BeliefState.SUPPORTED,
        stakes="HIGH",
        occurred_at=T0 + dt.timedelta(hours=1),
        trace_id=TRACE,
    )
    assert real.decision.outcome is TransitionOutcome.NEED_MORE_EVIDENCE
    assert not real.transitioned
    assert [e.event_id for e in SqlBeliefEventStore(world).history(PROJECT, HYP)] == ["bre:genesis"]


def test_once_the_measurement_is_really_admitted_the_transition_goes_through(world):
    """The positive control, without which the test above proves only that the policy refuses.

    The same relation the prediction described, this time recorded as a real judgment backed by a
    real attestation -- and now the belief moves. The difference between the two tests is the
    entire content of "side-effect free".
    """
    SqlAttestationStore(world).add(
        Attestation(
            attestation_id="att:measured",
            claim_id="clm:1",
            epistemic_type=EpistemicType.MEASURED,
            source_artifact_id=SqlAttestationStore(world)
            .get(PROJECT, "att:genesis")
            .source_artifact_id,  # type: ignore[union-attr]
            locator="table 2",
            conditions_schema_version="core/sch_test@1.0.0",
            project_id=PROJECT,
            extractor_version="1.0.0",
            extraction_provenance=ExtractionProvenance(
                extractor_id="ext:t", extractor_version="1.0.0"
            ),
        )
    )
    SqlRelationStore(world).add(
        RelationJudgment(
            relation_id="rel:measured",
            from_entity_id="att:measured",
            to_entity_id=HYP,
            relation_type=RelationType.SUPPORTS,
            project_id=PROJECT,
            supporting_attestation_ids=("att:measured",),
            valid_from=T0,
            created_at=T0,
        )
    )

    result = _episode(world).attempt_transition(
        project_id=PROJECT,
        hypothesis_id=HYP,
        policy_id="pol:promote",
        policy_version="1.0.0",
        candidate_to_state=BeliefState.SUPPORTED,
        stakes="HIGH",
        occurred_at=T0 + dt.timedelta(hours=1),
        trace_id=TRACE,
    )
    assert result.decision.outcome is TransitionOutcome.ALLOW
    assert result.projection.current_state is BeliefState.SUPPORTED
