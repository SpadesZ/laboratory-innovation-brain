"""Localized predictive checks: a deviation confined to one experiment is not diluted away.

v1.0's adequacy is a global chi-square (p >= 0.01) plus a 4-sigma bound on every entry. A
hypothesis that is wrong in ONE experiment by about 3 sigma on each of its entries passes both: the
experiment's share of the global sum is spread over every other residual's degrees of freedom, and
no single entry reaches 4 sigma. v1.1 adds, per DISTINCT experiment, the chi-square of that
experiment's standardised residuals under the global fit (k = entries x replicates), and tests the
family with Holm's step-down procedure at `alpha_localized` (declared in `SafetyProtocolV11`).

A toy catalog keeps every number checkable by hand: ten experiments of two unit-sigma entries, one
mechanism with a fixed amplitude predicting 1.0 on every entry.
"""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from lab_brain.discovery.model import (
    EntrySpec,
    ExperimentSpec,
    MechanismClass,
    MechanismKind,
    Observation,
    Tier,
    make_hypothesis,
)
from lab_brain.discovery.numerics import chi2_sf
from lab_brain.discovery_safety.gate import adequacy_test
from lab_brain.discovery_safety.model import SAFETY
from lab_brain.discovery_safety.v11.gate import adequacy_test_v11, localized_checks
from lab_brain.discovery_safety.v11.model import HOLM, SAFETY_V11, SafetyProtocolV11

EXPERIMENTS = {
    f"e{i}": ExperimentSpec(
        f"e{i}", "two readings", 1, (EntrySpec("a", "u", 1.0), EntrySpec("b", "u", 1.0))
    )
    for i in range(10)
}
MECHANISM = MechanismClass(
    class_id="toy.flat",
    family="toy",
    mechanism="toy",
    regime="fixed",
    statement="predicts 1.0 on every entry",
    kind=MechanismKind.PHYSICAL,
    tier=Tier.INITIAL,
    parameter="a",
    lower=1.0,
    upper=1.0 + 1e-9,
    sensitivity=tuple((e, n, 1.0) for e in EXPERIMENTS for n in ("a", "b")),
    prior=0.5,
)
H = make_hypothesis(MECHANISM)


def observations(deviations: dict[str, tuple[float, float]]) -> list[Observation]:
    """One observation per experiment: the prediction (1.0) plus the given deviations."""
    out = []
    for i, experiment_id in enumerate(EXPERIMENTS):
        da, db = deviations.get(experiment_id, (0.0, 0.0))
        out.append(
            Observation(
                observation_id=f"obs:{i + 1}",
                experiment_id=experiment_id,
                replicate=0,
                taken_at=i + 1,
                values=(("a", 1.0 + da), ("b", 1.0 + db)),
            )
        )
    return out


#: Two entries of one experiment 2.9 sigma off: global p ~ 0.6, max |z| 2.9 < 4.
LOCAL = observations({"e3": (2.9, 2.9)})


def test_the_protocol_declares_the_check_and_its_level_before_any_evaluation():
    assert SAFETY_V11.version == "1.1.0"
    assert SAFETY_V11.localized_check and SAFETY_V11.refit_fixpoint
    assert SAFETY_V11.alpha_localized == 0.01 and SAFETY_V11.localized_correction == HOLM
    # v1.0's thresholds are kept exactly.
    for name in ("alpha_adequacy", "z_adequacy", "z_signal", "signal_coverage"):
        assert getattr(SAFETY_V11, name) == getattr(SAFETY, name)
    assert SAFETY_V11.digest != SAFETY.digest
    assert replace(SAFETY_V11, alpha_localized=0.05).digest != SAFETY_V11.digest
    with pytest.raises(ValueError):
        SafetyProtocolV11(alpha_localized=0.0)
    with pytest.raises(ValueError):
        SafetyProtocolV11(localized_correction="none")


def test_v10_misses_a_deviation_confined_to_one_experiment():
    t = adequacy_test(H, LOCAL, EXPERIMENTS, SAFETY)
    assert t.adequate
    assert t.p_value > 0.5 and t.worst_z == pytest.approx(2.9)


def test_v11_rejects_it_and_names_the_experiment_and_its_worst_observation():
    t = adequacy_test_v11(H, LOCAL, EXPERIMENTS, SAFETY_V11)
    assert t.global_adequate and not t.adequate
    assert t.localized_failed == ("e3",)
    e3 = next(c for c in t.localized if c.experiment_id == "e3")
    assert e3.k == 2 and e3.chi2 == pytest.approx(2 * 2.9**2)
    assert e3.p_value == pytest.approx(math.exp(-(2.9**2)), rel=1e-6)  # chi2(2) tail
    assert e3.level == pytest.approx(0.01 / 10)  # rank 1 of 10: Holm's first level
    assert t.worst_observation == "obs:4" and t.worst_z == pytest.approx(2.9)


def test_with_the_check_disabled_v11_reduces_to_v10():
    off = replace(SAFETY_V11, localized_check=False)
    t = adequacy_test_v11(H, LOCAL, EXPERIMENTS, off)
    assert t.adequate and t.localized == () and t.localized_failed == ()


def test_holm_is_step_down_and_stops_at_the_first_acceptance():
    # e1: chi2(2) tail at 2.9 sigma per entry ~ 2.2e-4 (< 0.01/10); e2: 2.6 sigma ~ 1.2e-3,
    # second level 0.01/9 = 1.1e-3 -> NOT rejected, so e5 (larger p) is not rejected either even
    # though it would pass a level it is never compared with.
    obs = observations({"e1": (2.9, 2.9), "e2": (2.6, 2.6), "e5": (2.5, 2.5)})
    checks = {c.experiment_id: c for c in localized_checks(H, obs, EXPERIMENTS, 0.01)}
    assert checks["e1"].rejected and checks["e1"].level == pytest.approx(0.001)
    assert not checks["e2"].rejected and checks["e2"].level == pytest.approx(0.01 / 9)
    assert not checks["e5"].rejected
    assert checks["e2"].p_value == pytest.approx(chi2_sf(2 * 2.6**2, 2))
    assert sum(c.rejected for c in checks.values()) == 1


def test_noise_spread_over_every_experiment_is_not_rejected():
    spread = observations(
        {f"e{i}": ((-1) ** i * 1.2, (-1) ** (i + 1) * 0.9) for i in range(len(EXPERIMENTS))}
    )
    t = adequacy_test_v11(H, spread, EXPERIMENTS, SAFETY_V11)
    assert t.adequate and not t.localized_failed


def test_replicates_of_one_experiment_are_pooled_into_one_check():
    obs = [*LOCAL, replace(LOCAL[3], observation_id="obs:11", replicate=1, taken_at=11)]
    checks = {c.experiment_id: c for c in localized_checks(H, obs, EXPERIMENTS, 0.01)}
    assert checks["e3"].observations == ("obs:4", "obs:11") and checks["e3"].k == 4
    assert len(checks) == len(EXPERIMENTS)


def test_a_global_failure_keeps_v10s_worst_observation():
    obs = observations({"e7": (6.0, 0.0)})
    base = adequacy_test(H, obs, EXPERIMENTS, SAFETY)
    t = adequacy_test_v11(H, obs, EXPERIMENTS, SAFETY_V11)
    assert not base.adequate and not t.adequate and not t.global_adequate
    assert (t.worst_observation, t.worst_z) == (base.worst_observation, base.worst_z)
