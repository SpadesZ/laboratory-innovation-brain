"""Evaluate safety v1.4 (B7) beside v1.3 (B6) and the v1.1 baseline (B4), world by world.

    python scripts/discovery_safety_v14_eval.py --reanalyse-v13          # the mean-cost problem
    python scripts/discovery_safety_v14_eval.py --dev BASE PER [--budgets 8,12] [--settings ...]
    python scripts/discovery_safety_v14_eval.py --design-freeze SHA      # held-out, ONCE
    python scripts/discovery_safety_v14_eval.py --check [--record-interpreter]
    python scripts/discovery_safety_v14_eval.py --hidden-package P --hidden-sealed S --out DIR
    python scripts/discovery_safety_v14_eval.py --hidden-example         # the example file only
    python scripts/discovery_safety_v14_eval.py --arm-worker             # (internal)

Offline and zero-cost: no model, simulator, network or database; Discovery is not connected to real
research execution. The engine, the 2026-11-02 evaluation tooling and the v1.0-v1.3 safety packages
are used exactly as frozen (their source hashes are checked against their manifests).

    boundary     every arm runs in a separate process (`--arm-worker`, a fresh interpreter) that
                 receives only its catalog, the available experiments (and removal reasons), the
                 cap and laboratory replies; the world, its truth, the meter and the ledger stay in
                 the evaluator's process (`lab_brain.discovery_safety.v13.boundary`)
    freeze       `--design-freeze SHA` refuses unless the v1.4 package and this script are
                 byte-identical to that commit; the held-out base seeds are then DERIVED from the
                 commit's full id (`v14.model.holdout_base_seed`, domain string
                 `HOLDOUT_DOMAIN`), so nobody could choose them before the freeze
    development  `--dev BASE PER` runs declared development seeds only (v1.3's held-out and
                 benchmark ranges are development data now) and writes nothing
    hidden       the independent protocol's scaffold: the engine side reads only the ENGINE PACKAGE
                 (`parse_engine_package`); the evaluator's laboratory serves the sealed worlds by
                 opaque case id; every arm runs blind in its own process at every cap; then the
                 evaluator verifies the reveal against the commitments and scores. A real hidden set
                 must live outside the repository (`load_document` refuses it inside)

SCORING. SAI 3.5 candidate.5 (spec commit 61af6ef) with the evaluator's v1.4 verdict for every arm;
the v1.3 rule's level beside. Comparisons world by world at equal realized cost
(`v14.costmatch.per_world_matched`), cost distributions beside every table.

WHAT THE NUMBERS ARE. ENGINEERING EVIDENCE ONLY on developer-authored synthetic worlds. Not
scientific validity, not an independent evaluation, nothing about a real device. Scientific
acceptance and G-D: NOT PASSED.

The composition root that names the silicon-photonics scenario and its grammar; `pyproject.toml`
exempts this single file from the §24.2 import ban.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from importlib import metadata
from multiprocessing import Pool
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lab_brain.discovery import benchmark  # noqa: E402
from lab_brain.discovery.catalog import DiscoveryCatalog  # noqa: E402
from lab_brain.discovery.distinguish import SeparationOracle  # noqa: E402
from lab_brain.discovery.metrics import Scorer  # noqa: E402
from lab_brain.discovery.model import (  # noqa: E402
    CLAIM_OUTCOMES,
    Hypothesis,
    Outcome,
    make_hypothesis,
    stable_digest,
    to_jsonable,
)
from lab_brain.discovery.protocol import DISCOVERY  # noqa: E402
from lab_brain.discovery.worlds import SyntheticWorld  # noqa: E402
from lab_brain.discovery_eval import held_out  # noqa: E402
from lab_brain.discovery_eval import hidden_worlds as hw  # noqa: E402
from lab_brain.discovery_safety.model import SAFETY  # noqa: E402
from lab_brain.discovery_safety.v11.model import SAFETY_V11  # noqa: E402
from lab_brain.discovery_safety.v12.evaluation import Judge  # noqa: E402
from lab_brain.discovery_safety.v12.grammar import grammar_from_declaration  # noqa: E402
from lab_brain.discovery_safety.v12.model import SAFETY_V12  # noqa: E402
from lab_brain.discovery_safety.v13 import evaluation as ev13  # noqa: E402
from lab_brain.discovery_safety.v13.boundary import serve_run, worker_loop  # noqa: E402
from lab_brain.discovery_safety.v13.ledger import EvaluatorLaboratory  # noqa: E402
from lab_brain.discovery_safety.v13.model import (  # noqa: E402
    EVALUATOR_RULE,
    SAFETY_V13,
    ArmAnswer,
)
from lab_brain.discovery_safety.v14 import costmatch  # noqa: E402
from lab_brain.discovery_safety.v14 import evaluation as ev  # noqa: E402
from lab_brain.discovery_safety.v14.model import (  # noqa: E402
    EVALUATOR_RULE_V14,
    HOLDOUT_DOMAIN,
    PLAN,
    SAFETY_V14,
)
from lab_brain.domains.silicon_photonics import discovery_grammar  # noqa: E402
from lab_brain.domains.silicon_photonics.discovery_catalog import (  # noqa: E402
    MOTIVATING_EXPERIMENT,
    ring_catalog,
    ring_scenario,
)

EVIDENCE_DIR = ROOT / "docs" / "audit" / "discovery-safety-v1.4-2026-11-21"
DEFAULT_OUT = EVIDENCE_DIR / "evidence"
AUDIT = ROOT / "docs" / "audit"
FROZEN_ENGINE = AUDIT / "discovery-loop-offline-2026-11-01" / "evidence"
FROZEN_EVAL = AUDIT / "discovery-independent-evaluation-2026-11-02" / "evidence"
FROZEN_V10 = AUDIT / "discovery-unknown-mechanism-safety-2026-11-04" / "evidence"
FROZEN_V11 = AUDIT / "discovery-safety-v1.1-2026-11-04" / "evidence"
FROZEN_V12 = AUDIT / "discovery-safety-v1.2-2026-11-08" / "evidence"
FROZEN_V13 = AUDIT / "discovery-safety-v1.3-2026-11-11" / "evidence"
V14_PACKAGE = ROOT / "src" / "lab_brain" / "discovery_safety" / "v14"
EXAMPLE = ROOT / "benchmarks" / "discovery_independent" / "example.hidden-worlds.json"
INTERPRETERS_FILE = "interpreter_verification.json"
DEPENDENCIES = ("pydantic", "pydantic-core", "PyYAML", "cryptography")
GRAMMAR = grammar_from_declaration(discovery_grammar.declaration())
SETTINGS = ("held_out", "control", "benchmark")
REANALYSIS_FILE = "v13_reanalysis.json"


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout


def _commit() -> str:
    try:
        head = _git("rev-parse", "HEAD").strip()
        dirty = _git("status", "--porcelain", "--", "src", "scripts").strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return f"{head}{'+dirty' if dirty else ''}"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _dump_rows(rows: list[dict[str, Any]]) -> str:
    return (
        "[\n"
        + ",\n".join(json.dumps(r, sort_keys=True, ensure_ascii=False) for r in rows)
        + "\n]\n"
    )


def interpreter_key() -> str:
    return f"{platform.python_implementation()} {sys.version_info.major}.{sys.version_info.minor}"


def environment() -> dict[str, Any]:
    versions: dict[str, str] = {}
    for name in DEPENDENCIES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = "absent"
    return {
        "interpreter": f"{platform.python_implementation()} {platform.python_version()}",
        "interpreter_key": interpreter_key(),
        "platform": platform.platform(),
        "dependencies": versions,
        "numerical_libraries": "none (no numpy, scipy or other compiled numerics are imported)",
    }


def v14_sources() -> dict[str, str]:
    files = [*sorted(V14_PACKAGE.glob("*.py")), Path(__file__).resolve()]
    return {_rel(p): _sha256(p) for p in files}


def frozen_inputs(scenario: benchmark.Scenario) -> dict[str, Any]:
    engine = _load(FROZEN_ENGINE / "manifest.json")
    evaluation = _load(FROZEN_EVAL / "manifest.json")
    manifests = {
        "v10": (_load(FROZEN_V10 / "manifest.json"), "safety_sources_sha256"),
        "v11": (_load(FROZEN_V11 / "manifest.json"), "v11_sources_sha256"),
        "v12": (_load(FROZEN_V12 / "manifest.json"), "v12_sources_sha256"),
        "v13": (_load(FROZEN_V13 / "manifest.json"), "v13_sources_sha256"),
    }
    out: dict[str, Any] = {
        "engine_sources_match_frozen_manifest": benchmark.source_hashes(scenario, ROOT)
        == engine["sources_sha256"],
        "evaluation_sources_match_frozen_manifest": {
            r: _sha256(ROOT / r) for r in evaluation["evaluation_sources_sha256"]
        }
        == evaluation["evaluation_sources_sha256"],
    }
    for name, (manifest, key) in manifests.items():
        frozen = {k: v for k, v in manifest[key].items() if not k.startswith("scripts/")}
        out[f"{name}_sources_match_frozen_manifest"] = {
            r: _sha256(ROOT / r) for r in frozen
        } == frozen
        out[f"frozen_{name}_manifest_sha256"] = manifest["manifest_sha256"]
    out["v10_protocol_digest_matches"] = (
        manifests["v10"][0]["inputs"]["safety_protocol_digest"] == SAFETY.digest
    )
    out["v11_protocol_digest_matches"] = (
        manifests["v11"][0]["inputs"]["safety_protocol_digest"] == SAFETY_V11.digest
    )
    out["v12_protocol_digest_matches"] = (
        manifests["v12"][0]["inputs"]["safety_protocol_digest"] == SAFETY_V12.digest
    )
    out["v13_protocol_digest_matches"] = (
        manifests["v13"][0]["inputs"]["safety_protocol_digest"] == SAFETY_V13.digest
    )
    out["v13_evaluator_rule_digest_matches"] = (
        manifests["v13"][0]["inputs"]["evaluator_rule_digest"] == EVALUATOR_RULE.digest
    )
    out["v12_grammar_digest_matches"] = (
        manifests["v12"][0]["inputs"]["grammar_digest"] == GRAMMAR.digest
    )
    out["frozen_engine_manifest_sha256"] = engine["manifest_sha256"]
    out["frozen_evaluation_manifest_sha256"] = evaluation["manifest_sha256"]
    if not all(v for k, v in out.items() if k.endswith(("_manifest", "_matches"))):
        raise SystemExit(f"a frozen input drifted; refusing to continue: {out}")
    return out


def design_freeze(commit: str) -> dict[str, Any]:
    """The freeze record, refused unless the v1.4 package and this script are the commit's."""
    try:
        resolved = _git("rev-parse", "--verify", f"{commit}^{{commit}}").strip()
        listed = _git("ls-tree", "--name-only", resolved, _rel(V14_PACKAGE) + "/").split()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"cannot read the design-freeze commit {commit}: {exc}") from exc
    at_freeze = {}
    for relative in [*sorted(p for p in listed if p.endswith(".py")), _rel(Path(__file__))]:
        blob = subprocess.run(
            ["git", "show", f"{resolved}:{relative}"], cwd=ROOT, capture_output=True, check=True
        ).stdout
        at_freeze[relative] = hashlib.sha256(blob).hexdigest()
    if at_freeze != v14_sources():
        raise SystemExit(
            "the v1.4 sources differ from the design-freeze commit; the evaluation would not be of "
            "the frozen design"
        )
    return {
        "commit": resolved,
        "v14_sources_identical_to_freeze": True,
        "protocol_digest": SAFETY_V14.digest,
        "evaluator_rule_digest": EVALUATOR_RULE_V14.digest,
        "plan_digest": PLAN.digest,
        "grammar_digest": GRAMMAR.digest,
        "held_out_seed_rule": {
            "domain": HOLDOUT_DOMAIN,
            "rule": "base = 3_000_000_000 + 1000 * (int(SHA-256(domain || 0x00 || role || 0x00 || "
            "full commit id || 0x00 || attempt)) mod 1_000_000); the first attempt (0, 1, ...) at "
            "least 20_000 from every earlier range and from the other role's range",
            "seeds": PLAN.held_out_seeds(resolved),
        },
    }


