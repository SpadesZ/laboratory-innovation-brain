"""T-SEC-001 — an external side effect cannot happen before authorization succeeds.

THE DEFECT THESE PROBES CLOSE. `EgressGate` decided correctly and nothing was obliged to ask it:
`SourceRouter.search` called `adapter.search` directly and `ScientificLLM.invoke` called its
transport directly. SEC-001 says external connector/model egress *requires* policy and Actor
clearance, and a requirement a caller may decline to satisfy is a convention.

**EVERY SPY BELOW RAISES IF ENTERED.** That is the whole method. Asserting on a returned decision
would pass equally against an implementation that called the transport first and refused
afterwards -- by which time the NDA text has already left the process. What is being proven is
ordering, so the only way to prove it is to make the effect itself fatal.

LOCALITY IS DECLARED, NOT INFERRED, and one probe holds that line specifically: a provider that
merely lacks a policy must be refused, not treated as local. An unwired production deployment
looks exactly like a local one if locality is guessed.
"""

from __future__ import annotations

import datetime as dt

import pytest

from lab_brain.cognition.llm import ModelSlot, PromptTemplate, ScientificLLM
from lab_brain.core.models.enums import LicenseClass, SensitivityLabel, TrustClass
from lab_brain.core.models.evidence_bundle import EvidenceBundle, ResearchIntent
from lab_brain.core.models.inference import LogicalSlot
from lab_brain.security.egress import (
    EgressAuditLog,
    EgressGate,
    EgressPolicy,
    PrivacyMode,
)
from lab_brain.security.external import (
    AuthorizedExternalRunner,
    ExternalEffect,
    ExternalEffectRefused,
    ExternalReach,
)
from lab_brain.sources.adapter import (
    ExternalSourceRecord,
    SourceCapabilities,
    SourceHealthReport,
    SourceQuery,
    SourceRouter,
    SourceVisibility,
)
from tests.conftest_fixtures import TOY_SCHEMA_REF

pytestmark = [pytest.mark.requirement("SEC-001"), pytest.mark.spec_test("T-SEC-001")]

PROJECT = "prj:test"
ACTOR = "act:test"
NOW = dt.datetime(2026, 9, 22, 11, 0, tzinfo=dt.UTC)

NDA_TEXT = "ACME 220nm PDK sidewall angle 83.4 deg, NDA-2026-117"


class TransportEntered(AssertionError):
    """Raised by every spy. Its existence in a traceback IS the failure."""


class _SpyAdapter:
    """An adapter whose transport is fatal.

    `search` and `fetch` raise. A test that reaches them has proven the opposite of what it
    intended, and it fails with a message saying so rather than with a confusing AssertionError
    three frames away.
    """

    def __init__(self, provider: str, *, reach: ExternalReach = ExternalReach.EXTERNAL) -> None:
        self._provider = provider
        self._reach = reach
        self.entered = 0

    def provider_id(self) -> str:
        return self._provider

    def capabilities(self) -> SourceCapabilities:
        return SourceCapabilities(provider_id=self._provider, reach=self._reach)

    def healthcheck(self) -> SourceHealthReport:
        return SourceHealthReport(provider_id=self._provider, reachable=True)

    def search(self, query: SourceQuery):
        self.entered += 1
        raise TransportEntered(
            f"{self._provider}.search was entered; the material had already left the process "
            "before any authorization decision could refuse it"
        )

    def fetch(self, locator: str):
        self.entered += 1
        raise TransportEntered(f"{self._provider}.fetch was entered")


class _WorkingAdapter(_SpyAdapter):
    """The positive control: same shape, but the transport actually returns."""

    def search(self, query: SourceQuery):
        self.entered += 1
        return [
            ExternalSourceRecord(
                provider=self._provider,
                source_type="JOURNAL_ARTICLE",
                canonical_locator=f"doi:10.1000/{self._provider}",
                retrieved_at=NOW,
                visibility=SourceVisibility.PUBLIC,
                trust_class=TrustClass.PEER_REVIEWED,
                sensitivity=SensitivityLabel.PUBLIC,
                license_class=LicenseClass.PERMISSIVE,
            )
        ]


def _policy(**overrides) -> EgressPolicy:
    payload = {
        "policy_id": "egp:test",
        "version": "1.0.0",
        "project_id": PROJECT,
        "mode": PrivacyMode.RESEARCH,
        "declared_by_actor_id": "act:pi",
        "permitted_labels": frozenset({SensitivityLabel.PUBLIC}),
        "approved_providers": frozenset({"src:literature"}),
    }
    payload.update(overrides)
    return EgressPolicy(**payload)  # type: ignore[arg-type]


