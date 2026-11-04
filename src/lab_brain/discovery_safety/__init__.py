"""Out-of-catalog safety for the offline Discovery Loop: never force-fit an available mechanism.

    model       the safety protocol (every threshold pre-declared and hashed), the decision and
                abstention vocabulary, and the frozen records an assessment is made of: adequacy
                tests, probes, a stage-1 new-family proposal, a discriminating-experiment request
    pairwise    distinguishability as a PAIRWISE relation. It is not transitive (predictions 0,
                0.75 and 1.5 with a threshold of 1: A~B and B~C, yet A and C are distinguishable),
                so nothing here merges hypotheses through a chain
    gate        `safe_investigate`: the frozen engine's investigation, then -- before anything is
                endorsed -- adequacy probes on experiments the claim has not been tested on, a
                pre-declared goodness-of-fit test against the noise model, replication of a failing
                probe, a catalog-completeness check over every hypothesis the catalog can express,
                and, when nothing declared is adequate: abstention, open anomaly records, a
                reframed question, a stage-1 proposal and a discriminating-experiment request
    evaluation  the held-out-family and in-catalog evaluations re-run with the safe arm (B3) next
                to the frozen arms, scored by the frozen scorers

WHY A SEPARATE PACKAGE. `lab_brain.discovery` is frozen by the 2026-11-01 evidence manifest and
`lab_brain.discovery_eval` by the 2026-11-02 one; both hash every file in their directory. This
package reads them and changes neither: the safe arm is a NEW, versioned decision layer over the
frozen engine, and the frozen arms and their recorded evidence stay exactly as they were.

WHAT THE NUMBERS ARE. Engineering evidence on synthetic worlds written by the same author lineage
as the engine. Not scientific validity, not an independent evaluation, and nothing about a real
device. Nothing here confirms anything: the best outcome is still "pending the Causal Warrant Gate".
"""
