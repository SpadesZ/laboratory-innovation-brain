"""A verification result as evidence: only the relations the rivals' own predictions declared, for
the outcome actually observed, in the exact space version they were bound to (§9.1, EVI-009)."""

from __future__ import annotations

import datetime as dt

import pytest

from lab_brain.core.models.enums import EpistemicType, RelationType
from lab_brain.core.models.job import RunStatus
from lab_brain.domains.silicon_photonics import vertical as sp
from lab_brain.verification.evidence import RunEvidenceError, comparable, evidence_from_run
from lab_brain.verification.workflows import ObservedOutcome
from tests.job_fixtures import make_run
from tests.vertical_units import PROJECT, exact_match, predictions

T0 = dt.datetime(2026, 9, 27, 9, 0, tzinfo=dt.UTC)


def _outcome(outcome: str = "DISCONTINUOUS", *, version: str = sp.SPACE_VERSION) -> ObservedOutcome:
    return ObservedOutcome(
        observable_ref=sp.OBS_CONNECTIVITY,
        outcome_space_id=sp.SPACE_CONNECTIVITY,
        outcome_space_version=version,
        outcome=outcome,
        epistemic_type=EpistemicType.OBSERVED,
        authority_class=sp.DESIGN_INSPECTION,
        method_ref="sp.rule.contact_connectivity@1.0.0",
    )


class _Ids:
    def __init__(self) -> None:
        self.n = 0

    def __call__(self, kind: str) -> str:
        self.n += 1
        return f"{kind}:{self.n}"


def _build(outcome: ObservedOutcome, **run: object):  # type: ignore[no-untyped-def]
    return evidence_from_run(
        run=make_run(
            "run:1",
            project_id=PROJECT,
            outputs=("art:out",),
            conditions={"device_length_um": "500"},
            conditions_schema_version=sp.DEVICE_SCHEMA_REF,
            **run,
        ),
        outcome=outcome,
        predictions=(*predictions("contact"), *predictions("mesh")),
        condition_match=exact_match(),
        actor_id="act:researcher",
        mint=_Ids(),
        at=T0,
    )


def test_the_observed_outcome_instantiates_exactly_the_matching_declared_effects():
    supported = _build(_outcome("DISCONTINUOUS"))
    assert [(r.to_entity_id, r.relation_type) for r in supported.relations] == [
        ("hyp:contact", RelationType.SUPPORTS)
    ]
    relation = supported.relations[0]
    assert relation.supporting_attestation_ids == (supported.attestation.attestation_id,)
    assert relation.condition_match_ref == "cmt:unit"
    assert relation.from_entity_id == supported.observation.observation_id
    assert supported.attestation.run_id == "run:1"
    assert supported.observation.run_id == "run:1"
    assert supported.attestation.authority_class == sp.DESIGN_INSPECTION
    contradicted = _build(_outcome("CONTINUOUS"))
    assert [(r.to_entity_id, r.relation_type) for r in contradicted.relations] == [
        ("hyp:contact", RelationType.CONTRADICTS)
    ]


def test_an_outcome_read_in_another_space_version_moves_nothing():
    other = _outcome("DISCONTINUOUS", version="2.0.0")
    assert not any(comparable(p, other) for p in predictions("contact"))
    evidence = _build(other)
    assert evidence.relations == ()
    assert evidence.observation.value == "DISCONTINUOUS", "it is still on record"


def test_only_a_succeeded_run_with_output_becomes_evidence_and_the_rule_is_versioned():
    with pytest.raises(RunEvidenceError, match="not evidence"):
        _build(_outcome(), status=RunStatus.FAILED, output_artifacts=())
    unversioned = ObservedOutcome(
        observable_ref=sp.OBS_CONNECTIVITY,
        outcome_space_id=sp.SPACE_CONNECTIVITY,
        outcome_space_version=sp.SPACE_VERSION,
        outcome="DISCONTINUOUS",
        epistemic_type=EpistemicType.OBSERVED,
        authority_class=sp.DESIGN_INSPECTION,
        method_ref="sp.rule.contact_connectivity",
    )
    with pytest.raises(RunEvidenceError, match="rule_id@version"):
        _build(unversioned)
