"""A deterministic STAND-IN for the Hypothesis Engine, shaped like the recorded live Gemini runs.

NOT A LANGUAGE MODEL, NOT A G0 RESULT. It answers the Hypothesis Engine's prompts (Stage A, the
coverage review, the screening review) through `FakeProvider.rewrite`, so the research pipeline,
its gates and its records can be exercised end to end without a model, a credential or a cost.
Every other role is answered by the fake provider's catalog reading, unchanged. Whatever this
stand-in "concludes" is a property of the rules below, declared before any evaluation ran -- it
measures what the PLATFORM does with such replies, never what a real model would reply.

THE RULES, AND WHAT THEY READ. Only the CONTEXT block of each prompt: the evidence texts, the
prediction bindings, the hypotheses shown, the screening readings shown and -- when the deployment
enables it -- the device structure summary. Never a fixture, a case id, a benchmark label or an
evaluator file; `reads` records every context it was given so a test can prove that.

    Stage A          one rival per observable the evidence CUES (the words below), the way the live
                     runs proposed contact resistance, uncorrected extraction, mesh, probe and
                     compensation but nothing about contact connectivity; padded with a second
                     impedance-only rival to reach the minimum. With `structure_reading`, it also
                     proposes a rival for each design field a reader would flag (a via not drawn
                     to metal; an overlap under half of the device's largest; an extraction length
                     more than 10% from the drawn length) -- from the summary only
    coverage review  declines every gap: "the evidence does not point there" -- the recorded
                     live behaviour
    Critic           the fake provider's catalog critique, with no alternative mechanisms named --
                     the recorded live critic named none for the open-via cases (opt in with
                     `critic_alternatives`)
    screening review for each ABNORMAL reading, one rival worded by the stand-in that accounts for
                     it, grounded on the evidence that shares words with it; declines a reading no
                     shown evidence shares a word with
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from lab_brain.cognition.roles import (
    ADVERSARIAL_CRITIC,
    COVERAGE_REVIEW,
    HYPOTHESIS_ENGINE,
    SCREENING_REVIEW,
)

MARKER = "\n\nCONTEXT:\n"

#: observable -> (words in the evidence that make a reader propose a mechanism there, the
#: stand-in's mechanism wording, its statement). Declared for the stand-in; not the pack's catalog.
CUES: dict[str, tuple[tuple[str, ...], str, str]] = {
    "sp.probe_contact_resistance": (
        ("probe station", "re-measure", "instrumentation"),
        "probe contact resistance during the two-point measurement (stand-in wording)",
        "The probe contact adds a series resistance to the measured Rs.",
    ),
    "sp.mesh_stability": (
        ("mesh",),
        "simulation mesh artefact in the access region (stand-in wording)",
        "A coarse access-region mesh distorts the simulated series resistance comparison.",
    ),
    "sp.carrier_profile": (
        ("doping", "implant"),
        "doping profile difference between splits (stand-in wording)",
        "A doping difference changes the access-region resistance between splits.",
    ),
    "sp.normalization_basis": (
        ("normalization", "normalisation", "per-length basis"),
        "extraction length basis error (stand-in wording)",
        "The extraction divides by the wrong device length, scaling the series resistance.",
    ),
    "sp.contact_connectivity": (
        ("open via", "disconnected contact", "not tied to metal"),
        "open contact access path (stand-in wording)",
        "A contact is not tied to metal, so the series resistance access current is cut.",
    ),
    "sp.small_signal_impedance": (
        ("contact resistance", "contact-resistance", "uncorrected"),
        "uncorrected contact resistance term in the extraction (stand-in wording)",
        "The series resistance contains an uncorrected contact resistance term.",
    ),
}
#: A second impedance-only rival, so Stage A reaches the minimum the way the live runs did.
PADDING = (
    "process-dependent contact resistance between splits (stand-in wording)",
    "A process step raised the contact resistance of one split's series resistance.",
)
#: The stand-in's wording for a rival that accounts for an abnormal reading of an observable.
SCREENING_WORDING: dict[str, tuple[str, str]] = {
    "sp.contact_connectivity": (
        "broken contact via in the access path (stand-in, after screening)",
        "A contact via does not reach metal, cutting the access path and raising the series "
        "resistance while the junction capacitance is unaffected.",
    ),
    "sp.normalization_basis": (
        "wrong extraction length basis (stand-in, after screening)",
        "The extraction divides the series resistance by a length other than the drawn device "
        "length, scaling the per-length value.",
    ),
}


def context(prompt: str) -> dict[str, Any]:
    return dict(json.loads(prompt.split(MARKER, 1)[1]))


def _words(text: str) -> set[str]:
    return {w for w in "".join(c if c.isalnum() else " " for c in text.lower()).split() if len(w) > 3}


@dataclass
class StandIn:
    structure_reading: bool = False
    critic_alternatives: bool = False
    #: Every Hypothesis Engine context the stand-in was shown, by prompt kind.
    reads: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    def rewrite(self, prompt: str, answer: str) -> str:
        if MARKER not in prompt or "PROBE:" in prompt:
            return answer
        if prompt.startswith(SCREENING_REVIEW.prompt.template):
            ctx = context(prompt)
            self.reads.append(("screening", ctx))
            return json.dumps(self._screening(ctx))
        if prompt.startswith(COVERAGE_REVIEW.prompt.template):
            ctx = context(prompt)
            self.reads.append(("coverage", ctx))
            return json.dumps(
                {
                    "hypotheses": [],
                    "declined": [
                        {
                            "observable_ref": c["observable_ref"],
                            "reason": "the evidence does not point there",
                        }
                        for c in ctx["unaddressed_checks"]
                    ],
                }
            )
        if prompt.startswith(ADVERSARIAL_CRITIC.prompt.template) and not self.critic_alternatives:
            reply = json.loads(answer)
            reply["alternative_mechanisms"] = []
            return json.dumps(reply)
        if prompt.startswith(HYPOTHESIS_ENGINE.prompt.template):
            ctx = context(prompt)
            if ctx.get("alternatives_to_certify"):
                self.reads.append(("alternatives", ctx))
                return answer
            self.reads.append(("stage_a", ctx))
            return json.dumps(self._stage_a(ctx))
        return answer

    # -- Stage A ---------------------------------------------------------------------------------

    def _stage_a(self, ctx: dict[str, Any]) -> dict[str, Any]:
        corpus = " ".join(e["text"] for e in ctx["evidence"]).lower()
        bindings = {b["observable_ref"]: b for b in ctx["prediction_bindings"]}
        rivals: list[dict[str, Any]] = []
        for observable, (cues, mechanism, statement) in CUES.items():
            if observable in bindings and any(c in corpus for c in cues):
                rivals.append(self._rival(bindings[observable], mechanism, statement, len(rivals)))
        if self.structure_reading and "device_structure" in ctx:
            for observable in self._flagged(ctx["device_structure"]):
                mechanism, statement = SCREENING_WORDING[observable]
                mechanism = mechanism.replace("after screening", "from the design summary")
                if observable in bindings and all(r["mechanism"] != mechanism for r in rivals):
                    rivals.append(self._rival(bindings[observable], mechanism, statement, len(rivals)))
        impedance = bindings.get("sp.small_signal_impedance")
        while len(rivals) < int(ctx["minimum_hypotheses"]) and impedance is not None:
            n = len(rivals)
            rivals.append(self._rival(impedance, f"{PADDING[0]} {n}", PADDING[1], n))
        return {"hypotheses": rivals, "position": {"mechanism_view": "contact resistance"}}

    @staticmethod
    def _flagged(structure: dict[str, Any]) -> list[str]:
        """Observables whose design fields a reader would flag -- from the summary alone."""
        values = {e["field"]: e["value"] for e in structure["entries"]}
        flagged: list[str] = []
        vias = [v for f, v in values.items() if f.endswith("/via_to_metal")]
        overlaps = [Decimal(v) for f, v in values.items() if f.endswith("/overlap_nm")]
        if "false" in vias or (overlaps and min(overlaps) * 2 < max(overlaps)):
            flagged.append("sp.contact_connectivity")
        drawn = Decimal(values["/drawn_length_um"])
        used = Decimal(values["/extraction_normalization_length_um"])
        if drawn > 0 and abs(used - drawn) / drawn > Decimal("0.1"):
            flagged.append("sp.normalization_basis")
        return flagged

    @staticmethod
    def _rival(binding: dict[str, Any], mechanism: str, statement: str, n: int) -> dict[str, Any]:
        outcomes = binding["outcomes"]

        def prediction(key: str, outcome: str, effect: str) -> dict[str, str]:
            return {
                "key": key,
                "observable_ref": binding["observable_ref"],
                "outcome_space_id": binding["outcome_space_id"],
                "outcome_space_version": binding["outcome_space_version"],
                "expected_outcome": outcome,
                "relation_effect": effect,
            }

        supports = outcomes[-1] if binding["observable_ref"] != "sp.small_signal_impedance" else outcomes[1]
        refutes = outcomes[0]
        return {
            "key": f"h{n}",
            "statement": statement,
            "mechanism": mechanism,
            "assumptions": ["the two splits differ only in process"],
            "falsifier": f"{binding['observable_ref']} reads {refutes}",
            "falsifier_prediction_keys": ["f"],
            "confounders": ["probe contact"],
            "minimal_test_ref": binding["observable_ref"],
            "predictions": [
                prediction("s", supports, "SUPPORTS"),
                prediction("f", refutes, "CONTRADICTS"),
            ],
        }

    # -- screening review ------------------------------------------------------------------------

    def _screening(self, ctx: dict[str, Any]) -> dict[str, Any]:
        bindings = {b["observable_ref"]: b for b in ctx["prediction_bindings"]}
        taken = {" ".join(m.lower().split()) for m in ctx["existing_mechanisms"]}
        certified: list[dict[str, Any]] = []
        declined: list[dict[str, Any]] = []
        for reading in ctx["screening_observations"]:
            if reading["finding"] != "ABNORMAL":
                continue
            observable = reading["observable_ref"]
            mechanism, statement = SCREENING_WORDING.get(
                observable, (f"unexplained reading of {observable} (stand-in)", "")
            )
            grounds = [
                e["attestation_id"]
                for e in ctx["evidence"]
                if _words(e["text"]) & _words(f"{mechanism} {statement}")
            ]
            if not statement or not grounds or mechanism.lower() in taken:
                declined.append(
                    {"observation_ref": reading["observation_ref"], "reason": "no evidence fits"}
                )
                continue
            binding = bindings[observable]

            def prediction(key: str, outcome: str, effect: str) -> dict[str, str]:
                return {
                    "key": key,
                    "observable_ref": observable,
                    "outcome_space_id": binding["outcome_space_id"],
                    "outcome_space_version": binding["outcome_space_version"],
                    "expected_outcome": outcome,
                    "relation_effect": effect,
                }

            certified.append(
                {
                    "key": f"s{len(certified)}",
                    "statement": statement,
                    "mechanism": mechanism,
                    "assumptions": ["the screened reading reflects the drawn device"],
                    "falsifier": f"{observable} reads {reading['reference_outcome']}",
                    "falsifier_prediction_keys": ["f"],
                    "confounders": ["probe contact resistance"],
                    "minimal_test_ref": reading["check"],
                    "predictions": [
                        prediction("s", reading["outcome"], "SUPPORTS"),
                        prediction("f", reading["reference_outcome"], "CONTRADICTS"),
                    ],
                    "responds_to": [reading["observation_ref"]],
                    "grounding_evidence_ids": grounds[:3],
                }
            )
        return {"hypotheses": certified, "declined": declined}


__all__ = ["CUES", "MARKER", "StandIn", "context"]
