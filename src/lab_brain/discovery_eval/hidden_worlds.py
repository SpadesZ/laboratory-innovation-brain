"""Sealed hidden worlds from a different author: format, validation, sealing, blind run, scoring.

ROLES. A WORLD AUTHOR (never the engine's author) writes worlds against a FROZEN engine interface:
the engine's catalog, named by ref and digest -- its experiments, entries, noise sigmas and costs,
and its declared mechanism classes. An EVALUATOR seals them, runs every arm blind and scores. The
engine is handed its own catalog, an engine package and a blind laboratory; nothing else.

THE AUTHOR'S FILE, `lab-brain/discovery-hidden-worlds@1`. Every key is required and no other key is
accepted, at any level:

    kind            "lab-brain/discovery-hidden-worlds@1"
    suite           a neutral name (it reaches the engine-side operator)
    example_only    true only for documentation material; an example is never a hidden set
    notice          free text for people; never reaches the engine
    author          {"role": "world_author", "label": free text}
    interface       {"catalog_ref", "catalog_digest", "motivating_experiment"}: the engine
                    catalog's ref and digest exactly; the motivating experiment is available
    worlds          a non-empty list of
      world_id      [A-Za-z0-9._-]{1,64}, unique; never shown to the engine
      public        what every arm is told about this world's laboratory:
        removed     [[experiment_id, reason], ...]: experiments this lab cannot run, and why
      hidden        never shown to the engine:
        category    declared | composition | null | held_out | aliased_held_out | non_stationary
        seed        an integer in [0, 2^53 - 1]
        effects     a list of
                      {"declared_class": id, "amplitude": "x"}
                          a class of the engine's catalog, amplitude inside its declared range
                      {"effect_id": id, "amplitude": "x", "session_slope": "s",
                       "sensitivity": [[experiment_id, entry_id, "v"], ...]}
                          a mechanism the engine does not have: a reading moves by
                          amplitude * (1 + slope * session) * v (session 0 is the motivating run)
        noise       {"scale": "1", "glitch_motivating": false, "glitch_first": false,
                     "glitch_sigma": "7"}: Gaussian noise of scale * each entry's declared sigma;
                    a glitch adds one +-glitch_sigma * sigma outlier to the motivating reading
                    and/or the first measurement, as in `lab_brain.discovery.worlds`

Numbers that are not integers are DECIMAL STRINGS ("1.25", "-0.5"): the commitment hashes canonical
JSON, whose profile refuses floats (`lab_brain.core.canonical_json`); a float anywhere is refused.

CATEGORIES. The author states one; the loader checks it against the effects; the evaluator scores by
it; the engine never sees it.

    declared          one declared class                         correct: its class (metrics rule)
    composition       two declared classes of different families correct: its class
    null              no effect                                  correct: NO_EFFECT_BEYOND_NOISE
    held_out          at least one tabulated effect, no slope, and the truth's predictions are
                      distinguishable from EVERY hypothesis the engine's catalog can express (at
                      the truth's fixed amplitudes, over the available protocol, with the engine's
                      own tau and replicates)                    correct: no claim
    aliased_held_out  as held_out, but some engine hypothesis cannot be separated from it; scored
                      separately: a claim of an alias is a `surrogate`, never counted correct
    non_stationary    at least one tabulated effect with a non-zero session slope
                                                                 correct: no claim

VALIDATION refuses (`HiddenWorldRefused`, listing every reason found) a malformed file -- a wrong
kind, missing or extra keys, floats, booleans where numbers belong, non-finite or out-of-range
numbers, duplicate ids, unknown experiments or entries, a declared amplitude outside its class's
range, a tabulated effect named like an engine class or family, a category its effects do not
satisfy -- and a world whose truth would LEAK into what the engine is given: a removal reason (the
only free text the engine sees) or a suite name that names a truth class, family, mechanism,
regime, effect id, category or world id; a removed motivating experiment.

LOCATION. A file that is not `example_only` is refused inside the repository: the hidden set and its
sealed form live with the author and the evaluator, outside it (as `evaluation.sealing` does for G0
truth). An `example_only` file is refused as a hidden set unless the caller is running the scaffold
demonstration (`allow_example`).

SEALING, commit-then-reveal after `lab_brain.evaluation.sealing`, with its own domain tags:

    case_id     "case-" + the first 12 hex of SHA-256(CASE_DOMAIN || salt): opaque, from the salt
    commitment  SHA-256(COMMIT_DOMAIN || salt ||
                        canonical_json({case_id, world_id, public, hidden}))
    root        the canonical hash of {case_id: commitment}

`seal` returns the SEALED file (salts, world ids, truth -- kept by the author and the evaluator,
outside the repository) and the ENGINE PACKAGE (`lab-brain/discovery-engine-cases@1`: the
interface, per case id only the public part, the commitments and the root). Cases are ordered by
case id, so the author's order, ids and categories do not reach the engine side. `reveal` refuses
unless every case's recomputed commitment matches the package, case for case.

ENGINE SIDE. `parse_engine_package` refuses any key outside its schema and any truth-bearing key at
any depth. `run_blind` hands the engine its own catalog, the case's available experiments and
removal reasons, the protocol, the cap and a blind, metered laboratory, and records outcomes by case
id, bound to the package root. `score_outputs` is the evaluator's: it scores each case by its
category, after the reveal has been verified.

LIMIT. `sealed_laboratories` runs the laboratory in the engine's process. That is the offline
scaffold; the independent protocol puts the laboratory in a separate process.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
import secrets
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from lab_brain.core.canonical_json import canonical_bytes, canonical_hash
from lab_brain.discovery.benchmark import Arm
from lab_brain.discovery.catalog import DiscoveryCatalog
from lab_brain.discovery.distinguish import SeparationOracle
from lab_brain.discovery.loop import Laboratory, hypothesis_universe
from lab_brain.discovery.metrics import Scorer, mean, rate
from lab_brain.discovery.model import (
    CLAIM_OUTCOMES,
    NULL_HYPOTHESIS,
    NULL_HYPOTHESIS_ID,
    AnomalyState,
    Budget,
    ExperimentSpec,
    Hypothesis,
    Outcome,
    make_hypothesis,
)
from lab_brain.discovery.numerics import box_lsq
from lab_brain.discovery.protocol import DiscoveryProtocol
from lab_brain.discovery_eval.blind import CostMeter, blind_laboratory, needle_pattern
from lab_brain.discovery_eval.curves import shared_protocol

HIDDEN_WORLDS_KIND = "lab-brain/discovery-hidden-worlds@1"
SEALED_KIND = "lab-brain/discovery-hidden-worlds-sealed@1"
ENGINE_PACKAGE_KIND = "lab-brain/discovery-engine-cases@1"
OUTPUTS_KIND = "lab-brain/discovery-blind-outputs@1"
COMMIT_DOMAIN = b"lab-brain/discovery-hidden-world/commit@1\x00"
CASE_DOMAIN = b"lab-brain/discovery-hidden-world/case-id@1\x00"
SCHEME = (
    "commitment = sha256(COMMIT_DOMAIN || salt || canonical_json({case_id, world_id, public, "
    "hidden})); case_id = 'case-' + sha256(CASE_DOMAIN || salt)[:12]; root = canonical_hash("
    "{case_id: commitment})"
)

CATEGORIES = ("declared", "composition", "null", "held_out", "aliased_held_out", "non_stationary")
EXPRESSIBLE = frozenset({"declared", "composition", "null"})

TOP_KEYS = frozenset({"kind", "suite", "example_only", "notice", "author", "interface", "worlds"})
AUTHOR_KEYS = frozenset({"role", "label"})
INTERFACE_KEYS = frozenset({"catalog_ref", "catalog_digest", "motivating_experiment"})
WORLD_KEYS = frozenset({"world_id", "public", "hidden"})
SEALED_WORLD_KEYS = WORLD_KEYS | {"case_id", "salt"}
PUBLIC_KEYS = frozenset({"removed"})
HIDDEN_KEYS = frozenset({"category", "seed", "effects", "noise"})
DECLARED_EFFECT_KEYS = frozenset({"declared_class", "amplitude"})
TABULATED_EFFECT_KEYS = frozenset({"effect_id", "amplitude", "session_slope", "sensitivity"})
NOISE_KEYS = frozenset({"scale", "glitch_motivating", "glitch_first", "glitch_sigma"})
ENGINE_TOP_KEYS = frozenset(
    {"kind", "suite", "example_only", "interface", "cases", "commitments", "root"}
)
ENGINE_CASE_KEYS = frozenset({"case_id", "public"})
#: Keys that carry truth. None may appear, at any depth, in what the engine side receives.
TRUTH_KEYS = frozenset(
    {
        "hidden",
        "effects",
        "effect_id",
        "declared_class",
        "amplitude",
        "sensitivity",
        "session_slope",
        "seed",
        "category",
        "noise",
        "scale",
        "glitch_motivating",
        "glitch_first",
        "glitch_sigma",
        "salt",
        "world_id",
        "truth",
        "expected",
        "answer",
    }
)

_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_CASE_ID = re.compile(r"^case-[0-9a-f]{12}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_DECIMAL = re.compile(r"^-?[0-9]+(\.[0-9]+)?([eE][-+]?[0-9]+)?$")
MAX_SEED = 2**53 - 1
MAX_REASON = 200


class HiddenWorldRefused(ValueError):
    """The file is malformed, or would leak truth into the engine's inputs. Every reason found."""

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = tuple(problems)
        super().__init__("; ".join(self.problems))