def _runner(
    policy: EgressPolicy | None = None,
    *,
    clearance: frozenset[SensitivityLabel] = frozenset({SensitivityLabel.PUBLIC}),
) -> AuthorizedExternalRunner:
    return AuthorizedExternalRunner(
        gate=EgressGate(
            policy_for=lambda _p: policy,
            clearance_of=lambda _a, _p: clearance,
        ),
        audit=EgressAuditLog(),
    )


# ---------------------------------------------------------------------------
# 1–3. SourceRouter cannot reach an adapter without authorization
# ---------------------------------------------------------------------------


def test_restricted_nda_cannot_reach_adapter_search():
    """THE T-SEC-001 probe. §14.1 gives RESTRICTED_NDA no policy exception at all."""
    spy = _SpyAdapter("src:literature")
    router = SourceRouter([spy], runner=_runner(_policy()))

    results = router.search(
        SourceQuery(NDA_TEXT),
        project_id=PROJECT,
        actor_id=ACTOR,
        sensitivity=SensitivityLabel.RESTRICTED_NDA,
    )
    assert results == ()
    assert spy.entered == 0, "the adapter transport was entered for RESTRICTED_NDA material"


def test_confidential_lab_without_explicit_permission_cannot_reach_the_adapter():
    """§14.1 defaults CONFIDENTIAL_LAB to local unless a project policy says otherwise."""
    spy = _SpyAdapter("src:literature")
    router = SourceRouter([spy], runner=_runner(_policy()))

    results = router.search(
        SourceQuery("unpublished ring topology"),
        project_id=PROJECT,
        actor_id=ACTOR,
        sensitivity=SensitivityLabel.CONFIDENTIAL_LAB,
    )
    assert results == ()
    assert spy.entered == 0


def test_an_actor_without_clearance_cannot_reach_the_adapter():
    """§14.3 requires policy AND Actor clearance.

    The policy permits CONFIDENTIAL_LAB; this actor does not hold it. The project approving a
    class of material is not every member being allowed to send it.
    """
    spy = _SpyAdapter("src:literature")
    permissive = _policy(
        permitted_labels=frozenset({SensitivityLabel.PUBLIC, SensitivityLabel.CONFIDENTIAL_LAB})
    )
    router = SourceRouter(
        [spy], runner=_runner(permissive, clearance=frozenset({SensitivityLabel.PUBLIC}))
    )

    results = router.search(
        SourceQuery("unpublished ring topology"),
        project_id=PROJECT,
        actor_id=ACTOR,
        sensitivity=SensitivityLabel.CONFIDENTIAL_LAB,
    )
    assert results == ()
    assert spy.entered == 0


def test_an_unapproved_provider_cannot_be_reached_even_for_public_material():
    spy = _SpyAdapter("src:random-web")
    router = SourceRouter([spy], runner=_runner(_policy()))
    router.search(
        SourceQuery("public abstract"),
        project_id=PROJECT,
        actor_id=ACTOR,
        sensitivity=SensitivityLabel.PUBLIC,
    )
    assert spy.entered == 0


def test_a_missing_policy_does_not_read_as_local():
    """THE probe that keeps locality honest.

    A provider declared EXTERNAL with no project policy is REFUSED. Inferring "no policy, so it
    must be local" would make an unwired production deployment indistinguishable from a Private
    Mode one -- and the unwired deployment is the one that egresses everything.
    """
    spy = _SpyAdapter("src:literature", reach=ExternalReach.EXTERNAL)
    router = SourceRouter([spy], runner=_runner(None))
    router.search(
        SourceQuery("public abstract"),
        project_id=PROJECT,
        actor_id=ACTOR,
        sensitivity=SensitivityLabel.PUBLIC,
    )
    assert spy.entered == 0


def test_a_declared_local_provider_works_with_no_policy_at_all():
    """§14.2's Private Mode must keep working. Declared LOCAL, so nothing leaves the boundary.

    The contrast with the previous test is the point: same missing policy, opposite outcome,
    decided by what the adapter DECLARES rather than by what the environment lacks.
    """
    local = _WorkingAdapter("src:local-corpus", reach=ExternalReach.LOCAL)
    router = SourceRouter([local], runner=_runner(None))
    results = router.search(
        SourceQuery("reverse bias"),
        project_id=PROJECT,
        actor_id=ACTOR,
        sensitivity=SensitivityLabel.CONFIDENTIAL_LAB,
    )
    assert results, "a declared-local provider was refused"
    assert local.entered == 1


