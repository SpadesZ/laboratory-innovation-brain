"""T-SIM-002's `e2e` half — a coarse contradiction CHALLENGES, durably, and cannot CONTRADICT.

    SIM-002    coarse/low-fidelity contradiction 只能標記 CHALLENGED；要 REJECT hypothesis 必須過
               standard/validation fidelity gate。
    T-SIM-002  **e2e** — low-fidelity contradiction 只使 hypothesis → CHALLENGED，不得直接 →
               REJECTED。

WHY THIS FILE EXISTS BESIDE `test_sim_fidelity_gate_postgres.py`. That one proves the DomainPack's
policy semantics and stops at `TransitionPolicy.evaluate()` -- which is the right place to prove a
comparator and the wrong place to stop for a row §26 types `e2e`. `evaluate` returning ALLOW is a
verdict; what the requirement is about is whether a *belief actually moves*, and between the two
sit the durable Decision, the BeliefRevisionEvent, and the re-derivation `v3.3-a13` requires on the
read path. A policy could be perfect and the projection still land somewhere else.

    Hypothesis ACTIVE
      -> admitted CONTRADICTS relation backed by SIM_COARSE authority
      -> canonical TransitionPolicy evaluation          (§8.2.1, hard-locked M0b)
      -> durable BeliefTransitionDecision               (`005d`, `v3.3-a12`)
      -> BeliefRevisionEvent                            (`005a`)
      -> verified replay                                (`v3.3-a13`: re-derive, then fold)
      -> projection == CHALLENGED

THE EXISTING M0b MACHINERY IS WHAT RUNS. `BeliefEpisode.attempt_transition` is the production path
and this test calls it; there is no second state-mutation helper written for M2, and
`test_this_file_declares_no_second_belief_path` parses the module and fails if one appears. What M2
supplies is the two policy records and the comparator -- which is the architectural claim the
requirement rests on: a fidelity gate is an AUTHORITY question (§10.5), so it needed no core change.

`CONTRADICTED` RATHER THAN `REJECTED`: §8.2's diagram is the normative one and has CONTRADICTED as
the negative terminal; SPEC-ISSUE-010 ruled on the prose's shorthand and `BeliefState` has no
REJECTED member.
"""

from __future__ import annotations

import ast
import datetime as dt
import inspect
import itertools

import pytest

from lab_brain.core.belief import (
    EpistemicStateProjection,
    admit_hypothesis,
)
from lab_brain.core.episode import BeliefEpisode
from lab_brain.core.models import (
    BeliefState,
    RelationJudgment,
    RelationType,
    TransitionOutcome,
    TransitionPolicy,
    TransitionReason,
)
from lab_brain.core.models.attestation import (
    Attestation,
    EpistemicType,
    ExtractionProvenance,
)
from lab_brain.core.models.condition import ConditionMatch, ConditionSchemaRef
from lab_brain.core.models.enums import ConditionMatchState
from lab_brain.core.models.transition import IndependenceSummary
from lab_brain.core.repositories import (
    SqlAttestationStore,
    SqlBeliefEventStore,
    SqlRelationStore,
    SqlTransitionPolicyStore,
)
from lab_brain.core.repositories.belief_events import SqlBeliefTransitionDecisionStore
from lab_brain.core.repositories.conflicts import SqlConflictStore
from lab_brain.core.repositories.reviews import SqlReviewItemStore
from lab_brain.domains.silicon_photonics.authority_policy import (
    CHALLENGE_POLICY_ID,
    MEAS_UNCALIBRATED,
    POLICY_VERSION,
    REJECT_POLICY_ID,
    SIM_COARSE,
    SIM_STANDARD,
    SIM_VALIDATION,
    SiliconPhotonicsAuthorityPolicy,
    transition_policies,
)
from lab_brain.domains.silicon_photonics.condition_schema import SCHEMA_REF, registration
from tests.conftest_fixtures import make_artifact

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.requirement("SIM-002"),
    pytest.mark.spec_test("T-SIM-002"),
]

T0 = dt.datetime(2026, 9, 24, 10, 0, tzinfo=dt.UTC)
T1 = T0 + dt.timedelta(hours=1)
PROJECT = "prj:test"
HYP = "hyp:rs-bias-insensitive"
TRACE = "trc:sim002"
AUTHORITY_REF = ("auth:silicon_photonics", "1.0.0")

#: §8's Hypothesis Admission Gate. Core's, not the pack's: a hypothesis has to exist before any
#: fidelity question can be asked about it, and §24.1 puts admission in the core column.
GENESIS = TransitionPolicy(
    policy_id="pol:sp-admission",
    version="1.0.0",
    from_state=BeliefState.DRAFT,
    candidate_to_state=BeliefState.ACTIVE,
    is_admission=True,
)


