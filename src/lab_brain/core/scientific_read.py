"""The one authorization boundary for scientific reads (SEC-002, R-7, §14.1, §14.4).

WHY THIS EXISTS, STATED AS THE DEFECT IT CLOSES.

M1 grew several production read surfaces and each of them answered a *different* question before
returning canonical evidence:

    CandidateResolver           asked EvidenceUnitOccurrence presence (§17.25.1)
    IngestionService.evidence_for  asked nothing -- it took no Actor at all
    PostgresEvidenceUnitReader  asks nothing, deliberately, and documents that
    DiagnosticsService          reimplemented clearance against SensitivityLabel

**A project occurrence proves presence, not authorization.** §17.25.1 answers "is this evidence in
this project"; SEC-002 answers "may this actor read it". A surface that checks only the first
returns a RESTRICTED_NDA body to a project member whose clearance is INTERNAL -- and every
individual check it performed passed honestly.

So there is one gate, and it is not a new one. `can_read_artifact` already evaluates all six facts
the audit named -- resolved Actor, `Actor.active`, ProjectMembership, `ProjectMembership.active`,
sensitivity clearance and the ArtifactOccurrence -- and it is the M0b-locked implementation of
SEC-002. This module does not re-decide any of that. It *composes* it: it resolves the records a
scientific read needs, maps an EvidenceUnit back to the Artifact its authorization derives from,
and calls the one gate.

WHY AUTHORIZATION FOLLOWS THE ARTIFACT AND NOT THE UNIT. An EvidenceUnit is globally identified
and carries no project (ADR-0012) and no sensitivity label; `artifact_occurrences` carries the
label, per project, and that is where §14.1 puts classification. So the authorization question for
"may I read this passage" is exactly "may I read the document it came from, in this project" --
one question, already answered by one gate. Giving units their own labels would be a second
classification scheme to keep in step with the first.

WHAT LOW-LEVEL READERS MAY STILL DO. `PostgresEvidenceUnitReader` remains ACL-free and that is
correct: it is the canonical revalidating loader, used by admission and by this gate itself, and
putting an ACL inside it would be a second copy of SEC-002. What changed is that the composition
root no longer *exposes* it at all. An intermediate shape exported it as `unauthorized_reader()`
and argued that the name was the contract; it is not. A production service that hands out a
canonical-body loader answering to nobody has a public bypass whatever the accessor is called,
and the M1 vertical was itself calling it. Trusted implementation code holds the reader through a
private field; tests that need it construct their own.

AUTHORIZE BEFORE THE BODY EXISTS IN THE PROCESS. Every path here decides from a *descriptor* --
``(evidence_unit_id, artifact_id)``, which is the minimum an authorization needs and carries no
text -- and loads the canonical unit only after an ALLOW. Loading first and filtering afterwards
is a correct filter over an exposure that already happened: the RESTRICTED_NDA body is in memory,
in logs if anything logged the row, and in the traceback if the filter raises.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from lab_brain.core.access import AccessDecision, can_read_artifact
from lab_brain.core.models.access import Actor, ArtifactOccurrence, ProjectMembership
from lab_brain.core.models.evidence_unit import EvidenceUnit, RetrievalCandidate


class ScientificReadRefused(Exception):
    """An authorized scientific read was refused.

    Carries the `AccessDecision`, so a caller that needs to audit the refusal has the reason the
    gate produced rather than a re-derived one.
    """

    def __init__(self, decision: AccessDecision) -> None:
        super().__init__(decision.reason)
        self.decision = decision


@dataclass(frozen=True)
class UnitSecurityDescriptor:
    """The minimum an authorization needs, and nothing a refusal would regret having read.

    Two ids. No body, no locator, no conditions. This exists so `authorize` can run against a
    unit the process has not loaded: an EvidenceUnit's classification lives on its Artifact's
    occurrence in the project (ADR-0012, §14.1), so the artifact id is the whole of what the
    decision consults.
    """

    evidence_unit_id: str
    artifact_id: str


@dataclass(frozen=True)
class AuthorizedUnit:
    """An EvidenceUnit whose read has been authorized, with the decision that authorized it.

    The decision travels with the unit on purpose. A bare list of units is indistinguishable from
    a list nobody checked, and an incident review asks *why* a body was returned -- which a
    boolean discarded at the filter cannot answer.
    """

    unit: EvidenceUnit
    decision: AccessDecision

    @property
    def body(self) -> str:
        return self.unit.body


class ScientificReadGate:
    """The production authorization boundary for reading scientific evidence.

    NOT A SECOND ACL. Every verdict is `can_read_artifact`'s. This class resolves the three
    records that gate needs -- Actor, ProjectMembership, ArtifactOccurrence -- and nothing else.
    A reviewer checking whether SEC-002 is implemented correctly still reads exactly one file.
    """

    def __init__(
        self,
        *,
        load_actor: Callable[[str], Actor | None],
        load_membership: Callable[[str, str], ProjectMembership | None],
        load_occurrence: Callable[[str, str], ArtifactOccurrence | None],
    ) -> None:
        self._load_actor = load_actor
        self._load_membership = load_membership
        self._load_occurrence = load_occurrence

    # -- the one decision ---------------------------------------------------

    def authorize_artifact(
        self, *, actor_id: str, project_id: str, artifact_id: str
    ) -> AccessDecision:
        """May ``actor_id`` read ``artifact_id`` as it exists in ``project_id``?

        Resolvers are consulted and the answer is the gate's. An unresolvable actor produces
        ``None`` and the gate refuses it -- rather than this method short-circuiting, which would
        be a seventh decision made outside the one place decisions are made.
        """
        return can_read_artifact(
            self._load_actor(actor_id),
            artifact_id,
            project_id,
            self._load_occurrence(artifact_id, project_id),
            self._load_membership(actor_id, project_id),
        )

    def authorize_unit(
        self, unit: EvidenceUnit, *, actor_id: str, project_id: str
    ) -> AccessDecision:
        """The same question for a passage, asked about the document it came from.

        See the module docstring: an EvidenceUnit carries no project and no label, so its
        authorization *is* its artifact's in this project.
        """
        return self.authorize_artifact(
            actor_id=actor_id, project_id=project_id, artifact_id=unit.artifact_id
        )

    def authorize_descriptor(
        self, descriptor: UnitSecurityDescriptor, *, actor_id: str, project_id: str
    ) -> AccessDecision:
        """The same question, asked before the unit has been loaded.

        This is the form every production read path uses. `authorize_unit` remains for callers
        that legitimately already hold a unit -- admission re-verifies one it has just rebuilt --
        but it must never be what *causes* the load.
        """
        return self.authorize_artifact(
            actor_id=actor_id, project_id=project_id, artifact_id=descriptor.artifact_id
        )

    # -- the surfaces -------------------------------------------------------

    def require_unit(self, unit: EvidenceUnit, *, actor_id: str, project_id: str) -> AuthorizedUnit:
        """Single-unit read. Raises, because a caller asking for one thing wants it or an error."""
        decision = self.authorize_unit(unit, actor_id=actor_id, project_id=project_id)
        if not decision.allowed:
            raise ScientificReadRefused(decision)
        return AuthorizedUnit(unit=unit, decision=decision)

    def clears_label(self, *, actor_id: str, project_id: str, artifact_id: str) -> AccessDecision:
        """The clearance question other surfaces used to answer for themselves.

        `DiagnosticsService` had its own comparison against `SensitivityLabel`. It agreed with
        this one, which is the dangerous kind of duplication: two copies of a rule that agree
        today and are edited separately. Exposed here so there is one answer.
        """
        return self.authorize_artifact(
            actor_id=actor_id, project_id=project_id, artifact_id=artifact_id
        )


#: A resolver that turns a reference into its canonical unit. Supplied by the caller because the
#: canonical loader is `PostgresEvidenceUnitReader.load` in production and an in-memory dict in a
#: contract test -- and neither belongs inside an authorization boundary.
UnitLoader = Callable[[str], EvidenceUnit | None]

#: ``evidence_unit_id -> artifact_id``, reading no body. The security-metadata half of the same
#: store, kept as a separate callable so the ordering below is visible in the types: what this
#: returns is enough to decide, and not enough to disclose.
ArtifactOfUnit = Callable[[str], str | None]


class AuthorizedCandidateResolver:
    """References → canonical bodies, only for references this actor may read.

    WHY THIS WRAPS `CandidateResolver` RATHER THAN REPLACING IT. EVI-010's locked boundary is
    that a candidate carries no body and the canonical unit is re-loaded by identity; that is
    unchanged and must stay unchanged. What this adds is the authorization question §17.25.1
    could not answer -- occurrence presence is not clearance.

    ORDER, AND IT IS NOW THE IMPLEMENTATION AND NOT JUST THE DOCSTRING:

        candidate.evidence_unit_id
          -> artifact_of(...)        security metadata only, no body
          -> gate.authorize_descriptor(...)
          -> load_unit(...)          canonical body, ONLY on ALLOW

    An earlier version documented this order and did the opposite: it loaded the unit first
    because `authorize_unit` needed `unit.artifact_id`, then filtered. The filter was correct and
    the body of every refused unit had already been materialized in the process -- which is what
    an exposure is. The descriptor step exists so the decision has what it needs without that.
    """

    def __init__(
        self,
        *,
        gate: ScientificReadGate,
        artifact_of: ArtifactOfUnit,
        load_unit: UnitLoader,
    ) -> None:
        self._gate = gate
        self._artifact_of = artifact_of
        self._load_unit = load_unit

    def resolve(
        self, candidates: Sequence[RetrievalCandidate], *, actor_id: str, project_id: str
    ) -> tuple[AuthorizedUnit, ...]:
        """Resolve what this actor may read, in candidate order.

        A candidate that does not resolve is dropped rather than raising -- an index row pointing
        at a deleted unit is an index-maintenance problem, and failing the whole retrieval would
        turn it into an outage. A candidate the actor may not read is dropped for a different
        reason and both are silent to the caller, deliberately: telling a researcher "there are
        three results you may not see" is itself a disclosure about a project's contents.
        """
        descriptors: list[UnitSecurityDescriptor] = []
        for candidate in candidates:
            if candidate.project_id != project_id:
                # A candidate from another project's index. Dropped before any read at all:
                # §17.25.1's scope and SEC-002's are different questions and this is the first.
                continue
            artifact_id = self._artifact_of(candidate.evidence_unit_id)
            if artifact_id is None:
                continue
            descriptors.append(
                UnitSecurityDescriptor(
                    evidence_unit_id=candidate.evidence_unit_id, artifact_id=artifact_id
                )
            )
        return self.resolve_descriptors(descriptors, actor_id=actor_id, project_id=project_id)

    def resolve_descriptors(
        self,
        descriptors: Sequence[UnitSecurityDescriptor],
        *,
        actor_id: str,
        project_id: str,
    ) -> tuple[AuthorizedUnit, ...]:
        """The same authorize-then-load step over descriptors already in hand.

        Used by the whole-project read, where one query produces every descriptor and asking
        `artifact_of` per unit would be the same decision at N times the cost.

        FILTERED, NOT REFUSED WHOLESALE. A researcher legitimately holds clearance for some of a
        project's documents and not others, and failing the whole query would make the system
        unusable in exactly the projects where classification matters most. What must never
        happen is a body crossing the boundary, and that is what the ordering guarantees.
        """
        authorized: list[AuthorizedUnit] = []
        for descriptor in descriptors:
            decision = self._gate.authorize_descriptor(
                descriptor, actor_id=actor_id, project_id=project_id
            )
            if not decision.allowed:
                continue
            unit = self._load_unit(descriptor.evidence_unit_id)
            if unit is None:
                continue
            authorized.append(AuthorizedUnit(unit=unit, decision=decision))
        return tuple(authorized)


__all__ = [
    "ArtifactOfUnit",
    "AuthorizedCandidateResolver",
    "AuthorizedUnit",
    "ScientificReadGate",
    "ScientificReadRefused",
    "UnitLoader",
    "UnitSecurityDescriptor",
]
