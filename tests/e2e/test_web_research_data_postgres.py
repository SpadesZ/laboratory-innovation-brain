"""Research Data and the input-selection workflow, end to end on PostgreSQL, as a browser drives it.

    home -> Research data -> import (declared kind and label) -> READY / DUPLICATE / BLOCKED / FAILED
      -> New research -> choose existing data (+ new files, + external sources) -> confirm -> start
      -> research task and its report -- with no simulator

Driven exactly as a browser drives it: pages fetched, the form's CSRF token read from the page,
files uploaded as `multipart/form-data`, the confirmation page's own hidden fields sent back as the
browser would send them. What every page shows is checked against the rows the one authoritative
ingestion path wrote, and every refusal against the database it leaves behind.

Also here, because they are the same pages: the AI model settings still refuse anyone but the
deployment's LLM administrator and say, at every stage, what to do next; the primary Chinese
interface uses the agreed researcher vocabulary; the canonical identifiers stay in the technical
details; the English interface is complete.
"""

from __future__ import annotations

import base64
import html
import re
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import unquote

import psycopg
import pytest

from lab_brain.core.models.enums import SensitivityLabel, TrustClass
from lab_brain.core.scientific_read import ScientificReadRefused
from lab_brain.interfaces.config import Settings
from lab_brain.interfaces.web import Workspace, allowed_hosts
from lab_brain.llm_runtime.secrets import SecretStore
from lab_brain.research.data import LabelNotCleared, NewFile, ResearchData
from lab_brain.research.report_store import report_from_json
from lab_brain.research.service import ProjectData, ResearchEpisodeService, ResearchRequest
from lab_brain.research.vertical import load_vertical_factory
from lab_brain.storage.artifacts.local import LocalArtifactStore
from tests.e2e.test_research_episode_postgres import (
    ACTOR,
    CORPUS,
    GOAL,
    PROJECT,
    REPORT,
    SIMULATIONS,
    _device,
    _member,
)
from tests.fake_llm_provider import FakeProvider
from tests.postgres_fixtures import database_url
from tests.wsgi_client import Browser, Reply

pytestmark = pytest.mark.postgres

OTHER_PROJECT = "prj:mzi"
MALLORY = "act:mallory"
KEY = "sk-test-labbrain-0123456789abcdefghij"
QUERY = "series resistance contact normalization reverse bias"
NOTE = (
    b"# Meeting note\n\nThe contact anneal on split B was shortened by 30 s compared with split "
    b"A. A shorter anneal is known to raise specific contact resistivity on p-type silicon.\n"
)
MZI_NOTE = (
    b"# MZI drift\n\nThe heater drift of the MZI arm follows the substrate temperature with a "
    b"lag of about four seconds after each power step.\n"
)
SECRET = (
    b"Probe station notes\n\n-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA1c2VjcmV0c2Vj\n"
    b"-----END RSA PRIVATE KEY-----\n"
)
BINARY = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0, 0, 0, 13, 0xFF, 0xFE, 0x00])

#: The agreed Traditional Chinese vocabulary replaced these; none may reach a primary page.
LEGACY_ZH = (
    "執行環境",
    "生命週期",
    "宣告模型",
    "已證實能力",
    "外送閘門",
    "受治理的轉移",
    "執行環境就緒狀態",
    "研究 episode",
    "續跑",
    "Slot 綁定",
)
#: English backend nouns a researcher should not meet on a Chinese page (outside the technical
#: details and the report's own stored text).
LEGACY_WORDS = re.compile(
    r"\b(project|projects|episode|episodes|run|runs|runtime|slot|slots|egress|lifecycle)\b",
    re.IGNORECASE,
)
CENSUS = (
    "artifacts",
    "artifact_occurrences",
    "evidence_units",
    "evidence_unit_occurrences",
    "ingestion_items",
    "research_data_declarations",
    "jobs",
    "research_episodes",
    "research_runs",
    "attestations",
)


# -- driving the workspace ------------------------------------------------------------------------


def _workspace(tmp_path: Path, actor: str = ACTOR, *, locale: str = "en") -> Browser:
    return Browser(
        Workspace(
            actor_id=actor,
            settings=Settings(dsn=database_url()),
            connect=lambda s: psycopg.connect(s.dsn),
            artifact_root=tmp_path / "artifacts",
            vertical_factory=load_vertical_factory("silicon_photonics"),
            allowed_hosts=allowed_hosts("127.0.0.1", 8765),
            secrets=SecretStore(environ={"FAKE_KEY": KEY}),
            default_locale=locale,
        )
    )


def _token(page: Reply) -> str:
    found = re.search(r'name="csrf" value="([^"]+)"', page.text)
    assert found, "the page carries no form token"
    return found.group(1)


