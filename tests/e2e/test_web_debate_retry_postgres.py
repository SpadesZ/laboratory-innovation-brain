"""A debate cut off by the deployment's deadline is retried -- in the same episode -- on PostgreSQL.

The first local smoke's episode ended COMPLETED / NOT_REACHED because its Hypothesis Engine call
timed out: a failure before anything was reasoned, closed as if it were an answer, and no
continuation could start the missing debate. Driven through the web workspace as a researcher
would, with a stand-in model that is slow only for the Hypothesis Engine:

    the timeout          is TIMEOUT, not UNREACHABLE; the episode is SUSPENDED / NOT_REACHED with a
                         durable reason; the failed call left no InferenceProvenance and no set
    the retry            after the operator raises the deadline, continuing the SAME episode debates
                         over the statements run 1 admitted -- nothing ingested or admitted again --
                         records the episode's one hypothesis set, and verification proceeds
    one history          a further continuation reuses that set; the database refuses a second one
    one deadline         the web workspace holds capability probes and research calls to its
                         `--inference-deadline`; model discovery keeps its own short timeout
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import unquote

import psycopg
import pytest

import lab_brain.llm_runtime.runtime as runtime_module
from lab_brain.cognition.roles import HYPOTHESIS_ENGINE
from lab_brain.interfaces.config import Settings
from lab_brain.interfaces.web import Workspace, allowed_hosts
from lab_brain.llm_runtime.runtime import DISCOVERY_TIMEOUT_S
from lab_brain.llm_runtime.secrets import DirectoryCredentialStore, SecretStore
from lab_brain.research.vertical import load_vertical_factory
from tests.e2e.test_research_episode_postgres import ACTOR
from tests.e2e.test_web_llm_credentials_postgres import KEY, _connection, _post, _setup, _text
from tests.e2e.test_web_llm_runtime_postgres import _bind, _egress, _model, _research, _runtime
from tests.fake_llm_provider import FakeProvider
from tests.postgres_fixtures import database_url
from tests.wsgi_client import Browser

pytestmark = pytest.mark.postgres

TIMED_OUT = (
    "hypotheses FAILED ProviderError: TIMEOUT: the endpoint accepted the call and did not answer "
    "within 2 s"
)


@pytest.fixture
def fake() -> Iterator[FakeProvider]:
    provider = FakeProvider(api_key=KEY).start()
    yield provider
    provider.stop()


def _deployment(tmp_path: Path, *, inference_deadline: float) -> Browser:
    """The workspace as `lab-brain web --inference-deadline N` builds it."""
    return Browser(
        Workspace(
            actor_id=ACTOR,
            settings=Settings(dsn=database_url()),
            connect=lambda s: psycopg.connect(s.dsn),
            artifact_root=tmp_path / "artifacts",
            vertical_factory=load_vertical_factory("silicon_photonics"),
            allowed_hosts=allowed_hosts("127.0.0.1", 8765),
            secrets=SecretStore(
                environ={"FAKE_KEY": KEY},
                credentials=DirectoryCredentialStore(tmp_path / "credentials"),
            ),
            default_locale="en",
            ollama_url="http://127.0.0.1:9/v1",
            inference_deadline=inference_deadline,
        )
    )


def _activated(db, browser: Browser, fake: FakeProvider) -> str:  # type: ignore[no-untyped-def]
    """The stand-in added, tested, locked, bound and activated through the pages, with the
    project's egress declared. Returns the connection id."""
    added = _post(
        browser,
        "/settings/llm/connections",
        {
            "provider": "custom",
            "name": "fake",
            "base_url": fake.base_url,
            "reach": "EXTERNAL",
            "secret_value": KEY,
        },
    )
    assert added.status == 303, _text(added)[:400]
    connection_id = _connection(db, "fake")[0]
    assert _post(browser, f"/settings/llm/connections/{connection_id}/fetch", {}).status == 303
    ids = {}
    for name in ("fake-reasoner", "fake-critic"):
        ids[name] = _model(db, name, connection_id)
        assert _post(browser, f"/settings/llm/models/{ids[name]}/test", {}).status == 303
        assert _post(browser, f"/settings/llm/models/{ids[name]}/lock", {}).status == 303
    runtime_id = _runtime(browser, "retry runtime")
    for slot, model in (
        ("REASONING_PRIMARY", "fake-reasoner"),
        ("FAST_UTILITY", "fake-reasoner"),
        ("REASONING_ADVERSARIAL", "fake-critic"),
    ):
        assert _bind(browser, runtime_id, slot, ids[model]).status == 303
    activated = _post(browser, f"/settings/llm/runtimes/{runtime_id}/activate", {})
    assert activated.status == 303, _text(activated)[:400]
    _egress(browser, db)
    return connection_id


