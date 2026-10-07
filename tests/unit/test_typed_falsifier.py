"""Every admitted hypothesis carries a machine-checkable typed falsifier, without a backend.

A deployed model wrote each falsifier in prose and declared only SUPPORTS predictions. The
deterministic check then observed exactly the outcome its prose falsifier named
(`sp.normalization_basis = AGREES`), and nothing moved: a relation is a prediction's declaration,
never inferred from an outcome that differs from a SUPPORTS prediction. Now every certificate
DESIGNATES its falsifier -- `falsifier_prediction_keys`, at least one of its own predictions with
relation_effect CONTRADICTS -- and the parser, the certificate, the admission gate and `012n` refuse
one that does not. Proven here:

    refused        a prose-only falsifier; an empty designation; a CONTRADICTS prediction that is
                   not designated; a key naming no prediction of the hypothesis (dangling, or the
                   other hypothesis's); a designated SUPPORTS, PREDICTS or TESTS prediction; a
                   designated prediction over an invalid observable, space, version or outcome; a
                   prediction with no key, or a repeated one
    accepted       the exact falsifying outcome with CONTRADICTS, over any declared binding (not
                   necessarily the SUPPORTS one), with other outcomes left unrelated
    certificate    a designation the certificate does not carry, or that does not only CONTRADICT,
                   is refused; the admission gate refuses a certificate with no typed falsifier and
                   writes nothing; the pack's catalog declares each mechanism's falsifier
    debate         every certificate a debate admits designates its own CONTRADICTS predictions
    evidence       a mismatch with a SUPPORTS prediction relates nothing; an outcome no prediction
                   names relates nothing; the exact designated outcome yields CONTRADICTS from that
                   prediction -- in a domain that is not silicon photonics
    qualification  the suite fails each adversarial reply and passes the typed one, and the routes
                   locked under the vocabulary semantics are no longer current

The same path on PostgreSQL and through the web workspace -- Run, Observation, Attestation,
RelationJudgment, TransitionPolicy decision, BeliefRevisionEvent -- is proven in
`tests/integration/test_typed_falsifier_postgres.py` and
`tests/e2e/test_web_typed_falsifier_postgres.py`.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from typing import Any

import pytest

import lab_brain.llm_runtime.registry as registry_module
from lab_brain.cognition.catalog_reasoner import CatalogMechanism, CatalogPrediction
from lab_brain.cognition.roles import HYPOTHESIS_ENGINE, RoleOutputRefused, parse_hypothesis_engine
from lab_brain.core.hypothesis_admission import AdmissionRefusal, HypothesisAdmissionRefused
from lab_brain.core.models.condition import ConditionMatch, ConditionSchemaRef
from lab_brain.core.models.enums import ConditionMatchState, EpistemicType, RelationType
from lab_brain.core.models.hypothesis_set import HypothesisCertificate
from lab_brain.core.models.prediction import OutcomeSpace, Prediction, RelationJudgmentTemplate
from lab_brain.domains.registry import DomainPackRegistry
from lab_brain.domains.silicon_photonics import SiliconPhotonicsPack
from lab_brain.domains.silicon_photonics.product import mechanism_catalog
from lab_brain.llm_runtime.contracts import HYPOTHESIS_CONTRACT, RESPONSE_CONTRACT_VERSION
from lab_brain.llm_runtime.probes import (
    HYPOTHESIS_SUITE,
    PROBE_VERSION,
    QUALIFICATION_DIGEST,
    hypothesis_suite,
)
from lab_brain.llm_runtime.registry import ConnectionRow, lock_fingerprint
from lab_brain.verification.evidence import comparable, evidence_from_run
from lab_brain.verification.workflows import ObservedOutcome
from tests.debate_fixtures import (
    ADMISSION_POLICY,
    DOMAIN,
    PROJECT,
    T0,
    TRACE,
    build_world,
    make_certificate,
    make_set,
)
from tests.job_fixtures import make_run
from tests.toy_domain import (
    TOY_DOMAIN,
    TOY_OBSERVABLE_METRIC,
    TOY_OUTCOME_SPACE,
    TOY_SCHEMA_REF,
    TOY_TIER_A,
    ToyDomainPack,
)

#: `QUALIFICATION_DIGEST` under the prediction vocabulary (probe-4.0.0, prompt 3.0.0, rc-2.0.0),
#: the semantics the LOCAL deployment's current locks were made under.
VOCABULARY_DIGEST = "5f82fb7a15f5e838b567c61ccc1d20b962e20d6aff90877d30601ee9d0f2d4cd"
_MARKER = "\n\nCONTEXT:\n"


def _prediction(key: str, observable: str, outcome: str, effect: str, **over: str) -> dict:
    return {
        "key": key,
        "observable_ref": observable,
        "outcome_space_id": over.get("space", f"os:{observable}"),
        "outcome_space_version": over.get("version", "1.0.0"),
        "expected_outcome": outcome,
        "relation_effect": effect,
    }


SUPPORTS = _prediction("s", "sp.normalization_basis", "DISAGREES", "SUPPORTS")
FALSIFIER = _prediction("f", "sp.normalization_basis", "AGREES", "CONTRADICTS")
#: The other hypothesis's own falsifier, over another binding.
OTHER_FALSIFIER = _prediction("cf", "sp.contact_connectivity", "CONTINUOUS", "CONTRADICTS")


def _certificate(
    key: str, predictions: list[dict], designation: list[str] | None = None
) -> dict[str, Any]:
    certificate: dict[str, Any] = {
        "key": key,
        "statement": f"{key} explains the reading.",
        "mechanism": f"mechanism {key}",
        "assumptions": ["the reading is representative"],
        "falsifier": f"the check that rules out {key} reads its falsifying outcome",
        "confounders": ["placement"],
        "minimal_test_ref": "inspect the layout",
        "predictions": predictions,
    }
    if designation is not None:
        certificate["falsifier_prediction_keys"] = designation
    return certificate


def _reply(first: dict[str, Any]) -> str:
    """`first`, beside a well-formed rival that designates its own falsifier."""
    second = _certificate(
        "h2",
        [
            _prediction("cs", "sp.contact_connectivity", "DISCONTINUOUS", "SUPPORTS"),
            OTHER_FALSIFIER,
        ],
        ["cf"],
    )
    return json.dumps(
        {"hypotheses": [first, second], "position": {"mechanism_view": "h1", "uncertainties": []}}
    )


def _sp_bindings() -> dict[str, OutcomeSpace]:
    registry = DomainPackRegistry()
    registry.install(
        SiliconPhotonicsPack(runner=lambda _r: None, conditions=registry.registries.conditions)  # type: ignore[arg-type,return-value]
    )
    return registry.registries.disagreement_metrics.observable_bindings(DOMAIN)


def _parse(first: dict[str, Any]):  # type: ignore[no-untyped-def]
    return parse_hypothesis_engine(_reply(first), bindings=_sp_bindings(), minimum=2)


# -- the parser: the admission boundary ------------------------------------------------------------


@pytest.mark.parametrize(
    ("first", "refusal"),
    [
        (  # the smoke's shape: a prose falsifier and a SUPPORTS prediction, nothing designated
            _certificate("h1", [SUPPORTS]),
            "hypothesis 'h1' designates no typed falsifier",
        ),
        (_certificate("h1", [SUPPORTS, FALSIFIER], []), "designates no typed falsifier"),
        (  # a CONTRADICTS prediction somewhere in the certificate is not a designation
            _certificate("h1", [SUPPORTS, FALSIFIER]),
            "designates no typed falsifier",
        ),
        (  # ... and cannot excuse designating the SUPPORTS prediction beside it
            _certificate("h1", [SUPPORTS, FALSIFIER], ["s"]),
            "designates falsifier prediction 's', whose relation_effect is SUPPORTS",
        ),
        (
            _certificate("h1", [SUPPORTS, {**FALSIFIER, "relation_effect": "PREDICTS"}], ["f"]),
            "whose relation_effect is PREDICTS",
        ),
        (
            _certificate("h1", [SUPPORTS, {**FALSIFIER, "relation_effect": "TESTS"}], ["f"]),
            "whose relation_effect is TESTS",
        ),
        (  # a key that names nothing
            _certificate("h1", [SUPPORTS, FALSIFIER], ["g"]),
            "designates falsifier prediction 'g', which is not one of its predictions (f, s)",
        ),
        (  # the rival's falsifier is the rival's
            _certificate("h1", [SUPPORTS, FALSIFIER], ["cf"]),
            "designates falsifier prediction 'cf', which is not one of its predictions",
        ),
        (  # a designated falsifier is held to the vocabulary like any prediction
            _certificate(
                "h1",
                [SUPPORTS, {**FALSIFIER, "observable_ref": "os:sp.normalization_basis"}],
                ["f"],
            ),
            "observable 'os:sp.normalization_basis', which is not in the prediction vocabulary",
        ),
        (
            _certificate("h1", [SUPPORTS, {**FALSIFIER, "outcome_space_version": "2.0.0"}], ["f"]),
            "os:sp.normalization_basis@2.0.0, which the engine was not shown",
        ),
        (
            _certificate(
                "h1", [SUPPORTS, {**FALSIFIER, "outcome_space_id": "os:sp.contact_connectivity"}]
            ),
            "reads observable 'sp.normalization_basis' in os:sp.contact_connectivity@1.0.0",
        ),
        (
            _certificate("h1", [SUPPORTS, {**FALSIFIER, "expected_outcome": "NOT_AGREES"}], ["f"]),
            "expects 'NOT_AGREES', which os:sp.normalization_basis@1.0.0 does not admit",
        ),
        (
            _certificate(
                "h1", [SUPPORTS, {k: v for k, v in FALSIFIER.items() if k != "key"}], ["f"]
            ),
            "hypothesis 'h1' has a prediction with no key",
        ),
        (
            _certificate("h1", [SUPPORTS, {**FALSIFIER, "key": "s"}], ["s"]),
            "hypothesis 'h1' repeats prediction key 's'",
        ),
    ],
)
def test_a_certificate_without_a_designated_typed_falsifier_is_refused(first, refusal):
    with pytest.raises(RoleOutputRefused) as refused:
        _parse(first)
    assert refusal in str(refused.value)


def test_the_exact_falsifying_outcome_with_contradicts_is_admitted_as_declared():
    proposals, _ = _parse(_certificate("h1", [SUPPORTS, FALSIFIER], ["f", "f"]))
    first = proposals[0]
    assert first.falsifier_prediction_keys == ("f",), "a repeated key designates once"
    (falsifier,) = (p for p in first.predictions if p.key == "f")
    assert (
        falsifier.observable_ref,
        falsifier.outcome_space_id,
        falsifier.outcome_space_version,
        falsifier.expected_outcome,
        falsifier.relation_effect,
    ) == (
        "sp.normalization_basis",
        "os:sp.normalization_basis",
        "1.0.0",
        "AGREES",
        RelationType.CONTRADICTS,
    )
    assert first.falsifier == "the check that rules out h1 reads its falsifying outcome", (
        "the prose stays, for explanation and inverted retrieval"
    )


def test_a_falsifier_need_not_share_the_supporting_observable_nor_cover_every_outcome():
    # SUPPORTS over the normalization basis, falsified over the contact connectivity.
    elsewhere = _prediction("x", "sp.contact_connectivity", "CONTINUOUS", "CONTRADICTS")
    proposals, _ = _parse(_certificate("h1", [SUPPORTS, elsewhere], ["x"]))
    assert proposals[0].falsifier_prediction_keys == ("x",)
    # A certificate may be nothing but its falsifier; the space's other outcome relates to nothing.
    proposals, _ = _parse(_certificate("h1", [FALSIFIER], ["f"]))
    assert [p.expected_outcome for p in proposals[0].predictions] == ["AGREES"]


# -- the certificate and the admission gate ---------------------------------------------------------


def test_the_certificate_refuses_a_designation_it_does_not_carry_or_that_does_not_contradict():
    hs = make_set()
    typed = make_certificate("normalization_error", hs)
    (falsifier_id,) = typed.falsifier_prediction_ids
    supporting = next(p.prediction_id for p in typed.predictions if p.prediction_id != falsifier_id)
    body = typed.model_dump()
    with pytest.raises(ValueError, match="which its certificate does not carry"):
        HypothesisCertificate.model_validate({**body, "falsifier_prediction_ids": ["prd:absent"]})
    with pytest.raises(ValueError, match=r"declares \['SUPPORTS'\]; a falsifier declares only"):
        HypothesisCertificate.model_validate({**body, "falsifier_prediction_ids": [supporting]})
    mixed = typed.predictions[0].model_copy(
        update={
            "relation_effect_if_observed": (
                RelationJudgmentTemplate(
                    relation_type=RelationType.CONTRADICTS, to_entity_id=typed.hypothesis_id
                ),
                RelationJudgmentTemplate(
                    relation_type=RelationType.SUPPORTS, to_entity_id=typed.hypothesis_id
                ),
            )
        }
    )
    with pytest.raises(ValueError, match="a falsifier declares only CONTRADICTS"):
        HypothesisCertificate.model_validate(
            {
                **body,
                "predictions": [mixed.model_dump(), typed.predictions[1].model_dump()],
                "falsifier_prediction_ids": [mixed.prediction_id],
            }
        )


@pytest.mark.parametrize("carried", [False, True], ids=["prose-only", "undesignated"])
def test_the_admission_gate_refuses_a_certificate_with_no_typed_falsifier(carried):
    world = build_world()
    hs = make_set()
    plain = make_certificate("mesh_artifact", hs, typed_falsifier=carried)
    if carried:  # the CONTRADICTS prediction is carried, and nothing designates it
        plain = HypothesisCertificate.model_validate(
            {**plain.model_dump(), "falsifier_prediction_ids": []}
        )
        assert any(
            e.relation_type is RelationType.CONTRADICTS
            for p in plain.predictions
            for e in p.relation_effect_if_observed
        )
    certificates = [make_certificate("contact_discontinuity", hs), plain]
    with pytest.raises(HypothesisAdmissionRefused) as refused:
        world.admission.admit_set(
            hs,
            certificates,
            basis=tuple(sorted(world.attestations))[:2],
            policy=ADMISSION_POLICY,
            event_ids=[f"bre:{c.hypothesis_id.split(':', 1)[1]}" for c in certificates],
            occurred_at=T0,
            trace_id=TRACE,
        )
    assert refused.value.reason is AdmissionRefusal.INCOMPLETE_CERTIFICATE
    assert "no typed falsifier" in refused.value.detail
    assert world.hypotheses.get_set(hs.set_id) is None, "a refused set writes nothing"
    for c in certificates:
        assert world.events.history(PROJECT, c.hypothesis_id) == ()


def test_the_packs_catalog_declares_each_mechanisms_falsifier_and_refuses_one_without():
    for mechanism in mechanism_catalog().mechanisms:
        designated = [
            p for p in mechanism.predictions if p.key in mechanism.falsifier_prediction_keys
        ]
        assert designated and all(p.relation_effect == "CONTRADICTS" for p in designated)
    supports = CatalogPrediction("s", "o", "os:o", "1.0.0", "A", "SUPPORTS")
    contradicts = CatalogPrediction("f", "o", "os:o", "1.0.0", "B", "CONTRADICTS")
    base: dict[str, Any] = {
        "key": "k",
        "statement": "s",
        "mechanism": "m",
        "assumptions": ("a",),
        "confounders": ("c",),
        "falsifier": "f",
        "minimal_test_ref": "t",
        "predictions": (supports, contradicts),
        "cues": ("cue",),
    }
    assert CatalogMechanism(**base, falsifier_prediction_keys=("f",))
    for designation, why in (((), "no typed falsifier"), (("s",), "not one of its CONTRADICTS")):
        with pytest.raises(ValueError, match=why):
            CatalogMechanism(**base, falsifier_prediction_keys=designation)


# -- the debate ---------------------------------------------------------------------------------


def test_every_certificate_a_debate_admits_designates_its_own_contradictions():
    world = build_world()
    outcome = world.debate.run(world.request())
    assert len(outcome.certificates) >= 2
    for certificate in outcome.certificates:
        assert certificate.falsifier_prediction_ids, certificate.hypothesis_id
        carried = {p.prediction_id: p for p in certificate.predictions}
        for prediction_id in certificate.falsifier_prediction_ids:
            prediction = carried[prediction_id]
            assert prediction.hypothesis_id == certificate.hypothesis_id
            assert [
                (e.relation_type, e.to_entity_id) for e in prediction.relation_effect_if_observed
            ] == [(RelationType.CONTRADICTS, certificate.hypothesis_id)]
        stored = world.hypotheses.get_certificate(PROJECT, certificate.hypothesis_id)
        assert stored is not None
        assert stored.falsifier_prediction_ids == certificate.falsifier_prediction_ids
    # The engine saw the rule it is held to.
    prompt = next(
        p for p in world.scientist.prompts_seen if p.startswith(HYPOTHESIS_ENGINE.prompt.template)
    )
    assert "falsifier_prediction_keys" in prompt


# -- evidence: a relation only from a declared prediction, in a domain that is not this one -------


def _toy(prediction_id: str, outcome: str, effect: RelationType) -> Prediction:
    return Prediction(
        prediction_id=prediction_id,
        hypothesis_id="hyp:toy",
        project_id=PROJECT,
        observable_ref=TOY_OBSERVABLE_METRIC,
        outcome_space_id=TOY_OUTCOME_SPACE,
        outcome_space_version="1.0.0",
        expected_outcome=outcome,
        relation_effect_if_observed=(
            RelationJudgmentTemplate(relation_type=effect, to_entity_id="hyp:toy"),
        ),
    )


def _observed(outcome: str) -> ObservedOutcome:
    return ObservedOutcome(
        observable_ref=TOY_OBSERVABLE_METRIC,
        outcome_space_id=TOY_OUTCOME_SPACE,
        outcome_space_version="1.0.0",
        outcome=outcome,
        epistemic_type=EpistemicType.OBSERVED,
        authority_class=TOY_TIER_A,
        method_ref="toy.rule.widget_verdict@1.0.0",
    )


def _evidence(outcome: str, predictions: tuple[Prediction, ...]):  # type: ignore[no-untyped-def]
    ids = iter(range(1, 100))
    return evidence_from_run(
        run=make_run(
            "run:toy",
            project_id=PROJECT,
            outputs=("art:toy",),
            conditions_schema_version=TOY_SCHEMA_REF,
        ),
        outcome=_observed(outcome),
        predictions=predictions,
        condition_match=ConditionMatch(
            condition_match_id="cmt:toy",
            state=ConditionMatchState.EXACT,
            matched_fields=("widget",),
            tolerance_policy_version="1.0.0",
            schema_ref=ConditionSchemaRef.parse(TOY_SCHEMA_REF),
            created_at=T0,
        ),
        actor_id="act:researcher",
        mint=lambda kind: f"{kind}:{next(ids)}",
        at=dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
    )


def test_only_a_declared_prediction_relates_an_outcome_and_the_falsifier_contradicts():
    registry = DomainPackRegistry()
    registry.install(ToyDomainPack())
    toy = registry.registries.disagreement_metrics.observable_bindings(TOY_DOMAIN)
    assert set(toy[TOY_OBSERVABLE_METRIC].outcomes) == {"STIFF", "FLOPPY", "BROKEN"}
    supports = _toy("prd:toy.s", "STIFF", RelationType.SUPPORTS)
    falsifier = _toy("prd:toy.f", "BROKEN", RelationType.CONTRADICTS)

    # A mismatch with a SUPPORTS prediction is not a contradiction: nothing is inferred from it.
    alone = _evidence("BROKEN", (supports,))
    assert not comparable(supports, _observed("BROKEN"))
    assert alone.relations == () and alone.matched_prediction_ids == ()
    assert alone.observation.value == "BROKEN", "on record, moving nothing"
    # An outcome that differs from both declarations relates to nothing either.
    neither = _evidence("FLOPPY", (supports, falsifier))
    assert neither.relations == ()
    # The exact declared falsifying outcome: CONTRADICTS, from that prediction, traceable.
    falsified = _evidence("BROKEN", (supports, falsifier))
    assert falsified.matched_prediction_ids == ("prd:toy.f",)
    (relation,) = falsified.relations
    assert (relation.relation_type, relation.to_entity_id) == (RelationType.CONTRADICTS, "hyp:toy")
    assert relation.attributes["prediction_id"] == "prd:toy.f"
    assert relation.from_entity_id == falsified.observation.observation_id
    assert relation.supporting_attestation_ids == (falsified.attestation.attestation_id,)
    assert falsified.attestation.run_id == falsified.observation.run_id == "run:toy"

    # The toy pack's certificates are held to the same contract through the same parser.
    reply = json.loads(_reply(_certificate("h1", [FALSIFIER], ["f"])))
    for certificate in reply["hypotheses"]:
        certificate["predictions"] = [
            _prediction(k, TOY_OBSERVABLE_METRIC, o, e, space=TOY_OUTCOME_SPACE)
            for k, o, e in (("s", "STIFF", "SUPPORTS"), ("f", "BROKEN", "CONTRADICTS"))
        ]
        certificate["falsifier_prediction_keys"] = ["f"]
    proposals, _ = parse_hypothesis_engine(json.dumps(reply), bindings=toy, minimum=2)
    assert all(p.falsifier_prediction_keys == ("f",) for p in proposals)
    reply["hypotheses"][0]["falsifier_prediction_keys"] = ["s"]
    with pytest.raises(RoleOutputRefused, match="whose relation_effect is SUPPORTS"):
        parse_hypothesis_engine(json.dumps(reply), bindings=toy, minimum=2)


def test_the_contract_lives_in_generic_code_that_imports_no_domain_pack():
    modules = (
        "lab_brain.cognition.roles",
        "lab_brain.cognition.debate",
        "lab_brain.core.models.hypothesis_set",
        "lab_brain.core.repositories.hypotheses",
        "lab_brain.core.hypothesis_admission",
        "lab_brain.verification.evidence",
        "lab_brain.llm_runtime.contracts",
        "lab_brain.llm_runtime.probes",
    )
    code = (
        f"import sys; import {', '.join(modules)}; "
        "print(sorted(m for m in sys.modules if m.startswith('lab_brain.domains.')))"
    )
    loaded = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    ).stdout
    assert "silicon_photonics" not in loaded, loaded


# -- qualification ---------------------------------------------------------------------------------


def _suite_reply(entries: list[dict[str, Any]], shape: str) -> str:
    """Five certificates over the case's first binding, typed or in one adversarial `shape`."""
    entry = entries[0]

    def p(key: str, outcome: str, effect: str) -> dict[str, str]:
        return {
            "key": key,
            "observable_ref": entry["observable_ref"],
            "outcome_space_id": entry["outcome_space_id"],
            "outcome_space_version": entry["outcome_space_version"],
            "expected_outcome": outcome,
            "relation_effect": effect,
        }

    first, last = entry["outcomes"][0], entry["outcomes"][-1]
    predictions, designation = {
        "typed": ([p("s", first, "SUPPORTS"), p("f", last, "CONTRADICTS")], ["f"]),
        "prose-only": ([p("s", first, "SUPPORTS")], None),
        "unrelated-contradicts": ([p("s", first, "SUPPORTS"), p("f", last, "CONTRADICTS")], ["s"]),
        "designated-predicts": ([p("s", first, "SUPPORTS"), p("f", last, "PREDICTS")], ["f"]),
        "designated-tests": ([p("s", first, "SUPPORTS"), p("f", last, "TESTS")], ["f"]),
        "dangling": ([p("s", first, "SUPPORTS"), p("f", last, "CONTRADICTS")], ["g"]),
    }[shape]
    return json.dumps(
        {
            "hypotheses": [
                {**_certificate(f"h{n}", predictions, designation), "mechanism": f"m{n}"}
                for n in range(5)
            ],
            "position": {"mechanism_view": "m0", "uncertainties": []},
        }
    )


