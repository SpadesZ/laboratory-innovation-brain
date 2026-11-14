"""Evaluate safety v1.3 (B6) beside v1.2 (B5), the v1.1 baseline (B4) and the frozen engine (B2).

    python scripts/discovery_safety_v13_eval.py --dev BASE PER [--budgets 8,12] [--settings ...]
    python scripts/discovery_safety_v13_eval.py --diagnose-noise PER [--budgets 24,48]
    python scripts/discovery_safety_v13_eval.py --design-freeze SHA          # write the evidence
    python scripts/discovery_safety_v13_eval.py --check [--record-interpreter]
    python scripts/discovery_safety_v13_eval.py --arm-worker                 # (internal)

Offline and zero-cost: no model, simulator, network or database; Discovery is not connected to real
research execution. The engine, the 2026-11-02 evaluation tooling and the v1.0/v1.1/v1.2 safety
packages are used exactly as frozen (their source hashes are checked against their manifests).

    boundary        every arm runs in a separate process (`--arm-worker`, a fresh interpreter) that
                    receives only its catalog as the arm holds it, the available experiments, the
                    cap and laboratory replies; the world, its truth, the meter and the ledger stay
                    in the evaluator's process (`lab_brain.discovery_safety.v13.boundary`)
    design freeze   `--design-freeze SHA` refuses unless the v1.3 package and this script are
                    byte-identical to that commit and the protocol, rule and plan digests computed
                    there are today's
    held-out        NEW worlds on `PLAN.held_out` and `PLAN.benchmark_worlds` (derived from fixed
                    strings, generated only after the freeze; no overlap with any earlier range)
    development     `--dev BASE PER` runs declared development seeds only and writes nothing

SCORING. SAI 3.5 candidate.5 (spec commit 61af6ef): outcome with `UNSUPPORTED_CLAIM`, evidential
level re-derived by the evaluator's own rule, the arm's stance; face-value columns and v1.1's legacy
categories beside. Comparisons at matched realized cost with paired-bootstrap intervals.

WHAT THE NUMBERS ARE. ENGINEERING EVIDENCE ONLY on developer-authored synthetic worlds. Not
scientific validity, not an independent evaluation, nothing about a real device. Scientific
acceptance and G-D: NOT PASSED.

The composition root that names the silicon-photonics scenario and its grammar; `pyproject.toml`
exempts this single file from the §24.2 import ban.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import platform
import subprocess
import sys
import time
from collections.abc import Mapping
from importlib import metadata
from multiprocessing import Pool
from pathlib import Path
from typing import Any, ClassVar

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from lab_brain.discovery import benchmark  # noqa: E402
from lab_brain.discovery.distinguish import SeparationOracle  # noqa: E402
from lab_brain.discovery.metrics import Scorer  # noqa: E402
from lab_brain.discovery.model import (  # noqa: E402
    CLAIM_OUTCOMES,
    Budget,
    Outcome,
    make_hypothesis,
    stable_digest,
    to_jsonable,
)
from lab_brain.discovery.protocol import DISCOVERY  # noqa: E402
from lab_brain.discovery.worlds import SyntheticWorld  # noqa: E402
from lab_brain.discovery_eval import held_out  # noqa: E402
from lab_brain.discovery_eval.blind import CostMeter, blind_laboratory  # noqa: E402
from lab_brain.discovery_safety.model import SAFETY  # noqa: E402
from lab_brain.discovery_safety.v11.model import SAFETY_V11  # noqa: E402
from lab_brain.discovery_safety.v12 import evaluation as ev12  # noqa: E402
from lab_brain.discovery_safety.v12.gate import (  # noqa: E402
    _combined_separation,
    _GateV12,
    _zero,
    hypothesis_prediction,
    safe_investigate_v12,
)
from lab_brain.discovery_safety.v12.grammar import grammar_from_declaration  # noqa: E402
from lab_brain.discovery_safety.v12.ledger import PredictionLedger  # noqa: E402
from lab_brain.discovery_safety.v12.model import SAFETY_V12  # noqa: E402
from lab_brain.discovery_safety.v13 import evaluation as ev  # noqa: E402
from lab_brain.discovery_safety.v13.boundary import ArmProcess, worker_loop  # noqa: E402
from lab_brain.discovery_safety.v13.ledger import EvaluatorLaboratory  # noqa: E402
from lab_brain.discovery_safety.v13.model import (  # noqa: E402
    EVALUATOR_RULE,
    PLAN,
    SAFETY_V13,
    ArmAnswer,
)
from lab_brain.domains.silicon_photonics import discovery_grammar  # noqa: E402
from lab_brain.domains.silicon_photonics.discovery_catalog import (  # noqa: E402
    MOTIVATING_EXPERIMENT,
    ring_catalog,
    ring_scenario,
)

DEFAULT_OUT = ROOT / "docs" / "audit" / "discovery-safety-v1.3-2026-11-11" / "evidence"
AUDIT = ROOT / "docs" / "audit"
FROZEN_ENGINE = AUDIT / "discovery-loop-offline-2026-11-01" / "evidence"
FROZEN_EVAL = AUDIT / "discovery-independent-evaluation-2026-11-02" / "evidence"
FROZEN_V10 = AUDIT / "discovery-unknown-mechanism-safety-2026-11-04" / "evidence"
FROZEN_V11 = AUDIT / "discovery-safety-v1.1-2026-11-04" / "evidence"
FROZEN_V12 = AUDIT / "discovery-safety-v1.2-2026-11-08" / "evidence"
V13_PACKAGE = ROOT / "src" / "lab_brain" / "discovery_safety" / "v13"
INTERPRETERS_FILE = "interpreter_verification.json"
DEPENDENCIES = ("pydantic", "pydantic-core", "PyYAML", "cryptography")
GRAMMAR = grammar_from_declaration(discovery_grammar.declaration())
SETTINGS = ("held_out", "control", "benchmark")


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


def v13_sources() -> dict[str, str]:
    files = [*sorted(V13_PACKAGE.glob("*.py")), Path(__file__).resolve()]
    return {_rel(p): _sha256(p) for p in files}


def frozen_inputs(scenario: benchmark.Scenario) -> dict[str, Any]:
    engine = _load(FROZEN_ENGINE / "manifest.json")
    evaluation = _load(FROZEN_EVAL / "manifest.json")
    v10 = _load(FROZEN_V10 / "manifest.json")
    v11 = _load(FROZEN_V11 / "manifest.json")
    v12 = _load(FROZEN_V12 / "manifest.json")
    out = {
        "engine_sources_match_frozen_manifest": benchmark.source_hashes(scenario, ROOT)
        == engine["sources_sha256"],
        "evaluation_sources_match_frozen_manifest": {
            r: _sha256(ROOT / r) for r in evaluation["evaluation_sources_sha256"]
        }
        == evaluation["evaluation_sources_sha256"],
        "v10_sources_match_frozen_manifest": {
            r: _sha256(ROOT / r) for r in v10["safety_sources_sha256"]
        }
        == v10["safety_sources_sha256"],
        "v11_sources_match_frozen_manifest": {
            r: _sha256(ROOT / r) for r in v11["v11_sources_sha256"] if not r.startswith("scripts/")
        }
        == {k: v for k, v in v11["v11_sources_sha256"].items() if not k.startswith("scripts/")},
        "v12_sources_match_frozen_manifest": {
            r: _sha256(ROOT / r) for r in v12["v12_sources_sha256"]
        }
        == v12["v12_sources_sha256"],
        "v10_protocol_digest_matches": v10["inputs"]["safety_protocol_digest"] == SAFETY.digest,
        "v11_protocol_digest_matches": v11["inputs"]["safety_protocol_digest"] == SAFETY_V11.digest,
        "v12_protocol_digest_matches": v12["inputs"]["safety_protocol_digest"] == SAFETY_V12.digest,
        "v12_grammar_digest_matches": v12["inputs"]["grammar_digest"] == GRAMMAR.digest,
        "frozen_engine_manifest_sha256": engine["manifest_sha256"],
        "frozen_evaluation_manifest_sha256": evaluation["manifest_sha256"],
        "frozen_v10_manifest_sha256": v10["manifest_sha256"],
        "frozen_v11_manifest_sha256": v11["manifest_sha256"],
        "frozen_v12_manifest_sha256": v12["manifest_sha256"],
    }
    if not all(v for k, v in out.items() if k.endswith(("_manifest", "_matches"))):
        raise SystemExit(f"a frozen input drifted; refusing to continue: {out}")
    return out


def design_freeze(commit: str) -> dict[str, Any]:
    try:
        resolved = _git("rev-parse", "--verify", f"{commit}^{{commit}}").strip()
        listed = _git("ls-tree", "--name-only", resolved, _rel(V13_PACKAGE) + "/").split()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"cannot read the design-freeze commit {commit}: {exc}") from exc
    at_freeze = {}
    for relative in [*sorted(p for p in listed if p.endswith(".py")), _rel(Path(__file__))]:
        blob = subprocess.run(
            ["git", "show", f"{resolved}:{relative}"], cwd=ROOT, capture_output=True, check=True
        ).stdout
        at_freeze[relative] = hashlib.sha256(blob).hexdigest()
    if at_freeze != v13_sources():
        raise SystemExit(
            "the v1.3 sources differ from the design-freeze commit; the evaluation would not be of "
            "the frozen design"
        )
    return {
        "commit": resolved,
        "v13_sources_identical_to_freeze": True,
        "protocol_digest": SAFETY_V13.digest,
        "evaluator_rule_digest": EVALUATOR_RULE.digest,
        "plan_digest": PLAN.digest,
        "grammar_digest": GRAMMAR.digest,
        "held_out_seeds_generated_after_freeze": True,
    }


# -- the arm process --------------------------------------------------------------------------

_CATALOG: list[Any] = []
_ORACLES: dict[tuple[Any, ...], tuple[Any, SeparationOracle]] = {}


def _arm_catalog(request: Mapping[str, Any]) -> tuple[Any, SeparationOracle]:
    """The catalog and oracle the arm holds at case start (no world, no truth)."""
    if not _CATALOG:
        _CATALOG.append(ring_catalog())
    catalog = _CATALOG[0]
    family = str(request.get("family") or "")
    available = tuple(request["available"])
    removed = tuple((str(a), str(b)) for a, b in request.get("removed", ()))
    key = (family, available, removed)
    if key not in _ORACLES:
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


_PROCESS: list[ArmProcess] = []


def _execute_in_process(request: Mapping[str, Any], lab: EvaluatorLaboratory) -> ArmAnswer:
    return _handle(request, lab)


def _execute_boundary(request: Mapping[str, Any], lab: EvaluatorLaboratory) -> ArmAnswer:
    if not _PROCESS:
        _PROCESS.append(ArmProcess([sys.executable, str(Path(__file__).resolve()), "--arm-worker"]))
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
            return ev.own_category_v11(scorer, world.spec, outcome, fingerprints, full)

    return ev.WorldCase(
        setting="held_out" if removed else "control",
        world=world.spec,
        kind=f"held_out:{world.family}",
        aliased=world.aliased and removed,
        lab_factory=lambda: held_out_lab(world, catalog),
        engine_catalog=engine_catalog,
        engine_oracle=engine_oracle,
        full_catalog=catalog,
        full_oracle=full,
        truth=truth,
        request={"family": world.family if removed else "", "available": list(all_ids)},
        own=own,
    )


def held_out_lab(world: held_out.HeldOutWorld, catalog: Any) -> Any:
    return SyntheticWorld(world.spec, catalog, MOTIVATING_EXPERIMENT)


def benchmark_case(scenario: benchmark.Scenario, world: Any, oracles: Any) -> ev.WorldCase:
    oracle = oracles.for_world(world)
    scorer = Scorer(scenario.catalog)

    def own(outcome: str, claim: tuple[str, ...], fingerprints: frozenset[str]) -> str:
        return ev.own_category_v11(scorer, world, outcome, fingerprints, oracle)

    return ev.WorldCase(
        setting="benchmark",
        world=world,
        kind=world.kind,
        aliased=False,
        lab_factory=lambda: benchmark.lab_for(scenario, world),
        engine_catalog=scenario.catalog,
        engine_oracle=oracle,
        full_catalog=scenario.catalog,
        full_oracle=oracle,
        truth=world.truth_hypothesis(scenario.catalog),
        request={
            "family": "",
            "available": [e.experiment_id for e in oracle.available],
            "removed": [list(r) for r in world.removed],
        },
        own=own,
    )


_MODE: list[str] = ["boundary"]
_ARMS: list[tuple[str, ...]] = [ev.ARM_IDS]


def _evaluator() -> ev.Evaluator:
    execute = _execute_boundary if _MODE[0] == "boundary" else _execute_in_process
    return ev.Evaluator(execute, GRAMMAR, EVALUATOR_RULE, _ARMS[0])


def _init(mode: str, arms: tuple[str, ...]) -> None:
    _MODE[0] = mode
    _ARMS[0] = arms


def _held_out_task(args: tuple[int, int, int, bool, tuple[int, ...]]) -> list[ev.RunRecord]:
    base, per, index, removed, budgets = args
    worlds = held_out.held_out_worlds(
        ring_catalog(), seeds_per_class=per, base_seed=base, protocol=DISCOVERY
    )
    return _evaluator().run(held_out_case(worlds[index], removed), budgets)


def _benchmark_task(args: tuple[int, int, int, tuple[int, ...], str]) -> list[ev.RunRecord]:
    base, per, index, budgets, _kinds = args
    scenario = ring_scenario(per, base_seed=base)
    oracles = benchmark.Oracles(scenario.catalog, DISCOVERY)
    return _evaluator().run(benchmark_case(scenario, scenario.worlds[index], oracles), budgets)


def _map(fn: Any, tasks: list[Any], jobs: int, mode: str, arms: tuple[str, ...]) -> list[Any]:
    if jobs <= 1:
        _init(mode, arms)
        return [r for t in tasks for r in fn(t)]
    with Pool(jobs, initializer=_init, initargs=(mode, arms)) as pool:
        return [r for rs in pool.map(fn, tasks, chunksize=1) for r in rs]


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
        part = "primary" if removed else "all"
        out[name] = {
            "setting": "true family REMOVED from the engine's catalog"
            if removed
            else "the same worlds with the family LEFT IN the catalog",
            "by_budget": ev.summarize(records, budgets),
            "matched": ev.matched_comparisons(
                [r for r in records if not r.aliased], PLAN, f"{name}-{base}-{part}"
            ),
            "budget_never_exceeded": all(r.spent <= r.budget for r in records),
        }
        files[f"{name}_{base}_rows.json"] = _dump_rows(ev.records_as_json(records))
        _log(log, f"{role} {name} {base}", records, budgets, part)
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
        (base, per, i, budgets, "")
        for i, w in enumerate(scenario.worlds)
        if not kinds or w.kind in kinds
    ]
    records = _map(_benchmark_task, tasks, jobs, mode, arms)
    _log(log, f"{role} benchmark {base}", records, budgets, "all")
    out = {
        "role": role,
        "base_seed": base,
        "seeds_per_kind": per,
        "worlds": len(tasks),
        "specs_digest": stable_digest(scenario.worlds),
        "by_budget": ev.summarize(records, budgets),
        "per_kind": {
            kind: ev.summarize([r for r in records if r.kind == kind], budgets)
            for kind in sorted({r.kind for r in records})
        },
        "matched": ev.matched_comparisons(records, PLAN, f"benchmark-{base}"),
        "budget_never_exceeded": all(r.spent <= r.budget for r in records),
    }
    return out, {f"benchmark_{base}_rows.json": _dump_rows(ev.records_as_json(records))}, records


def _log(log: list[str], label: str, records: list[ev.RunRecord], budgets: Any, part: str) -> None:
    short = {
        ev.EXACT: "exact",
        ev.INDISTINGUISHABLE: "indist",
        ev.VALIDATED_NEW: "new",
        ev.PROPOSAL_ONLY: "proposal",
        ev.UNSUPPORTED_CLAIM: "unsupported",
        ev.CORRECT_ABSTENTION: "abstain-ok",
        ev.FALSE_NULL: "false-null",
        ev.FORCE_FIT: "force-fit",
        ev.WRONG_CLAIM: "wrong",
    }
    for budget in budgets:
        for arm in ev.ARM_IDS:
            mine = [r for r in records if r.budget == budget and r.arm == arm]
            if not mine:
                continue
            t = ev.parts(mine).get(part, mine)
            tab = ev.table(t)
            cats = " ".join(f"{short[c]} {tab['outcomes'][c]['k']}" for c in ev.CATEGORIES)
            log.append(
                f"{label} b{budget} {arm} n={tab['n']}: {cats} | asserted {tab['asserted']} "
                f"supported {tab['supported']} errors {tab['errors']} | own correct "
                f"{tab['own_correct']} own error {tab['own_error']} | v1.1-native correct "
                f"{tab['own_category']['CORRECT_IDENTIFICATION']} force-fit "
                f"{tab['own_category']['FORCE_FIT']} | cost {tab['realized_cost'].get('mean')}"
            )
    for r in records:
        if (
            r.arm == "B6"
            and r.category in (ev.FORCE_FIT, ev.WRONG_CLAIM)
            and (part != "primary" or not r.aliased)
        ):
            log.append(
                f"  B6 {r.category} {r.setting} {r.world_id} b{r.budget}: {r.answer} "
                f"{list(r.claim)} ({r.outcome})"
            )


def _matched_log(log: list[str], label: str, matched: dict[str, Any]) -> None:
    for p in matched["pairs"]:
        d = p["differences"]
        log.append(
            f"{label} {p['y']}@{p['cap_y']} - {p['x']}@{p['cap_x']} ({p['basis']}, cost "
            f"{p['mean_cost_y']} vs {p['mean_cost_x']}): credited {d['credited']['mean']:+.3f} "
            f"{d['credited']['ci95']} errors(c5) {d['errors_c5']['mean']:+.3f} "
            f"{d['errors_c5']['ci95']} own-correct {d['own_correct']['mean']:+.3f} "
            f"{d['own_correct']['ci95']} own-error {d['own_error']['mean']:+.3f} "
            f"{d['own_error']['ci95']}"
        )


# -- the noise-only diagnosis of v1.2 (development seeds) -------------------------------------


class _DiagnosticGate(_GateV12):
    """v1.2's gate, unchanged, recording at its decision what blocked a claim (read-only)."""

    captured: ClassVar[dict[str, Any]] = {}

    def assess_v12(self) -> Any:
        run = super().assess_v12()
        admitted = self.admitted()
        rivals = []
        for _chi2, hid, h in self.open_rivals() if self.members else []:
            best_fit = 0.0
            best_lower = 0.0
            for e in self.available:
                p = hypothesis_prediction(h, admitted, self.experiments, e)
                best_fit = max(best_fit, _combined_separation(p, _zero(e), e))
                lower = {
                    x.entry_id: sum(
                        c.coefficient(e.experiment_id, x.entry_id) * c.lower for c in h.components
                    )
                    for x in e.entries
                }
                best_lower = max(
                    best_lower,
                    sum((lower[x.entry_id] / x.sigma) ** 2 for x in e.entries) ** 0.5,
                )
            rivals.append((hid, round(best_fit, 2), round(best_lower, 2)))
        _DiagnosticGate.captured = {
            "members": [h.hypothesis_id for h in self.members],
            "support": [ok for _, ok in run.support],
            "rivals": rivals,
            "remaining": self.remaining(),
            "catalog_incomplete": run.assessment.catalog_incomplete,
        }
        return run