def _text(page: Reply | str) -> str:
    markup = page.text if isinstance(page, Reply) else page
    inline = re.sub(r"</?(?:code|strong|span|a|time|label)\b[^>]*>", "", markup)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", inline)).split())


def _strip_details(markup: str) -> str:
    """Every Technical details / Advanced block, and every collapsed layer of the episode page,
    removed, nested ones included."""
    out, depth, skipping, i = [], 0, 0, 0
    for tag in re.finditer(r"<details\b[^>]*>|</details>", markup):
        opening = tag.group(0).startswith("<details")
        hidden = re.search(r'class="[^"]*\b(tech|advanced|layer)\b', tag.group(0))
        if not skipping and opening and hidden:
            out.append(markup[i : tag.start()])
            skipping, depth = 1, 1
            continue
        if skipping:
            depth += 1 if opening else -1
            if depth == 0:
                skipping, i = 0, tag.end()
    if not skipping:
        out.append(markup[i:])
    return "".join(out)


def _visible(page: Reply | str) -> str:
    """What a reader sees at first: no technical details or advanced settings, no stored report
    text, no page furniture that names a language by its own name."""
    markup = page.text if isinstance(page, Reply) else page
    markup = re.sub(r"<head>.*?</head>", "", markup, flags=re.S)
    markup = _strip_details(markup)
    markup = re.sub(r'<section class="report">.*?</section>', "", markup, flags=re.S)
    markup = re.sub(r'<form method="post" action="/locale">.*?</form>', "", markup, flags=re.S)
    return _text(markup)


def _details(page: Reply) -> str:
    return " ".join(re.findall(r"<details.*?</details>", page.text, flags=re.S))


def _census(db) -> dict[str, int]:  # type: ignore[no-untyped-def]
    return {t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in CENSUS}


def _join(
    db, project: str, actor: str = ACTOR, clearance: tuple[str, ...] = ("PUBLIC", "INTERNAL")
) -> None:  # type: ignore[no-untyped-def]
    db.execute(
        "INSERT INTO projects (project_id, name) VALUES (%s, 'MZI thermal drift')"
        " ON CONFLICT DO NOTHING",
        (project,),
    )
    db.execute(
        "INSERT INTO project_memberships (actor_id, project_id, role, sensitivity_clearance,"
        " approval_scopes, active) VALUES (%s, %s, 'RESEARCHER', %s, ARRAY[]::text[], TRUE)",
        (actor, project, list(clearance)),
    )


def _import(
    browser: Browser,
    project: str,
    files: list[tuple[str, bytes]],
    *,
    kind: str | None = "measurement",
    sensitivity: str | None = "INTERNAL",
) -> Reply:
    fields = {"csrf": _token(browser.get(f"/data?project={project}")), "project": project}
    if kind is not None:
        fields["kind"] = kind
    if sensitivity is not None:
        fields["sensitivity"] = sensitivity
    return browser.post("/data", fields, {"files": files})


def _added(reply: Reply) -> list[str]:
    assert reply.status == 303, reply.text[:2000]
    found = re.search(r"added=([^&#]+)", reply.location)
    assert found
    return unquote(found.group(1)).split(",")


def _artifact(db, item_id: str) -> str:  # type: ignore[no-untyped-def]
    return str(
        db.execute(
            "SELECT raw_artifact_id FROM ingestion_items WHERE item_id = %s", (item_id,)
        ).fetchone()[0]
    )


def _hidden(page: Reply) -> dict[str, list[str]]:
    """The confirmation's own hidden fields, as a browser sends them back."""
    fields: dict[str, list[str]] = {}
    for name, value in re.findall(
        r'<input type="hidden" name="([^"]+)" value="([^"]*)">', page.text
    ):
        fields.setdefault(html.unescape(name), []).append(html.unescape(value))
    return fields


def _stored(db, episode_id: str) -> list:  # type: ignore[no-untyped-def]
    rows = db.execute(
        "SELECT p.report FROM research_run_reports p JOIN research_runs r USING (research_run_id)"
        " WHERE p.episode_id = %s ORDER BY r.ordinal",
        (episode_id,),
    ).fetchall()
    return [report_from_json(r[0]) for r in rows]


# -- intake ---------------------------------------------------------------------------------------


def test_the_homepage_leads_a_researcher_to_research_data(db, tmp_path):
    _member(db)
    browser = _workspace(tmp_path)
    home = browser.get("/")
    assert home.status == 200
    assert '<a class="button" href="/data">＋ Import research data</a>' in home.text
    assert "Next: import research data into a project." in _text(home)
    zh = _workspace(tmp_path, locale="zh-TW").get("/")
    assert '<a class="button" href="/data">＋ 匯入研究資料</a>' in zh.text
    assert '<a href="/data" title="要把資料交給 Lab Brain，就是來這裡"' in zh.text
    page = browser.get("/data")
    assert page.status == 200 and 'action="/data" enctype="multipart/form-data"' in page.text
    form = re.search(r'<form method="post" action="/data".*?</form>', page.text, flags=re.S)
    assert form is not None
    assert " checked" not in form.group(0), "no kind and no label is chosen for the researcher"
    assert 'name="kind"' in form.group(0) and 'name="sensitivity"' in form.group(0)


