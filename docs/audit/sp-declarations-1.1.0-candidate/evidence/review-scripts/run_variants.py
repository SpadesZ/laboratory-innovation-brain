"""Independent science review P6: run ordinary diagnosis episodes for case variants under the
1.0.0 (registered) and 1.1.0 (candidate) SP declarations. Variants are built in memory only.

Usage (from the worktree, PYTHONPATH="src;."):
    python run_variants.py <group> [<variant id> ...]

Writes one JSON line per (variant, version, strategy) to results.jsonl in this directory.
"""

from __future__ import annotations

import copy
import json
import sys
import time
import traceback
from pathlib import Path

import psycopg

from lab_brain.domains.silicon_photonics import vertical as sp
from tests.postgres_fixtures import reset_database
from tests.vertical_fixtures import (
    LEAST_COST,
    SIMULATE_FIRST,
    candidate_declarations,
    case_by_id,
    load_fixture,
    record_for,
    run_with_history,
)

HERE = Path(__file__).resolve().parent
ROOT = Path.cwd()
FIXTURE_110 = ROOT / "fixtures" / "vertical" / "sp_rs_root_cause_benchmark_1.1.0.json"
DSN = "postgresql://lab_brain:lab_brain@127.0.0.1:5433/lab_brain_sci_p6"

NOMINAL_CONTACTS = [
    {"contact_id": "anode", "region": "p_plus", "via_to_metal": True, "overlap_nm": "400"},
    {"contact_id": "cathode", "region": "n_plus", "via_to_metal": True, "overlap_nm": "400"},
]


def contacts(**over: dict) -> list[dict]:
    out = copy.deepcopy(NOMINAL_CONTACTS)
    for c in out:
        c.update(over.get(c["contact_id"], {}))
    return out


