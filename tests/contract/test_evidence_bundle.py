"""T-EVI-006 — canonical EvidenceBundle hash (EVI-006).

Pass condition (§26):

    permuted JSON key order yields same canonical bundle hash; changed attestation
    order/policy/query snapshot changes hash as defined.

Two halves, and they pull in opposite directions. The hash must be **insensitive** to things that
are not content — key order, insertion order, the bundle's own id and timestamp — and
**sensitive** to everything that is: which attestations, in what order, under which query, policy
and condition filter.

A hash that fails the first half breaks deduplication: the same retrieval assembled by two code
paths would look like two different bundles. A hash that fails the second half is worse — two
genuinely different retrievals would share provenance, so "the model saw this evidence" would be
unfalsifiable.

Note on EVI-006's scope. The requirement reads "Every scientific LLM call MUST use a canonical
EvidenceBundle with deterministic hash...". The *hash* half is what T-EVI-006 asserts and what M0a
delivers. The "every LLM call" half is enforced at the call wrapper (AGT-017) and is covered by
T-LLM-001 in M1, when a model call path exists to enforce it against.
"""

from __future__ import annotations

import os

import pytest

from lab_brain.core.canonical_json import CanonicalizationError
from lab_brain.core.models.evidence_bundle import (
    BUNDLE_SCHEMA_VERSION,
    IDENTITY_EXCLUDED_FIELDS,
    EvidenceBundle,
    ResearchIntent,
)
from lab_brain.spec import repo_root


def make_bundle(**overrides) -> EvidenceBundle:
    fields = {
        "research_intent": ResearchIntent(intent="DIAGNOSIS", stakes="HIGH"),
        "query_text": "why is Rs weakly bias-dependent",
        "source_policy_id": "sp:diagnosis",
        "source_policy_version": "1.0.0",
        "condition_filter": {"setting": "nominal"},
        "condition_schema_versions": {"toy": "toy/basic@1.0.0"},
        "ordered_attestation_ids": ("att:a", "att:b", "att:c"),
        "source_snapshot_refs": ("snap:1",),
        "project_id": "prj:test",
    }
    fields.update(overrides)
    return EvidenceBundle(**fields)


# ---------------------------------------------------------------------------
# Insensitive to what is not content
# ---------------------------------------------------------------------------


@pytest.mark.requirement("EVI-006")
@pytest.mark.spec_test("T-EVI-006")
def test_permuted_key_order_yields_the_same_hash():
    """The literal pass condition. Dict insertion order must not reach the hash."""
    forward = EvidenceBundle(
        research_intent=ResearchIntent(intent="DIAGNOSIS"),
        query_text="q",
        source_policy_id="sp:1",
        source_policy_version="1.0.0",
        condition_filter={"a": 1, "b": 2},
        condition_schema_versions={"x": "x/y@1.0.0", "m": "m/n@1.0.0"},
        ordered_attestation_ids=("att:a",),
        project_id="prj:test",
    )
    reversed_insertion = EvidenceBundle(
        project_id="prj:test",
        ordered_attestation_ids=("att:a",),
        condition_schema_versions={"m": "m/n@1.0.0", "x": "x/y@1.0.0"},
        condition_filter={"b": 2, "a": 1},
        source_policy_version="1.0.0",
        source_policy_id="sp:1",
        query_text="q",
        research_intent=ResearchIntent(intent="DIAGNOSIS"),
    )
    assert forward.canonical_hash == reversed_insertion.canonical_hash


@pytest.mark.requirement("EVI-006")
@pytest.mark.spec_test("T-EVI-006")
def test_hash_ignores_bundle_id_and_timestamp():
    """Two retrievals selecting the same evidence under the same policy are the same bundle.

    Folding a fresh UUID or timestamp into the hash would make every bundle unique, which defeats
    the comparison the hash exists for.
    """
    first, second = make_bundle(), make_bundle()
    assert first.bundle_id != second.bundle_id
    assert first.created_at <= second.created_at
    assert first.canonical_hash == second.canonical_hash
    assert first.is_equivalent_to(second)


@pytest.mark.requirement("EVI-006")
@pytest.mark.spec_test("T-EVI-006")
@pytest.mark.parametrize("field", sorted(IDENTITY_EXCLUDED_FIELDS))
def test_declared_non_identity_fields_do_not_affect_the_hash(field):
    """Every field documented as excluded must actually be excluded."""
    baseline = make_bundle()
    altered = make_bundle(
        **{
            field: {
                "bundle_id": "bdl:different",
                "created_at": baseline.created_at.replace(year=2030),
                "retrieval_trace_id": "trace:different",
                "project_id": "prj:different",
            }[field]
        }
    )
    assert altered.canonical_hash == baseline.canonical_hash, (
        f"{field} is documented as excluded from identity but changed the hash"
    )


