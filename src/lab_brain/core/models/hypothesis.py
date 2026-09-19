"""§8.1's Hypothesis certificate, as the minimum M0b can hold honestly (SYS-001).

    §8.1  Hypothesis {
            hypothesis_id, statement, mechanism, assumptions[],
            prediction_ids[],                      # references Prediction (17.5.1), not free text
            falsifier, confounders[], minimal_test_ref?, parent_id?,
            status_projection, belief_level_projection,
            created_in_episode, inference_provenance_id
          }

          No evidence_for[] / evidence_against[] / triggering_evidence_ids[] arrays.
          Support/contradiction is resolved only through RelationJudgment.
          Status is rebuilt from BeliefRevisionEvent + TransitionPolicy.

WHY THIS EXISTS NOW AND NOT IN M3. `docs/milestones.yaml` moved SYS-001 from M0a to M0b on exactly
this reasoning:

    its §26 pass condition is "rejects bypass from cognition directly to EpistemicState
    update OR support arrays on Attestation/Hypothesis". EpistemicStateProjection and
    Hypothesis do not exist until M0b, so only half the condition is exercisable here.

`EpistemicStateProjection` landed with EPI-003. This is the other half. Without it the "on
Hypothesis" clause has no subject, and SYS-001 would be discharged against `HypothesisView` — a
surrogate — while the milestone record said the real thing was testable here.

WHAT IS *NOT* HERE, AND IT IS THE EXPENSIVE HALF. §8's **Hypothesis Admission Gate** — deciding
whether a mechanism is a mechanism, whether a falsifier could actually falsify, whether the minimum
test is minimal — is `EPI-001` in M3. This module holds the *certificate*, and the certificate is a
data contract: the fields exist, the forbidden ones cannot, and the typed references are typed.
Judging the contents is cognition and is not built here.

THE ONE DESIGN DECISION WORTH READING. §8.1 lists `status_projection` and
`belief_level_projection`, **and this model does not carry them.** Four lines further down the same
block says:

    Status is rebuilt from BeliefRevisionEvent + TransitionPolicy.

A stored, writable `status_projection` is precisely the "bypass from cognition directly to
EpistemicState update" that T-SYS-001 requires be rejected: it is a place to put an answer instead
of deriving one. So the projection lives where it is derived --
:class:`lab_brain.core.belief.EpistemicStateProjection`, keyed by `target_id` -- and the
certificate names the hypothesis, not its current belief. Read `status_projection` as "this
hypothesis *has* a status projection", which it does, in the projector.
"""

from __future__ import annotations

from typing import Self

from pydantic import model_validator

from lab_brain.core.models.attestation import FORBIDDEN_RELATION_FIELDS
from lab_brain.core.models.base import CoreModel


class Hypothesis(CoreModel):
    """§8.1's certificate: what was proposed, and what would refute it.

    Frozen and `extra="forbid"` like every core entity, which is what makes the "no support arrays"
    rule enforceable rather than aspirational: a `supports=[...]` passed to the constructor is a
    validation error, not a silently-kept attribute.
    """

    hypothesis_id: str
    project_id: str
    #: The proposition itself. Free text, because a hypothesis *is* a sentence a human wrote.
    statement: str
    #: Why it would be true. §8's admission gate judges this; M0b only insists it is present.
    mechanism: str
    assumptions: tuple[str, ...] = ()
    #: References to §17.5.1 `Prediction` objects -- **ids, not prose**. §8.1: "predictions are
    #: typed objects, not prose; the planner cannot infer outcome effects from free text." The
    #: objects themselves arrived with VER-006.
    prediction_ids: tuple[str, ...] = ()
    #: What observation would refute this. A hypothesis with no falsifier is not a hypothesis, so
    #: this is required rather than optional -- the one §8 quality rule cheap enough to hold here.
    falsifier: str
    confounders: tuple[str, ...] = ()
    minimal_test_ref: str | None = None
    parent_id: str | None = None
    created_in_episode: str | None = None
    #: Required when an LLM proposed the hypothesis (LLM-001 / AGT-010).
    inference_provenance_id: str | None = None

    @model_validator(mode="after")
    def _a_hypothesis_says_something_and_can_be_wrong(self) -> Self:
        """Blank `statement`, `mechanism` or `falsifier` is refused.

        A required field satisfied by an empty string is an optional field with extra steps, and
        these three are what separate §8's "scientific hypothesis" from its "idea". The full
        admission gate (EPI-001, M3) judges whether they are any *good*; refusing the empty case is
        the part that needs no cognition and would otherwise let an idea occupy simulation budget.
        """
        blank = sorted(
            name
            for name in ("statement", "mechanism", "falsifier")
            if not getattr(self, name).strip()
        )
        if blank:
            raise ValueError(
                f"hypothesis {self.hypothesis_id} has blank {blank}. §8 admits a hypothesis only "
                "with a mechanism and a falsifier; without them it is an idea, and ideas do not "
                "occupy simulation budget"
            )
        return self

    @model_validator(mode="after")
    def _a_hypothesis_is_not_its_own_parent(self) -> Self:
        if self.parent_id == self.hypothesis_id:
            raise ValueError(
                f"hypothesis {self.hypothesis_id} names itself as parent; an EVOLVED chain that "
                "loops has no origin and replay would not terminate"
            )
        return self


#: Field names that would make the Hypothesis certificate carry its own belief state.
#:
#: Separate from `FORBIDDEN_RELATION_FIELDS` because they are a different mistake. A support array
#: is a second store of *evidence*; a status column is a second store of the *conclusion* -- and
#: §8.1 says the conclusion is rebuilt from `BeliefRevisionEvent` + `TransitionPolicy`. T-SYS-001
#: names both, and the second is the one an LLM-driven implementation reaches for first.
FORBIDDEN_STATUS_FIELDS = frozenset(
    {
        "status",
        "current_status",
        "current_state",
        "status_projection",
        "belief_state",
        "belief_level",
        "belief_level_projection",
    }
)

#: Everything a §8.1 certificate must not carry, as one set for the conformance test.
FORBIDDEN_HYPOTHESIS_FIELDS = FORBIDDEN_RELATION_FIELDS | FORBIDDEN_STATUS_FIELDS


__all__ = [
    "FORBIDDEN_HYPOTHESIS_FIELDS",
    "FORBIDDEN_STATUS_FIELDS",
    "Hypothesis",
]
