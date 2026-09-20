"""Candidate retrieval, and the seam EVI-007's vector index will plug into — §6.22, §17.25.

WHAT THIS SLICE BUILDS AND WHAT IT DOES NOT. No embedding index. EVI-007's dual-index migration
is a later slice, and building a vector store now would fix the wrong thing first. What is built
is the *boundary*: retrieval returns identifiers and scores, and the canonical evidence body is
re-loaded from the store by identity before anything becomes evidence.

THE ATTACK THE BOUNDARY CLOSES. An index holds a copy of the text. If admission reads that copy,
then whoever can write to the index can write scientific evidence -- and the resulting attestation
is well-formed, correctly statused, and cites a real locator in a real document. Nothing about it
looks wrong except that the document does not say it. So ``RetrievalCandidate`` has no body field
to read, and ``CandidateResolver`` re-loads every unit by ``evidence_unit_id``.

WHY A DIGEST COMPARISON EXISTS AT ALL, given that the canonical body always wins. Not to decide
anything -- to make a stale or tampered index *visible*. Without it the two simply disagree in
silence and the only symptom is that retrieval ranks things oddly. ``IndexDivergence`` is a
report; the evidence is unaffected either way.

ONE SOURCE OF TRUTH PER RULE. This module does no authority comparison, no independence counting,
no bundle hashing and no admission. Those live in ``AuthorityPolicy``, ``independence``,
``EvidenceBundle`` and ``EvidenceAdmissionGate`` respectively, and a retriever that re-implemented
any of them would be a second place they could be got wrong.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from lab_brain.core.models.enums import RetrievalIndexKind
from lab_brain.core.models.evidence_unit import (
    EvidenceUnit,
    RetrievalCandidate,
    RetrievalRepresentation,
)
from lab_brain.core.models.identifiers import compute_content_hash

_TOKEN = re.compile(r"[a-z0-9]+(?:[./][a-z0-9]+)*")

#: Okapi BM25 constants, at their standard values. Deliberately not tuned: T-EVI-010 compares two
#: *segmentation* strategies, and a retriever tuned on the fixture would move the measurement it
#: is supposed to be taking.
_BM25_K1 = 1.5
_BM25_B = 0.75


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric tokens, keeping ``0.515`` and ``pf/mm`` intact.

    Splitting on every punctuation mark would turn "0.515" into "0" and "515" and make a numeric
    query match every number in the corpus -- which matters here, because the fixture's questions
    are about specific measured values.
    """
    return _TOKEN.findall(text.lower())


@dataclass(frozen=True)
class IndexDivergence:
    """The index's copy no longer matches the canonical body. A report, never a refusal."""

    evidence_unit_id: str
    representation_id: str
    indexed_digest: str
    canonical_digest: str


