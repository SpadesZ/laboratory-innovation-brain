"""The deployment's inference deadline where it decides something, on PostgreSQL.

The first local smoke ran qwen2.5:7b on CPU: its ROLE_HYPOTHESIS probe had passed in 194 s (probed
under a 300 s timeout), the configuration was declared READY, and the research call then timed out
at the runtime's own 180 s. One deadline now governs both, and readiness reads the recorded
evidence against it:

    one deadline     the capability probes that qualify a model and the calls an active runtime
                     makes wait exactly the deployment's inference deadline; listing models and
                     checking health use their own short timeout
    readiness        a configuration whose model already needed longer than the deadline for a
                     capability its slot requires is NOT ready -- not activated, not loaded for
                     research
    the evidence     raising the deadline makes the very same recorded probes acceptable; nothing
                     is re-probed, unlocked or rewritten
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

import pytest

from lab_brain.core.models.inference import LogicalSlot
from lab_brain.llm_runtime.probes import PROBE_VERSION
from lab_brain.llm_runtime.provider import OpenAICompatibleClient
from lab_brain.llm_runtime.registry import SqlLLMRegistry
from lab_brain.llm_runtime.runtime import (
    DISCOVERY_TIMEOUT_S,
    LLMSettings,
    RuntimeUnavailable,
    SettingsRefused,
    load_active_runtime,
)
from lab_brain.llm_runtime.secrets import SecretStore
from tests.fake_llm_provider import FakeProvider

pytestmark = pytest.mark.postgres

T0 = "2026-09-28T00:00:00Z"
#: The smoke's evidence: what each capability's passing probe took, in ms.
LATENCY_MS = {
    "CHAT": 21_371,
    "STRUCTURED_JSON": 8_438,
    "ROLE_QUERY": 26_835,
    "ROLE_HYPOTHESIS": 193_636,
    "ROLE_SPECIALIST": 62_692,
    "ROLE_CRITIQUE": 112_318,
}
SLOW = (
    "REASONING_PRIMARY: model qwen2.5:7b's recorded ROLE_HYPOTHESIS probe took 194 s, longer than "
    "this deployment's inference deadline (180 s)"
)


@pytest.fixture
def local_model() -> Iterator[FakeProvider]:
    """A local endpoint that answers health checks and model calls (no credential)."""
    provider = FakeProvider(api_key=None).start()
    yield provider
    provider.stop()


@pytest.fixture(autouse=True)
def _administrator(db):  # type: ignore[no-untyped-def]
    db.execute(
        "INSERT INTO llm_administrators (actor_id, granted_at, granted_through)"
        " VALUES ('act:test', now(), 'OPERATOR_CLI')"
    )


def _settings(db, deadline: float, **kwargs: object) -> LLMSettings:  # type: ignore[no-untyped-def]
    kwargs.setdefault("hypothesis_minimum", 5)
    return LLMSettings(
        db,
        secrets=SecretStore(environ={}, credentials=None),
        actor_id="act:test",
        inference_deadline=deadline,
        **kwargs,  # type: ignore[arg-type]
    )


def _smoke_configuration(db, base_url: str) -> str:  # type: ignore[no-untyped-def]
    """The smoke's configuration as stored: qwen2.5:7b locked on the evidence above, bound to the
    required slots of a DRAFT runtime, its LOCAL connection healthy. Returns the runtime id."""
    db.execute(
        "INSERT INTO llm_connections (connection_id, name, provider_kind, base_url, reach,"
        " lifecycle, created_by, created_at, updated_at) VALUES ('llc:ollama', 'ollama',"
        " 'OPENAI_COMPATIBLE', %s, 'LOCAL', 'ENABLED', 'act:test', %s, %s)",
        (base_url, T0, T0),
    )
    db.execute(
        "INSERT INTO llm_models (model_profile_id, connection_id, model_name, source, created_at)"
        " VALUES ('llm:qwen', 'llc:ollama', 'qwen2.5:7b', 'FETCHED', %s)",
        (T0,),
    )
    for n, (capability, latency) in enumerate(LATENCY_MS.items()):
        # ROLE_HYPOTHESIS demonstrated at the research's minimum (`012l` records what was asked).
        parameters = '{"minimum_hypotheses": 5}' if capability == "ROLE_HYPOTHESIS" else "{}"
        db.execute(
            "INSERT INTO llm_capability_probes (probe_id, model_profile_id, capability, outcome,"
            " probe_version, latency_ms, probed_at, parameters) VALUES (%s, 'llm:qwen', %s,"
            " 'PASSED', %s, %s, %s, %s::jsonb)",
            (f"lcp:qwen-{n}", capability, PROBE_VERSION, latency, T0, parameters),
        )
    db.execute("UPDATE llm_models SET lifecycle = 'TESTED' WHERE model_profile_id = 'llm:qwen'")
    # Locked through the registry, so the lock is current under the qualification semantics.
    SqlLLMRegistry(db).lock("llm:qwen", actor_id="act:test", at=dt.datetime.now(dt.UTC))
    db.execute(
        "INSERT INTO llm_connection_health (check_id, connection_id, outcome, latency_ms, detail,"
        " checked_at) VALUES ('lch:ok', 'llc:ollama', 'REACHABLE', 5, '4 model(s) listed', now())"
    )
    llm = _settings(db, 180)
    runtime = llm.create_runtime("local-first", ["PUBLIC"])
    for slot in (
        LogicalSlot.REASONING_PRIMARY,
        LogicalSlot.FAST_UTILITY,
        LogicalSlot.REASONING_ADVERSARIAL,
    ):
        llm.bind(runtime.runtime_id, slot, "llm:qwen")
    return runtime.runtime_id


def _evidence(db) -> list[tuple[object, ...]]:  # type: ignore[no-untyped-def]
    return db.execute(
        "SELECT p.probe_id, p.capability, p.outcome, p.latency_ms, p.probed_at,"
        " m.lifecycle, m.locked_capabilities, m.lock_fingerprint"
        " FROM llm_capability_probes p JOIN llm_models m USING (model_profile_id)"
        " ORDER BY p.probe_id"
    ).fetchall()


def test_a_capability_proven_in_194_s_cannot_make_a_180_s_deployment_ready(db, local_model):
    runtime_id = _smoke_configuration(db, local_model.base_url)
    before = _evidence(db)

    under = _settings(db, 180).readiness(runtime_id)
    assert not under.ready and SLOW in under.blockers, under.blockers
    # Only the slot that needs the slow capability: FAST_UTILITY's requirements were all quick.
    assert not any(b.startswith("FAST_UTILITY") for b in under.blockers)
    with pytest.raises(SettingsRefused, match=r"not ready: .*probe took 194 s"):
        _settings(db, 180).activate(runtime_id)

    # The same recorded evidence, under a deadline the deployment raised: ready, and activated.
    over = _settings(db, 300)
    assert over.readiness(runtime_id).ready, over.readiness(runtime_id).blockers
    over.activate(runtime_id)
    assert _evidence(db) == before, "nothing was re-probed, unlocked or rewritten"

    # The research boundary holds the same line, under whatever deadline it is given.
    secrets = SecretStore(environ={}, credentials=None)
    with pytest.raises(RuntimeUnavailable, match=r"probe took 194 s, longer than .*180 s"):
        load_active_runtime(
            db, secrets, local_hosts=(), inference_deadline=180, hypothesis_minimum=5
        )
    runtime = load_active_runtime(
        db, secrets, local_hosts=(), inference_deadline=300, hypothesis_minimum=5
    )
    assert runtime is not None
    assert "Each model call waits at most 300 s for its answer" in " ".join(runtime.description)


def test_probes_and_research_calls_wait_one_deadline_and_discovery_its_own(db, local_model):
    waited: list[float] = []

    def client(base_url: str, key: str | None, timeout: float) -> OpenAICompatibleClient:
        waited.append(timeout)
        return OpenAICompatibleClient(base_url, key, timeout=timeout)

    llm = _settings(db, 42, client=client, hypothesis_minimum=2)
    made = llm.add_connection(
        name="local", base_url=local_model.base_url, reach="LOCAL", secret_mode="none"
    )
    llm.fetch_models(made.connection_id)
    llm.check_health(made.connection_id)
    assert waited == [DISCOVERY_TIMEOUT_S, DISCOVERY_TIMEOUT_S], "discovery is not inference"

    waited.clear()
    models = {m.model_name: m.model_profile_id for m in llm.registry.models()}
    llm.test_model(models["fake-reasoner"])
    assert waited == [42.0], "every capability probe waits the deployment's inference deadline"

    llm.lock(models["fake-reasoner"])
    runtime = llm.create_runtime("one deadline", ["PUBLIC"])
    for slot in (LogicalSlot.REASONING_PRIMARY, LogicalSlot.FAST_UTILITY):
        llm.bind(runtime.runtime_id, slot, models["fake-reasoner"])
    llm.activate(runtime.runtime_id)
    active = load_active_runtime(
        db,
        SecretStore(environ={}, credentials=None),
        local_hosts=(),
        inference_deadline=42,
        hypothesis_minimum=2,
    )
    assert active is not None
    routes = active.complete._routes  # type: ignore[attr-defined]
    assert {route.client._timeout for route in routes.values()} == {42.0}