def diagnose_noise(log: list[str], per: int, budgets: tuple[int, ...]) -> None:
    """Why v1.2 loses noise-only worlds: development benchmark worlds (base 1) only."""
    import lab_brain.discovery_safety.v12.gate as gate_module

    scenario = ring_scenario(per, base_seed=1)
    oracles = benchmark.Oracles(scenario.catalog, DISCOVERY)
    experiments = ev12._all_experiments(scenario.catalog)
    original = gate_module._GateV12
    gate_module._GateV12 = _DiagnosticGate  # type: ignore[misc]
    buckets: collections.Counter[tuple[int, str]] = collections.Counter()
    try:
        for budget in budgets:
            for w in scenario.worlds:
                if w.kind != "noise_only_null":
                    continue
                oracle = oracles.for_world(w)
                lab = ev12.LedgerLaboratory(
                    blind_laboratory(
                        benchmark.lab_for(scenario, w),
                        experiments=experiments,
                        available=tuple(e.experiment_id for e in oracle.available),
                        meter=CostMeter({k: e.cost for k, e in experiments.items()}, budget),
                    ),
                    PredictionLedger(),
                )
                run = safe_investigate_v12(
                    arm="B5",
                    catalog=scenario.catalog,
                    oracle=oracle,
                    protocol=DISCOVERY,
                    budget=Budget(budget),
                    lab=lab,
                    grammar=GRAMMAR,
                )
                cap = _DiagnosticGate.captured
                null = cap["members"] == ["hyp:null"]
                rivals_close = [r for r in cap["rivals"] if r[0] != "hyp:null"]
                if run.result.claim:
                    bucket = "endorsed"
                elif not cap["members"]:
                    bucket = "no claim to assess"
                elif null and rivals_close and not any(cap["support"]):
                    bucket = "null claim: open rivals AND no risky registered pass"
                elif null and rivals_close:
                    bucket = "null claim: open rivals"
                elif null:
                    bucket = "null claim: no risky registered pass"
                elif cap["catalog_incomplete"]:
                    bucket = "non-null claim (glitch-driven, small ladder cap): catalog incomplete"
                elif any(r[0] == "hyp:null" for r in cap["rivals"]):
                    bucket = "non-null claim: 'no effect' is an open rival"
                else:
                    bucket = f"non-null claim: {run.assessment.reason}"
                buckets[(budget, bucket)] += 1
                below = [r for r in rivals_close if r[2] < SAFETY_V12.tau_risky]
                log.append(
                    f"b{budget} {w.world_id}: engine {list(run.engine.claim)} at ladder cap "
                    f"{run.allocation.engine_cap} -> {run.result.outcome.value} "
                    f"({run.assessment.reason}); {bucket}; units left {cap['remaining']}; open "
                    f"rivals (single-run separation from zero at fit / at the declared smallest "
                    f"amplitude): {rivals_close[:4]}; below tau_risky=3 at the smallest "
                    f"amplitude: {len(below)}/{len(rivals_close)}"
                )
    finally:
        gate_module._GateV12 = original  # type: ignore[misc]
    for (budget, bucket), n in sorted(buckets.items()):
        log.append(f"SUMMARY b{budget}: {bucket}: {n}")


