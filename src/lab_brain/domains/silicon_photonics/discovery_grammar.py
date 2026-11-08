"""A declared compositional grammar of mechanism TERMS for the ring scenario (plain data).

WHAT THIS IS. The vocabulary the offline safety gate v1.2 may build candidate NEW mechanisms from
when no declared mechanism explains the data. It has two parts, both stated before any v1.2
evaluation world was generated:

    readouts   what each entry of each experiment the lab runs MEASURES, as device channels read
               at declared conditions -- taken from the experiments' own descriptions (a resonance
               shift reads the ring's index and the laser's wavelength; "high-minus-low" is two
               readings; a TEC-locked stage removes an ambient temperature offset; an HCN-referenced
               laser removes the laser's own wavelength error, which then shows up as the offset
               of the reference line; a cutback reads a straight guide's propagation loss, in which
               any length-independent loss cancels; a polariser fixes the input state)
    laws       how a perturbation of a channel may scale along each condition axis, from generic
               physics: power laws in optical power (exponents 0, 1, 2: static, linear absorption
               or one-photon processes, two-photon processes), in waveguide width (exponents -1 to
               3: confinement and surface-overlap scalings), in bend radius (0 to 2) and in
               wavelength (-2 to 3: Rayleigh-like to dispersion-like); evanescent coupling decaying
               exponentially with gap at the field or power decay length of a silicon strip guide
               at 1550 nm (about 128 nm and 64 nm: 1 / (k0 * sqrt(n_eff^2 - n_clad^2)) with
               n_eff ~ 2.4, n_clad 1.44); categorical presence or absence under a TEC lock, a
               laser reference or a polariser; a chain-loss spread over realignments of 10 % to
               100 %; an extinction-ratio readout of 0.5 to 4 per unit apparent loss
    compositions  one cause moving two channels: a complex index perturbation (the index and the
               loss share stage, power, width and wavelength laws) and a geometric deviation (the
               index and the coupling move together)

WHAT THIS IS NOT. It is written by the same author lineage that wrote the ring catalog and has read
its forward models. It names no catalog class, family or forward-model function and computes
nothing from them (a structural test holds that), but its physics is the same textbook physics the
catalog's toy forward models gesture at, so some declared classes are expressible in it exactly and
others only approximately or not at all; the v1.2 report gives each class's distance to the
grammar. It is not calibrated physics, not product domain knowledge, and it registers nothing
anywhere. This module is plain data: it imports nothing from `lab_brain`.
"""

from __future__ import annotations

from typing import Any, Final

GRAMMAR_ID: Final = "sp.ring.term-grammar"
GRAMMAR_VERSION: Final = "1.0.0"

REFERENCES: Final = (
    ("power_mw", "0.1"),
    ("stage", "free"),
    ("laser_reference", "free"),
    ("width_nm", "500"),
    ("gap_nm", "200"),
    ("radius_um", "10"),
    ("wavelength_nm", "1550"),
    ("geometry", "ring"),
    ("realignment", "fixed"),
    ("polarization", "free"),
)


def _power(law_id: str, exponent: float) -> dict[str, Any]:
    return {"law_id": law_id, "kind": "power", "param": exponent}


def _table(law_id: str, table: dict[str, float]) -> dict[str, Any]:
    return {"law_id": law_id, "kind": "table", "table": sorted(table.items())}


_STAGE = (
    _table("intrinsic", {"free": 1.0, "locked": 1.0}),
    _table("ambient", {"free": 1.0, "locked": 0.0}),
)
_POWER = tuple(_power(f"P^{k}", float(k)) for k in (0, 1, 2))
#: Narrower guides: (w / 500 nm) ** -m.
_WIDTH = tuple(_power(f"w^{-m:g}", -float(m)) for m in (-1, 0, 1, 2, 3))
#: Tighter bends: (R / 10 um) ** -r.
_RADIUS = tuple(_power(f"R^{-r:g}", -float(r)) for r in (0, 1, 2))
_WAVELENGTH = tuple(_power(f"lambda^{p}", float(p)) for p in (-2, -1, 0, 1, 2, 3))
_GEOMETRY = (
    _table("propagation", {"ring": 1.0, "straight": 1.0}),
    _table("bend-only", {"ring": 1.0, "straight": 0.0}),
)
_GAP = (
    _power("gap-uniform", 0.0),
    {"law_id": "evanescent-field-128nm", "kind": "exp_decay", "param": 128.0},
    {"law_id": "evanescent-power-64nm", "kind": "exp_decay", "param": 64.0},
)
_SPREAD = tuple(_table(f"spread-{q:g}", {"fixed": 1.0, "spread": q}) for q in (0.1, 0.25, 0.5, 1.0))
_LASER = (_table("laser-error", {"free": 1.0, "referenced": 0.0, "line": 1.0}),)
_POLARIZATION = tuple(
    _table(f"er-{e:g}", {"free": 1.0, "controlled": 0.0, "er": e}) for e in (0.5, 1.0, 2.0, 4.0)
)