@pytest.mark.requirement("EVI-006")
@pytest.mark.spec_test("T-EVI-006")
def test_hash_is_stable_across_processes():
    """A hash that depends on process state cannot be compared tomorrow.

    Run in real subprocesses under different ``PYTHONHASHSEED`` values, because the seed is fixed
    for a process's lifetime -- asserting twice inside one process could not detect the problem.

    The condition filter is built by iterating a **set**, so its insertion order really is
    hash-order dependent. An earlier version of this test used a dict literal, whose insertion
    order is fixed in Python 3.7+; the seed could not have influenced it, so the test would have
    passed against a naive serializer and proved nothing.

    Two assertions, and the second is what makes the first mean something:

      1. the canonical hash is identical across every seed;
      2. a naive ``json.dumps`` over the same source differs across seeds.

    If (2) ever stops holding, the fixture has stopped being hash-order dependent and (1) has
    become vacuous -- so the test fails and says so rather than passing quietly.
    """
    import json
    import subprocess
    import sys

    program = (
        "import hashlib, json, sys\n"
        "sys.path.insert(0, 'src')\n"
        "from lab_brain.core.models.evidence_bundle import EvidenceBundle, ResearchIntent\n"
        # Iterating a set is where string hash randomisation actually shows up. Enough members
        # that the permutation differs between seeds with overwhelming probability.
        "keys = {'alpha', 'beta', 'gamma', 'delta', 'epsilon', 'zeta', 'eta', 'theta'}\n"
        "condition_filter = {key: 'v' for key in keys}\n"
        "schema_versions = {key: 'toy/basic@1.0.0' for key in keys}\n"
        "b = EvidenceBundle(\n"
        "    research_intent=ResearchIntent(intent='DIAGNOSIS', stakes='HIGH'),\n"
        "    query_text='q',\n"
        "    source_policy_id='sp:1',\n"
        "    source_policy_version='1.0.0',\n"
        "    condition_filter=condition_filter,\n"
        "    condition_schema_versions=schema_versions,\n"
        "    ordered_attestation_ids=('att:a', 'att:b'),\n"
        "    project_id='prj:test',\n"
        ")\n"
        # The control: what a naive serializer would have hashed.
        "naive = hashlib.sha256(json.dumps(condition_filter).encode()).hexdigest()\n"
        "print(json.dumps({'canonical': b.canonical_hash, 'naive': naive}))\n"
    )

    canonical_digests: set[str] = set()
    naive_digests: set[str] = set()
    for seed in ("0", "1", "12345", "99999"):
        result = subprocess.run(
            [sys.executable, "-c", program],
            cwd=repo_root(),
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "PYTHONHASHSEED": seed},
        )
        assert result.returncode == 0, f"seed {seed} failed:\n{result.stderr}"
        payload = json.loads(result.stdout.strip())
        canonical_digests.add(payload["canonical"])
        naive_digests.add(payload["naive"])

    assert len(naive_digests) > 1, (
        "the fixture is no longer hash-order dependent: a naive json.dumps produced the same "
        f"digest under every seed ({naive_digests}). The canonical-stability assertion below "
        "would be vacuous, so fix the fixture rather than this assertion."
    )
    assert len(canonical_digests) == 1, (
        f"canonical hash varied across hash seeds: {canonical_digests}"
    )


# ---------------------------------------------------------------------------
# Sensitive to everything that is content
# ---------------------------------------------------------------------------


@pytest.mark.requirement("EVI-006")
@pytest.mark.spec_test("T-EVI-006")
def test_attestation_order_changes_the_hash():
    """Rank affects what a model attends to, so order is part of identity."""
    baseline = make_bundle(ordered_attestation_ids=("att:a", "att:b", "att:c"))
    reordered = make_bundle(ordered_attestation_ids=("att:c", "att:b", "att:a"))
    assert baseline.canonical_hash != reordered.canonical_hash


@pytest.mark.requirement("EVI-006")
@pytest.mark.spec_test("T-EVI-006")
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("query_text", "a different question"),
        ("source_policy_id", "sp:novelty"),
        ("source_policy_version", "2.0.0"),
        ("condition_filter", {"setting": "stressed"}),
        ("condition_schema_versions", {"toy": "toy/basic@2.0.0"}),
        ("ordered_attestation_ids", ("att:a", "att:b")),
        ("source_snapshot_refs", ("snap:2",)),
        ("schema_version", BUNDLE_SCHEMA_VERSION + 1),
    ],
)
def test_changing_any_identity_field_changes_the_hash(field, value):
    assert make_bundle(**{field: value}).canonical_hash != make_bundle().canonical_hash


