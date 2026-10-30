"""The prospective-evidence loopholes 011p left open, each shown as a basis 011p ACCEPTED.

On a real screened episode (open via, conditioned rival), every case below offers SUPPORT to the
post-screening rival from a run that 011p judged prospective -- run started after the rival, no
artifact captured before it, no input read from an earlier run, a capability registered with a kind
that "produces new evidence" -- and yet its evidence is not a new, independent check:

    unknown capture time   an uploaded measurement export with no capture time, as the run's
                           output or as its input (011p skipped a NULL `captured_at`)
    lineage                an output DERIVED from a 2020 measurement; an input derived --
                           directly or through a chain -- from the screened output; a lineage
                           cycle; a lineage deeper than any record should be (011p read no
                           lineage at all)
    classification         a kind written into `capabilities` by the application (a lookup
                           registered as a MEASUREMENT); an UPDATE that reclassifies a registered
                           check; an ANALYTICAL_RULE_CHECK re-reading the same design file the
                           screened reading read (011p took any registered non-lookup kind)
    authorization          a genuinely new measurement nobody pre-registered as a test of the
                           rival (011p had no authorization at all)

DEMONSTRATED on 011r (011p in force): every case was accepted -- the test failed with "DID NOT
RAISE" (see docs/audit/g0-owner-boundary-closure-2026-10-28/prospective-evidence.md). 011s refuses
each for its own reason. The authorized, prospective, independent check -- and what stays allowed
(retrospective CITES, support of a pre-screening rival) -- is in
`test_g0_prospective_verification_postgres.py`.
"""

from __future__ import annotations

import datetime as dt

import psycopg
import pytest

from lab_brain.domains.silicon_photonics import diagnosis
from lab_brain.domains.silicon_photonics import vertical as sp
from tests.e2e.test_g0_screening_independence_postgres import Guarded, _refused
from tests.e2e.test_g0_screening_independence_postgres import guarded as guarded
from tests.e2e.test_g0_screening_independence_postgres import standin as standin

pytestmark = pytest.mark.postgres

OLD = dt.datetime(2020, 1, 1, tzinfo=dt.UTC)
DESIGN = diagnosis.DEVICE_PROJECT_MEDIA_TYPE


def _probe(g: Guarded, name: str, *, outputs: tuple[str, ...], **changes: object) -> str:
    """A four-point probe Run (a MEASUREMENT) after the rival, with the outputs given."""
    fields: dict[str, object] = {
        "capability_id": sp.CAP_FOURPOINT_PROBE,
        "backend_id": "lab.probe_station",
        "input_artifacts": (),
        "input_parameters": {"variant": name},
        "output_artifacts": outputs,
        **changes,
    }
    return g.run(name, **fields)


def _simulation(g: Guarded, name: str, *, inputs: tuple[str, ...]) -> str:
    """A DC-sweep simulation Run after the rival, reading `inputs`, with new output content."""
    return g.run(
        name,
        capability_id=sp.CAP_CHARGE_DC,
        backend_id="sp.charge.dc",
        input_artifacts=inputs,
        input_parameters={"variant": name},
        output_artifacts=(g.fresh_output(name),),
    )


def _offered(g: Guarded, run: str, name: str, why: str) -> None:
    observation = g.observe(run, name)
    _refused(g, observation, why, cites=[g.attest(observation, run)])


# -- 1. unknown capture time ------------------------------------------------------------------