def test_an_import_is_declared_authorized_and_goes_through_the_one_ingestion_path(db, tmp_path):
    _member(db)
    browser = _workspace(tmp_path)
    upload = [(REPORT.name, REPORT.read_bytes())]
    before = _census(db)

    no_kind = _import(browser, PROJECT, upload, kind=None)
    assert no_kind.status == 400 and "Choose what kind of material the files are." in _text(no_kind)
    no_label = _import(browser, PROJECT, upload, sensitivity=None)
    assert no_label.status == 400 and "Choose how sensitive the files are." in _text(no_label)
    guessed = _import(browser, PROJECT, upload, kind="INTERNAL_MEASUREMENT")
    assert guessed.status == 400, "only the three declared kinds, by their form value"
    too_high = _import(browser, PROJECT, upload, sensitivity="CONFIDENTIAL_LAB")
    assert too_high.status == 403
    assert "your access in this project does not include “Lab confidential”" in _text(too_high)
    assert "Nothing was stored." in _text(too_high)
    assert _census(db) == before, "a refused import writes nothing"

    sent = _import(browser, PROJECT, upload)
    (item_id,) = _added(sent)
    assert sent.location.startswith("/data?project=prj%3Aps-rs&added=")
    artifact = _artifact(db, item_id)
    # The one authoritative path: a job with no episode, the artifact, its occurrence under the
    # declared label, evidence units, the inbox item -- and the declaration beside it.
    assert db.execute(
        "SELECT capability_id, episode_id FROM jobs WHERE project_id = %s", (PROJECT,)
    ).fetchall() == [("cap:ingest_document", None)]
    assert db.execute(
        "SELECT sensitivity_label, ingested_by_actor_id FROM artifact_occurrences"
        " WHERE artifact_id = %s AND project_id = %s",
        (artifact, PROJECT),
    ).fetchone() == ("INTERNAL", ACTOR)
    units = db.execute(
        "SELECT count(*) FROM evidence_unit_occurrences WHERE artifact_id = %s", (artifact,)
    ).fetchone()[0]
    assert units > 0
    assert db.execute(
        "SELECT declared_kind, declared_label, file_name, actor_id FROM research_data_declarations"
        " WHERE item_id = %s",
        (item_id,),
    ).fetchone() == ("INTERNAL_MEASUREMENT", "INTERNAL", REPORT.name, ACTOR)

    page = browser.get(sent.location)
    shown = _text(page)
    assert "1 file(s) imported. How each was processed:" in shown
    assert f"{REPORT.name} Ready for research -- Nothing to do: pick it in New research." in shown
    assert f"{units} passage(s)" in shown
    # Reloading the result page shows it again; it never imports twice.
    assert browser.get(sent.location).status == 200
    assert _census(db)["ingestion_items"] == before["ingestion_items"] + 1


def test_nobody_outside_the_project_and_no_label_above_clearance_writes_anything(db, tmp_path):
    _member(db)
    _member(db, MALLORY, member=False)
    before = _census(db)
    mallory = _workspace(tmp_path, MALLORY)
    token = _token(mallory.get("/"))
    refused = mallory.post(
        "/data",
        {"csrf": token, "project": PROJECT, "kind": "note", "sensitivity": "PUBLIC"},
        {"files": [(REPORT.name, REPORT.read_bytes())]},
    )
    assert refused.status == 403 and f"No research for {MALLORY} in {PROJECT}." in _text(refused)
    # The service's own gate, below the page: authorization first and fatal.
    data = ResearchData(
        connection=db, artifact_store=LocalArtifactStore((tmp_path / "artifacts").resolve())
    )
    with pytest.raises(ScientificReadRefused):
        data.add(
            project_id=PROJECT,
            actor_id=MALLORY,
            files=[NewFile(REPORT.name, REPORT.read_bytes(), "text/markdown")],
            kind=TrustClass.EXPERT_HEURISTIC,
            sensitivity=SensitivityLabel.PUBLIC,
        )
    with pytest.raises(LabelNotCleared):
        data.add(
            project_id=PROJECT,
            actor_id=ACTOR,
            files=[NewFile(REPORT.name, REPORT.read_bytes(), "text/markdown")],
            kind=TrustClass.INTERNAL_MEASUREMENT,
            sensitivity=SensitivityLabel.RESTRICTED_NDA,
        )
    # A deactivated account keeps its membership row, clearance and all; the gate refuses the
    # account itself, before anything is written.
    db.execute("UPDATE actors SET active = FALSE WHERE actor_id = %s", (ACTOR,))
    with pytest.raises(ScientificReadRefused):
        data.add(
            project_id=PROJECT,
            actor_id=ACTOR,
            files=[NewFile(REPORT.name, REPORT.read_bytes(), "text/markdown")],
            kind=TrustClass.INTERNAL_MEASUREMENT,
            sensitivity=SensitivityLabel.INTERNAL,
        )
    assert _census(db) == before