@pytest.mark.requirement("EVI-006")
@pytest.mark.spec_test("T-EVI-006")
def test_research_intent_and_stakes_are_part_of_identity():
    """SRC-002 switches policy on intent and stakes, so they must not be invisible to the hash."""
    baseline = make_bundle()
    assert (
        make_bundle(
            research_intent=ResearchIntent(intent="NOVELTY_AUDIT", stakes="HIGH")
        ).canonical_hash
        != baseline.canonical_hash
    )
    assert (
        make_bundle(research_intent=ResearchIntent(intent="DIAGNOSIS", stakes="LOW")).canonical_hash
        != baseline.canonical_hash
    )


@pytest.mark.requirement("EVI-006")
@pytest.mark.spec_test("T-EVI-006")
def test_an_empty_bundle_still_has_a_hash():
    """ "We searched under this policy and found nothing" is a reproducible, auditable result."""
    empty = make_bundle(ordered_attestation_ids=())
    assert empty.is_empty
    assert empty.canonical_hash
    assert empty.canonical_hash != make_bundle().canonical_hash


@pytest.mark.requirement("EVI-006")
@pytest.mark.spec_test("T-EVI-006")
def test_nesting_is_not_flattened_into_a_collision():
    """A filter of `{"a": {"b": 1}}` must not hash as `{"a.b": 1}`."""
    assert (
        make_bundle(condition_filter={"a": {"b": "1"}}).canonical_hash
        != make_bundle(condition_filter={"a.b": "1"}).canonical_hash
    )


# ---------------------------------------------------------------------------
# The hash is derived, not assigned
# ---------------------------------------------------------------------------


@pytest.mark.requirement("EVI-006")
@pytest.mark.spec_test("T-EVI-006")
def test_hash_cannot_be_supplied_by_a_caller():
    """A stored hash disagreeing with its content would make provenance unverifiable."""
    dumped = make_bundle().model_dump()
    assert "canonical_hash" in dumped
    with pytest.raises(ValueError, match="are derived, not inputs"):
        EvidenceBundle.model_validate(dumped)


@pytest.mark.requirement("EVI-006")
@pytest.mark.spec_test("T-EVI-006")
def test_bundle_round_trips_once_the_derived_fields_are_dropped():
    """The reconstruction path a repository uses: drop derived values, recompute, compare."""
    original = make_bundle()
    payload = {
        key: value
        for key, value in original.model_dump().items()
        if key not in {"canonical_hash", "query_hash"}
    }
    rebuilt = EvidenceBundle.model_validate(payload)
    assert rebuilt.canonical_hash == original.canonical_hash
    assert rebuilt.query_hash == original.query_hash
    assert rebuilt.bundle_id == original.bundle_id


@pytest.mark.requirement("EVI-006")
@pytest.mark.spec_test("T-EVI-006")
def test_query_hash_matches_the_query_text():
    bundle = make_bundle(query_text="exact question")
    assert bundle.query_hash == make_bundle(query_text="exact question").query_hash
    assert bundle.query_hash != make_bundle(query_text="other question").query_hash


@pytest.mark.requirement("EVI-006")
@pytest.mark.spec_test("T-EVI-006")
def test_hash_declares_its_algorithm():
    """So a future digest migration can coexist instead of silently reinterpreting old hashes."""
    digest = make_bundle().canonical_hash
    algorithm, _, hex_digest = digest.partition(":")
    assert algorithm == "sha256"
    assert len(hex_digest) == 64


# ---------------------------------------------------------------------------
# Integrity of the bundle contents
# ---------------------------------------------------------------------------


@pytest.mark.requirement("EVI-006")
@pytest.mark.spec_test("T-EVI-006")
def test_duplicate_attestation_in_one_bundle_is_rejected():
    """One attestation listed twice double-counts it before EVI-004 is ever reached."""
    with pytest.raises(ValueError, match="duplicates"):
        make_bundle(ordered_attestation_ids=("att:a", "att:b", "att:a"))


@pytest.mark.requirement("EVI-006")
@pytest.mark.spec_test("T-EVI-006")
def test_a_float_in_the_condition_filter_is_refused_not_guessed():
    """Floats are outside the restricted JCS profile, so hashing fails loudly.

    Hashing a float on a guess would produce digests that agree on one machine and disagree on
    another -- the failure mode that makes a provenance hash worthless precisely when it matters.
    A conformant RFC 8785 implementation would accept this; this profile refuses rather than
    approximate ECMAScript `Number::toString`.
    """
    bundle = make_bundle(condition_filter={"level": 1.5})
    with pytest.raises(CanonicalizationError, match="outside this restricted JCS profile"):
        bundle.compute_hash()