class CommitmentMismatch(ValueError):
    """The revealed worlds are not exactly what was committed before the run."""


class ScoringRefused(ValueError):
    """The outputs cannot be scored against this package and reveal."""


@dataclass(frozen=True)
class Interface:
    catalog_ref: str
    catalog_digest: str
    motivating_experiment: str


@dataclass(frozen=True)
class Effect:
    amplitude: float
    declared_class: str | None = None
    effect_id: str | None = None
    session_slope: float = 0.0
    sensitivity: tuple[tuple[str, str, float], ...] = ()


@dataclass(frozen=True)
class Noise:
    scale: float = 1.0
    glitch_motivating: bool = False
    glitch_first: bool = False
    glitch_sigma: float = 7.0


@dataclass(frozen=True)
class HiddenWorld:
    world_id: str
    removed: tuple[tuple[str, str], ...]
    category: str
    seed: int
    effects: tuple[Effect, ...]
    noise: Noise
    #: Engine hypotheses the truth cannot be separated from (stationary tabulated truths only).
    aliases: tuple[str, ...] = ()
    case_id: str | None = None
    salt: str | None = None
    #: The validated source, exactly as committed.
    public_json: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)
    hidden_json: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    @property
    def expressible(self) -> bool:
        return self.category in EXPRESSIBLE

    def truth_hypothesis(self, catalog: DiscoveryCatalog) -> Hypothesis | None:
        """The truth as an engine hypothesis, or None when the engine cannot express it."""
        if not self.expressible:
            return None
        if not self.effects:
            return NULL_HYPOTHESIS
        return make_hypothesis(*(catalog.mechanism(str(e.declared_class)) for e in self.effects))

    def available(self, catalog: DiscoveryCatalog) -> tuple[str, ...]:
        removed = {e for e, _ in self.removed}
        return tuple(e.experiment_id for e in catalog.experiments if e.experiment_id not in removed)


@dataclass(frozen=True)
class HiddenWorldSet:
    suite: str
    example_only: bool
    notice: str
    author_label: str
    interface: Interface
    worlds: tuple[HiddenWorld, ...]


@dataclass(frozen=True)
class EngineCase:
    case_id: str
    removed: tuple[tuple[str, str], ...]

    def available(self, catalog: DiscoveryCatalog) -> tuple[str, ...]:
        removed = {e for e, _ in self.removed}
        return tuple(e.experiment_id for e in catalog.experiments if e.experiment_id not in removed)


