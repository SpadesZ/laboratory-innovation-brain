"""T-LLM-001 / T-SRC-001 — the model boundary and the source boundary (§7.3, §7.6, §17.14, §17.21).

    T-LLM-001  Hypothesis/Critique/Relation 缺 model/prompt/bundle provenance 時 admission fail；
               且既存於庫中而無 InferenceProvenance 的舊推論不得作為新 belief transition 的依據
               -- 以該推論為唯一 basis 的 transition 被拒絕，理由可追溯（§7.6）。
               **僅測 admission 不足以通過。**
    T-SRC-001  以 fake GitHub/Literature connectors 替換真 provider 時 SourceRouter/cognition 不需
               修改；normalized record schema 相同。

The bolded sentence in T-LLM-001 is why half this file is about records that already exist. A
check that only ran at creation would never see them -- and they are exactly what §7.6 is about.
"""

from __future__ import annotations

import ast
import datetime as dt
import inspect

import pytest

from lab_brain.cognition import llm as llm_module
from lab_brain.cognition.llm import (
    BeliefBasisGate,
    LLMRefusal,
    LLMRefusalReason,
    ModelSlot,
    PromptTemplate,
    ScientificLLM,
)
from lab_brain.core.models.enums import LicenseClass, SensitivityLabel, TrustClass
from lab_brain.core.models.evidence_bundle import EvidenceBundle, ResearchIntent
from lab_brain.core.models.inference import InferenceProvenance, LogicalSlot
from lab_brain.security.egress import EgressAuditLog, EgressGate, EgressPolicy, PrivacyMode
from lab_brain.security.external import AuthorizedExternalRunner, ExternalReach
from lab_brain.sources import adapter as adapter_module
from lab_brain.sources.adapter import (
    ExternalSourceRecord,
    ProviderUnavailable,
    SourceCapabilities,
    SourceHealthReport,
    SourceQuery,
    SourceRouter,
    SourceVisibility,
)
from tests.conftest_fixtures import TOY_SCHEMA_REF

NOW = dt.datetime(2026, 9, 21, 12, 0, tzinfo=dt.UTC)
PROJECT = "prj:test"

llm001 = [pytest.mark.requirement("LLM-001"), pytest.mark.spec_test("T-LLM-001")]


def _bundle(attestation_ids: tuple[str, ...] = ("att:1", "att:2")) -> EvidenceBundle:
    return EvidenceBundle(
        research_intent=ResearchIntent(intent="DIAGNOSIS", stakes="HIGH"),
        query_text="why does Cj fall with reverse bias",
        source_policy_id="sp:diagnosis",
        source_policy_version="1.0.0",
        condition_filter={"setting": "nominal"},
        condition_schema_versions={"toy": TOY_SCHEMA_REF},
        ordered_attestation_ids=attestation_ids,
        project_id=PROJECT,
    )


def _runner() -> AuthorizedExternalRunner:
    """A permissive-but-real runner. SEC-001's own refusals are proven in
    `tests/security/test_external_effect_authorization.py`; here the point is the provenance
    discipline, so the gate is wired to allow the PUBLIC material these fixtures use."""
    return AuthorizedExternalRunner(
        gate=EgressGate(
            policy_for=lambda _p: EgressPolicy(
                policy_id="egp:test",
                version="1.0.0",
                project_id=PROJECT,
                mode=PrivacyMode.RESEARCH,
                declared_by_actor_id="act:pi",
                permitted_labels=frozenset({SensitivityLabel.PUBLIC}),
                approved_providers=frozenset({"src:literature", "src:github", "src:patents"}),
            ),
            clearance_of=lambda _a, _p: frozenset({SensitivityLabel.PUBLIC}),
        ),
        audit=EgressAuditLog(),
    )


