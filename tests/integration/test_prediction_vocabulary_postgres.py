"""The prediction vocabulary in qualification and in locks, on PostgreSQL.

The Hypothesis Engine's contract now binds a prediction's observable to its declared space (prompt
3.0.0, rc-2.0.0, `hypothesis-conformance@2.0.0`). Driven through the settings service with a
stand-in local model:

    the smoke's error   a model that writes a space id where the observable belongs fails
                        ROLE_HYPOTHESIS in qualification, and cannot serve REASONING_PRIMARY
    stale               a route qualified under the previous semantics (the outcome-space-only
                        contract) is refused by readiness and by the runtime boundary, its evidence
                        cannot be locked again, and testing it under the vocabulary gives a new route;
                        no probe or lock row written before is changed
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

import lab_brain.llm_runtime.registry as registry_module
from lab_brain.core.models.inference import LogicalSlot
from lab_brain.llm_runtime.capabilities import Capability
from lab_brain.llm_runtime.probes import HYPOTHESIS_SUITE, QUALIFICATION_DIGEST
from lab_brain.llm_runtime.runtime import RuntimeUnavailable, SettingsRefused
from tests.fake_llm_provider import FakeProvider
from tests.integration.test_hypothesis_conformance_postgres import _load, _model, _rows, _settings

pytestmark = pytest.mark.postgres

#: `QUALIFICATION_DIGEST` under the outcome-space-only contract (prompt 2.1.0, `probe-3.0.0`).
OUTCOME_SPACE_ONLY_DIGEST = "9a34d824c9fd495b74f47b3af195436c0267762d8a3287f761f55cbc70d52007"
LOCKS = "SELECT t::text FROM llm_model_locks t WHERE model_profile_id = %s ORDER BY locked_at"
PROBES = "SELECT t::text FROM llm_capability_probes t WHERE model_profile_id = %s ORDER BY 1"
SLOTS = (LogicalSlot.REASONING_PRIMARY, LogicalSlot.FAST_UTILITY)


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


def test_a_model_that_writes_space_ids_as_observables_does_not_qualify(db):  # type: ignore[no-untyped-def]
    copier = FakeProvider(api_key=None, space_as_observable=True).start()
    try:
        model_id = _model(db, copier.base_url)
        llm = _settings(db)
        rows = {r.capability: r for r in llm.test_model(model_id)}
    finally:
        copier.stop()
    hypothesis = rows[Capability.ROLE_HYPOTHESIS.value]
    assert hypothesis.outcome == "FAILED"
    assert hypothesis.detail.startswith("contextual-minimum: the typed role parser refused it")
    assert "observable 'os:probe.level', which is not in the prediction vocabulary" in (
        hypothesis.detail
    )
    assert hypothesis.parameters["suite"] == HYPOTHESIS_SUITE
    locked = llm.lock(model_id)
    assert "ROLE_HYPOTHESIS" not in (locked.locked_capabilities or ())
    runtime = llm.create_runtime("copier", ["PUBLIC"])
    with pytest.raises(SettingsRefused):
        llm.bind(runtime.runtime_id, LogicalSlot.REASONING_PRIMARY, model_id)


def test_a_route_qualified_without_the_vocabulary_is_stale_until_tested_again(
    db, local_model, monkeypatch
):
    assert QUALIFICATION_DIGEST != OUTCOME_SPACE_ONLY_DIGEST
    model_id = _model(db, local_model.base_url)
    llm = _settings(db)
    # Tested, locked and applied while the outcome-space-only contract was in force.
    with monkeypatch.context() as then:
        then.setattr(registry_module, "QUALIFICATION_DIGEST", OUTCOME_SPACE_ONLY_DIGEST)
        llm.test_model(model_id)
        old = llm.lock(model_id)
        runtime = llm.create_runtime("outcome spaces only", ["PUBLIC"])
        for slot in SLOTS:
            llm.bind(runtime.runtime_id, slot, model_id)
        llm.activate(runtime.runtime_id)
        assert _load(db)
    locks, probes = _rows(db, LOCKS, model_id), _rows(db, PROBES, model_id)

    # Under the vocabulary contract: stale, refused at readiness and at the boundary, untouched.
    assert "no longer in force" in str(llm.registry.lock_problem(old))
    assert any("no longer in force" in b for b in llm.readiness(runtime.runtime_id).blockers)
    with pytest.raises(RuntimeUnavailable, match="no longer in force"):
        _load(db)
    llm.retire_runtime(runtime.runtime_id)
    llm.unlock(model_id)
    with pytest.raises(SettingsRefused, match="not run under the qualification semantics") as no:
        llm.lock(model_id)
    assert f"theirs: probe-4.0.0 {OUTCOME_SPACE_ONLY_DIGEST[:12]}" in str(no.value)

    # Tested under the vocabulary: a new route; every earlier row as it was.
    llm.test_model(model_id)
    new = llm.lock(model_id)
    assert new.lock_fingerprint not in (None, old.lock_fingerprint)
    assert llm.registry.lock_problem(new) is None
    after_locks, after_probes = _rows(db, LOCKS, model_id), _rows(db, PROBES, model_id)
    assert after_locks[: len(locks)] == locks and len(after_locks) == len(locks) + 1
    assert [r for r in after_probes if r in probes] == probes
