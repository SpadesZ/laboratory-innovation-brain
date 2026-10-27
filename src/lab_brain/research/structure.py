"""A device structure summary: what the verification input DECLARES about the device, for reasoning.

THE QUESTION IT ANSWERS (G0 secondary investigation). A model shown only a measurement report
cannot propose a mechanism the report never hints at; the design file that would hint at it was
deliberately kept from the model, so no answer could leak. Some of that file is legitimate context
a scientist would read -- the drawn length, the contacts and their regions, the doping -- and none
of it is a verdict. This is that part, typed, with exact source links, so its effect on research
can be measured on its own (separately from exploratory screening, never conflated with it).

WHAT IT IS, AND WHAT IT IS NOT.

    is       design-declared fields of the user's verification input, each with its JSON pointer
             into the stored artifact, the artifact's content hash, its unit, and the uncertainty
             that comes with any as-drawn value
    is not   an inspection or a measurement: no rule is applied, no outcome of any OutcomeSpace is
             named, nothing says CONTINUOUS or DISCONTINUOUS. A reader that wants to know whether a
             contact is connected still has to run the check
    is not   evidence: it is never an Attestation, never a citable grounding id, never a basis for
             any relation. A Hypothesis Engine context carries it beside the evidence, labelled so

LEAK GUARD. A summary is built by its DomainPack from the PARSED input model (which forbids unknown
fields), from an explicit allowlist of fields; `check_no_concealed_fields` then refuses any entry
whose path or label names something that reads as an answer -- a truth, a label, an expected
result, a root cause, a verdict. Benchmark files keep those beside the device, never in it; this is
the second line if one ever slips in.

ACCESS. Built only by the research service, only from the verification input THIS run stored in
THIS project, and shown only in that run's model calls -- the same project, classification and
egress decision as the run's evidence. A deployment enables it explicitly; it is off by default.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from lab_brain.core.canonical_json import canonical_hash
from lab_brain.core.models.base import CoreModel

#: Words that would make a field an answer rather than a description. Matched against each entry's
#: path segments and label, case-insensitively, as whole words.
CONCEALED_WORDS = frozenset(
    {
        "truth",
        "label",
        "expected",
        "answer",
        "verdict",
        "cause",
        "root_cause",
        "diagnosis",
        "fault",
        "defect",
        "outcome",
        "note",
        "benchmark",
    }
)

STRUCTURE_NOTE = (
    "Design-declared fields of the device project under study, as drawn in the stored file. They "
    "are not measurements and not inspection results: no rule has been applied to them and no "
    "outcome is implied. Fabricated devices may differ from the drawing. These entries are not "
    "evidence and cannot be cited as grounding; cite only CONTEXT.evidence ids."
)


class StructureEntry(CoreModel):
    #: JSON pointer into the source artifact, e.g. `/contacts/1/via_to_metal`.
    path: str = Field(pattern=r"^(/[A-Za-z0-9_]+)+$")
    #: What the field is, in the domain's words.
    label: str
    #: The value as written in the source, verbatim as text.
    value: str
    unit: str | None = None
    kind: Literal["DESIGN_DECLARED"] = "DESIGN_DECLARED"


class StructureSummary(CoreModel):
    summary_ref: str
    project_id: str
    source_artifact_id: str
    entries: tuple[StructureEntry, ...] = Field(min_length=1)
    #: Source fields deliberately left out, each with the reason (e.g. a mock-solver switch).
    excluded_fields: tuple[str, ...] = ()
    uncertainty: str

    @property
    def digest(self) -> str:
        return canonical_hash(self.model_dump(mode="json"))

    @model_validator(mode="after")
    def _no_answers(self) -> Self:
        check_no_concealed_fields(self.entries)
        return self

    def as_context(self) -> dict[str, object]:
        """The summary as a Hypothesis Engine is shown it: S1, S2, ... per entry."""
        return {
            "kind": "DESIGN_DECLARED",
            "note": STRUCTURE_NOTE,
            "summary_ref": self.summary_ref,
            "source": {"artifact_id": self.source_artifact_id},
            "uncertainty": self.uncertainty,
            "entries": [
                {
                    "ref": f"S{n}",
                    "field": e.path,
                    "label": e.label,
                    "value": e.value,
                    **({"unit": e.unit} if e.unit else {}),
                }
                for n, e in enumerate(self.entries, start=1)
            ],
            "digest": self.digest,
        }


class ConcealedField(ValueError):
    """A structure entry names something that reads as an answer, not a description."""


def check_no_concealed_fields(entries: tuple[StructureEntry, ...]) -> None:
    for entry in entries:
        words = {
            w for segment in entry.path.strip("/").split("/") for w in segment.lower().split("_")
        }
        words |= set(entry.path.strip("/").lower().split("/"))
        words |= set("".join(c if c.isalnum() else " " for c in entry.label.lower()).split())
        found = sorted(words & CONCEALED_WORDS)
        if found:
            raise ConcealedField(
                f"structure entry {entry.path} ({entry.label!r}) names {found}; a structure "
                "summary describes the device as drawn and never carries an answer"
            )


__all__ = [
    "CONCEALED_WORDS",
    "STRUCTURE_NOTE",
    "ConcealedField",
    "StructureEntry",
    "StructureSummary",
    "check_no_concealed_fields",
]
