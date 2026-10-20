"""T-SEC-002 — one authorization boundary for every production scientific read (R-7).

THE DEFECT THESE PROBES CLOSE, in one sentence: **a project occurrence proves presence, not
authorization.** §17.25.1 answers "is this evidence in this project"; SEC-002 answers "may this
actor read it". Every M1 read surface that checked only the first returned a RESTRICTED_NDA body
to a member whose clearance was INTERNAL -- and every check it performed passed honestly.

Four surfaces bypassed the ACL before this repair:

    CandidateResolver              occurrence presence only
    IngestionService.evidence_for  no Actor parameter at all
    PostgresEvidenceUnitReader     ACL-free, and exposed as an authorized read
    DiagnosticsService             its own clearance comparison

All four now go through `ScientificReadGate`, which decides nothing -- every verdict is
`can_read_artifact`'s, the M0b-locked SEC-002 implementation.

THE ASSERTION IS ALWAYS ABOUT THE BODY. A refusal that returns an empty list is indistinguishable
from a query that found nothing, so each probe checks that the canonical text is *absent* from
what came back, not merely that the result was empty.
"""

from __future__ import annotations

import datetime as dt

import pytest

from lab_brain.composition import IngestionService
from lab_brain.core.models.enums import SensitivityLabel
from lab_brain.core.scientific_read import ScientificReadRefused, UnitSecurityDescriptor
from lab_brain.evidence.dense_index import DenseEvidenceIndex, EmbeddingSpace, hashing_embedder
from lab_brain.storage.artifacts.local import LocalArtifactStore
from lab_brain.storage.postgres.evidence_units import PostgresEvidenceUnitReader
from tests.evidence_fixtures import fixture_bytes

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.requirement("SEC-002"),
    pytest.mark.spec_test("T-SEC-002"),
]

PROJECT = "prj:test"
OTHER_PROJECT = "prj:other"
NOW = dt.datetime(2026, 9, 22, 10, 0, tzinfo=dt.UTC)
SPACE = EmbeddingSpace(model="toy-embed", version="1.0.0", dimensions=64)

#: Every actor below is a *member* with a *present* occurrence. The only thing that varies is the
#: fact the ACL is being asked about, so a probe that passed for the wrong reason would show up as
#: its neighbour also passing.
CLEARED = "act:cleared"
UNCLEARED = "act:uncleared"
INACTIVE_ACTOR = "act:inactive"
REVOKED = "act:revoked"
OUTSIDER = "act:outsider"


@pytest.fixture
def world(db, tmp_path):
    """One RESTRICTED_NDA document, and five actors differing in exactly one fact each."""
    db.execute(
        "INSERT INTO projects (project_id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (OTHER_PROJECT, "Other Project"),
    )
    for actor_id, active in (
        (CLEARED, True),
        (UNCLEARED, True),
        (INACTIVE_ACTOR, False),
        (REVOKED, True),
        (OUTSIDER, True),
    ):
        db.execute(
            "INSERT INTO actors (actor_id, actor_type, display_name, active) "
            "VALUES (%s, 'HUMAN', %s, %s) ON CONFLICT DO NOTHING",
            (actor_id, actor_id, active),
        )
    nda = ["RESTRICTED_NDA"]
    for actor_id, clearance, active in (
        (CLEARED, nda, True),
        (UNCLEARED, ["INTERNAL"], True),
        (INACTIVE_ACTOR, nda, True),
        (REVOKED, nda, False),
    ):
        db.execute(
            "INSERT INTO project_memberships (actor_id, project_id, role, "
            "sensitivity_clearance, approval_scopes, active) "
            "VALUES (%s, %s, 'RESEARCHER', %s, ARRAY[]::text[], %s)",
            (actor_id, PROJECT, clearance, active),
        )
    # The outsider is a fully cleared, active member -- of the OTHER project.
    db.execute(
        "INSERT INTO project_memberships (actor_id, project_id, role, sensitivity_clearance, "
        "approval_scopes, active) VALUES (%s, %s, 'RESEARCHER', %s, ARRAY[]::text[], TRUE)",
        (OUTSIDER, OTHER_PROJECT, nda),
    )

    svc = IngestionService(
        connection=db, artifact_store=LocalArtifactStore(tmp_path), clock=lambda: NOW
    )
    job = svc.submit(
        project_id=PROJECT, actor_id=CLEARED, idempotency_key="idem:acl", trace_id="trc:acl"
    )
    result = svc.ingest(
        fixture_bytes(),
        job_id=job.job_id,
        actor_id=CLEARED,
        sensitivity_label=SensitivityLabel.RESTRICTED_NDA,
        uri="file:///nda.md",
    )
    assert result.succeeded, "the fixture ingestion failed"
    return db, svc, result


