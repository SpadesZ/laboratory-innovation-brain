"""What can warrant a belief-moving relation: a domain's diagnostic declarations, or a person.

THE DISTINCTION THIS EXISTS FOR. A typed prediction that matches an observation says the prediction
came true. Its declared effect is its author's claim about what the outcome means for the
mechanism: SUPPORTS, that the mechanism produces it and the rivals do not; CONTRADICTS, that the
mechanism cannot. When the author is a language model that claim is unverified. `epi:7b56877f`
confirmed a mechanism on an outcome it could not produce, and three recorded rejections in the same
project rested on a falsifier the mechanism could not have triggered. A warrant is an accountable
source, other than the author, agreeing with the claim for one exact link:

    DOMAIN   a DiagnosticDeclarationSet the DomainPack registers, by version, names the link
    REVIEW   a person resolved a DIAGNOSTIC_WARRANT review for that relation as warranted

WHAT A DECLARATION SAYS. A mechanism class, the one observable whose outcome diagnoses it, the
outcome it produces there, and the outcomes it cannot. The supporting outcome is EXCLUSIVE within
the set: among the declared classes only this one produces it -- which is what makes an observation
of it discriminating rather than merely consistent, and why a set refuses two classes claiming the
same outcome. Declaring the exclusivity is the domain's responsibility, reviewed as code.

BINDING IS BY CONTENT, NOT BY AUTHOR. A hypothesis is of a declared class when it states the class's
canonical mechanism exactly AND its own predictions on the class's observable state the whole
declaration -- the signature as SUPPORTS, every refuting outcome as CONTRADICTS, nothing that
disagrees -- so the domain can refute what it would support. A paraphrase is unbound and goes to a
person, which is the safe way to be wrong; a hypothesis borrowing a class name over a partial or
disagreeing declaration is unbound too. Nothing here searches text, scores similarity or reads who
wrote a hypothesis.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterable
from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from lab_brain.core.canonical_json import canonical_hash
from lab_brain.core.models.base import CoreModel
from lab_brain.core.models.enums import RelationType
from lab_brain.core.models.prediction import Prediction
from lab_brain.core.models.reviewer import grant_statement

#: (observable, outcome space, space version, outcome): the observed side of a link.
Link = tuple[str, str, str, str]


class DiagnosticDeclaration(CoreModel):
    """One mechanism class: the observable that diagnoses it and what it does there."""

    class_id: str = Field(min_length=1)
    #: The canonical mechanism string a hypothesis states to be of this class, exactly.
    mechanism: str = Field(min_length=1)
    #: The class's own statement, shown beside a bound hypothesis's narrative in a conclusion.
    statement: str = Field(min_length=1)
    observable_ref: str
    outcome_space_id: str
    outcome_space_version: str
    #: Produced by this class and, within the set, by no other.
    supports_outcome: str
    #: Outcomes this class cannot produce on the observable: observing one refutes it.
    refutes_outcomes: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _an_outcome_cannot_both_support_and_refute(self) -> Self:
        if self.supports_outcome in self.refutes_outcomes:
            raise ValueError(
                f"class {self.class_id} declares {self.supports_outcome} as both its signature "
                "and its refutation"
            )
        return self

    def link(self, outcome: str) -> Link:
        return (self.observable_ref, self.outcome_space_id, self.outcome_space_version, outcome)

    @property
    def signature(self) -> Link:
        return self.link(self.supports_outcome)

    def same_observable(self, prediction: Prediction) -> bool:
        return (
            prediction.observable_ref,
            prediction.outcome_space_id,
            prediction.outcome_space_version,
        ) == (self.observable_ref, self.outcome_space_id, self.outcome_space_version)

    def refuted_by(self, link: Link) -> bool:
        """Whether this observed outcome is one the class cannot produce on its observable."""
        return link[:3] == self.signature[:3] and link[3] in self.refutes_outcomes

    def effect_for(self, outcome: str) -> RelationType | None:
        """What observing `outcome` means for this class, or None if the declaration is silent."""
        if outcome == self.supports_outcome:
            return RelationType.SUPPORTS
        if outcome in self.refutes_outcomes:
            return RelationType.CONTRADICTS
        return None

    def binds(self, predictions: Iterable[Prediction]) -> bool:
        """Whether a hypothesis's predictions on this observable make it this class.

        It must state the whole declaration: the signature as SUPPORTS and every refuting outcome
        as CONTRADICTS -- and nothing that disagrees (affirming an outcome the class cannot
        produce, or refuting its signature). Silence is NOT enough: a copy that omits the refuting
        outcome could be supported by the domain and never refuted by it, because a refutation
        acts only through a relation, and a relation exists only for an outcome predicted.
        """
        declared: set[tuple[str, RelationType]] = set()
        for prediction in predictions:
            if not self.same_observable(prediction):
                continue
            meaning = self.effect_for(prediction.expected_outcome)
            for effect in prediction.relation_effect_if_observed:
                kind = effect.relation_type
                if kind in (RelationType.SUPPORTS, RelationType.PREDICTS):
                    if meaning is not RelationType.SUPPORTS:
                        return False
                elif kind is RelationType.CONTRADICTS and meaning is not RelationType.CONTRADICTS:
                    return False
                declared.add((prediction.expected_outcome, kind))
        return (self.supports_outcome, RelationType.SUPPORTS) in declared and all(
            (outcome, RelationType.CONTRADICTS) in declared for outcome in self.refutes_outcomes
        )


#: `dds:<set id>@<version>#<class id>`, the reference a DOMAIN warrant carries.
_DOMAIN_REF = re.compile(r"^dds:(?P<set>[^@#\s]+)@(?P<version>[^@#\s]+)#(?P<cls>[^@#\s]+)$")


def parse_domain_ref(ref: str) -> tuple[str, str, str] | None:
    """`(set id, version, class id)` of a DOMAIN warrant reference, or None if it is not one."""
    found = _DOMAIN_REF.match(ref)
    if found is None:
        return None
    return found["set"], found["version"], found["cls"]


class DiagnosticDeclarationSet(CoreModel):
    """A domain's versioned diagnostic declarations.

    Immutable once registered: a changed declaration is a new version, so a warrant that cited
    the old one still re-checks. `digest` is pinned by the pack's tests, so an edit made in place
    without a version bump fails before it can silently change what re-derivation means.
    """

    set_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    domain: str
    declarations: tuple[DiagnosticDeclaration, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _one_class_per_signature(self) -> Self:
        """Class ids and mechanism strings are unique, and no outcome is two classes' signature."""
        for attribute in ("class_id", "mechanism"):
            values = [getattr(d, attribute) for d in self.declarations]
            twice = sorted({v for v in values if values.count(v) > 1})
            if twice:
                raise ValueError(f"declaration set {self.ref} declares {attribute} {twice} twice")
        owners: dict[Link, str] = {}
        for declaration in self.declarations:
            other = owners.setdefault(declaration.signature, declaration.class_id)
            if other != declaration.class_id:
                raise ValueError(
                    f"declaration set {self.ref} declares {declaration.signature} as the signature "
                    f"of both {other} and {declaration.class_id}. An outcome both classes produce "
                    "discriminates neither, so it cannot warrant support for either"
                )
        return self

    @property
    def ref(self) -> str:
        return f"{self.set_id}@{self.version}"

    @property
    def digest(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))

    def domain_ref(self, declaration: DiagnosticDeclaration) -> str:
        return f"dds:{self.ref}#{declaration.class_id}"

    def by_class(self, class_id: str) -> DiagnosticDeclaration | None:
        return next((d for d in self.declarations if d.class_id == class_id), None)

    def bound_class(
        self, mechanism: str, predictions: Iterable[Prediction]
    ) -> DiagnosticDeclaration | None:
        """The class a hypothesis is of, by its exact mechanism and its whole declaration."""
        declaration = next((d for d in self.declarations if d.mechanism == mechanism), None)
        if declaration is None or not declaration.binds(predictions):
            return None
        return declaration

    def signature_of(self, link: Link) -> DiagnosticDeclaration | None:
        """The class whose declared signature this observed outcome is, whatever anyone claims.

        Shown when an unbound hypothesis claims it: in `epi:7b56877f` it would have said that the
        observed DISAGREES is the signature of a length normalization error -- a class nobody had
        proposed.
        """
        return next((d for d in self.declarations if d.signature == link), None)


