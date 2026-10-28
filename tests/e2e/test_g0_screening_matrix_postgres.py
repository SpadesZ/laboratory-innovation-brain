"""The offline G0 screening matrix: four configurations x the dev and exposed-regression cases.

The `holdout/` directory is development/regression evidence since protocol amendment 1: its truth
was reported to the implementer before the stand-in was frozen, so it is not a blind split.

    baseline    no screening, no structure summary -- the recorded live behaviour
    screening   exploratory screening only (G0 option A)
    structure   the device structure summary only, with a stand-in that reads it (option B)
    combined    both

SOFTWARE EVIDENCE, NOT A G0 RESULT. Every Hypothesis Engine reply comes from the deterministic
stand-in (`tests.g0_standin`), whose rules were frozen in `benchmarks/g0_screening/protocol.json`
before any run; every other role from the fake provider's catalog reading. What is measured is what
the platform does with replies of that shape: which checks run, what is recorded, what can and
cannot move belief. Whether a real model behaves like the stand-in is exactly what the later live
retest has to show.

TRUTH IS READ AFTER THE RUNS, BY THE EVALUATOR. Each episode sees the case's device file and
evidence document only. When every case of a configuration has run, the records are collected from
the database and scored by `benchmarks/g0_screening/score.py` against the evaluator-only truth
files. The governance invariants the protocol fixes for every configuration -- no false
confirmation, no support for a post-screening rival, no repeated screened reading, no ineligible
screening, no false abnormal reading, no leak -- are asserted here; the usefulness rates are
reported (`LAB_BRAIN_G0_MATRIX_OUT=<dir>` writes the records and the scored matrix).
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import psycopg
import pytest

from lab_brain.core.models.capability import Availability
from lab_brain.evaluation.collect import support_provenance
from lab_brain.interfaces.config import Settings
from lab_brain.interfaces.web import Workspace, allowed_hosts
from lab_brain.llm_runtime.secrets import DirectoryCredentialStore, SecretStore
from lab_brain.research.report_store import SqlResearchReportStore
from lab_brain.research.service import ResearchFeatures
from lab_brain.research.vertical import load_vertical_factory
from tests.e2e.test_research_episode_postgres import GOAL, PROJECT, REPORT
from tests.e2e.test_web_debate_retry_postgres import ACTOR, _activated
from tests.e2e.test_web_llm_credentials_postgres import KEY, _setup, _text
from tests.e2e.test_web_llm_runtime_postgres import _token
from tests.fake_llm_provider import FakeProvider
from tests.g0_standin import StandIn
from tests.postgres_fixtures import database_url
from tests.wsgi_client import Browser

pytestmark = pytest.mark.postgres

ROOT = Path(__file__).resolve().parents[2]
BENCH = ROOT / "benchmarks" / "g0_screening"
PROTOCOL = json.loads((BENCH / "protocol.json").read_text(encoding="utf-8"))
OUT = os.environ.get("LAB_BRAIN_G0_MATRIX_OUT", "")


def _scorer() -> Any:
    spec = importlib.util.spec_from_file_location("g0_screening_score", BENCH / "score.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _split(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((BENCH / name / "cases.json").read_text(encoding="utf-8"))
    return data


class _Deployment:
    """The SiPh vertical as a deployment that can or cannot run a given capability."""

    def __init__(self) -> None:
        self.unavailable: tuple[str, ...] = ()
        self._base = load_vertical_factory("silicon_photonics")

    def __call__(self, **kwargs: Any) -> Any:
        vertical = self._base(**kwargs)
        for capability_id in self.unavailable:
            vertical.registry.registries.capabilities.set_availability(
                capability_id, Availability.UNAVAILABLE
            )
        return vertical


def _evidence(split: str, stem: str) -> tuple[str, bytes]:
    if stem == "default":
        return REPORT.name, REPORT.read_bytes()
    path = BENCH / split / "evidence" / f"{stem}.md"
    return path.name, path.read_bytes()


def _run(browser: Browser, split: str, nominal: dict[str, Any], case: dict[str, Any]) -> str:
    name, document = _evidence(split, case["evidence"])
    device = json.dumps({**nominal, **case["device"]}).encode()
    sent = browser.post(
        "/runs",
        {
            "csrf": _token(browser.get("/runs/new")),
            "project": PROJECT,
            "goal": GOAL,
            "sensitivity": "INTERNAL",
        },
        {"measurement": [(name, document)], "verification_input": [("device.json", device)]},
    )
    assert sent.status == 303, _text(sent)[:800]
    found = re.search(r"/episodes/([^?#]+)", sent.location)
    assert found
    return unquote(found.group(1))


def _rows(db: Any, sql: str, *args: object) -> list[tuple[Any, ...]]:
    return list(db.execute(sql, args).fetchall())


def collect(db: Any, episode: str) -> dict[str, Any]:
    """What one episode did, read from the database -- the only input the scorer gets."""
    conditioned = {
        r[0]
        for r in _rows(
            db,
            "SELECT hypothesis_id FROM screening_conditioned_hypotheses WHERE episode_id = %s",
            episode,
        )
    }
    hypotheses = []
    for hid, mechanism in _rows(
        db,
        "SELECT hypothesis_id, mechanism FROM hypotheses WHERE created_in_episode = %s"
        " ORDER BY hypothesis_id",
        episode,
    ):
        discriminates = sorted(
            {
                r[0]
                for r in _rows(
                    db,
                    "SELECT observable_ref FROM predictions WHERE hypothesis_id = %s AND"
                    " relation_effect_if_observed -> 0 ->> 'relation_type' IN"
                    " ('SUPPORTS', 'CONTRADICTS')",
                    hid,
                )
            }
        )
        refutable = sorted(
            {
                r[0]
                for r in _rows(
                    db,
                    "SELECT observable_ref FROM predictions WHERE hypothesis_id = %s AND"
                    " relation_effect_if_observed -> 0 ->> 'relation_type' = 'CONTRADICTS'",
                    hid,
                )
            }
        )
        hypotheses.append(
            {
                "hypothesis_id": hid,
                "refutable_on": refutable,
                "mechanism": mechanism,
                "origin": "POST_SCREENING" if hid in conditioned else "PRE_OBSERVATION",
                "discriminates_on": discriminates,
                # Each SUPPORTS relation with the facts scorer 2.0.0 judges it by -- never a bare
                # count, which could not tell a prospective support from the screened reading.
                "supports": support_provenance(db, hid),
            }
        )
    executed = _rows(
        db,
        "SELECT j.capability_id, j.idempotency_key LIKE 'scr:%%' FROM jobs j"
        " JOIN runs u ON u.job_id = j.job_id WHERE j.episode_id = %s AND u.status = 'SUCCEEDED'"
        " AND (j.idempotency_key LIKE 'scr:%%' OR j.idempotency_key LIKE 'vs:%%')",
        episode,
    )
    # The action type each screened capability was planned under, from the plan's typed
    # candidates; a screening Job no plan selected is reported as such.
    planned = {
        c["capability_id"]: c["action_type"]
        for (candidates,) in _rows(
            db, "SELECT candidates FROM screening_plans WHERE episode_id = %s", episode
        )
        for c in candidates
        if c["disposition"] == "SELECTED"
    }
    kinds = {
        r[0]: planned.get(r[0], "NOT_SELECTED_BY_ANY_PLAN")
        for r in _rows(
            db,
            "SELECT DISTINCT capability_id FROM jobs WHERE episode_id = %s"
            " AND idempotency_key LIKE 'scr:%%'",
            episode,
        )
    }
    readings = [
        {
            "check": check,
            "observable": r["observable_ref"],
            "outcome": r["outcome"],
            "finding": r["finding"],
        }
        for check, payload in _rows(
            db,
            "SELECT capability_id, readings FROM screening_observations WHERE episode_id = %s",
            episode,
        )
        for r in payload
    ]
    (recorded,) = SqlResearchReportStore(db).for_episode(project_id=PROJECT, episode_id=episode)
    report = recorded.report
    ((state, outcome),) = _rows(
        db,
        "SELECT state, coalesce(outcome_status, '') FROM research_episodes WHERE episode_id = %s",
        episode,
    )
    return {
        "episode": episode,
        "episode_state": state,
        "outcome": outcome,
        "confirmed": outcome.removeprefix("CONFIRMED:")
        if outcome.startswith("CONFIRMED:")
        else None,
        "conclusion": report.conclusion.status,
        "conclusion_statement": report.conclusion.statement,
        "hypotheses": hypotheses,
        "screening_executed": sorted({c for c, screened in executed if screened}),
        "verification_executed": sorted({c for c, screened in executed if not screened}),
        "screening_kinds": kinds,
        "readings": readings,
        "screening_enabled": report.screening is not None and report.screening.status != "DISABLED",
        "stages": [[s.stage, s.status] for s in report.stages],
    }


@pytest.fixture
def standin(request: pytest.FixtureRequest) -> Iterator[tuple[FakeProvider, StandIn]]:
    config = PROTOCOL["configurations"][request.param]
    model = StandIn(structure_reading=config["standin"]["structure_reading"])
    provider = FakeProvider(api_key=KEY, rewrite=model.rewrite).start()
    yield provider, model
    provider.stop()


@pytest.mark.parametrize(
    ("config", "standin"),
    [(name, name) for name in PROTOCOL["configurations"]],
    indirect=["standin"],
)
def test_the_matrix_holds_every_governance_invariant(db, tmp_path, config, standin):
    fake, model = standin
    settings = PROTOCOL["configurations"][config]
    _setup(db)
    deployment = _Deployment()
    browser = _browser(tmp_path, deployment, settings)
    _activated(db, browser, fake)
    outputs = _run_splits(db, browser, deployment, fake, ("dev", "holdout"))

    # Only now is truth read -- by the evaluator, for scoring.
    scorer = _scorer()
    forbidden = scorer.truth_strings(scorer.load_truth())
    for split in outputs.values():
        for record in split.values():
            prompts = record.pop("prompts")
            record["leaks"] = sorted({s for s in forbidden for p in prompts if s in p})
    standin_reads = json.dumps(model.reads)
    assert not [s for s in forbidden if s in standin_reads], "the stand-in saw a truth string"
    result = scorer.evaluate({"configurations": {config: outputs}})
    if OUT:
        out = Path(OUT)
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{config}.outputs.json").write_text(
            json.dumps({"configurations": {config: outputs}}, indent=1, ensure_ascii=False),
            encoding="utf-8",
        )
        (out / f"{config}.scored.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    for split in ("dev", "holdout"):
        summary = result["configurations"][config][split]["summary"]
        for invariant, required in PROTOCOL["acceptance_thresholds"]["all_configurations"].items():
            assert summary[invariant] == required, (config, split, invariant, summary)


def _browser(tmp_path: Path, deployment: _Deployment, settings: dict[str, Any]) -> Browser:
    return Browser(
        Workspace(
            actor_id=ACTOR,
            settings=Settings(dsn=database_url()),
            connect=lambda s: psycopg.connect(s.dsn),
            artifact_root=tmp_path / "artifacts",
            vertical_factory=deployment,
            allowed_hosts=allowed_hosts("127.0.0.1", 8765),
            secrets=SecretStore(
                environ={"FAKE_KEY": KEY},
                credentials=DirectoryCredentialStore(tmp_path / "credentials"),
            ),
            default_locale="en",
            ollama_url="http://127.0.0.1:9/v1",
            inference_deadline=60,
            research_features=ResearchFeatures(
                exploratory_screening=settings["exploratory_screening"],
                structure_context=settings["structure_context"],
            ),
        )
    )


def _run_splits(
    db: Any,
    browser: Browser,
    deployment: _Deployment,
    fake: FakeProvider | None,
    splits: tuple[str, ...],
    before_each: Callable[[], None] | None = None,
) -> dict[str, dict[str, Any]]:
    """Every case of `splits`, one episode each. `fake`, when given, is the provider whose
    prompts are kept with each record for the leak check; a live model's run passes None.
    `before_each` runs before every episode -- a live run's cumulative cap, which may refuse."""
    outputs: dict[str, dict[str, Any]] = {}
    calls_before = len(fake.calls) if fake is not None else 0
    for split in splits:
        data = _split(split)
        outputs[split] = {}
        for case in data["cases"]:
            deployment.unavailable = tuple(case.get("deployment", {}).get("unavailable", ()))
            if before_each is not None:
                before_each()
            episode = _run(browser, split, data["nominal_device"], case)
            record = collect(db, episode)
            record["unavailable"] = list(deployment.unavailable)
            if fake is not None:
                record["prompts"] = [c.prompt for c in fake.calls[calls_before:]]
                calls_before = len(fake.calls)
            outputs[split][case["case_id"]] = record
    deployment.unavailable = ()
    return outputs


