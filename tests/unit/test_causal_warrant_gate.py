"""The Causal Warrant Gate, domain-general: the policy, the declarations, the resolver, the rule.

Nothing here is silicon photonics. Two toy domains written for these tests -- an optical fibre
link losing power and a web service timing out -- exercise every part of the gate, so a pass does
not depend on the SP catalog's wording or on the benchmark cases it was written around. The SP
pack's own declarations are checked only for their pinned digest.

What is asserted, in the order the gate applies it:

    declarations   a class is bound by its exact mechanism AND agreeing predictions; no outcome is
                   two classes' signature; the set's identity is pinned by digest
    resolver       warrants come from declarations or grants, never from authorship; a recorded
                   record that does not re-check against its sources is refused
    policy         a gated SUPPORTS/CONTRADICTS counts only when warranted; authority, conditions
                   and independence are read from warranted relations only; a person is asked only
                   when a warrant would change the verdict; ungated policies decide as before
    snapshot       an empty `relation_evidence` leaves the canonical form -- and every stored hash --
                   exactly as it was
    confirmation   one class, warranted support, no rival affirming the same observation unless a
                   warranted refutation excludes it, no answer pending that could overturn it
"""

from __future__ import annotations

import ast
import datetime as dt
from pathlib import Path
from typing import Any, cast

import pytest

from lab_brain.core.models.belief_event import BeliefState
from lab_brain.core.models.decision import DecisionInputSnapshot
from lab_brain.core.models.enums import RelationType
from lab_brain.core.models.hypothesis import Hypothesis
from lab_brain.core.models.hypothesis_set import HypothesisCertificate, HypothesisSet
from lab_brain.core.models.prediction import Prediction, RelationJudgmentTemplate
from lab_brain.core.models.relation import RelationJudgment
from lab_brain.core.models.transition import (
    HypothesisView,
    IndependenceSummary,
    RelationEvidence,
    TransitionOutcome,
    TransitionPolicy,
    TransitionReason,
    WarrantBasis,
)
from lab_brain.core.models.warrant import (
    DiagnosticDeclaration,
    DiagnosticDeclarationSet,
    DiagnosticWarrantGrant,
    GrantVerdict,
    Link,
)
from lab_brain.core.warrant import WarrantResolver, WarrantUnverified, domain_warrant
from lab_brain.verification.loop import LoopDependencies, LoopRequest, VerificationLoop

T0 = dt.datetime(2026, 10, 14, 9, 0, tzinfo=dt.UTC)
PROJECT = "prj:toy"
SRC = Path(__file__).resolve().parents[2] / "src" / "lab_brain"

# -- two toy domains ---------------------------------------------------------------------------

FIBRE = DiagnosticDeclarationSet(
    set_id="fl.loss_mechanisms",
    version="1.0.0",
    domain="fibre_link",
    declarations=(
        DiagnosticDeclaration(
            class_id="contamination",
            mechanism="connector end-face contamination",
            statement="Debris on a connector end-face scatters light at the mating point.",
            observable_ref="fl.endface",
            outcome_space_id="os:fl.endface",
            outcome_space_version="1.0.0",
            supports_outcome="DIRTY",
            refutes_outcomes=("CLEAN",),
        ),
        DiagnosticDeclaration(
            class_id="macrobend",
            mechanism="macrobend in the patch run",
            statement="A tight bend leaks the guided mode into the cladding.",
            observable_ref="fl.otdr_bend",
            outcome_space_id="os:fl.otdr_bend",
            outcome_space_version="1.0.0",
            supports_outcome="WAVELENGTH_DEPENDENT_STEP",
            refutes_outcomes=("NO_STEP", "FLAT_STEP"),
        ),
    ),
)

INCIDENT = DiagnosticDeclarationSet(
    set_id="web.timeout_causes",
    version="1.0.0",
    domain="web_service",
    declarations=(
        DiagnosticDeclaration(
            class_id="pool_exhaustion",
            mechanism="database connection pool exhaustion",
            statement="Requests wait for a connection the pool cannot hand out.",
            observable_ref="web.pool_wait",
            outcome_space_id="os:web.pool_wait",
            outcome_space_version="1.0.0",
            supports_outcome="SATURATED_WAITING",
            refutes_outcomes=("IDLE_CAPACITY",),
        ),
        DiagnosticDeclaration(
            class_id="slow_query",
            mechanism="slow query regression",
            statement="A changed query plan makes one statement orders of magnitude slower.",
            observable_ref="web.query_latency",
            outcome_space_id="os:web.query_latency",
            outcome_space_version="1.0.0",
            supports_outcome="REGRESSED",
            refutes_outcomes=("BASELINE",),
        ),
    ),
)


def prediction(
    hypothesis: str,
    observable: str,
    outcome: str,
    effect: RelationType,
    *,
    key: str = "",
) -> Prediction:
    return Prediction(
        prediction_id=f"prd:{hypothesis}.{key or outcome.lower()}",
        hypothesis_id=f"hyp:{hypothesis}",
        project_id=PROJECT,
        observable_ref=observable,
        outcome_space_id=f"os:{observable}",
        outcome_space_version="1.0.0",
        expected_outcome=outcome,
        relation_effect_if_observed=(
            RelationJudgmentTemplate(relation_type=effect, to_entity_id=f"hyp:{hypothesis}"),
        ),
    )


def certificate(
    hypothesis: str, mechanism: str, predictions: tuple[Prediction, ...], **hypothesis_fields: Any
) -> HypothesisCertificate:
    return HypothesisCertificate(
        hypothesis=Hypothesis(
            hypothesis_id=f"hyp:{hypothesis}",
            project_id=PROJECT,
            statement=f"{mechanism} explains the symptom.",
            mechanism=mechanism,
            prediction_ids=tuple(p.prediction_id for p in predictions),
            falsifier="its refuting outcome",
            **hypothesis_fields,
        ),
        hypothesis_set_id="hst:toy",
        predictions=predictions,
        created_at=T0,
    )


def observed(
    p: Prediction, *, observation: str = "obs:1", relation_id: str = ""
) -> RelationJudgment:
    return RelationJudgment(
        relation_id=relation_id or f"rel:{p.prediction_id}",
        from_entity_id=observation,
        to_entity_id=p.hypothesis_id,
        relation_type=p.relation_effect_if_observed[0].relation_type,
        attributes={
            "prediction_id": p.prediction_id,
            "outcome": p.expected_outcome,
            "outcome_space": p.outcome_space_ref,
        },
        supporting_attestation_ids=(f"att:{observation}",),
        condition_match_ref="cmt:toy",
        project_id=PROJECT,
        valid_from=T0,
        created_at=T0,
    )


# -- declarations ------------------------------------------------------------------------------


def test_one_outcome_cannot_be_the_signature_of_two_classes():
    first = FIBRE.declarations[0]
    clone = first.model_copy(update={"class_id": "other", "mechanism": "something else"})
    with pytest.raises(ValueError, match="discriminates neither"):
        DiagnosticDeclarationSet(
            set_id="fl", version="1", domain="fibre_link", declarations=(first, clone)
        )
    with pytest.raises(ValueError, match="both its signature and its refutation"):
        first.model_copy(update={"refutes_outcomes": ("DIRTY",)}).model_validate(
            {**first.model_dump(), "refutes_outcomes": ("DIRTY",)}
        )


