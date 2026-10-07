"""§8's Hypothesis Admission Gate, and the competing set it admits into (EPI-001).

    §8       只有通過 Hypothesis Admission Gate，補齊 mechanism、prediction、falsifier、
             assumptions、confounders 與 minimum test，才可佔用昂貴 simulation budget。
    §3 P6    Competing hypotheses — 任何時刻維持 ≥2 個競爭機制
    EPI-001  至少維護 2 個 competing hypotheses；單一看似合理原因不得直接被升級成 confirmed root
             cause。

M0b BUILT THE CERTIFICATE AND THE GENESIS EVENT; THIS IS WHAT DECIDES WHETHER ONE MAY BE WRITTEN.
`Hypothesis` refuses a blank statement, mechanism or falsifier, and `belief.admit_hypothesis`
records a first state -- and its docstring says it "checks nothing about the certificate, which is
why EPI-003 stays IN_PROGRESS". The checks it defers are here:

    complete      >=1 assumption, >=1 confounder, a minimal test, an author, an episode, at
                  least one typed Prediction (§8: "補齊 ... prediction"), and a typed falsifier:
                  at least one of its own CONTRADICTS predictions, designated as such (`012n`)
    bound         every Prediction admitted against the exact OutcomeSpace version it names
                  (`prediction.bind`, VER-006's rule reused, not restated)
    provenanced   an LLM-authored certificate names an inference that is durably recorded in the
                  same project (LLM-001: a certificate whose provenance does not resolve is text)
    competing     a set is admitted with >=2 certificates proposing DISTINCT mechanisms; two
                  phrasings of one mechanism are one hypothesis twice (P6)
    grounded      the genesis event cites the attestations the certificate was reasoned from --
                  the evidence bundle the engine was shown -- each resolving in the set's project.
                  §6.18's rollback replays by skipping events whose triggers were quarantined, so
                  a hypothesis proposed from a contaminated bundle must name that bundle's
                  evidence, or quarantine cannot reach it

THE PROMOTION HALF LIVES IN `revision_gate`, AND THE DATABASE HOLDS BOTH. "A single plausible cause
must not be directly upgraded" is a rule about a later transition, so it is enforced where
transitions are attempted; `011i` refuses the same promotion and the same incomplete admission for
any writer of SQL.

ADMISSION IS ALL OR NOTHING PER SET. A competing set whose first member was admitted and whose
second was refused would be exactly the single-cause set EPI-001 forbids, durably, with a genesis
event. So every certificate is checked before any is written.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from enum import StrEnum

from lab_brain.core.belief import EpistemicStateProjection, admit_hypothesis
from lab_brain.core.models.attestation import Attestation
from lab_brain.core.models.belief_event import BeliefRevisionEvent
from lab_brain.core.models.hypothesis_set import HypothesisCertificate, HypothesisSet
from lab_brain.core.models.inference import InferenceProvenance
from lab_brain.core.models.prediction import OutcomeSpace, PredictionAdmissionError, bind
from lab_brain.core.models.transition import TransitionPolicy
from lab_brain.core.repositories.hypotheses import (
    HypothesisStore,
    certificate_completeness_problems,
)


class AdmissionRefusal(StrEnum):
    """Why a certificate or a set was refused. The assertion surface, so an enum."""

    INCOMPLETE_CERTIFICATE = "INCOMPLETE_CERTIFICATE"
    PREDICTION_UNBOUND = "PREDICTION_UNBOUND"
    PROVENANCE_UNRESOLVED = "PROVENANCE_UNRESOLVED"
    WRONG_SCOPE = "WRONG_SCOPE"
    NOT_COMPETING = "NOT_COMPETING"
    DUPLICATE_MECHANISM = "DUPLICATE_MECHANISM"
    UNGROUNDED = "UNGROUNDED"


class HypothesisAdmissionRefused(RuntimeError):
    def __init__(self, reason: AdmissionRefusal, detail: str) -> None:
        super().__init__(f"{reason.value}: {detail}")
        self.reason = reason
        self.detail = detail


OutcomeSpaceLookup = Callable[[str, str], OutcomeSpace | None]
ProvenanceLookup = Callable[[str], InferenceProvenance | None]
#: (project_id, attestation_id) -> the attestation, read in that project only (SEC-002).
AttestationLookup = Callable[[str, str], Attestation | None]


def mechanism_key(certificate: HypothesisCertificate) -> str:
    """The mechanism a certificate proposes, normalised for the P6 distinctness check.

    Whitespace and case only. Anything cleverer -- synonyms, embeddings -- would be a similarity
    judgment, and a gate that merged "contact discontinuity" with "contact resistance" on a model's
    say-so would be letting a model decide which rivals exist.
    """
    return " ".join(certificate.hypothesis.mechanism.lower().split())


def check_certificate(
    certificate: HypothesisCertificate,
    hypothesis_set: HypothesisSet,
    *,
    outcome_space: OutcomeSpaceLookup,
    provenance: ProvenanceLookup,
) -> None:
    """Refuse a certificate §8's gate would not admit. Pure: reads only through the lookups."""
    h = certificate.hypothesis
    if (
        h.project_id != hypothesis_set.project_id
        or certificate.hypothesis_set_id != hypothesis_set.set_id
        or h.created_in_episode != hypothesis_set.episode_id
    ):
        raise HypothesisAdmissionRefused(
            AdmissionRefusal.WRONG_SCOPE,
            f"hypothesis {h.hypothesis_id} (project {h.project_id}, episode "
            f"{h.created_in_episode}, set {certificate.hypothesis_set_id}) is not a member of set "
            f"{hypothesis_set.set_id} in {hypothesis_set.project_id}/{hypothesis_set.episode_id}",
        )
    problems = certificate_completeness_problems(certificate)
    if problems:
        raise HypothesisAdmissionRefused(
            AdmissionRefusal.INCOMPLETE_CERTIFICATE,
            f"hypothesis {h.hypothesis_id}'s certificate is incomplete: {problems}. §8 admits a "
            "hypothesis only with mechanism, prediction, falsifier, assumptions, confounders and a "
            "minimum test; until then it is an idea, and ideas do not occupy simulation budget",
        )
    for prediction in certificate.predictions:
        space = outcome_space(prediction.outcome_space_id, prediction.outcome_space_version)
        if space is None:
            raise HypothesisAdmissionRefused(
                AdmissionRefusal.PREDICTION_UNBOUND,
                f"prediction {prediction.prediction_id} names outcome space "
                f"{prediction.outcome_space_ref}, which is not declared (VER-004)",
            )
        try:
            bind(prediction, space)
        except PredictionAdmissionError as refused:
            raise HypothesisAdmissionRefused(
                AdmissionRefusal.PREDICTION_UNBOUND, str(refused)
            ) from refused
    if h.inference_provenance_id is not None:
        recorded = provenance(h.inference_provenance_id)
        if recorded is None:
            raise HypothesisAdmissionRefused(
                AdmissionRefusal.PROVENANCE_UNRESOLVED,
                f"hypothesis {h.hypothesis_id} cites inference {h.inference_provenance_id}, which "
                "is not durably recorded. LLM-001: a certificate an LLM proposed without durable "
                "provenance is text nobody can replay",
            )


