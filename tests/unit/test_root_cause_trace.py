"""EPI-002's pure half: a confirmed root cause traces to Run and Artifact, and a model statement
never confirms one. The durable half -- the same chain walked by `011l` for any writer, over a real
VS-SP-001 episode -- is `tests/e2e/test_root_cause_provenance_postgres.py`.

    EPI-002    confirmed root cause 必須可以 trace 回 Run/Evidence/Artifact；LLM statement 不可作為證據。
    T-EPI-002  confirmed root cause query 必須 trace 到 Relation/Attestation or Observation → Run →
               Artifact；只有 LLM statement 的 fixture 不得確認 root cause。
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from lab_brain.core.models.attestation import Attestation
from lab_brain.core.models.belief_event import BeliefState
from lab_brain.core.models.enums import EpistemicType, RelationType, VerificationStatus
from lab_brain.core.models.failure import CandidateHeuristic, FailureAnalysis, ResolutionStatus
from lab_brain.core.models.job import RunStatus
from lab_brain.core.models.observation import Observation
from lab_brain.core.models.relation import RelationJudgment
from lab_brain.core.repositories.failures import FailureStoreError, InMemoryFailureStore
from lab_brain.core.root_cause import (
    MinedEvidence,
    RootCauseRefusal,
    RootCauseRefused,
    confirm_root_cause,
    mine_candidate_heuristics,
    trace_root_cause,
)
from tests.conftest_fixtures import make_attestation
from tests.debate_fixtures import make_set
from tests.job_fixtures import make_run

PROJECT = "prj:m3"
HYP = "hyp:contact"
T0 = dt.datetime(2026, 9, 27, 9, 0, tzinfo=dt.UTC)


class Chain:
    """One SUPPORTED hypothesis whose support is attestation `att` on relation `rel`."""

    def __init__(self, attestation: Attestation, *, state: BeliefState = BeliefState.SUPPORTED):
        self.relation = RelationJudgment(
            relation_id="rel:1",
            from_entity_id="obs:1",
            to_entity_id=HYP,
            relation_type=RelationType.SUPPORTS,
            supporting_attestation_ids=(attestation.attestation_id,),
            project_id=PROJECT,
            valid_from=T0,
            created_at=T0,
        )
        self.attestation = attestation
        self.observation = Observation(
            observation_id="obs:1",
            run_id="run:1",
            metric_or_event="sp.contact_connectivity",
            value="DISCONTINUOUS",
            conditions={"setting": "nominal"},
            conditions_schema_version=attestation.conditions_schema_version,
            method_ref="sp.rule.contact_connectivity@1.0.0",
            project_id=PROJECT,
        )
        self.run = make_run("run:1", project_id=PROJECT, outputs=("art:out",))
        self.events = [
            SimpleNamespace(to_state=BeliefState.ACTIVE, triggering_relation_ids=(), event_id="e0"),
            SimpleNamespace(to_state=state, triggering_relation_ids=("rel:1",), event_id="e1"),
        ]
        self.present = {"art:out"}

    def trace(self) -> Any:
        return trace_root_cause(
            project_id=PROJECT,
            hypothesis_id=HYP,
            history=lambda _p, _h: self.events,  # type: ignore[arg-type,return-value]
            relation=lambda _p, r: self.relation if r == "rel:1" else None,
            attestation=lambda _p, a: (
                self.attestation if a == self.attestation.attestation_id else None
            ),
            observation=lambda _p, o: self.observation if o == "obs:1" else None,
            run=lambda r: self.run if r == "run:1" else None,
            artifact_exists=lambda a: a in self.present,
        )


def _run_backed(**overrides: Any) -> Attestation:
    fields: dict[str, Any] = {
        "attestation_id": "att:inspection",
        "claim_id": None,
        "observation_id": "obs:1",
        "source_work_id": None,
        "run_id": "run:1",
        "epistemic_type": EpistemicType.OBSERVED,
        "project_id": PROJECT,
        "authority_class": "DESIGN_INSPECTION",
    }
    fields.update(overrides)
    return make_attestation(**fields)


@pytest.mark.requirement("EPI-002")
@pytest.mark.spec_test("T-EPI-002")
def test_a_supported_cause_traces_relation_attestation_run_artifact():
    trace = Chain(_run_backed()).trace()
    assert [link.relation_id for link in trace.links] == ["rel:1"]
    assert trace.evidence_ids == ("att:inspection",)
    assert trace.run_ids == ("run:1",)
    assert trace.artifact_ids == ("art:out",)
    # Through the Observation when the attestation names no run itself.
    via_observation = Chain(_run_backed(run_id=None, source_work_id="swk:reader")).trace()
    assert via_observation.run_ids == ("run:1",)


@pytest.mark.requirement("EPI-002")
@pytest.mark.spec_test("T-EPI-002")
def test_a_model_statement_alone_cannot_confirm_a_root_cause():
    """The LLM-only fixture: the only support is an INFERRED attestation of a model's reading."""
    inferred = make_attestation(
        attestation_id="att:llm",
        epistemic_type=EpistemicType.INFERRED,
        project_id=PROJECT,
    )
    with pytest.raises(RootCauseRefused) as refused:
        Chain(inferred).trace()
    assert refused.value.reason is RootCauseRefusal.ONLY_MODEL_STATEMENTS
    assert "att:llm" in refused.value.detail