def test_a_class_binds_by_exact_mechanism_and_agreeing_predictions_only():
    sig = prediction("a", "fl.endface", "DIRTY", RelationType.SUPPORTS)
    contra = prediction("a", "fl.endface", "CLEAN", RelationType.CONTRADICTS)
    exact = FIBRE.bound_class("connector end-face contamination", (sig, contra))
    assert exact is not None and exact.class_id == "contamination"
    # A paraphrase is unbound: it goes to a person, never to a guess.
    assert FIBRE.bound_class("dirty connector", (sig, contra)) is None
    # The class's name over predictions that contradict the declaration is not the class.
    backwards = prediction("a", "fl.endface", "CLEAN", RelationType.SUPPORTS)
    assert FIBRE.bound_class("connector end-face contamination", (backwards,)) is None
    affirms_refuter = prediction("a", "fl.endface", "CLEAN", RelationType.PREDICTS)
    assert FIBRE.bound_class("connector end-face contamination", (sig, affirms_refuter)) is None
    # A partial declaration is not the class: a copy stating only the signature could be
    # supported by the domain and never refuted by it, because nothing predicts the refutation.
    assert FIBRE.bound_class("connector end-face contamination", (sig,)) is None
    elsewhere = prediction("a", "fl.otdr_bend", "NO_STEP", RelationType.PREDICTS)
    assert FIBRE.bound_class("connector end-face contamination", (elsewhere,)) is None
    assert FIBRE.bound_class("connector end-face contamination", (sig, contra, elsewhere))


def test_the_sp_declaration_set_is_pinned_by_digest():
    """Editing a diagnostic link in place would silently change what re-derivation means."""
    from lab_brain.domains.silicon_photonics.product import diagnostic_declaration_set

    sp = diagnostic_declaration_set()
    assert sp.ref == "sp.rs_anomaly_mechanisms@1.0.0"
    assert sp.digest == (
        "sha256:e1d637af972bb9fc902772e926f3ed796ab5ad183b21edfe132fd993d24aa0e6"
    ), "a declaration changed without a catalog version bump"


# -- resolver ----------------------------------------------------------------------------------


class _Grants:
    def __init__(self, *grants: DiagnosticWarrantGrant) -> None:
        self._grants = grants

    def grants_for_relations(self, project_id: str, relation_ids: Any) -> tuple[Any, ...]:
        wanted = set(relation_ids)
        return tuple(g for g in self._grants if g.relation_id in wanted)

    def grant(self, project_id: str, grant_id: str) -> Any:
        return next((g for g in self._grants if g.grant_id == grant_id), None)


def _resolver(
    *certificates: HypothesisCertificate,
    grants: _Grants | None = None,
    attestations: Any = None,
    relations: Any = None,
) -> WarrantResolver:
    by_id = {c.hypothesis_id: c for c in certificates}
    return WarrantResolver(
        certificates=lambda _p, h: by_id.get(h),
        attestations=attestations or (lambda _p, _a: None),
        observations=lambda _p, _o: None,
        runs=lambda _r: None,
        grants=grants,
        relations=relations,
        declaration_sets=(FIBRE,),
        active=FIBRE.ref,
    )


def test_a_proxy_observable_earns_no_domain_warrant_in_another_domain():
    """The `epi:7b56877f` shape, in a fibre link: a contamination story bound to the bend trace."""
    sig = prediction("proxy", "fl.otdr_bend", "WAVELENGTH_DEPENDENT_STEP", RelationType.SUPPORTS)
    cert = certificate("proxy", "dust inside the adapter sleeve", (sig,))
    (record,) = _resolver(cert).resolve(PROJECT, "hyp:proxy", (observed(sig),)).records
    assert record.warrant is None and not record.refused


def test_authorship_never_decides_a_warrant():
    """Identical claims are warranted identically, whatever produced them."""
    sig = prediction("h", "fl.endface", "DIRTY", RelationType.SUPPORTS)
    contra = prediction("h", "fl.endface", "CLEAN", RelationType.CONTRADICTS)
    relation = observed(sig)
    catalog = certificate("h", "connector end-face contamination", (sig, contra))
    model = certificate(
        "h",
        "connector end-face contamination",
        (sig, contra),
        inference_provenance_id="inf:any-model",
    )
    a = _resolver(catalog).resolve(PROJECT, "hyp:h", (relation,)).records
    b = _resolver(model).resolve(PROJECT, "hyp:h", (relation,)).records
    assert a == b and a[0].warrant is WarrantBasis.DOMAIN
    assert a[0].warrant_ref == "dds:fl.loss_mechanisms@1.0.0#contamination"


@pytest.mark.parametrize("path", ["core/warrant.py", "core/models/warrant.py"])
def test_the_warrant_code_reads_no_authorship_field(path: str):
    tree = ast.parse((SRC / path).read_text(encoding="utf-8"))
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    forbidden = {"provider", "model_id", "model_version", "inference_provenance_id"}
    assert not (names & forbidden), f"{path} reads {sorted(names & forbidden)}"
    assert "authored_by_actor_id" not in names


def test_a_review_grant_warrants_one_relation_and_a_refusal_is_terminal():
    sig = prediction("n", "fl.otdr_bend", "WAVELENGTH_DEPENDENT_STEP", RelationType.SUPPORTS)
    cert = certificate("n", "fibre crushed under a cable tie", (sig,))
    relation = observed(sig)

    def grant(verdict: GrantVerdict) -> DiagnosticWarrantGrant:
        return DiagnosticWarrantGrant(
            grant_id="dwg:1",
            project_id=PROJECT,
            review_id="rvw:1",
            relation_id=relation.relation_id,
            relation_type=RelationType.SUPPORTS,
            hypothesis_id="hyp:n",
            prediction_id=sig.prediction_id,
            verdict=verdict,
            granted_by_actor_id="act:reviewer",
            granted_at=T0,
            rationale="a crush produces a bend-like, wavelength-dependent step",
        )

    (yes,) = (
        _resolver(cert, grants=_Grants(grant(GrantVerdict.WARRANTED)))
        .resolve(PROJECT, "hyp:n", (relation,))
        .records
    )
    assert (yes.warrant, yes.warrant_ref) == (WarrantBasis.REVIEW, "dwg:1")
    (no,) = (
        _resolver(cert, grants=_Grants(grant(GrantVerdict.NOT_WARRANTED)))
        .resolve(PROJECT, "hyp:n", (relation,))
        .records
    )
    assert no.warrant is None and no.refused