# -- the arm process --------------------------------------------------------------------------

_CATALOG: list[Any] = []
_ORACLES: dict[tuple[Any, ...], tuple[Any, SeparationOracle]] = {}


def _case_token(setting: str, world_id: str) -> str:
    """An opaque per-case token (it names no world, kind or truth): one oracle per case in the arm
    process, so cached separations never depend on which cases the process ran before."""
    return hashlib.sha256(f"lab-brain/v1.4/case/{setting}/{world_id}".encode()).hexdigest()[:16]


def _arm_catalog(request: Mapping[str, Any]) -> tuple[Any, SeparationOracle]:
    """The catalog and oracle the arm holds at case start (no world, no truth), one per case."""
    if not _CATALOG:
        _CATALOG.append(ring_catalog())
    catalog = _CATALOG[0]
    family = str(request.get("family") or "")
    available = tuple(request["available"])
    removed = tuple((str(a), str(b)) for a, b in request.get("removed", ()))
    key = (str(request.get("case", "")), family, available, removed)
    if key not in _ORACLES:
        _ORACLES.clear()
        engine_catalog = held_out.without_family(catalog, family) if family else catalog
        _ORACLES[key] = (
            engine_catalog,
            SeparationOracle(engine_catalog, available, DISCOVERY, dict(removed)),
        )
    return _ORACLES[key]


