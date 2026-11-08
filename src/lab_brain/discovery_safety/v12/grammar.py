"""A pre-declared compositional grammar of mechanism TERMS, and candidate mechanisms built from it.

WHAT THE GRAMMAR IS. A domain declares (as data, handed in by the composition root; this package
imports no domain):

    readouts      for each (experiment, entry) the laboratory reports, which physical CHANNELS of
                  the device it reads, with what weight, under which declared CONDITIONS -- e.g. a
                  resonance-shift entry reads the ring's index channel and the laser's wavelength
                  channel at 0.1 mW, stage free, 500 nm wide, 1550 nm; a "high-minus-low" entry is
                  two readings with weights +1 and -1. This describes the INSTRUMENTS, not any
                  mechanism
    channels      the device properties a perturbation can move, and per condition AXIS the
                  declared scaling LAWS it may follow (a power law in the axis value with a declared
                  exponent, an exponential decay with a declared length, or a categorical table such
                  as "vanishes when the stage is temperature-locked"); every law is 1 at the axis's
                  reference value
    compositions  which pairs of channels one cause may move together, and which axes they then
                  share (the same law on both)

A TERM is one channel with one law chosen per axis; its forward model (sensitivity per unit
amplitude, per declared entry) is computed from the readouts alone. A CANDIDATE is one term, or one
declared composition of two terms, each with its own fitted amplitude (free sign). Nothing here
reads a catalog mechanism: the structural test holds that this module and the domain's declaration
name no catalog class, family or forward-model function.

FIT AND DOMAIN. A candidate is fitted by ordinary least squares in standard units (sign free); its
amplitudes' covariance is (X^T X)^-1. Its declared amplitude domain is the fitted value times
(1 - band, 1 + band) (sign-definite; `SafetyProtocolV12.candidate_band`), fixed by the protocol,
never by the evaluator; that domain is what the distinguishability of the candidate from anything
else is computed over.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cached_property
from typing import Any

from lab_brain.discovery.model import (
    ExperimentSpec,
    Hypothesis,
    MechanismClass,
    MechanismKind,
    Observation,
    Tier,
    make_hypothesis,
    stable_digest,
)
from lab_brain.discovery.numerics import box_lsq, chi2_sf

POWER = "power"
EXP_DECAY = "exp_decay"
TABLE = "table"


@dataclass(frozen=True)
class AxisLaw:
    """How a channel scales along one condition axis; 1 at the axis's reference value."""

    law_id: str
    kind: str
    #: POWER: (x / ref) ** param.  EXP_DECAY: exp(-(x - ref) / param).
    param: float = 0.0
    #: TABLE: categorical axis value -> factor (the reference value maps to 1).
    table: tuple[tuple[str, float], ...] = ()

    def factor(self, value: str, reference: str) -> float:
        if self.kind == TABLE:
            return dict(self.table)[value]
        x, ref = float(value), float(reference)
        if self.kind == POWER:
            return float((x / ref) ** self.param)
        if self.kind == EXP_DECAY:
            return math.exp(-(x - ref) / self.param)
        raise ValueError(f"unknown law kind {self.kind!r}")


@dataclass(frozen=True)
class Reading:
    """One channel read by an entry: weight x the channel's level at these conditions."""

    channel: str
    weight: float
    conditions: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Readout:
    experiment_id: str
    entry_id: str
    readings: tuple[Reading, ...]


@dataclass(frozen=True)
class ChannelSpec:
    channel: str
    description: str
    #: Per axis, the laws this channel may follow (the grammar's choices).
    laws: tuple[tuple[str, tuple[AxisLaw, ...]], ...]


@dataclass(frozen=True)
class Composition:
    """One cause moving two channels; `shared` axes carry the same law on both."""

    channels: tuple[str, str]
    shared: tuple[str, ...]
    rationale: str


