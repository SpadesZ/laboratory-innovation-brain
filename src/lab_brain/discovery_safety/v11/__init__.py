"""Out-of-catalog safety v1.1: the v1.0 gate with a refit fixpoint and localized checks.

    model   `SafetyProtocolV11` (v1.0's thresholds plus the v1.1 additions, hashed), the new
            records (localized checks, the refit trace) and the pre-registered evaluation plan
    gate    `safe_investigate_v11`: v1.0's gate, subclassed; coverage is judged against every signal
            set the refits produced, and adequacy adds per-experiment checks (Holm)
    evaluation  arms B2 (frozen engine), B3 (v1.0) and B4 (v1.1) on the same worlds, scored per
            arm and per budget, plus realized-cost checkpoints

v1.0 (`lab_brain.discovery_safety`, the files directly in that directory) is frozen by its evidence
manifest and is not edited: this subpackage only imports it. Discovery stays offline and is not
connected to real research execution.

WHAT THE NUMBERS ARE. ENGINEERING EVIDENCE ONLY, on developer-authored synthetic worlds; the
held-out families were declared in the catalog the engine was developed against. Scientific
acceptance and G-D: NOT PASSED.
"""
