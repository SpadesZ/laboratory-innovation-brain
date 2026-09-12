"""RFC 8785 conformance for the canonical JSON serializer.

Unmarked: this is the mechanism EVI-006 depends on, not the requirement itself. T-EVI-006 asserts
bundle-level properties; these assert that the serializer underneath actually follows the standard,
including the two places it is easy to be accidentally wrong -- UTF-16 key ordering and string
escaping.
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


def test_integers_beyond_the_safe_range_are_rejected():
    """Past 2^53-1 an integer is not exactly a double, so it has no canonical JCS form."""
    with pytest.raises(CanonicalizationError, match="safe range"):
        canonicalize(MAX_SAFE_INTEGER + 1)


def test_floats_are_rejected_with_an_explanation():
    """Deliberate: ECMAScript Number::toString is the one part of RFC 8785 easy to get wrong."""
    with pytest.raises(CanonicalizationError, match="float values are not canonicalizable"):
        canonicalize({"level": 1.5})


def test_unsupported_types_are_rejected():
    with pytest.raises(CanonicalizationError, match="not JSON-canonicalizable"):
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
# RFC 8785 published test vectors
# ---------------------------------------------------------------------------


def test_rfc8785_structural_example():
    """The RFC's own sorting example, minus its float members.

    Adapted rather than copied verbatim: the published vector includes floats, which this
    implementation refuses by design. The structural properties it demonstrates -- literal
    ordering, nested sorting, array order preservation -- are what is checked here.
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
