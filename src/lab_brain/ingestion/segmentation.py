"""Evidence-aware hierarchical segmentation — §6.22, EVI-010.

THE RULE, and why it is not a retrieval-quality preference.

The smallest unit that can honestly support a scientific claim is the result *together with the
conditions that make it interpretable*. Cut::

    Reverse bias increased from 0 to -2 V.
    The junction capacitance decreased from 0.515 to 0.345 pF/mm.

into two units and each half is still true, still attributable, still correctly statused -- and
the measurement is no longer a measurement of anything. No downstream check fires, because no
field is missing: the conditions were not dropped, they were filed separately. The corruption
surfaces much later as a corroboration that was never valid, by which time the unit that caused it
looks exactly like a good one.

THE ORDER OF OPERATIONS, which is the requirement.

    structure  ->  boundary binding  ->  (only if oversized) token subdivision

Not "token windows, with structure as a hint". §6.22 rule 3 makes fixed-token splitting a fallback
with a recorded reason, and ``SubdivisionReason`` is a closed two-member vocabulary so a record has
to say which of the two permitted reasons applies. Every library one would reach for defaults to
the opposite order, which is exactly why the prohibition has to be structural rather than advisory.

WHAT THIS MODULE DOES NOT DO. It does not extract scientific values, guess units, or decide what a
number means -- that is ``extract_*`` and a DomainPack's business (§24.1, AGT-014). It decides
where the cuts go. The only scientific judgement it makes is "these sentences belong together",
and it makes that judgement conservatively: the binder errs toward keeping text together, because
an over-large unit is a retrieval-precision cost and an under-large one is a correctness failure.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from lab_brain.core.models.enums import EvidenceUnitType, SubdivisionReason
from lab_brain.core.models.evidence_unit import (
    EvidenceUnit,
    FigureContext,
    SegmenterProvenance,
    SourceLocator,
    TableContext,
)
from lab_brain.core.models.identifiers import compute_content_hash, evidence_unit_id_for
from lab_brain.ingestion.parsers.structure import ParsedBlock, ParsedDocument

SEGMENTER_ID = "evidence_aware_hierarchical"
SEGMENTER_VERSION = "1.0.0"

#: Default ceiling for one evidence unit, in whitespace tokens. §6.22 rule 3(a) permits
#: subdivision only when a unit exceeds *a declared* limit, so the number is recorded on every
#: unit's provenance rather than left implicit -- "was this cut legitimately" is answerable only
#: against the limit that was in force at the time.
DEFAULT_TOKEN_LIMIT = 320

#: Overlap carried into each fallback sub-unit, in tokens. Not a retrieval trick: rule 4 requires
#: sub-units to retain the parent's interpretive context, and the leading sentences of an
#: oversized unit are usually where its conditions are stated.
SUBDIVISION_OVERLAP_TOKENS = 40


class SegmentationError(RuntimeError):
    """Segmentation could not produce units that satisfy §6.22."""


# ---------------------------------------------------------------------------
# Condition/result binding
# ---------------------------------------------------------------------------

#: Sentences that *set up* an experimental condition. Present tense, past tense and imperative,
#: because papers use all three ("the bias is swept", "we increased the bias", "sweep the bias").
_CONDITION_VERBS = (
    r"increas\w*",
    r"decreas\w*",
    r"sweep|swept|sweeping",
    r"set\b|setting",
    r"appli\w*|apply\w*",
    r"bias\w*",
    r"vari\w*",
    r"ramp\w*",
    r"held|hold\w*|maintain\w*",
    r"raised|lowered",
    r"measured at|taken at|recorded at",
)

#: Sentences that *report a result*.
_RESULT_VERBS = (
    r"decreas\w*",
    r"increas\w*",
    r"chang\w*",
    r"improv\w*|degrad\w*",
    r"drop\w*|ros\w*|fell|rise\w*",
    r"shift\w*",
    r"remain\w*|stay\w*",
    r"reach\w*",
    r"yield\w*|result\w*",
    r"was|were|is|are",
)

#: A quantity with a unit: ``-2 V``, ``0.515 pF/mm``, ``1550 nm``, ``25 °C``. Deliberately
#: generic -- §24.1 forbids the core knowing what a volt means, and this only needs to know that
#: *something* was measured in *some* unit.
_QUANTITY = re.compile(
    r"[-+]?\d+(?:\.\d+)?\s*"
    r"(?:[munpfkKMG]?(?:[VAWΩ]|Hz|m|s|F|eV|K|°C|dB|dBm|bar|Pa|T)"
    r"(?:\s*/\s*[munpfkKMG]?(?:m|s|cm|mm|µm|um|nm|Hz))?)\b"
)

_CONDITION_RE = re.compile("|".join(_CONDITION_VERBS), re.IGNORECASE)
_RESULT_RE = re.compile("|".join(_RESULT_VERBS), re.IGNORECASE)

#: Sentence splitter. Deliberately simple and deliberately conservative: it does not split on a
#: period followed by a digit ("0.515"), a lowercase letter, or a closing bracket. Getting this
#: wrong in the splitting direction is a correctness failure, so it under-splits by design.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\[])")

#: Pronouns and determiners that make a sentence unreadable on its own. A result sentence opening
#: with one of these is bound to its predecessor regardless of the quantity heuristics: "This
#: decreased to 0.345 pF/mm" names no subject.
_DEPENDENT_OPENER = re.compile(
    r"^\s*(?:this|that|these|those|it|they|the (?:former|latter|result|value|measurement))\b",
    re.IGNORECASE,
)


def split_sentences(text: str) -> list[str]:
    """Split prose into sentences, under-splitting rather than over-splitting."""
    return [part.strip() for part in _SENTENCE_END.split(text.strip()) if part.strip()]


def _states_condition(sentence: str) -> bool:
    return bool(_CONDITION_RE.search(sentence)) and bool(_QUANTITY.search(sentence))


def _states_result(sentence: str) -> bool:
    return bool(_RESULT_RE.search(sentence)) and bool(_QUANTITY.search(sentence))


@dataclass(frozen=True)
class BoundGroup:
    """Sentences that must stay in one evidence unit, and which of them are the conditions.

    ``condition_texts`` is recorded separately so the resulting ``EvidenceUnit`` can *declare*
    what it must contain. That declaration is what turns a segmenter behaviour into a checkable
    property: the model validator refuses a unit whose declared conditions are not in its body,
    so a regression in this function fails at construction rather than producing a plausible unit.
    """

    sentences: tuple[str, ...]
    condition_texts: tuple[str, ...]

    @property
    def text(self) -> str:
        return " ".join(self.sentences)


def bind_condition_result_groups(text: str) -> list[BoundGroup]:
    """Group prose sentences so no result is separated from the conditions it needs (rule 1).

    Two ways a sentence joins the group before it, and they catch different things:

        quantitative   the previous sentence set a condition with a magnitude and this one
                       reports a magnitude. "Bias went 0 to -2 V." + "Cj fell 0.515 to 0.345."
        referential    this sentence opens with a pronoun or a bare "the result", so it has no
                       subject of its own. "This decreased to 0.345 pF/mm."

    The second is not redundant. A result sentence can carry a quantity and still be readable
    alone, and a referential one can carry no quantity at all and still be meaningless alone.
    """
    sentences = split_sentences(text)
    if not sentences:
        return []

    groups: list[list[str]] = [[sentences[0]]]
    conditions: list[list[str]] = [[sentences[0]] if _states_condition(sentences[0]) else []]

    for sentence in sentences[1:]:
        previous = groups[-1][-1]
        joins = (_states_condition(previous) and _states_result(sentence)) or bool(
            _DEPENDENT_OPENER.match(sentence)
        )
        if joins:
            groups[-1].append(sentence)
            if _states_condition(sentence):
                conditions[-1].append(sentence)
            continue
        groups.append([sentence])
        conditions.append([sentence] if _states_condition(sentence) else [])

    return [
        BoundGroup(sentences=tuple(group), condition_texts=tuple(condition))
        for group, condition in zip(groups, conditions, strict=True)
    ]


# ---------------------------------------------------------------------------
# Figure context
# ---------------------------------------------------------------------------


def _figure_reference_pattern(label: str) -> re.Pattern[str]:
    """Match prose that refers to ``label``: "Figure 3", "Fig. 3", "Fig 3", "(Fig. 3)"."""
    number = label.rsplit(" ", 1)[-1].rstrip(".:")
    return re.compile(rf"\b(?:fig(?:ure)?\.?)\s*{re.escape(number)}\b", re.IGNORECASE)


def prose_referring_to(document: ParsedDocument, figure: ParsedBlock) -> tuple[str, ...]:
    """Body prose that discusses ``figure`` (rule 6).

    Two sources, in document order:

      * any prose block anywhere in the document that names the figure explicitly;
      * the prose block immediately preceding it, which is the convention papers actually follow
        -- "...as shown below." then the figure -- and which frequently names no figure at all.

    The second is why a pure reference scan is insufficient, and why this returns prose rather
    than just checking that some exists.
    """
    pattern = _figure_reference_pattern(figure.figure_label or "")
    referring: list[tuple[int, str]] = []
    for block in document.blocks:
        if block.block_type is not EvidenceUnitType.PROSE:
            continue
        if pattern.search(block.text) or block.index == figure.index - 1:
            referring.append((block.index, block.text))
    return tuple(text for _, text in sorted(set(referring)))


# ---------------------------------------------------------------------------
# Fallback subdivision (rule 3(a))
# ---------------------------------------------------------------------------


def token_count(text: str) -> int:
    """Whitespace tokens. A stand-in for a model tokenizer, and honest about being one.

    EVI-010 constrains *when* subdivision is permitted, not how tokens are counted. Using a real
    tokenizer would bind evidence boundaries to a model's vocabulary, which is precisely the
    dependency §6.22 removes -- so the limit is expressed in a unit that no embedding model owns.
    """
    return len(text.split())


def subdivide_oversized(
    text: str, limit: int, overlap: int = SUBDIVISION_OVERLAP_TOKENS
) -> list[tuple[str, tuple[str, ...]]]:
    """Cut one oversized valid unit into sub-units, each carrying inherited context.

    Returns ``(body, inherited_context)`` pairs. The inherited context is the tail of the previous
    sub-unit, so rule 4's "retains the parent's identity and interpretive context" is satisfied by
    something the sub-unit actually holds rather than by a claim in a comment.

    Sentence-aligned rather than token-aligned: cutting mid-sentence would reintroduce the failure
    the whole module exists to prevent, one level down.
    """
    if limit <= 0:
        raise SegmentationError(f"token limit must be positive, got {limit}")
    sentences = split_sentences(text) or [text]

    chunks: list[list[str]] = [[]]
    for sentence in sentences:
        current = chunks[-1]
        if current and token_count(" ".join([*current, sentence])) > limit:
            chunks.append([sentence])
        else:
            current.append(sentence)

    out: list[tuple[str, tuple[str, ...]]] = []
    for position, chunk in enumerate(chunks):
        if position == 0:
            out.append((" ".join(chunk), ()))
            continue
        previous = " ".join(chunks[position - 1]).split()
        carried = " ".join(previous[-overlap:]) if previous else ""
        out.append((" ".join(chunk), (carried,) if carried else ()))
    return out


# ---------------------------------------------------------------------------
# The segmenter
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SegmentationResult:
    units: tuple[EvidenceUnit, ...]
    #: Units the fallback path produced, for the benchmark report and for the test that fixed
    #: token splitting was used *only* as a fallback.
    subdivided_unit_ids: frozenset[str]

    def of_type(self, unit_type: EvidenceUnitType) -> tuple[EvidenceUnit, ...]:
        return tuple(unit for unit in self.units if unit.unit_type is unit_type)

    def by_id(self, evidence_unit_id: str) -> EvidenceUnit | None:
        for unit in self.units:
            if unit.evidence_unit_id == evidence_unit_id:
                return unit
        return None


class EvidenceAwareSegmenter:
    """Structure-first segmentation (§6.22). The primary and only production splitter.

    Stateless and deterministic: the same document and the same limit always produce the same
    units with the same ids. That is not a convenience -- re-running ingestion over unchanged
    bytes must not orphan the Attestations that reference the previous run's units.
    """

    def __init__(self, token_limit: int = DEFAULT_TOKEN_LIMIT) -> None:
        if token_limit <= 0:
            raise SegmentationError(f"token limit must be positive, got {token_limit}")
        self._token_limit = token_limit

    @property
    def token_limit(self) -> int:
        return self._token_limit

    def segment(self, document: ParsedDocument) -> SegmentationResult:
        provenance = SegmenterProvenance(
            segmenter_id=SEGMENTER_ID,
            segmenter_version=SEGMENTER_VERSION,
            parser_id=document.parser_id,
            parser_version=document.parser_version,
            token_limit=self._token_limit,
        )
        units: list[EvidenceUnit] = []
        subdivided: set[str] = set()

        for block in document.blocks:
            if block.block_type is EvidenceUnitType.SECTION:
                # A heading is navigation, not evidence. It reaches units as `structural_path`
                # and `locator.label`; emitting it as its own unit would put a retrievable record
                # with no content into the corpus.
                continue
            produced = self._segment_block(document, block, provenance=provenance)
            units.extend(produced)
            subdivided.update(unit.evidence_unit_id for unit in produced if unit.is_subdivision)

        return SegmentationResult(units=tuple(units), subdivided_unit_ids=frozenset(subdivided))

    # -- per block ----------------------------------------------------------

    def _segment_block(
        self,
        document: ParsedDocument,
        block: ParsedBlock,
        *,
        provenance: SegmenterProvenance,
    ) -> list[EvidenceUnit]:
        if block.block_type is EvidenceUnitType.TABLE:
            return [self._table_unit(document, block, provenance)]
        if block.block_type is EvidenceUnitType.FIGURE:
            return [self._figure_unit(document, block, provenance)]
        if block.block_type in {EvidenceUnitType.CODE, EvidenceUnitType.LOG}:
            # Never sentence-split: a code block or a log is one artefact, and cutting it between
            # two lines produces two things that each look like a complete listing.
            return self._atomic_units(document, block, provenance, group_index=0)
        return self._prose_units(document, block, provenance)

    def _locator(self, block: ParsedBlock, suffix: str = "") -> SourceLocator:
        label = block.section_label
        if suffix:
            label = f"{label} / {suffix}"
        return SourceLocator(
            label=label,
            page=block.page,
            start_offset=block.start_offset,
            end_offset=block.end_offset,
        )

    def _prose_units(
        self,
        document: ParsedDocument,
        block: ParsedBlock,
        provenance: SegmenterProvenance,
    ) -> list[EvidenceUnit]:
        groups = bind_condition_result_groups(block.text)
        if not groups:
            return []

        units: list[EvidenceUnit] = []
        for group_index, group in enumerate(groups):
            units.extend(
                self._emit(
                    document=document,
                    block=block,
                    provenance=provenance,
                    body=group.text,
                    group_index=group_index,
                    bound_condition_texts=group.condition_texts,
                )
            )
        return units

    def _atomic_units(
        self,
        document: ParsedDocument,
        block: ParsedBlock,
        provenance: SegmenterProvenance,
        group_index: int,
    ) -> list[EvidenceUnit]:
        return self._emit(
            document=document,
            block=block,
            provenance=provenance,
            body=block.text,
            group_index=group_index,
            bound_condition_texts=(),
        )

    def _emit(
        self,
        *,
        document: ParsedDocument,
        block: ParsedBlock,
        provenance: SegmenterProvenance,
        body: str,
        group_index: int,
        bound_condition_texts: Sequence[str],
    ) -> list[EvidenceUnit]:
        """Emit one unit, or -- only if it is oversized -- its fallback subdivisions."""
        base_path = f"{block.structural_key}/{group_index}"

        if token_count(body) <= self._token_limit:
            return [
                EvidenceUnit.build(
                    artifact_id=document.artifact_id,
                    unit_type=block.block_type,
                    structural_path=base_path,
                    locator=self._locator(block),
                    body=body,
                    provenance=provenance,
                    bound_condition_texts=tuple(bound_condition_texts),
                )
            ]

        # Rule 3(a). The parent is not stored -- it is the thing that was too large to store --
        # but its identity is computed so every sub-unit names the same parent and a reader can
        # tell the pieces apart from independently segmented units.
        parent_id = evidence_unit_id_for(
            document.artifact_id, base_path, compute_content_hash(body.encode("utf-8"))
        )
        pieces = subdivide_oversized(body, self._token_limit)
        units: list[EvidenceUnit] = []
        for position, (piece_body, inherited) in enumerate(pieces):
            # Conditions stated in the parent must reach every piece, or rule 4 is unmet. A piece
            # whose own text lacks a bound condition inherits it explicitly rather than by luck.
            carried = tuple(inherited)
            missing = tuple(
                text
                for text in bound_condition_texts
                if text not in piece_body and text not in "\n".join(carried)
            )
            units.append(
                EvidenceUnit.build(
                    artifact_id=document.artifact_id,
                    unit_type=block.block_type,
                    structural_path=f"{base_path}#sub{position}",
                    locator=self._locator(block, suffix=f"part {position + 1}/{len(pieces)}"),
                    body=piece_body,
                    provenance=provenance,
                    parent_unit_id=parent_id,
                    subdivision_index=position,
                    subdivision_reason=SubdivisionReason.OVERSIZED_UNIT,
                    inherited_context=carried + missing,
                    bound_condition_texts=tuple(bound_condition_texts),
                )
            )
        return units

    def _table_unit(
        self,
        document: ParsedDocument,
        block: ParsedBlock,
        provenance: SegmenterProvenance,
    ) -> EvidenceUnit:
        """One unit per table (rule 5). Never one per row.

        A row on its own has lost the header that names its columns and the units that give its
        numbers magnitude, which is the exact failure rule 5 describes. Tables are therefore
        atomic here even when large -- and if a table exceeds the token limit, the body is what
        gets subdivided in a future slice, never the header/unit context.
        """
        context = TableContext(
            caption=block.table_caption,
            headers=block.table_headers,
            units=block.table_units,
            row_labels=block.table_row_labels,
            rows=block.table_rows,
        )
        if not context.is_interpretable:
            raise SegmentationError(
                f"table at {block.structural_key} has no headers or no rows; emitting it would "
                "produce an evidence unit whose values cannot be read (§6.22 rule 5)"
            )
        return EvidenceUnit.build(
            artifact_id=document.artifact_id,
            unit_type=EvidenceUnitType.TABLE,
            structural_path=block.structural_key,
            locator=self._locator(block, suffix=block.table_caption or "table"),
            body=block.text,
            provenance=provenance,
            table_context=context,
        )

    def _figure_unit(
        self,
        document: ParsedDocument,
        block: ParsedBlock,
        provenance: SegmenterProvenance,
    ) -> EvidenceUnit:
        """One unit per figure, carrying the prose that explains it (rule 6)."""
        prose = prose_referring_to(document, block)
        context = FigureContext(
            figure_label=block.figure_label or "",
            caption=block.figure_caption,
            surrounding_prose=prose,
        )
        if not context.is_interpretable:
            raise SegmentationError(
                f"figure {block.figure_label!r} has no caption or no explanatory prose; §6.22 "
                "rule 6 states a caption alone is not sufficient to read a figure"
            )
        # The body carries the prose too. The context fields make it queryable; the body makes it
        # retrievable, and a retriever that scored only the caption would rank the figure by the
        # one piece of text the spec says is insufficient.
        body = "\n".join([block.text, *prose])
        return EvidenceUnit.build(
            artifact_id=document.artifact_id,
            unit_type=EvidenceUnitType.FIGURE,
            structural_path=block.structural_key,
            locator=self._locator(block, suffix=block.figure_label or "figure"),
            body=body,
            provenance=provenance,
            figure_context=context,
        )


__all__ = [
    "DEFAULT_TOKEN_LIMIT",
    "SEGMENTER_ID",
    "SEGMENTER_VERSION",
    "SUBDIVISION_OVERLAP_TOKENS",
    "BoundGroup",
    "EvidenceAwareSegmenter",
    "SegmentationError",
    "SegmentationResult",
    "bind_condition_result_groups",
    "prose_referring_to",
    "split_sentences",
    "subdivide_oversized",
    "token_count",
]
