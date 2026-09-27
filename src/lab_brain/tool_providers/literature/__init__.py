"""A literature provider behind the ExternalSourceAdapter boundary (local fixture corpus)."""

from lab_brain.tool_providers.literature.corpus import (
    PROVIDER_ID,
    LiteratureCorpusAdapter,
    declaration,
)

__all__ = ["PROVIDER_ID", "LiteratureCorpusAdapter", "declaration"]