#: id -> (base case in benchmark 1.1.0, device overrides, case overrides, strategies)
VARIANTS: dict[str, tuple[str, dict, dict, tuple[str, ...]]] = {
    # -- the benchmark's changed and added cases, as committed -------------------------------
    "B-mesh-coarse-access": ("mesh-coarse-access", {}, {}, (LEAST_COST, SIMULATE_FIRST)),
    "B-probe-lab-closed": ("probe-lab-closed", {}, {}, (LEAST_COST, SIMULATE_FIRST)),
    "B-open-via-and-taper": ("open-via-and-taper-normalization", {}, {}, (LEAST_COST,)),
    "B-probe-2pct-length": ("probe-artifact-2pct-length", {}, {}, (LEAST_COST,)),
    "B-probe-shorter-length": ("probe-artifact-shorter-length", {}, {}, (LEAST_COST,)),
    # -- counterexample variants --------------------------------------------------------------
    # C1: true cause counter-doping; the simulation mesh is coarse (irrelevant to a measured Rs).
    "C1-dopant+coarse-mesh": (
        "dopant-counterdoped",
        {"device_id": "PS-601", "access_mesh_max_edge_nm": "40"},
        {},
        (LEAST_COST,),
    ),
    # C2: anode overlap 95 nm against a 100 nm rule; nothing else wrong (probe artifact).
    "C2-overlap-95nm": (
        "probe-artifact",
        {"device_id": "PS-602", "contacts": contacts(anode={"overlap_nm": "95"})},
        {},
        (LEAST_COST,),
    ),
    # C3: counter-doping 1.6E17 on 5E17 (ratio 0.32): ~1.5x resistivity, not "several times".
    "C3-weak-compensation": (
        "probe-artifact",
        {"device_id": "PS-603", "counterdoping_cm3": "1.6E17"},
        {},
        (LEAST_COST,),
    ),
    # C4: probe-lab-closed with a coarse simulation mesh as well.
    "C4-lab-closed+coarse-mesh": (
        "probe-lab-closed",
        {"device_id": "PS-604", "access_mesh_max_edge_nm": "40"},
        {},
        (LEAST_COST,),
    ),
    # C5: probe-lab-closed and the split lot not offered either.
    "C5-lab-closed+no-fab": (
        "probe-lab-closed",
        {"device_id": "PS-605"},
        {"unavailable": [sp.CAP_FOURPOINT_PROBE, sp.CAP_FABRICATE_SPLIT]},
        (LEAST_COST,),
    ),
    # C6: counter-doped, solver not converging, probe station closed.
    "C6-nonconverged+lab-closed": (
        "dopant-nonconverged",
        {"device_id": "PS-606"},
        {"unavailable": [sp.CAP_FOURPOINT_PROBE]},
        (LEAST_COST,),
    ),
    # C7: open cathode via AND counter-doping 3E17 (one cheap fault, one simulation-only fault).
    "C7-open-via+dopant": (
        "contact-open-via",
        {"device_id": "PS-607", "counterdoping_cm3": "3E17"},
        {},
        (LEAST_COST,),
    ),
    # C8: taper normalization 1000 um with a coarse mesh, solver-first baseline (mesh is run).
    "C8-taper+coarse-mesh": (
        "normalization-taper",
        {"device_id": "PS-608", "access_mesh_max_edge_nm": "40"},
        {},
        (LEAST_COST, SIMULATE_FIRST),
    ),
    # C9: open via with a coarse mesh, solver-first baseline.
    "C9-open-via+coarse-mesh": (
        "contact-open-via",
        {"device_id": "PS-609", "access_mesh_max_edge_nm": "40"},
        {},
        (LEAST_COST, SIMULATE_FIRST),
    ),
    # C10: counter-doping plus a 95 nm sub-rule overlap: the cheap check stops the loop.
    "C10-dopant+overlap-95nm": (
        "dopant-counterdoped",
        {"device_id": "PS-610", "contacts": contacts(anode={"overlap_nm": "95"})},
        {},
        (LEAST_COST,),
    ),
    # C11: counter-doping just below the rule threshold (ratio 0.28), probe station closed.
    "C11-subthreshold-dopant+lab-closed": (
        "probe-lab-closed",
        {"device_id": "PS-611", "counterdoping_cm3": "1.4E17"},
        {},
        (LEAST_COST,),
    ),
    # C12: marginal mesh edge 11 nm: halving gives exactly the 5 % tolerance.
    "C12-mesh-11nm": (
        "mesh-coarse-access",
        {"device_id": "PS-612", "access_mesh_max_edge_nm": "11"},
        {},
        (LEAST_COST,),
    ),
    # C13: dopant + coarse mesh with the probe station closed.
    "C13-dopant+coarse-mesh+lab-closed": (
        "dopant-counterdoped",
        {"device_id": "PS-613", "access_mesh_max_edge_nm": "40"},
        {"unavailable": [sp.CAP_FOURPOINT_PROBE]},
        (LEAST_COST,),
    ),
    # C14: counter-doping 3E17 with the 1000 um taper normalization (review 04 V5 shape).
    "C14-taper+dopant": (
        "normalization-taper",
        {"device_id": "PS-614", "counterdoping_cm3": "3E17"},
        {},
        (LEAST_COST,),
    ),
    # C16: C1 under the solver-first baseline: the DC sweep runs before the mesh study.
    "C16-dopant+coarse-mesh-simfirst": (
        "dopant-counterdoped",
        {"device_id": "PS-616", "access_mesh_max_edge_nm": "40"},
        {},
        (SIMULATE_FIRST,),
    ),
    # C15: a deep counter-doping (ratio 0.9) on a design that is otherwise sound.
    "C15-deep-compensation": (
        "dopant-counterdoped",
        {"device_id": "PS-615", "counterdoping_cm3": "4.5E17"},
        {},
        (LEAST_COST,),
    ),
}