CHANNELS: Final = (
    {
        "channel": "index",
        "description": "the ring's guided-mode effective index (resonance shift)",
        "laws": (
            ("stage", _STAGE),
            ("power_mw", _POWER),
            ("width_nm", _WIDTH),
            ("wavelength_nm", _WAVELENGTH),
        ),
    },
    {
        "channel": "loss",
        "description": "the guide's intrinsic loss",
        "laws": (
            ("stage", _STAGE),
            ("power_mw", _POWER),
            ("width_nm", _WIDTH),
            ("radius_um", _RADIUS),
            ("wavelength_nm", _WAVELENGTH),
            ("geometry", _GEOMETRY),
        ),
    },
    {
        "channel": "coupling",
        "description": "the ring-bus power coupling",
        "laws": (("gap_nm", _GAP),),
    },
    {
        "channel": "chain_loss",
        "description": "insertion loss outside the ring (fibre-to-chip)",
        "laws": (("realignment", _SPREAD),),
    },
    {
        "channel": "laser",
        "description": "the laser's wavelength reading",
        "laws": (("laser_reference", _LASER),),
    },
    {
        "channel": "polarization",
        "description": "the input polarisation state's apparent loss",
        "laws": (("polarization", _POLARIZATION),),
    },
)

COMPOSITIONS: Final = (
    {
        "channels": ("index", "loss"),
        "shared": ("stage", "power_mw", "width_nm", "wavelength_nm"),
        "rationale": "a complex refractive-index perturbation moves the real and imaginary parts "
        "with the same condition dependences",
    },
    {
        "channels": ("index", "coupling"),
        "shared": (),
        "rationale": "a geometric deviation moves the mode index and the evanescent coupling",
    },
)


def _r(channel: str, weight: float = 1.0, **conditions: str) -> dict[str, Any]:
    return {"channel": channel, "weight": weight, "conditions": sorted(conditions.items())}


def _diff(channel: str, axis: str, high: str, low: str) -> tuple[dict[str, Any], ...]:
    return (_r(channel, 1.0, **{axis: high}), _r(channel, -1.0, **{axis: low}))


#: (experiment, entry) -> what it reads. Taken from the experiments' descriptions only.
READOUTS: Final = (
    ("baseline", "shift", (_r("index"), _r("laser"))),
    ("baseline", "loss", (_r("loss"), _r("polarization"))),
    ("baseline", "kappa", (_r("coupling"),)),
    ("baseline", "il", (_r("chain_loss"),)),
    (
        "power_sweep",
        "dshift",
        (*_diff("index", "power_mw", "1.0", "0.1"), *_diff("laser", "power_mw", "1.0", "0.1")),
    ),
    (
        "power_sweep",
        "dloss",
        (
            *_diff("loss", "power_mw", "1.0", "0.1"),
            *_diff("polarization", "power_mw", "1.0", "0.1"),
        ),
    ),
    ("tec_stabilized", "shift", (_r("index", stage="locked"), _r("laser"))),
    ("tec_stabilized", "loss", (_r("loss", stage="locked"), _r("polarization"))),
    ("gas_cell_reference", "shift", (_r("index"), _r("laser", laser_reference="referenced"))),
    ("gas_cell_reference", "refline", (_r("laser", laser_reference="line"),)),
    ("fiber_recouple", "il_spread", (_r("chain_loss", realignment="spread"),)),
    ("fiber_recouple", "loss", (_r("loss"), _r("polarization"))),
    (
        "polarization_controlled",
        "loss",
        (_r("loss"), _r("polarization", polarization="controlled")),
    ),
    ("polarization_controlled", "er_change", (_r("polarization", polarization="er"),)),
    ("width_array", "shift_contrast", _diff("index", "width_nm", "400", "600")),
    ("width_array", "loss_contrast", _diff("loss", "width_nm", "400", "600")),
    ("gap_array", "kappa_g150", (_r("coupling", gap_nm="150"),)),
    ("gap_array", "kappa_g200", (_r("coupling", gap_nm="200"),)),
    ("gap_array", "kappa_g250", (_r("coupling", gap_nm="250"),)),
    ("radius_array", "loss_contrast", _diff("loss", "radius_um", "5", "20")),
    ("wavelength_span", "shift_span", _diff("index", "wavelength_nm", "1600", "1500")),
    ("wavelength_span", "loss_span", _diff("loss", "wavelength_nm", "1600", "1500")),
    ("cutback", "loss_straight", (_r("loss", geometry="straight"),)),
)

STATEMENT: Final = (
    "Ring drift and loss: device channels (index, loss, coupling, chain loss, laser reading, "
    "input polarisation), generic scaling laws per condition axis, and two one-cause "
    "compositions."
)


def declaration() -> dict[str, Any]:
    """The grammar as plain data, for the composition root to hand to the safety gate."""
    return {
        "grammar_id": GRAMMAR_ID,
        "version": GRAMMAR_VERSION,
        "statement": STATEMENT,
        "references": REFERENCES,
        "readouts": READOUTS,
        "channels": CHANNELS,
        "compositions": COMPOSITIONS,
    }


__all__ = [
    "CHANNELS",
    "COMPOSITIONS",
    "GRAMMAR_ID",
    "GRAMMAR_VERSION",
    "READOUTS",
    "REFERENCES",
    "declaration",
]
