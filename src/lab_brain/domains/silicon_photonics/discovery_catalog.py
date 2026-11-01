"""An offline discovery catalog for one silicon-photonics scenario: ring drift and extra loss.

WHAT THIS IS. A small, typed catalog the offline Discovery Loop (`lab_brain.discovery`) runs
against: twelve declared experiments a photonics lab might run on a silicon microring (one of them
unavailable here), and fourteen mechanism classes -- eleven parameter regimes of the ten mechanisms
a lab raises first for "the resonance has drifted and the ring is lossier than designed", plus three
it raises only when those fail. Each class has a cheap deterministic forward model: a function of
an experiment's declared conditions (powers, temperatures, widths, radii, gaps, wavelengths) that
returns how much each reported entry moves per unit of the class's one amplitude parameter.

WHAT THIS IS NOT. It is NOT calibrated physics and NOT product domain knowledge:

    - the sensitivities have the right SIGNS and the right qualitative dependences (thermo-optic
      drift scales with temperature and vanishes under a stabilised stage; scattering loss grows as
      the waveguide narrows and falls with wavelength; substrate leakage grows with wavelength and
      as the radius shrinks; free carriers blue-shift and absorb; a laser wavelength error moves
      every resonance and the gas-cell line alike) but their MAGNITUDES are toy numbers chosen for
      a sensible signal-to-noise structure;
    - it is not installed into the product vertical, registers nothing in any registry, adds no
      condition-schema field (`condition_schema.py` deliberately declares no ring radius, and this
      module does not change that), and is not a `DiagnosticDeclarationSet` a warrant may cite.
      Making any of it domain knowledge is a code-reviewed DomainPack change and an Owner decision
      (§23.4), not something an offline benchmark does by existing.

The worlds at the end hide a truth among these classes (or outside them) for the offline benchmark;
they were written by the same implementer as the engine, which is why the benchmark is engineering
evidence of algorithmic behaviour and nothing more.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from lab_brain.discovery.benchmark import Scenario
from lab_brain.discovery.catalog import DiscoveryCatalog
from lab_brain.discovery.model import (
    EntrySpec,
    ExperimentSpec,
    MechanismClass,
    MechanismKind,
    Tier,
    UnavailableExperiment,
)
from lab_brain.discovery.worlds import UndeclaredEffect, WorldSpec

CATALOG_ID: Final = "sp.ring_drift_loss.discovery"
CATALOG_VERSION: Final = "0.1.0"
MOTIVATING_EXPERIMENT: Final = "baseline"

#: Thermo-optic resonance coefficient of a silicon ring near 1550 nm, pm per kelvin (toy value).
THERMO_PM_PER_K: Final = 75.0
LAMBDA0_NM: Final = 1550.0

# -- experiments --------------------------------------------------------------------------------

_SHIFT = ("pm", 3.0)
_LOSS = ("dB/cm", 0.15)


def _e(entry_id: str, unit: str, sigma: float) -> EntrySpec:
    return EntrySpec(entry_id, unit, sigma)


EXPERIMENTS: Final[tuple[ExperimentSpec, ...]] = (
    ExperimentSpec(
        "baseline",
        "re-measure the ring transmission at low power, stage at its set point",
        1,
        (
            _e("shift", *_SHIFT),
            _e("loss", *_LOSS),
            _e("kappa", "%", 1.0),
            _e("il", "dB", 0.10),
        ),
        (("power_mw", "0.1"), ("wavelength_nm", "1550")),
    ),
    ExperimentSpec(
        "power_sweep",
        "measure at 0.1 mW and 1.0 mW on-chip; report the high-minus-low differences",
        1,
        (_e("dshift", *_SHIFT), _e("dloss", *_LOSS)),
        (("power_low_mw", "0.1"), ("power_high_mw", "1.0")),
    ),
    ExperimentSpec(
        "tec_stabilized",
        "re-measure with the chip actively stabilised at the reference temperature",
        2,
        (_e("shift", *_SHIFT), _e("loss", *_LOSS)),
        (("power_mw", "0.1"), ("stage", "TEC-locked at reference")),
    ),
    ExperimentSpec(
        "gas_cell_reference",
        "re-measure with the laser referenced to an HCN gas-cell line; report the ring shift "
        "and the apparent offset of the reference line",
        2,
        (_e("shift", "pm", 2.0), _e("refline", "pm", 1.5)),
        (("reference", "HCN gas cell"),),
        chain_check=True,
    ),
    ExperimentSpec(
        "fiber_recouple",
        "realign the fibre three times; report the insertion-loss spread and the intrinsic loss",
        1,
        (_e("il_spread", "dB", 0.05), _e("loss", *_LOSS)),
        (("realignments", "3"),),
        chain_check=True,
    ),
    ExperimentSpec(
        "polarization_controlled",
        "re-measure with a polariser and controller fixing TE input; report intrinsic loss and the "
        "change in extinction ratio",
        1,
        (_e("loss", *_LOSS), _e("er_change", "dB", 0.3)),
        (("input", "TE, controlled"),),
        chain_check=True,
    ),
    ExperimentSpec(
        "width_array",
        "measure sibling rings drawn 400 nm and 600 nm wide; report the narrow-minus-wide contrast",
        2,
        (_e("shift_contrast", "pm", 2.0), _e("loss_contrast", "dB/cm", 0.2)),
        (("widths_nm", "400,600"),),
    ),
    ExperimentSpec(
        "gap_array",
        "measure sibling rings with 150, 200 and 250 nm coupling gaps; report coupling deviations",
        2,
        (_e("kappa_g150", "%", 1.0), _e("kappa_g200", "%", 1.0), _e("kappa_g250", "%", 1.0)),
        (("gaps_nm", "150,200,250"),),
    ),
    ExperimentSpec(
        "radius_array",
        "measure sibling rings of 5 um and 20 um radius; report the small-minus-large loss "
        "contrast",
        2,
        (_e("loss_contrast", "dB/cm", 0.2),),
        (("radii_um", "5,20"),),
    ),
    ExperimentSpec(
        "wavelength_span",
        "measure resonances near 1500 nm and 1600 nm; report the long-minus-short differences",
        1,
        (_e("shift_span", "pm", 4.0), _e("loss_span", "dB/cm", 0.2)),
        (("wavelengths_nm", "1500,1600"),),
    ),
    ExperimentSpec(
        "cutback",
        "straight-waveguide cutback on the same die; report the excess propagation loss",
        3,
        (_e("loss_straight", "dB/cm", 0.1),),
        (("lengths_mm", "1,3,5"),),
    ),
)

ELLIPSOMETRY: Final = UnavailableExperiment(
    ExperimentSpec(
        "ellipsometry",
        "measure the silicon device-layer thickness directly",
        3,
        (_e("thickness_dev", "nm", 0.5),),
    ),
    "no ellipsometer in this lab",
)

# -- forward models -----------------------------------------------------------------------------

#: A forward model: experiment -> {entry: sensitivity per unit amplitude}.
Forward = Callable[[ExperimentSpec], Mapping[str, float]]


def _span_ratio(power: float) -> float:
    """(1600^p - 1500^p) / 1550^p: how a lambda^p dependence differs across the span."""
    return float((1600.0**power - 1500.0**power) / LAMBDA0_NM**power)


def _thermo_ambient(x: ExperimentSpec) -> Mapping[str, float]:
    k = THERMO_PM_PER_K
    return {
        "baseline": {"shift": k},
        # The stabilised stage removes an ambient offset.
        "tec_stabilized": {"shift": 0.0},
        "gas_cell_reference": {"shift": k},
        "wavelength_span": {"shift_span": k * _span_ratio(1.0)},
    }.get(x.experiment_id, {})


def _thermo_self_heating(x: ExperimentSpec) -> Mapping[str, float]:
    k = THERMO_PM_PER_K  # amplitude is K per mW absorbed
    low, high = 0.1, 1.0
    return {
        "baseline": {"shift": k * low},
        "power_sweep": {"dshift": k * (high - low)},
        # Self-heating persists under a stabilised stage: the heat is generated in the ring.
        "tec_stabilized": {"shift": k * low},
        "gas_cell_reference": {"shift": k * low},
    }.get(x.experiment_id, {})


def _fcd_static(x: ExperimentSpec) -> Mapping[str, float]:
    shift, loss = -30.0, 0.5  # per 1e17 cm^-3 (toy)
    return {
        "baseline": {"shift": shift, "loss": loss},
        "tec_stabilized": {"shift": shift, "loss": loss},
        "gas_cell_reference": {"shift": shift},
        "fiber_recouple": {"loss": loss},
        "polarization_controlled": {"loss": loss},
        "wavelength_span": {
            "shift_span": shift * _span_ratio(2.0),
            "loss_span": loss * _span_ratio(2.0),
        },
        "cutback": {"loss_straight": loss},
    }.get(x.experiment_id, {})


def _tpa_fca(x: ExperimentSpec) -> Mapping[str, float]:
    return {
        "baseline": {"loss": 0.08},
        "power_sweep": {"dloss": 0.8, "dshift": -3.0},
    }.get(x.experiment_id, {})


def _fca_dominated(x: ExperimentSpec) -> Mapping[str, float]:
    return {
        "baseline": {"shift": -0.2, "loss": 0.05},
        "power_sweep": {"dloss": 0.5, "dshift": -20.0},
    }.get(x.experiment_id, {})


def _sidewall(x: ExperimentSpec) -> Mapping[str, float]:
    loss = 0.8  # at 500 nm width, 1550 nm
    narrow, wide = 1.6, 0.6  # relative scattering at 400 nm and 600 nm width
    return {
        "baseline": {"loss": loss},
        "tec_stabilized": {"loss": loss},
        "fiber_recouple": {"loss": loss},
        "polarization_controlled": {"loss": loss},
        "width_array": {"loss_contrast": loss * (narrow - wide)},
        "radius_array": {"loss_contrast": loss * 0.3},
        # Scattering falls roughly as lambda^-2.
        "wavelength_span": {"loss_span": loss * _span_ratio(-2.0)},
        "cutback": {"loss_straight": loss},
    }.get(x.experiment_id, {})


def _width(x: ExperimentSpec) -> Mapping[str, float]:
    per_nm = 6.0  # pm of red shift per nm of extra width at 500 nm (toy)
    return {
        "baseline": {"shift": per_nm, "kappa": 0.8},
        "tec_stabilized": {"shift": per_nm},
        "gas_cell_reference": {"shift": per_nm},
        # Narrow guides are more width-sensitive: 9 pm/nm at 400 nm, 4 pm/nm at 600 nm.
        "width_array": {"shift_contrast": 9.0 - 4.0},
        "wavelength_span": {"shift_span": 0.8},
        # A wider guide closes the coupling gap: more coupling, most at the smallest gap.
        "gap_array": {"kappa_g150": 1.2, "kappa_g200": 0.8, "kappa_g250": 0.5},
    }.get(x.experiment_id, {})


def _thickness(x: ExperimentSpec) -> Mapping[str, float]:
    # Indistinguishable from a width deviation everywhere except where widths differ (and the
    # unavailable ellipsometer): a thicker layer shifts narrow and wide rings almost alike.
    shared = dict(_width(x))
    if x.experiment_id == "width_array":
        return {"shift_contrast": 6.5 - 5.5}
    if x.experiment_id == "ellipsometry":
        return {"thickness_dev": 1.0}
    return shared


def _gap(x: ExperimentSpec) -> Mapping[str, float]:
    # Amplitude is the gap error in nm (negative: too narrow, over-coupled).
    return {
        "baseline": {"kappa": -0.25},
        "gap_array": {"kappa_g150": -0.35, "kappa_g200": -0.25, "kappa_g250": -0.18},
    }.get(x.experiment_id, {})


def _substrate(x: ExperimentSpec) -> Mapping[str, float]:
    loss = 0.5
    return {
        "baseline": {"loss": loss},
        "tec_stabilized": {"loss": loss},
        "fiber_recouple": {"loss": loss},
        "polarization_controlled": {"loss": loss},
        "width_array": {"loss_contrast": 0.3},
        # Leakage grows sharply as the bend tightens and the wavelength lengthens.
        "radius_array": {"loss_contrast": 0.9},
        "wavelength_span": {"loss_span": 0.4},
        "cutback": {"loss_straight": 0.15},
    }.get(x.experiment_id, {})


def _laser_drift(x: ExperimentSpec) -> Mapping[str, float]:
    # Amplitude is the laser's wavelength error in pm: every resonance moves by it, and so does the
    # gas line the laser reads -- until the laser is referenced to that line.
    return {
        "baseline": {"shift": 1.0},
        "tec_stabilized": {"shift": 1.0},
        "gas_cell_reference": {"shift": 0.0, "refline": 1.0},
    }.get(x.experiment_id, {})


def _fiber(x: ExperimentSpec) -> Mapping[str, float]:
    return {
        "baseline": {"il": 1.0},
        "fiber_recouple": {"il_spread": 0.3},
    }.get(x.experiment_id, {})


def _cladding(x: ExperimentSpec) -> Mapping[str, float]:
    # Amplitude is the shift in pm of a 500 nm guide at 1550 nm from a cladding index change.
    return {
        "baseline": {"shift": 1.0},
        "tec_stabilized": {"shift": 1.0},
        "gas_cell_reference": {"shift": 1.0},
        # Narrow guides and long wavelengths put more of the mode in the cladding.
        "width_array": {"shift_contrast": 1.4 - 0.7},
        "wavelength_span": {"shift_span": 0.15},
    }.get(x.experiment_id, {})


def _polarization(x: ExperimentSpec) -> Mapping[str, float]:
    return {
        "baseline": {"loss": 0.8},
        "tec_stabilized": {"loss": 0.8},
        "fiber_recouple": {"loss": 0.8},
        "polarization_controlled": {"loss": 0.0, "er_change": 1.5},
    }.get(x.experiment_id, {})


@dataclass(frozen=True)
class _Declared:
    class_id: str
    family: str
    mechanism: str
    regime: str
    statement: str
    kind: MechanismKind
    tier: Tier
    parameter: str
    lower: float
    upper: float
    prior: float
    forward: Forward


_P = MechanismKind.PHYSICAL
_C = MechanismKind.MEASUREMENT_CHAIN

DECLARED: Final[tuple[_Declared, ...]] = (
    _Declared(
        "thermo.ambient",
        "thermo",
        "thermo-optic drift",
        "ambient temperature offset",
        "The chip sits above its reference temperature and the resonance drifts thermo-optically.",
        _P,
        Tier.INITIAL,
        "delta_T_K",
        0.4,
        2.0,
        0.20,
        _thermo_ambient,
    ),
    _Declared(
        "thermo.self_heating",
        "thermo",
        "thermo-optic drift",
        "optical self-heating",
        "Absorbed optical power heats the ring itself and red-shifts the resonance with power.",
        _P,
        Tier.VARIANT,
        "K_per_mW",
        0.4,
        1.5,
        0.0,
        _thermo_self_heating,
    ),
    _Declared(
        "fcd.static",
        "fcd",
        "free-carrier dispersion",
        "static free carriers",
        "Unintended free carriers blue-shift the resonance and absorb.",
        _P,
        Tier.INITIAL,
        "delta_N_1e17_cm3",
        0.5,
        2.0,
        0.06,
        _fcd_static,
    ),
    _Declared(
        "nonlinear.tpa_fca",
        "nonlinear",
        "two-photon and free-carrier absorption",
        "TPA-dominated",
        "Two-photon absorption and the carriers it creates add power-dependent loss.",
        _P,
        Tier.INITIAL,
        "beta_scale",
        0.5,
        2.0,
        0.08,
        _tpa_fca,
    ),
    _Declared(
        "nonlinear.fca_dominated",
        "nonlinear",
        "two-photon and free-carrier absorption",
        "FCA/FCD-dominated",
        "TPA-generated carriers dominate: power-dependent blue shift and loss.",
        _P,
        Tier.VARIANT,
        "beta_scale",
        0.5,
        2.0,
        0.0,
        _fca_dominated,
    ),
    _Declared(
        "scatter.sidewall",
        "scatter",
        "sidewall-roughness scattering",
        "roughness-limited loss",
        "Sidewall roughness scatters light and raises the propagation loss.",
        _P,
        Tier.INITIAL,
        "roughness_scale",
        0.5,
        2.5,
        0.15,
        _sidewall,
    ),
    _Declared(
        "geometry.width_wide",
        "geometry.width",
        "waveguide width deviation",
        "wider than drawn",
        "The waveguide came out wider than drawn and the resonance red-shifted.",
        _P,
        Tier.INITIAL,
        "delta_w_nm",
        2.0,
        10.0,
        0.12,
        _width,
    ),
    _Declared(
        "geometry.width_narrow",
        "geometry.width",
        "waveguide width deviation",
        "narrower than drawn",
        "The waveguide came out narrower than drawn and the resonance blue-shifted.",
        _P,
        Tier.VARIANT,
        "delta_w_nm",
        -10.0,
        -2.0,
        0.0,
        _width,
    ),
    _Declared(
        "geometry.gap_small",
        "geometry.gap",
        "coupling-gap deviation",
        "gap too narrow",
        "The coupling gap came out narrower than drawn and the ring is over-coupled.",
        _P,
        Tier.INITIAL,
        "delta_gap_nm",
        -25.0,
        -5.0,
        0.08,
        _gap,
    ),
    _Declared(
        "geometry.gap_large",
        "geometry.gap",
        "coupling-gap deviation",
        "gap too wide",
        "The coupling gap came out wider than drawn and the ring is under-coupled.",
        _P,
        Tier.VARIANT,
        "delta_gap_nm",
        5.0,
        25.0,
        0.0,
        _gap,
    ),
    _Declared(
        "leakage.substrate",
        "leakage",
        "substrate leakage",
        "thin buried oxide",
        "Light leaks through the buried oxide into the substrate.",
        _P,
        Tier.INITIAL,
        "leakage_scale",
        0.5,
        2.5,
        0.08,
        _substrate,
    ),
    _Declared(
        "chain.laser_drift",
        "chain.laser",
        "measurement-chain artefact",
        "laser wavelength error",
        "The tunable laser's wavelength reading is off; the ring did not move.",
        _C,
        Tier.INITIAL,
        "lambda_error_pm",
        20.0,
        120.0,
        0.10,
        _laser_drift,
    ),
    _Declared(
        "chain.fiber_coupling",
        "chain.fiber",
        "measurement-chain artefact",
        "fibre coupling loss",
        "The fibre coupling is lossy and drifting; the ring itself is unchanged.",
        _C,
        Tier.INITIAL,
        "coupling_loss_dB",
        0.5,
        2.0,
        0.08,
        _fiber,
    ),
    _Declared(
        "geometry.thickness",
        "geometry.thickness",
        "device-layer thickness deviation",
        "thicker than specified",
        "The silicon device layer is thicker than specified and the resonance red-shifted.",
        _P,
        Tier.EXTENDED,
        "delta_t_nm",
        2.0,
        10.0,
        0.0,
        _thickness,
    ),
    _Declared(
        "cladding.index_drift",
        "cladding",
        "cladding index drift",
        "moisture or stress",
        "The oxide cladding's index changed (moisture uptake or stress) and red-shifted the ring.",
        _P,
        Tier.EXTENDED,
        "shift_pm",
        20.0,
        100.0,
        0.0,
        _cladding,
    ),
    _Declared(
        "chain.polarization_drift",
        "chain.polarization",
        "measurement-chain artefact",
        "input polarisation drift",
        "The input polarisation drifted off TE; the apparent loss is a measurement artefact.",
        _C,
        Tier.EXTENDED,
        "pol_scale",
        0.5,
        2.0,
        0.0,
        _polarization,
    ),
)


def _tabulate(declared: _Declared) -> MechanismClass:
    """Evaluate the forward model against every declared experiment, once, into its table."""
    rows: list[tuple[str, str, float]] = []
    for experiment in (*EXPERIMENTS, ELLIPSOMETRY.experiment):
        sensitivities = declared.forward(experiment)
        for entry in experiment.entries:
            value = float(sensitivities.get(entry.entry_id, 0.0))
            if value != 0.0:
                rows.append((experiment.experiment_id, entry.entry_id, round(value, 9)))
    return MechanismClass(
        class_id=declared.class_id,
        family=declared.family,
        mechanism=declared.mechanism,
        regime=declared.regime,
        statement=declared.statement,
        kind=declared.kind,
        tier=declared.tier,
        parameter=declared.parameter,
        lower=declared.lower,
        upper=declared.upper,
        sensitivity=tuple(rows),
        prior=declared.prior,
    )


#: The catalog's digest, pinned: a forward model, a range or an experiment edited in place stops the
#: catalog from building instead of silently changing what the frozen benchmark measured. A
#: changed catalog is a new `CATALOG_VERSION` with its own pinned digest.
CATALOG_DIGEST: Final = "sha256:69c86963d6e1ae31832208530654539a9283bded6638cad8f0877848553d9119"


def ring_catalog() -> DiscoveryCatalog:
    catalog = DiscoveryCatalog(
        catalog_id=CATALOG_ID,
        version=CATALOG_VERSION,
        question="why has the ring's resonance drifted and its loss risen above design?",
        experiments=EXPERIMENTS,
        unavailable=(ELLIPSOMETRY,),
        mechanisms=tuple(_tabulate(d) for d in DECLARED),
    )
    if catalog.digest != CATALOG_DIGEST:
        raise RuntimeError(
            f"discovery catalog {catalog.ref} hashes to {catalog.digest}, not its pinned digest: "
            "a forward model changed without a catalog version bump"
        )
    return catalog


# -- an effect no class declares ----------------------------------------------------------------


def _progressive_oxidation(experiment: ExperimentSpec, session: int) -> Mapping[str, float]:
    """Photo-induced oxidation that grows with every measurement session -- non-stationary."""
    level = 2.0 + session
    table = {
        "baseline": {"shift": 15.0 * level, "loss": 0.1 * level},
        "tec_stabilized": {"shift": 15.0 * level, "loss": 0.1 * level},
        "gas_cell_reference": {"shift": 15.0 * level},
        "width_array": {"shift_contrast": 3.0 * level},
        "fiber_recouple": {"loss": 0.1 * level},
        "polarization_controlled": {"loss": 0.1 * level},
    }
    return table.get(experiment.experiment_id, {})


UNDECLARED: Final[Mapping[str, UndeclaredEffect]] = {
    "progressive_photo_oxidation": _progressive_oxidation,
}

# -- the benchmark worlds -----------------------------------------------------------------------

WORLD_KINDS: Final = (
    "in_catalog_single",
    "outside_initial_prior",
    "inseparable_pair",
    "noise_glitch",
    "noise_only_null",
    "confounded_measurement_chain",
    "composition",
    "outside_all_declared",
)

_OUTSIDE_PRIOR: Final = (
    "cladding.index_drift",
    "geometry.thickness",
    "thermo.self_heating",
    "geometry.width_narrow",
    "nonlinear.fca_dominated",
    "geometry.gap_large",
)
_INSEPARABLE: Final = ("geometry.width_wide", "geometry.thickness")
_CHAIN: Final = ("chain.laser_drift", "chain.polarization_drift")
_COMPOSITIONS: Final = (
    ("thermo.ambient", "scatter.sidewall"),
    ("geometry.width_wide", "leakage.substrate"),
    ("chain.laser_drift", "scatter.sidewall"),
    ("fcd.static", "nonlinear.tpa_fca"),
    ("cladding.index_drift", "scatter.sidewall"),
)
_SINGLE_WIDTH_DIE: Final = ("width_array", "this die carries a single ring width")


def _amplitude(rng: random.Random, mechanism: MechanismClass) -> float:
    """Inside the inner 80% of the declared range, so the truth is not pinned to a bound."""
    span = mechanism.upper - mechanism.lower
    return round(mechanism.lower + span * (0.1 + 0.8 * rng.random()), 4)


#: The base seed of the frozen evaluation. Development and tests use other seeds, so the evaluation
#: worlds were not inspected while the protocol was being written.
EVALUATION_BASE_SEED: Final = 2026_11_01_00
#: The base seed used while developing the engine and in the unit tests.
DEVELOPMENT_BASE_SEED: Final = 1


def ring_worlds(seeds_per_kind: int, *, base_seed: int) -> tuple[WorldSpec, ...]:
    """The benchmark's worlds: `seeds_per_kind` of each kind, deterministic in `base_seed`."""
    catalog = ring_catalog()
    initial = sorted(m.class_id for m in catalog.initial)
    worlds: list[WorldSpec] = []
    for kind_index, kind in enumerate(WORLD_KINDS):
        for i in range(seeds_per_kind):
            seed = base_seed + 1000 * kind_index + i
            rng = random.Random(f"{seed}:{kind}")
            world_id = f"{kind}-{i:02d}"

            def single(class_id: str, rng: random.Random = rng) -> tuple[tuple[str, float], ...]:
                return ((class_id, _amplitude(rng, catalog.mechanism(class_id))),)

            if kind == "in_catalog_single":
                spec = WorldSpec(world_id, kind, seed, single(rng.choice(initial)))
            elif kind == "outside_initial_prior":
                spec = WorldSpec(world_id, kind, seed, single(rng.choice(_OUTSIDE_PRIOR)))
            elif kind == "inseparable_pair":
                spec = WorldSpec(
                    world_id,
                    kind,
                    seed,
                    single(rng.choice(_INSEPARABLE)),
                    removed=(_SINGLE_WIDTH_DIE,),
                )
            elif kind == "noise_glitch":
                spec = WorldSpec(
                    world_id, kind, seed, single(rng.choice(initial)), glitch_first=True
                )
            elif kind == "noise_only_null":
                spec = WorldSpec(
                    world_id, kind, seed, (), glitch_motivating=True, glitch_first=True
                )
            elif kind == "confounded_measurement_chain":
                spec = WorldSpec(world_id, kind, seed, single(rng.choice(_CHAIN)))
            elif kind == "composition":
                pair = rng.choice(_COMPOSITIONS)
                truth = tuple((c, _amplitude(rng, catalog.mechanism(c))) for c in sorted(pair))
                spec = WorldSpec(world_id, kind, seed, truth)
            else:
                spec = WorldSpec(world_id, kind, seed, (), undeclared="progressive_photo_oxidation")
            worlds.append(spec)
    return tuple(worlds)


def ring_scenario(seeds_per_kind: int, *, base_seed: int) -> Scenario:
    """The ring catalog, its worlds and its undeclared effect, as one benchmark scenario."""
    return Scenario(
        name="sp.ring_drift_loss",
        catalog=ring_catalog(),
        worlds=ring_worlds(seeds_per_kind, base_seed=base_seed),
        undeclared=UNDECLARED,
        motivating_experiment=MOTIVATING_EXPERIMENT,
        base_seed=base_seed,
        seeds_per_kind=seeds_per_kind,
        source_files=(Path(__file__).resolve(),),
    )


__all__ = [
    "CATALOG_DIGEST",
    "CATALOG_ID",
    "CATALOG_VERSION",
    "DECLARED",
    "DEVELOPMENT_BASE_SEED",
    "ELLIPSOMETRY",
    "EVALUATION_BASE_SEED",
    "EXPERIMENTS",
    "MOTIVATING_EXPERIMENT",
    "UNDECLARED",
    "WORLD_KINDS",
    "ring_catalog",
    "ring_scenario",
    "ring_worlds",
]
