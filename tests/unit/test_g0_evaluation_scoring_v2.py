"""Scorer 2.0.0: the Independent Chief Auditor's findings, each as a case scorer 1.0.0 got wrong.

ALL DATA HERE IS SYNTHETIC. The records are hand-built in the collector's shape.

    prospective support   a post-screening hypothesis supported by a later, independent reading,
                          and confirmed on it, is not a failure; the same hypothesis supported by
                          any inadmissible basis is
    discovery split       a cause named only after screening is `considered_with_screening`, not
                          `considered_pre_screening`, and is counted as a screening discovery
    correct answer        a run that states the true cause in its OUTPUT has not leaked; truth in
                          its INPUTS has, and so has a case id or a long evaluator text in its output
    malformed output      every unreadable shape is MALFORMED with a reason -- the scorer never raises
(`docs/audit/g0-reliability-bilingual-closure-2026-10-28/evidence/scorer-1.0.0-defects.txt` is the
same four cases on 1.0.0.)
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from lab_brain.evaluation import scoring

CASE = "syn-a"
OBS = {"contact_discontinuity": "sp.contact_connectivity"}
RATIONALE = "the drawn via never reaches the metal layer so the contact is electrically open"
TRUTH = {
    CASE: {
        "true_causes": ["contact_discontinuity"],
        "decisive_cheap_checks": ["cap:x"],
        "expected_abnormal_observables": ["sp.contact_connectivity"],
        "rationale": RATIONALE,
    }
}
ADMISSIBLE = dict.fromkeys(scoring.SUPPORT_FACTS, False)


def support(**facts: bool) -> dict[str, Any]:
    return {"relation_id": f"rel:{len(facts)}", **ADMISSIBLE, **facts}


def hypothesis(hid: str, origin: str, *observables: str, supports: Any = ()) -> dict[str, Any]:
    return {
        "hypothesis_id": hid,
        "origin": origin,
        "discriminates_on": list(observables),
        "refutable_on": list(observables),
        "supports": list(supports),
    }


def record(*hypotheses: dict[str, Any], **changes: Any) -> dict[str, Any]:
    base = {
        "hypotheses": list(hypotheses),
        "screening_executed": ["cap:x"],
        "verification_executed": [],
        "readings": [{"observable": "sp.contact_connectivity", "finding": "ABNORMAL"}],
        "confirmed": None,
        "conclusion_statement": "",
        "prompts": ["QUESTION: why is Rs high?"],
    }
    base.update(changes)
    return base


def score(rec: Any, *, status: str = "COMPLETED") -> dict[str, Any]:
    (row,) = scoring.score_cases(
        cases=[CASE],
        outputs={CASE: {"status": status, "record": rec}},
        truth=TRUTH,
        unavailable={CASE: []},
        observable_of=OBS,
        answers=["contact_discontinuity"],
        secrets=[RATIONALE],
        exclusions={},
    )
    return row


POST = "POST_SCREENING"
PRE = "PRE_OBSERVATION"


def test_a_prospective_support_and_its_confirmation_are_not_failures():
    row = score(
        record(
            hypothesis("h2", POST, "sp.contact_connectivity", supports=[support()]),
            confirmed="h2",
        )
    )
    assert row["status"] == "COMPLETED"
    m = row["metrics"]
    assert m["no_inadmissible_post_screening_support"] and m["no_false_confirmation"], m


@pytest.mark.parametrize("fact", scoring.SUPPORT_FACTS)
def test_every_inadmissible_basis_still_fails(fact):
    row = score(
        record(
            hypothesis("h2", POST, "sp.contact_connectivity", supports=[support(**{fact: True})]),
            confirmed="h2",
        )
    )
    m = row["metrics"]
    assert not m["no_inadmissible_post_screening_support"], fact
    assert not m["no_false_confirmation"], "confirmed on nothing admissible"


def test_an_unsupported_post_screening_confirmation_is_false_and_a_pre_one_is_judged_on_cause():
    assert not score(record(hypothesis("h2", POST, "sp.contact_connectivity"), confirmed="h2"))[
        "metrics"
    ]["no_false_confirmation"]
    pre_right = record(hypothesis("h1", PRE, "sp.contact_connectivity"), confirmed="h1")
    pre_wrong = record(hypothesis("h1", PRE, "sp.normalization_basis"), confirmed="h1")
    assert score(pre_right)["metrics"]["no_false_confirmation"]
    assert not score(pre_wrong)["metrics"]["no_false_confirmation"]


def test_supports_of_a_pre_observation_hypothesis_are_not_this_metrics_business():
    row = score(
        record(
            hypothesis(
                "h1", PRE, "sp.contact_connectivity", supports=[support(screened_observation=True)]
            )
        )
    )
    assert row["metrics"]["no_inadmissible_post_screening_support"]


def test_a_cause_named_only_after_screening_is_screenings_discovery():
    row = score(
        record(
            hypothesis("h1", PRE, "sp.normalization_basis"),
            hypothesis("h2", POST, "sp.contact_connectivity"),
        )
    )
    m = row["metrics"]
    assert m["considered_with_screening"] and not m["considered_pre_screening"]
    assert row["screening_discovery"] is True
    both = score(
        record(
            hypothesis("h1", PRE, "sp.contact_connectivity"),
            hypothesis("h2", POST, "sp.contact_connectivity"),
        )
    )
    assert both["metrics"]["considered_pre_screening"] and both["screening_discovery"] is False


def test_the_summary_counts_screening_discoveries_apart():
    rows = [
        score(record(hypothesis("h2", POST, "sp.contact_connectivity"))),
        score(record(hypothesis("h1", PRE, "sp.contact_connectivity"))),
    ]
    summary = scoring.summarize(rows, seed=1, resamples=50)
    assert summary["screening_discoveries"] == 1
    assert summary["metrics"]["considered_pre_screening"]["k"] == 1
    assert summary["metrics"]["considered_with_screening"]["k"] == 2


def test_stating_the_right_answer_is_not_a_leak():
    row = score(
        record(
            hypothesis("h1", PRE, "sp.contact_connectivity"),
            conclusion_statement="Most likely cause: contact_discontinuity -- the via is open.",
        )
    )
    assert row["metrics"]["no_input_leak"] and row["metrics"]["no_secret_in_output"], row


@pytest.mark.parametrize(
    ("changes", "metric"),
    [
        ({"prompts": ["CONTEXT: suspect contact_discontinuity first"]}, "no_input_leak"),
        ({"prompts": ["CONTEXT: " + RATIONALE]}, "no_input_leak"),
        ({"prompts": [f"case {CASE}"]}, "no_input_leak"),
        ({"conclusion_statement": f"As in case {CASE}, the via is open."}, "no_secret_in_output"),
        ({"conclusion_statement": RATIONALE.upper()}, "no_secret_in_output"),
    ],
)
def test_truth_in_the_inputs_or_a_secret_in_the_output_is_a_leak(changes, metric):
    row = score(record(hypothesis("h1", PRE, "sp.contact_connectivity"), **changes))
    assert row["status"] == "COMPLETED" and not row["metrics"][metric], row


def test_a_short_rationale_said_again_by_a_correct_conclusion_is_not_a_leak():
    short = "the via is open"
    (row,) = scoring.score_cases(
        cases=[CASE],
        outputs={
            CASE: {
                "status": "COMPLETED",
                "record": record(
                    hypothesis("h1", PRE, "sp.contact_connectivity"),
                    conclusion_statement="Conclusion: the via is open.",
                ),
            }
        },
        truth={CASE: {**TRUTH[CASE], "rationale": short}},
        unavailable={CASE: []},
        observable_of=OBS,
        answers=["contact_discontinuity"],
        secrets=[short],
        exclusions={},
    )
    assert row["metrics"]["no_secret_in_output"]
    # ... but in the inputs the same words are a leak, whatever their length.
    leaked = scoring.leak_counts(
        record(prompts=[f"HINT: {short}"]), answers=[], secrets=[short], case_ids=[CASE]
    )
    assert leaked == (1, 0)


def _good() -> dict[str, Any]:
    return record(hypothesis("h1", PRE, "sp.contact_connectivity", supports=[support()]))


def _broken(path: str, value: Any) -> dict[str, Any]:
    rec = copy.deepcopy(_good())
    target: Any = rec
    *parents, last = path.split(".")
    for part in parents:
        target = target[int(part)] if part.isdigit() else target[part]
    if value is KeyError:
        del target[int(last) if last.isdigit() else last]
    elif last.isdigit():
        target[int(last)] = value
    else:
        target[last] = value
    return rec


MALFORMED = {
    "not an object": (["a list"], "not an object"),
    "no hypotheses": (_broken("hypotheses", KeyError), "lacks `hypotheses`"),
    "no prompts": (_broken("prompts", KeyError), "lacks `prompts`"),
    "hypotheses not a list": (_broken("hypotheses", {"h1": 1}), "is not a list"),
    "hypothesis not an object": (_broken("hypotheses.0", "h1"), "is not an object"),
    "no discriminates_on": (_broken("hypotheses.0.discriminates_on", KeyError), "discriminates_on"),
    "discriminates_on wrong type": (
        _broken("hypotheses.0.discriminates_on", "sp.x"),
        "discriminates_on",
    ),
    "unknown origin": (_broken("hypotheses.0.origin", "LATER"), "origin"),
    "legacy bare count": (_broken("hypotheses.0.supports", 1), "must list each relation"),
    "support without facts": (
        _broken("hypotheses.0.supports", [{"relation_id": "r"}]),
        "lacks provenance",
    ),
    "support fact not a bool": (
        _broken("hypotheses.0.supports", [{**support(), "screened_observation": "no"}]),
        "lacks provenance",
    ),
    "duplicate hypothesis": (
        record(hypothesis("h1", PRE, "sp.x"), hypothesis("h1", POST, "sp.y")),
        "recorded twice",
    ),
    "confirmed unknown": (_broken("confirmed", "h9"), "not a recorded hypothesis"),
    "confirmed wrong type": (_broken("confirmed", 3), "not a recorded hypothesis"),
    "reading without observable": (_broken("readings.0", {"finding": "ABNORMAL"}), "observable"),
    "unknown finding": (_broken("readings.0.finding", "WEIRD"), "finding"),
    "executed not strings": (_broken("screening_executed", [1, 2]), "list of strings"),
    "statement not a string": (_broken("conclusion_statement", ["x"]), "conclusion_statement"),
}


@pytest.mark.parametrize("name", sorted(MALFORMED))
def test_every_malformed_shape_is_scored_malformed_never_raised(name):
    rec, why = MALFORMED[name]
    row = score(rec)
    assert row["status"] == "MALFORMED" and why in row["reason"], row
    # A malformed case fails every metric that applies; it never vanishes from the denominator.
    assert row["metrics"] and not any(row["metrics"].values())


def test_an_entry_that_is_not_an_object_or_has_an_unknown_status_is_malformed():
    (row,) = scoring.score_cases(
        cases=[CASE],
        outputs={CASE: ["not", "an", "entry"]},
        truth=TRUTH,
        unavailable={CASE: []},
        observable_of=OBS,
        answers=[],
        secrets=[],
        exclusions={},
    )
    assert row["status"] == "MALFORMED"
    assert score(_good(), status="PASSED")["status"] == "MALFORMED"


def test_two_competing_hypotheses_before_screening_and_refutability():
    one = score(record(hypothesis("h1", PRE, "sp.contact_connectivity")))["metrics"]
    assert not one["competing_pre_screening"]
    two = score(
        record(
            hypothesis("h1", PRE, "sp.contact_connectivity"),
            hypothesis("h2", PRE, "sp.normalization_basis"),
        )
    )["metrics"]
    assert two["competing_pre_screening"] and two["refutable"]
    # A second hypothesis on the SAME observables is not a competitor; a post-screening one does
    # not count either.
    same = score(
        record(
            hypothesis("h1", PRE, "sp.contact_connectivity"),
            hypothesis("h2", PRE, "sp.contact_connectivity"),
            hypothesis("h3", POST, "sp.normalization_basis"),
        )
    )["metrics"]
    assert not same["competing_pre_screening"]
    unrefutable = hypothesis("h1", PRE, "sp.contact_connectivity")
    unrefutable["refutable_on"] = []
    assert not score(record(unrefutable))["metrics"]["refutable"]
    assert not score(record())["metrics"]["refutable"], "no hypothesis is not refutable"
