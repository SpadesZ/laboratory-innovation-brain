"""The structural intermediate every parser produces and the segmenter consumes (§6.22).

WHY AN INTERMEDIATE AT ALL. §6.22 requires segmentation to be structure-first, which only means
something if "structure" is a thing the segmenter can see. Wire the segmenter to a Markdown AST
and the rule becomes a property of Markdown; wire it to a PDF layout model and it becomes a
property of that library's idea of a paragraph. Either way the *evidence* semantics change when
the file format does, which is the one thing that must not happen -- a table's header is load
bearing whether it arrived as a pipe table, a PDF ruling line or a CSV.

So parsers produce this, and only this. A later PDF or DOCX parser is conformant when it can fill
these blocks; it needs no say in where evidence boundaries fall.

WHAT IS DELIBERATELY NOT HERE. Fonts, coordinates, styling, and any notion of a page's visual
layout. Those are how a document *looks*; the segmenter needs to know what it *is*. Keeping them
out also keeps the intermediate honest about what a plain-text source can supply -- a Markdown
file has no pages, and a block that had to invent one would be inventing provenance.
"""

from __future__ import annotations

from typing import Self

from pydantic import Field, model_validator

from lab_brain.core.models.base import CoreModel
from lab_brain.core.models.enums import EvidenceUnitType


class ParsedBlock(CoreModel):
    """One structural element of a document, in reading order.

    Blocks are flat with an explicit ``section_path`` rather than nested, because the segmenter
    walks them in order and needs to ask "same section?" far more often than "what are this
    section's children?". A tree would make the common question a traversal.
    """

    #: Index in reading order. Part of the structural path, so it survives into evidence identity.
    index: int = Field(ge=0)
    block_type: EvidenceUnitType
    #: Heading trail, outermost first: ``("3", "3.2")``. Empty for content before any heading.
    section_path: tuple[str, ...] = ()
    #: Heading titles matching ``section_path`` positionally, for a human-readable locator.
    section_titles: tuple[str, ...] = ()
    text: str
    #: Character offsets into the source text this block was parsed from.
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=0)

    #: TABLE only. Raw grid, headers first; units row separated by the parser when present.
    table_headers: tuple[str, ...] = ()
    table_units: tuple[str | None, ...] = ()
    table_row_labels: tuple[str, ...] = ()
    table_rows: tuple[tuple[str, ...], ...] = ()
    table_caption: str | None = None

    #: FIGURE only.
    figure_label: str | None = None
    figure_caption: str | None = None

    #: Page, when the source format has pages. ``None`` means the format has none.
    page: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _offsets_are_ordered(self) -> Self:
        if self.end_offset < self.start_offset:
            raise ValueError(
                f"block {self.index} ends at {self.end_offset} before it starts at "
                f"{self.start_offset}"
            )
        return self

    @model_validator(mode="after")
    def _section_path_and_titles_align(self) -> Self:
        if self.section_titles and len(self.section_titles) != len(self.section_path):
            raise ValueError(
                f"block {self.index} has {len(self.section_path)} section path segments but "
                f"{len(self.section_titles)} titles"
            )
        return self

    @model_validator(mode="after")
    def _typed_fields_match_the_block_type(self) -> Self:
        """A parser that fills table fields on a prose block has mislabelled something.

        Caught here rather than in the segmenter: the segmenter's job is deciding boundaries, and
        it should be able to trust that a TABLE block has a header row. A mislabelled block that
        reached it would produce a unit that passes every later check while meaning nothing.
        """
        if self.block_type is EvidenceUnitType.TABLE and not self.table_headers:
            raise ValueError(
                f"block {self.index} is a TABLE with no headers; a table whose columns are "
                "unnamed cannot have its values interpreted (§6.22 rule 5)"
            )
        if self.block_type is EvidenceUnitType.FIGURE and not self.figure_label:
            raise ValueError(
                f"block {self.index} is a FIGURE with no label; a figure that cannot be named "
                "cannot be cited"
            )
        if self.block_type is not EvidenceUnitType.TABLE and self.table_headers:
            raise ValueError(f"block {self.index} is {self.block_type} but carries table headers")
        if self.block_type is not EvidenceUnitType.FIGURE and self.figure_label:
            raise ValueError(f"block {self.index} is {self.block_type} but carries a figure label")
        return self

    @property
    def section_label(self) -> str:
        """``"§3.2 Bias dependence"`` — the human half of a locator."""
        if not self.section_path:
            return "(preamble)"
        number = ".".join(self.section_path)
        title = self.section_titles[-1] if self.section_titles else ""
        return f"§{number} {title}".strip()

    @property
    def structural_key(self) -> str:
        """``"3/3.2/table:7"`` — stable under re-parsing, and part of evidence identity."""
        prefix = "/".join(self.section_path) if self.section_path else "_"
        return f"{prefix}/{self.block_type.value.lower()}:{self.index}"


class ParsedDocument(CoreModel):
    """A whole document reduced to ordered blocks plus its source-work metadata.

    ``source_metadata`` is free-form on purpose. It is what the parser could read off the document
    -- DOI, title, version -- and it is *input to* source-work resolution rather than a resolved
    identity. Typing it here would mean this module deciding what makes two documents the same
    work, which is EVI-004's judgement and lives in ``source_work_resolution``.
    """

    artifact_id: str
    #: The text the offsets index into. Kept so a locator can be resolved without re-parsing.
    source_text: str
    blocks: tuple[ParsedBlock, ...]
    parser_id: str
    parser_version: str
    source_metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _blocks_are_in_reading_order(self) -> Self:
        indices = [block.index for block in self.blocks]
        if indices != sorted(indices):
            raise ValueError("blocks must be in reading order; segmentation depends on adjacency")
        if len(set(indices)) != len(indices):
            duplicates = sorted({i for i in indices if indices.count(i) > 1})
            raise ValueError(f"duplicate block indices: {duplicates}")
        return self

    def blocks_of(self, *types: EvidenceUnitType) -> tuple[ParsedBlock, ...]:
        wanted = set(types)
        return tuple(block for block in self.blocks if block.block_type in wanted)

    def block_at(self, index: int) -> ParsedBlock | None:
        for block in self.blocks:
            if block.index == index:
                return block
        return None


__all__ = ["ParsedBlock", "ParsedDocument"]