class CountingIds:
    """Deterministic ids, so two runs of this vertical produce comparable records."""

    def __init__(self) -> None:
        self._counters: dict[str, itertools.count[int]] = {}

    def _next(self, prefix: str) -> str:
        return f"{prefix}:{next(self._counters.setdefault(prefix, itertools.count(1)))}"

    def decision_id(self) -> str:
        return self._next("dec")

    def event_id(self) -> str:
        return self._next("bre")

    def conflict_id(self) -> str:
        return self._next("cfl")

    def review_id(self) -> str:
        return self._next("rvw")


def _episode(world) -> BeliefEpisode:  # type: ignore[no-untyped-def]
    """Fresh STORES every call, one shared id source per test.

    The stores are rebuilt so a reload is a real reload rather than a cached object. The id source
    is NOT: it lives on the fixture, because `dec:1` minted twice in one test is a primary-key
    collision rather than a finding, and a test that does two transitions is exactly the sequence
    §25.1's case produces.

    The comparator is supplied as the registry the episode resolves against -- §8.2.1 passes it as
    an argument to `evaluate`, and `_authority_policy_for` refuses a policy that needs one when it
    is absent rather than escalating a configuration error to a human.
    """
    return BeliefEpisode(
        policies=SqlTransitionPolicyStore(world),
        decisions=SqlBeliefTransitionDecisionStore(world),
        events=SqlBeliefEventStore(world),
        relations=SqlRelationStore(world),
        authority_classes=SqlAttestationStore(world),
        conflicts=SqlConflictStore(world),
        reviews=SqlReviewItemStore(world),
        ids=world.ids,
        authority_policies={AUTHORITY_REF: SiliconPhotonicsAuthorityPolicy()},
    )


@pytest.fixture
def world(db):  # type: ignore[no-untyped-def]
    """A project holding an ACTIVE hypothesis and the two M2 fidelity policies, all durable."""
    artifact = make_artifact(b"a silicon photonics fidelity fixture")
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
    db.execute(
        "INSERT INTO claims (claim_id, normalized_proposition) VALUES ('clm:rs', 'Rs is high')"
    )
    schema = registration()
    db.execute(
        "INSERT INTO condition_schemas (domain, schema_id, version, json_schema,"
        " comparator_version) VALUES (%s, %s, %s, %s::jsonb, %s)",
        (
            schema.domain,
            schema.schema_id,
            schema.version,
            __import__("json").dumps(schema.json_schema),
            schema.comparator_version,
        ),
    )

    policies = SqlTransitionPolicyStore(db)
    policies.register(GENESIS)
    # THE M2 CONTRIBUTION, and all of it: two §8.2.1 records the DomainPack supplies. No core file
    # was changed to make SIM-002 hold.
    for policy in transition_policies():
        policies.register(policy)

    db.artifact_id = artifact.artifact_id  # type: ignore[attr-defined]
    db.ids = CountingIds()  # type: ignore[attr-defined]
    return db


def _contradiction(world, fidelity: str, suffix: str = "1"):  # type: ignore[no-untyped-def]
    """An Attestation at ``fidelity`` and a CONTRADICTS relation citing it, both durable.

    The authority class is on the ATTESTATION, which is where §17.2 puts it -- `BeliefEpisode`
    resolves the relation's supporting attestations to their classes when it assembles the
    `HypothesisView`. So "this contradiction is coarse" is a fact about the evidence row, not a
    parameter of the call, and that is what makes the gate ungameable from the caller's side.
    """
    attestation = SqlAttestationStore(world).add(
        Attestation(
            attestation_id=f"att:{suffix}",
            claim_id="clm:rs",
            epistemic_type=EpistemicType.SIMULATED,
            source_artifact_id=world.artifact_id,
            locator=f"run output {suffix}",
            conditions_schema_version=SCHEMA_REF,
            conditions={"bias_v": "-1.0", "frequency_hz": "1000000", "device_length_um": "500"},
            authority_class=fidelity,
            project_id=PROJECT,
            extractor_version="1.0.0",
            extraction_provenance=ExtractionProvenance(
                extractor_id="extract_cj_rs", extractor_version="1.0.0"
            ),
        )
    )
    relation = SqlRelationStore(world).add(
        RelationJudgment(
            relation_id=f"rel:{suffix}",
            from_entity_id=attestation.attestation_id,
            to_entity_id=HYP,
            relation_type=RelationType.CONTRADICTS,
            project_id=PROJECT,
            supporting_attestation_ids=(attestation.attestation_id,),
            valid_from=T0,
            created_at=T0,
        )
    )
    return attestation, relation