def _llm(*, slots: tuple[ModelSlot, ...] | None = None, reply: str = "a critique") -> ScientificLLM:
    configured = slots or (
        ModelSlot(
            LogicalSlot.HYPOTHESIS,
            "toy-model",
            "1.0.0",
            provider="local",
            reach=ExternalReach.LOCAL,
        ),
        ModelSlot(
            LogicalSlot.CRITIQUE,
            "toy-critic",
            "2.0.0",
            provider="local",
            reach=ExternalReach.LOCAL,
        ),
    )
    return ScientificLLM(
        slots=configured,
        prompts=(PromptTemplate("prm:hypothesis", "3.1.0", "Consider {evidence}"),),
        complete=lambda _text, _slot: reply,
        runner=_runner(),
        source_policy_version="srp:1.0.0",
    )


def _invoke(model: ScientificLLM, **overrides):
    payload = {
        "inference_id": "inf:1",
        "slot": LogicalSlot.HYPOTHESIS,
        "role": "hypothesis_generator",
        "prompt_id": "prm:hypothesis",
        "bundle": _bundle(),
        "trace_id": "trc:1",
        "project_id": PROJECT,
        "actor_id": "act:test",
        "sensitivity": SensitivityLabel.PUBLIC,
        "now": NOW,
    }
    payload.update(overrides)
    return model.invoke(**payload)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# LLM-001, write side
# ---------------------------------------------------------------------------


@pytest.mark.requirement("LLM-001")
@pytest.mark.spec_test("T-LLM-001")
def test_a_scientific_output_carries_the_whole_provenance():
    """§17.14's five required facts, plus the bundle hash that distinguishes two runs."""
    output = _invoke(_llm())
    p = output.provenance
    assert p.model_id == "toy-model"
    assert p.model_version == "1.0.0"
    assert p.logical_slot is LogicalSlot.HYPOTHESIS
    assert p.prompt_id == "prm:hypothesis"
    assert p.prompt_version == "3.1.0"
    assert p.evidence_bundle_hash == _bundle().canonical_hash
    assert p.source_policy_version == "srp:1.0.0"
    assert p.trace_id == "trc:1"


@pytest.mark.requirement("LLM-001")
@pytest.mark.spec_test("T-LLM-001")
def test_a_call_without_an_evidence_bundle_is_refused_before_the_model_is_reached():
    """No bundle means no bundle hash, and §17.14 requires one.

    Refused BEFORE the call: a completion whose provenance cannot be recorded has produced an
    output that may not be used, and having spent budget on it is the only consequence left.
    Asserted by making the transport raise if it is ever entered.
    """

    def must_not_be_called(_text, _slot):  # pragma: no cover - the assertion is that it is not
        raise AssertionError("the model was called despite provenance being impossible")

    model = ScientificLLM(
        slots=(ModelSlot(LogicalSlot.HYPOTHESIS, "toy-model", "1.0.0", reach=ExternalReach.LOCAL),),
        prompts=(PromptTemplate("prm:hypothesis", "3.1.0", "x"),),
        complete=must_not_be_called,
        runner=_runner(),
    )
    with pytest.raises(LLMRefusal) as caught:
        _invoke(model, bundle=None)
    assert caught.value.reason is LLMRefusalReason.NO_EVIDENCE_BUNDLE


@pytest.mark.requirement("LLM-001")
@pytest.mark.spec_test("T-LLM-001")
def test_an_empty_slot_refuses_rather_than_routing_elsewhere():
    """§7.3's slots may be empty. Silently routing to another slot's model would make the
    recorded route a fiction -- and §7.6's independence check reads that route."""
    only_critique = _llm(
        slots=(ModelSlot(LogicalSlot.CRITIQUE, "toy-critic", "2.0.0", reach=ExternalReach.LOCAL),)
    )
    with pytest.raises(LLMRefusal) as caught:
        _invoke(only_critique)
    assert caught.value.reason is LLMRefusalReason.SLOT_NOT_CONFIGURED


@pytest.mark.requirement("LLM-001")
@pytest.mark.spec_test("T-LLM-001")
def test_an_unregistered_prompt_is_refused():
    """A prompt with no registered version makes every inference from it unreproducible."""
    with pytest.raises(LLMRefusal) as caught:
        _invoke(_llm(), prompt_id="prm:improvised")
    assert caught.value.reason is LLMRefusalReason.PROMPT_VERSION_MISSING


