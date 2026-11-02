"""A formally ACCEPTED blind evaluation needs an independently verified environment.

On f41758c every score was the same kind of score: a run whose environment nobody verified was
scored exactly like a run whose environment the runner and the evaluator both verified, and
nothing let an acceptance score demand more (the first test failed: `score_run` had no notion of
purpose). Now:

    ACCEPTANCE   the runner verified the environment before the first case and after the last,
                 AND the evaluator's own verification record (`verify --verifier --out`) is of
                 that same environment, found no difference, saw a clean tree and a model digest
                 the server measured, and hashes to itself. Anything less is refused.
    DIAGNOSTIC   scores whatever ran, and says it is not an acceptance result -- and, when so,
                 that its environment was not independently verified.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from lab_brain.evaluation.environment import (
    capture,
    environment_hash,
    verification_record,
)
from lab_brain.evaluation.manifest import ScoringRefused, score_run
from lab_brain.evaluation.runner import run_blind
from tests.e2e.test_g0_evaluation_blind_run_postgres import _prepare
from tests.unit.test_g0_eval_environment import LOCAL, ORDER, _repo


def _served(url: str) -> Any:
    return {"models": [{"name": LOCAL["model_id"], "digest": LOCAL["model_digest"][7:]}]}


def _environment(tmp_path: Any, **changes: Any) -> dict[str, Any]:
    return capture(_repo(tmp_path), ORDER, fetch_tags=_served, **{**LOCAL, **changes})


def _run(evaluator: Any, root: Any, environment: dict[str, Any] | None) -> dict[str, Any]:
    return run_blind(
        manifest=evaluator["manifest"],
        root=root,
        run_case=lambda inputs: "e",
        collect_record=lambda episode: {"episode": episode},
        environment=environment,
        observe_environment=(lambda: environment) if environment is not None else None,
    )


def _score(evaluator: Any, root: Any, outputs: Any, **kwargs: Any) -> dict[str, Any]:
    return score_run(
        manifest=evaluator["manifest"],
        root=root,
        outputs=outputs,
        truth=evaluator["sealed"],
        **kwargs,
    )


def _record(recorded: dict[str, Any], now: dict[str, Any] | None = None) -> dict[str, Any]:
    return verification_record(
        recorded, now or recorded, verifier_id="act:evaluator", verified_at="2026-11-02T00:00:00Z"
    )


def test_an_acceptance_score_refuses_a_run_whose_environment_nobody_verified(tmp_path):
    evaluator = _prepare(tmp_path)
    outputs = _run(evaluator, tmp_path, None)
    with pytest.raises(ScoringRefused, match="runner verified"):
        _score(evaluator, tmp_path, outputs, purpose="ACCEPTANCE")


def test_an_acceptance_score_needs_the_evaluators_own_verification(tmp_path):
    evaluator = _prepare(tmp_path)
    environment = _environment(tmp_path / "env")
    outputs = _run(evaluator, tmp_path, environment)
    with pytest.raises(ScoringRefused, match="no independent environment verification"):
        _score(evaluator, tmp_path, outputs, purpose="ACCEPTANCE")


def test_a_verified_run_with_a_clean_independent_record_is_accepted(tmp_path):
    evaluator = _prepare(tmp_path)
    environment = _environment(tmp_path / "env")
    outputs = _run(evaluator, tmp_path, environment)
    score = _score(
        evaluator,
        tmp_path,
        outputs,
        purpose="ACCEPTANCE",
        environment_verification=_record(environment),
    )
    assert score["purpose"] == "ACCEPTANCE" and score["standing"].startswith("ACCEPTANCE")
    assert score["environment_verification"]["verifier_id"] == "act:evaluator"
    assert score["environment_verification"]["problems"] == []


def _rehash(m: dict[str, Any]) -> dict[str, Any]:
    m["environment_sha256"] = environment_hash(m)
    return m


@pytest.mark.parametrize(
    ("label", "make", "why"),
    [
        (
            "another environment",
            lambda env, tmp: _record(_rehash({**copy.deepcopy(env), "platform": {"x": 1}})),
            "another environment",
        ),
        (
            "differences",
            lambda env, tmp: _record(
                env, _rehash({**copy.deepcopy(env), "platform": {"system": "Other"}})
            ),
            "found differences",
        ),
        (
            "declared digest",
            lambda env, tmp: _record(
                _environment(tmp / "declared", model_digest=LOCAL["model_digest"])
                | {"model": {**env["model"], "digest_source": "declared"}}
            ),
            "only declared",
        ),
        (
            "tampered",
            lambda env, tmp: {**_record(env), "verifier_id": "act:someone-else"},
            "does not hash",
        ),
    ],
)
def test_an_acceptance_score_refuses_a_verification_that_does_not_qualify(
    tmp_path, label, make, why
):
    evaluator = _prepare(tmp_path)
    environment = _environment(tmp_path / "env")
    outputs = _run(evaluator, tmp_path, environment)
    with pytest.raises(ScoringRefused, match=why):
        _score(
            evaluator,
            tmp_path,
            outputs,
            purpose="ACCEPTANCE",
            environment_verification=make(environment, tmp_path),
        )


def test_a_dirty_tree_never_verifies_for_acceptance(tmp_path):
    evaluator = _prepare(tmp_path)
    environment = _environment(tmp_path / "env")
    outputs = _run(evaluator, tmp_path, environment)
    dirty = _rehash(copy.deepcopy(environment))
    dirty["code"]["clean"] = False
    record = _record(environment, _rehash(dirty))
    with pytest.raises(ScoringRefused, match="not clean"):
        _score(evaluator, tmp_path, outputs, purpose="ACCEPTANCE", environment_verification=record)


def test_a_diagnostic_score_says_what_it_is(tmp_path):
    evaluator = _prepare(tmp_path)
    outputs = _run(evaluator, tmp_path, None)
    score = _score(evaluator, tmp_path, outputs)
    assert score["purpose"] == "DIAGNOSTIC"
    assert score["standing"] == (
        "DIAGNOSTIC: not an acceptance result (environment not independently verified)"
    )
    environment = _environment(tmp_path / "env")
    verified = _score(
        evaluator,
        tmp_path,
        _run(evaluator, tmp_path, environment),
        environment_verification=_record(environment),
    )
    assert verified["standing"] == "DIAGNOSTIC: not an acceptance result"


def test_a_purpose_is_one_of_two(tmp_path):
    evaluator = _prepare(tmp_path)
    with pytest.raises(ScoringRefused, match="ACCEPTANCE or DIAGNOSTIC"):
        _score(evaluator, tmp_path, _run(evaluator, tmp_path, None), purpose="GATE")


def test_a_verification_names_its_verifier(tmp_path):
    from lab_brain.evaluation.environment import EnvironmentRefused

    environment = _environment(tmp_path / "env")
    with pytest.raises(EnvironmentRefused, match="who verified"):
        verification_record(environment, environment, verifier_id=" ", verified_at="t")