class LexicalEvidenceIndex:
    """A deterministic BM25 index over canonical evidence units.

    Deterministic because T-EVI-010's fixture is locked: the same units and the same query must
    produce the same ranking on every run, or a regression in segmentation would be
    indistinguishable from retrieval noise.

    ``index_kind`` is LEXICAL, so ``RetrievalRepresentation`` carries no embedding fields -- and
    its validator refuses them, because recording an embedding space on a lexical index invites a
    later cosine comparison against a space nothing was embedded in (EVI-007).
    """

    def __init__(self, index_id: str = "idx:lexical:v1") -> None:
        self._index_id = index_id
        self._representations: dict[str, RetrievalRepresentation] = {}
        self._tokens: dict[str, list[str]] = {}
        self._document_frequency: Counter[str] = Counter()
        self._total_length = 0

    @property
    def index_id(self) -> str:
        return self._index_id

    @property
    def size(self) -> int:
        return len(self._representations)

    def add(self, unit: EvidenceUnit) -> RetrievalRepresentation:
        """Index one canonical unit.

        The representation records the digest of what was indexed. Note that it indexes
        ``interpretive_text`` -- body plus inherited context -- so a fallback sub-unit is findable
        by the conditions it inherited rather than only by the tokens in its own slice.
        """
        indexed_text = unit.interpretive_text
        representation = RetrievalRepresentation(
            evidence_unit_id=unit.evidence_unit_id,
            project_id=unit.project_id,
            index_id=self._index_id,
            index_kind=RetrievalIndexKind.LEXICAL,
            payload_digest=compute_content_hash(indexed_text.encode("utf-8")),
        )
        tokens = tokenize(indexed_text)
        self._representations[unit.evidence_unit_id] = representation
        self._tokens[unit.evidence_unit_id] = tokens
        self._total_length += len(tokens)
        for term in set(tokens):
            self._document_frequency[term] += 1
        return representation

    def add_all(self, units: Iterable[EvidenceUnit]) -> tuple[RetrievalRepresentation, ...]:
        return tuple(self.add(unit) for unit in units)

    def drop(self) -> None:
        """Delete the whole index.

        Exists so the test that rebuilding an index changes no evidence identity has something to
        call. §17.25: dropping every representation for an index MUST NOT touch any EvidenceUnit
        -- and the only way to show that is to actually drop one.
        """
        self._representations.clear()
        self._tokens.clear()
        self._document_frequency.clear()
        self._total_length = 0

    def search(
        self, query: str, *, project_id: str, limit: int = 10
    ) -> tuple[RetrievalCandidate, ...]:
        """Rank units by BM25. Returns identifiers and scores — deliberately not bodies.

        ``project_id`` filters before scoring rather than after, so a cross-project unit is never
        ranked, never scored and never leaks through a result count (SEC-002).
        """
        if limit <= 0:
            raise ValueError("limit must be positive; traversal MUST be bounded (§17.12)")

        scoped = {
            unit_id: representation
            for unit_id, representation in self._representations.items()
            if representation.project_id == project_id
        }
        if not scoped:
            return ()

        query_terms = tokenize(query)
        average_length = self._total_length / max(len(self._representations), 1)
        scored: list[tuple[float, str]] = []

        for unit_id in scoped:
            tokens = self._tokens[unit_id]
            counts = Counter(tokens)
            length = len(tokens)
            score = 0.0
            for term in query_terms:
                frequency = counts.get(term, 0)
                if not frequency:
                    continue
                document_frequency = self._document_frequency[term]
                idf = math.log(
                    1
                    + (len(self._representations) - document_frequency + 0.5)
                    / (document_frequency + 0.5)
                )
                denominator = frequency + _BM25_K1 * (
                    1 - _BM25_B + _BM25_B * length / max(average_length, 1e-9)
                )
                score += idf * (frequency * (_BM25_K1 + 1)) / denominator
            if score > 0:
                scored.append((score, unit_id))

        # Sort by score then by id: ties must break the same way on every run, or a locked
        # fixture's expected ranking is not actually locked.
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        return tuple(
            RetrievalCandidate(
                evidence_unit_id=unit_id,
                representation_id=scoped[unit_id].representation_id,
                project_id=project_id,
                score=score,
                rank=position + 1,
            )
            for position, (score, unit_id) in enumerate(scored[:limit])
        )

    def representation_for(self, evidence_unit_id: str) -> RetrievalRepresentation | None:
        return self._representations.get(evidence_unit_id)

    def tamper(self, evidence_unit_id: str, replacement: str) -> None:
        """Overwrite what the index holds for a unit, leaving the canonical unit untouched.

        A test affordance, and it is the only way to build the negative case honestly: the attack
        is that the index and the canonical store disagree, so the test has to be able to make
        them disagree. Named ``tamper`` rather than ``update`` so its presence in a non-test
        caller is obvious in review.

        Both halves of the representation are rewritten -- the searchable tokens *and* the
        recorded ``payload_digest``. Changing only the tokens would model an attacker who
        rewrote the index but politely left a digest that convicts them, and the resulting test
        would pass while proving nothing about detection.
        """
        representation = self._representations.get(evidence_unit_id)
        if representation is None:
            raise KeyError(evidence_unit_id)
        self._tokens[evidence_unit_id] = tokenize(replacement)
        self._representations[evidence_unit_id] = representation.model_copy(
            update={"payload_digest": compute_content_hash(replacement.encode("utf-8"))}
        )


@dataclass(frozen=True)
class ResolvedCandidate:
    """A candidate paired with the canonical unit that was re-loaded for it."""

    candidate: RetrievalCandidate
    unit: EvidenceUnit

    @property
    def body(self) -> str:
        """Always the canonical body. There is no other body to return."""
        return self.unit.body


class CandidateResolver:
    """Turns candidates into canonical units by re-loading each one by identity.

    This is the seam §6.22 requires between retrieval and admission. It is a separate object from
    the index on purpose: the index can be replaced with a dense one (EVI-007) and this does not
    change, because it never asked the index for content in the first place.
    """

    def __init__(self, load_unit: Callable[[str], EvidenceUnit | None]) -> None:
        self._load_unit = load_unit

    def resolve(
        self,
        candidates: Sequence[RetrievalCandidate],
        *,
        index: LexicalEvidenceIndex | None = None,
    ) -> tuple[tuple[ResolvedCandidate, ...], tuple[IndexDivergence, ...]]:
        """Re-load each candidate's canonical unit.

        Returns the resolved candidates and any divergences found. A candidate that does not
        resolve is dropped rather than raising: an index row pointing at a deleted unit is an
        index maintenance problem, and failing the whole retrieval would turn it into an outage.
        Admission refuses an unresolvable unit separately, so nothing slips through.
        """
        resolved: list[ResolvedCandidate] = []
        divergences: list[IndexDivergence] = []

        for candidate in candidates:
            unit = self._load_unit(candidate.evidence_unit_id)
            if unit is None:
                continue
            if unit.project_id != candidate.project_id:
                # Defence in depth: the index already filters by project. A candidate that
                # disagrees means an index built against another project's units, and answering
                # it would be the R-7 leak through a different door.
                continue
            resolved.append(ResolvedCandidate(candidate=candidate, unit=unit))

            if index is not None:
                representation = index.representation_for(unit.evidence_unit_id)
                if representation is None:
                    continue
                canonical = compute_content_hash(unit.interpretive_text.encode("utf-8"))
                if representation.payload_digest != canonical:
                    divergences.append(
                        IndexDivergence(
                            evidence_unit_id=unit.evidence_unit_id,
                            representation_id=representation.representation_id,
                            indexed_digest=representation.payload_digest,
                            canonical_digest=canonical,
                        )
                    )

        return tuple(resolved), tuple(divergences)


__all__ = [
    "CandidateResolver",
    "IndexDivergence",
    "LexicalEvidenceIndex",
    "ResolvedCandidate",
    "tokenize",
]
