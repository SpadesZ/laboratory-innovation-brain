"""Prospective registration: a prediction is hashed into an evaluator-owned ledger BEFORE its data.

THE LEDGER belongs to the laboratory side (the evaluator builds it and wraps the laboratory with
it), never to the arm. It is an append-only sequence of two kinds of event:

    REGISTER   the arm hands over a canonical JSON payload (a prediction for one future run of one
               experiment, with the pre-declared rule it is to be scored by); the ledger stores the
               payload and its SHA-256 and returns the event's index
    MEASURE    the laboratory ran experiment E (its replicate k) and returned these values --
               written by the laboratory wrapper itself, so an arm cannot write one without paying
               for a run

A registration is PROSPECTIVE for a measurement iff its index is smaller than the measurement's
index and it names that experiment and replicate. Re-scoring needs nothing from the arm: the
evaluator recomputes the hash, finds the measurement, and applies `score_prediction` (the same
pre-declared rule the payload names) to the registered prediction and the measured values.

THE RULE (pre-declared, `PredictionRule`): per entry the standardised residual
z = (observed - predicted) / sqrt(sigma^2 + sd^2), where sd is the prediction's own standard
deviation (the fitted amplitudes' uncertainty propagated through the forward model). PASS iff the
chi-square of the z over the experiment's entries has an upper-tail p-value of at least `alpha`
AND no |z| exceeds `z_max`. RISKY iff the predicted values are separated from at least one
registered ALTERNATIVE prediction (the zero prediction "nothing here", a rival's prediction) by at
least `tau_risky` in the same combined units: a test the prediction could have failed.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from lab_brain.discovery.model import ExperimentSpec
from lab_brain.discovery.numerics import chi2_sf

REGISTER = "REGISTER"
MEASURE = "MEASURE"

Values = tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class PredictionRule:
    """The pre-declared scoring rule a registration names (hashed into the payload)."""

    alpha: float = 1e-2
    z_max: float = 4.0
    tau_risky: float = 3.0

    def as_json(self) -> dict[str, float]:
        return {"alpha": self.alpha, "z_max": self.z_max, "tau_risky": self.tau_risky}


def canonical(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def payload_digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LedgerEvent:
    index: int
    kind: str
    #: REGISTER: the canonical payload text and its digest. MEASURE: experiment, replicate, values.
    text: str = ""
    digest: str = ""
    experiment_id: str = ""
    replicate: int = -1
    values: Values = ()


@dataclass
class PredictionLedger:
    """Append-only; written by the laboratory wrapper (MEASURE) and by `register` (REGISTER)."""

    events: list[LedgerEvent] = field(default_factory=list)

    def register(self, text: str) -> int:
        json.loads(text)  # a registration is a JSON document, or it is refused
        event = LedgerEvent(len(self.events), REGISTER, text=text, digest=payload_digest(text))
        self.events.append(event)
        return event.index

    def record_measurement(self, experiment_id: str, replicate: int, values: Values) -> int:
        event = LedgerEvent(
            len(self.events),
            MEASURE,
            experiment_id=experiment_id,
            replicate=replicate,
            values=values,
        )
        self.events.append(event)
        return event.index

    def registrations(self) -> list[tuple[LedgerEvent, dict[str, Any]]]:
        return [(e, json.loads(e.text)) for e in self.events if e.kind == REGISTER]

    def measurement(self, experiment_id: str, replicate: int) -> LedgerEvent | None:
        return next(
            (
                e
                for e in self.events
                if e.kind == MEASURE
                and e.experiment_id == experiment_id
                and e.replicate == replicate
            ),
            None,
        )


def prediction_payload(
    *,
    subject: str,
    fingerprint: str,
    experiment_id: str,
    replicate: int,
    predicted: Mapping[str, float],
    sd: Mapping[str, float],
    alternatives: Sequence[tuple[str, Mapping[str, float], Mapping[str, float]]],
    rule: PredictionRule,
    purpose: str,
) -> str:
    """The canonical text of one registration (floats as fixed 9-decimal strings)."""

    def num(x: float) -> str:
        return format(round(x, 9), ".9f")

    return canonical(
        {
            "kind": "lab-brain/discovery-prospective-prediction@1",
            "subject": subject,
            "fingerprint": fingerprint,
            "experiment_id": experiment_id,
            "replicate": replicate,
            "predicted": {k: num(v) for k, v in sorted(predicted.items())},
            "sd": {k: num(v) for k, v in sorted(sd.items())},
            "alternatives": [
                {
                    "label": label,
                    "predicted": {k: num(v) for k, v in sorted(p.items())},
                    "sd": {k: num(v) for k, v in sorted(s.items())},
                }
                for label, p, s in alternatives
            ],
            "rule": rule.as_json(),
            "purpose": purpose,
        }
    )


@dataclass(frozen=True)
class Score:
    passed: bool
    risky: bool
    p_value: float
    max_abs_z: float
    #: Largest separation of the prediction from a registered alternative (combined units).
    risk_separation: float


def _floats(table: Mapping[str, Any]) -> dict[str, float]:
    return {k: float(v) for k, v in table.items()}


def score_prediction(
    payload: Mapping[str, Any], values: Values, experiment: ExperimentSpec
) -> Score:
    """Apply the payload's own rule to the measured values (what the evaluator re-derives)."""
    rule = payload["rule"]
    predicted = _floats(payload["predicted"])
    sd = _floats(payload["sd"])
    observed = dict(values)
    chi2 = 0.0
    worst = 0.0
    for entry in experiment.entries:
        scale = math.sqrt(entry.sigma**2 + sd.get(entry.entry_id, 0.0) ** 2)
        z = (observed[entry.entry_id] - predicted.get(entry.entry_id, 0.0)) / scale
        chi2 += z * z
        worst = max(worst, abs(z))
    p = chi2_sf(chi2, len(experiment.entries))
    separation = 0.0
    for alternative in payload["alternatives"]:
        other = _floats(alternative["predicted"])
        other_sd = _floats(alternative["sd"])
        d2 = 0.0
        for entry in experiment.entries:
            scale2 = (
                entry.sigma**2
                + sd.get(entry.entry_id, 0.0) ** 2
                + other_sd.get(entry.entry_id, 0.0) ** 2
            )
            d = predicted.get(entry.entry_id, 0.0) - other.get(entry.entry_id, 0.0)
            d2 += d * d / scale2
        separation = max(separation, math.sqrt(d2))
    return Score(
        passed=p >= float(rule["alpha"]) and worst <= float(rule["z_max"]),
        risky=separation >= float(rule["tau_risky"]),
        p_value=p,
        max_abs_z=worst,
        risk_separation=separation,
    )


