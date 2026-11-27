"""T-EVI-007 — dense retrieval, embedding-space filtering, and verified cutover (§6.13, §6.20).

§26's pass condition: *mixed embedding versions are never compared; dual-index migration
preserves benchmark recall within threshold before cutover.*

Both clauses, plus the adversarial set, because the attacks M1-P1 closed for lexical retrieval do
not transfer by assumption -- a dense index is a second index, and every one of them has to be
re-run against it. Stale body, wrong project, incompatible space, dropped index, model migration.

THE THING THAT MAKES THIS REQUIREMENT DIFFERENT from the rest of the evidence path: a cross-space
cosine does not fail. It returns a real number in [-1, 1], it ranks, and the retrieval looks like
it worked. So every test below asserts a *refusal*, never an empty result -- an empty result reads
as "nothing matched", which is a legitimate outcome and would hide the misconfiguration behind a
plausible one.
"""

from __future__ import annotations

import pytest

from lab_brain.evidence.dense_index import (
    DenseEvidenceIndex,
    DualIndexCutover,
    EmbeddingSpace,
    EmbeddingSpaceMismatch,
    IndexNotReady,
    cosine,
    hashing_embedder,
)
from lab_brain.evidence.retriever import CandidateResolver
from tests.evidence_fixtures import segment_fixture

pytestmark = [pytest.mark.requirement("EVI-007"), pytest.mark.spec_test("T-EVI-007")]

PROJECT = "prj:test"
OTHER_PROJECT = "prj:other"

SPACE_V1 = EmbeddingSpace(model="toy-embed", version="1.0.0", dimensions=64)
SPACE_V2 = EmbeddingSpace(model="toy-embed", version="2.0.0", dimensions=64)
OTHER_MODEL = EmbeddingSpace(model="other-embed", version="1.0.0", dimensions=64)
WIDER = EmbeddingSpace(model="toy-embed", version="1.0.0", dimensions=128)


def _units():
    return segment_fixture().units


def _index(space: EmbeddingSpace = SPACE_V1, index_id: str = "idx:dense:v1") -> DenseEvidenceIndex:
    index = DenseEvidenceIndex(index_id, space, hashing_embedder(space))
    index.add_all(_units(), project_id=PROJECT)
    return index


# ---------------------------------------------------------------------------
# Clause one — mixed embedding versions are never compared
# ---------------------------------------------------------------------------


def test_a_query_in_the_same_space_retrieves(capsys=None):
    """The control. Every refusal below is worthless without it."""
    index = _index()
    hits = index.search("reverse bias capacitance", project_id=PROJECT, space=SPACE_V1)
    assert hits, "same-space retrieval returned nothing"
    assert all(0.0 <= h.score <= 1.0 or -1.0 <= h.score <= 1.0 for h in hits)


@pytest.mark.parametrize(
    ("other", "label"),
    [(SPACE_V2, "same model, different version"), (OTHER_MODEL, "different model")],
)
def test_a_query_from_another_space_is_refused_not_silently_ranked(other, label):
    """THE EVI-007 probe. §6.13: mixing spaces is 靜默垃圾 -- silent garbage.

    The failure being prevented is not an error, it is a *plausible answer*. So the assertion is
    on the exception, and a companion assertion below pins that the permissive version would
    have produced results rather than nothing.
    """
    index = _index()
    with pytest.raises(EmbeddingSpaceMismatch, match="embedding space"):
        index.search("reverse bias", project_id=PROJECT, space=other)


def test_the_refusal_prevents_a_ranking_that_would_otherwise_have_looked_fine():
    """What the guard is standing in front of, demonstrated rather than asserted.

    Two spaces, same dimensionality. Their vectors are genuinely different, and a cosine over
    them still produces a finite, orderable number. That number is what would have been returned
    -- not an error, not an empty list -- which is exactly why the check has to be a refusal.
    """
    v1 = hashing_embedder(SPACE_V1)("reverse bias capacitance")
    v2 = hashing_embedder(SPACE_V2)("reverse bias capacitance")
    assert list(v1) != list(v2), "the two spaces produced identical vectors; the fixture is weak"
    score = cosine(v1, v2)
    assert -1.0 <= score <= 1.0, "a cross-space cosine is a perfectly well-formed number"