@dataclass(frozen=True)
class EnginePackage:
    suite: str
    example_only: bool
    interface: Interface
    cases: tuple[EngineCase, ...]
    commitments: Mapping[str, str] = field(compare=False)
    root: str = ""


# -- validation helpers ---------------------------------------------------------------------------


def _floats(value: Any, where: str, problems: list[str]) -> None:
    if isinstance(value, float):
        problems.append(f"{where}: a float; write non-integer numbers as decimal strings")
    elif isinstance(value, Mapping):
        for key, item in value.items():
            _floats(item, f"{where}.{key}", problems)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _floats(item, f"{where}[{index}]", problems)


def _keys(value: Any, allowed: frozenset[str], where: str, problems: list[str]) -> bool:
    if not isinstance(value, Mapping):
        problems.append(f"{where}: an object is required")
        return False
    keys = set(value)
    missing = sorted(allowed - keys)
    extra = sorted(keys - allowed)
    if missing:
        problems.append(f"{where}: missing {missing}")
    if extra:
        problems.append(f"{where}: keys outside the schema {extra}")
    return not missing and not extra


def _text(value: Any, where: str, problems: list[str], *, limit: int = 2000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        problems.append(f"{where}: a non-empty string of at most {limit} characters")
        return ""
    return value


def _decimal(
    value: Any,
    where: str,
    problems: list[str],
    *,
    low: float | None = None,
    high: float | None = None,
    nonzero: bool = False,
) -> float:
    if not isinstance(value, str) or not _DECIMAL.match(value):
        problems.append(f'{where}: a decimal string such as "1.25" is required')
        return math.nan
    number = float(value)
    if not math.isfinite(number):
        problems.append(f"{where}: not finite")
    elif nonzero and number == 0.0:
        problems.append(f"{where}: must not be zero")
    elif (low is not None and number < low) or (high is not None and number > high):
        problems.append(f"{where}: {value} is outside [{low}, {high}]")
    return number


def _flag(value: Any, where: str, problems: list[str]) -> bool:
    if not isinstance(value, bool):
        problems.append(f"{where}: true or false")
        return False
    return value


def _interface(value: Any, catalog: DiscoveryCatalog, problems: list[str]) -> Interface | None:
    if not _keys(value, INTERFACE_KEYS, "interface", problems):
        return None
    if value["catalog_ref"] != catalog.ref:
        problems.append(
            f"interface.catalog_ref {value['catalog_ref']!r} is not the engine catalog "
            f"{catalog.ref}"
        )
    if value["catalog_digest"] != catalog.digest:
        problems.append("interface.catalog_digest does not match the engine catalog's digest")
    motivating = value["motivating_experiment"]
    if motivating not in {e.experiment_id for e in catalog.experiments}:
        problems.append(f"interface.motivating_experiment {motivating!r} is not available")
    return Interface(str(value["catalog_ref"]), str(value["catalog_digest"]), str(motivating))


def _removed(
    value: Any, where: str, catalog: DiscoveryCatalog, motivating: str, problems: list[str]
) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, list):
        problems.append(f"{where}: a list of [experiment_id, reason] pairs")
        return ()
    available = {e.experiment_id for e in catalog.experiments}
    out: list[tuple[str, str]] = []
    for index, pair in enumerate(value):
        at = f"{where}[{index}]"
        if not (isinstance(pair, list) and len(pair) == 2):
            problems.append(f"{at}: an [experiment_id, reason] pair")
            continue
        experiment_id, reason = pair
        if experiment_id not in available:
            problems.append(f"{at}: {experiment_id!r} is not an available experiment")
        elif experiment_id == motivating:
            problems.append(f"{at}: the motivating experiment cannot be removed")
        elif experiment_id in {e for e, _ in out}:
            problems.append(f"{at}: {experiment_id!r} is removed twice")
        out.append((str(experiment_id), _text(reason, f"{at}.reason", problems, limit=MAX_REASON)))
    if len(out) >= len(available):
        problems.append(f"{where}: no experiment would be left to run")
    return tuple(out)


def _entries(catalog: DiscoveryCatalog) -> dict[str, set[str]]:
    declared = (*catalog.experiments, *(u.experiment for u in catalog.unavailable))
    return {e.experiment_id: {n.entry_id for n in e.entries} for e in declared}


def _effect(
    value: Any, where: str, catalog: DiscoveryCatalog, problems: list[str]
) -> Effect | None:
    if isinstance(value, Mapping) and "declared_class" in value:
        if not _keys(value, DECLARED_EFFECT_KEYS, where, problems):
            return None
        class_id = value["declared_class"]
        known = {m.class_id: m for m in catalog.mechanisms}
        if class_id not in known:
            problems.append(f"{where}.declared_class {class_id!r} is not in the engine catalog")
            return None
        m = known[class_id]
        amplitude = _decimal(
            value["amplitude"], f"{where}.amplitude", problems, low=m.lower, high=m.upper
        )
        return Effect(amplitude=amplitude, declared_class=str(class_id))
    if not _keys(value, TABULATED_EFFECT_KEYS, where, problems):
        return None
    effect_id = value["effect_id"]
    names = {m.class_id for m in catalog.mechanisms} | {m.family for m in catalog.mechanisms}
    if not isinstance(effect_id, str) or not _ID.match(effect_id):
        problems.append(f"{where}.effect_id: [A-Za-z0-9._-]{{1,64}}")
    elif effect_id in names:
        problems.append(f"{where}.effect_id {effect_id!r} names an engine class or family")
    amplitude = _decimal(value["amplitude"], f"{where}.amplitude", problems, nonzero=True)
    slope = _decimal(value["session_slope"], f"{where}.session_slope", problems, low=-10, high=10)
    rows = value["sensitivity"]
    entries = _entries(catalog)
    table: list[tuple[str, str, float]] = []
    if not isinstance(rows, list) or not rows:
        problems.append(f"{where}.sensitivity: a non-empty list of [experiment, entry, value]")
    else:
        for index, row in enumerate(rows):
            at = f"{where}.sensitivity[{index}]"
            if not (isinstance(row, list) and len(row) == 3):
                problems.append(f'{at}: an [experiment_id, entry_id, "value"] triple')
                continue
            experiment_id, entry_id, raw = row
            if entry_id not in entries.get(experiment_id, set()):
                problems.append(f"{at}: {experiment_id}.{entry_id} is not a declared entry")
                continue
            if (experiment_id, entry_id) in {(e, n) for e, n, _ in table}:
                problems.append(f"{at}: {experiment_id}.{entry_id} appears twice")
                continue
            table.append((experiment_id, entry_id, _decimal(raw, at, problems)))
        if table and all(v == 0.0 for _, _, v in table):
            problems.append(f"{where}.sensitivity: every value is zero")
    return Effect(
        amplitude=amplitude,
        effect_id=str(effect_id),
        session_slope=slope,
        sensitivity=tuple(table),
    )


