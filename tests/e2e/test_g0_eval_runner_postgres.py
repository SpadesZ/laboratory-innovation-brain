"""The blind runner end to end, offline: SYNTHETIC case, stand-in model, real PostgreSQL.

    runs      the runner feeds the frozen package's allowlisted inputs through the product, collects
              the record, keeps the prompts the stand-in received, and the evaluator scores it
    crashes   a case whose run raises is CRASHED and stays in the denominator
    frozen    a package edited after the freeze is refused before anything runs
    live      a live run stores no prompt text: `prompts_captured` is false
SOFTWARE EVIDENCE about the evaluation plumbing; not a G0 result and not an independent holdout.
"""

from __future__ import annotations

import pytest

from lab_brain.evaluation.manifest import score_run
from lab_brain.evaluation.runner import RunnerRefused, run_blind
from tests.e2e.test_g0_evaluation_blind_run_postgres import CASE, _prepare, _run
from tests.e2e.test_g0_evaluation_blind_run_postgres import standin as standin
from tests.e2e.test_g0_screening_matrix_postgres import PROTOCOL as MATRIX
from tests.e2e.test_g0_screening_matrix_postgres import _browser, _Deployment, collect
from tests.e2e.test_web_debate_retry_postgres import _activated
from tests.e2e.test_web_llm_credentials_postgres import _setup

pytestmark = pytest.mark.postgres


def _workspace(db, tmp_path, fake):
    _setup(db)
    deployment = _Deployment()
    browser = _browser(tmp_path, deployment, MATRIX["configurations"]["screening"])
    _activated(db, browser, fake)
    return browser, deployment


def test_the_runner_runs_every_frozen_case_blind_and_the_evaluator_scores_it(db, tmp_path, standin):
    fake, _model = standin
    evaluator = _prepare(tmp_path)
    browser, deployment = _workspace(db, tmp_path, fake)
    seen: dict[str, list[str]] = {}

    def run_case(inputs):
        deployment.unavailable = inputs.unavailable
        before = len(fake.calls)
        episode = _run(browser, inputs)
        seen[episode] = [c.prompt for c in fake.calls[before:]]
        return episode

    outputs = run_blind(
        manifest=evaluator["manifest"],
        root=tmp_path,
        run_case=run_case,
        collect_record=lambda episode: collect(db, episode),
        prompts_of=lambda episode: seen[episode],
        environment_sha256="sha256:" + "e" * 64,
    )
    entry = outputs["cases"][CASE]
    assert entry["status"] == "COMPLETED" and entry["record"]["prompts_captured"] is True
    assert entry["record"]["prompts"], "the stand-in saw the run's prompts"
    assert outputs["environment_sha256"].startswith("sha256:")
    result = score_run(
        manifest=evaluator["manifest"], root=tmp_path, outputs=outputs, truth=evaluator["sealed"]
    )
    assert result["summary"]["status_counts"]["COMPLETED"] == 1


def test_a_case_that_raises_is_crashed_and_kept(db, tmp_path, standin):
    evaluator = _prepare(tmp_path)

    def broken(_inputs):
        raise RuntimeError("SYNTHETIC: the worker died")

    outputs = run_blind(
        manifest=evaluator["manifest"], root=tmp_path, run_case=broken, collect_record=dict
    )
    assert outputs["cases"] == {
        CASE: {"status": "CRASHED", "reason": "RuntimeError: SYNTHETIC: the worker died"}
    }
    result = score_run(
        manifest=evaluator["manifest"], root=tmp_path, outputs=outputs, truth=evaluator["sealed"]
    )
    assert result["summary"]["status_counts"]["CRASHED"] == 1
    assert result["summary"]["frozen_cases"] == 1


def test_a_package_edited_after_the_freeze_runs_nothing(db, tmp_path, standin):
    evaluator = _prepare(tmp_path)
    package = evaluator["package"]
    package.write_text(package.read_text().replace("weakly bias dependent", "strongly"))
    ran: list[object] = []
    with pytest.raises(RunnerRefused, match="not the generator package"):
        run_blind(
            manifest=evaluator["manifest"],
            root=tmp_path,
            run_case=lambda inputs: ran.append(inputs) or "x",
            collect_record=dict,
        )
    assert not ran
    tampered = {**evaluator["manifest"], "cases": []}
    with pytest.raises(RunnerRefused, match="does not hash"):
        run_blind(manifest=tampered, root=tmp_path, run_case=str, collect_record=dict)


def test_a_run_without_prompt_capture_says_so(db, tmp_path, standin):
    evaluator = _prepare(tmp_path)
    outputs = run_blind(
        manifest=evaluator["manifest"],
        root=tmp_path,
        run_case=lambda inputs: "episode",
        collect_record=lambda episode: {"hypotheses": []},
    )
    record = outputs["cases"][CASE]["record"]
    assert record["prompts_captured"] is False and record["prompts"] == []