def test_every_import_state_says_what_happened_and_what_to_do(db, tmp_path):
    _member(db)
    browser = _workspace(tmp_path)
    (first,) = _added(_import(browser, PROJECT, [(REPORT.name, REPORT.read_bytes())]))
    artifact = _artifact(db, first)
    units_before = _census(db)["evidence_units"]
    again = _import(
        browser,
        PROJECT,
        [
            ("rs_report_copy.md", REPORT.read_bytes()),
            ("probe_access.md", SECRET),
            ("cv_sweep.png", BINARY),
        ],
        kind="note",
        sensitivity="PUBLIC",
    )
    copy, blocked, failed = _added(again)
    # Duplicate bytes: the SAME artifact, no second identity, no new evidence -- and the label in
    # force is the first arrival's; what was declared this time is kept beside it.
    assert _artifact(db, copy) == artifact
    assert (
        db.execute("SELECT count(*) FROM artifacts WHERE artifact_id = %s", (artifact,)).fetchone()[
            0
        ]
        == 1
    )
    assert _census(db)["evidence_units"] == units_before
    assert (
        db.execute(
            "SELECT sensitivity_label FROM artifact_occurrences WHERE artifact_id = %s", (artifact,)
        ).fetchone()[0]
        == "INTERNAL"
    )
    assert db.execute(
        "SELECT declared_kind, declared_label FROM research_data_declarations WHERE item_id = %s",
        (copy,),
    ).fetchone() == ("EXPERT_HEURISTIC", "PUBLIC")
    # A credential is never stored; an unreadable file is stored and says why it failed.
    assert (
        db.execute(
            "SELECT raw_artifact_id FROM ingestion_items WHERE item_id = %s", (blocked,)
        ).fetchone()[0]
        is None
    )

    shown = _text(browser.get(again.location))
    assert "3 file(s) imported. How each was processed:" in shown
    assert (
        f"rs_report_copy.md Same content as an earlier file -- Identical to “{REPORT.name}”, "
        "so nothing was added twice. Use that one; it keeps its own classification (Lab "
        "internal)." in shown
    )
    assert "You declared Public this time, but content identity keeps" in shown
    assert "probe_access.md Stopped by a safety rule -- Stopped before it was stored" in shown
    assert "Why: This file was quarantined because it appears to contain a credential." in shown
    assert "cv_sweep.png Could not be processed -- The file could not be read." in shown
    zh = _text(_workspace(tmp_path, locale="zh-TW").get(f"/data?project={PROJECT}"))
    assert "已被安全規則擋下" in zh and "檔案看起來含有憑證" in zh
    assert "與既有檔案內容相同" in zh and "處理失敗" in zh and "可用於研究" in zh

    # A later duplicate declares nothing about the original: it is offered once, as first declared.
    new = browser.get(f"/runs/new?project={PROJECT}")
    assert new.text.count('name="use"') == 1
    assert re.search(
        rf'<select name="kind:{re.escape(artifact)}"[^>]*>(?:(?!</select>).)*'
        r'<option value="measurement" selected>',
        new.text,
        flags=re.S,
    ), "the original's declared kind, not the duplicate's"
    assert blocked not in new.text and failed not in new.text


# -- new research: choose, add, confirm, start ----------------------------------------------------


