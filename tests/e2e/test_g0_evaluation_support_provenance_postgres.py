"""The evaluator's collector reads each support's basis from the canonical rows, not from a verdict.

On a real screened episode (open via, conditioned rival), through `matrix.collect` and
`lab_brain.evaluation.collect.support_provenance`:

    prospective     a later reading with new content, citing its own attestation: every fact is
                    false, and scorer 2.0.0 counts neither a failure nor a false confirmation
    inadmissible    rows the 011o guard refuses, written here with the guard switched OFF inside a
                    rolled-back transaction -- standing in for a guard that failed or a database
                    edited by hand. The collector still reports each basis, so the score never rests
                    on the guard having held:
                        the screened observation itself          screened_observation
                        the screened attestation as the source   unobserved_basis
                        a fresh observation citing a repeat      repeats_screened_check
                        an observation older than the rival      observed_before_hypothesis
                        the screened output bytes                shares_screened_output
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from typing import Any

import pytest

from lab_brain.evaluation import scoring
from lab_brain.evaluation.collect import support_provenance
from tests.e2e.test_g0_screening_independence_postgres import Guarded, _fresh
from tests.e2e.test_g0_screening_independence_postgres import guarded as guarded
from tests.e2e.test_g0_screening_independence_postgres import standin as standin
from tests.e2e.test_g0_screening_matrix_postgres import collect

pytestmark = pytest.mark.postgres


def _post_screening(record: dict[str, Any], hypothesis: str) -> dict[str, Any]:
    (h,) = [x for x in record["hypotheses"] if x["hypothesis_id"] == hypothesis]
    assert h["origin"] == "POST_SCREENING"
    return h


def test_a_prospective_support_is_collected_admissible_and_scores_clean(guarded):
    g: Guarded = guarded
    with g.db.transaction(force_rollback=True):
        run, observation = _fresh(g, "prospective")
        g.support(observation, [g.attest(observation, run)])
        record = collect(g.db, g.episode)
        h = _post_screening(record, g.hypothesis)
        (entry,) = h["supports"]
        assert entry == {
            "relation_id": f"rel:{observation}",
            **dict.fromkeys(scoring.SUPPORT_FACTS, False),
        }
        assert scoring.record_problems({**record, "prompts": []}) is None
        assert all(scoring.admissible(s) for s in h["supports"])


@pytest.fixture
def unguarded(guarded: Guarded) -> Iterator[Guarded]:
    """The same episode with the screening guard switched off, inside a transaction that rolls back."""
    with guarded.db.transaction(force_rollback=True):
        guarded.db.execute(
            "ALTER TABLE relation_judgments DISABLE TRIGGER relation_judgments_screening_guard_trg"
        )
        yield guarded


def _only_fact(g: Guarded, relation_source: str) -> set[str]:
    h = _post_screening(collect(g.db, g.episode), g.hypothesis)
    (entry,) = [s for s in h["supports"] if s["relation_id"] == f"rel:{relation_source}"]
    return {f for f in scoring.SUPPORT_FACTS if entry[f]}


def test_the_screened_observation_is_collected_as_screened(unguarded):
    g = unguarded
    ((screened,),) = g.db.execute(
        "SELECT observation_id FROM attestations WHERE attestation_id = %s", (g.attestation,)
    ).fetchall()
    g.support(screened)
    assert "screened_observation" in _only_fact(g, screened)


def test_the_screened_attestation_as_source_is_an_unobserved_basis(unguarded):
    g = unguarded
    # A relation must cite an attestation (a CHECK); it cites the screened one, as such a relation
    # would. Both the non-observation source and the screened evidence are reported.
    g.support(g.attestation)
    assert _only_fact(g, g.attestation) >= {"unobserved_basis", "screened_observation"}


def test_a_fresh_observation_citing_a_repeat_is_collected_as_a_repeat(unguarded):
    g = unguarded
    _run, observation = _fresh(g, "fresh")
    repeat = g.run("repeat")
    borrowed = g.observe(repeat, "repeat")
    g.support(observation, [g.attest(borrowed, repeat)])
    facts = _only_fact(g, observation)
    assert "repeats_screened_check" in facts and "shares_screened_output" in facts, facts


def test_an_older_observation_is_collected_as_older(unguarded):
    g = unguarded
    run, observation = _fresh(g, "older")
    g.db.execute(
        "UPDATE observations SET created_at = %s WHERE observation_id = %s",
        (dt.datetime(2020, 1, 1, tzinfo=dt.UTC), observation),
    )
    g.support(observation, [g.attest(observation, run)])
    assert _only_fact(g, observation) == {"observed_before_hypothesis"}


def test_the_screened_bytes_under_another_capability_are_collected(unguarded):
    g = unguarded
    from tests.e2e.test_g0_screening_independence_postgres import SAME_BYTES

    g.register_capabilities()
    run = g.run("same-bytes", **SAME_BYTES["other_capability_same_output"](g))
    observation = g.observe(run, "same-bytes")
    g.support(observation, [g.attest(observation, run)])
    assert _only_fact(g, observation) == {"shares_screened_output"}


def test_support_provenance_is_read_only(guarded):
    g = guarded
    before = g.db.execute("SELECT count(*) FROM relation_judgments").fetchone()
    assert support_provenance(g.db, g.hypothesis) == []
    assert g.db.execute("SELECT count(*) FROM relation_judgments").fetchone() == before


def test_old_evidence_written_today_is_collected_as_retrospective(unguarded):
    """011p in the collector: a run that started before the rival, recorded now."""
    g = unguarded
    import datetime as _dt

    g.register_capabilities()
    old = _dt.datetime(2020, 1, 1, tzinfo=_dt.UTC)
    run = g.run(
        "late",
        job_at=old,
        input_parameters={"variant": "late"},
        output_artifacts=(g.fresh_output("late"),),
    )
    observation = g.observe(run, "late")
    g.support(observation, [g.attest(observation, run)])
    assert _only_fact(g, observation) == {"retrospective_basis"}