def test_a_recorded_warrant_that_does_not_recheck_is_refused():
    sig = prediction("p", "fl.otdr_bend", "WAVELENGTH_DEPENDENT_STEP", RelationType.SUPPORTS)
    cert = certificate("p", "dust inside the adapter sleeve", (sig,))
    relation = observed(sig)
    resolver = _resolver(cert)
    forged = RelationEvidence(
        relation_id=relation.relation_id,
        relation_type=RelationType.SUPPORTS,
        prediction_id=sig.prediction_id,
        warrant=WarrantBasis.DOMAIN,
        warrant_ref="dds:fl.loss_mechanisms@1.0.0#macrobend",
    )
    with pytest.raises(WarrantUnverified, match="does not declare"):
        resolver.verify(PROJECT, "hyp:p", forged, (relation,))
    review = forged.model_copy(update={"warrant": WarrantBasis.REVIEW, "warrant_ref": "dwg:none"})
    with pytest.raises(WarrantUnverified, match="not a WARRANTED grant"):
        resolver.verify(PROJECT, "hyp:p", review, (relation,))
    refusal = forged.model_copy(update={"warrant": None, "warrant_ref": None, "refused": True})
    with pytest.raises(WarrantUnverified, match="refusal nobody made"):
        resolver.verify(PROJECT, "hyp:p", refusal, (relation,))
    lent = RelationEvidence(
        relation_id=relation.relation_id,
        relation_type=RelationType.SUPPORTS,
        prediction_id=sig.prediction_id,
        authority_classes=("CALIBRATED",),
    )
    with pytest.raises(WarrantUnverified, match="states authority"):
        resolver.verify(PROJECT, "hyp:p", lent, (relation,))


def test_a_refuting_outcome_is_warranted_only_for_the_bound_class():
    contra = prediction("c", "fl.endface", "CLEAN", RelationType.CONTRADICTS)
    sig = prediction("c", "fl.endface", "DIRTY", RelationType.SUPPORTS)
    bound = certificate("c", "connector end-face contamination", (sig, contra))
    unbound = certificate("c", "contaminated splice", (sig, contra))
    assert domain_warrant(observed(contra), bound, FIBRE) is not None
    assert domain_warrant(observed(contra), unbound, FIBRE) is None


# -- policy ------------------------------------------------------------------------------------


def _promote(**overrides: Any) -> TransitionPolicy:
    fields: dict[str, Any] = {
        "policy_id": "pol:toy-promote",
        "version": "2.0.0",
        "from_state": BeliefState.ACTIVE,
        "candidate_to_state": BeliefState.SUPPORTED,
        "required_relation_types": (RelationType.SUPPORTS,),
        "min_independent_attestations": 1,
        "diagnostic_warrant_required": True,
    }
    fields.update(overrides)
    return TransitionPolicy(**fields)


class _Rank:
    """CALIBRATED > FIELD_NOTE; the rule asks for CALIBRATED."""

    policy_id = "auth:toy"
    policy_version = "1.0.0"

    def compare(self, candidate: str, required: str) -> Any:
        from lab_brain.core.models.enums import AuthorityComparison

        order = {"FIELD_NOTE": 0, "CALIBRATED": 1}
        if order[candidate] == order[required]:
            return AuthorityComparison.EQUIVALENT
        return (
            AuthorityComparison.STRONGER
            if order[candidate] > order[required]
            else AuthorityComparison.WEAKER
        )

    def meets(self, required: str, candidate: str) -> bool:
        return {"FIELD_NOTE": 0, "CALIBRATED": 1}[candidate] >= {"FIELD_NOTE": 0, "CALIBRATED": 1}[
            required
        ]


def _view(*records: RelationEvidence, classes: tuple[str, ...] = ()) -> HypothesisView:
    return HypothesisView(
        hypothesis_id="hyp:h",
        project_id=PROJECT,
        current_state=BeliefState.ACTIVE,
        admitted_authority_classes=classes,
        relation_evidence=records,
    )


def _record(
    relation: RelationJudgment,
    *,
    warranted: bool,
    authority: str = "CALIBRATED",
    line: str = "line:1",
    refused: bool = False,
) -> RelationEvidence:
    return RelationEvidence(
        relation_id=relation.relation_id,
        relation_type=relation.relation_type,
        prediction_id=str(relation.attributes["prediction_id"]),
        authority_classes=(authority,),
        evidence_line=line,
        warrant=WarrantBasis.DOMAIN if warranted else None,
        warrant_ref="dds:x@1#c" if warranted else None,
        refused=refused,
    )


SIG = prediction("h", "web.pool_wait", "SATURATED_WAITING", RelationType.SUPPORTS)
REL = observed(SIG)


def _evaluate(policy: TransitionPolicy, view: HypothesisView, *relations: RelationJudgment) -> Any:
    return policy.evaluate(
        view,
        relations or (REL,),
        cast(Any, _Rank()),
        (),
        IndependenceSummary(independent_count=5),
        policy.candidate_to_state,
    )


def test_an_ungated_policy_decides_exactly_as_before():
    """Version 1.0.0 semantics: the author's SUPPORTS counts. Stored decisions must re-derive."""
    decision = _evaluate(_promote(diagnostic_warrant_required=False), _view())
    assert decision.outcome is TransitionOutcome.ALLOW


def test_an_unwarranted_support_asks_a_person_and_never_promotes():
    decision = _evaluate(_promote(), _view(_record(REL, warranted=False)))
    assert decision.outcome is TransitionOutcome.NEED_HUMAN_REVIEW
    assert decision.reason_code is TransitionReason.DIAGNOSTIC_WARRANT_MISSING
    assert decision.review_item_spec is not None
    assert decision.review_item_spec.subject_type == "DIAGNOSTIC_WARRANT"


def test_a_warranted_support_promotes_and_counts_its_lines():
    decision = _evaluate(_promote(), _view(_record(REL, warranted=True)))
    assert decision.outcome is TransitionOutcome.ALLOW
    assert decision.independent_attestation_count == 1


def test_a_refused_warrant_is_an_answer_not_a_new_question():
    decision = _evaluate(_promote(), _view(_record(REL, warranted=False, refused=True)))
    assert decision.outcome is TransitionOutcome.NEED_MORE_EVIDENCE
    assert decision.reason_code is TransitionReason.DIAGNOSTIC_WARRANT_REFUSED


def test_nobody_is_asked_a_question_whose_answer_cannot_matter():
    """An unwarranted relation that would fail on authority anyway is answered as that failure."""
    policy = _promote(required_authority_rule="CALIBRATED")
    decision = _evaluate(policy, _view(_record(REL, warranted=False, authority="FIELD_NOTE")))
    assert decision.outcome is TransitionOutcome.DENY
    assert decision.reason_code is TransitionReason.AUTHORITY_INSUFFICIENT


def test_a_warranted_relation_cannot_borrow_authority_from_an_unwarranted_one():
    """The flat view says CALIBRATED is present; it belongs to the unwarranted proxy."""
    strong = observed(SIG, observation="obs:proxy", relation_id="rel:proxy")
    policy = _promote(required_authority_rule="CALIBRATED")
    view = _view(
        _record(REL, warranted=True, authority="FIELD_NOTE"),
        _record(strong, warranted=False, authority="CALIBRATED", line="line:2"),
        classes=("CALIBRATED", "FIELD_NOTE"),
    )
    decision = _evaluate(policy, view, REL, strong)
    assert decision.outcome is not TransitionOutcome.ALLOW
    # Warranting the strong relation WOULD decide it, so a person is asked about that one.
    assert decision.reason_code is TransitionReason.DIAGNOSTIC_WARRANT_MISSING


