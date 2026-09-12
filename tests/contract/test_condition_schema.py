"""T-EVI-005 — versioned condition schemas (EVI-005).

Pass condition (§26): 錯誤 condition schema version/write 被拒絕；ConditionMatch 回傳受版本控制。

Two halves. A write whose declared schema version is malformed, unregistered, or whose condition
keys do not conform is rejected at the boundary. And a ConditionMatch is attributable to the
comparator version that produced it, so a belief transition authorised under one set of tolerance
rules stays explainable after those rules change.

The comparator below belongs to a fictional ``toy`` domain. Core tests must not import the
Silicon Photonics DomainPack -- it does not exist until M2, and depending on it here would be the
core-to-domain coupling §24.2 forbids.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from pydantic import ValidationError

from lab_brain.core.models import (
    ConditionMatch,
    ConditionMatchState,
    ConditionMismatch,
    ConditionSchemaError,
    ConditionSchemaRef,
    ConditionSchemaRegistration,
    Observation,
)
from lab_brain.core.repositories import (
    InMemoryAttestationRepository,
    InMemoryObservationRepository,
)
from lab_brain.evidence import ConditionSchemaRegistry
from tests.conftest_fixtures import (
    TOY_COMPARATOR_VERSION,
    TOY_SCHEMA,
    TOY_SCHEMA_REF,
    TOY_SCHEMA_V2,
    make_attestation,
    make_observation,
    registry_with_toy_schema,
)


class ToyComparator:
    """A deliberately simple domain comparator.

    Exact match on ``setting``; ``level`` within tolerance counts as COMPATIBLE. Reports UNKNOWN
    when a field is absent on either side rather than assuming equality -- the distinction
    ConditionMatchState keeps separate so escalation remains possible.
    """

    version = TOY_COMPARATOR_VERSION

    def __init__(self, tolerance: float = 0.5) -> None:
        self.tolerance = tolerance

    def compare(
        self,
        left: Mapping[str, Any],
        right: Mapping[str, Any],
        schema: ConditionSchemaRegistration,
    ) -> ConditionMatch:
        matched: list[str] = []
        mismatches: list[ConditionMismatch] = []
        unknowns: list[str] = []

        for field in sorted(schema.known_fields):
            if field not in left or field not in right:
                unknowns.append(field)
                continue
            left_value, right_value = left[field], right[field]
            if left_value == right_value or (
                field == "level" and abs(float(left_value) - float(right_value)) <= self.tolerance
            ):
                matched.append(field)
            else:
                mismatches.append(
                    ConditionMismatch(
                        field=field,
                        left=left_value,
                        right=right_value,
                        reason="values differ beyond tolerance",
                    )
                )

        if mismatches:
            state = ConditionMatchState.INCOMPATIBLE
        elif unknowns:
            state = ConditionMatchState.UNKNOWN
        else:
            state = ConditionMatchState.EXACT

        return ConditionMatch(
            state=state,
            matched_fields=tuple(matched),
            mismatches=tuple(mismatches),
            unknowns=tuple(unknowns),
            tolerance_policy_version=self.version,
            schema_ref=schema.ref,
        )


class LyingComparator(ToyComparator):
    """Declares c1 but stamps its matches with a different version.

    Registered as the *sole* comparator in its own registry below. Since P2-fix,
    ``register_comparator`` rejects two implementations sharing one declared version, so this
    cannot simply be layered over ``ToyComparator``.
    """

    def compare(self, left, right, schema):  # type: ignore[no-untyped-def]
        match = super().compare(left, right, schema)
        return match.model_copy(update={"tolerance_policy_version": "not-my-version"})


@pytest.fixture
def registry() -> ConditionSchemaRegistry:
    reg = registry_with_toy_schema()
    reg.register_comparator("toy", "basic", ToyComparator())
    return reg


# ---------------------------------------------------------------------------
# Malformed and unregistered versions
# ---------------------------------------------------------------------------


@pytest.mark.requirement("EVI-005")
@pytest.mark.spec_test("T-EVI-005")
@pytest.mark.parametrize(
    "malformed",
    [
        "1.0.0",  # no domain or schema id
        "toy/basic",  # no version
        "toy@1.0.0",  # no schema id
        "toy/basic@1.0",  # not semver
        "Toy/Basic@1.0.0",  # uppercase
        "",
    ],
)
def test_malformed_schema_reference_is_rejected(malformed):
    with pytest.raises(ConditionSchemaError):
        ConditionSchemaRef.parse(malformed)


@pytest.mark.requirement("EVI-005")
@pytest.mark.spec_test("T-EVI-005")
def test_unregistered_schema_version_is_rejected(registry):
    """An unregistered version means nobody can later say what those keys meant."""
    with pytest.raises(ConditionSchemaError, match="not registered"):
        registry.validate({"setting": "nominal"}, "toy/basic@9.9.9")


@pytest.mark.requirement("EVI-005")
@pytest.mark.spec_test("T-EVI-005")
def test_a_registered_version_does_not_admit_its_siblings(registry):
    """Registering 1.0.0 must not implicitly accept 2.0.0.

    Versions are separate contracts; 2.0.0 here requires a field 1.0.0 does not.
    """
    assert registry.is_registered(TOY_SCHEMA_REF)
    assert not registry.is_registered("toy/basic@2.0.0")

    registry.register_schema(TOY_SCHEMA_V2)
    assert registry.versions_of("toy", "basic") == ("1.0.0", "2.0.0")
    # v2 requires `level`; the v1-shaped payload is invalid against it.
    with pytest.raises(ConditionSchemaError, match="missing required"):
        registry.validate({"setting": "nominal"}, "toy/basic@2.0.0")


@pytest.mark.requirement("EVI-005")
@pytest.mark.spec_test("T-EVI-005")
def test_schema_versions_are_immutable(registry):
    """Redefining a registered version would reinterpret every record written against it."""
    altered = TOY_SCHEMA.model_copy(update={"comparator_version": "something-else"})
    with pytest.raises(ConditionSchemaError, match="immutable"):
        registry.register_schema(altered)
    # Re-registering byte-identical content is a harmless no-op.
    registry.register_schema(TOY_SCHEMA)


# ---------------------------------------------------------------------------
# Non-conforming condition payloads
# ---------------------------------------------------------------------------


@pytest.mark.requirement("EVI-005")
@pytest.mark.spec_test("T-EVI-005")
def test_missing_required_condition_field_is_rejected(registry):
    with pytest.raises(ConditionSchemaError, match="missing required fields"):
        registry.validate({"level": 1.0}, TOY_SCHEMA_REF)


@pytest.mark.requirement("EVI-005")
@pytest.mark.spec_test("T-EVI-005")
def test_undeclared_condition_field_is_rejected(registry):
    """A misspelled key that is silently dropped yields a record that looks complete.

    Condition-aware retrieval would then treat it as comparable when it is not.
    """
    with pytest.raises(ConditionSchemaError, match="not declared"):
        registry.validate({"setting": "nominal", "levle": 1.0}, TOY_SCHEMA_REF)


@pytest.mark.requirement("EVI-005")
@pytest.mark.spec_test("T-EVI-005")
def test_conforming_conditions_are_accepted(registry):
    schema = registry.validate({"setting": "nominal", "level": 1.0}, TOY_SCHEMA_REF)
    assert schema.ref == ConditionSchemaRef.parse(TOY_SCHEMA_REF)


# ---------------------------------------------------------------------------
# Write-time enforcement (EVI-005 is a write gate, not a read-time check)
# ---------------------------------------------------------------------------


@pytest.mark.requirement("EVI-005")
@pytest.mark.spec_test("T-EVI-005")
def test_observation_write_validates_its_condition_schema(registry):
    """Validating on read would let unauditable records accumulate silently."""
    repository = InMemoryObservationRepository(registry)

    good = make_observation(conditions={"setting": "nominal", "level": 2.0})
    assert repository.add(good).observation_id == good.observation_id

    with pytest.raises(ConditionSchemaError, match="not declared"):
        repository.add(make_observation(conditions={"setting": "x", "bogus": 1}))

    with pytest.raises(ConditionSchemaError, match="missing required"):
        repository.add(make_observation(conditions={}))


@pytest.mark.requirement("EVI-005")
@pytest.mark.spec_test("T-EVI-005")
def test_attestation_write_validates_its_condition_schema(registry):
    repository = InMemoryAttestationRepository(registry)

    good = make_attestation(conditions={"setting": "nominal"})
    assert repository.add(good).attestation_id == good.attestation_id

    with pytest.raises(ConditionSchemaError, match="not registered"):
        repository.add(make_attestation(conditions_schema_version="toy/basic@7.0.0"))


@pytest.mark.requirement("EVI-005")
@pytest.mark.spec_test("T-EVI-005")
def test_condition_schema_version_is_mandatory_on_condition_aware_records():
    with pytest.raises(ValueError, match="conditions_schema_version"):
        Observation(  # type: ignore[call-arg]
            artifact_id="art:sha256:" + "0" * 64,
            metric_or_event="toy_metric",
            method_ref="toy@1.0.0",
            project_id="prj:test",
        )


@pytest.mark.requirement("EVI-005")
@pytest.mark.spec_test("T-EVI-005")
def test_malformed_schema_version_is_rejected_at_model_construction():
    """Rejected at the boundary, not left to surface as an unresolvable lookup later.

    Pydantic wraps an exception raised inside a model validator in ``ValidationError``, so the
    ``ConditionSchemaError`` type does not survive model construction -- only its message does.
    It does propagate unwrapped from ``ConditionSchemaRegistry.validate``, which is where callers
    branch on it.
    """
    with pytest.raises(ValidationError, match="condition schema reference must be"):
        make_observation(conditions_schema_version="not-a-reference")


# ---------------------------------------------------------------------------
# ConditionMatch is version-controlled
# ---------------------------------------------------------------------------


@pytest.mark.requirement("EVI-005")
@pytest.mark.spec_test("T-EVI-005")
def test_condition_match_records_the_comparator_version(registry):
    match = registry.compare(
        {"setting": "nominal", "level": 1.0},
        {"setting": "nominal", "level": 1.2},
        TOY_SCHEMA_REF,
    )
    assert match.tolerance_policy_version == TOY_COMPARATOR_VERSION
    assert match.schema_ref == ConditionSchemaRef.parse(TOY_SCHEMA_REF)
    # 1.0 vs 1.2 is inside the toy tolerance, so both fields matched.
    assert match.state is ConditionMatchState.EXACT
    assert set(match.matched_fields) == {"setting", "level"}


@pytest.mark.requirement("EVI-005")
@pytest.mark.spec_test("T-EVI-005")
def test_comparator_must_not_misreport_its_own_version():
    """A ConditionMatch that cannot be attributed to real rules is not reproducible."""
    lying = registry_with_toy_schema()
    lying.register_comparator("toy", "basic", LyingComparator())
    with pytest.raises(ConditionSchemaError, match="tolerance_policy_version"):
        lying.compare(
            {"setting": "nominal", "level": 1.0},
            {"setting": "nominal", "level": 1.0},
            TOY_SCHEMA_REF,
        )


@pytest.mark.requirement("EVI-005")
@pytest.mark.spec_test("T-EVI-005")
def test_incompatible_conditions_are_reported_as_such(registry):
    match = registry.compare(
        {"setting": "nominal", "level": 1.0},
        {"setting": "stressed", "level": 1.0},
        TOY_SCHEMA_REF,
    )
    assert match.state is ConditionMatchState.INCOMPATIBLE
    assert not match.is_comparable
    assert [m.field for m in match.mismatches] == ["setting"]


@pytest.mark.requirement("EVI-005")
@pytest.mark.spec_test("T-EVI-005")
def test_absent_field_yields_unknown_not_incompatible(registry):
    """P4 / §6.8: "cannot tell" must stay distinguishable from "not comparable"."""
    match = registry.compare(
        {"setting": "nominal", "level": 1.0}, {"setting": "nominal"}, TOY_SCHEMA_REF
    )
    assert match.state is ConditionMatchState.UNKNOWN
    assert match.unknowns == ("level",)
    assert not match.is_comparable


@pytest.mark.requirement("EVI-005")
@pytest.mark.spec_test("T-EVI-005")
def test_comparison_validates_both_sides_before_comparing(registry):
    """A match computed from unvalidated input would look authoritative and not be."""
    with pytest.raises(ConditionSchemaError, match="not declared"):
        registry.compare({"setting": "nominal"}, {"setting": "nominal", "junk": 1}, TOY_SCHEMA_REF)


@pytest.mark.requirement("EVI-005")
@pytest.mark.spec_test("T-EVI-005")
def test_core_does_not_define_comparison_semantics():
    """§24.1: without a registered domain comparator, core refuses rather than guessing."""
    bare = registry_with_toy_schema()
    with pytest.raises(ConditionSchemaError, match="no comparator registered"):
        bare.compare({"setting": "a"}, {"setting": "a"}, TOY_SCHEMA_REF)


@pytest.mark.requirement("EVI-005")
@pytest.mark.spec_test("T-EVI-005")
def test_condition_match_state_cannot_contradict_its_findings():
    """A comparator bug reporting EXACT alongside mismatches must not be storable."""
    ref = ConditionSchemaRef.parse(TOY_SCHEMA_REF)
    with pytest.raises(ValueError, match="EXACT contradicts"):
        ConditionMatch(
            state=ConditionMatchState.EXACT,
            tolerance_policy_version=TOY_COMPARATOR_VERSION,
            schema_ref=ref,
            mismatches=(ConditionMismatch(field="setting", left="a", right="b", reason="differs"),),
        )
    with pytest.raises(ValueError, match="INCOMPATIBLE requires"):
        ConditionMatch(
            state=ConditionMatchState.INCOMPATIBLE,
            tolerance_policy_version=TOY_COMPARATOR_VERSION,
            schema_ref=ref,
        )