# Every case of benchmark 1.1.0, unmodified, for the sanity rerun under both versions.
for _c in load_fixture(FIXTURE_110)["cases"]:
    VARIANTS.setdefault(f"F-{_c['case_id']}", (_c["case_id"], {}, {}, (LEAST_COST,)))


def build(fx: dict, base: str, device: dict, over: dict) -> dict:
    case = copy.deepcopy(case_by_id(fx, base))
    case["device"] = {**case.get("device", {}), **device}
    case.update(copy.deepcopy(over))
    return case


def states(run) -> dict[str, str]:
    d = run.loop._d  # read-only projection of each member's belief state
    out = {}
    for mechanism, hid in sorted(run.certificates_by_mechanism.items()):
        p = d.belief.project(
            project_id=run.request.project_id, hypothesis_id=hid, projected_at=d.now()
        )
        out[mechanism] = None if p.current_state is None else p.current_state.value
    return out


def describe(run, case, version: str, strategy: str, variant: str, seconds: float) -> dict:
    record = record_for(run, case)
    outcomes = []
    for step in run.result.steps:
        for o in step.outcomes:
            outcomes.append(
                f"{step.chosen.split('.')[-1]}:{o.outcome}@{o.authority_class}"
            )
    last_plan = run.result.steps[-1].plan if run.result.steps else None
    sufficient = (
        sorted(a for a, s in last_plan.sufficiency_results.items() if s.sufficient)
        if last_plan is not None
        else []
    )
    standing = run.loop.standing(run.request)
    names = {h: m for m, h in run.certificates_by_mechanism.items()}
    discriminating = (
        {
            a: sorted(f"{names.get(h, h)}->{to}@{o}" for h, to, o in s.discriminating)
            for a, s in last_plan.sufficiency_results.items()
            if s.sufficient
        }
        if last_plan is not None
        else {}
    )
    return {
        "variant": variant,
        "version": version,
        "strategy": strategy,
        "device": case.get("device", {}),
        "unavailable": case.get("unavailable", []),
        "stop": record.stop,
        "confirmed": record.confirmed,
        "pending": record.pending_action,
        "checks": [c.split(".")[-1] for c in run.result.executed],
        "outcomes": outcomes,
        "last_plan_sufficient": sufficient,
        "last_plan_discriminating": discriminating,
        "states": states(run),
        "awaiting_relations": len(standing.awaiting),
        "notes": list(run.result.notes),
        "seconds": round(seconds, 1),
    }


def main(argv: list[str]) -> None:
    wanted = argv or sorted(VARIANTS)
    fx = load_fixture(FIXTURE_110)
    candidate, registered = candidate_declarations()
    versions = {"1.0.0": {}, "1.1.0": {"declarations": candidate, "registered": registered}}
    import os

    out = (HERE / os.environ.get("P6_OUT", "results.jsonl")).open("a", encoding="utf-8")
    with psycopg.connect(DSN, autocommit=True) as connection:
        for variant in wanted:
            base, device, over, strategies = VARIANTS[variant]
            case = build(fx, base, device, over)
            for strategy in strategies:
                for version, kw in versions.items():
                    reset_database(connection)
                    started = time.time()
                    try:
                        run, _ = run_with_history(connection, fx, case, strategy=strategy, **kw)
                        row = describe(
                            run, case, version, strategy, variant, time.time() - started
                        )
                    except Exception as bad:  # recorded, not hidden
                        row = {
                            "variant": variant,
                            "version": version,
                            "strategy": strategy,
                            "error": f"{type(bad).__name__}: {bad}",
                            "traceback": traceback.format_exc()[-3000:],
                        }
                    out.write(json.dumps(row) + "\n")
                    out.flush()
                    print(
                        variant,
                        version,
                        strategy,
                        row.get("stop"),
                        row.get("confirmed"),
                        row.get("pending"),
                        ",".join(row.get("checks", [])),
                        row.get("error", ""),
                        flush=True,
                    )
        reset_database(connection)


if __name__ == "__main__":
    main(sys.argv[1:])