@dataclass(frozen=True)
class TermGrammar:
    grammar_id: str
    version: str
    statement: str
    #: Axis -> reference value (as a string).
    references: tuple[tuple[str, str], ...]
    readouts: tuple[Readout, ...]
    channels: tuple[ChannelSpec, ...]
    compositions: tuple[Composition, ...]

    @property
    def digest(self) -> str:
        return stable_digest(self)

    def channel(self, name: str) -> ChannelSpec:
        return next(c for c in self.channels if c.channel == name)


@dataclass(frozen=True)
class Term:
    channel: str
    #: (axis, law) per axis of the channel, in the channel's declared axis order.
    laws: tuple[tuple[str, AxisLaw], ...]

    @property
    def term_id(self) -> str:
        return f"{self.channel}[" + ",".join(f"{a}={law.law_id}" for a, law in self.laws) + "]"


def grammar_from_declaration(declared: Mapping[str, Any]) -> TermGrammar:
    """Build a `TermGrammar` from a domain's plain-data declaration (see the ring scenario's)."""

    def law(d: Mapping[str, Any]) -> AxisLaw:
        return AxisLaw(
            law_id=str(d["law_id"]),
            kind=str(d["kind"]),
            param=float(d.get("param", 0.0)),
            table=tuple((str(k), float(v)) for k, v in d.get("table", ())),
        )

    return TermGrammar(
        grammar_id=str(declared["grammar_id"]),
        version=str(declared["version"]),
        statement=str(declared["statement"]),
        references=tuple((str(a), str(v)) for a, v in declared["references"]),
        readouts=tuple(
            Readout(
                experiment_id=str(e),
                entry_id=str(n),
                readings=tuple(
                    Reading(
                        channel=str(r["channel"]),
                        weight=float(r["weight"]),
                        conditions=tuple((str(a), str(v)) for a, v in r["conditions"]),
                    )
                    for r in readings
                ),
            )
            for e, n, readings in declared["readouts"]
        ),
        channels=tuple(
            ChannelSpec(
                channel=str(c["channel"]),
                description=str(c["description"]),
                laws=tuple((str(axis), tuple(law(x) for x in laws)) for axis, laws in c["laws"]),
            )
            for c in declared["channels"]
        ),
        compositions=tuple(
            Composition(
                channels=(str(c["channels"][0]), str(c["channels"][1])),
                shared=tuple(str(a) for a in c["shared"]),
                rationale=str(c["rationale"]),
            )
            for c in declared["compositions"]
        ),
    )


def term_table(grammar: TermGrammar, term: Term) -> tuple[tuple[str, str, float], ...]:
    """The term's sensitivity per unit amplitude for every declared entry (zeros omitted)."""
    references = dict(grammar.references)
    laws = dict(term.laws)
    rows = []
    for readout in grammar.readouts:
        value = 0.0
        for reading in readout.readings:
            if reading.channel != term.channel:
                continue
            conditions = dict(reading.conditions)
            level = 1.0
            for axis, law in laws.items():
                level *= law.factor(conditions.get(axis, references[axis]), references[axis])
            value += reading.weight * level
        if abs(value) > 1e-12:
            rows.append((readout.experiment_id, readout.entry_id, round(value, 9)))
    return tuple(rows)


def _channel_terms(spec: ChannelSpec, fixed: Mapping[str, AxisLaw]) -> list[Term]:
    axes = [a for a, _ in spec.laws]
    choices = [((fixed[a],) if a in fixed else laws) for a, laws in spec.laws]
    return [
        Term(spec.channel, tuple(zip(axes, combo, strict=True)))
        for combo in itertools.product(*choices)
    ]


@dataclass(frozen=True)
class CandidateShape:
    """One or two terms (before fitting)."""

    terms: tuple[Term, ...]
    tables: tuple[tuple[tuple[str, str, float], ...], ...]

    @cached_property
    def shape_id(self) -> str:
        return " + ".join(t.term_id for t in self.terms)

    @cached_property
    def fingerprint(self) -> str:
        return stable_digest(sorted([[list(map(str, r)) for r in t] for t in self.tables]))


