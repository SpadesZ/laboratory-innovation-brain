"""§7.6's adjudication: what a critique must cite to have been settled by evidence (SRC-002).

    §7.6     重大 REJECT / irreversible action 必須經 independent critique path: ... 並由 external
             evidence / verification adjudicate。
    SRC-002  adjudication 引用 external evidence 或 verification result，不得由另一次
             model opinion 裁定。
    EVI-003  INFERRED can never be promoted to OBSERVED / SIMULATED / MEASURED.

CITING SOMETHING IS NOT BEING SETTLED BY IT. A CritiqueReport names attestation ids; that it names
any is a fact about the critique, not about the evidence. An `INFERRED` attestation is a model's
interpretation recorded as such (EVI-003), so a critique adjudicated by one was settled by another
model opinion -- the circularity §7.6 exists to refuse. So the adjudication basis is read from the
DURABLE attestations the critique cites, never from the critique's say-so or from objects a caller
hands in, and it fails closed:

    a cited id that does not resolve    refused -- in the critique's project, a citation to nothing
      in the project                    (or to another project's evidence, SEC-002) proves nothing,
                                        and ignoring it would let a critique pad itself with ghosts
    INFERRED                            excluded -- a model's reading is not external evidence
    DISPUTED                            excluded -- evidence whose own standing is contested cannot
                                        settle a contest
    nothing admissible left             MODEL_OPINION, which `core.critique_gate` refuses

and what remains decides the adjudicator: VERIFICATION_RESULT when an admissible attestation is the
witness of a Run (a verification action's output, §17.2's `run_id` source), EXTERNAL_EVIDENCE
otherwise. `FACTUAL_EPISTEMIC_TYPES` is the one definition of "not an inference" -- the same set the
belief-revision gate reads -- so the two §7.6 triggers cannot disagree about what counts. `011j`'s
deferred constraint trigger states the same exclusions in SQL for the belief path.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from lab_brain.core.critique_gate import Adjudicator
from lab_brain.core.models.attestation import Attestation
from lab_brain.core.models.enums import FACTUAL_EPISTEMIC_TYPES, VerificationStatus

#: (project_id, attestation_id) -> the durable attestation, read in that project only.
AttestationLookup = Callable[[str, str], Attestation | None]


class AdjudicationBasisRefused(ValueError):
    """A critique cites evidence that does not resolve durably in its project."""


def inadmissibility(attestation: Attestation) -> str | None:
    """Why ``attestation`` cannot adjudicate under §7.6, or ``None`` when it can."""
    if attestation.epistemic_type not in FACTUAL_EPISTEMIC_TYPES:
        return (
            f"{attestation.attestation_id} is {attestation.epistemic_type.value}: a model's "
            "interpretation is another opinion, not external evidence (EVI-003)"
        )
    if attestation.verification_status == VerificationStatus.DISPUTED:
        return (
            f"{attestation.attestation_id} is DISPUTED: evidence whose own standing is contested "
            "cannot settle a contest"
        )
    return None


def admissible(attestations: Iterable[Attestation]) -> tuple[Attestation, ...]:
    """The attestations that may adjudicate, in the order given."""
    return tuple(a for a in attestations if inadmissibility(a) is None)


@dataclass(frozen=True)
class AdjudicationBasis:
    """What a critique's citations amount to, once each one is read from the record."""

    admissible: tuple[Attestation, ...]
    #: (attestation_id, why it cannot adjudicate)
    excluded: tuple[tuple[str, str], ...]

    @property
    def adjudicator(self) -> Adjudicator:
        if any(a.run_id is not None for a in self.admissible):
            return Adjudicator.VERIFICATION_RESULT
        if self.admissible:
            return Adjudicator.EXTERNAL_EVIDENCE
        return Adjudicator.MODEL_OPINION

    def describe(self) -> str:
        kept = ", ".join(a.attestation_id for a in self.admissible) or "none"
        dropped = "; ".join(reason for _, reason in self.excluded) or "none"
        return f"admissible: {kept}; excluded: {dropped}"


def resolve_adjudication_basis(
    cited_attestation_ids: Iterable[str],
    *,
    project_id: str,
    attestations: AttestationLookup,
) -> AdjudicationBasis:
    """Read every cited attestation from the record in ``project_id`` and classify it.

    Raises `AdjudicationBasisRefused` for a citation that does not resolve there -- fail closed:
    a critique that cites a ghost is not a critique whose remaining citations can be trusted.
    """
    kept: list[Attestation] = []
    excluded: list[tuple[str, str]] = []
    # Sorted: the record, and the refusal on the first ghost, must not depend on set order.
    for attestation_id in sorted(set(cited_attestation_ids)):
        found = attestations(project_id, attestation_id)
        if found is None or found.project_id != project_id:
            raise AdjudicationBasisRefused(
                f"the critique cites {attestation_id}, which is not an attestation of project "
                f"{project_id}. §7.6's adjudication must be evidence on record; a citation "
                "that resolves to nothing -- or to another project's evidence (SEC-002) -- proves "
                "nothing"
            )
        reason = inadmissibility(found)
        if reason is None:
            kept.append(found)
        else:
            excluded.append((attestation_id, reason))
    return AdjudicationBasis(admissible=tuple(kept), excluded=tuple(excluded))


__all__ = [
    "AdjudicationBasis",
    "AdjudicationBasisRefused",
    "AttestationLookup",
    "admissible",
    "inadmissibility",
    "resolve_adjudication_basis",
]
