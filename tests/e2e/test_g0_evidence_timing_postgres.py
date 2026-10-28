"""Prospective evidence is judged by when the evidence came to be, not when its row was written.

012y (b) refused an observation RECORDED before the post-screening hypothesis. Recording time is
the database's clock, not science's: data older than the hypothesis can be written today. On a
real screened episode (open via, conditioned rival), each case below is a basis whose evidence
existed -- or was read from evidence that existed -- before the hypothesis was proposed:

    late-recorded run        the run STARTED before the hypothesis; its observation is written now
    old captured data        a new run whose output says its data was CAPTURED years ago
    re-read screened output  a new run of another check whose INPUT is the screened output itself
    evidence lookup          a run of a capability whose kind is to look up existing evidence

DEMONSTRATED on 011o (`evidence/evidence-timing-before-011p.txt`): every case was accepted as
SUPPORT for the post-screening hypothesis. 011p judges the basis by run start, data capture time,
derivation from conditioned outputs, and the capability's kind.

RETROSPECTIVE EVIDENCE IS KEPT, NOT UPGRADED. The same old evidence may still be RECORDED against
the hypothesis as context (a CITES relation) -- it is real evidence of what was already known --
and may still SUPPORT a hypothesis formed before screening, exactly as before. It is only refused
as prospective SUPPORT of a hypothesis its author formed after seeing the screening reading.
"""

from __future__ import annotations

import datetime as dt

import pytest

from lab_brain.domains.silicon_photonics import vertical as sp
from tests.e2e.test_g0_exploratory_screening_postgres import rows
from tests.e2e.test_g0_screening_independence_postgres import _refused
from tests.e2e.test_g0_screening_independence_postgres import guarded as guarded
from tests.e2e.test_g0_screening_independence_postgres import standin as standin
from tests.e2e.test_research_episode_postgres import PROJECT

pytestmark = pytest.mark.postgres

OLD = dt.datetime(2020, 1, 1, tzinfo=dt.UTC)
#: Each case is refused for its own TIME reason, not because the check is unregistered: every
#: case registers the vertical's capabilities first.
RETRO = "retrospective|derived from evidence that already existed|reads existing evidence"


def test_a_run_that_started_before_the_hypothesis_is_not_prospective(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        g.register_capabilities()
        run = g.run(
            "late-recorded",
            input_parameters={"variant": "late"},
            output_artifacts=(g.fresh_output("late-recorded"),),
            job_at=OLD,
        )
        observation = g.observe(run, "late-recorded")
        _refused(g, observation, RETRO, cites=[g.attest(observation, run)])


def test_a_new_run_of_old_captured_data_is_not_prospective(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        g.register_capabilities()
        run = g.run(
            "old-capture",
            input_parameters={"variant": "old-capture"},
            output_artifacts=(g.fresh_output("old-capture", captured_at=OLD),),
        )
        observation = g.observe(run, "old-capture")
        _refused(g, observation, RETRO, cites=[g.attest(observation, run)])


def test_a_new_check_that_reads_the_screened_output_is_not_independent(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        g.register_capabilities()
        run = g.run(
            "re-read",
            capability_id=sp.CAP_EXTRACTION_CONSISTENCY,
            backend_id="sp.local.normalization_basis_reader",
            input_artifacts=tuple(g.screened.output_artifacts),
            input_parameters={"variant": "re-read"},
            output_artifacts=(g.fresh_output("re-read"),),
        )
        observation = g.observe(run, "re-read")
        _refused(g, observation, RETRO, cites=[g.attest(observation, run)])


def test_an_evidence_lookup_is_not_new_verification(guarded):
    g = guarded
    capability = "cap:sp.lookup_prior_measurements"
    with g.db.transaction(force_rollback=True):
        g.register_capabilities()
        g.db.execute(
            "INSERT INTO capabilities (capability_id, domain, version, action_type, backend_id,"
            " requires, produces, authority_class, estimate_cost_contract)"
            " SELECT %s, domain, version, 'EXISTING_EVIDENCE_LOOKUP', 'sp.lookup', requires,"
            " produces, authority_class, estimate_cost_contract FROM capabilities"
            " WHERE capability_id = %s",
            (capability, g.screened.capability_id),
        )
        run = g.run(
            "lookup",
            capability_id=capability,
            backend_id="sp.lookup",
            input_parameters={"variant": "lookup"},
            output_artifacts=(g.fresh_output("lookup"),),
        )
        observation = g.observe(run, "lookup")
        _refused(g, observation, RETRO, cites=[g.attest(observation, run)])


def test_retrospective_evidence_is_kept_as_context_not_support(guarded):
    """The old evidence is recorded against the rival (CITES), and is not counted as support."""
    g = guarded
    with g.db.transaction(force_rollback=True):
        run = g.run(
            "context",
            input_parameters={"variant": "context"},
            output_artifacts=(g.fresh_output("context", captured_at=OLD),),
        )
        observation = g.observe(run, "context")
        evidence = g.attest(observation, run)
        g.db.execute(
            "INSERT INTO relation_judgments (relation_id, from_entity_id, to_entity_id,"
            " relation_type, supporting_attestation_ids, project_id)"
            " VALUES (%s, %s, %s, 'CITES', %s, %s)",
            (f"rel:cites-{observation}", observation, g.hypothesis, [evidence], PROJECT),
        )
        assert not rows(
            g.db,
            "SELECT 1 FROM relation_judgments WHERE to_entity_id = %s AND relation_type = 'SUPPORTS'",
            g.hypothesis,
        )


def test_a_genuinely_new_check_after_the_hypothesis_still_supports(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        run = g.run(
            "new",
            input_parameters={"variant": "new"},
            output_artifacts=(g.fresh_output("new"),),
        )
        observation = g.observe(run, "new")
        g.register_capabilities()
        g.support(observation, [g.attest(observation, run)])


def test_a_check_of_no_registered_kind_cannot_support(guarded):
    """Fail closed: the research flow persists no capability, so its kind is unknown -- and a
    check of unknown kind may be a lookup of what already exists."""
    g = guarded
    assert not rows(
        g.db, "SELECT 1 FROM capabilities WHERE capability_id = %s", g.screened.capability_id
    )
    with g.db.transaction(force_rollback=True):
        run = g.run(
            "unregistered",
            input_parameters={"variant": "unregistered"},
            output_artifacts=(g.fresh_output("unregistered"),),
        )
        observation = g.observe(run, "unregistered")
        _refused(g, observation, "not registered with a kind", cites=[g.attest(observation, run)])
