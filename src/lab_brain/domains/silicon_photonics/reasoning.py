"""What this pack contributes to M3's reasoning: an OutcomeSpace, its metric, and two specialists.

THE OUTCOME SPACE IS VS-SP-001's QUESTION, NOT A GENERIC ONE. §25.1's anomaly is "Rs extremely high
and weakly bias-dependent", and the rival mechanisms it names -- access/contact discontinuity, a
mesh/convergence artefact, a contact/material/normalization model issue -- disagree about how Rs
should respond to reverse bias. So the declared outcomes are exactly those responses, ordered, and
a Prediction over `sp.small_signal_impedance` says which one its hypothesis expects.

THE METRIC IS ORDINAL DISTANCE, AND IT IS THIS DOMAIN'S CHOICE. Two predictions that Rs falls and
that Rs rises with reverse bias disagree more than two that differ by one step; the metric says so,
normalised to [0, 1]. It is declared here -- core has no distance of its own (VER-008) -- and a
different domain may declare a different one: the ToyDomain's is categorical.

SPECIALISTS ARE DATA. §7.1 makes a Domain Specialist "不是 core" and limits it to the evidence its
DomainPack authorises; each one is a prompt, a reading scope and a retrieval vocabulary, routed by
`lab_brain.cognition` and never executed by core.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Final

from lab_brain.core.models.benchmark import DisagreementMetric
from lab_brain.core.models.prediction import OutcomeSpace
from lab_brain.domains.base import SpecialistRole
from lab_brain.domains.silicon_photonics.condition_schema import DOMAIN
from lab_brain.domains.silicon_photonics.tools import OBSERVABLE_IMPEDANCE

RS_RESPONSE_SPACE_ID: Final = "os:sp.rs_bias_response"
RS_RESPONSE_SPACE_VERSION: Final = "1.0.0"
RS_FALLS: Final = "RS_FALLS_WITH_REVERSE_BIAS"
RS_INSENSITIVE: Final = "RS_BIAS_INSENSITIVE"
RS_RISES: Final = "RS_RISES_WITH_REVERSE_BIAS"
#: Ordered: the metric's rank is the position here.
RS_RESPONSES: Final = (RS_FALLS, RS_INSENSITIVE, RS_RISES)

RS_RESPONSE_METRIC_ID: Final = "dm:sp.rs_response_rank_distance"
RS_RESPONSE_METRIC_VERSION: Final = "1.0.0"

#: The observable the space's outcomes are read from: the small-signal impedance sweep's Rs(V).
RS_RESPONSE_OBSERVABLE: Final = OBSERVABLE_IMPEDANCE


def rs_response_space() -> OutcomeSpace:
    return OutcomeSpace(
        outcome_space_id=RS_RESPONSE_SPACE_ID,
        version=RS_RESPONSE_SPACE_VERSION,
        domain=DOMAIN,
        action_type="SIMULATION",
        hypothesis_type="ROOT_CAUSE",
        outcomes=RS_RESPONSES,
        order_or_metric_ref=f"{RS_RESPONSE_METRIC_ID}@{RS_RESPONSE_METRIC_VERSION}",
    )


class RsResponseRankDistance:
    """|rank(a) - rank(b)| / (n - 1) over the ordered Rs responses. Exact, symmetric, pure."""

    @property
    def declaration(self) -> DisagreementMetric:
        return DisagreementMetric(
            metric_id=RS_RESPONSE_METRIC_ID,
            outcome_space_id=RS_RESPONSE_SPACE_ID,
            outcome_space_version=RS_RESPONSE_SPACE_VERSION,
            implementation_ref=f"{__name__}:RsResponseRankDistance",
            version=RS_RESPONSE_METRIC_VERSION,
        )

    def distance(self, a: str, b: str) -> Decimal:
        span = Decimal(len(RS_RESPONSES) - 1)
        return Decimal(abs(RS_RESPONSES.index(a) - RS_RESPONSES.index(b))) / span


SEMICONDUCTOR_SPECIALIST: Final = SpecialistRole(
    role_id="sp.specialist.semiconductor_device",
    domain=DOMAIN,
    description="PN-junction device physics: depletion, doping, contact and access resistance",
    prompt_id="prm:sp.specialist.semiconductor_device",
    prompt_version="1.0.0",
    prompt_template=(
        "You are the semiconductor-device specialist. From ONLY the evidence given, state which "
        "of the hypotheses under consideration the device physics favours and why."
    ),
    evidence_domains=(DOMAIN,),
    focus_terms=("contact", "doping", "junction", "depletion", "access"),
)

NUMERICS_SPECIALIST: Final = SpecialistRole(
    role_id="sp.specialist.simulation_numerics",
    domain=DOMAIN,
    description="Solver numerics: mesh resolution, convergence and normalization artefacts",
    prompt_id="prm:sp.specialist.simulation_numerics",
    prompt_version="1.0.0",
    prompt_template=(
        "You are the simulation-numerics specialist. From ONLY the evidence given, state whether "
        "the anomaly could be a numerical artefact and which hypotheses that favours."
    ),
    evidence_domains=(DOMAIN,),
    focus_terms=("mesh", "convergence", "solver", "normalization", "refinement"),
)


__all__ = [
    "NUMERICS_SPECIALIST",
    "RS_FALLS",
    "RS_INSENSITIVE",
    "RS_RESPONSES",
    "RS_RESPONSE_METRIC_ID",
    "RS_RESPONSE_METRIC_VERSION",
    "RS_RESPONSE_OBSERVABLE",
    "RS_RESPONSE_SPACE_ID",
    "RS_RESPONSE_SPACE_VERSION",
    "RS_RISES",
    "SEMICONDUCTOR_SPECIALIST",
    "RsResponseRankDistance",
    "rs_response_space",
]
