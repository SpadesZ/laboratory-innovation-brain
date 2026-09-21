"""EVI-009's Run half, closed by OPS-001 (§25.3, §14.3, §17.4).

WHAT M1-P1 LEFT OPEN, AND WHY IT WAS LEFT OPEN.

The admission gate recorded a Run reference and did not resolve it. The comment in
`_check_reference` said so outright: Run was not an entity, and resolving the reference would have
required inventing a fake Run record -- which is precisely the shape the gate exists to refuse. So
M1-P1 admitted artifact-backed evidence and declared EVI-009 READY on the artifact half only.

`006_jobs_runs.sql` makes Runs durable, so the reference is now resolved. Three things are
checked, not one, and the third is the one that would be easiest to skip:

    resolves            a reference to a Run nobody can load fails closed
    produced something  §25.3 says "Run provenance must trace to produced Artifact(s)", which a
                        Run that merely exists does not satisfy
    same project        resolving by id alone lets evidence inherit another project's authority

Each has its own ``RefusalReason``, so a test cannot pass because the wrong guard fired.
"""

from __future__ import annotations

import pytest

from lab_brain.core.models import (
    Attestation,
    EpistemicType,
    ExtractionProvenance,
)
from lab_brain.core.models.job import Run, RunStatus
from lab_brain.ingestion.admission_gate import (
    AdmissionRefusal,
    AdmissionRequest,
    EvidenceAdmissionGate,
    RefusalReason,
)
from tests.conftest_fixtures import TOY_SCHEMA_REF
from tests.job_fixtures import make_run

pytestmark = [pytest.mark.requirement("EVI-009"), pytest.mark.spec_test("T-EVI-009")]

PROJECT = "prj:test"
OTHER_PROJECT = "prj:other"


def _attestation(
    run_id: str | None = "run:measured",
    *,
    epistemic_type: EpistemicType = EpistemicType.MEASURED,
    project_id: str = PROJECT,
) -> Attestation:
    return Attestation(
        claim_id="clm:cj-falls-with-reverse-bias",
        epistemic_type=epistemic_type,
        run_id=run_id,
        locator="run output / row 2",
        conditions={"bias_v": -2.0},
        conditions_schema_version=TOY_SCHEMA_REF,
        project_id=project_id,
        extractor_version="1.0.0",
        extraction_provenance=ExtractionProvenance(
            extractor_id="metric_extractor", extractor_version="1.0.0"
        ),
    )


def _gate(runs: dict[str, Run] | None = None, *, resolver: bool = True) -> EvidenceAdmissionGate:
    store = runs or {}
    return EvidenceAdmissionGate(
        load_artifact=lambda _: None,
        load_evidence_unit=lambda _: None,
        load_run=(lambda key: store.get(key)) if resolver else None,
    )


def _admit(gate: EvidenceAdmissionGate, attestation: Attestation) -> Attestation:
    return gate.admit(AdmissionRequest(attestation=attestation))


# ---------------------------------------------------------------------------
# The positive path
# ---------------------------------------------------------------------------


def test_a_measurement_backed_by_a_real_run_is_admitted():
    """The control. Without it every refusal below could be a gate that refuses everything."""
    run = make_run("run:measured", job_id="job:m", project_id=PROJECT, outputs=("art:trace",))
    admitted = _admit(_gate({"run:measured": run}), _attestation())
    assert admitted.run_id == "run:measured"


def test_the_run_reference_resolves_to_the_artifacts_it_produced():
    """§25.3's "Run provenance must trace to produced Artifact(s)", followed through.

    Asserting the admission succeeded is not enough: what makes the reference *useful* is that a
    reader can get from the attestation to the bytes. So the test walks it.
    """
    run = make_run(
        "run:measured", job_id="job:m", project_id=PROJECT, outputs=("art:trace", "art:raw")
    )
    gate = _gate({"run:measured": run})
    admitted = _admit(gate, _attestation())
    assert run.produced("art:trace")
    assert set(run.output_artifacts) == {"art:trace", "art:raw"}
    assert admitted.run_id == run.run_id


# ---------------------------------------------------------------------------
# The three refusals
# ---------------------------------------------------------------------------


def test_a_reference_to_a_run_that_does_not_exist_fails_closed():
    """THE probe M1-P1 could not write. Before OPS-001 this was admitted unresolved."""
    with pytest.raises(AdmissionRefusal) as caught:
        _admit(_gate({}), _attestation("run:never-happened"))
    assert caught.value.reason is RefusalReason.REFERENCED_RUN_NOT_FOUND