def enumerate_shapes(grammar: TermGrammar) -> tuple[CandidateShape, ...]:
    """Every single term and every declared composition, deduplicated by forward model (a term
    that reads nothing, or a composition identical to one already listed, is dropped)."""
    out: list[CandidateShape] = []
    seen: set[str] = set()

    def add(terms: tuple[Term, ...]) -> None:
        tables = tuple(term_table(grammar, t) for t in terms)
        if any(not table for table in tables):
            return
        shape = CandidateShape(terms, tables)
        if shape.fingerprint in seen:
            return
        seen.add(shape.fingerprint)
        out.append(shape)

    for spec in grammar.channels:
        for term in _channel_terms(spec, {}):
            add((term,))
    for composition in grammar.compositions:
        first, second = (grammar.channel(c) for c in composition.channels)
        shared_choices = [dict(first.laws)[a] for a in composition.shared]
        for combo in itertools.product(*shared_choices):
            fixed = dict(zip(composition.shared, combo, strict=True))
            a_fixed = {k: v for k, v in fixed.items() if k in dict(first.laws)}
            b_fixed = {k: v for k, v in fixed.items() if k in dict(second.laws)}
            for a in _channel_terms(first, a_fixed):
                for b in _channel_terms(second, b_fixed):
                    add((a, b))
    return tuple(out)


@dataclass(frozen=True)
class FittedShape:
    shape: CandidateShape
    theta: tuple[float, ...]
    covariance: tuple[tuple[float, ...], ...]
    chi2: float
    n: int
    p_value: float
    max_abs_z: float


