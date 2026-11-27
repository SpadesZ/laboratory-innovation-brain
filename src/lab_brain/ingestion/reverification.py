"""Re-derive an evidence unit under the implementation it *records*, not the current one.

SPEC-ISSUE-015's semantic layer, and the reason it can exist at all:

    the artifact is content-addressed   -> its bytes are pinned by its identity
    the segmenter is deterministic      -> the same bytes always give the same units
    parser/segmenter versions are on
      every unit's provenance           -> "which segmenter" is not a guess

Therefore *what segmentation produces from this artifact* is computable at admission time, and a
unit that is not among the answers was written by something other than the path it claims. No
component has to read the prose to establish that -- which is what makes this the honest answer
where a SQL-side check would have meant a second, drifting copy of the segmenter (`v3.3-a13`).

WHAT REPAIR-2 FIXED HERE, and why it mattered. The first version took an ``artifact_id`` and ran
whatever parser and segmenter it had been constructed with -- in practice the current defaults. So
a unit could record ``segmenter_id="some_other_segmenter", segmenter_version="99.0.0"``, be
re-derived by the *current* segmenter, produce a matching body, and be admitted. The check proved
"some segmenter produces this", which is not what §17.25 and ADR-0012 require: they require the
**recorded** provenance to be reproducible, because provenance nobody ever re-runs is decoration.

So re-verification now takes the unit, resolves its recorded implementation from a versioned
registry, and **fails closed when that implementation is not available**. It never substitutes the
current version. A historical unit is verified as the thing that made it, or not at all.

WHAT THIS IS NOT. A cache, and not an optimisation. It re-parses on every call by design. A cache
keyed on ``(artifact_id, parser_version, segmenter_version, token_limit)`` is the available
mitigation if the cost ever matters, and ADR-0012 records that it must remain a cache *of the
re-derivation* rather than becoming trust in the stored witness -- which would delete this layer
and restore the issue.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from lab_brain.core.models.evidence_unit import EvidenceUnit, SegmenterProvenance
from lab_brain.ingestion.parsers.documents import PARSER_ID, PARSER_VERSION, MarkdownDocumentParser
from lab_brain.ingestion.parsers.structure import ParsedDocument
from lab_brain.ingestion.segmentation import (
    SEGMENTER_ID,
    SEGMENTER_VERSION,
    EvidenceAwareSegmenter,
)


class ReverificationFailure(StrEnum):
    """Why re-derivation could not produce an answer. Each leads to a refusal, not a skip.

    Separated because they are different operational problems with different remedies, and
    collapsing them would make an unreachable artifact store indistinguishable from a unit whose
    segmenter no longer exists.
    """

    #: The unit records a parser/segmenter identity+version this build cannot construct.
    IMPLEMENTATION_NOT_REGISTERED = "IMPLEMENTATION_NOT_REGISTERED"
    #: The artifact's bytes could not be loaded, so there is nothing to re-derive from.
    ARTIFACT_BYTES_UNAVAILABLE = "ARTIFACT_BYTES_UNAVAILABLE"
    #: The bytes loaded but the recorded parser could not read them.
    PARSE_FAILED = "PARSE_FAILED"


@dataclass(frozen=True)
class Reverification:
    """What re-derivation established, or why it could not.

    ``units`` is ``None`` when the check could not run. It is an empty tuple when the check ran
    and the document genuinely yields no evidence units -- opposite facts, and the caller refuses
    for different reasons. Collapsing them to ``None`` is what let "we could not check" read as
    "this document has no evidence".
    """

    units: tuple[EvidenceUnit, ...] | None = None
    failure: ReverificationFailure | None = None
    detail: str = ""

    @property
    def ran(self) -> bool:
        return self.units is not None


#: A parser factory: takes nothing, returns something with ``.parse(text, artifact_id=...)``.
ParserFactory = Callable[[], MarkdownDocumentParser]
#: A segmenter factory: takes the recorded token limit, returns the segmenter that was in force.
SegmenterFactory = Callable[[int | None], EvidenceAwareSegmenter]


class SegmentationRegistry:
    """Maps a recorded ``(id, version)`` to the implementation that produced it.

    Small on purpose. M1-P1 has exactly one parser version and one segmenter version, so this
    registry has two entries -- and that is precisely why it has to exist rather than be inlined:
    the property that matters is not "look up the right one among many", it is **refuse when the
    recorded one is absent**. With a single implementation and no registry, every historical unit
    silently verifies against today's code, which is the defect Repair-2 found.

    When `EVI-007` or a later slice ships a second segmenter version, registering it here is the
    whole change, and units written by version 1 keep verifying under version 1.
    """

    def __init__(self) -> None:
        self._parsers: dict[tuple[str, str], ParserFactory] = {}
        self._segmenters: dict[tuple[str, str], SegmenterFactory] = {}

    def register_parser(self, parser_id: str, version: str, factory: ParserFactory) -> None:
        self._parsers[(parser_id, version)] = factory

    def register_segmenter(
        self, segmenter_id: str, version: str, factory: SegmenterFactory
    ) -> None:
        self._segmenters[(segmenter_id, version)] = factory

    def parser_for(self, provenance: SegmenterProvenance) -> MarkdownDocumentParser | None:
        factory = self._parsers.get((provenance.parser_id, provenance.parser_version))
        return factory() if factory is not None else None

    def segmenter_for(self, provenance: SegmenterProvenance) -> EvidenceAwareSegmenter | None:
        factory = self._segmenters.get((provenance.segmenter_id, provenance.segmenter_version))
        # The token limit travels too. A unit subdivided under a 25-token limit does not reproduce
        # under the default 320 -- rule 3(a)'s fallback would not fire, the sub-units would not
        # exist, and a legitimate historical unit would be refused as unreproducible.
        return factory(provenance.token_limit) if factory is not None else None

    @property
    def registered(self) -> tuple[str, ...]:
        """Human-readable inventory, for the refusal message. An operator needs to see what *is*
        available to know whether the recorded version is a typo or a genuinely retired build."""
        return tuple(
            sorted(
                [f"parser {pid} {ver}" for pid, ver in self._parsers]
                + [f"segmenter {sid} {ver}" for sid, ver in self._segmenters]
            )
        )


def default_registry() -> SegmentationRegistry:
    """The implementations this build actually contains.

    Deliberately not populated by scanning or by a plugin hook: what is registered here is what
    this commit can genuinely re-run, and an entry that is wrong is a lie the admission gate will
    act on.
    """
    registry = SegmentationRegistry()
    registry.register_parser(PARSER_ID, PARSER_VERSION, MarkdownDocumentParser)
    registry.register_segmenter(
        SEGMENTER_ID,
        SEGMENTER_VERSION,
        lambda token_limit: (
            EvidenceAwareSegmenter(token_limit=token_limit)
            if token_limit is not None
            else EvidenceAwareSegmenter()
        ),
    )
    return registry


class SegmentationReverifier:
    """Re-runs the unit's *recorded* parse + segmentation over the artifact's own bytes."""

    def __init__(
        self,
        load_bytes: Callable[[str], bytes | None],
        *,
        registry: SegmentationRegistry | None = None,
    ) -> None:
        self._load_bytes = load_bytes
        self._registry = registry or default_registry()

    def __call__(self, unit: EvidenceUnit) -> Reverification:
        """Takes the UNIT, not an artifact id.

        The unit is the only thing that knows which implementation is supposed to have produced
        it. Passing an artifact id was the Repair-2 defect: it left the choice of verifier to
        whoever constructed this object, which in practice meant "whatever is current".
        """
        provenance = unit.provenance

        parser = self._registry.parser_for(provenance)
        segmenter = self._registry.segmenter_for(provenance)
        if parser is None or segmenter is None:
            missing = []
            if parser is None:
                missing.append(f"parser {provenance.parser_id} {provenance.parser_version}")
            if segmenter is None:
                missing.append(
                    f"segmenter {provenance.segmenter_id} {provenance.segmenter_version}"
                )
            return Reverification(
                failure=ReverificationFailure.IMPLEMENTATION_NOT_REGISTERED,
                detail=(
                    f"{' and '.join(missing)} is not registered in this build, so the unit's "
                    "recorded provenance cannot be re-run. Substituting the current version "
                    "would prove that *some* implementation produces this unit, which is not "
                    f"what §17.25 requires. Available: {', '.join(self._registry.registered)}"
                ),
            )

        try:
            raw = self._load_bytes(unit.artifact_id)
        except Exception as exc:
            # A store that raises and a store that returns None are the same fact to the gate:
            # the check could not be performed. Swallowing it here keeps that fact from arriving
            # as an unrelated error halfway up the admission path.
            return Reverification(
                failure=ReverificationFailure.ARTIFACT_BYTES_UNAVAILABLE,
                detail=f"the artifact store raised while loading {unit.artifact_id}: {exc}",
            )
        if raw is None:
            return Reverification(
                failure=ReverificationFailure.ARTIFACT_BYTES_UNAVAILABLE,
                detail=f"no bytes available for artifact {unit.artifact_id}",
            )

        try:
            document: ParsedDocument = parser.parse(
                raw.decode("utf-8"), artifact_id=unit.artifact_id
            )
            return Reverification(units=segmenter.segment(document).units)
        except Exception as exc:
            # A document that no longer parses cannot verify anything. Refusing is the only safe
            # reading: "the parser broke" must not become "the unit is fine".
            return Reverification(
                failure=ReverificationFailure.PARSE_FAILED,
                detail=f"the recorded parser could not read {unit.artifact_id}: {exc}",
            )


__all__ = [
    "ParserFactory",
    "Reverification",
    "ReverificationFailure",
    "SegmentationRegistry",
    "SegmentationReverifier",
    "SegmenterFactory",
    "default_registry",
]