def test_the_suite_passes_only_hypotheses_that_designate_a_typed_falsifier():
    for name, case in hypothesis_suite(5):
        entries = json.loads(case.prompt.split(_MARKER, 1)[1])["prediction_bindings"]
        assert case.judge(_suite_reply(entries, "typed")) is None, name
        for shape, why in (
            ("prose-only", "designates no typed falsifier"),
            ("unrelated-contradicts", "whose relation_effect is SUPPORTS"),
            ("designated-predicts", "whose relation_effect is PREDICTS"),
            ("designated-tests", "whose relation_effect is TESTS"),
            ("dangling", "which is not one of its predictions"),
        ):
            failed = case.judge(_suite_reply(entries, shape))
            assert failed is not None and why in failed, (name, shape, failed)
        assert "falsifier_prediction_keys" in case.prompt and case.system == HYPOTHESIS_CONTRACT
    # The prompt and the contract say the rule the parser enforces, and that nothing is inferred.
    template = HYPOTHESIS_ENGINE.prompt.template
    assert "lists that prediction's key in falsifier_prediction_keys" in template
    assert "an outcome no prediction names relates to nothing" in template
    assert '"falsifier_prediction_keys": ["<key of one of this hypothesis' in HYPOTHESIS_CONTRACT
    assert "never a SUPPORTS, PREDICTS or TESTS prediction" in HYPOTHESIS_CONTRACT
    assert "an outcome no prediction names relates to nothing" in HYPOTHESIS_CONTRACT


