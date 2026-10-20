"""A local Markdown/plain-text parser producing the §6.22 structural intermediate.

Scope, stated plainly: this handles local Markdown and plain text. It is deliberately the
smallest adapter that can exercise every block type the segmenter distinguishes -- headings,
prose, pipe tables with a units row, figure captions, fenced code and log blocks.

WHY NO PDF. A PDF stack is a heavy dependency with a layout model of its own, and M1-P1's job is
to fix the *evidence* semantics so a later parser inherits them. Adding OCR to satisfy a fixture
would buy nothing the fixture proves and would couple the first segmentation contract to one
library's idea of a paragraph. The intermediate is what a PDF parser will target.

WHAT THIS PARSER MAY NOT DO. Invent scientific values (EVI-002). A table cell that is empty, or a
units row that is absent, is reported as absent -- ``None`` for a missing unit, no row for a
missing row. It never supplies a typical voltage, a default unit or a plausible temperature
because the shape of the table suggests one.
"""

from __future__ import annotations

import re

from lab_brain.core.models.enums import EvidenceUnitType
from lab_brain.ingestion.parsers.structure import ParsedBlock, ParsedDocument

PARSER_ID = "local_markdown"
PARSER_VERSION = "1.0.0"

_HEADING = re.compile(r"^(#{1,6})\s+(?:(\d+(?:\.\d+)*)\.?\s+)?(.*)$")
_FENCE = re.compile(r"^```\s*([A-Za-z0-9_+-]*)\s*$")
_TABLE_DIVIDER = re.compile(r"^\|[\s:|-]+\|$")
_FIGURE_CAPTION = re.compile(
    r"^\s*(?:!\[[^\]]*\]\([^)]*\)\s*)?(?P<label>Fig(?:ure)?\.?\s*\d+[a-z]?)\s*[.:—-]\s*"
    r"(?P<caption>.+)$",
    re.IGNORECASE,
)
_TABLE_CAPTION = re.compile(
    r"^\s*(?P<label>Table\s*\d+[a-z]?)\s*[.:—-]\s*(?P<caption>.+)$", re.IGNORECASE
)

#: Fence languages treated as machine output rather than source. A log block and a code block are
#: both atomic, but they are different evidence: one is what a program *is*, the other what it
#: *did*.
_LOG_LANGUAGES = frozenset({"log", "logs", "output", "console", "stdout", "stderr", "text"})

#: Heuristic for an un-fenced log block: several consecutive lines that look like timestamped or
#: level-prefixed machine output.
_LOG_LINE = re.compile(
    r"^\s*(?:\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}|\[?(?:INFO|WARN|WARNING|ERROR|DEBUG|TRACE)\]?\b)"
)


class DocumentParseError(RuntimeError):
    """The source could not be parsed into the structural intermediate."""


def _split_row(line: str) -> tuple[str, ...]:
    return tuple(cell.strip() for cell in line.strip().strip("|").split("|"))


def _looks_like_units_row(cells: tuple[str, ...]) -> bool:
    """A units row is short, bracketed or unit-shaped, and carries no digits.

    Conservative: when in doubt this returns False and the row is kept as data. Misreading a data
    row as units would delete a measurement; misreading a units row as data leaves the units
    unextracted, which the table-context validator then reports rather than hides.
    """
    filled = [cell for cell in cells if cell and cell not in {"-", "—"}]
    if not filled:
        return False
    if any(re.search(r"\d", cell) for cell in filled):
        return False
    bracketed = all(re.fullmatch(r"[\[(].+[\])]", cell) for cell in filled)
    short = all(len(cell) <= 12 for cell in filled)
    return bracketed or short


def _clean_unit(cell: str) -> str | None:
    """Normalise a units cell. Empty or a dash means *this column has no unit*, not unknown."""
    value = cell.strip().strip("[]()")
    if not value or value in {"-", "—", "–"}:
        return None
    return value