def test_new_research_uses_existing_data_adds_files_confirms_and_runs_without_a_simulator(
    db, tmp_path
):
    _member(db)
    _join(db, OTHER_PROJECT)
    browser = _workspace(tmp_path)
    (report_item,) = _added(_import(browser, PROJECT, [(REPORT.name, REPORT.read_bytes())]))
    (mzi_item,) = _added(_import(browser, OTHER_PROJECT, [("mzi_drift.md", MZI_NOTE)], kind="note"))
    report_artifact, mzi_artifact = _artifact(db, report_item), _artifact(db, mzi_item)

    # Another project's data never appears in this project's selector.
    new = browser.get(f"/runs/new?project={PROJECT}")
    assert report_artifact in new.text and mzi_artifact not in new.text
    assert f'<input type="hidden" name="project" value="{PROJECT}">' in new.text
    other = browser.get(f"/runs/new?project={OTHER_PROJECT}")
    assert mzi_artifact in other.text and report_artifact not in other.text

    device = _device(tmp_path, "mesh-coarse-access")
    before_confirm = _census(db)
    review = browser.post(
        "/runs/review",
        {
            "csrf": _token(new),
            "project": PROJECT,
            "goal": GOAL,
            "sensitivity": "INTERNAL",
            "symptom": "Rs about 50% higher on split B",
            "use": [report_artifact],
            f"kind:{report_artifact}": "measurement",
            "files_kind": "note",
            "files_sensitivity": "INTERNAL",
            "literature_query": QUERY,
            "literature_query_public": "yes",
        },
        {
            "files": [("anneal_note.md", NOTE), ("rs_report_again.md", REPORT.read_bytes())],
            "literature_corpus": [(CORPUS.name, CORPUS.read_bytes())],
            "verification_input": [(device.name, device.read_bytes())],
        },
    )
    assert review.status == 200, review.text[:3000]
    after_confirm = _census(db)
    # Confirming reasons nothing: no research task, no run. The new files were imported first,
    # through the same path; the re-uploaded report is the same artifact, once.
    assert after_confirm["research_episodes"] == after_confirm["research_runs"] == 0
    assert after_confirm["ingestion_items"] == before_confirm["ingestion_items"] + 2
    assert after_confirm["artifacts"] == before_confirm["artifacts"] + 1
    anneal_artifact = db.execute(
        "SELECT i.raw_artifact_id FROM ingestion_items i JOIN research_data_declarations d"
        " USING (item_id) WHERE d.file_name = 'anneal_note.md'"
    ).fetchone()[0]

    shown = _text(review)
    assert "This research will use" in shown
    assert f"Question {GOAL}" in shown and "Question classification Lab internal" in shown
    assert "Research project Rs anomaly" in shown and "Research data (2)" in shown
    assert f"{REPORT.name} -- Measurement report or lab record, Lab internal" in shown
    assert "your new file “rs_report_again.md” has the same content" in shown
    assert "anneal_note.md new -- Notes, ideas or literature excerpts, Lab internal" in shown
    assert f"Literature file “{CORPUS.name}”, searched with the public query “{QUERY}”" in shown
    assert f"Verification input {device.name} ({len(device.read_bytes())} bytes)" in shown
    assert "Symptom: Rs about 50% higher on split B" in shown
    assert "No simulator is connected to this deployment." in shown
    carried = _hidden(review)
    # Exactly what is shown is what is sent: these two artifacts, as these kinds; these bytes.
    assert sorted(carried["use"]) == sorted([report_artifact, anneal_artifact])
    assert carried[f"kind:{report_artifact}"] == ["measurement"]
    assert carried[f"kind:{anneal_artifact}"] == ["note"]
    assert base64.b64decode(carried["literature_corpus_b64"][0]) == CORPUS.read_bytes()
    assert base64.b64decode(carried["verification_b64"][0]) == device.read_bytes()
    assert carried["sensitivity"] == ["INTERNAL"] and carried["goal"] == [GOAL]

    ours = [report_artifact, anneal_artifact]
    units = "SELECT count(*) FROM evidence_unit_occurrences WHERE artifact_id = ANY(%s)"
    units_before = db.execute(units, (ours,)).fetchone()[0]
    started = browser.post("/runs", carried)
    assert started.status == 303, started.text[:3000]
    episode_id = started.location.rsplit("/", 1)[1]
    after_run = _census(db)
    # Selection copied nothing: no new ingestion item, no second artifact, no new unit or
    # occurrence of the data used. The run's admission (attestations) is the only new record of
    # it -- the one an uploaded document gets.
    assert after_run["ingestion_items"] == after_confirm["ingestion_items"]
    assert db.execute(units, (ours,)).fetchone()[0] == units_before
    assert (
        db.execute(
            "SELECT count(*) FROM artifacts WHERE artifact_id = ANY(%s)", (ours,)
        ).fetchone()[0]
        == 2
    )
    assert after_run["attestations"] > after_confirm["attestations"]
    cited = {
        r[0]
        for r in db.execute(
            "SELECT DISTINCT source_artifact_id FROM attestations WHERE project_id = %s"
            " AND source_artifact_id IS NOT NULL",
            (PROJECT,),
        ).fetchall()
    }
    assert {report_artifact, anneal_artifact} <= cited and mzi_artifact not in cited

    state, reason = db.execute(
        "SELECT state, suspend_reason FROM research_episodes WHERE episode_id = %s", (episode_id,)
    ).fetchone()
    assert state == "SUSPENDED" and "cap:sp.mesh_sensitivity" in reason
    assert (
        db.execute(
            "SELECT count(*) FROM jobs WHERE capability_id = ANY(%s)", (list(SIMULATIONS),)
        ).fetchone()[0]
        == 0
    ), "no simulator is needed, and none is run or emulated"
    (report,) = _stored(db, episode_id)
    inputs = {i.name: i for i in report.inputs}
    assert inputs[REPORT.name].role == "research data"
    assert inputs[REPORT.name].declared_kind == "INTERNAL_MEASUREMENT"
    assert inputs["anneal_note.md"].declared_kind == "EXPERT_HEURISTIC"
    assert "used as ingested, not ingested again" in (inputs[REPORT.name].detail or "")
    assert report.literature is not None and report.literature.query == QUERY

    page = browser.get(started.location)
    shown = _text(page)
    assert f"Research task {GOAL}" in shown
    assert "Status now: Waiting -- can be continued" in shown
    assert "waiting for a simulation that cannot run here (mesh sensitivity)" in shown
    assert "Run 1" in shown and "Paused, waiting (provisional conclusion)" in shown
    assert episode_id in _details(page), "the canonical id stays in the technical details"


