"""Every decision the deployment stored before the Causal Warrant Gate still re-derives, byte-exact.

`fixtures/history/pre_gate_decisions.json` is a read-only export of every BELIEF_TRANSITION
decision in the deployment on 2026-10-14 -- including `dec:7d6d7411`, the ALLOW behind the wrong
confirmation of `epi:7b56877f`. History is not rewritten: each stored snapshot must canonicalise to
exactly the text and hash that were stored, and re-evaluate under its own policy version to exactly
the verdict that was stored. The gate added a field to the hypothesis view; this is the test that
it changed nothing already written.

And one forward-looking check on the same record: evaluated under the warrant-gated 2.0.0 policy,
the snapshot behind the wrong confirmation asks for a warrant instead of allowing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from lab_brain.core.canonical_json import canonicalize
from lab_brain.core.models.decision import DecisionInputSnapshot
from lab_brain.core.models.transition import (
    RelationEvidence,
    TransitionOutcome,
    TransitionReason,
)
from lab_brain.domains.silicon_photonics import vertical as sp
from lab_brain.domains.silicon_photonics.authority_policy import (
    SiliconPhotonicsAuthorityPolicy,
    transition_policies,
    warranted_transition_policies,
)

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "history" / "pre_gate_decisions.json"
DECISIONS: list[dict[str, Any]] = json.loads(FIXTURE.read_text(encoding="utf-8"))["decisions"]
WRONG_CONFIRMATION = "dec:7d6d7411-c9e9-4bbd-80e2-7c81185299e4"

POLICIES = {
    (p.policy_id, p.version): p
    for p in (
        *transition_policies(),
        *warranted_transition_policies(),
        *sp.vertical_transition_policies(),
    )
}
COMPARATORS = {
    (c.policy_id, c.policy_version): c
    for c in (sp.VerticalAuthorityPolicy(), SiliconPhotonicsAuthorityPolicy())
}


def _snapshot(record: dict[str, Any]) -> DecisionInputSnapshot:
    return DecisionInputSnapshot.model_validate_json(record["decision_input_snapshot"])


@pytest.mark.parametrize("record", DECISIONS, ids=[d["decision_id"] for d in DECISIONS])
def test_a_stored_snapshot_canonicalises_to_exactly_what_was_stored(record: dict[str, Any]):
    snapshot = _snapshot(record)
    assert snapshot.canonical_bytes_text() == record["decision_input_snapshot"]
    assert snapshot.input_hash() == record["input_hash"]


@pytest.mark.parametrize("record", DECISIONS, ids=[d["decision_id"] for d in DECISIONS])
def test_a_stored_decision_re_evaluates_to_exactly_its_stored_verdict(record: dict[str, Any]):
    snapshot = _snapshot(record)
    policy = POLICIES[(record["policy_id"], record["policy_version"])]
    assert not policy.diagnostic_warrant_required, "history was decided by ungated versions"
    comparator = COMPARATORS[
        (snapshot.authority_policy_id or "", snapshot.authority_policy_version or "")
    ]
    replayed = policy.evaluate(
        snapshot.hypothesis,
        snapshot.admitted_relations,
        comparator,
        snapshot.condition_matches,
        snapshot.independence_summary,
        snapshot.candidate_to_state,
    )
    assert canonicalize(replayed.model_dump(mode="json")) == record["evaluated_decision"]


def test_the_wrong_confirmation_would_have_asked_for_a_warrant_under_the_gate():
    record = next(d for d in DECISIONS if d["decision_id"] == WRONG_CONFIRMATION)
    snapshot = _snapshot(record)
    gated = POLICIES[(record["policy_id"], sp.WARRANTED_VERTICAL_POLICY_VERSION)]
    verdict = gated.evaluate(
        snapshot.hypothesis,
        snapshot.admitted_relations,
        COMPARATORS[("auth:silicon_photonics", "1.1.0")],
        snapshot.condition_matches,
        snapshot.independence_summary,
        snapshot.candidate_to_state,
    )
    assert verdict.outcome is TransitionOutcome.NEED_HUMAN_REVIEW
    assert verdict.reason_code is TransitionReason.DIAGNOSTIC_WARRANT_MISSING
    # With the facts the resolver would give it: its own authority and line, and no warrant --
    # "missing correction artefact" is not a class the pack declares for the normalization basis.
    (relation,) = snapshot.admitted_relations
    resolved = snapshot.hypothesis.model_copy(
        update={
            "relation_evidence": (
                RelationEvidence(
                    relation_id=relation.relation_id,
                    relation_type=relation.relation_type,
                    prediction_id=str(relation.attributes["prediction_id"]),
                    authority_classes=("DESIGN_INSPECTION",),
                    evidence_line="line:extraction",
                ),
            )
        }
    )
    verdict = gated.evaluate(
        resolved,
        snapshot.admitted_relations,
        COMPARATORS[("auth:silicon_photonics", "1.1.0")],
        snapshot.condition_matches,
        snapshot.independence_summary,
        snapshot.candidate_to_state,
    )
    assert verdict.reason_code is TransitionReason.DIAGNOSTIC_WARRANT_MISSING
