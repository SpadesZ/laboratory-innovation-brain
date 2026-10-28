"""Separation of visibility: what the generator may see, and what only the evaluator holds.

An independent G0 evaluation has two packages with two schemas, and nothing converts one into the
other:

    generator package   `g0-eval/generator-package@1` -- case inputs ONLY: the question, the device
                        file, the evidence documents, the sources the run may use, the deployment's
                        unavailable capabilities, and provenance metadata (experimental unit,
                        source family, device family) that the contamination check reads and the
                        research run never receives
    sealed truth        `g0-eval/evaluator-truth@1` -- the rubric answers per case, each with its
                        own random salt. Held by the evaluator, outside the repository; the public
                        repository holds only its commitment (`sealing.py`)

THE GENERATOR LOADER FAILS CLOSED. `load_generator_package` refuses a file whose `kind` is not the
generator kind (an evaluator file named by mistake is refused by kind before a field is read), a
file or evidence path whose name marks it as evaluator material, any key anywhere -- including
inside the free-form device file -- that names a truth field, and any field outside the schema
(`extra="forbid"`, so a new field is refused until someone decides which side it belongs to).

THE RESEARCH INPUTS ARE A PROJECTION, NOT A FILTER. `research_inputs` builds the only object a run
receives from an allowlist of fields: the question, the merged device JSON, the evidence bytes, the
allowed sources and the unavailable capabilities. The case id and the provenance block are not in
it. `assert_no_truth` is the evaluator-side proof: given the sealed truth, it scans any set of
texts (the research inputs, the prompts a model was sent, rows persisted by the run) for every
secret string and refuses on a hit, exact or after whitespace/case normalisation.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

GENERATOR_KIND = "g0-eval/generator-package@1"
TRUTH_KIND = "g0-eval/evaluator-truth@1"
COMMITMENTS_KIND = "g0-eval/truth-commitments@1"

#: Keys that denote evaluator material. Refused anywhere in a generator package, at any depth.
TRUTH_KEYS = frozenset(
    {
        "truth",
        "ground_truth",
        "true_cause",
        "true_causes",
        "rationale",
        "expected_abnormal_observables",
        "decisive_cheap_checks",
        "design_sound",
        "salt",
        "answer",
        "answers",
        "rubric",
        "expected",
        "label",
        "labels",
        "verdict",
        "evaluator",
        "evaluator_notes",
    }
)

#: Truth fields whose VALUES are secret and must never reach a run (with the case ids). Values of
#: other truth fields -- observable or capability ids -- are vocabulary the platform itself uses in
#: every prompt, so finding them in a prompt is not evidence of a leak.
SECRET_TRUTH_FIELDS: tuple[str, ...] = ("true_causes", "rationale", "notes")
#: The part of the truth a correct run may state in its OUTPUT (the answer itself), and the part it
#: could not derive. Both must stay out of the INPUTS (`SECRET_TRUTH_FIELDS` is their union).
ANSWER_TRUTH_FIELDS: tuple[str, ...] = ("true_causes",)
PRIVATE_TRUTH_FIELDS: tuple[str, ...] = ("rationale", "notes")

_EVALUATOR_NAME = re.compile(r"(truth|evaluator|answer|rubric|seal)", re.IGNORECASE)


class VisibilityViolation(ValueError):
    """Evaluator material was offered where only generator material may be read."""


class TruthLeak(AssertionError):
    """A secret truth string was found in something the generator side produced or saw."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceRef(_Strict):
    name: str = Field(min_length=1)
    path: str = Field(min_length=1)


class Deployment(_Strict):
    unavailable: tuple[str, ...] = ()


class Provenance(_Strict):
    """Read by the contamination check only; never part of the research inputs."""

    unit_id: str = Field(min_length=1)
    source_family: str = Field(min_length=1)
    device_family: str = Field(min_length=1)