def _handle(request: Mapping[str, Any], lab: Any) -> ArmAnswer:
    catalog, oracle = _arm_catalog(request)
    return ev.run_arm(
        str(request["arm"]),
        catalog=catalog,
        oracle=oracle,
        budget=int(request["budget"]),
        lab=lab,
        grammar=GRAMMAR,
    )


class ArmProcess:
    """One arm process (a fresh interpreter running `--arm-worker`), reused for many runs."""

    def __init__(self) -> None:
        self.process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--arm-worker"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )

    def run(self, request: Mapping[str, Any], lab: EvaluatorLaboratory) -> ArmAnswer:
        assert self.process.stdin is not None and self.process.stdout is not None
        return serve_run(request, lab, self.process.stdin, self.process.stdout)


_PROCESS: list[ArmProcess] = []


def _execute_in_process(request: Mapping[str, Any], lab: EvaluatorLaboratory) -> ArmAnswer:
    return _handle(request, lab)


def _execute_boundary(request: Mapping[str, Any], lab: EvaluatorLaboratory) -> ArmAnswer:
    if not _PROCESS:
        _PROCESS.append(ArmProcess())
    return _PROCESS[0].run(request, lab)


# -- the evaluator's cases --------------------------------------------------------------------


def held_out_case(world: held_out.HeldOutWorld, removed: bool) -> ev.WorldCase:
    catalog = ring_catalog()
    all_ids = tuple(e.experiment_id for e in catalog.experiments)
    full = SeparationOracle(catalog, all_ids, DISCOVERY)
    truth = make_hypothesis(catalog.mechanism(world.truth_class))
    if removed:
        engine_catalog = held_out.without_family(catalog, world.family)
        held_out.assert_family_absent(
            engine_catalog, [m for m in catalog.mechanisms if m.family == world.family]
        )
        engine_oracle = SeparationOracle(engine_catalog, all_ids, DISCOVERY)

        def own(outcome: str, claim: tuple[str, ...], fingerprints: frozenset[str]) -> str:
            if Outcome(outcome) not in CLAIM_OUTCOMES:
                return "NO_CLAIM"
            if Outcome(outcome) is Outcome.NO_EFFECT_BEYOND_NOISE:
                return "FALSE_NULL"
            if world.aliased and set(claim) & set(world.aliases):
                return "INDISTINGUISHABLE_ALTERNATIVE"
            return "FORCE_FIT"

    else:
        engine_catalog, engine_oracle = catalog, full
        scorer = Scorer(catalog)

        def own(outcome: str, claim: tuple[str, ...], fingerprints: frozenset[str]) -> str:
            return ev13.own_category_v11(scorer, world.spec, outcome, fingerprints, full)

    setting = "held_out" if removed else "control"
    return ev.WorldCase(
        setting=setting,
        world_id=world.spec.world_id,
        kind=f"held_out:{world.family}",
        aliased=world.aliased and removed,
        lab_factory=lambda: SyntheticWorld(world.spec, catalog, MOTIVATING_EXPERIMENT),
        engine_catalog=engine_catalog,
        engine_oracle=engine_oracle,
        full_catalog=catalog,
        judge=lambda held: Judge(truth, dict(world.spec.truth), held, full),
        request={
            "case": _case_token(setting, world.spec.world_id),
            "family": world.family if removed else "",
            "available": list(all_ids),
        },
        own=own,
    )


def benchmark_case(scenario: benchmark.Scenario, world: Any, oracles: Any) -> ev.WorldCase:
    oracle = oracles.for_world(world)
    scorer = Scorer(scenario.catalog)
    truth = world.truth_hypothesis(scenario.catalog)

    def own(outcome: str, claim: tuple[str, ...], fingerprints: frozenset[str]) -> str:
        return ev13.own_category_v11(scorer, world, outcome, fingerprints, oracle)

    return ev.WorldCase(
        setting="benchmark",
        world_id=world.world_id,
        kind=world.kind,
        aliased=False,
        lab_factory=lambda: benchmark.lab_for(scenario, world),
        engine_catalog=scenario.catalog,
        engine_oracle=oracle,
        full_catalog=scenario.catalog,
        judge=lambda held: Judge(truth, dict(world.truth), held, oracle),
        request={
            "case": _case_token("benchmark", world.world_id),
            "family": "",
            "available": [e.experiment_id for e in oracle.available],
            "removed": [list(r) for r in world.removed],
        },
        own=own,
    )


# -- hidden worlds (lab-brain/discovery-hidden-worlds@1) ---------------------------------------