def test_replicates_of_one_computation_are_one_line():
    again = observed(SIG, observation="obs:2", relation_id="rel:again")
    policy = _promote(min_independent_attestations=2)
    same_line = _view(_record(REL, warranted=True), _record(again, warranted=True))
    decision = _evaluate(policy, same_line, REL, again)
    assert decision.outcome is TransitionOutcome.NEED_MORE_EVIDENCE
    assert decision.reason_code is TransitionReason.INSUFFICIENT_INDEPENDENT_ATTESTATIONS
    two_lines = _view(_record(REL, warranted=True), _record(again, warranted=True, line="line:2"))
    assert _evaluate(policy, two_lines, REL, again).outcome is TransitionOutcome.ALLOW


def test_a_record_cannot_lend_its_warrant_to_a_relation_it_does_not_describe():
    other = _record(REL, warranted=True).model_copy(update={"prediction_id": "prd:someone-else"})
    decision = _evaluate(_promote(), _view(other))
    assert decision.outcome is not TransitionOutcome.ALLOW


def test_refutation_is_gated_the_same_way():
    contra = prediction("h", "web.pool_wait", "IDLE_CAPACITY", RelationType.CONTRADICTS)
    relation = observed(contra)
    reject = _promote(
        policy_id="pol:toy-reject",
        candidate_to_state=BeliefState.CONTRADICTED,
        required_relation_types=(RelationType.CONTRADICTS,),
    )
    unwarranted = _evaluate(reject, _view(_record(relation, warranted=False)), relation)
    assert unwarranted.reason_code is TransitionReason.DIAGNOSTIC_WARRANT_MISSING
    warranted = _evaluate(reject, _view(_record(relation, warranted=True)), relation)
    assert warranted.outcome is TransitionOutcome.ALLOW


# -- snapshot compatibility ------------------------------------------------------------------


def test_an_empty_relation_evidence_leaves_every_stored_hash_as_it_was():
    snapshot = DecisionInputSnapshot(
        hypothesis=_view(),
        admitted_relations=(REL,),
        independence_summary=IndependenceSummary(independent_count=1),
        candidate_to_state=BeliefState.SUPPORTED,
    )
    assert "relation_evidence" not in snapshot.canonical_bytes_text()
    # Defaulted fields that historical snapshots DID serialise are kept.
    assert '"stakes"' in snapshot.canonical_bytes_text()
    with_record = snapshot.model_copy(update={"hypothesis": _view(_record(REL, warranted=True))})
    assert "relation_evidence" in with_record.canonical_bytes_text()
    assert with_record.input_hash() != snapshot.input_hash()


# -- the confirmation rule ----------------------------------------------------------------------


class _World:
    """Just enough of the loop's dependencies for `VerificationLoop.standing`."""

    def __init__(
        self,
        states: dict[str, BeliefState],
        relations: dict[str, tuple[Any, ...]],
        records: dict[str, tuple[RelationEvidence, ...]],
        outstanding: frozenset[str] = frozenset(),
    ):
        self.states, self.relations, self.records, self.pending = (
            states,
            relations,
            records,
            outstanding,
        )

    def project(self, *, project_id: str, hypothesis_id: str, projected_at: Any = None) -> Any:
        return type("P", (), {"current_state": self.states[hypothesis_id]})()

    def hypothesis_view(self, *, hypothesis_id: str, **_: Any) -> HypothesisView:
        return HypothesisView(
            hypothesis_id=hypothesis_id,
            project_id=PROJECT,
            current_state=self.states[hypothesis_id],
            relation_evidence=self.records.get(hypothesis_id, ()),
        )

    def admitted_for_subject(self, project_id: str, subject_id: str) -> tuple[Any, ...]:
        return self.relations.get(subject_id, ())

    def enqueue_warrant_review(self, **fields: Any) -> str:
        self.asked = (*getattr(self, "asked", ()), fields["relation_id"])
        return f"rvw:{fields['relation_id']}"

    def outstanding_relations(self, project_id: str, relation_ids: Any) -> frozenset[str]:
        return frozenset(r for r in relation_ids if r in self.pending)


def _standing(
    world: _World,
    certificates: tuple[HypothesisCertificate, ...] | None = None,
    declarations: DiagnosticDeclarationSet | None = None,
    outcomes: tuple[tuple[str, Link], ...] | None = None,
) -> Any:
    deps = LoopDependencies(
        **{
            name: cast(Any, None)
            for name in LoopDependencies.__dataclass_fields__
            if name
            not in {
                "belief",
                "evidence",
                "warrant_reviews",
                "now",
                "declarations",
                "episode_outcomes",
            }
        },
        belief=cast(Any, world),
        evidence=cast(Any, world),
        warrant_reviews=world,
        now=lambda: T0,
        declarations=declarations,
        episode_outcomes=None if outcomes is None else (lambda _p, _e: outcomes),
    )
    certificates = certificates or tuple(
        certificate(h.split(":", 1)[1], h, ()) for h in sorted(world.states)
    )
    request = LoopRequest(
        **{
            name: cast(Any, None)
            for name in LoopRequest.__dataclass_fields__
            if name not in {"project_id", "certificates", "hypothesis_set", "max_steps"}
        },
        project_id=PROJECT,
        certificates=certificates,
        hypothesis_set=HypothesisSet(
            set_id="hst:toy",
            project_id=PROJECT,
            episode_id="epi:toy",
            question="why do requests time out?",
            research_intent="DIAGNOSIS",
            stakes="HIGH",
            source_policy_id="srcpol:toy",
            source_policy_version="1.0.0",
            inverted_retrieval_required=False,
        ),
    )
    return VerificationLoop(deps).standing(request)


POOL = prediction("pool", "web.pool_wait", "SATURATED_WAITING", RelationType.SUPPORTS)
POOL_REL = observed(POOL, observation="obs:pool-check")
POOL_WARRANTED = _record(POOL_REL, warranted=True)


def _rival_affirming(effect: RelationType) -> RelationJudgment:
    """The slow-query rival says a saturated pool is what IT would produce too."""
    p = prediction("query", "web.pool_wait", "SATURATED_WAITING", effect)
    return observed(p, observation="obs:pool-check", relation_id="rel:query-on-pool")


def test_a_rival_that_predicts_the_same_observation_blocks_confirmation():
    """Downstream saturation from a slow query looks exactly like exhaustion on the pool check."""
    world = _World(
        states={"hyp:pool": BeliefState.SUPPORTED, "hyp:query": BeliefState.ACTIVE},
        relations={
            "hyp:pool": (POOL_REL,),
            "hyp:query": (_rival_affirming(RelationType.PREDICTS),),
        },
        records={"hyp:pool": (POOL_WARRANTED,)},
    )
    standing = _standing(world)
    assert standing.confirmable is None
    assert standing.undischarged == ("hyp:query",)


def test_only_a_warranted_refutation_excludes_the_rival():
    contra = prediction("query", "web.query_latency", "BASELINE", RelationType.CONTRADICTS)
    refutation = observed(contra, observation="obs:latency-check", relation_id="rel:query-baseline")
    affirming = _rival_affirming(RelationType.SUPPORTS)

    def world(warranted: bool) -> _World:
        return _World(
            states={"hyp:pool": BeliefState.SUPPORTED, "hyp:query": BeliefState.CONTRADICTED},
            relations={"hyp:pool": (POOL_REL,), "hyp:query": (affirming, refutation)},
            records={
                "hyp:pool": (POOL_WARRANTED,),
                "hyp:query": (
                    _record(affirming, warranted=False),
                    _record(refutation, warranted=warranted, line="line:latency"),
                ),
            },
        )

    # An unwarranted refutation (the recorded `epi:6174b0fe` shape) leaves the rival standing.
    assert _standing(world(False)).confirmable is None
    assert _standing(world(True)).confirmable == "hyp:pool"