class GeneratorCase(_Strict):
    case_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    device: dict[str, Any] = Field(default_factory=dict)
    evidence: tuple[EvidenceRef, ...] = ()
    allowed_sources: tuple[str, ...] = ()
    deployment: Deployment = Deployment()
    provenance: Provenance


class GeneratorPackage(_Strict):
    kind: Literal["g0-eval/generator-package@1"]
    suite: str = Field(min_length=1)
    synthetic: bool
    nominal_device: dict[str, Any] = Field(default_factory=dict)
    cases: tuple[GeneratorCase, ...]


@dataclass(frozen=True)
class LoadedPackage:
    """A validated generator package and the evidence bytes it names, keyed by relative path."""

    path: Path
    package: GeneratorPackage
    evidence: Mapping[str, bytes]

    def case(self, case_id: str) -> GeneratorCase:
        for case in self.package.cases:
            if case.case_id == case_id:
                return case
        raise KeyError(case_id)


@dataclass(frozen=True)
class ResearchInputs:
    """Everything one research run receives for one case. No case id, no provenance, no truth."""

    question: str
    device_json: bytes
    evidence: tuple[tuple[str, bytes], ...]
    allowed_sources: tuple[str, ...]
    unavailable: tuple[str, ...]

    def texts(self) -> dict[str, str]:
        """Every text this object carries, labelled, for a leak scan."""
        out = {
            "question": self.question,
            "device_json": self.device_json.decode("utf-8", errors="replace"),
            "allowed_sources": "\n".join(self.allowed_sources),
            "unavailable": "\n".join(self.unavailable),
        }
        for name, body in self.evidence:
            out[f"evidence:{name}:name"] = name
            out[f"evidence:{name}"] = body.decode("utf-8", errors="replace")
        return out