@pytest.mark.requirement("LLM-001")
@pytest.mark.spec_test("T-LLM-001")
def test_the_provenance_comes_from_the_call_not_from_the_model_reply():
    """A model asked to describe its own provenance is being asked to be its own witness.

    The transport returns text claiming a different model and prompt. None of it reaches the
    record, because the record is built from what the caller and the registry know.
    """
    liar = _llm(reply='{"model_id": "gpt-9", "prompt_version": "99.0.0"}')
    provenance = _invoke(liar).provenance
    assert provenance.model_id == "toy-model"
    assert provenance.prompt_version == "3.1.0"


@pytest.mark.requirement("LLM-001")
@pytest.mark.spec_test("T-LLM-001")
def test_two_runs_over_different_bundles_are_distinguishable():
    """The field people leave out, and what it buys.

    Same prompt, same model, different retrieval context. Without the bundle hash these two
    contradictory inferences would look like the same inference twice.
    """
    first = _invoke(_llm(), inference_id="inf:1", bundle=_bundle(("att:1", "att:2")))
    second = _invoke(_llm(), inference_id="inf:2", bundle=_bundle(("att:3",)))
    assert first.provenance.evidence_bundle_hash != second.provenance.evidence_bundle_hash
    assert first.provenance.model_ref == second.provenance.model_ref


@pytest.mark.requirement("LLM-001")
@pytest.mark.spec_test("T-LLM-001")
def test_a_critique_that_changed_nothing_is_refused():
    """§7.6: 不同 provider 不是科學獨立性的充分條件.

    Same bundle, same policy, same route, run again. That is the same inference a second time,
    and presenting it as independent corroboration is the self-citation EVI-003 and §6.17 exist
    to prevent.
    """
    model = _llm()
    original = _invoke(model, slot=LogicalSlot.CRITIQUE, inference_id="inf:0").provenance
    with pytest.raises(LLMRefusal) as caught:
        model.critique(
            original=original,
            inference_id="inf:1",
            prompt_id="prm:hypothesis",
            bundle=_bundle(),
            trace_id="trc:1",
            project_id=PROJECT,
            actor_id="act:test",
            sensitivity=SensitivityLabel.PUBLIC,
            now=NOW,
        )
    assert caught.value.reason is LLMRefusalReason.CRITIQUE_ROUTE_UNCHANGED


@pytest.mark.requirement("LLM-001")
@pytest.mark.spec_test("T-LLM-001")
def test_a_critique_over_a_different_bundle_is_accepted():
    """The positive control, and it pins which change counts: the retrieval bundle."""
    model = _llm()
    original = _invoke(model, slot=LogicalSlot.CRITIQUE, inference_id="inf:0").provenance
    output = model.critique(
        original=original,
        inference_id="inf:1",
        prompt_id="prm:hypothesis",
        bundle=_bundle(("att:9",)),
        trace_id="trc:1",
        project_id=PROJECT,
        actor_id="act:test",
        sensitivity=SensitivityLabel.PUBLIC,
        now=NOW,
    )
    assert output.provenance.inference_id == "inf:1"


@pytest.mark.requirement("LLM-001")
@pytest.mark.spec_test("T-LLM-001")
def test_a_provenance_with_a_blank_required_field_cannot_be_built():
    """A half-filled provenance is indistinguishable at read time from one never checked."""
    base = _invoke(_llm()).provenance.model_dump()
    for blank in ("model_id", "model_version", "prompt_id", "prompt_version", "trace_id"):
        with pytest.raises(ValueError, match=blank):
            InferenceProvenance.model_validate({**base, blank: "   "})
    with pytest.raises(ValueError, match="evidence_bundle_hash"):
        InferenceProvenance.model_validate({**base, "evidence_bundle_hash": ""})


