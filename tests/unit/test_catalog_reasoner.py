"""The local rule-based reasoner: what it reads, what it answers, and what it never claims to be."""

from __future__ import annotations

import json

import pytest

from lab_brain.cognition.catalog_reasoner import CatalogReasoner, reasoner_slots
from lab_brain.cognition.llm import ModelSlot
from lab_brain.cognition.roles import ADVERSARIAL_CRITIC, HYPOTHESIS_ENGINE, QUERY_REWRITER
from lab_brain.core.models.inference import LogicalSlot
from lab_brain.domains.silicon_photonics.product import mechanism_catalog
from lab_brain.security.external import ExternalReach

CATALOG = mechanism_catalog()
SLOT = ModelSlot(LogicalSlot.REASONING_PRIMARY, "rules:x", "1.0.0", reach=ExternalReach.LOCAL)


def _ask(template: str, context: dict) -> dict:  # type: ignore[type-arg]
    reply = CatalogReasoner(CATALOG)(f"{template}\n\nCONTEXT:\n{json.dumps(context)}", SLOT)
    return json.loads(reply)  # type: ignore[no-any-return]


def _evidence(*texts: str) -> list[dict[str, str]]:
    return [
        {"attestation_id": f"att:{n}", "trust_class": "INTERNAL_MEASUREMENT", "text": t}
        for n, t in enumerate(texts)
    ]


def test_the_engine_ranks_the_catalog_by_what_the_evidence_mentions_and_proposes_all_rivals():
    reply = _ask(
        HYPOTHESIS_ENGINE.prompt.template,
        {
            "question": "why is Rs high",
            "evidence": _evidence("a mesh convergence warning", "the mesh was coarse"),
            "outcome_spaces": [],
            "minimum_hypotheses": len(CATALOG.mechanisms),
        },
    )
    keys = [h["key"] for h in reply["hypotheses"]]
    assert keys[0] == "mesh_artifact"
    assert sorted(keys) == sorted(m.key for m in CATALOG.mechanisms)
    for h in reply["hypotheses"]:
        effects = {p["relation_effect"] for p in h["predictions"]}
        assert effects == {"SUPPORTS", "CONTRADICTS"}, "each check can support and contradict"
    assert "mesh convergence artifact" in reply["position"]["mechanism_view"]


def test_evidence_that_names_no_mechanism_is_said_to_name_none():
    reply = _ask(
        HYPOTHESIS_ENGINE.prompt.template,
        {"evidence": _evidence("the wafer was blue"), "minimum_hypotheses": 2},
    )
    assert "names none" in reply["position"]["mechanism_view"]


def test_the_critic_objects_only_from_inverted_evidence_it_was_shown():
    hypotheses = [{"hypothesis_id": "hyp:c", "mechanism": "access contact discontinuity"}]
    shown = _evidence("contact continuity verified by the probe station team")
    not_inverted = _ask(
        ADVERSARIAL_CRITIC.prompt.template,
        {"hypotheses": hypotheses, "evidence": shown, "inverted_attestation_ids": []},
    )
    assert not_inverted["objections"] == []
    inverted = _ask(
        ADVERSARIAL_CRITIC.prompt.template,
        {"hypotheses": hypotheses, "evidence": shown, "inverted_attestation_ids": ["att:0"]},
    )
    (objection,) = inverted["objections"]
    assert objection["target_id"] == "hyp:c" and objection["severity"] == "CONTRADICTS"
    assert objection["evidence_attestation_ids"] == ["att:0"]


def test_the_critic_names_alternatives_the_evidence_points_at_and_no_hypothesis_covers():
    reply = _ask(
        ADVERSARIAL_CRITIC.prompt.template,
        {
            "hypotheses": [{"hypothesis_id": "hyp:c", "mechanism": "access contact discontinuity"}],
            "evidence": _evidence("a counterdoping step was added to the rib implant"),
        },
    )
    assert reply["alternative_mechanisms"] == ["dopant compensation in the rib"]


def test_query_rewrites_come_from_the_catalog_or_the_falsifiers():
    primary = _ask(QUERY_REWRITER.prompt.template, {"question": "q", "mode": "PRIMARY"})
    assert primary["terms"] == list(CATALOG.primary_terms)
    inverted = _ask(
        QUERY_REWRITER.prompt.template,
        {"question": "q", "mode": "INVERTED", "falsifiers": ["refining the mesh"]},
    )
    assert inverted["terms"] == ["refining", "the", "mesh"]


def test_an_unknown_prompt_is_refused_and_the_slots_name_the_reasoner_for_what_it_is():
    with pytest.raises(ValueError, match="no rule"):
        CatalogReasoner(CATALOG)("You are something else.", SLOT)
    slots = reasoner_slots(CATALOG, (LogicalSlot.REASONING_PRIMARY, LogicalSlot.FAST_UTILITY))
    for slot in slots:
        assert slot.model_id == f"rules:{CATALOG.catalog_id}"
        assert slot.provider == "local-rules" and slot.reach is ExternalReach.LOCAL