def test_vectors_of_different_width_cannot_be_compared_at_all():
    """`dimensions` is a compatibility key, not a detail.

    A cosine that zero-padded would not be a smaller error than a cross-space one -- it is the
    same error with an extra step, and it produces a number that ranks.
    """
    index = _index()
    with pytest.raises(EmbeddingSpaceMismatch):
        index.search("reverse bias", project_id=PROJECT, space=WIDER)
    with pytest.raises(EmbeddingSpaceMismatch, match="dimensional"):
        cosine([0.1] * 64, [0.1] * 128)


def test_the_representation_records_which_space_answered():
    """§6.20: "cutover 前後都必須可回答『這筆檢索用的是哪個 embedding version』"."""
    index = _index()
    unit = _units()[0]
    representation = index.representation_for(unit.evidence_unit_id, PROJECT)
    assert representation is not None
    assert representation.embedding_model == "toy-embed"
    assert representation.embedding_version == "1.0.0"
    assert representation.dimensions == 64


# ---------------------------------------------------------------------------
# The locked boundary, re-run against the dense index
# ---------------------------------------------------------------------------


def test_a_dense_candidate_carries_no_evidence_body():
    """ADR-0011, expressed as an API. A second index does not get a second rule."""
    index = _index()
    hit = index.search("reverse bias", project_id=PROJECT, space=SPACE_V1)[0]
    assert not hasattr(hit, "body")
    assert set(hit.model_dump()) == {
        "evidence_unit_id",
        "representation_id",
        "project_id",
        "score",
        "rank",
        "retrieval_trace_id",
    }


def test_a_tampered_dense_payload_cannot_change_the_evidence_body():
    """The attack the lexical index closed, re-run here rather than assumed to transfer.

    An attacker with index write access rewrites both the vector and the digest -- a tamper that
    left the digest behind would model an attacker who politely left evidence convicting them.
    Retrieval may rank differently; the canonical body does not move.
    """
    index = _index()
    units = {u.evidence_unit_id: u for u in _units()}
    target = _units()[0]
    original_body = target.body

    index.tamper(target.evidence_unit_id, PROJECT, "Cj increased to 9.99 pF/mm under forward bias")

    resolver = CandidateResolver(
        load_unit=lambda key: units.get(key), is_present_in=lambda _unit, _project: True
    )
    # A generous limit, because what is being proven is about the *body* of whatever comes back,
    # not about ranking. Narrowing it would make the test depend on the fixture embedder's
    # ordering, which is not the property under test.
    hits = index.search("forward bias", project_id=PROJECT, space=SPACE_V1, limit=50)
    resolved, _divergences = resolver.resolve(hits)

    matched = [c for c in resolved if c.unit.evidence_unit_id == target.evidence_unit_id]
    assert matched, "the tampered unit was not retrieved at all, so nothing was proven"
    assert matched[0].body == original_body
    assert "9.99" not in matched[0].body


def test_dense_retrieval_does_not_cross_project_boundaries():
    """SEC-002. A second index is a second place project scope can be forgotten."""
    index = _index()
    other = DenseEvidenceIndex("idx:dense:v1", SPACE_V1, hashing_embedder(SPACE_V1))
    other.add_all(_units(), project_id=OTHER_PROJECT)

    mine = index.search("reverse bias", project_id=PROJECT, space=SPACE_V1)
    theirs = index.search("reverse bias", project_id=OTHER_PROJECT, space=SPACE_V1)
    assert mine, "the control returned nothing"
    assert theirs == (), "a query scoped to another project returned this project's evidence"


def test_dropping_and_rebuilding_the_index_changes_no_evidence_identity():
    """ADR-0011's whole point: the index is derived, the evidence is not.

    A rebuild mints new `representation_id`s -- they are event-addressed, and a new build is a
    new event. What must not move: the unit ids, the canonical bodies, and the payload digests,
    because those are functions of the evidence rather than of the index.
    """
    index = _index()
    before = {
        u.evidence_unit_id: index.representation_for(u.evidence_unit_id, PROJECT) for u in _units()
    }
    index.drop()
    assert index.size == 0
    assert index.search("reverse bias", project_id=PROJECT, space=SPACE_V1) == ()

    index.add_all(_units(), project_id=PROJECT)
    after = {
        u.evidence_unit_id: index.representation_for(u.evidence_unit_id, PROJECT) for u in _units()
    }

    assert set(before) == set(after), "a rebuild changed which evidence units exist"
    for unit_id, old in before.items():
        assert after[unit_id].payload_digest == old.payload_digest
        assert after[unit_id].representation_id != old.representation_id


# ---------------------------------------------------------------------------
# Clause two — dual-index migration with a verified cutover
# ---------------------------------------------------------------------------


