# Claim revision figure

`python docs/assets/draw_claim_revision.py` uses Matplotlib to generate the
English-only SVG and PNG. No research result is drawn. The example is the toy
policy path in `tests/contract/test_belief_transition.py` and
`tests/contract/test_transition_policy.py`.

Sources: `src/lab_brain/core/belief.py`, `authority.py`, `escalation.py` and
`repositories/reviews.py`. The three toy cases compare support with two independent
attestations, no admitted support, and an open blocking conflict. Only ALLOW can
record a revision. A review does not itself promote a claim. The footer distinguishes
the core fixture from planned lab applications; no scientific result is depicted.

The original layout uses typography and vector-export guidance from
[figures4papers](https://github.com/ChenLiu-1996/figures4papers).
The generator checks label language, bounds and overlaps before export.