def test_an_approved_public_search_reaches_the_adapter():
    """The positive control. Without it every assertion above could be a router that refuses all."""
    working = _WorkingAdapter("src:literature")
    router = SourceRouter([working], runner=_runner(_policy()))
    results = router.search(
        SourceQuery("public abstract"),
        project_id=PROJECT,
        actor_id=ACTOR,
        sensitivity=SensitivityLabel.PUBLIC,
    )
    assert len(results) == 1
    assert working.entered == 1


def test_fetch_by_name_raises_rather_than_silently_returning_nothing():
    """A caller naming one provider gets a refusal, not an empty result.

    Returning nothing would read as "no such record" when the truth is "you may not ask" --
    which sends the researcher to look for a document instead of to an approver.
    """
    spy = _SpyAdapter("src:literature")
    router = SourceRouter([spy], runner=_runner(_policy()))
    with pytest.raises(ExternalEffectRefused):
        router.fetch(
            "src:literature",
            "doi:10.1000/x",
            project_id=PROJECT,
            actor_id=ACTOR,
            sensitivity=SensitivityLabel.RESTRICTED_NDA,
        )
    assert spy.entered == 0


# ---------------------------------------------------------------------------
# 4. A scientific model call cannot reach its transport first
# ---------------------------------------------------------------------------


def _bundle() -> EvidenceBundle:
    return EvidenceBundle(
        research_intent=ResearchIntent(intent="DIAGNOSIS", stakes="HIGH"),
        query_text="why does Cj fall",
        source_policy_id="sp:diagnosis",
        source_policy_version="1.0.0",
        condition_filter={},
        condition_schema_versions={"toy": TOY_SCHEMA_REF},
        ordered_attestation_ids=("att:1",),
        project_id=PROJECT,
    )


def _fatal_transport(_text, _slot):
    raise TransportEntered(
        "the model transport was entered; the prompt had already left the process before "
        "SEC-001 could refuse it"
    )


def test_a_scientific_model_call_cannot_invoke_its_transport_before_authorization():
    """THE model half of T-SEC-001. §14.1: RESTRICTED_NDA may not reach a cloud model."""
    model = ScientificLLM(
        slots=(ModelSlot(LogicalSlot.HYPOTHESIS, "cloud-model", "1.0.0", provider="src:cloud"),),
        prompts=(PromptTemplate("prm:hypothesis", "3.1.0", NDA_TEXT),),
        complete=_fatal_transport,
        runner=_runner(_policy()),
    )
    with pytest.raises(ExternalEffectRefused):
        model.invoke(
            inference_id="inf:1",
            slot=LogicalSlot.HYPOTHESIS,
            role="hypothesis_generator",
            prompt_id="prm:hypothesis",
            bundle=_bundle(),
            trace_id="trc:1",
            project_id=PROJECT,
            actor_id=ACTOR,
            sensitivity=SensitivityLabel.RESTRICTED_NDA,
            now=NOW,
        )


def test_a_local_model_slot_runs_under_private_mode():
    """A model on this machine is a legitimate Private Mode slot, DECLARED as local."""
    model = ScientificLLM(
        slots=(
            ModelSlot(
                LogicalSlot.HYPOTHESIS,
                "local-model",
                "1.0.0",
                reach=ExternalReach.LOCAL,
            ),
        ),
        prompts=(PromptTemplate("prm:hypothesis", "3.1.0", "Consider the evidence"),),
        complete=lambda _t, _s: "a local answer",
        runner=_runner(None),
    )
    output = model.invoke(
        inference_id="inf:1",
        slot=LogicalSlot.HYPOTHESIS,
        role="hypothesis_generator",
        prompt_id="prm:hypothesis",
        bundle=_bundle(),
        trace_id="trc:1",
        project_id=PROJECT,
        actor_id=ACTOR,
        sensitivity=SensitivityLabel.RESTRICTED_NDA,
        now=NOW,
    )
    assert output.text == "a local answer"
    assert output.provenance.model_id == "local-model"


