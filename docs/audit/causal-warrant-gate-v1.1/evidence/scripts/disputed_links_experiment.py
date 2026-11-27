"""Experiment (not product code): withdraw the automatic DOMAIN authority of disputed links.

Review 4 (science validator) disputed three links on CATEGORY grounds -- the check cannot observe
what the link claims:
    contact_discontinuity  CONTRADICTS  (CONTINUOUS from a drawn-layout reading: a fabricated
                                         defect is invisible to it)
    dopant_compensation    CONTRADICTS  (NOMINAL from a design-file solve: process compensation is
                                         invisible to it)
    mesh_artifact          SUPPORTS     (a solver mesh property as the cause of a MEASURED anomaly)
Withdrawing automatic authority means the relation still records its outcome but needs a person
(REVIEW) to warrant it. Python-only patch; the SQL mirror is not patched, so the harness's
SQL/Python agreement check is disabled for this experiment only.

Usage (repo root, PYTHONPATH="src;.", disposable LAB_BRAIN_DATABASE_URL):
    python disputed_links_experiment.py [baseline|withdrawn]
"""

from __future__ import annotations

import sys

import psycopg

import lab_brain.core.warrant as warrant
import tests.vertical_fixtures as vf
from lab_brain.core.models.enums import RelationType
from tests.postgres_fixtures import database_url, reset_database

DISPUTED = {
    ("contact_discontinuity", RelationType.CONTRADICTS),
    ("dopant_compensation", RelationType.CONTRADICTS),
    ("mesh_artifact", RelationType.SUPPORTS),
}

mode = sys.argv[1] if len(sys.argv) > 1 else "withdrawn"
if mode == "withdrawn":
    original = warrant.domain_warrant

    def withdrawn(relation, certificate, declarations):  # type: ignore[no-untyped-def]
        found = original(relation, certificate, declarations)
        if found is not None and (found.class_id, relation.relation_type) in DISPUTED:
            return None
        return found

    warrant.domain_warrant = withdrawn  # type: ignore[assignment]
    vf.assert_rules_agree = lambda *a, **k: None  # type: ignore[assignment]

fx = vf.load_fixture()
with psycopg.connect(database_url(), autocommit=True) as c:
    for strategy in vf.STRATEGIES:
        for case in fx["cases"]:
            reset_database(c)
            run, _ = vf.run_with_history(c, fx, case, strategy=strategy)
            record = vf.record_for(run, case)
            print(
                f"{mode:9} {strategy:14} {case['case_id']:22} expected="
                f"{case['expected']['stop']}/{case['expected'].get('cause')} got="
                f"{record.stop}/{record.confirmed} pending={record.pending_action} "
                f"checks={','.join(x.action_id.split('.')[-1] for x in record.executed)}",
                flush=True,
            )
    reset_database(c)