@dataclass(frozen=True)
class RescoredTest:
    """One registration, re-derived from the ledger alone."""

    register_index: int
    measure_index: int | None
    subject: str
    fingerprint: str
    experiment_id: str
    replicate: int
    purpose: str
    prospective: bool
    passed: bool
    risky: bool
    p_value: float
    max_abs_z: float


def rescore(
    ledger: PredictionLedger, experiments: Mapping[str, ExperimentSpec]
) -> list[RescoredTest]:
    """Every registration in the ledger, scored against the measurement it names (if any)."""
    out = []
    for event, payload in ledger.registrations():
        if payload_digest(event.text) != event.digest:
            raise ValueError(f"registration {event.index} does not match its digest")
        experiment_id = str(payload["experiment_id"])
        replicate = int(payload["replicate"])
        measured = ledger.measurement(experiment_id, replicate)
        prospective = measured is not None and measured.index > event.index
        if measured is None:
            out.append(
                RescoredTest(
                    event.index,
                    None,
                    str(payload["subject"]),
                    str(payload["fingerprint"]),
                    experiment_id,
                    replicate,
                    str(payload["purpose"]),
                    False,
                    False,
                    False,
                    0.0,
                    0.0,
                )
            )
            continue
        s = score_prediction(payload, measured.values, experiments[experiment_id])
        out.append(
            RescoredTest(
                event.index,
                measured.index,
                str(payload["subject"]),
                str(payload["fingerprint"]),
                experiment_id,
                replicate,
                str(payload["purpose"]),
                prospective,
                s.passed,
                s.risky,
                s.p_value,
                s.max_abs_z,
            )
        )
    return out


def holm_rejections(p_values: Sequence[float], alpha: float) -> list[bool]:
    """Holm's step-down over a family of p-values at family-wise level alpha."""
    m = len(p_values)
    order = sorted(range(m), key=lambda i: (p_values[i], i))
    rejected = [False] * m
    for rank, i in enumerate(order):
        if p_values[i] < alpha / (m - rank):
            rejected[i] = True
        else:
            break
    return rejected


def supported(tests: Sequence[RescoredTest], fingerprint: str, alpha: float) -> bool:
    """The evaluator's evidential rule for one mechanism (by forward-model fingerprint):

    SUPPORTED iff (1) at least one prospective, risky registration of it passed, and (2) the family
    of ALL its prospective registrations, tested with Holm's step-down at family-wise level
    `alpha`, rejects none (alpha spending over repeated predictive tests: the family-wise false-
    alarm rate stays at `alpha` however many tests were registered). A registration whose data
    never arrived counts for nothing."""
    mine = [t for t in tests if t.fingerprint == fingerprint and t.prospective]
    if not any(t.passed and t.risky for t in mine):
        return False
    return not any(holm_rejections([t.p_value for t in mine], alpha))


__all__ = [
    "MEASURE",
    "REGISTER",
    "LedgerEvent",
    "PredictionLedger",
    "PredictionRule",
    "RescoredTest",
    "Score",
    "canonical",
    "holm_rejections",
    "payload_digest",
    "prediction_payload",
    "rescore",
    "score_prediction",
    "supported",
]
