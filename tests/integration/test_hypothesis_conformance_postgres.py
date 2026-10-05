"""The ROLE_HYPOTHESIS conformance suite against the registry and the runtime, on PostgreSQL.

Driven through the settings service with a stand-in local model:

    stale             a route locked under the single-space suite is refused by readiness and by
                      `load_active_runtime`, and nothing of it is rewritten
    no shortcut       unlocking it and locking it again WITHOUT testing is refused: its tests ran
                      under the probes no longer in force, and a lock computed now would pass as
                      current on them
    re-qualified      testing it under the suite and locking it gives a new route fingerprint; the
                      suite, its cases and N are on the probe; every earlier row is byte-identical
    inventive model   one that binds a prediction to a space it named itself fails ROLE_HYPOTHESIS
                      in the multi-space case, and cannot serve REASONING_PRIMARY
    local setup       a model whose tests predate the probes is said and left unlocked, and the rest
                      of the setup goes on
"""

from __future__ import annotations

import io
import json
from collections.abc import Iterator

import pytest

import lab_brain.llm_runtime.registry as registry_module
from lab_brain.core.models.inference import LogicalSlot
from lab_brain.llm_runtime.capabilities import Capability
from lab_brain.llm_runtime.local_setup import configure
from lab_brain.llm_runtime.probes import HYPOTHESIS_SUITE, PROBE_VERSION
from lab_brain.llm_runtime.runtime import (
    LLMSettings,
    RuntimeUnavailable,
    SettingsRefused,
    load_active_runtime,
)
from lab_brain.llm_runtime.secrets import SecretStore
from tests.fake_llm_provider import FakeProvider
from tests.unit.test_hypothesis_conformance import SINGLE_SPACE_DIGEST

pytestmark = pytest.mark.postgres

LOCKED = (
    "CHAT",
    "STRUCTURED_JSON",
    "ROLE_QUERY",
    "ROLE_HYPOTHESIS",
    "ROLE_SPECIALIST",
    "ROLE_CRITIQUE",
)


@pytest.fixture
def local_model() -> Iterator[FakeProvider]:
    provider = FakeProvider(api_key=None).start()
    yield provider
    provider.stop()


@pytest.fixture(autouse=True)
def _administrator(db):  # type: ignore[no-untyped-def]
    db.execute(
        "INSERT INTO llm_administrators (actor_id, granted_at, granted_through)"
        " VALUES ('act:test', now(), 'OPERATOR_CLI')"
    )


def _settings(db) -> LLMSettings:  # type: ignore[no-untyped-def]
    """The settings service of a deployment whose research asks for 5 hypotheses."""
    return LLMSettings(
        db,
        secrets=SecretStore(environ={}, credentials=None),
        actor_id="act:test",
        hypothesis_minimum=5,
    )


def _model(db, base_url: str, name: str = "fake-reasoner", connection: str = "local") -> str:  # type: ignore[no-untyped-def]
    llm = _settings(db)
    made = llm.add_connection(name=connection, base_url=base_url, reach="LOCAL", secret_mode="none")
    llm.fetch_models(made.connection_id)
    return next(m.model_profile_id for m in llm.registry.models() if m.model_name == name)


def _tested_under_the_single_space_suite(db, model_id: str) -> None:  # type: ignore[no-untyped-def]
    """The probe rows a model has from before the suite: `probe-2.0.0`, ROLE_HYPOTHESIS at 5 over
    one outcome space -- what the deployment's qwen2.5:7b was locked on."""
    for n, capability in enumerate(LOCKED):
        parameters = {"minimum_hypotheses": 5} if capability == "ROLE_HYPOTHESIS" else {}
        db.execute(
            "INSERT INTO llm_capability_probes (probe_id, model_profile_id, capability, outcome,"
            " probe_version, latency_ms, probed_at, parameters) VALUES (%s, %s, %s, 'PASSED',"
            " 'probe-2.0.0', 900, now() - interval '1 day', %s::jsonb)",
            (f"lcp:old-{n}", model_id, capability, json.dumps(parameters)),
        )
    db.execute(
        "UPDATE llm_models SET lifecycle = 'TESTED' WHERE model_profile_id = %s", (model_id,)
    )


def _rows(db, sql: str, *args: object) -> list[str]:  # type: ignore[no-untyped-def]
    return [r[0] for r in db.execute(sql, args).fetchall()]


def _load(db):  # type: ignore[no-untyped-def]
    return load_active_runtime(
        db,
        SecretStore(environ={}, credentials=None),
        local_hosts=(),
        inference_deadline=180,
        hypothesis_minimum=5,
    )