def test_a_run_reference_with_no_resolver_configured_fails_closed():
    """A deployment that cannot resolve Runs must not admit Run-backed evidence.

    The same fail-closed reading Repair-2 applied to the occurrence resolver: an unverifiable
    reference is not a verified one, and treating "no resolver" as "skip the check" is the
    fail-open shape that audit found three times.
    """
    with pytest.raises(AdmissionRefusal) as caught:
        _admit(_gate(resolver=False), _attestation())
    assert caught.value.reason is RefusalReason.REFERENCED_RUN_NOT_FOUND


def test_a_failed_run_cannot_back_a_measurement():
    """A Run that exists is not a Run that produced evidence.

    §6.10 needs failed runs to be recorded, so the Run itself is legitimate. What is refused is
    citing it as the provenance of a MEASURED value -- an execution that produced nothing cannot
    be where a number came from.
    """
    failed = make_run(
        "run:measured",
        job_id="job:m",
        project_id=PROJECT,
        status=RunStatus.FAILED,
        outputs=(),
    )
    with pytest.raises(AdmissionRefusal) as caught:
        _admit(_gate({"run:measured": failed}), _attestation())
    assert caught.value.reason is RefusalReason.RUN_PRODUCED_NO_ARTIFACT


def test_a_run_in_another_project_cannot_be_cited():
    """SEC-002 one entity over from CROSS_PROJECT_UNIT.

    Resolving by id alone would let an attestation in project A inherit the authority of an
    execution in project B -- and the attestation would look perfectly well-formed.
    """
    elsewhere = make_run(
        "run:measured", job_id="job:m", project_id=OTHER_PROJECT, outputs=("art:trace",)
    )
    with pytest.raises(AdmissionRefusal) as caught:
        _admit(_gate({"run:measured": elsewhere}), _attestation())
    assert caught.value.reason is RefusalReason.CROSS_PROJECT_RUN


# ---------------------------------------------------------------------------
# The rules the Run half must not disturb
# ---------------------------------------------------------------------------


def test_a_measurement_with_no_reference_at_all_is_still_refused():
    """The artifact-half rule, re-asserted. Adding a Run path must not open a way round it."""
    bare = Attestation(
        claim_id="clm:cj-falls-with-reverse-bias",
        epistemic_type=EpistemicType.MEASURED,
        source_work_id="swk:unreferenced",
        locator="somewhere",
        conditions={},
        conditions_schema_version=TOY_SCHEMA_REF,
        project_id=PROJECT,
        extractor_version="1.0.0",
        extraction_provenance=ExtractionProvenance(
            extractor_id="metric_extractor", extractor_version="1.0.0"
        ),
    )
    with pytest.raises(AdmissionRefusal) as caught:
        _admit(_gate(), bare)
    assert caught.value.reason is RefusalReason.REFERENCE_MISSING


def test_an_inferred_record_naming_a_run_is_not_subject_to_the_run_checks():
    """EVI-009 exempts INFERRED from the reference requirement, and the exemption still holds.

    The Run named here does not exist. An INFERRED record is not a measurement, so the gate must
    not demand its provenance resolve -- while EVI-003 continues to forbid typing it as fact,
    which the next test pins.
    """
    admitted = _admit(
        _gate({}),
        _attestation("run:never-happened", epistemic_type=EpistemicType.INFERRED),
    )
    assert admitted.epistemic_type is EpistemicType.INFERRED


def test_an_inference_still_cannot_be_typed_as_a_measurement_by_naming_a_real_run():
    """A real Run does not launder an inference into a fact.

    The attack is plausible: attach genuine execution provenance to an LLM interpretation and type
    it MEASURED. EVI-003 fires on the extraction provenance, which is upstream of this whole file,
    and a real run reference does not reach it.
    """
    run = make_run("run:measured", job_id="job:m", project_id=PROJECT, outputs=("art:trace",))
    llm_backed = Attestation(
        claim_id="clm:cj-falls-with-reverse-bias",
        epistemic_type=EpistemicType.MEASURED,
        run_id="run:measured",
        locator="run output",
        conditions={},
        conditions_schema_version=TOY_SCHEMA_REF,
        project_id=PROJECT,
        extractor_version="1.0.0",
        extraction_provenance=ExtractionProvenance(
            extractor_id="llm_extractor",
            extractor_version="1.0.0",
            inference_provenance_id="inf:guessed",
        ),
    )
    with pytest.raises(AdmissionRefusal) as caught:
        _admit(_gate({"run:measured": run}), llm_backed)
    assert caught.value.reason is RefusalReason.INFERENCE_TYPED_AS_FACT
