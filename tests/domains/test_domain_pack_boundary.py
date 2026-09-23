"""T-DOM-SP-001 — the Rs trend rule exists only in the pack, and core starts without it.

    DOM-SP-001    Silicon photonics rule/validator 版本必須記錄；core 不得內建 Rs 趨勢規則。
    T-DOM-SP-001  Rs trend validator 只存在 Silicon Photonics DomainPack，移除 plugin 後 core
                  仍可啟動。

"CORE STILL STARTS" IS ONLY CHECKABLE IF INSTALLING IS AN ACT. A pack installed by import-time
registration into a module global makes "not installed" unreachable, and the test degrades into
asserting that an import succeeded. `DomainPackRegistry.install` is the one entrance, empty
registries are a legal state, and the test below builds the whole verification surface with nothing
installed and uses it.

THE VERSION CLAUSE IS THE ONE THAT LOOKS LIKE BOOKKEEPING AND IS NOT. A finding that cannot name
the rule version that produced it cannot be re-checked after the rule is corrected -- and §17.19.3
opens a VALIDITY_CONFLICT against `failed_rules`, so a report whose rules are unversioned opens a
conflict nobody can close.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from lab_brain.core.models.validation import ValidationStatus
from lab_brain.domains import DomainPackRegistry, DomainRegistries
from lab_brain.domains.silicon_photonics import SiliconPhotonicsPack
from lab_brain.domains.silicon_photonics.validators import (
    RULE_CJ_REVERSE_BIAS,
    RULE_RS_BIAS_STABILITY,
    RULES,
    ExpectedTrendValidator,
    TrendSample,
    TrendSubject,
)
from lab_brain.spec import repo_root
from lab_brain.verification.planner import VerificationPlanner

pytestmark = [pytest.mark.requirement("DOM-SP-001"), pytest.mark.spec_test("T-DOM-SP-001")]

VALIDATOR = ExpectedTrendValidator()


def _sweep(*rs: str, cj: tuple[str, ...] | None = None) -> TrendSubject:
    """A synthetic sweep. Bias values are round decimals and mean nothing physically."""
    biases = [Decimal(f"-{index}") for index in range(len(rs))]
    capacitances = (
        [Decimal(value) for value in cj]
        if cj is not None
        # Cj rising as bias rises towards zero, which is what the declared rule expects. The
        # ordering is what matters here, not the magnitudes.
        else [Decimal(200) - Decimal(10) * Decimal(index) for index in range(len(rs))]
    )
    return TrendSubject(
        subject_id="sweep:1",
        samples=tuple(
            TrendSample(bias_v=bias, rs_per_length=Decimal(value), cj_per_length=capacitance)
            for bias, value, capacitance in zip(biases, rs, capacitances, strict=True)
        ),
        provenance_refs=("run:1", "art:sha256:" + "aa" * 32),
    )


# ---------------------------------------------------------------------------
# The rule lives in the pack, and core does not contain it
# ---------------------------------------------------------------------------


def test_core_contains_no_rs_trend_rule():
    """DOM-SP-001's negative, read over the shipped package outside this domain directory.

    Scanned for the RULE rather than for the letters "Rs": a variable named `rs` in an unrelated
    module is not a trend rule, and a guard that tripped on it would be suppressed within a week.
    What is forbidden is the rule's identity and its threshold appearing anywhere but here.
    """
    source_root = repo_root() / "src" / "lab_brain"
    pack = source_root / "domains" / "silicon_photonics"
    needles = (RULE_RS_BIAS_STABILITY, RULE_CJ_REVERSE_BIAS, "max_rs_relative_swing")
    offenders = [
        f"{path.relative_to(repo_root()).as_posix()} ({needle})"
        for path in sorted(source_root.rglob("*.py"))
        if pack not in path.parents
        for needle in needles
        if needle in path.read_text(encoding="utf-8")
    ]
    assert not offenders, (
        f"the Rs trend rule appears outside the DomainPack: {offenders}. DOM-SP-001: core 不得"
        "內建 Rs 趨勢規則"
    )


def test_core_starts_and_plans_with_no_domain_pack_installed():
    """THE clause. Nothing installed, and the verification surface is usable.

    "Still starts" is asserted by USING the surfaces rather than by importing them: a planner that
    raised on an empty registry would be a core that needs a domain to run.
    """
    registry = DomainPackRegistry()
    assert registry.installed() == ()

    planner = VerificationPlanner(registry.registries.capabilities)
    assert planner.plan(goal=("anything",)) == ()
    assert registry.registries.validators.registered() == ()
    assert registry.registries.extractors.registered() == ()
    assert registry.registries.backend_validity.registered() == ()
    assert registry.registries.authority.registered() == ()
    assert len(registry.registries.tools) == 0


def test_installing_the_pack_is_what_makes_the_rule_reachable():
    """The positive control for the clause above: the rule arrives with the plugin and not before."""
    registries = DomainRegistries()
    assert registries.validators.registered() == ()

    SiliconPhotonicsPack(runner=lambda request: None).register_validators(  # type: ignore[arg-type]
        registries.validators
    )
    assert registries.validators.registered() == ("validate_expected_trends",)
    resolved = registries.validators.resolve("validate_expected_trends")
    assert resolved.validator_version == "1.0.0"


# ---------------------------------------------------------------------------
# The rule itself, and its version
# ---------------------------------------------------------------------------


def test_every_finding_names_its_rule_and_the_version_of_that_rule():
    """DOM-SP-001's first clause. An unversioned finding cannot be re-checked."""
    result = VALIDATOR.validate(_sweep("1000", "1010", "1005"))
    assert result.findings
    for finding in result.findings:
        assert finding.rule_id in RULES
        assert finding.rule_version == RULES[finding.rule_id]["version"]
    assert result.validator_id == "validate_expected_trends"
    assert result.validator_version == "1.0.0"