class HiddenJudge(Judge):
    """The evaluator's judge for one REVEALED hidden world. An expressible truth (declared,
    composition, null) is judged as v1.3 judges a synthetic world. A tabulated truth is not an
    engine hypothesis: an answer matches it iff the answer's forward model can come within the
    engine's distinguishability tau of the truth's fixed predictions over the available protocol
    (`hidden_worlds.truth_separation`); a non-stationary truth matches nothing."""

    def __init__(
        self,
        world: hw.HiddenWorld,
        catalog: DiscoveryCatalog,
        held: Sequence[Hypothesis],
        oracle: SeparationOracle,
    ) -> None:
        truth = world.truth_hypothesis(catalog)
        point = {str(e.declared_class): e.amplitude for e in world.effects if e.declared_class}
        super().__init__(truth, point, held, oracle)
        self.world = world
        self.catalog = catalog
        self.available_ids = world.available(catalog)

    def matches(self, h: Hypothesis) -> bool:
        if self.world.expressible:
            return super().matches(h)
        if self.world.category == "non_stationary":
            return False
        tau = self.full.protocol.distinguish_tau
        if h.is_null or not h.components:
            experiments = [self.catalog.experiment(e) for e in self.available_ids]
            y = hw.truth_vector(self.world, self.catalog, experiments)
            return (
                math.sqrt(self.full.protocol.distinguish_replicates)
                * math.sqrt(math.fsum(v * v for v in y))
                < tau
            )
        return (
            hw.truth_separation(self.world, h, self.catalog, self.available_ids, self.full.protocol)
            < tau
        )

    def catalog_category(self, members: Sequence[Hypothesis]) -> str:
        if self.world.expressible:
            return super().catalog_category(members)
        if members and all(self.matches(m) for m in members):
            return ev13.INDISTINGUISHABLE  # a surrogate of an aliased truth
        return ev13.WRONG_CLAIM if self.any_held_matches() else ev13.FORCE_FIT


def hidden_case(world: hw.HiddenWorld, catalog: DiscoveryCatalog, case_id: str) -> ev.WorldCase:
    """One sealed world as the evaluator holds it; the arm's request carries only the opaque case
    id, the available experiments and the removal reasons (the engine package's public part)."""
    available = world.available(catalog)
    oracle = SeparationOracle(catalog, available, DISCOVERY, dict(world.removed))
    scorer = Scorer(catalog)

    def own(outcome: str, claim: tuple[str, ...], fingerprints: frozenset[str]) -> str:
        if Outcome(outcome) not in CLAIM_OUTCOMES:
            return "NO_CLAIM"
        if world.expressible:
            truth = world.truth_hypothesis(catalog)
            assert truth is not None
            near, simple = scorer.truth_class(truth, oracle)
            if (
                truth.fingerprint in fingerprints
                and fingerprints <= near
                and simple <= fingerprints
            ):
                return "CORRECT_IDENTIFICATION"
            if Outcome(outcome) is Outcome.NO_EFFECT_BEYOND_NOISE and not truth.is_null:
                return "FALSE_NULL"
            return (
                "INDISTINGUISHABLE_ALTERNATIVE"
                if fingerprints and fingerprints <= near
                else "FORCE_FIT"
            )
        if Outcome(outcome) is Outcome.NO_EFFECT_BEYOND_NOISE:
            return "FALSE_NULL"
        if world.category == "aliased_held_out" and set(claim) & set(world.aliases):
            return "INDISTINGUISHABLE_ALTERNATIVE"
        return "FORCE_FIT"

    return ev.WorldCase(
        setting="hidden",
        world_id=case_id,
        kind=world.category,
        aliased=world.category == "aliased_held_out",
        lab_factory=lambda: hw.HiddenWorldLab(world, catalog, MOTIVATING_EXPERIMENT),
        engine_catalog=catalog,
        engine_oracle=oracle,
        full_catalog=catalog,
        judge=lambda held: HiddenJudge(world, catalog, held, oracle),
        request={
            "case": case_id,
            "family": "",
            "available": list(available),
            "removed": [list(r) for r in world.removed],
        },
        own=own,
    )


# -- running ------------------------------------------------------------------------------------

_MODE: list[str] = ["boundary"]
_ARMS: list[tuple[str, ...]] = [ev.ARM_IDS]


def _evaluator() -> ev.Evaluator:
    execute = _execute_boundary if _MODE[0] == "boundary" else _execute_in_process
    return ev.Evaluator(execute, GRAMMAR, EVALUATOR_RULE_V14, _ARMS[0])


def _init(mode: str, arms: tuple[str, ...]) -> None:
    _MODE[0] = mode
    _ARMS[0] = arms


def _held_out_task(args: tuple[int, int, int, bool, tuple[int, ...]]) -> list[ev.RunRecord]:
    base, per, index, removed, budgets = args
    worlds = held_out.held_out_worlds(
        ring_catalog(), seeds_per_class=per, base_seed=base, protocol=DISCOVERY
    )
    return _evaluator().run(held_out_case(worlds[index], removed), budgets)


def _benchmark_task(args: tuple[int, int, int, tuple[int, ...]]) -> list[ev.RunRecord]:
    base, per, index, budgets = args
    scenario = ring_scenario(per, base_seed=base)
    oracles = benchmark.Oracles(scenario.catalog, DISCOVERY)
    return _evaluator().run(benchmark_case(scenario, scenario.worlds[index], oracles), budgets)


def _map(fn: Any, tasks: list[Any], jobs: int, mode: str, arms: tuple[str, ...]) -> list[Any]:
    if jobs <= 1:
        _init(mode, arms)
        return [r for t in tasks for r in fn(t)]
    with Pool(jobs, initializer=_init, initargs=(mode, arms)) as pool:
        return [r for rs in pool.map(fn, tasks, chunksize=1) for r in rs]


def comparisons(
    rows: Sequence[Mapping[str, Any]], budgets: Sequence[int], label: str, arms: Sequence[str]
) -> dict[str, Any]:
    """Per-world matched comparisons (and, for contrast, what a mean-cost match would say)."""
    out: dict[str, Any] = {"method": "per-world matched at equal realized cost (v14.costmatch)"}
    for y, x in PLAN.comparisons:
        if y not in arms or x not in arms:
            continue
        out[f"{y}-{x}"] = {
            "per_world": [
                costmatch.per_world_matched(
                    rows,
                    y,
                    x,
                    cap,
                    tolerance=PLAN.per_world_tolerance,
                    resamples=PLAN.bootstrap_resamples,
                    label=label,
                )
                for cap in budgets
            ],
            "mean_cost_contrast": [
                costmatch.cost_contrast(
                    rows,
                    y,
                    x,
                    cap,
                    tolerance=PLAN.per_world_tolerance,
                    resamples=PLAN.bootstrap_resamples,
                    label=label,
                )
                for cap in budgets
            ],
        }
    return out