def test_an_undeclared_model_slot_with_no_policy_is_refused():
    """The same asymmetry as the source side: EXTERNAL by default, refused without a policy."""
    model = ScientificLLM(
        slots=(ModelSlot(LogicalSlot.HYPOTHESIS, "cloud-model", "1.0.0"),),
        prompts=(PromptTemplate("prm:hypothesis", "3.1.0", "x"),),
        complete=_fatal_transport,
        runner=_runner(None),
    )
    with pytest.raises(ExternalEffectRefused):
        model.invoke(
            inference_id="inf:1",
            slot=LogicalSlot.HYPOTHESIS,
            role="hypothesis_generator",
            prompt_id="prm:hypothesis",
            bundle=_bundle(),
            trace_id="trc:1",
            project_id=PROJECT,
            actor_id=ACTOR,
            sensitivity=SensitivityLabel.PUBLIC,
            now=NOW,
        )


# ---------------------------------------------------------------------------
# 5. The refusal is audited, and carries no payload
# ---------------------------------------------------------------------------


def test_a_refused_effect_is_audited_without_the_payload():
    """§17.23: a POLICY_BLOCK emits an audit event. SEC-001: without logging the payload.

    Recorded by the runner rather than by the caller -- a caller that forgot would satisfy the
    gate and not the requirement.
    """
    runner = _runner(_policy())
    spy = _SpyAdapter("src:literature")
    router = SourceRouter([spy], runner=runner)
    router.search(
        SourceQuery(NDA_TEXT),
        project_id=PROJECT,
        actor_id=ACTOR,
        sensitivity=SensitivityLabel.RESTRICTED_NDA,
    )

    blocked = runner.audit.blocked()
    assert len(blocked) == 1
    assert runner.audit.actors == [ACTOR]
    for surface in (repr(blocked), repr(runner.audit)):
        assert "ACME" not in surface
        assert "83.4" not in surface
        assert "NDA-2026-117" not in surface
    assert blocked[0].content_digest.startswith("sha256:")


def test_a_permitted_effect_is_not_recorded_as_a_block():
    """The log is evidence of refusals. Recording permitted traffic would bury them."""
    runner = _runner(_policy())
    router = SourceRouter([_WorkingAdapter("src:literature")], runner=runner)
    router.search(
        SourceQuery("public"),
        project_id=PROJECT,
        actor_id=ACTOR,
        sensitivity=SensitivityLabel.PUBLIC,
    )
    assert runner.audit.blocked() == ()


# ---------------------------------------------------------------------------
# 6. The dependency is structural, not conventional
# ---------------------------------------------------------------------------


def test_neither_component_can_be_built_without_a_runner():
    """THE structural claim. An optional gate is not a gate.

    There is no default and no `None` branch: a deployment that never wired authorization cannot
    construct the objects that perform external effects. That is what makes SEC-001 hold by
    construction rather than by every caller remembering.
    """
    with pytest.raises(TypeError):
        SourceRouter([_SpyAdapter("src:x")])  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        ScientificLLM(  # type: ignore[call-arg]
            slots=(ModelSlot(LogicalSlot.HYPOTHESIS, "m", "1.0.0"),),
            prompts=(PromptTemplate("p", "1.0.0", "x"),),
            complete=_fatal_transport,
        )


def test_the_runner_performs_nothing_when_it_refuses():
    """The runner's own contract, tested directly rather than only through its callers."""
    runner = _runner(_policy())
    entered = []

    def effectful():
        entered.append(True)
        raise TransportEntered("perform() was called on a refused effect")

    with pytest.raises(ExternalEffectRefused):
        runner.execute(
            ExternalEffect(
                project_id=PROJECT,
                actor_id=ACTOR,
                provider_id="src:literature",
                sensitivity=SensitivityLabel.RESTRICTED_NDA,
                material=NDA_TEXT,
            ),
            effectful,
        )
    assert entered == []


def test_authorize_is_a_read_and_performs_nothing():
    """`authorize` exists for UX surfaces. It must never be mistakeable for permission to run."""
    runner = _runner(_policy())
    decision = runner.authorize(
        ExternalEffect(
            project_id=PROJECT,
            actor_id=ACTOR,
            provider_id="src:literature",
            sensitivity=SensitivityLabel.PUBLIC,
            material="public",
        )
    )
    assert decision.permitted

    router = SourceRouter([_SpyAdapter("src:literature")], runner=runner)
    assert router.authorized_providers(
        project_id=PROJECT, actor_id=ACTOR, sensitivity=SensitivityLabel.PUBLIC
    ) == ("src:literature",)
    assert (
        router.authorized_providers(
            project_id=PROJECT, actor_id=ACTOR, sensitivity=SensitivityLabel.RESTRICTED_NDA
        )
        == ()
    )
