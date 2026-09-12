"""Conformance of the canonical JSON serializer to its **restricted JCS profile**.

Not "RFC 8785 conformance" -- the serializer deliberately implements a subset and fails closed
outside it (floats, oversized integers, non-JSON types). Calling these tests a conformance suite
for the full standard would overstate what they establish, so both the module and this file say
"restricted profile" and the rejection cases are asserted as *deliberate refusals* rather than as
gaps.

What the tests do establish: for every document the profile accepts, the output matches what a
conformant implementation would produce. The two places that is easy to get accidentally wrong are
UTF-16 key ordering and string escaping, so both are checked directly.

Unmarked: this is the mechanism EVI-006 depends on, not the requirement itself. T-EVI-006 asserts
bundle-level properties.
"""

from __future__ import annotations

import json

import pytest

from lab_brain.core.canonical_json import (
    MAX_SAFE_INTEGER,
    CanonicalizationError,
    canonical_bytes,
    canonical_hash,
    canonicalize,
)

# ---------------------------------------------------------------------------
# Key ordering
# ---------------------------------------------------------------------------


def test_object_keys_are_sorted():
    assert canonicalize({"b": 1, "a": 2}) == '{"a":2,"b":1}'


def test_key_order_in_the_input_does_not_affect_the_output():
    """The whole reason JCS exists: same content, same bytes, whatever the insertion order."""
    forms = [
        {"query": "x", "policy": "p", "ids": ["a", "b"]},
        {"ids": ["a", "b"], "query": "x", "policy": "p"},
        {"policy": "p", "ids": ["a", "b"], "query": "x"},
    ]
    outputs = {canonicalize(form) for form in forms}
    assert len(outputs) == 1


def test_nested_object_keys_are_also_sorted():
    assert canonicalize({"z": {"b": 1, "a": 2}, "a": 3}) == '{"a":3,"z":{"a":2,"b":1}}'


def test_keys_are_sorted_by_utf16_code_unit_not_code_point():
    """RFC 8785 §3.2.3. The two orders diverge outside the BMP.

    U+10000 encodes as the surrogate pair D800 DC00, so by UTF-16 code unit it sorts *before*
    U+FFFD (FFFD). By Python's default code-point ordering it would sort after. Sorting with
    `sorted()` here would produce a hash that disagrees with any conforming implementation.
    """
    astral = "\U00010000"
    bmp_high = "�"
    result = canonicalize({bmp_high: 1, astral: 2})
    assert result.index(json.dumps(astral, ensure_ascii=False)) < result.index(
        json.dumps(bmp_high, ensure_ascii=False)
    )


def test_non_string_keys_are_rejected():
    with pytest.raises(CanonicalizationError, match="keys must be strings"):
        canonicalize({1: "a"})


# ---------------------------------------------------------------------------
# Scalars
# ---------------------------------------------------------------------------


def test_whitespace_is_not_emitted():
    assert canonicalize({"a": [1, 2], "b": {"c": 3}}) == '{"a":[1,2],"b":{"c":3}}'


def test_booleans_and_null():
    assert canonicalize({"t": True, "f": False, "n": None}) == '{"f":false,"n":null,"t":true}'


def test_bool_is_not_serialized_as_an_integer():
    """`bool` subclasses `int`, so an ordering slip here would emit `1` instead of `true`."""
    assert canonicalize(True) == "true"
    assert canonicalize(1) == "1"


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, "0"), (-1, "-1"), (42, "42"), (MAX_SAFE_INTEGER, str(MAX_SAFE_INTEGER))],
)
def test_integers(value, expected):
    assert canonicalize(value) == expected


# ---------------------------------------------------------------------------
# Outside the profile: deliberate refusals, not gaps
#
# A conformant RFC 8785 implementation would serialize all three of these. This profile refuses
# them, and the refusal is the tested behaviour -- rejecting is safe, guessing is not.
# ---------------------------------------------------------------------------


