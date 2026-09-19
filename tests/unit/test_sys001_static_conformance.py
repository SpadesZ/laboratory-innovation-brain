"""T-SYS-001's static half, executed **under the SYS-001 marker** (architecture).

    §26  SYS-001 | T-SYS-001 | architecture | static/conformance test rejects bypass from
         cognition directly to EpistemicState update or support arrays on Attestation/Hypothesis.

WHY THIS MODULE EXISTS RATHER THAN A MARKER ON THE OLD ONE. The support-array assertions have been
in `tests/unit/test_core_architecture_invariants.py` since M0a, and that module is deliberately
**unmarked** -- correctly at the time, since it also guards things that are not SYS-001 (frozen
models, `extra="forbid"`, the DomainPack import direction, migration ordering). So the exact
obligation §26 names was executing, and executing under no requirement at all: the marked SYS-001
module is an e2e that proves the *dynamic* half and performs none of these assertions.

The M0b sign-off audit called that out, and the fix is not a second marker on the old module.
Markers multiply: `requirement` × `spec_test` is a cross-product, so adding SYS-001/T-SYS-001 beside
nothing would be fine but adding it to a module that later gained a second pair would claim a
mapping §26 does not have. One module, one pair, containing exactly the clause -- and the old
module keeps the checks that are not SYS-001's.

NO `postgres` MARKER, DELIBERATELY. §26 types this test `architecture`. A static conformance check
that needed a database would be skipped by the backend-free profile, which is the run that proves
AGT-007 -- and "rejects support arrays" is a fact about the source tree, not about a row.
"""

from __future__ import annotations

import pytest

from lab_brain.core.belief import EpistemicStateProjection
from lab_brain.core.models import FORBIDDEN_RELATION_FIELDS
from lab_brain.core.models.artifact import Artifact
from lab_brain.core.models.attestation import Attestation
from lab_brain.core.models.claim import Claim
from lab_brain.core.models.hypothesis import (
    FORBIDDEN_HYPOTHESIS_FIELDS,
    FORBIDDEN_STATUS_FIELDS,
    Hypothesis,
)
from lab_brain.core.models.observation import Observation
from lab_brain.core.models.relation import RelationJudgment
from lab_brain.core.models.source_work import SourceWork
from lab_brain.core.models.transition import HypothesisView

pytestmark = [pytest.mark.requirement("SYS-001"), pytest.mark.spec_test("T-SYS-001")]

#: The entities §26's clause names, plus the ones on the same path. `Hypothesis` is first because
#: it is the half that had no subject until M0b closure.
SUBJECTS = (Hypothesis, Attestation, Artifact, SourceWork, Claim, Observation, RelationJudgment)


# --------------------------------------------------------------------------------------------
# "support arrays on Attestation/Hypothesis"
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("model", SUBJECTS, ids=lambda m: m.__name__)
def test_no_entity_carries_a_parallel_support_array(model):
    """Support and contradiction are resolved only through `RelationJudgment` (§8.1, §17.2).

    A parallel array is a second store of the same fact that nothing keeps in step with the
    relation table, and when the two disagree there is no way to tell which one the belief state
    was computed from.
    """
    offending = sorted(set(model.model_fields) & FORBIDDEN_RELATION_FIELDS)
    assert not offending, (
        f"{model.__name__} declares {offending}; support/contradiction is resolved only through "
        "RelationJudgment"
    )


def test_the_hypothesis_certificate_carries_no_support_array_by_construction():
    """Not only absent from the declaration -- unconstructable.

    `extra="forbid"` is what turns "we did not add the field" into "the field cannot be added by a
    caller", which is the difference between a convention and a conformance rule.
    """
    with pytest.raises(ValueError):
        Hypothesis(
            hypothesis_id="hyp:1",
            project_id="prj:1",
            statement="contact resistance falls with anneal time",
            mechanism="interfacial oxide reduction",
            falsifier="no change after a 30-minute anneal",
            evidence_for=["att:1"],  # type: ignore[call-arg]
        )


def test_the_hypothesis_view_carries_no_support_array_either():
    """The surrogate is held to the same rule as the certificate.

    `HypothesisView` is what `TransitionPolicy.evaluate` actually reads, so if a support array were
    ever going to appear it would appear here -- "just pass the supporting ids along" is the
    shortest path to the arrangement §17.19.3 forbids. `conflicts` is present and is not an
    exception: it holds typed `Conflict` records the policy matches against its own declared
    `blocking_conflict_policy`, where a support array would be the caller's conclusion.
    """
    offending = sorted(set(HypothesisView.model_fields) & FORBIDDEN_RELATION_FIELDS)
    assert not offending, f"HypothesisView declares {offending}"


# --------------------------------------------------------------------------------------------
# "bypass from cognition directly to EpistemicState update"
# --------------------------------------------------------------------------------------------


