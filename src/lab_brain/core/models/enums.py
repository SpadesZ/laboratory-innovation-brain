"""Closed vocabularies for the core scientific state path.

Every enum here is a *scientific or governance* vocabulary, so none of them may gain a
domain-specific member. Nothing in this module mentions Cj, Rs, mesh, CHARGE or a wavelength
(§24.1); a DomainPack expresses those through condition schemas and validators instead.
"""

from __future__ import annotations

from enum import StrEnum


class ActorType(StrEnum):
    """§14.4's minimum Actor model: no governance without "who".

    AGENT_ROLE is a first-class actor rather than a flag on a human. An agent acting under a
    delegated role must be attributable in its own right, or every action it takes is recorded
    against whoever configured it.
    """

    HUMAN = "HUMAN"
    SERVICE = "SERVICE"
    AGENT_ROLE = "AGENT_ROLE"


class SensitivityLabel(StrEnum):
    """§14.1. Ordered most-restrictive first so fail-closed defaults are unambiguous."""

    RESTRICTED_NDA = "RESTRICTED_NDA"
    CONFIDENTIAL_LAB = "CONFIDENTIAL_LAB"
    INTERNAL = "INTERNAL"
    PUBLIC = "PUBLIC"


#: P28 / SEC-002: unclassified data is treated as the strictest label, never the loosest.
#: In M0a `Artifact.sensitivity_label` is a required field, so this cannot be applied
#: implicitly by construction; the admission gate applies it in M1.
FAIL_CLOSED_SENSITIVITY = SensitivityLabel.RESTRICTED_NDA


class SourceOrigin(StrEnum):
    """Where an Artifact entered the system from."""

    UPLOAD = "UPLOAD"
    WATCHER_FILESYSTEM = "WATCHER_FILESYSTEM"
    WATCHER_GIT = "WATCHER_GIT"
    RUN_OUTPUT = "RUN_OUTPUT"
    EXTERNAL_CONNECTOR = "EXTERNAL_CONNECTOR"
    DERIVED = "DERIVED"


class SecretScanStatus(StrEnum):
    """SEC-003. An artifact reaches durable storage only after this is resolved."""

    PENDING = "PENDING"
    CLEAN = "CLEAN"
    QUARANTINED = "QUARANTINED"
    REDACTED = "REDACTED"
    SCAN_FAILED = "SCAN_FAILED"


class LicenseClass(StrEnum):
    """SEC-004. UNKNOWN and COPYLEFT are blocked from code-generation context by policy."""

    PERMISSIVE = "PERMISSIVE"
    COPYLEFT = "COPYLEFT"
    PROPRIETARY = "PROPRIETARY"
    UNKNOWN = "UNKNOWN"


class EpistemicType(StrEnum):
    """EVI-003 / P3. The single most important distinction in the system.

    ``INFERRED`` can never be promoted to ``OBSERVED``/``SIMULATED``/``MEASURED``. An LLM
    interpretation stays an inference forever, no matter how often it is cited. Without that
    asymmetry the store fills with self-citations that read as established fact months later.
    """

    OBSERVED = "OBSERVED"
    SIMULATED = "SIMULATED"
    MEASURED = "MEASURED"
    REPORTED = "REPORTED"
    DERIVED = "DERIVED"
    INFERRED = "INFERRED"


#: Epistemic types that may back a factual evidence claim. `INFERRED` is deliberately absent.
FACTUAL_EPISTEMIC_TYPES = frozenset(
    {
        EpistemicType.OBSERVED,
        EpistemicType.SIMULATED,
        EpistemicType.MEASURED,
        EpistemicType.REPORTED,
        EpistemicType.DERIVED,
    }
)


class FieldStatus(StrEnum):
    """§6.3 / §17.9. Per-field status, not one confidence score for a whole record.

    ``UNKNOWN`` and ``NOT_REPORTED`` are the load-bearing members: they are what an extractor
    emits instead of guessing a plausible value (P14 / EVI-002).
    """

    EXPLICIT = "EXPLICIT"
    DERIVED = "DERIVED"
    VERIFIED_DERIVED = "VERIFIED_DERIVED"
    INFERRED = "INFERRED"
    UNKNOWN = "UNKNOWN"
    NOT_REPORTED = "NOT_REPORTED"
    REFERENCED_EXTERNALLY = "REFERENCED_EXTERNALLY"
    CONFLICTING = "CONFLICTING"