def raw_reader(db) -> PostgresEvidenceUnitReader:
    """The ACL-free canonical loader, built HERE as test infrastructure.

    Production no longer exposes one. An intermediate shape offered
    `IngestionService.unauthorized_reader()` and argued the name was the contract; it is not -- a
    production service handing out a canonical-body loader that answers to nobody has a public
    bypass whatever the accessor is called, and the M1 vertical was calling it.

    A test constructing its own is a different thing entirely: this file needs the plaintext in
    order to assert its ABSENCE from the authorized surfaces, and building the reader here makes
    that an explicit act of test scaffolding rather than a production capability.
    """
    return PostgresEvidenceUnitReader(db)


def _secret_text(db, result) -> str:
    units = raw_reader(db).load_for_project(PROJECT)
    assert units, "no evidence to protect"
    return units[0].body


# ---------------------------------------------------------------------------
# 1. Member, insufficient clearance
# ---------------------------------------------------------------------------


def test_a_member_without_clearance_gets_no_canonical_body_from_evidence_for(world):
    """THE R-7 probe. Membership and occurrence are both present; clearance is not.

    Before this repair `evidence_for(project_id)` took no Actor and returned the body.
    """
    _db, svc, result = world
    secret = _secret_text(_db, result)

    allowed = svc.evidence_for(actor_id=UNCLEARED, project_id=PROJECT)
    assert allowed == (), "an uncleared member received canonical evidence"
    assert secret not in repr(allowed)

    control = svc.evidence_for(actor_id=CLEARED, project_id=PROJECT)
    assert control, "the positive control returned nothing; the gate may refuse everyone"
    assert any(u.body == secret for u in control)


def test_a_member_without_clearance_gets_no_body_from_retrieval(world):
    """The same actor, the same document, reached through retrieval instead.

    A retrieval candidate EXISTS for them -- the index is project-scoped and they are in the
    project. Occurrence presence is satisfied; clearance is not, and the body must not cross.
    """
    _db, svc, result = world
    secret = _secret_text(_db, result)

    index = DenseEvidenceIndex("idx:dense:v1", SPACE, hashing_embedder(SPACE))
    index.add_all(raw_reader(_db).load_for_project(PROJECT), project_id=PROJECT)
    candidates = index.search("reverse bias", project_id=PROJECT, space=SPACE, limit=50)
    assert candidates, "the index returned nothing; the probe would be vacuous"

    resolver = svc.candidate_resolver()
    refused = resolver.resolve(candidates, actor_id=UNCLEARED, project_id=PROJECT)
    assert refused == ()
    assert secret not in repr(refused)

    allowed = resolver.resolve(candidates, actor_id=CLEARED, project_id=PROJECT)
    assert allowed, "the positive control resolved nothing"
    assert any(u.body == secret for u in allowed)


# ---------------------------------------------------------------------------
# 2. Cross-project
# ---------------------------------------------------------------------------


def test_an_actor_from_another_project_cannot_read_this_projects_evidence(world):
    """Fully cleared and active -- in `prj:other`. Presence in one project grants nothing here.

    Both directions are asserted: asking about this project's evidence as an outsider, and
    asking about this project's evidence *through* the other project's scope.
    """
    _db, svc, result = world
    secret = _secret_text(_db, result)

    assert svc.evidence_for(actor_id=OUTSIDER, project_id=PROJECT) == ()
    # Through their own project, where they are cleared: the evidence has no occurrence there.
    assert svc.evidence_for(actor_id=OUTSIDER, project_id=OTHER_PROJECT) == ()
    assert secret not in repr(svc.evidence_for(actor_id=OUTSIDER, project_id=OTHER_PROJECT))


def test_the_gate_names_the_missing_occurrence_rather_than_the_clearance(world):
    """The refusal reason matters: it decides who the user is sent to.

    "You are not cleared" sends a researcher to an approver; "this is not in your project" sends
    them to check what they asked for. The canonical gate already distinguishes these and the
    boundary must not flatten them.
    """
    _db, svc, _result = world
    decision = svc.read_gate().authorize_artifact(
        actor_id=OUTSIDER, project_id=OTHER_PROJECT, artifact_id="art:whatever"
    )
    assert not decision.allowed
    assert "occurrence" in decision.reason


# ---------------------------------------------------------------------------
# 3 & 4. Inactive actor, inactive membership
# ---------------------------------------------------------------------------