def _cases():
    """Benchmark cases: each query and the unit ids it must recall."""
    units = _units()
    return [(unit.body[:60], frozenset({unit.evidence_unit_id})) for unit in units[:4]]


def _cutover(recall_floor: float = 0.9) -> DualIndexCutover:
    old = _index(SPACE_V1, "idx:dense:v1")
    new = DenseEvidenceIndex("idx:dense:v2", SPACE_V2, hashing_embedder(SPACE_V2))
    new.add_all(_units(), project_id=PROJECT)
    return DualIndexCutover(old=old, new=new, recall_floor=recall_floor)


def test_both_indexes_coexist_and_the_old_one_answers_until_promotion():
    """§6.20's 新舊並存. A half-finished migration degrades to the previous behaviour."""
    cutover = _cutover()
    assert cutover.active.index_id == "idx:dense:v1"
    assert cutover.which_version_answered() == SPACE_V1.key
    assert cutover.new.size > 0, "the new index was never populated"


def test_a_cutover_that_was_never_measured_is_refused():
    """ "以 benchmark recall 驗證後才 cutover". "We did not check" is not a pass."""
    cutover = _cutover()
    with pytest.raises(IndexNotReady, match="has not been measured"):
        cutover.promote()
    assert cutover.active.index_id == "idx:dense:v1"


def test_a_measured_cutover_above_the_floor_promotes_and_reports_which_version():
    cutover = _cutover()
    report = cutover.measure(_cases(), project_id=PROJECT)
    assert report.recall >= 0.9, f"the fixture index recalled only {report.recall:.2f}"

    promoted = cutover.promote()
    assert cutover.promoted
    assert cutover.active.index_id == "idx:dense:v2"
    assert cutover.which_version_answered() == SPACE_V2.key
    assert promoted.space_key == SPACE_V2.key


def test_a_cutover_below_the_declared_floor_leaves_the_old_index_active():
    """The gate, doing its job. A disappointing measurement does not become a deploy decision."""
    cutover = _cutover(recall_floor=1.01)
    cutover.measure(_cases(), project_id=PROJECT)
    with pytest.raises(IndexNotReady, match="below the declared floor"):
        cutover.promote()
    assert not cutover.promoted
    assert cutover.active.index_id == "idx:dense:v1"
    assert cutover.which_version_answered() == SPACE_V1.key


def test_recall_cannot_be_measured_over_an_empty_benchmark():
    """1.00 over nothing is the number an unverified cutover produces."""
    cutover = _cutover()
    with pytest.raises(IndexNotReady, match="empty benchmark"):
        cutover.measure([], project_id=PROJECT)


def test_a_case_expecting_no_units_is_refused():
    """0/0 reported as 1.00 is how a cutover passes without recalling anything."""
    cutover = _cutover()
    with pytest.raises(IndexNotReady, match="expects no units"):
        cutover.measure([("anything", frozenset())], project_id=PROJECT)


def test_the_two_indexes_are_never_queried_together():
    """Dual-index means two indexes, not one merged result set.

    Merging them would be the cross-space comparison this whole requirement forbids, arrived at
    by a different route -- and the merged ranking would look entirely reasonable.
    """
    cutover = _cutover()
    with pytest.raises(EmbeddingSpaceMismatch):
        cutover.old.search("reverse bias", project_id=PROJECT, space=cutover.new.space)
    with pytest.raises(EmbeddingSpaceMismatch):
        cutover.new.search("reverse bias", project_id=PROJECT, space=cutover.old.space)


def test_the_migration_changes_no_evidence_identity_or_body():
    """The model migrated; the evidence did not.

    This is the claim EVI-007 has to be able to make and EVI-010 makes possible: swapping an
    embedding model is an index operation. If it could move an evidence identity, the scientific
    record would depend on an embedding version -- which is precisely what ADR-0011 separates.
    """
    cutover = _cutover()
    cutover.measure(_cases(), project_id=PROJECT)
    cutover.promote()

    for unit in _units():
        old_rep = cutover.old.representation_for(unit.evidence_unit_id, PROJECT)
        new_rep = cutover.new.representation_for(unit.evidence_unit_id, PROJECT)
        assert old_rep is not None and new_rep is not None
        assert old_rep.evidence_unit_id == new_rep.evidence_unit_id == unit.evidence_unit_id
        assert old_rep.payload_digest == new_rep.payload_digest
        assert new_rep.embedding_version == "2.0.0"
        assert old_rep.embedding_version == "1.0.0"