def _stage(page: str, stage: str) -> str:
    found = re.search(rf"\b{stage} (DONE|SKIPPED|FAILED|REFUSED|RESUMED|PARTIAL|SUSPENDED)\b", page)
    assert found, (stage, page[:2000])
    return found.group(1)


def _count(db, sql: str, *params: object) -> int:  # type: ignore[no-untyped-def]
    return int(db.execute(sql, params).fetchone()[0])


def test_a_timed_out_debate_suspends_and_the_same_episode_retries_it(db, tmp_path, fake):
    _setup(db)
    slow = _deployment(tmp_path, inference_deadline=2)
    _activated(db, slow, fake)

    # Run 1: the Hypothesis Engine needs 4 s; this deployment grants each call 2 s.
    fake.delay = lambda prompt, _system: (
        4.0 if prompt.startswith(HYPOTHESIS_ENGINE.prompt.template) else 0.0
    )
    opened = _research(slow, tmp_path)
    assert opened.status == 303, _text(opened)[:500]
    episode_id = unquote(opened.location.rsplit("/", 1)[1])
    first = _text(slow.get(opened.location))
    assert TIMED_OUT in first, first[:3000]
    assert "ProviderError: UNREACHABLE" not in first
    state, outcome, reason, trace_id = db.execute(
        "SELECT state, outcome_status, suspend_reason, trace_id FROM research_episodes"
        " WHERE episode_id = %s",
        (episode_id,),
    ).fetchone()
    assert state == "SUSPENDED" and outcome is None, (state, outcome)
    assert reason.startswith("the debate failed before a hypothesis set existed (ProviderError:")
    assert "TIMEOUT" in reason and reason.endswith("continue the episode to retry it")
    roles = {
        r[0]
        for r in db.execute(
            "SELECT role FROM inference_provenance WHERE trace_id = %s", (trace_id,)
        ).fetchall()
    }
    assert roles == {"EVIDENCE_RESEARCHER"}, "the timed-out call left no InferenceProvenance"
    assert _count(db, "SELECT count(*) FROM hypothesis_sets WHERE episode_id = %s", episode_id) == 0
    run_one = db.execute(
        "SELECT research_run_id FROM research_runs WHERE episode_id = %s AND ordinal = 1",
        (episode_id,),
    ).fetchone()[0]
    admitted = [
        r[0]
        for r in db.execute(
            "SELECT attestation_id FROM research_run_statements WHERE research_run_id = %s"
            " ORDER BY ordinal",
            (run_one,),
        ).fetchall()
    ]
    assert admitted, "run 1 recorded what it admitted, before it debated"
    document = db.execute(
        "SELECT source_artifact_id FROM attestations WHERE attestation_id = %s", (admitted[0],)
    ).fetchone()[0]
    ingested = _count(db, "SELECT count(*) FROM ingestion_items")
    attested = _count(
        db, "SELECT count(*) FROM attestations WHERE source_artifact_id = %s", document
    )

    # The operator raises the deadline; the researcher continues the SAME episode.
    fake.delay = None
    fixed = _deployment(tmp_path, inference_deadline=60)
    continued = _post(fixed, f"/episodes/{episode_id}/continue", {})
    assert continued.status == 303, _text(continued)[:500]
    assert unquote(continued.location.rsplit("/", 1)[1].split("?")[0]) == episode_id
    second = _text(fixed.get(f"/episodes/{episode_id}?run=2"))
    assert f"evidence RESUMED {len(admitted)} statement(s) admitted by run 1" in second, second[
        :3000
    ]
    assert _stage(second, "hypotheses") == "DONE"
    assert "the episode's first debate, retried" in second
    assert "the debate did not produce admitted hypotheses" not in second
    # The normal path from here: verification runs over the new set, and the episode parks on the
    # simulator this deployment does not have -- the vertical's own reason, not the timeout.
    assert _stage(second, "verification") == "DONE"

    # Nothing ingested or admitted again; one reasoning history, recorded by the run that debated.
    assert _count(db, "SELECT count(*) FROM ingestion_items") == ingested
    assert (
        _count(db, "SELECT count(*) FROM attestations WHERE source_artifact_id = %s", document)
        == attested
    )
    runs = db.execute(
        "SELECT ordinal, hypothesis_set_id FROM research_runs WHERE episode_id = %s"
        " ORDER BY ordinal",
        (episode_id,),
    ).fetchall()
    sets = [
        r[0]
        for r in db.execute(
            "SELECT set_id FROM hypothesis_sets WHERE episode_id = %s", (episode_id,)
        ).fetchall()
    ]
    assert len(sets) == 1 and runs[0] == (1, None) and runs[1] == (2, sets[0]), runs
    roles = {
        r[0]
        for r in db.execute(
            "SELECT role FROM inference_provenance WHERE trace_id = %s", (trace_id,)
        ).fetchall()
    }
    assert "HYPOTHESIS_ENGINE" in roles

    state, reason = db.execute(
        "SELECT state, suspend_reason FROM research_episodes WHERE episode_id = %s", (episode_id,)
    ).fetchone()
    assert state == "SUSPENDED" and reason.startswith("awaiting simulator"), (state, reason)

    # A further continuation reuses the recorded set and never debates again.
    again = _post(fixed, f"/episodes/{episode_id}/continue", {})
    assert again.status == 303, _text(again)[:500]
    third = _text(fixed.get(f"/episodes/{episode_id}?run=3"))
    assert _stage(third, "hypotheses") == "RESUMED"
    run_three = db.execute(
        "SELECT hypothesis_set_id FROM research_runs WHERE episode_id = %s AND ordinal = 3",
        (episode_id,),
    ).fetchone()[0]
    assert run_three == sets[0]
    assert _count(db, "SELECT count(*) FROM hypothesis_sets WHERE episode_id = %s", episode_id) == 1

    # The database holds the history whoever writes: a finished run's record is final, a second
    # hypothesis set in the episode is a parallel history, and what a run admitted is append-only.
    with pytest.raises(psycopg.errors.RaiseException, match="its record is final"):
        db.execute(
            "UPDATE research_runs SET hypothesis_set_id = NULL WHERE episode_id = %s"
            " AND ordinal = 2",
            (episode_id,),
        )
    with pytest.raises(psycopg.errors.RaiseException, match="parallel reasoning history"):
        db.execute(
            "INSERT INTO hypothesis_sets SELECT 'hset:second', project_id, episode_id, question,"
            " research_intent, stakes, root_cause, source_policy_id, source_policy_version,"
            " inverted_retrieval_required, created_at FROM hypothesis_sets WHERE set_id = %s",
            (sets[0],),
        )
    with pytest.raises(psycopg.errors.RaiseException, match="append-only"):
        db.execute("DELETE FROM research_run_statements WHERE research_run_id = %s", (run_one,))
    with pytest.raises(psycopg.errors.RaiseException, match="finished"):
        db.execute(
            "INSERT INTO research_run_statements (research_run_id, ordinal, attestation_id,"
            " trust_class, source_name, recorded_at) VALUES (%s, 999, %s, 'INTERNAL_MEASUREMENT',"
            " 'late.md', now())",
            (run_one, admitted[0]),
        )


def test_the_workspace_holds_probes_and_research_calls_to_its_one_deadline(
    db, tmp_path, fake, monkeypatch
):
    _setup(db)
    waited: list[float] = []
    real = runtime_module.OpenAICompatibleClient

    class Recording(real):  # type: ignore[misc, valid-type]
        def __init__(self, base_url: str, api_key: str | None, **kwargs: object) -> None:
            waited.append(float(kwargs.get("timeout", 0)))  # type: ignore[arg-type]
            super().__init__(base_url, api_key, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(runtime_module, "OpenAICompatibleClient", Recording)
    browser = _deployment(tmp_path, inference_deadline=37)
    _activated(db, browser, fake)
    sent = _research(browser, tmp_path)
    assert sent.status == 303, _text(sent)[:500]
    assert fake.research_calls(), "research reached the model"
    # Discovery and health: their own short timeout. Every probe and research call: 37 s.
    assert set(waited) == {DISCOVERY_TIMEOUT_S, 37.0}, waited
    assert waited.count(37.0) >= 3, "two models probed, and the active runtime's routes"
