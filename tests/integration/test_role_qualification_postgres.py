"""Role qualification and stale locks against the registry, on PostgreSQL.

A capability probe now records what it demonstrated (`012l`): ROLE_HYPOTHESIS run at N competing
hypotheses. A lock's fingerprint names that N and the qualification semantics it was made under.
Proven here, with a stand-in local model and the settings service:

    fit           evidence for 2 does not qualify a REASONING_PRIMARY model for research that asks
                  for 5 -- not ready, not activated, not loaded; evidence for 5 serves 5 and less,
                  and nothing more
    stale         once the semantics change (a probe, a role prompt, a response contract), a lock
                  made before is refused by readiness and by the runtime boundary, and is left as
                  it was; re-testing and re-locking gives a new fingerprint, and the earlier one
                  stays on record (`llm_model_locks`)
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

import lab_brain.llm_runtime.registry as registry_module
from lab_brain.core.models.inference import LogicalSlot
from lab_brain.llm_runtime.runtime import (
    LLMSettings,
    RuntimeUnavailable,
    SettingsRefused,
    load_active_runtime,
)
from lab_brain.llm_runtime.secrets import SecretStore
from tests.fake_llm_provider import FakeProvider

pytestmark = pytest.mark.postgres

UNFIT = (
    "REASONING_PRIMARY: model fake-reasoner demonstrated ROLE_HYPOTHESIS for at least {shown} "
    "competing hypotheses; this deployment's research requires {required}"
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


def _settings(db, minimum: int) -> LLMSettings:  # type: ignore[no-untyped-def]
    """The settings service of a deployment whose research asks for `minimum` hypotheses."""
    return LLMSettings(
        db,
        secrets=SecretStore(environ={}, credentials=None),
        actor_id="act:test",
        hypothesis_minimum=minimum,
    )


def _qualified(db, base_url: str, *, at: int) -> tuple[str, str]:  # type: ignore[no-untyped-def]
    """fake-reasoner tested with ROLE_HYPOTHESIS at `at`, locked, and bound to the reasoning
    route of a DRAFT runtime. Returns (model id, runtime id)."""
    llm = _settings(db, at)
    made = llm.add_connection(name="local", base_url=base_url, reach="LOCAL", secret_mode="none")
    llm.fetch_models(made.connection_id)
    model_id = next(
        m.model_profile_id for m in llm.registry.models() if m.model_name == "fake-reasoner"
    )
    llm.test_model(model_id)
    llm.lock(model_id)
    runtime = llm.create_runtime("qualified", ["PUBLIC"])
    for slot in (LogicalSlot.REASONING_PRIMARY, LogicalSlot.FAST_UTILITY):
        llm.bind(runtime.runtime_id, slot, model_id)
    return model_id, runtime.runtime_id


def _secrets() -> SecretStore:
    return SecretStore(environ={}, credentials=None)


def test_evidence_for_two_does_not_qualify_for_research_that_asks_for_five(db, local_model):
    model_id, runtime_id = _qualified(db, local_model.base_url, at=2)
    recorded = db.execute(
        "SELECT parameters FROM llm_capability_probes WHERE model_profile_id = %s"
        " AND capability = 'ROLE_HYPOTHESIS'",
        (model_id,),
    ).fetchone()[0]
    assert recorded == {"minimum_hypotheses": 2}, "the evidence says what was demonstrated"

    unfit = UNFIT.format(shown=2, required=5)
    blockers = _settings(db, 5).readiness(runtime_id).blockers
    assert unfit in blockers, blockers
    assert not any(b.startswith("FAST_UTILITY") for b in blockers), "it needs no hypotheses"
    with pytest.raises(SettingsRefused, match="requires 5"):
        _settings(db, 5).activate(runtime_id)

    # Activated where 2 is what research asks; refused wherever 5 is.
    _settings(db, 2).activate(runtime_id)
    with pytest.raises(RuntimeUnavailable, match="requires 5"):
        load_active_runtime(
            db, _secrets(), local_hosts=(), inference_deadline=180, hypothesis_minimum=5
        )
    assert load_active_runtime(
        db, _secrets(), local_hosts=(), inference_deadline=180, hypothesis_minimum=2
    )


def test_evidence_for_five_serves_five_and_less_and_nothing_more(db, local_model):
    _, runtime_id = _qualified(db, local_model.base_url, at=5)
    for required in (2, 3, 5):
        assert _settings(db, required).readiness(runtime_id).ready, required
    assert UNFIT.format(shown=5, required=6) in _settings(db, 6).readiness(runtime_id).blockers


def test_a_lock_made_under_earlier_semantics_is_stale_until_requalified(
    db, local_model, monkeypatch
):
    model_id, runtime_id = _qualified(db, local_model.base_url, at=5)
    llm = _settings(db, 5)
    llm.activate(runtime_id)
    old = llm.registry.model(model_id)
    assert old is not None and old.lock_fingerprint is not None
    assert llm.registry.lock_problem(old) is None, "current when made"

    # The qualification semantics change -- a probe, a role prompt, a response contract.
    monkeypatch.setattr(registry_module, "QUALIFICATION_DIGEST", "0" * 64)
    stale = llm.registry.lock_problem(old)
    assert stale is not None and f"lock {old.lock_fingerprint} was made under" in stale
    blockers = llm.readiness(runtime_id).blockers
    assert any("no longer in force" in b for b in blockers), blockers
    assert not any("demonstrated ROLE_HYPOTHESIS" in b for b in blockers), "not weighed when stale"
    with pytest.raises(RuntimeUnavailable, match="no longer in force"):
        load_active_runtime(
            db, _secrets(), local_hosts=(), inference_deadline=180, hypothesis_minimum=5
        )
    unchanged = llm.registry.model(model_id)
    assert unchanged == old, "the lock is refused, never rewritten"

    # Re-qualified by the operator: the configuration released, the model tested and locked again.
    llm.retire_runtime(runtime_id)
    llm.unlock(model_id)
    llm.test_model(model_id)
    new = llm.lock(model_id)
    assert new.lock_fingerprint not in (None, old.lock_fingerprint), "a new route fingerprint"
    assert llm.registry.lock_problem(new) is None
    history = [
        r[0]
        for r in db.execute(
            "SELECT lock_fingerprint FROM llm_model_locks WHERE model_profile_id = %s"
            " ORDER BY locked_at",
            (model_id,),
        ).fetchall()
    ]
    assert history == [old.lock_fingerprint, new.lock_fingerprint], "every lock stays on record"
    with pytest.raises(Exception, match="append-only"):
        db.execute("DELETE FROM llm_model_locks WHERE model_profile_id = %s", (model_id,))
