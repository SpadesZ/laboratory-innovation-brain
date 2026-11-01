"""The offline Discovery Loop (v0): distinct mechanisms, anomalies, reframing, no confirmation.

    model         vocabularies and frozen records -- no CONFIRMED state exists
    catalog       a domain's declared experiments and typed mechanism classes
    numerics      exact box-constrained least squares and the chi-square tail
    forward       predictions and fits of a hypothesis against observations
    distinguish   the separation statistic and indistinguishability classes
    protocol      the pre-registered thresholds and feature switches (the benchmark's arms)
    loop          `investigate`: evaluate, notice, test, reframe, claim or stop
    baselines     B0, the single-hypothesis baseline (a deterministic stand-in, not a model)
    handover      the typed packet for the Causal Warrant Gate, and draft certificates
    worlds        seeded synthetic worlds for offline evaluation
    metrics       scoring that counts distinguishable classes, never hypotheses
    benchmark     matched-budget arms over a scenario's worlds, frozen by a manifest

The engine is domain-agnostic: it imports no DomainPack and names no physical quantity
(`tests/unit/test_discovery_governance.py`). A scenario -- for example the silicon-photonics ring
catalog in `lab_brain.domains.silicon_photonics.discovery_catalog` -- is handed to it as data.
"""
