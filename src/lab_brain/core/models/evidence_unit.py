"""EvidenceUnit and RetrievalRepresentation — §6.22, §17.25, EVI-010, ADR-0011.

Two objects that a conventional retrieval stack would make one, and the whole requirement is the
separation.

    EvidenceUnit               what the evidence IS. Canonical, project-scoped, identity derived
                               from (artifact_id, structural_path, content_digest).
    RetrievalRepresentation    what an INDEX holds about it. Derived, disposable, per index.

Merged into a single "chunk", the row's lifetime becomes the index's lifetime: re-embedding is an
UPDATE on scientific data, and "drop the index and rebuild" becomes a destructive operation on
evidence. Keeping them apart is what lets ``EVI-007``'s later dense index be plugged in, swapped
and deleted without any of those verbs touching an Attestation.

THE MINIMUM EVIDENCE BOUNDARY, which is the reason any of this exists. The smallest unit that can
honestly support a scientific claim is the result *together with the conditions that make it
interpretable*. Split::

    Reverse bias increased from 0 to -2 V.
    The junction capacitance decreased from 0.515 to 0.345 pF/mm.

and each half is still true, still attributable, still correctly statused -- and the measurement
is no longer a measurement of anything. Nothing downstream can detect it, because no field is
missing: the conditions were not dropped, they were filed separately. That is why the check lives
at segmentation time and why the boundary is a property of the record rather than a convention.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Self

from pydantic import Field, model_validator

from lab_brain.core.models.base import CoreModel, utc_now
from lab_brain.core.models.enums import (
    EvidenceUnitType,
    RetrievalIndexKind,
    SubdivisionReason,
)
from lab_brain.core.models.identifiers import (
    compute_content_hash,
    evidence_unit_id_for,
    new_id,
    parse_content_hash,
)


class SourceLocator(CoreModel):
    """Where in a source a unit came from, kept structured rather than as display text.

    §6.22 requires every unit to resolve back to a re-checkable position. A locator flattened to
    "p. 4, Table 2" is readable and not comparable: two units from the same table cannot be
    recognised as such, and a human re-checking the claim has to search rather than navigate.
    """

    #: Human-facing, stable across re-parses of the same document: ``"§3.2 / Table 2 / row 3"``.
    label: str
    #: Page when the source has pages. Absent for Markdown, logs and most structured formats;
    #: absent means "this source has no pages", never "we did not record it".
    page: int | None = Field(default=None, ge=1)
    #: Character offsets into the parsed document text. The precise half of the locator: it is
    #: what makes "show me exactly this" possible without re-running the parser.
    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _offsets_are_ordered(self) -> Self:
        if (
            self.start_offset is not None
            and self.end_offset is not None
            and self.end_offset < self.start_offset
        ):
            raise ValueError(
                f"locator {self.label!r} ends at {self.end_offset} before it starts at "
                f"{self.start_offset}"
            )
        if (self.start_offset is None) != (self.end_offset is None):
            raise ValueError(
                f"locator {self.label!r} has only one offset; half a span cannot be resolved "
                "back to the document"
            )
        return self


class TableContext(CoreModel):
    """§6.22 rule 5. What a table cell needs in order to still mean something.

    A value lifted out of a table without its header and unit is a number. This carries the three
    things that turn it back into a measurement -- what the column is, what it is measured in, and
    which row it belongs to -- plus the caption, because a table's caption routinely carries the
    conditions the columns do not repeat.
    """

    caption: str | None = None
    #: Column headers, in document order. Positional correspondence with each row's cells is
    #: checked below, because a header list that has drifted out of alignment is worse than none:
    #: it labels every value with its neighbour's name.
    headers: tuple[str, ...] = ()
    #: Unit per column, positionally aligned with ``headers``. ``None`` means the column is
    #: genuinely unitless (a name, a count of things); it never means "not extracted" -- an
    #: unextracted unit makes the whole table uninterpretable and fails validation instead.
    units: tuple[str | None, ...] = ()
    #: Row label per row, when the table has a label column.
    row_labels: tuple[str, ...] = ()
    rows: tuple[tuple[str, ...], ...] = ()

    @model_validator(mode="after")
    def _shape_is_consistent(self) -> Self:
        if self.units and len(self.units) != len(self.headers):
            raise ValueError(
                f"table has {len(self.headers)} headers but {len(self.units)} units; a "
                "positionally misaligned unit list labels every value with the wrong unit"
            )
        if self.row_labels and self.rows and len(self.row_labels) != len(self.rows):
            raise ValueError(
                f"table has {len(self.rows)} rows but {len(self.row_labels)} row labels"
            )
        wrong = [
            index
            for index, row in enumerate(self.rows)
            if self.headers and len(row) != len(self.headers)
        ]
        if wrong:
            raise ValueError(
                f"table rows {wrong} do not have {len(self.headers)} cells; a ragged table cannot "
                "be read by column, which is the only way its units apply"
            )
        return self

    def cell(self, row_index: int, column: str) -> str | None:
        """One cell, addressed the way a reader addresses it: by row and column name."""
        if column not in self.headers:
            return None
        column_index = self.headers.index(column)
        if not 0 <= row_index < len(self.rows):
            return None
        return self.rows[row_index][column_index]

    def unit_for(self, column: str) -> str | None:
        if column not in self.headers or not self.units:
            return None
        return self.units[self.headers.index(column)]

    @property
    def is_interpretable(self) -> bool:
        """Whether this table retains enough to read a value out of it (§6.22 rule 5)."""
        return bool(self.headers) and bool(self.rows)


class FigureContext(CoreModel):
    """§6.22 rule 6. A caption alone is not enough to read a figure.

    Stated as its own rule rather than folded into the table one because the failure differs: a
    table loses its header, a figure loses the body text that says what it shows. The spec is
    explicit that the caption does not suffice, which a table rule would not have implied.
    """

    #: The figure's own label -- ``"Figure 3"``, ``"Fig. 3b"``. What a citation points at.
    figure_label: str
    caption: str | None = None
    #: The body prose that discusses this figure. §6.22's "相關周邊說明文字": without it a caption
    #: reading "Cj versus reverse bias" says what the axes are and not what the figure shows.
    surrounding_prose: tuple[str, ...] = ()

    @property
    def is_interpretable(self) -> bool:
        return bool(self.caption) and bool(self.surrounding_prose)


class SegmenterProvenance(CoreModel):
    """Which segmenter drew these boundaries, so a bad version is selectable.

    The same reasoning as ``ExtractionProvenance``: §6.18 quarantines by version, and a unit that
    does not record which segmenter cut it cannot be found when that segmenter turns out to have
    been splitting conditions off results.
    """

    segmenter_id: str
    segmenter_version: str
    parser_id: str
    parser_version: str
    segmented_at: dt.datetime = Field(default_factory=utc_now)
    #: The token limit in force when this unit was produced. Recorded because rule 3(a)'s
    #: "exceeded the declared limit" is only checkable against the limit that was declared *then*.
    token_limit: int | None = Field(default=None, gt=0)


class EvidenceUnit(CoreModel):
    """One canonical unit of scientific evidence (§17.25).

    ``evidence_unit_id`` is derived, not supplied: it is recomputed on construction and a mismatch
    is rejected, exactly as ``Artifact`` does. So a unit whose id does not match its content cannot
    be built, deserialised or loaded from the database -- and re-segmenting unchanged bytes with an
    unchanged strategy produces the same ids rather than orphaning every Attestation.
    """

    evidence_unit_id: str
    project_id: str
    artifact_id: str
    source_work_id: str | None = None

    unit_type: EvidenceUnitType
    #: Position in the document's structure: ``"3/3.2/table:2"``. Part of identity, so the same
    #: sentence appearing in an abstract and a conclusion is two units rather than one.
    structural_path: str
    locator: SourceLocator
    #: The canonical evidence body. This, and never a retrieval payload, is what an Attestation
    #: is made from.
    body: str
    content_digest: str

    #: Rule 3(a) fallback lineage. Set together or not at all -- see the validator.
    parent_unit_id: str | None = None
    subdivision_index: int | None = Field(default=None, ge=0)
    subdivision_reason: SubdivisionReason | None = None
    #: Context inherited from the parent when this unit is a fallback subdivision. §6.22 rule 4
    #: requires sub-units to retain the parent's interpretive context; carrying it explicitly is
    #: what makes that checkable rather than a claim about the splitter's behaviour.
    inherited_context: tuple[str, ...] = ()

    conditions: dict[str, Any] = Field(default_factory=dict)
    conditions_schema_version: str | None = None
    #: The conditions this unit's result cannot be read without. §6.22 rule 1 is enforced against
    #: this list: a unit naming a bound condition whose text it does not contain has been split.
    bound_condition_texts: tuple[str, ...] = ()

    table_context: TableContext | None = None
    figure_context: FigureContext | None = None

    provenance: SegmenterProvenance
    created_at: dt.datetime = Field(default_factory=utc_now)

    #: Deliberately ABSENT: any embedding, vector or index reference. §17.25 puts those on
    #: `RetrievalRepresentation`, and `CoreModel` forbids extra fields, so adding one here is a
    #: ValidationError rather than a quietly accepted kwarg. This is the field whose absence
    #: ADR-0011 is about.

    @model_validator(mode="after")
    def _identity_is_derived_from_content(self) -> Self:
        parse_content_hash(self.content_digest)
        expected = evidence_unit_id_for(self.artifact_id, self.structural_path, self.content_digest)
        if self.evidence_unit_id != expected:
            raise ValueError(
                f"evidence_unit_id {self.evidence_unit_id!r} is not the derived identity of "
                f"(artifact={self.artifact_id!r}, path={self.structural_path!r}, "
                f"digest={self.content_digest!r}); expected {expected!r}. Evidence identity is "
                "computed from content, never assigned (§17.25, ADR-0011)"
            )
        return self

    @model_validator(mode="after")
    def _digest_matches_the_body(self) -> Self:
        """The body and its digest must agree, or identity means nothing.

        Without this the digest is a free parameter: a unit could carry one body and be addressed
        as another, which is exactly the substitution the admission path re-loads units to prevent.
        """
        if self.content_digest != compute_content_hash(self.body.encode("utf-8")):
            raise ValueError(
                "content_digest does not match body; the unit's identity would address content "
                "it does not hold"
            )
        return self

    @model_validator(mode="after")
    def _subdivision_lineage_is_complete(self) -> Self:
        """A fallback subdivision declares all three facts about itself, or none (§6.22 rule 3-4).

        Partial lineage is the failure mode worth blocking: a sub-unit with a parent and no reason
        is indistinguishable from one produced by a token splitter that simply recorded a parent,
        which is the practice rule 3 exists to forbid.
        """
        declared = [self.parent_unit_id, self.subdivision_index, self.subdivision_reason]
        present = [field for field in declared if field is not None]
        if present and len(present) != 3:
            raise ValueError(
                "a subdivided unit must declare parent_unit_id, subdivision_index and "
                f"subdivision_reason together; got parent={self.parent_unit_id!r}, "
                f"index={self.subdivision_index!r}, reason={self.subdivision_reason!r}"
            )
        if self.parent_unit_id == self.evidence_unit_id:
            raise ValueError("a unit must not be its own parent")
        if self.inherited_context and self.parent_unit_id is None:
            raise ValueError(
                "inherited_context is set on a unit with no parent; context is inherited from a "
                "parent unit or it is this unit's own body"
            )
        return self

    @model_validator(mode="after")
    def _typed_context_matches_the_unit_type(self) -> Self:
        """A TABLE unit carries table context; a FIGURE unit carries figure context.

        Checked in both directions. A TABLE with no ``table_context`` has lost its headers and
        units, which is rule 5's exact failure; a PROSE unit carrying ``table_context`` means the
        segmenter mislabelled something, and the mislabel would propagate into retrieval.
        """
        if self.unit_type is EvidenceUnitType.TABLE and self.table_context is None:
            raise ValueError(
                "a TABLE evidence unit must carry table_context; without headers, units and "
                "row/column context its values cannot be interpreted (§6.22 rule 5)"
            )
        if self.unit_type is EvidenceUnitType.FIGURE and self.figure_context is None:
            raise ValueError(
                "a FIGURE evidence unit must carry figure_context; a caption alone is not "
                "sufficient to read a figure (§6.22 rule 6)"
            )
        if self.unit_type is not EvidenceUnitType.TABLE and self.table_context is not None:
            raise ValueError(f"{self.unit_type} unit carries table_context; only TABLE may")
        if self.unit_type is not EvidenceUnitType.FIGURE and self.figure_context is not None:
            raise ValueError(f"{self.unit_type} unit carries figure_context; only FIGURE may")
        return self

    @model_validator(mode="after")
    def _bound_conditions_are_present_in_the_body(self) -> Self:
        """THE boundary check (§6.22 rule 1, EVI-010).

        A unit may declare that its result cannot be read without certain conditions. If it
        declares one and does not contain it, the condition was separated from the result it
        qualifies -- which is the split this whole requirement exists to prevent, and the one that
        is undetectable downstream because nothing is missing from the record.

        A subdivided unit satisfies the check through ``inherited_context`` too: rule 3(a) allows
        an oversized unit to be cut, and rule 4 requires the pieces to keep the parent's context,
        so a condition carried in inherited context is still bound to the result.
        """
        available = self.body + "\n" + "\n".join(self.inherited_context)
        severed = [text for text in self.bound_condition_texts if text not in available]
        if severed:
            raise ValueError(
                f"evidence unit {self.structural_path!r} declares conditions it does not contain: "
                f"{severed!r}. The result has been separated from what makes it interpretable "
                "(§6.22 rule 1). Nothing downstream can detect this, because no field is missing."
            )
        return self

    @classmethod
    def build(
        cls,
        *,
        project_id: str,
        artifact_id: str,
        unit_type: EvidenceUnitType,
        structural_path: str,
        locator: SourceLocator,
        body: str,
        provenance: SegmenterProvenance,
        **extra: Any,
    ) -> EvidenceUnit:
        """Construct a unit, deriving the digest and identity from ``body``.

        The only ergonomic constructor, for the same reason ``Artifact.from_bytes`` is: the
        ordinary path then cannot produce a unit whose identity disagrees with its content.
        """
        digest = compute_content_hash(body.encode("utf-8"))
        return cls(
            evidence_unit_id=evidence_unit_id_for(artifact_id, structural_path, digest),
            project_id=project_id,
            artifact_id=artifact_id,
            unit_type=unit_type,
            structural_path=structural_path,
            locator=locator,
            body=body,
            content_digest=digest,
            provenance=provenance,
            **extra,
        )

    @property
    def is_subdivision(self) -> bool:
        return self.parent_unit_id is not None

    @property
    def interpretive_text(self) -> str:
        """Body plus inherited context -- everything a reader has when reading this unit."""
        if not self.inherited_context:
            return self.body
        return self.body + "\n" + "\n".join(self.inherited_context)


class RetrievalRepresentation(CoreModel):
    """What one index holds about one unit (§17.25). Derived, disposable, never evidence.

    Carries the embedding fields so ``EvidenceUnit`` does not have to. Deleting every row of these
    for an ``index_id`` must leave every ``EvidenceUnit`` byte-identical -- that property is what
    ADR-0011 buys, and ``test_rebuilding_an_index_changes_no_evidence_identity`` is what holds it.
    """

    representation_id: str = Field(default_factory=lambda: new_id("retrieval_representation"))
    evidence_unit_id: str
    project_id: str

    index_id: str
    index_kind: RetrievalIndexKind

    #: EVI-007's compatibility keys. Unset for a LEXICAL index, and that is not a missing value:
    #: a BM25 index has no embedding space to be incompatible with.
    embedding_model: str | None = None
    embedding_version: str | None = None
    dimensions: int | None = Field(default=None, gt=0)

    #: Digest of the body AS INDEXED. Present so divergence from the canonical body is
    #: *detectable*, not so it can be trusted -- §17.25 is explicit that on disagreement the
    #: canonical body wins. See `IndexDivergence` in the retriever.
    payload_digest: str
    built_at: dt.datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def _embedding_fields_travel_together(self) -> Self:
        """A dense index names its space completely, or EVI-007 cannot filter on it."""
        declared = [self.embedding_model, self.embedding_version]
        if self.index_kind is RetrievalIndexKind.LEXICAL:
            if any(field is not None for field in (*declared, self.dimensions)):
                raise ValueError(
                    "a LEXICAL representation declares embedding model/version/dimensions; a "
                    "lexical index has no embedding space, and recording one invites a later "
                    "cosine comparison against it (EVI-007)"
                )
            return self
        if any(field is None for field in declared):
            raise ValueError(
                f"{self.index_kind} representation must name both embedding_model and "
                f"embedding_version; got {self.embedding_model!r} / {self.embedding_version!r}. "
                "Retrieval MUST filter by compatible model+version (EVI-007), which an "
                "unidentified space makes impossible"
            )
        return self

    @model_validator(mode="after")
    def _payload_digest_is_wellformed(self) -> Self:
        parse_content_hash(self.payload_digest)
        return self


class RetrievalCandidate(CoreModel):
    """One retrieval hit: an identifier and a score. Deliberately not a body (§17.25).

    This class is small on purpose, and its smallness is the requirement. Give it a ``body`` field
    and the admission path can read evidence out of the retriever's output, which is the thing
    EVI-010 forbids -- so there is nothing here to read. Resolution goes through
    ``CandidateResolver``, which re-loads the canonical unit by id.
    """

    evidence_unit_id: str
    representation_id: str
    project_id: str
    score: float
    rank: int = Field(ge=1)
    retrieval_trace_id: str | None = None


__all__ = [
    "EvidenceUnit",
    "FigureContext",
    "RetrievalCandidate",
    "RetrievalRepresentation",
    "SegmenterProvenance",
    "SourceLocator",
    "TableContext",
]
