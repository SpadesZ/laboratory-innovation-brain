"""External source adapters and the router (SRC-001, §17.21).

Core cognition depends on `ExternalSourceRecord` and never on a provider. §24.2's boundary is
what keeps a vendor's schema change out of the middle of a scientific decision.
"""

from lab_brain.sources.adapter import (
    ExternalSourceAdapter,
    ExternalSourceRecord,
    ProviderUnavailable,
    SourceCapabilities,
    SourceHealthReport,
    SourceQuery,
    SourceRouter,
    SourceVisibility,
)

__all__ = [
    "ExternalSourceAdapter",
    "ExternalSourceRecord",
    "ProviderUnavailable",
    "SourceCapabilities",
    "SourceHealthReport",
    "SourceQuery",
    "SourceRouter",
    "SourceVisibility",
]
