"""Evaluator-controlled G0 evaluation: a workflow that can accept a sealed, independent holdout.

NO GENUINE INDEPENDENT HOLDOUT EXISTS YET. This package is the machinery an independent evaluator
would use; every fixture it is tested with is synthetic. The exposed `benchmarks/g0_screening`
cases are development/regression evidence (protocol amendment 1) and appear here only as the
reference corpus a new holdout must not overlap.

    packages        generator package vs sealed evaluator truth: two schemas, a fail-closed
                    generator loader, the allowlisted research inputs, the truth-leak scan
    sealing         salted per-case SHA-256 commitments and their root; reveal verification
    contamination   exact / n-gram text overlap, source and device family overlap, duplicated
                    experimental units -- against dev packages and the exposed screening cases
    manifest        the frozen protocol manifest (inputs, cases, commitments, scorer source
                    hashes, contamination findings, exclusions) and `score_run`, which refuses
                    on any drift
    scoring         the deterministic per-case rules and the honest-denominator summary
    stats           Wilson 95% interval and a seeded percentile bootstrap

Operator procedure: `docs/evaluation/G0-independent-holdout-workflow.md`.
"""