def test_a_stable_rs_sweep_passes():
    """The positive control. Without it "FAIL everything" satisfies the test below."""
    result = VALIDATOR.validate(_sweep("1000", "1010", "1005"))
    assert result.status is ValidationStatus.PASS
    assert result.failed_rules == ()


def test_an_rs_swing_beyond_the_declared_threshold_fails_and_names_the_rule():
    """§25.1's anomaly, reported as a rule violation and NOT as a diagnosis.

    The validator does not say what caused it. Naming a cause is EPI-001's competing hypotheses in
    M3, and a validator that announced a root cause would pre-empt the debate.
    """
    result = VALIDATOR.validate(_sweep("1000", "4000", "8000"))
    assert result.status is ValidationStatus.FAIL
    assert result.failed_rules == (RULE_RS_BIAS_STABILITY,)
    finding = next(f for f in result.findings if f.rule_id == RULE_RS_BIAS_STABILITY)
    assert "relative_swing" in finding.detail and "limit" in finding.detail

    # §25.1's three candidate causes -- access/contact discontinuity, mesh or convergence artefact,
    # contact/material/normalization model issue. None of them may appear: the validator reports
    # the violated rule and the measured deviation, and the mechanism is EPI-001's to argue.
    lowered = finding.message.lower()
    for mechanism in ("contact", "mesh", "convergence", "doping", "material", "model issue"):
        assert mechanism not in lowered, f"the validator diagnosed {mechanism!r}"


def test_a_cj_trend_running_the_wrong_way_fails_its_own_rule():
    result = VALIDATOR.validate(_sweep("1000", "1000", "1000", cj=("100", "150", "200")))
    assert RULE_CJ_REVERSE_BIAS in result.failed_rules
    assert result.status is ValidationStatus.FAIL


def test_a_single_point_is_unknown_rather_than_pass():
    """A value is not a trend. Reporting PASS would make an un-run check look satisfied."""
    result = VALIDATOR.validate(_sweep("1000"))
    assert result.status is ValidationStatus.UNKNOWN
    assert result.failed_rules == ()


def test_a_subject_the_validator_cannot_read_is_unknown_rather_than_fail():
    """§17.19.2 keeps UNKNOWN distinct from FAIL, and the reason is what a gate does next."""
    result = VALIDATOR.validate(object())
    assert result.status is ValidationStatus.UNKNOWN


def test_the_validator_returns_a_report_and_never_a_boolean():
    """§17.19.2's prohibition, asserted on the return type across every branch."""
    from lab_brain.core.models.validation import ValidationReport

    for subject in (_sweep("1000", "1010"), _sweep("1000", "9000"), _sweep("1000"), object()):
        assert isinstance(VALIDATOR.validate(subject), ValidationReport)


def test_a_report_whose_summary_contradicts_its_findings_cannot_be_constructed():
    """A report read one way by a gate and another way by a human is worse than no report."""
    from lab_brain.core.models.validation import ValidationFinding, ValidationReport
    from tests.refusals import refused

    with refused("contradicts its own detail"):
        ValidationReport(
            subject_type="T",
            subject_id="s",
            validator_id="v",
            validator_version="1.0.0",
            status=ValidationStatus.PASS,
            findings=(
                ValidationFinding(
                    rule_id="R",
                    rule_version="1.0.0",
                    status=ValidationStatus.FAIL,
                    message="failed",
                ),
            ),
            failed_rules=("R",),
        )


def test_failed_rules_must_agree_with_the_findings():
    """§17.19.3 opens a VALIDITY_CONFLICT against `failed_rules`; a wrong list cannot be closed."""
    from lab_brain.core.models.validation import ValidationFinding, ValidationReport
    from tests.refusals import refused

    with refused("opens a conflict nobody can close"):
        ValidationReport(
            subject_type="T",
            subject_id="s",
            validator_id="v",
            validator_version="1.0.0",
            status=ValidationStatus.FAIL,
            findings=(
                ValidationFinding(
                    rule_id="R",
                    rule_version="1.0.0",
                    status=ValidationStatus.FAIL,
                    message="failed",
                ),
            ),
            failed_rules=("SOMETHING_ELSE",),
        )


def test_the_report_carries_provenance_refs_and_not_the_values():
    """§10.2.1: a validator MUST NOT mutate raw evidence, and this one cannot even hold it."""
    result = VALIDATOR.validate(_sweep("1000", "1010"))
    assert result.provenance_refs == ("run:1", "art:sha256:" + "aa" * 32)
    assert "1000" not in str(result.provenance_refs)


def test_the_validator_holds_no_store_connection_or_gate():
    """ "MUST NOT mutate raw evidence" as a property of what it can reach, not of what it does."""
    reachable = [name for name in vars(VALIDATOR) if not name.startswith("__")]
    assert reachable == [], f"the validator holds {reachable}; it should hold nothing"
