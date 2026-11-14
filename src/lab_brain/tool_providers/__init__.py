"""Backend-bound providers: `run_*` implementations only (§18, §24.2).

NOTHING IN CORE IMPORTS THIS PACKAGE, and nothing here imports a DomainPack. A provider implements
`lab_brain.tools.simulation.SimulationBackend` and knows about arrays and manifests; which physical
quantity those arrays represent is the DomainPack's business, and which solver produced them is
core's business not to know (§24.1).

The only provider wired in this repository is a deterministic mock. See
`lab_brain.tool_providers.lumerical` for what that does and does not claim.
"""
