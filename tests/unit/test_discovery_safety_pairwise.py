"""Pairwise indistinguishability is not transitive, and the safety layer never closes it.

The counterexample: one experiment, one entry of sigma 1, and three hypotheses predicting 0 (the
noise model), 0.75 and 1.5, with a threshold of 1. A~B (0.75 < 1) and B~C (0.75 < 1), yet A and C
are separated (1.5 >= 1). The frozen engine's `SeparationOracle.classes` takes the connected
component (all three in one class -- its documented conservative reading for a claim); the safety
layer's relations are pairs and direct neighbours only, and a renamed duplicate is one model.
"""

from __future__ import annotations

from dataclasses import replace

from lab_brain.discovery.catalog import DiscoveryCatalog
from lab_brain.discovery.distinguish import SeparationOracle
from lab_brain.discovery.model import (
    NULL_HYPOTHESIS,
    EntrySpec,
    ExperimentSpec,
    MechanismClass,
    MechanismKind,
    Tier,
    make_hypothesis,
)
from lab_brain.discovery.protocol import DISCOVERY
from lab_brain.discovery_safety.pairwise import (
    direct_neighbours,
    distinct_forward_models,
    indistinguishable_pairs,
)


def _mechanism(class_id: str, sensitivity: float) -> MechanismClass:
    return MechanismClass(
        class_id=class_id,
        family=class_id,
        mechanism=class_id,
        regime="fixed",
        statement=f"{class_id} predicts {sensitivity}",
        kind=MechanismKind.PHYSICAL,
        tier=Tier.INITIAL,
        parameter="a",
        lower=1.0,
        upper=1.0 + 1e-9,
        sensitivity=(("x", "y", sensitivity),),
        prior=0.5,
    )


B = _mechanism("toy.b", 0.75)
C = _mechanism("toy.c", 1.5)
CATALOG = DiscoveryCatalog(
    catalog_id="toy",
    version="1",
    question="toy",
    experiments=(ExperimentSpec("x", "one reading", 1, (EntrySpec("y", "u", 1.0),)),),
    unavailable=(),
    mechanisms=(B, C),
)
PROTOCOL = replace(DISCOVERY, distinguish_tau=1.0, distinguish_replicates=1)
ORACLE = SeparationOracle(CATALOG, ("x",), PROTOCOL)
HA, HB, HC = NULL_HYPOTHESIS, make_hypothesis(B), make_hypothesis(C)


def test_the_counterexample_holds_pairwise():
    assert not ORACLE.distinguishable(HA, HB)
    assert not ORACLE.distinguishable(HB, HC)
    assert ORACLE.distinguishable(HA, HC)


def test_the_safety_layer_keeps_pairs_and_never_merges_a_and_c():
    pairs = indistinguishable_pairs((HA, HB, HC), ORACLE)
    assert set(pairs) == {
        tuple(sorted((HA.hypothesis_id, HB.hypothesis_id))),
        tuple(sorted((HB.hypothesis_id, HC.hypothesis_id))),
    }
    assert tuple(sorted((HA.hypothesis_id, HC.hypothesis_id))) not in pairs
    assert direct_neighbours(HA, (HB, HC), ORACLE) == (HB.hypothesis_id,)
    assert direct_neighbours(HC, (HA, HB), ORACLE) == (HB.hypothesis_id,)
    assert direct_neighbours(HB, (HA, HC), ORACLE) == tuple(
        sorted((HA.hypothesis_id, HC.hypothesis_id))
    )


def test_the_frozen_engine_closure_differs_on_the_counterexample():
    """Documented, not changed: the engine's class is the transitive closure."""
    assert ORACLE.classes((HA, HB, HC)) == (
        tuple(sorted((HA.hypothesis_id, HB.hypothesis_id, HC.hypothesis_id))),
    )


def test_a_renamed_duplicate_is_one_forward_model():
    twin = make_hypothesis(replace(B, class_id="toy.b_renamed", family="toy.b_renamed"))
    assert twin.fingerprint == HB.fingerprint and twin.hypothesis_id != HB.hypothesis_id
    models = distinct_forward_models((HB, twin, HC))
    assert [h.hypothesis_id for h in models] == sorted((HB.hypothesis_id, HC.hypothesis_id))
    assert indistinguishable_pairs((HA, HB, twin, HC), ORACLE) == indistinguishable_pairs(
        (HA, HB, HC), ORACLE
    )
    assert direct_neighbours(HA, (HB, twin, HC), ORACLE) == (HB.hypothesis_id,)
