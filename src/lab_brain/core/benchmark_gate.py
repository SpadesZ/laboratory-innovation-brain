"""LLM-002's hard gates: a gate is armed only by a calibrated BenchmarkPolicy (§15.4, §17.19.2).

    LLM-002  hard gates use a versioned BenchmarkPolicy calibrated on a fixed domain benchmark
             before enforcement.
    §15.4    校準前不得任意 hard-code 門檻數字。

THERE IS NO THRESHOLD IN THIS MODULE, AND THAT IS THE WHOLE DESIGN. `evaluate_gate` takes the policy
or nothing. With nothing, it measures and reports ADVISORY -- the value is recorded, nothing is
refused -- because a gate with no calibrated threshold has no threshold, and inventing one would be
exactly the hard-coded number §15.4 forbids. `tests/unit/test_benchmark_gate.py` parses this module
and the debate-metrics module and fails if a numeric comparison appears in either.

AN ARMED GATE FAILS CLOSED ON AN UNMEASURABLE VALUE. When a calibrated policy is active and the
metric could not be computed (no inverted retrieval, so no divergence), the verdict is FAIL: the
policy says a decision needs this measurement, and "we could not measure it" does not satisfy a
requirement to have it.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from lab_brain.core.models.benchmark import BenchmarkPolicy


@dataclass(frozen=True)
class GateVerdict:
    """What one LLM-002 gate said about one value, with the policy it said it under."""

    metric_key: str
    value: Decimal | None
    #: `policy_id@version`, or `None` when no calibrated policy was active.
    policy_ref: str | None
    enforced: bool
    #: `None` when not enforced: an advisory reading neither passes nor fails anything.
    passed: bool | None
    detail: str

    @property
    def blocks(self) -> bool:
        return self.enforced and self.passed is False

    def as_record(self) -> dict[str, object]:
        return {
            "metric_key": self.metric_key,
            "value": None if self.value is None else str(self.value),
            "policy_ref": self.policy_ref,
            "enforced": self.enforced,
            "passed": self.passed,
            "detail": self.detail,
        }


def evaluate_gate(
    metric_key: str, value: Decimal | None, policy: BenchmarkPolicy | None
) -> GateVerdict:
    """Apply ``policy`` to ``value``, or report ADVISORY when there is no calibrated policy."""
    if policy is None:
        return GateVerdict(
            metric_key=metric_key,
            value=value,
            policy_ref=None,
            enforced=False,
            passed=None,
            detail=(
                f"no calibrated BenchmarkPolicy is active for {metric_key}; the value is recorded "
                "and nothing is enforced. §15.4: 校準前不得任意 hard-code 門檻數字"
            ),
        )
    if policy.metric_key != metric_key:
        raise ValueError(
            f"benchmark policy {policy.ref} calibrates {policy.metric_key}, not {metric_key}; a "
            "threshold applied to another metric is a number with no calibration behind it"
        )
    if not policy.active:
        raise ValueError(
            f"benchmark policy {policy.ref} is not active; a gate is armed by the active version "
            "only, or two thresholds would govern one decision"
        )
    if policy.direction is None:
        return GateVerdict(
            metric_key=metric_key,
            value=value,
            policy_ref=policy.ref,
            enforced=False,
            passed=None,
            detail=(
                f"benchmark policy {policy.ref} records a calibrated distribution but no "
                "direction; which side passes is undeclared, so nothing is enforced"
            ),
        )
    if value is None:
        return GateVerdict(
            metric_key=metric_key,
            value=None,
            policy_ref=policy.ref,
            enforced=True,
            passed=False,
            detail=(
                f"{metric_key} could not be measured and benchmark policy {policy.ref} requires "
                "it; "
                "an armed gate does not accept 'unmeasured' as meeting its threshold"
            ),
        )
    passed = policy.passes(value)
    return GateVerdict(
        metric_key=metric_key,
        value=value,
        policy_ref=policy.ref,
        enforced=True,
        passed=passed,
        detail=(
            f"{metric_key}={value} {'meets' if passed else 'does not meet'} {policy.ref} "
            f"({policy.direction.value} {policy.threshold}, calibrated on "
            f"{policy.benchmark_set_id} "
            f"with n={policy.sample_size})"
        ),
    )


__all__ = ["GateVerdict", "evaluate_gate"]
