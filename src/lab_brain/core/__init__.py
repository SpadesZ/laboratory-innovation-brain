"""Domain-agnostic core.

§24.2 dependency rule: this package MUST NOT import from ``lab_brain.domains.*``. A core module
that knows what Rs is has stopped being core, and EXT-001 -- adding a second domain without
modifying core -- becomes impossible to satisfy.
"""