@pytest.mark.requirement("LLM-001")
@pytest.mark.spec_test("T-LLM-001")
def test_no_llm_path_writes_evidence_or_belief():
    """ "No LLM may directly mutate evidence or belief state."

    Structural: the cognition module imports nothing that could write. A model that could write
    belief directly would make EVI-003's typing rule and §8.2.1's policy requirement optional.
    """
    tree = ast.parse(inspect.getsource(llm_module))
    imported = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    for name in imported:
        assert "repositories" not in name, f"cognition imports a repository: {name}"
        assert "belief" not in name, f"cognition imports the belief path: {name}"
        assert "storage" not in name, f"cognition imports storage: {name}"


# ---------------------------------------------------------------------------
# LLM-001, read side — the half §26 says admission alone cannot satisfy
# ---------------------------------------------------------------------------


def _basis_gate(with_provenance: frozenset[str], inferences: frozenset[str]) -> BeliefBasisGate:
    sample = _invoke(_llm()).provenance
    return BeliefBasisGate(
        load_provenance=lambda ref: sample if ref in with_provenance else None,
        is_inference=lambda ref: ref in inferences,
    )


@pytest.mark.requirement("LLM-001")
@pytest.mark.spec_test("T-LLM-001")
def test_a_stored_inference_without_provenance_cannot_be_the_sole_basis():
    """THE T-LLM-001 read-side probe. §7.6: 無 provenance 的舊推論不可作為新 belief transition 的依據.

    The record already exists -- it predates the rule, which is the situation the rule is about.
    A check that ran only at creation would never see it.
    """
    gate = _basis_gate(with_provenance=frozenset(), inferences=frozenset({"inf:legacy"}))
    decision = gate.evaluate(["inf:legacy"])
    assert not decision.permitted
    assert decision.reason_code == LLMRefusalReason.INFERENCE_WITHOUT_PROVENANCE.value
    assert "inf:legacy" in decision.detail, "the refusal is not traceable to the record"

    with pytest.raises(LLMRefusal):
        gate.require(["inf:legacy"])


@pytest.mark.requirement("LLM-001")
@pytest.mark.spec_test("T-LLM-001")
def test_a_provenanced_inference_may_be_the_sole_basis():
    """The positive control. Without it the gate could be refusing every inference."""
    gate = _basis_gate(
        with_provenance=frozenset({"inf:modern"}), inferences=frozenset({"inf:modern"})
    )
    assert gate.evaluate(["inf:modern"]).permitted


@pytest.mark.requirement("LLM-001")
@pytest.mark.spec_test("T-LLM-001")
def test_a_legacy_inference_beside_real_evidence_is_not_the_sole_basis():
    """ "SOLE basis" is the spec's word and it is load-bearing.

    §7.6 forbids such an inference being *the* 依據. A transition also resting on a measured
    attestation is not resting on the inference alone, and refusing that case would make legacy
    records unusable rather than untrustworthy -- a different policy, and not the stated one.
    """
    gate = _basis_gate(with_provenance=frozenset(), inferences=frozenset({"inf:legacy"}))
    decision = gate.evaluate(["inf:legacy", "att:measured"])
    assert decision.permitted
    assert decision.reason_code == "BASIS_TRACEABLE_WITHOUT_LEGACY"
    assert "att:measured" in decision.detail


@pytest.mark.requirement("LLM-001")
@pytest.mark.spec_test("T-LLM-001")
def test_an_empty_basis_is_refused():
    """A transition with no basis has nothing to be traceable to."""
    gate = _basis_gate(frozenset(), frozenset())
    assert not gate.evaluate([]).permitted


@pytest.mark.requirement("LLM-001")
@pytest.mark.spec_test("T-LLM-001")
def test_not_an_inference_and_an_inference_without_provenance_are_different_answers():
    """Collapsing them into one `load -> None` would make a measured attestation look legacy."""
    gate = _basis_gate(with_provenance=frozenset(), inferences=frozenset({"inf:legacy"}))
    assert gate.evaluate(["att:measured"]).permitted
    assert not gate.evaluate(["inf:legacy"]).permitted


# ---------------------------------------------------------------------------
# SRC-001
# ---------------------------------------------------------------------------


