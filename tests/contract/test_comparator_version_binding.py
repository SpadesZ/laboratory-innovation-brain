"""Regression: a schema version is compared under the comparator *it* declares (EVI-005).

The defect this file exists to prevent: the comparator registry was keyed by
``(domain, schema_id)`` alone. Two schema versions declaring different ``comparator_version``
values therefore shared whichever comparator had been registered last. Concretely — register
``toy/basic@1.0.0`` (comparator c1) and ``toy/basic@2.0.0`` (comparator c2), and v1 conditions
would be compared under c2's tolerance rules while the resulting ConditionMatch reported
``tolerance_policy_version = c1``.

That is worse than an incorrect comparison. The ConditionMatch is persisted and later read to
explain why a belief transition was authorised, so it would attribute the decision to rules that
were never applied.

Binding is now: schema registration declares ``comparator_version``, and that version selects
the comparator. Absent comparator fails closed rather than falling back to any other.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from lab_brain.core.models import (
    ConditionMatch,
    ConditionMatchState,
    ConditionMismatch,
    ConditionSchemaError,
    ConditionSchemaRegistration,
)
from lab_brain.evidence import ConditionSchemaRegistry
from tests.conftest_fixtures import (
    TOY_COMPARATOR_V2_VERSION,
    TOY_COMPARATOR_VERSION,
    TOY_SCHEMA,
    TOY_SCHEMA_REF,
    TOY_SCHEMA_V2,
)

TOY_SCHEMA_V2_REF = "toy/basic@2.0.0"


class ExactOnlyComparator:
    """c1: equality only. No tolerance at all."""

    version = TOY_COMPARATOR_VERSION

    def compare(
        self,
        left: Mapping[str, Any],
        right: Mapping[str, Any],
        schema: ConditionSchemaRegistration,
    ) -> ConditionMatch:
        return _build_match(left, right, schema, self.version, tolerance=0.0)


class TolerantComparator:
    """c2: `level` within +/- 1.0 counts as a match.

    Deliberately more permissive than c1 on the same input, so a binding error is observable
    rather than merely theoretical.
    """

    version = TOY_COMPARATOR_V2_VERSION

    def compare(
        self,
        left: Mapping[str, Any],
        right: Mapping[str, Any],
        schema: ConditionSchemaRegistration,
    ) -> ConditionMatch:
        return _build_match(left, right, schema, self.version, tolerance=1.0)


def _build_match(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    schema: ConditionSchemaRegistration,
    version: str,
    *,
    tolerance: float,
) -> ConditionMatch:
    matched: list[str] = []
    mismatches: list[ConditionMismatch] = []
    unknowns: list[str] = []

    for field in sorted(schema.known_fields):
        if field not in left or field not in right:
            unknowns.append(field)
            continue
        a, b = left[field], right[field]
        numeric_close = (
            isinstance(a, int | float)
            and isinstance(b, int | float)
            and abs(float(a) - float(b)) <= tolerance
        )
        if a == b or numeric_close:
            matched.append(field)
        else:
            mismatches.append(
                ConditionMismatch(field=field, left=a, right=b, reason="outside tolerance")
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
        tolerance_policy_version=version,
        schema_ref=schema.ref,
    )


@pytest.fixture
def two_versions() -> ConditionSchemaRegistry:
    """Both schema versions and both comparators registered simultaneously."""
    registry = ConditionSchemaRegistry()
    registry.register_schema(TOY_SCHEMA)
    registry.register_schema(TOY_SCHEMA_V2)
    registry.register_comparator("toy", "basic", ExactOnlyComparator())
    registry.register_comparator("toy", "basic", TolerantComparator())
    return registry


#: Differ by 0.5 on `level`: outside c1's zero tolerance, inside c2's 1.0. This is the input that
#: makes a mis-binding visible in the *verdict*, not only in the recorded version string.
_LEFT = {"setting": "nominal", "level": 1.0}
_RIGHT = {"setting": "nominal", "level": 1.5}

#: v2 declares an extra optional property, `mode`. Supplying it keeps the comparison free of
#: UNKNOWN fields so the verdict isolates the tolerance difference. Omitting it would make v2
#: report UNKNOWN for a reason unrelated to what this file is testing -- and supplying it to v1
#: would be rejected, since v1 does not declare it.
_LEFT_V2 = {**_LEFT, "mode": "a"}
_RIGHT_V2 = {**_RIGHT, "mode": "a"}


@pytest.mark.requirement("EVI-005")
@pytest.mark.spec_test("T-EVI-005")
def test_v1_always_resolves_to_c1(two_versions):
    assert two_versions.get_comparator(TOY_SCHEMA_REF).version == TOY_COMPARATOR_VERSION


@pytest.mark.requirement("EVI-005")
@pytest.mark.spec_test("T-EVI-005")
def test_v2_always_resolves_to_c2(two_versions):
    assert two_versions.get_comparator(TOY_SCHEMA_V2_REF).version == TOY_COMPARATOR_V2_VERSION


@pytest.mark.requirement("EVI-005")
@pytest.mark.spec_test("T-EVI-005")
def test_registration_order_does_not_decide_which_comparator_is_used():
    """The original defect: last-registered won. Both orders must give the same binding."""
    for order in (
        (ExactOnlyComparator(), TolerantComparator()),
        (TolerantComparator(), ExactOnlyComparator()),
    ):
        registry = ConditionSchemaRegistry()
        registry.register_schema(TOY_SCHEMA)
        registry.register_schema(TOY_SCHEMA_V2)
        for comparator in order:
            registry.register_comparator("toy", "basic", comparator)
        assert registry.get_comparator(TOY_SCHEMA_REF).version == TOY_COMPARATOR_VERSION
        assert registry.get_comparator(TOY_SCHEMA_V2_REF).version == TOY_COMPARATOR_V2_VERSION


@pytest.mark.requirement("EVI-005")
@pytest.mark.spec_test("T-EVI-005")
def test_v1_and_v2_reach_different_verdicts_on_the_same_level_difference(two_versions):
    """The observable consequence: same 0.5 gap, different declared rules, different verdict.

    If binding were still by ``(domain, schema_id)`` these two would agree, because both would
    run whichever comparator was registered last.
    """
    v1 = two_versions.compare(_LEFT, _RIGHT, TOY_SCHEMA_REF)
    v2 = two_versions.compare(_LEFT_V2, _RIGHT_V2, TOY_SCHEMA_V2_REF)

    # c1: zero tolerance, so a 0.5 gap on `level` is a mismatch.
    assert v1.tolerance_policy_version == TOY_COMPARATOR_VERSION
    assert v1.state is ConditionMatchState.INCOMPATIBLE
    assert [m.field for m in v1.mismatches] == ["level"]
    assert not v1.is_comparable

    # c2: 1.0 tolerance, so the same gap matches.
    assert v2.tolerance_policy_version == TOY_COMPARATOR_V2_VERSION
    assert v2.state is ConditionMatchState.EXACT
    assert "level" in v2.matched_fields
    assert v2.is_comparable


@pytest.mark.requirement("EVI-005")
@pytest.mark.spec_test("T-EVI-005")
def test_match_records_the_schema_version_it_was_computed_under(two_versions):
    assert str(two_versions.compare(_LEFT, _RIGHT, TOY_SCHEMA_REF).schema_ref) == TOY_SCHEMA_REF
    assert (
        str(two_versions.compare(_LEFT_V2, _RIGHT_V2, TOY_SCHEMA_V2_REF).schema_ref)
        == TOY_SCHEMA_V2_REF
    )


@pytest.mark.requirement("EVI-005")
@pytest.mark.spec_test("T-EVI-005")
def test_missing_comparator_for_a_declared_version_fails_closed():
    """Falling back to another registered comparator would apply undeclared rules silently."""
    registry = ConditionSchemaRegistry()
    registry.register_schema(TOY_SCHEMA)
    registry.register_schema(TOY_SCHEMA_V2)
    # Only c1 registered; v2 declares c2.
    registry.register_comparator("toy", "basic", ExactOnlyComparator())

    assert registry.get_comparator(TOY_SCHEMA_REF).version == TOY_COMPARATOR_VERSION
    with pytest.raises(ConditionSchemaError, match="declared comparator_version"):
        registry.get_comparator(TOY_SCHEMA_V2_REF)
    with pytest.raises(ConditionSchemaError, match="declared comparator_version"):
        registry.compare(
            {"setting": "a", "level": 1.0}, {"setting": "a", "level": 1.0}, TOY_SCHEMA_V2_REF
        )


@pytest.mark.requirement("EVI-005")
@pytest.mark.spec_test("T-EVI-005")
def test_two_implementations_cannot_share_one_comparator_version():
    """A persisted match names only the version, so it must identify one implementation."""

    class Impostor(ExactOnlyComparator):
        pass

    registry = ConditionSchemaRegistry()
    registry.register_schema(TOY_SCHEMA)
    registry.register_comparator("toy", "basic", ExactOnlyComparator())
    with pytest.raises(ConditionSchemaError, match="already registered"):
        registry.register_comparator("toy", "basic", Impostor())


@pytest.mark.requirement("EVI-005")
@pytest.mark.spec_test("T-EVI-005")
def test_re_registering_the_same_comparator_instance_is_a_no_op():
    registry = ConditionSchemaRegistry()
    registry.register_schema(TOY_SCHEMA)
    comparator = ExactOnlyComparator()
    registry.register_comparator("toy", "basic", comparator)
    registry.register_comparator("toy", "basic", comparator)
    assert registry.get_comparator(TOY_SCHEMA_REF) is comparator


@pytest.mark.requirement("EVI-005")
@pytest.mark.spec_test("T-EVI-005")
def test_comparator_whose_version_drifted_from_the_schema_is_rejected(two_versions):
    """Defensive: a ConditionMatch must never claim rules that were not applied."""

    class Drifted(ExactOnlyComparator):
        def compare(self, left, right, schema):  # type: ignore[no-untyped-def]
            match = super().compare(left, right, schema)
            return match.model_copy(update={"tolerance_policy_version": "somewhere-else"})

    two_versions._comparators[("toy", "basic", TOY_COMPARATOR_VERSION)] = Drifted()
    with pytest.raises(ConditionSchemaError, match="tolerance_policy_version"):
        two_versions.compare(_LEFT, _RIGHT, TOY_SCHEMA_REF)
