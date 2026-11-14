"""Parsers: source format in, §6.22 structural intermediate out.

Every parser targets ``structure.ParsedDocument`` and nothing downstream knows which one ran. A
later PDF or DOCX parser is conformant when it can fill these blocks; it gets no say in where
evidence boundaries fall, which is what keeps ``EVI-010``'s semantics from becoming a property of
whichever library read the file (§6.22, ADR-0011).
"""

from lab_brain.ingestion.parsers.documents import (
    PARSER_ID,
    PARSER_VERSION,
    DocumentParseError,
    MarkdownDocumentParser,
)
from lab_brain.ingestion.parsers.structure import ParsedBlock, ParsedDocument

__all__ = [
    "PARSER_ID",
    "PARSER_VERSION",
    "DocumentParseError",
    "MarkdownDocumentParser",
    "ParsedBlock",
    "ParsedDocument",
]
