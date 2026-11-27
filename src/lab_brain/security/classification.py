"""Effective egress classification, derived from provenance (SEC-001, §14.1, §14.3).

WHY A CALLER MAY NOT STATE THE SENSITIVITY OF WHAT IT IS SENDING.

`AuthorizedExternalRunner` made the gate unbypassable: the transport is reachable only through
`execute`, and only on ALLOW. What it could not fix is *what the gate was deciding about*. Both
production entry points took the label as an argument --

    ScientificLLM.invoke(..., sensitivity=SensitivityLabel.PUBLIC)
    SourceRouter.search(..., sensitivity=SensitivityLabel.PUBLIC)

-- so a caller assembling a bundle of RESTRICTED_NDA evidence could declare PUBLIC and the gate
would answer correctly about a fiction. Every check ran; every check was honest; the material
left. An authorization over a caller-supplied classification is a caller-supplied authorization.

So the classification is *derived*. §14.1 puts the label on `ArtifactOccurrence` -- per project,
because ADR-0010 made presence and classification properties of the occurrence rather than of the
globally content-addressed artifact -- and that row is written by ingestion, not by the caller
about to send something. The path is:

    EvidenceBundle.ordered_attestation_ids
      -> Attestation.source_artifact_id      (the attestation records where the claim came from)
      -> ArtifactOccurrence.sensitivity_label in THIS project
      -> the set of labels the material actually carries

A SET, NOT A LEVEL, AND THE CONJUNCTION IS THE POINT. §14.1's labels are categories of handling,
not a security ladder: `CONFIDENTIAL_LAB` (unpublished lab work) does not contain `INTERNAL`
(meeting notes). `can_read_artifact` has said so since M0b and refuses to compare them with `>=`.
Collapsing a mixed bundle to "the most restrictive label" would require exactly the ordering this
codebase refuses to invent -- so instead material carrying {PUBLIC, CONFIDENTIAL_LAB} may leave
only if **both** PUBLIC and CONFIDENTIAL_LAB may leave. That needs no ordering, and it composes
`EgressGate` unchanged: the policy still lives in one place and is asked once per category.

ESCALATION IS A UNION, WHICH IS WHY IT CANNOT BE A DOWNGRADE. A caller may declare additional
labels; the effective set is `derived | declared`. Adding a member to a conjunction can only make
it harder to satisfy. There is no subtraction anywhere in this module, so "may escalate, must not
downgrade" is a property of the operation rather than a rule somebody remembered to check.

TWO WAYS TO BE UNUSABLE, AND BOTH REFUSE.

    unresolved   a context reference with no occurrence in this project. The material cannot be
                 classified here, and absence of a classification is not permission (§14.3) --
                 the same reading `EgressGate` already applies to a missing policy.
    empty        nothing was derived and nothing was declared. A conjunction over an empty set is
                 vacuously true, which would make "I sent no classification" the most permissive
                 thing a caller could say. It is refused instead.

THIS MODULE CLASSIFIES AND DECIDES NOTHING ELSE. It holds no policy, no provider list and no
clearance. Whether a label may leave is `EgressGate`'s question and stays there; what this answers
is *which labels are being asked about*. Keeping the two apart is why the runner needed no new
rule to gain a trustworthy input.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from lab_brain.core.models.access import ArtifactOccurrence
from lab_brain.core.models.enums import SensitivityLabel
from lab_brain.core.models.evidence_bundle import EvidenceBundle

#: ``(artifact_id, project_id) -> occurrence``. The same resolver `ScientificReadGate` is built
#: from, deliberately: the label an egress decision reads must be the label a read decision reads,
#: or the two disagree about what a document is.
OccurrenceLoader = Callable[[str, str], ArtifactOccurrence | None]

#: ``(attestation_id, project_id) -> source_artifact_id``. Project-scoped because an attestation
#: id resolved without a project would let a bundle name a row in someone else's project and
#: inherit its label.
ArtifactOfAttestation = Callable[[str, str], str | None]


class ClassificationRefused(Exception):
    """The material could not be classified, so it may not leave.

    Raised rather than returned as a permissive default. The two cases it covers -- an
    unclassifiable reference and an empty classification -- are exactly the ones where a
    return-value API invites a caller to treat "no answer" as "no restriction".
    """

    def __init__(self, classification: EgressClassification) -> None:
        super().__init__(classification.refusal_detail)
        self.classification = classification


@dataclass(frozen=True)
class EgressClassification:
    """What material carries, and where that was read from.

    ``basis`` and ``declared`` are kept apart after the union is computed. An auditor asking why
    an effect was blocked needs to know whether the restricting label came from a document or
    from the caller's own escalation -- and a single merged set cannot answer that.
    """

    labels: frozenset[SensitivityLabel]
    #: The artifact ids whose occurrences produced `derived`, sorted. The evidence for the claim.
    basis: tuple[str, ...] = ()
    #: What the caller asked to add. Never subtracted from `derived`; see the module docstring.
    declared: frozenset[SensitivityLabel] = frozenset()
    #: Context references that could not be classified in this project.
    unresolved: tuple[str, ...] = ()

    @property
    def usable(self) -> bool:
        return bool(self.labels) and not self.unresolved

    @property
    def refusal_detail(self) -> str:
        if self.unresolved:
            return (
                f"{list(self.unresolved)} have no classification in this project, so the material "
                "being sent cannot be classified. Absence of a classification is not permission "
                "(§14.3): an unresolvable reference is the shape a caller would use to smuggle "
                "material past a derivation it cannot otherwise influence"
            )
        return (
            "no sensitivity could be derived and none was declared. An empty classification would "
            "make the conjunction vacuous, so 'I said nothing about what I am sending' would be "
            "the most permissive thing a caller could say (§14.3)"
        )


class ContextClassifier:
    """Derives the effective egress classification of scientific context.

    Built from this deployment's stores and holding no policy of its own. The occurrence loader is
    the same one `ScientificReadGate` uses, so the label that decides a read and the label that
    decides an egress are read from one row.
    """

    def __init__(
        self,
        *,
        load_occurrence: OccurrenceLoader,
        artifact_of_attestation: ArtifactOfAttestation | None = None,
    ) -> None:
        self._load_occurrence = load_occurrence
        self._artifact_of_attestation = artifact_of_attestation

    def classify_artifacts(
        self,
        artifact_ids: Sequence[str],
        *,
        project_id: str,
        declared: frozenset[SensitivityLabel] = frozenset(),
    ) -> EgressClassification:
        """The labels a set of artifacts carries in this project.

        An artifact with no occurrence here is `unresolved` rather than skipped. Skipping it would
        mean a reference the project does not hold *lowers* the effective classification of the
        batch, which is the downgrade this module exists to remove -- and it is available to any
        caller who can name an id.
        """
        derived: set[SensitivityLabel] = set()
        basis: list[str] = []
        unresolved: list[str] = []
        for artifact_id in artifact_ids:
            occurrence = self._load_occurrence(artifact_id, project_id)
            if occurrence is None:
                unresolved.append(artifact_id)
                continue
            derived.add(occurrence.sensitivity_label)
            basis.append(artifact_id)
        return EgressClassification(
            # Union, never difference. The whole "may escalate, must not downgrade" rule is this
            # operator; there is no code path in this module that removes a derived label.
            labels=frozenset(derived) | declared,
            basis=tuple(sorted(set(basis))),
            declared=declared,
            unresolved=tuple(sorted(set(unresolved))),
        )

    def classify_bundle(
        self,
        bundle: EvidenceBundle,
        *,
        project_id: str,
        declared: frozenset[SensitivityLabel] = frozenset(),
    ) -> EgressClassification:
        """The labels an EvidenceBundle's evidence carries in this project.

        The bundle names attestations, not artifacts (§17.14.1), so the attestation's recorded
        `source_artifact_id` is the hop -- and it is authoritative for the same reason the
        occurrence is: ingestion wrote it, not the caller about to send the prompt.

        A bundle whose project differs from the one being classified is refused outright. Reading
        another project's labels into this project's decision would make a cross-project bundle a
        way to inherit a friendlier classification.
        """
        if self._artifact_of_attestation is None:
            raise ClassificationRefused(
                EgressClassification(
                    labels=frozenset(),
                    unresolved=tuple(sorted(bundle.ordered_attestation_ids)) or ("<bundle>",),
                )
            )
        if bundle.project_id != project_id:
            return EgressClassification(
                labels=declared,
                declared=declared,
                unresolved=(bundle.bundle_id,),
            )

        artifact_ids: list[str] = []
        unresolved: list[str] = []
        for attestation_id in bundle.ordered_attestation_ids:
            artifact_id = self._artifact_of_attestation(attestation_id, project_id)
            if artifact_id is None:
                unresolved.append(attestation_id)
                continue
            artifact_ids.append(artifact_id)

        classification = self.classify_artifacts(
            artifact_ids, project_id=project_id, declared=declared
        )
        if not unresolved:
            return classification
        return EgressClassification(
            labels=classification.labels,
            basis=classification.basis,
            declared=classification.declared,
            unresolved=tuple(sorted(set(classification.unresolved) | set(unresolved))),
        )

    # -- the forms production code uses -------------------------------------

    def require_artifacts(
        self,
        artifact_ids: Sequence[str],
        *,
        project_id: str,
        declared: frozenset[SensitivityLabel] = frozenset(),
    ) -> EgressClassification:
        return _require(
            self.classify_artifacts(artifact_ids, project_id=project_id, declared=declared)
        )

    def require_bundle(
        self,
        bundle: EvidenceBundle,
        *,
        project_id: str,
        declared: frozenset[SensitivityLabel] = frozenset(),
    ) -> EgressClassification:
        return _require(self.classify_bundle(bundle, project_id=project_id, declared=declared))


def _require(classification: EgressClassification) -> EgressClassification:
    """Refuse an unusable classification. One function, so both forms fail identically."""
    if not classification.usable:
        raise ClassificationRefused(classification)
    return classification


__all__ = [
    "ArtifactOfAttestation",
    "ClassificationRefused",
    "ContextClassifier",
    "EgressClassification",
    "OccurrenceLoader",
]