def test_an_inactive_actor_with_valid_membership_and_clearance_is_refused(world):
    """`Actor.active` is the global fact. A departed researcher's memberships still exist.

    Checking only the membership would leave a centrally disabled credential holding every grant
    it already had -- which is why `can_read_artifact` checks both, and why this probe holds the
    boundary to the same standard.
    """
    _db, svc, result = world
    secret = _secret_text(_db, result)

    assert svc.evidence_for(actor_id=INACTIVE_ACTOR, project_id=PROJECT) == ()
    decision = svc.read_gate().authorize_artifact(
        actor_id=INACTIVE_ACTOR, project_id=PROJECT, artifact_id=result.artifact.artifact_id
    )
    assert not decision.allowed
    assert "not active" in decision.reason
    assert secret not in decision.reason


def test_an_inactive_membership_is_refused(world):
    """Revocation without deleting the audit trail. The actor is active; the grant is not."""
    _db, svc, result = world
    assert svc.evidence_for(actor_id=REVOKED, project_id=PROJECT) == ()
    decision = svc.read_gate().authorize_artifact(
        actor_id=REVOKED, project_id=PROJECT, artifact_id=result.artifact.artifact_id
    )
    assert not decision.allowed
    assert "not active" in decision.reason


def test_an_unresolvable_actor_is_refused(world):
    """An unidentified request cannot be authorised (§14.4: no governance without 'who')."""
    _db, svc, _result = world
    assert svc.evidence_for(actor_id="act:does-not-exist", project_id=PROJECT) == ()


# ---------------------------------------------------------------------------
# 5. The authorized path, and the shape of the result
# ---------------------------------------------------------------------------


def test_an_authorized_actor_retrieves_and_resolves_canonical_evidence(world):
    """The positive control, end to end: retrieval → authorization → canonical body."""
    _db, svc, result = world
    secret = _secret_text(_db, result)

    index = DenseEvidenceIndex("idx:dense:v1", SPACE, hashing_embedder(SPACE))
    index.add_all(raw_reader(_db).load_for_project(PROJECT), project_id=PROJECT)
    candidates = index.search("reverse bias", project_id=PROJECT, space=SPACE, limit=50)

    resolved = svc.candidate_resolver().resolve(candidates, actor_id=CLEARED, project_id=PROJECT)
    assert resolved
    assert any(u.body == secret for u in resolved)
    # Every body that crossed the boundary carries the decision that let it.
    for unit in resolved:
        assert unit.decision.allowed
        assert CLEARED in unit.decision.reason


def test_a_refused_single_read_raises_with_the_canonical_reason(world):
    """`require_unit` is the single-item read; a caller asking for one thing wants it or an error."""
    _db, svc, _result = world
    unit = raw_reader(_db).load_for_project(PROJECT)[0]
    with pytest.raises(ScientificReadRefused) as caught:
        svc.read_gate().require_unit(unit, actor_id=UNCLEARED, project_id=PROJECT)
    assert not caught.value.decision.allowed
    assert "clearance" in caught.value.decision.reason


def test_authorization_follows_the_artifact_not_the_unit(world):
    """Why one question, not two.

    An EvidenceUnit carries no project (ADR-0012) and no label; `artifact_occurrences` carries
    the label per project, which is where §14.1 puts classification. So "may I read this passage"
    IS "may I read the document it came from, here". Giving units their own labels would be a
    second classification scheme to keep in step with the first.
    """
    _db, svc, result = world
    unit = raw_reader(_db).load_for_project(PROJECT)[0]
    assert unit.artifact_id == result.artifact.artifact_id
    assert not hasattr(unit, "sensitivity_label")
    assert not hasattr(unit, "project_id")

    by_unit = svc.read_gate().authorize_unit(unit, actor_id=UNCLEARED, project_id=PROJECT)
    by_artifact = svc.read_gate().authorize_artifact(
        actor_id=UNCLEARED, project_id=PROJECT, artifact_id=unit.artifact_id
    )
    assert by_unit == by_artifact


def test_the_boundary_contains_no_second_acl(world):
    """Structural: `scientific_read` decides nothing on its own.

    Every verdict is `can_read_artifact`'s. A module that grew its own comparison against
    `SensitivityLabel` would agree today and be edited separately tomorrow -- which is exactly
    what `DiagnosticsService` had done, and what this repair removed.
    """
    import ast
    import inspect

    from lab_brain.core import scientific_read

    tree = ast.parse(inspect.getsource(scientific_read))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
    }
    assert "can_read_artifact" in names, "the boundary does not call the canonical gate"
    for invented in ("SensitivityLabel", "clears", "sensitivity_clearance", "RESTRICTED_NDA"):
        assert invented not in names, (
            f"{invented} appears in the read boundary; clearance is decided in one place"
        )


