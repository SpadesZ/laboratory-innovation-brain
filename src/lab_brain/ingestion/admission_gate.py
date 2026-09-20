"""The memory admission gate — §14.3, EVI-002, EVI-003, EVI-009, EVI-010.

§14.3 states two obligations in one line::

    Memory admission gate：任何 inferred claim 標為 inferred；measurement/simulation 需 artifact
    reference

and this module is where both become refusals rather than conventions.

WHY A GATE RATHER THAN MODEL VALIDATORS. Some of these *are* model validators --
``EvidenceField`` already refuses a value behind an ``UNKNOWN`` status, and ``Attestation``
already refuses two subjects. What a model cannot check is the relationship between a record and
the world: whether the artifact it references exists, whether the unit it was built from is a
baseline artefact, whether the text it reports came from an LLM. Those need a gate with access to
the stores, and a gate is also where a refusal can carry a reason code a user can act on.

EVERY REFUSAL IS FAIL-CLOSED. The absence of a reason to admit is a refusal, in the same shape as
``can_read_artifact``. That matters most for EVI-009: "we could not find the referenced artifact"
and "there is no reference" must both refuse, because a lookup that fails open turns a missing
artifact into an admitted measurement.

WHAT THIS GATE DOES NOT DO. It does not construct Attestations, resolve source works or decide
independence -- those are ``source_work_resolution`` and ``independence``, and duplicating their
rules here would give the system two places that decide what a corroboration is. One source of
truth per rule (§0.6).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from lab_brain.core.models.artifact import Artifact
from lab_brain.core.models.attestation import Attestation
from lab_brain.core.models.enums import (
    EpistemicType,
    FieldStatus,
    SubdivisionReason,
)
from lab_brain.core.models.evidence_unit import EvidenceUnit

#: EVI-009's scope. These two epistemic types assert that something was *done* -- an instrument
#: read a value, a solver computed one -- so the record must name the Run or Artifact it came
#: from. REPORTED and DERIVED are outside: a paper reporting someone else's measurement has a
#: source work, not a run of ours, and saying otherwise would make every citation a measurement.
REFERENCE_REQUIRED_TYPES = frozenset({EpistemicType.MEASURED, EpistemicType.SIMULATED})

#: EVI-003. What an LLM-derived record may never be typed as. INFERRED is the only type an
#: inference may carry, and §6.3 requires it to be marked as non-original evidence.
INFERENCE_FORBIDDEN_TYPES = frozenset(
    {EpistemicType.OBSERVED, EpistemicType.SIMULATED, EpistemicType.MEASURED}
)


class RefusalReason(StrEnum):
    """Why admission was refused. Machine-readable so tests assert state, not prose.

    Each member is a distinct guard. A test that could be satisfied by any of several reasons
    would pass when the wrong guard fired, which is how a gate keeps working while checking
    something other than what it is supposed to.
    """

    #: EVI-003
    INFERENCE_TYPED_AS_FACT = "INFERENCE_TYPED_AS_FACT"
    INFERENCE_PROVENANCE_MISSING = "INFERENCE_PROVENANCE_MISSING"
    #: EVI-003. The caller said "not LLM-derived" about a record whose own provenance says
    #: otherwise. Refused rather than reconciled -- see `_check_inference`.
    INFERENCE_FLAG_CONTRADICTS_PROVENANCE = "INFERENCE_FLAG_CONTRADICTS_PROVENANCE"
    #: EVI-009
    REFERENCE_MISSING = "REFERENCE_MISSING"
    REFERENCED_ARTIFACT_NOT_FOUND = "REFERENCED_ARTIFACT_NOT_FOUND"
    BACKFILL_REFUSED = "BACKFILL_REFUSED"
    #: EVI-002
    INVENTED_SCIENTIFIC_VALUE = "INVENTED_SCIENTIFIC_VALUE"
    #: EVI-010
    BASELINE_UNIT_NOT_ADMISSIBLE = "BASELINE_UNIT_NOT_ADMISSIBLE"
    EVIDENCE_UNIT_NOT_FOUND = "EVIDENCE_UNIT_NOT_FOUND"
    EVIDENCE_BODY_NOT_CANONICAL = "EVIDENCE_BODY_NOT_CANONICAL"
    #: EVI-010 / SPEC-ISSUE-015. Segmentation could not be re-run, or the unit is not among
    #: what it produces from the artifact's own bytes.
    SEGMENTATION_NOT_VERIFIABLE = "SEGMENTATION_NOT_VERIFIABLE"
    SEGMENTATION_NOT_REPRODUCIBLE = "SEGMENTATION_NOT_REPRODUCIBLE"
    #: §17.25 / `v3.3-a18`. The durable reference on the record disagrees with the one being
    #: submitted, or is absent while an evidence unit is claimed.
    EVIDENCE_LINK_NOT_DURABLE = "EVIDENCE_LINK_NOT_DURABLE"
    #: SEC-002
    CROSS_PROJECT_UNIT = "CROSS_PROJECT_UNIT"
    READ_NOT_PERMITTED = "READ_NOT_PERMITTED"


class AdmissionRefusal(Exception):
    """Admission was refused. Carries the reason code, not just a message."""

    def __init__(self, reason: RefusalReason, detail: str) -> None:
        super().__init__(f"{reason.value}: {detail}")
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class AdmissionRequest:
    """One candidate Attestation plus the evidence unit it claims to have come from.

    ``claimed_body`` is what the caller *says* the unit contains. It exists to be checked against
    the canonical unit and then discarded -- that comparison is EVI-010's "a tampered retrieval
    payload cannot alter the scientific evidence body", and without carrying the claim there is
    nothing to catch.
    """

    attestation: Attestation
    evidence_unit_id: str | None = None
    claimed_body: str | None = None
    #: What the CALLER says about the text's origin. **Not a source of truth** (EVI-003).
    #:
    #: Tri-state, and the third state is the point. ``None`` means *not asserted*; ``True`` and
    #: ``False`` are claims the caller is making. A plain ``bool`` defaulting to ``False`` cannot
    #: tell "this did not come from a model" apart from "nobody said", so an omission silently
    #: became a denial -- which is how the guard became opt-in for the one party who would never
    #: opt in.
    #:
    #: The gate derives inference status from the attestation's own
    #: ``extraction_provenance.inference_provenance_id``. This flag may only *widen* that: a
    #: caller volunteering LLM origin for a record whose provenance is silent is believed, because
    #: claiming a stricter classification is not an attack. Claiming the opposite is.
    llm_derived: bool | None = None


class EvidenceAdmissionGate:
    """Decides whether a record may enter the scientific evidence path.

    The resolvers are injected for the same reason the pipeline's are: this has to run against
    in-memory repositories and PostgreSQL, and the negative tests need to make a lookup fail
    without breaking a database.
    """

    def __init__(
        self,
        *,
        load_artifact: Callable[[str], Artifact | None],
        load_evidence_unit: Callable[[str], EvidenceUnit | None],
        already_admitted: Callable[[str], bool] | None = None,
        can_read: Callable[[str, str], bool] | None = None,
        resegment: Callable[[str], tuple[EvidenceUnit, ...] | None] | None = None,
        is_present_in: Callable[[str, str], bool] | None = None,
    ) -> None:
        self._load_artifact = load_artifact
        self._load_evidence_unit = load_evidence_unit
        self._already_admitted = already_admitted or (lambda _: False)
        #: SPEC-ISSUE-015's semantic layer. Given an artifact id, re-runs the recorded parser and
        #: segmenter over that artifact's content-addressed bytes and returns what segmentation
        #: produces, or ``None`` when the bytes cannot be loaded.
        #:
        #: Left unset, admission of any unit FAILS CLOSED rather than skipping the check. That is
        #: the whole point: a deployment that cannot re-derive cannot verify, and an unverifiable
        #: admission is exactly the hole the issue describes.
        self._resegment = resegment
        #: §17.25.1 presence. Replaces the old comparison against `EvidenceUnit.project_id`,
        #: which ADR-0012 removed -- presence is a property of the occurrence, not of the unit.
        self._is_present_in = is_present_in
        #: SEC-002. Injected rather than reimplemented: `lab_brain.core.access.can_read_artifact`
        #: is the gate, and a second copy of ACL logic here would be a second thing to keep in
        #: step with it. R-7's note that "nothing calls the gate" is what this parameter closes.
        self._can_read = can_read

    def admit(self, request: AdmissionRequest) -> Attestation:
        """Return the attestation if it may be admitted; raise ``AdmissionRefusal`` otherwise."""
        attestation = request.attestation

        self._check_backfill(attestation)
        self._check_inference(request)
        self._check_reference(attestation)
        unit = self._check_evidence_unit(request)
        self._check_no_invented_values(attestation)
        if unit is not None:
            self._check_durable_link(request, unit)
            self._check_read_permitted(attestation, unit)
            # Last, and deliberately: it is the only expensive check, so every cheap refusal has
            # already had its chance. Ordering does not change any verdict -- each guard is
            # independent -- only how much work a doomed admission costs.
            self._check_segmentation_reproducible(unit)
        return attestation

    # -- EVI-009 ------------------------------------------------------------

    def _check_reference(self, attestation: Attestation) -> None:
        """MEASURED/SIMULATED must name their Run or Artifact, and it must resolve.

        §25.3 is explicit that a record without the reference is refused *at admission* and MUST
        NOT be admitted first and back-filled later. Both halves are here: this method is the
        admission-time check, ``_check_backfill`` is the other.
        """
        if attestation.epistemic_type not in REFERENCE_REQUIRED_TYPES:
            return

        artifact_id = attestation.source_artifact_id
        run_id = attestation.run_id
        if artifact_id is None and run_id is None:
            raise AdmissionRefusal(
                RefusalReason.REFERENCE_MISSING,
                f"attestation {attestation.attestation_id} is typed "
                f"{attestation.epistemic_type} but references neither a Run nor an Artifact "
                "(EVI-009, §14.3). A measurement nobody can trace to what produced it is a "
                "number with a label",
            )

        if artifact_id is not None and self._load_artifact(artifact_id) is None:
            # Fail closed. A lookup that returned None because the store was unreachable and a
            # lookup that returned None because the artifact does not exist must both refuse --
            # treating "not found" as "probably fine" is how a missing artifact becomes an
            # admitted measurement.
            raise AdmissionRefusal(
                RefusalReason.REFERENCED_ARTIFACT_NOT_FOUND,
                f"attestation {attestation.attestation_id} references artifact {artifact_id}, "
                "which does not resolve. The reference must point at something that exists",
            )
        # A Run reference is recorded and not resolved: Run is OPS-001 and does not exist as an
        # entity yet (R-11). Resolving it would need a fake Run record, and inventing one to make
        # a test pass is exactly what this gate exists to prevent. Artifact-backed fixtures are
        # what M1-P1 admits; the Run half lands with OPS-001.

    def _check_backfill(self, attestation: Attestation) -> None:
        """An already-admitted record may not be re-submitted with a reference attached."""
        if self._already_admitted(attestation.attestation_id):
            raise AdmissionRefusal(
                RefusalReason.BACKFILL_REFUSED,
                f"attestation {attestation.attestation_id} is already admitted; re-admitting it "
                "with a reference attached is the back-fill EVI-009 forbids. Write a new "
                "attestation with its own provenance instead",
            )

    # -- EVI-003 ------------------------------------------------------------

    def _check_inference(self, request: AdmissionRequest) -> None:
        """An LLM's interpretation may never be typed as something that was observed.

        THE TRUST BOUNDARY, and the thing this method got wrong before: **inference status is
        derived from the record, not asserted by the caller.**

        The earlier shape returned early on ``not request.llm_derived``, which made the entire
        EVI-003 guard opt-in by whoever was submitting -- and the one party guaranteed not to
        volunteer "this came from a model" is the party laundering a model's output into the
        evidence path. A record carrying ``inference_provenance_id`` with the flag omitted sailed
        straight through and was admitted as MEASURED.

        So the canonical signal is ``extraction_provenance.inference_provenance_id``. Its presence
        *is* the record saying a model produced this; §17.14 makes it mandatory on every
        LLM-generated object, so a record that has one is inference-derived whatever the caller
        claims.

        The flag may only WIDEN, never narrow:

            provenance says inference, flag explicitly False -> refused (the attack)
            provenance says inference, flag not asserted     -> inference, by the record
            provenance silent, flag says inference           -> believed (volunteering strictness)
            both agree                                       -> obvious

        Row two is why the flag is tri-state. An omission is not a denial, so it does not raise a
        contradiction -- but it does not exempt the record either: it is still inference-derived,
        so a MEASURED one is refused by the type check below. Both refusals are real; they differ
        only in which defect they name, and naming the right one matters because an explicit
        ``False`` means a *producer* is lying while an omission usually means a caller forgot.

        Note what this still does NOT do: relabel. §26's fixture requires the record to be
        *refused*, not silently corrected to INFERRED -- a gate that repaired the type would admit
        the content under a different name and the caller would never learn that what it submitted
        was not evidence.
        """
        attestation = request.attestation
        canonical_inference = attestation.extraction_provenance.inference_provenance_id is not None

        # Refused before anything else, because the two disagreeing is itself the finding. A
        # caller that got this wrong may have got other things wrong, and silently preferring the
        # safe reading would hide a broken producer.
        if canonical_inference and request.llm_derived is False:
            raise AdmissionRefusal(
                RefusalReason.INFERENCE_FLAG_CONTRADICTS_PROVENANCE,
                f"attestation {attestation.attestation_id} carries "
                f"inference_provenance_id="
                f"{attestation.extraction_provenance.inference_provenance_id!r}, so its own "
                "provenance records that a model produced it, while the submitted request "
                "declares llm_derived=False. The record is authoritative and the claim is refused "
                "rather than reconciled: EVI-003 cannot be a guard the submitter opts out of",
            )

        is_inference = canonical_inference or bool(request.llm_derived)
        if not is_inference:
            return

        if attestation.epistemic_type in INFERENCE_FORBIDDEN_TYPES:
            raise AdmissionRefusal(
                RefusalReason.INFERENCE_TYPED_AS_FACT,
                f"attestation {attestation.attestation_id} is inference-derived and typed "
                f"{attestation.epistemic_type}; an inference cannot be admitted as observed, "
                "simulated or measured evidence (EVI-003, P3). It remains an inference with "
                "InferenceProvenance -- this is refused, not relabelled",
            )
        if not canonical_inference:
            raise AdmissionRefusal(
                RefusalReason.INFERENCE_PROVENANCE_MISSING,
                f"attestation {attestation.attestation_id} is declared LLM-derived but records no "
                "inference_provenance_id; an inference with no model/prompt/bundle provenance "
                "cannot be audited (LLM-001, AGT-010)",
            )

    # -- EVI-002 ------------------------------------------------------------

    def _check_no_invented_values(self, attestation: Attestation) -> None:
        """No field may carry a value its status says is absent.

        ``EvidenceField`` already refuses this at construction, and the check is repeated here on
        purpose: the model guards a record being *built*, this guards a record being *admitted*,
        and a record can reach admission from a database row that predates the validator.
        """
        offenders = [
            name
            for name, evidence_field in attestation.field_states.items()
            if evidence_field.status in {FieldStatus.UNKNOWN, FieldStatus.NOT_REPORTED}
            and evidence_field.value is not None
        ]
        if offenders:
            raise AdmissionRefusal(
                RefusalReason.INVENTED_SCIENTIFIC_VALUE,
                f"fields {sorted(offenders)} carry a value behind an absent status; a missing "
                "field is UNKNOWN or NOT_REPORTED and stays empty (EVI-002, P14)",
            )

    # -- EVI-010 ------------------------------------------------------------

    def _check_evidence_unit(self, request: AdmissionRequest) -> EvidenceUnit | None:
        """Re-resolve the canonical unit and refuse a body that is not the canonical one.

        THE attack this closes: retrieve a candidate, alter the payload the index handed back,
        and submit it. Every field is well-formed and the locator is real. The only thing that
        distinguishes it from a legitimate admission is that the body does not match the unit it
        claims to come from -- so the unit is re-loaded by identity and compared.
        """
        if request.evidence_unit_id is None:
            return None

        unit = self._load_evidence_unit(request.evidence_unit_id)
        if unit is None:
            raise AdmissionRefusal(
                RefusalReason.EVIDENCE_UNIT_NOT_FOUND,
                f"evidence unit {request.evidence_unit_id} does not resolve; a candidate that "
                "cannot be re-loaded by identity cannot become evidence (§6.22, EVI-010)",
            )

        if unit.subdivision_reason is SubdivisionReason.BENCHMARK_BASELINE:
            raise AdmissionRefusal(
                RefusalReason.BASELINE_UNIT_NOT_ADMISSIBLE,
                f"evidence unit {unit.evidence_unit_id} was produced by the fixed-token "
                "benchmark baseline (§6.22 rule 3(b)). Baseline units exist to be measured "
                "against, never to be admitted",
            )

        if request.claimed_body is not None and request.claimed_body != unit.body:
            raise AdmissionRefusal(
                RefusalReason.EVIDENCE_BODY_NOT_CANONICAL,
                f"the submitted body for {unit.evidence_unit_id} differs from the canonical "
                "evidence body. Retrieval supplies candidates; the evidence body is re-loaded "
                "from the canonical record and a retrieved payload never replaces it "
                "(§6.22, §17.25)",
            )
        return unit

    # -- SEC-002 ------------------------------------------------------------

    def _check_durable_link(self, request: AdmissionRequest, unit: EvidenceUnit) -> None:
        """The evidence reference must be ON THE RECORD, not only in the call (17.25, v3.3-a18).

        17.25 always required an Attestation citing an EvidenceUnit to record
        ``evidence_unit_id``. Implementing that as an admission-call parameter satisfied the
        sentence and not the requirement: persist the attestation, restart, reload it, and it can
        no longer say which passage it read. The locator does not close that gap -- a document
        routinely has several units at one human-facing position, which is exactly why
        ``structural_path`` is part of evidence identity and the locator is not.

        So an admission that names a unit must submit an attestation that names the same one.
        """
        attestation = request.attestation
        # NOT an independent guard, and the mutation battery says so: disabling this branch alone
        # survives, because `None != unit.evidence_unit_id` means the comparison below refuses
        # anyway. It is kept to name the defect precisely -- "records none" and "records a
        # different one" send an operator to different places -- and the battery therefore
        # anchors on the comparison, which is the part that actually holds the rule.
        if attestation.evidence_unit_id is None:
            raise AdmissionRefusal(
                RefusalReason.EVIDENCE_LINK_NOT_DURABLE,
                f"admission cites evidence unit {unit.evidence_unit_id} but attestation "
                f"{attestation.attestation_id} records no evidence_unit_id. The reference must be "
                "durable: a reloaded attestation that cannot name its evidence has lost the only "
                "precise route back to it (17.25, v3.3-a18)",
            )
        if attestation.evidence_unit_id != unit.evidence_unit_id:
            raise AdmissionRefusal(
                RefusalReason.EVIDENCE_LINK_NOT_DURABLE,
                f"attestation {attestation.attestation_id} records evidence unit "
                f"{attestation.evidence_unit_id} but admission cites {unit.evidence_unit_id}; "
                "the durable reference and the submitted one must be the same unit",
            )

    def _check_segmentation_reproducible(self, unit: EvidenceUnit) -> None:
        """The unit must be something the recorded segmenter actually produces (SPEC-ISSUE-015).

        THE HOLE THIS CLOSES. 6.22 rule 1 is enforced by a trigger that fires only when a unit
        *declares* a bound condition, so a raw writer skipped it by declaring nothing: a severed
        result with ``bound_condition_texts`` empty was a fully conformant canonical evidence unit
        whose interpreting condition existed nowhere.

        The answer is not to teach PostgreSQL to read prose -- v3.3-a13 refused exactly that for
        ``TransitionPolicy.evaluate``, because a second copy of the semantics in SQL is two
        definitions that drift. It is to re-derive: the artifact is content-addressed so its bytes
        are pinned, the segmenter is deterministic and its version is on the row, therefore "what
        would segmentation produce here" is computable, and a severed unit is not among the
        answers. Nothing has to understand what the text says.

        FAILS CLOSED in both directions -- no verifier configured, and bytes unavailable. An
        unverifiable admission is the hole, not a tolerable degradation of it.
        """
        if self._resegment is None:
            raise AdmissionRefusal(
                RefusalReason.SEGMENTATION_NOT_VERIFIABLE,
                f"evidence unit {unit.evidence_unit_id} cannot be verified: this gate has no "
                "re-segmentation path configured, so there is no way to establish that the unit "
                "came from a real segmentation rather than from a raw write. Refused rather than "
                "skipped (SPEC-ISSUE-015)",
            )

        produced = self._resegment(unit.artifact_id)
        if produced is None:
            raise AdmissionRefusal(
                RefusalReason.SEGMENTATION_NOT_VERIFIABLE,
                f"the bytes of artifact {unit.artifact_id} could not be loaded, so evidence unit "
                f"{unit.evidence_unit_id} cannot be re-derived. An admission that cannot be "
                "verified is refused",
            )

        match = next(
            (c for c in produced if c.evidence_unit_id == unit.evidence_unit_id),
            None,
        )
        if match is None:
            raise AdmissionRefusal(
                RefusalReason.SEGMENTATION_NOT_REPRODUCIBLE,
                f"evidence unit {unit.evidence_unit_id} is not among the {len(produced)} units "
                f"that {unit.provenance.segmenter_id} {unit.provenance.segmenter_version} "
                f"produces from artifact {unit.artifact_id}. It was written by something other "
                "than the segmentation path it claims, so 6.22's boundary rules never ran on it "
                "(SPEC-ISSUE-015)",
            )

        # Identity already pins artifact, path and body digest, so reaching here with a different
        # body is impossible. The bindings are the point: they are NOT part of identity, which is
        # precisely how a severed unit could carry a real id and an empty binding list.
        if match.bound_condition_texts != unit.bound_condition_texts:
            raise AdmissionRefusal(
                RefusalReason.SEGMENTATION_NOT_REPRODUCIBLE,
                f"evidence unit {unit.evidence_unit_id} records bound conditions "
                f"{list(unit.bound_condition_texts)} but segmentation produces "
                f"{list(match.bound_condition_texts)} for it. The stored bindings are not the "
                "ones the segmenter derived, so rule 1 was never enforced against this row",
            )
        if match.inherited_context != unit.inherited_context:
            raise AdmissionRefusal(
                RefusalReason.SEGMENTATION_NOT_REPRODUCIBLE,
                f"evidence unit {unit.evidence_unit_id} records inherited context that "
                "segmentation does not produce; rule 4's context could have been altered after "
                "the fact",
            )

    def _check_read_permitted(self, attestation: Attestation, unit: EvidenceUnit) -> None:
        """Project scope, enforced through the existing gates rather than a second copy.

        Presence first, through ``EvidenceUnitOccurrence`` (17.25.1). This used to compare
        ``unit.project_id``, which ADR-0012 removed: identity is derived from content and is
        project-independent, so the unit has no project to compare against and presence is a
        separate fact. Then ``can_read_artifact``, if the caller supplied it.
        """
        if self._is_present_in is not None and not self._is_present_in(
            unit.evidence_unit_id, attestation.project_id
        ):
            raise AdmissionRefusal(
                RefusalReason.CROSS_PROJECT_UNIT,
                f"evidence unit {unit.evidence_unit_id} has no occurrence in project "
                f"{attestation.project_id}; the evidence exists globally -- identity is shared -- "
                "but presence in one project grants nothing in another (SEC-002, R-7, 17.25.1)",
            )
        if self._can_read is not None and not self._can_read(
            unit.artifact_id, attestation.project_id
        ):
            raise AdmissionRefusal(
                RefusalReason.READ_NOT_PERMITTED,
                f"the requesting actor may not read {unit.artifact_id} in "
                f"{attestation.project_id} (SEC-002)",
            )


__all__ = [
    "INFERENCE_FORBIDDEN_TYPES",
    "REFERENCE_REQUIRED_TYPES",
    "AdmissionRefusal",
    "AdmissionRequest",
    "EvidenceAdmissionGate",
    "RefusalReason",
]