@pytest.mark.requirement("EPI-002")
@pytest.mark.spec_test("T-EPI-002")
def test_every_missing_link_refuses_and_names_itself():
    # A report someone wrote: admissible, but the output of no execution.
    reported = make_attestation(attestation_id="att:paper", project_id=PROJECT)
    with pytest.raises(RootCauseRefused) as refused:
        Chain(reported).trace()
    assert refused.value.reason is RootCauseRefusal.NO_EXECUTION_TRACE
    assert "no Run in its chain" in refused.value.detail

    disputed = Chain(_run_backed(verification_status=VerificationStatus.DISPUTED))
    with pytest.raises(RootCauseRefused, match="DISPUTED"):
        disputed.trace()

    failed = Chain(_run_backed())
    failed.run = make_run("run:1", project_id=PROJECT, outputs=(), status=RunStatus.FAILED)
    with pytest.raises(RootCauseRefused, match="is FAILED"):
        failed.trace()

    vanished = Chain(_run_backed())
    vanished.present = set()
    with pytest.raises(RootCauseRefused, match="missing"):
        vanished.trace()

    elsewhere = Chain(_run_backed())
    elsewhere.run = make_run("run:1", project_id="prj:other", outputs=("art:out",))
    with pytest.raises(RootCauseRefused, match="does not resolve"):
        elsewhere.trace()

    not_supported = Chain(_run_backed(), state=BeliefState.CHALLENGED)
    with pytest.raises(RootCauseRefused) as refused:
        not_supported.trace()
    assert refused.value.reason is RootCauseRefusal.NOT_SUPPORTED


@pytest.mark.requirement("EPI-002")
@pytest.mark.spec_test("T-EPI-002")
def test_a_confirmed_analysis_names_its_traced_evidence_and_only_a_root_cause_set_confirms():
    trace = Chain(_run_backed()).trace()
    hypothesis_set = make_set("hst:m4", project_id=PROJECT, root_cause=True)
    analysis = confirm_root_cause(
        hypothesis_set=hypothesis_set,
        hypothesis_id=HYP,
        candidate_causes=(HYP, "hyp:mesh"),
        trace=trace,
        failure_analysis_id="fan:1",
        symptom="Rs high and flat",
        expected_behavior="design Rs",
        observed_behavior="several times design",
        failure_class="access contact discontinuity",
        created_at=T0,
    )
    assert analysis.resolution_status is ResolutionStatus.CONFIRMED
    assert analysis.root_cause_evidence_ids == ("att:inspection",)
    with pytest.raises(RootCauseRefused) as refused:
        confirm_root_cause(
            hypothesis_set=make_set("hst:routine", project_id=PROJECT, root_cause=False),
            hypothesis_id=HYP,
            candidate_causes=(HYP,),
            trace=trace,
            failure_analysis_id="fan:2",
            symptom="s",
            expected_behavior="e",
            observed_behavior="o",
            failure_class="c",
            created_at=T0,
        )
    assert refused.value.reason is RootCauseRefusal.NOT_A_ROOT_CAUSE_CANDIDATE


def _analysis(**overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "failure_analysis_id": "fan:1",
        "project_id": PROJECT,
        "episode_id": "epi:1",
        "symptom": "Rs high and flat",
        "expected_behavior": "design Rs",
        "observed_behavior": "several times design",
        "candidate_causes": (HYP, "hyp:mesh"),
        "confirmed_root_cause": HYP,
        "root_cause_evidence_ids": ("att:inspection",),
        "failure_class": "access contact discontinuity",
        "resolution_status": ResolutionStatus.CONFIRMED,
        "created_at": T0,
    }
    fields.update(overrides)
    return fields