def truth_vector(
    world: HiddenWorld, catalog: DiscoveryCatalog, experiments: Sequence[ExperimentSpec]
) -> list[float]:
    """The stationary truth's predictions over `experiments`, in standard units (session 0)."""
    out: list[float] = []
    for x in experiments:
        for entry in x.entries:
            value = 0.0
            for effect in world.effects:
                if effect.declared_class is not None:
                    m = catalog.mechanism(effect.declared_class)
                    value += effect.amplitude * m.coefficient(x.experiment_id, entry.entry_id)
                else:
                    for e, n, v in effect.sensitivity:
                        if e == x.experiment_id and n == entry.entry_id:
                            value += effect.amplitude * v
            out.append(value / entry.sigma)
    return out


def truth_separation(
    world: HiddenWorld,
    hypothesis: Hypothesis,
    catalog: DiscoveryCatalog,
    available: Sequence[str],
    protocol: DiscoveryProtocol,
) -> float:
    """How close `hypothesis` can come to the truth's fixed predictions over the available
    protocol, replicated as the engine's distinguishability is (`sqrt(R) * distance`)."""
    experiments = [catalog.experiment(e) for e in available]
    y = truth_vector(world, catalog, experiments)
    columns = [
        [
            c.coefficient(x.experiment_id, entry.entry_id) / entry.sigma
            for x in experiments
            for entry in x.entries
        ]
        for c in hypothesis.components
    ]
    lower = [c.lower for c in hypothesis.components]
    upper = [c.upper for c in hypothesis.components]
    _, value = box_lsq(columns, y, lower, upper)
    return math.sqrt(protocol.distinguish_replicates) * math.sqrt(value)


def truth_aliases(
    world: HiddenWorld, catalog: DiscoveryCatalog, protocol: DiscoveryProtocol
) -> tuple[str, ...]:
    """Engine hypotheses (the noise model, each class, each family pair) that the available
    protocol cannot separate from the truth: separation below the engine's `distinguish_tau`."""
    available = world.available(catalog)
    return tuple(
        sorted(
            u.hypothesis_id
            for u in hypothesis_universe(catalog)
            if truth_separation(world, u, catalog, available, protocol) < protocol.distinguish_tau
        )
    )


def _category(world: HiddenWorld, catalog: DiscoveryCatalog, problems: list[str]) -> None:
    where = f"world {world.world_id}"
    declared = [e for e in world.effects if e.declared_class is not None]
    tabulated = [e for e in world.effects if e.declared_class is None]
    sloped = [e for e in tabulated if e.session_slope != 0.0]
    families = [catalog.mechanism(str(e.declared_class)).family for e in declared]
    if len(set(families)) != len(families):
        problems.append(f"{where}: two declared effects share a mechanism family")
    ids = [e.effect_id for e in tabulated]
    if len(set(ids)) != len(ids):
        problems.append(f"{where}: an effect id appears twice")
    c = world.category
    if c == "null" and world.effects:
        problems.append(f"{where}: category null has no effects")
    elif c == "declared" and not (len(world.effects) == 1 and len(declared) == 1):
        problems.append(f"{where}: category declared is exactly one declared class")
    elif c == "composition" and not (len(world.effects) == 2 and len(declared) == 2):
        problems.append(f"{where}: category composition is exactly two declared classes")
    elif c in ("held_out", "aliased_held_out") and (not tabulated or sloped):
        problems.append(f"{where}: category {c} needs a tabulated effect and no session slope")
    elif c == "non_stationary" and not sloped:
        problems.append(f"{where}: category non_stationary needs a non-zero session slope")


#: Categories that are ordinary words and say nothing beyond "the catalog can express it".
_PLAIN_CATEGORIES = frozenset({"declared", "null"})


def _needles(world: HiddenWorld, catalog: DiscoveryCatalog) -> set[str]:
    """Strings that would name this world's truth: its world id, a telling category, and every
    truth class's id, family, mechanism and regime, or effect id (and their last id segment)."""
    needles = {world.world_id}
    if world.category not in _PLAIN_CATEGORIES:
        needles.add(world.category)
    for effect in world.effects:
        if effect.declared_class is not None:
            m = catalog.mechanism(effect.declared_class)
            needles |= {m.class_id, m.family, m.mechanism, m.regime}
            ids = [m.class_id]
        else:
            ids = [str(effect.effect_id)]
            needles.add(str(effect.effect_id))
        for identifier in ids:
            last = identifier.split(".")[-1]
            if len(last) >= 5:
                needles.add(last)
    spelled = {n.replace("_", sep) for n in needles if "_" in n for sep in (" ", "-")}
    return {n for n in needles | spelled if n}


def _leaks(text: str, needles: set[str]) -> list[str]:
    lowered = text.lower()
    return sorted(n for n in needles if needle_pattern(n).search(lowered))