def test_a_single_space_route_is_stale_and_only_testing_requalifies_it(
    db, local_model, monkeypatch
):
    model_id = _model(db, local_model.base_url)
    _tested_under_the_single_space_suite(db, model_id)
    llm = _settings(db)
    # Locked, bound and applied while the single-space suite was the one in force.
    with monkeypatch.context() as then:
        then.setattr(registry_module, "QUALIFICATION_DIGEST", SINGLE_SPACE_DIGEST)
        then.setattr(registry_module, "PROBE_VERSION", "probe-2.0.0")
        old = llm.lock(model_id)
        runtime = llm.create_runtime("single-space", ["PUBLIC"])
        for slot in (LogicalSlot.REASONING_PRIMARY, LogicalSlot.FAST_UTILITY):
            llm.bind(runtime.runtime_id, slot, model_id)
        llm.activate(runtime.runtime_id)
        assert _load(db), "current, then"
    locks = "SELECT t::text FROM llm_model_locks t WHERE model_profile_id = %s ORDER BY locked_at"
    probes = "SELECT t::text FROM llm_capability_probes t WHERE model_profile_id = %s ORDER BY 1"
    history, evidence = _rows(db, locks, model_id), _rows(db, probes, model_id)

    # Under the suite: stale, refused by readiness and by the runtime boundary, left as it was.
    stale = llm.registry.lock_problem(old)
    assert stale is not None and f"lock {old.lock_fingerprint} was made under" in stale
    assert any("no longer in force" in b for b in llm.readiness(runtime.runtime_id).blockers)
    with pytest.raises(RuntimeUnavailable, match="no longer in force"):
        _load(db)
    assert llm.registry.model(model_id) == old

    # No shortcut: unlocked and locked again without a test, it is refused, and nothing is written.
    llm.retire_runtime(runtime.runtime_id)
    llm.unlock(model_id)
    with pytest.raises(SettingsRefused, match=r"ran under probe-2\.0\.0") as refused:
        llm.lock(model_id)
    assert refused.value.code == "lock.outdated_tests"
    assert PROBE_VERSION in str(refused.value)
    unlocked = llm.registry.model(model_id)
    assert unlocked is not None and unlocked.lifecycle == "TESTED"
    assert _rows(db, locks, model_id) == history

    # Tested under the suite and locked: a new route, with what the suite demonstrated on it.
    llm.test_model(model_id)
    hypothesis = llm.registry.latest_probes(model_id)[Capability.ROLE_HYPOTHESIS]
    assert (hypothesis.outcome, hypothesis.probe_version) == ("PASSED", PROBE_VERSION)
    assert dict(hypothesis.parameters) == {
        "minimum_hypotheses": 5,
        "suite": HYPOTHESIS_SUITE,
        "cases": ["contextual-minimum", "multi-space"],
    }
    new = llm.lock(model_id)
    assert new.lock_fingerprint not in (None, old.lock_fingerprint)
    assert llm.registry.lock_problem(new) is None
    again = llm.create_runtime("conformance", ["PUBLIC"])
    for slot in (LogicalSlot.REASONING_PRIMARY, LogicalSlot.FAST_UTILITY):
        llm.bind(again.runtime_id, slot, model_id)
    llm.activate(again.runtime_id)
    assert _load(db)

    # Every earlier row is as it was, byte for byte; the new lock is added beside the old.
    now_locks = _rows(db, locks, model_id)
    assert now_locks[: len(history)] == history and len(now_locks) == len(history) + 1
    assert set(evidence) <= set(_rows(db, probes, model_id))


def test_an_inventive_model_does_not_qualify_for_hypotheses(db):  # type: ignore[no-untyped-def]
    inventive = FakeProvider(api_key=None, invent_space=True).start()
    try:
        model_id = _model(db, inventive.base_url)
        llm = _settings(db)
        rows = {r.capability: r for r in llm.test_model(model_id)}
    finally:
        inventive.stop()
    hypothesis = rows[Capability.ROLE_HYPOTHESIS.value]
    assert hypothesis.outcome == "FAILED"
    assert hypothesis.detail.startswith("multi-space: the typed role parser refused it")
    assert "os:probe.noise_per_hz@1.0.0, which the engine was not shown" in hypothesis.detail
    assert hypothesis.parameters["suite"] == HYPOTHESIS_SUITE
    locked = llm.lock(model_id)
    assert "ROLE_HYPOTHESIS" not in (locked.locked_capabilities or ())
    runtime = llm.create_runtime("inventive", ["PUBLIC"])
    llm.bind(runtime.runtime_id, LogicalSlot.FAST_UTILITY, model_id)
    with pytest.raises(SettingsRefused):
        llm.bind(runtime.runtime_id, LogicalSlot.REASONING_PRIMARY, model_id)


def test_local_setup_leaves_a_model_with_outdated_tests_unlocked_and_goes_on(db, local_model):  # type: ignore[no-untyped-def]
    reasoner = _model(db, local_model.base_url, connection="ollama")
    _tested_under_the_single_space_suite(db, reasoner)
    out = io.StringIO()
    assert configure(_settings(db), local_model.base_url, out=out) == 0
    said = out.getvalue()
    assert "not locked fake-reasoner: model fake-reasoner's latest tests of" in said, said
    assert "locked fake-critic:" in said, "the rest of the setup goes on"
    registry = _settings(db).registry
    assert registry.model(reasoner).lifecycle == "TESTED"  # type: ignore[union-attr]
    critic = next(m for m in registry.models() if m.model_name == "fake-critic")
    assert critic.lifecycle == "LOCKED" and registry.lock_problem(critic) is None
