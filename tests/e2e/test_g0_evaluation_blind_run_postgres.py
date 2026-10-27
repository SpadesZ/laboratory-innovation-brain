"""G0 independent-holdout workflow end to end: one SYNTHETIC case run blind through the product.

ALL DATA HERE IS SYNTHETIC and the Hypothesis Engine is the deterministic stand-in
(`tests.g0_standin`), exactly as in the offline screening matrix: SOFTWARE EVIDENCE about the
evaluation plumbing, not a G0 result and not an independent holdout.

What only a real backend can show, and the unit tests cannot:

    blind       the generator side is handed the generator package and the manifest hash only;
                the run is fed from `research_inputs` (the allowlisted projection) through the
                web form, and the stand-in's reads, every prompt the provider received and every
                row of every table in the database afterwards are scanned for each secret truth
                string -- the case id, the true cause, the sealed rationale. None may appear
                (the database holds the cause keys only in the vertical's own diagnostic catalog,
                which is checked to be the only place)
    bound       the outputs document carries the manifest hash; the evaluator reveals the sealed
                truth (kept outside the package directory), it verifies against the frozen
                commitment, and the scorer counts the case, with Wilson and bootstrap intervals
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest

from lab_brain.evaluation.manifest import OUTPUTS_KIND, freeze, score_run
from lab_brain.evaluation.packages import (
    ResearchInputs,
    assert_no_truth,
    load_generator_package,
    research_inputs,
    truth_strings,
)
from lab_brain.evaluation.sealing import commitments_document, load_sealed_truth, seal
from tests.e2e.test_g0_screening_matrix_postgres import PROTOCOL as MATRIX
from tests.e2e.test_g0_screening_matrix_postgres import _browser, _Deployment, collect
from tests.e2e.test_research_episode_postgres import PROJECT, REPORT
from tests.e2e.test_web_debate_retry_postgres import _activated
from tests.e2e.test_web_llm_credentials_postgres import KEY, _setup, _text
from tests.e2e.test_web_llm_runtime_postgres import _token
from tests.fake_llm_provider import FakeProvider
from tests.g0_standin import StandIn
from tests.wsgi_client import Browser

pytestmark = pytest.mark.postgres

ROOT = Path(__file__).resolve().parents[2]
CASE = "syn-blind-e2e-7f3a"
RATIONALE = "SYNTHETIC sealed rationale marmot-upsilon: cathode via left floating"
TRUTH = {
    "true_causes": ["contact_discontinuity"],
    "decisive_cheap_checks": ["cap:sp.inspect_contact_connectivity"],
    "expected_abnormal_observables": ["sp.contact_connectivity"],
    "rationale": RATIONALE,
}


@pytest.fixture
def standin() -> Iterator[tuple[FakeProvider, StandIn]]:
    model = StandIn(structure_reading=False)
    provider = FakeProvider(api_key=KEY, rewrite=model.rewrite).start()
    yield provider, model
    provider.stop()


def _prepare(root: Path) -> dict[str, Any]:
    """The evaluator's side: a SYNTHETIC package, sealed truth outside it, and the freeze."""
    holdout = root / "holdout"
    (holdout / "evidence").mkdir(parents=True)
    (holdout / "evidence" / "report.md").write_bytes(REPORT.read_bytes())
    nominal = json.loads((ROOT / "benchmarks/g0_screening/dev/cases.json").read_text())[
        "nominal_device"
    ]
    package = holdout / "generator-package.json"
    package.write_text(
        json.dumps(
            {
                "kind": "g0-eval/generator-package@1",
                "suite": "synthetic-e2e",
                "synthetic": True,
                "nominal_device": {**nominal, "device_id": "SYN-900"},
                "cases": [
                    {
                        "case_id": CASE,
                        "question": "Why is Rs extremely high and weakly bias dependent while Cj"
                        " trends normally?",
                        "device": {
                            "contacts": [
                                {
                                    "contact_id": "anode",
                                    "region": "p_plus",
                                    "via_to_metal": True,
                                    "overlap_nm": "400",
                                },
                                {
                                    "contact_id": "cathode",
                                    "region": "n_plus",
                                    "via_to_metal": False,
                                    "overlap_nm": "400",
                                },
                            ]
                        },
                        "evidence": [{"name": "report.md", "path": "evidence/report.md"}],
                        "allowed_sources": ["the attached measurement report"],
                        "provenance": {
                            "unit_id": "synthetic-e2e-unit",
                            "source_family": "synthetic-e2e",
                            "device_family": "synthetic-SYN-900",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    sealed_path = root / "evaluator-only" / "truth.sealed.json"
    sealed_path.parent.mkdir()
    sealed_path.write_text(
        json.dumps(
            seal(
                {
                    "kind": "g0-eval/evaluator-truth@1",
                    "suite": "synthetic-e2e",
                    "cases": {CASE: {"truth": TRUTH}},
                }
            )
        ),
        encoding="utf-8",
    )
    sealed = load_sealed_truth(sealed_path)
    # The protocol is copied under the freeze root: every frozen path is relative to it.
    protocol = holdout / "protocol.json"
    protocol.write_bytes((ROOT / "benchmarks/g0_evaluation/protocol.example.json").read_bytes())
    manifest = freeze(
        root=root,
        protocol_path=protocol,
        package_path=package,
        commitments=commitments_document(sealed),
        include_exposed_screening=False,
    )
    return {"package": package, "sealed": sealed, "manifest": manifest}


def _run(browser: Browser, inputs: ResearchInputs) -> str:
    """The generator side: the allowlisted inputs, through the product's own form."""
    sent = browser.post(
        "/runs",
        {
            "csrf": _token(browser.get("/runs/new")),
            "project": PROJECT,
            "goal": inputs.question,
            "sensitivity": "INTERNAL",
        },
        {
            "measurement": list(inputs.evidence),
            "verification_input": [("device.json", inputs.device_json)],
        },
    )
    assert sent.status == 303, _text(sent)[:800]
    return sent.location.split("/episodes/", 1)[1].split("?", 1)[0].split("#", 1)[0]


def _database_text(db: Any) -> dict[str, str]:
    """Every row of every table, as JSON text -- what the run persisted, all of it."""
    tables = [
        r[0]
        for r in db.execute(
            "SELECT table_name FROM information_schema.tables"
            " WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
        ).fetchall()
    ]
    out: dict[str, str] = {}
    for table in tables:
        rows = db.execute(
            psycopg.sql.SQL("SELECT row_to_json(t)::text FROM {} t").format(
                psycopg.sql.Identifier(table)
            )
        ).fetchall()
        out[f"table:{table}"] = "\n".join(r[0] for r in rows)
    return out


def test_a_synthetic_case_runs_blind_and_is_scored_against_its_commitment(db, tmp_path, standin):
    fake, model = standin
    evaluator = _prepare(tmp_path)
    manifest, sealed = evaluator["manifest"], evaluator["sealed"]

    # ---- generator side: package + manifest hash, nothing else ----
    loaded = load_generator_package(evaluator["package"])
    inputs = research_inputs(loaded, CASE)
    _setup(db)
    deployment = _Deployment()
    deployment.unavailable = inputs.unavailable
    browser = _browser(tmp_path, deployment, MATRIX["configurations"]["screening"])
    _activated(db, browser, fake)
    calls_before = len(fake.calls)
    episode = _run(browser, inputs)
    record = collect(db, episode)
    record["prompts"] = [c.prompt for c in fake.calls[calls_before:]]
    assert record["prompts"], "the run sent no prompt: nothing was tested"
    outputs = {
        "kind": OUTPUTS_KIND,
        "manifest_sha256": manifest["manifest_sha256"],
        "cases": {CASE: {"status": "COMPLETED", "record": record}},
    }

    # ---- evaluator side: only now is the truth read ----
    forbidden = truth_strings(sealed.truth())
    assert {CASE, RATIONALE, "contact_discontinuity"} <= set(forbidden)
    assert_no_truth(inputs.texts(), forbidden)
    assert_no_truth({"standin_reads": json.dumps(model.reads)}, forbidden)
    assert_no_truth({f"prompt[{i}]": p for i, p in enumerate(record["prompts"])}, forbidden)
    # The database holds the vertical's own diagnostic catalog, whose keys include every cause
    # name ("contact_discontinuity") by design -- vocabulary, not an answer. Every string that
    # cannot appear there legitimately -- the case id and the sealed rationale -- must not.
    persisted = _database_text(db)
    assert_no_truth(persisted, [s for s in forbidden if s not in TRUTH["true_causes"]])
    catalog = {label for label, text in persisted.items() if "contact_discontinuity" in text}
    assert catalog == {"table:diagnostic_declaration_sets"}, catalog

    result = score_run(manifest=manifest, root=tmp_path, outputs=outputs, truth=sealed)
    summary = result["summary"]
    assert summary["frozen_cases"] == 1 and summary["status_counts"]["COMPLETED"] == 1
    assert summary["metrics"]["no_leak"]["k"] == summary["metrics"]["no_leak"]["n"] == 1
    for metric in summary["metrics"].values():
        assert metric["n"] == metric["applicable"] == 1
        assert metric["wilson95"] is not None and metric["bootstrap95"] is not None
