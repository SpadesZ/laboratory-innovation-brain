"""Acceptance without Lumerical: a researcher's whole journey through the workspace with accounts.

THE REASONER HERE IS THE PACK'S RULE-BASED CATALOG REASONER, NOT A LANGUAGE MODEL. No model route
is applied; the run's inference provenance says so, and the page and the summary say it from
there. What a language model changes -- who proposes the hypotheses and the critique -- is not
tested here. Everything after the proposal is: the checks that can run here run, the ones that
cannot are named as unknown and never emulated, the governed path moves beliefs, and the page and
the summary say what the record holds, in Traditional Chinese and in English.

    journey       an administrator opens the project for its owner; the owner adds a measurement
                  report as research data, opens research on it with a device project, reads the
                  result in both languages and exports its summary
    sufficient    an open via: the connectivity check observes the contact discontinuity's
                  signature, and the cause is confirmed -- with the rivals never tested named as a
                  limitation, and no simulation job anywhere
    insufficient  a sound design: two rivals refuted, three open; the simulations that cannot run
                  are named unknown and unverified, and nothing is confirmed
    competing     an open via and the taper-inclusive normalization length: two rivals each
                  supported by an observation of their own; nothing is confirmed, and the page
                  says the evidence does not single out one cause
    record        the summary names the SHA-256 of the record's export, which is report.md byte
                  for byte; after a continuation, run 1 reads exactly as before and run 2 shows
                  its checks as earlier ones
    isolation     the summary is the opener's, like the report: anyone else is told nothing
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import pytest

from lab_brain.cognition.catalog_reasoner import PROVIDER as CATALOG_PROVIDER
from lab_brain.domains.silicon_photonics import tools
from lab_brain.domains.silicon_photonics import vertical as sp
from tests.account_fixtures import Lab
from tests.e2e.test_research_episode_postgres import GOAL, REPORT
from tests.e2e.test_web_accounts_postgres import _browser, _csrf, _sign_in
from tests.e2e.test_web_research_data_postgres import _artifact, _hidden, _text
from tests.wsgi_client import Browser

pytestmark = pytest.mark.postgres

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = json.loads(
    (ROOT / "fixtures/vertical/sp_rs_root_cause_benchmark.json").read_text(encoding="utf-8")
)
SIMULATIONS = [sp.CAP_MESH_SENSITIVITY, sp.CAP_CHARGE_DC, tools.CHARGE_AC_CAPABILITY]
OWNER = "ada@uni.example.edu"


@dataclass
class Lab2:
    lab: Lab
    owner: Browser
    outsider: Browser
    project: str


@pytest.fixture
def journey(db: Any, tmp_path: Path) -> Lab2:
    lab = Lab(db)
    admin = lab.admin()
    lab.member(OWNER, "Ada", admin=admin)
    lab.member("bob@gmail.example", "Bob", admin=admin)
    administrator, owner, outsider = (_browser(tmp_path, lab.mail) for _ in range(3))
    _sign_in(administrator, "owner@lab.example")
    _sign_in(owner, OWNER)
    _sign_in(outsider, "bob@gmail.example")
    created = administrator.post(
        "/projects",
        {
            "csrf": _csrf(administrator.get("/projects")),
            "name": "Rs anomaly",
            "owner": OWNER,
            "clearance": ["INTERNAL", "PUBLIC"],
        },
    )
    assert created.status == 303, created.text[:600]
    project = unquote(created.location.split("/projects/", 1)[1].split("?", 1)[0])
    return Lab2(lab, owner, outsider, project)


def _device(case_id: str, **override: str) -> bytes:
    case = next(c for c in FIXTURE["cases"] if c["case_id"] == case_id)
    return json.dumps({**FIXTURE["nominal_device"], **case["device"], **override}).encode()


def _research(j: Lab2, db: Any, device: bytes) -> str:
    """Add the measurement report as research data, then open research on it -- and check the
    run admitted its evidence from that very artifact."""
    imported = j.owner.post(
        "/data",
        {
            "csrf": _csrf(j.owner.get(f"/data?project={j.project}")),
            "project": j.project,
            "kind": "measurement",
            "sensitivity": "INTERNAL",
        },
        {"files": [(REPORT.name, REPORT.read_bytes())]},
    )
    assert imported.status == 303, imported.text[:600]
    (item,) = unquote(re.search(r"added=([^&#]+)", imported.location).group(1)).split(",")
    artifact = _artifact(db, item)
    assert REPORT.name in j.owner.get(f"/data?project={j.project}").text
    review = j.owner.post(
        "/runs/review",
        {
            "csrf": _csrf(j.owner.get(f"/runs/new?project={j.project}")),
            "project": j.project,
            "goal": GOAL,
            "sensitivity": "INTERNAL",
            "use": [artifact],
            f"kind:{artifact}": "measurement",
        },
        {"verification_input": [("device.json", device)]},
    )
    assert review.status == 200, review.text[:2000]
    started = j.owner.post("/runs", _hidden(review))
    assert started.status == 303, started.text[:2000]
    episode = unquote(started.location.rsplit("/", 1)[1].split("?", 1)[0])
    assert _one(
        db,
        "SELECT count(*) FROM attestations WHERE project_id = %s AND source_artifact_id = %s",
        j.project,
        artifact,
    )[0], "the evidence is traceable to the research data it came from"
    return episode


def _in(browser: Browser, locale: str, path: str) -> str:
    browser.post("/locale", {"csrf": _csrf(browser.get("/")), "locale": locale, "next": "/"})
    page = browser.get(path)
    assert page.status == 200, page.text[:600]
    return page.text


def _section(markup: str, key: str) -> str:
    found = re.search(rf'<section id="v-{key}" class="view">.*?</section>', markup, flags=re.S)
    assert found is not None, key
    return _text(found.group(0))


def _one(db: Any, sql: str, *args: object) -> Any:
    return db.execute(sql, args).fetchone()


def _no_simulation_and_no_model(db: Any, j: Lab2, episode: str) -> None:
    assert (
        _one(
            db,
            "SELECT count(*) FROM jobs WHERE project_id = %s AND capability_id = ANY(%s)",
            j.project,
            SIMULATIONS,
        )[0]
        == 0
    ), "no simulation was run, and none was emulated"
    providers = {
        r[0]
        for r in db.execute(
            "SELECT DISTINCT provider FROM inference_provenance WHERE project_id = %s",
            (j.project,),
        ).fetchall()
    }
    assert providers == {CATALOG_PROVIDER}, providers


def test_sufficient_evidence_confirms_from_a_signature_and_names_what_was_never_tested(db, journey):
    j = journey
    episode = _research(j, db, _device("contact-open-via"))
    state, outcome = _one(
        db, "SELECT state, outcome_status FROM research_episodes WHERE episode_id = %s", episode
    )
    assert state == "COMPLETED" and outcome.startswith("CONFIRMED:")
    _no_simulation_and_no_model(db, j, episode)

    zh = _in(j.owner, "zh-TW", f"/episodes/{episode}")
    result = _section(zh, "result")
    assert (
        "已確認的發現 已確認 根本原因：存取區接點不連續（access contact discontinuity）" in result
    )
    why = _section(zh, "why")
    assert why.startswith("為什麼能（或不能）下結論 系統可以下結論：")
    assert (
        "支持的觀察：接點連通性檢查（connectivity inspection）：觀察到 接點連通性（contact"
        " connectivity） = 不連續（discontinuous）" in why
    )
    assert "此確認依據 1 項已記錄的診斷依據（diagnostic warrant），且可驗證" in why
    assert "已被觀察排除的對立假說：長度正規化錯誤（length normalization error）" in why
    assert "限制：本研究從未檢驗的對立假說：" in why
    assert "網格收斂假象（mesh convergence artifact）" in why.split("限制：", 1)[1]
    assert "假說與反方審查來自本機的規則式目錄推理器，沒有使用語言模型。" in why
    assert "未翻譯" not in _text(zh.split('<details id="v-reasoning"', 1)[0])
    reasoning = zh.split('<details id="v-reasoning"', 1)[1].split('<details id="v-audit"', 1)[0]
    assert REPORT.name in _text(reasoning), "each excerpt names the document it came from"

    en = _in(j.owner, "en", f"/episodes/{episode}")
    assert "Confirmed finding Confirmed Root cause: access contact discontinuity" in _section(
        en, "result"
    )
    assert "a limitation -- rivals never tested in this research:" in _section(en, "why")


def test_insufficient_evidence_confirms_nothing_and_names_every_check_that_never_ran(db, journey):
    j = journey
    episode = _research(j, db, _device("probe-artifact"))
    state, outcome = _one(
        db, "SELECT state, outcome_status FROM research_episodes WHERE episode_id = %s", episode
    )
    assert state == "SUSPENDED" and not (outcome or "").startswith("CONFIRMED")
    _no_simulation_and_no_model(db, j, episode)

    zh = _in(j.owner, "zh-TW", f"/episodes/{episode}")
    assert "已確認的發現" not in _text(zh.split('<details id="v-reasoning"', 1)[0])
    result = _section(zh, "result")
    assert "尚未確認 問題仍待解答。" in result
    assert (
        "已排除： 存取區接點不連續（access contact discontinuity）、長度正規化錯誤（length"
        " normalization error）" in result
    )
    why = _section(zh, "why")
    assert "系統目前還不能下結論" in why and "仍有 3 個假說尚未判定" in why
    assert (
        "以下檢查沒有執行，結果未知、未經驗證，也沒有以任何假設值代替："
        "網格敏感度模擬（mesh sensitivity）（模擬）、CHARGE 直流掃描模擬（DC sweep）（模擬）" in why
    )
    nxt = _section(zh, "next")
    assert "最佳的下一項檢查：網格敏感度模擬（mesh sensitivity）（模擬）。" in nxt
    assert "這裡無法執行：這個部署沒有接上任何模擬後端" in nxt
    assert "若 網格收斂穩定性（mesh stability） = 不穩定（unstable）" in nxt


def test_competing_evidence_supports_two_rivals_and_confirms_neither(db, journey):
    j = journey
    episode = _research(
        j, db, _device("contact-open-via", extraction_normalization_length_um="1000")
    )
    _, outcome = _one(
        db, "SELECT state, outcome_status FROM research_episodes WHERE episode_id = %s", episode
    )
    assert not (outcome or "").startswith("CONFIRMED")
    supported = {
        r[0]
        for r in db.execute(
            "SELECT h.mechanism FROM hypotheses h JOIN belief_revision_events b"
            " ON b.target_id = h.hypothesis_id"
            " WHERE h.created_in_episode = %s AND b.to_state = 'SUPPORTED'",
            (episode,),
        ).fetchall()
    }
    assert {"access contact discontinuity", "length normalization error"} <= supported
    _no_simulation_and_no_model(db, j, episode)

    zh = _in(j.owner, "zh-TW", f"/episodes/{episode}")
    result = _section(zh, "result")
    assert (
        "已獲支持： 存取區接點不連續（access contact discontinuity）、長度正規化錯誤（length"
        " normalization error）" in result
    )
    assert "已確認的發現" not in result
    why = _section(zh, "why")
    assert (
        "2 個對立假說各自獲得自己的觀察支持：存取區接點不連續（access contact discontinuity）、"
        "長度正規化錯誤（length normalization error）——證據無法指出單一原因" in why
    )
    assert "支持就不等於確認" in why
    en = _section(_in(j.owner, "en", f"/episodes/{episode}"), "why")
    assert "the evidence does not single out one cause" in en


def test_the_summary_names_its_source_and_a_continuation_leaves_run_one_as_it_was(db, journey):
    j = journey
    episode = _research(j, db, _device("probe-artifact"))
    summary = j.owner.get(f"/episodes/{episode}/runs/1/summary.html")
    assert summary.status == 200
    assert summary.headers["Content-Type"].startswith("text/html")
    record = j.owner.get(f"/episodes/{episode}/runs/1/report.md")
    digest = "sha256:" + hashlib.sha256(record.body).hexdigest()
    assert digest in summary.text, "the summary names the record it was derived from"
    assert "<form" not in summary.text
    zh_summary = _in(j.owner, "zh-TW", f"/episodes/{episode}/runs/1/summary.html")
    assert '<html lang="zh-TW">' in zh_summary and "研究摘要（衍生文件）" in zh_summary
    assert digest in zh_summary, "the same record, whichever language it is read in"

    stored = db.execute(
        "SELECT p.report::text FROM research_run_reports p JOIN research_runs r"
        " USING (research_run_id) WHERE r.episode_id = %s AND r.ordinal = 1",
        (episode,),
    ).fetchone()[0]
    before = _in(j.owner, "zh-TW", f"/episodes/{episode}?run=1")
    continued = j.owner.post(
        f"/episodes/{episode}/continue", {"csrf": _csrf(j.owner.get(f"/episodes/{episode}"))}
    )
    assert continued.status == 303, continued.text[:800]
    after = _in(j.owner, "zh-TW", f"/episodes/{episode}?run=1")
    for key in ("hypotheses", "tested", "support", "why"):
        assert _section(after, key) == _section(before, key), key
    second = _in(j.owner, "zh-TW", f"/episodes/{episode}?run=2")
    assert "先前已執行、這次不再重複的檢查" in _section(second, "tested")
    assert "第 2 次執行是從上次停下的地方繼續，不是重新開始。" in _section(second, "result")
    assert j.owner.get(f"/episodes/{episode}/runs/1/report.md").body == record.body
    # Reading run 1 in both languages, exporting it and continuing changed no stored record of it.
    assert (
        db.execute(
            "SELECT p.report::text FROM research_run_reports p JOIN research_runs r"
            " USING (research_run_id) WHERE r.episode_id = %s AND r.ordinal = 1",
            (episode,),
        ).fetchone()[0]
        == stored
    )

    for path in (f"/episodes/{episode}", f"/episodes/{episode}/runs/1/summary.html"):
        refused = j.outsider.get(path)
        assert refused.status == 404, path
        assert GOAL not in refused.text
