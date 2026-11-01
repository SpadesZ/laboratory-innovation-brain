"""A domain's declared discovery catalog: experiments (available or not) and typed mechanisms.

The catalog is DATA a domain pack declares; this module only checks that it is coherent:

    - experiment ids, entry ids and class ids are unique;
    - every tabulated sensitivity names a declared experiment and one of its entries;
    - the initial working set holds at least two mechanisms (one cannot compete).

It deliberately does NOT refuse two classes with the same forward model under different names. A
renamed duplicate is a real thing a catalog, a person or a model can produce; the engine's answer is
to merge it (`Origin`/`alias_of`, and equivalence classes in `distinguish`), and a test proves the
merge, which a refusal at declaration time would leave untested.
"""

from __future__ import annotations

from dataclasses import dataclass

from lab_brain.discovery.model import (
    ExperimentSpec,
    MechanismClass,
    MechanismKind,
    Tier,
    UnavailableExperiment,
    stable_digest,
)


@dataclass(frozen=True)
class DiscoveryCatalog:
    catalog_id: str
    version: str
    #: The question the catalog's mechanisms compete to answer.
    question: str
    experiments: tuple[ExperimentSpec, ...]
    unavailable: tuple[UnavailableExperiment, ...]
    mechanisms: tuple[MechanismClass, ...]

    def __post_init__(self) -> None:
        all_experiments = [*self.experiments, *(u.experiment for u in self.unavailable)]
        ids = [e.experiment_id for e in all_experiments]
        if len(set(ids)) != len(ids):
            raise ValueError(f"catalog {self.ref} declares an experiment twice")
        entries = {e.experiment_id: {n.entry_id for n in e.entries} for e in all_experiments}
        class_ids = [m.class_id for m in self.mechanisms]
        if len(set(class_ids)) != len(class_ids):
            raise ValueError(f"catalog {self.ref} declares a mechanism class twice")
        for mechanism in self.mechanisms:
            for experiment_id, entry_id, _ in mechanism.sensitivity:
                if entry_id not in entries.get(experiment_id, set()):
                    raise ValueError(
                        f"mechanism {mechanism.class_id} predicts {experiment_id}.{entry_id}, "
                        "which no declared experiment reports"
                    )
        if len(self.initial) < 2:
            raise ValueError("an initial working set of fewer than two mechanisms cannot compete")

    @property
    def ref(self) -> str:
        return f"{self.catalog_id}@{self.version}"

    @property
    def initial(self) -> tuple[MechanismClass, ...]:
        return tuple(m for m in self.mechanisms if m.tier is Tier.INITIAL)

    @property
    def variants(self) -> tuple[MechanismClass, ...]:
        return tuple(m for m in self.mechanisms if m.tier is Tier.VARIANT)

    @property
    def extended(self) -> tuple[MechanismClass, ...]:
        return tuple(m for m in self.mechanisms if m.tier is Tier.EXTENDED)

    @property
    def measurement_chain(self) -> tuple[MechanismClass, ...]:
        return tuple(m for m in self.mechanisms if m.kind is MechanismKind.MEASUREMENT_CHAIN)

    def mechanism(self, class_id: str) -> MechanismClass:
        return next(m for m in self.mechanisms if m.class_id == class_id)

    def experiment(self, experiment_id: str) -> ExperimentSpec:
        for e in self.experiments:
            if e.experiment_id == experiment_id:
                return e
        for u in self.unavailable:
            if u.experiment.experiment_id == experiment_id:
                return u.experiment
        raise KeyError(experiment_id)

    @property
    def digest(self) -> str:
        return stable_digest(self)


__all__ = ["DiscoveryCatalog"]