class _FakeAdapter:
    """A deterministic local adapter. No network, no provider SDK."""

    def __init__(self, provider: str, *, reachable: bool = True, records: int = 2) -> None:
        self._provider = provider
        self._reachable = reachable
        self._records = records

    def provider_id(self) -> str:
        return self._provider

    def capabilities(self) -> SourceCapabilities:
        # LOCAL, because this file is about the SRC-001 contract. SEC-001's refusals get their
        # own file with a transport that raises; declaring locality here keeps the two
        # requirements from being proven by each other's fixtures.
        return SourceCapabilities(
            provider_id=self._provider,
            can_search=True,
            can_fetch=True,
            reach=ExternalReach.LOCAL,
        )

    def healthcheck(self) -> SourceHealthReport:
        return SourceHealthReport(
            provider_id=self._provider,
            reachable=self._reachable,
            detail="" if self._reachable else "connection refused",
        )

    def _record(self, n: int) -> ExternalSourceRecord:
        return ExternalSourceRecord(
            provider=self._provider,
            source_type="JOURNAL_ARTICLE",
            canonical_locator=f"doi:10.1000/{self._provider}.{n}",
            retrieved_at=NOW,
            visibility=SourceVisibility.PUBLIC,
            trust_class=TrustClass.PEER_REVIEWED,
            sensitivity=SensitivityLabel.PUBLIC,
            title=f"Result {n}",
            license_class=LicenseClass.PERMISSIVE,
        )

    def search(self, query: SourceQuery):
        return [self._record(n) for n in range(self._records)]

    def fetch(self, locator: str):
        return self._record(0) if locator.startswith("doi:") else None


@pytest.mark.requirement("SRC-001")
@pytest.mark.spec_test("T-SRC-001")
def test_swapping_adapters_changes_no_router_or_cognition_code():
    """§26's pass condition, stated as an experiment.

    The router is constructed with one set of adapters and then another. Nothing about the call
    changes, and the record schema is the same object in both cases -- which is what
    "normalized record schema 相同" means operationally.
    """
    router = SourceRouter([_FakeAdapter("src:literature")], runner=_runner())
    first = router.search(
        SourceQuery("cj reverse bias"),
        project_id=PROJECT,
        actor_id="act:test",
        sensitivity=SensitivityLabel.PUBLIC,
    )

    swapped = SourceRouter(
        [_FakeAdapter("src:github"), _FakeAdapter("src:patents")], runner=_runner()
    )
    second = swapped.search(
        SourceQuery("cj reverse bias"),
        project_id=PROJECT,
        actor_id="act:test",
        sensitivity=SensitivityLabel.PUBLIC,
    )

    assert {type(r) for r in first} == {type(r) for r in second} == {ExternalSourceRecord}
    assert {r.provider for r in second} == {"src:github", "src:patents"}
    assert all(isinstance(r.canonical_locator, str) for r in first + second)


@pytest.mark.requirement("SRC-001")
@pytest.mark.spec_test("T-SRC-001")
def test_removing_an_adapter_does_not_prevent_startup_or_search():
    """A router that raised on a missing adapter would make every deployment carry every
    provider -- and one provider's outage would be an outage in all of them."""
    router = SourceRouter(
        [_FakeAdapter("src:literature"), _FakeAdapter("src:github")], runner=_runner()
    )
    router.remove("src:github")
    assert router.providers == ("src:literature",)
    assert router.search(
        SourceQuery("anything"),
        project_id=PROJECT,
        actor_id="act:test",
        sensitivity=SensitivityLabel.PUBLIC,
    ), "search broke when an adapter was removed"

    empty = SourceRouter(runner=_runner())
    assert empty.providers == ()
    assert (
        empty.search(
            SourceQuery("anything"),
            project_id=PROJECT,
            actor_id="act:test",
            sensitivity=SensitivityLabel.PUBLIC,
        )
        == ()
    )
    assert empty.health() == ()