def parse_hidden_worlds(
    data: Any, catalog: DiscoveryCatalog, protocol: DiscoveryProtocol, *, sealed: bool = False
) -> HiddenWorldSet:
    """Validate an author's file (or, with `sealed`, a sealed one) against the engine catalog."""
    problems: list[str] = []
    _floats(data, "$", problems)
    if not isinstance(data, Mapping):
        raise HiddenWorldRefused(["the document is a JSON object"])
    kind = SEALED_KIND if sealed else HIDDEN_WORLDS_KIND
    if data.get("kind") != kind:
        raise HiddenWorldRefused([f"kind {data.get('kind')!r} is not {kind}"])
    if not _keys(data, TOP_KEYS, "$", problems):
        raise HiddenWorldRefused(problems)
    suite = _text(data["suite"], "suite", problems, limit=80)
    example_only = _flag(data["example_only"], "example_only", problems)
    notice = _text(data["notice"], "notice", problems)
    author_label = ""
    if _keys(data["author"], AUTHOR_KEYS, "author", problems):
        if data["author"]["role"] != "world_author":
            problems.append('author.role is "world_author"')
        author_label = _text(data["author"]["label"], "author.label", problems, limit=200)
    interface = _interface(data["interface"], catalog, problems)
    motivating = interface.motivating_experiment if interface else ""
    worlds_raw = data["worlds"]
    if not isinstance(worlds_raw, list) or not worlds_raw:
        problems.append("worlds: a non-empty list")
        worlds_raw = []
    worlds: list[HiddenWorld] = []
    seen: set[str] = set()
    for index, raw in enumerate(worlds_raw):
        where = f"worlds[{index}]"
        if not _keys(raw, SEALED_WORLD_KEYS if sealed else WORLD_KEYS, where, problems):
            continue
        world_id = raw["world_id"]
        if not isinstance(world_id, str) or not _ID.match(world_id):
            problems.append(f"{where}.world_id: [A-Za-z0-9._-]{{1,64}}")
            continue
        if world_id in seen:
            problems.append(f"{where}.world_id {world_id!r} appears twice")
        seen.add(world_id)
        where = f"world {world_id}"
        before = len(problems)
        removed: tuple[tuple[str, str], ...] = ()
        if _keys(raw["public"], PUBLIC_KEYS, f"{where}.public", problems):
            removed = _removed(
                raw["public"]["removed"], f"{where}.public.removed", catalog, motivating, problems
            )
        hidden = raw["hidden"]
        if not _keys(hidden, HIDDEN_KEYS, f"{where}.hidden", problems):
            continue
        category = hidden["category"]
        if category not in CATEGORIES:
            problems.append(f"{where}.hidden.category {category!r} is not one of {CATEGORIES}")
        seed = hidden["seed"]
        if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= MAX_SEED:
            problems.append(f"{where}.hidden.seed: an integer in [0, 2^53 - 1]")
            seed = 0
        effects_raw = hidden["effects"]
        effects: list[Effect] = []
        if not isinstance(effects_raw, list):
            problems.append(f"{where}.hidden.effects: a list")
        else:
            for k, item in enumerate(effects_raw):
                effect = _effect(item, f"{where}.hidden.effects[{k}]", catalog, problems)
                if effect is not None:
                    effects.append(effect)
        noise = Noise()
        if _keys(hidden["noise"], NOISE_KEYS, f"{where}.hidden.noise", problems):
            n = hidden["noise"]
            noise = Noise(
                scale=_decimal(
                    n["scale"], f"{where}.hidden.noise.scale", problems, low=1e-3, high=10
                ),
                glitch_motivating=_flag(
                    n["glitch_motivating"], f"{where}.hidden.noise.glitch_motivating", problems
                ),
                glitch_first=_flag(
                    n["glitch_first"], f"{where}.hidden.noise.glitch_first", problems
                ),
                glitch_sigma=_decimal(
                    n["glitch_sigma"],
                    f"{where}.hidden.noise.glitch_sigma",
                    problems,
                    low=1e-3,
                    high=50,
                ),
            )
        case_id = salt = None
        if sealed:
            salt = raw["salt"]
            case_id = raw["case_id"]
            if (
                not isinstance(salt, str)
                or not re.fullmatch(r"[0-9a-f]{32,}", salt)
                or len(salt) % 2
            ):
                problems.append(f"{where}.salt: at least 16 random bytes, lower-case hex")
            elif case_id != case_id_for(salt):
                problems.append(f"{where}.case_id does not derive from its salt")
        world = HiddenWorld(
            world_id=world_id,
            removed=removed,
            category=str(category),
            seed=int(seed),
            effects=tuple(effects),
            noise=noise,
            case_id=case_id,
            salt=salt,
            public_json=raw["public"],
            hidden_json=hidden,
        )
        if len(problems) > before:
            continue
        _category(world, catalog, problems)
        for experiment_id, reason in removed:
            leaked = _leaks(reason, _needles(world, catalog))
            if leaked:
                problems.append(
                    f"{where}: the removal reason for {experiment_id} names the truth {leaked}; "
                    "it is shown to every arm"
                )
        if len(problems) > before:
            continue
        if category in ("held_out", "aliased_held_out"):
            aliases = truth_aliases(world, catalog, protocol)
            if category == "held_out" and aliases:
                problems.append(
                    f"{where}: category held_out, but the engine cannot separate the truth from "
                    f"{list(aliases)[:4]}: label it aliased_held_out (scored separately)"
                )
            elif category == "aliased_held_out" and not aliases:
                problems.append(
                    f"{where}: category aliased_held_out, but every engine hypothesis is "
                    "distinguishable from the truth: label it held_out"
                )
            world = replace(world, aliases=aliases)
        worlds.append(world)
    if suite:
        for world in worlds:
            leaked = _leaks(suite, _needles(world, catalog))
            if leaked:
                problems.append(f"suite names the truth of {world.world_id}: {leaked}")
    if problems or interface is None:
        raise HiddenWorldRefused(problems or ["interface missing"])
    return HiddenWorldSet(
        suite=suite,
        example_only=example_only,
        notice=notice,
        author_label=author_label,
        interface=interface,
        worlds=tuple(worlds),
    )


