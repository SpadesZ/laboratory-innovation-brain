"""Role qualification through the web workspace, on PostgreSQL.

The workspace's research asks for one competing hypothesis per mechanism its vertical catalogues
(5 for the silicon-photonics pack). Driven as an administrator would, with the stand-in model:

    the requirement     is read from the vertical; ROLE_HYPOTHESIS is probed at it and the evidence
                        records it; research names the lock and the Hypothesis Engine prompt in
                        force
    stale               after the qualification semantics change, research is refused before any
                        model call, the page says the confirmation predates the current test rules,
                        and no lock or InferenceProvenance is rewritten
    re-qualified        retiring the configuration, unlocking, testing and confirming again gives a
                        new route fingerprint; research uses it, and the earlier inferences keep
                        the one they were produced under
    unfit               a model qualified only at the generic floor (2) is refused for this research
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from unittest.mock import patch

import pytest

import lab_brain.llm_runtime.registry as registry_module
from lab_brain.cognition.roles import HYPOTHESIS_ENGINE
from lab_brain.core.models.inference import LogicalSlot
from lab_brain.domains.silicon_photonics.product import mechanism_catalog
from lab_brain.llm_runtime.runtime import LLMSettings
from lab_brain.llm_runtime.secrets import SecretStore
from tests.e2e.test_research_episode_postgres import ACTOR
from tests.e2e.test_web_debate_retry_postgres import _activated, _deployment
from tests.e2e.test_web_llm_credentials_postgres import KEY, _post, _setup, _text
from tests.e2e.test_web_llm_runtime_postgres import _bind, _model, _research, _runtime
from tests.fake_llm_provider import FakeProvider

pytestmark = pytest.mark.postgres


@pytest.fixture
def fake() -> Iterator[FakeProvider]:
    provider = FakeProvider(api_key=KEY).start()
    yield provider
    provider.stop()


def _provenance(db) -> list[tuple[str, str, str]]:  # type: ignore[no-untyped-def]
    return [
        (str(r[0]), str(r[1]), str(r[2]))
        for r in db.execute(
            "SELECT inference_id, model_version, prompt_version FROM inference_provenance"
            " WHERE role = 'HYPOTHESIS_ENGINE' ORDER BY inference_id"
        ).fetchall()
    ]


def test_the_web_qualifies_at_the_verticals_minimum_and_refuses_stale_locks(db, tmp_path, fake):
    _setup(db)
    required = len(mechanism_catalog().mechanisms)
    browser = _deployment(tmp_path, inference_deadline=60)
    connection_id = _activated(db, browser, fake)

    # The requirement is the vertical's, and the probe demonstrated exactly it.
    probes = [c for c in fake.calls if c.system and "CONTEXT.minimum_hypotheses" in c.system]
    assert probes and all(f'"minimum_hypotheses":{required}' in c.prompt for c in probes)
    reasoner = _model(db, "fake-reasoner", connection_id)
    assert (
        db.execute(
            "SELECT parameters FROM llm_capability_probes WHERE model_profile_id = %s"
            " AND capability = 'ROLE_HYPOTHESIS'",
            (reasoner,),
        ).fetchone()[0]["minimum_hypotheses"]
        == required
    )
    # The model page says what was demonstrated -- in its latest results and its test history.
    shown = browser.get(f"/settings/llm/models/{reasoner}")
    assert "&lt;span" not in shown.text, "a label is markup, never escaped text"
    assert _text(shown).count(f"(asked for at least {required} hypotheses)") == 2

    sent = _research(browser, tmp_path)
    assert sent.status == 303, _text(sent)[:500]
    before = _provenance(db)
    old_lock = db.execute(
        "SELECT lock_fingerprint FROM llm_models WHERE model_profile_id = %s", (reasoner,)
    ).fetchone()[0]
    prompt = HYPOTHESIS_ENGINE.prompt.prompt_version
    assert before and {(v, p) for _, v, p in before} == {(old_lock, prompt)}

    # The qualification semantics change: everything locked before is stale.
    with patch.object(registry_module, "QUALIFICATION_DIGEST", "f" * 64):
        calls = len(fake.calls)
        refused = _research(browser, tmp_path)
        assert refused.status == 409 and "no longer in force" in _text(refused)
        assert len(fake.calls) == calls, "refused before any model call"
        zh = _deployment(tmp_path, inference_deadline=60)
        assert _post(zh, "/locale", {"locale": "zh-TW"}).status in (200, 303)
        overview = _text(zh.get("/settings/llm"))
        assert "是在舊版測試規則下確認的" in overview, overview[:3000]
        page = _text(zh.get(f"/settings/llm/models/{reasoner}"))
        assert "這個確認是在舊版測試規則下完成的" in page
        assert _provenance(db) == before, "no inference is rewritten"
        assert (
            db.execute(
                "SELECT lock_fingerprint FROM llm_models WHERE model_profile_id = %s", (reasoner,)
            ).fetchone()[0]
            == old_lock
        ), "no lock is rewritten"

        # A new configuration is not offered the stale model; it says why.
        runtime_id = _runtime(browser, "requalified")
        offered = browser.get(f"/settings/llm/runtimes/{runtime_id}")
        assert f'<option value="{reasoner}"' not in offered.text
        assert "fake-reasoner (confirmed under earlier test rules" in _text(offered)

        # Re-qualified through the pages: release, unlock, test, confirm, bind, apply.
        active = db.execute("SELECT runtime_id FROM llm_runtimes WHERE state = 'ACTIVE'").fetchone()
        assert _post(browser, f"/settings/llm/runtimes/{active[0]}/retire", {}).status == 303
        ids = {}
        for name in ("fake-reasoner", "fake-critic"):
            ids[name] = _model(db, name, connection_id)
            assert _post(browser, f"/settings/llm/models/{ids[name]}/unlock", {}).status == 303
            assert _post(browser, f"/settings/llm/models/{ids[name]}/test", {}).status == 303
            assert _post(browser, f"/settings/llm/models/{ids[name]}/lock", {}).status == 303
        for slot, model in (
            ("REASONING_PRIMARY", "fake-reasoner"),
            ("FAST_UTILITY", "fake-reasoner"),
            ("REASONING_ADVERSARIAL", "fake-critic"),
        ):
            assert _bind(browser, runtime_id, slot, ids[model]).status == 303
        applied = _post(browser, f"/settings/llm/runtimes/{runtime_id}/activate", {})
        assert applied.status == 303, _text(applied)[:500]
        new_lock = db.execute(
            "SELECT lock_fingerprint FROM llm_models WHERE model_profile_id = %s", (reasoner,)
        ).fetchone()[0]
        assert new_lock != old_lock
        again = _research(browser, tmp_path)
        assert again.status == 303, _text(again)[:500]
        after = _provenance(db)

    assert [row for row in after if row in before] == before, "earlier inferences keep their lock"
    assert {v for row in after if row not in before for v in (row[1],)} == {new_lock}
    history = {
        r[0]
        for r in db.execute(
            "SELECT lock_fingerprint FROM llm_model_locks WHERE model_profile_id = %s", (reasoner,)
        ).fetchall()
    }
    assert {old_lock, new_lock} <= history


def test_a_model_qualified_only_at_the_generic_floor_is_refused_for_this_research(
    db, tmp_path, fake
):
    _setup(db)
    # Configured and applied by a settings service that asks only the generic floor (2) ...
    floor = LLMSettings(
        db,
        secrets=SecretStore(environ={"FAKE_KEY": KEY}, credentials=None),
        actor_id=ACTOR,
        hypothesis_minimum=2,
    )
    made = floor.add_connection(
        name="fake", base_url=fake.base_url, reach="LOCAL", secret_mode="env", env_name="FAKE_KEY"
    )
    floor.fetch_models(made.connection_id)
    model_id = next(
        m.model_profile_id for m in floor.registry.models() if m.model_name == "fake-reasoner"
    )
    floor.test_model(model_id)
    floor.lock(model_id)
    runtime = floor.create_runtime("floor", ["PUBLIC"])
    for slot in (LogicalSlot.REASONING_PRIMARY, LogicalSlot.FAST_UTILITY):
        floor.bind(runtime.runtime_id, slot, model_id)
    floor.activate(runtime.runtime_id)
    # ... the workspace, whose research asks for 5, refuses it before any model call.
    browser = _deployment(tmp_path, inference_deadline=60)
    calls = len(fake.calls)
    refused = _research(browser, tmp_path)
    assert refused.status == 409, _text(refused)[:500]
    assert "demonstrated ROLE_HYPOTHESIS for at least 2 competing hypotheses" in _text(refused)
    assert len(fake.calls) == calls
    # A configuration page offers it for fast processing, and says why not for primary reasoning.
    draft = _runtime(browser, "candidate")
    offered = browser.get(f"/settings/llm/runtimes/{draft}")

    def options(slot: str) -> str:
        found = re.search(rf'value="{slot}"><select name="model">(.*?)</select>', offered.text)
        return found.group(1) if found else ""

    assert f'<option value="{model_id}"' in options("FAST_UTILITY")
    assert f'<option value="{model_id}"' not in options("REASONING_PRIMARY")
    assert (
        "fake-reasoner (demonstrated ROLE_HYPOTHESIS for at least 2 competing hypotheses; this "
        "deployment's research requires 5)"
    ) in _text(offered)