@pytest.mark.requirement("SRC-001")
@pytest.mark.spec_test("T-SRC-001")
def test_an_unreachable_provider_is_skipped_rather_than_failing_the_query():
    """UX-007 renders a degraded connector as health. Raising here would turn one provider's
    outage into a failed research query, and the researcher would learn nothing about which."""
    router = SourceRouter(
        [_FakeAdapter("src:literature"), _FakeAdapter("src:offline", reachable=False)],
        runner=_runner(),
    )
    results = router.search(
        SourceQuery("anything"),
        project_id=PROJECT,
        actor_id="act:test",
        sensitivity=SensitivityLabel.PUBLIC,
    )
    assert {r.provider for r in results} == {"src:literature"}
    assert {h.provider_id for h in router.health() if not h.reachable} == {"src:offline"}


@pytest.mark.requirement("SRC-001")
@pytest.mark.spec_test("T-SRC-001")
def test_fetching_by_name_from_a_missing_or_unreachable_provider_raises():
    """Naming a provider is a different request from searching all of them.

    Silently substituting another provider would change where the evidence came from without
    saying so, which is a provenance corruption rather than a degraded query.
    """
    router = SourceRouter([_FakeAdapter("src:offline", reachable=False)], runner=_runner())
    with pytest.raises(ProviderUnavailable, match="no adapter registered"):
        router.fetch(
            "src:absent",
            "doi:10.1000/x",
            project_id=PROJECT,
            actor_id="act:test",
            sensitivity=SensitivityLabel.PUBLIC,
        )
    with pytest.raises(ProviderUnavailable, match="unreachable"):
        router.fetch(
            "src:offline",
            "doi:10.1000/x",
            project_id=PROJECT,
            actor_id="act:test",
            sensitivity=SensitivityLabel.PUBLIC,
        )


@pytest.mark.requirement("SRC-001")
@pytest.mark.spec_test("T-SRC-001")
def test_search_results_are_ordered_deterministically():
    """A retrieval whose order depended on registry iteration would not be reproducible, and
    EVI-006's bundle hash is computed over an ordered set."""
    adapters = [_FakeAdapter("src:b"), _FakeAdapter("src:a")]
    first = SourceRouter(adapters, runner=_runner()).search(
        SourceQuery("x"),
        project_id=PROJECT,
        actor_id="act:test",
        sensitivity=SensitivityLabel.PUBLIC,
    )
    second = SourceRouter(list(reversed(adapters)), runner=_runner()).search(
        SourceQuery("x"),
        project_id=PROJECT,
        actor_id="act:test",
        sensitivity=SensitivityLabel.PUBLIC,
    )
    assert [r.canonical_locator for r in first] == [r.canonical_locator for r in second]


@pytest.mark.requirement("SRC-001")
@pytest.mark.spec_test("T-SRC-001")
def test_the_router_names_no_provider():
    """§24.2's boundary, checked structurally.

    The moment a `if provider == "github"` exists, the router has a second contract -- the real
    one, and the one it documents. Parsed rather than grepped so the module's own prose about
    providers does not trip it.
    """
    tree = ast.parse(inspect.getsource(adapter_module))
    literals = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    docstrings = {
        id(n.body[0].value)
        for n in ast.walk(tree)
        if isinstance(n, ast.Module | ast.ClassDef | ast.FunctionDef)
        and n.body
        and isinstance(n.body[0], ast.Expr)
        and isinstance(n.body[0].value, ast.Constant)
    }
    code_literals = [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings
    ]
    for provider in ("github", "arxiv", "crossref", "semanticscholar", "openai"):
        assert not any(provider in lit.lower() for lit in code_literals), (
            f"the router names {provider} in code; §24.2 keeps provider specifics out"
        )
    # The stdlib is fine; a provider SDK is not. §24.2 is about vendor coupling, not about
    # whether `dataclasses` may be imported.
    imported = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
        alias.name for n in ast.walk(tree) if isinstance(n, ast.Import) for alias in n.names
    }
    vendor = {
        name
        for name in imported
        if not name.startswith(("lab_brain", "__future__"))
        and name.split(".")[0] not in {"dataclasses", "typing", "collections", "enum", "datetime"}
    }
    assert vendor == set(), f"the router imports a provider SDK: {sorted(vendor)}"
    assert literals, "the parse found nothing; the assertion above would be vacuous"