def check_competing(
    certificates: Sequence[HypothesisCertificate], hypothesis_set: HypothesisSet
) -> None:
    """P6 over the set: at least two certificates, each proposing a distinct mechanism."""
    if len(certificates) < 2:
        raise HypothesisAdmissionRefused(
            AdmissionRefusal.NOT_COMPETING,
            f"set {hypothesis_set.set_id} would be admitted with {len(certificates)} "
            "hypothesis. EPI-001: 至少維護 2 個 competing hypotheses -- a set of one is a single "
            "plausible cause, which is what the requirement exists to stop from becoming a root "
            "cause",
        )
    seen: dict[str, str] = {}
    for certificate in certificates:
        key = mechanism_key(certificate)
        if key in seen:
            raise HypothesisAdmissionRefused(
                AdmissionRefusal.DUPLICATE_MECHANISM,
                f"{certificate.hypothesis_id} and {seen[key]} propose the same mechanism "
                f"({key!r}); two phrasings of one mechanism are one hypothesis counted twice, and "
                "P6's 'competing' would be satisfied by repetition",
            )
        seen[key] = certificate.hypothesis_id


def resolve_basis(
    basis: Sequence[str], hypothesis_set: HypothesisSet, *, attestations: AttestationLookup
) -> tuple[Attestation, ...]:
    """The attestations a certificate was reasoned from, resolved in the set's project.

    Empty is refused: a hypothesis grounded in nothing survives every §6.18 rollback, and "the
    engine was shown no evidence" is a reason not to admit, not a first state. Each id must resolve
    to an attestation of the SAME project -- a basis borrowed from another project is a SEC-002
    leak that the genesis event would make durable.
    """
    if not basis:
        raise HypothesisAdmissionRefused(
            AdmissionRefusal.UNGROUNDED,
            f"set {hypothesis_set.set_id} would be admitted from no evidence. A genesis event must "
            "cite the attestations its certificate was reasoned from, or §6.18's contamination "
            "rollback cannot reach it",
        )
    resolved: list[Attestation] = []
    for attestation_id in dict.fromkeys(basis):
        found = attestations(hypothesis_set.project_id, attestation_id)
        if found is None or found.project_id != hypothesis_set.project_id:
            raise HypothesisAdmissionRefused(
                AdmissionRefusal.UNGROUNDED,
                f"basis attestation {attestation_id} does not resolve in project "
                f"{hypothesis_set.project_id}; a hypothesis may only be grounded in evidence its "
                "own project admitted",
            )
        resolved.append(found)
    return tuple(resolved)


@dataclass(frozen=True)
class AdmittedSet:
    hypothesis_set: HypothesisSet
    certificates: tuple[HypothesisCertificate, ...]
    events: tuple[BeliefRevisionEvent, ...]

    @property
    def hypothesis_ids(self) -> tuple[str, ...]:
        return tuple(c.hypothesis_id for c in self.certificates)


