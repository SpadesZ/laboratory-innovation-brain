"""T-EVI-004 — source-work identity and independence counting (EVI-004, §6.17, §17.22).

Pass condition (§26):

    preprint/journal/review fixture resolve 為同一 source work；DEPENDENCE_UNKNOWN fixture
    contributes 0 to independent count until resolved; promotion requiring independence stays
    blocked.

The failure being prevented, from §6.2: one measurement cited four times reading as five
independent supports. Nothing in the record looks wrong -- there really are five attestations,
each with a real source and a real locator -- which is why the count has to be computed from
resolved identity rather than from how many rows exist.
"""

from __future__ import annotations

import pytest

from lab_brain.core.models import (
    IndependenceBasis,
    IndependenceRelation,
    SourceWork,
    SourceWorkType,
    TrustClass,
    WorkIdentifier,
)
from lab_brain.evidence.independence import count_independent_attestations
from lab_brain.ingestion.source_work_resolution import (
    SourceWorkResolver,
    WorkMatchBasis,
    independence_relation_for,
    normalise_title,
)

TITLE = "Bias-dependent junction capacitance in a lateral PN phase shifter"
AUTHORS = ("R. Kuo", "A. Lin", "M. Sato")

PREPRINT_ARTIFACT = "art:sha256:" + "1" * 64
JOURNAL_ARTIFACT = "art:sha256:" + "2" * 64
REVIEW_ARTIFACT = "art:sha256:" + "3" * 64


class _Store:
    """A minimal SourceWork store with the three lookups the resolver needs."""

    def __init__(self) -> None:
        self.works: dict[str, SourceWork] = {}

    def add(self, work: SourceWork) -> SourceWork:
        self.works[work.source_work_id] = work
        return work

    def find_by_identifier(self, scheme: str, value: str) -> SourceWork | None:
        needle = str(WorkIdentifier(scheme=scheme, value=value))
        for work in self.works.values():
            if needle in work.identifier_keys:
                return work
        return None

    def find_by_artifact(self, artifact_id: str) -> tuple[SourceWork, ...]:
        return tuple(
            work for work in self.works.values() if artifact_id in work.manifestation_artifact_ids
        )

    def all_works(self) -> list[SourceWork]:
        return list(self.works.values())

    def resolver(self) -> SourceWorkResolver:
        return SourceWorkResolver(
            find_by_identifier=self.find_by_identifier,
            find_by_artifact=self.find_by_artifact,
            all_works=self.all_works,
            add=self.add,
        )


def _work(
    work_type: SourceWorkType,
    identifiers: tuple[WorkIdentifier, ...],
    *,
    title: str = TITLE,
    trust: TrustClass = TrustClass.PREPRINT,
) -> SourceWork:
    return SourceWork(
        work_type=work_type,
        title=title,
        identifiers=identifiers,
        authors=AUTHORS,
        trust_class=trust,
    )


# ---------------------------------------------------------------------------
# preprint / journal / review resolve to one work
# ---------------------------------------------------------------------------


@pytest.mark.requirement("EVI-004")
@pytest.mark.spec_test("T-EVI-004")
def test_a_preprint_and_its_journal_version_resolve_to_one_work():
    """The DOI is shared, so the two manifestations are one work.

    Note what is NOT used to decide this: the filename, the bytes, the page numbers or the venue.
    §6.2 is explicit that the point of SourceWork is to survive those differing.
    """
    store = _Store()
    resolver = store.resolver()
    doi = WorkIdentifier(scheme="doi", value="10.1000/lab-brain-demo-001")

    first = resolver.resolve(_work(SourceWorkType.PREPRINT, (doi,)), artifact_id=PREPRINT_ARTIFACT)
    assert first.created
    assert first.basis is WorkMatchBasis.NONE

    second = resolver.resolve(
        _work(SourceWorkType.JOURNAL_ARTICLE, (doi,), trust=TrustClass.PEER_REVIEWED),
        artifact_id=JOURNAL_ARTIFACT,
    )
    assert not second.created
    assert second.basis is WorkMatchBasis.IDENTIFIER
    assert second.duplicate_of_source_work_id == first.source_work.source_work_id
    assert set(second.source_work.manifestation_artifact_ids) == {
        PREPRINT_ARTIFACT,
        JOURNAL_ARTIFACT,
    }


