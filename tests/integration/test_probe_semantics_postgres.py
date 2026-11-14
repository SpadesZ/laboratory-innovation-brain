"""Probe evidence names the qualification semantics it was produced under (`012m`), on PostgreSQL.

A lock's fingerprint is computed under the semantics in force when it is made. If a lock could
count probe rows by `probe_version` alone, a prompt, contract or payload changed WITHOUT a version
bump would let a stale model be unlocked and locked again on evidence from the old semantics -- a
current-looking lock on tests that qualify nothing. Proven here, with a stand-in local model and the
settings service, `PROBE_VERSION` left exactly as it is:

    prompt / contract / payload   each changed alone: the lock made before is stale (readiness and
                                  the runtime boundary refuse it); unlocking it and locking it again
                                  without a test is refused; tested under the semantics in force, it
                                  is locked again, under a new route fingerprint
    unrecorded                    probe rows that recorded no semantics (written before `012m`)
                                  qualify nothing: no lock is made on them, and a lock already made
                                  on them is refused by readiness and the runtime boundary
    history                       no probe or lock row written before is changed
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest

import lab_brain.llm_runtime.registry as registry_module
from lab_brain.cognition.roles import HYPOTHESIS_ENGINE
from lab_brain.core.models.inference import LogicalSlot
from lab_brain.llm_runtime.capabilities import Capability
from lab_brain.llm_runtime.contracts import CONTRACTS, contract_digest
from lab_brain.llm_runtime.probes import (
    HYPOTHESIS_SUITE,
    PROBE_VERSION,
    QUALIFICATION_DIGEST,
    qualification_digest,
    qualification_inputs,
)
from lab_brain.llm_runtime.registry import lock_fingerprint, qualification_of
from lab_brain.llm_runtime.runtime import RuntimeUnavailable, SettingsRefused
from tests.fake_llm_provider import FakeProvider
from tests.integration.test_hypothesis_conformance_postgres import _load, _model, _rows, _settings

pytestmark = pytest.mark.postgres

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


def _semantics_with(change: str) -> str:
    """The qualification digest after ONE part changed, the probe version left as it is."""
    inputs: dict[str, Any] = qualification_inputs()
    if change == "prompt text":
        prompts = dict(inputs["prompts"])
        version, template = prompts[HYPOTHESIS_ENGINE.prompt.prompt_id]
        prompts[HYPOTHESIS_ENGINE.prompt.prompt_id] = [version, template + " Be brief."]
        inputs["prompts"] = prompts
    elif change == "response contract":
        contracts = dict(CONTRACTS)
        contracts["ROLE_HYPOTHESIS"] += " Use lower-case keys."
        inputs["contracts"] = contract_digest(contracts)  # under the same contract version
    elif change == "probe payload":
        probes = json.loads(json.dumps(inputs["probes"]))
        probes["ROLE_HYPOTHESIS"]["cases"]["multi-space"][0] += " "
        inputs["probes"] = probes
    assert inputs["probe_version"] == PROBE_VERSION
    changed = qualification_digest(**inputs)
    assert changed != QUALIFICATION_DIGEST
    return changed


@pytest.mark.parametrize("change", ["prompt text", "response contract", "probe payload"])
def test_changed_semantics_without_a_version_bump_need_a_test_before_a_lock(
    db, local_model, monkeypatch, change
):
    model_id = _model(db, local_model.base_url)
    llm = _settings(db)
    llm.test_model(model_id)
    recorded = llm.registry.latest_probes(model_id).values()
    assert {(p.probe_version, p.qualification_digest) for p in recorded} == {
        (PROBE_VERSION, QUALIFICATION_DIGEST)
    }, "every probe names the semantics it ran under"
    old = llm.lock(model_id)
    runtime = llm.create_runtime("before", ["PUBLIC"])
    for slot in SLOTS:
        llm.bind(runtime.runtime_id, slot, model_id)
    llm.activate(runtime.runtime_id)
    assert _load(db)
    locks, probes = _rows(db, LOCKS, model_id), _rows(db, PROBES, model_id)

    # One part of the semantics changes; the probe version does not.
    now = _semantics_with(change)
    monkeypatch.setattr(registry_module, "QUALIFICATION_DIGEST", now)
    assert registry_module.PROBE_VERSION == PROBE_VERSION
    assert "no longer in force" in str(llm.registry.lock_problem(old))
    assert any("no longer in force" in b for b in llm.readiness(runtime.runtime_id).blockers)
    with pytest.raises(RuntimeUnavailable, match="no longer in force"):
        _load(db)

    # Unlocked and locked again at once: refused -- its evidence ran under the old semantics.
    llm.retire_runtime(runtime.runtime_id)
    llm.unlock(model_id)
    with pytest.raises(SettingsRefused, match="not run under the qualification semantics") as no:
        llm.lock(model_id)
    assert no.value.code == "lock.outdated_tests"
    assert f"{PROBE_VERSION} {now[:12]}" in str(no.value), "the semantics in force"
    assert f"theirs: {PROBE_VERSION} {QUALIFICATION_DIGEST[:12]}" in str(no.value)
    assert llm.registry.model(model_id).lifecycle == "TESTED"  # type: ignore[union-attr]
    assert _rows(db, LOCKS, model_id) == locks, "no lock was written"

    # Tested under the semantics in force: locked again, a new route; nothing earlier rewritten.
    llm.test_model(model_id)
    assert {p.qualification_digest for p in llm.registry.latest_probes(model_id).values()} == {now}
    new = llm.lock(model_id)
    assert new.lock_fingerprint not in (None, old.lock_fingerprint)
    assert llm.registry.lock_problem(new) is None
    again = llm.create_runtime("after", ["PUBLIC"])
    for slot in SLOTS:
        llm.bind(again.runtime_id, slot, model_id)
    llm.activate(again.runtime_id)
    assert _load(db)
    after_locks, after_probes = _rows(db, LOCKS, model_id), _rows(db, PROBES, model_id)
    assert after_locks[: len(locks)] == locks and len(after_locks) == len(locks) + 1
    assert [r for r in after_probes if r in probes] == probes
    assert len(after_probes) == 2 * len(probes)


def _tested_before_012m(db, model_id: str) -> None:  # type: ignore[no-untyped-def]
    """Probe rows as `012m` found them: the probes in force, the semantics never recorded."""
    suite = {"minimum_hypotheses": 5, "suite": HYPOTHESIS_SUITE, "cases": ["contextual-minimum"]}
    for n, capability in enumerate(Capability):
        if capability in (Capability.CODE, Capability.VISION):
            continue
        parameters = suite if capability is Capability.ROLE_HYPOTHESIS else {}
        db.execute(
            "INSERT INTO llm_capability_probes (probe_id, model_profile_id, capability, outcome,"
            " probe_version, latency_ms, probed_at, parameters) VALUES (%s, %s, %s, 'PASSED', %s,"
            " 900, now() - interval '1 day', %s::jsonb)",
            (
                f"lcp:unrecorded-{n}",
                model_id,
                capability.value,
                PROBE_VERSION,
                json.dumps(parameters),
            ),
        )
    db.execute(
        "UPDATE llm_models SET lifecycle = 'TESTED' WHERE model_profile_id = %s", (model_id,)
    )


def test_probes_that_recorded_no_semantics_qualify_nothing(db, local_model):
    model_id = _model(db, local_model.base_url)
    _tested_before_012m(db, model_id)
    llm = _settings(db)
    with pytest.raises(SettingsRefused, match="semantics not recorded") as no:
        llm.lock(model_id)
    assert no.value.code == "lock.outdated_tests"

    # A lock already made on them -- as the registry made locks before `012m` -- is refused at use.
    model = llm.registry.model(model_id)
    assert model is not None
    connection = llm.registry.connection(model.connection_id)
    assert connection is not None
    verified = sorted(c.value for c in llm.registry.verified_capabilities(model_id))
    fingerprint = lock_fingerprint(
        connection,
        model.model_name,
        verified,
        qualification_of(llm.registry.latest_probes(model_id), verified),
    )
    db.execute(
        "UPDATE llm_models SET lifecycle = 'LOCKED', locked_capabilities = %s,"
        " lock_fingerprint = %s, locked_at = now(), locked_by = 'act:test'"
        " WHERE model_profile_id = %s",
        (verified, fingerprint, model_id),
    )
    locked = llm.registry.model(model_id)
    assert locked is not None
    problem = llm.registry.lock_problem(locked)
    assert problem is not None and "whose qualification semantics were not recorded" in problem
    runtime = llm.create_runtime("unrecorded", ["PUBLIC"])
    for slot in SLOTS:
        llm.bind(runtime.runtime_id, slot, model_id)
    blockers = llm.readiness(runtime.runtime_id).blockers
    assert any("whose qualification semantics were not recorded" in b for b in blockers), blockers
    # Applied as it was before `012m` (a direct activation), it is refused at the boundary.
    db.execute(
        "UPDATE llm_runtimes SET state = 'ACTIVE', activated_at = now(), activated_by = 'act:test'"
        " WHERE runtime_id = %s",
        (runtime.runtime_id,),
    )
    with pytest.raises(RuntimeUnavailable, match="whose qualification semantics were not recorded"):
        _load(db)
    assert all(
        p.qualification_digest is None for p in llm.registry.latest_probes(model_id).values()
    ), "the rows are left as they were"
