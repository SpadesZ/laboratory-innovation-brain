"""The research pipeline with a REAL language model and no Lumerical: the live acceptance check.

SKIPPED UNLESS ASKED FOR. It runs only when `LAB_BRAIN_LIVE_PRIMARY` names a model this machine's
Ollama serves (`LAB_BRAIN_LIVE_OLLAMA`, default http://127.0.0.1:11434/v1), with
`LAB_BRAIN_LIVE_CRITIC` and `LAB_BRAIN_LIVE_UTILITY` for the other slots (each defaults to the
primary). Local only: no credential, no egress, no cost. Nothing is stubbed -- every capability
probe and every research call goes to the named model, and a run takes as long as the model does
(`LAB_BRAIN_LIVE_DEADLINE`, seconds per inference, default 1800).

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
                   models' outputs, and each episode's zh-TW page and summary are written there
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import psycopg
import pytest

from lab_brain.domains.silicon_photonics import tools
from lab_brain.domains.silicon_photonics import vertical as sp
from lab_brain.interfaces.config import Settings
from lab_brain.interfaces.web import Workspace, allowed_hosts
from lab_brain.llm_runtime.secrets import SecretStore
from lab_brain.research.vertical import load_vertical_factory
from tests.e2e.test_research_episode_postgres import GOAL, PROJECT, REPORT, _member
from tests.e2e.test_web_llm_credentials_postgres import _admin
from tests.e2e.test_web_llm_runtime_postgres import _bind, _model, _post, _runtime, _text, _token
from tests.postgres_fixtures import database_url
from tests.wsgi_client import Browser

PRIMARY = os.environ.get("LAB_BRAIN_LIVE_PRIMARY", "")
CRITIC = os.environ.get("LAB_BRAIN_LIVE_CRITIC", "") or PRIMARY
UTILITY = os.environ.get("LAB_BRAIN_LIVE_UTILITY", "") or PRIMARY
OLLAMA = os.environ.get("LAB_BRAIN_LIVE_OLLAMA", "http://127.0.0.1:11434/v1")
DEADLINE = float(os.environ.get("LAB_BRAIN_LIVE_DEADLINE", "1800"))
EVIDENCE = os.environ.get("LAB_BRAIN_LIVE_EVIDENCE", "")

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


def _workspace(tmp_path: Path) -> Browser:
    return Browser(
        Workspace(
            actor_id="act:rkuo",
            settings=Settings(dsn=database_url()),
            connect=lambda s: psycopg.connect(s.dsn),
            artifact_root=tmp_path / "artifacts",
            vertical_factory=load_vertical_factory("silicon_photonics"),
            allowed_hosts=allowed_hosts("127.0.0.1", 8765),
            secrets=SecretStore(environ={}),
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
    ids: dict[str, str] = {}
    for name in dict.fromkeys((PRIMARY, CRITIC, UTILITY)):
        ids[name] = _model(db, name, connection)
        assert _post(browser, f"/settings/llm/models/{ids[name]}/test", {}).status == 303
        assert _post(browser, f"/settings/llm/models/{ids[name]}/lock", {}).status == 303
    probes = _rows(
        db,
        "SELECT m.model_name, p.capability, p.outcome, p.probe_version, p.latency_ms, p.detail"
        " FROM llm_capability_probes p JOIN llm_models m USING (model_profile_id)"
        " WHERE m.connection_id = %s ORDER BY m.model_name, p.capability",
        connection,
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


def test_a_real_local_model_researches_three_cases_without_lumerical(db, tmp_path):
    _member(db)
    _admin(db)
    browser = _workspace(tmp_path)
    _qualified(db, browser)
    models = {PRIMARY, CRITIC, UTILITY}
    for name in CASES:
        episode = _episode(browser, tmp_path, name)
        provenance = _rows(
            db,
            "SELECT inference_id, role, logical_slot, provider, model_id, model_version,"
            " prompt_id, prompt_version, created_at::text, output_text FROM inference_provenance"
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
        _, outcome = db.execute(
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
        browser.post("/locale", {"csrf": _token(browser.get("/")), "locale": "zh-TW", "next": "/"})
        page = browser.get(f"/episodes/{episode}").text
        _write(f"{name}.zh-TW.html", page)
        _write(
            f"{name}.summary.zh-TW.html",
            browser.get(f"/episodes/{episode}/runs/1/summary.html").text,
        )
        assert "假說與反方審查由語言模型產生" in _text(page)
        assert PRIMARY in _text(page)
        browser.post("/locale", {"csrf": _token(browser.get("/")), "locale": "en", "next": "/"})
