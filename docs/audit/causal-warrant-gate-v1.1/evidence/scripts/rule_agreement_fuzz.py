"""Differential check of the two confirmation rules on random multi-fault devices (implementer-run).

Each run is a whole diagnosis episode through `tests.vertical_fixtures.run_case`, whose loop is
`CheckedLoop`: after every run it asserts that, for every member of the hypothesis set, SQL's
`confirmation_rule_breaches` finds no breach exactly when Python's `ConfirmationRule.standing`
would confirm that member. A divergence raises AssertionError and is recorded here.

Usage (repo root, PYTHONPATH="src;.", disposable LAB_BRAIN_DATABASE_URL):
    python rule_agreement_fuzz.py <runs> <seed>
"""

from __future__ import annotations

import collections
import random
import sys
import traceback

import psycopg

from tests.postgres_fixtures import database_url, reset_database
from tests.vertical_fixtures import LEAST_COST, SIMULATE_FIRST, load_fixture, run_case

runs, seed = int(sys.argv[1]), int(sys.argv[2])
rng = random.Random(seed)
fx = load_fixture()


def device(i: int) -> dict[str, object]:
    contacts = [
        {
            "contact_id": cid,
            "region": region,
            "via_to_metal": rng.random() > 0.2,
            "overlap_nm": rng.choice(["400", "400", "95", "40"]),
        }
        for cid, region in (("anode", "p_plus"), ("cathode", "n_plus"))
    ]
    return {
        "device_id": f"FZ-{i}",
        "contacts": contacts,
        "extraction_normalization_length_um": rng.choice(
            ["500", "500", "505", "510", "250", "1000"]
        ),
        "access_mesh_max_edge_nm": rng.choice(["5", "5", "40"]),
        "counterdoping_cm3": rng.choice(["0", "0", "1E17", "3E17"]),
        "solver_converges": rng.random() > 0.1,
    }


outcomes: collections.Counter[str] = collections.Counter()
divergences: list[str] = []
errors: list[str] = []
with psycopg.connect(database_url(), autocommit=True) as c:
    for i in range(runs):
        case: dict[str, object] = {
            "case_id": f"fz-{seed}-{i}",
            "device": device(i),
            "truth": None,
            "expected": {"stop": "UNKNOWN"},
            "cheap_resolvable": False,
        }
        if rng.random() < 0.1:
            case["seat_held_elsewhere"] = True
        if rng.random() < 0.2:
            case["unavailable"] = ["cap:sp.fourpoint_probe"]
        strategy = rng.choice([LEAST_COST, LEAST_COST, SIMULATE_FIRST])
        reset_database(c)
        try:
            run = run_case(c, fx, case, strategy=strategy)
        except AssertionError as exc:
            divergences.append(f"{case['case_id']} {strategy} {case['device']}: {exc}")
            print("DIVERGENCE", divergences[-1], flush=True)
            continue
        except Exception:
            errors.append(f"{case['case_id']} {strategy}: {traceback.format_exc(limit=3)}")
            print("ERROR", errors[-1], flush=True)
            continue
        stop = run.result.stop_reason.value
        confirmed = run.mechanism_of(run.result.confirmed_root_cause)
        outcomes[f"{stop}/{confirmed}"] += 1
        print(f"{case['case_id']} {strategy:14} {stop}/{confirmed}", flush=True)
    reset_database(c)

print(f"\nseed {seed}: {runs} runs, {len(divergences)} divergences, {len(errors)} errors")
for key, n in sorted(outcomes.items()):
    print(f"  {n:3}  {key}")