def test_integers_beyond_the_safe_range_are_refused():
    """Past 2^53-1 an integer is not exactly a double, so it has no canonical JCS form."""
    with pytest.raises(CanonicalizationError, match="safe range"):
        canonicalize(MAX_SAFE_INTEGER + 1)


def test_floats_are_refused_rather_than_approximated():
    """Outside the profile by design.

    ECMAScript Number::toString is the one genuinely hard part of RFC 8785. An approximation would
    produce hashes agreeing on one machine and disagreeing on another -- worse than refusing,
    because the failure surfaces only when two environments compare provenance.
    """
    with pytest.raises(CanonicalizationError, match="outside this restricted JCS profile"):
        canonicalize({"level": 1.5})


def test_types_outside_the_profile_are_refused():
    with pytest.raises(CanonicalizationError, match="outside this restricted JCS profile"):
        canonicalize({"when": object()})


# ---------------------------------------------------------------------------
# String escaping (RFC 8785 §3.2.2.2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("plain", '"plain"'),
        ('quote"', '"quote\\""'),
        ("back\\slash", '"back\\\\slash"'),
        ("tab\t", '"tab\\t"'),
        ("nl\n", '"nl\\n"'),
        ("cr\r", '"cr\\r"'),
        ("bs\b", '"bs\\b"'),
        ("ff\f", '"ff\\f"'),
        # Other C0 controls use \u00xx with lowercase hex.
        ("\x00", '"\\u0000"'),
        ("\x1f", '"\\u001f"'),
    ],
)
def test_string_escaping(raw, expected):
    assert canonicalize(raw) == expected


def test_non_ascii_is_not_escaped():
    """RFC 8785 output is UTF-8; escaping non-ASCII would change the bytes that get hashed."""
    assert canonicalize("條件") == '"條件"'
    assert canonical_bytes("條件") == '"條件"'.encode()


def test_forward_slash_is_not_escaped():
    assert canonicalize("a/b") == '"a/b"'


# ---------------------------------------------------------------------------
# RFC 8785 published test vector, restricted to the accepted domain
# ---------------------------------------------------------------------------


def test_rfc8785_sorting_vector_within_the_profile():
    """The RFC's own key-sorting example, with its float members removed.

    Adapted, not copied: the published vector includes floats, which this profile refuses by
    design. So this checks the property the vector exists to demonstrate -- UTF-16 key ordering
    across literals, BMP and non-BMP characters -- on the subset the profile accepts. It is not
    evidence of full-vector conformance and is not named as if it were.
    """
    document = {
        "€": "Euro Sign",
        "\r": "Carriage Return",
        "1": "One",
        "": "Control",
        "ö": "Latin Small Letter O With Diaeresis",
        "": "Empty",
        "": "Start of Heading",
    }
    expected_key_order = [
        "",
        "",
        "\r",
        "1",
        "",
        "ö",
        "€",
    ]
    result = canonicalize(document)
    positions = [
        result.index(json.dumps(key, ensure_ascii=False) + ":") for key in expected_key_order
    ]
    assert positions == sorted(positions)


def test_array_order_is_preserved():
    """Arrays are ordered data. Sorting them would silently merge distinct bundles."""
    assert canonicalize(["b", "a"]) == '["b","a"]'
    assert canonicalize(["a", "b"]) != canonicalize(["b", "a"])


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------


def test_hash_carries_its_algorithm():
    digest = canonical_hash({"a": 1})
    assert digest.startswith("sha256:")
    assert len(digest.split(":")[1]) == 64


def test_hash_is_stable_across_key_permutations():
    assert canonical_hash({"a": 1, "b": 2}) == canonical_hash({"b": 2, "a": 1})


def test_hash_changes_with_content():
    assert canonical_hash({"a": 1}) != canonical_hash({"a": 2})
    assert canonical_hash({"a": 1}) != canonical_hash({"b": 1})


def test_hash_distinguishes_nesting_from_flattening():
    """`{"a": {"b": 1}}` and `{"a.b": 1}` are different documents and must not collide."""
    assert canonical_hash({"a": {"b": 1}}) != canonical_hash({"a.b": 1})