def held_out_set(
    log: list[str],
    base: int,
    per: int,
    budgets: tuple[int, ...],
    jobs: int,
    role: str,
    settings: tuple[str, ...] = SETTINGS,
    mode: str = "boundary",
    arms: tuple[str, ...] = ev.ARM_IDS,
) -> tuple[dict[str, Any], dict[str, str], list[ev.RunRecord]]:
    worlds = held_out.held_out_worlds(
        ring_catalog(), seeds_per_class=per, base_seed=base, protocol=DISCOVERY
    )
    out: dict[str, Any] = {
        "role": role,
        "base_seed": base,
        "seeds_per_class": per,
        "worlds": len(worlds),
        "worlds_primary": sum(1 for w in worlds if not w.aliased),
        "worlds_aliased": sum(1 for w in worlds if w.aliased),
        "specs_digest": stable_digest(worlds),
    }
    files: dict[str, str] = {}
    every: list[ev.RunRecord] = []
    for removed, name in ((True, "held_out"), (False, "control")):
        if name not in settings:
            continue
        tasks = [(base, per, i, removed, budgets) for i in range(len(worlds))]
        records = _map(_held_out_task, tasks, jobs, mode, arms)
        every.extend(records)
        rows = ev.records_as_json(records)
        part: dict[str, Any] = {
            "setting": "true family REMOVED from the engine's catalog"
            if removed
            else "the same worlds with the family LEFT IN the catalog",
            "by_budget": ev.summarize(records, budgets, arms),
            "budget_never_exceeded": all(r.spent <= r.budget for r in records),
        }
        if removed:
            part["matched_primary"] = comparisons(
                [r for r in rows if not r["aliased"]], budgets, f"{name}-{base}-primary", arms
            )
            part["matched_aliased"] = comparisons(
                [r for r in rows if r["aliased"]], budgets, f"{name}-{base}-aliased", arms
            )
        else:
            part["matched"] = comparisons(rows, budgets, f"{name}-{base}", arms)
        out[name] = part
        files[f"{name}_{base}_rows.json"] = _dump_rows(rows)
        _log(log, f"{role} {name} {base}", records, budgets, arms)
    return out, files, every


def benchmark_set(
    log: list[str],
    base: int,
    per: int,
    budgets: tuple[int, ...],
    jobs: int,
    role: str,
    mode: str = "boundary",
    arms: tuple[str, ...] = ev.ARM_IDS,
    kinds: tuple[str, ...] = (),
) -> tuple[dict[str, Any], dict[str, str], list[ev.RunRecord]]:
    scenario = ring_scenario(per, base_seed=base)
    tasks = [
        (base, per, i, budgets)
        for i, w in enumerate(scenario.worlds)
        if not kinds or w.kind in kinds
    ]
    records = _map(_benchmark_task, tasks, jobs, mode, arms)
    _log(log, f"{role} benchmark {base}", records, budgets, arms)
    rows = ev.records_as_json(records)
    out = {
        "role": role,
        "base_seed": base,
        "seeds_per_kind": per,
        "worlds": len(tasks),
        "specs_digest": stable_digest(scenario.worlds),
        "by_budget": ev.summarize(records, budgets, arms),
        "per_kind": {
            kind: ev.summarize([r for r in records if r.kind == kind], budgets, arms)
            for kind in sorted({r.kind for r in records})
        },
        "matched": comparisons(rows, budgets, f"benchmark-{base}", arms),
        "budget_never_exceeded": all(r.spent <= r.budget for r in records),
    }
    return out, {f"benchmark_{base}_rows.json": _dump_rows(rows)}, records


SHORT = {
    ev13.EXACT: "exact",
    ev13.INDISTINGUISHABLE: "indist",
    ev13.VALIDATED_NEW: "new",
    ev13.PROPOSAL_ONLY: "proposal",
    ev13.UNSUPPORTED_CLAIM: "unsupported",
    ev13.CORRECT_ABSTENTION: "abstain-ok",
    ev13.FALSE_NULL: "false-null",
    ev13.FORCE_FIT: "force-fit",
    ev13.WRONG_CLAIM: "wrong",
}


def _log(
    log: list[str], label: str, records: list[ev.RunRecord], budgets: Any, arms: Sequence[str]
) -> None:
    for budget in budgets:
        for arm in arms:
            mine = [r for r in records if r.budget == budget and r.arm == arm]
            for part, sub in ev.parts(mine).items():
                if not sub:
                    continue
                t = ev.table(sub)
                cats = " ".join(f"{SHORT[c]} {t['outcomes'][c]}" for c in ev.CATEGORIES)
                cost = t["realized_cost"]
                log.append(
                    f"{label} {part} b{budget} {arm} n={t['n']}: {cats} | supported "
                    f"{t['supported']} (v1.3 rule {t['v13_rule_supported']}) errors {t['errors']} "
                    "| "
                    f"own correct {t['own_correct']} own error {t['own_error']} | cost mean "
                    f"{cost.get('mean')} median {cost.get('median')} p90 {cost.get('p90')} at-cap "
                    f"{cost.get('at_cap')}"
                )
    for r in records:
        if r.category in (ev13.FORCE_FIT, ev13.WRONG_CLAIM):
            log.append(
                f"  {r.arm} {r.category} {r.setting} {r.world_id}"
                f"{' (aliased)' if r.aliased else ''}"
                f" b{r.budget}: {r.answer} {list(r.claim)} ({r.outcome})"
            )


def _matched_log(log: list[str], label: str, matched: Mapping[str, Any]) -> None:
    for key, block in matched.items():
        if not isinstance(block, Mapping):
            continue
        for p in block["per_world"]:
            d = p["differences"]
            log.append(
                f"{label} {key} @cap{p['anchor_cap']}: matched {p['matched']}/{p['worlds']} "
                f"(unmatched: {p['y']} dearer {p['unmatched_y_dearer']}, {p['x']} dearer "
                f"{p['unmatched_x_dearer']}); cost point median "
                f"{p['matched_cost_point'].get('median')}; credited {d['credited']['mean']:+.3f} "
                f"{d['credited']['ci95']} errors(c5) {d['errors_c5']['mean']:+.3f} "
                f"{d['errors_c5']['ci95']} SUPPORTED errors {d['supported_errors']['mean']:+.3f} "
                f"{d['supported_errors']['ci95']} own-correct {d['own_correct']['mean']:+.3f} "
                f"{d['own_correct']['ci95']} own-error {d['own_error']['mean']:+.3f} "
                f"{d['own_error']['ci95']}"
            )


