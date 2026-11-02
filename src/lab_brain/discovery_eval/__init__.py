"""Evaluation tooling for the offline Discovery Loop, kept outside the frozen engine package.

    blind          a laboratory that exposes only `motivating` and `measure`, a cost meter that
                   counts what the laboratory actually ran, and a check that no truth string is
                   reachable from what the engine is handed
    curves         realized-cost / cost-discovery curves over a budget grid: realized (not nominal)
                   cost, area under the curve, budget-to-first-correct, paired tests with a
                   multiplicity correction, and the cap invariants that hold by construction
    held_out       worlds whose true mechanism family is removed from the engine's catalog and
                   prior; the correct outcome there is no claim, and a claim is a force-fit
    hidden_worlds  the documented format in which a DIFFERENT author supplies sealed hidden worlds:
                   schema, loader, validation that refuses truth leaking into the engine's inputs,
                   commit-then-reveal sealing, a blind runner and the evaluator's scorer

WHY A SEPARATE PACKAGE. `lab_brain.discovery` is frozen by the 2026-11-01 evidence manifest, which
hashes every file in that directory; a new module there would invalidate it. This package only
reads the engine (`investigate`, the B0 baseline, the separation oracle, the scorer's class rule)
and adds nothing to it. Like the engine, it imports no DomainPack: the scenario is handed in by the
composition root (`scripts/discovery_independent_eval.py`).

WHAT THE NUMBERS ARE. Engineering evidence about the engine's behaviour on synthetic worlds written
by the same author lineage as the engine. Not scientific validity, not an independent evaluation,
and nothing about a real device, real literature or a language model. The protocol for a genuinely
independent evaluation is `docs/evaluation/discovery-independent-evaluation-protocol.md`.
"""
