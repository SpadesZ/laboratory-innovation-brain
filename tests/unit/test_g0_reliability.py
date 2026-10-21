"""G0 research reliability, without a backend: identifiers, replies, retries and coverage.

Four live research runs with a real model failed or fell short in ways the earlier tests did not
reach. Each failure is reproduced here from what the model actually sent, and the repair is shown
to hold without weakening any gate:

    ids         a specialist shortened `hyp:<uuid>` to eight characters. Roles are now shown short
                aliases (`H1`, `E1`) and the parser maps them back -- exactly, never by prefix
    envelope    a Hypothesis Engine reply wrapped in one ```json fence. That envelope, and only it,
                is removed before parsing, and the repair is recorded
    retries     a refused reply is asked for once more with the parser's reason, as a new recorded
                inference; a reply refused every time still builds nothing
    coverage    five rivals left the cheapest discriminating check unaddressed. A review now asks
                about exactly such checks -- named by cost and coverage, never by an answer -- and
                a reply may decline; a rival it adds must cite evidence
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import pytest

from lab_brain.cognition.aliases import AliasTable, aliased, resolve
from lab_brain.cognition.coverage import unaddressed_checks
from lab_brain.cognition.debate import DebatePolicy
from lab_brain.cognition.llm import ModelSlot
from lab_brain.cognition.roles import (
    STRIPPED_CODE_FENCE,
    RoleOutputRefused,
    normalize_reply,
    parse_coverage_review,
    parse_critique,
    parse_hypothesis_engine,
    parse_specialist,
)
from lab_brain.core.models.prediction import OutcomeSpace
from lab_brain.domains.silicon_photonics import vertical as sp
from lab_brain.domains.silicon_photonics.tools import INPUT_DEVICE_PROJECT
from tests.debate_fixtures import MockScientist, build_world, load_fixture

MARKER = "\n\nCONTEXT:\n"
#: The two hypothesis ids of the first live run, and what its specialist wrote for them.
LIVE_IDS = ("hyp:9a8257a7-5f0e-4d1c-9a51-3c2e1f6b7d10", "hyp:6f488e12-0b7d-4c55-8e2a-91d4b3a6c2f7")
LIVE_SHORTENED = ["hyp:9a8257a7", "hyp:6f488e12"]


def _context(material: str) -> dict[str, Any]:
    return dict(json.loads(material.split(MARKER, 1)[1])) if MARKER in material else {}


# -- the alias table ---------------------------------------------------------------------------


def test_aliases_are_deterministic_append_only_and_one_to_one():
    table = AliasTable("H")
    assert [table.add(i) for i in ("hyp:b", "hyp:a", "hyp:b")] == ["H1", "H2", "H1"]
    assert table.alias("hyp:a") == "H2" and table.shown(["hyp:a"]) == {"H2": "hyp:a"}
    again = AliasTable("H")
    assert [again.add(i) for i in ("hyp:b", "hyp:a")] == ["H1", "H2"], "same order, same aliases"
    shown, by_alias = aliased([{"hypothesis_id": "hyp:a", "x": 1}], "hypothesis_id", table)
    assert shown == [{"hypothesis_id": "H2", "x": 1}] and by_alias == {"H2": "hyp:a"}


@pytest.mark.parametrize("canonical", ["H1", "E12", " ", ""])
def test_a_canonical_id_that_could_be_read_as_an_alias_is_refused(canonical):
    with pytest.raises(ValueError, match="ambiguous"):
        AliasTable("H").add(canonical)


def test_a_reference_resolves_only_exactly():
    table = AliasTable("H")
    shown = table.shown(LIVE_IDS)
    assert resolve("H1", shown) == LIVE_IDS[0]
    assert resolve(LIVE_IDS[1], shown) == LIVE_IDS[1], "a canonical id in full names itself"
    for bad in (*LIVE_SHORTENED, "h1", "H01", "H 1", "H3", " H1", LIVE_IDS[0].upper()):
        assert resolve(bad, shown) is None, bad


# -- the specialist and the critic ---------------------------------------------------------------


def _specialist(favoured: list[str], *, shown: Mapping[str, str] | None = None) -> Any:
    return parse_specialist(
        json.dumps({"mechanism_view": "contact resistance", "favoured_hypothesis_ids": favoured}),
        role_id="sp.specialist.semiconductor_device",
        hypothesis_ids=list(LIVE_IDS),
        shown=shown if shown is not None else AliasTable("H").shown(LIVE_IDS),
    )


def test_the_specialist_names_rivals_by_alias_and_the_position_records_canonical_ids():
    assert _specialist(["H2", "H1"]).favoured == (LIVE_IDS[1], LIVE_IDS[0])
    assert _specialist([LIVE_IDS[0]]).favoured == (LIVE_IDS[0],)
    assert _specialist([]).favoured == ()


@pytest.mark.parametrize(
    ("favoured", "why"),
    [
        # What the first live run's specialist actually sent.
        (LIVE_SHORTENED, "not under consideration"),
        (["H3"], "not under consideration"),
        (["h1"], "not under consideration"),
        (["Hypothesis 1"], "not under consideration"),
        (["hyp:9a8257a7-5f0e-4d1c-9a51-3c2e1f6b7d1"], "not under consideration"),
        (["H1", "H1"], "already listed"),
        (["H1", LIVE_IDS[0]], "already listed"),
        ([""], "non-empty strings"),
    ],
)
def test_a_specialist_reference_that_names_nothing_exactly_is_refused(favoured, why):
    with pytest.raises(RoleOutputRefused, match=why):
        _specialist(favoured)


def test_an_alias_of_a_hypothesis_the_call_did_not_show_is_refused():
    table = AliasTable("H")
    table.add("hyp:other-project-or-round")
    shown = table.shown(LIVE_IDS)  # H2, H3
    with pytest.raises(RoleOutputRefused, match="not under consideration"):
        _specialist(["H1"], shown=shown)
    assert _specialist(["H2"], shown=shown).favoured == (LIVE_IDS[0],)


def test_a_malformed_proposed_prediction_is_a_refusal_not_a_crash():
    with pytest.raises(RoleOutputRefused, match="proposed prediction is malformed"):
        parse_specialist(
            json.dumps(
                {
                    "mechanism_view": "v",
                    "favoured_hypothesis_ids": [],
                    "proposed_predictions": [{"observable_ref": "x"}],
                }
            ),
            role_id="sp.s",
            hypothesis_ids=list(LIVE_IDS),
        )


def _critique(objection: dict[str, Any], challenges: list[dict[str, str]] | None = None) -> Any:
    hyp = AliasTable("H").shown(LIVE_IDS)
    ev = AliasTable("E").shown(["att:7a", "att:7b"])
    return parse_critique(
        json.dumps(
            {
                "objections": [objection],
                "alternative_mechanisms": [],
                "falsifier_challenges": challenges or [],
            }
        ),
        targets=list(LIVE_IDS),
        shown_attestation_ids=["att:7a", "att:7b"],
        hypothesis_refs=hyp,
        evidence_refs=ev,
    )


def _objection(**overrides: Any) -> dict[str, Any]:
    return {
        "target_id": "H1",
        "kind": "COUNTEREXAMPLE",
        "severity": "CONTRADICTS",
        "text": "E2 says otherwise",
        "evidence_attestation_ids": ["E2"],
        **overrides,
    }


def test_the_critic_targets_and_cites_by_alias_and_the_draft_carries_canonical_ids():
    draft = _critique(_objection(), [{"target_id": "H2", "text": "the falsifier is untestable"}])
    (objection,) = draft.objections
    assert objection.target_id == LIVE_IDS[0] and objection.evidence_attestation_ids == ("att:7b",)
    assert draft.falsifier_challenges[0].target_id == LIVE_IDS[1]


@pytest.mark.parametrize(
    ("objection", "why"),
    [
        (_objection(target_id="hyp:9a8257a7"), "not under consideration"),
        (_objection(target_id="H9"), "not under consideration"),
        (_objection(evidence_attestation_ids=["E3"]), "which it was not shown"),
        (_objection(evidence_attestation_ids=["att:7"]), "which it was not shown"),
        (_objection(evidence_attestation_ids=["E1", "att:7a"]), "already listed"),
        (_objection(kind="CONTRADICTS"), "is not a valid ObjectionKind"),
    ],
)
def test_a_critic_reference_that_names_nothing_it_was_shown_is_refused(objection, why):
    with pytest.raises(RoleOutputRefused, match=why):
        _critique(objection)


# -- the envelope -----------------------------------------------------------------------------


def test_only_a_whole_reply_code_fence_is_removed_and_the_json_is_untouched():
    body = '{"terms": ["a ```b``` c"]}'
    assert normalize_reply(f"```json\n{body}\n```") == (body, STRIPPED_CODE_FENCE)
    assert normalize_reply(f"﻿```\n{body}\n```\n") == (body, STRIPPED_CODE_FENCE)
    assert normalize_reply(f"  {body}  ") == (body, None)
    for not_an_envelope in (
        f"Here you go:\n```json\n{body}\n```",
        f"```json\n{body}\n```\nI hope this helps.",
        f"```json\n{body}",
        f"{body}\n```",
    ):
        text, repair = normalize_reply(not_an_envelope)
        assert repair is None and text == not_an_envelope.strip(), not_an_envelope


def test_the_second_live_runs_fenced_engine_reply_parses_after_the_repair_only():
    bindings = {
        "bench.level": OutcomeSpace(
            outcome_space_id="os:t.level",
            version="1.0.0",
            domain="t",
            action_type="MEASUREMENT",
            outcomes=("HIGH", "NOMINAL"),
        )
    }
    certificate = {
        "key": "h1",
        "statement": "s",
        "mechanism": "m1",
        "assumptions": [],
        "falsifier": "f",
        "falsifier_prediction_keys": ["f"],
        "confounders": [],
        "minimal_test_ref": "t",
        "predictions": [
            {
                "key": "f",
                "observable_ref": "bench.level",
                "outcome_space_id": "os:t.level",
                "outcome_space_version": "1.0.0",
                "expected_outcome": "NOMINAL",
                "relation_effect": "CONTRADICTS",
            }
        ],
    }
    reply = (
        "```json\n"
        + json.dumps(
            {
                "hypotheses": [certificate, {**certificate, "key": "h2", "mechanism": "m2"}],
                "position": {"mechanism_view": "v"},
            },
            indent=2,
        )
        + "\n```"
    )
    with pytest.raises(RoleOutputRefused, match="not JSON"):
        parse_hypothesis_engine(reply, bindings=bindings, minimum=2)
    text, repair = normalize_reply(reply)
    assert repair == STRIPPED_CODE_FENCE
    assert len(parse_hypothesis_engine(text, bindings=bindings, minimum=2)[0]) == 2


# -- the coverage review's parser ------------------------------------------------------------------

_SPACES = {
    sp.OBS_CONNECTIVITY: OutcomeSpace(
        outcome_space_id=sp.SPACE_CONNECTIVITY,
        version="1.0.0",
        domain="silicon_photonics",
        action_type="ANALYTICAL_RULE_CHECK",
        outcomes=("CONTINUOUS", "DISCONTINUOUS"),
    ),
    sp.OBS_NORMALIZATION: OutcomeSpace(
        outcome_space_id=sp.SPACE_NORMALIZATION,
        version="1.0.0",
        domain="silicon_photonics",
        action_type="ANALYTICAL_RULE_CHECK",
        outcomes=("AGREES", "DISAGREES"),
    ),
}


def _rival(mechanism: str, observable: str, supports: str, refutes: str, **extra: Any) -> dict:
    space = _SPACES[observable]
    return {
        "key": mechanism.replace(" ", "_"),
        "statement": f"{mechanism} explains it",
        "mechanism": mechanism,
        "assumptions": [],
        "falsifier": f"{observable} = {refutes}",
        "falsifier_prediction_keys": ["f"],
        "confounders": [],
        "minimal_test_ref": "inspection",
        "predictions": [
            {
                "key": "s",
                "observable_ref": observable,
                "outcome_space_id": space.outcome_space_id,
                "outcome_space_version": "1.0.0",
                "expected_outcome": supports,
                "relation_effect": "SUPPORTS",
            },
            {
                "key": "f",
                "observable_ref": observable,
                "outcome_space_id": space.outcome_space_id,
                "outcome_space_version": "1.0.0",
                "expected_outcome": refutes,
                "relation_effect": "CONTRADICTS",
            },
        ],
        "grounding_evidence_ids": ["E1"],
        **extra,
    }


def _review(reply: dict[str, Any], gaps: tuple[str, ...] = (sp.OBS_CONNECTIVITY,)) -> Any:
    return parse_coverage_review(
        json.dumps(reply),
        bindings=_SPACES,
        unaddressed=gaps,
        existing_mechanisms=["process contact resistance", "uncorrected extraction artefact"],
        evidence_refs=AliasTable("E").shown(["att:1", "att:2"]),
        shown_attestation_ids=["att:1", "att:2"],
    )


def test_a_rival_cannot_be_grounded_on_evidence_of_another_project_or_call():
    """Only what this review was shown resolves: an attestation of another project, named in
    full, is refused like an invented one -- and admission would re-check its project anyway."""
    for foreign in ("att:of-another-project", "att:1x", "E1 "):
        with pytest.raises(RoleOutputRefused, match="not under consideration"):
            _review(
                {
                    "hypotheses": [
                        _rival(
                            "access contact discontinuity",
                            sp.OBS_CONNECTIVITY,
                            "DISCONTINUOUS",
                            "CONTINUOUS",
                            grounding_evidence_ids=[foreign],
                        )
                    ],
                    "declined": [],
                }
            )


def test_a_coverage_review_may_decline_every_check_with_a_reason():
    draft = _review(
        {
            "hypotheses": [],
            "declined": [
                {"observable_ref": sp.OBS_CONNECTIVITY, "reason": "no", "evidence_ids": ["E2"]}
            ],
        }
    )
    assert draft.proposals == () and draft.declined[0].evidence == ("att:2",)


def test_a_rival_certified_for_a_check_is_grounded_on_the_evidence_it_cites():
    draft = _review(
        {
            "hypotheses": [
                _rival(
                    "access contact discontinuity",
                    sp.OBS_CONNECTIVITY,
                    "DISCONTINUOUS",
                    "CONTINUOUS",
                    grounding_evidence_ids=["E2", "E1"],
                )
            ],
            "declined": [],
        }
    )
    (proposal,) = draft.proposals
    assert proposal.mechanism == "access contact discontinuity"
    assert draft.grounding[proposal.key] == ("att:2", "att:1")


@pytest.mark.parametrize(
    ("reply", "why"),
    [
        ({"hypotheses": [], "declined": []}, "unanswered"),
        (
            {
                "hypotheses": [
                    _rival(
                        "access contact discontinuity",
                        sp.OBS_CONNECTIVITY,
                        "DISCONTINUOUS",
                        "CONTINUOUS",
                        grounding_evidence_ids=[],
                    )
                ],
                "declined": [],
            },
            "cites no evidence",
        ),
        (
            {
                "hypotheses": [
                    _rival(
                        "access contact discontinuity",
                        sp.OBS_CONNECTIVITY,
                        "DISCONTINUOUS",
                        "CONTINUOUS",
                        grounding_evidence_ids=["E7"],
                    )
                ],
                "declined": [],
            },
            "not under consideration",
        ),
        (
            {
                "hypotheses": [
                    _rival(
                        "Process  Contact Resistance",
                        sp.OBS_CONNECTIVITY,
                        "DISCONTINUOUS",
                        "CONTINUOUS",
                    )
                ],
                "declined": [],
            },
            "already under consideration",
        ),
        (
            {
                "hypotheses": [
                    _rival("an off-topic rival", sp.OBS_NORMALIZATION, "DISAGREES", "AGREES")
                ],
                "declined": [{"observable_ref": sp.OBS_CONNECTIVITY, "reason": "r"}],
            },
            "no SUPPORTS or CONTRADICTS prediction over an unaddressed check",
        ),
        (
            {
                "hypotheses": [
                    _rival(
                        "access contact discontinuity",
                        sp.OBS_CONNECTIVITY,
                        "DISCONTINUOUS",
                        "CONTINUOUS",
                    )
                ],
                "declined": [{"observable_ref": sp.OBS_CONNECTIVITY, "reason": "r"}],
            },
            "twice",
        ),
        (
            {"hypotheses": [], "declined": [{"observable_ref": "sp.made_up", "reason": "r"}]},
            "not an unaddressed check",
        ),
        (
            {
                "hypotheses": [],
                "declined": [{"observable_ref": sp.OBS_CONNECTIVITY, "reason": " "}],
            },
            "reason is missing",
        ),
        (
            {
                "hypotheses": [
                    _rival(
                        "access contact discontinuity",
                        sp.OBS_CONNECTIVITY,
                        "DISCONTINUOUS",
                        "CONTINUOUS",
                        falsifier_prediction_keys=["s"],
                    )
                ],
                "declined": [],
            },
            "whose relation_effect is SUPPORTS",
        ),
    ],
)
def test_a_coverage_reply_outside_its_contract_is_refused(reply, why):
    with pytest.raises(RoleOutputRefused, match=why):
        _review(reply)


# -- the debate: retries, repairs, coverage ------------------------------------------------------


@dataclass
class Scripted:
    """The fixture's mock scientist, with chosen replies replaced -- `edits` are tried in order,
    and the first that returns text answers. Records every prompt."""

    base: MockScientist
    edits: list[Callable[[str, dict[str, Any], int], str | None]] = field(default_factory=list)
    seen: list[str] = field(default_factory=list)

    def __call__(self, material: str, slot: ModelSlot) -> str:
        self.seen.append(material)
        ctx = _context(material)
        for edit in self.edits:
            out = edit(material, ctx, len(self.seen))
            if out is not None:
                return out
        return self.base(material, slot)


def _scientist(*edits: Callable[[str, dict[str, Any], int], str | None]) -> Scripted:
    fx = load_fixture()
    return Scripted(
        MockScientist(
            mechanisms=fx["mechanisms"],
            primary_terms=fx["primary_terms"],
            outcome_space=fx["outcome_space"],
        ),
        list(edits),
    )


def _world(scientist: Scripted, **policy: Any) -> Any:
    return build_world(scientist=scientist, policy=DebatePolicy(**policy))  # type: ignore[arg-type]


def _specialist_once(reply: list[str], *, times: int) -> Callable[..., str | None]:
    """The first `times` specialist calls favour `reply`; later ones answer normally."""
    calls = {"n": 0}

    def edit(material: str, ctx: dict[str, Any], _: int) -> str | None:
        if "specialist" not in ctx:
            return None
        calls["n"] += 1
        if calls["n"] > times:
            return None
        return json.dumps({"mechanism_view": "v", "favoured_hypothesis_ids": reply})

    return edit


def test_a_shortened_id_is_asked_for_again_and_only_the_valid_reply_is_kept():
    scientist = _scientist(_specialist_once(LIVE_SHORTENED, times=1))
    world = _world(scientist, max_attempts=2)
    outcome = world.debate.run(world.request())
    attempts = outcome.record.reliability["reply_attempts"]
    refused = [a for a in attempts if a["outcome"] == "REFUSED"]
    assert len(refused) == 1 and "not under consideration" in refused[0]["detail"]
    retry = next(a for a in attempts if a["role"] == refused[0]["role"] and a["attempt"] == 2)
    assert retry["outcome"] == "ACCEPTED"
    # The refused reply is a durable inference, verbatim; the retry names it and says why.
    first = world.provenance.get(refused[0]["inference_id"])
    second = world.provenance.get(retry["inference_id"])
    assert first is not None and second is not None
    assert second.parameters["retry_of"] == refused[0]["inference_id"]
    assert second.parameters["attempt"] == 2 and first.parameters["attempt"] == 1
    asked = next(m for m in scientist.seen if "previous_reply_refused" in _context(m))
    assert "not under consideration" in _context(asked)["previous_reply_refused"]["reason"]
    # Every position records canonical hypothesis ids only.
    ids = {c.hypothesis_id for c in outcome.certificates}
    for position in outcome.positions:
        assert set(position.hypothesis_refs) <= ids


def test_a_reply_refused_on_every_attempt_builds_nothing_and_says_so():
    scientist = _scientist(_specialist_once(LIVE_SHORTENED, times=99))
    world = _world(scientist, max_attempts=2)
    with pytest.raises(RoleOutputRefused, match="refused on all 2 attempts"):
        world.debate.run(world.request())
    specialist_prompts = [m for m in scientist.seen if "specialist" in _context(m)]
    assert len(specialist_prompts) == 2, "two attempts, then the call is refused"


def test_one_attempt_is_the_default_and_refuses_as_before():
    scientist = _scientist(_specialist_once(LIVE_SHORTENED, times=1))
    world = _world(scientist)
    with pytest.raises(RoleOutputRefused, match="not under consideration") as refused:
        world.debate.run(world.request())
    assert "attempts" not in str(refused.value)


def test_a_fenced_reply_is_repaired_recorded_and_stored_verbatim():
    def fenced(material: str, ctx: dict[str, Any], _: int) -> str | None:
        if material.startswith("You are the Evidence Researcher") and ctx.get("mode") == "PRIMARY":
            return '```json\n{"terms": ["contact", "resistance"]}\n```'
        return None

    world = _world(_scientist(fenced), max_attempts=2)
    outcome = world.debate.run(world.request())
    (first, *_) = outcome.record.reliability["reply_attempts"]
    assert first["repair"] == STRIPPED_CODE_FENCE and first["outcome"] == "ACCEPTED"
    stored = world.provenance.get(first["inference_id"])
    assert stored is not None
    text = next(
        c.inference.text for c in outcome.calls if c.inference.inference_id == first["inference_id"]
    )
    assert text.startswith("```json"), "the reply is recorded as the model wrote it"


def test_specialists_and_critic_are_shown_aliases_and_the_same_hypothesis_keeps_its_alias():
    scientist = _scientist()
    world = _world(scientist)
    world.debate.run(world.request())
    role_contexts = [
        _context(m)
        for m in scientist.seen
        if "specialist" in _context(m) or m.startswith("You are the Adversarial Critic")
    ]
    assert role_contexts
    by_alias: dict[str, str] = {}
    for ctx in role_contexts:
        assert "hyp:" not in json.dumps(ctx) and "att:" not in json.dumps(ctx)
        for h in ctx["hypotheses"]:
            assert re.fullmatch(r"H[0-9]+", h["hypothesis_id"])
            assert by_alias.setdefault(h["hypothesis_id"], h["mechanism"]) == h["mechanism"]
        for e in ctx["evidence"]:
            assert re.fullmatch(r"E[0-9]+", e["attestation_id"])


# -- the coverage review in a debate ------------------------------------------------------------


#: Two rivals over the impedance and the normalization -- none says anything about connectivity,
#: as the live run's five did not.
def _engine_without_connectivity(material: str, ctx: dict[str, Any], _: int) -> str | None:
    if not material.startswith("You are the Hypothesis Engine. From ONLY"):
        return None
    imp = ("sp.small_signal_impedance", "os:sp.rs_bias_response", "1.0.0")

    def pred(key: str, where: tuple[str, str, str], outcome: str, effect: str) -> dict:
        return {
            "key": key,
            "observable_ref": where[0],
            "outcome_space_id": where[1],
            "outcome_space_version": where[2],
            "expected_outcome": outcome,
            "relation_effect": effect,
        }

    norm = (sp.OBS_NORMALIZATION, sp.SPACE_NORMALIZATION, "1.0.0")
    rivals = [
        (
            "process contact resistance",
            [
                pred("s", imp, "RS_BIAS_INSENSITIVE", "SUPPORTS"),
                pred("f", imp, "RS_FALLS_WITH_REVERSE_BIAS", "CONTRADICTS"),
            ],
        ),
        (
            "uncorrected extraction artefact",
            [pred("s", norm, "DISAGREES", "SUPPORTS"), pred("f", norm, "AGREES", "CONTRADICTS")],
        ),
    ]
    return json.dumps(
        {
            "hypotheses": [
                {
                    "key": m.replace(" ", "_"),
                    "statement": m,
                    "mechanism": m,
                    "assumptions": ["the splits differ"],
                    "falsifier": "f",
                    "falsifier_prediction_keys": ["f"],
                    "confounders": ["probe contact"],
                    "minimal_test_ref": "t",
                    "predictions": p,
                }
                for m, p in rivals
            ],
            "position": {"mechanism_view": "contact resistance"},
        }
    )


def _coverage(reply: Callable[[dict[str, Any]], dict[str, Any]]) -> Callable[..., str | None]:
    def edit(material: str, ctx: dict[str, Any], _: int) -> str | None:
        if material.startswith("You are the Hypothesis Engine, reviewing the coverage"):
            return json.dumps(reply(ctx))
        return None

    return edit


def _certify(ctx: dict[str, Any]) -> dict[str, Any]:
    space = sp.SPACE_CONNECTIVITY
    return {
        "hypotheses": [
            {
                "key": "c1",
                "statement": "the access contact is open",
                "mechanism": "access contact discontinuity",
                "assumptions": ["a via is open"],
                "falsifier": "connected",
                "falsifier_prediction_keys": ["f"],
                "confounders": ["probe contact"],
                "minimal_test_ref": "cap:sp.inspect_contact_connectivity",
                "predictions": [
                    {
                        "key": "s",
                        "observable_ref": sp.OBS_CONNECTIVITY,
                        "outcome_space_id": space,
                        "outcome_space_version": "1.0.0",
                        "expected_outcome": "DISCONTINUOUS",
                        "relation_effect": "SUPPORTS",
                    },
                    {
                        "key": "f",
                        "observable_ref": sp.OBS_CONNECTIVITY,
                        "outcome_space_id": space,
                        "outcome_space_version": "1.0.0",
                        "expected_outcome": "CONTINUOUS",
                        "relation_effect": "CONTRADICTS",
                    },
                ],
                "grounding_evidence_ids": [ctx["evidence"][0]["attestation_id"]],
            }
        ],
        "declined": [],
    }


def test_the_review_is_asked_only_about_cheap_checks_no_rival_addresses():
    scientist = _scientist(
        _engine_without_connectivity,
        _coverage(
            lambda ctx: {
                "hypotheses": [],
                "declined": [
                    {"observable_ref": c["observable_ref"], "reason": "nothing points there"}
                    for c in ctx["unaddressed_checks"]
                ],
            }
        ),
    )
    world = _world(scientist, coverage_review=True)
    outcome = world.debate.run(world.request())
    asked = [m for m in scientist.seen if "unaddressed_checks" in _context(m)]
    assert len(asked) == 1
    checks = _context(asked[0])["unaddressed_checks"]
    # Normalization is addressed (a rival SUPPORTS/CONTRADICTS on it); simulations need a seat.
    assert [c["observable_ref"] for c in checks] == [sp.OBS_CONNECTIVITY]
    assert checks[0]["check"] == sp.CAP_INSPECT_CONNECTIVITY
    coverage = outcome.record.reliability["coverage_review"]
    assert coverage["status"] == "DONE" and coverage["declined"][0]["reason"]
    assert len(outcome.certificates) == 2, "a declined check adds no rival"


def test_a_certified_rival_is_admitted_on_its_grounds_and_every_later_role_sees_it():
    scientist = _scientist(_engine_without_connectivity, _coverage(_certify))
    world = _world(scientist, coverage_review=True)
    outcome = world.debate.run(world.request())
    added = [
        c for c in outcome.certificates if c.hypothesis.mechanism == "access contact discontinuity"
    ]
    assert len(added) == 1
    assert added[0].hypothesis_id in outcome.record.initial_hypothesis_ids
    assert not outcome.record.critic_changed_final_set, "the Critic did not add it"
    coverage = outcome.record.reliability["coverage_review"]
    assert coverage["certified"][0]["addresses"] == [sp.OBS_CONNECTIVITY]
    assert coverage["certified"][0]["grounding"], "admitted on the evidence it cited"
    for m in scientist.seen:
        ctx = _context(m)
        if "specialist" in ctx or m.startswith("You are the Adversarial Critic"):
            assert "access contact discontinuity" in {h["mechanism"] for h in ctx["hypotheses"]}


def test_a_review_that_cannot_be_completed_leaves_the_stage_a_set_and_records_why():
    scientist = _scientist(
        _engine_without_connectivity, _coverage(lambda ctx: {"hypotheses": "none"})
    )
    world = _world(scientist, coverage_review=True, max_attempts=2)
    outcome = world.debate.run(world.request())
    coverage = outcome.record.reliability["coverage_review"]
    assert coverage["status"] == "FAILED" and "refused on all 2 attempts" in coverage["detail"]
    assert len(outcome.certificates) == 2


def test_the_unaddressed_checks_depend_on_the_rivals_and_the_capabilities_never_on_an_answer():
    """The gap is a function of (hypotheses, vocabulary, capability descriptors, input KINDS)
    and nothing else: no device content, case, catalog or expected outcome is a parameter."""
    import inspect

    assert list(inspect.signature(unaddressed_checks).parameters) == [
        "certificates",
        "bindings",
        "capabilities",
        "available",
    ]
    scientist = _scientist(_engine_without_connectivity, _coverage(_certify))
    contexts = []
    for case in load_fixture()["cases"][:4]:  # cases whose true mechanism differs
        world = build_world(case, scientist=scientist, policy=DebatePolicy(coverage_review=True))
        scientist.seen.clear()
        world.debate.run(world.request(case))
        (asked,) = [m for m in scientist.seen if "unaddressed_checks" in _context(m)]
        contexts.append(_context(asked)["unaddressed_checks"])
    assert all(c == contexts[0] for c in contexts)
    # Without the device project nothing is executable, so nothing is unaddressed-but-cheap.
    world = _world(_scientist(_engine_without_connectivity), coverage_review=True)
    outcome = world.debate.run(world.request(available_inputs=frozenset()))
    assert outcome.record.reliability["coverage_review"]["status"] == "NOT_NEEDED"
    assert INPUT_DEVICE_PROJECT  # the kind the planner needs; its CONTENT is never read here


def test_a_report_reads_aliases_back_and_leaves_the_rest_as_written():
    from lab_brain.research.service import _dealias

    shown = {"H1": "hyp:a", "E2": "att:b"}
    said = "H1 ignores E2; H9, E7 and H10x stay"
    assert _dealias(said, shown, {"hyp:a": "contact discontinuity"}) == (
        "H1 [contact discontinuity] ignores E2 [att:b]; H9, E7 and H10x stay"
    )