def _admit(world) -> Attestation:  # type: ignore[no-untyped-def]
    """§8's admission gate: the hypothesis's FIRST event, so it has a state to move from.

    IT CITES A TRIGGER, and that is not boilerplate. `BeliefRevisionEvent` refuses an event naming
    none, because §6.18's contamination rollback replays by skipping events whose triggers were
    quarantined -- an untriggered event survives every rollback and makes it quietly incomplete.
    So the hypothesis is admitted on the measurement that motivated it, which is also what §25.1's
    case describes: an observed Rs anomaly comes first, and the simulations argue about it after.
    """
    origin = SqlAttestationStore(world).add(
        Attestation(
            attestation_id="att:origin",
            claim_id="clm:rs",
            epistemic_type=EpistemicType.MEASURED,
            source_artifact_id=world.artifact_id,
            locator="bias sweep, observed",
            conditions_schema_version=SCHEMA_REF,
            conditions={"bias_v": "-1.0", "frequency_hz": "1000000", "device_length_um": "500"},
            authority_class=MEAS_UNCALIBRATED,
            project_id=PROJECT,
            extractor_version="1.0.0",
            extraction_provenance=ExtractionProvenance(
                extractor_id="extract_cj_rs", extractor_version="1.0.0"
            ),
        )
    )
    SqlBeliefEventStore(world).append(
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
            triggering_attestations=(origin,),
        )
    )
    return origin


def _exact_conditions() -> ConditionMatch:
    """Conditions out of the way, so every assertion below is about AUTHORITY and nothing else."""
    return ConditionMatch(
        state=ConditionMatchState.EXACT,
        schema_ref=ConditionSchemaRef.parse(SCHEMA_REF),
        tolerance_policy_version="1.0.0",
    )


def _attempt(world, policy_id: str, to_state: BeliefState):  # type: ignore[no-untyped-def]
    return _episode(world).attempt_transition(
        project_id=PROJECT,
        hypothesis_id=HYP,
        policy_id=policy_id,
        policy_version=POLICY_VERSION,
        candidate_to_state=to_state,
        stakes="HIGH",
        occurred_at=T1,
        trace_id=TRACE,
        episode_id="epi:sim002",
        authority_policy_ref=AUTHORITY_REF,
        condition_matches=(_exact_conditions(),),
        independence_summary=IndependenceSummary(independent_count=1),
    )


# ---------------------------------------------------------------------------
# THE requirement, end to end
# ---------------------------------------------------------------------------


def test_a_coarse_contradiction_moves_the_projection_to_challenged(world):
    """Decision -> event -> replay -> CHALLENGED, through the production read path.

    The projection is read with `BeliefEpisode.project`, which re-derives every stored event's
    authorization before folding (`v3.3-a13`). So this is not "the event we just wrote says
    CHALLENGED" -- it is "the verified history replays to CHALLENGED", which is the thing §26 types
    `e2e`.
    """
    _admit(world)
    _contradiction(world, SIM_COARSE)

    result = _attempt(world, CHALLENGE_POLICY_ID, BeliefState.CHALLENGED)

    assert result.decision.outcome is TransitionOutcome.ALLOW
    assert result.transitioned

    # Durable authorization (§17.14.1, `v3.3-a12`) -- reloaded, not the object just returned.
    assert result.authorization is not None
    stored_decision = SqlBeliefTransitionDecisionStore(world).get(result.authorization.decision_id)
    assert stored_decision is not None
    assert stored_decision.decision_input_snapshot.candidate_to_state is BeliefState.CHALLENGED
    assert stored_decision.decision_input_snapshot.hypothesis.admitted_authority_classes == (
        SIM_COARSE,
    )

    # Durable event (`005a`), and it names the decision that authorised it.
    history = SqlBeliefEventStore(world).history(PROJECT, HYP)
    assert [event.to_state for event in history] == [
        BeliefState.ACTIVE,
        BeliefState.CHALLENGED,
    ]
    assert history[-1].authorization_decision_id == result.authorization.decision_id

    # The replayed projection, through the verifying read path.
    projection = _episode(world).project(project_id=PROJECT, hypothesis_id=HYP)
    assert projection.current_state is BeliefState.CHALLENGED
    assert projection.skipped == (), "an event was dropped by re-derivation"


def test_the_same_coarse_contradiction_cannot_produce_a_contradicted_event(world):
    """THE prohibition. Same evidence, same fidelity, terminal state -- and nothing is written.

    Asserted against the STORE rather than against the return value: a DENY that nevertheless left
    a row would be the failure, and a caller-visible refusal beside a durable CONTRADICTED event is
    exactly the shape that would pass a verdict-only test.
    """
    _admit(world)
    _contradiction(world, SIM_COARSE)

    result = _attempt(world, REJECT_POLICY_ID, BeliefState.CONTRADICTED)

    assert result.decision.outcome is TransitionOutcome.DENY
    assert result.decision.reason_code is TransitionReason.AUTHORITY_INSUFFICIENT
    assert result.decision.required_authority_gap == SIM_STANDARD
    assert not result.transitioned

    history = SqlBeliefEventStore(world).history(PROJECT, HYP)
    assert [event.to_state for event in history] == [BeliefState.ACTIVE]
    assert all(event.to_state is not BeliefState.CONTRADICTED for event in history)

    projection = _episode(world).project(project_id=PROJECT, hypothesis_id=HYP)
    assert projection.current_state is BeliefState.ACTIVE
    assert projection.current_state is not BeliefState.CONTRADICTED


