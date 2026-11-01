"""A tiny, domain-free discovery catalog whose behaviour is known by construction, and helpers.

e.cheap  (cost 1)   x, y        a and b both move x; c, d, e, f all move y
e.split  (cost 2)   z           a moves z up, b moves it down: separates a from b
e.dear   (cost 50)  w           c moves w up, d down: separates c from d, never affordable
e.ideal  (unavailable)  v       d, e and f move v: the only thing that separates e from f

toy.a, toy.b, toy.c, toy.d   initial working set
toy.e, toy.f                 extended: identical on every AVAILABLE experiment
"""

from __future__ import annotations

from dataclasses import replace

from lab_brain.discovery.catalog import DiscoveryCatalog
from lab_brain.discovery.distinguish import SeparationOracle
from lab_brain.discovery.model import (
    Budget,
    DiscoveryResult,
    EntrySpec,
    ExperimentSpec,
    MechanismClass,
    MechanismKind,
    Tier,
    UnavailableExperiment,
)
from lab_brain.discovery.protocol import DISCOVERY, DiscoveryProtocol
from lab_brain.discovery.worlds import SyntheticWorld, WorldSpec

CHEAP = ExperimentSpec("e.cheap", "cheap", 1, (EntrySpec("x", "u", 1.0), EntrySpec("y", "u", 1.0)))
SPLIT = ExperimentSpec("e.split", "split", 2, (EntrySpec("z", "u", 1.0),))
DEAR = ExperimentSpec("e.dear", "dear", 50, (EntrySpec("w", "u", 1.0),))
IDEAL = UnavailableExperiment(
    ExperimentSpec("e.ideal", "ideal", 1, (EntrySpec("v", "u", 1.0),)), "not built here"
)


def mechanism(
    class_id: str,
    sensitivity: tuple[tuple[str, str, float], ...],
    *,
    tier: Tier = Tier.INITIAL,
    prior: float = 0.2,
    family: str | None = None,
    kind: MechanismKind = MechanismKind.PHYSICAL,
) -> MechanismClass:
    return MechanismClass(
        class_id=class_id,
        family=family or class_id,
        mechanism=f"mechanism {class_id}",
        regime="default",
        statement=f"{class_id} explains the observation.",
        kind=kind,
        tier=tier,
        parameter="amplitude",
        lower=1.0,
        upper=2.0,
        sensitivity=sensitivity,
        prior=prior,
    )


TOY_A = mechanism("toy.a", (("e.cheap", "x", 10.0), ("e.split", "z", 10.0)), prior=0.3)
TOY_B = mechanism("toy.b", (("e.cheap", "x", 10.0), ("e.split", "z", -10.0)))
TOY_C = mechanism("toy.c", (("e.cheap", "y", 10.0), ("e.dear", "w", 10.0)))
TOY_D = mechanism("toy.d", (("e.cheap", "y", 10.0), ("e.dear", "w", -10.0), ("e.ideal", "v", 10.0)))
TOY_E = mechanism("toy.e", (("e.cheap", "y", 10.0), ("e.ideal", "v", 10.0)), tier=Tier.EXTENDED)
TOY_F = mechanism("toy.f", (("e.cheap", "y", 10.0), ("e.ideal", "v", -10.0)), tier=Tier.EXTENDED)


def toy_catalog(
    *extra: MechanismClass, initial_ef: bool = False, with_cd: bool = True
) -> DiscoveryCatalog:
    e, f = TOY_E, TOY_F
    if initial_ef:
        e, f = replace(e, tier=Tier.INITIAL, prior=0.2), replace(f, tier=Tier.INITIAL, prior=0.2)
    cd = (TOY_C, TOY_D) if with_cd else ()
    return DiscoveryCatalog(
        catalog_id="toy.discovery",
        version="1.0.0",
        question="which toy mechanism moved the readings?",
        experiments=(CHEAP, SPLIT, DEAR),
        unavailable=(IDEAL,),
        mechanisms=(TOY_A, TOY_B, *cd, e, f, *extra),
    )


def toy_oracle(
    catalog: DiscoveryCatalog, protocol: DiscoveryProtocol = DISCOVERY
) -> SeparationOracle:
    return SeparationOracle(catalog, ("e.cheap", "e.split", "e.dear"), protocol)


def toy_world(truth: tuple[tuple[str, float], ...], seed: int = 7, **kwargs: object) -> WorldSpec:
    return WorldSpec(f"toy-{seed}", "toy", seed, truth, **kwargs)  # type: ignore[arg-type]


def run_toy(
    catalog: DiscoveryCatalog,
    world: WorldSpec,
    *,
    protocol: DiscoveryProtocol = DISCOVERY,
    budget: int = 12,
) -> DiscoveryResult:
    from lab_brain.discovery.loop import investigate

    return investigate(
        arm="toy",
        catalog=catalog,
        oracle=toy_oracle(catalog, protocol),
        protocol=protocol,
        budget=Budget(budget),
        lab=SyntheticWorld(world, catalog, "e.cheap"),
    )
