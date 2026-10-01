# Claim revision figure

`python docs/assets/draw_claim_revision.py` uses Matplotlib to generate the
English-only SVG and PNG. No research result is drawn. The example is the toy
policy path in `tests/contract/test_belief_transition.py` and
`tests/contract/test_transition_policy.py`.

Sources: `src/lab_brain/core/belief.py`, `authority.py`, `escalation.py` and
`repositories/reviews.py`. Solid arrows show evaluation; the dashed loop shows
human review and reconsideration. A review does not itself promote a claim.
The footer distinguishes the core from planned lab applications.

The original layout uses typography and vector-export guidance from
[figures4papers](https://github.com/ChenLiu-1996/figures4papers).
The generator checks label language, bounds and overlaps before export.
