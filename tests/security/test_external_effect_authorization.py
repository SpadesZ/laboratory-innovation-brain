"""T-SEC-001 — an external side effect cannot happen before authorization succeeds, over a
classification the caller did not choose.

TWO DEFECTS, AND THE SECOND ONLY BECAME VISIBLE ONCE THE FIRST WAS CLOSED.

**The gate was optional.** `EgressGate` decided correctly and nothing was obliged to ask it:
`SourceRouter.search` called `adapter.search` directly and `ScientificLLM.invoke` called its
transport directly. A requirement a caller may decline to satisfy is a convention.
`AuthorizedExternalRunner` made it structural -- a required constructor argument with no `None`
branch, and `execute` performs only on ALLOW.

**The gate was deciding about a caller's claim.** Both entry points then took
`sensitivity=SensitivityLabel.PUBLIC` as an argument. So a caller assembling RESTRICTED_NDA
evidence declared PUBLIC, the gate answered correctly about a fiction, and the material left with
every check passing honestly. An authorization over a caller-supplied classification is a
caller-supplied authorization. The classification is now derived from `ArtifactOccurrence` rows
that ingestion wrote (§14.1), and a caller may only ADD labels.

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
from lab_brain.security.classification import ClassificationRefused, EgressClassification
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
from tests.classification_fixtures import artifact_id, labelled
from tests.conftest_fixtures import TOY_SCHEMA_REF

pytestmark = [pytest.mark.requirement("SEC-001"), pytest.mark.spec_test("T-SEC-001")]

PROJECT = "prj:test"
OTHER_PROJECT = "prj:other"
ACTOR = "act:test"
NOW = dt.datetime(2026, 9, 22, 11, 0, tzinfo=dt.UTC)

NDA_TEXT = "ACME 220nm PDK sidewall angle 83.4 deg, NDA-2026-117"

#: Four artifacts, three of which this project has classified. The fourth is deliberately absent
#: from the map: an artifact with no occurrence here is what an unclassifiable reference IS, and
#: needs no separate switch to simulate.
PUBLIC_ART = artifact_id("a public abstract")
NDA_ART = artifact_id("an NDA datasheet")
LAB_ART = artifact_id("unpublished lab work")
UNCLASSIFIED_ART = artifact_id("something this project does not hold")

LABELS = {
    PUBLIC_ART: SensitivityLabel.PUBLIC,
    NDA_ART: SensitivityLabel.RESTRICTED_NDA,
    LAB_ART: SensitivityLabel.CONFIDENTIAL_LAB,
}

#: `attestation -> artifact`, the hop a bundle's classification travels (§17.14.1 names
#: attestations; §17.2 records where each came from).
ATTESTED = {"att:public": PUBLIC_ART, "att:nda": NDA_ART, "att:lab": LAB_ART}


def _classifier(*, project_id: str = PROJECT):
    return labelled(LABELS, project_id=project_id, attestations=ATTESTED)


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


def _router(adapters, runner=None, *, project_id: str = PROJECT) -> SourceRouter:
    return SourceRouter(
        adapters,
        runner=runner or _runner(_policy()),
        classifier=_classifier(project_id=project_id),
    )


# ---------------------------------------------------------------------------
# 1–3. SourceRouter cannot reach an adapter without authorization
# ---------------------------------------------------------------------------


def test_restricted_nda_cannot_reach_adapter_search():
    """THE T-SEC-001 probe. §14.1 gives RESTRICTED_NDA no policy exception at all."""
    spy = _SpyAdapter("src:literature")
    results = _router([spy]).search(
        SourceQuery(NDA_TEXT),
        project_id=PROJECT,
        actor_id=ACTOR,
        context_artifact_ids=(NDA_ART,),
    )
    assert results == ()
    assert spy.entered == 0, "the adapter transport was entered for RESTRICTED_NDA material"


def test_confidential_lab_without_explicit_permission_cannot_reach_the_adapter():
    """§14.1 defaults CONFIDENTIAL_LAB to local unless a project policy says otherwise."""
    spy = _SpyAdapter("src:literature")
    results = _router([spy]).search(
        SourceQuery("unpublished ring topology"),
        project_id=PROJECT,
        actor_id=ACTOR,
        context_artifact_ids=(LAB_ART,),
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
    router = _router([spy], _runner(permissive, clearance=frozenset({SensitivityLabel.PUBLIC})))

    results = router.search(
        SourceQuery("unpublished ring topology"),
        project_id=PROJECT,
        actor_id=ACTOR,
        context_artifact_ids=(LAB_ART,),
    )
    assert results == ()
    assert spy.entered == 0


def test_an_unapproved_provider_cannot_be_reached_even_for_public_material():
    spy = _SpyAdapter("src:random-web")
    _router([spy]).search(
        SourceQuery("public abstract"),
        project_id=PROJECT,
        actor_id=ACTOR,
        context_artifact_ids=(PUBLIC_ART,),
    )
    assert spy.entered == 0


def test_a_missing_policy_does_not_read_as_local():
    """THE probe that keeps locality honest.

    A provider declared EXTERNAL with no project policy is REFUSED. Inferring "no policy, so it
    must be local" would make an unwired production deployment indistinguishable from a Private
    Mode one -- and the unwired deployment is the one that egresses everything.
    """
    spy = _SpyAdapter("src:literature", reach=ExternalReach.EXTERNAL)
    _router([spy], _runner(None)).search(
        SourceQuery("public abstract"),
        project_id=PROJECT,
        actor_id=ACTOR,
        context_artifact_ids=(PUBLIC_ART,),
    )
    assert spy.entered == 0


def test_a_declared_local_provider_works_with_no_policy_at_all():
    """§14.2's Private Mode must keep working. Declared LOCAL, so nothing leaves the boundary.

    The contrast with the previous test is the point: same missing policy, opposite outcome,
    decided by what the adapter DECLARES rather than by what the environment lacks.
    """
    local = _WorkingAdapter("src:local-corpus", reach=ExternalReach.LOCAL)
    results = _router([local], _runner(None)).search(
        SourceQuery("reverse bias"),
        project_id=PROJECT,
        actor_id=ACTOR,
        context_artifact_ids=(LAB_ART,),
    )
    assert results, "a declared-local provider was refused"
    assert local.entered == 1


def test_an_approved_public_search_reaches_the_adapter():
    """The positive control. Without it every assertion above could be a router that refuses all."""
    working = _WorkingAdapter("src:literature")
    results = _router([working]).search(
        SourceQuery("public abstract"),
        project_id=PROJECT,
        actor_id=ACTOR,
        context_artifact_ids=(PUBLIC_ART,),
    )
    assert len(results) == 1
    assert working.entered == 1


def test_fetch_by_name_raises_rather_than_silently_returning_nothing():
    """A caller naming one provider gets a refusal, not an empty result.

    Returning nothing would read as "no such record" when the truth is "you may not ask" --
    which sends the researcher to look for a document instead of to an approver.
    """
    spy = _SpyAdapter("src:literature")
    with pytest.raises(ExternalEffectRefused):
        _router([spy]).fetch(
            "src:literature",
            "doi:10.1000/x",
            project_id=PROJECT,
            actor_id=ACTOR,
            context_artifact_ids=(NDA_ART,),
        )
    assert spy.entered == 0


# ---------------------------------------------------------------------------
# 4. The classification is not the caller's to state
# ---------------------------------------------------------------------------


def test_a_caller_cannot_declare_nda_context_as_public():
    """THE downgrade attack, source side.

    The context is RESTRICTED_NDA and the caller declares PUBLIC. Under the old signature this
    was a supported call: the gate evaluated PUBLIC, permitted it, and the NDA-derived query left
    the boundary with every check passing honestly.

    `escalate` is a UNION with the derived set, so the declaration cannot remove
    RESTRICTED_NDA -- there is no subtraction operator anywhere in the classifier. The spy proves
    the ordering rather than the verdict.
    """
    spy = _SpyAdapter("src:literature")
    results = _router([spy]).search(
        SourceQuery(NDA_TEXT),
        project_id=PROJECT,
        actor_id=ACTOR,
        context_artifact_ids=(NDA_ART,),
        escalate=frozenset({SensitivityLabel.PUBLIC}),
    )
    assert results == ()
    assert spy.entered == 0, "a declared PUBLIC downgrade reached the transport"


def test_a_model_call_cannot_declare_nda_evidence_as_public():
    """The same attack on the model side, through the bundle's own attestations.

    The bundle names an attestation whose source artifact is RESTRICTED_NDA in this project. The
    caller declares PUBLIC. The transport is fatal, so reaching it fails loudly rather than
    producing a passing assertion about a returned decision.
    """
    model = ScientificLLM(
        slots=(ModelSlot(LogicalSlot.HYPOTHESIS, "cloud-model", "1.0.0", provider="src:cloud"),),
        prompts=(PromptTemplate("prm:hypothesis", "3.1.0", NDA_TEXT),),
        complete=_fatal_transport,
        runner=_runner(_policy()),
        classifier=_classifier(),
    )
    with pytest.raises(ExternalEffectRefused):
        model.invoke(
            inference_id="inf:1",
            slot=LogicalSlot.HYPOTHESIS,
            role="hypothesis_generator",
            prompt_id="prm:hypothesis",
            bundle=_bundle(("att:nda",)),
            trace_id="trc:1",
            project_id=PROJECT,
            actor_id=ACTOR,
            escalate=frozenset({SensitivityLabel.PUBLIC}),
            now=NOW,
        )


def test_escalation_adds_a_label_and_can_only_make_the_effect_stricter():
    """The other direction, which must keep working.

    A caller that believes a nominally PUBLIC artifact is being used in a restricted way may say
    so. The result is a refusal where the derivation alone would have allowed -- escalation is
    useful precisely because it changes the answer, and it changes it in one direction.
    """
    working = _WorkingAdapter("src:literature")
    router = _router([working])

    permitted = router.search(
        SourceQuery("public abstract"),
        project_id=PROJECT,
        actor_id=ACTOR,
        context_artifact_ids=(PUBLIC_ART,),
    )
    assert len(permitted) == 1

    escalated = router.search(
        SourceQuery("public abstract"),
        project_id=PROJECT,
        actor_id=ACTOR,
        context_artifact_ids=(PUBLIC_ART,),
        escalate=frozenset({SensitivityLabel.RESTRICTED_NDA}),
    )
    assert escalated == ()
    assert working.entered == 1, "the escalated call still reached the transport"


def test_unclassifiable_context_is_refused_rather_than_read_as_unrestricted():
    """Absence of a classification is not permission (§14.3).

    An artifact with no occurrence in this project cannot be classified here. Skipping it would
    mean a reference the project does not hold LOWERS the effective classification -- available
    to anyone who can name an id, which is the downgrade wearing a different hat.
    """
    spy = _SpyAdapter("src:literature")
    with pytest.raises(ClassificationRefused):
        _router([spy]).search(
            SourceQuery(NDA_TEXT),
            project_id=PROJECT,
            actor_id=ACTOR,
            context_artifact_ids=(PUBLIC_ART, UNCLASSIFIED_ART),
        )
    assert spy.entered == 0


def test_declaring_nothing_at_all_is_refused():
    """An empty classification would make the conjunction vacuous.

    Every label is asked about separately because §14.1's labels are categories rather than a
    ladder -- so "no labels" would be the most permissive thing a caller could say. It is the
    only remaining way to assert nothing about what is leaving, and it refuses.
    """
    spy = _SpyAdapter("src:literature")
    with pytest.raises(ClassificationRefused):
        _router([spy]).search(SourceQuery(NDA_TEXT), project_id=PROJECT, actor_id=ACTOR)
    assert spy.entered == 0


def test_a_mixed_bundle_must_satisfy_the_policy_for_every_label_it_carries():
    """Categories, not a ladder. Material carrying two labels needs both permitted.

    The policy here permits PUBLIC. The context is one PUBLIC artifact and one CONFIDENTIAL_LAB
    artifact. A "most restrictive wins" collapse would need an ordering `can_read_artifact`
    refuses to invent; a conjunction needs none and gives the same answer.
    """
    spy = _SpyAdapter("src:literature")
    results = _router([spy]).search(
        SourceQuery("mixed"),
        project_id=PROJECT,
        actor_id=ACTOR,
        context_artifact_ids=(PUBLIC_ART, LAB_ART),
    )
    assert results == ()
    assert spy.entered == 0


def test_a_bundle_from_another_project_cannot_import_its_classification():
    """A cross-project bundle would otherwise inherit a friendlier project's labels.

    §14.1 classifies per project (ADR-0010), so a bundle built in `prj:other` says nothing about
    what this project's policy governs. It is unresolvable here, and unresolvable is refused.
    """
    foreign = EvidenceBundle(
        research_intent=ResearchIntent(intent="DIAGNOSIS", stakes="HIGH"),
        query_text="why does Cj fall",
        source_policy_id="sp:diagnosis",
        source_policy_version="1.0.0",
        condition_schema_versions={"toy": TOY_SCHEMA_REF},
        ordered_attestation_ids=("att:public",),
        project_id=OTHER_PROJECT,
    )
    model = ScientificLLM(
        slots=(ModelSlot(LogicalSlot.HYPOTHESIS, "cloud-model", "1.0.0", provider="src:cloud"),),
        prompts=(PromptTemplate("prm:hypothesis", "3.1.0", "x"),),
        complete=_fatal_transport,
        runner=_runner(_policy()),
        classifier=_classifier(),
    )
    with pytest.raises(ClassificationRefused):
        model.invoke(
            inference_id="inf:1",
            slot=LogicalSlot.HYPOTHESIS,
            role="hypothesis_generator",
            prompt_id="prm:hypothesis",
            bundle=foreign,
            trace_id="trc:1",
            project_id=PROJECT,
            actor_id=ACTOR,
            now=NOW,
        )


def test_the_classifier_refuses_before_an_effect_is_ever_built():
    """The OUTER of two layers, tested on its own.

    `require_artifacts` raises, and `ExternalEffect.__post_init__` raises too. Both are wanted --
    the classifier gives the message naming what could not be resolved, and the constructor makes
    the bad state unrepresentable for any future caller that skips the classifier. But a probe
    that only exercised them together would let either one rot: the mutation battery kills the
    constructor's guard and the classifier's guard survives, because the other catches it.

    So this calls the classifier directly, and the next test calls the constructor directly.
    """
    classifier = _classifier()
    with pytest.raises(ClassificationRefused) as unresolved:
        classifier.require_artifacts((UNCLASSIFIED_ART,), project_id=PROJECT)
    assert UNCLASSIFIED_ART in str(unresolved.value)

    with pytest.raises(ClassificationRefused) as empty:
        classifier.require_artifacts((), project_id=PROJECT)
    assert "no sensitivity could be derived" in str(empty.value)

    # The positive control: the same call over a classified artifact returns a usable answer.
    usable = classifier.require_artifacts((PUBLIC_ART,), project_id=PROJECT)
    assert usable.labels == frozenset({SensitivityLabel.PUBLIC})
    assert usable.basis == (PUBLIC_ART,)


def test_an_effect_over_an_unusable_classification_cannot_be_constructed():
    """The refusal is structural, not a branch the runner remembers.

    `ExternalEffect.__post_init__` refuses an unusable classification, so there is no object
    representing "an effect over material nobody classified" for any code path to mishandle.
    """
    with pytest.raises(ClassificationRefused):
        ExternalEffect(
            project_id=PROJECT,
            actor_id=ACTOR,
            provider_id="src:literature",
            classification=EgressClassification(labels=frozenset()),
            material=NDA_TEXT,
        )


# ---------------------------------------------------------------------------
# 5. A scientific model call cannot reach its transport first
# ---------------------------------------------------------------------------


def _bundle(attestation_ids: tuple[str, ...] = ("att:public",)) -> EvidenceBundle:
    return EvidenceBundle(
        research_intent=ResearchIntent(intent="DIAGNOSIS", stakes="HIGH"),
        query_text="why does Cj fall",
        source_policy_id="sp:diagnosis",
        source_policy_version="1.0.0",
        condition_filter={},
        condition_schema_versions={"toy": TOY_SCHEMA_REF},
        ordered_attestation_ids=attestation_ids,
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
        classifier=_classifier(),
    )
    with pytest.raises(ExternalEffectRefused):
        model.invoke(
            inference_id="inf:1",
            slot=LogicalSlot.HYPOTHESIS,
            role="hypothesis_generator",
            prompt_id="prm:hypothesis",
            bundle=_bundle(("att:nda",)),
            trace_id="trc:1",
            project_id=PROJECT,
            actor_id=ACTOR,
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
        classifier=_classifier(),
    )
    output = model.invoke(
        inference_id="inf:1",
        slot=LogicalSlot.HYPOTHESIS,
        role="hypothesis_generator",
        prompt_id="prm:hypothesis",
        bundle=_bundle(("att:nda",)),
        trace_id="trc:1",
        project_id=PROJECT,
        actor_id=ACTOR,
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
        classifier=_classifier(),
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
            now=NOW,
        )


# ---------------------------------------------------------------------------
# 6. The refusal is audited, and carries no payload
# ---------------------------------------------------------------------------


def test_a_refused_effect_is_audited_without_the_payload():
    """§17.23: a POLICY_BLOCK emits an audit event. SEC-001: without logging the payload.

    Recorded by the runner rather than by the caller -- a caller that forgot would satisfy the
    gate and not the requirement.
    """
    runner = _runner(_policy())
    spy = _SpyAdapter("src:literature")
    _router([spy], runner).search(
        SourceQuery(NDA_TEXT),
        project_id=PROJECT,
        actor_id=ACTOR,
        context_artifact_ids=(NDA_ART,),
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
    _router([_WorkingAdapter("src:literature")], runner).search(
        SourceQuery("public"),
        project_id=PROJECT,
        actor_id=ACTOR,
        context_artifact_ids=(PUBLIC_ART,),
    )
    assert runner.audit.blocked() == ()


# ---------------------------------------------------------------------------
# 7. The dependency is structural, not conventional
# ---------------------------------------------------------------------------


def test_neither_component_can_be_built_without_a_runner_or_a_classifier():
    """THE structural claim, now covering both halves.

    An optional gate is not a gate, and a gate over a caller's claim is not an authorization.
    Neither collaborator has a default and neither has a `None` branch: a deployment missing
    either cannot construct the objects that perform external effects.
    """
    with pytest.raises(TypeError):
        SourceRouter([_SpyAdapter("src:x")])  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        SourceRouter([_SpyAdapter("src:x")], runner=_runner(_policy()))  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        ScientificLLM(  # type: ignore[call-arg]
            slots=(ModelSlot(LogicalSlot.HYPOTHESIS, "m", "1.0.0"),),
            prompts=(PromptTemplate("p", "1.0.0", "x"),),
            complete=_fatal_transport,
        )
    with pytest.raises(TypeError):
        ScientificLLM(  # type: ignore[call-arg]
            slots=(ModelSlot(LogicalSlot.HYPOTHESIS, "m", "1.0.0"),),
            prompts=(PromptTemplate("p", "1.0.0", "x"),),
            complete=_fatal_transport,
            runner=_runner(_policy()),
        )


def test_no_production_entry_point_still_accepts_a_sensitivity_argument():
    """The parameter itself is gone, not merely discouraged.

    A deprecated-but-accepted `sensitivity=` would keep every existing caller compiling while
    keeping the hole open. Checked against the signatures so the claim cannot rot into a comment.
    """
    import inspect

    for call in (SourceRouter.search, SourceRouter.fetch, ScientificLLM.invoke):
        assert "sensitivity" not in inspect.signature(call).parameters, (
            f"{call.__qualname__} still lets a caller state the sensitivity of what it sends"
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
                classification=_classifier().require_artifacts((NDA_ART,), project_id=PROJECT),
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
            classification=_classifier().require_artifacts((PUBLIC_ART,), project_id=PROJECT),
            material="public",
        )
    )
    assert decision.permitted

    router = _router([_SpyAdapter("src:literature")], runner)
    assert router.authorized_providers(
        project_id=PROJECT, actor_id=ACTOR, context_artifact_ids=(PUBLIC_ART,)
    ) == ("src:literature",)
    assert (
        router.authorized_providers(
            project_id=PROJECT, actor_id=ACTOR, context_artifact_ids=(NDA_ART,)
        )
        == ()
    )