def test_a_measurement_export_with_no_capture_time_is_not_prospective(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        g.register_capabilities()
        run = _probe(g, "no-capture", outputs=(g.artifact("probe export, no capture time"),))
        _offered(g, run, "no-capture", "capture time is unknown")


def test_an_input_measurement_with_no_capture_time_is_not_prospective(guarded):
    g = guarded
    (design,) = g.screened.input_artifacts
    with g.db.transaction(force_rollback=True):
        g.register_capabilities()
        export = g.artifact("an older sweep, imported, no capture time")
        run = _simulation(g, "input-no-capture", inputs=(design, export))
        _offered(g, run, "input-no-capture", "capture time is unknown")


# -- 2. lineage -------------------------------------------------------------------------------


def test_an_output_derived_from_old_data_is_not_prospective(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        g.register_capabilities()
        old = g.artifact("the 2020 probe log", captured_at=OLD)
        derived = g.artifact("re-processed today", captured_at=g.later, derived_from=(old,))
        run = _probe(g, "derived-old", outputs=(derived,))
        _offered(g, run, "derived-old", "lineage")


def test_an_input_derived_from_the_screened_output_is_not_independent(guarded):
    g = guarded
    (screened,) = g.screened.output_artifacts
    with g.db.transaction(force_rollback=True):
        g.register_capabilities()
        copy = g.artifact(
            "a design re-exported from the reading", media_type=DESIGN, derived_from=(screened,)
        )
        run = _simulation(g, "derived-screened", inputs=(copy,))
        _offered(g, run, "derived-screened", "lineage")


def test_lineage_is_walked_transitively(guarded):
    g = guarded
    (screened,) = g.screened.output_artifacts
    with g.db.transaction(force_rollback=True):
        g.register_capabilities()
        first = g.artifact("hop 1", media_type=DESIGN, derived_from=(screened,))
        second = g.artifact("hop 2", media_type=DESIGN, derived_from=(first,))
        third = g.artifact("hop 3", media_type=DESIGN, derived_from=(second,))
        run = _simulation(g, "transitive", inputs=(third,))
        _offered(g, run, "transitive", "lineage")


def test_a_lineage_cycle_fails_closed(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        g.register_capabilities()
        # Each names the other: the array has no foreign key, so the cycle can be written.
        ahead = "art:sha256:" + __import__("hashlib").sha256(b"artifact cycle b").hexdigest()
        first = g.artifact("cycle a", captured_at=g.later, derived_from=(ahead,))
        second = g.artifact("cycle b", captured_at=g.later, derived_from=(first,))
        assert second == ahead
        run = _probe(g, "cycle", outputs=(first,))
        _offered(g, run, "cycle", "lineage")


def test_a_lineage_deeper_than_the_bound_fails_closed(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        g.register_capabilities()
        link = g.artifact("depth 0", captured_at=g.later)
        for depth in range(1, 40):
            link = g.artifact(f"depth {depth}", captured_at=g.later, derived_from=(link,))
        run = _probe(g, "deep", outputs=(link,))
        _offered(g, run, "deep", "lineage")


# -- 3. capability classification -------------------------------------------------------------


def test_a_kind_the_application_wrote_is_not_a_declaration(guarded):
    """A lookup of prior measurements, inserted into `capabilities` as a MEASUREMENT."""
    g = guarded
    capability = "cap:sp.lookup_prior_measurements"
    with g.db.transaction(force_rollback=True):
        g.register_capabilities()
        g.db.execute(
            "INSERT INTO capabilities (capability_id, domain, version, action_type, backend_id,"
            " requires, produces, authority_class, estimate_cost_contract)"
            " SELECT %s, domain, version, 'MEASUREMENT', 'sp.lookup', requires, produces,"
            " authority_class, estimate_cost_contract FROM capabilities WHERE capability_id = %s",
            (capability, sp.CAP_FOURPOINT_PROBE),
        )
        run = _probe(
            g,
            "app-kind",
            capability_id=capability,
            backend_id="sp.lookup",
            outputs=(g.artifact("looked up", captured_at=g.later),),
        )
        _offered(g, run, "app-kind", "not declared")


def test_a_registered_kind_cannot_be_rewritten(guarded):
    g = guarded
    with g.db.transaction(force_rollback=True):
        g.register_capabilities()
        with (
            pytest.raises(psycopg.errors.RaiseException, match="declared"),
            g.db.transaction(force_rollback=True),
        ):
            g.db.execute(
                "UPDATE capabilities SET action_type = 'MEASUREMENT' WHERE capability_id = %s",
                (sp.CAP_INSPECT_CONNECTIVITY,),
            )


def test_a_rule_check_rereading_the_design_is_not_new_evidence(guarded):
    """Another rule reading of the very design file the screened reading read: deterministic, so
    its outcome was fixed -- and readable -- before the rival was proposed."""
    g = guarded
    with g.db.transaction(force_rollback=True):
        g.register_capabilities()
        run = g.run(
            "rule-reread",
            capability_id=sp.CAP_EXTRACTION_CONSISTENCY,
            backend_id="sp.local.normalization_basis_reader",
            input_parameters={"variant": "rule-reread"},
            output_artifacts=(g.fresh_output("rule-reread"),),
        )
        _offered(g, run, "rule-reread", "deterministic")


# -- 4. authorization -------------------------------------------------------------------------


def test_a_new_measurement_nobody_authorized_cannot_support(guarded):
    """Everything 011p asks holds; no one pre-registered it as a test of the rival."""
    g = guarded
    with g.db.transaction(force_rollback=True):
        g.register_capabilities()
        run = _probe(g, "unauthorized", outputs=(g.artifact("probe", captured_at=g.later),))
        _offered(g, run, "unauthorized", "authoriz")
