"""The ROLE_HYPOTHESIS conformance suite through the web workspace, on PostgreSQL.

Driven as an administrator would, with the stand-in model:

    qualified         a model is tested with every case of the suite at the research's N, and the
                      model page names the suite beside N
    inventive         a model that binds a prediction to a space it named from the evidence fails
                      the multi-space case: the page says so, and primary reasoning is not offered
    next suite        when the qualification semantics move on, research is refused before any
                      model call; confirming the model again without testing it is refused, in the
                      researcher's words; testing and confirming it gives a new route -- and every
                      earlier InferenceProvenance and lock row is byte-for-byte as it was
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import patch

import pytest

import lab_brain.llm_runtime.registry as registry_module
from lab_brain.llm_runtime.probes import HYPOTHESIS_SUITE
from tests.e2e.test_web_debate_retry_postgres import _activated, _deployment
from tests.e2e.test_web_llm_credentials_postgres import KEY, _connection, _post, _setup, _text
from tests.e2e.test_web_llm_runtime_postgres import _bind, _model, _proven, _research, _runtime
from tests.fake_llm_provider import FakeProvider

pytestmark = pytest.mark.postgres


@pytest.fixture
def fake() -> Iterator[FakeProvider]:
    provider = FakeProvider(api_key=KEY).start()
    yield provider
    provider.stop()


def _rows(db, sql: str) -> list[str]:  # type: ignore[no-untyped-def]
    return [r[0] for r in db.execute(sql).fetchall()]


PROVENANCE = "SELECT t::text FROM inference_provenance t ORDER BY inference_id"
LOCKS = "SELECT t::text FROM llm_model_locks t ORDER BY model_profile_id, locked_at"


def test_a_route_from_an_earlier_suite_is_refused_and_history_stays_byte_for_byte(
    db, tmp_path, fake
):
    _setup(db)
    browser = _deployment(tmp_path, inference_deadline=60)
    connection_id = _activated(db, browser, fake)
    reasoner = _model(db, "fake-reasoner", connection_id)
    assert db.execute(
        "SELECT parameters FROM llm_capability_probes WHERE model_profile_id = %s"
        " AND capability = 'ROLE_HYPOTHESIS'",
        (reasoner,),
    ).fetchone()[0] == {
        "minimum_hypotheses": 5,
        "suite": HYPOTHESIS_SUITE,
        "cases": ["contextual-minimum", "multi-space"],
    }
    assert f"conformance suite {HYPOTHESIS_SUITE}" in _text(
        browser.get(f"/settings/llm/models/{reasoner}")
    )
    assert _research(browser, tmp_path).status == 303
    provenance, locks = _rows(db, PROVENANCE), _rows(db, LOCKS)
    assert provenance and locks

    # The next suite: other payloads, another probe version.
    with (
        patch.object(registry_module, "QUALIFICATION_DIGEST", "e" * 64),
        patch.object(registry_module, "PROBE_VERSION", "probe-9.9.9"),
    ):
        calls = len(fake.calls)
        refused = _research(browser, tmp_path)
        assert refused.status == 409 and "no longer in force" in _text(refused)
        assert len(fake.calls) == calls, "refused before any model call"

        active = db.execute("SELECT runtime_id FROM llm_runtimes WHERE state = 'ACTIVE'").fetchone()
        assert _post(browser, f"/settings/llm/runtimes/{active[0]}/retire", {}).status == 303
        assert _post(browser, f"/settings/llm/models/{reasoner}/unlock", {}).status == 303
        # Confirming it again on the earlier suite's tests: refused, said in the researcher's words.
        zh = _deployment(tmp_path, inference_deadline=60)
        assert _post(zh, "/locale", {"locale": "zh-TW"}).status in (200, 303)
        shortcut = _post(zh, f"/settings/llm/models/{reasoner}/lock", {})
        assert shortcut.status == 409
        assert "最近一次的能力測試是在舊版測試規則下完成的" in _text(shortcut)
        assert "lock.outdated_tests" in _text(shortcut)

        # Tested and confirmed: a new route, and research goes on over it.
        assert _post(browser, f"/settings/llm/models/{reasoner}/test", {}).status == 303
        assert _post(browser, f"/settings/llm/models/{reasoner}/lock", {}).status == 303
        critic = _model(db, "fake-critic", connection_id)
        assert _post(browser, f"/settings/llm/models/{critic}/unlock", {}).status == 303
        assert _post(browser, f"/settings/llm/models/{critic}/test", {}).status == 303
        assert _post(browser, f"/settings/llm/models/{critic}/lock", {}).status == 303
        runtime_id = _runtime(browser, "next suite")
        for slot, model in (
            ("REASONING_PRIMARY", reasoner),
            ("FAST_UTILITY", reasoner),
            ("REASONING_ADVERSARIAL", critic),
        ):
            assert _bind(browser, runtime_id, slot, model).status == 303
        applied = _post(browser, f"/settings/llm/runtimes/{runtime_id}/activate", {})
        assert applied.status == 303, _text(applied)[:500]
        assert _research(browser, tmp_path).status == 303

    after_provenance, after_locks = _rows(db, PROVENANCE), _rows(db, LOCKS)
    assert [r for r in after_provenance if r in provenance] == provenance, "byte for byte"
    assert len(after_provenance) > len(provenance)
    assert [r for r in after_locks if r in locks] == locks, "every lock row as it was"
    assert len(after_locks) == len(locks) + 2, "the two new locks beside them"


def test_an_inventive_model_is_not_qualified_for_primary_reasoning(db, tmp_path):
    _setup(db)
    inventive = FakeProvider(api_key=KEY, invent_space=True).start()
    try:
        browser = _deployment(tmp_path, inference_deadline=60)
        added = _post(
            browser,
            "/settings/llm/connections",
            {
                "provider": "custom",
                "name": "inventive",
                "base_url": inventive.base_url,
                "reach": "EXTERNAL",
                "secret_value": KEY,
            },
        )
        assert added.status == 303, _text(added)[:400]
        connection_id = _connection(db, "inventive")[0]
        model_id = _proven(browser, db, connection_id, "fake-reasoner")["fake-reasoner"]
    finally:
        inventive.stop()
    page = _text(browser.get(f"/settings/llm/models/{model_id}"))
    assert "multi-space: the typed role parser refused it" in page
    assert "os:probe.noise_per_hz@1.0.0, which the engine was not shown" in page
    runtime_id = _runtime(browser, "inventive")
    offered = browser.get(f"/settings/llm/runtimes/{runtime_id}")
    assert "fake-reasoner (not proven: ROLE_HYPOTHESIS)" in _text(offered)
    refused = _bind(browser, runtime_id, "REASONING_PRIMARY", model_id)
    assert refused.status == 409
    assert _bind(browser, runtime_id, "FAST_UTILITY", model_id).status == 303