# -- round-4 data: what the mean-cost match hid -------------------------------------------------


def reanalyse_v13(log: list[str]) -> dict[str, Any]:
    """v1.3's frozen row files, re-read: v1.3's mean-cost basis beside the per-world method."""
    out: dict[str, Any] = {
        "source": _rel(FROZEN_V13),
        "rows_sha256": {},
        "tolerance": PLAN.per_world_tolerance,
        "resamples": PLAN.bootstrap_resamples,
    }
    files = (
        ("held_out_primary", "held_out_3218044000_rows.json", False),
        ("control", "control_3218044000_rows.json", None),
        ("benchmark", "benchmark_3729592000_rows.json", None),
    )
    for name, filename, aliased in files:
        path = FROZEN_V13 / filename
        out["rows_sha256"][filename] = _sha256(path)
        rows = _load(path)
        if aliased is not None:
            rows = [r for r in rows if r["aliased"] is aliased]
        caps = sorted({int(c) for r in rows for c in r["arms"]["B4"]})
        block: dict[str, Any] = {}
        for y, x in (("B6", "B4"), ("B5", "B4")):
            contrast = [
                costmatch.cost_contrast(
                    rows,
                    y,
                    x,
                    cap,
                    tolerance=PLAN.per_world_tolerance,
                    resamples=PLAN.bootstrap_resamples,
                    label=f"v13-{name}",
                )
                for cap in caps
            ]
            per_world = [
                costmatch.per_world_matched(
                    rows,
                    y,
                    x,
                    cap,
                    tolerance=PLAN.per_world_tolerance,
                    resamples=PLAN.bootstrap_resamples,
                    label=f"v13-{name}",
                )
                for cap in caps
            ]
            block[f"{y}-{x}"] = {"mean_cost_contrast": contrast, "per_world": per_world}
            for c, p in zip(contrast, per_world, strict=True):
                d = p["differences"]
                log.append(
                    f"{name} {y}-{x} cap {c['cap']}: mean cost {c['mean_cost'][y]} vs "
                    f"{c['mean_cost'][x]}, difference {c['mean_cost_difference']['mean']:+.3f} "
                    f"{c['mean_cost_difference']['ci95']} -> v1.3 basis "
                    f"{c['v13_basis_would_say']}; "
                    f"per-world cost difference min {c['per_world_cost_difference']['min']} p10 "
                    f"{c['per_world_cost_difference']['p10']} p90 "
                    f"{c['per_world_cost_difference']['p90']} max "
                    f"{c['per_world_cost_difference']['max']}; worlds beyond +-"
                    f"{PLAN.per_world_tolerance}: {c['worlds_beyond_tolerance']}/{c['worlds']}; "
                    f"at cap {y} {c['cost'][y]['at_cap']} {x} {c['cost'][x]['at_cap']}; "
                    "own-correct "
                    f"difference by stratum "
                    + ", ".join(
                        f"{k}: {v['worlds']} worlds {v['own_correct_difference']}"
                        for k, v in c["outcome_by_cost_stratum"].items()
                    )
                )
                log.append(
                    f"    per-world: matched {p['matched']}/{p['worlds']} (unmatched {y} dearer "
                    f"{p['unmatched_y_dearer']}, {x} dearer {p['unmatched_x_dearer']}); "
                    "own-correct "
                    f"{d['own_correct']['mean']:+.3f} {d['own_correct']['ci95']}; credited "
                    f"{d['credited']['mean']:+.3f} {d['credited']['ci95']}; own-error "
                    f"{d['own_error']['mean']:+.3f} {d['own_error']['ci95']}"
                )
        out[name] = block
    return out


# -- hidden worlds: blind run, reveal, score ----------------------------------------------------


def _hidden_task(args: tuple[str, str, tuple[int, ...]]) -> list[ev.RunRecord]:
    sealed_path, case_id, budgets = args
    catalog = ring_catalog()
    worlds = hw.parse_hidden_worlds(_load(Path(sealed_path)), catalog, DISCOVERY, sealed=True)
    world = next(w for w in worlds.worlds if w.case_id == case_id)
    return _evaluator().run(hidden_case(world, catalog, case_id), budgets)


def run_hidden(
    log: list[str],
    package_data: Any,
    sealed_path: Path,
    budgets: tuple[int, ...],
    jobs: int,
    mode: str = "boundary",
    arms: tuple[str, ...] = ev.ARM_IDS,
) -> tuple[dict[str, Any], dict[str, str]]:
    """The protocol's T5-T7 for arms B4, B6, B7: blind runs from the engine package; then the reveal
    is verified against the commitments; then candidate.5 scoring and per-world comparisons."""
    catalog = ring_catalog()
    package = hw.parse_engine_package(package_data, catalog)
    if (package.interface.catalog_ref, package.interface.catalog_digest) != (
        catalog.ref,
        catalog.digest,
    ):
        raise SystemExit("the package was written against another catalog")
    tasks = [(str(sealed_path), c.case_id, budgets) for c in package.cases]
    records = _map(_hidden_task, tasks, jobs, mode, arms)
    revealed = hw.reveal(_load(sealed_path), package, catalog, DISCOVERY)
    revealed_ids = {str(w.case_id) for w in revealed.worlds}
    if {r.world_id for r in records} != revealed_ids:
        raise SystemExit("a committed case has no output")
    rows = ev.records_as_json(records)
    primary = [r for r in rows if not r["aliased"]]
    result = {
        "package_root": package.root,
        "suite": package.suite,
        "example_only": package.example_only,
        "cases": len(package.cases),
        "per_category": {
            c: sum(1 for w in revealed.worlds if w.category == c) for c in hw.CATEGORIES
        },
        "by_budget": ev.summarize(records, budgets, arms),
        "per_category_by_budget": {
            c: ev.summarize([r for r in records if r.kind == c], budgets, arms)
            for c in sorted({r.kind for r in records})
        },
        "matched_primary": comparisons(primary, budgets, f"hidden-{package.root[:16]}", arms),
        "budget_never_exceeded": all(r.spent <= r.budget for r in records),
        "reveal_verified": True,
    }
    _log(log, "hidden", records, budgets, arms)
    _matched_log(log, "hidden primary", result["matched_primary"])
    return result, {"hidden_rows.json": _dump_rows(rows)}


