"""The research pipeline with a REAL language model and no Lumerical: the live acceptance check.

SKIPPED UNLESS ASKED FOR. It runs only when `LAB_BRAIN_LIVE_PRIMARY` names a model this machine's
Ollama serves (`LAB_BRAIN_LIVE_OLLAMA`, default http://127.0.0.1:11434/v1), with
`LAB_BRAIN_LIVE_CRITIC` and `LAB_BRAIN_LIVE_UTILITY` for the other slots (each defaults to the
primary). Local: no credential, no egress, no cost. Nothing is stubbed -- every capability probe
and every research call goes to the named model, and a run takes as long as the model does
(`LAB_BRAIN_LIVE_DEADLINE`, seconds per inference, default 1800).

AN EXTERNAL PRIMARY ONLY BY THE OWNER'S OWN SETTING. With `LAB_BRAIN_LIVE_PRIMARY_PROVIDER` (a
preset such as `gemini`) and `LAB_BRAIN_LIVE_PRIMARY_KEY_ENV` (the NAME of an environment variable
the owner has set to the key), the primary is reached through that provider: the workspace reads
the key from that variable by name, as `lab-brain web` does, and the test never sees or stores it.
That sends the test project's evidence -- the repository's fixture report, nothing of the lab's --
to the provider and may cost money; the disposable project declares that egress through its own
page first, as a real one must. The critic and utility slots stay local unless named otherwise.

    qualification  each model is tested with all eight capability probes and locked through the
                   pages, as an administrator does; a slot takes it only if it demonstrated what
                   the slot needs. A model that did not is reported with the probes' own reasons,
                   and no research runs: the blocker, not a substitute
    provenance     every inference the runs made is on record as one of the named models, through
                   the local connection -- never the catalog reasoner, never a stand-in
    three cases    sufficient (open via), insufficient (sound design), competing (two signatures):
                   no simulation runs or is emulated, and nothing is confirmed unless the confirmed
                   hypothesis itself declared the outcome the check observed
    reading        the zh-TW page names the models from provenance; their own text is shown as
                   written and marked untranslated
    evidence       with `LAB_BRAIN_LIVE_EVIDENCE=<dir>`, the probes, the provenance rows with the
                   models' outputs (and each call's parameters: attempt, retry_of, aliases, output
                   mode), and each episode's zh-TW page and summary are written there; outcomes.json
                   also holds what each case executed, every admitted prediction, the debate's
                   reliability record (reply attempts, coverage review) and the provider's usage --
                   what `scripts/g0_live_compare.py` scores against the earlier runs

    features       `LAB_BRAIN_LIVE_FEATURES` names the configuration of `benchmarks/g0_screening/
                   protocol.json` the runs use -- baseline, screening (the default, as deployed),
                   structure or combined -- and the outcomes record which
    matrix         `LAB_BRAIN_LIVE_CASES=dev|holdout|matrix` also runs the protocol's dev and/or
                   exposed-regression (former holdout) cases -- development evidence, not a blind
                   split (protocol amendment 1) -- each with its own evidence and deployment, and
                   writes `matrix.outputs.json` in the form `benchmarks/g0_screening/score.py`
                   scores -- truth is read by the scorer only, after the runs

G0 RETEST (owner-authorized only; an external primary is billable). From the repository root:

    LAB_BRAIN_TEST_POSTGRES=1 LAB_BRAIN_DATABASE_URL=<a fresh, migrated database>
    LAB_BRAIN_LIVE_PRIMARY=models/gemini-3.1-pro-preview LAB_BRAIN_LIVE_PRIMARY_PROVIDER=gemini
    LAB_BRAIN_LIVE_PRIMARY_KEY_ENV=GEMINI_API_KEY LAB_BRAIN_LIVE_CRITIC=qwen2.5:7b
    LAB_BRAIN_LIVE_UTILITY=qwen2.5:7b LAB_BRAIN_LIVE_EVIDENCE=<new evidence dir>
    LAB_BRAIN_LIVE_MAX_CALLS=<cap> LAB_BRAIN_LIVE_MAX_TOKENS=<cap>
    LAB_BRAIN_LIVE_SPEND_CEILING=<money> LAB_BRAIN_LIVE_SPEND_CURRENCY=USD
    LAB_BRAIN_LIVE_PRICE_INPUT_PER_MTOK=<Owner's price> LAB_BRAIN_LIVE_PRICE_OUTPUT_PER_MTOK=<...>
    LAB_BRAIN_LIVE_PRICE_SOURCE=<where read> LAB_BRAIN_LIVE_PRICE_DATE=<YYYY-MM-DD>
    pytest tests/e2e/test_research_live_model_postgres.py
    python scripts/g0_live_compare.py <earlier run dirs> -- <new evidence dir>

  For the screening evaluation, repeat with LAB_BRAIN_LIVE_FEATURES=baseline|screening|structure|
  combined and LAB_BRAIN_LIVE_CASES=matrix (a fresh database each time), then
    python benchmarks/g0_screening/score.py <evidence dir>/matrix.outputs.json
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
from pathlib import Path
from typing import Any

import psycopg
import pytest

from lab_brain.domains.silicon_photonics import tools
from lab_brain.domains.silicon_photonics import vertical as sp
from lab_brain.evaluation.live_budget import (
    cap_from_env,
    check_before_episode,
    check_spend_before_episode,
    install_live_spend_guard,
    spend_from_env,
)
from lab_brain.interfaces.config import Settings
from lab_brain.interfaces.web import Workspace, allowed_hosts
from lab_brain.interfaces.web.settings_pages import PROVIDERS
from lab_brain.llm_runtime import spend
from lab_brain.llm_runtime.secrets import SecretStore
from lab_brain.research.report_store import SqlResearchReportStore
from lab_brain.research.service import ResearchFeatures
from lab_brain.research.vertical import load_vertical_factory
from tests.e2e.test_research_episode_postgres import GOAL, PROJECT, REPORT, _member
from tests.e2e.test_web_llm_credentials_postgres import _admin
from tests.e2e.test_web_llm_runtime_postgres import (
    _bind,
    _egress,
    _model,
    _post,
    _runtime,
    _text,
    _token,
)
from tests.postgres_fixtures import database_url
from tests.wsgi_client import Browser

PRIMARY = os.environ.get("LAB_BRAIN_LIVE_PRIMARY", "")
CRITIC = os.environ.get("LAB_BRAIN_LIVE_CRITIC", "") or PRIMARY
UTILITY = os.environ.get("LAB_BRAIN_LIVE_UTILITY", "") or PRIMARY
OLLAMA = os.environ.get("LAB_BRAIN_LIVE_OLLAMA", "http://127.0.0.1:11434/v1")
DEADLINE = float(os.environ.get("LAB_BRAIN_LIVE_DEADLINE", "1800"))
EVIDENCE = os.environ.get("LAB_BRAIN_LIVE_EVIDENCE", "")
EXTERNAL = os.environ.get("LAB_BRAIN_LIVE_PRIMARY_PROVIDER", "")
KEY_ENV = os.environ.get("LAB_BRAIN_LIVE_PRIMARY_KEY_ENV", "")
FEATURES = os.environ.get("LAB_BRAIN_LIVE_FEATURES", "screening")
MATRIX_CASES = os.environ.get("LAB_BRAIN_LIVE_CASES", "")
PROTOCOL = json.loads(
    (Path(__file__).resolve().parents[2] / "benchmarks/g0_screening/protocol.json").read_text(
        encoding="utf-8"
    )
)

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(not PRIMARY, reason="set LAB_BRAIN_LIVE_PRIMARY to a local model to run"),
]

FIXTURE = json.loads(
    (
        Path(__file__).resolve().parents[2] / "fixtures/vertical/sp_rs_root_cause_benchmark.json"
    ).read_text(encoding="utf-8")
)
SIMULATIONS = [sp.CAP_MESH_SENSITIVITY, sp.CAP_CHARGE_DC, tools.CHARGE_AC_CAPABILITY]
CASES = {
    "sufficient": ("contact-open-via", {}),
    "insufficient": ("probe-artifact", {}),
    "competing": ("contact-open-via", {"extraction_normalization_length_um": "1000"}),
}


def _workspace(tmp_path: Path, deployment: Any = None) -> Browser:
    config = PROTOCOL["configurations"][FEATURES]
    return Browser(
        Workspace(
            actor_id="act:rkuo",
            settings=Settings(dsn=database_url()),
            connect=lambda s: psycopg.connect(s.dsn),
            artifact_root=tmp_path / "artifacts",
            vertical_factory=deployment or load_vertical_factory("silicon_photonics"),
            research_features=ResearchFeatures(
                exploratory_screening=config["exploratory_screening"],
                structure_context=config["structure_context"],
            ),
            allowed_hosts=allowed_hosts("127.0.0.1", 8765),
            secrets=SecretStore(environ={KEY_ENV: os.environ[KEY_ENV]} if KEY_ENV else {}),
            ollama_url=OLLAMA,
            inference_deadline=DEADLINE,
        )
    )


def _write(name: str, content: str) -> None:
    if EVIDENCE:
        Path(EVIDENCE).mkdir(parents=True, exist_ok=True)
        (Path(EVIDENCE) / name).write_text(content, encoding="utf-8")


def _rows(db: Any, sql: str, *args: object) -> list[dict[str, Any]]:
    cursor = db.execute(sql, args)
    names = [c.name for c in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _said(markup: str) -> str:
    """What a refusal page says, without its frame."""
    return _text(markup.split("<main>", 1)[-1].split("</main>", 1)[0])[:400]


def _qualified(db: Any, browser: Browser) -> dict[str, str]:
    """The named models tested (all eight probes) and locked through the pages, bound to the
    slots and activated -- or the test fails with what refused them."""
    added = _post(browser, "/settings/llm/connections", {"provider": "ollama", "name": "local"})
    assert added.status == 303, _text(added)[:600]
    (connection,) = db.execute(
        "SELECT connection_id FROM llm_connections WHERE name = 'local'"
    ).fetchone()
    assert _post(browser, f"/settings/llm/connections/{connection}/fetch", {}).status == 303
    where = dict.fromkeys((PRIMARY, CRITIC, UTILITY), connection)
    if EXTERNAL:
        assert KEY_ENV in os.environ, f"{KEY_ENV} is not set: the owner sets the key there"
        added = _post(
            browser,
            "/settings/llm/connections",
            {"provider": EXTERNAL, "name": "external", "env_name": KEY_ENV},
        )
        assert added.status == 303, _said(added.text)
        (external,) = db.execute(
            "SELECT connection_id FROM llm_connections WHERE name = 'external'"
        ).fetchone()
        assert _post(browser, f"/settings/llm/connections/{external}/fetch", {}).status == 303
        where[PRIMARY] = external
        # The disposable project declares its own egress, through its page, before any of its
        # evidence may reach the external connection.
        _egress(browser, db)
    ids: dict[str, str] = {}
    for name, held_by in where.items():
        ids[name] = _model(db, name, held_by)
        assert _post(browser, f"/settings/llm/models/{ids[name]}/test", {}).status == 303
        assert _post(browser, f"/settings/llm/models/{ids[name]}/lock", {}).status == 303
    probes = _rows(
        db,
        "SELECT m.model_name, p.capability, p.outcome, p.probe_version, p.latency_ms, p.detail"
        " FROM llm_capability_probes p JOIN llm_models m USING (model_profile_id)"
        " WHERE m.connection_id = ANY(%s) ORDER BY m.model_name, p.capability",
        sorted(set(where.values())),
    )
    _write("probes.json", json.dumps(probes, indent=1, ensure_ascii=False))
    runtime = _runtime(browser, "live acceptance")
    for slot, name in (
        ("REASONING_PRIMARY", PRIMARY),
        ("FAST_UTILITY", UTILITY),
        ("REASONING_ADVERSARIAL", CRITIC),
    ):
        bound = _bind(browser, runtime, slot, ids[name])
        if bound.status != 303:
            failed = [p for p in probes if p["model_name"] == name and p["outcome"] != "PASSED"]
            pytest.fail(
                f"BLOCKED: {slot} refuses {name}: {_said(bound.text)} -- probes not passed: "
                + json.dumps(failed, ensure_ascii=False)
            )
    activated = _post(browser, f"/settings/llm/runtimes/{runtime}/activate", {})
    assert activated.status == 303, _text(activated)[:600]
    return ids


def _device(tmp_path: Path, case_id: str, override: dict[str, str]) -> Path:
    case = next(c for c in FIXTURE["cases"] if c["case_id"] == case_id)
    path = tmp_path / f"{case_id}.device.json"
    path.write_text(json.dumps({**FIXTURE["nominal_device"], **case["device"], **override}))
    return path


def _episode(browser: Browser, tmp_path: Path, name: str) -> str:
    case_id, override = CASES[name]
    device = _device(tmp_path, case_id, override)
    started = browser.post(
        "/runs",
        {
            "csrf": _token(browser.get("/runs/new")),
            "project": PROJECT,
            "goal": GOAL,
            "sensitivity": "INTERNAL",
        },
        {
            "measurement": [(REPORT.name, REPORT.read_bytes())],
            "verification_input": [(device.name, device.read_bytes())],
        },
    )
    assert started.status == 303, _text(started)[:1200]
    found = re.search(r"/episodes/([^?#]+)", started.location)
    assert found
    from urllib.parse import unquote

    return unquote(found.group(1))


def _host(url: str | None) -> str:
    """How the spend ceiling names an endpoint: `host`, or `host:port` when the URL gives one."""
    from urllib.parse import urlsplit

    parts = urlsplit(url or "")
    host = (parts.hostname or "").lower()
    return f"{host}:{parts.port}" if parts.port else host


def test_a_real_model_researches_three_cases_without_lumerical(db, tmp_path, request):
    """Every case runs, whatever the one before it did; each is checked for what must hold of any
    run -- whose inferences these are, no simulation, no confirmation the record does not carry,
    a page that says what happened -- and the test then asks the acceptance question: did every
    case get through the debate to verification? Each case's outcome is written to the evidence
    either way."""
    _member(db)
    _admin(db)
    from tests.e2e.test_g0_screening_matrix_postgres import _Deployment, _run_splits, collect

    # The evaluation's cumulative cap, read before anything else: an external primary without one
    # is refused here, before the qualification probes make the first call.
    cap = cap_from_env(external=bool(EXTERNAL))
    # And the MONEY ceiling (`llm_runtime.spend`): an external primary without the Owner's ceiling
    # and unit prices is refused here too. With them, the budget and the primary's price are
    # declared in this (fresh) database and a REQUIRED guard is installed for the process: every
    # request to a host that is not this machine -- probes, research, retries, the schema
    # fallback -- is reserved at its worst case before it is sent, and anything unpriced refused.
    money = spend_from_env(external=bool(EXTERNAL))
    budget = None
    if money is not None:
        install_live_spend_guard(
            database_url(),
            money,
            endpoint_host=_host(PROVIDERS[EXTERNAL][0]),
            model=PRIMARY,
            actor_id="act:rkuo",
        )
        request.addfinalizer(lambda: spend.install(None))
        budget = money.budget_id

    def within_cap() -> None:
        check_before_episode(db, PRIMARY, cap)
        check_spend_before_episode(db, budget)

    deployment = _Deployment()
    browser = _workspace(tmp_path, deployment)
    within_cap()
    _qualified(db, browser)
    models = {PRIMARY, CRITIC, UTILITY}
    outcomes: dict[str, dict[str, Any]] = {}
    for name in CASES:
        within_cap()
        episode = _episode(browser, tmp_path, name)
        provenance = _rows(
            db,
            "SELECT inference_id, role, logical_slot, provider, model_id, model_version,"
            " prompt_id, prompt_version, created_at::text, parameters, output_text"
            " FROM inference_provenance"
            " WHERE project_id = %s AND trace_id = (SELECT trace_id FROM research_episodes"
            " WHERE episode_id = %s) ORDER BY created_at",
            PROJECT,
            episode,
        )
        _write(f"{name}.provenance.json", json.dumps(provenance, indent=1, ensure_ascii=False))
        assert provenance, "the run made no inference at all"
        assert {p["model_id"] for p in provenance} <= models, {p["model_id"] for p in provenance}
        assert not db.execute(
            "SELECT 1 FROM jobs WHERE project_id = %s AND capability_id = ANY(%s)",
            (PROJECT, SIMULATIONS),
        ).fetchone(), "no simulation is run, and none is emulated"
        state, outcome = db.execute(
            "SELECT state, outcome_status FROM research_episodes WHERE episode_id = %s", (episode,)
        ).fetchone()
        if (outcome or "").startswith("CONFIRMED:"):
            assert name == "sufficient", (name, outcome)
            declared = db.execute(
                "SELECT p.observable_ref, p.expected_outcome FROM predictions p"
                " WHERE p.hypothesis_id = %s",
                (outcome.removeprefix("CONFIRMED:"),),
            ).fetchall()
            assert ("sp.contact_connectivity", "DISCONTINUOUS") in {tuple(r) for r in declared}
        (recorded,) = SqlResearchReportStore(db).for_episode(project_id=PROJECT, episode_id=episode)
        report = recorded.report
        browser.post("/locale", {"csrf": _token(browser.get("/")), "locale": "zh-TW", "next": "/"})
        page = browser.get(f"/episodes/{episode}").text
        _write(f"{name}.zh-TW.html", page)
        _write(
            f"{name}.summary.zh-TW.html",
            browser.get(f"/episodes/{episode}/runs/1/summary.html").text,
        )
        browser.post("/locale", {"csrf": _token(browser.get("/")), "locale": "en", "next": "/"})
        # The page says what happened: who reasoned, once a debate exists; where it stopped, if
        # it stopped before one.
        if report.debate is not None:
            assert "假說與反方審查由語言模型產生" in _text(page) and PRIMARY in _text(page)
        else:
            assert "研究停在" in _text(page)
        outcomes[name] = {
            "episode": episode,
            "state": state,
            "outcome": outcome,
            "conclusion": report.conclusion.status,
            "stages": [[x.stage, x.status, x.detail] for x in report.stages],
            "hypotheses": [[x.mechanism, x.final_state] for x in report.hypotheses],
            "inferences": [[p["role"], p["logical_slot"], p["model_id"]] for p in provenance],
            "executed": sorted(
                r[0]
                for r in db.execute(
                    "SELECT DISTINCT j.capability_id FROM jobs j JOIN runs u ON u.job_id = j.job_id"
                    " WHERE j.episode_id = %s AND u.status = 'SUCCEEDED'",
                    (episode,),
                ).fetchall()
            ),
            "predictions": [
                list(r)
                for r in db.execute(
                    "SELECT h.mechanism, p.observable_ref, p.expected_outcome,"
                    " p.relation_effect_if_observed -> 0 ->> 'relation_type'"
                    " FROM predictions p JOIN hypotheses h USING (hypothesis_id)"
                    " WHERE h.created_in_episode = %s ORDER BY 1, 2, 3",
                    (episode,),
                ).fetchall()
            ],
            "confirmed": (outcome or "").removeprefix("CONFIRMED:")
            if (outcome or "").startswith("CONFIRMED:")
            else None,
            "reliability": dataclasses.asdict(report.debate.reliability)
            if report.debate is not None and report.debate.reliability is not None
            else None,
            "usage": [dataclasses.asdict(u) for u in report.usage],
            "features": FEATURES,
            "screening": dataclasses.asdict(report.screening)
            if report.screening is not None
            else None,
            "record": collect(db, episode),
        }
    _write("outcomes.json", json.dumps(outcomes, indent=1, ensure_ascii=False))
    if MATRIX_CASES:
        splits = ("dev", "holdout") if MATRIX_CASES == "matrix" else (MATRIX_CASES,)
        records = _run_splits(db, browser, deployment, None, splits, before_each=within_cap)
        _write(
            "matrix.outputs.json",
            json.dumps({"configurations": {FEATURES: records}}, indent=1, ensure_ascii=False),
        )
    stopped = {
        name: next(
            (
                f"{stage} {status}: {detail}"
                for stage, status, detail in o["stages"]
                if status in ("FAILED", "REFUSED")
            ),
            None,
        )
        for name, o in outcomes.items()
    }
    reached = {
        name
        for name, o in outcomes.items()
        if any(
            stage == "verification" and status in ("DONE", "PARTIAL")
            for stage, status, _ in o["stages"]
        )
    }
    assert reached == set(CASES), (
        "the pipeline did not reach verification in every case: "
        + json.dumps({n: stopped[n] for n in CASES if n not in reached}, ensure_ascii=False)
    )