def test_a_coarse_result_challenges_and_still_cannot_reject_afterwards(world):
    """The two halves in one history, which is the sequence §25.1's case actually produces.

    A coarse run challenges the hypothesis; the same coarse evidence then tries to finish the job
    and is refused. This is the ordering a careless implementation gets wrong -- once CHALLENGED,
    the "obvious" next step is CONTRADICTED, and the fidelity gate is the only thing between them.
    """
    _admit(world)
    _contradiction(world, SIM_COARSE)
    assert _attempt(world, CHALLENGE_POLICY_ID, BeliefState.CHALLENGED).transitioned

    # The reject policy governs ACTIVE -> CONTRADICTED, and the hypothesis is now CHALLENGED, so
    # this is refused as ungoverned before authority is even consulted -- which is the honest
    # answer: a terminal move from CHALLENGED needs a policy that declares it, and M2 ships none.
    second = _attempt(world, REJECT_POLICY_ID, BeliefState.CONTRADICTED)
    assert not second.transitioned

    projection = _episode(world).project(project_id=PROJECT, hypothesis_id=HYP)
    assert projection.current_state is BeliefState.CHALLENGED


# ---------------------------------------------------------------------------
# Positive controls: the gate opens for standard and validation fidelity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fidelity", [SIM_STANDARD, SIM_VALIDATION])
def test_a_standard_or_validation_contradiction_reaches_contradicted_durably(world, fidelity):
    """Without these, "refuse every rejection" satisfies the prohibition and removes the feature.

    Same path, same policy, same conditions and corroboration -- only the attestation's authority
    class differs, so what is being tested is the gate and not the surrounding requirements.
    """
    _admit(world)
    _contradiction(world, fidelity)

    result = _attempt(world, REJECT_POLICY_ID, BeliefState.CONTRADICTED)

    assert result.decision.outcome is TransitionOutcome.ALLOW, result.decision.reason_code
    assert result.transitioned

    projection = _episode(world).project(project_id=PROJECT, hypothesis_id=HYP)
    assert projection.current_state is BeliefState.CONTRADICTED


def test_standard_fidelity_still_needs_the_other_requirements_the_policy_declares(world):
    """The gate is one of several, and passing it is not passing them all.

    SIM-002 is about authority; the reject policy also declares `min_independent_attestations`, and
    a test that only ever varied fidelity could not tell a working gate from a policy that had
    quietly stopped checking anything else.
    """
    _admit(world)
    _contradiction(world, SIM_STANDARD)

    result = _episode(world).attempt_transition(
        project_id=PROJECT,
        hypothesis_id=HYP,
        policy_id=REJECT_POLICY_ID,
        policy_version=POLICY_VERSION,
        candidate_to_state=BeliefState.CONTRADICTED,
        stakes="HIGH",
        occurred_at=T1,
        trace_id=TRACE,
        episode_id="epi:sim002",
        authority_policy_ref=AUTHORITY_REF,
        condition_matches=(_exact_conditions(),),
        independence_summary=IndependenceSummary(independent_count=0),
    )
    assert result.decision.outcome is TransitionOutcome.NEED_MORE_EVIDENCE
    assert result.decision.reason_code is TransitionReason.INSUFFICIENT_INDEPENDENT_ATTESTATIONS
    assert not result.transitioned


# ---------------------------------------------------------------------------
# Structural: no second belief path was written for M2
# ---------------------------------------------------------------------------


def test_this_file_declares_no_second_belief_path():
    """The instruction, made checkable: use the M0b machinery, do not write a second mutator.

    A helper in this module that appended an event or built a Decision itself would let the
    assertions above pass against a path production does not use. `_admit` is the one exception and
    it calls `admit_hypothesis`, which IS the locked M0b admission gate.
    """
    import tests.e2e.test_sim_fidelity_vertical_postgres as module

    tree = ast.parse(inspect.getsource(module))
    forbidden = {"BeliefRevisionEvent", "BeliefTransitionDecision", "record_transition", "replay"}
    constructed = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert not (constructed & forbidden), (
        f"this module builds {sorted(constructed & forbidden)} directly. SIM-002 must exercise the "
        "existing transition/event/replay path; a second state mutation helper would make the "
        "projection assertions true of something production does not run"
    )
    # ...and it does use the production one.
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "attempt_transition" in called and "project" in called