def test_the_composition_root_exposes_no_raw_reader(world):
    """Structural: production hands out no canonical-body loader that answers to nobody.

    `unauthorized_reader()` existed and was documented as safe because of its name. A method
    named "unauthorized" is documentation; it is not an authorization control, and the M1 vertical
    itself was calling it to fetch canonical bodies. What closes R-7 is that the accessor is gone
    -- the reader is a private field used by this class's own trusted paths.

    Asserted over the PUBLIC surface rather than by name, so re-adding the capability under a
    different name fails too.
    """
    _db, svc, _result = world
    public = [name for name in dir(svc) if not name.startswith("_")]
    assert "unauthorized_reader" not in public

    for name in public:
        attribute = getattr(type(svc), name, None)
        if not callable(attribute):
            continue
        returns = getattr(attribute, "__annotations__", {}).get("return")
        assert returns is not PostgresEvidenceUnitReader, (
            f"IngestionService.{name} returns the ACL-free reader; a production accessor for it "
            "is a public bypass whatever it is called"
        )


def test_an_unauthorized_body_is_never_loaded_by_the_authorized_path(world):
    """ORDERING, not just the verdict. The refused unit's body is never materialized.

    The resolver used to load the canonical unit first -- it needed `unit.artifact_id` to ask the
    question -- and filter afterwards. The filter was correct and the RESTRICTED_NDA text had
    already been read into the process that was about to decide it may not be.

    The loader here RAISES if entered, so reaching it fails loudly rather than producing a passing
    assertion about an empty result.
    """
    from lab_brain.core.scientific_read import AuthorizedCandidateResolver

    _db, svc, _result = world
    reader = raw_reader(_db)
    descriptors = tuple(
        UnitSecurityDescriptor(evidence_unit_id=unit_id, artifact_id=artifact_id)
        for unit_id, artifact_id in reader.security_index_for_project(PROJECT)
    )
    assert descriptors, "no evidence to protect"

    def fatal_load(_unit_id: str):
        raise AssertionError(
            "the canonical body was loaded for a unit this actor may not read; the filter is "
            "correct and the exposure has already happened"
        )

    refused = AuthorizedCandidateResolver(
        gate=svc.read_gate(), artifact_of=reader.artifact_of, load_unit=fatal_load
    ).resolve_descriptors(descriptors, actor_id=UNCLEARED, project_id=PROJECT)
    assert refused == ()

    allowed = AuthorizedCandidateResolver(
        gate=svc.read_gate(), artifact_of=reader.artifact_of, load_unit=reader.load
    ).resolve_descriptors(descriptors, actor_id=CLEARED, project_id=PROJECT)
    assert allowed, "the positive control loaded nothing; the probe would be vacuous"


def test_a_candidate_from_another_projects_index_is_dropped_before_any_read(world):
    """§17.25.1's scope, asserted as ORDERING rather than only as an outcome.

    A foreign candidate would be refused anyway -- the artifact has no occurrence here, so
    SEC-002 says no. That makes the two checks look redundant and they are not: this one drops
    the candidate before *any* query runs, so a cross-project index entry costs nothing and
    discloses nothing, not even the existence of a row to look up.

    Both loaders raise if entered, so this proves the candidate never became a read.
    """
    from lab_brain.core.models.evidence_unit import RetrievalCandidate
    from lab_brain.core.scientific_read import AuthorizedCandidateResolver

    _db, svc, _result = world

    def fatal_artifact_of(_unit_id: str) -> str:
        raise AssertionError(
            "a candidate from another project's index was looked up; §17.25.1's scope question "
            "is asked before SEC-002's, and a foreign candidate must cost no query at all"
        )

    def fatal_load(_unit_id: str):
        raise AssertionError("a candidate from another project's index was loaded")

    resolver = AuthorizedCandidateResolver(
        gate=svc.read_gate(), artifact_of=fatal_artifact_of, load_unit=fatal_load
    )
    foreign = RetrievalCandidate(
        evidence_unit_id="evu:sha256:" + "f" * 64,
        representation_id="rrp:elsewhere",
        project_id=OTHER_PROJECT,
        score=0.99,
        rank=1,
    )
    assert resolver.resolve([foreign], actor_id=CLEARED, project_id=PROJECT) == ()