@pytest.mark.requirement("EVI-004")
@pytest.mark.spec_test("T-EVI-004")
def test_a_same_work_duplicate_still_creates_an_attestation():
    """§17.22, and the counter-intuitive half.

    A preprint and its journal version are different documents -- different bytes, different
    pages, often different numbers after review. The second is a distinct witnessing act and
    MUST be recorded. What it is not is a second independent support.
    """
    store = _Store()
    resolver = store.resolver()
    doi = WorkIdentifier(scheme="doi", value="10.1000/x")
    resolver.resolve(_work(SourceWorkType.PREPRINT, (doi,)), artifact_id=PREPRINT_ARTIFACT)
    second = resolver.resolve(
        _work(SourceWorkType.JOURNAL_ARTICLE, (doi,)), artifact_id=JOURNAL_ARTIFACT
    )

    assert second.is_same_work_duplicate
    assert second.must_still_create_attestation, (
        "a same-work duplicate was marked discardable; silently dropping it corrupts "
        "corroboration counting in the opposite direction (§17.22)"
    )
    assert independence_relation_for(second) is IndependenceRelation.SAME_WORK


@pytest.mark.requirement("EVI-004")
@pytest.mark.spec_test("T-EVI-004")
def test_byte_identical_bytes_create_no_new_attestation():
    """The other duplicate kind. Identical bytes carry no new information."""
    store = _Store()
    resolver = store.resolver()
    doi = WorkIdentifier(scheme="doi", value="10.1000/x")
    resolver.resolve(_work(SourceWorkType.PREPRINT, (doi,)), artifact_id=PREPRINT_ARTIFACT)
    again = resolver.resolve(_work(SourceWorkType.PREPRINT, (doi,)), artifact_id=PREPRINT_ARTIFACT)

    assert again.duplicate_of_artifact_id == PREPRINT_ARTIFACT
    assert not again.must_still_create_attestation


@pytest.mark.requirement("EVI-004")
@pytest.mark.spec_test("T-EVI-004")
def test_a_review_citing_the_work_is_a_different_work():
    """A review is its own work with its own DOI -- and CITES, not INDEPENDENT.

    Resolution says "these are two works", which is true. Independence is a separate question,
    answered by the relation between them, and the counting test below is where that matters.
    """
    store = _Store()
    resolver = store.resolver()
    original = resolver.resolve(
        _work(SourceWorkType.PREPRINT, (WorkIdentifier(scheme="doi", value="10.1000/x"),)),
        artifact_id=PREPRINT_ARTIFACT,
    )
    review = resolver.resolve(
        _work(
            SourceWorkType.JOURNAL_ARTICLE,
            (WorkIdentifier(scheme="doi", value="10.1000/review-y"),),
            title="A review of silicon phase shifter capacitance",
        ),
        artifact_id=REVIEW_ARTIFACT,
    )
    assert review.created
    assert review.source_work.source_work_id != original.source_work.source_work_id


@pytest.mark.requirement("EVI-004")
@pytest.mark.spec_test("T-EVI-004")
def test_neither_filename_nor_byte_identity_is_work_identity():
    """Two genuinely different papers with the same filename are two works."""
    store = _Store()
    resolver = store.resolver()
    first = resolver.resolve(
        _work(
            SourceWorkType.PREPRINT,
            (WorkIdentifier(scheme="arxiv", value="2601.00001"),),
            title="First paper",
        ),
        artifact_id=PREPRINT_ARTIFACT,
    )
    second = resolver.resolve(
        _work(
            SourceWorkType.PREPRINT,
            (WorkIdentifier(scheme="arxiv", value="2601.00002"),),
            title="Second paper",
        ),
        artifact_id=JOURNAL_ARTIFACT,
    )
    assert first.source_work.source_work_id != second.source_work.source_work_id


@pytest.mark.requirement("EVI-004")
@pytest.mark.spec_test("T-EVI-004")
def test_a_doi_matches_case_insensitively():
    """DOIs are case-insensitive; comparing them case-sensitively re-splits one work into two."""
    assert normalise_title("The Bias Dependence") == normalise_title("bias dependence")
    store = _Store()
    resolver = store.resolver()
    resolver.resolve(
        _work(SourceWorkType.PREPRINT, (WorkIdentifier(scheme="doi", value="10.1000/ABC"),)),
        artifact_id=PREPRINT_ARTIFACT,
    )
    second = resolver.resolve(
        _work(SourceWorkType.JOURNAL_ARTICLE, (WorkIdentifier(scheme="DOI", value="10.1000/abc"),)),
        artifact_id=JOURNAL_ARTIFACT,
    )
    assert second.basis is WorkMatchBasis.IDENTIFIER