def test_another_projects_data_is_refused_before_anything_is_written(db, tmp_path):
    _member(db)
    _join(db, OTHER_PROJECT)
    browser = _workspace(tmp_path)
    (mzi_item,) = _added(_import(browser, OTHER_PROJECT, [("mzi_drift.md", MZI_NOTE)], kind="note"))
    foreign = _artifact(db, mzi_item)
    before = _census(db)
    token = _token(browser.get(f"/runs/new?project={PROJECT}"))
    fields = {
        "csrf": token,
        "project": PROJECT,
        "goal": GOAL,
        "sensitivity": "INTERNAL",
        "use": [foreign],
        f"kind:{foreign}": "note",
    }
    confirm = browser.post("/runs/review", fields)
    assert confirm.status == 400
    assert f"“{foreign}” is not data this research may use in this project." in _text(confirm)
    start = browser.post("/runs", fields)
    assert start.status == 400
    assert _census(db) == before
    # Below the page: the research service authorizes every artifact a run would use.
    service = ResearchEpisodeService(
        connection=db,
        artifact_store=LocalArtifactStore((tmp_path / "artifacts").resolve()),
        vertical_factory=load_vertical_factory("silicon_photonics"),
    )
    with pytest.raises(ScientificReadRefused):
        service.run(
            ResearchRequest(
                project_id=PROJECT,
                actor_id=ACTOR,
                goal=GOAL,
                documents=(),
                project_data=(ProjectData(foreign, "mzi_drift.md", TrustClass.EXPERT_HEURISTIC),),
            )
        )
    assert _census(db) == before


def test_data_above_the_researchers_clearance_is_listed_but_never_offered(db, tmp_path):
    _member(db)
    browser = _workspace(tmp_path)
    (item,) = _added(_import(browser, PROJECT, [(REPORT.name, REPORT.read_bytes())]))
    artifact = _artifact(db, item)
    assert artifact in browser.get(f"/runs/new?project={PROJECT}").text
    db.execute(
        "UPDATE project_memberships SET sensitivity_clearance = ARRAY['PUBLIC']"
        " WHERE actor_id = %s AND project_id = %s",
        (ACTOR, PROJECT),
    )
    assert artifact not in browser.get(f"/runs/new?project={PROJECT}").text
    shown = _text(browser.get(f"/data?project={PROJECT}"))
    assert "Classified above your access in this project: listed, but you cannot use it." in shown
    token = _token(browser.get(f"/runs/new?project={PROJECT}"))
    refused = browser.post(
        "/runs",
        {
            "csrf": token,
            "project": PROJECT,
            "goal": GOAL,
            "sensitivity": "PUBLIC",
            "use": [artifact],
            f"kind:{artifact}": "measurement",
        },
    )
    assert refused.status == 400


def test_the_question_classification_is_declared_never_defaulted(db, tmp_path):
    _member(db)
    browser = _workspace(tmp_path)
    before = _census(db)
    token = _token(browser.get("/runs/new"))
    undeclared = browser.post(
        "/runs",
        {"csrf": token, "project": PROJECT, "goal": GOAL},
        {"measurement": [(REPORT.name, REPORT.read_bytes())]},
    )
    assert undeclared.status == 400 and "Choose how sensitive the question is." in _text(undeclared)
    confirm = browser.post("/runs/review", {"csrf": token, "project": PROJECT, "goal": GOAL})
    assert confirm.status == 400 and "Choose how sensitive the question is." in _text(confirm)
    new = browser.get("/runs/new")
    question = re.search(r'name="sensitivity".*?</fieldset>', new.text, flags=re.S)
    assert question is not None and " checked" not in question.group(0)
    assert _census(db) == before