class GrantVerdict(StrEnum):
    """A reviewer's answer to "does this outcome bear on this mechanism as its author claims?"."""

    WARRANTED = "WARRANTED"
    #: Terminal for the relation: it never counts and is not asked about again.
    NOT_WARRANTED = "NOT_WARRANTED"


class DiagnosticWarrantGrant(CoreModel):
    """A person's resolution of one DIAGNOSTIC_WARRANT review: append-only, one relation.

    Not reusable. A grant answers for one relation of one hypothesis -- one observation of one
    prediction -- and says nothing about the class, the observable in general, or the next
    episode. Making a link domain knowledge is a DomainPack change, reviewed as code.
    """

    grant_id: str
    project_id: str
    review_id: str
    relation_id: str
    relation_type: RelationType
    hypothesis_id: str
    prediction_id: str
    verdict: GrantVerdict
    granted_by_actor_id: str
    granted_at: dt.datetime
    rationale: str
    #: The rivals the reviewer weighed the outcome against. Recorded because a warrant is only as
    #: good as the alternatives it was weighed against.
    considered_rival_ids: tuple[str, ...] = ()
    #: The reviewer's explicit statement that the hypothesis IS this declared class (`dds:` ref):
    #: how a person says a model's paraphrase is a catalog mechanism. Approving the link alone
    #: does not say it -- an outcome can diagnose a mechanism the domain did not name.
    identifies_class_ref: str | None = None
    #: V1.1: the reviewer key enrolment the answer was signed with, and the Ed25519 signature
    #: over `statement()`. An answer without them -- or whose signature does not verify against
    #: an authority-enrolled key -- counts as no answer (`lab_brain.security.reviewer_identity`).
    enrolment_id: str | None = None
    signature: str | None = None

    @model_validator(mode="after")
    def _a_rationale_is_required(self) -> Self:
        if not self.rationale.strip():
            raise ValueError(
                f"grant {self.grant_id} records no rationale; it is the only account of why a "
                "person judged this outcome diagnostic"
            )
        if self.relation_type not in (RelationType.SUPPORTS, RelationType.CONTRADICTS):
            raise ValueError(f"grant {self.grant_id} is for a {self.relation_type.value} relation")
        if self.identifies_class_ref is not None and (
            self.verdict is not GrantVerdict.WARRANTED
            or self.relation_type is not RelationType.SUPPORTS
            or parse_domain_ref(self.identifies_class_ref) is None
        ):
            raise ValueError(
                f"grant {self.grant_id} identifies a class but is not a WARRANTED support, or the "
                "reference is not a declaration reference"
            )
        return self

    def statement(self) -> bytes:
        """The exact bytes the reviewer signed (`core.models.reviewer.grant_statement`)."""
        return grant_statement(
            grant_id=self.grant_id,
            project_id=self.project_id,
            review_id=self.review_id,
            relation_id=self.relation_id,
            relation_type=self.relation_type.value,
            hypothesis_id=self.hypothesis_id,
            prediction_id=self.prediction_id,
            verdict=self.verdict.value,
            granted_by_actor_id=self.granted_by_actor_id,
            granted_at=self.granted_at,
            rationale=self.rationale,
            considered_rival_ids=self.considered_rival_ids,
            identifies_class_ref=self.identifies_class_ref,
            enrolment_id=self.enrolment_id or "",
        )


__all__ = [
    "DiagnosticDeclaration",
    "DiagnosticDeclarationSet",
    "DiagnosticWarrantGrant",
    "GrantVerdict",
    "Link",
    "parse_domain_ref",
]