def test_two_classes_supported_is_competition_not_a_choice():
    query = prediction("query", "web.query_latency", "REGRESSED", RelationType.SUPPORTS)
    query_rel = observed(query, observation="obs:latency-check")
    query_record = _record(query_rel, warranted=True).model_copy(
        update={"warrant_ref": "dds:web.timeout_causes@1.0.0#slow_query"}
    )
    pool_record = POOL_WARRANTED.model_copy(
        update={"warrant_ref": "dds:web.timeout_causes@1.0.0#pool_exhaustion"}
    )
    world = _World(
        states={"hyp:pool": BeliefState.SUPPORTED, "hyp:query": BeliefState.SUPPORTED},
        relations={"hyp:pool": (POOL_REL,), "hyp:query": (query_rel,)},
        records={"hyp:pool": (pool_record,), "hyp:query": (query_record,)},
    )
    standing = _standing(world)
    assert standing.confirmable is None
    assert standing.competing == ("hyp:pool", "hyp:query")


def test_an_unsettled_answer_that_could_overturn_the_conclusion_holds_it_queued_or_not():
    """Read off the records: a project with no review queue does not make the threat vanish."""
    rival_support = _rival_affirming(RelationType.SUPPORTS).model_copy(
        update={"from_entity_id": "obs:elsewhere", "relation_id": "rel:query-elsewhere"}
    )

    def world(refused: bool) -> _World:
        return _World(
            states={"hyp:pool": BeliefState.SUPPORTED, "hyp:query": BeliefState.ACTIVE},
            relations={"hyp:pool": (POOL_REL,), "hyp:query": (rival_support,)},
            records={
                "hyp:pool": (POOL_WARRANTED,),
                "hyp:query": (_record(rival_support, warranted=False, refused=refused),),
            },
        )

    held = _standing(world(refused=False))
    assert held.confirmable is None and held.awaiting == ("rel:query-elsewhere",)
    assert _standing(world(refused=True)).confirmable == "hyp:pool"


def test_a_refutation_arriving_after_the_promotion_still_holds_the_conclusion():
    """No policy starts from SUPPORTED, so only the confirmation rule can notice it."""
    late = prediction("pool", "web.pool_wait", "IDLE_CAPACITY", RelationType.CONTRADICTS)
    late_rel = observed(late, observation="obs:second-pool-check")
    world = _World(
        states={"hyp:pool": BeliefState.SUPPORTED, "hyp:query": BeliefState.ACTIVE},
        relations={"hyp:pool": (POOL_REL, late_rel)},
        records={"hyp:pool": (POOL_WARRANTED, _record(late_rel, warranted=False, line="l2"))},
    )
    standing = _standing(world)
    assert standing.confirmable is None
    assert standing.awaiting == (late_rel.relation_id,)


def test_an_excluded_rivals_unanswered_support_is_not_a_threat():
    """Once a warranted refutation excludes a rival, its pending support question cannot matter."""
    affirming = _rival_affirming(RelationType.SUPPORTS)
    contra = prediction("query", "web.query_latency", "BASELINE", RelationType.CONTRADICTS)
    refutation = observed(contra, observation="obs:latency", relation_id="rel:query-baseline")
    world = _World(
        states={"hyp:pool": BeliefState.SUPPORTED, "hyp:query": BeliefState.CONTRADICTED},
        relations={"hyp:pool": (POOL_REL,), "hyp:query": (affirming, refutation)},
        records={
            "hyp:pool": (POOL_WARRANTED,),
            "hyp:query": (
                _record(affirming, warranted=False),
                _record(refutation, warranted=True, line="line:latency"),
            ),
        },
    )
    assert _standing(world).confirmable == "hyp:pool"


def test_a_refuted_copy_of_the_candidates_own_class_blocks_it():
    """Two members of one declared class are one candidate: a refutation of either refutes it.

    Serial readings disagree -- saturated, then idle. The copy that holds both is not a rival the
    refutation could "exclude"; it is the same class, refuted.
    """
    pair = {
        h: (
            prediction(h, "web.pool_wait", "SATURATED_WAITING", RelationType.SUPPORTS),
            prediction(h, "web.pool_wait", "IDLE_CAPACITY", RelationType.CONTRADICTS),
        )
        for h in ("pool", "twin")
    }
    mechanism = "database connection pool exhaustion"
    certificates = (
        certificate("pool", mechanism, pair["pool"]),
        certificate("twin", mechanism, pair["twin"]),
    )
    supported = observed(pair["pool"][0], observation="obs:first-reading")
    twin_refuted = observed(pair["twin"][1], observation="obs:second-reading")
    world = _World(
        states={"hyp:pool": BeliefState.SUPPORTED, "hyp:twin": BeliefState.ACTIVE},
        relations={"hyp:pool": (supported,), "hyp:twin": (twin_refuted,)},
        records={
            "hyp:pool": (_record(supported, warranted=True),),
            "hyp:twin": (_record(twin_refuted, warranted=True, line="line:2"),),
        },
    )
    standing = _standing(world, certificates=certificates, declarations=INCIDENT)
    assert standing.confirmable is None
    assert any("own class" in note for note in standing.notes)
    # Without the twin's refutation the class stands, and the twin is not a rival to discharge.
    clean = _World(
        states=world.states,
        relations={"hyp:pool": (supported,)},
        records={"hyp:pool": (_record(supported, warranted=True),)},
    )
    assert _standing(clean, certificates=certificates, declarations=INCIDENT).confirmable == (
        "hyp:pool"
    )


def test_support_nobody_warranted_never_confirms():
    """A belief moved by an ungated policy is SUPPORTED, not a confirmed cause."""
    world = _World(
        states={"hyp:pool": BeliefState.SUPPORTED, "hyp:query": BeliefState.ACTIVE},
        relations={"hyp:pool": (POOL_REL,)},
        records={"hyp:pool": (_record(POOL_REL, warranted=False),)},
    )
    assert _standing(world).confirmable is None


def test_a_novel_mechanism_is_neither_rejected_nor_confirmed_without_a_person():
    """An uncatalogued mechanism's support asks; it does not refuse and does not decide."""
    novel = prediction("novel", "web.pool_wait", "SATURATED_WAITING", RelationType.SUPPORTS)
    relation = observed(novel)
    decision = _evaluate(_promote(), _view(_record(relation, warranted=False)), relation)
    assert decision.outcome is TransitionOutcome.NEED_HUMAN_REVIEW
    assert decision.outcome is not TransitionOutcome.DENY


# -- the read path, the product targets, the event --------------------------------------------