def test_switching_project_keeps_what_was_typed_and_drops_what_was_ticked(db, tmp_path):
    _member(db)
    _join(db, OTHER_PROJECT)
    browser = _workspace(tmp_path)
    (item,) = _added(_import(browser, PROJECT, [(REPORT.name, REPORT.read_bytes())]))
    artifact = _artifact(db, item)
    page = browser.get(f"/runs/new?project={PROJECT}")
    switched = browser.post(
        "/runs/new",
        {
            "csrf": _token(page),
            "project": PROJECT,
            "switch_to": OTHER_PROJECT,
            "goal": "Why does the MZI drift?",
            "sensitivity": "PUBLIC",
            "use": [artifact],
            f"kind:{artifact}": "measurement",
        },
    )
    assert switched.status == 200
    assert f'name="project" value="{OTHER_PROJECT}"' in switched.text
    assert ">Why does the MZI drift?</textarea>" in switched.text
    assert 'name="sensitivity" value="PUBLIC" required checked' in switched.text
    assert artifact not in switched.text


# -- AI model settings: still administration, and always a next step -----------------------------


@pytest.fixture
def fake() -> Iterator[FakeProvider]:
    provider = FakeProvider(api_key=KEY).start()
    yield provider
    provider.stop()


def _admin(db) -> None:  # type: ignore[no-untyped-def]
    db.execute(
        "INSERT INTO llm_administrators (actor_id, granted_at, granted_through)"
        " VALUES (%s, now(), 'OPERATOR_CLI')",
        (ACTOR,),
    )


def _next(page: Reply) -> str:
    found = re.search(r'<div class="next"><strong>[^<]*</strong> ([^<]*)</div>', page.text)
    assert found, "the page says what to do next"
    return html.unescape(found.group(1))


def _todo(page: Reply) -> list[str]:
    table = re.search(r'<table class="checklist">.*?</table>', page.text, flags=re.S)
    if table is None:
        return []
    return [_text(row) for row in re.findall(r"<tr><td>.*?</tr>", table.group(0), flags=re.S)]


def test_ai_model_settings_stay_administration_only(db, tmp_path):
    _member(db)
    browser = _workspace(tmp_path)
    token = _token(browser.get("/"))
    before = {
        t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        for t in ("llm_connections", "llm_connection_health", "llm_runtimes", "llm_slot_bindings")
    }
    assert browser.get("/settings/llm").status == 403
    for path, fields in (
        ("/settings/llm/connections", {"provider": "ollama"}),
        ("/settings/llm/assign", {"slot": "REASONING_PRIMARY", "model": "llm:x"}),
        ("/status/check", {}),
    ):
        refused = browser.post(path, {"csrf": token, **fields})
        assert refused.status == 403, path
        assert "For the AI model administrator only" in _text(refused)
    after = {t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in before}
    assert after == before
    status = _text(browser.get("/status"))
    assert "Check the connections now" not in status


def test_every_incomplete_ai_model_state_names_the_next_step(db, tmp_path, fake):
    _member(db)
    _admin(db)
    browser = _workspace(tmp_path, locale="zh-TW")

    def post(path: str, fields: dict[str, str]) -> Reply:
        sent = browser.post(path, {"csrf": _token(browser.get("/settings/llm")), **fields})
        assert sent.status == 303, sent.text[:3000]
        return browser.get("/settings/llm")

    page = browser.get("/settings/llm")
    assert _next(page) == "新增模型連線（步驟 1）。"
    assert _todo(page) == [
        "尚未新增模型連線 在步驟 1 選擇模型服務，填入名稱與 API 金鑰（本機模型不需要金鑰），再按「＋ 新增」。"
    ]
    # The normal form: provider, name, API key (here from the workspace's environment), add.
    page = post(
        "/settings/llm/connections",
        {
            "provider": "custom",
            "name": "Fake Lab",
            "base_url": fake.base_url,
            "env_name": "FAKE_KEY",
        },
    )
    (connection_id,) = db.execute(
        "SELECT connection_id FROM llm_connections WHERE name = 'fake-lab'"
    ).fetchone()
    assert _next(page) == "取得「fake-lab」的可用模型。"
    page = post(f"/settings/llm/connections/{connection_id}/fetch", {"next": "/settings/llm"})
    assert _next(page) == "選一個「fake-lab」的模型，執行模型能力測試。"
    reasoner = db.execute(
        "SELECT model_profile_id FROM llm_models WHERE model_name = 'fake-reasoner'"
    ).fetchone()[0]
    page = post(
        f"/settings/llm/connections/{connection_id}/test",
        {"model_profile_id": reasoner, "next": "/settings/llm"},
    )
    assert _next(page) == "確認「fake-reasoner」這個模型。"
    assert "「fake-reasoner」已測試，還沒確認" in _todo(page)[0]
    page = post(f"/settings/llm/models/{reasoner}/lock", {"next": "/settings/llm"})
    assert _next(page) == "替「主要推理」指派模型（步驟 3）。"
    assert [row.split(" ")[0] for row in _todo(page)] == [
        "「主要推理」還沒有模型",
        "「快速處理」還沒有模型",
    ]
    assert "套用配置</button>" not in page.text, "nothing to apply yet"
    page = post("/settings/llm/assign", {"slot": "REASONING_PRIMARY", "model": reasoner})
    assert _next(page) == "替「快速處理」指派模型（步驟 3）。"
    assert "「獨立批判」沒有指派模型" in _text(page), "the fallback is a note, not hidden"
    page = post("/settings/llm/assign", {"slot": "FAST_UTILITY", "model": reasoner})
    (draft,) = db.execute(
        "SELECT runtime_id, name FROM llm_runtimes WHERE state = 'DRAFT'"
    ).fetchall()
    assert _next(page) == f"套用配置「{draft[1]}」（步驟 4）。"
    assert _todo(page) == [] and "沒有尚待處理的項目。" in _text(page)
    assert page.text.count(">套用配置</button>") == 1, "one obvious action"
    page = post(f"/settings/llm/runtimes/{draft[0]}/activate", {"next": "/settings/llm"})
    assert (
        db.execute("SELECT state FROM llm_runtimes WHERE runtime_id = %s", (draft[0],)).fetchone()[
            0
        ]
        == "ACTIVE"
    )
    assert _next(page).startswith("不需要處理：配置「")
    # The endpoint, the credential reference and the internal ids stay under the details.
    visible = _visible(page)
    assert (
        fake.base_url not in visible
        and "env:FAKE_KEY" not in visible
        and connection_id not in visible
    )
    assert (
        fake.base_url in page.text
        and "env:FAKE_KEY" in page.text
        and "REASONING_PRIMARY" in page.text
    )