def load_document(path: Path, *, repo: Path, allow_example: bool) -> Any:
    """Read an author's or a sealed file, refusing a real hidden set inside the repository and an
    example used as a hidden set."""
    data = json.loads(path.read_text(encoding="utf-8"))
    example = isinstance(data, Mapping) and data.get("example_only") is True
    if path.resolve().is_relative_to(repo.resolve()) and not example:
        raise HiddenWorldRefused(
            [f"{path.name} is inside the repository; a hidden world file is kept outside it"]
        )
    if example and not allow_example:
        raise HiddenWorldRefused(
            [
                f"{path.name} is an example, not a hidden set (allow_example is for the "
                "scaffold demonstration only)"
            ]
        )
    return data


# -- sealing --------------------------------------------------------------------------------------


def case_id_for(salt: str) -> str:
    return "case-" + hashlib.sha256(CASE_DOMAIN + bytes.fromhex(salt)).hexdigest()[:12]


def commitment(world: HiddenWorld) -> str:
    if world.salt is None or world.case_id is None:
        raise ValueError(f"world {world.world_id} is not sealed")
    body = canonical_bytes(
        {
            "case_id": world.case_id,
            "world_id": world.world_id,
            "public": dict(world.public_json),
            "hidden": dict(world.hidden_json),
        }
    )
    return hashlib.sha256(COMMIT_DOMAIN + bytes.fromhex(world.salt) + body).hexdigest()


