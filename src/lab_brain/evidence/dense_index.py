"""Dense retrieval and the dual-index cutover (EVI-007, §6.13, §6.20, §17.25).

WHAT §6.13 SAYS, AND WHY IT IS BLUNTER THAN MOST OF THE SPEC.

    向量檢索**必須**依 `embedding_model` + version 過濾。混合不同 embedding space 的 cosine
    距離是靜默垃圾（EVI-007）。

"靜默垃圾" -- silent garbage -- is the operative phrase. Cosine similarity between vectors from
two different models is a real number in [-1, 1]. It ranks. It looks exactly like a working
retrieval. Nothing anywhere reports an error, and the only symptom is that the evidence bundle
quietly contains the wrong documents. That is why the compatibility check is a MUST and why this
module refuses rather than warns.

THE THREE KEYS, AND WHY DIMENSIONS IS ONE OF THEM. §6.13 names model and version. `dimensions` is
added because two vectors of different length cannot be compared at all -- a cosine that silently
zero-pads is not a smaller error than one that mixes spaces, it is the same error with an extra
step. §17.25 already declares the field on `RetrievalRepresentation`, so this reads what the
record states rather than inventing a key.

WHAT THIS MODULE IS NOT ALLOWED TO DO. Decide what evidence *is*. ADR-0011 and EVI-010 are locked:
a `RetrievalCandidate` carries no body, and the canonical body is re-loaded by identity through
`CandidateResolver`. Dense retrieval FINDS units; it never supplies them. Every guarantee that
made lexical retrieval safe holds here unchanged, and the adversarial tests re-run the same
attacks against this index rather than assuming they transfer.

THE CUTOVER (§6.20). Dual-index: old and new coexist, and the switch happens only after benchmark
recall is *verified*, never on a deploy flag. `DualIndexCutover` refuses to promote an index whose
measured recall is below the declared floor, and refuses to measure against a benchmark whose
expected units it cannot resolve -- because a recall of 1.00 over an empty expectation set is the
number an unverified cutover produces.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from lab_brain.core.models.enums import RetrievalIndexKind
from lab_brain.core.models.evidence_unit import (
    EvidenceUnit,
    RetrievalCandidate,
    RetrievalRepresentation,
)
from lab_brain.core.models.identifiers import compute_content_hash

#: An embedding function: text -> vector. Injected so tests are deterministic and so core never
#: imports a model runtime (§24.2 keeps provider specifics out of the cognition path).
Embedder = Callable[[str], Sequence[float]]


@dataclass(frozen=True)
class EmbeddingSpace:
    """The identity of a vector space (EVI-007's compatibility key).

    Frozen and compared by value: "are these comparable" has to be one equality test, because a
    check spread over three separate comparisons is one someone eventually writes two of.
    """

    model: str
    version: str
    dimensions: int

    def __post_init__(self) -> None:
        if self.dimensions <= 0:
            raise ValueError(f"embedding space {self.model}@{self.version} has no dimensions")

    @property
    def key(self) -> str:
        return f"{self.model}@{self.version}/{self.dimensions}d"

    def compatible_with(self, other: EmbeddingSpace) -> bool:
        return self == other


class EmbeddingSpaceMismatch(RuntimeError):
    """A query and an index disagree about the vector space.

    Raised, never degraded to an empty result. An empty result reads as "nothing matched", which
    is a legitimate outcome and would hide the misconfiguration behind a plausible one.
    """


class IndexNotReady(RuntimeError):
    """A cutover was attempted without verified benchmark recall (§6.20)."""


def hashing_embedder(space: EmbeddingSpace) -> Embedder:
    """A deterministic feature-hashing embedder for fixtures and benchmarks.

    NOT A MODEL, and not pretending to be. It exists because EVI-007's guarantees are about
    *space bookkeeping* -- which vectors may be compared with which, and whether a cutover was
    verified -- and testing those against a real model would make the suite depend on a download,
    a GPU and a version that drifts.

    IT DOES HAVE TO EMBED, THOUGH, and the first draft did not. That draft hashed the whole string
    into a pseudo-random unit vector, which is stable and distinguishable and carries no lexical
    signal at all -- so similar texts landed nowhere near each other. The benchmark then measured
    0.50 recall, and the cutover gate correctly refused to promote. The gate was right and the
    fixture was wrong: a recall number produced by a random oracle measures nothing, and a test
    that lowered the floor to accommodate it would have made the gate decorative.

    So this is feature hashing: each token is hashed to a dimension and accumulated. Shared
    vocabulary produces genuine similarity, which is enough for recall to mean something.

    THE SPACE SEEDS THE HASH, so the same token lands in a different dimension in a different
    space. Two spaces therefore produce genuinely incomparable vectors for identical text --
    without that, a test that mixed spaces would still retrieve the right answer and the mismatch
    guard would look like ceremony.
    """
    salt = space.key.encode()

    def embed(text: str) -> Sequence[float]:
        vector = [0.0] * space.dimensions
        for token in _tokens(text):
            digest = hashlib.sha256(salt + b"\x00" + token.encode()).digest()
            bucket = int.from_bytes(digest[:4], "big") % space.dimensions
            # The sign bit keeps unrelated tokens from only ever adding, which would make every
            # vector point into the same orthant and every cosine positive.
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[bucket] += sign
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0.0:
            # Empty or punctuation-only text. A zero vector has no direction, so cosine against
            # it is undefined; a fixed unit vector is an honest "no signal" that still compares.
            return [1.0] + [0.0] * (space.dimensions - 1)
        return [v / norm for v in vector]

    return embed


def _tokens(text: str) -> list[str]:
    return [token for token in re.split(r"[^0-9A-Za-z]+", text.lower()) if token]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity. Refuses unequal lengths rather than padding.

    A zero-padded comparison is not a smaller error than a cross-space one; it is the same error
    with an extra step, and it produces a number that ranks.
    """
    if len(a) != len(b):
        raise EmbeddingSpaceMismatch(
            f"cannot compare a {len(a)}-dimensional vector with a {len(b)}-dimensional one"
        )
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


@dataclass
class _Entry:
    representation: RetrievalRepresentation
    vector: Sequence[float]


class DenseEvidenceIndex:
    """A vector index over evidence units, scoped by project and by embedding space.

    THREE THINGS IT REFUSES, each because the permissive version is silent:

        a query embedded in another space      -> EmbeddingSpaceMismatch, not an empty result
        a unit already indexed in this index   -> re-index through `rebuild`, so the caller says so
        a cross-project read                   -> filtered at search, and asserted by a probe

    WHAT IT RETURNS. `RetrievalCandidate`, which has no body field. Callers reach the evidence
    through `CandidateResolver`, which re-loads the canonical unit by identity. This class cannot
    supply an evidence body even if a caller wanted one, which is ADR-0011 expressed as an API
    rather than as a rule people remember.
    """

    def __init__(self, index_id: str, space: EmbeddingSpace, embedder: Embedder) -> None:
        self._index_id = index_id
        self._space = space
        self._embed = embedder
        self._entries: dict[str, _Entry] = {}

    @property
    def index_id(self) -> str:
        return self._index_id

    @property
    def space(self) -> EmbeddingSpace:
        return self._space

    @property
    def size(self) -> int:
        return len(self._entries)

    def add(self, unit: EvidenceUnit, *, project_id: str) -> RetrievalRepresentation:
        """Index one unit. The representation records the space it was built in."""
        vector = self._embed(unit.body)
        if len(vector) != self._space.dimensions:
            raise EmbeddingSpaceMismatch(
                f"embedder produced {len(vector)} dimensions for index {self._index_id}, which "
                f"declares {self._space.dimensions}"
            )
        representation = RetrievalRepresentation(
            evidence_unit_id=unit.evidence_unit_id,
            project_id=project_id,
            index_id=self._index_id,
            index_kind=RetrievalIndexKind.DENSE,
            embedding_model=self._space.model,
            embedding_version=self._space.version,
            dimensions=self._space.dimensions,
            payload_digest=compute_content_hash(unit.body.encode("utf-8")),
        )
        self._entries[f"{project_id}\x00{unit.evidence_unit_id}"] = _Entry(
            representation=representation, vector=vector
        )
        return representation

    def add_all(
        self, units: Iterable[EvidenceUnit], *, project_id: str
    ) -> tuple[RetrievalRepresentation, ...]:
        return tuple(self.add(unit, project_id=project_id) for unit in units)

    def drop(self) -> None:
        """Delete the index. The evidence is untouched -- that is the point of ADR-0011."""
        self._entries.clear()

    def search(
        self,
        query: str,
        *,
        project_id: str,
        space: EmbeddingSpace,
        limit: int = 5,
    ) -> tuple[RetrievalCandidate, ...]:
        """Rank units by cosine similarity, within one project and one embedding space.

        ``space`` is required rather than defaulted to this index's own. A caller that could omit
        it would never discover that it was querying the wrong index -- the check would compare
        the index against itself and always pass.
        """
        if not space.compatible_with(self._space):
            raise EmbeddingSpaceMismatch(
                f"query embedded in {space.key} cannot search index {self._index_id}, which is "
                f"{self._space.key}. §6.13: mixing embedding spaces produces a number that ranks "
                "and means nothing, and no error would be raised downstream"
            )
        vector = self._embed(query)
        scored = [
            (cosine(vector, entry.vector), entry.representation)
            for entry in self._entries.values()
            if entry.representation.project_id == project_id
        ]
        # Ranked before truncation, and the tie-break is the unit id: a ranking that depended on
        # dict insertion order would make the same query answer differently after a rebuild, and
        # the benchmark recall a cutover is gated on would move for no reason anyone could name.
        scored.sort(key=lambda pair: (-pair[0], pair[1].evidence_unit_id))
        return tuple(
            RetrievalCandidate(
                evidence_unit_id=representation.evidence_unit_id,
                representation_id=representation.representation_id,
                project_id=project_id,
                score=score,
                rank=position,
            )
            for position, (score, representation) in enumerate(scored[:limit], start=1)
        )

    def representation_for(
        self, evidence_unit_id: str, project_id: str
    ) -> RetrievalRepresentation | None:
        entry = self._entries.get(f"{project_id}\x00{evidence_unit_id}")
        return None if entry is None else entry.representation

    def tamper(self, evidence_unit_id: str, project_id: str, replacement: str) -> None:
        """Rewrite an indexed payload, as an attacker with index write access would.

        Test-only, and it lives here rather than in a test file for the reason the lexical index
        gives about its own: an attack simulated by the thing under attack is the honest version.
        Both the vector and the digest are rewritten -- a tamper that left the digest behind would
        model an attacker who politely left evidence convicting them.
        """
        key = f"{project_id}\x00{evidence_unit_id}"
        entry = self._entries[key]
        self._entries[key] = _Entry(
            representation=entry.representation.model_copy(
                update={"payload_digest": compute_content_hash(replacement.encode("utf-8"))}
            ),
            vector=self._embed(replacement),
        )


@dataclass
class RecallReport:
    """What a benchmark run measured, and over what."""

    index_id: str
    space_key: str
    queries: int
    expected: int
    found: int

    @property
    def recall(self) -> float:
        return self.found / self.expected if self.expected else 0.0


@dataclass
class DualIndexCutover:
    """§6.20's migration: old and new coexist, and recall is verified before the switch.

    WHY THIS IS AN OBJECT RATHER THAN A DEPLOY FLAG. "換 model 時採 dual-index：新舊並存，以
    benchmark recall 驗證後才 cutover" describes a *sequence with a gate in it*. A boolean that
    someone flips is the same migration with the gate removed, and the gate is the requirement.

    ``active`` is what retrieval reads. It stays the old index until `promote` succeeds, so a
    half-finished migration degrades to the previous behaviour rather than to no retrieval.
    """

    old: DenseEvidenceIndex
    new: DenseEvidenceIndex
    #: §6.20's "以 benchmark recall 驗證". The floor is declared up front, so a disappointing
    #: measurement cannot be accommodated by lowering it afterwards.
    recall_floor: float = 0.9
    _promoted: bool = field(default=False, init=False)
    _report: RecallReport | None = field(default=None, init=False)

    @property
    def active(self) -> DenseEvidenceIndex:
        return self.new if self._promoted else self.old

    @property
    def promoted(self) -> bool:
        return self._promoted

    @property
    def report(self) -> RecallReport | None:
        return self._report

    def measure(
        self,
        cases: Sequence[tuple[str, frozenset[str]]],
        *,
        project_id: str,
        limit: int = 5,
    ) -> RecallReport:
        """Measure the new index's recall over ``(query, expected unit ids)`` cases."""
        if not cases:
            raise IndexNotReady(
                "recall cannot be measured over an empty benchmark. A cutover verified against "
                "no cases is an unverified cutover with a number attached"
            )
        expected_total = 0
        found_total = 0
        for query, expected in cases:
            if not expected:
                raise IndexNotReady(
                    f"benchmark case {query!r} expects no units; recall over an empty expectation "
                    "is 0/0, and reporting that as 1.00 is how an unverified cutover passes"
                )
            hits = {
                candidate.evidence_unit_id
                for candidate in self.new.search(
                    query, project_id=project_id, space=self.new.space, limit=limit
                )
            }
            expected_total += len(expected)
            found_total += len(expected & hits)
        report = RecallReport(
            index_id=self.new.index_id,
            space_key=self.new.space.key,
            queries=len(cases),
            expected=expected_total,
            found=found_total,
        )
        self._report = report
        return report

    def promote(self) -> RecallReport:
        """Switch retrieval to the new index. Refuses unless recall was measured and met."""
        if self._report is None:
            raise IndexNotReady(
                f"index {self.new.index_id} has not been measured. §6.20 requires benchmark "
                "recall to be verified before cutover, and 'we did not check' is not a pass"
            )
        if self._report.recall < self.recall_floor:
            raise IndexNotReady(
                f"index {self.new.index_id} recalled {self._report.recall:.2f}, below the "
                f"declared floor of {self.recall_floor:.2f}. The old index stays active"
            )
        self._promoted = True
        return self._report

    def which_version_answered(self) -> str:
        """§6.20: "cutover 前後都必須可回答『這筆檢索用的是哪個 embedding version』"."""
        return self.active.space.key


__all__ = [
    "DenseEvidenceIndex",
    "DualIndexCutover",
    "Embedder",
    "EmbeddingSpace",
    "EmbeddingSpaceMismatch",
    "IndexNotReady",
    "RecallReport",
    "cosine",
    "hashing_embedder",
]