@pytest.mark.requirement("EPI-002")
@pytest.mark.spec_test("T-EPI-002")
def test_the_failure_analysis_model_refuses_a_confirmation_without_evidence():
    FailureAnalysis(**_analysis())
    with pytest.raises(ValidationError, match="names no evidence"):
        FailureAnalysis(**_analysis(root_cause_evidence_ids=()))
    with pytest.raises(ValidationError, match="never a candidate"):
        FailureAnalysis(**_analysis(confirmed_root_cause="hyp:unlisted"))
    with pytest.raises(ValidationError, match="exactly when"):
        FailureAnalysis(**_analysis(resolution_status=ResolutionStatus.INCONCLUSIVE))
    with pytest.raises(ValidationError, match="does not confirm"):
        FailureAnalysis(
            **_analysis(
                confirmed_root_cause=None,
                resolution_status=ResolutionStatus.INCONCLUSIVE,
            )
        )


def _mint() -> Any:
    counter = iter(range(1, 100))
    return lambda kind: f"chr:{next(counter)}"


def test_recurring_confirmed_failures_become_one_pending_review_candidate():
    """§25.4: 同類失敗形成可審核 heuristic candidate -- and one failure is not a pattern."""
    first = FailureAnalysis(**_analysis(failure_analysis_id="fan:1", episode_id="epi:1"))
    second = FailureAnalysis(**_analysis(failure_analysis_id="fan:2", episode_id="epi:2"))
    evidence = {
        f.failure_analysis_id: MinedEvidence(
            capability_ids=("cap:sp.inspect_contact_connectivity",),
            artifact_ids=(f"art:{f.failure_analysis_id}",),
            run_ids=(f"run:{f.failure_analysis_id}",),
        )
        for f in (first, second)
    }
    assert (
        mine_candidate_heuristics(
            [first], evidence_for=evidence, existing=(), mint=_mint(), now=lambda: T0
        )
        == ()
    )
    (candidate,) = mine_candidate_heuristics(
        [first, second], evidence_for=evidence, existing=(), mint=_mint(), now=lambda: T0
    )
    assert candidate.status == "PENDING_REVIEW"
    assert candidate.suggested_checks == ("cap:sp.inspect_contact_connectivity",)
    assert candidate.source_episode_ids == ("epi:1", "epi:2")
    assert candidate.source_artifact_ids == ("art:fan:1", "art:fan:2")
    assert candidate.derived_from_failures == ("fan:1", "fan:2")
    # Proposed once: the same evidence does not produce a second candidate.
    assert (
        mine_candidate_heuristics(
            [first, second],
            evidence_for=evidence,
            existing=(candidate,),
            mint=_mint(),
            now=lambda: T0,
        )
        == ()
    )
    with pytest.raises(ValidationError):
        CandidateHeuristic.model_validate({**candidate.model_dump(), "status": "ACTIVE"})
    with pytest.raises(ValidationError):
        CandidateHeuristic.model_validate({**candidate.model_dump(), "source_locators": ()})


def test_the_in_memory_failure_store_is_append_only_and_candidates_rest_on_confirmed_failures():
    store = InMemoryFailureStore()
    store.add_analysis(FailureAnalysis(**_analysis()))
    with pytest.raises(FailureStoreError, match="append-only"):
        store.add_analysis(FailureAnalysis(**_analysis()))
    store.add_analysis(
        FailureAnalysis(
            **_analysis(
                failure_analysis_id="fan:open",
                confirmed_root_cause=None,
                root_cause_evidence_ids=(),
                resolution_status=ResolutionStatus.OPEN,
            )
        )
    )
    assert store.similar_failures(PROJECT, "  rs HIGH and flat ") == ("fan:1",)
    assert store.similar_failures("prj:other", "Rs high and flat") == ()
    candidate = CandidateHeuristic(
        candidate_id="chr:1",
        project_id=PROJECT,
        trigger_pattern="rs high and flat",
        suggested_checks=("cap:sp.inspect_contact_connectivity",),
        rationale="r",
        source_artifact_ids=("art:1",),
        source_locators=("run:1",),
        source_episode_ids=("epi:1",),
        miner_model_version="m@1",
        derived_from_failures=("fan:open",),
        created_at=T0,
    )
    with pytest.raises(FailureStoreError, match="not a CONFIRMED"):
        store.add_candidate(candidate)
    store.add_candidate(candidate.model_copy(update={"derived_from_failures": ("fan:1",)}))
