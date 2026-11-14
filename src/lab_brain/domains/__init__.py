"""DomainPack extension point (§11, §24).

    §24.2  FORBIDDEN:  core -> domains.silicon_photonics

So `lab_brain.core` imports nothing from here, and nothing here is imported by core. This package
holds the protocol and the registry; `domains.silicon_photonics` is one pack, and a second one
lives in `tests/toy_domain.py` deliberately -- EXT-001 asks whether a domain can be added without
touching core, and a toy domain shipped inside `src/` would be a domain core already knows about.
"""

from lab_brain.domains.base import (
    BenchmarkRegistry,
    DomainInstallError,
    DomainPack,
    DomainRegistries,
    DomainValidator,
    ExtractorRegistry,
    ValidatorRegistry,
)
from lab_brain.domains.registry import DomainPackRegistry

__all__ = [
    "BenchmarkRegistry",
    "DomainInstallError",
    "DomainPack",
    "DomainPackRegistry",
    "DomainRegistries",
    "DomainValidator",
    "ExtractorRegistry",
    "ValidatorRegistry",
]