@pytest.mark.requirement("EVI-004")
@pytest.mark.spec_test("T-EVI-004")
def test_a_title_author_match_is_flagged_for_review_not_merged():
    """§6.17's reasoning, applied to identity.

    Guessing two works are the same inflates nothing. Guessing they are *different* inflates
    corroboration -- so an unresolved heuristic match maps to UNKNOWN, which contributes 0, and
    a human resolves it.
    """
    store = _Store()
    resolver = store.resolver()
    resolver.resolve(
        _work(SourceWorkType.PREPRINT, (WorkIdentifier(scheme="arxiv", value="2601.1"),)),
        artifact_id=PREPRINT_ARTIFACT,
    )
    second = resolver.resolve(
        _work(SourceWorkType.JOURNAL_ARTICLE, (WorkIdentifier(scheme="doi", value="10.1/z"),)),
        artifact_id=JOURNAL_ARTIFACT,
    )
    assert second.basis is WorkMatchBasis.TITLE_AUTHOR_HEURISTIC
    assert second.needs_review
    assert independence_relation_for(second) is IndependenceRelation.UNKNOWN, (
        "an unresolved heuristic match was treated as independent; §6.17 fixes UNKNOWN's "
        "contribution at 0 rather than letting the guess be made one layer down"
    )


# ---------------------------------------------------------------------------
# Counting
# ---------------------------------------------------------------------------


@pytest.mark.requirement("EVI-004")
@pytest.mark.spec_test("T-EVI-004")
def test_five_attestations_of_one_work_count_as_one():
    """§6.2's exact scenario: one measurement cited four times is not five supports."""
    count = count_independent_attestations(
        [f"att:{n}" for n in range(5)],
        source_work_of={f"att:{n}": "swk:one-work" for n in range(5)},
        relations={},
    )
    assert count.independent == 1
    assert count.dependent == 4


@pytest.mark.requirement("EVI-004")
@pytest.mark.spec_test("T-EVI-004")
def test_dependence_unknown_contributes_zero():
    """§6.17, stated as a fixed number rather than a weighting."""
    count = count_independent_attestations(
        ["att:1", "att:2"],
        source_work_of={"att:1": "swk:a", "att:2": "swk:b"},
        relations={("att:1", "att:2"): IndependenceRelation.UNKNOWN},
    )
    assert count.independent == 1
    assert count.unknown == 1
    assert count.shortfall_is_resolvable, (
        "a shortfall caused by unresolved dependence must be distinguishable from one caused by "
        "absent evidence -- they lead to NEED_HUMAN_REVIEW and NEED_MORE_EVIDENCE respectively"
    )


@pytest.mark.requirement("EVI-004")
@pytest.mark.spec_test("T-EVI-004")
def test_a_promotion_requiring_two_independent_supports_stays_blocked():
    """The consequence §26 names: promotion requiring independence stays blocked."""
    count = count_independent_attestations(
        ["att:preprint", "att:journal"],
        source_work_of={"att:preprint": "swk:one", "att:journal": "swk:one"},
        relations={},
    )
    assert count.independent < 2
    assert not count.shortfall_is_resolvable, (
        "the shortfall is resolved -- both attestations are known to be the same work -- so the "
        "remedy is more evidence, not more review"
    )


@pytest.mark.requirement("EVI-004")
@pytest.mark.spec_test("T-EVI-004")
def test_a_citation_is_not_an_independent_support():
    """CITES and DERIVED_FROM fold into the work they point at."""
    count = count_independent_attestations(
        ["att:original", "att:citing"],
        source_work_of={"att:original": "swk:a", "att:citing": "swk:b"},
        relations={("att:citing", "att:original"): IndependenceRelation.CITES},
    )
    assert count.independent == 1
    assert count.dependent == 1


@pytest.mark.requirement("EVI-004")
@pytest.mark.spec_test("T-EVI-004")
def test_genuinely_independent_works_count_separately():
    """The positive control. Without it every test above passes on a function returning 1."""
    count = count_independent_attestations(
        ["att:a", "att:b", "att:c"],
        source_work_of={"att:a": "swk:a", "att:b": "swk:b", "att:c": "swk:c"},
        relations={},
    )
    assert count.independent == 3
    assert count.unknown == 0


@pytest.mark.requirement("EVI-004")
@pytest.mark.spec_test("T-EVI-004")
def test_an_attestation_with_no_resolved_work_is_unknown_not_independent():
    """ "We did not resolve where this came from" is not evidence that it is new."""
    count = count_independent_attestations(
        ["att:a", "att:unresolved"],
        source_work_of={"att:a": "swk:a", "att:unresolved": None},
        relations={},
    )
    assert count.independent == 1
    assert count.unknown == 1


@pytest.mark.requirement("EVI-004")
@pytest.mark.spec_test("T-EVI-004")
def test_a_basis_stronger_than_work_refuses_to_produce_a_count():
    """§6.17: v3.3 models WORK-level independence only.

    A policy declaring GROUP or INSTRUMENT must escalate rather than pretend the requirement is
    met, so this refuses to hand back a number that would be read as one.
    """
    with pytest.raises(ValueError, match=r"not implemented in v3\.3"):
        count_independent_attestations(
            ["att:a"],
            source_work_of={"att:a": "swk:a"},
            relations={},
            basis=IndependenceBasis.INSTRUMENT,
        )
