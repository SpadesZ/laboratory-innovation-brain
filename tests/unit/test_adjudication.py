"""SRC-002 / §7.6: the one statement of what may adjudicate a critique -- read from the record.

`core.adjudication` is used by both §7.6 triggers: M2's dispatcher for an irreversible action, and
`HypothesisRevisionGate` (through `admissible`) for a major REJECT. These tests pin the rule itself;
the dispatch and belief paths are exercised in `test_irreversible_dispatch.py`, `test_revision_gate.py`
and `e2e/test_hypothesis_brain_postgres.py`.
"""

from __future__ import annotations

import pytest

from lab_brain.core.adjudication import (
    AdjudicationBasisRefused,
    admissible,
    inadmissibility,
    resolve_adjudication_basis,
)
from lab_brain.core.critique_gate import Adjudicator
from lab_brain.core.models.enums import EpistemicType, VerificationStatus
from tests.conftest_fixtures import make_attestation

pytestmark = [pytest.mark.requirement("SRC-002"), pytest.mark.spec_test("T-SRC-002")]

PROJECT = "prj:test"


def _att(attestation_id: str, kind: EpistemicType, **overrides: object):  # type: ignore[no-untyped-def]
    return make_attestation(
        attestation_id=attestation_id, epistemic_type=kind, project_id=PROJECT, **overrides
    )


RECORD = {
    "att:measured": _att("att:measured", EpistemicType.MEASURED),
    "att:reported": _att("att:reported", EpistemicType.REPORTED),
    "att:derived": _att("att:derived", EpistemicType.DERIVED),
    "att:inferred": _att("att:inferred", EpistemicType.INFERRED),
    "att:disputed": _att(
        "att:disputed", EpistemicType.MEASURED, verification_status=VerificationStatus.DISPUTED
    ),
    "att:run": _att(
        "att:run", EpistemicType.SIMULATED, source_work_id=None, run_id="run:verification"
    ),
}


def _lookup(project_id: str, attestation_id: str):  # type: ignore[no-untyped-def]
    found = RECORD.get(attestation_id)
    return found if found is not None and found.project_id == project_id else None


def _basis(*ids: str):  # type: ignore[no-untyped-def]
    return resolve_adjudication_basis(ids, project_id=PROJECT, attestations=_lookup)


def test_only_inferred_evidence_is_model_opinion():
    basis = _basis("att:inferred")
    assert basis.admissible == ()
    assert basis.adjudicator is Adjudicator.MODEL_OPINION
    assert "INFERRED" in basis.excluded[0][1]


def test_disputed_evidence_is_set_aside():
    assert _basis("att:disputed").adjudicator is Adjudicator.MODEL_OPINION
    assert inadmissibility(RECORD["att:disputed"]) is not None


@pytest.mark.parametrize("attestation_id", ["att:measured", "att:reported", "att:derived"])
def test_factual_evidence_is_external(attestation_id):
    assert _basis(attestation_id).adjudicator is Adjudicator.EXTERNAL_EVIDENCE


def test_a_runs_witness_is_a_verification_result():
    assert _basis("att:run", "att:reported").adjudicator is Adjudicator.VERIFICATION_RESULT


def test_inferred_beside_factual_is_set_aside_not_fatal():
    basis = _basis("att:inferred", "att:reported")
    assert [a.attestation_id for a in basis.admissible] == ["att:reported"]
    assert [i for i, _ in basis.excluded] == ["att:inferred"]
    assert basis.adjudicator is Adjudicator.EXTERNAL_EVIDENCE


def test_a_citation_that_resolves_nowhere_refuses_the_whole_basis():
    with pytest.raises(AdjudicationBasisRefused, match="att:ghost"):
        _basis("att:reported", "att:ghost")


def test_another_projects_record_does_not_count_even_from_an_unscoped_store():
    foreign = RECORD["att:reported"].model_copy(update={"project_id": "prj:other"})
    with pytest.raises(AdjudicationBasisRefused, match="SEC-002"):
        resolve_adjudication_basis(
            ["att:reported"], project_id=PROJECT, attestations=lambda _p, _a: foreign
        )


def test_the_basis_is_independent_of_citation_order():
    one = _basis("att:reported", "att:inferred", "att:measured")
    other = _basis("att:measured", "att:reported", "att:inferred", "att:reported")
    assert one == other


def test_admissible_is_the_same_rule_the_revision_gate_reads():
    kept = admissible(RECORD.values())
    assert {a.attestation_id for a in kept} == {
        "att:measured",
        "att:reported",
        "att:derived",
        "att:run",
    }