class MarkdownDocumentParser:
    """Parse Markdown/plain text into ``ParsedDocument``. Deterministic; no I/O."""

    parser_id = PARSER_ID
    parser_version = PARSER_VERSION

    def parse(
        self,
        text: str,
        *,
        artifact_id: str,
        source_metadata: dict[str, str] | None = None,
    ) -> ParsedDocument:
        lines = text.splitlines(keepends=True)
        offsets: list[int] = []
        running = 0
        for line in lines:
            offsets.append(running)
            running += len(line)
        offsets.append(running)

        blocks: list[ParsedBlock] = []
        section_path: list[str] = []
        section_titles: list[str] = []
        index = 0
        cursor = 0
        # Front-matter style metadata, e.g. `doi: 10.1000/xyz` before the first heading.
        metadata: dict[str, str] = dict(source_metadata or {})
        pending_caption: tuple[str, str] | None = None

        while cursor < len(lines):
            raw = lines[cursor]
            stripped = raw.strip()

            if not stripped:
                cursor += 1
                continue

            heading = _HEADING.match(stripped)
            if heading:
                hashes, number, title = heading.groups()
                depth = len(hashes)
                number = number or str(depth)
                section_path = section_path[: depth - 1]
                section_titles = section_titles[: depth - 1]
                section_path.append(number.split(".")[-1] if "." in number else number)
                section_titles.append(title.strip())
                blocks.append(
                    ParsedBlock(
                        index=index,
                        block_type=EvidenceUnitType.SECTION,
                        section_path=tuple(section_path),
                        section_titles=tuple(section_titles),
                        text=title.strip(),
                        start_offset=offsets[cursor],
                        end_offset=offsets[cursor + 1],
                    )
                )
                index += 1
                cursor += 1
                continue

            fence = _FENCE.match(stripped)
            if fence:
                language = (fence.group(1) or "").lower()
                start = cursor
                cursor += 1
                while cursor < len(lines) and not _FENCE.match(lines[cursor].strip()):
                    cursor += 1
                if cursor >= len(lines):
                    raise DocumentParseError(
                        f"unterminated code fence opened at line {start + 1}; the block's extent "
                        "is undefined and a locator over it would be a guess"
                    )
                body = "".join(lines[start + 1 : cursor]).rstrip("\n")
                block_type = (
                    EvidenceUnitType.LOG if language in _LOG_LANGUAGES else EvidenceUnitType.CODE
                )
                blocks.append(
                    ParsedBlock(
                        index=index,
                        block_type=block_type,
                        section_path=tuple(section_path),
                        section_titles=tuple(section_titles),
                        text=body,
                        start_offset=offsets[start],
                        end_offset=offsets[min(cursor + 1, len(lines))],
                    )
                )
                index += 1
                cursor += 1
                continue

            if stripped.startswith("|"):
                block, cursor = self._parse_table(
                    lines,
                    offsets,
                    cursor,
                    index,
                    tuple(section_path),
                    tuple(section_titles),
                    pending_caption,
                )
                blocks.append(block)
                pending_caption = None
                index += 1
                continue

            figure = _FIGURE_CAPTION.match(stripped)
            if figure:
                label = re.sub(r"\s+", " ", figure.group("label")).rstrip(".").strip()
                blocks.append(
                    ParsedBlock(
                        index=index,
                        block_type=EvidenceUnitType.FIGURE,
                        section_path=tuple(section_path),
                        section_titles=tuple(section_titles),
                        text=stripped,
                        start_offset=offsets[cursor],
                        end_offset=offsets[cursor + 1],
                        figure_label=label,
                        figure_caption=figure.group("caption").strip(),
                    )
                )
                index += 1
                cursor += 1
                continue

            table_caption = _TABLE_CAPTION.match(stripped)
            if table_caption:
                # Held for the table that follows rather than emitted: a caption is not evidence
                # on its own, and attaching it to the table is rule 5's "row/column context".
                pending_caption = (
                    table_caption.group("label").strip(),
                    table_caption.group("caption").strip(),
                )
                cursor += 1
                continue

            if ":" in stripped and not section_path and len(stripped) < 200:
                key, _, value = stripped.partition(":")
                if re.fullmatch(r"[A-Za-z][A-Za-z0-9_ -]{0,40}", key.strip()):
                    metadata.setdefault(key.strip().lower(), value.strip())
                    cursor += 1
                    continue

            start = cursor
            while cursor < len(lines):
                nxt = lines[cursor].strip()
                if not nxt or nxt.startswith("|") or _FENCE.match(nxt) or _HEADING.match(nxt):
                    break
                if _FIGURE_CAPTION.match(nxt) and cursor != start:
                    break
                cursor += 1
            body = " ".join(line.strip() for line in lines[start:cursor] if line.strip())
            is_log = sum(bool(_LOG_LINE.match(line)) for line in lines[start:cursor]) >= 2
            blocks.append(
                ParsedBlock(
                    index=index,
                    block_type=EvidenceUnitType.LOG if is_log else EvidenceUnitType.PROSE,
                    section_path=tuple(section_path),
                    section_titles=tuple(section_titles),
                    text="".join(lines[start:cursor]).strip() if is_log else body,
                    start_offset=offsets[start],
                    end_offset=offsets[cursor],
                )
            )
            index += 1

        return ParsedDocument(
            artifact_id=artifact_id,
            source_text=text,
            blocks=tuple(blocks),
            parser_id=self.parser_id,
            parser_version=self.parser_version,
            source_metadata=metadata,
        )

    def _parse_table(
        self,
        lines: list[str],
        offsets: list[int],
        cursor: int,
        index: int,
        section_path: tuple[str, ...],
        section_titles: tuple[str, ...],
        caption: tuple[str, str] | None,
    ) -> tuple[ParsedBlock, int]:
        start = cursor
        rows: list[tuple[str, ...]] = []
        while cursor < len(lines) and lines[cursor].strip().startswith("|"):
            line = lines[cursor].strip()
            if not _TABLE_DIVIDER.match(line):
                rows.append(_split_row(line))
            cursor += 1

        if not rows:
            raise DocumentParseError(f"table at line {start + 1} parsed to zero rows")

        headers = rows[0]
        body_rows = rows[1:]
        units: tuple[str | None, ...] = ()
        if body_rows and _looks_like_units_row(body_rows[0]):
            units = tuple(_clean_unit(cell) for cell in body_rows[0])
            body_rows = body_rows[1:]

        # A leading label column is common ("Bias (V) | Cj | Rs"). Row labels are the first cell
        # when every row has one and the header for that column is empty or non-numeric.
        row_labels: tuple[str, ...] = ()
        if body_rows and headers and all(row and row[0] for row in body_rows):
            row_labels = tuple(row[0] for row in body_rows)

        return (
            ParsedBlock(
                index=index,
                block_type=EvidenceUnitType.TABLE,
                section_path=section_path,
                section_titles=section_titles,
                text="".join(lines[start:cursor]).strip(),
                start_offset=offsets[start],
                end_offset=offsets[min(cursor, len(lines))],
                table_headers=headers,
                table_units=units,
                table_row_labels=row_labels,
                table_rows=tuple(body_rows),
                table_caption=(f"{caption[0]}. {caption[1]}" if caption else None),
            ),
            cursor,
        )


__all__ = [
    "PARSER_ID",
    "PARSER_VERSION",
    "DocumentParseError",
    "MarkdownDocumentParser",
]