def _example_salt(world_id: str) -> str:
    """Reproducible salts for the EXAMPLE file only (a real hidden set is sealed by its author
    with fresh salts)."""
    return hashlib.sha256(f"lab-brain/v1.4/example-salt/{world_id}".encode()).hexdigest()


def hidden_example(log: list[str], out: Path, jobs: int, check_only: bool) -> int:
    """The scaffold demonstration on `example.hidden-worlds.json` (an example, not a hidden set)."""
    catalog = ring_catalog()
    data = hw.load_document(EXAMPLE, repo=ROOT, allow_example=True)
    worlds = hw.parse_hidden_worlds(data, catalog, DISCOVERY)
    sealed, package = hw.seal(worlds, salts=_example_salt)
    target = out / "hidden_example"
    target.mkdir(parents=True, exist_ok=True)
    sealed_path = target / "example.sealed.json"
    files = {"example.sealed.json": _dump(sealed), "example.engine-package.json": _dump(package)}
    if not check_only:
        sealed_path.write_text(files["example.sealed.json"], encoding="utf-8")
    elif sealed_path.read_text(encoding="utf-8") != files["example.sealed.json"]:
        print("STALE: hidden_example/example.sealed.json differs")
        return 1
    result, rows = run_hidden(log, package, sealed_path, PLAN.budgets, jobs)
    files["results.json"] = _dump(result)
    files.update(rows)
    stale = []
    for name, text in files.items():
        path = target / name
        if check_only:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(name)
        else:
            path.write_text(text, encoding="utf-8")
    if check_only:
        print("STALE: " + "; ".join(stale) if stale else "hidden example evidence is current")
        return 1 if stale else 0
    (target / "run.log").write_text("\n".join(log) + "\n", encoding="utf-8")
    return 0


# -- building the held-out evidence ---------------------------------------------------------------


def build(log: list[str], freeze: dict[str, Any], jobs: int) -> dict[str, str]:
    started = time.monotonic()
    scenario = ring_scenario(1, base_seed=1)
    tooling = frozen_inputs(scenario)
    seeds = freeze["held_out_seed_rule"]["seeds"]
    files: dict[str, str] = {}
    results: dict[str, Any] = {}
    base = int(seeds["held-out-worlds"]["base_seed"])
    results["held_out_worlds"], extra, _ = held_out_set(
        log, base, PLAN.held_out_per_class, PLAN.budgets, jobs, "HELD_OUT_FOR_V1_4"
    )
    files.update(extra)
    _matched_log(log, "held_out primary", results["held_out_worlds"]["held_out"]["matched_primary"])
    _matched_log(log, "control", results["held_out_worlds"]["control"]["matched"])
    bench = int(seeds["benchmark-worlds"]["base_seed"])
    results["benchmark"], extra, _ = benchmark_set(
        log, bench, PLAN.benchmark_per_kind, PLAN.budgets, jobs, "HELD_OUT_FOR_V1_4"
    )
    _matched_log(log, "benchmark", results["benchmark"]["matched"])
    files.update(extra)
    inputs = {
        "catalog": {"ref": scenario.catalog.ref, "digest": scenario.catalog.digest},
        "engine_protocol_digest": DISCOVERY.digest,
        "v11_safety_protocol_digest": SAFETY_V11.digest,
        "v13_safety_protocol_digest": SAFETY_V13.digest,
        "v13_evaluator_rule_digest": EVALUATOR_RULE.digest,
        "safety_protocol": to_jsonable(SAFETY_V14),
        "safety_protocol_digest": SAFETY_V14.digest,
        "evaluator_rule": to_jsonable(EVALUATOR_RULE_V14),
        "evaluator_rule_digest": EVALUATOR_RULE_V14.digest,
        "plan": to_jsonable(PLAN),
        "plan_digest": PLAN.digest,
        "grammar_digest": GRAMMAR.digest,
        "boundary": "every arm in a separate process (scripts/discovery_safety_v14_eval.py "
        "--arm-worker); JSON messages only",
    }
    body: dict[str, Any] = {
        "kind": "lab-brain/discovery-safety-v1.4-evaluation-manifest@1",
        "frozen_inputs": tooling,
        "design_freeze": freeze,
        "v14_sources_sha256": v14_sources(),
        "inputs": inputs,
        "inputs_digest": stable_digest(inputs),
        "evidence_files": sorted([*files, "results.json"]),
        "evidence_class": "ENGINEERING EVIDENCE ONLY -- developer-authored synthetic worlds",
        "not_claimed": [
            "scientific validity of any mechanism, forward model, grammar term or new mechanism",
            "an independent or blind evaluation: worlds, held-out families, the grammar, the "
            "engine, every safety gate and the evaluator's rule share an author lineage",
            "that v1.3 or v1.4 replaces v1.1: v1.1 remains the offline safety baseline",
            "anything about a real device, real literature, a language model or the real "
            "PostgreSQL LIB workflow; Discovery is not connected to real research execution",
            "scientific acceptance (NOT PASSED) or G-D (NOT PASSED)",
        ],
    }
    results_text = _dump(results)
    body["results_sha256"] = hashlib.sha256(results_text.encode("utf-8")).hexdigest()
    body["rows_sha256"] = {
        name: hashlib.sha256(text.encode("utf-8")).hexdigest()
        for name, text in sorted(files.items())
    }
    body["manifest_sha256"] = stable_digest(body)
    manifest = {**body, "code_commit": _commit(), "environment": environment()}
    log.append(f"elapsed {time.monotonic() - started:.1f}s")
    return {"manifest.json": _dump(manifest), "results.json": results_text, **files}


UNHASHED = ("code_commit", "environment")