def _truth_keys_in(value: Any, path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, inner in value.items():
            where = f"{path}.{key}"
            if str(key).lower() in TRUTH_KEYS:
                found.append(where)
            found.extend(_truth_keys_in(inner, where))
    elif isinstance(value, list | tuple):
        for i, inner in enumerate(value):
            found.extend(_truth_keys_in(inner, f"{path}[{i}]"))
    return found


def check_generator_document(data: Any, *, origin: str) -> GeneratorPackage:
    """Validate a parsed generator document, refusing evaluator material before the schema."""
    if not isinstance(data, Mapping):
        raise VisibilityViolation(f"{origin}: not a JSON object")
    kind = data.get("kind")
    if kind in (TRUTH_KIND, COMMITMENTS_KIND):
        raise VisibilityViolation(f"{origin}: evaluator material ({kind}) offered to the generator")
    if kind != GENERATOR_KIND:
        raise VisibilityViolation(f"{origin}: kind {kind!r} is not {GENERATOR_KIND}")
    leaked = _truth_keys_in(data)
    if leaked:
        raise VisibilityViolation(f"{origin}: truth fields in a generator package: {leaked}")
    return GeneratorPackage.model_validate(dict(data))


def load_generator_package(path: Path) -> LoadedPackage:
    """Load a generator package and its evidence; refuse anything that is evaluator material."""
    if _EVALUATOR_NAME.search(path.name):
        raise VisibilityViolation(f"{path.name}: the file name marks evaluator material")
    package = check_generator_document(
        json.loads(path.read_text(encoding="utf-8")), origin=path.name
    )
    base = path.resolve().parent
    evidence: dict[str, bytes] = {}
    seen: set[str] = set()
    for case in package.cases:
        if case.case_id in seen:
            raise VisibilityViolation(f"duplicate case id {case.case_id}")
        seen.add(case.case_id)
        for ref in case.evidence:
            target = (base / ref.path).resolve()
            if not target.is_relative_to(base):
                raise VisibilityViolation(f"{ref.path}: evidence outside the package directory")
            if _EVALUATOR_NAME.search(ref.path) or _EVALUATOR_NAME.search(ref.name):
                raise VisibilityViolation(f"{ref.path}: the name marks evaluator material")
            body = target.read_bytes()
            _refuse_evaluator_json(body, ref.path)
            evidence[ref.path] = body
    return LoadedPackage(path=path, package=package, evidence=evidence)


def _refuse_evaluator_json(body: bytes, origin: str) -> None:
    try:
        parsed = json.loads(body)
    except ValueError:
        return
    if isinstance(parsed, Mapping) and parsed.get("kind") in (TRUTH_KIND, COMMITMENTS_KIND):
        raise VisibilityViolation(f"{origin}: an evidence file is evaluator material")


def merged_device(loaded: LoadedPackage, case: GeneratorCase) -> dict[str, Any]:
    return {**loaded.package.nominal_device, **case.device}


def research_inputs(loaded: LoadedPackage, case_id: str) -> ResearchInputs:
    """The allowlisted projection of one case: what a research run is given, and nothing else."""
    case = loaded.case(case_id)
    return ResearchInputs(
        question=case.question,
        device_json=json.dumps(merged_device(loaded, case), sort_keys=True).encode(),
        evidence=tuple((ref.name, loaded.evidence[ref.path]) for ref in case.evidence),
        allowed_sources=case.allowed_sources,
        unavailable=case.deployment.unavailable,
    )


def string_leaves(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for inner in value.values():
            yield from string_leaves(inner)
    elif isinstance(value, list | tuple):
        for inner in value:
            yield from string_leaves(inner)


def truth_strings(
    truth_cases: Mapping[str, Mapping[str, Any]],
    *,
    fields: Sequence[str] = SECRET_TRUTH_FIELDS,
    min_length: int = 6,
) -> list[str]:
    """What must never reach a run: every case id, and every string under a secret truth field.

    `truth_cases` maps case id -> the case's truth object (salts excluded: a salt is random and
    reaching a prompt would be a curiosity, not a leak of an answer).
    """
    out: set[str] = set(truth_cases)
    for truth in truth_cases.values():
        for field in fields:
            out.update(string_leaves(truth.get(field)))
    return sorted(s for s in out if len(s) >= min_length)


def normalize_text(text: str) -> str:
    """Lowercase, every run of non-alphanumerics collapsed to one space."""
    return " ".join(re.sub(r"[^0-9a-z]+", " ", text.lower()).split())


#: Secrets with fewer words than this are matched exactly only (see `find_truth`).
NORMALISED_MIN_WORDS = 3


def find_truth(texts: Mapping[str, str], forbidden: Sequence[str]) -> list[tuple[str, int]]:
    """(text label, index into `forbidden`) for every secret found, exact or normalised.

    The normalised match (case, punctuation and line breaks ignored) applies to secrets of at least
    `NORMALISED_MIN_WORDS` words -- a sentence such as a rationale, or a multi-part case id. A short
    identifier such as a cause key matches exactly only: its words ("contact discontinuity") are
    the platform's own catalog vocabulary and appear in prompts by design.

    Returns indices rather than the strings so a report of a leak does not itself republish it.
    """
    hits: list[tuple[str, int]] = []
    normalized = [
        n if len(n.split()) >= NORMALISED_MIN_WORDS else ""
        for n in (normalize_text(s) for s in forbidden)
    ]
    for label, text in texts.items():
        folded = f" {normalize_text(text)} "
        for i, secret in enumerate(forbidden):
            if secret in text or (normalized[i] and f" {normalized[i]} " in folded):
                hits.append((label, i))
    return hits


def assert_no_truth(texts: Mapping[str, str], forbidden: Sequence[str]) -> None:
    """Fail closed: raise `TruthLeak` naming where (never what) a secret was found."""
    if not forbidden:
        raise TruthLeak("no secret strings to scan for: refusing to call an empty scan a pass")
    hits = find_truth(texts, forbidden)
    if hits:
        raise TruthLeak(f"truth reached the generator side at {sorted({h[0] for h in hits})}")