def _stored_allow(record: RelationEvidence) -> tuple[Any, Any, Any]:
    from lab_brain.core.belief import authorize_transition
    from lab_brain.core.models.belief_event import BeliefRevisionEvent, BeliefTargetType

    policy = _promote()
    view = _view(record)
    authorization = authorize_transition(
        decision_id="dec:toy",
        policy=policy,
        hypothesis=view,
        admitted_relations=(REL,),
        authority_policy=None,
        independence_summary=IndependenceSummary(independent_count=1),
        candidate_to_state=BeliefState.SUPPORTED,
        created_at=T0,
    )
    assert authorization.evaluated.outcome is TransitionOutcome.ALLOW
    event = BeliefRevisionEvent(
        event_id="bre:toy",
        project_id=PROJECT,
        target_type=BeliefTargetType.HYPOTHESIS,
        target_id="hyp:h",
        from_state=BeliefState.ACTIVE,
        to_state=BeliefState.SUPPORTED,
        triggering_relation_ids=(REL.relation_id,),
        policy_id=policy.policy_id,
        policy_version=policy.version,
        authorization_decision_id="dec:toy",
        occurred_at=T0,
        trace_id="trc:toy",
    )
    decisions = type("D", (), {"get": staticmethod(lambda _id: authorization)})()
    policies = type("P", (), {"get": staticmethod(lambda _i, _v: policy)})()
    return event, decisions, policies


def test_a_stored_allow_whose_warrant_does_not_recheck_moves_no_belief():
    from lab_brain.core.belief import (
        UnverifiedBeliefRevision,
        VerificationFailure,
        verify_stored_revision,
    )

    event, decisions, policies = _stored_allow(_record(REL, warranted=True))
    with pytest.raises(UnverifiedBeliefRevision) as unchecked:
        verify_stored_revision(event=event, decisions=decisions, policies=policies)
    assert unchecked.value.reason is VerificationFailure.WARRANT_UNVERIFIED

    def forged(*_: Any) -> None:
        raise WarrantUnverified("no such declaration")

    with pytest.raises(UnverifiedBeliefRevision) as refused:
        verify_stored_revision(
            event=event, decisions=decisions, policies=policies, warrant_verifier=forged
        )
    assert refused.value.reason is VerificationFailure.WARRANT_UNVERIFIED
    verified = verify_stored_revision(
        event=event, decisions=decisions, policies=policies, warrant_verifier=lambda *_: None
    )
    assert verified.event is event


def test_every_product_diagnosis_target_that_moves_a_belief_is_warrant_gated():
    """A new target, or an old version slipped back in, would let a declared effect decide."""
    from lab_brain.domains.silicon_photonics import vertical as sp

    targets = sp.diagnosis_targets()
    assert targets
    for policy, _ in targets:
        assert set(policy.required_relation_types) & {
            RelationType.SUPPORTS,
            RelationType.CONTRADICTS,
        }
        assert policy.diagnostic_warrant_required, f"{policy.policy_id}@{policy.version}"
    offered = {(p.policy_id, p.version) for p in sp.vertical_transition_policies()}
    assert ("policy:sp-vs001-promote", "1.0.0") in offered, "1.0.0 must stay re-derivable"


def test_an_allowed_event_cites_only_the_warranted_relations():
    """What the trace and the miner read as a cause's evidence is what was counted."""
    from lab_brain.core.episode import counted_triggers
    from lab_brain.core.models.attestation import Attestation

    proxy = observed(SIG, observation="obs:proxy", relation_id="rel:proxy")
    view = _view(_record(REL, warranted=True), _record(proxy, warranted=False, line="line:2"))
    attestations = tuple(
        cast(Attestation, type("A", (), {"attestation_id": f"att:{o}"})())
        for o in ("obs:1", "obs:proxy")
    )
    relations, cited = counted_triggers(_promote(), view, (REL, proxy), attestations)
    assert [r.relation_id for r in relations] == [REL.relation_id]
    assert [a.attestation_id for a in cited] == ["att:obs:1"]
    ungated, _ = counted_triggers(
        _promote(diagnostic_warrant_required=False), view, (REL, proxy), attestations
    )
    assert len(ungated) == 2


def test_a_superseded_policy_version_is_re_derivable_but_never_attempted():
    from lab_brain.core.episode import BeliefEpisode, EpisodeRefused, superseded_versions
    from lab_brain.domains.silicon_photonics import vertical as sp

    offered = sp.vertical_transition_policies()
    superseded = superseded_versions(offered)
    assert (sp.PROMOTE_POLICY_ID, sp.VERTICAL_POLICY_VERSION) in superseded
    first = next(p for p in offered if p.version == sp.VERTICAL_POLICY_VERSION)
    episode = BeliefEpisode(
        **{
            name: cast(Any, None)
            for name in (
                "decisions",
                "events",
                "relations",
                "authority_classes",
                "conflicts",
                "reviews",
                "ids",
            )
        },
        policies=cast(Any, type("P", (), {"get": staticmethod(lambda _i, _v: first)})()),
        superseded=superseded,
    )
    with pytest.raises(EpisodeRefused, match="superseded"):
        episode.attempt_transition(
            project_id=PROJECT,
            hypothesis_id="hyp:h",
            policy_id=first.policy_id,
            policy_version=first.version,
            candidate_to_state=BeliefState.SUPPORTED,
            stakes="HIGH",
            occurred_at=T0,
            trace_id="trc:toy",
        )


def test_a_persons_refusal_outranks_a_domain_declaration():
    """A refusal is about this observation; a declaration is about the class in general."""
    sig = prediction("h", "fl.endface", "DIRTY", RelationType.SUPPORTS)
    contra = prediction("h", "fl.endface", "CLEAN", RelationType.CONTRADICTS)
    cert = certificate("h", "connector end-face contamination", (sig, contra))
    relation = observed(sig)
    refusal = DiagnosticWarrantGrant(
        grant_id="dwg:no",
        project_id=PROJECT,
        review_id="rvw:no",
        relation_id=relation.relation_id,
        relation_type=RelationType.SUPPORTS,
        hypothesis_id="hyp:h",
        prediction_id=sig.prediction_id,
        verdict=GrantVerdict.NOT_WARRANTED,
        granted_by_actor_id="act:reviewer",
        granted_at=T0,
        rationale="the end-face image was of the wrong connector",
    )
    (record,) = (
        _resolver(cert, grants=_Grants(refusal)).resolve(PROJECT, "hyp:h", (relation,)).records
    )
    assert record.refused and record.warrant is None


def test_a_declaration_edited_in_place_stops_the_pack_loading(monkeypatch: pytest.MonkeyPatch):
    from lab_brain.domains.silicon_photonics import product

    original = product.mechanism_catalog()
    edited = original.__class__(
        catalog_id=original.catalog_id,
        version=original.version,
        primary_terms=original.primary_terms,
        mechanisms=tuple(
            m.__class__(**{**m.__dict__, "statement": m.statement + " (edited)"})
            for m in original.mechanisms
        ),
    )
    monkeypatch.setattr(product, "mechanism_catalog", lambda: edited)
    with pytest.raises(RuntimeError, match="without a catalog version bump"):
        product.diagnostic_declaration_set()


# -- the attacker's findings, held -------------------------------------------------------------


