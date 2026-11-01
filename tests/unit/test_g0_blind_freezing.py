"""Blind evaluation: the inputs a run reads are the frozen ones, and the environment is checked.

Written first; on 58c68be each of these failed:

    evidence       an evidence file edited after the freeze was fed to the run: the runner hashed
                   only the generator package, never the evidence files the manifest froze
    read twice     the package was hashed, then read again from disk to be parsed: a file swapped
                   in between was the one that ran
    environment    the outputs carried whatever `environment_sha256` string the caller passed --
                   nothing checked the environment before the first case or after the last
    drift fields   `verify` ignored a dirty tree, the endpoint itself (only its locality), the
                   platform, the deployment's LAB_BRAIN_* settings, the schema actually applied to
                   the database, and whether the model digest was measured or only declared
    served digest  a model replaced under the same tag kept the declared digest: nothing asked the
                   local server what it serves

No database and no model: the package is the e2e suite's SYNTHETIC one, and the local model
server is a stand-in answering `/api/tags`.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from lab_brain.evaluation import environment, runner
from lab_brain.evaluation.environment import EnvironmentRefused, capture, environment_hash, verify
from lab_brain.evaluation.manifest import ScoringRefused, score_run
from lab_brain.evaluation.runner import RunnerRefused, run_blind
from tests.e2e.test_g0_evaluation_blind_run_postgres import CASE, _prepare
from tests.unit.test_g0_eval_environment import LOCAL, ORDER, _repo


def _record(episode: str) -> dict[str, Any]:
    return {"episode": episode}


def _rehash(manifest: dict[str, Any]) -> dict[str, Any]:
    manifest["environment_sha256"] = environment_hash(manifest)
    return manifest


# -- the inputs ---------------------------------------------------------------------------------


def test_an_evidence_file_edited_after_the_freeze_is_refused_before_anything_runs(tmp_path):
    evaluator = _prepare(tmp_path)
    (tmp_path / "holdout" / "evidence" / "report.md").write_text("an edited report", "utf-8")
    ran: list[Any] = []
    with pytest.raises(RunnerRefused, match=r"evidence/report\.md"):
        run_blind(
            manifest=evaluator["manifest"],
            root=tmp_path,
            run_case=lambda inputs: ran.append(inputs) or "e",
            collect_record=_record,
        )
    assert ran == []


def test_the_package_is_parsed_from_the_bytes_that_were_hashed(tmp_path, monkeypatch):
    evaluator = _prepare(tmp_path)
    package = tmp_path / "holdout" / "generator-package.json"
    frozen_question = json.loads(package.read_text("utf-8"))["cases"][0]["question"]
    real_load = runner.load_generator_package

    def swap_then_load(path: Path, *args: Any, **kwargs: Any) -> Any:
        swapped = json.loads(package.read_text("utf-8"))
        swapped["cases"][0]["question"] = "a question nobody froze"
        package.write_text(json.dumps(swapped), "utf-8")
        return real_load(path, *args, **kwargs)

    monkeypatch.setattr(runner, "load_generator_package", swap_then_load)
    asked: list[str] = []
    try:
        run_blind(
            manifest=evaluator["manifest"],
            root=tmp_path,
            run_case=lambda inputs: asked.append(inputs.question) or "e",
            collect_record=_record,
        )
    except RunnerRefused as refused:  # the swapped file was read, hashed and refused
        assert "not the file the manifest froze" in str(refused)
    assert asked in ([], [frozen_question]), "the swapped package never runs"


def test_an_evidence_file_the_manifest_did_not_freeze_is_refused(tmp_path):
    evaluator = _prepare(tmp_path)
    manifest = copy.deepcopy(evaluator["manifest"])
    del manifest["input_files"]["holdout/evidence/report.md"]
    from lab_brain.evaluation.manifest import manifest_hash

    manifest["manifest_sha256"] = manifest_hash(manifest)
    with pytest.raises(RunnerRefused, match="not frozen"):
        run_blind(manifest=manifest, root=tmp_path, run_case=str, collect_record=_record)


# -- the environment, around the run ------------------------------------------------------------


def _environment(tmp_path: Path) -> dict[str, Any]:
    return capture(_repo(tmp_path), ORDER, **LOCAL)


def test_a_drifted_environment_is_refused_before_the_first_case(tmp_path):
    evaluator = _prepare(tmp_path)
    recorded = _environment(tmp_path)
    now = _rehash({**copy.deepcopy(recorded), "platform": {"system": "Other", "machine": "x"}})
    ran: list[Any] = []
    with pytest.raises(RunnerRefused, match="platform"):
        run_blind(
            manifest=evaluator["manifest"],
            root=tmp_path,
            run_case=lambda inputs: ran.append(inputs) or "e",
            collect_record=_record,
            environment=recorded,
            observe_environment=lambda: now,
        )
    assert ran == []


def test_drift_during_the_run_is_recorded_and_the_scorer_refuses_it(tmp_path):
    evaluator = _prepare(tmp_path)
    recorded = _environment(tmp_path)
    changed = copy.deepcopy(recorded)
    changed["model"]["model_digest"] = "sha256:" + "f" * 64
    observed = iter([recorded, _rehash(changed)])
    outputs = run_blind(
        manifest=evaluator["manifest"],
        root=tmp_path,
        run_case=lambda inputs: "e",
        collect_record=_record,
        environment=recorded,
        observe_environment=lambda: next(observed),
    )
    assert outputs["environment"]["sha256"] == recorded["environment_sha256"]
    assert outputs["environment"]["verified_before"] is True
    assert any("model digest" in d for d in outputs["environment"]["drift_after"])
    with pytest.raises(ScoringRefused, match="environment changed during the run"):
        score_run(
            manifest=evaluator["manifest"],
            root=tmp_path,
            outputs=outputs,
            truth=evaluator["sealed"],
        )


def test_a_recorded_environment_needs_a_way_to_observe_it(tmp_path):
    evaluator = _prepare(tmp_path)
    with pytest.raises(RunnerRefused, match="observe"):
        run_blind(
            manifest=evaluator["manifest"],
            root=tmp_path,
            run_case=str,
            collect_record=_record,
            environment=_environment(tmp_path),
        )


def test_without_an_environment_the_outputs_say_it_was_not_verified(tmp_path):
    evaluator = _prepare(tmp_path)
    outputs = run_blind(
        manifest=evaluator["manifest"], root=tmp_path, run_case=str, collect_record=_record
    )
    assert outputs["environment"] == {"verified_before": False, "drift_after": None}
    score = score_run(
        manifest=evaluator["manifest"], root=tmp_path, outputs=outputs, truth=evaluator["sealed"]
    )
    assert score["environment"] == {"verified": False, "sha256": None}
    assert CASE in {row["case_id"] for row in score["cases"]}


# -- what verify compares -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "change"),
    [
        ("clean tree", lambda m: m["code"].__setitem__("clean", False)),
        (
            "model endpoint",
            lambda m: m["model"].__setitem__("endpoint", "http://127.0.0.1:8080/v1"),
        ),
        ("platform", lambda m: m["platform"].__setitem__("machine", "riscv64")),
        ("settings", lambda m: m["settings"].__setitem__("digest", "sha256:" + "0" * 64)),
        (
            "applied schema",
            lambda m: m["schema"].__setitem__("applied_digest", "sha256:" + "1" * 64),
        ),
        ("model digest source", lambda m: m["model"].__setitem__("digest_source", "served")),
    ],
)
def test_verify_reports_each_field_that_makes_another_experiment(tmp_path, label, change):
    recorded = _environment(tmp_path)
    now = copy.deepcopy(recorded)
    change(now)
    drift = verify(recorded, _rehash(now))
    assert any(d.startswith(label + ":") for d in drift), drift


def test_settings_record_values_but_only_the_presence_of_secrets():
    state = environment.settings_state(
        {
            "LAB_BRAIN_LLM_MAX_OUTPUT_TOKENS": "2048",
            "LAB_BRAIN_DATABASE_URL": "postgresql://u:hunter2@db/x",
            "LAB_BRAIN_REVIEW_KEY_PASSPHRASE": "hunter2",
            "LAB_BRAIN_LLM_API_KEY": "sk-live-abc",
            "PATH": "/usr/bin",
        }
    )
    text = json.dumps(state)
    assert "LAB_BRAIN_LLM_MAX_OUTPUT_TOKENS=2048" in state["values"]
    assert "hunter2" not in text and "sk-live-abc" not in text and "PATH" not in text
    assert "LAB_BRAIN_DATABASE_URL=<set>" in state["values"]


# -- the digest the local server serves ---------------------------------------------------------


def _tags(digest: str) -> Any:
    def fetch(url: str) -> Mapping[str, Any]:
        assert url == "http://127.0.0.1:11434/api/tags"
        return {"models": [{"name": "qwen2.5:7b", "model": "qwen2.5:7b", "digest": digest}]}

    return fetch


def test_the_served_digest_is_read_from_the_local_server():
    got = environment.served_model_digest(LOCAL["endpoint"], "qwen2.5:7b", fetch=_tags("a" * 64))
    assert got == "sha256:" + "a" * 64
    assert (
        environment.served_model_digest(LOCAL["endpoint"], "other", fetch=_tags("a" * 64)) is None
    )


def test_a_declared_digest_the_server_contradicts_is_refused(tmp_path):
    with pytest.raises(EnvironmentRefused, match="serves"):
        capture(_repo(tmp_path), ORDER, fetch_tags=_tags("b" * 64), **LOCAL)
    agreed = capture(_repo(tmp_path / "2"), ORDER, fetch_tags=_tags("a" * 64), **LOCAL)
    assert agreed["model"]["digest_source"] == "served"


def test_a_server_that_cannot_say_leaves_the_digest_declared(tmp_path):
    def unreachable(url: str) -> Mapping[str, Any]:
        raise OSError("connection refused")

    m = capture(_repo(tmp_path), ORDER, fetch_tags=unreachable, **LOCAL)
    assert m["model"]["digest_source"] == "declared"


def test_a_remote_endpoint_is_never_asked(tmp_path):
    asked: list[str] = []

    def fetch(url: str) -> Mapping[str, Any]:
        asked.append(url)
        return {}

    remote = {**LOCAL, "endpoint": "https://models.provider.invalid/v1"}
    m = capture(_repo(tmp_path), ORDER, allow_remote=True, fetch_tags=fetch, **remote)
    assert asked == [] and m["model"]["digest_source"] == "declared"


def test_the_environment_module_states_what_it_pins():
    for word in ("settings", "applied", "served", "platform"):
        assert word in (environment.__doc__ or "")
