"""Resolving and re-checking diagnostic warrants: the impure seam the pure policy reads through.

    TransitionPolicy.evaluate   pure; counts a SUPPORTS or CONTRADICTS only with its warrant, and
                                evaluates authority, conditions and independence over those
    this module                 reads certificates, attestations, runs, declarations and grants,
                                and states per relation what the policy may count

The split is the one `core.episode` draws for authority classes: `evaluate` must stay replayable,
so every repository read happens here and its result goes into the decision snapshot. A snapshot
is only a record of inputs, so the read path asks this module again (`verify`) against the same
sources -- the declaration set version the warrant names, the grant it cites, the attestations
and runs behind the relation -- before a stored ALLOW may change a belief.

WHAT IS NEVER READ. Who authored the hypothesis or prediction -- provider, model, slot, connection.
A catalog reasoner and a language model that state the same declared link are warranted alike,
and a route named after the catalog reasoner gains nothing. Only claim content, the registered
declaration sets and durable grants decide. A relation that cannot be traced to its prediction gets
no DOMAIN warrant: there is then no declared link to compare.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

from lab_brain.core.canonical_json import canonical_hash
from lab_brain.core.models.attestation import Attestation
from lab_brain.core.models.enums import RelationType
from lab_brain.core.models.hypothesis_set import HypothesisCertificate
from lab_brain.core.models.job import Run
from lab_brain.core.models.observation import Observation
from lab_brain.core.models.prediction import Prediction
from lab_brain.core.models.relation import RelationJudgment
from lab_brain.core.models.transition import RelationEvidence, WarrantBasis
from lab_brain.core.models.warrant import (
    DiagnosticDeclaration,
    DiagnosticDeclarationSet,
    DiagnosticWarrantGrant,
    GrantVerdict,
    Link,
    parse_domain_ref,
)

#: The relation types a diagnostic warrant gates.
GATED_TYPES = frozenset({RelationType.SUPPORTS, RelationType.CONTRADICTS})


class GrantLookup(Protocol):
    def grants_for_relations(
        self, project_id: str, relation_ids: Sequence[str]
    ) -> tuple[DiagnosticWarrantGrant, ...]: ...

    def grant(self, project_id: str, grant_id: str) -> DiagnosticWarrantGrant | None: ...


CertificateLookup = Callable[[str, str], HypothesisCertificate | None]
RelationLookup = Callable[[str, str], RelationJudgment | None]
AttestationLookup = Callable[[str, str], Attestation | None]
ObservationLookup = Callable[[str, str], Observation | None]
RunLookup = Callable[[str], Run | None]


def observed_link(relation: RelationJudgment, prediction: Prediction) -> Link | None:
    """The (observable, space, version, outcome) a relation records having observed, or None.

    Only a relation instantiated from this prediction by an observation qualifies: it names the
    prediction, and the outcome it records is the one the prediction expected.
    """
    attributes = relation.attributes
    if attributes.get("prediction_id") != prediction.prediction_id:
        return None
    if attributes.get("outcome") != prediction.expected_outcome:
        return None
    space = attributes.get("outcome_space")
    if space is not None and space != prediction.outcome_space_ref:
        return None
    return (
        prediction.observable_ref,
        prediction.outcome_space_id,
        prediction.outcome_space_version,
        prediction.expected_outcome,
    )


def domain_warrant(
    relation: RelationJudgment,
    certificate: HypothesisCertificate,
    declarations: DiagnosticDeclarationSet,
) -> DiagnosticDeclaration | None:
    """The declaration warranting this relation, or None. Pure.

    The hypothesis must be bound to a class (exact mechanism, agreeing predictions), the relation
    must be an observation of one of its predictions on the class's observable, and the declared
    meaning of the observed outcome must be the relation's own type: the class's signature for
    SUPPORTS, one of its refuting outcomes for CONTRADICTS.
    """
    if relation.relation_type not in GATED_TYPES:
        return None
    declaration = declarations.bound_class(
        certificate.hypothesis.mechanism, certificate.predictions
    )
    if declaration is None:
        return None
    prediction = next(
        (
            p
            for p in certificate.predictions
            if p.prediction_id == relation.attributes.get("prediction_id")
        ),
        None,
    )
    if prediction is None or not declaration.same_observable(prediction):
        return None
    link = observed_link(relation, prediction)
    if link is None or declaration.effect_for(link[3]) is not relation.relation_type:
        return None
    return declaration


def evidence_line(runs: Sequence[Run]) -> str | None:
    """One identity for the execution(s) behind a relation, or None if any is unknown.

    Capability, backend, input artefacts (content-addressed ids) and parameters: two Runs of one
    computation on one input are the same line, so repeating a check never manufactures
    independence. Not the observable -- one Run emitting two observables is still one line.
    """
    if not runs:
        return None
    keys = sorted(
        (
            run.capability_id,
            run.backend_id,
            tuple(sorted(run.input_artifacts)),
            canonical_hash(dict(run.input_parameters)),
        )
        for run in runs
    )
    return canonical_hash([list(k) for k in keys])


def _content(relation: RelationJudgment) -> tuple[object, ...]:
    """What a relation says, without its validity window -- which an invalidation may close."""
    return (
        relation.relation_id,
        relation.project_id,
        relation.from_entity_id,
        relation.to_entity_id,
        relation.relation_type,
        dict(relation.attributes),
        tuple(relation.supporting_attestation_ids),
        relation.condition_match_ref,
    )


@dataclass(frozen=True)
class ResolvedEvidence:
    records: tuple[RelationEvidence, ...] = ()


class WarrantUnverified(RuntimeError):
    """A recorded relation fact or warrant does not re-check against its source."""


class WarrantResolver:
    """Per-relation facts, DOMAIN warrants from the active declaration set, REVIEW from grants.

    `declaration_sets` holds every version that may appear in a stored warrant -- the read path
    re-checks against the version recorded, never the newest -- and `active` names the one new
    resolutions use. A deployment without one resolves no DOMAIN warrant: every gated relation
    then needs a person, which is slower and never wrong in the direction that matters.
    """

    def __init__(
        self,
        *,
        certificates: CertificateLookup,
        attestations: AttestationLookup,
        observations: ObservationLookup,
        runs: RunLookup,
        grants: GrantLookup | None,
        relations: RelationLookup | None = None,
        declaration_sets: Sequence[DiagnosticDeclarationSet] = (),
        active: str | None = None,
    ) -> None:
        sets = {s.ref: s for s in declaration_sets}
        if len(sets) != len(declaration_sets):
            raise ValueError("a declaration set version is registered twice")
        if active is not None and active not in sets:
            raise ValueError(f"active declaration set {active} is not registered")
        self._sets: Mapping[str, DiagnosticDeclarationSet] = MappingProxyType(sets)
        self._active = active
        self._certificates = certificates
        self._attestations = attestations
        self._observations = observations
        self._runs = runs
        self._grants = grants
        #: The stored relations, so the read path re-checks a recorded warrant against the
        #: relation as stored -- not against the snapshot's own copy of it. None only where there
        #: is no store to ask (unit tests); a deployment always passes one.
        self._relations = relations

    @property
    def active(self) -> DiagnosticDeclarationSet | None:
        return None if self._active is None else self._sets[self._active]

    def declaration(self, domain_ref: str) -> DiagnosticDeclaration | None:
        parsed = parse_domain_ref(domain_ref)
        if parsed is None:
            return None
        found = self._sets.get(f"{parsed[0]}@{parsed[1]}")
        return None if found is None else found.by_class(parsed[2])

    def certificate(self, project_id: str, hypothesis_id: str) -> HypothesisCertificate | None:
        return self._certificates(project_id, hypothesis_id)

    # -- facts ------------------------------------------------------------------------------

    def _facts(
        self, project_id: str, relation: RelationJudgment
    ) -> tuple[tuple[str, ...], str | None]:
        classes, line, _ = self._observed(project_id, relation)
        return classes, line

    def _observed(
        self, project_id: str, relation: RelationJudgment
    ) -> tuple[tuple[str, ...], str | None, bool]:
        """Authority classes, evidence line, and whether every attestation recorded the outcome
        the relation claims -- a relation is a claim about an observation, and the observation's
        own record is what it must agree with."""
        classes: set[str] = set()
        runs: list[Run] = []
        unknown = False
        agrees = True
        for attestation_id in sorted(set(relation.supporting_attestation_ids)):
            attestation = self._attestations(project_id, attestation_id)
            if attestation is None:
                unknown = True
                continue
            recorded = attestation.method.get("outcome") if attestation.method else None
            if recorded is not None and recorded != relation.attributes.get("outcome"):
                agrees = False
            if attestation.authority_class:
                classes.add(attestation.authority_class)
            run_id = attestation.run_id
            if run_id is None and attestation.observation_id is not None:
                observation = self._observations(project_id, attestation.observation_id)
                run_id = None if observation is None else observation.run_id
            run = None if run_id is None else self._runs(run_id)
            if run is None or run.project_id != project_id:
                unknown = True
            else:
                runs.append(run)
        return tuple(sorted(classes)), None if unknown else evidence_line(runs), agrees

    def resolve(
        self, project_id: str, hypothesis_id: str, relations: Sequence[RelationJudgment]
    ) -> ResolvedEvidence:
        gated = sorted(
            (r for r in relations if r.relation_type in GATED_TYPES), key=lambda r: r.relation_id
        )
        if not gated:
            return ResolvedEvidence()
        certificate = self._certificates(project_id, hypothesis_id)
        grants: dict[str, DiagnosticWarrantGrant] = {}
        if self._grants is not None:
            for grant in self._grants.grants_for_relations(
                project_id, [r.relation_id for r in gated]
            ):
                if grant.hypothesis_id == hypothesis_id:
                    grants[grant.relation_id] = grant
        active = self.active
        records: list[RelationEvidence] = []
        for relation in gated:
            classes, line, agrees = self._observed(project_id, relation)
            warrant: WarrantBasis | None = None
            ref: str | None = None
            refused = False
            declaration = (
                None
                if certificate is None or active is None
                else domain_warrant(relation, certificate, active)
            )
            answered = grants.get(relation.relation_id)
            if answered is not None and (
                answered.relation_type is not relation.relation_type
                or answered.prediction_id != relation.attributes.get("prediction_id")
            ):
                answered = None
            if not agrees:
                # The relation claims an outcome its own attestations did not record: nothing
                # vouches for a link to an observation that did not happen.
                declaration = None
                answered = None
            # A person who refused this exact link outranks a declaration about the class: the
            # refusal is about this observation, the declaration is general.
            if answered is not None and answered.verdict is GrantVerdict.NOT_WARRANTED:
                refused = True
            elif declaration is not None and active is not None:
                warrant, ref = WarrantBasis.DOMAIN, active.domain_ref(declaration)
            elif answered is not None:
                warrant, ref = WarrantBasis.REVIEW, answered.grant_id
            prediction_id = relation.attributes.get("prediction_id")
            records.append(
                RelationEvidence(
                    relation_id=relation.relation_id,
                    relation_type=relation.relation_type,
                    prediction_id=None if prediction_id is None else str(prediction_id),
                    authority_classes=classes,
                    evidence_line=line,
                    warrant=warrant,
                    warrant_ref=ref,
                    refused=refused,
                )
            )
        return ResolvedEvidence(records=tuple(records))

    # -- re-checking a recorded record -------------------------------------------------------

    def verify(
        self,
        project_id: str,
        hypothesis_id: str,
        record: RelationEvidence,
        relations: Sequence[RelationJudgment],
    ) -> None:
        """Raise `WarrantUnverified` unless a recorded record re-checks against its sources.

        Against the declaration set version the warrant names, not the active one, so upgrading
        a pack's declarations never invalidates a belief warranted under the earlier version.
        """
        relation = next((r for r in relations if r.relation_id == record.relation_id), None)
        if relation is None or relation.relation_type is not record.relation_type:
            raise WarrantUnverified(
                f"record for {record.relation_id} names no {record.relation_type.value} relation "
                "in the snapshot"
            )
        if relation.to_entity_id != hypothesis_id:
            raise WarrantUnverified(f"{record.relation_id} is not a relation to {hypothesis_id}")
        if self._relations is not None:
            stored = self._relations(project_id, record.relation_id)
            if stored is None or _content(stored) != _content(relation):
                raise WarrantUnverified(
                    f"the snapshot's copy of {record.relation_id} is not the relation stored"
                )
        if record.prediction_id != relation.attributes.get("prediction_id"):
            raise WarrantUnverified(f"record for {record.relation_id} names another prediction")
        classes, line, agrees = self._observed(project_id, relation)
        if record.warrant is not None and not agrees:
            raise WarrantUnverified(
                f"{record.relation_id} claims an outcome its attestations did not record"
            )
        if (classes, line) != (record.authority_classes, record.evidence_line):
            raise WarrantUnverified(
                f"record for {record.relation_id} states authority {record.authority_classes} and "
                f"line {record.evidence_line}; its attestations and runs give {classes} and {line}"
            )
        if record.warrant is WarrantBasis.DOMAIN:
            parsed = parse_domain_ref(record.warrant_ref or "")
            declarations = None if parsed is None else self._sets.get(f"{parsed[0]}@{parsed[1]}")
            certificate = self._certificates(project_id, hypothesis_id)
            found = (
                None
                if declarations is None or certificate is None
                else domain_warrant(relation, certificate, declarations)
            )
            if found is None or parsed is None or found.class_id != parsed[2]:
                raise WarrantUnverified(
                    f"DOMAIN warrant {record.warrant_ref} does not declare {hypothesis_id}'s link "
                    f"for {record.relation_id}"
                )
            return
        grant = (
            None
            if self._grants is None
            else next(
                iter(self._grants.grants_for_relations(project_id, [record.relation_id])), None
            )
        )
        if record.warrant is WarrantBasis.REVIEW:
            if (
                grant is None
                or grant.grant_id != record.warrant_ref
                or grant.verdict is not GrantVerdict.WARRANTED
                or grant.hypothesis_id != hypothesis_id
                or grant.relation_type is not record.relation_type
                or grant.prediction_id != relation.attributes.get("prediction_id")
            ):
                raise WarrantUnverified(
                    f"REVIEW warrant {record.warrant_ref} is not a WARRANTED grant for "
                    f"{record.relation_id} of {hypothesis_id}"
                )
        elif record.refused and (grant is None or grant.verdict is not GrantVerdict.NOT_WARRANTED):
            raise WarrantUnverified(f"record for {record.relation_id} claims a refusal nobody made")


__all__ = [
    "GATED_TYPES",
    "AttestationLookup",
    "CertificateLookup",
    "GrantLookup",
    "ObservationLookup",
    "RelationLookup",
    "ResolvedEvidence",
    "RunLookup",
    "WarrantResolver",
    "WarrantUnverified",
    "domain_warrant",
    "evidence_line",
    "observed_link",
]
