"""The designated typed falsifier is the ONLY machine falsifier; the prose explains, nothing more.

The deployed model wrote a certificate whose prose falsifier named one outcome (the normalization
basis AGREES) and whose designated typed falsifier named the other (DISAGREES -> CONTRADICTS).
Verification adjudicated the typed one; the debate's inverted retrieval and the Critic were given
the prose -- two authorities for one falsifier. Now every machine path reads the designation,
rendered by `typed_falsifier_text`; the prose is kept and shown, labelled as the model's
explanation. Nothing compares the two or decides which is meant. Proven here, with every certificate
written the way the deployed model wrote its own -- prose naming outcome A, designation naming B:

    admissible     such a certificate is admitted under the unchanged typed rules
    retrieval      the inverted Evidence Researcher is shown, and searches with, B; never the prose
    critic         the Critic is shown B as each hypothesis's falsifier; never the prose
    verification   observing B instantiates the predeclared CONTRADICTS; observing A relates nothing
    several        two designated falsifiers are rendered and consumed in prediction-id order,
                   identically on every run
    history        the stored prose and predictions are exactly what the model wrote
    report         the episode report shows the machine falsifier and the prose, labelled
    generic        the rendering is the prediction's own fields, in any domain
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from lab_brain.cognition.roles import ADVERSARIAL_CRITIC, QUERY_REWRITER
from lab_brain.core.models.enums import EpistemicType, RelationType
from lab_brain.core.models.hypothesis_set import HypothesisCertificate, typed_falsifier_text
from lab_brain.core.models.prediction import Prediction, RelationJudgmentTemplate
from lab_brain.domains.silicon_photonics import vertical as sp
from lab_brain.interfaces.web import pages
from lab_brain.research.render import render_markdown
from lab_brain.verification.evidence import evidence_from_run
from lab_brain.verification.workflows import ObservedOutcome
from tests.debate_fixtures import (
    PROJECT,
    MockScientist,
    build_world,
    fixture_falsifier,
    load_fixture,
)
from tests.job_fixtures import make_run
from tests.report_samples import full_report
from tests.vertical_units import exact_match

#: A word only the prose uses, so its absence from a machine path is unambiguous.
PROSE_MARK = "quokka"
_MARKER = "\n\nCONTEXT:\n"


def _other_outcome(observable: str, outcome: str) -> str:
    """The binding's other outcome -- what the prose names, as the deployed model's did."""
    outcomes = {
        "sp.contact_connectivity": ("CONTINUOUS", "DISCONTINUOUS"),
        "sp.normalization_basis": ("AGREES", "DISAGREES"),
        "sp.mesh_stability": ("STABLE", "UNSTABLE"),
        "sp.carrier_profile": ("NOMINAL", "COMPENSATED"),
    }[observable]
    return next(o for o in outcomes if o != outcome)


@dataclass
class _SplitScientist(MockScientist):
    """Writes every certificate as the deployed model wrote its own: prose naming outcome A, the
    designated typed falsifier naming B. `second` designates a second falsifier too."""

    second: bool = False

    def _certificate(self, key: str) -> dict[str, Any]:
        certificate = super()._certificate(key)
        typed = fixture_falsifier(key)
        certificate["falsifier"] = (
            f"{PROSE_MARK}: {typed['observable_ref']} reads "
            f"{_other_outcome(typed['observable_ref'], typed['expected_outcome'])}"
        )
        if self.second:
            certificate["predictions"].append(
                {
                    "key": "falsifier2",
                    "observable_ref": sp.OBS_PROBE,
                    "outcome_space_id": sp.SPACE_PROBE,
                    "outcome_space_version": sp.SPACE_VERSION,
                    "expected_outcome": "ELEVATED",
                    "relation_effect": "CONTRADICTS",
                }
            )
            certificate["falsifier_prediction_keys"] = ["falsifier2", "falsifier"]
        return certificate


def _split_world(second: bool = False):  # type: ignore[no-untyped-def]
    fx = load_fixture()
    scientist = _SplitScientist(
        mechanisms=fx["mechanisms"],
        primary_terms=fx["primary_terms"],
        outcome_space=fx["outcome_space"],
        second=second,
    )
    world = build_world(fx["cases"][0], scientist=scientist)
    return world, world.debate.run(world.request())


def _contexts(world, template: str) -> list[Mapping[str, Any]]:  # type: ignore[no-untyped-def]
    return [
        json.loads(p.split(_MARKER, 1)[1])
        for p in world.scientist.prompts_seen
        if p.startswith(template)
    ]


def _expected(certificates: tuple[HypothesisCertificate, ...]) -> list[str]:
    return [typed_falsifier_text(p) for c in certificates for p in c.falsifier_predictions]


def test_a_prose_and_typed_split_is_admitted_and_kept_as_written():
    world, outcome = _split_world()
    assert len(outcome.certificates) >= 2
    for certificate in outcome.certificates:
        (falsifier,) = certificate.falsifier_predictions
        assert PROSE_MARK in certificate.hypothesis.falsifier
        assert falsifier.expected_outcome not in certificate.hypothesis.falsifier.split()[-1:], (
            "the prose names the other outcome"
        )
        stored = world.hypotheses.get_certificate(PROJECT, certificate.hypothesis_id)
        assert stored == certificate, "prose and predictions as the model wrote them"


def test_inverted_retrieval_searches_the_typed_falsifier_never_the_prose():
    world, outcome = _split_world()
    inverted = [
        c for c in _contexts(world, QUERY_REWRITER.prompt.template) if c["mode"] == "INVERTED"
    ]
    assert inverted
    for context in inverted:
        assert context["falsifiers"], "the designation is what it is shown"
        assert set(context["falsifiers"]) <= set(_expected(outcome.certificates))
        assert PROSE_MARK not in json.dumps(context)
    # And the stored inverted bundle's query is built from the same designation.
    inverted_ids = {c.inverted_bundle_id for c in outcome.critiques if c.inverted_bundle_id}
    assert inverted_ids
    for bundle_id in inverted_ids:
        query = world.bundles.get(bundle_id).query_text
        assert PROSE_MARK not in query
        assert any(text in query for text in _expected(outcome.certificates))


def test_the_critic_is_shown_the_typed_falsifier_never_the_prose():
    world, outcome = _split_world()
    by_id = {c.hypothesis_id: c for c in outcome.certificates}
    critiques = _contexts(world, ADVERSARIAL_CRITIC.prompt.template)
    assert critiques
    for context in critiques:
        assert PROSE_MARK not in json.dumps(context)
        for entry in context["hypotheses"]:
            certificate = by_id[entry["hypothesis_id"]]
            assert entry["falsifier"] == "; ".join(
                typed_falsifier_text(p) for p in certificate.falsifier_predictions
            )


def _observe(certificate: HypothesisCertificate, outcome: str):  # type: ignore[no-untyped-def]
    (falsifier,) = certificate.falsifier_predictions
    ids = iter(range(1, 100))
    return evidence_from_run(
        run=make_run(
            "run:split",
            project_id=PROJECT,
            outputs=("art:split",),
            conditions={"device_length_um": "500"},
            conditions_schema_version=sp.DEVICE_SCHEMA_REF,
        ),
        outcome=ObservedOutcome(
            observable_ref=falsifier.observable_ref,
            outcome_space_id=falsifier.outcome_space_id,
            outcome_space_version=falsifier.outcome_space_version,
            outcome=outcome,
            epistemic_type=EpistemicType.OBSERVED,
            authority_class=sp.DESIGN_INSPECTION,
            method_ref="test.rule.reader@1.0.0",
        ),
        predictions=certificate.predictions,
        condition_match=exact_match(),
        actor_id="act:researcher",
        mint=lambda kind: f"{kind}:{next(ids)}",
        at=dt.datetime(2026, 10, 8, tzinfo=dt.UTC),
    )


def test_verification_adjudicates_the_typed_falsifier_and_the_prose_outcome_relates_nothing():
    _, outcome = _split_world()
    for certificate in outcome.certificates:
        (falsifier,) = certificate.falsifier_predictions
        prose_outcome = _other_outcome(falsifier.observable_ref, falsifier.expected_outcome)
        assert certificate.hypothesis.falsifier.endswith(prose_outcome)
        named_in_prose = _observe(certificate, prose_outcome)
        assert named_in_prose.relations == (), "the prose named it; no prediction declared it"
        designated = _observe(certificate, falsifier.expected_outcome)
        (relation,) = designated.relations
        assert (relation.relation_type, relation.to_entity_id) == (
            RelationType.CONTRADICTS,
            certificate.hypothesis_id,
        )
        assert relation.attributes["prediction_id"] == falsifier.prediction_id


def test_several_designated_falsifiers_are_rendered_and_consumed_in_id_order_every_time():
    first_world, first = _split_world(second=True)
    second_world, second = _split_world(second=True)
    for certificate in first.certificates:
        designated = certificate.falsifier_predictions
        assert len(designated) == 2
        assert [p.prediction_id for p in designated] == sorted(certificate.falsifier_prediction_ids)
    assert _expected(first.certificates) == _expected(second.certificates)

    def consumed(world):  # type: ignore[no-untyped-def]
        inverted = [
            c["falsifiers"]
            for c in _contexts(world, QUERY_REWRITER.prompt.template)
            if c["mode"] == "INVERTED"
        ]
        critic = [
            [e["falsifier"] for e in c["hypotheses"]]
            for c in _contexts(world, ADVERSARIAL_CRITIC.prompt.template)
        ]
        return inverted, critic

    inverted, critic = consumed(first_world)
    assert inverted and critic
    assert (inverted, critic) == consumed(second_world), "deterministic"
    for entries in critic:
        for entry in entries:
            assert entry.count(" -> CONTRADICTS ") == 2 and "; " in entry


def test_the_report_shows_the_machine_falsifier_and_the_prose_labelled():
    report = full_report()
    (line,) = report.hypotheses
    assert line.machine_falsifiers and line.falsifier not in line.machine_falsifiers
    markdown = render_markdown(report)
    assert f"Machine falsifier (what verification adjudicates): `{line.machine_falsifiers[0]}`" in (
        markdown
    )
    assert f"Model's explanation (prose falsifier, not adjudicated): {line.falsifier}" in markdown
    html = pages.report_html(report)
    assert "Machine falsifier -- what verification adjudicates:" in html
    assert "Model&#x27;s explanation (prose falsifier, not adjudicated):" in html or (
        "Model's explanation (prose falsifier, not adjudicated):" in html
    )


def test_the_rendering_is_the_predictions_own_fields_in_any_domain():
    toy = Prediction(
        prediction_id="prd:toy.f",
        hypothesis_id="hyp:toy",
        project_id=PROJECT,
        observable_ref="toy.widget_stiffness",
        outcome_space_id="os:toy.widget_verdict",
        outcome_space_version="1.0.0",
        expected_outcome="BROKEN",
        relation_effect_if_observed=(
            RelationJudgmentTemplate(
                relation_type=RelationType.CONTRADICTS, to_entity_id="hyp:toy"
            ),
        ),
    )
    assert typed_falsifier_text(toy) == (
        "toy.widget_stiffness = BROKEN in os:toy.widget_verdict@1.0.0 -> CONTRADICTS hyp:toy "
        "(prd:toy.f)"
    )