# -- the language of the primary pages ------------------------------------------------------------


def _every_primary_page(browser: Browser, db, tmp_path: Path) -> dict[str, Reply]:  # type: ignore[no-untyped-def]
    (item,) = _added(_import(browser, PROJECT, [(REPORT.name, REPORT.read_bytes())]))
    artifact = _artifact(db, item)
    token = _token(browser.get("/runs/new"))
    fields = {
        "csrf": token,
        "project": PROJECT,
        "goal": GOAL,
        "sensitivity": "INTERNAL",
        "use": [artifact],
        f"kind:{artifact}": "measurement",
    }
    review = browser.post("/runs/review", fields)
    started = browser.post("/runs", _hidden(review))
    assert started.status == 303, started.text[:2000]
    return {
        "home": browser.get("/"),
        "data": browser.get(f"/data?project={PROJECT}"),
        "new": browser.get("/runs/new"),
        "review": review,
        "history": browser.get("/episodes"),
        "task": browser.get(started.location),
        "status": browser.get("/status"),
        "ai": browser.get("/settings/llm"),
        "configuration": browser.get("/runtime"),
        "transfer": browser.get(f"/projects/{PROJECT}/egress"),
    }


def test_the_primary_chinese_pages_speak_the_researchers_language(db, tmp_path):
    _member(db)
    _admin(db)
    browser = _workspace(tmp_path, locale="zh-TW")
    for name, page in _every_primary_page(browser, db, tmp_path).items():
        assert page.status == 200, name
        assert '<html lang="zh-TW">' in page.text, name
        for phrase in LEGACY_ZH:
            assert phrase not in page.text, (name, phrase)
        visible = _visible(page)
        leaked = LEGACY_WORDS.findall(visible)
        assert not leaked, (name, leaked)


def test_canonical_identifiers_stay_in_the_technical_details_and_the_rows(db, tmp_path):
    _member(db)
    browser = _workspace(tmp_path, locale="zh-TW")
    (item,) = _added(_import(browser, PROJECT, [(REPORT.name, REPORT.read_bytes())]))
    artifact = _artifact(db, item)
    page = browser.get(f"/data?project={PROJECT}")
    details = _details(page)
    for canonical in (item, artifact, "state=READY", "kind=INTERNAL_MEASUREMENT", "label=INTERNAL"):
        assert canonical in details, canonical
        assert canonical not in _visible(page), canonical
    assert 'title="READY"' in page.text, "the canonical state is the badge's tooltip"
    # Nothing was renamed where it is stored.
    assert db.execute(
        "SELECT declared_kind, declared_label FROM research_data_declarations"
    ).fetchone() == ("INTERNAL_MEASUREMENT", "INTERNAL")


def test_the_english_interface_is_complete(db, tmp_path):
    _member(db)
    _admin(db)
    browser = _workspace(tmp_path)
    for name, page in _every_primary_page(browser, db, tmp_path).items():
        assert page.status == 200, name
        cjk = re.findall(r"[㐀-鿿（）「」]+", _visible(page))
        assert not cjk, (name, cjk)