#: §6.3: only these may carry high weight in condition filtering. `INFERRED` must be marked
#: as non-original evidence and must not reach this set.
HIGH_WEIGHT_FIELD_STATUSES = frozenset({FieldStatus.EXPLICIT, FieldStatus.VERIFIED_DERIVED})


class ExtractionStatus(StrEnum):
    """§6.4 progressive enrichment. Stages must be able to stop and stay stopped."""

    STAGE_A_METADATA = "STAGE_A_METADATA"
    STAGE_B_STRUCTURED = "STAGE_B_STRUCTURED"
    STAGE_C_DEEP = "STAGE_C_DEEP"
    STAGE_D_HUMAN_VERIFIED = "STAGE_D_HUMAN_VERIFIED"


class VerificationStatus(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    MACHINE_CHECKED = "MACHINE_CHECKED"
    HUMAN_VERIFIED = "HUMAN_VERIFIED"
    DISPUTED = "DISPUTED"


class ClaimIdentityStatus(StrEnum):
    """P22. Identity is resolved before corroboration is counted, never after."""

    PROVISIONAL = "PROVISIONAL"
    RESOLVED = "RESOLVED"
    MERGED = "MERGED"
    DISPUTED = "DISPUTED"


class SourceWorkType(StrEnum):
    JOURNAL_ARTICLE = "JOURNAL_ARTICLE"
    PREPRINT = "PREPRINT"
    CONFERENCE_PAPER = "CONFERENCE_PAPER"
    THESIS = "THESIS"
    PATENT = "PATENT"
    TECHNICAL_REPORT = "TECHNICAL_REPORT"
    SOFTWARE_REPOSITORY = "SOFTWARE_REPOSITORY"
    DATASET = "DATASET"
    WEB_PAGE = "WEB_PAGE"
    INTERNAL_DOCUMENT = "INTERNAL_DOCUMENT"


class SourceWorkStatus(StrEnum):
    """EVI-008. The check result is recorded even when it is UNKNOWN."""

    ACTIVE = "ACTIVE"
    RETRACTED = "RETRACTED"
    ERRATUM_ISSUED = "ERRATUM_ISSUED"
    WITHDRAWN = "WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"
    UNKNOWN = "UNKNOWN"
    SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"


class TrustClass(StrEnum):
    """§6.5. A ranking of source *kinds*, not of evidence strength.

    Evidence strength is `AuthorityPolicy.compare` and is domain-supplied (ADR-0007). This is
    only about what kind of thing produced the record.
    """

    INTERNAL_RUN = "INTERNAL_RUN"
    INTERNAL_MEASUREMENT = "INTERNAL_MEASUREMENT"
    PEER_REVIEWED = "PEER_REVIEWED"
    PREPRINT = "PREPRINT"
    PATENT = "PATENT"
    TECHNICAL_ARTIFACT = "TECHNICAL_ARTIFACT"
    WEB = "WEB"
    EXPERT_HEURISTIC = "EXPERT_HEURISTIC"


class RelationType(StrEnum):
    """§17.8. The only place support/contradiction semantics may live.

    No entity carries an `evidence_for[]` or `support_targets[]` array. A parallel array would
    be a second, unversioned source of truth that nothing keeps in step with the relation
    table -- and the two would disagree silently (SYS-001).
    """

    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    TESTS = "TESTS"
    PREDICTS = "PREDICTS"
    PRODUCES = "PRODUCES"
    DERIVED_FROM = "DERIVED_FROM"
    INSTANTIATES = "INSTANTIATES"
    SUPERSEDES = "SUPERSEDES"
    SAME_WORK_AS = "SAME_WORK_AS"
    CITES = "CITES"
    SUGGESTS_CHECK = "SUGGESTS_CHECK"


class IndependenceRelation(StrEnum):
    """§6.17. ``UNKNOWN`` contributes 0 to independent-attestation counts (EVI-004).

    v3.3 models WORK-level independence only. Same-group / same-wafer / same-instrument
    correlation is DEFERRED, and a policy needing it must escalate to human review rather than
    assume independence.
    """

    INDEPENDENT = "INDEPENDENT"
    DERIVED_FROM = "DERIVED_FROM"
    SAME_WORK = "SAME_WORK"
    CITES = "CITES"
    UNKNOWN = "UNKNOWN"


class IndependenceBasis(StrEnum):
    """§8.2.1 ``independence_basis`` domain. Only WORK is implemented in v3.3."""

    WORK = "WORK"
    GROUP = "GROUP"
    SAMPLE = "SAMPLE"
    INSTRUMENT = "INSTRUMENT"
    METHOD = "METHOD"


#: Bases a TransitionPolicy may actually rely on. Declaring anything else MUST yield
#: NEED_HUMAN_REVIEW rather than pretending the requirement is met (§6.17).
IMPLEMENTED_INDEPENDENCE_BASES = frozenset({IndependenceBasis.WORK})


class AuthorityComparison(StrEnum):
    """§10.5.1. Evidence authority is a **partial** order.

    ``INCOMPARABLE`` is a legitimate result and MUST NOT be silently coerced into an ordering: a
    calibrated measurement outside its validated range and a simulation inside its own genuinely do
    not rank, and a comparator that returned WEAKER there would be inventing the ranking a belief
    transition then rests on. §8.2.1 routes it to NEED_HUMAN_REVIEW.
    """

    STRONGER = "STRONGER"
    WEAKER = "WEAKER"
    EQUIVALENT = "EQUIVALENT"
    INCOMPARABLE = "INCOMPARABLE"


class EvidenceUnitType(StrEnum):
    """§6.22 / §17.25. What kind of document structure a canonical evidence unit came from.

    Structural, never domain-specific: a unit is a TABLE because the document had a table there,
    not because it holds capacitance. §24.1 keeps the core free of Cj, Rs and wavelengths, and this
    vocabulary is one of the places that rule is easy to break by accident.

    ``PROSE`` rather than ``PARAGRAPH``: §6.22's boundary rule routinely binds two adjacent
    sentences that a parser would emit as separate paragraphs, so the unit is the semantic block,
    not the layout element.
    """

    SECTION = "SECTION"
    PROSE = "PROSE"
    TABLE = "TABLE"
    FIGURE = "FIGURE"
    CODE = "CODE"
    LOG = "LOG"


class SubdivisionReason(StrEnum):
    """§6.22 rule 3. Why a unit was cut by token count rather than by structure.

    The vocabulary is closed and has two members, which is the point: fixed-token splitting is
    permitted for exactly two reasons and a record has to name which. An open reason string would
    let "chunked for retrieval" be written into the same field and read as compliant.
    """

    #: 3(a): one valid evidence unit exceeded the declared safety/token limit.
    OVERSIZED_UNIT = "OVERSIZED_UNIT"
    #: 3(b): produced deliberately as the T-EVI-010 comparison baseline. Never admitted.
    BENCHMARK_BASELINE = "BENCHMARK_BASELINE"


class RetrievalIndexKind(StrEnum):
    """§17.25. How a retrieval index finds candidates.

    ``DENSE`` and ``HYBRID`` are declared now and unused: EVI-007's vector index is a later slice.
    They are here so the seam's shape is fixed before something is plugged into it, rather than
    the enum growing to fit whatever arrives.
    """

    LEXICAL = "LEXICAL"
    DENSE = "DENSE"
    HYBRID = "HYBRID"


class ConditionMatchState(StrEnum):
    """§17.19. ``UNKNOWN`` is distinct from ``INCOMPATIBLE`` on purpose.

    "We cannot tell whether these conditions are comparable" and "these conditions are not
    comparable" lead to different gate outcomes; collapsing them loses the escalation signal.
    """

    EXACT = "EXACT"
    COMPATIBLE = "COMPATIBLE"
    PARTIAL = "PARTIAL"
    INCOMPATIBLE = "INCOMPATIBLE"
    UNKNOWN = "UNKNOWN"


__all__ = [
    "FACTUAL_EPISTEMIC_TYPES",
    "FAIL_CLOSED_SENSITIVITY",
    "HIGH_WEIGHT_FIELD_STATUSES",
    "IMPLEMENTED_INDEPENDENCE_BASES",
    "AuthorityComparison",
    "ClaimIdentityStatus",
    "ConditionMatchState",
    "EpistemicType",
    "EvidenceUnitType",
    "ExtractionStatus",
    "FieldStatus",
    "IndependenceBasis",
    "IndependenceRelation",
    "LicenseClass",
    "RelationType",
    "RetrievalIndexKind",
    "SecretScanStatus",
    "SensitivityLabel",
    "SourceOrigin",
    "SourceWorkStatus",
    "SourceWorkType",
    "SubdivisionReason",
    "TrustClass",
    "VerificationStatus",
]