def _normalized(records: dict[str, Any]) -> dict[str, Any]:
    """What must reproduce: the checks, the readings, the rivals by wording and origin, the
    conclusion -- not ids or timestamps."""
    return {
        case: {
            "screening": r["screening_executed"],
            "verification": r["verification_executed"],
            "readings": sorted(json.dumps(x, sort_keys=True) for x in r["readings"]),
            "hypotheses": sorted(
                (h["mechanism"], h["origin"], tuple(h["discriminates_on"]), h["supports"])
                for h in r["hypotheses"]
            ),
            "conclusion": r["conclusion"],
            "state": r["episode_state"],
        }
        for case, r in records.items()
    }


@pytest.mark.parametrize("standin", ["screening"], indirect=True)
def test_the_screening_configuration_reproduces_on_the_dev_split(db, tmp_path, standin):
    fake, _model = standin
    _setup(db)
    deployment = _Deployment()
    browser = _browser(tmp_path, deployment, PROTOCOL["configurations"]["screening"])
    _activated(db, browser, fake)
    first = _run_splits(db, browser, deployment, fake, ("dev",))["dev"]
    second = _run_splits(db, browser, deployment, fake, ("dev",))["dev"]
    assert _normalized(first) == _normalized(second)
    # Each episode screened on its own: the second run's readings are its own Jobs and Runs.
    assert {r["episode"] for r in first.values()}.isdisjoint(
        {r["episode"] for r in second.values()}
    )