# -- building the evidence --------------------------------------------------------------------


def build(log: list[str], freeze: dict[str, Any], jobs: int) -> dict[str, str]:
    started = time.monotonic()
    scenario = ring_scenario(1, base_seed=1)
    tooling = frozen_inputs(scenario)
    files: dict[str, str] = {}
    results: dict[str, Any] = {}
    for seeds in PLAN.held_out:
        results[f"held_out_{seeds.base_seed}"], extra, _ = held_out_set(
            log, seeds.base_seed, seeds.per_group, PLAN.budgets, jobs, seeds.role
        )
        files.update(extra)
        for name in ("held_out", "control"):
            _matched_log(log, name, results[f"held_out_{seeds.base_seed}"][name]["matched"])
    b = PLAN.benchmark_worlds
    results["benchmark"], extra, _ = benchmark_set(
        log, b.base_seed, b.per_group, PLAN.budgets, jobs, b.role
    )
    _matched_log(log, "benchmark", results["benchmark"]["matched"])
    files.update(extra)
    inputs = {
        "catalog": {"ref": scenario.catalog.ref, "digest": scenario.catalog.digest},
        "engine_protocol_digest": DISCOVERY.digest,
        "v10_safety_protocol_digest": SAFETY.digest,
        "v11_safety_protocol_digest": SAFETY_V11.digest,
        "v12_safety_protocol_digest": SAFETY_V12.digest,
        "safety_protocol": to_jsonable(SAFETY_V13),
        "safety_protocol_digest": SAFETY_V13.digest,
        "evaluator_rule": to_jsonable(EVALUATOR_RULE),
        "evaluator_rule_digest": EVALUATOR_RULE.digest,
        "plan": to_jsonable(PLAN),
        "plan_digest": PLAN.digest,
        "grammar_digest": GRAMMAR.digest,
        "boundary": "every arm in a separate process (scripts/discovery_safety_v13_eval.py "
        "--arm-worker); JSON messages only",
    }
    body: dict[str, Any] = {
        "kind": "lab-brain/discovery-safety-v1.3-evaluation-manifest@1",
        "frozen_inputs": tooling,
        "design_freeze": freeze,
        "v13_sources_sha256": v13_sources(),
        "inputs": inputs,
        "inputs_digest": stable_digest(inputs),
        "evidence_files": sorted([*files, "results.json"]),
        "evidence_class": "ENGINEERING EVIDENCE ONLY -- developer-authored synthetic worlds",
        "not_claimed": [
            "scientific validity of any mechanism, forward model, grammar term or new mechanism",
            "an independent or blind evaluation: worlds, held-out families, the grammar, the "
            "engine, every safety gate and the evaluator's rule share an author lineage",
            "that v1.2 or v1.3 replaces v1.1: v1.1 remains the offline safety baseline",
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
#: Files in the evidence directory that `build` does not produce (kept, never compared).
NOT_BUILT = ("run.log", INTERPRETERS_FILE, "reproduction_before.log")


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
        if current not in known:
            print(
                f"(note: INTERPRETER MISMATCH as well -- written under {recorded}, "
                f"running {current})"
            )
        return 1
    if record:
        if current not in known:
            verified.append({**environment(), "result": "every evidence file reproduced exactly"})
            verified_path.write_text(_dump({"reproduced_under": verified}), encoding="utf-8")
            print(f"recorded: {current} reproduces the evidence exactly")
        return 0
    if current not in known:
        print(
            f"INTERPRETER MISMATCH: the evidence was written under {recorded} and reproduced under "
            f"{sorted(k for k in known if k)}; this is {current}. Every file matched, but this "
            "interpreter is not recorded as verified -- refusing to call the evidence current "
            "(re-run with --record-interpreter after review)."
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
    parser.add_argument("--dev", nargs=2, type=int, metavar=("BASE", "PER"))
    parser.add_argument("--diagnose-noise", type=int, metavar="PER")
    parser.add_argument("--budgets", default="")
    parser.add_argument("--settings", default=",".join(SETTINGS))
    parser.add_argument("--arms", default=",".join(ev.ARM_IDS))
    parser.add_argument("--kinds", default="")
    parser.add_argument("--in-process", action="store_true")
    parser.add_argument("--dev-out", type=Path, help="development only: also write JSON here")
    parser.add_argument("--arm-worker", action="store_true")
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args(argv)
    if args.arm_worker:
        return worker_loop(_handle)
    log: list[str] = []
    budgets = tuple(int(b) for b in args.budgets.split(",")) if args.budgets else PLAN.budgets
    if args.diagnose_noise:
        diagnose_noise(log, args.diagnose_noise, budgets)
        print("\n".join(log))
        return 0
    if args.dev:
        base, per = args.dev
        if base not in {r.base_seed for r in PLAN.development}:
            parser.error("--dev runs declared development seeds only")
        mode = "in-process" if args.in_process else "boundary"
        arms = tuple(a for a in args.arms.split(",") if a)
        settings = tuple(s for s in args.settings.split(",") if s)
        if base == 1 and "benchmark" in settings:
            kinds = tuple(k for k in args.kinds.split(",") if k)
            result, rows, _ = benchmark_set(
                log, base, per, budgets, args.jobs, "DEVELOPMENT", mode, arms, kinds
            )
            _matched_log(log, "benchmark", result["matched"])
            for kind, summary in result["per_kind"].items():
                for budget in budgets:
                    line = " ".join(
                        f"{arm} credited {summary[str(budget)][arm]['all']['credited']} "
                        f"own {summary[str(budget)][arm]['all']['own_correct']}"
                        for arm in arms
                        if arm in summary[str(budget)]
                    )
                    log.append(f"per kind {kind} b{budget}: {line}")
        elif base != 1:
            result, rows, _ = held_out_set(
                log, base, per, budgets, args.jobs, "DEVELOPMENT", settings, mode, arms
            )
            for name in ("held_out", "control"):
                if name in result:
                    _matched_log(log, name, result[name]["matched"])
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