def test_a_coarse_challenge_does_not_exclude_a_rival_that_shares_the_observation():
    """SIM-002: a coarse refutation challenges; it does not reject, so it discharges nothing."""
    affirming = _rival_affirming(RelationType.PREDICTS)
    contra = prediction("query", "web.query_latency", "BASELINE", RelationType.CONTRADICTS)
    coarse = observed(contra, observation="obs:coarse", relation_id="rel:query-coarse")
    world = _World(
        states={"hyp:pool": BeliefState.SUPPORTED, "hyp:query": BeliefState.CHALLENGED},
        relations={"hyp:pool": (POOL_REL,), "hyp:query": (affirming, coarse)},
        records={
            "hyp:pool": (POOL_WARRANTED,),
            "hyp:query": (_record(coarse, warranted=True, line="line:coarse"),),
        },
    )
    standing = _standing(world)
    assert standing.confirmable is None and standing.undischarged == ("hyp:query",)


def test_another_classes_observed_signature_blocks_a_unique_confirmation():
    """The slow-query signature was observed, claimed by a hypothesis nobody believes. It is
    still the domain's evidence of a second mechanism -- or of the right one."""
    pool_pair = (
        prediction("pool", "web.pool_wait", "SATURATED_WAITING", RelationType.SUPPORTS),
        prediction("pool", "web.pool_wait", "IDLE_CAPACITY", RelationType.CONTRADICTS),
    )
    claim = prediction("noise", "web.query_latency", "REGRESSED", RelationType.SUPPORTS)
    certificates = (
        certificate("pool", "database connection pool exhaustion", pool_pair),
        certificate("noise", "a noisy neighbour on the host", (claim,)),
    )
    supported = observed(pool_pair[0], observation="obs:pool-check")
    signature = observed(claim, observation="obs:latency-check")
    world = _World(
        states={"hyp:pool": BeliefState.SUPPORTED, "hyp:noise": BeliefState.ACTIVE},
        relations={"hyp:pool": (supported,), "hyp:noise": (signature,)},
        records={
            "hyp:pool": (_record(supported, warranted=True),),
            "hyp:noise": (_record(signature, warranted=False, refused=True, line="l2"),),
        },
    )
    standing = _standing(world, certificates=certificates, declarations=INCIDENT)
    assert standing.confirmable is None
    assert any("declared signature of 'slow query regression'" in n for n in standing.notes)


def test_each_gated_type_a_policy_requires_needs_its_own_warrant():
    contra = prediction("h", "web.pool_wait", "IDLE_CAPACITY", RelationType.CONTRADICTS)
    contra_rel = observed(contra, observation="obs:2")
    both = _promote(
        required_relation_types=(RelationType.SUPPORTS, RelationType.CONTRADICTS),
    )
    view = _view(_record(REL, warranted=True), _record(contra_rel, warranted=False, line="l2"))
    decision = _evaluate(both, view, REL, contra_rel)
    assert decision.outcome is not TransitionOutcome.ALLOW


def test_a_warrant_is_rechecked_against_the_stored_relation_not_the_snapshots_copy():
    sig = prediction("h", "fl.endface", "DIRTY", RelationType.SUPPORTS)
    contra = prediction("h", "fl.endface", "CLEAN", RelationType.CONTRADICTS)
    cert = certificate("h", "connector end-face contamination", (sig, contra))
    stored = observed(contra)
    forged = stored.model_copy(
        update={
            "relation_type": RelationType.SUPPORTS,
            "attributes": {
                "prediction_id": sig.prediction_id,
                "outcome": "DIRTY",
                "outcome_space": sig.outcome_space_ref,
            },
        }
    )
    resolver = _resolver(cert, relations=lambda _p, _r: stored)
    record = RelationEvidence(
        relation_id=forged.relation_id,
        relation_type=RelationType.SUPPORTS,
        prediction_id=sig.prediction_id,
        warrant=WarrantBasis.DOMAIN,
        warrant_ref="dds:fl.loss_mechanisms@1.0.0#contamination",
    )
    with pytest.raises(WarrantUnverified, match="not the relation stored"):
        resolver.verify(PROJECT, "hyp:h", record, (forged,))


def test_a_grant_for_another_prediction_and_an_unrecorded_outcome_warrant_nothing():
    sig = prediction("n", "fl.otdr_bend", "WAVELENGTH_DEPENDENT_STEP", RelationType.SUPPORTS)
    cert = certificate("n", "fibre crushed under a cable tie", (sig,))
    relation = observed(sig)
    elsewhere = DiagnosticWarrantGrant(
        grant_id="dwg:x",
        project_id=PROJECT,
        review_id="rvw:x",
        relation_id=relation.relation_id,
        relation_type=RelationType.SUPPORTS,
        hypothesis_id="hyp:n",
        prediction_id="prd:someone-else",
        verdict=GrantVerdict.WARRANTED,
        granted_by_actor_id="act:reviewer",
        granted_at=T0,
        rationale="r",
    )
    (record,) = (
        _resolver(cert, grants=_Grants(elsewhere)).resolve(PROJECT, "hyp:n", (relation,)).records
    )
    assert record.warrant is None

    # The relation says the step was observed; its own attestation recorded NO_STEP.
    from lab_brain.core.models.attestation import Attestation

    def attestation(_p: str, _a: str) -> Any:
        return cast(
            Attestation,
            type(
                "A",
                (),
                {
                    "method": {"outcome": "NO_STEP"},
                    "authority_class": None,
                    "run_id": None,
                    "observation_id": None,
                },
            )(),
        )

    bound = certificate(
        "b",
        "macrobend in the patch run",
        (
            prediction("b", "fl.otdr_bend", "WAVELENGTH_DEPENDENT_STEP", RelationType.SUPPORTS),
            prediction("b", "fl.otdr_bend", "NO_STEP", RelationType.CONTRADICTS, key="ns"),
            prediction("b", "fl.otdr_bend", "FLAT_STEP", RelationType.CONTRADICTS, key="fs"),
        ),
    )
    claimed = observed(bound.predictions[0])
    (unrecorded,) = (
        _resolver(bound, attestations=attestation).resolve(PROJECT, "hyp:b", (claimed,)).records
    )
    assert unrecorded.warrant is None


def test_a_persons_identity_statement_counts_only_where_the_domain_supports_it():
    """'This hypothesis IS class C' is honoured when the warranted outcome is C's signature."""
    sig = prediction("p", "fl.endface", "DIRTY", RelationType.SUPPORTS)
    cert = certificate("p", "grime on the ferrule", (sig,))
    relation = observed(sig)

    def grant(identifies: str) -> DiagnosticWarrantGrant:
        return DiagnosticWarrantGrant(
            grant_id="dwg:id",
            project_id=PROJECT,
            review_id="rvw:id",
            relation_id=relation.relation_id,
            relation_type=RelationType.SUPPORTS,
            hypothesis_id="hyp:p",
            prediction_id=sig.prediction_id,
            verdict=GrantVerdict.WARRANTED,
            granted_by_actor_id="act:reviewer",
            granted_at=T0,
            rationale="grime on the ferrule is end-face contamination",
            identifies_class_ref=identifies,
        )

    right = "dds:fl.loss_mechanisms@1.0.0#contamination"
    (record,) = (
        _resolver(cert, grants=_Grants(grant(right))).resolve(PROJECT, "hyp:p", (relation,)).records
    )
    assert record.warrant is WarrantBasis.REVIEW and record.identifies == right
    # The macrobend class's signature is a wavelength-dependent step, not a dirty end-face.
    wrong = "dds:fl.loss_mechanisms@1.0.0#macrobend"
    (record,) = (
        _resolver(cert, grants=_Grants(grant(wrong))).resolve(PROJECT, "hyp:p", (relation,)).records
    )
    assert record.warrant is WarrantBasis.REVIEW and record.identifies is None