def _invert(matrix: list[list[float]]) -> list[list[float]] | None:
    n = len(matrix)
    a = [[*row, *(1.0 if i == j else 0.0 for j in range(n))] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-12:
            return None
        a[col], a[pivot] = a[pivot], a[col]
        p = a[col][col]
        a[col] = [v / p for v in a[col]]
        for r in range(n):
            if r != col and a[r][col]:
                f = a[r][col]
                a[r] = [v - f * w for v, w in zip(a[r], a[col], strict=True)]
    return [row[n:] for row in a]


def fit_shape(
    shape: CandidateShape,
    observations: Sequence[Observation],
    experiments: Mapping[str, ExperimentSpec],
) -> FittedShape | None:
    """Ordinary least squares in standard units (sign free). None when the data do not constrain
    every term (a term no admitted entry reads cannot be fitted, so it predicts nothing tested)."""
    coefficient = [{(e, n): c for e, n, c in table} for table in shape.tables]
    rows: list[tuple[list[float], float, str]] = []
    for o in observations:
        experiment = experiments[o.experiment_id]
        for entry in experiment.entries:
            x = [c.get((o.experiment_id, entry.entry_id), 0.0) / entry.sigma for c in coefficient]
            rows.append((x, o.value(entry.entry_id) / entry.sigma, o.observation_id))
    k = len(shape.tables)
    xtx = [[math.fsum(r[0][i] * r[0][j] for r in rows) for j in range(k)] for i in range(k)]
    if any(xtx[i][i] <= 1e-12 for i in range(k)):
        return None
    inverse = _invert(xtx)
    if inverse is None:
        return None
    xty = [math.fsum(r[0][i] * r[1] for r in rows) for i in range(k)]
    theta = [math.fsum(inverse[i][j] * xty[j] for j in range(k)) for i in range(k)]
    chi2 = 0.0
    worst = 0.0
    for x, y, _ in rows:
        r = y - math.fsum(t * v for t, v in zip(theta, x, strict=True))
        chi2 += r * r
        worst = max(worst, abs(r))
    n = len(rows)
    dof = max(1, n - k)
    return FittedShape(
        shape=shape,
        theta=tuple(theta),
        covariance=tuple(tuple(row) for row in inverse),
        chi2=chi2,
        n=n,
        p_value=chi2_sf(chi2, dof),
        max_abs_z=worst,
    )


def candidate_classes(
    fitted: FittedShape, band: float, label: str
) -> tuple[MechanismClass, ...] | None:
    """The fitted candidate as catalog-shaped classes (one per term) with the declared domain.
    None when an amplitude is exactly zero (no sign-definite domain exists)."""
    out = []
    for i, (term, table, theta) in enumerate(
        zip(fitted.shape.terms, fitted.shape.tables, fitted.theta, strict=True)
    ):
        if theta == 0.0:
            return None
        lo, hi = sorted((theta * (1.0 - band), theta * (1.0 + band)))
        out.append(
            MechanismClass(
                class_id=f"{label}.t{i}",
                family=f"{label}.{term.channel}.t{i}",
                mechanism=f"grammar term {term.term_id}",
                regime="fitted",
                statement=f"grammar candidate term {term.term_id} (fitted amplitude {theta:+.4g})",
                kind=MechanismKind.PHYSICAL,
                tier=Tier.EXTENDED,
                parameter="amplitude",
                lower=lo,
                upper=hi,
                sensitivity=table,
            )
        )
    return tuple(out)


def candidate_hypothesis(classes: Sequence[MechanismClass]) -> Hypothesis:
    return make_hypothesis(*classes)


def prediction(
    fitted: FittedShape, experiment: ExperimentSpec
) -> tuple[dict[str, float], dict[str, float]]:
    """Predicted value and standard deviation per entry at the fitted amplitudes."""
    mean: dict[str, float] = {}
    sd: dict[str, float] = {}
    tables = [{(e, n): c for e, n, c in table} for table in fitted.shape.tables]
    for entry in experiment.entries:
        s = [t.get((experiment.experiment_id, entry.entry_id), 0.0) for t in tables]
        mean[entry.entry_id] = math.fsum(a * b for a, b in zip(fitted.theta, s, strict=True))
        # covariance is in standard units of the amplitudes (the design was divided by sigma,
        # the response too), so it is the amplitudes' own covariance.
        var = math.fsum(
            s[i] * fitted.covariance[i][j] * s[j] for i in range(len(s)) for j in range(len(s))
        )
        sd[entry.entry_id] = math.sqrt(max(0.0, var))
    return mean, sd


def separation(
    a: Hypothesis,
    b: Hypothesis,
    experiments: Sequence[ExperimentSpec],
    replicates: int,
) -> float:
    """The engine's distinguishability statistic for ANY two hypotheses (catalog or grammar):
    sqrt(replicates) x the closest the two forward models come over both amplitude domains, in
    standard units, over `experiments` (SAI Appendix S §3, worst case over parameters)."""
    columns: list[list[float]] = []
    lower: list[float] = []
    upper: list[float] = []
    for sign, hypothesis in ((1.0, a), (-1.0, b)):
        for component in hypothesis.components:
            columns.append(
                [
                    sign * component.coefficient(x.experiment_id, e.entry_id) / e.sigma
                    for x in experiments
                    for e in x.entries
                ]
            )
            lower.append(component.lower)
            upper.append(component.upper)
    n = sum(len(x.entries) for x in experiments)
    if not columns:
        return 0.0
    _, value = box_lsq(columns, [0.0] * n, lower, upper)
    return math.sqrt(replicates) * math.sqrt(value)


__all__ = [
    "EXP_DECAY",
    "POWER",
    "TABLE",
    "AxisLaw",
    "CandidateShape",
    "ChannelSpec",
    "Composition",
    "FittedShape",
    "Reading",
    "Readout",
    "Term",
    "TermGrammar",
    "candidate_classes",
    "candidate_hypothesis",
    "enumerate_shapes",
    "fit_shape",
    "grammar_from_declaration",
    "prediction",
    "separation",
    "term_table",
]