def check(out: Path, files: dict[str, str], record: bool) -> int:
    stale = []
    for name, content in files.items():
        path = out / name
        if not path.exists():
            stale.append(f"{name}: missing")
            continue
        on_disk = path.read_text(encoding="utf-8")
        if name == "manifest.json":
            old, new = json.loads(on_disk), json.loads(content)
            for key in UNHASHED:
                old.pop(key, None)
                new.pop(key, None)
            if old != new:
                stale.append(f"{name}: hashed body differs")
        elif on_disk != content:
            stale.append(f"{name}: differs")
    recorded = (
        _load(out / "manifest.json")["environment"]["interpreter_key"]
        if (out / "manifest.json").exists()
        else None
    )
    verified_path = out / INTERPRETERS_FILE
    verified = _load(verified_path)["reproduced_under"] if verified_path.exists() else []
    known = {recorded, *(v["interpreter_key"] for v in verified)}
    current = interpreter_key()
    if stale:
        print("STALE: " + "; ".join(stale))
        return 1
    if record:
        if current not in known:
            verified.append({**environment(), "result": "every evidence file reproduced exactly"})
            verified_path.write_text(_dump({"reproduced_under": verified}), encoding="utf-8")
            print(f"recorded: {current} reproduces the evidence exactly")
        return 0
    if current not in known:
        print(
            f"INTERPRETER MISMATCH: written under {recorded}, reproduced under "
            f"{sorted(k for k in known if k)}; this is {current}. Every file matched, but this "
            "interpreter is not recorded as verified (re-run with --record-interpreter)."
        )
        return 2
    print("evidence is current")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--record-interpreter", action="store_true")
    parser.add_argument("--design-freeze")
    parser.add_argument("--reanalyse-v13", action="store_true")
    parser.add_argument("--dev", nargs=2, type=int, metavar=("BASE", "PER"))
    parser.add_argument("--budgets", default="")
    parser.add_argument("--settings", default=",".join(SETTINGS))
    parser.add_argument("--arms", default=",".join(ev.ARM_IDS))
    parser.add_argument("--kinds", default="")
    parser.add_argument("--worlds", default="", help="development only: world ids to run")
    parser.add_argument("--in-process", action="store_true")
    parser.add_argument("--dev-out", type=Path, help="development only: also write JSON here")
    parser.add_argument("--hidden-package", type=Path)
    parser.add_argument("--hidden-sealed", type=Path)
    parser.add_argument("--hidden-example", action="store_true")
    parser.add_argument("--arm-worker", action="store_true")
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args(argv)
    if args.arm_worker:
        return worker_loop(_handle)
    log: list[str] = []
    budgets = tuple(int(b) for b in args.budgets.split(",")) if args.budgets else PLAN.budgets
    arms = tuple(a for a in args.arms.split(",") if a)
    mode = "in-process" if args.in_process else "boundary"
    if args.reanalyse_v13:
        result = reanalyse_v13(log)
        text = _dump(result)
        target = args.out / REANALYSIS_FILE
        print("\n".join(log))
        if args.check:
            current = target.exists() and target.read_text(encoding="utf-8") == text
            print("reanalysis is current" if current else f"STALE: {REANALYSIS_FILE}")
            return 0 if current else 1
        args.out.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        (args.out / "v13_reanalysis.log").write_text("\n".join(log) + "\n", encoding="utf-8")
        return 0
    if args.hidden_example:
        rc = hidden_example(log, args.out, args.jobs, args.check)
        print("\n".join(log))
        return rc
    if args.hidden_package or args.hidden_sealed:
        if not (args.hidden_package and args.hidden_sealed):
            parser.error("a hidden run needs --hidden-package and --hidden-sealed")
        package = hw.load_document(args.hidden_package, repo=ROOT, allow_example=False)
        hw.load_document(args.hidden_sealed, repo=ROOT, allow_example=False)
        result, rows = run_hidden(log, package, args.hidden_sealed, budgets, args.jobs, mode, arms)
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "hidden_results.json").write_text(_dump(result), encoding="utf-8")
        for name, text in rows.items():
            (args.out / name).write_text(text, encoding="utf-8")
        (args.out / "hidden_run.log").write_text("\n".join(log) + "\n", encoding="utf-8")
        print("\n".join(log))
        return 0
    if args.dev:
        base, per = args.dev
        if base not in {r.base_seed for r in PLAN.development}:
            parser.error("--dev runs declared development seeds only")
        settings = tuple(s for s in args.settings.split(",") if s)
        result: dict[str, Any] = {}
        rows: dict[str, str] = {}
        if "benchmark" in settings and base in (1, 3_729_592_000):
            kinds = tuple(k for k in args.kinds.split(",") if k)
            result, rows, _ = benchmark_set(
                log, base, per, budgets, args.jobs, "DEVELOPMENT", mode, arms, kinds
            )
            _matched_log(log, "benchmark", result["matched"])
        elif base not in (1, 3_729_592_000):
            result, rows, _ = held_out_set(
                log, base, per, budgets, args.jobs, "DEVELOPMENT", settings, mode, arms
            )
            if "held_out" in result:
                _matched_log(log, "held_out primary", result["held_out"]["matched_primary"])
            if "control" in result:
                _matched_log(log, "control", result["control"]["matched"])
        if args.dev_out:
            args.dev_out.mkdir(parents=True, exist_ok=True)
            (args.dev_out / f"dev_{base}_{per}.json").write_text(_dump(result), encoding="utf-8")
            for name, text in rows.items():
                (args.dev_out / f"dev_{name}").write_text(text, encoding="utf-8")
        print("\n".join(log))
        return 0
    if args.check:
        manifest_path = args.out / "manifest.json"
        if not manifest_path.exists():
            print("STALE: manifest.json: missing")
            return 1
        commit = _load(manifest_path)["design_freeze"]["commit"]
    else:
        if not args.design_freeze:
            parser.error("writing the evidence needs --design-freeze SHA")
        commit = args.design_freeze
        if (args.out / "manifest.json").exists():
            raise SystemExit(
                "held-out evidence already exists: the held-out evaluation runs exactly once "
                "(use --check to reproduce it)"
            )
    files = build(log, design_freeze(commit), args.jobs)
    for line in log:
        print(line)
    if args.check:
        return check(args.out, files, args.record_interpreter)
    args.out.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (args.out / name).write_text(content, encoding="utf-8")
    (args.out / "run.log").write_text("\n".join(log) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
