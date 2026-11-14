"""The Silicon Photonics DomainPack (§11, §24, §25).

Everything this domain knows lives under this directory. Core imports none of it -- §24.2's
FORBIDDEN edge -- and `tests/unit/test_extension_boundary.py` parses the import graph to keep that
true rather than asserting it in prose.

    condition_schema.py   bias / frequency / temperature / wavelength / geometry, and tolerances
    authority_policy.py   the fidelity partial order SIM-002 turns on, and §10.6's INCOMPARABLE
    backend_validity.py   SimulatorValidityV1 -- the fields SIM-001 refuses a manifest without
    extractors.py         extract_cj_rs, one reduction for simulated and measured alike
    validators.py         the Rs trend rule DOM-SP-001 requires core not to contain
    tools.py              the typed registry faces
    plugin.py             the §24.3 pack
"""

from lab_brain.domains.silicon_photonics.plugin import (
    PACK_ID,
    PACK_VERSION,
    SiliconPhotonicsPack,
)

__all__ = ["PACK_ID", "PACK_VERSION", "SiliconPhotonicsPack"]
