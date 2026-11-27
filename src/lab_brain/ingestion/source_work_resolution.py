"""Source-work identity and independence counting — EVI-004, §6.17, §6.21, §17.22.

THE FAILURE THIS PREVENTS. §6.2 states it directly:

    同一個 claim 被 5 篇論文引用，若直接產生 5 筆互不相關的 evidence，系統會把「1 次量測被轉引
    4 次」誤算成「5 個獨立支持」。這會系統性污染每一次信念更新。

One measurement, cited four times, reads as five independent supports. Every belief update after
that is computed on a corroboration count that was never true, and nothing in the record looks
wrong -- there really are five attestations, each with a real source and a real locator.

TWO DUPLICATES, AND §17.22 IS EMPHATIC THEY ARE NOT THE SAME THING::

    duplicate_of_artifact_id     identical bytes -> no new scientific value; safe to skip
    duplicate_of_source_work_id  same work, different bytes (preprint vs journal vs mirror)
                                 -> NOT a discardable duplicate. MUST still create
                                    SourceWork/Attestation so EVI-004 can resolve independence.
                                    Silently dropping it corrupts corroboration counting.

The second is the counter-intuitive one and it is where implementations go wrong. A preprint and
its journal version are *different documents* -- different bytes, different page numbers, often
different numbers after review. The journal version is a distinct Attestation and must be stored.
What it is not is a second independent support.

WHAT MAY NOT BE USED AS WORK IDENTITY. Filename, and byte identity. A filename is a property of
whoever downloaded it; byte identity answers a different question, and two manifestations of one
work never share bytes. Identity resolution here is by declared external identifier, with title
and author as a *weaker* basis that produces a flag rather than a merge.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from lab_brain.core.models.enums import IndependenceRelation
from lab_brain.core.models.source_work import SourceWork, WorkIdentifier


class WorkMatchBasis(StrEnum):
    """How two manifestations were judged to be the same work. Ordered strongest first.

    Recorded on the resolution rather than collapsed to a boolean, because the bases differ in
    what they license. A DOI match is a fact about a registry; a title match is a guess, and
    §6.17 says a guess contributes zero rather than being treated as resolved.
    """

    #: Same registered identifier (DOI, arXiv id, ISBN). Authoritative.
    IDENTIFIER = "IDENTIFIER"
    #: One work explicitly declares the other as its preprint/published counterpart.
    DECLARED_VERSION_OF = "DECLARED_VERSION_OF"
    #: Normalised title and author overlap. A candidate, never an automatic merge.
    TITLE_AUTHOR_HEURISTIC = "TITLE_AUTHOR_HEURISTIC"
    #: No basis found.
    NONE = "NONE"


@dataclass(frozen=True)
class SourceWorkResolution:
    """The outcome of resolving one incoming manifestation against the store."""

    source_work: SourceWork
    #: True when this manifestation created a new SourceWork rather than joining one.
    created: bool
    basis: WorkMatchBasis
    #: Set when the same work was already present under different bytes. §17.22's
    #: ``duplicate_of_source_work_id`` -- NOT a reason to discard the manifestation.
    duplicate_of_source_work_id: str | None = None
    #: Set when the exact bytes were already stored. §17.22's ``duplicate_of_artifact_id``.
    duplicate_of_artifact_id: str | None = None
    #: A TITLE_AUTHOR_HEURISTIC match that needs a human. Surfaced rather than acted on.
    needs_review: bool = False

    @property
    def is_same_work_duplicate(self) -> bool:
        return self.duplicate_of_source_work_id is not None

    @property
    def must_still_create_attestation(self) -> bool:
        """§17.22: a same-work duplicate is still a distinct witnessing act.

        The whole point of the distinction. Byte-identical bytes carry no new information;
        a different manifestation of the same work reports it in its own words, at its own
        locator, sometimes with different numbers.
        """
        return self.duplicate_of_artifact_id is None


_ARTICLE_PREFIX = re.compile(r"^(?:the|a|an)\s+", re.IGNORECASE)
_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9 ]+")
_WHITESPACE = re.compile(r"\s+")


def normalise_title(title: str) -> str:
    """Fold a title to a comparable form.

    Only for the heuristic basis, and the heuristic never merges on its own. Case, punctuation
    and a leading article are the differences that appear between a preprint and its published
    version; anything more aggressive starts matching genuinely different papers.
    """
    folded = _NON_ALPHANUMERIC.sub(" ", title.lower())
    folded = _ARTICLE_PREFIX.sub("", folded.strip())
    return _WHITESPACE.sub(" ", folded).strip()


def surname_of(author: str) -> str:
    """Last whitespace-separated token, lowercased. Robust to "J. Smith" vs "Smith, J."."""
    cleaned = author.replace(",", " ").strip()
    return cleaned.split()[-1].lower() if cleaned else ""


class SourceWorkResolver:
    """Resolves an incoming manifestation to the work it manifests (EVI-004)."""

    def __init__(
        self,
        *,
        find_by_identifier: Callable[[str, str], SourceWork | None],
        find_by_artifact: Callable[[str], tuple[SourceWork, ...]],
        all_works: Callable[[], Sequence[SourceWork]],
        add: Callable[[SourceWork], SourceWork],
        #: How much of the author list must agree for the heuristic to fire. 0.6 rather than 1.0
        #: because author lists legitimately change between preprint and publication.
        author_overlap_threshold: float = 0.6,
    ) -> None:
        self._find_by_identifier = find_by_identifier
        self._find_by_artifact = find_by_artifact
        self._all_works = all_works
        self._add = add
        self._author_overlap_threshold = author_overlap_threshold

    def resolve(self, incoming: SourceWork, *, artifact_id: str) -> SourceWorkResolution:
        """Resolve ``incoming`` against what is already stored.

        Order matters: byte identity first (cheapest and most decisive), then registered
        identifier, then the heuristic. Each step's outcome is different, not merely more or less
        confident.
        """
        # 1. Identical bytes. Not "the same work" -- literally the same file, already recorded.
        for existing in self._find_by_artifact(artifact_id):
            return SourceWorkResolution(
                source_work=existing,
                created=False,
                basis=WorkMatchBasis.IDENTIFIER,
                duplicate_of_artifact_id=artifact_id,
            )

        # 2. A registered identifier. Authoritative, and the only basis that merges automatically.
        for identifier in incoming.identifiers:
            match = self._find_by_identifier(identifier.scheme, identifier.value)
            if match is not None and match.source_work_id != incoming.source_work_id:
                return SourceWorkResolution(
                    source_work=self._attach(match, artifact_id, incoming.identifiers),
                    created=False,
                    basis=WorkMatchBasis.IDENTIFIER,
                    duplicate_of_source_work_id=match.source_work_id,
                )

        # 3. Title + author. A candidate, surfaced for review rather than merged. §6.17's
        #    DEPENDENCE_UNKNOWN reasoning applies: guessing that two works are the same inflates
        #    nothing, but guessing they are *different* inflates corroboration -- so the flag is
        #    raised and the count stays conservative until a human resolves it.
        candidate = self._heuristic_match(incoming)
        if candidate is not None:
            stored = self._add(
                incoming.model_copy(update={"manifestation_artifact_ids": (artifact_id,)})
            )
            return SourceWorkResolution(
                source_work=stored,
                created=True,
                basis=WorkMatchBasis.TITLE_AUTHOR_HEURISTIC,
                duplicate_of_source_work_id=candidate.source_work_id,
                needs_review=True,
            )

        stored = self._add(
            incoming.model_copy(update={"manifestation_artifact_ids": (artifact_id,)})
        )
        return SourceWorkResolution(source_work=stored, created=True, basis=WorkMatchBasis.NONE)

    def _attach(
        self,
        work: SourceWork,
        artifact_id: str,
        identifiers: tuple[WorkIdentifier, ...],
    ) -> SourceWork:
        """Record a new manifestation against an existing work.

        A preprint's arXiv id and the journal version's DOI both end up on one work, which is
        what makes the *next* manifestation resolvable by either.
        """
        merged_artifacts = tuple(dict.fromkeys([*work.manifestation_artifact_ids, artifact_id]))
        known = {str(identifier) for identifier in work.identifiers}
        merged_identifiers = work.identifiers + tuple(
            identifier for identifier in identifiers if str(identifier) not in known
        )
        return self._add(
            work.model_copy(
                update={
                    "manifestation_artifact_ids": merged_artifacts,
                    "identifiers": merged_identifiers,
                }
            )
        )

    def _heuristic_match(self, incoming: SourceWork) -> SourceWork | None:
        incoming_title = normalise_title(incoming.title)
        incoming_authors = {surname_of(author) for author in incoming.authors if author}
        for existing in self._all_works():
            if existing.source_work_id == incoming.source_work_id:
                continue
            if normalise_title(existing.title) != incoming_title:
                continue
            if not incoming_authors:
                return existing
            existing_authors = {surname_of(a) for a in existing.authors if a}
            if not existing_authors:
                return existing
            overlap = len(incoming_authors & existing_authors) / len(
                incoming_authors | existing_authors
            )
            if overlap >= self._author_overlap_threshold:
                return existing
        return None


def independence_relation_for(
    resolution: SourceWorkResolution,
) -> IndependenceRelation:
    """Map a resolution to the independence relation it licenses (§6.17).

    The load-bearing line is the last one. An *unresolved* heuristic match is
    ``UNKNOWN``, not ``INDEPENDENT``: §6.17 fixes UNKNOWN's contribution at 0 and requires
    ``NEED_MORE_EVIDENCE``/``NEED_HUMAN_REVIEW`` rather than a guess, and returning INDEPENDENT
    here would be that guess made one layer down where no policy can see it.
    """
    if resolution.duplicate_of_artifact_id is not None:
        return IndependenceRelation.SAME_WORK
    if resolution.needs_review:
        return IndependenceRelation.UNKNOWN
    if resolution.duplicate_of_source_work_id is not None:
        return IndependenceRelation.SAME_WORK
    return IndependenceRelation.INDEPENDENT


__all__ = [
    "SourceWorkResolution",
    "SourceWorkResolver",
    "WorkMatchBasis",
    "independence_relation_for",
    "normalise_title",
    "surname_of",
]