class HypothesisAdmissionService:
    """Check every certificate, then write sets, certificates and genesis events.

    `append` is M0b's event sink (`SqlBeliefEventStore.append` / the in-memory one) and the genesis
    event is minted by `belief.admit_hypothesis` -- the only admission path the event store
    accepts. This service adds the certificate checks in front of it and nothing else.

    ATOMICITY IS THE CALLER'S TRANSACTION. Every certificate in a set is checked before any is
    written, so a refusal writes nothing; a storage failure midway is rolled back by the
    transaction the orchestrator holds around `admit_set` (`HypothesisBrain` does), which is what
    keeps a half-admitted set -- a single plausible cause with a genesis event -- from ever being
    durable.
    """

    def __init__(
        self,
        *,
        store: HypothesisStore,
        append: Callable[[object], BeliefRevisionEvent],
        outcome_space: OutcomeSpaceLookup,
        provenance: ProvenanceLookup,
        attestations: AttestationLookup,
        atomic: Callable[[], AbstractContextManager[object]] | None = None,
    ) -> None:
        self._store = store
        self._append = append
        self._outcome_space = outcome_space
        self._provenance = provenance
        self._attestations = attestations
        #: One transaction around a set's writes (PostgreSQL: `connection.transaction`). No model
        #: is called inside it -- every certificate was produced and checked before it opens.
        self._atomic = atomic or nullcontext

    def admit_set(
        self,
        hypothesis_set: HypothesisSet,
        certificates: Sequence[HypothesisCertificate],
        *,
        basis: Sequence[str],
        policy: TransitionPolicy,
        event_ids: Sequence[str],
        occurred_at: dt.datetime,
        trace_id: str,
        actor_id: str | None = None,
    ) -> AdmittedSet:
        """Admit a new competing set: >=2 distinct mechanisms, every certificate complete.

        `basis` is the attestation ids of the bundle the certificates were reasoned from; every
        genesis event in the set cites them.
        """
        check_competing(certificates, hypothesis_set)
        for certificate in certificates:
            check_certificate(
                certificate,
                hypothesis_set,
                outcome_space=self._outcome_space,
                provenance=self._provenance,
            )
        grounds = resolve_basis(basis, hypothesis_set, attestations=self._attestations)
        if len(event_ids) != len(certificates):
            raise ValueError("one event id per certificate")
        with self._atomic():
            self._store.add_set(hypothesis_set)
            events = tuple(
                self._write(
                    certificate,
                    grounds=grounds,
                    policy=policy,
                    event_id=event_id,
                    occurred_at=occurred_at,
                    trace_id=trace_id,
                    actor_id=actor_id,
                )
                for certificate, event_id in zip(certificates, event_ids, strict=True)
            )
        return AdmittedSet(hypothesis_set, tuple(certificates), events)

    def admit_alternative(
        self,
        hypothesis_set: HypothesisSet,
        certificate: HypothesisCertificate,
        *,
        basis: Sequence[str],
        policy: TransitionPolicy,
        event_id: str,
        occurred_at: dt.datetime,
        trace_id: str,
        actor_id: str | None = None,
    ) -> BeliefRevisionEvent:
        """Add a rival to an existing set -- the Critic's alternative mechanism, in a later round.

        Checked against the mechanisms already in the set: a "new" alternative that restates an
        admitted mechanism would inflate the count without adding a rival.
        """
        existing = self._store.certificates_in_set(hypothesis_set.set_id)
        check_competing((*existing, certificate), hypothesis_set)
        check_certificate(
            certificate,
            hypothesis_set,
            outcome_space=self._outcome_space,
            provenance=self._provenance,
        )
        grounds = resolve_basis(basis, hypothesis_set, attestations=self._attestations)
        with self._atomic():
            return self._write(
                certificate,
                grounds=grounds,
                policy=policy,
                event_id=event_id,
                occurred_at=occurred_at,
                trace_id=trace_id,
                actor_id=actor_id,
            )

    def _write(
        self,
        certificate: HypothesisCertificate,
        *,
        grounds: Sequence[Attestation],
        policy: TransitionPolicy,
        event_id: str,
        occurred_at: dt.datetime,
        trace_id: str,
        actor_id: str | None,
    ) -> BeliefRevisionEvent:
        h = certificate.hypothesis
        self._store.add_certificate(certificate)
        authorized = admit_hypothesis(
            event_id=event_id,
            policy=policy,
            project_id=h.project_id,
            hypothesis_id=h.hypothesis_id,
            prior=EpistemicStateProjection(
                project_id=h.project_id,
                target_id=h.hypothesis_id,
                current_state=None,
                last_event_id=None,
            ),
            occurred_at=occurred_at,
            trace_id=trace_id,
            triggering_attestations=grounds,
            actor_id=actor_id,
            inference_provenance_id=h.inference_provenance_id,
        )
        return self._append(authorized)


__all__ = [
    "AdmissionRefusal",
    "AdmittedSet",
    "AttestationLookup",
    "HypothesisAdmissionRefused",
    "HypothesisAdmissionService",
    "OutcomeSpaceLookup",
    "ProvenanceLookup",
    "check_certificate",
    "check_competing",
    "mechanism_key",
    "resolve_basis",
]
