"""Cost of one reuse re-derivation, and of case memory as a project's history grows.

Runs benchmark cases into ONE project of a disposable database (no reset between them), then times
`trusted_confirmations` / `similar_failures` through the deployment's verifier. Usage (repo root,
PYTHONPATH=src, LAB_BRAIN_DATABASE_URL set to a disposable database):
    python verify_cost.py <rounds>
"""

from __future__ import annotations

import sys
import time

import psycopg

from lab_brain.core.models.base import utc_now
from lab_brain.core.repositories.failures import SqlFailureStore
from lab_brain.domains.silicon_photonics.product import product_vertical
from lab_brain.research.confirmation import confirmation_verifier
from tests.debate_fixtures import PROJECT
from tests.postgres_fixtures import database_url, reset_database
from tests.reviewer_keys import TRUST
from tests.vertical_fixtures import load_fixture, run_case

rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 3
fx = load_fixture()
confirmable = [
    c
    for c in fx["cases"]
    if c["expected"]["stop"] == "CONFIRMED" and not c.get("seat_held_elsewhere")
]

with psycopg.connect(database_url(), autocommit=True) as c:
    reset_database(c)
    reading = product_vertical(outputs=None, jobs=None, broker=None, now=utc_now)
    project = PROJECT
    for n in range(rounds):
        for case in confirmable:
            run_case(c, fx, case, scope=f"{case['case_id']}-r{n}")
    store = SqlFailureStore(
        c,
        verify=confirmation_verifier(
            c,
            trust=TRUST,
            declaration_sets=reading.declaration_sets,
            active=reading.active_declarations,
            authority_policies=reading.authority_policies,
        ),
    )
    analyses = store.analyses(project)
    confirmed = [a for a in analyses if a.resolution_status.value == "CONFIRMED"]
    t = time.perf_counter()
    trusted = store.trusted_confirmations(project)
    all_s = time.perf_counter() - t
    symptom = confirmed[0].symptom if confirmed else ""
    t = time.perf_counter()
    similar = store.similar_failures(project, symptom)
    sim_s = time.perf_counter() - t
    t = time.perf_counter()
    none = store.similar_failures(project, "a symptom nobody recorded")
    none_s = time.perf_counter() - t
    print(
        f"analyses={len(analyses)} confirmed={len(confirmed)} trusted={len(trusted)}\n"
        f"trusted_confirmations: {all_s:.2f}s ({all_s / max(len(confirmed), 1) * 1000:.0f} ms each)\n"
        f"similar_failures(same symptom): {sim_s:.2f}s -> {len(similar)} precedents\n"
        f"similar_failures(unrecorded symptom): {none_s:.3f}s -> {len(none)}"
    )
    reset_database(c)