def test_the_hypothesis_certificate_stores_no_belief_status():
    """§8.1: "Status is rebuilt from BeliefRevisionEvent + TransitionPolicy."

    THE FIELD LIST IN §8.1 NAMES `status_projection`, AND THIS ASSERTS ITS ABSENCE. Those two
    sentences are four lines apart in the same block, and the second one wins: a stored, writable
    status is a place to put an answer instead of deriving one, which is the bypass §26 names. The
    projection lives in `EpistemicStateProjection`, where it is computed.
    """
    offending = sorted(set(Hypothesis.model_fields) & FORBIDDEN_STATUS_FIELDS)
    assert not offending, (
        f"Hypothesis declares {offending}; §8.1 rebuilds status from BeliefRevisionEvent, and a "
        "stored status field is somewhere to write one instead"
    )


def test_a_cognition_result_cannot_be_written_onto_the_certificate():
    """The bypass attempted, not assumed impossible.

    This is the exact shape: a model returns a status, and a caller sets it on the hypothesis.
    There is no attribute to set, and the model is frozen, so both halves fail.
    """
    hypothesis = Hypothesis(
        hypothesis_id="hyp:1",
        project_id="prj:1",
        statement="contact resistance falls with anneal time",
        mechanism="interfacial oxide reduction",
        falsifier="no change after a 30-minute anneal",
    )
    assert not hasattr(hypothesis, "status_projection")

    with pytest.raises(ValueError):
        hypothesis.status_projection = "SUPPORTED"  # type: ignore[attr-defined]
    with pytest.raises(ValueError):
        hypothesis.statement = "something else"  # type: ignore[misc]


def test_the_projection_is_the_only_place_a_belief_state_lives():
    """And it is derived: its `current_state` comes from folding events, not from a setter.

    Asserted together so the pair is visible -- the certificate has no status, the projection has
    one, and the only way to change the projection is to append an event and replay.
    """
    assert "current_state" in {
        field.name for field in EpistemicStateProjection.__dataclass_fields__.values()
    }
    assert FORBIDDEN_STATUS_FIELDS & set(Hypothesis.model_fields) == set()

    projection = EpistemicStateProjection(
        project_id="prj:1", target_id="hyp:1", current_state=None, last_event_id=None
    )
    with pytest.raises(Exception):  # noqa: B017 - frozen dataclass; the type varies by Python
        projection.current_state = "SUPPORTED"  # type: ignore[misc]


# --------------------------------------------------------------------------------------------
# The certificate is a certificate: typed predictions, a falsifier, no idea-shaped holes.
# --------------------------------------------------------------------------------------------


def test_predictions_are_referenced_by_id_not_written_as_prose():
    """§8.1: "predictions are typed objects, not prose; the planner cannot infer outcome effects
    from free text." The ids point at VER-006's `Prediction`, which landed in M0b."""
    annotation = str(Hypothesis.model_fields["prediction_ids"].annotation)
    assert "str" in annotation and "tuple" in annotation.lower()


@pytest.mark.parametrize("field", ["statement", "mechanism", "falsifier"])
def test_a_blank_certificate_field_is_refused(field):
    """A required field satisfied by an empty string is an optional field with extra steps.

    §8's full admission gate judges whether a mechanism is any *good* -- that is EPI-001 in M3.
    Refusing the empty case needs no cognition and is what stops an idea occupying simulation
    budget.
    """
    fields = {
        "hypothesis_id": "hyp:1",
        "project_id": "prj:1",
        "statement": "contact resistance falls with anneal time",
        "mechanism": "interfacial oxide reduction",
        "falsifier": "no change after a 30-minute anneal",
    }
    fields[field] = "   "
    with pytest.raises(ValueError, match="blank"):
        Hypothesis(**fields)  # type: ignore[arg-type]


def test_the_forbidden_vocabularies_are_not_empty():
    """The guards' *data*, held by a test. Found by mutation, and it is the P12 lesson again.

    Every assertion above is a set intersection against a frozenset of names. Emptying that
    frozenset makes all of them pass while the rule they encode stops existing -- the mutation run
    emptied `FORBIDDEN_STATUS_FIELDS` and the whole module stayed green. A check whose vocabulary
    can be switched off silently is a check that is not held.

    The names below are the ones §8.1 and §26 actually name, so this fails if the vocabulary is
    emptied, trimmed, or renamed out from under the tests.
    """
    # Pinned exactly, not as a subset. A subset check catches an emptied vocabulary and misses a
    # trimmed one, and trimming is the likelier accident: someone removes the name they just hit.
    # Adding a name here is safe and deliberate; this line is where that deliberation happens.
    assert {
        "status",
        "current_status",
        "current_state",
        "status_projection",
        "belief_state",
        "belief_level",
        "belief_level_projection",
    } == FORBIDDEN_STATUS_FIELDS, "§8.1's projection fields must stay forbidden on the certificate"

    assert {
        "evidence_for",
        "evidence_against",
        "triggering_evidence_ids",
    } <= FORBIDDEN_RELATION_FIELDS, (
        "§8.1 names these three explicitly: 'No evidence_for[] / evidence_against[] / "
        "triggering_evidence_ids[] arrays'"
    )

    assert FORBIDDEN_RELATION_FIELDS <= FORBIDDEN_HYPOTHESIS_FIELDS
    assert FORBIDDEN_STATUS_FIELDS <= FORBIDDEN_HYPOTHESIS_FIELDS