def test_an_identified_paraphrase_joins_its_class_and_an_unidentified_one_does_not():
    pool_pair = (
        prediction("pool", "web.pool_wait", "SATURATED_WAITING", RelationType.SUPPORTS),
        prediction("pool", "web.pool_wait", "IDLE_CAPACITY", RelationType.CONTRADICTS),
    )
    para = prediction("para", "web.pool_wait", "SATURATED_WAITING", RelationType.SUPPORTS)
    certificates = (
        certificate("pool", "database connection pool exhaustion", pool_pair),
        certificate("para", "connections run out under load", (para,)),
    )
    pool_rel = observed(pool_pair[0], observation="obs:pool-check")
    para_rel = observed(para, observation="obs:pool-check")
    ref = "dds:web.timeout_causes@1.0.0#pool_exhaustion"

    def world(identified: bool) -> _World:
        para_record = _record(para_rel, warranted=True, line="line:1").model_copy(
            update={"warrant": WarrantBasis.REVIEW, "warrant_ref": "dwg:para"}
        )
        if identified:
            para_record = para_record.model_copy(update={"identifies": ref})
        return _World(
            states={"hyp:pool": BeliefState.SUPPORTED, "hyp:para": BeliefState.SUPPORTED},
            relations={"hyp:pool": (pool_rel,), "hyp:para": (para_rel,)},
            records={
                "hyp:pool": (_record(pool_rel, warranted=True),),
                "hyp:para": (para_record,),
            },
        )

    joined = _standing(world(True), certificates=certificates, declarations=INCIDENT)
    assert joined.confirmable is not None and not joined.competing
    apart = _standing(world(False), certificates=certificates, declarations=INCIDENT)
    assert apart.confirmable is None and apart.competing == ("hyp:para", "hyp:pool")


def test_the_policy_store_says_what_is_superseded_even_where_nobody_wired_it():
    from lab_brain.core.episode import BeliefEpisode, EpisodeRefused

    first = _promote(version="1.0.0", diagnostic_warrant_required=False)
    store = type(
        "Store",
        (),
        {
            "get": staticmethod(lambda _i, _v: first),
            "superseded_by": staticmethod(lambda _i, _v: "pol:toy-promote@2.0.0"),
        },
    )()
    episode = BeliefEpisode(
        **{
            name: cast(Any, None)
            for name in (
                "decisions",
                "events",
                "relations",
                "authority_classes",
                "conflicts",
                "reviews",
                "ids",
            )
        },
        policies=cast(Any, store),
    )
    with pytest.raises(EpisodeRefused, match="superseded"):
        episode.attempt_transition(
            project_id=PROJECT,
            hypothesis_id="hyp:h",
            policy_id=first.policy_id,
            policy_version=first.version,
            candidate_to_state=BeliefState.SUPPORTED,
            stakes="HIGH",
            occurred_at=T0,
            trace_id="trc:toy",
        )


def test_an_attestation_of_another_observation_lends_nothing():
    sig = prediction("h", "fl.endface", "DIRTY", RelationType.SUPPORTS)
    contra = prediction("h", "fl.endface", "CLEAN", RelationType.CONTRADICTS)
    cert = certificate("h", "connector end-face contamination", (sig, contra))
    relation = observed(sig, observation="obs:this")
    from lab_brain.core.models.attestation import Attestation

    def borrowed(_p: str, _a: str) -> Any:
        return cast(
            Attestation,
            type(
                "A",
                (),
                {
                    "method": {"outcome": "DIRTY", "outcome_space": sig.outcome_space_ref},
                    "authority_class": None,
                    "run_id": None,
                    "observation_id": "obs:another",
                },
            )(),
        )

    (record,) = (
        _resolver(cert, attestations=borrowed).resolve(PROJECT, "hyp:h", (relation,)).records
    )
    assert record.warrant is None


def test_a_relation_with_no_attestation_warrants_nothing():
    """A claim about an observation with no record of that observation agrees with nothing."""
    sig = prediction("h", "fl.endface", "DIRTY", RelationType.SUPPORTS)
    contra = prediction("h", "fl.endface", "CLEAN", RelationType.CONTRADICTS)
    cert = certificate("h", "connector end-face contamination", (sig, contra))
    bare = observed(sig).model_copy(
        update={"supporting_attestation_ids": (), "actor_id": "act:runner"}
    )
    (record,) = _resolver(cert).resolve(PROJECT, "hyp:h", (bare,)).records
    assert record.warrant is None
    (control,) = _resolver(cert).resolve(PROJECT, "hyp:h", (observed(sig),)).records
    assert control.warrant is WarrantBasis.DOMAIN


def test_an_identified_member_is_refuted_by_its_class_outcome_nobody_predicted():
    """A paraphrase joined the pool-exhaustion class by a person's statement, so it never had to
    predict that class's refuting outcome. A second check observed IDLE_CAPACITY anyway: the
    domain says the class cannot produce it, so the identified member is not confirmed."""
    para = prediction("para", "web.pool_wait", "SATURATED_WAITING", RelationType.SUPPORTS)
    certificates = (certificate("para", "connections run out under load", (para,)),)
    para_rel = observed(para, observation="obs:pool-check")
    ref = "dds:web.timeout_causes@1.0.0#pool_exhaustion"
    world = _World(
        states={"hyp:para": BeliefState.SUPPORTED},
        relations={"hyp:para": (para_rel,)},
        records={
            "hyp:para": (
                _record(para_rel, warranted=True).model_copy(
                    update={
                        "warrant": WarrantBasis.REVIEW,
                        "warrant_ref": "dwg:para",
                        "identifies": ref,
                    }
                ),
            )
        },
    )
    pool = INCIDENT.declarations[0]
    seen = (("obs:pool-check", pool.signature),)
    control = _standing(world, certificates, INCIDENT, outcomes=seen)
    assert control.confirmable == "hyp:para" and control.declared_class == "pool_exhaustion"
    refuted = _standing(
        world,
        certificates,
        INCIDENT,
        outcomes=(*seen, ("obs:pool-recheck", pool.link("IDLE_CAPACITY"))),
    )
    assert refuted.confirmable is None and refuted.undischarged == ("hyp:para",)
    assert any(
        "IDLE_CAPACITY is an outcome the declared class 'database connection pool exhaustion' "
        "cannot produce" in n
        for n in refuted.notes
    )
    # The same outcome name on another observable refutes nothing.
    elsewhere = (
        "obs:other",
        ("web.query_latency", "os:web.query_latency", "1.0.0", "IDLE_CAPACITY"),
    )
    assert _standing(world, certificates, INCIDENT, outcomes=(*seen, elsewhere)).confirmable