def seal(
    worlds: HiddenWorldSet, *, salts: Callable[[str], str] | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """(sealed file, engine package). `salts` (world id -> hex) is for reproducible test material
    only; by default every world gets 32 fresh random bytes."""
    sealed_worlds: list[dict[str, Any]] = []
    commitments: dict[str, str] = {}
    cases: list[dict[str, Any]] = []
    for world in sorted(worlds.worlds, key=lambda w: w.world_id):
        salt = salts(world.world_id) if salts is not None else secrets.token_hex(32)
        case_id = case_id_for(salt)
        if case_id in commitments:
            raise ValueError("two worlds drew the same case id; seal again")
        sealed = replace(world, case_id=case_id, salt=salt)
        commitments[case_id] = commitment(sealed)
        sealed_worlds.append(
            {
                "world_id": world.world_id,
                "case_id": case_id,
                "salt": salt,
                "public": dict(world.public_json),
                "hidden": dict(world.hidden_json),
            }
        )
        cases.append({"case_id": case_id, "public": dict(world.public_json)})
    interface = {
        "catalog_ref": worlds.interface.catalog_ref,
        "catalog_digest": worlds.interface.catalog_digest,
        "motivating_experiment": worlds.interface.motivating_experiment,
    }
    sealed_doc = {
        "kind": SEALED_KIND,
        "suite": worlds.suite,
        "example_only": worlds.example_only,
        "notice": worlds.notice,
        "author": {"role": "world_author", "label": worlds.author_label},
        "interface": interface,
        "worlds": sealed_worlds,
    }
    package = {
        "kind": ENGINE_PACKAGE_KIND,
        "suite": worlds.suite,
        "example_only": worlds.example_only,
        "interface": interface,
        "cases": sorted(cases, key=lambda c: c["case_id"]),
        "commitments": dict(sorted(commitments.items())),
        "root": canonical_hash(dict(sorted(commitments.items()))),
    }
    return sealed_doc, package


def _truth_keys(value: Any, where: str, problems: list[str]) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key in TRUTH_KEYS:
                problems.append(f"{where}.{key}: a truth-bearing key in the engine's input")
            _truth_keys(item, f"{where}.{key}", problems)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _truth_keys(item, f"{where}[{index}]", problems)


def parse_engine_package(data: Any, catalog: DiscoveryCatalog) -> EnginePackage:
    """What the engine side may read: refused on any key outside the schema or any truth key."""
    problems: list[str] = []
    _floats(data, "$", problems)
    _truth_keys(data, "$", problems)
    if not isinstance(data, Mapping) or data.get("kind") != ENGINE_PACKAGE_KIND:
        raise HiddenWorldRefused([*problems, f"kind is not {ENGINE_PACKAGE_KIND}"])
    if not _keys(data, ENGINE_TOP_KEYS, "$", problems):
        raise HiddenWorldRefused(problems)
    interface = _interface(data["interface"], catalog, problems)
    motivating = interface.motivating_experiment if interface else ""
    cases: list[EngineCase] = []
    raw_cases = data["cases"]
    if not isinstance(raw_cases, list) or not raw_cases:
        problems.append("cases: a non-empty list")
        raw_cases = []
    for index, raw in enumerate(raw_cases):
        where = f"cases[{index}]"
        if not _keys(raw, ENGINE_CASE_KEYS, where, problems):
            continue
        case_id = raw["case_id"]
        if not isinstance(case_id, str) or not _CASE_ID.match(case_id):
            problems.append(f"{where}.case_id: case-<12 hex>")
            continue
        removed: tuple[tuple[str, str], ...] = ()
        if _keys(raw["public"], PUBLIC_KEYS, f"{where}.public", problems):
            removed = _removed(
                raw["public"]["removed"], f"{where}.public.removed", catalog, motivating, problems
            )
        cases.append(EngineCase(case_id, removed))
    ids = [c.case_id for c in cases]
    if len(set(ids)) != len(ids):
        problems.append("cases: a case id appears twice")
    commitments = data["commitments"]
    if not isinstance(commitments, Mapping) or sorted(commitments) != sorted(ids):
        problems.append("commitments: exactly one per case")
    elif not all(isinstance(v, str) and _HEX64.match(v) for v in commitments.values()):
        problems.append("commitments: SHA-256 hex digests")
    elif canonical_hash(dict(commitments)) != data["root"]:
        problems.append("root: the commitments do not hash to it")
    if problems or interface is None:
        raise HiddenWorldRefused(problems or ["interface missing"])
    return EnginePackage(
        suite=str(data["suite"]),
        example_only=bool(data["example_only"]),
        interface=interface,
        cases=tuple(cases),
        commitments=dict(commitments),
        root=str(data["root"]),
    )


def reveal(
    sealed_data: Any,
    package: EnginePackage,
    catalog: DiscoveryCatalog,
    protocol: DiscoveryProtocol,
) -> HiddenWorldSet:
    """The sealed worlds, after verifying them against the engine package case for case."""
    worlds = parse_hidden_worlds(sealed_data, catalog, protocol, sealed=True)
    if worlds.interface != package.interface:
        raise CommitmentMismatch("the sealed file and the package name different interfaces")
    revealed = {str(w.case_id): w for w in worlds.worlds}
    if set(revealed) != {c.case_id for c in package.cases}:
        raise CommitmentMismatch("the revealed case set differs from the committed one")
    if canonical_hash(dict(package.commitments)) != package.root:
        raise CommitmentMismatch("the package's commitments do not hash to its root")
    bad = sorted(cid for cid, w in revealed.items() if commitment(w) != package.commitments[cid])
    if bad:
        raise CommitmentMismatch(f"revealed worlds do not match their commitments: {bad}")
    for case in package.cases:
        if revealed[case.case_id].removed != case.removed:
            raise CommitmentMismatch(f"{case.case_id}: the package's public part was altered")
    return worlds


# -- the laboratory, the blind run and scoring ----------------------------------------------------


class HiddenWorldLab:
    """A `Laboratory` for one hidden world. With only declared effects, unit noise scale and no
    slope, it reads exactly what `lab_brain.discovery.worlds.SyntheticWorld` reads for the same
    seed, world id and truth (the same common-random-number keys)."""

    def __init__(
        self, world: HiddenWorld, catalog: DiscoveryCatalog, motivating_experiment: str
    ) -> None:
        self._world = world
        self._catalog = catalog
        self._motivating = motivating_experiment

    def _truth(self, experiment: ExperimentSpec, session: int) -> dict[str, float]:
        values = {e.entry_id: 0.0 for e in experiment.entries}
        for effect in self._world.effects:
            if effect.declared_class is not None:
                m = self._catalog.mechanism(effect.declared_class)
                for entry in experiment.entries:
                    values[entry.entry_id] += effect.amplitude * m.coefficient(
                        experiment.experiment_id, entry.entry_id
                    )
            else:
                factor = effect.amplitude * (1.0 + effect.session_slope * session)
                for experiment_id, entry_id, v in effect.sensitivity:
                    if experiment_id == experiment.experiment_id:
                        values[entry_id] += factor * v
        return values

    def _sample(
        self, experiment: ExperimentSpec, key: str, session: int, glitch: bool
    ) -> tuple[tuple[str, float], ...]:
        w = self._world
        rng = random.Random(f"{w.seed}:{w.world_id}:{key}")
        truth = self._truth(experiment, session)
        values = {
            e.entry_id: truth[e.entry_id] + w.noise.scale * e.sigma * rng.gauss(0.0, 1.0)
            for e in experiment.entries
        }
        if glitch:
            g = random.Random(f"{w.seed}:{w.world_id}:glitch:{key}")
            entry = experiment.entries[g.randrange(len(experiment.entries))]
            sign = 1.0 if g.random() < 0.5 else -1.0
            values[entry.entry_id] += sign * w.noise.glitch_sigma * entry.sigma
        return tuple((e.entry_id, values[e.entry_id]) for e in experiment.entries)

    def motivating(self) -> tuple[str, tuple[tuple[str, float], ...]]:
        experiment = self._catalog.experiment(self._motivating)
        return experiment.experiment_id, self._sample(
            experiment, "motivating", 0, self._world.noise.glitch_motivating
        )

    def measure(
        self, experiment_id: str, *, replicate: int, session: int
    ) -> tuple[tuple[str, float], ...]:
        experiment = self._catalog.experiment(experiment_id)
        return self._sample(
            experiment,
            f"{experiment_id}:{replicate}",
            session,
            self._world.noise.glitch_first and session == 1,
        )


def sealed_laboratories(
    worlds: HiddenWorldSet, catalog: DiscoveryCatalog
) -> Callable[[str], Laboratory]:
    """The laboratory service: case id -> laboratory. It holds the sealed worlds; the engine never
    does. (In-process here: the offline scaffold, not the protocol's process boundary.)"""
    by_case = {str(w.case_id): w for w in worlds.worlds}
    motivating = worlds.interface.motivating_experiment

    def laboratory(case_id: str) -> Laboratory:
        return HiddenWorldLab(by_case[case_id], catalog, motivating)

    return laboratory


def run_blind(
    package: EnginePackage,
    catalog: DiscoveryCatalog,
    *,
    arms: Sequence[Arm],
    budget: int,
    laboratories: Callable[[str], Laboratory],
) -> dict[str, Any]:
    """Every arm on every case, from the package alone; outputs bound to the package root."""
    if (package.interface.catalog_ref, package.interface.catalog_digest) != (
        catalog.ref,
        catalog.digest,
    ):
        raise HiddenWorldRefused(["the package was written against another catalog"])
    protocol = shared_protocol(arms)
    experiments = {
        e.experiment_id: e
        for e in (*catalog.experiments, *(u.experiment for u in catalog.unavailable))
    }
    costs = {k: e.cost for k, e in experiments.items()}
    cases: dict[str, Any] = {}
    for case in package.cases:
        available = case.available(catalog)
        oracle = SeparationOracle(catalog, available, protocol, dict(case.removed))
        per_arm: dict[str, Any] = {}
        for arm in arms:
            meter = CostMeter(costs, budget)
            lab = blind_laboratory(
                laboratories(case.case_id),
                experiments=experiments,
                available=available,
                meter=meter,
            )
            result = arm.runner(
                arm=arm.arm_id,
                catalog=catalog,
                oracle=oracle,
                protocol=arm.protocol,
                budget=Budget(budget),
                lab=lab,
            )
            per_arm[arm.arm_id] = {
                "outcome": result.outcome.value,
                "claim": list(result.claim),
                "spent": meter.spent,
                "reported_spent": result.spent,
                "budget": budget,
                "experiments": [s.experiment_id for s in result.steps],
                "open_anomalies": sum(
                    1
                    for a in result.anomalies
                    if a.state in (AnomalyState.UNEXPLAINED, AnomalyState.ACCOMMODATED)
                ),
                "reframings": [r.kind.value for r in result.reframings],
                "digest": result.digest,
            }
        cases[case.case_id] = per_arm
    return {
        "kind": OUTPUTS_KIND,
        "package_root": package.root,
        "engine": {
            "catalog_ref": catalog.ref,
            "catalog_digest": catalog.digest,
            "protocols": {a.arm_id: a.protocol.digest for a in arms},
        },
        "budget": budget,
        "cases": cases,
    }


def _claimed(catalog: DiscoveryCatalog, hypothesis_id: str) -> Hypothesis:
    if hypothesis_id == NULL_HYPOTHESIS_ID:
        return NULL_HYPOTHESIS
    if not hypothesis_id.startswith("hyp:"):
        raise ScoringRefused(f"{hypothesis_id!r} is not a hypothesis id")
    known = {m.class_id: m for m in catalog.mechanisms}
    parts = hypothesis_id[len("hyp:") :].split("+")
    if any(p not in known for p in parts):
        raise ScoringRefused(f"{hypothesis_id!r} names a class outside the engine catalog")
    return make_hypothesis(*(known[p] for p in parts))


def score_outputs(
    outputs: Mapping[str, Any],
    worlds: HiddenWorldSet,
    package: EnginePackage,
    catalog: DiscoveryCatalog,
    protocol: DiscoveryProtocol,
    *,
    seed: int,
    resamples: int,
) -> dict[str, Any]:
    """The evaluator's scoring, after `reveal`. A case with no output fails every metric."""
    if outputs.get("kind") != OUTPUTS_KIND or outputs.get("package_root") != package.root:
        raise ScoringRefused("the outputs were not produced against this engine package")
    by_case = {str(w.case_id): w for w in worlds.worlds}
    if set(by_case) != {c.case_id for c in package.cases}:
        raise ScoringRefused("score only a verified reveal of this package")
    unknown = sorted(set(outputs["cases"]) - set(by_case))
    if unknown:
        raise ScoringRefused(f"outputs name cases that were never committed: {unknown}")
    scorer = Scorer(catalog)
    arms = sorted({arm for per_arm in outputs["cases"].values() for arm in per_arm})
    rows: list[dict[str, Any]] = []
    for case_id in sorted(by_case):
        world = by_case[case_id]
        oracle = SeparationOracle(catalog, world.available(catalog), protocol, dict(world.removed))
        for arm in arms:
            entry = outputs["cases"].get(case_id, {}).get(arm)
            row: dict[str, Any] = {"case_id": case_id, "world_id": world.world_id, "arm": arm}
            row["category"] = world.category
            if entry is None:
                rows.append(
                    {
                        **row,
                        "status": "MISSING",
                        "correct": False,
                        "false_discovery": False,
                        "surrogate": False,
                        "spent": None,
                        "within_cap": False,
                    }
                )
                continue
            outcome = Outcome(entry["outcome"])
            claim_made = outcome in CLAIM_OUTCOMES
            claimed = [_claimed(catalog, h) for h in entry["claim"]] if claim_made else []
            surrogate = False
            if world.expressible:
                truth = world.truth_hypothesis(catalog)
                assert truth is not None
                near, simple = scorer.truth_class(truth, oracle)
                fps = frozenset(h.fingerprint for h in claimed)
                correct = claim_made and truth.fingerprint in fps and fps <= near and simple <= fps
                false_discovery = claim_made and not (fps & near)
            else:
                correct = not claim_made
                surrogate = (
                    world.category == "aliased_held_out"
                    and claim_made
                    and bool({h.hypothesis_id for h in claimed} & set(world.aliases))
                )
                false_discovery = claim_made and not surrogate
            rows.append(
                {
                    **row,
                    "status": "SCORED",
                    "outcome": outcome.value,
                    "claim": list(entry["claim"]),
                    "correct": correct,
                    "false_discovery": false_discovery,
                    "surrogate": surrogate,
                    "spent": entry["spent"],
                    "within_cap": entry["spent"] <= entry["budget"]
                    and entry["spent"] == entry["reported_spent"],
                }
            )
    summary: dict[str, Any] = {}
    for arm in arms:
        mine = [r for r in rows if r["arm"] == arm]
        primary = [r for r in mine if r["category"] != "aliased_held_out"]
        summary[arm] = {
            "correct": rate([r["correct"] for r in primary]),
            "false_discovery": rate([r["false_discovery"] for r in primary]),
            "realized_cost": mean(
                [float(r["spent"]) for r in mine if r["spent"] is not None],
                seed=seed,
                resamples=resamples,
                label=f"hidden:{arm}:realized",
            ),
            "missing": sum(1 for r in mine if r["status"] == "MISSING"),
            "all_within_cap_and_metered": all(r["within_cap"] for r in mine),
            "per_category": {
                c: {
                    "n": sum(1 for r in mine if r["category"] == c),
                    "correct": sum(1 for r in mine if r["category"] == c and r["correct"]),
                    "false_discovery": sum(
                        1 for r in mine if r["category"] == c and r["false_discovery"]
                    ),
                    "surrogate": sum(1 for r in mine if r["category"] == c and r["surrogate"]),
                }
                for c in CATEGORIES
                if any(r["category"] == c for r in mine)
            },
        }
    return {"package_root": package.root, "cases": len(by_case), "arms": summary, "rows": rows}


__all__ = [
    "CATEGORIES",
    "ENGINE_PACKAGE_KIND",
    "HIDDEN_WORLDS_KIND",
    "OUTPUTS_KIND",
    "SEALED_KIND",
    "TRUTH_KEYS",
    "CommitmentMismatch",
    "Effect",
    "EngineCase",
    "EnginePackage",
    "HiddenWorld",
    "HiddenWorldLab",
    "HiddenWorldRefused",
    "HiddenWorldSet",
    "Interface",
    "Noise",
    "ScoringRefused",
    "case_id_for",
    "commitment",
    "load_document",
    "parse_engine_package",
    "parse_hidden_worlds",
    "reveal",
    "run_blind",
    "score_outputs",
    "seal",
    "sealed_laboratories",
    "truth_aliases",
    "truth_separation",
    "truth_vector",
]