def test_the_routes_locked_under_the_vocabulary_semantics_are_no_longer_current(monkeypatch):
    assert (HYPOTHESIS_ENGINE.prompt.prompt_version, RESPONSE_CONTRACT_VERSION) == (
        "4.0.0",
        "rc-3.0.0",
    )
    assert (PROBE_VERSION, HYPOTHESIS_SUITE) == ("probe-5.0.0", "hypothesis-conformance@3.0.0")
    assert QUALIFICATION_DIGEST != VOCABULARY_DIGEST
    # The two locks the LOCAL deployment holds, recomputed from their public parts.
    ollama = ConnectionRow(
        "llc:x",
        "ollama",
        "OPENAI_COMPATIBLE",
        "http://host.docker.internal:11434/v1",
        "LOCAL",
        None,
        None,
        "ENABLED",
        "act:x",
        None,  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
    )
    roles = ["CHAT", "ROLE_CRITIQUE", "ROLE_HYPOTHESIS", "ROLE_QUERY", "ROLE_SPECIALIST"]
    shown = {
        "ROLE_HYPOTHESIS": {
            "minimum_hypotheses": 5,
            "suite": "hypothesis-conformance@2.0.0",
            "cases": ["contextual-minimum", "multi-space"],
        }
    }
    locks = (
        ("qwen2.5-coder:7b", sorted([*roles, "CODE", "STRUCTURED_JSON"]), "lk:de37c0ddb915b220"),
        ("qwen2.5:7b", sorted([*roles, "STRUCTURED_JSON"]), "lk:427cdea03b491e41"),
    )
    for model, caps, fingerprint in locks:
        assert lock_fingerprint(ollama, model, caps, shown) != fingerprint
    monkeypatch.setattr(registry_module, "QUALIFICATION_DIGEST", VOCABULARY_DIGEST)
    for model, caps, fingerprint in locks:
        assert lock_fingerprint(ollama, model, caps, shown) == fingerprint
